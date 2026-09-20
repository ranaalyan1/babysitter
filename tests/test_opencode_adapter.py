"""Owned-process failure injection. Scripted child is NOT the official CLI test."""
import json
import sys
from pathlib import Path

import pytest

from aletheia.adapters.opencode import AgentRunError, NativeTurn, supervise
from aletheia.metrics import metrics
from test_claude_adapter import BAD, GOOD


def child(project, body):
    path = project.root / '.aletheia' / 'agent-fixture'
    path.write_text(f'#!{sys.executable}\n' + '''import json, sys, time, pathlib, os
prompt = sys.stdin.read()
root = pathlib.Path.cwd()
def emit(kind, **part):
    print(json.dumps({'type': kind, 'sessionID': 'ses_fixture', 'part': part}), flush=True)
''' + body)
    path.chmod(0o700)
    return str(path)


async def test_owned_native_session_recovery(setup_runtime):
    config, store, project, _ = setup_runtime
    config.save(project.root)
    executable = child(project, f'''
resume = '--session' in sys.argv
if resume: assert sys.argv[sys.argv.index('--session') + 1] == 'ses_fixture'
assert '--auto' not in sys.argv and '--attach' not in sys.argv
assert ('NOT VERIFIED' in prompt) == resume
emit('step_start')
(root / 'calc.py').write_text({GOOD!r} if resume else {BAD!r})
emit('tool_use', tool='write', callID='write-1', state={{'status':'completed', 'input':{{'filePath':'calc.py'}}, 'output':'done'}})
emit('text', text='All done!')
emit('step_finish', reason='stop')
''')
    report = await supervise(project, store, config, 'Fix addition', executable)
    assert report['verified'] and report['result'] == 'All done!'
    trace = store.trace(report['task_id'])
    assert trace['tasks'][0]['attempts'] == 2
    assert [e['payload']['status'] for e in trace['events'] if e['kind'] == 'verification.result'] == ['failed', 'passed']
    assert len(trace['checkpoints']) == 2
    assert (project.root / 'calc.py').read_text() == GOOD
    assert metrics(trace)['tasks_with_agent_owned_model_selection'] == 1
    assert metrics(trace)['tasks_completed_on_base_model_only'] == 0
    assert not any(e['kind'] == 'tool.valid' for e in trace['events'])


@pytest.mark.parametrize('body,reason', [
    ("print('not-json')", 'non-JSON'),
    ("print('{}', end='')", 'Truncated'),
    ("emit('step_start')", 'complete final stop'),
    ("emit('step_start'); emit('step_finish', reason='tool-calls')", 'complete final stop'),
    ("sys.exit(4)", 'exited 4'),
    ("emit('step_start'); emit('step_finish', reason='stop'); print(json.dumps({'type':'error','sessionID':'ses_fixture','error':{'message':'native failure'}}))", 'native session'),
    ("emit('tool_use', tool='task', callID='sub', state={'status':'completed'})", 'Subagent'),
    ("emit('step_start'); emit('tool_use', tool='bash', callID='x', state={'status':'running'})", 'Unfinished'),
])
async def test_unclean_native_exit_never_success_and_retains_changes(setup_runtime, body, reason):
    config, store, project, _ = setup_runtime
    executable = child(project, f"(root / 'calc.py').write_text({BAD!r})\n" + body)
    result = await supervise(project, store, config, 'Fix', executable)
    assert not result['verified'] and reason in result['reason']
    assert (project.root / 'calc.py').read_text() == BAD
    assert any(c['purpose'] == 'failed_changes' for c in store.trace()['checkpoints'])
    assert not any(e['kind'] == 'verification.result' for e in store.trace()['events'])


async def test_timeout_kills_child_before_return_and_preserves_bytes(setup_runtime):
    config, store, project, _ = setup_runtime
    executable = child(project, f"(root / 'calc.py').write_text({BAD!r})\ntime.sleep(20)\n(root / 'late').write_text('unsafe')")
    result = await supervise(project, store, config, 'Fix', executable, timeout=0.2)
    assert not result['verified'] and 'timeout' in result['reason']
    assert not (project.root / 'late').exists()
    assert (project.root / 'calc.py').read_text() == BAD


async def test_rollback_baseline_cannot_earn_success(setup_runtime):
    config, store, project, _ = setup_runtime
    executable = child(project, f"if '--session' not in sys.argv: (root / 'calc.py').write_text({BAD!r})\nemit('step_start'); emit('text', text='done'); emit('step_finish', reason='stop')")
    result = await supervise(project, store, config, 'Fix', executable)
    assert not result['verified'] and 'budget exhausted' in result['reason']
    trace = store.trace(result['task_id'])
    assert trace['tasks'][0]['attempts'] == 3
    assert any(e['kind'] == 'failure' and e['payload']['class'] == 'no-progress-loop' for e in trace['events'])


async def test_controls_changed_by_native_process_halt_before_checks(setup_runtime):
    config, store, project, _ = setup_runtime
    config.save(project.root)
    executable = child(project, "(root / 'aletheia.json').write_text('{}')\nemit('step_start'); emit('step_finish', reason='stop')")
    result = await supervise(project, store, config, 'Fix', executable)
    assert not result['verified'] and 'configuration changed' in result['reason']
    assert not any(e['kind'] == 'verification.result' for e in store.trace()['events'])


async def test_new_task_rejected_while_other_owns_project(setup_runtime):
    config, store, project, _ = setup_runtime
    store.create('Native unfinished', 'native')
    with pytest.raises(AgentRunError, match='already owns'):
        await supervise(project, store, config, 'Fix', '/nonexistent')


def test_session_correlation_is_strict():
    turn = NativeTurn(session_id='ses_expected')
    with pytest.raises(AgentRunError, match='changed session'):
        turn.consume({'type':'step_start', 'sessionID':'ses_other', 'part':{}})


@pytest.mark.parametrize('model', ['--auto', '--model=x', '', 'no-provider', 'p/model --auto'])
async def test_model_flag_injection_rejected(setup_runtime, model):
    config, store, project, _ = setup_runtime
    with pytest.raises(ValueError, match='provider/model'):
        await supervise(project, store, config, 'Fix', '/not-executed', model=model)
    assert not store.trace()['tasks']


async def test_missing_checks_never_complete(setup_runtime):
    config, store, project, _ = setup_runtime
    config.typecheck_command = []
    executable = child(project, "emit('step_start'); emit('step_finish', reason='stop')")
    result = await supervise(project, store, config, 'Fix', executable)
    assert result['state'] == 'verification_unavailable' and not result['verified']


async def test_oversized_event_stream_halts(setup_runtime):
    config, store, project, _ = setup_runtime
    executable = child(project, "print('x' * 2100000)")
    result = await supervise(project, store, config, 'Fix', executable)
    assert not result['verified']
    assert not any(e['kind'] == 'verification.result' for e in store.trace()['events'])
