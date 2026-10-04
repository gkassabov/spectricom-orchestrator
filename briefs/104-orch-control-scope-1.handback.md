# filename: briefs/104-orch-control-scope-1.handback.md

# 104 · ORCH-CONTROL-SCOPE-1: handback

The brief asked for one increment in six parts: the queue's controls tell the truth. All six are in, plus the unit (C7a), shipped and not installed. Two §0 items needed correcting: §0.7 (there is no code-level clean-tree check) and §0.4's cause. One consequence goes beyond what the brief expected: `orchestrator.py` and `prefire.py` load fresh for every route, so A1, the Yorsie worktree and the parallel gate take effect at **the next fire after this merges, not at the daemon restart**. That is Found-and-LEFT item 1.

- **Branch:** `orch-orch-104-orch-control-scope-1`, from `71cef01`. Ancestry checked: `git merge-base --is-ancestor 71cef01 HEAD` ✓, and HEAD was `71cef01`.
- **Commits:** `5ba410f` has the code and tests; the second commit is this file.
- **Tests:** `pytest -q tests/` gave 871 passed at `71cef01` and **935 passed** at `5ba410f`. The delta is +64, all in the new `tests/test_control_scope.py`; no existing test was removed.

## Found and LEFT

1. **A1, C4 and C5 are live at the next fire after the merge, before Gemma restarts the daemon.**
   - The daemon fires every route as a new `python3 -u orchestrator.py run …` process (`queue_daemon.py:774-778` at `71cef01`), and that process imports `prefire`.
   - So once this merges, the next route the *old* daemon fires is checked for A1, runs in a worktree if it is a Yorsie route, and the parallel lane is gated.
   - A brief refused at pre-fire exits 1. The old daemon's `stop_on_failure` then pauses the queue (`queue_daemon.py:815-817`). That is the same path an A2 refusal takes today.
   - C1, C2, C6 and C7b live in `queue_daemon.py` and take effect only after the restart (L-29). C7a takes effect only after George installs the unit.
2. **Two held briefs fail A1 (AC-104-10, below): `108-minig-listen-1.md` and `109-minime-rules-1.md`.**
   - Both are `repo=ai-foundation`, and their `## Kanban:` line is prose ("Kanban row to be added at S7-CORE-19 EOS").
   - No Kanban family covers MiniMe/ai-foundation work. `KANBAN_FAMILIES = ("SCP_Kanban", "Yorsie_Kanban")` (`prefire.py:46`) is the brief's list. Adding a family, or adding rows for these to SCP_Kanban, is George's call.
   - I did not edit the briefs (AC-104-10).
3. **A State cell reading `NOT READY` would pass A1.** The rule is as specified: the token `READY` is present and none of `MERGED`/`COMPLETE`/`CUT` is. Today `SCP_Kanban_v0-75.md` and `Yorsie_Kanban_v0-3.md` have 0 such cells (grep checked). Left as written.
4. **A row id that appears in two tables must be READY in every one.**
   - `Yorsie_Kanban_v0-3.md` lists Y-rows twice: a summary table (`State at EOS`) and the main table (`State`).
   - A1 reads every table whose header names a `state` column, and fails on the first row that is not READY. If the two tables disagree, the brief is refused. That is fail-safe, but a lagging summary table can block a fire.
5. **Dead-route recovery (C7b) runs only at daemon start.**
   - A route that dies while the daemon lives (the orchestrator killed, OOM) still leaves its tree dirty. The daemon's `stop_on_failure` pause covers it (the route exits non-zero), but the tree is not stashed until the next daemon start.
   - The `<ts>` in `route process died <ts>` is when the daemon **found** the route dead. The time of death is recorded nowhere.
6. **The dashboard's in-process daemon (`orch-dashboard.py --daemon`, `:901-902`) is not scoped by C1.**
   - Its HTTP resume calls `QueueDaemon.resume()` / `reset_consecutive()` directly (`:364`, `:370`). That is a click at the moment of action, not a stale request.
   - C2 does apply to it: started with work queued, it comes up paused.
   - The dashboard is not running now (`ps`). `orch-dashboard.py` is outside §3.
