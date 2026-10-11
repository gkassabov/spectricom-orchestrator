"""ORCH-PREFIRE-RUNTIME-1 (S7-CORE-24) D3 · LESSONS L-92 — a brief can declare that its route needs its own dependency
tree instead of the main checkout's linked one.

L-92: a Yorsie route worktree's `yorsie/node_modules` is a link to the checkout yorsie-dev.service runs from
(UNIT_BASELINE_LINK_PATHS, _link_unit_deps), so a dependency-upgrade route installs into the live service's tree, and
its unit-baseline leg runs on the route's new packages (route 143: BLOCKED(environment), handback 8077419).

  D3  `## Isolated deps: true` — the route worktree, and its unit-baseline worktree, build their own trees (`npm ci`
      beside a node_modules; a venv from requirements.txt beside a venv) instead of linking UNIT_BASELINE_LINK_PATHS,
      and teardown removes them with the worktree. Absent → the links, unchanged. The route log names the mode.
  P4  a fixture route through the real run_batch (tests/test_control_scope.py's WorktreeRoute): its worktree has a
      real node_modules, what the route installs never reaches the dev tree, and teardown removes it. Control: the
      header absent → the link as today — and what the route installs lands in the dev tree (L-92 itself).

`npm ci` is faked by an `npm` on PATH (no registry in a test); every other npm call is the real npm. The venv is real.
"""
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orchestrator  # noqa: E402
from tests.test_control_scope import WorktreeRoute, _sha  # noqa: E402  (the real-run_batch fixture route)

DEV_DEP = "a dependency the route needs\n"    # WorktreeRoute's dev-tree yorsie/node_modules/dep.txt
FAKE_NPM = """#!/bin/sh
if [ "$1" = ci ]; then
  pwd -P >> "$NPM_CI_LOG"
  [ -f package-lock.json ] || { echo "npm ERR! npm ci can only install with an existing package-lock.json" >&2; exit 1; }
  mkdir -p node_modules && echo "npm ci in $(pwd -P)" > node_modules/dep.txt
  exit 0
fi
exec "$REAL_NPM" "$@"
"""
LOCKFILE = json.dumps({"name": "stub", "lockfileVersion": 3, "requires": True, "packages": {}})


@pytest.fixture
def fake_npm(tmp_path, monkeypatch):
    """Returns the file `npm ci` appends its working directory to, once per install."""
    real = shutil.which("npm")
    if real is None:
        pytest.skip("npm is not on PATH (the fixture route's build gate runs it)")
    bindir = tmp_path / "fake-bin"
    bindir.mkdir()
    (bindir / "npm").write_text(FAKE_NPM)
    (bindir / "npm").chmod(0o755)
    calls = tmp_path / "npm-ci.log"
    monkeypatch.setenv("REAL_NPM", real)
    monkeypatch.setenv("NPM_CI_LOG", str(calls))
    monkeypatch.setenv("PATH", f"{bindir}:{orchestrator.os.environ['PATH']}")
    return calls


def _ok(cmd: str, cwd: Path) -> str:
    r = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, f"{cmd}: {r.stderr}"
    return r.stdout.strip()


def _ci_dirs(calls: Path) -> list:
    return calls.read_text().splitlines() if calls.exists() else []


# ═══════════════════════════════════════════════════════
# the header
# ═══════════════════════════════════════════════════════
@pytest.mark.parametrize("line,isolated", [
    ("## Isolated deps: true", True), ("## Isolated deps: True", True), ("## Isolated deps: `true`", True),
    ("## Isolated deps: **true**", True), ("##Isolated deps:true", True),
    ("## Isolated deps: false", False), ("", False), ("Isolated deps: true", False)])
def test_the_header(tmp_path, line, isolated):
    b = tmp_path / "b.md"
    b.write_text(f"#!queue repo=yorsie\n## Repo: yorsie\n{line}\n")
    assert orchestrator.parse_isolated_deps(b) is isolated


def test_a_value_that_is_neither_true_nor_false_links_and_says_so(tmp_path, caplog):
    b = tmp_path / "b.md"
    b.write_text("## Isolated deps: yes\n")
    with caplog.at_level(logging.WARNING, logger="orch"):
        assert orchestrator.parse_isolated_deps(b) is False
    assert "'## Isolated deps: yes' is not 'true' or 'false' — the dependency trees are LINKED" in caplog.text


