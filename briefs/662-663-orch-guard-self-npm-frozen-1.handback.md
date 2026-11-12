# HANDBACK — 662-663-orch-guard-self-npm-frozen-1 (ORCH-GUARD-SELF-NPM-FROZEN-1, Kanban 662 + 663)

**Status: DONE. Parts A and B are built, each in its own commit, with every predicate green.** Preflight exits 3 with "not computed" on the unit leg. That is structural (the orchestrator repo has no related-test selection, so the merge gate runs the full unit suite), not a red test. It is the same result 652-660 handed back. No STOP was hit. Two things go beyond the brief's letter and are named under "Deviations": a third Part A rule #8 edit under the mechanical-pin line, and a few hook rules that are stricter than written.

| Part | Commit | Diff stat |
|---|---|---|
| A — the guard protects its own files; agentic-ops; no inventory refuses | `1c6c223` | 4 files, +138 −18 |
| B — npm frozen hook, `## Dependency change:`, G-N4 | `f025c7b` | 12 files, +1315 |

## X0 · the worktree
1. `HEAD` = `707b2e09ee701eb4f9fde144f87dc6b1fe73b7e6`. `git log --oneline -5`: `707b2e0` handback 652-660 · `edff123` · `ce776e0` · `0640837` · `bfe00e7` (652-660 A–D). `git merge-base --is-ancestor 707b2e0 main` is true, so 652-660 is merged.
2. `prefire.__file__` = `/tmp/orch-fire-20261112-095550/prefire.py` and `orchestrator.__file__` = `/tmp/orch-fire-20261112-095550/orchestrator.py`. Both are under the worktree.
3. `grep -l "repo=orchestrator" ~/spectricom-orchestrator/queue/*.md` → `queue/662-663-orch-guard-self-npm-frozen-1.md` only (this route's own copy).

---

## PART A · ORCH-GUARD-SELF-PROTECT-1 (Kanban 662) — `1c6c223`

### A0 · as built (at `707b2e0`)
1. `prefire_opex_paths.json` at the base: `protected.orchestrator` `:54-57` = `executor/**`, `orchestrator.py`. `_orchestrator` note `:58` = "orchestrator.py holds the merge code (merge_branch, run_batch's merge)." `agent_runtime.clinical-mp` `:5-11` = `src/lib/agentic-runtime/**`, `src/daemon/**`, `src/lib/agentic-drafts/**`, `server/**/agent*`, `server/simulation/**` (652 A is in). Moved from the brief's `:53-56` / `:57` / `:5-10` by 652 A's one line.
2. `check_agent_policy` at `prefire.py:752` (was `:737`). Its no-inventory branch `:770-772` returned `OpexVerdict(True, "OPX-2 ⚠ … — no %s_v*.md in %s yet, so no policy id can be checked: warning, pass (D-S7CORE33-20)")`. Its docstring is `:753-755`. The module docstring's OPX-2 entry `:43-45` read "No inventory file yet ⇒ warning, pass." The canon-unreadable branch (`:766-768`) and the inventory-unreadable branch (`:775-777`) already refused.
3. The three gaps, shown on the base with scratch brief and canon under `/tmp` (the test file's own `brief()` / `opex()` helpers):
   - (a) `repo=orchestrator`, no George go. Each of `prefire.py`, `queue_daemon.py`, `admission.py`, `prefire_opex_paths.json` → `OPX-3 ✅ no never-autonomous path in ALLOWED FILES (1 named without a directory — matched by file name only)`.
   - (b) `repo=clinical-mp`, `src/lib/agentic-ops/routing.ts`, no policy id → `OPX-2 ✅ no agent-runtime path in ALLOWED FILES`.
   - (c) No inventory, `src/daemon/x.ts` → `OPX-2 ⚠ agent-runtime path(s) src/daemon/x.ts (src/daemon/**) — no SCP_Agent_Inventory_v*.md in /tmp/oc34a0-…/canon yet, so no policy id can be checked: warning, pass (D-S7CORE33-20)`.
4. Matcher (`prefire.path_matches`, read-only). Same result as the author's:

   | glob | path | match |
   |---|---|---|
   | `prefire.py` | `prefire.py` · `tests/test_prefire.py` · `docs/x/prefire.py` | True · **False** · True |
   | `queue_daemon.py` | `queue_daemon.py` · `tests/test_queue_daemon.py` | True · **False** |
   | `admission.py` | `admission.py` · `tests/test_admission.py` | True · **False** |
   | `prefire_opex_paths.json` | itself · `tests/prefire_opex_paths.json.bak` | True · False |
   | `src/lib/agentic-ops/**` | `src/lib/agentic-ops` · `…/routing.ts` · `…/__tests__/routing.test.ts` · `src/lib/agentic-opsx/y.ts` · `src/lib/agentic-runtime/tools.ts` | True · True · True · **False** · **False** |
5. Corpus: the live queue is now `662-663`, `664`, `665`, `668`. The author's list of 585-606 … 661 has left `queue/`. Each brief's OPX-2 / OPX-3 line, base vs this worktree:
   - **662-663**: OPX-2 ✅ (executor/** under AP-ORCH, AP-TONI, AP-DAEMON) on both. OPX-3 ✅ on both. The worktree's OPX-3 line now names `prefire_opex_paths.json (prefire_opex_paths.json), prefire.py (prefire.py)` first.
   - **664-lockfile-tracked-1**: OPX-2 ✅ no agent-runtime path · OPX-3 ✅ no never-autonomous path. Identical on both.
   - **665-home-readerror-consent-bundle-1**: OPX-2 ✅ no agent-runtime path · OPX-3 ✅ no never-autonomous path. Identical on both.
   - **668-sched-agent-approval-first-1**: OPX-2 ✅ agent-runtime path(s) `src/lib/agentic-runtime/tools.ts`, `src/lib/agentic-drafts/…` (under its listed id) · OPX-3 ✅ none. Identical on both (it names no `agentic-ops` path).
   - **No new refusal.**
6. The canon's inventory family is `SCP_Agent_Inventory_v0-2`, `-3`, `-4`, `-5`, `-8`. The newest is **v0-8**, not the v0-7 the brief read. Reading the canon file directly was denied by permissions. Prefire's own OPX-2 line on this brief shows that v0-8 lists AP-ORCH, AP-TONI and AP-DAEMON (`… under AP-ORCH, AP-TONI, AP-DAEMON (SCP_Agent_Inventory_v0-8.md)`). So the fail-closed flip refuses nothing that passes today.

### F-A1..F-A3 as built
- **F-A1.** `prefire_opex_paths.json:55-63`: `protected.orchestrator` = `executor/**`, `orchestrator.py`, `prefire.py`, `prefire_opex_paths.json`, `queue_daemon.py`, `admission.py`, in that order. The `protected._orchestrator` note gains the sentence verbatim. `agent_runtime._orchestrator` is byte-identical.
- **F-A2.** `prefire_opex_paths.json:11`: `"src/lib/agentic-ops/**"` is the last `agent_runtime.clinical-mp` entry, after `server/simulation/**`.
- **F-A3.** `prefire.py:775-778` (the no-inventory branch) returns `OpexVerdict(False, "OPX-2 ❌ AGENT-POLICY — ALLOWED FILES name agent-runtime path(s) %s and there is no %s_v*.md in %s, so no policy id can be checked (fails closed; OC-4, D-S7CORE51-20)")`. The docstring (`:758-760`) and the module OPX-2 entry (`:43-46`) now say "No inventory file ⇒ a refusal (fail closed; OC-4, D-S7CORE51-20)". Every other OPX-2 line is byte-identical.
- `git diff 707b2e0 -- prefire_opex_paths.json` adds the five entries and the one note sentence. It removes only the two former last lines, which gain a trailing comma.

### P-A1..P-A7 (new `tests/test_guard_self_protect.py`, 26 cases)
- **On the base** (the file copied into a `git archive` of `707b2e0`): 17 RED, 9 green.
  - RED: P-A1 ×4, P-A2 go ×4, P-A2 OWED ×4, P-A3 ×2, P-A4 refusal, P-A5 exact lists, P-A7.
  - Green on both sides: the P-A4 no-runtime-path control and the P-A5 near-name and positive-match controls.
- **In the worktree: 26/26 GREEN.**
- **P-A6:** the A0 #5 lines above. No new refusal.
- **P-A7:** `python3 prefire.py briefs/662-663-orch-guard-self-npm-frozen-1.md` (exit 0):
  - `OPX-2 ✅ agent-runtime path(s) executor/hooks/npm_frozen.py (executor/**), executor/settings/ai-foundation.json (executor/**), executor/settings/clinical-mp.json (executor/**), executor/settings/collateral.json (executor/**), executor/settings/norra.json (executor/**) (+3 more) under AP-ORCH, AP-TONI, AP-DAEMON (SCP_Agent_Inventory_v0-8.md)`
  - `OPX-3 ✅ never-autonomous path(s) prefire_opex_paths.json (prefire_opex_paths.json), prefire.py (prefire.py), executor/hooks/npm_frozen.py (executor/**), executor/settings/ai-foundation.json (executor/**), executor/settings/clinical-mp.json (executor/**) (+5 more) — George go: '## George go: George 2026-11-11 10:12 "oc-4 amend" (D-S7CORE51-20: the protected-list part of route '`
  - A1 on the same run: `SCP_Kanban row 662 READY (SCP_Kanban_v0-778.md)`. A11: `652-660-orch-prefire-bundle-1 merged on orchestrator/main (707b2e09 …)`. **This brief's own go line passes the check it introduces, so there is no lock-out.**

### Rule #8 — Part A
The search, re-run at the base, hit 5 lines, all in `tests/test_opex_prefire.py`: `:156` (A-1's assertion), `:202` (`test_sim_P3`), `:312` and `:316` (the P4 subset test), and `:323` (A-2). Worktree prefire + json against the base tests (the `tests/test_opex_prefire.py tests/test_prefire.py … tests/test_toni_guards.py` set the brief names) gives **3 reds, 658 passed**:
- **GRANT A-1** (D-S7CORE51-32, "grant all"). `test_P3_no_inventory_warns_and_passes` becomes `test_P3_no_inventory_refuses` (`tests/test_opex_prefire.py:153-158`). Old: `check(b) == []` and the `⚠ … warning, pass` line. New: `check(b) == ["OPX-2 ❌ AGENT-POLICY — … src/daemon/x.ts (src/daemon/**) and there is no SCP_Agent_Inventory_v*.md in <canon>, so no policy id can be checked (fails closed; OC-4, D-S7CORE51-20)"]` and `not opex(b)["OPX-2"].ok`. Nothing else changed.
- **GRANT A-2** (D-S7CORE51-32). `:323` (now `:324`): `assert len(prefire.check(b)) == 2  # OPX-1 + OPX-3 (no inventory: OPX-2 warns)` → `== 3  # OPX-1 + OPX-2 + OPX-3 (no inventory: OPX-2 refuses)`. The rest of the test is word for word.
- **Mechanical-pin line (not named in the brief; see Deviations 1).** `test_sim_P3_control_the_path_list_gains_exactly_the_one_glob` (`:200-204`, added by 652 Part A after the author's `b9cf4c9` measurement) pins the exact `agent_runtime.clinical-mp` list. Old: `[… "server/**/agent*", "server/simulation/**"]`. New: `[… "server/simulation/**", "src/lib/agentic-ops/**"]`. That is one entry appended by F-A2, nothing else. The test name is unchanged.
- **Additions only:**
  - `:175-177` `test_P3_control_every_clinical_mp_agent_path_is_named` gains `"src/lib/agentic-ops/routing.ts"`.
  - `:311-317` `test_P4_control_the_path_lists_are_data_and_carry_the_briefs_paths` gains `"src/lib/agentic-ops/**"` in the clinical-mp subset, and `"prefire.py", "prefire_opex_paths.json", "queue_daemon.py", "admission.py"` in the orchestrator `protected` subset. 652 A's additions are kept.
- **Keep-green unchanged:** every other test in `test_opex_prefire.py` and `test_prefire_typed_go.py` (`test_report_prints_opx_1_2_3_after_the_unchanged_pass_line` and `test_P4_control_no_repo_is_judged_against_every_list` included).

---

## PART B · ORCH-NPM-FROZEN-1 (Kanban 663) — `f025c7b`

### B0 · as built (at `707b2e0`)
1. Install sites.
   - The `git grep -n -i -E "npm (install|i|add|update)\b" -- '*.py' '*.sh' '*.json' '*.yaml' executor config` has **2 hits**:
     - `task_queue/tasks/brief-010a.yaml:12` (the old task text, as the brief says).
     - `tests/test_isolated_deps.py:111`, a comment: `(nm / "upgraded-pkg.txt").write_text("v2\n")    # what the route's `npm install x@2` writes`.

     The second is test-fixture text that nothing runs, so it is not a false premise. It is named here because the author counted one hit.
   - Moved lines:
     - `_install_unit_deps` is at `orchestrator.py:3434-3467` (was `3431-3465`), with `npm ci` at `:3446`.
     - `TONI_ENV_SET` is at `:948` (was `:947`).
     - `BUILD_GATE_CMD = "npx tsc --noEmit && npm run build"` is at `:242` (was `:241`).
     - `sit_cmd = "npm run sit:gate"` is at `:2856` (was `:2853`).
2. `executor/settings/*.json`: six files (ai-foundation, clinical-mp, collateral, norra, orchestrator, yorsie). Each had one PreToolUse entry, matcher `"*"`, running `bash "${TONI_GUARDS_HOME:-$HOME/spectricom-orchestrator}/executor/hooks/kill_switch.sh" || exit 2`. They were identical except the orchestrator's `allow`. `clinical-mp.json` had 28 deny rules: `Read`+`Edit` on 9 credential paths and `Edit` on 5 control paths ×2.
3. `executor/hooks/kill_switch.sh:6-11`: "Exit 2 = the CLI blocks the call and shows stderr to the model (honoured under --dangerously-skip-permissions). Exit 0 = no objection … Fails closed … The settings files run this as `bash "<path>" || exit 2`".
4. npm prefix resolution and npx (read-only). The nvm default is v22.22.1 / npm 10.9.4; v24.14.0 / npm 11.9.0 was also run, with the same results:
   - `npm upd --help` → `Update packages`. `npm shr --help` → `Lock down dependency versions for publication`. `npm t --help` → `Test a package`. `npm run-script --help` → `Run arbitrary package scripts`.
   - From `~/spectricom-clinical-mp`: `npx --no-install tsc --version` → `Version 6.0.3`. `npx --no -- tsc --version` → `Version 6.0.3`. **`npx --no tsc --version` → `10.9.4`** (npm's version; `11.9.0` under npm 11).
   - From `/tmp`: `npx --no-install cowsay hi` → `npm error npx canceled due to missing packages and no YES option: ["cowsay@1.6.0"]`, exit 1.
   - Every premise holds.
5. `fire_toni` is at `orchestrator.py:1042` (was `1041`). `env = _toni_guards_apply(guards, toni_child_env(route_timeout_s))` is at `:1079` (was `:1081`); `toni_guarded_env` is at `:1004-1011`. The pins hold as the brief cites them: `tests/test_toni_guards.py:132-133`, `tests/test_foreground.py:162` and `:175-186`, `tests/test_control_verdict_lines.py:40-52` and `:347-348`.
6. `command -v python3` → `/usr/bin/python3`. `python3 --version` → `Python 3.12.3`.

### G-N1..G-N5 as built
- **G-N1** — new `executor/hooks/npm_frozen.py`: 644 lines, stdlib only, executable, no repo imports. The module docstring names OC-3, D-S7CORE51-18, Gemma's rulings and this route. Pieces:
  - The parser: `_Level` `:105-138`, `_Scanner` `:141-317` and `split_commands` `:320`.
  - Command-word logic with the wrappers: `_skip_wrapper` / `command_index`.
  - `judge_npm` `:404`, with `NPM_ALLOWED` at `:41`.
  - `judge_npx` `:446` and `find_bin` `:430`.
  - `dep_changes` `:377`.
  - `judge_simple` `:514`, which handles cd tracking, `bash|sh|zsh -c`, `eval`, and script files.
  - `fallback` `:584` (item (i)).
  - `main` `:616`, which wraps everything in one `try` (item (j)).

  The four message shapes i–iv are the brief's text. iii is adapted per case, and every variant contains "is not in" and "node_modules/.bin". Timing: about 25 ms per call (10 calls in 0.25 s).
- **G-N2** — each of the six settings files gains exactly one entry after the kill entry: `{"matcher": "Bash", "hooks": [{"type": "command", "command": "f=\"${TONI_GUARDS_HOME:-$HOME/spectricom-orchestrator}/executor/hooks/npm_frozen.py\"; { [ -r \"$f\" ] && command -v python3 >/dev/null; } || { echo \"🛡 npm frozen: the hook could not run (no $f or no python3) — the Bash call is denied (fails closed). Stop and say so in the handback.\" >&2; exit 2; }; python3 \"$f\" || exit 2"}]}`. Checked: with that entry dropped, each file is byte-identical to `707b2e0`.
- **G-N3** — `prefire.py`:
  - Module docstring DEPCHANGE entry: `:51-55`.
  - Constants and `_dep_change_problem`: `:899-933`.
  - `_dependency_lines`: `:935`. It skips fenced lines, and two lines for one package refuse.
  - `dependency_changes(filepath) -> (entries, problems)`: `:958`.
  - The one failure in `check()`: `:1042`.
  - The DEPCHANGE ✅ lines in `report()`, after the OPX lines: `:1070-1072`.

  The go is judged by `_go_text_problem(<words inside the quote> + " " + <after the quote>)`.
- **G-N4** — `orchestrator.py:1082-1094`, inside `fire_toni` only, after the `env is None` return and only when `guards is not None`:
  - It pops any `TONI_DEP_CHANGES`.
  - Good entries and no problems → `env["TONI_DEP_CHANGES"] = json.dumps(deps, separators=(",", ":"))` and `log.info("Dependency change approved for this fire: …")`.
  - Any exception → nothing is set, `log.warning("Dependency change not read (<type>): no install is allowed for this fire")`, and the fire goes on.

  No `🛡` line, no new function, and the command literal is untouched.
- **G-N5** — `README.md:245-251`: one "npm is frozen" paragraph at the end of "Executor guards", with bullets. It covers the allow-list, the npx rule and the `--no` pitfall, the `## Dependency change:` path, `TONI_NPM_FROZEN=off` (needs a daemon restart or a hand-run), the `npx --no-install` convention, the residual, and the `npm ci` live-checkout note.

### P-N1..P-N7 · P-D1..P-D4
- `tests/test_npm_frozen_hook.py` (`pytestmark = guards`) has 202 cases. Every case runs `python3 <worktree>/executor/hooks/npm_frozen.py` against a scratch tree under `tmp_path`. No npm, npx or `claude` is run.
- `tests/test_dependency_change.py` has 46 cases.
- **On the base** (both files in a `git archive` of `707b2e0`): **242 RED, 6 green.**
  - The green controls: P-D3 bad-line, P-D3 guards-off, P-D3 missing brief, and P-D4 json.
  - Two P-N6 cases are green only vacuously: `TONI_NPM_FROZEN=of` and `=0` expect exit 2, and on the base `python3 <missing file>` also exits 2.
- **In the worktree: 248/248 GREEN.**
- Coverage:
  - P-N1: every listed command, the bash-script-file case, and the ≤120-char name.
  - P-N2: every listed command, plus `npm ci 2>&1 | tail -5`, `npm test > /tmp/out.log 2>&1` and `echo hi # npm install`.
  - P-N3: all allowed cases; message ii for `npx tsc --noEmit` and `npx --no tsc --noEmit`; message iii for all 19 listed cases.
  - P-N4: all listed cases, with message iv naming `vitest-axe@0.1.0 (dev): only 'npm install vitest-axe@0.1.0 --save-exact -D' is allowed`.
  - P-N5, P-N6 (input, crash via the module with `split_commands` monkeypatched, off) and P-N7 (all six files, verbatim through `bash -c`: install → 2, `ci` → 0, a bash-only `PATH` → "could not run", symlink removed → "could not run").
  - P-D1 (3 good lines; 23 bad shapes, each refused with its reason; duplicates; fence), P-D2, P-D3 (all five cases from the brief, plus a bad line, which sets nothing), P-D4.

### Rule #8 — Part B
- The search now hits more test files than the author's `b9cf4c9` list: 29 files, mostly via the `🛡` literal.
- **No existing assertion was changed.** Every keep-green the brief names is green unchanged, and so is every other file that touches `fire_toni` or prefire:
  - In the gate run: `test_toni_guards.py` (P1 env equality `:132-133`, TONI_GUARDS=off byte-for-byte, all P2 / P3 pins incl. `_hook_commands` matcher `"*"` only, `:403-414` verbatim), `test_foreground.py:157-164` and `:175-186`, `test_control_verdict_lines.py::test_source_guard_C_is_pinned`, and `test_opex_prefire.py::test_rename_no_output_line_carries_a12_a13_or_a14`.
  - `test_timeout_hold`, `test_orch_lane`, `test_stale_base`, `test_executor_auth`: 134 passed.
  - `test_admission_parser`, `test_baseline_reuse_1`, `test_gate_cost`, `test_handback_guard`, `test_merge_conflict`, `test_prelist`, `test_regate_gates_only`, `test_route_ref_integrity`, `test_unit_baseline_gate`, `test_unit_gate_wording`, `test_yorsie_safety`: 522 passed.

---

## Gates (targeted, foreground, worktree root)
- `/home/gkassa/spectricom-orchestrator/venv/bin/python -m pytest -q` on the brief's 15 files (`test_opex_prefire`, `test_prefire`, `test_prefire_typed_go`, `test_guard_self_protect`, `test_toni_guards`, `test_npm_frozen_hook`, `test_dependency_change`, `test_foreground`, `test_control_verdict_lines`, `test_bg_ceiling`, `test_control_scope`, `test_depends_on`, `test_depends_product`, `test_runtime_parse`, `test_isolated_deps`) → **1045 passed in 41.62s**.
- Neighbours (above): 134 + 522 passed.
- `python3 -m py_compile prefire.py orchestrator.py executor/hooks/npm_frozen.py` → ok.
- `json.load` of `prefire_opex_paths.json` and all six `executor/settings/*.json` → ok.
- The full `tests/` suite was not run (Test scope: targeted). No merge-base measurement was run.

## Preflight (`python3 ~/spectricom-orchestrator/orchestrator.py preflight --repo orchestrator`)
```
  SIT: 0 file(s) — pass — orchestrator's gate has no SIT leg
  unit: ? file(s) — not computed — the gate runs the FULL unit suite — related selection not available for orchestrator — `pytest -q tests/` is not a vitest run
🧪 Preflight (executor): 0 SIT files / ? unit files — fail (not computed)
   JSON: /home/gkassa/spectricom-orchestrator/state/preflight/orch-orch-662-663-orch-guard-self-npm-frozen-1.json
```
Exit 3. The "fail" is "not computed": the orchestrator has no related-file selection, so the pre-merge gate runs the full unit suite (the brief's GATE PRE-LIST says the same). No test failed. Under rule #8 and the STOP rules this is not a red. Running `pytest -q tests/` here would break Test scope: targeted.

## Deviations (named, not silently taken)
1. **A third Part A rule #8 edit, under the standard mechanical-pin line.** `test_sim_P3_control_the_path_list_gains_exactly_the_one_glob` came with 652 Part A, after the author measured "exactly two reds" at `b9cf4c9`. It pins the exact clinical-mp list, so F-A2's one new glob turns it red. The only change is that glob appended to its expected list. This is the allow-list pin class the brief's own GRANT A-2 note calls mechanical. If George or Gemma read this as STOP (c) instead, reverting that one line and the F-A2 entry restores the base.
2. **The hook is stricter than the brief's letter in these places.** Each follows bash's real behaviour, and each is tested:
   - A heredoc with an **unquoted** delimiter has its `$(…)` / backtick spans judged, because bash expands them, as in a double-quoted string. Quoted-delimiter bodies are dropped, as the brief says. Claude Code's `<<'EOF'` commit shape passes.
   - `)` is also a command position in the fallback scan, so `case x in a) npm i;; esac` (unparsable) is refused.
   - `npm audit -f` (npm's alias for `--force`) is refused.
   - A script file passed to `source` / `.` is judged like `bash <file>`.
   - A here-string fed to a shell (`bash <<< "npm i"`) is judged.
   - `env -S '<cmd>'` is split.
   - Shell reserved words are skipped before the command word: `{`, `if`, `then` and the rest.
   - `TONI_NPM_FROZEN=off` is read before stdin, so "off allows everything" holds even for input the hook cannot read.
3. **README residual: two more entries, found by probing.** A command string piped into a shell (`echo 'npm install' | bash`, exit 0), and a command word built at run time (`$x install`).
4. The newest agent inventory is v0-8, not v0-7 (A0 #6). The live queue corpus differs from the author's list (A0 #5). B0 #1 has a second, harmless grep hit.

## R-items
- **(R-a)** The next route after merge is the first under the new lists and the hook. Queued briefs whose ALLOWED FILES name a newly protected path (`prefire.py`, `prefire_opex_paths.json`, `queue_daemon.py`, `admission.py`) or `src/lib/agentic-ops/**`: only this route's own `queue/662-663-…`, which names `prefire.py` and `prefire_opex_paths.json` and carries its go. `664`, `665` and `668` name none (A0 #5). Under the hook, briefs and gate lines that write a bare `npx tsc` / `npx vitest` cost one refused call and a re-run each. Those are 664 (which already writes `npx --no-install`), 665 and 668, and they need checking: OPEN ITEMS (f).
- **(R-b)** Prefix-resolution pastes: B0 #4 above. `upd` = update and `shr` = shrinkwrap on npm 10.9.4 and 11.9.0.
- **(R-c)** The Bash residual, as written in the README (`README.md:250`). The hook does not see:
  - `npm run <script>` whose package script installs;
  - a script file the hook cannot read;
  - a command string piped into a shell (`echo '…' | bash`);
  - a command word built at run time (`$x install`);
  - `node <npm-cli.js> …`;
  - an alias or function defined in the same command;
  - `npm ci` in a scratch directory whose `package.json` and lockfile the executor wrote (scripts stay off, but `npx --no-install` there would then run what it installed);
  - a forged `## Dependency change:` line in a queued brief, until route 621's write-deny on `queue/`.

  All of these stand until route 620's sandbox is the default. `npm ci` stays allowed in clinical-mp's single-stream live checkout (handed to routes 620 and 621).
- **(R-d)** No daemon restart is needed for either part (OPEN ITEMS (b)). Each `orchestrator.py run` imports prefire fresh, and each fire reads the settings and hooks. A restart in a quiet window keeps the daemon's in-process prefire in step. Run `python3 prefire.py ~/spectricom-orchestrator/queue/*.md` right after the merge.
