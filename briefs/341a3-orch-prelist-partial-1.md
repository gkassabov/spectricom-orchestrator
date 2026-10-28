#!queue model=claude-opus-5-5 effort=high repo=orchestrator

# ORCH-PRELIST-PARTIAL-1 — the generated GATE PRE-LIST still lists the SIT files (and whatever unit files can be named) when the gate's unit leg runs the full suite, instead of generating nothing

## Repo: orchestrator (`~/spectricom-orchestrator`)
## Batch ID: s7core36-orch-prelist-partial-1
## Briefs: 1
## Kanban: SCP_Kanban row 497
## Estimated runtime: 30-60 min
## Test scope: targeted (D-S7CORE30-05)
## Spec reference: D-S7CORE36-03 (Codex v2-74; George 2026-10-28 11:13 "go") — ORCH-PRELIST-1 (`034b35f`, 341a2). First live fire after the 13:51 daemon restart, `341b5c-prevent-risk-1` (`logs/clinical-mp/orch-341b5c-prevent-risk-1-*.log` 13:53:43): `📋 Gate pre-list not generated: unit: the gate runs the FULL unit suite — (a) the diff touches a shared trigger (unit_full_triggers): src/lib/cds/risk/index.ts (src/lib/**), …`. Cause: `gate_prelist` (`orchestrator.py` ~:5544) returns `_not(...)` when EITHER `reach.sit` or `reach.unit` is None, and `tests_reaching` (~:5328) leaves `unit` None whenever the unit leg is full and the related set is not computed — which is every brief touching `src/lib/**` (a shared trigger), i.e. most clinical routes. The SIT set — the leg that caused the S7-CORE-36 gate failures — was computable and was dropped with it.
## Predecessor: orchestrator `main` at or after `db7612b` (341a2 merge).
## Executor: claude-opus-5-5 --effort high (queue header line 1; D-S7CORE35-09)
## Agent policy: AP-ORCH (SCP_Agent_Inventory_v0-3)
## George go: 2026-10-28 11:13 George "go" (D-S7CORE36-03) — the generated pre-list; this route completes it for the common full-unit case

> Background tasks disabled. Foreground everything. No daemon restart is needed: `gate_prelist` runs inside `orchestrator.py run`, fresh per route. Do NOT edit `queue_daemon.py`.

## Operability & safety
- **Telemetry:** the existing `📋 Gate pre-list generated: <n> SIT + <m> unit files …` line, now also when one leg is unavailable, with ` (unit: <why>)` / ` (SIT: <why>)` appended; `📋 Gate pre-list not generated: <why>` only when BOTH legs are unavailable or the worktree cannot be made.
- **Failure mode + degraded path:** a leg that cannot be named is stated in the block as one line (`- unit leg: the gate runs the full unit suite — <why>; the executor's preflight runs it`) — never silently omitted; nothing about the gate changes.
- **Rollback / kill switch:** revert this route's commit; `ORCH_PRELIST=off` unchanged.
- **Agent permissions (Rule of Two):** deterministic orchestrator code only (AP-ORCH); no LLM.
- **PHI & protected paths:** none; orchestrator fire code is a protected path — George go above.

## PART A · PARTIAL PRE-LIST (Kanban row 497)

## A0 · FIRST STEP — as built (paste file:line)
`tests_reaching` (~:5328-5375: the SIT branch, the unit branch's three outcomes), `_prelist_reach` (~:5520), `gate_prelist` (~:5544-5585: the `reach.sit is None or reach.unit is None` refusal, the block rows, `PRELIST_HEADING` / `PRELIST_RULE`), and `tests/test_prelist.py` (PL1–PL4 from 341a2). Paste why `unit` is None for the 341b5c paths (scope not capable, or `_unit_related_files` returning None on the synthetic uncommitted diff) — run `tests_reaching` on a worktree at HEAD of `~/spectricom-clinical-mp` with `src/lib/clinical/longevity/risk-context.ts` touched, read only.

## A1 · TARGET STATE
- **F1 · One leg is enough.** `gate_prelist` generates the block when at least one of `reach.sit` / `reach.unit` is a tuple; a leg that is None contributes one line `- <leg> leg: <its why>` (e.g. "unit leg: the gate runs the full unit suite — (a) shared trigger …; the executor's preflight runs it") instead of file rows. Both None ⇒ today's `_not(...)` with both reasons.
- **F2 · Name what can be named.** If the unit leg is full only because of a shared trigger and `_unit_related_files` CAN compute the related set on the synthetic diff, the unit rows are those files (the `else` branch already intends this — fix it if the synthetic uncommitted diff is why it returns None, e.g. by committing the touched paths in the temporary worktree before listing, then removing the worktree as today). Paste which case applied.
- **F3 · Nothing else moves.** The heading, the rule sentence, the named-file filter and the log line keep their text except for the appended leg reason.

## A2 · ALLOWED FILES
`orchestrator.py` (`gate_prelist` and, for F2, `_prelist_reach` / `tests_reaching`'s unit branch only), `tests/test_prelist.py` (new cases; existing cases unchanged unless they pin the "not generated" refusal for one missing leg — rule #8 below), `briefs/341a3-orch-prelist-partial-1.handback.md`. NOT `queue_daemon.py`.

**Rule #8 line — George go 2026-10-28 11:13:** a `tests/test_prelist.py` case that asserts "not generated" when exactly one leg is None may change only to assert the block with that leg's reason line; every other assertion unchanged; old/new in the handback.

## A3 · PREDICATES
- **PP1:** reach with SIT files and unit None ⇒ the block lists the SIT files and one "unit leg: …" line; log line names both. RED on HEAD (not generated).
- **PP2:** reach with unit files and SIT None ⇒ the mirror. RED on HEAD.
- **PP3:** both None ⇒ not generated, both reasons (unchanged).
- **PP4 (F2):** a fixture repo whose touched path is a shared trigger and whose related set is listable ⇒ unit rows present (paste whether the fix was needed).
- **PP5:** the full `venv/bin/python -m pytest -q tests/` GREEN (the build gate, ~70 s).

## STOP
(a) any change to what a gate leg runs or decides; (b) a pre-list set different from `tests_reaching` for the same diff; (c) a part that needs `queue_daemon.py` or a daemon restart; (d) any LLM judgement.

## 4 · HANDBACK / 6 · GATES
Handback `briefs/341a3-orch-prelist-partial-1.handback.md`: A0 pastes (incl. why `unit` was None for the 341b5c paths), F1/F2 as built, PP RED→GREEN, rule #8 old/new. Gates: the full `venv/bin/python -m pytest -q tests/` and `python3 -m py_compile orchestrator.py`.

## Closes capability advancement: none (pipeline reliability, D-S7CORE36-03)
## Gates journey: orchestrator — fire → generated pre-list → executor
