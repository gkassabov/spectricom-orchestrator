# filename: tests/test_prefire_npm_notes.py
"""Tests for PREFIRE-NPM-HOOK-NOTE-1 (Kanban 886).

The executor's npm hook (executor/hooks/npm_frozen.py, ORCH-NPM-FROZEN-1) refuses `npm exec`, a bare `npx <tool>` and
every npm subcommand off its list. Route 873 (2026-11-22) STOPPED (guard) because its A0-3 was an `npm exec` the hook
refused; route 865r's executor had to re-write every `npx vitest …` as `npx --no-install vitest …`. prefire now names
each brief command the hook would refuse, with the hook's own line — a NOTE beside the verdict, never a failure.

  N-1  a bare `npx vitest …` → one note naming it and the hook's `--no-install` line
  N-2  `npm exec …` → a note
  N-3  controls: `npx --no-install …`, `npm ci`, `npm run build`, `git apply …` → no note
  N-4  a command inside a ```diff fence (patch text) is not judged; each command is named once; at most 5 + a count
  N-5  a note is never a failure: check() is unchanged by it, and report() prints it with the same verdict
  N-6  nothing is judged when the brief's repo has no project_dir, or the hook cannot be loaded

The hook runs against a throwaway project (package.json + node_modules/.bin/vitest, tsc); config/repos.yaml is a temp
file. Module-level imports are existing symbols only, so the RED run on the base collects.
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import prefire  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    (proj / "node_modules" / ".bin").mkdir(parents=True)
    (proj / "package.json").write_text("{}\n")
    for tool in ("vitest", "tsc", "eslint"):
        (proj / "node_modules" / ".bin" / tool).write_text("#!/bin/sh\n")
    cfg = tmp_path / "repos.yaml"
    cfg.write_text(yaml.safe_dump({"kanban_dir": str(tmp_path), "repos": {"clinical-mp": {"project_dir": str(proj)}}}))
    monkeypatch.setattr(prefire, "REPOS_CONFIG", cfg)
    return proj


def brief(tmp_path, body: str, repo: str = "clinical-mp") -> Path:
    p = tmp_path / "b.md"
    p.write_text(f"#!queue model=claude-opus-5-5 effort=high repo={repo}\n\n# X-1 — fixture\n\n{body}\n", encoding="utf-8")
    return p


def notes(p: Path) -> list:
    fn = getattr(prefire, "npm_hook_notes", None)
    assert fn is not None, "prefire.npm_hook_notes is missing"
    return fn(p)


def test_N1_a_bare_npx_is_named_with_the_hooks_line(tmp_path, project):
    got = notes(brief(tmp_path, "## RED / GREEN\n- RED: `npx vitest run --maxWorkers=1 src/a.test.ts` → fails.\n"))
    print(f"[N-1] {got}")
    assert len(got) == 1
    assert got[0].startswith("NPM ⚠ `npx vitest run --maxWorkers=1 src/a.test.ts` — the executor's npm hook refuses it: ")
    assert "npx --no-install vitest" in got[0]


def test_N2_npm_exec_is_named(tmp_path, project):
    got = notes(brief(tmp_path, "## A0\n3. `npm exec vitest -- --version` → the version.\n"))
    print(f"[N-2] {got}")
    assert len(got) == 1 and got[0].startswith("NPM ⚠ `npm exec vitest -- --version`")


def test_N3_controls_draw_no_note(tmp_path, project):
    body = ("- `npx --no-install vitest run src/a.test.ts` · `npx --no-install tsc --noEmit` · `npm ci` · "
            "`npm run build` · `git apply ~/x.patch` · `NODE_OPTIONS=--max-old-space-size=8192 npx --no-install tsc --noEmit`\n")
    assert notes(brief(tmp_path, body)) == []


def test_N4_diff_fence_ignored_dedup_and_cap(tmp_path, project):
    fence = "```diff\n+// run `npx vitest run` here\n```\n"
    assert notes(brief(tmp_path, fence)) == []
    body = "".join(f"- `npx vitest run src/{i}.test.ts`\n- `npx vitest run src/{i}.test.ts`\n" for i in range(7))
    got = notes(brief(tmp_path, body))
    print(f"[N-4] {len(got)} lines, last {got[-1]!r}")
    assert len(got) == 6 and got[-1] == "NPM ⚠ … and 2 more"


def test_N5_a_note_is_never_a_failure(tmp_path, project, monkeypatch, capsys):
    p = brief(tmp_path, "- `npx vitest run src/a.test.ts`\n")
    assert not any("NPM" in f for f in prefire.check(p)), "check() carries no NPM line"
    monkeypatch.setattr(prefire, "check", lambda fp: ["A1 KANBAN — fixture failure"])
    assert prefire.report(p) is False
    out = capsys.readouterr().out
    assert "• A1 KANBAN — fixture failure" in out and "NPM ⚠ `npx vitest run src/a.test.ts`" in out
    assert "• NPM" not in out, "the note is printed as a note, not as a failure bullet"


def test_N6_nothing_judged_without_a_project_or_the_hook(tmp_path, project, monkeypatch):
    assert notes(brief(tmp_path, "- `npx vitest run a`\n", repo="nowhere")) == []
    monkeypatch.setattr(prefire, "NPM_HOOK", tmp_path / "missing.py", raising=False)
    assert notes(brief(tmp_path, "- `npx vitest run a`\n")) == []
