# filename: tests/test_route_time.py
"""Tests for ORCH-ROUTE-TIME-1 (Kanban 698, S7-CORE-54 · D-S7CORE54-01/-03).

34 gated merges since 11-08: median 105.8 min, the executor 59.5 %, the unit leg 25.1 %. A route stopped paying twice
for the same tests:

  P-1 / P-2  (T-1) the gate's SIT leg reuses the executor's clean-green preflight on the same tree, else says why
  P-3        (T-1) the unit leg likewise — related scope only, clean green only
  P-4        `full-gate` and the nightly path never read state/preflight/
  P-5        (T-2) clinical-mp's unit triggers and the always-run source scanners (the real config/repos.yaml)
  P-6 / 6b   (T-3) a flaky-only full-scope PASS seeds the next baseline with the flakes taken out
  P-7        (T-4) executor/hooks/long_wait.py, and every settings file runs it
  P-8        (T-4) the fire prompt's typecheck sentence
  P-9        (T-4) the state/preflight/ Edit deny in every settings file
  P-10       preflight() records `dirty`

Harness: the rigs of tests/test_exec_preflight.py (build + SIT + unit, a REAL git repo), tests/test_unit_related.py,
tests/test_baseline_reuse_1.py (the REAL _run_batch_inner) and tests/test_gate_cost.py (`full-gate`); ORCH_DIR and
SIT_ARCHIVE_DIR are tmp in every one. Module-level imports are existing symbols only (RED collects).
"""

import inspect
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_baseline_reuse_1 import (ALONE_GREEN, ALONE_RED, BASE_290EA, FLAKY_UC, PASSED, UC, code,  # noqa: E402
                                         entries, fire, key, lane, main_sha)  # noqa: F401  (lane is a fixture)
from tests.test_exec_preflight import (SIT_LIST, U1, U2, UNIT_SUITE, Suites, _route, child,  # noqa: E402,F401
                                       rig)  # noqa: F401  (child and rig are fixtures)
from tests.test_foreground import PROMPT_TAIL  # noqa: E402
from tests.test_gate_cost import F, REPO, TEST_CMD, UA, UB, _git, fg, vitest  # noqa: E402,F401  (fg is a fixture)

ROOT = Path(__file__).parent.parent
PASS = orchestrator.GateOutcome.PASS
CLINICAL = yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["repos"]["clinical-mp"]
REPOS = sorted(yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["repos"])
SETTINGS = ROOT / "executor" / "settings"
LONG_WAIT = ROOT / "executor" / "hooks" / "long_wait.py"
NPM_FROZEN = ROOT / "executor" / "hooks" / "npm_frozen.py"
TYPECHECK = ("Compile once: run the repo's typecheck (if it has one: npx tsc --noEmit, plus -p server where the "
             "repo has one) one time after your last code change, and again only to confirm a fix to an error it "
             "reported; never run npm run build (the gate builds). Run only the test files you added or changed, "
             "by path; never a suite or a related set (the gate runs those).")   # [ORCH-LEAN-GATE-1] G-1
PREFLIGHT_DENY = "Edit(~/spectricom-orchestrator/state/preflight/**)"
# [698t] the deny list every settings file held before 698 (7b6cc99, all six identical), frozen here so P-9 never
# reads `main`: true on 698's branch only, it failed every later orchestrator route's build gate (705, 13:16).
PRE_698_DENY = ([f"{tool}({p})" for p in ("~/.ssh/**", "~/.aws/**", "~/.config/gcloud/**", "~/.config/gh/**",
                                         "~/.git-credentials", "~/.npmrc", "~/.docker/config.json", "~/.claude/**",
                                         "//mnt/c/**") for tool in ("Read", "Edit")]
                + [f"Edit({a}{p})" for a in ("", "//") for p in ("**/.claude/**", "**/.mcp.json",
                                                                "**/.github/workflows/**", "**/.husky/**",
                                                                "**/.vscode/tasks.json")])
KILL_CMD = 'bash "${TONI_GUARDS_HOME:-$HOME/spectricom-orchestrator}/executor/hooks/kill_switch.sh" || exit 2'
NPM_CMD = ('f="${TONI_GUARDS_HOME:-$HOME/spectricom-orchestrator}/executor/hooks/npm_frozen.py"; '
           '{ [ -r "$f" ] && command -v python3 >/dev/null; } || { echo "🛡 npm frozen: the hook could not run (no $f '
           'or no python3) — the Bash call is denied (fails closed). Stop and say so in the handback." >&2; exit 2; }; '
           'python3 "$f" || exit 2')
