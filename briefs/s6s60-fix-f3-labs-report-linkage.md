# Toni Batch S6S60 — FIX-F3: link DiagnosticReport.result to Observations (labs flags/filter/detail empty)

## Repo: clinical-mp
## Batch ID: s6s60-fix-f3-labs-report-linkage
## Briefs: 2
## Estimated runtime: 30-40m
## Predecessor: clinical-mp main @ 51979ed
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 45
## Severity: P1 (labs results UI shows no flags / Abnormal filter returns 0)

## CONTEXT

Synth UAT (B5) found the Labs results UI broken: the abnormal **Flags column is empty**, the
**"Abnormal only" filter returns 0**, and a report's detail shows "No detailed results available" /
"No result observations linked" — even though the Trend panel (which queries Observations directly
by patient+code) works.

Root cause (confirmed in code + live Medplum):
- The abnormal LOGIC is correct: `src/lib/clinical/lab-flag.ts#isObservationAbnormal` already flags
  on reference-range OR interpretation. Not the problem.
- The report-centric views build their observation list ONLY from `DiagnosticReport.result[]`:
  - `src/components/labs/LabResultChartView.tsx` (~L46-58): loops `report.result ?? []`, reads each
    Observation; `hasAbnormal = observations.some(isObservationAbnormal)`.
  - `src/components/labs/LabResultDetail.tsx` (~L34-46): same — observations come only from `result[]`.
- Live Medplum: the synth DiagnosticReports are **orphaned** — for Catherine Hargrove, 0/6 reports
  have `result[]`, 0/6 have `.encounter`, 0/6 have `.basedOn`. So `observations` is always empty ->
  no flags, `hasAbnormal=false` for every report -> "Abnormal only" yields 0.

The Observations exist (Trend uses them); they are simply not linked from the reports. Fix the
linkage (non-disruptive heal of existing data) and harden the seeder so new reports are linked.

## GOAL

Link existing orphaned DiagnosticReports to their Observations, and make the seeder set `result[]`
on creation, so the report-centric Labs views populate (flags, Abnormal filter, detail).

---

## BRIEF F3-1 — heal script: link orphaned DiagnosticReport.result -> Observations

### FILES
- `src/lib/synth/heal-diagnostic-results.ts` (new)
- `src/lib/synth/__tests__/heal-diagnostic-results.test.ts` (new)
- `package.json` (script)

### IMPLEMENT
New script (model the auth/env + dry-run pattern on `src/lib/synth/heal-refs.ts`):
- Page all `DiagnosticReport` (category laboratory if set) where `result` is empty/absent.
- For each, resolve the subject Patient id and the report's `effectiveDateTime` (fallback
  `effectivePeriod.start`); query `Observation?subject=Patient/<id>&category=laboratory&_count=400`.
- Select the Observations whose `effectiveDateTime` falls on the SAME calendar day as the report
  (UTC date match). These are the report's analytes.
- If >=1 match, set `report.result = matches.map(o => ({ reference: 'Observation/' + o.id }))` and
  `updateResource`. Skip if 0 matches (log it).
- Default DRY-RUN (log "would link N obs to report X"); `--fix` performs the writes. Print a summary
  `linked R reports / O observations`.
- Add npm script `"synth:heal-results": "tsx src/lib/synth/heal-diagnostic-results.ts"`.

### ACCEPTANCE
1. Dry-run lists orphaned reports and the obs it would link (no writes).
2. `--fix` populates `result[]`; re-running dry-run then reports 0 remaining orphans for healed reports.
3. Unit test: a report with empty result + 3 same-day lab obs -> 3 result refs after fix; a report
   with a non-matching date -> left untouched.

---

## BRIEF F3-2 — harden the observations seeder to set result[] on creation

### FILES
- `src/lib/synth/seed-script.ts` (the `observations` case that creates DiagnosticReports)
- relevant seeder test if present

### IMPLEMENT
In the `observations` seeding path, when a DiagnosticReport is created for a panel, create/collect
its member Observations FIRST, then set `result: observations.map(o => ({reference:'Observation/'+o.id}))`
on the report before `createResource` (or update right after). Keep existing identifiers/idempotency.
If the current flow creates report before obs, reorder or do a post-create update.

### ACCEPTANCE
1. A freshly seeded DiagnosticReport has a non-empty `result[]` referencing its Observations.
2. Existing seeder behavior (counts, identifiers) otherwise unchanged.

---

## OUT OF SCOPE
- Re-seeding all observations (disruptive; the heal script fixes existing data instead).
- Changing `isObservationAbnormal` (already correct).

## DEFINITION OF DONE
- Heal script links orphaned reports; seeder sets result[] going forward.
- Commit message: `FIX-F3: link DiagnosticReport.result to Observations + heal script (S6S60)`.
- POST-FIRE MANUAL (not Toni): `npm run synth:heal-results -- --fix` vs live Medplum, then in-browser
  verify Labs tab flags column + "Abnormal only" filter + report detail.

## §29 / §31
§29 standard.
§31 smoke (after heal run):
1. Patient chart -> Labs -> results table shows abnormal Flags on out-of-range analytes.
2. Toggle "Abnormal only" -> returns the reports/analytes that are out of range (not 0).
3. Open a report detail -> lists its result Observations (not "No detailed results available").
