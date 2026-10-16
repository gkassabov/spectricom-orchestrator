# filename: briefs/279a-orch-gate-cost-1.handback.md

# 279a · ORCH-GATE-COST-1: handback

**A briefs-only merge runs no code gate (D1).** `run_pre_merge_gates` diffs the branch against its merge base (`git diff --name-only --no-renames <base>...<branch>`). When every path is under the repo's `briefs_subdir`, it returns PASS without running build, SIT or unit:
`PASS (briefs-only diff (2 files: briefs/268-one-owner-1.handback.md, briefs/268-one-owner-1.md) — build/SIT/unit not run (D-S7CORE29-02))`
- The same text rides into FINAL STATUS and `notify()`.
- It applies on every caller: the route lane, a route worktree, the meta-fire lane (whose verdict `_self_mod_auto_merge` consumes), and a parallel worker.
- These are not briefs-only, so the gates run: an empty diff, a diff that cannot be computed, a rename into or out of `briefs/`, a deleted file outside it, a handback outside it.

**The unit baseline is keyed on the non-briefs tree (D2).** The cache is now v2. An entry's key is a hash of `git ls-tree -r <sha>` with `briefs_subdir` removed, plus the repo and `test_cmd` as before. Each entry keeps the `sha` it was measured at and gains `content_key`.
- A merge base that differs from a measured commit only under `briefs/` hits. The note names both commits: `cache hit by content: measured at <A7>, merge base <B7>, non-briefs tree identical`.
- v1 entries are migrated on first load. An unreachable commit is dropped with one line.
- On the live cache, read in memory only: **217 v1 entries become 192. 25 were re-measurements of a tree already measured** (L-150), and none would be dropped.

**Per-merge SIT runs the related files (D3).** For a repo with `sit_list_cmd`, the set is the union of:
- (a) the files vitest 4.1.4 reports affected, from `<sit_list_cmd> --changed <merge base> --filesOnly` (enumerated, never run);
- (b) the SIT files the branch adds or changes;
- (c) `sit_core_files`, which is documented in repos.yaml and not set.

The verdict line names the mode: `sit[related 2/115 files] …` or `sit[full 115 files] …`.
- An empty union is **not applicable**: `sit: no SIT file relates to this diff (<n> changed files)`. It is PASS for that leg, never zero-collection.
- An enumeration failure runs the **full** suite and logs why.
- Batching, pauses, isolation and GATE-SIT-2 are unchanged on the related set.

**The full suites run as `full-gate` (D4).** The command is `python3 orchestrator.py full-gate --repo <name> [--ref main] [--dry-run]`.
- It runs the full SIT (batched as today) and the full unit suite in a detached worktree, holding the repo's fire lock.
- It writes `logs/<log_subdir>/full-gate-<ts>.log` and `state/full-gate-<repo>.json`.
- Exit codes: **0** only when nothing is new, **1** for NEW FAILURES or BLOCKED, **2** (one line, nothing run) when a fire lock for the repo is held or the daemon reports a route live.
- The daemon runs it once per local day for each repo with `full_gate_nightly: "HH:MM"`. clinical-mp is set to `"02:30"`. It runs only while the daemon is running and idle, as a scheduler step between routes.
- `qstat.sh` and `queue_daemon.py status` show each repo's last result.

> **Gemma: restart the queue daemon after this merges, once route 279a has ended:**
> `systemctl --user restart spectricom-queue-daemon.service`
> - If work is queued it starts paused (`start:queue-non-empty`). Lift that with `cd ~/spectricom-orchestrator && python3 queue_daemon.py resume --reason start:queue-non-empty`.
> - Check it with `python3 ~/spectricom-orchestrator/queue_daemon.py status`. Line 1 should end `| full-gate clinical-mp: never run (nightly 02:30)`.
> - **A restart after 02:30 runs today's full gate at the first idle, running moment (≈45 min). The next brief waits for it.** To avoid that, restart before 02:30, or accept it. The `orchestrator.py` half (D1–D3 and the `full-gate` command) loads on the next fire with no restart.

- **Branch:** `orch-orch-279a-orch-gate-cost-1`, from `4913a4f` (= `main` = merge-base). `git log 4913a4f..HEAD` was empty, so no file needed a re-read.
- **Commits:**
  - `0adf02a` holds `orchestrator.py`, `queue_daemon.py`, `qstat.sh`, `config/repos.yaml`, `tests/test_gate_cost.py` (new), `tests/test_config_truth.py` and `tests/test_unit_baseline_gate.py`.
  - The next commit is this file.
  - The brief is not committed, following routes 94–241.
