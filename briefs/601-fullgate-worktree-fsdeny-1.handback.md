# Handback — 601-fullgate-worktree-fsdeny-1 (ORCH-FULLGATE-WT-FSDENY-1 + ORCH-PREFLIGHT-READMAP-1, Kanban 601)

**Executor:** claude-opus-5-5 (effort high) · **Worktree:** `/tmp/orch-fire-20261115-110535`, branch
`orch-orch-000000601-fullgate-worktree-fsdeny-1`, base `d152f1f` · **Test scope:** targeted (D-S7CORE30-05)

| Part | Commit | Diff stat |
|---|---|---|
| A — a run that could not load its files is not a measurement; the full gate's collection check | `30435e0` | 9 files, +965 / −9 |
| B — a newly-failing file keeps its error lines (`confirm_errors`) | `62c92fa` | 3 files, +183 / −6 |
| C — `unit_related_extra`: preflight and the related leg reach the read-map pin test | `3917c13` | 4 files, +231 / −1 |

Each part was committed only after passing on its own: A's state 524 passed; A+B 533; A+B+C 549 (the gate list
below). Files touched are only the ones A2 allows: `orchestrator.py`, `config/repos.yaml` (the four clinical-mp keys),
`README.md` (one bullet per part, new section "Unit evidence"), `tests/test_unit_load_check.py`,
`tests/test_unit_confirm_errors.py`, `tests/test_unit_related_extra.py`, `tests/fixtures/unit_load/` (new), and this
handback. None of `prefire.py`, `prefire_opex_paths.json`, `queue_daemon.py`, `admission.py`, `executor/**` changed.

---

## A0 · as built at `d152f1f` (base line → line at `3917c13`)

0. **Worktree proof:** `/home/gkassa/spectricom-orchestrator/venv/bin/python -c "import orchestrator; print(orchestrator.__file__)"`
   from the worktree root → `/tmp/orch-fire-20261115-110535/orchestrator.py`.
1. `_link_unit_deps` `:3402-3428` (→ `:3412`), symlink `d.symlink_to(s.resolve(), …)` `:3425` (→ `:3435`).
   `_run_unit_baseline` `:3549` (→ `:3701`). The full gate's link `:6277` (→ `:6728`). The SIT collection-equals-suite
   check `:2692-2709` is unchanged. The unit legs had no collection check (confirmed).
2. `ENV_BLOCK_SIGNALS` `:457-499` (→ `:458`). Its block is **byte-identical** (asserted by
   `test_the_env_block_signals_table_is_byte_identical_to_the_base`). `_classify_gate_failure` `:5149` (→ `:5416`).
   Its calls moved as follows:
   - build `:1714` (unchanged), `:5395` → `:5662`, `:7045` → `:7497`;
   - SIT `:5332` → `:5599`, `:5971` → `:6247`;
   - unit `:5436` → `:5703`;
   - unit `:5572` → now `_classify_unit_failure` at `:5844`;
   - plus one new unit call inside `_classify_unit_failure` (`:3573`).

   No signal matches `Denied ID` (confirmed). `output=raw[-20000:]` `:3539` (→ `:3691`).
   `_unit_is_measurement` / `_unit_is_cacheable` `:3677/:3688` (→ `:3830/:3841`).