WAIT_CMD = ('f="${TONI_GUARDS_HOME:-$HOME/spectricom-orchestrator}/executor/hooks/long_wait.py"; '
            '{ [ -r "$f" ] && command -v python3 >/dev/null; } || { echo "🛡 long wait: the hook could not run (no $f '
            'or no python3) — the Bash call is denied (fails closed). Stop and say so in the handback." >&2; exit 2; }; '
            'python3 "$f" || exit 2')
SIT_NO, SIT_YES = "SIT: preflight not reused — ", "SIT: reused the executor preflight"
UNIT_NO, UNIT_YES = "unit: preflight not reused — ", "unit: reused the executor preflight"


def _msgs(caplog) -> list:
    return [r.getMessage() for r in caplog.records]


def _said(caplog, what) -> list:
    return [m for m in _msgs(caplog) if what in m]


def _pf_file(r, branch="route") -> Path:
    return r.orch / "state" / "preflight" / f"{branch}.json"


def _pf(r, capsys, monkeypatch=None):
    """The executor's preflight, as the fire prompt asks for it: the default JSON path, under the tmp ORCH_DIR."""
    Suites(r.monkeypatch)
    code_ = orchestrator.preflight(r.repo)
    capsys.readouterr()
    return code_, json.loads(_pf_file(r).read_text())


def _edit(r, **kv):
    f = _pf_file(r)
    rec = json.loads(f.read_text())
    for k, v in kv.items():
        if v is _DROP:
            rec.pop(k, None)
        else:
            rec[k] = v
    f.write_text(json.dumps(rec))
    return rec


_DROP = object()


def _gate(r, caplog, **suites):
    s = Suites(r.monkeypatch, **suites)
    with caplog.at_level(logging.INFO, logger="orch"):
        v = orchestrator.run_pre_merge_gates(r.repo, "route")
    return v, s


def _sit_log(r) -> list:
    f = r.tmp / "archive" / "orchestrator-sit-log.json"
    return json.loads(f.read_text()) if f.exists() else []


def _unit_log(r) -> list:
    f = r.tmp / "archive" / "orchestrator-unit-log.json"
    return json.loads(f.read_text()) if f.exists() else []


def _counter(r) -> dict:
    f = r.orch / "state" / f"unit-full-counter-{REPO}.json"
    return json.loads(f.read_text()) if f.exists() else {}


def _no_enum_worker() -> bool:
    return not any(t.name.startswith("sit-enum") and t.is_alive() for t in threading.enumerate())


# ═══════════════════════════════════════════════════════
# P-1 (RED) · a clean-green matching preflight: the SIT runner is not called
# ═══════════════════════════════════════════════════════
class TestP1SitReuse:

    def test_a_clean_green_matching_record_is_reused(self, rig, capsys, caplog):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        code_, rec = _pf(rig, capsys)
        assert code_ == 0 and rec["sit"]["files"] == [F[2]], rec
        v, s = _gate(rig, caplog)
        assert v.outcome is PASS, v.label
        assert s.sit_runs == [], "the SIT runner ran again on a tree the preflight already ran green"
        assert f"sit[related 1/5 files] — reused preflight {rec['at']}" in (v.collection or ""), v.collection
        (line,) = _said(caplog, SIT_YES)
        assert rec["tip"][:7] in line and not _said(caplog, SIT_NO)
        sit = [e for e in _sit_log(rig) if e.get("reused")]
        assert len(sit) == 1 and sit[0]["reused"] == "preflight" and sit[0]["passed"] is True
        assert (sit[0]["preflight_at"], sit[0]["preflight_tip"]) == (rec["at"], rec["tip"])
        assert sit[0]["scope"] == "related 1/5"
        assert _no_enum_worker()

    def test_the_serial_enumeration_path_also_reuses(self, rig, capsys, caplog):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        _pf(rig, capsys)
        rig.monkeypatch.setenv("ORCH_SIT_ENUM_PARALLEL", "off")
        v, s = _gate(rig, caplog)
        assert v.outcome is PASS and s.sit_runs == [] and len(_said(caplog, SIT_YES)) == 1


