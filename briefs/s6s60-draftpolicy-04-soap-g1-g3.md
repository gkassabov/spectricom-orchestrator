# Toni Batch S6S60 — DRAFTPOLICY-04: G1/G3 locked-core into draftSOAP

## Repo: clinical-mp
## Batch ID: s6s60-draftpolicy-04-soap-g1-g3
## Briefs: 1
## Estimated runtime: 15-25m
## Predecessor: clinical-mp main @ ebcfe40
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 30
## Severity: P0 (direct fix for the original Santos fabrication — Subjective invented from an empty transcript)

## CONTEXT

Authority: `SCA_Draft_Grounding_and_Dependency_Policy_v0-2.md` (§4 locked core G1 + G3).

This is the hardening at the SOURCE of the failure that started this work: with no transcript, the
one-shot `draftSOAP` fabricated a Subjective ("fatigue 7/10") from the chart alone.

Confirmed in code (`src/lib/llm/scribe-context.ts`):
- `SOAP_SYSTEM_PROMPT` has a RECONCILIATION DIRECTIVE that guards numeric VALUES (G2) and age (G5):
  "DO NOT invent VALUES absent from both the transcript and the structured record…". It does NOT
  forbid inventing the subjective NARRATIVE, and has NO rule that the Subjective must be empty when
  there is no transcript.
- `buildScribeContext` includes a "Voice transcript:\n…" block ONLY when `input.voiceTranscript` is
  present; when it is ABSENT there is no transcript block and no explicit marker — the model is simply
  told "Generate the SOAP note draft.", so it fills the Subjective from the chart (the bug).

This brief adds the two missing locked-core rules to the prompt and makes the absence of a transcript
explicit, so the Subjective is grounded in the transcript or left empty — never invented.

## GOAL

`draftSOAP` produces an EMPTY Subjective when no transcript is present, and never invents subjective/
narrative content absent from the transcript — while preserving the existing G2 (values) and G5 (age)
directives and the JSON output schema.

---

## BRIEF DP4-1 — add G1 (empty-when-no-transcript) + G3 (no-invented-narrative) to the SOAP prompt

### FILES
- `src/lib/llm/scribe-context.ts` (`SOAP_SYSTEM_PROMPT` + `buildScribeContext`)
- `src/lib/llm/scribe-context.test.ts` (extend)

### IMPLEMENT
- Augment `SOAP_SYSTEM_PROMPT` (append to the existing directive block — do NOT remove G2/G5):
  - **G1 (empty when no source):** "If NO voice transcript is provided in the context, the Subjective
    section MUST be empty — return an empty subjective array. Do not generate a chief complaint, HPI,
    or review of systems from the chart alone."
  - **G3 (no invented narrative):** "Do NOT invent symptoms, patient complaints, history, or any
    subjective/narrative content that is not stated in the transcript. The chart (conditions,
    medications, observations) is the patient's standing record for reference — it is NOT a record of
    what the patient reported at THIS visit. When the transcript is silent on something, omit it
    rather than inferring it."
- In `buildScribeContext`, when `input.voiceTranscript` is absent or blank, push an explicit marker
  into the user-message parts (before the final "Generate the SOAP note draft."), e.g.:
  "No voice transcript was captured for this encounter." — so the model sees the absence and G1 applies.
  Keep the existing "Voice transcript:\n…" block unchanged when a transcript is present.
- Do NOT change the SOAP JSON schema, the section object shape, or the downstream parsing. An empty
  subjective array must remain valid output (it already is — sections are arrays).

### ACCEPTANCE
1. `SOAP_SYSTEM_PROMPT` contains both the G1 (empty-Subjective-when-no-transcript) and G3
   (no-invented-narrative) directives — tests assert the directive text is present.
2. `buildScribeContext` with NO `voiceTranscript` includes the explicit "no voice transcript" marker in
   the assembled user message (test asserts).
3. `buildScribeContext` WITH a `voiceTranscript` still includes the transcript block and NOT the marker
   (test asserts).
4. The existing G2 (values-authoritative) and G5 (age-given) directives remain present (test asserts).
5. `npm run build` green; unit tests green (`scribe-context.test.ts`).

### OUT OF SCOPE (do NOT implement)
- Mode-B prose drafter (DP-3).
- The SOAP JSON schema / parser / section shape.
- The compiled policy object, editable overlay, provenance stamping (later phase).
