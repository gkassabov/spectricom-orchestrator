# Toni Batch S6S60 — FIX-02: Scribe full-note 413 + silent failure

## Repo: clinical-mp
## Batch ID: s6s60-fix-02-scribe-413
## Briefs: 1
## Estimated runtime: 25-35m
## Predecessor: clinical-mp main @ a617327
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 40
## Severity: P0 (demo-killer)

## CONTEXT

The headline AI Scribe action "Structure from visit notes" (full-note draftSOAP) **fails
silently every time** in synth UAT. Console shows the real cause, reproducibly:

  `Groq API error: 413 ... Request too large for model llama-3.1-8b-instant ...
   Limit 6000, Requested 6665 (rate_limit_exceeded)` thrown in `draftSOAP`.

The physician sees no SOAP draft, no progress meter, no error toast. The per-section "Draft"
buttons (smaller prompts) DO produce real Groq output — so the model/provider are healthy; only
the full-note path is broken.

Two defects:
  (a) **Oversized request.** A short visit note totals ~6,665 tokens once you add the injected
      context + the reserved `max_tokens`. Groq's hard per-request/TPM ceiling for
      `llama-3.1-8b-instant` is 6,000. There is already a capped serializer
      (`buildScribeContext`, `SAFE_INPUT_TOKEN_THRESHOLD = 5000` in `src/lib/llm/scribe-context.ts`)
      and a TPM token-bucket in `groq-provider.ts` — but the token-bucket only smooths the rolling
      TPM; a SINGLE request whose `(estimated input + max_tokens) > 6000` hard-413s regardless.
      So the full-note path is either bypassing `buildScribeContext` or reserving too high a
      `max_tokens` on top of the context.
  (b) **Silent failure.** `useCaptureScribe.ts` (~line 190) `setError(msg)` on catch, but the
      consuming Scribe-notes UI never renders that error — so the failure is invisible with no
      retry.

## GOAL

Keep every full-note `draftSOAP` request under Groq's per-request ceiling, and surface any scribe
failure to the physician with a Retry — never fail blank.

## FILES

- `src/lib/llm/scribe-context.ts` — `buildScribeContext`, caps, `estimateScribeContextTokens`.
- `src/lib/llm/providers/groq-provider.ts` — `draftSOAP` request assembly + `max_tokens`.
- `src/hooks/useCaptureScribe.ts` — already exposes `error`; confirm it propagates.
- The Scribe-notes UI component consuming `useCaptureScribe` (the "Structure from visit notes"
  panel in the encounter note) — render the error + a Retry button + the running meter.

## ACCEPTANCE CRITERIA

1. **No 413 on a normal full note.** A typical multi-problem visit note structures successfully
   on `llama-3.1-8b-instant`; `(estimated input tokens + max_tokens) ≤ ~5,500` for the request
   (≤ 92% of the 6,000 ceiling, matching the existing safety margin).
2. **Full-note path uses the capped serializer.** The full-note `draftSOAP` goes through
   `buildScribeContext` (observation/condition/med/substrate caps applied), not the legacy
   full-history serializer.
3. **Error is visible.** If the scribe call throws (413 or any error), the panel shows a clear
   inline error ("Couldn't generate the note — try again") with a **Retry** button. No blank
   silent failure.
4. **Meter runs and completes** on success; on failure it stops and yields to the error state.
5. **Per-section Draft still works** (no regression).
6. **Unit test** for the token-budget guard: a synthetic over-cap input is trimmed/blocked
   before the request, and `estimateScribeContextTokens(messages) + maxTokens ≤ ceiling`.

## IMPLEMENTATION SKETCH

1. In `groq-provider.ts` `draftSOAP`: compute the input estimate
   (`estimateScribeContextTokens(messages)`) and set
   `max_tokens = min(currentSoapMaxTokens, CEILING_92 - estInput)` where `CEILING_92 = 5500`.
   If `estInput` alone is already near the ceiling, first re-run the context through
   `buildScribeContext` with tighter caps (drop substrate, then trim observations/conditions)
   until `estInput ≤ ~2500`, leaving ~3000 for the completion. (A SOAP note fits comfortably in
   ~2,500-3,000 completion tokens.)
2. Confirm the full-note entry point calls `buildScribeContext` (not the legacy serializer). If
   it doesn't, route it through `buildScribeContext`.
3. In `useCaptureScribe.ts`: ensure `error` is returned and not swallowed by the provider's
   retry wrapper (the 413 should propagate as a thrown error, caught by the hook's `.catch`).
4. In the Scribe-notes UI: bind the hook's `error` to a Mantine `Alert` with a Retry button that
   re-invokes the structure action; show the meter only while `isLoading`.

OPTION (note for George, not in scope unless you say so): bump `VITE_GROQ_MODEL` to a
higher-TPM model (e.g. `llama-3.3-70b-versatile`) — larger ceiling, better SOAP quality, but a
model change. Default approach above keeps the current model and just respects its ceiling.

## OUT OF SCOPE

- Switching the scribe model (config decision — left to George).
- Streaming the SOAP draft / partial rendering.
- Deepgram ambient capture (BAA-gated, D-377).

## DEFINITION OF DONE

- Full-note structure succeeds on `llama-3.1-8b-instant` without 413.
- Any scribe failure shows an inline error + Retry.
- Token-budget unit test passes.
- Commit message: `FIX-02: cap full-note draftSOAP under Groq ceiling + surface scribe errors (S6S60)`.

## §29 / §31

§29 standard.

§31 smoke:
1. Open Hargrove's encounter → Encounter Note → Scribe notes.
2. Paste a multi-problem visit note; click "Structure from visit notes".
3. Expect a SOAP draft to populate, meter runs+completes, no console 413.
4. Force-fail (e.g. temporarily point Groq base to an invalid host) → expect an inline error +
   Retry, NOT a blank panel.
