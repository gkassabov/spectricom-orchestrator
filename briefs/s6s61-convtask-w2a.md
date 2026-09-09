# Brief: s6s61-convtask-w2a — Conversations/Tasks Wave 2A

**Goal:** Per the Conversations/Tasks IA contract, rename the Inbox to "Conversations" and make it render **messages only**. Action items (tasks/approvals) live in the Tasks page. The Inbox rail's redundant "Tasks" folder is dropped.

**Scope note:** Native action items (labs, refills, unsigned notes, document-reviews) are being removed from the Conversations unified view in this wave. They remain reachable in their native pages; a following wave brings them into the Tasks page as linked Task objects. Do NOT attempt to surface them in the Tasks page here.

Frontend-only. No daemon changes. Build gate: `npx tsc --noEmit && npm run build`. Fix all type/lint errors and any broken tests in the touched areas.

---

## Sub-brief 1 — Top-nav entry: Inbox → Conversations
File: `src/shell/TopMainNav.tsx`
- In `NAV_ITEMS`, change the Inbox entry to `label: 'Conversations'` and `icon: <IconMessages size={18} />`. Import `IconMessages` from `@tabler/icons-react`. Keep `href: '/Inbox'` and `contextKey: 'inbox'` unchanged. Remove the `IconInbox` import if it is now unused in this file.
- In `NAV_FEATURE_MAP`, rename the `Inbox` key to `Conversations` (keep the same value array `['inbox-workflow', 'escalation-queue']`).
- Update any test asserting the `'Inbox'` nav label to expect `'Conversations'`.

## Sub-brief 2 — InboxPage becomes Conversations (messages-only)
File: `src/pages/inbox/InboxPage.tsx`
- Header: change the title text `Inbox` → `Conversations`; change the icon `IconInbox` → `IconMessages` (update the import).
- In the `folder === null` (unified) block, render ONLY the `Messages` `InboxSection`. Remove the Tasks, "Labs to Review", Refills, "Document Review", and "Unsigned notes" sections from that block.
- Remove the `folder === 'tasks'` branch entirely. Remove `'tasks'` from `VALID_FOLDERS` and from the `InboxFolder` type so it becomes `'messages' | 'sent'`. Keep the `messages` and `sent` branches.
- Trim the `sections` useMemo so it only computes/returns `messages` (drop the now-unused notes/labs/tasks/refills/documentReviews accumulators) to keep lint green. The `filteredItems` logic stays.
- Keep `handleItemClick` → `/Inbox/${item.id}` unchanged.
- Update inbox tests that assert the Tasks/Labs/Refills/Notes/Document-Review sections appear in the default view, and any test referencing the inbox `tasks` folder.

## Sub-brief 3 — Inbox rail: drop the Tasks folder
File: `src/shell/rail-content/InboxRailContent.tsx`
- Remove the `{ label: 'Tasks', folder: 'tasks', icon: IconBell }` entry from `FOLDERS`. Keep `Messages` and `Sent`. Remove the now-unused `IconBell` import.
- Update any rail test accordingly.

## Sub-brief 4 — Repoint stray deep-links
- Search the `src` tree for any hardcoded links to `/Inbox?folder=tasks`. Repoint each to `/Tasks`. (Leave `/Inbox?folder=messages` and `/Inbox?folder=sent` as-is.)
