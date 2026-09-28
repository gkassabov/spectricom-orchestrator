# filename: tests/test_foreground.py
"""Tests for ORCH-FOREGROUND-1 — the executor is not offered a background it will lose.

S7-CORE-16 · [TONI-BACKGROUND-EXIT] second door. Route 60's probe, and this route's T0 probe on
CLI 2.1.283, showed that a backgrounded command is killed when the executor's turn ends and that
no follow-up turn arrives. T0 found that `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` is honoured:
the Bash tool is not offered `run_in_background`, and the command runs in the foreground. So for
every fire f:

    env_f[CLAUDE_CODE_DISABLE_BACKGROUND_TASKS] == "1"
    ∧ ∀ V ∈ {CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS, BASH_DEFAULT_TIMEOUT_MS, BASH_MAX_TIMEOUT_MS}:
          env_f[V] matches ^[0-9]+$ ∧ 0 < int(env_f[V]) < 1000 · T_f

and the prompt says the same thing in words.

  AC-FG-02  the env predicate: the child sees it (red at the brief-1 commit); the bound at
            T = 1800 / 3360 / 10800; one case per reason
  AC-FG-03  the prompt pin: a source guard over fire_toni's literal, and the argv the child got

The child-env tests call the REAL fire_toni against a fake `claude` on PATH that reports its own
argv and environment. No test calls the real `claude`.
"""

import ast
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator

ROOT = Path(__file__).parent.parent
DISABLE = "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"
CEILING = "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"
BDEF, BMAX = "BASH_DEFAULT_TIMEOUT_MS", "BASH_MAX_TIMEOUT_MS"
PROMPT_TAIL = (" and execute all briefs in order. Run every command in the foreground and wait for it to "
               "finish; never use run_in_background — background tasks are killed when your turn ends "
               "and no follow-up turn will come.")

FAKE_CLAUDE = f"""#!{sys.executable}
import json, os, sys
print("CHILD=" + json.dumps({{"argv": sys.argv[1:], "env": {{k: os.environ.get(k) for k in
      ({DISABLE!r}, {CEILING!r}, {BDEF!r}, {BMAX!r})}}}}), flush=True)
"""


