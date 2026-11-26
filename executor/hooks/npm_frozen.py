#!/usr/bin/env python3
# filename: executor/hooks/npm_frozen.py
"""[ORCH-NPM-FROZEN-1] The executor's npm guard: a PreToolUse hook, matcher "Bash", in every
executor/settings/<repo>.json (Kanban 663; OC-3's orchestrator half, George 2026-11-11 09:52 "oc-3 amend",
D-S7CORE51-18: routes use `npm ci`, never `npm install`; Gemma's rulings on verifier M1/M2 and the v2 open items;
briefs/662-663-orch-guard-self-npm-frozen-1.md G-N1).

The executor may run only:
  npm ci · npm run <script> (or run-script) · npm test (or t) · npm ls · npm view · npm audit (never audit fix /
  --fix / --force) · npm --version (or -v)
exactly as written: npm resolves any unique prefix of a subcommand (`npm upd` = update, `npm shr` = shrinkwrap), so
only exact, named subcommands pass (an allow-list, never a deny-list). pnpm and yarn are refused whatever follows.
`npx` runs only with one no-install form (`--no-install`, `--yes=false`, or `--no --`; a bare `--no` before the tool
is misread by npx) and only for a plain tool name already in <dir>/node_modules/.bin, searched from the command's
directory up to the first directory holding a package.json. `npm install` is allowed only for the exact dependency
the orchestrator passes in TONI_DEP_CHANGES (a brief's `## Dependency change:` line with George's go; G-N3/G-N4):
`npm install <pkg>@<version> --save-exact` (+ `-D` / `--save-dev` iff dev), nothing else.

Data is never judged as commands (M1): heredoc bodies are dropped (a body fed to bash/sh/zsh/source/. is judged as
commands; an unquoted-delimiter body is expanded by the shell, so its $(…) and `…` spans are judged, as in a
double-quoted string); single-quoted strings are data; double-quoted strings are data except their $(…) and `…`
spans. Only `bash|sh|zsh [-flags] -c '<string>'`, `eval '<string>'`, a script file passed to a shell or `source`,
and a here-string fed to a shell are judged as commands, to depth MAX_DEPTH.

Exit 2 + one `🛡 npm frozen:` stderr line = the CLI blocks the call and shows the line to the model. Exit 0, silent =
no objection. Fails closed: unreadable input or any crash denies. A command the parser cannot read (an unbalanced
quote) is scanned at its command positions only: npm / npx / pnpm / yarn there is refused.
TONI_NPM_FROZEN=off (any case) in the hook's environment allows everything (the fire's env carries the daemon's).

Reads only: stdin, its env, a script file passed to a shell (≤ 64 KB), and the existence of node_modules/.bin/<name>
and package.json. Imports nothing from the repo, writes nothing, calls nothing. Standard library only.
"""

import json
import os
import re
import sys

OFF_VAR = "TONI_NPM_FROZEN"
DEP_VAR = "TONI_DEP_CHANGES"
NPM_ALLOWED = ("ci", "run", "run-script", "test", "t", "ls", "view", "audit")
NPM_VALUE_OPTS = ("--prefix", "-C", "--workspace", "-w", "--cache", "--registry", "--userconfig", "--loglevel")
NPX_NO_INSTALL = ("--no-install", "--yes=false")
REFUSED_TOOLS = ("pnpm", "yarn")
SHELLS = ("bash", "sh", "zsh", "dash", "ksh")
SOURCES = ("source", ".")
MAX_DEPTH = 3
MAX_SCRIPT_BYTES = 64 * 1024
CMD_CHARS = 120

PKG_NAME = re.compile(r"(@[a-z0-9-~][a-z0-9-._~]*/)?[a-z0-9-~][a-z0-9-._~]*")
EXACT_VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
PLAIN_TOOL = re.compile(r"[A-Za-z0-9._-]+")
_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
_RESERVED = frozenset({"{", "}", "!", "if", "then", "else", "elif", "fi", "do", "done", "while", "until"})
# wrapper → (options that take the next word as their value, does a positional word follow the options before the
# command — timeout's duration)
_WRAPPERS = {
    "env": (("-u", "--unset", "-C", "--chdir"), False),
    "sudo": (("-u", "-g", "-C", "-h", "-p", "-r", "-t", "-U", "-D", "--user", "--group", "--host", "--prompt"), False),
    "command": ((), False),
    "builtin": ((), False),
    "exec": (("-a",), False),
    "nohup": ((), False),
    "time": (("-o", "-f", "--output", "--format"), False),
    "nice": (("-n", "--adjustment"), False),
    "timeout": (("-s", "--signal", "-k", "--kill-after"), True),
    "stdbuf": (("-i", "-o", "-e", "--input", "--output", "--error"), False),
    "xargs": (("-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a", "--max-args", "--max-procs", "--delimiter",
               "--arg-file", "--replace", "--max-lines", "--eof", "--max-chars"), False),
}
_SHELL_VALUE_OPTS = ("-o", "+o", "-O", "+O", "--rcfile", "--init-file")

