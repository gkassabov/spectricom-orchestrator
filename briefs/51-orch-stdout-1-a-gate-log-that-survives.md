#!queue model=claude-opus-5-5 effort=high repo=orchestrator

# ORCH-STDOUT-1 — a gate log that survives

## Repo: orchestrator
## Batch ID: s7core15-orch-stdout-1
## Briefs: 1
## Estimated runtime: 30-45 min
## Spec reference: [ORCH-STDOUT-1], Bug Registry v1-48
## Predecessor: current `main` tip — `23ab07f` (GATE-SIT-2) when this brief was written, verified with `git log`. Reported baseline there: `pytest -q tests/` = **454 passed, 0 failed**. The brief author did NOT re-measure it; you measure it (AC-SO-10).

## 0 · FIRST STEP

Read these in full, in this order, before you design anything. Every name and line below was verified on `main` @ `23ab07f`. If a line has moved, find it by name with grep. Do not trust the number.

1. `queue_daemon.py:376-399`: the command string (`:376-380`), the `Popen` with `stdout=subprocess.PIPE, stderr=subprocess.STDOUT` (`:385-389`), the bare `self.current_process.wait(timeout=…)` (`:390-391`), the timeout branch (`:392-396`, exit `-1`) and the spawn-exception branch (`:397-399`, exit `-2`). **Nothing reads the pipe.** `grep -rn current_process` over the repo finds one other mention, a docstring in `orchestrator.py:1392`. The dashboard (`orch-dashboard.py:25`, `:901-902`) only constructs and starts the daemon.
2. `queue_daemon.py:401-431`: the entry dict (`:405-411`: `file`, `exit_code`, `duration_s`, `started_at`, `finished_at`, and **no log path**), the completed branch (`:413-420`) and the failed branch (`:421-427`).
3. `queue_daemon.py:215-236`: `cancel_current`, the fourth way an entry is appended (`:226-232`, exit `-9`).
4. `queue_daemon.py:130-156`: `_load_state` / `_save_state`. The lists are capped on save: `completed[-30:]`, `failed[-15:]` (`:148-149`).
5. `queue_daemon.py:73-89`: `repo_route`, which reads `config/repos.yaml` at `:79-84`. `:452-475` is the `__main__` CLI. `check` (`:465-472`) reports through a method (`find_merged_briefs`, `:275-280`) so the CLI and the tests call the same code.
6. **The convention you must match.** In `orchestrator.py`: `LOG_DIR = ORCH_DIR / "logs"` (`:76`); `LOG_SUBDIR = r.get("log_subdir", name)` (`:166`); `ensure_log_subdir` (`:475-479`); and `fire_toni` (`:799-847`). `fire_toni` names the per-route log `log_subdir / f"toni-{batch_file.stem}-{ts}.log"` with `ts = %Y%m%d-%H%M%S` (`:800-802`), writes a header (`:828-829`), gives the child **the open file handle** as `stdout`, with `stderr=subprocess.STDOUT` (`:831-833`), and writes a `Finished/Exit` trailer (`:835`). That is how this codebase already persists a child's output. Every `log_subdir` in `config/repos.yaml` (`:12`, `:24`, `:36`, `:64`, `:80`, `:91`) equals its repo name today.
7. `orchestrator.py:500-511`: `setup_logging`. A `FileHandler` writes to `logs/orch-<ts>.log` at the TOP level of `logs/` (`:503-505`), and a `StreamHandler` writes the same records to stderr (`:506`). Stderr is the pipe the daemon discards.
8. `canon_assert.py:557` `check_queue_trunk_invariants`, `:606-618` `StaleBaseViolation`, and `:621-648` `check_branch_freshness_invariants`. Also read `:505-510`, `_landed`'s "unreadable is never a violation" rule, and §2 on why this predicate breaks that rule on purpose. The `# ── verdict building` block starts at `:651`.
9. `tests/test_queue_retire.py:411-425`: the `daemon` fixture, which monkeypatches `QUEUE_DIR/QUEUE_DONE/QUEUE_FAILED/QUEUE_STATE/REPOS_CONFIG`. Also `:471-473` and `:393`: source-parsing tests on `run_loop` that must stay green.

## 1 · WHY THIS EXISTS

