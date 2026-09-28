# filename: tests/test_bg_ceiling.py
"""Tests for TONI-BG-CEILING-1 — a wait that cannot outlive its route.

S7-CORE-15 · [TONI-BG-CEILING-1], the prevention half of [TONI-BACKGROUND-EXIT]. The `claude`
CLI stops waiting on the executor's background work at CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS
(600 s by default), kills it and exits 0. fire_toni now sets that ceiling in the child's
environment, bounded strictly below the route's own timeout, and never to 0.

  R1  the child sees the bounded ceiling; the parent has none           (red at the merge-base)
  R2  an inherited value — `0` included — is overridden, not inherited  (red at the merge-base)
  R3  source guard: the spawn passes `env=`                             (red at the merge-base)
  G1  check_bg_ceiling_invariants: one case per reason, and the order
  G2  the bound, over the brief's §2.2 table
  G3  toni_child_env hygiene
  G4  an invalid route timeout is refused, never spawned
  G5  source guard: the executor spawn set S is exactly one site       (green at the merge-base)
  G6  reachability: fire_toni calls the predicate exactly once, with what it spawns
  G7  the BgWaitCeilingMs header line does not trip the handback guard

The R- and G4/G6/G7 tests call the REAL fire_toni: the real Popen, /bin/bash -c, cd, stdbuf and
PATH lookup. The `claude` found on PATH is a fake that reports its OWN os.environ — it is the
process the real CLI would be. No test calls the real `claude`, touches the live running.json
or writes under the live logs/.

Module-level imports are existing orchestrator symbols only; new names are imported inside the
tests that need them, so the red run fails on assertions, not on ImportError.
"""

import ast
import logging
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator
from canon_assert import check_handback_invariants, load_outstanding_work_rules

ROOT = Path(__file__).parent.parent
ORCH_SRC = ROOT / "orchestrator.py"
V = "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"
RULE = "=" * 60

FAKE_CLAUDE = f"""#!{sys.executable}
import os
print("CEILING=" + os.environ.get({V!r}, "<unset>"), flush=True)
with open(os.environ["BC_MARKER"], "w") as f:
    f.write("ran\\n")
"""


class Fire:
    """One real fire_toni call against the fake `claude`."""

    def __init__(self, tmp_path: Path, monkeypatch):
        self.monkeypatch = monkeypatch
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "claude"
        fake.write_text(FAKE_CLAUDE)
        fake.chmod(0o755)
        self.marker = tmp_path / "marker"
        self.logs = tmp_path / "logs"
        self.logs.mkdir()
        self.project = tmp_path / "proj"
        self.project.mkdir()
        self.brief = self.project / "brief.md"
        self.brief.write_text("# a brief\n")
        monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
        monkeypatch.setenv("BC_MARKER", str(self.marker))
        monkeypatch.setattr(orchestrator, "ensure_log_subdir", lambda _s: self.logs)
        monkeypatch.setattr(orchestrator, "RUNNING_FILE", tmp_path / "running.json")
        # monkeypatch restores TONI_TIMEOUT at teardown
        monkeypatch.setattr(orchestrator, "TONI_TIMEOUT", orchestrator.TONI_TIMEOUT)

    def __call__(self, route_timeout_s):
        self.monkeypatch.setattr(orchestrator, "TONI_TIMEOUT", route_timeout_s)
        ec, out_log = orchestrator.fire_toni(self.brief, self.project)
        self.log_path = Path(out_log)
        return ec

    @property
    def text(self) -> str:
        return self.log_path.read_text()

    def child_ceiling(self) -> str:
        m = re.search(r"^CEILING=(.*)$", self.text, re.MULTILINE)
        assert m, f"the fake claude never ran:\n{self.text}"
        return m.group(1)


@pytest.fixture
def fire(tmp_path, monkeypatch):
    return Fire(tmp_path, monkeypatch)


# ── the red set ──────────────────────────────────────────────────────────────────────────────

def test_R1_child_sees_the_bounded_ceiling(fire, monkeypatch):
    monkeypatch.delenv(V, raising=False)
    ec = fire(1800)
    assert ec == 0, fire.text
    assert "CEILING=1500000" in fire.text, fire.text
    assert V not in os.environ


def test_R2_inherited_ceiling_is_overridden(fire, monkeypatch):
    monkeypatch.setenv(V, "0")
    ec = fire(3360)
    assert ec == 0, fire.text
    assert "CEILING=3060000" in fire.text, fire.text
    assert os.environ[V] == "0"


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(fns) == 1, f"expected one def {name}, found {len(fns)}"
    return fns[0]


def _is_popen(call: ast.Call) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr == "Popen") or (isinstance(f, ast.Name) and f.id == "Popen")


