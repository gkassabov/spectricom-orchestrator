# filename: tests/test_running_marker.py
"""Tests for B2 — marker-file state/running.json watcher pattern."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator


class TestRunningMarker:

    def test_running_marker_written_with_correct_fields(self, tmp_path):
        """_write_running_marker creates state/running.json with expected keys."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            batch = tmp_path / "test-batch.md"
            batch.write_text("# test batch")
            orchestrator._write_running_marker(
                batch, "orchestrator", tmp_path,
                "orch-test-branch", None, False,
            )
            marker = tmp_path / "state" / "running.json"
            assert marker.exists()
            data = json.loads(marker.read_text())
            assert data["pid"] == os.getpid()
            assert data["batch_id"] == "test-batch"
            assert data["repo"] == "orchestrator"
            assert data["repo_path"] == str(tmp_path)
            assert data["branch"] == "orch-test-branch"
            assert "started_at" in data
            assert data["meta_fire_worktree"] is None
            assert data["is_self_mod"] is False

    def test_running_marker_cleared_on_success(self, tmp_path):
        """_clear_running_marker removes the marker file."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            marker_dir = tmp_path / "state"
            marker_dir.mkdir(parents=True, exist_ok=True)
            marker = marker_dir / "running.json"
            marker.write_text('{"pid": 1}')
            assert marker.exists()

            orchestrator._clear_running_marker()
            assert not marker.exists()

    def test_running_marker_cleared_on_exception(self, tmp_path):
        """Marker is cleaned up even when an exception occurs (try/finally semantics)."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            batch = tmp_path / "test-batch.md"
            batch.write_text("# test batch")
            orchestrator._write_running_marker(
                batch, "orchestrator", tmp_path,
                "orch-test-branch", None, False,
            )
            marker = tmp_path / "state" / "running.json"
            assert marker.exists()

            with pytest.raises(RuntimeError):
                try:
                    raise RuntimeError("simulated failure")
                finally:
                    orchestrator._clear_running_marker()

            assert not marker.exists()

    def test_stale_marker_detected_when_pid_dead(self, tmp_path):
        """Stale marker (dead PID) is auto-cleaned with warning."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            marker_dir = tmp_path / "state"
            marker_dir.mkdir(parents=True, exist_ok=True)
            marker = marker_dir / "running.json"
            marker.write_text(json.dumps({
                "pid": 99999,
                "batch_id": "old-batch",
                "started_at": "2026-01-01T00:00:00+00:00",
            }))

            result = orchestrator._check_stale_marker()
            assert result is True
            assert not marker.exists()

    def test_active_marker_blocks_concurrent_fire(self, tmp_path):
        """Active marker (own PID alive) blocks with exit 4."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            marker_dir = tmp_path / "state"
            marker_dir.mkdir(parents=True, exist_ok=True)
            marker = marker_dir / "running.json"
            marker.write_text(json.dumps({
                "pid": os.getpid(),
                "batch_id": "active-batch",
                "started_at": "2026-05-02T12:00:00+00:00",
            }))

            with pytest.raises(SystemExit) as exc_info:
                orchestrator._check_stale_marker()
            assert exc_info.value.code == 4


# ═══════════════════════════════════════════════════════════════════════════════════════
# S7-CORE-8 [ORCH-4] — the fire lock is PER REPO.
#
# System Prompt §5.19.1: cross-repo parallel fires are safe — different worktrees, different
# merge targets, no collision. That was true of the design and false of the implementation:
# one global state/running.json refused a clinical-mp route while an orchestrator meta-fire
# held it (observed 2026-09-12). The class above keeps the pre-[ORCH-4] no-repo call shape
# working, unmodified; these cover the per-repo behaviour.
# ═══════════════════════════════════════════════════════════════════════════════════════
def _marker(tmp_path, repo, pid, batch="b", started="2026-09-13T10:00:00+00:00"):
    d = tmp_path / "state"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"running-{repo}.json"
    f.write_text(json.dumps({"pid": pid, "batch_id": batch, "repo": repo,
                             "started_at": started, "branch": f"orch-{repo}"}))
    return f


