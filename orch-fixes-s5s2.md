# Orchestrator Fixes — ORCH-BUG-001/002/003/004
# Target: ~/spectricom-orchestrator/
# Run manually via Claude Code — NOT through the pipeline
# 4 fixes in orchestrator.py, 1 fix in orch-dashboard.py

---

## Fix 1: ORCH-BUG-001 — Brief parser counts 1 instead of actual count

**File:** orchestrator.py — `parse_batch()` function

**Problem:** The parser looks for YAML-style `id:` / `title:` fields, but our batch files use markdown `## Brief N:` headers. The regex never matches, so the fallback fires and returns 1 brief. This breaks the rate limiter count (says 1/60 instead of 6/60).

**Fix:** In the `parse_batch()` function, AFTER the existing YAML parsing block and BEFORE the `if not briefs:` fallback, add a markdown header parser:

Find this block:
```python
    for i, bid in enumerate(ids):
        # ... existing loop ...
        briefs.append(Brief(id=bid, title=title, depends_on=deps))
    if not briefs:
        briefs.append(Brief(id=filepath.stem, title=f"Batch: {filepath.name}"))
```

Replace the `if not briefs:` fallback with:
```python
    # If no YAML-style briefs found, try markdown ## Brief N: pattern
    if not briefs:
        brief_pat = re.compile(r'^## Brief (\d+)[:\s—–\-]+\s*(.+)', re.MULTILINE)
        matches = brief_pat.findall(content)
        for num, title in matches:
            briefs.append(Brief(id=f"brief-{num}", title=title.strip()[:80]))

    # Final fallback: count as single batch
    if not briefs:
        briefs.append(Brief(id=filepath.stem, title=f"Batch: {filepath.name}"))
```

**Verify:** `python3 -c "from orchestrator import parse_batch; from pathlib import Path; print(len(parse_batch(Path('/home/gkassa/spectricom-dev-pipeline/yorsie/briefs/toni-batch-pi2s5-39.md'))))"` should print 3, not 1.

---

## Fix 2: ORCH-BUG-002 — Show batch summary even with --approve

**File:** orchestrator.py — `approval_gate()` function

**Problem:** With `--approve`, the function returns True immediately with just a one-line log. George never sees what's about to fire (brief list, rate status, deps). The interactive prompt exists but George always uses `--approve` because that's what the fire commands include.

**Fix:** In the `approval_gate()` function, replace the `if approve:` block:

Find:
```python
    if approve:
        log.info("✅ Pre-approved via --approve flag")
        # Still check deps unless --skip-deps
        if not skip_deps:
            all_met, met, unmet = check_batch_deps(batch_file)
            if not all_met:
                log.error(f"⛔ Unmet dependencies: {unmet}")
                log.error(f"   Use --skip-deps to override")
                return False
        return True
```

Replace with:
```python
    if approve:
        # Show summary even when pre-approved
        print(f"\n{'━'*60}")
        print(f"  ✅ PRE-APPROVED (--approve)")
        print(f"{'━'*60}")
        print(f"  Batch:      {batch_file.name}")
        print(f"  Briefs:     {len(briefs)}")
        for b in briefs:
            dep = f"  ← deps: {b.depends_on}" if b.depends_on else ""
            print(f"    • {b.id}: {b.title}{dep}")

        # Dependency check
        if not skip_deps:
            all_met, met, unmet = check_batch_deps(batch_file)
            if not all_met:
                print(f"  Deps:       ❌ UNMET — {unmet}")
                print(f"\n  ⛔ BLOCKED by unmet dependencies. Use --skip-deps to override.")
                print(f"{'━'*60}\n")
                return False
            elif met:
                print(f"  Deps:       ✅ All met — {met}")

        # Rate check display
        ok, msg = rate_limiter.pre_flight(len(briefs))
        print(f"  Rate:       {msg}")
        print(f"  Timeout:    {TONI_TIMEOUT // 60}m")
        print(f"{'━'*60}")
        log.info("✅ Pre-approved via --approve flag")
        return True
```

---

## Fix 3: ORCH-BUG-003 — Dashboard shows per-brief progress from log parsing

**File:** orch-dashboard.py — `get_git_progress()` function

**Problem:** Progress tracking relies on git commits, but Toni doesn't commit per-brief. So progress always shows "Working on brief 1/1... (5 files changed)" at 10%. Need to parse the Toni log file for brief completion markers.

**Fix:** Add a `get_brief_progress()` function and integrate it into `get_git_progress()`.

Add this new function BEFORE `get_git_progress()`:

