# filename: briefs/283-orch-prefire-test-scope-1.handback.md

# 283 · ORCH-PREFIRE-TEST-SCOPE-1: handback

**STOP (b) hit, on one clause only. A10's bare-`pytest` clause is built and tested, but it ships OFF (`A10_BARE_PYTEST = False`, `prefire.py:198`).** When on, it refuses **`queue/286-minig-documents-whole-kb-1.md` at line 48**: "Gates: `pytest` on the changed/new test files only; `python -m compileall src` clean." That line has a bare `pytest`, no path and no negation. 286 is queued now (and an identical copy sits in `held/`). The daemon runs one batch at a time and 283 is the current one, so 286 would have been refused at its next fire. To turn the clause on: reword 286:48 (for example "`pytest <changed/new test files>` only", which passes) or let 286 fire, then flip the constant. That flip is a one-line change and needs an instruction. With the clause on, the only brief now in `queue/` it refuses is 286 (see §2 P3).

**Everything else is in, at `2d38cf5`:**
- **A9** (D1): every brief must carry exactly one `## Test scope:` header line, either `targeted (D-S7CORE30-05)` or `full — D-S7CORE<n>-<n>`.
- **A10** (D2): a targeted brief may not tell the executor to run `npm test` (unless given ` -- <path or pattern>`), `sit:gate`, or a merge-base baseline, unless the same line negates it.
- **D3**: the report pass line says `A1/A2/A8/A9/A10 pass`.
- **D4**: Gemma's existing `CLAUDE.md` section is left as it was.

A1/A2/A8 are unchanged: their verdicts match HEAD on all 239 `done/` briefs and all 35 `queue/`, `held/` and `failed/` briefs. **No daemon restart is needed.**

**Incident during the RED run (§4, cleaned up):** my first reachability test called the real `run_batch`. Against HEAD's prefire it fired a real nested executor, and that executor started two more. None committed, merged or changed the live daemon. The test is now stubbed so it cannot fire.

Commit `2d38cf5`: `prefire.py` and four test files. `CLAUDE.md` is not changed.

## §0 As built (L-30)

### Predecessor
```
$ git log --oneline ccdf0c9..HEAD -- prefire.py tests/test_prefire.py queue_daemon.py CLAUDE.md
5ceca0b docs(CLAUDE.md): test scope — executor runs targeted checks only; full suites belong to the gate (D-S7CORE30-05)
$ git log --oneline ccdf0c9..HEAD | wc -l        # 7 commits; the others touch orchestrator.py, repos.yaml, other tests
7
```
`prefire.py`, `tests/test_prefire.py` and `queue_daemon.py` are unchanged since `ccdf0c9`. `CLAUDE.md` changed in `5ceca0b` (see D4). The premises hold at HEAD `1b6d98e`:
```
$ git show HEAD:prefire.py | grep -n "^def check_kanban\|^def parse_declared_runtime\|^def find_skip_sit\|^def check(\|^def report\|A1/A2/A8 pass"
81:def parse_declared_runtime(filepath: Path) -> Optional[tuple[int, int]]:
152:def find_skip_sit(filepath: Path) -> list[str]:
239:def check_kanban(filepath: Path) -> tuple[Optional[str], str]:
275:def check(filepath: Path) -> list[str]:
336:def report(filepath: Path, timeout: Optional[tuple[int, str, int]] = None) -> bool:
348:        print("  Assertions: ✅ A1/A2/A8 pass — %s; %s; %s" % (row, detail, _timeout_detail(filepath, timeout)))
```

