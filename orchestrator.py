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
  python3 orchestrator.py verify <brief-stem> [--commit <sha>]   ← one route's evidence (read-only)

Batch-level dependencies:
  Add to batch file header:  # depends_on_batches: [toni-batch-31.md, toni-batch-30.md]
"""

import os, sys, re, time, json, shlex, signal, logging, hashlib, subprocess, argparse, tempfile
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Mapping, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import prefire  # HOOK-1: pre-fire assertions (SESSION-BOOT A1/A2/A8)
# ORCH-STALEBASE-1: the branch-side invariant, asserted at the branch cut. One implementation,
# shared with the tests; canon_assert imports nothing from here.
# ORCH-CONFLICT-1: the landed invariant, asserted at the route lane's FINAL STATUS site.
# TONI-BG-CEILING-1: the executor wait-ceiling invariant, asserted at fire_toni's spawn.
# GATE-CLOCK-1: the clock-plausibility predicate, asserted at the end of every gate leg.
# ORCH-FOREGROUND-1: the executor's foreground-only environment, asserted beside the ceiling.
# ORCH-YORSIE-SAFETY-1: a brief's `#!queue repo=…`, read by the one parser the daemon fires with.
from canon_assert import (BG_WAIT_CEILING_VAR, CLOCK_HISTORY_MIN, DEFAULT_EXECUTOR_EFFORT,
                          DEFAULT_EXECUTOR_MODEL, DISABLE_BG_TASKS_VAR,
                          FOREGROUND_BOUND_VARS, ClockViolation, LegClocks, QueueRepo,
                          check_bg_ceiling_invariants, check_branch_freshness_invariants,
                          check_clock_plausibility, check_foreground_invariants,
                          check_handback_invariants, check_route_landed_invariants,
                          executor_default, load_outstanding_work_rules, queue_header)

# HOOK-1: set from --force in main(); --force already means 'ALL safety checks bypassed'.
PREFIRE_BYPASS = False

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
# QUEUE-RETIRE-1: the queue the daemon feeds this process from. Retirement happens here, in
# the process that merges — see retire_batch_file.
QUEUE_DIR = ORCH_DIR / "queue"
QUEUE_DONE = QUEUE_DIR / "done"

# Per-repo state — populated by set_active_repo(<name>) once main() has resolved the repo from --repo
# or the brief's own header. [ORCH-YORSIE-SAFETY-1] there is no default repo: until a repo is named
# these stay empty, and a command that acts on a repo refuses rather than pick one.
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
IS_META_FIRE: bool = False


def load_repo_config() -> dict:
    """Load ~/spectricom-orchestrator/config/repos.yaml and return parsed dict.

    Validates: file exists, has `repos:` key with at least one entry, and NO entry carries a
    `default:` key ([ORCH-YORSIE-SAFETY-1] — there is no default repo; one written back would read
    as working while nothing honours it). Raises RuntimeError on any violation.
    """
    if not REPOS_CONFIG_PATH.exists():
        raise RuntimeError(f"Repo config not found: {REPOS_CONFIG_PATH}")
    cfg = _yaml.safe_load(REPOS_CONFIG_PATH.read_text())
    if not isinstance(cfg, dict) or "repos" not in cfg or not cfg["repos"]:
        raise RuntimeError(f"Malformed repo config: {REPOS_CONFIG_PATH} (expected 'repos:' map)")
    declared = [n for n, r in cfg["repos"].items() if isinstance(r, dict) and "default" in r]
    if declared:
        raise RuntimeError(
            f"{REPOS_CONFIG_PATH}: `default:` on {', '.join(declared)} — there is no default repo; every "
            f"brief names its repo (ORCH-YORSIE-SAFETY-1). Remove the key."
        )
    return cfg


def set_active_repo(name: str) -> str:
    """Switch active repo and populate module-level state from repos.yaml.

    Args:
        name: Repo name (e.g. 'yorsie', 'ai-foundation', 'clinical-mp', 'orchestrator').
              Required — [ORCH-YORSIE-SAFETY-1] there is no default repo to fall back to.

    Returns:
        The active repo name.

    Raises:
        RuntimeError if name is empty or not declared in repos.yaml.
    """
    global ACTIVE_REPO_NAME, ACTIVE_REPO_CONFIG
    global PROJECT_ROOT, YORSIE_DIR, BRIEFS_DIR, WORKTREE_BASE
    global BRANCH_PREFIX, MERGE_TARGET, REMOTE, LOG_SUBDIR
    global WORKTREE_MODE, TEST_CMD, IS_META_FIRE

    if not name:
        raise RuntimeError("no repo named — there is no default repo (ORCH-YORSIE-SAFETY-1)")
    cfg = load_repo_config()
    repos = cfg["repos"]

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
    IS_META_FIRE = bool(r.get("meta_fire", False))
    return name


# [ORCH-YORSIE-SAFETY-1] nothing is populated at module load: importing this module used to make
# yorsie active (`set_active_repo()` here, the v3.3 backward-compat default), so a brief that named
# no repo landed in Yorsie. main() calls set_active_repo(<name>) once the repo is named.


def parse_repo_from_brief(filepath) -> Optional[str]:
    """The repo a brief names: its `#!queue repo=…` header (what the daemon fires it with, read by
    canon_assert.queue_header), else a `## Repo: <name>` line; None when it names none."""
    named = queue_header(Path(filepath)).get("repo")
    if named:
        return named
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
BG_WAIT_MARGIN_S = 300  # TONI-BG-CEILING-1 §2.2: CLI bg-wait ceiling = route timeout − this (>=25 m wait on a 30 m route)

# Executor model/effort (D-S7CORE3-05, S7-CORE-4 [MODEL-1]).
# Precedence: CLI --model/--effort > env TONI_MODEL/TONI_EFFORT > default.
# [EXECUTOR-DEFAULT-1] the default is canon_assert's DEFAULT_EXECUTOR_MODEL / _EFFORT, the queue
# daemon's too (D-S7CORE15-01) — no other place in the pipeline names one.
TONI_MODEL, TONI_EFFORT = executor_default(os.environ)
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
# S7-CORE-10 SIT-RATE-1: the SIT gate runs in BATCHES of files with a pause between, so one
# batch completes inside the upstream rate-limit window. Measured 2026-09-15 on clinical-mp
# @181a109: 19 files in ONE run = `_consumedPoints 50090` against `limit: 50000` → HTTP 429
# thrown in the harness login (each file's login provisions a Practitioner, so gate cost
# scales with file count: 10 files a week earlier, 19 now). The same commit in two halves
# 90 s apart: 10 files/29 tests green, then 9 files/31 tests green — 19/19, 60/60.
# Batching is ON for a repo iff it declares `sit_list_cmd` in config/repos.yaml — the command
# that ENUMERATES the suite without running it (`file > test` per line). That enumeration is
# also the whole-suite count the batched totals must reconcile against (AC-SR-05): a batching
# scheme that loses a file is worse than the rate limit. Size and pause are per-repo keys
# with these defaults; never inline a number at a call site (CLAUDE.md). SIT_TIMEOUT above
# is the budget of ONE batch (each batch is one gate invocation).
SIT_BATCH_FILES = 10
SIT_BATCH_PAUSE_S = 90
SIT_LIST_CMD_KEY = "sit_list_cmd"
SIT_BATCH_FILES_KEY = "sit_batch_files"
SIT_BATCH_PAUSE_KEY = "sit_batch_pause_s"
# SitOutcome.error values that are an ENVIRONMENT verdict on the gate's own machinery, never
# a verdict about the product (run_pre_merge_gates maps them to BLOCKED(environment)).
SIT_GATE_ENV_ERRORS = ("zero-collection", "sit-list-failed", "batch-incomplete")
# S7-CORE-7 [ORCH-2] / D-S7CORE6-05: the thin-gate floor is configuration, not a literal.
# Unset ⇒ no floor, no warning; only the collected counts are reported. Zero-collection
# blocking (§4.5) is independent of this floor and always on.
_sit_min_raw = os.environ.get("SIT_MIN_TEST_FILES", "").strip()
SIT_MIN_TEST_FILES: Optional[int] = int(_sit_min_raw) if _sit_min_raw.isdigit() else None
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

# ═══════════════════════════════════════════════════════
# UNIT SUITE BASELINE GATE (S7-CORE-8 [ORCH-3])
# George ruling 2026-09-12 (PCU v1-133 ruling 2): the unit suite gates a merge as a
# BASELINE gate, not a zero gate. Halt only when the branch is WORSE than the commit it
# forked from. A zero gate would block every merge behind pre-existing reds; a baseline
# gate stops the NEXT red entering while known debt is repaired.
# Root cause it addresses: eleven unit tests across six files under clinical-mp
# src/lib/synth/ were RED through at least two merges and nothing noticed, because
# NEITHER existing gate runs the unit suite — sit:gate covers sit/integration/** and the
# build gate runs tsc + build. Those were the seeds T2 synth UAT runs on.
# ═══════════════════════════════════════════════════════
UNIT_GATE_ENABLED = os.environ.get("DISABLE_UNIT_GATE", "") == ""  # emergency bypass, mirrors DISABLE_BUILD_GATE
UNIT_GATE_TIMEOUT = 900  # 15 min. The BRANCH leg's budget. §2.6 runs the gate last.
# S7-CORE-8 [ORCH-5]: the two legs get SEPARATE budgets, because they are not the same cost.
# Measured 2026-09-13 on clinical-mp: `npm test` is the whole repo — 773 files / 7103 tests /
# ~14 min. The branch leg fits in 900s on a warm checkout; the baseline leg runs in a fresh
# detached worktree and blew straight through it, so the very first live route returned
# `baseline-unmeasurable (timeout)` and was blocked with nothing measured. The verdict logic
# was right and the cost model was wrong. A timeout on EITHER leg is BLOCKED(environment) —
# the measurement failed, not the product.
UNIT_BASELINE_TIMEOUT = 1800  # 30 min. Per-repo override: `baseline_timeout_s` in repos.yaml.
UNIT_BASELINE_REF_PREFIX = "merge-base"  # the ref prefix that identifies the baseline leg
# Per-repo override keys read out of config/repos.yaml (ACTIVE_REPO_CONFIG). Absent ⇒ the
# defaults above. Never inline a number at a call site (CLAUDE.md).
UNIT_TIMEOUT_KEY = "test_timeout_s"
UNIT_BASELINE_TIMEOUT_KEY = "baseline_timeout_s"
# S7-CORE-9 [ORCH-6] AC-O6-07: the CONFIRMATION leg (a handful of files, not the whole
# suite) gets its own, smaller budget — generous relative to that, not to the full suite.
UNIT_CONFIRM_TIMEOUT = 300  # 5 min. Per-repo override: `confirm_timeout_s` in repos.yaml.
UNIT_CONFIRM_TIMEOUT_KEY = "confirm_timeout_s"
UNIT_CONFIRM_REF_PREFIX = "confirm"  # the ref prefix that identifies the confirmation leg
# [ORCH-5] decision 1: the baseline for a given commit is IMMUTABLE, so measure it once and
# keep it, keyed by that commit's SHA. This is what turns ~28 min per route into ~14 min once
# per merge base. It does NOT weaken §2.2 below: the number is still MEASURED on the merge
# base, by us, from a real suite run — it is simply not re-measured for a commit that has not
# changed. What §2.2 forbids is a baseline that was never measured for the commit in hand:
# main's current tip, or a hand-entered figure. Neither is reachable from here.
UNIT_BASELINE_CACHE_FILE = "unit-baseline-cache.json"   # in the sit-archive dir, gitignored
UNIT_BASELINE_CACHE_VERSION = 1
# §2.2: the baseline is MEASURED on the MERGE BASE — never stored, never read off main's
# current tip. A stored number goes stale and becomes a lie; the `test_cmd` key in
# repos.yaml that sat unconsumed through this whole incident is the cautionary precedent.
# It is measured in a DETACHED worktree so a concurrently-running route in the target repo
# keeps its working tree and its branch untouched (brief §4 STOP trigger 1).
UNIT_BASELINE_WORKTREE_PREFIX = "orch-unit-baseline-"
# A fresh detached worktree has no installed dependencies, so the baseline would fail for
# reasons that have nothing to do with the code. These git-ignored paths are symlinked in
# from the gated checkout so both sides run the same suite. Read-only use — a concurrent
# route sharing them is unaffected. The repo's declared env_file (PRE_MERGE_GATES) is
# linked too; its NAME is used, its values are never read or logged (canon §23.9d).
UNIT_BASELINE_LINK_PATHS = ("node_modules", "venv", ".venv", "yorsie/node_modules")
# A fully-green branch cannot be a regression against ANY baseline: 0 > n is false for
# every n >= 0, and an empty failing-file set cannot contain a newly-failing file. So the
# baseline run is skipped in that case and the gate costs one suite run, not two.
# Set False to always measure both sides.
UNIT_GATE_SKIP_BASELINE_WHEN_GREEN = True
# S7-CORE-9 [ORCH-7] AC-O7-04: named once is noise; named this many times is a file to
# quarantine. Never inline a number at a call site (CLAUDE.md).
UNIT_FLAKY_QUARANTINE_THRESHOLD = 2
# S7-CORE-16 [GATE-CLOCK-1]: the PLAUSIBLE wall durations of every gate leg, per (repo, leg kind) —
# the history behind canon_assert.check_clock_plausibility's outlier clause. Kept in the gate-record
# store (the archive dir beside orchestrator-sit-log.json and orchestrator-unit-log.json, gitignored):
# neither of those records a per-leg duration with the clocks that make it trustworthy, and the
# build gate records nothing at all. An implausible leg is never written here.
GATE_DURATIONS_FILE = "gate-durations.json"
GATE_DURATIONS_VERSION = 1
GATE_DURATIONS_KEEP = 20   # newest plausible samples kept per (repo, leg kind); the median reads them all

# ═══════════════════════════════════════════════════════
# PRE-MERGE GATE POLICY (S7-CORE-4 [ORCH-1] — gate-then-merge)
# Gates run ON THE ROUTE BRANCH, BEFORE the merge to MERGE_TARGET. A red gate leaves
# the branch unmerged and MERGE_TARGET untouched. (2026-09-09 incident: merge-then-gate
# let a red sit:gate land on main.)
# Eligibility is deliberately explicit per repo — there is no implicit
# "declares build_gate_cmd ⇒ gated" rule — so turning a gate on is a visible, ratified
# change. Repos absent from this table are UNGATED and that is a stated decision
# (run_pre_merge_gates returns PASS with reason "ungated by policy").
#   gates    : ordered tuple of "build" (run_build_gate) / "sit" (run_sit_post_merge)
#   env_file : dotenv sourced via GATE_ENV_SOURCE in the BUILD and SIT gate shells (never the
#              unit suite — see _run_unit_suite, [ORCH-9]), cwd = repo root,
#              values never logged (canon §23.9d). Declared-but-missing ⇒ BLOCKED(environment).
#              None ⇒ no sourcing and no requirement.
# The S7-CORE-8 [ORCH-3] unit baseline gate is deliberately NOT listed here: per that
# ruling's §2.3 its eligibility is DERIVED from each repo's `test_cmd` in config/repos.yaml
# (run_pre_merge_gates → run_unit_gate), so it covers repos with no entry in this table too.
PRE_MERGE_GATES = {
    # S6S47 / D-S6S46-B: build (tsc+build) then SIT (npm run sit:gate). Same set as before;
    # only the execution point moved (pre-merge).
    "clinical-mp":  {"gates": ("build", "sit"), "env_file": ".env"},
    # AC-ORCH1-09: meta-fire lane gated by build_gate_cmd (pytest -q). env_file=None on purpose:
    # the orchestrator's own .env.example declares ANTHROPIC_API_KEY, and sourcing that into the
    # gate shell would trip the CODE-GUARD (exit 3) inside every test that imports orchestrator.
    "orchestrator": {"gates": ("build",), "env_file": None},
    # ORCH-YORSIE-SAFETY-1 Y2 (S7-CORE-17, Yorsie PDLC plan Phase 0): Yorsie merges only what builds —
    # build_gate_cmd `cd yorsie && npm run build` (tsc -b && vite build) in repos.yaml, run on the
    # route's checkout. env_file=None on purpose: the build needs no secrets and yorsie/.env is never
    # sourced into a gate. No SIT leg yet (Phase 4); the unit leg is its test_cmd, as before.
    "yorsie":       {"gates": ("build",), "env_file": None},
    # ai-foundation / norra declare build_gate_cmd in repos.yaml but were never wired into the
    # gate lane (a836886 left the clinical-mp-only condition in place). Not widened here —
    # reported as a typed gap for ratification, not changed silently.
}
GATE_ENV_SOURCE = "set -a; . ./{env_file}; set +a"  # canon §23.9d: no set -x, no echo

# ── PDLC F-20 (first instance, defined by [ORCH-1]) ────────────────────────────────
# BLOCKED(environment) vs FAIL(product). A red gate is BLOCKED(environment) iff its combined
# stdout+stderr matches one of these signals, or a declared env_file is missing, or the gate
# names a required env var that IS a key in the repo's env_file (see _classify_gate_failure).
# Anything else red is FAIL(product). Extend F-20 by extending these tables only.
#   (signal id, regex over gate output, human description)
ENV_BLOCK_SIGNALS = (
    ("medplum-unreachable",
     r"ECONNREFUSED\s+(?:127\.0\.0\.1|localhost|\[::1\]):8103"
     r"|localhost:8103[^\n]*(?:ECONNREFUSED|fetch failed)"
     r"|(?:ECONNREFUSED|fetch failed)[^\n]*localhost:8103",
     "Medplum at http://localhost:8103 not answering"),
    ("docker-unavailable",
     r"Cannot connect to the Docker daemon|docker daemon is not running|Is the docker daemon running",
     "Docker not running"),
    ("port-in-use",
     r"\bEADDRINUSE\b",
     "required port already bound"),
    ("network-dns",
     r"\bENOTFOUND\b|\bEAI_AGAIN\b|getaddrinfo E[A-Z_]+",
     "network/DNS failure reaching a dependency"),
    ("toolchain-missing",
     r"\b(?:npx|npm|node|pytest|python3?|tsc|vitest|playwright): (?:command )?not found",
     "missing toolchain binary"),
    ("env-file-unsourceable",
     r"\./\.env: (?:line )?\d+:",
     ".env present but the shell could not source it"),
    # S7-CORE-10 [ORCH-11] AC-SR-02: transport-level refusals. 2026-09-15: Medplum answered
    # the harness login with HTTP 429 (`_consumedPoints 50090 / limit 50000`) and the gate
    # returned FAIL(product) because nothing above knew a 429 — the second false FAIL(product)
    # from this detector that night. A refusal at the transport is never a product verdict.
    # `429` is matched only in its HTTP shapes: a bare 429 is also a line number
    # (`harness.ts:429:5`), a tally (`429 passed (429)`) or an id (`obs-429`), and none of
    # those may turn a product failure into an environment one.
    ("rate-limited",
     r"Too Many Requests|_consumedPoints|\bHTTP[ /]?429\b|\bstatus(?:Code)?\W{0,3}429\b"
     r"|\bcode\W{0,3}429\b|\b429\s+Too Many",
     "upstream rate limit (HTTP 429) — the budget, not the product"),
    ("connection-refused",
     r"\bECONNREFUSED\b|\bECONNRESET\b|\bETIMEDOUT\b",
     "connection refused/reset by a dependency (any host)"),
    # The Medplum client raising for a SERVER-side refusal, before any assertion ran. Scoped
    # to the transport-class statuses on purpose: an OperationOutcomeError carrying a 400 for a
    # resource the PRODUCT built wrong is a product failure and must fall through.
    ("client-operation-outcome",
     r"^\s*OperationOutcomeError\b[^\n]*(?:Too Many Requests|Service Unavailable|Bad Gateway"
     r"|Gateway Timeout|Internal Server Error|Request Timeout|fetch failed|ECONN[A-Z]+)",
     "Medplum client raised OperationOutcomeError for a server/transport refusal, not an assertion"),
)
# A gate throw naming a required env var, e.g. "requires `MEDPLUM_CLIENT_ID`" (2026-09-09).
# Fires as signal "env-var-unsourced" only when the named var IS a key in the repo's env_file —
# the value exists but did not reach the gate shell. Key names are read; values never are.
ENV_VAR_MISSING_PATTERNS = (
    r"requires\s+[`'\"]?([A-Z][A-Z0-9_]{2,})[`'\"]?",
    r"[`'\"]?([A-Z][A-Z0-9_]{2,})[`'\"]?\s+(?:is|was)\s+(?:not set|not defined|missing|required|undefined)",
    r"[Mm]issing\s+(?:required\s+)?(?:env(?:ironment)?\s+var(?:iable)?)?\s*:?\s*[`'\"]?([A-Z][A-Z0-9_]{2,})",
)
# [ORCH-11] MULTILINE so a signal may anchor to the start of a runner error line; the
# classifier strips ANSI colour first, because vitest wraps the error name in it.
_ENV_BLOCK_SIGNALS_RE = [(sid, re.compile(rx, re.IGNORECASE | re.MULTILINE), desc) for sid, rx, desc in ENV_BLOCK_SIGNALS]
_ENV_VAR_MISSING_RE = [re.compile(rx) for rx in ENV_VAR_MISSING_PATTERNS]

# [ORCH-LANE-1] O5 · S7-CORE-19 route 108: ai-foundation's test_cmd `source venv/bin/activate && …` died in
# 0.1s under /bin/sh (`source: not found`, exit 127) and the unit gate said only `runner=unrecognised`. A
# gate command that fails this fast says how in its BLOCKED(environment) message: its exit code and the
# first lines of its stderr. The message only — which verdict a red gate gets is unchanged.
GATE_FAST_DEATH_S = 5
GATE_FAST_DEATH_STDERR_LINES = 5
GATE_STDERR_HEAD_CHARS = 4000     # what a gate leg keeps of its stderr's head, for the lines above
_GATE_STDERR_LINE_CHARS = 200


def _gate_fast_death(exit_code: int, duration_s: float, stderr_head: Optional[str],
                     elide: Optional[str] = None) -> Optional[str]:
    """`failed in 0.1s (exit 127); stderr: /bin/sh: 1: source: not found` for a gate command that exited
    non-zero in under GATE_FAST_DEATH_S; None otherwise. `stderr_head` None ⇒ no exit was observed (a
    timeout, a raise, a cached leg): None. Its first GATE_FAST_DEATH_STDERR_LINES non-blank lines, joined
    by ⏎; a line naming `elide` (the env_file a gate shell sources) is never quoted (canon §23.9d)."""
    if stderr_head is None or exit_code == 0 or duration_s >= GATE_FAST_DEATH_S:
        return None
    lines = [l.strip() for l in stderr_head.splitlines() if l.strip()][:GATE_FAST_DEATH_STDERR_LINES]
    said = " ⏎ ".join(f"<a line naming {elide}, elided — its values are never logged>" if elide and elide in l
                      else l[:_GATE_STDERR_LINE_CHARS] for l in lines)
    return f"failed in {duration_s:.1f}s (exit {exit_code}); " + (f"stderr: {said}" if said else "stderr empty")


class GateOutcome(str, Enum):
    PASS = "PASS"
    BLOCKED_ENV = "BLOCKED(environment)"
    FAIL_PRODUCT = "FAIL(product)"


@dataclass
class GateVerdict:
    outcome: GateOutcome
    gate: Optional[str] = None      # "build" | "sit" | "env" | None (ungated / all green)
    signal: Optional[str] = None    # F-20 signal id, or a short product reason
    detail: Optional[str] = None    # what triggered it — never a secret value
    collection: Optional[str] = None  # [ORCH-2] "7 files/18 tests, 6.6s" when the SIT summary parsed; None otherwise
    unit_collection: Optional[str] = None  # [ORCH-3] both sides of the unit baseline; None when the unit gate did not run

    @property
    def label(self) -> str:
        s = self.outcome.value
        if self.signal:
            s += f" — {self.gate or 'gate'}: {self.signal}"
        if self.detail:
            s += f" ({self.detail})"
        return s

PROTECTED_BRANCHES = {"main", "master", "develop", "staging"}

# ═══════════════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════════════
class Status(str, Enum):
    PENDING="pending"; RUNNING="running"; PASSED="passed"
    FAILED="failed"; SKIPPED="skipped"; BLOCKED="blocked"
    # [ORCH-10] Neither `passed` nor `failed`: the route's own git state moved under it,
    # so nothing the run observed about the product can be trusted. See TAMPER_VERDICT.
    TAMPERED="tampered"
    # [ORCH-HANDBACK-GUARD-1] Neither `passed` nor `failed`: the executor's own closing words said
    # it had not finished, so no gate was run and nothing merged. See INCOMPLETE_VERDICT.
    INCOMPLETE="incomplete"

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
    gate_outcome: Optional[str]=None  # [ORCH-1] PASS | BLOCKED(environment) | FAIL(product) | None (gate not run)
    gate_collection: Optional[str]=None  # [ORCH-2] "7 files/18 tests, 6.6s" when the SIT summary parsed; None otherwise
    unit_collection: Optional[str]=None  # [ORCH-3] "baseline merge-base abc1234: ... → branch ...", None when the unit gate did not run
    tampered: Optional[str]=None  # [ORCH-10] one-line tamper label when the route's ref moved; None on every honest run

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
def bg_wait_ceiling_ms(route_timeout_s: int) -> int:
    """[TONI-BG-CEILING-1] The CLI's background-wait ceiling for a route of `route_timeout_s`:
    BG_WAIT_MARGIN_S below the route, or half of it for tiny (<= 600 s) env-override routes."""
    if route_timeout_s > 2 * BG_WAIT_MARGIN_S:
        return (route_timeout_s - BG_WAIT_MARGIN_S) * 1000
    return route_timeout_s * 1000 // 2


def toni_child_env(route_timeout_s: int, base: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    """[TONI-BG-CEILING-1] The executor's explicit environment: a copy of `base` (os.environ, read
    now, when None) with BG_WAIT_CEILING_VAR OVERRIDDEN — an inherited value, 0 included, never
    survives. Mutates neither `base` nor os.environ.
    [ORCH-FOREGROUND-1] Likewise overridden: DISABLE_BG_TASKS_VAR = "1" (no background to lose),
    and the Bash tool's default and maximum timeouts — ONE bound for all of FOREGROUND_BOUND_VARS,
    bg_wait_ceiling_ms(T): a foreground command may run long, never past the route."""
    env = dict(os.environ if base is None else base)
    bound = str(bg_wait_ceiling_ms(route_timeout_s))
    for var in FOREGROUND_BOUND_VARS:
        env[var] = bound
    env[DISABLE_BG_TASKS_VAR] = "1"
    return env


def _toni_trailer(out_log: Path, exit_note: str):
    """[ORCH-TIMEOUT-HOLD-1] the trailer fire_toni's normal path writes, for the paths that never reach
    it: `Finished:` and `Exit: <code> (<why>)`, appended — so handback-scan, the guard's
    _executor_output and a human all see where the executor stopped and why."""
    try:
        with open(out_log, "a") as lf:
            lf.write(f"\n{'='*60}\nFinished: {datetime.now().isoformat()}\nExit: {exit_note}\n")
    except OSError as e:
        log.error(f"Toni log trailer not written ({out_log}): {e}")


def fire_toni(batch_file: Path, project: Path=PROJECT_ROOT) -> tuple[int, str]:
    route_timeout_s = TONI_TIMEOUT  # TONI-BG-CEILING-1: read once — the wait bound and the ceiling cannot diverge
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
        f"--model {TONI_MODEL} --effort {TONI_EFFORT} "
        f'"Read {brief_rel} and execute all briefs in order. Run every command in the foreground and '
        f'wait for it to finish; never use run_in_background — background tasks are killed when your '
        f'turn ends and no follow-up turn will come."'
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
    log.info(f"  Timeout: {route_timeout_s // 60}m")
    env = toni_child_env(route_timeout_s)
    v = check_bg_ceiling_invariants("orchestrator.fire_toni", env, route_timeout_s)
    if v:
        log.error(f"⛔ Toni NOT fired — bg-wait ceiling: {v[0]}")
        log.error(f"🛡 bg-wait-ceiling: BLOCKED — {v[0].reason}; not fired")
        return -2, str(out_log)
    fv = check_foreground_invariants("orchestrator.fire_toni", env, route_timeout_s)
    if fv:
        log.error(f"⛔ Toni NOT fired — foreground: {fv[0]}")
        log.error(f"🛡 bg-wait-ceiling: BLOCKED — {fv[0].reason} ({fv[0].var}); not fired")
        return -2, str(out_log)
    ceiling_ms = env[BG_WAIT_CEILING_VAR]
    foreground = f"{DISABLE_BG_TASKS_VAR}=1, " + ", ".join(f"{k}={env[k]}" for k in FOREGROUND_BOUND_VARS[1:])
    log.info(f"🛡 bg-wait-ceiling: CLEAN — {BG_WAIT_CEILING_VAR}={ceiling_ms} < {1000 * route_timeout_s} "
             f"(route timeout {route_timeout_s}s); foreground: {foreground}")
    log.info(f"  BG wait ceiling: {ceiling_ms}ms ({BG_WAIT_CEILING_VAR}; route timeout {route_timeout_s}s, margin {BG_WAIT_MARGIN_S}s)")
    log.info(f"  Log: {out_log}")
    try:
        with open(out_log, "w") as lf:
            lf.write(f"=== TONI EXECUTION ===\nBatch: {batch_file.name}\n")
            lf.write(f"Started: {datetime.now().isoformat()}\nCommand: {cmd}\n")
            lf.write(f"BgWaitCeilingMs: {ceiling_ms} (route timeout {route_timeout_s}s, margin {BG_WAIT_MARGIN_S}s)\n")
            lf.write(f"Foreground: {foreground}\n{'='*60}\n\n")
            lf.flush()
            proc = subprocess.Popen(cmd, shell=True, executable="/bin/bash",
                stdout=lf, stderr=subprocess.STDOUT, cwd=str(project),
                preexec_fn=os.setsid, env=env)
            ec = proc.wait(timeout=route_timeout_s)
            lf.write(f"\n{'='*60}\nFinished: {datetime.now().isoformat()}\nExit: {ec}\n")
        log.info(f"Toni finished: exit {ec}")
        return ec, str(out_log)
    except subprocess.TimeoutExpired:
        log.error(f"Toni TIMEOUT after {route_timeout_s//60}m")
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        time.sleep(3)
        try: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError: pass
        _toni_trailer(out_log, f"-1 (TIMEOUT after {route_timeout_s // 60}m — SIGTERM, SIGKILL)")
        return -1, str(out_log)
    except Exception as e:
        log.error(f"Toni error: {e}")
        _toni_trailer(out_log, f"-2 ({type(e).__name__}: {e})")
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

# ═══════════════════════════════════════════════════════
# [ORCH-10] ROUTE REF INTEGRITY — detect, never repair
# ═══════════════════════════════════════════════════════
# 2026-09-15: a `git checkout main` run by a human in a live route's working
# directory, 84s after the fire, sent the executor's commit onto `main` instead of
# onto the route branch. The orchestrator looked at its branch, correctly found no
# changes, and returned `passed | gate: not run` — so a commit reached `main` with
# no build gate, no SIT gate and no unit baseline gate.
#
# [ORCH-1] gate-then-merge was not violated; it was bypassed from outside, and the
# orchestrator could not tell. Two states must never look alike:
#   "I ran, and chose to change nothing."  -> passed (no changes), a good outcome
#   "My branch is not where I left it."    -> not passed at all
#
# This code makes the system NOTICE. It deliberately does not prevent (the operating
# rule — never run git in a repo with a live route — lives in LESSONS.md) and it
# deliberately does not repair: a wrong automatic reset on `main` is far worse than a
# loud stop. Every git command below is read-only.

TAMPER_VERDICT = "TAMPERED"  # greppable in the FINAL STATUS line and in orchestrator-unit-log.json
# [ORCH-CONFLICT-1] greppable in the FINAL STATUS gate field. Not a GateOutcome: the gate said PASS
# and was right; it is the merge that followed it that did not land.
MERGE_CONFLICT_VERDICT = "MERGE CONFLICT"
# [ORCH-HANDBACK-GUARD-1] greppable in the FINAL STATUS gate field. Not a GateOutcome: no gate ran.
# Neither product nor environment — the executor said it had not finished.
INCOMPLETE_VERDICT = "INCOMPLETE(executor)"
# [ORCH-TIMEOUT-HOLD-1] likewise Status.INCOMPLETE, not a GateOutcome: the executor did not exit 0 and
# left work on the tree — fire_toni killed it at the route timeout (-1), or anything else (-2, a
# signal, a non-zero exit). No gate ran; the work sits on its branch for a person to salvage.
INCOMPLETE_TIMEOUT_VERDICT = "INCOMPLETE(timeout)"
INCOMPLETE_EXECUTOR_ERROR_VERDICT = "INCOMPLETE(executor-error)"
HANDBACK_GUARD_CONFIG = ORCH_DIR / "config" / "handback-guard.json"


def _git_read(cmd: str, cwd: Path) -> str:
    """stdout of a read-only git command, stripped; "" on any failure."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=str(cwd))
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _snapshot_heads(proj: Path) -> dict:
    """Every local branch -> its SHA. The S3 baseline: anything that moves here and is
    not the route's own branch is a commit the route did not own."""
    out = _git_read("git show-ref --heads", proj)
    heads = {}
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            heads[parts[1]] = parts[0]
    return heads


