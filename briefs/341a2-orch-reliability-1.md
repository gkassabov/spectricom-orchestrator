#!queue model=claude-opus-5-5 effort=high repo=orchestrator

# ORCH-RELIABILITY-1 — fewer re-runs: (1) the executor runs the gate's own related SIT + unit set on its branch before it hands back; (2) the brief Toni receives carries a generated pre-list of every test the gate will run for its ALLOWED FILES; (3) a `## Depends-on:` is met only when the route merged product files, so a STOPPED route's handback-only merge no longer lets its dependents fire on a base that lacks the work

## Repo: orchestrator (`~/spectricom-orchestrator`)
## Batch ID: s7core36-orch-reliability-1
## Briefs: 3 (one fire, one gate run; executed in order)
## Kanban: SCP_Kanban row 496 (supersedes row 488 ORCH-PIN-REACH-1)
## Estimated runtime: 120-180 min
## Test scope: targeted (D-S7CORE30-05)
## Spec reference: George 2026-10-28 10:38 "So many re-runs. What do u recommend we do to take care of the root causes" → Gemma's 10:4x analysis → George 11:13 "go" (D-S7CORE36-03, Codex v2-74). Evidence, S7-CORE-36 (2026-10-27/28, `~/_eos/s7core36/session-log.md`): three routes built clean and failed at the gate's SIT leg 1–2 h later on SITs the executor never ran (`341b1c6` care-gap-provider-first P5; `341b2a` drk-session-fixes-1; `341b5b` llm-paid-drk-session); four STOPs on tests the brief's hand-grepped pre-list missed (`341b1c3d` SearchPage.test; `341b3` 5 files reaching the provider through `src/lib/llm/index.ts`; `341b5` 3 `vi.mock` factories; `341b1c6` re-fire `:171`); `341b5a` fired while its Depends-on `341b5-…-refire` had merged only a STOP handback (`canon_assert._landed` detector 1 matched the merge commit). Dependency ORDER is already enforced (`queue_daemon._next_brief`, ORCH-DEPENDS-ON-1 D4) — not in scope.
## Predecessor: orchestrator `main` containing the merge of `341a1-orch-test-efficiency-1` (its related-unit set, ORCH-UNIT-RELATED-1, is what Brief 1 and Brief 2 reuse).
## Depends-on: 341a1-orch-test-efficiency-1-refire
## Executor: claude-opus-5-5 --effort high (queue header line 1; D-S7CORE35-09)
## Agent policy: AP-ORCH (SCP_Agent_Inventory_v0-3)
## George go: 2026-10-28 11:13 George "go" (D-S7CORE36-03) — authorises changes to the orchestrator's gate, prefire and dependency code (protected paths) named in Operability

> Background tasks disabled. Foreground everything. No daemon restart by the executor: `prefire.py` and `canon_assert.py` are imported by the running queue daemon, so Brief 3 takes effect when Gemma restarts the daemon in a quiet window after merge (say so in the handback). Do NOT edit `queue_daemon.py`; if a part cannot be done without it, STOP (c). Never weaken a gate: the preflight and the generated pre-list add checks, they never replace or skip a gate leg; every new path fails toward more testing or toward not firing.

## Operability & safety
- **Telemetry:** INFO lines `🧪 Preflight (executor): <n> SIT files / <m> unit files — <pass|fail>` (written by the preflight command into the route log and its JSON `state/preflight/<branch>.json`), `📋 Gate pre-list generated: <n> SIT + <m> unit files for <k> allowed files at <sha7>` at fire, and `⛔ Depends-on <stem>: merged handback only (briefs/) — not met` from A11 / D4.
- **Failure mode + degraded path:** preflight cannot compute the set (no SIT plan, diff unreadable) ⇒ it says so, exits non-zero, and the executor's brief rules treat it as a red to report (never a silent pass); the generated pre-list cannot be computed ⇒ the fire proceeds with the brief as written and logs `📋 Gate pre-list not generated: <why>` (the gate itself is unchanged); a dependency's merged diff cannot be read ⇒ "not met" (A11 fires nothing — today's safe answer).
- **Rollback / kill switch:** revert this batch's commits; env escapes `ORCH_EXEC_PREFLIGHT=off` (the executor prompt omits the preflight step), `ORCH_PRELIST=off` (no generated block), `ORCH_DEPENDS_PRODUCT=off` (Depends-on judged by `_landed` alone, today's behaviour).
- **Agent permissions (Rule of Two):** deterministic orchestrator code only (AP-ORCH); the preflight is a command the executor runs inside its own worktree, read-only to main, writing only its JSON under `state/preflight/`; no LLM in any decision.
- **PHI & protected paths:** none; orchestrator gate/prefire/dependency code is a protected path — George go above.

