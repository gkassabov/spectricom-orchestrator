# Toni execution brief — S7-CORE-4 · orchestrator gate-then-merge

## Repo: orchestrator

| Field | Value |
|---|---|
| Batch ID | `toni-batch-s7core4-orch1-gate-then-merge-01` |
| Repo | `orchestrator` (`~/spectricom-orchestrator`) |
| Brief count | **1** (BRIEF 1 of 1 = `[ORCH-1]`) |
| Estimated runtime | **~25 min** · declared timeout `TONI_TIMEOUT_MIN=45` |
| Verified baseline | `0b59820` — working tree clean (0 dirty) · `HEAD == origin/main == 0b59820` · branch `main` |
| Fire class | **meta-fire** — the orchestrator modifies its own repo (see §M) |
| Authored | 2026-09-09 (S7-CORE-4) · Classification: PROPOSAL — grants no execution by itself |
| Executor profile | Claude Code via `orchestrator.py run … --repo orchestrator`, model/effort from `TONI_MODEL` / `TONI_EFFORT`, `ANTHROPIC_API_KEY` unset (CODE-GUARD) |
| Revision | **rev3** — closes all 4 typed gaps from rev2 (meta-fire worktree path/branch template; PDLC F-20 environment-vs-product signal list; test-suite correction — `test_cmd` was stale, real `tests/` suite of 7 files is the owning SIT spec; no-lint-config finding). Batch ID and filename subject unchanged from rev2. |

**Change note (rev3):** Four typed-gap markers from rev2 are closed with facts verified live on the repo: (1) §M worktree/branch path — single-stream mode runs no worktree; (2) new `PDLC F-20` subsection defining `BLOCKED(environment)` vs `FAIL(product)` signals; (3) **correction** — the anchors-table claim that the orchestrator repo "has no test suite" is wrong; it has a 7-file pytest suite that is now the owning SIT spec, with new acceptance item AC-ORCH1-09 requiring `test_cmd`/`build_gate_cmd` fixes and a before/after run; (4) §V lint entry point — confirmed no lint config exists, `py_compile` + the pytest suite stand in for it. No other section was touched.

# Rule: Verify with build + lint after all briefs complete. Do NOT run Playwright E2E tests during batch execution.

**Locks (apply to the whole brief)**
1. Do **not** weaken, bypass or add any flag that skips the SIT gate. The bypass environment variables that already exist (`DISABLE_BUILD_GATE`, `DISABLE_SIT_BLOCKING`) are **pre-existing operator escapes** — they must keep working exactly as they do today, and **no new** bypass of any kind may be introduced, and none may be invoked by this work.
2. Do **not** change the CODE-GUARD that exits `3` when `ANTHROPIC_API_KEY` is set. It stays exactly as it is.
3. Secrets never reach logs or stdout — no `cat .env`, no `echo "$MEDPLUM_CLIENT_ID"`, no unmasked `grep` of `.env`, no `set -x` around the sourcing block (canon §23.9d).
4. Read the repo before you edit it. The anchors named in this brief (below) are verified; do **not** invent additional function names or line numbers. Where something else is needed, find it in `orchestrator.py` yourself and report what you found.
5. Editable files: `orchestrator.py` and `config/repos.yaml` (the latter only for acceptance item 3). If the change genuinely requires touching any other file, **STOP AND REPORT** with the file and the reason before editing it.

### Grounded code anchors (verified on the repo at `0b59820` — use these, do not invent others)

