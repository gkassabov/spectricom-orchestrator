## STATUS: DONE

# ORCH-PREFIRE-DRYRUN-GATE-1 (Kanban 727) — handback

Route branch `orch-orch-00000727-prefire-dryrun-gate-1`, base `2e062f5` (HEAD at start: `2e062f5046b7be0cf2bd1250b644b77c6f00bbe8`). One commit. The saved r2 patch was applied as is, with no edits beyond it.

## X0 · worktree
```
$ python3 -c "import prefire, queue_daemon; print(prefire.__file__, queue_daemon.__file__)"
/tmp/orch-fire-20261117-042327/prefire.py /tmp/orch-fire-20261117-042327/queue_daemon.py
```
Both modules load from inside the meta-fire worktree, so STOP (e) does not apply.

## A0 · re-read at the base (2e062f5)
1. `prefire.py:1092` `def check(filepath: Path) -> list[str]:`. `git grep -n "DRY RUN\|sha256\|_eos" HEAD -- prefire.py` returned no hits.
2. `prefire.py:1191` `def report(filepath, timeout=None) -> bool:`. It is called at `orchestrator.py:7484` (`prefire.report(batch_file, …)`), inside `approval_gate` (`orchestrator.py:808`).
3. `queue_daemon.py:910` `def enqueue(self, batch_path):` has no check. The enqueue branch of `main` is at `queue_daemon.py:1936-1938`: it prints the JSON and falls through, returning 0 even when `ok` is false.
4. `HEADER_WINDOWS` is at `prefire.py:1057`, before `header_window_problems` at `prefire.py:1069`.
5. Template lines (Toni template v1-5 `:223-232`, `:264-271`, `:240-243`): this file is canon, not in the repo, so I did not re-read it. The checks rely on the block shape that the D-5 heading pin asserts.

## Handback step 1 · patch
```
$ sha256sum ~/_eos/s7core55/briefs/_work/727/prefire-dryrun-gate-1-r2.patch
e1f8bea3e82709c4465720b9803905d0667d5ccff170d1f5d099dd8105ead75c  (matches)
$ git apply --check …   → clean
$ git apply --3way …    → Applied patch to 'config/repos.yaml' / 'prefire.py' / 'queue_daemon.py' cleanly; exit 0
$ git diff --cached --stat
 config/repos.yaml                 |   5 +
 prefire.py                        | 299 +++++++++++++++++++++++++++++++++
 queue_daemon.py                   |   9 +-
 tests/test_prefire_dryrun_gate.py | 345 ++++++++++++++++++++++++++++++++++++++
 4 files changed, 657 insertions(+), 1 deletion(-)
```
## Handback step 2
No edits beyond the patch. Every changed file is in ALLOWED FILES. The `queue_daemon.py` hunks touch only `enqueue` and the `enqueue` branch of `main`.

## Handback step 3 · gates
- `python3 -m py_compile prefire.py queue_daemon.py`: exit 0.
- `python3 -c "import yaml; yaml.safe_load(open('config/repos.yaml'))"`: exit 0, and `prefire_dryrun` reads `required`.
- The targeted pytest set (the 11 files the brief names): **738 passed, 1 skipped, exit 0, 19.5 s**. The skip is `tests/test_prefire_obs_paths.py:159` ("the route's own brief is not in this tree"), the same skip the DRY RUN shows.
- Not run: the full `pytest tests/` (the gate's unit leg runs it). tsc and build are n/a.

## A3 · predicates (`tests/test_prefire_dryrun_gate.py`): 59 passed in 0.60 s
| group | cases | result |
|---|---|---|
| D-1 DRY | 16 | 16 passed |
| D-2 enqueue | 6 | 6 passed |
| D-3 VERIFY | 17 | 17 passed |
| D-4 INPUTS | 18 | 18 passed |
| D-5 live config + heading | 2 | 2 passed |

Red at the base: I did not re-measure this here. The author measured 59 errors on a pristine `git archive 2e062f5` (`_work/727/base-red.txt`); the fixture reads `prefire.DRYRUN_ENV`, which does not exist at the base.

## RULE #8 · searches re-run at the base, every hit named
- `git grep -n -E "def enqueue|\.enqueue\(|\"enqueue\"" -- tests/` returned 2 hits, `tests/test_executor_default.py:309` and `tests/test_queue_pause.py:174`. Both are in the targeted set and green.
- `git grep -n -E "prefire\.check\(|prefire\.report\(|== \[\]" -- tests/test_prefire*.py tests/test_opex_prefire.py tests/test_control_scope.py tests/test_crash_prefire_h3.py` returned 91 hits:

  | file | hits |
  |---|---|
  | `test_prefire.py` | 33 |
  | `test_prefire_parse_hazards.py` | 23 |
  | `test_opex_prefire.py` | 18 |
  | `test_control_scope.py` | 13 |
  | `test_prefire_obs_paths.py` | 2 |
  | `test_crash_prefire_h3.py` | 1 |
  | `test_prefire_typed_go.py` | 1 |

  Every file is in the targeted set and green, and no assertion changed.
- `git grep -n "HEADER_WINDOWS" -- tests/` returned no hits.
- `git grep -n "prefire_dryrun\|DRY RUN (pasted)" -- tests/` returned no hits at the base.
- Branch guards, run by node id on the committed branch, **2 passed**:
  - `tests/test_unit_baseline_gate.py::TestTheSuiteCommandIsNotNarrowed::test_no_repo_test_cmd_changed_on_this_branch` (`:1031`)
  - `tests/test_unit_baseline_gate.py::TestOrch8ChangedNoVerdictSemantics::test_ac_o8_10_no_timeout_pool_or_parallelism_knob_moved_on_this_branch` (`:1594`)
- Harness edits: none. Grants used: none. Reds outside a grant: none.

## Extra (read-only)
I ran the patched `prefire.dry_run_problems` and `prefire.named_input_problems` on this brief. Both returned `[]`.

## Notes
- No daemon restart is needed. The next fire's `orchestrator.py run` and every `enqueue` are fresh processes.
- From the first fire after merge, a READY brief with no `## DRY RUN (pasted)` block is refused, for example `0000626b-regate-agent-write-gate-1b.md` if it is re-queued.
- Kanban 727 closes per the brief: the first post-merge fire logs `DRY ✅`, and Gemma confirms one refused enqueue on a scratch copy.
- OPEN-1 and the Gemma follow-ups are unchanged and are not this route's work.
