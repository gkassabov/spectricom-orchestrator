# tests/fixtures/unit_load — ORCH-FULLGATE-WT-FSDENY-1 (Kanban 601)

- `probe_linked_worktree.txt` — leg A of `~/_eos/s7core52/briefs/_work/fsdeny_probe.out` (2026-11-12 20:24), byte for
  byte, ANSI kept: vitest 4 run on one test file in a detached clinical-mp worktree whose `node_modules` is a symlink to
  the checkout's. `Denied ID …/pdf.worker.min.mjs?url`, `Tests no tests`. Captured by the brief's author; vitest was not
  run against clinical-mp from this route.
- `unit_failed_to_resolve.txt` — a vitest unit run whose file imports a missing module (`Failed to resolve import`).
- `build_failed_to_resolve.txt` — a `vite build` that cannot resolve an import (`failed to resolve import`, both cases).
- `assert_quotes_denied.txt` — an assertion failure whose message quotes `Denied ID` inside a string.

The last three are product failures; none may match G-A1 (STOP (d)).
