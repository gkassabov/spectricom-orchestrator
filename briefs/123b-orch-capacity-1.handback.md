# filename: briefs/123b-orch-capacity-1.handback.md

# 123b · ORCH-CAPACITY-1: handback

C1 and C4 are in, and so is C3's deploy script. **C2's flip to `worktree_mode: parallel` is stopped.** As built, the first ai-foundation merge after the flip would delete the venv the MiniMe services run from. Everything else in C2 is staged: the worktree base, and a gate command proven in a fresh worktree. The flip becomes one config line once ai-foundation's `.gitignore` ignores a `venv` symlink.

P1, P2, P3, P5, P6 and P7 are green. P4 is green on what can be shipped: the gate command and the path the staged block resolves to. The flip itself waits on the fix in Found-and-LEFT 1.

Things you need to know first:
- **Flipping C2 as written would delete `~/spectricom-ai-foundation/venv/`.** ai-foundation's `.gitignore:1` reads `venv/`, which matches a directory only. A route worktree gets a `venv` **symlink** from `orchestrator._create_route_worktree`, so the route's `git add -A` commits it. The merge then fast-forwards the main checkout, and git replaces the ignored `venv/` directory with that symlink. I reproduced this in a temp repo (gate table), and `TestP4VenvLinkHazard` pins it. The fix belongs to ai-foundation (one character), or to `orchestrator._create_route_worktree`, which is outside §3. Found-and-LEFT 1.
- **C3 holds only once the main checkout is off `main`.** `_land_from_route_worktree` runs `git merge --ff-only` in whichever checkout has `main` checked out (§0.2), and ai-foundation's main checkout does. `aif-deploy.sh` prints this as a NOTE. Detaching the checkout is George's call. Found-and-LEFT 2.
- **The first `aif-deploy.sh` dry-run refuses today (exit 2).** Listen sitting `20261005-150302-3a4c6dc7ccf2` reads `recording` (its `captured_at.end` is null) and has since 15:03. Found-and-LEFT 3.
- **C1 and C4 take effect in the daemon only after Gemma restarts it (L-29).** A direct `orchestrator.py run` asks admission from the next fire after this merges. The live queue is empty now (124–129 are in `queue/held/s7c21-restart/`), so the old daemon fires nothing in between. The restart steps are under THE CONSEQUENCE.

- **Branch:** `orch-orch-123b-orch-capacity-1`, from `e028795`. Ancestry checked: `git merge-base --is-ancestor e0287955 HEAD` ✓.
- **Commits:** `fb0fa69` has the code, config, script and tests. The second commit is this file.
- **Tests:** `pytest -q tests/` gave **996 passed** at `e028795` and **1062 passed** at `fb0fa69`. The +66 are all in the new `tests/test_capacity.py`. No test was removed. Three existing tests were changed, because C1 and C4 change what they pinned (Found-and-LEFT 6).

## Found and LEFT

1. **C2's flip is STOPPED: as built, it deletes the services' venv at the first merge.**
   - **Mechanism.** `_create_route_worktree` (`orchestrator.py:1577` at base) calls `_link_unit_deps(PROJECT_ROOT, wt)`, which symlinks `venv` (`UNIT_BASELINE_LINK_PATHS`, `:333`) into the route worktree. ai-foundation's `.gitignore:1` is `venv/`, and `git check-ignore` does not match a symlink against a directory pattern. So the link is untracked and not ignored. The route lane's `git add -A` (`:4511`) commits it, and so would Toni's own `git add -A`. The gates pass, because the link is harmless in the worktree. Then `_land_from_route_worktree` fast-forwards the main checkout (item 2).
   - **Probe (temp repo, `.gitignore: venv/`, a real `venv/bin/python`):** a worktree linked `venv` → `git status` `?? venv` → committed → `git merge --ff-only` in the main checkout: `create mode 120000 venv`, exit 0. Afterwards `venv` is a symlink and `venv/bin` is `Too many levels of symbolic links`. The directory was gone.
   - **What I shipped instead.** `worktree_base: /home/gkassa/aif-toni` is set; it is read only when the mode is `parallel`. `worktree_mode` stays `single-stream`, with a comment naming this item. The gate command names the services' venv by absolute path, so it needs no link, and it is proven in a fresh worktree (gate table). A tripwire test (`test_the_shipped_mode_stays_single_stream_until_venv_is_ignored`) fails when someone flips the mode.
   - **The remedy, in order:**
     1. In ai-foundation, change `.gitignore:1` from `venv/` to `venv`. This ignores both the directory and the link (`TestP4VenvLinkHazard::test_venv_without_the_slash_ignores_it`). George's commit, or an ai-foundation route.
     2. In `config/repos.yaml`, set ai-foundation's `worktree_mode: parallel`, and delete the tripwire test in the same commit.
     3. Item 2's detach, if C3 is wanted.
   - **The other fix is in code:** `_create_route_worktree` would drop any link git would not ignore. It is outside §3 ("orchestrator.py: run admission call + --force log only"), so I left it. That fix would also cover 104's Found-and-LEFT 8, the Yorsie `node_modules/` case.
   - **Until then, ai-foundation routes keep running in the main checkout, as before,** and L-71's exposure is unchanged for 125, 126 and 128 (held). Whether to fire them before the remedy is Gemma's call.
