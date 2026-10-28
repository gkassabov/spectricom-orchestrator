# 341a1 RE-FIRE · ORCH-TEST-EFFICIENCY-1 — handback

**Result:** the three `341a1` commits are cherry-picked with no conflicts. F1 and F2 are done. The full
`pytest -q tests/` passes: **1889 passed**. `py_compile` is OK. No daemon restart is needed, and
`queue_daemon.py` is untouched.

**⚠ Read first: F2 is option (b), but in the shape C actually has, not the brief's literal text.** The brief's entry
`'_unit_baseline_related': {'baseline-trust'}` crashes the guard, because C is keyed by control, not by speaker. The
test edit is 2 lines: the C entry, plus the one line that reads C. See F2 below. If you read that as STOP (m),
revert `tests/test_control_verdict_lines.py` in the F1/F2 commit. The two old lines are pasted under "Rule #8".

## A0 · First step
1. **HEAD and source branch.** `git merge-base --is-ancestor 4160d6b HEAD` → yes. Commits in
   `main..orch-orch-341a1-orch-test-efficiency-1`:
   ```
   330e191 handback: 341a1-orch-test-efficiency-1 — all three briefs done and committed, no STOP, no daemon restart
   e4a1dc4 feat(orch): a `## Re-gate of: <branch> <sha>` file re-runs the gates on an environment-blocked route, …
   d3d275c feat(orch): the per-route unit gate runs the files related to the diff; …
   b7c7efb feat(orch): SIT enumeration runs during the build, and the nightly full gate reuses a measured unit run …
   ```
2. **Cherry-pick.** `git cherry-pick b7c7efb d3d275c e4a1dc4` had no conflicts. The new SHAs are `e7984c8`,
   `c1c2bdd` and `18ca74a`, with diffs identical to the originals. D-S7CORE36-02 did not come into play.
3. **Full suite on the cherry-picked tree:** exactly the two expected reds.
   ```
   FAILED tests/test_control_verdict_lines.py::test_source_guard_C_is_pinned - a...
   FAILED tests/test_sit_rate_limit.py::TestSitBatching::test_batch_size_and_pause_are_configuration_not_literals
   2 failed, 1887 passed in 74.27s (0:01:14)
   ```
4. **C and the speaker map.**
   - **C** (`tests/test_control_verdict_lines.py:39-52` before this route) maps **control → its one speaker
     function**:
     ```python
     # C, and the one function that speaks for each member.
     C = {
         "handback-guard": "_handback_hold",
         "bg-wait-ceiling": "fire_toni",
         "clock-plausibility": "_judge_leg",
         "sit-isolation": "_sit_isolate",
         "unit-confirm": "_unit_confirm_new_files",
         "executor-exit": "_executor_exit_hold",
         "baseline-trust": "_unit_baseline_measure_or_reuse",
         "guards": "_toni_guards_apply",
     }
     ```
   - **How `_control_violations` builds the speaker map.** It looks only at the top-level functions of
     `orchestrator.py`. For each one, `_shield_names` walks its AST and collects the `<name>` from every string
     constant, or f-string head, that starts with `🛡 <name>:`. `speakers` is every function that has at least one
     name. `expected = {fn: {c} for c, fn in C.items()}`. The test fails unless `speakers == expected`.
   - **`_unit_baseline_related`'s 🛡 line** (`orchestrator.py`, the full-cache-hit branch, new in `d3d275c`):
     ```python
     log.info(f'🛡 baseline-trust: CLEAN — cache hit at {base_sha[:7]}, measured '
              f'{str(hit.get("measured_at") or "?")[:19]} on a clock judged plausible (cache entry "clock": '
              f'"{hit["clock"]}"), restricted to the related files')
     ```
   - **`_unit_baseline_measure_or_reuse`'s three 🛡 lines** (unchanged, inline `log.*` calls, no helper):
     ```python
     log.info(f'🛡 baseline-trust: CLEAN — cache hit at {base_sha[:7]}, measured {measured_at} on a clock '
              f'judged plausible (cache entry "clock": "{hit["clock"]}")')
     log.error(f"🛡 baseline-trust: BLOCKED — baseline-clock-implausible: {note} — never PASS, "
               f"never FAIL(product)")
     log.info(f"🛡 baseline-trust: CLEAN — unit-baseline at {base_sha[:7]} {trust}")
     ```
   - **The violation:** `🛡 speakers {…, '_unit_baseline_measure_or_reuse': {'baseline-trust'},
     '_unit_baseline_related': {'baseline-trust'}, …} != C {…, '_unit_baseline_measure_or_reuse':
     {'baseline-trust'}, …}`

## F1 · No forbidden literal (as built)
`orchestrator.py` had **four** `vitest list` literals, all in comments or docstrings and all from the cherry-picks
(`git log -S` → `e7984c8`, `c1c2bdd`). The test failure showed only the first one. I reworded all four. Code and
behaviour are unchanged.

| where | old | new |
|---|---|---|
| `_sit_tree_state` docstring | what `` `vitest list --changed` `` reads | what the repo's `` `sit_list_cmd` `` reads with `` `--changed` `` |
| `_SitEnumJob.discard` comment | never leave a `` `vitest list` `` running | never leave a `` `sit_list_cmd` `` listing running |
| `_unit_list_cmd` docstring | (`` `npx vitest list <config args>` ``, None) | (the vitest `` `list` `` command with the run's config args, None) |
| `_unit_listing` docstring | from a `` `vitest list --filesOnly` `` run | from a vitest `` `list --filesOnly` `` run |

Two docstrings were re-wrapped to stay within 120 columns.

Grep of `orchestrator.py` after F1: `vitest list` 0, `vitest.sit.config` 0, `sleep(90` 0, `range(0, 19` 0.
`tests/test_sit_rate_limit.py` is not edited.

## F2 · One registered speaker per control line (as built: option (b), adapted to C's shape)
**Why not (a).** No helper emits `🛡 baseline-trust:`. All three lines in `_unit_baseline_measure_or_reuse` are
inline `log.*` calls. The only existing speaker I could call is `_unit_baseline_measure_or_reuse` itself, from
`_unit_baseline_related`'s full-cache-hit branch. That would not be a "no behaviour change" call:
- It redoes the content-key and cache lookup. On any miss, for example `git ls-tree` failing the second time, it
  **measures the full suite** at the base.
- It adds a second `♻️ CACHE HIT` line.
- It drops "restricted to the related files" from the 🛡 text.

A new shared helper would itself become the speaker, and C would have to name it instead. That is a larger test
edit. Changing the string so the guard does not see it would defeat the guard, so I ruled it out.

**Why (b) cannot be literal.** C is `{control: speaker}`, not `{speaker: {controls}}`. With the brief's entry, the
reader line `expected = {fn: {c} for c, fn in C.items()}` builds `{{'baseline-trust'}: {'_unit_baseline_related'}}`,
which fails with `TypeError: unhashable type: 'set'`. I checked this by running it. A dict also cannot hold a second
`"baseline-trust"` key. So the only way to register a second speaker is for the `baseline-trust` value to name two
functions, and for the one reader line to accept that.

**As built.**
- C's `baseline-trust` value is now the tuple `("_unit_baseline_measure_or_reuse", "_unit_baseline_related")`.
- `expected` expands a tuple into one entry per speaker. A plain string reads as before.
- Every assertion is unchanged: `test_source_guard_C_is_pinned` still asserts `_control_violations(...) == []`, and
  the four `test_source_guard_turns_red` cases are untouched and pass.

**Guard checked after the edit:**
- A third `baseline-trust` speaker (`def _x` emitting `🛡 baseline-trust: CLEAN`) → `🛡 speakers … != C`.
- `_unit_baseline_related` speaking a second control → `🛡 speakers … != C`.

`orchestrator.py` is not touched by F2.

### Rule #8 (George go 2026-10-24 12:10 + RE-CHECK class (i)): `tests/test_control_verdict_lines.py`, old → new
```diff
     # BASELINE-TRUST-1 (route 67): a seventh, one line per baseline the unit gate needs
-    "baseline-trust": "_unit_baseline_measure_or_reuse",
+    # ORCH-UNIT-RELATED-1 (route 341a1): a second speaker, the related-files baseline's restricted cache hit
+    "baseline-trust": ("_unit_baseline_measure_or_reuse", "_unit_baseline_related"),
```
```diff
-    expected = {fn: {c} for c, fn in C.items()}
+    expected = {fn: {c} for c, fns in C.items() for fn in ((fns,) if isinstance(fns, str) else fns)}
```
**This goes beyond the brief's literal "the C set entry only, nothing else":** the second hunk changes the line that
reads C. It changes no assertion. The comment above C ("the one function that speaks for each member") is left as
it was, and is now slightly loose for `baseline-trust`.

## F3 · Nothing else moves
- The three cherry-picked commits are unchanged: no conflicts.
- The F1/F2 commit touches only `orchestrator.py` (4 comment/docstring rewordings plus re-wraps) and
  `tests/test_control_verdict_lines.py` (the 2 hunks above).
- The handback commit `330e191` was **not** cherry-picked, as the brief asks. Its one-line `orchestrator.py` change
  is therefore not here: the module usage line `full-gate --repo <name> --requested-by <name> …`. See found-and-left.

## A3 · Predicates
**PR1 RED.** `pytest -q tests/test_sit_rate_limit.py tests/test_control_verdict_lines.py` on a `git archive` copy of
the cherry-picked HEAD `18ca74a`, without F1/F2:
```
E           AssertionError: clinical/environment literal in source: vitest list
E       assert ["🛡 speakers ... {'guards'}}"] == []
FAILED tests/test_sit_rate_limit.py::TestSitBatching::test_batch_size_and_pause_are_configuration_not_literals
FAILED tests/test_control_verdict_lines.py::test_source_guard_C_is_pinned - a...
2 failed, 88 passed in 6.93s
```
**PR1 GREEN, with F1/F2:** `90 passed in 0.88s`.

**PR2, the full `pytest -q tests/` on the final tree:** `1889 passed in 66.37s (0:01:06)`.

**The original brief's predicate files, re-run:**

| file | result |
|---|---|
| `tests/test_sit_enum_parallel.py` | 9 passed |
| `tests/test_fullgate_reuse.py` | 15 passed |
| `tests/test_unit_related.py` | 35 passed |
| `tests/test_regate_gates_only.py` | 12 passed |
| all four together | 71 passed |

**Gates:** the full `pytest -q tests/` gives 1889 passed, and `python3 -m py_compile orchestrator.py` is OK.

**Test-scope note.** The header says `Test scope: targeted`, while A0.3, PR2 and §6 order the full `pytest -q tests/`
by name. I followed the explicit steps and ran it three times: A0.3, PR2, and the final tree. Each run took about
70 s.

**Venv.** The worktree has no `venv/`, so every `venv/bin/python` above was run as
`~/spectricom-orchestrator/venv/bin/python` with `-p no:cacheprovider`.

## STOP checks
- **(k)** No conflicts.
- **(l)** No red after F1/F2: 1889 passed.
- **(m)** The test edit goes beyond the literal F2 (b) text by the one reader line. The reasons are above, and it is
  flagged at the top of this handback. No other test is edited.
- **Original brief (a)–(d).** Unchanged by this route: the cherry-picks are byte-identical, and `queue_daemon.py`
  is untouched.

## R-items (carried from `330e191`'s handback)
1. **1a, red build.** A red build waits for the worker to finish, which is at most its two listing runs, so no
   listing outlives the route. If clinical-mp's build writes untracked, non-ignored files, every route falls back to
   serial with `re-run serially — the tree moved`. Check the first live `⏩` lines.
2. **1b, the reused leg is not compared with itself.** It is compared with the baseline chain minus the reused
   entry. Comparing it with its own entry is a one-line `hit` lookup change, if George wants that.
3. **1b, what counts as reusable.** A landed route-branch entry (`measured_as: route-branch`) is a reusable
   full-suite measurement. This is the 03:10/03:11 case.
4. **1c, `--requested-by`.** `full-gate` without `--requested-by` is refused with exit 2, except `--dry-run`. No
   script in this repo omits it, and the daemon passes `--trigger nightly`.
5. **2, vitest filters.** Positional filters are substrings: `a.test.ts` also pulls in `a.test.tsx`. That is more
   testing, never less.
6. **2, scope.** Related selection exists only for `npm test` → `vitest run [--config X]`, which today means
   clinical-mp only. The other repos run the full suite with one `🎯 … related selection not available` line.
7. **2, the counter.** It counts routes whose branch leg measured. A route that breaks `scripts.test` runs the full
   suite without resetting the counter.
8. **2, the empty set.** A docs-only or tests-only diff that relates to no unit file runs no unit leg, and the
   verdict says so.
9. **2, `sit_core_files`.** It is a unit trigger, but it is not set for clinical-mp, so it has no effect today.
10. **3, the meta-fire lane.** Orchestrator routes record no gate note, so a re-gate of one is refused, typed. A
    Toni re-fire is still the way for those.
11. **3, the old branch.** It is left in place after a re-gate. It is merged, so `orchestrator.py branches clean`
    removes it.
12. **3, the queue.** A refused re-gate exits 2. The daemon moves it to `queue/failed/` and, with
    `stop_on_failure`, pauses the queue.
13. **No longer applies.** The original R13 ("suites that exercise `run_pre_merge_gates`/`run_batch` not run
    locally") is moot: the full `tests/` ran here, 1889 passed.
14. **(new) F2 shape.** C now lets one control have more than one speaker, but only where a tuple names them. A
    future second speaker for any control needs the same explicit tuple entry. Nothing is inferred.

## Found-and-left
- **The `full-gate` usage line.** The module usage line in `orchestrator.py` still reads
  `full-gate --repo <name> [--ref main] [--dry-run]`, without `--requested-by`. The fix was in the original
  handback commit `330e191`, which this re-fire does not cherry-pick, and the line is outside F1/F2's allowed edits.
  It is a one-line doc fix for a later route.
- **`_unit_list_cmd` still builds the vitest list command from tokens**
  (`" ".join(["npx", "vitest", "list", …])`). That is not a literal, so the guard passes, but it is a
  vitest-specific command in source, which the guard is meant to keep in `repos.yaml` (`sit_list_cmd`). It came
  from `d3d275c`, which was approved as built, and is left alone.
- **(carried) `_unit_repo_timeout`'s warning ends in "s".** For `unit_full_every` and `full_gate_reuse_max_h` it
  reads "… using 5s" or "… using 24s". Cosmetic.