7. **Nothing stops two daemons.**
   - `install-queue-daemon-unit.sh` refuses to *start* the unit beside a live daemon.
   - Nothing stops a hand-run `python3 queue_daemon.py` beside a unit-started one. A single-instance guard (refuse to start while queue-state.json's `pid` is alive and not this process) is a follow-up.
   - The live daemon (pid 13818) logs to `~/_eos/logs/s7core14-queue-daemon2.log`. The unit logs to `logs/queue-daemon.log`.
8. **The Yorsie worktree lane, residuals in `orchestrator.py` that I left:**
   - `get_migrations()` (`:823` at `71cef01`) reads the main checkout. It never sees a migration the route adds in its worktree, so the "NEW MIGRATIONS — apply manually" warning cannot fire for a Yorsie route.
   - `run_playwright()` runs in `PROJECT_ROOT`. `RUN_PLAYWRIGHT` is the constant `False`.
   - `yorsie/.env` is not in the worktree: it is gitignored and not linked, because `env_file` is `None`. The executor, the build gate and the unit leg run without it. The unit leg's baseline already ran that way, in a detached worktree. `vite build` therefore inlines no `VITE_*` values into the gitignored `dist/`.
   - `node_modules` is a symlink in the worktree. `yorsie/.gitignore:10` reads `node_modules` with no trailing slash, so the symlink is ignored. If that line ever became `node_modules/`, the symlink would show as untracked and `git add -A` would commit it.
9. **The `parallel` lane's other residuals, left:**
   - `create_worktree` (`:1463`) branches from the main checkout's HEAD, not `MERGE_TARGET`.
   - `merge_branch` (`:1488`) merges into whatever that checkout has out.
   - All workers share one per-repo fire lock, and the first to finish releases it (`run_batch` → `_clear_running_marker`).
   - C5 gates the lane; it does not rebuild it.
10. **`status <anything but --json>` now prints usage (exit 0) instead of the status.** Before, extra arguments were ignored. Only `pause`/`resume` exit 2 (C6).
11. **A daemon that has not been restarted applies the new CLI's requests unscoped.** It ignores the `issued_*` fields. C1 holds from the restart on.
12. **This brief was not committed** (it is outside §3), as with route 94. The queue's copy is in `queue/`.

## §0 as-built at `71cef01` (AC-104-01)

1. **Confirmed.**
   - `_poll_control` (`queue_daemon.py:605`) returns only when `rid <= self.control_ack` (`:611`). Otherwise a `resume` reaches `(self.reset_consecutive if reset else self.resume)()` (`:620-621`), whatever the pause's reason and whenever the request was written.
   - The request carried `requested_at` (`:226`) and nothing about the state it was issued against.
   - Why request 9 waited: the loop does not poll while a route runs, because `_run_route` blocks. It polls again at `:700`, after `_mark_paused(f"stop-on-failure:{batch_name}")` (`:817`).
2. **Confirmed.** `run_loop` (`:676`) acknowledges a pending request (`:684-686`), then sets `self.status = "running"` unconditionally (`:688`).
3. **Confirmed.** `prefire.py:18`: "NOT enforced here (not decidable from the brief file): A1 Kanban READY, A3-A7, A9."
4. **Confirmed, with the cause named.**
   - `logs/yorsie/orch-97-yorsie-stability-1-20261004-044417.log:31` and `orch-98-android-release-1-20261004-051557.log:31` say `Project: /home/gkassa/spectricom-dev-pipeline`.
   - Cause: `run_batch` makes a worktree only for a meta-fire (`orchestrator.py:3886`), so `proj = worktree or PROJECT_ROOT` (`:3921`).
   - `WORKTREE_MODE` is assigned (`:180`) and read nowhere. `WORKTREE_BASE` is read only by `create_worktree` (`:1463`, the `parallel` subcommand).
   - `~/yorsie-toni` does not exist. The dev tree is on `main`, clean, and serves `yorsie-dev.service` (`WorkingDirectory=/home/gkassa/spectricom-dev-pipeline/yorsie`, vite dev on :5175).
5. **Confirmed: the `parallel` lane merges ungated.**
   - `run_parallel` (`:4379`) submits `run_batch(bf, wt)` (`:4397`).
   - With a worktree and no meta-fire, `_run_batch_inner` takes neither gate lane: the route lane needs `worktree is None` (`:4112`), the meta lane needs `IS_META_FIRE` (`:4270`). Its "produced work" is `ec == 0` (`:4062`).
   - `run_parallel` then calls `merge_branch(br)` (`:4408`) for every `passed` result. It also never commits a worker's uncommitted output.
6. **Confirmed.**
   - `main` (`:890`): `elif cmd in ("pause", "resume")` (`:913`) passes only `"--reset-consecutive" in argv[1:]` (`:914`). Every other argument, `--help` included, is ignored, and the request is written.
   - `status` prints `status_line(st)` (`:908`) and then the JSON (`:912`).
7. **Corrected in one place.**
   - Confirmed: nothing restarts the daemon. There is no unit for it under `~/.config/systemd/user` (linger is on for `gkassa`). And `_clear_stale_markers` (`:630`) only renames the marker (`:665`).
   - **Correction: there is no §23.1 clean-tree check in the code.** §23.1 is the System Prompt's pre-fire assertion, made by a human. What the code does with a dead route's dirty tree is worse than refusing:
     - The next route in that repo runs `git checkout -b <branch> <MERGE_TARGET>` (`orchestrator.py:3999`) in the dirty tree.
     - Git carries non-conflicting uncommitted changes onto the new branch, and `git add -A` (`:4116`) commits them into the **next** route.
     - If they conflict, the checkout fails. With no retired branch, `:4016` logs `Could not create branch … Running on current branch.` and the next route runs on the **dead route's** branch with no commit, gate or merge lane (`branch_name = None`).

## Shipped

### C1 · a control request is scoped to the state it was issued against
- `request_control` (`queue_daemon.py:211`) records `reason`, `issued_status`, `issued_paused_reason` and `issued_current_batch` (`:242-244`). `resume --reason <paused_reason>` names a pause explicitly.
- `_resume_expired` (`:655`) is checked before anything else in `_poll_control`:
  - A resume applies only while the daemon's `paused_reason` (None when not paused) equals the one it was issued under, or the one it names.
  - A `stop-on-failure:` pause is lifted only by a request whose `requested_at` is at or after that pause's `paused_at`, `--reason` included.
  - A request with no `issued_status` cannot be judged and expires.
  - `pause` is unchanged.
- New strings, verbatim:
  - `resume request <id> expired — issued while <issued state>, daemon now paused for <paused_reason>; nothing resumed`. `<issued state>` is `<status>[ (<paused_reason>)][ on <brief>][ (--reason <r>)][ before that pause began]`, or `an unrecorded state (a request with no issued_status)`. When the daemon is not paused, the tail reads `daemon now <status>; nothing resumed`.
  - The incident, as the test reproduces it: `resume request 1 expired — issued while running on 95-x.md, daemon now paused for stop-on-failure:95-x.md; nothing resumed`. The daemon logs `[QUEUE] control request 1: <that>`. The CLI prints `acknowledged request 1: <that> — <status line>` and exits 1.

### C2 · a starting daemon fires nothing until told, when work is queued
- `run_loop` (`:814-829`): C7b recovery first, then:
  - queue non-empty ⇒ `paused`, `paused_reason="start:queue-non-empty"` (`START_PAUSED_REASON`, `:65`);
  - empty ⇒ `running`.
- `python3 queue_daemon.py --start-running` keeps the old start. The unit never passes it.
- One line, verbatim:
  - `[QUEUE] 🛡 start: <n> brief(s) queued — PAUSED (start:queue-non-empty); nothing fires until `python3 queue_daemon.py resume` (or a start with --start-running)`
  - `[QUEUE] 🛡 start: queue empty — running`
  - `[QUEUE] 🛡 start: --start-running — running; <n> brief(s) queued fire now`
  - `[QUEUE] 🛡 start: PAUSED (start:dirty-tree:<repo>) — a dead route's repo is dirty and was left as it is; nothing fires until `python3 queue_daemon.py resume``

### C3 · A1 is machine-checked
- `prefire.check_kanban` (`prefire.py:185`) is called first in `check` (`:224`). It works as follows:
  - It reads the `## Kanban: <SCP_Kanban|Yorsie_Kanban> row <N>` header.
  - It resolves the newest `<family>_v*.md` in `kanban_dir` (`config/repos.yaml:9`, default `/mnt/c/Users/gkass/OneDrive/Documents/Spectricom`), by number, through `canon_assert.disk_family`. `_DRAFT_GEMMA`, `BAD` and `*bak` files are not members.
  - It reads the State column of every table whose header names `state` (`State`, `Runtime state`, `State at EOS`), via `kanban_states` (`:155`).
- New strings, verbatim:
  - `A1 KANBAN — <family> row <N> is <STATE>, not READY`. `<STATE>` is the first of `MERGED`/`COMPLETE`/`CUT` in the cell, else its first capitalised status word (e.g. `BACKLOG`, `LIVE`).
  - `A1 KANBAN — <family> row <N> is missing from <file>, not READY`
  - `A1 KANBAN — <family> row <N> is unreadable (no <family>_v*.md in <dir>), not READY`, or `(<file> unreadable in <dir>)`
  - `A1 KANBAN — no '## Kanban: <SCP_Kanban|Yorsie_Kanban> row <N>' header; a brief fires only from a READY Kanban row`
  - `A1 KANBAN — '## Kanban: <text>' names no Kanban row ('<SCP_Kanban|Yorsie_Kanban> row <N>'), not READY`
  - `A1 KANBAN — '## Kanban: <family> row <N>' names no Kanban family (SCP_Kanban or Yorsie_Kanban), not READY`
  - Pass: `  Assertions: ✅ A1/A2/A8 pass — SCP_Kanban row 145 READY (SCP_Kanban_v0-75.md); declared 75m (floor 30m)`
  - `--force` (`orchestrator.py:5009`): `--force: pre-fire assertions (A2/A8) BYPASSED; A1 Kanban READY not checked`. The route's error is now `pre-fire assertions failed (A1/A2/A8) — HOOK-1`.

### C4 · a Yorsie route runs in a worktree
- `run_batch` (`orchestrator.py:4074`): `WORKTREE_MODE == "parallel"`, no worktree passed, and not a meta-fire ⇒ `_create_route_worktree` (`:1532`):
  - It creates `<worktree_base>/<route>` with `git worktree add --detach … <MERGE_TARGET>`. A kept earlier one is never reused; the new one gets `-<ts>`.
  - It links `node_modules`/`venv` from the main checkout (`_link_unit_deps`, the unit baseline's rule).
  - `_run_batch_inner` then runs the route lane in it unchanged: branch cut, executor, commit, gate (the build gate's cwd is the worktree).
  - It never checks out `MERGE_TARGET` (`_leave_route_branch`, `:1591`).
  - A worktree that cannot be made is not fired, never redirected to the main checkout. A branch that cannot be cut in it is a stale-base refusal, never "running on current branch".
- The merge is `_land_from_route_worktree` (`:1601`, called at `:4362`):
  - It merges in the worktree on a detached HEAD at `MERGE_TARGET`, so a conflict is met and aborted there.
  - `MERGE_TARGET` then moves **by fast-forward only**: `git merge --ff-only` in the checkout that holds it, which refuses rather than overwrite a local change, or a compare-and-swap `update-ref` when none holds it.
  - The main checkout's branch is never switched. Its files change only when `main` fast-forwards after a PASS.
- `_finish_route_worktree` (`:1559`) unlinks the dependency links, then removes the worktree after a merge or a no-change run. Any other outcome keeps it, named in the log.
- The fire lock records `route_worktree`. `qstat.sh` counts uncommitted files there.
- New strings, verbatim:
  - `🌳 Route worktree: <wt> (from <target>; <n> dependency path(s) linked from <project>) — the main checkout is not the route's`
  - `🌳 Route worktree removed: <wt>`
  - `🌳 Route worktree preserved: <wt> (branch <branch>). After review: git -C <project> worktree remove <wt>`
  - `⛔ ROUTE WORKTREE — <why> — not firing.` (error `route-worktree: <why>`). `<why>` is one of:
    - `worktree_mode: parallel needs a worktree_base outside <project> (config/repos.yaml, repo <name>)`
    - `cannot create <base>: <e>`
    - `git worktree add <wt> <target> failed: <stderr>`
  - `🔀 Merged <branch> → <target> (<pre> → <post>) from the route worktree; <target> fast-forwarded in <checkout>`, or `… <target> ref moved (no checkout holds it)`
  - `⚠️ Merge conflict on <branch>, met in the route worktree <wt> — MANUAL RESOLUTION NEEDED`. The error is `MERGE CONFLICT — <branch> → <target> (<files>); gate was PASS`.
  - `NOT LANDED — <target> is checked out at <checkout> and did not fast-forward to the merged commit <sha7>: <git stderr>; gate was PASS`, and `NOT LANDED — the route worktree <wt> could not detach at <target>: <stderr>`
  - `could not cut <branch> from <target> in the route worktree <wt>: <stderr>`

### C5 · every lane is gated
- `run_parallel` (`:4589`) gates every `passed` branch in its own worktree **before any merge** with `_gate_parallel_branch` (`:1499`). That is the same `run_pre_merge_gates`, with the route lane's semantics: PASS merges; anything else preserves the branch with a git note.
- A worker's uncommitted output is committed on its branch first (the route lane's `git add -A`), so the gate judges what the merge brings in.
- New strings, verbatim:
  - `Gating each branch before any merge...`
  - `📦 Committed <br>'s uncommitted output before its gate`
  - `⛔ <outcome> — <target> NOT merged. Branch preserved: <br>. <verdict label>`
  - `⛔ Pre-merge gate raised on <br>: <e> → <verdict label>`

### C6 · CLI truth
- `_control_args` (`queue_daemon.py:1030`):
  - `pause` takes nothing.
  - `resume` takes `--reset-consecutive` and `--reason <paused_reason>`, each at most once.
  - Anything else, `--help` and `-h` included, prints usage to stderr and exits 2 with nothing written.
- `status --json` (`:1062`) prints the JSON alone; plain `status` is unchanged.
- Usage, verbatim: `Usage: python3 queue_daemon.py [--start-running] | enqueue <file> | status [--json] | pause | resume [--reset-consecutive] [--reason <paused_reason>] | config <key> <value> | check | check-logs | clear`, then `  With no command it runs the daemon loop: paused at start when work is queued; --start-running fires the queue at once.`

### C7 · a WSL restart loses no work
- **(a) The unit, shipped and not installed.** `systemd/spectricom-queue-daemon.service`:
  - `ExecStart=/usr/bin/env -u ANTHROPIC_API_KEY /usr/bin/python3 -u @ORCH_DIR@/queue_daemon.py`
  - `UnsetEnvironment=ANTHROPIC_API_KEY`
  - `Environment=PATH=@DAEMON_PATH@`, from `daemon_path` (`config/repos.yaml:14`): the live daemon's nvm bin, `~/.local/bin` for `claude`, then the system paths
  - `Restart=on-failure`
  - `KillMode=process`, so a daemon restart never kills the route it launched
  - `WantedBy=default.target`
- `scripts/install-queue-daemon-unit.sh` renders the unit into `~/.config/systemd/user`, runs `daemon-reload` and `enable`, and **never starts it**. Its output, verbatim:
  - `✅ wrote <dest>/spectricom-queue-daemon.service (ExecStart <orch>/queue_daemon.py, ANTHROPIC_API_KEY unset)`
  - `✅ enabled spectricom-queue-daemon.service — the next boot starts the daemon; it comes up paused when work is queued`
  - With a live daemon: `⚠️  a daemon is running now (pid <pid>) — the unit is enabled, NOT started:` / `   two daemons would both fire. To hand over: stop pid <pid> while no route runs, then` / `   systemctl --user start spectricom-queue-daemon.service`
  - Without one: `   no daemon is running — start it now with: systemctl --user start spectricom-queue-daemon.service`
  - On a config error: `⛔ config/repos.yaml has no daemon_path — the unit's PATH comes from there; nothing installed`
- **(b) Recovery at start.** `_recover_dead_routes` (`queue_daemon.py:728`) takes each marker P-STALE clears (`_clear_stale_markers` now returns them) and calls `_recover_dead_route` (`:747`) on the repo's `repos.yaml` entry, never a path the marker names:
  - Clean ⇒ nothing.
  - Dirty on the route's own branch ⇒ `git stash push -u -m "<route> partial WIP (route process died <ts>), recovered by daemon start"`, `git branch -m <branch> <branch>-died-<ts>`, `git checkout <merge_target>`.
  - Dirty on any other branch ⇒ untouched, and the start pauses `start:dirty-tree:<repo>`.
  - A marker with `meta_fire_worktree` or `route_worktree` is skipped: that route never had the main checkout.
  - No `reset --hard`, `clean`, `checkout -- .` or branch delete; a source scan in the tests asserts it.
- New strings, verbatim:
  - `[QUEUE] 🛡 dead-route-recovery: <repo> — <route>'s uncommitted work stashed as <sha12> (<route> partial WIP (route process died <ts>), recovered by daemon start); branch <branch> → <branch>-died-<ts>; <merge_target> checked out in <path>`
  - `[QUEUE] 🛡 dead-route-recovery: <repo> — <path> is dirty on <head>, not on <route>'s branch <branch>; left as it is — PAUSED (start:dirty-tree:<repo>)`
  - `[QUEUE] 🛡 dead-route-recovery: <repo> — <path> is dirty on <branch> and `git stash push -u` did not leave it clean (<err>); left as it is — PAUSED (start:dirty-tree:<repo>)`
  - `[QUEUE] 🛡 dead-route-recovery: <repo> — <route>'s uncommitted work stashed as <sha12> (<msg>); the <rename|checkout> after it failed (<err>) — PAUSED (start:dirty-tree:<repo>)`
  - `[QUEUE] 🛡 dead-route-recovery: <repo> — not in <repos.yaml>; its tree is not inspected` and `… <path> could not be read (<err>); not inspected`

### Existing tests touched (one line each, no expectation changed)
- Five daemon harnesses fire queued briefs at start: `test_executor_default.py`, `test_queue_gate_log.py`, `test_queue_pause.py`, `test_timeout_hold.py` and `test_yorsie_safety.py`. Each now sets `start_running = True` — the harness is "an operator who means it".
- `test_prefire.py` gives its A2/A8 briefs a `## Kanban:` line, and an autouse fixture supplies a scratch READY row.

## Gate table

| Gate | Result |
|---|---|
| Ancestry | `71cef01` is an ancestor of HEAD ✓ |
| `pytest -q tests/` at `71cef01` | **871 passed** |
| `tests/test_control_scope.py` against untouched `71cef01` (RED) | **49 failed, 15 passed** (64), run in a throwaway worktree of `71cef01` that was removed after |
| `tests/test_control_scope.py` at `5ba410f` (GREEN) | **64 passed** |
| `pytest -q tests/` at `5ba410f` | **935 passed**: 871 + 64 new, 0 removed |
| Diff bounded to §3 (AC-104-11) | `queue_daemon.py`, `orchestrator.py`, `prefire.py`, `config/repos.yaml`, `qstat.sh`, `systemd/spectricom-queue-daemon.service` (new), `scripts/install-queue-daemon-unit.sh` (new), `tests/**`. `repo_config.py` is unchanged. |
| Handback guard (`config/handback-guard.json`, via `canon_assert.check_handback_invariants`) | the closing message and this file: **CLEAN** |
| Destructive operations | **None.** Stash and rename ran only in tmp fixture repos. Nothing was written to a product repo, `~/.config` or the live queue. No process was signalled. The shared stash list is unchanged (2 entries before and after). |

**The 15 that passed on `71cef01`** are negative controls, or cases the old code already got right by accident:
- P1: a resume issued after the pause; an explicit reason that matches; one named after the failure; pause unscoped.
- P3: a READY row; the per-table State column; a Yorsie row; A2 still reported.
- P4: single-stream runs in the main checkout.
- P5: two green branches both merge.
- P6: a bare `pause` writes; plain `status`.
- P7: a clean tree; a live route; a worktree route.

Two other P2 negative controls, an empty queue and `--start-running`, failed on `71cef01` **only** because the new `🛡 start:` line was absent. Their behaviour assertions (running; both briefs fire) held on the old code.

| Predicate | RED at `71cef01` (one failure line) | GREEN | Negative control |
|---|---|---|---|
| **P1** (C1) | `assert ['95-x.md', '96-y.md'] == ['95-x.md']`: the old code fired 96 on the resume issued while 95 ran | ✓ | the same request issued after the pause resumes, and 96 fires ✓ |
| **P2** (C2) | `assert ['95-x.md', '96-y.md'] == []`: the old code fired both at start | ✓ | an empty queue ⇒ `running`; `--start-running` fires both ✓ |
| **P3** (C3) | `SCP_Kanban row 2/3/4/5`, missing row and no header all returned `[]` (a silent pass) | ✓, exact strings | a READY row passes; Yorsie row Y10 passes ✓ |
| **P4** (C4) | `Toni ran in …/dev-pipeline, not the route worktree` | ✓ dev tree stays `main`/unchanged/clean while running; build cwd = `<wt>/yorsie` on `orch-batch-wt` with deps; merged ⇒ ff, worktree removed; red ⇒ kept and named; conflict ⇒ met in the worktree; a dev-tree file in the way ⇒ `NOT LANDED`, nothing changed | single-stream: the route branch is checked out in the main checkout ✓ |
| **P5** (C5) | `the red branch must not merge — assert not True` | ✓ all gates before the first merge, each in `wts/toni-N`; red preserved with its commit | two green ⇒ both merge ✓ |
| **P6** (C6) | `assert 1 == 2` for `main(['pause', '--help'])`: the old code wrote a pause request and waited for its ack. `status --json`: `JSONDecodeError: Expecting value: line 1 column 1` | ✓ exit 2, byte-identical, for 8 argument shapes; the brief's own pipe exits 0 | a bare `pause` writes request 4; plain `status` keeps line 1 ✓ |
| **P7** (C7b) | `assert 0 == 1` (`len(stash list)`); dirty-on-main: `assert ('running', None) == ('paused', 'start:dirty-tree:clinical-mp')` | ✓ one stash `On orch-mp-101-clip-truth-2: 101-clip-truth-2 partial WIP (route process died <ts>), recovered by daemon start` holding the tracked edit and the untracked file; branch → `-died-<ts>` at the same tip; `main` checked out; tree clean | clean tree ⇒ untouched; live pid ⇒ untouched; worktree route ⇒ untouched ✓ |
| **C7a** | the files did not exist | ✓ rendered under a tmp `HOME` with a fake `systemctl`: calls `--user daemon-reload` and `--user enable …` only, never `start` | a dead pid ⇒ still enable-only, with the start command printed ✓ |

## AC-104-10 · the existing queue under the new A1 (read-only: `python3 prefire.py <file>`, nothing edited)

| Brief | Where | `## Kanban:` | A1 |
|---|---|---|---|
| `104-orch-control-scope-1.md` | `queue/` | `SCP_Kanban row 145 (READY)` | ✅ `SCP_Kanban row 145 READY (SCP_Kanban_v0-75.md); declared 75m` |
| `105-messaging-draft-truth-1.md` | `queue/held/` | `SCP_Kanban row 144 (READY)` | ✅ `SCP_Kanban row 144 READY (SCP_Kanban_v0-75.md); declared 45m` |
| `108-minig-listen-1.md` | `queue/held/` | `MiniMe lane — George go in chat 2026-10-04 (…); Kanban row to be added at S7-CORE-19 EOS` | ⛔ `A1 KANBAN — '## Kanban: MiniMe lane — …' names no Kanban row ('<SCP_Kanban|Yorsie_Kanban> row <N>'), not READY` |
| `109-minime-rules-1.md` | `queue/held/` | `MiniMe lane — George go in chat 2026-10-04; Kanban row to be added at S7-CORE-19 EOS` | ⛔ the same |

`queue/` holds only 104 (this route). Every file parses.

## THE CONSEQUENCE (D-S7CORE13-03)

**From the next fire after this merges, even before the restart:**
- A brief without a READY Kanban row named in its header is refused at pre-fire. **Every brief in `queue/` needs a `## Kanban: <SCP_Kanban|Yorsie_Kanban> row <N>` line naming a READY row, or it is refused.** Today that means 108 and 109 in `queue/held/` (table above).
- A refusal exits 1, and the running daemon's `stop_on_failure` pauses the queue on it.
- Yorsie routes stop touching the dev tree:
  - They run in `~/yorsie-toni/<route>`, with `node_modules` linked from the dev tree.
  - `main` in `~/spectricom-dev-pipeline` moves only by fast-forward after a PASS.
  - A red route's worktree stays in `~/yorsie-toni/` until someone removes it.
- `orchestrator.py parallel` gates every branch before it merges any.

**After Gemma restarts the daemon (L-29):**
1. A resume issued before a failure can no longer release the stop-on-failure pause. It expires and says so. A `resume` must be issued after the pause it means; `--reason <paused_reason>` names one explicitly.
2. The restarted daemon comes up **paused** (`start:queue-non-empty`) when work is queued, and needs `python3 queue_daemon.py resume` to fire. `--start-running` keeps the old start.
3. `pause --help` (or any argument `pause`/`resume` does not take) prints usage and exits 2, and writes nothing. `status --json` is machine-readable.
4. At each start, a route that died with its branch checked out and work uncommitted is recovered into a named stash, with its branch renamed `-died-<ts>`.
   - A dirty tree the daemon cannot attribute is left alone, and the start pauses `start:dirty-tree:<repo>`.
   - Recovered work comes back with `git stash list` → `git stash apply <sha>` on the `-died-` branch. That is an operator act; the daemon never applies or drops a stash.

**After George installs the unit:** a WSL restart restarts the daemon itself. It comes up paused when work is queued, after recovering any dead route's tree into a named stash.

**George's step:**
```bash
cd ~/spectricom-orchestrator && bash scripts/install-queue-daemon-unit.sh
```
- It enables the unit for the next boot and does not start it beside the hand-run daemon (pid 13818 today).
- To hand over now: stop that daemon while no route runs, then `systemctl --user start spectricom-queue-daemon.service`. Gemma's restart (L-29) is the natural moment.
