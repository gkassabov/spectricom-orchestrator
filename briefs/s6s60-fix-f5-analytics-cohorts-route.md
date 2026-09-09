# Toni Batch S6S60 — FIX-F5: register /analytics/cohorts route + analytics nav consistency

## Repo: clinical-mp
## Batch ID: s6s60-fix-f5-analytics-cohorts-route
## Briefs: 1
## Estimated runtime: 15-25m
## Predecessor: clinical-mp main (post-F3)
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 30
## Severity: P2 (analytics nav dead-link; working route exists)

## CONTEXT

Synth UAT (J-K) found `/analytics/cohorts` renders a blank page (console
`OperationOutcomeError: Not found`). The Cohort builder works fine at `/cohorts`
(`src/App.tsx` ~L284: `<Route path="/cohorts" ... ><CohortBuilderPage/></...>`), but the analytics
nav links to it under the `/analytics/` prefix, which is not registered. The other analytics pages
ARE under `/analytics/` (`/analytics/quality`, `/analytics/productivity`, `/analytics/population`),
so cohorts is the odd one out. Also noted: bare `/productivity` 404s while `/analytics/productivity`
works — nav-prefix inconsistency.

EXPLICITLY NOT IN SCOPE (these are by-design, NOT bugs): the Population-health "risk-tier UNKNOWN"
and "0 uncontrolled conditions" readings. `src/lib/analytics/population/fromFhir.ts#buildPanelFromCohort`
intentionally sets `riskTier: undefined` and `uncontrolledConditionKeys: []` (its comment: CDS-5
stratification "is not run in this view ... rather than inventing a tier"). Do NOT fabricate tiers or
control flags. Do NOT touch the population aggregators.

## GOAL

Make the Cohort builder reachable at `/analytics/cohorts` (matching the analytics nav + the other
analytics routes), without breaking the existing `/cohorts` route.

## FILES
- `src/App.tsx` (route table + `ROUTE_COMPONENT_MAP` if the gate keys off it)
- whichever nav/sidebar component links Cohorts (search for `/analytics/cohorts` or the Cohorts nav item)

## IMPLEMENT
1. Add a `/analytics/cohorts` route mirroring the existing `/cohorts` route — same
   `PracticeFeatureGate` wrapper and `<CohortBuilderPage/>`. If `PracticeFeatureGate` keys off
   `ROUTE_COMPONENT_MAP`, add an `'/analytics/cohorts'` entry mapping to the same component value as
   `'/cohorts'` (or reuse the `/cohorts` key). KEEP `/cohorts` registered too (both resolve).
2. Make the analytics nav Cohorts link point to a registered path (`/analytics/cohorts`). While here,
   confirm the Productivity nav item points to `/analytics/productivity` (registered), not bare
   `/productivity`.

## ACCEPTANCE CRITERIA
1. Navigating to `/analytics/cohorts` renders `CohortBuilderPage` (not blank / not "Not found").
2. The analytics-nav Cohorts link resolves to the working page.
3. `/cohorts` still renders `CohortBuilderPage` (no regression).
4. Productivity nav resolves to `/analytics/productivity`.

## OUT OF SCOPE
- Risk-tier / uncontrolled-condition computation (by-design; see CONTEXT).
- Cohort-match vs population-prevalence reconciliation and the 41-vs-6 panel-size question
  (separate investigation — may also be by-design; not in this brief).

## DEFINITION OF DONE
- `/analytics/cohorts` works; `/cohorts` unaffected; nav links resolve.
- Commit message: `FIX-F5: register /analytics/cohorts route + analytics nav consistency (S6S60)`.

## §29 / §31
§29 standard.
§31 smoke:
1. Go to `/analytics/cohorts` -> Cohort builder renders (criterion builder, saved cohorts).
2. Click the analytics-nav Cohorts item -> same page.
3. Go to `/cohorts` -> still renders.
