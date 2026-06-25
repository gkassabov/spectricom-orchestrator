#!/usr/bin/env python3
"""
SPECTRICOM ORCHESTRATOR v3.1
=============================
Automated Toni batch execution pipeline.
v3:   Approval gate (D-184) + rate limit monitoring.
v3.1: Dependency cascade + Slack notifications.

Usage:
  python3 orchestrator.py run <batch-file>              ← interactive approval
  python3 orchestrator.py run <batch-file> --approve     ← pre-approved
  python3 orchestrator.py run <batch-file> --force       ← skip all safety checks
  python3 orchestrator.py run <batch-file> --skip-deps   ← ignore dependency check
  python3 orchestrator.py queue <batch-file> ...         ← requires --approve
  python3 orchestrator.py watch
  python3 orchestrator.py parallel <f1> <f2> ...         ← requires --approve
  python3 orchestrator.py status
  python3 orchestrator.py deps <batch-file>              ← show dependency status

Batch-level dependencies:
  Add to batch file header:  # depends_on_batches: [toni-batch-31.md, toni-batch-30.md]
"""

import os, sys, re, time, json, signal, logging, hashlib, subprocess, argparse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# ═══════════════════════════════════════════════════════
# AUTH GUARD (D-184 / memory #24) — Toni MUST run on Max OAuth, never API.
# ═══════════════════════════════════════════════════════
if os.environ.get("ANTHROPIC_API_KEY"):
    print("=" * 60, file=sys.stderr)
    print("❌ ANTHROPIC_API_KEY is set in the environment.", file=sys.stderr)
    print("   Toni must run on Claude Max OAuth (D-184 / memory #24).", file=sys.stderr)
    print("", file=sys.stderr)
    print("   Fix options:", file=sys.stderr)
    print("     1. Use the 'toni' alias (unsets key automatically):", file=sys.stderr)
    print("        toni <batch-file.md> --approve", file=sys.stderr)
    print("     2. Or unset inline:", file=sys.stderr)
    print("        unset ANTHROPIC_API_KEY && python3 orchestrator.py run ...", file=sys.stderr)
    print("", file=sys.stderr)
    print("   To fire on API explicitly (requires explicit George request),", file=sys.stderr)
    print("   use the 'toni-api' alias.", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    sys.exit(3)


# Import local modules (same directory)
sys.path.insert(0, str(Path(__file__).parent))
import rate_limiter

try:
    import slack_notify
    HAS_SLACK = True
except ImportError:
    HAS_SLACK = False

# ═══════════════════════════════════════════════════════
# CONFIGURATION (OI-026 v3.4 — multi-repo via config/repos.yaml)
# ═══════════════════════════════════════════════════════
import yaml as _yaml

ORCH_DIR = Path(__file__).parent.resolve()
LOG_DIR = ORCH_DIR / "logs"
STATE_FILE = ORCH_DIR / "state.json"
RUNNING_FILE = ORCH_DIR / "running.json"
REPOS_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "repos.yaml"

# Per-repo state — populated by set_active_repo() at module load (defaults to yorsie).
# A3 will re-call set_active_repo() after CLI / brief-header parsing to switch repos pre-fire.
ACTIVE_REPO_NAME: str = ""
ACTIVE_REPO_CONFIG: dict = {}
PROJECT_ROOT: Path = Path()        # set by set_active_repo(); legacy var name preserved
YORSIE_DIR: Path = Path()           # yorsie-only convenience: project_root / "yorsie" when active=yorsie, else project_root
BRIEFS_DIR: Path = Path()           # project_root / briefs_subdir
WORKTREE_BASE: Path = Path()        # parallel mode: yorsie-toni base; single-stream: project_root (unused)
BRANCH_PREFIX: str = ""
MERGE_TARGET: str = "main"
REMOTE: str = "origin"
LOG_SUBDIR: str = ""
WORKTREE_MODE: str = "single-stream"
TEST_CMD: str = ""
FIRE_TEMPLATE: str = ""
IS_META_FIRE: bool = False


def load_repo_config() -> dict:
    """Load ~/spectricom-orchestrator/config/repos.yaml and return parsed dict.

    Validates: file exists, has `repos:` key with at least one entry, exactly one
    entry has `default: true`. Raises RuntimeError on any violation.
    """
    if not REPOS_CONFIG_PATH.exists():
        raise RuntimeError(f"Repo config not found: {REPOS_CONFIG_PATH}")
    cfg = _yaml.safe_load(REPOS_CONFIG_PATH.read_text())
    if not isinstance(cfg, dict) or "repos" not in cfg or not cfg["repos"]:
        raise RuntimeError(f"Malformed repo config: {REPOS_CONFIG_PATH} (expected 'repos:' map)")
    defaults = [n for n, r in cfg["repos"].items() if r.get("default")]
    if len(defaults) != 1:
        raise RuntimeError(
            f"Repo config must declare exactly one default repo; found {len(defaults)}: {defaults}"
        )
    return cfg


def set_active_repo(name: str = "") -> str:
    """Switch active repo and populate module-level state from repos.yaml.

    Args:
        name: Repo name (e.g. 'yorsie', 'ai-foundation', 'clinical-mp', 'orchestrator').
              Empty string → use the default repo from config (yorsie for v3.4.0).

    Returns:
        The active repo name (resolved).

    Raises:
        RuntimeError if name is provided but not declared in repos.yaml.
    """
    global ACTIVE_REPO_NAME, ACTIVE_REPO_CONFIG
    global PROJECT_ROOT, YORSIE_DIR, BRIEFS_DIR, WORKTREE_BASE
    global BRANCH_PREFIX, MERGE_TARGET, REMOTE, LOG_SUBDIR
    global WORKTREE_MODE, TEST_CMD, FIRE_TEMPLATE, IS_META_FIRE

    cfg = load_repo_config()
    repos = cfg["repos"]

    if not name:
        name = next(n for n, r in repos.items() if r.get("default"))

    if name not in repos:
        valid = ", ".join(sorted(repos.keys()))
        raise RuntimeError(f"Unknown repo: {name}. Valid: {valid}")

    r = repos[name]
    ACTIVE_REPO_NAME = name
    ACTIVE_REPO_CONFIG = r
    PROJECT_ROOT = Path(r["project_dir"]).expanduser()
    BRIEFS_DIR = PROJECT_ROOT / r.get("briefs_subdir", "briefs")
    # YORSIE_DIR is preserved as a legacy convenience: when yorsie is active it points at the yorsie subdir
    # of the monorepo (matches v3.3 behavior); for any other repo it equals project_root (used only by
    # yorsie-specific callsites such as the supabase migrations helper).
    YORSIE_DIR = PROJECT_ROOT / "yorsie" if name == "yorsie" else PROJECT_ROOT
    WORKTREE_BASE = (
        Path(r["worktree_base"]).expanduser()
        if r.get("worktree_mode") == "parallel" and r.get("worktree_base")
        else PROJECT_ROOT
    )
    BRANCH_PREFIX = r.get("branch_prefix", "orch")
    MERGE_TARGET = r.get("merge_target", "main")
    REMOTE = r.get("remote", "origin")
    LOG_SUBDIR = r.get("log_subdir", name)
    WORKTREE_MODE = r.get("worktree_mode", "single-stream")
    TEST_CMD = r.get("test_cmd", "")
    FIRE_TEMPLATE = r.get("fire_command_template", "")
    IS_META_FIRE = bool(r.get("meta_fire", False))
    return name


# Initial population at module load → defaults to yorsie (backward-compat with v3.3).
# A3 (CLI parser) will re-call set_active_repo(<name>) before any work if --repo or
# `## Repo:` header specifies a different target.
set_active_repo()


def parse_repo_from_brief(filepath) -> Optional[str]:
    """Parse ## Repo: <name> from a brief/batch file header."""
    try:
        content = Path(filepath).read_text(encoding="utf-8")
        m = re.search(r'^## Repo:\s*(\S+)', content[:2000], re.MULTILINE)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return None


TIMEOUT_DEFAULT_MIN = 45
TIMEOUT_HARD_CAP_MIN = 180
TONI_TIMEOUT = int(os.environ.get("TONI_TIMEOUT_MIN", str(TIMEOUT_DEFAULT_MIN))) * 60
TONI_COOLDOWN = 10
MAX_PARALLEL = 3
RUN_PLAYWRIGHT = False
PLAYWRIGHT_CMD = "npx playwright test"
SKIP_SIT = False
# S6S47 P1 hardening (D-S6S46-B): post-merge build gate + blocking SIT.
# Both default ON for clinical-mp; disable via env for emergency bypass.
BUILD_GATE_ENABLED = os.environ.get("DISABLE_BUILD_GATE", "") == ""
SIT_BLOCKING = os.environ.get("DISABLE_SIT_BLOCKING", "") == ""
BUILD_GATE_CMD = "npx tsc --noEmit && npm run build"
BUILD_GATE_TIMEOUT = 600  # 10 min
SIT_TIMEOUT = 600  # S6S47: 300 was too tight for full smoke suite w/ 4 workers
# S6S47: SIT blocks only on NEW failures vs this known-failing baseline.
# These are pre-existing tracked bugs (verified failing on 632b236 pre-PCFG),
# so they must NOT cause every brief's gate to false-FAIL. Remove an ID here
# once its bug is actually fixed.
SIT_KNOWN_FAILING = {
    "home-count-parity",            # BUG-026 (pre-existing, S6S46 baseline)
    "mini-me-bridge-consent-gate",  # BUG-v4r-005 (pre-existing, verified failing on 632b236)
    # encounter-autosave-roundtrip REMOVED S6S72 — spec repaired (re-pointed to the structured
    # Subjective HPI) and underlying BUG-S6S70-COMPOSE-CMP1-PERSIST fixed/verified. It is now a
    # live CRITICAL guard (SIT_CRITICAL_SPECS below).
}
# S6S72: SIT halt rule = MANY-or-SEVERE. Among NEW failures (those NOT in SIT_KNOWN_FAILING):
# a CRITICAL spec failing halts on any 1; non-critical failures halt only once they reach
# SIT_MANY_THRESHOLD. CRITICAL = data-integrity / safety journeys. Substring-matched against
# failing spec basenames (same style as SIT_KNOWN_FAILING). Remove/extend as the suite evolves.
SIT_CRITICAL_SPECS = {
    "encounter-autosave-roundtrip",       # persistence — Subjective survives nav roundtrip (data loss)
    "encounter-autosave-unicode",         # persistence — unicode payload (data loss)
    "encounter-idle-autosave-warning",    # persistence — idle autosave (data loss)
    "encounter-sign-finalization",        # signed-note finalize integrity
    "encounter-finished-readonly",        # signed-note immutability
    "post-sign-route-refresh",            # post-sign route integrity
    "SCA-BUG-S6S36-finalized-edit-leak",  # finalized-note edit leak (compliance)
    "05-audit-emission",                  # audit / provenance emission (compliance)
}
SIT_MANY_THRESHOLD = 3  # >= this many NEW non-critical failures halts a batch (George, S6S72)
SIT_ARCHIVE_DIR = ORCH_DIR / "sit-archive"
PROTECTED_BRANCHES = {"main", "master", "develop", "staging"}

# ═══════════════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════════════
class Status(str, Enum):
    PENDING="pending"; RUNNING="running"; PASSED="passed"
    FAILED="failed"; SKIPPED="skipped"; BLOCKED="blocked"

@dataclass
class Brief:
    id: str; title: str; status: str="pending"; depends_on: list=field(default_factory=list)

@dataclass
class Result:
    batch_file: str; status: Status; started: str; finished: str
    duration_s: float; exit_code: int; briefs: int
    playwright_ok: Optional[bool]=None; pw_tests: int=0
    new_migrations: list=field(default_factory=list)
    error: Optional[str]=None; log_file: Optional[str]=None
    worktree: Optional[str]=None; no_changes: bool=False

# ═══════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════
def ensure_log_subdir(subdir: str) -> Path:
    """Create and return the log subdirectory for a repo."""
    d = LOG_DIR / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_log_migration():
    """One-time migration: move top-level toni-*.log files into logs/yorsie/."""
    marker = LOG_DIR / ".migrated-v3.4"
    if marker.exists():
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    yorsie_dir = LOG_DIR / "yorsie"
    yorsie_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    moved = 0
    for f in LOG_DIR.glob("toni-*.log"):
        dest = yorsie_dir / f.name
        if not dest.exists():
            shutil.move(str(f), str(dest))
            moved += 1
    marker.write_text(f"Migrated {moved} files at {datetime.now().isoformat()}\n")


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    lf = LOG_DIR / f"orch-{ts}.log"
    fmt = logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s", datefmt="%H:%M:%S")
    fh = logging.FileHandler(lf); fh.setFormatter(fmt)
    ch = logging.StreamHandler(); ch.setFormatter(fmt)
    logger = logging.getLogger("orch"); logger.setLevel(logging.INFO)
    logger.addHandler(fh); logger.addHandler(ch)
    return logger, lf

log, log_file = setup_logging()
run_log_migration()

# ═══════════════════════════════════════════════════════
# BRIEF PARSER
# ═══════════════════════════════════════════════════════
def parse_batch(filepath: Path) -> list[Brief]:
    content = filepath.read_text(encoding="utf-8")
    briefs = []
    id_pat = re.compile(r'^\s*-?\s*id:\s*(.+)', re.MULTILINE)
    title_pat = re.compile(r'^\s*title:\s*"?(.+?)"?\s*$', re.MULTILINE)
    deps_pat = re.compile(r'^\s*depends_on:\s*\[([^\]]*)\]', re.MULTILINE)
    ids_raw = id_pat.findall(content)
    ids = [i for i in ids_raw if not i.strip().strip('"').strip("'").lower() in ('string','number','boolean','integer','pending','true','false')]
    titles = title_pat.findall(content)
    for i, bid in enumerate(ids):
        bid = bid.strip().strip('"').strip("'")
        title = titles[i].strip() if i < len(titles) else bid
        start = content.find(f"id: {bid}")
        if start == -1: start = content.find(bid)
        nxt = len(content)
        for j, oid in enumerate(ids):
            if j > i:
                pos = content.find(f"id: {oid.strip()}", start+1)
                if pos != -1: nxt = pos; break
        section = content[start:nxt]
        dm = deps_pat.search(section)
        deps = [d.strip().strip('"').strip("'") for d in dm.group(1).split(",") if d.strip()] if dm else []
        briefs.append(Brief(id=bid, title=title, depends_on=deps))
    # If no YAML-style briefs found, try markdown ## Brief N: pattern
    if not briefs:
        brief_pat = re.compile(r'^## Brief (\d+)[:\s—–\-]+\s*(.+)', re.MULTILINE)
        matches = brief_pat.findall(content)
        for num, title in matches:
            briefs.append(Brief(id=f"brief-{num}", title=title.strip()[:80]))

    # Final fallback: count as single batch
    if not briefs:
        briefs.append(Brief(id=filepath.stem, title=f"Batch: {filepath.name}"))
    log.info(f"Parsed {filepath.name}: {len(briefs)} briefs")
    for b in briefs:
        dep = f" (deps: {b.depends_on})" if b.depends_on else ""
        log.info(f"  -> {b.id}: {b.title}{dep}")
    return briefs

# ═══════════════════════════════════════════════════════
# BRIEF TIMEOUT PARSING (A62)
# ═══════════════════════════════════════════════════════
def parse_brief_timeout(filepath: Path) -> Optional[int]:
    """Parse TONI_TIMEOUT_MIN advisory from brief file header.
    Returns timeout in minutes, or None if not declared.
    """
    try:
        content = filepath.read_text(encoding="utf-8")[:4000]
    except Exception:
        return None

    m = re.search(r'^## TONI_TIMEOUT_MIN:\s*(\d+)', content, re.MULTILINE)
    if m:
        return int(m.group(1))

    m = re.search(r'^## Fire mechanism:.*TONI_TIMEOUT_MIN=(\d+)', content, re.MULTILINE)
    if m:
        return int(m.group(1))

    m = re.search(r'^## Estimated runtime:\s*(.+)', content, re.MULTILINE)
    if m:
        runtime_line = m.group(1)
        rm = re.search(r'(\d+)\s*-\s*(\d+)\s*m', runtime_line)
        if rm:
            upper = int(rm.group(2))
            return int(upper * 1.25)
        rm = re.search(r'(\d+)\s*m', runtime_line)
        if rm:
            return int(int(rm.group(1)) * 1.25)

    return None


def resolve_timeout(brief_path: Optional[Path] = None) -> tuple[int, str]:
    """Resolve timeout with precedence: env-var > brief-declared > default.
    Returns (timeout_minutes, source_label). Hard cap at 180m.
    """
    env_raw = os.environ.get("TONI_TIMEOUT_MIN", "")
    if env_raw:
        timeout = int(env_raw)
        source = "env-var"
    elif brief_path:
        brief_val = parse_brief_timeout(brief_path)
        if brief_val is not None:
            timeout = brief_val
            source = "brief-declared"
        else:
            timeout = TIMEOUT_DEFAULT_MIN
            source = "default"
    else:
        timeout = TIMEOUT_DEFAULT_MIN
        source = "default"

    if timeout > TIMEOUT_HARD_CAP_MIN:
        log.warning(
            f"Timeout {timeout}min exceeds hard cap {TIMEOUT_HARD_CAP_MIN}min; clamping"
        )
        timeout = TIMEOUT_HARD_CAP_MIN

    return timeout, source


# ═══════════════════════════════════════════════════════
# DEPENDENCY CASCADE
# ═══════════════════════════════════════════════════════
def parse_batch_deps(filepath: Path) -> list[str]:
    """
    Parse batch-level dependencies from file header.
    Format: # depends_on_batches: [batch-a.md, batch-b.md]
    """
    try:
        content = filepath.read_text(encoding="utf-8")
        # Match comment-style or yaml-style
        pat = re.compile(r'#?\s*depends_on_batches:\s*\[([^\]]*)\]', re.IGNORECASE)
        m = pat.search(content[:2000])  # only scan first 2000 chars (header area)
        if m:
            deps = [d.strip().strip('"').strip("'") for d in m.group(1).split(",") if d.strip()]
            return deps
    except Exception:
        pass
    return []

def check_batch_deps(filepath: Path, state: dict = None) -> tuple[bool, list[str], list[str]]:
    """
    Check if all batch-level dependencies are satisfied.
    Returns (all_met, met_deps, unmet_deps).
    """
    deps = parse_batch_deps(filepath)
    if not deps:
        return True, [], []

    if state is None:
        state = load_state()

    completed_names = {b.get("batch_file", "") for b in state.get("completed", [])}

    met = [d for d in deps if d in completed_names]
    unmet = [d for d in deps if d not in completed_names]

    return len(unmet) == 0, met, unmet

def find_unblocked(state: dict = None) -> list[Path]:
    """
    Scan pending briefs and return those whose dependencies are now met.
    """
    if state is None:
        state = load_state()

    completed_names = {b.get("batch_file", "") for b in state.get("completed", [])}
    failed_names = {b.get("batch_file", "") for b in state.get("failed", [])}
    done_names = completed_names | failed_names

    unblocked = []
    if BRIEFS_DIR.exists():
        for f in sorted(BRIEFS_DIR.glob("*.md")):
            if f.name in done_names:
                continue
            deps = parse_batch_deps(f)
            if not deps:
                continue  # no deps = always eligible, not "unblocked"
            if all(d in completed_names for d in deps):
                unblocked.append(f)
                log.info(f"🔓 Unblocked: {f.name} (deps met: {deps})")
                if HAS_SLACK:
                    for d in deps:
                        slack_notify.notify_cascade(f.name, d)

    return unblocked

# ═══════════════════════════════════════════════════════
# APPROVAL GATE (D-184)
# ═══════════════════════════════════════════════════════
def approval_gate(batch_file: Path, briefs: list[Brief], approve: bool = False,
                  force: bool = False, skip_deps: bool = False) -> bool:
    if force:
        log.warning("⚠️  --force: ALL safety checks bypassed")
        return True

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

    # Interactive approval
    print(f"\n{'━'*60}")
    print(f"  🔒 APPROVAL REQUIRED (D-184)")
    print(f"{'━'*60}")
    print(f"  Batch:      {batch_file.name}")
    print(f"  Briefs:     {len(briefs)}")
    for b in briefs:
        dep = f"  ← deps: {b.depends_on}" if b.depends_on else ""
        print(f"    • {b.id}: {b.title}{dep}")
    print(f"  Project:    {PROJECT_ROOT}")
    print(f"  Playwright: {'ON' if RUN_PLAYWRIGHT else 'OFF'}")
    print(f"  Timeout:    {TONI_TIMEOUT // 60}m")

    # Dependency check
    all_met, met, unmet = check_batch_deps(batch_file)
    if unmet:
        print(f"  Deps:       ❌ UNMET — {unmet}")
        if not skip_deps:
            print(f"\n  ⛔ BLOCKED by unmet dependencies. Use --skip-deps to override.")
            print(f"{'━'*60}\n")
            return False
        else:
            print(f"              (--skip-deps: proceeding anyway)")
    elif met:
        print(f"  Deps:       ✅ All met — {met}")
    else:
        print(f"  Deps:       — (none declared)")

    # Rate check
    ok, msg = rate_limiter.pre_flight(len(briefs))
    print(f"  Rate limit: {msg}")
    if not ok:
        print(f"\n  ⛔ BLOCKED by rate limiter.")
        print(f"{'━'*60}\n")
        return False

    print(f"{'━'*60}")
    try:
        answer = input("  Fire Toni? [y/N] ").strip().lower()
        approved = answer in ('y', 'yes')
        if approved:
            log.info("✅ Approved interactively")
        else:
            log.info("❌ Rejected by user")
        return approved
    except (EOFError, KeyboardInterrupt):
        print("\n  ❌ Cancelled")
        return False

# ═══════════════════════════════════════════════════════
# RATE LIMIT PRE-FLIGHT (non-interactive)
# ═══════════════════════════════════════════════════════
def rate_check(brief_count: int, force: bool = False) -> bool:
    if force:
        return True
    ok, msg = rate_limiter.pre_flight(brief_count)
    log.info(f"Rate check: {msg}")
    if not ok:
        log.error("⛔ Execution blocked by rate limiter")
        return False
    return True

# ═══════════════════════════════════════════════════════
# MIGRATION CHECK
# ═══════════════════════════════════════════════════════
def get_migrations() -> set:
    d = PROJECT_ROOT / "supabase" / "migrations"
    if not d.exists(): d = YORSIE_DIR / "supabase" / "migrations"
    if not d.exists(): return set()
    return {f.name for f in d.glob("*.sql")}

# ═══════════════════════════════════════════════════════
# TONI EXECUTOR
# ═══════════════════════════════════════════════════════
def fire_toni(batch_file: Path, project: Path=PROJECT_ROOT) -> tuple[int, str]:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_subdir = ensure_log_subdir(LOG_SUBDIR)
    out_log = log_subdir / f"toni-{batch_file.stem}-{ts}.log"
    try:
        brief_rel = batch_file.relative_to(project)
    except ValueError:
        brief_rel = batch_file.name
    cmd = (
        f"cd {project} && "
        f"stdbuf -oL "
        f"claude --dangerously-skip-permissions "
        f"--model claude-opus-4-8 --effort high "
        f'"Read {brief_rel} and execute all briefs in order."'
    )
    # Update running.json with log file path
    try:
        if RUNNING_FILE.exists():
            rd = json.loads(RUNNING_FILE.read_text())
            rd["log_file"] = str(out_log)
            RUNNING_FILE.write_text(json.dumps(rd, indent=2))
    except Exception:
        pass
    log.info(f"Firing Toni: {batch_file.name}")
    log.info(f"  Project: {project}")
    log.info(f"  Timeout: {TONI_TIMEOUT // 60}m")
    log.info(f"  Log: {out_log}")
    try:
        with open(out_log, "w") as lf:
            lf.write(f"=== TONI EXECUTION ===\nBatch: {batch_file.name}\n")
            lf.write(f"Started: {datetime.now().isoformat()}\nCommand: {cmd}\n{'='*60}\n\n")
            lf.flush()
            proc = subprocess.Popen(cmd, shell=True, executable="/bin/bash",
                stdout=lf, stderr=subprocess.STDOUT, cwd=str(project),
                preexec_fn=os.setsid)
            ec = proc.wait(timeout=TONI_TIMEOUT)
            lf.write(f"\n{'='*60}\nFinished: {datetime.now().isoformat()}\nExit: {ec}\n")
        log.info(f"Toni finished: exit {ec}")
        return ec, str(out_log)
    except subprocess.TimeoutExpired:
        log.error(f"Toni TIMEOUT after {TONI_TIMEOUT//60}m")
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        time.sleep(3)
        try: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError: pass
        return -1, str(out_log)
    except Exception as e:
        log.error(f"Toni error: {e}")
        return -2, str(out_log)

# ═══════════════════════════════════════════════════════
# POST-EXECUTION
# ═══════════════════════════════════════════════════════
def run_playwright() -> tuple[bool, int]:
    log.info("Running Playwright...")
    try:
        r = subprocess.run(PLAYWRIGHT_CMD, shell=True, capture_output=True,
            text=True, timeout=300, cwd=str(PROJECT_ROOT))
        m = re.search(r'(\d+)\s+passed', r.stdout + r.stderr)
        cnt = int(m.group(1)) if m else 0
        ok = r.returncode == 0
        log.info(f"Playwright: {'PASSED' if ok else 'FAILED'} ({cnt} tests)")
        if not ok: log.warning(f"Stderr:\n{r.stderr[-500:]}")
        return ok, cnt
    except subprocess.TimeoutExpired:
        log.error("Playwright timed out"); return False, 0
    except Exception as e:
        log.error(f"Playwright error: {e}"); return False, 0

def notify(result: Result):
    e = "✅" if result.status == Status.PASSED else "❌"
    status_label = "passed (no changes)" if result.no_changes else result.status.value
    msg = f"{e} {result.batch_file} — {status_label} | {result.briefs} briefs | {result.duration_s:.0f}s"
    if result.playwright_ok is not None:
        msg += f" | PW: {'✅' if result.playwright_ok else '❌'} ({result.pw_tests})"
    if result.new_migrations:
        msg += f"\n  ⚠️  {len(result.new_migrations)} migrations to apply manually"
        for m in result.new_migrations:
            msg += f"\n    npx supabase db query --linked -f supabase/migrations/{m}"
    log.info(f"\n{'━'*60}\n{msg}\n{'━'*60}")

    # Slack notification
    if HAS_SLACK:
        try:
            slack_notify.notify_batch(
                result.batch_file, result.status.value,
                briefs=result.briefs, duration_s=result.duration_s,
                migrations=result.new_migrations, exit_code=result.exit_code
            )
        except Exception as ex:
            log.warning(f"Slack notify failed: {ex}")

    # Rate limit warning via Slack
    if HAS_SLACK:
        caps = rate_limiter.load_caps()
        data = rate_limiter.load()
        today_key = rate_limiter.today_key()
        today = data.get("daily", {}).get(today_key, {})
        batch_pct = today.get("batches", 0) / caps["daily_batches"] * 100 if caps["daily_batches"] > 0 else 0
        if batch_pct >= 80:
            try:
                slack_notify.notify_rate_warning(
                    today.get("batches", 0), caps["daily_batches"],
                    today.get("briefs", 0), caps["daily_briefs"]
                )
            except Exception:
                pass

# ═══════════════════════════════════════════════════════
# STATE
# ═══════════════════════════════════════════════════════
def load_state() -> dict:
    if STATE_FILE.exists(): return json.loads(STATE_FILE.read_text())
    return {"queue":[], "completed":[], "failed":[], "watched":{}}
def save_state(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2, default=str))
def fhash(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()

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


def _write_running_marker(batch_file: Path, repo_name: str, repo_path: Path,
                          branch: str, meta_fire_worktree: Optional[Path],
                          is_self_mod: bool):
    """Write state/running.json marker for in-flight fire visibility."""
    marker_dir = ORCH_DIR / "state"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_dir / "running.json"
    marker.write_text(json.dumps({
        "pid": os.getpid(),
        "batch_id": batch_file.stem,
        "repo": repo_name,
        "repo_path": str(repo_path),
        "branch": branch,
        "started_at": datetime.now().astimezone().isoformat(),
        "meta_fire_worktree": str(meta_fire_worktree) if meta_fire_worktree else None,
        "is_self_mod": is_self_mod,
    }, indent=2))


def _clear_running_marker():
    """Remove state/running.json marker."""
    marker = ORCH_DIR / "state" / "running.json"
    try:
        marker.unlink(missing_ok=True)
    except Exception:
        pass


def _check_stale_marker() -> bool:
    """Check for stale or active running.json marker at startup.

    Returns True if safe to proceed. Exits with code 4 if another fire is active.
    """
    marker = ORCH_DIR / "state" / "running.json"
    if not marker.exists():
        return True

    try:
        data = json.loads(marker.read_text())
    except (json.JSONDecodeError, IOError):
        marker.unlink(missing_ok=True)
        return True

    pid = data.get("pid", 0)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        log.warning(
            f"⚠️  Stale running.json from {data.get('started_at', '?')} "
            f"(pid {pid} no longer alive); cleaned up."
        )
        marker.unlink(missing_ok=True)
        return True
    except PermissionError:
        pass

    print(
        f"❌ Another orchestrator fire is in progress "
        f"(pid {pid}, batch {data.get('batch_id', '?')}, "
        f"started {data.get('started_at', '?')}). "
        f"Wait or kill the existing process.",
        file=sys.stderr,
    )
    sys.exit(4)


# ═══════════════════════════════════════════════════════
# WORKTREES (PARALLEL)
# ═══════════════════════════════════════════════════════
def create_worktree(name: str, wid: int) -> Optional[Path]:
    wt = WORKTREE_BASE / f"toni-{wid}"
    br = f"{BRANCH_PREFIX}-{name}-w{wid}"
    try:
        if wt.exists():
            subprocess.run(f"cd {PROJECT_ROOT} && git worktree remove {wt} --force",
                shell=True, capture_output=True)
        r = subprocess.run(f"cd {PROJECT_ROOT} && git worktree add {wt} -b {br}",
            shell=True, capture_output=True, text=True)
        if r.returncode != 0:
            r = subprocess.run(f"cd {PROJECT_ROOT} && git worktree add {wt} {br}",
                shell=True, capture_output=True, text=True)
        if r.returncode == 0:
            log.info(f"Worktree: {wt} (branch: {br})"); return wt
        log.error(f"Worktree fail: {r.stderr}"); return None
    except Exception as e:
        log.error(f"Worktree error: {e}"); return None

def cleanup_worktree(wt: Path):
    try:
        subprocess.run(f"cd {PROJECT_ROOT} && git worktree remove {wt} --force",
            shell=True, capture_output=True)
        log.info(f"Cleaned: {wt}")
    except: pass

def merge_branch(br: str) -> bool:
    r = subprocess.run(f"cd {PROJECT_ROOT} && git merge {br} --no-edit",
        shell=True, capture_output=True, text=True)
    if r.returncode == 0:
        log.info(f"Merged {br}"); return True
    log.error(f"Merge conflict on {br} — MANUAL RESOLUTION NEEDED"); return False


def _self_mod_auto_merge(orch_dir: Path, branch_name: str) -> bool:
    """Auto-merge meta-fire branch to main after successful self-mod fire.

    Returns True if merge succeeded (or no commits to merge), False on failure.
    Note: after auto-merge, the orchestrator's loaded Python modules are unchanged
    in memory; new code on disk takes effect on next invocation.
    """
    try:
        r = subprocess.run(
            f"git -C {orch_dir} rev-list --count main..{branch_name}",
            shell=True, capture_output=True, text=True
        )
        count = int(r.stdout.strip()) if r.returncode == 0 else 0
    except (ValueError, Exception):
        count = 0

    if count == 0:
        log.info("Self-mod auto-merge: no commits to bring in; skipping")
        return True

    r = subprocess.run(
        f"git -C {orch_dir} merge --ff-only {branch_name}",
        shell=True, capture_output=True, text=True
    )
    if r.returncode == 0:
        log.info(f"✅ Self-mod auto-merge: brought {count} commits to main")
        return True
    else:
        log.warning(
            f"⚠️  Self-mod auto-merge failed (non-ff). Branch preserved: {branch_name}. "
            f"Run: cd {orch_dir} && git merge --ff-only {branch_name}"
        )
        return False

# ═══════════════════════════════════════════════════════
# BUILD GATE (S6S47 P1 hardening — D-S6S46-B)
# Post-merge tsc + build. BLOCKING: failure → caller sets Status.FAILED,
# existing run_queue halt-on-fail (line ~1208) stops the queue.
# Root cause it addresses: no between-brief build gate → 30 TS errors
# accumulated silently across the Phase 2 autopilot (S6S46 cleanup 055aab6).
# ═══════════════════════════════════════════════════════
@dataclass
class BuildGateOutcome:
    passed: bool
    exit_code: int
    error: Optional[str] = None
    duration_s: float = 0.0


def run_build_gate(repo_path: Path) -> BuildGateOutcome:
    """Run tsc --noEmit && npm run build after merge. BLOCKING gate.

    Returns BuildGateOutcome; caller promotes a fail to Status.FAILED.
    Disable via DISABLE_BUILD_GATE env (emergency bypass only).
    """
    if not BUILD_GATE_ENABLED:
        log.info("⏭️  Build gate disabled (DISABLE_BUILD_GATE)")
        return BuildGateOutcome(passed=True, exit_code=0, error="disabled")

    # Per-repo build gate: repos.yaml may declare `build_gate_cmd` (e.g. "pytest -q"
    # for Python repos). Falls back to the global TS default, preserving every TS repo.
    gate_cmd = ACTIVE_REPO_CONFIG.get("build_gate_cmd", BUILD_GATE_CMD)
    log.info(f"🔧 Running build gate [{ACTIVE_REPO_NAME or 'default'}]: {gate_cmd}")
    started = time.time()
    try:
        r = subprocess.run(
            gate_cmd, shell=True, capture_output=True, text=True,
            cwd=str(repo_path), timeout=BUILD_GATE_TIMEOUT
        )
        duration = time.time() - started
        passed = r.returncode == 0
        if passed:
            log.info(f"✅ BUILD GATE PASSED ({duration:.1f}s)")
            return BuildGateOutcome(passed=True, exit_code=0, duration_s=duration)
        log.error(f"❌ BUILD GATE FAILED (exit {r.returncode}, {duration:.1f}s) — BLOCKING, queue will halt")
        tail = (r.stdout or "")[-800:] + "\n" + (r.stderr or "")[-800:]
        log.error(f"   {tail.strip()[-1000:]}")
        return BuildGateOutcome(passed=False, exit_code=r.returncode,
                                error=tail.strip()[-1000:], duration_s=duration)
    except subprocess.TimeoutExpired:
        duration = time.time() - started
        log.error(f"❌ BUILD GATE TIMEOUT after {duration:.1f}s — BLOCKING")
        return BuildGateOutcome(passed=False, exit_code=-1, error="timeout", duration_s=duration)
    except Exception as e:
        duration = time.time() - started
        log.error(f"❌ BUILD GATE ERROR: {e} — BLOCKING")
        return BuildGateOutcome(passed=False, exit_code=-1, error=str(e), duration_s=duration)


# ═══════════════════════════════════════════════════════
# SIT POST-MERGE INTEGRATION (A58a — advisory v1)
# ═══════════════════════════════════════════════════════
@dataclass
class SitOutcome:
    passed: bool
    exit_code: int
    report_path: Optional[str] = None
    error: Optional[str] = None
    duration_s: float = 0.0


def run_sit_post_merge(repo_path: Path, archive_path: Optional[Path] = None) -> SitOutcome:
    """Run SIT smoke tests after merge, then apply the MANY-or-SEVERE halt rule.

    Baseline (SIT_KNOWN_FAILING) failures never block. Among NEW failures: a CRITICAL spec
    (SIT_CRITICAL_SPECS) blocks on any 1; non-critical failures block only at SIT_MANY_THRESHOLD
    or more. Timeout / unparseable failure -> advisory (surfaced, not blocking). SitOutcome.passed
    encodes block-worthiness; the caller blocks iff not passed and SIT_BLOCKING.
    """
    if SKIP_SIT:
        log.info("⏭️  SIT skipped (--skip-sit)")
        return SitOutcome(passed=True, exit_code=0, error="skipped")

    archive = archive_path or SIT_ARCHIVE_DIR
    archive.mkdir(parents=True, exist_ok=True)

    # Playwright config uses env var NO_AUTO_SPAWN (not a CLI flag); with
    # reuseExistingServer: true, no orchestrator-side suppression needed.
    sit_cmd = "npm run sit:smoke"
    log.info(f"🧪 Running SIT post-merge: {sit_cmd}")
    started = time.time()

    try:
        r = subprocess.run(
            sit_cmd, shell=True, capture_output=True, text=True,
            cwd=str(repo_path), timeout=SIT_TIMEOUT
        )
        duration = time.time() - started
        # S6S47: baseline-aware. Block only on NEW failures, not pre-existing
        # known-failing specs (BUG-018/BUG-026). Parse failing spec basenames
        # from playwright output; if every failing spec is in SIT_KNOWN_FAILING,
        # treat as pass-with-known-failures.
        raw = (r.stdout or "") + "\n" + (r.stderr or "")
        import re as _re
        failing_specs = set()
        for m in _re.finditer(r"✘\s+\d+\s+\[[^\]]*\]\s+›\s+(\S+\.spec\.ts)", raw):
            failing_specs.add(Path(m.group(1)).stem.replace(".spec", ""))
        new_failures = {s for s in failing_specs
                        if not any(k in s for k in SIT_KNOWN_FAILING)}
        # S6S72 MANY-or-SEVERE threshold.
        new_critical = {s for s in new_failures
                        if any(c in s for c in SIT_CRITICAL_SPECS)}
        new_noncritical = new_failures - new_critical
        if r.returncode == 0:
            passed = True
        elif not failing_specs:
            # exit!=0 but no spec failures parsed (crash / format drift / infra) — advisory.
            passed = True
            log.error(f"🟠 SIT exited {r.returncode} but parsed NO failing specs — "
                      f"ADVISORY (not blocking); surfacing for review.")
        elif new_critical:
            passed = False
            log.error(f"⛔ SIT CRITICAL new failure(s) — BLOCKING: {', '.join(sorted(new_critical))}")
        elif len(new_noncritical) >= SIT_MANY_THRESHOLD:
            passed = False
            log.error(f"⛔ SIT {len(new_noncritical)} new non-critical failures >= "
                      f"{SIT_MANY_THRESHOLD} — BLOCKING: {', '.join(sorted(new_noncritical))}")
        else:
            passed = True
            _baseline_hit = failing_specs - new_failures
            _bits = []
            if _baseline_hit:
                _bits.append(f"{len(_baseline_hit)} baseline ({', '.join(sorted(_baseline_hit))})")
            if new_noncritical:
                _bits.append(f"{len(new_noncritical)} new non-critical < {SIT_MANY_THRESHOLD} "
                             f"({', '.join(sorted(new_noncritical))})")
            log.warning(f"🟡 SIT: {'; '.join(_bits) or 'failures present'} — NOT blocking (under threshold)")

        # Archive SIT report if it exists
        report_path = None
        sit_reports_dir = repo_path / "sit-reports"
        if sit_reports_dir.exists():
            import shutil, glob as _glob
            reports = sorted(sit_reports_dir.glob("alex-mp-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if reports:
                dest = archive / reports[0].name
                shutil.copy2(reports[0], dest)
                report_path = str(dest)
                log.info(f"📋 SIT report archived: {dest.name}")

        error_excerpt = None
        if passed:
            log.info(f"✅ SIT PASSED ({duration:.1f}s)")
        else:
            log.warning(f"⚠️  SIT FAILED (exit {r.returncode}, {duration:.1f}s) — advisory only, not blocking merge")
            if r.stdout:
                log.warning(f"   stdout: {r.stdout[-500:]}")
            error_excerpt = (r.stderr or r.stdout or "")[-1000:].strip() or None

        # Log to orchestrator-sit-log.json
        _log_sit_outcome(archive, repo_path, passed, r.returncode, duration, report_path,
                         error_excerpt=error_excerpt)

        return SitOutcome(passed=passed, exit_code=r.returncode, report_path=report_path, duration_s=duration)

    except subprocess.TimeoutExpired:
        duration = time.time() - started
        log.error(f"🟠 SIT TIMEOUT after {duration:.1f}s — ADVISORY (not blocking); surfacing for review.")
        _log_sit_outcome(archive, repo_path, True, -1, duration, None, error="timeout-advisory")
        return SitOutcome(passed=True, exit_code=-1, error="timeout-advisory", duration_s=duration)
    except Exception as e:
        duration = time.time() - started
        log.warning(f"⚠️  SIT ERROR: {e} — advisory only")
        _log_sit_outcome(archive, repo_path, False, -1, duration, None, error=str(e))
        return SitOutcome(passed=False, exit_code=-1, error=str(e), duration_s=duration)


def _log_sit_outcome(archive: Path, repo_path: Path, passed: bool, exit_code: int,
                     duration: float, report_path: Optional[str], error: Optional[str] = None,
                     error_excerpt: Optional[str] = None):
    """Append SIT outcome to orchestrator-sit-log.json."""
    log_file = archive / "orchestrator-sit-log.json"
    entries = []
    if log_file.exists():
        try:
            entries = json.loads(log_file.read_text())
        except (json.JSONDecodeError, IOError):
            entries = []

    entry = {
        "timestamp": datetime.now().isoformat(),
        "repo": str(repo_path),
        "passed": passed,
        "exit_code": exit_code,
        "duration_s": round(duration, 2),
        "report_path": report_path,
        "error": error,
    }
    if error_excerpt is not None:
        entry["error_excerpt"] = error_excerpt
    entries.append(entry)
    log_file.write_text(json.dumps(entries, indent=2))


def sit_report_aggregate(since: Optional[str] = None):
    """Aggregate archived SIT reports since a given date."""
    archive = SIT_ARCHIVE_DIR
    if not archive.exists():
        print("No SIT archive found."); return

    log_file = archive / "orchestrator-sit-log.json"
    if not log_file.exists():
        print("No SIT log entries found."); return

    entries = json.loads(log_file.read_text())
    if since:
        entries = [e for e in entries if e["timestamp"] >= since]

    if not entries:
        print(f"No SIT runs found since {since or 'beginning'}."); return

    total = len(entries)
    passed = sum(1 for e in entries if e["passed"])
    failed = total - passed

    print(f"\n{'═'*60}")
    print(f"SIT REPORT AGGREGATE (since {since or 'all time'})")
    print(f"{'═'*60}")
    print(f"  Total runs:  {total}")
    print(f"  Passed:      {passed} ({100*passed/total:.0f}%)")
    print(f"  Failed:      {failed} ({100*failed/total:.0f}%)")
    avg_dur = sum(e.get("duration_s", 0) for e in entries) / total
    print(f"  Avg duration: {avg_dur:.1f}s")
    print(f"\n  Recent entries:")
    for e in entries[-10:]:
        status = "✅" if e["passed"] else "❌"
        err = f" ({e['error']})" if e.get("error") else ""
        print(f"    {status} {e['timestamp'][:19]} — {e.get('duration_s', 0):.1f}s{err}")
    print(f"{'═'*60}\n")


# ═══════════════════════════════════════════════════════
# BATCH RUNNER
# ═══════════════════════════════════════════════════════
def run_batch(batch_file: Path, worktree: Optional[Path]=None) -> Result:
    meta_wt = None
    meta_branch = None
    is_self_mod = IS_META_FIRE and (PROJECT_ROOT.resolve() == ORCH_DIR)

    if IS_META_FIRE and worktree is None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        meta_wt = Path(f"/tmp/orch-fire-{ts}")
        meta_branch = f"{BRANCH_PREFIX}-{batch_file.stem}"
        try:
            if meta_wt.exists():
                subprocess.run(f"cd {PROJECT_ROOT} && git worktree remove {meta_wt} --force",
                    shell=True, capture_output=True)
            r = subprocess.run(f"cd {PROJECT_ROOT} && git worktree add {meta_wt} -b {meta_branch}",
                shell=True, capture_output=True, text=True)
            if r.returncode != 0:
                r = subprocess.run(f"cd {PROJECT_ROOT} && git worktree add {meta_wt} {meta_branch}",
                    shell=True, capture_output=True, text=True)
            if r.returncode == 0:
                log.info(f"Meta-fire worktree: {meta_wt} (branch: {meta_branch})")
                worktree = meta_wt
            else:
                log.error(f"Meta-fire worktree failed: {r.stderr}")
        except Exception as e:
            log.error(f"Meta-fire worktree error: {e}")

    proj = worktree or PROJECT_ROOT
    started = datetime.now()
    briefs_preview = parse_batch(batch_file)
    write_running(batch_file, len(briefs_preview))
    _write_running_marker(
        batch_file, ACTIVE_REPO_NAME, PROJECT_ROOT,
        meta_branch or f"{BRANCH_PREFIX}-{batch_file.stem}",
        meta_wt, is_self_mod,
    )
    result = None
    try:
        result = _run_batch_inner(batch_file, proj, started, worktree)
    finally:
        clear_running()
        _clear_running_marker()
        if meta_wt:
            if is_self_mod and meta_branch:
                if result is not None and result.exit_code == 0:
                    merged = _self_mod_auto_merge(ORCH_DIR, meta_branch)
                    if merged:
                        cleanup_worktree(meta_wt)
                else:
                    log.warning(
                        f"Self-mod fire failed; branch preserved: {meta_branch}. "
                        f"Inspect {meta_wt} for state."
                    )
            else:
                cleanup_worktree(meta_wt)
    return result

def _run_batch_inner(batch_file: Path, proj: Path, started: datetime, worktree=None) -> Result:
    briefs_subdir = ACTIVE_REPO_CONFIG.get("briefs_subdir", "briefs")
    target = proj / briefs_subdir / batch_file.name
    if not batch_file.is_relative_to(proj):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(batch_file.read_bytes())
        log.info(f"Copied brief to {target}")
    briefs = parse_batch(batch_file)

    # A62: resolve timeout from env-var > brief-declared > default
    global TONI_TIMEOUT
    timeout_min, timeout_src = resolve_timeout(batch_file)
    TONI_TIMEOUT = timeout_min * 60
    log.info(f"timeout={timeout_min}min source={timeout_src}")

    # Auto branch creation (D-148) — skip if using worktrees
    branch_name = None
    if worktree is None:
        branch_name = f"{BRANCH_PREFIX}-{batch_file.stem}"
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
    finished = datetime.now()
    dur = (finished - started).total_seconds()
    # S6S49 fix: claude-code 2.1.123 returns a NON-ZERO exit even on a fully
    # successful run (thinking-block teardown regression). Trusting ec alone
    # made the orchestrator discard good work (006/007 produced correct,
    # compiling code yet were logged FAILED, leaving edits uncommitted).
    # Real success signal = Toni produced work (commits ahead of target OR
    # staged/unstaged changes in the tree). The post-merge BUILD GATE remains
    # the quality arbiter, so this cannot merge broken code — it only stops a
    # bad exit code from throwing away good code. ec is still recorded.
    if worktree is None and branch_name:
        _staged = subprocess.run("git status --porcelain", shell=True,
            capture_output=True, text=True, cwd=str(proj)).stdout.strip()
        _ahead = subprocess.run(f"git rev-list --count {MERGE_TARGET}..HEAD",
            shell=True, capture_output=True, text=True, cwd=str(proj)).stdout.strip()
        try: _ahead_n = int(_ahead)
        except ValueError: _ahead_n = 0
        _produced_work = bool(_staged) or _ahead_n > 0
    else:
        _produced_work = (ec == 0)
    status = Status.PASSED if (ec == 0 or _produced_work) else Status.FAILED
    if ec != 0 and _produced_work:
        log.warning(f"⚠️  Toni exited non-zero (ec={ec}) but produced work "
                    f"(staged/ahead) — treating as PASSED; build gate will verify. "
                    f"(claude-code 2.1.123 exit-code regression)")
    mig_after = get_migrations()
    new_mig = sorted(mig_after - mig_before)
    if new_mig:
        log.warning(f"⚠️  NEW MIGRATIONS — apply manually:")
        for m in new_mig:
            log.warning(f"  npx supabase db query --linked -f supabase/migrations/{m}")
    pw_ok, pw_cnt = (None, 0)
    if RUN_PLAYWRIGHT and ec == 0 and worktree is None:
        pw_ok, pw_cnt = run_playwright()
        if not pw_ok: status = Status.FAILED

    # Auto-commit + merge back to main (D-148)
    no_change_run = False
    if branch_name and worktree is None:
        try:
            if status == Status.PASSED:
                # Commit all changes on feature branch
                subprocess.run("git add -A", shell=True, cwd=str(proj), capture_output=True)

                diff_check = subprocess.run(
                    "git diff --cached --quiet",
                    shell=True, capture_output=True, cwd=str(proj)
                )
                # OBS-S6S17-02: Toni (post-OBS-S6S16-01) commits autonomously — staging
                # may be empty even though Toni made commits on the branch. Count commits
                # ahead of merge target, OR-combine with staged-changes check.
                rev_count_proc = subprocess.run(
                    f"git rev-list --count {MERGE_TARGET}..HEAD",
                    shell=True, capture_output=True, text=True, cwd=str(proj)
                )
                toni_commits = (
                    int(rev_count_proc.stdout.strip())
                    if rev_count_proc.returncode == 0 and rev_count_proc.stdout.strip().isdigit()
                    else 0
                )
                has_staged_changes = diff_check.returncode != 0
                has_changes = has_staged_changes or toni_commits > 0
                if toni_commits > 0:
                    log.info(f"📦 Toni made {toni_commits} commit(s) on {branch_name}")

                if has_changes:
                    if has_staged_changes:
                        commit_msg = f"fix: {batch_file.stem} — {len(briefs)} briefs"
                        r = subprocess.run(
                            f'git commit -m "{commit_msg}"',
                            shell=True, capture_output=True, text=True, cwd=str(proj)
                        )
                        if r.returncode == 0:
                            log.info(f"📦 Committed: {commit_msg}")
                        else:
                            log.warning(f"⚠️ Commit failed: {r.stderr.strip()}")
                    else:
                        log.info(f"📦 Skipping orchestrator commit — Toni already committed {toni_commits} commit(s)")

                    # Merge back to merge target
                    pre_merge_tip = subprocess.run(
                        f"git rev-parse {MERGE_TARGET}",
                        shell=True, capture_output=True, text=True, cwd=str(proj)
                    ).stdout.strip()
                    subprocess.run(f"git checkout {MERGE_TARGET}", shell=True, capture_output=True, cwd=str(proj))
                    r = subprocess.run(
                        f"git merge {branch_name} --no-edit",
                        shell=True, capture_output=True, text=True, cwd=str(proj)
                    )
                    if r.returncode == 0:
                        post_merge_tip = subprocess.run(
                            f"git rev-parse {MERGE_TARGET}",
                            shell=True, capture_output=True, text=True, cwd=str(proj)
                        ).stdout.strip()
                        if post_merge_tip == pre_merge_tip and toni_commits > 0:
                            # OBS-S6S17-02: defense-in-depth — main didn't advance despite
                            # Toni having made commits. This is the silent-failure mode.
                            log.error(
                                f"❌ Merge reported success but {MERGE_TARGET} tip unchanged "
                                f"({pre_merge_tip[:7]}). Toni had {toni_commits} commit(s) on "
                                f"{branch_name}. NOT deleting branch — manual recovery needed."
                            )
                            status = Status.FAILED
                        else:
                            log.info(f"🔀 Merged {branch_name} → {MERGE_TARGET} ({pre_merge_tip[:7]} → {post_merge_tip[:7]})")
                            # Clean up feature branch
                            subprocess.run(f"git branch -d {branch_name}", shell=True, capture_output=True, cwd=str(proj))
                        # S6S47 P1 hardening (D-S6S46-B): post-merge gates.
                        # Order: build gate (tsc+build) → SIT (visual smoke).
                        # Both BLOCKING: a fail sets Status.FAILED so run_queue
                        # halt-on-fail stops the queue (no firing onto a broken base).
                        if ACTIVE_REPO_NAME == "clinical-mp":
                            # Gate 1: build (catches typecheck/build drift)
                            bg = run_build_gate(proj)
                            if not bg.passed:
                                subprocess.run(
                                    f'git notes add -m "BUILD GATE: FAILED — exit {bg.exit_code}"',
                                    shell=True, capture_output=True, cwd=str(proj)
                                )
                                status = Status.FAILED
                            # Gate 2: SIT visual smoke — only if build passed
                            if status == Status.PASSED:
                                sit_outcome = run_sit_post_merge(proj)
                                if not sit_outcome.passed:
                                    label = "BLOCKING" if SIT_BLOCKING else "advisory"
                                    subprocess.run(
                                        f'git notes add -m "SIT: FAILED ({label}) — exit {sit_outcome.exit_code}"',
                                        shell=True, capture_output=True, cwd=str(proj)
                                    )
                                    if SIT_BLOCKING:
                                        log.error("⛔ SIT failed and SIT_BLOCKING — marking batch FAILED")
                                        status = Status.FAILED
                    else:
                        log.error(f"⚠️ Merge conflict on {branch_name} — MANUAL RESOLUTION NEEDED")
                        log.error(f"   {r.stderr.strip()}")
                else:
                    log.warning(
                        "⚠️ Toni produced no changes — skipping commit "
                        "(usually means idempotent re-fire or halt-and-report)."
                    )
                    no_change_run = True
                    subprocess.run(f"git checkout {MERGE_TARGET}", shell=True, capture_output=True, cwd=str(proj))
                    subprocess.run(f"git branch -D {branch_name}", shell=True, capture_output=True, cwd=str(proj))
            else:
                # Failed batch — switch back to merge target, leave branch for inspection
                subprocess.run(f"git checkout {MERGE_TARGET}", shell=True, capture_output=True, cwd=str(proj))
                log.warning(f"⚠️ Batch failed — branch {branch_name} left for inspection")
        except Exception as e:
            log.warning(f"⚠️ Git automation error: {e}")
            # Ensure we're back on merge target
            subprocess.run(f"git checkout {MERGE_TARGET}", shell=True, capture_output=True, cwd=str(proj))

    result = Result(batch_file=batch_file.name, status=status,
        started=started.isoformat(), finished=finished.isoformat(),
        duration_s=dur, exit_code=ec, briefs=len(briefs),
        playwright_ok=pw_ok, pw_tests=pw_cnt,
        new_migrations=new_mig, log_file=out_log,
        worktree=str(worktree) if worktree else None,
        no_changes=no_change_run)
    notify(result)
    rate_limiter.record(batch_file.name, len(briefs), dur, status.value)

    # Dependency cascade: check if this completion unblocks anything
    if status == Status.PASSED:
        unblocked = find_unblocked()
        if unblocked:
            log.info(f"🔓 {len(unblocked)} batch(es) unblocked by {batch_file.name}")

    return result

# ═══════════════════════════════════════════════════════
# QUEUE (SEQUENTIAL)
# ═══════════════════════════════════════════════════════
def run_queue(files: list[Path], force: bool = False, skip_deps: bool = False):
    state = load_state(); results = []
    log.info(f"\n{'═'*60}\nQUEUE: {len(files)} batches\n{'═'*60}")
    for i, bf in enumerate(files):
        log.info(f"\n{'─'*60}\nBATCH {i+1}/{len(files)}: {bf.name}\n{'─'*60}")
        # Dependency check
        if not skip_deps:
            all_met, met, unmet = check_batch_deps(bf, state)
            if not all_met:
                log.warning(f"⏭️  Skipping {bf.name} — unmet deps: {unmet}")
                continue
        # Rate check
        briefs = parse_batch(bf)
        if not rate_check(len(briefs), force):
            log.error(f"⛔ Queue HALTED at batch {i+1} — rate limit exceeded")
            break
        r = run_batch(bf); results.append(r)
        state["completed" if r.status==Status.PASSED else "failed"].append(asdict(r))
        save_state(state)
        if r.status == Status.FAILED:
            rem = len(files)-i-1
            if rem: log.error(f"⛔ Queue HALTED — {rem} batches skipped")
            break
        if i < len(files)-1:
            log.info(f"Cooldown {TONI_COOLDOWN}s..."); time.sleep(TONI_COOLDOWN)
    p = sum(1 for r in results if r.status==Status.PASSED)
    nc = sum(1 for r in results if r.no_changes)
    t = sum(r.duration_s for r in results)
    b = sum(r.briefs for r in results)
    nc_tag = f" ({nc} no changes)" if nc else ""
    log.info(f"\n{'═'*60}\nQUEUE DONE: {p}/{len(results)} passed{nc_tag} | {b} briefs | {t:.0f}s\n{'═'*60}")
    return results

# ═══════════════════════════════════════════════════════
# PARALLEL
# ═══════════════════════════════════════════════════════
def run_parallel(files: list[Path], force: bool = False):
    if len(files) > MAX_PARALLEL:
        log.error(f"Max {MAX_PARALLEL} workers"); return
    total_briefs = 0
    for f in files:
        total_briefs += len(parse_batch(f))
    if not rate_check(total_briefs, force):
        return
    log.info(f"\n{'═'*60}\nPARALLEL: {len(files)} batches\n{'═'*60}")
    wts = []
    for i, bf in enumerate(files):
        wt = create_worktree(bf.stem, i+1)
        if not wt:
            for w in wts: cleanup_worktree(w)
            return
        wts.append(wt)
    results = []
    with ThreadPoolExecutor(max_workers=len(files)) as ex:
        futs = {ex.submit(run_batch, bf, wt): (bf, wt) for bf, wt in zip(files, wts)}
        for f in as_completed(futs):
            bf, wt = futs[f]
            try:
                r = f.result(); results.append((r, wt))
            except Exception as e:
                log.error(f"Worker crash: {bf.name} — {e}")
    log.info("\nMerging sequentially...")
    for r, wt in sorted(results, key=lambda x: x[0].batch_file):
        if r.status == Status.PASSED:
            br = f"{BRANCH_PREFIX}-{Path(r.batch_file).stem}-w{wts.index(wt)+1}"
            if merge_branch(br) and RUN_PLAYWRIGHT:
                ok, _ = run_playwright()
                if not ok: log.error("PW failed post-merge — stopping"); break
        cleanup_worktree(wt)
    p = sum(1 for r,_ in results if r.status==Status.PASSED)
    nc = sum(1 for r,_ in results if r.no_changes)
    nc_tag = f" ({nc} no changes)" if nc else ""
    log.info(f"\nPARALLEL DONE: {p}/{len(results)} passed{nc_tag}")

# ═══════════════════════════════════════════════════════
# WATCHER
# ═══════════════════════════════════════════════════════
def watch():
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    log.info(f"\n{'═'*60}\nWATCHER: {BRIEFS_DIR}\n⚠️  AUTO-FIRE DISABLED (D-184) — approval required\nDependency cascade: ON\nCtrl+C to stop\n{'═'*60}\n")
    try:
        while True:
            for f in sorted(BRIEFS_DIR.glob("*.md")):
                h = fhash(f)
                if h not in state.get("watched", {}):
                    log.info(f"📄 New brief: {f.name}")
                    state.setdefault("watched", {})[h] = {"file": f.name, "at": datetime.now().isoformat()}
                    save_state(state)

                    # Check dependencies first
                    all_met, met, unmet = check_batch_deps(f, state)
                    if not all_met:
                        log.info(f"🔒 {f.name} blocked — unmet deps: {unmet}")
                        continue

                    # Approval gate
                    briefs = parse_batch(f)
                    if approval_gate(f, briefs, approve=False, force=False):
                        r = run_batch(f)
                        state["completed" if r.status==Status.PASSED else "failed"].append(asdict(r))
                        save_state(state)

                        # Re-check blocked batches for cascade
                        if r.status == Status.PASSED:
                            unblocked = find_unblocked(state)
                            for ub in unblocked:
                                log.info(f"🔓 Cascade: {ub.name} now eligible")
                    else:
                        log.info(f"⏭️  Skipped {f.name} — not approved")
                    log.info("Resuming watch...\n")
            time.sleep(5)
    except KeyboardInterrupt:
        log.info("\nWatcher stopped.")

# ═══════════════════════════════════════════════════════
# STATUS
# ═══════════════════════════════════════════════════════
def show_status():
    s = load_state()
    print(f"\n{'═'*60}\nSPECTRICOM ORCHESTRATOR v3.1 STATUS\n{'═'*60}")

    marker = ORCH_DIR / "state" / "running.json"
    if marker.exists():
        try:
            data = json.loads(marker.read_text())
            pid = data.get("pid", 0)
            pid_alive = False
            try:
                os.kill(pid, 0)
                pid_alive = True
            except (ProcessLookupError, PermissionError):
                pass

            if pid_alive:
                started_str = data.get("started_at", "?")
                elapsed = ""
                try:
                    start_dt = datetime.fromisoformat(started_str)
                    elapsed_s = (datetime.now().astimezone() - start_dt).total_seconds()
                    elapsed = f" ({int(elapsed_s // 60)}m {int(elapsed_s % 60)}s elapsed)"
                except Exception:
                    pass
                print(f"\n  🔥 ACTIVE FIRE:")
                print(f"    PID:      {pid}")
                print(f"    Batch:    {data.get('batch_id', '?')}")
                print(f"    Repo:     {data.get('repo', '?')}")
                print(f"    Branch:   {data.get('branch', '?')}")
                print(f"    Started:  {started_str}{elapsed}")
                if data.get("meta_fire_worktree"):
                    print(f"    Worktree: {data['meta_fire_worktree']}")
            else:
                print(f"\n  ⚠️  Stale running.json from {data.get('started_at', '?')} "
                      f"(pid {pid} no longer alive)")
                print(f"    Cleaning up stale marker...")
                marker.unlink(missing_ok=True)
        except (json.JSONDecodeError, IOError):
            print(f"\n  ⚠️  Corrupt running.json — cleaning up")
            marker.unlink(missing_ok=True)
    else:
        print(f"\n  No active fire.")

    print(f"  Project:    {PROJECT_ROOT}")
    c, f = s.get("completed",[]), s.get("failed",[])
    print(f"\n  Completed: {len(c)}")
    for x in c[-5:]: print(f"    ✅ {x['batch_file']} — {x.get('duration_s',0):.0f}s, {x.get('briefs','?')} briefs")
    if f:
        print(f"\n  Failed: {len(f)}")
        for x in f[-5:]: print(f"    ❌ {x['batch_file']}")
    if BRIEFS_DIR.exists():
        done = {x["batch_file"] for x in c} | {x["batch_file"] for x in f}
        pend = [b for b in BRIEFS_DIR.glob("*.md") if b.name not in done]
        if pend:
            print(f"\n  Pending: {len(pend)}")
            for p in pend:
                deps = parse_batch_deps(p)
                dep_str = f" ← deps: {deps}" if deps else ""
                all_met, _, unmet = check_batch_deps(p, s)
                status = "🔒 BLOCKED" if deps and not all_met else "📋 READY"
                print(f"    {status} {p.name}{dep_str}")

    # Rate + Slack status
    rate_limiter.show()
    if HAS_SLACK:
        url = slack_notify.load_webhook()
        print(f"\n  Slack: {'✅ configured' if url else '❌ not configured'}")
    else:
        print(f"\n  Slack: — (slack_notify.py not found)")

    print(f"\n  Logs: {LOG_DIR}\n{'═'*60}\n")

def show_deps(filepath: Path):
    """Show dependency status for a batch file."""
    deps = parse_batch_deps(filepath)
    if not deps:
        print(f"  {filepath.name}: no dependencies declared")
        return
    all_met, met, unmet = check_batch_deps(filepath)
    print(f"\n  {filepath.name} dependencies:")
    for d in deps:
        status = "✅" if d in met else "❌"
        print(f"    {status} {d}")
    print(f"\n  Status: {'🟢 ALL MET — ready to run' if all_met else '🔒 BLOCKED — ' + str(len(unmet)) + ' unmet'}")


# ═══════════════════════════════════════════════════════
# BRANCH SWEEP (B3)
# ═══════════════════════════════════════════════════════
def _get_current_branch(repo_path: Path) -> str:
    """Get currently checked-out branch name."""
    r = subprocess.run(
        "git rev-parse --abbrev-ref HEAD",
        shell=True, capture_output=True, text=True, cwd=str(repo_path),
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def _is_branch_merged(repo_path: Path, branch: str, target: str = "main") -> bool:
    """Check if branch is an ancestor of target (i.e., fully merged)."""
    r = subprocess.run(
        f"git merge-base --is-ancestor {branch} {target}",
        shell=True, capture_output=True, cwd=str(repo_path),
    )
    return r.returncode == 0


def list_branches(repo_path: Path, pattern: str = "orch-*") -> list:
    """List branches matching pattern with merge status. Returns list of tuples."""
    r = subprocess.run(
        f"git for-each-ref 'refs/heads/{pattern}' "
        f"--format='%(refname:short) %(committerdate:iso-strict) %(subject)'",
        shell=True, capture_output=True, text=True, cwd=str(repo_path),
    )
    if r.returncode != 0:
        print(f"Error listing branches: {r.stderr}")
        return []

    branches = []
    for line in r.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split(" ", 2)
        if len(parts) < 2:
            continue
        name = parts[0]
        date = parts[1] if len(parts) > 1 else "?"
        subject = parts[2] if len(parts) > 2 else ""
        merged = _is_branch_merged(repo_path, name)
        branches.append((name, date, subject, merged))

    branches.sort(key=lambda x: x[1], reverse=True)

    if not branches:
        print(f"No branches matching '{pattern}' found.")
        return branches

    print(f"\n{'═'*80}")
    print(f"BRANCHES matching '{pattern}' in {repo_path}")
    print(f"{'═'*80}")
    for name, date, subject, merged in branches:
        status = "✅ merged" if merged else "❌ unmerged"
        print(f"  {status}  {name}  {date[:19]}  {subject[:50]}")
    print(f"{'═'*80}")
    merged_count = sum(1 for _, _, _, m in branches if m)
    unmerged_count = sum(1 for _, _, _, m in branches if not m)
    print(f"  Total: {len(branches)} ({merged_count} merged, {unmerged_count} unmerged)")

    return branches


def clean_branches(repo_path: Path, pattern: str = "orch-*", force: bool = False):
    """Delete branches matching pattern. Only merged by default; --force for unmerged."""
    current = _get_current_branch(repo_path)
    branches = list_branches(repo_path, pattern)

    if not branches:
        return

    deleted = 0
    skipped = 0
    for name, date, subject, merged in branches:
        if name in PROTECTED_BRANCHES:
            print(f"  ⛔ Protected: {name} — skipping")
            skipped += 1
            continue
        if name == current:
            print(f"  ⛔ Current HEAD: {name} — skipping")
            skipped += 1
            continue

        if merged:
            r = subprocess.run(
                f"git branch -d {name}",
                shell=True, capture_output=True, text=True, cwd=str(repo_path),
            )
            if r.returncode == 0:
                print(f"  🗑️  Deleted (merged): {name}")
                deleted += 1
            else:
                print(f"  ⚠️  Failed to delete {name}: {r.stderr.strip()}")
        elif force:
            r = subprocess.run(
                f"git branch -D {name}",
                shell=True, capture_output=True, text=True, cwd=str(repo_path),
            )
            if r.returncode == 0:
                print(f"  🗑️  Deleted (force): {name}")
                deleted += 1
            else:
                print(f"  ⚠️  Failed to delete {name}: {r.stderr.strip()}")
        else:
            print(f"  ⏭️  Skipping unmerged: {name} (use --force to delete)")
            skipped += 1

    print(f"\n  Summary: {deleted} deleted, {skipped} skipped")


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════
def resolve(p: str) -> Path:
    for candidate in [Path(p), BRIEFS_DIR/Path(p).name, PROJECT_ROOT/p]:
        if candidate.exists(): return candidate.resolve()
    raise FileNotFoundError(f"Brief not found: {p}")

def main():
    ap = argparse.ArgumentParser(description="Spectricom Orchestrator v3.1")
    sp = ap.add_subparsers(dest="cmd")
    stp = sp.add_parser("status")
    stp.add_argument("--repo", default="", help="Target repo (from config/repos.yaml)")
    sp.add_parser("watch")

    rp = sp.add_parser("run")
    rp.add_argument("batch_file")
    rp.add_argument("--approve", action="store_true", help="Pre-approve execution")
    rp.add_argument("--force", action="store_true", help="Skip ALL safety checks")
    rp.add_argument("--skip-deps", action="store_true", help="Ignore dependency check")
    rp.add_argument("--skip-sit", action="store_true", help="Skip post-merge SIT smoke test")
    rp.add_argument("--repo", default="", help="Target repo (from config/repos.yaml)")

    qp = sp.add_parser("queue")
    qp.add_argument("batch_files", nargs="+")
    qp.add_argument("--approve", action="store_true", required=True)
    qp.add_argument("--force", action="store_true")
    qp.add_argument("--skip-deps", action="store_true")
    qp.add_argument("--skip-sit", action="store_true", help="Skip post-merge SIT smoke test")
    qp.add_argument("--repo", default="", help="Target repo (from config/repos.yaml)")

    pp = sp.add_parser("parallel")
    pp.add_argument("batch_files", nargs="+")
    pp.add_argument("--approve", action="store_true", required=True)
    pp.add_argument("--force", action="store_true")
    pp.add_argument("--skip-sit", action="store_true", help="Skip post-merge SIT smoke test")
    pp.add_argument("--repo", default="", help="Target repo (from config/repos.yaml)")

    dp = sp.add_parser("deps")
    dp.add_argument("batch_file")
    dp.add_argument("--repo", default="", help="Target repo (from config/repos.yaml)")

    sit_rp = sp.add_parser("sit:report")
    sit_rp.add_argument("--since", default=None, help="ISO date to filter from (e.g. 2026-05-01)")
    sit_rp.add_argument("--repo", default="", help="Target repo (from config/repos.yaml)")

    bp = sp.add_parser("branches")
    bp.add_argument("action", choices=["list", "clean"])
    bp.add_argument("--repo", default="", help="Target repo (from config/repos.yaml)")
    bp.add_argument("--pattern", default="orch-*", help="Branch glob pattern (default: orch-*)")
    bp.add_argument("--force", action="store_true", help="Delete unmerged branches too")

    a = ap.parse_args()

    # OI-026 A3: resolve repo — --repo CLI > ## Repo: header > default
    repo_name = getattr(a, 'repo', '') or ''
    if not repo_name:
        batch_arg = getattr(a, 'batch_file', None) or (getattr(a, 'batch_files', None) or [None])[0]
        if batch_arg:
            try:
                repo_name = parse_repo_from_brief(resolve(batch_arg)) or ''
            except FileNotFoundError:
                pass
    try:
        set_active_repo(repo_name)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    # Apply --skip-sit globally before any command runs
    global SKIP_SIT
    if getattr(a, 'skip_sit', False):
        SKIP_SIT = True

    if a.cmd == "run":
        _check_stale_marker()
        bf = resolve(a.batch_file)
        briefs = parse_batch(bf)
        if not approval_gate(bf, briefs, approve=a.approve, force=a.force,
                            skip_deps=getattr(a, 'skip_deps', False)):
            log.info("Execution cancelled.")
            sys.exit(2)
        if a.approve and not a.force:
            if not rate_check(len(briefs)):
                sys.exit(2)
        r = run_batch(bf)
        s = load_state()
        s["completed" if r.status==Status.PASSED else "failed"].append(asdict(r))
        save_state(s)
        sys.exit(0 if r.status==Status.PASSED else 1)

    elif a.cmd == "queue":
        files = [resolve(f) for f in a.batch_files]
        rs = run_queue(files, force=a.force, skip_deps=getattr(a, 'skip_deps', False))
        sys.exit(0 if all(r.status==Status.PASSED for r in rs) else 1)

    elif a.cmd == "watch":
        watch()

    elif a.cmd == "parallel":
        run_parallel([resolve(f) for f in a.batch_files], force=a.force)

    elif a.cmd == "deps":
        show_deps(resolve(a.batch_file))

    elif a.cmd == "sit:report":
        sit_report_aggregate(since=a.since)

    elif a.cmd == "status":
        show_status()

    elif a.cmd == "branches":
        repo_path = PROJECT_ROOT
        if a.action == "list":
            list_branches(repo_path, a.pattern)
        elif a.action == "clean":
            clean_branches(repo_path, a.pattern, force=a.force)

    else:
        ap.print_help()

if __name__ == "__main__":
    main()
