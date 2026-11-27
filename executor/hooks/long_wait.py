#!/usr/bin/env python3
# filename: executor/hooks/long_wait.py
"""[ORCH-ROUTE-TIME-1] T-4 (Kanban 698, D-S7CORE54-03): the executor's long-wait guard — a PreToolUse hook, matcher
"Bash", the third entry in every executor/settings/<repo>.json after the npm guard.

Route 604-682 slept 41.9 min waiting for a clock (`sleep $s` to just past midnight). A route never waits for a clock:
at a command position this refuses `sleep` whose operands add up to 300 s or more (s/m/h/d suffixes and decimals
read as GNU sleep reads them; `inf` / `infinity` refused), and `sleep` with any operand that is not a literal
(`$…`, `$(…)`, `` `…` ``) — its length is not known until it runs. An operand that is not a duration is refused too
(it cannot be shown to be short). `timeout N <cmd>` is not a wait; the command it runs is judged.

One shell parser decides what is a command: npm_frozen.py's, imported from this file's own directory (the real file
behind a symlink) — heredoc bodies, quoted strings and commit messages are data; `bash -c '…'`, `eval '…'`, a script
fed to a shell and a body fed to a shell are judged, to npm_frozen.MAX_DEPTH. Text the parser cannot read is scanned
at its command positions only.

Exit 2 + one `🛡 long wait:` stderr line = the CLI blocks the call and shows the line to the model. Exit 0, silent =
no objection. Fails closed: unreadable input, a missing parser or any crash denies. TONI_LONG_WAIT=off (any case) in
the hook's environment allows everything.

[PATTERN-KILL-DENY-1] (L-563, rule #27) The same walk refuses a pattern kill: `pkill` / `killall`, or one call that both
finds PIDs by name (`pgrep` / `pidof`) and runs `kill` — one `🛡 pattern kill:` line. `kill <pid>` stays allowed.
TONI_PATTERN_KILL=off turns that half off; TONI_LONG_WAIT=off turns the whole hook off, as before.

Reads only stdin, its env and a script file passed to a shell (npm_frozen's reader). Writes nothing. Standard library
only. Residual (said in the brief): a loop of short literal sleeps, or a sleep inside another interpreter
(`python3 -c "time.sleep(…)"`), is not caught.
"""

import json
import os
import re
import sys

OFF_VAR = "TONI_LONG_WAIT"
LIMIT_S = 300.0
CMD_CHARS = 120
_TAIL = " — a route never waits for a clock; use fake timers or say so in the handback"
MSG_WAIT = "🛡 long wait: %s" + _TAIL
MSG_INPUT = ("🛡 long wait: the hook could not read its input — the Bash call is denied (fails closed). Stop and say "
             "so in the handback.")
MSG_CRASH = ("🛡 long wait: the hook failed (%s) — the Bash call is denied (fails closed). Stop and say so in the "
             "handback.")
# [PATTERN-KILL-DENY-1] (L-563, rule #27): a process is stopped by the PID / PGID recorded when it started, never by a
# name or pattern match — `pkill -f` / `pgrep -f … | xargs kill` matched a lane's own shell and took its runner with it.
# Refused: `pkill` / `killall` at a command position, and one Bash call that both finds PIDs by name (`pgrep` / `pidof`)
# and runs `kill` (a pipe into `xargs kill`, `kill $(pgrep …)`, a loop). `kill <pid>` / `kill -- -<pgid>` stay allowed;
# `pgrep` alone (to look) stays allowed. TONI_PATTERN_KILL=off (any case) turns this half off.
KILL_OFF_VAR = "TONI_PATTERN_KILL"
PATTERN_KILLERS = ("pkill", "killall")
PID_FINDERS = ("pgrep", "pidof")
MSG_KILL = ("🛡 pattern kill: %s — stop a process by the PID / PGID you recorded when it started (rule #27, L-563), "
            "never by a name or pattern; run `pgrep` alone to look, then `kill <pid>` in its own call")
_DURATION = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?([smhd]?)")
_UNIT_S = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
_SLEEP_OPTS = ("--help", "--version")


