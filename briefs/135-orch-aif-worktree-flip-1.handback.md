# filename: briefs/135-orch-aif-worktree-flip-1.handback.md

# 135 · ORCH-AIF-WORKTREE-FLIP-1: handback

**ai-foundation is now `worktree_mode: parallel`.** From the next ai-foundation fire after this merges, the route runs, is gated and merges in `/home/gkassa/aif-toni/<route>`. The executor no longer writes in `~/spectricom-ai-foundation`, the checkout the Listen services, the EC answerer and the Fourth Turning ingest import from. The tripwire that pinned `single-stream` is gone. It is replaced by a test that asserts `parallel` **and** an exact `venv` line in ai-foundation's `.gitignore`.

P1, P2 and P3 are green. The predecessor check passed: ai-foundation `main:.gitignore` line 1 is exactly `venv` (route 134, `3cfb727d`).

Things you need to know first:
- **L-71 is narrowed, not closed.** A route no longer edits the services' checkout while it runs. But that checkout still has `main` checked out, so **every PASS merge fast-forwards it in place**: `_land_from_route_worktree`, `orchestrator.py:1653-1655`. The services' tree now moves once per route, at the merge, and only to a gated commit. Before, it moved throughout the route. Moving it only through `aif-deploy.sh` is remedy step 3, the detach, which is George's call (last section).
- **No daemon restart is needed for the flip to take effect.** The daemon starts a fresh `orchestrator.py run` for every fire (`queue_daemon.py:1241`), and that process reads `config/repos.yaml` in `set_active_repo` (`orchestrator.py:157`, `:182`). No daemon code changes here. If L-82 asks for a restart after every orchestrator merge anyway, the exact steps are under THE CONSEQUENCE.
- **No ai-foundation brief is queued.** `queue/` holds 136–141, all `repo=clinical-mp`. So the first `parallel` ai-foundation route is whichever one you enqueue next.

- **Branch:** `orch-orch-135-orch-aif-worktree-flip-1`, from `af3a0f2` (= `main` = merge-base).
- **Commits:** `170ce50` (`config/repos.yaml`, `tests/test_capacity.py`). The next commit is this file.
- **Tests:** `pytest -q tests/`: **1062 passed** at `af3a0f2`, **1062 passed** at `170ce50`, 0 failed, 0 skipped. One test was replaced by one test.

## Found and LEFT

1. **Four pieces of text in `tests/test_capacity.py` still describe the flip as stopped.** The brief limited me to the tripwire test, so I left them. All four are docstrings or names, not assertions:
   - `:8-9`, the module docstring: `P4 (C2) the staged ai-foundation block … The flip itself is STOPPED (the venv link hazard).`
   - `:458`, `test_R_the_staged_block_resolves_to_aif_toni`. It still flips a copy of the config. It is now redundant with the shipped config, but it is still true and green.
   - `:476-477`, `test_the_gate_command_is_mains`: `relative to the checkout the route runs in — single-stream, the checkout itself.` The route now runs in `/home/gkassa/aif-toni/<route>`, and `venv/bin/activate` resolves through the link `_link_unit_deps` makes (P2).
   - `:515-516`, the `TestP4VenvLinkHazard` docstring: `Why the flip is STOPPED: …`. The class itself is still the right pin. It shows why the `venv` line matters.
2. **Detaching the checkout stays George's call (remedy step 3), so I did not detach it.** `git -C ~/spectricom-ai-foundation symbolic-ref HEAD` → `refs/heads/main`. `aif-deploy.sh`'s dry-run prints its NOTE (gate table).
3. **The code fix 123b named is still not made.** That fix: `_create_route_worktree` would drop any dependency link git does not ignore. Today the protection is ai-foundation's `.gitignore` line alone. If that line ever reads `venv/` again, the new test fails here, but only on a machine that has the checkout (in CI it skips the `.gitignore` read with a reason, and still asserts the mode). The code fix also covers 104's Found-and-LEFT 8 (Yorsie `node_modules/`). It is outside this brief.
4. **This machine is loaded.** Load average was 12.11 at 17:51. The suite took 110–130 s here, against 47.68 s in 123c. 123c's Found-and-LEFT 2 shows that the gate's clock check can label a slow run `BLOCKED(environment) — clock-implausible`. If this route's gate says that, it is the clock, not the product: P1 below is green at the committed tree.
5. **I did not commit this brief.** That follows routes 94, 104, 114, 123b and 123c.