### Find 1: where `check` runs, at fire and at enqueue
```
$ grep -n "prefire\.\(check\|report\)\|import prefire" orchestrator.py queue_daemon.py admission.py
admission.py:45:import prefire   # [ORCH-ADMISSION-PARSER-1] D1: the runtime line's one parser (stdlib, yaml, canon_assert; no log)
orchestrator.py:41:import prefire  # HOOK-1: pre-fire assertions (SESSION-BOOT A1/A2/A8)
orchestrator.py:5189:    if not PREFIRE_BYPASS and not prefire.report(batch_file, timeout=prefire_timeout(batch_file)):
$ grep -c prefire queue_daemon.py
0
$ grep -n "def enqueue\|shutil.copy2(str(src), str(dst))\|python3 -u orchestrator.py run {next_batch}" queue_daemon.py
665:    def enqueue(self, batch_path):
673:        shutil.copy2(str(src), str(dst))
1217:                f"python3 -u orchestrator.py run {next_batch} --approve "
```
- **There is one path, not two.** `check` runs only through `report`, and `report` is the first statement of `run_batch` (`orchestrator.py:5189`).
- **`queue_daemon.py enqueue` checks nothing.** It copies the file (`:665-675`) and calls no prefire function today, so A1/A2/A8 are not applied at enqueue either.
- **A9/A10 therefore apply exactly where A1/A2/A8 do: at the fire.** They live inside `check()`.
- **Adding them at enqueue would mean changing `queue_daemon.py`,** which §2 does not allow, so I left it (§1 item 1).
- **`admission.py` uses prefire only for the runtime timeout** (`prefire.runtime_timeout`, `:315`).

**No daemon restart.** Each fire runs `cd {ORCH_DIR} && … python3 -u orchestrator.py run <brief> --approve …` as a new process (`queue_daemon.py:1214-1218`). That process imports prefire fresh (`orchestrator.py:41`), so the first fire after the merge judges A9/A10.

### Find 2: how prefire knows the brief's repo
It does not read it. `#!queue repo=` is parsed by `canon_assert.queue_header` (`canon_assert.py:544`), which the daemon (`_parse_batch_header`) and the trunk invariant use. prefire imports only `disk_family` from `canon_assert` (`prefire.py:50`). D1 says *every* brief, so no repo or docs-only exemption was needed or built.

### Find 3: the A8 tests to mirror
At HEAD, `tests/test_prefire.py:86-98` has `test_skip_sit_invocation_blocks` (an invocation is refused) and `test_negated_skip_sit_mention_allowed` (a negated mention passes). `tests/test_control_scope.py:395` has `test_negative_control_a2_and_a8_still_report_beside_a1`. The A9/A10 tests follow the same shape: refused / negated or allowed / reported beside the others.

### Live queue at the time of building (read-only)
```
$ ls ~/spectricom-orchestrator/queue/*.md        # re-checked just before commit
282c-small-fixes-13.md   (queued 14:57, during this route)
283-orch-prefire-test-scope-1.md
286-minig-documents-whole-kb-1.md
$ state/queue-state.json current_batch.file = 283-orch-prefire-test-scope-1.md   # one batch at a time
```

## D1–D4 as built (`2d38cf5`)

- **D1 · A9** (`prefire.py:179-182`, `parse_test_scope` `:213`, wired in `check` `:395-397`)
  - **What it reads:** `## Test scope:` lines (colon required) in the header window, the same `_HEADER_CHARS` 6000 that A1 and A2 read.
  - **What counts as one valid header:** exactly one such line, whose text full-matches `targeted\s*\(D-S7CORE30-05\)` or `full\s*[—–-]\s*D-S7CORE\d+-\d+`.
  - **No line:** the refusal is exactly D1's text: `A9 TEST-SCOPE — the brief does not declare its test scope (`## Test scope: targeted (D-S7CORE30-05)`)`.
  - **Malformed, or more than one:** the same text, then `; '<line>' is neither that nor `full — <D-S7COREnn-nn>`` or `; 2 '## Test scope:' lines, exactly one: … | …`.
  - **Reading choices:**
    - Text after a valid ruling id is refused (`full — D-S7CORE30-99 because George said`).
    - Em dash, en dash and hyphen are all accepted, as the runtime parse also does.
    - This repo's `CLAUDE.md` heading `## Test scope — no duplicate regression runs (…)` has no colon, so it is not a header line.
