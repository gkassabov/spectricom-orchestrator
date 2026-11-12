"""[ORCH-NPM-FROZEN-1] Kanban 663, OC-3 (D-S7CORE51-18) — predicates P-N1..P-N7 of
briefs/662-663-orch-guard-self-npm-frozen-1.md Part B: executor/hooks/npm_frozen.py, the executor's PreToolUse Bash
hook, lets through only an allow-list of npm subcommands, npx only no-install for a tool already in
node_modules/.bin, and npm install only for the exact dependency TONI_DEP_CHANGES carries; and every settings file
runs it. Every case runs `python3 <worktree>/executor/hooks/npm_frozen.py`; no test runs npm, npx or claude."""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.guards

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "executor" / "hooks" / "npm_frozen.py"
SETTINGS = ROOT / "executor" / "settings"
REPOS = sorted(yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["repos"])
MSG_I = "the executor may run only npm ci, npm run <script>"
MSG_II = "re-run it as 'npx --no-install"
MSG_IV = "this fire's approved dependency change is"
KILL_CMD = 'bash "${TONI_GUARDS_HOME:-$HOME/spectricom-orchestrator}/executor/hooks/kill_switch.sh" || exit 2'
GN2_CMD = ('f="${TONI_GUARDS_HOME:-$HOME/spectricom-orchestrator}/executor/hooks/npm_frozen.py"; '
           '{ [ -r "$f" ] && command -v python3 >/dev/null; } || { echo "🛡 npm frozen: the hook could not run (no $f '
           'or no python3) — the Bash call is denied (fails closed). Stop and say so in the handback." >&2; exit 2; }; '
           'python3 "$f" || exit 2')


@pytest.fixture
def tree(tmp_path):
    """A scratch project: node_modules/.bin holds tsc, vitest and tsx stubs; yorsie/ is its own package whose .bin
    holds vitest only; src/ has no package.json."""
    root = tmp_path / "proj"
    for d, tools in ((root, ("tsc", "vitest", "tsx")), (root / "yorsie", ("vitest",))):
        b = d / "node_modules" / ".bin"
        b.mkdir(parents=True)
        (d / "package.json").write_text("{}\n")
        for t in tools:
            (b / t).write_text("#!/bin/sh\n")
            (b / t).chmod(0o755)
    (root / "src").mkdir()
    return root


def _env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in ("TONI_NPM_FROZEN", "TONI_DEP_CHANGES")}
    env.update(extra)
    return env


def run(cmd, cwd, stdin=None, **env):
    payload = stdin if stdin is not None else json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd},
                                                          "cwd": str(cwd)})
    return subprocess.run(["python3", str(HOOK)], input=payload, capture_output=True,
                          text=True, env=_env(**env), timeout=30)


def refused(r, needle=MSG_I):
    return r.returncode == 2 and r.stderr.startswith("🛡 npm frozen: '") and needle in r.stderr


# ── P-N1 · npm refused, message i ───────────────────────────────────────────
P_N1 = ["npm install", "npm i lodash", "npm add -D x", "npm isntall", "npm update", "npm up x", "npm uninstall x",
        "npm rm x", "npm link", "npm dedupe", "npm prune", "npm audit fix", "npm audit --fix", "npm audit --json fix",
        "npm audit fix --force", "npm audit --force", "npm rebuild", "npm pack", "npm exec -- tsc", "npm x tsc",
        "npm cit", "npm clean-install", "npm", "npm run", "npm install --package-lock-only",
        "npm --prefix yorsie install", "npm -C yorsie i", "npm -w app install x", "cd yorsie && npm install",
        "npm run build; npm install", "(cd yorsie && npm up)", "echo $(npm install)", 'echo "$(npm install)"',
        "echo `npm i`", "A=1 B=2 npm install", "env -u X FOO=1 npm install", "sudo npm install -g x",
        "timeout 60 npm install", "nice -n 5 npm ci && npm install", "bash -c 'npm install'",
        'sh -lc "cd x && npm i y"', "eval 'npm i x'", "bash <<'EOF'\nnpm install\nEOF",
        "/home/gkassa/.nvm/versions/node/v22.22.1/bin/npm install", "pnpm install", "pnpm run build", "yarn",
        "yarn test", "ls\nnpm install",
        # prefixes and abbreviations (verifier M2)
        "npm upd x", "npm updat", "npm upda", "npm dedup", "npm prun", "npm uninst x", "npm shrinkwrap", "npm shr",
        "npm insta", "npm ru build", "npm tst", "npm vie x", "npm l", "npm aud",
        # neighbours: reserved words, wrappers, quoting, substitutions, here-strings, an unparsable case pattern
        "{ npm install; }", "if true; then npm i x; fi", "echo x | xargs -n1 npm install", "env -S 'npm install'",
        '"npm" install', "n\\pm install", "stdbuf -oL npm install", "time -p npm i", ">/dev/null npm install",
        "cat <(npm install)", "x=$(npm i)", 'bash -o pipefail -c "npm i"', 'bash <<< "npm i x"',
        "case x in a) npm i;; esac", "npm audit fix -f", "npm audit -f"]