`run_loop` spawns every daemon-fired route as `Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)` (`queue_daemon.py:385-389`) and then only calls `.wait(timeout=11400)` (`:390-391`). No code ever reads that pipe. Two defects follow.

**(b) The documented deadlock, which is the serious one.** The Python docs warn that `wait()` deadlocks when the child writes enough to a `PIPE` to fill the OS buffer (64 KiB on Linux). Once that happens the child blocks on `write()`, the parent blocks in `wait()`, and neither moves until the 11400 s (3h10m) kill. The route is then recorded as failed with exit `-1`, and `stop_on_failure` (`:425-427`) pauses the whole queue. It has not bitten yet only because a normal route's output is small. For example, `logs/orch-20260927-122214.log` (route 45: build + 3 SIT batches + unit baseline) is 5.8 KB. Any of these would cross 64 KiB: one verbose failure, a traceback loop, a `print` of a gate tail, or a warning storm. The orchestrator's own pytest runs already produce 115–185 KB of the same log stream (`logs/orch-20260927-125243.log`, 185 523 bytes). An unattended overnight chain would hang on this, and nothing in the design prevents it.

**(a) What the pipe discards. The premise needs correcting before it is built on.** The owner's report says no daemon-fired route left a gate log on disk. **That is only partly true, and the brief must not repeat it.** The orchestrator child writes every `log.*` record twice (`orchestrator.py:505-506`): once to `logs/orch-<ts>.log` through the FileHandler, and once to stderr, which is the pipe. So the **gate verdict lines are on disk** for every daemon route today. For example, `logs/orch-20260927-122214.log` holds route 45's build, SIT batches, unit baseline, merge and `FINAL STATUS`. GATE-SIT-2's isolation leg logs through `log.info` (`orchestrator.py:1902`, `:3165`) and writes an `isolation` key into `sit-archive/orchestrator-sit-log.json`, so it **is** observable in production. What is genuinely lost:
- **Every byte the child writes outside `log`**: `print()` output, Python warnings, and, most importantly, **uncaught tracebacks**. A route that crashes is recorded as `exit_code: 1` with no reason anywhere on disk. `queue-state.json` holds 8 such `failed` entries, and none says why.
- **The link from the record to the log.** A queue-state entry has no log path (`:405-411`). The `orch-<ts>.log` it corresponds to sits at the top of `logs/`, next to 1 109 others, named by timestamp only, with no brief name and no repo. Test runs write there too (every `import orchestrator` calls `setup_logging`, `:511`). Finding route 45's log meant matching `started_at 12:22:14.55` to `orch-20260927-122214.log` by eye. After a fire-lock wait (`:350-363`) even that match breaks.

**The raw gate-runner output is not on disk in either path.** That means `npm run sit:gate` and `npm test` stdout. Every gate call uses `capture_output=True` (e.g. `orchestrator.py:1829`, `:1918`, `:2442`), is summarised into `log` lines, and SIT red tails go to the sit-log. That is a separate defect with a separate fix inside `orchestrator.py`, so it is **not this brief** (§4, successor).

## 2 · THE TARGET STATE (D-S7CORE13-02 · S1: a runnable predicate, not a symptom list)

**Every entry the queue daemon records in `queue-state.json` `completed` or `failed` names, under `log_file`, a regular, readable, non-empty file on disk that holds that route's full stdout+stderr. No daemon-fired child writes to a pipe.**

Ship the first half as one predicate in **`canon_assert.py`**. Place it directly after `check_branch_freshness_invariants` (`:621-648`) and before `# ── verdict building` (`:651`). This EXTENDS the module that already holds the daemon's other two queue invariants. It is not a fourth module.

```python
@dataclass(frozen=True)
class GateLogViolation:
    """One daemon-recorded route whose output is not on disk where its record says."""
    brief: str               # entry["file"]; "<unnamed>" if the entry has none
    started_at: str          # entry.get("started_at") or ""
    exit_code: object        # entry.get("exit_code")
    log_file: Optional[str]  # entry.get("log_file")
    reason: str              # see below

def check_gate_log_invariants(entries: Iterable[Mapping[str, object]]) -> list[GateLogViolation]:
    """[ORCH-STDOUT-1] EMPTY WHEN CLEAN. ..."""
```

