# Toni Batch S6S61 — MSG-03: portal threads invisible in provider inbox until replied (Medplum _has child filter)

## Repo: clinical-mp
## Batch ID: s6s61-msg-03-thread-anchor
## Briefs: 1
## Estimated runtime: 20-30m
## Predecessor: clinical-mp main @ d75909c
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 30
## Severity: P1 (a patient's FIRST message never reaches the provider inbox; the concierge E2E is blocked at step 1->2)

## CONTEXT

Confirmed in code, the @medplum/react-hooks library, AND live Medplum data (:8103):
- Provider inbox `src/pages/messages/MessagesPage.tsx` renders Medplum `ThreadInbox`, whose hook
  (in `node_modules/@medplum/react-hooks`) queries threads with BOTH `part-of:missing=true` AND
  `_has:Communication:part-of:_id:not=null`. The `_has` clause shows a thread root ONLY if at least one
  Communication references it via `part-of` (the root has >=1 child message). The list preview is the
  latest child (GraphQL CommunicationList by part_of, _count:1, _sort:-sent).
- `src/lib/messaging/compose-message.ts` `composeNewThread` and `src/lib/messaging/phone-callback.ts`
  `requestPhoneCallback` each create ONE flat Communication (body in the root, no child). Zero children =>
  fails `_has` => never appears in the provider inbox. Live: Catherine Hargrove's BP messages
  (status=in-progress, recipient=Whitman, zero children) are absent; seeded threads appear only because
  they already have reply children.
- Portal side: `useMyMessageThreads` (thread-query.ts) groups by `inResponseTo` (root = no inResponseTo);
  `useMessageThread` fetches replies by `part-of`; `PortalMessagesPage` reads `thread.root.payload` for the
  preview. The reply path / `replyToThread` create children with part-of + inResponseTo.

## GOAL

Every portal-initiated thread is immediately visible in the provider inbox, achieved by giving the thread
root a `part-of` child (a "thread anchor" that mirrors the opening message) so Medplum's `_has` filter is
satisfied. Keep the root carrying the body (portal unchanged) and ensure NO user-visible duplication on
either side. This is the minimal alignment to Medplum's part-of thread model; no header/children migration.

---

## BRIEF MSG3-1 — create a thread-anchor child on compose; exclude it from portal grouping + detail

### FILES
- `src/lib/messaging/compose-message.ts`
- `src/lib/messaging/phone-callback.ts`
- `src/lib/messaging/thread-query.ts`
- `src/lib/messaging/__tests__/` (extend / add)

### CONST
- Define and export `THREAD_ANCHOR_TAG = 'urn:spectricom:thread-anchor'` (in a shared messaging module,
  e.g. compose-message.ts) so both creators and both portal hooks reference the same constant.

### IMPLEMENT
1. `compose-message.ts` `composeNewThread`: KEEP the existing root creation unchanged (status 'in-progress',
   topic, payload=body, sender, recipient, subject, category, urgent extension). AFTER the root is created,
   create a SECOND Communication (the anchor):
   - `status: 'in-progress'`, `partOf: [{ reference: 'Communication/' + root.id }]`, `sender: root.sender`,
     `recipient: root.recipient`, `subject: root.subject`, `category: root.category`,
     `payload: root.payload`, `sent: root.sent`, `meta: { tag: [{ system: THREAD_ANCHOR_TAG, code: 'anchor' }] }`.
   - Do NOT set `inResponseTo` on the anchor.
   - Return the ROOT (unchanged return contract).
2. `phone-callback.ts` `requestPhoneCallback`: same pattern — after creating the callback root, create a
   part-of anchor child mirroring its `payload` + `category`, tagged THREAD_ANCHOR_TAG, NO `inResponseTo`.
   (Escalation/callback extensions stay on the ROOT, as today.)
3. `thread-query.ts`:
   - `useMyMessageThreads`: SKIP any Communication carrying THREAD_ANCHOR_TAG entirely — it must NOT be
     treated as a root (it has no inResponseTo) NOR as a reply. (Prevents a phantom thread.)
   - `useMessageThread`: when building `replies` from part-of children, EXCLUDE any carrying
     THREAD_ANCHOR_TAG (so the portal detail does not double-show the opening message).
   - Leave `useProviderInboxThreads` (dead code) untouched.

### ACCEPTANCE
1. `composeNewThread` creates exactly TWO Communications: the root (with body) and one anchor child whose
   `partOf[0].reference === 'Communication/' + root.id`, carrying THREAD_ANCHOR_TAG and NO `inResponseTo`
   (unit test asserts both resources + tag + part-of + absence of inResponseTo).
2. `requestPhoneCallback` likewise creates a root + a tagged part-of anchor child (test asserts).
3. `useMyMessageThreads` returns exactly ONE thread for a freshly composed message (no phantom thread from
   the anchor), preview body from the root, reply count 0 (test asserts).
4. `useMessageThread` returns the thread with the anchor EXCLUDED from `replies` (test asserts).
5. `npm run build` green; unit/integration tests green.

### OUT OF SCOPE (do NOT implement)
- Migrating to a header+children thread model or wiring the dead `useProviderInboxThreads` inbox.
- Provider-reply-via-Medplum-inbox cross-model nuances (pre-existing).
- The agentic daemon.
- The provider inbox component (`MessagesPage.tsx`) — unchanged.