- **Tests** (`pytest -q tests/`): **1206 passed** at `4913a4f` → **1271 passed** at `0adf02a`. There are 65 new items in `test_gate_cost.py`. None was deleted, none skipped.

## §0 As built (L-30)

**Premises, re-proven at `4913a4f`** (`git show 4913a4f:orchestrator.py | grep -n …`):
```
327:UNIT_BASELINE_CACHE_FILE = "unit-baseline-cache.json"   # in the sit-archive dir, gitignored
328:UNIT_BASELINE_CACHE_VERSION = 1
382:PRE_MERGE_GATES = {
1524:def _gate_parallel_branch(wt: Path, br: str) -> "GateVerdict":
1726:def _self_mod_auto_merge(orch_dir: Path, branch_name: str, gate_outcome: Optional[str] = None,
2169:def _sit_plan(repo_path: Path) -> Optional[SitPlan]:
2314:def _sit_isolate(sit_cmd: str, repo_path: Path, plan: SitPlan, files: list,
2391:def run_sit_post_merge(repo_path: Path, archive_path: Optional[Path] = None) -> SitOutcome:
2825:def _unit_merge_base(repo_path: Path, branch_name: Optional[str]) -> Optional[str]:
3136:def _unit_cache_key(repo_name: str, sha: str, cmd: str) -> str:
3528:def _unit_cache_ancestor(repo_path: Path, archive: Path, repo_name: str, base_sha: str,
3575:def _unit_baseline_measure_or_reuse(repo_path: Path, base_sha: str, cmd: str, archive: Path,
3672:def run_unit_gate(repo_path: Path, branch_name: Optional[str] = None,
3741:    branch_green = branch_run.exit_code == 0 and not branch_run.failing_files and (branch_run.failures or 0) == 0
4057:def sit_verdict_violations(so: SitOutcome, v: GateVerdict) -> list[str]:
4092:def run_pre_merge_gates(repo_path: Path, branch_name: Optional[str] = None) -> GateVerdict:
```
- Every premise holds. `run_pre_merge_gates` reads no diff: build → SIT → unit for every branch.
- The cache key is `repo@<merge-base sha>@md5(cmd)[:8]`.
- `git show 4913a4f:queue_daemon.py | grep -n "nightly\|schedule"` → lines 347, 369 and 1167, all about "scheduler" bookkeeping. There is no time-based job.

**The vitest mechanism.** It is `list --changed <ref>`, not `related`: `related` is a run command. The help below is from `npx vitest --help` / `list --help` / `related --help` in `~/spectricom-clinical-mp`, vitest **4.1.4**:
```
Commands:
  run [...filters]
  related [...filters]
  …
  list [...filters]
--changed [since]          Run tests that are affected by the changed files (default: false)      ← vitest --help
$ vitest list [...filters]
  --changed [since]        Print only tests that are affected by the changed files (default: false)  ← list --help
  --filesOnly              Print only test files with out the test cases
$ vitest related [...filters]                                                                    ← runs tests
```
- **Source** (`node_modules/vitest/dist/chunks/cli-api.lDy4N9kC.js`):
  - `GitVCSProvider.findChangedFiles` takes `git diff --name-only <since>...HEAD`, plus `git diff --cached --name-only`, plus `git ls-files --other --modified --exclude-standard`.
  - `filterTestsBySource` keeps a spec when it changed or its import graph reaches a changed file. It walks the graph with vite `transformRequest`, so nothing is executed.
  - A changed `forceRerunTriggers` file (`package.json`, `{vitest,vite}.config.*`) returns every spec.
  - `list --filesOnly` prints the files (`outputFileList`) without collecting them.
  - A git error is a `Collect Error` with exit 1.
  - Unhandled collection errors print `There were unhandled errors during test collection` and keep exit 0, which is why D3 reads the banners and not only the exit code.
- **Run read-only on the real checkout.** Afterwards `git status --porcelain` was empty and `node_modules/.vite` was unchanged:
  ```
  $ npx vitest list --config vitest.sit.config.ts --changed HEAD --filesOnly        → (no output) exit=0, 0.7 s
  $ npx vitest list --config vitest.sit.config.ts --changed HEAD~3 --filesOnly      → exit=0, 7.8 s
  sit/integration/drk-session-fixes-1.integration.test.tsx                         (diff: 4 briefs + that 1 SIT file)
  $ … --changed a18c50f5~1 --filesOnly                                              → exit=0, 66 of 115 SIT files
                                                                                      (diff: 52 files, 4 of them SIT files)
  ```