- **D2 · A10** (`_A10_NEGATION` `:187`, `_A10_SUITES` `:188-194`, `_bare_pytest` `:202`, `find_full_suite_instructions` `:231`, wired `:398-406`)
  - **When it runs:** only when A9 found `targeted`. A brief with no scope gets A9's refusal alone; a `full` brief skips A10.
  - **What it scans:** every line of the file, as A8 does, fenced code included.
  - **What a line must contain to be refused:**
    - `npm test` or `npm run test` (not `test:unit`) not followed by ` -- ` and a non-flag argument. `npm test -- --run` is refused.
    - `sit:gate`.
    - `merge-base baseline`.
    - A bare `pytest`, but only when `A10_BARE_PYTEST` is on.
  - **The negation escape:** the line passes if it also contains `do not`, `don't` / `don’t`, `never` or `not run`, case-insensitive, anywhere on the line. A8's negation is narrower: it must appear before the flag.
  - **The refusal** names each line as `line N: <text≤160>`, the first three joined by ` | ` like A8, then ` (+k more)`.
  - **Bare `pytest`:** the first non-flag word after `pytest`, up to the code span's closing backtick (or the end of the line), must contain `/`, `.py` or `::`, or start with `<`. `pytest.ini`, `pytest-xdist` and `_pytest` are not commands.
  - **"merge-base baseline (as a thing to run)":** a plain match plus the negation escape. In the corpus, every non-negated mention is an instruction to measure one:
    - `done/110:49` "unit failures ≤ merge-base baseline"
    - `done/108:53` "failures ≤ merge-base baseline (record the baseline count first)"
    - `done/57:142` "no new failures against the merge-base baseline. Run `pytest -q tests/` at the merge-base…"