DEAD_PID = 99999


class TestFireLockIsPerRepo:

    def test_two_fires_for_different_repos_both_proceed(self, tmp_path):
        """AC-O4-01: a LIVE fire in repo A does not refuse a fire in repo B, and taking B's
        lock does not disturb A's."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            batch = tmp_path / "b-a.md"
            batch.write_text("# a")
            orchestrator._write_running_marker(batch, "clinical-mp", tmp_path,
                                               "orch-mp-a", None, False)
            a_lock = tmp_path / "state" / "running-clinical-mp.json"
            assert a_lock.exists()
            assert json.loads(a_lock.read_text())["pid"] == os.getpid()  # live

            # A different repo is not refused — no SystemExit.
            assert orchestrator._check_stale_marker("orchestrator") is True

            batch_b = tmp_path / "b-b.md"
            batch_b.write_text("# b")
            orchestrator._write_running_marker(batch_b, "orchestrator", tmp_path,
                                               "orch-orch-b", None, True)
            b_lock = tmp_path / "state" / "running-orchestrator.json"

            assert a_lock.exists() and b_lock.exists(), "both fires hold their own lock"
            assert json.loads(a_lock.read_text())["batch_id"] == "b-a"
            assert json.loads(b_lock.read_text())["batch_id"] == "b-b"

    def test_second_fire_for_the_same_repo_is_refused_and_names_the_repo(self, tmp_path, capsys):
        """AC-O4-02: same repo ⇒ still serial, and the refusal says WHICH repo."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            _marker(tmp_path, "clinical-mp", os.getpid(), batch="live-batch")
            with pytest.raises(SystemExit) as exc:
                orchestrator._check_stale_marker("clinical-mp")
            assert exc.value.code == 4
            err = capsys.readouterr().err
            assert "clinical-mp" in err, "the refusal must name the repo"
            assert "live-batch" in err
            assert "Another orchestrator fire is in progress" not in err, \
                "the bare, repo-less wording is what misled the operator on 2026-09-12"

    def test_releasing_one_repos_lock_leaves_the_others_alone(self, tmp_path):
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            a = _marker(tmp_path, "clinical-mp", os.getpid())
            b = _marker(tmp_path, "orchestrator", os.getpid())
            orchestrator._clear_running_marker("clinical-mp")
            assert not a.exists()
            assert b.exists(), "clearing repo A must not release repo B's lock"


class TestStaleCleanupIsPerRepo:
    """AC-O4-04 — a dead PID under one repo never clears another repo's live lock."""

    def test_stale_repo_a_is_cleaned_and_live_repo_b_survives(self, tmp_path):
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            a = _marker(tmp_path, "clinical-mp", DEAD_PID)
            b = _marker(tmp_path, "orchestrator", os.getpid())
            assert orchestrator._check_stale_marker("clinical-mp") is True
            assert not a.exists(), "the dead PID's lock is cleaned"
            assert b.exists(), "repo B's LIVE lock must survive repo A's cleanup"

    def test_stale_repo_b_is_cleaned_and_live_repo_a_survives(self, tmp_path):
        """The other direction — asserted separately so a one-sided fix cannot pass."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            a = _marker(tmp_path, "clinical-mp", os.getpid())
            b = _marker(tmp_path, "orchestrator", DEAD_PID)
            assert orchestrator._check_stale_marker("orchestrator") is True
            assert not b.exists()
            assert a.exists()

    def test_a_live_fire_elsewhere_does_not_make_this_repo_stale_or_blocked(self, tmp_path):
        """No lock of its own + a live lock elsewhere ⇒ proceed, touching nothing."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            b = _marker(tmp_path, "orchestrator", os.getpid())
            assert orchestrator._check_stale_marker("clinical-mp") is True
            assert b.exists()


