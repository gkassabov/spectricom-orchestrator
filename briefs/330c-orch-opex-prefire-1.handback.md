daemon restart by George needed for A12–A14 to apply at fire time

# Handback — 330c ORCH-OPEX-PREFIRE-1 (Kanban SCP_Kanban row 393, S7-CORE-33)

**Outcome: built as specified, no STOP.** A12 / A13 / A14 are in `prefire.py`, the path lists are in `prefire_opex_paths.json`, and `PREFIRE_OPEX=off` is the kill switch. The predicates went from RED on HEAD (80 failed) to GREEN (80 passed). Targeted gates: 621 passed.

## ⚠ Read before the restart: two queued briefs will be refused (P6)

After the restart, the daemon refuses these two briefs at fire time. Each refused brief moves to `queue/failed/`, and with `stop_on_failure=true` the queue pauses (queue_daemon.py:1357-1362). The brief expected "no refusal" in P6. That expectation was wrong on two counts:

| Brief | Row | Refused by | Why | One-line fix (George / Gemma — not done here, outside §2) |
|---|---|---|---|---|
| `337i-tasks-work-1.md` | 387 | **A13** | ALLOWED FILES name `src/lib/agentic-runtime/tools.ts` (the agentic reply-draft writer) and the brief cites no `AP-…` id. §1 assumed "no inventory file yet", but `SCP_Agent_Inventory_v0-1.md` (2026-10-23, 7 ids) is now in the canon folder, so A13 enforces. | add `## Agent policy: AP-CAREMGR` (the care-manager reply drafter; pick the id) |
| `338-device-member-1.md` | 376 | **A14** | ALLOWED FILES name `src/lib/clinical/longevity/device-member-view.ts` (new) and `src/lib/clinical/longevity/device-series.ts` (an export). Both are under `src/lib/clinical/**`, and the brief has no George go line. Its row is outside the 384–392 range the brief checked. | add `## George go: <when> <what>` if George approves; else the route waits |

The alternatives are a one-fire `PREFIRE_OPEX=off` (said loudly in the fire log), or a decision to grandfather A13/A14 below row 393 (R1). Every other queued brief passes (P6 below).

## §0 · FIRST STEP — how prefire reads a brief (premises hold at dd7e346)

- **Shape.** `prefire.py` is pure functions over the brief file and the canon folder. `check(path)` returns the failure strings (empty = cleared), and `report(path)` prints a verdict. `orchestrator.run_batch` calls `prefire.report` (orchestrator.py:5343) unless `--force`. The daemon runs orchestrator with stdout to `logs/…/orch-<stem>-<ts>.log` (queue_daemon.py:1443), so a printed line *is* the fire log.
- **Header lines.** Each assertion has its own `re.MULTILINE` regex over the first `_HEADER_CHARS = 6000` characters (prefire.py:85):
  - `## Estimated runtime:` and `## Micro-fire trigger:` (A2)
  - `## Test scope:` (A9)
  - `## Kanban:` (A1)
  - `## Depends-on:` (A11)
  - The `#!queue … repo=` line is `canon_assert.queue_header`.
  - A8 and A10 scan every line of the file.
- **Sections.** There was **no section parser** before this route: no assertion read a `## <section>` body. A12–A14 add one: `_section`, prefire.py:513.
- **Kanban row lookup (A1).**
  - `_KANBAN_HEADER` (:265) gives `(family, row)` (`parse_kanban_header`, :295).
  - `check_kanban` (:335) takes the newest `<family>_v*.md` in `kanban_dir()`, which is `kanban_dir` in config/repos.yaml, today `/mnt/c/Users/gkass/OneDrive/Documents/Spectricom`. It finds it via `canon_assert.disk_family`.
  - `kanban_states` (:305) reads the State column of every table row whose first cell is the row.
