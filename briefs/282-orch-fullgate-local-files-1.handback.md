# filename: briefs/282-orch-fullgate-local-files-1.handback.md

# 282 · ORCH-FULLGATE-LOCAL-FILES-1: handback

**The full gate's worktree now gets the repo's declared git-ignored SIT files (D1).** A new optional per-repo key, `full_gate_link_files:`, lists repo-relative paths. clinical-mp has `[".medplum-admin-credentials.local"]`. `full_gate` and its dry run symlink each listed path from the checkout into the detached worktree, right after `_link_unit_deps`. The links go into the same `links` list, so the same teardown removes them. The code checks only that a file exists and makes a symlink by path. It never opens the file, so no value can reach a log. With the key absent (or `[]`), the worktree's links are exactly what HEAD made.

**A listed file the checkout lacks is named before any batch runs (D2).** The SIT leg is BLOCKED and runs nothing, not even the enumeration. The unit leg still runs. The verdict detail is `full_gate_link_files: <path> not in <checkout>`. The dry run reports each listed file as present or MISSING.

**Each leg's verdict says what was linked (D3).** Both the SIT and the unit part of the 🌙 line end with `; local files linked k/n: <names>`, plus ` (not linked: <names>)` when some were not. A `🔗` log line says the same when the links are made. Each leg in `state/full-gate-<repo>.json` carries `local_files: {linked, not_linked}`.

On the real config, `full-gate --repo clinical-mp --dry-run` prints:
`local file .medplum-admin-credentials.local (full_gate_link_files): present in /home/gkassa/spectricom-clinical-mp — would be linked into the worktree` (P4). HEAD's code prints no such line from the same config.

Commit: `c7da3d5` (`orchestrator.py`, `config/repos.yaml`, new `tests/test_fullgate_local_files.py`). No per-merge code path changed.

## §0 As built (L-30)

### Predecessor
```
$ git log --oneline ccdf0c9..HEAD
5ceca0b docs(CLAUDE.md): test scope — executor runs targeted checks only; full suites belong to the gate (D-S7CORE30-05)
$ git diff ccdf0c9..HEAD --stat
 CLAUDE.md | 5 +++++
```
No named file was touched after `ccdf0c9`. Only CLAUDE.md changed, and its test-scope rule was followed (§3). All `:line` references below are at HEAD `5ceca0b`, which is identical to `ccdf0c9` for `orchestrator.py`, unless marked as at `c7da3d5`.

### Premises re-proven (no linked file read)
```
$ sed -n 15p ~/spectricom-clinical-mp/.gitignore
*.local
$ git -C ~/spectricom-clinical-mp check-ignore -v .medplum-admin-credentials.local
.gitignore:15:*.local	.medplum-admin-credentials.local
$ test -e ~/spectricom-clinical-mp/.medplum-admin-credentials.local && echo "credentials file: present (not read)"
credentials file: present (not read)
$ sed -n 30,40p ~/spectricom-clinical-mp/sit/integration/probe-identity.ts      # the source that reads it, not the file (excerpt)
function adminCredentials(): { email: string; password: string } {
  const email = process.env.ADMIN_EMAIL ?? 'dev-admin@spectricom.local';
  let password = process.env.ADMIN_PASSWORD;
  const file = resolve(__dirname, '../../.medplum-admin-credentials.local');
  if (!password && existsSync(file)) password = /^Password:\s*(\S+)/m.exec(readFileSync(file, 'utf8'))?.[1];
  if (!password) throw new Error('The SIT probe identity needs the project admin: set ADMIN_PASSWORD (see .medplum-admin-credentials.local).');
```
`resolve(__dirname, '../../…')` from `<wt>/sit/integration` is `<wt>/.medplum-admin-credentials.local`. A symlink at the worktree root is therefore what the probe reads.

