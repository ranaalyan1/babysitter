"""Official hook payload contract + real subprocess verification, no Claude auth."""
from __future__ import annotations

import asyncio
import copy
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from babysitter.adapters.claude import ClaudeAdapter, HookError, parse_event, hook_main
from babysitter.adapters.claude_install import EVENTS, install, uninstall, status, owned
from babysitter.cli import main
from babysitter.metrics import metrics

BAD = 'def add(a: int, b: int) -> int:\n    return a - b\n'
GOOD = 'def add(a: int, b: int) -> int:\n    # Corrected under supervision.\n    return a + b\n'


@pytest.fixture
def adapter(setup_runtime):
    config, store, project, _ = setup_runtime
    config.save(project.root)
    return ClaudeAdapter(project, store, config)


def event(adapter, kind, **extra):
    return {'session_id': 'native-session', 'cwd': str(adapter.project.root), 'hook_event_name': kind, **extra}


async def start(adapter, prompt='Fix addition'):
    await adapter.handle(event(adapter, 'SessionStart', model='reported-claude-model'))
    response = await adapter.handle(event(adapter, 'UserPromptSubmit', prompt=prompt, prompt_id='prompt-1'))
    assert 'hookSpecificOutput' in response
    return adapter.session('native-session')['task_id']


async def write(adapter, content, call_id='write-1'):
    args = {'file_path': str(adapter.project.root / 'calc.py'), 'content': content}
    response = await adapter.handle(event(adapter, 'PreToolUse', tool_name='Write', tool_use_id=call_id, tool_input=args))
    assert response == {}, response
    (adapter.project.root / 'calc.py').write_text(content)
    return await adapter.handle(event(adapter, 'PostToolUse', tool_name='Write', tool_use_id=call_id, tool_input=args,
                                     tool_response={'filePath': args['file_path'], 'type': 'update'}))


async def test_complete_native_recovery_loop(adapter):
    task_id = await start(adapter)
    await write(adapter, BAD)
    failed = await adapter.handle(event(adapter, 'Stop', stop_hook_active=False, last_assistant_message='I am done'))
    assert failed['decision'] == 'block'
    assert 'rolled back' in failed['reason'] and 'AssertionError' in failed['reason']
    assert 'return a + b' in (adapter.project.root / 'calc.py').read_text()
    assert adapter.store.task(task_id)['state'] == 'recovering'
    await write(adapter, GOOD, 'write-2')
    passed = await adapter.handle(event(adapter, 'Stop', stop_hook_active=True))
    assert 'decision' not in passed and 'verified-complete' in passed['systemMessage']
    trace = adapter.store.trace(task_id)
    assert trace['tasks'][0]['state'] == 'verified_complete'
    evidence = [e['payload']['status'] for e in trace['events'] if e['kind'] == 'verification.result']
    assert evidence == ['failed', 'passed']
    assert len(trace['checkpoints']) == 2
    assert any(e['kind'] == 'rollback.completed' for e in trace['events'])


async def test_rollback_alone_cannot_earn_completion(adapter):
    task_id = await start(adapter)
    await write(adapter, BAD)
    await adapter.handle(event(adapter, 'Stop', stop_hook_active=False))
    response = await adapter.handle(event(adapter, 'Stop', stop_hook_active=True))
    assert response['decision'] == 'block' and 'No corrected changes' in response['reason']
    response = await adapter.handle(event(adapter, 'Stop', stop_hook_active=True))
    assert response['continue'] is False and 'NOT VERIFIED' in response['stopReason']
    assert adapter.store.task(task_id)['state'] == 'failed'
    assert any(e['kind'] == 'escalation.requested' for e in adapter.events(task_id))
    assert not any(e['kind'] == 'model.escalated' for e in adapter.events(task_id))


async def test_native_permissions_are_never_auto_approved(adapter):
    await start(adapter)
    response = await adapter.handle(event(adapter, 'PreToolUse', tool_name='Bash', tool_use_id='bash-1',
                                         tool_input={'command': 'git status --short'}))
    assert response == {}


@pytest.mark.parametrize('path', ['/etc/passwd', '../escape.txt', '.git/config', '.babysitter/state.sqlite3', 'babysitter.json',
                                 '.claude/settings.local.json', '.gitignore', '.env'])
async def test_native_file_paths_are_guarded(adapter, path):
    await start(adapter)
    response = await adapter.handle(event(adapter, 'PreToolUse', tool_name='Write', tool_use_id='bad-path',
                                         tool_input={'file_path': path, 'content': 'bad'}))
    assert response['hookSpecificOutput']['permissionDecision'] == 'deny'


