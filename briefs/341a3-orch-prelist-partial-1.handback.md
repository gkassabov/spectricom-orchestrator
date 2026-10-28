# Handback — 341a3-orch-prelist-partial-1 (ORCH-PRELIST-PARTIAL-1, Kanban 497, S7-CORE-36, D-S7CORE36-03)

## Status
F1 is done in `0824522` (on `db7612b`; `orchestrator.py` `gate_prelist` + `tests/test_prelist.py`). F2: **no fix**. The synthetic diff is not why `unit` is None. The cause is a listing-parser gap in a shared function (`_parse_sit_listing`). Fixing it would change what the gate's unit leg decides, which is STOP (a), and the function is outside A2. It is flagged below for George. PP1/PP2 RED → GREEN; PP3/PP4 GREEN on HEAD and after. Related tests: 27 passed. py_compile ok. The preflight exits 3 (`not computed`, the known R1), pasted below. No daemon restart; `queue_daemon.py` is untouched.

## A0 · as built (at `db7612b`)
- `tests_reaching` `orchestrator.py:5328`. The SIT branch is :5333-5347. The unit branch has three outcomes:
  - :5352-5353 `scope.files` set ⇒ the related set.
  - :5354-5355 not capable / no diff ⇒ None.
  - :5356-5361 (a)-(d) full ⇒ `_unit_related_files`. Its None ⇒ `unit` None; files ⇒ `unit` = files with `unit_full` = reason.
- `_prelist_reach` `:5520` (a detached worktree, paths touched uncommitted, deps linked, removed after).
- `gate_prelist` `:5544`. At HEAD, the refusal `if reach.sit is None or reach.unit is None: return _not(...)` was at ~:5562. `PRELIST_HEADING` :5497, `PRELIST_RULE` :5498.
- `tests/test_prelist.py` PL1–PL4 (`:111`, `:143`, `:152`, `:168`).

**Why `unit` was None for the 341b5c paths.** This was a read-only probe: `tests_reaching` on a `_prelist_reach`-shaped detached worktree at clinical-mp HEAD `e5ea3e2`, with `src/lib/clinical/longevity/risk-context.ts` touched. The worktree was removed after; `git worktree list | grep -c prelist` = 0.
```
test_cmd npm test
UnitScope True None None (a) the diff touches a shared trigger (unit_full_triggers): src/lib/clinical/longevity/risk-context.ts (src/lib/**)
list_cmd ('npx vitest list', None)
_unit_related_files (0.5s): None None the unit suite could not be enumerated — no file listed
tests_reaching (150.1s):
  sit (129 files: 'sit/integration/member-portal-via-bff.integration.test.ts', …) | 129 affected by the diff against merge-base e5ea3e2 (--changed), 0 changed by the branch, 0 core (sit_core_files)
  unit None | the gate runs the FULL unit suite — (a) the diff touches a shared trigger (unit_full_triggers): src/lib/clinical/longevity/risk-context.ts (src/lib/**) | full: None
```
The scope is capable (`npm test` → `vitest run` → `npx vitest list`). It is `_unit_related_files` returning None. Its **first** call, the suite enumeration (`--filesOnly`, no `--changed`), already fails, so the synthetic uncommitted diff plays no part. The raw listing, in the worktree and in the checkout alike:
```
rc 0 stdout lines 1754
STDOUT head: [server] server/__tests__/assistant.test.ts
[server] server/__tests__/auth.test.ts …
parsed 0            (worktree)
checkout parsed 0   (the main checkout, same)
```
clinical-mp's unit config is a vitest workspace (`[server]`, `[app]` projects), so every line carries a `[project] ` prefix. `_parse_sit_listing` (`orchestrator.py:2391`, `if not line or " " in line.split(" > ", 1)[0]: continue`) reads each such line as a banner. `_unit_listing` (:4497) then returns `[]`, and `_unit_related_files` (:4566) returns None.

On the synthetic diff itself: the SIT leg's `--changed e5ea3e2` on the same uncommitted worktree returned 129 affected files. Real vitest reads the uncommitted touch as changed.

## F1 · as built (`orchestrator.py:5564-5576`, the log line :5581-5583)
- `missing` = the legs whose set is None, with their `*_why`.
- `len(missing) == 2` ⇒ `_not("SIT: <why>; unit: <why>")`. This is today's text and order.
- Otherwise the rows are built as before from the leg(s) that are tuples (`reach.sit or ()`, `reach.unit or ()`). A None leg adds one line after the rows and before `PRELIST_RULE`: `- <leg> leg: <its why>; the executor's preflight runs it`.
- The heading, the rule sentence, the named-file filter, the `(none beyond …)` row and the log text are unchanged. The log line appends ` (<leg>: <why>)` per None leg, after the existing `unit_full` suffix.
- Example (PP1b, the 341b5c shape): `- unit leg: the gate runs the FULL unit suite — (a) the diff touches a shared trigger (unit_full_triggers): src/pages/SearchPage.tsx (src/**); the executor's preflight runs it`. The why is `reach.unit_why` verbatim, so it reads "FULL", as `tests_reaching` writes it.
- On the next clinical fire of the 341b5c kind, the block will carry the SIT rows (129 here, minus any the brief names) plus that one unit line.