- So STOP (b) does not apply, and D3 is built.

**Find 1: the callers.** At `4913a4f`:
- `run_pre_merge_gates` is called from three places:
  - `:1536`, `_gate_parallel_branch`, the parallel lane;
  - `:4665`, the route lane in `_run_batch_inner`, also for a `worktree_mode: parallel` route;
  - `:4792`, the meta-fire lane, whose `result.gate_outcome` `run_batch` hands to `_self_mod_auto_merge` at `:4433`.
- `_self_mod_auto_merge` itself runs no gate. It refuses anything but PASS (`:1745`).
- `run_build_gate` / `run_sit_post_merge` / `run_unit_gate` are called only inside `run_pre_merge_gates` (`:4119`, `:4129`, `:4167`).
- So D1 lives in `run_pre_merge_gates` and reaches every caller. `TestP1BriefsOnlyThroughEachCaller` drives the route lane, the meta-fire lane → `_self_mod_auto_merge`, and `_gate_parallel_branch`.

**Find 2: where the changed-file list comes from.** `_unit_merge_base` (`:2825`) gives `git merge-base <merge_target> <branch>`, falling back to HEAD.
- The new `_branch_diff` (`orchestrator.py:4411`) reuses it and calls `branch_changed_paths` (`:4396`).
- What merges is exactly what is diffed:
  - the route lane `git add -A` + commit before the gate, then `git merge <branch>`;
  - the parallel lane commits first;
  - the self-mod merge is `--ff-only <branch>`.

**Find 3: the verdict-line readers** (lines at `4913a4f`).
- `queue_daemon.find_missing_gate_logs` (`queue_daemon.py:740`) calls `canon_assert.check_gate_log_invariants`. It checks that a route's own log exists and is readable and non-empty, and reads no gate line. A briefs-only merge still writes its route log.
- `qstat.sh` reads `queue-state.json`, the `state/running.json` mirror (pid, batch_id, branch, route_worktree) and git log.
- `orchestrator.py verify` keeps the lines matching `VERIFY_LOG_RE` (`:3329`, `FINAL STATUS|verdict|gate|baseline|\bSIT\b|unit|🛡|Merged`, IGNORECASE). The new lines match as `gate` / `sit[`.
- `sit:report` is `sit_report_aggregate` (`:4239`), over `orchestrator-sit-log.json`.
- `handback-scan` (`:3291`) reads only the executor's log, against `config/handback-guard.json`.
- One reader the brief did not name: `queue_daemon.route_phase` (`ROUTE_PHASES`, `:410-417`). It reads `Pre-merge gate.*: PASS` as the merge phase.
- Changed: qstat (a D4 line), `status` (a D4 line) and sit:report (scope / not-applicable). The others need no change. P5 has one test each.

**Find 4: what an on-demand full run must take so it never overlaps a route** (lines at `4913a4f`; at `0adf02a` the three lock functions are at `:1404` / `:1427` / `:1480`).
- **The repo's fire lock**, `state/running-<repo>.json` plus the mirror (`_write_running_marker` `:1372` / `_clear_running_marker` `:1395`, used unchanged):
  - it refuses a direct `run` for that repo (`_check_stale_marker` `:1448`);
  - it makes the daemon wait before a brief for that repo (`_fire_locks` `queue_daemon.py:948`);
  - `admission.live_routes` (`admission.py:156`) counts it, so with `max_concurrent_routes: 1` routes in every repo wait.
- **The refusal** (`_full_gate_refusal`) asks two things:
  - `admission.live_routes(ORCH_DIR)` for that repo: its lock, the mirror, a root marker naming it or naming none, or a claim, pid alive;
  - `queue-state.json` `current_batch` with the daemon's pid alive.
- `admission.py` is unchanged and only read.
- **The daemon's nightly step** additionally asks `admission.admit(repo)` (`claim=False`): no live route in any repo, and MemAvailable above its floor.

**Find 5: the tests that pin this behaviour.** The listed files plus `test_gate_clock.py`. Changed, both under pre-authorisation (a):
- `tests/test_config_truth.py:213`: `_seed` computed the key as `_unit_cache_key(REPO, sha, TEST_CMD)` and now uses the content key. **D2.**
- `tests/test_unit_baseline_gate.py:2043`: `UNIT_BASELINE_CACHE_VERSION == 1` → `== 2`. **D2.**

