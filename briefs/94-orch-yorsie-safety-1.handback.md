# filename: briefs/94-orch-yorsie-safety-1.handback.md

# 94 · ORCH-YORSIE-SAFETY-1: handback

The brief asked for three things: a brief that names no repo is refused, Yorsie merges only what builds, and `qstat.sh` shows the daemon's real state. All three are in. One premise in Y2 did not hold, and that is Found-and-LEFT item 1.

- **Branch:** `orch-orch-94-orch-yorsie-safety-1`, from `2fbf5ce`. Ancestry was checked: HEAD = `main` = `2fbf5ce`.
- **Commits:** `d72cc00` has the code and tests; the second commit is this file.

## Found and LEFT

1. **Y2's premise is false: a daemon-fired Yorsie route has no worktree.**
   - **The gate cannot be proven to run outside `~/spectricom-dev-pipeline`, because the whole route runs there.**
     - The daemon fires `orchestrator.py run … --repo yorsie`. `run_batch` makes a worktree only for a meta-fire route (`orchestrator.py:3875` at `2fbf5ce`), so for yorsie `proj = worktree or PROJECT_ROOT` (`:3910`) is `~/spectricom-dev-pipeline`.
     - In that tree the route branch is cut (`_run_batch_inner`), the executor edits it, and the unit leg `cd yorsie && npm test` already ran there. The build gate now runs there too: `run_pre_merge_gates(proj, branch_name)` at `:4153`.
   - **`worktree_mode: parallel` and `worktree_base: /home/gkassa/yorsie-toni` (`repos.yaml:13-14`) do not change that.**
     - `WORKTREE_MODE` is assigned (`:177`) and read nowhere.
     - `WORKTREE_BASE` is read only by `create_worktree` (`:1452`), and only the `parallel` subcommand calls that.
     - `~/yorsie-toni` does not exist.
   - **What the gate's build writes in that tree is all gitignored** (`yorsie/.gitignore:10-11`): `yorsie/dist/`, `yorsie/node_modules/.tmp/*.tsbuildinfo` (from `tsconfig.app.json:3`) and `node_modules/.vite-temp/`. Nothing either server serves changes:
     - The dev server on :5175 is `vite` in dev mode from `~/spectricom-dev-pipeline/yorsie`. It serves source, not `dist/`.
     - The preview on :5173 serves `~/yorsie-release/current`, its own tree. `cutover.sh:19` checks `$CAND/yorsie/dist`, never the dev-pipeline `dist/`.
   - **Pre-existing, not changed by this route:** while a route runs, its branch is checked out in the dev server's tree, so the dev server shows the route's code mid-route.
   - Moving Yorsie routes, or only the gate, into a worktree is a lane change with an open question: where `node_modules` comes from (a symlink, or `npm ci` per route). It is not in §3 and not ratified, so I did not build it. What Q3 does prove is that the gate builds the tree the route branch is checked out in, on that branch.
2. **The `parallel` lane merges with no pre-merge gate, for every repo.** `run_parallel` (`:4368`) merges with `merge_branch(br)` (`:4397`) and never calls `run_pre_merge_gates`. Y2 gates `run`, which is the daemon's only lane, but not `parallel`. Not in the brief; left.
3. **Four helper scripts read a default repo at import, and all are outside §3:**
   - `orch-dashboard.py:43`, `drive-sync.py:22`, `drive-bridge.py:23`, `patch-dashboard-progress.py:11` each call `repo_config.load_default_repo_config()`.
   - With `default: true` gone, the old function raises at import. That would have taken down the dashboard (`startup.sh:126`; `spectricom-tmux.sh:44` runs `orch-dashboard.py --daemon`) and the Drive bridge.
   - **Kept them working behind an explicit name:** `repo_config.HELPER_REPO = "yorsie"`. They list and pull Drive/Yorsie/Briefs/, and none of them routes a brief. Checked: `orch-dashboard.py` still imports, with the same `BRIEFS_DIR`.
   - drive-bridge's one fire path (`drive-bridge.py:127`, `orchestrator.py run {brief_path} --approve` with no `--repo`) sits behind `AUTO_FIRE=False` (`:35`). If it were on, the CLI would now refuse a brief there that names no repo.
   - **Follow-up, 4 lines outside §3:** change each call to `repo_config.load_repo_config("yorsie")`, then delete the shim.