| Anchor | What it is |
|---|---|
| `orchestrator.py::run_build_gate(repo_path)` | The build gate. Command comes from `ACTIVE_REPO_CONFIG.get("build_gate_cmd", BUILD_GATE_CMD)`; module default `BUILD_GATE_CMD = "npx tsc --noEmit && npm run build"`. Bypass env `DISABLE_BUILD_GATE`. |
| `orchestrator.py::run_sit_post_merge(repo_path, archive_path)` | The SIT gate. Applies the MANY-or-SEVERE halt rule. Bypass env `DISABLE_SIT_BLOCKING`. Module flag `SIT_BLOCKING`. |
| `orchestrator.py::_run_batch_inner` — **~lines 1247–1272** | Where the merge happens: `git merge {branch_name} --no-edit`, with a `pre_merge_tip` / `post_merge_tip` comparison. |
| `orchestrator.py::_run_batch_inner` — **~line 1275+** | Where the post-merge gates are invoked, immediately after the merge. **This is the ordering defect.** |
| `orchestrator.py::merge_branch(br)` | Plain merge helper. |
| `orchestrator.py::_self_mod_auto_merge(orch_dir, branch_name)` | The meta-fire path for the orchestrator repo itself. Merges `--ff-only`; **preserves the branch on failure.** |
| `config/repos.yaml` → `orchestrator` | `branch_prefix: orch-orch` · `worktree_mode: single-stream` · `meta_fire: true` · `merge_target: main` · `test_cmd: "pytest 2>/dev/null || echo 'orchestrator has no test suite yet'"`. **There is no `build_gate_cmd` for the orchestrator repo and the orchestrator repo has no test suite.** Do not invent gates for it. |

Note the naming: `run_sit_post_merge` is named for the behaviour this brief is changing. Renaming it is **optional** and, if done, must be a mechanical rename with every call site updated in the same commit — report it either way.

---

## §P. Pre-fire branch-state assertion (George runs this BEFORE the fire; not a Toni step)

Run in `~/spectricom-orchestrator` and require all three to be true:

```
git status --porcelain            # MUST be empty
git rev-parse HEAD                # MUST equal git rev-parse origin/main, and MUST be 0b59820…
git rev-parse --abbrev-ref HEAD   # MUST be "main"
```

Assertion contract: **working tree clean · HEAD == origin/main == `0b59820` · branch == main**.

**Verified 2026-09-09:** the repo is at **0 dirty files**, `HEAD == origin/main == 0b59820` (the merged `[MODEL-1]` model/effort CLI-flag commit, pushed), branch `main`. **The §23.1 pre-fire assertion passes as written** — no waiver, no disposition, no flag outstanding. Re-run the three commands immediately before firing to confirm nothing has drifted since.

Also assert no live route: `running.json` absent and `ps` shows no orchestrator run (Kanban §3). The Kanban row's READY? must read `yes` before fire (System Prompt §23.1 pre-fire assertion, control candidate F-15).

---

## §M. Meta-fire — orchestrator self-modification uses the git-worktree pattern

This brief edits the orchestrator **with the orchestrator**. The run is fired with `--repo orchestrator`, which is the meta-fire lane: `config/repos.yaml` sets `meta_fire: true`, `worktree_mode: single-stream` and `branch_prefix: orch-orch`, so the route branch is materialised in a **git worktree** and the merge-back is handled by `_self_mod_auto_merge(orch_dir, branch_name)` — which merges **`--ff-only`** and **preserves the branch on failure** — rather than by the ordinary `_run_batch_inner` merge at ~1247–1272. Consequences Toni must respect:

- Work only inside the worktree checkout the orchestrator hands you. Do not `cd` to the main checkout, and do not restart or re-exec the orchestrator process from inside the route.
- **`_self_mod_auto_merge` is a second merge path and it is in scope.** The gate-before-merge guarantee is worthless if the meta-fire lane still merges unconditionally. Toni must read `_self_mod_auto_merge` and either (a) route it through the same pre-merge gate decision as `_run_batch_inner`, or (b) if the orchestrator repo genuinely has no gate to run (see the anchors table: no `build_gate_cmd`, no test suite), make that **explicit in the code and in the return** — a stated, deliberate no-gate lane, not an accidental one. Do not silently leave it unconditional.
- A change to gate/merge ordering does **not** take effect for the run that is making the change. It takes effect on the **next** fire. Do not attempt to prove this brief by observing this run's own merge.
- Verification is therefore done by **reading back the changed source** and by the observable criteria below — not by watching this run's own lifecycle.
- **Worktree path and branch template (verified on the repo).** The orchestrator repo runs `worktree_mode: single-stream`, so **no git worktree is created for this run** — `WORKTREE_BASE` is set and used only when `worktree_mode == "parallel"` (the yorsie lane); in single-stream mode it is unused. For reference, a parallel-mode worktree is created at `WORKTREE_BASE / f"toni-{wid}"` via `git worktree add`. This meta-fire's self-modification path is `_self_mod_auto_merge(ORCH_DIR, branch_name)`, where `ORCH_DIR = Path(__file__).parent.resolve()` — the orchestrator's own checkout, not a worktree. Branches use `branch_prefix: orch-orch` from `config/repos.yaml`, and the merge is `git -C {orch_dir} merge --ff-only {branch_name}`, with the branch preserved on a non-ff-only failure. Toni: confirm this against the source and report the exact branch name actually used for this run in the return.