Nothing else needed to move:
- No test asserted (b) a briefs-only branch running every leg.
- No direct `run_sit_post_merge(repo)` test changes, because the full suite with no selection is unchanged (c).
- No `status`/`qstat` test changes (d): the full-gate segment is appended to line 1, and only appears when a repo has a schedule or a result.

## §1 Found and LEFT

1. **The brief's P6 premise for 268r reads only true from the route's merge base.**
   - `76f37cde`'s first parent (`2808bf70`) → it is **briefs-only**: `briefs/268r-one-owner-1r.md`, the orchestrator's own `fix: … — 1 briefs` commit at the route tip.
   - Route 268r's diff from its merge base `62a5e6be` is **32 paths, code included**.
   - The gate always diffs merge-base…branch, the whole route, so 268r is gated. A first-parent diff of a route's tip would have read it as briefs-only.
2. **The full SIT enumeration still runs per merge**, about 2 min on clinical-mp (P6's dry-run took 2 m 04 s).
   - The related set needs it: for N, for "the branch changed a SIT file" (b), for the per-file test counts the batches reconcile against (AC-SR-05), and to check that a vitest-listed file is in the suite.
   - The related list itself is about 8 s.
   - A related merge costs ≈2 min + its batches, against ≈25 min before.
3. **vitest relates by imports only.** The following relate to no SIT file, so with nothing else changed the leg is *not applicable*:
   - a fixture a SIT file reads with `fs`;
   - `sit/alex-mp/global-setup.ts` and other setup the SIT config does not name;
   - a `.env` change;
   - a lockfile-only change (`package-lock.json` is not a force-rerun trigger; `package.json` is).

   The one config vitest's triggers miss **and the gate sees** is the `--config` file in `sit_list_cmd`: a diff touching `vitest.sit.config.ts` runs the full suite (`_sit_config_file`). The lever for the rest is `sit_core_files` (Gemma's decision, not set) and the nightly full gate.
4. **`full-gate` stores its unit run as the tree's baseline.** When the run is plausible, measured and no judged entry exists for that tree, the result goes into the cache. The next route off that `main` then reuses it instead of re-measuring.
   - This is the same measurement a route's baseline leg makes: the same `test_cmd`, a detached worktree at that commit, the dependency trees linked. It goes through the same `_unit_cache_store`, so BASELINE-TRUST-1 / CONFIG-TRUTH-1 apply.
   - D4 did not ask for it. It is a few lines in `_full_gate_unit`.
5. **One-way cache migration.** The first unit gate after this merge rewrites the live `sit-archive/unit-baseline-cache.json` as v2.
   - Code from before this route reads v2 as "another version", that is empty. Its next store would write v1 over the v2 entries.
   - A rollback therefore costs the cache, not a verdict: every route re-measures.
