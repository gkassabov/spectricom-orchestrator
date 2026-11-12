"""[ORCH-NPM-FROZEN-1] Kanban 663, OC-3 (D-S7CORE51-18) — predicates P-D1..P-D4 of
briefs/662-663-orch-guard-self-npm-frozen-1.md Part B: a brief's `## Dependency change:` line (G-N3, prefire) and
the fire that hands the approved change to the executor's npm hook as TONI_DEP_CHANGES (G-N4, fire_toni)."""
import json
import logging
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import orchestrator  # noqa: E402
import prefire  # noqa: E402
from test_opex_prefire import FIVE, brief, canon  # noqa: E402,F401  (canon: the autouse scratch canon)

GOOD = ['## Dependency change: vitest-axe@0.1.0 (dev) — George go "629 dev dep, approve"',
        '## Dependency change: @testing-library/user-event@14.5.2 (dev) — George go 2026-11-12 09:10 "yes"',
        '## Dependency change: zod@3.23.8 (prod) — George go "ok" (D-S7CORE52-04)']
WANT = [{"pkg": "vitest-axe", "version": "0.1.0", "kind": "dev"},
        {"pkg": "@testing-library/user-event", "version": "14.5.2", "kind": "dev"},
        {"pkg": "zod", "version": "3.23.8", "kind": "prod"}]
QUOTES = ["629 dev dep, approve", "yes", "ok"]


def dep_brief(tmp_path, *lines) -> Path:
    return brief(tmp_path, header="".join(l + "\n" for l in lines))


# ── P-D1 · the grammar ──────────────────────────────────────────────────────
@pytest.mark.parametrize("i", range(3))
def test_PD1_a_good_line_is_one_entry_and_a_report_line(tmp_path, capsys, i):
    b = dep_brief(tmp_path, GOOD[i])
    assert prefire.dependency_changes(b) == ([WANT[i]], [])
    assert prefire.check(b) == []
    assert prefire.report(b) is True
    out = capsys.readouterr().out.splitlines()
    e = WANT[i]
    assert out[-1] == "  DEPCHANGE ✅ %s@%s (%s) — George go: '%s'" % (e["pkg"], e["version"], e["kind"], QUOTES[i])
    assert out[-2].startswith("  OPX-3 ")                  # after the OPX lines


BAD_SPECS = ["vitest-axe@^0.1.0", "vitest-axe@~0.1.0", "vitest-axe@>=0.1.0", "vitest-axe@0.1.x", "vitest-axe@*",
             "vitest-axe@0.1.0 || 0.2.0", "vitest-axe@latest", "vitest-axe@next", "vitest-axe@npm:other@1.0.0",
             "vitest-axe@file:../x", "vitest-axe@github:a/b", "vitest-axe@https://x.test/a.tgz", "vitest-axe@0.1",
             "vitest-axe@0.1.0 lodash@4.17.21", "vitest-axe", "Vitest-Axe@0.1.0"]
BAD = (['## Dependency change: %s (dev) — George go "629 dev dep, approve"' % s for s in BAD_SPECS]
       + ['## Dependency change: vitest-axe@0.1.0 (test) — George go "approve"',
          '## Dependency change: vitest-axe@0.1.0 (dev) — "approve"',
          '## Dependency change: vitest-axe@0.1.0 (dev) — George go ""',
          '## Dependency change: vitest-axe@0.1.0 (dev) — George go "OWED"',
          '## Dependency change: vitest-axe@0.1.0 (dev) — George go "TBD — ask at EOS"',
          '## Dependency change: vitest-axe@0.1.0 (dev) — George go "<George\'s words>"',
          '## Dependency change: vitest-axe@0.1.0 (dev) — George go "do it"'])


@pytest.mark.parametrize("line", BAD)
def test_PD1_a_bad_line_is_refused_naming_why(tmp_path, line):
    b = dep_brief(tmp_path, line)
    entries, problems = prefire.dependency_changes(b)
    assert entries == [] and len(problems) == 1
    fails = prefire.check(b)
    assert fails == problems
    assert fails[0].startswith("DEPCHANGE ❌ — '## Dependency change: ") and fails[0].endswith("(OC-3, D-S7CORE51-18)")
    assert "is not a George-approved exact dependency: " in fails[0]
    assert fails[0].split("exact dependency: ", 1)[1].strip(" (OC-3, D-S7CORE51-18)"), "says why"


@pytest.mark.parametrize("line, why", [(BAD[0], "'^0.1.0' is not an exact version"),
                                       (BAD[-4], "placeholder 'OWED'"), (BAD[-2], "template marker"),
                                       (BAD[-1], "no ruling id, go word or timed quote"),
                                       (BAD[-5], "no George's words in quotes"), (BAD[-7], "the kind is 'test'"),
                                       (BAD[14], "no version in 'vitest-axe'"),
                                       (BAD[15], "'Vitest-Axe' is not an npm package name")])
def test_PD1_the_refusal_says_why(tmp_path, line, why):
    assert why in prefire.check(dep_brief(tmp_path, line))[0]


def test_PD1_two_lines_for_one_package_refuse(tmp_path):
    b = dep_brief(tmp_path, GOOD[0], GOOD[0].replace("0.1.0", "0.1.1"))
    entries, problems = prefire.dependency_changes(b)
    assert entries == [WANT[0]] and len(problems) == 1 and "a second line for vitest-axe" in problems[0]
    assert prefire.check(b) == problems


