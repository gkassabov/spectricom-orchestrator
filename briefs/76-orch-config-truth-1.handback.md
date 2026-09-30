# filename: briefs/76-orch-config-truth-1.handback.md

# 76 · ORCH-CONFIG-TRUTH-1: handback

The brief asked for two fixes: a control command that changes nothing must say so, and a baseline whose clock was never judged must not be trusted. Both are in. The route ran on `orch-orch-76-orch-config-truth-1`, from `d495729` (whose parent is `5ad0e45`), in two commits: `3345bd8` has the code and tests, and the second commit is this file.

## Found and LEFT

1. **Stale `CLAUDE.md:16` (owner-guarded).** Its UNRATIFIED model note says `claude-opus-4-8` is pinned in `orchestrator.py` and `config/repos.yaml`. Neither file contains that string. Since `5ad0e45` the direct path takes its model from `canon_assert.DEFAULT_EXECUTOR_MODEL`, and the yaml has no model. The note's other half is still accurate: `agents/toni.py:6`, `agents/gemma.py:6` and `loop/executor.py:16-17` pin `claude-sonnet-4-20250514`. I did not edit it (§3, §4; this is George's call).
2. **A persisted value beats the code default for every non-executor key at daemon start.** `_load_state` applies whatever `queue-state.json` holds.
   - **Live today:** `max_consecutive: 10`, although the code default has been 25 since S7-CORE-11 (`0b93837`). No command ever set it: `update_config` had no caller. So the 10 is an earlier daemon's default that outlived the change, the same shape as L-8.
   - `repo` (persisted beats `QUEUE_REPO`) and `timeout_seconds` (persisted beats the code's value) resolve the same way. The new refusal messages describe this accurately.
   - Not changed: how keys resolve is out of scope (§4).
3. **A settable key cannot be set on a running daemon.** The CLI is another process, and the control file (QUEUE-PAUSE-OPAQUE) carries only `pause` / `resume`. A `config` action through the control file would make the three settable keys live-settable. I did not build it (§4). The new CLI command refuses rather than pretend (see Shipped).
4. **The 18 cache entries written after GATE-CLOCK-1 carry no field either.** Their clocks were judged when they were written, but nothing records that, so D2 treats them as unjudged and re-measures them when a route needs them. That follows D2 as written. I name it here because of the cost in the Consequence.
5. **Flakes can still attach to an unjudged entry.** `_unit_cache_record_flakes` does this when the re-measure could not be stored (both legs implausible, or no failure count). Only the `flaky` report reads that field; no verdict does. Left as is.
6. **`~/bin` scripts call `QueueDaemon` methods in their own process.** For example, `s7core14-switch-29-to-fable.sh` calls `d.reset_consecutive()` and `d.resume()`. This is the same other-process problem as item 3. None of them call `update_config`. These scripts are Gemma's.

## §0 as-built (AC-OC-01)

1. **`update_config`: confirmed, with one correction.** `queue_daemon.py:474-483` behaved as the brief says: `{"ok": True}` for any key in `config`, but only three keys were assigned.
   - **Correction: nothing called it.** There was no `config` CLI command. `orch-dashboard.py:362-370` wires only pause, resume, cancel, clear and reset. `git log -S update_config` shows only `c81d126`, the commit that introduced it.
   - On `5ad0e45`, `queue_daemon.py config model X` printed Usage and exited 0.
   - So D1's "the CLI prints the error and exits non-zero" had no CLI to change. I added `config <key> <value>`.
2. **The store and the trust line: confirmed.** `_unit_cache_store` is at `orchestrator.py:2868-2891` (the brief says 2869-2890) and wrote no clock field. The cache-hit trust line is at `orchestrator.py:3088-3089`, verbatim as quoted.
3. **The ancestor path.** `_unit_cache_ancestor` is at `orchestrator.py:3031-3065`, is called at `:3133`, and its result is returned as `"ancestor-cache"` at `:3141`. It read the same entries with no clock check.

**Live cache count** (`~/spectricom-orchestrator/sit-archive/unit-baseline-cache.json`, read only; sha256 `22b1f67c…a5a9` before and after this route):

- 80 entries, all clinical-mp: **0 with `clock`, 80 without.**
- By `measured_at` against the time of the GATE-CLOCK-1 commit `964e564` (2026-09-28 03:13): 62 are earlier (route 67's 62) and 18 are at or after it.

## Shipped (`3345bd8`)

- **D1: refuse what cannot be set** (`queue_daemon.py`).
  - `parse_config(key, value)` holds the one rule. `update_config` calls it and, on a refusal, returns `{"ok": False, "error": …}` and writes nothing.
  - **Settable keys:** `max_consecutive` and `cooldown_seconds` take a non-negative integer, as an int or a decimal string. `stop_on_failure` takes a bool or `true`/`false` in any case.
  - **Unparseable values are refused, not coerced:** `ten`, `3.5`, `-1`, `True` given for a count, `maybe`, `1`, `0`.
  - Each unsettable key gets `<key> is not settable by command: <reason>`:
    - `model` / `effort`: "one default in the repo (canon_assert's DEFAULT_EXECUTOR_MODEL, or TONI_MODEL at daemon start); a brief's `#!queue model=…` header overrides it (EXECUTOR-DEFAULT-1)"
    - `repo`: the brief header, else the daemon's default read at start (queue-state.json, else QUEUE_REPO, else clinical-mp)
    - `timeout_seconds`: queue_daemon.py's default, kept above orchestrator.py's 180-minute cap
    - an unknown key: "not a config key", plus the list of settable keys
  - **New CLI `queue_daemon.py config <key> <value>`:**
    - A refusal prints the error and exits 1.
    - A settable key is also refused (exit 1) while `queue-state.json` says a daemon may be running (status not `stopped` and pid alive or not recorded). That daemon keeps its config in memory, and its next save would overwrite the write.
    - Otherwise it writes `queue-state.json`, exits 0, and says the next daemon start reads it.
    - It shows the daemon's model and effort, not its own, the same way `status` does.
- **D2: a cache entry says its clock was judged** (`orchestrator.py`, cache store and lookup only).
  - `_unit_cache_store` adds `"clock": "plausible"`. The field is additive; every existing field stays.
  - It refuses to store a leg whose `clock` is set, so the field cannot be false.
  - When it supersedes an entry at the same key, it carries that entry's `flaky_files` / `flaky_seen` forward, so the ORCH-7 tally survives.
  - A lookup that finds no `clock` field logs `♻️  Unit baseline: cached entry at <sha7> predates GATE-CLOCK-1 (clock never judged) — re-measuring`, measures, and overwrites that key if the leg is plausible.
  - The ancestor path skips such entries and logs how many it skipped.
  - Nothing is bulk-rewritten or deleted.
- **D3: the trust line tells the truth.** A cache hit now logs `🛡 baseline-trust: CLEAN — cache hit at <sha7>, measured <ts> on a clock judged plausible (cache entry "clock": "plausible")`. The phrase "only a plausible leg is cached" is gone from the source.
- **Tests:** `tests/test_config_truth.py`, 40 new. No existing test changed. `canon_assert.py` is untouched: the ♻️ line is not a `🛡` verdict line, so no control set needed a new member.

## Gate table

| AC | Evidence | Result |
|---|---|---|
| AC-OC-01 | §0 above: three confirmations with file:line, one correction (no CLI caller), live count 80 / 0 with `clock` / 80 without | PASS |
| AC-OC-02 P-CFG | **RED on `5ad0e45`:** `update_config("model", "some-model")` → `{'config': {…'model': 'claude-opus-5-5'…}, 'ok': True}`, the same for effort, repo and timeout_seconds; `("stop_on_failure", "false")` → True; `("cooldown_seconds", "-1")` → ok, -1 stored; `("max_consecutive", "ten")` → ValueError; `main(["config", "model", …])` → Usage, exit 0. **GREEN:** every case refused with the state file byte-identical; the CLI exits 1. **Negative control:** 6 valid settable values applied and persisted (5 of them already passed on `5ad0e45`; `"false"` did not) | PASS |
| AC-OC-03 P-CACHE | **RED on `5ad0e45`:** the route 59 masking baseline stored without `clock` was a hit, so `calls == ["branch"]` and the regressing branch got `PASS (unit green on route)`; an unjudged ancestor was borrowed (`baseline ancestor-cache`, PASS); the store had no `clock` (KeyError). **GREEN:** the unjudged entry is re-measured, gives FAIL(product) `regression`, and is overwritten with `clock: "plausible"`, 3 failures, 338.8 s; an implausible re-measure (two legs) gives BLOCKED `baseline-clock-implausible` and leaves the legacy entry byte-equal; another unjudged entry is untouched; the flaky tally is carried forward; an unjudged ancestor is not borrowed (`baseline-unmeasurable`). **Negative control:** a judged entry is a hit (`["branch", "confirm"]`), and a judged ancestor is borrowed | PASS |
| AC-OC-04 P-LINE | **RED on `5ad0e45`:** an entry without the field logged `🛡 baseline-trust: CLEAN — cache hit at eff5103: no leg measured now, so no clock to judge; since GATE-CLOCK-1 only a plausible leg is cached`. **GREEN:** the hit line quotes `"clock": "plausible"`, and the phrase is gone from the source. **Negative control:** an unjudged entry gives exactly one trust line, "measured on a plausible clock", and no "cache hit" | PASS |
| AC-OC-05 | `pytest -q tests/`, run in the foreground: 782 → **822 passed, 0 failed** (27 s). New file on `5ad0e45`: 32 failed, 8 passed, and all 8 are negative controls | PASS |
| AC-OC-06 | The diff touches `orchestrator.py` (cache store, `_unit_cache_judged`, ancestor path, lookup and trust line), `queue_daemon.py`, the new `tests/test_config_truth.py` and this handback. `config/`, `CLAUDE.md` and `canon_assert.py` are untouched. 2 commits | PASS |
| AC-OC-07 | `queue_daemon.py` changed, so the daemon must be restarted; see Consequence 3 | noted |
| Handback guard | This file, wrapped in a `=== TONI EXECUTION ===` log, run through `orchestrator.py handback-scan` against `config/handback-guard.json` | CLEAN |

## THE CONSEQUENCE (D-S7CORE13-03)

1. **`queue_daemon.py config model …` now fails loudly instead of pretending.** The same goes for `effort`, `repo`, `timeout_seconds`, any unknown key and any unparseable value. It prints `{"ok": false, "error": "…"}` and exits 1.
   - Before, the command did not exist: it printed Usage and exited 0. A Python caller of `update_config` got `ok: True` and no change.
   - `stop_on_failure` given `"false"` now means False; before, it meant True.
   - A settable key through the CLI now lands only while no daemon may be running. While one is live the CLI refuses with exit 1, because the write would have been overwritten.
2. **Unit baseline: one extra measurement per base commit.** The first clinical-mp route per merge base after this merge re-measures instead of trusting an entry without `clock`. Today that is all 80 live entries. The cost is one extra baseline leg: live median 271 s (p10 241 s, p90 342 s), and about 310 s over the last 10.
   - **Verdict classes can change on those routes.** An unjudged entry that masked a regression (the route 59 shape) now gives FAIL(product) on a plausible re-measure, or BLOCKED(environment) `baseline-clock-implausible` if both legs are implausible.
   - **The ancestor fallback no longer borrows an unjudged entry.** Where that was the only candidate, the verdict is now `baseline-unmeasurable` instead of a PASS on an approximate baseline.
   - Each legacy entry is superseded one key at a time, and none is deleted.
3. **Daemon restart.** `queue_daemon.py` changed, so the running daemon (pid 2877480, started 2026-09-29 11:45) keeps the old code until it restarts. The `orchestrator.py` change needs no restart, because each route runs a fresh `orchestrator.py` from the merged checkout. Restart only when no route is live, using route 67's procedure:
   1. `cd ~/spectricom-orchestrator && python3 queue_daemon.py pause`. This route (76) is the daemon's current batch, with nothing queued behind it.
   2. Check that `python3 queue_daemon.py status` shows `paused` and `"current_batch": null`.
   3. Stop pid 2877480, then run `~/bin/s7core14-start-daemon.sh`.
   4. Check the new daemon's `🛡 executor-default:` start line.