# ═══════════════════════════════════════════════════════
# P-2 · every condition that cannot be proven runs the leg, and one line names it
# ═══════════════════════════════════════════════════════
def _commit(r, rel, text):
    (r.repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (r.repo / rel).write_text(text)
    _git(r.repo, "add", "-A")
    _git(r.repo, "commit", "-qm", f"after the preflight: {rel}")


CONTROLS = {
    "missing": (lambda r: _pf_file(r).unlink(), {}, "no preflight record"),
    "unparsable": (lambda r: _pf_file(r).write_text("{ not json"), {}, "does not parse"),
    "repo": (lambda r: _edit(r, repo="other"), {}, "is for repo 'other'"),
    "branch": (lambda r: _edit(r, branch="other"), {}, "is for branch 'other'"),
    "sit-missing": (lambda r: _edit(r, sit=_DROP), {}, "incomplete"),
    "sit-not-dict": (lambda r: _edit(r, sit="pass"), {}, "incomplete"),
    "exit-not-int": (lambda r: _edit(r, exit="0"), {}, "incomplete"),
    "status-environment": (lambda r: _edit(r, sit={**json.loads(_pf_file(r).read_text())["sit"],
                                                   "status": "environment"}), {}, "SIT leg is 'environment'"),
    "base": (lambda r: _edit(r, base="0" * 40), {}, "merge base"),
    "dirty": (lambda r: _edit(r, dirty=["src/feature/a.ts"]), {}, "uncommitted outside briefs/"),
    "dirty-absent": (lambda r: _edit(r, dirty=_DROP), {}, "no `dirty` list"),
    "tip-tree": (lambda r: _commit(r, "src/feature/b.ts", "later\n"), {}, "non-briefs tree"),
    "file-set": (lambda r: None, {"sit_related": (F[2], F[3])}, "SIT file set"),
    "age-3h": (lambda r: _edit(r, at=(datetime.now() - timedelta(hours=3)).isoformat()), {}, "h old"),
    "max-h-abc": (lambda r: r.monkeypatch.setenv("ORCH_PREFLIGHT_REUSE_MAX_H", "abc"), {},
                  "ORCH_PREFLIGHT_REUSE_MAX_H='abc' is not a positive number"),
    "switch-off": (lambda r: r.monkeypatch.setenv("ORCH_PREFLIGHT_REUSE", "off"), {}, "ORCH_PREFLIGHT_REUSE=off"),
    "regate": (lambda r: r.monkeypatch.setattr(orchestrator, "REGATE", object()), {}, "re-gate lane"),
}


class TestP2SitControls:

    @pytest.mark.parametrize("case", sorted(CONTROLS))
    def test_the_sit_leg_runs_and_one_line_names_the_condition(self, rig, capsys, caplog, case):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        _pf(rig, capsys)
        mutate, suites, words = CONTROLS[case]
        mutate(rig)
        v, s = _gate(rig, caplog, **suites)
        assert v.outcome is PASS, v.label
        assert s.sit_runs, f"{case}: the SIT runner did not run"
        lines = _said(caplog, SIT_NO)
        assert len(lines) == 1 and words in lines[0], (case, lines)
        assert not _said(caplog, SIT_YES)
        assert not any(e.get("reused") for e in _sit_log(rig))
        assert _no_enum_worker()

    def test_a_briefs_only_commit_after_the_preflight_still_reuses(self, rig, capsys, caplog):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        _pf(rig, capsys)
        _commit(rig, "briefs/route.handback.md", "# handback\n")
        v, s = _gate(rig, caplog)
        assert v.outcome is PASS and s.sit_runs == [] and len(_said(caplog, SIT_YES)) == 1

    def test_a_record_red_only_on_its_unit_leg_reuses_sit_and_runs_unit(self, rig, capsys, caplog):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        _, rec = _pf(rig, capsys)
        _edit(rig, exit=1, result="fail", unit={**rec["unit"], "status": "fail", "failed": [U1]})
        v, s = _gate(rig, caplog)
        assert v.outcome is PASS and s.sit_runs == [] and len(_said(caplog, SIT_YES)) == 1
        assert s.unit_runs == [[U1, U2]], s.unit_runs
        (line,) = _said(caplog, UNIT_NO)
        assert "'fail'" in line


# ═══════════════════════════════════════════════════════
# P-3 · the unit leg: clean green, related scope, the same files
# ═══════════════════════════════════════════════════════
class TestP3UnitReuse:

    def test_a_clean_green_related_record_is_reused(self, rig, capsys, caplog):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        _, rec = _pf(rig, capsys)
        n_log = len(_unit_log(rig))
        v, s = _gate(rig, caplog)
        assert v.outcome is PASS and s.unit_runs == [], s.unit_runs
        uo = v.unit
        assert (uo.passed, uo.ran, uo.signal) == (True, False, "reused-preflight")
        assert uo.scope == f"related 2/{len(UNIT_SUITE)}" and uo.related_files == (U1, U2)
        assert uo.detail == f"reused the executor preflight ({rec['at']}, tip {rec['tip'][:7]})"
        assert "reused the executor preflight" in (v.unit_collection or ""), v.unit_collection
        assert _counter(rig) == {}, "[ORCH-LEAN-GATE-1] G-3: no every-N-th counter is kept"
        log_ = _unit_log(rig)
        assert len(log_) == n_log + 1 and log_[-1]["signal"] == "reused-preflight"
        (line,) = _said(caplog, UNIT_YES)
        assert rec["tip"][:7] in line
        tip = _git(rig.repo, "rev-parse", "HEAD")
        archive = rig.tmp / "cache"
        with caplog.at_level(logging.INFO, logger="orch"):
            orchestrator._unit_cache_store_landed(rig.repo, v, tip, archive, route_tip=tip)
        assert any("(a) no unit branch run — the unit gate was reused-preflight" in m for m in _msgs(caplog))
        assert not (archive / orchestrator.UNIT_BASELINE_CACHE_FILE).exists()

    def test_a_flaky_only_leg_is_reused(self, rig, capsys, caplog):   # [ORCH-LEAN-GATE-1] G-3 (was: runs the suite)
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        _, rec = _pf(rig, capsys)
        _edit(rig, unit={**rec["unit"], "flaky": [U1]})
        v, s = _gate(rig, caplog)
        assert s.unit_runs == [] and "flaky there, passed alone" in _said(caplog, UNIT_YES)[0]
        assert v.unit.signal == "reused-preflight"

    def test_a_different_related_set_runs_and_lists_once(self, rig, capsys, caplog):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        _pf(rig, capsys)
        v, s = _gate(rig, caplog, unit_related=(U1,))
        assert s.unit_runs == [[U1]] and "unit file set" in _said(caplog, UNIT_NO)[0]
        lists = [c for c in s.calls if c.startswith("npx vitest list") and not c.startswith(SIT_LIST)]
        assert len(lists) == 1 and not any("--changed" in c for c in lists), lists   # [ORCH-LEAN-GATE-1] G-3

    def test_a_non_reused_route_lists_the_unit_suite_once(self, rig, caplog):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})   # no preflight at all
        v, s = _gate(rig, caplog)
        assert s.unit_runs == [[U1, U2]]
        lists = [c for c in s.calls if c.startswith("npx vitest list") and not c.startswith(SIT_LIST)]
        assert len(lists) == 1, lists   # [ORCH-LEAN-GATE-1] G-3: the suite listing; the related set is read from files
        assert len(_said(caplog, UNIT_NO)) == 1 and "no preflight record" in _said(caplog, UNIT_NO)[0]

    def test_a_direct_run_unit_gate_call_is_todays(self, rig):
        assert "scope" in inspect.signature(orchestrator.run_unit_gate).parameters
        assert inspect.signature(orchestrator.run_unit_gate).parameters["scope"].default is None


