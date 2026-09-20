"""Checkpoint / rollback / retry-context tests (both strategies)."""

import json
import subprocess

import pytest

from babysitter.recover import (
    CheckpointError,
    build_retry_context,
    create_checkpoint,
    restore_checkpoint,
)
from babysitter.schema import (
    CHECKPOINT_COPY,
    CHECKPOINT_GIT,
    KIND_CHECKPOINT_CREATED,
    KIND_ROLLBACK_DONE,
)
from babysitter.store import BabysitterStore


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def task_in(tmp_path):
    store = BabysitterStore(tmp_path / "state.db")
    task = store.create_task("goal", str(tmp_path), "m", {})
    yield store, task, tmp_path
    store.close()


def test_file_copy_roundtrip(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "keep.txt").write_text("v1")
    (proj / "del.txt").write_text("bye")
    (proj / "sub").mkdir()
    (proj / "sub" / "nested.txt").write_text("n")
    store = BabysitterStore(proj / ".babysitter" / "babysitter.db")
    task = store.create_task("g", str(proj), "m", {})

    chk = create_checkpoint(store, task.id, proj, "test")
    assert chk.strategy == CHECKPOINT_COPY

    (proj / "keep.txt").write_text("v2-MODIFIED")
    (proj / "del.txt").unlink()
    (proj / "added.txt").write_text("new")

    restore_checkpoint(store, chk, proj)
    assert (proj / "keep.txt").read_text() == "v1"
    assert (proj / "del.txt").read_text() == "bye"
    assert not (proj / "added.txt").exists()
    assert (proj / "sub" / "nested.txt").read_text() == "n"
    kinds = [e.kind for e in store.list_events(task.id, limit=100)]
    assert KIND_CHECKPOINT_CREATED in kinds and KIND_ROLLBACK_DONE in kinds
    assert store.get_checkpoint(chk.id).status == "restored"
    store.close()


def test_git_roundtrip(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    git(proj, "init", "-q")
    git(proj, "config", "user.email", "t@t")
    git(proj, "config", "user.name", "t")
    (proj / "keep.txt").write_text("v1")
    git(proj, "add", ".")
    git(proj, "commit", "-qm", "base")
    store = BabysitterStore(proj / ".babysitter" / "babysitter.db")

    task = store.create_task("g", str(proj), "m", {})
    chk = create_checkpoint(store, task.id, proj, "test")
    assert chk.strategy == CHECKPOINT_GIT

    (proj / "keep.txt").write_text("v2-MODIFIED")
    (proj / "added.txt").write_text("new")

    restore_checkpoint(store, chk, proj)
    assert (proj / "keep.txt").read_text() == "v1"
    assert not (proj / "added.txt").exists()
    # Babysitter's own state survives the rollback.
    assert (proj / ".babysitter" / "babysitter.db").exists()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=proj,
                            capture_output=True, text=True)
    assert status.stdout.strip() == ""
    store.close()


def test_git_checkpoint_ignores_state_dir(tmp_path):
    """The checkpoint commit must not swallow .babysitter/ (db churn would
    dirty every diff)."""
    proj = tmp_path / "proj"
    proj.mkdir()
    git(proj, "init", "-q")
    git(proj, "config", "user.email", "t@t")
    git(proj, "config", "user.name", "t")
    (proj / "a.txt").write_text("a")
    store = BabysitterStore(proj / ".babysitter" / "babysitter.db")
    task = store.create_task("g", str(proj), "m", {})
    create_checkpoint(store, task.id, proj, "test")
    tracked = subprocess.run(["git", "ls-files"], cwd=proj, capture_output=True,
                             text=True).stdout
    assert ".babysitter" not in tracked
    store.close()


def test_newer_checkpoint_supersedes_older(task_in):
    store, task, root = task_in
    first = create_checkpoint(store, task.id, root, "one")
    second = create_checkpoint(store, task.id, root, "two")
    assert store.get_checkpoint(first.id).status == "superseded"
    assert store.latest_active_checkpoint(task.id).id == second.id


def test_retry_context_names_class_attempts_and_evidence():
    ctx = build_retry_context("test-fail", "FAILED x - assert 1 == 2", 1, 2,
                              last_action="write_file(foo.py)")
    assert "test-fail" in ctx
    assert "attempt 1 of 2" in ctx
    assert "assert 1 == 2" in ctx
    assert "write_file(foo.py)" in ctx


def test_restore_missing_copy_manifest_errors(task_in):
    store, task, root = task_in
    from babysitter.schema import Checkpoint, utcnow

    chk = Checkpoint(id="chk_bogus", task_id=task.id, created_at=utcnow(),
                     strategy=CHECKPOINT_COPY, ref=str(root / "nope"),
                     status="active", reason="t")
    store.save_checkpoint(chk)
    with pytest.raises(CheckpointError):
        restore_checkpoint(store, chk, root)
