## STATUS: DONE — one commit `bb6c565` (G-1…G-8); P-1…P-8 RED on the base `239ec42` → GREEN, P-9 controls green both sides; no existing test edited (rule #8: no pin moved).

# Handback — 690-orch-handback-stop-status-1 (ORCH-HANDBACK-STOP-STATUS-1, Kanban 690)

**Executor:** claude-opus-5-5 (effort high) · **Worktree:** `/tmp/orch-fire-20261115-113259`, branch
`orch-orch-000000690-orch-handback-stop-status-1`, base `239ec42` (601's handback; 601 merged first — every A0
line re-read at the base, moved lines below) · **Test scope:** targeted (D-S7CORE30-05).

This route fires under `main`'s code, so its own handback is judged by the OLD verdict code. The first route
after the merge is the first one the new code judges. **Restart the daemon after the merge, before the next fire
(rule #12).** Until then, the daemon files an exit 5 under `failed` and pauses (`stop_on_failure: true`).

## X0 · the worktree
```
$ git rev-parse HEAD && git log --oneline -3
239ec42afdd55fbb307aa26824cc93e16d910932
239ec42 handback: 601-fullgate-worktree-fsdeny-1 — A (30435e0) …
3917c13 feat(orch): preflight and the related unit leg reach the read-map pin test — …
62c92fa feat(orch): a newly-failing file keeps its first error lines — …
$ venv/bin/python -c "…import orchestrator, queue_daemon; print(orchestrator.__file__, queue_daemon.__file__)"
/tmp/orch-fire-20261115-113259/orchestrator.py /tmp/orch-fire-20261115-113259/queue_daemon.py
```
Both modules load from the worktree. STOP (e) not hit.

## A0 · as built at `239ec42` (the lines that moved from `d152f1f`)
1. Evidence, re-read: `logs/clinical-mp/orch-685-hardstop-unassessed-blocks-1-20261112-234830.log:47` `🛡 handback-guard: CLEAN`,
   `:49` `✅ Pre-merge gate … PASS (briefs-only diff (2 files: …handback.md, …`, `:50` `🔀 Merged … (eced0dc → 0dcbf0b)`,
   `:51` `🗃️ Retired … → queue/done/`, `:53` `🏁 FINAL STATUS: passed | gate: PASS (briefs-only diff …`, `:56` `✅ 685-… — passed`.
   `git -C ~/spectricom-clinical-mp show 0dcbf0bb:briefs/685-hardstop-unassessed-blocks-1.handback.md | head -1` → `## STATUS: STOP (g)`.
2. `Status` — `orchestrator.py:570-578` (unchanged).
3. `status = Status.PASSED if (ec == 0 or _produced_work)` `:7261` (was `:6809`); `hold` `:7268-7270` (was `:6816-6818`); `_handback_hold` `:6817` (was `:6365`).
4. Briefs-only gate: `run_pre_merge_gates` `:5618`, reason built at `:5627` (was `:5349-5364`).
5. Hold override `:7506-7512`; landed invariant `:7517-7525`; FINAL STATUS `:7530-7531`; cascade `:7545`; `notify` `:1367-1371`;
   `_finish_route_worktree` `:1779`; `run` `:8124-8127`; `queue` `:8132`; `run_queue` halt `:7576`; self-mod merge `:7111`.
   Exit codes in use: 0, 1, 2, 3 (`:84`, `PREFLIGHT_EXIT`), 4 (`:1658`); daemon -9/-1/-2 (cancel/timeout/error).
   **5 is used nowhere** in `orchestrator.py` or `queue_daemon.py` (grep for `exit(5`, `== 5`, `return 5`: no hit).
6. Daemon: `queue_daemon.py:1543-1557` (unchanged), state `:739-740`, loaded `:796-798`, saved `:828-830`, status `:872-878`, `find_missing_gate_logs` `:1040-1043`.
7. `verify_route` `:4395` (was `:4237`).
8. Corpus: see the P-3 section.

## A1 · as built (`bb6c565`: 4 files, +842 −21 — orchestrator.py +160 −17, queue_daemon.py +22 −4, README.md +17, tests/test_handback_stop_status.py +643)
- **G-1** `orchestrator.py:6809-6899`. `HandbackStatus` `:6826`, `_classify_handback_status` `:6842` (steps 1-5 as the brief orders them),
  `_read_handback_status` `:6858`, `handback_status(path)` `:6876` (pure; None for no file, no status line in the first 40,
  `OSError`/`UnicodeDecodeError`), `route_handback_path(proj, stem)` `:6882` (exact name first; the zero-less name only when the
  exact one is absent, `re.match(r"0+\d", stem)` and the zero-less one exists), `_log_handback_status` `:6894`
  (`🛑 handback-status: <label | none (<why>)> (<path read>)`). Re-gate stem: `_regate_route_stem(spec)` `:7055`. The same
  expression `_regate_bring` used inline now lives there, and `_regate_bring` calls it. Markdown stripping: `*` and backticks are
  removed anywhere, `#` / `_` / whitespace are stripped at the edges, and `#` / `_` are stripped again after the colon. No `_*_hold`
  name, no `guard` word, 🛑 not 🛡: `test_source_guard_C_is_pinned` stays green, unedited.
- **G-2** `Status.STOPPED` `:579-581`. Read once beside the hold, `:7377-7380` (one `🛑` line per route that reaches the executor
  or the re-gate bring). Demotion `:7636-7642`, after the landed invariant and only from `PASSED`.
  `Result.error = 'handback STATUS: <label> — "<line[:160]>"'`; the FINAL STATUS gate label is still computed from `gate_error`, so it is unchanged.
- **G-3** self-mod merge `:7216-7217` `status in (PASSED, STOPPED)` (exit 0 still required); `_finish_route_worktree` `:1786`;
  `run_parallel` `:7765` (gate) and `:7769` (merge). The route and route-worktree lanes merge before G-2 runs (no change there).
- **G-4** FINAL STATUS `:7647-7649` appends ` | handback: <label>`. `notify` `:1375-1376` uses 🛑. The cascade stays PASSED-only.
- **G-5** `EXIT_STOPPED = 5` `:585`; `_record_result` `:7673` (completed / stopped / failed, `setdefault`); `_exit_code_of` `:7679`;
  `_stopped_tag` `:7688` (`, N stopped`, empty when none); `run_queue` halts on STOPPED `:7716`, and its halt line says `(stopped)`;
  `load_state` default `:1427`; `run` `:8270`; `queue` `:8275`; `watch()` uses `_record_result`.
- **G-6** `queue_daemon.py:64` `EXIT_STOPPED = 5` (mirrored; pin test `test_P4_EXIT_STOPPED_is_5_and_both_modules_agree`);
  `self.stopped` `:745`, loaded `:803`, saved `[-15:]` `:836`, status `[-5:]` `:881` + `stopped_total` `:887`;
  `exit_code == EXIT_STOPPED` branch `:1560-1569`: entry `"status": "stopped"`, `_safe_move(…, QUEUE_DONE)` as for 0,
  `consecutive_count += 1`, `[QUEUE] STOPPED: <file> (handback STATUS STOP/PARTIAL — read it before closing the Kanban row, rule #15; <n>s)`, no pause;
  `find_missing_gate_logs` `:1052` = completed + failed + stopped. Exit 0 and every other code: byte-identical paths.
- **G-7** `verify_route` `:4447-4451` → rc 1 with `FINAL STATUS is stopped — the handback's status line says STOP / PARTIAL; read it before closing the Kanban row (rule #15)`.
- **G-8** `README.md:211-226` `## Route verdict `stopped``.

Deviation, named: the `none (…)` reasons are `none (no handback file)`, `none (no status line in its first 40 lines)` and
`none (unreadable: <ExcType>: <msg>)`. Only an unreadable file says `unreadable:`, so the other two gaps are named for what they are.

## A3 · predicates — RED on the base, GREEN at `bb6c565`
RED run: the new test file against `git archive 239ec42` (in a scratch dir; no git state touched):
```
47 failed, 8 passed in 3.35s     (base: the 8 P-9 controls pass)
```
The reason each one fails on the base (`--tb=line`):
- P-1 `assert '🏁 FINAL STATUS: passed | gate: PASS (briefs-only diff (2 files: briefs/685-x.handback.md, briefs/685-x.md) — build/SIT/unit not run (D-S7CORE29-02))' == '… | handback: STOP (g)'`
- P-2 the same `passed` line vs `… | handback: PARTIAL`
- P-3 (31 cases) `module 'orchestrator' has no attribute 'handback_status'`
- P-3b zero-prefix: `Status.PASSED`; exact-name-first: no `🛑 handback-status: DONE (…0653-x.handback.md)` line; re-gate `0584ar-x-regate.md`: `Status.PASSED`
- P-4 `run`: `assert 0 == 5`; P-4b `queue`: `assert 0 == 5`; `run_queue`: `the second brief is not fired` (base fires both; `QUEUE DONE: 2/2 passed`); `watch()`: `stopped` empty; `load_state`: `KeyError: 'stopped'`
- P-5 exit 5: `assert [] == ['685-x.md']` (base files it in `failed` and pauses); restart-load: `no attribute 'stopped'`
- P-6 meta lane: `Status.PASSED` (merged); P-7 worktree lane: `Status.PASSED` (merged); P-7b `run_parallel`: `[PASSED]`, `PARALLEL DONE: 1/1 passed`
- P-8 verify: rc 0
- G-4 notify: `'str' object has no attribute 'value'` (no STOPPED status)

GREEN:
```
$ venv/bin/python -m pytest -q tests/test_handback_stop_status.py
55 passed
```
P-9 controls, green on both sides: `## STATUS: DONE` / `# hb` / no handback → today's `🏁 FINAL STATUS: passed | gate: PASS (briefs-only diff (…))`
byte-for-byte with `error is None`. A STOP handback on a FAIL(product) route stays `failed`, on an INCOMPLETE (R54 fixture) route
`incomplete`, on a TAMPERED route `tampered`, and on a BLOCKED route `blocked`, each with no `| handback:`. Daemon exit 0 → `completed`
and exit 1 → `failed` + pause, as today. `tests/test_depends_product.py` is untouched and green (gate list).

## P-3 · the corpus (read-only `git show` of every `briefs/*.handback.md`)
- At the verifier's refs (clinical-mp `72abb866` + orchestrator `d152f1f`): **503 — STOP 67, PARTIAL 23, not a stop 197, None 216.**
  This matches the verifier's `/tmp/v53/corpus3.py` count exactly.
- At today's mains (clinical-mp `e7a99957` + orchestrator `239ec42`): **521 — STOP 69, PARTIAL 24, not a stop 211, None 217.**
  Every difference is a handback added since: STOP +2 (`585-606-657-refire-bundle-1`, `702-member-bff-boundary-1`), PARTIAL +1
  (`654-655-task-close-truth-1`), not a stop +14 (`600`, `600r`, `604-682`, `604-682r2`, `639`, `669-585r`, `683`, `686r`, `687`, `688`,
  `701`, `702r`, `703`, `704`), None +1 (orchestrator `601-fullgate-worktree-fsdeny-1`: its first 40 lines carry no `Status:` label).
  Nothing changed class.
- **Every PARTIAL (24, today's mains):** `234-small-fixes-5`, `244-small-fixes-8`, `250-small-fixes-9`, `251-visit-entry-integrity-1`,
  `258a-small-fixes-10`, `279b-small-fixes-12`, `294-followup-truth-2`, `295-chart-truth-3`, `299a-note-addendum-1`, `337m-small-fixes-24`,
  `341b9h-bundle-caregap-disposition-1`, `341k1-member-pdf-upload-1`, `341n10-agent-draft-truth-1`, `341n11-member-portal-truth-1`,
  `341n13-agent-draft-truth-2`, `341n14-orders-truth-2`, `341n2-meds-orders-truth-1`, `341n8-previsit-truth-3`, `588-coding-rules-1`,
  `588b-coding-rules-1b`, `589-meds-cds-3`, `654-655-task-close-truth-1`, `664-lockfile-tracked-1`, `665-home-readerror-consent-bundle-1` (all clinical-mp).
  Borderline, read by the exact G-1 rule: `251-visit-entry-integrity-1` (`## STATUS: DONE. STOP (a) and (b) did not fire. STOP (c): one case reported, no rule invented (R-4).`)
  is PARTIAL because its third sentence names `STOP (c)` with no negation. `250-small-fixes-9` (`DONE, with STOP (a) FIRED for 40 stored panels`) is PARTIAL too.
- Five STOP, checked by eye: `138-voice-l-1` `## STATUS: STOPPED at §0.3 S1, before any edit.` → STOP; `145-voice-l-1r` → STOP;
  `146c-clinician-reasons-internal-1` `## STATUS: STOPPED — STOP (f) on the live server …` → STOP (f); `685-hardstop-unassessed-blocks-1` → STOP (g);
  `341n15-member-portal-truth-2` `## STATUS: HELD — STOP (e) on both parts; nothing committed.` → STOP (e). All five are right.
- Five DONE, checked by eye: `0653-sit-member-pdf-upload-p3-error-1` `**Status: DONE.** G1 is in commit …` → DONE; `255r-chart-truth-1r` `## STATUS: DONE`;
  `337g3-data-hygiene-1` `**Status: DONE.** … **`--apply` was never run.**` → DONE; `341g2-member-form-amend-boundary-1` `## STATUS: DONE`;
  `341n6b-no-phi-browser-cache-2` `## STATUS: DONE — one commit …` → DONE. All five are right.
- Test `test_the_685_handback_on_clinical_mp_main_reads_stop_g` reads 685's handback at clinical-mp `main` (read-only) → `STOP (g)`. It is skipped where there is no checkout.

## R-items
- **(R-a) queue/done/ since 2026-11-01** (134 briefs by file mtime, read-only; handback from the repo's `main` by G-1's name rule):
  **43 would now read `stopped`: 30 STOP, 13 PARTIAL.** Five have no handback at `main` and five are None. The ones the daemon's
  `queue-state.json` still lists as **`completed`**, which Gemma should check against their Kanban rows (rule #15):
  `0686-careplan-hardstop-signblocker-1` → `686-…handback.md` STOP (b); `0702-member-bff-boundary-1` → `702-…` STOP (h);
  `654-655-task-close-truth-1` PARTIAL; `664-lockfile-tracked-1` PARTIAL; `665-home-readerror-consent-bundle-1` PARTIAL;
  `685-hardstop-unassessed-blocks-1` STOP (g). Listed as `failed`: `585-586-bundle-item9-cssrs-safety-1` STOP (b).
  The other 36 have rolled out of the `completed[-30:]` / `failed[-15:]` lists, so the daemon's record of them cannot be read:
  STOP (26) — `341g1` (c), `341g3` (c), `341g3r` (c), `341g3r2` (c), `341g4` (d), `341h1b` (c), `341h1c` (c), `341h1c2` (a), `341h1c4` (e),
  `341h2` (c), `341h4` (c), `341h4b` (a), `341h5` (c), `341k3` (f), `341l1` (d), `341l1r` (e), `341l2` (b), `341n15` (e), `341n3` (e), `341n4` (b),
  `341n7` (STOP, no letter), `341p1` (e), `341p3` (c), `584-clinician-name-truth-2` (c), `585-item9-safety-2-bundle` (c), `614-lab-release-on-final-1` (c);
  PARTIAL (10) — `341k1`, `341n10`, `341n11`, `341n13`, `341n14`, `341n2`, `341n8`, `588`, `588b`, `589`.
- **(R-b) label-less `**Result:**` / `**Outcome:**`:** 103 of the 217 None handbacks have, in their first 40 lines, a verdict line
  that starts `Result:` / `Outcome:` and no `Status:` line. They read as None (fail-open). 32 of those lines name a STOP, STOPPED,
  HELD or PARTIAL, for example `290d-member-write-guard-1` `Outcome: STOPPED on STOP (a).`, `290eb0-phq9-item9-escalation-1`
  `Outcome: STOPPED on STOP (a).`, `290ed-partner-pdf-legacy-tag-1` `Outcome: STOPPED on STOP (b).`, `282c-small-fixes-13`
  `Outcome: … D6 is not built: STOP (d) fired`, `255-chart-truth-1` `Result: built and verified, except one sign path, which is a STOP (b).`
  These are all older routes (290-series and earlier, plus 313d). The newest corpus uses the `Status:` label.
- **(R-c) the live checkout:** the preflight the fire prompt asks for wrote its JSON to
  `~/spectricom-orchestrator/state/preflight/orch-orch-000000690-orch-handback-stop-status-1.json`. That is the command's own
  output, as on every route. Nothing else in the live checkout was written: queue/, logs/, `queue-state.json` and config were
  read-only reads for R-a.

## RULE #8
Search re-run at the base: `git grep -n -E "FINAL STATUS|\[QUEUE\] (PASSED|FAILED)|\.completed\b|\"completed\"|completed_total|exit_code|returncode == [0-9]|Status\.(PASSED|FAILED|INCOMPLETE)" -- tests/`
hits 37 files: `test_baseline_reuse_1`, `test_baseline_trust`, `test_canon_assert`, `test_capacity`, `test_config_truth`, `test_control_scope`,
`test_control_verdict_lines`, `test_empty_commit_guard`, `test_executor_auth`, `test_executor_default`, `test_fullgate_local_files`, `test_gate_clock`,
`test_gate_collection`, `test_gate_cost`, `test_handback_guard`, `test_isolated_deps`, `test_merge_conflict`, `test_npm_frozen_hook`, `test_orch_lane`,
`test_prefire`, `test_queue_gate_log`, `test_queue_pause`, `test_regate_gates_only`, `test_route_landed`, `test_route_ref_integrity`, `test_sit_integration`,
`test_sit_rate_limit`, `test_stale_base`, `test_timeout_hold`, `test_toni_guards`, `test_unit_baseline_gate`, `test_unit_fail_label`, `test_unit_gate_wording`,
`test_unit_load_check`, `test_unit_related`, `test_yorsie_safety`, plus two fixture logs (`fixtures/handback/toni-51-…`, `fixtures/verify/orch-20261004-184720.log`).
`git grep -n -i -E "status\s*:\**\s*(stop|held|partial)|route status|DONE except" -- tests/` → no hit before this route, so no fixture handback
reaches G-2. The one stop-like fixture, `test_depends_product.py:136` `"STOPPED\n"`, has no label, so it reads None and does not go through
`_run_batch_inner`. Every file the author and verifier named stays green unedited. That includes `test_prelist.py:312` (G-2 adds no
`gate_prelist`/`capture_handoff`/`fire_toni` call) and the strict source pin `test_control_verdict_lines.py:349-350`.
**No existing test's assertion changed. No pin moved. Mechanical pins: none.** STOP (c) not hit.

## STOP check
(a) every RED predicate was red at the base (above) · (b) only the ALLOWED FILES changed, plus this handback and the brief copy ·
(c) no existing assertion changed · (d) G-3 holds: P-1/P-3b/P-6/P-7/P-7b show a STOPPED route merging exactly what `passed` merged
at the base (the same RED runs show `passed` + merged) · (e) X0 #2 shows worktree modules. **No STOP fired.**

## Gates (targeted, foreground, from the worktree root)
```
$ venv/bin/python -m pytest -q tests/test_handback_stop_status.py tests/test_handback_guard.py tests/test_gate_cost.py tests/test_orch_lane.py
    tests/test_merge_conflict.py tests/test_route_ref_integrity.py tests/test_timeout_hold.py tests/test_queue_gate_log.py tests/test_self_mod_auto_merge.py
    tests/test_regate_gates_only.py tests/test_control_scope.py tests/test_depends_product.py tests/test_queue_pause.py tests/test_capacity.py
    tests/test_yorsie_safety.py tests/test_control_verdict_lines.py tests/test_depends_on.py tests/test_queue_retire.py tests/test_toni_guards.py
    tests/test_executor_auth.py tests/test_executor_default.py tests/test_config_truth.py tests/test_gate_collection.py tests/test_baseline_reuse_1.py
    tests/test_stale_base.py tests/test_prefire.py tests/test_prelist.py tests/test_unit_baseline_gate.py
1377 passed in 42.98s
$ (rule #8 neighbours) test_baseline_trust test_canon_assert test_empty_commit_guard test_fullgate_local_files test_gate_clock test_isolated_deps
    test_npm_frozen_hook test_route_landed test_sit_integration test_sit_rate_limit test_unit_fail_label test_unit_gate_wording test_unit_load_check
    test_unit_related test_bg_ceiling test_foreground test_admission_parser
637 passed in 20.81s
$ python3 -m py_compile orchestrator.py queue_daemon.py
py_compile ok
```
I did not run the full `tests/` directory or any merge-base measurement (Test scope: targeted); the route's pre-merge gate runs them.

## Preflight (the fire prompt's)
```
$ python3 ~/spectricom-orchestrator/orchestrator.py preflight --repo orchestrator
  SIT: 0 file(s) — pass — orchestrator's gate has no SIT leg
  unit: ? file(s) — not computed — the gate runs the FULL unit suite — related selection not available for orchestrator — `pytest -q tests/` is not a vitest run
🧪 Preflight (executor): 0 SIT files / ? unit files — fail (not computed)
EXIT=3
```
Exit 3 means `not computed`. This is the orchestrator repo's structural result, as on 601 and 662-663: its gate has no related
unit selection, and the pre-merge gate runs the full suite. It is not a red under rule #8 or STOP (a).

## OPEN (unchanged from the brief; for George / Gemma)
(b) a stopped brief's tray is `queue/done/`, as today · (c) the dashboard, qstat and Slack do not show `stopped` yet;
`rate_limiter.record(…, "stopped")` will render as ❌ in `rate_limiter.py status` · (d) the daemon does not pause on a STOP
(`run_queue` does halt, per G-5) · (e) a gated product merge with a STOP/PARTIAL handback is also `stopped` (R-a lists them).
**Restart the daemon after this merges, before the next fire (rule #12).**
