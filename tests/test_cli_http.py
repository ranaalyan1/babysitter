"""The console server must work over TCP, not only under an ASGI test client."""
import importlib.util
from pathlib import Path

import pytest


def demo_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'demo.py'
    spec = importlib.util.spec_from_file_location('babysitter_demo', path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('fail_twice', [False, True])
async def test_cli_server_recovery_over_real_http(tmp_path, fail_twice):
    demo = demo_module()
    root = tmp_path / 'project'
    demo.create_fixture(root)
    report = await demo.run_demo(root, 'calc.py',
        'def add(a: int, b: int) -> int:\n    return a - b\n',
        'def add(a: int, b: int) -> int:\n    # Verified correction.\n    return a + b\n',
        fail_twice=fail_twice, over_http=True)
    assert report['state'] == 'verified_complete'
    assert report['transport'] == 'CLI server over TCP + real HTTP upstream'
    assert report['metrics']['verification_failures_caught_before_completion'] == (2 if fail_twice else 1)
    assert report['metrics']['escalations'] == int(fail_twice)
    assert (root / '.babysitter' / 'demo-server.log').exists()
    assert 'Application shutdown complete' in (root / '.babysitter' / 'demo-server.log').read_text()