_TAIL = " Do not retry another way: STOP and say so in the handback."
MSG_INPUT = ("🛡 npm frozen: the hook could not read its input — the Bash call is denied (fails closed). Stop and say "
             "so in the handback.")
MSG_CRASH = ("🛡 npm frozen: the hook failed (%s) — the Bash call is denied (fails closed). Stop and say so in the "
             "handback.")
MSG_NPM = ("🛡 npm frozen: '%s' is refused — the executor may run only npm ci, npm run <script> (or run-script), "
           "npm test (or t), npm ls, npm view, npm audit (never audit fix) and npm --version (or -v), exactly as "
           "written, no abbreviations; routes install only with npm ci, frozen to the tracked lockfile (OC-3, "
           "D-S7CORE51-18). A dependency change needs a '## Dependency change:' line with George's go in the brief."
           + _TAIL)
MSG_NPX_FORM = ("🛡 npm frozen: '%s' is refused — npx runs only without downloading: re-run it as "
                "'npx --no-install %s …' (or 'npx --no -- %s …'; a bare '--no' before the tool is misread by npx).")
MSG_NPX_TOOL = ("🛡 npm frozen: '%s' is refused — %s; the executor runs only tools already installed in this tree."
                + _TAIL)
MSG_DEP = "🛡 npm frozen: '%s' is refused — %s" + _TAIL


class Unreadable(Exception):
    """The command text cannot be parsed (an unbalanced quote or parenthesis): fallback() judges it."""


class Sub(list):
    """A scoped group — a subshell or a substitution: a `cd` inside it does not move the commands after it."""


class Text(str):
    """Text that the shell runs as commands (a heredoc body fed to a shell, a substitution in backticks, a here-string
    fed to a shell): judged as its own command string, one level deeper."""


# ── the parser: the command text → simple commands (word lists), Sub groups and Text to judge ──────────────────────
class _Level:
    def __init__(self):
        self.items: list = []
        self.words: list = []
        self.word = None
        self.skip = False          # the next word is a redirection target
        self.here = False          # the next word is a here-string
        self.herestrings: list = []

    def add(self, s: str):
        self.word = (self.word or "") + s

    def end_word(self):
        if self.word is None:
            return
        w, self.word = self.word, None
        if self.skip:
            self.skip = False
        elif self.here:
            self.here = False
            self.herestrings.append((w, self.words))
        else:
            self.words.append(w)

    def end_cmd(self):
        self.end_word()
        if self.words:
            self.items.append(self.words)
        for text, words in self.herestrings:
            if command_name(words) in SHELLS + SOURCES:
                self.items.append(Text(text))
        self.herestrings = []
        self.words = []
        self.skip = self.here = False


