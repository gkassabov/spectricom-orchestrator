# filename: briefs/341a2-orch-reliability-1.handback.md
# Handback — 341a2-orch-reliability-1 (ORCH-RELIABILITY-1, S7-CORE-36, D-S7CORE36-03)

**Status: all three briefs are DONE and committed, one commit each. No daemon restart was done.**

| Brief | Commit | Predicates RED → GREEN |
|---|---|---|
| 1 · ORCH-EXEC-PREFLIGHT-1 | `3329843` | RED at `1388d18`: 10 failed, 1 passed → GREEN: 11 passed |
| 2 · ORCH-PRELIST-1 | `034b35f` | RED at `3329843`: 11 failed → GREEN: 11 passed |
| 3 · ORCH-DEPENDS-PRODUCT-1 | `0158139` | RED at `034b35f`: 11 failed, 1 passed → GREEN: 12 passed |

The one test that passes on HEAD in each RED run is a control by design. In Brief 1 it is `ORCH_EXEC_PREFLIGHT=off` (the sentence is absent). In Brief 3 it is PD3 (B6 already retires the brief).

**Gates (targeted, never the full suite):** `py_compile orchestrator.py canon_assert.py prefire.py` passed. The run covered 31 files: the 3 new ones, every §0.4 file, and the fire-lane files that Briefs 1–2 reach. Result: **1395 passed**, 0 failed.
```
venv/bin/python -m pytest tests/test_exec_preflight.py tests/test_prelist.py tests/test_depends_product.py \
  tests/test_sit_rate_limit.py tests/test_gate_cost.py tests/test_sit_enum_parallel.py tests/test_sit_isolation_attributed.py \
  tests/test_sit_integration.py tests/test_unit_related.py tests/test_unit_baseline_gate.py tests/test_foreground.py \
  tests/test_toni_guards.py tests/test_route_landed.py tests/test_queue_retire.py tests/test_canon_assert.py tests/test_prefire.py \
  tests/test_depends_on.py tests/test_merge_conflict.py tests/test_route_ref_integrity.py tests/test_yorsie_safety.py \
  tests/test_control_scope.py tests/test_regate_gates_only.py tests/test_handback_guard.py tests/test_baseline_reuse_1.py \
  tests/test_capacity.py tests/test_stale_base.py tests/test_timeout_hold.py tests/test_bg_ceiling.py \
  tests/test_control_verdict_lines.py tests/test_gate_collection.py tests/test_executor_default.py   → 1395 passed
```

**When it takes effect:**
- **Briefs 1–2** take effect on the **next fire**. They live in `orchestrator.py`, which each route runs as a fresh process.
- **Brief 3** is split:
  - A11, the prefire refusal, runs inside that same fresh process, so it also applies from the next fire.
  - **D4** (`queue_daemon._next_brief`, where a dependent is parked in `held/depends-on/`) runs inside the long-lived queue daemon, which has the old `prefire.py`/`canon_assert.py` imported. **The queue daemon must be restarted (Gemma, in a quiet window, after merge) for D4 to use the new rule.** I did not restart it.

---

## §0 · FIRST STEP — as built at HEAD (file:line after this batch)

**1. The gate's SIT relation and the unit related set**
- `_sit_plan` is at `orchestrator.py:2402`, `_sit_related_files` at `:2451`, `BranchDiff` at `:5119` and `_branch_diff` at `:5142`.
- The briefs-only rule is inside `run_pre_merge_gates` (`:5180`), at `:5198`: `diff.paths and all(_under_subdir(p, briefs) …)`.
- Order is briefs-only → env file → build (the SIT enumeration worker starts beside it) → SIT → unit.
- The SIT verdict is now `_sit_gate_verdict` (`:5160`), extracted from the gate with no change.
- 341c's related unit set (ORCH-UNIT-RELATED-1) is `_unit_scope` at `:4510`. Its enumeration is now `_unit_related_files` (`:4560`), also extracted with no change.
- The full-suite fallbacks:
  - (a) `UNIT_FULL_TRIGGERS_KEY` (`:4401`, default `UNIT_FULL_TRIGGERS_DEFAULT`)
  - (b) `UNIT_FULL_EVERY_KEY` (`:4404`), `UNIT_FULL_EVERY` = 5, with the counter in `state/unit-full-counter-<repo>.json`
  - (c) the related set is uncomputable, or empty while non-test source changed
  - (d) `ORCH_UNIT_RELATED=off`

**2. The executor prompt and the brief copy**
- `fire_toni` is at `orchestrator.py:1041`. The prompt literal is at `:1063`, and the new `preflight_ask` at `:1055`.
- The brief is **copied, not committed**, into the route checkout at `_run_batch_inner` `:6479` (`target.write_bytes(batch_file.read_bytes())`). It stays untracked until the route's commit.
- Toni reads that copy. The pre-list is appended to it at `:6554`, after the branch is cut and before `capture_handoff` / `fire_toni`.

