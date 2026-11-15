"""Pre-fire assertions — machine-checkable subset of the SESSION-BOOT
PRE-FIRE ASSERTION BLOCK (A1-A9).  [HOOK-1, D-S7CORE4-03]

Origin: S7-CORE-4. Gemma_System_Prompt 5.19.3 (brief sizing floor) was loaded in
full at boot and violated twice the same session (ORCH-1 12.4 min, L-11 18.7 min)
while F-15, which was written as an assertion checked at the moment of action,
fired correctly and unprompted twice.  D-S7CORE4-02: a rule that cannot be phrased
as an assertion checked at a decidable moment is not a rule.

The decidable moment for a brief is the fire.  These run inside approval_gate().

ENFORCED:
  A1  Kanban READY  — '## Kanban: <family> row <N>' must be declared, <family> one of
                      `kanban_families` in config/repos.yaml (default SCP_Kanban, Yorsie_Kanban), and row N
                      of the newest <family>_v*.md in the canon dir (`kanban_dir` in
                      config/repos.yaml): the State cell's first word is READY (markdown aside) and it
                      carries no MERGED / COMPLETE / CUT. [ORCH-PREFIRE-PARSE-HAZARDS-1] a READY anywhere
                      in the cell ('DONE … · was: READY', 'SUPERSEDED … · was READY') is not READY.
                      [ORCH-CONTROL-SCOPE-1] S7-CORE-18 L-49: five routes (99-103) were enqueued
                      with no Kanban row; "not decidable from the brief file" was true, and the
                      brief file now names the row that decides it.
  A2  sizing floor  — '## Estimated runtime:' must be declared and its lower bound
                      must be >= 30 min, unless '## Micro-fire trigger:' names a
                      P0-infra or P1-safety trigger (System Prompt 5.9): its value begins with P0 / P1
                      (markdown aside) and does not negate it ('P1-safety: none', 'P1 — n/a'); a P0/P1
                      later in the line ('none — no P1 trigger') is no trigger, and the A2 SIZING
                      failure says so.  [ORCH-PREFIRE-PARSE-HAZARDS-1]
                      [ORCH-PREFIRE-RUNTIME-1] L-102: the line is also the route timeout
                      (orchestrator.parse_brief_timeout reads this module's parse, upper bound
                      × 1.25), so a line that gives no upper bound fails, micro-fire or not, and
                      the pass line names the timeout the route will run under.
  A8  no skip-sit   — 'skip-sit' must not appear in a feature brief (5.5).
  A9  test scope    — exactly one '## Test scope: targeted (D-S7CORE30-05)' or
                      '## Test scope: full — D-S7CORE<n>-<n>' (the George decision that ordered full
                      suites for that brief) header line.  [ORCH-PREFIRE-TEST-SCOPE-1] D-S7CORE30-05.
  A10 no full suite — a targeted brief has no line instructing a suite the pre-merge gate already runs
                      (`npm test` without ' -- <path or pattern>', `sit:gate`, a merge-base baseline,
                      `pytest` without a path — staged off, A10_BARE_PYTEST) unless that line negates
                      it (do not / don't / never / not run).
  A11 depends-on    — every route a '## Depends-on: <brief-stem>[@<repo>][, …]' line names (default repo: the
                      brief's `#!queue … repo=`) is on its repo's merge target — canon_assert.route_merged, the
                      predicate B6 asks. The failure names each unmet stem and where its brief sits; a line that
                      cannot be read is a refusal. No line, no dependency.  [ORCH-DEPENDS-ON-1] F-289: 309b ran
                      on top of a STOPPED 309a. queue_daemon orders the queue by the same answer (D4).
  OPX-1 operability — a brief on Kanban row >= 393 has '## Operability & safety' with a non-empty Telemetry: /
                      Failure mode…: / Rollback…: / Agent permissions…: / PHI…: line ('none'/'n/a' only with a
                      reason of >= 3 words); rows below are grandfathered.  [ORCH-OPEX-PREFIRE-1] D-S7CORE33-20.
  OPX-2 agent policy — ALLOWED FILES naming an agent-runtime path (prefire_opex_paths.json `agent_runtime`) ⇒ the
                      brief cites an AP-… id the newest SCP_Agent_Inventory_v*.md in the canon folder lists. No
                      inventory file ⇒ a refusal (fail closed; OC-4, D-S7CORE51-20). A citation is an id on a
                      '## Agent policy:' / '## Agent policies:' / '## Agent policy (…):' line or in the Operability
                      Agent permissions answer — an id named anywhere else ('## Not in this route:', the body) is
                      not credited, and the refusal names it.  [ORCH-PREFIRE-PARSE-HAZARDS-1]
  OPX-3 George go   — ALLOWED FILES naming a never-autonomous path (prefire_opex_paths.json `protected`) ⇒ a
                      '## George go:' line, or a '## Briefs:' / '## Spec reference:' line saying George … go / agreed.
                      A go line that is a placeholder (OWED, pending, TBD, …), empty, or carries no ruling id / go word /
                      timed quote is no go; words in quotes are George's.  [ORCH-PREFIRE-GO-TYPED-1] D-S7CORE50-27.
                      OPX-2/-3 refuse a brief on row >= 393 with no ALLOWED FILES section (fail closed).
  DEPCHANGE         — each '## Dependency change: <pkg>@<exact version> (dev|prod) — George go "<George's words>"'
                      line names an npm package, an exact version (no range, tag or URL) and a go whose quoted words
                      pass OPX-3's go grammar; a bad line, or two for one package, is a refusal. The fire hands the
                      good entries to the executor's npm hook as TONI_DEP_CHANGES: the one install it allows.
                      [ORCH-NPM-FROZEN-1] OC-3, D-S7CORE51-18.
  HDR header window — a header line a reader reads only in the brief's first N chars — Kanban, Estimated runtime,
                      Test scope, Depends-on, Micro-fire trigger, Re-gate of (this module, _HEADER_CHARS = 6000);
                      '## TONI_TIMEOUT_MIN:' and a '## Fire mechanism: … TONI_TIMEOUT_MIN=' line
                      (admission.parse_brief_timeout, ADMISSION_HEADER_CHARS = 4000) — that ends past it is a refusal
                      naming the line, its reader and the window: past it the line reads as absent. Lines inside a
                      code fence are not judged. George go, Dependency change, ALLOWED FILES and Operability & safety
                      are read in the whole file.  [ORCH-PREFIRE-PARSE-HAZARDS-1]

  Re-gate          — a brief whose header has '## Re-gate of: <route branch> <sha>' is a gates-only route
                      (orchestrator ORCH-REGATE-GATE-ONLY-1: no executor runs): A2's sizing floor is waived and the
                      pass line says so; a malformed line is a refusal. Every other check, OPX lines included, holds.

NOT enforced here: A3-A7, nor SESSION-BOOT's own A9 (System Prompt v5-38) — this A9 is not that one.
OPX-1/-2/-3 were labelled A12-A14 until ORCH-PREFIRE-RENAME-1: SESSION-BOOT's A12 and A13 are other checks.

Bypass: orchestrator --force, which already means "ALL safety checks bypassed"
and logs a warning.  The one narrower override is PREFIRE_OPEX=off, which skips OPX-1/-2/-3 only and says so on
every fire (D-S7CORE33-20's kill switch); there is deliberately no quiet one.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import yaml

import canon_assert   # A11: route_merged, read off the module at call time
from canon_assert import QueueRepo, disk_family, queue_header

# System Prompt 5.19.3 — briefs target >= 30 min Toni, ideally 45-90.
SIZING_FLOOR_MIN = 30

# [ORCH-CONTROL-SCOPE-1] C3 · A1. The canon dir is `kanban_dir` in config/repos.yaml, else this.
REPOS_CONFIG = Path(__file__).resolve().parent / "config" / "repos.yaml"
KANBAN_DIR_DEFAULT = Path("/mnt/c/Users/gkass/OneDrive/Documents/Spectricom")
# [ORCH-LANE-1] O4 · route 104 handback item 2: the families A1 accepts are `kanban_families` in
# config/repos.yaml; this is the default when the key is absent or not a list of family names.
KANBAN_FAMILIES = ("SCP_Kanban", "Yorsie_Kanban")
_FAMILY_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
KANBAN_READY = "READY"
KANBAN_DONE = ("MERGED", "COMPLETE", "CUT")      # any of these in the State cell ⇒ not READY
# [ORCH-PREFIRE-PARSE-HAZARDS-1] (i): READY is the cell's first word ('READY-REFIRE' and 'Ready' are not READY).
_READY_FIRST = re.compile(r"^[^A-Za-z0-9]*" + KANBAN_READY + r"(?![\w-])")

# How much of the brief header to scan for the declarations.
_HEADER_CHARS = 6000
# [ORCH-PREFIRE-PARSE-HAZARDS-1] (iv): admission.parse_brief_timeout's header window and its two override lines. This
# module owns them (one copy — tests/test_admission_parser.py pins it) so that HDR judges the lines admission reads.
ADMISSION_HEADER_CHARS = 4000
TIMEOUT_MIN_LINE = re.compile(r'^## TONI_TIMEOUT_MIN:\s*(\d+)', re.MULTILINE)
FIRE_MECHANISM_TIMEOUT_LINE = re.compile(r'^## Fire mechanism:.*TONI_TIMEOUT_MIN=(\d+)', re.MULTILINE)


def _read(filepath: Path) -> str:
    try:
        return filepath.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


_RUNTIME_LINE = re.compile(r'^##\s*Estimated runtime:\s*(.+)$', re.MULTILINE)
# A unit may touch its number ('2-3h', '90min'); it may not sit inside a word ('admin', 'with').
_MINUTES = re.compile(r'(?<![a-z])m(in(ute)?s?)?\b', re.IGNORECASE)
_HOURS = re.compile(r'(?<![a-z])h(ours?|rs?)?\b', re.IGNORECASE)
# [ORCH-PREFIRE-RUNTIME-1] D1: the route timeout a runtime line asks for is its upper bound × this.
RUNTIME_TIMEOUT_FACTOR = 1.25


def _runtime_line(filepath: Path) -> Optional[re.Match]:
    return _RUNTIME_LINE.search(_read(filepath)[:_HEADER_CHARS])


def parse_declared_runtime(filepath: Path) -> Optional[tuple[int, int]]:
    """(lower, upper) of the brief's '## Estimated runtime:' line, in minutes — the ONE parse of it.

    [ORCH-PREFIRE-RUNTIME-1] D1 · L-102: the sizing floor (parse_declared_estimate) reads the lower
    bound and the route timeout (orchestrator.parse_brief_timeout) the upper. Route 225's '2-3 h'
    was 120 min to this grammar and nothing to the timeout's own, so it ran under the 45-min default.

    None when the line is absent, or gives no number. A single value is both bounds.

    '75-95 min'  -> (75, 95)      '90 min'   -> (90, 90)
    '45-90 min (HIGH-substrate bundle)' -> (45, 90)   (parentheticals stripped first)
    '1.5h' / '2-3 hours' -> (90, 90) / (120, 180)
    """
    m = _runtime_line(filepath)
    if not m:
        return None

    line = re.sub(r'\([^)]*\)', ' ', m.group(1))          # drop parentheticals
    line = line.replace('–', '-').replace('—', '-')  # en/em dash -> hyphen
    nums = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', line)]
    if not nums:
        return None

    if _HOURS.search(line) and not _MINUTES.search(line):
        nums = [n * 60 for n in nums]

    return int(min(nums)), int(max(nums))


def parse_declared_estimate(filepath: Path) -> Optional[int]:
    """Lower bound of the brief's '## Estimated runtime:' line, in minutes.

    Returns None when the line is absent — which is itself an A2 failure, and is
    exactly what happened on both S7-CORE-4 routes: neither brief declared one.
    """
    runtime = parse_declared_runtime(filepath)
    return runtime[0] if runtime else None


def runtime_timeout(filepath: Path) -> Optional[int]:
    """The route timeout the '## Estimated runtime:' line asks for: its upper bound × 1.25, in minutes.
    None when it gives none. orchestrator.parse_brief_timeout returns this unless a TONI_TIMEOUT_MIN
    header or Fire mechanism override comes first."""
    runtime = parse_declared_runtime(filepath)
    return int(runtime[1] * RUNTIME_TIMEOUT_FACTOR) if runtime else None


# [ORCH-REGATE-GATE-ONLY-1] `## Re-gate of: <route branch> <sha>` — the orchestrator re-runs the gates on that
# branch and fires no executor. Read here and by orchestrator.py (one parser).
_REGATE_LINE = re.compile(r'^##[ \t]*Re-gate of:[ \t]*(.*?)[ \t]*$', re.MULTILINE)
_REGATE_VALUE = re.compile(r'^`?(\S+?)`?\s+`?([0-9a-fA-F]{7,40})`?$')


def regate_line(filepath: Path) -> Optional[str]:
    """The `## Re-gate of:` value as written, or None when the brief has no such line."""
    m = _REGATE_LINE.search(_read(filepath)[:_HEADER_CHARS])
    return m.group(1) if m else None


def parse_regate(filepath: Path) -> Optional[tuple[str, str]]:
    """(route branch, sha) from a well-formed `## Re-gate of:` line; None when absent or malformed."""
    raw = regate_line(filepath)
    m = _REGATE_VALUE.match(raw.strip()) if raw is not None else None
    return (m.group(1), m.group(2).lower()) if m else None


_MICROFIRE_LINE = re.compile(r'^##\s*Micro-fire trigger:\s*(.+)$', re.MULTILINE)
# [ORCH-PREFIRE-PARSE-HAZARDS-1] (ii): the value begins with the P0/P1 token (and any '-qualifier'), and what follows it
# — past ':', dashes and spaces — is not a negation ('P1-safety: none', 'P1 — n/a').
_MICROFIRE_TOKEN = re.compile(r'P[01](?![0-9A-Za-z])(?:-\w+)*', re.IGNORECASE)
_MICROFIRE_NEGATED = re.compile(r'[\s:—–-]*(?:none|n/a|na|no|not|never)\b', re.IGNORECASE)
MICROFIRE_NOT_A_TRIGGER = ("The '## Micro-fire trigger:' line is not a trigger: it must begin with P0 or P1 and not "
                           "negate it (ORCH-PREFIRE-PARSE-HAZARDS-1).")


def microfire_line(filepath: Path) -> Optional[str]:
    """The '## Micro-fire trigger:' value as written (stripped), trigger or not; None when the brief has no such line."""
    m = _MICROFIRE_LINE.search(_read(filepath)[:_HEADER_CHARS])
    return m.group(1).strip() if m else None


def parse_microfire_trigger(filepath: Path) -> Optional[str]:
    """'## Micro-fire trigger:' line, if it names a P0-infra or P1-safety trigger.

    System Prompt 5.9 / A2: under the sizing floor is permitted only when the
    micro-fire trigger is named IN WRITING. A bare line does not satisfy it.
    [ORCH-PREFIRE-PARSE-HAZARDS-1] (ii): named means the value (`*` and backticks aside) BEGINS with P0 / P1 and does
    not negate it — 'none — no P1-safety trigger', 'not P0', 'P1-safety: none', 'P1 — n/a' are no trigger.
    """
    text = microfire_line(filepath)
    if text is None:
        return None
    m = _MICROFIRE_TOKEN.match(_MD.sub("", text).strip())
    if not m or _MICROFIRE_NEGATED.match(m.string, m.end()):
        return None
    return text


# A line that NEGATES the flag ("No --skip-sit", "never --skip-sit", "without
# --skip-sit") is a compliance note, not an invocation. Matching the bare
# substring false-positived on exactly that shape in the S7-CORE-3 bundle.
_NEGATION = re.compile(
    r"\b(no|not|never|without|avoid|omit|remove[ds]?|absent|don'?t|do not)\b",
    re.IGNORECASE)


def find_skip_sit(filepath: Path) -> list[str]:
    """A8 / System Prompt 5.5 — '--skip-sit' never belongs in a feature brief.

    Returns the offending lines (invocations only; negated mentions are allowed).
    """
    hits: list[str] = []
    for raw in _read(filepath).splitlines():
        idx = raw.find('skip-sit')
        if idx < 0:
            continue
        if _NEGATION.search(raw[:idx]):
            continue          # "No `--skip-sit`: ..." — a compliance note
        hits.append(raw.strip()[:160])
    return hits


# ── A9 / A10: the test scope ─────────────────────────────────────────────────
# [ORCH-PREFIRE-TEST-SCOPE-1] D-S7CORE30-05 (George 2026-10-16 14:43: no duplicate regression runs). The
# pre-merge gate runs the full suites right after the executor, and nightly + before every tester session;
# a brief that has the executor run one too pays for it twice. Nothing checked the gates paragraph existed.
_TEST_SCOPE_LINE = re.compile(r'^##\s*Test scope\s*:(?P<text>.*)$', re.MULTILINE)
_TEST_SCOPE_TARGETED = re.compile(r'targeted\s*\(D-S7CORE30-05\)')
_TEST_SCOPE_FULL = re.compile(r'full\s*[—–-]\s*D-S7CORE\d+-\d+')      # full — <the George decision>
A9_REFUSAL = ("A9 TEST-SCOPE — the brief does not declare its test scope "
              "(`## Test scope: targeted (D-S7CORE30-05)`)")

# A10. The gates paragraph says the opposite on the same line ("Do NOT run the full `npm test`, a merge-base
# baseline, or `npm run sit:gate`"), so a line that negates is allowed — anywhere on it, unlike A8's.
_A10_NEGATION = re.compile(r"\b(?:do\s+not|don['’]t|never|not\s+run)\b", re.IGNORECASE)
_A10_SUITES = (
    # `npm test` / `npm run test` not given ` -- <path or pattern>` (flags after the `--` are not one)
    re.compile(r"\bnpm\s+(?:run\s+)?test(?![\w:-])(?!\s+--\s+(?:-\S*\s+)*[^\s`-])", re.IGNORECASE),
    re.compile(r"\bsit:gate\b", re.IGNORECASE),
    re.compile(r"\bmerge-base\s+baseline\b", re.IGNORECASE),
)
_PYTEST = re.compile(r"\bpytest(?![\w-]|\.\w)", re.IGNORECASE)        # not pytest.ini, pytest-xdist, _pytest
# STOP (b) of route 283's brief: ON, this clause refuses brief 286, queued at the time, on its gates line
# (:48 "Gates: `pytest` on the changed/new test files only" — no path, no negation). Staged OFF; turn it on
# once no queued brief has such a line (283 handback, found-and-left). The other three clauses are on.
A10_BARE_PYTEST = False
_PATH_ARG = re.compile(r"/|\.py\b|::|^<")                                 # tests/x.py, x.py::t, <changed paths>


def _bare_pytest(raw: str) -> bool:
    """A `pytest` given no path: the first word after it that is not a flag, up to the code span's end (or
    the line's), is not a path. '`pytest -q`', '`pytest` on the changed files' are bare; '`pytest
    tests/test_prefire.py`', 'pytest -q <changed paths>' are not."""
    for m in _PYTEST.finditer(raw):
        words = [w for w in raw[m.end():].split("`", 1)[0].replace("*", " ").split() if not w.startswith("-")]
        if not words or not _PATH_ARG.search(words[0]):
            return True
    return False


