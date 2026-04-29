#!/usr/bin/env python3
"""Patch orchestrator.py to add running.json for live dashboard status."""
from pathlib import Path

f = Path.home() / "spectricom-orchestrator" / "orchestrator.py"
content = f.read_text()

# 1. Add RUNNING_FILE constant after STATE_FILE
content = content.replace(
    'STATE_FILE = ORCH_DIR / "state.json"',
    'STATE_FILE = ORCH_DIR / "state.json"\nRUNNING_FILE = ORCH_DIR / "running.json"'
)

# 2. Add write/clear running functions after the fhash function
running_funcs = '''
def write_running(batch_file: Path, brief_count: int, log_file: str = ""):
    """Write running.json so dashboard knows what's executing."""
    RUNNING_FILE.write_text(json.dumps({
        "batch_file": batch_file.name,
        "briefs": brief_count,
        "started": datetime.now().isoformat(),
        "log_file": log_file
    }, indent=2))

def clear_running():
    """Remove running.json when execution completes."""
    try:
        RUNNING_FILE.unlink(missing_ok=True)
    except Exception:
        pass
'''

content = content.replace(
    'def fhash(p: Path) -> str:\n    return hashlib.md5(p.read_bytes()).hexdigest()',
    'def fhash(p: Path) -> str:\n    return hashlib.md5(p.read_bytes()).hexdigest()\n' + running_funcs
)

# 3. Wrap run_batch internals with running.json write/clear
# Replace the start of run_batch to write running.json
content = content.replace(
    '''def run_batch(batch_file: Path, worktree: Optional[Path]=None) -> Result:
    proj = worktree or PROJECT_ROOT
    started = datetime.now()
    target = proj / "yorsie" / "briefs" / batch_file.name''',
    '''def run_batch(batch_file: Path, worktree: Optional[Path]=None) -> Result:
    proj = worktree or PROJECT_ROOT
    started = datetime.now()
    briefs_preview = parse_batch(batch_file)
    write_running(batch_file, len(briefs_preview))
    try:
        return _run_batch_inner(batch_file, proj, started)
    finally:
        clear_running()

def _run_batch_inner(batch_file: Path, proj: Path, started: datetime) -> Result:
    target = proj / "yorsie" / "briefs" / batch_file.name'''
)

# 4. Update the log_file in running.json once we know it
content = content.replace(
    '    log.info(f"Firing Toni: {batch_file.name}")',
    '    # Update running.json with log file path\n'
    '    try:\n'
    '        if RUNNING_FILE.exists():\n'
    '            rd = json.loads(RUNNING_FILE.read_text())\n'
    '            rd["log_file"] = str(out_log)\n'
    '            RUNNING_FILE.write_text(json.dumps(rd, indent=2))\n'
    '    except Exception:\n'
    '        pass\n'
    '    log.info(f"Firing Toni: {batch_file.name}")'
)

f.write_text(content)
print(f"✅ Patched {f}")
print(f"   Added: RUNNING_FILE constant")
print(f"   Added: write_running() / clear_running()")
print(f"   Modified: run_batch() → writes running.json during execution")
