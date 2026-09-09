# Toni Batch S6S60 — FIX-05: Labs triage surface (flags + live indicator)

## Repo: clinical-mp
## Batch ID: s6s60-fix-05-labs-triage
## Briefs: 1
## Estimated runtime: 30-40m
## Predecessor: clinical-mp main @ a617327
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 45
## Severity: P2

## CONTEXT

Synth UAT (J-D, Hargrove) found the labs INTELLIGENCE is demo-grade (trend narrative flags A1c
6.9→7.4 "WORSENING / above reference range"; scorecard shows "HbA1c 7.4% — OUTSIDE REFERENCE
RANGE"), but the labs TRIAGE surface is weak and self-contradicting:

  - Home "New labs to review" shows **"All clear (0)" and is inert** even though an out-of-range
    A1c is outstanding — because `useHomeInboxLabs` counts only `status=final` DiagnosticReports
    and the abnormal A1c is PRELIMINARY. Misleading.
  - In the chart Labs → Results table, the per-result **Flags column is empty** and the
    **"Abnormal only" filter returns 0**, even though the trend engine flags A1c on the same
    screen. The results table doesn't carry the abnormal interpretation.
  - **Result rows aren't openable** — clicking a CBC/BMP row does nothing; can't drill into the
    component analytes.

## GOAL

Make abnormal results visible and actionable: the home indicator counts abnormals (incl.
preliminary), the results table flags abnormals and its "Abnormal only" filter works, and rows
open a result detail.

## FILES

- `src/hooks/home/useHomeInboxLabs.ts` — the "labs to review" count.
- `src/pages/patient/tabs/LabsTab.tsx` — the Results sub-tab table (Flags column + "Abnormal only").
- `src/pages/patient/LabResultPage.tsx`, `src/components/labs/LabResultDetail.tsx` — result detail.
- `src/components/labs/LabTrendPanel.tsx` — reuse its out-of-range logic as the shared flag source.

## ACCEPTANCE CRITERIA

1. **Home indicator counts abnormals.** "New labs to review" counts results that are out of
   range / flagged abnormal, including `preliminary` status — not only `final`. When an abnormal
   exists, the tile shows a non-zero count and is clickable (routes to the results queue/list),
   not "All clear / inert".
2. **Per-result Flags populated.** Each results-table row shows an abnormal flag when the value
   is out of range (derive from `Observation.interpretation`, or compare value to reference
   range using the SAME logic the trend panel uses). A1c 7.4% shows abnormal.
3. **"Abnormal only" filter works.** Toggling it returns the out-of-range results (≥1 for
   Hargrove), not 0.
4. **Rows openable.** Clicking a result row opens its detail (`LabResultPage`/`LabResultDetail`)
   showing component analytes and which is abnormal.
5. No regression to the trend panel or scorecard.

## IMPLEMENTATION SKETCH

- Extract the out-of-range determination from `LabTrendPanel` into a shared helper
  `isObservationAbnormal(obs)` (interpretation code in {H,HH,L,LL,A} OR value outside
  `referenceRange`). Use it in: (a) `useHomeInboxLabs` count, (b) the Results table Flags column
  + "Abnormal only" filter, so the table and the trend engine agree.
- `useHomeInboxLabs`: broaden the query to include `preliminary` results and count those that are
  abnormal; expose `count` + make the home tile `href` route to the results list.
- `LabsTab` Results table: render an abnormal Badge per row via the shared helper; wire the
  "Abnormal only" toggle to filter on it; make each row a button → `navigate` to the result detail.

## OUT OF SCOPE

- Building a full cross-patient labs inbox / sign-off workflow (post-demo; this brief makes the
  per-patient surface correct + the home indicator honest).
- The process-measure "IN TARGET" green badge vs abnormal value visual subordination (P3, defer).

## DEFINITION OF DONE

- Home labs indicator honest + clickable; results flagged; "Abnormal only" works; rows open.
- Commit message: `FIX-05: labs triage — abnormal flags, working filter, live home indicator (S6S60)`.

## §29 / §31

§29 standard.

§31 smoke:
1. Home → "New labs to review" shows a non-zero count (Hargrove's abnormal A1c) and is clickable.
2. Chart → Labs → Results → A1c row shows an abnormal flag; "Abnormal only" returns it.
3. Click a result row → opens the result detail with component values.