---

# BRIEF 1 of 1 — [ORCH-1] gate-then-merge + `.env` sourcing + dead `fire_command_template` (P0)

**Work type:** IMPLEMENTATION (control-flow) + OPERATIONS (environment) + CONFIG HYGIENE · **Priority:** P0 · **Est. 25 min**

## Why (grounded incident)

On **2026-09-09** the orchestrator merged the route branch to `main` and **then** ran the gate. The gate came back **RED** — and `main` had already taken the merge. A red `sit:gate` landed on `main`. The structure of `_run_batch_inner` matches the incident exactly: the merge is at ~1247–1272 and the gates (`run_build_gate`, `run_sit_post_merge`) are invoked at ~1275+, i.e. **after**. Two distinct root causes were observed in that same return:

1. **Ordering:** merge-then-gate. PDLC (Operating Model §12.4 / §15) wants the gate **before** adoption.
2. **Environment:** the orchestrator shell does not source the repo `.env`, so the gate failed for environment reasons — `ECONNREFUSED 127.0.0.1:8103` (Medplum down) and a harness throw of "requires `MEDPLUM_CLIENT_ID`" while that variable **is** present in `.env` but not in the orchestrator's shell. The batch was then reported as `FAILED`, which is wrong: that was an environment block, not a product failure.

## What this brief delivers

1. **Gate before merge.** `run_build_gate(repo_path)` **and** `run_sit_post_merge(repo_path, archive_path)` run **on the `orch-*` route branch**, **before** the `git merge {branch_name} --no-edit` at ~1247–1272 — not at ~1275+ after it.
2. **Red gate ⇒ no merge.** A red gate leaves the route branch **unmerged**, intact, and available for review; the orchestrator reports the red result and exits without touching `main`. The existing `pre_merge_tip` / `post_merge_tip` comparison stays as the merge-happened witness; on a red gate neither is reached and `main`'s tip is unchanged.
3. **Green gate ⇒ merge proceeds** exactly as it does today (no other change to merge behaviour). `merge_branch(br)` and the `--ff-only` semantics of `_self_mod_auto_merge` are unchanged.
4. **`.env` sourcing.** Before invoking either gate, the orchestrator sources the gated repo's `.env` with exactly:
   ```
   set -a; . ./.env; set +a
   ```
   sourced from the repo root of the repo being gated (cwd = `repo_path`). **No value is ever printed** (canon §23.9d). Handle a missing `.env` explicitly (see the taxonomy below) rather than letting the sourcing line abort the run.
5. **Three-way outcome taxonomy.** The result reported by the orchestrator distinguishes:

| Outcome | Meaning | Merge? | Reported as |
|---|---|---|---|
| `PASS` | both gates green on the route branch | **yes** | batch success |
| `BLOCKED(environment)` | the gate could not render a product verdict because the environment was not there — e.g. Medplum at `http://localhost:8103` not answering (`ECONNREFUSED 127.0.0.1:8103`), `.env` absent or unsourced, a required env var missing from the shell | **no** | **BLOCKED(environment)**, distinct from FAIL; branch left unmerged for review |
| `FAIL(product)` | the gate ran with its environment satisfied and the product did not pass (including the MANY-or-SEVERE halt rule in `run_sit_post_merge`) | **no** | **FAIL(product)**; branch left unmerged for review |

`BLOCKED(environment)` and `FAIL(product)` are **different outcomes** and must be **separately reported** — in the orchestrator's console output, in its per-run log, and in whatever run-status/ledger field the orchestrator already writes. Never collapse them into one `FAILED`. That collapse is the exact defect from 2026-09-09.

