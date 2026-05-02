# filename: tests/test_timeout_resolution.py
"""Tests for A62 — brief-declared TONI_TIMEOUT_MIN advisory + precedence chain."""

import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

with patch.dict("sys.modules", {"yaml": MagicMock()}):
    pass

from orchestrator import parse_brief_timeout, resolve_timeout, TIMEOUT_DEFAULT_MIN


def _write_brief(tmp_path: Path, content: str) -> Path:
    f = tmp_path / "test-brief.md"
    f.write_text(content, encoding="utf-8")
    return f


class TestParseBriefTimeout:

    def test_header_pattern(self, tmp_path):
        f = _write_brief(tmp_path, "## TONI_TIMEOUT_MIN: 60\n## Other stuff\n")
        assert parse_brief_timeout(f) == 60

    def test_fire_mechanism_pattern(self, tmp_path):
        f = _write_brief(
            tmp_path,
            "## Fire mechanism: orchestrator with TONI_TIMEOUT_MIN=90 --repo foo\n",
        )
        assert parse_brief_timeout(f) == 90

    def test_estimated_runtime_range(self, tmp_path):
        f = _write_brief(tmp_path, "## Estimated runtime: 30-40m total\n")
        assert parse_brief_timeout(f) == 50  # 40 * 1.25

    def test_estimated_runtime_single(self, tmp_path):
        f = _write_brief(tmp_path, "## Estimated runtime: 20m\n")
        assert parse_brief_timeout(f) == 25  # 20 * 1.25

    def test_no_timeout_declared(self, tmp_path):
        f = _write_brief(tmp_path, "# Just a title\nSome content\n")
        assert parse_brief_timeout(f) is None


class TestResolveTimeout:

    def test_timeout_env_var_wins_over_brief(self, tmp_path):
        f = _write_brief(tmp_path, "## TONI_TIMEOUT_MIN: 60\n")
        with patch.dict(os.environ, {"TONI_TIMEOUT_MIN": "120"}):
            timeout, source = resolve_timeout(f)
        assert timeout == 120
        assert source == "env-var"

    def test_timeout_brief_wins_over_default(self, tmp_path):
        f = _write_brief(tmp_path, "## TONI_TIMEOUT_MIN: 60\n")
        env = os.environ.copy()
        env.pop("TONI_TIMEOUT_MIN", None)
        with patch.dict(os.environ, env, clear=True):
            timeout, source = resolve_timeout(f)
        assert timeout == 60
        assert source == "brief-declared"

    def test_timeout_default_when_neither(self, tmp_path):
        f = _write_brief(tmp_path, "# No timeout info\n")
        env = os.environ.copy()
        env.pop("TONI_TIMEOUT_MIN", None)
        with patch.dict(os.environ, env, clear=True):
            timeout, source = resolve_timeout(f)
        assert timeout == TIMEOUT_DEFAULT_MIN
        assert source == "default"

    def test_timeout_hard_cap_at_180(self, tmp_path, caplog):
        f = _write_brief(tmp_path, "## TONI_TIMEOUT_MIN: 240\n")
        env = os.environ.copy()
        env.pop("TONI_TIMEOUT_MIN", None)
        with patch.dict(os.environ, env, clear=True):
            with caplog.at_level(logging.WARNING, logger="orch"):
                timeout, source = resolve_timeout(f)
        assert timeout == 180
        assert source == "brief-declared"
        assert any("hard cap" in r.message for r in caplog.records)
