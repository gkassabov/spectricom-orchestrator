## STATUS: DONE

# ORCH-STOP-COMMIT-SUBJECT-1 + PREFIRE-NPM-HOOK-NOTE-1 (Kanban 885 + 886) — handback

G-1 applied verbatim: `rh.patch` sha256 `4e93216719836b99a081f0793a33bf5d33dc30c6799a18f6a063417f69449a2f` (verified), `git apply --check` clean on HEAD; 4 files (orchestrator.py, prefire.py, tests/test_stop_commit_subject.py new, tests/test_prefire_npm_notes.py new). No existing test edited. No file outside ALLOWED FILES touched.

## Predecessor
`git merge-base --is-ancestor 4c3423f HEAD` → true (HEAD = `4c3423f`).

## A0 (at HEAD, before any edit) — all as the brief states
1. `git ls-files tests/test_stop_commit_subject.py tests/test_prefire_npm_notes.py` → nothing
2. `git grep -n "route_commit_message\|npm_hook_notes\|NPM_HOOK" -- orchestrator.py prefire.py` → 0 lines
3. `orchestrator.py:8305:                        commit_msg = f"fix: {batch_file.stem} — {len(briefs)} briefs"`
4. `orchestrator.py:8234:    hb_status = _log_handback_status(route_handback_path(` (above A0-3)
5. `executor/hooks/npm_frozen.py:595:def judge_text(text: str, d, env, depth: int):`

## RED (base + the two new tests only; `git apply --include='tests/*'`)
`python3 -m pytest -q -p no:cacheprovider tests/test_stop_commit_subject.py tests/test_prefire_npm_notes.py` → **10 failed, 2 passed in 5.41s**
- PASSED S-3, S-4 (controls)
- FAILED S-1, S-2, S-5, S-6, N-1, N-2, N-3, N-4, N-5, N-6

## GREEN (after G-1)
`python3 -m pytest -q -p no:cacheprovider tests/test_stop_commit_subject.py tests/test_prefire_npm_notes.py tests/test_handback_stop_status.py tests/test_npm_frozen_hook.py` → **269 passed in 64.31s**

The two new files alone: **12 passed in 3.29s**
- [S-1] ['stop: 685-x — 1 briefs — handback STOP (g)', 'M0']
- [S-2] ['partial: 685-x — 1 briefs — handback PARTIAL']
- [S-3] ['fix: 685-x — 1 briefs']
- [S-4] ['fix: 685-x — 1 briefs']
- [S-5] 'stop: 685-x — 1 briefs — handback STOP ("q" $HOME; : >S5)'  (no `S5` file created in the repo or cwd)
- [N-1] ["NPM ⚠ `npx vitest run --maxWorkers=1 src/a.test.ts` — the executor's npm hook refuses it: 🛡 npm frozen: 'npx vitest run --maxWorkers=1 src/a.test.ts' is refused — npx runs only without downloading: re-run it as 'n…
- [N-2] ["NPM ⚠ `npm exec vitest -- --version` — the executor's npm hook refuses it: 🛡 npm frozen: 'npm exec vitest -- --version' is refused — the executor may run only npm ci, npm run <script> (or run-script), npm test (or…
- [N-4] 6 lines, last 'NPM ⚠ … and 2 more'

## Suite
Not run by the executor (test scope: targeted; ORCH-LEAN-GATE-1 — the pre-merge gate runs the full unit suite). The author's dry run with G-1 had it green: 1070 passed · 1199 passed, 1 skipped · 1024 passed, 3 skipped.

## Typecheck
None. orchestrator is a Python repo with no tsc project.

## Commit
One commit on `orch-orch-000000885-orch-stop-commit-subject-1`: `STOP-COMMIT-SUBJECT-1 + PREFIRE-NPM-HOOK-NOTE-1 (885 + 886; …)`. Its SHA is in the route log and `git log`.

## Notes
- 885 takes effect at the daemon's next restart (rule #12). prefire's CLI uses 886 at once.
- `executor/hooks/npm_frozen.py` was read, never edited.
