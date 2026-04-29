#!/usr/bin/env python3
"""
SPECTRICOM OPS DASHBOARD v5
=============================
Live monitoring + Kanban + Queue Daemon (D-256 AAI Layer A).

  python3 orch-dashboard.py              ← start on port 8091 (no daemon)
  python3 orch-dashboard.py --daemon     ← start with queue daemon
  python3 orch-dashboard.py --port 9000  ← custom port

Dashboard: http://localhost:8091
API:
  GET /api/all         ← combined payload (state + rate + daemons + running + logs + queue)
  GET /api/toni-log    ← live tail of active Toni execution log
  GET /api/queue       ← queue daemon status
"""

import os, sys, json, glob, argparse, subprocess, shlex
from pathlib import Path
from datetime import datetime, date
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

try:
    from queue_daemon import QueueDaemon, start_daemon_thread
except ImportError:
    QueueDaemon = None
    start_daemon_thread = None

# Global daemon instance (set in main if --daemon)
_daemon = None

ORCH_DIR = Path.home() / "spectricom-orchestrator"
STATE_FILE = ORCH_DIR / "state.json"
RATE_FILE = ORCH_DIR / "rate-limits.json"
CAPS_FILE = ORCH_DIR / "rate-caps.json"
RUNNING_FILE = ORCH_DIR / "running.json"
BRIDGE_PID = ORCH_DIR / "bridge.pid"
WATCHER_PID = ORCH_DIR / "watcher.pid"
BRIDGE_LOG = ORCH_DIR / "logs" / "bridge.log"
ORCH_LOG_DIR = ORCH_DIR / "logs"
from repo_config import load_default_repo_config as _ldrc
_default_name, _default_cfg = _ldrc()
BRIEFS_DIR = Path(_default_cfg["project_dir"]).expanduser() / _default_cfg.get("briefs_subdir", "briefs")

DEFAULT_PORT = 8091

def read_json(path):
    try:
        if path.exists(): return json.loads(path.read_text())
    except: pass
    return {}

def get_state():
    s = read_json(STATE_FILE)
    completed = s.get("completed", [])
    failed = s.get("failed", [])
    done_names = {b.get("batch_file","") for b in completed} | {b.get("batch_file","") for b in failed}
    pending = []
    if BRIEFS_DIR.exists():
        for f in sorted(BRIEFS_DIR.glob("*.md")):
            if f.name not in done_names:
                pending.append({"name":f.name,"size":f.stat().st_size,
                    "modified":datetime.fromtimestamp(f.stat().st_mtime).isoformat()})
    return {
        "completed": completed[-20:], "failed": failed[-10:], "pending": pending,
        "totals": {"completed":len(completed),"failed":len(failed),"pending":len(pending),
            "total_duration_s":sum(b.get("duration_s",0) for b in completed),
            "total_briefs":sum(b.get("briefs",0) for b in completed)}
    }

def get_running():
    """Read running.json for live execution status."""
    if not RUNNING_FILE.exists():
        return None
    try:
        data = json.loads(RUNNING_FILE.read_text())
        # Calculate elapsed time
        started = datetime.fromisoformat(data.get("started",""))
        data["elapsed_s"] = (datetime.now() - started).total_seconds()
        data["elapsed_fmt"] = f"{data['elapsed_s']/60:.1f}m"
        return data
    except:
        return None

def get_toni_log(n=80):
    """Tail the active Toni log file."""
    running = get_running()
    if not running:
        # Fall back to most recent toni log
        logs = sorted(ORCH_LOG_DIR.glob("toni-*.log"), reverse=True)
        if not logs: return {"active": False, "lines": [], "file": None}
        latest = logs[0]
    else:
        log_file = running.get("log_file","")
        latest = Path(log_file) if log_file and Path(log_file).exists() else None
        if not latest:
            logs = sorted(ORCH_LOG_DIR.glob("toni-*.log"), reverse=True)
            latest = logs[0] if logs else None
    if not latest or not latest.exists():
        return {"active": bool(running), "lines": [], "file": None}
    try:
        content = latest.read_text(errors="replace")
        lines = content.strip().split("\n")
        return {"active": bool(running), "lines": lines[-n:], "file": latest.name}
    except:
        return {"active": bool(running), "lines": [], "file": None}

def get_rate():
    data = read_json(RATE_FILE)
    caps = read_json(CAPS_FILE) or {"daily_batches":15,"daily_briefs":60}
    tk = date.today().isoformat()
    today = data.get("daily",{}).get(tk,{"batches":0,"briefs":0,"duration_s":0,"executions":[]})
    lt = data.get("lifetime",{"batches":0,"briefs":0,"total_duration_s":0})
    br = today["duration_s"]/today["briefs"] if today["briefs"]>0 else 0
    history = []
    for d in sorted(data.get("daily",{}).keys(), reverse=True)[:7]:
        dd=data["daily"][d]; history.append({"date":d,"batches":dd.get("batches",0),
            "briefs":dd.get("briefs",0),"duration_min":round(dd.get("duration_s",0)/60,1)})
    return {"caps":caps,"today":today,"lifetime":lt,"burn_rate_s_per_brief":round(br,1),
        "batch_pct":round(today["batches"]/caps["daily_batches"]*100) if caps["daily_batches"]>0 else 0,
        "brief_pct":round(today["briefs"]/caps["daily_briefs"]*100) if caps["daily_briefs"]>0 else 0,
        "history":history}

def check_pid(pf):
    if not pf.exists(): return {"running":False,"pid":None,"status":"stopped"}
    try:
        pid=int(pf.read_text().strip()); os.kill(pid,0)
        return {"running":True,"pid":pid,"status":"running"}
    except: return {"running":False,"pid":None,"status":"dead"}

def get_daemons():
    bridge=check_pid(BRIDGE_PID); bridge["name"]="Drive Bridge"
    watcher=check_pid(WATCHER_PID); watcher["name"]="Drive Watcher"
    bl=[]
    if BRIDGE_LOG.exists():
        try: bl=BRIDGE_LOG.read_text().strip().split("\n")[-8:]
        except: pass
    bridge["recent_log"]=bl
    return {"bridge":bridge,"watcher":watcher}

def get_orch_logs(n=30):
    logs=sorted(ORCH_LOG_DIR.glob("orch-*.log"), reverse=True)
    if not logs: return {"file":None,"lines":[]}
    try: lines=logs[0].read_text().strip().split("\n"); return {"file":logs[0].name,"lines":lines[-n:]}
    except: return {"file":None,"lines":[]}


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


