#!/usr/bin/env python3
"""
ADMISSION — whether a Toni route may start now (ORCH-CAPACITY-1, S7-CORE-21)
=============================================================================
S7-CORE-20 10:30: the laptop ran out of memory with two Toni routes live, and George ruled one Toni
route at a time, and only with memory to spare (LESSONS L-70). One place decides; both callers ask it:
the queue daemon's fire loop WAITS on a refusal, a direct `orchestrator.py run` is REFUSED (exit 2) and
`--force` bypasses it, saying so.

  admit(repo) -> (ok, reason) refuses when
    (a) the live routes across ALL repos >= admission.max_concurrent_routes (config/repos.yaml, default 1).
        A route is a live marker: state/running*.json (the per-repo locks and their mirror), the root
        running*.json, or a claim (below), whose pid is alive. A dead pid is stale and ignored, as P-STALE
        ignores it. One process is one route, however many markers name it;
    (b) MemAvailable in /proc/meminfo < admission.min_mem_available_gib (config; shipped 6).

A CLAIM, state/admitted-<pid>.json, closes the gap between a yes and the route's own lock, which
orchestrator.py writes only after pre-fire and the worktree. It is written under state/admission.lock in
the same breath as the yes, so two askers can never both be admitted into one free slot. The daemon
claims for the route it fires and names the claim to it (ORCH_ADMISSION_CLAIM); that route's `run`
adopts the claim instead of asking again, so a route the daemon admitted is never refused by its own
second look.

route_wall(brief, repo) is the daemon's kill for one route (C4): the route timeout orchestrator.py
resolves for that brief, plus the repo's gate budget, plus ROUTE_WALL_SLACK_S.

CLI, read-only:  python3 admission.py [--orch-dir D] check <repo>            # exit 0 admitted, 2 refused
                 python3 admission.py [--orch-dir D] routes [--repo <repo>]  # exit 0 none live, 1 some
"""

import atexit
import fcntl
import json
import os
import re
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

import yaml

ORCH_DIR = Path.home() / "spectricom-orchestrator"   # where the markers live; callers pass their own
MEMINFO = Path("/proc/meminfo")
DEFAULT_MAX_CONCURRENT_ROUTES = 1     # L-70: one Toni route at a time
DEFAULT_MIN_MEM_AVAILABLE_GIB = 6     # the floor when config names none; the shipped config says it too
KIB_PER_GIB = 1024 * 1024
CLAIM_ENV = "ORCH_ADMISSION_CLAIM"
CLAIM_GLOB = "admitted-*.json"
ADMISSION_LOCK = "admission.lock"

# ── orchestrator.py's clocks, restated: importing orchestrator writes a log (the reason queue_daemon
# restates _pid_alive). tests/test_capacity.py pins every value here against orchestrator's own. ──
TIMEOUT_DEFAULT_MIN = 45
TIMEOUT_HARD_CAP_MIN = 180
GATE_TIMEOUTS = {"build": 600, "sit": 600, "unit": 900, "unit-baseline": 1800, "unit-confirm": 300}
UNIT_TIMEOUT_KEYS = {"unit": "test_timeout_s", "unit-baseline": "baseline_timeout_s",
                     "unit-confirm": "confirm_timeout_s"}
PRE_MERGE_GATE_SETS = {"clinical-mp": ("build", "sit"), "orchestrator": ("build",), "yorsie": ("build",)}
# C4: what neither clock bounds — pre-fire, the worktree and branch, the commit, SIT enumeration and its
# batch pauses, the merge. Added on top of the derived budget; never a ceiling below it.
ROUTE_WALL_SLACK_S = 900


def _read_json(path) -> dict:
    """The JSON object at `path`, or {} when it is absent, unreadable, mid-write or not an object."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, default=str))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _pid_alive(pid) -> Optional[bool]:
    """True / False / None, None being "exists but not ours to signal", which counts as ALIVE (the safe
    direction). orchestrator._pid_alive's rule, restated for the reason above."""
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


