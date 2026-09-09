# Toni Batch S6S61 — TASKS-1: keep AI-draft proposals out of the generic Task surfaces

## Repo: clinical-mp
## Batch ID: s6s61-tasks-1-exclude-ai-drafts
## Briefs: 1
## Estimated runtime: 15-20m
## Predecessor: clinical-mp main @ b542c31
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 20
## Severity: P1 (correctness/safety: AI schedule-drafts appear in the generic Tasks page; "Mark Complete" there sets the Task completed, which the daemon treats as APPROVED and books the visit with no patient/visit review — bypassing the Approve & schedule card)

## CONTEXT (confirmed in code)

AI drafts are FHIR Tasks created by `enqueueDraft` (`src/lib/agentic-drafts/draft-queue.ts`) with `intent: 'proposal'`
and a `urn:spectricom:ai-draft` extension (`AI_DRAFT_EXTENSION_URL` in `src/lib/agentic-drafts/types.ts`). They are
meant to be approved ONLY in the Inbox approval queue (Inbox → Tasks), via the Approve & schedule / Approve & send card.

But three generic task surfaces fetch Tasks by owner+status and do NOT filter these proposals out, so the drafts
leak in as ordinary to-dos:
- `src/hooks/usePractitionerTasks.ts` — powers the /Tasks page (`TasksQueuePage`); its generic "Edit Task" modal's
  "Mark Complete" calls `completeTask` → `status: 'completed'` → the daemon's pre-encounter pass books the visit.
- `src/hooks/home/useHomeInboxTasks.ts` — the Home "Needs your attention → Tasks" count (`setCount(results.length)`).
- `src/hooks/useOverdueTaskCount.ts` — the top-nav Tasks overdue badge (`countOverdue(tasks)`).

## GOAL

AI-draft proposal Tasks are excluded from all THREE generic task surfaces (the /Tasks page + its tab counts, the
Home Tasks count, the nav overdue badge). They continue to appear ONLY in the Inbox approval queue (unchanged).

---

## BRIEF TASKS1-1 — exclude agent-draft proposals from generic task hooks

### FILES
- `src/lib/agentic-drafts/draft-queue.ts` (add + export `isAgentDraftTask`)
- `src/hooks/usePractitionerTasks.ts`
- `src/hooks/home/useHomeInboxTasks.ts`
- `src/hooks/useOverdueTaskCount.ts`
- tests under `src/hooks/__tests__/` (and/or `src/lib/agentic-drafts/__tests__/`)

### IMPLEMENT
- In `draft-queue.ts`, add and export:
  ```ts
  import type { Task } from '@medplum/fhirtypes';
  export function isAgentDraftTask(task: Task): boolean {
    return task.intent === 'proposal'
      && (task.extension ?? []).some((e) => e.url === AI_DRAFT_EXTENSION_URL);
  }
  ```
  (`AI_DRAFT_EXTENSION_URL` is already imported in this file.)
- `usePractitionerTasks.ts`: after the Task search results are assembled into the array the hook returns as `tasks`,
  filter out agent drafts: `.filter((t) => !isAgentDraftTask(t))`. The /Tasks page table AND its tab counts
  (Today/Upcoming/Overdue/Done, all derived from this `tasks`) must therefore never include AI drafts.
- `useHomeInboxTasks.ts`: change `setCount(results.length)` to `setCount(results.filter((t) => !isAgentDraftTask(t)).length)`.
- `useOverdueTaskCount.ts`: change `setCount(countOverdue(tasks))` to `setCount(countOverdue(tasks.filter((t) => !isAgentDraftTask(t))))`.

### ACCEPTANCE
1. A Task with `intent: 'proposal'` + the `urn:spectricom:ai-draft` extension does NOT appear on the /Tasks page,
   is not in any /Tasks tab count, is not in the Home "Tasks" count, and is not in the nav overdue badge.
2. A normal Task (no AI-draft extension) AND an escalation Task (no AI-draft extension) still appear and count exactly
   as before (unit tests assert both: a draft is excluded, a non-draft is retained).
3. Build green; tests green.

### OUT OF SCOPE (do NOT touch)
- The Inbox: `src/lib/inbox/use-inbox-items.ts`, `classify-item.ts`, `InboxPage`, `InboxItemDetail`. AI drafts MUST
  still appear in Inbox → Tasks (the approval queue) — do not filter them there.
- The "Edit Task" modal itself; the daemon; `completeTask`.
- Task count reconciliation between the /Tasks header and the Overdue tab (separate item).
