## Repo: clinical-mp
## Batch ID: s6s61-sched-1
## Briefs: 4 (SCHED-1A, SCHED-1B, SCHED-1C, SCHED-1D)
## Predecessor: 8ad8361 (TASKS-1)
## Fire mechanism: orchestrator queue --approve --skip-sit
## TONI_TIMEOUT_MIN: 30
## Severity: feature

## CONTEXT
Patient-first conversational scheduling, wave 1 of 2.

Today the front-desk agent's `draftSchedule` (src/lib/agentic-runtime/tools.ts) enqueues a `schedule` PracticeDraft (status 'pending-approval') via `enqueueDraft` -> a Task (status 'requested', intent 'proposal'). Provider approval (`approveDraft` schedule branch, src/lib/agentic-drafts/draft-queue.ts ~line 120) and the daemon Phase B both call `bookScheduleDraft` (src/lib/agentic-drafts/book-schedule.ts), which instant-creates a 'booked' Appointment at now+1day. Unrealistic.

NEW flow (patient-first): when triage flags a visit the agent (a) computes 2-3 open slots from the PANEL PROVIDER's OWN calendar (working hours minus that provider's existing appointments), (b) drops ONE placeholder hold = a 'pending' Appointment at the top slot, tagged so it can be moved/released, (c) messages the PATIENT the 2-3 options as STRUCTURED data on the Communication (a `urn:spectricom:proposed-slots` extension carrying JSON; the patient UI renders buttons in SCHED-2 and the LLM NEVER parses the reply), (d) opens the provider Task in an "awaiting patient selection" state. NOTHING books until the patient picks (SCHED-2) and the provider gives final approval.

SCHED-1 (this wave) = slot computation + placeholder hold + patient proposal message + awaiting-selection draft state + faded/tentative calendar rendering. The provider approval->book and the patient's tappable pick are SCHED-2 -- DO NOT build them here.

The daemon Phase B books only Tasks with status 'completed'; our awaiting Task stays status 'requested', so it will NOT be prematurely booked. Keep it that way.

## GOAL
Triage that decides "needs a visit" proposes real open times to the patient and holds one slot, instead of instant-booking. The provider sees a tentative hold on their calendar and a Task that reads "awaiting patient selection."

---

### BRIEF SCHED-1A -- open-slot computation lib

FILES:
- NEW src/lib/scheduling/propose-slots.ts
- EDIT src/lib/synth/schedule-generator.ts (add `export` to existing internal helpers ONLY -- do not change their logic)

IMPLEMENT:
1. In schedule-generator.ts add the `export` keyword to the existing functions `getAvailableSlotHours`, `slotToISO`, and `clinicLocalToUTC` (plus any tz helper they depend on). Logic UNCHANGED -- this is only to reuse the clinic working-hours window + tz conversion.
2. In propose-slots.ts:
   - `export const PROPOSED_SLOTS_EXTENSION_URL = 'urn:spectricom:proposed-slots';`
   - `export const AGENT_PLACEHOLDER_TAG_SYSTEM = 'urn:spectricom:agent-placeholder';`
   - `export interface OpenSlot { start: string; end: string; }` (ISO strings)
   - `export async function computeOpenSlots(medplum: MedplumClient, providerRef: Reference<Practitioner>, opts?: { count?: number; fromDate?: Date; daysAhead?: number }): Promise<OpenSlot[]>`
     - Defaults: count=3, fromDate=now, daysAhead=14, slot duration 30min.
     - Candidate slots: for each day from fromDate up to daysAhead, use `getAvailableSlotHours(date)` + `slotToISO(date, hour)` to produce candidate {start,end} in clinic tz. Skip any candidate whose start is already in the past relative to fromDate.
     - Busy set: query the provider's Appointments overlapping [fromDate, fromDate+daysAhead] whose status is NOT one of 'cancelled' | 'noshow' | 'entered-in-error' (treat booked/pending/arrived/proposed as busy). Use the SAME Appointment search param SchedulePage.tsx uses for the actor/practitioner filter (inspect it ~line 111); add date range params and `['_count','200']`.
     - A candidate collides if its [start,end) overlaps any busy appointment's [start,end). Return the first `count` non-colliding candidates, soonest first. If none, return [].

ACCEPTANCE:
- `npx tsc --noEmit && npm run build` green.
- computeOpenSlots returns soonest open 30-min slots in working hours, excluding times overlapping that provider's non-cancelled appointments (including 'pending' holds).

OUT OF SCOPE: any UI; booking; placeholder creation.

---

### BRIEF SCHED-1B -- extend draft + message types

FILES:
- EDIT src/lib/agentic-drafts/types.ts
- EDIT src/lib/messaging/compose-message.ts

IMPLEMENT:
1. types.ts -- add these OPTIONAL fields to `PracticeDraft`:
   - `proposedSlots?: { start: string; end: string }[];`
   - `placeholderAppointmentRef?: string;`   // e.g. 'Appointment/123'
   - `scheduleState?: 'awaiting-patient-selection' | 'patient-selected' | 'booked';`
   - `patientSelectedSlot?: { start: string; end: string };`   // populated in SCHED-2; declare now
   - `proposalThreadRef?: string;`   // the Communication carrying the proposed-slots extension
2. compose-message.ts -- add optional `extensions?: Extension[]` to the `ComposeThreadOptions` interface. When present, attach them to the created ROOT Communication before createResource: `comm.extension = [...(comm.extension ?? []), ...opts.extensions];`. No behavior change when absent. Import `Extension` from '@medplum/fhirtypes'.