```
$ python3 -c '…state/full-gate-clinical-mp.json…'          # ~/spectricom-orchestrator, read-only
{'sha': 'a4f0e184…', 'started_at': '2026-10-16T21:38:13', 'finished_at': '2026-10-16T22:12:50', 'outcome': 'BLOCKED', 'duration_s': 2077.4}
{'outcome': 'BLOCKED', 'signal': 'no-failed-assertions', 'batches': 12, 'duration_s': 1421.06, 'collection': '116 files/426 tests in 12 batches, 1421.1s', 'scope': 'full 116'}
{'outcome': 'PASS', 'collection': '1273 files/13038 tests, 4 failed, 13022 passed, 8 skipped, 4 todo', 'duration_s': 528.77}
sit detail: exit 1 with 0 failed assertions and 31 file(s) down at setup: sit/integration/assistant-escalation-honest.integration.test.ts, …
$ grep -n "probe\|setup\|admin" logs/clinical-mp/full-gate-20261016-213813.log | cut -c1-300      # excerpt, ANSI stripped here
45:ORD (see .medplum-admin-credentials.local).
46: ❯ adminCredentials sit/integration/probe-identity.ts:38:24
49:    38|   if (!password) throw new Error('The SIT probe identity needs the pro…
69:22:04:00 [INFO   ] 🔎 F-20 sit gate: signal 'no-failed-assertions' matched — 0 failed assertions, 31 file(s) down at setup: …
```
vitest's ANSI colouring splits the error sentence across lines 44-45, so a plain grep for the whole sentence returns 0. Every premise holds as Gemma stated it: `full_gate` `:4867`, `FULL_GATE_WORKTREE_PREFIX` `:394`, `_link_unit_deps(PROJECT_ROOT, wt)` `:4917` (dry run `:4831`), `UNIT_BASELINE_LINK_PATHS` `:362`, `_full_gate_sit` `:4684`.

### Find 1: every link into the full-gate worktree, and its teardown (HEAD)
- **`full_gate`:**
  - `links, state = [], {}` at `:4901`.
  - `links = _link_unit_deps(PROJECT_ROOT, wt)` at `:4917`, in the `else:` of `if add.returncode != 0:` (`:4913`), i.e. only when `git worktree add` succeeded.
  - Teardown is in the `finally:` block: `for d in links: d.unlink(missing_ok=True)` at `:4955`, then `worktree remove --force` (`:4957`), `worktree prune` (`:4958`) and `shutil.rmtree(td)` (`:4959`).
- **`_full_gate_dry_run`:**
  - A worktree is made only when the checkout is not clean at `<ref>`'s commit: `tempfile.TemporaryDirectory` at `:4827`. Otherwise it enumerates in the checkout and links nothing.
  - `links = _link_unit_deps(PROJECT_ROOT, wt) if add.returncode == 0 else []` at `:4831`.
  - Teardown is `for d in links: d.unlink` at `:4834`, then `worktree remove --force` (`:4836`) and `prune` (`:4838`).
- **Other `_link_unit_deps` callers, not touched:** the per-merge unit baseline (`:3163`, teardown `:3177`) and the parallel-worker gate worktree (`:1610`, teardown `:1618`).

### Find 2: how repos.yaml per-repo keys are read and validated (HEAD)
- `load_repo_config()` (`:124`) validates only three things: the file exists, it has a `repos:` map, and no entry has `default:`.
- `set_active_repo()` (`:145`) stores the entry dict as `ACTIVE_REPO_CONFIG` (`:174`).
- Optional keys are read where they are used, via `ACTIVE_REPO_CONFIG.get(<KEY constant>)`, and validated there.
- The optional list key copied here is `sit_core_files`:
  - `SIT_CORE_FILES_KEY` at `:263`;
  - read at `:2317-2318`: `… .get(KEY) or []`, a bare string becomes a one-item list, then `list(…)`;
  - a bad entry is reported and skipped at `:2320-2323`.
- `queue_daemon.py` reads its own `full_gate_nightly` (`:430`, `:439-455`). `repo_config.py` is the helper scripts' loader; the full gate does not use it.
- No key whitelist exists anywhere (`tests/test_config_truth.py` has none either). So the "config loader" is orchestrator.py's own `ACTIVE_REPO_CONFIG` pattern, and no loader file changed.

### Find 3: where the SIT leg's verdict line is built (HEAD)
- **Full gate:** `_full_gate_sit` (`:4684`) builds the leg dict (`outcome`/`signal`/`detail`). Its one existing pre-batch BLOCKED is `env-file-missing` (`:4689-4691`). `full_gate`'s nested `_leg()` (`:4947-4949`) renders `sit <outcome> (<collection|detail>)[; NEW: …]` into the 🌙 line (`:4950-4952`). The new code goes in these two places.
- **Per-merge, not touched:** `run_pre_merge_gates` (`:4429`) builds `GateVerdict(…, "sit", …)` (`:4496`, `:4502`, …) from `SitOutcome.collection` (`:2084` at `c7da3d5`).

