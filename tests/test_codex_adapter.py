"""Codex wire semantics differ from Claude even when lifecycle logic is shared."""
import json
import time

import pytest

from aletheia.adapters.codex import CodexAdapter, hook_main, teardown
from aletheia.adapters.codex_install import install, status, uninstall, EVENTS
from aletheia.adapters.claude import ClaudeAdapter
from aletheia.metrics import metrics
from test_claude_adapter import event, start, BAD, GOOD


@pytest.fixture
def adapter(setup_runtime):
    config, store, project, _ = setup_runtime
    config.save(project.root)
    return CodexAdapter(project, store, config)


async def patch(adapter, content, call_id):
    command = '*** Begin Patch\n*** Update File: calc.py\n@@\n+replacement\n*** End Patch'
    args = dict(tool_name='apply_patch', tool_use_id=call_id, tool_input={'command': command})
    assert await adapter.handle(event(adapter, 'PreToolUse', **args)) == {}
    (adapter.project.root / 'calc.py').write_text(content)
    await adapter.handle(event(adapter, 'PostToolUse', tool_response='Success. Updated calc.py', **args))


async def test_recovery_continuation_keeps_original_task_checkpoint_and_budget(adapter):
    task_id = await start(adapter)
    baseline = adapter.store.task(task_id)['checkpoint_id']
    await patch(adapter, BAD, 'bad')
    response = await adapter.handle(event(adapter, 'Stop', turn_id='turn-1', stop_hook_active=False))
    assert response['decision'] == 'block'
    await adapter.handle(event(adapter, 'UserPromptSubmit', turn_id='continuation-2', prompt=response['reason']))
    assert adapter.session('native-session')['task_id'] == task_id
    assert adapter.store.task(task_id)['checkpoint_id'] == baseline
    assert adapter.store.task(task_id)['attempts'] == 1
    assert len(adapter.store.trace()['tasks']) == 1
    await patch(adapter, GOOD, 'good')
    result = await adapter.handle(event(adapter, 'Stop', turn_id='continuation-2', stop_hook_active=True))
    assert 'verified-complete' in result['systemMessage']
    assert [e['payload']['status'] for e in adapter.events(task_id) if e['kind'] == 'verification.result'] == ['failed', 'passed']
    assert metrics(adapter.store.trace())['tasks_completed_on_base_model_only'] == 0


async def test_genuine_new_prompt_supersedes_but_never_rolls_back_user_work(adapter):
    old = await start(adapter)
    await patch(adapter, BAD, 'bad')
    await adapter.handle(event(adapter, 'UserPromptSubmit', prompt='Different user request', turn_id='2'))
    assert adapter.store.task(old)['state'] == 'failed'
    assert (adapter.project.root / 'calc.py').read_text() == BAD
    assert adapter.session('native-session')['task_id'] != old


@pytest.mark.parametrize('path', ['/etc/passwd', '../escape', '.git/config', '.aletheia/state.sqlite3', '.codex/hooks.json', '.opencode/plugin.js', '.env', 'aletheia.json'])
@pytest.mark.parametrize('operation', ['Add File', 'Update File', 'Delete File', 'Move to'])
async def test_all_patch_headers_guard_paths(adapter, path, operation):
    await start(adapter)
    command = f'*** Begin Patch\n*** Update File: calc.py\n*** {operation}: {path}\n*** End Patch'
    result = await adapter.handle(event(adapter, 'PreToolUse', tool_name='apply_patch', tool_use_id='unsafe', tool_input={'command': command}))
    assert result['hookSpecificOutput']['permissionDecision'] == 'deny'


async def test_repair_never_auto_approves(adapter):
    await start(adapter)
    result = await adapter.handle(event(adapter, 'PreToolUse', tool_name='Bash', tool_use_id='repair', tool_input={'command': 'pwd', 'timeout': '1000'}))
    assert result['hookSpecificOutput']['permissionDecision'] == 'deny'
    assert 'updatedInput' not in result['hookSpecificOutput']
    assert await adapter.handle(event(adapter, 'PreToolUse', tool_name='Bash', tool_use_id='valid', tool_input={'command': 'pwd'})) == {}


async def test_nonzero_shell_result_is_failure_not_success(adapter):
    task_id = await start(adapter)
    args = dict(tool_name='Bash', tool_use_id='shell', tool_input={'command': 'false'})
    await adapter.handle(event(adapter, 'PreToolUse', **args))
    result = await adapter.handle(event(adapter, 'PostToolUse', tool_response='Process exited with code 7\nFinal output:\nFailure', **args))
    assert result['hookSpecificOutput']['hookEventName'] == 'PostToolUse'
    assert adapter.store.db.execute('SELECT state FROM codex_calls WHERE task_id=?', (task_id,)).fetchone()[0] == 'failed'


async def test_terminal_pretool_uses_supported_deny_not_unsupported_continue(adapter):
    task_id = await start(adapter)
    adapter.finish(task_id, 'failed', 'test halt')
    result = await adapter.handle(event(adapter, 'PreToolUse', tool_name='Bash', tool_use_id='late', tool_input={'command': 'pwd'}))
    assert 'continue' not in result
    assert result['hookSpecificOutput']['permissionDecision'] == 'deny'


