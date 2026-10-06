# filename: briefs/123c-orch-capacity-1r.handback.md

# 123c · ORCH-CAPACITY-1r: handback

Route 123b's capacity work is carried over unchanged except for one thing: ai-foundation's `test_cmd` and `build_gate_cmd` are back to `main`'s. **`pytest -q tests/` gives 1062 passed, 0 failed.** The guard that was red at `507f015`, `TestTheSuiteCommandIsNotNarrowed::test_no_repo_test_cmd_changed_on_this_branch`, is now green, and I did not edit it.

Things you need to know first:
- **Three statements in 123b's handback are out of date.** Its file is carried byte-for-byte (`507f015`), so the corrections are here:
  - Its C2 section and THE CONSEQUENCE give ai-foundation's gate as `. /home/gkassa/spectricom-ai-foundation/venv/bin/activate && …`. The shipped command is now `main`'s: `. venv/bin/activate && PYTHONPATH=. pytest`.
  - Its Found-and-LEFT 12 says the first ai-foundation route re-measures its baseline. That no longer happens. The cache key hashes the command (`_unit_cache_key`, `orchestrator.py:3041`), and the command is `main`'s again.
  - Its "1062 passed at `fb0fa69`" is not what the orchestrator's own gate measured on that branch: 1 failed, 1061 passed (Found-and-LEFT 2 and 3).
- **The C2 flip still needs no command change.** Once ai-foundation's `.gitignore:1` reads `venv`, the route worktree's `venv` link is ignored, and `main`'s relative command runs through that link with a clean tree (probe in the gate table). 123b's remedy order (its Found-and-LEFT 1) stands. The absolute path was never needed.
- **Gemma restarts the daemon after this merges.** The steps are under THE CONSEQUENCE.

- **Branch:** `orch-orch-123c-orch-capacity-1r`, from `e028795` (= `main`), fast-forwarded to `507f015`.
- **Commits:**
  - `fb0fa69`: 123b's code, carried with the same SHA.
  - `507f015`: 123b's handback, carried with the same SHA.
  - `d071cc7`: this route's fix (`config/repos.yaml`, `tests/test_capacity.py`).
  - The next commit is this file.
- **Tests:** `pytest -q tests/` at `d071cc7` → **1062 passed in 47.68 s, 0 failed**. 123b's 66 tests in `test_capacity.py` are all still there and green; three of them were changed (Shipped).

## Found and LEFT

1. **123b's Found-and-LEFT 1–11 and 13–15 still stand, unchanged and out of scope (§4).** They cover the ai-foundation `.gitignore` venv fix, the C2 flip, detaching the checkout, the Listen sitting stuck at `recording`, and `minime-listen-ingest.service` being `failed`. Its item 12 no longer applies (above).
2. **123b's gate saw a real red and labelled it environment.**
   - In `~/spectricom-orchestrator/logs/orchestrator/orch-123b-orch-capacity-1-20261005-230035.log`, lines 55–56 read `FAILED tests/test_unit_baseline_gate.py::TestTheSuiteCommandIsNotNarrowed::test_no_repo_test_cmd_changed_on_this_branch` and `1 failed, 1061 passed in 164.17s`.
   - Line 58 gives the verdict: `BLOCKED(environment) — build: clock-implausible (build outlier-vs-history: Δwall 166.0s > 5 × median 28.1s of its history — a red measured on that clock is not a product verdict)`.
   - The red was deterministic: it fails here in 0.40 s (§0.2). The clock check took precedence over a real failure. The merge was withheld, so nothing bad landed, but the label pointed away from the cause.
   - Changing the gate is outside §3, so I left it.
3. **The guard reads only committed history.** It runs `git diff main...HEAD`, so a suite run before a route's commit cannot see that route's config change.
   - Observed here: with the fix in the working tree but not yet committed, the guard still failed against `507f015`'s committed config (gate table). After `d071cc7` it passed.
   - So 123b's "1062 passed at `fb0fa69`" was most likely measured before its commit. That is my inference; I cannot see that run.
   - The guard must not be edited (§1), so I left it.
4. **`test_negative_control_the_relative_command_fails_there` now describes the shipped command.** It shows that `main`'s command fails in a worktree with no `venv`, which is why the flip needs the link, and so the `.gitignore` fix. I did not change it: it does not pin the shipped lines.
5. **I did not commit this brief.** It is outside §3, as with routes 94, 104, 114 and 123b.

## §0 as-built (L-30)