**Set quantified over (A11):** exactly the mappings in `entries`, each judged once. Callers pass either one freshly recorded entry, or `completed + failed` as loaded from `queue-state.json`. Nothing is excluded by date, exit code or tray. At most one violation per entry: the **first** that applies, in this order:
- `no-log-recorded`: `log_file` absent, `None` or `""`.
- `log-missing`: the path does not exist.
- `log-not-a-file`: it exists and is not a regular file.
- `log-unreadable`: opening it and reading one byte raises `OSError`.
- `log-empty`: `st_size == 0`.

**Unreadable IS a violation here, on purpose.** `_landed`'s "unreadable is never a violation" rule (`canon_assert.py:505-510`) exists because its violations authorise a retirement. This predicate authorises nothing. It reports, and a log you cannot read is exactly the defect. Say so in the docstring.

The predicate proves the file is **there**. The tests in §5 prove it holds **the child's output**. Neither substitutes for the other, and the docstring says which is which.

The second half ("no pipe") is a source guard, AC-SO-07.

**Done:** the predicate returns `[]` for every entry the tests in §5 make the real `run_loop` / `cancel_current` record, across all five exit paths. It also returns one violation per entry over the pre-change history (AC-SO-02). Done is not "a log file now appears".

## 3 · SCOPE — exactly what to change

Three files change: `canon_assert.py`, `queue_daemon.py`, and the new `tests/test_queue_gate_log.py`.

### T1 · the predicate (`canon_assert.py`, after `:648`)
As §2 specifies. No I/O beyond `stat`/`open`, no git, no config.

### T2 · the daemon writes the child's output to a per-route file (`queue_daemon.py`)

**The mechanism is decided: redirect to a file handle.** `Popen(..., stdout=lf, stderr=subprocess.STDOUT)` with `lf` an open file. This is the exact shape `fire_toni` already uses (`orchestrator.py:827-834`). Why not the alternatives:
- **`communicate(timeout=…)`** drains correctly, but it holds the whole output in the daemon's memory and writes nothing to disk until the child exits. A daemon killed or restarted mid-route (it runs standalone as `python3 -u queue_daemon.py`, live now) would lose everything. `tail -f` on a running route would be impossible. And on `TimeoutExpired` you must kill and then `communicate()` again to collect the rest.
- **A reader thread** is correct too, but it adds a thread, a join, and failure handling for a copy loop the kernel does for free.
- **A file handle** means no pipe exists, so no buffer can fill. Output lands on disk as it is produced, so a crash or kill leaves a partial log. `cancel_current`'s `poll/terminate/kill` (`:217-222`) is unaffected.

Changes:
1. **`LOG_DIR = ORCH_DIR / "logs"`** as a module constant beside `QUEUE_STATE` (`:35`), mirroring `orchestrator.py:76`. Tests monkeypatch it.
2. **One reader of `repos.yaml`.** Factor the `yaml.safe_load` in `repo_route` (`:79-84`) into a helper that returns the repo's dict, or `{}`. `repo_route` uses it unchanged in behaviour. A new `_log_subdir(repo_name) -> str` uses it with **the same default rule as `orchestrator.py:166`**: `r.get("log_subdir", name)`. The subdir is configuration, read and never written. Do not add a field to `QueueRepo`.
3. **`route_log_path(repo_name, batch_name, when: datetime) -> Path`** returns `LOG_DIR / _log_subdir(repo_name) / f"orch-{Path(batch_name).stem}-{when:%Y%m%d-%H%M%S}.log"`. It sits in the same directory as `fire_toni`'s `toni-<stem>-<ts>.log`, with the same stem and timestamp shape. The `orch-` prefix says whose output it is. `mkdir(parents=True, exist_ok=True)` the parent. No new convention.
4. **Extract the spawn into a method `_run_route(self, cmd: str, batch_name: str, log_path: Path) -> int`** that replaces `:383-399`. `run_loop` keeps its signature and its `while self.status` loop (source tests `tests/test_queue_retire.py:471-473`). The method:
   - opens `log_path` for writing and writes a header in `fire_toni`'s form (`=== QUEUE ROUTE ===`, `Batch:`, `Started:`, `Command:`, a rule), then flushes;
   - `Popen(cmd, shell=True, executable="/bin/bash", stdout=lf, stderr=subprocess.STDOUT)`, sets `self.current_process`, and waits with `timeout=self.config["timeout_seconds"]`;
   - on `TimeoutExpired`: prints the same `[QUEUE] Timeout …` line, `kill()`, `wait()`, and uses exit `-1`. On any other exception: prints the same `[QUEUE] Error …` line and uses exit `-2`. Exit codes are unchanged;
   - writes a trailer on **every** path (`Finished:`, `Exit: <code>`, plus `(timeout after <n>s)` or `(error: <e>)` when applicable) and returns the code.