- **A9.** `parse_test_scope` (:232) and `find_full_suite_instructions` (A10, :250). Tested in `tests/test_prefire.py` (P1/P2/D3, :101-290).
- **A11.** `parse_depends_on` (:402) and `dependency_status` (:452), which asks `canon_assert.route_merged`. Tested in `tests/test_depends_on.py`.
- **ALLOWED FILES sections of the briefs in `queue/`** (names only; every one is headed `## 2 · ALLOWED FILES`):
  - **330c:** `prefire.py`, `prefire_opex_paths.json`, the prefire tests, `README`, handback.
  - **330d** (queued during this route, row 394): `orchestrator.py`, `queue_daemon.py`, `executor/settings/*.json`, `executor/hooks/kill_switch.sh`, tests, `README`, handback.
  - **337g:** `src/components/care-plans/**`, `CarePlansTab.tsx`, `next-step-copy.ts`, `materialize-care-plan.ts`, `__tests__`, care-plan SITs, handback.
  - **337g2:** `src/lib/synth/transcripts/{compose,shapes,check,fact-coverage,chart-facts}.ts` + `__tests__/*`, `src/lib/synth/scribe-injector.ts` (+ test), `scripts/synth-scribe.ts`, `scripts/synth-scribe-one.ts`, `src/lib/synth/schedule-generator.ts` (+ test), `sit/journey/l-enrol/invariants.ts`, `synth-fixtures/transcripts/README.md`, handback; **Not** `transcript.md` / fixture `.txt`.
  - **337h:** `src/pages/patient/encounter/**`, `src/lib/encounter/next-steps.ts`, `__tests__`, SITs, handback.
  - **337i:** `TasksQueuePage.tsx`, `src/components/tasks/**`, `action-targets.ts`, `src/lib/agentic-runtime/tools.ts`, `__tests__`, task SITs, handback.
  - **337j:** `AiProvenanceWrapper.tsx`, `synthesis-suggestions.ts`, `__tests__`, handback.
  - **337k:** `EncounterSectionsLayout.tsx`, `AiProvenanceWrapper.tsx`, `encounterSections.ts`, `useEncounterCompose.ts`, `__tests__`, handback.
  - **337l:** `FinalizeBillCodesSection.tsx`, `FinalizeBottomBar.tsx`, `FinalizeFollowUpSection.tsx`, `followup/FollowUpBookSection.tsx`, `src/components/common/FollowUpDatePicker.tsx`, `next-step-copy.ts`, `__tests__`, SITs, handback.
  - **337m:** `negation.ts`, `check-soap-draft.ts`, `vitals-from-text.ts`, `useEncounterCompose.ts`, `__tests__`, handback.
  - **338:** new `src/lib/clinical/longevity/device-member-view.ts`, `src/components/healthspan/MemberDeviceTrendCard.tsx`, `member-device-trend-copy.ts`, `sit/integration/device-member.integration.test.ts`; edit `DeviceDataSection.tsx`, `device-data-copy.ts`, `src/lib/portal/health-snapshot.ts`, `MemberHealthSnapshotBody.tsx`, `ResultRelease.tsx`, `src/lib/clinical/longevity/device-series.ts`, `docs/portal-read-map.md`, `server/allowlist.generated.ts`, `src/lib/capability-register.ts`; **Read only:** `release-to-patient.ts`, `member-access-policy.ts`, `server/fhir-proxy.ts`, ….
  - **340:** new `src/lib/practice-config/timelineTiles.ts`, `src/pages/patient/TimelineTiles.tsx`, `src/pages/patient/tabs/TimelineUpcomingCard.tsx`, `sit/integration/chart-tiles.integration.test.tsx`; edit `PatientPage.tsx`, `tabs/TimelineTab.tsx`, `chartLayout.ts`, `encounterPrefsStore.ts`, `src/hooks/usePractitionerEncounterPrefs.ts`, `ChartLayoutEditorCard.tsx`, `chart-layout-editor-copy.ts`, `src/lib/capability-register.ts`; **Read only:** `componentCatalog.ts`, `permissions.ts`, ….