def parse_test_scope(filepath: Path) -> tuple[Optional[str], str]:
    """A9. ('targeted' | 'full', the header line) when the brief carries exactly one '## Test scope:' line
    and it is `targeted (D-S7CORE30-05)` or `full — D-S7CORE<n>-<n>`; (None, what is wrong) otherwise —
    '' when there is no such line."""
    lines = [(m.group(0).strip(), m.group("text").strip())
             for m in _TEST_SCOPE_LINE.finditer(_read(filepath)[:_HEADER_CHARS])]
    if not lines:
        return None, ""
    if len(lines) > 1:
        return None, "%d '## Test scope:' lines, exactly one: %s" % (len(lines), " | ".join(l for l, _ in lines))
    line, text = lines[0]
    if _TEST_SCOPE_TARGETED.fullmatch(text):
        return "targeted", line
    if _TEST_SCOPE_FULL.fullmatch(text):
        return "full", line
    return None, "'%s' is neither that nor `full — <D-S7COREnn-nn>`" % line


def find_full_suite_instructions(filepath: Path) -> list[str]:
    """A10. 'line N: <text>' for every line that instructs a suite the gate runs — `npm test` with no
    ` -- <path or pattern>`, `sit:gate`, a merge-base baseline, `pytest` with no path (A10_BARE_PYTEST) —
    and does not also negate it. Applied to a `targeted` brief only."""
    hits: list[str] = []
    for n, raw in enumerate(_read(filepath).splitlines(), 1):
        if not (any(p.search(raw) for p in _A10_SUITES) or (A10_BARE_PYTEST and _bare_pytest(raw))):
            continue
        if _A10_NEGATION.search(raw):
            continue          # "**Do NOT run the full `npm test`** …" — the gates paragraph
        hits.append("line %d: %s" % (n, raw.strip()[:160]))
    return hits