@dataclass
class RouteHandoff:
    """[ORCH-10] S1 — the route's expected git state at the moment control passes to the
    executor. Captured once, immediately before fire_toni()."""
    branch: Optional[str]              # branch name the orchestrator resolved, or None
    branch_sha: Optional[str]          # that branch's SHA at hand-off
    head_ref: Optional[str]            # 'refs/heads/<x>'; None when HEAD was already detached
    head_sha: Optional[str]
    heads: dict = field(default_factory=dict)  # ref -> sha for every local branch


@dataclass
class TamperReport:
    """[ORCH-10] S2/S3 — a description of what moved. Never a repair instruction."""
    expected_ref: Optional[str]
    found_ref: Optional[str]
    branch: Optional[str]
    branch_sha_at_handoff: Optional[str]
    branch_sha_now: Optional[str]
    stray: list = field(default_factory=list)  # [{"ref","was","now","commits":[sha,...]}]

    @property
    def label(self) -> str:
        """One line for FINAL STATUS / notify / Result.tampered. Names both refs (AC-O10-01)."""
        s = (f"{TAMPER_VERDICT} — route ref moved: expected {self.expected_ref or '(none)'}, "
             f"found {self.found_ref or '(detached HEAD)'}")
        if self.stray:
            n = sum(len(x["commits"]) for x in self.stray)
            s += f"; {n} commit(s) on {len(self.stray)} ref(s) the route did not own"
        return s

    def log_lines(self) -> list:
        """The loud log. A human reading only this knows exactly what to look at."""
        out = [
            f"🚨 {TAMPER_VERDICT}: the route's git state moved between hand-off and return.",
            f"   expected HEAD on : {self.expected_ref or '(none — HEAD was detached at hand-off)'}",
            f"   found HEAD on    : {self.found_ref or '(detached HEAD)'}",
            f"   route branch     : {self.branch or '(none)'} "
            f"— was {(self.branch_sha_at_handoff or '(absent)')[:7]}, "
            f"now {(self.branch_sha_now or '(absent)')[:7]}",
        ]
        for x in self.stray:
            out.append(f"   ⚠️  commits on a ref this route did not own: {x['ref']} "
                       f"{x['was'][:7] if x['was'] else '(new)'} → {x['now'][:7]}")
            for sha in x["commits"]:
                out.append(f"        {sha}")
        out += [
            "   NO gate was run. NO merge was performed. NO ref was modified by the orchestrator.",
            "   This is neither `passed` nor `failed(product)` — the run observed a repo that is",
            "   not the one it was handed. Inspect by hand before trusting anything above.",
        ]
        return out


def capture_handoff(proj: Path, branch_name: Optional[str]) -> RouteHandoff:
    """[ORCH-10] S1. Called immediately before fire_toni(), in the route's working dir."""
    head_ref = _git_read("git symbolic-ref --quiet HEAD", proj) or None
    return RouteHandoff(
        branch=branch_name,
        branch_sha=_git_read(f"git rev-parse --verify {branch_name}", proj) or None if branch_name else None,
        head_ref=head_ref,
        head_sha=_git_read("git rev-parse HEAD", proj) or None,
        heads=_snapshot_heads(proj),
    )


def check_route_integrity(proj: Path, h: RouteHandoff) -> Optional[TamperReport]:
    """[ORCH-10] S2. Re-check name, SHA and HEAD ref on return — BEFORE the no-changes
    decision. Returns None on an honest run (S4: that path must stay byte-identical),
    a TamperReport when HEAD is no longer on the ref the route was handed.

    S3: the report also names commits that landed on refs the route did not own, with
    their SHAs. It does not move, reset, revert or delete anything."""
    head_ref_now = _git_read("git symbolic-ref --quiet HEAD", proj) or None
    if head_ref_now == h.head_ref:
        return None  # honest run — including the legitimate no-changes case

    branch_ref = f"refs/heads/{h.branch}" if h.branch else None
    report = TamperReport(
        expected_ref=h.head_ref,
        found_ref=head_ref_now,
        branch=h.branch,
        branch_sha_at_handoff=h.branch_sha,
        branch_sha_now=_git_read(f"git rev-parse --verify {h.branch}", proj) or None if h.branch else None,
    )

    # S3 — damage detection. Any local head other than the route's own that advanced.
    for ref, now in _snapshot_heads(proj).items():
        if ref == branch_ref:
            continue
        was = h.heads.get(ref)
        if was == now:
            continue
        rng = f"{was}..{now}" if was else now
        commits = _git_read(f"git log --oneline --no-decorate {rng}", proj).splitlines()
        report.stray.append({"ref": ref, "was": was, "now": now, "commits": commits})
    return report


def _log_tamper_outcome(archive: Path, repo_path: Path, report: TamperReport):
    """[ORCH-10] AC-O10-05 — the tampered verdict is persisted alongside the unit-gate
    entries, in the same file, carrying `verdict: TAMPERED`. Grep the archive for
    TAMPERED and every such run surfaces; no honest entry ever carries that key."""
    archive.mkdir(parents=True, exist_ok=True)
    log_file = archive / "orchestrator-unit-log.json"
    entries = []
    if log_file.exists():
        try:
            entries = json.loads(log_file.read_text())
        except (json.JSONDecodeError, IOError):
            entries = []
    entries.append({
        "timestamp": datetime.now().isoformat(),
        "repo": str(repo_path),
        "repo_name": ACTIVE_REPO_NAME,
        "verdict": TAMPER_VERDICT,
        "passed": False,
        "signal": "route-ref-moved",
        "detail": report.label,
        "expected_ref": report.expected_ref,
        "found_ref": report.found_ref,
        "branch": report.branch,
        "branch_sha_at_handoff": report.branch_sha_at_handoff,
        "branch_sha_now": report.branch_sha_now,
        "stray_commits": report.stray,
        "baseline": None,
        "branch_run": None,
    })
    log_file.write_text(json.dumps(entries, indent=2))


def _gate_status_label(gate_error: Optional[str], gate_outcome: Optional[str],
                       gate_collection: Optional[str], unit_collection: Optional[str] = None,
                       tampered: Optional[str] = None, incomplete: Optional[str] = None,
                       incomplete_verdict: str = INCOMPLETE_VERDICT) -> str:
    """[ORCH-2] `PASS (7 files/18 tests, 6.6s)` when the SIT summary parsed; the prior wording
    (`PASS` / verdict label / `not run`) when it did not.
    [ORCH-3] appends ` | unit: <baseline> → <branch>` when the unit baseline gate ran.
    [ORCH-10] a tampered run never ran a gate, and says so in a way that cannot be misread
    as the ordinary ungated `not run`.
    [ORCH-HANDBACK-GUARD-1] likewise an incomplete route: `incomplete` is "<rule> at line <n>".
    [ORCH-TIMEOUT-HOLD-1] or "exit <ec>", under its own `incomplete_verdict`."""
    if tampered:
        return f"not run ({TAMPER_VERDICT} — route ref moved)"
    if incomplete:
        return f"not run ({incomplete_verdict} — {incomplete})"
    s = gate_error or gate_outcome or "not run"
    if gate_collection:
        s = f"{s} ({gate_collection})"
    if unit_collection:
        s = f"{s} | unit: {unit_collection}"
    return s

def notify(result: Result):
    e = "✅" if result.status == Status.PASSED else ("🚧" if result.status == Status.BLOCKED else
        ("🚨" if result.status == Status.TAMPERED else "❌"))
    status_label = "passed (no changes)" if result.no_changes and result.status == Status.PASSED else result.status.value
    msg = f"{e} {result.batch_file} — {status_label} | {result.briefs} briefs | {result.duration_s:.0f}s"
    if result.tampered:
        # [ORCH-10] the gate is named even though none ran — silence here is what made the
        # 2026-09-15 incident read as an ordinary halt-and-report.
        msg += f" | gate: {_gate_status_label(None, None, None, None, result.tampered)}"
    elif result.gate_outcome:
        msg += f" | gate: {_gate_status_label(None, result.gate_outcome, result.gate_collection, result.unit_collection)}"
    if result.error:
        msg += f"\n  {result.error}"
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
    """Write running.json so dashboard knows what's executing. [QUEUE-PAUSE-OPAQUE] With the pid, so
    a marker a killed route leaves behind is judged dead by the queue daemon (P-STALE), not waited on."""
    RUNNING_FILE.write_text(json.dumps({
        "batch_file": batch_file.name,
        "briefs": brief_count,
        "started": datetime.now().isoformat(),
        "log_file": log_file,
        "pid": os.getpid(),
    }, indent=2))

def clear_running():
    """Remove running.json when execution completes."""
    try:
        RUNNING_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ── the fire lock (S7-CORE-8 [ORCH-4]) ────────────────────────────────────────────────
# The lock is PER REPO. System Prompt §5.19.1 holds that cross-repo parallel fires are safe —
# different worktrees, different merge targets, no collision — and that was true of the design
# and false of this implementation: one global `state/running.json` refused a clinical-mp route
# while an orchestrator meta-fire held it (observed 2026-09-12). Within a repo the lock is
# still serial; across repos it no longer refuses.
#
# Two files, deliberately:
#   state/running-<repo>.json  — the LOCK. One per repo. This is what is taken and released.
#   state/running.json         — a MIRROR of the newest live lock, maintained for the readers
#                                that predate per-repo locking and know only this path:
#                                qstat.sh, watchdog.sh, and show_status() below. A migration
#                                that orphans a reader is worse than the bug it fixes
#                                (brief decision 2), so the old path keeps working.
# The mirror is derived, never authoritative: every write and every clear rebuilds it from the
# per-repo locks, so it can go stale only for as long as one call takes.
_RUNNING_MARKER_GLOB = "running-*.json"


def _marker_repo_slug(repo_name: str) -> str:
    """Repo name → a filename component. Never empty, never a path traversal."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", (repo_name or "").strip()).strip("-.")
    return slug or "unknown"


def _running_marker_dir() -> Path:
    # Resolved per call, not at import: ORCH_DIR is patched in tests and the marker must
    # follow it.
    return ORCH_DIR / "state"


def _legacy_running_marker() -> Path:
    """state/running.json — the pre-[ORCH-4] path. Kept as a mirror, see above."""
    return _running_marker_dir() / "running.json"


def _running_marker_path(repo_name: Optional[str] = None) -> Path:
    """The lock file for `repo_name`. With no repo, the legacy path — that is the shape the
    pre-[ORCH-4] callers and tests use, and it still means "the fire", globally."""
    if not repo_name:
        return _legacy_running_marker()
    return _running_marker_dir() / f"running-{_marker_repo_slug(repo_name)}.json"


def _pid_alive(pid) -> Optional[bool]:
    """True / False / None where None is "exists but is not ours to signal" (PermissionError).
    None is treated as ALIVE by the lock — refusing a live fire we cannot prove is dead is the
    safe direction."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return None


def _read_marker(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, IOError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _refresh_legacy_running_mirror():
    """Rebuild state/running.json from the per-repo locks: the newest one, or nothing at all.

    Called after every write and every clear. A stale per-repo lock is NOT cleaned here —
    cleanup is the lock check's job and is scoped to one repo (brief decision 3); the mirror
    only reflects what the lock files say."""
    legacy = _legacy_running_marker()
    # A LIVE lock always wins over a dead one, whatever the timestamps say: the single-file
    # readers ask "is a fire running?", and answering with a corpse while a real fire burns
    # would be the [ORCH-4] bug again in miniature. With only dead locks left, the newest of
    # those is mirrored — qstat.sh's "stale PID" branch is a real, reachable report.
    newest = None
    newest_live = False
    for p in sorted(_running_marker_dir().glob(_RUNNING_MARKER_GLOB)):
        data = _read_marker(p)
        if data is None:
            continue
        live = _pid_alive(data.get("pid", 0)) is not False
        if newest is None or (live, str(data.get("started_at", ""))) > \
                (newest_live, str(newest.get("started_at", ""))):
            newest, newest_live = data, live
    try:
        if newest is None:
            legacy.unlink(missing_ok=True)
        else:
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_text(json.dumps(newest, indent=2))
    except OSError:
        pass


def _write_running_marker(batch_file: Path, repo_name: str, repo_path: Path,
                          branch: str, meta_fire_worktree: Optional[Path],
                          is_self_mod: bool, route_worktree: Optional[Path] = None):
    """Take the fire lock for `repo_name`: state/running-<repo>.json, plus the mirror.
    [ORCH-CONTROL-SCOPE-1] `route_worktree`: the tree a `worktree_mode: parallel` route runs in — the
    route's tree for qstat.sh, and the daemon's sign that the main checkout was never the route's."""
    marker_dir = _running_marker_dir()
    marker_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        "pid": os.getpid(),
        "batch_id": batch_file.stem,
        "repo": repo_name,
        "repo_path": str(repo_path),
        "branch": branch,
        "started_at": datetime.now().astimezone().isoformat(),
        "meta_fire_worktree": str(meta_fire_worktree) if meta_fire_worktree else None,
        "route_worktree": str(route_worktree) if route_worktree else None,
        "is_self_mod": is_self_mod,
    }, indent=2)
    _running_marker_path(repo_name).write_text(payload)
    _refresh_legacy_running_mirror()


def _clear_running_marker(repo_name: Optional[str] = None):
    """Release the fire lock.

    With a repo: release THAT repo's lock only — another repo's live fire is untouched.
    Without one (the pre-[ORCH-4] call shape): release every lock this process owns, plus the
    mirror. Either way the mirror is rebuilt afterwards, so a still-live fire in another repo
    reappears in state/running.json immediately."""
    if repo_name:
        try:
            _running_marker_path(repo_name).unlink(missing_ok=True)
        except OSError:
            pass
    else:
        me = os.getpid()
        for p in list(_running_marker_dir().glob(_RUNNING_MARKER_GLOB)):
            data = _read_marker(p)
            if data is None or data.get("pid") == me:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
        try:
            _legacy_running_marker().unlink(missing_ok=True)
        except OSError:
            pass
    _refresh_legacy_running_mirror()


def _lock_candidates(repo_name: Optional[str]) -> list:
    """The marker files the lock check must consider for `repo_name`.

    Scoped deliberately (brief decision 3): with a repo, only that repo's lock — and, when it
    has none yet, a pre-[ORCH-4] mirror that names it (or names nobody), so a marker written by
    the old code is still honoured and still cleaned. Repo B's lock is never in repo A's list,
    so a dead PID under A can never clear B."""
    if not repo_name:
        # Legacy/global shape: any live fire anywhere refuses.
        paths = sorted(_running_marker_dir().glob(_RUNNING_MARKER_GLOB))
        legacy = _legacy_running_marker()
        if legacy.exists():
            paths.append(legacy)
        return paths
    own = _running_marker_path(repo_name)
    if own.exists():
        return [own]
    legacy = _legacy_running_marker()
    if legacy.exists():
        data = _read_marker(legacy)
        if data is None or data.get("repo") in (None, "", repo_name):
            return [legacy]
    return []


def _check_stale_marker(repo_name: Optional[str] = None) -> bool:
    """Take-or-refuse the fire lock at startup, for `repo_name`.

    Returns True if safe to proceed. Exits with code 4 if a fire is already live FOR THIS REPO.
    A fire in a different repo is not this repo's business and does not refuse it (AC-O4-01).
    """
    for marker in _lock_candidates(repo_name):
        data = _read_marker(marker)
        if data is None:
            marker.unlink(missing_ok=True)
            continue

        pid = data.get("pid", 0)
        alive = _pid_alive(pid)
        if alive is False:
            log.warning(
                f"⚠️  Stale running.json from {data.get('started_at', '?')} "
                f"(pid {pid} no longer alive); cleaned up."
            )
            marker.unlink(missing_ok=True)
            continue

        # Alive, or alive-but-not-ours-to-signal. Refuse, and NAME THE REPO (AC-O4-02) —
        # "another fire" on line 2 of a log whose line 1 says `Executor: …` reads as progress.
        who = data.get("repo") or repo_name or "?"
        _refresh_legacy_running_mirror()
        print(
            f"❌ A fire is already in progress for repo '{who}' "
            f"(pid {pid}, batch {data.get('batch_id', '?')}, "
            f"started {data.get('started_at', '?')}). "
            f"Wait or kill the existing process. "
            f"Fires for OTHER repos are not blocked by this lock.",
            file=sys.stderr,
        )
        sys.exit(4)

    _refresh_legacy_running_mirror()
    return True


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


def _gate_parallel_branch(wt: Path, br: str) -> "GateVerdict":
    """[ORCH-CONTROL-SCOPE-1] C5 / ORCH-PARALLEL-GATE-1: the route lane's pre-merge gate, for one
    `parallel` worker's branch, in its own worktree. The worker's uncommitted output is committed on
    its branch first — the route lane's `git add -A` — so the gate judges exactly what a merge would
    bring in. PASS merges; anything else preserves the branch, with a git note, as the route lane does."""
    subprocess.run("git add -A", shell=True, capture_output=True, cwd=str(wt))
    if subprocess.run("git diff --cached --quiet", shell=True, capture_output=True, cwd=str(wt)).returncode != 0:
        r = subprocess.run(f'git commit -m "fix: {br} — parallel worker output"', shell=True,
                           capture_output=True, text=True, cwd=str(wt))
        log.info(f"📦 Committed {br}'s uncommitted output before its gate" if r.returncode == 0
                 else f"⚠️ Commit failed on {br}: {r.stderr.strip()}")
    try:
        v = run_pre_merge_gates(wt, br)
    except Exception as e:
        v = _classify_gate_failure("build", str(e), wt, -1)
        log.error(f"⛔ Pre-merge gate raised on {br}: {e} → {v.label}")
    if v.outcome is not GateOutcome.PASS:
        subprocess.run(f'git notes add -m "PRE-MERGE GATE: {v.outcome.value} — {v.gate}: {v.signal}"',
                       shell=True, capture_output=True, cwd=str(wt))
        log.error(f"⛔ {v.outcome.value} — {MERGE_TARGET} NOT merged. Branch preserved: {br}. {v.label}")
    return v


# ── [ORCH-CONTROL-SCOPE-1] C4 · YORSIE-WORKTREE-1: the single route of a `worktree_mode: parallel` repo ──
# Yorsie's project_dir is the tree yorsie-dev.service (:5175) serves. Until this, a Yorsie route cut its
# branch there, the executor wrote there for the whole route and the gate built there: the dev server
# served a half-written, ungated branch (logs/yorsie/orch-97-*.log, orch-98-*.log: `Project:
# /home/gkassa/spectricom-dev-pipeline`), although repos.yaml declared `worktree_mode: parallel`.
# Now the route runs, is gated and merges in <worktree_base>/<route>. The main checkout's branch is never
# switched, and MERGE_TARGET moves there only by fast-forward, after a PASS.
ROUTE_NOT_LANDED_VERDICT = "NOT LANDED"


def _create_route_worktree(batch_file: Path) -> tuple[Optional[Path], str]:
    """(<WORKTREE_BASE>/<route>, "") detached at MERGE_TARGET — _run_batch_inner cuts the route branch in
    it exactly as in a single-stream checkout — or (None, why). A worktree an earlier attempt of the same
    route left (kept on failure) is never reused or removed: this one gets a `-<ts>` suffix. The
    git-ignored dependency trees are linked from the main checkout (_link_unit_deps, the unit baseline's
    rule), so the executor and the gate see the node_modules the dev tree builds with."""
    if WORKTREE_BASE.resolve() == PROJECT_ROOT.resolve():
        return None, (f"worktree_mode: parallel needs a worktree_base outside {PROJECT_ROOT} "
                      f"(config/repos.yaml, repo {ACTIVE_REPO_NAME})")
    wt = WORKTREE_BASE / batch_file.stem
    if wt.exists():
        wt = WORKTREE_BASE / f"{batch_file.stem}-{datetime.now():%Y%m%d-%H%M%S}"
    try:
        WORKTREE_BASE.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return None, f"cannot create {WORKTREE_BASE}: {e}"
    r = subprocess.run(f"git -C {shlex.quote(str(PROJECT_ROOT))} worktree add --detach "
                       f"{shlex.quote(str(wt))} {shlex.quote(MERGE_TARGET)}",
                       shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        return None, f"git worktree add {wt} {MERGE_TARGET} failed: {r.stderr.strip()[-300:]}"
    links = _link_unit_deps(PROJECT_ROOT, wt)
    log.info(f"🌳 Route worktree: {wt} (from {MERGE_TARGET}; {len(links)} dependency path(s) linked from "
             f"{PROJECT_ROOT}) — the main checkout is not the route's")
    return wt, ""


def _finish_route_worktree(wt: Path, result: Optional["Result"]):
    """A route that merged, or changed nothing, leaves no worktree; any other keeps it, named in the log.
    The dependency links are removed first, so the removal can never reach into the main checkout."""
    branch = _git_read("git rev-parse --abbrev-ref HEAD", wt) or "?"
    if result is None or result.status != Status.PASSED:
        log.warning(f"🌳 Route worktree preserved: {wt} (branch {branch}). After review: "
                    f"git -C {PROJECT_ROOT} worktree remove {wt}")
        return
    env_name, _ = _gate_env_file(PROJECT_ROOT)
    for rel in list(UNIT_BASELINE_LINK_PATHS) + ([env_name] if env_name else []):
        if (wt / rel).is_symlink():
            try:
                (wt / rel).unlink()
            except OSError as e:
                log.warning(f"⚠️ Route worktree: could not unlink {rel}: {e}")
    subprocess.run(f"git -C {shlex.quote(str(PROJECT_ROOT))} worktree remove --force {shlex.quote(str(wt))}",
                   shell=True, capture_output=True)
    subprocess.run(f"git -C {shlex.quote(str(PROJECT_ROOT))} worktree prune", shell=True, capture_output=True)
    log.info(f"🌳 Route worktree removed: {wt}")


def _checkout_holding(branch: str, repo: Path) -> Optional[Path]:
    """The checkout (main or linked worktree) that has refs/heads/<branch> checked out, or None."""
    path = None
    for line in _git_read("git worktree list --porcelain", repo).splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
        elif line == f"branch refs/heads/{branch}" and path is not None:
            return path
    return None


def _leave_route_branch(proj: Path, route_wt: Optional[Path], detach: bool = False):
    """The route lane's `git checkout MERGE_TARGET` once a route is done with its branch. A route
    worktree stays on its branch instead (kept, named, for inspection) — or, `detach`, lets go of it so
    the branch can be deleted; MERGE_TARGET belongs to the main checkout, which a route never switches."""
    if route_wt is None:
        subprocess.run(f"git checkout {MERGE_TARGET}", shell=True, capture_output=True, cwd=str(proj))
    elif detach:
        subprocess.run("git checkout -q --detach", shell=True, capture_output=True, cwd=str(proj))


def _land_from_route_worktree(wt: Path, branch: str, toni_commits: int) -> Optional[str]:
    """Merge a gated route branch into MERGE_TARGET from its worktree. None when it landed; else the
    verdict, with the branch checked out again in the kept worktree and MERGE_TARGET untouched.

    The merge is made in the worktree, on a detached HEAD at MERGE_TARGET's tip, so a conflict is met
    and aborted there, never in the main checkout. MERGE_TARGET then moves by fast-forward only: in the
    checkout that holds it (`git merge --ff-only`, which refuses rather than overwrite a local change),
    or by a compare-and-swap `update-ref` when no checkout holds it."""
    def git(cmd: str, cwd: Path = wt) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=str(cwd))

    pre = _git_read(f"git rev-parse {MERGE_TARGET}", wt)
    d = git(f"git checkout -q --detach {MERGE_TARGET}")
    if d.returncode != 0:
        git(f"git checkout -q {branch}")
        return f"{ROUTE_NOT_LANDED_VERDICT} — the route worktree {wt} could not detach at {MERGE_TARGET}: {d.stderr.strip()[-300:]}"
    r = git(f"git merge {branch} --no-edit -m \"Merge branch '{branch}'\"")
    if r.returncode != 0:
        unmerged = git("git diff --name-only --diff-filter=U").stdout.split()
        a = git("git merge --abort")
        if a.returncode != 0:
            log.error(f"❌ git merge --abort failed in {wt}: {a.stderr.strip()}")
        git(f"git checkout -q {branch}")
        log.error(f"⚠️ Merge conflict on {branch}, met in the route worktree {wt} — MANUAL RESOLUTION NEEDED")
        return f"{MERGE_CONFLICT_VERDICT} — {branch} → {MERGE_TARGET} ({', '.join(unmerged)})"
    merged = _git_read("git rev-parse HEAD", wt)
    ff_ref = branch if merged == _git_read(f"git rev-parse {branch}", wt) else merged
    holder = _checkout_holding(MERGE_TARGET, wt)
    if holder is not None:
        r, how = git(f"git merge --ff-only {ff_ref}", cwd=holder), f"fast-forwarded in {holder}"
    else:
        r = git(f'git update-ref -m "merge {branch}: Fast-forward" refs/heads/{MERGE_TARGET} {merged} {pre}')
        how = "ref moved (no checkout holds it)"
    post = _git_read(f"git rev-parse {MERGE_TARGET}", wt)
    if r.returncode != 0 or (post == pre and toni_commits > 0):
        git(f"git checkout -q {branch}")
        where = f"checked out at {holder}" if holder else "checked out nowhere"
        why = (r.stderr or r.stdout).strip()[-300:] if r.returncode != 0 else f"its tip is unchanged ({pre[:7]})"
        return (f"{ROUTE_NOT_LANDED_VERDICT} — {MERGE_TARGET} is {where} and did not fast-forward to the merged "
                f"commit {merged[:7]}: {why}")
    log.info(f"🔀 Merged {branch} → {MERGE_TARGET} ({pre[:7]} → {post[:7]}) from the route worktree; "
             f"{MERGE_TARGET} {how}")
    return None


