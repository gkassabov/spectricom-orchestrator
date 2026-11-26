"""[ORCH-NPM-GUARD-TILDE-CD-1] Kanban 979 (ORCH-NPM-GUARD-TILDE-CD-1, 669-585r handback "npm guard note") — the executor's
npm hook follows `cd ~` and `cd ~/…` to its own env's HOME, so `cd ~/<repo> && npx --no-install <tool>` is judged against
that directory's node_modules/.bin instead of being refused as "the directory is not known". `~user`, `$HOME/…`, an
unset or a relative HOME stay unknown (refused, as before). Every case runs `python3 <worktree>/executor/hooks/npm_frozen.py`;
no test runs npm, npx or claude."""
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.guards

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "executor" / "hooks" / "npm_frozen.py"
UNKNOWN = "the directory is not known"


@pytest.fixture
def home(tmp_path):
    """A scratch HOME: proj/ has node_modules/.bin with tsc and vitest; proj/yorsie/ has vitest only."""
    h = tmp_path / "home"
    for d, tools in ((h / "proj", ("tsc", "vitest")), (h / "proj" / "yorsie", ("vitest",))):
        b = d / "node_modules" / ".bin"
        b.mkdir(parents=True)
        (d / "package.json").write_text("{}\n")
        for t in tools:
            (b / t).write_text("#!/bin/sh\n")
            (b / t).chmod(0o755)
    return h


def run(cmd, cwd, home_value):
    env = {k: v for k, v in os.environ.items() if k not in ("TONI_NPM_FROZEN", "TONI_DEP_CHANGES", "HOME")}
    if home_value is not None:
        env["HOME"] = str(home_value)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)})
    return subprocess.run(["python3", str(HOOK)], input=payload, capture_output=True, text=True, env=env, timeout=30)


@pytest.mark.parametrize("cmd", ["cd ~/proj && npx --no-install tsc --noEmit",
                                 "cd ~/proj/yorsie && npx --no-install vitest run",
                                 "cd ~ && cd proj && npx --no-install vitest run x"])
def test_T1_a_tilde_cd_is_followed_to_home(home, tmp_path, cmd):
    r = run(cmd, tmp_path, home)
    assert (r.returncode, r.stderr) == (0, ""), r.stderr


def test_T2_the_followed_directory_is_checked(home, tmp_path):
    r = run("cd ~/proj/yorsie && npx --no-install tsc", tmp_path, home)
    assert r.returncode == 2 and "'tsc' is not in %s/node_modules/.bin" % (home / "proj" / "yorsie") in r.stderr, r.stderr
    assert UNKNOWN not in r.stderr


@pytest.mark.parametrize("cmd", ["cd ~other/proj && npx --no-install tsc", "cd $HOME/proj && npx --no-install tsc",
                                 "cd ~$X && npx --no-install tsc"])
def test_T3_other_forms_stay_unknown(home, tmp_path, cmd):
    r = run(cmd, tmp_path, home)
    assert r.returncode == 2 and UNKNOWN in r.stderr, r.stderr


@pytest.mark.parametrize("home_value", [None, "", "relative/home"])
def test_T4_no_absolute_home_stays_unknown(tmp_path, home_value):
    r = run("cd ~/proj && npx --no-install tsc", tmp_path, home_value)
    assert r.returncode == 2 and UNKNOWN in r.stderr, r.stderr
