# filename: tests/test_yorsie_safety.py
"""Tests for ORCH-YORSIE-SAFETY-1: no brief reaches a repo it did not name; Yorsie merges only what
builds; the queue's real state is visible.

S7-CORE-17 · Yorsie PDLC integration plan, Phase 0 · D-S7CORE13-02 (RED first).
  Q1  a brief with no `repo=` in its `#!queue` header is refused to queue/failed/ with the reason; the
      next brief still fires; stop_on_failure is not tripped.                               (TestQ1*)
  Q2  no code path resolves a repo without an explicit name: repos.yaml declares no `default:`, the
      loader refuses one, the orchestrator CLI refuses a repo command that names none, and a source
      scan finds no default lookup.                                                          (TestQ2*)
  Q3  a yorsie route whose branch fails `npm run build` is not merged; a passing build merges; the
      build runs in the route's own checkout, on the route branch, with no env file sourced. (TestQ3*)
  Q4  qstat.sh prints the daemon's pid, daemon_status, paused_reason and paused_at from
      queue-state.json, the queued brief count and the running route.                        (TestQ4*)

Each predicate has a negative control. Every path is under tmp_path; no test reads or writes the live
queue, the live queue-state.json or a product repo.
"""

import ast
import inspect
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator
import queue_daemon
import repo_config

ROOT = Path(__file__).parent.parent
REASON = "no repo= in #!queue header — refused, nothing fired"   # the brief's words, verbatim
NAMED = "named-repo"


def _dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


# ═══════════════════════════════════════════════════════
# Q1 · the daemon refuses a brief that names no repo
# ═══════════════════════════════════════════════════════
# The fake route: records its argv, exits with the code in exit-code (0 when absent). Stdlib only.
FAKE_ORCHESTRATOR = '''\
import json, sys
from pathlib import Path
here = Path(__file__).parent
with open(here / "fired.jsonl", "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
code = here / "exit-code"
sys.exit(int(code.read_text()) if code.exists() else 0)
'''


class Daemon:
    """One real QueueDaemon wired under tmp_path. Its loop ends at its first sleep (queue empty,
    paused, or a cooldown) — only queue_daemon's `time` is replaced."""

    def __init__(self, tmp_path: Path, monkeypatch, persisted: dict = None):
        self.orch = tmp_path / "orch"
        self.orch.mkdir()
        (self.orch / "orchestrator.py").write_text(FAKE_ORCHESTRATOR)
        self.queue = self.orch / "queue"
        self.queue.mkdir()
        not_git = tmp_path / "not-a-repo"   # B6 over a non-repo retires nothing
        not_git.mkdir()
        cfg = tmp_path / "repos.yaml"
        # clinical-mp is the old daemon default (QUEUE_REPO, else clinical-mp): declared here so a
        # daemon that still applied it would resolve it, and the tests would see it.
        cfg.write_text(yaml.safe_dump({"repos": {NAMED: {"project_dir": str(not_git)},
                                                 "clinical-mp": {"project_dir": str(not_git)}}}))
        self.state_file = tmp_path / "queue-state.json"
        if persisted is not None:
            self.state_file.write_text(json.dumps(persisted))
        for name, val in (("ORCH_DIR", self.orch), ("QUEUE_DIR", self.queue),
                          ("QUEUE_DONE", self.queue / "done"), ("QUEUE_FAILED", self.queue / "failed"),
                          ("QUEUE_STATE", self.state_file), ("REPOS_CONFIG", cfg),
                          ("LOG_DIR", tmp_path / "logs")):
            monkeypatch.setattr(queue_daemon, name, val)
        self.d = queue_daemon.QueueDaemon()
        self.d.config.update(cooldown_seconds=0, timeout_seconds=15, model="m", effort="e",
                             stop_on_failure=True)
        monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=self._stop))

    def _stop(self, _seconds):
        self.d.status = "stopped"

    def brief(self, name: str, first_line: str) -> Path:
        p = self.queue / name
        p.write_text(f"{first_line}\n\n# {name}\n")
        return p

    def fired(self) -> list:
        f = self.orch / "fired.jsonl"
        return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []

    def run(self):
        self.d.run_loop()


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    monkeypatch.delenv("QUEUE_REPO", raising=False)
    return Daemon(tmp_path, monkeypatch)


