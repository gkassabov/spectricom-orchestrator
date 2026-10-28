# filename: tests/test_unit_listing_prefix.py
"""Tests for ORCH-UNIT-LISTING-PREFIX-1 (S7-CORE-36 · D-S7CORE33-36 fix #1 · D-S7CORE36-03, Kanban row 499).

clinical-mp's unit config is a vitest workspace (`[app]`, `[server]`, `[journey]` projects), so every line of its
unit listing reads `[project] file > test` (or `[project] file` with --filesOnly). _parse_sit_listing read each as
a banner, the unit listing came back empty, and the per-route unit gate fell to "(c) the unit suite could not be
enumerated" on every clinical route — ORCH-UNIT-RELATED-1 never took effect there. The parser now strips a leading
`[name] ` before its banner check; nothing else about it changes, and the SIT listing (no workspace) parses as before.

  PU1  a workspace listing ⇒ _unit_listing returns its paths                                         (TestPU1*)
  PU2  a clinical-mp-shaped diff with no trigger ⇒ the related set, `🎯 related n/total`             (TestPU2*)
  PU3  every SIT listing fixture parses identically to the parser as it was at d5f1a97 (control)    (TestPU3*)
  PU4  the preflight on a workspace-listing branch ⇒ the unit leg lists files, not `not computed`   (TestPU4*)

Harness: real git repositories; only `npx vitest list …` / `npm …` are scripted, by the fakes of the tests this
extends, with each unit listing line given its workspace project. Module-level imports are existing symbols only.
"""

import logging
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests import test_clockguard_1, test_gate_cost, test_sit_isolation_attributed, test_sit_rate_limit  # noqa: E402
from tests.test_exec_preflight import SIT_LIST, U1, U2, Suites, _preflight, _route, rig  # noqa: E402,F401
from tests.test_gate_cost import TEST_CMD, _activate, _msgs  # noqa: E402
from tests.test_unit_related import SUITE, T1, T2, THREE, Unit, _branch, _repo  # noqa: E402

# the line shape clinical-mp's `npx vitest list` prints (2026-10-28, main): 1728 [app], 16 [server], 11 [journey]
REAL_UNIT = ("[app] src/__tests__/tab-placement-1-routes.test.tsx > redirects — an old child route lands on its tab "
             "(Navigate replace), no loop, both letter cases > /pros → /vitals\n"
             "[server] server/__tests__/auth.test.ts\n"
             "[journey] sit/journey/l-enrol/__tests__/lane-options.test.ts > P10 (F10) — lane options, upstream > "
             "owner, name, run tag and lane reach the plan\n")
# and its SIT listing (`--config vitest.sit.config.ts`, no workspace): 649 lines, none prefixed
REAL_SIT = ("sit/integration/member-portal-via-bff.integration.test.ts > MEMBER-API-PROXY-1a-iii P4 — the portal on "
            "the BFF, live, in a browser > she signs in at /portal/signin and visits every /portal route\n"
            "sit/integration/member-portal-via-bff.integration.test.ts > MEMBER-API-PROXY-1a-iii P4 — the portal on "
            "the BFF, live, in a browser > each page shows her data\n")


def _ws(text: str) -> str:
    """A listing as a vitest workspace prints it: `[server] ` before server/ files, `[app] ` before the rest."""
    return "".join(f"[{'server' if l.startswith('server/') else 'app'}] {l}\n" if l.strip() else "\n"
                   for l in (text or "").splitlines())


def _parse_at_d5f1a97(text: str) -> tuple:
    """_parse_sit_listing exactly as it was at d5f1a97 — the PU3 control."""
    files, per_file = [], {}
    for line in orchestrator._ANSI_RE.sub("", text or "").splitlines():
        line = line.strip()
        if not line or " " in line.split(" > ", 1)[0]:
            continue
        f = line.split(" > ", 1)[0]
        if f not in files:
            files.append(f)
            per_file[f] = 0
        if " > " in line:
            per_file[f] += 1
    return files, per_file


class WsUnit(Unit):
    """test_unit_related's fake, every unit listing printed as a workspace prints it."""

    def __call__(self, cmd, *a, **kw):
        r = super().__call__(cmd, *a, **kw)
        if isinstance(cmd, str) and cmd.startswith("npx vitest list"):
            r.stdout = _ws(r.stdout)
        return r


class WsSuites(Suites):
    """test_exec_preflight's fake, the unit listings (not the SIT config's) printed as a workspace prints them."""

    def __call__(self, cmd, *a, **kw):
        r = super().__call__(cmd, *a, **kw)
        if isinstance(cmd, str) and cmd.startswith("npx vitest list") and not cmd.startswith(SIT_LIST):
            r.stdout = _ws(r.stdout)
        return r


