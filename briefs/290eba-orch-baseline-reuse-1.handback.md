# filename: briefs/290eba-orch-baseline-reuse-1.handback.md
# Handback — 290eba · ORCH-BASELINE-REUSE-1 (S7-CORE-31 · SCP_Kanban row 344)

**Outcome:** done. When a route lands, its own unit branch run is now stored as the cached baseline of the commit it landed as, if every R2 condition holds. Otherwise nothing is stored and one line says which condition failed. No gate verdict, route status, cache version or existing entry changed (STOP b/c not hit). The only files touched are `orchestrator.py`, the new `tests/test_baseline_reuse_1.py`, and this handback (STOP a not hit). No daemon restart, no write to the live cache (STOP d not hit).

**Test scope: targeted.** I ran only the brief's six files and the 13 other test files that call a changed function. I did not run the full suite.

---

## §0 · Premises, as built (L-30)

The executor ran from the daemon: `queue_daemon.py` pid 3128 → `orchestrator.py run …/queue/290eba-orch-baseline-reuse-1.md` pid 1167481 → this session. It ran in worktree `/tmp/orch-fire-20261018-101542` on branch `orch-orch-290eba-orch-baseline-reuse-1`.

```
$ git log --oneline 81ef432..HEAD
(empty — HEAD is 81ef432; nothing merged since, so no named function moved)
```

Premise line numbers checked at `81ef432` (`git show 81ef432:orchestrator.py | grep -n …`). All hold:

```
350:UNIT_BASELINE_CACHE_VERSION = 2
367:ISOLATED_DEPS = False
533:class GateVerdict:                       (decorator at :532)
1684:def _land_from_route_worktree(...)        (… :1726 return None)
2857:class UnitGateOutcome:
3206:            links = _link_unit_deps(repo_path, wt, isolated=ISOLATED_DEPS)
3339:def _unit_content_key(...)
3444:def _unit_cache_key(...)
3449:def _unit_cache_entry_matches(...)
3458:def _unit_cache_lookup(...)
3470:def _unit_cache_store(...)
3484:        return   # BASELINE-TRUST-1 …      (under `if run.clock is not None:` at :3483)
3494:    flaky = ({k: prior[k] for k in ("flaky_files", "flaky_seen") if k in prior}
3510:        "clock": "plausible",
3522:def _unit_cache_record_flakes(...)
3937:        log.info(f"♻️  Unit baseline: CACHE HIT for …")
3973:        _unit_cache_store(archive, repo_name, base_sha, …)        ← writer 1 (the merge base)
4009:def run_unit_gate(...)
4049:    branch_run = _run_unit_suite(test_cmd, repo_path, label)
4052:    branch_run.clock = _judge_leg("unit-branch", …)
4078:    branch_green = …                                            (fast path → :4089)
4093:    baseline_run, baseline_source, baseline_note = _unit_baseline_measure_or_reuse(
4140:    new_files = tuple(sorted(set(branch_run.failing_files) - set(baseline_run.failing_files)))
4175:            _unit_cache_record_flakes(archive_path or SIT_ARCHIVE_DIR, ACTIVE_REPO_NAME, base_sha,
4195:    verdict = ("equal to" if … else "below")                   (PASS → :4213)
4475:def run_pre_merge_gates(...)
4893:        _unit_cache_store(archive, ACTIVE_REPO_NAME, sha, …)     ← writer 2 (full gate, `hit is None`)
5274:                    merged = _self_mod_auto_merge(ORCH_DIR, meta_branch, …)   (out of scope)
5458:                subprocess.run("git add -A", shell=True, cwd=str(proj), …)
5506:                        verdict = run_pre_merge_gates(proj, branch_name)
5535:                        route_tip = _git_read("git rev-parse HEAD", proj) or None
5547:                        route_tip = subprocess.run(
5561:                            post_merge_tip = subprocess.run(
5565:                            if post_merge_tip == pre_merge_tip and toni_commits > 0:
5767:            if merge_branch(br) and RUN_PLAYWRIGHT:                         (out of scope)
```

The measured spec reference, re-read from the live logs:

```
$ grep -h "Unit gate branch run\|Merged \|cache MISS\|Unit gate baseline run" logs/clinical-mp/orch-290ea-…-052413.log logs/clinical-mp/orch-290eaa-…-061034.log
06:00:44 🧪 Unit gate branch run — orch-mp-290ea-member-write-guard-1r: 1311 files/13326 tests, 5 failed, 13309 passed, 8 skipped, 4 todo in 552.4s
06:00:45 🧬 Unit baseline: cache MISS for b7ec916 — measuring (budget 1800s)
06:10:04 🧬 Unit gate baseline run — merge-base b7ec916: 1309 files/13297 tests, 4 failed, … in 558.9s
06:10:04 🔀 Merged orch-mp-290ea-member-write-guard-1r → main (b7ec916 → 94ef57f)
06:49:15 🧪 Unit gate branch run — orch-mp-290eaa-partner-pdf-k3-1r: 1311 files/13326 tests, 4 failed, … in 554.1s
06:49:15 🧬 Unit baseline: cache MISS for 94ef57f — measuring (budget 1800s)
06:58:32 🧬 Unit gate baseline run — merge-base 94ef57f: 1311 files/13326 tests, 4 failed, … in 556.2s
```

### Find 1 · What can change the gated tree between the branch run and the landing

There is nothing in the code between them that commits. The route lane runs `git add -A` and commits at `:5458-5491` (HEAD numbering), before the gate at `:5506`. After the gate, nothing commits again. The landing merges the branch ref: `:5544-5583`, or `_land_from_route_worktree` `:1684-1726`.

So the risk is the working tree, not the commit. The build gate (`run_build_gate`, as-built `:4627`) and the SIT gate (`run_sit_post_merge`, `:4637`) run in the same checkout before the unit leg (`:4676`). Any **un-ignored** file they leave is in the tree the branch leg measures, but never in the commit that lands.

- **On clinical-mp, at rest, that set is empty.** Its build and SIT outputs are git-ignored: `.gitignore:11 dist`, `:14 tsconfig.tsbuildinfo`, `:16 package-lock.json`, `:34 sit-reports/`. Its checkout after its latest gated routes (40d6b9a0 290eb1, 56b0d46c 290eb0) was clean:
  ```
  $ git -C ~/spectricom-clinical-mp --no-optional-locks status --porcelain --untracked-files=all | wc -l
  0
  ```
- **On the lane harness, it is also empty.** This is `TestFind1…::test_the_route_lane_commits_everything_before_the_gate`, with `git status` recorded at the moment the branch leg is invoked:
  ```
  Find 1 · lane harness, at the branch leg: HEAD e6afc1f; git status --porcelain --untracked-files=all → ''; landed as e6afc1f; legs ['build', 'sit', 'branch', 'baseline']
  ```
- The same `git status` is now checked on every gate, before the branch leg (R2e). A leg that leaves an un-ignored artefact makes the gate record it, so nothing is stored. Test `test_an_untracked_non_briefs_file_at_the_branch_run` shows this: `?? coverage-summary.txt` → `(e) … uncommitted outside briefs/ before it: coverage-summary.txt`.
- **Not covered:** git-ignored files such as `dist/`, `tsconfig.tsbuildinfo` and `node_modules/.vite`. They are present at the branch leg but are not in a baseline worktree. Every branch-vs-baseline comparison already has this asymmetry, and the stored entry inherits it (see found-and-left).

### Find 2 · Linked vs `ISOLATED_DEPS`

**Linked (the default, and every live repo today): no difference.** The branch leg and a baseline leg on the same tree use the same dependency trees:

- The branch leg runs in the gated checkout `proj` (`:5253 proj = worktree or route_wt or PROJECT_ROOT`).
- Single-stream (clinical-mp, orchestrator) uses PROJECT_ROOT's own `node_modules`. Parallel (yorsie, ai-foundation) uses links to PROJECT_ROOT's trees (`_create_route_worktree` `:1617`).
- A baseline leg links `repo_path`'s trees, i.e. `proj`'s (`:3206`), through `s.resolve()` (`:3061`). That reaches the same directories.