## D1–D3 as built (`c7da3d5`)

| | Where | What |
|---|---|---|
| D1 key | `orchestrator.py:396-402` | `FULL_GATE_LINK_FILES_KEY = "full_gate_link_files"`, with the incident in the comment |
| D1 config | `config/repos.yaml:96-100` | clinical-mp: `full_gate_link_files: [".medplum-admin-credentials.local"]` (comment: never read; a missing one ⇒ SIT BLOCKED before any batch) |
| D1 link | `orchestrator.py:4715-4748` `_link_full_gate_files(src, dst)` | For each listed path: `(src/p).exists()`, then `d.symlink_to(s.resolve())`, as `_link_unit_deps` does. `dst=None` only checks. Returns `FullGateLocalFiles` (`:4691-4712`): `links` (for teardown), `linked`, `not_linked` `[(path, why)]`, `missing` |
| D1 full gate | `orchestrator.py:5012-5014` | `links = _link_unit_deps(…)`, then `local = _link_full_gate_files(PROJECT_ROOT, wt)`, then `links += local.links`. The HEAD `finally` teardown (`for d in links: d.unlink`) removes them |
| D1 dry run | `orchestrator.py:4913-4915` | In the dry run's worktree: `local = _link_full_gate_files(PROJECT_ROOT, wt)`, then `links += local.links`. Torn down by the HEAD loop (`:4918`) |
| D2 block | `orchestrator.py:4767-4771` (`_full_gate_sit`, after the env-file check) | `local.blocked` returns `{"ran": False, "outcome": "BLOCKED", "signal": "local-file-missing", "detail": "full_gate_link_files: <path> not in <checkout>"}`. Nothing runs, not even `vitest list` |
| D2 log | `orchestrator.py:5018-5022` | `⛔ full-gate <repo>: full_gate_link_files: <path> not in <checkout> — the SIT leg is BLOCKED before any batch; the unit leg runs` |
| D2 dry run | `orchestrator.py:4937-4947` | One line per listed file: `present in <checkout> — would be linked into the worktree`, or `MISSING — <path> not in <checkout>; a real run's SIT leg would be BLOCKED before any batch, the unit leg still runs` (dry-run exit 1, as for an enumeration failure) |
| D3 | `orchestrator.py:4751-4755` `_describe_local_files`; `:5016-5017` the `🔗` line; `:5027-5029` `local_files` on each leg; `:5056-5057` `_leg()` | `; local files linked k/n: <names>[ (not linked: <names>)]` on the SIT part and the unit part of the 🌙 line. Nothing is added when no file is listed |

The 🌙 line as built (from the P3 tests; tmp paths shortened):
```
🔗 full-gate cost-repo: full_gate_link_files — local files linked 2/2: .x.local, config/.z.local
🌙 full-gate cost-repo @ 98e728e (main): PASS — sit PASS (5 files/10 tests in 3 batches, 15.0s); local files linked 2/2: .x.local, config/.z.local | unit PASS (6 files/18 tests, 0 failed (derived), 18 passed); local files linked 2/2: .x.local, config/.z.local | 0s → …/full-gate-cost-repo.json
⛔ full-gate cost-repo: full_gate_link_files: .y.local not in <tmp>/project — the SIT leg is BLOCKED before any batch; the unit leg runs
🌙 full-gate cost-repo @ 98e728e (main): BLOCKED — sit BLOCKED (full_gate_link_files: .y.local not in <tmp>/project); local files linked 1/2: .x.local (not linked: .y.local) | unit PASS (6 files/18 tests, 0 failed (derived), 18 passed); local files linked 1/2: .x.local (not linked: .y.local) | 0s → …
```

**Choices made within D1/D2, stated so they can be overruled:**
- **More cases block, beyond "missing".** Any listed path that cannot be linked also BLOCKS the SIT leg before any batch, with the reason in the detail. The same `local-file-missing` signal is used for all of them:
  - an absolute path, or one containing `..` (`is not a repo-relative path`; never linked, so nothing escapes the worktree);
  - a path already in the worktree, i.e. tracked or under a linked tree (`… — not linked over`);
  - a symlink `OSError` (`could not be linked (<strerror>)`).
  Each has the same consequence as a missing file: every SIT file that needs it would fail at setup.