@pytest.mark.parametrize("cmd", P_N1)
def test_PN1_npm_outside_the_allow_list_is_refused(tree, cmd):
    r = run(cmd, tree)
    assert refused(r), (r.returncode, r.stderr)
    assert "Do not retry another way: STOP and say so in the handback." in r.stderr
    assert len(r.stderr.strip().splitlines()) == 1


def test_PN1_a_script_file_passed_to_bash_is_judged(tree, tmp_path):
    (tmp_path / "x.sh").write_text("set -e\nnpm install\n")
    assert refused(run("bash %s" % (tmp_path / "x.sh"), tree))
    (tmp_path / "ok.sh").write_text("set -e\nnpm ci\n")
    assert run("bash %s" % (tmp_path / "ok.sh"), tree).returncode == 0


def test_PN1_the_message_names_the_simple_command_within_120_chars(tree):
    r = run("npm ci && npm install " + "x" * 300, tree)
    assert refused(r)
    named = r.stderr.split("'")[1]
    assert named.startswith("npm install xxx") and len(named) <= 120


# ── P-N2 · allowed, exit 0, nothing printed ─────────────────────────────────
P_N2 = ["npm ci", "npm ci --ignore-scripts --no-audit --no-fund", "npm ci --legacy-peer-deps", "cd yorsie && npm ci",
        "npm run sit:gate", "npm run-script build", "npm --prefix yorsie run build", "npm test",
        "npm test -- src/x.test.ts", "npm t", "npm ls", "npm ls --depth 0", "npm view x version", "npm audit",
        "npm audit --omit=dev", "npm audit --json", "npm audit signatures", "npm --version", "npm -v",
        'git commit -m "routes use npm ci, never npm install"', 'grep -n "npm install" README.md', "echo npm install",
        "cat package.json | grep install", "ls node_modules | wc -l",
        # heredoc and commit-message data (verifier M1)
        "git commit -F - <<'EOF'\nGeorge's rule: routes never run npm install\nEOF",
        "git commit -m \"$(cat <<'EOF'\nfix: the hook refuses `npm install` (George's \"oc-3 amend\")\n\n"
        "Co-Authored-By: x\nEOF\n)\"",
        "cat > /tmp/notes.md <<'EOF'\nnpm install is refused by the hook\nnpx cowsay too\nEOF",
        "cat <<-EOF\n\tnpm install\n\tEOF",
        "git commit -m 'never run npm install; use npm ci'", 'git commit --message="npm update is refused"',
        # neighbours: redirections, comments, pipelines
        "npm ci 2>&1 | tail -5", "npm test > /tmp/out.log 2>&1", "echo hi # npm install"]


@pytest.mark.parametrize("cmd", P_N2)
def test_PN2_allowed_commands_and_data_pass_silently(tree, cmd):
    r = run(cmd, tree)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_PN2_an_unquoted_heredoc_runs_its_substitutions(tree):
    """bash expands $(…) and `…` in a heredoc whose delimiter is unquoted: those spans are commands."""
    assert refused(run("cat <<EOF\n$(npm install)\nEOF", tree))
    assert run("cat <<'EOF'\n$(npm install)\nEOF", tree).returncode == 0


# ── P-N3 · npx ──────────────────────────────────────────────────────────────
P_N3_OK = ["npx --no-install tsc --noEmit", "npx --yes=false vitest run src/x.test.ts", "npx --no -- tsx scripts/x.ts",
           "cd yorsie && npx --no-install vitest run", "npx --no-install tsc -b && npx --no-install vitest run x",
           "cd src && npx --no-install tsc --noEmit"]


@pytest.mark.parametrize("cmd", P_N3_OK)
def test_PN3_npx_no_install_for_an_installed_tool_passes(tree, cmd):
    r = run(cmd, tree)
    assert (r.returncode, r.stderr) == (0, "")


@pytest.mark.parametrize("cmd", ["npx tsc --noEmit", "npx --no tsc --noEmit"])
def test_PN3_npx_without_a_no_install_form_is_told_the_form(tree, cmd):
    r = run(cmd, tree)
    assert r.returncode == 2 and "re-run it as 'npx --no-install tsc" in r.stderr
    assert "STOP" not in r.stderr                     # a retry in that form is expected


