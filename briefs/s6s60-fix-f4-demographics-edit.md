# Toni Batch S6S60 — FIX-F4: demographics edit page graceful fallback (us-core profile not installed)

## Repo: clinical-mp
## Batch ID: s6s60-fix-f4-demographics-edit
## Briefs: 1
## Estimated runtime: 20-30m
## Predecessor: clinical-mp main @ 42c5c6e
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 35
## Severity: P1 (raw server error on a clinician route)

## CONTEXT

Synth UAT (J-G, Marcus Chen) found `/Patient/:id/edit` renders a raw error:
"Could not find the US Core Patient Profile ... us-core-patient not found." The inline header
"Quick edit" works (PUT Patient 200), but the dedicated edit page is dead.

Root cause (confirmed in code):
- `src/pages/patient/EditTab.tsx` (~L63) renders `<ResourceFormWithRequiredProfile
  profileUrl={RESOURCE_PROFILE_URLS.Patient} .../>` — i.e. it REQUIRES the `us-core-patient`
  StructureDefinition.
- `src/components/ResourceFormWithRequiredProfile.tsx`: when `profileUrl` is set but the profile
  schema cannot be loaded (`profileUrl && !profile`), it returns a red "Not found" `Alert` INSTEAD
  of a form. The us-core-patient StructureDefinition is not installed on this Medplum server, so
  the profile never resolves and the whole edit form is replaced by the error.

The app does not actually need us-core to edit a Patient (Quick-edit is a plain PUT). The page
should degrade to a base Patient form rather than dead-end on a raw error.

## GOAL

Make the Patient demographics edit page render a usable (base) `ResourceForm` when the required
profile is not installed, instead of the blocking "Not found" Alert — without weakening the strict
behavior for other callers of `ResourceFormWithRequiredProfile` (e.g. `ResourceEditPage`).

## FILES
- `src/components/ResourceFormWithRequiredProfile.tsx`
- `src/pages/patient/EditTab.tsx`
- `src/components/__tests__/ResourceFormWithRequiredProfile.test.tsx` (add if absent)
- `src/pages/patient/EditTab.test.tsx`

## IMPLEMENT
1. In `ResourceFormWithRequiredProfile`, add an optional prop:
   `readonly fallbackToBaseFormWhenProfileMissing?: boolean;` (default `false` — preserves current
   strict behavior for all existing callers).
2. In the `profileUrl && !profile` branch: if `fallbackToBaseFormWhenProfileMissing` is true, render
   `<ResourceForm onSubmit={handleSubmit} {...resourceFormProps} />` WITHOUT the profile (so it uses
   the base Patient schema), preceded by a small non-blocking inline notice (Mantine `Alert`
   color="yellow", e.g. "Editing with the base form — practice profile not installed."). When the
   prop is false, keep the existing red "Not found" Alert exactly as-is.
   - Note: when falling back, do NOT call `addProfileToResource` in `handleSubmit` (guard on whether
     a profile actually resolved), so the saved Patient is not stamped with a profile that is not
     present.
3. In `EditTab.tsx`, pass `fallbackToBaseFormWhenProfileMissing` so the Patient demographics edit
   degrades gracefully.

## ACCEPTANCE CRITERIA
1. With the us-core-patient profile NOT loaded, `/Patient/:id/edit` renders an editable base Patient
   form (name, phone, etc.) with a yellow non-blocking notice — NOT the red "Not found" Alert.
2. Editing a field and submitting saves via `updateResource`/`PUT Patient` (200); the saved Patient
   is not stamped with the absent profile.
3. `ResourceEditPage` and any other caller that does NOT set the new prop keep the existing strict
   "Not found" behavior (regression test).
4. Quick-edit header editor is untouched.

## OUT OF SCOPE
- Installing the US Core StructureDefinition pack into Medplum (separate infra task).
- Immunizations UI (separate gap).

## DEFINITION OF DONE
- `/Patient/:id/edit` is usable without us-core installed; strict callers unchanged.
- Commit message: `FIX-F4: demographics edit graceful fallback when required profile missing (S6S60)`.

## §29 / §31
§29 standard.
§31 smoke:
1. As Dr. Whitman open a panel patient -> `/Patient/<id>/edit`.
2. Expect an editable Patient form (not the "Not found" red alert), with a small yellow notice.
3. Edit phone -> Save -> PUT Patient 200; reload reflects the change.
4. Open `/<some other resource>/<id>/edit` (ResourceEditPage path) with a missing profile -> still shows strict "Not found".
