"""ORCH-QUEUE-PARK-RED-1 (SD-2, George 2026-11-16 17:41 "Agree").

(a) A FAIL(product) route is parked in queue/held/parked/ with a reason file; the queue keeps firing briefs that neither
    `## Depends-on:` it nor share an ALLOWED path with it. It still stops on a machine fault it cannot re-check, on a red
    already on main, and on two product reds in a row.
(b) A BLOCKED(environment) route gets ONE automatic gates-only re-check (`<stem>-recheck.md`, `## Re-gate of:`), fired
    next and alone; a red re-check stops the queue.
G-3 A verdict override is appended (approver, reason), never written over the gate's own line; the re-gate reads it.
"""
import json
import os
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orchestrator  # noqa: E402
import queue_daemon  # noqa: E402
import executor_auth  # noqa: E402

PRODUCT = ("failed", "FAIL(product)", "FAIL(product) — unit: regression (newly-failing file(s): src/a.test.ts)")
ENV = ("blocked", "BLOCKED(environment)", "BLOCKED(environment) — build: timeout (no exit observed)")
ON_MAIN = ("blocked", "BLOCKED(environment)", "BLOCKED(environment) — unit: already-red-on-main (src/x.test.ts red at "
                                               "the merge base too)")
PASS = ("passed", "PASS", None)


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()


class Q:
    """A daemon over a scratch queue; each fired route answers from `script` and records itself in state.json the way
    `orchestrator.py run` does."""

    def __init__(self, tmp_path, monkeypatch, meta_fire=False):
        self.tmp = tmp_path
        self.orch = tmp_path / "orch"
        (self.orch / "state").mkdir(parents=True)
        self.queue = self.orch / "queue"
        self.queue.mkdir()
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "base")
        self.cfg = tmp_path / "repos.yaml"
        self.cfg.write_text(yaml.safe_dump({"repos": {
            "cmp": {"project_dir": str(self.repo), "branch_prefix": "orch-mp", "merge_target": "main",
                    **({"meta_fire": True} if meta_fire else {})},
            "other": {"project_dir": str(self.repo), "branch_prefix": "orch-o", "merge_target": "main"}}}))
        for name, val in (("ORCH_DIR", self.orch), ("QUEUE_DIR", self.queue), ("QUEUE_DONE", self.queue / "done"),
                          ("QUEUE_FAILED", self.queue / "failed"), ("QUEUE_STATE", tmp_path / "queue-state.json"),
                          ("REPOS_CONFIG", self.cfg), ("LOG_DIR", tmp_path / "logs")):
            monkeypatch.setattr(queue_daemon, name, val)
        monkeypatch.setattr(queue_daemon, "full_gate_schedule", lambda: {})
        monkeypatch.setattr(queue_daemon.admission, "admit", lambda *a, **k: (True, "admitted"))
        monkeypatch.setattr(queue_daemon.admission, "release", lambda *a, **k: None)
        monkeypatch.setenv(executor_auth.PROBE_VAR, "off")
        monkeypatch.delenv(queue_daemon.PARK_ENV, raising=False)
        self.script, self.fired = {}, []
        d = self.d = queue_daemon.QueueDaemon()
        d.start_running = True
        d.config.update(cooldown_seconds=0, stop_on_failure=True)
        d._run_route = self._route
        monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=lambda s: setattr(d, "status", "stopped")))

    def branch(self, stem, prefix="orch-mp"):
        """The route branch with one commit of its own (not merged), as a red route leaves it."""
        git(self.repo, "checkout", "-q", "-b", f"{prefix}-{stem}", "main")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", f"route {stem}")
        git(self.repo, "checkout", "-q", "main")
        return git(self.repo, "rev-parse", f"{prefix}-{stem}")

    def brief(self, stem, allowed=("src/a.ts",), repo="cmp", extra=""):
        files = "".join(f"- `{p}`\n" for p in (allowed or ()))
        body = (f"#!queue repo={repo}\n# {stem}\n{extra}" +
                (f"\n## A2 · ALLOWED FILES\n{files}" if allowed is not None else "") + "\n## STOP\n(a)\n")
        p = self.queue / f"{stem}.md"
        p.write_text(body)
        return p

    def _route(self, cmd, batch_name, log_path):
        self.fired.append(batch_name)
        status, gate, error = self.script.get(batch_name, PASS)
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(f"🏁 FINAL STATUS: {status} | gate: {gate}\n")
        state = self.orch / "state.json"
        data = json.loads(state.read_text()) if state.exists() else {"completed": [], "failed": [], "stopped": []}
        key = {"passed": "completed", "stopped": "stopped"}.get(status, "failed")
        data[key].append({"batch_file": batch_name, "status": status, "started": datetime.now().isoformat(),
                          "gate_outcome": gate, "error": error, "exit_code": 0})
        state.write_text(json.dumps(data))
        return {"passed": 0, "stopped": 5}.get(status, 1)

    def run(self):
        self.d.run_loop()
        return self.d

    def at(self, *parts):
        return (self.queue.joinpath(*parts)).exists()


