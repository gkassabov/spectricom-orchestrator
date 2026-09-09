# Toni Batch S6S60 — DRAFTPOLICY-05: ground the per-problem CHIP redraft (draftChipProse)

## Repo: clinical-mp
## Batch ID: s6s60-draftpolicy-05-chipprose-grounding
## Briefs: 1
## Estimated runtime: 20-30m
## Predecessor: clinical-mp main @ 31cc07e
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 35
## Severity: P0 (UAT J6 FAIL — per-problem Assessment chip ignores today's findings AND fabricates family history)

## CONTEXT

Authority: `SCA_Draft_Grounding_and_Dependency_Policy_v0-2.md` (§3 Mode B; §4 G3/G4).

Synth UAT J6 FAILED: redrafting the Hypertension per-problem **Assessment** chip produced generic
textbook prose ("...characterized by systolic pressure greater than 130...") that ignored today's
in-office **BP 152/94** and the documented **lisinopril lapse**, and **invented "family history of
hypertension"** (absent from the note/chart). The Plan chip was better grounded but still said
"continue" (vs documented restart-after-lapse) and "1 week" (note documents 2 weeks).

Root cause (confirmed in code): DP-3 threaded siblings + transcript into `serializeProseDraftInput`,
but the per-problem CHIP path does NOT use that serializer. `draftChipProse`
(`groq-provider.ts` / `ollama-provider.ts`) builds its prompt with `buildChipProseSystemPrompt` +
`buildChipProseUserPrompt` in `src/lib/llm/prompts.ts`, which DP-3 never touched:
- `buildChipProseUserPrompt` emits identity + ACTIVE MEDICATIONS + ACTIVE CONDITIONS + RECENT RENAL
  LABS (renal only) + PROBLEM CHIPS. **No transcript, no Subjective/Objective siblings, no today's
  vitals** (BP is not a renal lab, so it's filtered out).
- `buildChipProseSystemPrompt` (assessment) asks for "clinical presentation, severity, diagnostic
  reasoning, differential considerations" + diagnostic vocabulary — it INVITES generic textbook prose
  — and has NO anti-fabrication rule.

IMPORTANT — the data is already present: DP-3 added `siblingSections` + `transcript` to
`ProseDraftInput`, and `useProseDrafter` (`draftChips` / `draftSingleChip`) already passes them on the
`input` handed to `draftChipProse`. So `buildChipProseUserPrompt(input, chips)` ALREADY RECEIVES them
on `input` — it just doesn't read them. This brief is a focused `prompts.ts` change only.

## GOAL

The per-problem Assessment/Plan chip redraft grounds in TODAY's visit (transcript + Subjective/
Objective findings provided on `input`), and never writes generic textbook prose or invents
history/risk factors absent from the inputs — while preserving the existing med-rec + renal awareness.

---

## BRIEF DP5-1 — read siblings + transcript in the chip prompt; harden the chip system prompt

### FILES
- `src/lib/llm/prompts.ts` (`buildChipProseUserPrompt` + `buildChipProseSystemPrompt`)
- `src/lib/llm/prompts.test.ts` (extend)

### IMPLEMENT
- `buildChipProseUserPrompt(input, chips)` — emit the visit grounding that is already on `input`:
  - When `input.transcript` is a non-blank string, add a `VISIT TRANSCRIPT:\n<transcript>` section.
  - When `input.siblingSections` is present, add a `THIS VISIT'S NOTE (ground the assessment/plan in
    these — today's findings):` section listing the non-empty `Subjective:` and `Objective:` (and
    `Assessment:`/`Plan:` if useful) — the Objective carries today's vitals (e.g., BP 152/94).
  - Place this grounding PROMINENTLY (before the PROBLEM CHIPS list). Omit any empty piece; when both
    are absent the prompt is unchanged (back-compat).
- `buildChipProseSystemPrompt('assessment')` — replace the generic framing:
  - Instruct: "Ground each chip's assessment in TODAY's visit — the transcript and the Subjective/
    Objective findings in the user prompt (today's vitals, what the patient reported, medication
    changes this visit). Reference today's specific findings (e.g., the in-office blood pressure, a
    lapsed/restarted medication). Do NOT write a generic textbook description of the condition, and do
    NOT list differential diagnoses that were not raised in this visit."
- Add a G3 ANTI-FABRICATION rule to BOTH 'assessment' and 'plan' system prompts:
  - "Do NOT invent history (family history, social history), risk factors, symptoms, exam findings, or
    any content not present in the transcript, the visit note, the active medications/conditions, or
    the labs provided. If there is nothing visit-specific to say for a chip, write a brief factual line
    — not generic filler."
- PRESERVE the existing 'plan' MEDICATION RECONCILIATION and RENAL AWARENESS directives verbatim.

### ACCEPTANCE
1. `buildChipProseUserPrompt` emits the `VISIT TRANSCRIPT` section and the `Subjective`/`Objective`
   siblings when present on `input` — tests assert the transcript text and the Objective vitals string
   appear in the prompt.
2. `buildChipProseSystemPrompt('assessment')` instructs grounding in today's visit findings, forbids
   generic-textbook condition prose, and forbids inventing family/social history — test asserts.
3. `buildChipProseSystemPrompt('plan')` carries the same anti-fabrication rule AND still contains the
   existing MEDICATION RECONCILIATION + RENAL AWARENESS directives — test asserts both remain.
4. With `input.transcript` and `input.siblingSections` absent, `buildChipProseUserPrompt` is unchanged
   (back-compat test).
5. `npm run build` green; unit tests green (`prompts.test.ts`).

### OUT OF SCOPE (do NOT implement)
- `serializeProseDraftInput` (the section path — already handled in DP-3).
- `ProseDraftInput` / `useProseDrafter` (DP-3 already wired siblings + transcript onto the chip input).
- `draftSOAP` (Mode A) and the AVS.