async def test_absolute_inside_path_and_conservative_repair(adapter):
    await start(adapter)
    response = await adapter.handle(event(adapter, 'PreToolUse', tool_name='Read', tool_use_id='read-1',
        tool_input={'file_path': str(adapter.project.root / 'calc.py'), 'offset': '1'}))
    assert response['hookSpecificOutput']['updatedInput']['offset'] == 1
    assert 'permissionDecision' not in response['hookSpecificOutput']


@pytest.mark.parametrize('tool,args', [('Bash', {'command': 'npm test', 'run_in_background': True}),
                                      ('Agent', {'prompt': 'delegate'}), ('Task', {'prompt': 'delegate'}),
                                      ('Bash', {'command': 'sudo rm x'})])
async def test_unsupported_execution_is_denied(adapter, tool, args):
    await start(adapter)
    response = await adapter.handle(event(adapter, 'PreToolUse', tool_name=tool, tool_use_id='call-1', tool_input=args))
    assert response['hookSpecificOutput']['permissionDecision'] == 'deny'


async def test_pending_calls_prevent_verification_and_rollback(adapter):
    task_id = await start(adapter)
    await adapter.handle(event(adapter, 'PreToolUse', tool_name='Bash', tool_use_id='pending', tool_input={'command': 'npm test'}))
    response = await adapter.handle(event(adapter, 'Stop', stop_hook_active=False))
    assert response['decision'] == 'block' and 'NOT rolled back' in response['reason']
    assert not any(e['kind'] in {'verification.result', 'rollback.completed'} for e in adapter.events(task_id))


async def test_background_work_prevents_completion(adapter):
    await start(adapter)
    response = await adapter.handle(event(adapter, 'Stop', background_tasks=[{'id': 'x', 'status': 'running'}]))
    assert response['decision'] == 'block'


async def test_missing_checks_are_explicitly_unavailable(adapter):
    task_id = await start(adapter)
    adapter.config.typecheck_command = []  # in-memory test; file tampering has a separate guard
    response = await adapter.handle(event(adapter, 'Stop', stop_hook_active=False))
    assert response['continue'] is False and 'NOT VERIFIED' in response['stopReason']
    assert adapter.store.task(task_id)['state'] == 'verification_unavailable'


async def test_control_tampering_never_executes_new_commands(adapter):
    task_id = await start(adapter)
    (adapter.project.root / 'babysitter.json').write_text('{"test_command":["touch","SHOULD_NOT_EXIST"]}')
    with pytest.raises(HookError, match='configuration changed'):
        await adapter.handle(event(adapter, 'Stop', stop_hook_active=False))
    assert not (adapter.project.root / 'SHOULD_NOT_EXIST').exists()
    assert not any(e['kind'] == 'verification.result' for e in adapter.events(task_id))


async def test_actual_tool_failure_recorded_without_premature_rollback(adapter):
    task_id = await start(adapter)
    args = {'command': 'python -m pytest'}
    await adapter.handle(event(adapter, 'PreToolUse', tool_name='Bash', tool_use_id='b1', tool_input=args))
    response = await adapter.handle(event(adapter, 'PostToolUseFailure', tool_name='Bash', tool_use_id='b1', tool_input=args,
                                         error='Exit code 1\nAssertionError'))
    assert 'AssertionError' in response['hookSpecificOutput']['additionalContext']
    assert any(e['kind'] == 'failure' and e['payload']['class'] == 'tool-error' for e in adapter.events(task_id))
    assert not any(e['kind'] == 'rollback.completed' for e in adapter.events(task_id))


async def test_duplicate_callbacks_are_idempotent(adapter):
    task_id = await start(adapter)
    args = {'file_path': str(adapter.project.root / 'calc.py')}
    pre = event(adapter, 'PreToolUse', tool_name='Read', tool_use_id='r1', tool_input=args)
    post = event(adapter, 'PostToolUse', tool_name='Read', tool_use_id='r1', tool_input=args, tool_response={'content': 'actual contents'})
    assert await adapter.handle(pre) == {}
    assert await adapter.handle(pre) == {}
    assert await adapter.handle(post) == {}
    assert await adapter.handle(post) == {}
    assert len([e for e in adapter.events(task_id) if e['kind'] == 'tool.result']) == 1
    assert (await adapter.handle(pre))['hookSpecificOutput']['permissionDecision'] == 'deny'


