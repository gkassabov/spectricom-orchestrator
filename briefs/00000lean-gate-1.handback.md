## STATUS: DONE

# ORCH-LEAN-GATE-1 (Kanban 728) — handback

Route branch `orch-orch-00000lean-gate-1`, base `main` 695f5c5 (= patch base; main did not move). One commit, re-land of the saved patch, no edits beyond it.

**daemon restart owed in a quiet window — not done** (Gemma's; procedure in the brief's SELF-MODIFICATION note — `queue_daemon.py` gains `header_effort` in its fire loop).

## X0
```
/tmp/orch-fire-20261116-205927/orchestrator.py /tmp/orch-fire-20261116-205927/queue_daemon.py
```
Both inside the meta-fire worktree.

## Step 1 · patch
- `sha256sum ~/_eos/s7core55/leangate/lean-gate-1-r5.patch` → `dc1a174e265f7e463029dd962f0080f5924cf2b2844d4ed4687d7a83bb37b5bd` (matches).
- `git apply --3way` → exit 0, every file "Applied patch … cleanly" (test_gate_cost.py via "Falling back to direct application…", still clean).
- `git diff --stat`:
```
 CLAUDE.md                           |   2 +-
 README.md                           |  55 ++--
 config/repos.yaml                   |  85 +++--
 orchestrator.py                     | 506 ++++++++++++++++++------------
 queue_daemon.py                     |  24 ++
 tests/test_control_verdict_lines.py |   2 +-
 tests/test_exec_preflight.py        |  15 +-
 tests/test_foreground.py            |   6 +-
 tests/test_gate_cost.py             |  27 +-
 tests/test_lean_gate.py             | 600 ++++++++++++++++++++++++++++++++++++
 tests/test_prelist.py               |  38 ++-
 tests/test_route_time.py            |  70 ++---
 tests/test_sit_enum_parallel.py     |   5 +-
 tests/test_toni_guards.py           |  11 +-
 tests/test_unit_listing_prefix.py   |   6 +-
 tests/test_unit_related.py          | 159 ++--------
 16 files changed, 1128 insertions(+), 483 deletions(-)
```
All 16 inside A2 ALLOWED FILES.

## Step 2 · no edits beyond the patch — none.

## A0 re-read at 695f5c5 (all as the author cited)
1. `orchestrator.py:4802` `def _unit_scope(...)`; `:4813-4824` triggers + `sit_core_files` ⇒ "(a) the diff touches a shared trigger"; `:4825-4832` "(b) route {since + 1} since the last full unit run"; `:4838-4846` "(c) the related set is empty while non-test source changed"; counter `:4715-4743` `_unit_full_counter_file/_read/_record`. `config/repos.yaml:116-118` `unit_full_triggers: ["package.json", "package-lock.json", …]`, `unit_full_every: 5`.
2. `orchestrator.py:4699` `UNIT_RELATED_ARGS = "--changed {base} --filesOnly"`; `:4852` `def _unit_related_files`; `:4870` `always, always_said = _unit_always(member, chosen) if graph else …`. `:270` `SIT_RELATED_ARGS = "--changed {base} --filesOnly"`; `:2489` `def _sit_related_files`; `:2504-2505` SIT-config change ⇒ `return None, "the diff changes the SIT config …"`.
3. `orchestrator.py:5172-5178` related scope ⇒ `_unit_baseline_related(...)`, else `_unit_baseline_measure_or_reuse(...)`; `:4967` `def _unit_baseline_related`.
4. `orchestrator.py:6154` `def _unit_preflight_reuse`; `:6164-6166` "reused only when both legs were green"; `:6173` `elif "flaky" in unit:`. `:6100` `def _sit_preflight_reuse`; `:6110-6111` `elif "verdict" in sit:` "needed isolation".
5. `orchestrator.py:1063-1065` `preflight_ask = … PREFLIGHT_SENTENCE …` / `" " + TYPECHECK_SENTENCE + preflight_ask`; `:5808-5815` `PREFLIGHT_SENTENCE`, `TYPECHECK_SENTENCE = "… while iterating, run the related tests of the files you changed."`
6. `orchestrator.py:6228` `def _prelist_reach`; `:7593-7597` `gate_prelist(target, proj)` … `fire_toni(target, proj)` (serial).
7. `queue_daemon.py:1522-1524` `b_effort = hdr.get("effort", self.config["effort"])`; `canon_assert.py:1262` `DEFAULT_EXECUTOR_EFFORT = "high"`.
8. `git grep -n -i lint main -- orchestrator.py` → no hits.
9. `state/full-gate-clinical-mp.json` — not re-read (live checkout state; read-only input to the gate, not touched by this route).
- `orchestrator.py:7143-7152` `route_handback_path` `re.match(r"0+\d", stem)` — confirmed, so this handback keeps the five zeros. `:7255` "a leg timeout or an implausible clock is one".

