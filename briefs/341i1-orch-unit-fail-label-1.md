#!queue model=claude-opus-5-5 effort=high repo=orchestrator

# ORCH-UNIT-FAIL-LABEL-1 — the unit gate names the files and tests that fail: vitest's project label (`|app|`) is not a file; a count rise nobody can name blocks; baselines measured blind are re-measured

## Repo: orchestrator (`~/spectricom-orchestrator`)
## Batch ID: s7core42-orch-unit-fail-label-1
## Briefs: 1
## Kanban: SCP_Kanban row 528
## Estimated runtime: 90-150 min
## Test scope: targeted (D-S7CORE30-05)
## Spec reference: 341a4 handback (`67cedf4`, "Finding for George: the unit run-output FAIL parser reads `|app|` as the failing file … not fixed"); 341h1c2 handback FL-4 (clinical-mp `72bb489a`); 341h4b FL-5 (`25f716da`); 341h5b FL-5 (`3b86d85b`). Gemma's read (S7-CORE-42, 2026-11-02 19:3x): `sit-archive/unit-baseline-cache.json` holds `failing_files: ['app']` on 219 clinical-mp entries from 2026-10-11T03:24 (`58de140`) to 2026-11-02T17:40 (`12290eb`); the last named entry is 2026-10-10T23:14 (`3fb8593`). So `set(branch.failing_files) - set(baseline.failing_files)` (`orchestrator.py` ~:4820–4870 in `run_unit_gate` :4634, and the cache writer ~:3887–3913) has been empty on every route since 10-11, and AC-O6b-03 (~:4891, "count rose … with no newly-failing file — not blocking") let rises through: 10→13 (341g3s), 13→16 (341g3t), 12→14 (341h2r) on 11-02.
## Predecessor: orchestrator `main` at or after `67cedf4`.
## Executor: claude-opus-5-5 --effort high (queue header line 1)
## Agent policy: AP-ORCH
## George go: 2026-11-03 09:41 "agree. go" on Gemma's 23:40 rec #1 ("go 1–4": pause merges; fix — strip the `|project|` label before reading the file name and block whenever the failure count rises without the new failures being named; audit; resume) — authorises a change to protected gate code and supersedes AC-O6b-03 (D-S7CORE42-02).

> Background tasks disabled. Foreground everything. No daemon restart is needed (`queue_daemon.py` runs `orchestrator.py` fresh per route and per full gate — `queue_daemon.py:1613`). Do NOT edit `queue_daemon.py`. The daemon is PAUSED (operator) while this route runs; Gemma resumes it after this route merges.

## Operability & safety
- **Telemetry:** the existing `UNIT BASELINE GATE PASSED/FAILED` line names failing files (paths, never a project label); a new line when a count rise is blocked, naming the extra failing tests; one INFO line per baseline entry rejected as blind (F3) with its key.
- **Failure mode + degraded path:** a run whose failing set cannot be named (no path parsed while failures > 0) is UNKNOWN — it never vouches for a branch: as a baseline it is re-measured; as a branch run with failures above the baseline it BLOCKS (fails toward more testing / no merge).
- **Rollback / kill switch:** revert this route's commit; the daemon `pause` stops merges in the meantime.
- **Agent permissions (Rule of Two):** deterministic orchestrator code only (AP-ORCH); no LLM.
- **PHI & protected paths:** none; orchestrator gate code is a protected path — George go above.

## A0 · FIRST STEP — as built (paste file:line)
1. `_UNIT_VITEST_FAIL_RE`, `_UNIT_VITEST_FILE_FAILED_RE` (~:3226), `_norm_test_path` (:3243), `_parse_unit_summary` (:3251), `_unit_confirm_new_files` (:3570), `run_unit_gate` (:4634) through its PASS/FAIL returns (~:4800–4900, AC-O6b-01/02/03), the cache writer (~:3880–3920) and reader, `_preflight_unit` (:5408).
2. A real clinical-mp failing line, read only: in a clean detached worktree at clinical-mp `main` (node_modules symlinked), run ONE file known red at HEAD (CACHE-GUARD-1 `IcdCodeSearch` C1 — locate it with `git grep -l "CACHE-GUARD-1" -- '*.test.*'`) with the gate's own command shape and paste the raw ` FAIL … ` and ` ❯ … ` lines (ANSI stripped). Never run the whole suite here.
3. Why the cache holds `'app'` (not `'|app|'`): name the step that turns the token into `app`.
4. The tests covering the unit summary parse, the gate verdicts and the cache (`tests/test_unit_baseline_gate.py`, `test_baseline_trust.py`, `test_baseline_reuse_1.py`, `test_unit_related.py` — list the AC-O6b-03 test).

