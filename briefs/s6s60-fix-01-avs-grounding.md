# Toni Batch S6S60 — FIX-01: AVS grounding (allergies / meds / plan / provider)

## Repo: clinical-mp
## Batch ID: s6s60-fix-01-avs-grounding
## Briefs: 1
## Estimated runtime: 20-30m
## Predecessor: clinical-mp main @ a617327
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 35
## Severity: P0 (patient-safety)

## CONTEXT

Synth UAT (Dr. Whitman, Catherine Hargrove encounter) found the After-Visit Summary
**denies a documented critical allergy**: it prints "ALLERGIES • No known allergies" for a
patient with Penicillin (critical) + Ibuprofen/NSAID — allergies that are visible in the
left rail and that fired an allergy CDS alert during prescribing. The AVS also omits the
medication list and the plan, and stamps "Provider: Provider".

Root cause (confirmed in code): `FinalizePage.tsx` builds the grounded `avsPayload` via an
inline `useMemo` (~line 214) that **hardcodes**:
  - `allergies: []`            → `formatAvsAsText` therefore always emits "No known allergies"
  - `providerName: 'Provider'` → the literal placeholder seen in the AVS
  - `medications` / `planItems` sourced ONLY from `composeState.structuredPlanItems`, so real
    prescribed `MedicationRequest`s and the narrative plan never appear.

The data is already in scope: the page loads `avsClinical` (which exposes `.allergies` and
`.medicationRequests`, already passed into `avsInput` at ~line 178), and there is a canonical,
tested composer `composeAvs()` in `src/lib/clinical/avs/compose-avs.ts` with helpers
`extractAllergies` / `extractMedications` / `practitionerDisplayName` that do this correctly
from FHIR. The grounding validator `src/lib/clinical/avs/validate-avs-grounding.ts` exists to
enforce allergy/med parity but never gets a populated payload to check.

This is NOT an LLM hallucination — it is a hardcoded-empty data-wiring defect. "Regenerate"
cannot fix it.

## GOAL

Populate the finalize `avsPayload` with the patient's real allergies, medications, and the
signing provider's name, so the Clinical AVS is grounded and the Patient-friendly rewrite is
validated against true allergies/meds. NKDA must appear only when the allergy list is genuinely
empty.

## FILES

- `src/pages/patient/encounter/FinalizePage.tsx` — the `avsPayload` useMemo (~line 214).
- `src/lib/clinical/avs/compose-avs.ts` — export `extractAllergies`, `extractMedications`,
  `practitionerDisplayName` (currently module-private) so the memo reuses them (no logic drift).
- `src/lib/clinical/avs/__tests__/compose-avs.test.ts` — extend (allergy population).
- `src/pages/patient/encounter/FinalizePage.test.tsx` — assert AVS payload allergies/provider.

## ACCEPTANCE CRITERIA

1. **Allergies grounded.** For a patient with charted `AllergyIntolerance`, the Clinical AVS
   lists each allergy (label + criticality/reaction). "No known allergies" appears ONLY when
   the patient truly has zero active allergies.
2. **Medications grounded.** The AVS Medications section includes the encounter's prescribed
   meds and continued active meds (from `avsClinical.medicationRequests`), de-duplicated, in
   addition to any structured plan-item meds.
3. **Plan present.** The AVS Plan section reflects the finalize plan (structured plan items
   and/or narrative plan), not empty.
4. **Provider name real.** `providerName` is the signing practitioner's display name
   (`medplum.getProfile()`), never the literal "Provider". Falls back to "Your Care Team" only
   if no profile name is resolvable.
5. **Patient-friendly rewrite stays grounded.** The patient-friendly toggle still routes through
   `rewriteAvsForPatient` + the grounding validator; the rewrite must not drop/add allergies or
   meds relative to the grounded payload (validator passes).
6. **PDF + Send-to-Portal unaffected** — both already consume `payload`; they now carry correct
   allergies/meds/provider.
7. **No regression** in existing AVS tests; build-green + unit-green.

## IMPLEMENTATION SKETCH

In `compose-avs.ts`, change `function extractAllergies` / `extractMedications` /
`practitionerDisplayName` to `export function ...` (no body change).

In `FinalizePage.tsx`, the memo currently (~line 214):

```ts
const avsPayload: AvsPayload | null = useMemo(() => {
  if (!patient || !encounter) return null;
  ...
  return {
    ...,
    providerName: 'Provider',
    diagnoses: composeState.assessmentProblems.filter(...).map(...),
    allergies: [],
    medications: composeState.structuredPlanItems.filter(p => p.planType === 'medication' ...).map(...),
    planItems: composeState.structuredPlanItems.filter(p => p.planType !== 'medication' ...).map(...),
    ...
  };
}, [...]);
```

Replace the three offending fields:

```ts
import { extractAllergies, extractMedications, practitionerDisplayName } from '../../../lib/clinical/avs/compose-avs';

// inside the memo:
const profile = medplum.getProfile();
const providerName =
  profile?.resourceType === 'Practitioner' && profile.name?.[0]
    ? practitionerDisplayName(profile)
    : 'Your Care Team';

// real allergies from the already-loaded clinical bundle
const groundedAllergies = extractAllergies(avsClinical.allergies ?? []);

// real meds (prescribed + continued) unioned with structured plan-item meds, de-duped by label
const clinicalMeds = extractMedications(avsClinical.medicationRequests ?? []);
const planMeds = composeState.structuredPlanItems
  .filter(p => p.planType === 'medication' && p.details.trim())
  .map(p => ({ label: p.details }));
const seen = new Set<string>();
const medications = [...clinicalMeds, ...planMeds].filter(m => {
  const k = m.label.toLowerCase().trim();
  if (seen.has(k)) return false; seen.add(k); return true;
});

return {
  ...,
  providerName,
  diagnoses: /* unchanged */,
  allergies: groundedAllergies,
  medications,
  planItems: /* unchanged (structured non-med plan items) */,
  ...
};
```

Add `avsClinical`, `medplum` to the memo dependency array.

Note: keep `diagnoses` and `planItems` sourced from `composeState` (they reflect the live,
unsigned finalize edits). Only allergies/meds/provider are pulled from the loaded clinical data
+ profile. Do NOT swap the whole memo to async `composeAvs()` — that reads committed FHIR and
would miss in-progress finalize edits.

## OUT OF SCOPE

- Refactoring the two AVS code paths (LLM `draftAVS` vs grounded `composeAvs`) into one.
- The patient-friendly LLM prose quality (separate concern; validator already guards safety).
- Visual AVS / portal AVS pages (they already use `composeAvs` correctly).

## DEFINITION OF DONE

- `avsPayload` carries real allergies, meds, plan, and provider name.
- NKDA only when allergy list is truly empty (unit test).
- Patient-friendly rewrite passes the grounding validator.
- Commit message: `FIX-01: ground finalize AVS payload — real allergies/meds/provider (S6S60)`.

## §29 / §31

§29 standard.

§31 smoke:
1. Open Catherine Hargrove's encounter → Finalize → After-visit summary (Clinical).
2. Expect ALLERGIES to list Penicillin (critical) + Ibuprofen/NSAID — NOT "No known allergies".
3. Expect MEDICATIONS to include the prescribed + continued meds; PLAN populated.
4. Expect "Provider: Dr. Sarah Whitman" (the signed-in provider), not "Provider".
5. Toggle Patient-friendly → allergies still present; no validator warning.
