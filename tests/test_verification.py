import os
import sys

import pytest

from babysitter.project import UnsafePath
from babysitter.verify import Verifier, run_command


def baseline(store, project):
    task = store.create("check", "weak")
    return task["id"], project.snapshot(task["id"], "baseline")


async def test_real_tests_typecheck_and_diff(setup_runtime):
    config, store, project, _ = setup_runtime
    _, checkpoint = baseline(store, project)
    (project.root / "calc.py").write_text("def add(a: int, b: int) -> int:\n    return a - b\n")
    evidence = await Verifier(project, config).verify(checkpoint)
    assert evidence["status"] == "failed"
    assert evidence["commands"][0]["exit_code"] == 1
    assert "AssertionError" in evidence["commands"][0]["stdout"]
    assert evidence["commands"][1]["exit_code"] == 0
    assert "calc.py" in evidence["files"] and "+    return a - b" in evidence["diff"]


async def test_pass_requires_both_checks(setup_runtime):
    config, store, project, _ = setup_runtime
    _, checkpoint = baseline(store, project)
    verifier = Verifier(project, config)
    assert (await verifier.verify(checkpoint))["status"] == "passed"
    config.typecheck_command = []
    assert (await verifier.verify(checkpoint))["status"] == "unavailable"


async def test_verifier_rejects_self_modifying_checks(setup_runtime):
    config, store, project, _ = setup_runtime
    _, checkpoint = baseline(store, project)
    config.test_command = [sys.executable, "-c", "from pathlib import Path; Path('calc.py').write_text('# changed')"]
    config.typecheck_command = [sys.executable, "-c", "pass"]
    evidence = await Verifier(project, config).verify(checkpoint)
    assert evidence["status"] == "failed" and "stale" in evidence["reason"]


async def test_timeout_and_bounded_output(setup_runtime):
    _, _, project, _ = setup_runtime
    result = await run_command([sys.executable, "-c", "import time; print('x' * 100000, flush=True); time.sleep(10)"], project, .2, 100)
    assert result.timed_out and result.output_truncated
    assert len(result.stdout) == 100
    assert result.duration_seconds < 3


async def test_missing_executable_is_evidence(setup_runtime):
    _, _, project, _ = setup_runtime
    result = await run_command(["/not/an/executable"], project, 1, 100)
    assert result.exit_code is None and result.stderr


async def test_subprocess_does_not_receive_credentials(setup_runtime, monkeypatch):
    _, _, project, _ = setup_runtime
    monkeypatch.setenv("BABYSITTER_PROVIDER_API_KEY", "secret")
    result = await run_command([sys.executable, "-c", "import os; assert 'BABYSITTER_PROVIDER_API_KEY' not in os.environ"], project, 2, 100)
    assert result.exit_code == 0


def test_rollback_preserves_dirty_untracked_and_failed_changes(setup_runtime):
    _, store, project, _ = setup_runtime
    (project.root / "calc.py").write_text("# preexisting dirty\n")
    (project.root / "notes.txt").write_text("original untracked\n")
    task_id, checkpoint = baseline(store, project)
    (project.root / "calc.py").write_text("# failed patch\n")
    (project.root / "notes.txt").unlink()
    (project.root / "new.txt").write_text("failed new file\n")
    failed_id = project.rollback(task_id, checkpoint)
    assert (project.root / "calc.py").read_text() == "# preexisting dirty\n"
    assert (project.root / "notes.txt").read_text() == "original untracked\n"
    assert not (project.root / "new.txt").exists()
    failed = project.manifest(failed_id)
    assert (project.blobs / failed["calc.py"]["sha256"]).read_text() == "# failed patch\n"
    assert store.trace(task_id)["events"][-1]["kind"] == "rollback.completed"


def test_snapshot_failure_cannot_discard_changes(setup_runtime):
    _, store, project, _ = setup_runtime
    task_id, checkpoint = baseline(store, project)
    (project.root / "calc.py").write_text("changed")
    project.max_bytes = 1
    with pytest.raises(UnsafePath):
        project.rollback(task_id, checkpoint)
    assert (project.root / "calc.py").read_text() == "changed"


@pytest.mark.parametrize("path", ["../outside", "/etc/passwd", ".git/config", ".babysitter/state.sqlite3", "x/../../oops", ".env"])
def test_reject_unsafe_managed_paths(setup_runtime, path):
    _, _, project, _ = setup_runtime
    with pytest.raises(UnsafePath):
        project.safe_path(path, managed=True)


def test_symlink_parent_is_not_followed(setup_runtime, tmp_path):
    _, _, project, _ = setup_runtime
    (project.root / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(UnsafePath):
        project.safe_path("link/outside.txt", managed=True)


def test_modes_restored(setup_runtime):
    _, store, project, _ = setup_runtime
    (project.root / "calc.py").chmod(0o755)
    task_id, checkpoint = baseline(store, project)
    (project.root / "calc.py").chmod(0o644)
    project.rollback(task_id, checkpoint)
    assert os.stat(project.root / "calc.py").st_mode & 0o777 == 0o755


def test_baseline_file_hidden_by_ignore_edit_still_checkpointed(setup_runtime):
    _, store, project, _ = setup_runtime
    (project.root / "notes.txt").write_text("original")
    task_id, checkpoint = baseline(store, project)
    (project.root / "notes.txt").write_text("unsuccessful hidden changes")
    (project.root / ".gitignore").write_text((project.root / ".gitignore").read_text() + "notes.txt\n")
    failed_id = project.rollback(task_id, checkpoint)
    assert (project.root / "notes.txt").read_text() == "original"
    entry = project.manifest(failed_id)["notes.txt"]
    assert (project.blobs / entry["sha256"]).read_text() == "unsuccessful hidden changes"


def test_corrupt_checkpoint_refuses_rollback(setup_runtime):
    _, store, project, _ = setup_runtime
    task_id, checkpoint = baseline(store, project)
    entry = project.manifest(checkpoint)["calc.py"]
    (project.blobs / entry["sha256"]).write_text("corrupt")
    (project.root / "calc.py").write_text("failed but inspectable")
    with pytest.raises(UnsafePath, match="corrupt"):
        project.rollback(task_id, checkpoint)
    assert (project.root / "calc.py").read_text() == "failed but inspectable"


async def test_untracked_changes_included_in_evidence(setup_runtime):
    config, store, project, _ = setup_runtime
    _, checkpoint = baseline(store, project)
    (project.root / "new.txt").write_text("new data\n")
    evidence = await Verifier(project, config).verify(checkpoint)
    assert evidence["status"] == "passed"
    assert evidence["files"] == ["new.txt"] and "+new data" in evidence["diff"]
