# Toni Batch S6S60 — DRAFTPOLICY-03: thread sibling sections + transcript into Mode-B redraft

## Repo: clinical-mp
## Batch ID: s6s60-draftpolicy-03-modeb-siblings-transcript
## Briefs: 1
## Estimated runtime: 25-35m
## Predecessor: clinical-mp main @ d33531b
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 40
## Severity: P1 (Mode-B isolation — per-section/per-chip redrafts are chart-only; the per-problem A/P chips came up ungrounded in Eleanor UAT)

## CONTEXT

Authority: `SCA_Draft_Grounding_and_Dependency_Policy_v0-2.md` (§3 Mode B; §5 contract for
`draftProseSection` / `draftChipProse`).

Confirmed in code: the per-section and per-problem-chip "AI draft" buttons (Mode B) each make an
independent call that is grounded in the CHART ONLY — no sibling sections, no transcript:
- `src/hooks/useProseDrafter.ts`: `ProseDrafterContext = { patient, encounter, conditions, medications,
  observations }`. All three drafters (`draftSection`, `draftChips`, `draftSingleChip`) build
  `ProseDraftInput` from that context only.
- `src/lib/llm/types.ts` `ProseDraftInput`: section/patient/encounter/conditions/medications/observations/
  recentEncounterSummaries?/targetSpec? — **no sibling sections, no transcript**.
- `src/lib/llm/prompt-serializers.ts` `serializeProseDraftInput`: system prompt literally says
  "draft … from patient-record context ONLY (no transcript, no voice input)".
- Reason already reaches it via `encounterSummary` (landed DP-1) — only siblings + transcript missing.

The call site ALREADY HOLDS what we need (just doesn't pass it):
- `src/components/encounter-compose/layouts/common/useEncounterCompose.ts` line ~307 calls
  `useProseDrafter({ patient, encounter, conditions, medications, observations })`.
- The same hook exposes a derived `sectionContents: { subjective, objective, assessment, plan }` and
  `state.scribeNotes` (the transcript — `composeState.scribeNotes: string`).

Result (seen in Eleanor UAT): redrafting a per-problem Assessment/Plan chip produces prose blind to the
Subjective/Objective and to the visit transcript. This brief threads both in, so a redrafted section
coheres with the rest of the note and is grounded in what was said.

## GOAL

Mode-B drafts (`draftProseSection` / `draftChipProse`) receive the current sibling sections and the
visit transcript, so a redrafted section/chip is coherent with the note and grounded in the encounter —
not chart-only.

---

## BRIEF DP3-1 — sibling sections + transcript into the Mode-B prose drafter

### FILES
- `src/lib/llm/types.ts` (extend `ProseDraftInput`)
- `src/hooks/useProseDrafter.ts` (extend `ProseDrafterContext`; thread through all 3 drafters)
- `src/components/encounter-compose/layouts/common/useEncounterCompose.ts` (populate the new context fields)
- `src/lib/llm/prompt-serializers.ts` (`serializeProseDraftInput`)
- `src/lib/llm/prompt-serializers.test.ts` (extend)

### IMPLEMENT
- Extend `ProseDraftInput` (optional, strict superset):
  `siblingSections?: { subjective?: string; objective?: string; assessment?: string; plan?: string };`
  `transcript?: string;`
- Extend `ProseDrafterContext`:
  `siblingSections: { subjective: string; objective: string; assessment: string; plan: string };`
  `transcript?: string;`
- In `useProseDrafter`, include `siblingSections: context.siblingSections` and
  `transcript: context.transcript` in the `ProseDraftInput` built by `draftSection`, `draftChips`,
  and `draftSingleChip`. (Pass all sections; the serializer frames target-vs-others.)
- In `useEncounterCompose`, pass `siblingSections: sectionContents` and `transcript: state.scribeNotes`
  into the `useProseDrafter({ ... })` call. (Use the existing `sectionContents` accessor + `state.scribeNotes`.)
- In `serializeProseDraftInput`:
  - When `transcript` is present, emit a "Visit transcript:" grounding block, and **update the system
    prompt** — remove the "patient-record context ONLY (no transcript)" claim; when a transcript is
    present the section must be grounded in it (consistent with the policy locked core).
  - When `siblingSections` is present, emit an "Other sections of this note (for coherence — align with
    these; do not contradict or duplicate verbatim):" block listing the non-empty S/O/A/P.
  - Keep the existing chart blocks (problem list, meds, observations, recent encounters).
  - Omit empty sibling entries / absent transcript. When both absent, output is unchanged (back-compat).

### ACCEPTANCE
1. `ProseDraftInput` and `ProseDrafterContext` carry optional `siblingSections` + `transcript`.
2. All three drafters in `useProseDrafter` pass them through.
3. `useEncounterCompose` populates them from `sectionContents` + `state.scribeNotes`.
4. `serializeProseDraftInput` emits the sibling block and the transcript block when set (test asserts
   the sibling section text and the transcript appear in the assembled prompt); the "no transcript"
   wording is removed from the system prompt.
5. With both absent, `serializeProseDraftInput` is byte-identical to before (explicit test).
6. `npm run build` green; unit tests green.

### OUT OF SCOPE (do NOT implement)
- Mode A one-shot `draftSOAP` (unchanged).
- AVS (DP-2) and the reason-keyed pre-visit fixture.
- Any change to how chips are built or how drafts land in the reducer.