@pytest.mark.parametrize('kind', ['Interrupt', 'SessionEnd'])
async def test_advisory_teardown_never_snapshots_or_runs_verification(adapter, monkeypatch, kind):
    task_id = await start(adapter)
    monkeypatch.setattr(adapter.project, 'snapshot', lambda *a: pytest.fail('teardown snapshot'))
    before = time.monotonic()
    assert teardown(adapter.store, event(adapter, kind)) == {}
    assert time.monotonic() - before < 1
    assert adapter.store.task(task_id)['state'] == 'failed'
    assert not any(e['kind'] == 'verification.result' for e in adapter.events(task_id))


def test_install_reversible_private_idempotent_preserves_native_config(adapter):
    root = adapter.project.root
    directory = root / '.codex'
    directory.mkdir()
    original = {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'echo external'}]}]}}
    (directory / 'hooks.json').write_text(json.dumps(original))
    (directory / 'config.toml').write_text('sandbox_mode = "read-only"\n')
    result = install(root)
    assert result['installed'] and not result['trust_granted']
    assert not install(root)['changed']
    assert status(root)['ok']
    installed = json.loads((directory / 'hooks.json').read_text())
    assert set(installed['hooks']) == set(EVENTS)
    assert installed['hooks']['SessionEnd'][0]['hooks'][0]['timeout'] == 3
    assert '--dangerously' not in (directory / 'hooks.json').read_text()
    uninstall(root)
    assert json.loads((directory / 'hooks.json').read_text()) == original
    assert (directory / 'config.toml').read_text() == 'sandbox_mode = "read-only"\n'


async def test_codex_and_claude_cannot_own_same_workspace(adapter):
    await start(adapter)
    claude = ClaudeAdapter(adapter.project, adapter.store, adapter.config)
    result = await claude.handle(event(claude, 'UserPromptSubmit', prompt='other'))
    assert result['decision'] == 'block'


def test_bad_hook_input_does_not_fail_open(adapter, capsys):
    assert hook_main(adapter.project.root, 'PreToolUse', b'not json') == 0
    assert json.loads(capsys.readouterr().out)['hookSpecificOutput']['permissionDecision'] == 'deny'


async def test_pending_call_continuations_cannot_reset_budget(adapter):
    task_id = await start(adapter)
    await adapter.handle(event(adapter, 'PreToolUse', tool_name='Bash', tool_use_id='pending', tool_input={'command':'sleep 100'}))
    for attempt in (1, 2):
        response = await adapter.handle(event(adapter, 'Stop', stop_hook_active=True))
        assert response['decision'] == 'block'
        await adapter.handle(event(adapter, 'UserPromptSubmit', prompt=response['reason'], turn_id=f'new-{attempt}'))
        assert adapter.store.task(task_id)['attempts'] == attempt
        assert adapter.session('native-session')['task_id'] == task_id
    result = await adapter.handle(event(adapter, 'Stop', stop_hook_active=True))
    assert result['continue'] is False
    assert len(adapter.store.trace()['tasks']) == 1
    assert not any(e['kind'] == 'rollback.completed' for e in adapter.events(task_id))


async def test_running_shell_result_is_not_quiescent(adapter):
    task_id = await start(adapter)
    args = dict(tool_name='Bash', tool_use_id='running', tool_input={'command':'sleep 100'})
    await adapter.handle(event(adapter, 'PreToolUse', **args))
    await adapter.handle(event(adapter, 'PostToolUse', tool_response={'output':'Process running with session ID 100'}, **args))
    row = adapter.store.db.execute('SELECT state FROM codex_calls WHERE task_id=?', (task_id,)).fetchone()
    assert row[0] == 'pending'
    result = await adapter.handle(event(adapter, 'Stop'))
    assert result['decision'] == 'block'
    assert not any(e['kind'] in {'verification.result', 'rollback.completed'} for e in adapter.events(task_id))


async def test_proxy_cannot_take_codex_ownership(adapter):
    from aletheia.server import create_app
    from conftest import ScriptedProvider, answer
    await start(adapter)
    app = create_app(adapter.project.root, adapter.config, ScriptedProvider([answer()]))
    with pytest.raises(RuntimeError, match='active Codex task'):
        async with app.router.lifespan_context(app):
            pass


async def test_continuation_after_pending_result_still_keeps_task(adapter):
    task_id = await start(adapter)
    args = dict(tool_name='Bash', tool_use_id='pending', tool_input={'command':'pwd'})
    await adapter.handle(event(adapter, 'PreToolUse', **args))
    blocked = await adapter.handle(event(adapter, 'Stop'))
    await adapter.handle(event(adapter, 'PostToolUse', tool_response={'exit_code':0}, **args))
    await adapter.handle(event(adapter, 'UserPromptSubmit', prompt=blocked['reason'], turn_id='late-continuation'))
    assert adapter.session('native-session')['task_id'] == task_id
    assert adapter.store.task(task_id)['attempts'] == 1


def test_installed_matcher_tampering_is_reported(adapter):
    root = adapter.project.root
    install(root)
    path = root / '.codex' / 'hooks.json'
    settings = json.loads(path.read_text())
    settings['hooks']['PreToolUse'][0]['matcher'] = 'NeverMatches'
    path.write_text(json.dumps(settings))
    assert not status(root)['ok']


async def test_unknown_running_result_does_not_create_false_quiescence(adapter):
    from aletheia.adapters.native import HookError
    await start(adapter)
    with pytest.raises(HookError, match='matching pending'):
        await adapter.handle(event(adapter, 'PostToolUse', tool_name='Bash', tool_use_id='unseen', tool_input={'command':'sleep 5'}, tool_response={'running':True}))
