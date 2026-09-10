"""Pre-fire assertions — machine-checkable subset of the SESSION-BOOT
PRE-FIRE ASSERTION BLOCK (A1-A9).  [HOOK-1, D-S7CORE4-03]

Origin: S7-CORE-4. Gemma_System_Prompt 5.19.3 (brief sizing floor) was loaded in
full at boot and violated twice the same session (ORCH-1 12.4 min, L-11 18.7 min)
while F-15, which was written as an assertion checked at the moment of action,
fired correctly and unprompted twice.  D-S7CORE4-02: a rule that cannot be phrased
as an assertion checked at a decidable moment is not a rule.

The decidable moment for a brief is the fire.  These run inside approval_gate().

ENFORCED (decidable from the brief file alone):
  A2  sizing floor  — '## Estimated runtime:' must be declared and its lower bound
                      must be >= 30 min, unless '## Micro-fire trigger:' names a
                      P0-infra or P1-safety trigger (System Prompt 5.9).
  A8  no skip-sit   — 'skip-sit' must not appear in a feature brief (5.5).

NOT enforced here (not decidable from the brief file): A1 Kanban READY, A3-A7, A9.

Bypass: orchestrator --force, which already means "ALL safety checks bypassed"
and logs a warning.  There is deliberately no second, quieter override.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# System Prompt 5.19.3 — briefs target >= 30 min Toni, ideally 45-90.
SIZING_FLOOR_MIN = 30

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


def check(filepath: Path) -> list[str]:
    """Return a list of assertion failures. Empty list == all checks pass."""
    failures: list[str] = []

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
        est = parse_declared_estimate(filepath)
        trig = parse_microfire_trigger(filepath)
        if est is not None:
            detail = "declared %dm (floor %dm)" % (est, SIZING_FLOOR_MIN)
        else:
            detail = "micro-fire: %s" % trig
        print("  Assertions: ✅ A2/A8 pass — %s" % detail)
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
