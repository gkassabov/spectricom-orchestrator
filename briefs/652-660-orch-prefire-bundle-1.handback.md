# HANDBACK — ORCH-PREFIRE-BUNDLE-1 (Kanban 652, 658, 659, 660) · batch s7core51-orch-prefire-bundle-1

**Status: all four parts done, each its own commit, predicates green. No STOP triggered.**
Route worktree `/tmp/orch-fire-20261111-123612`, branch `orch-orch-652-660-orch-prefire-bundle-1`, base `b9cf4c9`.

| Part | Commit | Files (diff stat) |
|---|---|---|
| A — OPX-2 covers `server/simulation/**` (652) | `bfe00e7` | `prefire_opex_paths.json` +2/−1 · `tests/test_opex_prefire.py` +36/−2 |
| B — a placeholder in a George go line is no go (658) | `0640837` | `prefire.py` +89/−10 · new `tests/test_prefire_typed_go.py` +154 |
| C — the executor's login is checked before a route starts (659) | `ce776e0` | new `executor_auth.py` +186 · `orchestrator.py` +59/−3 · `queue_daemon.py` +53/−7 · `tests/conftest.py` +17 · `tests/test_control_verdict_lines.py` +2 · `tests/test_timeout_hold.py` +2/−2 · new `tests/test_executor_auth.py` +477 |
| D — the unit gate's verdict line says above / equal to / below truthfully (660) | `edff123` | `orchestrator.py` +25/−8 · new `tests/test_unit_gate_wording.py` +68 |

Tests: targeted gate list **1076 passed**; Part C keep-green set (every `run_loop` / `run_batch` driver) **1203 passed**; unit-gate detail neighbours **210 passed**; `py_compile` ok on all four modules; `prefire_opex_paths.json` loads. Full `tests/` not run (header `Test scope: targeted`). Preflight: **exit 3, `not computed`**. The unit leg can't select related tests for orchestrator's pytest suite. Nothing failed (see the end of this file).

---

## X0 · the worktree
1. `git rev-parse HEAD` → `b9cf4c9d4ea70c2258d558a414f6a8955fbc7a9e`; `git log --oneline -3` → `b9cf4c9 handback: 341i1-…`, `f2953e8 feat(orch): the unit gate names the files and tests that fail …`, `67cedf4 handback: 341a4-…`. At `b9cf4c9`.
2. `…/venv/bin/python -c "import sys; sys.path.insert(0, '.'); import prefire, orchestrator, queue_daemon; print(...)"` →
   `/tmp/orch-fire-20261111-123612/prefire.py /tmp/orch-fire-20261111-123612/orchestrator.py /tmp/orch-fire-20261111-123612/queue_daemon.py`. All three are the worktree's.
