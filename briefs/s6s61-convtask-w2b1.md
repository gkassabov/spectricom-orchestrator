# Brief: s6s61-convtask-w2b1 — Source-task generator (Results) + FHIR task-type model

**Goal:** Preserve and extend FHIR. Introduce a **task-type** taxonomy carried on the FHIR `Task` itself, and a deterministic generator that spawns a linked `Task` for every diagnostic result, carrying a normal/abnormal indication. The Tasks page renders these through its existing uniform shell — they appear under the **Results** facet with an indication chip and can be reviewed/completed. Backing store (FHIR resource vs not) must NOT produce a different UI.

This wave covers **result-review** only. Refill/note/document-review types are a later pass — build the taxonomy generically so adding them is trivial, but do not implement them here.

Build gate: `npx tsc --noEmit && npm run build`. Fix all type/lint errors and tests in touched areas. Touches frontend + daemon.

---

## Sub-brief 1 — Task-type taxonomy + result indication
NEW FILE: `src/lib/tasks/task-types.ts`
- Export `const TASK_TYPE_SYSTEM = 'urn:spectricom:task-type'`.
- Export `type TaskType = 'result-review' | 'refill-approval' | 'note-signing' | 'document-review' | 'schedule-approval' | 'todo'`.
- `export function taskTypeToCoding(type: TaskType): CodeableConcept` → `{ coding: [{ system: TASK_TYPE_SYSTEM, code: type }], text: <human label> }`.
- `export function getTaskType(task: Task): TaskType | undefined` → reads the coding with `system === TASK_TYPE_SYSTEM` from `task.code`; returns its code as TaskType if present, else `undefined`.
- `export const TASK_TYPE_TO_FACET: Record<TaskType, TaskFacet>` → result-review→`results`, refill-approval→`refills`, note-signing→`system`, document-review→`system`, schedule-approval→`approvals`, todo→`my-todos`. (Import TaskFacet from `./types`.)
- Result indication:
  - `export const RESULT_INDICATION_EXTENSION = 'urn:spectricom:result-indication'` (values `'normal' | 'abnormal' | 'review'`).
  - `export type ResultIndication = 'normal' | 'abnormal' | 'review'`.
  - `export function deriveResultIndication(report: DiagnosticReport, observations?: Observation[]): ResultIndication` — STRUCTURED FIRST: if any provided Observation has an `interpretation` coding code in {H,HH,L,LL,A,AA,LU,HU} → `'abnormal'`; if all observations present and none abnormal → `'normal'`. FALLBACK on `report.conclusion` text (lowercased): if it matches any of /elevated|above|below|high\b|low\b|abnormal|outside|positive|deficien|exceed/ → `'abnormal'`; else if it matches /within normal|normal range|\bnormal\b|negative|unremarkable|no abnormal/ → `'normal'`; else `'review'`.
  - `export function getResultIndication(task: Task): ResultIndication | undefined` — reads the `RESULT_INDICATION_EXTENSION` valueCode from `task.extension`.
- Export `const TASK_SOURCE_TAG_SYSTEM = 'urn:spectricom:task-source'` (used to tag generator-created tasks, value = the task type).

## Sub-brief 2 — Route facets through task-type
File: `src/lib/tasks/task-facets.ts`
- In `taskFacet(task)`, FIRST check `getTaskType(task)` (import from `./task-types`); if defined, return `TASK_TYPE_TO_FACET[type]`. Otherwise fall back to the existing heuristic logic unchanged.

## Sub-brief 3 — The generator
NEW FILE: `src/lib/tasks/generate-source-tasks.ts`
- `export async function generateResultReviewTasks(medplum: MedplumClient, opts?: { maxReports?: number }): Promise<{ created: number; skipped: number }>`.
- Query: `medplum.searchResources('DiagnosticReport', { _sort: '-_lastUpdated', _count: String(opts?.maxReports ?? 200), status: 'final,preliminary,amended' })`.
- For each report (skip if no `id` or no `subject`):
  - DEDUP: `medplum.searchResources('Task', { focus: 'DiagnosticReport/' + report.id, _count: '1' })`; if any existing Task whose `getTaskType` is `'result-review'` (or any task with that focus) → skip (count skipped), regardless of task status.
  - Resolve owner: fetch the Patient (`report.subject.reference`), use `patient.generalPractitioner?.[0]` if present; else `report.performer?.[0]`; else leave `owner` unset. Cache patient fetches by id to avoid refetching.
  - Fetch the report's Observations (from `report.result` refs, best-effort, tolerate failures) to pass into `deriveResultIndication`.
  - Create Task: `status: 'requested'`, `intent: 'order'`, `code: taskTypeToCoding('result-review')`, `focus: { reference: 'DiagnosticReport/' + report.id }`, `for: report.subject`, `owner` (if resolved), `authoredOn: new Date().toISOString()`, `description: 'Review result: ' + (report.code?.text ?? 'Lab result')`, `meta.tag: [{ system: TASK_SOURCE_TAG_SYSTEM, code: 'result-review' }]`, and `extension: [{ url: RESULT_INDICATION_EXTENSION, valueCode: <derived indication> }]`.
  - Count created.
- Idempotent and safe to re-run. Use a module-level logger or console with a clear prefix.

## Sub-brief 4 — Daemon phase (deterministic, throttled)
File: `src/daemon/agentic-daemon.ts`
- Add a deterministic phase that calls `generateResultReviewTasks(medplum)` — NO LLM. Wire it into `runCycle` alongside the existing phases.
- THROTTLE: keep a module-level `lastResultGenAt` timestamp; only run the generator if more than 5 minutes have elapsed since the last run (so it does not hammer FHIR every 60s cycle). On the very first cycle after start, run it (backfill).
- Log created/skipped counts. Guard with try/catch so a generator failure never crashes the cycle.

## Sub-brief 5 — Indication chip on the task row
File: `src/components/tasks/TaskRow.tsx`
- For tasks where `getTaskType(task) === 'result-review'`, render a small Badge next to the task description from `getResultIndication(task)`: `abnormal` → red filled "Abnormal"; `normal` → gray light "Normal"; `review` → yellow light "Review". Other task types unchanged.

## Sub-brief 6 — Result-review detail + "Mark reviewed"
File: `src/pages/tasks/TasksQueuePage.tsx`
- In `handleRowClick`, BEFORE the existing edit-modal branch, add: if `getTaskType(task) === 'result-review'`, set a new `resultTarget` state to the task and return (do not open the edit modal).
- Add a Modal (title "Review result") shown when `resultTarget !== null`. On open, fetch the linked DiagnosticReport via `resultTarget.focus.reference`. Render: the report `code.text`, the indication chip (`getResultIndication`), the report `conclusion` text, and a primary button **"Mark reviewed"**.
- "Mark reviewed" → `completeTask(medplum, resultTarget.id, agentRef)`; then best-effort set the DiagnosticReport `status` to `'final'` (`medplum.updateResource`); then close the modal, `invalidateSearches('Task')`, and `refetch()`. Show success/error notifications consistent with the rest of the page.
- Plain (non-result) tasks keep the existing edit modal behavior.

## Tests
- Update/add unit tests for `getTaskType`/`taskTypeToCoding`/`deriveResultIndication` (cover the conclusion-text fallback cases) and the facet routing through task-type. Keep existing Tasks-page tests green.