class TestQ1Refused:

    def test_a_headerless_brief_is_refused_and_the_next_still_fires(self, daemon):
        daemon.brief("a-headerless.md", "# A brief with no queue header")
        daemon.brief("b-named.md", f"#!queue model=m effort=e repo={NAMED}")
        daemon.run()
        assert (daemon.queue / "failed" / "a-headerless.md").exists(), "refused → queue/failed/"
        assert not (daemon.queue / "a-headerless.md").exists()
        assert not (daemon.queue / "done" / "a-headerless.md").exists(), "it must not have run"
        fired = daemon.fired()
        assert len(fired) == 1, f"only the named brief fires: {fired}"
        assert fired[0][1].endswith("b-named.md") and fired[0][fired[0].index("--repo") + 1] == NAMED
        assert (daemon.queue / "done" / "b-named.md").exists(), "the next brief still fires"

    def test_stop_on_failure_is_not_tripped(self, daemon):
        daemon.brief("a-headerless.md", "# no header")
        daemon.brief("b-named.md", f"#!queue repo={NAMED}")
        daemon.run()
        assert daemon.d.paused_reason is None, daemon.d.paused_reason
        assert daemon.d.failed == [], "a refusal is not a route failure"
        assert daemon.d.consecutive_count == 1, "only the brief that fired counts"

    def test_the_reason_is_printed_and_recorded(self, daemon, capsys):
        daemon.brief("a-headerless.md", "# no header")
        daemon.run()
        out = capsys.readouterr().out
        assert f"[QUEUE] REFUSED: a-headerless.md — {REASON}" in out, out
        [entry] = daemon.d.refused
        assert entry["file"] == "a-headerless.md" and entry["reason"] == REASON
        persisted = json.loads(daemon.state_file.read_text())
        assert [e["reason"] for e in persisted["refused"]] == [REASON]

    @pytest.mark.parametrize("first_line", [
        "#!queue model=m effort=e",                 # a header, no repo=
        "#!queue model=m effort=e repo=",           # repo= with no value
        "# Title — ## Repo: below is not the queue header",
    ], ids=["header-without-repo", "empty-repo", "no-header"])
    def test_every_shape_of_unnamed_is_refused(self, daemon, first_line):
        daemon.brief("a.md", first_line)
        (daemon.queue / "a.md").write_text(f"{first_line}\n\n## Repo: {NAMED}\n")
        daemon.run()
        assert daemon.fired() == [] and (daemon.queue / "failed" / "a.md").exists()

    def test_a_refusal_is_not_a_route_record(self, daemon):
        """check-logs judges every completed/failed entry for a readable log. Nothing fired, so
        nothing is recorded there and check-logs stays clean."""
        daemon.brief("a-headerless.md", "# no header")
        daemon.run()
        assert daemon.d.completed == [] and daemon.d.failed == []
        assert daemon.d.find_missing_gate_logs() == []

    def test_negative_control_a_named_brief_fires_with_its_repo(self, daemon):
        daemon.brief("b-named.md", f"#!queue model=m effort=e repo={NAMED}")
        daemon.run()
        assert daemon.d.refused == []
        [argv] = daemon.fired()
        assert argv[argv.index("--repo") + 1] == NAMED

    def test_negative_control_stop_on_failure_is_live_in_this_harness(self, daemon):
        """A named brief whose route FAILS does pause the queue — so the refusal's not pausing it
        above is the refusal's doing, not a harness that cannot pause."""
        (daemon.orch / "exit-code").write_text("1")
        daemon.brief("b-named.md", f"#!queue repo={NAMED}")
        daemon.run()
        assert daemon.d.paused_reason == "stop-on-failure:b-named.md"

    def test_an_unmovable_refusal_pauses_instead_of_spinning(self, daemon, monkeypatch):
        """A refused brief that cannot leave queue/ would be refused again at once, forever."""
        monkeypatch.setattr(queue_daemon, "_safe_move", lambda src, dst: False)
        daemon.brief("a-headerless.md", "# no header")
        daemon.run()
        assert daemon.d.paused_reason == "refused-unmovable:a-headerless.md", daemon.d.paused_reason
        assert len(daemon.d.refused) == 1 and daemon.fired() == []


