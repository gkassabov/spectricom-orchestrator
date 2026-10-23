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
                      config/repos.yaml) must be READY and not MERGED / COMPLETE / CUT.
                      [ORCH-CONTROL-SCOPE-1] S7-CORE-18 L-49: five routes (99-103) were enqueued
                      with no Kanban row; "not decidable from the brief file" was true, and the
                      brief file now names the row that decides it.
  A2  sizing floor  — '## Estimated runtime:' must be declared and its lower bound
                      must be >= 30 min, unless '## Micro-fire trigger:' names a
                      P0-infra or P1-safety trigger (System Prompt 5.9).
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
  A12 operability   — a brief on Kanban row >= 393 has '## Operability & safety' with a non-empty Telemetry: /
                      Failure mode…: / Rollback…: / Agent permissions…: / PHI…: line ('none'/'n/a' only with a
                      reason of >= 3 words); rows below are grandfathered.  [ORCH-OPEX-PREFIRE-1] D-S7CORE33-20 OPX-1.
  A13 agent policy  — ALLOWED FILES naming an agent-runtime path (prefire_opex_paths.json `agent_runtime`) ⇒ the
                      brief cites an AP-… id the newest SCP_Agent_Inventory_v*.md in the canon folder lists. No
                      inventory file yet ⇒ warning, pass.  OPX-2.
  A14 George go     — ALLOWED FILES naming a never-autonomous path (prefire_opex_paths.json `protected`) ⇒ a
                      '## George go:' line, or a '## Briefs:' / '## Spec reference:' line saying George … go / agreed.
                      OPX-3.  A13/A14 refuse a brief on row >= 393 with no ALLOWED FILES section (fail closed).

NOT enforced here: A3-A7, nor SESSION-BOOT's own A9 (System Prompt v5-38) — this A9 is not that one.

Bypass: orchestrator --force, which already means "ALL safety checks bypassed"
and logs a warning.  The one narrower override is PREFIRE_OPEX=off, which skips A12-A14 only and says so on
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

# How much of the brief header to scan for the declarations.
_HEADER_CHARS = 6000


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


