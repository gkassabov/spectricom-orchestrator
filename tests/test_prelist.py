# filename: tests/test_prelist.py
"""Tests for ORCH-PRELIST-1 (ORCH-RELIABILITY-1 Brief 2 · S7-CORE-36 · D-S7CORE36-03; supersedes Kanban 488).

Four STOPs came from tests a hand-grepped pre-list missed: `341b3` (5 files reaching the provider through
`src/lib/llm/index.ts`), `341b5` (3 `vi.mock` factories), `341b1c3d` (SearchPage.test), `341b1c6` re-fire. At fire,
the brief's ALLOWED FILES become a synthetic diff (each path touched, uncommitted, in a detached worktree at the
route's base) and tests_reaching — the preflight's function (A13) — names what the gate would run; the route's copy
of the brief gets a `## GATE PRE-LIST` block of the files it does not already name.

  PL1  a module reached through an index file and `vi.mock`ed in a test elsewhere ⇒ that test is in the block
  PL2  a module whose rendered text a SIT locates, related by the SIT plan ⇒ the SIT file is in the block
  PL3  files the brief already names are not repeated
  PL4  ORCH_PRELIST=off ⇒ byte-identical; a set that cannot be computed ⇒ unchanged + a log line

Harness: a REAL git repository and a real detached worktree. `npx vitest list --changed` is scripted to answer from
the real `git status` of the directory it runs in — so the synthetic diff is what decides the related set, as the
installed vitest's `--changed` does. Module-level imports are existing symbols only (RED collects).
"""

import ast
import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_gate_cost import _activate, _git  # noqa: E402

ROOT = Path(__file__).parent.parent
SIT_LIST = "npx vitest list --config vitest.sit.config.ts"
PROVIDER, INDEX, PAGE = "src/lib/llm/provider.ts", "src/lib/llm/index.ts", "src/pages/SearchPage.tsx"
MOCKED = "src/feature/chat.test.ts"          # imports INDEX, `vi.mock('../lib/llm/provider')` — the 341b3/341b5 class
OTHER_UNIT = "src/feature/other.test.ts"
SEARCH_SIT = "sit/integration/search.integration.test.ts"   # getByPlaceholder('Search patients') — SearchPage's text
OTHER_SIT = "sit/integration/other.integration.test.ts"
UNIT_SUITE, SIT_SUITE = [MOCKED, OTHER_UNIT], [SEARCH_SIT, OTHER_SIT]
# what vitest's import graph relates to each changed source file
GRAPH = {"unit": {PROVIDER: [MOCKED], INDEX: [MOCKED]}, "sit": {PAGE: [SEARCH_SIT]}}


class Vitest:
    """`npx vitest list …` for both configs; `--changed` answers from the real `git status` of its cwd."""

    def __init__(self, monkeypatch, unit_rc=0):
        self.real, self.unit_rc, self.cwds = subprocess.run, unit_rc, []
        monkeypatch.setattr(subprocess, "run", self)

    def __call__(self, cmd, *a, **kw):
        if not (isinstance(cmd, str) and cmd.startswith("npx vitest list")):
            return self.real(cmd, *a, **kw)
        leg = "sit" if cmd.startswith(SIT_LIST) else "unit"
        self.cwds.append(kw.get("cwd"))
        if "--changed" not in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="\n".join(SIT_SUITE if leg == "sit" else UNIT_SUITE)
                                               + "\n", stderr="")
        if leg == "unit" and self.unit_rc:
            return subprocess.CompletedProcess(cmd, self.unit_rc, stdout="", stderr="Startup Error\n")
        st = self.real(["git", "-C", kw["cwd"], "status", "--porcelain"], capture_output=True, text=True).stdout
        changed = [l[3:] for l in st.splitlines()]
        out = [t for p in changed for t in GRAPH[leg].get(p, [])]
        return subprocess.CompletedProcess(cmd, 0, stdout="".join(f"{t}\n" for t in dict.fromkeys(out)), stderr="")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    files = {"package.json": json.dumps({"scripts": {"test": "vitest run"}}) + "\n", PROVIDER: "p\n",
             INDEX: "export * from './provider'\n", PAGE: "<input placeholder='Search patients'/>\n",
             "src/feature/chat.ts": "c\n", **{t: "t\n" for t in UNIT_SUITE + SIT_SUITE}}
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "M0")
    orch = tmp_path / "orch"
    (orch / "state").mkdir(parents=True)
    monkeypatch.setattr(orchestrator, "ORCH_DIR", orch)
    _activate(monkeypatch, tmp_path, repo, gates=("build", "sit"), sit_list_cmd=SIT_LIST)
    for var in ("ORCH_PRELIST", "ORCH_UNIT_RELATED"):
        monkeypatch.delenv(var, raising=False)

    class R:
        pass
    r = R()
    r.repo, r.monkeypatch, r.sha = repo, monkeypatch, _git(repo, "rev-parse", "HEAD")
    return r