async def test_post_without_pre_is_not_invented_visibility(adapter):
    await start(adapter)
    with pytest.raises(HookError, match='no matching'):
        await adapter.handle(event(adapter, 'PostToolUse', tool_name='Read', tool_use_id='missing',
                                   tool_input={'file_path': str(adapter.project.root / 'calc.py')}, tool_response='x'))


async def test_second_session_cannot_share_active_worktree(adapter):
    task_id = await start(adapter)
    response = await adapter.handle(event(adapter, 'UserPromptSubmit', session_id='other-session', prompt='Race this task'))
    assert response['decision'] == 'block' and task_id in response['reason']


async def test_new_prompt_preserves_unfinished_task(adapter):
    old = await start(adapter)
    await write(adapter, BAD)
    response = await adapter.handle(event(adapter, 'UserPromptSubmit', prompt='New explicit task'))
    new = adapter.session('native-session')['task_id']
    assert old != new
    assert adapter.store.task(old)['state'] == 'failed'
    assert (adapter.project.root / 'calc.py').read_text() == BAD
    assert len(adapter.store.trace(old)['checkpoints']) == 2


async def test_session_end_does_not_claim_success_or_discard_changes(adapter):
    task_id = await start(adapter)
    await write(adapter, BAD)
    assert await adapter.handle(event(adapter, 'SessionEnd', reason='user_exit')) == {}
    assert adapter.store.task(task_id)['state'] == 'failed'
    assert (adapter.project.root / 'calc.py').read_text() == BAD


async def test_changed_files_invalidate_duplicate_stop(adapter):
    task_id = await start(adapter)
    assert 'verified-complete' in (await adapter.handle(event(adapter, 'Stop')))['systemMessage']
    (adapter.project.root / 'calc.py').write_text(BAD)
    response = await adapter.handle(event(adapter, 'Stop', stop_hook_active=True))
    assert response['continue'] is False
    assert adapter.store.task(task_id)['state'] == 'failed'


async def test_claude_plan_is_observed_not_invented(adapter):
    task_id = await start(adapter)
    await adapter.handle(event(adapter, 'PreToolUse', tool_name='ExitPlanMode', tool_use_id='p1', tool_input={}))
    await adapter.handle(event(adapter, 'PostToolUse', tool_name='ExitPlanMode', tool_use_id='p1', tool_input={}, tool_response={'plan': '1. Inspect\n2. Fix\n3. Verify'}))
    assert json.loads(adapter.store.task(task_id)['plan_json']) == ['1. Inspect\n2. Fix\n3. Verify']


