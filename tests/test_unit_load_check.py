# filename: tests/test_unit_load_check.py
"""Tests for ORCH-FULLGATE-WT-FSDENY-1 Part A (Kanban 601; Bug SCA-ORCH-FULLGATE-WT-FSDENY-1).

2026-11-12 08:04: the nightly full gate ran clinical-mp's unit suite in a detached worktree whose node_modules is a
symlink to the checkout's; Vite refused the symlink's real path (`Error: Denied ID …/pdf.worker.min.mjs?url`), 82
files could not load, every one of them "still failed alone" in the same worktree, and the gate said FAIL(product).
Baselines measured the same way carried those files as failing at the base.

  P-A1  the probe's output is BLOCKED(environment) `vite-fs-deny` for a run that linked the checkout's node_modules;
        the shared classifier (HEAD's unit call) says FAIL(product); the full gate over it is BLOCKED     (TestPA1*)
  P-A2  controls: an assertion quoting `Denied ID`, a denied path inside the worktree, `Failed to resolve import`
        (unit and build), build/SIT classification, ENV_BLOCK_SIGNALS untouched; STOP (d) scan            (TestPA2*)
  P-A3  such a run is never cached and never a full gate's `previous`; a real regression among the files that
        loaded still wins (FAIL(product), the load error said); the route gate's baseline the same       (TestPA3*)
  P-A4  the full gate's collection against the chain: same key −0.6% / −3.7% BLOCK, −0.25% / equal / larger judged
        as today, no reference said; no ratchet; deleted tests subtracted; a reused entry not its own ref  (TestPA4*)
  P-A5  ORCH_UNIT_LOAD_CHECK=off → HEAD's verdicts, one warning line per gate                              (TestPA5*)

Harness: tests.test_gate_cost.FullGate (a real project repo, a real detached worktree, real symlinks; only the suite
commands are scripted) and a real repo for the route gate. Module-level imports are existing symbols only.
"""

import json
import logging
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_gate_cost import REPO, TEST_CMD, UA, UB, FullGate, _git, _msgs, vitest  # noqa: E402

ROOT = Path(__file__).parent.parent
FIX = ROOT / "tests" / "fixtures" / "unit_load"
PROBE = (FIX / "probe_linked_worktree.txt").read_text()
PROBE_FILE = "src/components/healthspan/IngestedResultReview.pdf-text.test.tsx"
CHECKOUT_NM = "/home/gkassa/spectricom-clinical-mp/node_modules"
WORKER = "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url"
BLOCKED, PRODUCT, PASS = (orchestrator.GateOutcome.BLOCKED_ENV, orchestrator.GateOutcome.FAIL_PRODUCT,
                          orchestrator.GateOutcome.PASS)
DENIED_RX = re.compile(r"^\s*(?:Error: )?Denied ID (\S+)")    # G-A1's anchor, as the brief states it


def denied_block(f: str, nm: str) -> str:
    """The probe's FAIL + Denied ID lines (ANSI and all) for test file `f`, the denied path under `nm`."""
    head, err = PROBE.splitlines()[:2]
    return (head.replace(PROBE_FILE, f) + "\n" + err.replace(CHECKOUT_NM, nm) + "\n")


def suite(denied=(), failing=(), nm=CHECKOUT_NM, total_tests=200, total_files=40) -> str:
    """A whole-suite vitest output: `denied` files that could not load (no tests), `failing` with one failure each."""
    body = "".join(denied_block(f, nm) for f in denied)
    body += "".join(f" FAIL  {f} > suite > case 0\nAssertionError: expected 1 to be 2\n ❯ {f}:3:5\n" for f in failing)
    bad = len(set(denied) | set(failing))
    files = f" Test Files  {bad} failed | {total_files - bad} passed ({total_files})" if bad else \
        f" Test Files  {total_files} passed ({total_files})"
    tests = (f"      Tests  {len(failing)} failed | {total_tests - len(failing)} passed ({total_tests})" if failing
             else f"      Tests  {total_tests} passed ({total_tests})")
    return f"{body}\n{files}\n{tests}\n   Duration  9.1s\n"