class _Scanner:
    def __init__(self, text: str):
        self.t = text
        self.n = len(text)
        self.pending: list = []    # heredocs whose bodies start after the next newline: (delim, strip, quoted, words)

    def scan(self, i: int = 0, close=None):
        t, st = self.t, _Level()
        while i < self.n:
            c = t[i]
            if c in " \t":
                st.end_word()
                i += 1
            elif c == "\n":
                st.end_cmd()
                i += 1
                if self.pending:
                    i = self._bodies(i, st)
            elif c == "#" and st.word is None:
                j = t.find("\n", i)
                i = self.n if j < 0 else j
            elif c == "'":
                j = t.find("'", i + 1)
                if j < 0:
                    raise Unreadable("unbalanced '")
                st.add(t[i + 1:j])
                i = j + 1
            elif c == '"':
                st.add("")
                i = self._dq(i + 1, st, '"')
            elif c == "\\":
                if i + 1 < self.n and t[i + 1] != "\n":
                    st.add(t[i + 1])
                i += 2
            elif c == "`":
                i = self._backtick(i + 1, st, None)
            elif t.startswith("$(", i):
                sub, i = self.scan(i + 2, ")")
                st.items.append(Sub(sub))
                st.add("$(…)")
            elif c in "<>" or t.startswith("&>", i):
                i = self._redirect(i, st)
            elif c == "(":
                st.end_cmd()
                sub, i = self.scan(i + 1, ")")
                st.items.append(Sub(sub))
            elif c == ")":
                if close != ")":
                    raise Unreadable("unbalanced )")
                st.end_cmd()
                return st.items, i + 1
            elif c in ";&|":
                st.end_cmd()
                i += 1
            else:
                st.add(c)
                i += 1
        if close:
            raise Unreadable("unclosed $( or (")
        st.end_cmd()
        self.pending = []          # a heredoc operator on the last line has an empty body
        return st.items, i

    def _dq(self, i: int, st: _Level, end):
        """Double-quoted text (end='"') or an unquoted heredoc body (end=None): data, except $(…) and `…`."""
        t, buf = self.t, []
        while i < self.n:
            c = t[i]
            if end and c == end:
                st.add("".join(buf))
                return i + 1
            if c == "\\" and i + 1 < self.n:
                nxt = t[i + 1]
                buf.append(nxt if nxt in '"\\$`' else ("" if nxt == "\n" else c + nxt))
                i += 2
            elif t.startswith("$(", i):
                sub, i = self.scan(i + 2, ")")
                st.items.append(Sub(sub))
                buf.append("$(…)")
            elif c == "`":
                i = self._backtick(i + 1, st, buf)
            else:
                buf.append(c)
                i += 1
        if end:
            raise Unreadable("unbalanced \"")
        st.add("".join(buf))
        return i

    def _backtick(self, i: int, st: _Level, buf):
        t, j = self.t, i
        while j < self.n and t[j] != "`":
            j += 2 if t[j] == "\\" else 1
        if j >= self.n:
            raise Unreadable("unbalanced `")
        st.items.append(Text(re.sub(r"\\([`\\$])", r"\1", t[i:j])))
        if buf is None:
            st.add("`…`")
        else:
            buf.append("`…`")
        return j + 1

    def _redirect(self, i: int, st: _Level):
        t = self.t
        if st.word is not None:
            if st.word.isdigit():
                st.word = None                         # the fd of `2>…`
            else:
                st.end_word()
        if t.startswith("<<<", i):
            st.here = True
            return i + 3
        if t.startswith("<<", i):
            j, strip = i + 2, False
            if j < self.n and t[j] == "-":
                strip, j = True, j + 1
            while j < self.n and t[j] in " \t":
                j += 1
            delim, quoted, j = self._delim(j)
            self.pending.append((delim, strip, quoted, st.words))
            return j
        if t[i] in "<>" and t.startswith("(", i + 1):  # process substitution
            sub, j = self.scan(i + 2, ")")
            st.items.append(Sub(sub))
            st.add("<(…)")
            return j
        j = i
        while j < self.n and t[j] in "<>&|":
            j += 1
        if t[j - 1] == "&" and j < self.n and (t[j].isdigit() or t[j] == "-"):
            while j < self.n and (t[j].isdigit() or t[j] == "-"):
                j += 1
            return j                                   # `>&2`: no target word
        st.skip = True
        return j

    def _delim(self, j: int):
        t, buf, quoted = self.t, [], False
        while j < self.n and t[j] not in " \t\n;&|()<>":
            c = t[j]
            if c in "'\"":
                k = t.find(c, j + 1)
                if k < 0:
                    raise Unreadable("unbalanced quote in a heredoc delimiter")
                buf.append(t[j + 1:k])
                quoted, j = True, k + 1
            elif c == "\\":
                buf.append(t[j + 1:j + 2])
                quoted, j = True, j + 2
            else:
                buf.append(c)
                j += 1
        if not buf:
            raise Unreadable("a heredoc with no delimiter")
        return "".join(buf), quoted, j

    def _bodies(self, i: int, st: _Level):
        t = self.t
        for delim, strip, quoted, words in self.pending:
            lines = []
            while i < self.n:
                j = t.find("\n", i)
                line = t[i:] if j < 0 else t[i:j]
                i = self.n if j < 0 else j + 1
                if (line.lstrip("\t") if strip else line) == delim:
                    break
                lines.append(line)
            body = "\n".join(lines)
            if command_name(words) in SHELLS + SOURCES:
                st.items.append(Text(body))            # fed to a shell: commands
            elif not quoted:                           # expanded by the shell: its $(…) and `…` run
                inner = _Scanner(body)
                lvl = _Level()
                inner._dq(0, lvl, None)
                st.items.append(Sub(lvl.items))
        self.pending = []
        return i