## ORDER (read first)
Brief 1, commit; Brief 2, commit; Brief 3, commit. Each brief's predicates RED on HEAD before its change, GREEN after. If time runs short, stop after a committed brief and say which are done — never a half-built brief committed. One handback `briefs/341a2-orch-reliability-1.handback.md`, a section per brief.

## 0 · FIRST STEP — as built (paste file:line for each, at HEAD after 341c)
1. The gate's SIT relation: `_sit_plan` (`orchestrator.py` ~:2385), `_sit_related_files` (~:2434), `BranchDiff` / briefs-only (~:4714-4762), `run_pre_merge_gates` order; 341c's related-unit computation (ORCH-UNIT-RELATED-1: function name, its `unit_full_triggers` / `unit_full_every` / uncomputable fallbacks).
2. The executor prompt: `orchestrator.py:1053` (`"Read {brief_rel} and execute all briefs in order. …"`) and where the brief file is copied/committed into the route branch before Toni starts.
3. Dependencies: `canon_assert._landed` (:508-541, three detectors), `route_merged` (:544), `prefire.parse_depends_on`, `prefire.dependency_status` (:453), A11 in `prefire.py` (~:835, :883), `queue_daemon._next_brief` (~:1077, read only) and `_hold_depends_on`.
4. The existing tests for each (`tests/` — list the files that cover the SIT plan, the unit related set, the executor prompt, `_landed`/`route_merged`, A11, D4).

## Brief 1: ORCH-EXEC-PREFLIGHT-1 — the executor runs the gate's own related set before handing back
- **F1.1** New subcommand `python3 orchestrator.py preflight --repo <name> [--json <path>]`, run from inside a route worktree: computes the branch diff against its merge base exactly as the gate does (`BranchDiff`), then the gate's SIT related set (`_sit_plan` + `_sit_related_files`) and 341c's related unit set, and runs both with the gate's own runners and config (same vitest configs, same isolation re-run of a failing SIT file, same environment-signal classification). Briefs-only diff ⇒ prints "briefs-only — nothing to run" and exits 0. Output: one summary line per leg (files, tests, failed with file:test names), JSON to `state/preflight/<branch>.json`; exit 0 only when both legs are green (a SIT failure the gate would class as environment is reported as such, exit 2).
- **F1.2** The executor prompt (`:1053`) gains one sentence when `ORCH_EXEC_PREFLIGHT` is not `off`: "Before you write the handback's final status, run `python3 ~/spectricom-orchestrator/orchestrator.py preflight --repo <repo>` and paste its summary; a red there is handled by your brief's rule #8 and STOP rules like any other red." The repo name is the brief's header `repo=`.
- **F1.3** No change to the gate: the merge still runs every leg itself (the preflight is advice to the executor, not evidence for the gate).
- **Predicates:** PB1 — on a fixture repo/branch whose diff reaches one SIT file and two unit files, `preflight` names exactly the files `run_pre_merge_gates` would run (same function results, asserted equal); PB2 — briefs-only diff ⇒ exit 0, "nothing to run"; PB3 — a failing SIT fixture ⇒ exit 1 and the failing file:test named; an environment-classed failure ⇒ exit 2; PB4 — the executor prompt contains the preflight sentence with the brief's repo, and omits it under `ORCH_EXEC_PREFLIGHT=off`.

## Brief 2: ORCH-PRELIST-1 — the brief Toni receives carries the gate's pre-list (supersedes Kanban 488)
- **F2.1** At fire, after prefire passes and before Toni starts, the orchestrator reads the brief's ALLOWED FILES sections (every `## <X>2 · ALLOWED FILES…` / `## ALLOWED FILES` section; the backticked `src|server|scripts|sit|tests|…` paths that exist, non-test), builds a synthetic diff of those paths, and computes the SIT related set and the related unit set with the same functions as Brief 1. It appends to the route's committed copy of the brief a block `## GATE PRE-LIST (generated at fire, <sha7>; D-S7CORE36-03)` listing each test file the gate would run for those paths that the brief does not already name, one line per file, followed by: "Each stays green unedited except under the brief's rule #8 lines (incl. D-S7CORE36-01 class (iii)); a red here is STOP (a) like any other." Files the brief names are not repeated. Under `ORCH_PRELIST=off`, or when the set cannot be computed, the brief is unchanged and the fire logs why.
- **F2.2** One owner of "the tests that reach a path set": Brief 1's preflight and this block call the same function (A13). The hand-made `RE-CHECK S7-CORE-36` blocks already in briefs stay as written (they are additive; duplicates are not re-listed).
- **Predicates:** PL1 — a fixture brief whose ALLOWED FILES name a module imported through an index file and mocked by `vi.mock` in a test elsewhere ⇒ that test is in the generated block (the class `341b3` and `341b5` missed); PL2 — a module whose rendered text a SIT locates (`getByPlaceholder`) and that the SIT plan relates ⇒ the SIT is in the block; PL3 — files the brief already names are not repeated; PL4 — `ORCH_PRELIST=off` ⇒ brief byte-identical; uncomputable ⇒ unchanged + log line.