D = [f"src/components/d{i}.test.tsx" for i in range(1, 4)]


def unit_verdict(out: str, root: Path, linked=(CHECKOUT_NM,)):
    """The unit leg's F-20 call. At d152f1f (no _classify_unit_failure) that is `_classify_gate_failure("unit", …)`
    — so a control asserting a verdict through this helper runs, and is green, on HEAD too."""
    f = getattr(orchestrator, "_classify_unit_failure", None)
    if f is None:
        return orchestrator._classify_gate_failure("unit", out, root, 1)
    return f(out, root, 1, linked, root)


# ═══════════════════════════════════════════════════════
# P-A1 · the probe's output
# ═══════════════════════════════════════════════════════
class TestPA1Probe:

    def test_the_probe_output_is_vite_fs_deny_for_a_run_that_linked_the_checkout(self, tmp_path):
        v = unit_verdict(PROBE, tmp_path / "wt")
        assert v.outcome is BLOCKED and v.signal == "vite-fs-deny", v
        assert v.detail == (f"vite-fs-deny: 1 test file(s) could not load (first: {PROBE_FILE} · Denied ID "
                            f"{CHECKOUT_NM}/{WORKER})")

    def test_heads_shared_classifier_says_product_on_it(self, tmp_path):
        """the call the unit gate made at d152f1f (`_classify_gate_failure("unit", …)`) — unchanged, FAIL(product)."""
        v = orchestrator._classify_gate_failure("unit", PROBE, tmp_path, 1)
        assert v.outcome is PRODUCT

    def test_a_run_that_linked_nothing_never_says_it(self, tmp_path):
        assert unit_verdict(PROBE, tmp_path, linked=()).outcome is PRODUCT

    def test_the_full_gate_over_82_unloadable_files_is_blocked_not_product(self, fg, caplog):
        """the 11-12 nightly's shape: the files fail in the whole suite AND alone (the same linked worktree)."""
        nm = fg.link_node_modules()
        files = [f"src/d/f{i}.test.tsx" for i in range(82)]
        fg.unit_out = suite(denied=files, nm=nm, total_tests=19543, total_files=2072)
        fg.confirm_out = suite(denied=files, nm=nm, total_tests=0, total_files=82)
        with caplog.at_level(logging.INFO, logger="orch"):
            fg.run()
        u = fg.state()["unit"]
        assert u["outcome"] == "BLOCKED" and u["signal"] == "vite-fs-deny" and u["new"] == [], u
        assert "confirm" not in fg.calls                     # nothing that could not load is "confirmed alone"
        line = next(m for m in _msgs(caplog) if m.startswith("⛔ full-gate unit: vite-fs-deny: 82 test file(s)"))
        assert f"(first: {files[0]} · Denied ID {nm}/{WORKER})" in line and "BLOCKED(environment)" in line
        assert u["failing_files"] is None


