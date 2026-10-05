# filename: briefs/114-orch-lane-1.handback.md

# 114 · ORCH-LANE-1: handback

All five decisions (O1–O5) are in, and P1–P6 are green. A route in one repo no longer holds another repo's queue. Every pause writes a notice that `status` shows on line 1, and the notice goes to Slack once a webhook is configured. `orchestrator.py verify <stem>` verifies a route in any repo with one read-only command. The A1 Kanban families come from `config/repos.yaml`. A gate command that dies fast now names its exit code and stderr.

Two things you need to know first:
- **Slack is not configured on this machine.** `~/spectricom-orchestrator/slack-webhook.json` does not exist. Until George sets a webhook, "out loud" means the notice file, the `status` line and the daemon log. That is Found-and-LEFT item 1.
- **O1 and O2 live in `queue_daemon.py`.** They take effect only after Gemma restarts the daemon (L-29). The restart steps are under THE CONSEQUENCE.

Also: I made the save of `queue-state.json` atomic. That fixes a flake that was already in the suite at `8d962c5`, and P6 needs the suite green. That is item 2.

- **Branch:** `orch-orch-114-orch-lane-1`, from `8d962c5`. Ancestry checked: `git merge-base --is-ancestor 8d962c5 HEAD` ✓.
- **Commits:** `ecf1114` has the code, tests and fixtures. The second commit is this file.
- **Tests:** `pytest -q tests/` at `8d962c5` collected **935**: 934 passed and 1 failed, the flake in item 2. At `ecf1114` it gives **996 passed**. The +61 are all in the new `tests/test_orch_lane.py`. No test was removed, and one existing test was changed (item 2).

## Found and LEFT

1. **Slack is not configured, so the announcement has no Slack leg yet.**
   - `ls ~/spectricom-orchestrator/slack-webhook.json` returns `No such file or directory`.
   - The daemon looks for the webhook at `<ORCH_DIR>/slack-webhook.json`, which is where `slack_notify.py set-webhook` writes it, and calls `slack_notify.send_slack` only when that file exists.
   - With no webhook, every pause still writes `state/queue-paused.json` and the line `[QUEUE] 📣 pause notice … — Slack not configured (…) — not sent`, and `status` shows the notice on line 1.
   - George's step, only if he wants Slack: `python3 slack_notify.py set-webhook "<url>"`, then `python3 slack_notify.py test`.
2. **A flake was in the suite at `8d962c5`. I fixed it, because P6 needs a green suite.**
   - `tests/test_queue_pause.py::TestResume` read `queue-state.json` while the daemon thread was halfway through `write_text`, which truncates and then writes. It then got `JSONDecodeError: Expecting value: line 1 column 1`.
   - Evidence at `8d962c5`:
     - the first full run stopped on `test_reset_consecutive_is_reachable` (`-x`);
     - a loop of that one test failed on run 4 of 15;
     - the second full run failed `test_a_request_left_before_start_is_not_replayed`.
   - The fix is in `queue_daemon.py`, an allowed file. `_save_state` now writes through `_write_json_atomic`: a temp file per process and thread, then `os.replace`, so a reader sees the whole old file or the whole new one.
   - A second race in `test_round_trip` was already there at base, and writing the notice made it wider. The test waits for the daemon's in-memory status to be `paused`, but `request_control` reads the file the daemon saves a moment later. Its wait now requires `queue-state.json` to say `paused` too. That one condition is the only change to an existing test.
   - After both fixes, `TestResume` + `TestP2PauseNotice` passed **40 of 40** looped runs.
3. **The build gate still gives FAIL(product) for a shell builtin `/bin/sh` lacks.**
   - `source: not found` (exit 127) matches no F-20 signal. `toolchain-missing` names binaries only (`npx|npm|node|pytest|python3?|tsc|vitest|playwright`). §3 forbids changing gate semantics, so O5 adds its clause only to a **BLOCKED(environment)** message.
   - The negative control: a fast red build with no signal stays `FAIL(product)`, worded exactly as before.
   - Route 108 was not affected. ai-foundation is not in `PRE_MERGE_GATES`, so 108 ran the unit gate only.
   - For the same reason, P5's command `false` gives BLOCKED(environment) on the **unit** gate (`comparison-unavailable`, as before, now with `(exit 1); stderr empty`). On the build gate it would still be `FAIL(product)`, `exit 1`.
