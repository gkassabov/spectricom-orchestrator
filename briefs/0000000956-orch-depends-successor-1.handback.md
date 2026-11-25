## STATUS: DONE

# ORCH-DEPENDS-SUCCESSOR-1 (Kanban 956; L-538; D-S7CORE62-14) — handback

## Predecessor
`git merge-base --is-ancestor e084f47 HEAD` → exit 0 (HEAD = `e084f47`).

## A0 (at HEAD, before any edit) — all as built
1. `prefire.py:1027:def dependency_status(filepath: Path, queue_dir: Path,` → 1 line
2. `prefire.py:1050:        judged.append(Dependency(stem, f"{repo.name}/{repo.merge_target}",` → 1 line
3. `successor_stems\|successor_queued` in prefire.py → none (git grep exit 1)
4. `canon_assert.py:589:def route_landed_product(repo: QueueRepo, brief: str, briefs_subdir: str = "briefs",` → 1 line

## Patch
`sha256sum ~/_eos/s7core62/r956/b956.patch` → `b9d95518ba14c1ef2f8176263683917414bc185fe4081047edb43d697c676421` (matches). Applied with `git apply` as written:
G-2 first (`--include=tests/test_depends_successor.py`) for RED, then G-1 (`--include=prefire.py`). 2 files, +156 / −3.

## RED (base + G-2 only)
`pytest -q tests/test_depends_successor.py` → **5 failed, 3 passed** (S1, S5, S6, the stems lister, S7 red; S2, S3, S4 green). Matches the brief.

## GREEN (G-1 + G-2)
`pytest -q tests/test_depends_successor.py tests/test_depends_on.py tests/test_depends_product.py` → **59 passed**.
`py_compile prefire.py queue_daemon.py orchestrator.py` → ok.

## Whole suite
**Not run by the executor.** The brief's header is `## Test scope: targeted`, and both the repo's CLAUDE.md (ORCH-LEAN-GATE-1, D-S7CORE54-77) and the fire prompt forbid a full suite unless the header says `full`. The pre-merge gate runs the full unit suite. Gemma's dry run recorded 3342 passed, 1 skipped, 0 failed on the same patch.

## Environment note
This route worktree has no `venv/`. Tests ran with `~/spectricom-orchestrator/venv/bin/python` against the worktree's files. Nothing was linked or added to the worktree.

## Commit
See the commit sha in the route log (one commit: `prefire.py`, `tests/test_depends_successor.py`, this handback).

## Takes effect
At the **next daemon restart** (rule #12) for the daemon's queue order (`_next_brief`). Prefire's A11 imports prefire fresh at each fire, so it uses the new rule from the merge on. Briefs already in `queue/held/depends-on/` are not moved back automatically (see OPEN ITEMS in the brief).
