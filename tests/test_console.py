"""The presentation layer must never become an execution or filesystem gateway."""
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from aletheia.console import create_console, reader
from aletheia.cli import main


def client(root, *, demo=False, token=None, host='localhost'):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_console(root, demo=demo, token=token)), base_url='http://' + host)


async def test_empty_workspace_does_not_create_state(tmp_path):
    async with client(tmp_path) as http:
        response = await http.get('/api/workspace')
        assert response.status_code == 200
        assert response.json()['stats']['total'] == 0
        assert response.json()['mode'] == 'local'
        assert (await http.get('/')).status_code == 200
    assert not (tmp_path / '.aletheia').exists()


async def test_demo_never_reads_project_files(tmp_path):
    (tmp_path / 'aletheia.json').write_text('not json')
    (tmp_path / '.aletheia').symlink_to('/not/a/real/path')
    async with client(tmp_path, demo=True, host='8040-preview.e2b.app') as http:
        data = (await http.get('/api/workspace')).json()
        assert data['mode'] == 'demo' and data['stats']['total'] == 8
        task = (await http.get('/api/tasks/' + data['tasks'][0]['id'])).json()
        cp = task['checkpoints'][0]
        contents = (await http.get(f"/api/tasks/{task['task']['id']}/checkpoints/{cp['id']}", params={'file':'src/runtime.py'})).json()
        assert 'Illustrative checkpoint' in contents['preview']
        assert (await http.get('/api/tasks/not-a-task')).status_code == 404
        assert (await http.get(f"/api/tasks/missing/checkpoints/{cp['id']}")).status_code == 404


async def test_real_state_is_read_only_and_summary_counts_are_truthful(setup_runtime, monkeypatch):
    config, store, project, _ = setup_runtime
    config.save(project.root)
    task = store.create('Check evidence', 'native-model')
    store.event(task['id'], 'observe', 'task.started', {'adapter':'codex'})
    store.event(task['id'], 'verify', 'verification.result', {'status':'failed','commands':[]}, state='recovering')
    store.event(task['id'], 'verify', 'verification.result', {'status':'passed','commands':[]})
    store.event(task['id'], 'observe', 'task.finished', {'state':'verified_complete'}, state='verified_complete')
    project.snapshot(task['id'], 'baseline')
    before = store.trace()
    import subprocess
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('console must not execute commands'))
    async with client(project.root) as http:
        data = (await http.get('/api/workspace')).json()
        assert data['stats'] == {'total':1,'verified':1,'active':0,'failed':0,'caught':1,'checkpoints':1}
        assert data['tasks'][0]['adapter'] == 'codex'
        assert data['tasks'][0]['verification_count'] == 2
        detail = (await http.get('/api/tasks/' + task['id'])).json()
        assert len(detail['events']) == len(before['events'])
        assert not detail['events_truncated']
        assert (await http.post('/api/tasks/' + task['id'], json={'state':'verified_complete'})).status_code == 405
    assert before == store.trace()


async def test_database_query_only_is_enforced(setup_runtime):
    _, _, project, _ = setup_runtime
    with pytest.raises(HTTPException):
        with reader(project.root) as db:
            db.execute('CREATE TABLE forbidden(id INTEGER)')


@pytest.mark.parametrize('host', ['preview.e2b.app','evil.test'])
async def test_real_nonloopback_needs_auth(tmp_path, host):
    async with client(tmp_path, host=host) as http:
        assert (await http.get('/')).status_code == 200  # Generic shell, no private evidence.
        assert (await http.get('/api/workspace')).status_code == 403
    async with client(tmp_path, host=host, token='console-test-token') as http:
        assert (await http.get('/api/workspace')).status_code == 401
        assert (await http.get('/api/workspace', headers={'Authorization':'Bearer wrong'})).status_code == 401
        assert (await http.get('/api/workspace', headers={'Authorization':'Bearer console-test-token'})).status_code == 200


async def test_origin_boundary_and_csp(tmp_path):
    async with client(tmp_path) as http:
        assert (await http.get('/api/workspace', headers={'Origin':'https://malicious.example'})).status_code == 403
        assert (await http.get('/api/workspace', headers={'Sec-Fetch-Site':'cross-site'})).status_code == 403
        assert (await http.get('/api/workspace', headers={'Origin':'http://localhost'})).status_code == 200
        response = await http.get('/')
        assert "script-src 'self'" in response.headers['content-security-policy']
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert (await http.get('/api/workspace')).headers['cache-control'] == 'no-store'


