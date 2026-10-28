#!queue model=claude-opus-5-5 effort=high repo=orchestrator

# ORCH-TEST-EFFICIENCY-1 RE-FIRE — land the three built `341a1` commits (`b7c7efb` SIT enumeration beside the build + full-gate unit reuse, `d3d275c` related unit set, `e4a1dc4` gates-only re-gate) and clear the two source guards the build gate (`pytest -q tests/`) tripped: a forbidden literal in a new docstring and a new 🛡 speaker not registered in the pinned control set

## Repo: orchestrator (`~/spectricom-orchestrator`)
## Batch ID: s7core36-orch-test-efficiency-refire
## Briefs: 1
## Kanban: SCP_Kanban row 403 (+ rows 404, 405, 406)
## Estimated runtime: 45-75 min
## Test scope: targeted (D-S7CORE30-05)
## Spec reference: `queue/failed/341a1-orch-test-efficiency-1.md` (the original brief — every target, allowed file, env escape and STOP applies unchanged to the cherry-picked commits); branch `orch-orch-341a1-orch-test-efficiency-1` (handback `330e191`: all three briefs done, no STOP); the first run's gate (`logs/orchestrator/orch-341a1-orch-test-efficiency-1-20261028-115411.log`): `BUILD GATE FAILED — 2 failed, 1887 passed`: (1) `tests/test_sit_rate_limit.py::TestSitBatching::test_batch_size_and_pause_are_configuration_not_literals` — `'vitest list' not in src` fails on a new docstring ("what `vitest list --changed` reads"); (2) `tests/test_control_verdict_lines.py::test_source_guard_C_is_pinned` — `_control_violations` reports the 🛡 speakers now include `_unit_baseline_related: {'baseline-trust'}`, which the pinned set C does not name.
## Predecessor: orchestrator `main` at or after `4160d6b`.
## Executor: claude-opus-5-5 --effort high (queue header line 1; D-S7CORE35-09)
## Agent policy: AP-ORCH (SCP_Agent_Inventory_v0-3)
## George go: 2026-10-24 12:10 George Agree (D-S7CORE33-36) — the original route; 2026-10-28 11:23 "go, move them" (run it next); the C-set registration below is a standing mechanical pin moved by the route's own change (RE-CHECK class (i)).

> Background tasks disabled. Foreground everything. No daemon restart, and none is needed (the original brief's note holds: `orchestrator.py` runs fresh per route). Do NOT edit `queue_daemon.py`.

## Operability & safety
- **Telemetry:** as the original brief (`⏩ SIT enumeration ran beside the build`, `♻️ full-gate unit: reused …`, `🎯 Unit gate: related …`, `🔁 Re-gate (gates only) …`); the new `baseline-trust` line from `_unit_baseline_related` is registered in the control set, not removed.
- **Failure mode + degraded path:** as the original brief — every new path fails toward more testing.
- **Rollback / kill switch:** revert this route's commits; env escapes `ORCH_SIT_ENUM_PARALLEL=off`, `ORCH_FULLGATE_REUSE=off`, `ORCH_UNIT_RELATED=off`, `ORCH_REGATE_GATES_ONLY=off`.
- **Agent permissions (Rule of Two):** deterministic orchestrator code only, AP-ORCH; no LLM in any gate decision.
- **PHI & protected paths:** none; orchestrator gate code is a protected path — George go above.

## PART A · LAND AND CLEAR THE GUARDS (Kanban rows 403–406)

## A0 · FIRST STEP
1. HEAD contains `4160d6b`; the branch `orch-orch-341a1-orch-test-efficiency-1` holds `b7c7efb`, `d3d275c`, `e4a1dc4`; paste.
2. `git cherry-pick b7c7efb d3d275c e4a1dc4`; paste conflicts and resolutions (D-S7CORE36-02: additive only, else STOP (b)).
3. Run `venv/bin/python -m pytest -q tests/` on the cherry-picked tree; paste the summary (expect exactly the two reds above).
4. Paste the pinned control set C in `tests/test_control_verdict_lines.py` and how `_control_violations` builds the speaker map; paste `_unit_baseline_related`'s 🛡 line and `_unit_baseline_measure_or_reuse`'s (both speak `baseline-trust`).

## A1 · TARGET STATE
- **F1 · No forbidden literal.** The new docstring that names the list command is reworded so `orchestrator.py` no longer contains the literal `vitest list` (e.g. "what the repo's `sit_list_cmd` reads with `--changed`"); no behaviour change. Grep `orchestrator.py` for the other forbidden literals of that test (`vitest.sit.config`, `sleep(90`, `range(0, 19`) — none present.
- **F2 · One registered speaker per control line.** Either (a) `_unit_baseline_related` emits its `baseline-trust` verdict through the existing `baseline-trust` speaker (`_unit_baseline_measure_or_reuse` or the helper it uses), so the speaker map equals C unchanged; or (b) C in `tests/test_control_verdict_lines.py` gains `'_unit_baseline_related': {'baseline-trust'}` and nothing else. Prefer (a) if it is a call to an existing helper with no behaviour change; else (b). Say which and why.
- **F3 · Nothing else moves.** The three cherry-picked commits unchanged except for conflict resolution and F1/F2.

## A2 · ALLOWED FILES
Everything the original brief's ALLOWED FILES allow (carried by the cherry-picked commits only), plus `orchestrator.py` (F1's docstring and, under F2 (a), the one `baseline-trust` emission in `_unit_baseline_related`), `tests/test_control_verdict_lines.py` (F2 (b): the C set entry only), `briefs/341a1-orch-test-efficiency-1-refire.handback.md`.

**Rule #8 line — George go 2026-10-24 12:10 + RE-CHECK class (i):** `tests/test_control_verdict_lines.py` may change only to register `_unit_baseline_related` → `baseline-trust` in C (F2 (b)); every other assertion unchanged; old/new text in the handback. `tests/test_sit_rate_limit.py` is not edited (F1 fixes the source).

## A3 · PREDICATES
- **PR1:** `venv/bin/python -m pytest -q tests/test_sit_rate_limit.py tests/test_control_verdict_lines.py` — RED on the cherry-picked tree without F1/F2 (paste the two failures), GREEN with them.
- **PR2:** the full `venv/bin/python -m pytest -q tests/` GREEN (paste the summary line) and the original brief's predicates re-run (paste counts).

## STOP
The original brief's STOP list, plus: (k) a non-additive cherry-pick conflict; (l) any red in the full `pytest -q tests/` other than the two named, after F1/F2; (m) a test edit beyond F2 (b).

## 4 · HANDBACK / 6 · GATES
Handback `briefs/341a1-orch-test-efficiency-1-refire.handback.md`: A0 pastes, F1/F2 as built (which F2 option and why), PR1 RED→GREEN, PR2 summary, rule #8 old/new if F2 (b), the original handback's R-items carried. Gates: the full `venv/bin/python -m pytest -q tests/` (the build gate) and `python3 -m py_compile orchestrator.py`.

## Closes capability advancement: none (gate efficiency, D-S7CORE33-36)
## Gates journey: orchestrator — fire → gates (build/SIT/unit) → merge; nightly full gate; gates-only re-gate