2. **C3: the orchestrator updates the main checkout whenever that checkout has `main` checked out.**
   - In the parallel lane, `_land_from_route_worktree` runs `git merge --ff-only` in `_checkout_holding(main)`'s checkout (`:1652-1654` at base). Only when no checkout holds `main` does it move the ref alone (`update-ref`, `:1656`). In the single-stream lane, the route runs in the checkout itself.
   - `git -C ~/spectricom-ai-foundation symbolic-ref HEAD` → `refs/heads/main`.
   - With C2 live **and** the checkout detached (`git -C ~/spectricom-ai-foundation switch --detach`), a merge moves only `refs/heads/main`. The services' tree then moves only through `aif-deploy.sh`, whose `git merge --ff-only <sha>` works on a detached HEAD (`TestP5 test_apply_…`).
   - Detaching changes how humans work in that checkout: `git pull` and commits land on no branch. That is why it is George's call, and why the script only prints the NOTE.
3. **Today's dry-run refuses on a Listen sitting that reads `recording`.**
   - `ORCH_DIR=~/spectricom-orchestrator scripts/aif-deploy.sh` → `⛔ aif-deploy: a Listen sitting is in progress: 20261005-150302-3a4c6dc7ccf2 recording — refused, nothing changed`, exit 2.
   - The script reads `<data_root>/george/*/sitting.json` through the worker's own `ListenConfig.from_env()` and `store.derive_status`. It loads `~/.config/minig-listen.env` first, the worker's EnvironmentFile. It runs with `PYTHONDONTWRITEBYTECODE=1`, takes no `.lock` and writes nothing.
   - Whether that sitting is really open (a page never stopped), or stuck, is for George to check. The refusal is deliberate: a record it cannot read also refuses.
4. **`minime-listen-ingest.service` is `failed`.** I saw this in §0.3 (`systemctl --user is-active` → `active`, `failed`). I did not investigate: it is outside §3, and `aif-deploy.sh` does not rerun the ingest service by design.
5. **The default gate budget counts one SIT budget, while clinical-mp's SIT runs in batches.**
   - `SIT_TIMEOUT` is the budget of one batch. Route 122 ran 5 batches (47 files / 137 tests, 659 s plus a ~140 s enumeration).
   - The default sum for clinical-mp is 5100 s: build 600 + SIT 600 + unit 1800 (`test_timeout_s`) + baseline 1800 + confirm 300. That is about 85 min against 122's ~19 min of build + SIT, and the 900 s slack covers enumeration and pauses.
   - Also not counted: a baseline re-measure on an implausible clock, and SIT isolation reruns.
   - The brief's definition ("the sum of the configured gate timeouts") is what shipped. `admission.gate_budget_s` (a number, or `{repo: seconds}`) raises it with no release.