6. **Dead `fire_command_template` config resolved.** `config/repos.yaml` declares `fire_command_template:` for **6 repos**, each hard-coding `--model claude-opus-4-8` (collateral says `claude-fable-5`). `orchestrator.py:158` reads this key into `FIRE_TEMPLATE` and **nothing ever consumes it**. It is dead config, and it is actively misleading: it reads authoritative and it contradicts the live `TONI_MODEL` / `TONI_EFFORT` defaults that actually select the executor. Toni must resolve it **one way, applied consistently to all 6 repos**, choosing between:
   - **(a) delete** the `fire_command_template:` key from all 6 repo entries, **or**
   - **(b) keep** it and add, on **each** of the 6, the explicit comment:
     ```
     # DEAD CONFIG — not consumed; executor model comes from TONI_MODEL/TONI_EFFORT in orchestrator.py
     ```

   Toni proposes one, applies it consistently across all 6, and **reports which option it chose and why** in the return. Do not do (a) on some repos and (b) on others. Before choosing (a), re-confirm by grep that `FIRE_TEMPLATE` has no consumer anywhere in the repo, and paste that grep in the return; if a consumer **does** exist, **STOP AND REPORT** — the key is not dead and this item is void.

## What this brief does NOT deliver

- No new skip/bypass flag of any kind. `DISABLE_BUILD_GATE` and `DISABLE_SIT_BLOCKING` are pre-existing and stay exactly as they are; nothing new is added and neither is invoked by this work.
- No change to the CODE-GUARD (`ANTHROPIC_API_KEY` set ⇒ exit 3).
- No change to the gate scripts themselves in the target repos, and no change to `BUILD_GATE_CMD`'s default value or to any repo's `build_gate_cmd`. This brief changes **when** and **with what environment** the orchestrator invokes the gates, not what they do.
- No new gate for the orchestrator repo itself. It has no `build_gate_cmd` and no test suite; `test_cmd` is `pytest 2>/dev/null || echo 'orchestrator has no test suite yet'`. Do not invent one, do not add one, do not pretend one ran.
- No auto-retry, no auto-start of Medplum/Docker, no auto-repair of `.env`. `BLOCKED(environment)` reports and stops; bringing Medplum up is George's action (Kanban §5).
- No change to the model/effort CLI flags landed in `0b59820` — that work is done and merged.
- No Playwright E2E runs during batch execution (rule line above).

## How to work it