@pytest.fixture
def q(tmp_path, monkeypatch):
    return Q(tmp_path, monkeypatch)


# ── P-1 · (a) park a product red; unrelated work keeps firing ───────────────────────────────────────────────────
class TestP1Park:

    def test_a_product_red_is_parked_and_independent_work_fires(self, q, capsys):
        q.brief("701-a", ["src/a.ts"])
        q.brief("702-b", ["src/b.ts"])
        q.brief("703-c", ["src/a.ts", "src/c.ts"])
        q.brief("704-d", ["src/d.ts"], extra="## Depends-on: 701-a\n")
        q.script["701-a.md"] = PRODUCT
        d = q.run()
        out = capsys.readouterr().out
        assert q.fired == ["701-a.md", "702-b.md"], q.fired
        assert d.paused_reason is None and d.status == "stopped"
        assert q.at("held", "parked", "701-a.md") and not q.at("failed", "701-a.md")
        reason = (q.queue / "held" / "parked" / "701-a.reason").read_text()
        assert "PARKED after FAIL(product)" in reason and "src/a.test.ts" in reason and "orch-mp-701-a" in reason
        assert q.at("703-c.md"), "703 shares src/a.ts: it waits in queue/"
        assert "703-c.md: WAITING — shares src/a.ts with parked 701-a.md" in out, out
        assert q.at("held", "depends-on", "704-d.md"), "704 depends on 701: A11 holds it"
        assert "🅿 PARKED: 701-a.md — FAIL(product)" in out
        assert d.failed[0]["red"] == "product" and [e["file"] for e in d.completed] == ["702-b.md"]

    def test_moving_the_parked_brief_out_releases_the_waiter(self, q):
        q.brief("701-a", ["src/a.ts"])
        q.brief("703-c", ["src/a.ts"])
        q.script["701-a.md"] = PRODUCT
        q.run()
        assert q.fired == ["701-a.md"]
        (q.queue / "held" / "parked" / "701-a.md").rename(q.queue / "failed" / "701-a.md")
        q.d.status = "running"
        q.run()
        assert q.fired == ["701-a.md", "703-c.md"]

    def test_a_glob_overlap_is_shared(self, q, capsys):
        q.brief("701-a", ["src/lib/**"])
        q.brief("703-c", ["src/lib/x.ts"])
        q.script["701-a.md"] = PRODUCT
        q.run()
        assert q.fired == ["701-a.md"] and "shares src/lib/x.ts with parked 701-a.md" in capsys.readouterr().out

    def test_a_brief_with_no_allowed_list_waits_fail_closed(self, q, capsys):
        q.brief("701-a", ["src/a.ts"])
        q.brief("703-c", allowed=None)
        q.script["701-a.md"] = PRODUCT
        q.run()
        assert q.fired == ["701-a.md"]
        assert "ALLOWED FILES list is missing" in capsys.readouterr().out

    def test_control_the_same_path_in_another_repo_is_not_shared(self, q):
        q.brief("701-a", ["src/a.ts"])
        q.brief("703-c", ["src/a.ts"], repo="other")
        q.script["701-a.md"] = PRODUCT
        q.run()
        assert q.fired == ["701-a.md", "703-c.md"]

    def test_two_product_reds_in_a_row_stop_everything(self, q, capsys):
        for s, p in (("701-a", "src/a.ts"), ("702-b", "src/b.ts"), ("703-c", "src/c.ts")):
            q.brief(s, [p])
        q.script.update({"701-a.md": PRODUCT, "702-b.md": PRODUCT})
        d = q.run()
        assert q.fired == ["701-a.md", "702-b.md"]
        assert d.paused_reason == "two-product-reds:701-a.md,702-b.md"
        assert q.at("held", "parked", "701-a.md") and q.at("held", "parked", "702-b.md") and q.at("703-c.md")
        assert "two product reds in a row" in capsys.readouterr().out

    def test_control_a_pass_between_two_product_reds_ends_the_row(self, q):
        for s, p in (("701-a", "src/a.ts"), ("702-b", "src/b.ts"), ("703-c", "src/c.ts"), ("704-d", "src/d.ts")):
            q.brief(s, [p])
        q.script.update({"701-a.md": PRODUCT, "703-c.md": PRODUCT})
        d = q.run()
        assert q.fired == ["701-a.md", "702-b.md", "703-c.md", "704-d.md"] and d.paused_reason is None

    def test_status_shows_the_parked_tray(self, q, capsys):
        q.brief("701-a", ["src/a.ts"])
        q.script["701-a.md"] = PRODUCT
        q.run()
        st = q.d.get_status()
        assert [p["file"] for p in st["parked"]] == ["701-a.md"] and "FAIL(product)" in st["parked"][0]["reason"]
        capsys.readouterr()
        assert queue_daemon.main(["status"]) in (0, None)
        assert "🅿 parked in queue/held/parked/: 701-a.md" in capsys.readouterr().out