# ═══════════════════════════════════════════════════════
# P-A2 · controls: today's verdicts stand
# ═══════════════════════════════════════════════════════
class TestPA2Controls:

    def test_an_assertion_quoting_denied_id_is_product(self, tmp_path):
        assert unit_verdict((FIX / "assert_quotes_denied.txt").read_text(), tmp_path).outcome is PRODUCT

    def test_a_denied_path_inside_the_worktree_root_is_product(self, tmp_path):
        wt = tmp_path / "wt"
        (wt / "node_modules").mkdir(parents=True)
        out = PROBE.replace(CHECKOUT_NM, str(wt / "node_modules"))
        # even were the worktree's own node_modules listed as a link, a path inside the root is not one
        assert unit_verdict(out, wt, linked=(str(wt / "node_modules"),)).outcome is PRODUCT
        assert unit_verdict(PROBE.replace(CHECKOUT_NM, str(wt / "src")), wt).outcome is PRODUCT

    def test_failed_to_resolve_import_is_product_on_the_unit_gate(self, tmp_path):
        assert unit_verdict((FIX / "unit_failed_to_resolve.txt").read_text(), tmp_path).outcome is PRODUCT

    def test_failed_to_resolve_import_is_product_on_the_build_gate(self, tmp_path):
        out = (FIX / "build_failed_to_resolve.txt").read_text()
        assert "failed to resolve import" in out and "Failed to resolve import" in out
        assert orchestrator._classify_gate_failure("build", out, tmp_path, 1).outcome is PRODUCT
        assert unit_verdict(out, tmp_path).outcome is PRODUCT

    def test_build_and_sit_classification_never_consult_the_signal(self, tmp_path):
        for gate in ("build", "sit"):
            assert orchestrator._classify_gate_failure(gate, PROBE, tmp_path, 1).outcome is PRODUCT
        assert "vite-fs-deny" not in {sid for sid, _, _ in orchestrator.ENV_BLOCK_SIGNALS}
        assert not any("Denied" in rx for _, rx, _ in orchestrator.ENV_BLOCK_SIGNALS)

    def test_the_env_block_signals_table_is_byte_identical_to_the_base(self):
        """every existing F-20 verdict reads this table: it is not edited."""
        base = subprocess.run(["git", "-C", str(ROOT), "show", "d152f1f:orchestrator.py"], capture_output=True,
                              text=True)
        if base.returncode != 0:
            pytest.skip("d152f1f not reachable from this checkout")
        grab = re.compile(r"^ENV_BLOCK_SIGNALS = \(.*?^\)$", re.S | re.M)
        assert grab.search(base.stdout).group(0) == grab.search((ROOT / "orchestrator.py").read_text()).group(0)

    def test_stop_d_g_a1_matches_no_line_of_the_f20_or_product_fixtures(self):
        """STOP (d): every text fixture under tests/fixtures (the F-20 ones and P-A2's product failures) — 0 lines."""
        files = [p for p in (ROOT / "tests" / "fixtures").rglob("*") if p.is_file() and p.suffix in (".txt", ".log")
                 and p.name != "probe_linked_worktree.txt"]
        assert len(files) >= 4 + 3
        hits = [(p.name, l) for p in files for l in orchestrator._ANSI_RE.sub("", p.read_text(errors="replace"))
                .splitlines() if DENIED_RX.match(l)]
        assert hits == []


# ═══════════════════════════════════════════════════════
# P-A3 · never cached, never a `previous`; a real failure still wins
# ═══════════════════════════════════════════════════════
@pytest.fixture
def fg(tmp_path, monkeypatch):
    g = FullGate(tmp_path, monkeypatch)
    monkeypatch.delenv("ORCH_UNIT_LOAD_CHECK", raising=False)

    def link_node_modules() -> str:
        nm = g.repo / "node_modules"
        (nm / "pdfjs-dist").mkdir(parents=True, exist_ok=True)
        return str(nm.resolve())
    g.link_node_modules = link_node_modules
    return g


def _cache(archive: Path) -> dict:
    f = archive / orchestrator.UNIT_BASELINE_CACHE_FILE
    return json.loads(f.read_text())["entries"] if f.exists() else {}