1. Read `_run_batch_inner` across ~1247–1300, and read `run_build_gate`, `run_sit_post_merge`, `merge_branch` and `_self_mod_auto_merge` in full. Quote the pre-change merge line and the pre-change gate-invocation lines verbatim with their line numbers in the return — that is the baseline.
2. Move both gate invocations **above** the `git merge {branch_name} --no-edit` step, with the route branch checked out, and make the merge step conditional on `PASS`. Keep `pre_merge_tip` / `post_merge_tip` doing what they do today for the merge that still happens.
3. Add the `.env` sourcing immediately before the gate invocations, in the shell that actually runs them, cwd = the gated repo's root. Secrets-silent (lock 3).
4. Implement the three-way classifier. Ground `BLOCKED(environment)` detection at minimum on the two signals actually observed on 2026-09-09: connection refused to `127.0.0.1:8103` / `localhost:8103`, and a missing-required-env-var throw naming a variable that exists in `.env`. Also classify "`.env` file not found" as `BLOCKED(environment)`.

   #### Environment-BLOCKED vs product-FAIL signal list (PDLC F-20 — first instance)

   No canonical list for this distinction exists elsewhere in Spectricom canon; this brief **defines** it, filed as PDLC learning-record item **F-20**:

   - **`BLOCKED(environment)`** — the gate did not evaluate the product because the environment was not there. Signals: Medplum (`http://localhost:8103`) unreachable; Docker not running; `.env` not sourced (a required key absent from the gate shell's environment); a required port already bound; a network/DNS failure reaching a dependency; a missing toolchain binary.
   - **`FAIL(product)`** — the gate evaluated the product and the product is wrong. Signals: test assertion failures; `tsc`/type errors; build errors; lint count above the recorded baseline; a SIT spec failing on an assertion rather than on setup.
   - **Rule:** `BLOCKED(environment)` must **not** be reported as a product failure, must **not** merge, and must be reported with the specific signal that triggered it.

   Implement this as a single clearly-marked table/constant in `orchestrator.py` so it can be extended without touching the control flow, and list in the return every signal actually implemented so George/Gemma can ratify or extend F-20. Do not invent additional signals silently.
5. Handle `_self_mod_auto_merge` per §M — gate it the same way, or make its no-gate status explicit and stated. Report which.
6. Leave the branch untouched on a non-PASS: no delete, no force-push, no rebase. Print the branch name and the exact command to inspect it.
7. Apply acceptance item 3 (`fire_command_template`) in `config/repos.yaml`, consistently across all 6 repos.

## Affected surface

*(SIT checklist for this brief is derived from this section.)*

- **Route lifecycle ordering in `_run_batch_inner`** — gate execution point (~1275+) moves above the merge (~1247–1272); the merge-to-`main` step becomes conditional.
- **`main` branch integrity** — the surface the incident damaged. After this change, `main` can only receive a merge behind a green gate.
- **Route branch lifecycle** — survival of the `orch-*` branch after a red gate (previously the failure path ran post-merge). `_self_mod_auto_merge` already preserves the branch on failure; that behaviour must be retained.
- **Meta-fire merge path (`_self_mod_auto_merge`, `--ff-only`)** — the second merge path; either gated or explicitly declared ungated.
- **Orchestrator shell environment** — a new sourcing step; risk surface = variables from `.env` now present in the gate subprocess that were not before, and the possibility of `.env` overriding a variable the orchestrator itself set (including `TONI_MODEL` / `TONI_EFFORT`).
- **Log / console / run-status output** — new `BLOCKED(environment)` outcome string; anything downstream that parses the orchestrator's outcome (ledger, Kanban runtime fields, George's fire logs) now sees a third value where it previously saw two.
- **Secret hygiene** — `.env` handling is now on the orchestrator's hot path; the surface to check is that no value appears in any log, console line or error trace.
- **`config/repos.yaml`** — 6 repo entries edited for the `fire_command_template` item; this file is read at startup by `orchestrator.py`, so a YAML syntax error breaks every repo, not just one.
- **Blast radius (report if touched):** any caller/consumer of the outcome value that assumes a binary success/fail. Toni: grep for consumers and report; **STOP AND REPORT** if changing them requires editing a file other than `orchestrator.py` / `config/repos.yaml`.

## SIT spec impact

**SIT spec impact:** the SIT spec gains a route-lifecycle lane — "gates run on the route branch before the merge; red gate ⇒ `main` unchanged and the branch preserved; environment block is reported as `BLOCKED(environment)`, never as `FAIL(product)`; the meta-fire `_self_mod_auto_merge` lane is either gated or explicitly declared ungated" — and the orchestrator's outcome vocabulary changes from two values to three, so every SIT step that asserts on the orchestrator's reported outcome must be updated to the three-way taxonomy. The `config/repos.yaml` hygiene item adds a config-truthfulness check: no unconsumed key may state an executor pin.

**⚠️ CORRECTION — the anchors table's `test_cmd` claim (line 35) is stale and wrong.** `config/repos.yaml` declares `test_cmd: "pytest 2>/dev/null || echo 'orchestrator has no test suite yet'"` for the orchestrator repo. That string is stale: the repo in fact has a `tests/` directory containing **7 pytest files** — `test_branch_sweep.py`, `test_empty_commit_guard.py`, `test_rate_limiter.py`, `test_running_marker.py`, `test_self_mod_auto_merge.py`, `test_sit_integration.py`, `test_timeout_resolution.py`. Two of these — **`test_self_mod_auto_merge.py`** and **`test_sit_integration.py`** — cover exactly the code this brief changes (the meta-fire merge path and the SIT gate). **This existing pytest suite is the owning SIT spec for this brief** — there is no separate SIT spec document to land this impact in; the suite itself is what Gemma/George ratify against, and it must be updated/extended in step with this brief's control-flow change.

## Acceptance criteria (observable)