# ── A1: the Kanban row ───────────────────────────────────────────────────────
_KANBAN_HEADER = re.compile(r'^##\s*Kanban:\s*(?P<family>\S+)\s+row\s+(?P<row>[A-Za-z]*\d+)\b', re.MULTILINE)
_KANBAN_HEADER_ANY = re.compile(r'^##\s*Kanban:\s*(?P<text>.*?)\s*$', re.MULTILINE)
_MD = re.compile(r'[*`]')


def _config_value(key: str):
    """One top-level key of config/repos.yaml, or None. Read per call: tests patch REPOS_CONFIG."""
    try:
        return (yaml.safe_load(REPOS_CONFIG.read_text(encoding="utf-8")) or {}).get(key)
    except Exception:
        return None


def kanban_dir() -> Path:
    """`kanban_dir` in config/repos.yaml, else KANBAN_DIR_DEFAULT."""
    named = _config_value("kanban_dir")
    return Path(named) if named else KANBAN_DIR_DEFAULT


def kanban_families() -> tuple:
    """[ORCH-LANE-1] O4: `kanban_families` in config/repos.yaml, else KANBAN_FAMILIES. A value that is not
    a non-empty list of family names (`X_Kanban`) is not guessed at: the default stands, and a family it
    does not name is refused as before."""
    named = _config_value("kanban_families")
    if (isinstance(named, list) and named
            and all(isinstance(f, str) and _FAMILY_NAME.fullmatch(f) for f in named)):
        return tuple(named)
    return KANBAN_FAMILIES


def parse_kanban_header(filepath: Path) -> Optional[tuple[str, str]]:
    """(family, row) from the brief's '## Kanban: <family> row <N>' line; None when there is none."""
    m = _KANBAN_HEADER.search(_read(filepath)[:_HEADER_CHARS])
    return (m.group("family"), m.group("row")) if m else None


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def kanban_states(text: str, row: str) -> list[str]:
    """The State cell of every table row whose first cell is `row`, markdown stripped. A table's
    State column is its first header cell naming `state` ("State", "Runtime state", "State at EOS");
    a table with none is not a Kanban table and is not read."""
    states, table = [], []
    for line in text.splitlines() + [""]:
        if line.lstrip().startswith("|"):
            table.append(line)
            continue
        if len(table) >= 2:
            head = [_MD.sub("", c).lower() for c in _cells(table[0])]
            col = next((i for i, h in enumerate(head) if re.search(r"\bstate\b", h)), None)
            for body in table[2:] if col is not None else []:
                cells = [_MD.sub("", c).strip() for c in _cells(body)]
                if cells and cells[0] == row and col < len(cells):
                    states.append(cells[col])
        table = []
    return states


def _state_word(state: str) -> str:
    """What a non-READY State cell says, in one word where it has one: a done token, else its
    first capitalised status word (BACKLOG, LIVE, RETIRED, DONE, SUPERSEDED), else the cell itself, quoted
    (first 60 chars). [ORCH-PREFIRE-PARSE-HAZARDS-1] never READY: a cell whose first such word is READY
    ('superseded — was READY') is quoted."""
    done = [t for t in KANBAN_DONE if re.search(rf"\b{t}\b", state)]
    if done:
        return done[0]
    word = re.search(r"\b[A-Z][A-Z_-]{2,}\b", state)
    if word and word.group(0) != KANBAN_READY:
        return word.group(0)
    return "'%s'" % state[:60] if state else "empty"


