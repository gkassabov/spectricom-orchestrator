# Bundle B — S6S16 Cleanup (D-CANDIDATE captures + OBS-S6S16 fixes)

**Authored:** S6S16 (May 4, 2026)
**Status:** Staged for fire — not yet executed
**Owner:** Gemma + George approval gate before each fire

This bundle contains **8 deliverables** in 3 categories:

| # | Deliverable | Type | Target | Fire mechanism |
|---|---|---|---|---|
| B1 | D-361 promotion capture | Canon-only | Pending_Canon_Updates | Manual edit |
| B2 | D-363 promotion capture | Canon-only | Pending_Canon_Updates | Manual edit |
| B3 | D-364 promotion capture | Canon-only | Pending_Canon_Updates | Manual edit |
| B4 | D-365 promotion capture | Canon-only | Pending_Canon_Updates | Manual edit |
| B5 | D-367 promotion capture | Canon-only | Pending_Canon_Updates | Manual edit |
| B6 | OBS-S6S16-01 fix (orchestrator empty-commit) | Code brief | spectricom-orchestrator | Toni fire |
| B7 | OBS-S6S16-02 note (audit row on direct-SQL pw rotation) | Canon-only | Pending_Canon_Updates | Manual edit |
| B8 | OBS-S6S16-03 fix (cherry-pick + Toni guard) | Process doc | Gemma_System_Prompt §X | Manual edit |

**Critical:** B1–B5 do NOT promote the D-CANDIDATEs unilaterally. They author the capture entries that will land in canon **once Dr. K performs her enriched-synth walkthrough and confirms** (per S6S15 close: "deferred to Dr. K re-walkthrough on enriched synth"). The captures are ready-to-promote text, gated by Dr. K nod. The handoff lock these to next session post-Mitchell-rerun + Dr. K turn.

---

## B1–B5: D-CANDIDATE Promotion Captures

The 5 D-CANDIDATEs are gated as a single group on Dr. K's enriched-synth walkthrough. Authoring all 5 capture entries together for atomic update.

### B1: D-361 — Pattern B + 3-Layer Architecture (LOCK on Dr. K nod)

```markdown
### D-361 — Pattern B + 3-Layer Architecture Model — LOCKED at S6S16 (post Dr. K enriched-synth walkthrough)

**Promoted from CANDIDATE → LOCKED on:** [DATE Dr. K confirms]
**Walkthrough commit:** [Mitchell rerun report at synth-feedback/walkthrough-mitchell-pcp-*.md]

The Pattern B + 3-Layer architecture model (Encounter compose at top, sectional editing in middle, ambient suggestions cap at bottom) is the canonical structure for all clinical surfaces from S6S16 forward. Phases 5.2 (pre-visit), 5.3 (finalize), and Home reinforcement all conform. Future surfaces (lab review, refill management, message triage) MUST adopt the same pattern unless an explicit per-surface deviation is approved.

**Operationalization:** Existing surfaces (Phase 2/3/4/5/Home) need no rework. New surfaces use Pattern B as default; deviations require D-number for justification.
```

### B2: D-363 — Command Center Merge Thesis (LOCK on Dr. K nod)

```markdown
### D-363 — Command Center Merge Thesis — LOCKED at S6S16

**Promoted from CANDIDATE → LOCKED on:** [DATE Dr. K confirms]

Home is the post-login Command Center, NOT a separate surface. The 5-section Home (Up Next + Today's schedule + Inbox + Outreach + End-of-day) is the canonical landing. /Schedule, /Patient/{id}, /Inbox/* are subordinate surfaces accessed via Home rows.

**Operationalization:** TopMainNav nav order: Home (default) → Schedule → Patients → Inbox. /Schedule is the calendar surface; Home is the action surface.
```

### B3: D-364 — Phase 4 SOAP Clinical Structure (LOCK on Dr. K nod)

```markdown
### D-364 — Phase 4 SOAP Clinical Structure — LOCKED at S6S16

**Promoted from CANDIDATE → LOCKED on:** [DATE Dr. K confirms]

SOAP note is the canonical clinical structure for encounter documentation. Subjective / Objective / Assessment / Plan as four distinct editable sections, each with AI-draft + per-item Confirm/Remove + section-level Import all + global Sign and lock. Pre-visit phase (5.2) and Finalize phase (5.3) wrap around the SOAP core.

**Operationalization:** D-368 (FHIR-shaped LLMProvider input) is the typing convention for SOAP draft methods; e.g., `provider.draftAssessment({ encounter, patient, conditions, medicationRequests })`.
```

### B4: D-365 — Suggestions Cap + Dismissal Modes (LOCK on Dr. K nod)

