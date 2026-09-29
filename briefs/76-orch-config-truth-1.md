#!queue model=claude-opus-5-5 effort=xhigh repo=orchestrator

# ORCH-CONFIG-TRUTH-1 — a control command that changes nothing says so, and a baseline whose clock was never judged is not trusted

## Repo: orchestrator
## Batch ID: s7core16-orch-config-truth-1
## Briefs: 1
## Estimated runtime: 30-45 min
## Spec reference: route 67 handback (Toni log `logs/orchestrator/toni-67-orch-baseline-trust-1-*.log`, "Found and left"); GATE-CLOCK-1 (route 61), BASELINE-TRUST-1 (route 67); Kanban row 119
## Predecessor: main at or after `5ad0e45` (route 67). Verify `git merge-base --is-ancestor 5ad0e45 main`.
## Executor: claude-opus-5-5 --effort xhigh (owner instruction 2026-09-28, S7-CORE-16)

> Background tasks are disabled for you (route 61). Foreground everything.

## 0 · FIRST STEP — as-built (checked at `5ad0e45`; confirm, correct what moved)
1. `queue_daemon.py:474-483` `update_config(key, value)`: for any key present in `self.config` it saves state and returns
   `{"ok": True, …}`, but only `max_consecutive`, `cooldown_seconds` (int) and `stop_on_failure` (bool) are assigned. For
   `model`, `effort`, `repo`, `timeout_seconds` it **reports success and changes nothing** (route 67 §Found-and-left).
2. `orchestrator.py:2869-2890` `_unit_cache_store` writes a baseline entry; since GATE-CLOCK-1 only a plausible leg is stored,
   but the entry records **no field saying its clock was judged**. `orchestrator.py:3080-3089` — a cache hit is logged
   `🛡 baseline-trust: CLEAN … since GATE-CLOCK-1 only a plausible leg is cached`, which is true only for entries written after
   route 61. Route 67 counted **62 of the live cache's 67 entries** as pre-route-61, never judged.
3. The ancestor-cache path (`source == "ancestor-cache"`) reads the same entries — find it and treat it the same way.

## 1 · DECISIONS (author's; implement)
- **D1 — refuse what cannot be set.** `update_config` returns `{"ok": False, "error": "<key> is not settable by command: <reason>"}`
  for every key outside `{max_consecutive, cooldown_seconds, stop_on_failure}`; `model`/`effort` name route 67's rule (one
  default in the repo; a brief header overrides), `repo`/`timeout_seconds` name where they come from. A value that does not
  parse for a settable key is refused, not coerced. The CLI prints the error and exits non-zero.
- **D2 — a cache entry says its clock was judged.** `_unit_cache_store` adds `"clock": "plausible"` (additive; entries keep every
  existing field). A lookup that finds an entry **without** that field treats it as a **miss**: logs `♻️ Unit baseline: cached
  entry at <sha7> predates GATE-CLOCK-1 (clock never judged) — re-measuring`, measures, and on a plausible leg overwrites that
  key. Same for the ancestor-cache path. **No bulk rewrite or delete of the cache file** — legacy entries are superseded one at
  a time as they are needed.
- **D3 — the cache-hit trust line tells the truth:** `🛡 baseline-trust: CLEAN — cache hit at <sha7>, measured <ts> on a clock
  judged plausible` (quote the field).

## 2 · TARGET STATE — predicates, RED first (`D-S7CORE13-02`)
- **P-CFG:** for each of `model, effort, repo, timeout_seconds` → `ok` is False and state is byte-unchanged; for each settable key
  a valid value → ok and applied; an unparseable value → refused, state unchanged. RED on `5ad0e45`: quote the `{"ok": True}`.
- **P-CACHE:** a legacy entry (no `clock`) → miss + re-measure + overwrite with `clock: "plausible"`; a judged entry → hit; an
  implausible re-measure → never stored (BASELINE-TRUST-1 unchanged). RED on `5ad0e45`: the legacy entry is a hit.
- **P-LINE:** the cache-hit trust line names the judged field; no line claims "only a plausible leg is cached" for an entry that
  does not carry it.
Each with a negative control.

## 3 · SCOPE / ALLOWED FILES
`queue_daemon.py`, `orchestrator.py` (cache store/lookup/trust-line only), `canon_assert.py` only if a verdict-line set needs its
member, `tests/` (new + the existing tests these touch). **Not** `config/`, **not** `CLAUDE.md` (its model note is owner-guarded —
name the stale line in the handback). Anything else: stop and say why.

## 4 · OUT OF SCOPE — name, leave
`CLAUDE.md`'s UNRATIFIED model note (George); `agents/*` model pins (George); `~/bin` operator scripts (Gemma handles them);
any change to which keys are settable beyond refusing the unsettable ones.

## 5 · ACCEPTANCE
- **AC-OC-01** §0 confirmations (file:line) + a read-only count of live cache entries with / without the `clock` field.
- **AC-OC-02..04** P-CFG, P-CACHE, P-LINE RED→GREEN with negative controls.
- **AC-OC-05** `pytest -q tests/` → 782 + new, 0 failed (foreground).
- **AC-OC-06** diff bounded to §3; two commits max.
- **AC-OC-07** **Daemon restart note:** `queue_daemon.py` changes → say so in the consequence; the operator restarts only when no
  route is live (route 67's pause → restart procedure).

## 6 · HANDBACK
In the Toni log's closing message (orchestrator convention) and `briefs/76-orch-config-truth-1.handback.md`, committed. Found-and-LEFT
first; shipped; gate table; **THE CONSEQUENCE (D-S7CORE13-03)**: `queue_daemon.py config model …` now fails loudly instead of
pretending; the first clinical-mp route per base commit after this merge may spend one extra ~280 s baseline measurement where it
used to trust a pre-GATE-CLOCK-1 cache entry. Check against `config/handback-guard.json` — `CLEAN`.
