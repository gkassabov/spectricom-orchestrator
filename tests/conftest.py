"""Suite-wide isolation for ORCH-CAPACITY-1 (S7-CORE-21).

admission.py reads two things a test must never inherit from the machine it runs on: /proc/meminfo, and the
live routes in an orchestrator dir. Every test reads a meminfo with memory to spare. A test that calls
orchestrator.main() for `run` without asking about admission gets admit_run's yes. Those tests patch
run_batch and leave orchestrator.ORCH_DIR as it is; run from ~/spectricom-orchestrator, the real admit_run
would count the live routes there and claim beside them. tests/test_capacity.py opts out with
@pytest.mark.admission and sets up both itself.

ORCH-TONI-GUARDS-1 (S7-CORE-33): fire_toni adds `--settings executor/settings/<repo>.json` and scrubs the env, and
refuses when the active repo has no settings file. The tests that call the real fire_toni were written against the
unguarded fire and most name no repo, so every test fires with TONI_GUARDS=off (HEAD's fire, byte-for-byte) unless
it is marked @pytest.mark.guards, as tests/test_toni_guards.py is.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import admission  # noqa: E402

PLENTY = "MemTotal:       67108864 kB\nMemAvailable:   67108864 kB\n"   # 64 GiB available


def pytest_configure(config):
    config.addinivalue_line("markers", "admission: the test sets up admission's meminfo and markers itself")
    config.addinivalue_line("markers", "guards: the test fires with ORCH-TONI-GUARDS-1's guards as configured")


@pytest.fixture(autouse=True)
def _admission_isolated(request, tmp_path_factory, monkeypatch):
    if request.node.get_closest_marker("admission"):
        return
    meminfo = tmp_path_factory.mktemp("meminfo") / "meminfo"
    meminfo.write_text(PLENTY)
    monkeypatch.setattr(admission, "MEMINFO", meminfo)
    monkeypatch.setattr(admission, "admit_run",
                        lambda repo, batch, **kw: (True, f"admitted {repo} (tests: admission isolated by conftest)"))


@pytest.fixture(autouse=True)
def _toni_guards_off(request, monkeypatch):
    if request.node.get_closest_marker("guards"):
        return
    monkeypatch.setenv("TONI_GUARDS", "off")
