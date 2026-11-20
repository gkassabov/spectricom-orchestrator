## STATUS: DONE

# ORCH-OPX-DENIALS-1 (Kanban 760; 622 slice 2 of 2) — handback

- **Base by ancestry:** `git merge-base --is-ancestor edc2b01 HEAD` → ok (HEAD `964f73866e6a4cb203432394462f4615e26c295f`, = the brief's `964f738`).
- **Live `KILL` absent at start:** `ls ~/spectricom-orchestrator/KILL` → `No such file or directory` (no STOP (f)). `TONI_GUARDS_HOME` unset in the fire's shell.

## A0 at HEAD, before any edit (matches the brief — no STOP (d))
1. `tests/test_opx_denials.py` placed alone → `ModuleNotFoundError: No module named 'denial_log'` — **1 error during collection**.
2. With `executor/hooks/denial_log.py`, `scripts/opx5.py`, `config/opx-denials.json` placed and the kill hook and settings as at HEAD → **13 failed, 26 passed**: `test_D1_a_KILL_denial_is_logged_and_still_denied` and the 12 `test_D4_every_settings_file_runs_the_logger[<Stop|SessionEnd>-<repo>]`.
3. `grep -c denials executor/hooks/kill_switch.sh` → `0`; `sorted(hooks)` of `executor/settings/clinical-mp.json` → `['ConfigChange', 'PreToolUse']`.

## G-LINES (each placed by `cp` from `~/_eos/s7core57/dry/760/ref/`; no Edit tool on `executor/**` or `config/**`)
Every ref file's sha256 matched the brief before it was placed:
- G-1 `executor/hooks/kill_switch.sh` `a4fde9c8…6000` ✔ — diff vs HEAD is only the header comment, `log_denial()` and its call as `deny()`'s first line (+15). Mode `0775` kept.
- G-2 `executor/hooks/denial_log.py` `f35bb22f…c83a` ✔ (new)
- G-3 `scripts/opx5.py` `1113d4ab…9429` ✔ (new)
- G-4 `config/opx-denials.json` `978fd582…bb2a` ✔ (new; `burst.n` / `burst.window_s` null = off)
- G-5 `tests/test_opx_denials.py` `36bab264…fcb9` ✔ (new)
- G-6 `executor/settings/{ai-foundation,clinical-mp,collateral,norra,yorsie}.json` `b86630fe…6d71` ✔, `orchestrator.json` `c16c35b2…6f09` ✔ — +20 lines each (`Stop` + `SessionEnd`), nothing else changed.
- 11 files, +670 −0 (7 modified +135, 4 new). Only ALLOWED FILES touched; no existing test edited; no `orchestrator.py` / `queue_daemon.py` / `prefire.py` change.

## D1–D5: RED → GREEN
- **RED:** A0 #1 (collection error) and A0 #2 (13 failed: D1 KILL-logged ×1, D4 ×12; the other D1–D5 cases need only the new files).
- **GREEN:** `venv/bin/python -m pytest -q tests/test_opx_denials.py` → **39 passed in 0.48s**.
- `bash -n executor/hooks/kill_switch.sh` → ok; `python3 -m py_compile executor/hooks/denial_log.py scripts/opx5.py` → ok.

## RULE #8 searches re-run at HEAD
- **R1** `git grep -lE "executor/settings|kill_switch|hooks\]\[" -- tests/` → **8 hits**, not the brief's 5 + conftest: `conftest.py`, `test_control_plane_guard.py`, `test_npm_frozen_hook.py`, `test_toni_guards.py`, plus `test_opex_prefire.py`, `test_prefire_dryrun_gate.py`, `test_queue_park_red.py`, `test_route_time.py`. `test_opx_gameday.py` and `test_guard_self_protect.py` (on the brief's list) do **not** match this pattern; both exist. The four extra hits match the literal `kill_switch` (test names / a path string). I read each one: `test_route_time.py` asserts `hooks.PreToolUse` and `permissions.deny` exactly (neither moved); `test_opex_prefire.py` names `executor/hooks/kill_switch.sh` as an allowed-path string; the other two only use `kill_switch` in test names. None reads the new `Stop`/`SessionEnd` keys or the changed lines of the kill hook. No test pins the exact `hooks` key set (`git grep` for that shape → only `test_control_plane_guard.py:67`, an `any(...)` over `PreToolUse`). None edited.
- **R2** every settings file: top-level keys `['hooks', 'permissions']`; hooks `['ConfigChange', 'PreToolUse', 'SessionEnd', 'Stop']` — P2's "one file / exactly {permissions, hooks}" holds.
- **R3** SIT: none. **R4** access-policy / member: none (`git grep` of `opx-denials|denial_log|opx5` outside this route's own files → 0).

## Gates — what this executor ran, and what it did not run
- **Ran:** the new test file by path (above), `bash -n`, `py_compile`.
- **Did not run:** the brief's guards set (6 files) and the full suite `nice -n 10 venv/bin/python -m pytest -q tests`. The brief's header is `## Test scope: targeted (D-S7CORE30-05)`, and the fire prompt / CLAUDE.md (ORCH-LEAN-GATE-1, D-S7CORE54-77) say to run only this route's own new or changed tests and never a suite unless the header reads `## Test scope: full — <George decision>`. The orchestrator's pre-merge gate runs the full suite. The dry run's numbers: guards 628 passed; full 3195 passed, 1 skipped.

## STOP checks
(a) no red from this route's test file at HEAD beyond A0's stated gap · (b) nothing outside ALLOWED FILES · (c) no existing assertion changed · (d) A0 #1–#3 matched · (e) the full suite is the gate's to run · (f) live `KILL` absent.

## For George / Gemma (from the brief's OPEN ITEMS)
- **(a)** Cells 1–4 of the OPX-5 row from data: a follow-on row after 623's ledger merges.
- **(b)** Burst values ship off; the brief recommends n = 5 within 600 s if George turns it on.
- **(c)** A CLI upgrade may change the refusal text; re-run the live proof on an upgrade.
- The R1 grep in the brief does not produce the list it names (see above). Worth fixing in the template so the keep-green list matches the search.
- The daemon needs no restart (hooks are read per fire).
