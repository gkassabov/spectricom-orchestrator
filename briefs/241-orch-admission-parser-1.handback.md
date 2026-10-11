# filename: briefs/241-orch-admission-parser-1.handback.md

# 241 · ORCH-ADMISSION-PARSER-1: handback

**The daemon's route wall now reads a brief's timeout through the route's own function.**
- `admission.parse_brief_timeout` reads the overrides as before: the `## TONI_TIMEOUT_MIN:` header, then the `## Fire mechanism:` override. It then reads the runtime line through `prefire.runtime_timeout`, route 233's single parser.
- `orchestrator.parse_brief_timeout` now returns admission's.
- The environment > brief > default precedence is now one function too: `admission.requested_timeout`. `orchestrator._requested_timeout` returns it.
- So there is no fourth copy, and the route keeps its third.
- Route 225's `2-3 h` now gets a clinical-mp wall of **280 min** (180 + 85 gates + 15 slack). On `8a2842c` it got 145 min, below the route's own 180-min timeout.

**The unit-gate tally now counts pytest's `xfailed` and `xpassed`.** pytest's total already counted them. Route 233's `1148 passed, 1 xfailed` now adds up to 1149 and is CLEAN. A real mismatch still warns: a fabricated 1148 passed over 1150 does, and so does every fixture that warned before.

**Gemma: restart the queue daemon after this merges to load D1. It imported `admission` at start (`queue_daemon.py:37`). Nothing else needs to change.** The `orchestrator.py` half (D1 delegation, D3 tally) loads on the next fire with no restart.

P1–P3 are green. P1 and P2 were RED first on `8a2842c`, each with negative controls. In P3 one brief changes, `failed/225-provider-task-privacy-1.md` (`2-3 h`), which is hour-format. No brief in minutes changes.

- **Branch:** `orch-orch-241-orch-admission-parser-1`, from `8a2842c` (= `main` = merge-base). No commit since `8a2842c` touches a named file, so §1 has no re-read.
- **Commits:**
  - `d7e43bb` holds `admission.py`, `orchestrator.py`, `tests/test_admission_parser.py` (new), `tests/test_capacity.py`, `tests/test_runtime_parse.py`, `tests/test_unit_baseline_gate.py` and the two fixtures `tests/fixtures/unit_pytest_{q_,}every_outcome.txt` (new).
  - The next commit is this file.
  - I did not commit the brief, following routes 94–233.
  - `prefire.py` is untouched: D1 needed no new export.
- **Tests:** `pytest -q tests/`:

  | | result | time |
  |---|---|---|
  | `8a2842c` | **1148 passed, 1 xfailed** | 67.92 s |
  | `d7e43bb` | **1206 passed** | 67.67 s |

  - 0 failed, 0 skipped.
  - The xfail is now a plain pass (D2).
  - There are 57 new test items: 33 in `test_admission_parser.py`, 2 in `test_capacity.py` and 22 in `test_unit_baseline_gate.py`.

## §1 Found and LEFT

1. **pytest's `deselected` is not counted** (D3 names the six outcomes; deselection is not one of them). This matters only for runs that deselect tests:
   - **Under `-q`:** the total is the summary's own sum, which already leaves `deselected` out, so the run is CLEAN.
   - **Without `-q`:** the total is `collected N items`, which counts deselected tests, so the run still warns. Real pytest 9.0.3 output: `collected 8 items / 5 deselected / 3 selected` with `2 passed, 1 skipped, 5 deselected` reads as 3 against 8.
   - **No configured `test_cmd` deselects.** ai-foundation and norra run bare `pytest`. ai-foundation's `pytest.ini` declares an `integration` marker but has no `addopts`.
   - **The fix** would count `deselected` only against a `collected` total. That is a decision about what the total means, so I left it.
2. **A test can be counted twice.** When a test fails and its teardown also errors, pytest prints `1 failed, 1 error` for that one test. Against a `collected` total (bare `pytest`) that warns. Under `-q` it cannot, because the total is the same sum. This is pytest's own count, so I left it.
3. **The daemon's `⏱ route wall` line does not show a clamp.** It says `route timeout 180m (brief-declared)` for a brief that asked 225. Prefire's pass line on the fire does show `⚠ clamped to 180 min from 225` (route 233).
4. **The daemon now reads the runtime line over a wider window.** It reads the line where prefire does, in the first 6000 characters; it used to read the first 4000.
   - The route has read 6000 since route 233, and `test_the_runtime_line_is_read_where_prefire_reads_it` pins that both read the same window.
   - A brief written in minutes with its runtime line between characters 4000 and 6000 would get a different wall. There are none in the corpus (P3: 0 such changes).
   - The two override headers are still read in the first 4000, unchanged.