def _brief(rig, allowed: str, extra: str = "") -> Path:
    b = rig.repo / "briefs" / "77-x.md"
    b.parent.mkdir(exist_ok=True)
    b.write_text(f"#!queue model=m effort=high repo=cost-repo\n# 77-x\n{extra}\n## B2 · ALLOWED FILES (Brief 2)\n"
                 f"{allowed}\n\n## STOP\n(a) `src/feature/chat.ts` is not allowed\n")
    return b


def _block(text: str) -> str:
    return text.split("## GATE PRE-LIST", 1)[1] if "## GATE PRE-LIST" in text else ""


class TestPL1IndexAndMock:

    def test_a_module_reached_through_an_index_and_mocked_elsewhere_names_that_test(self, rig, caplog):
        b = _brief(rig, f"`{PROVIDER}` (the provider) and `{PAGE}:12`")
        Vitest(rig.monkeypatch)
        with caplog.at_level(logging.INFO, logger="orch"):
            block = orchestrator.gate_prelist(b, rig.repo)
        text = b.read_text()
        assert block and f"- `{MOCKED}` (unit)" in _block(text), text
        assert f"## GATE PRE-LIST (generated at fire, {rig.sha[:7]}; D-S7CORE36-03)" in text
        assert text.rstrip().endswith(orchestrator.PRELIST_RULE)
        assert OTHER_UNIT not in text and OTHER_SIT not in text
        msgs = [r.getMessage() for r in caplog.records]
        assert f"📋 Gate pre-list generated: 1 SIT + 1 unit files for 2 allowed files at {rig.sha[:7]}" in msgs, msgs

    def test_the_synthetic_diff_lives_in_a_removed_worktree_and_the_checkout_is_untouched(self, rig):
        b = _brief(rig, f"`{PROVIDER}`")
        fake = Vitest(rig.monkeypatch)
        orchestrator.gate_prelist(b, rig.repo)
        assert fake.cwds and all(c != str(rig.repo) for c in fake.cwds), fake.cwds
        assert _git(rig.repo, "status", "--porcelain", "--untracked-files=no") == ""
        assert len(_git(rig.repo, "worktree", "list").splitlines()) == 1

    def test_the_set_is_tests_reaching(self, rig, monkeypatch):
        b = _brief(rig, f"`{PROVIDER}`")
        Vitest(rig.monkeypatch)
        seen, real = [], orchestrator.tests_reaching
        monkeypatch.setattr(orchestrator, "tests_reaching", lambda p, d: seen.append(d.paths) or real(p, d))
        orchestrator.gate_prelist(b, rig.repo)
        assert seen == [(PROVIDER,)]


class TestPL2SitLocator:

    def test_a_sit_that_locates_the_modules_text_is_in_the_block(self, rig):
        b = _brief(rig, f"`{PAGE}`")
        Vitest(rig.monkeypatch)
        orchestrator.gate_prelist(b, rig.repo)
        assert f"- `{SEARCH_SIT}` (SIT)" in _block(b.read_text())