def retire_batch_file(batch_file: Path) -> Optional[Path]:
    """Retire a QUEUED batch file to queue/done/ — part of the merge's own completion.

    D-S7CORE14-02: the process that merges is the only process that knows the merge happened.
    Until QUEUE-RETIRE-1 the scheduler owned this half of the transaction and did it only after
    `self.current_process.wait()` returned (queue_daemon.py:325). Everything between the merge
    inside this process and that line was an unguarded window, and a kill in it left an
    already-merged brief queued: RESOLVER-1 merged as f1359634 on 21 Sep, sat in queue/ for five
    days, and was re-fired on the 26th. Widening the window was never the fix; moving the
    retirement to the side that knows is.

    BOUNDED — and the bound is the point. Only a batch file whose parent IS queue/ moves. A
    batch passed by path from anywhere else (the DATE-7 shape,
    `orchestrator.py run ~/spectricom-clinical-mp/briefs/41-….md --repo clinical-mp`) is never
    touched and this returns None: that invocation behaves byte-identically to before.
    queue/done/, queue/failed/ and queue/held/ are the scheduler's trays, not the queue, so a
    file already parked in one of them is not queued and does not move either.

    Never raises. A failed retirement must not turn a good merge into a failed route.
    """
    try:
        src = Path(batch_file)
        if not src.is_file():
            return None
        if src.resolve().parent != QUEUE_DIR.resolve():
            return None            # not queued — the path lane, untouched
        QUEUE_DONE.mkdir(parents=True, exist_ok=True)
        dst = QUEUE_DONE / src.name
        src.replace(dst)           # same filesystem by construction — atomic rename
        log.info(f"🗃️  Retired {src.name} → queue/done/ (the merge retires its own brief)")
        return dst
    except Exception as e:
        log.warning(f"⚠️ Could not retire batch file {batch_file}: {e}")
        return None


def _self_mod_auto_merge(orch_dir: Path, branch_name: str, gate_outcome: Optional[str] = None,
                         batch_file: Optional[Path] = None) -> bool:
    """Auto-merge meta-fire branch to main after successful self-mod fire.

    Returns True if merge succeeded (or no commits to merge), False on failure.
    Note: after auto-merge, the orchestrator's loaded Python modules are unchanged
    in memory; new code on disk takes effect on next invocation.

    S7-CORE-4 [ORCH-1]: this lane is GATED. run_batch (the only production caller) runs
    run_pre_merge_gates on the worktree checkout first and passes the verdict as
    gate_outcome; anything but PASS is refused here and the branch preserved.
    gate_outcome=None means the caller made no gate claim (tests / manual use) and is
    honoured as-is — the production path always passes the verdict.

    QUEUE-RETIRE-1: batch_file is the brief this route came from. A REAL merge retires it
    before returning success (retire_batch_file — a no-op unless it is sitting in queue/).
    The `no commits to bring in` path deliberately does NOT retire: nothing merged there, so
    the trunk invariant has nothing to say and the scheduler's bookkeeping still owns it.
    """
    if gate_outcome is not None and gate_outcome != GateOutcome.PASS.value:
        log.error(
            f"⛔ Self-mod auto-merge REFUSED — pre-merge gate {gate_outcome}. "
            f"Branch preserved: {branch_name}. After review: cd {orch_dir} && git merge --ff-only {branch_name}"
        )
        return False
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
        if batch_file is not None:
            retire_batch_file(batch_file)
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
    output: str = ""  # [ORCH-1] combined stdout+stderr tail for F-20 classification (never logged whole)
    clock: Optional[ClockViolation] = None  # [GATE-CLOCK-1] the leg's clocks disagree; None = plausible
    stderr_head: Optional[str] = None  # [ORCH-LANE-1] O5: the command's stderr head; None = no exit observed


# ── GATE-CLOCK-1 · every gate leg reads three clocks (S7-CORE-16) ───────────────────────────
# L, the legs the orchestrator times — each judged exactly once, by _judge_leg, as it ends:
#   build          run_build_gate
#   sit-run        run_sit_post_merge, when the SIT gate runs in one invocation
#   sit-batch      _run_sit_batched, once per batch
#   sit-isolation  _sit_isolate, the alone re-runs after the refill pause (the pause is not measured)
#   unit-branch    run_unit_gate, the branch leg
#   unit-baseline  _unit_baseline_measure_or_reuse, only when MEASURED — a cache hit is not a leg;
#                  an implausible one is re-measured once, a second leg (BASELINE-TRUST-1)
#   unit-confirm   run_unit_gate, the isolation confirmation of newly-failing files
# The verdict clause is one rule in _classify_gate_failure; the predicate is canon_assert's.
def _leg_clocks() -> LegClocks:
    """[GATE-CLOCK-1] wall, monotonic and boot time, read together. boottime is None where
    CLOCK_BOOTTIME does not exist (non-Linux) — the suspend clause is then skipped, never guessed."""
    try:
        boot = time.clock_gettime(time.CLOCK_BOOTTIME)
    except (AttributeError, OSError):
        boot = None
    return LegClocks(wall=time.time(), monotonic=time.monotonic(), boottime=boot)


def _gate_durations_load(archive: Path) -> dict:
    """{repo: {leg kind: [{"at", "d_wall", "d_monotonic"}, ...]}} from the store; {} when absent,
    unreadable or another version (the history then restarts — it never invents a sample)."""
    f = archive / GATE_DURATIONS_FILE
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        log.warning(f"⚠️  Gate duration history unreadable at {f} — treated as empty (it will be rewritten)")
        return {}
    repos = data.get("repos") if isinstance(data, dict) and data.get("version") == GATE_DURATIONS_VERSION else None
    return repos if isinstance(repos, dict) else {}


def _gate_durations_history(archive: Path, kind: str) -> list:
    """The recorded plausible wall durations of (ACTIVE_REPO_NAME, kind), oldest first."""
    samples = ((_gate_durations_load(archive).get(ACTIVE_REPO_NAME) or {}).get(kind)) or []
    return [float(s["d_wall"]) for s in samples
            if isinstance(s, dict) and isinstance(s.get("d_wall"), (int, float))]


def _gate_durations_record(archive: Path, kind: str, d_wall: float, d_mono: float):
    """Append one PLAUSIBLE sample to (ACTIVE_REPO_NAME, kind), keeping the newest GATE_DURATIONS_KEEP."""
    repos = _gate_durations_load(archive)
    kinds = repos.get(ACTIVE_REPO_NAME)
    if not isinstance(kinds, dict):
        kinds = repos[ACTIVE_REPO_NAME] = {}
    samples = [s for s in (kinds.get(kind) or []) if isinstance(s, dict)]
    samples.append({"at": datetime.now().isoformat(), "d_wall": round(d_wall, 2), "d_monotonic": round(d_mono, 2)})
    kinds[kind] = samples[-GATE_DURATIONS_KEEP:]
    try:
        archive.mkdir(parents=True, exist_ok=True)
        (archive / GATE_DURATIONS_FILE).write_text(
            json.dumps({"version": GATE_DURATIONS_VERSION, "repos": repos}, indent=2))
    except OSError as e:
        log.warning(f"⚠️  Gate duration history not written ({e}) — the outlier clause keeps its old history")


def _judge_leg(kind: str, clocks: Optional[tuple], archive: Path, *, red: bool,
               completed: bool = True) -> Optional[ClockViolation]:
    """[GATE-CLOCK-1] P-CLOCK and P-SAY for ONE leg that ran: exactly one `🛡 clock-plausibility:`
    line, CLEAN or IMPLAUSIBLE, green or red. The leg's wall duration joins the (repo, kind) history
    iff it is plausible and ran to completion (a timeout's duration is its budget, not a sample).
    `clocks` is (start, end) LegClocks; None ⇒ the leg was not measured now (a cache hit, a stub) —
    not engaged, no line. Returns the violation, or None when plausible."""
    if clocks is None:
        return None
    start, end = clocks
    history = _gate_durations_history(archive, kind)
    found = check_clock_plausibility(kind, start, end, history)
    d_boot = ("n/a (no CLOCK_BOOTTIME)" if start.boottime is None or end.boottime is None
              else f"{end.boottime - start.boottime:.1f}s")
    hist = (f"outlier clause against the median of {len(history)} plausible samples"
            if len(history) >= CLOCK_HISTORY_MIN else
            f"outlier clause dormant ({len(history)} < {CLOCK_HISTORY_MIN} plausible samples)")
    if found:
        v = found[0]
        what = "red: not a product verdict" if red else "green: stays green"
        log.warning(f"🛡 clock-plausibility: IMPLAUSIBLE — {v}; Δboottime {d_boot}; {hist} "
                    f"[{what}; not recorded]")
        return v
    d_wall, d_mono = end.wall - start.wall, end.monotonic - start.monotonic
    log.info(f"🛡 clock-plausibility: CLEAN — {kind} Δwall {d_wall:.1f}s, Δmonotonic {d_mono:.1f}s, "
             f"Δboottime {d_boot}; {hist}")
    if completed:
        _gate_durations_record(archive, kind, d_wall, d_mono)
    return None


def _run_leg(kind: str, archive: Path, cmd: str, **kwargs) -> tuple:
    """[GATE-CLOCK-1] subprocess.run(cmd, **kwargs) as one timed leg of `kind`: returns
    (CompletedProcess, ClockViolation | None). A leg that raises — its timeout included — is judged
    as incomplete and red, the verdict is attached to the exception as `gate_clock`, and the
    exception propagates to the caller's own handler."""
    c0 = _leg_clocks()
    try:
        r = subprocess.run(cmd, **kwargs)
    except Exception as e:
        e.gate_clock = _judge_leg(kind, (c0, _leg_clocks()), archive, red=True, completed=False)
        raise
    return r, _judge_leg(kind, (c0, _leg_clocks()), archive, red=r.returncode != 0)


def _gate_env_file(repo_path: Path) -> tuple[Optional[str], Optional[Path]]:
    """(declared env_file name or None, its Path under repo_path or None) per PRE_MERGE_GATES."""
    policy = PRE_MERGE_GATES.get(ACTIVE_REPO_NAME) or {}
    name = policy.get("env_file")
    return name, (repo_path / name if name else None)


def _gate_shell_cmd(cmd: str, repo_path: Path) -> str:
    """Prefix a gate command with dotenv sourcing (GATE_ENV_SOURCE) when the repo policy
    declares an env_file and it exists. cwd is repo_path, so `. ./.env` resolves to the gated
    repo root. A declared-but-missing env_file is caught before any gate runs
    (run_pre_merge_gates), so the sourcing line can never abort the run silently.
    Secrets-silent: no set -x, no echo; values are never read by the orchestrator.

    [ORCH-9]: the BUILD and SIT gates only. The unit suite is deliberately NOT run through
    this — see _run_unit_suite for the measurement that settled it."""
    name, path = _gate_env_file(repo_path)
    if name and path.is_file():
        return f"{GATE_ENV_SOURCE.format(env_file=name)}; {cmd}"
    return cmd


def run_build_gate(repo_path: Path) -> BuildGateOutcome:
    """Run tsc --noEmit && npm run build on the route branch, BEFORE merge ([ORCH-1]). BLOCKING gate.

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
        r, clock = _run_leg(
            "build", SIT_ARCHIVE_DIR,
            _gate_shell_cmd(gate_cmd, repo_path), shell=True, capture_output=True, text=True,
            cwd=str(repo_path), timeout=BUILD_GATE_TIMEOUT
        )
        duration = time.time() - started
        passed = r.returncode == 0
        if passed:
            log.info(f"✅ BUILD GATE PASSED ({duration:.1f}s)")
            return BuildGateOutcome(passed=True, exit_code=0, duration_s=duration, clock=clock)
        log.error(f"❌ BUILD GATE FAILED (exit {r.returncode}, {duration:.1f}s) — BLOCKING, queue will halt")
        tail = (r.stdout or "")[-800:] + "\n" + (r.stderr or "")[-800:]
        log.error(f"   {tail.strip()[-1000:]}")
        return BuildGateOutcome(passed=False, exit_code=r.returncode,
                                error=tail.strip()[-1000:], duration_s=duration,
                                output=((r.stdout or "") + "\n" + (r.stderr or ""))[-20000:], clock=clock,
                                stderr_head=(r.stderr or "")[:GATE_STDERR_HEAD_CHARS])
    except subprocess.TimeoutExpired as e:
        duration = time.time() - started
        log.error(f"❌ BUILD GATE TIMEOUT after {duration:.1f}s — BLOCKING")
        return BuildGateOutcome(passed=False, exit_code=-1, error="timeout", duration_s=duration,
                                clock=getattr(e, "gate_clock", None))
    except Exception as e:
        duration = time.time() - started
        log.error(f"❌ BUILD GATE ERROR: {e} — BLOCKING")
        return BuildGateOutcome(passed=False, exit_code=-1, error=str(e), duration_s=duration, output=str(e),
                                clock=getattr(e, "gate_clock", None))


# ═══════════════════════════════════════════════════════
# SIT POST-MERGE INTEGRATION (A58a — advisory v1)
# ═══════════════════════════════════════════════════════
@dataclass
class SitIsolation:
    """[GATE-SIT-2] The evidence of the isolation leg: each file that failed in its batch,
    re-run ALONE after the refill pause. A measurement, not a retry — the verdict is decided
    from it by _classify_gate_failure rule 3, never here."""
    contaminated: tuple = ()   # failed in the batch, PASSED alone
    confirmed: tuple = ()      # failed alone too
    neighbours: dict = field(default_factory=dict)  # file -> the other files of its batch, listing order
    batch_of: dict = field(default_factory=dict)    # file -> 1-based batch index
    duration_s: float = 0.0
    pause_s: int = 0
    error: Optional[str] = None    # "isolation-unmeasurable" ⇒ fail closed (BLOCKED(environment))
    detail: Optional[str] = None
    skipped: Optional[str] = None  # why isolation was owed-shaped but not attempted (the cap)
    batches: Optional[int] = None  # how many batches the gate ran, for `batch 2/3`
    alone: dict = field(default_factory=dict)       # file -> `3/3` tests passed alone
    clock: Optional[ClockViolation] = None          # [GATE-CLOCK-1] the leg's clocks disagree

    def where(self, f: str) -> str:
        """`batch 2/3, neighbours: a, b` — the evidence the harness fix needs."""
        nb = ", ".join(self.neighbours.get(f, ())) or "none"
        return f"batch {self.batch_of.get(f, '?')}/{self.batches or '?'}, neighbours: {nb}"

    def as_log(self) -> dict:
        return {"contaminated": list(self.contaminated), "confirmed": list(self.confirmed),
                "neighbours": {k: list(v) for k, v in self.neighbours.items()},
                "batch_of": dict(self.batch_of), "error": self.error, "detail": self.detail,
                "skipped": self.skipped, "duration_s": round(self.duration_s, 2)}


@dataclass
class SitOutcome:
    passed: bool
    exit_code: int
    report_path: Optional[str] = None
    error: Optional[str] = None
    duration_s: float = 0.0
    output: str = ""  # [ORCH-1] combined stdout+stderr tail for F-20 classification (never logged whole)
    # [ORCH-2] what the gate collected, parsed from the vitest summary already in its output.
    # None = summary not parsed. NEVER 0 for "unknown" — 0 is a real, blocking, empty collection.
    test_files_total: Optional[int] = None
    test_files_passed: Optional[int] = None
    tests_total: Optional[int] = None
    tests_passed: Optional[int] = None
    # [ORCH-11] the tally the verdict turns on. None = the summary did not state it and the
    # named tallies did not reconcile (UNKNOWN, never 0 — §2.4); 0 = the runner's own line says
    # every executed assertion passed.
    tests_failed: Optional[int] = None
    tests_skipped: Optional[int] = None
    # [SIT-RATE-1] how many gate invocations produced these counts; None = one unbatched run.
    batches: Optional[int] = None
    detail: Optional[str] = None  # the sentence behind a machinery `error` (never a secret)
    # [GATE-SIT-2] the isolation leg's evidence; None = the leg was not owed (or not batched).
    isolation: Optional[SitIsolation] = None
    # [GATE-CLOCK-1] the first implausible leg of this gate (run, batch or isolation); None = all plausible.
    clock: Optional[ClockViolation] = None

    @property
    def files_failed(self) -> Optional[int]:
        """Files that did not finish green — down at setup or carrying a failed test."""
        if self.test_files_total is None or self.test_files_passed is None:
            return None
        return self.test_files_total - self.test_files_passed

    @property
    def collection(self) -> Optional[str]:
        """`7 files/18 tests, 6.6s` for FINAL STATUS / batch summary; None when nothing parsed.
        [SIT-RATE-1] `19 files/60 tests in 2 batches, 110.2s` when the gate ran batched."""
        if self.test_files_total is None and self.tests_total is None:
            return None
        f = "?" if self.test_files_total is None else self.test_files_total
        t = "?" if self.tests_total is None else self.tests_total
        b = f" in {self.batches} batches" if self.batches else ""
        s = f"{f} files/{t} tests{b}, {self.duration_s:.1f}s"
        iso = self.isolation
        if iso is not None and iso.contaminated:
            # [GATE-SIT-2] named on every path, the way UnitGateOutcome names its flakes
            s += " | contaminated, passed alone (not blocking): " + \
                 "; ".join(f"{c} ({iso.where(c)})" for c in iso.contaminated)
        if iso is not None and iso.confirmed:
            s += f" | confirmed failing alone: {', '.join(iso.confirmed)}"
        return s


# [ORCH-2] vitest summary as the SIT gate prints it (captured 2026-09-11 from clinical-mp, tests/fixtures/):
#      Test Files  7 passed (7)
#           Tests  18 passed (18)
# Mixed shape: `Test Files  2 failed | 5 passed (7)`. Tolerant of ANSI colour and leading space.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_VITEST_SUMMARY_RE = {
    "test_files": re.compile(r"^\s*Test Files\s+(.+?)\s*$", re.MULTILINE),
    "tests": re.compile(r"^\s*Tests\s+(.+?)\s*$", re.MULTILINE),
}
_VITEST_TOTAL_RE = re.compile(r"\((\d+)\)\s*$")
_VITEST_PASSED_RE = re.compile(r"(\d+) passed\b")
_VITEST_NO_FILES_RE = re.compile(r"^\s*No test files found", re.MULTILINE)
# S7-CORE-9 [ORCH-8]: vitest's `Tests` line carries FOUR named tallies, not two —
#      Tests  9 failed | 7267 passed | 8 skipped | 4 todo (7288)
# `total - passed` reads 21 there, not 9. Skipped and todo are not failures; on clinical-mp
# that was a constant +12 on every unit-gate number since [ORCH-3] shipped. Parse the count
# vitest itself states, in the same style as the two segments above.
_VITEST_FAILED_RE = re.compile(r"(\d+) failed\b")
_VITEST_SKIPPED_RE = re.compile(r"(\d+) skipped\b")
_VITEST_TODO_RE = re.compile(r"(\d+) todo\b")
# S7-CORE-15 [ORCH-TALLY-1]: and a FIFTH — a `test.fails(...)` that failed as expected, which
# vitest (4.1.4, getStateString) prints between `passed` and `skipped` and EXCLUDES from
# `passed`. `failed\b` never matches `1 expected fail`, so it was silently dropped.
_VITEST_EXPECTED_FAIL_RE = re.compile(r"(\d+) expected fail\b")
_VITEST_TALLY_RES = {"failed": _VITEST_FAILED_RE, "expected_fail": _VITEST_EXPECTED_FAIL_RE,
                     "skipped": _VITEST_SKIPPED_RE, "todo": _VITEST_TODO_RE}


def _parse_vitest_summary(raw: str) -> dict:
    """[ORCH-2] The four collection counts from the vitest summary already in `raw`. Parse,
    never re-run. Absent / unrecognised ⇒ None, NEVER 0: a fabricated 0 would trip the
    zero-collection block and turn a reporting gap into a false BLOCKED."""
    out = {"test_files_total": None, "test_files_passed": None, "tests_total": None, "tests_passed": None}
    text = _ANSI_RE.sub("", raw or "")
    for key, rx in _VITEST_SUMMARY_RE.items():
        for m in rx.finditer(text):  # last match wins — the summary block is at the end
            t = _VITEST_TOTAL_RE.search(m.group(1))
            if not t:
                continue
            p = _VITEST_PASSED_RE.search(m.group(1))
            out[f"{key}_total"] = int(t.group(1))
            out[f"{key}_passed"] = int(p.group(1)) if p else 0  # line parsed; no "passed" segment ⇒ none passed
    if out["test_files_total"] is None and _VITEST_NO_FILES_RE.search(text):
        # vitest's explicit empty run ("No test files found, exiting with code 0" under passWithNoTests)
        out.update(test_files_total=0, test_files_passed=0, tests_total=0, tests_passed=0)
    return out


def _parse_vitest_tallies(raw: str) -> dict:
    """[ORCH-8] The NAMED tallies on vitest's `Tests` line: failed / expected fail / skipped /
    todo ([ORCH-TALLY-1] added the second).

    Kept separate from _parse_vitest_summary so [ORCH-2]'s four-key contract — which the SIT
    gate and its tests depend on — is untouched. A segment the summary does not carry is
    None, not 0: `Tests  7288 passed (7288)` states nothing about failures, and the caller
    (not this parser) decides what to make of that absence (§2.4)."""
    out = {"failed": None, "expected_fail": None, "skipped": None, "todo": None}
    text = _ANSI_RE.sub("", raw or "")
    for m in _VITEST_SUMMARY_RE["tests"].finditer(text):  # last match wins, as above
        seg = m.group(1)
        if not _VITEST_TOTAL_RE.search(seg):
            continue
        for key, rx in _VITEST_TALLY_RES.items():
            hit = rx.search(seg)
            out[key] = int(hit.group(1)) if hit else None
    return out


def _describe_collection(c: dict) -> str:
    """Run-log wording: `collected 7 test files / 18 tests` or `collection unknown (summary not parsed)`."""
    if c["test_files_total"] is None and c["tests_total"] is None:
        return "collection unknown (summary not parsed)"
    f = "?" if c["test_files_total"] is None else c["test_files_total"]
    t = "?" if c["tests_total"] is None else c["tests_total"]
    s = f"collected {f} test files / {t} tests"
    if c["tests_passed"] is not None and c["tests_passed"] != c["tests_total"]:
        s += f" ({c['tests_passed']} passed)"
    return s


def _sit_tests_failed(counts: dict, tallies: dict) -> Optional[int]:
    """[ORCH-11] The failed-assertion count the vitest summary STATES. `Tests 51 passed | 9
    skipped (60)` carries no `failed` segment; it is read as 0 only when the tallies it does
    carry reconcile against its own total (51 + 9 = 60). Anything else is None — unknown is
    not zero (§2.4), and unknown never earns an environment verdict."""
    if tallies.get("failed") is not None:
        return tallies["failed"]
    total, passed = counts.get("tests_total"), counts.get("tests_passed")
    if total is None or passed is None:
        return None
    if passed + (tallies.get("skipped") or 0) + (tallies.get("todo") or 0) == total:
        return 0
    return None


@dataclass
class SitPlan:
    """[SIT-RATE-1] What the suite enumerates, before anything runs. `files` in listing order;
    `tests_expected` None when the list command printed files only."""
    files: list = field(default_factory=list)
    tests_expected: Optional[int] = None
    batch_files: int = SIT_BATCH_FILES
    pause_s: int = SIT_BATCH_PAUSE_S
    error: Optional[str] = None
    detail: Optional[str] = None

    @property
    def batches(self) -> list:
        n = max(1, self.batch_files)
        return [self.files[i:i + n] for i in range(0, len(self.files), n)]


def _sit_plan(repo_path: Path) -> Optional[SitPlan]:
    """[SIT-RATE-1] None ⇒ batching is not configured for this repo (no `sit_list_cmd`) and
    the gate runs exactly as before, in one invocation. Otherwise enumerate the suite with the
    repo's own list command so the batches are cut from the same file set the runner would
    collect — no glob is duplicated here. A list that fails or enumerates nothing is an
    environment error (`sit-list-failed`): the gate would otherwise run unbatched into the
    very rate limit this exists to avoid."""
    list_cmd = (ACTIVE_REPO_CONFIG.get(SIT_LIST_CMD_KEY) or "").strip()
    if not list_cmd:
        return None
    plan = SitPlan(batch_files=_unit_repo_timeout(SIT_BATCH_FILES_KEY, SIT_BATCH_FILES))
    raw_pause = ACTIVE_REPO_CONFIG.get(SIT_BATCH_PAUSE_KEY)
    try:  # 0 is a legitimate pause (none); a non-integer is not
        plan.pause_s = SIT_BATCH_PAUSE_S if raw_pause in (None, "") else max(0, int(raw_pause))
    except (TypeError, ValueError):
        log.warning(f"⚠️  SIT gate: repos.yaml {SIT_BATCH_PAUSE_KEY}={raw_pause!r} is not an integer — using {SIT_BATCH_PAUSE_S}s")
    try:
        r = subprocess.run(_gate_shell_cmd(list_cmd, repo_path), shell=True, capture_output=True,
                           text=True, cwd=str(repo_path), timeout=SIT_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as e:
        plan.error, plan.detail = "sit-list-failed", f"{list_cmd!r}: {type(e).__name__}"
        return plan
    text = _ANSI_RE.sub("", r.stdout or "")
    files, tests = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line or " " in line.split(" > ", 1)[0]:
            continue  # banners / blank lines are never a path
        if " > " in line:
            tests += 1
        f = line.split(" > ", 1)[0]
        if f not in files:
            files.append(f)
    if r.returncode != 0 or not files:
        plan.error = "sit-list-failed"
        plan.detail = (f"{list_cmd!r} exit {r.returncode}, {len(files)} files enumerated: "
                       f"{((r.stderr or r.stdout or '').strip()[-300:]) or 'no output'}")
        return plan
    plan.files, plan.tests_expected = files, (tests or None)
    return plan


@dataclass
class _SitBatchedRun:
    """[SIT-RATE-1] The aggregate of every batch — one gate result, never a partial one."""
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    red_output: str = ""   # tails of the RED batches only, for F-20 classification
    counts: dict = field(default_factory=dict)
    tallies: dict = field(default_factory=dict)
    batches: int = 0
    mismatch: Optional[str] = None
    clock: Optional[ClockViolation] = None   # [GATE-CLOCK-1] the first implausible batch leg


def _add_count(agg: dict, key: str, val: Optional[int], unknown: set):
    if val is None:
        unknown.add(key)
    else:
        agg[key] = agg.get(key, 0) + val


def _run_sit_batched(sit_cmd: str, repo_path: Path, plan: SitPlan,
                     archive: Optional[Path] = None) -> _SitBatchedRun:
    """[SIT-RATE-1] Run `sit_cmd -- <files>` once per batch, pausing `plan.pause_s` between,
    and add the per-batch vitest summaries up. Every batch runs (no early exit, and a BATCH is
    NEVER re-run — a re-run against an unrefilled budget is dirtier than the first, measured
    2026-09-15: 5 files down instead of 3). [GATE-SIT-2] A single failing file may afterwards
    be re-measured ALONE, after the refill pause, by run_sit_post_merge (_sit_isolate) — a
    measurement, not a retry, and never of a batch. A batch that collects a different number of files
    than it was handed, or an aggregate that does not equal the enumeration, is `mismatch`:
    the [ORCH-8] failure in a new costume, and not a verdict."""
    out = _SitBatchedRun()
    agg, unknown = {}, set()
    batches = plan.batches
    out.batches = len(batches)
    notes = []
    for i, files in enumerate(batches, 1):
        if i > 1 and plan.pause_s > 0:
            log.info(f"⏸️  SIT batch pause {plan.pause_s}s (rate-limit window refill) before batch {i}/{len(batches)}")
            time.sleep(plan.pause_s)
        cmd = f"{sit_cmd} -- {' '.join(shlex.quote(f) for f in files)}"
        started = time.time()
        r, clock = _run_leg("sit-batch", archive or SIT_ARCHIVE_DIR, _gate_shell_cmd(cmd, repo_path),
                            shell=True, capture_output=True, text=True, cwd=str(repo_path), timeout=SIT_TIMEOUT)
        out.clock = out.clock or clock
        d = time.time() - started
        raw = (r.stdout or "") + "\n" + (r.stderr or "")
        c, t = _parse_vitest_summary(raw), _parse_vitest_tallies(raw)
        head = f"── SIT batch {i}/{len(batches)} ({len(files)} files) ──\n"
        out.stdout += head + (r.stdout or "")
        out.stderr += head + (r.stderr or "")
        if r.returncode != 0:
            out.returncode = out.returncode or r.returncode
            out.red_output += head + raw[-10000:]
        status = "PASS" if r.returncode == 0 else f"exit {r.returncode}"
        log.info(f"🧪 SIT batch {i}/{len(batches)}: {status} — {_describe_collection(c)} in {d:.1f}s")
        if c["test_files_total"] != len(files):
            notes.append(f"batch {i} was handed {len(files)} files and collected "
                         f"{'?' if c['test_files_total'] is None else c['test_files_total']}")
        for k in ("test_files_total", "test_files_passed", "tests_total", "tests_passed"):
            _add_count(agg, k, c[k], unknown)
        # `failed` per batch by the same rule as a single run (_sit_tests_failed): a line with
        # no `failed` segment that reconciles states 0. skipped/todo are printed only when
        # non-zero, so absent IS 0 for them.
        _add_count(agg, "t_failed", _sit_tests_failed(c, t), unknown)
        for k in ("skipped", "todo"):
            _add_count(agg, f"t_{k}", t[k] or 0, unknown)
    out.counts = {k: (None if k in unknown else agg.get(k, 0))
                  for k in ("test_files_total", "test_files_passed", "tests_total", "tests_passed")}
    # A batch whose failed count is UNKNOWN makes the aggregate unknown — a partial sum is not
    # a count (§2.4).
    out.tallies = {k: (None if f"t_{k}" in unknown else agg.get(f"t_{k}", 0))
                   for k in ("failed", "skipped", "todo")}
    got_f, got_t = out.counts["test_files_total"], out.counts["tests_total"]
    if got_f != len(plan.files):
        notes.append(f"batches collected {got_f} files, the suite enumerates {len(plan.files)}")
    if plan.tests_expected is not None and got_t != plan.tests_expected:
        notes.append(f"batches collected {got_t} tests, the suite enumerates {plan.tests_expected}")
    out.mismatch = "; ".join(notes) or None
    return out


def _sit_env_signal(text: str) -> Optional[str]:
    """[GATE-SIT-2] The first F-20 ENV_BLOCK_SIGNALS id matching `text` (ANSI stripped, as the
    classifier reads it), or None. Rule 2's table, read — never copied."""
    text = _ANSI_RE.sub("", text or "")
    for sid, rx, _ in _ENV_BLOCK_SIGNALS_RE:
        if rx.search(text):
            return sid
    return None