@pytest.fixture
def urig(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    orch = tmp_path / "orch"
    (orch / "state").mkdir(parents=True)
    monkeypatch.setattr(orchestrator, "ORCH_DIR", orch)
    _activate(monkeypatch, tmp_path, repo, gates=())
    monkeypatch.delenv("ORCH_UNIT_RELATED", raising=False)

    class R:
        pass
    r = R()
    r.repo, r.monkeypatch = repo, monkeypatch
    return r


# ── PU1 · a workspace listing is read as its paths ───────────────────────────────────────────────────────────────────
class TestPU1WorkspaceListing:

    def test_unit_listing_returns_both_projects_paths(self, tmp_path, monkeypatch):
        out = "[app] src/a.test.tsx > renders > the page\n[server] server/__tests__/b.test.ts > signs in\n"
        monkeypatch.setattr(subprocess, "run",
                            lambda cmd, *a, **kw: subprocess.CompletedProcess(cmd, 0, stdout=out, stderr=""))
        assert orchestrator._unit_listing(tmp_path, "npx vitest list") == (
            ["src/a.test.tsx", "server/__tests__/b.test.ts"], None)

    def test_files_only_lines_are_read_too(self, tmp_path, monkeypatch):
        out = "[app] src/a.test.tsx\n[server] server/__tests__/b.test.ts\n"
        monkeypatch.setattr(subprocess, "run",
                            lambda cmd, *a, **kw: subprocess.CompletedProcess(cmd, 0, stdout=out, stderr=""))
        assert orchestrator._unit_listing(tmp_path, "npx vitest list --filesOnly")[0] == [
            "src/a.test.tsx", "server/__tests__/b.test.ts"]

    def test_the_real_clinical_mp_shape(self):
        files, per_file = orchestrator._parse_sit_listing(REAL_UNIT)
        assert files == ["src/__tests__/tab-placement-1-routes.test.tsx", "server/__tests__/auth.test.ts",
                         "sit/journey/l-enrol/__tests__/lane-options.test.ts"], files
        assert list(per_file.values()) == [1, 0, 1]

    def test_only_the_prefix_is_stripped_a_banner_stays_a_banner(self):
        out = ("\x1b[36m[app]\x1b[39m src/a.test.tsx > x\n[app] RUN  v3.2.4 /home/x\n[a b] src/c.test.ts\n"
               "[app]src/d.test.ts\n")
        assert orchestrator._parse_sit_listing(out)[0] == ["src/a.test.tsx", "[app]src/d.test.ts"]

    def test_the_count_of_stripped_lines_is_logged_at_debug(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="orch"):
            orchestrator._parse_sit_listing(REAL_UNIT)
        assert any(m.startswith("listing: 3 workspace-prefixed line(s)") for m in _msgs(caplog)), _msgs(caplog)


# ── PU2 · the per-route unit gate selects the related set on a workspace repo ────────────────────────────────────────
class TestPU2RelatedOnWorkspace:

    def test_unit_scope_is_the_related_set_not_c(self, urig):
        _branch(urig.repo, THREE)
        WsUnit(urig.monkeypatch, urig.repo, related=(T1, T2))
        diff = orchestrator._branch_diff(urig.repo, "route")
        scope = orchestrator._unit_scope(urig.repo, TEST_CMD, diff)
        assert scope.files == (T1, T2) and scope.total == len(SUITE), scope
        assert not scope.reason.startswith("(c)"), scope.reason

    def test_the_gate_runs_only_the_related_files_and_says_so(self, urig, caplog):
        _branch(urig.repo, THREE)
        u = WsUnit(urig.monkeypatch, urig.repo, related=(T1, T2))
        with caplog.at_level(logging.INFO, logger="orch"):
            v = orchestrator.run_pre_merge_gates(urig.repo, "route")
        assert v.outcome is orchestrator.GateOutcome.PASS, v.label
        assert u.runs() == [f"{TEST_CMD} -- {T1} {T2}"], u.runs()
        assert any(m.startswith(f"🎯 Unit gate: related 2/{len(SUITE)} files") for m in _msgs(caplog)), _msgs(caplog)

    def test_a_trigger_diff_is_the_full_suite_with_the_related_set_still_named(self, urig):
        _branch(urig.repo, {**THREE, "vite.config.ts": "y\n"})
        WsUnit(urig.monkeypatch, urig.repo, related=(T1,))
        diff = orchestrator._branch_diff(urig.repo, "route")
        assert orchestrator._unit_scope(urig.repo, TEST_CMD, diff).reason.startswith("(a)")
        reach = orchestrator.tests_reaching(urig.repo, diff)
        assert reach.unit == (T1,) and reach.unit_full.startswith("(a)"), (reach.unit, reach.unit_why)


# ── PU3 · the SIT listing parses as it did (control) ─────────────────────────────────────────────────────────────────
SIT_FIXTURES = {
    "test_gate_cost": test_gate_cost.LIST_OUT,
    "test_sit_isolation_attributed": test_sit_isolation_attributed.LIST_OUT,
    "test_sit_rate_limit": test_sit_rate_limit.LIST_OUT,
    "test_clockguard_1": test_clockguard_1.LIST_OUT,
    "real clinical-mp SIT": REAL_SIT,
    "banners, ANSI, blanks, files only": (" RUN  v3.2.4 /home/x\n\n\x1b[32msit/a.test.ts\x1b[39m > one\n"
                                           "sit/a.test.ts > two\nsit/b.test.ts\nNo test files found, exiting\n"),
    "empty": "",
}


class TestPU3SitUnchanged:

    @pytest.mark.parametrize("name", list(SIT_FIXTURES))
    def test_identical_to_the_parser_at_d5f1a97(self, name):
        text = SIT_FIXTURES[name]
        assert orchestrator._parse_sit_listing(text) == _parse_at_d5f1a97(text), name


# ── PU4 · the executor's preflight names unit files on a workspace repo ─────────────────────────────────────────────
class TestPU4Preflight:

    def test_the_unit_leg_lists_files_not_not_computed(self, rig, capsys):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        fake = WsSuites(rig.monkeypatch)
        code, out, rec = _preflight(rig, capsys)
        assert rec["unit"]["status"] == "pass" and rec["unit"]["files"] == [U1, U2], (out, rec["unit"])
        assert fake.unit_runs == [[U1, U2]] and code == 0, (out, fake.unit_runs)

