# filename: repo_config.py
"""Lightweight repo config loader for helper scripts (OI-026 A7)."""
from pathlib import Path
import yaml

# ORCH-YORSIE-SAFETY-1 (S7-CORE-17): repos.yaml names no default repo — a brief names its repo or is
# refused. The helper scripts that import this at module load (orch-dashboard.py, drive-sync.py,
# drive-bridge.py, patch-dashboard-progress.py) list and pull Yorsie's briefs (Drive/Yorsie/Briefs/);
# they keep Yorsie BY NAME here, not through a `default:` flag. None of them decides where a brief
# fires: drive-bridge fires through orchestrator.py, which refuses a brief that names no repo.
HELPER_REPO = "yorsie"


def load_repo_config(name: str) -> dict:
    """The entry for `name` in config/repos.yaml; RuntimeError if it is not declared there."""
    cfg_path = Path(__file__).resolve().parent / "config" / "repos.yaml"
    if not cfg_path.exists():
        cfg_path = Path.home() / "spectricom-orchestrator" / "config" / "repos.yaml"
    repos = yaml.safe_load(cfg_path.read_text())["repos"]
    if name not in repos:
        raise RuntimeError(f"Unknown repo: {name}. Valid: {', '.join(sorted(repos))}")
    return repos[name]


def load_default_repo_config():
    """The helpers' entry point, kept under its old name: (HELPER_REPO, its config) — named."""
    return HELPER_REPO, load_repo_config(HELPER_REPO)