## §0 as-built (pastes, at `af3a0f2`)

1. **Predecessor.** `git -C ~/spectricom-ai-foundation show main:.gitignore | head -1` → `venv`. `od -c` shows `v e n v \n`, exactly. It came from ai-foundation `3cfb727d fix: 134-aif-gitignore-venv-1 — 1 briefs` (Tue Oct 6 17:38:41 2026), whose `.gitignore` hunk is `-venv/` / `+venv`. The checkout is on `refs/heads/main` at `3cfb727d`, and its working-tree `.gitignore:1` reads `venv`.
2. **`config/repos.yaml:49-64`:**
   ```
     ai-foundation:
       project_dir: /home/gkassa/spectricom-ai-foundation
       branch_prefix: orch-aif
       merge_target: main
       remote: origin
       log_subdir: ai-foundation
       # ORCH-CAPACITY-1 C2 (S7-CORE-21, L-71) — STAGED, NOT LIVE: stays single-stream. DO NOT flip to `parallel`
       # until ai-foundation's .gitignore ignores a `venv` SYMLINK: its line 1 reads `venv/`, which matches a
       # directory only. A route worktree links venv from this checkout (orchestrator._link_unit_deps), so the
       # route's `git add -A` commits the link, and the merge's fast-forward here DELETES this checkout's venv/ —
       # the venv the MiniMe services run from (briefs/123b-orch-capacity-1.handback.md, Found and LEFT 1).
       worktree_mode: single-stream
       worktree_base: /home/gkassa/aif-toni
       briefs_subdir: briefs
       test_cmd: ". venv/bin/activate && PYTHONPATH=. pytest"
       build_gate_cmd: ". venv/bin/activate && PYTHONPATH=. pytest -q"
   ```
3. **`tests/test_capacity.py:456-470`:**
   ```
   class TestP4AifWorktree:

       def test_R_the_staged_block_resolves_to_aif_toni(self, tmp_path, monkeypatch):
           cfg = json.loads(json.dumps(SHIPPED))
           cfg["repos"]["ai-foundation"]["worktree_mode"] = "parallel"     # the flip, in a copy
           _set_repo(monkeypatch, cfg, tmp_path, "ai-foundation")
           assert orchestrator.WORKTREE_MODE == "parallel"
           assert orchestrator.WORKTREE_BASE / "125-minime-console-1" == Path("/home/gkassa/aif-toni/125-minime-console-1")

       def test_the_shipped_mode_stays_single_stream_until_venv_is_ignored(self):
           """A tripwire, not a preference: see config/repos.yaml and the handback's Found and LEFT 1. Flip it only
           after ai-foundation's .gitignore ignores a `venv` symlink (TestP4VenvLinkHazard shows why)."""
           aif = SHIPPED["repos"]["ai-foundation"]
           assert aif["worktree_mode"] == "single-stream" and aif["worktree_base"] == "/home/gkassa/aif-toni"
   ```

## Shipped (`170ce50`)

### `config/repos.yaml`
- `worktree_mode: single-stream` → `worktree_mode: parallel` for ai-foundation.
- The five-line STAGED/hazard comment is now one line: ``# ORCH-AIF-WORKTREE-FLIP-1 (L-71): parallel since route 134 merged — ai-foundation 3cfb727d, .gitignore `venv`.``
- `worktree_base: /home/gkassa/aif-toni` was already set. `set_active_repo` reads it only when the mode is `parallel` (`orchestrator.py:173-177`). The directory does not exist yet; `_create_route_worktree` makes it on the first route.
- `test_cmd` and `build_gate_cmd` are untouched. `TestTheSuiteCommandIsNotNarrowed` is green at `170ce50` (gate table).