# ═══════════════════════════════════════════════════════
# P4 · a fixture route through the real run_batch
# ═══════════════════════════════════════════════════════
class DepsRoute(WorktreeRoute):
    """WorktreeRoute's Yorsie-shaped route, with a lockfile, and an executor that upgrades a dependency."""

    def __init__(self, tmp_path, monkeypatch, header: str):
        super().__init__(tmp_path, monkeypatch)
        monkeypatch.setattr(orchestrator, "ISOLATED_DEPS", orchestrator.ISOLATED_DEPS)   # run_batch sets it
        (self.proj / "yorsie" / "package-lock.json").write_text(LOCKFILE)
        self.brief.write_text(self.brief.read_text() + header)
        _ok("git add -A && git commit -qm 'lockfile, header'", self.proj)
        self.main_before = _sha("main", self.proj)
        self.dev_deps = self.proj / "yorsie" / "node_modules"

    def fire_upgrading(self):
        def upgrade(_dev):
            nm = self.seen["proj"] / "yorsie" / "node_modules"
            self.seen.update(link=nm.is_symlink(), real_dir=nm.is_dir() and not nm.is_symlink(),
                             dep=(nm / "dep.txt").read_text())
            (nm / "upgraded-pkg.txt").write_text("v2\n")    # what the route's `npm install x@2` writes
        return self.fire(meanwhile=upgrade)


@pytest.fixture
def isolated(tmp_path, monkeypatch, fake_npm):
    return DepsRoute(tmp_path, monkeypatch, "## Isolated deps: true\n")


@pytest.fixture
def linked(tmp_path, monkeypatch, fake_npm):
    return DepsRoute(tmp_path, monkeypatch, "")


class TestP4:

    def test_R_the_route_worktree_has_its_own_node_modules(self, isolated, fake_npm):
        r = isolated.fire_upgrading()
        assert r.status is orchestrator.Status.PASSED, r.error
        assert isolated.seen["proj"] == isolated.wt
        assert isolated.seen["real_dir"] and not isolated.seen["link"], "a real directory, not a link"
        assert isolated.seen["dep"] == f"npm ci in {(isolated.wt / 'yorsie').resolve()}\n"
        assert _ci_dirs(fake_npm) == [str((isolated.wt / "yorsie").resolve())], "one `npm ci`, in the route's tree"
        cwd, branch, deps = isolated.probed()
        assert (cwd, deps) == (str((isolated.wt / "yorsie").resolve()), "deps"), "the build gate sees the route's tree"

    def test_R_what_the_route_installs_never_reaches_the_dev_tree(self, isolated):
        isolated.fire_upgrading()
        assert not (isolated.dev_deps / "upgraded-pkg.txt").exists()
        assert (isolated.dev_deps / "dep.txt").read_text() == DEV_DEP
        assert not isolated.dev_deps.is_symlink()

    def test_R_teardown_removes_the_tree_with_the_worktree(self, isolated):
        r = isolated.fire_upgrading()
        assert r.status is orchestrator.Status.PASSED and r.gate_outcome == "PASS", r.error
        assert not isolated.wt.exists(), "the worktree, and the node_modules it built, are gone"
        assert isolated.worktrees() == [str(isolated.proj)]
        assert (isolated.dev_deps / "dep.txt").read_text() == DEV_DEP, "teardown never reaches the dev tree's"

    def test_R_the_route_log_names_the_mode(self, isolated, caplog):
        caplog.set_level("INFO", logger="orch")
        isolated.fire_upgrading()
        assert "📦 deps: ISOLATED (## Isolated deps: true)" in caplog.text
        assert (f"🌳 Route worktree: {isolated.wt} (from main; isolated deps — built its own yorsie/node_modules "
                f"(npm ci); linked from {isolated.proj}: nothing) — the main checkout is not the route's, nor are "
                f"its dependency trees") in caplog.text
        assert f"🌳 Route worktree removed: {isolated.wt} (with the dependency trees it built)" in caplog.text

    def test_a_failed_route_keeps_its_worktree_and_its_tree(self, isolated):
        r = isolated.fire(build_exit="1")
        assert r.status is orchestrator.Status.FAILED
        nm = isolated.wt / "yorsie" / "node_modules"
        assert nm.is_dir() and not nm.is_symlink()

    def test_negative_control_no_header_links_as_today(self, linked, fake_npm, caplog):
        caplog.set_level("INFO", logger="orch")
        r = linked.fire_upgrading()
        assert r.status is orchestrator.Status.PASSED, r.error
        assert linked.seen["link"] and linked.seen["dep"] == DEV_DEP
        assert _ci_dirs(fake_npm) == [], "no install"
        assert "📦 deps: linked" in caplog.text
        assert (f"🌳 Route worktree: {linked.wt} (from main; 1 dependency path(s) linked from {linked.proj}) — the "
                f"main checkout is not the route's") in caplog.text
        assert not linked.wt.exists() and (linked.dev_deps / "dep.txt").read_text() == DEV_DEP

    def test_negative_control_the_link_is_the_L92_hazard(self, linked):
        """Linked, the route's upgrade is written into the tree the dev server runs from."""
        linked.fire_upgrading()
        assert (linked.dev_deps / "upgraded-pkg.txt").read_text() == "v2\n"