# ── P-2 · (b) one automatic gates-only re-check of an environment red ────────────────────────────────────────────
class TestP2Recheck:

    def test_an_environment_red_is_rechecked_once_next_and_lands(self, q, capsys):
        tip = q.branch("701-a")
        q.brief("701-a", ["src/a.ts"])
        q.brief("702-b", ["src/b.ts"])
        q.script["701-a.md"] = ENV
        d = q.run()
        out = capsys.readouterr().out
        assert q.fired == ["701-a.md", "701-a-recheck.md", "702-b.md"], q.fired
        assert d.paused_reason is None and d.recheck is None
        text = (q.queue / "done" / "701-a-recheck.md").read_text()
        assert text.splitlines()[0] == "#!queue repo=cmp"
        assert text.splitlines()[1] == f"## Re-gate of: orch-mp-701-a {tip}"
        assert "ORCH-QUEUE-PARK-RED-1 (b)" in text and "## A2 · ALLOWED FILES" in text
        assert "one automatic gates-only re-check queued, fired next and alone: 701-a-recheck.md" in out
        assert q.at("failed", "701-a.md")

    def test_the_recheck_fires_before_a_brief_that_sorts_first(self, q):
        q.brief("aaa-first", ["src/z.ts"])
        (q.queue / "zzz-recheck.md").write_text("#!queue repo=cmp\n")
        q.d.recheck = "zzz-recheck.md"
        assert q.d._next_brief(q.d._scan_queue()).name == "zzz-recheck.md"

    def test_a_red_recheck_stops_everything(self, q, capsys):
        q.branch("701-a")
        q.brief("701-a", ["src/a.ts"])
        q.brief("702-b", ["src/b.ts"])
        q.script.update({"701-a.md": ENV, "701-a-recheck.md": ENV})
        d = q.run()
        assert q.fired == ["701-a.md", "701-a-recheck.md"]
        assert d.paused_reason == "recheck-red:701-a-recheck.md" and q.at("702-b.md")
        assert "is red too" in capsys.readouterr().out

    def test_a_product_red_recheck_also_stops_and_is_not_parked(self, q):
        q.branch("701-a")
        q.brief("701-a", ["src/a.ts"])
        q.script.update({"701-a.md": ENV, "701-a-recheck.md": PRODUCT})
        d = q.run()
        assert d.paused_reason == "recheck-red:701-a-recheck.md" and not q.at("held", "parked", "701-a-recheck.md")

    def test_no_route_branch_means_no_recheck_and_a_stop(self, q, capsys):
        q.brief("701-a", ["src/a.ts"])
        q.brief("702-b", ["src/b.ts"])
        q.script["701-a.md"] = ENV
        d = q.run()
        assert q.fired == ["701-a.md"] and d.paused_reason == "stop-on-failure:701-a.md"
        out = capsys.readouterr().out
        assert "no automatic re-check — no route branch orch-mp-701-a" in out and "Pausing queue." in out

    def test_the_meta_fire_lane_is_not_rechecked(self, tmp_path, monkeypatch, capsys):
        q = Q(tmp_path, monkeypatch, meta_fire=True)
        q.branch("701-a")
        q.brief("701-a", ["src/a.ts"])
        q.script["701-a.md"] = ENV
        assert q.run().paused_reason == "stop-on-failure:701-a.md"
        assert "meta-fire lane" in capsys.readouterr().out and not q.at("701-a-recheck.md")

    def test_a_hand_regate_that_is_red_is_not_rechecked(self, q):
        q.branch("701-a")
        q.brief("701-a", ["src/a.ts"], extra="## Re-gate of: orch-mp-700-z abc1234\n")
        q.script["701-a.md"] = ENV
        assert q.run().paused_reason == "stop-on-failure:701-a.md"
        assert not q.at("701-a-recheck.md")

    def test_a_red_already_on_main_stops_everything_with_no_recheck(self, q, capsys):
        q.branch("701-a")
        q.brief("701-a", ["src/a.ts"])
        q.brief("702-b", ["src/b.ts"])
        q.script["701-a.md"] = ON_MAIN
        d = q.run()
        assert q.fired == ["701-a.md"] and d.paused_reason == "red-on-main:701-a.md"
        assert not q.at("701-a-recheck.md") and "main is red" in capsys.readouterr().out


