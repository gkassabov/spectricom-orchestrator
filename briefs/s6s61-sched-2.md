## Repo: clinical-mp
## Batch ID: s6s61-sched-2
## Briefs: 4 (SCHED-2A list-hygiene, SCHED-2B portal-pick, SCHED-2C daemon-selection, SCHED-2D approve-book)
## Predecessor: 52a3992 (SCHED-1-FIX)
## Fire mechanism: orchestrator queue --approve --skip-sit
## TONI_TIMEOUT_MIN: 35
## Severity: feature

## CONTEXT
SCHED-2 completes patient-first scheduling. SCHED-1 (52a3992) already: computes open slots from the provider's calendar, drops ONE 'pending' placeholder Appointment (tagged AGENT_PLACEHOLDER_TAG_SYSTEM), and posts the proposed times as a REPLY into the patient's thread carrying extension PROPOSED_SLOTS_EXTENSION_URL ('urn:spectricom:proposed-slots' = JSON [{start,end}]). The awaiting draft is a Task (status 'requested', intent 'proposal') whose serialized PracticeDraft lives in extension 'urn:spectricom:ai-draft' and carries: scheduleState, proposedSlots, placeholderAppointmentRef, proposalThreadRef ('Communication/'+proposalMessageId), patientSelectedSlot, sourceRef, providerRef/providerName, patientName/patientId. `approveDraft` already GUARDS: a schedule draft with scheduleState !== 'patient-selected' throws. `replyToThread` already accepts an optional `extensions` arg.

Now wire the rest: patient TAPS a proposed time -> selection recorded STRUCTURALLY (no LLM parsing) -> daemon flips the draft to 'patient-selected' + moves the hold -> provider approves -> books the chosen slot + posts a confirmation. PLUS one real bug: anchor Communications (meta.tag system THREAD_ANCHOR_TAG, no topic) and entered-in-error Communications still render as phantom "No subject" rows in the inbox + portal LISTS (the earlier fix only de-duped the thread DETAIL).

A clinic-local slot formatter `formatSlotLabel` already exists in src/lib/scheduling/propose-slots.ts -- reuse it everywhere a slot is shown.

## GOAL
End-to-end patient-first scheduling that BOOKS only after the patient picks AND the provider approves; and message lists that show each thread once.

---

### BRIEF SCHED-2A -- list hygiene (the live bug)

FILES:
- EDIT src/lib/inbox/use-inbox-items.ts
- EDIT src/pages/portal/PortalMessagesPage.tsx

IMPLEMENT:
1. use-inbox-items.ts: the Communications fetched (~line 89 via the `messageParams` searchResources) must be filtered to EXCLUDE any Communication whose meta.tag includes system === THREAD_ANCHOR_TAG OR whose status === 'entered-in-error', BEFORE classification/listing. Import THREAD_ANCHOR_TAG from '../messaging/compose-message'.
2. PortalMessagesPage.tsx: wherever it assembles the list of threads, apply the SAME exclusion (THREAD_ANCHOR_TAG anchors + status 'entered-in-error').

ACCEPTANCE:
- `npx tsc --noEmit && npm run build` green.
- Provider inbox + patient portal lists render each thread exactly ONCE (no "No subject" anchor rows); entered-in-error threads do not appear.

OUT OF SCOPE: thread detail (already de-duped).

---

### BRIEF SCHED-2B -- portal tappable slots + post structured selection

FILES:
- EDIT src/lib/scheduling/propose-slots.ts
- EDIT src/lib/messaging/compose-message.ts
- EDIT src/pages/portal/PortalMessageThreadPage.tsx

IMPLEMENT:
1. propose-slots.ts -- add exports:
   - `export const SELECTED_SLOT_EXTENSION_URL = 'urn:spectricom:selected-slot';`
   - `export const SLOT_SELECTION_TAG_SYSTEM = 'urn:spectricom:slot-selection';`
   - `export function readProposedSlots(comm: Communication): OpenSlot[]` -> JSON-parse the slots from the comm's PROPOSED_SLOTS_EXTENSION_URL extension; return [] if absent/invalid.
2. compose-message.ts -- add optional `tags?: Coding[]` to `ReplyOptions`. In replyToThread, if opts.tags?.length, set `reply.meta = { ...(reply.meta ?? {}), tag: [ ...((reply.meta?.tag) ?? []), ...opts.tags ] };` before createResource. Import `Coding` from '@medplum/fhirtypes'.
3. PortalMessageThreadPage.tsx:
   - Determine if a selection already exists in this thread: true if ANY rendered message carries the SELECTED_SLOT_EXTENSION_URL extension.
   - For each rendered thread message where `readProposedSlots(msg).length > 0`: if NO selection exists yet, render the slots as tappable buttons (label via formatSlotLabel) directly beneath that message; if a selection DOES exist, render a subtle line "You selected <label of the selected slot>" instead of buttons.
   - On tapping a slot button, call:
     `await replyToThread(medplum, threadId, { sender: <same member/patient sender handleReply uses>, body: \`I'd like ${formatSlotLabel(slot)}.\`, extensions: [{ url: SELECTED_SLOT_EXTENSION_URL, valueString: JSON.stringify({ slot, proposalRef: 'Communication/' + msg.id }) }], tags: [{ system: SLOT_SELECTION_TAG_SYSTEM, code: 'pending' }] });`
     then refetch/refresh the thread so the buttons collapse to the "You selected" line.