def get_git_progress():
    """Get live git activity from the project repo during Toni execution."""
    import subprocess
    PROJECT = Path(_default_cfg["project_dir"]).expanduser()
    running = get_running()

    result = {
        "active": bool(running),
        "batch": running["batch_file"] if running else None,
        "expected_briefs": running["briefs"] if running else 0,
        "elapsed": running.get("elapsed_fmt", "") if running else "",
        "commits_since_start": [],
        "commit_count": 0,
        "modified_files": [],
        "modified_count": 0,
        "staged_files": [],
        "progress_pct": 0,
        "current_brief": "Starting..."
    }

    if not running:
        # Show last batch results
        try:
            r = subprocess.run(
                "git log --oneline -10",
                shell=True, capture_output=True, text=True, cwd=str(PROJECT), timeout=5
            )
            if r.returncode == 0:
                result["commits_since_start"] = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
        except: pass
        return result

    start_time = running.get("started", "")

    # Recent commits since batch started
    try:
        cmd = f'git log --oneline --since="{start_time}"'
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=str(PROJECT), timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            commits = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
            result["commits_since_start"] = commits
            result["commit_count"] = len(commits)
            if commits:
                result["current_brief"] = commits[0].split(" ", 1)[-1] if " " in commits[0] else commits[0]
    except: pass

    # Modified files in working directory
    try:
        r = subprocess.run(
            "git diff --name-only",
            shell=True, capture_output=True, text=True, cwd=str(PROJECT), timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            files = [f.strip() for f in r.stdout.strip().split("\n") if f.strip()]
            result["modified_files"] = files[-20:]  # last 20
            result["modified_count"] = len(files)
    except: pass

    # Staged files
    try:
        r = subprocess.run(
            "git diff --cached --name-only",
            shell=True, capture_output=True, text=True, cwd=str(PROJECT), timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            result["staged_files"] = [f.strip() for f in r.stdout.strip().split("\n") if f.strip()]
    except: pass

    # New untracked files
    try:
        r = subprocess.run(
            "git ls-files --others --exclude-standard",
            shell=True, capture_output=True, text=True, cwd=str(PROJECT), timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            new_files = [f.strip() for f in r.stdout.strip().split("\n") if f.strip() and not f.startswith("yorsie/test-results")]
            result["modified_files"] = list(set(result["modified_files"] + new_files))[-20:]
            result["modified_count"] = len(set(result.get("modified_files", []) + new_files))
    except: pass

    # Progress percentage — use brief progress from log parsing
    bp = get_brief_progress()
    expected = result["expected_briefs"]
    if bp["completed_briefs"] > 0 and expected > 0:
        result["progress_pct"] = min(100, round(bp["completed_briefs"] / expected * 100))
    elif expected > 0 and result["commit_count"] > 0:
        result["progress_pct"] = min(100, round(result["commit_count"] / expected * 100))
    elif result["modified_count"] > 0:
        result["progress_pct"] = 10  # at least started

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

    return result

# ─── ACTION HANDLERS ───────────────────────────────────────────────────────
ACTIONS = {
    "restart-watcher": {
        "label": "Restart Drive Watcher",
        "cmd": "bash -c 'python3 ~/spectricom-orchestrator/drive-watcher.py stop; sleep 1; python3 ~/spectricom-orchestrator/drive-watcher.py start'"
    },
    "restart-bridge": {
        "label": "Restart Drive Bridge",
        "cmd": "bash -c 'python3 ~/spectricom-orchestrator/drive-bridge.py stop; sleep 1; python3 ~/spectricom-orchestrator/drive-bridge.py start'"
    },
    "start-all": {
        "label": "Start All Services",
        "cmd": "bash ~/spectricom-orchestrator/startup.sh start"
    },
    "stop-all": {
        "label": "Stop All Services",
        "cmd": "bash ~/spectricom-orchestrator/startup.sh stop"
    },
    "status-all": {
        "label": "Service Status",
        "cmd": "bash ~/spectricom-orchestrator/startup.sh status"
    },
    # YORSIE-specific dashboard shortcuts (per OI-026 v1-2 A7 scope).
    "dev-server-start": {
        "label": "Start Dev Server",
        "cmd": "bash -c 'cd ~/spectricom-dev-pipeline/yorsie && nohup npm run dev > /tmp/dev-server.log 2>&1 &'"
    },
    "dev-server-stop": {
        "label": "Stop Dev Server",
        "cmd": "bash -c 'pkill -f vite || true'"
    },
    "dev-server-status": {
        "label": "Dev Server Status",
        "cmd": "bash -c 'pgrep -a vite || echo not running'"
    },
    "apply-migrations": {
        "label": "Apply Migrations (last)",
        "cmd": "bash -c 'cd ~/spectricom-dev-pipeline && ls yorsie/supabase/migrations/*.sql | tail -1 | xargs -I{} npx supabase db query --linked -f {}'"
    },
    "git-status": {
        "label": "Git Status",
        "cmd": "bash -c 'cd ~/spectricom-dev-pipeline && git status --short'"
    },
    "git-pull": {
        "label": "Git Pull",
        "cmd": "bash -c 'cd ~/spectricom-dev-pipeline && git pull'"
    },
    "queue-pause": {
        "label": "Pause Queue",
        "handler": "queue"
    },
    "queue-resume": {
        "label": "Resume Queue",
        "handler": "queue"
    },
    "queue-cancel": {
        "label": "Cancel Current Batch",
        "handler": "queue"
    },
    "queue-clear": {
        "label": "Clear Queue",
        "handler": "queue"
    },
    "queue-reset": {
        "label": "Reset Consecutive Counter",
        "handler": "queue"
    },
}

def run_queue_action(action_id):
    global _daemon
    if not _daemon:
        return {"ok": False, "error": "Queue daemon not running. Start with --daemon flag."}
    if action_id == "queue-pause":
        return _daemon.pause()
    elif action_id == "queue-resume":
        return _daemon.resume()
    elif action_id == "queue-cancel":
        return _daemon.cancel_current()
    elif action_id == "queue-clear":
        return _daemon.clear_queue()
    elif action_id == "queue-reset":
        return _daemon.reset_consecutive()
    return {"ok": False, "error": f"Unknown queue action: {action_id}"}

def run_action(action_id):
    if action_id not in ACTIONS:
        return {"ok": False, "error": f"Unknown action: {action_id}"}
    a = ACTIONS[action_id]
    if a.get("handler") == "queue":
        return run_queue_action(action_id)
    try:
        r = subprocess.run(
            a["cmd"], shell=True, capture_output=True, text=True, timeout=30,
            executable="/bin/bash"
        )
        return {
            "ok": r.returncode == 0,
            "action": action_id,
            "label": a["label"],
            "stdout": r.stdout.strip()[-2000:],
            "stderr": r.stderr.strip()[-500:],
            "returncode": r.returncode
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "action": action_id, "error": "Timed out after 30s"}
    except Exception as e:
        return {"ok": False, "action": action_id, "error": str(e)}

def get_all():
    running = get_running()
    q = _daemon.get_status() if _daemon else {"daemon_status": "off", "queue_count": 0}
    return {
        "state":get_state(),"rate":get_rate(),"daemons":get_daemons(),
        "logs":get_orch_logs(30),"toni_log":get_toni_log(40),
        "running":running,"git_progress":get_git_progress(),
        "queue":q,
        "timestamp":datetime.now().isoformat(),"auto_fire":False
    }

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spectricom Ops</title>
<style>
  :root {
    --bg:#0f1117;--surface:#1a1d27;--border:#2a2d3a;
    --text:#e4e4e7;--muted:#71717a;--accent:#6366f1;
    --green:#22c55e;--red:#ef4444;--yellow:#eab308;--blue:#3b82f6;--orange:#f97316;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'SF Mono','Cascadia Code','Fira Code',monospace;background:var(--bg);color:var(--text);font-size:13px;line-height:1.5}
  .container{max-width:1200px;margin:0 auto;padding:16px}
  .header{display:flex;align-items:center;justify-content:space-between;padding:12px 0;border-bottom:1px solid var(--border);margin-bottom:16px}
  .header h1{font-size:16px;font-weight:600}
  .header .meta{color:var(--muted);font-size:11px}
  .pulse{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--green);margin-right:8px;animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
  .tabs{display:flex;gap:0;margin-bottom:16px;border-bottom:1px solid var(--border)}
  .tab{padding:8px 20px;cursor:pointer;color:var(--muted);font-size:13px;font-weight:600;border-bottom:2px solid transparent;transition:.2s;user-select:none}
  .tab:hover{color:var(--text)}.tab.active{color:var(--accent);border-bottom-color:var(--accent)}
  .tab-panel{display:none}.tab-panel.active{display:block}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
  .grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:12px}
  @media(max-width:768px){.grid,.grid-3{grid-template-columns:1fr}}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px}
  .card h2{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:10px}
  .card.full{grid-column:1/-1}
  .stat{display:flex;align-items:baseline;gap:6px;margin-bottom:6px}
  .stat .value{font-size:24px;font-weight:700}.stat .label{color:var(--muted);font-size:11px}
  .meter{height:6px;background:var(--border);border-radius:3px;margin:6px 0;overflow:hidden}
  .meter .fill{height:100%;border-radius:3px;transition:width .5s}.fill.green{background:var(--green)}.fill.yellow{background:var(--yellow)}.fill.red{background:var(--red)}
  .badge{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
  .badge.running{background:rgba(34,197,94,.15);color:var(--green)}.badge.stopped{background:rgba(113,113,122,.15);color:var(--muted)}.badge.dead{background:rgba(239,68,68,.15);color:var(--red)}
  .tbl{width:100%;border-collapse:collapse;font-size:12px}
  .tbl th{text-align:left;color:var(--muted);font-weight:500;padding:4px 8px;border-bottom:1px solid var(--border)}
  .tbl td{padding:4px 8px;border-bottom:1px solid rgba(42,45,58,.5)}.tbl tr:hover td{background:rgba(99,102,241,.05)}
  .pass{color:var(--green)}.fail{color:var(--red)}
  .log{background:#0a0b0f;border-radius:4px;padding:8px;max-height:200px;overflow-y:auto;font-size:11px;line-height:1.6;color:var(--muted)}
  .log .line{white-space:pre-wrap;word-break:break-all}.log .line.err{color:var(--red)}.log .line.warn{color:var(--yellow)}.log .line.ok{color:var(--green)}
  .safety{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.3);border-radius:6px;padding:8px 12px;margin-bottom:12px;display:flex;align-items:center;gap:8px;font-size:12px}

  /* Running banner */
  .running-banner{background:rgba(249,115,22,.12);border:1px solid rgba(249,115,22,.4);border-radius:6px;padding:10px 14px;margin-bottom:12px;display:none;align-items:center;gap:10px;font-size:13px}
  .running-banner.active{display:flex}
  .running-dot{width:10px;height:10px;border-radius:50%;background:var(--orange);animation:pulse 1s infinite}
  .running-banner .rb-name{font-weight:700;color:var(--orange)}
  .running-banner .rb-meta{color:var(--muted);font-size:11px;margin-left:auto}

  /* Kanban */
  .kanban{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;min-height:400px}
  @media(max-width:900px){.kanban{grid-template-columns:repeat(2,1fr)}}
  .kanban-col{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px;display:flex;flex-direction:column}
  .kanban-col-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid var(--border)}
  .kanban-col-title{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em}
  .kanban-col-count{font-size:11px;color:var(--muted);background:var(--border);padding:1px 7px;border-radius:8px}
  .col-pending{border-top:3px solid var(--blue)}.col-pending .kanban-col-title{color:var(--blue)}
  .col-running{border-top:3px solid var(--orange)}.col-running .kanban-col-title{color:var(--orange)}
  .col-passed{border-top:3px solid var(--green)}.col-passed .kanban-col-title{color:var(--green)}
  .col-failed{border-top:3px solid var(--red)}.col-failed .kanban-col-title{color:var(--red)}
  .kanban-cards{flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:6px}
  .k-card{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px 10px;font-size:11px;transition:border-color .2s}
  .k-card:hover{border-color:var(--accent)}
  .k-card.k-running{border-color:var(--orange);background:rgba(249,115,22,.05);animation:runGlow 2s infinite}
  @keyframes runGlow{0%,100%{box-shadow:0 0 0 0 rgba(249,115,22,0)}50%{box-shadow:0 0 8px 0 rgba(249,115,22,.3)}}
  .k-card .k-name{font-weight:600;margin-bottom:3px;word-break:break-all}
  .k-card .k-meta{color:var(--muted);font-size:10px;display:flex;gap:8px;flex-wrap:wrap}
  .kanban-summary{display:flex;gap:20px;margin-bottom:14px;padding:10px 14px;background:var(--surface);border:1px solid var(--border);border-radius:8px;flex-wrap:wrap}
  .ks-item{display:flex;align-items:baseline;gap:5px}.ks-num{font-size:18px;font-weight:700}.ks-label{font-size:11px;color:var(--muted)}
  .empty-col{color:var(--muted);font-size:11px;font-style:italic;padding:10px 0;text-align:center}

  /* Toni log */
  .toni-log-section{margin-top:12px}
  .toni-log{max-height:300px}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1><span class="pulse"></span>SPECTRICOM OPS</h1>
    <div class="meta">Refreshes every 3s &bull; <span id="ts">&mdash;</span></div>
  </div>
  <div class="safety">&#x1F512; AUTO_FIRE=False &bull; Approval gate active &bull; Rate limiter armed</div>
  <div class="running-banner" id="running-banner">
    <div class="running-dot"></div>
    <span>TONI EXECUTING: <span class="rb-name" id="rb-name"></span></span>
    <span class="rb-meta"><span id="rb-briefs"></span> briefs &bull; <span id="rb-elapsed"></span></span>
  </div>
  <div class="tabs">
    <div class="tab active" data-tab="monitor">Monitor</div>
    <div class="tab" data-tab="kanban">Kanban</div>
    <div class="tab" data-tab="toni">Toni Log</div>
    <div class="tab" data-tab="queue">&#x1F4E6; Queue</div>
    <div class="tab" data-tab="controls">&#x26A1; Controls</div>
  </div>

  <!-- MONITOR -->
  <div class="tab-panel active" id="tab-monitor">
    <div class="grid-3">
      <div class="card"><h2>Completed</h2><div class="stat"><span class="value pass" id="s-completed">&mdash;</span><span class="label">batches</span></div><div class="stat"><span class="value" id="s-briefs" style="font-size:16px">&mdash;</span><span class="label">briefs</span></div></div>
      <div class="card"><h2>Failed</h2><div class="stat"><span class="value fail" id="s-failed">&mdash;</span><span class="label">batches</span></div></div>
      <div class="card"><h2>Pending</h2><div class="stat"><span class="value" id="s-pending" style="color:var(--blue)">&mdash;</span><span class="label">batches</span></div></div>
    </div>
    <div class="grid">
      <div class="card">
        <h2>Rate Limits (Today)</h2>
        <div style="display:flex;justify-content:space-between;margin-bottom:4px"><span>Batches: <strong id="r-batches">&mdash;</strong></span><span id="r-batch-status" class="badge stopped">&mdash;</span></div>
        <div class="meter"><div class="fill green" id="r-batch-bar" style="width:0%"></div></div>
        <div style="display:flex;justify-content:space-between;margin-bottom:4px;margin-top:8px"><span>Briefs: <strong id="r-briefs">&mdash;</strong></span><span id="r-brief-status" class="badge stopped">&mdash;</span></div>
        <div class="meter"><div class="fill green" id="r-brief-bar" style="width:0%"></div></div>
        <div style="margin-top:10px;color:var(--muted);font-size:11px">Burn rate: <strong id="r-burn">&mdash;</strong> s/brief &bull; Duration: <strong id="r-dur">&mdash;</strong> min &bull; Lifetime: <strong id="r-lifetime">&mdash;</strong></div>
      </div>
      <div class="card">
        <h2>Daemons</h2>
        <div style="margin-bottom:10px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px"><span>Drive Bridge</span><span id="d-bridge" class="badge stopped">&mdash;</span></div>
          <div style="display:flex;justify-content:space-between;align-items:center"><span>Drive Watcher</span><span id="d-watcher" class="badge stopped">&mdash;</span></div>
        </div>
        <div class="log" id="d-bridge-log" style="max-height:100px"></div>
      </div>
    </div>
    <div class="card full" style="margin-bottom:12px"><h2>Recent Batches</h2><table class="tbl"><thead><tr><th>Batch</th><th>Status</th><th>Briefs</th><th>Duration</th><th>Time</th></tr></thead><tbody id="batch-table"></tbody></table></div>
    <div class="grid">
      <div class="card"><h2>Pending Briefs</h2><div id="pending-list" style="font-size:12px"></div></div>
      <div class="card"><h2>Orchestrator Log</h2><div class="log" id="orch-log"></div></div>
    </div>
    <div class="card full" style="margin-top:12px"><h2>Daily History</h2><table class="tbl"><thead><tr><th>Date</th><th>Batches</th><th>Briefs</th><th>Duration</th></tr></thead><tbody id="history-table"></tbody></table></div>
  </div>

  <!-- KANBAN -->
  <div class="tab-panel" id="tab-kanban">
    <div class="kanban-summary" id="kanban-summary"></div>
    <div class="kanban">
      <div class="kanban-col col-pending"><div class="kanban-col-header"><span class="kanban-col-title">&#x1F4CB; Pending</span><span class="kanban-col-count" id="kc-pending">0</span></div><div class="kanban-cards" id="kb-pending"></div></div>
      <div class="kanban-col col-running"><div class="kanban-col-header"><span class="kanban-col-title">&#x26A1; Running</span><span class="kanban-col-count" id="kc-running">0</span></div><div class="kanban-cards" id="kb-running"></div></div>
      <div class="kanban-col col-passed"><div class="kanban-col-header"><span class="kanban-col-title">&#x2705; Passed</span><span class="kanban-col-count" id="kc-passed">0</span></div><div class="kanban-cards" id="kb-passed"></div></div>
      <div class="kanban-col col-failed"><div class="kanban-col-header"><span class="kanban-col-title">&#x274C; Failed</span><span class="kanban-col-count" id="kc-failed">0</span></div><div class="kanban-cards" id="kb-failed"></div></div>
    </div>
  </div>

  <!-- QUEUE DAEMON -->
  <div class="tab-panel" id="tab-queue">
    <div id="q-banner" style="background:rgba(99,102,241,.12);border:1px solid rgba(99,102,241,.4);border-radius:6px;padding:10px 14px;margin-bottom:12px;display:flex;align-items:center;gap:10px;font-size:13px">
      <span id="q-status-dot" style="width:10px;height:10px;border-radius:50%;background:var(--muted)"></span>
      <span>Queue Daemon: <strong id="q-status-text">off</strong></span>
      <span style="color:var(--muted);margin-left:auto" id="q-consecutive"></span>
    </div>
    <div class="grid">
      <div class="card">
        <h2>Current Batch</h2>
        <div id="q-current" style="font-size:13px;color:var(--muted)">No batch running</div>
      </div>
      <div class="card">
        <h2>Queue (<span id="q-count">0</span> pending)</h2>
        <div id="q-list" style="font-size:12px;max-height:200px;overflow-y:auto"></div>
      </div>
    </div>
    <div class="grid" style="margin-top:12px">
      <div class="card">
        <h2>Controls</h2>
        <div style="display:flex;flex-direction:column;gap:8px;margin-top:4px">
          <button class="ctl-btn" data-action="queue-pause" style="background:rgba(234,179,8,.15);border:1px solid rgba(234,179,8,.4);color:#eab308">&#x23F8; Pause Queue</button>
          <button class="ctl-btn" data-action="queue-resume" style="background:rgba(34,197,94,.15);border:1px solid rgba(34,197,94,.4);color:#22c55e">&#x25B6; Resume Queue</button>
          <button class="ctl-btn" data-action="queue-cancel" style="background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.4);color:#ef4444">&#x25A0; Cancel Current</button>
          <button class="ctl-btn" data-action="queue-clear" style="background:rgba(113,113,122,.15);border:1px solid rgba(113,113,122,.4);color:#a1a1aa">&#x1F5D1; Clear Queue</button>
          <button class="ctl-btn" data-action="queue-reset" style="background:rgba(59,130,246,.15);border:1px solid rgba(59,130,246,.4);color:#3b82f6">&#x21BA; Reset Counter</button>
        </div>
      </div>
      <div class="card">
        <h2>Queue History</h2>
        <div id="q-history" style="font-size:12px;max-height:200px;overflow-y:auto"></div>
      </div>
    </div>
  </div>

  <!-- CONTROLS -->
  <div class="tab-panel" id="tab-controls">
    <div class="grid" style="margin-bottom:12px">
      <div class="card">
        <h2>Services</h2>
        <div style="display:flex;flex-direction:column;gap:8px;margin-top:4px">
          <button class="ctl-btn" data-action="restart-watcher" style="background:rgba(59,130,246,.15);border:1px solid rgba(59,130,246,.4);color:#3b82f6">&#x21BA; Restart Drive Watcher</button>
          <button class="ctl-btn" data-action="restart-bridge" style="background:rgba(59,130,246,.15);border:1px solid rgba(59,130,246,.4);color:#3b82f6">&#x21BA; Restart Drive Bridge</button>
          <button class="ctl-btn" data-action="start-all" style="background:rgba(34,197,94,.15);border:1px solid rgba(34,197,94,.4);color:#22c55e">&#x25B6; Start All Services</button>
          <button class="ctl-btn" data-action="stop-all" style="background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.4);color:#ef4444">&#x25A0; Stop All Services</button>
          <button class="ctl-btn" data-action="status-all" style="background:rgba(113,113,122,.15);border:1px solid rgba(113,113,122,.4);color:#a1a1aa">&#x2139; Service Status</button>
        </div>
      </div>
      <div class="card">
        <h2>Dev Server (localhost:5173)</h2>
        <div style="display:flex;flex-direction:column;gap:8px;margin-top:4px">
          <button class="ctl-btn" data-action="dev-server-start" style="background:rgba(34,197,94,.15);border:1px solid rgba(34,197,94,.4);color:#22c55e">&#x25B6; Start Dev Server</button>
          <button class="ctl-btn" data-action="dev-server-stop" style="background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.4);color:#ef4444">&#x25A0; Stop Dev Server</button>
          <button class="ctl-btn" data-action="dev-server-status" style="background:rgba(113,113,122,.15);border:1px solid rgba(113,113,122,.4);color:#a1a1aa">&#x2139; Dev Server Status</button>
        </div>
        <h2 style="margin-top:16px">Git</h2>
        <div style="display:flex;flex-direction:column;gap:8px;margin-top:4px">
          <button class="ctl-btn" data-action="git-status" style="background:rgba(113,113,122,.15);border:1px solid rgba(113,113,122,.4);color:#a1a1aa">&#x1F4CB; Git Status</button>
          <button class="ctl-btn" data-action="git-pull" style="background:rgba(99,102,241,.15);border:1px solid rgba(99,102,241,.4);color:#6366f1">&#x2B07; Git Pull</button>
        </div>
      </div>
    </div>
    <div class="card full">
      <h2>Output <span id="ctl-action-label" style="font-weight:400;color:var(--muted)"></span></h2>
      <div class="log" id="ctl-output" style="max-height:300px;min-height:80px"><span style="color:var(--muted)">Click a button to run a command...</span></div>
    </div>
  </div>

  <!-- TONI PROGRESS -->
  <div class="tab-panel" id="tab-toni">
    <div class="grid">
      <div class="card">
        <h2>Toni Progress</h2>
        <div id="tp-status" style="margin-bottom:10px;font-size:14px;font-weight:600;color:var(--orange)">Idle</div>
        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
          <span>Briefs: <strong id="tp-briefs">0/0</strong></span>
          <span id="tp-pct" style="color:var(--muted)">0%</span>
        </div>
        <div class="meter" style="height:10px"><div class="fill green" id="tp-bar" style="width:0%"></div></div>
        <div style="margin-top:10px;color:var(--muted);font-size:11px">
          <span id="tp-elapsed"></span>
        </div>
        <div style="margin-top:12px"><h2 style="margin-bottom:6px">Recent Commits</h2>
          <div id="tp-commits" class="log" style="max-height:150px;font-size:11px"></div>
        </div>
      </div>
      <div class="card">
        <h2>Modified Files <span id="tp-fcount" style="font-weight:400;color:var(--muted)"></span></h2>
        <div id="tp-files" class="log" style="max-height:300px;font-size:11px"></div>
      </div>
    </div>
    <div class="card full" style="margin-top:12px">
      <h2>Execution Log <span id="toni-log-file" style="font-weight:400;color:var(--muted)"></span></h2>
      <div class="log toni-log" id="toni-log" style="max-height:300px"></div>
    </div>
  </div>
</div>

<script>
document.querySelectorAll('.tab').forEach(function(t){t.addEventListener('click',function(){
  document.querySelectorAll('.tab').forEach(function(x){x.classList.remove('active')});
  document.querySelectorAll('.tab-panel').forEach(function(x){x.classList.remove('active')});
  t.classList.add('active');document.getElementById('tab-'+t.dataset.tab).classList.add('active')})});

function mc(p){return p>=100?'red':p>=80?'yellow':'green'}
function ml(p){return p>=100?'FULL':p>=80?'WARN':'OK'}
function fd(s){return s<60?s.toFixed(0)+'s':(s/60).toFixed(1)+'m'}
function ft(iso){if(!iso)return'\u2014';try{return new Date(iso).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'})}catch(e){return'\u2014'}}
function fdt(iso){if(!iso)return'';try{return new Date(iso).toLocaleDateString('en-US',{month:'short',day:'numeric'})}catch(e){return''}}
function esc(s){return(s||'').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function logCls(l){return l.indexOf('ERROR')>-1||l.indexOf('BLOCKED')>-1?'err':l.indexOf('WARNING')>-1||l.indexOf('WARN')>-1?'warn':l.indexOf('PASSED')>-1||l.indexOf('exit 0')>-1||l.indexOf('OK')>-1?'ok':''}

function renderRunning(d){
  var rb=document.getElementById('running-banner');
  if(d.running){
    rb.classList.add('active');
    document.getElementById('rb-name').textContent=d.running.batch_file;
    document.getElementById('rb-briefs').textContent=d.running.briefs;
    document.getElementById('rb-elapsed').textContent=d.running.elapsed_fmt;
  }else{rb.classList.remove('active')}
}

function renderMonitor(d){
  var st=d.state.totals;
  document.getElementById('s-completed').textContent=st.completed;
  document.getElementById('s-failed').textContent=st.failed;
  document.getElementById('s-pending').textContent=st.pending;
  document.getElementById('s-briefs').textContent=st.total_briefs+' briefs / '+fd(st.total_duration_s);
  var r=d.rate;
  document.getElementById('r-batches').textContent=r.today.batches+'/'+r.caps.daily_batches;
  document.getElementById('r-briefs').textContent=r.today.briefs+'/'+r.caps.daily_briefs;
  var bb=document.getElementById('r-batch-bar');bb.style.width=Math.min(r.batch_pct,100)+'%';bb.className='fill '+mc(r.batch_pct);
  var fb=document.getElementById('r-brief-bar');fb.style.width=Math.min(r.brief_pct,100)+'%';fb.className='fill '+mc(r.brief_pct);
  var bbs=document.getElementById('r-batch-status');bbs.textContent=ml(r.batch_pct);bbs.className='badge '+(r.batch_pct>=100?'dead':r.batch_pct>=80?'stopped':'running');
  var fbs=document.getElementById('r-brief-status');fbs.textContent=ml(r.brief_pct);fbs.className='badge '+(r.brief_pct>=100?'dead':r.brief_pct>=80?'stopped':'running');
  document.getElementById('r-burn').textContent=r.burn_rate_s_per_brief||'\u2014';
  document.getElementById('r-dur').textContent=(r.today.duration_s/60).toFixed(1);
  document.getElementById('r-lifetime').textContent=r.lifetime.batches+'b / '+r.lifetime.briefs+'br / '+(r.lifetime.total_duration_s/3600).toFixed(1)+'h';
  function setD(id,dm){var el=document.getElementById(id);el.textContent=dm.status+(dm.pid?' ('+dm.pid+')':'');el.className='badge '+dm.status}
  setD('d-bridge',d.daemons.bridge);setD('d-watcher',d.daemons.watcher);
  document.getElementById('d-bridge-log').innerHTML=(d.daemons.bridge.recent_log||[]).map(function(l){return'<div class="line '+logCls(l)+'">'+esc(l)+'</div>'}).join('');
  var all=d.state.completed.map(function(b){return Object.assign({},b,{_s:'pass'})}).concat(d.state.failed.map(function(b){return Object.assign({},b,{_s:'fail'})})).sort(function(a,b){return(b.finished||'').localeCompare(a.finished||'')}).slice(0,15);
  document.getElementById('batch-table').innerHTML=all.map(function(b){return'<tr><td>'+esc(b.batch_file)+'</td><td class="'+(b._s==='pass'?'pass':'fail')+'">'+(b._s==='pass'?'&#x2705; PASSED':'&#x274C; FAILED')+'</td><td>'+(b.briefs||'?')+'</td><td>'+fd(b.duration_s||0)+'</td><td>'+ft(b.finished)+'</td></tr>'}).join('');
  document.getElementById('pending-list').innerHTML=d.state.pending.length===0?'<span style="color:var(--muted)">No pending briefs</span>':d.state.pending.map(function(p){return'<div style="padding:3px 0">&#x1F4CB; '+esc(p.name)+'</div>'}).join('');
  var ol=document.getElementById('orch-log');ol.innerHTML=(d.logs.lines||[]).map(function(l){return'<div class="line '+logCls(l)+'">'+esc(l)+'</div>'}).join('');ol.scrollTop=ol.scrollHeight;
  document.getElementById('history-table').innerHTML=(d.rate.history||[]).map(function(h){return'<tr><td>'+h.date+'</td><td>'+h.batches+'</td><td>'+h.briefs+'</td><td>'+h.duration_min+'m</td></tr>'}).join('')||'<tr><td colspan="4" style="color:var(--muted)">No history yet</td></tr>';
}

function renderKanban(d){
  var completed=d.state.completed||[],failed=d.state.failed||[],pending=d.state.pending||[];
  var running=d.running;

  // Filter running batch from pending
  var runName=running?running.batch_file:'';
  var filteredPending=pending.filter(function(p){return p.name!==runName});

  function mkCard(item,type){
    var name=item.batch_file||item.name||'?',meta='',cls='k-card';
    if(type==='running'){
      cls+=' k-running';
      meta='<span>'+item.briefs+' briefs</span><span style="color:var(--orange)">'+item.elapsed_fmt+'</span>';
      name=item.batch_file;
    }else if(type==='passed'||type==='failed'){
      meta='<span>'+(item.briefs||'?')+' briefs</span>';
      if(item.duration_s)meta+='<span>'+fd(item.duration_s)+'</span>';
      var dt=fdt(item.finished);if(dt)meta+='<span>'+dt+'</span>';
      var tm=ft(item.finished);if(tm&&tm!=='\u2014')meta+='<span>'+tm+'</span>';
      if(item.exit_code&&item.exit_code!==0)meta+='<span style="color:var(--red)">exit '+item.exit_code+'</span>';
    }else{var m=fdt(item.modified);if(m)meta='<span>'+m+'</span>'}
    return'<div class="'+cls+'"><div class="k-name">'+esc(name)+'</div>'+(meta?'<div class="k-meta">'+meta+'</div>':'')+'</div>'
  }

  document.getElementById('kb-pending').innerHTML=filteredPending.map(function(p){return mkCard(p,'pending')}).join('')||'<div class="empty-col">No pending batches</div>';
  document.getElementById('kb-running').innerHTML=running?mkCard(running,'running'):'<div class="empty-col">Nothing running</div>';
  document.getElementById('kb-passed').innerHTML=completed.slice().reverse().map(function(c){return mkCard(c,'passed')}).join('');
  document.getElementById('kb-failed').innerHTML=failed.slice().reverse().map(function(f){return mkCard(f,'failed')}).join('');
  document.getElementById('kc-pending').textContent=filteredPending.length;
  document.getElementById('kc-running').textContent=running?'1':'0';
  document.getElementById('kc-passed').textContent=completed.length;
  document.getElementById('kc-failed').textContent=failed.length;

  var total=filteredPending.length+(running?1:0)+completed.length+failed.length;
  var denom=completed.length+failed.length;
  var pr=denom>0?Math.round(completed.length/denom*100):0;
  document.getElementById('kanban-summary').innerHTML=
    '<div class="ks-item"><span class="ks-num" style="color:var(--text)">'+total+'</span><span class="ks-label">total</span></div>'+
    '<div class="ks-item"><span class="ks-num" style="color:var(--blue)">'+filteredPending.length+'</span><span class="ks-label">pending</span></div>'+
    (running?'<div class="ks-item"><span class="ks-num" style="color:var(--orange)">1</span><span class="ks-label">running</span></div>':'')+
    '<div class="ks-item"><span class="ks-num" style="color:var(--green)">'+completed.length+'</span><span class="ks-label">passed</span></div>'+
    '<div class="ks-item"><span class="ks-num" style="color:var(--red)">'+failed.length+'</span><span class="ks-label">failed</span></div>'+
    '<div class="ks-item"><span class="ks-num" style="color:var(--accent)">'+pr+'%</span><span class="ks-label">pass rate</span></div>';
}

function renderToniLog(d){
  // Queue tab
  var q=d.queue||{};
  var qs=q.daemon_status||'off';
  var dot=document.getElementById('q-status-dot');
  var stColors={running:'var(--green)',paused:'var(--yellow)',idle:'var(--blue)',off:'var(--muted)',stopped:'var(--red)'};
  dot.style.background=stColors[qs]||'var(--muted)';
  if(qs==='running')dot.style.animation='pulse 2s infinite';else dot.style.animation='none';
  document.getElementById('q-status-text').textContent=qs.toUpperCase();
  document.getElementById('q-consecutive').textContent=qs!=='off'?'Consecutive: '+q.consecutive_count+'/'+q.config.max_consecutive:'';
  document.getElementById('q-count').textContent=q.queue_count||0;
  var cur=q.current_batch;
  if(cur){
    document.getElementById('q-current').innerHTML='<div style="color:var(--orange);font-weight:600">'+esc(cur.file)+'</div><div style="color:var(--muted);margin-top:4px">Running '+(q.current_elapsed_fmt||'...')+'</div>';
  }else{
    document.getElementById('q-current').innerHTML='<span style="color:var(--muted)">No batch running</span>';
  }
  var ql=q.queue||[];
  document.getElementById('q-list').innerHTML=ql.length===0?'<span style="color:var(--muted)">Queue empty</span>':ql.map(function(f,i){return'<div style="padding:3px 0">'+(i+1)+'. '+esc(f.name)+'</div>'}).join('');
  var qh=(q.completed||[]).concat(q.failed||[]).sort(function(a,b){return(b.finished_at||'').localeCompare(a.finished_at||'')}).slice(0,10);
  document.getElementById('q-history').innerHTML=qh.length===0?'<span style="color:var(--muted)">No history</span>':qh.map(function(h){var ok=h.exit_code===0;return'<div style="padding:3px 0"><span class="'+(ok?'pass':'fail')+'">'+(ok?'\u2705':'\u274C')+'</span> '+esc(h.file)+' <span style="color:var(--muted)">'+fd(h.duration_s||0)+'</span></div>'}).join('');
  // Original Toni log rendering below
  var tl=d.toni_log||{};
  var fl=document.getElementById('toni-log-file');
  fl.textContent=tl.file?(tl.active?' (LIVE) ':'  ')+tl.file:'';
  if(tl.active)fl.style.color='var(--orange)';else fl.style.color='var(--muted)';
  var el=document.getElementById('toni-log');
  el.innerHTML=(tl.lines||[]).map(function(l){return'<div class="line '+logCls(l)+'">'+esc(l)+'</div>'}).join('');
  el.scrollTop=el.scrollHeight;

  // Git progress
  var gp=d.git_progress||{};
  var st=document.getElementById('tp-status');
  if(gp.active){
    st.textContent=gp.current_brief||'Working...';
    st.style.color='var(--orange)';
    document.getElementById('tp-briefs').textContent=gp.commit_count+'/'+gp.expected_briefs;
    document.getElementById('tp-pct').textContent=gp.progress_pct+'%';
    var bar=document.getElementById('tp-bar');
    bar.style.width=gp.progress_pct+'%';
    bar.className='fill '+(gp.progress_pct>=100?'green':gp.progress_pct>=50?'yellow':'green');
    document.getElementById('tp-elapsed').textContent='Elapsed: '+gp.elapsed+' \u2022 '+gp.modified_count+' files modified';
  }else{
    st.textContent='Idle \u2014 no batch running';
    st.style.color='var(--muted)';
    document.getElementById('tp-briefs').textContent='\u2014';
    document.getElementById('tp-pct').textContent='';
    document.getElementById('tp-bar').style.width='0%';
    document.getElementById('tp-elapsed').textContent='';
  }

  // Commits
  var ce=document.getElementById('tp-commits');
  var commits=gp.commits_since_start||[];
  if(commits.length>0){
    ce.innerHTML=commits.map(function(c){return'<div class="line ok">'+esc(c)+'</div>'}).join('');
  }else{
    ce.innerHTML='<div class="line" style="color:var(--muted)">'+(gp.active?'No commits yet \u2014 Toni is working...':'No recent activity')+'</div>';
  }

  // Files
  var fe=document.getElementById('tp-files');
  var files=gp.modified_files||[];
  document.getElementById('tp-fcount').textContent=files.length>0?'('+gp.modified_count+')':'';
  if(files.length>0){
    fe.innerHTML=files.map(function(f){
      var cls=f.endsWith('.tsx')||f.endsWith('.ts')?'ok':f.endsWith('.sql')?'warn':'';
      return'<div class="line '+cls+'">'+esc(f)+'</div>'}).join('');
  }else{
    fe.innerHTML='<div class="line" style="color:var(--muted)">'+(gp.active?'No changes yet...':'No uncommitted changes')+'</div>';
  }
}

async function poll(){
  try{
    var r=await fetch('/api/all');
    if(r.ok){var d=await r.json();document.getElementById('ts').textContent=new Date().toLocaleTimeString();
    renderRunning(d);renderMonitor(d);renderKanban(d);renderToniLog(d)}
  }catch(e){console.error('Poll:',e)}
}
poll();setInterval(poll,3000);

// Controls
document.querySelectorAll('.ctl-btn').forEach(function(btn){
  btn.style.cssText += ';padding:10px 14px;border-radius:6px;font-family:inherit;font-size:13px;font-weight:600;cursor:pointer;text-align:left;transition:.15s;';
  btn.addEventListener('mouseenter',function(){this.style.opacity='.8'});
  btn.addEventListener('mouseleave',function(){this.style.opacity='1'});
  btn.addEventListener('click',function(){
    var action=this.dataset.action,label=this.textContent;
    var out=document.getElementById('ctl-output');
    document.getElementById('ctl-action-label').textContent='— '+label;
    out.innerHTML='<span style="color:var(--yellow)">&#x23F3; Running...</span>';
    fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:action})})
      .then(function(r){return r.json()})
      .then(function(d){
        var cls=d.ok?'ok':'err';
        var lines=[];
        if(d.stdout)lines.push(esc(d.stdout));
        if(d.stderr)lines.push('<span style="color:var(--red)">STDERR: '+esc(d.stderr)+'</span>');
        if(d.error)lines.push('<span style="color:var(--red)">ERROR: '+esc(d.error)+'</span>');
        if(!lines.length)lines.push(d.ok?'&#x2705; Done':'&#x274C; Failed (exit '+d.returncode+')');
        out.innerHTML='<div class="line '+cls+'">'+lines.join('<br>')+'</div>';
      })
      .catch(function(e){out.innerHTML='<div class="line err">Fetch error: '+esc(String(e))+'</div>'});
  });
});
</script>
</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self,f,*a):pass
    def respond(self,c,ct,b):
        try:
            self.send_response(c);self.send_header("Content-Type",ct);self.send_header("Access-Control-Allow-Origin","*");self.end_headers()
            self.wfile.write(b.encode("utf-8") if isinstance(b,str) else b)
        except BrokenPipeError:
            pass
    def do_POST(self):
        p = urlparse(self.path)
        if p.path == "/api/action":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length > 0 else {}
                action_id = body.get("action", "")
                result = run_action(action_id)
                self.respond(200, "application/json", json.dumps(result))
            except Exception as e:
                self.respond(400, "application/json", json.dumps({"ok": False, "error": str(e)}))
        else:
            self.respond(404, "text/plain", "Not found")

    def do_GET(self):
        p=urlparse(self.path)
        if p.path in ("/","/dashboard"): self.respond(200,"text/html",DASHBOARD_HTML)
        elif p.path=="/api/all": self.respond(200,"application/json",json.dumps(get_all(),default=str))
        elif p.path=="/api/toni-log":
            qs=parse_qs(p.query);n=int(qs.get("n",[80])[0])
            self.respond(200,"application/json",json.dumps(get_toni_log(n),default=str))
        elif p.path=="/api/state": self.respond(200,"application/json",json.dumps(get_state(),default=str))
        elif p.path=="/api/rate": self.respond(200,"application/json",json.dumps(get_rate(),default=str))
        elif p.path=="/api/daemons": self.respond(200,"application/json",json.dumps(get_daemons(),default=str))
        elif p.path=="/api/running": self.respond(200,"application/json",json.dumps(get_running(),default=str))
        elif p.path=="/api/queue": self.respond(200,"application/json",json.dumps(_daemon.get_status() if _daemon else {"daemon_status":"off"},default=str))
        elif p.path=="/api/git-progress": self.respond(200,"application/json",json.dumps(get_git_progress(),default=str))
        elif p.path=="/api/git-progress": self.respond(200,"application/json",json.dumps(get_git_progress(),default=str))
        else: self.respond(404,"text/plain","Not found")

def main():
    global _daemon
    ap=argparse.ArgumentParser(description="Spectricom Ops Dashboard v5")
    ap.add_argument("--port",type=int,default=DEFAULT_PORT)
    ap.add_argument("--daemon",action="store_true",help="Start queue daemon background thread")
    args=ap.parse_args()
    if args.daemon:
        if QueueDaemon is None:
            print("ERROR: queue_daemon.py not found. Place it in the same directory.")
            sys.exit(1)
        _daemon = QueueDaemon()
        start_daemon_thread(_daemon)
        print(f"  Queue daemon: STARTED (watching queue/)")
    server=HTTPServer(("0.0.0.0",args.port),Handler)
    print("="*39);print(f"  SPECTRICOM OPS DASHBOARD v5");print(f"  http://localhost:{args.port}")
    print(f"  Tabs: Monitor | Kanban | Toni Log | Queue | Controls")
    print(f"  Queue daemon: {'ON' if args.daemon else 'OFF (use --daemon)'}");print(f"  Refresh: 3s");print(f"  Ctrl+C to stop");print("="*39)
    try:server.serve_forever()
    except KeyboardInterrupt:print("\nStopped.");server.server_close()

if __name__=="__main__":main()
