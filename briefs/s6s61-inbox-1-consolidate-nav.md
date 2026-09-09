# Toni Batch S6S61 — INBOX-1: consolidate to one inbox, fix navigation, taxonomy, back-links

## Repo: clinical-mp
## Batch ID: s6s61-inbox-1-consolidate-nav
## Briefs: 4
## Estimated runtime: 20-30m
## Predecessor: clinical-mp main @ 08f561b
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 30
## Severity: P1 (provider-facing: two competing inboxes wired to different entry points; junk-led default view; mislabeled folders; broken back-links)

## CONTEXT (all confirmed in code)

There are TWO inbox implementations and they are wired to different entry points:
- OLD: `/Communication` -> `src/pages/messages/MessagesPage.tsx` (Medplum `ThreadInbox`). The top-nav "Inbox"
  (`src/shell/TopMainNav.tsx` NAV_ITEMS, href `/Communication?status=in-progress`) AND
  `src/pages/home/HomeEndOfDaySection.tsx` (two `navigate('/Communication?status=in-progress')` calls) point here.
- NEW: `/Inbox` -> `src/pages/inbox/InboxPage.tsx`. The left rail (`src/shell/rail-content/InboxRailContent.tsx`)
  points here via `?folder=...`.

So nav + Home land on the OLD inbox; the rail lands on the NEW one; "Back to Inbox" lands on a third view
(bare `/Inbox`, a firehose led by junk "Notes"). We are standardizing on the NEW `/Inbox` and retiring the old one.

Additional confirmed facts:
- `src/shell/useShellContext.ts:32` maps `/inbox`, `/communication`, `/fax` -> context 'inbox'.
- `src/pages/inbox/InboxPage.tsx`: `folder === null` renders a firehose (Notes, Messages, Labs, Tasks, Refills,
  Document Review — in that order, Notes FIRST). The left-rail folder 'notifications' renders a section titled
  "Tasks" (label mismatch). 'faxes'/'archive' folders render "Nothing here yet" (dead).
- `src/components/inbox/InboxItemPage.tsx` "Back to Inbox" -> `navigate('/Inbox')` (bare firehose).
- `src/components/inbox/InboxItemDetail.tsx`: `MessageDetail.handleStateChange` and `TaskDetail.handleMarkDone`
  both `navigate('/Inbox')` after acting (bare firehose, not where the user came from).

## GOAL

One inbox (`/Inbox`). Nav + Home + back-links all resolve there. Coherent rail (Messages / Tasks / Sent).
Default overview leads with actionable items, not junk drafts. Back-links return the user where they came from.

---

## BRIEF INBOX1-1 — single inbox entry points; retire /Communication

### FILES
- `src/shell/TopMainNav.tsx`
- `src/pages/home/HomeEndOfDaySection.tsx`
- `src/App.tsx`
- `src/shell/useShellContext.ts`

### IMPLEMENT
- In `TopMainNav.tsx` NAV_ITEMS, change the "Inbox" item `href` from `/Communication?status=in-progress` to `/Inbox`.
- In `HomeEndOfDaySection.tsx`, change BOTH `navigate('/Communication?status=in-progress')` calls to `navigate('/Inbox?folder=messages')`.
- In `App.tsx`, REPLACE the standalone `/Communication` route block (the one rendering `MessagesPage` with an
  `index` child and a `:messageId` child — currently ~lines 376-378) with a single redirect:
  `<Route path="/Communication" element={<Navigate to="/Inbox" replace />} />`.
  Then remove the now-unused `MessagesPage` import. Do NOT touch the `/Communication/new`, `/Communication/:messageId/view`,
  or `Communication`/`Communication/:messageId` routes that live under other parent layouts.
- In `useShellContext.ts` line ~32, remove the `lower.startsWith('/communication') ||` clause (route is now a redirect);
  keep `/inbox` and `/fax`.

### ACCEPTANCE
1. Clicking top-nav "Inbox" navigates to `/Inbox` and the "Inbox" nav item renders active (highlighted).
2. Home End-of-Day links navigate to `/Inbox?folder=messages`.
3. Visiting `/Communication` redirects to `/Inbox`. `MessagesPage` is no longer referenced anywhere in routing.
4. Build green; tests green.