def _sit_failing_files(text: str) -> list:
    """[GATE-SIT-2] The failing files the runner output names (`FAIL sit/x.test.ts`), normalised,
    in first-seen order, each once."""
    out = []
    for f in _GATE_FAIL_FILE_RE.findall(_ANSI_RE.sub("", text or "")):
        f = _norm_test_path(f)
        if f not in out:
            out.append(f)
    return out


def _sit_isolate(sit_cmd: str, repo_path: Path, plan: SitPlan, files: list,
                 archive: Optional[Path] = None) -> SitIsolation:
    """[GATE-SIT-2] Re-run each failing file ALONE — one `sit_cmd -- <file>` invocation per file,
    in listing order, after ONE refill pause. Copies the [ORCH-6] unit-gate shape: a file that
    passes alone was its batch's (`contaminated`), a file that fails alone is the product's
    (`confirmed`), and a measurement that cannot be read stops the leg with `error` — fail
    closed, never a verdict about the file. More failing files than a batch holds is not
    contamination-shaped: recorded as `skipped`, nothing re-run."""
    iso = SitIsolation(pause_s=plan.pause_s, batches=len(plan.batches))
    if len(files) > plan.batch_files:
        iso.skipped = (f"{len(files)} failing files exceed the batch size {plan.batch_files} — "
                       f"not contamination-shaped, not re-run")
        log.warning(f"⚠️  SIT gate isolation skipped: {iso.skipped}")
        log.warning(f"🛡 sit-isolation: SKIPPED — {iso.skipped}")
        return iso
    log.info(f"🔬 SIT gate: {len(files)} failing file(s) — confirming in isolation before verdict: "
             f"{', '.join(files)}")
    for i, batch in enumerate(plan.batches, 1):
        for f in files:
            if f in batch:
                iso.batch_of[f] = i
                iso.neighbours[f] = tuple(x for x in batch if x != f)
    started = time.time()
    if plan.pause_s > 0:
        log.info(f"⏸️  SIT batch pause {plan.pause_s}s (rate-limit window refill) before the isolation leg")
        time.sleep(plan.pause_s)
    c0 = _leg_clocks()   # [GATE-CLOCK-1] the leg is the re-runs; the refill pause measures nothing
    contaminated, confirmed = [], []
    for f in files:
        cmd = f"{sit_cmd} -- {shlex.quote(f)}"
        why = None
        try:
            r = subprocess.run(_gate_shell_cmd(cmd, repo_path), shell=True, capture_output=True,
                               text=True, cwd=str(repo_path), timeout=SIT_TIMEOUT)
        except (subprocess.TimeoutExpired, OSError) as e:
            r, why = None, (f"timeout — exceeded its {SIT_TIMEOUT}s budget"
                            if isinstance(e, subprocess.TimeoutExpired) else type(e).__name__)
        if r is not None:
            raw = (r.stdout or "") + "\n" + (r.stderr or "")
            c, t = _parse_vitest_summary(raw), _parse_vitest_tallies(raw)
            tf, sig = _sit_tests_failed(c, t), _sit_env_signal(raw)
            if sig:
                why = f"F-20 signal '{sig}' in its own output"
            elif c["test_files_total"] != 1:
                why = f"collected {'?' if c['test_files_total'] is None else c['test_files_total']} files, not 1"
            elif r.returncode == 0 and tf == 0:
                contaminated.append(f)
                iso.alone[f] = f"{c['tests_passed']}/{c['tests_total']}"
            elif r.returncode != 0 and tf is not None and tf >= 1:
                confirmed.append(f)
                iso.alone[f] = f"{c['tests_passed']}/{c['tests_total']}"
            else:
                why = f"exit {r.returncode} with {'unknown' if tf is None else tf} failed assertions"
        if why:
            iso.error = "isolation-unmeasurable"
            iso.detail = f"{f} could not be measured alone ({why}) — batch contamination cannot be told from a product failure"
            log.error(f"⛔ SIT gate isolation: {iso.detail}")
            break
    iso.contaminated, iso.confirmed = tuple(contaminated), tuple(confirmed)
    iso.duration_s = time.time() - started
    log.info(f"🔬 SIT gate isolation — {len(files)} file(s) in {iso.duration_s:.1f}s; "
             f"contaminated: {', '.join(iso.contaminated) or '(none)'}; "
             f"confirmed: {', '.join(iso.confirmed) or '(none)'}")
    iso.clock = _judge_leg("sit-isolation", (c0, _leg_clocks()), archive or SIT_ARCHIVE_DIR,
                           red=bool(iso.error or iso.confirmed), completed=iso.error is None)
    # [ORCH-HANDBACK-SILENT-PASS] P-SAY: exactly one verdict line per engagement, on every path.
    if iso.error:
        log.error(f"🛡 sit-isolation: BLOCKED — {iso.error}: {iso.detail}")
    elif iso.confirmed:
        log.error(f"🛡 sit-isolation: FAIL — confirmed failing alone: {', '.join(iso.confirmed)}; "
                  f"contaminated: {', '.join(iso.contaminated) or '(none)'}")
    else:
        log.info(f"🛡 sit-isolation: CLEAN — every failing file passed alone (batch contamination): "
                 f"{', '.join(iso.contaminated)}")
    return iso


def run_sit_post_merge(repo_path: Path, archive_path: Optional[Path] = None) -> SitOutcome:
    """Run SIT smoke tests, then apply the MANY-or-SEVERE halt rule.

    [ORCH-1] Name retained for its call sites (tests import it by name); since S7-CORE-4 this
    runs on the route branch BEFORE the merge via run_pre_merge_gates, not after.

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
    sit_cmd = "npm run sit:gate"  # S6S78: deterministic headless T1 (vitest); exit-code = pass/fail
    # [SIT-RATE-1] None ⇒ one invocation, exactly as before. A plan ⇒ batches of `batch_files`
    # with `pause_s` between, added up and reconciled against the enumeration.
    plan = _sit_plan(repo_path)
    if plan is not None and plan.error:
        log.error(f"⛔ SIT gate: could not enumerate the suite for batching — {plan.error} ({plan.detail}) "
                  f"— BLOCKED(environment), not run unbatched into the rate limit")
        _log_sit_outcome(archive, repo_path, False, -1, 0.0, None, error=plan.error, error_excerpt=plan.detail)
        return SitOutcome(passed=False, exit_code=-1, error=plan.error, detail=plan.detail, output=plan.detail or "")
    if plan is None:
        log.info(f"🧪 Running SIT post-merge: {sit_cmd}")
    else:
        log.info(f"🧪 Running SIT post-merge: {sit_cmd} — {len(plan.files)} files"
                 f"{'' if plan.tests_expected is None else f' / {plan.tests_expected} tests'} enumerated, "
                 f"in {len(plan.batches)} batches of ≤{plan.batch_files} files, {plan.pause_s}s pause between")
    started = time.time()
    batch_mismatch: Optional[str] = None
    batches: Optional[int] = None

    try:
        if plan is None:
            r, clock = _run_leg(
                "sit-run", archive,
                _gate_shell_cmd(sit_cmd, repo_path), shell=True, capture_output=True, text=True,
                cwd=str(repo_path), timeout=SIT_TIMEOUT
            )
            raw = (r.stdout or "") + "\n" + (r.stderr or "")
            counts, tallies = _parse_vitest_summary(raw), _parse_vitest_tallies(raw)
        else:
            b = _run_sit_batched(sit_cmd, repo_path, plan, archive)
            r = subprocess.CompletedProcess(sit_cmd, b.returncode, stdout=b.stdout, stderr=b.stderr)
            raw = b.red_output or (b.stdout + "\n" + b.stderr)
            counts, tallies, batches, batch_mismatch = b.counts, b.tallies, b.batches, b.mismatch
            clock = b.clock
        duration = time.time() - started
        # S6S47: baseline-aware. Block only on NEW failures, not pre-existing
        # known-failing specs (BUG-018/BUG-026). Parse failing spec basenames
        # from playwright output; if every failing spec is in SIT_KNOWN_FAILING,
        # treat as pass-with-known-failures.
        # S6S78: sit:gate is the deterministic headless T1 (vitest). Pass/fail is
        # exit-code based — a nonzero exit is a real regression and BLOCKS. The old
        # Playwright spec-name / known-failing / critical parsing does NOT apply to
        # the vitest gate (its failure format differs); relying on it here would
        # mis-read a real vitest failure as "no specs parsed -> advisory" and
        # silently pass. (When T2 browser smoke lands in sit:gate, revisit whether
        # any tier warrants a retry/known-failing carve-out.)
        passed = (r.returncode == 0)
        # S7-CORE-7 [ORCH-2]: declare what the gate collected. Parsed from `raw` — the summary is
        # already in hand; nothing is re-run. (2026-09-10: a 2.3s PASS over a directory holding two
        # unrelated files promoted three Longevity capabilities. A gate must say what it tested.)
        # [SIT-RATE-1] batched: `counts` is the per-batch sum, already parsed above.
        tests_failed = _sit_tests_failed(counts, tallies)
        collection = _describe_collection(counts)
        if batches:
            collection += f" in {batches} batches"
        # [GATE-SIT-2] a red batched run with ≥1 failed assertion, no F-20 signal and named
        # failing files: re-measure those files alone before anything decides. A run that
        # D-S7CORE10-02 already calls environment (0 failed / a transport signal) is never
        # re-run. `passed` stays False whatever this finds — the classifier decides.
        isolation: Optional[SitIsolation] = None
        if (plan is not None and r.returncode != 0 and batch_mismatch is None
                and isinstance(tests_failed, int) and tests_failed >= 1 and _sit_env_signal(raw) is None):
            named = set(_sit_failing_files(raw))
            suspects = [f for f in plan.files if _norm_test_path(f) in named]
            if suspects:
                isolation = _sit_isolate(sit_cmd, repo_path, plan, suspects, archive)
                clock = clock or isolation.clock
        error, detail = None, None
        if batch_mismatch:
            # AC-SR-05: the batches do not add up to the suite. Not a verdict about anything.
            passed, error, detail = False, "batch-incomplete", batch_mismatch
            log.error(f"⛔ SIT gate batching does not sum to the suite — {batch_mismatch} — "
                      f"BLOCKED(environment), not PASS, not FAIL(product) ({collection}, {duration:.1f}s)")
        elif passed and (counts["test_files_total"] == 0 or counts["tests_total"] == 0):
            # §4.5: green exit over an empty collection tested nothing. Environment, never product.
            passed, error = False, "zero-collection"
            log.error(f"⛔ SIT gate collected NOTHING — treating as BLOCKED(environment), not PASS "
                      f"(exit 0, {collection}, {duration:.1f}s)")
        elif passed:
            recon = "" if plan is None else f" (equals the enumerated suite: {len(plan.files)} files" + \
                    ("" if plan.tests_expected is None else f" / {plan.tests_expected} tests") + ")"
            log.info(f"🧪 SIT gate: PASS — {collection}{recon} in {duration:.1f}s")
        else:
            fl = "?" if tests_failed is None else tests_failed
            iso = "" if isolation is None else (
                f" (isolation: contaminated {len(isolation.contaminated)}, confirmed {len(isolation.confirmed)}"
                f"{', ' + (isolation.error or isolation.skipped) if (isolation.error or isolation.skipped) else ''}"
                f" — the verdict is the classifier's)")
            log.error(f"⛔ SIT gate FAILED (exit {r.returncode}) — {collection}, {fl} failed assertions{iso} — BLOCKING.\n{raw[-800:]}")
        if (SIT_MIN_TEST_FILES is not None and counts["test_files_total"] is not None
                and counts["test_files_total"] < SIT_MIN_TEST_FILES):
            # §4.6: warning only, never blocking
            log.warning(f"⚠️  SIT gate thin: {counts['test_files_total']} test files (floor {SIT_MIN_TEST_FILES})")

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
        if not passed:
            # [ORCH-1] since 448e0c4 a red gate blocks the merge (gate-then-merge); wording fixed in [ORCH-2]
            log.warning(f"⛔ SIT {error or 'FAILED'} (exit {r.returncode}, {duration:.1f}s) — BLOCKING merge")
            if r.stdout:
                log.warning(f"   stdout: {r.stdout[-500:]}")
            error_excerpt = (r.stderr or r.stdout or "")[-1000:].strip() or None

        # Log to orchestrator-sit-log.json
        _log_sit_outcome(archive, repo_path, passed, r.returncode, duration, report_path,
                         error=error, error_excerpt=error_excerpt, tests_failed=tests_failed,
                         batches=batches, isolation=None if isolation is None else isolation.as_log(),
                         **counts)

        return SitOutcome(passed=passed, exit_code=r.returncode, report_path=report_path, duration_s=duration,
                          error=error, detail=detail, output="" if passed else raw[-20000:],
                          tests_failed=tests_failed, tests_skipped=tallies.get("skipped"),
                          batches=batches, isolation=isolation, clock=clock, **counts)

    except subprocess.TimeoutExpired:
        duration = time.time() - started
        log.error(f"🟠 SIT TIMEOUT after {duration:.1f}s — ADVISORY (not blocking); surfacing for review.")
        _log_sit_outcome(archive, repo_path, True, -1, duration, None, error="timeout-advisory")
        return SitOutcome(passed=True, exit_code=-1, error="timeout-advisory", duration_s=duration)
    except Exception as e:
        duration = time.time() - started
        log.warning(f"⚠️  SIT ERROR: {e} — advisory only")
        _log_sit_outcome(archive, repo_path, False, -1, duration, None, error=str(e))
        return SitOutcome(passed=False, exit_code=-1, error=str(e), duration_s=duration, output=str(e),
                          clock=getattr(e, "gate_clock", None))


# ═══════════════════════════════════════════════════════
# UNIT SUITE BASELINE GATE (S7-CORE-8 [ORCH-3])
# Runs the repo's `test_cmd` (config/repos.yaml) on the route branch AND on the merge base,
# and halts only on a REGRESSION: more failures than the baseline, or a test FILE that is
# failing now and was not failing at the fork point. Added ALONGSIDE run_build_gate and the
# SIT block — neither is touched (brief §4 STOP trigger 3).
# ═══════════════════════════════════════════════════════
@dataclass
class UnitSuiteRun:
    """One execution of the unit suite, on one ref."""
    ref: str                       # "merge-base abc1234" | branch name — what was measured
    exit_code: int
    duration_s: float = 0.0
    runner: Optional[str] = None   # "vitest" | "pytest" | None (summary not recognised)
    # None means UNKNOWN, never 0. A fabricated 0 would trip the zero-collection block
    # (§2.4) and turn a reporting gap into a false BLOCKED — the same rule [ORCH-2] set.
    test_files_total: Optional[int] = None
    tests_total: Optional[int] = None
    tests_passed: Optional[int] = None
    failures: Optional[int] = None
    # [ORCH-8] the other two tallies the runner states. None ⇒ the summary carried no such
    # segment, which is NOT the same as zero and is rendered as an omission, never as a 0.
    tests_skipped: Optional[int] = None
    tests_todo: Optional[int] = None
    # [ORCH-TALLY-1] vitest's `N expected fail` (a `test.fails` that failed as expected). Same
    # discipline: None ⇒ no such segment (and always None on pytest), never rendered as 0.
    tests_expected_fail: Optional[int] = None
    # [ORCH-8] AC-O8-03: "reported" ⇒ the runner stated the failure count and we read it;
    # "derived" ⇒ there was no `failed` segment and it came from the fallback subtraction.
    # A reader of the log must never have to guess which of the two produced the number.
    failures_source: Optional[str] = None
    failing_files: tuple = ()      # sorted, repo-relative; the SET half of the §2.1 comparison
    output: str = ""               # combined stdout+stderr tail, for F-20 classification
    error: Optional[str] = None    # "timeout" | subprocess error text
    # [GATE-CLOCK-1] (start, end) LegClocks of THIS execution; None ⇒ not measured now (cache, stub).
    clocks: Optional[tuple] = None
    clock: Optional[ClockViolation] = None   # set by _judge_leg when the clocks disagree
    stderr_head: Optional[str] = None        # [ORCH-LANE-1] O5: the command's stderr head; None = no exit observed

    @property
    def collection(self) -> Optional[str]:
        """`789 files/7288 tests, 9 failed, 7267 passed, 8 skipped, 4 todo` — what this run
        actually collected. None when nothing parsed.

        [ORCH-8] AC-O8-05: every tally the runner STATED is repeated here, so the reader can
        add them up against the runner's own summary line without re-running anything — the
        reconciliation that `total - passed` made impossible. A tally the runner did not
        state is omitted rather than printed as 0, and a failure count that came from the
        fallback says so."""
        if self.test_files_total is None and self.tests_total is None:
            return None
        f = "?" if self.test_files_total is None else self.test_files_total
        t = "?" if self.tests_total is None else self.tests_total
        s = f"{f} files/{t} tests"
        if self.failures is not None:
            s += f", {self.failures} failed"
            if self.failures_source == "derived":
                s += " (derived)"
        for n, label in ((self.tests_passed, "passed"), (self.tests_expected_fail, "expected fail"),
                         (self.tests_skipped, "skipped"), (self.tests_todo, "todo")):
            if n is not None:
                s += f", {n} {label}"
        return s

    @property
    def tally_sum(self) -> Optional[int]:
        """[ORCH-9] failed + passed + expected fail + skipped + todo, over the tallies THIS
        run carries ([ORCH-TALLY-1] added expected fail — vitest counts it in its total). A
        tally the runner did not state contributes 0 — it was not counted anywhere else
        either. None when there is nothing to add up, or no stated total to check it
        against: an UNKNOWN is not a disagreement (§2.4)."""
        if self.tests_total is None or self.failures is None or self.tests_passed is None:
            return None
        return (self.failures + self.tests_passed + (self.tests_expected_fail or 0)
                + (self.tests_skipped or 0) + (self.tests_todo or 0))

    @property
    def tally_note(self) -> Optional[str]:
        """[ORCH-9] AC-O9-03 — None when the tallies add up to the total the runner stated
        (or when there is not enough to check); otherwise the sentence that says they do not.

        This is the assertion §4 asks for, and the one that would have caught [ORCH-8]'s
        `total - passed` three sessions earlier: 7288 - 7267 = 21 reconciles against nothing,
        while 9 + 7267 + 8 + 4 = 7288 reconciles against vitest's own parenthesised total. A
        number that does not add up is not evidence, and the verdict must not quote it
        silently."""
        s = self.tally_sum
        if s is None or s == self.tests_total:
            return None
        parts = [f"{self.failures} failed", f"{self.tests_passed} passed"]
        for n, label in ((self.tests_expected_fail, "expected fail"), (self.tests_skipped, "skipped"),
                         (self.tests_todo, "todo")):
            if n is not None:
                parts.append(f"{n} {label}")
        return (f"TALLY MISMATCH on {self.ref}: {' + '.join(parts)} = {s}, but the runner "
                f"states {self.tests_total} — these counts do not all come from one run, or "
                f"one of them was not read from the runner's own summary")

    @property
    def describe(self) -> str:
        return f"{self.ref}: {self.collection or 'collection unknown (summary not parsed)'} in {self.duration_s:.1f}s"


@dataclass
class UnitGateOutcome:
    """Verdict of the baseline comparison. `passed` encodes merge-worthiness; `env` says
    whether a red verdict is an environment problem (BLOCKED) rather than a product one."""
    passed: bool
    signal: Optional[str] = None    # "ungated" | "disabled" | "not-applicable" | "regression" | ...
    detail: Optional[str] = None
    env: bool = False               # True ⇒ BLOCKED(environment), never FAIL(product)
    ran: bool = False               # did the gate actually measure the branch?
    baseline: Optional[UnitSuiteRun] = None
    branch: Optional[UnitSuiteRun] = None
    baseline_note: Optional[str] = None  # how the baseline was obtained, or why there isn't one
    # [ORCH-5] AC-O5-05: "measured" | "cache" | "ancestor-cache" | "unmeasurable" | None;
    # [BASELINE-TRUST-1] "implausible" — measured twice, both legs on an implausible clock.
    # The verdict must never leave "was this measured now, or read off disk?" unanswered.
    baseline_source: Optional[str] = None
    duration_s: float = 0.0
    # [ORCH-6] AC-O6-02/06: newly-failing files that PASSED the isolation confirmation —
    # order/load-dependent, not a regression. Never empty on a FAIL(product) verdict alone.
    flaky_files: tuple = ()
    confirm: Optional[UnitSuiteRun] = None   # [GATE-CLOCK-1] the confirmation leg, when it ran

    @property
    def clock(self) -> Optional[ClockViolation]:
        """[GATE-CLOCK-1] the first implausible leg this gate measured NOW — branch, baseline,
        confirm. A cached baseline carries no clocks and is never judged."""
        return next((r.clock for r in (self.branch, self.baseline, self.confirm)
                     if r is not None and r.clock is not None), None)

    @property
    def collection(self) -> Optional[str]:
        """`baseline merge-base abc1234: 6 files/79 tests, 2 failed → branch route-br:
        6 files/81 tests, 2 failed, 24.1s` — the [ORCH-2] shape, both sides declared.
        [ORCH-6] AC-O6-06: a confirmed flake is named here too, so it reaches FINAL STATUS
        on the PASS path (where flakes alone land) as well as the FAIL path."""
        if not self.ran or self.branch is None:
            return None
        base = self.baseline.describe if self.baseline else (self.baseline_note or "not measured")
        if self.baseline is not None and self.baseline_source:
            base += f" [{self.baseline_source}]"
        s = f"baseline {base} → branch {self.branch.describe}, {self.duration_s:.1f}s"
        if self.flaky_files:
            s += f" | flaky, confirmed in isolation (not blocking): {', '.join(self.flaky_files)}"
        return s

    @property
    def tally_note(self) -> Optional[str]:
        """[ORCH-9] AC-O9-03: whichever leg's tallies do not add up to the total its runner
        stated, named. None when both reconcile — or when neither could be checked."""
        notes = [n for n in ((self.branch.tally_note if self.branch else None),
                             (self.baseline.tally_note if self.baseline else None)) if n]
        return "; ".join(notes) or None


# ── suite-output parsing ───────────────────────────────────────────────────────────────
# vitest/jest failing FILES: ` FAIL  src/lib/synth/seed.test.ts > wipe > keeps Patients`
# and the per-file listing ` ❯ src/lib/synth/seed.test.ts (3 tests | 2 failed)`.
_UNIT_VITEST_FAIL_RE = re.compile(r"^\s*(?:❯\s+)?FAIL\s+(\S+)", re.MULTILINE)
_UNIT_VITEST_FILE_FAILED_RE = re.compile(r"^\s*❯\s+(\S+)\s+\(\d+\s+tests?\s*\|\s*\d+\s+failed", re.MULTILINE)
# pytest tallies: `2 failed, 1 passed in 0.01s` (-q) or `==== 2 failed, 1 passed in 0.01s ====`.
_UNIT_PYTEST_SUMMARY_RE = re.compile(
    r"^[=\s]*((?:\d+\s+(?:passed|failed|errors?|skipped|deselected|xfailed|xpassed|warnings?)"
    r"(?:,\s*)?)+)\s+in\s+[\d.]+s", re.MULTILINE)
_UNIT_PYTEST_TALLY_RE = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|deselected|xfailed|xpassed|warnings?)\b")
_UNIT_PYTEST_NO_TESTS_RE = re.compile(r"^[=\s]*no tests ran in [\d.]+s", re.MULTILINE)
_UNIT_PYTEST_COLLECTED_RE = re.compile(r"^\s*collected (\d+) items?", re.MULTILINE)
# `FAILED tests/test_x.py::TestY::test_z - AssertionError` / `ERROR tests/test_x.py`
_UNIT_PYTEST_FAILED_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?\.py)(?:::|\s|$)", re.MULTILINE)
# traceback tail `tests/test_x.py:2: AssertionError` — fallback when the short summary is off
_UNIT_PYTEST_TRACEBACK_RE = re.compile(r"^(\S+\.py):\d+:\s+\w", re.MULTILINE)
# non-quiet per-file progress `tests/test_x.py .FF   [100%]` — the only source of a FILE count
_UNIT_PYTEST_PROGRESS_RE = re.compile(r"^(\S+\.py)\s+[.FEsxXpPu]+\s*(?:\[\s*\d+%\])?\s*$", re.MULTILINE)


def _norm_test_path(p: str) -> str:
    """Repo-relative-ish normalisation so the two sides of the comparison are comparable."""
    p = p.strip().strip('"\'')
    while p.startswith("./"):
        p = p[2:]
    return p


def _parse_unit_summary(raw: str) -> dict:
    """Collection counts + the failing-FILE set from a unit-suite run. Understands the two
    runners this fleet declares in repos.yaml (vitest/jest and pytest). An unrecognised
    runner yields all-None — UNKNOWN, never 0 (§2.4)."""
    text = _ANSI_RE.sub("", raw or "")
    out = {"runner": None, "test_files_total": None, "tests_total": None,
           "tests_passed": None, "failures": None, "tests_skipped": None,
           "tests_todo": None, "tests_expected_fail": None, "failures_source": None,
           "failing_files": ()}

    v = _parse_vitest_summary(text)
    if v["tests_total"] is not None or v["test_files_total"] is not None:
        out["runner"] = "vitest"
        out["test_files_total"] = v["test_files_total"]
        out["tests_total"] = v["tests_total"]
        out["tests_passed"] = v["tests_passed"]
        # [ORCH-8] S1/S2: the failure count is the one vitest STATES. `total - passed` counts
        # skipped and todo as failures — 7288-7267 reads 21 where vitest says 9 — so it is the
        # fallback, used only when there is no `failed` segment to read, and it subtracts the
        # named tallies that are demonstrably not failures.
        t = _parse_vitest_tallies(text)
        out["tests_skipped"] = t["skipped"]
        out["tests_todo"] = t["todo"]
        out["tests_expected_fail"] = t["expected_fail"]  # [ORCH-TALLY-1]
        if t["failed"] is not None:
            out["failures"] = t["failed"]
            out["failures_source"] = "reported"
        elif v["tests_total"] is not None and v["tests_passed"] is not None:
            # [ORCH-TALLY-1] an expected fail is not a failure either.
            out["failures"] = max(0, v["tests_total"] - v["tests_passed"] - (t["expected_fail"] or 0)
                                  - (t["skipped"] or 0) - (t["todo"] or 0))
            out["failures_source"] = "derived"
        files = {_norm_test_path(m) for m in _UNIT_VITEST_FAIL_RE.findall(text)}
        files |= {_norm_test_path(m) for m in _UNIT_VITEST_FILE_FAILED_RE.findall(text)}
        out["failing_files"] = tuple(sorted(f for f in files if f))
        return out

    m = _UNIT_PYTEST_SUMMARY_RE.search(text)
    collected = _UNIT_PYTEST_COLLECTED_RE.search(text)
    if m or collected or _UNIT_PYTEST_NO_TESTS_RE.search(text):
        out["runner"] = "pytest"
        tally = {}
        if m:
            for n, kind in _UNIT_PYTEST_TALLY_RE.findall(m.group(1)):
                tally[kind.rstrip("s") if kind.startswith("error") else kind] = \
                    tally.get(kind.rstrip("s") if kind.startswith("error") else kind, 0) + int(n)
        passed = tally.get("passed", 0)
        # [ORCH-8] S5/AC-O8-07: THIS is the line that decides it — pytest's failure count has
        # always come from its own NAMED tallies, and `other` (skipped/xfailed/xpassed) is
        # folded into the total, never into the failures. The vitest defect does not exist
        # here, so nothing on this path changes but the reporting fields below.
        failed = tally.get("failed", 0) + tally.get("error", 0)
        other = sum(tally.get(k, 0) for k in ("skipped", "xfailed", "xpassed"))
        out["failures"] = failed
        out["failures_source"] = "reported" if m else "derived"
        out["tests_skipped"] = tally.get("skipped") if m else None
        out["tests_passed"] = passed
        out["tests_total"] = int(collected.group(1)) if collected else passed + failed + other
        progress = {_norm_test_path(f) for f in _UNIT_PYTEST_PROGRESS_RE.findall(text)}
        if progress:
            out["test_files_total"] = len(progress)
        files = {_norm_test_path(f) for f in _UNIT_PYTEST_FAILED_RE.findall(text)}
        if not files and failed:
            files = {_norm_test_path(f) for f in _UNIT_PYTEST_TRACEBACK_RE.findall(text)}
        out["failing_files"] = tuple(sorted(f for f in files if f))
        return out

    return out


def _is_git_work_tree(p: Path) -> bool:
    """True iff p is inside a git working tree. False ⇒ there is no route branch to baseline."""
    if not p.is_dir():
        return False
    r = subprocess.run(f"git -C {shlex.quote(str(p))} rev-parse --is-inside-work-tree",
                       shell=True, capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def _unit_merge_base(repo_path: Path, branch_name: Optional[str]) -> Optional[str]:
    """The commit the branch forked from — `git merge-base <merge_target> <branch>`.

    §2.2: this is the fork point, NOT main's current tip. When main has advanced past the
    fork point, merge-base still returns the fork commit, which is exactly the baseline the
    ruling asks for. Falls back to HEAD when the branch ref is not resolvable here (meta-fire
    worktrees are checked out detached in some lanes)."""
    for rev in [r for r in (branch_name, "HEAD") if r]:
        r = subprocess.run(
            f"git -C {shlex.quote(str(repo_path))} merge-base "
            f"{shlex.quote(MERGE_TARGET)} {shlex.quote(rev)}",
            shell=True, capture_output=True, text=True)
        sha = (r.stdout or "").strip()
        if r.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,40}", sha):
            return sha
    return None


def _link_unit_deps(src: Path, dst: Path) -> list:
    """Symlink the git-ignored dependency paths (and the declared env_file) from the gated
    checkout into the detached baseline worktree, so the baseline runs the same suite the
    branch does. Returns the links created, for teardown. Never reads any file's contents.

    [ORCH-9]: the env_file is linked for PARITY, not for use — the unit suite is no longer run
    through the env-sourcing shell. The branch leg runs in a checkout that has the file on
    disk, so the baseline leg gets one too; whether a repo's own config reads it is the
    repo's decision to make identically on both sides."""
    created = []
    names = list(UNIT_BASELINE_LINK_PATHS)
    env_name, _ = _gate_env_file(src)
    if env_name:
        names.append(env_name)
    for rel in names:
        s, d = src / rel, dst / rel
        if not s.exists() or d.exists():
            continue
        try:
            d.parent.mkdir(parents=True, exist_ok=True)
            d.symlink_to(s.resolve(), target_is_directory=s.is_dir())
            created.append(d)
        except OSError as e:
            log.warning(f"⚠️  Unit baseline: could not link {rel}: {e}")
    return created


