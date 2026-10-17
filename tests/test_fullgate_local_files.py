# filename: tests/test_fullgate_local_files.py
"""Tests for ORCH-FULLGATE-LOCAL-FILES-1 (S7-CORE-31 · SCP_Kanban row 282).

The first full gate (clinical-mp, 2026-10-16 21:38 on a4f0e18) was BLOCKED(environment) after 12 batches /
1421 s: 31 SIT files down at setup, 0 failed assertions. Its detached worktree had the dependency trees and the
env_file (_link_unit_deps) but not `.medplum-admin-credentials.local` — git-ignored (`*.local`), read by
sit/integration/probe-identity.ts when ADMIN_PASSWORD is unset. The per-merge SIT runs in the checkout, which
has it, so only the full gate broke.

  P1 (D1) each path `full_gate_link_files` lists is symlinked into the full gate's worktree beside
          _link_unit_deps and removed with those links; no file content reaches a log. Absent key ⇒ exactly
          the links HEAD made                                                             (TestP1*)
  P2 (D2) a listed path the checkout does not have ⇒ the SIT leg BLOCKED before any batch, naming it; the
          unit leg runs. The dry run says present / missing for each                      (TestP2*)
  P3 (D3) each leg's part of the verdict line says how many local files were linked, and which (TestP3*)

Harness: tests.test_gate_cost.FullGate — a real project repo, a real detached worktree; only the suite commands
are scripted. The listed file is this test's own fixture; its sentinel content must appear in no log.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_gate_cost import REPO, FullGate, _commit, _git, _msgs  # noqa: E402

KEY = "full_gate_link_files"
LOCAL, OTHER, NESTED = ".x.local", ".y.local", "config/.z.local"
SENTINEL = "sentinel-282-never-logged"


class LocalGate(FullGate):
    """FullGate, recording — at the first suite command of each kind — the symlinks its cwd holds."""

    def __init__(self, tmp_path, monkeypatch):
        super().__init__(tmp_path, monkeypatch)
        # git-ignored in the checkout, as clinical-mp's `.gitignore:15 *.local`; the checkout stays clean
        (self.repo / ".git" / "info" / "exclude").write_text("*.local\nnode_modules\n")
        (self.repo / "node_modules").mkdir()          # a dependency tree _link_unit_deps links, as at HEAD
        self.links, self.cwds_seen = {}, set()

    def listed(self, *paths):
        orchestrator.ACTIVE_REPO_CONFIG[KEY] = list(paths)

    def local(self, rel=LOCAL):
        (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / rel).write_text(f"Password: {SENTINEL}\n")
        return (self.repo / rel).stat()

    def deps(self) -> dict:
        return {"node_modules": str((self.repo / "node_modules").resolve())}

    def target(self, rel=LOCAL) -> str:
        return str((self.repo / rel).resolve())

    def __call__(self, cmd, *a, **kw):
        if isinstance(cmd, str) and cmd.startswith(("npm ", "npx ")) and kw.get("cwd"):
            cwd = Path(kw["cwd"])
            self.cwds_seen.add(cwd)
            kind = ("list" if cmd.startswith("npx vitest list") else "sit" if cmd.startswith("npm run sit:gate")
                    else "unit")
            self.links.setdefault(kind, _symlinks(cwd))
        return super().__call__(cmd, *a, **kw)

    def worktrees(self) -> set:
        return {c for c in self.cwds_seen if c != self.repo}


def _symlinks(root: Path) -> dict:
    """{repo-relative path: target} for every symlink under `root`; a linked tree is not descended."""
    out = {}
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            p = Path(d) / n
            if p.is_symlink():
                out[p.relative_to(root).as_posix()] = os.readlink(p)
    return out


@pytest.fixture
def lg(tmp_path, monkeypatch):
    return LocalGate(tmp_path, monkeypatch)


def _verdict(caplog) -> str:
    lines = [m for m in _msgs(caplog) if m.startswith(f"🌙 full-gate {REPO} @ ") and "): " in m]
    assert len(lines) == 1, lines
    return lines[0]


def _everything_written(lg, caplog, capsys) -> str:
    """Every log record, stdout/stderr, the full-gate log file and the state file."""
    cap = capsys.readouterr()
    st = lg.state()
    log_file = Path(st["log"]).read_text() if st.get("log") and Path(st["log"]).exists() else ""
    state_file = lg.orch / "state" / f"full-gate-{REPO}.json"
    return "\n".join(_msgs(caplog) + [cap.out, cap.err, log_file, state_file.read_text() if state_file.exists() else ""])


# ═══════════════════════════════════════════════════════
# P1 · D1 — the listed files are linked beside the dependency trees, and torn down with them
# ═══════════════════════════════════════════════════════
class TestP1Linked:

    def test_a_listed_file_is_a_symlink_in_the_worktree_and_gone_after(self, lg, caplog, capsys):
        caplog.set_level("DEBUG")
        lg.listed(LOCAL)
        before = lg.local()
        assert lg.run() == 0
        want = {**lg.deps(), LOCAL: lg.target()}
        assert lg.links == {"list": want, "sit": want, "unit": want}, "every leg runs with it linked"
        (wt,) = lg.worktrees()
        assert not wt.exists() and len(_git(lg.repo, "worktree", "list").splitlines()) == 1
        after = (lg.repo / LOCAL).stat()
        assert (after.st_ino, after.st_size, after.st_mtime_ns) == (before.st_ino, before.st_size, before.st_mtime_ns), \
            "teardown removed the link, never its target"
        assert SENTINEL not in _everything_written(lg, caplog, capsys), "no file content in any log"

    def test_a_nested_path_is_linked_at_its_place(self, lg):
        lg.listed(NESTED)
        lg.local(NESTED)
        assert lg.run() == 0
        assert lg.links["unit"] == {**lg.deps(), NESTED: lg.target(NESTED)}

    @pytest.mark.parametrize("value", ["absent", []], ids=["key-absent", "empty-list"])
    def test_negative_control_no_key_links_exactly_what_head_linked(self, lg, caplog, value):
        if value != "absent":
            orchestrator.ACTIVE_REPO_CONFIG[KEY] = value
        lg.local()                                    # on disk in the checkout, not listed
        assert lg.run() == 0
        assert lg.links == {"list": lg.deps(), "sit": lg.deps(), "unit": lg.deps()}
        assert lg.calls == ["list", "batch", "batch", "batch", "unit"]
        st = lg.state()
        assert "local_files" not in st["sit"] and "local_files" not in st["unit"]
        assert "local file" not in _verdict(caplog) and not any("🔗" in m for m in _msgs(caplog))

    def test_the_dry_run_worktree_links_it_beside_the_deps_and_removes_both(self, lg, capsys):
        lg.listed(LOCAL)
        lg.local()
        _commit(lg.repo, "other", write={"src/b.ts": "export const b = 2;\n"})   # the checkout stays on main
        assert lg.run("other", dry_run=True) == 0
        assert lg.links == {"list": {**lg.deps(), LOCAL: lg.target()}}
        (wt,) = lg.worktrees()
        assert not wt.exists() and len(_git(lg.repo, "worktree", "list").splitlines()) == 1
        assert "a detached worktree" in capsys.readouterr().out


# ═══════════════════════════════════════════════════════
# P2 · D2 — a listed file the checkout lacks: SIT BLOCKED before any batch, named; unit still runs
# ═══════════════════════════════════════════════════════
class TestP2Missing:

    def test_sit_is_blocked_before_any_batch_naming_the_path_and_unit_runs(self, lg):
        lg.listed(LOCAL)
        assert lg.run() == 1
        st = lg.state()
        assert st["outcome"] == "BLOCKED" and st["exit_code"] == 1
        sit = st["sit"]
        assert (sit["ran"], sit["outcome"], sit["signal"]) == (False, "BLOCKED", "local-file-missing")
        assert sit["detail"] == f"{KEY}: {LOCAL} not in {lg.repo}"
        assert lg.calls == ["unit"], "0 batches — not even the enumeration"
        assert (st["unit"]["ran"], st["unit"]["outcome"]) == (True, "PASS")

    def test_negative_control_present_runs_every_batch(self, lg):
        lg.listed(LOCAL)
        lg.local()
        assert lg.run() == 0 and lg.calls == ["list", "batch", "batch", "batch", "unit"]
        assert lg.state()["sit"]["outcome"] == "PASS"

    def test_one_of_two_missing_links_the_other_and_names_only_the_missing(self, lg):
        lg.listed(LOCAL, OTHER)
        lg.local()
        assert lg.run() == 1
        assert lg.state()["sit"]["detail"] == f"{KEY}: {OTHER} not in {lg.repo}"
        assert lg.links == {"unit": {**lg.deps(), LOCAL: lg.target()}}

    @pytest.mark.parametrize("bad", ["/etc/hostname", "../outside.local"])
    def test_a_path_that_is_not_repo_relative_is_never_linked_and_blocks_sit(self, lg, bad):
        lg.listed(bad)
        assert lg.run() == 1
        assert lg.state()["sit"]["detail"] == f"{KEY}: {bad} is not a repo-relative path"
        assert lg.links == {"unit": lg.deps()} and lg.calls == ["unit"]

    def test_the_dry_run_says_present_or_missing_for_each(self, lg, capsys):
        lg.listed(LOCAL, OTHER)
        lg.local()
        assert lg.run(dry_run=True) == 1, "a real run's SIT leg would be BLOCKED"
        out = capsys.readouterr().out
        assert f"  local file {LOCAL} ({KEY}): present in {lg.repo} — would be linked into the worktree" in out
        assert f"  local file {OTHER} ({KEY}): MISSING — {OTHER} not in {lg.repo}; a real run's SIT leg would be " \
               f"BLOCKED before any batch, the unit leg still runs" in out
        assert lg.state() == {} and lg.calls == ["list"]

    def test_negative_control_the_dry_run_with_no_key_says_nothing_new(self, lg, capsys):
        lg.local()
        assert lg.run(dry_run=True) == 0
        assert "local file" not in capsys.readouterr().out


# ═══════════════════════════════════════════════════════
# P3 · D3 — each leg's verdict says how many local files were linked, and which
# ═══════════════════════════════════════════════════════
class TestP3VerdictLine:

    def test_each_leg_names_the_count_and_the_names(self, lg, caplog):
        lg.listed(LOCAL, NESTED)
        lg.local()
        lg.local(NESTED)
        assert lg.run() == 0
        line = _verdict(caplog)
        said = f"; local files linked 2/2: {LOCAL}, {NESTED}"
        sit_part, unit_part = line.split(" | ")[:2]
        assert sit_part.startswith(f"🌙 full-gate {REPO} @ ") and " sit PASS (" in sit_part and sit_part.endswith(said)
        assert unit_part.startswith("unit PASS (") and unit_part.endswith(said)
        st = lg.state()
        assert st["sit"]["local_files"] == st["unit"]["local_files"] == {"linked": [LOCAL, NESTED], "not_linked": []}
        assert f"🔗 full-gate {REPO}: {KEY} — {said[2:]}" in _msgs(caplog)

    def test_a_missing_file_is_counted_and_named_on_both_legs(self, lg, caplog):
        lg.listed(LOCAL, OTHER)
        lg.local()
        lg.run()
        sit_part, unit_part = _verdict(caplog).split(" | ")[:2]
        said = f"; local files linked 1/2: {LOCAL} (not linked: {OTHER})"
        assert sit_part.endswith(f"sit BLOCKED ({KEY}: {OTHER} not in {lg.repo}){said}")
        assert unit_part.startswith("unit PASS (") and unit_part.endswith(said)
        assert any(m.startswith(f"⛔ full-gate {REPO}: {KEY}: {OTHER} not in {lg.repo} — the SIT leg is BLOCKED "
                                f"before any batch; the unit leg runs") for m in _msgs(caplog))

    def test_none_linked_says_zero(self, lg, caplog):
        lg.listed(LOCAL)
        lg.run()
        assert _verdict(caplog).count(f"; local files linked 0/1 (not linked: {LOCAL})") == 2
