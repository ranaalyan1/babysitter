"""Deliverable 2 tests: the verification engine.

Mechanics are tested in hermetic tmp git repos; then the engine is run
against REAL suites (this monorepo's vitest suite and Babysitter's own
pytest subset) to prove it observes genuine results.
"""

import shutil
import subprocess

import pytest

from babysitter.verify import (
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_UNAVAILABLE,
    VerificationEngine,
    git_diff_summary,
    run_command,
)

MONOREPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent.parent


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@babysitter.local")
    git(tmp_path, "config", "user.name", "babysitter-test")
    (tmp_path / "a.txt").write_text("hello\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_pass_verdict_when_all_checks_exit_zero(repo):
    (repo / "check.sh").write_text("#!/bin/sh\nexit 0\n")
    engine = VerificationEngine({"test": ["sh", "check.sh"]})
    report = engine.run(repo)
    assert report.verdict == VERDICT_PASS
    assert report.checks[0].exit_code == 0
    assert report.git.available


def test_fail_verdict_carries_failed_check_and_tail(repo):
    (repo / "check.sh").write_text("#!/bin/sh\necho boom >&2\nexit 3\n")
    engine = VerificationEngine({"test": ["sh", "check.sh"]})
    report = engine.run(repo)
    assert report.verdict == VERDICT_FAIL
    assert report.failed_check == "test"
    assert "boom" in report.tail
    assert report.checks[0].exit_code == 3


def test_typecheck_runs_first_and_short_circuits(repo):
    (repo / "bad.sh").write_text("#!/bin/sh\nexit 1\n")
    (repo / "good.sh").write_text("#!/bin/sh\nexit 0\n")
    engine = VerificationEngine(
        {"typecheck": ["sh", "bad.sh"], "test": ["sh", "good.sh"]}
    )
    report = engine.run(repo)
    assert report.verdict == VERDICT_FAIL
    assert report.failed_check == "typecheck"
    assert [c.name for c in report.checks] == ["typecheck"]  # test never ran


def test_timeout_is_failure_with_evidence(repo):
    engine = VerificationEngine({"test": ["sleep", "30"], "timeout_s": 1})
    report = engine.run(repo)
    assert report.verdict == VERDICT_FAIL
    assert "timed out" in report.tail


def test_missing_binary_is_unavailable_not_pass(repo):
    engine = VerificationEngine({"test": ["definitely-not-a-real-binary-xyz"]})
    report = engine.run(repo)
    assert report.verdict == VERDICT_UNAVAILABLE
    assert "not found" in report.unavailable_reason


def test_no_commands_configured_is_unavailable(repo):
    report = VerificationEngine({}).run(repo)
    assert report.verdict == VERDICT_UNAVAILABLE


def test_git_diff_reports_modified_and_untracked_files(repo):
    (repo / "a.txt").write_text("hello\nworld\n")
    (repo / "new.txt").write_text("one\ntwo\nthree\n")
    diff = git_diff_summary(repo)
    assert diff.available and not diff.clean
    by_path = {f["path"]: f for f in diff.files_changed}
    assert by_path["a.txt"] == {"path": "a.txt", "added": 1, "deleted": 0}
    assert by_path["new.txt"] == {"path": "new.txt", "added": 3, "deleted": 0}
    assert diff.insertions == 4


def test_git_diff_clean_tree(repo):
    diff = git_diff_summary(repo)
    assert diff.available and diff.clean and diff.files_changed == []


def test_git_diff_outside_repo_is_unavailable(tmp_path):
    diff = git_diff_summary(tmp_path)
    assert not diff.available
    assert "not a git repository" in diff.reason


def test_run_command_captures_output_and_timing(repo):
    result = run_command(["echo", "hi"], cwd=repo)
    assert result.exit_code == 0
    assert result.stdout_tail.strip() == "hi"
    assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# Real-project runs (not toy scripts): the engine must observe genuine
# results from genuine suites.
# ---------------------------------------------------------------------------

HAS_NODE_MODULES = (MONOREPO_ROOT / "node_modules").exists()
npx_vitest = shutil.which("npx") and HAS_NODE_MODULES


@pytest.mark.skipif(not npx_vitest, reason="needs monorepo node_modules + npx")
def test_real_js_suite_passes():
    """Run the REAL @test0/core vitest suite through the engine."""
    engine = VerificationEngine(
        {"test": ["npx", "vitest", "run"], "timeout_s": 240}
    )
    report = engine.run(MONOREPO_ROOT / "packages" / "core")
    assert report.verdict == VERDICT_PASS, report.tail
    assert report.checks[0].exit_code == 0


def test_real_python_suite_passes():
    """Run a REAL pytest subset (Babysitter's own schema tests) through it.

    Uses a fixed subset that spawns no subprocesses itself, so this can
    never recurse.
    """
    babysitter_root = MONOREPO_ROOT / "babysitter"
    engine = VerificationEngine(
        {
            "test": [
                "python3",
                "-m",
                "pytest",
                "tests/test_schema_store.py",
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            "timeout_s": 120,
        }
    )
    report = engine.run(babysitter_root)
    assert report.verdict == VERDICT_PASS, report.tail


@pytest.mark.skipif(not npx_vitest, reason="needs monorepo node_modules + npx")
def test_real_js_suite_failure_is_caught(tmp_path):
    """A REAL failing suite in a disposable copy of the real package must
    come back FAIL with the failing output attached — this is verification
    catching a broken change before 'completion'.

    Hermetic by design: copies the real package subtree + its real tests
    into tmp (symlinking node_modules), git-inits the copy, breaks it. No
    dependence on ambient git state.
    """
    proj = tmp_path / "proj"
    dest = proj / "packages" / "core"
    shutil.copytree(
        MONOREPO_ROOT / "packages" / "core",
        dest,
        ignore=shutil.ignore_patterns("node_modules", "dist"),
    )
    (proj / "node_modules").symlink_to(
        MONOREPO_ROOT / "node_modules", target_is_directory=True
    )
    git(proj, "init", "-q")
    git(proj, "config", "user.email", "test@babysitter.local")
    git(proj, "config", "user.name", "babysitter-test")
    git(proj, "add", ".")
    git(proj, "commit", "-qm", "snapshot of real package")
    breaking = dest / "test" / "zz-babysitter-probe.test.ts"
    breaking.write_text(
        "import { describe, expect, it } from 'vitest';\n"
        "describe('babysitter probe', () => {\n"
        "  it('fails on purpose', () => { expect(1 + 1).toBe(3); });\n"
        "});\n"
    )
    engine = VerificationEngine({"test": ["npx", "vitest", "run"], "timeout_s": 240})
    report = engine.run(dest)
    assert report.verdict == VERDICT_FAIL
    assert report.failed_check == "test"
    assert "probe" in report.tail or "failed" in report.tail.lower()
    diff = git_diff_summary(proj)
    assert any(
        f["path"].endswith("zz-babysitter-probe.test.ts") for f in diff.files_changed
    )
