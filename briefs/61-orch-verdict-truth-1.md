#!queue model=claude-opus-5-5 effort=xhigh repo=orchestrator

# ORCH-VERDICT-TRUTH-1 — a verdict that can say "I could not tell", a route that cannot merge half-done, a queue an operator can see

## Repo: orchestrator
## Batch ID: s7core16-orch-verdict-truth-1
## Briefs: 3 (bundle — one increment per brief, §5.12; executed in order, one commit per brief)
## Estimated runtime: 60-90 min
## Spec reference: Bug Registry v1-58 — [GATE-CLOCK-1] P1 · [ORCH-TIMEOUT-HOLD-1] P1 · [TONI-BACKGROUND-EXIT] P1 (second door) · [QUEUE-PAUSE-OPAQUE] P2 · [ORCH-HANDBACK-SILENT-PASS] P3; LESSONS L-18, L-19, L-21, L-25
## Predecessor: orchestrator main @ 567fccf (TONI-BG-CEILING-1). Verify with `git rev-parse --short main`. The author did NOT run pytest; route 60 measured 625 passed / 0 failed at 567fccf. You measure it at the merge-base.
## Executor: claude-opus-5-5 --effort xhigh (owner instruction 2026-09-28, S7-CORE-16; smoke-verified on CLI 2.1.283 before fire)

> **DO NOT BACKGROUND ANYTHING. Not a test run, not a sleep, not a probe.** Route 60's own probe proved
> that on CLI 2.1.283 a background Bash task is **killed within ~13 s of your turn ending** and **no
> follow-up turn ever arrives**. If you background the suite and end your turn, the suite dies, you never
> hear about it, and this brief merges half-done. `pytest -q tests/` takes ~15 s here. Run everything in
> the foreground and wait for the numbers. If you need a pause, `python3 -c 'import time; time.sleep(60)'`
> in the foreground.

## 0 · FIRST STEP

1. `git rev-parse --short main` → expect `567fccf`. If different, `git log --oneline 567fccf..main` and
   state what landed.
2. `pytest -q tests/` at the merge-base, **foreground**. Record passed/failed. This is your baseline.
3. Read, by name (line numbers below are as of `567fccf`; if moved, grep the name, never trust the number):
   - `orchestrator.py`: `fire_toni` (~`:824`, the `TimeoutExpired` branch ~`:870-876` writes **no trailer**),
     `toni_child_env` (~`:815`), `_run_batch_inner` and its `Status.PASSED if (ec == 0 or _produced_work)`
     line (~`:3712` per route 60's handback), `_handback_hold` (~`:3500-3522` — it logs **only** when it
     holds), `run_unit_gate` (~`:2916`), `_unit_baseline_measure_or_reuse` (~`:2860`), `run_sit_gate` and its
     isolation leg (~`:1994`), the F-20 classifier (~`:3201-3306`, the function whose docstring begins
     "PDLC F-20: BLOCKED(environment) vs FAIL(product)"), `GateOutcome` (~`:426`), `INCOMPLETE_VERDICT`.
   - `canon_assert.py`: the ORCH-HANDBACK-GUARD-1 section and the TONI-BG-CEILING-1 section (`:915-989`).
     Every predicate in this brief goes into `canon_assert.py` in the same idiom (stdlib-only, frozen
     violation dataclass, `check_*_invariants` returning `[]` when clean, first-match ordered reasons).
   - `queue_daemon.py`: `pause` / `resume` / `reset_consecutive` (~`:231-295`), `run_loop` (~`:355-470`;
     `self.status = "paused"` at ~`:372` and ~`:465`), `_save_state`, the `__main__` CLI (~`:536-582`).
   - `config/handback-guard.json` (the guard fails CLOSED if it is missing — do not move or rename it).
4. The evidence, read-only: `logs/orch-20260928-014908.log` (route 59's second fire, clean 336.7 s unit leg)
   and whichever `logs/orch-2026092[78]-*.log` carries route 59's FIRST fire (unit leg **15,867.9 s** across
   a ~4 h machine sleep, 5 failed vs a declared 3). `grep -l "59-ui-identifier" logs/orch-2026092*.log`.

## WHY ONE BUNDLE

Three defects, one shape: **the pipeline reports a state it did not measure.** A gate leg that ran across a
four-hour suspension reports a product verdict. A route killed at its timeout with work on the tree reports
`PASSED` and merges. A daemon that paused itself reports nothing anywhere a human can read. Each brief below
is one increment, one commit, and each is independently revertible (A12). They share `canon_assert.py` and
the orchestrator's verdict vocabulary, which is why they travel together (`D-S7CORE11-01`, defect-batching
rule: none of the five blocks development alone; together they are the trust in every future verdict).

