no daemon restart needed: the daemon runs a fresh `orchestrator.py` for each route, and `prefire.report` runs inside it, so the OPX-1/-2/-3 labels show from the first fire after merge. The daemon itself calls only `prefire.dependency_status`, which has no label.

# Handback — 330e ORCH-PREFIRE-RENAME-1 (SCP_Kanban row 395, S7-CORE-33, batch s7core33-orch-prefire-rename-1)

**Outcome: built as specified, no STOP.**
- The three 330c checks are now labelled OPX-1 (was A12), OPX-2 (was A13) and OPX-3 (was A14). This covers prefire output, refusal messages, docstrings and comments, test names, test expectations and the README.
- No pass/refuse decision changed. P1 compared 761 recorded decisions on 149 tests against HEAD: 0 differ. P2 ran all 12 live-queue briefs: the pass/refuse set is the same, and `A1[234]` appears in no output line.
- `PREFIRE_OPEX=off` keeps its name. The README says so in one line.
- Gates: `py_compile` passed. The 9 targeted test files passed: 637 tests.

## §0 · FIRST STEP — every `A12` / `A13` / `A14` at HEAD (`dae7b23`)

There are 97 lines in the five named files. 96 are the 330c checks. One is not: `prefire.py:456` (the `dependency_status` docstring) is SESSION-BOOT's A13, "one owner per fact". That line is left as it is.

Outside the named files, a repo-wide `git grep` finds only `canon_assert.py:547` and `tests/test_depends_on.py:15,377`. Both are SESSION-BOOT's A13, the same "one merged-route predicate" meaning, and both are left as they are.

