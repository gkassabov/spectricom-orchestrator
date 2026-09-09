# Brief: s6s61-convtask-w2b2 — Source-task generator: refills, notes, doc-reviews

**Goal:** Extend the deterministic source-task generator (from w2b1) to the remaining actionable types, mirroring the EXACT actionable signals the inbox already uses. Each spawns a typed, linked FHIR `Task` that flows into the Tasks page through the existing uniform shell under its facet. No new UI shell — same rows, faceted.

This wave creates the tasks and routes them. Type-specific completion ACTIONS (approve refill / sign note / mark doc reviewed) are a following wave — for now these tasks are completable via the existing generic task modal.

Build gate: `npx tsc --noEmit && npm run build`. Fix all type/lint errors and tests in touched areas. Touches `task-types.ts`, `generate-source-tasks.ts`, the daemon, and `TaskRow.tsx`.

---

## Sub-brief 1 — Constants
File: `src/lib/tasks/task-types.ts`
- Add `export const REFILL_REQUEST_TAG_SYSTEM = 'urn:spectricom:refill-request'` (the meta.tag system marking a Communication as a patient refill request — the message-sourced path).

## Sub-brief 2 — Three new generators
File: `src/lib/tasks/generate-source-tasks.ts`
Reuse the existing `resolveOwner` and the dedup pattern (query `Task?focus=<ref>&_count=1`, skip if any existing Task of the SAME task-type for that focus, or any task with that focus). Each generator returns `{ created, skipped }` and is independently try/catch-guarded by the caller.

**`generateRefillApprovalTasks(medplum, opts?)`** — two source paths:
- Path A — MedicationRequest: `searchResources('MedicationRequest', { status: 'draft', intent: 'order', _count: '200', _sort: '-authoredon' })`, then keep only those where `mr.requester?.reference?.startsWith('Patient/')`. (This is the established refill-request signal — a draft order requested BY the patient, not an active prescription.)
- Path B — Communication: `searchResources('Communication', { _tag: REFILL_REQUEST_TAG_SYSTEM, _count: '200', _sort: '-sent' })`, keep only `status !== 'entered-in-error'`.
- For each source: dedup by `focus`; create Task `code: taskTypeToCoding('refill-approval')`, `focus` → the source (`MedicationRequest/<id>` or `Communication/<id>`), `for` → the patient (`mr.subject` for path A; `comm.subject` for path B), `owner` via `resolveOwner` (use the patient ref to look up generalPractitioner), `status: 'requested'`, `intent: 'order'`, `authoredOn` now, `meta.tag` source tag `{ system: TASK_SOURCE_TAG_SYSTEM, code: 'refill-approval' }`, `description`: path A → `Approve refill: <med name>` where med name = `mr.medicationCodeableConcept?.text ?? coding[0].display ?? mr.medicationReference?.display ?? 'Medication'`; path B → `comm.topic?.text ?? 'Refill request'`.

**`generateNoteSigningTasks(medplum, opts?)`**:
- `searchResources('Composition', { status: 'preliminary', _count: '200', _sort: '-date' })`.
- For each (require `id` and `subject`): dedup by `focus`; create Task `code: taskTypeToCoding('note-signing')`, `focus` → `Composition/<id>`, `for` → `comp.subject`, `owner` → `comp.author?.[0]` if it has a `reference`, else `resolveOwner` via the patient, `status: 'requested'`, `intent: 'order'`, `description: 'Sign note: ' + (comp.title ?? 'Clinical note')`, source tag code `'note-signing'`.

**`generateDocumentReviewTasks(medplum, opts?)`**:
- `searchResources('DocumentReference', { type: 'http://loinc.org|47420-5', _count: '100', _sort: '-date' })`, then keep only those with an extension whose `url === REVIEW_STATE_URL` (import from `../documents/upload-document`) and `valueCode === 'pending'`.
- For each (require `id` and `subject`): dedup by `focus`; create Task `code: taskTypeToCoding('document-review')`, `focus` → `DocumentReference/<id>`, `for` → `docRef.subject`, `owner` via `resolveOwner`, `status: 'requested'`, `intent: 'order'`, `description`: derive a category label from `docRef.category?.[0]?.coding?.[0]?.code` via the documents category map if available, else `'Review document'`, source tag code `'document-review'`.

**`generateAllSourceTasks(medplum)`** — NEW orchestrator: calls `generateResultReviewTasks`, `generateRefillApprovalTasks`, `generateNoteSigningTasks`, `generateDocumentReviewTasks`, each wrapped in its own try/catch so one failure can't block the others. Log a combined summary line and return the aggregate `{ created, skipped }`.

## Sub-brief 3 — Daemon: call the orchestrator
File: `src/daemon/agentic-daemon.ts`
- Change the throttled deterministic phase to call `generateAllSourceTasks(medplum)` instead of only `generateResultReviewTasks`. Keep the same 5-minute throttle and the first-cycle backfill. Log the aggregate counts. Keep the try/catch guard around the whole phase.

## Sub-brief 4 — Row legibility: task-type label
File: `src/components/tasks/TaskRow.tsx`
- Next to the description, render a small muted Badge with a short type label derived from `getTaskType(task)`: result-review→"Result", refill-approval→"Refill", note-signing→"Sign", document-review→"Doc". For result-review tasks, keep the existing Normal/Abnormal/Review indication badge as well. Tasks with no recognized type render no type badge (unchanged).

## Tests
- Add unit tests for the new generators' source-filtering logic where practical (e.g., the refill clientFilter keeps only patient-requested draft orders; note generator targets preliminary compositions; doc generator requires the pending review-state). Keep existing tests green.