6. **Three existing tests changed, because they pinned what C1 and C4 change.**
   - `test_orch_lane.py::test_R_a_direct_route_in_another_repo_does_not_hold_the_queue`: under the shipped limit of 1, admission now holds 110 behind 109. That is C1's point, and it reverses that test's consequence. The test now sets `max_concurrent_routes: 2`, so it still tests O1's per-repo lock. P1 tests the default.
   - `test_queue_gate_log.py::test_timeout_keeps_what_was_printed_before_the_kill`: the 2 s kill is now a 2 s `RouteWall` put in place of `admission.route_wall`, not `config["timeout_seconds"]`. Its assertions are unchanged, including `^Exit: -1 \(timeout after 2s\)$`.
   - `test_executor_default.py::test_every_other_persisted_key_still_applies`: a persisted `timeout_seconds` is no longer applied (C4), so the test asserts it is absent.
   - New `tests/conftest.py`: every test reads a 64 GiB meminfo. A test that calls `orchestrator.main()` for `run` without opting in (`@pytest.mark.admission`) gets admission's yes. Those tests stub `run_batch` and leave `orchestrator.ORCH_DIR` as it is, so if they were run from `~/spectricom-orchestrator` they would count, and claim beside, the live routes.
7. **Before the restart, admission works one level down.** The old daemon does not pass a claim. A route it fires asks admission in its own `run`. A refusal there is exit 2, which the old daemon records as FAILED, moving the brief to `failed/` and pausing on `stop_on_failure`. The live queue is empty (item 4 of THE CONSEQUENCE), so nothing should reach that path.
8. **Only `orchestrator.py run` is admitted.** `queue` and `parallel` (legacy multi-batch subcommands) are not; the brief names `run`.
9. **The daemon's kill signals the shell it spawned, as before.** `proc.kill()` targets the `/bin/bash -c` child. Toni runs in its own session (`preexec_fn=os.setsid` in `fire_toni`), so it is not in that process group. I did not measure what outlives a wall kill.
10. **A dead route's pid that the OS reuses still counts as alive.** This is P-STALE's rule, restated in admission.py, and it has the same weakness.
11. **The route shares the services' venv, by absolute path or by link.** A route that runs `pip install` changes the live services' environment. That was already true for single-stream, and it stays true with C2.
12. **ai-foundation's first route after this measures its baseline afresh.** The unit-baseline cache is keyed by the command, and `test_cmd` changed. On today's tree that is about 4 min (830 passed / 33 skipped in 223 s).
13. **The kill message names the clock and the phase.** Phases are read off the route's own log: `before Toni`, `Toni`, `after Toni`, `build`, `SIT`, `unit`, `merge`. The route's own clocks (Toni's, each gate leg's) are orchestrator.py's. If one of them ends the route, it exits by itself and the daemon kills nothing.
14. **`_run_route` outside `run_loop` has no brief to derive a wall from.** It falls back to the 180-minute cap plus the slack. Only `run_loop` calls it.
15. **I did not commit this brief.** It is outside §3, as with routes 94, 104 and 114.

## §0 as-built at `e028795` (L-30)

1. **Confirmed.** `sed -n '/^  yorsie:/,/^$/p;/^  ai-foundation:/,/^$/p' config/repos.yaml`:
   ```
   yorsie:            worktree_mode: parallel / worktree_base: /home/gkassa/yorsie-toni
                      test_cmd: "cd yorsie && npm test" / build_gate_cmd: "cd yorsie && npm run build"
   ai-foundation:     project_dir: /home/gkassa/spectricom-ai-foundation / worktree_mode: single-stream
                      test_cmd: ". venv/bin/activate && PYTHONPATH=. pytest"
                      build_gate_cmd: ". venv/bin/activate && PYTHONPATH=. pytest -q"
   ```
   (Both blocks verbatim, comments omitted. ai-foundation has no `worktree_base`.)
2. **Confirmed, and the answer is that the main checkout is fast-forwarded in place.**
   - `set_active_repo` reads `WORKTREE_MODE` (`orchestrator.py:181`).
   - `run_batch` (`:4298`): `parallel`, no worktree, not a meta-fire ⇒ `_create_route_worktree` (`:1556`). That runs `git worktree add --detach <worktree_base>/<stem> main`, then `_link_unit_deps(PROJECT_ROOT, wt)` (`:1577`), which links `node_modules`, `venv`, `.venv` and `yorsie/node_modules` from the main checkout.
   - `_run_batch_inner` cuts the branch there, runs Toni, `git add -A` (`:4511`), and gates with cwd = the worktree.
   - The merge is `_land_from_route_worktree` (`:1625`). It merges on a detached HEAD in the worktree, then `holder = _checkout_holding(main)` (`:1652`). If a checkout holds `main`, it runs `git merge --ff-only` **in that checkout** (`:1654`). Only otherwise does it run `update-ref` (`:1656`).
   - `_finish_route_worktree` (`:1583`) then unlinks the links and removes the worktree.
   - **Plainly:** after every merge, the main checkout's working tree advances to the merged commit, with whatever the route committed, including a dependency link git did not ignore (Found-and-LEFT 1). ai-foundation's checkout holds `main` (`refs/heads/main`, `4f348510`).
