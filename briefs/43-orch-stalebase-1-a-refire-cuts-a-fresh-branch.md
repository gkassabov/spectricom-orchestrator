#!queue model=claude-opus-5-5 effort=high repo=orchestrator

# ORCH-STALEBASE-1 — a re-fire cuts a fresh branch from the merge target

## Repo: orchestrator
## Batch ID: s7core15-orch-stalebase-1
## Briefs: 1
## Estimated runtime: 30-45 min
## Spec reference: BUG-S7CORE14-ORCH-STALEBASE-01
## Predecessor: none. `main` at fire time (verified at c292570 — QUEUE-RETIRE-1 already landed there; see §4 for what that moved).

## 0 · FIRST STEP

Read these IN FULL before designing anything. Every line number below was read at c292570; QUEUE-RETIRE-1 (c292570) touched the merge site in `_run_batch_inner`, so re-verify each number with `grep -n` before you edit — do not trust this brief's numbers over the file.

1. `orchestrator.py` `_run_batch_inner` — the whole function, `orchestrator.py:3244` to the `except Exception` at `:3473`. The defect is the branch block at `:3259-3283`. The exits that always put the checkout back on `MERGE_TARGET` are `:3418`, `:3430`, `:3468`, `:3472`; branch deletion after a good merge is `:3458`; the no-change `branch -D` is `:3469`.
2. `orchestrator.py` `run_batch` — `:3171-3242`, specifically the meta-fire worktree block `:3184-3204`, which has the SAME `-b`-then-fall-back-to-existing shape and is the lane THIS brief will be fired on (`repo=orchestrator` ⇒ `IS_META_FIRE`, self-mod, merged `--ff-only` at `:1459`).
3. `orchestrator.py` `create_worktree` `:1351-1367` and `merge_branch` `:1376-1381` — the parallel-worktree lane. Read so you recognise the third copy of the shape; it is OUT of scope (§4).
4. `orchestrator.py` `capture_handoff` `:962-970`, `check_route_integrity` `:974-1006`, `_git_read` `:887-894`, `_snapshot_heads` `:896-905` — the ORCH-10 hand-off snapshot. The fresh branch must be cut BEFORE `capture_handoff` runs (`:3289`), so the snapshot records the fresh SHA.
5. `canon_assert.py` `:400-590` — `git()` `:400`, `QueueRepo` `:459-473` (`branch_for` at `:470`), `Violation` `:476-490`, `_git_rc`/`_is_ancestor` `:492-498`, `_landed` `:505-538`, `check_queue_trunk_invariants` `:557-587`. This is the invariant module you EXTEND; the new predicate lives here, in this shape (frozen dataclass + `-> list[...]`, empty when clean, unreadable is never a violation).
6. `tests/test_route_ref_integrity.py` `:29-135` — the harness: `_init_repo` `:34`, the `route` fixture `:67-95` (monkeypatches `PROJECT_ROOT`, `BRANCH_PREFIX="orch"`, `MERGE_TARGET="main"`, `IS_META_FIRE=False`), `fire()` `:97-109` (monkeypatches `run_pre_merge_gates` and `fire_toni`; the `executor(proj)` callable runs INSIDE the route at hand-off time — that is where the predicate can be sampled), executors `works` `:120-125`. Build the new tests on this harness, not on a new one.
7. `tests/test_queue_retire.py` `:29-32` and `:97-201` — how a `QueueRepo` is built for a tmp repo and how a `check_*_invariants` predicate is asserted `== []` / destructured `(v,) = ...`.
8. `tests/test_branch_sweep.py` `:15-60` — `_init_repo`, `_create_merged_branch`, `_create_unmerged_branch` helpers (shell-string style), for the shape of a "main advanced past the branch" fixture.
9. `queue_daemon.py:29` and `:279` — the only production importer of `canon_assert` invariants today. Do not add a daemon call; note the import shape.

## 1 · WHY THIS EXISTS

The story, from the orchestrator's own logs in `logs/orch-*.log` (clinical-mp, branch `orch-mp-23-l-ui-safety-1-one-gate-one-interrupt-both-doors`):