class TestIsolatedInstallRefusals:
    """A tree that cannot be built is a route that does not fire — never a silent fall-back to the link."""

    def test_npm_ci_failing_refuses_the_route(self, tmp_path, monkeypatch, fake_npm, caplog):
        route = DepsRoute(tmp_path, monkeypatch, "## Isolated deps: true\n")
        _ok("git rm -q yorsie/package-lock.json && git commit -qm 'no lockfile'", route.proj)
        caplog.set_level("INFO", logger="orch")
        r = route.fire()
        assert r.status is orchestrator.Status.FAILED and r.exit_code == 2
        assert r.error.startswith("route-worktree: isolated deps: yorsie/node_modules: `npm ci` exit 1: npm ERR!")
        assert "proj" not in route.seen, "the executor never ran"
        assert not route.wt.exists() and route.worktrees() == [str(route.proj)], "the half-built worktree is removed"
        assert (route.dev_deps / "dep.txt").read_text() == DEV_DEP
        assert "⛔ ROUTE WORKTREE — isolated deps: yorsie/node_modules: `npm ci` exit 1" in caplog.text

    def test_a_tree_git_does_not_ignore_refuses_the_route(self, tmp_path, monkeypatch, fake_npm):
        """`git add -A` would commit it."""
        route = DepsRoute(tmp_path, monkeypatch, "## Isolated deps: true\n")
        (route.proj / "yorsie" / ".gitignore").write_text("dist\n")
        _ok("git add yorsie/.gitignore && git commit -qm 'node_modules not ignored'", route.proj)
        before = _sha("main", route.proj)
        r = route.fire()
        assert r.status is orchestrator.Status.FAILED
        assert "yorsie/node_modules is not git-ignored in" in r.error and "`git add -A` would commit it" in r.error
        assert not route.wt.exists() and route.worktrees() == [str(route.proj)]
        assert _sha("main", route.proj) == before, "nothing merged"


# ═══════════════════════════════════════════════════════
# D3 · the unit-baseline worktree
# ═══════════════════════════════════════════════════════
@pytest.fixture
def node_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _ok("git init -q && git symbolic-ref HEAD refs/heads/main && git config user.email t@t && "
         "git config user.name T", repo)
    (repo / ".gitignore").write_text("node_modules\n")
    (repo / "package.json").write_text(json.dumps({"name": "stub", "private": True}))
    (repo / "package-lock.json").write_text(LOCKFILE)
    _ok("git add -A && git commit -qm base", repo)
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "dep.txt").write_text("the checkout's\n")
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "fixture-repo")   # declares no env_file
    monkeypatch.setattr(orchestrator, "ISOLATED_DEPS", orchestrator.ISOLATED_DEPS)
    return repo


def _measure(repo: Path, monkeypatch) -> tuple:
    seen = {}

    def suite(cmd, cwd, ref):
        nm = Path(cwd) / "node_modules"
        seen.update(cwd=Path(cwd), link=nm.is_symlink(), dep=(nm / "dep.txt").read_text())
        return orchestrator.UnitSuiteRun(ref=ref, exit_code=0)
    monkeypatch.setattr(orchestrator, "_run_unit_suite", suite)
    run = orchestrator._run_unit_baseline(repo, _sha("HEAD", repo), "npm test")
    return run, seen