# ═══════════════════════════════════════════════════════
# P-4 · full-gate and the nightly path never read state/preflight/
# ═══════════════════════════════════════════════════════
class TestP4FullGate:

    def test_full_gate_runs_every_leg_with_a_record_present(self, fg, monkeypatch):
        d = fg.orch / "state" / "preflight"
        d.mkdir(parents=True, exist_ok=True)
        (d / "main.json").write_text(json.dumps({"repo": REPO, "branch": "main", "result": "pass", "exit": 0}))

        def boom(*a, **k):
            raise AssertionError("full-gate read a preflight record")
        monkeypatch.setattr(orchestrator, "_preflight_record", boom, raising=False)
        assert fg.run() == 0
        assert fg.calls == ["list", "batch", "batch", "batch", "unit"]

    def test_the_full_gate_source_never_names_the_preflight(self):
        for fn in (orchestrator.full_gate, orchestrator._full_gate_unit):
            src = inspect.getsource(fn)
            assert "PREFLIGHT_DIR" not in src and "_preflight_record" not in src and "run_pre_merge_gates" not in src


# ═══════════════════════════════════════════════════════
# P-5 (RED) · clinical-mp's triggers and always-run scanners, from the real config/repos.yaml
# ═══════════════════════════════════════════════════════
ALWAYS = CLINICAL.get("unit_always_files") or ["src/__tests__/no-clinical-literals.test.ts",
                                               "src/lib/__tests__/one-owner-per-fact.test.ts"]
