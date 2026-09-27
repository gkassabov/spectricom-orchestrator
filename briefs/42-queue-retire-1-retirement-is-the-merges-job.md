#!queue model=claude-opus-5 effort=high repo=orchestrator

# QUEUE-RETIRE-1 — retirement is the merge's job, not the scheduler's exit path

## Repo: orchestrator
## Batch ID: s7core15-queue-retire-1
## Briefs: 1
## Estimated runtime: 30-45 min
## Spec reference: `D-S7CORE14-02` (a daemon retires the brief before it dies) · boot assert `B6` (SESSION-BOOT, S7-CORE-14)
## Predecessor: none. `main` at fire time.

## 0 · FIRST STEP

Read `queue_daemon.py` in full (382 lines) and `orchestrator.py` around the two merge sites —
`:3401` (the normal `Merged <branch> -> <target>` path) and `_self_mod_auto_merge` at `:1380`.
Read `tests/test_self_mod_auto_merge.py` and `tests/test_running_marker.py` for the shape the
existing tests use. Do not design before reading.

## 1 · WHY THIS EXISTS

`RESOLVER-1` merged as `f1359634` on 21 Sep 15:59. The daemon that would have retired its brief was
killed at shutdown **after** the merge and **before** the bookkeeping. The brief stayed in `queue/`
for five days, and the 26 Sep restart **re-fired an already-merged route**.

The cause is a division of labour, not a missing try/except. `queue_daemon.py:325` performs the
retirement — `shutil.move(next_batch, QUEUE_DONE / batch_name)` — and it runs only after
`self.current_process.wait()` returns. Everything between the merge (inside the child process) and
that line is an unguarded window. Widening the window is a scheduling detail; **owning the wrong
half of the transaction is the defect.** The process that merges is the only process that knows the
merge happened.

`queue_daemon.py` also has **no SIGTERM handler** — line 380 catches `KeyboardInterrupt` only — so a
`kill` skips bookkeeping entirely. That is a real gap and it is **deliberately out of scope**: it
would only narrow the window. This brief closes it.

## 2 · THE TARGET STATE (`D-S7CORE13-02` · `S1` — a predicate, not a list of symptoms)

**No brief file remains in `queue/` whose route has already merged to its repo's merge target.**

That sentence is boot assert `B6`, and `B6` is currently a human running two commands at boot. Ship
it as the acceptance oracle:

`check_queue_trunk_invariants(queue_dir, repo) -> list[Violation]`, **empty when clean.** A violation
names the brief filename and the merge commit that already carries it. Put it where
`canon_assert.py` lives so the boot path and the tests share one implementation — **do not write a
second copy for the tests.**

**Done is that predicate returning empty after a kill in the window, not a list of the places I
happened to notice a move.**

## 3 · SCOPE — exactly what to change

### T1 · the merge retires the brief
At **both** merge sites — `:3401` and `_self_mod_auto_merge` — retire the originating batch file as
part of the merge's own completion, before the function returns success.

**Bounded, and this bound is the increment's main risk:** retirement fires **only when the batch file
resolves inside `queue/`**. A batch file passed by path from anywhere else is **never moved**. The
`DATE-7` invocation shape —
`orchestrator.py run /home/gkassa/spectricom-clinical-mp/briefs/41-….md --repo clinical-mp` — must
behave **byte-identically** to today. Test both directions; a passing test for the queue case and no
test for the path case is a fail of method.

### T2 · the daemon's move becomes idempotent
`queue_daemon.py:325` and `:330` and `cancel_current` at `:164` all `shutil.move` a file that may
already be gone. Make each a no-op on a missing source rather than an exception. The daemon keeps
recording its `completed` / `failed` entry — **state bookkeeping stays the scheduler's, file
retirement moves to the merge.** Do not conflate the two.

### T3 · the predicate runs at daemon start
On startup, before the first batch, run `check_queue_trunk_invariants` and retire anything it names,
logging each retirement. This is `B6` automated and it is the recovery half: a kill *during* the
merge leaves a state the merge itself could not have finished. **Idempotent — a second start finds
nothing.**

## 4 · OUT OF SCOPE

- **Do not** add a SIGTERM/atexit handler. It narrows the window instead of closing it and it invites
  the reading that the window is the defect.
- **Do not** touch `max_consecutive` or `reset_consecutive()` (`L-9`, a separate finding).
- **Do not** touch branch naming or stale-base reuse (`BUG-S7CORE14-ORCH-STALEBASE-01`).
- **Do not** change gate semantics, verdict classification or `PRE_MERGE_GATES`.
- **Nothing** in `clinical-mp`. This is one repo (`A3`).

## 5 · ACCEPTANCE

- **AC-QR-01** — `check_queue_trunk_invariants` exists, returns `[]` on a clean queue, and returns a
  violation naming brief and merge commit when a merged brief sits in `queue/`. **Demonstrate the
  failure; do not assert it.**
- **AC-QR-02** — **`RESOLVER-1` reproduced, red before green.** A test that merges and then prevents
  the daemon's bookkeeping from running at all must still leave the brief in `queue/done/`. State the
  red count on unmodified code.
- **AC-QR-03** — a batch file outside `queue/` is never moved. Assert the file is still at its
  original path after a successful merge, and assert the queue case moves. Both directions.
- **AC-QR-04** — daemon start retires an already-merged brief and logs it; a second start retires
  nothing.
- **AC-QR-05** — no `shutil.move` in `queue_daemon.py` raises on a missing source. Cover all three
  call sites.
- **AC-QR-06** — `pytest -q tests/` green with no new failures against the merge-base baseline. State
  both counts.
- **AC-QR-07** — reachability (`D-S7CORE9-01`): name the non-test caller of the new predicate. "It is
  exported and tested" is not an answer.

## 6 · HANDBACK

§7 first (`D-S7CORE13-02`): what you found and left, and why. Then what shipped, the gate table with
both baseline counts, AC-QR-07's caller, and — `D-S7CORE13-03` — **the consequence**: whether any
existing invocation shape changes behaviour, and whether a brief currently sitting in any queue
directory moves as a side effect of this change.