**3. Dependencies**
- In `canon_assert.py`:
  - `_landed` is at `:508`, with its three detectors (merge commit, target reflog, branch ref).
  - `route_merged` is at `:544`.
  - `route_landed_product` is new, at `:589`. `under_subdir` (`:556`) and `_landed_paths` (`:564`) are also new.
  - B6 (`check_queue_trunk_invariants`) is at `:627`. It still asks `route_merged` and is unchanged.
- In `prefire.py`:
  - `parse_depends_on` is at `:432` and `dependency_status` at `:482`. It now asks `route_landed_product` at `:504`.
  - A11 is at `:877`, with the new ⛔ line at `:884`. The pass line is at `:932`.
- In `queue_daemon.py`, read only and **not edited**: `_next_brief` is at `:1075` (it calls `prefire.dependency_status` at `:1090`), and `_hold_depends_on` is at `:1113`.

**4. Existing tests for each area**
- SIT plan / related set: `test_sit_rate_limit.py`, `test_gate_cost.py` (P3), `test_sit_enum_parallel.py`, `test_sit_isolation_attributed.py`, `test_sit_integration.py`
- Unit related set: `test_unit_related.py`, `test_unit_baseline_gate.py`
- Executor prompt: `test_foreground.py`, `test_toni_guards.py`
- `_landed` / `route_merged`: `test_route_landed.py`, `test_queue_retire.py`, `test_canon_assert.py`
- A11 / D4: `test_prefire.py`, `test_depends_on.py`

---

## Brief 1 · ORCH-EXEC-PREFLIGHT-1 — `3329843`

**As built**
- **`tests_reaching(repo_path, diff) -> PathReach`** (`orchestrator.py:5328`) is the single owner of "the tests that reach a path set" (A13).
  - SIT: it runs the gate's own `_SitEnumJob._run()` in place. These are exactly the gate's `_sit_plan` and `_sit_related_files` calls. If the repo's `PRE_MERGE_GATES` has no SIT leg, the SIT set is `()`.
  - Unit: it uses `_unit_scope`. When the gate would run the full suite for (a)–(d), it still records the related set from `_unit_related_files`, and stores the reason in `unit_full`.
- **`preflight(repo_path, json_path)`** (`:5425`) and **`orchestrator.py preflight --repo <name> [--json <path>]`** (CLI `:7504`, added to `REPO_CMDS`) work as follows:
  - Scope: the checkout's top level and HEAD branch.
  - Diff: `_branch_diff`.
  - A briefs-only diff prints `briefs-only — nothing to run` and exits 0.
  - SIT: `run_sit_post_merge(…, enumerated=<that job>)`, the gate's runner with its batching and isolation. Its archive is `state/preflight/sit-archive`, so the gate's SIT log is never written. The verdict comes from `_sit_gate_verdict`, the gate's own classification.
  - Unit: the gate's branch leg (`_run_unit_suite(_unit_confirm_cmd(...))`), then `_unit_confirm_new_files` re-runs any failing file alone.
  - Output: one line per leg (files, why, `failed: file > test`), then `🧪 Preflight (executor): <n> SIT files / <m> unit files — pass|fail (<kind>)`. It also warns when there are uncommitted files outside `briefs/`.
  - JSON goes to `state/preflight/<branch>.json`.
  - Exit codes: 0 green, 1 fail, 2 environment, 3 not computed. The worst leg wins.