```python
def get_brief_progress():
    """Parse the active Toni log to detect per-brief progress."""
    running = get_running()
    if not running:
        return {"completed_briefs": 0, "current_brief": None, "brief_names": []}

    log_file = running.get("log_file", "")
    if not log_file or not Path(log_file).exists():
        return {"completed_briefs": 0, "current_brief": None, "brief_names": []}

    try:
        content = Path(log_file).read_text(errors="replace")

        # Count completed briefs by looking for common patterns Toni outputs
        # Patterns: "## Brief N", "Brief N:", "### Brief N", completion markers
        import re
        brief_starts = re.findall(r'(?:^|\n)\s*#{1,3}\s*Brief\s+(\d+)', content)
        completed_markers = re.findall(r'(?:Brief \d+.*?(?:complete|done|finished|✅|PASS))', content, re.IGNORECASE)

        # Also look for file modification patterns as proxy
        file_writes = re.findall(r'(?:Created|Modified|Updated|Wrote)\s+(\S+\.(?:tsx?|sql|css))', content, re.IGNORECASE)

        current = None
        if brief_starts:
            current = f"Brief {brief_starts[-1]}"

        return {
            "completed_briefs": len(completed_markers),
            "current_brief": current,
            "brief_names": list(dict.fromkeys(brief_starts)),  # unique, ordered
            "files_touched": list(dict.fromkeys(file_writes))[-10:]
        }
    except Exception:
        return {"completed_briefs": 0, "current_brief": None, "brief_names": []}
```

Then in the FIRST `get_git_progress()` function (note: there are two duplicate definitions — delete the second one), update the progress calculation section. Find:

```python
    # Progress percentage
    expected = result["expected_briefs"]
    if expected > 0 and result["commit_count"] > 0:
        result["progress_pct"] = min(100, round(result["commit_count"] / expected * 100))
    elif result["modified_count"] > 0:
        result["progress_pct"] = 10  # at least started
```

Replace with:
```python
    # Progress percentage — use brief progress from log parsing
    bp = get_brief_progress()
    expected = result["expected_briefs"]
    if bp["completed_briefs"] > 0 and expected > 0:
        result["progress_pct"] = min(100, round(bp["completed_briefs"] / expected * 100))
    elif expected > 0 and result["commit_count"] > 0:
        result["progress_pct"] = min(100, round(result["commit_count"] / expected * 100))
    elif result["modified_count"] > 0:
        result["progress_pct"] = 10  # at least started
```

Also update the "Infer current state" section. Find:
```python
    # Infer current state
    if result["commit_count"] >= expected and expected > 0:
        result["current_brief"] = "Finishing up..."
    elif result["commit_count"] == 0 and result["modified_count"] > 0:
        result["current_brief"] = f"Working on brief 1/{expected}... ({result['modified_count']} files changed)"
    elif result["commit_count"] > 0:
        result["current_brief"] = f"Brief {result['commit_count']}/{expected} committed. Working on next..."
```

Replace with:
```python
    # Infer current state from log parsing + git
    if bp["current_brief"] and expected > 0:
        done = bp["completed_briefs"]
        result["current_brief"] = f"Working on {bp['current_brief']}/{expected}... ({result['modified_count']} files changed)"
        if done > 0:
            result["current_brief"] = f"{bp['current_brief']}/{expected} in progress ({done} done, {result['modified_count']} files)"
    elif result["commit_count"] >= expected and expected > 0:
        result["current_brief"] = "Finishing up..."
    elif result["modified_count"] > 0:
        result["current_brief"] = f"Working... ({result['modified_count']} files changed)"
```

**Also:** Delete the second duplicate `get_git_progress()` function definition. The file has it defined twice — remove the entire second copy (the one starting around line 200+).

---

## Fix 4: ORCH-BUG-004 — Auto branch creation + commit on completion

**File:** orchestrator.py — `run_batch()` and `_run_batch_inner()` functions

**Problem:** All batches run directly on `main` with no branch isolation. Batches 37/38/39 all stacked uncommitted changes on main. D-148 requires feature branches per batch.

**Fix:** Add git branch creation before firing and auto-commit after success.

In `_run_batch_inner()`, add branch creation BEFORE `fire_toni()` and auto-commit AFTER. Find:

```python
def _run_batch_inner(batch_file: Path, proj: Path, started: datetime, worktree=None) -> Result:
    target = proj / "yorsie" / "briefs" / batch_file.name
    if not batch_file.is_relative_to(proj):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(batch_file.read_bytes())
        log.info(f"Copied brief to {target}")
    briefs = parse_batch(batch_file)
    mig_before = get_migrations()
    ec, out_log = fire_toni(target, proj)
```

