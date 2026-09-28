#!queue model=claude-opus-5-5 effort=xhigh repo=orchestrator

# ORCH-BASELINE-TRUST-1 — a baseline measured on a bad clock cannot pass a branch, and the pipeline has one default executor

## Repo: orchestrator
## Batch ID: s7core16-orch-baseline-trust-1
## Briefs: 2 (bundle, §5.12 — one increment per brief, one commit each)
## Estimated runtime: 45-75 min
## Spec reference: route 61 handback "Found and left — Masked regression" (`logs/orchestrator/toni-61-orch-verdict-truth-1-*.log`); `[ORCH-16]` (SESSION-BOOT, corrected S7-CORE-14); `D-S7CORE15-01`; Kanban row 111
## Predecessor: orchestrator main @ `92803c6` (verify; say what landed).
## Executor: claude-opus-5-5 --effort xhigh (owner instruction 2026-09-28, S7-CORE-16)

> Background tasks are disabled for you (route 61, `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`). Foreground everything.

## 0 · FIRST STEP
1. `git rev-parse --short main` → `92803c6` expected. `pytest -q tests/` at the merge-base, foreground (route 61
   measured 740 passed / 0 failed). Record it.
2. Read route 61's handback (its Toni log, "Found and left") and the P-CLOCK code it shipped: `_leg_clocks`, the
   classifier clause, `check_clock_plausibility` in `canon_assert.py`, and the unit gate's baseline leg
   (`run_unit_gate`, `_unit_baseline_measure_or_reuse`).
3. Grep every place a default executor model/effort is set: `orchestrator.py` (`TONI_MODEL`/`TONI_EFFORT`,
   ~`:200-205`), `queue_daemon.py` (`"model"`/`"effort"` defaults ~`:141-146`, and `queue-state.json`'s persisted
   `config.model` = `claude-fable-5-1`, which survives restarts — LESSONS S7-CORE-14 L-8), `~/bin/s7core14-start-daemon.sh`
   (`TONI_MODEL=claude-opus-5`, read-only for you — it is outside the repo; report it), `config/*.yaml`. List them.

---

# BRIEF 1 of 2: BASELINE-TRUST-1

## 1.1 Target state
**P-BASE.** A unit-gate verdict of `PASS` that depends on a baseline comparison (branch has ≥1 failure) is issued
**only if the baseline leg was plausible** (route 61's P-CLOCK). If the baseline leg is implausible: re-measure the
baseline **once**; if the re-measure is plausible, compare against it; if it is also implausible, the verdict is
`BLOCKED(environment)` `baseline-clock-implausible` — **never PASS, never FAIL(product)**. An implausible baseline is
**never cached** (route 61 says it already is not — prove it with a test, do not assume). A fully green branch still
needs no baseline (unchanged `[ORCH-5]` fast path). Log the decision on both paths (`🛡 baseline-trust: …`, P-SAY).

## 1.2 Acceptance
- **AC-BT-01 red first:** a test where the branch has 5 failures, the baseline leg reports 5 failures with
  Δwall ≫ Δmonotonic: on unmodified code the verdict is `PASS` (quote it); after, a plausible re-measure with 3
  failures ⇒ `FAIL(product)`; an implausible re-measure ⇒ `BLOCKED(environment)`.
- **AC-BT-02** the fast path: fully green branch ⇒ no baseline measured, `PASS`, asserted.
- **AC-BT-03** no cache write for an implausible baseline, asserted by reading the cache.

---

# BRIEF 2 of 2: EXECUTOR-DEFAULT-1 — one default, from one place

## 2.1 Target state
**P-DEFAULT.** The pipeline's default executor is `claude-opus-5-5` / `high` (`D-S7CORE15-01`), defined in **one**
place (a module constant or `config/` value — choose and say why), and every reader of a default — the direct
`orchestrator.py` path, the queue daemon's config when no brief header is present, and `handback-scan`'s banner —
derives from it. A persisted `queue-state.json` `config.model` that differs from the default is **reported** at
daemon start (`🛡 executor-default: persisted claude-fable-5-1 ≠ default claude-opus-5-5 — using …`); decide
whether the persisted value or the default wins and justify it in one line (recommendation: the default wins unless
an operator set it via an explicit command — the persisted value is how a stale default survived before, L-8). A
brief's `#!queue model=… effort=…` header still overrides both (unchanged). `handback-scan` no longer prints a
misleading `Executor:` banner (it runs no executor — print none, or label it `(not a route)`).

## 2.2 Acceptance
- **AC-ED-01** a source-guard test: exactly one literal default model string in the repo outside tests.
- **AC-ED-02** direct path with no `--model` and daemon with no header both resolve `claude-opus-5-5 high` (tests).
- **AC-ED-03** the persisted-mismatch report line, asserted.
- **AC-ED-04** `handback-scan` output carries no `Executor: model=claude-fable-5-1` line (test).
- **AC-ED-05** name `~/bin/s7core14-start-daemon.sh`'s `TONI_MODEL=claude-opus-5` as an operator follow-up with the
  exact one-line `sed` to fix it — do not edit it (outside the repo).

## BUNDLE ACCEPTANCE
- **AC-B-01** `pytest -q tests/` at the merge-base and on the branch, both foreground, both counts; 0 failed.
- **AC-B-02** diff bounded to `orchestrator.py`, `canon_assert.py`, `queue_daemon.py`, `config/` (only if the default
  lands there), new/updated `tests/`. Existing assertions changed ⇒ quote before/after.
- **AC-B-03** two commits. **AC-B-04** handback self-check against `config/handback-guard.json` prints `CLEAN`.

## HANDBACK — THE CONSEQUENCE (D-S7CORE13-03)
Which verdicts change class; that the direct path's default changes from Fable to Opus 5.5; whether the live daemon
needs a restart to pick up the default (it does if `queue_daemon.py` changed — give the command
`~/bin/s7core14-start-daemon.sh` after stopping the daemon PID, only when no route is live).