IN_SUITE_ALWAYS = sorted(ALWAYS)[:2]
P5_SUITE = ["src/feature/t1.test.ts", "src/feature/t2.test.ts", *IN_SUITE_ALWAYS]


class ListStub:
    """`npx vitest list …` only (the suite, the related set); git runs for real."""

    def __init__(self, monkeypatch, related=("src/feature/t1.test.ts",)):
        self.real, self.related, self.calls = subprocess.run, related, []
        monkeypatch.setattr(subprocess, "run", self)
        # [ORCH-LEAN-GATE-1] harness (D-S7CORE36-01 class iii): the related set is the one-hop importer set now
        monkeypatch.setattr(orchestrator, "_direct_importers", lambda repo, files, changed, roots=():
                            set(self.related) & set(files), raising=False)

    def __call__(self, cmd, *a, **kw):
        if not (isinstance(cmd, str) and cmd.startswith("npx vitest list")):
            return self.real(cmd, *a, **kw)
        self.calls.append(cmd)
        files = self.related if "--changed" in cmd else P5_SUITE
        return subprocess.CompletedProcess(cmd, 0, stdout="".join(f"{f}\n" for f in files), stderr="")


@pytest.fixture
def mp(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    for rel, text in {"package.json": json.dumps({"scripts": {"test": "vitest run"}}) + "\n",
                      "src/lib/x.ts": "x\n", "src/lib/data.json": "{}\n", "docs/readme.md": "d\n",
                      "src/test.setup.ts": "s\n", "server/allowlist.writes.ts": "w\n",
                      **{t: "t\n" for t in P5_SUITE}}.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "M0")
    orch = tmp_path / "orch"
    (orch / "state").mkdir(parents=True)
    monkeypatch.setattr(orchestrator, "ORCH_DIR", orch)
    from tests.test_gate_cost import _activate
    cfg = _activate(monkeypatch, tmp_path, repo, gates=(),
                    **{k: CLINICAL[k] for k in ("unit_full_triggers", "unit_full_every", "unit_always_files",
                                                "sit_core_files") if k in CLINICAL})
    for var in ("ORCH_UNIT_RELATED", "ORCH_UNIT_ALWAYS"):
        monkeypatch.delenv(var, raising=False)

    class R:
        pass
    r = R()
    r.repo, r.orch, r.cfg, r.monkeypatch = repo, orch, cfg, monkeypatch
    return r


def _scope(r, write, related=("src/feature/t1.test.ts",)):
    _git(r.repo, "checkout", "-q", "-B", "route", "main")
    for rel, text in write.items():
        (r.repo / rel).write_text(text)
    _git(r.repo, "add", "-A")
    _git(r.repo, "commit", "-qm", "route work")
    ListStub(r.monkeypatch, related=related)
    diff = orchestrator._branch_diff(r.repo, "route")
    return orchestrator._unit_scope(r.repo, TEST_CMD, diff), diff


class TestP5Triggers:

    def test_the_config_declares_the_scanners(self):
        assert isinstance(CLINICAL.get("unit_always_files"), list) and CLINICAL["unit_always_files"]
        assert CLINICAL["unit_always_files"] == sorted(CLINICAL["unit_always_files"])
        assert "unit_full_triggers" not in CLINICAL and "unit_full_every" not in CLINICAL   # [ORCH-LEAN-GATE-1] G-3

    def test_a_src_lib_change_is_related_and_carries_the_scanners(self, mp):
        s, diff = _scope(mp, {"src/lib/x.ts": "x2\n"})
        assert s.files is not None and not s.reason.startswith("(a)"), s.reason
        assert "src/feature/t1.test.ts" in s.files and set(IN_SUITE_ALWAYS) <= set(s.files), s.files
        assert "unit_always_files" in s.reason
        assert orchestrator.tests_reaching(mp.repo, diff).unit == s.files

    @pytest.mark.parametrize("path", ["package.json", "src/test.setup.ts", "server/allowlist.writes.ts"])
    def test_a_former_trigger_is_related_not_full(self, mp, path):   # [ORCH-LEAN-GATE-1] G-3 (was: the full suite)
        text = json.dumps({"scripts": {"test": "vitest run"}, "dependencies": {"zod": "^3"}}) + "\n" \
            if path == "package.json" else "changed\n"
        s, _ = _scope(mp, {path: text})
        assert s.files is not None and not s.reason.startswith("(a)"), s.reason

    def test_the_switch_drops_the_union(self, mp):
        mp.monkeypatch.setenv("ORCH_UNIT_ALWAYS", "off")
        s, _ = _scope(mp, {"src/lib/x.ts": "x2\n"})
        assert s.files == ("src/feature/t1.test.ts",), s.files

    def test_a_docs_only_diff_runs_no_unit_file(self, mp):
        s, _ = _scope(mp, {"docs/readme.md": "d2\n"}, related=())
        assert s.files == (), (s.files, s.reason)

    def test_a_change_nothing_imports_runs_the_scanners_only(self, mp):   # [ORCH-LEAN-GATE-1] G-3 (was: "(c)" full)
        s, _ = _scope(mp, {"src/lib/data.json": "{\"a\": 1}\n"}, related=())
        assert s.files == tuple(IN_SUITE_ALWAYS), (s.files, s.reason)


