"""Optional real-agent test. Uses the official CLI, never a real API key/model."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(not os.environ.get('ALETHEIA_CLAUDE_BIN'), reason='Set ALETHEIA_CLAUDE_BIN to an officially installed Claude Code executable')
def test_actual_claude_cli_recovers_using_installed_hooks(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'claude_demo.py'
    output = tmp_path / 'native-report.json'
    result = subprocess.run([sys.executable, str(script), '--claude', os.environ['ALETHEIA_CLAUDE_BIN'], '--output', str(output)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=150)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text())
    assert report['native_cli_executed'] is True
    assert report['real_model_tested'] is False
    assert report['state'] == 'verified_complete'
    assert report['tool_results_observed'] == 4
    assert [item['status'] for item in report['verification']] == ['failed', 'passed']
    assert report['metrics']['tasks_completed_on_base_model_only'] == 0
