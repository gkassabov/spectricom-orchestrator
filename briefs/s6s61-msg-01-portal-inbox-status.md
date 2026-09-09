# Toni Batch S6S61 — MSG-01: portal patient messages never reach the provider inbox (status=preparation)

## Repo: clinical-mp
## Batch ID: s6s61-msg-01-portal-inbox-status
## Briefs: 1
## Estimated runtime: 12-20m
## Predecessor: clinical-mp main @ 01bd0c1
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 20
## Severity: P1 (blocks the concierge E2E at step 1->2: portal messages + phone-callback requests are invisible to the provider inbox)

## CONTEXT

Confirmed in code AND in live Medplum data (:8103):
- Provider inbox `src/pages/messages/MessagesPage.tsx` renders Medplum `ThreadInbox` with exactly two
  status buckets: `inProgressUri` = `status=in-progress` and `completedUri` = `status=completed`. A
  Communication whose `status` is NEITHER shows in NEITHER tab.
- `src/lib/messaging/compose-message.ts` `composeNewThread` creates the root Communication with
  `status: 'preparation'`.
- `src/lib/messaging/phone-callback.ts` `requestPhoneCallback` also creates with `status: 'preparation'`.
- Live: Catherine Hargrove's two portal-sent threads ("BP High", "BP running high / lisinopril refill")
  are `status=preparation` and absent from the provider inbox; the seeded threads that DO appear
  (UAT J9, Symptom follow-up, Question about lab results) are `status=in-progress`.
- Thread-state (daemon idempotency) is an INDEPENDENT axis: `src/lib/agentic-runtime/thread-state.ts`
  tracks progress via `meta.tag` (`urn:spectricom:agentic-thread-state`); an untagged Communication is
  treated as 'new'. Changing the FHIR `status` does NOT affect the daemon's "new"-thread detection.

## GOAL

Portal-initiated patient Communications (messages + phone-callback requests) are created with
`status: 'in-progress'` so they land in the provider inbox's In Progress tab, matching seeded threads.
No change to daemon thread-state behavior, category, recipient, or extensions.

---

## BRIEF MSG1-1 — create portal-initiated Communications as in-progress

### FILES
- `src/lib/messaging/compose-message.ts`
- `src/lib/messaging/phone-callback.ts`
- `src/lib/messaging/__tests__/` (extend the compose-message + phone-callback tests; add if absent)

### IMPLEMENT
- In `composeNewThread`, change the root Communication `status` from `'preparation'` to `'in-progress'`.
  Leave the reply path `replyToThread` unchanged (replies are already `'completed'`).
- In `requestPhoneCallback`, change the Communication `status` from `'preparation'` to `'in-progress'`.
- Do NOT change `category`, `recipient`, `subject`, `sender`, `payload`, `extension`, or any other field.

### ACCEPTANCE
1. `composeNewThread` returns a Communication with `status === 'in-progress'` (unit test asserts).
2. `requestPhoneCallback` returns a Communication with `status === 'in-progress'` (unit test asserts).
3. Grep shows no portal-side creator emitting `status: 'preparation'`.
4. `npm run build` green; unit tests green.

### OUT OF SCOPE (do NOT implement)
- The provider inbox query/tabs (`MessagesPage.tsx`) — unchanged.
- thread-state tags / the agentic daemon.
- Reply status (`replyToThread`) — unchanged.
