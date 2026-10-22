# filename: briefs/330-orch-depends-on-1.handback.md
# HANDBACK — 330 · ORCH-DEPENDS-ON-1 (S7-CORE-33, batch s7core33-orch-depends-on-1, SCP_Kanban row 360)

Branch `orch-orch-330-orch-depends-on-1` off `4ba2cb3`. Executor: claude-opus-5-5 --effort xhigh.

**A daemon restart is needed for D4.** `queue_daemon.py` changed, and the running daemon (pid 3128) still runs the old selection. A11 needs no restart: `orchestrator.py` is spawned per route and imports `prefire` fresh, so A11 is live at the next fire after merge. Between the merge and the restart, a brief whose dependency has not merged is refused by A11 at the fire. The old daemon then records that as FAILED and pauses on stop-on-failure, instead of waiting. I did not touch `queue/`, `state/`, the daemon or any live route. I only read the live `queue/` trays (§0, P-scan below).

## 0 · As built (L-30, rule #7). All premises hold at `4ba2cb3`
- **prefire:**
  - `prefire.py:352` `check()` runs A1 (`check_kanban`, `:316`), then A2, A8, A9 and A10.
  - `prefire.py:426` `report()`.
  - `orchestrator.py:5343`: `if not PREFIRE_BYPASS and not prefire.report(batch_file, timeout=prefire_timeout(batch_file))` is the first statement of `run_batch`. `--force` sets `PREFIRE_BYPASS` (`:6356-6358`).
- **Daemon order:**
  - `queue_daemon.py:630` `_scan_queue` → `:633` `sorted(f for f in QUEUE_DIR.glob("*.md") if f.is_file())`.
  - `run_loop` took `next_batch = queue[0]`. Filename order was the only order.
- **The merged-route owner:**
  - `canon_assert.py:560` `check_queue_trunk_invariants(queue_dir, repo)`, used by `queue_daemon.py:814` `find_merged_briefs` and `:826` `retire_merged_briefs` (boot assert B6).
  - `queue_daemon.py:849` `_refuse` moves a brief to `queue/failed/`.
- **How a brief's repo is read:** `canon_assert.queue_header(path)` (`:544` at HEAD) parses line 1, `#!queue … repo=…`, into `{key: value}`. The trunk invariant skips a brief naming another repo, and the daemon resolves the name through `repo_route` (config/repos.yaml `project_dir` / `merge_target` / `branch_prefix`).
- **How "route merged" is decided:** by the **route branch name**, never by file presence. The branch is `QueueRepo.branch_for(brief)` = `<branch_prefix>-<brief stem>`; for orchestrator that is `orch-orch-<stem>`. `_landed` (`canon_assert.py:508`) tries three detectors, strongest first:
  1. A merge commit on the merge target whose subject names `'<branch>'` (last 500 merges).
  2. A `merge <branch>:` reflog entry on the merge target that is still reachable (the fast-forward lane).
  3. The branch ref still exists and is an ancestor of the merge target (the meta-fire `--ff-only` lane).
  Unreadable is None.

## 1 · D1–D5 as built
- **D1 Declaration**
  - `prefire.py:390` `parse_depends_on`. The line is `^##\s*Depends[- ]on\s*:` (`:364`), case-insensitive, read from the header like A1/A2/A9.
  - Entries are comma-separated, each `<stem>[@<repo>]` (`:365`; stem `[A-Za-z0-9][A-Za-z0-9_-]*`). Markdown `*` and backticks are stripped first.
  - No line means no dependency, the same as today.
  - Unreadable means an A11 refusal that says what is wrong:
    - an empty line
    - an entry that is not `<stem>[@<repo>]` (a space, `.md`, a parenthetical, a bare `@`)
    - an empty entry
    - the brief itself
    - two lines
    - a stem with no repo to look in
    - a repo that config/repos.yaml does not name
  - The default repo is the brief's `#!queue … repo=`.
- **D2 One owner (A13)**
  - `canon_assert.py:544` `route_merged(repo, brief)` = `_landed(repo, repo.branch_for(brief))`. `check_queue_trunk_invariants` now calls it (`:594`).
  - prefire calls it as `canon_assert.route_merged` (`prefire.py:456`, inside `dependency_status` `:440`). The daemon reaches it only through `prefire.dependency_status`. No second git reader: prefire imports no `subprocess`.