---

# BRIEF 1 of 3: GATE-CLOCK-1 + HANDBACK-SILENT-PASS — a verdict is only as honest as its clock, and a control that passes must say so

## 1.1 Target state (the predicate — `D-S7CORE13-02`)

**Let L = every gate LEG the orchestrator times**: the build gate, each SIT batch run, the SIT isolation
re-run, the unit gate's branch leg, the unit gate's baseline leg (when measured, not when reused from cache),
and the unit isolation confirm re-run. State L as found (file:line per leg) in the handback; a leg you find
that is not in this list is added to L, not skipped.

**For every leg l ∈ L, record three clocks at start and end:** `time.time()` (wall), `time.monotonic()`,
and `time.clock_gettime(time.CLOCK_BOOTTIME)` (Linux; fall back to `None` if unavailable and say so).

**P-CLOCK (plausibility).** A leg is *implausible* iff ANY of:
- `|Δwall − Δmonotonic| > 60 s` (the wall clock jumped — NTP/Hyper-V resync after a host sleep), or
- `Δboottime − Δmonotonic > 60 s` (the kernel was suspended during the leg), or
- `Δwall > 5 × median(history)` where history = the last ≥3 recorded **plausible** durations of the same
  (repo, leg-kind), persisted where the gate already persists its counts. Fewer than 3 samples ⇒ this clause
  does not apply (say so in the log line; never invent a default median).

**The rule (one clause in the existing F-20 classifier — not a new verdict path):**
- a **red** verdict from an implausible leg is `BLOCKED(environment)` with reason `clock-implausible`, never
  `FAIL(product)`. The branch is preserved, nothing merges;
- a **green** leg stays green but its log line says `implausible` — a sleep can manufacture failures, it
  cannot manufacture passes; record it and do not discard it;
- an implausible leg's duration is **never** written into the history used by the median clause.

**P-SAY (every control logs its verdict on the PASS path — `L-18`, PDLC F-99).** Let C = { handback guard
(`_handback_hold`), bg-wait ceiling check (`fire_toni`), clock plausibility (new, per leg), SIT isolation
leg, unit isolation confirm }. For every engagement of every c ∈ C, the orchestrator log carries **exactly
one** verdict line on both the pass and the hold/fail path, of the form
`🛡 <control>: <CLEAN|HOLD|BLOCKED|…> — <one-line detail>`. A control that was **not engaged** on a route
(e.g. SIT isolation when nothing failed) logs nothing — absence then means "not engaged", which is only
auditable because presence is guaranteed when it was.

## 1.2 Scope
- `canon_assert.py`: `check_clock_plausibility(leg_kind, clocks_start, clocks_end, history) -> list[ClockViolation]`
  (pure; no I/O; reasons ordered: `wall-jump`, `suspended`, `outlier-vs-history`).
- `orchestrator.py`: a tiny `_leg_clocks()` helper; each leg in L captures start/end; the F-20 classifier
  gains the one clause; history persistence reuses the gate-record store you find (do not invent a new file
  if one exists; if none exists, add `state/gate-durations.json` and say so).
- `_handback_hold` and the other C members gain their PASS-path line.
- `tests/test_gate_clock.py` (new) and `tests/test_control_verdict_lines.py` (new).

## 1.3 Acceptance
- **AC-GC-01 red first.** Tests that simulate a leg with `Δwall = 15867.9, Δmonotonic = 336.7` and red
  counts fail against unmodified code (the classifier says `FAIL(product)`), quote the failing line. After:
  `BLOCKED(environment)` / `clock-implausible`.
- **AC-GC-02 the replay.** Feed route 59's two real unit legs (first fire 15,867.9 s / second 336.7 s, same
  5-vs-3 counts) through the classifier: first ⇒ `BLOCKED(environment) clock-implausible`, second ⇒
  `FAIL(product)` (it was a real regression — the rule must not rescue it). Both asserted.
- **AC-GC-03 bounds (A11).** The 60 s thresholds and the 5× factor are module constants with a test each at
  the boundary (60 s not implausible, 60.001 s implausible; 5.0× not, 5.01× is). History of 2 samples ⇒ the
  outlier clause does not fire, asserted.
- **AC-GC-04 green stays green.** An implausible green leg ⇒ PASS, with the `implausible` log line, asserted.
- **AC-GC-05 every control speaks.** For each c ∈ C one test drives the PASS path and asserts exactly one
  `🛡 <c>:` line; one drives the non-pass path and asserts exactly one. A source-guard test pins C: a new
  `_*_hold`/guard function without a verdict line turns it red (state how you detect "a control" — name the
  pattern, bounded).
