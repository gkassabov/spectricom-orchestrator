# 983 BUILD-GATE-SERVER-TSC-1 — handback

## STATUS: DONE

Route branch `orch-orch-00000983-build-gate-server-tsc-1`, base `f326c50` (`git merge-base --is-ancestor b827a9b HEAD` → ok).
Commit: see `git log -1` on the route branch, subject `BUILD-GATE-SERVER-TSC-1 (983; …)`.

## STOP checks
- (a) 981 on clinical-mp main: `ba3af042 fix: 981 TSC-SERVER-GREEN-1 …` and `e0cba67c fix: 00000981-tsc-server-green-1 — 1 briefs` (clinical-mp main = HEAD = `e0cba67c`, clean). `tsc --noEmit -p server` on clinical-mp main (`~/spectricom-clinical-mp/node_modules/.bin/tsc --noEmit -p ~/spectricom-clinical-mp/server`) → exit 0, no output.
- (b) no change outside ALLOWED FILES. (c) no existing assertion changed (no existing test edited). (d) A0 matches (below).

## A0 (at HEAD, before any edit)
1. `…['clinical-mp'].get('build_gate_cmd')` → `None`
2. `grep -c "    build_timeout_s: 1200" config/repos.yaml` → `1`
3. `git -C ~/spectricom-clinical-mp log main --oneline -i --grep="TSC-SERVER-GREEN-1" | wc -l` → `2` (≥ 1)

## G-1
`sha256sum ~/_eos/s7core63/laneT/p983.patch` → `c9c894b51abf8035667c9beec6b0014c1e91e9691974749efe0a2bc92fb5f9f3` (matches). `git apply --check` clean; `--stat` 2 files changed, 34 insertions(+). Applied in two `--include` passes (tests/* first for RED, then config/*) — net result is the patch byte-for-byte.

## RED / GREEN (`python3 -m pytest -q -p no:cacheprovider tests/test_build_gate_server_tsc_1.py`)
- RED (test only): 1 failed (S-1, `[S-1] clinical-mp build_gate_cmd = None`), 1 passed (S-2).
- GREEN (G-1): 2 passed — `[S-1] clinical-mp build_gate_cmd = 'npx tsc --noEmit && npx tsc --noEmit -p server && npm run build'`.

## Related five files
Not run by the executor: the fire instruction (and CLAUDE.md ORCH-LEAN-GATE-1) limits the executor to its own new/changed test files by path; the pre-merge gate runs the full orchestrator suite. Dry run's count stands as the reference: 274 passed.

## Discrepancy for Gemma / George (not a STOP — flagged)
The brief's prose quotes the command with `--no-install` (Delivers (1), CRITICAL CONTEXT's `BUILD_GATE_CMD`, DRY RUN GREEN line): `npx --no-install tsc --noEmit && npx --no-install tsc --noEmit -p server && npm run build`. The hash-locked patch (and so the merged config and S-1) carries **no** `--no-install`: `npx tsc --noEmit && npx tsc --noEmit -p server && npm run build`. That matches HEAD's real default `BUILD_GATE_CMD = "npx tsc --noEmit && npm run build"` (`orchestrator.py:243`, asserted unchanged by S-2), so the new command follows the existing default's form. I applied the patch verbatim per G-1. If `--no-install` was intended, that is a one-line follow-up to the yaml value plus S-1's expected string.

No typecheck run: the orchestrator repo has no tsc and this route changes no code (config + one test); the gate's py_compile covers the rest.

## After merge (main session)
Restart the daemon in a quiet window (rule #12) and read the next clinical-mp route's `🔧 Running build gate [clinical-mp]:` line — it should name the three-part command above.