- **D3 Prefire A11**
  - `prefire.py:519-526` in `check()`. One failure lists every unmet dependency as `<stem> (not merged on <repo>/<target>; <where>)`.
  - `<where>` is every tray that holds `<stem>.md`: `queue/`, `queue/failed/`, `queue/held/<sub>/`, `queue/done/`. If none, it is `nowhere — not in queue/, queue/failed/, queue/held/ or queue/done/` (`dependency_trays` `:425`; `Dependency.__str__` `:371`).
  - Pass line `:558`: `Assertions: ✅ A1/A2/A8/A9/A10/A11 pass — …`. When a line is declared, one more line follows: `Depends-on: <stem> merged on <repo>/<target> (<sha8> [<evidence>])` (`:561-563`).
  - `prefire.QUEUE_DIR` (`:363`) = `<orchestrator dir>/queue`; tests patch it. `prefire.queue_repo` (`:414`) resolves a name with the keys and defaults of `queue_daemon.repo_route`.
- **D4 Daemon order** (`queue_daemon.py`)
  - `run_loop` (`:1224`) calls `_next_brief(self._scan_queue())` (`:899`). It picks the first brief in filename order whose dependencies are all merged, judged by `prefire.dependency_status(brief, QUEUE_DIR, repo_route)`.
  - **Wait:** every unmet dependency is still in `queue/`. The brief stays in place and one line is printed for it: `[QUEUE] ⏳ <brief>: WAITING depends-on <stem> (not merged on …; queue/) — not fired until it merges; the next eligible brief fires`. It is printed once per brief while it waits (a restart says it again). The waiting set is persisted as `depends_waiting` (a daemon-owned key, `:69`, `:646`).
  - **Hold:** some unmet dependency is anywhere else — `failed/`, `held/`, unmerged in `done/`, or nowhere. `_hold_depends_on` (`:937`) moves the brief to `queue/held/depends-on/` and writes `<stem>.reason` beside it. The reason is one line: `<iso> <brief>: HELD depends-on <stem> (…; queue/failed/) — the queue cannot merge it, so this brief is not fired; move it back to queue/ once that route is merged`. The same text is printed to the daemon log.
    - A hold is never `failed/`, never a pause, never a completed/failed/refused entry, and never a consecutive count.
    - A brief that will not move stays in `queue/`, is passed over (never fired) and is said once (`_depends_unmovable`).
    - Chains are held link by link in one scan.
  - **Neither applies** (no line, or a line A11 cannot read): the brief is taken as today. A11 refuses an unreadable line at the fire.
  - **Every queued brief waits:** nothing fires. The loop idles (`sleep(10)`, as for an empty queue) and does not pause.
  - **`status`:** line 1 gets `| ⏳ depends-on waiting: <brief> ← <stem>, … · held in queue/held/depends-on/: <brief>, …` (`depends_on_line` `:317`, used `:1603`). The JSON gets `depends_waiting` (the daemon's, from queue-state.json) and `depends_held` (`[{file, reason}]` read off disk, `depends_held` `:303`).
  - `dependency_status` raising never ends the loop: the brief is taken as it stands and A11 judges it again at the fire.
- **D5 Not changed**
  - Filename order for briefs without dependencies (control test). A1–A10 are unchanged.
  - `--force` still bypasses all prefire checks (`orchestrator.py:5343` unchanged; control test). Its warning still reads `pre-fire assertions (A2/A8) BYPASSED; A1 Kanban READY not checked` (found-and-left 1).
  - Stop-on-failure, `_refuse`, B6 at start, admission and the fire lock are unchanged.

## 2 · Tests changed
- **Rule #8 pins (pre-authorised message-text pins: the pass line `A1/A2/A8/A9/A10` → `…/A11`):**
  1. `tests/test_prefire.py::test_D3_report_names_a9_and_a10_and_the_scope_it_passed_on:262`
  2. `tests/test_control_scope.py::TestP3Kanban::test_report_names_the_row_it_passed:405`
  3. `tests/test_runtime_parse.py::TestP1::test_R_the_pass_line_names_the_timeout_and_warns_of_the_clamp:137`
  The text changed and nothing else. No other existing test changed.
- **New:** `tests/test_depends_on.py`, 39 tests. All repos, queues and configs are under tmp_path. Merged states are made with git. The daemon runs its real `run_loop` with `_run_route` stubbed.

## 3 · Predicates RED → GREEN
- **RED** on HEAD `4ba2cb3` (code unchanged, new file only): **35 failed, 4 passed**. The 4 passes are controls:
  - a merged dependency passes
  - no line is unchanged
  - filename order without lines
  - `--force` source
- **GREEN: 39 passed.**
- **P1:** `## Depends-on: 400a-first`, with A in `queue/`, `failed/`, `held/s7x/` or `done/` → exactly one A11 failure naming `400a-first`, `testrepo/main` and the tray. A nowhere → `nowhere`. A STOPPED branch → not merged. A merged → `[]`. Several deps → one failure naming only the unmet ones. `@otherrepo` → judged on otherrepo, not on the brief's own repo, where the same stem merged. Nine malformed lines, two lines, and no repo → one A11 failure each. No line → `[]`, and `route_merged` is never called. `report` shows the A11 pass line and `Depends-on: … merged on testrepo/main (<sha8> [`; a refusal is listed `  • A11 DEPENDS-ON — `.
  - HEAD: `assert 0 == 1` ×13 and `('<line>', [])` ×9. The pass line was `A1/A2/A8/A9/A10`.
- **P2:**
  - Selection over `[501-b (depends 503-a), 502-c, 503-a]` → `502-c`. B stays in `queue/`, with exactly one `WAITING depends-on 503-a-later` line and no pause.
  - The real loop fires `['502-c-free.md', '503-a-later.md', '501-b-needs-a.md']`, with A's stub route merging as it runs. One WAITING line across the three scans. Count 3, no failures.
  - After A merges, B is selected.
  - A cycle fires nothing, sleeps `("running", 10)`, and persists both as waiting.
  - HEAD: `['501-b…','502-c…','503-a…']` (B fired first); `no attribute '_next_brief'`.
- **P3:**
  - With A in `failed/`, `held/s7x/` or nowhere, the real loop fires nothing. B moves to `queue/held/depends-on/`, with a `.reason` naming A and the tray. The sleep is `("running", 10)` (not paused). `consecutive_count` stays 2. `failed == refused == []`. B is not in `failed/`.
  - One unmet dependency in `failed/` holds even beside a queued one.
  - A chain is held in one scan.
  - An unmovable hold is passed over and said once.
  - `status` line 1 shows `602-x.md ← 603-y` and `601b-needs-dep.md`. The JSON has `depends_waiting` and `depends_held[0].reason`.
  - HEAD: `['601b-needs-dep.md'] == []` (fired), ×3.
- **P4 (F-289 replay):** branch `orch-t-309a-member-function-1` committed and never merged; `309a-member-function-1.md` in `failed/`; `309b-home-bp-platform-1` declaring it; `309c-…` free. The loop fires only `309c-member-partner-results-1.md` and 309b is held. `prefire.check` on the held 309b gives one A11 failure naming 309a and `queue/failed/`.
  - HEAD: `['309b-home-bp-platform-1.md', '309c-…']`. 309b fired first, which is F-289.
- **P5 (A13):**
  - A spy on `canon_assert.route_merged` is called by `retire_merged_briefs` (B6), by `prefire.check` (A11) and by `_next_brief` (D4, through A11's reading).
  - The grep:
    ```
    $ grep -rn "route_merged(\|_landed(" --include=*.py . | grep -v "^./tests/"
    canon_assert.py:508:def _landed(…)            canon_assert.py:544:def route_merged(…)
    canon_assert.py:553:    return _landed(repo, repo.branch_for(brief))
    canon_assert.py:594:        landed = route_merged(repo, brief.name)        ← B6
    prefire.py:456:        landed = canon_assert.route_merged(repo, stem)       ← A11 (and D4 through it)
    (+ orchestrator.py `_unit_cache_store_landed(` — an unrelated name that matches the substring)
    ```
  - HEAD: `canon_assert.route_merged` is None.
- **P-scan (read-only, live):** all 375 briefs under `~/spectricom-orchestrator/queue/` (every tray) were run through `parse_depends_on`. 3 carry a line: `done/145-voice-l-1r.md`, `145r`, `145s`, each `## Depends on: **SPEECH-SEAM-1 (brief 144) merged to main.** Pre-flight below.` That prose is now an A11 refusal (found-and-left 3). No queued, held or failed brief is affected. `python3 prefire.py briefs/330-orch-depends-on-1.md` gives `✅ A1/A2/A8/A9/A10/A11 pass — SCP_Kanban row 360 READY (SCP_Kanban_v0-438.md); …`.

## 6 · Gates (targeted, D-S7CORE30-05; no full suite, no baseline)
- `python3 -m pytest tests/test_prefire.py tests/test_depends_on.py tests/test_control_scope.py tests/test_runtime_parse.py -q` → **234 passed**.
- `python3 -m py_compile prefire.py canon_assert.py queue_daemon.py` → clean. No ruff, flake8 or pyflakes is installed on this host.
- **Controls:** the test files that drive the daemon, the trunk invariant or `canon_assert` (`test_queue_retire`, `test_queue_pause`, `test_queue_gate_log`, `test_orch_lane`, `test_capacity`, `test_config_truth`, `test_executor_default`, `test_yorsie_safety`, `test_gate_cost`, `test_route_landed`, `test_stale_base`, `test_canon_assert`) → **445 passed**, none changed.
- **Safety check:** `test_prefire.py::test_D3_the_fire_refuses_a_brief_with_no_test_scope`, which calls `orchestrator.run_batch`, is guarded: `fire_toni` is patched to fail and prefire refuses. No nested executor started.

## 7 · Found and left
1. **The `--force` and refusal texts in `orchestrator.py` are stale.** `:6359` says `--force: pre-fire assertions (A2/A8) BYPASSED; A1 Kanban READY not checked`, and `:5349` the error says `pre-fire assertions failed (A1/A2/A8)`. Neither names A9/A10 (stale since 283) or A11. `orchestrator.py` is outside §2. The bypass itself is total.
2. **A second, older dependency dialect.** `orchestrator.py:728-790` has `# depends_on_batches: [x.md, …]` (`parse_batch_deps` / `check_batch_deps` / `find_unblocked`). The `deps`, `watch` and `run-all` commands use it, keyed on state.json `completed`, not on a merge. Neither the daemon nor prefire reads it. Left (outside §2).
3. **Prose `## Depends on:` lines are now a refusal.** The 145-series briefs (in `done/`, never re-fired) wrote one in prose. A brief written that way is now an A11 refusal at the fire, which names the grammar, instead of a silent pass. That is D1's "never a silent pass", applied to the habitual wording, which the regex also matches. A brief template should show the grammar, but **this repo has no `docs/`**, so no template note was added. The header is documented in `prefire.py`'s module docstring (`:35-39`).
4. **Cycles wait forever.** Two queued briefs that depend on each other fire nothing, without pausing; `status` shows both waiting. A self-reference is refused as malformed. A cycle is not detected.
5. **Done but not merged is held, by design.** A dependency in `queue/done/` that git cannot see as merged is HELD and named `queue/done/`. Examples: an exit-0 route with no commits, a merge under another branch name, or a fast-forward merge whose branch was deleted and whose reflog expired (about 90 days by default; detector 1 also scans only the last 500 merges). D4 lists failed / held / nowhere; I read "not still queued" as hold.
6. **Mixed dependencies hold.** A brief with one unmet dependency queued and another in `failed/` is held, not waiting. It waits only when the queue alone can still merge every unmet dependency.
7. **Malformed line in the daemon.** The daemon fires it and A11 refuses it, giving exit 2 → FAILED → stop-on-failure pause. That is the existing path for any prefire refusal (D5). The daemon does not pre-refuse it.
8. **Releasing a held brief is manual.** Nothing re-checks `queue/held/depends-on/`; an operator moves a held brief back to `queue/`. Its `.reason` file stays beside it until it is removed or overwritten.
9. **The pause notice can name a waiting brief.** Its "next brief" (`_write_pause_notice`, `queue[0]`) is still the first brief in filename order, which may be one that is waiting.
