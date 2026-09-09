# Toni Batch S6S60 — FIX-07: Longevity care-plan template + outreach seed

## Repo: clinical-mp
## Batch ID: s6s60-fix-07-longevity-seed
## Briefs: 1
## Estimated runtime: 25-35m
## Predecessor: clinical-mp main @ a617327
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 40
## Severity: P1-demo (J-E enabler) / seed

## CONTEXT

Synth UAT (J-E, Hargrove) found the longevity STORY is demo-grade (Bio-Age hero + attribution +
graceful fallback + care-plan assign→chart→portal all verified), but the "assign a LONGEVITY
plan + send a nudge" beat can't be completed:
  - The Care-Plan assign dropdown offers only "UAT Diabetes Care Plan"; there is no
    Metabolic-Longevity template to assign (it exists only as a pre-seeded instance on Hargrove).
  - Every assigned plan shows "0/0 steps · No action steps defined" — the assign flow doesn't
    materialize the `PlanDefinition.action` steps into the resulting `CarePlan.activity`.
  - The `/outreach` worklist is empty ("No outreach events today") with no manual nudge. The
    seed (`seedOutreachHistory`) creates PAST-dated outreach Communications (`daysAgo` offsets),
    but the worklist surfaces TODAY's events, so the seeds never appear.

`seed-care-plans.ts` already defines several `PlanDefinition`s with `action:[{title,description,
code:[actionCode(...)]}]` (ANNUAL_PHYSICAL, HRT_MALE, …). The pattern is clear.

## GOAL

Make the longevity demo self-contained: a Metabolic-Longevity care-plan template (with real
steps) is assignable, assigned plans show their steps, and the `/outreach` worklist has events to
act on.

## FILES

- `src/lib/synth/seed-care-plans.ts` — add a `METABOLIC_LONGEVITY` PlanDefinition with steps; ensure it's seeded.
- `src/pages/patient/tabs/CarePlansTab.tsx` (+ the assign handler / care-plan service) — materialize `PlanDefinition.action` → `CarePlan.activity` on assign.
- `src/lib/synth/seed-outreach.ts` — seed a few TODAY-dated outreach events.
- `src/lib/synth/__tests__/` — extend the care-plans seed test.

## ACCEPTANCE CRITERIA

1. **Longevity template assignable.** The Care-Plan "Assign New" dropdown includes
   "Metabolic Longevity Protocol" (and the other seeded PlanDefinitions), not just UAT Diabetes.
2. **Template has real steps.** `METABOLIC_LONGEVITY` defines ≥4 action steps (e.g. comprehensive
   longevity panel incl. ApoB/hs-CRP/fasting insulin/HbA1c; metabolic + Levine PhenoAge baseline;
   personalized intervention plan; 90-day re-test; lifestyle/supplement counseling), each with a
   `title`, `description`, and an `actionCode`.
3. **Assigned plan shows steps.** After assigning the longevity plan to Hargrove, the card shows
   "N/N steps" with the action steps listed — NOT "0/0 steps · No action steps defined". The
   assign flow copies `PlanDefinition.action` into `CarePlan.activity`.
4. **Outreach worklist populated.** After seeding, `/outreach` shows ≥2 events dated today
   (Total/Sent reflect them) so a physician can see/act on the worklist (route-around no longer
   required for the demo). Existing past-dated history seeding is preserved.
5. Idempotent seed (re-running doesn't duplicate); seed test passes.

## IMPLEMENTATION SKETCH

- `seed-care-plans.ts`: add `const METABOLIC_LONGEVITY: PlanDefinition = { resourceType:
  'PlanDefinition', status:'active', title:'Metabolic Longevity Protocol', action:[ {title:'…',
  description:'…', code:[actionCode('order-labs')]}, … ] }` following the ANNUAL_PHYSICAL pattern;
  include it in the array the seeder upserts. Confirm the seeder upserts ALL templates (so the
  assign dropdown lists them), keyed by a stable identifier for idempotency.
- Assign flow: in the assign handler that turns a chosen `PlanDefinition` into a `CarePlan`, map
  `planDef.action` → `carePlan.activity` (each as a `detail` with `description`/`status:'not-started'`)
  so the card renders steps. This fixes the 0/0 for ALL templates, not just longevity.
- `seed-outreach.ts`: add a couple of samples with `daysAgo: 0` (today) — or compute `occurrence`
  for today — so `seedOutreachHistory` produces events the worklist's "today" query returns. Keep
  existing past samples for history.

## OUT OF SCOPE

- A care-plan AUTHORING UI (create-from-scratch) — post-demo; this brief enables assign-from-template.
- A manual "schedule/send nudge" action in `/outreach` — post-demo; seeding events covers the demo.
- `/concierge` route 404 + nav entry (separate P3, defer).

## DEFINITION OF DONE

- Longevity template assignable with steps; assigned plans show steps; outreach worklist populated.
- Commit message: `FIX-07: longevity care-plan template + step materialization + today outreach seed (S6S60)`.

## §29 / §31

§29 standard.

§31 smoke:
1. Open Hargrove → Care Plans → Assign New → "Metabolic Longevity Protocol" is selectable.
2. Assign it → card shows N/N steps with the listed actions (not 0/0).
3. Open `/outreach` → ≥2 events visible today; Total/Sent non-zero.