```
[330c]             README.md:125  | A12 (OPX-1) | Kanban row ≥ 393 | `## Operability & safety` has non-empty `Telemetry:`, `Failure mode…:`, …
[330c]             README.md:126  | A13 (OPX-2) | ALLOWED FILES name an agent-runtime path | the brief cites an `AP-…` id listed in the newes…
[330c]             README.md:127  | A14 (OPX-3) | ALLOWED FILES name a never-autonomous path | the brief has a `## George go:` line, or a `##…
[330c]             README.md:130  - A13 and A14 read the ALLOWED FILES section(s): code spans, and bare words with a `/` or a file extension.…
[330c]             README.md:132  - Kill switch: `PREFIRE_OPEX=off` skips A12–A14 and prints a `⚠⚠ PREFIRE_OPEX=off … SKIPPED` line on every …
[330c]             prefire.py:40  A12 operability   — a brief on Kanban row >= 393 has '## Operability & safety' with a non-empty Telemetry: /
[330c]             prefire.py:43  A13 agent policy  — ALLOWED FILES naming an agent-runtime path (prefire_opex_paths.json `agent_runtime`) ⇒ the
[330c]             prefire.py:46  A14 George go     — ALLOWED FILES naming a never-autonomous path (prefire_opex_paths.json `protected`) ⇒ a
[330c]             prefire.py:48  OPX-3.  A13/A14 refuse a brief on row >= 393 with no ALLOWED FILES section (fail closed).
[330c]             prefire.py:53  and logs a warning.  The one narrower override is PREFIRE_OPEX=off, which skips A12-A14 only and says so on
[SESSION-BOOT A13] prefire.py:456  canon_assert.route_merged's answer and nobody else's (A13). No line ⇒ ([], None), and nothing is asked."""
[330c]             prefire.py:475  # ── A12-A14: the OpEx pre-checks ─────────────────────────────────────────────
[330c]             prefire.py:477  # MANDATORY — absence must block something. OPX-1 (A12): the brief says how its change is seen, degrades, i…
[330c]             prefire.py:479  # `## Operability & safety`). OPX-2 (A13): agent-runtime code changes under a cited Agent Policy. OPX-3 (A1…
[330c]             prefire.py:482  OPEX_ENV = "PREFIRE_OPEX"                 # =off skips A12-A14, said on every fire
[330c]             prefire.py:483  OPEX_FROM_ROW = 393                       # A12: rows below were written before OPX-1 — grandfathered
[330c]             prefire.py:503  """One of A12-A14 on one brief: `line` is what prefire prints ('A12 ✅ …', 'A12 ❌ …', 'A13 ⚠ …', 'A12 — …')."""
[330c]             prefire.py:573  """A12 (OPX-1). A brief whose Kanban row is ≥ OPEX_FROM_ROW carries `## Operability & safety` with a non-empty
[330c]             prefire.py:578  return OpexVerdict(True, "A12 — not judged: no Kanban row number (A1 refuses the brief)")
[330c]             prefire.py:580  return OpexVerdict(True, "A12 — grandfathered (row %d < %d)" % (row, OPEX_FROM_ROW))
[330c]             prefire.py:589  return OpexVerdict(True, "A12 ✅ Operability & safety — Telemetry · Failure mode · Rollback · Agent "
[330c]             prefire.py:591  return OpexVerdict(False, "A12 ❌ OPERABILITY — row %d ≥ %d (D-S7CORE33-20 OPX-1) and the brief %s. Five non…
[330c]             prefire.py:679  """A13/A14's clean line says how many paths carried no directory: `negation.ts` is matched by its name only…
[330c]             prefire.py:686  """A13/A14 before their own question: no ALLOWED FILES section is a refusal from row OPEX_FROM_ROW on (they…
[330c]             prefire.py:701  """A13 (OPX-2). ALLOWED FILES naming an agent-runtime path ⇒ the brief cites an Agent Policy id (AP-…) that…
[330c]             prefire.py:704  early = _unjudged("A13", filepath, paths)
[330c]             prefire.py:710  return OpexVerdict(False, "A13 ❌ AGENT-POLICY — the agent-runtime path list cannot be read: %s (fails close…
[330c]             prefire.py:712  return OpexVerdict(True, "A13 ✅ no agent-runtime path in ALLOWED FILES" + _bare_note(paths))
[330c]             prefire.py:715  return OpexVerdict(False, "A13 ❌ AGENT-POLICY — ALLOWED FILES name agent-runtime path(s) %s and the canon f…
[330c]             prefire.py:719  return OpexVerdict(True, "A13 ⚠ agent-runtime path(s) %s — no %s_v*.md in %s yet, so no policy id can be "
[330c]             prefire.py:724  return OpexVerdict(False, "A13 ❌ AGENT-POLICY — %s unreadable (%s), so no policy id can be checked (fails "
[330c]             prefire.py:729  return OpexVerdict(True, "A13 ✅ agent-runtime path(s) %s under %s (%s)" % (_list(named), ", ".join(good), n…
[330c]             prefire.py:730  return OpexVerdict(False, "A13 ❌ AGENT-POLICY — ALLOWED FILES name agent-runtime path(s) %s and the brief c…
[330c]             prefire.py:737  """A14: the brief's George go — a `## George go: …` line, else the first `## Briefs:` / `## Spec reference:…
[330c]             prefire.py:751  """A14 (OPX-3). ALLOWED FILES naming a never-autonomous path ⇒ the brief carries a George go."""
[330c]             prefire.py:752  early = _unjudged("A14", filepath, paths)
[330c]             prefire.py:758  return OpexVerdict(False, "A14 ❌ NEVER-AUTONOMOUS — the protected path list cannot be read: %s (fails close…
[330c]             prefire.py:760  return OpexVerdict(True, "A14 ✅ no never-autonomous path in ALLOWED FILES" + _bare_note(paths))
[330c]             prefire.py:763  return OpexVerdict(True, "A14 ✅ never-autonomous path(s) %s — George go: '%s'" % (_list(named), go[:100]))
[330c]             prefire.py:764  return OpexVerdict(False, "A14 ❌ NEVER-AUTONOMOUS — ALLOWED FILES name protected path(s) %s and the brief c…
[330c]             prefire.py:770  """A12, A13, A14 — [] when PREFIRE_OPEX=off (report() says so, loudly)."""
[330c]             prefire.py:842  failures += [v.line for v in check_opex(filepath) if not v.ok]     # A12-A14 [ORCH-OPEX-PREFIRE-1]
[330c]             prefire.py:867  print("  ⚠⚠ %s=off — A12/A13/A14 (D-S7CORE33-20 OPX-1/-2/-3: Operability & safety, agent policy, George go) "
[330c]             prefire.py:869  opex = [v.line for v in check_opex(filepath) if v.ok]               # A12-A14: one line each; a ❌ is a failure
[330c]             prefire_opex_paths.json:2  "_about": "[ORCH-OPEX-PREFIRE-1] D-S7CORE33-20 (Codex v2-57). The paths prefire's A13 (OPX-2) and A14 (OPX-…
[330c]             prefire_opex_paths.json:4  "_about": "A13 (OPX-2): code an agent runs on. A brief naming one cites an Agent Policy id (AP-…) listed in…
[330c]             prefire_opex_paths.json:18  "_about": "A14 (OPX-3): never-autonomous paths. A brief naming one carries a George go (`## George go:` lin…
[330c]             tests/test_opex_prefire.py:1  """[ORCH-OPEX-PREFIRE-1] D-S7CORE33-20 OPX-1/-2/-3 as prefire A12 (Operability & safety), A13 (agent policy…
[330c]             tests/test_opex_prefire.py:2  A14 (George go) — predicates P1-P5 of briefs/330c-orch-opex-prefire-1.md, and their controls."""
[330c]             tests/test_opex_prefire.py:53  # ── P1 · A12: a row-393 brief carries its Operability & safety section ──────
[330c]             tests/test_opex_prefire.py:56  assert [f for f in fails if f.startswith("A12")] == [
[330c]             tests/test_opex_prefire.py:57  "A12 ❌ OPERABILITY — row 393 ≥ 393 (D-S7CORE33-20 OPX-1) and the brief has no '## Operability & safety' "
[330c]             tests/test_opex_prefire.py:66  assert opex(b)["A12"].line == ("A12 ✅ Operability & safety — Telemetry · Failure mode · Rollback · Agent "
[330c]             tests/test_opex_prefire.py:74  assert len(fails) == 1 and fails[0].startswith("A12 ❌ OPERABILITY — row 393 ≥ 393"), fails
[330c]             tests/test_opex_prefire.py:86  assert opex(b)["A12"].ok is ok, opex(b)["A12"].line
[330c]             tests/test_opex_prefire.py:91  line = opex(b)["A12"].line
[330c]             tests/test_opex_prefire.py:92  assert not opex(b)["A12"].ok and "'## Operability & safety' has no Rollback, PHI line" in line
[330c]             tests/test_opex_prefire.py:100  assert opex(brief(tmp_path, opex=text))["A12"].ok
[330c]             tests/test_opex_prefire.py:105  assert not opex(b)["A12"].ok and "has no PHI line" in opex(b)["A12"].line
[330c]             tests/test_opex_prefire.py:110  assert not opex(b)["A12"].ok and "Rollback: empty" in opex(b)["A12"].line
[330c]             tests/test_opex_prefire.py:115  assert opex(brief(tmp_path, opex=fenced))["A12"].ok
[330c]             tests/test_opex_prefire.py:118  # ── P2 · A12: rows below 393 are grandfathered ──────────────────────────────
[330c]             tests/test_opex_prefire.py:122  assert opex(b)["A12"] == prefire.OpexVerdict(True, "A12 — grandfathered (row 390 < 393)")
[330c]             tests/test_opex_prefire.py:130  assert opex(b)["A12"].line == "A12 — not judged: no Kanban row number (A1 refuses the brief)"
[330c]             tests/test_opex_prefire.py:133  # ── P3 · A13: agent-runtime code is changed under a listed Agent Policy ─────
[330c]             tests/test_opex_prefire.py:138  assert opex(b)["A13"].line == ("A13 ✅ agent-runtime path(s) src/daemon/x.ts (src/daemon/**) under AP-DAEMON "
[330c]             tests/test_opex_prefire.py:146  "A13 ❌ AGENT-POLICY — ALLOWED FILES name agent-runtime path(s) src/daemon/x.ts (src/daemon/**) and the brief "
[330c]             tests/test_opex_prefire.py:154  assert opex(b)["A13"].line == ("A13 ⚠ agent-runtime path(s) src/daemon/x.ts (src/daemon/**) — no "
[330c]             tests/test_opex_prefire.py:163  assert not opex(b)["A13"].ok and "SCP_Agent_Inventory_v0-10.md lists (AP-TONI)" in opex(b)["A13"].line
[330c]             tests/test_opex_prefire.py:177  assert not opex(brief(tmp_path, allowed="`%s`" % path))["A13"].ok
[330c]             tests/test_opex_prefire.py:183  assert not opex(brief(tmp_path, allowed=allowed, repo="orchestrator"))["A13"].ok
[330c]             tests/test_opex_prefire.py:184  assert opex(brief(tmp_path, allowed=allowed, repo="orchestrator", header="## Agent policy: AP-TONI\n"))["A1…
[330c]             tests/test_opex_prefire.py:187  # ── P4 · A14: a never-autonomous path is changed only on George's go ────────
[330c]             tests/test_opex_prefire.py:191  assert opex(b)["A14"].line == "A14 ✅ never-autonomous path(s) src/lib/cds/x.ts (src/lib/cds/**) — George go…
[330c]             tests/test_opex_prefire.py:197  "A14 ❌ NEVER-AUTONOMOUS — ALLOWED FILES name protected path(s) src/lib/cds/x.ts (src/lib/cds/**) and the br…
[330c]             tests/test_opex_prefire.py:206  assert opex(brief(tmp_path, allowed="`src/lib/clinical/x.ts`", header=header))["A14"].ok
[330c]             tests/test_opex_prefire.py:213  assert not opex(brief(tmp_path, allowed="`src/lib/clinical/x.ts`", header=header))["A14"].ok
[330c]             tests/test_opex_prefire.py:222  assert not opex(brief(tmp_path, allowed="`%s`" % path))["A14"].ok
[330c]             tests/test_opex_prefire.py:228  assert opex(brief(tmp_path, allowed="`%s`" % path))["A14"].ok
[330c]             tests/test_opex_prefire.py:235  assert opex(b)["A14"].ok
[330c]             tests/test_opex_prefire.py:244  line = opex(brief(tmp_path, allowed="`negation.ts`, `check-soap-draft.ts`, their `__tests__`"))["A14"].line
[330c]             tests/test_opex_prefire.py:245  assert line == ("A14 ✅ no never-autonomous path in ALLOWED FILES (2 named without a directory — matched by …
[330c]             tests/test_opex_prefire.py:251  assert not opex(b)["A14"].ok
[330c]             tests/test_opex_prefire.py:255  assert not opex(brief(tmp_path, allowed="`executor/x.sh`", repo=None))["A14"].ok
[330c]             tests/test_opex_prefire.py:261  assert (v["A13"].ok, v["A14"].ok) == (ok, ok), (v["A13"].line, v["A14"].line)
[330c]             tests/test_opex_prefire.py:269  assert not v["A13"].ok and not v["A14"].ok
[330c]             tests/test_opex_prefire.py:270  assert "paths.json unreadable" in v["A14"].line and "(fails closed)" in v["A14"].line
[330c]             tests/test_opex_prefire.py:284  # ── P5 · PREFIRE_OPEX=off skips A12-A14, loudly ─────────────────────────────
[330c]             tests/test_opex_prefire.py:287  assert len(prefire.check(b)) == 2                      # A12 + A14 (no inventory: A13 warns)
[330c]             tests/test_opex_prefire.py:292  assert ("⚠⚠ PREFIRE_OPEX=off — A12/A13/A14 (D-S7CORE33-20 OPX-1/-2/-3: Operability & safety, agent policy, "
[330c]             tests/test_opex_prefire.py:294  assert "A12 " not in out.replace("A12/A13/A14", "")
[330c]             tests/test_opex_prefire.py:300  assert [f[:3] for f in prefire.check(brief(tmp_path, opex=""))] == ["A12"]
[330c]             tests/test_opex_prefire.py:308  assert [l.split()[0:2] for l in out[2:]] == [["A12", "✅"], ["A13", "✅"], ["A14", "✅"]]
[330c]             tests/test_opex_prefire.py:314  assert "  • A14 ❌ NEVER-AUTONOMOUS — ALLOWED FILES name protected path(s) src/lib/cds/x.ts" in out
[330c]             tests/test_opex_prefire.py:315  assert "  A12 — grandfathered (row 390 < 393)\n  A13 ✅ no agent-runtime path in ALLOWED FILES\n" in out
[330c]             tests/test_prefire.py:261  # rule #8 [ORCH-OPEX-PREFIRE-1]: A12/A13/A14 print one line each after these two (tests/test_opex_prefire.py)
[330c]             tests/test_prefire.py:265  assert [l.split()[0] for l in opex] == ["A12", "A13", "A14"]
```

## As built

**`prefire.py`** (45 insertions, 43 deletions; no logic line changed):
- **Labels.** Every `OpexVerdict` line now starts with `OPX-1` / `OPX-2` / `OPX-3`: 8 pass lines, 7 refusal lines, and `_unjudged("OPX-2" | "OPX-3", …)` at :706/:754.
- **Redundant OPX id dropped.** Four messages ended with `(D-S7CORE33-20 OPX-n)` after the label. They now end with `(D-S7CORE33-20)`, so they do not read `OPX-1 ❌ … (D-S7CORE33-20 OPX-1)`.
- **The `⚠⚠` line** (:869) now reads `⚠⚠ PREFIRE_OPEX=off — OPX-1/-2/-3 (D-S7CORE33-20: Operability & safety, agent policy, George go) SKIPPED for <brief>. …`.
- **Docstrings and comments.** These are the module docstring's ENFORCED list (:40-48), the bypass paragraph, the section rule (:476), `OPEX_ENV` / `OPEX_FROM_ROW`, `OpexVerdict`, the three check docstrings, `_bare_note`, `_unjudged`, `george_go`, `check_opex`, and the two comments in `check` / `report`.
- **New line (:51).** `OPX-1/-2/-3 were labelled A12-A14 until ORCH-PREFIRE-RENAME-1: SESSION-BOOT's A12 and A13 are other checks.`
- **Function names were already label-free** (`check_operability`, `check_agent_policy`, `check_george_go`, `check_opex`), so none changed.
- **Unchanged.** The A1–A11 pass line, every other A-numbered assertion, and `OPEX_ENV = "PREFIRE_OPEX"`.

**`README.md`.**
- The OpEx table rows read `OPX-1` / `OPX-2` / `OPX-3`. Before, they read `A12 (OPX-1)` and so on.
- The grandfathered example and the ALLOWED FILES bullet now use the new labels.
- The kill-switch bullet adds "The variable kept its name through the rename below."
- New bullet: "Old labels (ORCH-PREFIRE-RENAME-1): OPX-1, OPX-2 and OPX-3 were A12, A13 and A14 until route 330e. They were renamed because SESSION-BOOT's PRE-FIRE ASSERTION BLOCK uses A12 and A13 for other checks. Every pass/refuse decision is unchanged."

**Tests (rule #8). Every changed pin is a label change that §1 authorises. No ok/refuse expectation moved; P1 verifies this.**
- `tests/test_opex_prefire.py`:
  - Every expected label and line now uses the new label, and `opex(b)["A12"]` lookups now read `opex(b)["OPX-1"]` (and so on).
  - The four expected messages lose the trailing ` OPX-n`.
  - Two tests are renamed: `test_P5_prefire_opex_off_skips_a12_to_a14_with_a_loud_line` → `…_skips_opx_1_to_3_…`, and `test_report_prints_a12_a13_a14_after_the_unchanged_pass_line` → `test_report_prints_opx_1_2_3_…`.
  - The P5 "no verdict line" assertion was `"A12 " not in out…`. It is now `"  OPX-" not in out`, so it covers all three labels.
  - The P5 control compared `f[:3]`. It now compares `f.split()[0]`, because `OPX-1` is 5 characters.
  - One test is new: `test_rename_no_output_line_carries_a12_a13_or_a14` (16 cases). It covers 8 fixtures: pass, no section, grandfathered without ALLOWED FILES, no ALLOWED FILES at row 393, no Kanban row, refusal, unreadable path list, and listed policy. Each fixture runs with `PREFIRE_OPEX` on and off. The test asserts that `report()` output, `check()` and `check_opex()` lines carry `OPX-` and never `\bA1[234]\b`.
- `tests/test_prefire.py:266` — 330c's rule-#8 pin now reads `["OPX-1", "OPX-2", "OPX-3"]`, and its comment says the checks were A12/A13/A14.

## P1 — the 330c predicate suite, decisions identical to HEAD

**Method.**
- A `git archive HEAD` copy and this branch each ran their own `tests/test_opex_prefire.py` + `tests/test_prefire.py`.
- A pytest plugin wrapped `check_operability`, `check_agent_policy`, `check_george_go`, `check_opex`, `check` and `report`. For every call during each test, it recorded:
  - each verdict's `ok`, label and mark (✅ / ❌ / ⚠ / —);
  - `check()`'s failure labels;
  - `report()`'s bool.
- The old labels were mapped to the new ones before comparing.

**Results.**
- HEAD: 149 passed. Branch: 165 passed (the 149, plus the 16 new cases).
- 149 tests are on both sides, with 761 decisions recorded per side. **Tests with a differing decision sequence: 0.**
- Aggregate, the same on both sides:

| decision | HEAD | branch |
|---|---|---|
| `check()` pass / refuse | 44 / 45 | 44 / 45 |
| OPX-1 ✅ / — / ❌ | 64 / 81 / 20 | 64 / 81 / 20 |
| OPX-2 ✅ / ⚠ / — / ❌ | 73 / 5 / 75 / 13 | 73 / 5 / 75 / 13 |
| OPX-3 ✅ / — / ❌ | 59 / 75 / 31 | 59 / 75 / 31 |
| `report()` True / False | 3 / 4 | 3 / 4 |

- **Full text.** The same plugin also recorded every verdict line and `check()` failure as text. HEAD's text was rewritten with only this route's two edits: the leading label, and `(D-S7CORE33-20 OPX-n)` → `(D-S7CORE33-20)`. pytest temp-dir numbers were also normalised. After that, HEAD's text equals the branch's in all 149 tests.
- **RED.** The branch's tests run against HEAD's code: 94 failed, 71 passed. The 94 include all 16 cases of the new test; every failure is a lookup or comparison on the new label.

## P2 — the live queue, read-only

Every brief in `~/spectricom-orchestrator/queue/` (12, top level) was run through HEAD's copy and this branch's `python3 prefire.py <brief>`, one brief at a time, back to back (2026-10-23 21:52–21:54).

| brief | HEAD exit | branch exit | HEAD output, label-mapped, vs branch |
|---|---|---|---|
| 330e-orch-prefire-rename-1 | 0 | 0 | identical |
| 337g2-synth-transcripts-by-reason-1 | 0 | 0 | identical |
| 337g3-data-hygiene-1 | 0 | 0 | identical |
| 337h-next-steps-panel-1 | 0 | 0 | identical |
| 337i-tasks-work-1 | 0 | 0 | identical |
| 337j-ai-marks-ux-1 | 0 | 0 | identical |
| 337k-ap-reason-block-1 | 0 | 0 | identical |
| 337l-finalize-ux-1 | 0 | 0 | identical |
| 337m-small-fixes-24 | 0 | 0 | identical |
| 338-device-member-1 | 0 | 0 | identical |
| 339a-orch-openshell-eval-1 | 0 | 0 | identical |
| 340-chart-tiles-1 | 0 | 0 | identical |

- **`grep -n "A1[234]"` on the branch's output for all 12 briefs: nothing** (grep exit 1). HEAD's output had 3 such lines per brief.
- **Same pass/refuse set: 12 pass on both sides, 0 refused.** Both briefs that 330c's P6 saw refused now pass on HEAD and on the branch alike. For example, 337i now cites `AP-CAREMGR`.
- Sample branch output (337i):
  - `OPX-1 — grandfathered (row 387 < 393)`
  - `OPX-2 ✅ agent-runtime path(s) src/lib/agentic-runtime/tools.ts (src/lib/agentic-runtime/**) under AP-CAREMGR (SCP_Agent_Inventory_v0-1.md)`
  - `OPX-3 ✅ no never-autonomous path in ALLOWED FILES (2 named without a directory — matched by file name only)`
- **Live kill switch.** `PREFIRE_OPEX=off python3 prefire.py …/337i-tasks-work-1.md` printed `⚠⚠ PREFIRE_OPEX=off — OPX-1/-2/-3 (D-S7CORE33-20: …) SKIPPED for 337i-tasks-work-1.md. …` and exit 0.

## STOP check

- **(a) Decision change: none.** P1 and P2 above.
- **(b) Label used outside prefire: none.**
  - Repo: the only `A13` outside prefire's files is SESSION-BOOT's (§0).
  - Nothing parses a verdict line. `orchestrator.py:5445` uses only `report()`'s bool, and `queue_daemon.py:1090` uses only `dependency_status`. Nothing outside prefire's own files reads `PREFIRE_OPEX`.
  - A search of `~/spectricom-orchestrator`, `~/bin` and `~/*.md` for the old verdict shapes (`A12 ✅`, `A13 (OPX`, `A12-A14`, `A12/A13/A14`, …) found only prefire and its tests.
- **(c) Daemon restart: none.** None was done, and none is needed (first line).

## Gates

- `python3 -m py_compile prefire.py tests/test_opex_prefire.py tests/test_prefire.py`: ok.
- Targeted: every test file that references `prefire` — `test_admission_parser`, `test_control_scope`, `test_depends_on`, `test_opex_prefire`, `test_orch_lane`, `test_prefire`, `test_runtime_parse`, `test_stale_base`, `test_unit_baseline_gate`. **637 passed.**
- Not run (D-S7CORE30-05): the full suite or a baseline. The pre-merge gate runs them next.
- No daemon restart, no LLM call. Nothing was written outside this worktree except scratch files in `/tmp/p330e/` (the HEAD copy, the recorder, the outputs). The queue, canon and git refs were only read.

## Found and left

- **`prefire_opex_paths.json` `_about` notes (:2, :4, :18) still say "A13 (OPX-2)" / "A14 (OPX-3)".**
  - §0 names the file, but §2 does not allow it, so it is not edited.
  - These are notes only: keys starting `_` are never read as paths, and prefire never prints them. So no output carries them, and P2 holds.
  - Fix: drop `A13 (` / `A14 (` and the closing `)` in a brief that allows the file.
- **This brief says "orchestrator prefire code is a protected path", but the data does not list it.** `prefire_opex_paths.json` `protected.orchestrator` lists only `executor/**` and `orchestrator.py`, and `agent_runtime.orchestrator` lists `orchestrator.py` and `executor/**`. So OPX-3 on this brief reads "no never-autonomous path in ALLOWED FILES". If prefire's own files should need a George go, add `prefire.py` and `prefire_opex_paths.json` to `protected.orchestrator` (George's call).
- **Historical text keeps the old labels**: the 330c handback, its commit messages, and fire logs. Not rewritten, by design. The README line maps them.
- **The `briefs/330e-orch-prefire-rename-1.md` brief file is untracked** in the route worktree, as it was at the start. It is not committed by this route (outside §2).