### `tests/test_capacity.py`
- `test_the_shipped_mode_stays_single_stream_until_venv_is_ignored` is deleted. In its place is **`test_the_shipped_mode_is_parallel_and_venv_is_ignored`**, which:
  - asserts the shipped ai-foundation entry is `worktree_mode: parallel` with `worktree_base: /home/gkassa/aif-toni`. This runs everywhere.
  - asserts that `<project_dir>/.gitignore` has a line exactly `venv` (`"venv" in read_text().splitlines()`). When `project_dir` is not a directory (CI), it calls `pytest.skip("the ai-foundation checkout is not on this machine (CI): its .gitignore is unchecked")`. That skip comes after the mode assertion, so the mode is pinned in CI too.
  - only reads. Nothing in ai-foundation is written.
- Negative controls: I replaced the module's `SHIPPED` in-process and edited no file. A temp dir held the `venv/` case:

  | Case | Result |
  |---|---|
  | shipped config | PASSED |
  | `worktree_mode: single-stream` | FAILED (mode assertion) |
  | `.gitignore` line 1 `venv/` | FAILED: ``ai-foundation's .gitignore must read `venv` (route 134), or a route commits the link`` |
  | `project_dir` absent | SKIPPED: `the ai-foundation checkout is not on this machine (CI): its .gitignore is unchecked` |
  | `project_dir` absent + `single-stream` | FAILED (mode assertion; the skip does not hide it) |

## Gate table

| Gate | Result |
|---|---|
| Predecessor | `main:.gitignore` line 1 = `venv` (`od -c`: `v e n v \n`) → proceed |
| **P1** before, `af3a0f2` (merge-base = `main`) | `pytest -q tests/` → **1062 passed** in 110.66 s |
| **P1** after, working tree | **1062 passed** in 114.65 s |
| **P1** after, committed `170ce50` | **1062 passed** in 130.08 s, 0 failed, 0 skipped |
| Guard + capacity at `170ce50` | `tests/test_unit_baseline_gate.py::TestTheSuiteCommandIsNotNarrowed` + `tests/test_capacity.py` → **69 passed** in 8.56 s |
| **P2** dry probe (no Toni) | below: link present, `git status --porcelain` empty, `!! venv`, `.gitignore:1:venv`, `git add -A --dry-run` empty on the route branch. Worktree and branch removed; ai-foundation snapshot identical before/after |
| **P3** `git diff --stat af3a0f2 170ce50` | `config/repos.yaml` (2+, 6−) · `tests/test_capacity.py` (8+, 4−) · `2 files changed, 10 insertions(+), 10 deletions(-)`. No other path |
| `aif-deploy.sh` dry-run (live, read-only) | `on main at 3cfb727d; origin/main is 3cfb727d` · `✓ no live ai-foundation route · ✓ Listen: none recording or transcribing … · ✓ no tracked changes` · `NOTE: this checkout has main checked out, so an orchestrator merge into main fast-forwards it …` · `dry-run: nothing changed.` exit 0 |
| Live, read-only | daemon pid **94787** `python3 -u queue_daemon.py`, cwd `~/spectricom-orchestrator`, stdout/stderr → `~/_eos/logs/s7core14-queue-daemon2.log`; `status` line 1: `daemon_status=running paused_reason=- … \| pid 94787 alive`. `spectricom-queue-daemon.service` inactive. `queue/`: 135 (this route) and 136–141, all `repo=clinical-mp`. `queue/held/`: 117, 121; `queue/held/s7c21-restart/` empty |
| Destructive operations | **None** beyond the probe's own worktree and branch, which it removed. `git worktree prune --dry-run -v` in ai-foundation was empty beforehand, so the teardown's prune touched no other entry (`/home/gkassa/_eos/s7core19/wt108` is intact). `/home/gkassa/aif-toni` was not created. The stash was not touched |
| Handback guard (`config/handback-guard.json`, `canon_assert.check_handback_invariants`) | this file, wrapped in a `TONI_HEADER` and a 60-`=` / `Exit: 0` trailer so the guard reads it as executor output (all 6 rules): **CLEAN** |

### P2 paste

