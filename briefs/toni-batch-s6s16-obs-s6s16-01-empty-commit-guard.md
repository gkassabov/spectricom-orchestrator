# Toni Batch S6S16 — OBS-S6S16-01: Conditional commit (no empty markers)

## Repo: spectricom-orchestrator
## Batch ID: s6s16-obs-s6s16-01-empty-commit-guard
## Briefs: 1
## Estimated runtime: 10-15m
## Predecessor: orchestrator main current tip
## Fire mechanism: orchestrator with --repo orchestrator
## TONI_TIMEOUT_MIN: 20

## CONTEXT

S6S16 HARNESS-FIX-01 fired three times consecutively (terminal paste mangled the brief filename, causing two failed retries that then succeeded after path correction). The two "successful retries" produced **empty marker commits** on top of the real fix:

- `a26c1f66` — REAL HARNESS-FIX-01 fix (8 files, 309+/89-)
- `7284956c` — empty marker (no files changed)
- `c7079647` — empty marker (no files changed)
- `15c63e2c` — empty marker (no files changed)

All four shipped through the `passed | 1 briefs | 178s` happy path. The three empty commits are noise: the orchestrator's `git commit --allow-empty` flag (line 1075) creates a commit even when Toni's diff is empty.

Fix: replace `--allow-empty` with conditional logic that skips the commit when there's nothing to commit, and emits a clear warning instead.

## GOAL

Conditional commit: stage all changes, check if anything is actually staged, commit only if yes, log a clear warning if no.

## FILES

- `orchestrator.py` — function that handles post-Toni commit + merge (around line 1067-1090 in the auto-commit block)
- Add a small unit test or integration test if the existing test pattern supports it

## ACCEPTANCE CRITERIA

1. **No empty commits on no-change runs.** After Toni runs and exits 0 with no file changes, orchestrator does NOT call `git commit`.
2. **Clear warning logged.** When no changes detected, log emits: `⚠️ Toni produced no changes — skipping commit (usually means idempotent re-fire or halt-and-report)`.
3. **Normal runs unaffected.** Toni runs that produce real changes commit and merge as before. No regression on the happy path.
4. **Branch cleanup.** When no commit is made, the orchestrator branch is deleted (clean state on main, no orphan branch).
5. **Final summary distinguishes outcomes.** The `━━━ ✅ ... passed | 1 briefs | Ns ━━━` summary shows either "passed" or "passed (no changes)" — operator can tell at a glance.
6. **Existing tests pass.** No regression in `tests/`.
7. **Idempotent re-fire test.** Fire the same brief twice in a row. First fire: real commit. Second fire: warning + no commit + clean state.

## IMPLEMENTATION SKETCH

Current code (around line 1067-1090):

```python
if branch_name and worktree is None:
    try:
        if status == Status.PASSED:
            subprocess.run("git add -A", shell=True, cwd=str(proj), capture_output=True)
            commit_msg = f"fix: {batch_file.stem} — {len(briefs)} briefs"
            r = subprocess.run(
                f'git commit -m "{commit_msg}" --allow-empty',
                shell=True, capture_output=True, text=True, cwd=str(proj)
            )
            ...
```

Replace with:

```python
if branch_name and worktree is None:
    try:
        if status == Status.PASSED:
            subprocess.run("git add -A", shell=True, cwd=str(proj), capture_output=True)

            # Check if anything is staged
            diff_check = subprocess.run(
                "git diff --cached --quiet",
                shell=True, capture_output=True, cwd=str(proj)
            )
            has_changes = diff_check.returncode != 0

            if has_changes:
                commit_msg = f"fix: {batch_file.stem} — {len(briefs)} briefs"
                r = subprocess.run(
                    f'git commit -m "{commit_msg}"',
                    shell=True, capture_output=True, text=True, cwd=str(proj)
                )
                if r.returncode == 0:
                    log.info(f"📦 Committed: {commit_msg}")
                    # Merge back to merge target — existing logic
                    ...
                else:
                    log.warning(f"⚠️ Commit failed: {r.stderr.strip()}")
            else:
                log.warning(
                    "⚠️ Toni produced no changes — skipping commit "
                    "(usually means idempotent re-fire or halt-and-report)."
                )
                # Cleanup branch
                subprocess.run(f"git checkout {MERGE_TARGET}", shell=True, capture_output=True, cwd=str(proj))
                subprocess.run(f"git branch -D {branch_name}", shell=True, capture_output=True, cwd=str(proj))
                # Mark status for summary
                no_change_run = True
```

Add a status flag `no_change_run` (or refactor to a Status.PASSED_NO_CHANGES enum if cleaner) so the final summary can distinguish.

In the final summary block (find via `grep -n "passed.*briefs.*s$" orchestrator.py` or similar), update the format string to show `(no changes)` when `no_change_run` is true.

## OUT OF SCOPE

- Fixing whatever causes the re-fire in the first place (the brief is idempotent, that's by design).
- Detecting and consolidating duplicate empty markers from the past (e.g., the three S6S16 markers — those stay, this fix prevents future ones).
- Per-brief idempotency markers (separate problem).
- Auto-aborting re-fires (different feature; this brief is just about avoiding empty commits when re-fires happen).

## DEFINITION OF DONE

- Conditional commit logic shipped in `orchestrator.py`.
- Warning message exact text: `⚠️ Toni produced no changes — skipping commit (usually means idempotent re-fire or halt-and-report).`
- Branch cleanup on no-change path.
- Final summary distinguishes "passed" from "passed (no changes)".
- Tests pass.
- Commit message: `OBS-S6S16-01: Conditional commit — drop --allow-empty flag (S6S16)`.

## §29 / §31

§29 standard.

§31 smoke test:
1. Find a previously-merged batch (any from S6S15 will do).
2. Re-fire it: `python3 orchestrator.py run <that-batch.md> --approve`.
3. Expected: orchestrator runs Toni, Toni produces no diff (idempotent), orchestrator logs the warning, no new commit on main.
4. Verify: `git log --oneline -3 main` shows the same 3 commits as before the re-fire.
5. Verify: `git branch | grep orch-` shows no orphan branches.
