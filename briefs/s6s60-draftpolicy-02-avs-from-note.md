# Toni Batch S6S60 — DRAFTPOLICY-02: ground the LLM AVS in the signed note (AVS-FAB-01)

## Repo: clinical-mp
## Batch ID: s6s60-draftpolicy-02-avs-from-note
## Briefs: 1
## Estimated runtime: 20-30m
## Predecessor: clinical-mp main @ 23dcf6c
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 35
## Severity: P1 (AVS-FAB-01 root — the LLM AVS narrative is not grounded in what was documented this visit)

## CONTEXT

Authority: `SCA_Draft_Grounding_and_Dependency_Policy_v0-2.md` (§3 dependency graph; §5 contract for
`draftAVS`; canon decision: "AVS ← signed note").

Confirmed in code:
- `AVSDraftInput` (`src/lib/llm/types.ts`) carries conditions/medicationRequests/serviceRequests/
  carePlans/tasks/observations/allergies/addendumHint — but **NO field for the signed note (S/O/A/P)**.
- `serializeAVSInput` (`src/lib/llm/prompt-serializers.ts`) builds the AVS prompt from those structured
  resources only. So the LLM `draftAVS` narrative is grounded in the CHART, not in what the provider
  actually documented this visit — it can drift / fabricate relative to the note (AVS-FAB-01).
- The signed note IS available where the AVS input is assembled: `src/pages/patient/encounter/FinalizePage.tsx`,
  the `avsInput` useMemo. `composeState` (from `buildFinalizeInput`) exposes:
  - `composeState.subjective: string`, `composeState.objective: string`
  - `composeState.assessmentNotes: string` + `composeState.assessmentProblems[]` (`.text`, `.assessmentProse`, `.icdCode`)
  - `composeState.planNotes: string` + `composeState.structuredPlanItems[]` (`.details`, `.planType`)
  - HTML/private-span stripping helpers already in-file: `stripPrivateSpans`, `htmlHasVisibleText`.
- Visit reason already reaches the AVS via `encounterSummary` (landed in DP-1, commit 23dcf6c) — no
  reason work needed here.

This brief grounds the LLM AVS narrative in the signed note, primary, with the structured resources as
supporting. It does NOT touch the deterministic `avsPayload` / `FinalizeAvsSection` grounded rendering.

## GOAL

`draftAVS` receives the signed note (S/O/A/P) and treats it as the authoritative basis for the summary,
so the AVS reflects what was documented this visit — closing AVS-FAB-01.

---

## BRIEF DP2-1 — add signed note to AVSDraftInput, populate it, ground the prompt on it

### FILES
- `src/lib/llm/types.ts` (extend `AVSDraftInput`)
- `src/lib/llm/prompt-serializers.ts` (`serializeAVSInput`)
- `src/pages/patient/encounter/FinalizePage.tsx` (the `avsInput` useMemo)
- `src/lib/llm/prompt-serializers.test.ts` (extend)

### IMPLEMENT
- Add an OPTIONAL field to `AVSDraftInput`:
  `signedNote?: { subjective?: string; objective?: string; assessment?: string; plan?: string }`.
  Optional = strict superset; existing callers/tests unaffected.
- In `FinalizePage.tsx` `avsInput` useMemo, build `signedNote` from `composeState`:
  - `subjective`: `composeState.subjective`
  - `objective`: `composeState.objective`
  - `assessment`: `composeState.assessmentNotes` joined with the per-problem
    `assessmentProblems` text/prose (use the existing strip-to-text helpers; problems already carry
    `.text` and `.assessmentProse`).
  - `plan`: `composeState.planNotes` joined with `structuredPlanItems[].details`.
  - Strip HTML/private spans to plain text (reuse `stripPrivateSpans`); OMIT any section that is empty
    after stripping (do not emit empty keys). Add `composeState` to the useMemo dependency list.
- In `serializeAVSInput`, when `signedNote` is present, emit it as the FIRST/PRIMARY grounding block,
  clearly labelled as authoritative for this visit, e.g.:
  `Visit documentation (authoritative — base the summary on what was documented this visit):`
  followed by the non-empty `Subjective:/Objective:/Assessment:/Plan:` lines. Keep the existing
  structured blocks (conditions/meds/orders/careplans/tasks/obs/allergies) as SUPPORTING context AFTER it.
- Tighten the AVS system prompt grounding so the summary is built from the note + structured data and
  does NOT introduce clinical content absent from both (consistent with the policy locked core G3/G4).
  Do not invent; if a needed detail is absent, omit it rather than fabricate.
- When `signedNote` is absent, `serializeAVSInput` output is unchanged (back-compat).

### ACCEPTANCE
1. `AVSDraftInput` carries optional `signedNote` (S/O/A/P).
2. `FinalizePage` populates `signedNote` from `composeState` (subjective/objective/assessmentNotes+problems/
   planNotes+items), plain-text (HTML + private spans stripped), empty sections omitted.
3. `serializeAVSInput` places the note as the primary grounding block ahead of the structured resources.
   A test asserts the Subjective/Assessment/Plan text appears in the assembled AVS prompt when
   `signedNote` is set.
4. With `signedNote` absent, `serializeAVSInput` produces byte-identical output to before (explicit test).
5. `npm run build` green; unit tests green (`prompt-serializers.test.ts`).

### OUT OF SCOPE (do NOT implement)
- The deterministic `avsPayload` / `FinalizeAvsSection` grounded rendering (separate surface; unchanged).
- Section→section (Mode B) chaining.
- Any change to `draftAVS` provider implementations beyond consuming the new prompt block.