def split_commands(text: str) -> list:
    """The command text as items: a list of words (one simple command, quotes removed), a Sub group, or Text.
    Raises Unreadable."""
    return _Scanner(text).scan()[0]


# ── the command word ─────────────────────────────────────────────────────────────────────────────────────────────
def _skip_wrapper(name: str, words: list, i: int) -> tuple:
    """Past a wrapper's options (and timeout's duration): (index of the next word, words — env -S splices in)."""
    values, positional = _WRAPPERS[name]
    while i < len(words) and words[i].startswith("-") and words[i] != "-":
        w = words[i]
        if w == "--":
            i += 1
            break
        if name == "env" and (w in ("-S", "--split-string") or w.startswith("--split-string=")):
            val = w.split("=", 1)[1] if "=" in w else (words[i + 1] if i + 1 < len(words) else "")
            rest = words[i + 1:] if "=" in w else words[i + 2:]
            words = words[:i] + val.split() + rest
            continue
        i += 2 if w in values else 1
    if name == "env":
        while i < len(words) and (words[i] == "-" or _ASSIGN.match(words[i])):
            i += 1
    if positional and i < len(words):
        i += 1
    return i, words


def command_index(words: list) -> tuple:
    """(index of the command word or None, words) — after NAME=value words, reserved words and the wrappers."""
    i = 0
    while i < len(words):
        w = words[i]
        if _ASSIGN.match(w) or w in _RESERVED:
            i += 1
            continue
        base = os.path.basename(w)
        if base in _WRAPPERS:
            i, words = _skip_wrapper(base, words, i + 1)
            continue
        return i, words
    return None, words


def command_name(words: list):
    i, words = command_index(words)
    return None if i is None else os.path.basename(words[i])


# ── judging ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _short(words) -> str:
    s = words if isinstance(words, str) else " ".join(words)
    s = " ".join(s.split())
    return s if len(s) <= CMD_CHARS else s[:CMD_CHARS - 1] + "…"


def dep_changes(env) -> list:
    """TONI_DEP_CHANGES as a list of {"pkg", "version", "kind"}; [] when unset, not JSON, or any entry malformed."""
    try:
        data = json.loads(env.get(DEP_VAR, ""))
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    for e in data:
        if not (isinstance(e, dict) and set(e) == {"pkg", "version", "kind"}
                and all(isinstance(v, str) for v in e.values()) and PKG_NAME.fullmatch(e["pkg"])
                and EXACT_VERSION.fullmatch(e["version"]) and e["kind"] in ("dev", "prod")):
            return []
    return data


def _install_form(e: dict) -> str:
    return "npm install %s@%s --save-exact%s" % (e["pkg"], e["version"], " -D" if e["kind"] == "dev" else "")


def _dep_match(rest: list, e: dict) -> bool:
    dev = e["kind"] == "dev"
    spec = "%s@%s" % (e["pkg"], e["version"])
    return (rest.count(spec) == 1 and rest.count("--save-exact") == 1
            and rest.count("-D") + rest.count("--save-dev") == (1 if dev else 0) and len(rest) == (3 if dev else 2))


def judge_npm(cmd: str, args: list, env) -> object:
    if args in (["--version"], ["-v"]):
        return None
    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] != "-":
        i += 2 if args[i] in NPM_VALUE_OPTS else 1
    sub, rest = (args[i], args[i + 1:]) if i < len(args) else (None, [])
    if sub in NPM_ALLOWED:
        if sub in ("run", "run-script") and not any(not w.startswith("-") for w in rest):
            return MSG_NPM % cmd
        if sub == "audit" and any(w == "fix" or w.startswith("--fix") or w in ("--force", "-f") for w in rest):
            return MSG_NPM % cmd
        return None
    deps = dep_changes(env) if sub == "install" else []
    if deps:
        if i == 0 and any(_dep_match(rest, e) for e in deps):
            return None
        named = ", ".join("%s@%s (%s)" % (e["pkg"], e["version"], e["kind"]) for e in deps)
        forms = " or ".join("'%s'" % _install_form(e) for e in deps)
        what = ("this fire's approved dependency change is %s: only %s is allowed." % (named, forms) if len(deps) == 1
                else "this fire's approved dependency changes are %s: only %s is allowed, one package per command."
                % (named, forms))
        return MSG_DEP % (cmd, what)
    return MSG_NPM % cmd