4. **Unattributable legacy markers still hold every repo. This is the safe direction, kept on purpose.**
   - A root `running.json` names no repo. `orchestrator.write_running` does not write one (`orchestrator.py:1226` at base), so the daemon attributes the file through the per-repo lock that names its batch.
   - If no lock names that batch, the marker holds every repo, as before. That covers three cases: a pre-[ORCH-4] marker; a mid-write or unreadable file; and the moment between `write_running` and `_write_running_marker` (`orchestrator.py:4085-4086` at base).
   - A pre-[ORCH-4] mirror that names nobody also holds, which matches orchestrator's own `_lock_candidates`. The existing tests `test_a_live_marker_is_waited_on` and `…held_and_said_once` pin this behaviour, and they still pass.
   - Every marker live today is attributable. See the live check in the gate table.
5. **The daemon is still serial: one route at a time.**
   - O1 lets it fire past another repo's route that was started **directly**. It never runs two routes of its own at once, so P6's "serial per repo" holds a fortiori.
   - Parallel daemon routes across repos would be a separate decision.
6. **The root `running.json` is one global file shared by every route.**
   - Two concurrent routes overwrite it, and the first to finish deletes it (`clear_running()`) while the other is still running.
   - The per-repo locks are right, and since O1 the daemon decides by them. The root file now feeds only the dashboard and `qstat.sh`.
   - `write_running` is outside §3 ("orchestrator.py: verify subcommand + gate message only"), so I left it.
7. **How `verify` finds a direct run's log, and what it costs:**
   - A direct run writes only `logs/orch-<ts>.log`, and 1233 of those exist today. `verify` scans them newest first and reads only the first 4 KB of each, looking for `Parsed <stem>.md:`.
   - The scan stops at the first match. It also stops at the mtime of the stem's daemon log: a direct run counts only if it started after that log was last written.
   - For a stem with no logs at all, it reads 4 KB from each of the 1233 files and then says so in one line.
   - Every `orchestrator.py` subcommand writes an empty `logs/orch-<ts>.log` when the module is imported (`setup_logging`). That was already true. `verify` skips its own log, and since it logs nothing, no later `verify` matches it either.
8. **For a self-mod (orchestrator) route, `verify` has no merge SHA to default to.**
   - `_self_mod_auto_merge` logs `brought N commits to main` with no SHA.
   - So the default falls back to the route branch if it still exists, then to the newest `main` commit that touches the handback. `--commit` overrides both.
9. **`verify` refuses to run when `ANTHROPIC_API_KEY` is set (exit 3), like every `orchestrator.py` subcommand.** The AUTH GUARD runs at import.
10. **`~/_eos/s7core17/verify.sh` is outside the repo and I did not touch it.** Use `orchestrator.py verify <stem> [--commit <sha>]` instead. It takes the same two inputs and runs the same four sections, plus the direct-run log and repo resolution.
11. **`qstat.sh` does not show the pause notice.** It is outside §3. It already shows `⏸️ DAEMON PAUSED … paused_reason=…` from `queue-state.json`.
12. **Any pause announces itself, not only the three the brief lists.**
    - The three are max-consecutive, stop-on-failure and operator.
    - Also announced: the start pauses `start:queue-non-empty` and `start:dirty-tree:<repo>`, and `refused-unmovable:<brief>`.
    - Once Slack is configured, every daemon restart with work queued sends one message. That is by design: a paused queue says so.
13. **`status` line 1 still begins with `daemon_status=…`.** The notice is appended to it as `| ⏸ next brief … · resume: … · <Slack result>`.
    - Two existing tests pin that prefix (`test_status_prints_them_on_its_first_line`, `test_negative_control_plain_status_is_unchanged`).
    - `status --json` gains a `pause_notice` key, which is the notice or `null`.
    - The notice is shown only while `queue-state.json` says paused for the same reason, so a stale one is never shown.