**Isolated (`## Isolated deps: true`): they can differ.** A baseline leg on T runs `npm ci` / pip from T's own manifests (`:3212` → `_install_unit_deps` `:3095`). The branch leg measures:

- **single-stream:** PROJECT_ROOT's real trees, whatever state they are in (nothing is built for it);
- **parallel:** the trees the route worktree built at creation from `MERGE_TARGET`'s manifests (`:1613`, `:1623`), plus anything the executor installed.

A route that changed a manifest, or a checkout whose trees drifted from the lockfile, therefore measures something an isolated baseline leg on T would not. The stored entry matches what the next **linked** route's baseline leg would measure, because that leg links the same checkout trees. The cache key already ignores the deps mode, for all writers. I did not add an R2 condition, because R2 is closed. Only `queue/done/233-orch-prefire-runtime-1.md` has declared `Isolated deps: true`. This is listed in found-and-left for Gemma.

### Find 3 · Tests asserting a cache entry count after a passing route-lane merge

**None.** Every count or "exactly one" assertion on the cache comes from a direct gate call, never from a `_run_batch_inner` landing:

- `test_unit_baseline_gate.py:733`, `:1197`, `:1803` — `run_unit_gate` directly;
- `test_baseline_trust.py:165`, `:185` — `run_pre_merge_gates` via `gate.run()`;
- `test_config_truth.py:258` — `gate`;
- `test_gate_cost.py:430` — `_unit_baseline_measure_or_reuse`;
- `test_gate_clock.py:433` (`== {}`) — `gate.run()`.

The `lane` tests in `test_gate_cost.py` (`:304-338`) never read the cache. **The rule-#8 pre-authorisation was not used.**

---

## R1-R4 · As built (file:line, `orchestrator.py` after this change)

- **R3 plumbing**
  - `GateVerdict.unit` `:542` — additive, default None.
  - `UnitGateOutcome.branch_sha` / `branch_tree_why` `:2883-2884` — additive, default None.
  - `run_unit_gate` records T and the (e) check around the branch run (`:4128-4153`): HEAD before, `git --no-optional-locks status --porcelain --untracked-files=all -z` outside `briefs_subdir` before the leg, HEAD after it. `--no-optional-locks` means the check never takes the index lock.
  - The local `_finish` was moved up to `:4159-4161`. It stamps both fields on every outcome after the branch leg; the timeout, zero-collection and green fast-path returns now go through it too, with the same `_unit_done` call. No verdict reads either field.
  - `run_pre_merge_gates`' PASS return carries `unit=uo` (`:4703`).
  - The helper `_unit_cache_store_landed(repo_path, verdict, merged_sha, archive, route_tip=None)` is at `:3569-3631`. It takes `route_tip` as one extra keyword, for R2e's "T == the tip the landing merged".
  - It is called only after each in-scope landing succeeds:
    - route worktree, `:5644` — `merged` is the worktree's detached HEAD, i.e. the commit `_land_from_route_worktree` made;
    - checkout, `:5691` — `post_merge_tip`, inside the `else` of the tip-unchanged check, so never on the OBS-S6S17-02 path, a conflict or a not-landed route.
  - It is placed after `retire_batch_file` and `git branch -d`, so the retire-before-delete order `test_queue_retire` asserts is unchanged.
  - It never raises: any exception produces one `log.warning` NOT-cached line (`:3628-3630`) and stores nothing.
- **R2 conditions** (`:3588-3615`): one `if/elif` chain in the brief's order. The first condition that fails is named:
  - (a) `:3588`
  - (b) `:3591`, `:3593`
  - (c) `:3595`
  - (d) `:3598` flakes, `:3600` failing ⊄ baseline (for `not-needed` the baseline set is empty, and a green branch has no failing files)
  - (e) `:3603` the leg's tree was not a commit, `:3605` T ≠ the tip the landing merged
  - (f) `:3607` a key is unreadable, `:3609` the keys differ
  - (g) `:3612` a judged entry exists at the key. An unjudged one is superseded, which is the store's existing behaviour.
