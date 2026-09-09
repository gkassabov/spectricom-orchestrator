# Toni Batch S6S61 — MSG-02: agentic daemon hardcodes Dr. K — generalize to the patient's panel provider

## Repo: clinical-mp
## Batch ID: s6s61-msg-02-daemon-provider-generic
## Briefs: 1
## Estimated runtime: 30-45m
## Predecessor: clinical-mp main @ 01bd0c1 (runs after MSG-01; files are disjoint)
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 45
## Severity: P1 (the live triage daemon escalates/books EVERY thread to Dr. K, so it misroutes any non-Dr-K-panel patient — blocks the Dr-W E2E self-run steps 2-4 + 10)

## CONTEXT

Confirmed in code AND in live Medplum data (:8103):
- `src/daemon/agentic-daemon.ts` resolves ONE `drKRef` at startup (from `DR_K.identifier`) and uses it as
  (a) the escalation Task owner (`escalate({ drKRef })`), (b) the schedule-draft approver
  (`draftSchedule({ approverRef: ctx.drKRef })`), and (c) the Appointment + Encounter participant in
  `processApprovedSchedules`. Every thread routes to Dr. K regardless of the patient's real provider.
  It also passes `providerName: ctx.michelleRef.display` into `draftSchedule` — i.e. the schedule draft
  records the CARE MANAGER as the provider, not the physician.
- The app already binds patient->provider via FHIR `Patient.generalPractitioner` (D-371/D-372 panel
  partition). Helper `getDefaultRecipient(patient)` (`src/lib/escalate/context-injection.ts`) returns
  `patient.generalPractitioner[0]`. `routeIncomingCommunication` (`src/lib/inbox/routing-rules.ts`) routes
  inbound comms to that GP. The daemon ignores both.
- Live: PT-016 Catherine Hargrove (Whitman panel) `generalPractitioner` -> Practitioner/00ef60a8... =
  Dr. Sarah Whitman (SYNTH-PROV-005). PT-001 Maria Santos -> her GP (Dr. K, SYNTH-PROV-001). IMPORTANT:
  the GP reference carries NO `display`, so the daemon must read the Practitioner to get the name for
  Michelle's prompt and the booking participant display.
- Michelle's SOP prompt is hardcoded to Dr. K: `src/lib/synth/practitioners.ts` `MICHELLE.michelleSystemPrompt`
  says the practice is "led by Dr. Daniela Kassabov" and the escalation rules name "Dr. Kassabov"/"Dr. K".
  For a Whitman patient she must escalate/refer to Dr. Whitman.
- The schedule draft schema `PracticeDraft` (`src/lib/agentic-drafts/types.ts`) has `providerName: string`
  but no provider REFERENCE, so `processApprovedSchedules` cannot recover the booking provider and falls
  back to `drKRef`.

## GOAL

The daemon resolves the patient's panel provider per thread (`Patient.generalPractitioner`) and uses that
single provider as the escalation owner, the schedule approver, and the booked Appointment/Encounter
provider; Michelle addresses that provider by name. Michelle stays the shared MA across the practice.
No hardcoded provider and NO silent Dr. K default — a patient with no resolvable provider is skipped, not
misrouted. Fallback order (locked): patient.generalPractitioner -> optional env AGENTIC_DEFAULT_PROVIDER ->
skip + log.

---

## BRIEF MSG2-1 — resolve provider per thread; thread it through escalate/draftSchedule/booking; parameterize Michelle

### FILES
- `src/lib/synth/practitioners.ts`
- `src/lib/agentic-drafts/types.ts`
- `src/lib/agentic-runtime/tools.ts`
- `src/daemon/agentic-daemon.ts`
- `src/lib/agentic-runtime/__tests__/` (add a daemon-routing / tools test; reuse existing test setup)

### IMPLEMENT

**1. `practitioners.ts` — parameterize Michelle's supervising-physician name**
- Add `export function buildMichelleSystemPrompt(supervisingProviderName: string): string` that returns
  Michelle's current SOP text with EVERY supervising-physician reference ("Dr. Daniela Kassabov",
  "Dr. Kassabov", "Dr. K") replaced by `supervisingProviderName`.
- Keep `MICHELLE.michelleSystemPrompt` populated for back-compat (e.g. set it to
  `buildMichelleSystemPrompt('your supervising physician')`). The daemon will call the builder per thread.

**2. `agentic-drafts/types.ts` — carry the booking provider on the draft**
- Add OPTIONAL `providerRef?: string` (a `Practitioner/{id}` reference string) to `PracticeDraft`,
  used by the `schedule` kind to persist the booking provider. Optional = back-compat for existing drafts.

