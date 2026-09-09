# Toni Batch S6S60 — AVS-CACHE-01: invalidate the cached AVS when the note changes

## Repo: clinical-mp
## Batch ID: s6s60-avs-cache-invalidate
## Briefs: 1
## Estimated runtime: 20-30m
## Predecessor: clinical-mp main @ ffeb242
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 35
## Severity: P2 (stale AVS shows on Finalize re-entry after the note changed; flagged in UAT J5)

## CONTEXT

`FinalizePage` (`src/pages/patient/encounter/FinalizePage.tsx`) persists the AVS draft to localStorage
per-encounter via `saveFinalizeDraft` (`src/lib/clinical/finalize-draft-storage.ts`,
`FinalizeDraftState`) and PREFERS the saved draft over a fresh generation on re-entry:
`const [avsDraft, setAvsDraft] = useState(draftFromLocalStorage?.avs ?? null)` and the fresh
`avsText` is only applied when `avsDraft === null`. So if the note's Plan/content changes after an AVS
was generated, re-opening Finalize shows the STALE AVS until the user clicks Regenerate (which does
`setAvsDraft(null); regenerateAvs()`).

This was seen in UAT J5: the pre-regenerate AVS still read lisinopril "— continued" after the note
documented a restart. Fix: fingerprint the note content that grounds the AVS, store it with the draft,
and auto-regenerate when the current note no longer matches the cached fingerprint.

## GOAL

On entry to Finalize, a cached AVS is shown only if it was generated against the CURRENT note; if the
note changed (or the draft predates this feature), the AVS regenerates automatically. An unchanged note
preserves the cached AVS (including any manual edits) — no needless regeneration.

---

## BRIEF AVSCACHE-1 — note fingerprint + stale-AVS auto-regenerate

### FILES
- `src/lib/clinical/finalize-draft-storage.ts` (extend `FinalizeDraftState`)
- `src/pages/patient/encounter/FinalizePage.tsx` (compute fingerprint; invalidate + regenerate stale AVS; save fingerprint)
- `src/lib/clinical/finalize-draft-storage.test.ts` and/or a FinalizePage-level test (extend/add)

### IMPLEMENT
- Add optional `noteFingerprint?: string` to `FinalizeDraftState`. `saveFinalizeDraft` persists it as
  given; `loadFinalizeDraft` returns it. Optional = back-compatible with existing stored drafts.
- Add a small deterministic fingerprint helper (pure function, no crypto dependency — e.g. a stable
  base-36 hash over a normalized string). Compute it from the SAME content that grounds the AVS: the
  `avsInput.signedNote` S/O/A/P strings (subjective, objective, assessment, plan), normalized
  (trim/whitespace-collapse) and concatenated in fixed order. Empty/undefined sections contribute a
  fixed empty token so the hash is stable.
- In `FinalizePage`:
  - Derive `currentNoteFingerprint` (memoized) from `avsInput?.signedNote` (null/empty → a fixed
    sentinel).
  - On entry, when a cached draft has a non-null `avs` AND (`noteFingerprint` is absent OR ≠
    `currentNoteFingerprint`): treat the cached AVS as stale — do NOT seed `avsDraft` from it; instead
    run the existing regenerate path once (`setAvsDraft(null)` + `regenerateAvs()`), exactly as the
    manual Refresh does. Use a ref/guard so this fires at most once per stale-detection and never loops
    (the regenerate → new `avsText` → `setAvsDraft` → save-with-new-fingerprint cycle must settle).
  - When the cached `noteFingerprint` matches `currentNoteFingerprint`, keep current behavior (seed
    `avsDraft` from the cached AVS — preserves manual edits).
  - Persist `noteFingerprint: currentNoteFingerprint` in every `saveFinalizeDraft` call alongside `avs`.
- Do not change the AVS prompt, grounding, or the deterministic `avsPayload`.

### ACCEPTANCE
1. `FinalizeDraftState` carries optional `noteFingerprint`; save/load round-trip it.
2. Cached AVS with a fingerprint ≠ the current note's fingerprint is discarded and regenerated on entry
   (stale AVS is not displayed) — covered by a test.
3. Cached AVS whose fingerprint matches the current note is preserved without regeneration — test.
4. A stored draft with no `noteFingerprint` (pre-existing) is treated as stale and regenerated — test.
5. No infinite regeneration loop (guarded); build + unit green.

### OUT OF SCOPE (do NOT implement)
- AVS prompt/grounding changes (DP-2 / DP-6 already done).
- The deterministic `avsPayload` / `FinalizeAvsSection` rendering.
- Persisting a separate "edited vs generated" AVS copy — a note change regenerates regardless (accepted).