- [ ] **AC-ORCH1-01 (observable — ordering, from source):** `cd ~/spectricom-orchestrator && grep -n "git merge\|run_build_gate\|run_sit_post_merge" orchestrator.py` prints line numbers for all three, and **within `_run_batch_inner` the `run_build_gate` and `run_sit_post_merge` call lines have LOWER line numbers than the `git merge {branch_name} --no-edit` line**. Return pastes the full command output verbatim, quotes each of those lines with its number, and states which branch is checked out at each point. Someone reading that output sees gate-then-merge, not merge-then-gate.
- [ ] **AC-ORCH1-02 (observable — red gate leaves `main` alone):** in a rehearsal where the gate is forced red (Medplum down is sufficient — that is the 2026-09-09 condition), running the orchestrator on a throwaway route branch prints `BLOCKED(environment)` **or** `FAIL(product)`, and `git rev-parse main` is **byte-identical before and after the run**, and `git branch --list 'orch-*'` still lists the route branch. Return shows both `rev-parse` outputs and the branch listing. Note: forcing red must be done by taking the environment away or by a genuinely failing product gate — **never** by setting `DISABLE_BUILD_GATE` or `DISABLE_SIT_BLOCKING`.
- [ ] **AC-ORCH1-03 (observable — `.env` is sourced, silently):** `grep -n "set -a" orchestrator.py` prints the sourcing line; and the run log for a gated run contains **zero** occurrences of any `.env` value — demonstrate with `grep -c "MEDPLUM_CLIENT_ID=" <run log>` → `0`, and confirm `grep -n "cat .*\.env" orchestrator.py` → no output. Return pastes all three commands and their outputs.
- [ ] **AC-ORCH1-04 (observable — taxonomy is distinguishable):** with Medplum **down**, the run's final status line reads `BLOCKED(environment)` and names the signal (e.g. `ECONNREFUSED 127.0.0.1:8103`). With Medplum **up** and a deliberately failing product gate, the final status line reads `FAIL(product)`. Return pastes both status lines. The two runs must not produce the same string.
- [ ] **AC-ORCH1-05 (observable — dead config resolved consistently):** `cd ~/spectricom-orchestrator && grep -n "fire_command_template\|claude-opus-4-8\|DEAD CONFIG" config/repos.yaml` — the output shows **either** zero `fire_command_template` lines and zero `claude-opus-4-8` occurrences (option a), **or** exactly 6 `fire_command_template` lines each immediately preceded by the `# DEAD CONFIG — not consumed; executor model comes from TONI_MODEL/TONI_EFFORT in orchestrator.py` comment (option b) — never a mixture. Return pastes the grep output, states which option was applied, and also pastes `grep -rn "FIRE_TEMPLATE" .` showing the key still has no consumer.
- [ ] **AC-ORCH1-06 (observable — no new skip path):** `grep -rniE -- "-{1,2}skip[-_]?sit" ~/spectricom-orchestrator` prints **no output**, before and after the change; and `git diff` shows **zero** changed lines touching `DISABLE_BUILD_GATE`, `DISABLE_SIT_BLOCKING` or `SIT_BLOCKING`. Return pastes the grep and its empty result, and states the diff is empty for those three names.
- [ ] **AC-ORCH1-07 (observable — CODE-GUARD intact):** `ANTHROPIC_API_KEY=x python3 orchestrator.py …; echo $?` prints **`3`**, unchanged, and `git diff` shows zero lines changed in the CODE-GUARD block. Return pastes the exit code.
- [ ] **AC-ORCH1-08 (observable — config still parses):** after the `config/repos.yaml` edit, `python3 -c "import yaml,sys; d=yaml.safe_load(open('config/repos.yaml')); print(sorted(d.keys()) if isinstance(d,dict) else type(d))"` prints the repo list without raising. Return pastes the output. A YAML break here takes down every repo.
- [ ] **AC-ORCH1-09 (observable — correct the stale `test_cmd` and run the owning suite; CORRECTION item):** Toni must (a) correct `test_cmd` for the orchestrator repo in `config/repos.yaml` from the stale `pytest 2>/dev/null || echo 'orchestrator has no test suite yet'` to a real invocation, `pytest -q`; (b) add a `build_gate_cmd` entry for the orchestrator repo; and (c) run the existing `tests/` suite (all 7 files, including `test_self_mod_auto_merge.py` and `test_sit_integration.py`) before and after this brief's change and report both pass/fail counts verbatim in the return.

