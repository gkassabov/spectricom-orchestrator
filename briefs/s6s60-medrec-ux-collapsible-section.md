# Toni Batch S6S60 — MEDREC-UX: replace blocking med-rec wizard step with a state-driven collapsible section

## Repo: clinical-mp
## Batch ID: s6s60-medrec-ux-collapsible-section
## Briefs: 1
## Estimated runtime: 30-45m
## Predecessor: clinical-mp main @ d6be959
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 50
## Severity: P2 (UX pattern inconsistency + provider confusion; observed by Dr. K in testing)

## CONTEXT

Provider testing (and Dr. K) found Med Reconciliation confusing for two reasons:
1. **Pattern inconsistency.** The encounter note is an all-in-one page (S/O/A/P visible, edit-in-place
   — `ProblemCentricLayout` / `SoapFlatLayout`), but Med Rec is a **blocking wizard sub-step**
   (`MedReconciliationStep`) the provider must clear (route `…/Encounter/{id}/med-reconciliation`,
   "Complete reconciliation") before the note appears. Two interaction paradigms in one encounter.
2. **Workflow mismatch.** Reconciliation is typically done by the MA pre-visit / before the provider
   arrives — so the provider is forced through work already done.

Reconciliation must still be PART of the encounter (compliance/signed note), and the provider must be
able to review/adjust it. The fix is to make it a **state-driven section inside the all-in-one page**,
not a gate.

Confirmed in code:
- Reconcile UI is already a standalone component: `src/components/med-reconciliation/ReconciliationGrid.tsx`
  (used by `MedReconciliationStep`). Reusable as-is.
- State is an Encounter extension (no schema work needed):
  - `MED_REC_COMPLETED_URL = 'urn:spectricom:med-rec-completed-at'` (valueString = ISO timestamp)
  - skip: `MED_REC_SKIP_ENCOUNTER_URL`, `MED_REC_SKIP_REASON_URL`; `STALE_THRESHOLD_DAYS = 60`
    (`src/lib/clinical/med-reconciliation/types.ts`)
  - readers exist: `getLastReconciliationDate(encounter)`, `wasSkippedThisEncounter(encounter)`
    (`src/lib/clinical/med-reconciliation/persistence.ts`)
  - writers exist + write provenance with the agent: `completeReconciliation`, `skipReconciliation`.
- All-in-one note layouts: `src/components/encounter-compose/layouts/ProblemCentricLayout.tsx`,
  `SoapFlatLayout.tsx`. Right rail already shows ACTIVE MEDS.

## GOAL

De-gate Med Rec from the encounter flow; render reconciliation as a collapsible "Medications" section
at the TOP of the all-in-one note, driven by existing state; add a rail reconciled/not badge.
Persistence and the reconcile grid logic are REUSED unchanged. No role-configurability.

---

## BRIEF MR-1 — collapsible in-page reconciliation section + de-gate

### FILES
- NEW: `src/components/encounter-compose/MedReconciliationSection.tsx` (wraps `ReconciliationGrid` + collapse logic)
- `src/components/encounter-compose/layouts/ProblemCentricLayout.tsx` (mount the section at top)
- `src/components/encounter-compose/layouts/SoapFlatLayout.tsx` (mount the section at top)
- the encounter stage routing/flow that sequences `med-reconciliation` before the note (locate it; the
  `…/Encounter/{id}/med-reconciliation` route currently gates entry — de-gate so the Encounter stage
  lands directly on the note)
- the right-rail ACTIVE MEDS component (add reconciled/not badge — locate via "ACTIVE MEDS")
- `src/pages/patient/encounter/MedReconciliationStep.tsx` (remove from the flow; keep the file or
  redirect its route — see acceptance #6)
- tests: add `MedReconciliationSection` test; update any encounter-flow/routing tests
- DO NOT modify `persistence.ts` / `actions.ts` / `ReconciliationGrid` logic (reuse as-is)

### IMPLEMENT
- `MedReconciliationSection({ encounter, ... })`:
  - reconciled & fresh (`getLastReconciliationDate` present and ≤ `STALE_THRESHOLD_DAYS` old) →
    render **collapsed** summary: "Medications — reconciled ✓ {relative date}". Expandable.
  - skipped this encounter (`wasSkippedThisEncounter`) → **collapsed** "Medications — reconciliation skipped ({reason})". Expandable.
  - not reconciled, or stale (> `STALE_THRESHOLD_DAYS`) → **expanded** with `ReconciliationGrid`
    + the existing Complete / Skip actions (reuse `completeReconciliation` / `skipReconciliation`).
  - either state is user-toggleable (expand to review even when collapsed).
  - completing reconciliation persists the extension (existing writer) and collapses the section.
- Mount `MedReconciliationSection` at the TOP of both note layouts, above the SOAP sections.
- Remove the blocking step: the Encounter stage must land on the note layout directly. Do NOT delete
  user data or the persistence path — only remove the wizard gate.
- Rail ACTIVE MEDS: add a small badge "Reconciled ✓ {date}" / "Not reconciled" reading the same state.

### ACCEPTANCE
1. Opening / starting an encounter lands directly on the all-in-one note — NO blocking med-rec step.
2. Reconciled (fresh) encounter → Medications section is collapsed with a date summary; expandable to the grid.
3. Not reconciled OR stale (>60d) → section expanded with the reconcile grid; "Complete reconciliation"
   sets `MED_REC_COMPLETED_URL` and collapses the section (verify the extension is written).
4. Skipped this encounter → collapsed with the skip reason; expandable.
5. Right-rail ACTIVE MEDS shows a reconciled/not badge reflecting the same state.
6. The legacy `…/Encounter/{id}/med-reconciliation` route no longer blocks: it redirects to / renders
   the note (no dead link, no crash for bookmarks).
7. `npm run build` green; unit tests green.

### OUT OF SCOPE (do NOT implement)
- Configurability of WHO reconciles (MA vs provider); any role/workflow enforcement.
- A provider attestation gate (optional future follow-up — collapsed "reconciled ✓ / expand to review"
  is sufficient acknowledgment for now).
- Changes to `ReconciliationGrid` behavior or the persistence/actions layer.