class TestQ1NoDaemonDefault:

    def test_a_persisted_repo_and_queue_repo_are_not_applied(self, tmp_path, monkeypatch):
        """The live queue-state.json carries config.repo=clinical-mp from the old default; the old
        daemon also read QUEUE_REPO. Neither names a brief's repo now."""
        monkeypatch.setenv("QUEUE_REPO", NAMED)
        dm = Daemon(tmp_path, monkeypatch, persisted={"config": {"repo": NAMED, "max_consecutive": 25}})
        assert "repo" not in dm.d.config, dm.d.config
        dm.brief("a-headerless.md", "# no header")
        dm.run()
        assert dm.fired() == [] and (dm.queue / "failed" / "a-headerless.md").exists()

    def test_the_start_line_says_so(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("QUEUE_REPO", "clinical-mp")
        dm = Daemon(tmp_path, monkeypatch, persisted={"config": {"repo": "yorsie"}})
        dm.run()
        line = next(l for l in capsys.readouterr().out.splitlines() if "🛡 repo:" in l)
        assert "refused" in line and "queue-state.json repo=yorsie" in line and "QUEUE_REPO=clinical-mp" in line

    def test_queue_repos_are_only_the_named_ones(self, daemon):
        daemon.brief("a-headerless.md", "# no header")
        daemon.brief("b-named.md", f"#!queue repo={NAMED}")
        assert [r.name for r in daemon.d.queue_repos()] == [NAMED]

    def test_repo_is_not_settable_and_the_refusal_says_why(self, daemon):
        err = daemon.d.update_config("repo", NAMED)["error"]
        assert "#!queue repo=" in err and "refused" in err and "no default" in err, err


# ═══════════════════════════════════════════════════════
# Q2 · no code path resolves a repo without an explicit name
# ═══════════════════════════════════════════════════════
# A repo resolved without its name being given: a `default:` lookup in repos.yaml, the daemon's
# QUEUE_REPO / config fallback, a header read with a fallback value.
DEFAULT_LOOKUPS = (
    (r"""\.get\(\s*["']default["']""", "a `default:` lookup in repos.yaml"),
    (r"""environ(?:\.get\(|\[)\s*["']QUEUE_REPO["']""", "QUEUE_REPO read"),
    (r"""config\[\s*["']repo["']\s*\]""", "the daemon's configured repo read"),
    # a repo read with a fallback value; a display's `'?'` placeholder (show_status) resolves nothing
    (r"""\.get\(\s*["']repo["']\s*,(?!\s*["']\?["'])""", "a repo read with a fallback"),
)
SCANNED = ("orchestrator.py", "queue_daemon.py", "repo_config.py")


def _default_lookups(src: str) -> list:
    return [why for pat, why in DEFAULT_LOOKUPS if re.search(pat, src)]


def _module_level_calls(src: str, fn: str) -> list:
    """Top-level statements of a module that call `fn` — what runs at import."""
    out = []
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and getattr(sub.func, "id", None) == fn:
                out.append(sub.lineno)
    return out


class TestQ2SourceScan:

    def test_repos_yaml_declares_no_default(self):
        text = (ROOT / "config" / "repos.yaml").read_text()
        repos = yaml.safe_load(text)["repos"]
        assert [n for n, r in repos.items() if "default" in r] == []
        assert not re.search(r"^\s*default\s*:", text, re.M), "not even `default: false`"

    @pytest.mark.parametrize("name", SCANNED)
    def test_no_default_lookup_in_source(self, name):
        assert _default_lookups((ROOT / name).read_text()) == [], name

    @pytest.mark.parametrize("old", [
        'name = next(n for n, r in repos.items() if r.get("default"))',          # orchestrator.py:153
        '"repo": os.environ.get("QUEUE_REPO", "clinical-mp"),',                  # queue_daemon.py:329
        'b_repo = hdr.get("repo", self.config["repo"])',                          # queue_daemon.py:729
        "    if r.get('default'):",                                                # repo_config.py:14
    ])
    def test_negative_control_the_scan_finds_the_old_lookups(self, old):
        assert _default_lookups(old), old

    def test_a_display_placeholder_is_not_a_lookup(self):
        assert _default_lookups("print(f\"    Repo:     {data.get('repo', '?')}\")") == []

    def test_nothing_at_import_picks_a_repo(self):
        assert _module_level_calls((ROOT / "orchestrator.py").read_text(), "set_active_repo") == []
        assert _module_level_calls("set_active_repo()\n", "set_active_repo") == [1], "negative control"

    def test_set_active_repo_takes_no_default(self):
        param = inspect.signature(orchestrator.set_active_repo).parameters["name"]
        assert param.default is inspect.Parameter.empty
        with pytest.raises(RuntimeError, match="no repo named"):
            orchestrator.set_active_repo("")


class TestQ2Loader:

    def _cfg(self, tmp_path, monkeypatch, **extra):
        p = tmp_path / "repos.yaml"
        p.write_text(yaml.safe_dump({"repos": {"a": {"project_dir": str(tmp_path), **extra}, "b": {"project_dir": "/x"}}}))
        monkeypatch.setattr(orchestrator, "REPOS_CONFIG_PATH", p)

    def test_a_default_in_repos_yaml_is_refused(self, tmp_path, monkeypatch):
        self._cfg(tmp_path, monkeypatch, default=True)
        with pytest.raises(RuntimeError, match=r"default.*a"):
            orchestrator.load_repo_config()

    def test_negative_control_no_default_loads(self, tmp_path, monkeypatch):
        self._cfg(tmp_path, monkeypatch)
        assert set(orchestrator.load_repo_config()["repos"]) == {"a", "b"}

    def test_the_helper_shim_names_its_repo(self):
        """repo_config.load_default_repo_config() is imported at module load by four helper scripts
        outside this route's scope. It keeps them working by NAMING yorsie — no `default:` lookup."""
        name, cfg = repo_config.load_default_repo_config()
        assert name == repo_config.HELPER_REPO == "yorsie"
        assert cfg == yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["repos"]["yorsie"]
        with pytest.raises(RuntimeError, match="Unknown repo"):
            repo_config.load_repo_config("no-such-repo")


# ── the CLI ───────────────────────────────────────────────────────────────────────────────────
REPO_GLOBALS = ("ACTIVE_REPO_NAME", "ACTIVE_REPO_CONFIG", "PROJECT_ROOT", "YORSIE_DIR", "BRIEFS_DIR",
                "WORKTREE_BASE", "BRANCH_PREFIX", "MERGE_TARGET", "REMOTE", "LOG_SUBDIR", "WORKTREE_MODE",
                "TEST_CMD", "IS_META_FIRE", "TONI_MODEL", "TONI_EFFORT", "PREFIRE_BYPASS", "SKIP_SIT")


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """main() with every effect replaced: run_batch / run_queue record the repo they were handed."""
    for g in REPO_GLOBALS:
        monkeypatch.setattr(orchestrator, g, getattr(orchestrator, g))
    seen = []
    now = orchestrator.datetime.now().isoformat()

    def _run_batch(bf, worktree=None):
        seen.append(orchestrator.ACTIVE_REPO_NAME)
        return orchestrator.Result(batch_file=bf.name, status=orchestrator.Status.PASSED, started=now,
                                   finished=now, duration_s=0.0, exit_code=0, briefs=1)

    monkeypatch.setattr(orchestrator, "run_batch", _run_batch)
    monkeypatch.setattr(orchestrator, "run_queue", lambda files, **k: [_run_batch(f) for f in files])
    monkeypatch.setattr(orchestrator, "_check_stale_marker", lambda *a, **k: True)
    monkeypatch.setattr(orchestrator, "approval_gate", lambda *a, **k: True)
    monkeypatch.setattr(orchestrator, "rate_check", lambda *a, **k: True)
    monkeypatch.setattr(orchestrator, "load_state", lambda: {"completed": [], "failed": []})
    monkeypatch.setattr(orchestrator, "save_state", lambda s: None)
    monkeypatch.setattr(orchestrator, "show_status", lambda: seen.append(orchestrator.ACTIVE_REPO_NAME))
    monkeypatch.setattr(orchestrator, "handback_scan", lambda paths, until: 0)

    def main(*argv):
        """The exit code main() leaves with — 0 for a command that returns without exiting."""
        monkeypatch.setattr(sys, "argv", ["orchestrator.py", *argv])
        try:
            orchestrator.main()
        except SystemExit as e:
            return e.code
        return 0

    def brief(name, text):
        p = tmp_path / name
        p.write_text(text)
        return str(p)

    return types.SimpleNamespace(main=main, brief=brief, seen=seen)


class TestQ2Cli:

    def test_a_brief_that_names_no_repo_is_refused(self, cli, capsys):
        b = cli.brief("x.md", "# no header, no ## Repo:\n- id: B1\n")
        assert cli.main("run", b, "--approve") == 1
        assert cli.seen == [], "nothing fired"
        err = capsys.readouterr().err
        assert "no repo named" in err and "x.md" in err and "refused, nothing fired" in err, err

    @pytest.mark.parametrize("text,argv,repo", [
        ("#!queue repo=clinical-mp\n- id: B1\n", (), "clinical-mp"),
        ("# t\n## Repo: orchestrator\n- id: B1\n", (), "orchestrator"),
        ("# t\n- id: B1\n", ("--repo", "orchestrator"), "orchestrator"),
    ], ids=["queue-header", "repo-header", "--repo"])
    def test_negative_control_a_named_repo_runs(self, cli, text, argv, repo):
        assert cli.main("run", cli.brief("x.md", text), "--approve", *argv) == 0
        assert cli.seen == [repo]

    def test_briefs_that_name_different_repos_are_refused(self, cli, capsys):
        a = cli.brief("a.md", "#!queue repo=clinical-mp\n")
        b = cli.brief("b.md", "#!queue repo=orchestrator\n")
        assert cli.main("queue", a, b, "--approve") == 1 and cli.seen == []
        assert "clinical-mp, orchestrator" in capsys.readouterr().err

    def test_one_unnamed_brief_in_a_queue_refuses_the_queue(self, cli, capsys):
        a = cli.brief("a.md", "#!queue repo=clinical-mp\n")
        b = cli.brief("b.md", "# no repo\n")
        assert cli.main("queue", a, b, "--approve") == 1 and cli.seen == []
        assert "b.md" in capsys.readouterr().err

    def test_status_names_a_repo_or_is_refused(self, cli):
        assert cli.main("status") == 1 and cli.seen == []
        assert cli.main("status", "--repo", "orchestrator") == 0 and cli.seen == ["orchestrator"]

    def test_negative_control_a_repo_free_command_needs_none(self, cli):
        assert cli.main("handback-scan") == 0


# ═══════════════════════════════════════════════════════
# Q3 · Yorsie merges only what builds
# ═══════════════════════════════════════════════════════
def _git(cmd: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True)


def _sha(rev: str, cwd: Path) -> str:
    return _git(f"git rev-parse {rev}", cwd).stdout.strip()


# The stub yorsie package: `npm run build` runs build.sh, which records where it ran, on which
# branch and whether a secret from an env file reached it, then exits with the code in build-exit.
BUILD_SH = '''\
pwd -P > "$YS_PROBE"
git rev-parse --abbrev-ref HEAD >> "$YS_PROBE"
echo "${YS_SECRET:-unset}" >> "$YS_PROBE"
code=$(cat build-exit)
[ "$code" = 0 ] || echo "src/broken.ts(1,7): error TS2322: Type 'string' is not assignable to type 'number'." >&2
exit "$code"
'''


class YorsieRoute:

    def __init__(self, tmp_path: Path, monkeypatch):
        for g in REPO_GLOBALS:
            monkeypatch.setattr(orchestrator, g, getattr(orchestrator, g))
        self.proj = tmp_path / "dev-pipeline"
        y = self.proj / "yorsie"
        (y / "briefs").mkdir(parents=True)
        _git("git init", self.proj)
        _git("git config user.email t@t && git config user.name T", self.proj)
        _git("git symbolic-ref HEAD refs/heads/main", self.proj)
        (y / "package.json").write_text(json.dumps({"name": "stub", "private": True,
                                                    "scripts": {"build": "sh ./build.sh"}}))
        (y / "build.sh").write_text(BUILD_SH)
        (y / "build-exit").write_text("0")
        # The secrets a gate must never see: env_file None sources neither.
        (self.proj / ".gitignore").write_text(".env\n")
        (self.proj / ".env").write_text("YS_SECRET=leaked-root\n")
        (y / ".gitignore").write_text(".env\n")
        (y / ".env").write_text("YS_SECRET=leaked-yorsie\n")
        self.brief = y / "briefs" / "batch-ys.md"
        self.brief.write_text("- id: B1\n  title: demo\n\n## Estimated runtime: 45-75 min\n")
        _git("git add -A && git commit -m init", self.proj)
        self.main_before = _sha("main", self.proj)
        self.branch = "orch-batch-ys"
        self.probe = tmp_path / "probe.txt"
        monkeypatch.setenv("YS_PROBE", str(self.probe))
        monkeypatch.delenv("YS_SECRET", raising=False)
        monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)

        # The REAL yorsie entry, pointed at the stub. Its unit leg (test_cmd) is not under test here.
        entry = dict(yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["repos"]["yorsie"])
        entry.update(project_dir=str(self.proj), worktree_base=str(tmp_path / "yorsie-toni"))
        entry.pop("test_cmd", None)
        cfg = tmp_path / "repos.yaml"
        cfg.write_text(yaml.safe_dump({"repos": {"yorsie": entry}}))
        monkeypatch.setattr(orchestrator, "REPOS_CONFIG_PATH", cfg)
        orchestrator.set_active_repo("yorsie")

        monkeypatch.setattr(orchestrator, "RUN_PLAYWRIGHT", False)
        monkeypatch.setattr(orchestrator, "SIT_ARCHIVE_DIR", tmp_path / "archive")
        monkeypatch.setattr(orchestrator, "get_migrations", lambda: set())
        monkeypatch.setattr(orchestrator, "notify", lambda r: None)
        monkeypatch.setattr(orchestrator, "find_unblocked", lambda *a, **k: [])
        monkeypatch.setattr(orchestrator.rate_limiter, "record", lambda *a, **k: None)
        self.monkeypatch = monkeypatch

    def fire(self, build_exit: str):
        """One route through the real _run_batch_inner and the REAL run_pre_merge_gates. The
        executor commits a change on the route branch; build_exit is what that tree's build returns."""
        log = self.proj.parent / "toni-test.log"

        def _toni(target, proj):
            (proj / "yorsie" / "build-exit").write_text(build_exit)
            (proj / "yorsie" / "feature.ts").write_text("export const n: number = 1;\n")
            _git('git add -A && git commit -m "feat: work"', proj)
            self.route_tip = _sha("HEAD", proj)
            log.write_text(f"=== TONI EXECUTION ===\n{'=' * 60}\n\nDone.\n\n{'=' * 60}\nExit: 0\n")
            return 0, str(log)

        self.monkeypatch.setattr(orchestrator, "fire_toni", _toni)
        return orchestrator._run_batch_inner(self.brief, self.proj, orchestrator.datetime.now(), worktree=None)

    def probed(self) -> list:
        return self.probe.read_text().splitlines()