### OUT OF SCOPE
- Deleting the `MessagesPage.tsx` file (leave it on disk, just unrouted/unimported).
- Patient-scoped Communication routes.

---

## BRIEF INBOX1-2 — clean default overview (no junk-led firehose)

### FILES
- `src/pages/inbox/InboxPage.tsx`

### IMPLEMENT
- In the `folder === null` overview block, REORDER the `<InboxSection>` list to be action-first and de-emphasize
  drafts, in EXACTLY this order: Tasks, Messages, Labs to Review, Refills, Document Review, Notes.
- Rename the Notes section title in the overview from "Notes" to "Unsigned notes".
  (Keep the section — it is clinically needed for signature visibility — just last.)

### ACCEPTANCE
1. Bare `/Inbox` renders Tasks first and "Unsigned notes" last.
2. Build green; tests green.

### OUT OF SCOPE
- Changing what counts as a note/task; data cleanup of empty notes (handled separately).

---

## BRIEF INBOX1-3 — coherent rail + folders (Messages / Tasks / Sent)

### FILES
- `src/shell/rail-content/InboxRailContent.tsx`
- `src/pages/inbox/InboxPage.tsx`
- `src/App.tsx`
- any file linking to `?folder=notifications` (grep repo-wide, e.g. `src/shell/NotificationsBell.tsx`)

### IMPLEMENT
- In `InboxRailContent.tsx`, set FOLDERS to exactly three entries:
  `{ label: 'Messages', folder: 'messages', icon: IconMail }`,
  `{ label: 'Tasks', folder: 'tasks', icon: IconBell }`,
  `{ label: 'Sent', folder: 'sent', icon: IconSend }`.
  Remove the Faxes and Archive entries (and now-unused icon imports).
- In `InboxPage.tsx`: set `VALID_FOLDERS` to `['messages','tasks','sent']`; update the `InboxFolder` type to
  `'messages' | 'tasks' | 'sent'`; rename the `folder === 'notifications'` branch to `folder === 'tasks'`
  (section title stays "Tasks", `defaultExpanded`); REMOVE the `folder === 'archive' || folder === 'faxes'`
  "Nothing here yet" branch. Keep the `folder === 'sent'` branch.
- Grep the repo for `folder=notifications` and update any such links to `folder=tasks`.
- In `App.tsx`, change the `/faxes` redirect target from `/Inbox?folder=faxes` to `/Fax/Communication`.

### ACCEPTANCE
1. The inbox left rail shows exactly: Messages, Tasks, Sent.
2. `/Inbox?folder=tasks` renders the Tasks section expanded; `/Inbox?folder=notifications` is no longer produced
   by any in-app link.
3. No dead Faxes/Archive folder views remain reachable from the rail.
4. Build green; tests green.

### OUT OF SCOPE
- The standalone Fax page (`/Fax/Communication`) behavior.

---

## BRIEF INBOX1-4 — back-links return where the user came from

### FILES
- `src/pages/inbox/InboxItemPage.tsx`
- `src/components/inbox/InboxItemDetail.tsx`
- `src/pages/inbox/InboxPage.tsx`

### IMPLEMENT
- In `InboxItemPage.tsx`, change the "Back to Inbox" button onClick from `navigate('/Inbox')` to `navigate(-1)`.
- In `InboxItemDetail.tsx`, change the post-action navigations from `navigate('/Inbox')` to `navigate(-1)` in BOTH:
  `MessageDetail.handleStateChange` (the `updated.status === 'completed'` branch) and `TaskDetail.handleMarkDone`.
- In `InboxPage.tsx`, REMOVE the "Back to Home" button block (the overview is a top-level destination reached via
  the nav; it should not have a back-to-home affordance). Remove the now-unused `IconArrowLeft` import if unused.

### ACCEPTANCE
1. Opening an inbox item then clicking "Back to Inbox" returns to the previous list (folder/overview), not bare `/Inbox`.
2. After "Mark Done" or resolving a message, the user is returned to the previous list and the item drops off.
3. The `/Inbox` overview no longer shows a "Back to Home" button.
4. Build green; tests green.

### OUT OF SCOPE
- Any change to the action semantics themselves (only the post-action navigation target changes).