14. **The resume command in the notice names its pause.** It reads `cd ~/spectricom-orchestrator && python3 queue_daemon.py resume [--reset-consecutive] --reason <paused_reason>`. Because of ORCH-CONTROL-SCOPE-1 C1, it cannot lift a later, different pause. A test runs the command exactly as written against a live daemon thread and gets `running`.
15. **The dashboard's in-process daemon (`orch-dashboard.py --daemon`) now writes notices too.** Its HTTP resume calls `resume()` / `reset_consecutive()`, and both remove the notice. The dashboard is not running (`ps`).
16. **The brief's §0.5 line number is wrong.** `orchestrator.py:995` is `_git_read`. The unit gate's `/bin/sh` call is `_run_unit_suite`, `orchestrator.py:2861` at base. The substance of §0.5 is confirmed (§0 below).
17. **The verify fixtures are real route-109 logs.** The orch log is verbatim. The Toni log keeps its real header and trailer, but its body is cut to four neutral lines, because the full body carries personal details that do not belong in a test fixture.
18. **I did not commit this brief.** It is outside §3, as with routes 94 and 104.

## §0 as-built at `8d962c5` (L-30)

1. **Confirmed.**
   - `grep -n "def _fire_lock_held" -A3 queue_daemon.py` → `795: def _fire_lock_held(self) -> bool:` … `798: return any(ORCH_DIR.glob("running*.json"))`.
   - Any root marker held every brief.
2. **Confirmed.**
   - `sed -n 845,848p queue_daemon.py` → `if self.consecutive_count >= self.config["max_consecutive"]: print(...Max consecutive...) self._mark_paused(f"max-consecutive:…")`.
   - `_mark_paused` (`:492-494`) only `print`s `[QUEUE] PAUSED — {reason}. Resume without a restart: …`, which goes to the daemon log alone.
3. **Confirmed.**
   - `verify.sh:2` reads `R=~/spectricom-clinical-mp`.
   - `ls -t ~/spectricom-orchestrator/logs/*/orch-109-minime-rules-1-*.log` → `No such file or directory`. 109 was a direct run, and its log is `logs/orch-20261004-184720.log`.
   - `OL=""; sleep 8 | timeout 3 bash -c "grep -E 'FINAL STATUS' $OL"` → exit **124**: `grep` was still waiting on stdin after 3 s.
4. **Confirmed.** `sed -n 46p prefire.py` → `KANBAN_FAMILIES = ("SCP_Kanban", "Yorsie_Kanban")`.
5. **Confirmed, at a different line (item 16).**
   - `orchestrator.py:2861`: `r = subprocess.run(cmd, shell=True, …)`.
   - Run the same way, `source /nonexistent/activate && pytest` gives `'/bin/sh: 1: source: not found\n' 127`. `/bin/sh` → `/usr/bin/dash`.
   - Route 108's log (`logs/orch-20261004-163715.log:33`): `⛔ Unit gate: suite output did not parse on branch (runner=unrecognised); baseline comparison impossible — BLOCKED(environment)`.
   - The branch and baseline legs both took `0.1s`, and neither message gave the exit code or stderr.

## Shipped

### O1 · per-repo fire lock in the daemon (`queue_daemon.py`)
- `_fire_locks(repo)` and `_fire_lock_held(repo)` run after P-STALE (stale-marker clearing is unchanged). A brief naming `repo` is held by exactly these markers:
  - its own `state/running-<repo>.json`;
  - a legacy global marker (root `running*.json`, or the `state/running.json` mirror) that names this repo. A marker names a repo either through its own `repo` field, or through the per-repo lock whose `batch_id` matches its batch. A legacy marker that names no repo also holds (item 4).
- The run loop takes the repo from the header (`lane`), waits only on that repo's lock, and names it: `fire lock held for clinical-mp (<marker>) — waiting before …`.
- If the header is edited during the wait to name another repo, the brief is not fired into that repo's lock. The loop goes round and asks that repo's lock first.
- `_marker_slug` restates orchestrator's slug rule, for the same reason `_pid_alive` is restated: importing orchestrator writes a log.

### O2 · a pause is announced (`queue_daemon.py`)
- `_mark_paused` is the one entry to every pause. In the daemon (`is_daemon`), it writes `state/queue-paused.json` atomically with these fields: `reason`, `at` (= `paused_at`), `next_brief`, `queued`, `resume` (the exact command, item 14), `pid` and `slack`.
- The Slack send runs at the next poll of `run_loop` (`_send_pause_notice`), outside the lock, because `send_slack` can block for its full 10 s timeout. The result is written back into the notice.
- `resume()`, `reset_consecutive()` and a start that runs all remove the notice, and drop any notice not yet sent.
- An expired resume (C1) leaves both the pause and its notice in place.
- A CLI process's `QueueDaemon` never writes a notice.
- `status` appends the notice to line 1 (item 13), and `--json` gains `pause_notice`.