`/tmp/orch135-p2.py` ran with the orchestrator imported from this branch. `set_active_repo("ai-foundation")` read the shipped, flipped config. `WORKTREE_BASE` was then set to `/tmp/orch135-p2-base`, so `aif-toni` was not used. The script called the orchestrator's own `_create_route_worktree` and `_finish_route_worktree`.
```
shipped: WORKTREE_MODE=parallel WORKTREE_BASE=/home/gkassa/aif-toni PROJECT_ROOT=/home/gkassa/spectricom-ai-foundation MERGE_TARGET=main BRANCH_PREFIX=orch-aif

── create (orchestrator._create_route_worktree) ──
  [orchestrator.log] 🌳 Route worktree: /tmp/orch135-p2-base/135-p2-dry-probe (from main; 1 dependency path(s) linked from /home/gkassa/spectricom-ai-foundation) — the main checkout is not the route's
returned: wt=/tmp/orch135-p2-base/135-p2-dry-probe why=''

── the venv link ──
(wt/'venv').is_symlink() = True  ->  /home/gkassa/spectricom-ai-foundation/venv
$ ls -ld /tmp/orch135-p2-base/135-p2-dry-probe/venv
lrwxrwxrwx 1 gkassa gkassa 42 Oct  6 17:50 /tmp/orch135-p2-base/135-p2-dry-probe/venv -> /home/gkassa/spectricom-ai-foundation/venv   [exit 0]
$ git -C /tmp/orch135-p2-base/135-p2-dry-probe status --porcelain
(no output)   [exit 0]
$ git -C /tmp/orch135-p2-base/135-p2-dry-probe status --porcelain --ignored
!! venv   [exit 0]
$ git -C /tmp/orch135-p2-base/135-p2-dry-probe check-ignore -v venv
.gitignore:1:venv	venv   [exit 0]

── the route's own steps: cut the branch (_run_batch_inner), then `git add -A` dry ──
$ git checkout -b orch-aif-135-p2-dry-probe main
Switched to a new branch 'orch-aif-135-p2-dry-probe'   [exit 0]
$ git add -A --dry-run
(no output)   [exit 0]
$ git -C /tmp/orch135-p2-base/135-p2-dry-probe status --porcelain
(no output)   [exit 0]

── teardown (orchestrator._finish_route_worktree, as after a PASS) + branch ──
  [orchestrator.log] 🌳 Route worktree removed: /tmp/orch135-p2-base/135-p2-dry-probe
$ git -C /home/gkassa/spectricom-ai-foundation branch -D orch-aif-135-p2-dry-probe
Deleted branch orch-aif-135-p2-dry-probe (was 3cfb727d).   [exit 0]
$ rmdir /tmp/orch135-p2-base
(no output)   [exit 0]
worktree dir exists after: False; temp base exists after: False
$ git -C /home/gkassa/spectricom-ai-foundation worktree list
/home/gkassa/spectricom-ai-foundation  3cfb727d [main]
/home/gkassa/_eos/s7core19/wt108       e73e3d04 (detached HEAD)   [exit 0]
$ git -C /home/gkassa/spectricom-ai-foundation branch --list 'orch-aif-135-p2-dry-probe'
(no output)   [exit 0]
```
The ai-foundation snapshot (HEAD, `status --porcelain`, worktrees, `orch-aif-*` branches, `venv` inode and mtime) was identical before and after (`diff` exit 0):
```
HEAD 3cfb727d20a840ddb8d6fece9566f1e234988a31 on refs/heads/main
status --porcelain: 0 line(s), sha1 da39a3ee5e6b
worktrees: 2 — /home/gkassa/spectricom-ai-foundation /home/gkassa/_eos/s7core19/wt108
orch-aif-* branches: 2
venv: directory inode=157413 mtime=1774796838; bin/python -> python3
```
`venv` is the only path linked: of `UNIT_BASELINE_LINK_PATHS` (`node_modules`, `venv`, `.venv`, `yorsie/node_modules`, `orchestrator.py:334`), only `venv` exists in ai-foundation. ai-foundation has no `PRE_MERGE_GATES` entry, so no `env_file` is linked either. The full ai-foundation suite in a fresh worktree was measured in 123b (830 passed, 33 skipped, 223 s), so I did not re-run it.