@pytest.fixture
def yorsie(tmp_path, monkeypatch):
    return YorsieRoute(tmp_path, monkeypatch)


class TestQ3Wiring:

    def test_yorsie_is_build_gated_with_no_env_file(self):
        assert orchestrator.PRE_MERGE_GATES["yorsie"] == {"gates": ("build",), "env_file": None}
        repos = yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["repos"]
        assert repos["yorsie"]["build_gate_cmd"] == "cd yorsie && npm run build"

    def test_negative_control_the_other_lanes_are_unchanged(self):
        assert orchestrator.PRE_MERGE_GATES["clinical-mp"] == {"gates": ("build", "sit"), "env_file": ".env"}
        assert orchestrator.PRE_MERGE_GATES["orchestrator"] == {"gates": ("build",), "env_file": None}


class TestQ3Route:

    def test_a_branch_that_does_not_build_is_not_merged(self, yorsie):
        r = yorsie.fire(build_exit="1")
        assert _sha("main", yorsie.proj) == yorsie.main_before, "main must not move"
        assert r.status is orchestrator.Status.FAILED
        assert r.gate_outcome == orchestrator.GateOutcome.FAIL_PRODUCT.value, r.gate_outcome
        assert _sha(yorsie.branch, yorsie.proj) == yorsie.route_tip, "branch preserved for review"

    def test_negative_control_a_branch_that_builds_merges(self, yorsie):
        r = yorsie.fire(build_exit="0")
        assert r.status is orchestrator.Status.PASSED, r.error
        assert r.gate_outcome == orchestrator.GateOutcome.PASS.value
        assert _sha("main", yorsie.proj) == yorsie.route_tip

    def test_the_build_runs_in_the_routes_checkout_on_the_route_branch(self, yorsie):
        yorsie.fire(build_exit="1")
        cwd, branch, secret = yorsie.probed()
        assert cwd == str((yorsie.proj / "yorsie").resolve()), cwd
        assert branch == yorsie.branch, f"the gate built {branch}, not the route branch"
        assert secret == "unset", "env_file None: no .env is sourced into the yorsie gate"

    def test_negative_control_the_probe_sees_an_env_file_when_one_is_declared(self, yorsie, monkeypatch):
        monkeypatch.setitem(orchestrator.PRE_MERGE_GATES, "yorsie", {"gates": ("build",), "env_file": "yorsie/.env"})
        yorsie.fire(build_exit="0")
        assert yorsie.probed()[2] == "leaked-yorsie"

    def test_red_reproduction_an_ungated_yorsie_merges_a_broken_build(self, yorsie, monkeypatch):
        """What the route found: yorsie absent from PRE_MERGE_GATES ⇒ a branch that does not build
        merges. The entry, and only the entry, is what stops it."""
        monkeypatch.delitem(orchestrator.PRE_MERGE_GATES, "yorsie", raising=False)
        r = yorsie.fire(build_exit="1")
        assert r.status is orchestrator.Status.PASSED and _sha("main", yorsie.proj) == yorsie.route_tip
        assert not yorsie.probe.exists(), "no build ran"