def _parser():
    here = os.path.dirname(os.path.realpath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import npm_frozen   # noqa: E402  the one shell parser (split_commands and the command walk)
    return npm_frozen


def _short(words) -> str:
    s = " ".join(" ".join(words).split()) if not isinstance(words, str) else " ".join(words.split())
    return s if len(s) <= CMD_CHARS else s[:CMD_CHARS - 1] + "…"


def sleep_seconds(args: list):
    """The seconds a `sleep <args>` waits, or None when that cannot be known (a non-literal or non-duration operand,
    or infinity)."""
    total = 0.0
    for a in args:
        if a in _SLEEP_OPTS or a == "--":
            continue
        if "$" in a or "`" in a or "…" in a:
            return None
        if a.lower() in ("inf", "infinity"):
            return None
        m = _DURATION.fullmatch(a)
        if not m:
            return None
        try:
            v = float(a[:-1] if m.group(1) else a) * _UNIT_S[m.group(1)]
        except (ValueError, OverflowError):
            return None
        if v != v or v == float("inf"):
            return None
        total += v
    return total


def judge_words(nf, words: list, d, depth: int):
    k, words = nf.command_index(list(words))
    if k is None:
        return None, d
    name, args = os.path.basename(words[k]), words[k + 1:]
    if name in ("cd", "pushd"):
        return None, nf._cd(d, args)
    if name == "popd":
        return None, None
    if name == "sleep":
        secs = sleep_seconds(args)
        return (MSG_WAIT % _short(words[k:]) if secs is None or secs >= LIMIT_S else None), d
    if name == "eval":
        return judge_text(nf, " ".join(args), d, depth + 1), d
    if name in nf.SHELLS or name in nf.SOURCES:   # npm_frozen.judge_simple's shell walk, verbatim in shape
        i, has_c = 0, False
        while name in nf.SHELLS and i < len(args) and args[i][:1] in "-+" and args[i] not in ("-", "--"):
            if args[i] in nf._SHELL_VALUE_OPTS:
                i += 2
                continue
            if not args[i].startswith("--") and "c" in args[i][1:]:
                has_c = True
            i += 1
        if i < len(args) and args[i] == "--":
            i += 1
        if i < len(args):
            if has_c:
                return judge_text(nf, args[i], d, depth + 1), d
            script = nf._read_script(d, args[i])
            if script is not None:
                return judge_text(nf, script, d, depth + 1), d
    return None, d


_KILL_ON = [True]


def _command_words(nf, items: list, depth: int) -> list:
    """Every simple command's words from its command word on, through Sub groups and Text the shell runs."""
    out = []
    for it in items:
        if isinstance(it, nf.Sub):
            out += _command_words(nf, it, depth)
        elif isinstance(it, nf.Text):
            if depth < nf.MAX_DEPTH:
                try:
                    out += _command_words(nf, nf.split_commands(str(it)), depth + 1)
                except nf.Unreadable:
                    out += [w for w in _fallback_words(nf, str(it))]
        else:
            k, words = nf.command_index(list(it))
            if k is not None:
                out.append(words[k:])
    return out


def _fallback_words(nf, text: str) -> list:
    out = []
    for seg in nf._CMD_POS.split(nf._drop_bodies_roughly(text)):
        words = [w.strip("\"'\\") for w in seg.split()]
        k, words = nf.command_index(words)
        if k is not None:
            out.append(words[k:])
    return out


def pattern_kill(cmds: list):
    """[PATTERN-KILL-DENY-1] The refusal line for a pattern kill among these simple commands, else None."""
    if not _KILL_ON[0]:
        return None
    named = [(os.path.basename(w[0]), w) for w in cmds if w]
    for name, w in named:
        if name in PATTERN_KILLERS:
            return MSG_KILL % _short(w)
    finders = [w for name, w in named if name in PID_FINDERS]
    kills = [w for name, w in named if name == "kill"]
    if finders and kills:
        return MSG_KILL % _short(finders[0] + ["…"] + kills[0])
    return None


def judge(nf, items: list, d, depth: int):
    for it in items:
        if isinstance(it, nf.Sub):
            m = judge(nf, it, d, depth)
        elif isinstance(it, nf.Text):
            m = judge_text(nf, str(it), d, depth + 1)
        else:
            m, d = judge_words(nf, it, d, depth)
        if m:
            return m
    return None


def fallback(nf, text: str):
    """Text the parser cannot read: `sleep` at a command position (npm_frozen's positions) is judged on its words;
    so is a pattern kill (PATTERN-KILL-DENY-1)."""
    m = pattern_kill(_fallback_words(nf, text))
    if m:
        return m
    for seg in nf._CMD_POS.split(nf._drop_bodies_roughly(text)):
        words = [w.strip("\"'\\") for w in seg.split()]
        k, words = nf.command_index(words)
        if k is not None and os.path.basename(words[k]) == "sleep":
            secs = sleep_seconds(words[k + 1:])
            if secs is None or secs >= LIMIT_S:
                return MSG_WAIT % _short(seg)
    return None


def judge_text(nf, text: str, d, depth: int):
    if depth > nf.MAX_DEPTH:
        return fallback(nf, text)
    try:
        items = nf.split_commands(text)
    except nf.Unreadable:
        return fallback(nf, text)
    return pattern_kill(_command_words(nf, items, depth)) or judge(nf, items, d, depth)


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
        _KILL_ON[0] = "".join(env.get(KILL_OFF_VAR, "").split()).lower() != "off"
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
        nf = _parser()
        msg = judge_text(nf, cmd, cwd, 0)
        return _deny(err, msg) if msg else 0
    except Exception as e:                             # any crash denies, as npm_frozen.py does
        return _deny(err, MSG_CRASH % type(e).__name__)


if __name__ == "__main__":
    sys.exit(main())