def find_bin(d: str, tool: str):
    """<d>/node_modules/.bin/<tool>, else the same in each parent, up to and including the first directory that holds
    a package.json (as npx searches); None when it is not there."""
    cur = d
    while True:
        p = os.path.join(cur, "node_modules", ".bin", tool)
        if os.path.isfile(p):
            return p
        if os.path.isfile(os.path.join(cur, "package.json")):
            return None
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def judge_npx(cmd: str, args: list, d, env) -> object:
    i, forms, bad = 0, 0, None
    while i < len(args) and args[i].startswith("-"):
        w = args[i]
        if w in NPX_NO_INSTALL:
            forms, i = forms + 1, i + 1
        elif w == "--no" and i + 1 < len(args) and args[i + 1] == "--":
            forms, i = forms + 1, i + 2
            break
        elif w == "--no":
            i += 1                                     # bare --no: npx reads the tool as its own option
        elif w == "--":
            i += 1
            break
        else:
            bad = w
            break
    if bad is not None or forms > 1:
        why = ("npx option '%s'" % bad if bad is not None else "more than one no-install form") + (
            " is not in the allowed set (exactly one of --no-install, --yes=false, '--no --'): it can make npx "
            "download or pick a package that is not in node_modules/.bin")
        return MSG_NPX_TOOL % (cmd, why)
    tool = args[i] if i < len(args) else None
    if tool is None:
        return MSG_NPX_TOOL % (cmd, "npx names no tool, and a tool that is not in node_modules/.bin is never run")
    if forms == 1 and tool == "npm":
        return judge_npm(cmd, args[i + 1:], env)
    if tool in REFUSED_TOOLS:
        return MSG_NPM % cmd
    if not PLAIN_TOOL.fullmatch(tool):
        return MSG_NPX_TOOL % (cmd, "'%s' is not a plain tool name, so it is not in any node_modules/.bin and npx "
                                    "would download it" % tool)
    if d is None:
        return MSG_NPX_TOOL % (cmd, "the directory is not known (a cd the hook cannot follow), so '%s' is not in a "
                                    "node_modules/.bin the hook can check and npx could download it" % tool)
    if find_bin(d, tool) is None:
        return MSG_NPX_TOOL % (cmd, "'%s' is not in %s/node_modules/.bin, so npx would download it" % (tool, d))
    if forms == 0:
        return MSG_NPX_FORM % (cmd, tool, tool)
    return None


def _cd(d, args: list, env=None):
    args = [a for a in args if a not in ("-L", "-P", "-e", "-@", "--")]
    if not args:
        return None
    p = args[0]
    if p == "-" or "$" in p or "`" in p:
        return None
    if p == "~" or p.startswith("~/"):
        # ORCH-NPM-GUARD-TILDE-CD-1 (Kanban 979; 669-585r handback): the shell expands a bare leading `~` to $HOME, so
        # the hook follows it to its own env's HOME when that is absolute; `~user`, an unset or a relative HOME stay
        # unknown (refused at a later npx), as before.
        home = (env or {}).get("HOME", "")
        if not os.path.isabs(home):
            return None
        return os.path.normpath(os.path.join(home, p[2:]))
    if p.startswith("~"):
        return None
    if os.path.isabs(p):
        return os.path.normpath(p)
    return None if d is None else os.path.normpath(os.path.join(d, p))


def _read_script(d, path: str):
    if not os.path.isabs(path):
        if d is None:
            return None
        path = os.path.join(d, path)
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > MAX_SCRIPT_BYTES:
            return None
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return None


