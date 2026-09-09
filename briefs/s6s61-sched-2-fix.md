## Repo: clinical-mp
## Batch ID: s6s61-sched-2-fix
## Briefs: 1 (SCHED-2-FIX)
## Predecessor: bd548bf (SCHED-2)
## Fire mechanism: orchestrator queue --approve --skip-sit
## TONI_TIMEOUT_MIN: 20
## Severity: bugfix

## CONTEXT
Live defect: after the provider approves a patient-selected schedule draft, the appointment IS booked correctly (verified: the placeholder Appointment flips to status 'booked' at the patient-selected slot, the draft Task completes with the agentic-booked tag) — BUT the calendar still renders it as a faded "Hold".

Root cause: `bookScheduleDraft` (src/lib/agentic-drafts/book-schedule.ts), in the placeholder-promotion branch, sets status 'booked' + start/end but LEAVES the `urn:spectricom:agent-placeholder` meta.tag on the appointment AND leaves description "Hold: <visit>". The SCHED-1 calendar render rule fades any appointment whose status==='pending' OR whose meta.tag includes AGENT_PLACEHOLDER_TAG_SYSTEM. So a booked-but-still-tagged appointment renders faded. Two fixes: (1) strip the placeholder tag + fix the description when booking; (2) make the faded "Hold" styling key off status==='pending' ONLY.

## GOAL
An approved appointment renders as a normal solid booked appointment; only true 'pending' holds render faded.

---

### BRIEF SCHED-2-FIX -- clear the hold on booking + fade by status only

FILES:
- EDIT src/lib/agentic-drafts/book-schedule.ts
- EDIT the calendar appointment renderer that SCHED-1 changed (src/pages/schedule/ — SchedulePage.tsx and/or the appointment block/cell component; find the existing branch that fades pending/agent-placeholder appointments)

IMPLEMENT:
1. book-schedule.ts: in the `draft.placeholderAppointmentRef && draft.patientSelectedSlot` promotion branch, when updating the Appointment to booked, ALSO:
   - remove the agent-placeholder tag: set `meta.tag` to the existing tags filtered to EXCLUDE any entry with system === AGENT_PLACEHOLDER_TAG_SYSTEM (import it from '../scheduling/propose-slots'). Preserve any other tags.
   - set `description` to `draft.title` (e.g. "Schedule: Follow-up") instead of the "Hold: ..." text.
   Keep everything else (status 'booked', start/end = patientSelectedSlot, participants 'accepted', Encounter, confirmation reply) as is.
2. Calendar renderer: change the tentative/faded "Hold" condition so it applies ONLY when `appointment.status === 'pending'`. REMOVE the "|| meta.tag includes AGENT_PLACEHOLDER_TAG_SYSTEM" part of the condition. A booked appointment must always render solid/normal (no opacity reduction, no dashed border, no "Hold" badge), even if it still carries a stale tag.

ACCEPTANCE:
- `npx tsc --noEmit && npm run build` green.
- Approving a patient-selected schedule draft yields a booked Appointment with NO agent-placeholder tag and a non-"Hold" description, rendered as a normal solid appointment on the calendar.
- A still-'pending' placeholder continues to render faded with the "Hold" badge.

OUT OF SCOPE: the Conversations/Tasks IA rework; sweeping legacy/test drafts.
