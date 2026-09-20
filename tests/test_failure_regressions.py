"""Regressions for failures not covered by the original happy-path demo."""
import os
import py_compile
import sys

import httpx
import pytest

from aletheia.cli import main
from aletheia.provider import OpenAIProvider, ProviderError
from aletheia.tools import TOOLS
from aletheia.verify import Verifier
from conftest import answer, call, tool_response
from test_protocol import client_for


async def test_unknown_task_returns_404_not_internal_error(workspace, setup_runtime):
    config, _, _, _ = setup_runtime
    async with client_for(workspace, config, [answer()]) as (client, _, _):
        response = await client.post('/v1/chat/completions', json={
            'model': 'weak', 'messages': [{'role': 'user', 'content': 'Check'}]},
            headers={'X-Aletheia-Task': 'nonexistent'})
        assert response.status_code == 404
        assert response.json()['error']['message'] == 'Unknown task'
        assert response.headers['X-Aletheia-Verified'] == 'false'


@pytest.mark.parametrize('payload', [[], {'choices': [None]}, {'choices': ['broken']}])
async def test_malformed_upstream_completion_is_provider_error(setup_runtime, payload):
    config, _, _, _ = setup_runtime
    provider = OpenAIProvider(config)
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(base_url='http://provider/v1/', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)))
    try:
        with pytest.raises(ProviderError):
            await provider.complete([{'role': 'user', 'content': 'Hi'}], [], 'weak', {})
    finally:
        await provider.close()


async def test_malformed_models_response_is_provider_error(setup_runtime):
    config, _, _, _ = setup_runtime
    provider = OpenAIProvider(config)
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(base_url='http://provider/v1/', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=[])))
    try:
        with pytest.raises(ProviderError):
            await provider.models()
    finally:
        await provider.close()


async def test_verification_cannot_pass_using_stale_python_bytecode(setup_runtime):
    config, store, project, _ = setup_runtime
    source = project.root / 'calc.py'
    original = source.read_text()
    # Emulate two same-length edits in the same timestamp-resolution window.
    timestamp = source.stat().st_mtime_ns
    py_compile.compile(str(source), doraise=True)
    task = store.create('verify actual source', 'weak')
    baseline = project.snapshot(task['id'], 'baseline')
    source.write_text(original.replace('a + b', 'a - b'))
    os.utime(source, ns=(timestamp, timestamp))
    config.test_command = [sys.executable, '-c', 'from calc import add; assert add(2, 3) == 5']
    evidence = await Verifier(project, config).verify(baseline)
    assert evidence['status'] == 'failed'
    assert evidence['commands'][0]['exit_code'] != 0


async def test_managed_forced_tool_choice_is_released_after_execution(setup_runtime):
    _, _, _, build = setup_runtime
    runtime, provider = build([tool_response(call('read_file', args={'path': 'calc.py'})), answer()])
    _, task = await runtime.run([{'role': 'user', 'content': 'Read and check'}], [],
                               {'tool_choice': 'required'}, protocol='openai', managed=True)
    assert task['state'] == 'verified_complete'
    assert provider.requests[0]['options']['tool_choice'] == 'required'
    assert provider.requests[1]['options'].get('tool_choice', 'auto') == 'auto'


async def test_relay_reused_tool_id_does_not_break_continuation(workspace, setup_runtime):
    config, _, _, _ = setup_runtime
    responses = [tool_response(call('read_file', args={'path': 'calc.py'})),
                 tool_response(call('read_file', args={'path': 'test_calc.py'})), answer()]
    async with client_for(workspace, config, responses) as (client, _, _):
        messages = [{'role': 'user', 'content': 'Read both files'}]
        headers = {}
        for round_number in range(3):
            response = await client.post('/v1/chat/completions', json={
                'model': 'weak', 'messages': messages, 'tools': TOOLS}, headers=headers)
            assert response.status_code == 200, response.text
            headers = {'X-Aletheia-Task': response.headers['X-Aletheia-Task']}
            if round_number < 2:
                assistant = response.json()['choices'][0]['message']
                messages.extend([assistant, {'role': 'tool', 'tool_call_id': assistant['tool_calls'][0]['id'], 'content': 'contents'}])
        assert response.headers['X-Aletheia-State'] == 'verified_complete'


@pytest.mark.parametrize('configuration', ['[]', '{"unknown_option":true}', '{"max_attempts":true}', '{"command_timeout":NaN}'])
def test_bad_config_reports_clean_cli_error(workspace, capsys, configuration):
    (workspace / 'aletheia.json').write_text(configuration)
    assert main(['--root', str(workspace), 'doctor', '--offline']) == 1
    assert 'aletheia:' in capsys.readouterr().err