- **Value forms.**
  - A bare string becomes a one-item list (the `sit_core_files` pattern). `[]` counts as absent.
  - The outcome string is `BLOCKED`, the full gate's existing spelling of BLOCKED(environment) (`env-file-missing` and the `BLOCKED_ENV` branch use it too). That is what `outcome`, `qstat.sh` and `queue_daemon.py status` read.
- **When SIT is not gated** (no `"sit"` in PRE_MERGE_GATES), the files are still linked and named on both legs. An unlinked one is only a warning there, and the dry run does not set exit 1.

## Tests changed
- **No existing test was changed.** The pre-authorised rule-#8 change was not needed: no existing full-gate test asserts the exact set of links into the worktree.
- **New: `tests/test_fullgate_local_files.py`, 15 tests.**
  - It reuses `tests.test_gate_cost.FullGate`: a real project repo and a real detached worktree, with only the suite commands scripted.
  - A `LocalGate` subclass records the symlinks under each suite command's `cwd`, at the first `list`, `sit` and `unit` command.
  - Its fixture file holds a sentinel line, `Password: sentinel-282-never-logged`. P1 searches every log record, stdout/stderr, the full-gate log file and the state file, and finds the sentinel in none of them.

## §2 Predicates

`python3 -m pytest -q tests/test_fullgate_local_files.py`: **RED on HEAD `5ceca0b`: 11 failed, 4 passed** (the 4 that pass are the negative controls, which assert HEAD behaviour). **GREEN at `c7da3d5`: 15 passed.**

| Predicate | Test | RED at `5ceca0b` | GREEN |
|---|---|---|---|
| P1 linked, gone after, no content in any log | `TestP1Linked::test_a_listed_file_is_a_symlink_in_the_worktree_and_gone_after` | `AssertionError: every leg runs with it linked` (only `node_modules`) | ✅ `{node_modules, .x.local}` at list/sit/unit; worktree gone; target inode/size/mtime unchanged; sentinel in no log |
| P1 nested path | `…::test_a_nested_path_is_linked_at_its_place` | `config/.z.local` absent | ✅ |
| P1 dry-run worktree | `…::test_the_dry_run_worktree_links_it_beside_the_deps_and_removes_both` | `.x.local` absent at `list` | ✅ linked in the dry run's worktree, removed with it |
| P1 control | `…::test_negative_control_no_key_links_exactly_what_head_linked[key-absent / empty-list]` | ✅ passes (HEAD) | ✅ links `== {node_modules}` exactly; calls `list, batch×3, unit`; no `local_files`, no `🔗`, no "local file" in the 🌙 line |
| P2 SIT BLOCKED, 0 batches, unit runs | `TestP2Missing::test_sit_is_blocked_before_any_batch_naming_the_path_and_unit_runs` | `assert 0 == 1` (HEAD ran the suite and passed) | ✅ exit 1; SIT `ran False, BLOCKED, local-file-missing`, detail `full_gate_link_files: .x.local not in <repo>`; calls `== ["unit"]`; unit `PASS` |
| P2 one of two | `…::test_one_of_two_missing_links_the_other_and_names_only_the_missing` | `assert 0 == 1` | ✅ names only `.y.local`; `.x.local` linked for the unit leg |
| P2 not repo-relative | `…::test_a_path_that_is_not_repo_relative_…[/etc/hostname, ../outside.local]` | `assert 0 == 1` ×2 | ✅ nothing linked; SIT BLOCKED naming it |
| P2 dry run present / MISSING | `…::test_the_dry_run_says_present_or_missing_for_each` | `AssertionError: a real run's SIT leg would be BLOCKED` (exit 0, no line) | ✅ both lines; exit 1; nothing written |
| P2 controls | `…::test_negative_control_present_runs_every_batch`, `…::test_negative_control_the_dry_run_with_no_key_says_nothing_new` | ✅ pass (HEAD) | ✅ |
| P3 count + names on each leg | `TestP3VerdictLine::test_each_leg_names_the_count_and_the_names` | the 🌙 parts end at `15.0s)` | ✅ both parts end `; local files linked 2/2: .x.local, config/.z.local`; state `local_files` on both legs; `🔗` line |
| P3 missing counted | `…::test_a_missing_file_is_counted_and_named_on_both_legs` | `assert False` | ✅ `1/2: .x.local (not linked: .y.local)` on both; the `⛔` line |
| P3 zero | `…::test_none_linked_says_zero` | `assert 0 == 2` | ✅ `0/1 (not linked: .x.local)` twice |

