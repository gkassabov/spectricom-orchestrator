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
  A8  no skip-sit   — 'skip-sit' must not appear in a feature brief (5.5).

NOT enforced here: A3-A7, A9.

Bypass: orchestrator --force, which already means "ALL safety checks bypassed"
and logs a warning.  There is deliberately no second, quieter override.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from canon_assert import disk_family

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


def parse_declared_estimate(filepath: Path) -> Optional[int]:
    """Lower bound of the brief's '## Estimated runtime:' line, in minutes.

    Returns None when the line is absent — which is itself an A2 failure, and is
    exactly what happened on both S7-CORE-4 routes: neither brief declared one.

    '75-95 min'  -> 75      '90 min'   -> 90
    '45-90 min (HIGH-substrate bundle)' -> 45   (parentheticals stripped first)
    '1.5h' / '2 hours' -> 90 / 120
    """
    m = re.search(r'^##\s*Estimated runtime:\s*(.+)$', _read(filepath)[:_HEADER_CHARS],
                  re.MULTILINE)
    if not m:
        return None

    line = re.sub(r'\([^)]*\)', ' ', m.group(1))          # drop parentheticals
    line = line.replace('–', '-').replace('—', '-')  # en/em dash -> hyphen
    nums = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', line)]
    if not nums:
        return None

    has_min = re.search(r'\bm(in(ute)?s?)?\b', line, re.IGNORECASE) is not None
    has_hr = re.search(r'\bh(ours?|rs?)?\b', line, re.IGNORECASE) is not None
    if has_hr and not has_min:
        nums = [n * 60 for n in nums]

    return int(min(nums))


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


def check(filepath: Path) -> list[str]:
    """Return a list of assertion failures. Empty list == all checks pass."""
    failures: list[str] = []

    a1, _ = check_kanban(filepath)
    if a1:
        failures.append(a1)

    estimate = parse_declared_estimate(filepath)
    trigger = parse_microfire_trigger(filepath)

    if estimate is None:
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

    return failures


def report(filepath: Path) -> bool:
    """Run the assertions and print the verdict. True == cleared to fire."""
    failures = check(filepath)
    bar = "━" * 60
    if not failures:
        _, row = check_kanban(filepath)
        est = parse_declared_estimate(filepath)
        trig = parse_microfire_trigger(filepath)
        if est is not None:
            detail = "declared %dm (floor %dm)" % (est, SIZING_FLOOR_MIN)
        else:
            detail = "micro-fire: %s" % trig
        print("  Assertions: ✅ A1/A2/A8 pass — %s; %s" % (row, detail))
        return True

    print("\n%s" % bar)
    print("  ⛔ PRE-FIRE ASSERTIONS FAILED — %s" % filepath.name)
    print("%s" % bar)
    for f in failures:
        print("  • %s" % f)
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
