#!queue model=claude-opus-5-5 effort=high repo=orchestrator

# ORCH-UNIT-LISTING-PREFIX-1 — the unit listing reads clinical-mp's vitest-workspace lines (`[server] …`, `[app] …`), so the per-route unit gate can select the related set it was built to select (ORCH-UNIT-RELATED-1), the executor's preflight runs it, and the generated pre-list names the unit files

## Repo: orchestrator (`~/spectricom-orchestrator`)
## Batch ID: s7core36-orch-unit-listing-prefix-1
## Briefs: 1
## Kanban: SCP_Kanban row 499
## Estimated runtime: 45-75 min
## Test scope: targeted (D-S7CORE30-05)
## Spec reference: `341a3` handback (`briefs/341a3-orch-prelist-partial-1.handback.md`, orchestrator `d5f1a97`) §A0 and "Finding for George": clinical-mp's unit config is a vitest workspace (`[server]`, `[app]` projects), so every listing line carries a `[project] ` prefix; `_parse_sit_listing` (`orchestrator.py:2391`, `if not line or " " in line.split(" > ", 1)[0]: continue`) reads each as a banner; `_unit_listing` (:4497) returns `[]`; `_unit_related_files` (:4566) returns None — **"on clinical-mp, the gate's unit leg can never select a related set today. Every route that does not hit (a) or (b) falls to (c) the unit suite could not be enumerated"**; and the executor's preflight unit leg reports `not computed` (exit 3) on every clinical route (`341b7`, `341b5d` logs). ORCH-UNIT-RELATED-1 (George 2026-10-24 12:10 Agree, D-S7CORE33-36 fix #1: "per-route unit gate runs the related test files; full suite on shared triggers, every 5th route, uncomputable set"; ~100–120 min/day) therefore never took effect on clinical-mp. The SIT listing (`vitest.sit.config.ts`, no workspace) parses today and must keep parsing identically.
## Predecessor: orchestrator `main` at or after `d5f1a97`.
## Executor: claude-opus-5-5 --effort high (queue header line 1; D-S7CORE35-09)
## Agent policy: AP-ORCH (SCP_Agent_Inventory_v0-3)
## George go: 2026-10-24 12:10 George Agree (D-S7CORE33-36 fix #1, the related unit gate — this route makes it work on clinical-mp as decided) + 2026-10-28 11:13 "go" (D-S7CORE36-03, preflight and pre-list) — authorises the listing parser change (protected gate code)

> Background tasks disabled. Foreground everything. No daemon restart is needed (`orchestrator.py` runs fresh per route and per full gate). Do NOT edit `queue_daemon.py`. The regression rule, the shared triggers (`unit_full_triggers`), `unit_full_every` and the nightly full suite are unchanged — only the listing parse that feeds them.

## Operability & safety
- **Telemetry:** the existing `🎯 Unit gate: related <n>/<total> files (full suite: <reason>)` line now shows a related count on clinical-mp routes that hit no trigger; the preflight unit leg shows files instead of `not computed`; one new DEBUG-level count of prefixed lines stripped per listing.
- **Failure mode + degraded path:** a listing line that still cannot be parsed after stripping a leading `[name] ` is skipped as today; an empty listing ⇒ `(c)` full suite as today (fails toward more testing). `unit_full_every` (every 5th route) and the nightly full gate keep the whole suite in rotation.
- **Rollback / kill switch:** revert this route's commit; `ORCH_UNIT_RELATED=off` (341a1) restores the full suite every route.
- **Agent permissions (Rule of Two):** deterministic orchestrator code only (AP-ORCH); no LLM.
- **PHI & protected paths:** none; orchestrator gate code is a protected path — George go above.

## PART A · READ WORKSPACE LISTING LINES (Kanban row 499)