- Attempt 1 — `logs/orch-20260920-202656.log:12` `🌿 Branch: orch-mp-23-…` (cut fresh at `bb6513b`, main's tip then). `:53-54` gate `FAIL(product)`, `main NOT merged. Branch preserved`. Correct behaviour — the branch stays for inspection.
- Between attempts, `main` advanced 7 commits (`git rev-list --count bb6513b..00ae1ed` = 7 in `~/spectricom-clinical-mp`, all fast-forward merges of other routes).
- Attempt 2 — `logs/orch-20260921-020444.log:12` `🌿 Switched to existing branch: orch-mp-23-…`. That is `orchestrator.py:3273` firing: `git checkout -b` failed because the branch existed, so `:3273` `git checkout {branch_name}` REUSED the stale branch. Toni worked on a base 7 commits behind main. `:30` unit gate measured "vs merge-base bb6513b"; `:35` `Pre-merge gate … PASS` — a green verdict rendered against code main no longer looked like. `:36` `⚠️ Merge conflict on orch-mp-23-… — MANUAL RESOLUTION NEEDED` (`orchestrator.py:3432` `git merge {branch_name} --no-edit` returned non-zero; logged at `:3460`). `:38` still says `FINAL STATUS: passed`. The queue holds the same brief in BOTH `queue/failed/` and `queue/done/`.
- A human renamed the branch by hand (`orch-mp-23-attempt1-stale-base` still exists in clinical-mp) and re-fired.
- Attempt 3 — `logs/orch-20260921-042012.log:12` `🌿 Branch: …` (fresh, at `00ae1ed`), `:40` `🔀 Merged … → main (00ae1ed → a93d589)`; main's reflog reads `merge orch-mp-23-…: Fast-forward`.

The mechanism, in the code:

- `orchestrator.py:3262` derives the name `f"{BRANCH_PREFIX}-{batch_file.stem}"` — deterministic per brief, so every attempt of a brief wants the same name.
- `orchestrator.py:3263-3266` `git checkout -b {branch_name}` cuts from HEAD (whatever HEAD is — never explicitly from `MERGE_TARGET`).
- `orchestrator.py:3271-3277` on failure it assumes "branch may already exist" and switches to it. There is no check of WHERE that branch is based. A branch left behind by a red gate (`:3418` preserved on purpose) is therefore silently adopted by the next attempt, with the base it was cut at.
- The same shape, second copy: `orchestrator.py:3192-3196` (meta-fire worktree: `git worktree add … -b` then fall back to `git worktree add … {meta_branch}` on the existing branch). The self-mod merge at `:1459` is `--ff-only`, so a stale base there does not even get a 3-way attempt — it fails "non-ff" at `:1467-1470`.
- Third copy, out of scope: `orchestrator.py:1358-1362` (`create_worktree`, `-w{wid}` names, parallel lane).

Nothing in the repo asserts "the route branch was cut at the merge target's current tip". `canon_assert.py:557` asserts the trunk side (a merged brief must not stay queued); the branch side has no predicate. That is what this brief adds, and the orchestrator asserts it at the moment of action.

## 2 · THE TARGET STATE

"Done" is a predicate, not a list of symptoms (house rule D-S7CORE13-02 / assertion S1).

Add to `canon_assert.py`, beside `check_queue_trunk_invariants` (`:557`), in the same style (frozen dataclass, `list[...]` result, empty when clean, unreadable never a violation):

```python
@dataclass(frozen=True)
class StaleBaseViolation:
    """A route branch whose base is behind the merge target's current tip."""
    repo: str
    branch: str
    merge_target: str
    target_tip: str          # sha the merge target is at now
    branch_tip: str          # sha the branch is at now
    merge_base: str          # git merge-base <target> <branch>
    behind: int              # git rev-list --count <branch>..<target>  (>0 by construction)

def check_branch_freshness_invariants(repo: QueueRepo, briefs: Iterable[str]) -> list[StaleBaseViolation]:
    """For each brief name in `briefs`, the route branch `repo.branch_for(brief)`, IF it
    exists as refs/heads/<branch>, must contain the merge target's current tip:
    `git merge-base --is-ancestor <merge_target> <branch>` must succeed.
    EMPTY WHEN CLEAN. A branch that does not exist is not a violation (nothing to be
    stale). An unreadable repo / missing merge target ⇒ [] (unreadable is never a
    violation — same rule as _landed at :505). Retired branches are never in the set:
    they are not `branch_for(any brief)`.
    """
```

Quantified set (RULE A11): exactly the branches `repo.branch_for(b)` for `b in briefs` — never "all `orch-*` heads". The caller names the set; the orchestrator names ONE (the brief it is firing); tests name the briefs they created.

The orchestrator's obligation, stated as the predicate: **immediately after the branch cut and before `capture_handoff` (`:3289`), `check_branch_freshness_invariants(QueueRepo(ACTIVE_REPO_NAME, proj, MERGE_TARGET, BRANCH_PREFIX), [batch_file.name]) == []` holds, on the first fire AND on every re-fire, and the route does not fire Toni when it does not hold.** The acceptance in §5 samples that predicate at hand-off (via the test harness's executor) and in the repo after the run.