# ── P-3 · controls: everything else stops as before; the switches ────────────────────────────────────────────────
class TestP3Controls:

    @pytest.mark.parametrize("record", [None, ("incomplete", None, "INCOMPLETE(timeout) — exit -1"),
                                        ("failed", "PASS", "ORCH-CONFLICT-1 invariant — x"),
                                        ("tampered", None, "TAMPERED")])
    def test_any_other_red_stops_as_before(self, q, capsys, record):
        q.brief("701-a", ["src/a.ts"])
        q.brief("702-b", ["src/b.ts"])
        if record is None:
            q.d._run_route = lambda c, b, l: (q.fired.append(b), 1)[1]      # no state.json record at all
        else:
            q.script["701-a.md"] = record
        d = q.run()
        assert q.fired == ["701-a.md"] and d.paused_reason == "stop-on-failure:701-a.md"
        assert q.at("failed", "701-a.md") and "stop_on_failure=true. Pausing queue." in capsys.readouterr().out

    def test_the_kill_switch_pauses_every_red_as_before(self, q, monkeypatch):
        monkeypatch.setenv(queue_daemon.PARK_ENV, "off")
        q.brief("701-a", ["src/a.ts"])
        q.brief("702-b", ["src/b.ts"])
        q.script["701-a.md"] = PRODUCT
        d = q.run()
        assert q.fired == ["701-a.md"] and d.paused_reason == "stop-on-failure:701-a.md" and q.at("failed", "701-a.md")

    def test_stop_on_failure_false_never_pauses_as_before(self, q):
        q.d.config["stop_on_failure"] = False
        q.brief("701-a", ["src/a.ts"])
        q.brief("702-b", ["src/a.ts"])
        q.script["701-a.md"] = PRODUCT
        d = q.run()
        assert q.fired == ["701-a.md", "702-b.md"] and d.paused_reason is None and q.at("failed", "701-a.md")

    def test_route_record_takes_the_newest_record_at_or_after_the_fire(self, q):
        (q.orch / "state.json").write_text(json.dumps({"failed": [
            {"batch_file": "x.md", "started": "2026-11-16T10:00:00", "status": "failed", "gate_outcome": "FAIL(product)"},
            {"batch_file": "x.md", "started": "2026-11-17T01:00:00", "status": "blocked",
             "gate_outcome": "BLOCKED(environment)"}], "completed": [
            {"batch_file": "x.md", "started": "2026-11-15T01:00:00", "status": "passed", "gate_outcome": "PASS"}]}))
        assert queue_daemon.route_record("x.md", "2026-11-17T00:59:59.5")["status"] == "blocked"
        assert queue_daemon.route_record("x.md", "2026-11-17T02:00:00") is None
        assert queue_daemon.route_record("y.md", "2026-11-01T00:00:00") is None

    def test_red_kind_table(self):
        k = lambda s, g, e=None, **x: queue_daemon.red_kind({"status": s, "gate_outcome": g, "error": e, **x})
        assert k(*PRODUCT) == "product" and k(*ENV) == "environment" and k(*ON_MAIN) == "red-on-main"
        assert k("failed", "FAIL(product)", "x", tampered="moved") == "other"
        assert k("failed", "BLOCKED(environment)") == "other" and k("blocked", "FAIL(product)") == "other"
        assert queue_daemon.red_kind(None) == "other"

    def test_the_already_red_signal_is_the_gates_own(self):
        assert queue_daemon.ALREADY_RED_SIGNAL == orchestrator.ALREADY_RED_SIGNAL