1. **Confirmed.** `git log --oneline -2 orch-orch-123b-orch-capacity-1`:
   ```
   507f015 handback: 123b-orch-capacity-1 — found-and-left, gate table, the consequence (ORCH-CAPACITY-1, S7-CORE-21)
   fb0fa69 fix(orch): one Toni route at a time and only with memory to spare; … (ORCH-CAPACITY-1, S7-CORE-21)
   ```
   Their parent is `e028795`, which is both `main` and this route's HEAD at fire. `git merge --ff-only orch-orch-123b-orch-capacity-1` put HEAD at `507f015`, with both SHAs unchanged.
2. **Confirmed.** At `507f015`, `pytest -q "tests/test_unit_baseline_gate.py::TestTheSuiteCommandIsNotNarrowed"` → `1 failed, 2 passed in 0.40s`:
   ```
   E         -    test_cmd: ". venv/bin/activate && PYTHONPATH=. pytest"
   E         -    build_gate_cmd: ". venv/bin/activate && PYTHONPATH=. pytest -q"
   E         +    test_cmd: ". /home/gkassa/spectricom-ai-foundation/venv/bin/activate && PYTHONPATH=. pytest"
   E         +    build_gate_cmd: ". /home/gkassa/spectricom-ai-foundation/venv/bin/activate && PYTHONPATH=. pytest -q"
   E       assert ['-    test_c...TH=. pytest"'] == []
   E         Left contains 2 more items, first extra item: '-    test_cmd: ". venv/bin/activate && PYTHONPATH=. pytest"'
   tests/test_unit_baseline_gate.py:1035: AssertionError
   ```
   The line that fails is `assert _changed_test_cmd_lines(r.stdout) == [], f"AC-O5-07 violated — test_cmd touched:\n{r.stdout}"`.
3. **Confirmed.** At `507f015`, ai-foundation has `worktree_mode: single-stream`, and `head -1 ~/spectricom-ai-foundation/.gitignore` → `venv/`. The flip stays stopped, so an ai-foundation route runs in the checkout itself. That checkout has `venv/`, and the relative command works there.

## Shipped (`d071cc7`)

### `config/repos.yaml`
- ai-foundation's two lines (now lines 63–64) are byte-for-byte `main`'s:
  ```
      test_cmd: ". venv/bin/activate && PYTHONPATH=. pytest"
      build_gate_cmd: ". venv/bin/activate && PYTHONPATH=. pytest -q"
  ```
- I also removed the two comment lines fb0fa69 put above them (`# C2: the services' venv by absolute path — a route worktree has no venv/ of its own. …`). They described only the absolute command, so above the relative one they would be wrong. These are the only lines I touched besides the two commands.
- Kept as fb0fa69 shipped them: the `admission:` block; `worktree_mode: single-stream`; and `worktree_base: /home/gkassa/aif-toni` with its STAGED comment.

### `tests/test_capacity.py`: P4, three tests changed because they pinned or ran the absolute command
- `test_R_the_gate_command_names_the_services_venv_by_absolute_path` is now **`test_the_gate_command_is_mains`**. It asserts `main`'s `test_cmd` and `build_gate_cmd`.
- `test_R_the_gate_command_runs_green_in_a_worktree_with_no_venv` is now **`test_the_gate_command_runs_green_in_the_checkout_it_runs_in`**.
  - It runs the shipped command verbatim through `_run_unit_suite`, in a fixture checkout with its gitignored `venv/`. That is where a single-stream route runs it.
  - Result: `1 passed`, and `git status --porcelain` is empty.
  - The old version replaced the absolute path with the fixture's path, and a relative command would fail in a worktree with no venv.
- **`test_the_shipped_command_verbatim_with_the_real_venv`** used to run in a temp worktree with no venv. It now runs in a temp checkout whose `venv` links to the real one. It still only reads: `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider`.
- `test_R_` marks a test that is red at base. The two renamed tests assert `main`'s own command, so they pass at `main` too, and they lose the `R_`.
- Nothing else pins those lines. `grep -n "test_cmd\|build_gate_cmd\|venv"` finds no other test that does. `admission.py:348` only asks whether `test_cmd` is set, for the gate budget, so ai-foundation's wall is unchanged at 3000 s. `scripts/aif-deploy.sh` reads no gate command.

## Gate table