5. **The record names its log.** At spawn time, under the lock, set `self.current_batch["log_file"] = str(log_path)` (the dict built at `:340-343`). Add `"log_file": str(log_path)` to the entry at `:405-411`. In `cancel_current` (`:226-232`), copy `self.current_batch.get("log_file")` into the cancelled entry.
6. **`python3 -u`** in the command at `:378`. A file-backed stdout is block-buffered, and a `kill()` at timeout would drop the unflushed `print()` tail. The daemon itself already runs with `-u`. Change nothing else in the command.

### T3 · reachability: two non-test callers (D-S7CORE9-01)
1. **Post-route oracle.** In `run_loop`, straight after the entry is appended and before `_save_state()` (`:429-431`), call `check_gate_log_invariants([entry])` and `print(f"[QUEUE] ⛔ ORCH-STDOUT-1 invariant: {v}")` for each violation. It changes no state and no verdict. It is an oracle, the same pattern as `sit_verdict_violations`.
2. **`QueueDaemon.find_missing_gate_logs() -> list[GateLogViolation]`** returns the predicate over `self.completed + self.failed`. Add a CLI subcommand `check-logs` beside `check` (`:465-472`) that prints `FAIL <v>` for each violation and then `ORCH-STDOUT-1: <n> recorded route(s) without a readable log (<k> no-log-recorded, …)`, counted per reason. It exits `1` if `n > 0`. Report only. Update the usage line at `:474`. **Do not add it to `check`**: B6's exit semantics stay exactly as they are.