4. **`canon_assert.check_queue_trunk_invariants` (`canon_assert.py:570-571`) is now stale.**
   - Its docstring says a brief naming no repo "is taken as this repo's — the same default the scheduler applies when it fires one". The scheduler now refuses such a brief.
   - **What this means at a daemon start (B6):** a brief with no header is still checked against every repo the other queued briefs name. If a route with the same branch name has merged in one of those repos, the brief is retired to `done/` instead of being refused to `failed/`. Nothing fires either way.
   - `canon_assert.py` is outside §3; left.
5. **A brief that names an unknown repo (`#!queue repo=typo`) is not refused by the daemon.** It fires; `orchestrator.py` exits 1 with `Unknown repo: typo. Valid: …` before touching any repo; and `stop_on_failure` pauses the queue. Y1 covers a missing `repo=` only, so this is left as it was.
6. **`setup.sh:18-20` prints usage with no `--repo`.** `orchestrator.py watch` and `status` now refuse without one. `setup.sh` is outside §3. The README's `--dry-run` usage was already stale before this route.
7. **`qstat.sh`'s "Recent landed commits" still reads clinical-mp's `main`** (`REPO=~/spectricom-clinical-mp`, `qstat.sh:5`). It is display only and now labelled `Recent landed commits (clinical-mp main):`.
8. **Vite reads `yorsie/.env` on its own.** `env_file: None` means the orchestrator sources nothing into the gate shell; the Q3 probe proves it (`unset`).
   - `vite build` itself still loads `yorsie/.env` (which exists in the dev-pipeline tree) and inlines `VITE_*` values into the gitignored `dist/`. That is Vite's own behaviour, the same as for any local build.
   - The gate logs only the tail of the build output; the build prints no values.
9. **This brief was not committed before enqueue.** Route 76's brief was (`d495729`). `briefs/94-orch-yorsie-safety-1.md` is not in §3, so it stays untracked in the route worktree. The queue's copy is in `queue/`.

## §0 as-built at `2fbf5ce` (AC-094-01)

1. **Default repo: confirmed.**
   - `config/repos.yaml:17` had `default: true` on `yorsie`, and every other repo had `default: false`. The header comment at `:4` said "Default repo (first with `default: true`) determines yorsie-backward-compat behavior".
   - `repo_config.py:7-16`: `load_default_repo_config()` returned the first entry with `default` set, and raised `No default repo declared in config/repos.yaml` otherwise.
   - In `orchestrator.py`:
     - `load_repo_config` (`:112`) required exactly one default (`:123-127`).
     - `set_active_repo(name: str = "")` (`:131`) fell back with `next(n for n, r in repos.items() if r.get("default"))` (`:153`).
     - It was called bare at module load (`:183-186`), so importing the module made yorsie active.
     - `main()` resolved `--repo > ## Repo: > default` (`:4760-4770`).
   - **Correction:** the two other `load_repo_config` callers, `:3016` (`handback_scan`) and `:3188` (`_unit_gate_eligible_repos`), read every repo, never the default. They are unaffected apart from the loader's new check.
2. **The daemon's default: confirmed, and it was clinical-mp, not Yorsie.**
   - `queue_daemon.py:139-140` described the rule.
   - `:329` set `"repo": os.environ.get("QUEUE_REPO", "clinical-mp")`. A persisted `config.repo` in `queue-state.json` won over both, through `_load_state`.
   - A brief's repo was resolved at `:726-729` (`b_repo = hdr.get("repo", self.config["repo"])`).
   - B6's `queue_repos` (`:529-536`) always added the default.
   - **So a brief with no header, fired by the daemon, landed in clinical-mp.** Only the CLI path landed it in Yorsie: a hand run, or drive-bridge.
   - **Live:** `queue-state.json` holds `config.repo: clinical-mp`, and the daemon (pid 3399893) has no `QUEUE_REPO` in its environment.
