# Toni Batch S6S61 — MSG-05: GroqProvider crashes under Node/tsx — use Node-safe readEnv

## Repo: clinical-mp
## Batch ID: s6s61-msg-05-groq-node-env
## Briefs: 1
## Estimated runtime: 10-15m
## Predecessor: clinical-mp main @ 0a1ab25
## Fire mechanism: orchestrator queue --repo clinical-mp --approve --skip-sit
## TONI_TIMEOUT_MIN: 15
## Severity: P1 (the always-on triage daemon cannot initialize the Groq LLM — it crash-loops on startup; live triage is fully blocked)

## CONTEXT

Confirmed in code AND live (systemd journal):
- The agentic daemon runs under Node/tsx, where `import.meta.env` is UNDEFINED. `src/lib/llm/env.ts`
  provides a Node-safe `readEnv(key)` (checks import.meta.env defensively, falls back to process.env).
  `getLLMProviderId()` and `src/lib/llm/providers/ollama-provider.ts` already use `readEnv`.
- `src/lib/llm/providers/groq-provider.ts` constructor (~lines 340-346) reads
  `import.meta.env.VITE_GROQ_API_KEY`, `import.meta.env.VITE_GROQ_MODEL`, and
  `import.meta.env.VITE_LLM_REQUEST_TIMEOUT_MS` DIRECTLY. Under Node this throws
  `Cannot read properties of undefined (reading 'VITE_GROQ_API_KEY')`, so `getLLMProvider()` fails and the
  daemon crash-loops on startup (observed live). With `VITE_LLM_PROVIDER=groq`, the daemon has never
  successfully initialized — it only ever worked on the mock provider.

## GOAL

GroqProvider reads its config via the Node-safe `readEnv`, mirroring ollama-provider.ts, so the daemon
initializes Groq under Node/tsx. The browser (Vite) path is unchanged (readEnv reads import.meta.env there).

---

## BRIEF MSG5-1 — Groq provider: read env via readEnv (Node-safe)

### FILES
- `src/lib/llm/providers/groq-provider.ts`
- `src/lib/llm/providers/` test (or `src/lib/llm/index.test.ts`) — assert Node init works

### IMPLEMENT
- Add `import { readEnv } from '../env';`
- Replace `import.meta.env.VITE_GROQ_API_KEY` → `readEnv('VITE_GROQ_API_KEY')`.
- Replace `import.meta.env.VITE_GROQ_MODEL ?? 'llama-3.1-8b-instant'` → `readEnv('VITE_GROQ_MODEL') ?? 'llama-3.1-8b-instant'`.
- Replace `Number(import.meta.env.VITE_LLM_REQUEST_TIMEOUT_MS) || 30_000` → `Number(readEnv('VITE_LLM_REQUEST_TIMEOUT_MS')) || 30_000`.
- Keep the existing `'VITE_GROQ_API_KEY required when VITE_LLM_PROVIDER=groq'` error. No other behavior change.

### ACCEPTANCE
1. `groq-provider.ts` contains NO direct `import.meta.env` references; all config via `readEnv`.
2. With `process.env.VITE_GROQ_API_KEY` set and `import.meta.env` undefined (Node), constructing the Groq
   provider succeeds and picks up the key (unit test asserts).
3. `npm run build` green; unit tests green.

### OUT OF SCOPE (do NOT implement)
- Other `import.meta.env` sites (e.g. prewarm.ts — browser-only).
- Provider request/chat logic; the daemon; env.ts itself.
