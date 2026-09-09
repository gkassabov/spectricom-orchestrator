# Toni Batch S6S61 — MSG-04: daemon double-triages — restrict to thread roots (skip anchors + replies)

## Repo: clinical-mp
## Batch ID: s6s61-msg-04-daemon-anchor-guard
## Briefs: 1
## Estimated runtime: 12-20m
## Predecessor: clinical-mp main @ 1c6c166
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 20
## Severity: P1 (the daemon would create DUPLICATE escalations/drafts: it processes both the thread root AND the MSG-03 anchor child as separate "new" patient messages)

## CONTEXT

Confirmed in code:
- `src/daemon/agentic-daemon.ts` `runCycle` Phase A:
  `comms = searchResources('Communication', { _count:50, _sort:-sent })`;
  `patientMsgs = comms.filter(c => c.sender?.reference?.startsWith('Patient/'))`;
  `open = filterOpenThreads(patientMsgs).filter(c => getThreadState(c) === 'new')`.
  It triages EVERY patient-sender Communication in 'new' thread-state, with NO part-of/root distinction.
- MSG-03 (HEAD 1c6c166) now creates, for each portal message, a `THREAD_ANCHOR_TAG`-tagged CHILD
  Communication: `partOf=[root]`, `sender=root.sender` (Patient), no inResponseTo, thread-state 'new'.
  So the daemon processes BOTH the root and the anchor => triages the same message twice (duplicate
  escalation/draft for one concern).
- `THREAD_ANCHOR_TAG` is exported from `src/lib/messaging/compose-message.ts`; the daemon does not use it.
- Related: in-thread patient REPLIES are also children (partOf set, sender Patient) and would likewise be
  mis-triaged as new threads. Restricting Phase A to thread ROOTS fixes both.

## GOAL

The daemon triages only NEW thread ROOTS — Communications with no `partOf` — which excludes the MSG-03
anchor children and any in-thread patient replies. One inbound message => exactly one triage.

---

## BRIEF MSG4-1 — restrict daemon Phase A to thread roots

### FILES
- `src/daemon/agentic-daemon.ts`
- `src/lib/agentic-runtime/__tests__/` (add a small filter test if the harness allows)

### IMPLEMENT
- In `runCycle` Phase A, after computing `patientMsgs`, keep only thread ROOTS — exclude any Communication
  with a non-empty `partOf`:
  `const roots = patientMsgs.filter((c) => !(c.partOf && c.partOf.length));`
  then apply the existing open/new filters to `roots`.
- Defensively also exclude any Communication carrying `THREAD_ANCHOR_TAG`
  (import `THREAD_ANCHOR_TAG` from `../lib/messaging/compose-message`), in case an anchor ever lacks partOf.
- Keep the existing `sender` = Patient and `getThreadState(c) === 'new'` filters unchanged.

### ACCEPTANCE
1. The daemon's Phase A candidate set excludes Communications with a non-empty `partOf` AND any
   `THREAD_ANCHOR_TAG`-tagged Communication.
2. A freshly composed portal message (root + anchor) yields exactly ONE triage candidate — the root
   (unit test asserts).
3. `npm run build` green; tests green.

### OUT OF SCOPE (do NOT implement)
- Event/Bot trigger; poll cadence; the always-on service (set up outside the repo).
- Any change to escalate / draftSchedule / booking / Michelle.