def test_install_uninstall_preserves_settings_and_is_idempotent(adapter):
    root = adapter.project.root
    (root / '.claude').mkdir()
    existing = {'permissions': {'deny': ['Bash(rm *)']}, 'env': {'KEEP_ME': 'yes'},
                'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'echo existing'}]}]}}
    path = root / '.claude' / 'settings.local.json'
    path.write_text(json.dumps(existing))
    report = install(root)
    assert report['installed'] and report['backup']
    assert json.loads(Path(report['backup']).read_text()) == existing
    installed = json.loads(path.read_text())
    assert installed['permissions'] == existing['permissions'] and installed['env'] == existing['env']
    assert status(root)['ok']
    assert install(root)['changed'] is False
    assert uninstall(root)['changed'] is True
    assert json.loads(path.read_text()) == existing
    assert uninstall(root)['changed'] is False


def test_install_requires_real_verification_commands(adapter):
    adapter.config.typecheck_command = []
    adapter.config.save(adapter.project.root)
    with pytest.raises(ValueError, match='Both'):
        install(adapter.project.root)


def test_install_does_not_enable_disabled_hooks(adapter):
    root = adapter.project.root
    (root / '.claude').mkdir()
    path = root / '.claude' / 'settings.local.json'
    content = '{"disableAllHooks": true}'
    path.write_text(content)
    with pytest.raises(ValueError, match='disableAllHooks'):
        install(root)
    assert path.read_text() == content


def test_install_does_not_follow_settings_symlink(adapter, tmp_path):
    (adapter.project.root / '.claude').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        install(adapter.project.root)


def test_cli_status(adapter, capsys):
    root = str(adapter.project.root)
    assert main(['--root', root, 'claude', 'status']) == 1
    capsys.readouterr()
    assert main(['--root', root, 'claude', 'install']) == 0
    assert json.loads(capsys.readouterr().out)['installed']
    assert main(['--root', root, 'claude', 'status']) == 0
    assert json.loads(capsys.readouterr().out)['ok']


@pytest.mark.parametrize('kind', ['PreToolUse', 'UserPromptSubmit', 'Stop'])
def test_bad_hook_input_produces_blocking_protocol_output(adapter, capsys, kind):
    assert hook_main(adapter.project.root, kind, b'{broken json') == 0
    response = json.loads(capsys.readouterr().out)
    if kind == 'PreToolUse':
        assert response['hookSpecificOutput']['permissionDecision'] == 'deny'
    elif kind == 'UserPromptSubmit':
        assert response['decision'] == 'block'
    else:
        assert response['continue'] is False


def test_separate_hook_processes_persist_native_session(adapter):
    root = adapter.project.root
    install(root)
    settings = json.loads((root / '.claude' / 'settings.local.json').read_text())
    def invoke(kind, **kwargs):
        command = next(h['command'] for group in settings['hooks'][kind] for h in group['hooks'] if owned(h))
        result = subprocess.run(command, shell=True, input=json.dumps(event(adapter, kind, **kwargs)), capture_output=True,
                                text=True, cwd=root, timeout=30)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    assert 'hookSpecificOutput' in invoke('SessionStart', model='reported-claude')
    assert 'hookSpecificOutput' in invoke('UserPromptSubmit', prompt='Verify current project')
    result = invoke('Stop', stop_hook_active=False)
    assert 'verified-complete' in result['systemMessage']
    assert adapter.store.trace()['tasks'][0]['state'] == 'verified_complete'


def test_adapter_version_keeps_core_schema_frozen(adapter):
    assert adapter.store.db.execute('SELECT version FROM schema_version').fetchone()[0] == 1
    assert adapter.store.db.execute('SELECT version FROM claude_adapter_version').fetchone()[0] == 1


async def test_protocol_server_cannot_steal_an_active_native_task(adapter):
    from babysitter.server import create_app
    from conftest import ScriptedProvider, answer
    task_id = await start(adapter)
    app = create_app(adapter.project.root, adapter.config, ScriptedProvider([answer()]))
    with pytest.raises(RuntimeError, match='active Claude Code task'):
        async with app.router.lifespan_context(app):
            pytest.fail('Server must not start over a native task')
    assert adapter.store.task(task_id)['state'] == 'observed'


async def test_metrics_do_not_infer_native_model_selection(adapter):
    task_id = await start(adapter)
    await adapter.handle(event(adapter, 'Stop'))
    report = metrics(adapter.store.trace(task_id))
    assert report['tasks_completed_on_base_model_only'] == 0
    assert report['tasks_with_agent_owned_model_selection'] == 1
    assert report['tasks_verified_complete'] == 1


def test_generated_command_quotes_paths_without_losing_virtualenv(adapter, tmp_path):
    from babysitter.adapters.claude_install import command
    root = tmp_path / "repo 'with spaces'"
    root.mkdir()
    handler = command(root, 'SessionStart')
    # Missing git config fails safely with valid hook JSON, not shell tokenization
    # or ImportError from resolving the virtualenv interpreter to system Python.
    result = subprocess.run(handler, shell=True, input=json.dumps({'session_id': 'q', 'hook_event_name': 'SessionStart', 'cwd': str(root)}),
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0
    assert json.loads(result.stdout)['continue'] is False
    assert 'No module named' not in result.stderr


def test_missing_interpreter_wrapper_exits_two_not_fail_open(adapter):
    from babysitter.adapters.claude_install import command
    handler = command(adapter.project.root, 'Stop').replace(str(Path(sys.executable).absolute()), '/nonexistent/babysitter-python', 1)
    result = subprocess.run(handler, shell=True, input='{}', capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert 'NOT VERIFIED' in result.stderr


async def test_parallel_native_callbacks_can_finish_out_of_order(adapter):
    task_id = await start(adapter)
    for call_id, filename in [('one', 'calc.py'), ('two', 'test_calc.py')]:
        assert await adapter.handle(event(adapter, 'PreToolUse', tool_name='Read', tool_use_id=call_id,
                                          tool_input={'file_path': str(adapter.project.root / filename)})) == {}
    for call_id, filename in [('two', 'test_calc.py'), ('one', 'calc.py')]:
        await adapter.handle(event(adapter, 'PostToolUse', tool_name='Read', tool_use_id=call_id,
                                   tool_input={'file_path': str(adapter.project.root / filename)}, tool_response='contents'))
    assert 'verified-complete' in (await adapter.handle(event(adapter, 'Stop')))['systemMessage']
    assert adapter.store.task(task_id)['state'] == 'verified_complete'