def _unit_repo_timeout(key: str, default: int) -> int:
    """A per-repo timeout override from config/repos.yaml, or the module default. A value that
    is not a positive integer is ignored loudly rather than silently becoming 0."""
    raw = ACTIVE_REPO_CONFIG.get(key)
    if raw in (None, ""):
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        v = 0
    if v <= 0:
        log.warning(f"⚠️  Unit gate: repos.yaml {key}={raw!r} is not a positive integer — using {default}s")
        return default
    return v


def _unit_suite_timeout(ref: str) -> int:
    """[ORCH-5] AC-O5-03 — the two legs have SEPARATE budgets, and `ref` is already the leg
    identifier this function's caller receives, so no call site has to carry a number.

    The baseline leg's default is deliberately the generous one (30 min vs 15): it runs in a
    fresh detached worktree, and on clinical-mp the same `npm test` that fits in 900s on the
    warm checkout did not fit there. Both are per-repo configurable."""
    if str(ref or "").startswith(UNIT_BASELINE_REF_PREFIX):
        return _unit_repo_timeout(UNIT_BASELINE_TIMEOUT_KEY, UNIT_BASELINE_TIMEOUT)
    if str(ref or "").startswith(UNIT_CONFIRM_REF_PREFIX):
        return _unit_repo_timeout(UNIT_CONFIRM_TIMEOUT_KEY, UNIT_CONFIRM_TIMEOUT)
    return _unit_repo_timeout(UNIT_TIMEOUT_KEY, UNIT_GATE_TIMEOUT)


def _run_unit_suite(cmd: str, cwd: Path, ref: str, timeout: Optional[int] = None) -> UnitSuiteRun:
    """Run `cmd` once and report what it collected. Never raises.

    `timeout` defaults to the budget for this leg (see _unit_suite_timeout); the parameter
    exists so a caller can be explicit, not so the derivation can be bypassed."""
    started = time.time()
    c0 = _leg_clocks()   # [GATE-CLOCK-1] judged by the caller, which knows the leg kind
    budget = timeout or _unit_suite_timeout(ref)
    try:
        # [ORCH-9] S2/S3: NOT _gate_shell_cmd. The declared env_file belongs to the BUILD and
        # SIT gates, which run the app's own toolchain and need its configuration. The unit
        # suite is the opposite case: clinical-mp's vite.config.ts sets `envDir: false` under
        # VITEST expressly to keep the developer .env out of the unit tests (RED-1), and
        # src/lib/llm/__tests__/env-isolation.test.ts asserts those keys are absent from
        # process.env (RED-4). [ORCH-3] inherited the gate-shell convention here without a
        # decision, so `set -a; . ./.env; set +a` exported exactly the keys that test forbids
        # — and the gate then failed the repo for it. Measured at e837cbe, the same seven
        # files back to back: sourced ⇒ 29 failed | 93 passed (122); not sourced ⇒ 3 failed |
        # 119 passed (122). 26 failures, on 6 files, that belonged to the gate and not to the
        # code. The gate must measure the suite the repo runs, not a different one.
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, cwd=str(cwd), timeout=budget)
        raw = (r.stdout or "") + "\n" + (r.stderr or "")
        parsed = _parse_unit_summary(raw)
        return UnitSuiteRun(ref=ref, exit_code=r.returncode, duration_s=time.time() - started,
                            output=raw[-20000:], clocks=(c0, _leg_clocks()),
                            stderr_head=(r.stderr or "")[:GATE_STDERR_HEAD_CHARS], **parsed)
    except subprocess.TimeoutExpired:
        return UnitSuiteRun(ref=ref, exit_code=-1, duration_s=time.time() - started,
                            error="timeout", output="timeout", clocks=(c0, _leg_clocks()))
    except Exception as e:
        return UnitSuiteRun(ref=ref, exit_code=-1, duration_s=time.time() - started,
                            error=str(e), output=str(e), clocks=(c0, _leg_clocks()))


def _run_unit_baseline(repo_path: Path, sha: str, cmd: str) -> UnitSuiteRun:
    """Measure the baseline on `sha` in a DETACHED worktree.

    brief §4 STOP trigger 1: a clinical-mp route may be live in that repo while this runs.
    `git worktree add --detach` touches neither the live working tree nor any branch — it
    writes only to .git/worktrees/ — so the concurrent route is undisturbed. The worktree is
    removed and pruned afterwards; the symlinked dependency dirs are unlinked FIRST so the
    teardown can never reach into the live checkout."""
    ref = f"merge-base {sha[:7]}"
    with tempfile.TemporaryDirectory(prefix=UNIT_BASELINE_WORKTREE_PREFIX) as td:
        wt = Path(td) / "wt"
        add = subprocess.run(
            f"git -C {shlex.quote(str(repo_path))} worktree add --detach "
            f"{shlex.quote(str(wt))} {shlex.quote(sha)}",
            shell=True, capture_output=True, text=True)
        if add.returncode != 0:
            log.error(f"⛔ Unit baseline: detached worktree at {sha[:7]} failed: {(add.stderr or '').strip()[-300:]}")
            return UnitSuiteRun(ref=ref, exit_code=-1, error="baseline-worktree-failed",
                                output=(add.stderr or "")[-2000:])
        links = []
        try:
            links = _link_unit_deps(repo_path, wt)
            log.info(f"🧬 Unit baseline: measuring {ref} in a detached worktree "
                     f"({len(links)} dependency path(s) linked)")
            return _run_unit_suite(cmd, wt, ref)
        finally:
            for d in links:
                try:
                    d.unlink()
                except OSError:
                    pass
            subprocess.run(f"git -C {shlex.quote(str(repo_path))} worktree remove --force {shlex.quote(str(wt))}",
                           shell=True, capture_output=True)
            subprocess.run(f"git -C {shlex.quote(str(repo_path))} worktree prune",
                           shell=True, capture_output=True)


# ── flake-vs-regression confirmation (S7-CORE-9 [ORCH-6]) ─────────────────────────────
# decision 1/2: a verdict is only as good as its evidence, and isolation is the
# discriminator — a newly-failing file that passes ALONE was order/load-dependent on the
# whole-suite run, not broken by this branch. This does not touch `test_cmd` itself (that
# stays whole, [ORCH-5] decision 4) — only the CONFIRMATION leg is narrowed, and only to
# the exact suspect set.
def _unit_confirm_cmd(test_cmd: str, files: tuple) -> str:
    """[ORCH-6] AC-O6-01: the runner invoked on EXACTLY `files` — no other file.

    Appending the files naively is not enough when `test_cmd` itself already carries a
    trailing directory argument (this repo's own `pytest -q tests/`): that argument would
    keep collecting the whole suite alongside the files we asked for, which is not
    isolation. A trailing bare-directory token (one that ends in `/`) is dropped before the
    files are appended; anything else is left alone, which is exactly right for the fleet's
    other declared shape — a bare `npm test` / `pytest` with no path argument.

    `npm`/`yarn`/`pnpm` need `--` to forward args through the package-script layer to the
    underlying runner (vitest/jest); a direct runner invocation does not.
    """
    quoted = " ".join(shlex.quote(f) for f in files)
    stripped = re.sub(r"\s+\S*/\s*$", "", test_cmd)
    last_segment = re.split(r"&&|;|\|\|", stripped)[-1].strip()
    sep = " -- " if re.match(r"(npm|yarn|pnpm)\b", last_segment) else " "
    return f"{stripped}{sep}{quoted}"


def _unit_confirm_new_files(repo_path: Path, test_cmd: str, ref_label: str,
                            new_files: tuple) -> tuple:
    """[ORCH-6] decisions 2 & 4 — re-run exactly `new_files`, alone, on the branch checkout.

    Returns (flakes, regressions, confirm_run). `flakes` is None iff the confirmation pass
    itself could not be performed (timeout, runner error, no parseable summary) — that is
    BLOCKED(environment), never a verdict about the files; the caller tells the two apart by
    checking `flakes is None`, not by inspecting `confirm_run`.
    """
    cmd = _unit_confirm_cmd(test_cmd, new_files)
    ref = f"{UNIT_CONFIRM_REF_PREFIX} {ref_label}"
    run = _run_unit_suite(cmd, repo_path, ref)
    if run.error or run.runner is None or run.failures is None:
        # [ORCH-HANDBACK-SILENT-PASS] P-SAY: exactly one verdict line per engagement, on every path.
        log.error(f"🛡 unit-confirm: BLOCKED — confirmation-unmeasurable: "
                  f"{run.error or run.collection or 'no parseable summary'} ({', '.join(new_files)})")
        return None, None, run
    still_failing = set(run.failing_files) & set(new_files)
    flakes = tuple(sorted(set(new_files) - still_failing))
    regressions = tuple(sorted(still_failing))
    if regressions:
        log.error(f"🛡 unit-confirm: FAIL — still failing alone: {', '.join(regressions)}; "
                  f"flaky: {', '.join(flakes) or '(none)'}")
    else:
        log.info(f"🛡 unit-confirm: CLEAN — every newly-failing file passed alone (flaky): {', '.join(flakes)}")
    return flakes, regressions, run


# ── the baseline cache (S7-CORE-8 [ORCH-5]) ───────────────────────────────────────────
# The baseline for a commit is immutable, so it is measured ONCE and kept, keyed by that
# commit's SHA. Lives in the sit-archive dir — inside this repo, gitignored (`sit-archive/
# *.json`), alongside orchestrator-unit-log.json. No state leaves the orchestrator repo.
#
# What the key covers, and why: (repo, merge-base SHA, test_cmd). The SHA alone is not
# enough — the same commit measured with a DIFFERENT command is a different measurement, and
# reusing it would be exactly the stale-number lie §2.2 warns about. Change `test_cmd` in
# repos.yaml and every entry for it is a miss, which is correct.
def _unit_is_measurement(run: Optional[UnitSuiteRun]) -> bool:
    """Did this run yield a measurement at all? The [ORCH-3] predicate, unchanged and now
    named: an error (timeout, worktree failure) or a demonstrably EMPTY collection is not a
    measurement. `None` counts stay UNKNOWN and fall through to the parse check below — a
    pytest `-q` green summary reports no file count, and treating that as zero would turn a
    reporting gap into a false block, which is precisely what [ORCH-2] ruled against."""
    if run is None or run.error:
        return False
    return run.tests_total != 0 and run.test_files_total != 0


def _unit_is_cacheable(run: UnitSuiteRun) -> bool:
    """A baseline with no failure COUNT cannot serve as a baseline — the comparison needs a
    number. Caching one would freeze an unusable entry in place for every later route off
    this base, so it is measured again instead."""
    return _unit_is_measurement(run) and run.failures is not None


def _unit_cache_file(archive: Path) -> Path:
    return archive / UNIT_BASELINE_CACHE_FILE


def _unit_cache_load(archive: Path) -> dict:
    f = _unit_cache_file(archive)
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text())
    except (json.JSONDecodeError, IOError, OSError):
        log.warning(f"⚠️  Unit baseline cache unreadable at {f} — treated as empty (it will be rewritten)")
        return {}
    if not isinstance(data, dict) or data.get("version") != UNIT_BASELINE_CACHE_VERSION:
        return {}
    entries = data.get("entries")
    return entries if isinstance(entries, dict) else {}


def _unit_cache_key(repo_name: str, sha: str, cmd: str) -> str:
    return f"{repo_name}@{sha}@{hashlib.md5(cmd.encode()).hexdigest()[:8]}"


def _unit_cache_entry_matches(e: dict, repo_name: str, sha: str, cmd: str) -> bool:
    """AC-O5-02: an entry is usable only for the SHA, repo and command it was measured under.
    Checked on the entry itself, not just on the key, so a hand-edited or renamed key cannot
    smuggle a measurement onto the wrong commit."""
    return (isinstance(e, dict) and e.get("sha") == sha
            and e.get("repo") == repo_name and e.get("test_cmd") == cmd)


def _unit_cache_lookup(archive: Path, repo_name: str, sha: str, cmd: str) -> Optional[dict]:
    e = _unit_cache_load(archive).get(_unit_cache_key(repo_name, sha, cmd))
    return e if _unit_cache_entry_matches(e, repo_name, sha, cmd) else None


def _unit_cache_store(archive: Path, repo_name: str, sha: str, cmd: str, run: UnitSuiteRun):
    """Persist a MEASURED baseline. AC-O5-02: files, tests, failures, duration and the SHA.
    The suite output is deliberately NOT stored — it is only ever used to F-20-classify the
    BRANCH leg, and keeping 20KB per commit forever buys nothing.

    [CONFIG-TRUTH-1] only a leg judged plausible reaches this (BASELINE-TRUST-1 returns first on an
    implausible one), and the entry says so: `clock: "plausible"`. Storing supersedes an unjudged
    entry at the same key; that entry's [ORCH-6/7] flaky tally is about files, not about this
    measurement, so it is carried forward."""
    if run.clock is not None:
        return   # BASELINE-TRUST-1: never cached — the field below would be false
    archive.mkdir(parents=True, exist_ok=True)
    entries = _unit_cache_load(archive)
    key = _unit_cache_key(repo_name, sha, cmd)
    prior = entries.get(key)
    flaky = ({k: prior[k] for k in ("flaky_files", "flaky_seen") if k in prior}
             if _unit_cache_entry_matches(prior, repo_name, sha, cmd) else {})
    entries[key] = {
        "sha": sha, "repo": repo_name, "test_cmd": cmd,
        "measured_at": datetime.now().isoformat(),
        "ref": run.ref, "exit_code": run.exit_code, "duration_s": round(run.duration_s, 2),
        "runner": run.runner, "test_files_total": run.test_files_total,
        "tests_total": run.tests_total, "tests_passed": run.tests_passed,
        "failures": run.failures, "failing_files": list(run.failing_files),
        # [ORCH-8] ADDITIVE: a reused baseline must reconcile the same way a measured one
        # does. Entries written before this existed simply lack these keys and read as None.
        "tests_skipped": run.tests_skipped, "tests_todo": run.tests_todo,
        "failures_source": run.failures_source,
        "tests_expected_fail": run.tests_expected_fail,   # [ORCH-TALLY-1], additive the same way
        # [CONFIG-TRUTH-1] additive: an entry without it predates GATE-CLOCK-1 and was never judged
        "clock": "plausible",
        **flaky,
    }
    try:
        _unit_cache_file(archive).write_text(
            json.dumps({"version": UNIT_BASELINE_CACHE_VERSION, "entries": entries}, indent=2))
    except OSError as e:
        log.warning(f"⚠️  Unit baseline cache not written ({e}) — the next route will re-measure")


def _unit_cache_judged(e: dict) -> bool:
    """[CONFIG-TRUTH-1] was this entry's clock judged? Only the store writes `clock`, and only after
    GATE-CLOCK-1; an entry without it is a miss, superseded one key at a time as it is needed."""
    return e.get("clock") == "plausible"


def _unit_cache_record_flakes(archive: Path, repo_name: str, sha: str, cmd: str, flakes: tuple):
    """[ORCH-6] AC-O6-06: union `flakes` into the ADDITIVE `flaky_files` field on the cached
    baseline entry for `sha` — every existing field (brief §4 STOP trigger 3) is untouched.
    Two routes off the same base naming the same file is exactly the recurrence signal the
    brief asks to make visible, so this ACCUMULATES rather than overwrites. A no-op when
    there is no matching entry to attach to — nothing here invents one.

    [ORCH-7] AC-O7-02: also accumulates a per-file `flaky_seen` count and last-seen
    timestamp, ADDITIVE alongside `flaky_files` — a second, ADDITIVE field, not a
    replacement for it. Entries written before this existed simply lack `flaky_seen`."""
    if not flakes:
        return
    entries = _unit_cache_load(archive)
    key = _unit_cache_key(repo_name, sha, cmd)
    entry = entries.get(key)
    if not _unit_cache_entry_matches(entry, repo_name, sha, cmd):
        return
    entry["flaky_files"] = sorted(set(entry.get("flaky_files") or ()) | set(flakes))
    now = datetime.now().isoformat()
    seen = entry.get("flaky_seen") or {}
    for f in flakes:
        prior = seen.get(f) or {}
        seen[f] = {"count": prior.get("count", 0) + 1, "last_seen": now}
    entry["flaky_seen"] = seen
    try:
        _unit_cache_file(archive).write_text(
            json.dumps({"version": UNIT_BASELINE_CACHE_VERSION, "entries": entries}, indent=2))
    except OSError as e:
        log.warning(f"⚠️  Unit gate: flaky-file set not persisted ({e})")


def _flaky_collect(archive: Path, repo_filter: str = "") -> dict:
    """[ORCH-7] AC-O7-01/02/03: read-only aggregation of every cache entry's flaky data,
    grouped by repo. Never writes. An entry written before `flaky_seen` existed (ORCH-6
    shape) still contributes its files, with `count`/`last_seen` left None — read without
    error rather than crashing (AC-O7-02)."""
    report: dict = {}
    for entry in _unit_cache_load(archive).values():
        if not isinstance(entry, dict):
            continue
        repo_name = entry.get("repo")
        if not repo_name or (repo_filter and repo_name != repo_filter):
            continue
        repo_report = report.setdefault(repo_name, {})
        seen = entry.get("flaky_seen") or {}
        for f in (entry.get("flaky_files") or ()):
            row = repo_report.setdefault(f, {"count": None, "last_seen": None})
            stat = seen.get(f)
            if not stat:
                continue
            c = stat.get("count")
            row["count"] = c if row["count"] is None else row["count"] + (c or 0)
            last_seen = stat.get("last_seen")
            if last_seen and (row["last_seen"] is None or last_seen > row["last_seen"]):
                row["last_seen"] = last_seen
    return report


def flaky_report(repo_filter: str = ""):
    """[ORCH-7] the `flaky` subcommand: per repo, every file the confirmation pass has ever
    classified as a flake, how many times, and when it was last seen — most-frequent first.
    AC-O7-01/03/04/05. Read-only: only ever calls `_unit_cache_load` (AC-O7-06)."""
    report = _flaky_collect(SIT_ARCHIVE_DIR, repo_filter)
    if not any(report.values()):
        print("No flakes recorded.")
        return

    print(f"\n{'═'*60}")
    print(f"FLAKY FILES{f' — {repo_filter}' if repo_filter else ''}")
    print(f"{'═'*60}")
    for repo_name in sorted(report):
        files = report[repo_name]
        if not files:
            continue
        print(f"\n  {repo_name}:")
        ranked = sorted(
            files.items(),
            key=lambda kv: (-(kv[1]["count"] if kv[1]["count"] is not None else -1), kv[0]))
        for f, stat in ranked:
            count = stat["count"]
            count_str = f"{count}x" if count is not None else "?x"
            last_seen = (stat["last_seen"] or "unknown")[:19]
            quarantine = (count is not None and count >= UNIT_FLAKY_QUARANTINE_THRESHOLD)
            tag = "  ⚠️  quarantine candidate" if quarantine else ""
            print(f"    {count_str:>4}  last seen {last_seen:<19}  {f}{tag}")
    print(f"{'═'*60}\n")


_LOG_TS_RE = re.compile(r"-(\d{8}-\d{6})\.log$")


def handback_scan(paths: list[str], until: Optional[str] = None) -> int:
    """[ORCH-HANDBACK-GUARD-1] the `handback-scan` subcommand: check_handback_invariants over
    fire_toni logs, with the same rules _run_batch_inner judges by. Each PATH is a file or a
    directory (its `toni-*.log`, non-recursive); no PATH ⇒ LOG_DIR/<log_subdir> for every repo in
    config/repos.yaml. `until` (YYYYMMDD-HHMMSS) keeps only logs whose filename timestamp is <= it,
    which pins a corpus. Read-only. Returns 1 if any violation, 2 if the rules do not resolve."""
    rules = load_outstanding_work_rules(HANDBACK_GUARD_CONFIG)
    if rules is None:
        print(f"handback guard unconfigured: {HANDBACK_GUARD_CONFIG} is missing or invalid")
        return 2
    if not paths:
        repos = load_repo_config()["repos"]
        paths = [str(LOG_DIR / r.get("log_subdir", n)) for n, r in repos.items()]
    files: list[Path] = []
    for raw in paths:
        p = Path(raw).expanduser()
        files.extend(sorted(p.glob("toni-*.log")) if p.is_dir() else [p])
    if until:
        files = [f for f in files if (m := _LOG_TS_RE.search(f.name)) and m.group(1) <= until]
    counts = {"outstanding-work": 0, "no-toni-header": 0, "log-unreadable": 0, "clean": 0}
    per_rule = {r.id: 0 for r in rules}
    for f in files:
        found = check_handback_invariants(f, rules)
        for v in found:
            print(f"FAIL {f}: {v}")
            if v.reason == "outstanding-work":
                per_rule[v.rule] += 1
        counts[found[0].reason if found else "clean"] += 1
    print(f"{len(files)} logs scanned: " + ", ".join(f"{n} {k}" for k, n in counts.items())
          + "; per rule: " + ", ".join(f"{k} {n}" for k, n in per_rule.items()))
    return 1 if len(files) != counts["clean"] else 0


# ── verify (S7-CORE-19 [ORCH-LANE-1] O3) ─────────────────────────────────────────────────────
# ~/_eos/s7core17/verify.sh hard-coded ~/spectricom-clinical-mp. For route 109 (ai-foundation, fired
# directly) its `ls -t logs/*/orch-$B-*.log` matched nothing — a daemon route writes
# logs/<log_subdir>/orch-<stem>-<ts>.log, a direct `run` only logs/orch-<ts>.log — and `grep … $OL` with
# no file waited on stdin. One read-only verifier, here: any route of any repo in config/repos.yaml.
VERIFY_LOG_RE = re.compile(r"FINAL STATUS|verdict|gate|baseline|\bSIT\b|unit|🛡|Merged", re.IGNORECASE)
VERIFY_LOG_LINES = 14
VERIFY_LINE_CHARS = 260
VERIFY_STAT_LINES = 25
VERIFY_HANDBACK_LINES = 80
_VERIFY_STEM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_VERIFY_HEAD_BYTES = 4096
_VERIFY_ROOT_LOG_RE = re.compile(r"orch-\d{8}-\d{6}\.log")
_VERIFY_MERGED_RE = re.compile(r"🔀 Merged \S+ → \S+ \(\w+ → (\w+)\)")
_VERIFY_TONI_LOG_RE = re.compile(r"\bLog: (\S*toni-\S+\.log)")


def _verify_route_logs(stem: str, log_dir: Path, kind: str) -> list:
    """`<kind>-<stem>-<ts>.log` in `log_dir`, oldest first — that stem exactly: verify.sh's
    `orch-109-x-*.log` also matched orch-109-x-2-<ts>.log."""
    rx = re.compile(rf"{kind}-{re.escape(stem)}-\d{{8}}-\d{{6}}\.log")
    return sorted((p for p in log_dir.glob(f"{kind}-{stem}-*.log") if rx.fullmatch(p.name)), key=lambda p: p.name)


def _verify_orch_log(stem: str, log_dir: Path) -> Optional[Path]:
    """The orch log of `stem`'s newest route: a daemon route's own log_dir/orch-<stem>-<ts>.log, or a direct
    run's LOG_DIR/orch-<ts>.log, whose head names the brief (`Parsed <stem>.md:`). A daemon route's own
    orchestrator process writes one of those too, inside the route, so a direct run counts only when it
    started after the daemon route's log was last written. This process's log (setup_logging) is never one."""
    own = _verify_route_logs(stem, log_dir, "orch")
    daemon = own[-1] if own else None
    after = datetime.fromtimestamp(daemon.stat().st_mtime).strftime("%Y%m%d-%H%M%S") if daemon else ""
    needle = f"Parsed {stem}.md:".encode()
    mine = Path(log_file).resolve()
    for p in sorted((p for p in LOG_DIR.glob("orch-*.log") if _VERIFY_ROOT_LOG_RE.fullmatch(p.name)),
                    key=lambda p: p.name, reverse=True):
        if _LOG_TS_RE.search(p.name).group(1) <= after:
            break
        if p.resolve() == mine:
            continue
        try:
            with p.open("rb") as fh:
                if needle in fh.read(_VERIFY_HEAD_BYTES):
                    return p
        except OSError:
            continue
    return daemon


def _verify_toni_log(stem: str, log_dir: Path, orch_text: str) -> Optional[Path]:
    """The Toni log the orch log names (`Log: …/toni-<stem>-<ts>.log`, looked up by NAME in log_dir — never
    the absolute path it was written under), else the newest toni-<stem>-<ts>.log in log_dir."""
    rx = re.compile(rf"toni-{re.escape(stem)}-\d{{8}}-\d{{6}}\.log")
    for name in reversed([Path(m).name for m in _VERIFY_TONI_LOG_RE.findall(orch_text)]):
        if rx.fullmatch(name) and (log_dir / name).is_file():
            return log_dir / name
    found = _verify_route_logs(stem, log_dir, "toni")
    return found[-1] if found else None


def _verify_repo(stem: str, repos: dict) -> tuple:
    """(repo, how it was known): the `#!queue repo=…` / `## Repo:` of the stem's brief — in queue/,
    queue/done/, queue/failed/ or a repo's briefs dir — else the one repo whose log dir holds its logs.
    (None, why) when neither decides: nothing is guessed."""
    entries = {n: r for n, r in repos.items() if isinstance(r, dict)}
    places = [QUEUE_DIR, QUEUE_DONE, QUEUE_DIR / "failed"] + [
        Path(r["project_dir"]).expanduser() / r.get("briefs_subdir", "briefs")
        for r in entries.values() if r.get("project_dir")]
    named = {}
    for d in places:
        b = d / f"{stem}.md"
        if b.is_file() and (n := parse_repo_from_brief(b)):
            named.setdefault(n, b)
    if len(named) > 1:
        return None, "its briefs name different repos (" + ", ".join(f"{n} in {b}" for n, b in sorted(named.items())) + ")"
    if named:
        (n, b), = named.items()
        if n not in entries:
            return None, f"its brief {b} names repo {n}, which is not in {REPOS_CONFIG_PATH}"
        return n, f"brief header: {b}"
    logged = [n for n, r in sorted(entries.items())
              if _verify_route_logs(stem, LOG_DIR / r.get("log_subdir", n), "toni")
              or _verify_route_logs(stem, LOG_DIR / r.get("log_subdir", n), "orch")]
    if len(logged) == 1:
        return logged[0], f"logs/{entries[logged[0]].get('log_subdir', logged[0])}/ holds its logs; no brief found"
    if logged:
        return None, f"its logs are in {len(logged)} repos' log dirs ({', '.join(logged)}) and no brief decides"
    return None, f"no brief and no route log for it in any repo of {REPOS_CONFIG_PATH}"