@pytest.fixture
def child(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text(FAKE_CLAUDE)
    fake.chmod(0o755)
    logs = tmp_path / "logs"
    logs.mkdir()
    proj = tmp_path / "proj"
    (proj / "briefs").mkdir(parents=True)
    brief = proj / "briefs" / "61-x.md"
    brief.write_text("# a brief\n")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setattr(orchestrator, "ensure_log_subdir", lambda _s: logs)
    monkeypatch.setattr(orchestrator, "RUNNING_FILE", tmp_path / "running.json")
    monkeypatch.setattr(orchestrator, "TONI_TIMEOUT", orchestrator.TONI_TIMEOUT)

    def _fire(T):
        monkeypatch.setattr(orchestrator, "TONI_TIMEOUT", T)
        ec, log_path = orchestrator.fire_toni(brief, proj)
        assert ec == 0, Path(log_path).read_text()
        line = next(l for l in Path(log_path).read_text().splitlines() if l.startswith("CHILD="))
        return json.loads(line[len("CHILD="):])
    return _fire


# ── AC-FG-02 · the child's environment ──────────────────────────────────────────────────────

BOUND = [(1800, "1500000"), (3360, "3060000"), (10800, "10500000")]


@pytest.mark.parametrize("T,ms", BOUND, ids=[f"T{t}" for t, _ in BOUND])
def test_R1_the_child_is_foreground_only_and_bounded(child, monkeypatch, T, ms):
    monkeypatch.setenv(DISABLE, "0")        # an inherited value never survives
    monkeypatch.setenv(BMAX, "999999999")
    monkeypatch.delenv(BDEF, raising=False)
    got = child(T)["env"]
    assert got == {DISABLE: "1", CEILING: ms, BDEF: ms, BMAX: ms}
    assert 0 < int(ms) < 1000 * T
    assert os.environ[DISABLE] == "0" and os.environ[BMAX] == "999999999", "the parent is untouched"


@pytest.mark.parametrize("T,ms", BOUND, ids=[f"T{t}" for t, _ in BOUND])
def test_toni_child_env_is_one_bound(T, ms):
    from canon_assert import check_foreground_invariants
    env = orchestrator.toni_child_env(T, base={"PATH": "/bin"})
    assert env == {"PATH": "/bin", DISABLE: "1", CEILING: ms, BDEF: ms, BMAX: ms}
    assert check_foreground_invariants("x", env, T) == []


def test_the_unit_suite_fits_twice_under_the_default_bound():
    """clinical-mp's `npm test` measured 337 s and 353 s back to back (BASELINE-FLAKE-1)."""
    assert int(orchestrator.toni_child_env(1800, base={})[BDEF]) > 2 * 353 * 1000


# ── AC-FG-02 · the predicate, one case per reason ───────────────────────────────────────────

def _ok(T=1800):
    return {DISABLE: "1", CEILING: "1500000", BDEF: "1500000", BMAX: "1500000"} if T == 1800 else None


CASES = [
    ("T-invalid", _ok(), 0, "route-timeout-invalid", None),
    ("T-bool", _ok(), True, "route-timeout-invalid", None),
    ("env-none", None, 1800, "env-not-explicit", None),
    ("disable-absent", {k: v for k, v in _ok().items() if k != DISABLE}, 1800, "background-not-disabled", DISABLE),
    ("disable-0", {**_ok(), DISABLE: "0"}, 1800, "background-not-disabled", DISABLE),
    ("disable-true", {**_ok(), DISABLE: "true"}, 1800, "background-not-disabled", DISABLE),
    ("ceiling-absent", {k: v for k, v in _ok().items() if k != CEILING}, 1800, "bound-absent", CEILING),
    ("bdef-absent", {k: v for k, v in _ok().items() if k != BDEF}, 1800, "bound-absent", BDEF),
    ("bmax-absent", {k: v for k, v in _ok().items() if k != BMAX}, 1800, "bound-absent", BMAX),
    ("bdef-decimal", {**_ok(), BDEF: "5.0"}, 1800, "bound-not-an-integer", BDEF),
    ("bmax-negative", {**_ok(), BMAX: "-1"}, 1800, "bound-not-an-integer", BMAX),
    ("bdef-zero", {**_ok(), BDEF: "0"}, 1800, "bound-not-positive", BDEF),
    ("bmax-equal", {**_ok(), BMAX: "1800000"}, 1800, "bound-not-below-route-timeout", BMAX),
    ("bdef-just-below", {**_ok(), BDEF: "1799999"}, 1800, None, None),
    ("order-first-var", {**_ok(), CEILING: "0", BMAX: "x"}, 1800, "bound-not-positive", CEILING),
]


@pytest.mark.parametrize("env,T,reason,var", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_predicate_cases(env, T, reason, var):
    from canon_assert import check_foreground_invariants
    v = check_foreground_invariants("orchestrator.fire_toni", env, T)
    assert len(v) <= 1
    if reason is None:
        assert v == []
    else:
        assert [(x.reason, x.var) for x in v] == [(reason, var)]
        assert reason in str(v[0]) and "orchestrator.fire_toni" in str(v[0])


def test_every_reason_is_covered():
    assert {c[3] for c in CASES if c[3]} == {
        "route-timeout-invalid", "env-not-explicit", "background-not-disabled", "bound-absent",
        "bound-not-an-integer", "bound-not-positive", "bound-not-below-route-timeout"}


def test_single_definition_of_the_names():
    import canon_assert
    assert (canon_assert.DISABLE_BG_TASKS_VAR, canon_assert.BASH_DEFAULT_TIMEOUT_VAR,
            canon_assert.BASH_MAX_TIMEOUT_VAR) == (DISABLE, BDEF, BMAX)
    assert canon_assert.FOREGROUND_BOUND_VARS == (CEILING, BDEF, BMAX)


def test_an_unfit_env_is_refused_not_fired(child, monkeypatch, caplog):
    import logging
    real = orchestrator.toni_child_env
    monkeypatch.setattr(orchestrator, "toni_child_env", lambda T: {**real(T), DISABLE: "0"})
    with caplog.at_level(logging.INFO, logger="orch"):
        ec, _ = orchestrator.fire_toni(Path("x.md"), Path("/nonexistent"))
    assert ec == -2
    shield = [r.getMessage() for r in caplog.records if r.getMessage().startswith("🛡 bg-wait-ceiling:")]
    assert len(shield) == 1 and shield[0].startswith("🛡 bg-wait-ceiling: BLOCKED — background-not-disabled")


# ── AC-FG-03 · the prompt pin ───────────────────────────────────────────────────────────────

def test_the_child_is_told_to_stay_in_the_foreground(child):
    argv = child(1800)["argv"]
    assert argv[-1] == "Read briefs/61-x.md" + PROMPT_TAIL


def test_source_guard_the_literal_in_fire_toni():
    tree = ast.parse((ROOT / "orchestrator.py").read_text())
    fire_toni = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "fire_toni")
    texts = []
    for n in ast.walk(fire_toni):
        if isinstance(n, ast.JoinedStr):
            texts.append("".join(v.value if isinstance(v, ast.Constant) else "{}" for v in n.values))
    # adjacent f-strings are ONE JoinedStr: the command literal, whose tail is the quoted prompt
    cmds = [t for t in texts if '"Read {}' in t]
    assert len(cmds) == 1, cmds
    assert cmds[0].startswith("cd {} && stdbuf -oL claude --dangerously-skip-permissions "), cmds[0]
    assert cmds[0].endswith(' "Read {}' + PROMPT_TAIL + '"'), cmds[0]