- **Premises.** They hold: prefire's structure is as §0 assumed, so STOP (b) does not apply. Two facts differ from the brief's text, and neither is a STOP:
  1. The agent inventory exists, which drives the 337i refusal.
  2. The predecessor 392 (330b) did not merge code. It STOPPED (b), and main has only its handback (dd7e346). So the brief's "the executor runs under ORCH-TONI-SANDBOX-1" is not true today; 330d (row 394) re-scopes it. Nothing in this route depends on the sandbox.

## As built

**`prefire.py`.** The A12–A14 block is at :475-774, after A11:

- **Constants:**
  - `OPEX_PATHS` (:481)
  - `OPEX_ENV = "PREFIRE_OPEX"`
  - `OPEX_FROM_ROW = 393` (:483)
  - `OPEX_LABELS = ("Telemetry", "Failure mode", "Rollback", "Agent permissions", "PHI")`
  - `AGENT_INVENTORY = "SCP_Agent_Inventory"`
- **`_section`** (:513): the lines under a `##` heading, up to the next `#`/`##` heading outside a code fence. `every=True` concatenates every matching section, so a multi-brief bundle's ALLOWED FILES are all read.
- **A12 — `check_operability`** (:572), using `operability_answers` (:537):
  - Reads the first `## Operability & safety` section (a trailing `[REQUIRED]` is accepted).
  - A label line is `<label>…: <answer>`, with markdown and the bullet stripped; the label must start with a whole label word. A following line that is neither a label nor a new bullet continues the answer above it.
  - Refused: a missing label, an empty answer, or `none` / `n/a` / `na` / `not applicable` followed by fewer than 3 words.
  - Rows below 393 print exactly `A12 — grandfathered (row N < 393)`.
  - A brief with no Kanban row number is "not judged — A1 refuses the brief". A1 always refuses a brief with no row, so no row-less brief can fire.
- **ALLOWED FILES — `allowed_paths`** (:597):
  - Reads code-span words, plus bare words that have a `/` or a file extension, in order of appearance.
  - On each line, text after `Read only:` / `**Read only:**` / `**Not**` is dropped, because those name no edit.
  - `:<line>` suffixes are dropped.
- **Matching — `_glob_rx` / `path_matches`** (:621 / :636):
  - Globs use gitignore-flavoured grammar and match case-insensitively.
  - A pattern with no `/` matches any one name in the path.
  - A pattern with a `/` matches the path or any directory it sits under.
  - A glob path in ALLOWED FILES (`src/**`) matches when it reaches into the pattern's tree.
- **Path lists — `opex_paths`** (:651): reads the JSON fresh on every call. It returns `*` plus the brief's `repo=` list, or every list when the brief has no `repo=`. If the JSON is unreadable or malformed it raises, and the caller refuses: fail closed.
- **A13 — `check_agent_policy`** (:700):
  - A named agent path requires a cited id from `(?<![A-Za-z0-9-])AP-[A-Z0-9]+(?:-[A-Z0-9]+)*`, found anywhere in the brief, that also appears in the newest `SCP_Agent_Inventory_v*.md` (`disk_family`, same version order as A1).
  - No inventory file → `A13 ⚠ … warning, pass`.
  - Canon folder not a directory, or the inventory unreadable → refusal (fail closed).
- **A14 — `check_george_go`** (:750) and `george_go` (:736):
  - Accepts a `## George go: <text>` line (an empty one does not count), else the first `## Briefs:` / `## Spec reference:` line matching `George[^\n]{0,80}\b(go|GO|agreed|Agree)\b`.
  - A refusal names every protected path and the pattern it matched.
- **`_unjudged`** (:685), shared by A13/A14 when there is no ALLOWED FILES section:
  - row ≥ 393 → refusal (fail closed);
  - row < 393 → a note;
  - no row → left to A1.
- **`_bare_note`** (:678): the clean A13/A14 line says how many names had no directory (see R2).
- **`check_opex`** (:769): returns `[]` when `PREFIRE_OPEX=off` (case-insensitive; any other value keeps the checks on). `check()` appends every ❌ line (:842).
- **`report()`** (:862):
  - prints `⚠⚠ PREFIRE_OPEX=off — A12/A13/A14 … SKIPPED for <brief>` first whenever the switch is off, on both pass and refusal;
  - then prints one line per assertion. On a pass they follow the unchanged A1–A11 pass line; on a refusal, the ❌ lines are bullets and the others print below them.