3. **Confirmed.** `systemctl --user cat minig-listen-worker.service minime-listen-ingest.service` gives:
   - `WorkingDirectory=/home/gkassa/spectricom-ai-foundation`, `ExecStart=/home/gkassa/spectricom-ai-foundation/venv/bin/python -m src.minime.listen.worker` (`Restart=on-failure`, `RestartSec=10`).
   - `WorkingDirectory=/home/gkassa/spectricom-ai-foundation`, `ExecStart=/home/gkassa/spectricom-ai-foundation/venv/bin/python -m src.minime.listen_ingest` (`Type=oneshot`, run by `minime-listen-ingest.timer`, `EnvironmentFile=-/home/gkassa/spectricom-ai-foundation/.env`).
   - `is-active`: worker `active`, ingest `failed` (Found-and-LEFT 4).
4. **Confirmed.**
   - `queue_daemon.py:912` `def _fire_locks(self, repo: str)`; `:925` `own = state_dir / f"running-{_marker_slug(repo)}.json"`; `:940-942` `def _fire_lock_held(self, repo)` → `return bool(self._fire_locks(repo))`; `:1027` `while self.status == "running" and (held := self._fire_locks(lane))`. Nothing global.
   - A direct run: `orchestrator.py:5270` `_check_stale_marker(ACTIVE_REPO_NAME)` → `_lock_candidates(repo_name)` (`:1422`) returns only that repo's lock, or a mirror naming it.
   - The daemon's kill was `queue_daemon.py:444` `"timeout_seconds": 11400` → `:1157` `proc.wait(timeout=timeout)`.

## Shipped

### C1 · global admission, one place (`admission.py`, new)
- `admit(repo, batch=None, *, claim=False, …) -> (ok, reason)`. Both limits are read from `config/repos.yaml` `admission:` at every call:
  - **Route limit:** refused when live routes ≥ `max_concurrent_routes` (shipped 1; anything but an int ≥ 1 means 1). A live route is any `state/running-*.json`, `state/running.json`, root `running*.json` or claim whose pid is alive; P-STALE's rule judges the pid. One process is one route, so a direct run's three markers count once.
  - **Memory floor:** refused when `MemAvailable` in `/proc/meminfo` < `min_mem_available_gib` (shipped 6). An unreadable figure is refused, never guessed.
- **Claims.** `state/admitted-<pid>.json` is written under `state/admission.lock` in the same breath as the yes, so the slot is held before the route's own lock exists.
  - The daemon claims for the route it fires and passes `ORCH_ADMISSION_CLAIM=<path>` on the command line.
  - The route's `run` adopts that claim (its pid becomes the route's) instead of asking again, so a daemon-admitted route is never refused by its own second look.
  - The daemon removes the claim when the route returns, and `run` removes its own at exit.
- **Daemon** (`queue_daemon.py` fire loop): the daemon asks after the per-repo fire lock is clear and the header has been re-read. A refusal waits: nothing fires, the brief stays first, there is no failure and no pause, and the daemon asks again each cooldown (`cooldown_seconds`, else 5 s). Strings, verbatim:
  - Logged once per change of reason (a moving MemAvailable figure is not a change): `[QUEUE] 🛡 admission: waiting before <brief> — <reason>`
  - Status line 1 ends `| waiting: <brief> — <reason>` (shown only while the daemon is `running`); `waiting` is in `status --json`.
  - At fire: `[QUEUE] 🛡 admission: admitted <repo> — <n> live route(s) < admission.max_concurrent_routes <m>; MemAvailable <x> GiB >= admission.min_mem_available_gib <f> GiB`
  - At start: `[QUEUE] 🛡 admission: at most <m> live route(s) across every repo, and MemAvailable >= <f> GiB — config/repos.yaml `admission:`, read at each fire; a refusal waits (ORCH-CAPACITY-1 C1)`