3. **Evidence pastes** (read-only from the main checkout's `logs/` and `state/`):
   - `full-gate-20261112-080457.log:62` — `🌙 full-gate clinical-mp @ 99a4787 (main): NEW FAILURES — … | unit FAIL(product) (2072 files/19543 tests, 9 failed, 19522 passed, 8 skipped, 4 todo); … NEW: sit/journey/l-enrol/__tests__/lane-dated-facts-1.test.…`
   - `:60` — `🛡 unit-confirm: FAIL — still failing alone: sit/journey/l-enrol/__tests__/lane-dated-facts-1.test.ts, src/App.portalChrome.test.tsx, src/App.practice-config.test.tsx, …`
   - `full-gate-20261112-013357.log:49` — `♻️ full-gate unit: reused measured run 99a4787 (3.3 h old) — 2072 files/20300 tests, 3 failed, …`
   - `orch-664r-lockfile-tracked-1r-20261112-164911.log:76` — `… unit: baseline merge-base 133f268: 2085 files/19666 tests, 4 failed, …`
   - `state/full-gate-clinical-mp.json` (finished_at, sha, outcome, unit failing files). History keeps 10 rows, so
     11-05 has rolled off: 11-07 e71872b PASS **82** · 11-08 f5aafbf PASS 4 · 11-08 acebef2 PASS 3 · 11-09 6130855
     PASS 1 · 11-10 ec40a84 PASS 2 · 11-11 93e227e PASS **84** · 11-12 01:53 99a4787 PASS 2 (reused) · 11-12 08:50
     99a4787 NEW FAILURES **89** · **after the brief was written:** 11-13 0dcbf0b BLOCKED **85** · 11-14 72abb86 PASS
     **84** · 11-15 03:49 c53cae4 PASS **1**.
   - 683 has landed on clinical-mp main (`bc6ba828` VITE-FS-ALLOW-LINKED-DEPS-1, `e7a99957`; `vite.config.ts:63-101`
     `linkedDepsFsAllow`). The Depends-on is met. The 11-15 nightly (1 failing file) is consistent with that, but I
     did not measure it.
4. `_unit_confirm_new_files` `:3621` (→ `:3774`). The confirm log keeps names only, e.g.
   `orch-668-…-140737.log:85` — `🔬 Unit gate confirmation — … flake: src/lib/__tests__/capability-reachability.test.ts; regression: (none)`.
5. `_unit_related_files` `:4659-4675` (→ `:4821`). clinical-mp `main:scripts/__tests__/gen-member-allowlist.test.ts`:
   `readFileSync` `:20`, `readRepo` `:32-35`, static imports `:23-30` (confirmed).
6. **Measure (fixtures only):** `~/_eos/s7core52/briefs/_work/fsdeny_probe.out` leg A was copied byte for byte (ANSI
   kept) to `tests/fixtures/unit_load/probe_linked_worktree.txt`. On HEAD it parses as `test_files_total 1`,
   `tests_total None`, `failures None`, failing `src/components/healthspan/IngestedResultReview.pdf-text.test.tsx`.
   `_classify_gate_failure("unit", …)` gives `FAIL(product) exit 1 — no F-20 environment signal`. Vitest was never
   run against clinical-mp from this route.

**F-20 fixtures counted (P-A2):**
- Gate-output fixture files: 4 under `tests/fixtures/*.txt` (`sit_gate_vitest_429_19files_3down`,
  `sit_gate_vitest_7files_18tests`, `unit_pytest_every_outcome`, `unit_pytest_q_every_outcome`).
- Signal-table tests: 41 in `tests/test_sit_rate_limit.py`, plus the direct-classifier tests in `test_gate_cost.py`
  and `test_clockguard_1.py`.
- All keep their verdicts (green in the gate list), and `ENV_BLOCK_SIGNALS` is byte-identical.

---

## Part A — `30435e0`

### G-* as built
- **G-A1:** `_UNIT_DENIED_ID_RE` `orchestrator.py:3454` (`^\s*(?:Error: )?Denied ID (\S+)`, applied per line after
  the ANSI strip). `_unit_load_denied(raw, linked_realpaths, root)` `:3501` checks three things:
  - the path, query string stripped, is under a linked realpath;
  - the path is not under `realpath(root)`;
  - the line is attributed to the FAIL header above it, one entry per file.

  The links come from `_link_unit_deps` `:3439-3441`, which records the realpaths of the `node_modules` links it
  creates in `_UNIT_LINKED[str(dst)]`. `_run_unit_suite` reads the registry for its cwd (`:3682-3689`); the baseline
  and the full gate drop it at teardown (`:3736`, `:6781`). The signal is not in `ENV_BLOCK_SIGNALS`. The unit-only
  classifier is `_classify_unit_failure` `:3563`: vite-fs-deny first, then the shared classifier unchanged.
- **G-A2:**
  - Unit gate `run_unit_gate`: `unloadable` `:5159` excludes files that could not load (on either side) from the
    regression rule. A confirmed regression keeps `FAIL(product)` and adds `also vite-fs-deny: …` (`:5213-5214`).
    Otherwise `BLOCKED(environment)` `vite-fs-deny` (`:5223-5236`). A zero collection caused by unloadable files
    says so (`:5079`).
  - Cache: `_unit_is_cacheable` `:3841/:3848` returns False for such a run. The baseline's note reads `NOT cached —
    vite-fs-deny: …` (`:4619`).
  - Full gate `_full_gate_unit` `:6268`: before the old `:6061`, `unloadable` → `failing_files: None` (`:6317-6320`).
    Suspects exclude unloadable files, and the denied verdict is at `:6365` / `:6393`. `_full_gate_previous` `:6589`
    itself is unchanged: it already skips a row whose `failing_files` is None, so storing None is what keeps such a
    run out of `previous`.
  - The two unit classifier sites the brief names:
    - Base `:5436` (→ `:5703`) is **unchanged**. It is reached only on a non-env `regression` outcome, because
      `run_unit_gate` decides vite-fs-deny before it. Routing it through the new classifier would have turned the
      mixed case into BLOCKED, against G-A2.
    - Base `:5572` (preflight, → `:5844`) now calls `_classify_unit_failure`. Unloadable files are never re-run as
      suspects (`:5839-5843`).
- **G-A3:**
  - The keys and defaults are at `:6405-6410`. `_full_gate_number` reads repos.yaml; a bad value gives one warning
    and the default.
  - `_unit_cache_measured_ancestors` `:6430` returns the nearest N judged full-suite ancestors.
  - `_unit_deleted_tests` `:6455` reads `git diff --name-status -M <ref> <sha>`, takes `D` entries for `*.test.*`
    files, and counts their `it(` / `test(` calls (`.each` / `.skip` / `.only` / `.todo`) in `git show <ref>:<file>`.
    An unreadable file is not subtracted and is named.
  - `_full_gate_collection` `:6478` is called at `:6322`. The blocked verdict is signal `collection-shrank` with
    `failing_files: None`. Any drop is never cached (`:6355`). A reused leg compares with ancestors via
    `exclude_ck=ck`, so never with itself.
  - **Subtraction stated:** reference − (static count of tests in deleted test files), printed
    `approx −N deleted (k test file(s) deleted since <sha7>, static it(/test( count)`.
- **G-A4:** `ORCH_UNIT_LOAD_CHECK` (any case) via `_unit_load_check_said` `:3470`. It writes one warning line per
  gate: unit gate `:5005`, full gate `:6285`, preflight `:5839`.

### P-* RED → GREEN (`tests/test_unit_load_check.py`, 45 tests)
- **On HEAD:** 23 failed, 21 passed, 1 skipped. Every red is a predicate or a new-record half. Every control is
  green. The skip is the byte-identity check, which needs git, and the HEAD copy (`git archive d152f1f`) has none.
- **Now:** 45 passed.

| Predicate | On HEAD (red) | Now (green) |
|---|---|---|
| **P-A1** probe → BLOCKED `vite-fs-deny` | `GateVerdict(FAIL(product), 'exit 1', 'no F-20 environment signal …')` | `vite-fs-deny: 1 test file(s) could not load (first: src/components/healthspan/IngestedResultReview.pdf-text.test.tsx · Denied ID /home/gkassa/spectricom-clinical-mp/node_modules/pdfjs-dist/legacy/build/pdf.worker.min.mjs?url)` |
| P-A1, full gate over 82 unloadable files | `unit FAIL(product) … NEW: src/d/f0…f81` | BLOCKED `vite-fs-deny`, no confirm run, `failing_files: null` |
| **P-A3** baseline measured in a linked worktree | `a run whose files could not load was cached` | not cached, note says why |
| P-A3, masked red in a file the base could not load | `UnitGateOutcome(passed=True, '1 failures, equal to the merge-base baseline of 1 …')` | BLOCKED `vite-fs-deny` (also on `run_pre_merge_gates`) |
| P-A3, mixed (route gate and full gate) | — | `FAIL(product)` + `also vite-fs-deny: 3 test file(s) …`; not cached |
| **P-A4** 19543 vs 20300, same key | PASS | BLOCKED; `⛔ full-gate unit: collected 19543 tests vs 20300 at <sha7> (−3.7%) — BLOCKED(environment), not FAIL(product) [same content key; threshold 0.5% (full_gate_collection_drop_same_pct)]` |
| P-A4, same key −0.6 % | PASS | BLOCKED |
| P-A4 (i), −1.5 % vs an ancestor | PASS and cached | judged PASS, not cached; the next run still compares with 20000 |
| P-A4, max of last N ancestors | PASS | max of N; `full_gate_collection_ref_n 2` changes the reference |
| P-A4 (iv), same drop with no deletion | PASS | BLOCKED |
| P-A4, a reused entry | PASS | compared from the second link → BLOCKED |
| **P-A5** kill switch | — | one warning line per gate |

**Controls, green on HEAD and now:**
- P-A2: an assertion quoting `Denied ID`; a denied path inside the worktree; a path outside the links; a run that
  linked nothing; `Failed to resolve import` on the unit leg; vite-build `failed to resolve import` on the build
  gate; build and SIT on the probe → all FAIL(product).
- P-A3: a clean baseline is cached as today.
- P-A4: 20300 / 20310 vs 20300 → PASS; no measurement → PASS and cached; same key −0.25 % → PASS; 500 deleted
  tests → PASS.
- P-A5 (`off` / `OFF` / `Off `): the full gate is HEAD's `FAIL(product)` with no `collection_check`; the route gate
  is HEAD's PASS and caches as HEAD did; the classifier is HEAD's.

### STOP (d) counts
The G-A1 anchor was checked against every text fixture under `tests/fixtures` (21 files, 615 lines). That covers
the 4 F-20 gate outputs, the handback logs, the canon/verify texts and P-A2's 3 product fixtures. Matches: **0**.
It was also checked against every line of the existing `tests/*.py` (22,324 lines): **0**. Test:
`test_stop_d_g_a1_matches_no_line_of_the_f20_or_product_fixtures`.

---

## Part B — `62c92fa`

### G-B1 as built
- `_unit_file_errors(raw, elide)` `:3531` gives each failing file's first ≤5 non-blank lines (`UNIT_ERROR_LINES`),
  each ≤200 chars (`_GATE_STDERR_LINE_CHARS`).
  - Vitest: the lines under a FAIL header, up to the next `⎯` / summary.
  - Pytest: the `FAILED … - <message>` line.
  - A line naming the env_file or matching `(?<![\w.])\.env\b` is replaced by
    `<a line naming …, elided — its values are never logged>`.
- It runs on the **full** `raw` before the cap (`:3682-3689`), into `UnitSuiteRun.file_errors`.
- `run_unit_gate` fills `confirm_errors` for every newly-failing file (`:5172`) and for the count-rise path's files
  (`:5277`), from the whole-suite branch run.
- `UnitGateOutcome.confirm_errors` goes into the unit-log entry (`:5376`, an optional key). The full gate's state
  carries `confirm_errors` for its suspects (`:6353`). No verdict reads it.

### P-B1 RED → GREEN (`tests/test_unit_confirm_errors.py`, 9 tests)
- **On HEAD:** 6 failed, 3 passed. `KeyError: 'confirm_errors'`; the helper doesn't exist.
- **Now:** 9 passed. The fixture is 28.7 kB (28,688 chars), with both files' blocks before the last 20 000 chars. The entry carries
  `confirm_errors` for UA and UB:
  - 5 lines each;
  - line 2 is the elided `.env` line;
  - no secret anywhere in the entry;
  - the lines are the whole-suite run's, not the isolation pass's.
- **Controls, green on HEAD and now:** the verdict is regression UA, flaky UB; every other entry field is HEAD's
  key set and values; a flaky-only gate still PASSes; no newly-failing file → no key.

---

## Part C — `3917c13`

### G-C1–C3 as built
- `_unit_related_files` `:4821` calls `_unit_related_extra` `:4834`. The scope line gains
  `, + N declared extra (unit_related_extra: <globs> or named in <doc> → <add>; touched <path>)`.
- The validator is in `_unit_related_extra` `:4866`. A malformed entry gives one warning line and today's set; any
  exception gives the same.
- `_unit_named_in` `:4852` takes backtick spans, strips a trailing `:line` / `:line-line`, and keeps only files
  tracked at the head (`git ls-files`). Routes and identifiers are ignored.
- **G-C2:** `config/repos.yaml` clinical-mp `unit_related_extra: [{when: ["docs/portal-read-map.md"], when_named_in:
  "docs/portal-read-map.md", add: ["scripts/__tests__/gen-member-allowlist.test.ts"]}]`. The test pins it to the real
  config.
- **G-C3:** `tests_reaching` `:5754` → `_unit_scope` → the same function. Proved through `preflight()` itself.

### P-C RED → GREEN (`tests/test_unit_related_extra.py`, 16 tests)
The HEAD run used HEAD's code with the new repos.yaml, so the reds are behavioural.
- **On HEAD:** 7 failed, 9 passed.
  - A map-only diff gives `UnitScope(files=(), reason='unit: no unit test file relates to this diff …')`.
  - Preflight gives `{'status': 'pass', 'files': [] …}`.
- **Now:** 16 passed.
  - P-C1: a map-only diff gives `(PIN,)`; the tracked call site `server/routes/member.ts:12` gives `(T1, PIN)`;
    `:30-41` is stripped; the gate runs `npm test -- PIN` and its 🎯 line names the rule.
  - P-C2: `preflight()` exits 0 with `unit.files == [PIN]`; `🧪 Preflight (executor): 0 SIT files / 1 unit files — pass`.
- **Controls, green on HEAD and now:**
  - An unrelated diff is unchanged.
  - 6 malformed shapes each give today's set (the warning is checked where it exists).
  - An `add` file outside the suite is not added.

---

## Rule #8
The search was re-run at the base: `grep -n -E "ENV_BLOCK_SIGNALS|_unit_is_cacheable|…|UnitSuiteRun" tests/*.py`.
**13 files** hit: test_baseline_reuse_1 (2), test_baseline_trust (3), test_config_truth (1),
test_control_verdict_lines (6), test_exec_preflight (3), test_gate_clock (1), test_gate_cost (4),
test_isolated_deps (1), test_unit_baseline_gate (22), test_unit_fail_label (1), test_unit_gate_wording (3),
test_unit_listing_prefix (2), test_unit_related (2).
- Every hit builds `UnitSuiteRun` objects, stubs `_run_unit_suite` / `_unit_confirm_new_files` with their base
  signatures, or asserts the `confirmed FLAKY` wording. All stay green **unedited**.
- The changes are additions only:
  - new dataclass fields with defaults;
  - no signature changed (the link registry exists so that no stub signature had to change);
  - `confirm_errors` is an optional log key;
  - the scope-line suffix appears only when a rule fires.
- `git grep ENV_BLOCK_SIGNALS d152f1f -- tests` = 0 and "affected by the diff" in tests = 0 (both re-checked).
- **No pin changed; OPEN (c) / 601-G1 not needed.** No mechanical pin was edited.

## Gates (targeted, foreground, worktree root, the main checkout's venv interpreter)
- **Gate list** — `pytest -q tests/test_unit_load_check.py tests/test_unit_confirm_errors.py tests/test_unit_related_extra.py tests/test_unit_related.py tests/test_unit_baseline_gate.py tests/test_baseline_trust.py tests/test_baseline_reuse_1.py tests/test_fullgate_reuse.py tests/test_fullgate_local_files.py tests/test_gate_cost.py tests/test_sit_rate_limit.py tests/test_clockguard_1.py`
  → **549 passed**.
- **Rule #8 neighbours** — `test_control_verdict_lines test_config_truth test_exec_preflight test_gate_clock test_isolated_deps test_unit_fail_label test_unit_gate_wording test_unit_listing_prefix test_prelist`
  → **191 passed**.
- `python -m py_compile orchestrator.py` ok · `yaml.safe_load(open('config/repos.yaml'))` ok.
- Full `tests/` not run (Test scope: targeted); the pre-merge gate runs it.

## Preflight (run as the fire prompt orders)
```
  SIT: 0 file(s) — pass — orchestrator's gate has no SIT leg
  unit: ? file(s) — not computed — the gate runs the FULL unit suite — related selection not available for orchestrator — `pytest -q tests/` is not a vitest run
🧪 Preflight (executor): 0 SIT files / ? unit files — fail (not computed)
   JSON: /home/gkassa/spectricom-orchestrator/state/preflight/orch-orch-000000601-fullgate-worktree-fsdeny-1.json
```
- **Exit 3, not computed.** This is not a test red: the orchestrator repo has no related selection, so the gate runs
  the full suite at merge. 652-660 and 662-663 reported the same.
- **Flag (STOP (f) tension):** the command is `python3 ~/spectricom-orchestrator/orchestrator.py`, so it ran the
  main checkout's code. It wrote that one JSON file under the main checkout's `state/preflight/`. I ran it because
  the fire prompt orders it verbatim. No other command wrote anywhere in `~/spectricom-orchestrator`.
- Reads made in the main checkout: the venv interpreter (as the brief orders), plus the A0 #3 log and state pastes.
  No daemon command was run, no process was signalled, and `claude` was not called. Clinical-mp was read only with
  `git log` / `git show main:`.

## Decisions to check (my reading of the brief, stated)
1. **The "links made for this run" are recorded in-process** (`_UNIT_LINKED`). This includes a parallel route
   worktree's links (`_link_unit_deps` at `:1754` registers too), so a route's branch leg in such a worktree is
   checked the same way. `preflight` is a separate process with no registry entry, so its vite-fs-deny check is
   wired but can only fire through `_link_unit_deps` in that process (in practice it does not).
2. **Files that could not load on either side are left out of the comparison.** That is the "LOADABLE files"
   reading, and it is what unmasks a branch red in a file the base never loaded. With such files present, the
   count-rise path does not run: the verdict is BLOCKED, never PASS.
3. **A suspect whose isolation run is itself `Denied ID` is not confirmed** (it joins the unloadable files). This
   goes beyond the brief and fails closed.
4. **"Same content key first"**: the cache holds one entry per tree, and that entry is the reference (0.5 %).
   Otherwise the reference is the max of the N nearest measured ancestors (2 %). The collection check is skipped on
   a run that already has unloadable files, because G-A2 has decided it. A run that dropped but stayed within the
   threshold keeps its `failing_files` as a possible `previous` (it is judged as today); only the collection
   reference is barred from ratcheting.
5. `tests/fixtures/unit_load/README.md` records where each fixture came from.

## R-items
- **OPEN (b)** is unchanged and still owed: entries cached before this route (linked-worktree measurements since
  2026-11-04) are still content hits, ancestors, and reuse sources. A reused entry has no output for G-A1 to see.
  G-A3 now catches a reused entry whose collection shrank against its second link.
- **OPEN (e) yorsie:** unchanged; any future `?url` / `?raw` / `?worker` import there needs 683's allow-list fix.
- The probe-shaped output (`Tests no tests`, one file) has `tests_total None`. On a route gate that is
  `comparison-unavailable`, and on the full gate `unmeasurable`. Both were already BLOCKED, and the vite-fs-deny
  verdict decides only when the counts parse. The `zero-collection` path names the signal.
- **Self-mod sequencing** (Notes for Gemma): the daemon imports `orchestrator.py`, so it needs a restart after merge
  for the new checks to run.

## FINAL STATUS
DONE — A `30435e0`, B `62c92fa`, C `3917c13`.
- New tests: 70/70 green. On HEAD: 36 red (the predicates and new-record halves), 33 green (every control), 1 skip.
- Gate list 549 passed · rule #8 neighbours 191 passed · `py_compile` and the YAML load ok.
- No pin changed (OPEN (c) not needed). STOP (d) matches: 0. No STOP hit.
- Full `tests/` not run (Test scope: targeted).
- Preflight: exit 3, not computed (unit leg, orchestrator); summary pasted above.