## Brief 3: ORCH-DEPENDS-PRODUCT-1 — a Depends-on is met only by merged product files
- **F3.1** New `canon_assert.route_landed_product(repo, brief) -> Optional[tuple[str, str, str]]`: `_landed`'s answer, plus the files the route brought to the merge target (merge commit ⇒ diff against its first parent; reflog fast-forward or branch-ref detector ⇒ `merge-base(target-before, tip)..tip`); returns the landed tuple only when at least one changed path is outside `briefs/` (the gate's own briefs-only rule, D-S7CORE29-02 — call the same predicate, A13). Unreadable ⇒ None.
- **F3.2** `prefire.dependency_status` uses `route_landed_product` for "merged" when `ORCH_DEPENDS_PRODUCT` is not `off`; a dependency that landed handback-only is reported `merged handback only (briefs/) — not met` and is not "queued" (so D4 parks the dependent in `queue/held/depends-on/` through the existing `_hold_depends_on`, with that reason). B6 (`check_queue_trunk_invariants`) keeps using `route_merged` / `_landed` unchanged — a STOPPED route's brief is still retired.
- **F3.3** A re-fire that lands the work under a new stem satisfies only briefs that name that stem (no aliasing).
- **Predicates:** PD1 — fixture repo: route A merged with a product file ⇒ met; route B merged with only `briefs/B.handback.md` ⇒ not met, reason names "handback only"; route C fast-forwarded with product ⇒ met; PD2 — D4 on a queue where X depends on B (handback-only) ⇒ X parked in `held/depends-on/` with the reason, the next eligible brief taken; PD3 — B6 still retires B's brief; PD4 — `ORCH_DEPENDS_PRODUCT=off` ⇒ today's answers on every fixture.

## ALLOWED FILES
`orchestrator.py` (the `preflight` subcommand, the shared "tests that reach a path set" function, the executor-prompt sentence, the pre-list block at fire), `canon_assert.py` (`route_landed_product` only), `prefire.py` (`dependency_status`'s merged judgement and its reason text only), `config/repos.yaml` (only if a new key is unavoidable — name it), new tests under `tests/` (`test_exec_preflight.py`, `test_prelist.py`, `test_depends_product.py`), the existing tests named in §0.4 only where an exact executor-prompt string or a dependency-reason string is pinned (rule #8 below), `briefs/341a2-orch-reliability-1.handback.md`. NOT `queue_daemon.py`.

**Rule #8 line — George go 2026-10-28 11:13:** a test that pins the exact executor prompt text or the exact `dependency_status` reason strings may change only to include the new sentence / the new "handback only" reason; every other assertion unchanged; old/new text in the handback.

## HANDBACK / GATES
Handback per brief: §0 pastes, as built (file:line), predicate RED→GREEN, rule #8 old/new, R-items; state plainly that Brief 3 needs the queue daemon restarted (Gemma, quiet window) and that Briefs 1–2 take effect on the next fire. Gates (targeted): `venv/bin/python -m pytest tests/test_exec_preflight.py tests/test_prelist.py tests/test_depends_product.py` plus every test file §0.4 lists, `python3 -m py_compile orchestrator.py canon_assert.py prefire.py` — never the full suite.

## STOP
(a) a change that lets a route merge with fewer checks than today, or a gate leg skipped/replaced by the preflight; (b) a preflight or pre-list set that differs from what `run_pre_merge_gates` computes for the same diff; (c) a part that needs `queue_daemon.py` edited or a daemon restart by the executor; (d) any LLM/Toni judgement in a set, a pre-list or a dependency decision; (e) B6 retirement behaviour changed.

## Closes capability advancement: none (pipeline reliability, D-S7CORE36-03)
## Gates journey: orchestrator — fire → executor preflight → gate → merge; depends-on hold