def parse_microfire_trigger(filepath: Path) -> Optional[str]:
    """'## Micro-fire trigger:' line, if it names a P0-infra or P1-safety trigger.

    System Prompt 5.9 / A2: under the sizing floor is permitted only when the
    micro-fire trigger is named IN WRITING. A bare line does not satisfy it.
    """
    m = re.search(r'^##\s*Micro-fire trigger:\s*(.+)$', _read(filepath)[:_HEADER_CHARS],
                  re.MULTILINE)
    if not m:
        return None
    text = m.group(1).strip()
    if not re.search(r'\bP[01]\b', text, re.IGNORECASE):
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
    first capitalised status word (BACKLOG, LIVE, RETIRED), else the cell itself."""
    done = [t for t in KANBAN_DONE if re.search(rf"\b{t}\b", state)]
    if done:
        return done[0]
    word = re.search(r"\b[A-Z][A-Z_-]{2,}\b", state)
    return word.group(0) if word else (state[:60] or "empty")


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
        if not re.search(rf"\b{KANBAN_READY}\b", state) or any(re.search(rf"\b{t}\b", state) for t in KANBAN_DONE):
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


@dataclass(frozen=True)
class Dependency:
    """One declared dependency, judged: the repo it must be merged on, whether it is, and where its brief sits."""
    stem: str
    target: str                  # '<repo>/<merge target>'
    merged: Optional[str]        # '<sha8> [<evidence>]' when its route is on the merge target, else None
    where: tuple = ()            # the trays holding <stem>.md, when not merged: 'queue/', 'queue/failed/', …

    @property
    def queued(self) -> bool:
        """Still in queue/ itself — the queue may yet merge it."""
        return QUEUED in self.where

    def __str__(self) -> str:
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
        landed = canon_assert.route_merged(repo, stem)
        judged.append(Dependency(stem, f"{repo.name}/{repo.merge_target}",
                                 f"{landed[0][:8]} [{landed[2]}]" if landed else None,
                                 () if landed else dependency_trays(queue_dir, stem)))
    return judged, None


# ── A12-A14: the OpEx pre-checks ─────────────────────────────────────────────
# [ORCH-OPEX-PREFIRE-1] D-S7CORE33-20 (Codex v2-57, George go 10-23 18:15): SCP adopts five OpEx controls as
# MANDATORY — absence must block something. OPX-1 (A12): the brief says how its change is seen, degrades, is turned
# off, what agent reach it grants and whether it touches PHI or a protected path (Toni_Brief_Authoring_Template_v1-2
# `## Operability & safety`). OPX-2 (A13): agent-runtime code changes under a cited Agent Policy. OPX-3 (A14): a
# never-autonomous path changes only on George's go. The path lists are data: prefire_opex_paths.json.
OPEX_PATHS = Path(__file__).resolve().parent / "prefire_opex_paths.json"     # tests patch it
OPEX_ENV = "PREFIRE_OPEX"                 # =off skips A12-A14, said on every fire
OPEX_FROM_ROW = 393                       # A12: rows below were written before OPX-1 — grandfathered
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
_GEORGE_GO_LINE = re.compile(r'^##\s*George go\s*:[ \t]*(?P<text>\S.*)$', re.MULTILINE | re.IGNORECASE)
_GO_HEADERS = re.compile(r'^##\s*(?:Briefs|Spec reference)\s*:.*$', re.MULTILINE)
_GEORGE_GO = re.compile(r'George[^\n]{0,80}\b(go|GO|agreed|Agree)\b')


@dataclass(frozen=True)
class OpexVerdict:
    """One of A12-A14 on one brief: `line` is what prefire prints ('A12 ✅ …', 'A12 ❌ …', 'A13 ⚠ …', 'A12 — …')."""
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
    """A12 (OPX-1). A brief whose Kanban row is ≥ OPEX_FROM_ROW carries `## Operability & safety` with a non-empty
    Telemetry: / Failure mode…: / Rollback…: / Agent permissions…: / PHI…: line, 'none'/'n/a' only with a reason.
    Rows below are grandfathered. No row: not judged here — A1 already refuses a brief that names none."""
    row = _kanban_row_number(filepath)
    if row is None:
        return OpexVerdict(True, "A12 — not judged: no Kanban row number (A1 refuses the brief)")
    if row < OPEX_FROM_ROW:
        return OpexVerdict(True, "A12 — grandfathered (row %d < %d)" % (row, OPEX_FROM_ROW))
    answers = operability_answers(filepath)
    if answers is None:
        wrong = "has no '## Operability & safety' section"
    else:
        missing = [l for l in OPEX_LABELS if l not in answers]
        bad = ["%s: %s" % (l, why) for l in OPEX_LABELS if l in answers for why in [_answer_problem(answers[l])] if why]
        wrong = "; ".join((["'## Operability & safety' has no %s line" % ", ".join(missing)] if missing else []) + bad)
        if not wrong:
            return OpexVerdict(True, "A12 ✅ Operability & safety — Telemetry · Failure mode · Rollback · Agent "
                                     "permissions · PHI answered (row %d ≥ %d)" % (row, OPEX_FROM_ROW))
    return OpexVerdict(False, "A12 ❌ OPERABILITY — row %d ≥ %d (D-S7CORE33-20 OPX-1) and the brief %s. Five non-empty "
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
    """A13/A14's clean line says how many paths carried no directory: `negation.ts` is matched by its name only, so a
    directory pattern (`src/lib/clinical/**`) cannot see it."""
    bare = [p for p in paths if "/" not in p and re.search(r"\.[A-Za-z]\w{0,5}$", p)]
    return " (%d named without a directory — matched by file name only)" % len(bare) if bare else ""


def _unjudged(tag: str, filepath: Path, paths: Optional[list[str]]) -> Optional[OpexVerdict]:
    """A13/A14 before their own question: no ALLOWED FILES section is a refusal from row OPEX_FROM_ROW on (they cannot
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


def check_agent_policy(filepath: Path, paths: Optional[list[str]]) -> OpexVerdict:
    """A13 (OPX-2). ALLOWED FILES naming an agent-runtime path ⇒ the brief cites an Agent Policy id (AP-…) that the
    newest SCP_Agent_Inventory_v*.md in the canon folder lists. No inventory file there yet ⇒ a warning, and a pass;
    the canon folder or the inventory unreadable ⇒ a refusal."""
    early = _unjudged("A13", filepath, paths)
    if early:
        return early
    try:
        named = _named(paths, opex_paths("agent_runtime", queue_header(filepath).get("repo")))
    except ValueError as e:
        return OpexVerdict(False, "A13 ❌ AGENT-POLICY — the agent-runtime path list cannot be read: %s (fails closed)" % e)
    if not named:
        return OpexVerdict(True, "A13 ✅ no agent-runtime path in ALLOWED FILES" + _bare_note(paths))
    canon = kanban_dir()
    if not canon.is_dir():
        return OpexVerdict(False, "A13 ❌ AGENT-POLICY — ALLOWED FILES name agent-runtime path(s) %s and the canon folder "
                                  "%s is unreadable, so no policy id can be checked (fails closed)" % (_list(named), canon))
    newest = disk_family(canon, re.escape(AGENT_INVENTORY), AGENT_INVENTORY).newest
    if newest is None:
        return OpexVerdict(True, "A13 ⚠ agent-runtime path(s) %s — no %s_v*.md in %s yet, so no policy id can be "
                                 "checked: warning, pass (D-S7CORE33-20 OPX-2)" % (_list(named), AGENT_INVENTORY, canon))
    try:
        listed = set(_POLICY_ID.findall((canon / newest[1]).read_text(encoding="utf-8", errors="replace")))
    except OSError as e:
        return OpexVerdict(False, "A13 ❌ AGENT-POLICY — %s unreadable (%s), so no policy id can be checked (fails "
                                  "closed)" % (newest[1], e))
    cited = list(dict.fromkeys(_POLICY_ID.findall(_read(filepath))))
    good = [c for c in cited if c in listed]
    if good:
        return OpexVerdict(True, "A13 ✅ agent-runtime path(s) %s under %s (%s)" % (_list(named), ", ".join(good), newest[1]))
    return OpexVerdict(False, "A13 ❌ AGENT-POLICY — ALLOWED FILES name agent-runtime path(s) %s and the brief cites no "
                              "Agent Policy id that %s lists (%s)%s. Cite one, e.g. '## Agent policy: AP-…' "
                              "(D-S7CORE33-20 OPX-2)" % (_list(named), newest[1], ", ".join(sorted(listed)) or "none",
                                                         "; cited but not listed: %s" % ", ".join(cited) if cited else ""))


def george_go(filepath: Path) -> Optional[str]:
    """A14: the brief's George go — a `## George go: …` line, else the first `## Briefs:` / `## Spec reference:` line
    matching George[^\\n]{0,80}\\b(go|GO|agreed|Agree)\\b — as the text that says it; None when there is none."""
    text = _read(filepath)
    m = _GEORGE_GO_LINE.search(text)
    if m:
        return m.group(0).strip()
    for line in _GO_HEADERS.finditer(text):
        g = _GEORGE_GO.search(line.group(0))
        if g:
            return g.group(0)
    return None


def check_george_go(filepath: Path, paths: Optional[list[str]]) -> OpexVerdict:
    """A14 (OPX-3). ALLOWED FILES naming a never-autonomous path ⇒ the brief carries a George go."""
    early = _unjudged("A14", filepath, paths)
    if early:
        return early
    try:
        named = _named(paths, opex_paths("protected", queue_header(filepath).get("repo")))
    except ValueError as e:
        return OpexVerdict(False, "A14 ❌ NEVER-AUTONOMOUS — the protected path list cannot be read: %s (fails closed)" % e)
    if not named:
        return OpexVerdict(True, "A14 ✅ no never-autonomous path in ALLOWED FILES" + _bare_note(paths))
    go = george_go(filepath)
    if go:
        return OpexVerdict(True, "A14 ✅ never-autonomous path(s) %s — George go: '%s'" % (_list(named), go[:100]))
    return OpexVerdict(False, "A14 ❌ NEVER-AUTONOMOUS — ALLOWED FILES name protected path(s) %s and the brief carries "
                              "no George go: a '## George go:' line, or a '## Briefs:' / '## Spec reference:' line saying "
                              "George … go / agreed (D-S7CORE33-20 OPX-3)" % _list(named))


def check_opex(filepath: Path) -> list[OpexVerdict]:
    """A12, A13, A14 — [] when PREFIRE_OPEX=off (report() says so, loudly)."""
    if opex_off():
        return []
    paths = allowed_paths(filepath)
    return [check_operability(filepath), check_agent_policy(filepath, paths), check_george_go(filepath, paths)]


def check(filepath: Path) -> list[str]:
    """Return a list of assertion failures. Empty list == all checks pass."""
    failures: list[str] = []

    a1, _ = check_kanban(filepath)
    if a1:
        failures.append(a1)

    line = _runtime_line(filepath)
    estimate = parse_declared_estimate(filepath)
    trigger = parse_microfire_trigger(filepath)

    if line and estimate is None:
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
                % SIZING_FLOOR_MIN
            )
    elif estimate < SIZING_FLOOR_MIN and not trigger:
        failures.append(
            "A2 SIZING — declared estimate %dm is under the %dm floor "
            "(System Prompt 5.19.3). Re-scope, bundle per 5.12, or add "
            "'## Micro-fire trigger:' naming the P0-infra or P1-safety trigger (5.9)."
            % (estimate, SIZING_FLOOR_MIN)
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
    if unmet:
        failures.append("A11 DEPENDS-ON — not merged, so not fired: %s. A brief fires only once every route it "
                        "depends on is on its repo's merge target (F-289)" % "; ".join(map(str, unmet)))

    failures += [v.line for v in check_opex(filepath) if not v.ok]     # A12-A14 [ORCH-OPEX-PREFIRE-1]

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
        print("  ⚠⚠ %s=off — A12/A13/A14 (D-S7CORE33-20 OPX-1/-2/-3: Operability & safety, agent policy, George go) "
              "SKIPPED for %s. Unset it to turn the OpEx pre-checks back on." % (OPEX_ENV, filepath.name))
    opex = [v.line for v in check_opex(filepath) if v.ok]               # A12-A14: one line each; a ❌ is a failure
    if not failures:
        _, row = check_kanban(filepath)
        est = parse_declared_estimate(filepath)
        trig = parse_microfire_trigger(filepath)
        if est is not None:
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