- **R1 entry**: written through the existing `_unit_cache_store` (`:3619`) with `sha` = T, `content_key` = the merged commit's key (equal to T's, by (f)), and `test_cmd` = the active repo's `test_cmd`. That is the value `run_unit_gate` read; it is re-read in the same process, not carried on the outcome.
  - The store has one additive kwarg, `landed_as` (`:3480`), which adds `"measured_as": "route-branch", "landed_as": <merged>` (`:3524`).
  - No version bump; no existing entry is rewritten. After the write, the helper looks the entry up again and only says "cached" if it is there.
- **R4 lines**
  - Stored (`:3626`): `♻️  Unit baseline: route branch run cached for <merged7> (gated tip <T7>, non-briefs tree identical) — <collection>; the next route off this tree reads it`
  - Not stored (`:3617`): `♻️  Unit baseline: route branch run NOT cached for <merged7> — <(a)…(g) reason>`
  - The next route's CACHE HIT line and note add ` (a route's branch run)` when `measured_as` is set (`:4011-4017`).
  - Spacing: two spaces after ♻️, matching every existing `♻️  Unit baseline:` line. The brief quoted it with one; grep for `route branch run`.
- **Unchanged:** every verdict; flaky bookkeeping (P2 shows the next route's flake landing on this entry through the existing `:4175` path, source `cache`); the clock guard; test_cmd invalidation; `_unit_cache_ancestor`; the full gate; the meta-fire and parallel lanes.

## Tests changed

**No existing test changed.** One new file, `tests/test_baseline_reuse_1.py`, with 23 tests. It reuses `test_gate_cost.py`'s `_repo` / `_activate` / `_toni_log` / `vitest` and the `lane` shape.

- It runs a real git repo through the real `_run_batch_inner`, with a real detached baseline worktree and both landing sites.
- Scripted: the executor, the suite commands, and the clock judgement per leg kind.
- Safety: `fire_toni` is stubbed in the fixture to fail the test if a route reaches it without a scripted executor, so no test can start a real executor. All caches are tmp archives.

## Predicates · RED → GREEN

RED was run on HEAD's code in a throwaway detached worktree at 81ef432 with only the new test file copied in. **RED: 17 failed, 6 passed. GREEN: 23 passed.**

All 17 RED failures fail for the intended reason: no entry (`KeyError` on the merged key, or `(line,) =` on `[]`), no line (`assert [] == ['♻️ …']`), or no helper (`AttributeError: … '_unit_cache_store_landed'`). The 6 that pass on HEAD are the controls that must hold before and after: the P2 test_cmd control, the four P4 no-landing cases, and the Find 1 observation.

| Predicate | Tests | HEAD | now |
|---|---|---|---|
| P1 (a) | fast-forward, 290ea shape 5 vs 4 → one entry at `key(REPO, ck(merged), TEST_CMD)`: `sha` T, `landed_as`, `measured_as`, `clock` plausible, `[UA, UB]`, and the stored line exactly once · route-worktree landing · green fast path → `failing_files []` | 3 F | 3 P |
| P2 (b) | next route: 0 baseline legs, `[cache]`, unit log `baseline_source == "cache"`, CACHE HIT says `(a route's branch run)`, its confirmed flake → `flaky_seen[UC].count == 1` on this entry · **control:** changed `test_cmd` → miss, 1 baseline leg, `[measured]` | 1 F + control P | 2 P |
| P3 (c) | true merge over a non-briefs `main` advance → no entry, one `(f)` line, next route `[measured]` · **control:** briefs-only advance (still a true merge) → stored | 2 F | 2 P |
| P4 (d) | FAIL(product) regression · BLOCKED clock-implausible (regression on an implausible branch leg) · BLOCKED baseline-unmeasurable · merge conflict → no entry, no line, main unmoved | 4 P (controls) | 4 P |
| P5 | (a) briefs-only, (a) ungated · (d) flake-only · (c) ancestor-cache · (e) untracked non-briefs file at the branch run · **control:** untracked under `briefs/` → stored · (e) HEAD moved during the leg · (b) implausible branch clock on a PASS · (g) judged entry already at the key → cache file **byte-identical** · direct call that raises → one warning, nothing written · `_unit_cache_store` raising in a lane → route still PASSED and landed, one warning | 11 F | 11 P |
| Find 1 | porcelain empty and HEAD == landed at the branch leg; build and SIT run before it | P (observation) | P |

## Gates (targeted)

- `python3 -m pytest tests/test_baseline_reuse_1.py tests/test_gate_cost.py tests/test_baseline_trust.py tests/test_config_truth.py tests/test_unit_baseline_gate.py tests/test_merge_conflict.py` → **358 passed**. This is P6: the five existing files are unchanged.
- Every other test file that references a changed function (`run_unit_gate`, `run_pre_merge_gates`, `_unit_cache_store`, `_run_batch_inner`, `GateVerdict(` / `UnitGateOutcome` / `.unit_collection`): `test_control_scope test_control_verdict_lines test_gate_clock test_gate_collection test_handback_guard test_orch_lane test_queue_retire test_route_ref_integrity test_sit_isolation_attributed test_sit_rate_limit test_stale_base test_timeout_hold test_yorsie_safety` → **507 passed**.
- **Not run:**
  - `test_prefire.py` / `test_capacity.py` call only `run_batch` for prefire and capacity, which are unchanged. `test_prefire` is also the file whose RED run spawned a nested executor on 2026-10-17.
  - The full suite is left to the pre-merge gate.
- **Lint:** the repo has no linter config and none is installed (no ruff, flake8 or pyflakes). `python3 -m py_compile` passes on both changed files.

## Found-and-left

1. **The meta-fire lane and parallel lanes still re-measure.** `_self_mod_auto_merge` (call site `:5274` at HEAD) and `merge_branch` (`:5767`) never call the helper. That includes this route itself (meta-fire).
2. **Concurrent cache writers.** `_unit_cache_store`, `_unit_cache_record_flakes` and `_unit_cache_write` read, modify and write `unit-baseline-cache.json` with no lock. Two processes writing it at once can drop one's entry: e.g. a clinical-mp route landing while the nightly full gate (`:4893` at HEAD) or another repo's route stores. This was already true for every writer; this change adds one more write per landed route.
3. **Find 2:** under `ISOLATED_DEPS` the branch leg's dependency trees are not what an isolated baseline leg on T would build. This is not guarded, because R2 is closed. A possible (h) "not isolated" condition is Gemma's call.
4. **`measured_at`** on a route-branch entry is the store time (the landing), not when the branch leg finished. On clinical-mp that is the baseline leg plus landing later (about 9-10 min when the baseline is measured). `duration_s` is the branch leg's own time.
5. **Ignored-file asymmetry** (Find 1): git-ignored build and SIT output is present at a branch leg and absent in a baseline worktree. This predates the change; the stored entry inherits it.
6. **Pre-existing wording bug, not touched.** On a flake PASS whose count rose, `run_unit_gate`'s detail reads "5 failures, **below** the merge-base baseline of 4". `verdict = ("equal to" if == else "below")` at `:4195` at HEAD never says "above". Seen in this route's RED-run log.
7. **Housekeeping side effect.** The RED run used a throwaway worktree, removed afterwards with `git worktree remove` + `git worktree prune`. The prune also dropped the stale admin record of `/tmp/orch-fire-20261005-230041`, which `git worktree list` already showed as **prunable** because its directory was gone. Its branch `orch-orch-123b-orch-capacity-1` (507f015) is intact.

## Owner steps

- **No restart.** `queue_daemon.py` (pid 3128) spawns `orchestrator.py run` per route (`queue_daemon.py:1214-1218`), so the next route after this merge runs the new code.
- Check in the logs:
  - The first clinical-mp route **gated and landed by the new code** should print exactly one `♻️  Unit baseline: route branch run cached for …` or `… NOT cached for … — (x) …` line after its `🔀 Merged` line.
  - If it printed "cached", the route after it should read `CACHE HIT … (measured at <T7> (a route's branch run), …)` and `[cache]`.
  - Per the brief, a route gated by the old code still measures: 290ec, then 290f.