- **D3 · report** (`:438-439`)
  - **Pass:** `  Assertions: ✅ A1/A2/A8/A9/A10 pass — <row>; <estimate>; <timeout>` (HEAD's line, with only the list changed), then a second line, `  Test scope: <targeted (D-S7CORE30-05) | full — D-…>`.
  - **Why a second line:** `tests/test_runtime_parse.py:148` pins that the pass line ends at the timeout, and that test is not pre-authorised.
  - **Refusals:** listed as `  • A9 …` / `  • A10 …` bullets, like A8's.
  - **Not changed:** `orchestrator.py:5195`'s error string still reads `(A1/A2/A8)`, because `orchestrator.py` is outside §2 (§1 item 2).
- **D4 · CLAUDE.md: already there, left unchanged.**
  - `git log -p CLAUDE.md` shows `5ceca0b` (George, 10:59, via `~/_eos/s7core30/testscope.py`) added `CLAUDE.md:46-47`, "Test scope — no duplicate regression runs".
  - It says: run only typecheck/build, lint on changed files, tests related to the changed files, and your own new or changed SIT tests alone; never a full suite or a baseline (bare `npm test`, `npm run sit:gate`, a merge-base baseline, bare `pytest`); the pre-merge gate, nightly and pre-tester runs cover them; and a `## Test scope: full — <George decision>` header is the only exception.
  - That covers D4. `pytest <changed paths>` is not named literally, but it falls under "tests related to the files you changed".
- **Module docstring:** A9 and A10 are listed under ENFORCED (`:28-34`). "NOT enforced here" now says SESSION-BOOT's own A9 (System Prompt v5-38) is a different assertion from this A9 (`:36`; §1 item 6).

## Tests changed

Pre-authorised (rule #8): only the A9 header added, or the report text changed. Each one:
1. `tests/test_prefire.py:11` `SCOPE_LINE`, and `w()` `:28` writes it. These are the fixtures of the 12 A2/A8 tests, so they keep judging A2/A8 alone.
2. `tests/test_control_scope.py:342-343` `_brief()`: header added. These are TestP3Kanban's fixtures (A1).
3. `tests/test_control_scope.py:398-399` `test_negative_control_a2_and_a8_still_report_beside_a1`: header added. It still asserts exactly one failure, A2 SIZING.
4. `tests/test_control_scope.py:405` `test_report_names_the_row_it_passed`: `A1/A2/A8 pass` becomes `A1/A2/A8/A9/A10 pass`.
5. `tests/test_orch_lane.py:591-592` `_kbrief()`: header added. These are TestP4KanbanFamilies' fixtures (A1).
6. `tests/test_runtime_parse.py:30` `SCOPE_LINE`, and `brief()` `:49` writes it. These are the A2/timeout fixtures.
7. `tests/test_runtime_parse.py:137`: `✅ A1/A2/A8 pass` becomes `✅ A1/A2/A8/A9/A10 pass`.

No assertion was loosened. Without items 1-7, the same targeted run had 32 failures, every one an extra A9 refusal on a header-less fixture or the old report text.

**New:** 57 tests in `tests/test_prefire.py:101-290`. P1 is A9; P2 is A10, including the staged clause, which the tests monkeypatch on and off; D3 is the report, plus reachability through `orchestrator.run_batch`.

## §2 Predicates

`python3 -m pytest -q -p no:cacheprovider tests/test_prefire.py`:
- **RED** with HEAD `1b6d98e`'s `prefire.py` in place: **37 failed, 32 passed** in 0.49 s.
  - The 32 that pass are the 12 existing A2/A8 tests and 20 new negative controls that pass on both sides: `targeted` passes; `full` with 3 dash forms passes; 10 allowed lines; 6 suite lines under `full`.
  - 7 clause-on controls (the 6 `PYTEST_WITH_PATH` lines and `test_P2_full_scope_lets_a_bare_pytest_pass`) are among the 37 failures only because `A10_BARE_PYTEST` does not exist at HEAD.
- **GREEN** at `2d38cf5`: **69 passed** in 0.28 s.

| Predicate | Test (`tests/test_prefire.py`) | RED (HEAD) | GREEN |
|---|---|---|---|
| P1 no header → A9, exact text | `test_P1_no_test_scope_header_is_refused` | `[] == [A9 …]` | ✅ |
| P1 `targeted` passes | `test_P1_targeted_passes` | ✅ (control) | ✅ |
| P1 `full — D-S7CORE30-99` passes A9 | `test_P1_full_naming_a_george_decision_passes_a9[—,–,-]` | ✅ (control) | ✅ |
| P1 `full — because` → refused, named | `test_P1_a_malformed_test_scope_is_refused_and_named[9 shapes]` | ×9 | ✅ `…; '## Test scope: full — because' is neither …` |
| P1 both / duplicate → refused | `test_P1_more_than_one_test_scope_line_is_refused[3]` | ×3 | ✅ `…; 2 '## Test scope:' lines, exactly one: …` |
| P1 controls | `…_the_claude_md_section_heading_is_not_a_header_line`, `…_a2_and_a8_still_report_beside_a9` | ×2 | ✅ `["A2","A8","A9"]` |
| P2 `Run `npm test` before the final commit.` → refused, line named | `test_P2_a_targeted_brief_that_instructs_a_full_suite_is_refused_naming_the_line[6]` (also `npm run sit:gate`, `sit:gate`, `npm run test`, `npm test -- --run`, done/112's merge-base line) | ×6 | ✅ `… Offending line(s): line 4: Run `npm test` before the final commit.` |
| P2 `**Do NOT run the full `npm test`** …`, `npm test -- src/x.test.ts`, `pytest tests/test_prefire.py` pass | `test_P2_a_negated_or_targeted_command_passes[10]` | ✅ (control) | ✅ |
| P2 `full — D-S7CORE30-99` lets the same lines pass | `test_P2_full_scope_lets_the_same_lines_pass[6]` | ✅ (control) | ✅ |
| P2 `pytest -q` → refused (clause on); 286:48 and 282br:25 shapes refused (on), pass (off) | `test_P2_a_bare_pytest_is_refused_when_its_clause_is_on[4]` | ×4 | ✅ |
| P2 `pytest tests/test_prefire.py`, `<changed paths>`, `::node`, negated, `pytest.ini` pass (clause on) | `test_P2_pytest_with_a_path_or_negated_passes_with_its_clause_on[6]`, `…full_scope_lets_a_bare_pytest_pass` | ×7 (no attribute) | ✅ |
| A10 only on targeted; >3 lines counted | `test_P2_a10_is_not_judged_without_a_scope`, `test_P2_every_offending_line_is_counted` | ×2 | ✅ `… (+2 more)` |
| D3 pass line + scope line; refusals as bullets | `test_D3_report_names_…`, `test_D3_report_lists_…` | ×2 | ✅ |
| D3 reachability: the fire refuses | `test_D3_the_fire_refuses_a_brief_with_no_test_scope` | fails in 0.20 s: `prefire cleared a brief with no test scope; run_batch stopped before firing` (HEAD printed `✅ A1/A2/A8 pass …`) | ✅ `Status.FAILED, exit 2, 0 briefs`, `  • A9 …` |

### P3: no regression on old briefs (read-only, live `~/spectricom-orchestrator/queue`)
I loaded HEAD's `prefire.py` and this tree's side by side, both reading the live canon through this tree's `config/repos.yaml`. A1/A2/A8 means "this tree's verdicts minus the A9/A10 lines".
```
done/: 239 briefs; A1/A2/A8 identical to HEAD on 239, differ on 0      (run twice, both 0)
queue/: 3 · held/: 10 · failed/: 22 — A1/A2/A8 identical to HEAD on all 35

from 279b onward (done/, by mtime)               HEAD       A9/A10 add (clause off)   (clause on)
  279b-small-fixes-12.md                          A1         A9 (no header)            A9
  279-sr-drk-session-fixes-1-regate.md            A1         A9                        A9
  282-orch-fullgate-local-files-1.md              A1         A9                        A9
  281r-drk-path-2-regate.md                       A1         nothing                   nothing
  282br-orch-sit-isolation-attributed-1-regate.md A1         nothing                   A10 line 25 (`python3 -m pytest -q` on the test files…)
```
- **One first-pass difference, not reproduced.** My first done/ pass reported `104-orch-control-scope-1.md` as differing on A1/A2/A8. I re-ran it alone: identical (`A1 KANBAN — SCP_Kanban row 145 is MERGED` on both sides). The likely cause is that `SCP_Kanban_v0-314.md` landed in the canon at 14:57:07, during that pass; A1 reads the newest file from disk on every call. Two complete re-runs gave 0 differences.
- **queue/ (fireable):**
  - `282c` and `283`: pass, with the clause off and on.
  - `286`: passes with the clause off; refused at line 48 with it on (STOP b).
- **held/:**
  - 117, 121, 259, 242b, 243, 244, 246, 247: gain A9. HEAD already refuses each at A1 (row not READY).
  - 284: adds nothing.
  - 286: identical to the queued copy.
- **failed/:**
  - All 21 header-less briefs gain A9, and HEAD already refuses each at A1.
  - `282b`: HEAD passes it; with the clause on it gains A10 at `:39`. Its work merged through 282br.

### P4: live, read-only
```
$ python3 prefire.py ~/_eos/s7core30/stage/284-journey-owner-vance-1.md; echo "exit=$?"
=== 284-journey-owner-vance-1.md
  ⛔ PRE-FIRE ASSERTIONS FAILED — 284-journey-owner-vance-1.md
  • A1 KANBAN — SCP_Kanban row 284 is HELD, not READY
exit=1
$ HEAD's prefire.py on the same file → the identical single A1 refusal, exit 1
$ python3 -c '…parse_test_scope / find_full_suite_instructions / check() on 284…'
A9 parse_test_scope -> ('targeted', '## Test scope: targeted (D-S7CORE30-05)')
A10 find_full_suite_instructions -> []
check() A9/A10 refusals -> []
```
- **A9 and A10 pass 284.** The live refusal is A1: Kanban row 284 is HELD on today's canon (the brief sits in `queue/held/`). HEAD gives the same verdict, so it is not this route's doing.
- **The pass line it will print once row 284 is READY,** shown with a scratch Kanban where row 284 is READY (`/tmp/orch283-scratch/p4canon`; the live canon was not touched):
```
  Assertions: ✅ A1/A2/A8/A9/A10 pass — SCP_Kanban row 284 READY (SCP_Kanban_v0-1.md); declared 60m (floor 30m); timeout 112 min (Estimated runtime × 1.25 — the fire applies TONI_TIMEOUT_MIN and the hard cap)
  Test scope: targeted (D-S7CORE30-05)
exit=0
```
The `held/` copy of 284 is md5-identical to the stage file (`680f5e51…`).

## §3 Gates

| Gate | Result |
|---|---|
| `tests/test_prefire.py` | RED 37 failed / 32 passed at HEAD's `prefire.py`; GREEN **69 passed** |
| The 4 changed prefire test files, in full: `test_prefire.py test_control_scope.py test_orch_lane.py test_runtime_parse.py` | **256 passed** in 9.5 s |
| Every other test calling `prefire.check`/`report`/`prefire_timeout`: `test_prefire.py`, `test_control_scope.py::TestP3Kanban`, `test_orch_lane.py::TestP4KanbanFamilies`, `test_runtime_parse.py`, `test_admission_parser.py` | **189 passed** |
| Full `pytest -q tests/` | **Not run** (brief §6, CLAUDE.md test scope, D-S7CORE30-05). The pre-merge gate runs it |
| Lint | `pyflakes` is not installed. `py_compile` passes on all 5 changed files |
| Live systems | Read-only throughout: `~/spectricom-orchestrator/queue/**`, `state/queue-state.json`, the canon Kanban, `~/_eos/s7core30/stage/284…`. The daemon was neither signalled nor restarted |

## §4 Incident: the RED run fired nested executors (cleaned up)
- **What happened.**
  - As first written, `test_D3_the_fire_refuses_a_brief_with_no_test_scope` called `orchestrator.run_batch` with `PREFIRE_BYPASS = False` and nothing stubbed.
  - On the RED run, HEAD's prefire cleared the fixture. `run_batch` then:
    - copied the fixture to `briefs/b.md`;
    - failed to cut a branch (`fatal: '-b' is not a valid branch name. Running on current branch.`);
    - at 14:43:18, started a real `claude --dangerously-skip-permissions --model claude-opus-5-5 --effort high` in this worktree (`logs/toni-b-20261017-144318.log`).
  - That session ran `tests/test_prefire.py`, which fired a second session (14:44:47), and that fired a third (14:46:39).
  - The RED run took 583 s instead of under 1 s.
- **What the nested sessions did, per their own logs, and what I verified.**
  - Session 3 says it was read-only.
  - Session 1 says it edited no tracked file.
  - Session 2 says it edited `prefire.py` and three test files, restored them to HEAD, and saved its diff to `/tmp/283-accidental-fire-491255.patch`.
  - **No commit or ref change:** `git reflog` shows only the 14:31:09 worktree creation, and the newest `refs/heads` timestamp is 14:28:23.
  - **The live daemon was untouched:** `~/spectricom-orchestrator/running.json` and `state/` keep their 14:31 mtimes.
  - **Nothing is left running:** no nested `claude` process remains.
  - **My working files are intact:**
    - `prefire.py` was restored from my saved copy (`cmp` identical).
    - Re-deriving `tests/test_prefire.py` from HEAD plus my edits gives the same prefix byte for byte, and I re-read the appended block in full.
- **What was left behind, and what I did with it.**
  - `briefs/b.md`: deleted.
  - The empty `state/` directory in the worktree: removed.
  - `logs/` (gitignored): kept as evidence.
  - Session 2 wrote a memory note, `~/.claude/projects/-home-gkassa-spectricom-orchestrator/memory/accidental-fixture-fire.md`, plus a one-line `MEMORY.md` index. That directory held nothing else, so nothing was overwritten. I left it; whether to keep it is your call.
- **The fix.** The test now wraps `prefire.report`, so a pass fails the test before `run_batch` goes on (`pytest.fail` is a BaseException, so no `except Exception` can swallow it). It also stubs `orchestrator.fire_toni`. Re-run RED on HEAD: it fails in 0.20 s, with nothing copied or fired.

## §1 Found and LEFT
1. **The daemon's `enqueue` checks nothing** (`queue_daemon.py:665-675`), for A1/A2/A8 as much as A9/A10. A brief is judged only when it fires. The brief assumed both paths apply the checks, but only one exists. Adding a check at enqueue means changing `queue_daemon.py`, which is outside §2.
2. **`orchestrator.py:5195`** still says `error='pre-fire assertions failed (A1/A2/A8) — HOOK-1'`, and the import comment at `:41` says `(SESSION-BOOT A1/A2/A8)`. Both are outside §2. Only the route's Result error string is stale; the printed refusal names A9/A10.
3. **Before turning `A10_BARE_PYTEST` on, the brief template needs changing.** Gemma's usual targeted gates wording is refused by D2's bare-`pytest` clause: 286:48 "Gates: `pytest` on the changed/new test files only", 282br:25 and 282b:39 "`python3 -m pytest -q` on the test files … adds". Forms that pass: `pytest <changed/new test files>`, `pytest tests/test_x.py`, or the same line carrying "do not run the full suite".
4. **A10's negation escape covers the whole line, so it is loose.** Any negation on a line lets a full-suite instruction on that line through, for example "never touch :3002 … run `npm test`". This is D2 as decided.
5. **A10 also refuses lines that only describe a suite** ("the gate runs `npm run sit:gate`") unless they negate. Orchestrator briefs about the gate will hit this; they need a negation on the line, or `full — D-…`.
6. **SESSION-BOOT's PRE-FIRE ASSERTION BLOCK already has an "A9"** (Gemma_System_Prompt v5-38, Canon_Index:34). Prefire's A9 is a different assertion with the same number. The docstring says so; renumbering is the canon owner's call.
7. **D2 does not cover these full-suite forms, and they pass A10:**
   - `npm run test:unit` and `npm run test:baseline`;
   - a bare `npx vitest run` (no files);
   - `yarn test` / `pnpm test`;
   - `pytest tests/` (the suite root counts as a path).
8. **Old briefs without the header** in `held/` and `failed/` are already refused at A1. If one is released with a READY row, it also needs the header.

## THE CONSEQUENCE (D-S7CORE13-03)
1. **After the merge.**
   - The next fire (282c, 286, …) prints `A1/A2/A8/A9/A10 pass`, then its `Test scope:` line. The current queue passes A9/A10.
   - A brief without the header, or with a malformed one, is refused at fire with the D1 text. So is a targeted brief that says `npm test`, `sit:gate` or a merge-base baseline without a negation; the refusal names the line.
   - No daemon restart is needed.
2. **Staged:** the bare-`pytest` clause, `prefire.py:198` `A10_BARE_PYTEST = False`. Turn it on once 286:48 is reworded or 286 has fired (see §1 item 3).
3. **Unchanged:**
   - A1/A2/A8 verdicts: identical on 274 real briefs;
   - the per-merge gate, the full gate, admission, the fire lock, `queue_daemon.py` and `--force`.

## Closes capability advancement: none
## Gates journey: none
