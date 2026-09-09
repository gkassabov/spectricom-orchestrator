# Toni Batch S6S60 — FIX-06: AuditEvent write 400

## Repo: clinical-mp
## Batch ID: s6s60-fix-06-auditevent-write
## Briefs: 1
## Estimated runtime: 20-30m
## Predecessor: clinical-mp main @ a617327
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 35
## Severity: P2 (silent backend failure)

## CONTEXT

Synth UAT (J-A refill approve) network trace: the core approval succeeded
(`PUT /MedicationRequest` 200, `POST /Provenance` 201), but `POST /AuditEvent` returned **400**.
So `logAuditEvent` (`src/lib/audit/audit-event.ts`) is emitting an AuditEvent that Medplum
rejects as malformed on every audited action (refill approve, inbox reply, etc.). The audit trail
is silently not being written — a compliance gap, and the same silent-write smell as the inbox
reply not surfacing.

A 400 (not 403) means a VALIDATION failure — a required FHIR R4 AuditEvent element is missing or
malformed, not a permission denial.

## GOAL

`logAuditEvent` produces a valid AuditEvent that Medplum accepts (201) for every `AuditAction`.

## FILES

- `src/lib/audit/audit-event.ts` — the AuditEvent construction.
- `src/lib/audit/__tests__/` — add a validation test.

## ACCEPTANCE CRITERIA

1. **AuditEvent writes succeed.** `logAuditEvent` returns a created AuditEvent (no 400) for a
   representative set of actions (approve-refill, reply-inbox-item, view-patient).
2. **R4-valid resource.** The emitted AuditEvent includes all required elements:
   `type` (Coding), `recorded` (instant), `agent` (≥1, each with `who` or `requestor:true`),
   `source` (with `observer`), and a valid `action`/`outcome` if present. Verify against the
   Medplum 400 response body (it names the missing/invalid path).
3. **No silent swallow.** If an audit write fails, it logs a warning (console) but does not break
   the user action (audit is best-effort, not blocking) — keep current non-blocking behavior.
4. Unit test asserts the constructed AuditEvent has the required fields populated.

## IMPLEMENTATION SKETCH

- Reproduce: call `logAuditEvent(medplum, { action: 'approve-refill', target: {...} })` and read
  the 400 body (it specifies the offending element, e.g. "AuditEvent.source.observer: missing").
- Most likely fixes: populate `source: { observer: { reference: 'Device/...' or 'Organization/...' } }`,
  ensure `agent: [{ who: <Practitioner ref>, requestor: true, type: ... }]`, set `recorded` to an
  ISO instant, and a valid `type` Coding (e.g. system
  `http://terminology.hl7.org/CodeSystem/audit-event-type`, code `rest`).
- Keep the call non-blocking (wrap in try/catch, warn on failure).

## OUT OF SCOPE

- Building an audit-log viewer or retention policy.
- AccessPolicy changes (this is validation, not permission — confirm via the 400 body first; only
  touch AccessPolicy if the body shows a permission error instead).

## DEFINITION OF DONE

- AuditEvent writes return 201 across sampled actions; unit test passes.
- Commit message: `FIX-06: emit R4-valid AuditEvent (fix 400 on audited actions) (S6S60)`.

## §29 / §31

§29 standard.

§31 smoke:
1. Approve a refill on `/refills`; in the network panel confirm `POST /AuditEvent` → 201 (was 400).
2. Reply to an inbox message; confirm its AuditEvent also 201.