def _slug(repo_name) -> str:
    """orchestrator._marker_repo_slug's rule, restated."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(repo_name or "").strip()).strip("-.")
    return slug or "unknown"


def _config(config_path) -> dict:
    try:
        cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return cfg if isinstance(cfg, dict) else {}


def _paths(orch_dir, config_path) -> tuple[Path, Path]:
    orch = Path(orch_dir or ORCH_DIR)
    return orch, Path(config_path or orch / "config" / "repos.yaml")


def _count(value, default, *, floor) -> int | float:
    """A config number >= floor (bool is not a number); `default` for anything else."""
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= floor
    return value if ok else default


def limits(config_path) -> tuple[int, float]:
    """(max_concurrent_routes, min_mem_available_gib) from the `admission:` block — read per call, so a
    changed floor takes effect at the next fire with no release and no restart."""
    block = _config(config_path).get("admission")
    block = block if isinstance(block, dict) else {}
    most = block.get("max_concurrent_routes")
    most = most if isinstance(most, int) and not isinstance(most, bool) and most >= 1 else DEFAULT_MAX_CONCURRENT_ROUTES
    return most, float(_count(block.get("min_mem_available_gib"), DEFAULT_MIN_MEM_AVAILABLE_GIB, floor=0))


@dataclass(frozen=True)
class LiveRoute:
    pid: Optional[int]
    repo: str
    batch: str
    marker: Path

    def describe(self, orch: Path) -> str:
        try:
            where = self.marker.relative_to(orch)
        except ValueError:
            where = self.marker
        who = f"pid {self.pid}" if self.pid is not None else "no pid recorded — cannot be judged"
        return f"{self.repo} {self.batch} ({who}, {where})"


def live_routes(orch_dir=None, repo: Optional[str] = None) -> list[LiveRoute]:
    """Every live route, one per process: the per-repo locks first (they name repo and batch), then the
    mirror, the root markers and the claims. A marker with no pid takes the pid of the lock naming its
    batch (P-STALE's rule); one with none to be had is counted — it cannot be judged, the safe direction.
    `repo` narrows the list to the routes in that repo."""
    orch, _ = _paths(orch_dir, None)
    state = orch / "state"
    paths = (sorted(state.glob("running-*.json")) + [state / "running.json"]
             + sorted(orch.glob("running*.json")) + sorted(state.glob(CLAIM_GLOB)))
    docs = [(p, _read_json(p)) for p in paths if p.is_file()]
    by_batch = {d.get("batch_id"): d for _, d in docs if d.get("batch_id") and d.get("pid") is not None}
    routes: dict = {}
    for p, d in docs:
        if not d:
            continue
        batch = d.get("batch_id") or d.get("batch") or Path(str(d.get("batch_file") or "")).stem or "?"
        lock = by_batch.get(batch) or {}
        pid = d.get("pid", lock.get("pid"))
        if pid is not None and _pid_alive(pid) is False:
            continue
        key = pid if pid is not None else str(p)
        if key not in routes:
            routes[key] = LiveRoute(pid=pid, repo=d.get("repo") or lock.get("repo") or "?", batch=batch, marker=p)
    out = list(routes.values())
    return [r for r in out if _slug(r.repo) == _slug(repo)] if repo else out


def mem_available_gib(meminfo=None) -> Optional[float]:
    """MemAvailable from /proc/meminfo, in GiB; None when it cannot be read."""
    try:
        text = Path(meminfo or MEMINFO).read_text()
    except OSError:
        return None
    m = re.search(r"^MemAvailable:\s+(\d+)\s*kB", text, re.M)
    return int(m.group(1)) / KIB_PER_GIB if m else None


def _verdict(repo: str, orch: Path, config_path: Path, meminfo) -> tuple[bool, str]:
    most, floor = limits(config_path)
    routes = live_routes(orch)
    if len(routes) >= most:
        return False, (f"route limit — {len(routes)} live route(s), admission.max_concurrent_routes {most}: "
                       + "; ".join(r.describe(orch) for r in routes) + f" — {repo} waits")
    gib = mem_available_gib(meminfo)
    where = meminfo or MEMINFO
    if gib is None:
        return False, f"memory floor — MemAvailable unreadable in {where}; cannot judge, {repo} waits"
    if gib < floor:
        return False, (f"memory floor — MemAvailable {gib:.1f} GiB < admission.min_mem_available_gib "
                       f"{floor:g} GiB ({where}) — {repo} waits")
    return True, (f"admitted {repo} — {len(routes)} live route(s) < admission.max_concurrent_routes {most}; "
                  f"MemAvailable {gib:.1f} GiB >= admission.min_mem_available_gib {floor:g} GiB")


@contextmanager
def _locked(orch: Path):
    """state/admission.lock, held for one count-and-claim: milliseconds."""
    (orch / "state").mkdir(parents=True, exist_ok=True)
    with open(orch / "state" / ADMISSION_LOCK, "a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def claim_path(orch_dir=None, pid: Optional[int] = None) -> Path:
    orch, _ = _paths(orch_dir, None)
    return orch / "state" / f"admitted-{pid or os.getpid()}.json"


def _claim(orch: Path, repo: str, batch: Optional[str], why: str) -> Path:
    p = claim_path(orch)
    _write_json_atomic(p, {"pid": os.getpid(), "repo": repo, "batch": batch or "?",
                           "at": datetime.now().isoformat(), "admitted": why})
    return p


def admit(repo: str, batch: Optional[str] = None, *, claim: bool = False, orch_dir=None, config_path=None,
          meminfo=None) -> tuple[bool, str]:
    """(ok, reason). `claim`: on a yes, write this process's claim under the admission lock, so the slot
    is held from this moment — not from when the route's own lock appears."""
    orch, cfg = _paths(orch_dir, config_path)
    if not claim:
        return _verdict(repo, orch, cfg, meminfo)
    with _locked(orch):
        ok, why = _verdict(repo, orch, cfg, meminfo)
        if ok:
            _claim(orch, repo, batch, why)
    return ok, why


def adopt(claim, batch: str) -> Optional[str]:
    """A daemon-fired route's half: take over the claim the daemon wrote for it (ORCH_ADMISSION_CLAIM) —
    its pid becomes this process's. None when there is nothing to adopt: no claim named, the file gone,
    a claim for another brief, or one whose writer is dead."""
    if not claim:
        return None
    p = Path(claim)
    with _locked(p.parent.parent):
        d = _read_json(p)
        if not d or d.get("batch") != batch or _pid_alive(d.get("pid")) is False:
            return None
        by = d.get("pid")
        d.update(pid=os.getpid(), adopted_from=by, adopted_at=datetime.now().isoformat())
        _write_json_atomic(p, d)
    atexit.register(release, p, os.getpid())
    return f"admitted by the queue daemon (pid {by}; its claim {p.name} is this route's now) — not asked again"


def release(claim, pid: Optional[int] = None) -> None:
    """Remove a claim — only its holder's, when `pid` is named. Never raises."""
    try:
        p = Path(claim)
        if pid is None or _read_json(p).get("pid") == pid:
            p.unlink(missing_ok=True)
    except OSError:
        pass


def admit_run(repo: str, batch: str, *, force: bool = False, orch_dir=None, config_path=None, meminfo=None,
              env: Optional[Mapping[str, str]] = None) -> tuple[bool, str]:
    """`orchestrator.py run`'s one call. A claim the daemon handed down is adopted; otherwise admit() and
    claim. `--force` claims whatever the verdict was, and the reason says it was bypassed."""
    env = os.environ if env is None else env
    handed = adopt(env.get(CLAIM_ENV), batch)
    if handed:
        return True, handed
    orch, cfg = _paths(orch_dir, config_path)
    with _locked(orch):
        ok, why = _verdict(repo, orch, cfg, meminfo)
        if ok or force:
            atexit.register(release, _claim(orch, repo, batch, why), os.getpid())
    if force:
        return True, f"--force: admission BYPASSED — {'it admits anyway' if ok else 'it would have refused'}: {why}"
    return ok, why


# ═══════════════════════════════════════════════════════
# C4 · the daemon's wall for one route
# ═══════════════════════════════════════════════════════
def parse_brief_timeout(brief) -> Optional[int]:
    """orchestrator.parse_brief_timeout, restated: minutes the brief declares, or None."""
    try:
        content = Path(brief).read_text(encoding="utf-8")[:4000]
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
        rm = re.search(r'(\d+)\s*-\s*(\d+)\s*m', m.group(1))
        if rm:
            return int(int(rm.group(2)) * 1.25)
        rm = re.search(r'(\d+)\s*m', m.group(1))
        if rm:
            return int(int(rm.group(1)) * 1.25)
    return None


def route_timeout(brief, env: Optional[Mapping[str, str]] = None) -> tuple[int, str]:
    """(minutes, source) by orchestrator.resolve_timeout's rule: TONI_TIMEOUT_MIN > brief-declared > the
    default, capped. The daemon's environment is its route's (the child inherits it). A TONI_TIMEOUT_MIN that
    is not a number fails the route in orchestrator.py; here it is the cap, the long side."""
    env = os.environ if env is None else env
    raw = env.get("TONI_TIMEOUT_MIN", "")
    if raw:
        try:
            minutes, source = int(raw), "env-var"
        except ValueError:
            return TIMEOUT_HARD_CAP_MIN, f"env-var {raw!r} unreadable — the {TIMEOUT_HARD_CAP_MIN}m cap"
    else:
        declared = parse_brief_timeout(brief) if brief else None
        minutes, source = (declared, "brief-declared") if declared is not None else (TIMEOUT_DEFAULT_MIN, "default")
    return min(minutes, TIMEOUT_HARD_CAP_MIN), source


def gate_budget(repo: str, config_path=None) -> tuple[int, str]:
    """(seconds, how). `admission.gate_budget_s` — one number for every repo, or a map of repo → number —
    else the sum of that repo's configured gate timeouts: each PRE_MERGE_GATES leg it runs, and the three
    unit legs when it declares a test_cmd, with its repos.yaml overrides."""
    cfg = _config(_paths(None, config_path)[1])
    block = cfg.get("admission") if isinstance(cfg.get("admission"), dict) else {}
    override = block.get("gate_budget_s")
    if isinstance(override, dict):
        override = override.get(repo)
    if _count(override, None, floor=1) is not None:
        return int(override), "admission.gate_budget_s"
    r = (cfg.get("repos") or {}).get(repo) or {}
    legs = [(g, GATE_TIMEOUTS[g]) for g in PRE_MERGE_GATE_SETS.get(repo, ()) if g in GATE_TIMEOUTS]
    if r.get("test_cmd"):
        legs += [(leg, int(_count(r.get(key), GATE_TIMEOUTS[leg], floor=1))) for leg, key in UNIT_TIMEOUT_KEYS.items()]
    how = " + ".join(f"{leg} {s}s" for leg, s in legs) or "no gates"
    return sum(s for _, s in legs), f"the sum of its gate timeouts: {how}"


@dataclass(frozen=True)
class RouteWall:
    seconds: int
    route_timeout_s: int
    route_timeout_source: str
    gate_budget_s: int
    gate_budget_source: str
    slack_s: int

    def describe(self) -> str:
        return (f"{self.seconds}s ({self.seconds / 60:.0f}m) = route timeout {self.route_timeout_s // 60}m "
                f"({self.route_timeout_source}) + gate budget {self.gate_budget_s}s ({self.gate_budget_source}) "
                f"+ {self.slack_s}s slack")

    def as_dict(self) -> dict:
        return {**asdict(self), "describe": self.describe()}


def route_wall(brief, repo: str, *, config_path=None, env: Optional[Mapping[str, str]] = None) -> RouteWall:
    """C4 · S7-CORE-21 21:27: route 122 (Toni exit 0 at 159 min, build and SIT green) was killed in its unit
    gate by the daemon's fixed 190 min, under orchestrator.py's own 162 min + gates. The wall is derived from
    the brief, as orchestrator derives its own clock, plus the gates' budget and the slack."""
    minutes, source = route_timeout(brief, env)
    budget, how = gate_budget(repo, config_path)
    return RouteWall(seconds=minutes * 60 + budget + ROUTE_WALL_SLACK_S, route_timeout_s=minutes * 60,
                     route_timeout_source=source, gate_budget_s=budget, gate_budget_source=how,
                     slack_s=ROUTE_WALL_SLACK_S)


def main(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="admission.py", description="ORCH-CAPACITY-1 admission (read-only)")
    ap.add_argument("--orch-dir", default=None, help=f"where the markers live (default {ORCH_DIR})")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("check", help="would a route in <repo> be admitted now? exit 0 yes, 2 no").add_argument("repo")
    rp = sp.add_parser("routes", help="the live routes; exit 0 none, 1 some")
    rp.add_argument("--repo", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        ok, why = admit(a.repo, orch_dir=a.orch_dir)
        print(why)
        return 0 if ok else 2
    orch, _ = _paths(a.orch_dir, None)
    routes = live_routes(orch, a.repo)
    for r in routes:
        print(r.describe(orch))
    return 1 if routes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
