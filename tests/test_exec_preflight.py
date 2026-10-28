# filename: tests/test_exec_preflight.py
"""Tests for ORCH-EXEC-PREFLIGHT-1 (ORCH-RELIABILITY-1 Brief 1 · S7-CORE-36 · D-S7CORE36-03).

Three routes built clean and went red at the gate's SIT leg 1–2 h later on SIT files the executor never ran. The
executor now runs `orchestrator.py preflight --repo <repo>` in its checkout before its handback: the gate's own
diff, related SIT + unit set (tests_reaching — one owner, A13) and runners, on the related files only.

  PB1  a diff reaching one SIT file and two unit files: preflight runs exactly the files run_pre_merge_gates runs
  PB2  a briefs-only diff ⇒ exit 0, "nothing to run", nothing invoked
  PB3  a SIT file failing in its batch and alone ⇒ exit 1, file:test named; an environment-classed SIT red ⇒ exit 2
  PB4  the executor prompt carries the preflight sentence with the brief's repo; ORCH_EXEC_PREFLIGHT=off omits it

Harness: a REAL git repository (real merge base, real diff); only `npx vitest list …`, `npm run sit:gate …`,
`npm run build` and `npm test …` are scripted. Module-level imports are existing symbols only (RED collects).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_foreground import PROMPT_TAIL, child  # noqa: E402,F401  (child is a fixture)
from tests.test_gate_cost import BUILD_CMD, F, LIST_OUT, SIT_CMD, TEST_CMD, _activate, _git, batch, vitest  # noqa: E402

SIT_LIST = "npx vitest list --config vitest.sit.config.ts"
UNIT_SUITE = ["src/feature/t1.test.ts", "src/feature/t2.test.ts", "src/feature/t3.test.ts", "src/lib/lib.test.ts"]
U1, U2 = UNIT_SUITE[0], UNIT_SUITE[2]
SENTENCE = ("Before you write the handback's final status, run `python3 ~/spectricom-orchestrator/orchestrator.py "
            "preflight --repo {repo}` and paste its summary; a red there is handled by your brief's rule #8 and STOP "
            "rules like any other red.")
ECONN = "Error: connect ECONNREFUSED 127.0.0.1:8103\n"


class Suites:
    """subprocess.run for every leg: the SIT listing / related listing / batches, the unit listing / related listing
    / runs, the build. Records the files each SIT and unit run was handed; git runs for real."""

    def __init__(self, monkeypatch, sit_related=(F[2],), unit_related=(U1, U2), sit_red=(), sit_red_alone=(),
                 sit_env=False):
        self.real = subprocess.run
        self.sit_related, self.unit_related = sit_related, unit_related
        self.sit_red, self.sit_red_alone, self.sit_env = set(sit_red), set(sit_red_alone), sit_env
        self.calls, self.sit_runs, self.unit_runs = [], [], []
        monkeypatch.setattr(subprocess, "run", self)
        monkeypatch.setattr("time.sleep", lambda s: None)

    def __call__(self, cmd, *a, **kw):
        if not (isinstance(cmd, str) and cmd.startswith(("npm ", "npx "))):
            return self.real(cmd, *a, **kw)
        self.calls.append(cmd)
        done = lambda rc, out: subprocess.CompletedProcess(cmd, rc, stdout=out, stderr="")  # noqa: E731
        if cmd.startswith(SIT_LIST):
            return done(0, "".join(f"{f}\n" for f in self.sit_related) if "--changed" in cmd else LIST_OUT)
        if cmd.startswith("npx vitest list"):
            return done(0, "".join(f"{f}\n" for f in (self.unit_related if "--changed" in cmd else UNIT_SUITE)))
        if cmd.startswith(BUILD_CMD):
            return done(0, "built\n")
        if cmd.startswith(SIT_CMD + " -- "):
            files = [f for f in F.values() if f in cmd]
            alone = len(files) == 1 and any(f in r for r in self.sit_runs for f in files)
            self.sit_runs.append(files)
            red = [f for f in files if f in (self.sit_red_alone if alone else self.sit_red)]
            return done(1 if red else 0, (ECONN if red and self.sit_env else "") + batch(len(files), red))
        if cmd == TEST_CMD or cmd.startswith(TEST_CMD + " -- "):
            files = UNIT_SUITE if cmd == TEST_CMD else [f for f in UNIT_SUITE if f in cmd.split(" -- ", 1)[1]]
            self.unit_runs.append(files)
            return done(0, vitest(total_tests=3 * len(files), total_files=len(files)))
        raise AssertionError(cmd)

    def ran(self) -> list:
        return [c for c in self.calls if not c.startswith("npx vitest list")]


@pytest.fixture
def rig(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    files = {"package.json": json.dumps({"scripts": {"test": "vitest run"}}) + "\n", "src/feature/a.ts": "a\n",
             "src/lib/b.ts": "b\n", "briefs/old.md": "# old\n", **{t: "t\n" for t in UNIT_SUITE},
             **{f: "s\n" for f in F.values()}}
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "M0")
    orch = tmp_path / "orch"
    (orch / "state").mkdir(parents=True)
    monkeypatch.setattr(orchestrator, "ORCH_DIR", orch)
    _activate(monkeypatch, tmp_path, repo, gates=("build", "sit"), sit_list_cmd=SIT_LIST, sit_batch_files=10,
              sit_batch_pause_s=0)
    for var in ("ORCH_UNIT_RELATED", "ORCH_SIT_ENUM_PARALLEL", "ORCH_EXEC_PREFLIGHT"):
        monkeypatch.delenv(var, raising=False)

    class R:
        pass
    r = R()
    r.repo, r.orch, r.tmp, r.monkeypatch = repo, orch, tmp_path, monkeypatch
    return r


def _route(repo, write: dict, name="route"):
    _git(repo, "checkout", "-q", "-B", name, "main")
    for rel, text in write.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"{name} work")


def _preflight(rig, capsys):
    out = rig.tmp / "pf.json"
    code = orchestrator.preflight(rig.repo, out)
    return code, capsys.readouterr().out, json.loads(out.read_text())


# ── PB1 · the preflight runs exactly what the gate runs ─────────────────────────────────────────────────────────────
class TestPB1SameSet:

    def test_preflight_runs_exactly_the_gates_files(self, rig, capsys):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        gate = Suites(rig.monkeypatch)
        v = orchestrator.run_pre_merge_gates(rig.repo, "route")
        assert v.outcome is orchestrator.GateOutcome.PASS, v.label
        pf = Suites(rig.monkeypatch)
        code, out, rec = _preflight(rig, capsys)
        assert code == 0, out
        assert gate.sit_runs == [[F[2]]] and gate.unit_runs == [[U1, U2]], (gate.sit_runs, gate.unit_runs)
        assert pf.sit_runs == gate.sit_runs and pf.unit_runs == gate.unit_runs, (pf.calls, gate.calls)
        assert rec["sit"]["files"] == [F[2]] and rec["unit"]["files"] == [U1, U2]
        assert "🧪 Preflight (executor): 1 SIT files / 2 unit files — pass" in out
        assert not any(c.startswith(BUILD_CMD) for c in pf.calls), "the preflight runs no build"

    def test_the_set_is_the_gates_functions_result(self, rig):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        Suites(rig.monkeypatch)
        diff = orchestrator._branch_diff(rig.repo, "route")
        plan = orchestrator._sit_plan(rig.repo)
        sit, _ = orchestrator._sit_related_files(rig.repo, plan, diff)
        scope = orchestrator._unit_scope(rig.repo, TEST_CMD, diff)
        reach = orchestrator.tests_reaching(rig.repo, diff)
        assert list(reach.sit) == sit and reach.unit == scope.files == (U1, U2)

    def test_a_shared_trigger_runs_the_related_set_and_says_the_gate_runs_full(self, rig, capsys):
        _route(rig.repo, {"src/feature/a.ts": "a2\n", "package.json": '{"scripts": {"test": "vitest run"}} \n'})
        fake = Suites(rig.monkeypatch)
        code, out, rec = _preflight(rig, capsys)
        assert code == 0 and fake.unit_runs == [[U1, U2]], (out, fake.unit_runs)
        assert rec["unit"]["gate_runs_full"].startswith("(a)") and "FULL unit suite" in out

    def test_a_set_that_cannot_be_computed_runs_no_full_suite_and_exits_3(self, rig, capsys):
        rig.monkeypatch.setitem(orchestrator.ACTIVE_REPO_CONFIG, "sit_list_cmd", "")
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        fake = Suites(rig.monkeypatch)
        code, out, rec = _preflight(rig, capsys)
        assert code == 3 and rec["sit"]["status"] == "not computed", out
        assert not fake.sit_runs and not any(c == SIT_CMD for c in fake.calls), "never the full suite"
        assert "fail (not computed)" in out


# ── PB2 · briefs-only ─────────────────────────────────────────────────────────────────────────────────────────────────
class TestPB2BriefsOnly:

    def test_briefs_only_is_exit_0_and_nothing_runs(self, rig, capsys):
        _route(rig.repo, {"briefs/x.md": "# x\n", "briefs/x.handback.md": "# hb\n"})
        fake = Suites(rig.monkeypatch)
        code, out, rec = _preflight(rig, capsys)
        assert code == 0 and "briefs-only — nothing to run" in out, out
        assert fake.calls == [] and rec["briefs_only"] is True


# ── PB3 · a red names the file:test; an environment red is exit 2 ─────────────────────────────────────────────────────
class TestPB3Red:

    def test_a_sit_file_failing_alone_is_exit_1_and_named(self, rig, capsys):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        Suites(rig.monkeypatch, sit_red=(F[2],), sit_red_alone=(F[2],))
        code, out, rec = _preflight(rig, capsys)
        assert code == 1, out
        assert rec["sit"]["status"] == "fail" and rec["sit"]["failed"] == [f"{F[2]} > case 1"], rec["sit"]
        assert f"failed: {F[2]} > case 1" in out and "— fail (fail)" in out

    def test_a_file_that_passes_alone_is_green_as_the_gate_reads_it(self, rig, capsys):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        Suites(rig.monkeypatch, sit_related=(F[2], F[3]), sit_red=(F[2],))
        code, out, rec = _preflight(rig, capsys)
        assert code == 0 and rec["sit"]["status"] == "pass", out

    def test_an_environment_classed_sit_red_is_exit_2(self, rig, capsys):
        _route(rig.repo, {"src/feature/a.ts": "a2\n"})
        Suites(rig.monkeypatch, sit_red=(F[2],), sit_red_alone=(F[2],), sit_env=True)
        code, out, rec = _preflight(rig, capsys)
        assert code == 2 and rec["sit"]["status"] == "environment", out
        assert "fail (environment)" in out


# ── PB4 · the executor prompt ─────────────────────────────────────────────────────────────────────────────────────────
class TestPB4Prompt:

    def test_the_prompt_carries_the_sentence_with_the_briefs_repo(self, child, tmp_path, monkeypatch):
        (tmp_path / "proj" / "briefs" / "61-x.md").write_text("#!queue model=m effort=high repo=clinical-mp\n# x\n")
        monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "orchestrator")
        argv = child(1800)["argv"]
        assert argv[-1] == "Read briefs/61-x.md" + PROMPT_TAIL + " " + SENTENCE.format(repo="clinical-mp")

    def test_no_header_falls_back_to_the_active_repo(self, child, monkeypatch):
        monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "yorsie")
        argv = child(1800)["argv"]
        assert argv[-1].endswith(PROMPT_TAIL + " " + SENTENCE.format(repo="yorsie"))

    def test_off_omits_it(self, child, monkeypatch):
        monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "yorsie")
        monkeypatch.setenv("ORCH_EXEC_PREFLIGHT", "off")
        argv = child(1800)["argv"]
        assert argv[-1] == "Read briefs/61-x.md" + PROMPT_TAIL