class TestEveryReaderOfTheMarkerStillWorks:
    """AC-O4-03 — enumerated by grep over the repo. Every reader of the running marker:

      1. orchestrator.py `_check_stale_marker`  — the lock itself; now per repo.
      2. orchestrator.py `show_status`          — reads the per-repo locks, legacy fallback.
      3. qstat.sh          `$ORCH/state/running.json` (pid, batch_id, branch) — mirror.
      4. watchdog.sh       `$ORCH/state/running.json`                          — mirror.
      5. orch-dashboard.py `$ORCH/running.json`      — the OTHER, dashboard marker
         (RUNNING_FILE / write_running / clear_running). Not a lock, not touched by [ORCH-4].
      6. verify-019.sh, pcfg-chain.sh `$ORCH/running.json` — likewise the dashboard marker.

    3 and 4 know only the single legacy path, so state/running.json is kept as a mirror of
    the newest live lock rather than deleted (brief decision 2).
    """

    def test_the_legacy_path_still_exists_and_carries_the_keys_the_shell_readers_parse(self, tmp_path):
        """qstat.sh reads ['pid'], ['batch_id'] and ['branch'] out of state/running.json with
        a bare json.load; watchdog.sh stats the same path."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            batch = tmp_path / "live.md"
            batch.write_text("# live")
            orchestrator._write_running_marker(batch, "clinical-mp", tmp_path,
                                               "orch-mp-live", None, False)
            legacy = tmp_path / "state" / "running.json"
            assert legacy.exists(), "qstat.sh/watchdog.sh would see an idle queue otherwise"
            d = json.loads(legacy.read_text())
            assert d["pid"] == os.getpid() and d["batch_id"] == "live" and d["branch"] == "orch-mp-live"
            assert d["repo"] == "clinical-mp"

    def test_the_mirror_reflects_the_newest_live_fire_and_clears_with_the_last_one(self, tmp_path):
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            _marker(tmp_path, "clinical-mp", os.getpid(), batch="older",
                    started="2026-09-13T09:00:00+00:00")
            orchestrator._refresh_legacy_running_mirror()
            legacy = tmp_path / "state" / "running.json"
            assert json.loads(legacy.read_text())["batch_id"] == "older"

            _marker(tmp_path, "orchestrator", os.getpid(), batch="newer",
                    started="2026-09-13T11:00:00+00:00")
            orchestrator._refresh_legacy_running_mirror()
            assert json.loads(legacy.read_text())["batch_id"] == "newer"

            orchestrator._clear_running_marker("orchestrator")
            assert json.loads(legacy.read_text())["batch_id"] == "older", \
                "with one fire still live the mirror must show it, not vanish"

            orchestrator._clear_running_marker("clinical-mp")
            assert not legacy.exists(), "no live fire ⇒ no marker, as the shell readers expect"

    def test_show_status_reports_a_per_repo_lock(self, tmp_path, capsys):
        with patch.object(orchestrator, "ORCH_DIR", tmp_path), \
             patch.object(orchestrator, "STATE_FILE", tmp_path / "state.json"), \
             patch.object(orchestrator, "BRIEFS_DIR", tmp_path / "briefs"):
            _marker(tmp_path, "clinical-mp", os.getpid(), batch="live-batch")
            orchestrator.show_status()
            out = capsys.readouterr().out
            assert "ACTIVE FIRE" in out and "clinical-mp" in out and "live-batch" in out

    def test_show_status_still_reads_a_pre_orch4_marker(self, tmp_path, capsys):
        """Migration: a marker written by the old code lives at the legacy path with no
        per-repo file beside it. `status` must still show it."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path), \
             patch.object(orchestrator, "STATE_FILE", tmp_path / "state.json"), \
             patch.object(orchestrator, "BRIEFS_DIR", tmp_path / "briefs"):
            d = tmp_path / "state"
            d.mkdir(parents=True)
            (d / "running.json").write_text(json.dumps({
                "pid": os.getpid(), "batch_id": "old-shape", "repo": "yorsie",
                "started_at": "2026-09-13T10:00:00+00:00", "branch": "orch-y"}))
            orchestrator.show_status()
            out = capsys.readouterr().out
            assert "ACTIVE FIRE" in out and "old-shape" in out

    def test_a_pre_orch4_marker_still_locks_its_own_repo(self, tmp_path):
        """Migration, the lock half: an old global marker naming repo X refuses X ...."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            d = tmp_path / "state"
            d.mkdir(parents=True)
            (d / "running.json").write_text(json.dumps({
                "pid": os.getpid(), "batch_id": "old-shape", "repo": "yorsie",
                "started_at": "2026-09-13T10:00:00+00:00"}))
            with pytest.raises(SystemExit) as exc:
                orchestrator._check_stale_marker("yorsie")
            assert exc.value.code == 4
            # ... and does NOT refuse a different repo.
            assert orchestrator._check_stale_marker("clinical-mp") is True

    def test_the_dashboard_marker_is_a_separate_file_and_is_untouched(self, tmp_path):
        """Reader 5/6: RUNNING_FILE is ORCH_DIR/running.json, not state/running.json. It is a
        display marker, never consulted by the lock, and [ORCH-4] does not repath it."""
        assert orchestrator.RUNNING_FILE.name == "running.json"
        assert orchestrator.RUNNING_FILE.parent.name != "state"
        src = (Path(__file__).parent.parent / "orchestrator.py").read_text()
        lock = src.split("def _check_stale_marker(")[1].split("\ndef ")[0]
        assert "RUNNING_FILE" not in lock, "the lock must not consult the dashboard marker"


class TestMarkerSlug:

    def test_repo_names_that_are_not_filenames_are_slugged(self, tmp_path):
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            p = orchestrator._running_marker_path("../evil/repo")
            assert p.parent == tmp_path / "state", "a repo name cannot escape state/"
            assert p.name.startswith("running-") and p.name.endswith(".json")

    def test_no_repo_means_the_legacy_path(self, tmp_path):
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            assert orchestrator._running_marker_path() == tmp_path / "state" / "running.json"
            assert orchestrator._running_marker_path("") == tmp_path / "state" / "running.json"

    def test_a_live_lock_outranks_a_dead_one_in_the_mirror(self, tmp_path):
        """qstat.sh reads ONE file. A dead clinical-mp lock must not make it report the queue
        dead while an orchestrator fire is actually burning."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            _marker(tmp_path, "clinical-mp", DEAD_PID, batch="dead",
                    started="2026-09-13T23:00:00+00:00")   # newer, but dead
            _marker(tmp_path, "orchestrator", os.getpid(), batch="live",
                    started="2026-09-13T08:00:00+00:00")   # older, but alive
            orchestrator._refresh_legacy_running_mirror()
            assert json.loads((tmp_path / "state" / "running.json").read_text())["batch_id"] == "live"

    def test_with_only_dead_locks_the_mirror_still_reports_one(self, tmp_path):
        """qstat.sh's `❌ QUEUE DEAD | stale PID` branch stays reachable."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            _marker(tmp_path, "clinical-mp", DEAD_PID, batch="dead")
            orchestrator._refresh_legacy_running_mirror()
            assert json.loads((tmp_path / "state" / "running.json").read_text())["batch_id"] == "dead"

    def test_watchdog_cleanup_is_per_repo_and_pid_aware(self):
        """Reader 4's cleanup half: watchdog.sh rm'd the single marker. It must now drop the
        per-repo locks too — but only the dead ones."""
        wd = (Path(__file__).parent.parent / "watchdog.sh").read_text()
        body = wd.split("cleanup_orphan_state() {")[1].split("\n}")[0]
        assert "state/running-*.json" in body, "watchdog would leave orphan per-repo locks behind"
        assert "kill -0" in body, "it must not delete a LIVE repo's lock"