## STOP AND REPORT triggers

- The change cannot be made inside `orchestrator.py` and `config/repos.yaml` alone.
- The merge step and the gate steps are not in the same control path such that "gate before merge" changes more than ordering.
- `run_sit_post_merge` depends on artefacts that only exist post-merge (e.g. `archive_path` is produced by the merge) — report exactly what the dependency is before restructuring it.
- `.env` sourcing would overwrite a variable the orchestrator itself relies on (`TONI_MODEL` / `TONI_EFFORT` in particular).
- Any existing consumer would break on a third outcome value.
- `FIRE_TEMPLATE` turns out to have a real consumer — acceptance item 3 is then void; report and do not edit `config/repos.yaml`.
- Anything that would require adding a skip/bypass flag to make the gates pass.

## Return contract

Commit on the route branch: `fix(orchestrator): gate-then-merge + .env sourcing + BLOCKED(environment) vs FAIL(product)`. Return must include: the verbatim pre-change merge and gate lines with line numbers; the post-change ordering; the disposition of `_self_mod_auto_merge` (gated, or explicitly declared ungated, and why); the implemented environment-signal list; which `fire_command_template` option was applied and the `FIRE_TEMPLATE` no-consumer grep; the worktree path and branch name actually used (§M typed gap); all AC evidence above; and any deviation, typed gap or STOP encountered. **Maximum truthful claim: code-true.** Runtime-true only after a live rehearsal with Medplum up and down. AI sets Met, never Accepted (C-03/C-04).

---

## §V. Batch verification (after the brief completes)

Per the rule line: **build + lint**, no Playwright E2E during batch execution.

- **The orchestrator repo has no build gate and no test suite.** `config/repos.yaml` declares no `build_gate_cmd` for it, and its `test_cmd` is `pytest 2>/dev/null || echo 'orchestrator has no test suite yet'`. Do not substitute an invented command and do not claim a green build. What Toni **must** run instead, and paste:
  - `python3 -m py_compile orchestrator.py` → no output (syntax-true).
  - The `test_cmd` above, verbatim, and paste whatever it prints — including the `orchestrator has no test suite yet` string if that is what comes back. That string **is** the honest result; report it, do not dress it up.
  - The AC-ORCH1-08 YAML parse check.
- **Lint entry point (verified on the repo): there is none.** The orchestrator repo has **no** python lint configuration — no ruff config, no flake8 config, no `setup.cfg`, no `pyproject.toml`, no `tox.ini`, no `Makefile`, no `package.json`. There is no lint gate to run for this repo. The build-gate equivalent for the orchestrator repo is `python3 -m py_compile orchestrator.py` (already listed above) plus the pytest suite identified in `## SIT spec impact` above — run both and report their results; do not invent a lint command.
- Re-assert the locks at the end: `grep -rniE -- "-{1,2}skip[-_]?sit" ~/spectricom-orchestrator` → no output; `ANTHROPIC_API_KEY=x` exit code → `3`; no diff on `DISABLE_BUILD_GATE` / `DISABLE_SIT_BLOCKING` / `SIT_BLOCKING`.
- This run's own merge-back goes through `_self_mod_auto_merge` under the **old** ordering (see §M) — the new gate-then-merge control flow does not govern this run. Say that plainly in the return rather than claiming this run was itself gated.

---

## RUN COMMAND

```
cd ~/spectricom-orchestrator && unset ANTHROPIC_API_KEY && TONI_TIMEOUT_MIN=45 python3 orchestrator.py run /mnt/c/Users/gkass/OneDrive/Documents/Spectricom/toni-batch-s7core4-orch1-gate-then-merge-01.md --repo orchestrator --approve
```

Pre-fire: the §P assertion must pass (verified baseline `0b59820` · 0 dirty · HEAD == origin/main · branch `main`), the Kanban row must read `READY`, `running.json` must be absent and `ps` must show no orchestrator run.
