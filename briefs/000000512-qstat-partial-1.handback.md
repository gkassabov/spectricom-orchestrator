## STATUS: DONE

# QSTAT-PARTIAL-1 (Kanban 512; ORCH-QSTAT-PARTIAL-1) — handback

**Commit:** one commit on `orch-orch-000000512-qstat-partial-1` — "QSTAT-PARTIAL-1 (512; ORCH-QSTAT-PARTIAL-1): …" (SHA in the git log; files: `queue_daemon.py`, `tests/test_qstat_partial.py`, this handback).

## Base
`git merge-base --is-ancestor 4ab922e HEAD` → exit 0 (ancestor). STOP (e) not met.

## A0 at HEAD, before any edit (all as the brief says)
1. `git grep -n 'def route_outcome\|def with_outcomes\|ORCH-QSTAT-PARTIAL-1' -- '*.py'` → 0 lines.
2. `git grep -n '"completed": self.completed\[-10:\],\|…' -- queue_daemon.py` → 4 lines:
   ```
   queue_daemon.py:1179:                "completed": self.completed[-10:],
   queue_daemon.py:1180:                "failed": self.failed[-5:],
   queue_daemon.py:1181:                "stopped": self.stopped[-5:],
   queue_daemon.py:1182:                "held": self.held[-5:],
   ```
3. `git grep -n "^def route_record" -- queue_daemon.py` → `queue_daemon.py:447:def route_record(batch_name: str, started_at: str) -> Optional[dict]:`

## G-1
`sha256sum ~/_eos/s7core59/dry/512.patch` → `81639747cbfb6760b374a0061c105f881d99679db1f412daebe3bef323c3828c` (matches). I applied it with `git apply`: first `--include='tests/test_qstat_partial.py'` (RED), then `--include='queue_daemon.py'` (GREEN). The resulting `git diff`, with `index` lines removed, is **identical** to the patch. No other edits.

## RED (base + test file only)
`PYTHONPATH=. pytest -q tests/test_qstat_partial.py` → **10 failed in 0.36s** (AttributeError: no `route_outcome`; QP-3 KeyError `outcome`).

## GREEN (after G-1)
`PYTHONPATH=. pytest -q -s tests/test_qstat_partial.py` → **10 passed in 0.19s**
```
[QP-3] {"passed-merged.md": "merged", "partial-merged.md": "merged (partial)", "stop-nothing.md": "stopped, nothing merged (handback STOP (d))", "blocked-env.md": "blocked (environment)", "failed.md": "failed"}
```
`python3 -m py_compile queue_daemon.py` → ok.

## The 153 (status-reader set): not run here
The fire prompt and the repo CLAUDE.md (ORCH-LEAN-GATE-1, D-S7CORE54-77) say to run only the test files I added or changed, by path, and never a related set, because the gate runs those. So I did not run `tests/test_handback_stop_status.py tests/test_merge_hold.py tests/test_queue_park_red.py tests/test_queue_gate_log.py tests/test_qstat_full_gate_truth.py` (153 in the dry run). The gate's full unit leg covers them. No existing test file was edited.

## Notes
- The worktree has no `venv/`. Tests ran with the main checkout's venv (`~/spectricom-orchestrator/venv`), activated read-only.
- The `~/bin/qstat` follow-up (read `outcome`) is still OPEN for Gemma, as the brief says. It is outside this repo and I did not touch it.