class TestBaselineWorktree:

    def test_R_isolated_the_baseline_builds_its_own_tree_and_removes_it(self, node_repo, monkeypatch, fake_npm,
                                                                        caplog):
        monkeypatch.setattr(orchestrator, "ISOLATED_DEPS", True)
        caplog.set_level("INFO", logger="orch")
        run, seen = _measure(node_repo, monkeypatch)
        assert run.error is None
        assert seen["link"] is False and seen["dep"] == f"npm ci in {seen['cwd'].resolve()}\n"
        assert _ci_dirs(fake_npm) == [str(seen["cwd"].resolve())]
        assert not seen["cwd"].exists(), "removed with the baseline worktree"
        assert _ok("git worktree list --porcelain", node_repo).count("worktree ") == 1
        assert (node_repo / "node_modules" / "dep.txt").read_text() == "the checkout's\n"
        assert "in a detached worktree (isolated deps — built its own node_modules (npm ci))" in caplog.text

    def test_negative_control_linked_the_baseline_runs_on_the_checkouts_tree(self, node_repo, monkeypatch,
                                                                             fake_npm, caplog):
        caplog.set_level("INFO", logger="orch")
        run, seen = _measure(node_repo, monkeypatch)
        assert seen["link"] is True and seen["dep"] == "the checkout's\n"
        assert _ci_dirs(fake_npm) == []
        assert "in a detached worktree (1 dependency path(s) linked)" in caplog.text
        assert (node_repo / "node_modules" / "dep.txt").read_text() == "the checkout's\n"

    def test_an_install_that_fails_is_an_unmeasured_baseline(self, node_repo, monkeypatch, fake_npm):
        monkeypatch.setattr(orchestrator, "ISOLATED_DEPS", True)
        _ok("git rm -q package-lock.json && git commit -qm 'no lockfile'", node_repo)
        run, seen = _measure(node_repo, monkeypatch)
        assert (run.exit_code, run.error) == (-1, "baseline-deps-install-failed")
        assert "node_modules: `npm ci` exit 1" in run.output
        assert seen == {}, "no suite ran"
        assert _ok("git worktree list --porcelain", node_repo).count("worktree ") == 1


# ═══════════════════════════════════════════════════════
# D3 · a Python repo: a venv of its own, from requirements.txt
# ═══════════════════════════════════════════════════════
@pytest.fixture
def py_repo(tmp_path, monkeypatch):
    repo = tmp_path / "py"
    repo.mkdir()
    _ok("git init -q && git symbolic-ref HEAD refs/heads/main && git config user.email t@t && "
         "git config user.name T", repo)
    (repo / ".gitignore").write_text("venv\n")
    (repo / "requirements.txt").write_text("")
    _ok("git add -A && git commit -qm base", repo)
    (repo / "venv" / "bin").mkdir(parents=True)
    (repo / "venv" / "bin" / "activate").write_text("# the checkout's venv\n")
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "fixture-repo")
    return repo


def test_a_python_repo_gets_a_venv_of_its_own(py_repo, tmp_path):
    dst = tmp_path / "wt"
    _ok(f"git worktree add -q --detach {dst} main", py_repo)
    built, why = orchestrator._install_unit_deps(py_repo, dst)
    assert why is None and built == [dst / "venv"]
    assert (dst / "venv").is_dir() and not (dst / "venv").is_symlink()
    assert (dst / "venv" / "bin" / "python").exists() and (dst / "venv" / "pyvenv.cfg").exists()
    assert _ok("git status --porcelain", dst) == "", "ignored, so `git add -A` leaves it"
    assert (py_repo / "venv" / "bin" / "activate").read_text() == "# the checkout's venv\n"


def test_a_python_repo_without_requirements_is_refused_not_given_an_empty_venv(py_repo, tmp_path):
    _ok("git rm -q requirements.txt && git commit -qm 'no requirements'", py_repo)
    dst = tmp_path / "wt"
    _ok(f"git worktree add -q --detach {dst} main", py_repo)
    built, why = orchestrator._install_unit_deps(py_repo, dst)
    assert built == [] and why == f"venv: no requirements.txt in {dst} to build it from"
    assert not (dst / "venv").exists()


def test_only_the_trees_the_checkout_has_are_built(node_repo, tmp_path, fake_npm):
    """The same paths _link_unit_deps would link — no venv for a Node repo, no node_modules where none is used."""
    dst = tmp_path / "wt"
    _ok(f"git worktree add -q --detach {dst} main", node_repo)
    built, why = orchestrator._install_unit_deps(node_repo, dst)
    assert why is None and built == [dst / "node_modules"]
    assert not (dst / "venv").exists() and not (dst / ".venv").exists()


def test_isolated_links_the_env_file_alone(tmp_path, monkeypatch):
    """The env_file is not a dependency tree: it is linked for parity in both modes ([ORCH-9])."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "node_modules").mkdir(parents=True)
    (src / ".env").write_text("K=V\n")
    dst.mkdir()
    monkeypatch.setitem(orchestrator.PRE_MERGE_GATES, "fixture-repo", {"gates": ("build",), "env_file": ".env"})
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "fixture-repo")
    assert orchestrator._link_unit_deps(src, dst, isolated=True) == [dst / ".env"]
    dst2 = tmp_path / "dst2"
    dst2.mkdir()
    assert {p.name for p in orchestrator._link_unit_deps(src, dst2)} == {"node_modules", ".env"}
