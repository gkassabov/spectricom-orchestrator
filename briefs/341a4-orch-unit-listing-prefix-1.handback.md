# filename: briefs/341a4-orch-unit-listing-prefix-1.handback.md

# 341a4 · ORCH-UNIT-LISTING-PREFIX-1: handback

**Status: done.** F1, F2 and F3 are in, in one product commit, `e9379c5` (code and tests); this file is the second commit. The route ran on `orch-orch-341a4-orch-unit-listing-prefix-1`, from `d5f1a97`. No daemon restart is needed, and `queue_daemon.py` is untouched.

On clinical-mp the unit listing now parses. A live preflight with one non-trigger file touched named **27 related unit files of 1755** and ran them: 332 tests passed in 68.9 s. Before this change the same leg said `not computed`.

## Finding for George (not fixed: STOP (a), outside ALLOWED FILES)

**The unit *run*-output parser has the same workspace problem as the listing had.** In run output, vitest prints a failure as `FAIL  |app| src/x.test.ts > …`. `_GATE_FAIL_FILE_RE` (`orchestrator.py:4998`, `^\s*(?:❯\s+)?FAIL\s+(\S+)`) captures `|app|` as the failing file.

**Live evidence (PU6, first probe).** The full 364-file run had 2 failures:

- the log read `🛡 unit-confirm: CLEAN — every newly-failing file passed alone (flaky): |app|`;
- the preflight JSON recorded `"flaky": ["|app|"]`.

The isolation re-run was `npm test -- '|app|'`, and it was read as "passed alone".

**Consequence.** On clinical-mp, a real unit failure in the `[app]` project may be classed as a flake by the gate's isolation step instead of as a regression. This is pre-existing: the run-output parse is independent of the listing, and the gate's full-suite runs on clinical-mp already went through it. This route only made it visible.

Fixing it changes the regression rule's input (STOP (a)) in a file region this brief does not allow. I made no change. It needs a George go and its own route: strip `\|[^|\s]+\|\s+` after `FAIL` in that parser, plus RED tests in the shape of the gate's isolation tests.

## A0 · as built (pre-change line numbers, `d5f1a97`)

1. **The parser and the code that uses it.**
   - `_parse_sit_listing` is at `orchestrator.py:2385`. Its banner check was `if not line or " " in line.split(" > ", 1)[0]: continue`.
   - It has three callers: `_sit_plan` at `:2424` (the SIT suite), `_sit_related_files` at `:2478` (the SIT related set) and `_unit_listing` at `:4506`.
   - `_unit_listing` (`:4497`) is used by `_unit_related_files` (`:4560`), which makes two calls: the suite (`--filesOnly`) and the related set (`--changed <base> --filesOnly`).
   - `_unit_scope` (`:4510`) gives the reasons (a) to (d): a shared trigger, every N-th route, a set that cannot be computed, and `ORCH_UNIT_RELATED=off`.
   - `tests_reaching` (`:5328`) feeds `_preflight_unit` (`:5394`). That function returns `not computed` when `reach.unit is None`, and it never runs a leg in that case. `_preflight_sit` does the same.
2. **The real listing shape** (clinical-mp `main` `665251a4`, read only). There is no `vitest.config.*`. `vite.config.ts` defines the projects, and `npm test` is `vitest run`.
   - `npx vitest list --filesOnly`: 1755 lines, all prefixed (1728 `[app]`, 16 `[server]`, 11 `[journey]`). Every path is repo-relative and exists:
     ```
     [server] server/__tests__/assistant.test.ts
     [app] src/App.portalChrome.test.tsx
     ```
   - `npx vitest list`: 17372 lines.
     ```
     [app] src/__tests__/tab-placement-1-routes.test.tsx > redirects — an old child route lands on its tab (Navigate replace), no loop, both letter cases > /pros → /vitals
     [journey] sit/journey/l-enrol/__tests__/lane-options.test.ts > P10 (F10) — lane options, upstream > owner, name, run tag and lane reach the plan: …
     ```
   - SIT, for contrast (`npx vitest list --config vitest.sit.config.ts`): 649 lines, **0 prefixed**:
     ```
     sit/integration/member-portal-via-bff.integration.test.ts > MEMBER-API-PROXY-1a-iii P4 — the portal on the BFF, live, in a browser > she signs in at /portal/signin and visits every /portal route: …
     ```
3. **Tests covering the parser and the unit scope:**
   - `tests/test_unit_related.py` (the unit scope)
   - `tests/test_exec_preflight.py` (the preflight)
   - `tests/test_prelist.py` (the pre-list)
   - `tests/test_gate_cost.py`, `tests/test_sit_rate_limit.py`, `tests/test_sit_enum_parallel.py`, `tests/test_sit_isolation_attributed.py`, `tests/test_clockguard_1.py`, `tests/test_control_verdict_lines.py` (the SIT plan and related listing)

