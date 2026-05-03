# Toni Batch S6S16 — OBS-S6S14-03: B3 branches default-repo UX fix

## Repo: orchestrator
## Batch ID: s6s16-obs-s6s14-03-b3-default-repo
## Briefs: 1
## Estimated runtime: 5-10m (1-line behavioral change + smoke test)
## Spec reference: Spectricom_Pending_Canon_Updates_v1-15.md / v1-16 (OBS-S6S14-03)
## Predecessor branch: orchestrator main @ 4b2f9fa
## Predecessor surfaces: B3 stale-branch sweep CLI from S6S14 Bundle B (commits ee3d505 / 4b2f9fa)
## Fire mechanism: orchestrator with --repo orchestrator (meta_fire)
## TONI_TIMEOUT_MIN: 15

## CONTEXT

B3 introduced `branches list / branches clean` CLI in S6S14. Per spec, default repo when `--repo` is omitted should be the orchestrator's own repo (this is the orchestrator-side meta tool). Current behavior defaults to `dev-pipeline` (global default from `repos.yaml`) which is functional but UX-confusing for orchestrator-context use.

OBS-S6S14-03 captured this as a P3 nit. ~1-line fix in the CLI handler.

## GOAL

`branches list` and `branches clean` invoked WITHOUT `--repo` default to the orchestrator's own repo (`~/spectricom-orchestrator`). Explicit `--repo <name>` continues to target the named repo.

## FILES (expected)

- **Update:** `orchestrator.py` — the CLI dispatcher for `branches` subcommand (B3 introduction commits ee3d505 / 4b2f9fa)

## ACCEPTANCE CRITERIA

1. `python3 orchestrator.py branches list` (no `--repo`) operates on `~/spectricom-orchestrator`
2. `python3 orchestrator.py branches list --repo clinical-mp` continues to operate on clinical-mp (unchanged)
3. `python3 orchestrator.py branches list --repo yorsie` continues to operate on dev-pipeline/yorsie (unchanged)
4. Same default-resolution applies to `branches clean`
5. CLI help / docstring text updated to reflect new default if it currently states the old default
6. No regression in any other subcommand (run / parallel / queue / status / watch / deps) — those keep existing default-repo behavior via `set_active_repo()` at module load

## §23.14 / §29 / §31

§23.14: not applicable (no LLM in this brief).
§29: standard. Self-mod fire — should auto-merge clean via B1 self-mod path.
§31: not applicable (CLI smoke test sufficient).

## OUT OF SCOPE

- Changing global default repo in repos.yaml
- Adding new `branches` subcommands
- Touching `set_active_repo()` global initialization
- Reorganizing `branches` CLI dispatcher beyond this default

## DEFINITION OF DONE

- 1-line (or small block) behavioral change
- Commit body documents smoke test
- Auto-merges via B1 self-mod path
- Commit message: "OBS-S6S14-03: B3 branches default to orchestrator repo (S6S16)"
