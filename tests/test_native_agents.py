"""Optional official-agent CLI tests; endpoints are scripted, not real models."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize('agent', ['codex', 'opencode'])
def test_official_cli_recovery(agent, tmp_path):
    executable = os.environ.get(f'ALETHEIA_{agent.upper()}_BIN')
    if not executable:
        pytest.skip(f'Set ALETHEIA_{agent.upper()}_BIN to an officially installed executable')
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'native_agents_demo.py'
    output = tmp_path / f'{agent}-report.json'
    result = subprocess.run([sys.executable, str(script), agent, '--executable', executable, '--output', str(output)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=330)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text())
    assert not report['real_model_tested']
    assert report['verification_statuses'] == ['failed', 'passed']
    assert report['metrics']['tasks_total'] == 1
    assert report['metrics']['tasks_verified_complete'] == 1
    assert report['observed_tool_results'] >= 2
    assert not report['permissions_auto_approved_by_adapter']
    assert report['metrics']['tasks_completed_on_base_model_only'] == 0
