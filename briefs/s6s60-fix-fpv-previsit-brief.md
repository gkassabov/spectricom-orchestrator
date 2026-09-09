# Toni Batch S6S60 — FIX-FPV: wire pre-visit brief to patient fixtures + add Santos/Hargrove briefs

## Repo: clinical-mp
## Batch ID: s6s60-fix-fpv-previsit-brief
## Briefs: 2
## Estimated runtime: 25-35m
## Predecessor: clinical-mp main @ 74db71b
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 40
## Severity: P1 (on Dr. K demo path — script-01 #1; brief never renders for real encounters)

## CONTEXT

Synth UAT (twice) found the Pre-visit brief shows **"No pre-visit brief generated for this
encounter"** with an empty Suggested agenda, for every real encounter. (The "Care gaps & missing
data" panel is a separate, working surface — not the brief.)

Root cause (confirmed in code):
- `src/hooks/useEncounterPrevisitBrief.ts` calls ONLY `getPrevisitBrief(encounterId)`.
- `src/lib/clinical/previsit-brief-fixtures.ts`: `getPrevisitBrief(encounterId)` looks up
  `PREVISIT_FIXTURES[encounterId]`, which is keyed by a single hardcoded `DAVID_WILLIAMS_ENCOUNTER_ID`.
  Real seeded encounters have random UUIDs, so this NEVER matches -> always null -> "No brief".
- A patient-keyed path already exists but is unused: `getPrevisitBriefByPatientSynthId(synthId)` +
  `PATIENT_SYNTH_FIXTURES`, which only contains `'VANCE-PT-001' -> MARCUS_CHEN_BRIEF` (not a real
  panel patient / wrong identifier scheme).
- `src/pages/patient/encounter/PrevisitPage.tsx` already has the `patient` object in scope.

This is a fixture-wiring defect: brief is fixture-fed by design (acceptable for the demo), but keyed
so it can never resolve for the demo patients.

## GOAL

Resolve the pre-visit brief by the patient's synth identifier (with the encounter-id path as
fallback), and add brief fixtures for the actual demo patients so the brief + agenda render.

---

## BRIEF FPV-1 — resolve the brief by patient synth identifier

### FILES
- `src/hooks/useEncounterPrevisitBrief.ts`
- `src/pages/patient/encounter/PrevisitPage.tsx`
- `src/hooks/__tests__/useEncounterPrevisitBrief.test.ts(x)` (add/extend)

### IMPLEMENT
- Extend the hook to accept the patient's synth identifier (and keep encounterId). Signature e.g.
  `useEncounterPrevisitBrief(encounterId: string, patientSynthId?: string)`.
- Resolution order: if `patientSynthId` and `getPrevisitBriefByPatientSynthId(patientSynthId)` returns
  a brief, use it; else fall back to `getPrevisitBrief(encounterId)`; else null.
- In `PrevisitPage.tsx`, extract the patient's SYNTH-PT identifier from `patient.identifier` (the
  synth identifier system already used across the seeders — match the same system constant) and pass
  it to the hook.

### ACCEPTANCE
1. A patient whose synth id has a fixture renders that brief regardless of the (random) encounter id.
2. A patient with no fixture still degrades gracefully to "No pre-visit brief generated" (no crash).
3. The existing encounter-id fixture path still works (back-compat).

---

## BRIEF FPV-2 — add brief fixtures for Maria Santos (SYNTH-PT-001) and Catherine Hargrove (SYNTH-PT-016)

### FILES
- `src/lib/clinical/previsit-brief-fixtures.ts`

### IMPLEMENT
Add two `PrevisitBrief` entries to `PATIENT_SYNTH_FIXTURES` keyed by the real synth identifiers
`'SYNTH-PT-001'` (Maria Santos) and `'SYNTH-PT-016'` (Catherine Hargrove). Author clinically-plausible
fixtures matching the existing `PrevisitBrief` shape (narrative, agenda[], miniMe, openFollowUps,
messages, yorsieForm):
- **SYNTH-PT-001 Maria Santos** — anchor on her real context: home BP running high, on an ACE-I
  (lisinopril) nearly out / refill needed, CKD/renal monitoring. Agenda items (defaultChecked true):
  "Review home BP trend", "Lisinopril refill + adherence", "Renal function / CKD monitoring",
  "Confirm BP recheck plan". messages.preview should include her "home BP high / out of lisinopril"
  message. Keep it concise and non-fabricated in tone (advisory).
- **SYNTH-PT-016 Catherine Hargrove** — a plausible concierge follow-up brief (e.g. lipid/lifestyle +
  the abnormal TSH she has on file); 3-4 agenda items.
You may keep/retire the `VANCE-PT-001 -> MARCUS_CHEN_BRIEF` entry; it is not a real panel patient.

### ACCEPTANCE
1. `getPrevisitBriefByPatientSynthId('SYNTH-PT-001')` and `('SYNTH-PT-016')` both return a brief with a
   non-empty narrative and >=3 agenda items.
2. A unit test asserts both resolve and have agenda items.

---

## OUT OF SCOPE
- Live generation of the brief from FHIR (future upgrade; it remains fixture-fed by design).

## DEFINITION OF DONE
- Pre-visit brief + Suggested agenda render for Santos and Hargrove encounters.
- Commit message: `FIX-FPV: resolve pre-visit brief by patient synth id + Santos/Hargrove fixtures (S6S60)`.

## §29 / §31
§29 standard.
§31 smoke:
1. Open Catherine Hargrove's scheduled encounter -> Pre-visit -> narrative brief renders (not "No
   pre-visit brief generated") and the Suggested agenda lists checkable items.
2. Repeat for Maria Santos -> BP/lisinopril/renal agenda renders.
