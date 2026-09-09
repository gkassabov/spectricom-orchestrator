# Toni Batch S6S60 — FIX-03: /Inbox surface completion (4 briefs)

## Repo: clinical-mp
## Batch ID: s6s60-fix-03-inbox-cluster
## Briefs: 4
## Estimated runtime: 40-55m
## Predecessor: clinical-mp main @ a617327
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 60
## Severity: P1 (demo dashboard)

## CONTEXT

Synth UAT (Dr. Whitman, J-A dashboard) found most dashboard defects trace to one half-finished
surface — the newer `/Inbox`. The counts themselves reconcile (notes 27=27, tasks 48 = 4 today +
44 overdue, refills 14=14, messages 22=22 via single-source `useInboxCounts`). The real defects:

  3a. **Tasks tile dead-links.** `ActionInboxCard.tsx` line 27 routes the Tasks tile to
      `/Inbox/tasks`, but there is no `InboxTasksPage` (only Notes/Labs/Messages/Refills pages
      exist) → "Item not found". The working Tasks queue is `/Tasks` (`TasksQueuePage`).
  3b. **Stale Tasks badge.** On `/Tasks`, the Overdue tab badge and the top-nav Tasks badge show
      "4" until the Overdue tab is selected, then correct to 44 (lazy per-tab count).
  3c. **Unsigned-note detail is a dead stub.** `InboxItemDetail.tsx` `case 'note'` renders only
      `item.subject` + `item.preview` (which is "(no content)" when the draft Composition has no
      text section). No body, no link to the encounter, no Sign action → EOD sign-off impossible
      from the inbox.
  3d. **Sent reply not surfaced.** `MessageDetail.handleSendReply` DOES persist (it
      `createResource`s a reply Communication with `inResponseTo`), but the `/Inbox` item detail
      renders only the single original Communication — not the thread — so on reload the sent
      reply is invisible, and the Sent folder doesn't list it. (UAT mis-read this as "reply not
      persisting"; the write works, the surfacing doesn't.) Also dead: LabDetail "Acknowledge"
      and RefillDetail "Approve/Deny" buttons have no onClick.

## GOAL

Make the `/Inbox` surface trustworthy for the demo: Tasks tile reaches a real queue, badges are
correct, a note can be opened to sign, and a sent reply is visible in-thread. Eliminate dead
action buttons.

## FILES

- `src/components/home/ActionInboxCard.tsx` — Tasks tile href (3a).
- `src/pages/tasks/TasksQueuePage.tsx` — eager tab counts (3b).
- `src/components/inbox/InboxItemDetail.tsx` — note branch + MessageDetail thread + dead buttons (3c, 3d).
- `src/lib/inbox/classify-item.ts` + `src/lib/inbox/types.ts` — carry the note's encounter/patient refs on `NoteInboxItem` (3c).
- `src/pages/inbox/InboxMessagesPage.tsx` — confirm the Sent folder query surfaces provider replies (3d).

## ACCEPTANCE CRITERIA

1. (3a) Clicking the Home **Tasks** tile lands on `/Tasks` (the working queue), never "Item not found".
2. (3b) On `/Tasks`, the Overdue tab badge and top-nav Tasks badge read **44** on first paint,
   without needing to select the tab; counts match the queue.
3. (3c) Opening an unsigned note from `/Inbox/notes` shows the note's content (if any) AND an
   **"Open to sign"** button that routes to that note's encounter finalize/sign page. From there
   the provider can sign. No more "(no content)" dead stub with no action.
4. (3d) After sending an inbox reply, the **thread view shows the sent reply** (original + reply,
   newest last) without a reload, and it survives a reload. The reply also appears in the Sent
   folder. No "Reply sent" toast followed by an empty thread.
5. (3d) No dead buttons: LabDetail "Acknowledge" marks the result reviewed (mirroring
   DocumentReviewDetail's `markDocumentReviewed` pattern) and RefillDetail "Approve/Deny" either
   perform the same approve/deny used on `/refills` OR route the user to `/refills` — no inert
   buttons remain.
6. No count regressions; `useInboxCounts` stays the single source of truth.

## IMPLEMENTATION SKETCH

3a — `ActionInboxCard.tsx`:
```ts
{ key: 'tasks', label: 'Tasks', icon: IconChecklist, dotColor: '#5C7C2F', href: '/Tasks' },  // was '/Inbox/tasks'
```

3b — `TasksQueuePage.tsx`: compute Today/Upcoming/Overdue/Done counts eagerly on data load
(single pass over the fetched tasks) and feed each tab badge from that, rather than computing the
active tab's count on selection. Also feed the top-nav Tasks badge from the same overdue count.

3c — `classify-item.ts` `classifyNote`: add `encounterId: comp.encounter?.reference?.replace('Encounter/','')`
and `patientId` to the returned `NoteInboxItem` (extend the type in `types.ts`). In
`InboxItemDetail.tsx` `case 'note'`, render the note body (Composition narrative/section text if
present) and a Button "Open to sign" → `navigate('/Patient/${patientId}/Encounter/${encounterId}/finalize')`
(or the existing encounter-note route). If no encounter ref, fall back to the patient chart.

3d — In `MessageDetail`, after `createResource(outgoing)`, append it to a local thread list and
render the full thread (load replies via `Communication?part-of=...` or `inResponseTo`), sorted by
`sent`. On mount, fetch the thread for the opened message, not just the single resource. Verify the
Sent folder query in `InboxMessagesPage` includes `sender=<me>` replies (add the category/folder
tag if the Sent filter requires one). Wire LabDetail "Acknowledge" + RefillDetail buttons (see AC 5).

## OUT OF SCOPE

- Full consolidation of the two inbox IAs (`/Inbox` vs `/Communication`) — bigger refactor, post-demo.
- Mobile inbox thread page changes beyond parity.

## DEFINITION OF DONE

- Tasks tile → `/Tasks`; Task badges correct on first paint.
- Note detail offers a real path to sign.
- Sent reply visible in-thread + in Sent; no inert buttons.
- Commit message: `FIX-03: complete /Inbox surface — tasks route, badges, note-sign, reply thread (S6S60)`.

## §29 / §31

§29 standard.

§31 smoke:
1. Home → click Tasks tile → lands on `/Tasks` (not "Item not found"); Overdue badge reads 44 immediately.
2. Home → Unsigned notes → open a note → "Open to sign" routes to the encounter; sign works.
3. Open an inbox message → reply → reply appears in-thread immediately and after reload; shows in Sent.
4. Open a lab/refill inbox item → Acknowledge/Approve/Deny perform a real action (or route), no inert buttons.