# ═══════════════════════════════════════════════════════
# P-6 (RED) / P-6b · a flaky-only full-scope PASS seeds the next baseline, the flakes taken out
# ═══════════════════════════════════════════════════════
class TestP6FlakyStore:

    def test_a_flaky_only_pass_is_stored_without_the_flakes(self, lane, caplog):
        lane.suites.out.update(branch=(1, FLAKY_UC), baseline=(1, BASE_290EA), confirm=(0, ALONE_GREEN))
        with caplog.at_level(logging.INFO, logger="orch"):
            r = fire(lane, "698-flake", code())
        assert (r.status, r.gate_outcome) == (PASSED, "PASS"), r.error
        merged = main_sha(lane)
        e = entries(lane)[key(lane, merged)]
        assert e["failing_files"] == [UA, UB] and UC not in e["failing_files"]
        assert e["failing_tests"] and not any(t.startswith(UC) for t in e["failing_tests"])
        assert e["failures"] == 4 and e["failures_source"] == "derived" and e["flaky_files"] == [UC]
        assert e["flaky_seen"][UC]["count"] >= 1 and e["landed_as"] == merged
        # the next route at that base reads it, and its tallies still reconcile
        caplog.clear()
        lane.suites.out.update(branch=(1, BASE_290EA))
        with caplog.at_level(logging.INFO, logger="orch"):
            r2 = fire(lane, "698-next", code("src/b.ts", "export const b = 1;\n"))
        assert (r2.status, r2.gate_outcome) == (PASSED, "PASS"), r2.error
        assert any("CACHE HIT" in m for m in _msgs(caplog)), _msgs(caplog)
        assert lane.suites.count("baseline") == 1, "the second route measured its baseline again"
        assert not any("TALLY MISMATCH" in m for m in _msgs(caplog))

    def test_a_non_flaky_new_failure_stores_nothing(self, lane, caplog):
        tip = main_sha(lane)
        run = orchestrator.UnitSuiteRun(ref="route", exit_code=1, **orchestrator._parse_unit_summary(
            vitest([UA, UB, UC, "src/lib/d.test.ts"], failed=4)))
        base = orchestrator.UnitSuiteRun(ref="base", exit_code=1, **orchestrator._parse_unit_summary(
            vitest([UA, UB], failed=2)))
        uo = orchestrator.UnitGateOutcome(passed=True, ran=True, branch=run, baseline=base, baseline_source="measured",
                                          flaky_files=(UC,), branch_sha=tip)
        v = orchestrator.GateVerdict(PASS, None, None, "x", unit=uo)
        with caplog.at_level(logging.INFO, logger="orch"):
            orchestrator._unit_cache_store_landed(lane.repo, v, tip, lane.archive, route_tip=tip)
        assert entries(lane) == {}
        assert any("NOT cached" in m and "(d) the branch run fails file(s) the accepted baseline does not: "
                   "src/lib/d.test.ts" in m for m in _msgs(caplog)), _msgs(caplog)

    def test_a_count_the_tests_do_not_name_stores_nothing(self, lane, caplog):
        lane.suites.out.update(branch=(1, vitest([UA, UA, UB, UB, UC], failed=6)), baseline=(1, BASE_290EA),
                               confirm=(0, ALONE_GREEN))
        with caplog.at_level(logging.INFO, logger="orch"):
            r = fire(lane, "698-unsplit", code())
        assert (r.status, r.gate_outcome) == (PASSED, "PASS"), r.error
        assert key(lane, main_sha(lane)) not in entries(lane)
        assert any("NOT cached" in m and f"(d) flaky file(s) {UC}: the failure count cannot be split" in m
                   for m in _msgs(caplog)), _msgs(caplog)

    def test_P6b_the_flaky_file_failing_alone_is_still_a_regression(self, lane, caplog):
        lane.suites.out.update(branch=(1, FLAKY_UC), baseline=(1, BASE_290EA), confirm=(0, ALONE_GREEN))
        r = fire(lane, "698-flake", code())
        assert r.gate_outcome == "PASS"
        assert key(lane, main_sha(lane)) in entries(lane)
        lane.suites.out.update(branch=(1, FLAKY_UC), confirm=(1, ALONE_RED))
        with caplog.at_level(logging.INFO, logger="orch"):
            r2 = fire(lane, "698-real", code("src/b.ts", "export const b = 1;\n"))
        assert r2.gate_outcome == "FAIL(product)", r2.error
        assert "regression" in (r2.error or "") or any("REGRESSED" in m and UC in m for m in _msgs(caplog))
        assert any("CACHE HIT" in m for m in _msgs(caplog))