## Predicates (`tests/test_lean_gate.py`, 67 cases)
- **At base** (695f5c5 + only `tests/test_lean_gate.py`): **45 failed, 17 errors, 5 passed**. The 5 passed are exactly the named controls: L-3 `test_a_file_the_nightly_confirmed_flaky_is_left_out_of_the_compare`, L-3 `test_the_history_list_is_read_when_the_newest_result_has_none`, L-5 `test_on_puts_the_preflight_sentence_back`, L-7 `test_no_key_no_lint`, L-9 `test_a_real_build_error_stays_product`. No RED-marked predicate green at base ⇒ no STOP (d).
- **After the patch:** 67/67 passed — L-1 (5), L-2 (10), L-3 (3+2), L-4 (5), L-5 (6+1), L-6 (4), L-7 (2+1), L-8 (1), L-9 (1+1), L-10 (18), L-11 (4+3) all green.

## Step 3 · gates
- `python3 -m py_compile orchestrator.py queue_daemon.py` → exit 0. (No other typecheck in this repo.)
- `yaml.safe_load(open('config/repos.yaml'))` → ok.
- Targeted pytest (the 13 files in step 3): **831 passed in 77.36s**, 0 failed, 0 skipped.
- Keep-green branch guards, re-run after the commit so `main...HEAD` holds the diff: `test_unit_baseline_gate.py::TestTheSuiteCommandIsNotNarrowed::test_no_repo_test_cmd_changed_on_this_branch` PASSED, `::TestOrch8ChangedNoVerdictSemantics::test_ac_o8_10_no_timeout_pool_or_parallelism_knob_moved_on_this_branch` PASSED (with test_lean_gate.py: 69 passed).
- The full `pytest tests/` was not run (the gate's leg runs it).

## Preflight (once)
```
  SIT: 0 file(s) — pass — orchestrator's gate has no SIT leg
  unit: ? file(s) — not computed — the gate runs the FULL unit suite — related selection not available for orchestrator — `pytest -q tests/` is not a vitest run
🧪 Preflight (executor): 0 SIT files / ? unit files — fail (not computed)
   JSON: /home/gkassa/spectricom-orchestrator/state/preflight/orch-orch-00000lean-gate-1.json
```
Exit 3 (`not computed`), not a test red: the brief's Sizing line says the preflight "on this repo measures nothing (its pytest `test_cmd` has no related selection)". No failing file, so no RULE #8 or STOP is triggered. The gate's unit leg runs the full orchestrator suite at merge. Note: the record's tip is the commit before this handback was folded in (amend), so the gate won't reuse it. It has nothing to reuse anyway.

## RULE #8 hits at base (695f5c5)
- **S1** `unit_full_triggers|unit_full_every|unit-full-counter|since_full|_unit_full_counter`: `tests/test_prelist.py:228,235,282`; `tests/test_route_time.py:130,245,254,277,284,285,288,293,384,412,433`; `tests/test_unit_related.py:131,194,201,206,279,282,285,289,291,292,299,306,307,311,316,317,319,417,424`.
- **S2** `--changed|SIT_RELATED_ARGS|UNIT_RELATED_ARGS|_unit_baseline_related|_sit_related_files|_unit_related_files`: `tests/test_control_verdict_lines.py:50`; `tests/test_exec_preflight.py:58,60,146`; `tests/test_gate_cost.py:509,520,560,614`; `tests/test_prelist.py:15,17,47,59`; `tests/test_route_time.py:303,360`; `tests/test_sit_enum_parallel.py:4,69,167`; `tests/test_unit_baseline_gate.py:767`; `tests/test_unit_related.py:6,77,156`; `tests/test_unit_related_extra.py:5,46`.
- **S3** `TYPECHECK|PREFLIGHT_SENTENCE|ORCH_EXEC_PREFLIGHT|preflight --repo`: `tests/test_exec_preflight.py:5,11,34,99,205,216,222,226,228`; `tests/test_foreground.py:171,177`; `tests/test_route_time.py:53,607,609,610,613,615`; `tests/test_toni_guards.py:54,57,64,264`.
- **S4** `needed isolation|"flaky" in unit|both legs`: `tests/test_route_time.py:188,271`; `tests/test_unit_baseline_gate.py:1418` (a comment, untouched).
- **S5** `baseline-trust`: `tests/test_baseline_trust.py:16,147,194,196,220`; `tests/test_clockguard_1.py:400,425,443`; `tests/test_config_truth.py:9,228,365`; `tests/test_control_verdict_lines.py:50`.
- Edits to the hit files are only what the patch makes (G-1…G-5 + the class-iii harness edits). The files the brief expects unchanged (`test_unit_baseline_gate.py`, `test_unit_related_extra.py`, `test_baseline_trust.py`, `test_clockguard_1.py`, `test_config_truth.py`) are untouched by the diff. `test_unit_baseline_gate.py` and `test_baseline_reuse_1.py` ran green in the targeted run. Reds outside a grant: none.

## Not done / owed
- **daemon restart owed in a quiet window — not done.**
- Kanban 728 closes after the first clinical-mp route after the restart logs `📋 Unit gate: known reds =` (or no red) and a `🎯 Unit gate: related … (one hop)` line, and the next 02:30 nightly runs green or names its new failing files.
- Gemma follow-ups (Toni template v1-6, SHARED-RULES §7, clinical-mp CLAUDE.md, SESSION-BOOT #30), ORCH-LEAN-GATE-2 (OPEN-1, M-2), OPEN-2 measurement: not this route.