ACCEPTANCE: build green; ComposeThreadOptions accepts `extensions` and they persist on the created Communication; PracticeDraft carries the new optional fields.

OUT OF SCOPE: callers (SCHED-1C wires them).

---

### BRIEF SCHED-1C -- patient-first draftSchedule

FILES:
- EDIT src/lib/agentic-runtime/tools.ts (the `draftSchedule` function)

IMPLEMENT:
Rework `draftSchedule` to run the patient-first flow. Panel provider ref = `p.providerRef ?? p.approverRef`.
1. `const slots = await computeOpenSlots(p.medplum, providerRef, { count: 3 });`
   - If `slots.length === 0`: GRACEFUL FALLBACK -- keep today's behavior: build the draft without proposedSlots/placeholder/scheduleState, enqueueDraft, return summary 'No open slots found; queued for manual scheduling.'
2. Create ONE placeholder Appointment:
   status 'pending', description `Hold: ${p.visitType}`, start/end = slots[0], appointmentType {text: p.visitType} when set,
   participant [{ actor: p.patientRef, status: 'needs-action' }, { actor: providerRef, status: 'tentative' }],
   meta.tag [{ system: AGENT_PLACEHOLDER_TAG_SYSTEM, code: 'hold' }]. Capture placeholder.id.
3. Send patient proposal via composeNewThread: sender = providerRef (display p.providerName), recipient = p.patientRef, patientRef = p.patientRef, subject = `Let's get you scheduled - ${p.visitType}`, body = a readable numbered list of the proposed times formatted in clinic-local (e.g. "1) Tue Jun 17, 9:00 AM  2) Wed Jun 18, 1:30 PM ...") followed by "Tap a time that works for you." ; extensions = [{ url: PROPOSED_SLOTS_EXTENSION_URL, valueString: JSON.stringify(slots) }]. Capture the returned Communication id.
4. Build the PracticeDraft as today PLUS: `proposedSlots: slots`, `placeholderAppointmentRef: 'Appointment/'+placeholder.id`, `scheduleState: 'awaiting-patient-selection'`, `proposalThreadRef: 'Communication/'+<id>`, and set body to note "Proposed 3 times to patient; awaiting selection." Keep `sourceRef` = p.threadRef when present.
5. `enqueueDraft(...)` (Task stays status 'requested').
6. Return { disposition, summary: 'Proposed 3 times to patient; placeholder held; awaiting patient selection.', record, sent: true, taskId: task.id }.

Imports: `computeOpenSlots, AGENT_PLACEHOLDER_TAG_SYSTEM, PROPOSED_SLOTS_EXTENSION_URL` from '../scheduling/propose-slots'; `composeNewThread` from '../messaging/compose-message'; `Appointment` from '@medplum/fhirtypes'.

ACCEPTANCE:
- build green.
- A draftSchedule call WITH open slots creates exactly ONE 'pending' Appointment tagged agent-placeholder at the soonest slot, sends a patient Communication carrying the proposed-slots extension, and enqueues a Task (status 'requested') whose serialized draft has scheduleState='awaiting-patient-selection' + proposedSlots + placeholderAppointmentRef.
- NO 'booked' Appointment is created by this path.

OUT OF SCOPE: patient pick; provider approval/booking; calendar visuals.

---

### BRIEF SCHED-1D -- guard approval + render the hold

FILES:
- EDIT src/lib/agentic-drafts/draft-queue.ts (approveDraft schedule branch ~line 120)
- EDIT src/components/inbox/InboxItemDetail.tsx (TaskDetail, schedule-draft branch)
- EDIT the appointment renderer in the schedule view (find under src/pages/schedule/ -- SchedulePage.tsx and/or an appointment block/cell component)

IMPLEMENT:
1. approveDraft schedule branch: BEFORE calling bookScheduleDraft, guard -- if `draft.scheduleState && draft.scheduleState !== 'patient-selected'`, throw `new Error('Awaiting patient time selection - cannot approve yet.')`. Drafts with NO scheduleState (legacy) keep instant-book. Leave bookScheduleDraft itself unchanged (its rewrite is SCHED-2).
2. InboxItemDetail schedule-draft card (uses readDraftFromTask): when `draft.kind==='schedule'` AND `draft.scheduleState==='awaiting-patient-selection'`, render a READ-ONLY "Scheduling in progress" card:
   - patient name; "Proposed times:" list from draft.proposedSlots (clinic-local formatted); "Hold placed: <top slot>"; status line "Awaiting patient selection."
   - Do NOT render "Approve & schedule." Keep a secondary "Decline / cancel hold" action: call the existing rejectDraft AND, if draft.placeholderAppointmentRef is set, set that Appointment's status to 'cancelled'.
   - Legacy schedule drafts (no scheduleState) keep the EXISTING Approve & schedule / Decline card unchanged.
3. Calendar rendering: appointments whose `status==='pending'` OR whose meta.tag includes system `urn:spectricom:agent-placeholder` render TENTATIVE -- reduced opacity (~0.55), dashed (not solid) border, and a small "Hold" badge -- visually distinct from 'booked'. Branch on status/tag in the existing appointment block renderer. Do NOT change booked rendering.

ACCEPTANCE:
- build green.
- An awaiting-selection schedule draft opened in the Inbox shows the read-only "Scheduling in progress" card (proposed times + hold), NOT an instant Approve button; Decline cancels the placeholder Appointment.
- approveDraft throws if asked to approve an awaiting (not patient-selected) schedule draft.
- A 'pending'/placeholder appointment renders faded with a "Hold" badge on the calendar; booked appointments unchanged.

OUT OF SCOPE: patient pick UI; moving the hold; final book + confirmation (all SCHED-2).
