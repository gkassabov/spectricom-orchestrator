# Toni Batch S6S60 — DRAFTPOLICY-01: thread visit reason into encounterSummary

## Repo: clinical-mp
## Batch ID: s6s60-draftpolicy-01-encountersummary-reason
## Briefs: 1
## Estimated runtime: 15-25m
## Predecessor: clinical-mp main @ 1f4175b
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 30
## Severity: P1 (foundation for the Draft Grounding & Dependency Policy; grounds five AI-draft generators at one point)

## CONTEXT

Authority: `SCA_Draft_Grounding_and_Dependency_Policy_v0-2.md` (OneDrive canon). This is the first,
highest-leverage brief implementing it — the "shared chokepoint" fix.

Confirmed in code: every AI-draft generator builds its prompt through one helper,
`encounterSummary()` in `src/lib/llm/scribe-context.ts`, which today emits ONLY
`Encounter: status=<...>, class=<...>`. The visit reason (`encounter.reasonCode`) is therefore
dropped for ALL five generators that call it via the serializers in
`src/lib/llm/prompt-serializers.ts`:
- `serializeSOAPInput` / `buildScribeContext` (draftSOAP)
- `serializeSuggestionInput` (generateSuggestions)
- `serializeAVSInput` (draftAVS)
- `serializeProseDraftInput` (draftProseSection / draftChipProse)
- `serializeAskInput` (ask)

Per the policy, Reason must reach the generators. Threading it through this ONE helper grounds all
five at once. This brief does ONLY that — no section chaining, no AVS rewire (those are later briefs).

NOTE (scope boundary): this brief makes the generators SEE the reason when `reasonCode` is present.
Populating `reasonCode` on encounters (from scheduling / the inbound message) is a separate concern
and is OUT OF SCOPE here. When `reasonCode` is absent, output must be unchanged (no placeholder).

## GOAL

`encounterSummary()` includes the visit reason when present, so it propagates to all five
prompt serializers, with zero change when the reason is absent and full back-compat for status/class.

---

## BRIEF DP-1 — emit visit reason from encounterSummary

### FILES
- `src/lib/llm/scribe-context.ts` (the `encounterSummary` function)
- `src/lib/llm/scribe-context.test.ts` (extend)
- `src/lib/llm/prompt-serializers.test.ts` (extend — assert reason propagates through the serializers)

### IMPLEMENT
- In `encounterSummary(encounter)`, after the existing `status`/`class` composition, read
  `encounter.reasonCode?.[0]?.text?.trim()`. If present and non-empty, append a clearly-labelled
  clause to the returned summary, e.g. `Encounter: status=<s>, class=<c>, reason="<text>"`
  (keep it on the same single line the callers already consume; do not change the function signature
  or return type).
- If `reasonCode` is missing/empty, return EXACTLY today's output (no "reason=unknown", no trailing
  separator). This is a strict superset — additive only.
- Do not touch the per-generator serializers' other logic; they already call `encounterSummary` and
  will inherit the reason automatically.

### ACCEPTANCE
1. `encounterSummary` for an encounter WITH `reasonCode[0].text` includes the reason text, labelled.
2. `encounterSummary` for an encounter WITHOUT `reasonCode` returns byte-identical output to before
   (covered by an explicit test asserting the unchanged string).
3. The existing status/class content is preserved in both cases.
4. A serializer-level test confirms the reason line is present in the assembled prompt for at least
   `serializeSOAPInput` and `serializeAVSInput` when `reasonCode` is set.
5. `npm run build` green; unit tests green (`scribe-context.test.ts`, `prompt-serializers.test.ts`).

### OUT OF SCOPE (do NOT implement here)
- Populating `reasonCode` on encounters.
- Section→section chaining (Mode B siblings).
- AVS consuming the signed note.
- Any new policy object / admin overlay / provenance stamping.