## F1–F3 as built (`e9379c5`)

- **F1 · Strip the prefix.**
  - `_LISTING_PROJECT_RE = ^\[[^\]\s]+\] ` (`:2385`) and `_strip_listing_project` (`:2388`) form the helper.
  - It is called once, inside `_parse_sit_listing` (`:2395`), before the banner check. Both listings go through that parser: the SIT callers at `:2438` and `:2492`, and the unit caller at `:4520`. So one helper serves both (A13).
  - Every other parser rule is byte-for-byte unchanged.
  - The DEBUG line `listing: <n> workspace-prefixed line(s) read past their [project]` (`:2412`) is logged only when n > 0.
  - Only `[name] ` with no whitespace inside the brackets and one following space is stripped. So `[a b] x` and `[app]x` parse as they did before. A prefixed banner such as `[app] RUN  v3.2.4 …` is still a banner.
- **F2 · The effect.** No change to `_unit_scope`, the triggers, `unit_full_every`, the regression rule or the nightly gate.
  - On a no-trigger diff, `_unit_related_files` now enumerates the suite, so `_unit_scope` returns the related set and the gate logs `🎯 Unit gate: related n/total`.
  - On a trigger diff it returns `(a)`, and `tests_reaching` still names the related set (`unit_full` = the reason). Pre-list rows and preflight files follow from that.
- **F3 · The pre-list line** (`:5587`) now reads `- <leg> leg: <why>; the gate runs the full suite at merge`.
  - Both `_preflight_sit` and `_preflight_unit` return `not computed` for a None leg, so the preflight never runs a leg the pre-list cannot name. The new text is therefore correct for every None leg, and no condition was added.
  - It is the f-string only. The `📋 Gate pre-list generated:` log line is unchanged.

## PU · RED → GREEN

New `tests/test_unit_listing_prefix.py`. It reuses the rigs of `test_unit_related` and `test_exec_preflight`, and its fakes print each unit listing line as a workspace does.

**RED:** run against `d5f1a97`'s `orchestrator.py` (a temporary detached worktree, removed afterwards): **9 failed, 7 passed**.

| Predicate | What it checks | RED (`d5f1a97`) | GREEN (`e9379c5`) |
|---|---|---|---|
| PU1 (5 tests) | `_unit_listing` returns both projects' paths, with and without `--filesOnly`; the real clinical-mp shape; only the prefix is stripped; the DEBUG count | all 5 fail (`[]`) | pass |
| PU2 (3 tests) | `_unit_scope` gives `(T1, T2)` with total 10, not `(c)`; the gate runs `npm test -- T1 T2` and logs `🎯 Unit gate: related 2/10 files`; a `vite.config.ts` diff gives `(a)` with `reach.unit == (T1,)` | all 3 fail | pass |
| PU3 (7 tests, control) | `test_gate_cost`, `test_sit_isolation_attributed`, `test_sit_rate_limit` and `test_clockguard_1` `LIST_OUT`, the real clinical-mp SIT lines, banners/ANSI/blank/files-only, and an empty listing each parse identically to a copy of the `d5f1a97` parser | all 7 pass (as a control should) | pass |
| PU4 (1 test) | preflight on a workspace-listing branch: unit leg `pass`, files `[U1, U2]`, both run, exit 0 | fails (`(c) the unit suite could not be enumerated — no file listed`) | pass |

**GREEN:** 16 passed.

- **Related set** (the 10 files in A0.3 plus the new file): **299 passed**.
- **`python3 -m py_compile orchestrator.py`:** ok.
- **PU5, the full `venv/bin/python -m pytest -q tests/`: NOT run.** The brief's header is `## Test scope: targeted (D-S7CORE30-05)`. Shared rules §7 and CLAUDE.md say a full suite runs only under a `## Test scope: full — <George decision>` header, and the pre-merge gate runs it right after this route. This matches the 341a3 precedent.

## PU6 · live, read only

The probe used a detached worktree of `~/spectricom-clinical-mp` at `main` `665251a4`, with `node_modules` symlinked. One file was touched and committed on the detached HEAD; no ref was created. Afterwards the link was unlinked, the worktree removed and pruned, and the clinical-mp checkout was left clean on `main`.

**Probe 1, discarded.** `src/lib/base64.ts` turned out to be a shared trigger: clinical-mp's `unit_full_triggers` include `src/lib/**`.

- Unit leg: `364 file(s) — pass — 364 affected … (the gate runs the FULL unit suite on this diff: (a) … src/lib/base64.ts (src/lib/**))`.
- So a trigger diff still names its related set, as F2 requires.
- This probe surfaced the `|app|` finding above.