### O3 · `orchestrator.py verify <brief-stem> [--commit <sha>]`
1. **Repo.** From the `#!queue repo=…` or `## Repo:` line of the brief. `verify` looks for the brief in `queue/`, `queue/done/`, `queue/failed/`, then each repo's `briefs_subdir`. With no brief, it uses the one repo whose log dir holds this stem's logs. If two briefs disagree, or no brief and no log exists, it says so in one line and exits 2.
2. **Orch log.** The stem's daemon log, `logs/<log_subdir>/orch-<stem>-<ts>.log`, matched on the exact stem. verify.sh's glob `orch-109-x-*` also matched `orch-109-x-2-*`. If a direct-run log is newer, that log wins (item 7).
3. **Printed:** the last 14 lines matching `FINAL STATUS|verdict|gate|baseline|SIT|unit|🛡|Merged`, plus the FINAL STATUS line itself if it fell outside them. With no FINAL STATUS line at all, it prints a line saying so.
4. **Toni log.** The one the orch log names (`Log: …`), looked up by name in the repo's log dir, else the newest `toni-<stem>-<ts>.log`. `verify` then runs `handback_scan` on it in-process.
5. **Commit.** `--commit` if given. Otherwise the orch log's `🔀 Merged … (<old> → <new>)`, then the route branch, then the newest merge-target commit that touches the handback.
6. **Git output.** `git show --stat` (last 25 lines), then `git show <sha>:<briefs_subdir>/<stem>.handback.md` (first 80 lines).
7. **Read-only.** It runs only `git show`, `git log` and `git rev-parse`, with `stdin=DEVNULL`. It never reads stdin.
- **Exit codes:**
  - `0`: every section found, and nothing to look at.
  - `1`: found, with something to look at: no FINAL STATUS, a handback-scan FAIL, or the commit or its handback not shown.
  - `2`: cannot verify: an unknown stem or repo, a commit argument that looks like an option, or a missing orch or Toni log. Each is said in one line. If the Toni log is the only one missing, the orch section still prints first.

### O4 · Kanban families from config (`prefire.py`, `config/repos.yaml`)
- `config/repos.yaml` gains `kanban_families: [SCP_Kanban, Yorsie_Kanban]`.
- `prefire.kanban_families()` reads it on each call. Anything other than a non-empty list of family names falls back to the default; the value is never guessed.
- `check_kanban` messages are unchanged apart from the family list. With the default config they are byte-identical, and the existing A1 tests pass untouched.

### O5 · a gate command that dies fast says so (`orchestrator.py`)
- `UnitSuiteRun` and `BuildGateOutcome` gain `stderr_head`. It is `None` when no exit was observed: a timeout, an exception, or a cached leg.
- `_gate_fast_death` returns `failed in 0.1s (exit 127); stderr: <first 5 non-blank lines, joined by ⏎>` when the command exited non-zero in under `GATE_FAST_DEATH_S` (5).
- **Unit gate:** the `comparison-unavailable` detail keeps its old words and appends `; on the <leg> the test command failed in …`.
- **Build gate:** the clause is appended to the detail only when the verdict is already BLOCKED(environment). An env-file line is replaced with `<a line naming .env, elided — its values are never logged>` (canon §23.9d).
- No verdict changes.

## Gate table

