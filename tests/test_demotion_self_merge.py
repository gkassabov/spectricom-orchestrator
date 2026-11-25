# filename: tests/test_demotion_self_merge.py
"""DEMOTION-SELF-MERGE-DETECT-1 (Kanban 937; AP-GEMMA demotion trigger PDT-57-1; S7-CORE-62).

Before each fire the daemon asks two questions of the repo the brief names, and a yes to either holds the queue
safety-red:
  * is every commit on the merge target's first-parent line after the recorded baseline inside a merge the
    orchestrator recorded — a `🔀 Merged <b> → <t> (<before> → <after>)` log line, or a ledger `merge` tip?
  * is the live checkout free of anything uncommitted or untracked outside the briefs folder?

Every history below is MADE with git, never mocked.
  SM-1…SM-5  the predicates (canon_assert)
  SM-6…SM-11 the daemon step, accept-main, and the fire loop
"""
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import canon_assert as ca  # noqa: E402
import queue_daemon  # noqa: E402
import slack_notify  # noqa: E402
from canon_assert import QueueRepo  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       capture_output=True, text=True)
    return r.stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    (path / ".gitignore").write_text("ignored/\n")
    (path / "briefs").mkdir()
    (path / "briefs" / ".keep").write_text("")
    (path / "f").write_text("0")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")
    return path


def _commit(repo: Path, name: str, msg: str) -> str:
    (repo / name).write_text(msg)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg)
    return _git(repo, "rev-parse", "HEAD")


def _route(repo: Path, branch: str, log: list) -> str:
    """What the orchestrator does: cut a branch from main, commit, merge back, log one `🔀 Merged` line."""
    before = _git(repo, "rev-parse", "main")
    _git(repo, "checkout", "-q", "-b", branch)
    _commit(repo, f"{branch}.txt", f"fix: {branch}")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", branch)
    after = _git(repo, "rev-parse", "main")
    log.append(f"02:13:53 [INFO   ] 🔀 Merged {branch} → main ({before[:7]} → {after[:7]})")
    return after


def _write_log(d: Path, lines: list, name="orch-0001-x-20261125-000000.log") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text("\n".join(lines) + "\n")
    return p


def _qr(path: Path, name="clinical-mp") -> QueueRepo:
    return QueueRepo(name=name, path=path)


# ═══════════════════════════════ SM-1…SM-5 · the predicates ═══════════════════════════════
def test_sm1_routes_the_orchestrator_logged_are_clean(tmp_path):
    repo = _repo(tmp_path / "r")
    base = _git(repo, "rev-parse", "main")
    log: list = []
    _route(repo, "orch-mp-1-a", log)
    _route(repo, "orch-mp-2-b", log)
    ranges = ca.logged_merge_ranges(_write_log(tmp_path / "logs", log).parent, "main")
    assert len(ranges) == 2
    assert ca.unrecorded_merges(_qr(repo), base, ranges) == []


def test_sm2_a_commit_straight_onto_main_is_named(tmp_path):
    repo = _repo(tmp_path / "r")
    base = _git(repo, "rev-parse", "main")
    log: list = []
    _route(repo, "orch-mp-1-a", log)
    stray = _commit(repo, "hand.txt", "hand edit on main")
    hits = ca.unrecorded_merges(_qr(repo), base, ca.logged_merge_ranges(_write_log(tmp_path / "logs", log).parent, "main"))
    assert [h.ref for h in hits] == [stray]
    assert hits[0].kind == "commit" and "hand edit on main" in str(hits[0])


def test_sm3_a_stray_a_later_route_fast_forwards_over_is_still_named(tmp_path):
    """The stray lands, then a route is cut from it and merged: the route's logged range starts AT the stray, so the
    stray is outside it."""
    repo = _repo(tmp_path / "r")
    base = _git(repo, "rev-parse", "main")
    log: list = []
    stray = _commit(repo, "hand.txt", "hand edit before the route")
    _route(repo, "orch-mp-1-a", log)
    hits = ca.unrecorded_merges(_qr(repo), base, ca.logged_merge_ranges(_write_log(tmp_path / "logs", log).parent, "main"))
    assert [h.ref for h in hits] == [stray]


