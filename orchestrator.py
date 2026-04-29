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

ORCH_DIR = Path.home() / "spectricom-orchestrator"
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

TONI_TIMEOUT = 45 * 60
TONI_COOLDOWN = 10
MAX_PARALLEL = 3
RUN_PLAYWRIGHT = False
PLAYWRIGHT_CMD = "npx playwright test"

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
    worktree: Optional[str]=None

# ═══════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════
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
    out_log = LOG_DIR / f"toni-{batch_file.stem}-{ts}.log"
    try:
        brief_rel = batch_file.relative_to(project)
    except ValueError:
        brief_rel = batch_file.name
    cmd = (
        f"cd {project} && "
        f"stdbuf -oL "
        f"claude --dangerously-skip-permissions "
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
    msg = f"{e} {result.batch_file} — {result.status.value} | {result.briefs} briefs | {result.duration_s:.0f}s"
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


# ═══════════════════════════════════════════════════════
# WORKTREES (PARALLEL)
# ═══════════════════════════════════════════════════════
def create_worktree(name: str, wid: int) -> Optional[Path]:
    wt = WORKTREE_BASE / f"toni-{wid}"
    br = f"orch-{name}-w{wid}"
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

# ═══════════════════════════════════════════════════════
# BATCH RUNNER
# ═══════════════════════════════════════════════════════
def run_batch(batch_file: Path, worktree: Optional[Path]=None) -> Result:
    proj = worktree or PROJECT_ROOT
    started = datetime.now()
    briefs_preview = parse_batch(batch_file)
    write_running(batch_file, len(briefs_preview))
    try:
        return _run_batch_inner(batch_file, proj, started, worktree)
    finally:
        clear_running()

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
    finished = datetime.now()
    dur = (finished - started).total_seconds()
    status = Status.PASSED if ec == 0 else Status.FAILED
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
        started=started.isoformat(), finished=finished.isoformat(),
        duration_s=dur, exit_code=ec, briefs=len(briefs),
        playwright_ok=pw_ok, pw_tests=pw_cnt,
        new_migrations=new_mig, log_file=out_log,
        worktree=str(worktree) if worktree else None)
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
    t = sum(r.duration_s for r in results)
    b = sum(r.briefs for r in results)
    log.info(f"\n{'═'*60}\nQUEUE DONE: {p}/{len(results)} passed | {b} briefs | {t:.0f}s\n{'═'*60}")
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
            br = f"orch-{Path(r.batch_file).stem}-w{wts.index(wt)+1}"
            if merge_branch(br) and RUN_PLAYWRIGHT:
                ok, _ = run_playwright()
                if not ok: log.error("PW failed post-merge — stopping"); break
        cleanup_worktree(wt)
    p = sum(1 for r,_ in results if r.status==Status.PASSED)
    log.info(f"\nPARALLEL DONE: {p}/{len(results)} passed")

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
# CLI
# ═══════════════════════════════════════════════════════
def resolve(p: str) -> Path:
    for candidate in [Path(p), BRIEFS_DIR/Path(p).name, PROJECT_ROOT/p]:
        if candidate.exists(): return candidate.resolve()
    raise FileNotFoundError(f"Brief not found: {p}")

def main():
    ap = argparse.ArgumentParser(description="Spectricom Orchestrator v3.1")
    sp = ap.add_subparsers(dest="cmd")
    sp.add_parser("status")
    sp.add_parser("watch")

    rp = sp.add_parser("run")
    rp.add_argument("batch_file")
    rp.add_argument("--approve", action="store_true", help="Pre-approve execution")
    rp.add_argument("--force", action="store_true", help="Skip ALL safety checks")
    rp.add_argument("--skip-deps", action="store_true", help="Ignore dependency check")

    qp = sp.add_parser("queue")
    qp.add_argument("batch_files", nargs="+")
    qp.add_argument("--approve", action="store_true", required=True)
    qp.add_argument("--force", action="store_true")
    qp.add_argument("--skip-deps", action="store_true")

    pp = sp.add_parser("parallel")
    pp.add_argument("batch_files", nargs="+")
    pp.add_argument("--approve", action="store_true", required=True)
    pp.add_argument("--force", action="store_true")

    dp = sp.add_parser("deps")
    dp.add_argument("batch_file")

    a = ap.parse_args()

    if a.cmd == "run":
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

    elif a.cmd == "status":
        show_status()

    else:
        ap.print_help()

if __name__ == "__main__":
    main()