6. **Two `test_unit_baseline_gate.py` tests now store nothing in their store step:** `test_an_entry_for_a_different_sha_is_not_used` and `test_a_non_ancestor_entry_is_never_borrowed`.
   - Their `active()` fixture names `project_dir: /x`, so no content key can be read, and `_unit_cache_store` says `NOT cached`.
   - They still pass, and I did not edit them (rule #8).
   - The same two properties are covered with a real repo in `test_gate_cost.py`: `test_a_src_change_misses` and `test_a_non_ancestor_measurement_is_never_borrowed_and_an_ancestor_is`.
7. **A related batch is its own GATE-CLOCK-1 leg kind, `sit-batch-related`.** A related batch holds 1–10 files. Judged against full 10-file batches it would make the nightly full batches read as 5× outliers.
   - Its history starts dormant (fewer than 3 samples).
   - Its sizes still vary, so a large related batch after small ones can be called an outlier. That only ever turns a red into BLOCKED(environment) `clock-implausible`, never into a PASS.
8. **What qstat and admission show while a full-gate runs.**
   - qstat's ROUTE / TONI lines (the mirror reader, outside the D4 line) show `batch=full-gate-<ts>` and `TONI branch=full-gate main | tree=/tmp/orch-full-gate-…`. The new `🌙 FULL-GATE … | running now` line says what it is.
   - `admission.live_routes` lists it as a live route, so the daemon's routes in every repo wait for it. That is the intended no-overlap.
9. **A full-gate may run beside a direct route in another repo.** Neither refusal condition in D4 covers that case (on demand). The nightly step is stricter: `admission.admit`, so no live route anywhere and memory above its floor.
10. **SIT `timeout-advisory` is BLOCKED in `full-gate`.** Per merge it stays a PASS, as before (D5). In `full-gate` a suite that did not finish knows nothing, so the result is BLOCKED, not PASS.
11. **The worktree's own dry-run shows `lock: free`.** Run from this worktree, `ORCH_DIR` is the worktree, so the dry-run's lock line reads the worktree's empty `state/`. Pointed at the live state (P6 b), the same check reports the daemon's live route 279a. After the merge `ORCH_DIR` is `~/spectricom-orchestrator`.
12. **What D1 leaves out in the meta-fire lane.**
    - Today the meta-fire build gate runs pytest on the worktree, uncommitted files included.
    - The D1 diff is the committed branch, because the self-mod merge brings in only that.
    - So a briefs-only commit set with uncommitted code in the worktree skips the build. That code does not merge either.

## D1–D4 as built (`0adf02a`)

- **D1:**
  - `BranchDiff` (`orchestrator.py:4388`).
  - `branch_changed_paths(repo_path, base_sha, branch)` (`:4396`): `git diff --name-only --no-renames -z <base>...<branch>`. It returns `()` for an empty diff and None when git cannot say. `--no-renames` so a rename names both of its paths.
  - `_branch_diff` (`:4411`).
  - `_under_subdir` / `_active_briefs_subdir` (`:3276`).
  - In `run_pre_merge_gates` (`:4429`): the diff at `:4445`, the briefs-only PASS at `:4450` (reason, and `collection` = reason). Otherwise one `🧾 Pre-merge gate …` line says the file count, or why the diff could not be computed.
  - `BRIEFS_ONLY_NAMED_FILES = 5` (`:389`).
- **D2:**
  - `UNIT_BASELINE_CACHE_VERSION = 2` (`:350`).
  - `_unit_content_key` (`:3296`): sha256 over the NUL-separated `ls-tree -r -z --full-tree` entries outside `briefs_subdir`, `[:32]`.
  - `_unit_cache_twins` / `_unit_cache_migrate_v1` / `_unit_cache_load(persist=)` (`:3317` / `:3339` / `:3379`). The `flaky` report and `--dry-run` migrate in memory only.
  - `_unit_cache_key` / `_unit_cache_entry_matches` / `_unit_cache_lookup` / `_unit_cache_store` / `_unit_cache_record_flakes` (`:3401` / `:3406` / `:3415` / `:3427` / `:3479`) key on the content key.
  - `_unit_baseline_measure_or_reuse` (`:3856`) looks up by content. The hit's ref reads `merge-base <B7> (measured at <A7>)` and its note `cache hit by content: …`. The `🛡 baseline-trust:` line is byte-identical (it is pinned).
  - `_unit_cache_ancestor` is unchanged.
- **D3:**
  - `SIT_CORE_FILES_KEY` / `SIT_RELATED_ARGS` / `_SIT_LIST_ERROR_RE` / `SIT_RELATED_BATCH_LEG` (`:263-270`).
  - `SitOutcome.scope` / `.not_applicable` and `collection`.
  - `SitPlan.tests_per_file`, `_parse_sit_listing` (`:2216`, `_sit_plan`'s parse, unchanged in effect).
  - `_sit_config_file` (`:2266`) and `_sit_related_files` (`:2282`).
  - `run_sit_post_merge(…, diff=)` (`:2513`, selection at `:2548`), with `_run_sit_batched(kind=)` (`:2352`).
  - `run_pre_merge_gates` passes the diff (`:4488`), and a not-applicable leg is named in the reason (`:4552`).
  - `_log_sit_outcome` writes `scope` / `not_applicable`, and `sit_report_aggregate` prints them.
  - `config/repos.yaml` documents `sit_core_files` (not set).
- **D4, `orchestrator.py`:**
  - `full_gate_state_file` (`:4660`) and `_full_gate_refusal` (`:4666`).
  - `_full_gate_sit` (`:4684`): the full `run_sit_post_merge` judged by `_classify_gate_failure`, the GATE-SIT-2 oracle consulted, compared against the previous full-gate's SIT failures.
  - `_full_gate_unit` (`:4726`): the full suite as an `unit-baseline` leg, against the content-keyed baseline, else the ancestor, else the previous full-gate, else nothing. A new file is confirmed alone, so a flake is not new.
  - `_full_gate_previous` (`:4801`), `_full_gate_dry_run` (`:4813`) and `full_gate` (`:4867`).
  - The CLI: `REPO_CMDS` (`:5925`), the parser (`:6024`) and the dispatch (`:6146`). `--log-file` and `--trigger` are the daemon's, hidden from `--help`.
- **D4, `queue_daemon.py`:**
  - `full_gate_schedule` / `full_gate_summary` / `full_gate_line` (`:438` / `:459` / `:475`).
  - `_full_gate_step` (`:1280`) is called at `:1121`, between routes, and at `:1111`, in the paused branch, where it only says the window was missed.
  - `_run_full_gate` (`:1323`): stdout to `logs/<log_subdir>/full-gate-<ts>.log`, a 6 h backstop, `full_gate_running` recorded and `current_batch` left empty.
  - The persisted `full_gate_nightly` / `full_gate_running` keys are in `DAEMON_OWNED_KEYS` (`:66`).
  - `status` line 1 and JSON `full_gate` (`:1502-1509`).
- **D4, elsewhere:**
  - `qstat.sh:59-82` adds the `🌙 FULL-GATE` lines.
  - `config/repos.yaml` sets clinical-mp `full_gate_nightly: "02:30"`.

## §2 Predicates

| # | RED on `4913a4f` | GREEN at `0adf02a` | Negative control | Verdict |
|---|---|---|---|---|
| **P1** (D1) | `briefs/x.md` + `briefs/x.handback.md` ran build 1, SIT 1, unit 1. `branch_changed_paths`, the truncation and the subdir tests fail on the missing symbol. The route lane, meta-fire lane and parallel worker each invoked every leg | PASS `briefs-only diff (2 files: briefs/x.handback.md, briefs/x.md) — build/SIT/unit not run (D-S7CORE29-02)`, **0 leg invocations**. Through `_run_batch_inner` it merged the queued brief + handback, and FINAL STATUS names the skip. Meta-fire `gate_outcome` PASS → `_self_mod_auto_merge` ff'd main. `_gate_parallel_branch` PASS, 0 legs | + `src/a.ts` → build/SIT/unit 1/1/1. A rename `briefs/old.md → docs/old.md`, and `docs/readme.md → briefs/readme.md` (both paths named) → gated. A deleted `docs/readme.md` → gated. A root `x.handback.md` → gated. Empty diff (`()`) → gated. Diff not computable → gated, said. `yorsie/briefs` subdir: top-level `briefs/` is code. A code route through the route lane and through a parallel worker → legs run (all green on HEAD too) | **PASS** |
| **P2** (D2) | Measured at A, the lookup at B **re-measured** (keyed by SHA). The v1 file was read as v1. The migration, twin and content-key tests fail | Measured at A → B **hits** with no baseline run: `cache hit by content: measured at <A7>, merge base <B7>, non-briefs tree identical`, ref `merge-base <B7> (measured at <A7>)`. `run_unit_gate` on a route off B reads it. A v1 file with A + an unreachable SHA → v2 with the content key, **one** `… entry … dropped — commit deadbee is unreachable` line, version 2 on disk, and B then hits. Two v1 twins → one entry with flaky counts summed (2 + 1 = 3) | C (a `src/` change) → **miss**, measured. A mode change → a new key. An unreachable commit → no key. An unjudged entry → miss, re-measured (as on HEAD). A sibling is never borrowed as an ancestor; a parent is, distance 1. The `flaky` report migrates in memory and writes nothing | **PASS** |
| **P3** (D3) | `run_sit_post_merge` has no `diff`, so every case fails. A verdict through `run_pre_merge_gates` ran the whole suite | Affected `{f2}` + branch adds `f4`, core unset → one batch handed **exactly f2, f4**. `sit[related 2/5 files] 2 files/4 tests in 1 batches`, logged `equals the enumerated related set: 2 of 5 files / 4 tests`, and the SIT log has `scope: related 2/5`. Empty union → `sit: no SIT file relates to this diff (3 changed files)`, PASS, **no SIT invocation**, never zero-collection. The verdict reads `unit green on route; sit: no SIT file …`. Enumeration exit 1, or exit 0 with `unhandled errors during test collection` → the **full** suite (all 5 handed), `sit[full 5 files]`, reason logged. Unknown diff / SIT-config change → full. The core set joins, an unknown core name is said. A related batch is judged as `sit-batch-related` | GATE-SIT-2 on the related set: F2 red in the batch and red alone → FAIL(product), `sit_verdict_violations == []`. Green alone → PASS `batch-contamination`, `[]`. No diff → the whole suite, no mode, as before | **PASS** |
| **P4** (D4) | No `full_gate`, `full_gate_state_file` or `FULL_GATE_CLOCK`: all fail or error | A held lock (live pid) → **exit 2**, one stderr line `⛔ full-gate cost-repo: refused — fire lock held — cost-repo 300-x (pid …)`, nothing run, no state. A daemon-reported live route → 2. Idle → list + 3 batches + unit. The state has sha, content_key, SIT/unit collections, failing files, `new`, the clock judgement and the duration → **exit 0**. Its own lock is held during the run (pid, `full-gate-…`, route_worktree) and released after, and its worktree removed. A unit file outside the baseline, failing alone → **exit 1** `NEW FAILURES`, `unit.new == [UB]`. A SIT failure confirmed alone → new (exit 1), and the same failure next run → not new (exit 0). `--dry-run` → plan printed, only the list ran, in the checkout, no lock, no state. **Daemon:** 02:29 no / 02:30 idle+running → runs, 02:31 / 23:59 no, the next day runs. Paused → not run, one `due at 02:30, not run now — daemon paused (operator)` line, the next day `SKIPPED 2026-10-17 …`. Busy at 02:30 → one deferral line, then it runs at 03:05 when idle. A restart the same day → not again. `run_loop` → full gate, **then** the queued route. The real runner → a log file with header, output and `Exit: 1`; `current_batch` stays None | A dead-pid lock → runs, exit 0. A failure in the baseline → exit 0. A new file that passes alone → flaky, exit 0. An unscheduled repo / `150` (unquoted) → never run | **PASS** |
| **P5** readers | qstat prints no full-gate line. `status` line 1 has no segment and no JSON `full_gate`. sit:report has no scope. `find_missing_gate_logs` fails on HEAD only through the fixture (`FULL_GATE_CLOCK`) | `find_missing_gate_logs` → `[]` for a daemon-recorded briefs-only route. qstat → `🌙 FULL-GATE clinical-mp \| ✅ PASS \| 2026-10-17T02:41 \| sha a1b2c3d \| nightly`, plus `never run \| nightly 03:00` and `running now`. `status` line 1 → `… \| full-gate clinical-mp: NEW FAILURES 2026-10-17T02:58 a1b2c3d (nightly 02:30) \| full-gate orchestrator: never run (nightly 04:00)`, and JSON `full_gate`. `verify` shows the briefs-only gate line and FINAL STATUS. sit:report → `sit[related 2/113 files]`, the not-applicable sentence and the counts. handback-scan over a toni log quoting every new line → 0 violations. `route_phase` → `merge` | The log removed → `log-missing` (control). `verify`, handback-scan and `route_phase` are line-agnostic: green on HEAD too, so they needed no change | **PASS** |

**RED run.** The 65 new tests ran against `4913a4f`'s files (`git archive 4913a4f`, plus `tests/test_gate_cost.py`): **48 failed, 6 errors, 11 passed.** The 11 are:
- the negative controls that need no new code: a code file / rename out / deleted file / root handback run every leg; a code route through the route lane and through a parallel worker; a `src/` change misses;
- the `flaky` report writing nothing (HEAD reads v1 natively);
- the three line-agnostic readers (`verify`, handback-scan, `route_phase`).

**GREEN:** 65/65.

### P6: live, read-only

**(a) The dry-run against the real clinical-mp checkout.** It was on `main`, clean, so the suite was enumerated in place and no worktree was made. Afterwards `git status --porcelain` was 0 lines and `git worktree list` still 30.
```
$ python3 orchestrator.py full-gate --repo clinical-mp --dry-run
full-gate --dry-run clinical-mp @ main = fc84bb8ba0a6 (content key fc7a531076e9351027b4f3d1c22810bc)
  lock: free — a real run would start now
  SIT: sit[full 115 files] — 115 files / 423 tests enumerated in the project checkout /home/gkassa/spectricom-clinical-mp (clean, at fc84bb8); 12 batches of ≤10, 90s pause between, 600s per batch
  unit: `npm test` — the full suite, budget 1800s; baseline: no content-keyed entry — the nearest measured ancestor, else the previous full-gate
  writes: /tmp/orch-fire-20261016-183718/logs/clinical-mp/full-gate-<ts>.log, /tmp/orch-fire-20261016-183718/state/full-gate-clinical-mp.json — nothing run, nothing written (--dry-run)
exit=0        real 2m4.345s
```
`lock: free` is the worktree's own `state/` (§1.11). The lock check against the live state:

**(b) The same refusal check and an in-memory cache migration, pointed at the live `~/spectricom-orchestrator`.** This is read-only. The live cache's sha256 is the same before and after (`aca1ba76d6d02f02`):
```
refusal against the live state: the queue daemon (pid 71536) reports a route live — 279a-orch-gate-cost-1.md since 2026-10-16T18:37:11.934373
live cache on disk: version 1 entries 217
♻️  Unit baseline cache migrated v1 → v2: 192 entries keyed by content (non-briefs tree), 25 merged into a content twin, 0 dropped
in-memory v2 entries: 192
content hit for clinical-mp main fc84bb8 -> None
```

**(c) `branch_changed_paths` on the real clinical-mp repo:**
```
route 268 (handback-only), first parent -> it: branch_changed_paths(clinical-mp, 78a128d6, 62a5e6be) -> 2 path(s), briefs-only=True
    briefs/268-one-owner-1.handback.md
    briefs/268-one-owner-1.md
route 268r, its route's merge base -> its tip: branch_changed_paths(clinical-mp, 62a5e6be, 76f37cde) -> 32 path(s), briefs-only=False
    briefs/268r-one-owner-1r.handback.md
    briefs/268r-one-owner-1r.md
    sit/integration/care-gap-active-and-lists.integration.test.ts
    sit/integration/job-idempotence.integration.test.ts
    sit/integration/one-owner.integration.test.tsx
    sit/integration/pro-instrument.integration.test.tsx
    src/components/encounter/sidebar/CopilotWidget.practice-scope.test.tsx
    src/components/encounter/sidebar/CopilotWidget.pro.test.tsx
    src/components/encounter/sidebar/CopilotWidget.tsx
    src/hooks/useEncounterCopilot.ts
    src/hooks/usePrevisitGapFlags.ts
    src/lib/__tests__/one-owner-agreement.test.tsx
    … +20 more
route 268r tip, first parent -> it (the orchestrator's own brief commit): branch_changed_paths(clinical-mp, 2808bf70, 76f37cde) -> 1 path(s), briefs-only=True
    briefs/268r-one-owner-1r.md
```
See §1.1 for the third line.

## §3 Gates

| Gate | Result |
|---|---|
| `pytest -q tests/` at merge-base `4913a4f`, in this worktree before any edit | **1206 passed** in 69.40 s |
| `pytest -q tests/` at `0adf02a` | **1271 passed** in 69.44 s. 0 failed, 0 skipped, 0 deleted; 65 new |
| Targeted: `tests/test_gate_cost.py` | RED 48 failed / 6 errors / 11 passed on `4913a4f`; GREEN 65 passed |
| The orchestrator's self-mod gate (`build` = `pytest -q tests/` on this worktree, then the unit baseline gate, then `_self_mod_auto_merge`) | The orchestrator runs it after this executor exits. It runs `4913a4f`'s gate code, which is in memory, on this suite: the suite above, green. This diff is code, so D1 would not skip it either |
| Daemon, `queue/`, `queue-state.json`, `state/`, the clinical-mp tree | Not touched; the daemon was not signalled. Only read: `queue-state.json` and `state/` (P6 b), `sit-archive/unit-baseline-cache.json` (same sha256 before and after), clinical-mp git, and `npx vitest list` / `--help` in its checkout (status clean before and after) |

## THE CONSEQUENCE (D-S7CORE13-03)

1. **After the merge, before the daemon restarts.** Every fire's `orchestrator.py` loads the new code.
   - **A route whose diff is briefs-only merges with no gate.** Routes 267/268 would have taken seconds instead of 46/45 min.
   - **A clinical-mp code route runs its related SIT files.** Its time is ≈2 min of enumeration + its batches, against ≈25 min. Or "not applicable", or the full suite with the reason.
   - **The first unit gate migrates the baseline cache to v2** (25 content twins collapse). After that, a merge base that differs from a measured commit only by briefs and handbacks reuses that measurement and saves 8-9 min.
   - `full-gate` works on demand.
2. **After the restart.**
   - The daemon runs `full-gate --repo clinical-mp` once a night from 02:30, when idle and running. That is ≈45 min: 12 SIT batches with 90 s pauses, plus the ≈14-min unit suite.
   - Routes wait for it, and it waits for routes.
   - `status` and `qstat.sh` show the last result.
   - A full gate that finds something new exits 1. The daemon logs `🌙 full-gate clinical-mp: NEW FAILURES (exit 1) — sha …`. Nothing is paused or blocked by it: it informs, it never merges.
3. **Unchanged:**
   - the build gate on every code diff;
   - the full unit suite per merge (with D2's baseline);
   - every verdict rule (F-20, GATE-SIT-2, GATE-CLOCK-1, BASELINE-TRUST-1, CONFIG-TRUTH-1);
   - the `DISABLE_*` escapes;
   - the CODE-GUARD, the handback guard, prefire, admission, the fire lock, timeout/hold;
   - the daemon's pause/resume semantics.