```markdown
### D-365 — Suggestions Cap + Dismissal Modes — LOCKED at S6S16

**Promoted from CANDIDATE → LOCKED on:** [DATE Dr. K confirms]

AI suggestions are capped at 3 per section. Three dismissal modes available per suggestion:
- `accept-all` — accept this suggestion, do not learn
- `dismiss-this-visit` — hide for current encounter, do not learn
- `dismiss-train-globally` — hide and feed to Mini-Me-of-clinician training loop

The dismiss-train-globally signal is the foundation for personalized learning. Per-clinician Mini-Me will reduce suggestion frequency on patterns the clinician repeatedly dismisses.

**Operationalization:** Dismissal events recorded as `Observation` resources with `category=clinician-feedback`, `code=suggestion-dismissed`, `valueString={mode}`, `subject={patient}`, `performer={clinician}`. Mini-Me ingestion via existing Bridge fetch (D-369 pull-on-encounter-open).
```

### B5: D-367 — Home as Post-Login Landing (LOCK on Dr. K nod)

```markdown
### D-367 — Home as Post-Login Landing — LOCKED at S6S16

**Promoted from CANDIDATE → LOCKED on:** [DATE Dr. K confirms Home is preferred landing surface]

Home is the post-login default route. TopMainNav `Dashboard` renamed `Home`. Single-column 5-section vertical scan. Fixture+real FHIR mix per S5S40 brief.

**Operationalization:** `useDefaultRoute` hook returns `/` (Home) for authenticated clinicians. Login redirect → Home, not /Dashboard.
```

**B1–B5 fire:** Single edit to `Spectricom_Pending_Canon_Updates_v1-17.md` adding all 5 capture sections with `[DATE Dr. K confirms]` placeholder. Date filled in at promotion session (S6S17 or later).

---

## B6: OBS-S6S16-01 — Orchestrator Empty-Commit Fix

### Repo: spectricom-orchestrator

### Brief: `toni-batch-s6s16-obs-s6s16-01-empty-commit-guard.md`

### Timeout: 15m

### CONTEXT

S6S16 HARNESS-FIX-01 fired three times (paste loop on bracket-mangled filename), producing two empty marker commits (`7284956c`, `c7079647`, `15c63e2c`) on top of the real fix at `a26c1f66`. Cause: orchestrator's `git commit --allow-empty` flag (orchestrator.py L1075) creates a marker even when Toni produced no diff.

Original intent of `--allow-empty` was likely audit-trail (every fire = visible commit). But empty markers create noise and confuse reconciliation: a green `passed | 1 briefs | 178s` log message accompanied by zero file changes is misleading.

### GOAL

Replace blanket `--allow-empty` with conditional: commit if and only if the working tree has staged changes after `git add -A`. If empty, log a clear warning and skip the commit (still merge nothing back, which becomes a no-op).

### FILES

- `orchestrator.py` lines 1067–1090 (post-Toni commit + merge block)
- Add unit test or smoke test covering the no-change path

### ACCEPTANCE CRITERIA

1. After Toni runs and exits 0 with no file changes, orchestrator does NOT create an empty commit.
2. Log emits explicit warning: `⚠️ Toni produced no changes — skipping commit (this is usually a re-fire of an idempotent brief or a halt-and-report)`.
3. Toni runs that DO produce file changes commit normally (no regression).
4. Merge step gracefully no-ops when there's nothing to merge (current branch == merge target after no-commit path).
5. Status string in final summary distinguishes "passed-with-changes" from "passed-no-changes".
6. Existing tests pass.

### IMPLEMENTATION SKETCH

```python
# Replace L1072-1078 region with:
subprocess.run("git add -A", shell=True, cwd=str(proj), capture_output=True)
diff_check = subprocess.run(
    "git diff --cached --quiet",
    shell=True, capture_output=True, cwd=str(proj)
)
has_changes = diff_check.returncode != 0  # exit 1 means there ARE staged changes

if has_changes:
    commit_msg = f"fix: {batch_file.stem} — {len(briefs)} briefs"
    r = subprocess.run(
        f'git commit -m "{commit_msg}"',  # NO --allow-empty
        shell=True, capture_output=True, text=True, cwd=str(proj)
    )
    if r.returncode == 0:
        log.info(f"📦 Committed: {commit_msg}")
    else:
        log.warning(f"⚠️ Commit failed: {r.stderr.strip()}")
else:
    log.warning(
        "⚠️ Toni produced no changes — skipping commit "
        "(usually means idempotent re-fire or halt-and-report). "
        f"Branch {branch_name} will be deleted clean."
    )
    # Subsequent merge becomes no-op; cleanup branch
    subprocess.run(f"git checkout {MERGE_TARGET}", shell=True, capture_output=True, cwd=str(proj))
    subprocess.run(f"git branch -D {branch_name}", shell=True, capture_output=True, cwd=str(proj))
    return Status.PASSED_NO_CHANGES  # new status enum
```