- **AC-GC-06 live history.** State how many real samples the history store holds after your change is
  seeded from existing records (if you backfill from `logs/`, say from which files; if you do not, say the
  outlier clause is dormant until 3 routes run).

---

# BRIEF 2 of 3: ORCH-TIMEOUT-HOLD-1 + ORCH-FOREGROUND-1 — a route killed mid-work never merges, and the executor is not offered a background it will lose

## 2.1 Target state

**P-MERGE.** For every route r: `merged(r) ⇒ ec(r) == 0 ∧ handback(r) CLEAN ∧ gates(r) PASS`.
Today `Status.PASSED if (ec == 0 or _produced_work)` lets `ec == -1` (timeout, SIGKILL) and `ec == -2`
(executor error) with work on the tree reach the gates and merge. After this brief:
- `ec ∉ {0}` with produced work ⇒ a distinct outcome **`INCOMPLETE(timeout)`** / **`INCOMPLETE(executor-error)`**
  (reuse `INCOMPLETE_VERDICT` / `Status` values if they fit — say which), branch preserved, **no gate run,
  no merge**, queue treats it as a failure (moves the brief to `queue/failed/`, pauses per `stop_on_failure`);
- `fire_toni`'s timeout and error paths **write a trailer** to the Toni log, the same shape the normal path
  writes: `Finished: <iso>` / `Exit: -1 (TIMEOUT after <n>m — SIGTERM, SIGKILL)` or `Exit: -2 (<error>)`, so
  `handback-scan` and a human both see why it stopped.
- **Salvage stays possible and manual**: the handback of an INCOMPLETE route names the branch and the exact
  `git log --oneline main..<branch>` command. Canon §5.X+1 salvage is an operator act, not an auto-merge.

**P-FOREGROUND.** For every fire f: the executor is not offered background execution, and a foreground
command is allowed to run long enough to finish the unit suite twice.
- Probe first (T0, foreground, ≤2 attempts, haiku, same shape as route 60's AC-BC-07 — no `-p`, stdout to a
  file, under `timeout 300`): with `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` set, ask the model to run
  `sleep 20 && echo PROBE-DONE` with `run_in_background=true`. Record whether the tool call was refused /
  ran in the foreground / was backgrounded. Also record whether the installed CLI binary mentions
  `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`, `BASH_DEFAULT_TIMEOUT_MS`, `BASH_MAX_TIMEOUT_MS` (bounded Python
  read of the binary in chunks — route 60's `grep` over the 230 MB binary hit the 120 s tool limit; do not
  repeat that).
- **If the probe shows the variable is honoured:** `toni_child_env` sets `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`
  (override, never setdefault) and sets `BASH_DEFAULT_TIMEOUT_MS` and `BASH_MAX_TIMEOUT_MS` to a value
  bounded **strictly below** the route timeout (reuse `bg_wait_ceiling_ms(T)` — one bound, not two).
  Extend `check_bg_ceiling_invariants` (or add a sibling in the same section) so the predicate covers all
  three variables with the same `0 < v < 1000·T` rule, and `DISABLE_BACKGROUND_TASKS == "1"`.
- **If it is NOT honoured (or the names do not exist in the binary):** set nothing you cannot prove, say so,
  and apply only the prompt half below.
- **Prompt half (always):** the fire command's instruction becomes
  `"Read <brief> and execute all briefs in order. Run every command in the foreground and wait for it to finish; never use run_in_background — background tasks are killed when your turn ends and no follow-up turn will come."`
  Pin it with a source-guard test. (Route 60 §4 kept the prompt out of scope; this brief brings it in.)

## 2.2 Acceptance
- **AC-TH-01 red first.** A test with a fake executor that exits via timeout after writing a file: on
  unmodified code the route is `PASSED` and reaches the merge step (quote the line); after, `INCOMPLETE(timeout)`,
  no gate call, no merge call (assert the gate/merge functions are never invoked — spies, not log greps).
- **AC-TH-02 trailer.** Timeout and error paths write `Exit: -1 …` / `Exit: -2 …` into the Toni log; asserted
  by reading the file.
- **AC-TH-03 the queue.** `queue_daemon` moves an INCOMPLETE route's brief to `queue/failed/` (assert via its
  existing exit-code path; state which exit code the orchestrator process returns for INCOMPLETE).
