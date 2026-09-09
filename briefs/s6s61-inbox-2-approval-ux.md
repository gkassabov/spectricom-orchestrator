# Toni Batch S6S61 — INBOX-2: AI Ops approval UX (schedule draft -> one-click approve & book)

## Repo: clinical-mp
## Batch ID: s6s61-inbox-2-approval-ux
## Briefs: 2
## Estimated runtime: 25-35m
## Predecessor: clinical-mp main @ <INBOX-1 head>
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 35
## Severity: P1 (the AI Ops approval surface is cryptic: AI schedule-drafts render as a generic Task with a bare "Mark Done" — no patient, no visit details, no approve/decline; approving has a multi-second daemon lag)

## CONTEXT (confirmed in code)

- AI drafts are FHIR Tasks created by `enqueueDraft` (`src/lib/agentic-drafts/draft-queue.ts`): `status: 'requested'`,
  `intent: 'proposal'`, description `"AI draft — review: {title} — {patient}"`, with the full `PracticeDraft` JSON in
  an extension (`AI_DRAFT_EXTENSION_URL`). `readDraftFromTask(task)` returns the `PracticeDraft`.
- `PracticeDraft` (`src/lib/agentic-drafts/types.ts`) carries structured fields: `kind`
  ('schedule'|'message-reply'|'referral'|'prior-auth'), `patientName`, `patientId`, `requestedVisitType`,
  `scheduleReason`, `suggestedTiming`, `providerRef` (booking provider "Practitioner/{id}"), `providerName`, `body`.
- `approveDraft(medplum, taskId, editedBody?)` is the canonical approve path: message-reply -> sends a Communication;
  referral/prior-auth -> finalizes a DocumentReference; schedule -> CURRENTLY just sets Task.status='completed' and
  relies on the daemon's pre-encounter pass to book (a multi-second lag). `rejectDraft(medplum, taskId, reason?)`
  sets status='cancelled'. Both are browser-safe.
- The daemon (`src/daemon/agentic-daemon.ts` `processApprovedSchedules`) books a completed schedule draft by creating
  an Appointment (status 'booked', start +1 day, 30 min) + Encounter, then tagging the Task with
  `AGENTIC_BOOKED_TAG_SYSTEM` ('urn:spectricom:agentic-booked'); it skips Tasks already carrying that tag.
- The inbox renders Task detail via `src/components/inbox/InboxItemDetail.tsx` `TaskDetail`, which today shows only
  Description/Owner/Due/Status + a single "Mark Done" button (generic; no draft awareness).

## GOAL

Provider opens an AI schedule-draft in the inbox and sees a clear card (patient, suggested visit, reason, timing,
booking provider) with **Approve & schedule** (books the visit immediately) and **Decline**. Message/referral/
prior-auth drafts get an editable body + Approve & send / Decline. Non-draft Tasks keep a sensible default.

---

## BRIEF INBOX2-1 — shared booking helper; instant schedule approve (no double-book)

### FILES
- NEW `src/lib/agentic-drafts/book-schedule.ts`
- `src/lib/agentic-drafts/types.ts` (export the booked-tag constant)
- `src/lib/agentic-drafts/draft-queue.ts`
- `src/daemon/agentic-daemon.ts`
- tests under `src/lib/agentic-drafts/__tests__/`