class TestPA3NotAMeasurement:

    def test_a_run_built_from_the_probe_output_is_not_cacheable(self):
        out = suite(denied=[PROBE_FILE], failing=[UA])
        run = orchestrator.UnitSuiteRun(ref="merge-base x", exit_code=1, **orchestrator._parse_unit_summary(out),
                                        load_denied=orchestrator._unit_load_denied(out, (CHECKOUT_NM,)))
        assert run.failures == 1 and run.load_denied == ((PROBE_FILE, f"{CHECKOUT_NM}/{WORKER}"),)
        assert orchestrator._unit_is_cacheable(run) is False
        plain = orchestrator.UnitSuiteRun(ref="merge-base x", exit_code=1, **orchestrator._parse_unit_summary(out))
        assert orchestrator._unit_is_cacheable(plain) is True       # what HEAD decided for the same run

    def test_the_full_gate_neither_caches_it_nor_keeps_it_as_previous(self, fg):
        nm = fg.link_node_modules()
        fg.unit_out = suite(denied=D, nm=nm)
        fg.run()
        state = fg.state()
        assert state["unit"]["outcome"] == "BLOCKED" and state["unit"]["failing_files"] is None
        assert orchestrator._full_gate_previous(state, "unit") is None
        assert _cache(fg.archive) == {}
        assert "cached" not in state["unit"]

    def test_mixed_a_real_regression_among_the_loadable_files_is_product_and_says_the_load_error(self, fg):
        nm = fg.link_node_modules()
        fg.unit_out = suite(denied=D, failing=[UA], nm=nm)
        fg.confirm_out = suite(failing=[UA], total_tests=3, total_files=1)
        assert fg.run() == 1
        u = fg.state()["unit"]
        assert u["outcome"] == "FAIL(product)" and u["new"] == [UA], u
        assert u["detail"].endswith(f"also vite-fs-deny: 3 test file(s) could not load (first: {D[0]} · Denied ID "
                                    f"{nm}/{WORKER})")
        assert _cache(fg.archive) == {} and u["failing_files"] is None

    def test_a_file_that_cannot_load_alone_is_not_confirmed(self, fg):
        """a loadable suspect whose isolation run is the one that cannot load is not a regression either."""
        nm = fg.link_node_modules()
        fg.unit_out = suite(denied=D, failing=[UA], nm=nm)
        fg.confirm_out = suite(denied=[UA], nm=nm, total_tests=0, total_files=1)
        fg.run()
        u = fg.state()["unit"]
        assert u["outcome"] == "BLOCKED" and u["signal"] == "vite-fs-deny" and u["new"] == []
        assert "vite-fs-deny: 4 test file(s)" in u["detail"]

    def test_a_denied_path_outside_the_links_is_todays_verdict(self, fg):
        fg.link_node_modules()
        fg.unit_out = suite(denied=D, nm="/elsewhere/node_modules")
        fg.confirm_out = suite(denied=D, nm="/elsewhere/node_modules", total_tests=0, total_files=3)
        fg.run()
        u = fg.state()["unit"]
        assert u["outcome"] == "FAIL(product)" and u["new"] == D     # HEAD's verdict, unchanged

    def test_the_link_registry_is_released_after_the_gate(self, fg):
        fg.link_node_modules()
        fg.run()
        assert not any(str(k).startswith(str(fg.repo.parent)) for k in orchestrator._UNIT_LINKED)