def _verify_git(repo_dir: Path, *args: str) -> tuple:
    """A read-only git command in `repo_dir`: (exit code, its output). Never reads stdin; never raises."""
    try:
        r = subprocess.run(["git", "-C", str(repo_dir), *args], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout).strip())


def _verify_commit(stem: str, given: Optional[str], orch_text: str, repo_dir: Path, cfg: dict) -> tuple:
    """(commit, whence): --commit; else the orch log's `🔀 Merged … (<old> → <new>)`; else the route branch,
    unmerged; else the newest merge-target commit touching the handback. (None, why) when none is found."""
    if given:
        return given, "--commit"
    merged = _VERIFY_MERGED_RE.findall(orch_text)
    if merged:
        return merged[-1], "the orch log's merge line"
    branch = f"{cfg.get('branch_prefix', 'orch')}-{stem}"
    if _verify_git(repo_dir, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")[0] == 0:
        return branch, "the route branch — no merge in the orch log"
    target = cfg.get("merge_target", "main")
    handback = f"{cfg.get('briefs_subdir', 'briefs')}/{stem}.handback.md"
    code, out = _verify_git(repo_dir, "log", "-1", "--format=%h", target, "--", handback)
    if code == 0 and out.strip():
        return out.strip(), f"the newest {target} commit touching {handback}"
    return None, (f"no merge line in the orch log, no branch {branch}, no {target} commit touching {handback} "
                  f"— pass --commit <sha>")


def verify_route(stem: str, commit: Optional[str] = None) -> int:
    """[ORCH-LANE-1] O3: the `verify` subcommand — one route's evidence, from the repo its brief names:
    the FINAL STATUS / gate / unit lines of its newest orch log, handback-scan over its Toni log,
    `git show --stat` of its commit and the head of its handback at that commit. Read-only: it reads logs
    and runs git show / log / rev-parse; it never reads stdin. 0 — every section found and clean;
    1 — found, with something to look at (no FINAL STATUS, a handback-scan FAIL, the commit or its handback
    not shown); 2 — it cannot verify: an unknown stem or repo, a missing log, each said in one line."""
    stem = Path(stem).name
    for suffix in (".md", ".handback"):
        stem = stem[:-len(suffix)] if stem.endswith(suffix) else stem
    if not _VERIFY_STEM_RE.fullmatch(stem):
        print(f"verify: {stem!r} — not a brief stem (letters, digits, '.', '_', '-')", file=sys.stderr)
        return 2
    if commit is not None and (not commit.strip() or commit.startswith("-")):
        print(f"verify: {stem} — --commit {commit!r} is not a commit", file=sys.stderr)
        return 2
    try:
        repos = load_repo_config()["repos"]
    except RuntimeError as e:
        print(f"verify: {stem} — {e}", file=sys.stderr)
        return 2
    name, how = _verify_repo(stem, repos)
    if name is None:
        print(f"verify: {stem} — {how}", file=sys.stderr)
        return 2
    cfg = repos[name]
    repo_dir = Path(cfg["project_dir"]).expanduser()
    log_dir = LOG_DIR / cfg.get("log_subdir", name)
    orch = _verify_orch_log(stem, log_dir)
    if orch is None:
        print(f"verify: {stem} — no orch log: no orch-{stem}-<ts>.log in {log_dir}, no orch-<ts>.log in "
              f"{LOG_DIR} whose head says `Parsed {stem}.md:`", file=sys.stderr)
        return 2
    rc = 0
    text = orch.read_text(encoding="utf-8", errors="replace")
    print(f"verify {stem} — repo {name} ({how}) · {repo_dir}")
    print(f"== orch log {orch}")
    lines = [l for l in text.splitlines() if VERIFY_LOG_RE.search(l)]
    final = [l for l in lines if "FINAL STATUS" in l]
    shown = lines[-VERIFY_LOG_LINES:] + ([final[-1]] if final and final[-1] not in lines[-VERIFY_LOG_LINES:] else [])
    for l in shown:
        print(l[:VERIFY_LINE_CHARS])
    if not final:
        print(f"no FINAL STATUS line in {orch.name} — the route has not finished, or was killed")
        rc = 1
    toni = _verify_toni_log(stem, log_dir, text)
    if toni is None:
        print(f"== handback-scan: no toni log in {log_dir} (toni-{stem}-*.log) — not run")
        rc = 2
    else:
        print(f"== handback-scan {toni}")
        if handback_scan([str(toni)]) != 0:
            rc = max(rc, 1)
    sha, whence = _verify_commit(stem, commit, text, repo_dir, cfg)
    if sha is None:
        print(f"== show --stat: {whence}")
        return max(rc, 1)
    code, out = _verify_git(repo_dir, "show", "--stat", "--format=%h %s", sha, "--")
    print(f"== show --stat {sha} ({whence})")
    print("\n".join(out.splitlines()[-VERIFY_STAT_LINES:]))
    handback = f"{cfg.get('briefs_subdir', 'briefs')}/{stem}.handback.md"
    hcode, hout = _verify_git(repo_dir, "show", f"{sha}:{handback}")
    if hcode == 0:
        print(f"== handback {handback} @ {sha}")
        print("\n".join(hout.splitlines()[:VERIFY_HANDBACK_LINES]))
    else:
        print(f"== handback: no {handback} at {sha}")
    return max(rc, 1 if code or hcode else 0)


def _unit_run_from_cache(e: dict, ref: str) -> UnitSuiteRun:
    """Rehydrate a stored measurement. `error` stays None and `output` empty: this is a real
    measurement that completed, and it has no output to classify."""
    return UnitSuiteRun(ref=ref, exit_code=e.get("exit_code", -1),
                        duration_s=float(e.get("duration_s") or 0.0), runner=e.get("runner"),
                        test_files_total=e.get("test_files_total"), tests_total=e.get("tests_total"),
                        tests_passed=e.get("tests_passed"), failures=e.get("failures"),
                        tests_skipped=e.get("tests_skipped"), tests_todo=e.get("tests_todo"),
                        tests_expected_fail=e.get("tests_expected_fail"),
                        failures_source=e.get("failures_source"),
                        failing_files=tuple(e.get("failing_files") or ()))


def _unit_cache_ancestor(repo_path: Path, archive: Path, repo_name: str, base_sha: str,
                         cmd: str) -> Optional[dict]:
    """[ORCH-5] decision 3 — the LAST resort, used only after a fresh measurement has already
    failed. The nearest ANCESTOR of the merge base that we have a real measurement for.

    This is still a baseline we measured; it is not one we inferred. But it is a baseline for
    an OLDER commit, so the comparison it supports is approximate in both directions, and
    every caller of this is required to say so in the verdict. Nothing here invents a number,
    and nothing here reads main's tip.

    [CONFIG-TRUTH-1] an entry whose clock was never judged is not a candidate — and it cannot be
    re-measured here, since the measurement at the base has just failed."""
    best, best_distance, unjudged = None, None, 0
    for e in _unit_cache_load(archive).values():
        if not isinstance(e, dict) or e.get("repo") != repo_name or e.get("test_cmd") != cmd:
            continue
        sha = e.get("sha")
        if not sha or sha == base_sha:
            continue
        if not _unit_cache_judged(e):
            unjudged += 1
            continue
        anc = subprocess.run(
            f"git -C {shlex.quote(str(repo_path))} merge-base --is-ancestor "
            f"{shlex.quote(sha)} {shlex.quote(base_sha)}",
            shell=True, capture_output=True)
        if anc.returncode != 0:
            continue
        d = subprocess.run(
            f"git -C {shlex.quote(str(repo_path))} rev-list --count "
            f"{shlex.quote(sha)}..{shlex.quote(base_sha)}",
            shell=True, capture_output=True, text=True)
        try:
            distance = int((d.stdout or "").strip())
        except ValueError:
            continue
        if best_distance is None or distance < best_distance:
            best, best_distance = e, distance
    if unjudged:
        log.info(f"♻️  Unit baseline: {unjudged} cached {repo_name} "
                 f"{'entry predates' if unjudged == 1 else 'entries predate'} GATE-CLOCK-1 (clock never judged) "
                 f"— not considered as an ancestor baseline")
    if best is not None:
        best = dict(best, ancestor_distance=best_distance)
    return best


def _unit_baseline_measure_or_reuse(repo_path: Path, base_sha: str, cmd: str, archive: Path,
                                    repo_name: str) -> tuple:
    """Get the baseline for `base_sha`. Returns (UnitSuiteRun|None, source, note).

    `source` is one of "cache" | "measured" | "ancestor-cache" | "unmeasurable" | "implausible"
    and reaches the verdict verbatim (AC-O5-05) — the operator is never left guessing whether a
    number was measured just now or read off disk.

    [BASELINE-TRUST-1] P-BASE: reached only past the [ORCH-5] green fast path, so every PASS it
    feeds is a comparison. A baseline leg on an implausible clock is never compared against and
    never cached: it is measured ONCE more, and a second implausible leg is "implausible" — the
    gate's BLOCKED(environment) `baseline-clock-implausible`. Exactly one `🛡 baseline-trust:`
    line per call (P-SAY).

    [CONFIG-TRUTH-1] a cached entry is a hit only if its clock was judged (`clock: "plausible"`). One
    that predates GATE-CLOCK-1 is a miss: measured again, and a plausible leg overwrites it."""
    hit = _unit_cache_lookup(archive, repo_name, base_sha, cmd)
    if hit and not _unit_cache_judged(hit):
        log.info(f"♻️  Unit baseline: cached entry at {base_sha[:7]} predates GATE-CLOCK-1 (clock never "
                 f"judged) — re-measuring")
        hit = None
    if hit:
        run = _unit_run_from_cache(hit, f"{UNIT_BASELINE_REF_PREFIX} {base_sha[:7]}")
        measured_at = hit.get("measured_at", "?")[:19]
        note = (f"read from cache — measured {measured_at} at "
                f"{base_sha[:7]}, {run.collection or 'collection unknown'} in {run.duration_s:.1f}s; "
                f"not re-run (the baseline for a commit does not change)")
        log.info(f"♻️  Unit baseline: CACHE HIT for {base_sha[:7]} — {run.collection}; no baseline run")
        log.info(f'🛡 baseline-trust: CLEAN — cache hit at {base_sha[:7]}, measured {measured_at} on a clock '
                 f'judged plausible (cache entry "clock": "{hit["clock"]}")')
        return run, "cache", note

    log.info(f"🧬 Unit baseline: cache MISS for {base_sha[:7]} — measuring "
             f"(budget {_unit_suite_timeout(UNIT_BASELINE_REF_PREFIX)}s)")
    run = _run_unit_baseline(repo_path, base_sha, cmd)
    log.info(f"🧬 Unit gate baseline run — {run.describe}")
    run.clock = _judge_leg("unit-baseline", run.clocks, archive, red=run.exit_code != 0,
                           completed=run.error is None)
    trust, again = "measured on a plausible clock", ""
    if run.clocks is None:
        trust = f"no leg ran ({run.error or 'not measured'}), so no clock to judge"
    if run.clock is not None:
        # [BASELINE-TRUST-1] a sleep can manufacture baseline failures, and each one would pass a
        # branch failure off as debt: the masked regression route 61 found. Discard the leg and
        # measure once more; whatever follows stands on the re-measure alone.
        first = run
        log.warning(f"🧬 Unit baseline: the leg at {base_sha[:7]} is implausible ({first.clock}) — "
                    f"discarded, not compared, not cached; re-measuring once")
        run = _run_unit_baseline(repo_path, base_sha, cmd)
        log.info(f"🧬 Unit gate baseline re-measure — {run.describe}")
        run.clock = _judge_leg("unit-baseline", run.clocks, archive, red=run.exit_code != 0,
                               completed=run.error is None)
        if run.clock is not None:
            note = (f"measured twice at {base_sha[:7]}, both legs implausible (first: {first.clock}; "
                    f"re-measure: {run.clock}); NOT compared against, NOT cached")
            log.error(f"🛡 baseline-trust: BLOCKED — baseline-clock-implausible: {note} — never PASS, "
                      f"never FAIL(product)")
            return run, "implausible", note
        trust = f"re-measured once on a plausible clock (first leg discarded: {first.clock})"
        again = f" — re-measured once, the first leg was implausible ({first.clock})"
    log.info(f"🛡 baseline-trust: CLEAN — unit-baseline at {base_sha[:7]} {trust}")
    if _unit_is_cacheable(run):
        _unit_cache_store(archive, repo_name, base_sha, cmd, run)
        return run, "measured", f"measured now at {base_sha[:7]} and cached for later routes off this base{again}"
    if _unit_is_measurement(run):
        # It ran and collected something, but the summary gave no failure count. That is the
        # [ORCH-3] `comparison-unavailable` path — let it reach its own verdict, uncached.
        return run, "measured", (f"measured now at {base_sha[:7]}; NOT cached — the summary "
                                 f"yielded no failure count{again}")

    # The fresh measurement failed outright. Decision 3: an ancestor we DID measure is usable
    # — said out loud — and if there is none, the block stands.
    why = (run.error or run.collection or "no measurement") + again
    anc = _unit_cache_ancestor(repo_path, archive, repo_name, base_sha, cmd)
    if anc:
        anc_run = _unit_run_from_cache(anc, f"{UNIT_BASELINE_REF_PREFIX} {anc['sha'][:7]} (ancestor)")
        note = (f"NOT measured at the merge base {base_sha[:7]} ({why}); compared instead against "
                f"the nearest measured ANCESTOR {anc['sha'][:7]}, {anc.get('ancestor_distance', '?')} "
                f"commit(s) back, measured {anc.get('measured_at', '?')[:19]} — an approximate "
                f"baseline, stated as such")
        log.warning(f"⚠️  Unit baseline: {note}")
        return anc_run, "ancestor-cache", note
    return run, "unmeasurable", f"no measurement at {base_sha[:7]} ({why}) and no measured ancestor in the cache"


def _unit_gate_eligible_repos() -> set:
    """§2.3 / AC-O3-01: the gated set is DERIVED from config/repos.yaml — every repo that
    declares a non-empty `test_cmd`. No repo name is hard-coded here; a repo that has not
    declared a command is ungated and no default is invented for it."""
    try:
        repos = load_repo_config()["repos"]
    except Exception as e:
        log.warning(f"⚠️  Unit gate: repo config unreadable ({e}) — no repo derived as eligible")
        return set()
    return {n for n, r in repos.items() if isinstance(r, dict) and (r.get("test_cmd") or "").strip()}


def run_unit_gate(repo_path: Path, branch_name: Optional[str] = None,
                  archive_path: Optional[Path] = None) -> UnitGateOutcome:
    """Baseline unit-suite gate. Halts iff the branch has a confirmed regression.

    [ORCH-6b] decision 1 — a regression is a named test FILE that fails in isolation on the
    branch and did not fail at the merge base. That, and only that, produces FAIL(product).
    The failure-COUNT delta is measured, logged and cached as evidence, but never appears in
    the boolean that decides the verdict — the same tree measures too noisily run to run for
    a count alone to carry signal.
    §2.4 — zero collection is BLOCKED(environment), never FAIL(product) and never a PASS.
    """
    started = time.time()
    test_cmd = (ACTIVE_REPO_CONFIG.get("test_cmd") or "").strip()
    if not test_cmd or ACTIVE_REPO_NAME not in _unit_gate_eligible_repos():
        # AC-O3-02: no declared command ⇒ no unit gate, and that is a stated decision, not a
        # silent skip. Do NOT invent a default command for a repo that has not declared one.
        log.info(f"🚪 Unit gate: repo '{ACTIVE_REPO_NAME}' declares no test_cmd — ungated by policy")
        return UnitGateOutcome(passed=True, signal="ungated",
                               detail=f"{ACTIVE_REPO_NAME}: no test_cmd in repos.yaml — ungated by policy")
    if not UNIT_GATE_ENABLED:
        log.warning("⏭️  Unit baseline gate BYPASSED (DISABLE_UNIT_GATE) — emergency operator escape")
        return UnitGateOutcome(passed=True, signal="disabled", detail="DISABLE_UNIT_GATE set")
    if not _is_git_work_tree(repo_path):
        # No git working tree ⇒ no route branch and no merge base ⇒ nothing to baseline
        # against. The production callers always hand this a real checkout; this path exists
        # for manual/test invocation and says so loudly rather than inventing a verdict.
        log.warning(f"⚠️  Unit gate: {repo_path} is not a git work tree — no branch to baseline; gate not applicable")
        return UnitGateOutcome(passed=True, signal="not-applicable",
                               detail=f"{repo_path} is not a git work tree")

    base_sha = _unit_merge_base(repo_path, branch_name)
    if not base_sha:
        # A baseline that cannot be measured is not a baseline. §2.2 forbids falling back to
        # a stored number or to main's tip, so this is an environment block, not a product one.
        detail = f"merge-base {MERGE_TARGET}..{branch_name or 'HEAD'} not resolvable in {repo_path}"
        log.error(f"⛔ Unit gate: {detail} — BLOCKED(environment); baseline cannot be measured")
        return UnitGateOutcome(passed=False, signal="baseline-unresolvable", detail=detail, env=True, ran=True)

    label = branch_name or "HEAD"
    log.info(f"🧪 Unit baseline gate [{ACTIVE_REPO_NAME}]: {test_cmd} — branch {label} vs merge-base {base_sha[:7]}")
    branch_run = _run_unit_suite(test_cmd, repo_path, label)
    log.info(f"🧪 Unit gate branch run — {branch_run.describe}")
    archive = archive_path or SIT_ARCHIVE_DIR
    branch_run.clock = _judge_leg("unit-branch", branch_run.clocks, archive,
                                  red=branch_run.exit_code != 0 or bool(branch_run.failures),
                                  completed=branch_run.error is None)

    baseline_run = None
    baseline_note = None
    if branch_run.error == "timeout":
        detail = f"branch suite exceeded {UNIT_GATE_TIMEOUT}s — no product verdict was produced"
        log.error(f"⛔ Unit gate: {detail} — BLOCKED(environment)")
        return _unit_done(UnitGateOutcome(passed=False, signal="timeout", detail=detail, env=True,
                                          ran=True, branch=branch_run), started, repo_path, archive_path)
    if branch_run.tests_total == 0 or branch_run.test_files_total == 0:
        # §2.4 / AC-O3-07: a green exit over an empty collection tested nothing.
        detail = f"branch suite collected NOTHING ({branch_run.collection}) — nothing was tested"
        log.error(f"⛔ Unit gate: {detail} — BLOCKED(environment), not PASS, not FAIL(product)")
        return _unit_done(UnitGateOutcome(passed=False, signal="zero-collection", detail=detail, env=True,
                                          ran=True, branch=branch_run), started, repo_path, archive_path)

    # [ORCH-5]'s green-branch fast path is the one consumer of `failures` that reads an
    # ABSOLUTE threshold rather than a delta, so it is the one the [ORCH-8] correction
    # actually moves. Before the fix, clinical-mp's 8 skipped + 4 todo were counted as 12
    # failures, so a branch with nothing genuinely failing reported 12 and this path was
    # UNREACHABLE for that repo — it paid for a baseline leg it did not need, every route.
    # The threshold itself is unchanged: 0 still means 0, it is now simply true when the
    # suite is in fact green. `exit_code == 0` still guards it, so a red run cannot slip
    # through on a mis-parse.
    branch_green = branch_run.exit_code == 0 and not branch_run.failing_files and (branch_run.failures or 0) == 0
    if branch_green and UNIT_GATE_SKIP_BASELINE_WHEN_GREEN:
        baseline_note = (f"not measured — branch is fully green (0 failures); no baseline can make "
                         f"a green branch a regression (merge-base {base_sha[:7]})")
        # AC-O5-05: even the skip declares its provenance, so the verdict never reads as if a
        # measurement happened.
        baseline_source = "not-needed"
        log.info(f"✅ UNIT BASELINE GATE PASSED — branch green: {branch_run.describe}; baseline {baseline_note}")
        return _unit_done(UnitGateOutcome(passed=True, ran=True, branch=branch_run,
                                          baseline_note=baseline_note, baseline_source=baseline_source,
                                          detail=f"branch green ({branch_run.collection})"),
                          started, repo_path, archive_path)

    # [ORCH-5]: measured once per merge base, then reused. The measurement is still OURS and
    # still on the merge base — it is simply not repeated for a commit that has not changed.
    baseline_run, baseline_source, baseline_note = _unit_baseline_measure_or_reuse(
        repo_path, base_sha, test_cmd, archive_path or SIT_ARCHIVE_DIR, ACTIVE_REPO_NAME)

    def _finish(o: UnitGateOutcome) -> UnitGateOutcome:
        return _unit_done(o, started, repo_path, archive_path)

    if baseline_source == "implausible":
        # [BASELINE-TRUST-1] P-BASE: the branch has failures, so any verdict here is a comparison,
        # and neither baseline leg's clock supports one — never PASS, never FAIL(product).
        detail = (f"the BASELINE at {base_sha[:7]} cannot be trusted — {baseline_note}; the branch's "
                  f"{branch_run.failures} failure(s) were compared against nothing")
        log.error(f"⛔ Unit gate: {detail} — BLOCKED(environment), not PASS, not FAIL(product)")
        return _finish(UnitGateOutcome(passed=False, signal="baseline-clock-implausible", detail=detail,
                                       env=True, ran=True, branch=branch_run, baseline=baseline_run,
                                       baseline_note=baseline_note, baseline_source=baseline_source))

    if baseline_source == "unmeasurable" or baseline_run is None or not _unit_is_measurement(baseline_run):
        # AC-O5-04: a timeout here means the MEASUREMENT failed, not the product. Say that in
        # those words — the first live run of this gate reported `baseline-unmeasurable
        # (timeout)` and the branch was correctly preserved; the wording must keep making
        # clear that nothing was learned about the code.
        why = (baseline_run.error if baseline_run else None) or (baseline_run.collection if baseline_run else None) or "no measurement"
        if why == "timeout":
            why = (f"timeout — the baseline suite exceeded its "
                   f"{_unit_suite_timeout(UNIT_BASELINE_REF_PREFIX)}s budget")
        detail = (f"the BASELINE MEASUREMENT at {base_sha[:7]} failed ({why}) — this says nothing "
                  f"about the branch; the comparison simply cannot be made")
        log.error(f"⛔ Unit gate: {detail} — BLOCKED(environment), not FAIL(product)")
        return _finish(UnitGateOutcome(passed=False, signal="baseline-unmeasurable", detail=detail, env=True,
                                       ran=True, branch=branch_run, baseline=baseline_run,
                                       baseline_note=baseline_note, baseline_source=baseline_source))

    if branch_run.failures is None or baseline_run.failures is None:
        # Both sides red with output we cannot parse: we cannot tell a regression from
        # pre-existing debt. Say so — a measurement failure is environment, never a silent pass.
        # [ORCH-LANE-1] O5: and when the leg that did not parse died fast, how it died.
        leg, unparsed = ("branch", branch_run) if branch_run.failures is None else ("baseline", baseline_run)
        died = None if unparsed.error else _gate_fast_death(unparsed.exit_code, unparsed.duration_s,
                                                            unparsed.stderr_head)
        detail = (f"suite output did not parse on {leg} "
                  f"(runner={branch_run.runner or baseline_run.runner or 'unrecognised'}); "
                  f"baseline comparison impossible" + (f"; on the {leg} the test command {died}" if died else ""))
        log.error(f"⛔ Unit gate: {detail} — BLOCKED(environment)")
        return _finish(UnitGateOutcome(passed=False, signal="comparison-unavailable", detail=detail, env=True,
                                       ran=True, branch=branch_run, baseline=baseline_run,
                                       baseline_note=baseline_note, baseline_source=baseline_source))

    new_files = tuple(sorted(set(branch_run.failing_files) - set(baseline_run.failing_files)))
    # S7-CORE-9 [ORCH-6b] decision 1/2: the same tree measures 68/104/106/118 failures across
    # runs on one commit — a count delta carries no signal on its own. It is still measured,
    # logged and cached below, but it never appears in the boolean that decides the verdict.
    worse_count = branch_run.failures > baseline_run.failures

    flakes, regressions, confirm_run = (), (), None
    if new_files:
        # S7-CORE-9 [ORCH-6] decisions 1/2: a single pair of whole-suite runs is not enough
        # evidence for FAIL(product) — confirm the suspect set in isolation before deciding.
        log.info(f"🔬 Unit gate: {len(new_files)} newly-failing file(s) — confirming in "
                 f"isolation before verdict: {', '.join(new_files)}")
        flakes, regressions, confirm_run = _unit_confirm_new_files(repo_path, test_cmd, label, new_files)
        if confirm_run is not None:
            confirm_run.clock = _judge_leg("unit-confirm", confirm_run.clocks, archive,
                                           red=flakes is None or bool(regressions),
                                           completed=confirm_run.error is None)
        if flakes is None:
            # decision 4: fail closed. A confirmation pass that did not complete is not
            # evidence of health — never PASS, never FAIL(product).
            why = (confirm_run.error if confirm_run else None) or \
                (confirm_run.collection if confirm_run else None) or "no measurement"
            if why == "timeout":
                why = (f"timeout — the confirmation pass exceeded its "
                       f"{_unit_suite_timeout(UNIT_CONFIRM_REF_PREFIX)}s budget")
            detail = (f"newly-failing file(s) {', '.join(new_files)} could not be confirmed in "
                      f"isolation ({why}) — the flake/regression distinction cannot be made")
            log.error(f"⛔ Unit gate: {detail} — BLOCKED(environment), not FAIL(product)")
            return _finish(UnitGateOutcome(passed=False, signal="confirmation-unmeasurable", detail=detail,
                                           env=True, ran=True, branch=branch_run, baseline=baseline_run,
                                           baseline_note=baseline_note, baseline_source=baseline_source,
                                           confirm=confirm_run))
        log.info(f"🔬 Unit gate confirmation — {confirm_run.describe}; "
                 f"flake: {', '.join(flakes) or '(none)'}; regression: {', '.join(regressions) or '(none)'}")
        if flakes and baseline_source in ("cache", "measured"):
            _unit_cache_record_flakes(archive_path or SIT_ARCHIVE_DIR, ACTIVE_REPO_NAME, base_sha,
                                      test_cmd, flakes)

    if regressions:
        # AC-O6b-01/02: a regression is a named file confirmed still failing in isolation that
        # did not fail at the merge base — that, and only that, produces FAIL(product). The
        # count is carried along as evidence, never as an independent trigger (AC-O6b-05).
        reasons = [f"newly-failing file(s): {', '.join(regressions)}"]
        if worse_count:
            reasons.append(f"{branch_run.failures} failures vs baseline {baseline_run.failures}")
        if flakes:
            reasons.append(f"flaky in isolation, not blocking: {', '.join(flakes)}")
        detail = (f"unit suite REGRESSED against merge-base {base_sha[:7]} — " + "; ".join(reasons)
                  + f" (baseline {baseline_source})")
        log.error(f"⛔ UNIT BASELINE GATE FAILED — {detail}. BLOCKING: branch stays unmerged.")
        return _finish(UnitGateOutcome(passed=False, signal="regression", detail=detail,
                                       ran=True, branch=branch_run, baseline=baseline_run,
                                       baseline_note=baseline_note, baseline_source=baseline_source,
                                       flaky_files=flakes, confirm=confirm_run))

    verdict = ("equal to" if branch_run.failures == baseline_run.failures else "below")
    detail = (f"{branch_run.failures} failures, {verdict} the merge-base baseline of "
              f"{baseline_run.failures} — no new failing file (baseline {baseline_source})")
    if flakes:
        # AC-O6b-01: every newly-failing file confirmed a FLAKE ⇒ PASS regardless of the
        # count delta. Flakes alone never fail the route, but they are still reported, never
        # silently swallowed.
        detail = (f"{branch_run.failures} failures, {verdict} the merge-base baseline of "
                  f"{baseline_run.failures} — newly-failing file(s) confirmed FLAKY in isolation "
                  f"(passed alone, not blocking): {', '.join(flakes)} (baseline {baseline_source})")
    elif worse_count:
        # AC-O6b-03: the count rose with no newly-failing file — logged as an explicit, named
        # observation so the noise stays visible without blocking.
        detail = (f"count rose from {baseline_run.failures} to {branch_run.failures} with no "
                  f"newly-failing file — not blocking (baseline {baseline_source})")
    log.info(f"✅ UNIT BASELINE GATE PASSED — {detail}; baseline {baseline_note}")
    return _finish(UnitGateOutcome(passed=True, ran=True, branch=branch_run, baseline=baseline_run,
                                   baseline_note=baseline_note, baseline_source=baseline_source,
                                   detail=detail, flaky_files=flakes, confirm=confirm_run))


def _unit_done(o: UnitGateOutcome, started: float, repo_path: Path,
               archive_path: Optional[Path]) -> UnitGateOutcome:
    """Stamp the duration and persist the run. AC-O3-06: what the gate collected on BOTH
    sides is written down, in the shape [ORCH-2] established for the SIT gate."""
    o.duration_s = time.time() - started
    # [ORCH-9] AC-O9-03 / §4: the gate reconciles itself. A verdict never quotes a failure
    # count whose own tallies do not sum to the total the runner stated without saying so in
    # the same line — and it says so LOUDLY, because that disagreement means the number and
    # the run it claims to describe have come apart. Pure arithmetic over what was already
    # parsed: nothing is re-run here ([ORCH-2]).
    note = o.tally_note
    if note:
        log.warning(f"⚠️  Unit gate: {note}")
        o.detail = f"{o.detail} | {note}" if o.detail else note
    try:
        _log_unit_outcome(archive_path or SIT_ARCHIVE_DIR, repo_path, o)
    except Exception as e:
        log.warning(f"⚠️  Unit gate: could not persist outcome: {e}")
    return o


def _log_unit_outcome(archive: Path, repo_path: Path, o: UnitGateOutcome):
    """Append the unit-gate outcome to orchestrator-unit-log.json — same archive dir and same
    entry shape as _log_sit_outcome, carrying BOTH sides' counts so "was this branch worse than
    where it forked from, and by how much?" stays answerable historically."""
    archive.mkdir(parents=True, exist_ok=True)
    log_file = archive / "orchestrator-unit-log.json"
    entries = []
    if log_file.exists():
        try:
            entries = json.loads(log_file.read_text())
        except (json.JSONDecodeError, IOError):
            entries = []

    def _side(r: Optional[UnitSuiteRun]) -> Optional[dict]:
        if r is None:
            return None
        return {"ref": r.ref, "exit_code": r.exit_code, "duration_s": round(r.duration_s, 2),
                "runner": r.runner, "test_files_total": r.test_files_total,
                "tests_total": r.tests_total, "tests_passed": r.tests_passed,
                "failures": r.failures, "tests_skipped": r.tests_skipped,   # [ORCH-8]
                "tests_todo": r.tests_todo, "failures_source": r.failures_source,
                "tests_expected_fail": r.tests_expected_fail,           # [ORCH-TALLY-1]
                # [ORCH-9] AC-O9-03: the agreement check, persisted — a later reader can tell
                # whether this entry's number reconciled without re-deriving it.
                "tally_sum": r.tally_sum, "tally_agrees": r.tally_note is None,
                "failing_files": list(r.failing_files),
                "error": r.error}

    entries.append({
        "timestamp": datetime.now().isoformat(),
        "repo": str(repo_path),
        "repo_name": ACTIVE_REPO_NAME,
        "passed": o.passed,
        "signal": o.signal,
        "detail": o.detail,
        "environment": o.env,
        "duration_s": round(o.duration_s, 2),
        "baseline": _side(o.baseline),
        "baseline_note": o.baseline_note,
        "baseline_source": o.baseline_source,   # [ORCH-5] AC-O5-05 / decision 5
        "branch": _side(o.branch),
        "flaky_files": list(o.flaky_files),     # [ORCH-6] AC-O6-06
    })
    log_file.write_text(json.dumps(entries, indent=2))


# ═══════════════════════════════════════════════════════
# PRE-MERGE GATE RUNNER + F-20 CLASSIFIER (S7-CORE-4 [ORCH-1])
# ═══════════════════════════════════════════════════════
def _env_file_keys(path: Optional[Path]) -> set:
    """Key NAMES declared in a dotenv file. Values are discarded at the split and never
    logged (canon §23.9d)."""
    keys = set()
    if not path or not path.is_file():
        return keys
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            k = line.split("=", 1)[0].strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                keys.add(k)
    except OSError:
        pass
    return keys


# [ORCH-11] rule 1 — the failing FILES named in the runner output (`FAIL sit/x.test.ts`), so
# the environment verdict says which files were down, not just how many.
_GATE_FAIL_FILE_RE = re.compile(r"^\s*(?:❯\s+)?FAIL\s+(\S+)", re.MULTILINE)


def _classify_gate_failure(gate: str, output: str, repo_path: Path, exit_code: int,
                           tests_failed: Optional[int] = None,
                           files_failed: Optional[int] = None,
                           isolation: Optional[SitIsolation] = None,
                           clock: Optional[ClockViolation] = None) -> GateVerdict:
    """PDLC F-20: BLOCKED(environment) vs FAIL(product) for a red gate. Only the F-20 tables
    decide. The matched token is quoted (≤80 chars); the gate output is never echoed whole.

    S7-CORE-10 [ORCH-11]: two additions, both decided from THIS function's inputs.
      2. Transport-level refusals (429 / ECONNREFUSED / client OperationOutcomeError) are in
         the signal table, and the matched signal is NAMED in the log — the way [ORCH-8] made
         `failures_source` explicit.
      1. `tests_failed == 0` ⇒ BLOCKED(environment), whatever the output says: a red gate with
         ZERO failed assertions is test files down at SETUP with every executed assertion
         passing — an environment verdict by construction. Both false FAIL(product)s of
         2026-09-15 (RM-I-028; the 19-file 429) had exactly this shape. None is UNKNOWN, not 0,
         and never earns it (§2.4); a run with one failed assertion still falls through to the
         product verdict. The caller that has the tallies passes them; a caller that does not
         gets the pre-[ORCH-11] behaviour unchanged.

    S7-CORE-15 [GATE-SIT-2], reached only when rules 2 and 1 were silent:
      3. A failed assertion that passes alone is the batch's, not the product's — decided from
         this function's inputs, like rules 1 and 2 (`isolation`, the SIT gate's SitIsolation).
         An unreadable isolation measurement ⇒ BLOCKED(environment) `isolation-unmeasurable`;
         any file confirmed failing alone ⇒ FAIL(product); only contaminated files ⇒ PASS
         `batch-contamination`, named. No isolation, or a skipped one ⇒ the product fall-through.

    S7-CORE-16 [GATE-CLOCK-1], the last clause before the product verdict:
      4. A red whose gate timed a leg across a clock jump, a suspend or a > 5× outlier (`clock`,
         the gate's first implausible leg) ⇒ BLOCKED(environment) `clock-implausible`: the
         measurement is not evidence about the product. It never touches rules 1-3's own
         BLOCKED or PASS results — a sleep can manufacture failures, it cannot manufacture passes."""
    text = _ANSI_RE.sub("", output or "")
    for sid, rx, desc in _ENV_BLOCK_SIGNALS_RE:
        m = rx.search(text)
        if m:
            log.info(f"🔎 F-20 {gate} gate: signal '{sid}' matched — {desc}")
            return GateVerdict(GateOutcome.BLOCKED_ENV, gate, sid, f"{desc}; matched '{m.group(0)[:80]}'")
    _, env_path = _gate_env_file(repo_path)
    keys = _env_file_keys(env_path)
    for rx in _ENV_VAR_MISSING_RE:
        for m in rx.finditer(text):
            var = m.group(1)
            if var in keys:
                log.info(f"🔎 F-20 {gate} gate: signal 'env-var-unsourced' matched — {var}")
                return GateVerdict(GateOutcome.BLOCKED_ENV, gate, "env-var-unsourced",
                                   f"gate requires {var}; it is a key in {env_path.name} but did not reach the gate shell")
    if tests_failed == 0:
        down = sorted({_norm_test_path(f) for f in _GATE_FAIL_FILE_RE.findall(text)})
        which = f": {', '.join(down)}" if down else ""
        n = "?" if files_failed is None else files_failed
        log.info(f"🔎 F-20 {gate} gate: signal 'no-failed-assertions' matched — 0 failed assertions, "
                 f"{n} file(s) down at setup{which}")
        return GateVerdict(GateOutcome.BLOCKED_ENV, gate, "no-failed-assertions",
                           f"exit {exit_code} with 0 failed assertions and {n} file(s) down at setup{which} "
                           f"— environment by construction [ORCH-11]")
    seen = "" if tests_failed is None else f" ({tests_failed} failed assertions)"
    product = f"no F-20 environment signal in gate output{seen} — product verdict stands"
    if isolation is not None and not isolation.skipped:
        if isolation.error:
            log.info(f"🔎 F-20 {gate} gate: signal 'isolation-unmeasurable' matched — {isolation.detail}")
            return GateVerdict(GateOutcome.BLOCKED_ENV, gate, "isolation-unmeasurable", isolation.detail)
        if isolation.confirmed:
            also = (f"; contaminated (passed alone, not counted): {', '.join(isolation.contaminated)}"
                    if isolation.contaminated else "")
            product = (f"no F-20 environment signal in gate output{seen}; confirmed failing alone: "
                       f"{', '.join(isolation.confirmed)}{also} — product verdict stands")
        elif isolation.contaminated:
            why = "; ".join(
                f"{f} failed in batch {isolation.batch_of.get(f, '?')}/{isolation.batches or '?'} beside "
                f"{', '.join(isolation.neighbours.get(f, ())) or 'no other file'} — passed alone "
                f"({isolation.alone.get(f, '?')})" for f in isolation.contaminated) + "; no product failure"
            log.info(f"🔎 F-20 {gate} gate: signal 'batch-contamination' — {why}")
            return GateVerdict(GateOutcome.PASS, gate, "batch-contamination", why)
    if clock is not None:
        log.info(f"🔎 F-20 {gate} gate: signal 'clock-implausible' matched — {clock}")
        return GateVerdict(GateOutcome.BLOCKED_ENV, gate, "clock-implausible",
                           f"{clock} — a red measured on that clock is not a product verdict")
    return GateVerdict(GateOutcome.FAIL_PRODUCT, gate, f"exit {exit_code}", product)


def sit_verdict_violations(so: SitOutcome, v: GateVerdict) -> list[str]:
    """[GATE-SIT-2] EMPTY WHEN CLEAN. Each string names one way (so, v) contradicts §2:
    no FAIL(product) names a failing file that was not re-run alone and confirmed failing
    alone; no file that passed alone is counted against the product; and a red gate that
    D-S7CORE10-02 already calls environment is never re-run.

    Scope: a batched (`so.batches`), red (`so.passed is False`) run with no machinery error
    (`so.error is None`) and a stated failed count (`so.tests_failed` not None). Everything
    else — unbatched runs, batch-incomplete / sit-list-failed / zero-collection /
    timeout-advisory / skipped, UNKNOWN tallies (§2.4) — returns [] from every clause.
    A SKIPPED isolation (the cap: more failing files than a batch holds) owes nothing:
    V1 and V2 exclude it, and its FAIL(product) is today's rule, unchanged."""
    if so.batches is None or so.passed is not False or so.error is not None or so.tests_failed is None:
        return []
    out = []
    iso = so.isolation
    signal = _sit_env_signal(so.output)
    product, passed = v.outcome is GateOutcome.FAIL_PRODUCT, v.outcome is GateOutcome.PASS
    if product and iso is not None and not iso.skipped and not iso.confirmed:
        out.append(f"V1: FAIL(product) with no file confirmed failing alone (isolation: {iso.as_log()})")
    if (product and iso is None and so.tests_failed >= 1 and signal is None
            and _sit_failing_files(so.output)):
        out.append(f"V2: FAIL(product) over failing file(s) {', '.join(_sit_failing_files(so.output))} "
                   f"that were never re-run alone")
    if passed and (iso is None or iso.error or iso.skipped or iso.confirmed or not iso.contaminated):
        out.append("V3: PASS over a red batched run without every failing file passing alone")
    if iso is not None and (so.tests_failed == 0 or signal is not None):
        out.append(f"V4: isolation ran where D-S7CORE10-02 had decided "
                   f"({'0 failed assertions' if so.tests_failed == 0 else f'signal {signal!r}'}) — a re-run, not a measurement")
    if (v.outcome is GateOutcome.BLOCKED_ENV and v.signal == "isolation-unmeasurable"
            and (iso is None or iso.error is None)):
        out.append("V5: BLOCKED(environment) isolation-unmeasurable without a failed measurement behind it")
    return out


def run_pre_merge_gates(repo_path: Path, branch_name: Optional[str] = None) -> GateVerdict:
    """Run the repo's PRE_MERGE_GATES on the route branch checked out at repo_path, BEFORE any
    merge, then the S7-CORE-8 [ORCH-3] unit baseline gate. Returns a three-way GateVerdict:
    PASS / BLOCKED(environment) / FAIL(product). Callers merge iff outcome is PASS.
    The operator escapes (DISABLE_BUILD_GATE, DISABLE_SIT_BLOCKING, --skip-sit, and
    [ORCH-3]'s DISABLE_UNIT_GATE) are honoured inside the gate functions, unchanged.

    Order is build → SIT → unit: cheapest signal first, the slowest suite last and only if
    the others were green."""
    policy = PRE_MERGE_GATES.get(ACTIVE_REPO_NAME)
    where = f" on {branch_name}" if branch_name else ""
    gates = tuple(policy["gates"]) if policy and policy.get("gates") else ()
    if not gates:
        log.info(f"🚪 Pre-merge gate{where}: repo '{ACTIVE_REPO_NAME}' is UNGATED by PRE_MERGE_GATES (explicit) — merge proceeds")

    env_name, env_path = _gate_env_file(repo_path)
    if env_name:
        if env_path.is_file():
            log.info(f"🔐 Pre-merge gate{where}: {env_name} will be sourced from {repo_path} into the gate shell (values not logged)")
        else:
            v = GateVerdict(GateOutcome.BLOCKED_ENV, "env", "env-file-missing", f"{env_path} not found")
            log.error(f"⛔ Pre-merge gate{where}: {v.label}")
            return v

    sit_collection: Optional[str] = None  # [ORCH-2]
    for gate in gates:
        if gate == "build":
            bg = run_build_gate(repo_path)
            if not bg.passed:
                v = _classify_gate_failure("build", bg.output or bg.error or "", repo_path, bg.exit_code,
                                           clock=bg.clock)
                died = _gate_fast_death(bg.exit_code, bg.duration_s, bg.stderr_head, elide=env_name)
                if v.outcome is GateOutcome.BLOCKED_ENV and died:      # [ORCH-LANE-1] O5: the message only
                    v.detail = f"{v.detail}; the build command {died}"
                log.error(f"⛔ Pre-merge gate{where}: {v.label}")
                return v
        elif gate == "sit":
            so = run_sit_post_merge(repo_path)
            sit_collection = so.collection
            if not so.passed:
                if SIT_BLOCKING:
                    if so.error == "zero-collection":
                        # [ORCH-2] §4.5: exit 0 over an empty collection — nothing was tested.
                        # Environment (F-20 / §23.9d handling), never product, never a pass.
                        v = GateVerdict(GateOutcome.BLOCKED_ENV, "sit", "zero-collection",
                                        f"exit 0 over an empty collection ({so.collection}) — nothing was tested",
                                        collection=sit_collection)
                    elif so.error in SIT_GATE_ENV_ERRORS:
                        # [SIT-RATE-1] the gate's own batching machinery could not produce a whole-suite
                        # result (enumeration failed / batches do not sum). Not a product verdict.
                        v = GateVerdict(GateOutcome.BLOCKED_ENV, "sit", so.error, so.detail,
                                        collection=sit_collection)
                    else:
                        # [ORCH-11] the tallies travel with the output: rule 1 is decided here.
                        v = _classify_gate_failure("sit", so.output or so.error or "", repo_path, so.exit_code,
                                                   tests_failed=so.tests_failed, files_failed=so.files_failed,
                                                   isolation=so.isolation, clock=so.clock)
                        v.collection = sit_collection
                    # [GATE-SIT-2] the invariant is an oracle, not a fourth rule: it never changes v.
                    for msg in sit_verdict_violations(so, v):
                        log.error(f"⛔ GATE-SIT-2 invariant: {msg}")
                    if v.outcome is GateOutcome.PASS:
                        log.info(f"✅ Pre-merge gate{where}: SIT green after isolation — {v.label}")
                        continue
                    log.error(f"⛔ Pre-merge gate{where}: {v.label}")
                    return v
                log.warning("⚠️  SIT red but DISABLE_SIT_BLOCKING is set — advisory (pre-existing operator escape)")
        else:
            log.warning(f"⚠️  Unknown gate '{gate}' in PRE_MERGE_GATES — ignored")

    # S7-CORE-8 [ORCH-3]: the unit suite, LAST (§2.6 — cheapest signal first; this is the
    # slowest gate and only runs once build and SIT are green). Its eligibility is NOT read
    # from PRE_MERGE_GATES: §2.3 derives it from the repo's `test_cmd` in config/repos.yaml,
    # so a repo that declares a command is gated even when it has no entry above, and a repo
    # that declares none is reported "ungated by policy" and does not block.
    uo = run_unit_gate(repo_path, branch_name)
    unit_collection = uo.collection
    if not uo.passed:
        if uo.env:
            v = GateVerdict(GateOutcome.BLOCKED_ENV, "unit", uo.signal, uo.detail,
                            collection=sit_collection, unit_collection=unit_collection)
        else:
            # A regression is a product verdict unless the F-20 tables see an environment
            # signal in the suite output — same classifier the build and SIT gates use.
            v = _classify_gate_failure("unit", (uo.branch.output if uo.branch else "") or uo.detail or "",
                                       repo_path, uo.branch.exit_code if uo.branch else -1, clock=uo.clock)
            if v.outcome is GateOutcome.FAIL_PRODUCT:
                v.signal, v.detail = uo.signal, uo.detail
            elif v.signal == "clock-implausible":
                v.detail = f"{v.detail} (the red: {uo.detail})"
            v.collection, v.unit_collection = sit_collection, unit_collection
        log.error(f"⛔ Pre-merge gate{where}: {v.label}")
        return v

    ran = list(gates) + ([] if uo.signal in ("ungated", "disabled", "not-applicable") else ["unit"])
    reason = f"{'+'.join(ran)} green{where}" if ran else f"{ACTIVE_REPO_NAME}: ungated by policy"
    if uo.signal == "ungated" and ran:
        reason += f" (unit: {uo.detail})"
    v = GateVerdict(GateOutcome.PASS, None, None, reason,
                    collection=sit_collection, unit_collection=unit_collection)
    log.info(f"✅ Pre-merge gate{where}: {v.label}")
    return v


def _log_sit_outcome(archive: Path, repo_path: Path, passed: bool, exit_code: int,
                     duration: float, report_path: Optional[str], error: Optional[str] = None,
                     error_excerpt: Optional[str] = None,
                     test_files_total: Optional[int] = None, test_files_passed: Optional[int] = None,
                     tests_total: Optional[int] = None, tests_passed: Optional[int] = None,
                     tests_failed: Optional[int] = None, batches: Optional[int] = None,
                     isolation: Optional[dict] = None):
    """Append SIT outcome to orchestrator-sit-log.json. [ORCH-2] carries the four collection
    counts (null when the summary did not parse) so "was the gate ever thin?" is answerable
    historically. Old-shape entries without them still load.
    [GATE-SIT-2] `isolation` (SitIsolation.as_log()) is written only when the leg was owed;
    entries without the key are runs where it was not."""
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
        "test_files_total": test_files_total,
        "test_files_passed": test_files_passed,
        "tests_total": tests_total,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,  # [ORCH-11] the tally the verdict turned on; null = not stated
        "batches": batches,            # [SIT-RATE-1] null = one unbatched run
    }
    if error_excerpt is not None:
        entry["error_excerpt"] = error_excerpt
    if isolation is not None:
        entry["isolation"] = isolation
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
# ═══════════════════════════════════════════════════════
# [ORCH-HANDBACK-GUARD-1] A ROUTE THAT SAYS IT IS UNFINISHED DOES NOT MERGE
# ═══════════════════════════════════════════════════════
# The executor sometimes starts a long verification in the background and ends its turn:
# `claude` exits 0 and the route went on to commit, gate and merge a coherent tree missing its
# last step. 27 of 829 fire_toni logs up to route 54 advertise outstanding work; at least 10
# merged. The predicate and its rules live in canon_assert / config/handback-guard.json.
@dataclass(frozen=True)
class HandbackHold:
    """Why a route's merge is withheld before any gate runs."""
    status: Status          # INCOMPLETE (the executor said so) | BLOCKED (the guard could not judge)
    verdict: str            # INCOMPLETE_VERDICT | GateOutcome.BLOCKED_ENV.value
    label: str              # "<rule> at line <n>" | the unjudgeable reason
    error: str              # the Result.error line; for INCOMPLETE it quotes the matched line
    source: str = "HANDBACK GUARD"   # the git-note prefix; "EXECUTOR EXIT" for _executor_exit_hold