## A1 · TARGET STATE
- **F1 · A project label is not a file.** The unit summary parse drops a leading vitest project label in any form the runner prints (`|app|`, `[app]`, a bare label token followed by a path) before taking the path; `failing_files` holds repo-relative test paths only. One helper, used by both regexes and by the confirm pass; the SIT parse (`_sit_failing_files`) is unchanged.
- **F2 · Failing tests are named too.** The parse also yields `failing_tests` (`<path> > <suite> > <test>` as vitest prints them, label dropped). The cache stores it beside `failing_files`.
- **F3 · A blind baseline is no baseline.** A run (cached or fresh) with `failures > 0` whose `failing_files` is empty or holds any token that is not a test path (no `/`, or not ending in a test suffix the repo uses) is UNKNOWN: the cache reader rejects such an entry (INFO line), so the gate measures the merge base fresh; the full gate does not reuse it. The 219 blind entries are not edited or deleted — they simply stop being read.
- **F4 · A rise nobody can name blocks (supersedes AC-O6b-03, D-S7CORE42-02).** When the branch count exceeds the baseline with no newly-failing FILE: the gate diffs `failing_tests` (branch − baseline); each extra failing test's file is re-run alone (the existing confirm pass); a test still failing alone ⇒ FAIL(product) "regression" naming it; all extras passing alone ⇒ PASS with them reported as flaky; extras that cannot be named (either side's `failing_tests` missing) ⇒ BLOCKED(gate) "count rose by N and the new failures cannot be named", never PASS.
- **F5 · Preflight agrees.** `_preflight_unit` reports file paths (not `|app|`) and never files a still-red HOLD test under `flaky` because of the label (341h1c2 FL-4 case).

## A2 · ALLOWED FILES
`orchestrator.py` (the unit summary parse, the cache entry fields + reader acceptance, the AC-O6b-03 branch of `run_unit_gate`, the confirm call it makes, `_preflight_unit`'s use of the parse — nothing else), new `tests/test_unit_fail_label.py`, existing unit-gate tests only per the rule #8 line, `briefs/341i1-orch-unit-fail-label-1.handback.md`. NOT `queue_daemon.py`, NOT `sit-archive/*` (no cache edits), NOT the SIT parse.

**Rule #8 line — George go 2026-11-03 09:41:** a test asserting AC-O6b-03 (count rose, no new file ⇒ PASS) may change only to assert F4's verdicts; a test fixture whose failing line carries no label stays byte-identical in its expectations; every edit named in the handback with old/new.

## A3 · PREDICATES
- **PF1:** fixture ` FAIL  |app| src/a.test.tsx > S > t1` (and the `❯ |app| src/a.test.tsx (3 tests | 1 failed)` form, and A0.2's real line) ⇒ `failing_files == ('src/a.test.tsx',)`, `failing_tests` names `t1`. RED on HEAD.
- **PF2:** unlabelled fixtures (today's) ⇒ identical parse (control).
- **PF3:** a cache entry with `failing_files == ('app',)` and failures 12 ⇒ rejected by the reader; the gate measures fresh. RED on HEAD.
- **PF4:** baseline 12 / branch 14, same files, `failing_tests` +2 that fail alone ⇒ FAIL(product) naming both. RED on HEAD (PASS today).
- **PF5:** same, +2 that pass alone ⇒ PASS, flaky named.
- **PF6:** same, `failing_tests` missing on one side ⇒ BLOCKED(gate). RED on HEAD.
- **PF7:** baseline 12 / branch 12 ⇒ PASS unchanged (control); a newly-failing FILE path ⇒ today's regression path unchanged (control).
- **PF8 (live, read only):** `python3 orchestrator.py preflight --repo clinical-mp --json /tmp/pf8.json` from a clean clinical-mp worktree at main with one test-adjacent file touched then reverted ⇒ the unit leg names paths; paste the summary.

## STOP
(a) a change to the SIT parse, the shared triggers, `unit_full_every`, the related-set rule or the nightly schedule; (b) any edit of `sit-archive/*` or `queue_daemon.py`; (c) running the whole clinical-mp unit suite (the gate does it at merge — the orchestrator repo's own gate is pytest); (d) any LLM judgement.

## 4 · HANDBACK / 6 · GATES
Handback: A0 pastes (the real line, why `app`), F1–F5 as built, PF RED→GREEN, PF8 live summary, rule #8 old/new, and the expected first-route effect on clinical-mp (one fresh merge-base measurement because every cached entry since 10-11 is blind). Gates: the targeted pytest files above plus `tests/test_unit_fail_label.py`, `python3 -m py_compile orchestrator.py`.

## Closes capability advancement: none (gate integrity; D-S7CORE42-02)
## Gates journey: orchestrator — per-route unit gate; full-gate reuse; executor preflight

## GATE PRE-LIST (generated at fire, 67cedf4; D-S7CORE36-03)
- (none beyond the test files this brief already names)
- unit leg: the gate runs the FULL unit suite — related selection not available for orchestrator — `pytest -q tests/` is not a vitest run; the gate runs the full suite at merge
Each stays green unedited except under the brief's rule #8 lines (incl. D-S7CORE36-01 class (iii)); a red here is STOP (a) like any other.
