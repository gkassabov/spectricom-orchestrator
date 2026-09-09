# Toni Batch S6S61 — MSG-06: agent loop loops to the turn cap — terminate after first substantive action

## Repo: clinical-mp
## Batch ID: s6s61-msg-06-agent-loop-terminate
## Briefs: 1
## Estimated runtime: 15-20m
## Predecessor: clinical-mp main @ b15a1cb
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 20
## Severity: P1 (live triage is slow + noisy: Michelle loops draftSchedule/reply to the 6-turn cap, ~5 min/thread, duplicate drafts, then a spurious auto-escalation)

## CONTEXT

Confirmed in code AND the live systemd journal:
- `src/lib/agentic-runtime/agent-loop.ts` `runAgentLoop`: `escalate` and `done` are terminal (they return),
  but `reply` and `draftSchedule` are NOT — after a successful tool run the loop appends to `history` and
  CONTINUES to the next turn, up to `cap`.
- Live (Groq llama-3.1-8b, the D-1 LLM): the model rarely emits `done` after acting, so it REPEATS actions.
  Observed for one thread: `tools=[draftSchedule, reply, draftSchedule, reply, draftSchedule, reply, escalate]`,
  then `Turn cap (6) reached; auto-escalating`, outcome `capped-escalated` — ~5 min/thread, duplicate
  schedule drafts, and an unnecessary final escalation.
- The cap is `MICHELLE_TURN_CAP`, imported from `src/lib/synth/michelle-handler.ts`.

## GOAL

One inbound message => exactly ONE substantive action (reply OR draftSchedule OR escalate) => the loop ends.
No looping, no duplicate drafts, no spurious cap-escalation. Fast (1-2 LLM calls per triage).

---

## BRIEF MSG6-1 — terminate the loop after the first successful substantive action

### FILES
- `src/lib/agentic-runtime/agent-loop.ts`
- `src/lib/synth/michelle-handler.ts` (turn cap)
- `src/lib/agentic-runtime/__tests__/` (agent-loop tests — extend)

### IMPLEMENT
- In `runAgentLoop`, in the `action.kind === 'tool'` branch: after `safeRun` returns a TRUTHY `outcome`
  (the reply/draftSchedule actually took effect), push the record/step/toolCall as today and then RETURN
  immediately with a terminal result: `{ outcome: 'done', escalated: false, steps, records, toolCalls }`.
  Do NOT fall through to the next loop iteration. (`escalate` and `done` already return.)
- Preserve the REJECTED path unchanged: if `safeRun` returns `undefined` (cage/scope/write rejection),
  append the rejection to `history` and CONTINUE the loop (so the agent can retry or escalate).
- Lower `MICHELLE_TURN_CAP` to `3` in `michelle-handler.ts` (defensive; with terminate-on-action it is
  rarely reached). Keep the cap-reached auto-escalate as the safety net.

### ACCEPTANCE
1. When the LLM returns a valid `draftSchedule`, the loop executes it and returns `outcome === 'done'` with
   `toolCalls === ['draftSchedule']`, and the injected LLM mock is called EXACTLY once (no further turns).
2. Same for a valid `reply`: `toolCalls === ['reply']`, one LLM call, `outcome === 'done'`.
3. `escalate` still returns `outcome === 'escalated'`; `done` still returns `outcome === 'done'` (unchanged).
4. A tool REJECTION (handler throws -> outcome undefined) does NOT terminate: the loop appends the rejection
   and continues (existing behavior; test asserts a second LLM turn occurs).
5. `MICHELLE_TURN_CAP === 3`.
6. `npm run build` green; unit tests green.

### OUT OF SCOPE (do NOT implement)
- Multi-step triage conversations / patient-reply follow-ups.
- Thread-state semantics, the daemon, provider routing, model choice.