def _handback_hold(out_log: str) -> Optional[HandbackHold]:
    """Resolve the rules once and judge the route's fire_toni log once. None ⇒ nothing outstanding
    is advertised and the route goes on to its gates as before. Unjudgeable (rules unresolved,
    log unreadable, no fire_toni header) ⇒ BLOCKED(environment): fail-closed, never INCOMPLETE."""
    rules = load_outstanding_work_rules(HANDBACK_GUARD_CONFIG)
    if rules is None:
        reason = "handback-guard-unconfigured"
    else:
        found = check_handback_invariants(Path(out_log), rules)
        if not found:
            # [ORCH-HANDBACK-SILENT-PASS] P-SAY: a control that passes says so — absence then means "not engaged".
            log.info(f"🛡 handback-guard: CLEAN — no outstanding work advertised ({len(rules)} rules, {out_log})")
            return None
        if found[0].reason == "outstanding-work":
            for v in found:
                log.error(f"⛔ {INCOMPLETE_VERDICT}: {v.rule} at line {v.line_no}: \"{v.line}\"")
            v = found[0]
            log.error(f"🛡 handback-guard: HOLD — {INCOMPLETE_VERDICT}: {v.rule} at line {v.line_no} "
                      f"({len(found)} rule(s) matched, {out_log})")
            return HandbackHold(
                Status.INCOMPLETE, INCOMPLETE_VERDICT, f"{v.rule} at line {v.line_no}",
                f"{INCOMPLETE_VERDICT} — executor output advertises outstanding work: "
                f"{v.rule} at line {v.line_no}: \"{v.line}\"")
        reason = found[0].reason
    log.error(f"⛔ {GateOutcome.BLOCKED_ENV.value} — handback guard: {reason} ({out_log})")
    log.error(f"🛡 handback-guard: BLOCKED — {reason} ({out_log})")
    return HandbackHold(Status.BLOCKED, GateOutcome.BLOCKED_ENV.value, reason,
                        f"{GateOutcome.BLOCKED_ENV.value} — handback guard: {reason}")


def _executor_exit_hold(ec: int, branch: str) -> Optional[HandbackHold]:
    """[ORCH-TIMEOUT-HOLD-1] P-MERGE: merged(r) ⇒ ec(r) == 0 ∧ handback(r) CLEAN ∧ gates(r) PASS. None
    ⇒ exit 0, and the handback guard judges next. An executor that did not exit 0 but left work on
    the tree is INCOMPLETE — exit -1 (fire_toni's timeout kill) ⇒ INCOMPLETE(timeout), any other ⇒
    INCOMPLETE(executor-error) — and is held exactly like a handback hold: the work is committed on
    its branch, no gate runs, nothing merges. Salvage stays possible and is an operator act; the
    error names the command that starts it. One `🛡 executor-exit:` line either way (P-SAY)."""
    if ec == 0:
        log.info("🛡 executor-exit: CLEAN — exit 0")
        return None
    verdict = INCOMPLETE_TIMEOUT_VERDICT if ec == -1 else INCOMPLETE_EXECUTOR_ERROR_VERDICT
    why = f"killed at the {TONI_TIMEOUT // 60}m route timeout" if ec == -1 else "the executor did not exit 0"
    error = (f"{verdict} — executor exit {ec} ({why}) with work on the tree; no gate run, nothing "
             f"merged. Salvage is an operator act — inspect: cd {PROJECT_ROOT} && git log --oneline "
             f"{MERGE_TARGET}..{branch}")
    log.error(f"⛔ {error}")
    log.error(f"🛡 executor-exit: HOLD — {verdict}: exit {ec} with work on {branch}")
    return HandbackHold(Status.INCOMPLETE, verdict, f"exit {ec}", error, source="EXECUTOR EXIT")


def run_batch(batch_file: Path, worktree: Optional[Path]=None) -> Result:
    # HOOK-1 / D-S7CORE4-02 — assertions checked at the moment of action.
    if not PREFIRE_BYPASS and not prefire.report(batch_file):
        log.error('Pre-fire assertions FAILED - not firing %s' % batch_file.name)
        _now = datetime.now().isoformat()
        return Result(batch_file=batch_file.name, status=Status.FAILED,
                      started=_now, finished=_now, duration_s=0.0,
                      exit_code=2, briefs=0,
                      error='pre-fire assertions failed (A1/A2/A8) — HOOK-1')
    meta_wt = None
    meta_branch = None
    is_self_mod = IS_META_FIRE and (PROJECT_ROOT.resolve() == ORCH_DIR)

    if IS_META_FIRE and worktree is None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        meta_wt = Path(f"/tmp/orch-fire-{ts}")
        meta_branch = f"{BRANCH_PREFIX}-{batch_file.stem}"
        stale_err = None
        try:
            if meta_wt.exists():
                subprocess.run(f"cd {PROJECT_ROOT} && git worktree remove {meta_wt} --force",
                    shell=True, capture_output=True)
            # ORCH-STALEBASE-1: never adopt an existing route branch — retire it, cut fresh
            # from the merge target (the self-mod merge is --ff-only and needs that base).
            try:
                retire_stale_branch(PROJECT_ROOT, meta_branch, MERGE_TARGET)
            except Exception as e:
                stale_err = str(e)
            if stale_err is None:
                r = subprocess.run(
                    f"cd {PROJECT_ROOT} && git worktree add {meta_wt} -b {meta_branch} {MERGE_TARGET}",
                    shell=True, capture_output=True, text=True)
                if r.returncode == 0:
                    log.info(f"Meta-fire worktree: {meta_wt} (branch: {meta_branch})")
                    worktree = meta_wt
                    v = check_branch_freshness_invariants(
                        QueueRepo(ACTIVE_REPO_NAME, PROJECT_ROOT, MERGE_TARGET, BRANCH_PREFIX),
                        [batch_file.name])
                    if v:
                        stale_err = str(v[0])
                        cleanup_worktree(meta_wt)
                else:
                    log.error(f"Meta-fire worktree failed: {r.stderr}")
        except Exception as e:
            log.error(f"Meta-fire worktree error: {e}")
        if stale_err is not None:
            return _stale_base_result(batch_file, datetime.now(), 0, stale_err)

    # [ORCH-CONTROL-SCOPE-1] C4: a `worktree_mode: parallel` repo's route runs in its own worktree. One
    # that cannot be made is not fired — never in the main checkout instead.
    route_wt = None
    if WORKTREE_MODE == "parallel" and worktree is None and not IS_META_FIRE:
        route_wt, why = _create_route_worktree(batch_file)
        if route_wt is None:
            log.error(f"⛔ ROUTE WORKTREE — {why} — not firing.")
            _now = datetime.now().isoformat()
            return Result(batch_file=batch_file.name, status=Status.FAILED, started=_now, finished=_now,
                          duration_s=0.0, exit_code=2, briefs=0, error=f"route-worktree: {why}")

    proj = worktree or route_wt or PROJECT_ROOT
    started = datetime.now()
    briefs_preview = parse_batch(batch_file)
    write_running(batch_file, len(briefs_preview))
    _write_running_marker(
        batch_file, ACTIVE_REPO_NAME, PROJECT_ROOT,
        meta_branch or f"{BRANCH_PREFIX}-{batch_file.stem}",
        meta_wt, is_self_mod, route_worktree=route_wt,
    )
    result = None
    try:
        result = _run_batch_inner(batch_file, proj, started, worktree,
                                  **({"route_wt": route_wt} if route_wt is not None else {}))
    finally:
        clear_running()
        # [ORCH-4]: release THIS repo's lock. Another repo's concurrent fire keeps its own.
        _clear_running_marker(ACTIVE_REPO_NAME)
        if meta_wt:
            if is_self_mod and meta_branch:
                if result is not None and result.exit_code == 0 and result.status == Status.PASSED:
                    # [ORCH-1] gate verdict was rendered in _run_batch_inner on the worktree checkout
                    merged = _self_mod_auto_merge(ORCH_DIR, meta_branch, gate_outcome=result.gate_outcome,
                                                  batch_file=batch_file)
                    if merged:
                        cleanup_worktree(meta_wt)
                elif result is not None and result.status == Status.INCOMPLETE:
                    # [ORCH-HANDBACK-GUARD-1] no gate ran, so gate_outcome is None: name the verdict here
                    # rather than fall through to the generic "Self-mod fire failed".
                    log.error(
                        f"⛔ Self-mod merge WITHHELD — {result.error}. "
                        f"Branch preserved: {meta_branch}. Worktree preserved: {meta_wt}. "
                        f"Re-fire, or after review: cd {ORCH_DIR} && git merge --ff-only {meta_branch}"
                    )
                elif result is not None and result.gate_outcome not in (None, GateOutcome.PASS.value):
                    log.error(
                        f"⛔ Self-mod merge WITHHELD — {result.gate_outcome}: {result.error}. "
                        f"Branch preserved: {meta_branch}. Worktree preserved: {meta_wt}. "
                        f"After review: cd {ORCH_DIR} && git merge --ff-only {meta_branch}"
                    )
                else:
                    log.warning(
                        f"Self-mod fire failed; branch preserved: {meta_branch}. "
                        f"Inspect {meta_wt} for state."
                    )
            else:
                cleanup_worktree(meta_wt)
        if route_wt is not None:
            _finish_route_worktree(route_wt, result)
    return result

