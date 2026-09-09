## Repo: clinical-mp
## Batch ID: s6s61-convtask-w1
## Briefs: 2 (W1A surface+facets+counts, W1B approval-card-in-tasks)
## Predecessor: 41c727c (SCHED-2-FIX)
## Fire mechanism: orchestrator queue --approve --skip-sit
## TONI_TIMEOUT_MIN: 30
## Severity: feature

## CONTEXT
Wave 1 of the Conversations/Tasks IA rework (contract: SCA_Conversations_Tasks_IA_Contract_v1-0). Make the **Tasks page the single home for every action item**, with source facets. This DELIBERATELY REVERSES TASKS-1 (which excluded AI drafts from the Tasks surfaces) — under the new contract, AI-draft approvals belong in Tasks, not the Inbox.

Today: `usePractitionerTasks` (src/hooks/usePractitionerTasks.ts line ~50) ends with `.filter((t) => !isAgentDraftTask(t))`; the same exclusion exists in `useHomeInboxTasks.ts` (~line 34) and `useOverdueTaskCount.ts` (~line 23). `TasksQueuePage.tsx` filters by time tabs only (TaskFilterTab today/upcoming/overdue/done via `filterTasks`), and opening a task shows a generic edit modal (editTarget) — there is no approval card. The rich AI-draft approval card (schedule "Approve & book", message-reply/referral/PA "Approve & send", "Decline / cancel hold") currently lives ONLY in `src/components/inbox/InboxItemDetail.tsx` (the draft-aware TaskDetail branch, via `readDraftFromTask`).

Wave 2 (later) strips these items out of the Inbox; do NOT touch the Inbox here. This wave only makes Tasks host + approve them.

## GOAL
Every action item (AI-draft approvals incl. schedule/refill/referral/PA, plus human and system tasks) shows in the Tasks page, grouped by a source facet, and AI-draft tasks are approvable directly from Tasks.

---

### BRIEF W1A -- surface AI drafts + source facets + counts

FILES:
- EDIT src/hooks/usePractitionerTasks.ts
- EDIT src/hooks/useHomeInboxTasks.ts
- EDIT src/hooks/useOverdueTaskCount.ts
- EDIT src/lib/tasks/types.ts
- NEW  src/lib/tasks/task-facets.ts
- EDIT src/pages/tasks/TasksQueuePage.tsx

IMPLEMENT:
1. usePractitionerTasks.ts: REMOVE the `.filter((t) => !isAgentDraftTask(t))` so AI-draft tasks (intent 'proposal' + ai-draft extension) are now included. (They are already in the active status set.)
2. Counts — adjust so the Home "Tasks" count + nav overdue badge reflect provider-actionable items WITHOUT the awaiting-patient noise:
   - In useHomeInboxTasks.ts and useOverdueTaskCount.ts, REPLACE the `!isAgentDraftTask(t)` exclusion with: include a task UNLESS it is an AI-draft schedule task still in scheduleState 'awaiting-patient-selection' (those are waiting on the patient, not the provider). Add a small helper `isAwaitingPatientDraft(task)` in src/lib/agentic-drafts/draft-queue.ts (read the ai-draft extension; true iff kind==='schedule' && scheduleState==='awaiting-patient-selection') and use it. So: patient-selected / ready approvals + all other drafts/tasks count; awaiting-patient ones do not.
3. types.ts: add `export type TaskFacet = 'approvals' | 'refills' | 'results' | 'escalations' | 'my-todos' | 'system';`
4. NEW task-facets.ts:
   - `export function taskFacet(task: Task): TaskFacet` — classify:
     * isAgentDraftTask(task): read the ai-draft kind; kind==='refill' -> 'refills'; else -> 'approvals'.
     * else if a meta.tag system contains 'escalation' OR the task code/description indicates escalation -> 'escalations'.
     * else if a meta.tag/code/category indicates results/labs/imaging review -> 'results'.
     * else if a meta.tag indicates system-generated (e.g. 'urn:spectricom:system-task') OR description matches unsigned-notes/care-gap -> 'system'.
     * else -> 'my-todos'.
   - `export const TASK_FACET_LABELS: Record<TaskFacet,string>` = Approvals / Refills / Results / Escalations / My to-dos / System.
   - `export function filterByFacet(tasks: Task[], facet: TaskFacet | 'all'): Task[]`.
5. TasksQueuePage.tsx: add a source-facet filter ABOVE the existing time tabs (a SegmentedControl or chip row: All + each facet with a count badge). Default = 'all'. Apply it to the task set so the visible list = facet filter THEN the existing time-tab filter (`filterTasks`). Keep the time tabs working. Empty facets may still show a chip with count 0.

ACCEPTANCE:
- `npx tsc --noEmit && npm run build` green.
- AI-draft tasks now appear in the Tasks page; a facet chip row filters by Approvals/Refills/Results/Escalations/My to-dos/System (+ All) with counts.
- Home Tasks count + nav overdue badge include provider-actionable approvals but NOT awaiting-patient schedule drafts.

OUT OF SCOPE: the approval card (W1B); any Inbox change (Wave 2).

---

### BRIEF W1B -- approval card available in the Tasks page

FILES:
- NEW  src/components/agentic-drafts/DraftApprovalCard.tsx
- EDIT src/components/inbox/InboxItemDetail.tsx
- EDIT src/pages/tasks/TasksQueuePage.tsx

IMPLEMENT:
1. Extract the existing AI-draft approval rendering into a SHARED component `DraftApprovalCard` (NEW file) that takes a Task (the AI-draft task) + an onDone callback, reads the draft via readDraftFromTask, and renders the SAME states already implemented in InboxItemDetail:
   - schedule draft: scheduleState 'awaiting-patient-selection' -> read-only "Scheduling in progress" (proposed times + hold + "Awaiting patient selection"); scheduleState 'patient-selected' -> "Patient selected: <slot>" + primary "Approve & book"; legacy schedule (no scheduleState) -> "Approve & schedule".
   - message-reply / referral / PA drafts -> editable body + "Approve & send".
   - all: "Decline / cancel hold" secondary (rejectDraft + cancel placeholder Appointment when placeholderAppointmentRef set).
   Reuse the existing approveDraft / rejectDraft logic — do NOT duplicate it; move/lift the JSX and wire the same handlers.
2. InboxItemDetail.tsx: replace its inline AI-draft TaskDetail branch with `<DraftApprovalCard task={...} onDone={...} />` so the Inbox keeps identical behavior through the shared component (no behavior change to the Inbox in this wave — Wave 2 removes it from the Inbox entirely).
3. TasksQueuePage.tsx: when the user opens a task that `isAgentDraftTask(task)` is true, render `<DraftApprovalCard>` (in the existing detail/modal slot, or a Modal) INSTEAD of the generic edit modal. Non-draft tasks keep the existing generic edit modal. After approve/decline, refetch the task list.

ACCEPTANCE:
- build green.
- Opening an AI-draft task from the Tasks page shows the rich approval card (e.g. a patient-selected schedule draft shows "Approve & book"), and approving it books + completes exactly as it does from the Inbox today.
- The Inbox's existing approval behavior is unchanged (now routed through the shared DraftApprovalCard).

OUT OF SCOPE: removing approvals from the Inbox (Wave 2); bidirectional task<->conversation linking (Wave 3).