class TestPL3NoRepeat:

    def test_files_the_brief_names_are_not_repeated(self, rig):
        b = _brief(rig, f"`{PROVIDER}`, `{PAGE}`", extra=f"RE-CHECK S7-CORE-36: `{MOCKED}` stays green.\n")
        Vitest(rig.monkeypatch)
        orchestrator.gate_prelist(b, rig.repo)
        block = _block(b.read_text())
        assert MOCKED not in block and f"- `{SEARCH_SIT}` (SIT)" in block, block

    def test_a_basename_counts_as_named(self, rig):
        b = _brief(rig, f"`{PAGE}`", extra="search.integration.test.ts must stay green\n")
        Vitest(rig.monkeypatch)
        orchestrator.gate_prelist(b, rig.repo)
        assert "(none beyond the test files this brief already names)" in _block(b.read_text())


class TestPL4OffAndUncomputable:

    def test_off_is_byte_identical(self, rig, caplog):
        b = _brief(rig, f"`{PROVIDER}`")
        before = b.read_bytes()
        rig.monkeypatch.setenv("ORCH_PRELIST", "off")
        fake = Vitest(rig.monkeypatch)
        with caplog.at_level(logging.INFO, logger="orch"):
            assert orchestrator.gate_prelist(b, rig.repo) is None
        assert b.read_bytes() == before and fake.cwds == []
        assert "📋 Gate pre-list not generated: ORCH_PRELIST=off" in [r.getMessage() for r in caplog.records]

    def test_uncomputable_is_unchanged_and_logged(self, rig, caplog):
        b = _brief(rig, f"`{PROVIDER}`")
        before = b.read_bytes()
        Vitest(rig.monkeypatch, unit_rc=1)
        with caplog.at_level(logging.INFO, logger="orch"):
            assert orchestrator.gate_prelist(b, rig.repo) is None
        assert b.read_bytes() == before
        msgs = [r.getMessage() for r in caplog.records if r.getMessage().startswith("📋 Gate pre-list not generated:")]
        assert len(msgs) == 1 and "unit:" in msgs[0], msgs

    def test_no_allowed_files_is_unchanged_and_logged(self, rig, caplog):
        b = _brief(rig, "`src/does/not/exist.ts`, `" + MOCKED + "` (a test file is not a source path)")
        before = b.read_bytes()
        with caplog.at_level(logging.INFO, logger="orch"):
            assert orchestrator.gate_prelist(b, rig.repo) is None
        assert b.read_bytes() == before
        assert any("name no existing non-test file" in r.getMessage() for r in caplog.records)


class TestAllowedFiles:

    def test_both_heading_shapes_and_only_their_sections(self):
        text = ("## ALLOWED FILES\n`a.py` and `docs/x.md:3-9`\n### sub\n`b.py`\n## STOP\n`c.py`\n"
                "## C2 · ALLOWED FILES (Brief C)\n`d.py`, `x/y.test.ts`, `briefs/z.md`, `a.py`\n# end\n`e.py`\n")
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            for f in ("a.py", "docs/x.md", "b.py", "c.py", "d.py", "x/y.test.ts", "briefs/z.md", "e.py"):
                (Path(td) / f).parent.mkdir(parents=True, exist_ok=True)
                (Path(td) / f).write_text("x\n")
            assert orchestrator.brief_allowed_paths(text, Path(td)) == ["a.py", "docs/x.md", "b.py", "d.py"]


def test_the_fire_calls_it_on_the_route_copy_before_toni():
    tree = ast.parse((ROOT / "orchestrator.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_run_batch_inner")
    calls = {n.func.id: n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "gate_prelist" in calls and calls["gate_prelist"] < calls["capture_handoff"] < calls["fire_toni"]