ACCEPTANCE:
- build green.
- The patient sees tappable time buttons under the proposal; tapping posts a reply Communication carrying the selected-slot extension AND a meta.tag system 'urn:spectricom:slot-selection' code 'pending', and the buttons are replaced by a "You selected <label>" line.

OUT OF SCOPE: moving the hold / booking (daemon + provider do those).

---

### BRIEF SCHED-2C -- daemon Phase C: process patient selections

FILES:
- EDIT src/daemon/agentic-daemon.ts

IMPLEMENT:
- Add `async function processPatientSelections(ctx: DaemonContext): Promise<void>` and call it inside runCycle as Phase C, AFTER Phase B (processApprovedSchedules). Wrap in try/catch + log like the other phases.
- Query Communications with `_tag=urn:spectricom:slot-selection|pending` (_count 50). For each selection comm:
  1. Parse the SELECTED_SLOT_EXTENSION_URL extension -> { slot: {start,end}, proposalRef }. If missing, retag done and continue.
  2. Find the awaiting draft Task: searchResources('Task', intent='proposal', _count 200); pick the one whose serialized draft (extension url 'urn:spectricom:ai-draft', JSON) has proposalThreadRef === proposalRef. If none found OR its scheduleState !== 'awaiting-patient-selection', retag the selection done and continue (idempotent no-op).
  3. Update that draft object: scheduleState='patient-selected', patientSelectedSlot=slot. Re-stringify into the Task's 'urn:spectricom:ai-draft' extension. Update Task.description to `${AI_DRAFT_LABEL}: Schedule — patient chose ${formatSlotLabel(slot)} — ${draft.patientName}`. Keep Task.status 'requested'. Persist (updateResource).
  4. If draft.placeholderAppointmentRef: read that Appointment, set start=slot.start end=slot.end (status stays 'pending'), update.
  5. Retag the selection comm: remove the slot-selection|pending tag, add slot-selection|done.
  6. log(`Selection: patient chose ${formatSlotLabel(slot)} for task <id>`).
- Import formatSlotLabel + SELECTED_SLOT_EXTENSION_URL + SLOT_SELECTION_TAG_SYSTEM from '../lib/scheduling/propose-slots'; AI_DRAFT_LABEL + the ai-draft extension url from the drafts types module.

ACCEPTANCE:
- build green.
- After a patient taps, ONE daemon cycle: flips the linked draft to scheduleState 'patient-selected' + patientSelectedSlot, moves the placeholder Appointment to the chosen slot (status still 'pending'), updates the Task description, and retags the selection 'done' so it is never reprocessed.

OUT OF SCOPE: booking (provider approval does that).

---

### BRIEF SCHED-2D -- provider approve -> book the patient-selected slot + confirm

FILES:
- EDIT src/lib/agentic-drafts/book-schedule.ts
- EDIT src/components/inbox/InboxItemDetail.tsx

IMPLEMENT:
1. book-schedule.ts `bookScheduleDraft`: at the top, if `draft.placeholderAppointmentRef && draft.patientSelectedSlot`:
   - read that Appointment, set status 'booked', start = draft.patientSelectedSlot.start, end = draft.patientSelectedSlot.end, set BOTH participants' status 'accepted'; updateResource; use its id as appointmentId.
   - create the Encounter as the existing code does (status 'planned', subject = patient, appointment -> this appointment, participant = bookingProvider, reasonCode from scheduleReason) — only if one is not already linked.
   - DO skip the legacy now+1day create path in this branch.
   Else (no placeholder/selection): keep the existing legacy behavior unchanged.
   - After booking, post a confirmation reply to the patient in-thread: rootId = (draft.sourceRef ?? draft.proposalThreadRef ?? '').replace('Communication/',''); if rootId, `await replyToThread(medplum, rootId, { sender: bookingProvider, body: \`You're confirmed for ${formatSlotLabel(draft.patientSelectedSlot)}. See you then.\` });`
   - Imports: replyToThread from '../messaging/compose-message'; formatSlotLabel from '../scheduling/propose-slots'.
2. InboxItemDetail.tsx schedule-draft card -- extend the SCHED-1 card:
   - when draft.scheduleState === 'patient-selected': render a header "Patient selected: <formatSlotLabel(patientSelectedSlot)>" and a PRIMARY button "Approve & book" whose onClick calls the existing approve path (approveDraft) — it now passes the guard — and on success reflects booked; KEEP a secondary "Decline / cancel hold" (rejectDraft + cancel the placeholder Appointment if placeholderAppointmentRef set).
   - when draft.scheduleState === 'awaiting-patient-selection': keep the SCHED-1 read-only "Scheduling in progress" card UNCHANGED.
   - legacy schedule drafts (no scheduleState): UNCHANGED.

ACCEPTANCE:
- build green.
- A 'patient-selected' draft shows "Approve & book"; approving updates the placeholder Appointment to status 'booked' at the patient-selected slot (no new now+1day appointment), posts an in-thread confirmation to the patient, and completes the Task.
- That appointment then renders as a normal booked appointment on the calendar (no longer faded/Hold).

OUT OF SCOPE: none beyond this; SCHED-2 is the final scheduling wave.