5. **The route's default now comes from `admission.TIMEOUT_DEFAULT_MIN`.** That is 45, the same as `orchestrator.TIMEOUT_DEFAULT_MIN`, and `tests/test_capacity.py::test_the_restated_clocks_are_orchestrators` pins the two equal.
   - `orchestrator.TIMEOUT_DEFAULT_MIN` is still read for `TONI_TIMEOUT` (`orchestrator.py:217`).
   - Changing one constant without the other fails that test, as it did before.
6. **Older cache entries lack the new tallies.**
   - A cached pytest baseline written before this merge has no `tests_xfailed` / `tests_xpassed`. If its run had an xfail or an xpass, it would still warn when reused.
   - **None today:** the live `sit-archive/unit-baseline-cache.json` (read-only) holds 168 entries, 1 of them pytest, and its tally adds up.
   - The entries are keyed on sha + cmd, so any new merge base re-measures.
7. **No vitest could be run here.** `npm install vitest@4.1.4` into a scratch directory fails, offline and online, with `npm error Cannot read properties of null (reading 'edgesOut')`.
   - So the vitest fixtures are real vitest 4.1.4 lines quoted in clinical-mp route logs, plus Yorsie's real SIT output, already in `tests/fixtures/sit_gate_vitest_429_19files_3down.txt`. The log sources are named in the test file.
   - In the log, the `Test Files` line of `VITEST_SKIPPED_TODO` carried a transcript note (`<- RUN 2, after the fix`). I dropped it, and nothing asserts on that line.
8. **One existing fixture changes verdict.** ORCH-8's `2 failed, 1 passed, 8 skipped, 4 xfailed in 0.5s` (`tests/test_unit_baseline_gate.py:1572`) now reconciles: 2 + 1 + 8 + 4 = 15 = its total.
   - It was the same false mismatch, and no test asserted on its tally.
   - This is the only pre-existing literal whose verdict moved (STOP (c) sweep, below).

## D1–D4 as built (`d7e43bb`)

- **D1, one function each:**
  - `admission.py:45` imports `prefire`. `prefire` imports only stdlib, `yaml` and `canon_assert`, and writes no log. The daemon already imports `canon_assert`.
  - `admission.parse_brief_timeout` (`admission.py:297`): the two override headers in the first 4000 characters, unchanged, then `return prefire.runtime_timeout(Path(brief))` (`:315`). The old `<n>-<m> m` grammar is deleted.
  - `admission.requested_timeout(brief, env)` (`:318`) gives `(minutes, source)` before the cap: env > brief > default. It raises `ValueError` when `TONI_TIMEOUT_MIN` is set and not a number.
  - `admission.route_timeout` (`:330`) is `requested_timeout`, capped. On a `ValueError` it returns the cap with source `env-var '<raw>' unreadable — the 180m cap`, byte-identical to `8a2842c`.
  - `admission.route_wall` (`:380`) and its call site in the daemon (`queue_daemon.py:1125`) are unchanged.
  - `orchestrator.parse_brief_timeout` (`orchestrator.py:630`) is now `return admission.parse_brief_timeout(filepath)` (`:642`).
  - `orchestrator._requested_timeout` (`:645`) is now `return admission.requested_timeout(brief_path, os.environ)` (`:648`).
  - `resolve_timeout` (`:651`, which keeps the clamp warning) and `prefire_timeout` (`:666`, which keeps its `ValueError` → None) are unchanged.
- **D2:** `tests/test_runtime_parse.py:238`, `test_found_and_left_the_daemons_wall_reads_the_same_route_timeout`, has lost its `xfail(strict=True)` marker. It FAILS on `8a2842c` (`(45, 'default') != (180, 'brief-declared')`) and passes at `d7e43bb`.
- **D3, the tally:**
  - **Fields:** `UnitSuiteRun.tests_xfailed` / `tests_xpassed` (`orchestrator.py:2578-2579`). None means the summary has no such segment, never 0, and they are always None on vitest.
  - **Properties:** `collection` (`:2593`) names them. `tally_sum` (`:2619`) adds them. `tally_note` (`:2634`, the `TALLY MISMATCH` sentence at `:2652`) names them in its parts.
  - **Parser:** `_parse_unit_summary` (`:2800-2801`) reads them off pytest's summary line.
  - **Persisted:** additively, in the baseline cache (`:3182`) and its rehydration (`:3523`), and in `orchestrator-unit-log.json` (`:3922`).
  - **The outcome set:**
    - pytest: passed, failed + error (inside `failures`, as always), skipped, xfailed, xpassed.
    - vitest: failed, passed, expected fail, skipped, todo, unchanged.
  - **Unchanged:** the total itself, `failures`, every verdict, the cache version and the fast path.