# ── P-4 · G-3: a verdict override is appended, never written over ─────────────────────────────────────────────────
class TestP4Override:

    def _route_branch(self, q, note="PRE-MERGE GATE: FAIL(product) — build: exit -1 (no F-20 environment signal)"):
        tip = q.branch("626b-x")
        if note:
            git(q.repo, "notes", "add", "-m", note, tip)
        return tip

    @pytest.mark.parametrize("args,why", [(("PASS", "George", "it was a timeout really"), "verdict must be one of"),
                                          (("BLOCKED(environment)", " ", "it was a timeout"), "--by"),
                                          (("BLOCKED(environment)", "George", "timeout"), "3 words")])
    def test_a_bad_override_is_refused(self, args, why):
        line, err = queue_daemon.override_line(*args)
        assert line is None and why in err

    def test_an_override_is_appended_and_the_gate_line_kept(self, q):
        tip = self._route_branch(q)
        rc, msg = queue_daemon.append_override("cmp", "orch-mp-626b-x", "BLOCKED(environment)", "George",
                                               "build leg timeout under load 17-19 (L-437)")
        assert rc == 0, msg
        note = git(q.repo, "notes", "show", tip).splitlines()
        assert note[0].startswith("PRE-MERGE GATE: FAIL(product)"), "the gate's own line is first and unchanged"
        assert note[-1].startswith("PRE-MERGE GATE OVERRIDE: BLOCKED(environment) — by George: build leg timeout")
        rc, _ = queue_daemon.append_override("cmp", "orch-mp-626b-x", "FAIL(product)", "Gemma", "back to product now")
        lines = [l for l in git(q.repo, "notes", "show", tip).splitlines() if l]
        assert rc == 0 and len(lines) == 3 and lines[1].startswith("PRE-MERGE GATE OVERRIDE: BLOCKED")

    def test_an_override_with_no_recorded_verdict_is_refused(self, q):
        self._route_branch(q, note=None)
        rc, msg = queue_daemon.append_override("cmp", "orch-mp-626b-x", "BLOCKED(environment)", "George", "a b c")
        assert rc == 1 and "no recorded gate verdict" in msg

    def test_the_cli(self, q, capsys):
        self._route_branch(q)
        assert queue_daemon.main(["override", "cmp", "orch-mp-626b-x", "--verdict", "BLOCKED(environment)"]) == 2
        assert queue_daemon.main(["override", "cmp", "orch-mp-626b-x", "--verdict", "BLOCKED(environment)",
                                  "--by", "George", "--reason", "leg timeout under load"]) == 0
        assert "override appended" in capsys.readouterr().out

    def test_the_regate_reads_the_newest_override(self, q, monkeypatch):
        tip = self._route_branch(q)
        b = q.tmp / "626b-x-regate.md"
        b.write_text(f"#!queue repo=cmp\n## Re-gate of: orch-mp-626b-x {tip}\n")
        monkeypatch.setattr(orchestrator, "PROJECT_ROOT", q.repo)
        monkeypatch.setattr(orchestrator, "IS_META_FIRE", False)
        monkeypatch.setattr(orchestrator, "BRANCH_PREFIX", "orch-mp")
        monkeypatch.delenv(orchestrator.REGATE_VAR, raising=False)
        spec, why = orchestrator._regate_check(b)
        assert spec is None and "is FAIL(product) — build: exit -1" in why, "control: the gate's own verdict"
        queue_daemon.append_override("cmp", "orch-mp-626b-x", "BLOCKED(environment)", "George", "leg timeout under load")
        spec, why = orchestrator._regate_check(b)
        assert why is None and spec.sha == tip
        assert spec.prior.startswith("BLOCKED(environment) — by George: leg timeout under load")
        assert "(gate: FAIL(product) — build: exit -1" in spec.prior
        queue_daemon.append_override("cmp", "orch-mp-626b-x", "FAIL(product)", "George", "no, it is product")
        spec, why = orchestrator._regate_check(b)
        assert spec is None and "FAIL(product) — by George: no, it is product" in why


# ── P-5 · r3 (verifier M-1, m-6, m-7, m-8) ────────────────────────────────────────────────────────────────────────
KILLED = ("failed", "FAIL(product)", "FAIL(product) — build: exit -1 (no F-20 environment signal in gate output — "
                                     "product verdict stands)")          # 626b, 2026-11-16 13:07, as state.json has it