### IMPLEMENT
- Move the booked-tag system constant into `types.ts`:
  `export const AGENTIC_BOOKED_TAG_SYSTEM = 'urn:spectricom:agentic-booked';` and import it in the daemon
  (replace the daemon's local definition with this import).
- Create `book-schedule.ts` exporting
  `export async function bookScheduleDraft(medplum: MedplumClient, task: Task, draft: PracticeDraft): Promise<{ appointmentId?: string; encounterId?: string }>`.
  MOVE the existing Appointment + Encounter creation logic from the daemon's `processApprovedSchedules` into this
  helper VERBATIM (same Appointment shape: status 'booked', start = now+1 day, end = +30 min, appointmentType from
  `draft.requestedVisitType`, participant [patient, provider]; same Encounter shape; then add the
  `AGENTIC_BOOKED_TAG_SYSTEM` tag to the Task). Resolve the booking provider in this order: `draft.providerRef`
  (preferred) -> else `getDefaultRecipient(patient)` (from `src/lib/escalate/context-injection.ts`) -> if none,
  throw `Error('No booking provider could be resolved for this schedule draft')`. Return the created ids.
- Refactor the daemon's `processApprovedSchedules` to call `bookScheduleDraft(ctx.medplum, task, draft)` instead of
  its inline creation; KEEP the existing `alreadyBooked` guard (skip Tasks already carrying the booked tag) so a
  UI-booked draft is not booked again.
- In `draft-queue.ts` `approveDraft`, in the `draft.kind === 'schedule'` branch: call
  `const booked = await bookScheduleDraft(medplum, task, draft);` BEFORE the `status: 'completed'` update, and add
  `appointmentId?: string` to `ApproveDraftResult`, returning `booked.appointmentId`.

### ACCEPTANCE
1. `approveDraft` on a schedule draft creates an Appointment + Encounter immediately, tags the Task booked, sets
   status 'completed', and returns an `appointmentId`.
2. The daemon's `processApprovedSchedules` produces identical bookings via the shared helper and SKIPS any Task
   already carrying the booked tag (a unit test asserts no second Appointment is created for an already-booked Task).
3. `bookScheduleDraft` throws when no provider can be resolved (test asserts).
4. Build green; tests green.

### OUT OF SCOPE
- Changing Appointment/Encounter field shapes from what the daemon already produced.
- The approval UI (next brief).

---

## BRIEF INBOX2-2 — approval card UI + item-page chrome

### FILES
- `src/components/inbox/InboxItemDetail.tsx`
- `src/pages/inbox/InboxItemPage.tsx`
- tests under `src/components/inbox/__tests__/` and `src/pages/inbox/__tests__/`

### IMPLEMENT
Rework `TaskDetail` in `InboxItemDetail.tsx` to be draft-aware. Compute `const draft = readDraftFromTask(task);`.

- **Schedule draft** (`draft?.kind === 'schedule'`): render a card titled "Schedule request — {draft.patientName}" with
  labeled rows: Suggested visit = `draft.requestedVisitType ?? '—'`; Reason = `draft.scheduleReason ?? '—'`;
  Timing = `draft.suggestedTiming ?? 'next available'`; Booking provider = `draft.providerName ?? task.owner?.display ?? '—'`.
  Buttons:
  - Primary **"Approve & schedule"** -> `await approveDraft(medplum, task.id!)`; on success
    `showSuccessNotification({ message: 'Visit booked for ' + draft.patientName })`, dispatch the `inbox-refresh`
    event, then `navigate(-1)`. Show a loading state; on error `showErrorNotification(err)`.
  - Secondary **"Decline"** (red, variant light) -> `await rejectDraft(medplum, task.id!)`; success notification,
    `inbox-refresh`, `navigate(-1)`.
  - If `draft.patientId`, also an "Open patient chart" button -> `/Patient/{patientId}`.
- **Other AI drafts** (`draft && (kind === 'message-reply' || 'referral' || 'prior-auth')`): render the draft body in an
  editable `Textarea` (default `draft.body`), with **"Approve & send"** -> `approveDraft(medplum, task.id!, editedBody)`
  (success -> notify + inbox-refresh + navigate(-1)) and **"Decline"** -> `rejectDraft`. (No bare "Mark Done".)
- **Non-draft Task** (`!draft`): keep the existing Description/Owner/Due/Status display and the "Mark Done" button
  (status -> completed, navigate(-1)); ADD an "Open patient chart" button when `task.for?.reference` is a `Patient/...`.

Import `approveDraft`, `rejectDraft`, `readDraftFromTask` from `../../lib/agentic-drafts/draft-queue`.

In `InboxItemPage.tsx`: above the card, add a breadcrumb/eyebrow so the user knows where they are — a small
uppercase "Inbox" eyebrow line (use `SCA_TYPOGRAPHY.fontSize.xs`, `SCA_COLORS.textTertiary`) directly under the
"Back to Inbox" button and before the item title. Keep the existing "Back to Inbox" button.

### ACCEPTANCE
1. Opening a schedule-draft Task shows patient + suggested visit/reason/timing + booking provider, with
   "Approve & schedule" and "Decline" (NO bare "Mark Done"). Approving books the visit (via INBOX2-1's `approveDraft`),
   shows "Visit booked for {patient}", and returns to the previous list.
2. Opening a message-reply/referral/prior-auth draft shows an editable body + "Approve & send" + "Decline".
3. A non-draft Task still shows "Mark Done" plus "Open patient chart" when it targets a patient.
4. The inbox item page shows an "Inbox" eyebrow/breadcrumb above the title.
5. Build green; tests green.

### OUT OF SCOPE
- Editing schedule date/time in the UI (booking uses the helper's default slot); the daemon/booking internals
  (done in INBOX2-1).
