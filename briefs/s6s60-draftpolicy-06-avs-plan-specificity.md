# Toni Batch S6S60 — DRAFTPOLICY-06: AVS reflects the note's Plan actions + follow-up specifics

## Repo: clinical-mp
## Batch ID: s6s60-draftpolicy-06-avs-plan-specificity
## Briefs: 1
## Estimated runtime: 15-25m
## Predecessor: clinical-mp main @ eb84a22
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 30
## Severity: P3 (UAT J5 minor — AVS under-specifies: flattens documented med actions + follow-up interval)

## CONTEXT

Authority: `SCA_Draft_Grounding_and_Dependency_Policy_v0-2.md` (§5 contract for `draftAVS`).

Synth UAT J5 PASSED anti-fabrication but flagged a refinement: the AVS narrative characterized
lisinopril as "continue/keep taking" (the note documented **restart-and-intensify after a lapse**) and
gave a generic "schedule a follow-up" (the note documented a **2-week BP recheck**). This is NOT
fabrication — it's the opposite, under-specification: the model leaned on the structured med-rec order
labels (all "Continue" after the J2 reconciliation) over the action + interval documented in the note's
Plan.

Confirmed in code: `serializeAVSInput` (`src/lib/llm/prompt-serializers.ts`, post-DP-2) already places
the signed note as the PRIMARY "Visit documentation (authoritative…)" block, with the structured
medicationRequests / serviceRequests / carePlans as supporting context. The note's Plan and the
structured orders can disagree (note: "restart and intensify"; structured: "continue"), and the model
currently resolves toward the structured label. The fix is a prompt-precedence clarification — the
note's Plan is authoritative for *what the clinician is doing and when they follow up*.

## GOAL

When the note's Plan specifies a medication action (start / restart / increase / intensify / titrate /
hold / stop) or a specific follow-up interval, the AVS reflects that exactly — not a generic "continue"
or "schedule a follow-up" — even when the structured order list only shows current status.

---

## BRIEF DP6-1 — Plan action verbs + follow-up interval take precedence in the AVS

### FILES
- `src/lib/llm/prompt-serializers.ts` (`serializeAVSInput` system prompt)
- `src/lib/llm/prompt-serializers.test.ts` (extend)

### IMPLEMENT
- In `serializeAVSInput`, when `input.signedNote` is present, add to the system prompt a precedence
  clarification (keep all existing anti-fabrication wording from DP-2):
  - "The visit documentation (Plan) is authoritative for medication actions and follow-up timing. If the
    Plan states a specific action — start, restart, increase/intensify, titrate, reduce, hold, or stop a
    medication — state that action; do NOT flatten it to a generic 'continue'. If the Plan states a
    specific follow-up interval (e.g., 'recheck in 2 weeks'), state that interval; do NOT replace it with
    a generic 'schedule a follow-up'. The structured medication/order list reflects current status and
    must NOT override an action documented in the Plan."
- This is additive to the existing grounding/anti-fabrication directive. Do NOT remove the rule that the
  AVS must not introduce content absent from the note + structured data.
- When `signedNote` is absent, the system prompt is unchanged (back-compat).

### ACCEPTANCE
1. With `signedNote` present, the AVS system prompt instructs that the note's Plan action verbs and
   follow-up interval take precedence over generic "continue" / generic follow-up and over the
   structured order labels — test asserts the directive text.
2. The DP-2 anti-fabrication wording ("do NOT introduce … absent from both") remains present — test
   asserts it is still there.
3. With `signedNote` absent, `serializeAVSInput` output is byte-identical to before (test).
4. `npm run build` green; unit tests green (`prompt-serializers.test.ts`).

### OUT OF SCOPE (do NOT implement)
- The chip prose path (DP-5) and `draftSOAP`.
- Any change to how the structured `avsPayload` / `FinalizeAvsSection` deterministic rendering works.
- Re-weighting which structured orders are included — this is a prompt-precedence change only.