class RouteRepo:
    """A real repo with a git-ignored node_modules, a route branch, and `npm test` scripted: the branch leg in the
    checkout (first call there), the baseline in a detached worktree (another cwd, node_modules linked), the
    confirmation in the checkout after the branch leg."""

    def __init__(self, tmp_path, monkeypatch, branch_out, base_out, confirm_out):
        from tests.test_gate_cost import _activate, _repo
        self.repo = _repo(tmp_path / "repo")
        (self.repo / ".gitignore").write_text("node_modules\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "ignore node_modules")
        (self.repo / "node_modules").mkdir()
        _git(self.repo, "checkout", "-q", "-b", "route")
        (self.repo / "src" / "b.ts").write_text("export const b = 2;\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "route work")
        _activate(monkeypatch, tmp_path, self.repo, gates=())
        self.nm = str((self.repo / "node_modules").resolve())
        self.outs = {"branch": branch_out, "base": base_out, "confirm": confirm_out}
        self.real, self.calls, self.archive = subprocess.run, [], tmp_path / "archive"
        monkeypatch.setattr(subprocess, "run", self)

    def __call__(self, cmd, *a, **kw):
        if not (isinstance(cmd, str) and cmd.startswith("npm ")):
            return self.real(cmd, *a, **kw)
        leg = ("confirm" if "branch" in self.calls else "branch") if kw.get("cwd") == str(self.repo) else "base"
        self.calls.append(leg)
        out = self.outs[leg].replace("<NM>", self.nm)
        return subprocess.CompletedProcess(cmd, 1 if "FAIL" in out else 0, stdout=out, stderr="")


class TestPA3RouteGate:

    def test_the_baseline_measured_in_a_linked_worktree_is_not_cached(self, tmp_path, monkeypatch):
        """HEAD caches it (3 failing files that never ran, for every later route off this tree)."""
        r = RouteRepo(tmp_path, monkeypatch, branch_out="", base_out=suite(denied=D, failing=[UB], nm="<NM>"),
                      confirm_out="")
        base = _git(r.repo, "merge-base", "main", "route")
        run, source, note = orchestrator._unit_baseline_measure_or_reuse(r.repo, base, TEST_CMD, r.archive, REPO)
        assert source == "measured" and run.failures == 1
        assert _cache(r.archive) == {}, "a run whose files could not load was cached"
        assert "NOT cached — vite-fs-deny: 3 test file(s) could not load" in note

    def test_a_baseline_that_could_not_load_a_file_no_longer_masks_the_branchs_red_in_it(self, tmp_path,
                                                                                        monkeypatch):
        """HEAD: D[0] "fails" at the (linked) base and the counts are equal (1 vs UB's 1), so the branch's real red in
        it is debt — PASS, and the baseline is cached. Now: D[0] is not compared, and the verdict is never PASS."""
        r = RouteRepo(tmp_path, monkeypatch, branch_out=suite(failing=[D[0]]),
                      base_out=suite(denied=D, failing=[UB], nm="<NM>"),
                      confirm_out=suite(failing=[D[0]], total_files=1))
        o = orchestrator.run_unit_gate(r.repo, "route")
        assert not o.passed and o.env and o.signal == "vite-fs-deny", o
        assert o.detail.startswith(f"vite-fs-deny: 3 test file(s) could not load (first: {D[0]} · Denied ID ")
        assert "on the baseline run" in o.detail and o.baseline_note.endswith(
            f"NOT cached — vite-fs-deny: 3 test file(s) could not load (first: {D[0]} · Denied ID {r.nm}/{WORKER})")
        assert _cache(r.archive) == {}
        v = orchestrator.run_pre_merge_gates(r.repo, "route")
        assert v.outcome is BLOCKED and v.signal == "vite-fs-deny"

    def test_a_regression_in_a_loadable_file_still_fails_the_route_and_says_the_load_error(self, tmp_path,
                                                                                         monkeypatch):
        r = RouteRepo(tmp_path, monkeypatch, branch_out=suite(failing=[UA]),
                      base_out=suite(denied=D, nm="<NM>"), confirm_out=suite(failing=[UA], total_files=1))
        o = orchestrator.run_unit_gate(r.repo, "route")
        assert not o.passed and not o.env and o.signal == "regression"
        assert f"newly-failing file(s): {UA}" in o.detail and "also vite-fs-deny: 3 test file(s)" in o.detail
        assert orchestrator.run_pre_merge_gates(r.repo, "route").outcome is PRODUCT

    def test_a_clean_baseline_is_cached_as_today(self, tmp_path, monkeypatch):
        r = RouteRepo(tmp_path, monkeypatch, branch_out=suite(failing=[UA]), base_out=suite(failing=[UA]),
                      confirm_out=suite(failing=[UA], total_files=1))
        o = orchestrator.run_unit_gate(r.repo, "route")
        assert o.passed and o.baseline_source == "measured" and len(_cache(r.archive)) == 1


# ═══════════════════════════════════════════════════════
# P-A4 · the full gate's collection against the chain
# ═══════════════════════════════════════════════════════
def _seed(fg, sha, total, failing=()):
    orchestrator._unit_cache_store(fg.archive, REPO, sha, TEST_CMD, orchestrator.UnitSuiteRun(
        ref=f"merge-base {sha[:7]}", exit_code=1 if failing else 0, duration_s=300.0,
        **orchestrator._parse_unit_summary(vitest(list(failing), failed=len(failing), total_tests=total,
                                                  total_files=2072))), repo_path=fg.repo)


def _main_commit(fg, write=None, delete=()):
    for rel, text in (write or {}).items():
        (fg.repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (fg.repo / rel).write_text(text)
    for rel in delete:
        _git(fg.repo, "rm", "-q", rel)
    _git(fg.repo, "add", "-A")
    _git(fg.repo, "commit", "-q", "--allow-empty", "-m", "main work")
    return _git(fg.repo, "rev-parse", "HEAD")


class TestPA4Collection:

    def _run(self, fg, n, caplog):
        fg.unit_out = vitest(total_tests=n, total_files=2072)
        with caplog.at_level(logging.INFO, logger="orch"):
            fg.run()
        return fg.state()["unit"]

    def test_19543_against_20300_for_the_same_tree_blocks_with_the_drop_line(self, fg, caplog):
        sha = _git(fg.repo, "rev-parse", "main")
        _seed(fg, sha, 20300)
        u = self._run(fg, 19543, caplog)
        assert u["outcome"] == "BLOCKED" and u["signal"] == "collection-shrank" and u["failing_files"] is None, u
        assert any(m.startswith(f"⛔ full-gate unit: collected 19543 tests vs 20300 at {sha[:7]} (−3.7%) — "
                                f"BLOCKED(environment), not FAIL(product)") for m in _msgs(caplog)), _msgs(caplog)
        assert u["collection_check"]["kind"] == "same content key"

    @pytest.mark.parametrize("n", [20300, 20310])
    def test_control_equal_or_larger_is_judged_as_today(self, fg, caplog, n):
        _seed(fg, _git(fg.repo, "rev-parse", "main"), 20300)
        assert self._run(fg, n, caplog)["outcome"] == "PASS"

    @pytest.mark.parametrize("n", [20300, 20310])
    def test_equal_or_larger_is_recorded_as_not_fewer(self, fg, caplog, n):
        _seed(fg, _git(fg.repo, "rev-parse", "main"), 20300)
        u = self._run(fg, n, caplog)
        assert not u["collection_check"].get("dropped") and u["collection_check"]["reference"] == 20300
        assert any("— not fewer; judged as today" in m for m in _msgs(caplog))

    def test_control_no_comparable_measurement_is_judged_as_today(self, fg, caplog):
        u = self._run(fg, 19543, caplog)
        assert u["outcome"] == "PASS" and u.get("cached") is True   # a first measurement is cached, as today

    def test_no_comparable_measurement_says_so(self, fg, caplog):
        u = self._run(fg, 19543, caplog)
        assert u["collection_check"]["reference"] is None
        assert any(m.startswith("🔎 full-gate unit: collected 19543 tests — no measurement to compare the "
                                "collection with") for m in _msgs(caplog))

    def test_control_same_key_a_quarter_percent_is_judged_as_today(self, fg, caplog):
        _seed(fg, _git(fg.repo, "rev-parse", "main"), 20300)
        assert self._run(fg, 20250, caplog)["outcome"] == "PASS"          # −0.25 %

    def test_same_key_a_quarter_percent_is_recorded_as_dropped(self, fg, caplog):
        _seed(fg, _git(fg.repo, "rev-parse", "main"), 20300)
        u = self._run(fg, 20250, caplog)
        assert u["collection_check"]["dropped"] and not u["collection_check"].get("blocked")

    def test_same_key_six_tenths_of_a_percent_blocks(self, fg, caplog):
        _seed(fg, _git(fg.repo, "rev-parse", "main"), 20300)
        u = self._run(fg, 20178, caplog)                   # −0.60 %
        assert u["outcome"] == "BLOCKED" and u["signal"] == "collection-shrank"

    def test_no_ratchet_a_small_drop_against_an_ancestor_is_judged_but_never_becomes_the_reference(self, fg, caplog):
        a = _git(fg.repo, "rev-parse", "main")
        _seed(fg, a, 20000)
        _main_commit(fg, {"src/b.ts": "export const b = 1;\n"})
        u = self._run(fg, 19700, caplog)                   # −1.5 % < 2 %
        assert u["outcome"] == "PASS" and u["collection_check"]["reference"] == 20000
        assert u["collection_check"]["dropped"] and "cached" not in u
        assert {e["sha"] for e in _cache(fg.archive).values()} == {a}
        u = self._run(fg, 19700, caplog)                   # the next run: still the old max, still not cached
        assert u["collection_check"]["reference"] == 20000 and u["collection_check"]["reference_sha"] == a
        assert {e["sha"] for e in _cache(fg.archive).values()} == {a}

    def test_the_reference_is_the_max_of_the_last_n_measured_ancestors(self, fg, caplog):
        shas = [_git(fg.repo, "rev-parse", "main")]
        _seed(fg, shas[0], 20300)
        for total in (20100, 20200):
            shas.append(_main_commit(fg, {"src/b.ts": f"export const b = {total};\n"}))
            _seed(fg, shas[-1], total)
        _main_commit(fg, {"src/c.ts": "c\n"})
        u = self._run(fg, 19800, caplog)                   # vs 20300: −2.5 % → BLOCKED
        assert u["outcome"] == "BLOCKED" and u["collection_check"]["reference_sha"] == shas[0]
        orchestrator.ACTIVE_REPO_CONFIG["full_gate_collection_ref_n"] = 2
        u = self._run(fg, 19800, caplog)                   # the 2 nearest: max 20200 → −1.98 % → judged
        assert u["outcome"] == "PASS" and u["collection_check"]["reference"] == 20200

    def _deleted_500(self, fg, delete=True):
        body = "".join(f"it('case {i}', () => {{}});\n" for i in range(490)) + \
            "test.each([1])('e', () => {});\nit.skip('s', () => {});\ntest.todo('t');\n" + \
            "".join(f"test('t{i}', () => {{}});\n" for i in range(7)) + "// commit( and submit( are not tests\n"
        a = _main_commit(fg, {"src/old.test.ts": body})
        _seed(fg, a, 20300)
        _main_commit(fg, delete=["src/old.test.ts"] if delete else (), write=None if delete else {"src/c.ts": "c\n"})

    def test_control_a_diff_that_deleted_500_tests_is_judged_as_today(self, fg, caplog):
        self._deleted_500(fg)
        assert self._run(fg, 19800, caplog)["outcome"] == "PASS"

    def test_the_same_drop_with_no_deletion_blocks(self, fg, caplog):
        self._deleted_500(fg, delete=False)
        u = self._run(fg, 19800, caplog)                   # vs 20300: −2.5 %
        assert u["outcome"] == "BLOCKED" and u["collection_check"]["deleted_tests"] == 0

    def test_deleted_test_files_are_subtracted_by_the_static_count(self, fg, caplog):
        body = "".join(f"it('case {i}', () => {{}});\n" for i in range(490)) + \
            "test.each([1])('e', () => {});\nit.skip('s', () => {});\ntest.todo('t');\n" + \
            "".join(f"test('t{i}', () => {{}});\n" for i in range(7)) + "// commit( and submit( are not tests\n"
        a = _main_commit(fg, {"src/old.test.ts": body})
        _seed(fg, a, 20300)
        _main_commit(fg, delete=["src/old.test.ts"])
        u = self._run(fg, 19800, caplog)                   # 20300 − 500 = 19800: equal
        c = u["collection_check"]
        assert c["deleted_tests"] == 500 and c["compared_with"] == 19800 and u["outcome"] == "PASS", c
        assert "approx −500 deleted" in c["line"]

    def test_a_reused_entry_is_compared_from_the_chains_second_link(self, fg, caplog, monkeypatch):
        monkeypatch.delenv("ORCH_FULLGATE_REUSE", raising=False)
        a = _git(fg.repo, "rev-parse", "main")
        _seed(fg, a, 20300)
        b = _main_commit(fg, {"src/b.ts": "b\n"})
        _seed(fg, b, 19543)                                # this tree's fresh entry: the reused leg
        with caplog.at_level(logging.INFO, logger="orch"):
            fg.run()
        u = fg.state()["unit"]
        assert u["reused"]["sha"] == b and "unit" not in fg.calls
        assert u["collection_check"]["reference_sha"] == a and u["outcome"] == "BLOCKED", u

    def test_a_reused_entry_with_no_other_link_is_never_its_own_reference(self, fg, caplog, monkeypatch):
        monkeypatch.delenv("ORCH_FULLGATE_REUSE", raising=False)
        _seed(fg, _git(fg.repo, "rev-parse", "main"), 19543)
        with caplog.at_level(logging.INFO, logger="orch"):
            fg.run()
        u = fg.state()["unit"]
        assert u["reused"] and u["outcome"] == "PASS"                     # judged as today (the control half)
        if "collection_check" in u or hasattr(orchestrator, "_full_gate_collection"):
            assert u["collection_check"]["reference"] is None
            assert "other than the reused one" in u["collection_check"]["line"]

    def test_a_malformed_threshold_is_ignored_loudly(self, fg, caplog):
        _seed(fg, _git(fg.repo, "rev-parse", "main"), 20300)
        orchestrator.ACTIVE_REPO_CONFIG["full_gate_collection_drop_same_pct"] = "lots"
        u = self._run(fg, 20178, caplog)
        assert u["outcome"] == "BLOCKED" and u["collection_check"]["threshold_pct"] == 0.5
        assert any("full_gate_collection_drop_same_pct='lots' is not a positive number" in m for m in _msgs(caplog))


# ═══════════════════════════════════════════════════════
# P-A5 · the kill switch
# ═══════════════════════════════════════════════════════
class TestPA5Off:

    @pytest.mark.parametrize("value", ["off", "OFF", "Off "])
    def test_off_restores_heads_full_gate_verdicts_with_one_warning(self, fg, caplog, monkeypatch, value):
        monkeypatch.setenv("ORCH_UNIT_LOAD_CHECK", value)
        nm = fg.link_node_modules()
        _seed(fg, _git(fg.repo, "rev-parse", "main"), 20300)
        fg.unit_out = suite(denied=D, nm=nm, total_tests=19543)
        fg.confirm_out = suite(denied=D, nm=nm, total_tests=0, total_files=3)
        with caplog.at_level(logging.INFO, logger="orch"):
            fg.run()
        u = fg.state()["unit"]
        assert u["outcome"] == "FAIL(product)" and u["new"] == D and "collection_check" not in u

    def test_off_says_so_once_per_gate(self, fg, caplog, monkeypatch):
        monkeypatch.setenv("ORCH_UNIT_LOAD_CHECK", "off")
        fg.unit_out = suite(denied=D, nm=fg.link_node_modules())
        with caplog.at_level(logging.INFO, logger="orch"):
            fg.run()
        warn = [m for m in _msgs(caplog) if "ORCH_UNIT_LOAD_CHECK=off" in m]
        assert len(warn) == 1 and warn[0].startswith("⚠️  full-gate unit: ORCH_UNIT_LOAD_CHECK=off")

    def test_off_restores_heads_route_gate_verdict_and_caching(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setenv("ORCH_UNIT_LOAD_CHECK", "off")
        r = RouteRepo(tmp_path, monkeypatch, branch_out=suite(failing=[D[0]]),
                      base_out=suite(denied=D, failing=[UB], nm="<NM>"),
                      confirm_out=suite(failing=[D[0]], total_files=1))
        with caplog.at_level(logging.INFO, logger="orch"):
            o = orchestrator.run_unit_gate(r.repo, "route")
        assert o.passed and len(_cache(r.archive)) == 1      # HEAD: the base's "failure" masks it, and is cached
        if hasattr(orchestrator, "UNIT_LOAD_CHECK_VAR"):
            assert len([m for m in _msgs(caplog) if "ORCH_UNIT_LOAD_CHECK=off" in m]) == 1

    def test_off_skips_the_classifier_signal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORCH_UNIT_LOAD_CHECK", "off")
        assert unit_verdict(PROBE, tmp_path).outcome is PRODUCT