**3. `tools.ts` — make the verbs provider-agnostic**
- `escalate`: rename the `drKRef` param to `providerRef` (it is ONLY used as the Task `owner`). Update the
  JSDoc/comment from "Dr. K" to "the patient's panel provider". Change the success summary
  "Escalated to Dr. K (urgent Task)." -> "Escalated to the provider (urgent Task)." Update ALL callers + tests.
- `draftSchedule`: add OPTIONAL `providerRef?: Reference<Practitioner>` to `DraftScheduleParams`; when
  present, persist `providerRef: p.providerRef.reference` into the `PracticeDraft`. Keep `providerName` as
  the display string (the caller now passes the PHYSICIAN's name). Change the summary
  "Schedule draft queued for Dr. K approval." -> "Schedule draft queued for provider approval."

**4. `agentic-daemon.ts` — resolve and thread the per-patient provider**
- Import `getDefaultRecipient` from `../lib/escalate/context-injection` and `buildMichelleSystemPrompt`
  from `../lib/synth/practitioners`.
- `DaemonContext`: REMOVE `drKRef`. ADD optional `defaultProviderRef?: Reference<Practitioner>` (the
  configurable fallback) and `providerNameCache: Map<string, string>`.
- Add `async function resolveProviderForPatient(ctx, patient): Promise<Reference<Practitioner> | undefined>`:
  start from `getDefaultRecipient(patient)` (falls back to `ctx.defaultProviderRef`). If the resulting
  reference lacks `display`, read the Practitioner once (cache the display name by reference string in
  `providerNameCache`) and return a reference WITH `display` set.
- `processThread`: resolve the provider for this patient. If NONE ->
  `log('Skipping ' + comm.id + ': patient has no panel provider (generalPractitioner) and no AGENTIC_DEFAULT_PROVIDER.')`
  and return (do NOT misroute). Build the system prompt via `buildMichelleSystemPrompt(providerDisplay)`
  and pass THAT to `runAgentLoop` instead of `MICHELLE.michelleSystemPrompt!`.
- `buildHandlers(ctx, comm, patient, providerRef)`: use `providerRef` as `approverRef` (reply +
  draftSchedule), as `providerRef` for `escalate`, and pass `providerName: providerRef.display ?? 'Provider'`
  + `providerRef` into `draftSchedule`.
- `processApprovedSchedules`: derive the booking provider per task =
  `draft.providerRef` (resolve to a Reference, attaching display via cache)
  ?? re-resolve the patient's GP (read Patient -> getDefaultRecipient)
  ?? `ctx.defaultProviderRef`.
  If STILL none -> log + skip that booking (do NOT book to a hardcoded Dr. K). Use that provider for both
  the Appointment participant and the Encounter participant.
- `main()`: resolve Michelle (REQUIRED — keep exit-on-missing). REMOVE the hard requirement on Dr. K.
  Optionally resolve `process.env.AGENTIC_DEFAULT_PROVIDER` (accept either a synth identifier OR a
  `Practitioner/{id}` reference) into `defaultProviderRef`; if unset, leave undefined. Update the startup
  log line to drop the Dr. K reference. Document the new optional `AGENTIC_DEFAULT_PROVIDER` env in the
  header comment block.

### ACCEPTANCE
1. No `DR_K`/`drKRef` remains as a routing target in `agentic-daemon.ts`; the provider is resolved from
   `Patient.generalPractitioner` per thread.
2. Unit test (mock Medplum): a thread whose patient's `generalPractitioner` is Whitman produces an
   escalation Task with `owner` = Whitman; a thread whose patient's GP is Dr. K escalates to Dr. K — with
   the SAME shared Michelle in both.
3. `draftSchedule` persists `providerRef`; `processApprovedSchedules` books the Appointment + Encounter
   with the draft's provider (test asserts the participant equals the patient's GP, not a fixed Dr. K).
4. `buildMichelleSystemPrompt('Dr. Sarah Whitman')` contains "Dr. Sarah Whitman" and not "Kassabov"
   (test asserts).
5. A patient with no `generalPractitioner` and no `AGENTIC_DEFAULT_PROVIDER` is skipped with a clear log,
   not routed to any default.
6. `npm run build` green; unit tests green.

### OUT OF SCOPE (do NOT implement)
- Event/Bot instant trigger (E4 roadmap; the poll cadence is unchanged).
- The inbox status fix (separate brief MSG-01).
- Any change to the agentic-ops cage (O2/O4/O5), routing dispositions, or the agent loop control flow.
- Pre-visit brief generation (still fixture-fed).