### T4 · tests (`tests/test_queue_gate_log.py`, new)
Drive the **real** `run_loop` for one batch. A fixture, modelled on `tests/test_queue_retire.py:411-425`, monkeypatches `QUEUE_DIR/QUEUE_DONE/QUEUE_FAILED/QUEUE_STATE/REPOS_CONFIG`, **`ORCH_DIR`** (a `tmp_path` dir holding a stdlib-only fake `orchestrator.py` that ignores its argv, writes what the test asks for, and exits with the test's code) and **`LOG_DIR`**. The fixture's `repos.yaml` names a repo whose `project_dir` is not a git repo (B6 then returns `[]`, as `canon_assert.py:505-510` guarantees) and whose `log_subdir` **differs from its name**. Set `cooldown_seconds = 0`. Monkeypatch `queue_daemon.time.sleep` to set `d.status = "stopped"`, which ends the loop at the first idle or paused sleep. **No test may import `orchestrator`**: its import writes `logs/orch-<ts>.log` into the real `logs/` (`orchestrator.py:511`).

Write the `run_loop`/`cancel_current` tests (AC-SO-03…06) FIRST and run them against unmodified `queue_daemon.py` to get the red (AC-SO-03). They assert on the entry and the file directly, and do not use the predicate, so they collect on unmodified code.

## 4 · OUT OF SCOPE

- **Gate semantics, verdict classification, F-20, SIT batching/isolation (GATE-SIT-2, shipped today), branch freshness/retirement (ORCH-STALEBASE-1, QUEUE-RETIRE-1, shipped today).** `orchestrator.py` is **not edited at all**. That includes its stale docstring citation `queue_daemon.py:325` at `orchestrator.py:1392`, which this change moves again. Report it in §7 and leave it.
- **Anything in clinical-mp.** Nothing outside this repo.
- **Successor brief, ORCH-GATELOG-2 (named, not done):** persist the **raw gate-runner output** (build, `npm run sit:gate` per batch and per isolation run, `npm test` branch and baseline) per route. Today it is `capture_output=True`, lives in memory, is summarised to `log` lines, and only SIT red tails reach the sit-log. The fix lives in `orchestrator.py`'s gate functions, not in the daemon. This brief makes the daemon's file the place such output would land if it were printed, but it does not print it.
- **Found, not fixed (successor candidate, needs an owner ruling):** `_load_state` does `self.config.update(data.get("config", {}))` (`queue_daemon.py:136`), and `queue-state.json` persists `"max_consecutive": 10`. So S7-CORE-11's raise to 25 (`:104-108`) is **dead while that file exists**, and the live daemon pauses at 10. `timeout_seconds` and every other config key behave the same way. Do not touch it here. Name it in §7.
- **Found, not fixed:** tests that import `orchestrator` write real `logs/orch-<ts>.log` files (the 115–185 KB `batch-orch10.md` ones). Hygiene, separate brief.
- **No retention or rotation** of the new per-route logs, and no migration or backfill of historic entries. Their output is gone. Say so; do not fabricate paths.
- **No change** to the `orch-dashboard.py` integration, the lock-wait loop (`:350-363`), exit-code meanings, `stop_on_failure`, or the capped list lengths.

## 5 · ACCEPTANCE

- **AC-SO-01 · the predicate.** `canon_assert.check_gate_log_invariants` and `GateLogViolation` exist where §2 puts them. Unit cases, one per reason (`no-log-recorded` for the key absent, `None` and `""`; `log-missing`; `log-not-a-file` for a directory; `log-unreadable` for `chmod 000`, skipped only if running as root; `log-empty`), each return exactly one violation with that reason. A good entry returns `[]`. An entry that fails two checks reports only the first in §2's order. **Set:** the entries each test constructs.
- **AC-SO-02 · red before green on the real record (log-absence half).** With T1 in place and T2 not yet in place, run the predicate read-only over `completed + failed` of the live `~/spectricom-orchestrator/queue-state.json`. At the time of writing that is **30 completed + 8 failed = 38 entries, 0 carrying `log_file`, so the expected red is 38 violations, all `no-log-recorded`**. The daemon is live, so state the N you measured and its breakdown. **Set:** exactly those two lists as read at that moment. Nothing is written.
- **AC-SO-03 · red before green in the tests, on unmodified `queue_daemon.py`.** The five tests of AC-SO-04/05/06 (the huge-output, marker, non-zero-exit, timeout and cancel cases) are run against unmodified `queue_daemon.py`. **Expected: 5 failed, 0 passed.** Four fail because the entry has no `log_file`. The huge-output one fails with `exit_code == -1` (timed out at the test's bound) instead of `0`: the deadlock, reproduced. State the observed count and each failure line. All 5 pass after T2.
- **AC-SO-04 · the deadlock is gone.** The fake child writes **≥ 320 KiB** (> 256 KiB, five times the 64 KiB pipe buffer) to stdout, plus a line to stderr, then exits 0. The test sets `timeout_seconds = 15`, so unmodified code fails in bounded time rather than hanging the suite. After T2 the entry is in `completed` with `exit_code == 0` and `duration_s < 15`. The log file is at least 320 KiB and contains the child's final stdout line and its stderr line.
- **AC-SO-05 · the log exists where the convention says, holding the child's output.** For a child that prints a unique stdout marker and a unique stderr marker, `entry["log_file"] == str(LOG_DIR / <log_subdir from the fixture yaml> / f"orch-{stem}-{ts}.log")`. `ts` matches `\d{8}-\d{6}`, and `<log_subdir>` is the configured value, not the repo name. The file contains both markers, a header naming the batch and the command, and a trailer `Exit: 0`. A second case with **no** `log_subdir` key lands under the repo name (the `orchestrator.py:166` rule). `check_gate_log_invariants([entry]) == []`. **Set:** the two markers the fake child wrote.
- **AC-SO-06 · every recording path names a readable log.** **Set:** the five ways `queue_daemon.py` appends an entry. These are exit 0 (`completed`), exit non-zero (`failed`, fake exits 3), timeout (`failed`, `-1`; the fake prints a marker, then sleeps past `timeout_seconds = 2`), spawn error (`failed`, `-2`; force `Popen` to raise), and `cancel_current` (`failed`, `-9`; a running `current_batch` with `log_file` set). For each, the entry carries `log_file`, `check_gate_log_invariants([entry]) == []`, and the trailer states the exit code. The timeout log also contains the marker printed before the kill.
- **AC-SO-07 · no pipe.** `queue_daemon.py` contains no occurrence of `subprocess.PIPE` (source-guard test). **Set:** `queue_daemon.py` only. Other modules' `PIPE`/`capture_output` uses are gate captures and out of scope (§4).
- **AC-SO-08 · reachability.** (a) A test patches `queue_daemon.check_gate_log_invariants`, drives one passing and one failing batch through `run_loop`, and asserts it was called with `[entry]` for each recorded entry. (b) `find_missing_gate_logs()`, the method `python3 queue_daemon.py check-logs` calls, returns the predicate over a `tmp_path` `queue-state.json` holding one good and one historic-shape entry: exactly one violation, `no-log-recorded`. The non-test callers are `run_loop` (T3.1) and the `check-logs` CLI (T3.2). The dashboard reaches `run_loop` through `start_daemon_thread` (`orch-dashboard.py:902`).
- **AC-SO-09 · the existing daemon tests are unchanged.** `tests/test_queue_retire.py` passes **with no edits to that file**. That includes the `run_loop` source guards at `:393` and `:471-473`. `git diff --stat` against the merge-base lists only `canon_assert.py`, `queue_daemon.py` and `tests/test_queue_gate_log.py`. **Set:** that diff.
- **AC-SO-10 · the gate: green, with no new failures against the merge-base baseline.** Run `pytest -q tests/` at the merge-base and on the branch, and state **both** counts. Expected baseline `454 passed, 0 failed` (reported at `23ab07f`, not re-measured by the brief author). Branch: `N passed, 0 failed` with `N = baseline + new tests`. **Set:** every test file under `tests/`, none excluded. The new file must not leave the suite slower by more than the AC-SO-06 timeout case's ~2 s. State its wall-clock.
- **AC-SO-11 · no test writes to the real `logs/`.** **Set:** files under `~/spectricom-orchestrator/logs/` whose mtime falls inside the new test file's run. List before and after and report zero new files.

## 6 · HANDBACK

**§7 first: what you found and LEFT, and why.** At minimum: the stale `orchestrator.py:1392` citation; the persisted-config override (`queue_daemon.py:136` makes `max_consecutive` 10, not 25); the test-import writes into `logs/`; the raw gate-runner output (ORCH-GATELOG-2); and anything else you met and did not touch.

Then report:
- **What shipped:** T1–T4 by function name and file:line.
- **The red counts:** AC-SO-02 (N and its breakdown) and AC-SO-03 (5, with each failure line).
- **The gate table:** merge-base `454 passed, 0 failed` (or what you measured) against the branch count.
- **AC-SO-08's two callers.**

Then **D-S7CORE13-03, the consequence**, stated plainly:

1. **A new file per route.** Every daemon-fired route now writes `logs/<log_subdir>/orch-<stem>-<ts>.log` beside `toni-<stem>-<ts>.log`. There is no rotation. State the size of the largest one your tests produced and the ~6 KB typical.
2. **`queue-state.json` entries gain `log_file`.** Entries recorded before the merge do not have it and never will.
3. **`check-logs` is red on the existing history by construction.** It will report every pre-change entry as `no-log-recorded` until they roll out of the capped lists: 30 completed routes for `completed`, and up to 15 new failures for `failed`. A `no-log-recorded` on an entry dated after the merge is a regression. Any other reason is a disk problem.
4. **The live daemon keeps the old code until restarted.** It runs now as `python3 -u queue_daemon.py`. Say whether it was restarted, and that the first route after the restart is where AC-SO-02's red turns green in production.
5. **Uncaught tracebacks from a crashing route now land in the route's log.** The next `exit_code: 1` in `failed` has a reason on disk. The 8 existing ones never will.
6. **`python3 -u`** changes when the child's `print()` output reaches the file (per line, not per block). Nothing else about the command changes.
7. **Open questions for the owner:**
   - The report says five routes ran through the daemon on 2026-09-27. `queue-state.json` records **four** dated that day (43, 44, 45, 46). Route 42 has `logs/orch-20260927-113718.log` and `logs/orchestrator/toni-42-…-113718.log` but no queue-state entry. Was it daemon-fired?
   - The report says no gate log existed and GATE-SIT-2 was unobservable. §1 shows the verdict lines and the isolation evidence **were** on disk. What went missing is the non-`log` output and the record→log link. Confirm that this correction matches what was looked for.
