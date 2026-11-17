## STATUS: DONE

# ORCH-QUEUE-PARK-RED-1 — handback (Kanban 733)

Route branch `orch-orch-00000733-queue-park-red-1`, base `8104e94`. That is main with 727 landed, not the brief's `2e062f5`. The brief's predecessor line covers this case ("applies clean on main + 727's r2 patch"). The patch applied clean with no conflicts, offset +5/+7 in `queue_daemon.py`.

## X0 — worktree
```
/tmp/orch-fire-20261117-042859/orchestrator.py /tmp/orch-fire-20261117-042859/queue_daemon.py
```
Both modules load from inside the meta-fire worktree.

## A0 — re-read at the base (8104e94)
1. `run_loop` red branch: `queue_daemon.py:1650-1656` (+5 from 727): `_safe_move(next_batch, QUEUE_FAILED / batch_name)` and then `if self.config["stop_on_failure"]: … self._mark_paused(f"stop-on-failure:{batch_name}")`.
2. `_exit_code_of`: `orchestrator.py:8044-8050`, which returns 1 for every non-pass. `_record_result`: `orchestrator.py:8038`.
3. `_next_brief`: `queue_daemon.py:1114`. `prefire.dependency_trays`: `prefire.py:532` (+14 from 727).
4. `_regate_check`: `orchestrator.py:7376`. The meta-fire refusal is at `:7387-7389`.
5. 626b relabel: a historical event, unchanged. Not re-read.
6. `ALREADY_RED_SIGNAL = "already-red-on-main"`: `orchestrator.py:4966`.
- `ORCH_DIR = Path.home() / "spectricom-orchestrator"`: `queue_daemon.py:53`, as the brief warns. No `queue_daemon.py` command was run from the worktree.

## Gates
- `sha256sum` of the patch: `68d7ebcd9ab225b5fd39a2cc2cc3f2eb30de0d02d041f00fef8e147450adb422`, which matches.
- `git apply --3way`: exit 0, applied cleanly.
- `git diff HEAD --stat`:
```
 orchestrator.py              |  12 +-
 qstat.sh                     |   8 +
 queue_daemon.py              | 322 +++++++++++++++++++++++++++++-
 tests/test_queue_park_red.py | 456 +++++++++++++++++++++++++++++++++++++++++++
 4 files, 790 insertions(+), 8 deletions(-)
```
- No edits beyond the patch.
- `python3 -m py_compile orchestrator.py queue_daemon.py`: exit 0. `bash -n qstat.sh`: exit 0.
- `pytest -q tests/test_queue_park_red.py`: **44 passed** in 1.85 s.

## Predicate groups (tests/test_queue_park_red.py)
- P-1 park (`TestP1Park`, 8): 8 passed
- P-2 re-check (`TestP2Recheck`, 8): 8 passed
- P-3 controls (`TestP3Controls`, 9): 9 passed
- P-4 overrides (`TestP4Override`, 7): 7 passed
- P-5 r3 (`TestP5R3`, 12): 12 passed
- The base-red evidence is the brief's DRY RUN (`base-red-r3.txt`: 15 failed + 29 errors, 0 passed). It was not re-run here.

## Test scope note
I ran only the test file this route adds. The fire's instruction and ORCH-LEAN-GATE-1 (CLAUDE.md, D-S7CORE54-77) both say: run only your own new or changed tests by path, never a related set. The brief's header is `## Test scope: targeted`, not `full — <George decision>`, so the lean-gate rule governs.

The brief's 17-file targeted list and the two branch guards (`tests/test_unit_baseline_gate.py:1031`, `:1594`) were **not run** here; they are left to the pre-merge gate's full unit leg. The brief's DRY RUN records them green on the r3 clone branch (`r3-clone-targeted-2.log`: 806 passed; `r3-guards.log`: 2 passed).

## RULE #8 hits (re-run at 8104e94)
- `git grep -l -E "stop-on-failure|stop_on_failure" -- tests/` finds `test_config_truth.py`, `test_control_scope.py`, `test_executor_auth.py`, `test_executor_default.py`, `test_handback_stop_status.py`, `test_orch_lane.py`, `test_queue_gate_log.py`, `test_queue_pause.py`, `test_timeout_hold.py`, `test_yorsie_safety.py`. This is the same set the brief names. They are keep-green with no edits (their fake routes write no `state.json` record, so a red is "other" and pauses `stop-on-failure:` with today's print).
- `git grep -l -E "_regate_check|Re-gate of" -- tests/` finds `test_regate_gates_only.py` and `test_prefire.py`, as the brief names. It also finds **three hits the brief does not list**: `test_executor_auth.py`, `test_handback_stop_status.py`, `test_prefire_parse_hazards.py`. None writes a `PRE-MERGE GATE OVERRIDE:` line (the override grep below has no hits), so `_regate_check` takes its unchanged no-override path for them. They are keep-green with no edits, and the gate's run decides.
- `git grep -n "_safe_move(next_batch" -- tests/` finds `tests/test_queue_retire.py:402-403`. That is the structural pin, and the patch keeps the call site in `run_loop`.
- `git grep -n "held/parked\|recheck" -- tests/` at the base: none.
- Harness edits: none. Grants: none. No existing assertion was changed.

## Daemon restart
**daemon restart owed in a quiet window — not done.** The park/re-check logic is in `run_loop`, which the running daemon holds in memory. The restart is Gemma's, by the brief's procedure (`pause` → wait until no route is live and it is outside 02:30-04:00 → stop the daemon by its PID → start `python3 queue_daemon.py` without `--start-running` → `status` → `resume`). `_regate_check` and the `override` CLI take effect at once.

## OPEN (carried from the brief, unchanged)
- OPEN-1 and OPEN-2 are Gemma's calls.
- `~/bin/qstat`'s parked print line is a Gemma follow-up (outside the repo).
- The row closes after the restart and the first live park, or after Gemma's paper replay plus one live night.