async def test_symlinked_state_is_never_served(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    root = tmp_path / 'project'
    root.mkdir()
    (root / '.aletheia').symlink_to(outside)
    async with client(root) as http:
        assert (await http.get('/api/workspace')).status_code == 409


async def test_checkpoint_ownership_canonical_paths_and_redaction(setup_runtime):
    config, store, project, _ = setup_runtime
    task = store.create('Retained evidence', 'native')
    (project.root / 'example.txt').write_text('api_key=private-test-secret\nretained contents')
    checkpoint_id = project.snapshot(task['id'], 'baseline')
    # Never follow the absolute manifest_path stored in the DB as a file-serving instruction.
    store.db.execute('UPDATE checkpoints SET manifest_path=? WHERE id=?', ('/etc/passwd', checkpoint_id))
    store.db.commit()
    prefix = f"/api/tasks/{task['id']}/checkpoints/{checkpoint_id}"
    async with client(project.root) as http:
        response = await http.get(prefix, params={'file':'example.txt'})
        assert response.status_code == 200
        assert 'private-test-secret' not in response.text and '[REDACTED]' in response.text
        assert 'retained contents' in response.json()['preview']
        assert (await http.get(prefix, params={'file':'../../etc/passwd'})).status_code == 404
        assert (await http.get(f'/api/tasks/other/checkpoints/{checkpoint_id}')).status_code == 404
        assert (await http.get(f"/api/tasks/{task['id']}/checkpoints/not-an-id")).status_code == 404
        assert (await http.get('/assets/../../etc/passwd')).status_code == 404


async def test_symlinked_checkpoint_blob_is_rejected(setup_runtime):
    _, store, project, _ = setup_runtime
    task = store.create('Check symlink', 'native')
    cid = project.snapshot(task['id'], 'baseline')
    blob = project.blobs / project.manifest(cid)['calc.py']['sha256']
    blob.unlink()
    blob.symlink_to('/etc/passwd')
    async with client(project.root) as http:
        response = await http.get(f"/api/tasks/{task['id']}/checkpoints/{cid}", params={'file':'calc.py'})
        assert response.status_code == 409
        assert 'root:' not in response.text


async def test_malformed_manifest_returns_clear_error(setup_runtime):
    _, store, project, _ = setup_runtime
    task = store.create('Bad manifest', 'native')
    cid = project.snapshot(task['id'], 'baseline')
    (project.directory / (cid + '.json')).write_text('{"files": []}')
    async with client(project.root) as http:
        assert (await http.get(f"/api/tasks/{task['id']}/checkpoints/{cid}")).status_code == 409


async def test_task_list_limit_keeps_total_count(setup_runtime):
    _, store, project, _ = setup_runtime
    for i in range(103):
        store.create(f'task {i}', 'native')
    async with client(project.root) as http:
        data = (await http.get('/api/workspace')).json()
        assert data['stats']['total'] == 103
        assert data['stats']['active'] == 103
        assert len(data['tasks']) == 100 and data['tasks_truncated']


def test_cli_refuses_public_real_console_without_token(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('ALETHEIA_UI_TOKEN', raising=False)
    assert main(['--root',str(tmp_path),'ui','--host','0.0.0.0']) == 1
    assert 'ALETHEIA_UI_TOKEN' in capsys.readouterr().err
    assert not (tmp_path / '.aletheia').exists()


async def test_no_provider_secrets_in_workspace(setup_runtime):
    config, store, project, _ = setup_runtime
    config.save(project.root)
    async with client(project.root) as http:
        data = (await http.get('/api/workspace')).json()
        assert set(data['config']) == {'initialized','commands','error'}
        assert 'provider_url' not in data['config']


async def test_guides_and_brand_assets_are_packaged_offline(tmp_path):
    async with client(tmp_path, demo=True) as http:
        assert (await http.get('/assets/logo.svg')).status_code == 200
        assert (await http.get('/assets/manrope.woff2')).status_code == 200
        guide = await http.get('/guides/getting-started.md')
        assert guide.status_code == 200 and 'aletheia ui' in guide.text
        assert (await http.get('/guides/../../aletheia.json')).status_code == 404


def test_packaged_documentation_matches_sources():
    root = Path(__file__).resolve().parents[1]
    directory = root / 'aletheia' / 'web' / 'guides'
    manifest = json.loads((directory / 'manifest.json').read_text())
    for name, entry in manifest.items():
        assert (directory / (name + '.md')).read_text() == (root / entry['source']).read_text(), 'Run python scripts/sync_console_docs.py'


async def test_event_payload_budget_is_explicit(setup_runtime):
    _, store, project, _ = setup_runtime
    task = store.create('Bounded evidence', 'native')
    store.event(task['id'], 'observe', 'task.started', {'adapter':'codex'})
    for _ in range(5):
        store.event(task['id'], 'observe', 'native.observation', {'text':'x' * 1_000_000})
    async with client(project.root) as http:
        result = (await http.get('/api/tasks/' + task['id'])).json()
        assert result['events_truncated']
        assert 0 < len(result['events']) < 5
        assert result['task']['adapter'] == 'codex'
        assert len(json.dumps(result)) < 1_000_000