def test_PD1_two_packages_on_two_lines_are_two_entries(tmp_path):
    assert prefire.dependency_changes(dep_brief(tmp_path, GOOD[0], GOOD[2])) == ([WANT[0], WANT[2]], [])


def test_PD1_a_line_inside_a_code_fence_is_not_read(tmp_path):
    b = brief(tmp_path, opex="```\n%s\n```\n\n" % GOOD[0] + FIVE)
    assert prefire.dependency_changes(b) == ([], [])


# ── P-D2 · no line: nothing changes ─────────────────────────────────────────
def test_PD2_a_brief_with_no_line(tmp_path, capsys):
    b = brief(tmp_path)
    assert prefire.dependency_changes(b) == ([], [])
    assert prefire.check(b) == []
    prefire.report(b)
    assert "DEPCHANGE" not in capsys.readouterr().out


def test_PD2_an_unreadable_brief(tmp_path):
    assert prefire.dependency_changes(tmp_path / "no-such.md") == ([], [])


# ── P-D3 · G-N4: the fire carries the approved change ───────────────────────
@pytest.fixture
def spy(tmp_path, monkeypatch):
    """tests/test_toni_guards.py's spy, local: the REAL fire_toni up to its Popen, which records (cmd, env)."""
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(orchestrator, "ensure_log_subdir", lambda _s: logs)
    monkeypatch.setattr(orchestrator, "RUNNING_FILE", tmp_path / "running.json")
    monkeypatch.setattr(orchestrator, "TONI_TIMEOUT", 3600)
    monkeypatch.setattr(orchestrator, "TONI_MODEL", "claude-opus-5-5")
    monkeypatch.setattr(orchestrator, "TONI_EFFORT", "xhigh")
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "clinical-mp")
    monkeypatch.delenv("TONI_GUARDS", raising=False)
    monkeypatch.delenv("TONI_DEP_CHANGES", raising=False)
    calls = []

    class _Popen:
        def __init__(self, cmd, **kw):
            calls.append({"cmd": cmd, **kw})
            self.pid = 0

        def wait(self, timeout=None):
            return 0
    monkeypatch.setattr(orchestrator.subprocess, "Popen", _Popen)
    project = tmp_path / "proj"
    (project / "briefs").mkdir(parents=True)
    b = project / "briefs" / "629-x.md"
    b.write_text("# x\n")

    def fire(path=None):
        return orchestrator.fire_toni(path or b, project)
    return types.SimpleNamespace(fire=fire, calls=calls, brief=b)


@pytest.mark.guards
def test_PD3_the_good_line_reaches_the_hooks_env(spy, caplog):
    spy.brief.write_text("# x\n%s\n" % GOOD[0])
    with caplog.at_level(logging.INFO, logger=orchestrator.log.name):
        assert spy.fire()[0] == 0
    assert spy.calls[0]["env"]["TONI_DEP_CHANGES"] == '[{"pkg":"vitest-axe","version":"0.1.0","kind":"dev"}]'
    assert "Dependency change approved for this fire: vitest-axe@0.1.0 (dev)" in caplog.text
    assert not any("Dependency change" in r.getMessage() and "🛡" in r.getMessage() for r in caplog.records)


@pytest.mark.guards
def test_PD3_an_inherited_value_never_survives(spy, monkeypatch):
    monkeypatch.setenv("TONI_DEP_CHANGES", '[{"pkg":"lodash","version":"4.17.21","kind":"prod"}]')
    assert spy.fire()[0] == 0
    assert "TONI_DEP_CHANGES" not in spy.calls[0]["env"]


@pytest.mark.guards
def test_PD3_a_bad_line_sets_nothing(spy):
    spy.brief.write_text("# x\n%s\n%s\n" % (GOOD[0], BAD[0]))
    assert spy.fire()[0] == 0
    assert "TONI_DEP_CHANGES" not in spy.calls[0]["env"]


@pytest.mark.guards
def test_PD3_guards_off_sets_and_pops_nothing(spy, monkeypatch):
    monkeypatch.setenv("TONI_GUARDS", "off")
    assert spy.fire()[0] == 0
    plain = spy.calls[0]["env"]
    spy.brief.write_text("# x\n%s\n" % GOOD[0])
    assert spy.fire()[0] == 0
    assert spy.calls[1]["env"] == plain and "TONI_DEP_CHANGES" not in plain


@pytest.mark.guards
def test_PD3_a_brief_that_does_not_exist_sets_nothing(spy, tmp_path):
    assert spy.fire(spy.brief.parent / "missing.md")[0] == 0
    assert "TONI_DEP_CHANGES" not in spy.calls[0]["env"]


@pytest.mark.guards
def test_PD3_a_read_that_raises_never_stops_the_fire(spy, monkeypatch, caplog):
    spy.brief.write_text("# x\n%s\n" % GOOD[0])

    def boom(_p):
        raise RuntimeError("disk gone")
    monkeypatch.setattr(prefire, "dependency_changes", boom)
    with caplog.at_level(logging.INFO, logger=orchestrator.log.name):
        assert spy.fire()[0] == 0
    assert len(spy.calls) == 1 and "TONI_DEP_CHANGES" not in spy.calls[0]["env"]
    assert "Dependency change not read (RuntimeError): no install is allowed for this fire" in caplog.text


# ── P-D4 · controls ─────────────────────────────────────────────────────────
def test_PD4_every_settings_file_is_json():
    files = sorted((ROOT / "executor" / "settings").glob("*.json"))
    assert len(files) == 6
    for p in files:
        assert isinstance(json.loads(p.read_text()), dict)