- **`orchestrator.py run`:** the call sits after `_check_stale_marker`, so a same-repo lock is still exit 4 and answers first.
  - Refusal: `⛔ ADMISSION — <reason> — refused, nothing fired (wait, or --force)` on stderr and in the log, then exit 2.
  - Admitted: `🚦 admission: <reason>`. The `🛡` prefix is reserved for the controls `test_control_verdict_lines` pins.
  - `--force`: `--force: admission BYPASSED — it would have refused: <reason>` (or `it admits anyway`), as a warning, A2/A8's convention. It still claims, so others see the route.
- **Reasons, verbatim shape:**
  - `route limit — 1 live route(s), admission.max_concurrent_routes 1: clinical-mp 110-visit-release-safety-1 (pid 55741, state/running-clinical-mp.json) — ai-foundation waits`
  - `memory floor — MemAvailable 4.0 GiB < admission.min_mem_available_gib 6 GiB (/proc/meminfo) — clinical-mp waits`
- **CLI, read-only:** `python3 admission.py [--orch-dir D] check <repo>` (exit 0 / 2) and `routes [--repo R]` (exit 0 none / 1 some). `aif-deploy.sh` uses `routes`.

### C2 · the ai-foundation gate in a worktree (`config/repos.yaml`), flip stopped
- `test_cmd: ". /home/gkassa/spectricom-ai-foundation/venv/bin/activate && PYTHONPATH=. pytest"`, and `build_gate_cmd` the same with `-q`.
- I picked the absolute path over the link: the link is exactly what Found-and-LEFT 1 found.
- No gitignored path is needed. The real suite ran green in a fresh worktree and left `git status` clean.
- `worktree_base: /home/gkassa/aif-toni` is staged; `worktree_mode` stays `single-stream` (Found-and-LEFT 1).

### C3 · `scripts/aif-deploy.sh` (new)
- Dry-run by default; `--apply` acts. It resolves the checkout and `<remote>/<merge_target>` from `config/repos.yaml`.
- **Refuses with exit 2, changing nothing:**
  - a live ai-foundation route or claim;
  - a Listen sitting `recording` or `transcribing`, by the worker's own status rule (Found-and-LEFT 3);
  - an unreadable sitting;
  - tracked changes in the checkout;
  - no `origin/main`, or one that is not a fast-forward of HEAD.
- **Prints** the checkout, its branch and HEAD, what `origin/main` brings in (`git log --oneline`), every command, `not rerun: minime-listen-ingest`, and the NOTE from Found-and-LEFT 2 when the checkout has `main` checked out.
- **The commands:**
  - `git -C <aif> merge --ff-only <sha>`. The sha is resolved at plan time, so the plan and the act agree.
  - `systemctl --user restart minig-listen-worker.service`, and nothing else.
- It does not fetch: it deploys `origin/main` as last fetched or pushed.

### C4 · the route wall (`admission.route_wall`, `queue_daemon.py` `_run_route`)
- **The wall** = the brief's route timeout + the repo's gate budget + `ROUTE_WALL_SLACK_S` (900 s).
  - The route timeout uses orchestrator's `resolve_timeout` rule: `TONI_TIMEOUT_MIN` > brief-declared > 45, capped at 180. The daemon's environment is the route's.
  - The gate budget is `admission.gate_budget_s`, else the sum of the repo's gate timeouts: each `PRE_MERGE_GATES` leg, plus branch, baseline and confirm when it declares `test_cmd`, with its `repos.yaml` overrides.
- **orchestrator.py's numbers are restated** (importing it writes a log). `TestP7 test_the_restated_clocks_are_orchestrators` and `test_the_route_timeout_is_orchestrators_own` pin them against orchestrator's own.
- **Shipped walls:**
  - clinical-mp: 5100 s budget.
  - orchestrator: 3600 s.
  - ai-foundation: 3000 s.
  - yorsie: 3600 s (build 600, plus the three unit legs, because it declares `test_cmd`).
  - Route 122 (162 min) gets 9720 + 5100 + 900 = **15720 s (262 min)**, against 11400.