### P4: live, read-only
GREEN at `c7da3d5`, on the real `config/repos.yaml`. The clinical-mp checkout is clean at `main` = `8e0c56fc`, so the dry run enumerated in the checkout. No worktree was made and nothing was linked; the file was checked for existence only.
```
$ time python3 orchestrator.py full-gate --repo clinical-mp --dry-run; echo "exit=$?"
full-gate --dry-run clinical-mp @ main = 8e0c56fc8e39 (content key 0015d54a81f27a06140c6d6e72c6c1ba)
  lock: free — a real run would start now
  SIT: sit[full 116 files] — 116 files / 427 tests enumerated in the project checkout /home/gkassa/spectricom-clinical-mp (clean, at 8e0c56f); 12 batches of ≤10, 90s pause between, 600s per batch
  local file .medplum-admin-credentials.local (full_gate_link_files): present in /home/gkassa/spectricom-clinical-mp — would be linked into the worktree
  unit: `npm test` — the full suite, budget 1800s; baseline: no content-keyed entry — the nearest measured ancestor, else the previous full-gate
  writes: /tmp/orch-fire-20261017-124009/logs/clinical-mp/full-gate-<ts>.log, /tmp/orch-fire-20261017-124009/state/full-gate-clinical-mp.json — nothing run, nothing written (--dry-run)
real	2m36.153s
exit=0
```
RED: HEAD's code, from a `git archive HEAD` export into `/tmp/orch-282-head-*` with the same `config/repos.yaml` copied in (key present, code absent), printed the same plan without the `local file` line, exit 0. The export was removed afterwards.
```
$ grep -c full_gate_link_files config/repos.yaml orchestrator.py
config/repos.yaml:1
orchestrator.py:0
$ python3 orchestrator.py full-gate --repo clinical-mp --dry-run
full-gate --dry-run clinical-mp @ main = 8e0c56fc8e39 (content key 0015d54a81f27a06140c6d6e72c6c1ba)
  lock: free — a real run would start now
  SIT: sit[full 116 files] — 116 files / 427 tests enumerated in the project checkout /home/gkassa/spectricom-clinical-mp (clean, at 8e0c56f); 12 batches of ≤10, 90s pause between, 600s per batch
  unit: `npm test` — the full suite, budget 1800s; baseline: no content-keyed entry — the nearest measured ancestor, else the previous full-gate
  writes: /tmp/orch-282-head-Gfnt/logs/clinical-mp/full-gate-<ts>.log, /tmp/orch-282-head-Gfnt/state/full-gate-clinical-mp.json — nothing run, nothing written (--dry-run)
exit=0
```
The suite has moved since the 10-16 run: 116 files / 427 tests at `8e0c56f`, against 426 tests at `a4f0e18`.

## §3 Gates

| Gate | Result |
|---|---|
| Targeted: `tests/test_fullgate_local_files.py` | RED 11 failed / 4 passed at `5ceca0b`; GREEN **15 passed** |
| Targeted, the full-gate tests and every test that reads the shipped `config/repos.yaml`: `test_fullgate_local_files.py test_gate_cost.py test_yorsie_safety.py test_capacity.py test_admission_parser.py test_isolated_deps.py` | **254 passed** in 19.6 s |
| Targeted, the per-merge `_link_unit_deps` callers and the config-loading lanes, to show per-merge behaviour is unchanged: `test_unit_baseline_gate.py test_control_scope.py test_orch_lane.py` | **328 passed** in 23.7 s |
| Full `pytest -q tests/` | **Not run** (brief §6, CLAUDE.md test scope, D-S7CORE30-05). The orchestrator's pre-merge gate runs it after this executor exits |
| Lint | `pyflakes` is not installed here. `pytest` imported and ran every changed module |
| Live systems | The daemon was not signalled or restarted, and no live `full-gate` was run. In `~/spectricom-orchestrator`, only `state/full-gate-clinical-mp.json`, `logs/clinical-mp/full-gate-20261016-213813.log` and `sit-archive/gate-durations.json` were read. In clinical-mp, only git, `.gitignore`, `probe-identity.ts` and (by the two dry runs) `npx vitest list` in the checkout. **`.medplum-admin-credentials.local` was never opened, printed or copied**: only `test -e`, `git check-ignore`, and `Path.exists()` in the dry run |