## F2 · which case applied: neither "the synthetic diff" nor a fix
- PP4 shows the `else` branch already works when the listing parses. With a shared trigger (`src/lib/**`) and a listable related set on the synthetic diff, the unit rows are present on HEAD with no change, and the log says `(the gate's unit leg runs the full suite here: (a) …)`. **The fix was not needed.**
- The real 341b5c cause is the `[project] `-prefix parse above. **Not fixed, deliberately.** `_parse_sit_listing` / `_unit_listing` feed `_unit_scope`, which decides the gate's unit leg. Accepting prefixed lines would turn clinical-mp's non-trigger routes from "(c) full suite" into "related set", which is STOP (a). It is also outside A2 (`_prelist_reach` / `tests_reaching`'s unit branch only).
- Finding for George (not acted on): on clinical-mp, the gate's unit leg can **never** select a related set today. Every route that does not hit (a) or (b) falls to `(c) the unit suite could not be enumerated — no file listed`. If that is unintended, it needs a brief that rules on the gate leg (stripping a leading `[name] ` in the unit listing).

## Flag · the mandated "the executor's preflight runs it" overstates
I used the line text from the brief's Operability section as written. But `_preflight_sit` / `_preflight_unit` (:5374/:5394) return `not computed` for a None leg and run nothing. On clinical-mp, the executor's preflight will show `unit: ? file(s) — not computed` and exit 3 for these routes; it does not run the unit leg. The text is one f-string at `orchestrator.py:5573` if George wants different wording (e.g. "the gate's own leg runs it").

## Predicates RED → GREEN (`venv/bin/python -m pytest -q tests/test_prelist.py`)
- RED (new tests on `db7612b` code): `3 failed, 13 passed`. The failures are PP1 `test_the_sit_rows_and_one_unit_leg_line` and `test_the_341b5c_shape_a_shared_trigger_and_a_project_prefixed_listing`, and PP2 `test_the_unit_rows_and_one_sit_leg_line`, all "not generated" (`assert (None)` / block `''`). PP3 and PP4 passed on HEAD.
- After F1, before rule #8: `1 failed, 15 passed`. The failure is `TestPL4…::test_uncomputable_is_unchanged_and_logged` (the one-leg refusal pin).
- GREEN: `16 passed in 7.98s`. Related set `tests/test_prelist.py tests/test_exec_preflight.py`: `27 passed in 1.48s`. `python3 -m py_compile orchestrator.py`: ok.
- Harness: `Vitest` gained optional `sit_rc` and `unit_prefix` kwargs. The defaults keep every existing case byte-identical in behaviour.

## Rule #8 · `tests/test_prelist.py:180` `test_uncomputable_is_unchanged_and_logged` (unit None, SIT `()`)
Old:
```python
        b = _brief(rig, f"`{PROVIDER}`")
        before = b.read_bytes()
        Vitest(rig.monkeypatch, unit_rc=1)
        with caplog.at_level(logging.INFO, logger="orch"):
            assert orchestrator.gate_prelist(b, rig.repo) is None
        assert b.read_bytes() == before
        msgs = [r.getMessage() for r in caplog.records if r.getMessage().startswith("📋 Gate pre-list not generated:")]
        assert len(msgs) == 1 and "unit:" in msgs[0], msgs
```
New:
```python
        b = _brief(rig, f"`{PROVIDER}`")
        Vitest(rig.monkeypatch, unit_rc=1)
        with caplog.at_level(logging.INFO, logger="orch"):
            block = orchestrator.gate_prelist(b, rig.repo)
        assert block and sum(l.startswith("- unit leg: ") for l in _block(b.read_text()).splitlines()) == 1, block
        msgs = [r.getMessage() for r in caplog.records if r.getMessage().startswith("📋 Gate pre-list generated:")]
        assert len(msgs) == 1 and "(unit:" in msgs[0], msgs
```
The test name is kept (it now reads stale: the brief is changed). The both-None "unchanged" pin is PP3.

## Gates / test scope
- **Not run: PP5's full `venv/bin/python -m pytest -q tests/`.** The brief's header is `## Test scope: targeted (D-S7CORE30-05)`. CLAUDE.md / shared rules §7 say a full suite runs only under a `## Test scope: full — <George decision>` header, and the orchestrator's pre-merge gate runs it right after this route. PP5 and §6's full-suite line conflict with that header; I followed the header.
- py_compile: ok.

## Preflight (`python3 ~/spectricom-orchestrator/orchestrator.py preflight --repo orchestrator`, at `0824522`)
```
  SIT: 0 file(s) — pass — orchestrator's gate has no SIT leg
  unit: ? file(s) — not computed — the gate runs the FULL unit suite — related selection not available for orchestrator — `pytest -q tests/` is not a vitest run
🧪 Preflight (executor): 0 SIT files / ? unit files — fail (not computed)
   JSON: /home/gkassa/spectricom-orchestrator/state/preflight/orch-orch-341a3-orch-prelist-partial-1.json
```
Exit 3 = `not computed`, not a red test. This is the 341a2 R1 (the preflight cannot compute a unit set on pytest repos). No STOP (a)-(d) applies and no rule #8 edit follows from it. The gate's own unit leg (full `pytest -q tests/`) is the measurement.

## Found-and-left
- clinical-mp's unit listing `[project] ` prefix, above (gate-leg scope; needs George).
- The preflight-sentence overstatement, above.
