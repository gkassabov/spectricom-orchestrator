# Toni Batch S7-CORE-8 — ORCH-3 · the unit suite as a BASELINE pre-merge gate

## Repo: orchestrator
## Batch ID: toni-batch-s7core8-orch-3-unit-baseline-gate-01
## Briefs: 1
## Estimated runtime: 45-70 min
## Spec reference: George ruling 2026-09-12 (PCU v1-133 ruling 2) — "the unit suite gates a merge as a BASELINE gate, not a zero gate"
## Predecessor branch: `main` @ `afc53e0` — clean, `HEAD == origin/main`, pytest 79 passed
## Executor profile: `claude-opus-5 --effort high`
## Executor smoke: `claude -p --model claude-opus-5 --effort high` → `OK` on CLI 2.1.266, 2026-09-12
## SELF-MOD: yes — this brief modifies the orchestrator. Expect the `meta_fire` worktree path and the `_self_mod_auto_merge` route.

## MANDATORY READS (pre-code)
- `orchestrator.py` — `run_pre_merge_gates` (the path that actually runs; start at the §976 BUILD GATE block), `run_build_gate` (1010), the SIT gate block (~1129-1165), `_gate_env_file` (991), `_gate_shell_cmd` (998), `_self_mod_auto_merge` (929), `_gate_status_label` (748)
- `config/repos.yaml` — note `clinical-mp.test_cmd: npm test` **already exists and is unconsumed**
- `tests/test_gate_collection.py` and `tests/test_sit_integration.py` — the patterns your tests must follow

## 1 · Why this exists

Eleven unit tests across six files under `src/lib/synth/` in clinical-mp were **RED through at least two merges** and nothing noticed, because **neither gate runs the unit suite**: `sit:gate` covers `sit/integration/**` and the build gate runs `tsc` + `build`. Those were the seeds T2 synth UAT runs on, and one of them asserted that the wipe path does not delete Patients.

George's ruling: **a baseline gate, not a zero gate.** A zero gate would block every merge behind pre-existing reds. A baseline gate stops the *next* red entering while known debt is repaired.

## 2 · Decisions locked

1. **Baseline semantics, per §5.15 and §23.3: halt only if `current_failures > baseline_failures`.** Equal or fewer passes. A *new* failing test **file** that was previously green is also a regression even if the total count did not rise — compare **both** the count and the set of failing files.
2. **The baseline is measured on the MERGE BASE, not on `main`-right-now** and not on a stored number. Check out or otherwise evaluate the predecessor commit the branch forked from, run the suite there, then run it on the branch. A stored baseline goes stale and becomes a lie — the `repos.yaml` `test_cmd` claim that sat unconsumed is the cautionary precedent in this very file.
3. **`test_cmd` comes from `config/repos.yaml`, which already has it for clinical-mp (`npm test`).** A repo with no `test_cmd` is **ungated for the unit suite** and the gate reports `ungated by policy` — the same shape `run_pre_merge_gates` already uses. Do **not** invent a default command for a repo that has not declared one.
4. **Declare what was collected, like [ORCH-2] made the SIT gate do.** The gate logs test-file and test counts for both baseline and branch, persists them with the run, and **zero collection is `BLOCKED(environment)`, never `FAIL(product)`**.
5. **Put it on the path that actually runs.** The A2/A8 assertions went into `run_batch()` and a grep of the call graph proved two of three fire commands would have bypassed a different placement. **This gate belongs in `run_pre_merge_gates` alongside build and SIT** — verify by grep that every fire path reaches it, and state that call graph in the report.
6. **Order: build → SIT → unit.** Cheapest-signal-first is already the existing order's logic; the unit suite is the slowest, so it runs last and only if the others passed.

## 3 · Acceptance criteria

- **AC-O3-01** — `run_pre_merge_gates` runs the unit suite after build and SIT, for **every repo in `config/repos.yaml` that declares a `test_cmd`**. Derive that set from the config; do not hard-code repo names.
- **AC-O3-02** — a repo with **no** `test_cmd` yields a unit-gate outcome of `ungated by policy` and **does not** block the merge. Asserted for at least one such repo from the real config.
- **AC-O3-03** — **baseline comparison:** `current > baseline` blocks; `current == baseline` passes; `current < baseline` passes. All three asserted.
- **AC-O3-04** — **a newly-failing file blocks even when the total count does not rise.** Construct the case where baseline is `{A: 2 failures}` and branch is `{B: 2 failures}` and assert it **blocks**.
- **AC-O3-05** — the baseline is computed from the **merge base**, not from a stored value and not from `main`'s current tip. Asserted by a test in which `main` has advanced past the branch's fork point.
- **AC-O3-06** — the gate **logs and persists** baseline and branch counts (test files and tests) and they appear in the run record, in the shape [ORCH-2] established for the SIT gate.
- **AC-O3-07** — **zero collection is `BLOCKED(environment)`**, not `FAIL(product)`. Asserted.
- **AC-O3-08** — a unit-gate failure **leaves the branch unmerged and preserved**, exactly as a red build or SIT gate does today.
- **AC-O3-09** — `python3 -m pytest tests/ -q` passes with **no new failures vs the `afc53e0` baseline of 79 passed**. State both numbers. New tests are additive.
- **AC-O3-10** — the existing build and SIT gate behaviour is **unchanged**: `tests/test_gate_collection.py` and `tests/test_sit_integration.py` pass with **their assertions unmodified** — no edit to either file.
- **AC-O3-11** — `--force` still bypasses, and the bypass is **logged as a bypass** including the unit gate, consistent with how A2/A8 already report it.

## 4 · STOP-and-report triggers

- Computing the merge-base baseline requires a second checkout of the target repo that could disturb a **concurrently running route in that repo** → **STOP and report.** A clinical-mp route may be live while this runs; do not touch its working tree or its branch. Use a detached worktree or a read-only strategy.
- The unit suite cannot be run without network or a dev server → **STOP**; that makes it an environment gate, not a product gate, and changes the design.
- Making this work appears to need a change to `run_build_gate` or the SIT block → **STOP.** Add alongside; do not refactor the gates that currently work.

## 5 · Test impact
New pytest coverage in `tests/`, following `test_gate_collection.py`'s patterns. No existing test file is edited.

## RUN COMMAND
```
cd ~/spectricom-orchestrator && unset ANTHROPIC_API_KEY && python3 orchestrator.py run toni-batch-s7core8-orch-3-unit-baseline-gate-01.md --repo orchestrator --model claude-opus-5 --effort high --approve
```
