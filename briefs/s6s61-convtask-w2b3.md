# Brief: s6s61-convtask-w2b3 — Type-specific task completion actions

**Goal:** Source-tasks currently close via the generic "Mark Complete," which closes the Task but does NOT perform the real clinical update. Add type-specific completion actions through a single generalized modal so the uniform Tasks shell does the right clinical write per task type. This finishes the Conversations/Tasks Wave 2.

A `result-review` action modal already exists in `TasksQueuePage.tsx` (from w2b1: shows the report + "Mark reviewed"). Generalize it into ONE `TaskActionModal` that handles all source task types, then remove the result-only modal.

Build gate: `npx tsc --noEmit && npm run build`. Fix all type/lint errors and keep tests green.

---

## Sub-brief 1 — Generalized TaskActionModal
NEW FILE: `src/components/tasks/TaskActionModal.tsx`
Props: `{ task: Task | null; onClose: () => void; onDone: () => void }`. When `task` is set, read `getTaskType(task)` and fetch the linked resource from `task.focus.reference`. Render a title, a type-specific summary, and type-specific action button(s). Use the existing `completeTask` helper + Mantine notifications consistent with the Tasks page. After any successful action: call `onDone()` (which the parent wires to `invalidateSearches('Task')` + refetch) and `onClose()`.

Per type:
- **result-review** — focus is a `DiagnosticReport`. Show `report.code?.text`, the indication chip via `getResultIndication(task)` (reuse the same badge styling as the row), and `report.conclusion`. Action **"Mark reviewed"** → `completeTask` then best-effort `updateResource` setting the report `status='final'`.
- **refill-approval** — focus may be a `MedicationRequest` OR a `Communication`.
  - If `MedicationRequest`: show the medication name (`medicationCodeableConcept?.text ?? coding[0].display ?? medicationReference?.display`) and dosage text if present. Two actions: **"Approve"** → set MR `status='active'` then `completeTask`; **"Deny"** → set MR `status='cancelled'` then `completeTask`.
  - If `Communication`: show `topic?.text` / the payload text. One action: **"Mark handled"** → `completeTask` only (no resource write).
- **note-signing** — focus is a `Composition`. Show `composition.title` and, if present, the first section's narrative text as a short preview. Action **"Sign note"** → set Composition `status='final'` then `completeTask`.
- **document-review** — focus is a `DocumentReference`. Show its description/type. Action **"Mark reviewed"** → set the extension whose url === `REVIEW_STATE_URL` (import from `../../lib/documents/upload-document`) to `valueCode='reviewed'` (add the extension if absent) then `completeTask`.
- Unknown/missing focus: show a minimal view with a single **"Mark complete"** that calls `completeTask`.

Handle fetch failures gracefully (show the action with whatever label applies; never crash). Show a small loading state while the focus resource loads.

## Sub-brief 2 — Wire into the Tasks page
File: `src/pages/tasks/TasksQueuePage.tsx`
- Remove the existing result-review-only modal and its branch; replace with the new `TaskActionModal`.
- In `handleRowClick`: if `getTaskType(task)` is defined (any recognized source type), set `actionTarget` state to the task (opens `TaskActionModal`); otherwise keep the existing generic edit-modal behavior for plain tasks.
- Pass `onDone` = a callback that runs `invalidateSearches('Task')` and `refetch()`.

## Tests
- Keep existing Tasks-page tests green; adjust any that referenced the old result modal. Add a light test that `handleRowClick` routes a typed task to the action modal.
