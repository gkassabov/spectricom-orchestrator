# filename: tests/test_lean_gate.py
"""Tests for ORCH-LEAN-GATE-1 (D-S7CORE54-77, George 2026-11-16 14:03: "the per-route gate runs only what the change
touches — no full or partial regression suite per route; full regression nightly and before tester sessions").

  L-1  one hop: a test file is selected only when its own specifiers resolve to a changed file          (TestL1*)
  L-2  no trigger and no route count runs the full unit suite; no counter file is written              (TestL2*)
  L-3  a red is judged against the newest full gate's failure list, never a merge base measured        (TestL3*)
  L-4  SIT runs the SIT files the branch changes or that directly import a changed server/ file        (TestL4*)
  L-5  the fire prompt asks for no preflight, compiles once, never builds; a second preflight is refused (TestL5*)
  L-6  a header's effort=xhigh needs its `## Executor: … xhigh … Why:` line                              (TestL6*)
  L-7  lint runs on the changed files only; an error is FAIL(product)                                  (TestL7*)
  L-8  a green preflight leg is reused on its own (flaky-only unit, green-after-isolation SIT)        (TestL8*)
  L-9  a build leg killed at its budget is BLOCKED(environment), never FAIL(product)                   (TestL9*)
  L-10 TC-6: a guard is kept per route by risk class; only a slow non-risk guard runs nightly only     (TestL10*)
  L-11 TC-4: a red off the known list runs only its file at the merge base; red there ⇒ environment;
       mixed ⇒ product on the green-there file(s), the red-there ones named                          (TestL11*)

Harness: real files and a real git repository; only `npx …` / `npm …` are scripted (tests.test_unit_related.Unit).
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
import queue_daemon  # noqa: E402
from tests.test_foreground import PROMPT_TAIL, child  # noqa: E402,F401  (child is a fixture)
from tests.test_gate_cost import REPO, TEST_CMD, _git, _msgs, vitest  # noqa: E402
from tests.test_unit_related import PKG2, SUITE, T1, T2, T3, THREE, Unit, _branch, _gate, rig  # noqa: E402,F401

ROOT = Path(__file__).parent.parent
PASS, PRODUCT = orchestrator.GateOutcome.PASS, orchestrator.GateOutcome.FAIL_PRODUCT
CLINICAL = yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["repos"]["clinical-mp"]


UnitAtBase = Unit   # [r3 TC-4] the merge-base answer is Unit's own `base_red` (tests/test_unit_related.py)


def _base_runs(u, r) -> list:
    """The test commands run outside the checkout — at the merge base."""
    return [c for c, cwd in u.calls if c.startswith(TEST_CMD) and cwd != str(r.repo)]


def _w(root: Path, files: dict):
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)


# ═══════════════════════════════════════════════════════
# L-1 · one hop
# ═══════════════════════════════════════════════════════
class TestL1OneHop:

    @pytest.fixture
    def tree(self, tmp_path):
        _w(tmp_path, {
            "src/lib/a.ts": "export const a = 1;\n",
            "src/lib/b.ts": "export const b = 1;\n",
            "src/lib/c/index.ts": "export const c = 1;\n",
            "src/lib/helper.ts": "export { a } from './a';\n",
            "src/lib/__tests__/direct.test.ts": "import { a } from '../a';\n",
            "src/lib/__tests__/two-hops.test.ts": "import { a } from '../helper';\n",
            "src/lib/__tests__/mocked.test.ts": "vi.mock('../b', () => ({}));\nimport x from 'vitest';\n",
            "src/lib/__tests__/index.test.ts": "const m = await import(\"../c\");\n",
            "src/lib/__tests__/js-spec.test.ts": "import { a } from '../a.js';\n",
            "src/lib/__tests__/package.test.ts": "import { a } from 'a';\nimport z from '@medplum/core';\n",
            "server/__tests__/req.test.ts": "const a = require('../../src/lib/a');\n",
        })
        return tmp_path

    TESTS = ["src/lib/__tests__/direct.test.ts", "src/lib/__tests__/two-hops.test.ts", "src/lib/__tests__/mocked.test.ts",
             "src/lib/__tests__/index.test.ts", "src/lib/__tests__/js-spec.test.ts", "src/lib/__tests__/package.test.ts",
             "server/__tests__/req.test.ts"]

    def test_a_direct_import_is_selected_and_two_hops_is_not(self, tree):
        got = orchestrator._direct_importers(tree, self.TESTS, {"src/lib/a.ts"})
        assert got == {"src/lib/__tests__/direct.test.ts", "src/lib/__tests__/js-spec.test.ts",
                       "server/__tests__/req.test.ts"}, got

    def test_vi_mock_index_and_dynamic_import_resolve(self, tree):
        assert orchestrator._direct_importers(tree, self.TESTS, {"src/lib/b.ts"}) == {"src/lib/__tests__/mocked.test.ts"}
        assert orchestrator._direct_importers(tree, self.TESTS, {"src/lib/c/index.ts"}) == \
            {"src/lib/__tests__/index.test.ts"}

    def test_a_deleted_file_still_selects_its_importers(self, tree):
        (tree / "src/lib/a.ts").unlink()
        assert "src/lib/__tests__/direct.test.ts" in orchestrator._direct_importers(tree, self.TESTS, {"src/lib/a.ts"})

    def test_roots_keep_only_changed_files_under_them(self, tree):
        assert orchestrator._direct_importers(tree, self.TESTS, {"src/lib/a.ts"}, ("server/",)) == set()

    def test_the_helper_change_selects_its_direct_importer_only(self, tree):
        assert orchestrator._direct_importers(tree, self.TESTS, {"src/lib/helper.ts"}) == \
            {"src/lib/__tests__/two-hops.test.ts"}


# ═══════════════════════════════════════════════════════
# L-2 · no trigger, no counter
# ═══════════════════════════════════════════════════════
TRIGGERS = ["package.json", "package-lock.json", "vite.config.ts", "vitest.config.ts", "tsconfig.app.json",
            "src/test.setup.ts", "server/allowlist.writes.ts"]


class TestL2NoFullSuite:

    @pytest.mark.parametrize("path", TRIGGERS)
    def test_a_former_trigger_runs_only_what_the_change_touches(self, rig, caplog, path):
        rig.cfg["unit_full_triggers"] = ["package.json", "package-lock.json", "vite.config.*", "vitest*.config.*",
                                         "tsconfig*.json", "src/test.setup.ts", "server/allowlist*.ts"]
        body = PKG2 if path == "package.json" else "{}\n" if path.endswith(".json") else "changed\n"
        _branch(rig.repo, {**THREE, path: body})
        u = Unit(rig.monkeypatch, rig.repo, related=(T1,))
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _gate(rig)
        assert u.runs() == [f"{TEST_CMD} -- {T1}"], u.runs()
        assert not any(m.startswith("🎯 Unit gate: full suite") for m in _msgs(caplog)), _msgs(caplog)
        assert v.outcome is PASS

    def test_the_fifth_route_is_not_full_and_no_counter_is_written(self, rig):
        f = rig.orch / "state" / f"unit-full-counter-{REPO}.json"
        f.write_text(json.dumps({"since_full": 4}))
        u = Unit(rig.monkeypatch, rig.repo, related=(T1,))
        for i in range(1, 7):
            _branch(rig.repo, {"src/feature/a.ts": f"a{i}\n"}, name=f"route{i}")
            u.calls.clear()
            _gate(rig, f"route{i}")
            assert u.runs() == [f"{TEST_CMD} -- {T1}"], (i, u.runs())
        assert json.loads(f.read_text()) == {"since_full": 4}, "nothing reads or writes the counter"

    def test_source_with_no_direct_test_runs_nothing_and_says_the_nightly_covers_it(self, rig, caplog):
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo, related=())
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _gate(rig)
        assert u.runs() == [] and v.outcome is PASS
        assert "the full suite runs nightly" in v.detail

    def test_the_source_has_no_trigger_or_counter_left(self):
        src = (ROOT / "orchestrator.py").read_text()
        for gone in ("unit_full_triggers", "unit_full_every", "unit-full-counter-", "--changed {base}"):
            assert gone not in src, gone
        assert "unit_full_triggers" not in CLINICAL and "unit_full_every" not in CLINICAL


# ═══════════════════════════════════════════════════════
# L-3 · known reds, never a measured baseline
# ═══════════════════════════════════════════════════════
class TestL3KnownReds:

    def _nightly(self, r, failing=(), flaky=(), history=None):
        st = {"repo": REPO, "sha": "f" * 40, "finished_at": "2026-11-16T03:35:01", "trigger": "nightly",
              "unit": {"failing_files": None if failing is None else list(failing), "flaky": list(flaky)},
              "history": history or []}
        (r.orch / "state" / f"full-gate-{REPO}.json").write_text(json.dumps(st))

    def _no_baseline(self, u, r):
        return not [c for c, cwd in u.calls if c.startswith(TEST_CMD) and cwd != str(r.repo)]

    def test_a_red_on_the_known_list_passes_with_no_baseline_run(self, rig, caplog):
        self._nightly(rig, failing=[T1])
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo, related=(T1, T2), red=(T1,), red_alone=(T1,))
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _gate(rig)
        assert v.outcome is PASS, v.label
        assert self._no_baseline(u, rig), u.calls
        assert v.unit.baseline_source == orchestrator.KNOWN_REDS_SOURCE
        line = next(m for m in _msgs(caplog) if m.startswith("📋 Unit gate: known reds"))
        assert f"full-gate-{REPO}.json" in line and "fffffff" in line and "nightly" in line

    def test_a_red_off_the_list_that_fails_alone_is_product(self, rig):
        self._nightly(rig, failing=[T1])
        _branch(rig.repo, THREE)
        u = UnitAtBase(rig.monkeypatch, rig.repo, related=(T1, T2), red=(T2,), red_alone=(T2,), base_red=())
        v = _gate(rig)
        assert (v.outcome, v.signal) == (PRODUCT, "regression"), v.label
        assert _base_runs(u, rig) == [f"{TEST_CMD} -- {T2}"], u.calls   # [r3 TC-4] the failing file only, green there

    def test_a_file_the_nightly_confirmed_flaky_is_left_out_of_the_compare(self, rig):
        self._nightly(rig, failing=[], flaky=[T2])
        _branch(rig.repo, THREE)
        Unit(rig.monkeypatch, rig.repo, related=(T1, T2), red=(T2,), red_alone=(T2,))
        assert _gate(rig).outcome is PASS

    def test_the_history_list_is_read_when_the_newest_result_has_none(self, rig):
        self._nightly(rig, failing=None, history=[{"at": "2026-11-15T03:49", "sha": "c" * 40,
                                                    "unit_failing_files": [T2]}])
        _branch(rig.repo, THREE)
        Unit(rig.monkeypatch, rig.repo, related=(T1, T2), red=(T2,), red_alone=(T2,))
        assert _gate(rig).outcome is PASS

    def test_no_list_judges_every_red_new_and_says_so(self, rig, caplog):
        _branch(rig.repo, THREE)
        u = UnitAtBase(rig.monkeypatch, rig.repo, related=(T1,), red=(T1,), red_alone=(T1,), base_red=())
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _gate(rig)
        assert (v.outcome, v.signal) == (PRODUCT, "regression") and _base_runs(u, rig) == [f"{TEST_CMD} -- {T1}"]
        assert any("holds no full-gate unit failure list" in m for m in _msgs(caplog))


# ═══════════════════════════════════════════════════════
# L-4 · SIT: changed SIT files and direct importers of a changed server/ file
# ═══════════════════════════════════════════════════════
class TestL4Sit:

    @pytest.fixture
    def tree(self, tmp_path, monkeypatch):
        _w(tmp_path, {"server/router.ts": "x\n", "src/lib/policy.ts": "x\n",
                      "sit/integration/a.integration.test.ts": "import { r } from '../../server/router';\n",
                      "sit/integration/b.integration.test.ts": "import { p } from '../../src/lib/policy';\n",
                      "sit/integration/c.integration.test.ts": "import { h } from './medplum-harness';\n"})
        monkeypatch.setattr(orchestrator, "ACTIVE_REPO_CONFIG",
                            {"sit_list_cmd": "npx vitest list --config vitest.sit.config.ts"})
        plan = orchestrator.SitPlan(files=["sit/integration/a.integration.test.ts",
                                           "sit/integration/b.integration.test.ts",
                                           "sit/integration/c.integration.test.ts"])
        return tmp_path, plan

    def _diff(self, *paths):
        return orchestrator.BranchDiff(base="b" * 40, tip="HEAD", paths=paths)

    def test_a_server_change_runs_its_direct_sit_importers(self, tree):
        root, plan = tree
        files, how = orchestrator._sit_related_files(root, plan, self._diff("server/router.ts"))
        assert files == ["sit/integration/a.integration.test.ts"] and "one hop" in how

    def test_a_src_change_runs_no_sit_file(self, tree):
        root, plan = tree
        assert orchestrator._sit_related_files(root, plan, self._diff("src/lib/policy.ts"))[0] == []

    def test_a_changed_sit_file_runs_itself(self, tree):
        root, plan = tree
        files, _ = orchestrator._sit_related_files(root, plan, self._diff("sit/integration/c.integration.test.ts"))
        assert files == ["sit/integration/c.integration.test.ts"]

    def test_a_sit_config_change_is_said_not_the_full_suite(self, tree):
        root, plan = tree
        files, how = orchestrator._sit_related_files(root, plan, self._diff("vitest.sit.config.ts"))
        assert files == [] and "nightly full gate" in how

    def test_no_vitest_listing_is_run_for_the_related_set(self, tree, monkeypatch):
        root, plan = tree
        seen = []
        real = subprocess.run
        monkeypatch.setattr(subprocess, "run", lambda c, *a, **k: seen.append(c) or real(c, *a, **k))
        orchestrator._sit_related_files(root, plan, self._diff("server/router.ts"))
        assert not [c for c in seen if "vitest" in str(c)], seen


# ═══════════════════════════════════════════════════════
# L-5 · the prompt, and one preflight at most
# ═══════════════════════════════════════════════════════
class TestL5Prompt:

    def test_the_prompt_asks_for_no_preflight_by_default(self, child, monkeypatch):
        monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "clinical-mp")
        monkeypatch.delenv("ORCH_EXEC_PREFLIGHT", raising=False)
        prompt = child(1800)["argv"][-1]
        assert "orchestrator.py preflight" not in prompt
        assert prompt == "Read briefs/61-x.md" + PROMPT_TAIL + " " + orchestrator.TYPECHECK_SENTENCE

    def test_on_puts_the_preflight_sentence_back(self, child, monkeypatch):
        monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "clinical-mp")
        monkeypatch.setenv("ORCH_EXEC_PREFLIGHT", "on")
        assert "orchestrator.py preflight --repo clinical-mp" in child(1800)["argv"][-1]

    def test_the_executor_compiles_once_never_builds_and_runs_only_its_own_tests(self):
        s = orchestrator.TYPECHECK_SENTENCE
        assert "one time after your last code change" in s and "never run npm run build" in s
        assert "Run only the test files you added or changed" in s and "never a suite" in s


class TestL5OnePreflight:

    @pytest.fixture
    def repo(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        (repo / "a.ts").write_text("a\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "M0")
        _git(repo, "checkout", "-q", "-b", "orch-mp-x")
        (repo / "a.ts").write_text("b\n")
        _git(repo, "commit", "-qam", "route")
        orch = tmp_path / "orch"
        (orch / "state" / "preflight").mkdir(parents=True)
        monkeypatch.setattr(orchestrator, "ORCH_DIR", orch)
        monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "clinical-mp")
        monkeypatch.setattr(orchestrator, "MERGE_TARGET", "main")
        monkeypatch.delenv("ORCH_PREFLIGHT_ONCE", raising=False)
        return repo

    def _record(self, repo, tip=None):
        base = _git(repo, "merge-base", "main", "HEAD")
        rec = {"repo": "clinical-mp", "branch": "orch-mp-x", "base": base, "at": "2026-11-16T14:00:00",
               "tip": tip or _git(repo, "rev-parse", "HEAD"), "summary": "🧪 Preflight (executor): 1 SIT files / 2 "
               "unit files — pass", "exit": 0}
        f = orchestrator.ORCH_DIR / "state" / "preflight" / "orch-mp-x.json"
        f.write_text(json.dumps(rec))
        return f

    def test_a_second_preflight_on_the_route_is_refused_and_the_record_kept(self, repo, capsys):
        f = self._record(repo)
        before = f.read_text()
        assert orchestrator.preflight(repo) == orchestrator.PREFLIGHT_EXIT["already ran"] == 4
        assert f.read_text() == before
        assert "one preflight per route at most (D-S7CORE54-77)" in capsys.readouterr().out

    def test_after_more_commits_on_the_same_route_it_is_still_refused(self, repo):
        self._record(repo)
        (repo / "a.ts").write_text("c\n")
        _git(repo, "commit", "-qam", "more")
        branch_diff = orchestrator._branch_diff(repo, "orch-mp-x")
        assert orchestrator._preflight_already_ran(repo, "orch-mp-x", branch_diff)

    def test_a_record_from_a_re_cut_branch_does_not_refuse(self, repo):
        self._record(repo, tip="0" * 40)
        assert orchestrator._preflight_already_ran(repo, "orch-mp-x", orchestrator._branch_diff(repo, "orch-mp-x")) \
            is None

    def test_off_lets_it_run_again(self, repo, monkeypatch):
        self._record(repo)
        monkeypatch.setenv("ORCH_PREFLIGHT_ONCE", "off")
        assert orchestrator._preflight_already_ran(repo, "orch-mp-x", orchestrator._branch_diff(repo, "orch-mp-x")) \
            is None


# ═══════════════════════════════════════════════════════
# L-6 · effort
# ═══════════════════════════════════════════════════════
class TestL6Effort:

    def _brief(self, tmp_path, executor_line):
        f = tmp_path / "0001-x.md"
        f.write_text("#!queue model=claude-opus-5-5 effort=xhigh repo=clinical-mp\n\n# x\n" + executor_line + "\n")
        return f

    def test_xhigh_without_a_reason_fires_at_high_and_says_so(self, tmp_path):
        effort, said = queue_daemon.header_effort(self._brief(tmp_path, "## Executor: claude-opus-5-5 --effort xhigh"),
                                                  "xhigh")
        assert effort == "high" and "fired at high" in said and "0001-x.md" in said

    def test_xhigh_with_its_why_is_honoured(self, tmp_path):
        f = self._brief(tmp_path, "## Executor: claude-opus-5-5 --effort xhigh (queue header line 1). Why: a privacy "
                                  "route on the agent runtime")
        assert queue_daemon.header_effort(f, "xhigh") == ("xhigh", None)

    def test_high_is_untouched(self, tmp_path):
        assert queue_daemon.header_effort(self._brief(tmp_path, ""), "high") == ("high", None)

    def test_the_house_executor_line_shape_is_honoured(self, tmp_path):   # the queued 626b / 713 shape
        f = self._brief(tmp_path, "## Executor: claude-opus-5-5 --effort xhigh (queue header line 1). Why: an "
                                  "engine/schema row (D-O-11 `:517`; Kanban 713 executor cell)")
        assert queue_daemon.header_effort(f, "xhigh") == ("xhigh", None)


# ═══════════════════════════════════════════════════════
# L-7 · lint on the changed files
# ═══════════════════════════════════════════════════════
class TestL7Lint:

    @pytest.fixture
    def lint(self, rig, monkeypatch):
        rig.cfg["lint_changed_cmd"] = "npx eslint --no-warn-ignored"
        rig.cfg["build_gate_cmd"] = "true"
        monkeypatch.setitem(orchestrator.PRE_MERGE_GATES, REPO, {"gates": ("build",), "env_file": None})
        seen = {"cmds": [], "rc": 0}
        unit = Unit(rig.monkeypatch, rig.repo, related=(T1,))   # npm / npx for the unit leg

        def run(cmd, *a, **kw):
            if isinstance(cmd, str) and cmd.startswith("npx eslint"):
                seen["cmds"].append(cmd)
                return subprocess.CompletedProcess(cmd, seen["rc"], stdout="src/feature/a.ts\n 1:1 error x\n",
                                                   stderr="")
            return unit(cmd, *a, **kw)
        monkeypatch.setattr(subprocess, "run", run)
        return seen

    def test_only_the_changed_source_files_are_linted(self, rig, lint):
        _branch(rig.repo, {**THREE, "docs/readme.md": "d\n", "briefs/x.md": "b\n"})
        assert _gate(rig).outcome is PASS
        assert lint["cmds"] == ["npx eslint --no-warn-ignored src/feature/a.ts src/feature/b.ts src/feature/c.ts"]

    def test_an_error_is_product(self, rig, lint):
        lint["rc"] = 1
        _branch(rig.repo, THREE)
        v = _gate(rig)
        assert (v.outcome, v.gate, v.signal) == (PRODUCT, "lint", "lint"), v.label

    def test_no_key_no_lint(self, rig, lint):
        rig.cfg.pop("lint_changed_cmd")
        _branch(rig.repo, THREE)
        _gate(rig)
        assert lint["cmds"] == []


# ═══════════════════════════════════════════════════════
# L-8 · a green preflight leg is reused on its own
# ═══════════════════════════════════════════════════════
class TestL8Reuse:

    def test_the_unit_reuse_no_longer_needs_both_legs_green_or_no_flake(self):
        src = (ROOT / "orchestrator.py").read_text()
        body = src.split("def _unit_preflight_reuse(")[1].split("\ndef ")[0]
        assert 'rec.get("result") != "pass"' not in body and '"flaky" in unit' not in body
        sit = src.split("def _sit_preflight_reuse(")[1].split("\ndef ")[0]
        assert '"verdict" in sit' not in sit


# ═══════════════════════════════════════════════════════
# L-9 · a build leg killed at its budget is BLOCKED(environment), never FAIL(product)
# ═══════════════════════════════════════════════════════
class TestL9BuildTimeout:

    @pytest.fixture
    def build(self, rig, monkeypatch):
        monkeypatch.setitem(orchestrator.PRE_MERGE_GATES, REPO, {"gates": ("build",), "env_file": None})
        out = {}
        monkeypatch.setattr(orchestrator, "run_build_gate", lambda repo_path: out["bg"])
        return out

    def test_a_build_timeout_is_blocked_environment(self, rig, build):
        build["bg"] = orchestrator.BuildGateOutcome(passed=False, exit_code=-1, error="timeout", duration_s=600.2)
        _branch(rig.repo, THREE)
        v = _gate(rig)
        assert (v.outcome, v.gate, v.signal) == (orchestrator.GateOutcome.BLOCKED_ENV, "build", "timeout"), v.label
        assert "no exit observed" in v.detail

    def test_a_real_build_error_stays_product(self, rig, build):
        build["bg"] = orchestrator.BuildGateOutcome(passed=False, exit_code=2, error="x", duration_s=12.0,
                                                    output="src/a.ts(1,1): error TS2322: Type 'x' is not assignable",
                                                    stderr_head="src/a.ts(1,1): error TS2322")
        _branch(rig.repo, THREE)
        assert _gate(rig).outcome is PRODUCT


# ═══════════════════════════════════════════════════════
# L-10 · TC-6: guards by risk, not by stopwatch
# ═══════════════════════════════════════════════════════
RISK_CLASSES = {   # one slow guard per kept class (TC-6)
    "release": "src/lib/release/__tests__/slow-release-guard.test.ts",
    "clinical": "src/lib/clinical/x/__tests__/slow-clinical-guard.test.ts",
    "tasks (safety)": "src/lib/tasks/__tests__/slow-safety-guard.test.ts",
    "llm": "src/lib/llm/__tests__/slow-llm-guard.test.tsx",
    "copilot": "src/lib/copilot/replay/__tests__/slow-copilot-guard.test.ts",
    "crisis": "src/lib/crisis/__tests__/slow-crisis-guard.test.ts",
    "agentic-ops": "src/lib/agentic-ops/__tests__/slow-ops-guard.test.ts",
    "server": "server/__tests__/slow-server-guard.test.ts",
    "member guard": "src/pages/portal/__tests__/slow-member-dismiss-guard.test.ts",
    "allow-list": "scripts/__tests__/gen-member-allowlist-slow.test.ts",
    "read-map": "src/lib/__tests__/portal-read-map-pin.test.ts",
    "no-clinical-literals": "src/__tests__/no-clinical-literals.test.ts",
}
SLOW_PLAIN = "src/components/x/__tests__/slow-ui-scan.test.tsx"
FAST_PLAIN = "src/components/x/__tests__/fast-ui-scan.test.tsx"
REVIEW_NAMED = ("src/lib/release/__tests__/sign-creates-final.test.ts",
                "src/lib/tasks/__tests__/safety-status-writers-guard.test.ts", "src/__tests__/no-clinical-literals.test.ts",
                "src/lib/clinical/__tests__/clinician-reasons.test.ts",
                "src/lib/clinical/time-dimension/date-semantics-invariants.test.ts",
                "src/lib/copilot/replay/__tests__/copilot-replay.test.ts",
                "src/lib/fhir/__tests__/do-not-perform-readers.test.ts", "src/lib/llm/__tests__/llm-seams-2.test.tsx",
                "src/hooks/ai-draft-coverage-1.test.tsx",
                "src/components/encounter-compose/__tests__/medrec-hardening-1.test.tsx")
VERIFIER_ADDED = ("src/components/encounter/rooming/__tests__/before-this-visit.test.tsx",       # r3 B2
                  "src/components/encounter/rooming/__tests__/rooming-tied-responses.test.tsx",  # r3 B2
                  "src/lib/cache/__tests__/write-invalidation-invariants.test.ts")               # r3 m1, George LG-R4-1


class TestL10GuardsByRisk:

    @pytest.fixture
    def guards(self, rig):
        listed = [*RISK_CLASSES.values(), SLOW_PLAIN, FAST_PLAIN]
        rig.cfg.update({"unit_always_files": listed, "unit_always_max_s": 3.0,
                        "unit_always_slow_s": {f: 9.5 for f in listed if f != FAST_PLAIN},
                        "unit_always_risk_globs": CLINICAL["unit_always_risk_globs"]})
        return set(listed)

    @pytest.mark.parametrize("cls", sorted(RISK_CLASSES))
    def test_a_slow_guard_in_a_risk_class_runs_per_route(self, rig, guards, cls):
        add, said = orchestrator._unit_always(guards, set())
        assert RISK_CLASSES[cls] in add, (cls, said)

    def test_control_a_slow_non_risk_guard_runs_nightly_only_and_a_fast_one_per_route(self, rig, guards):
        add, said = orchestrator._unit_always(guards, set())
        assert SLOW_PLAIN not in add and FAST_PLAIN in add
        assert f"{len(RISK_CLASSES)} slow guard(s) kept by risk" in said and "1 slow non-risk guard(s) nightly" in said

    def test_a_malformed_rule_keeps_every_guard(self, rig, guards):
        rig.cfg["unit_always_slow_s"] = ["not", "a", "map"]
        add, _ = orchestrator._unit_always(guards, set())
        assert add == guards

    @pytest.mark.parametrize("risk", ["absent", [], [1]], ids=["risk-absent", "risk-empty", "risk-non-string"])
    def test_with_a_cut_a_missing_empty_or_non_string_risk_list_keeps_every_guard_and_warns(self, rig, guards,
                                                                                             caplog, risk):
        # verifier r3 B1: without a usable risk list every slow safety guard would go nightly, silently
        if risk == "absent":
            rig.cfg.pop("unit_always_risk_globs")
        else:
            rig.cfg["unit_always_risk_globs"] = risk
        with caplog.at_level(logging.WARNING, logger="orch"):
            add, _ = orchestrator._unit_always(guards, set())
        assert add == guards
        assert any("unit_always_risk_globs" in m and "every listed guard runs" in m for m in _msgs(caplog)), \
            _msgs(caplog)

    def test_clinical_mp_config_keeps_every_review_named_guard_per_route(self, monkeypatch):
        monkeypatch.setattr(orchestrator, "ACTIVE_REPO_CONFIG", CLINICAL)
        listed = {orchestrator._norm_test_path(f) for f in CLINICAL["unit_always_files"]}
        kept = set(REVIEW_NAMED) | set(VERIFIER_ADDED)
        assert len(listed) == 93 and kept <= listed
        nightly, _ = orchestrator._unit_always_nightly_only(listed)
        assert not (nightly & kept), sorted(nightly & kept)
        assert len(nightly) == 3 and all(CLINICAL["unit_always_slow_s"][f] > 3.0 for f in nightly)
        assert len(listed - nightly) == 90


# ═══════════════════════════════════════════════════════
# L-11 · TC-4: "already red on main"
# ═══════════════════════════════════════════════════════
class TestL11AlreadyRed:

    def _nightly(self, r):
        (r.orch / "state" / f"full-gate-{REPO}.json").write_text(json.dumps(
            {"repo": REPO, "sha": "f" * 40, "finished_at": "2026-11-16T03:35:01", "trigger": "nightly",
             "unit": {"failing_files": [T1], "flaky": []}, "history": []}))

    def test_red_at_the_merge_base_too_is_environment_already_red_on_main(self, rig, monkeypatch):
        monkeypatch.delenv(orchestrator.ALREADY_RED_VAR, raising=False)
        self._nightly(rig)
        _branch(rig.repo, THREE)
        u = UnitAtBase(rig.monkeypatch, rig.repo, related=(T1, T2, T3), red=(T2,), red_alone=(T2,), base_red=(T2,))
        v = _gate(rig)
        assert (v.outcome, v.gate, v.signal) == (orchestrator.GateOutcome.BLOCKED_ENV, "unit",
                                                 orchestrator.ALREADY_RED_SIGNAL), v.label
        assert T2 in v.detail and "already red on main" in v.detail
        assert _base_runs(u, rig) == [f"{TEST_CMD} -- {T2}"], u.calls   # that one file, once

    def test_green_at_the_merge_base_is_product(self, rig):
        self._nightly(rig)
        _branch(rig.repo, THREE)
        u = UnitAtBase(rig.monkeypatch, rig.repo, related=(T1, T2, T3), red=(T2,), red_alone=(T2,), base_red=())
        v = _gate(rig)
        assert (v.outcome, v.signal) == (PRODUCT, "regression"), v.label
        assert "already-red check" in v.detail and _base_runs(u, rig) == [f"{TEST_CMD} -- {T2}"]

    def test_never_runs_at_the_base_when_there_is_no_red(self, rig):
        self._nightly(rig)
        _branch(rig.repo, THREE)
        u = UnitAtBase(rig.monkeypatch, rig.repo, related=(T1, T2, T3), base_red=(T2,))
        assert _gate(rig).outcome is PASS and _base_runs(u, rig) == []

    def test_never_runs_at_the_base_for_a_known_red(self, rig):
        self._nightly(rig)
        _branch(rig.repo, THREE)
        u = UnitAtBase(rig.monkeypatch, rig.repo, related=(T1, T2), red=(T1,), red_alone=(T1,), base_red=(T1,))
        assert _gate(rig).outcome is PASS and _base_runs(u, rig) == []

    def test_a_file_new_on_the_route_is_product_with_no_base_run(self, rig):
        self._nightly(rig)
        new = "src/feature/t-new.test.ts"
        _branch(rig.repo, {**THREE, new: "test\n"})
        from tests import test_unit_related as tur
        rig.monkeypatch.setattr(tur, "SUITE", [*tur.SUITE, new])
        u = UnitAtBase(rig.monkeypatch, rig.repo, related=(T1, new), red=(new,), red_alone=(new,), base_red=(new,))
        v = _gate(rig)
        assert (v.outcome, v.signal) == (PRODUCT, "regression"), v.label
        assert _base_runs(u, rig) == [] and "exists at merge-base" in v.detail

    def test_mixed_red_and_green_at_base_is_product_naming_both(self, rig):
        # verifier r3 m3: T2 red at the base too, T3 green there ⇒ product on T3, T2 named, one base run of both
        self._nightly(rig)
        _branch(rig.repo, THREE)
        u = UnitAtBase(rig.monkeypatch, rig.repo, related=(T1, T2, T3), red=(T2, T3), red_alone=(T2, T3),
                       base_red=(T2,))
        v = _gate(rig)
        assert (v.outcome, v.signal) == (PRODUCT, "regression"), v.label
        assert f"newly-failing file(s): {T3};" in v.detail, v.detail
        assert f"red there too: {T2}" in v.detail and f"green there: {T3}" in v.detail, v.detail
        assert _base_runs(u, rig) == [f"{TEST_CMD} -- {T2} {T3}"], u.calls

    def test_off_switch_runs_nothing_at_the_base(self, rig, monkeypatch):
        monkeypatch.setenv(orchestrator.ALREADY_RED_VAR, "off")
        self._nightly(rig)
        _branch(rig.repo, THREE)
        u = UnitAtBase(rig.monkeypatch, rig.repo, related=(T1, T2), red=(T2,), red_alone=(T2,), base_red=(T2,))
        v = _gate(rig)
        assert (v.outcome, v.signal) == (PRODUCT, "regression") and _base_runs(u, rig) == []