| Gate | Result |
|---|---|
| §0.1 carry | `git merge --ff-only` → HEAD `507f015`; `fb0fa69` and `507f015` unchanged |
| §0.2 red at `507f015` | guard class: **1 failed, 2 passed** in 0.40 s |
| Guard + `test_capacity.py`, fix in the working tree, not yet committed | 1 failed (the guard), 68 passed: the guard diffs committed history (Found-and-LEFT 3) |
| Guard + `test_capacity.py` at `d071cc7` | **69 passed** in 3.01 s |
| **P1** `git diff main -- config/repos.yaml` | no `+`/`-` line names `test_cmd` or `build_gate_cmd`. The `grep -n "test_cmd\|build_gate_cmd"` output for every repo is identical to `main`'s (`diff` exit 0). The only diffs are the `admission:` block, and ai-foundation's STAGED comment and `worktree_base` |
| **P2** `pytest -q tests/` at `d071cc7` | **1062 passed** in 47.68 s, 0 failed |
| Fix bounded to §3 | `git diff --stat 507f015 HEAD` → `config/repos.yaml` (2 lines restored, 2 comment lines dropped) and `tests/test_capacity.py` (17+, 21−) |
| Flip probe (temp repos under `/tmp`, removed) | `main`'s command in a route worktree whose `venv` links to the checkout's. `.gitignore` `venv/` → `1 passed`, `git status` `?? venv`. `.gitignore` `venv` → `1 passed`, status clean |
| Live, read-only | daemon pid **26875** alive (`python3 -u queue_daemon.py`, started Sun Oct 4 23:22:51); `spectricom-queue-daemon.service` inactive (no unit). `queue/held/s7c21-restart/` holds 124, 125, 126, 128 and 129. ai-foundation: HEAD `4f348510` on `refs/heads/main`, `.gitignore:1` `venv/` |
| Handback guard (`config/handback-guard.json`, `canon_assert.check_handback_invariants`) | this file, wrapped in a `TONI_HEADER` and a 60-`=` / `Exit: 0` trailer so the guard reads it as executor output (all 6 rules): **CLEAN** |
| Destructive operations | **None.** The probe's temp repos were removed. Nothing in `~/spectricom-orchestrator` or `~/spectricom-ai-foundation` was written. The stash was not touched |

## THE CONSEQUENCE (D-S7CORE13-03)

**From the next fire after this merges, before any restart:** 123b's THE CONSEQUENCE applies, with one change. ai-foundation's unit gate runs `main`'s `. venv/bin/activate && PYTHONPATH=. pytest` in the main checkout, as it did before 123b, and its cached baselines stay valid.

**Until the restart,** the old daemon keeps its fixed 11400 s wall. That wall is what kills 125 and 129 by construction, so they stay held until step 4. A route the old daemon fires is admitted one level down, in its own `run` (123b's Found-and-LEFT 7).

**Gemma: restart the daemon after this merges (L-29, L-46): pause → restart → resume.** These are 123b's steps, with the live facts re-read today.
1. **After this route has merged to `main`:** `cd ~/spectricom-orchestrator && python3 queue_daemon.py status` must show `"current_batch": null`.
2. **Pause:** `python3 queue_daemon.py pause` → `acknowledged request …`.
3. **Stop:** `kill 26875`, or the pid on `status` line 1.
4. **Re-queue** in the order you want them fired: `mv queue/held/s7c21-restart/<brief>.md queue/` for 124, 125, 126, 128 and 129. 125, 126 and 128 are ai-foundation; they run single-stream in the main checkout (123b's Found-and-LEFT 1).
5. **Start:** `nohup python3 -u queue_daemon.py >> ~/_eos/logs/s7core21-queue-daemon.log 2>&1 &`. The start lines include:
   - `[QUEUE] 🛡 admission: at most 1 live route(s) across every repo, and MemAvailable >= 6 GiB …`
   - `[QUEUE] 🛡 route-wall: … ; persisted timeout_seconds=11400 not applied`
   - With work queued, it comes up `PAUSED (start:queue-non-empty)`.
6. **Resume:** `python3 queue_daemon.py resume --reason start:queue-non-empty`.
7. **Check:** `status` line 1 shows the new pid `alive`. While a route runs, `current_batch.wall.describe` names its wall. While admission holds back the next brief, line 1 ends `| waiting: <brief> — <reason>`.

**George's calls** are 123b's, unchanged:
- ai-foundation's `.gitignore:1`: change `venv/` to `venv`, then make the one-line C2 flip.
- Whether to detach `~/spectricom-ai-foundation` from `main`.
- The sitting stuck at `recording`.