# ═══════════════════════════════════════════════════════
# P-7 (RED) · executor/hooks/long_wait.py
# ═══════════════════════════════════════════════════════
CLOCK_604_682 = ("date; now=$(date +%s); target=$(date -d 'tomorrow 00:01' +%s); s=$((target-now)); "
                 "echo \"sleeping $s s\"; [ $s -gt 0 ] && [ $s -lt 3600 ] && sleep $s; date")
# the brief's list: `sleep 5m` → 2, so a wait of 300 s or more is refused (A1 T-4 says "more than 300 s"; the
# predicate is the stricter reading and is the one pinned here — said in the handback)
WAITS = [("sleep 2520", 2), ("sleep 30", 0), ("sleep 1m", 0), ("sleep 5m", 2), ("sleep 4m 59", 0), ("sleep 6m", 2),
         ("sleep infinity", 2), ("sleep 200 200", 2), ("sleep $s", 2), ("sleep \"$s\"", 2), ("sleep $(echo 9)", 2),
         ("sleep `echo 9`", 2), ("sleep 0.5h", 2), ("sleep 1d", 2), ("sleep 299", 0), ("sleep 300", 2),
         ("sleep 1e3", 2), (CLOCK_604_682, 2), ("timeout 600 npx --no-install vitest run x", 0),
         ("timeout 900 sleep 900", 2), ("echo \"sleeping $s s\"", 0), ("git commit -m \"sleep 600\"", 0),
         ("cat > x.sh <<'EOF'\nsleep 900\nEOF", 0), ("cat > x.sh <<EOF\nsleep 900\nEOF", 0),
         ("bash -c 'sleep 900'", 2), ("cd /tmp && /bin/sleep 3600", 2), ("ls; sleep 10; ls", 0)]


def _hook(command=None, raw=None, env_extra=None, hook=LONG_WAIT):
    env = {k: v for k, v in os.environ.items() if k != "TONI_LONG_WAIT"}
    env.update(env_extra or {})
    stdin = raw if raw is not None else json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                                                    "cwd": "/tmp"})
    return subprocess.run([sys.executable, str(hook)], input=stdin, capture_output=True, text=True, env=env,
                          timeout=30)