- **Prompt (F1.2):** `PREFLIGHT_SENTENCE` is appended unless `ORCH_EXEC_PREFLIGHT=off`. The repo comes from `parse_repo_from_brief` (the `#!queue repo=` line), otherwise `ACTIVE_REPO_NAME`. The backticks are escaped as `` \` `` because the prompt is a double-quoted bash word, and an unescaped backtick would run the preflight at fire time. PB4 checks the argv the child actually receives.
- **F1.3:** the gate is unchanged. The two extractions (`_unit_related_files`, `_sit_gate_verdict`) move code without changing behaviour, and the gate's tests are unchanged and green.

**Predicates**
- PB1: the preflight hands the runners exactly the gate's files, `[[F2]]` for SIT and `[[U1, U2]]` for unit. A separate test asserts `tests_reaching` equals `_sit_related_files` / `_unit_scope.files`.
- PB2: briefs-only exits 0, prints "nothing to run", and invokes nothing.
- PB3: a SIT file that fails in its batch and alone exits 1 and names `sit/integration/f2… > case 1`. A file that passes alone counts as green, as the gate reads it. An `ECONNREFUSED 127.0.0.1:8103` red exits 2.
- PB4: the sentence carries the header's repo (and the active repo when there is no header), and is absent under `off`.
- Two extra cases:
  - On a shared trigger, the preflight runs the related set and says the gate runs the full suite.
  - With no `sit_list_cmd`, it exits 3 and never runs the full suite.

**Rule #8 (prompt pins only include the new sentence; every other assertion is unchanged)**
- `tests/test_toni_guards.py`, `head_cmd`:
  - old: `def head_cmd(project, brief_rel, model, effort)` … `f'"Read {brief_rel}{PROMPT_TAIL}"'`
  - new: `def head_cmd(project, brief_rel, model, effort, repo="clinical-mp")` … `ask = PREFLIGHT.format(repo=repo).replace("`", "\\`")` … `f'"Read {brief_rel}{PROMPT_TAIL}{ask}"'`. A new module constant `PREFLIGHT` holds the sentence.
- `tests/test_toni_guards.py`, argv pin:
  - old: `got["argv"][-1] == "Read briefs/394-x.md" + PROMPT_TAIL`
  - new: `got["argv"][-1] == ("Read briefs/394-x.md" + PROMPT_TAIL + PREFLIGHT.format(repo="orchestrator"))`
- `tests/test_foreground.py`, source guard:
  - old: `cmds[0].endswith(' "Read {}' + PROMPT_TAIL + '"')`
  - new: `cmds[0].endswith(' "Read {}' + PROMPT_TAIL + '{}"')`

**Live check:** I ran `orchestrator.py preflight --repo orchestrator` in this worktree. The SIT leg reported "0 files, gate has no SIT leg". The unit leg reported "not computed — `pytest -q tests/` is not a vitest run". The command exited 3 and ran nothing (see R1).

## Brief 2 · ORCH-PRELIST-1 — `034b35f`

**As built**
- **`brief_allowed_paths`** (`:5505`) reads every `## ALLOWED FILES…` and `## <X>2 · ALLOWED FILES…` section, up to the next `#`/`##` heading. It keeps backticked tokens, drops a `:line` suffix, and accepts only files that exist, are not test files, and are not under `briefs_subdir`.
- **`_prelist_reach`** (`:5520`) builds a detached worktree at the route's HEAD and links the dependency trees into it. It appends `\n` to each path, uncommitted, so `list --changed <HEAD>` reads them as changed. It then calls `tests_reaching` on `BranchDiff(base=HEAD, paths=<allowed>)`. The worktree is removed afterwards (links first).
- **`gate_prelist`** (`:5544`) appends to the route's copy:
  - `## GATE PRE-LIST (generated at fire, <sha7>; D-S7CORE36-03)`
  - one `` - `<file>` (SIT|unit) `` line per file the brief does not name
  - the rule sentence
- If every file is already named, the block says "(none beyond the test files this brief already names)".
- It logs `📋 Gate pre-list generated: <n> SIT + <m> unit files for <k> allowed files at <sha7>`. When `ORCH_PRELIST=off`, when nothing is computable, or on any exception, it leaves the brief untouched and logs `📋 Gate pre-list not generated: <why>`. It never raises.
- A fix inside Brief 2: when nothing related but source changed, `tests_reaching` used to treat the unit set as "not computed". It now keeps the computed related set (possibly empty) and records the gate's full-suite reason in `unit_full`. Only a set that truly cannot be computed is `None`.

**Predicates**
- PL1: the brief allows `src/lib/llm/provider.ts`, which reaches `src/feature/chat.test.ts` through `index.ts` and `vi.mock`. The scripted `--changed` answers from the real `git status` of its own cwd, so it is the synthetic diff that decides. The test file is in the block.
- PL2: the brief allows `SearchPage.tsx`, and the SIT file that locates its text is in the block.
- PL3: a file named elsewhere in the brief (the RE-CHECK shape), or named by basename, is not repeated.
- PL4: `off` leaves the brief byte-identical. An uncomputable set, or no allowed file, leaves it unchanged with exactly one log line.
- Extra checks:
  - The checkout is untouched and the temporary worktree is gone.
  - The set comes from `tests_reaching` (A13).
  - Both heading shapes are parsed.
  - An AST check confirms `gate_prelist` is called before `capture_handoff`, which is before `fire_toni`.

## Brief 3 · ORCH-DEPENDS-PRODUCT-1 — `0158139`

**As built**
- **`canon_assert.route_landed_product(repo, brief, briefs_subdir="briefs", why=None)`** returns `route_merged`'s tuple only when the route brought a path outside `briefs_subdir`. `_landed_paths` finds those paths by detector:
  - merge commit: `sha^1..sha`
  - target reflog: `merge-base(<the entry before it>, tip)..tip`
  - branch ref: `merge-base(<the branch's creation in its own reflog>, tip)..tip`