3. **Pre-merge gates: confirmed, with the premise in item 1 above corrected.**
   - `PRE_MERGE_GATES` (`orchestrator.py:361-372`) had `clinical-mp` with `("build", "sit")` and `.env`, and `orchestrator` with `("build",)` and `None`. Yorsie was absent, so it was ungated except for its `test_cmd` unit leg.
   - `build_gate_cmd` is read at `:1731` (`ACTIVE_REPO_CONFIG.get("build_gate_cmd", BUILD_GATE_CMD)`) and run with `cwd=repo_path` on the `proj` handed in.
   - The brief's "yorsie worktrees under ~/yorsie-toni" is **not confirmed**; see Found-and-LEFT 1.
4. **`qstat.sh`: confirmed.**
   - It read `state/running.json` (`:12-22`, `:35-38`), the watchdog process (`:26`), and clinical-mp's git (`:5`, `:37`, `:44`). It did not read `queue-state.json`.
   - **Its `uncommitted files` count always came from clinical-mp's tree**, whatever repo the route was in.

## Shipped (`d72cc00`)

### Y1: a brief names its repo or is refused

**In the daemon (`queue_daemon.py`):**

- A brief whose `#!queue` header has no `repo=` (no header at all, a header without `repo=`, or `repo=` with an empty value) is refused, and the queue goes on. The refusal comes before the fire lock and before `current_batch` is set:
  - it is moved to `queue/failed/` with the reason `no repo= in #!queue header — refused, nothing fired`;
  - it is printed as `[QUEUE] REFUSED: <file> — no repo= in #!queue header — refused, nothing fired`;
  - it is recorded under a new `refused` list in `queue-state.json` (`{"file", "reason", "refused_at"}`).
- **A refusal is not a route.** It adds no `completed` / `failed` entry, so `check-logs` stays clean. It does not trigger `stop_on_failure` and does not add to `consecutive_count`.
- The header is read again after any wait for the fire lock, so an edit made while the brief waited is refused the same way.
- **A refused brief that cannot be moved out of `queue/` pauses the daemon with `refused-unmovable:<file>`.** Otherwise it would be refused again on every pass of the loop, with nothing in between.
- **`config.repo` is gone.** `QUEUE_REPO` is not read, and a persisted `config.repo` is not loaded.
- **Start line:** a daemon start prints `🛡 repo: a brief names its repo in its `#!queue repo=…` header; one that names none is refused to failed/, nothing fired`. When it finds an old default it adds ` — queue-state.json repo=clinical-mp not applied (no default repo)` and/or `QUEUE_REPO=…`.
- `queue_repos` (B6) counts only the repos briefs name.
- `config repo …` is refused with `repo is not settable by command: a brief names its repo in its `#!queue repo=…` header; one that names none is refused to queue/failed/ and nothing fires — there is no default repo (ORCH-YORSIE-SAFETY-1)`.

**In `orchestrator.py`:**

- **`load_repo_config` refuses any `default:` key**, with `<path>: `default:` on <names> — there is no default repo; every brief names its repo (ORCH-YORSIE-SAFETY-1). Remove the key.`
- **`set_active_repo(name)` has no default.** Called with an empty name it raises `no repo named — there is no default repo (ORCH-YORSIE-SAFETY-1)`.
- **Nothing runs at import.**
- **`main()` resolves the repo** from `--repo`, else from the one repo every brief argument names. `parse_repo_from_brief` now reads `#!queue repo=…` first, through `canon_assert.queue_header`, the daemon's own parser; then `## Repo:`.
- **`run`, `queue`, `parallel`, `watch`, `status` and `branches` (`REPO_CMDS`) refuse with exit 1** and fire nothing:
  - `⛔ no repo named for <brief> — pass --repo <name>, or name it in the brief (`#!queue repo=…` or `## Repo:`); there is no default repo — refused, nothing fired`
  - `⛔ the briefs name different repos (<a>, <b>) — one invocation runs one repo; pass --repo, or fire them apart — refused, nothing fired`
  - `⛔ <cmd>: no repo named — pass --repo <name> (config/repos.yaml); there is no default repo — refused, nothing fired`
