# filename: tests/test_unit_related_extra.py
"""Tests for ORCH-PREFLIGHT-READMAP-1 (Kanban 601 Part C; 341n6b handback F-1).

`scripts/__tests__/gen-member-allowlist.test.ts` reads `docs/portal-read-map.md` — and the call-site files the map
names — with `readFileSync`, so `vitest list --changed` never relates it to a change to them, and neither the unit
gate's related leg nor the executor's preflight ran it. repos.yaml `unit_related_extra` declares the edge: a diff
path matching a rule's `when` glob, or named in its `when_named_in` doc as a backtick span (a trailing `:line` /
`:line-line` stripped) that is a file tracked at the head, adds the rule's `add` files that are in the suite.

  P-C1  a diff touching only the map, or a tracked path the map names, relates the pin test (the real clinical-mp
        entry in config/repos.yaml); controls: an unrelated diff is unchanged, a malformed entry is a warning and
        today's set, routes / identifiers / untracked paths in backticks are ignored               (TestPC1*)
  P-C2  the preflight's unit set (the same function) on the same diff includes the test           (TestPC2*)

Harness: tests.test_unit_related (a real git repository; `npx vitest list …` and `npm test …` scripted).
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_gate_cost import TEST_CMD, _git, _msgs, vitest  # noqa: E402
from tests.test_unit_related import CLINICAL, SUITE, T1, Unit, _branch, rig  # noqa: E402,F401

PIN = "scripts/__tests__/gen-member-allowlist.test.ts"
MAP = "docs/portal-read-map.md"
SUITE2 = SUITE + [PIN]
MAP_TEXT = ("# Portal read map\n\n| row | call site | reads | route | component |\n|---|---|---|---|---|\n"
            "| P1 | `server/routes/member.ts:12` | Patient | `/appointments` | `PortalLayout` |\n"
            "| P2 | `src/portal/list.tsx:30-41` | Observation | `/portal` | `MemberHeader` |\n"
            "| P3 | `src/gone.ts:3` | (removed) | | |\n")
RULE_SAID = (f"+ 1 declared extra (unit_related_extra: {MAP} or named in {MAP} → {PIN}; touched ")


class Unit2(Unit):
    """test_unit_related's fake, with the pin test in the suite listing and runnable."""

    def __call__(self, cmd, *a, **kw):
        if isinstance(cmd, str) and cmd.startswith("npx vitest list") and "--changed" not in cmd:
            self.calls.append((cmd, kw.get("cwd")))
            return subprocess.CompletedProcess(cmd, 0, stdout="".join(f"{f}\n" for f in SUITE2), stderr="")
        if isinstance(cmd, str) and cmd.startswith(TEST_CMD + " -- "):
            self.calls.append((cmd, kw.get("cwd")))
            files = [f for f in SUITE2 if f in cmd.split(" -- ", 1)[1].split()]
            return subprocess.CompletedProcess(cmd, 0, stdout=vitest(total_tests=3 * len(files),
                                                                     total_files=len(files)), stderr="")
        return super().__call__(cmd, *a, **kw)


