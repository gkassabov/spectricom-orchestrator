# filename: repo_config.py
"""Lightweight repo config loader for helper scripts (OI-026 A7)."""
from pathlib import Path
import yaml


def load_default_repo_config():
    """Load repos.yaml and return (name, config_dict) for the default repo."""
    cfg_path = Path(__file__).resolve().parent / "config" / "repos.yaml"
    if not cfg_path.exists():
        cfg_path = Path.home() / "spectricom-orchestrator" / "config" / "repos.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    for name, r in cfg["repos"].items():
        if r.get("default"):
            return name, r
    raise RuntimeError("No default repo declared in config/repos.yaml")