# ═══════════════════════════════════════════════════════
# Q4 · qstat.sh shows the daemon's own state
# ═══════════════════════════════════════════════════════
class QstatHome:
    """$HOME/spectricom-orchestrator under tmp_path — qstat.sh reads `~/spectricom-orchestrator`."""

    def __init__(self, tmp_path: Path):
        self.home = tmp_path
        self.orch = tmp_path / "spectricom-orchestrator"
        (self.orch / "queue").mkdir(parents=True)
        (self.orch / "state").mkdir()

    def state(self, **fields):
        (self.orch / "queue-state.json").write_text(json.dumps(fields))

    def queued(self, *names):
        for n in names:
            (self.orch / "queue" / n).write_text(f"#!queue repo=x\n# {n}\n")

    def run(self) -> str:
        env = {**os.environ, "HOME": str(self.home)}
        r = subprocess.run(["bash", str(ROOT / "qstat.sh")], capture_output=True, text=True, env=env, timeout=60)
        return r.stdout + r.stderr


@pytest.fixture
def qstat(tmp_path):
    return QstatHome(tmp_path)


class TestQ4Qstat:

    def test_paused_prints_why_and_since_when(self, qstat):
        pid = os.getpid()
        qstat.state(daemon_status="paused", paused_reason="max-consecutive:10",
                    paused_at="2026-10-04T01:02:03.456789", pid=pid, current_batch=None)
        qstat.queued("95-a.md", "96-b.md")
        out = qstat.run()
        assert (f"⏸️  DAEMON PAUSED | pid={pid} alive | daemon_status=paused | paused_reason=max-consecutive:10 "
                f"| paused_at=2026-10-04T01:02:03.456789") in out, out
        assert "📥 QUEUED 2 brief(s) waiting" in out, out
        assert "idle" not in out, "paused must never read as idle"

    def test_negative_control_running_prints_running_and_the_route(self, qstat):
        pid = os.getpid()
        qstat.state(daemon_status="running", paused_reason=None, paused_at=None, pid=pid,
                    current_batch={"file": "94-x.md", "started_at": "2026-10-04T01:50:30.4"})
        qstat.queued("94-x.md", "95-a.md")
        out = qstat.run()
        assert f"✅ DAEMON running | pid={pid} alive | daemon_status=running | paused_reason=- | paused_at=-" in out, out
        assert "▶️  RUNNING 94-x.md | since 2026-10-04T01:50:30.4" in out, out
        assert "📥 QUEUED 1 brief(s) waiting" in out, "the running brief is not counted as waiting"
        assert "PAUSED" not in out

    def test_a_dead_daemon_never_reads_as_running(self, qstat):
        dead = _dead_pid()
        qstat.state(daemon_status="running", paused_reason=None, paused_at=None, pid=dead, current_batch=None)
        out = qstat.run()
        assert f"❌ DAEMON DEAD | pid={dead} dead | daemon_status=running" in out, out
        assert "✅ DAEMON" not in out

    def test_no_state_file_says_so(self, qstat):
        out = qstat.run()
        assert "⚪ NO DAEMON STATE | no queue-state.json" in out, out
        assert "📥 QUEUED 0 brief(s) waiting" in out, out

    def test_no_fire_lock_is_not_called_idle(self, qstat):
        qstat.state(daemon_status="paused", paused_reason="operator", paused_at="t", pid=os.getpid())
        out = qstat.run()
        assert "⚪ NO ROUTE | no state/running.json — no fire in progress" in out, out
        assert "NO QUEUE" not in out