def test_sm4_a_ledger_tip_covers_the_meta_lane_and_a_rewritten_target_is_named(tmp_path):
    repo = _repo(tmp_path / "r")
    base = _git(repo, "rev-parse", "main")
    tip = _commit(repo, "orch.py", "QUEUE-GUARDS-1 (meta lane merge)")
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"kind": "merge", "lane": "meta", "repo": "orchestrator", "target": "main",
                                  "target_tip": tip}) + "\n"
                      + json.dumps({"kind": "merge", "lane": "route", "repo": "clinical-mp", "target": "main",
                                    "target_tip": "f" * 40}) + "\n")
    ranges = ca.ledger_merge_tips(ledger, "orchestrator", "main")
    assert ranges == [(None, tip)]
    assert ca.unrecorded_merges(_qr(repo, "orchestrator"), base, ranges) == []
    after = _commit(repo, "orch2.py", "direct commit after the last merge")
    assert [h.ref for h in ca.unrecorded_merges(_qr(repo, "orchestrator"), base, ranges)] == [after]
    # the target rewritten under the baseline
    _git(repo, "reset", "-q", "--hard", base)
    _commit(repo, "other.py", "rewritten history")
    hits = ca.unrecorded_merges(_qr(repo, "orchestrator"), tip, ranges)
    assert len(hits) == 1 and hits[0].kind == "baseline"


def test_sm5_live_checkout_writes_outside_briefs_only(tmp_path):
    repo = _repo(tmp_path / "r")
    assert ca.live_checkout_writes(_qr(repo)) == []
    (repo / "briefs" / "000000001-x-1.handback.md").write_text("handback")
    (repo / "ignored").mkdir()
    (repo / "ignored" / "cache.bin").write_text("x")
    assert ca.live_checkout_writes(_qr(repo)) == []
    (repo / "stray").mkdir()
    (repo / "stray" / "copy.ts").write_text("x")
    (repo / "f").write_text("edited")
    hits = ca.live_checkout_writes(_qr(repo))
    assert sorted(h.ref for h in hits) == ["f", "stray/copy.ts"]
    assert all(h.kind == "live-write" for h in hits)
    assert ca.live_checkout_writes(_qr(tmp_path / "not-a-repo")) is None


# ═══════════════════════════════ SM-6…SM-11 · the daemon ═══════════════════════════════
class Daemon:
    def __init__(self, tmp_path: Path, monkeypatch):
        self.tmp = tmp_path
        self.orch = tmp_path / "orch"
        self.queue = self.orch / "queue"
        self.logs = tmp_path / "logs"
        self.repo = _repo(tmp_path / "clinical")
        (self.orch / "state").mkdir(parents=True)
        cfg = tmp_path / "repos.yaml"
        cfg.write_text(yaml.safe_dump({"repos": {"clinical-mp": {"project_dir": str(self.repo)}}}))
        for name, val in (("ORCH_DIR", self.orch), ("QUEUE_DIR", self.queue), ("QUEUE_DONE", self.queue / "done"),
                          ("QUEUE_FAILED", self.queue / "failed"), ("QUEUE_STATE", tmp_path / "queue-state.json"),
                          ("REPOS_CONFIG", cfg), ("LOG_DIR", self.logs)):
            monkeypatch.setattr(queue_daemon, name, val)
        monkeypatch.setattr(slack_notify, "send_slack", lambda text, blocks=None: True)
        self.d = queue_daemon.QueueDaemon()
        self.d.start_running = True
        self.d.config.update(cooldown_seconds=0, model="m", effort="e")
        self.fired: list = []
        self.log: list = []

        def _route_stub(cmd, batch_name, log_path):
            self.fired.append(batch_name)
            Path(log_path).write_text("route output\n")
            return 0
        self.d._run_route = _route_stub

    def state(self) -> dict:
        return json.loads(queue_daemon.self_merge_file("clinical-mp").read_text())

    def flush_log(self):
        _write_log(self.logs / "clinical-mp", self.log)


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    return Daemon(tmp_path, monkeypatch)


@pytest.mark.self_merge
def test_sm6_first_sight_records_the_baseline_and_fires(daemon, capsys):
    tip = _git(daemon.repo, "rev-parse", "main")
    assert daemon.d._self_merge_step("1-x.md", "clinical-mp") is True
    assert daemon.state()["baseline"] == tip and daemon.state()["by"] == "first sight"
    assert capsys.readouterr().out.count("🛡 self-merge: BASELINE") == 1


@pytest.mark.self_merge
def test_sm7_logged_routes_are_clean_and_the_baseline_moves(daemon, capsys):
    daemon.d._self_merge_step("1-x.md", "clinical-mp")
    tip = _route(daemon.repo, "orch-mp-1-a", daemon.log)
    daemon.flush_log()
    capsys.readouterr()
    assert daemon.d._self_merge_step("2-y.md", "clinical-mp") is True
    out = capsys.readouterr().out
    assert out.count("🛡 self-merge: CLEAN") == 1 and "HOLD" not in out
    assert daemon.state()["baseline"] == tip
    assert daemon.d.status != "paused"


