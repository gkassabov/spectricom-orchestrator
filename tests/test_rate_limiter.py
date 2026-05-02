# filename: tests/test_rate_limiter.py
"""Tests for A60 — pre_flight() rate-cap gating on ANTHROPIC_API_KEY presence."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import rate_limiter


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path):
    """Point rate_limiter at temp files so tests don't touch real state."""
    caps = {"daily_batches": 15, "daily_briefs": 60}
    caps_file = tmp_path / "rate-caps.json"
    caps_file.write_text(json.dumps(caps))

    state = {
        "daily": {
            rate_limiter.today_key(): {
                "batches": 20,
                "briefs": 50,
                "duration_s": 0,
                "executions": [],
            }
        },
        "lifetime": {"batches": 20, "briefs": 50, "total_duration_s": 0},
    }
    rate_file = tmp_path / "rate-limits.json"
    rate_file.write_text(json.dumps(state))

    with patch.object(rate_limiter, "CAPS_FILE", caps_file), \
         patch.object(rate_limiter, "RATE_FILE", rate_file):
        yield


def test_preflight_skips_cap_in_cli_mode():
    """ANTHROPIC_API_KEY unset, count above cap -> returns clean."""
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    with patch.dict(os.environ, env, clear=True):
        allowed, msg = rate_limiter.pre_flight(5)
    assert allowed is True
    assert "cli-mode-no-cap" in msg


def test_preflight_enforces_cap_in_api_mode():
    """ANTHROPIC_API_KEY=fake, count above cap -> returns blocked."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
        allowed, msg = rate_limiter.pre_flight(5)
    assert allowed is False
    assert "BLOCKED" in msg


def test_preflight_enforces_cap_in_api_mode_below_threshold():
    """Key set, count below cap -> returns clean."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
        with patch.object(rate_limiter, "RATE_FILE") as mock_rf:
            state = {
                "daily": {
                    rate_limiter.today_key(): {
                        "batches": 2,
                        "briefs": 5,
                        "duration_s": 0,
                        "executions": [],
                    }
                },
                "lifetime": {"batches": 2, "briefs": 5, "total_duration_s": 0},
            }
            tmp = Path(tempfile.mktemp(suffix=".json"))
            tmp.write_text(json.dumps(state))
            with patch.object(rate_limiter, "RATE_FILE", tmp):
                allowed, msg = rate_limiter.pre_flight(3)
            tmp.unlink(missing_ok=True)
    assert allowed is True
    assert "Rate OK" in msg
