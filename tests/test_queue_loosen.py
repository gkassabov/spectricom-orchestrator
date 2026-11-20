"""ORCH-QUEUE-LOOSEN-1 (Kanban 794; D-S7CORE58, George 2026-11-20 15:24 "we must adjust", 15:33 "yes all").
  (1) a brief HOOK-1 refuses at fire is set aside in queue/held/prefire/; the queue keeps firing.
  (2) `resume --reason <free text>` issued after the pause began lifts it; a pause-shaped reason still must match.
  (4) A9 reads any `## Test scope: targeted…` line as targeted, with a warning, unless it names a full suite.
"""
import json
from pathlib import Path

import pytest

import orchestrator
import prefire
import queue_daemon
from tests.test_control_scope import Daemon
from tests.test_queue_park_red import PASS, PRODUCT, Q

PREFIRE_RED = ("failed", None, "pre-fire assertions failed (A1/A2/A8) — HOOK-1")


@pytest.fixture
def q(tmp_path, monkeypatch):
    return Q(tmp_path, monkeypatch)


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    return Daemon(tmp_path, monkeypatch)


# ── (1) ──────────────────────────────────────────────────────────────────────────────────────────────────────────
class TestPrefireSetAside:

    def test_R_a_prefire_refusal_is_set_aside_and_the_next_brief_fires(self, q, capsys):
        q.brief("791-a", ["src/a.ts"])
        q.brief("792-b", ["src/b.ts"])
        q.script["791-a.md"] = PREFIRE_RED
        d = q.run()
        assert q.fired == ["791-a.md", "792-b.md"]
        assert d.status != "paused" and d.paused_reason is None
        assert q.at("held", "prefire", "791-a.md") and q.at("held", "prefire", "791-a.reason")
        assert not q.at("791-a.md") and not q.at("failed", "791-a.md")
        assert "SET ASIDE" in capsys.readouterr().out

    def test_the_reason_file_says_how_to_bring_it_back(self, q):
        q.brief("791-a", ["src/a.ts"])
        q.script["791-a.md"] = PREFIRE_RED
        q.run()
        text = (q.queue / "held" / "prefire" / "791-a.reason").read_text()
        assert "791-a.md" in text and "enqueue" in text

    def test_red_kind_names_a_prefire_refusal(self):
        k = lambda s, g, e=None: queue_daemon.red_kind({"status": s, "gate_outcome": g, "error": e})
        assert k(*PREFIRE_RED) == "prefire"
        assert k("failed", "FAIL(product)", "pre-fire assertions failed") == "product"   # a gate verdict wins

    def test_the_error_prefix_is_the_orchestrators_own(self):
        src = Path(orchestrator.__file__).read_text()
        assert f"error='{queue_daemon.PREFIRE_REFUSED} (A1/A2/A8) — HOOK-1'" in src

    def test_negative_control_a_product_red_still_parks_not_sets_aside(self, q):
        q.brief("701-a", ["src/a.ts"])
        q.script["701-a.md"] = PRODUCT
        q.run()
        assert q.at("held", "parked", "701-a.md") and not q.at("held", "prefire", "701-a.md")

    def test_negative_control_a_pass_is_untouched(self, q):
        q.brief("701-a", ["src/a.ts"])
        q.script["701-a.md"] = PASS
        d = q.run()
        assert q.fired == ["701-a.md"] and d.paused_reason is None and not q.at("held", "prefire")

    def test_fails_closed_when_it_cannot_be_moved(self, q, monkeypatch):
        q.brief("791-a", ["src/a.ts"])
        q.brief("792-b", ["src/b.ts"])
        q.script["791-a.md"] = PREFIRE_RED
        real = queue_daemon._safe_move
        monkeypatch.setattr(queue_daemon, "_safe_move",
                            lambda src, dst: False if "prefire" in str(dst) else real(src, dst))
        d = q.run()
        assert q.fired == ["791-a.md"] and d.paused_reason == "stop-on-failure:791-a.md"


# ── (2) ──────────────────────────────────────────────────────────────────────────────────────────────────────────
class TestResumeFreeText:

    def _paused(self, daemon, reason, paused_at="2026-10-04T03:50:00"):
        daemon.d.is_daemon = True
        daemon.d.status, daemon.d.paused_reason, daemon.d.paused_at = "paused", reason, paused_at

    def _write(self, **req):
        f = queue_daemon.control_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"id": 1, "action": "resume", "reset_consecutive": False,
                                 "issued_status": "paused", "issued_paused_reason": "stop-on-failure:791-a.md",
                                 "issued_current_batch": None, "requested_at": "2026-10-04T04:00:00", **req}))

    def test_R_free_text_issued_after_the_pause_lifts_it(self, daemon):
        self._paused(daemon, "stop-on-failure:791-a.md")
        self._write(reason="George go 2026-11-20 14:28 ET: go resume (791 brief fixed)")
        daemon.d._poll_control()
        assert daemon.d.status == "running"

    def test_free_text_issued_before_the_pause_expires(self, daemon):
        self._paused(daemon, "stop-on-failure:791-a.md")
        self._write(reason="George go: resume", requested_at="2026-10-04T03:00:00")
        daemon.d._poll_control()
        assert daemon.d.status == "paused" and "before that pause began" in daemon.d.control_result

    @pytest.mark.parametrize("pause", ["safety-red:0000000700-x.md", "executor-auth:x.md — Toni's login has expired"])
    def test_a_pause_only_george_lifts_by_name_is_not_lifted_by_free_text(self, daemon, pause):
        self._paused(daemon, pause)
        self._write(reason="George go: resume")
        daemon.d._poll_control()
        assert (daemon.d.status, daemon.d.paused_reason) == ("paused", pause)

    def test_negative_control_a_pause_shaped_reason_that_does_not_match_still_expires(self, daemon):
        self._paused(daemon, "stop-on-failure:791-a.md")
        self._write(reason="max-consecutive:100")
        daemon.d._poll_control()
        assert daemon.d.status == "paused" and "expired" in daemon.d.control_result

    def test_negative_control_the_exact_reason_still_lifts(self, daemon):
        self._paused(daemon, "stop-on-failure:791-a.md")
        self._write(reason="stop-on-failure:791-a.md")
        daemon.d._poll_control()
        assert daemon.d.status == "running"


# ── (4) ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def _brief(tmp_path, scope):
    p = tmp_path / "x.md"
    p.write_text(f"# x\n{scope}\n")
    return p


@pytest.mark.parametrize("line", ["## Test scope: targeted (one file)", "## Test scope: targeted",
                                  "## Test scope: targeted (D-S7CORE30-04)", "## Test scope: Targeted — the new test"])
def test_R_a_targeted_ish_line_is_read_as_targeted_with_a_warning(tmp_path, line):
    scope, shown = prefire.parse_test_scope(_brief(tmp_path, line))
    assert scope == "targeted" and "⚠️ A9" in shown and line in shown


def test_negative_control_the_exact_line_has_no_warning(tmp_path):
    assert prefire.parse_test_scope(_brief(tmp_path, "## Test scope: targeted (D-S7CORE30-05)")) == \
        ("targeted", "## Test scope: targeted (D-S7CORE30-05)")


@pytest.mark.parametrize("line", ["## Test scope: targeted (D-S7CORE30-05) but run npm test",
                                  "## Test scope: targeted, then sit:gate", "## Test scope: full", "## Test scope:"])
def test_negative_control_a_full_suite_or_a_non_targeted_line_is_still_refused(tmp_path, line):
    assert prefire.parse_test_scope(_brief(tmp_path, line))[0] is None