- **Polling.** `_run_route` polls `ROUTE_CLOCK` (bound to `time.monotonic` at import) every `ROUTE_POLL_S` (30 s), and kills only past the deadline. The kill, said in the daemon log and written into the route log before the unchanged trailer:
  - `[QUEUE] ⏱ ROUTE WALL — the daemon's route wall fired on <brief> after <s>s, in phase <phase>; the wall: <describe>. orchestrator.py's own clocks (Toni, each gate leg) had not ended the route. Killing.`
- **Status and start lines.** `current_batch.wall` is in `status`. At fire: `[QUEUE] ⏱ route wall 15720s (262m) = route timeout 162m (brief-declared) + gate budget 5100s (the sum of its gate timeouts: build 600s + sit 600s + unit 1800s + unit-baseline 1800s + unit-confirm 300s) + 900s slack`. At start: `[QUEUE] 🛡 route-wall: per route — … (ORCH-CAPACITY-1 C4); persisted timeout_seconds=11400 not applied`.
- **`timeout_seconds` is gone from the defaults.** A persisted value is no longer applied, and the first save drops it. `config timeout_seconds …` is refused with the new rule; its message still names `queue_daemon.py` and the 180-minute cap.

## Gate table

| Gate | Result |
|---|---|
| Ancestry | `e0287955` is an ancestor of HEAD ✓; HEAD was `e028795` at fire |
| `pytest -q tests/` at `e028795` | **996 passed** in 142.58 s |
| `tests/test_capacity.py` RED: `e028795` code + the new `admission.py`, tests and conftest, in a temp worktree of this repo (removed, pruned) | **30 failed, 36 passed** (66). The 36 that pass are `admission.py`'s own unit tests, which exist only because the module was copied in, plus the negative controls and the hazard characterisation. Without `admission.py` all 66 fail at import |
| `tests/test_capacity.py` GREEN at `fb0fa69` | **66 passed** |
| `pytest -q tests/` at `fb0fa69` | **1062 passed** in 138.26 s: 996 + 66, 0 removed, 3 changed (Found-and-LEFT 6) |
| C2 live gate proof | `git clone ~/spectricom-ai-foundation` to `/tmp`, then `git worktree add --detach … main` (`4f348510`), with no `venv/` (`ls: cannot access 'venv'`). The shipped `test_cmd` under `/bin/sh` with `HOME` set to a temp dir: **exit 0, 830 passed, 33 skipped, 223 s**; `git status --porcelain` empty after. The clone was removed |
| Venv-link hazard probe (temp repos) | `.gitignore: venv/` + a `venv` symlink → `?? venv`, `check-ignore` exit 1. Committed in a worktree, then `git merge --ff-only` in the main checkout: `create mode 120000 venv`, and the ignored `venv/` directory was replaced |
| Live, read-only | `python3 admission.py routes` → `orchestrator 123b-orch-capacity-1 (pid 7548, state/running-orchestrator.json)`, exit 1: one route from three markers. `check ai-foundation` → `route limit — 1 live route(s) … — ai-foundation waits`, exit 2. `ORCH_DIR=~/spectricom-orchestrator scripts/aif-deploy.sh` → exit 2 (Found-and-LEFT 3). MemAvailable 9.3 GiB during this route |
| ai-foundation untouched | Before and after: HEAD `4f348510` on `main`; `git --no-optional-locks status --porcelain --untracked-files=no` empty; `worktree list` the same 2 entries. No unit file was touched, and no service was restarted |
| Diff bounded to §3 | `admission.py` (new); `queue_daemon.py` (fire loop, status, route wall, and dropping the fixed `timeout_seconds` that C4 replaces); `orchestrator.py` (the import, and the `run` admission call with its `--force` log: 14 added lines); `config/repos.yaml` (the `admission:` block and the ai-foundation block); `scripts/aif-deploy.sh` (new); `tests/**`. No merge or gate semantics, worktree code, systemd unit or other repo's config changed |
| Handback guard (`config/handback-guard.json`, 6 rules, `canon_assert.check_handback_invariants`) | this file: **CLEAN** |
| Destructive operations | **None.** Every daemon, marker, git and deploy write in the tests ran under `tmp_path`. My temp clone and the RED worktree were removed. The only processes signalled were the tests' own `sleep` fixtures. Nothing in `~/spectricom-orchestrator` was written: `routes` and `check` take no lock and write no claim. The shared stash list is unchanged (2 entries before and after) |

