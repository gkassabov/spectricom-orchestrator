#!/usr/bin/env python3
"""
Patch orch-dashboard.py to add git-based Toni progress tracking.
Adds /api/git-progress endpoint and updates Toni Log tab with live progress.
"""
from pathlib import Path

ORCH = Path.home() / "spectricom-orchestrator"
DASH = ORCH / "orch-dashboard.py"

# Read current dashboard
content = DASH.read_text()

# ═══════════════════════════════════════════════════════
# 1. Add git progress function after get_toni_log
# ═══════════════════════════════════════════════════════
git_progress_func = '''
def get_git_progress():
    """Get live git activity from the project repo during Toni execution."""
    import subprocess
    PROJECT = Path.home() / "spectricom-dev-pipeline"
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
                result["commits_since_start"] = [l.strip() for l in r.stdout.strip().split("\\n") if l.strip()]
        except: pass
        return result

    start_time = running.get("started", "")

    # Recent commits since batch started
    try:
        cmd = f'git log --oneline --since="{start_time}"'
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=str(PROJECT), timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            commits = [l.strip() for l in r.stdout.strip().split("\\n") if l.strip()]
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
            files = [f.strip() for f in r.stdout.strip().split("\\n") if f.strip()]
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
            result["staged_files"] = [f.strip() for f in r.stdout.strip().split("\\n") if f.strip()]
    except: pass

    # New untracked files
    try:
        r = subprocess.run(
            "git ls-files --others --exclude-standard",
            shell=True, capture_output=True, text=True, cwd=str(PROJECT), timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            new_files = [f.strip() for f in r.stdout.strip().split("\\n") if f.strip() and not f.startswith("yorsie/test-results")]
            result["modified_files"] = list(set(result["modified_files"] + new_files))[-20:]
            result["modified_count"] = len(set(result.get("modified_files", []) + new_files))
    except: pass

    # Progress percentage
    expected = result["expected_briefs"]
    if expected > 0 and result["commit_count"] > 0:
        result["progress_pct"] = min(100, round(result["commit_count"] / expected * 100))
    elif result["modified_count"] > 0:
        result["progress_pct"] = 10  # at least started

    # Infer current state
    if result["commit_count"] >= expected and expected > 0:
        result["current_brief"] = "Finishing up..."
    elif result["commit_count"] == 0 and result["modified_count"] > 0:
        result["current_brief"] = f"Working on brief 1/{expected}... ({result['modified_count']} files changed)"
    elif result["commit_count"] > 0:
        result["current_brief"] = f"Brief {result['commit_count']}/{expected} committed. Working on next..."

    return result
'''

# Insert after get_toni_log function
content = content.replace(
    'def get_all():',
    git_progress_func + '\ndef get_all():'
)

# ═══════════════════════════════════════════════════════
# 2. Add git_progress to get_all() response
# ═══════════════════════════════════════════════════════
content = content.replace(
    '"running":running,"timestamp":datetime.now().isoformat(),"auto_fire":False',
    '"running":running,"git_progress":get_git_progress(),"timestamp":datetime.now().isoformat(),"auto_fire":False'
)

# ═══════════════════════════════════════════════════════
# 3. Add /api/git-progress endpoint
# ═══════════════════════════════════════════════════════
content = content.replace(
    'elif p.path=="/api/running": self.respond(200,"application/json",json.dumps(get_running(),default=str))',
    'elif p.path=="/api/running": self.respond(200,"application/json",json.dumps(get_running(),default=str))\n'
    '        elif p.path=="/api/git-progress": self.respond(200,"application/json",json.dumps(get_git_progress(),default=str))'
)

# ═══════════════════════════════════════════════════════
# 4. Replace Toni Log tab HTML with progress panel
# ═══════════════════════════════════════════════════════
old_toni_tab = '''  <!-- TONI LOG -->
  <div class="tab-panel" id="tab-toni">
    <div class="card full">
      <h2>Toni Execution Log <span id="toni-log-file" style="font-weight:400;color:var(--muted)"></span></h2>
      <div class="log toni-log" id="toni-log" style="max-height:500px"></div>
    </div>
  </div>'''

new_toni_tab = '''  <!-- TONI PROGRESS -->
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
  </div>'''

content = content.replace(old_toni_tab, new_toni_tab)

# ═══════════════════════════════════════════════════════
# 5. Replace renderToniLog with renderToniProgress
# ═══════════════════════════════════════════════════════
old_render = '''function renderToniLog(d){
  var tl=d.toni_log||{};
  var fl=document.getElementById('toni-log-file');
  fl.textContent=tl.file?(tl.active?' (LIVE) ':'  ')+tl.file:'';
  if(tl.active)fl.style.color='var(--orange)';else fl.style.color='var(--muted)';
  var el=document.getElementById('toni-log');
  el.innerHTML=(tl.lines||[]).map(function(l){return'<div class="line '+logCls(l)+'">'+esc(l)+'</div>'}).join('');
  el.scrollTop=el.scrollHeight;
}'''

new_render = '''function renderToniLog(d){
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
    document.getElementById('tp-elapsed').textContent='Elapsed: '+gp.elapsed+' \\u2022 '+gp.modified_count+' files modified';
  }else{
    st.textContent='Idle \\u2014 no batch running';
    st.style.color='var(--muted)';
    document.getElementById('tp-briefs').textContent='\\u2014';
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
    ce.innerHTML='<div class="line" style="color:var(--muted)">'+(gp.active?'No commits yet \\u2014 Toni is working...':'No recent activity')+'</div>';
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
}'''

content = content.replace(old_render, new_render)

# Write back
DASH.write_text(content)
print("✅ Dashboard patched with git progress tracking")
print("   Added: /api/git-progress endpoint")
print("   Added: Toni Progress panel (commits, files, progress bar)")
print("   Restart dashboard to apply: pkill -f orch-dashboard; python3 orch-dashboard.py")
