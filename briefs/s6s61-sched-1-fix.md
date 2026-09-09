## Repo: clinical-mp
## Batch ID: s6s61-sched-1-fix
## Briefs: 1 (SCHED-1-FIX)
## Predecessor: d033008 (SCHED-1)
## Fire mechanism: orchestrator queue --approve --skip-sit
## TONI_TIMEOUT_MIN: 20
## Severity: bugfix

## CONTEXT
Two defects found in the live patient-first test (SCHED-1, d033008):

(1) PATIENT NEVER SEES THE PROPOSAL. `draftSchedule` (src/lib/agentic-runtime/tools.ts) sends the proposed-times message via `composeNewThread`, which opens a BRAND-NEW thread ("Let's get you scheduled - <visit>"). The patient asked "can I get in to be seen?" in their EXISTING thread; the answer is orphaned in a separate conversation they aren't looking at. The daemon already passes `threadRef = 'Communication/<inbound root id>'` into draftSchedule (agentic-daemon.ts line ~214), so the proposal MUST reply into that thread instead. `replyToThread` (src/lib/messaging/compose-message.ts) already sets partOf + inResponseTo and routes the reply back to the thread's original sender (the patient) -- exactly right.

(2) DUPLICATE MESSAGE in the provider inbox thread view. `composeNewThread` creates the root Communication PLUS a second `THREAD_ANCHOR_TAG`-tagged Communication that COPIES the payload. `src/components/inbox/InboxItemDetail.tsx` renders BOTH as conversation bubbles, so every thread shows its message twice. The patient portal does not double-render; only the provider inbox detail does. Fix = exclude anchor-tagged Communications from the rendered bubble list.

## GOAL
The agent's proposed times land as a reply INSIDE the patient's existing thread (patient sees it where they asked), and each message renders once in the provider inbox.

---

### BRIEF SCHED-1-FIX -- reply-into-thread + anchor dedupe

FILES:
- EDIT src/lib/messaging/compose-message.ts (ReplyOptions + replyToThread)
- EDIT src/lib/agentic-runtime/tools.ts (draftSchedule proposal send)
- EDIT src/components/inbox/InboxItemDetail.tsx (filter anchor from thread render)

IMPLEMENT:
1. compose-message.ts: add optional `extensions?: Extension[]` to the `ReplyOptions` interface. In `replyToThread`, after building `reply` and BEFORE createResource, if `opts.extensions?.length` then `reply.extension = [...(reply.extension ?? []), ...opts.extensions];`. (Extension is already imported from SCHED-1B.)
2. tools.ts `draftSchedule`: replace the proposal-send block (currently `composeNewThread(...)`) with thread-aware logic, keeping `proposalBody` as-is:
   - If `p.threadRef` is set:
       `const rootId = p.threadRef.replace('Communication/', '');`
       `const comm = await replyToThread(p.medplum, rootId, { sender: { reference: providerRef.reference, display: p.providerName }, body: proposalBody, extensions: [{ url: PROPOSED_SLOTS_EXTENSION_URL, valueString: JSON.stringify(slots) }] });`
   - Else: keep the existing `composeNewThread(...)` call (new-thread fallback) unchanged.
   - Either branch: capture the created id and set `proposalThreadRef: 'Communication/' + comm.id` on the draft (as today).
   - Add `replyToThread` to the import from '../messaging/compose-message'.
3. InboxItemDetail.tsx: where the thread's messages are assembled into the list of conversation bubbles, filter OUT any Communication whose `meta.tag` includes an entry with system === `THREAD_ANCHOR_TAG` (import `THREAD_ANCHOR_TAG` from '../../lib/messaging/compose-message' -- adjust relative path as needed). Do NOT change which Communication is treated as the thread root; only suppress anchor-tagged entries from rendering.

ACCEPTANCE:
- `npx tsc --noEmit && npm run build` green.
- With `threadRef` present, draftSchedule's proposal is a REPLY (partOf + inResponseTo = the inbound root; recipient = the inbound thread's original sender) carrying the `proposed-slots` extension -- and NO new thread or anchor Communication is created for the proposal.
- A thread created via composeNewThread (root + anchor) now renders its message exactly ONCE in the provider inbox detail.

OUT OF SCOPE: the Tasks-in-Inbox / Conversations IA rework; SCHED-2 (patient pick -> book).