| Predicate | Tests (`tests/test_capacity.py`) | RED at `e028795` (one line) | GREEN | Negative control |
|---|---|---|---|---|
| **P1** (C1a) | `TestP1RouteLimit`, 10 | daemon: `AssertionError: nothing fired … assert (['120-minime-x-1.md'] == []`. Direct run: `assert 0 == 2`; end to end: `assert 1 == 2`. Base went on to `Pre-fire assertions FAILED`, past where admission now stands | ✓ `admit("ai-foundation")` names `clinical-mp 110-visit-release-safety-1 (pid …, state/running-clinical-mp.json)`. The daemon does not fire, and status line 1 shows `waiting: …`. Six re-checks give two lines (route limit, then memory floor). `run --repo ai-foundation` exits 2, both in-process and as the real CLI in a copy of the repo. A direct run's three markers count as one route | a dead-pid marker ⇒ admitted, and the daemon fires ✓. A dead-pid marker ⇒ direct run exits 0 ✓. `--force` ⇒ runs, and the warning starts `--force: admission BYPASSED — it would have refused: route limit` ✓. A same-repo lock ⇒ still exit 4 ✓ |
| **P2** (C1b) | `TestP2MemoryFloor`, 6 | the daemon test fired: `assert ['120-minime-x-1.md'] == []` | ✓ 4 GiB, floor 6 ⇒ `memory floor — MemAvailable 4.0 GiB < admission.min_mem_available_gib 6 GiB (…)`. With the floor changed in config: 3 ⇒ admitted, 5.5 ⇒ refused. The daemon waits on the floor. The real `/proc/meminfo` parses | 8 GiB ⇒ admitted ✓. An unreadable MemAvailable ⇒ refused, never guessed ✓ |
| **P3** (C1) | `TestP3Limit`, 14 | `KeyError: 'admission'` (shipped config); `test_the_daemon_names_its_claim_to_the_route_and_releases_it` failed: the base command names no claim | ✓ `max_concurrent_routes: 2` with one live route ⇒ admitted. Shipped `(1, 6.0)`. A live claim is a route. The daemon's claim is adopted by its route (pid handed over) and released when the route returns | 6 malformed limits ⇒ 1 ✓. A claim for another brief is not adopted ⇒ refused ✓ |
| **P4** (C2) | `TestP4AifWorktree`, 6; `TestP4VenvLinkHazard`, 2 | `assert (PosixPath('/home/gkassa/spectricom-ai-foundation') / '125-minime-console-1') == PosixPath('/home/gkassa/aif-toni/125-minime-console-1')`. The base `test_cmd` is relative | ✓ the staged block, flipped in a copy, resolves to `/home/gkassa/aif-toni/<route>`. The shipped command through `_run_unit_suite` is green in a git worktree with no `venv/` (fixture venv), and verbatim with the real venv (no bytecode). The tree is clean after | the relative command fails there ✓. The tripwire pins `single-stream` ✓. Hazard: `venv/` ⇒ `?? venv`; `venv` ⇒ clean (both pass at base: they describe orchestrator as it is) |
| **P5** (C3) | `TestP5AifDeploy`, 7 | `bash: …/scripts/aif-deploy.sh: No such file or directory`, `assert 127 == 2` | ✓ a live ai-foundation marker ⇒ exit 2, for both the dry-run and `--apply`, with HEAD, the tree and systemctl untouched. The dry-run prints `git -C <aif> merge --ff-only <sha>` and `systemctl --user restart minig-listen-worker.service`, with nothing changed. `--apply` ⇒ HEAD = `origin/main`, and systemctl is called once with `--user restart minig-listen-worker.service` | a `recording` sitting ⇒ 2 ✓. An unreadable sitting ⇒ 2 ✓. Tracked changes ⇒ 2, and the edit is kept ✓. Not a fast-forward ⇒ 2 ✓ |
| **P7** (C4) | `TestP7RouteWall`, 21 | fake clock: `AttributeError: … has no attribute 'ROUTE_CLOCK'`; base `_run_route` was `proc.wait(timeout=11400)`. Persisted `timeout_seconds` applied: `assert 'timeout_seconds' not in {…}`. In production, route 122's log: `21:15:33 🧪 Unit baseline gate [clinical-mp]` … `Exit: -1 (timeout after 11400s)` | ✓ a 162-min brief ⇒ `route_timeout_s` 9720 (brief-declared) + 5100 + 900 ≥ 162 min + budget, and > 11400. The route-122 timeline on a fake clock is in phase `unit` and waited on across 11400 s, then exits 0 at 215 min with nothing killed. The daemon records the wall from the brief it fires. The route timeout and the gate clocks match orchestrator's own | a route that never ends ⇒ killed at exactly `wall.seconds`, exit -1. The daemon log and the route log both carry `⏱ ROUTE WALL — the daemon's route wall fired on 122-organ-fat-1.md after 15720s, in phase unit; …`, then `Exit: -1 (timeout after 15720s)` ✓ |
| **P6** | full suite | n/a | **1062 passed**. Per-repo lock: `test_orch_lane` P1 (with limit 2) and `TestP1 test_the_per_repo_lock_still_answers_first` (exit 4). A1/A2/A8 tests unchanged and green | — |