## THE CONSEQUENCE (D-S7CORE13-03)

**From the next ai-foundation fire after this merges, restart or not:** `run_batch` (`orchestrator.py:4299-4300`) creates `/home/gkassa/aif-toni/<route>` from `main` and links `venv` into it. `_run_batch_inner` cuts `orch-aif-<route>` there (`:4392`). Toni, `git add -A` (`:4512`) and the gates all run with that worktree as cwd. On PASS, `_land_from_route_worktree` merges there and fast-forwards `main` **in `~/spectricom-ai-foundation`** (`:1653-1655`), because that checkout holds `main`. `_finish_route_worktree` (`:1584`) then unlinks `venv` and removes the worktree. On any other outcome, the worktree is kept and named in the log. The daemon's dead-route recovery skips the main checkout for a route whose marker names a `route_worktree` (`queue_daemon.py:892`).

**Gemma (L-82): the restart this change needs is none.** The daemon reads `config/repos.yaml` at every use (`_repo_config`, `queue_daemon.py:376`; `admission.limits` / `admit`, `:1018`, `:1117`), and each route is a new `orchestrator.py run` process (`:1241`). No daemon code changed. If L-82 asks for a restart after every orchestrator merge anyway, this is the exact sequence, with today's live facts:
1. **After this route has merged to `main`, pause:** `cd ~/spectricom-orchestrator && python3 queue_daemon.py pause` → `acknowledged request …`. 136–141 are queued behind this route, so pause first: the daemon then fires nothing new.
2. **Idle:** `python3 queue_daemon.py status` must show `"current_batch": null`. If 136 had already started, let it finish first.
3. **Stop:** `kill 94787`, or the pid shown in `status` line 1.
4. **Start** (the live daemon's own cwd and log): `cd ~/spectricom-orchestrator && nohup python3 -u queue_daemon.py >> ~/_eos/logs/s7core14-queue-daemon2.log 2>&1 &`. With 136–141 still queued, it comes up `PAUSED (start:queue-non-empty)`.
5. **Resume:** `python3 queue_daemon.py resume --reason start:queue-non-empty`.
6. **Check:** `status` line 1 shows the new pid `alive` and `paused_reason=-`.

## Remedy step 3 (detach): what it would change, for George

The command is `git -C ~/spectricom-ai-foundation switch --detach` (HEAD stays at `3cfb727d`; no file changes).

- **What it changes:**
  - `_checkout_holding("main")` would find no checkout, because `wt108` is detached too. `_land_from_route_worktree` would then take the `update-ref` branch (`orchestrator.py:1657`): a compare-and-swap of `refs/heads/main` only.
  - A PASS merge would no longer touch the services' files at all. The services' tree would move only when you run `scripts/aif-deploy.sh --apply`. That script refuses while an ai-foundation route is live, or while a Listen sitting is recording or transcribing. It fast-forwards with `git merge --ff-only <sha>`, which works on a detached HEAD (`TestP5`), and restarts `minig-listen-worker.service`.
  - That closes L-71 fully. With `parallel` alone, the services' checkout still moves at every merge.
- **What it costs:**
  - In that checkout, `git pull` fails ("not currently on a branch"), and a commit made there lands on no branch.
  - `aif-deploy.sh` deploys `origin/main` (`<remote>/<merge_target>` from `repos.yaml`), and the orchestrator never pushes (no `git push` in `orchestrator.py`). So after a detach, a merged route reaches the services only once `main` is pushed and then deployed.
  - Today `origin/main` = `main` = `3cfb727d`. The reflog shows `update by push` at 17:54:23. That push was not the orchestrator's.
- **What it does not change:**
  - Route execution, gates and the worktree path.
  - The daemon's dead-route recovery: a `parallel` route's marker names its `route_worktree`, so recovery skips the main checkout either way.
  - `aif-deploy.sh` already prints `on a detached HEAD` for this case and drops the NOTE.
