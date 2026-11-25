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

ORCH-EXECUTOR-AUTH-PROBE-1 (S7-CORE-51): the daemon and run_batch ask executor_auth.probe() whether the executor is
logged in, and the real probe calls the claude CLI. Every test sees a stubbed ok unless it is marked
@pytest.mark.executor_auth (tests/test_executor_auth.py stubs subprocess itself); EXECUTOR_AUTH_CHECKED and
EXECUTOR_AUTH_PROBE are always removed, so a value inherited from a daemon-spawned gate or a shell never reaches a test.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import admission  # noqa: E402
import executor_auth  # noqa: E402

PLENTY = "MemTotal:       67108864 kB\nMemAvailable:   67108864 kB\n"   # 64 GiB available


def pytest_configure(config):
    config.addinivalue_line("markers", "admission: the test sets up admission's meminfo and markers itself")
    config.addinivalue_line("markers", "guards: the test fires with ORCH-TONI-GUARDS-1's guards as configured")
    config.addinivalue_line("markers", "executor_auth: the test runs executor_auth.probe itself (subprocess stubbed)")
    config.addinivalue_line("markers", "self_merge: the test runs the daemon's DEMOTION-SELF-MERGE check (937)")


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


@pytest.fixture(autouse=True)
def _executor_auth_ok(request, monkeypatch):
    monkeypatch.delenv(executor_auth.CHECKED_VAR, raising=False)
    monkeypatch.delenv(executor_auth.PROBE_VAR, raising=False)
    if request.node.get_closest_marker("executor_auth"):
        return
    monkeypatch.setattr(executor_auth, "probe", lambda *a, **k: executor_auth.AuthProbe(
        True, "ok", "logged in (tests: stubbed by conftest)", None))


@pytest.fixture(autouse=True)
def _self_merge_off(request, monkeypatch):
    """DEMOTION-SELF-MERGE-DETECT-1 (S7-CORE-62, route 937): before each fire the daemon reads the brief's repo's
    merge target and live checkout. A fire-loop test names a real repo from config/repos.yaml and must not judge
    the live checkout it happens to run beside: off unless the test is marked @pytest.mark.self_merge."""
    if request.node.get_closest_marker("self_merge"):
        monkeypatch.delenv("ORCH_SELF_MERGE", raising=False)
        return
    monkeypatch.setenv("ORCH_SELF_MERGE", "off")


@pytest.fixture(autouse=True)
def _ledger_isolated(tmp_path_factory, monkeypatch):
    """ORCH-LEDGER-CHAIN-1 (S7-CORE-57, route 623): every gate verdict, hold, merge, kill, unkill, override and
    release appends to logs/ledger.jsonl. No test may append to the ledger of the checkout it runs in (the live one,
    when the suite runs from ~/spectricom-orchestrator): every test writes to its own temporary ledger dir."""
    monkeypatch.setenv("SPECTRICOM_LEDGER_DIR", str(tmp_path_factory.mktemp("ledger")))