## THE CONSEQUENCE (D-S7CORE13-03)

**From the next fire after this merges, before any restart.** Every route is a new `orchestrator.py run` process:
- A direct `orchestrator.py run` is admitted or refused (exit 2) by `config/repos.yaml` `admission:`. `--force` bypasses and says so.
- ai-foundation's unit gate runs `. /home/gkassa/spectricom-ai-foundation/venv/bin/activate && PYTHONPATH=. pytest`. Its routes still run single-stream in the main checkout, and the first one re-measures its baseline (Found-and-LEFT 12).
- `scripts/aif-deploy.sh` exists. Nothing runs it.

**After Gemma restarts the daemon (L-29, L-46): pause → restart → resume.** The live daemon is pid **26875**, `python3 -u queue_daemon.py` in `~/spectricom-orchestrator`, logging to `~/_eos/logs/s7core14-queue-daemon2.log`, started 4 Oct 23:22. No systemd unit (`spectricom-queue-daemon.service`: `not-found`).
1. **After this route has merged to `main`:** `cd ~/spectricom-orchestrator && python3 queue_daemon.py status` must show `"current_batch": null`.
2. **Pause:** `python3 queue_daemon.py pause` → `acknowledged request …`.
3. **Stop:** `kill 26875`, or the pid from `status` line 1.
4. **Re-queue what you want fired**, in the order you want: `mv queue/held/s7c21-restart/<brief>.md queue/`. 125, 126 and 128 are ai-foundation and would run single-stream (Found-and-LEFT 1).
5. **Start:** `nohup python3 -u queue_daemon.py >> ~/_eos/logs/s7core21-queue-daemon.log 2>&1 &`. The start lines now include:
   - `[QUEUE] 🛡 admission: at most 1 live route(s) across every repo, and MemAvailable >= 6 GiB …`
   - `[QUEUE] 🛡 route-wall: … ; persisted timeout_seconds=11400 not applied`
   - With work queued, it comes up `PAUSED (start:queue-non-empty)`.
6. **Resume:** `python3 queue_daemon.py resume --reason start:queue-non-empty`.
7. **Check:** `status` line 1 shows the new pid `alive`. While a route runs, `current_batch.wall.describe` names its wall. While admission holds the next brief, line 1 ends `| waiting: <brief> — <reason>`.

**The first `aif-deploy.sh` dry-run** (Gemma or George; read-only):
`cd ~/spectricom-orchestrator && scripts/aif-deploy.sh`

Today it refuses on sitting `20261005-150302-3a4c6dc7ccf2` (`recording`), exit 2. Once that sitting is closed and no ai-foundation route is live, it prints the plan. `scripts/aif-deploy.sh --apply` acts on it.

**George's calls:**
- ai-foundation `.gitignore:1` `venv/` → `venv`, then the one-line C2 flip (Found-and-LEFT 1).
- Whether to detach `~/spectricom-ai-foundation` from `main`, so that only `aif-deploy.sh` moves the services (Found-and-LEFT 2).
- The `recording` sitting (Found-and-LEFT 3).
