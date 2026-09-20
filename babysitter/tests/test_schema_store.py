"""Deliverable 1 tests: the frozen schema and its SQLite enforcement."""

import pytest

from babysitter import schema as S
from babysitter.store import BabysitterStore


@pytest.fixture()
def store(tmp_path):
    s = BabysitterStore(tmp_path / ".babysitter" / "babysitter.db")
    yield s
    s.close()


def make_task(store, **kw):
    args = {
        "goal": "fix the bug",
        "project_root": "/tmp/proj",
        "model": "weak-model",
        "config": {"verify": {"test": ["true"]}},
    }
    args.update(kw)
    return store.create_task(**args)


def test_create_task_logs_task_created(store):
    task = make_task(store)
    assert task.id.startswith("bst_")
    assert task.status == S.STATUS_OPEN
    events = store.list_events(task.id)
    assert [e.kind for e in events] == [S.KIND_TASK_CREATED]
    assert events[0].payload["goal"] == "fix the bug"


def test_status_transitions_log_task_status_and_freeze_at_terminal(store):
    task = make_task(store)
    store.set_task_status(task.id, S.STATUS_IN_PROGRESS)
    store.set_task_status(task.id, S.STATUS_VERIFIED_COMPLETE, "tests passed")
    assert store.get_task(task.id).status == S.STATUS_VERIFIED_COMPLETE
    with pytest.raises(ValueError):
        store.set_task_status(task.id, S.STATUS_IN_PROGRESS)


def test_unknown_status_rejected(store):
    task = make_task(store)
    with pytest.raises(ValueError):
        store.set_task_status(task.id, "done-because-model-said-so")


def test_unknown_event_kind_rejected(store):
    task = make_task(store)
    with pytest.raises(ValueError):
        store.log_event(task.id, S.STAGE_OBSERVE, "validation.maybe", "nope")


def test_wrong_stage_for_kind_rejected(store):
    task = make_task(store)
    with pytest.raises(ValueError):
        # validation.passed belongs to stage "validate", not "observe"
        store.log_event(task.id, S.STAGE_OBSERVE, S.KIND_VALIDATION_PASSED, "x")


def test_every_frozen_kind_is_loggable_under_its_stage(store):
    task = make_task(store)
    for kind in sorted(S.EVENT_KINDS):
        store.log_event(task.id, S.KIND_STAGES[kind], kind, f"probe {kind}")
    assert store.count_events(task.id, S.KIND_TASK_CREATED) == 2
    assert len(store.list_events(task.id, limit=100)) == len(S.EVENT_KINDS) + 1


def test_oversize_payload_rejected(store):
    task = make_task(store)
    with pytest.raises(ValueError):
        store.log_event(
            task.id,
            S.STAGE_OBSERVE,
            S.KIND_MODEL_TURN,
            "too big",
            {"blob": "x" * (20 * 1024)},
        )


def test_events_filtered_by_kind_and_stage(store):
    task = make_task(store)
    store.log_event(task.id, S.STAGE_VALIDATE, S.KIND_VALIDATION_PASSED, "ok")
    store.log_event(task.id, S.STAGE_VALIDATE, S.KIND_VALIDATION_FAILED, "bad")
    by_kind = store.list_events(task.id, kinds=[S.KIND_VALIDATION_FAILED])
    assert [e.kind for e in by_kind] == [S.KIND_VALIDATION_FAILED]
    by_stage = store.list_events(task.id, stages=[S.STAGE_VALIDATE])
    assert {e.kind for e in by_stage} == {
        S.KIND_VALIDATION_PASSED,
        S.KIND_VALIDATION_FAILED,
    }


def test_checkpoint_roundtrip(store):
    task = make_task(store)
    from babysitter.schema import Checkpoint, utcnow

    chk = Checkpoint(
        id="chk_test123",
        task_id=task.id,
        created_at=utcnow(),
        strategy=S.CHECKPOINT_GIT,
        ref="abc123",
        status=S.CHECKPOINT_ACTIVE,
        reason="pre-change",
    )
    store.save_checkpoint(chk)
    assert store.latest_active_checkpoint(task.id).id == "chk_test123"
    store.set_checkpoint_status("chk_test123", S.CHECKPOINT_RESTORED)
    assert store.latest_active_checkpoint(task.id) is None
    assert store.get_checkpoint("chk_test123").status == S.CHECKPOINT_RESTORED


def test_schema_version_guard_rejects_foreign_db(store, tmp_path):
    import sqlite3

    other = tmp_path / "other.db"
    conn = sqlite3.connect(str(other))
    conn.executescript(S.DDL)
    conn.execute("INSERT INTO schema_meta(key, value) VALUES ('version', '99')")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError):
        BabysitterStore(other)