@pytest.mark.self_merge
def test_sm8_a_stray_commit_holds_the_queue_safety_red(daemon, capsys):
    daemon.d._self_merge_step("1-x.md", "clinical-mp")
    base = daemon.state()["baseline"]
    stray = _commit(daemon.repo, "hand.txt", "hand edit on main")
    capsys.readouterr()
    assert daemon.d._self_merge_step("2-y.md", "clinical-mp") is False
    out = capsys.readouterr().out
    assert out.count("🛡 self-merge: HOLD — DEMOTION-SELF-MERGE") == 1 and "accept-main clinical-mp" in out
    assert daemon.d.status == "paused"
    assert daemon.d.paused_reason == f"safety-red:demotion-self-merge:clinical-mp:{stray[:12]}"
    assert daemon.d.current_batch is None
    assert daemon.state()["baseline"] == base    # not moved past a hit
    # the hold stands until George's ruling: a second look holds again
    assert daemon.d._self_merge_step("2-y.md", "clinical-mp") is False


@pytest.mark.self_merge
def test_sm9_a_write_in_the_live_checkout_holds_the_queue(daemon, capsys):
    daemon.d._self_merge_step("1-x.md", "clinical-mp")
    (daemon.repo / "c1a435c7").mkdir()
    (daemon.repo / "c1a435c7" / "x.ts").write_text("a stray copy")
    capsys.readouterr()
    assert daemon.d._self_merge_step("2-y.md", "clinical-mp") is False
    assert daemon.d.paused_reason == "safety-red:demotion-self-merge:clinical-mp:c1a435c7/x.ts"
    assert "written in the live checkout outside a route fire" in capsys.readouterr().out


@pytest.mark.self_merge
def test_sm10_accept_main_is_george_s_ruling_then_it_fires(daemon, capsys):
    daemon.d._self_merge_step("1-x.md", "clinical-mp")
    stray = _commit(daemon.repo, "hand.txt", "hand edit on main")
    assert daemon.d._self_merge_step("2-y.md", "clinical-mp") is False
    rc, msg = queue_daemon.accept_main("clinical-mp", "George 2026-11-25: legitimate hotfix")
    assert rc == 0 and stray[:8] in msg
    assert daemon.state()["baseline"] == stray and daemon.state()["by"].startswith("accept-main:")
    assert "accept-main clinical-mp" in (daemon.logs / "self-merge.log").read_text()
    daemon.d.status, daemon.d.paused_reason = "running", None
    assert daemon.d._self_merge_step("2-y.md", "clinical-mp") is True
    assert queue_daemon.main(["accept-main", "clinical-mp"]) == 2          # --reason is required
    assert queue_daemon.main(["accept-main", "nope", "--reason", "x"]) == 2


@pytest.mark.self_merge
def test_sm12_the_daemon_s_own_checkout_is_judged_on_commits_only(daemon, monkeypatch):
    """The orchestrator repo is ORCH_DIR: its untracked runtime files are not a write outside a route."""
    monkeypatch.setattr(queue_daemon, "ORCH_DIR", daemon.repo)
    (daemon.repo / "state").mkdir()
    daemon.d._self_merge_step("1-x.md", "clinical-mp")
    (daemon.repo / "session-log.md").write_text("runtime")
    assert daemon.d._self_merge_step("2-y.md", "clinical-mp") is True
    stray = _commit(daemon.repo, "orch.py", "direct commit")
    assert daemon.d._self_merge_step("3-z.md", "clinical-mp") is False
    assert daemon.d.paused_reason.endswith(stray[:12])


def test_sm11_off_by_default_in_the_suite_and_the_fire_loop_holds_before_admission(daemon, monkeypatch):
    # conftest: ORCH_SELF_MERGE=off unless marked — nothing is read or written
    assert daemon.d._self_merge_step("1-x.md", "clinical-mp") is True
    assert not queue_daemon.self_merge_file("clinical-mp").exists()
    # on, in the loop: a stray on main ⇒ nothing fires and the brief stays first in queue/
    monkeypatch.delenv("ORCH_SELF_MERGE", raising=False)
    daemon.d._self_merge_step("0-seed.md", "clinical-mp")
    _commit(daemon.repo, "hand.txt", "hand edit on main")
    daemon.queue.mkdir(parents=True, exist_ok=True)
    (daemon.queue / "120-x-1.md").write_text("#!queue repo=clinical-mp\n\n# 120-x-1\n")
    seen = []

    def _sleep(s):
        seen.append(s)
        if len(seen) >= 1:
            daemon.d.status = "stopped"
    monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=_sleep))
    daemon.d.run_loop()
    assert daemon.fired == []
    assert (daemon.queue / "120-x-1.md").exists()
    assert daemon.d.paused_reason.startswith("safety-red:demotion-self-merge:clinical-mp:")