A re-fire achieves this by RETIRING the stale branch (rename, never delete — the previous attempt's commits are evidence a human may want) and cutting the route branch afresh, explicitly from `MERGE_TARGET`.

## 3 · SCOPE

**T1 — the predicate.** `canon_assert.py`, after `check_queue_trunk_invariants` (`:557-587`): add `StaleBaseViolation` and `check_branch_freshness_invariants` exactly as in §2. Use the existing `git()` (`:400`), `_git_rc`/`_is_ancestor` (`:492-498`). Give `StaleBaseViolation.__str__` a one-line human form like `Violation.__str__` (`:487`): `"<branch> is <behind> commit(s) behind <merge_target> (<target_tip[:8]>): cut at <merge_base[:8]>, tip <branch_tip[:8]>"`. No config literals; `merge_target` and `branch_prefix` come from `QueueRepo` as they do today.

**T2 — the retire helper.** `orchestrator.py`, next to `_get_current_branch` / `_is_branch_merged` (`:3734-3750`) or next to `_git_read` (`:887`) — your call, one place: add

```python
def retire_stale_branch(proj: Path, branch_name: str, merge_target: str) -> Optional[str]:
    """If refs/heads/<branch_name> exists, rename it to
    <branch_name>--stale-<YYYYmmdd-HHMMSS> (git branch -m) and return the new name.
    Returns None when the branch does not exist (nothing to retire).
    Raises RuntimeError when the branch exists and the rename fails — the caller must
    NOT fall through to running on the stale branch."""
```

Rename, not delete: `git branch -m` preserves the attempt-1 commits and works even when that branch is checked out in another worktree (git 2.43 on this box). Log one line: `♻️  Retired stale branch <old> → <new> (was <n> behind <merge_target>)` — compute `<n>` with `git rev-list --count <old>..<merge_target>`; if `<n>` is 0 the branch is not stale but still must be retired (it exists; the previous attempt's commits, if any, are not this attempt's), so log `(at <merge_target> tip)` instead of a number. The suffix `--stale-<ts>` must not be a name `QueueRepo.branch_for` can produce (a brief stem never contains `--stale-`) — say so in the docstring; that is what keeps retired branches out of the predicate's set.

**T3 — the single-stream branch cut (the defect).** `orchestrator.py:3259-3283`, replace the block's logic with:

1. `retired = retire_stale_branch(proj, branch_name, MERGE_TARGET)` inside the existing `try`.
2. `git checkout -b {branch_name} {MERGE_TARGET}` — cut EXPLICITLY from the merge target, not from HEAD.
3. On success: `log.info(f"🌿 Branch: {branch_name} (from {MERGE_TARGET} @ {tip[:7]})")` — keep the literal prefix `🌿 Branch: {branch_name}` so existing log greps hold.
4. Then assert: `v = check_branch_freshness_invariants(QueueRepo(ACTIVE_REPO_NAME, proj, MERGE_TARGET, BRANCH_PREFIX), [batch_file.name])`. If `v` is non-empty, or step 2 failed, or `retire_stale_branch` raised: log `⛔ STALE-BASE — <str(v[0]) or stderr> — not firing.` and return `Result(batch_file=batch_file.name, status=Status.FAILED, …, exit_code=2, briefs=len(briefs), error="stale-base: …")` in the shape of the prefire early return at `run_batch` `:3175-3179`. The `🌿 Switched to existing branch` path (`:3271-3277`) is DELETED — there is no legitimate case where a re-fire adopts an existing route branch.
5. Keep the pre-existing degraded path ONLY for "not a git repo / cannot create a branch at all and no branch exists" (`branch_name = None`, "Running on current branch", `:3278-3283`). Do not widen it.

Import `QueueRepo, check_branch_freshness_invariants` from `canon_assert` at the top of `orchestrator.py` the way `queue_daemon.py:29` does. Verified at c292570: `orchestrator.py` does not import `canon_assert` at all (`grep -n canon_assert orchestrator.py` is empty), so this is a new import line; `canon_assert.py` imports nothing from `orchestrator.py` (keep it that way — no cycle).

**T4 — the meta-fire worktree cut (second copy).** `orchestrator.py:3184-3204`: before `git worktree add {meta_wt} -b {meta_branch}`, call `retire_stale_branch(PROJECT_ROOT, meta_branch, MERGE_TARGET)`; cut with `git worktree add {meta_wt} -b {meta_branch} {MERGE_TARGET}`; DELETE the fall-back `git worktree add {meta_wt} {meta_branch}` at `:3195-3196`. On failure the existing `log.error("Meta-fire worktree failed…")` path stands (it already does not adopt a branch — it runs with `worktree=None`, which the self-mod lane then treats as non-worktree; leave that behaviour exactly as is, it is not this brief's problem). Assert the predicate here too with `QueueRepo(ACTIVE_REPO_NAME, PROJECT_ROOT, MERGE_TARGET, BRANCH_PREFIX)` — a violation logs `⛔ STALE-BASE` and returns the FAILED `Result` before `write_running` (`:3208`).

**T5 — tests.** New file `tests/test_stale_base.py` on the `test_route_ref_integrity.py` harness (copy the `route` fixture and `fire()` shape; do not import private names from that module — duplicate the ~40 harness lines, the way `test_branch_sweep.py` and `test_route_ref_integrity.py` each carry their own `_init_repo`). ACs in §5 name every test.

**T6 — `_write_running_marker` (`:1235`) is called at `:3211` with `meta_branch or f"{BRANCH_PREFIX}-{batch_file.stem}"`** — the branch NAME is unchanged by this brief (the fresh cut reuses the canonical name; only the stale one gets the suffix), so the marker needs no change. Verify, and say so in §6, rather than assume.

## 4 · OUT OF SCOPE — do NOT touch

- Gate semantics or verdict classification: `run_pre_merge_gates` (`:3002`), `run_unit_gate` (`:2676`), `_unit_merge_base` (`:2204`), `GateOutcome`, `Status`, the `FINAL STATUS` line. In particular: attempt 2 logged `FINAL STATUS: passed` AFTER a merge conflict (`:3460` logs but does not change `status`). That is a real second defect — leave it, and name it in §6 as found-and-left.
- The queue daemon's bookkeeping, `queue_daemon.py` entirely, and `retire_batch_file` (`orchestrator.py:1384`) plus its call at `:3456`. QUEUE-RETIRE-1 landed on `main` at c292570 and rewrote the merge site of `_run_batch_inner` (`:3450-3458`) and the daemon; if a further QUEUE-RETIRE follow-up is in flight when you fire, EXPECT the line numbers in this brief around `:3400-3475` to have moved and rebase onto what is there. Your change is confined to the branch-cut block at the top of `_run_batch_inner` and the meta-fire block of `run_batch`; you should not need to edit a single line inside the `if status == Status.PASSED:` merge body.
- `create_worktree` (`:1351`) and `merge_branch` (`:1376`) — the parallel `-w{wid}` lane (yorsie, `worktree_mode: parallel`). Same shape, separate increment; name it in §6.
- `list_branches` / `clean_branches` (`:3752`, `:3796`) — the sweep CLI. Note only: a retired `--stale-` branch still matches `orch-*`, is unmerged, and so survives `branches clean` without `--force`. That is the intended behaviour; do not special-case it.
- `capture_handoff` / `check_route_integrity` (ORCH-10) — read-only for you; the fresh cut happens before them and they need no change.
- `config/repos.yaml`, `prefire.py`, `SESSION-BOOT.md`, `canon_assert.py`'s B1-B9 assertions and `ASSERTIONS` registry (`:971`) — the new predicate is NOT a boot assert and is not registered there.
- Nothing outside `/home/gkassa/spectricom-orchestrator`. You do not touch `~/spectricom-clinical-mp` or the `orch-mp-23-attempt1-stale-base` branch that lives there.
- Do not delete any branch anywhere. The fix renames.

## 5 · ACCEPTANCE

Baseline at the merge-base (c292570): `pytest -q tests/` → **409 passed, 0 failed** (measured 2026-09-27 in `venv`, 12.3s).

- **AC-SB-01 — the predicate is clean on a fresh cut.** `tests/test_stale_base.py::test_fresh_cut_is_clean`: init repo, commit brief, `fire(route, monkeypatch, works)`; the executor samples `check_branch_freshness_invariants(QueueRepo("testrepo", proj, "main", "orch"), [brief.name])` at hand-off and stores it; assert `== []` and `git rev-parse orch-<stem>` at hand-off equals `git rev-parse main` at fixture time. Set quantified: the one branch `orch-<stem>`.
- **AC-SB-02 — RED-BEFORE-GREEN: the L-UI-SAFETY-1 shape reproduces.** `test_refire_after_red_gate_and_advanced_main_cuts_fresh`: (1) fire with `works`, `gate=GateOutcome.FAIL_PRODUCT` → branch preserved, main untouched (existing behaviour, `:3418`). (2) Advance `main` by 3 commits directly (touching the same file `works` touched, so a 3-way merge would conflict — mirror attempt 2). (3) Fire the SAME brief again with `works`, `gate=PASS`. Assert at hand-off: predicate `== []` AND `git merge-base main orch-<stem>` == `git rev-parse main` (fresh, not `bb6513b`-shaped). Assert after the run: `result.status == Status.PASSED`, main advanced (`rev-list --count` before < after), and the log contains `🔀 Merged`, not `Merge conflict`. **Write this test first and run it against unmodified c292570: it MUST fail** (the current `:3273` path yields a `Switched to existing branch` log line, a non-empty predicate at hand-off with `behind == 3`, and a merge conflict). Record the red output in §6.
- **AC-SB-03 — the stale branch is retired, not deleted.** In the same scenario, after (3): exactly one ref matching `refs/heads/orch-<stem>--stale-*` exists, its tip equals the attempt-1 tip recorded in (1), and the log contains `♻️  Retired stale branch orch-<stem> → orch-<stem>--stale-`. Set quantified: refs under `refs/heads/` in the tmp repo.
- **AC-SB-04 — `Switched to existing branch` never appears.** Over the three tests above plus `test_second_refire_retires_again` (fire → red, fire → red, main advances, fire → green: two `--stale-` refs with distinct suffixes, predicate clean at each hand-off): the substring `Switched to existing branch` appears in NO caplog record of these four tests. Set quantified: those four tests' log records.
- **AC-SB-05 — the predicate is red on the incident shape, in isolation.** `test_predicate_flags_a_branch_behind_main`: no orchestrator call — build the repo with `test_branch_sweep`-style helpers: cut `orch-x` at main, advance main by 2 commits; `(v,) = check_branch_freshness_invariants(QueueRepo(..., "orch"), ["x.md"])`; assert `v.behind == 2`, `v.merge_base == <sha at cut>`, `v.target_tip == <main now>`, and `str(v)` contains `2 commit(s) behind main`. And `test_predicate_ignores_missing_and_retired`: a brief whose branch does not exist ⇒ `[]`; a repo with only `orch-x--stale-20260101-000000` (behind main) and brief `x.md` with no `orch-x` ⇒ `[]`. Set quantified: the `briefs` list passed in.
- **AC-SB-06 — a failed retire does not fire on the stale branch.** `test_retire_failure_refuses_to_fire`: monkeypatch `orchestrator.retire_stale_branch` to raise `RuntimeError("simulated")` while `orch-<stem>` exists behind main; fire; assert `result.status == Status.FAILED`, `result.error` starts with `stale-base:`, the executor was NOT called (counter == 0), `main` unchanged, and `git symbolic-ref HEAD` is back on `refs/heads/main`.
- **AC-SB-07 — the meta-fire cut is fresh.** `test_meta_fire_worktree_cuts_from_merge_target`: with `IS_META_FIRE=True`, `PROJECT_ROOT=tmp repo`, and `_run_batch_inner` monkeypatched to a stub that returns a PASSED `Result` and records `git rev-parse HEAD` in the worktree it is handed; pre-create `orch-<stem>` behind main; call `run_batch`; assert the recorded HEAD == `git rev-parse main`, and one `orch-<stem>--stale-*` ref exists. Cleanup of `/tmp/orch-fire-*` is the existing `cleanup_worktree` (`:3241`); assert the worktree dir is gone after the call. If you find `run_batch` cannot be driven this way without touching `prefire.report` (`:3173`), monkeypatch `orchestrator.PREFIRE_BYPASS = True` for this test and say so in §6.
- **AC-SB-08 — no invocation shape changes.** All of `tests/test_route_ref_integrity.py` (8 classes, 36 tests at c292570 — re-count and cite), `tests/test_queue_retire.py`, `tests/test_branch_sweep.py`, `tests/test_self_mod_auto_merge.py` pass UNMODIFIED. Set quantified: those four files as they exist at c292570.
- **AC-SB-09 — suite green, no new failures.** `pytest -q tests/` → `409 + N passed, 0 failed`, where N is the number of tests you added (state N). Any test that fails at c292570 AND after your change is not yours; there are 0 such at c292570.
- **AC-SB-10 — the string `skip` + `-sit` (joined) appears nowhere in the diff**, and no new config literal (branch prefix, merge target, repo name, path) enters `orchestrator.py` or `canon_assert.py`; `grep -n '"main"\|"orch-' <your diff>` shows only the pre-existing defaults in `QueueRepo` (`:467-468`) and `_is_branch_merged` (`:3743`).

## 6 · HANDBACK

Write §7 FIRST — what you found and left, and why: at minimum (a) `FINAL STATUS: passed` after a merge conflict (`:3460` does not fail the route — attempt 2's `logs/orch-20260921-020444.log:36-38`), (b) the third copy of the shape in `create_worktree` `:1358-1362`, (c) the brief sitting in both `queue/failed/` and `queue/done/` for `23-l-ui-safety-1`, (d) anything else you tripped over. Each with file:line and one sentence on why it is not this increment.

Then:

1. **What shipped** — files touched, the predicate's final signature, the retire helper's final signature and where you placed it, the exact log line prefixes (`🌿 Branch:`, `♻️  Retired stale branch`, `⛔ STALE-BASE`).
2. **Red-before-green** — paste the AC-SB-02 failure output from c292570 (the assertion that failed and the `Switched to existing branch` line) and its green output after.
3. **Gate table** —

   | run | passed | failed | note |
   |---|---|---|---|
   | merge-base c292570 | 409 | 0 | baseline (measured 2026-09-27) |
   | this branch | 409 + N | 0 | N = tests added |

   plus the per-AC row: AC id → test name → pass/fail.
4. **CONSEQUENCE (house rule D-S7CORE13-03)** — state for each existing invocation shape whether behaviour changes:
   - First fire of a brief (no branch exists): the cut is now explicitly `git checkout -b <b> <MERGE_TARGET>` instead of from HEAD. Say whether that is observable when the repo is checked out on `MERGE_TARGET` (it should not be) and what happens when it is NOT (a human left the repo on another branch): previously the route branched from wherever HEAD was; now it branches from `MERGE_TARGET`. That IS a behaviour change; name it and argue it is the correct one (a route's base is the merge target, never a human's parked branch).
   - Re-fire after a red gate: previously adopted the stale branch; now retires it and cuts fresh. The change this brief exists for.
   - Re-fire after a green merge: `:3458` deletes the branch on success, so no branch exists and this is the first-fire shape — unchanged apart from the explicit base.
   - Re-fire after a no-change run: `:3469` `branch -D`, same as above.
   - Meta-fire (`repo=orchestrator`): same as single-stream, plus the `--ff-only` merge at `:1459` now has a base it can fast-forward from.
   - `orchestrator.py branches list|clean`: unchanged; retired branches appear as unmerged.
   - The queue daemon: no call added, no import changed; `check_queue_trunk_invariants` untouched.
5. **Open questions you could not settle** — say plainly rather than assert. Known at brief time: whether `run_batch` can be unit-driven for AC-SB-07 without `PREFIRE_BYPASS` (see the AC); whether `canon_assert.py`'s own module-level imports (`:1-60`) pull anything that makes importing it from `orchestrator.py` slow or side-effectful at fire time — read them before adding the import.