| Gate | Result |
|---|---|
| Ancestry | `8d962c5` is an ancestor of HEAD ✓ |
| `pytest -q tests/` at `8d962c5` | **935 collected: 934 passed, 1 failed.** The failure is the flake in item 2: `test_a_request_left_before_start_is_not_replayed`; an earlier `-x` run stopped on `test_reset_consecutive_is_reachable` |
| `tests/test_orch_lane.py` against untouched `8d962c5` code (RED) | **57 failed, 4 passed** (61). Run in this worktree before any code change, with only the test file and fixtures added |
| `tests/test_orch_lane.py` at `ecf1114` (GREEN) | **61 passed** |
| `pytest -q tests/` at `ecf1114` | **996 passed**: 935 + 61 new, 0 removed, 1 wait condition tightened (item 2) |
| Flake loop at `ecf1114` | `TestResume` + `TestP2PauseNotice`: 40 of 40 runs clean |
| Live `verify`, read-only, against the real 108 and 109 logs (copied to a scratch HOME, real `repos.yaml`) | **109:** exit 0. FINAL STATUS `passed`, handback-scan `1 clean`, `show --stat 7822990 (the orch log's merge line)` 34 files, handback head `# MINIME-RULES-1 — handback`. **108:** exit 0. FINAL STATUS `blocked`, the gate line showing route 108's `source venv/bin/activate && …`, `show --stat orch-aif-108-minig-listen-1 (the route branch — no merge in the orch log)`. **110** (clinical-mp, logs not copied): one line, exit 2. In `~/spectricom-ai-foundation`, `git status`, `HEAD` and `stash list` were the same before and after |
| Live O1 check, read-only (`_fire_locks` on the live `~/spectricom-orchestrator`, with P-STALE stubbed out because it renames files) | `clinical-mp` held by `state/running-clinical-mp.json` (route 112, a direct run, pid 55741). `ai-foundation` held by nothing. `yorsie` held by nothing. `orchestrator` held by its lock, the root `running.json` and the mirror (this route, 114). The old rule held all four |
| Diff bounded to §3 | `queue_daemon.py`, `orchestrator.py` (the `verify` subcommand; the gate message and the `stderr_head` that carries it), `prefire.py`, `config/repos.yaml` (`kanban_families` only), `tests/**`. `slack_notify.py` unchanged (reused). No merge or gate semantics, route timeout or repo test command changed |
| Handback guard (`config/handback-guard.json`, 6 rules, via `canon_assert.check_handback_invariants`) | this file: **CLEAN** |
| Destructive operations | **None.** Every daemon, git and log write in the tests ran under `tmp_path`. The live check stubbed the marker renaming and ran `verify` against copies. No process was signalled. The live queue, `state/` and logs were only read. The shared stash list is unchanged (2 entries before and after) |

**The 4 tests that passed on `8d962c5` are negative controls:**
- P3: `verify` writes nothing in the repo. It passed at base only because the subcommand did not exist.
- P4: a family absent from config is refused, with today's exact message.
- P5: a parseable red suite gets no clause.
- P5: a fast build `FAIL(product)` keeps its exact detail.

| Predicate | Tests (`tests/test_orch_lane.py`) | RED at `8d962c5` (one failure line) | GREEN | Negative control |
|---|---|---|---|---|
| **P1** (O1) | `TestP1FireLockPerRepo`, 15 tests | `assert [] == ['110-visit-release-safety-1.md']`: with route 109's three markers (root, lock, mirror) present, the old daemon held 110 (clinical-mp). Also `TypeError: _fire_lock_held() takes 1 positional argument but 2 were given` | ✓ 110 fires. Checked against markers written by orchestrator's own `write_running` / `_write_running_marker` too. 9-case table over lock, root, mirror and unattributable | its own repo's lock holds: `fire lock held for clinical-mp (…)`, nothing fired ✓. A dead marker in another repo is still cleared ✓. A header edited mid-wait to another repo is not fired into that repo's lock ✓ |
| **P2** (O2) | `TestP2PauseNotice`, 11 tests | `FileNotFoundError: …/orch/state/queue-paused.json` | ✓ max-consecutive writes the notice (reason, `at` = `paused_at`, next brief, `… resume --reset-consecutive --reason max-consecutive:3`); the stubbed notifier is called once with all of them. Stop-on-failure, operator and start pauses are announced. `status` line 1 carries it. The command, run as written, resumes a live daemon | no webhook ⇒ no send, file still written ✓. A CLI object never announces ✓. A stale notice is not shown and a running start clears it ✓. An expired resume leaves it ✓ |
| **P3** (O3) | `TestP3Verify` (10 tests) and `TestP3VerifyLogChoice` (4 tests) | `orchestrator.py: error: argument cmd: invalid choice: 'verify'`, exit 2 ≠ 0 | ✓ `verify 109-minime-rules-1` on the ai-foundation fixture logs exits 0 with stdin closed, and also with an **open** stdin pipe that is never written. It prints FINAL STATUS, handback-scan, `--stat` and the handback head | an unknown stem gives one line, exit 2 ✓. A missing orch log gives one line, exit 2 ✓. A missing Toni log gives one line in its section, exit 2 ✓. `--commit=--output=…` is refused ✓. An outstanding-work Toni log exits 1 ✓. A stem prefix is not a match ✓ |
| **P4** (O4) | `TestP4KanbanFamilies`, 9 tests | `A1 KANBAN — '## Kanban: X_Kanban row 7' names no Kanban family (SCP_Kanban or Yorsie_Kanban), not READY` (should pass). `KeyError: 'kanban_families'` (real config) | ✓ `X_Kanban` in config + `X_Kanban_v0-1.md` row 7 READY ⇒ `[]`. Messages list the configured families | absent from config ⇒ refused, message byte-identical to today ✓. 5 malformed values ⇒ the default ✓ |
| **P5** (O5) | `TestP5FastGateDeath`, 12 tests | detail was `suite output did not parse on branch (runner=unrecognised); baseline comparison impossible`, with no exit code. Build: `missing toolchain binary; matched 'pytest: command not found'`, with no clause | ✓ real `false` (unit gate) ⇒ BLOCKED(environment) `… (exit 1); stderr empty`. 6 stderr lines ⇒ `e1 ⏎ … ⏎ e5`, no `e6`. Route 108's `source …` under `/bin/sh` ⇒ `(exit 127); stderr: /bin/sh: 1: source: not found`. Build BLOCKED(env) ⇒ `; the build command failed in … (exit 127); stderr: pytest: command not found` | a parseable red suite gets no clause ✓. A build `FAIL(product)` keeps its exact detail ✓. 5.0 s, exit 0 and no observed exit ⇒ none ✓. An `.env` line is elided ✓ |
| **P6** | full suite | n/a | **996 passed**. The daemon is still serial (item 5) | `TestP1 test_negative_control_its_own_repos_lock_holds` ✓ |