@pytest.fixture
def mp(rig):
    """The rig's repo with the read map, the pin test and the call sites on main; the real clinical-mp rule."""
    for rel, text in ((MAP, MAP_TEXT), (PIN, "test\n"), ("server/routes/member.ts", "m\n"),
                      ("src/portal/list.tsx", "l\n")):
        (rig.repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (rig.repo / rel).write_text(text)
    _git(rig.repo, "add", "-A")
    _git(rig.repo, "commit", "-qm", "read map")
    rig.cfg["unit_related_extra"] = CLINICAL["unit_related_extra"]
    return rig


def _scope(r, write, related=()):
    _branch(r.repo, write)
    Unit2(r.monkeypatch, r.repo, related=related)
    return orchestrator._unit_scope(r.repo, TEST_CMD, orchestrator._branch_diff(r.repo, "route"))


class TestPC1ReadMap:

    def test_the_real_clinical_mp_entry_is_the_one_under_test(self):
        assert CLINICAL["unit_related_extra"] == [{"when": [MAP], "when_named_in": MAP, "add": [PIN]}]

    def test_a_diff_touching_only_the_map_relates_the_pin_test(self, mp):
        s = _scope(mp, {MAP: MAP_TEXT + "| P4 | new |\n"})
        assert s.files == (PIN,), s
        assert s.reason.endswith(f", {RULE_SAID}{MAP})"), s.reason

    def test_a_tracked_call_site_the_map_names_relates_it(self, mp):
        s = _scope(mp, {"server/routes/member.ts": "m2\n"}, related=(T1,))
        assert s.files == (T1, PIN), s           # the suite's listing order
        assert f"{RULE_SAID}server/routes/member.ts)" in s.reason

    def test_a_line_range_suffix_is_stripped_too(self, mp):
        assert _scope(mp, {"src/portal/list.tsx": "l2\n"}).files == (PIN,)

    def test_routes_identifiers_and_untracked_spans_are_ignored(self, mp):
        assert orchestrator._unit_named_in(mp.repo, MAP) == {"server/routes/member.ts", "src/portal/list.tsx"}
        # `src/gone.ts:3` names no tracked file on main (ignored above); a branch that adds it tracks it at the head
        assert _scope(mp, {"src/gone.ts": "back\n"}).files == (PIN,)

    def test_control_an_unrelated_diff_is_unchanged(self, mp):
        s = _scope(mp, {"src/feature/a.ts": "a2\n"}, related=(T1,))
        assert s.files == (T1,) and "declared extra" not in s.reason

    @pytest.mark.parametrize("bad", ["docs/portal-read-map.md", [{"when": [MAP]}], [{"when": [MAP], "add": []}],
                                     [{"when": [MAP], "add": [PIN], "also": 1}], [{"add": [PIN]}], [[MAP, PIN]]])
    def test_control_a_malformed_entry_is_a_warning_and_todays_set(self, mp, caplog, bad):
        mp.cfg["unit_related_extra"] = bad
        with caplog.at_level(logging.INFO, logger="orch"):
            s = _scope(mp, {MAP: MAP_TEXT + "| P4 | new |\n"})
        assert s.files == () and "no unit test file relates" in s.reason      # today's verdict on a doc-only diff
        if hasattr(orchestrator, "UNIT_RELATED_EXTRA_KEY"):
                assert any(m.startswith("⚠️  Unit gate: repos.yaml unit_related_extra is malformed")
                       for m in _msgs(caplog))

    def test_an_add_file_outside_the_suite_is_not_added(self, mp):
        mp.cfg["unit_related_extra"] = [{"when": [MAP], "add": ["scripts/__tests__/nope.test.ts"]}]
        s = _scope(mp, {MAP: MAP_TEXT + "| P4 | new |\n"})
        assert s.files == ()

    def test_the_gate_runs_it_and_its_scope_line_names_the_rule(self, mp, caplog):
        _branch(mp.repo, {MAP: MAP_TEXT + "| P4 | new |\n"})
        u = Unit2(mp.monkeypatch, mp.repo, related=())
        with caplog.at_level(logging.INFO, logger="orch"):
            v = orchestrator.run_pre_merge_gates(mp.repo, "route")
        assert v.outcome is orchestrator.GateOutcome.PASS
        assert f"{TEST_CMD} -- {PIN}" in [c for c, _ in u.calls]
        assert any(m.startswith("🎯 Unit gate: related 1/11 files — ") and RULE_SAID in m for m in _msgs(caplog))


class TestPC2Preflight:

    def test_the_preflight_unit_set_on_the_same_diff_includes_the_pin_test(self, mp, capsys):
        _branch(mp.repo, {MAP: MAP_TEXT + "| P4 | new |\n"})
        Unit2(mp.monkeypatch, mp.repo, related=())
        out = mp.orch / "pf.json"
        code = orchestrator.preflight(mp.repo, out)
        rec = json.loads(out.read_text())
        assert code == 0 and rec["unit"]["files"] == [PIN], rec["unit"]
        assert RULE_SAID in rec["unit"]["why"]
        assert "🧪 Preflight (executor): 0 SIT files / 1 unit files — pass" in capsys.readouterr().out

    def test_tests_reaching_names_it(self, mp):
        _branch(mp.repo, {"server/routes/member.ts": "m2\n"})
        Unit2(mp.monkeypatch, mp.repo, related=(T1,))
        reach = orchestrator.tests_reaching(mp.repo, orchestrator._branch_diff(mp.repo, "route"))
        assert reach.unit == (T1, PIN)
