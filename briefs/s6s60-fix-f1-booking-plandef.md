# Toni Batch S6S60 — FIX-F1: booking Care-template picker + PlanDefinition seeding (J-F + B7 consolidation)

## Repo: clinical-mp
## Batch ID: s6s60-fix-f1-booking-plandef
## Briefs: 3
## Estimated runtime: 30-45m
## Predecessor: clinical-mp main @ 78c06b4
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 50
## Severity: P0 (blocks visit booking — on Dr. K E2E path)

## CONTEXT

Two synth-UAT findings share one root cause in PlanDefinition handling:

- **J-F (scheduling):** the "New Calendar Event" booking flow is hard-blocked. The required
  "Care template" field renders ZERO selectable options — even for "UAT Diabetes Care Plan",
  which exists. The form fires `GET /fhir/R4/PlanDefinition?name=<q>` on each keystroke and gets
  nothing back, so submit throws "Please fill out required fields." No appointment can be created.
- **B7 (longevity):** the seeded care-plan templates (incl. "Metabolic Longevity Protocol",
  added by FIX-07) are absent from the Assign dropdown and `/outreach` is empty.

Root cause (confirmed in code + live Medplum):
1. `CreateVisit.tsx` (L144-149) uses Medplum's stock `<ResourceInput resourceType="PlanDefinition"
   label="Care template">`, which autocompletes via the **`name`** search param.
2. Every seeded PlanDefinition in `seed-care-plans.ts` sets `title` but **no `name`** (verified:
   zero `name:` lines). So `PlanDefinition?name=<q>` matches nothing -> empty picker -> blocked.
3. The working Assign dialog instead uses `useCarePlanLibrary()` (`src/hooks/useCarePlanLibrary.ts`),
   which queries `PlanDefinition?status=active&_count=100` and filters client-side; it never relies
   on `name`. That path works today.
4. `seedCarePlanTemplates` (seed-care-plans.ts L262) and `seedOutreachHistory` (seed-outreach.ts L30)
   are NOT wired into the `seed-script.ts` CLI dispatch (no `care-plans`/`outreach` case), so they
   were never runnable — which is why the templates are not in live Medplum (FIX-07 landed the code
   but the seed could never be executed).

## GOAL

Make the booking Care-template picker populate from the active care-plan library (not the broken
`name` search), give every seeded PlanDefinition a proper machine `name`, and wire the care-plans +
outreach seeders into the CLI so they can be run. After this lands, a follow-up MANUAL seed run
(`npm run synth:care-plans && npm run synth:outreach`) populates live Medplum — the orchestrator gate
cannot run live seeds (build-green != shipped; D-S6S52-I), so the seed RUN is explicitly a post-fire step.

---

## BRIEF F1-1 — CreateVisit Care-template picker -> useCarePlanLibrary

### FILES
- `src/components/schedule/CreateVisit.tsx`
- `src/components/schedule/CreateVisit.test.tsx`

### IMPLEMENT
Replace the `<ResourceInput name="plandefinition" resourceType="PlanDefinition" label="Care template">`
(L144-149) with a picker backed by `useCarePlanLibrary()`:
- Call `const { definitions, loading } = useCarePlanLibrary();` in the component.
- Render a select/combobox listing `definitions` by `pd.title` (fallback `pd.name ?? pd.id`), value = `pd.id`.
- On change, resolve the chosen `PlanDefinition` from `definitions` and `setPlanDefinitionData(pd)`
  (same state `PlanDefinitionSummary` at L155 consumes).
- Keep the field required (submit still gated on `planDefinitionData`), but it is now satisfiable.
- Show a loading state while `loading`; if `definitions.length === 0`, render a help hint
  ("No care templates — seed via `npm run synth:care-plans`") instead of an empty silent control.

### ACCEPTANCE
1. With >=1 active PlanDefinition in the store, the Care-template control lists it by title and is selectable.
2. Selecting a template sets `planDefinitionData`; `PlanDefinitionSummary` renders; submit proceeds
   (no "fill out required fields" when a template is chosen).
3. Options appear WITHOUT any `PlanDefinition?name=` call (unit test mocks `useCarePlanLibrary` /
   `searchResources('PlanDefinition', {status:'active', ...})`).

---

## BRIEF F1-2 — add machine `name` to every seeded PlanDefinition

### FILES
- `src/lib/synth/seed-care-plans.ts`
- `src/lib/synth/__tests__/seed-care-plans.test.ts`

### IMPLEMENT
Add a FHIR `name` (machine-readable, PascalCase, no spaces) to EACH PlanDefinition template object in
the `seedCarePlanTemplates` upsert set (ANNUAL_PHYSICAL, HRT_MALE, WEIGHT_LOSS_GLP1, METABOLIC_LONGEVITY,
and any others), derived from the title — e.g. `name: 'ConciergeAnnualPhysical'`,
`name: 'MetabolicLongevityProtocol'`. Keep `title` unchanged. FHIR hygiene + restores name-based lookup.

### ACCEPTANCE
1. Every template in the upsert set has a non-empty `name` matching `^[A-Za-z][A-Za-z0-9]*$`.
2. Existing seed test passes; extend it to assert each template has a `name`.

---

## BRIEF F1-3 — wire care-plans + outreach into the seed CLI

### FILES
- `src/lib/synth/seed-script.ts`  (dispatch switch + `default:` Usage string)
- `package.json`  (scripts)

### IMPLEMENT
Add to the `seed-script.ts` command switch (alongside the other `case` blocks):
```
case 'care-plans': {
  const { seedCarePlanTemplates } = await import('./seed-care-plans');
  await seedCarePlanTemplates(medplum);
  break;
}
case 'outreach': {
  const { seedOutreachHistory } = await import('./seed-outreach');
  await seedOutreachHistory(medplum);
  break;
}
```
Add `care-plans` and `outreach` to the `default:` Usage string. Add npm scripts mirroring the existing
pattern: `"synth:care-plans": "tsx src/lib/synth/seed-script.ts care-plans"` and
`"synth:outreach": "tsx src/lib/synth/seed-script.ts outreach"`.

### ACCEPTANCE
1. `seed-script.ts care-plans` / `seed-script.ts outreach` dispatch to the respective seeders.
2. Usage string lists both new commands.
3. `npm run synth:care-plans` / `npm run synth:outreach` exist in package.json.

---

## OUT OF SCOPE
- Reschedule / cancel / double-booking guard (Medplum Scheduling Alpha — separate backlog).
- Running the seeds against live Medplum (post-fire MANUAL step; gate cannot seed).
- Migrating the Assign dialog (already correct via useCarePlanLibrary).

## DEFINITION OF DONE
- Booking Care-template picker populates from useCarePlanLibrary; booking submits.
- Every seeded PlanDefinition has a machine `name`.
- `care-plans` + `outreach` CLI cases + npm scripts exist.
- Commit message: `FIX-F1: booking care-template picker via useCarePlanLibrary + PlanDefinition name + seed CLI wiring (S6S60)`.
- POST-FIRE MANUAL (not Toni): `npm run synth:care-plans && npm run synth:outreach` vs live Medplum, then in-browser verify booking picker + Assign dropdown + /outreach.

## §29 / §31
§29 standard.
§31 smoke:
1. Calendar -> New Calendar Event -> fill Practitioner/Patient/time/class.
2. Open "Care template" -> options listed by title (after seed run: Annual Physical, HRT, GLP-1, Metabolic Longevity, + UAT Diabetes).
3. Select one -> PlanDefinitionSummary renders -> Submit -> appointment created (no "fill out required fields").
4. Patient chart -> Assign care plan -> "Metabolic Longevity Protocol" present.