3. `grep -l "repo=orchestrator" ~/spectricom-orchestrator/queue/*.md` (at fire) → `queue/652-660-orch-prefire-bundle-1.md` only (this route's own copy). **Later in the route:** `queue/662-663-orch-guard-self-npm-frozen-1.md` (`repo=orchestrator`, mtime 12:36:54) appeared after this grep ran. It carries `## Depends-on: 652-660-orch-prefire-bundle-1` (`:16`) and says it edits `prefire.py` / `prefire_opex_paths.json` / `queue_daemon.py` after this merge, so it is sequenced after this route. Not a STOP.

---

## PART A — OPX-2 covers `server/simulation/**` (Kanban 652, ORCH-PREFIRE-SIM-PATHS-1) · `bfe00e7`

### A0 · as built
1. `prefire_opex_paths.json:5-10` at `b9cf4c9` — `agent_runtime.clinical-mp`: `"src/lib/agentic-runtime/**"`, `"src/daemon/**"`, `"src/lib/agentic-drafts/**"`, `"server/**/agent*"`. ✓
2. `_about` (`:2`): "a trailing '/**' the directory itself and everything under it … matched case-insensitively against each path". `_glob_rx` `prefire.py:658-670` (`**/` → `(?:.*/)?`, trailing `/**` → `(?:/.*)?`, `*` → `[^/]*`, `?` → `[^/]`, `re.IGNORECASE`); `path_matches` `:673-685` (a pattern with no `/` matches any one name; else the path or a directory it sits under; a glob path matches when it reaches into the tree). ✓
3. Gap on HEAD (scratch brief under a temp dir, ALLOWED FILES `server/simulation/engine.ts`, no `## Agent policy:`):
   `OPX-2 ✅ no agent-runtime path in ALLOWED FILES` ✓ (the gap).
4. Matcher table on HEAD (`prefire.path_matches` over `opex_paths("agent_runtime","clinical-mp")`, read-only, scratch script outside the repo). **Identical to the brief's table:** every `server/simulation/…` row and the directory → `none`; `server/routes/agent-runner.ts`, `server/agents/x.ts` → `['server/**/agent*']`; `server/routes/sim-agent.ts` → `none`; `src/lib/simulation/engine/run.ts`, `src/lib/simulation/x.ts`, `server/__tests__/simulation/run-writer.test.ts`, `server/router.ts`, `server/index.ts`, `scripts/sim-eos.ts` → `none`.
5. `git grep -n "agent_runtime\|OPEX_PATHS\|prefire_opex_paths" -- tests` → `tests/test_opex_prefire.py:269, :276, :278, :279, :331` (one file, as stated).
6. `grep -l "server/simulation" ~/spectricom-orchestrator/queue/*.md` → `queue/652-660-orch-prefire-bundle-1.md` only. That is this brief, which names the path in its own text and is `repo=orchestrator`. No clinical-mp brief would be refused.

### F1 as built
`prefire_opex_paths.json:9-10` — `"server/**/agent*",` + `"server/simulation/**"`. Nothing else changed. `git diff b9cf4c9 -- prefire_opex_paths.json` = one added line plus the comma on `:9`.
After the change, the scratch brief gives:
`OPX-2 ❌ AGENT-POLICY — ALLOWED FILES name agent-runtime path(s) server/simulation/engine.ts (server/simulation/**) and the brief cites no Agent Policy id that SCP_Agent_Inventory_v0-7.md lists (AP-CAREMGR, AP-DAEMON, AP-GEMMA, AP-ORCH, AP-SCRIBE, AP-SIM-ENGINE, AP-SYNTH, AP-TONI). …`
(Observation: the live canon `SCP_Agent_Inventory_v0-7.md` **already lists `AP-SIM-ENGINE`**, so a T-SIM brief citing it passes OPX-2 today.)

### Predicates (RED = HEAD's JSON swapped back in temporarily, same tests)
- **P1** `test_sim_P1_a_simulation_engine_path_needs_a_policy_id[engine.ts | server/simulation/** | plan/read-current-plan.ts]`: RED 3 failed → GREEN. Each asserts `OPX-2 ❌` naming `<path> (server/simulation/**)`.
- **P2** `test_sim_P2_the_cited_id_must_be_in_the_newest_inventory[AP-SIM-ENGINE-True | AP-TONI-False]`: the AP-TONI case RED → GREEN. The AP-SIM-ENGINE case passes on HEAD too, because HEAD names no agent path there.
- **P3** `test_sim_P3_control_the_path_list_gains_exactly_the_one_glob` (exact list, in order): RED → GREEN. The diff is the one line above.
- **P4** `test_sim_P4_control_the_new_glob_is_not_widened[agent-runner.ts→[server/**/agent*] | src/lib/simulation/engine/run.ts→[] | server/__tests__/…→[] | server/router.ts→[]]`: green before and after.
- File totals: RED **7 failed / 100 passed** → GREEN **107 passed** (96 HEAD + 11 new).

### Rule #8 edits (George 2026-11-10 19:05 go)
- `tests/test_opex_prefire.py:175-176` `test_P3_control_every_clinical_mp_agent_path_is_named`. Old: `[…, "server/routes/agent-runner.ts", "server/agents/x.ts", "src/daemon/**"]`. New: the same five plus `"server/simulation/engine.ts"`.
- `tests/test_opex_prefire.py:277-278` (now `:311-312`) `test_P4_control_the_path_lists_are_data_and_carry_the_briefs_paths`. Old: `{…, "server/**/agent*"} <= set(…clinical-mp)`. New: `{…, "server/**/agent*", "server/simulation/**"} <= …`.
- New functions `test_sim_P1..P4`, placed after `:179` using `brief()` / `opex()` / `INVENTORY`. Every other test in the file is unedited and green.

---

## PART B — a placeholder in a George go line is no go (Kanban 658, ORCH-PREFIRE-GO-TYPED-1, D-S7CORE50-27) · `0640837`

### B0 · as built
1. `prefire.py:532` `_GEORGE_GO_LINE = re.compile(r'^##\s*George go\s*:[ \t]*(?P<text>\S.*)$', …)`; `:533` `_GO_HEADERS`; `:534` `_GEORGE_GO = re.compile(r'George[^\n]{0,80}\b(go|GO|agreed|Agree)\b')`. ✓
2. `george_go` `:773-784` returns the first go line whole, else the first `_GEORGE_GO` match on a `## Briefs:` / `## Spec reference:` line. `check_george_go` `:787-803` passes on any non-None return. Docstring OPX-3 entry `:46-48`. ✓
3. Defect on HEAD (scratch briefs, ALLOWED FILES `orchestrator.py`, `repo=orchestrator`):
   ```
   OPX-3 ✅ never-autonomous path(s) orchestrator.py (orchestrator.py) — George go: '## George go: OWED — George's go needed before enqueue'
   OPX-3 ✅ never-autonomous path(s) orchestrator.py (orchestrator.py) — George go: '## George go: pending'
   OPX-3 ✅ never-autonomous path(s) orchestrator.py (orchestrator.py) — George go: '## George go: TBD'
   OPX-3 ✅ never-autonomous path(s) orchestrator.py (orchestrator.py) — George go: 'George go'
   ```
   ✓ (the fourth is `## Briefs: 1 (George go OWED)`).
4. `git grep -n "george_go\|_GEORGE_GO\|check_george_go" -- '*.py'` → `prefire.py:532, :534, :773, :777, :781, :787, :798, :811`. Tests: `tests/test_opex_prefire.py:224, :230` (function names; the go tests sit at `:189-215` pre-Part-A). ✓
5. **Corpus (P-B6)**, read-only over `~/spectricom-orchestrator/queue/{done,failed,held}/*.md` + `queue/*.md`: **614 briefs** (the verifier counted 604, before the latest enqueues), **218 `## George go:` lines (189 distinct)**, **244 briefs where HEAD's `george_go` finds a go**, of which **B1 refuses 2**:
   - `done/487-careplans-layout-1.md`: `'## George go: 2026-10-26 18:54 (George, chat: Care Plans fix tonight) — includes'` (no ruling id, go word or timed quote)
   - `done/487-careplans-layout-1-refire.md`: the same line, same reason.
   Exactly the two 487 briefs (the P-B7 shape). `341cfg1`, `341h2r` and `282c` pass. No brief passes under B1 that HEAD refused. **No brief now in `queue/`** (pending) is refused. Pending briefs that name a protected path, all ✅ under B1: `585-606-657-refire-bundle-1.md`, `605-allergy-unchosen-defaults-1.md`, `652-660-orch-prefire-bundle-1.md` (this one), `662-663-orch-guard-self-npm-frozen-1.md`.

### G-B1..G-B5 as built (`prefire.py`)
- **G-B1** `george_go_verdict` `:847` → `(go_text, None)` | `(None, why_not)`, and `(None, None)` when the brief carries no go text at all. That third shape is how `check_george_go` keeps today's no-go refusal byte-identical. `george_go` `:855` = `george_go_verdict(filepath)[0]`, same signature, same text for every go it accepts. The one judge is `_judge_george_go` `:826`, which also returns the judged text for the refusal line.
- **G-B2** `_GEORGE_GO_LINE` `:534` is now `^##\s*George go\s*:(?P<text>.*)$` (an empty line is judged). Every go line must pass; the first that fails is named. With no go line, the fallback is judged on its clause: `_go_clause` `:810`, which spans from the match start to the first `;` / `**` / `. ` after the match, outside quoted or backtick spans. A `)` ends nothing, and quote state is tracked from the match start, so a match that ends inside George's quote is handled. The returned text is still `_GEORGE_GO`'s match.
- **G-B3** `_go_text_problem` `:788`, constants `:537-551` (`GO_PLACEHOLDERS`, `GO_EMPTY_ALONE`, `GO_WORDS`, `_GO_PLACEHOLDER` (multi-word phrases match any whitespace, longest first), `_GO_TEMPLATE`, `_GO_QUOTED`, `_GO_SPAN`, `_GO_RULING_ID`, `_GO_WORD`, `_GO_TIME`). Placeholders and template markers are scanned with double-quoted and backtick spans removed. Go evidence is a ruling id, a go word, or a time together with a quoted span, anywhere in the text. One reading choice: `?`, `…`, `...`, `n/a`, `none`, `-` alone report as `placeholder '<as written>'`, and only blank text reports `empty`. The four `why_not` forms are exactly as specified.
- **G-B4** `check_george_go` `:862`: the new refusal is `:876-879`, `OPX-3 ❌ NEVER-AUTONOMOUS — ALLOWED FILES name protected path(s) <paths> and the brief's George go is not a go: '<text ≤ 80>' (<why_not>) — any non-go text reads as no go (D-S7CORE50-27)`. The quoted text is the whole go line for a `## George go:` line, and the judged clause for the fallback. The no-go refusal and the no-protected-path pass are unchanged.
- **G-B5** docstring `:46-50`: one added sentence (two lines). `prefire_opex_paths.json` was not touched.

### Predicates (`tests/test_prefire_typed_go.py`; RED = HEAD's `prefire.py` swapped in temporarily)
- **P-B1** OWED → `(placeholder 'OWED')`, the line is in `prefire.check(b)`, and `george_go` is None: RED → GREEN.
- **P-B2** `pending`, `TBD`, `TBC`, `TODO — ask George`, `awaiting George`, `not yet given`, `to be asked at EOS`, `<George's words>`, `{go}`, `?`, `n/a`, and the empty line, each with its exact refusal line: RED 12 → GREEN. The empty line was already refused on HEAD (`not ok`); it is RED only on the new refusal text.
- **P-B3** `## Briefs: 1 (George go OWED)` and `## Briefs: 1 (George go) OWED` → `(placeholder 'OWED')`: RED 2 → GREEN.
- **P-B4** a good go line followed by `## George go: OWED (Part B)`: refused naming the second line. RED → GREEN.
- **P-B5** controls, **green on HEAD and after**: `10-23 18:08 "agree"`; `D-S7CORE50-27`; `10-23 21:1x EOS "Evaluate OpenShell"`; `07:00 "656 FL-1 preliminary pending Dr K co-sign"`; `George T0 … George 13:47 agreed`; this bundle's own `:14` go line, **verbatim**; `341cfg1:14`, **verbatim**; `08:53 "go h2" (digest \`…rulings-owed-…\`)`; the `/tmp/orch-fire-<ts>` / `server/simulation/{loop,route}.ts` code-span line; `282c:11`'s `## Spec reference:` line, **verbatim** (fallback); `## Briefs: 1 (George go 10-23)`, whose pass line still ends `— George go: 'George go'`; OWED with `src/components/x.tsx` → `OPX-3 ✅ no never-autonomous path in ALLOWED FILES`; the no-go refusal text byte-identical. The two `george_go_verdict`-API tests are RED on HEAD only because the function is new.
- **P-B6** corpus: B0 #5 above.
- **P-B7** `487-careplans-layout-1.md:14`, verbatim → `(no ruling id, go word or timed quote)`: RED → GREEN. With `"go"` after the time → ✅.
- File totals: RED **23 failed / 15 passed** → GREEN **38 passed**. `tests/test_opex_prefire.py` + `tests/test_prefire.py` + the new file: **219 passed**.

### Rule #8 — Part B
No edits. Every `git grep -n "george_go\|George go\|OPX-3\|GEORGE_GO" -- tests` hit (`tests/test_opex_prefire.py`, `tests/test_prefire.py:266`) stays green unchanged.

---

## PART C — the executor's login is checked before a route starts (Kanban 659, ORCH-EXECUTOR-AUTH-PROBE-1, L-382) · `ce776e0`

### C0 · as built
1. `logs/clinical-mp/toni-602a-approvals-holding-1-rerun-20261111-065036.log` (13 lines). Its executor output (`:9`) is `Failed to authenticate: OAuth session expired and could not be refreshed`, then `Finished: 2026-11-11T06:50:39.759575`, `Exit: 1` (3 s after `Started: …06:50:36`). `logs/orch-20261111-064615.log:19-28`: `:19-22` guards / bg-wait-ceiling / Log lines; `:23` `Toni finished: exit 1`; `:24` `⛔ INCOMPLETE(executor-error) — executor exit 1 (the executor did not exit 0) with work on the tree; no gate run, nothing merged. …`; `:25` `🛡 executor-exit: HOLD — INCOMPLETE(executor-error): exit 1 with work on orch-mp-602a-…`; `:26` `📦 Committed: …`; `:27` `⛔ INCOMPLETE(executor-error) — main NOT merged …`; `:28` `🏁 FINAL STATUS: incomplete | gate: not run (INCOMPLETE(executor-error) — exit 1)`. ✓
2. Daemon at `b9cf4c9`: `killed = read_kill()` `queue_daemon.py:1475`, admission `:1485`, `claim = admission.claim_path(ORCH_DIR)` `:1489`, `[QUEUE] Firing:` `:1495`, command `:1497-1502`, failure → `failed/` + `_mark_paused(f"stop-on-failure:…")` `:1541-1546`; `_mark_paused` `:891`, `_write_pause_notice` `:902`, `pause_notice_text` `:133`, `resume_command` `:125`; `_wait_for_admission` `:1651`; `_wait_for_unkill` `:1666`. Orchestrator: `run_batch` `orchestrator.py:6479`, prefire `:6481-6487`, re-gate `:6489-6495`, `ISOLATED_DEPS` `:6497`, meta-fire worktree `:6505-6546`; `fire_toni` `:1041-1124`; AUTH GUARD `:67-82`; `prefire_timeout` `:719-727`. ✓
3. **`env -u ANTHROPIC_API_KEY claude auth status --json`** (CLI `2.1.322`, run once, read-only, account fields redacted in the pipe): exit 0,
   `{"loggedIn": true, "authMethod": "claude.ai", "apiProvider": "firstParty", "analyticsDisabled": false, "projectsDirectory": "…/.claude/projects", "configDirectory": "…/.claude", "loginExpiresAt": "2026-12-10T03:32:12.098Z", "email": "<redacted>", "orgId": "<redacted>", "orgName": "<redacted>", "subscriptionType": "max", "storedClaudeAiLogin": true, "planTier": "max_20x"}`. Every expected key is present, plus `analyticsDisabled`, `projectsDirectory`, `configDirectory`, and `loggedIn` is boolean. ✓
   **The live probe, once** (a script file in a scratch dir outside the repo, run from a fresh `mktemp -d`, exactly the G-C1 argv with `--setting-sources local`): **exit 0, 4.0 s**, stderr empty, tempdir removed, `is_error: False`, `subtype: success`. JSON keys: `api_error_status, credential_expires_at, duration_api_ms, duration_ms, fast_mode_disabled_reason, fast_mode_state, first_content_frame_ms, is_error, modelUsage, num_turns, permission_denials, queued_turn_count, result, result_index, safety_stops, session_id, stop_reason, subagent_stats, subtype, terminal_reason, time_to_request_ms, total_cost_usd, ttft_ms, ttft_stream_ms, type, usage, uuid`. `local` authenticates and every flag was accepted. No login, logout or auth write was made.
4. `_executor_exit_hold` `orchestrator.py:6362-6379` (verdict `:6375`, error `:6377-6379`); call `:6731-6732`; verdict constants `:1168-1173`. ✓
5. Not measured here (R-c): whether `auth status` reports `loggedIn: false` for a refresh token the server has already refused.

### G-C1..G-C5 as built
- **G-C1** `executor_auth.py` (new, 186 lines): `PROBE_VAR`, `CHECKED_VAR`, `CHECKED_MAX_AGE_S=600`, `STATUS_TIMEOUT_S=30`, `LIVE_TIMEOUT_S=60`, `LIVE_PROMPT`, `LIVE_SETTING_SOURCES="local"`, `AUTH_FAILURE_LINES`, `AUTH_FAILURE_MAX_LINES=5`, `AUTH_FIX`, `ENV_FIX` (`:27-39`); `AuthProbe` `:45`; `probe_off` `:52`; `probe` `:101`; `checked_by_daemon` `:169`; `auth_failure_line` `:180`. Helpers: `fix_for`, `iso_z`, `_parse_iso`. Step 1 reads only `loggedIn`, `loginExpiresAt`, `authMethod`, `subscriptionType`; email, orgId and orgName are never read into a detail. Step 2 is one call in a `tempfile.TemporaryDirectory()` cwd. A rejected flag is named only when stderr carries one of the probe's own flags with `unknown option` / `invalid` / `error: option`; any other non-zero exit is `exit <n>: <first stderr line>`. Both are `environment`, and neither is retried.
- **G-C2** `queue_daemon.py`: `fire, auth_checked = self._executor_auth_step(next_batch, batch_name, claim)` at `:1499`, after the admission print (after the claim) and before the route wall and `Firing:`. The step itself is a helper method `_executor_auth_step` `:1677`, kept out of the loop body. It prints OFF on every fire, skips the probe for a re-gate brief, prints CLEAN on a change of verdict, and on BLOCKED does `admission.release(claim)`, then `current_batch = None`, `_mark_paused(reason, say=False, detail=…)` and `_save_state()` under the lock, and prints one `[QUEUE] 🛡 executor-auth: BLOCKED — …` line. `EXECUTOR_AUTH_CHECKED=<ISO Z>` goes into the command at `:1509`, *before* `ORCH_ADMISSION_CLAIM=` so that `tests/test_capacity.py:410`'s `CLAIM_ENV=<claim> python3 -u orchestrator.py run` stays contiguous and unedited. `_mark_paused` `:893` and `_write_pause_notice` gain an optional `detail` (key `detail` only when given, `:916`). `pause_notice_text` `:138` appends ` — <detail>` only when the notice has one. Imports: `executor_auth`, and `timezone` from datetime.
- **G-C3** `orchestrator.py`: `_executor_auth_check` `:6519`, called at `:6566` in an `else:` of the re-gate branch (so only when `REGATE is None`), before `ISOLATED_DEPS`. It emits SKIPPED (`--force`), OFF, `CLEAN — checked by the queue daemon at …`, `CLEAN — <detail>`, or BLOCKED with `Result(FAILED, exit_code=2, briefs=0, error=…)`. `within_s = prefire_timeout(batch_file)[0] * 60`. `import executor_auth` is at `:45`.
- **G-C4** `INCOMPLETE_EXECUTOR_AUTH_VERDICT` `:1176`. `_executor_exit_hold(ec, branch, out_log=None)` `:6382`: when ec is not 0 and not −1, it reads the executor output between fire_toni's first and last 60-`=` rules. A sign-in failure line there is the auth branch (`:6404`), with the error and the `🛡 executor-exit: HOLD — INCOMPLETE(executor-auth): exit <ec> on <branch>` line as specified. Every other case is byte-identical. The call site at `:6804` passes `out_log`.
- **G-C5** `tests/conftest.py`: the `executor_auth` marker (`:37`) and the autouse `_executor_auth_ok` (`:59`), which always delenvs `EXECUTOR_AUTH_CHECKED` / `EXECUTOR_AUTH_PROBE` and stubs `executor_auth.probe` unless the test is marked. Every caller goes through `executor_auth.probe(...)`.

### Predicates (`tests/test_executor_auth.py`, `pytestmark = executor_auth`; executor_auth's `subprocess` / `shutil` replaced by a recorder namespace, so no global patch and no real CLI)
- **P-C1 (a)–(i)**: (a) ok, the detail starts `logged in (claude.ai, max); login expires <ISO Z>; live call ok in`, one live call, and none of `x@example.test` / `org-test` / `Org Test` / the reply in the detail, stdout or log. (b)/(c) auth with no live call. (d) five status-step causes → environment, no live call. (e) 602a's line → auth, quoted. (f) live timeout / `getaddrinfo ENOTFOUND` → `BLOCKED(environment) … not a login problem`. (g) `— expires inside this route's 60 min`, plus a control. (h) no `ANTHROPIC_API_KEY` in either call, the exact live argv, and a cwd that is empty, not under any `.git`, and gone afterwards. (i) `--setting-sources` / `--tools` / `--strict-mcp-config` rejected → environment naming the flag, one live call. Also `probe_off` any case, and `checked_by_daemon` fresh / 20-min / future / junk.
- **P-C2** daemon (subprocess-stubbed probe, real admission and claim):
  - A refused refresh → no `_run_route`, no claim left, the brief still in `queue/` and not in `failed/`, paused, `paused_reason` starting with the exact executor-auth text, a notice `detail` holding the quoted line + `AUTH_FIX`, `pause_notice_text` ending ` — <detail>`, the `resume_command` round-tripping via `shlex.split`, and one BLOCKED line.
  - A live timeout → `executor-check:<name> — BLOCKED(environment)`.
  - A later poll with the probe healed: still paused, still one live call, nothing fired.
  - Ok → fires, the command carries `EXECUTOR_AUTH_CHECKED=`, and the `CLAIM_ENV=… python3 -u orchestrator.py run` adjacency holds.
  - Admission no ×3 then yes → exactly one live call, made while the claim file exists.
  - A refusal releases the claim. A re-gate brief → no CLI call. `EXECUTOR_AUTH_PROBE=Off` → no CLI call and the OFF line. A notice without `detail` → HEAD's text exactly.
- **P-C3** `run_batch`:
  - auth / environment → `FAILED`, exit 2, the error starts `executor-auth: ` / `BLOCKED(environment) — executor check: `, and none of `_run_batch_inner`, `_create_route_worktree` or `fire_toni` is called. Exactly one `🛡 executor-auth:` line, which is the BLOCKED one.
  - Ok → one CLEAN line, the route proceeds, and `within_s` = prefire's minutes × 60.
  - Fresh `EXECUTOR_AUTH_CHECKED` → no probe, plus the daemon CLEAN line. Twenty minutes old or `junk` → probed. `--force` → SKIPPED. Off → OFF. A re-gate → no line.
- **P-C4**: 602a's log shape → `INCOMPLETE(executor-auth)`, quoting the line, naming `/login`, without "with work on the tree". 40 ordinary lines that include `OAuth session expired` → `INCOMPLETE(executor-error)` with an error byte-identical to the `out_log=None` call. `out_log=None` → HEAD's text. ec −1 with 602a's log → `INCOMPLETE(timeout)`.
- **P-C5**: `test_control_verdict_lines.py` green with C naming `executor-auth` (42 passed with test_timeout_hold), and every existing test green under the stub.
- **RED**, against a `git archive` export of `0640837` (no worktree, no stash): (1) as-is → collection error (`executor_auth` absent). (2) With only the new module and conftest copied in → **19 failed / 27 passed**; the failures are every P-C2/P-C3/P-C4 case that needs the new code. GREEN: **46 passed**.

### Rule #8 edits — Part C (George 2026-11-11 08:03 / 08:09)
- `tests/test_timeout_hold.py:201-205` `test_verdicts_are_distinct`. Old: the set of 5 constants + GateOutcome, `len(vs) == 8`. New: `+ orchestrator.INCOMPLETE_EXECUTOR_AUTH_VERDICT`, `len(vs) == 9`. The `(timeout, executor-error)` tuple assertion is unchanged.
- `tests/test_control_verdict_lines.py:51` `C`: added `# ORCH-EXECUTOR-AUTH-PROBE-1: a ninth control, one line per fire` + `"executor-auth": "_executor_auth_check",`. `:297-302` is unchanged and green.
- `tests/conftest.py`: the `executor_auth` marker plus `_executor_auth_ok`, a harness edit that changes no assertion (and one docstring paragraph).
- Keep-green re-grep `git grep -ln "_run_route\|\.run_loop\|QueueDaemon(\|run_batch(" -- tests` → `test_capacity`, `test_config_truth`, `test_control_scope`, `test_depends_on`, `test_executor_default`, `test_gate_cost`, `test_handback_guard`, `test_orch_lane`, `test_prefire`, `test_queue_gate_log`, `test_queue_pause`, `test_queue_retire`, `test_regate_gates_only`, `test_stale_base`, `test_timeout_hold`, `test_toni_guards`, `test_unit_baseline_gate`, `test_yorsie_safety` (plus a fixture log). All ran unedited with `test_control_verdict_lines` + `test_executor_auth`: **1203 passed**.
  - One transient red, noted: before `executor_auth.py` was `git add`ed, 15 `test_orch_lane` cases (P3 verify, a copied-install subprocess) failed with `ModuleNotFoundError: executor_auth`. Their `home` fixture copies only *tracked* top-level `.py` files (`:397-401`). Staging the new module fixed it with no test edit (61 passed), and it is committed in `ce776e0`.
  - The subprocess-spawning `orchestrator.py run` tests (`test_capacity.py:266`, `test_executor_default.py:227,231`) exit at admission or at the missing brief, before `run_batch`, so none reaches the real probe.

---

## PART D — the unit gate's verdict line says above / equal to / below truthfully (Kanban 660, ORCH-UNIT-GATE-WORDING-1, L-384) · `edff123`

### D0 · as built
1. `orchestrator.py:4946` (HEAD): `verdict = ("equal to" if branch_run.failures == baseline_run.failures else "below")`, used by the no-new-file detail `:4947-4948` and the flaky detail `:4952-4959`. ✓
2. Live lines (`grep -n "UNIT BASELINE GATE PASSED"`), quoted as evidence of the old wording:
   - `logs/orch-20261110-214112.log:76` — `… — 6 failures, below the merge-base baseline of 3 — newly-failing file(s) confirmed FLAKY …` (6 vs 3; the word was wrong, and the fixed line reads `above`)
   - `logs/orch-20261111-042625.log:65` — `5 failures, below … of 3` (5 vs 3, same defect)
   - `logs/orch-20261109-043702.log:49` — `5 failures, below … of 3` (5 vs 3, same defect)
3. `count_comparable` `:3083` (now `:3086`). `:4949-4951` drops the comparison for the no-new-file detail, but the flaky detail overwrote it with one anyway. ✓
4. `collection` `:3087-3104`, ` (derived)` at `:3101-3103`. ✓

### G-D1..G-D3 as built (`orchestrator.py`)
- **G-D1** `_count_word` `:4706` (`below` / `equal to` / `above`), used at `:4962` by both details.
- **G-D2** the flaky detail with `count_comparable` False is `<n> failure(s) on the related files — newly-failing file(s) confirmed FLAKY in isolation (passed alone, not blocking): <files> (baseline <source>: <k> failing related file(s); counts not compared)`. The no-new-file not-comparable text is unchanged, built from the same `not_compared` tail.
- **G-D3** `_count_said` `:4711` writes `<n> (derived)` for a `derived` run. It is applied to the branch and baseline numbers in these PASS details only. The `count rose from …` texts on the F4 path (BLOCKED / FAIL / flaky-tests details) are verdict-path lines and were left as they are.
- No verdict, signal, flaky set or cache write changed.

### Predicates (`tests/test_unit_gate_wording.py`, driven with `tests/test_unit_baseline_gate.py`'s `confirm_fake` / `vitest` / `run_gate` / `repo` / `active`; RED against a `git archive` of `ce776e0`)
- **P-D1** 6 (B, C newly failing) vs 3, both flaky → PASS. The detail has `6 failures, above the merge-base baseline of 3 — newly-failing file(s) confirmed FLAKY` and no `below`. RED (HEAD said `6 failures, below the merge-base baseline of 3`) → GREEN.
- **P-D2** 2 vs 2 `equal to`, 1 vs 2 `below`: green before and after. The `_count_word` unit check is RED only because the helper is new.
- **P-D3** a related-files baseline (`count_comparable=False`, injected via `_unit_baseline_measure_or_reuse`) with one flaky new file → the exact G-D2 text, `counts not compared`, no `baseline of`. RED (HEAD said `5 failures, below the merge-base baseline of 1 …`) → GREEN.
- **P-D4** a derived branch count → `0 (derived) failures, below the merge-base baseline of 1`: RED → GREEN.
- Totals: RED **4 failed / 1 passed** → GREEN **5 passed**.

### Rule #8 — Part D
No edits. `tests/test_unit_baseline_gate.py:219, 227, 1005, 1010, 1278, 1573` and `tests/test_unit_fail_label.py:250` are green unchanged (226 passed); so are `:1124, :1236-1246`. Neighbours that pin gate detail text (`test_baseline_reuse_1`, `test_baseline_trust`, `test_config_truth`, `test_unit_related`, `test_gate_cost`, `test_exec_preflight`, `test_unit_listing_prefix`): **210 passed**.

---

## R-items
- **(R-a) The first route after merge** runs the new OPX-3 (Part B) and the orchestrator-side probe (G-C3) at once. Pending briefs that name a protected path: `585-606-657-refire-bundle-1.md`, `605-allergy-unchosen-defaults-1.md`, `662-663-orch-guard-self-npm-frozen-1.md`, and this brief. All four pass B1's OPX-3 (corpus run above). From then on, every fire also makes one `claude auth status` call and one trivial `claude -p` call (≈ 4 s here) before any branch is cut.
- **(R-b) The daemon half of Part C (`queue_daemon.py`, G-C2) takes effect only after a daemon restart** (rule #12, Gemma, quiet window). Until then, G-C3 refuses a logged-out fire with exit 2 / `FAILED` before any branch is cut, and the running daemon treats that exit as a failure today (`failed/`, `stop-on-failure` pause).
- **(R-c) C0 #5 is still unmeasured**: whether `auth status` reports `loggedIn: false` (or a past expiry) for a refresh token the server has already refused. The live call (G-C1 step 2) and G-C4 cover it either way.
- **(R-d) Late repo=orchestrator brief.** `662-663-orch-guard-self-npm-frozen-1` (`Depends-on: 652-660-…`) was enqueued during this route. Its premises cite `b9cf4c9` line numbers that this merge moves (it says so itself: "re-located after 652-660").
- **(R-e) Finding** (repeats Notes for Gemma, not changed): `prefire.py` and `queue_daemon.py` are on neither the `protected` nor the `agent_runtime` orchestrator list. 662-663 Part A proposes adding them.
- **(R-f) Canon observation:** `SCP_Agent_Inventory_v0-7.md` already lists `AP-SIM-ENGINE` (seen in OPX-2's refusal text above).

## Executor preflight (`python3 ~/spectricom-orchestrator/orchestrator.py preflight --repo orchestrator`, run at tip `edff123`)
```
  SIT: 0 file(s) — pass — orchestrator's gate has no SIT leg
  unit: ? file(s) — not computed — the gate runs the FULL unit suite — related selection not available for orchestrator — `pytest -q tests/` is not a vitest run
🧪 Preflight (executor): 0 SIT files / ? unit files — fail (not computed)
   JSON: /home/gkassa/spectricom-orchestrator/state/preflight/orch-orch-652-660-orch-prefire-bundle-1.json
```
Exit **3** (`result: not computed`, `failed: []` on both legs; diff = the 12 files above). Nothing failed. The unit leg can't be computed for orchestrator, which is the shape this brief's GATE PRE-LIST names ("the gate runs the full suite at merge"), the same as 341i1 / 341a4's R1. Under rule #8 / STOP it is not a red test: no test was named failing. The full suite is the pre-merge gate's job.