class TestP5R3:

    def test_M1_a_safety_tier_product_red_stops_the_queue_and_is_not_parked(self, q, capsys):
        q.brief("0000000729-s", ["src/crisis.ts"])
        q.brief("000000731-l", ["src/l.ts"])
        q.brief("00000740-o", ["orchestrator.py"])
        q.script["0000000729-s.md"] = PRODUCT
        d = q.run()
        assert q.fired == ["0000000729-s.md"], q.fired
        assert d.paused_reason == "safety-red:0000000729-s.md"
        assert q.at("failed", "0000000729-s.md") and not q.at("held", "parked", "0000000729-s.md")
        assert "FAIL(product) on a SAFETY-tier brief — not parked; the queue stops" in capsys.readouterr().out

    def test_M1_control_six_and_eight_zeros_are_not_the_safety_tier(self, q):
        q.brief("000000731-l", ["src/l.ts"])
        q.brief("000000732-m", ["src/m.ts"])
        q.script["000000731-l.md"] = PRODUCT
        d = q.run()
        assert q.fired == ["000000731-l.md", "000000732-m.md"] and d.paused_reason is None
        assert q.at("held", "parked", "000000731-l.md")
        assert queue_daemon.SAFETY_TIER.match("0000000729-x.md")
        assert not queue_daemon.SAFETY_TIER.match("000000731-l.md")
        assert not queue_daemon.SAFETY_TIER.match("00000000729-x.md")

    def test_m6_a_killed_leg_labelled_product_stops_rather_than_parks(self, q, capsys):
        q.brief("0000626b-x", ["src/a.ts"])
        q.brief("0000627-y", ["src/b.ts"])
        q.script["0000626b-x.md"] = KILLED
        d = q.run()
        assert q.fired == ["0000626b-x.md"] and d.paused_reason == "stop-on-failure:0000626b-x.md"
        assert q.at("failed", "0000626b-x.md") and not q.at("held", "parked", "0000626b-x.md")
        assert d.failed[0]["red"] == "other"

    def test_m6_red_kind_rows(self):
        k = lambda s, g, e=None: queue_daemon.red_kind({"status": s, "gate_outcome": g, "error": e})
        assert k(*KILLED) == "other"
        assert k("failed", "FAIL(product)", "FAIL(product) — sit: exit -9 (killed)") == "other"
        assert k("failed", "FAIL(product)", "FAIL(product) — build: exit 1 (no F-20 environment signal)") == "product"

    @pytest.mark.parametrize("by", ["Bob", "george2", "Toni", ""])
    def test_m7_an_unknown_approver_is_refused(self, by):
        line, why = queue_daemon.override_line("BLOCKED(environment)", by, "leg timeout under load")
        assert line is None and "known approver (George or Gemma)" in why

    @pytest.mark.parametrize("by,named", [("george", "George"), (" GEMMA ", "Gemma"), ("George", "George")])
    def test_m7_a_known_approver_is_named_as_the_record_names_them(self, by, named):
        line, why = queue_daemon.override_line("BLOCKED(environment)", by, "leg timeout under load", at="T")
        assert why is None and line == f"PRE-MERGE GATE OVERRIDE: BLOCKED(environment) — by {named}: leg timeout under load (T)"

    def test_m8_qstat_lists_the_parked_tray(self, tmp_path):
        orch = tmp_path / "spectricom-orchestrator"
        tray = orch / "queue" / "held" / "parked"
        tray.mkdir(parents=True)
        (orch / "state").mkdir()
        (orch / "config").mkdir()
        (orch / "config" / "repos.yaml").write_text(yaml.safe_dump({"repos": {}}))
        (orch / "queue-state.json").write_text(json.dumps({"daemon_status": "running", "pid": os.getpid()}))
        (tray / "701-a.md").write_text("#!queue repo=cmp\n")
        (tray / "701-a.reason").write_text("2026-11-17T01:00:00 701-a.md: PARKED after FAIL(product) — unit: regression\n")
        root = Path(__file__).resolve().parents[1]
        r = subprocess.run(["bash", str(root / "qstat.sh")], capture_output=True, text=True, timeout=60,
                           env={**os.environ, "HOME": str(tmp_path)})
        out = r.stdout + r.stderr
        assert "🅿 PARKED 701-a.md | waiting for George | 2026-11-17T01:00:00 701-a.md: PARKED after FAIL(product)" in out, out