def test_R3_source_guard_spawn_passes_env():
    tree = ast.parse(ORCH_SRC.read_text())
    calls = [n for n in ast.walk(_function(tree, "fire_toni")) if isinstance(n, ast.Call) and _is_popen(n)]
    assert len(calls) == 1
    kws = {k.arg for k in calls[0].keywords}
    assert "env" in kws, f"fire_toni's Popen has no env= keyword (keywords: {sorted(k for k in kws if k)})"


# ── G1 · the predicate ───────────────────────────────────────────────────────────────────────

_OK_ENV = {V: "1500000"}

G1_CASES = [
    # (id, env, T, expected reason or None)
    ("T0-env-none-order", None, 0, "route-timeout-invalid"),
    ("T-bool", _OK_ENV, True, "route-timeout-invalid"),
    ("T-negative", _OK_ENV, -60, "route-timeout-invalid"),
    ("T-str", _OK_ENV, "1800", "route-timeout-invalid"),
    ("T-none", _OK_ENV, None, "route-timeout-invalid"),
    ("env-none", None, 1800, "env-not-explicit"),
    ("absent", {"PATH": "/bin"}, 1800, "ceiling-absent"),
    ("absent-empty-env", {}, 1800, "ceiling-absent"),
    ("int-minus-one", {V: "-1"}, 1800, "ceiling-not-an-integer"),
    ("int-leading-space", {V: " 5"}, 1800, "ceiling-not-an-integer"),
    ("int-plus", {V: "+5"}, 1800, "ceiling-not-an-integer"),
    ("int-decimal", {V: "5.0"}, 1800, "ceiling-not-an-integer"),
    ("int-empty", {V: ""}, 1800, "ceiling-not-an-integer"),
    ("zero", {V: "0"}, 1800, "ceiling-not-positive"),
    ("zeros", {V: "000"}, 1800, "ceiling-not-positive"),
    ("just-below", {V: "1799999"}, 1800, None),
    ("equal", {V: "1800000"}, 1800, "ceiling-not-below-route-timeout"),
    ("above", {V: "999999999999"}, 1800, "ceiling-not-below-route-timeout"),
]


@pytest.mark.parametrize("env,T,expected", [c[1:] for c in G1_CASES], ids=[c[0] for c in G1_CASES])
def test_G1_predicate_cases(env, T, expected):
    from canon_assert import check_bg_ceiling_invariants
    v = check_bg_ceiling_invariants("x", env, T)
    assert len(v) <= 1
    if expected is None:
        assert v == []
    else:
        assert [x.reason for x in v] == [expected]
        assert v[0].site == "x"
        assert v[0].route_timeout_s is T or v[0].route_timeout_s == T
        assert v[0].value == (None if env is None else env.get(V))
        assert expected in str(v[0])


def test_G1_every_reason_is_covered():
    reasons = {c[3] for c in G1_CASES if c[3]}
    assert reasons == {"route-timeout-invalid", "env-not-explicit", "ceiling-absent", "ceiling-not-an-integer",
                       "ceiling-not-positive", "ceiling-not-below-route-timeout"}


def test_G1_single_definition_of_the_variable():
    from canon_assert import BG_WAIT_CEILING_VAR
    assert BG_WAIT_CEILING_VAR == V
    assert orchestrator.BG_WAIT_CEILING_VAR is BG_WAIT_CEILING_VAR


# ── G2 · the bound ───────────────────────────────────────────────────────────────────────────

G2_TABLE = [(1, 500), (60, 30_000), (600, 300_000), (601, 301_000), (1800, 1_500_000),
            (2220, 1_920_000), (3360, 3_060_000), (10800, 10_500_000)]


@pytest.mark.parametrize("T,ms", G2_TABLE, ids=[f"T{t}" for t, _ in G2_TABLE])
def test_G2_bound_table(T, ms):
    from canon_assert import check_bg_ceiling_invariants
    assert orchestrator.bg_wait_ceiling_ms(T) == ms
    assert 0 < ms < 1000 * T
    env = orchestrator.toni_child_env(T, base={})
    assert env == {V: str(ms)}
    assert check_bg_ceiling_invariants("x", env, T) == []


@pytest.mark.parametrize("T", [0, -60], ids=["T0", "Tneg60"])
def test_G2_nonpositive_route_is_invalid(T):
    from canon_assert import check_bg_ceiling_invariants
    env = {V: "1"}
    assert [x.reason for x in check_bg_ceiling_invariants("x", env, T)] == ["route-timeout-invalid"]


def test_G2_margin_constant():
    assert orchestrator.BG_WAIT_MARGIN_S == 300


# ── G3 · toni_child_env hygiene ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("inherited", ["0", "999999999999"])
def test_G3_overrides_and_preserves(inherited):
    base = {"PATH": "/usr/bin", "ANTHROPIC_API_KEY": "sk-test", V: inherited}
    snapshot = dict(base)
    environ_before = dict(os.environ)
    env = orchestrator.toni_child_env(1800, base=base)
    assert env[V] == "1500000"
    assert env["PATH"] == "/usr/bin" and env["ANTHROPIC_API_KEY"] == "sk-test"
    assert set(env) == set(base)
    assert base == snapshot
    assert dict(os.environ) == environ_before
    assert env is not base