- The module docstring lists A12–A14 and the kill switch.

**`prefire_opex_paths.json`** (new). The path lists, with a grammar note inside:

| List | Repo | Globs |
|---|---|---|
| `agent_runtime` (A13) | clinical-mp | `src/lib/agentic-runtime/**`, `src/daemon/**`, `src/lib/agentic-drafts/**`, `server/**/agent*` |
| `agent_runtime` (A13) | orchestrator | `orchestrator.py`, `executor/**` |
| `protected` (A14) | `*` (every repo) | `*.env*`, `Dockerfile*`, `docker-compose*`, `*.tf`, `*.tfvars`, `vercel.json`, `netlify.toml`, `fly.toml`, `Procfile`, `.github/workflows/**`, `deploy/**`, `infra/**`, `terraform/**`, `k8s/**`, `helm/**`, `*deploy*.sh` |
| `protected` (A14) | clinical-mp | `src/lib/cds/**`, `src/lib/clinical/**`, `src/lib/fhir/**`, `src/lib/pros/**`, `src/lib/auth/**`, `src/components/auth/**`, `server/auth.ts`, `*access-policy*`, `*accesspolicy*`, `*client-application*`, `*clientapplication*`, `scripts/migrat*` |
| `protected` (A14) | orchestrator | `executor/**`, `orchestrator.py` (the merge code: `merge_branch` :1564, run_batch's merge :5714) |

**Tests.**
- `tests/test_opex_prefire.py` is new: 80 tests.
- In `tests/test_prefire.py`, one pin moved (rule #8, below).

**README.** New "Pre-fire assertions (prefire.py)" section, placed before Project Structure. README had no prefire section, so this one was added.

**Rule #8, one pin moved.** `tests/test_prefire.py::test_D3_report_names_a9_and_a10_and_the_scope_it_passed_on` unpacked `report()`'s pass output into exactly two lines. The brief's Telemetry line orders one line per new assertion, so the pin now reads `passed, scope, *opex` and also asserts that the extra lines are A12, A13, A14. The A1–A11 pass line itself is byte-identical, so no other pin moved.

## Predicates — RED on HEAD, then GREEN

`tests/test_opex_prefire.py` was run against a `git archive HEAD` copy, then on this branch.

**HEAD:** 80 failed.
- The refusal predicates fail on behaviour. HEAD's `check()` returns `[]` for the P1 no-section, P1 `Telemetry: none`, P3 unlisted-id and P4 no-go fixtures (`assert [] == ['A12 ❌ OPERA…']`, `assert [] == ['A13 ❌ AGENT…']`).
- The rest fail on the missing API.

**Branch:** 80 passed.

| | Predicate | Tests |
|---|---|---|
| P1 | Row 393 without the section is refused; with all five lines it passes (`check() == []` plus the ✅ line); `Telemetry: none` is refused, naming Telemetry | Controls: none/n/a with 0–2 words refused, with ≥ 3 passes; an empty answer is refused; a missing label is named; a label must be a whole word (`Phishing risk:` is not PHI); template heading, plain labels and a wrapped answer pass; a code fence holding `# filename:` does not end the section |
| P2 | Row 390 without the section passes as `A12 — grandfathered (row 390 < 393)` | Control: no Kanban row → only A1 refuses |
| P3 | `src/daemon/x.ts` + `AP-DAEMON` listed in a fixture inventory → pass (`… under AP-DAEMON (SCP_Agent_Inventory_v0-1.md)`); unlisted id → refused, naming the path, the listed ids and the unlisted one; no inventory → `A13 ⚠ … warning, pass` | Controls: the newest inventory version is read (v0-10 over v0-1); an unreadable canon folder fails closed; all 4 clinical-mp agent globs are named; orchestrator `orchestrator.py` and `executor/**` need a policy |
| P4 | `src/lib/cds/x.ts` + `## Briefs: 1 (George go 10-23)` → pass; without it → refused, naming `src/lib/cds/x.ts (src/lib/cds/**)` | Controls: `## George go:`, Spec reference "agreed" and Briefs "Agree" are go shapes; an empty `## George go:`, another header, >80 chars between "George" and "go", and "ago" are not; 15 protected and 6 unprotected paths; `Read only:` / `**Not**` dropped; bare paths and `:137` suffixes read; every ALLOWED FILES section read; no `repo=` → every list; no section fails closed from row 393; an unreadable path list fails closed; the data file carries every path §1 names |
| P5 | `PREFIRE_OPEX=Off` → `check_opex == []`, `check() == []` for a brief that fails A12 + A14, `report()` prints the `⚠⚠ … SKIPPED` line and no A12–A14 lines | Control: `""`, `on`, `of`, `0` keep the checks on |

**P6 — live, read-only.** This is `prefire.check` / `check_opex` on every brief in `~/spectricom-orchestrator/queue/` at 2026-10-23 ~19:30. Rows 384 and 392 are in `queue/done/`, so only A12–A14 were run on them. Live P5: `PREFIRE_OPEX=off python3 prefire.py …/337i-tasks-work-1.md` printed the `⚠⚠` line and passed, exit 0.

| Brief | Row | Verdict | A12 | A13 | A14 |
|---|---|---|---|---|---|
| 330c-orch-opex-prefire-1 | 393 | PASS | ✅ five lines | ✅ none | ✅ none |
| 330d-orch-toni-guards-1 | 394 | PASS | ✅ five lines | ✅ `orchestrator.py`, `executor/settings/*.json`, `executor/hooks/kill_switch.sh` under AP-TONI, AP-ORCH | ✅ same paths, `## George go: 10-23 18:08 "agree"` |
| 337g-careplan-embed-1 | 385 | PASS | grandfathered | ✅ none | ✅ none (George T0 bundle go present) |
| 337g2-synth-transcripts-by-reason-1 | 383 | PASS | grandfathered | ✅ none | ✅ none (no go line; none needed) |
| 337h-next-steps-panel-1 | 386 | PASS | grandfathered | ✅ none | ✅ none (bundle go) |
| **337i-tasks-work-1** | 387 | **REFUSED** | grandfathered | ❌ `src/lib/agentic-runtime/tools.ts`, no AP id | ✅ none (bundle go) |
| 337j-ai-marks-ux-1 | 388 | PASS | grandfathered | ✅ none | ✅ none (bundle go) |
| 337k-ap-reason-block-1 | 389 | PASS | grandfathered | ✅ none | ✅ none (bundle go) |
| 337l-finalize-ux-1 | 390 | PASS | grandfathered | ✅ none | ✅ none (bundle go) |
| 337m-small-fixes-24 | 391 | PASS | grandfathered | ✅ none | ✅ none (bundle go) |
| **338-device-member-1** | 376 | **REFUSED** | grandfathered | ✅ none | ❌ `src/lib/clinical/longevity/{device-member-view,device-series}.ts`, no go |
| 340-chart-tiles-1 | 378 | PASS | grandfathered | ✅ none | ✅ none |
| done/337f-phq9-item9-task-truth-1 | 384 | (done) | grandfathered | ✅ none | ✅ none |
| done/330b-orch-toni-sandbox-1 | 392 | (done) | grandfathered | ❌ `orchestrator.py`, `executor/**`, no AP id | ✅ "George go" |

Against §1's expectation ("384–391 carry George's bundle go; 392 carries 'George go'"):
- **A14:** every one of rows 384–392 carries its go; 384 and 392 are done.
- **A13:**
  - 387 (337i) is refused.
  - 392 (330b) would be refused, but it is done.
  - Both cite no AP id because they were written before the inventory existed.

## Gates

- `python3 -m py_compile prefire.py tests/test_opex_prefire.py tests/test_prefire.py`: ok. `prefire_opex_paths.json` parses as JSON.
- Targeted: every test file that imports `prefire` (`test_prefire`, `test_depends_on`, `test_control_scope`, `test_orch_lane`, `test_runtime_parse`, `test_admission_parser`, `test_stale_base`, `test_unit_baseline_gate`) plus `test_opex_prefire`: **621 passed** (541 existing + 80 new), 15.9 s.
- Not run (D-S7CORE30-05): the full suite, which the pre-merge gate runs.
- No daemon restart, no live LLM call, nothing written to canon or clinical-mp. The queue and canon were only read: queue briefs, `SCP_Kanban_v0-462.md` via A1, `SCP_Agent_Inventory_v0-1.md`, the Operability section of `Toni_Brief_Authoring_Template_v1-2.md` to match its label shape, and `git ls-files` of clinical-mp for R2.

## R-items (George)

- **R1 — 337i and 338** (see top). Recommendation: amend the two briefs before the restart (two header lines), which keeps OPX-2/-3 intact.
  - The alternative is to grandfather A13/A14 below row 393, as A12 is. That is one condition in `_unjudged`/`check_opex`, but it would let 338 change `src/lib/clinical/**` without a go.
- **R2 — bare file names.** ALLOWED FILES often name a file without its directory: `negation.ts`, `materialize-care-plan.ts`. A directory glob such as `src/lib/clinical/**` cannot see these.
  - The clean A13/A14 line says so (`(N named without a directory — matched by file name only)`).
  - Measured with read-only `git ls-files` of clinical-mp, resolving bare names would add only 337g `materialize-care-plan.ts` and 337m `negation.ts` / `check-soap-draft.ts`, all under `src/lib/clinical/**`. Both briefs carry the bundle go, so no outcome changes today.
  - Options: (a) an authoring rule that files under a protected or agent directory are written repo-relative; (b) prefire resolves bare names against `git ls-files` of the repo's `project_dir`. That is a new fire-time input, and common names (`index.ts`, `types.ts`) are ambiguous and would have to fail closed.
- **R3 — `orchestrator.py` is matched as a whole file**, for both A13 (fire path) and A14 (merge code). Every brief that edits it needs an AP id and a George go; 330d already has both. If only the fire path should count, it would have to live in its own module (e.g. under `executor/`). A path list cannot see functions.
- **R4 — the `*` list.** §1 lists `*.env*` and deploy/IaC in the clinical-mp clause. I applied them to every repo, because OPX-3 names secrets and production deploys as never-autonomous in general, as does the inventory's "Never-autonomous paths". The visible effect in orchestrator: `scripts/aif-deploy.sh` now needs a go. Move them under `"clinical-mp"` in the JSON if that is not wanted.
- **R5 — A12's 393 applies to every Kanban family**, as §1 says literally. Yorsie_Kanban numbers its rows independently, so a Yorsie brief would come under A12 at its own row 393. A per-family threshold is a small change if wanted.
- **R6 — A13 accepts any listed AP id.** It does not check that the id matches the path: `AP-TONI` cited for `src/daemon/**` passes. A path → policy map could go into the JSON.
- **R7 — matching approximations.**
  - A glob in ALLOWED FILES "reaches" a protected tree by a sample path. `src/**` names `src/lib/cds/**`, but `scripts/*.ts` does not name `scripts/migrat*`.
  - `*.env*` would also match a token such as `process.env.X` written in ALLOWED FILES, which fails closed.

## Found and left

- **`orchestrator.py:5349`.** run_batch's refusal text still reads `pre-fire assertions failed (A1/A2/A8)`. That file is outside §2; the 330 handback already noted it.
- **330d has no Depends-on line.** It is queued with "Predecessor: … at or after 393's merge, else dd7e346" but no `## Depends-on: 330c-orch-opex-prefire-1`. Filename order fires 330c first anyway.
- **The 330c brief's own Agent permissions line** says "the executor runs under ORCH-TONI-SANDBOX-1". It does not: 330b STOPPED, and 330d is the follow-up.
- **The `briefs/330c-orch-opex-prefire-1.md` brief file is untracked** in the route worktree, as it was at the start. Not committed by this route (outside §2).