P_N3_III = ["npx --no-install cowsay hi", "npx --no-install eslint .", "cd yorsie && npx --no-install tsc",
            "npx --no-install vitest@4.1.4 run", "npx --no-install @scope/tool", "npx --no-install ./node_modules/.bin/tsc",
            "npx --no-install github:a/b", "npx --no-install no-such-zz9", "npx -y tsc", "npx -y cowsay", "npx --yes tsc",
            "npx --yes=true tsc", "npx -p tsc --no-install tsc", "npx --no-install --package=x y",
            "npx --no-install -p x y", "npx --no-install --registry https://x.test tsc", "npx -c 'tsc'", "npx x@1.0.0",
            "cd $HOME/x && npx --no-install tsc"]


@pytest.mark.parametrize("cmd", P_N3_III)
def test_PN3_npx_that_could_download_is_refused(tree, cmd):
    r = run(cmd, tree)
    assert r.returncode == 2 and "is not in" in r.stderr and "node_modules/.bin" in r.stderr, r.stderr
    assert "STOP and say so in the handback" in r.stderr


def test_PN3_the_missing_tool_message_names_the_directory(tree):
    r = run("cd yorsie && npx --no-install tsc", tree)
    assert "'tsc' is not in %s/node_modules/.bin" % (tree / "yorsie") in r.stderr


def test_PN3_npx_npm_is_judged_as_npm(tree):
    assert refused(run("npx --no-install npm install", tree))


# ── P-N4 · a George-approved dependency change ──────────────────────────────
DEV = '[{"pkg":"vitest-axe","version":"0.1.0","kind":"dev"}]'
PROD = '[{"pkg":"zod","version":"3.23.8","kind":"prod"}]'


@pytest.mark.parametrize("cmd", ["npm install vitest-axe@0.1.0 --save-exact -D", "npm install -D --save-exact vitest-axe@0.1.0",
                                 "npm install vitest-axe@0.1.0 --save-exact --save-dev"])
def test_PN4_the_approved_dev_install_passes(tree, cmd):
    r = run(cmd, tree, TONI_DEP_CHANGES=DEV)
    assert (r.returncode, r.stderr) == (0, "")


P_N4_IV = ["--ignore-scripts", "--registry https://x.test", "--force", "-g", "--legacy-peer-deps", "--ignore-scripts=false",
           "--foreground-scripts", "--package-lock-only"]
P_N4_IV_CMDS = (["npm install vitest-axe@0.1.0 --save-exact -D " + w for w in P_N4_IV]
                + ["npm install vitest-axe@next --save-exact -D", "npm install vitest-axe@~0.1.0 --save-exact -D",
                   "npm install vitest-axe@0.1.0 -D", "npm install vitest-axe@0.1.0 --save-exact",
                   "npm install vitest-axe@0.1.1 --save-exact -D", "npm install vitest-axe@^0.1.0 --save-exact -D",
                   "npm install vitest-axe@latest --save-exact -D", "npm install vitest-axe --save-exact -D",
                   "npm install lodash@4.17.21 --save-exact -D",
                   "npm install vitest-axe@0.1.0 lodash@4.17.21 --save-exact -D",
                   "npm --prefix x install vitest-axe@0.1.0 --save-exact -D"])


@pytest.mark.parametrize("cmd", P_N4_IV_CMDS)
def test_PN4_anything_else_is_refused_naming_the_approved_change(tree, cmd):
    r = run(cmd, tree, TONI_DEP_CHANGES=DEV)
    assert refused(r, MSG_IV + " vitest-axe@0.1.0 (dev): only 'npm install vitest-axe@0.1.0 --save-exact -D' is allowed"), r.stderr


@pytest.mark.parametrize("cmd", ["npm i vitest-axe@0.1.0 --save-exact -D", "npm add vitest-axe@0.1.0 --save-exact -D"])
def test_PN4_i_and_add_are_never_the_install(tree, cmd):
    assert refused(run(cmd, tree, TONI_DEP_CHANGES=DEV))


def test_PN4_a_prod_change(tree):
    assert run("npm install zod@3.23.8 --save-exact", tree, TONI_DEP_CHANGES=PROD).returncode == 0
    r = run("npm install zod@3.23.8 --save-exact -D", tree, TONI_DEP_CHANGES=PROD)
    assert refused(r, MSG_IV + " zod@3.23.8 (prod): only 'npm install zod@3.23.8 --save-exact' is allowed")


@pytest.mark.parametrize("value", [None, "", "not json", "{}", '[{"pkg":"zod"}]',
                                   '[{"pkg":"zod","version":"^3","kind":"prod"}]'])