- **D4:** see §2, P3.

## §2 Predicates

| # | RED on `8a2842c` | GREEN at `d7e43bb` | Negative control | Verdict |
|---|---|---|---|---|
| **P1** `2-3 h` daemon wall | `admission.parse_brief_timeout` → None; `route_timeout` → `(45, 'default')`; walls 145 / 120 / 110 / 120 min (clinical-mp / yorsie / ai-foundation / orchestrator), each below the route's 180. The daemon loop (`test_R_the_daemon_reads_a_runtime_line_in_hours_as_the_route_does`) recorded `(45, 'default')`, i.e. 2700 s | `parse_brief_timeout` → **225**; `route_timeout` → **`(180, 'brief-declared')`** = `orchestrator.resolve_timeout`; walls **280 / 255 / 245 / 255 min** (each `8a2842c` wall + 135); the daemon loop records 10800 s and `seconds` = 180·60 + 5100 + 900 | `90-120 min` → **150** on both (RED-run PASS). `TONI_TIMEOUT_MIN: 40` + `2-3 h` → **40** on both, and the wall is built from 40. `Fire mechanism … =75` → 75. Env `30` → `(30, 'env-var')` on both. Env `abc` → the wall's cap, the route's `ValueError`. All green on HEAD | **PASS** |
| **P1** agreement | Over an 18-shape table: 6 FAIL (`2-3 h`, `2-3h`, `3-4 hours Toni session`, `1.5 hours`, `1.5h`, `2 hours`); 12 PASS (every minutes shape, `TBD`, no line, both headers). Runtime line past char 4000: FAIL. Replay: 1 disagreement in 201 | 18/18, the past-4000 case, and **0 disagreements in 201** replayed briefs | — | **PASS** |
| **P1** one function | `TestD1OneFunction`: 4 FAIL (no `requested_timeout`; monkeypatching admission does not reach orchestrator; the runtime line is not prefire's; the header regexes are written twice and the old grammar exists) | 4 PASS. Monkeypatching `admission.parse_brief_timeout` → 123 moves `orchestrator.parse_brief_timeout` and `resolve_timeout`. Monkeypatching `admission.requested_timeout` → 321 moves `resolve_timeout` (180, clamped) and `prefire_timeout` (`(180, 'spy', 321)`). `prefire.parse_declared_runtime` → (10, 100) moves the wall to 125 min | — | **PASS** |
| **P2** tally | Route 233's real line (`1148 passed, 1 xfailed in 67.92s (0:01:07)`): `TALLY MISMATCH on route: 0 failed + 1148 passed = 1148, but the runner states 1149`, the same sentence 233's gate logged (`logs/orchestrator/orch-233-…-20261011-052144.log:47`). The every-outcome run: `2 failed + 2 passed + 1 skipped = 5, but the runner states 8`, under both `-q` and `collected`. 12 tests FAIL (`TestP2Route233sLineReconciles` 10/10; `TestP2AGenuineMismatchStillWarns` 2/7 need the new terms in the sentence) | 233's line → **CLEAN**: total 1149 = 0 + 1148 + 1 xfailed. The gate is silent, the record has `tally_agrees: true`, `tally_sum: 1149`, `tests_xfailed: 1`, and the line reads `1149 tests, 0 failed, 1148 passed, 1 xfailed`. The every-outcome run → **CLEAN** under both: 2 (1 failed + 1 error) + 2 + 1 + 2 + 1 = 8. The cache reuses the xfail and stays CLEAN | `collected 1150 items` + `1148 passed in 66.23s` → **MISMATCH** `0 failed + 1148 passed = 1148, but the runner states 1150` (RED-run PASS). 233's line over 1150 → **MISMATCH** `… + 1 xfailed = 1149, but … 1150`. The every-outcome run over `collected 9` → **MISMATCH**. CMP_SHORT, expected-fail-off-by-one, CMP_EXPECTED_FAIL_SHORT and the clamped derivation → **MISMATCH**, before and after. Real vitest skipped + todo (`3 failed \| 7273 passed \| 8 skipped \| 4 todo (7288)`), skipped only (`13 failed \| 11 passed \| 14 skipped (38)`), all five, and Yorsie's SIT output → **CLEAN**, before and after | **PASS** |
| **P3** replay | 1 disagreement (`failed/225`: daemon `(45, 'default')`, route `(180, 'brief-declared')`) | 1 wall changed, hour-format; 0 written in minutes; 0 disagreements | — | **PASS** |

**RED run** (the new and changed tests against `8a2842c`'s `admission.py` / `orchestrator.py`): **30 failed, 49 passed.** The 49 are the negative controls, which need no new behaviour, plus the unchanged `TestP7RouteWall` cases. **GREEN:** 79/79.

### P3: D4 replay

`/tmp/p241/replay.py` is read-only. It loads `admission.py` twice:
- **before:** `git show 8a2842c:admission.py`
- **after:** this tree's

It computes `route_wall(brief, <#!queue repo>, config/repos.yaml, env={})` for every brief in the live checkout's `queue/`, in `queue/done/` modified in the last 30 days, and in `queue/failed/`. It also asserts that the after side equals `orchestrator.resolve_timeout`. The live `config/repos.yaml` is byte-identical to this tree's.

```
== cutoff for done/: mtime since 2026-09-11 14:08
== queue/: 6 briefs; wall changed: 0
== done/: 178 briefs; wall changed: 0
== failed/: 17 briefs; wall changed: 1
== replayed 201; daemon route timeout != orchestrator.resolve_timeout (after): 0
== changed walls: 1; of them NOT hour-format: 0 []
   failed/225-provider-task-privacy-1.md [clinical-mp] '2-3 h' hour-format=True: 45m (default) wall 145m -> 180m (brief-declared) wall 280m
```
On `8a2842c` (the same script before the edit) the line read `daemon route timeout != orchestrator.resolve_timeout: 1`, which was `failed/225`.

**The hour-format briefs that change:**

| brief | repo | runtime | daemon route timeout / wall, before | after |
|---|---|---|---|---|
| `failed/225-provider-task-privacy-1.md` | clinical-mp | `2-3 h` | 45 (default) / 145 min | 180 (brief-declared, clamped from 225) / 280 min |

**What is queued now** (route timeout in minutes (source) / wall in minutes; nothing changes):

| brief | repo | runtime | before | after |
|---|---|---|---|---|
| `241-orch-admission-parser-1.md` | orchestrator | `30-50 min` | 62 (brief-declared) / 137 | 62 (brief-declared) / 137 |
| `242-template-apply-artifacts-1.md` | clinical-mp | `100-140 min` | 175 (brief-declared) / 275 | 175 (brief-declared) / 275 |
| `242b-care-gap-provider-first-1.md` | clinical-mp | `140-170 min` | 180 (brief-declared) / 280 | 180 (brief-declared) / 280 |
| `243-small-fixes-7.md` | clinical-mp | `100-140 min` | 175 (brief-declared) / 275 | 175 (brief-declared) / 275 |
| `244-small-fixes-8.md` | clinical-mp | `80-110 min` | 137 (brief-declared) / 237 | 137 (brief-declared) / 237 |
| `246-member-api-proxy-1c-ii.md` | clinical-mp | `140-170 min` | 180 (brief-declared) / 280 | 180 (brief-declared) / 280 |

### STOP (c) sweep

`/tmp/p241/stop_c.py` runs every string literal in `tests/*.py`, and every `tests/fixtures/**/*.txt`, through `_parse_unit_summary`. That is 2822 texts; 52 of them give a checkable tally. The old verdict is the new sum minus D3's two terms, which are the only terms D3 added.

```
  moved MISMATCH->CLEAN tests/test_unit_baseline_gate.py:2061: total=1149 old_sum=1148 new_sum=1149 xfailed=1 xpassed=None
  moved MISMATCH->CLEAN tests/test_unit_baseline_gate.py:2121: total=1149 old_sum=1148 new_sum=1149 xfailed=1 xpassed=None
  moved MISMATCH->CLEAN tests/test_unit_baseline_gate.py:1572: total=15 old_sum=11 new_sum=15 xfailed=4 xpassed=None
  moved MISMATCH->CLEAN tests/fixtures/unit_pytest_every_outcome.txt: total=8 old_sum=5 new_sum=8 xfailed=2 xpassed=1
  moved MISMATCH->CLEAN tests/fixtures/unit_pytest_q_every_outcome.txt: total=8 old_sum=5 new_sum=8 xfailed=2 xpassed=1
== 2822 literals/files; 52 parse to a checkable tally; MISMATCH old=15 new=10; moved=5
```
- Four of the five are this route's own fixtures. The fifth is Found-and-LEFT 8.
- Each one sums exactly to its total once xfailed and xpassed are counted, so none of them is a real mismatch hidden.
- The other 10 still warn. STOP (c) does not apply.

### The pytest fixtures (real output, pytest 9.0.3)

`PYTEST_233` is the tail of `pytest -q tests/` at `8a2842c`: this route's merge-base gate, the suite route 233's gate ran.

The two `unit_pytest_*every_outcome.txt` files are pytest's output on this 8-test scratch file, run with `-q` and without:

```python
import pytest

def test_pass(): pass
def test_pass2(): pass
def test_fail(): assert False
@pytest.fixture
def broken(): raise RuntimeError("setup")
def test_error(broken): pass
@pytest.mark.skip(reason="s")
def test_skip(): pass
@pytest.mark.xfail(reason="x")
def test_xfail(): assert False
@pytest.mark.xfail(reason="x")
def test_xpass(): pass
@pytest.mark.xfail(strict=True, reason="x")
def test_xfail_strict(): assert False
```

The summary for both runs: `1 failed, 2 passed, 1 skipped, 2 xfailed, 1 xpassed, 1 error`. The run without `-q` also prints `collected 8 items`.

## §3 Gates

| Gate | Result |
|---|---|
| `pytest -q tests/` at merge-base `8a2842c` (this worktree, before any edit) | **1148 passed, 1 xfailed** in 67.92 s |
| `pytest -q tests/` at `d7e43bb` | **1206 passed** in 67.67 s. **0 new failures** (merge-base failures: none), 0 skipped, 0 xfailed |
| Targeted: the P1/P2/D2 tests | RED 30 failed / 49 passed on `8a2842c`; GREEN 79 passed |
| The orchestrator's self-mod gate (`build` = `pytest -q tests/` on this worktree, the unit baseline gate with `test_cmd` = `pytest -q tests/`, then `_self_mod_auto_merge`) | The orchestrator runs it after this executor exits; it cannot be run from here without firing a route. The suite it runs is the one above, green at `d7e43bb`. Its summary has no xfail, so it reconciles under the old tally as well as the new |
| Smoke: `admission` imported from outside the repo, as the daemon loads it | `admission.prefire is prefire`; `route_wall(<2-3 h>, 'clinical-mp')` → `16800s (280m) = route timeout 180m (brief-declared) + gate budget 5100s (…) + 900s slack`. `python3 admission.py --orch-dir <empty> routes` → exit 0 |
| Daemon, `queue/`, `logs/`, `state/` of the live checkout | Not touched, and the daemon was not signalled. The live checkout was only read: the P3 corpus, `config/repos.yaml` (diffed), route logs for the real vitest lines and 233's gate line, and `sit-archive/unit-baseline-cache.json` |

## THE CONSEQUENCE (D-S7CORE13-03)

1. **After the merge, before the daemon restarts:**
   - Every fire's `orchestrator.py` process loads the new `admission.py` and `orchestrator.py`.
   - So the route's timeout and the unit-gate tally are the new ones. The route's timeout is the same number as before for every brief.
   - The daemon's wall is still `8a2842c`'s, held in memory, until the restart. No queued brief is affected (P3).
2. **After the restart**, a brief whose runtime line is in hours gets a wall built from its own timeout. For `2-3 h` that is 180 (clamped from 225) + gates + 15 min, not 45 + gates + 15. Such a route is then held by its own 180-min timeout first, and by the wall only past its gates' budget. Every brief written in minutes keeps the same wall (P3).
3. **A pytest suite carrying an xfail or an xpass stops warning `TALLY MISMATCH` on correct runs.**
   - Its gate line names them: `…, 1148 passed, 1 xfailed`.
   - The unit log and baseline cache record `tests_xfailed` / `tests_xpassed`.
   - A run whose parts do not sum to the runner's total still warns, in the same sentence, now naming the xfailed / xpassed parts.
4. **Nothing else changes:** no verdict, no gate decision, no timeout, no header, no constant, no config.