- An unreadable diff returns None. In that case `why` gets "merged …, but what it brought cannot be read", and the result is never called handback-only.
- **`prefire.dependency_status`:**
  - Unless `ORCH_DEPENDS_PRODUCT=off`, it asks `route_landed_product` and passes the repo's own `briefs_subdir` from repos.yaml (yorsie uses `yorsie/briefs`).
  - A route that landed but is unmet gets `Dependency.landed_unmet`. Its text is `<stem>: merged handback only (briefs/) — not met on <repo>/<target>`, and it is never `queued`. So D4's existing `_hold_depends_on` parks the dependent in `queue/held/depends-on/` with that reason.
  - A11 prints `⛔ Depends-on <stem>: merged handback only (briefs/) — not met` and fails with the same text.
- **B6 is unchanged:** it still calls `route_merged`.
- **F3.3 (no aliasing):** a re-fire stem satisfies only briefs that name that stem.

**Predicates**
- PD1:
  - A merge commit with product is met.
  - A merge commit with only `briefs/b.handback.md` is not met, the reason says "handback only", and A11 fails.
  - A fast-forward with product is met through the reflog.
  - A fast-forward that is handback-only is not met.
  - The branch-ref detector (with main's reflog expired) is met for product and not met for handback-only.
  - With every reflog expired, the result is "cannot be read" and not met.
  - The repo's own `briefs_subdir` is respected.
- PD2: X depends on handback-only B, with B's brief either in `done/` or still in `queue/`. X is parked in `held/depends-on/` with the reason, and the next brief is taken.
- PD3: B6 still retires B's brief.
- PD4: under `off`, every fixture gives `route_merged`'s answer, and A11 passes.
- F3.3: covered as above.

**Beyond the literal ALLOWED text — please review (STOP (m)-style flags)**
1. **`tests/test_depends_on.py:409`** pins a substring, which is not covered by rule #8.
   - old: `assert "canon_assert.route_merged(" in pf and "subprocess" not in pf and "_landed" not in pf`
   - new: `… and "_landed(" not in pf`
   - Why: the name the brief mandates, `route_landed_product`, contains `_landed`, so the old assertion cannot hold under F3.1.
   - The pin's intent still holds: prefire never calls `_landed(` and reads no git. Line 413 (`"_landed(" not in qd and "_landed(" not in pf`) was already in that form.
2. **canon_assert has more than "`route_landed_product` only".**
   - `_landed_paths` is its private helper.
   - `under_subdir` is the gate's briefs-only predicate, **moved** out of `orchestrator.py`. F3.1 says "call the same predicate (A13)", but canon_assert cannot import orchestrator (that would be circular, and the daemon must not load it).
   - `orchestrator.py:61` now has `from canon_assert import under_subdir as _under_subdir`. All 8 call sites are unchanged. The removed definition was identical.
   - `route_landed_product` also takes two optional parameters (`briefs_subdir`, `why`). The two-argument call is the specified signature.

---

## R-items (found, not changed)
- **R1 — the preflight on pytest repos always exits 3.** For orchestrator and ai-foundation (`test_cmd` is pytest), the unit related set cannot be computed, so the preflight reports "not computed" every time. Per the brief's failure mode, the executor reports that as a red. Every fire there will carry one, which is noise for meta-fires. Options for George/Gemma: add the sentence only on repos with a related selection, or give pytest repos a related set. I did not change this, because F1.2 says to add the sentence whenever it is not `off`.
- **R2 — the preflight's unit leg does not measure the merge base.** It reports a file that fails alone as `fail`, with a note. The gate would call that file a regression only if it is also green at the merge base, so the preflight can be redder than the gate (it errs toward caution). The SIT leg is the gate's own runner and verdict.
- **R3 — the preflight never runs a full suite** (test-scope rule). When the gate would run the full unit suite (a trigger, the 5th route, (c), or `off`), the preflight runs the related set and says the gate runs full. An uncomputable SIT set exits 3 without running anything. A SIT `timeout-advisory`, which the gate lets pass, is reported as environment (exit 2).
- **R4 — the pre-list's cost at fire is not measured live.** On clinical-mp it adds four `vitest list` runs in a temporary worktree. The "already named" rule also counts a basename match, so a brief that mentions only the basename of a different file with the same name would suppress that line.
- **R5 — the pre-list is appended only to a route copy.** When the queued brief is itself the file in the route checkout (no copy made), it is left alone and logged.
- **R6 — Brief 3's D4 effect needs the queue daemon restarted** (see the top of this handback). Briefs 1–2 and A11 apply from the next fire.