- **AC-FG-01 the probe table** (both variants, exit, wall, what happened to the background request, binary
  string presence). Or `BLOCKED(environment)` with the reason. Do not fake it.
- **AC-FG-02 the env predicate** (only if honoured): red on unmodified code, green after, bound cases at
  T = 1800 / 3360 / 10800.
- **AC-FG-03 the prompt pin.** Source guard over the literal in `fire_toni`.

---

# BRIEF 3 of 3: QUEUE-PAUSE-OPAQUE — a paused queue says so, and one command resumes it

## 3.1 Target state

**P-PAUSE.** For every transition of the running daemon into `paused` (stop_on_failure, max_consecutive,
operator `pause`): within one poll interval `queue-state.json` carries `daemon_status: "paused"`,
`paused_reason` (one of `stop-on-failure:<brief>`, `max-consecutive:<n>`, `operator`), and `paused_at`.
`python3 queue_daemon.py status` prints them on its first line.

**P-RESUME.** `python3 queue_daemon.py resume` (new subcommand) returns a paused daemon to `running`
**without a restart**, within one poll interval, and is a no-op with a clear message when the daemon is not
paused or not running. Mechanism: the CLI process cannot touch the daemon's memory — use a control file the
run loop reads each poll (e.g. `state/queue-control.json` with a monotonic request id; the daemon acknowledges
by writing the id back). `pause` gets the same CLI. `reset_consecutive` is reachable the same way
(`resume --reset-consecutive`).

**P-STALE.** A `running.json` / `state/running-*.json` whose PID is dead does not block a fire: the daemon's
next poll logs `🛡 stale-running-marker: CLEARED <file> (pid <n> dead)` and archives it as
`*.killed-<ts>` (the two existing `running.json.killed-*` untracked files in the repo root show the manual
version of this — say whether you move them; do not delete them).

## 3.2 Acceptance
- **AC-QP-01** a test drives stop_on_failure and asserts the persisted state fields; red on unmodified code.
- **AC-QP-02** `resume` round-trip test against a daemon object run in a thread (no real subprocess fires —
  stub `_run_route`), asserting status `running` within one poll and the ack written.
- **AC-QP-03** stale-marker test with a PID that does not exist.
- **AC-QP-04 live, read-only:** run `python3 queue_daemon.py status` against the real daemon (PID from
  `pgrep -af queue_daemon`) and paste the first line. **Do not pause, resume, restart or kill the live
  daemon.** It keeps running the old `queue_daemon.py` until the operator restarts it — say so in the
  consequence section.

---

## BUNDLE-LEVEL ACCEPTANCE
- **AC-B-01 the gate, no new failures.** `pytest -q tests/` at the merge-base and on the branch, both
  **foreground**, both counts stated. Set: every test under `tests/`, none deselected.
- **AC-B-02 diff bounded.** `git diff --stat <merge-base>` touches only `orchestrator.py`, `canon_assert.py`,
  `queue_daemon.py`, `config/` (only if the history store lands there — say so), and new `tests/test_*.py`.
  No existing test's **assertions** change; if one must, quote before/after and why.
- **AC-B-03 three commits**, one per brief, messages `fix(orch): … (GATE-CLOCK-1 …, S7-CORE-16)` etc.
- **AC-B-04 handback self-check** exactly as route 60 §6 did: draft to `/tmp/vt-handback.txt`, run the
  guard's rules over it, it must print `CLEAN`, then print it unchanged as your closing message. Quote CLI
  lines off the start of a line.

## OUT OF SCOPE — name, leave
- Retro-classifying past verdicts (route 59's first fire stays recorded as killed).
- Any clinical-mp file. Any change to `config/repos.yaml` gate commands or SIT batch sizes.
- `[BASELINE-FLAKE-1]` — measured separately by the operator at S7-CORE-16 boot; if its result is in
  `~/_eos/s7core16/flake.log` when you start, read it and say in one line whether it changes BRIEF 1's
  design (it should not: flake is a per-file property, clock plausibility is a per-leg property).
- Restarting the live daemon (operator step after merge).

## HANDBACK — consequence section (D-S7CORE13-03), state plainly
1. Which red verdicts would now be `BLOCKED(environment)` instead of `FAIL(product)` (the clock rule), and
   that a real regression measured on a sane clock is still `FAIL(product)` (AC-GC-02).
2. That a timed-out route with work no longer merges — **a class of past "salvage" merges becomes manual.**
3. Whether background execution is now disabled for the executor, or only discouraged in the prompt (probe).
4. That the live daemon runs old code until restarted, with the exact restart command from
   `~/bin/s7core14-start-daemon.sh`.