## A0 · FIRST STEP — as built (paste file:line)
1. `_parse_sit_listing` (:2391), its callers (SIT plan, `_unit_listing` :4497), `_unit_related_files` (:4566), `_unit_scope` (the (a)–(d) reasons), `_preflight_unit` (:5394).
2. A real listing sample from clinical-mp, read only: `cd ~/spectricom-clinical-mp && npx vitest list --changed HEAD~1 2>/dev/null | head -5` (or the repo's configured unit list command) — paste the `[app] …` / `[server] …` line shape; and the SIT listing's shape (`vitest.sit.config.ts`) for contrast.
3. The tests covering the parser and the unit scope (`tests/` — list them).

## A1 · TARGET STATE
- **F1 · Strip the project prefix, nothing else.** Before the banner check, a line matching `^\[[^\]\s]+\] ` has that prefix removed (one helper, used by both listings — A13); every other rule of the parser is unchanged, so the SIT listing's parse is byte-identical on its fixtures. The file path after the prefix is what the related set uses (paths stay repo-relative as today).
- **F2 · The effect is the decided one.** On a clinical-mp diff that hits no shared trigger, `_unit_scope` returns the related file set (not `(c)`); on a trigger diff, the full suite as today with the related set still named (pre-list rows, preflight files). `unit_full_every` and the nightly full gate unchanged.
- **F3 · The pre-list line tells the truth.** The None-leg line from 341a3 (`orchestrator.py` ~:5573, "the executor's preflight runs it") reads "the gate runs the full suite at merge" when the preflight does not run that leg (341a3 flag).

## A2 · ALLOWED FILES
`orchestrator.py` (the prefix helper and its two call sites in the listing parse; the ~:5573 f-string only), new `tests/test_unit_listing_prefix.py`, existing parser/scope tests only where a fixture asserts a prefixed line is ignored (rule #8 below), `briefs/341a4-orch-unit-listing-prefix-1.handback.md`. NOT `queue_daemon.py`.

**Rule #8 line — George go 2026-10-24 12:10 + 2026-10-28 11:13:** a test asserting that a `[project] `-prefixed listing line is skipped may change only to assert it is read as its path; every other assertion unchanged; old/new in the handback.

## A3 · PREDICATES
- **PU1:** a workspace listing fixture (`[app] src/a.test.tsx > …`, `[server] server/__tests__/b.test.ts > …`) ⇒ `_unit_listing` returns both paths. RED on HEAD (`[]`).
- **PU2:** a clinical-mp-shaped diff with no trigger ⇒ `_unit_scope` gives the related set with the `🎯 related n/total` reason. RED on HEAD (`(c)`).
- **PU3:** the SIT listing fixtures ⇒ identical parse before and after (control).
- **PU4:** the preflight on a fixture branch ⇒ unit leg lists files, not `not computed`. RED on HEAD.
- **PU5:** the full `venv/bin/python -m pytest -q tests/` GREEN (the build gate).
- **PU6 (live, read only):** `python3 orchestrator.py preflight --repo clinical-mp --json /tmp/pu6.json` from a clean clinical-mp worktree at main with one non-trigger test-adjacent file touched (then reverted) ⇒ the unit leg names files; paste the summary.

## STOP
(a) any change to the regression rule, the shared triggers, `unit_full_every` or the nightly full suite; (b) the SIT listing's parse changing on any fixture; (c) a part that needs `queue_daemon.py` or a daemon restart; (d) any LLM judgement.

## 4 · HANDBACK / 6 · GATES
Handback: A0 pastes (the real listing line shape), F1–F3 as built, PU RED→GREEN, PU6 live summary, rule #8 old/new; the expected effect on clinical-mp unit time per route (from the related count on PU6). Gates: the full `venv/bin/python -m pytest -q tests/`, `python3 -m py_compile orchestrator.py`.

## Closes capability advancement: none (D-S7CORE33-36 fix #1 made effective on clinical-mp; D-S7CORE36-03)
## Gates journey: orchestrator — per-route unit gate; executor preflight; generated pre-list

## GATE PRE-LIST (generated at fire, d5f1a97; D-S7CORE36-03)
- (none beyond the test files this brief already names)
- unit leg: the gate runs the FULL unit suite — related selection not available for orchestrator — `pytest -q tests/` is not a vitest run; the executor's preflight runs it
Each stays green unedited except under the brief's rule #8 lines (incl. D-S7CORE36-01 class (iii)); a red here is STOP (a) like any other.