**Probe 2, the PU6 answer.** `src/components/ChargeItem/ChargeItemList.tsx` (non-trigger, with an adjacent test). `python3 orchestrator.py preflight --repo clinical-mp --json /tmp/pu6.json`, exit 2:

```
🧪 Preflight unit run — 6375c1c5: 27 files/332 tests, 0 failed (derived), 332 passed in 68.9s
  SIT: 3 file(s) — environment — 3 affected by the diff against merge-base 665251a (--changed), 0 changed by the branch, 0 core (sit_core_files); failed: sit/integration/chart-truth-1.integration.test.tsx, sit/integration/problems-plan-links.integration.test.tsx, sit/integration/tab-placement.integration.test.tsx
  unit: 27 file(s) — pass — 27 affected by the diff against merge-base 665251a (--changed), 0 changed by the branch
🧪 Preflight (executor): 3 SIT files / 27 unit files — fail (environment)
```

- **The unit leg names files.** Before this change it was `not computed`, exit 3 (`341b7` and `341b5d` logs).
- **The SIT leg is environment-red: services were not up for the throwaway worktree.** Every SIT batch in probe 1 had 0 passed. It is unrelated to this change, because the SIT listing parse is unchanged and PU3 confirms it.

## Rule #8 · old/new

**Rule #8 edit:** `tests/test_prelist.py::TestPP1UnitLegUnavailable::test_the_341b5c_shape_a_shared_trigger_and_a_project_prefixed_listing`. It pinned the `[app] `-prefixed listing as unreadable; it now asserts the listing is read as its paths. Every other assertion is unchanged.

Old:
```python
        why = (f"the gate runs the FULL unit suite — (a) the diff touches a shared trigger (unit_full_triggers): "
               f"{PAGE} (src/**)")
        assert f"- `{SEARCH_SIT}` (SIT)" in text and _leg_line("unit", why) in text.splitlines(), text
        assert _generated(caplog) == [f"📋 Gate pre-list generated: 1 SIT + 0 unit files for 1 allowed files at "
                                      f"{rig.sha[:7]} (unit: {why})"]
```
New:
```python
        # [ORCH-UNIT-LISTING-PREFIX-1] rule #8: the `[app] ` listing is read as its paths — the unit leg is named
        why = f"(a) the diff touches a shared trigger (unit_full_triggers): {PAGE} (src/**)"
        assert f"- `{SEARCH_SIT}` (SIT)" in text and "- unit leg: " not in text, text
        assert _generated(caplog) == [f"📋 Gate pre-list generated: 1 SIT + 0 unit files for 1 allowed files at "
                                      f"{rig.sha[:7]} (the gate's unit leg runs the full suite here: {why})"]
```

**F3 text pins, mandated by F3 itself and flagged as rule #8-adjacent.** The suffix `"; the executor's preflight runs it"` became `"; the gate runs the full suite at merge"` in three places in `tests/test_prelist.py`: the `_leg_line` helper (`:199`), PP1 (`:219`) and PP2 (`:253`). Nothing else changed in those tests.

## Expected effect on clinical-mp unit time per route

- **A non-trigger route** now runs its related set instead of the full suite. PU6 ran 27 of 1755 files (332 tests) in **68.9 s**. The full suite is the ~9.7 min a route measured for ORCH-UNIT-RELATED-1, so this is **about 8.5 min saved** on such a route.
- **Routes that touch a trigger** still run the full suite, and every 5th route (`unit_full_every`) does too. clinical-mp's triggers are broad (`src/lib/**`, `server/**`, `src/types/**`, `src/test/**`, configs), so the daily saving depends on how many routes avoid them. Probe 1, a single `src/lib` file, related 364 files.
- The ~100–120 min/day decided in D-S7CORE33-36 assumed most routes miss the triggers. The `🎯 Unit gate: related n/total` log lines over the next days will show the real share.

## Preflight (`python3 ~/spectricom-orchestrator/orchestrator.py preflight --repo orchestrator`), exit 3

```
  SIT: 0 file(s) — pass — orchestrator's gate has no SIT leg
  unit: ? file(s) — not computed — the gate runs the FULL unit suite — related selection not available for orchestrator — `pytest -q tests/` is not a vitest run
🧪 Preflight (executor): 0 SIT files / ? unit files — fail (not computed)
```

- This is the known R1 (341a2, 341a3): the preflight cannot compute a related set on a pytest repo.
- Nothing ran and nothing was red. The gate runs the full `pytest -q tests/` at merge, as the pre-list line now says.
- No rule #8 or STOP applies.

## STOP check

None of the STOP conditions was hit:

- (a) The regression rule, triggers, `unit_full_every` and nightly gate are untouched. The `|app|` run-output fix that would touch the regression rule's input is flagged above, not made.
- (b) The SIT parse is identical on every fixture (PU3).
- (c) No `queue_daemon.py` change and no restart.
- (d) No LLM judgement.