def check_kanban(filepath: Path) -> tuple[Optional[str], str]:
    """A1. (failure line, "") or (None, the row it passed on). Never a silent pass: no header, no
    file, no row ⇒ a failure that says which."""
    header = parse_kanban_header(filepath)
    families = kanban_families()
    if header is None:
        named = _KANBAN_HEADER_ANY.search(_read(filepath)[:_HEADER_CHARS])
        if named:
            return (f"A1 KANBAN — '## Kanban: {named.group('text')}' names no Kanban row "
                    f"('<{'|'.join(families)}> row <N>'), not READY"), ""
        return (f"A1 KANBAN — no '## Kanban: <{'|'.join(families)}> row <N>' header; a brief "
                f"fires only from a READY Kanban row"), ""
    family, row = header
    if family not in families:
        return (f"A1 KANBAN — '## Kanban: {family} row {row}' names no Kanban family "
                f"({' or '.join(families)}), not READY"), ""
    canon = kanban_dir()
    newest = disk_family(canon, re.escape(family), family).newest
    text = None
    if newest is not None:
        try:
            text = (canon / newest[1]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = None
    if text is None:
        where = f"{newest[1]} unreadable in {canon}" if newest else f"no {family}_v*.md in {canon}"
        return f"A1 KANBAN — {family} row {row} is unreadable ({where}), not READY", ""
    states = kanban_states(text, row)
    if not states:
        return f"A1 KANBAN — {family} row {row} is missing from {newest[1]}, not READY", ""
    for state in states:
        if not _READY_FIRST.match(state) or any(re.search(rf"\b{t}\b", state) for t in KANBAN_DONE):
            return f"A1 KANBAN — {family} row {row} is {_state_word(state)}, not READY", ""
    return None, f"{family} row {row} READY ({newest[1]})"


# ── A11: the routes a brief depends on ───────────────────────────────────────
# [ORCH-DEPENDS-ON-1] PDLC v0-34 F-289 · L-184: filename order is not dependency order — 309b ran on top of a
# STOPPED 309a. A brief that needs another route's code names it, and fires only once that route is on its repo's
# merge target. queue_daemon reads the same dependency_status to order the queue (D4).
QUEUE_DIR = Path(__file__).resolve().parent / "queue"      # where a dependency's brief is looked for; tests patch it
_DEPENDS_ON_LINE = re.compile(r'^##\s*Depends[- ]on\s*:(?P<text>.*)$', re.MULTILINE | re.IGNORECASE)
_DEPENDENCY = re.compile(r'(?P<stem>[A-Za-z0-9][A-Za-z0-9_-]*)(?:@(?P<repo>[A-Za-z0-9][A-Za-z0-9_-]*))?')
A11_GRAMMAR = "'## Depends-on: <brief-stem>[@<repo>][, …]' (a queue filename without .md)"
QUEUED = "queue/"
DEPENDS_PRODUCT_ENV = "ORCH_DEPENDS_PRODUCT"   # =off ⇒ merged is route_merged alone (a handback-only merge meets it)


@dataclass(frozen=True)
class Dependency:
    """One declared dependency, judged: the repo it must be merged on, whether it is, and where its brief sits."""
    stem: str
    target: str                  # '<repo>/<merge target>'
    merged: Optional[str]        # '<sha8> [<evidence>]' when its route is on the merge target, else None
    where: tuple = ()            # the trays holding <stem>.md, when not merged: 'queue/', 'queue/failed/', …
    # [ORCH-RELIABILITY-1] F3.2: the route IS on the merge target but is not met — `merged handback only (briefs/)`,
    # or what it brought cannot be read. Never queued: the queue will not merge that route again.
    landed_unmet: Optional[str] = None

    @property
    def queued(self) -> bool:
        """Still in queue/ itself — the queue may yet merge it."""
        return QUEUED in self.where and not self.landed_unmet

    def __str__(self) -> str:
        if self.landed_unmet:
            return f"{self.stem}: {self.landed_unmet} — not met on {self.target}"
        if self.merged:
            return f"{self.stem} merged on {self.target} ({self.merged})"
        where = " + ".join(self.where) or "nowhere — not in queue/, queue/failed/, queue/held/ or queue/done/"
        return f"{self.stem} (not merged on {self.target}; {where})"


def parse_depends_on(filepath: Path) -> tuple[list[tuple[str, Optional[str]]], Optional[str]]:
    """D1. ([(stem, repo or None)], None) from the brief's one '## Depends-on:' line, [] when it has none; ([], what
    is wrong) when one is there and cannot be read — no stem, an entry that is not `<stem>[@<repo>]` (markdown `*`
    and backticks stripped), the brief itself, more than one such line. Never a silent pass."""
    lines = [m.group(0).strip() for m in _DEPENDS_ON_LINE.finditer(_read(filepath)[:_HEADER_CHARS])]
    if not lines:
        return [], None
    if len(lines) > 1:
        return [], "%d '## Depends-on:' lines, exactly one: %s" % (len(lines), " | ".join(lines))
    entries = [e.strip() for e in _MD.sub("", lines[0].split(":", 1)[1]).split(",")]
    if entries == [""]:
        return [], "'%s' names no brief" % lines[0]
    out: list[tuple[str, Optional[str]]] = []
    for entry in entries:
        m = _DEPENDENCY.fullmatch(entry)
        if not m:
            return [], ("'%s' is not a brief stem[@repo]" % entry if entry else "an empty entry in '%s'" % lines[0])
        if m.group("stem") == filepath.stem:
            return [], "'%s' is this brief itself" % entry
        if (m.group("stem"), m.group("repo")) not in out:
            out.append((m.group("stem"), m.group("repo")))
    return out, None


def queue_repo(name: str) -> Optional[QueueRepo]:
    """A11: a repo name → what canon_assert.route_merged needs, from `repos:` in config/repos.yaml (the keys and
    defaults queue_daemon.repo_route reads); None when no such repo is configured."""
    repos = _config_value("repos")
    r = repos.get(name) if isinstance(repos, dict) else None
    if not isinstance(r, dict) or not r.get("project_dir"):
        return None
    return QueueRepo(name=name, path=Path(r["project_dir"]), merge_target=r.get("merge_target", "main"),
                     branch_prefix=r.get("branch_prefix", "orch"))


def dependency_trays(queue_dir: Path, stem: str) -> tuple:
    """Where `<stem>.md` sits: 'queue/', 'queue/failed/', 'queue/held/<sub>/', 'queue/done/' — every one it is in."""
    name, queue_dir = f"{stem}.md", Path(queue_dir)
    found = [QUEUED] if (queue_dir / name).is_file() else []
    if (queue_dir / "failed" / name).is_file():
        found.append("queue/failed/")
    held = queue_dir / "held"
    if held.is_dir():
        found += ["queue/%s/" % p.parent.relative_to(queue_dir).as_posix()
                  for p in sorted(held.rglob(name)) if p.is_file()]
    if (queue_dir / "done" / name).is_file():
        found.append("queue/done/")
    return tuple(found)


def dependency_status(filepath: Path, queue_dir: Path,
                      resolve: Callable[[str], Optional[QueueRepo]]) -> tuple[list[Dependency], Optional[str]]:
    """D3 / D4. Every dependency the brief declares, judged — or ([], why its line cannot be read). `resolve` maps a
    repo name to its QueueRepo (None: not configured): A11 passes queue_repo, the daemon its repo_route. Merged is
    canon_assert.route_merged's answer and nobody else's (A13). No line ⇒ ([], None), and nothing is asked."""
    declared, why = parse_depends_on(filepath)
    if why or not declared:
        return [], why
    own = queue_header(filepath).get("repo")
    judged: list[Dependency] = []
    for stem, named in declared:
        if not (named or own):
            return [], "'%s' names no repo and the brief has no `#!queue … repo=` — write %s@<repo>" % (stem, stem)
        repo = resolve(named or own)
        if repo is None:
            return [], "'%s' is looked for on repo '%s', which config/repos.yaml does not name" % (stem, named or own)
        why: list = []
        if os.environ.get(DEPENDS_PRODUCT_ENV, "").strip().lower() == "off":
            landed = canon_assert.route_merged(repo, stem)
        else:   # [ORCH-RELIABILITY-1] F3.2: merged = merged product files, judged in canon_assert (A13)
            repos = _config_value("repos")
            cfg = repos.get(repo.name) if isinstance(repos, dict) and isinstance(repos.get(repo.name), dict) else {}
            landed = canon_assert.route_landed_product(repo, stem, cfg.get("briefs_subdir") or "briefs", why)
        judged.append(Dependency(stem, f"{repo.name}/{repo.merge_target}",
                                 f"{landed[0][:8]} [{landed[2]}]" if landed else None,
                                 () if landed else dependency_trays(queue_dir, stem), why[0] if why else None))
    return judged, None


# ── OPX-1/-2/-3: the OpEx pre-checks ─────────────────────────────────────────
# [ORCH-OPEX-PREFIRE-1] D-S7CORE33-20 (Codex v2-57, George go 10-23 18:15): SCP adopts five OpEx controls as
# MANDATORY — absence must block something. OPX-1: the brief says how its change is seen, degrades, is turned
# off, what agent reach it grants and whether it touches PHI or a protected path (Toni_Brief_Authoring_Template_v1-2
# `## Operability & safety`). OPX-2: agent-runtime code changes under a cited Agent Policy. OPX-3: a
# never-autonomous path changes only on George's go. The path lists are data: prefire_opex_paths.json.
OPEX_PATHS = Path(__file__).resolve().parent / "prefire_opex_paths.json"     # tests patch it
OPEX_ENV = "PREFIRE_OPEX"                 # =off skips OPX-1/-2/-3, said on every fire
OPEX_FROM_ROW = 393                       # OPX-1: rows below were written before it — grandfathered
OPEX_LABELS = ("Telemetry", "Failure mode", "Rollback", "Agent permissions", "PHI")
AGENT_INVENTORY = "SCP_Agent_Inventory"   # <canon>/SCP_Agent_Inventory_v*.md, the newest
_OPEX_HEADING = re.compile(r'^##\s*Operability\s*(?:&|and)\s*safety\b', re.IGNORECASE)
_ALLOWED_HEADING = re.compile(r'^##\s.*\bALLOWED\s+FILES\b', re.IGNORECASE)
_SECTION_END = re.compile(r'^#{1,2}(?:\s|$)')
_FENCE = re.compile(r'^\s*(?:```|~~~)')
_BULLET = re.compile(r'^\s*(?:[-*+]|\d+[.)])\s+')
_NONE = re.compile(r'^(?:none|n/a|n\.a\.?|na|not applicable)(?![\w/])', re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z0-9][\w'’/.-]*")
_NOT_EDITED = re.compile(r'\*{0,2}read[- ]only\*{0,2}\s*:|\*\*not\*\*', re.IGNORECASE)   # rest of the line names no edit
_PATH_WORD = re.compile(r'`(?P<span>[^`\n]+)`|(?P<word>[^\s`,;()\[\]]+)')   # a code span, or a bare word
_POLICY_ID = re.compile(r'(?<![A-Za-z0-9-])AP-[A-Z0-9]+(?:-[A-Z0-9]+)*')
_GEORGE_GO_LINE = re.compile(r'^##\s*George go\s*:(?P<text>.*)$', re.MULTILINE | re.IGNORECASE)   # empty text too
_GO_HEADERS = re.compile(r'^##\s*(?:Briefs|Spec reference)\s*:.*$', re.MULTILINE)
_GEORGE_GO = re.compile(r'George[^\n]{0,80}\b(go|GO|agreed|Agree)\b')
# [ORCH-PREFIRE-GO-TYPED-1] D-S7CORE50-27 "any non-go text reads as no go": what a go text may not carry outside George's
# quoted words and cited code spans, and the evidence it must carry somewhere.
GO_PLACEHOLDERS = ("OWED", "PENDING", "TBD", "TBC", "TODO", "AWAITING", "NOT YET", "TO BE ASKED", "TO ASK", "PLACEHOLDER")
GO_EMPTY_ALONE = ("?", "…", "...", "n/a", "none", "-")
GO_WORDS = ("go", "approve", "approved", "approves", "agree", "agreed", "agrees", "yes", "grant", "granted", "ok")
_GO_PLACEHOLDER = re.compile(r'\b(?:%s)\b' % "|".join(
    r"\s+".join(map(re.escape, w.split())) for w in sorted(GO_PLACEHOLDERS, key=len, reverse=True)), re.IGNORECASE)
_GO_TEMPLATE = re.compile(r'<[^<>\n]*>|\{[^{}\n]*\}')
_GO_QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
_GO_SPAN = re.compile(r'`[^`\n]*`|"[^"\n]*"|“[^”\n]*”')        # a code span or a double-quoted span
_GO_RULING_ID = re.compile(r'\bD-[A-Z0-9]+(?:-\d+)+\b')
_GO_WORD = re.compile(r'\b(?:%s)\b' % "|".join(GO_WORDS), re.IGNORECASE)
_GO_TIME = re.compile(r'\b\d{1,2}:\d[\dx]\b')


@dataclass(frozen=True)
class OpexVerdict:
    """One of OPX-1/-2/-3 on one brief: `line` is what prefire prints ('OPX-1 ✅ …', 'OPX-1 ❌ …', 'OPX-2 ⚠ …',
    'OPX-1 — …')."""
    ok: bool
    line: str


def opex_off() -> bool:
    """PREFIRE_OPEX=off (any case) — the kill switch. Anything else, or unset, is on."""
    return os.environ.get(OPEX_ENV, "").strip().lower() == "off"


def _section(text: str, heading: re.Pattern, every: bool = False) -> Optional[list[str]]:
    """The lines under the first `##` heading `heading` matches (every one's, when `every`), up to the next `#`/`##`
    heading outside a code fence; None when there is no such heading."""
    out: Optional[list[str]] = None
    inside = fenced = False
    for raw in text.splitlines():
        if _FENCE.match(raw):
            fenced = not fenced
        elif not fenced and _SECTION_END.match(raw):
            inside = bool(heading.match(raw)) and (every or out is None)
            if inside:
                out = out if out is not None else []
            continue
        if inside:
            out.append(raw)
    return out


def _kanban_row_number(filepath: Path) -> Optional[int]:
    header = parse_kanban_header(filepath)
    digits = re.search(r'\d+', header[1]) if header else None
    return int(digits.group(0)) if digits else None


def operability_answers(filepath: Path) -> Optional[dict[str, str]]:
    """{label: its answer} for each of OPEX_LABELS the `## Operability & safety` section has a `<label>…:` line for
    (markdown and the bullet stripped; a line that is not itself a label or a new bullet continues the answer above
    it); None when there is no such section. The first line for a label is its answer."""
    lines = _section(_read(filepath), _OPEX_HEADING)
    if lines is None:
        return None
    answers: dict[str, str] = {}
    current: Optional[str] = None
    for raw in lines:
        bullet = bool(_BULLET.match(raw))
        line = _MD.sub("", _BULLET.sub("", raw, count=1)).strip()
        label, colon, value = line.partition(":")
        named = next((l for l in OPEX_LABELS if colon and re.match(re.escape(l) + r"\b", label.strip(), re.I)), None)
        if named:
            current = named if named not in answers else None
            if current:
                answers[current] = value.strip()
        elif bullet or not line:
            current = None
        elif current:
            answers[current] = (answers[current] + " " + line).strip()
    return answers


def _answer_problem(answer: str) -> Optional[str]:
    """Why an Operability answer does not count, or None. Empty, or 'none'/'n/a' with fewer than three words after."""
    if not _WORD.search(answer):
        return "empty"
    lead = _NONE.match(answer)
    if lead and len(_WORD.findall(answer[lead.end():])) < 3:
        return "'%s' with no reason (≥ 3 words after it)" % answer.strip()[:60]
    return None


def check_operability(filepath: Path) -> OpexVerdict:
    """OPX-1. A brief whose Kanban row is ≥ OPEX_FROM_ROW carries `## Operability & safety` with a non-empty
    Telemetry: / Failure mode…: / Rollback…: / Agent permissions…: / PHI…: line, 'none'/'n/a' only with a reason.
    Rows below are grandfathered. No row: not judged here — A1 already refuses a brief that names none."""
    row = _kanban_row_number(filepath)
    if row is None:
        return OpexVerdict(True, "OPX-1 — not judged: no Kanban row number (A1 refuses the brief)")
    if row < OPEX_FROM_ROW:
        return OpexVerdict(True, "OPX-1 — grandfathered (row %d < %d)" % (row, OPEX_FROM_ROW))
    answers = operability_answers(filepath)
    if answers is None:
        wrong = "has no '## Operability & safety' section"
    else:
        missing = [l for l in OPEX_LABELS if l not in answers]
        bad = ["%s: %s" % (l, why) for l in OPEX_LABELS if l in answers for why in [_answer_problem(answers[l])] if why]
        wrong = "; ".join((["'## Operability & safety' has no %s line" % ", ".join(missing)] if missing else []) + bad)
        if not wrong:
            return OpexVerdict(True, "OPX-1 ✅ Operability & safety — Telemetry · Failure mode · Rollback · Agent "
                                     "permissions · PHI answered (row %d ≥ %d)" % (row, OPEX_FROM_ROW))
    return OpexVerdict(False, "OPX-1 ❌ OPERABILITY — row %d ≥ %d (D-S7CORE33-20) and the brief %s. Five non-empty "
                              "lines are required — Telemetry: · Failure mode + degraded path: · Rollback / kill switch: · "
                              "Agent permissions (Rule of Two): · PHI & protected paths: — 'none' / 'n/a' only with a "
                              "reason" % (row, OPEX_FROM_ROW, wrong if answers is None else "is not complete: " + wrong))


def allowed_paths(filepath: Path) -> Optional[list[str]]:
    """Every path the brief's ALLOWED FILES section(s) name, in order, once each: each word of a `code span`, and each
    bare word with a '/' or a file extension. What a line says after 'Read only:' or '**Not**' is not an edit and is
    not read. A `:<line>` suffix is dropped. None when the brief has no ALLOWED FILES section."""
    lines = _section(_read(filepath), _ALLOWED_HEADING, every=True)
    if lines is None:
        return None
    words: list[str] = []
    for raw in lines:
        cut = _NOT_EDITED.search(raw)
        for m in _PATH_WORD.finditer(raw[:cut.start()] if cut else raw):
            if m.group("span"):
                words += m.group("span").split()
            elif "/" in m.group("word") or re.search(r"\.[A-Za-z]\w{0,5}$", m.group("word").rstrip(".:")):
                words.append(m.group("word"))
    paths: list[str] = []
    for w in words:
        p = re.sub(r":\d+(?:[-–,]\d+)*$", "", w.strip("\"'“”‘’,;").rstrip(".:"))
        p = p[2:] if p.startswith("./") else p
        if p and p not in paths:
            paths.append(p)
    return paths


def _glob_rx(glob: str) -> re.Pattern:
    """A prefire_opex_paths.json glob as a case-insensitive regex (that file's `_about` says the grammar)."""
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif glob.startswith("/**", i) and i + 3 == len(glob):
            out, i = out + "(?:/.*)?", i + 3
        elif glob.startswith("**", i):
            out, i = out + ".*", i + 2
        else:
            out, i = out + {"*": "[^/]*", "?": "[^/]"}.get(glob[i], re.escape(glob[i])), i + 1
    return re.compile(out, re.IGNORECASE)


def path_matches(path: str, pattern: str) -> bool:
    """Does `path` (as ALLOWED FILES writes it) name `pattern`'s files? A pattern with no '/' matches any one name in
    the path; one with a '/' matches the path or a directory it sits under; a glob path also matches when it reaches
    into the pattern's tree (`src/**` names `src/lib/cds/**`)."""
    rx, parts = _glob_rx(pattern), [p for p in path.split("/") if p]
    if "/" not in pattern.strip("/"):
        return any(rx.fullmatch(p) for p in parts)
    if any(rx.fullmatch("/".join(parts[:n])) for n in range(len(parts), 0, -1)):
        return True
    if any(c in path for c in "*?"):
        sample = re.sub(r"\*\*/", "", re.sub(r"/\*\*$", "/x", pattern)).replace("**", "x").replace("*", "x").replace("?", "x")
        return bool(_glob_rx(path.strip("/")).fullmatch(sample.strip("/")))
    return False


def opex_paths(kind: str, repo: Optional[str]) -> list[str]:
    """The `kind` ('agent_runtime' | 'protected') globs of prefire_opex_paths.json that apply to `repo`: '*' and the
    repo's own; every repo's when `repo` is None. Raises ValueError naming what is wrong with the file — the caller
    fails closed."""
    try:
        data = json.loads(OPEX_PATHS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError("%s unreadable (%s)" % (OPEX_PATHS.name, e)) from None
    lists = data.get(kind) if isinstance(data, dict) else None
    if not isinstance(lists, dict):
        raise ValueError("%s has no '%s' object" % (OPEX_PATHS.name, kind))
    lists = {k: v for k, v in lists.items() if not k.startswith("_")}
    if not all(isinstance(v, list) and all(isinstance(g, str) and g for g in v) for v in lists.values()):
        raise ValueError("%s '%s' is not lists of globs" % (OPEX_PATHS.name, kind))
    keys = ["*", repo] if repo else list(lists)
    return [g for k in keys for g in lists.get(k, [])]


def _named(paths: list[str], globs: list[str]) -> list[str]:
    """'<path> (<glob>)' for each path that names one of `globs` — the first glob it names."""
    return ["%s (%s)" % (p, g) for p in paths for g in [next((g for g in globs if path_matches(p, g)), None)] if g]


def _list(items: list[str], n: int = 5) -> str:
    return ", ".join(items[:n]) + (" (+%d more)" % (len(items) - n) if len(items) > n else "")


def _bare_note(paths: list[str]) -> str:
    """OPX-2/-3's clean line says how many paths carried no directory: `negation.ts` is matched by its name only, so a
    directory pattern (`src/lib/clinical/**`) cannot see it."""
    bare = [p for p in paths if "/" not in p and re.search(r"\.[A-Za-z]\w{0,5}$", p)]
    return " (%d named without a directory — matched by file name only)" % len(bare) if bare else ""


def _unjudged(tag: str, filepath: Path, paths: Optional[list[str]]) -> Optional[OpexVerdict]:
    """OPX-2/-3 before their own question: no ALLOWED FILES section is a refusal from row OPEX_FROM_ROW on (they cannot
    read their input — fail closed), a note below it, and left to A1 when the brief names no row. None: go on."""
    if paths is None:
        row = _kanban_row_number(filepath)
        if row is not None and row < OPEX_FROM_ROW:
            return OpexVerdict(True, "%s — no ALLOWED FILES section, nothing to judge (row %d < %d)" % (tag, row, OPEX_FROM_ROW))
        if row is None:
            return OpexVerdict(True, "%s — not judged: no ALLOWED FILES section and no Kanban row number (A1 refuses "
                                     "the brief)" % tag)
        return OpexVerdict(False, "%s ❌ — the brief has no ALLOWED FILES section, so what it may touch cannot be judged "
                                  "(row %d ≥ %d; fails closed)" % (tag, row, OPEX_FROM_ROW))
    return None


_AGENT_POLICY_LINE = re.compile(r'^##\s*Agent polic(?:y|ies)\b[^:\n]*:.*$', re.MULTILINE)


def cited_policy_ids(filepath: Path) -> list[str]:
    """[ORCH-PREFIRE-PARSE-HAZARDS-1] (iii): the AP-… ids the brief cites as its own, in order, once each — those on
    every '## Agent policy:' / '## Agent policies:' / '## Agent policy (…):' line, then those in the Operability
    `Agent permissions` answer. An id named anywhere else (`## Not in this route:`, the body) is not a citation."""
    ids = [i for m in _AGENT_POLICY_LINE.finditer(_read(filepath)) for i in _POLICY_ID.findall(m.group(0))]
    ids += _POLICY_ID.findall((operability_answers(filepath) or {}).get("Agent permissions", ""))
    return list(dict.fromkeys(ids))


def check_agent_policy(filepath: Path, paths: Optional[list[str]]) -> OpexVerdict:
    """OPX-2. ALLOWED FILES naming an agent-runtime path ⇒ the brief cites an Agent Policy id (AP-…) that the
    newest SCP_Agent_Inventory_v*.md in the canon folder lists. No inventory file ⇒ a refusal (fail closed; OC-4,
    D-S7CORE51-20); the canon folder or the inventory unreadable ⇒ a refusal. A citation is what cited_policy_ids
    reads; a listed id the brief names only elsewhere is named in the refusal, not credited."""
    early = _unjudged("OPX-2", filepath, paths)
    if early:
        return early
    try:
        named = _named(paths, opex_paths("agent_runtime", queue_header(filepath).get("repo")))
    except ValueError as e:
        return OpexVerdict(False, "OPX-2 ❌ AGENT-POLICY — the agent-runtime path list cannot be read: %s (fails closed)" % e)
    if not named:
        return OpexVerdict(True, "OPX-2 ✅ no agent-runtime path in ALLOWED FILES" + _bare_note(paths))
    canon = kanban_dir()
    if not canon.is_dir():
        return OpexVerdict(False, "OPX-2 ❌ AGENT-POLICY — ALLOWED FILES name agent-runtime path(s) %s and the canon folder "
                                  "%s is unreadable, so no policy id can be checked (fails closed)" % (_list(named), canon))
    newest = disk_family(canon, re.escape(AGENT_INVENTORY), AGENT_INVENTORY).newest
    if newest is None:
        return OpexVerdict(False, "OPX-2 ❌ AGENT-POLICY — ALLOWED FILES name agent-runtime path(s) %s and there is no "
                                  "%s_v*.md in %s, so no policy id can be checked (fails closed; OC-4, D-S7CORE51-20)"
                                  % (_list(named), AGENT_INVENTORY, canon))
    try:
        listed = set(_POLICY_ID.findall((canon / newest[1]).read_text(encoding="utf-8", errors="replace")))
    except OSError as e:
        return OpexVerdict(False, "OPX-2 ❌ AGENT-POLICY — %s unreadable (%s), so no policy id can be checked (fails "
                                  "closed)" % (newest[1], e))
    cited = cited_policy_ids(filepath)
    good = [c for c in cited if c in listed]
    if good:
        return OpexVerdict(True, "OPX-2 ✅ agent-runtime path(s) %s under %s (%s)" % (_list(named), ", ".join(good), newest[1]))
    elsewhere = [i for i in dict.fromkeys(_POLICY_ID.findall(_read(filepath))) if i in listed and i not in cited]
    return OpexVerdict(False, "OPX-2 ❌ AGENT-POLICY — ALLOWED FILES name agent-runtime path(s) %s and the brief cites no "
                              "Agent Policy id that %s lists (%s)%s%s. Cite one, e.g. '## Agent policy: AP-…' "
                              "(D-S7CORE33-20)" % (_list(named), newest[1], ", ".join(sorted(listed)) or "none",
                                                         "; cited but not listed: %s" % ", ".join(cited) if cited else "",
                                                         "; named only outside '## Agent policy:' and Agent permissions "
                                                         "(not credited): %s" % ", ".join(elsewhere) if elsewhere else ""))


def _go_text_problem(text: str) -> Optional[str]:
    """[ORCH-PREFIRE-GO-TYPED-1] G-B3: None when `text` is a go — no placeholder or template marker outside its
    double-quoted spans (George's words) and code spans (cited paths), and a ruling id, a go word, or a time with a
    quoted span somewhere in it. Else why not: 'empty', "placeholder '<token>'", "template marker '<marker>'", or 'no
    ruling id, go word or timed quote'."""
    t = text.strip()
    if not t:
        return "empty"
    if t.lower() in GO_EMPTY_ALONE:
        return "placeholder '%s'" % t
    rest = _GO_SPAN.sub(" ", t)
    m = _GO_PLACEHOLDER.search(rest)
    if m:
        return "placeholder '%s'" % m.group(0)
    m = _GO_TEMPLATE.search(rest)
    if m:
        return "template marker '%s'" % m.group(0)
    if _GO_RULING_ID.search(t) or _GO_WORD.search(t) or (_GO_TIME.search(t) and _GO_QUOTED.search(t)):
        return None
    return "no ruling id, go word or timed quote"


def _go_clause(line: str, start: int, end: int) -> str:
    """G-B2: the fallback's judged span — from the George … go match at line[start:end] to the end of its clause: the
    first ';', '**' or '. ' after the match, outside a quoted or code span, else the line's end (')' ends nothing)."""
    closer, i = None, start
    while i < len(line):
        c = line[i]
        if closer:
            closer = None if c == closer else closer
        elif c in '`"“':
            closer = {"`": "`", '"': '"', "“": "”"}[c]
        elif i >= end and (c == ";" or line.startswith("**", i) or line.startswith(". ", i)):
            return line[start:i]
        i += 1
    return line[start:]


def _judge_george_go(filepath: Path) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(go_text, judged_text, why_not) — G-B2: every '## George go:' line decides when there is one (all must pass; the
    first that fails is named); else the first '## Briefs:' / '## Spec reference:' line George … go matches, judged on
    that clause. (None, None, None) when the brief has no go text at all."""
    text = _read(filepath)
    lines = list(_GEORGE_GO_LINE.finditer(text))
    if lines:
        for m in lines:
            why = _go_text_problem(m.group("text"))
            if why:
                return None, m.group(0).strip(), why
        return lines[0].group(0).strip(), lines[0].group(0).strip(), None
    for line in _GO_HEADERS.finditer(text):
        g = _GEORGE_GO.search(line.group(0))
        if g:
            span = _go_clause(line.group(0), g.start(), g.end())
            why = _go_text_problem(span)
            return (None if why else g.group(0)), span, why
    return None, None, None


def george_go_verdict(filepath: Path) -> tuple[Optional[str], Optional[str]]:
    """[ORCH-PREFIRE-GO-TYPED-1] OPX-3's one judge of a go text: (go_text, None) for a go; (None, why_not) for a go line
    (or George … go fallback clause) that is not one — a placeholder, empty, or no go evidence (D-S7CORE50-27: any
    non-go text reads as no go); (None, None) when the brief carries no go text at all."""
    go, _judged, why = _judge_george_go(filepath)
    return go, why


def george_go(filepath: Path) -> Optional[str]:
    """OPX-3: the brief's George go — a `## George go: …` line, else the first `## Briefs:` / `## Spec reference:` line
    matching George[^\\n]{0,80}\\b(go|GO|agreed|Agree)\\b — as the text that says it; None when there is none or when
    it is not a go (george_go_verdict)."""
    return george_go_verdict(filepath)[0]


def check_george_go(filepath: Path, paths: Optional[list[str]]) -> OpexVerdict:
    """OPX-3. ALLOWED FILES naming a never-autonomous path ⇒ the brief carries a George go."""
    early = _unjudged("OPX-3", filepath, paths)
    if early:
        return early
    try:
        named = _named(paths, opex_paths("protected", queue_header(filepath).get("repo")))
    except ValueError as e:
        return OpexVerdict(False, "OPX-3 ❌ NEVER-AUTONOMOUS — the protected path list cannot be read: %s (fails closed)" % e)
    if not named:
        return OpexVerdict(True, "OPX-3 ✅ no never-autonomous path in ALLOWED FILES" + _bare_note(paths))
    go, judged, why = _judge_george_go(filepath)
    if go:
        return OpexVerdict(True, "OPX-3 ✅ never-autonomous path(s) %s — George go: '%s'" % (_list(named), go[:100]))
    if why:
        return OpexVerdict(False, "OPX-3 ❌ NEVER-AUTONOMOUS — ALLOWED FILES name protected path(s) %s and the brief's "
                                  "George go is not a go: '%s' (%s) — any non-go text reads as no go (D-S7CORE50-27)"
                                  % (_list(named), judged[:80], why))
    return OpexVerdict(False, "OPX-3 ❌ NEVER-AUTONOMOUS — ALLOWED FILES name protected path(s) %s and the brief carries "
                              "no George go: a '## George go:' line, or a '## Briefs:' / '## Spec reference:' line saying "
                              "George … go / agreed (D-S7CORE33-20)" % _list(named))


def check_opex(filepath: Path) -> list[OpexVerdict]:
    """OPX-1, OPX-2, OPX-3 — [] when PREFIRE_OPEX=off (report() says so, loudly)."""
    if opex_off():
        return []
    paths = allowed_paths(filepath)
    return [check_operability(filepath), check_agent_policy(filepath, paths), check_george_go(filepath, paths)]


# ── DEPCHANGE: a George-approved exact dependency (ORCH-NPM-FROZEN-1 G-N3; OC-3, D-S7CORE51-18) ──────────────────
# Routes install only with `npm ci`; the executor's npm hook (executor/hooks/npm_frozen.py) allows `npm install` only
# for an entry this returns, handed over by fire_toni as TONI_DEP_CHANGES. This is the one owner of the grammar.
DEP_CHANGE_PKG = re.compile(r'(@[a-z0-9-~][a-z0-9-._~]*/)?[a-z0-9-~][a-z0-9-._~]*')
DEP_CHANGE_VERSION = re.compile(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?')
DEP_CHANGE_KINDS = ("dev", "prod")
_DEP_CHANGE_LINE = re.compile(r'^##\s*Dependency change\s*:(?P<text>.*)$', re.IGNORECASE)
_DEP_CHANGE_SHAPE = re.compile(r'\s*(?P<spec>\S+)\s+\((?P<kind>[^()]*)\)\s*[—–-]+\s*(?P<go>George go\b.*)$')
_DEP_CHANGE_QUOTE = re.compile(r'"(?P<words>[^"\n]*)"(?P<after>.*)$')


def _dep_change_problem(text: str) -> tuple[Optional[dict], str, Optional[str]]:
    """One line's text after 'Dependency change:' → (entry, George's quoted words, None) or (None, '', why not)."""
    m = _DEP_CHANGE_SHAPE.match(text)
    if not m:
        return None, "", "not '<pkg>@<exact version> (dev|prod) — George go \"<George's words>\"'"
    spec, kind = m.group("spec"), m.group("kind").strip()
    at = spec.find("@", 1)
    if at < 0:
        return None, "", "no version in '%s'" % spec
    pkg, version = spec[:at], spec[at + 1:]
    if not DEP_CHANGE_PKG.fullmatch(pkg):
        return None, "", "'%s' is not an npm package name" % pkg
    if not DEP_CHANGE_VERSION.fullmatch(version):
        return None, "", "'%s' is not an exact version (no range, tag, URL or alias)" % version
    if kind not in DEP_CHANGE_KINDS:
        return None, "", "the kind is '%s', not dev or prod" % kind
    q = _DEP_CHANGE_QUOTE.search(m.group("go"))
    if not q or not q.group("words").strip():
        return None, "", "no George's words in quotes after 'George go'"
    why = _go_text_problem(q.group("words") + " " + q.group("after"))
    if why:
        return None, "", "the go is not a go: %s" % why
    return {"pkg": pkg, "version": version, "kind": kind}, q.group("words").strip(), None


def _dependency_lines(filepath: Path) -> tuple[list[tuple[dict, str]], list[str]]:
    good: list[tuple[dict, str]] = []
    problems: list[str] = []
    fenced = False
    for raw in _read(filepath).splitlines():
        if _FENCE.match(raw):
            fenced = not fenced
            continue
        m = None if fenced else _DEP_CHANGE_LINE.match(raw)
        if not m:
            continue
        entry, quote, why = _dep_change_problem(m.group("text"))
        if entry and any(e["pkg"] == entry["pkg"] for e, _ in good):
            entry, why = None, "a second line for %s" % entry["pkg"]
        if why:
            shown = raw.strip()
            problems.append("DEPCHANGE ❌ — '%s' is not a George-approved exact dependency: %s (OC-3, D-S7CORE51-18)"
                            % (shown if len(shown) <= 80 else shown[:79] + "…", why))
        else:
            good.append((entry, quote))
    return good, problems


def dependency_changes(filepath: Path) -> tuple[list[dict], list[str]]:
    """[ORCH-NPM-FROZEN-1] G-N3: the brief's `## Dependency change:` lines as ([{"pkg", "version", "kind"}, …], the
    DEPCHANGE ❌ refusals). ([], []) for a brief with no such line or one that cannot be read. Lines inside a code fence
    are not read."""
    good, problems = _dependency_lines(filepath)
    return [e for e, _ in good], problems


# ── HDR: a header line its reader cannot see (ORCH-PREFIRE-PARSE-HAZARDS-1 (iv)) ──────────────────────────────────
# (the reader's own regex, the window it reads, who reads it) — first matching entry names a line. A line past its
# window reads as absent, silently: 341b5a's '## Depends-on:' started at char 6495, so its five dependencies were
# never checked. George go / Dependency change / ALLOWED FILES / Operability are read whole and are not here.
HEADER_WINDOWS = (
    (_KANBAN_HEADER_ANY, _HEADER_CHARS, "prefire"),
    (_RUNTIME_LINE, _HEADER_CHARS, "prefire"),
    (_TEST_SCOPE_LINE, _HEADER_CHARS, "prefire"),
    (_DEPENDS_ON_LINE, _HEADER_CHARS, "prefire"),
    (_MICROFIRE_LINE, _HEADER_CHARS, "prefire"),
    (_REGATE_LINE, _HEADER_CHARS, "prefire"),
    (TIMEOUT_MIN_LINE, ADMISSION_HEADER_CHARS, "admission.parse_brief_timeout"),
    (FIRE_MECHANISM_TIMEOUT_LINE, ADMISSION_HEADER_CHARS, "admission.parse_brief_timeout"),
)


def header_window_problems(filepath: Path) -> list[str]:
    """HDR. One 'HDR ❌ HEADER-WINDOW — …' refusal per header line (HEADER_WINDOWS) whose END offset is past its
    reader's window — a line the window cuts mid-way counts. Lines inside a code fence are not judged. [] when every
    header line is in its window."""
    out: list[str] = []
    end, fenced = -1, False
    for n, raw in enumerate(_read(filepath).split("\n"), 1):
        start = end + 1
        end = start + len(raw)
        if _FENCE.match(raw):
            fenced = not fenced
            continue
        if fenced:
            continue
        for rx, window, reader in HEADER_WINDOWS:
            if end > window and rx.match(raw):
                out.append("HDR ❌ HEADER-WINDOW — '%s' (line %d) ends at char %d, past %s's %d-char header window, so "
                           "it is not read. Move it above char %d (ORCH-PREFIRE-PARSE-HAZARDS-1)"
                           % (raw.strip()[:60], n, end, reader, window, window))
                break
    return out


def check(filepath: Path) -> list[str]:
    """Return a list of assertion failures. Empty list == all checks pass."""
    failures: list[str] = []

    a1, _ = check_kanban(filepath)
    if a1:
        failures.append(a1)

    line = _runtime_line(filepath)
    estimate = parse_declared_estimate(filepath)
    trigger = parse_microfire_trigger(filepath)
    # [ORCH-PREFIRE-PARSE-HAZARDS-1] (ii): an A2 SIZING failure says when the micro-fire line it saw is no trigger
    not_a_trigger = " " + MICROFIRE_NOT_A_TRIGGER if not trigger and microfire_line(filepath) is not None else ""
    regate_raw = regate_line(filepath)
    regate = parse_regate(filepath)

    if regate_raw is not None and regate is None:
        failures.append("A2 RE-GATE — '## Re-gate of: %s' is not '<route branch> <sha>' (ORCH-REGATE-GATE-ONLY-1)"
                        % regate_raw)
    elif regate is not None:
        pass  # [ORCH-REGATE-GATE-ONLY-1] gates only, no executor: the sizing floor is waived (report says so)
    elif line and estimate is None:
        # [ORCH-PREFIRE-RUNTIME-1] D2: declared, but no route timeout can be read off it. A micro-fire
        # trigger waives the floor, not the timeout.
        failures.append("A2 RUNTIME — '%s' gives no route timeout; write '<n>-<m> min'"
                        % line.group(0).strip())
    elif estimate is None:
        if trigger:
            pass  # declared micro-fire: sizing floor waived by 5.9
        else:
            failures.append(
                "A2 SIZING — no '## Estimated runtime:' declared. "
                "Declare it (>= %dm, ideally 45-90 — System Prompt 5.19.3), or add "
                "'## Micro-fire trigger:' naming the P0-infra or P1-safety trigger (5.9)."
                % SIZING_FLOOR_MIN + not_a_trigger
            )
    elif estimate < SIZING_FLOOR_MIN and not trigger:
        failures.append(
            "A2 SIZING — declared estimate %dm is under the %dm floor "
            "(System Prompt 5.19.3). Re-scope, bundle per 5.12, or add "
            "'## Micro-fire trigger:' naming the P0-infra or P1-safety trigger (5.9)."
            % (estimate, SIZING_FLOOR_MIN) + not_a_trigger
        )

    hits = find_skip_sit(filepath)
    if hits:
        failures.append(
            "A8 SKIP-SIT — '--skip-sit' is invoked in the brief. It never belongs in "
            "a feature brief (System Prompt 5.5); gates now run pre-merge ([ORCH-1]). "
            "Offending line(s): %s" % " | ".join(hits[:3])
        )

    scope, why = parse_test_scope(filepath)
    if scope is None:
        failures.append(A9_REFUSAL + ("; %s" % why if why else ""))
    elif scope == "targeted":
        suites = find_full_suite_instructions(filepath)
        if suites:
            failures.append(
                "A10 FULL-SUITE — the brief is `## Test scope: targeted` but instructs a suite the "
                "orchestrator's pre-merge gate runs right after the executor (D-S7CORE30-05). Name the "
                "paths, or say it is not to be run on that line. Offending line(s): %s%s"
                % (" | ".join(suites[:3]), " (+%d more)" % (len(suites) - 3) if len(suites) > 3 else "")
            )

    deps, why = dependency_status(filepath, QUEUE_DIR, queue_repo)
    if why:
        failures.append("A11 DEPENDS-ON — the '## Depends-on:' line cannot be read: %s. Write %s, or no line "
                        "when the brief depends on no route" % (why, A11_GRAMMAR))
    unmet = [d for d in deps if not d.merged]
    for d in unmet:
        if d.landed_unmet:
            print("⛔ Depends-on %s: %s — not met" % (d.stem, d.landed_unmet))
    if unmet:
        failures.append("A11 DEPENDS-ON — not merged, so not fired: %s. A brief fires only once every route it "
                        "depends on is on its repo's merge target (F-289)" % "; ".join(map(str, unmet)))

    failures += [v.line for v in check_opex(filepath) if not v.ok]     # OPX-1/-2/-3 [ORCH-OPEX-PREFIRE-1]
    failures += dependency_changes(filepath)[1]                         # DEPCHANGE [ORCH-NPM-FROZEN-1]
    failures += header_window_problems(filepath)                        # HDR [ORCH-PREFIRE-PARSE-HAZARDS-1]

    return failures


def _timeout_detail(filepath: Path, timeout: Optional[tuple[int, str, int]]) -> str:
    """[ORCH-PREFIRE-RUNTIME-1] D2: the pass line's timeout. `timeout` is what the fire resolved —
    orchestrator.prefire_timeout: (minutes, source, minutes asked before the hard cap). Without it (this
    module's CLI) the line can say only what the runtime line asks."""
    if timeout is not None:
        minutes, source, asked = timeout
        clamp = " ⚠ clamped to %d min from %d" % (minutes, asked) if asked > minutes else ""
        return "timeout %d min (%s)%s" % (minutes, source, clamp)
    asks = runtime_timeout(filepath)
    if asks is None:
        return "timeout: none declared — the fire's default"
    return ("timeout %d min (Estimated runtime × %s — the fire applies TONI_TIMEOUT_MIN and the hard cap)"
            % (asks, RUNTIME_TIMEOUT_FACTOR))


def report(filepath: Path, timeout: Optional[tuple[int, str, int]] = None) -> bool:
    """Run the assertions and print the verdict. True == cleared to fire."""
    failures = check(filepath)
    bar = "━" * 60
    if opex_off():
        print("  ⚠⚠ %s=off — OPX-1/-2/-3 (D-S7CORE33-20: Operability & safety, agent policy, George go) "
              "SKIPPED for %s. Unset it to turn the OpEx pre-checks back on." % (OPEX_ENV, filepath.name))
    opex = [v.line for v in check_opex(filepath) if v.ok]               # OPX-1/-2/-3: one line each; a ❌ is a failure
    opex += ["DEPCHANGE ✅ %s@%s (%s) — George go: '%s'" % (e["pkg"], e["version"], e["kind"],
                                                         q if len(q) <= 60 else q[:59] + "…")
             for e, q in _dependency_lines(filepath)[0]]                # [ORCH-NPM-FROZEN-1] after the OPX lines
    if not failures:
        _, row = check_kanban(filepath)
        est = parse_declared_estimate(filepath)
        trig = parse_microfire_trigger(filepath)
        regate = parse_regate(filepath)
        if regate is not None:
            detail = ("gates-only re-gate of %s %s: A2 sizing floor waived — no executor runs "
                      "(ORCH-REGATE-GATE-ONLY-1)" % regate)
        elif est is not None:
            detail = "declared %dm (floor %dm)" % (est, SIZING_FLOOR_MIN)
        else:
            detail = "micro-fire: %s" % trig
        print("  Assertions: ✅ A1/A2/A8/A9/A10/A11 pass — %s; %s; %s"
              % (row, detail, _timeout_detail(filepath, timeout)))
        print("  %s" % parse_test_scope(filepath)[1].lstrip("# "))     # A9: the scope it passed on
        deps, _ = dependency_status(filepath, QUEUE_DIR, queue_repo)
        if deps:                                                        # A11: what each dependency merged as
            print("  Depends-on: %s" % "; ".join(map(str, deps)))
        for line in opex:
            print("  %s" % line)
        return True

    print("\n%s" % bar)
    print("  ⛔ PRE-FIRE ASSERTIONS FAILED — %s" % filepath.name)
    print("%s" % bar)
    for f in failures:
        print("  • %s" % f)
    for line in opex:
        print("  %s" % line)
    print("\n  Fix the brief and re-fire. --force bypasses ALL safety checks.")
    print("%s\n" % bar)
    return False


if __name__ == "__main__":
    import sys
    ok = True
    for arg in sys.argv[1:]:
        p = Path(arg)
        print("=== %s" % p.name)
        ok = report(p) and ok
    raise SystemExit(0 if ok else 1)
