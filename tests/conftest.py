"""Suite-wide isolation for ORCH-CAPACITY-1 (S7-CORE-21).

admission.py reads two things a test must never inherit from the machine it runs on: /proc/meminfo, and the
live routes in an orchestrator dir. Every test reads a meminfo with memory to spare. A test that calls
orchestrator.main() for `run` without asking about admission gets admit_run's yes. Those tests patch
run_batch and leave orchestrator.ORCH_DIR as it is; run from ~/spectricom-orchestrator, the real admit_run
would count the live routes there and claim beside them. tests/test_capacity.py opts out with
@pytest.mark.admission and sets up both itself.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import admission  # noqa: E402

PLENTY = "MemTotal:       67108864 kB\nMemAvailable:   67108864 kB\n"   # 64 GiB available


def pytest_configure(config):
    config.addinivalue_line("markers", "admission: the test sets up admission's meminfo and markers itself")


@pytest.fixture(autouse=True)
def _admission_isolated(request, tmp_path_factory, monkeypatch):
    if request.node.get_closest_marker("admission"):
        return
    meminfo = tmp_path_factory.mktemp("meminfo") / "meminfo"
    meminfo.write_text(PLENTY)
    monkeypatch.setattr(admission, "MEMINFO", meminfo)
    monkeypatch.setattr(admission, "admit_run",
                        lambda repo, batch, **kw: (True, f"admitted {repo} (tests: admission isolated by conftest)"))
