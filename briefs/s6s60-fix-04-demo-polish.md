# Toni Batch S6S60 — FIX-04: Demo-polish cluster (4 briefs)

## Repo: clinical-mp
## Batch ID: s6s60-fix-04-demo-polish
## Briefs: 4
## Estimated runtime: 35-50m
## Predecessor: clinical-mp main @ a617327
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 55
## Severity: P2/P3 (visible in demo)

## CONTEXT

Four small, high-visibility issues found across J-A and J-B:

  4a. **Runaway scribe meter.** The encounter Timeline banner reads "Voice scribe listening ·
      33,71x min · consent on file" (~561 hours) — a placeholder/never-reset counter. Glaring.
      Source: `src/components/encounter/VoiceScribeBanner.tsx` (+ `src/pages/patient/ActiveVisitStrip.tsx`).
  4b. **Right notification bell dead-ends.** The provider-shell "Notifications" bell
      (`src/shell/NotificationsBell`) opens no panel and navigates nowhere; clicking it just
      mutates its own badge (19→20, then clears). The left "What's New" bell
      (`src/components/features/WhatsNewPanel.tsx`) works.
  4c. **Tab-panel stacking.** Opening the Care Plans tab AND the Labs tab renders the Bio-Age
      hero / Active Conditions / Recent Labs (chart-summary/Timeline content) ABOVE the actual
      tab panel — a screenful of summary to scroll past. Source:
      `src/pages/patient/PatientTabsContent.tsx`. Systemic (both tabs), so one fix.
  4d. **Prescribe modal retains stale data after a blocked order.** After a med is blocked
      (e.g. allergy) and cancelled, reopening Prescribe pre-fills the cancelled med's
      name/sig/indication, so new typing APPENDS ("Aspirin 81mgAtorvastatin 20mg") — a
      prescription-contamination risk. Tied to the blocked-submit path.
      Source: `src/components/medications/PrescribeModal.tsx`.

## GOAL

Remove four demo-embarrassing defects: sane scribe meter, a working notifications bell, clean
tab-panel swapping, and a prescribe modal that always opens fresh.

## FILES

- `src/components/encounter/VoiceScribeBanner.tsx`, `src/pages/patient/ActiveVisitStrip.tsx` (4a)
- `src/shell/NotificationsBell.tsx` (4b)
- `src/pages/patient/PatientTabsContent.tsx` (4c)
- `src/components/medications/PrescribeModal.tsx` (4d)

## ACCEPTANCE CRITERIA

1. (4a) The scribe banner never shows an implausible duration. The elapsed minutes derive from
   the actual capture start and reset when the encounter/capture ends; if no active capture, the
   "listening" banner does not render a runaway counter (cap at the encounter length; hide if no
   active session).
2. (4b) Clicking the provider Notifications bell opens a notifications panel (or navigates to the
   notifications list) showing the unread items; the badge reflects true unread count and clears
   on view — it does not increment on click.
3. (4c) Opening the Care Plans tab shows ONLY the Care Plans panel; opening Labs shows ONLY the
   Labs panel. The Timeline/chart-summary content does not stack above the active tab panel.
   Holds after a hard reload.
4. (4d) Every time the Prescribe modal opens, all fields (medication, sig, indication, etc.) are
   empty — including after a blocked/cancelled order. Typing never appends to stale values.
5. No regressions; build-green + unit-green.

## IMPLEMENTATION SKETCH

4a — In `VoiceScribeBanner`, compute elapsed from a real `captureStartedAt`; clamp to a sane max
(e.g. the encounter period length) and render the banner only when a capture session is active.
Reset the start ref when capture stops / encounter finalizes.

4b — In `NotificationsBell`, replace the badge-mutating onClick with a Mantine `Menu`/`Popover`
that lists notifications (reuse the data the badge already counts) and a "View all" route, OR
`navigate` to the notifications list. Badge = unread count; clears on open.

4c — In `PatientTabsContent`, render the active tab's panel exclusively (the summary/Timeline
should be its own tab, not a prefix to every panel). Likely the summary block is rendered
unconditionally before the `switch(activeTab)` — move it under the Timeline/Overview case only.

4d — In `PrescribeModal`, reset form state on close AND on the blocked/cancel path (clear the
controlled fields in the close handler, or key the modal/form so it remounts fresh on open).
Ensure the blocked-submit branch calls the same reset as a clean cancel.

## OUT OF SCOPE

- Redesigning the notifications model or the chart tab IA.
- Ambient/voice capture behavior beyond the meter display (4a is display-only).

## DEFINITION OF DONE

- Scribe meter sane; bell opens a panel; tabs swap cleanly; prescribe modal opens empty.
- Commit message: `FIX-04: demo-polish — scribe meter, notif bell, tab swap, prescribe reset (S6S60)`.

## §29 / §31

§29 standard.

§31 smoke:
1. Open an encounter Timeline → scribe banner shows a plausible duration or none, never ~33k min.
2. Click the provider Notifications bell → a panel/list opens; badge doesn't increment on click.
3. Open Care Plans tab, then Labs tab → each shows only its panel, no summary stacked above.
4. Prescribe a med, get it blocked, cancel, reopen Prescribe → all fields empty; type → no append.