def judge_simple(words: list, d, env, depth: int) -> tuple:
    """(refusal or None, the directory after it) for one simple command."""
    k, words = command_index(list(words))
    if k is None:
        return None, d
    name, args, cmd = os.path.basename(words[k]), words[k + 1:], _short(words)
    if name in ("cd", "pushd"):
        return None, _cd(d, args, env)
    if name == "popd":
        return None, None
    if name == "npm":
        return judge_npm(cmd, args, env), d
    if name == "npx":
        return judge_npx(cmd, args, d, env), d
    if name in REFUSED_TOOLS:
        return MSG_NPM % cmd, d
    if name == "eval":
        return judge_text(" ".join(args), d, env, depth + 1), d
    if name in SHELLS or name in SOURCES:
        i, has_c = 0, False
        while name in SHELLS and i < len(args) and args[i][:1] in "-+" and args[i] not in ("-", "--"):
            if args[i] in _SHELL_VALUE_OPTS:
                i += 2
                continue
            if not args[i].startswith("--") and "c" in args[i][1:]:
                has_c = True
            i += 1
        if i < len(args) and args[i] == "--":
            i += 1
        if i < len(args):
            if has_c:
                return judge_text(args[i], d, env, depth + 1), d
            script = _read_script(d, args[i])
            if script is not None:
                return judge_text(script, d, env, depth + 1), d
    return None, d


def judge(items: list, d, env, depth: int):
    for it in items:
        if isinstance(it, Sub):
            m = judge(it, d, env, depth)
        elif isinstance(it, Text):
            m = judge_text(str(it), d, env, depth + 1)
        else:
            m, d = judge_simple(it, d, env, depth)
        if m:
            return m
    return None


_CMD_POS = re.compile(r"\$\(|[;&|()\n`]")      # G-N1 (i)'s positions, and ')' (a case pattern's end)
_HEREDOC_OP = re.compile(r"<<-?\s*(['\"]?)([A-Za-z0-9_.-]+)\1")
_SHELL_LINE = re.compile(r"^\s*(?:bash|sh|zsh|source|\.)(?:\s|$)")


def _drop_bodies_roughly(text: str) -> str:
    out, waiting = [], []
    for line in text.split("\n"):
        if waiting:
            if line.lstrip("\t") == waiting[0][0]:
                waiting.pop(0)
            elif waiting[0][1]:
                out.append(line)
            continue
        out.append(line)
        waiting = [(m.group(2), bool(_SHELL_LINE.match(line))) for m in _HEREDOC_OP.finditer(line)]
    return "\n".join(out)


def fallback(text: str):
    """G-N1 (i): text the parser cannot read — only its command positions are scanned (the start, and after ; & | ( )
    a newline, $( or a backtick). npm, npx, pnpm or yarn at one is refused; nothing else is."""
    for seg in _CMD_POS.split(_drop_bodies_roughly(text)):
        words = seg.split()
        k, words = command_index(words)
        if k is not None and os.path.basename(words[k].strip("\"'\\")) in ("npm", "npx") + REFUSED_TOOLS:
            return MSG_NPM % _short(seg)
    return None


def judge_text(text: str, d, env, depth: int):
    if depth > MAX_DEPTH:
        return fallback(text)
    try:
        items = split_commands(text)
    except Unreadable:
        return fallback(text)
    return judge(items, d, env, depth)


# ── the hook ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _deny(err, msg: str) -> int:
    line = msg + "\n"
    if hasattr(err, "buffer"):
        err.buffer.write(line.encode("utf-8"))
        err.flush()
    else:
        err.write(line)
    return 2


def main(stdin=None, env=None, err=None) -> int:
    env = os.environ if env is None else env
    err = sys.stderr if err is None else err
    try:
        if "".join(env.get(OFF_VAR, "").split()).lower() == "off":
            return 0
        raw = stdin.read() if stdin is not None else sys.stdin.buffer.read().decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return _deny(err, MSG_INPUT)
        if "tool_name" in data and data["tool_name"] != "Bash":
            return 0
        ti = data.get("tool_input")
        cmd = ti.get("command") if isinstance(ti, dict) else None
        if not isinstance(cmd, str):
            return _deny(err, MSG_INPUT)
        cwd = data.get("cwd")
        cwd = os.path.abspath(cwd) if isinstance(cwd, str) and cwd else os.getcwd()
        msg = judge_text(cmd, cwd, env, 0)
        return _deny(err, msg) if msg else 0
    except Exception as e:                             # G-N1 (j): any crash denies
        return _deny(err, MSG_CRASH % type(e).__name__)


if __name__ == "__main__":
    sys.exit(main())