def _run_batch_inner(batch_file: Path, proj: Path, started: datetime, worktree=None,
                     route_wt: Optional[Path] = None) -> Result:
    # [ORCH-CONTROL-SCOPE-1] C4: `route_wt` is set when proj IS a route worktree (run_batch made it). The
    # route lane runs unchanged in it — branch cut, executor, commit, gate — except that it never checks
    # out MERGE_TARGET, and the merge is _land_from_route_worktree.
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
    # ORCH-STALEBASE-1: an existing route branch is never adopted. It is retired (renamed) and
    # the route branch is cut afresh, explicitly from MERGE_TARGET, then the freshness
    # predicate is asserted BEFORE capture_handoff — a violation does not fire Toni.
    branch_name = None
    if worktree is None:
        branch_name = f"{BRANCH_PREFIX}-{batch_file.stem}"
        stale_err = None
        retired = None
        try:
            retired = retire_stale_branch(proj, branch_name, MERGE_TARGET)
        except Exception as e:
            stale_err = str(e)
        if stale_err is None:
            try:
                r = subprocess.run(
                    f"git checkout -b {branch_name} {MERGE_TARGET}",
                    shell=True, capture_output=True, text=True, cwd=str(proj)
                )
                if r.returncode == 0:
                    tip = _git_read(f"git rev-parse {MERGE_TARGET}", proj)
                    log.info(f"🌿 Branch: {branch_name} (from {MERGE_TARGET} @ {tip[:7]})")
                    v = check_branch_freshness_invariants(
                        QueueRepo(ACTIVE_REPO_NAME, proj, MERGE_TARGET, BRANCH_PREFIX),
                        [batch_file.name])
                    if v:
                        stale_err = str(v[0])
                        subprocess.run(f"git checkout {MERGE_TARGET}", shell=True,
                                       capture_output=True, cwd=str(proj))
                elif retired is not None or route_wt is not None:
                    stale_err = (f"could not cut {branch_name} from {MERGE_TARGET}"
                                 + (f" after retiring {retired}" if retired else f" in the route worktree {proj}")
                                 + f": {r.stderr.strip()}")
                else:
                    log.warning(f"⚠️ Could not create branch: {r.stderr.strip()}. Running on current branch.")
                    branch_name = None
            except Exception as e:
                if retired is not None or route_wt is not None:
                    stale_err = (f"could not cut {branch_name}"
                                 + (f" after retiring {retired}" if retired else f" in the route worktree {proj}")
                                 + f": {e}")
                else:
                    log.warning(f"⚠️ Branch creation failed: {e}. Running on current branch.")
                    branch_name = None
        if stale_err is not None:
            return _stale_base_result(batch_file, started, len(briefs), stale_err)

    mig_before = get_migrations()
    # [ORCH-10] S1: record the route's expected state at the hand-off point — the branch
    # name, its SHA, and the repo's HEAD ref — at the moment control passes to the executor.
    # Meta-fire lane excluded on purpose: S5 is report-only for this route.
    handoff = capture_handoff(proj, branch_name) if worktree is None else None
    ec, out_log = fire_toni(target, proj)
    finished = datetime.now()
    dur = (finished - started).total_seconds()
    # [ORCH-10] S2: re-check all three BEFORE the no-changes decision is made. `has_changes`
    # below is computed from MERGE_TARGET..HEAD, which is meaningless once HEAD has moved —
    # that is precisely how the incident's commit-on-main read as "produced no changes".
    tamper = check_route_integrity(proj, handoff) if handoff is not None else None
    # S6S49 fix: claude-code 2.1.123 returns a NON-ZERO exit even on a fully
    # successful run (thinking-block teardown regression). Trusting ec alone
    # made the orchestrator discard good work (006/007 produced correct,
    # compiling code yet were logged FAILED, leaving edits uncommitted).
    # Real success signal = Toni produced work (commits ahead of target OR
    # staged/unstaged changes in the tree). The post-merge BUILD GATE remains
    # the quality arbiter, so this cannot merge broken code — it only stops a
    # bad exit code from throwing away good code. ec is still recorded.
    # S7-CORE-16 [ORCH-TIMEOUT-HOLD-1]: the work is still never thrown away, but it no longer merges:
    # a non-zero exit with work on the tree is INCOMPLETE (_executor_exit_hold) — committed on its
    # branch, never gated. The meta-fire worktree is a route branch too and is measured the same way.
    if tamper is not None:
        # [ORCH-10] S2: the work-produced signals all read the wrong ref now. Do not compute them.
        _produced_work = False
    elif (worktree is None and branch_name) or (worktree is not None and IS_META_FIRE):
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
    # [ORCH-HANDBACK-GUARD-1] T2.1: judge the executor's closing words once, here. A tampered
    # route is not judged — TAMPERED already stops it. A hold keeps `status` PASSED until its
    # lane below has committed the work onto the route branch, then replaces the gate.
    # [ORCH-TIMEOUT-HOLD-1] a non-zero exit is held on the exit code alone: the closing words of an
    # executor that was killed, or that failed, are not asked (the guard is not engaged).
    hold = None
    if tamper is None and status == Status.PASSED:
        hold = (_executor_exit_hold(ec, branch_name or f"{BRANCH_PREFIX}-{batch_file.stem}")
                or _handback_hold(out_log))
    if tamper is not None:
        # [ORCH-10] S2: not `passed`, and not `failed(product)` either — the run was handed a
        # repo it no longer recognises, so it has no opinion about the product at all.
        status = Status.TAMPERED
        for line in tamper.log_lines():
            log.error(line)
        try:
            _log_tamper_outcome(SIT_ARCHIVE_DIR, proj, tamper)
        except Exception as e:
            log.warning(f"⚠️  {TAMPER_VERDICT}: could not persist outcome: {e}")
    mig_after = get_migrations()
    new_mig = sorted(mig_after - mig_before)
    if new_mig:
        log.warning(f"⚠️  NEW MIGRATIONS — apply manually:")
        for m in new_mig:
            log.warning(f"  npx supabase db query --linked -f supabase/migrations/{m}")
    pw_ok, pw_cnt = (None, 0)
    # [ORCH-10] S2: a tampered run runs no gate — Playwright included. Its result would
    # describe a tree the route does not own, and a red one would overwrite the verdict.
    if RUN_PLAYWRIGHT and ec == 0 and worktree is None and tamper is None and hold is None:
        pw_ok, pw_cnt = run_playwright()
        if not pw_ok: status = Status.FAILED

    # Auto-commit + merge back to main (D-148)
    no_change_run = False
    gate_outcome: Optional[str] = None   # [ORCH-1] PASS | BLOCKED(environment) | FAIL(product) | None (gate not run)
    gate_error: Optional[str] = None     # [ORCH-1] human verdict line (never a secret value)
    gate_collection: Optional[str] = None  # [ORCH-2] "7 files/18 tests, 6.6s" when the SIT summary parsed
    unit_collection: Optional[str] = None  # [ORCH-3] both sides of the unit baseline when that gate ran
    route_tip: Optional[str] = None      # [ORCH-CONFLICT-1] route branch tip as the merge was attempted
    if tamper is not None:
        # [ORCH-10] S2/S3: no gate, no commit, no merge, no checkout, no branch delete.
        # Detect and report only — the ordinary path below both gates AND moves refs
        # (`git checkout MERGE_TARGET`, `git branch -D`), and a wrong automatic move on a
        # repo somebody else is standing in is worse than a loud stop. AC-O10-04 asserts
        # that every ref is byte-identical after a tampered run.
        gate_error = tamper.label
        log.error(f"⛔ {TAMPER_VERDICT} — no gate run, nothing merged, no ref touched. "
                  f"Branch preserved: {branch_name or '(none)'}.")
    elif branch_name and worktree is None:
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

                    # S7-CORE-4 [ORCH-1]: GATE-THEN-MERGE. Gates run HERE, on the route branch
                    # (still checked out at proj), BEFORE `git merge`. Red gate ⇒ no merge,
                    # MERGE_TARGET tip untouched, branch preserved for review.
                    # (2026-09-09: merge-then-gate let a red sit:gate land on main.)
                    # Gate set is per-repo via PRE_MERGE_GATES (clinical-mp: build → SIT, S6S47).
                    # [ORCH-HANDBACK-GUARD-1] T2.3: a held route is committed above (the failed-batch
                    # branch below would check out MERGE_TARGET WITHOUT committing, dragging the work
                    # into the target's checkout), then gets no gate and no merge. Its status is set
                    # after the lanes, from the hold.
                    verdict = None
                    if hold is None:
                        verdict = run_pre_merge_gates(proj, branch_name)
                        gate_outcome = verdict.outcome.value
                        gate_collection = verdict.collection
                        unit_collection = verdict.unit_collection
                    if verdict is None:
                        subprocess.run(
                            f'git notes add -m "{hold.source}: {hold.verdict} — {hold.label}"',
                            shell=True, capture_output=True, cwd=str(proj)
                        )
                        _leave_route_branch(proj, route_wt)
                        log.error(
                            f"⛔ {hold.verdict} — {MERGE_TARGET} NOT merged, no gate run. Branch preserved: "
                            f"{branch_name}. {hold.error}"
                        )
                    elif verdict.outcome is not GateOutcome.PASS:
                        gate_error = verdict.label
                        subprocess.run(
                            f'git notes add -m "PRE-MERGE GATE: {gate_outcome} — {verdict.gate}: {verdict.signal}"',
                            shell=True, capture_output=True, cwd=str(proj)
                        )
                        status = Status.BLOCKED if verdict.outcome is GateOutcome.BLOCKED_ENV else Status.FAILED
                        _leave_route_branch(proj, route_wt)
                        log.error(
                            f"⛔ {gate_outcome} — {MERGE_TARGET} NOT merged. Branch preserved: {branch_name}. "
                            f"Inspect: cd {proj} && git log --oneline {MERGE_TARGET}..{branch_name} "
                            f"&& git diff {MERGE_TARGET}...{branch_name}"
                        )
                    elif route_wt is not None:
                        # [ORCH-CONTROL-SCOPE-1] C4: green gate only, merged FROM the route worktree.
                        route_tip = _git_read("git rev-parse HEAD", proj) or None
                        unlanded = _land_from_route_worktree(proj, branch_name, toni_commits)
                        if unlanded is None:
                            retire_batch_file(batch_file)   # QUEUE-RETIRE-1, as below
                            subprocess.run(f"git branch -d {branch_name}", shell=True, capture_output=True, cwd=str(proj))
                        else:
                            status = Status.FAILED
                            gate_error = f"{unlanded}; gate was {gate_outcome}"
                    else:
                        # Merge back to merge target — green gate only
                        # [ORCH-CONFLICT-1] the route branch is still checked out: its tip is the
                        # evidence the landed invariant checks, since a good merge deletes the ref.
                        route_tip = subprocess.run(
                            "git rev-parse HEAD",
                            shell=True, capture_output=True, text=True, cwd=str(proj)
                        ).stdout.strip() or None
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
                                # QUEUE-RETIRE-1 / D-S7CORE14-02: retire the originating brief
                                # HERE, as part of the merge's own completion — first thing
                                # after the merge is known good, before the branch is deleted
                                # and long before this process returns to the scheduler. No-op
                                # unless the batch file is sitting in queue/.
                                retire_batch_file(batch_file)
                                # Clean up feature branch
                                subprocess.run(f"git branch -d {branch_name}", shell=True, capture_output=True, cwd=str(proj))
                        else:
                            # [ORCH-CONFLICT-1] a merge that did not land is never `passed`. Abort it
                            # so MERGE_TARGET is left at its pre-merge tip with a clean tree; keep
                            # the branch (and the brief) for manual resolution.
                            log.error(f"⚠️ Merge conflict on {branch_name} — MANUAL RESOLUTION NEEDED")
                            log.error(f"   {r.stdout.strip()}")
                            log.error(f"   {r.stderr.strip()}")
                            unmerged = subprocess.run(
                                "git diff --name-only --diff-filter=U",
                                shell=True, capture_output=True, text=True, cwd=str(proj)
                            ).stdout.split()
                            a = subprocess.run("git merge --abort", shell=True, capture_output=True,
                                               text=True, cwd=str(proj))
                            if a.returncode != 0:
                                log.error(f"❌ git merge --abort failed on {MERGE_TARGET}: {a.stderr.strip()}")
                            status = Status.FAILED
                            gate_error = (f"{MERGE_CONFLICT_VERDICT} — {branch_name} → {MERGE_TARGET} "
                                          f"({', '.join(unmerged)}); gate was {gate_outcome}")
                else:
                    log.warning(
                        "⚠️ Toni produced no changes — skipping commit "
                        "(usually means idempotent re-fire or halt-and-report)."
                    )
                    no_change_run = True
                    _leave_route_branch(proj, route_wt, detach=True)
                    subprocess.run(f"git branch -D {branch_name}", shell=True, capture_output=True, cwd=str(proj))
                    if hold is not None:
                        # [ORCH-HANDBACK-GUARD-1] nothing to merge, but still not `passed` (set below).
                        log.error(f"⛔ {hold.verdict} — produced no changes and said it had not finished. "
                                  f"{hold.error}")
            else:
                # Failed batch — switch back to merge target, leave branch for inspection
                _leave_route_branch(proj, route_wt)
                log.warning(f"⚠️ Batch failed — branch {branch_name} left for inspection")
        except Exception as e:
            log.warning(f"⚠️ Git automation error: {e}")
            # Ensure we're back on merge target
            _leave_route_branch(proj, route_wt)
    elif worktree is not None and IS_META_FIRE and status == Status.PASSED:
        # S7-CORE-4 [ORCH-1] meta-fire lane: the route branch is the worktree checkout at
        # `proj`. Gate it HERE so the Result carries the verdict BEFORE run_batch decides
        # whether to call _self_mod_auto_merge (--ff-only). Red ⇒ run_batch withholds the merge.
        meta_branch = f"{BRANCH_PREFIX}-{batch_file.stem}"
        if hold is not None:
            # [ORCH-HANDBACK-GUARD-1] T2.4: no gate; run_batch merges only `passed` (set below).
            log.error(f"⛔ {hold.verdict} — no gate run, self-mod merge withheld. "
                      f"Branch preserved: {meta_branch}. {hold.error}")
        else:
            try:
                verdict = run_pre_merge_gates(proj, meta_branch)
            except Exception as e:
                verdict = _classify_gate_failure("build", str(e), proj, -1)
                log.error(f"⛔ Pre-merge gate raised on {meta_branch}: {e} → {verdict.label}")
            gate_outcome = verdict.outcome.value
            gate_collection = verdict.collection
            unit_collection = verdict.unit_collection
            if verdict.outcome is not GateOutcome.PASS:
                gate_error = verdict.label
                status = Status.BLOCKED if verdict.outcome is GateOutcome.BLOCKED_ENV else Status.FAILED

    if hold is not None and status == Status.PASSED:
        # [ORCH-HANDBACK-GUARD-1] every lane above, and any it does not name (no route branch, a
        # parallel worktree, a git automation error): a held route is never reported `passed`.
        # BLOCKED(environment) is a GateOutcome and fills the gate field; INCOMPLETE is not.
        status, gate_error = hold.status, hold.error
        if hold.status is Status.BLOCKED:
            gate_outcome = hold.verdict

    # [ORCH-CONFLICT-1] the landed invariant: a route-lane `passed` that produced changes has its
    # tip on MERGE_TARGET and leaves the repo not mid-merge. Acted on, not just logged — this
    # guards the one line every downstream claim is built on.
    if (tamper is None and branch_name and worktree is None and status is Status.PASSED
            and not no_change_run and route_tip is not None):
        unlanded = check_route_landed_invariants(
            QueueRepo(ACTIVE_REPO_NAME, proj, MERGE_TARGET, BRANCH_PREFIX), batch_file.name, route_tip)
        for v in unlanded:
            log.error(f"⛔ ORCH-CONFLICT-1 invariant: {v}")
        if unlanded:
            status = Status.FAILED
            gate_error = f"ORCH-CONFLICT-1 invariant — {unlanded[0]}; gate was {gate_outcome}"

    # [ORCH-10] AC-O10-05: `tampered` in the status field and `TAMPERED` in the gate field —
    # distinct from `passed` and from `FAIL(product)`, and greppable either way.
    incomplete = hold.label if hold is not None and status == Status.INCOMPLETE else None
    log.info(f"🏁 FINAL STATUS: {status.value} | gate: "
             f"{_gate_status_label(gate_error, gate_outcome, gate_collection, unit_collection, tamper and tamper.label, incomplete, hold.verdict if hold else INCOMPLETE_VERDICT)}")
    result = Result(batch_file=batch_file.name, status=status,
        started=started.isoformat(), finished=finished.isoformat(),
        duration_s=dur, exit_code=ec, briefs=len(briefs),
        playwright_ok=pw_ok, pw_tests=pw_cnt,
        new_migrations=new_mig, log_file=out_log,
        worktree=str(worktree) if worktree else None,
        no_changes=no_change_run, gate_outcome=gate_outcome, gate_collection=gate_collection,
        unit_collection=unit_collection, error=gate_error,
        tampered=(tamper.label if tamper is not None else None))  # [ORCH-10]
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
        # [ORCH-10] TAMPERED halts too: the working directory is not the one the route was
        # handed, so firing the next batch in it would compound the damage, not survive it.
        if r.status in (Status.FAILED, Status.BLOCKED, Status.TAMPERED, Status.INCOMPLETE):
            rem = len(files)-i-1
            if rem: log.error(f"⛔ Queue HALTED ({r.gate_outcome or r.status.value}) — {rem} batches skipped")
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
    # [ORCH-CONTROL-SCOPE-1] C5 / ORCH-PARALLEL-GATE-1: this lane merged with no pre-merge gate. Every
    # branch is now gated in its own worktree BEFORE any merge — PASS merges; anything else is preserved.
    branches = {r.batch_file: f"{BRANCH_PREFIX}-{Path(r.batch_file).stem}-w{wts.index(wt)+1}" for r, wt in results}
    log.info("\nGating each branch before any merge...")
    green = {r.batch_file for r, wt in sorted(results, key=lambda x: x[0].batch_file)
             if r.status == Status.PASSED
             and _gate_parallel_branch(wt, branches[r.batch_file]).outcome is GateOutcome.PASS}
    log.info("\nMerging sequentially...")
    for r, wt in sorted(results, key=lambda x: x[0].batch_file):
        if r.status == Status.PASSED and r.batch_file in green:
            br = branches[r.batch_file]
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

    # [ORCH-4] AC-O4-03: `status` reads the per-repo locks now, and falls back to the legacy
    # state/running.json when there are none — so a marker written by the pre-[ORCH-4] code,
    # or by a still-running old process, is still shown rather than silently dropped.
    markers = sorted((ORCH_DIR / "state").glob(_RUNNING_MARKER_GLOB))
    if not markers and _legacy_running_marker().exists():
        markers = [_legacy_running_marker()]
    if not markers:
        print(f"\n  No active fire.")
    for marker in markers:
        try:
            data = json.loads(marker.read_text())
            pid = data.get("pid", 0)
            pid_alive = _pid_alive(pid) is not False

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
                print(f"\n  ⚠️  Stale {marker.name} from {data.get('started_at', '?')} "
                      f"(pid {pid} no longer alive)")
                print(f"    Cleaning up stale marker...")
                marker.unlink(missing_ok=True)
        except (json.JSONDecodeError, IOError):
            print(f"\n  ⚠️  Corrupt {marker.name} — cleaning up")
            marker.unlink(missing_ok=True)
    if markers:
        _refresh_legacy_running_mirror()

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


def retire_stale_branch(proj: Path, branch_name: str, merge_target: str) -> Optional[str]:
    """If refs/heads/<branch_name> exists, rename it to
    <branch_name>--stale-<YYYYmmdd-HHMMSS> (git branch -m) and return the new name.
    Returns None when the branch does not exist (nothing to retire).
    Raises RuntimeError when the branch exists and the rename fails — the caller must
    NOT fall through to running on the stale branch.

    ORCH-STALEBASE-1. Rename, never delete: the previous attempt's commits are evidence a
    human may want. A second retirement inside the same second gets a `-2`, `-3`, … suffix
    rather than failing. A brief stem never contains `--stale-`, so a retired name is never
    `QueueRepo.branch_for(any brief)` and stays out of check_branch_freshness_invariants.
    """
    if not _git_read(f"git rev-parse --verify --quiet refs/heads/{branch_name}", proj):
        return None
    behind = _git_read(f"git rev-list --count {branch_name}..{merge_target}", proj)
    base = f"{branch_name}--stale-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    new_name, n = base, 2
    while _git_read(f"git rev-parse --verify --quiet refs/heads/{new_name}", proj):
        new_name, n = f"{base}-{n}", n + 1
    r = subprocess.run(f"git branch -m {branch_name} {new_name}",
                       shell=True, capture_output=True, text=True, cwd=str(proj))
    if r.returncode != 0:
        raise RuntimeError(f"could not retire {branch_name} → {new_name}: {r.stderr.strip()}")
    where = f"at {merge_target} tip" if behind == "0" else f"was {behind or '?'} behind {merge_target}"
    log.info(f"♻️  Retired stale branch {branch_name} → {new_name} ({where})")
    return new_name


def _stale_base_result(batch_file: Path, started: datetime, briefs: int, err: str) -> Result:
    """ORCH-STALEBASE-1: the route was not fired — its branch could not be made fresh."""
    log.error(f"⛔ STALE-BASE — {err} — not firing.")
    now = datetime.now()
    return Result(batch_file=batch_file.name, status=Status.FAILED,
                  started=started.isoformat(), finished=now.isoformat(),
                  duration_s=(now - started).total_seconds(),
                  exit_code=2, briefs=briefs, error=f"stale-base: {err}")


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

EXECUTOR_CMDS = ("run", "queue", "parallel", "watch")   # the subcommands that fire an executor
# [ORCH-YORSIE-SAFETY-1] the subcommands that act on ONE repo's tree. Each is named its repo — --repo, or
# the brief's own header — or refused: there is no default to fall back to. The rest (deps, sit:report,
# flaky, handback-scan) read orchestrator state only and run without one.
REPO_CMDS = EXECUTOR_CMDS + ("status", "branches")


def _named_repo(a) -> tuple[str, Optional[str]]:
    """[ORCH-YORSIE-SAFETY-1] (repo, None): --repo, else the one repo every brief argument names.
    ("", why) when none is named or the briefs disagree — never a default."""
    if getattr(a, "repo", ""):
        return a.repo, None
    one = getattr(a, "batch_file", None)
    batches = [one] if one else list(getattr(a, "batch_files", None) or [])
    if not batches:
        return "", f"{a.cmd}: no repo named — pass --repo <name> (config/repos.yaml); there is no default repo"
    named, unnamed = set(), []
    for b in batches:
        try:
            n = parse_repo_from_brief(resolve(b))
        except FileNotFoundError:
            n, b = None, f"{b} (not found)"
        if n:
            named.add(n)
        else:
            unnamed.append(b)
    if unnamed:
        return "", (f"no repo named for {', '.join(unnamed)} — pass --repo <name>, or name it in the brief "
                    f"(`#!queue repo=…` or `## Repo:`); there is no default repo")
    if len(named) > 1:
        return "", (f"the briefs name different repos ({', '.join(sorted(named))}) — one invocation runs "
                    f"one repo; pass --repo, or fire them apart")
    return named.pop(), None


def main():
    ap = argparse.ArgumentParser(description="Spectricom Orchestrator v3.1")
    sp = ap.add_subparsers(dest="cmd")
    stp = sp.add_parser("status")
    stp.add_argument("--repo", default="", help="Target repo (from config/repos.yaml)")
    wp = sp.add_parser("watch")
    wp.add_argument("--repo", default="", help="Target repo (from config/repos.yaml)")

    rp = sp.add_parser("run")
    rp.add_argument("batch_file")
    rp.add_argument("--approve", action="store_true", help="Pre-approve execution")
    rp.add_argument("--force", action="store_true", help="Skip ALL safety checks")
    rp.add_argument("--skip-deps", action="store_true", help="Ignore dependency check")
    rp.add_argument("--skip-sit", action="store_true", help="Skip post-merge SIT smoke test")
    rp.add_argument("--repo", default="", help="Target repo (from config/repos.yaml)")
    rp.add_argument("--model", default="", help=f"Executor model (default: env TONI_MODEL or {DEFAULT_EXECUTOR_MODEL})")
    rp.add_argument("--effort", default="", help=f"Executor effort (default: env TONI_EFFORT or {DEFAULT_EXECUTOR_EFFORT})")

    qp = sp.add_parser("queue")
    qp.add_argument("batch_files", nargs="+")
    qp.add_argument("--approve", action="store_true", required=True)
    qp.add_argument("--force", action="store_true")
    qp.add_argument("--skip-deps", action="store_true")
    qp.add_argument("--skip-sit", action="store_true", help="Skip post-merge SIT smoke test")
    qp.add_argument("--repo", default="", help="Target repo (from config/repos.yaml)")
    qp.add_argument("--model", default="", help=f"Executor model (default: env TONI_MODEL or {DEFAULT_EXECUTOR_MODEL})")
    qp.add_argument("--effort", default="", help=f"Executor effort (default: env TONI_EFFORT or {DEFAULT_EXECUTOR_EFFORT})")

    pp = sp.add_parser("parallel")
    pp.add_argument("batch_files", nargs="+")
    pp.add_argument("--approve", action="store_true", required=True)
    pp.add_argument("--force", action="store_true")
    pp.add_argument("--skip-sit", action="store_true", help="Skip post-merge SIT smoke test")
    pp.add_argument("--repo", default="", help="Target repo (from config/repos.yaml)")
    pp.add_argument("--model", default="", help=f"Executor model (default: env TONI_MODEL or {DEFAULT_EXECUTOR_MODEL})")
    pp.add_argument("--effort", default="", help=f"Executor effort (default: env TONI_EFFORT or {DEFAULT_EXECUTOR_EFFORT})")

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

    fkp = sp.add_parser("flaky", help="Report the accumulated flaky-file tail (read-only)")
    fkp.add_argument("--repo", default="", help="Narrow the report to one repo (from config/repos.yaml)")

    hsp = sp.add_parser("handback-scan",
                        help="Check fire_toni logs for executor output that advertises outstanding work (read-only)")
    hsp.add_argument("paths", nargs="*", help="toni-*.log files or directories (default: every repo's log dir)")
    hsp.add_argument("--until", default=None, help="Only logs whose filename timestamp is <= YYYYMMDD-HHMMSS")

    # [ORCH-LANE-1] O3: no --repo — the brief names its repo, and nothing here acts on a tree.
    vp = sp.add_parser("verify", help="One route's evidence: FINAL STATUS/gate/unit lines, handback-scan, "
                                      "git show --stat, the handback head (read-only; never reads stdin)")
    vp.add_argument("stem", help="the brief's stem, e.g. 109-minime-rules-1")
    vp.add_argument("--commit", default=None, help="the commit to show (default: the orch log's merge line, else "
                                                   "the route branch, else the newest merge-target commit "
                                                   "touching the handback)")

    a = ap.parse_args()

    # OI-026 A3: resolve repo — --repo CLI > the brief's own header. [ORCH-YORSIE-SAFETY-1] no default:
    # a repo command named none is refused here, before any lock, branch or executor.
    repo_name, why = _named_repo(a)
    if why and a.cmd in REPO_CMDS:
        print(f"⛔ {why} — refused, nothing fired", file=sys.stderr)
        sys.exit(1)
    if repo_name:
        try:
            set_active_repo(repo_name)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)

    # HOOK-1: --force is the single documented bypass for the assertions.
    global PREFIRE_BYPASS
    if getattr(a, 'force', False):
        PREFIRE_BYPASS = True
        log.warning('--force: pre-fire assertions (A2/A8) BYPASSED; A1 Kanban READY not checked')
        # S7-CORE-8 [ORCH-3] / AC-O3-11: --force bypasses the PRE-FIRE assertions. It does not,
        # and has never, bypassed the PRE-MERGE gates. State that in the same breath, in the
        # same wording A2/A8 report in, so "ALL safety checks bypassed" is never read as
        # covering the gates. The unit gate's own escape is DISABLE_UNIT_GATE, alongside
        # DISABLE_BUILD_GATE / DISABLE_SIT_BLOCKING; each logs itself as a bypass when used.
        log.warning('--force: pre-merge gates NOT bypassed — build, SIT and the unit baseline '
                    'gate still run and still block the merge '
                    '(escapes: DISABLE_BUILD_GATE / DISABLE_SIT_BLOCKING / DISABLE_UNIT_GATE)')

    # Apply --skip-sit globally before any command runs
    global SKIP_SIT
    if getattr(a, 'skip_sit', False):
        SKIP_SIT = True

    # Executor model/effort override (S7-CORE-4 [MODEL-1], D-S7CORE3-05)
    global TONI_MODEL, TONI_EFFORT
    if getattr(a, 'model', ''):
        TONI_MODEL = a.model
    if getattr(a, 'effort', ''):
        TONI_EFFORT = a.effort
    # [EXECUTOR-DEFAULT-1] only a command that fires an executor names one: a read-only command
    # (handback-scan, status, deps, …) printing `Executor:` reads as a route that never ran.
    if a.cmd in EXECUTOR_CMDS:
        log.info(f"Executor: model={TONI_MODEL} effort={TONI_EFFORT}")

    if a.cmd == "run":
        # [ORCH-4]: the lock is per repo — a live fire in a DIFFERENT repo does not refuse
        # this one. set_active_repo() ran above, so ACTIVE_REPO_NAME is resolved by here.
        _check_stale_marker(ACTIVE_REPO_NAME)
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

    elif a.cmd == "flaky":
        flaky_report(getattr(a, "repo", "") or "")

    elif a.cmd == "handback-scan":
        sys.exit(handback_scan(a.paths, a.until))

    elif a.cmd == "verify":
        sys.exit(verify_route(a.stem, a.commit))

    else:
        ap.print_help()

if __name__ == "__main__":
    main()