## THE CONSEQUENCE (D-S7CORE13-03)

**From the next fire after this merges, before any restart.** Every route is a new `python3 -u orchestrator.py run …` process, so it loads the new `orchestrator.py` and `prefire.py`:
- `orchestrator.py verify <stem> [--commit <sha>]` is available. It replaces `~/_eos/s7core17/verify.sh`.
- A unit or build gate command that dies in under 5 s puts its exit code and the first 5 stderr lines into the BLOCKED(environment) message and FINAL STATUS. No verdict changes.
- A1 reads `kanban_families` from `config/repos.yaml`. It holds the same two families as before, so nothing is refused or admitted differently until a family is added there.

**After Gemma restarts the daemon (L-29).** `queue_daemon.py` changes take effect only in a new daemon process:
1. A brief waits only on its own repo's lock. A direct route in another repo, such as 112 (clinical-mp) running now, no longer holds an ai-foundation, yorsie or orchestrator brief.
2. Every pause writes `state/queue-paused.json`, and `python3 queue_daemon.py status` line 1 shows the next brief and the exact resume command. Slack follows once George sets a webhook (item 1).
3. `queue-state.json` is written atomically.

**Gemma's restart step (L-29, with L-46 in mind).** The live daemon is pid **79256**, run by hand as `python3 -u queue_daemon.py` in `~/spectricom-orchestrator`, logging to `~/_eos/logs/s7core14-queue-daemon2.log`. Its queue is empty and `current_batch` is null now. The systemd unit is not installed (`systemctl --user is-enabled` → `not-found`).
1. **After this route has merged to `main`, confirm the daemon is idle.** `python3 queue_daemon.py status` must show `"current_batch": null`. Stopping the daemon mid-route cancels the route.
2. **Stop it:** `kill 79256`. Use the pid from `status` line 1 if it has changed.
3. **Start it in `~/spectricom-orchestrator`:** `nohup python3 -u queue_daemon.py >> ~/_eos/logs/s7core19-queue-daemon.log 2>&1 &`.
4. **Expect a paused start if work is queued (L-46).** With work queued, the new daemon comes up paused (`start:queue-non-empty`). That pause is now announced: `status` line 1 ends `| ⏸ next brief <first> · resume: cd ~/spectricom-orchestrator && python3 queue_daemon.py resume --reason start:queue-non-empty · …`. Run that command to fire. With an empty queue, the daemon comes up `running`.
5. **Check:** `python3 queue_daemon.py status` line 1 shows the new pid, `alive`.

**George's optional step:** `python3 slack_notify.py set-webhook "<url>"` puts pauses into Slack (item 1).