- `watch` gained `--repo`; it had none.
- `deps`, `sit:report`, `flaky` and `handback-scan` read only orchestrator state and run without a repo.

**`config/repos.yaml`:** every `default:` line is removed (one `true`, five `false`), and the header comment now states the rule.

**`repo_config.py`:** a new `load_repo_config(name)`. `load_default_repo_config()` now returns `(HELPER_REPO, …)` by name; see Found-and-LEFT 3.

### Y2: Yorsie merges only what builds

- `repos.yaml` `yorsie` has `build_gate_cmd: "cd yorsie && npm run build"` (that script is `tsc -b && vite build`).
- `PRE_MERGE_GATES["yorsie"] = {"gates": ("build",), "env_file": None}`.
- **Yorsie `main` builds today.** I built `a15ccd2` from a read-only export in `/tmp` (`git archive`, with `node_modules` linked per entry so the build's caches landed in `/tmp`): **exit 0 in 12 s**, against `BUILD_GATE_TIMEOUT = 600`. The product tree was untouched: `git status` clean, no file newer than the build.

### Y3: the queue's state is visible

`qstat.sh` now prints these first, from `queue-state.json`:

- **The daemon line**, one of:
  - `✅ DAEMON running | pid=<pid> alive | daemon_status=… | paused_reason=… | paused_at=…`
  - `⏸️  DAEMON PAUSED | …`, plus a `resume: python3 queue_daemon.py resume[ --reset-consecutive]` line
  - `❌ DAEMON DEAD | pid=<pid> dead | …`, when the file says not-stopped but the pid is dead
  - `⚪ DAEMON <status> | …`, for any other status
  - `⚪ NO DAEMON STATE | no queue-state.json`
- `📥 QUEUED <n> brief(s) waiting`. The running brief is not counted.
- `▶️  RUNNING <file> | since <started_at>`, when there is one.

The fire-lock line now says ROUTE, not QUEUE: `✅ ROUTE alive …`, `❌ ROUTE DEAD …`, and `⚪ NO ROUTE | no state/running.json — no fire in progress` instead of `⚪ NO QUEUE | no running.json (idle or all done)`. The TONI line counts uncommitted files in the route's own tree (a meta-fire's worktree, else the lock's `repo_path`), not in clinical-mp.

**Live, on this route:**

```
✅ DAEMON running | pid=3399893 alive | daemon_status=running | paused_reason=- | paused_at=-
📥 QUEUED 2 brief(s) waiting
▶️  RUNNING 94-orch-yorsie-safety-1.md | since 2026-10-04T01:50:30.496526
✅ ROUTE alive | PID=3870365 | elapsed=14:58 | batch=94-orch-yorsie-safety-1
```

### Tests

- `tests/test_yorsie_safety.py` has 48 new tests.
- **Six existing tests pinned the old default and were updated to the new rule, each keeping its intent:**
  - `test_config_truth.py::test_repo_says_where_it_comes_from` now expects "no default repo" instead of "QUEUE_REPO".
  - `test_executor_default.py`:
    - the two `run no-such-brief.md` banner tests now pass `--repo orchestrator`;
    - `test_daemon_no_header_…` is renamed `test_daemon_no_executor_header_no_env_no_state`, with header `#!queue repo=r`.
  - `test_queue_retire.py::test_the_repo_checked_is_the_one_the_brief_names` now expects `[]`, since no default is added.
  - `test_unit_baseline_gate.py::test_force_logs_…` now passes `--repo gated-repo`.
- One docstring in `test_running_marker.py` was updated: `QUEUE DEAD` became `ROUTE DEAD`.
- **One existing check was too broad, and I fixed it.** `test_unit_baseline_gate.py::test_no_repo_test_cmd_changed_on_this_branch` (AC-O5-07) searched the whole `git diff main...HEAD -- config/repos.yaml` for `test_cmd`, context lines included.
  - Once the change was committed, the unchanged `test_cmd` next to each removed `default:` appeared as context, and the check went red. It would have held this route back in its own `pytest -q tests/` gate.
  - It now counts only added and removed lines. A new negative control (`test_negative_control_only_a_changed_line_counts`) confirms that a changed `test_cmd` line is still caught.
  - No `test_cmd` changed in this route.

## Gate table

| AC | Evidence | Result |
|---|---|---|
| AC-094-01 | §0 above: four confirmations with file:line. Two corrections: the daemon's default was clinical-mp, and Yorsie routes have no worktree | PASS |
| AC-094-02 Q1 | **RED on `2fbf5ce`:** a headerless brief fired as `['run', '…/a-headerless.md', '--approve', '--repo', 'clinical-mp', '--model', 'm', '--effort', 'e']` and went to `done/` (with `failed/` empty). The `header-without-repo`, `empty-repo` and `no-header` shapes all fired. An unmovable brief was fired again and again until `max-consecutive:25`. **GREEN:** refused to `failed/` with the verbatim reason; the next brief fires with `--repo named-repo`; `paused_reason` is None; `failed == []`; `consecutive_count == 1`; `check-logs` clean; a persisted `repo` plus `QUEUE_REPO` are not applied. **Negative controls:** a named brief fires with its repo; a named brief whose route exits 1 does pause with `stop-on-failure:b-named.md`, so the harness can pause | PASS |
| AC-094-03 Q2 | **RED on `2fbf5ce`:** `repos.yaml` declared `default` on all six repos. The scan found a default lookup in all three files. `set_active_repo()` was called at import (line 186) and its `name` defaulted to `''`. A `#!queue repo=clinical-mp` brief run by hand went to `['yorsie']`. `status`, a headerless `run` and a mixed `queue` all exited 0 on yorsie. **GREEN:** no `default:` in the yaml (not even `false`); no lookup in `orchestrator.py`, `queue_daemon.py` or `repo_config.py`; nothing selects a repo at import; the loader refuses `default:`. **Negative controls:** the scan finds each of the four old lines; a display's `'?'` placeholder is not flagged; `#!queue repo=`, `## Repo:` and `--repo` each run on the named repo; `handback-scan` runs without one | PASS |
| AC-094-04 Q3 | **RED on `2fbf5ce`:** with yorsie ungated, a stub branch whose `npm run build` exits 1 merged (status `passed`, main moved to the route tip) and no build ran. **GREEN, through the real `_run_batch_inner` and `run_pre_merge_gates` against a stub git repo:** the failing build gives `FAIL(product)`, main is unchanged and the branch is preserved; the gate's `pwd -P` is `<route checkout>/yorsie` on branch `orch-batch-ys`; `YS_SECRET` is `unset` with `.env` at the root and in `yorsie/`. **Negative controls:** a passing build merges, main moving to the route tip; declaring `env_file: "yorsie/.env"` makes the probe read `leaked-yorsie`, so the probe can see sourcing; deleting the yorsie entry reproduces the merge of a broken build; the clinical-mp and orchestrator entries are unchanged | PASS |
| AC-094-05 Q4 | **RED on `2fbf5ce`:** against the fixture (`paused`, `max-consecutive:10`, live pid), `qstat.sh` printed only `⚪ NO QUEUE \| no running.json (idle or all done)`. **GREEN:** `⏸️  DAEMON PAUSED \| pid=<pid> alive \| daemon_status=paused \| paused_reason=max-consecutive:10 \| paused_at=2026-10-04T01:02:03.456789`, then `📥 QUEUED 2 brief(s) waiting`, and no "idle" anywhere. **Negative controls:** `running` prints `✅ DAEMON running …` plus `▶️  RUNNING 94-x.md \| since …` with `QUEUED 1` and no "PAUSED"; a dead pid prints `❌ DAEMON DEAD`; no file prints `⚪ NO DAEMON STATE` | PASS |
| AC-094-06 | `pytest -q tests/`, run in the foreground on the committed branch: 822 → **871 passed, 0 failed** (20 s): the 48 new tests plus the AC-O5-07 negative control. The new file on `2fbf5ce` (a `git archive` export): 36 failed, 12 passed, and all 12 are negative controls, the RED reproduction, or checks of the scan itself | PASS |
| AC-094-07 | `d72cc00` touches `config/repos.yaml`, `orchestrator.py`, `qstat.sh`, `queue_daemon.py`, `repo_config.py` and `tests/**` (one new file and six edited). The second commit is this handback. No product repo was changed: Yorsie `main` was only read, through `git archive` | PASS |
| Handback guard | This file plus the closing message, wrapped as a `=== TONI EXECUTION ===` log and run through `orchestrator.py handback-scan` against `config/handback-guard.json` | CLEAN |

## THE CONSEQUENCE (D-S7CORE13-03)

1. **The daemon refuses a brief that does not name its repo (after Gemma restarts it).** Such a brief goes to `queue/failed/` with `no repo= in #!queue header — refused, nothing fired`, and the next brief fires.
   - Before, the daemon fired it into clinical-mp (`QUEUE_REPO`, else clinical-mp, or the persisted `config.repo`). A hand run or drive-bridge fired it into Yorsie.
   - The start line names the persisted `repo=clinical-mp` it no longer applies; the next save drops it.
   - **Nothing queued now is affected:** `95-llm-seams-2.md` and `96-data-apply-1.md` both name `repo=clinical-mp`. Of the 82 briefs in `queue/done/`, 8 have no `repo=`; each of those would now be refused.
2. **The CLI refuses a repo command that names no repo, from the merge on.** This takes effect without the restart, because each route and each hand run starts a fresh `orchestrator.py`.
   - `orchestrator.py status`, `branches` and `watch` need `--repo`.
   - `run`, `queue` and `parallel` need `--repo`, `#!queue repo=` or `## Repo:`.
   - A brief that names its repo only in `#!queue repo=` now runs there by hand; before, it ran in Yorsie.
   - Until the daemon restarts, the old daemon still adds `--repo clinical-mp` to a headerless brief, so the CLI refusal never sees one from the queue.
3. **A Yorsie change that does not build cannot merge, from the next Yorsie route after the merge.** The gate runs in `orchestrator.py`, so no restart is needed for it.
   - The route ends `FAIL(product)` (or BLOCKED(environment) on an F-20 signal), main is untouched, and the branch is kept.
   - Yorsie `main` (`a15ccd2`) builds in 12 s, so the gate does not block a clean route today. It adds about 12 s to every Yorsie route.
   - **It builds in `~/spectricom-dev-pipeline`, the dev server's tree** (Found-and-LEFT 1). It writes only gitignored `dist/` and caches, which neither server serves.
4. **`qstat.sh` shows when the queue is paused and why, from the merge on (it is a script).** It prints the daemon's pid, `daemon_status`, `paused_reason`, `paused_at`, the queued count and the running brief. A paused daemon reads `⏸️  DAEMON PAUSED | … | paused_reason=max-consecutive:10 | paused_at=…` with its resume command, never "idle". A dead one reads `❌ DAEMON DEAD`.
5. **Restart (Gemma; not done here, per L-29).** `queue_daemon.py` changed, so the daemon (pid 3399893, started 2026-10-03 11:59) keeps the old code until it restarts. Restart only when no route is live, using route 76's procedure:
   1. Run `python3 queue_daemon.py pause`.
   2. Check that `status` shows `paused` and `"current_batch": null`.
   3. Stop pid 3399893, then run `~/bin/s7core14-start-daemon.sh`.
   4. Check the new start lines, `🛡 executor-default:` and `🛡 repo: … — queue-state.json repo=clinical-mp not applied (no default repo)`.