## §1 Found and LEFT

1. **The `sit-batch` clock history is made mostly of batches that failed at setup.**
   - What the history holds: clinical-mp's `sit-batch` history (`sit-archive/gate-durations.json`, read-only) has 20 samples, median **17.6 s**. 11 of them are the 10-16 full gate's own batches, which failed at setup: 21:45-22:04, 6.9-75.5 s. Its 12th batch, the 145 s one, was implausible and so was not recorded. The other 9 are an earlier series, 18:04-18:18 at 4.2-34.3 s, which I did not trace.
   - Why it matters: the 10-16 run's SIT `clock` already reads `sit-batch outlier-vs-history: Δwall 145.0s > 5 × median 17.6s`. With the credentials linked, real batches will likely run longer than 88 s (5 × 17.6). An implausible sample is never written to the history (`GATE_DURATIONS_*`, GATE-CLOCK-1), so the median may not recover by itself.
   - The consequence for verdicts:
     - A **green** full-gate SIT is still PASS: `_full_gate_sit` checks `so.passed` first, and only records the clock.
     - A **red** one would be classified with `clock=` an outlier, so it may read BLOCKED(clock-implausible) instead of FAIL(product).
     - The per-merge leg uses `sit-batch` only when it falls back to the full suite.
   - Left alone: GATE-CLOCK-1 is a verdict rule this brief forbids changing. **Gemma's call:** watch the first linked run's SIT `clock`, and if needed clear the polluted `sit-batch` samples from `gate-durations.json` (a data edit, not code).
2. **The dry run's `lock:` and `writes:` resolve against the running script's own `ORCH_DIR`.** Run from a fire worktree (as P4 was), it reads that worktree's `state/`. So `lock: free` there says nothing about the live daemon's lock. From `~/spectricom-orchestrator`, which is where the daemon and the operator run it, it is correct. Not changed: it is outside D1-D3.
3. **The 10-16 unit leg passed with 4 failures**, all in the baseline. That is unrelated to this brief, so it was not looked into.

## THE CONSEQUENCE (D-S7CORE13-03)

1. **After the merge.**
   - **No daemon restart is needed.** The daemon's nightly step starts a fresh `cd ~/spectricom-orchestrator && python3 -u orchestrator.py full-gate --repo clinical-mp --trigger nightly` (`queue_daemon.py:1330`, `subprocess.Popen` `:1343`). So the next 02:30 run loads the new `orchestrator.py` and `config/repos.yaml`. The daemon itself does not read `full_gate_link_files`.
   - **The first linked nightly** links `.medplum-admin-credentials.local` into its worktree and logs `🔗 full-gate clinical-mp: full_gate_link_files — local files linked 1/1: .medplum-admin-credentials.local`. Its 🌙 line then shows `; local files linked 1/1: .medplum-admin-credentials.local` on both legs.
   - The 31 SIT files that failed at setup on 10-16 now get the probe identity. Whether they pass is the suite's own verdict; see §1.1 for how a red one could read.
   - **If the file is ever missing** from the checkout, the SIT leg is BLOCKED within seconds, naming it, and the unit leg still runs. On 10-16 the same discovery took 1421 s.
2. **Unchanged:**
   - every per-merge gate verdict and code path: `run_pre_merge_gates`, `_link_unit_deps` and its two per-merge callers, per-merge SIT, which runs in the checkout;
   - every verdict rule (F-20, GATE-SIT-2, GATE-CLOCK-1, BASELINE-TRUST-1);
   - the CODE-GUARD, the handback guard, prefire, admission, the fire lock, timeout/hold;
   - `queue_daemon.py`'s pause/resume semantics.
   A repo with no `full_gate_link_files` gets exactly HEAD's links and HEAD's verdict line.

## Closes capability advancement: none
## Gates journey: none