def test_PN4_no_valid_change_allows_no_install(tree, value):
    env = {} if value is None else {"TONI_DEP_CHANGES": value}
    assert refused(run("npm install zod@3.23.8 --save-exact", tree, **env))


# ── P-N5 · a command the parser cannot read ─────────────────────────────────
@pytest.mark.parametrize("cmd, code", [('npm install "x', 2), ('npx "tsc', 2), ('echo "unbalanced', 0),
                                       ('git commit -m "it\'s npm install', 0)])
def test_PN5_unreadable_commands_scan_command_positions_only(tree, cmd, code):
    r = run(cmd, tree)
    assert r.returncode == code, r.stderr
    if code:
        assert refused(r)


# ── P-N6 · input, crash, off ────────────────────────────────────────────────
@pytest.mark.parametrize("stdin", ["not json", "[]", '{"tool_name": "Bash"}',
                                   '{"tool_name": "Bash", "tool_input": {"command": 5}}'])
def test_PN6_unreadable_input_denies(tree, stdin):
    r = run(None, tree, stdin=stdin)
    assert r.returncode == 2 and "could not read its input" in r.stderr


def test_PN6_another_tool_is_not_judged(tree):
    r = run(None, tree, stdin='{"tool_name": "Read", "tool_input": {"file_path": "x"}}')
    assert (r.returncode, r.stderr) == (0, "")


def test_PN6_a_crash_denies(monkeypatch):
    spec = importlib.util.spec_from_file_location("npm_frozen_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def boom(_text):
        raise RuntimeError("parser broke")
    monkeypatch.setattr(mod, "split_commands", boom)
    err = io.StringIO()
    code = mod.main(io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})), {}, err)
    assert code == 2 and "🛡 npm frozen: the hook failed (RuntimeError)" in err.getvalue()


@pytest.mark.parametrize("value, code", [("Off", 0), (" OFF ", 0), ("of", 2), ("0", 2)])
def test_PN6_toni_npm_frozen_off_allows_everything(tree, value, code):
    assert run("npm install", tree, TONI_NPM_FROZEN=value).returncode == code


def test_PN6_no_cwd_uses_the_hooks_own_directory(tree):
    r = subprocess.run(["python3", str(HOOK)], input=json.dumps({"tool_input": {"command": "npx --no-install tsc"}}),
                       capture_output=True, text=True, env=_env(), cwd=str(tree / "src"), timeout=30)
    assert (r.returncode, r.stderr) == (0, "")


# ── P-N7 · every settings file runs it on Bash ──────────────────────────────
def _pre(repo):
    return json.loads((SETTINGS / ("%s.json" % repo)).read_text())["hooks"]["PreToolUse"]


@pytest.mark.parametrize("repo", REPOS)
def test_PN7_the_settings_file_runs_the_kill_hook_then_the_npm_hook(repo):
    assert _pre(repo) == [{"matcher": "*", "hooks": [{"type": "command", "command": KILL_CMD}]},
                          {"matcher": "Bash", "hooks": [{"type": "command", "command": GN2_CMD}]}]


@pytest.fixture
def home(tmp_path):
    hooks = tmp_path / "home" / "spectricom-orchestrator" / "executor" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "npm_frozen.py").symlink_to(HOOK)
    return tmp_path / "home"


def _via_settings(cmd_string, home, tree, command, path=None):
    env = {"HOME": str(home), "PATH": path or os.environ["PATH"]}
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tree)})
    return subprocess.run([shutil.which("bash"), "-c", cmd_string], input=stdin, capture_output=True, text=True,
                          env=env, timeout=30)


@pytest.mark.parametrize("repo", REPOS)
def test_PN7_the_settings_command_verbatim(repo, home, tree, tmp_path):
    cmd = _pre(repo)[1]["hooks"][0]["command"]
    r = _via_settings(cmd, home, tree, "npm install")
    assert r.returncode == 2 and MSG_I in r.stderr
    assert _via_settings(cmd, home, tree, "npm ci").returncode == 0
    bare = tmp_path / "bare-path"
    bare.mkdir()
    (bare / "bash").symlink_to(shutil.which("bash"))
    r = _via_settings(cmd, home, tree, "npm ci", path=str(bare))
    assert r.returncode == 2 and "🛡 npm frozen: the hook could not run" in r.stderr
    (home / "spectricom-orchestrator" / "executor" / "hooks" / "npm_frozen.py").unlink()
    r = _via_settings(cmd, home, tree, "npm ci")
    assert r.returncode == 2 and "🛡 npm frozen: the hook could not run" in r.stderr