### OUT OF SCOPE

- Detecting and merging duplicate idempotent commits (separate problem, OBS-S6S16-04 candidate).
- Running diagnostics on WHY Toni produced no changes (could be idempotent brief, could be halt-and-report; CLI doesn't distinguish).

### DEFINITION OF DONE

- Test fires of an already-applied brief produce zero new commits on main.
- Test fires of a brand-new brief produce one commit (unchanged behavior).
- Status enum `PASSED_NO_CHANGES` shipped (or equivalent string).
- Commit msg: `OBS-S6S16-01: Conditional commit — no empty markers (S6S16)`.

---

## B7: OBS-S6S16-02 — Audit Row on Direct-SQL Password Rotation

### Type: Canon-only note (no Toni fire)

### Target: `Spectricom_Pending_Canon_Updates_v1-17.md` and `clinical-mp/docs/dev-setup-medplum.md`

```markdown
### OBS-S6S16-02 — Direct-SQL password rotation skips User_History audit row

**Date:** S6S16 May 4, 2026
**Severity:** P3 (E1 dev only)
**Triggered by:** S6S16 password rotation to `Dani2002` for `dev-admin@spectricom.local` and `dani@spectricom.com`

**Problem:** Medplum's `setPassword` API path is gated behind a `UserSecurityRequest` (forgot-password flow). For E1 dev rotation, raw SQL `UPDATE "User" SET content = jsonb_set(...)` is the practical path. This succeeds at login but skips the `User_History` audit row that Medplum's app-level write path would have appended.

**Impact for E1:** None. Login works. Audit trail has a one-version gap.

**Impact for E2/E3 (staging/prod):** Direct-SQL rotation must NOT be used. All password mutations must go through Medplum admin API or a script that writes both `User` and `User_History` (and bumps `versionId` consistently across both).

**Mitigation now:** Standing rule — direct SQL on `User.content.passwordHash` is **E1-only**. For E2+, use Medplum admin API (`/admin/projects/{id}/users/{userId}/password` PUT) or `setPassword` with a programmatically-generated `UserSecurityRequest`.

**Promotes to:** D-370 (E1 dev credential mutation policy) on first staging deployment if pattern recurs.
```

---

## B8: OBS-S6S16-03 — Cherry-Pick + Toni Write Guard (Process Rule)

### Type: Process doc (Gemma System Prompt update)

### Target: `Gemma_System_Prompt_v5-25.md` — new §35 or amendment to §32

```markdown
### §35 — WIP Branch + Toni Brief Same-File Guard

**When:** A prep branch (e.g., `s6s16-prep`) holds WIP scaffolding (uncompleted commit) AND a brief queued for the same files is about to fire.

**Rule:** Do NOT cherry-pick or merge the WIP onto main before firing the brief. Toni branches from `MERGE_TARGET` (main) and orchestrator merges back. If WIP is on main already AND Toni writes the same files, the orchestrator merge collides — manual resolution required.

**Right path:**
1. Leave WIP on prep branch.
2. Fire brief from main (orchestrator branches off main, ignores prep branch entirely).
3. Toni produces full implementation, including the WIP scaffolding pieces.
4. Orchestrator merges back clean.
5. Discard prep branch (or rebase for archival).

**Wrong path (caused S6S16 conflict in CONFIG-01):**
1. Cherry-pick WIP onto main → main now has scaffolding.
2. Fire brief from main → Toni writes the scaffolding files anew.
3. Toni's branch and main diverge on the same files → merge conflict.
4. Manual `git checkout --theirs` to take Toni's version → resolved, but cherry-pick was wasted work.

**Detection:** Before any `git cherry-pick` from prep onto main, ask: "Is there a brief queued that touches any of these same files?" If yes → don't cherry-pick. If no → safe to cherry-pick.

**Reference:** S6S16 CONFIG-01 (commit `6568b61` + merge `86a5312`) for the conflict pattern.
```

---

## Bundle B Fire Order Summary

| # | Deliverable | Where | Action |
|---|---|---|---|
| **First** | B1–B5 + B7 + B8 | OneDrive canon docs | Single editorial pass — Gemma writes Pending Canon entries with placeholders for Dr. K date, plus §35 amendment. **No Toni fire required.** |
| **Second** | B6 | spectricom-orchestrator repo | Author standalone Toni brief (this doc serves as input spec). Place at `~/spectricom-orchestrator/briefs/toni-batch-s6s16-obs-s6s16-01-empty-commit-guard.md`. Fire after current SD5a/b/c/d clear. |
| **Third** | D-CANDIDATE LOCK | OneDrive canon | At Dr. K walkthrough completion (S6S17 or later), fill in dates and replace `[DATE Dr. K confirms]` with actual confirmation date. Move from Pending Canon → Logs delta + Section 1.10. |

End Bundle B authoring spec.