class TestP7LongWait:

    @pytest.mark.parametrize("command, rc", WAITS)
    def test_a_wait_over_five_minutes_is_refused(self, command, rc):
        r = _hook(command)
        assert r.returncode == rc, (command, r.stderr)
        if rc == 2:
            (line,) = r.stderr.strip().splitlines()
            assert line.startswith("🛡 long wait: ") and line.endswith(
                "— a route never waits for a clock; use fake timers or say so in the handback"), line
            assert len(line.split(" — a route never")[0]) <= len("🛡 long wait: ") + 120
        else:
            assert r.stderr == ""

    def test_the_604_682_command_is_named(self):
        r = _hook(CLOCK_604_682)
        assert r.returncode == 2 and "sleep $s" in r.stderr

    def test_unparsable_json_denies(self):
        r = _hook(raw="{ not json")
        assert r.returncode == 2 and r.stderr.startswith("🛡 long wait:")

    @pytest.mark.parametrize("value", ["off", "OFF", " Off "])
    def test_the_switch_allows_all(self, value):
        assert _hook("sleep 2520", env_extra={"TONI_LONG_WAIT": value}).returncode == 0

    def test_another_tool_is_not_judged(self):
        raw = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
        assert _hook(raw=raw).returncode == 0

    def test_it_uses_npm_frozens_parser(self):
        src = LONG_WAIT.read_text()
        assert "split_commands" in src and "npm_frozen" in src

    @pytest.mark.parametrize("repo", REPOS)
    def test_every_settings_file_runs_it_third(self, repo):
        pre = json.loads((SETTINGS / f"{repo}.json").read_text())["hooks"]["PreToolUse"]
        assert pre == [{"matcher": "*", "hooks": [{"type": "command", "command": KILL_CMD}]},
                       {"matcher": "Bash", "hooks": [{"type": "command", "command": NPM_CMD}]},
                       {"matcher": "Bash", "hooks": [{"type": "command", "command": WAIT_CMD}]}]

    def test_the_wrapper_fails_closed_without_the_hook(self, tmp_path):
        hooks = tmp_path / "home" / "spectricom-orchestrator" / "executor" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "long_wait.py").symlink_to(LONG_WAIT)
        (hooks / "npm_frozen.py").symlink_to(NPM_FROZEN)
        env = {"HOME": str(tmp_path / "home"), "PATH": os.environ["PATH"]}

        def via(command):
            stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tmp_path)})
            return subprocess.run([shutil.which("bash"), "-c", WAIT_CMD], input=stdin, capture_output=True, text=True,
                                  env=env, timeout=30)
        assert via("sleep 30").returncode == 0
        r = via("sleep 2520")
        assert r.returncode == 2 and "🛡 long wait: sleep 2520" in r.stderr
        (hooks / "long_wait.py").unlink()
        r = via("sleep 30")
        assert r.returncode == 2 and "🛡 long wait: the hook could not run" in r.stderr


# ═══════════════════════════════════════════════════════
# P-8 (RED) · the typecheck sentence rides in preflight_ask's placeholder
# ═══════════════════════════════════════════════════════
class TestP8Prompt:

    def test_the_prompt_carries_the_typecheck_sentence(self, child, tmp_path, monkeypatch):
        (tmp_path / "proj" / "briefs" / "61-x.md").write_text("#!queue model=m effort=high repo=clinical-mp\n# x\n")
        monkeypatch.setenv("ORCH_EXEC_PREFLIGHT", "on")   # [ORCH-LEAN-GATE-1] G-1: opt-in now
        argv = child(1800)["argv"]
        pre = orchestrator.PREFLIGHT_SENTENCE.format(repo="clinical-mp")
        assert argv[-1] == "Read briefs/61-x.md" + PROMPT_TAIL + " " + TYPECHECK + " " + pre

    def test_off_drops_only_the_preflight_sentence(self, child, monkeypatch):
        monkeypatch.setenv("ORCH_EXEC_PREFLIGHT", "off")
        argv = child(1800)["argv"]
        assert argv[-1] == "Read briefs/61-x.md" + PROMPT_TAIL + " " + TYPECHECK


# ═══════════════════════════════════════════════════════
# P-9 (RED) · the state/preflight/ Edit deny
# ═══════════════════════════════════════════════════════
class TestP9Deny:

    @pytest.mark.parametrize("repo", REPOS)
    def test_every_settings_file_denies_edits_to_the_record(self, repo):
        deny = json.loads((SETTINGS / f"{repo}.json").read_text())["permissions"]["deny"]
        assert deny.count(PREFLIGHT_DENY) == 1 and deny[-1] == PREFLIGHT_DENY
        assert deny[:-1] == PRE_698_DENY, "every pre-existing entry unchanged and in order"
        import re
        assert re.fullmatch(r"(Read|Edit)\((~/|//|\*\*/)[^()\s]+\)", PREFLIGHT_DENY)


# ═══════════════════════════════════════════════════════
# P-10 · preflight() records `dirty`
# ═══════════════════════════════════════════════════════
class TestP10Dirty:

    def test_a_clean_checkout_records_an_empty_list(self, rig, capsys):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        _, rec = _pf(rig, capsys)
        assert rec["dirty"] == []

    def test_an_uncommitted_file_is_recorded(self, rig, capsys):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        (rig.repo / "src" / "feature" / "new.ts").write_text("n\n")
        (rig.repo / "briefs" / "x.handback.md").write_text("h\n")
        _, rec = _pf(rig, capsys)
        assert rec["dirty"] == ["src/feature/new.ts"]