Replace with:
```python
def _run_batch_inner(batch_file: Path, proj: Path, started: datetime, worktree=None) -> Result:
    target = proj / "yorsie" / "briefs" / batch_file.name
    if not batch_file.is_relative_to(proj):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(batch_file.read_bytes())
        log.info(f"Copied brief to {target}")
    briefs = parse_batch(batch_file)

    # Auto branch creation (D-148) — skip if using worktrees
    branch_name = None
    if worktree is None:
        branch_name = f"orch-{batch_file.stem}"
        try:
            r = subprocess.run(
                f"git checkout -b {branch_name}",
                shell=True, capture_output=True, text=True, cwd=str(proj)
            )
            if r.returncode == 0:
                log.info(f"🌿 Branch: {branch_name}")
            else:
                # Branch may already exist — try switching to it
                r2 = subprocess.run(
                    f"git checkout {branch_name}",
                    shell=True, capture_output=True, text=True, cwd=str(proj)
                )
                if r2.returncode == 0:
                    log.info(f"🌿 Switched to existing branch: {branch_name}")
                else:
                    log.warning(f"⚠️ Could not create/switch branch: {r.stderr.strip()}. Running on current branch.")
                    branch_name = None
        except Exception as e:
            log.warning(f"⚠️ Branch creation failed: {e}. Running on current branch.")
            branch_name = None

    mig_before = get_migrations()
    ec, out_log = fire_toni(target, proj)
```

Then, after the Playwright check and before the `Result` construction, add auto-commit + merge. Find:

```python
    pw_ok, pw_cnt = (None, 0)
    if RUN_PLAYWRIGHT and ec == 0 and worktree is None:
        pw_ok, pw_cnt = run_playwright()
        if not pw_ok: status = Status.FAILED
    result = Result(batch_file=batch_file.name, status=status,
```

Replace with:
```python
    pw_ok, pw_cnt = (None, 0)
    if RUN_PLAYWRIGHT and ec == 0 and worktree is None:
        pw_ok, pw_cnt = run_playwright()
        if not pw_ok: status = Status.FAILED

    # Auto-commit + merge back to main (D-148)
    if branch_name and worktree is None:
        try:
            if status == Status.PASSED:
                # Commit all changes on feature branch
                subprocess.run("git add -A", shell=True, cwd=str(proj), capture_output=True)
                commit_msg = f"fix: {batch_file.stem} — {len(briefs)} briefs"
                r = subprocess.run(
                    f'git commit -m "{commit_msg}" --allow-empty',
                    shell=True, capture_output=True, text=True, cwd=str(proj)
                )
                if r.returncode == 0:
                    log.info(f"📦 Committed: {commit_msg}")
                else:
                    log.warning(f"⚠️ Commit failed: {r.stderr.strip()}")

                # Merge back to main
                subprocess.run("git checkout main", shell=True, capture_output=True, cwd=str(proj))
                r = subprocess.run(
                    f"git merge {branch_name} --no-edit",
                    shell=True, capture_output=True, text=True, cwd=str(proj)
                )
                if r.returncode == 0:
                    log.info(f"🔀 Merged {branch_name} → main")
                    # Clean up feature branch
                    subprocess.run(f"git branch -d {branch_name}", shell=True, capture_output=True, cwd=str(proj))
                else:
                    log.error(f"⚠️ Merge conflict on {branch_name} — MANUAL RESOLUTION NEEDED")
                    log.error(f"   {r.stderr.strip()}")
            else:
                # Failed batch — switch back to main, leave branch for inspection
                subprocess.run("git checkout main", shell=True, capture_output=True, cwd=str(proj))
                log.warning(f"⚠️ Batch failed — branch {branch_name} left for inspection")
        except Exception as e:
            log.warning(f"⚠️ Git automation error: {e}")
            # Ensure we're back on main
            subprocess.run("git checkout main", shell=True, capture_output=True, cwd=str(proj))

    result = Result(batch_file=batch_file.name, status=status,
```

---

## Verification

After applying all fixes, test with:

```bash
cd ~/spectricom-orchestrator && python3 -c "
from orchestrator import parse_batch
from pathlib import Path
briefs = parse_batch(Path('/home/gkassa/spectricom-dev-pipeline/yorsie/briefs/toni-batch-pi2s5-39.md'))
print(f'Brief count: {len(briefs)}')
for b in briefs:
    print(f'  {b.id}: {b.title}')
"
```

Expected output: 3 briefs, not 1.

Then restart the dashboard:
```bash
bash ~/spectricom-orchestrator/startup.sh stop && bash ~/spectricom-orchestrator/startup.sh start
```

---
# END