def test_G3_reads_os_environ_at_call_time(monkeypatch):
    monkeypatch.setenv("BC_LATE_KEY", "late")
    monkeypatch.setenv(V, "0")
    env = orchestrator.toni_child_env(3360)
    assert env["BC_LATE_KEY"] == "late"
    assert env[V] == "3060000"
    assert os.environ[V] == "0"
    assert env is not os.environ


# ── G4 · refusal ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("T", [0, -60], ids=["T0", "Tneg60"])
def test_G4_invalid_route_timeout_is_refused(fire, caplog, T):
    with caplog.at_level(logging.INFO, logger="orch"):
        ec = fire(T)
    assert ec == -2
    assert not fire.marker.exists(), "the fake claude ran — the fire was not refused"
    refusals = [r.getMessage() for r in caplog.records if "Toni NOT fired — bg-wait ceiling:" in r.getMessage()]
    assert len(refusals) == 1, caplog.text
    assert "route-timeout-invalid" in refusals[0]


# ── G5 · S is exactly one site ───────────────────────────────────────────────────────────────

def _docstring_nodes(tree: ast.Module) -> set[int]:
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def _inside(node: ast.AST, fn: ast.FunctionDef) -> bool:
    return any(n is node for n in ast.walk(fn))


def _dotted(f: ast.AST) -> str:
    if isinstance(f, ast.Attribute):
        return f"{_dotted(f.value)}.{f.attr}"
    if isinstance(f, ast.Name):
        return f.id
    return ""


_OTHER_SPAWNERS = re.compile(r"^(os\.system|os\.exec\w*|os\.spawn\w*|os\.posix_spawn\w*|pty\.spawn|"
                             r"subprocess\.(call|check_call|check_output|run))$")


def test_G5_source_guard_one_executor_spawn_site():
    tree = ast.parse(ORCH_SRC.read_text())
    fire_toni = _function(tree, "fire_toni")

    # (a) exactly one Popen, inside fire_toni
    popens = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_popen(n)]
    assert len(popens) == 1, f"{len(popens)} Popen calls at lines {[p.lineno for p in popens]}"
    assert _inside(popens[0], fire_toni)

    # (b) every `claude --` literal (docstrings excluded) lies inside fire_toni
    docs = _docstring_nodes(tree)
    lits = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docs and re.search(r"\bclaude\s+--", n.value)]
    assert lits, "no `claude --` literal found at all — the guard would be vacuous"
    outside = [n.lineno for n in lits if not _inside(n, fire_toni)]
    assert outside == [], f"`claude --` literal outside fire_toni at lines {outside}"

    # (c) no other spawner is handed a string naming claude
    bad = []
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call) and _OTHER_SPAWNERS.match(_dotted(n.func))):
        for sub in (a for arg in [*call.args, *(k.value for k in call.keywords)] for a in ast.walk(arg)):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and re.search(r"\bclaude\b", sub.value):
                bad.append((call.lineno, _dotted(call.func)))
    assert bad == [], f"claude spawned outside fire_toni's Popen: {bad}"


# ── G6 · reachability ────────────────────────────────────────────────────────────────────────

def test_G6_fire_toni_calls_the_predicate_once(fire, monkeypatch):
    real = orchestrator.check_bg_ceiling_invariants
    calls = []

    def spy(site, env, route_timeout_s):
        calls.append((site, None if env is None else dict(env), route_timeout_s))
        return real(site, env, route_timeout_s)

    monkeypatch.setattr(orchestrator, "check_bg_ceiling_invariants", spy)
    monkeypatch.delenv(V, raising=False)
    assert fire(1800) == 0, fire.text
    assert len(calls) == 1
    site, env, T = calls[0]
    assert site == "orchestrator.fire_toni"
    assert T == orchestrator.TONI_TIMEOUT == 1800
    assert env[V] == fire.child_ceiling() == "1500000"


# ── G7 · the header line and the handback guard ─────────────────────────────────────────────

def test_G7_header_line_does_not_trip_the_guard(fire, monkeypatch):
    monkeypatch.delenv(V, raising=False)
    assert fire(1800) == 0, fire.text
    lines = fire.text.splitlines()
    rule_at = lines.index(RULE)
    hdr = [i for i, l in enumerate(lines) if l.startswith("BgWaitCeilingMs: 1500000 ")]
    assert len(hdr) == 1 and hdr[0] < rule_at, fire.text
    assert lines[hdr[0]] == "BgWaitCeilingMs: 1500000 (route timeout 1800s, margin 300s)"
    rules = load_outstanding_work_rules(orchestrator.HANDBACK_GUARD_CONFIG)
    assert rules
    assert check_handback_invariants(fire.log_path, rules) == []
