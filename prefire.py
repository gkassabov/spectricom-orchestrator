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
                      OPX-2/-3 refuse a brief on row >= 393 with no ALLOWED FILES section (fail closed). An
                      ALLOWED FILES heading is read at any depth, ## … ######; its section runs to the next heading
                      of its depth or shallower.  [ORCH-PREFIRE-ALLOWED-H3-MISSED-1] D-S7CORE53-09.
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

  DRY dry run      — a brief whose Kanban row reads READY (A1 passed), and every brief queue_daemon.py enqueue copies,
                      has a '## DRY RUN (pasted)' block outside a code fence holding a run result (an exit code or a
                      count), no unfilled v1-5 placeholder and no NOT READY.  [ORCH-PREFIRE-DRYRUN-GATE-1] Kanban 727,
                      D-S7CORE54-63 (3), SD-6(a); retro fix 1.
  VERIFY            — each report a '## Verify report: <path>[, …]' header line names exists, and a claim that a test
                      holds / is unchanged / keep-green / green has a run result in its paragraph; a report claiming
                      any run has a command + exit/count line. CLI: `python3 prefire.py --verify-report <file>…`.
                      [ORCH-PREFIRE-DRYRUN-GATE-1] retro fix 7.
  INPUTS            — every `~/_eos/…` path the brief names exists; every 'sha256 <hex>' is 64 hex and matches the
                      file a path on its line names. Code fences, placeholders and globs aside.
                      [ORCH-PREFIRE-DRYRUN-GATE-1] retro fix 6. All three judge when config/repos.yaml has
                      `prefire_dryrun: required` (the live config does; a drift test pins it); PREFIRE_DRYRUN=off skips
                      them, said on every fire.

  Re-gate          — a brief whose header has '## Re-gate of: <route branch> <sha>' is a gates-only route
                      (orchestrator ORCH-REGATE-GATE-ONLY-1: no executor runs): A2's sizing floor is waived and the
                      pass line says so; a malformed line is a refusal. Every other check, OPX lines included, holds.

  APPLY            — a brief whose header has '## Apply patch: <path> <sha256>' lands that saved patch with no executor
                      (orchestrator ORCH-APPLY-PATCH-1, SD-1 trial: George 2026-11-16 17:40 "approved", conditions
                      17:52 "Yes"): A2's sizing floor is waived. Refused: a malformed line; a patch carrying the
                      route's own handback or brief copy; a patch that is missing, under /tmp, /var/tmp, /dev/shm or
                      $TMPDIR, of another sha256, binary, or unreadable as `diff --git` blocks (a `---`/`+++`/`@@`
                      header outside a git block's header included); a patch path outside
                      ALLOWED FILES or on the never-autonomous list (OPX-3 `protected`: protected areas join later,
                      with George's go by name); a change to an existing test file, or any change to a conftest.py,
                      a runner config, a setup file (by name, or what a runner config names in `setupFiles` /
                      `globalSetup`), a snapshot, a fixture, a sit/ file or package.json, that no
                      GRANT line under the brief's '## RULE #8' (outside an HTML note) carrying
                      'Granted: George' names (condition 2; a new test file is not a change to a test); no
                      '## Patch author:' line; and no '## Verify report:' report that names the patch's sha256, a
                      'Verifier:' other than the author, 'Wrote any of this change: no' and a READY verdict
                      (condition 1, G-17), or any report on the patch that says NOT READY, or a report with a run
                      claim and no run (727's check). The orchestrator asks the same question again at the fire
                      (--force does not skip it), and refuses a brief whose repo is not the fire's.

NOT enforced here: A3-A7, nor SESSION-BOOT's own A9 (System Prompt v5-38) — this A9 is not that one.
OPX-1/-2/-3 were labelled A12-A14 until ORCH-PREFIRE-RENAME-1: SESSION-BOOT's A12 and A13 are other checks.

Bypass: orchestrator --force, which already means "ALL safety checks bypassed"
and logs a warning.  The one narrower override is PREFIRE_OPEX=off, which skips OPX-1/-2/-3 only and says so on
every fire (D-S7CORE33-20's kill switch); there is deliberately no quiet one.
"""

from __future__ import annotations

import json
import os
import posixpath
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


# [ORCH-APPLY-PATCH-1] SD-1 trial (George 2026-11-16 17:40 "approved"; conditions 17:52 "Yes"): `## Apply patch: <path>
# <sha256>` — the orchestrator applies that exact saved patch to a branch cut from the merge target, fires no executor,
# runs the normal gate and lands it. Read here and by orchestrator.py (one parser); apply_patch_problems is the one judge.
_APPLY_LINE = re.compile(r'^##[ \t]*Apply patch:[ \t]*(.*?)[ \t]*$', re.MULTILINE)
_APPLY_VALUE = re.compile(r'^`?(\S+?)`?\s+`?([0-9a-fA-F]{64})`?$')
_AUTHOR_LINE = re.compile(r'^##[ \t]*Patch author:[ \t]*(.*?)[ \t]*$', re.MULTILINE)
_DIFF_GIT = re.compile(r'^diff --git a/(\S+) b/(\S+)$')
_HUNK = re.compile(r'^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@')
# a test file or test harness, by path: a tests/ / __tests__/ / __mocks__/ / e2e/ / test-utils/ directory, or a test-named
# file (test_*.py, *_test.py, conftest.py, *.test.ts, *.spec.tsx, vitest/jest/playwright config); r3 (S7-CORE-56, C2-a):
# a __snapshots__/ / __fixtures__/ / fixtures/ / sit/ directory, a *.snap file or a *.fixture(s).* file — a snapshot IS an
# assertion, a fixture is what the assertion reads, and sit/ is clinical-mp's SIT tree (invariants, harness, runner)
_TEST_PATH = re.compile(r'(?:^|/)(?:tests?|__tests__|__mocks__|__snapshots__|__fixtures__|fixtures|sit|e2e'
                        r'|test[-_]?utils?|testing)/'
                        r'|(?:^|/)(?:test_[^/]*\.py|[^/]*_test\.py|conftest\.py|[^/]*\.(?:test|spec)\.[cm]?[jt]sx?'
                        r'|[^/]*\.snap|[^/]*\.fixtures?\.[^/]*|(?:vitest|jest|playwright)\.[^/]*)$', re.IGNORECASE)
# r2 (verifier m-1): what decides how EVERY existing test runs — a conftest.py, a runner's config or the package scripts.
# Added or changed, it needs a grant in the trial. r4 (VERIFY-r3 M-1): `.pytest.ini` too — pytest reads it as it reads
# `pytest.ini` (_pytest/config/findpaths.py), so a new one could set `addopts = -k "not …"`; r5 (VERIFY-r4 M-1r):
# `pytest.toml` / `.pytest.toml` too — pytest 9 reads them before `pytest.ini` in every folder.
_RUNNER_PATH = re.compile(r'(?:^|/)(?:conftest\.py|\.?pytest\.(?:ini|toml)|pyproject\.toml|setup\.cfg|tox\.ini|package\.json'
                          r'|(?:vitest|vite|jest|playwright)(?:\.[^/]+)?\.config\.[^/]*|[^/]*\.setup\.[cm]?[jt]sx?'
                          r'|setupTests\.[cm]?[jt]sx?)$', re.IGNORECASE)
# r3 (n-2): what a repo's runner config names in `setupFiles` runs before every test, whatever its name; S7-CORE-56 (C2-b):
# every vite / vitest / jest / playwright config at the root or one folder down (`server/vitest.config.ts`,
# `vitest.sit.config.ts`, `playwright.config.ts`), and `setupFilesAfterEnv`, `globalSetup`, `globalTeardown` too
_RUNNER_CONFIG_NAME = re.compile(r'^(?:vitest|vite|jest|playwright)(?:\.[^/]+)?\.config\.[cm]?[jt]s$', re.IGNORECASE)
_SETUP_FILES = re.compile(r'\b(?:setupFiles(?:AfterEnv)?|globalSetup|globalTeardown)\s*:\s*'
                          r'(\[[^\]]*\]|["\'][^"\']+["\'])')
# r4 (VERIFY-r3 M-1): a NEW file the runner loads on its own — a `__mocks__/` neighbour (vitest/jest load it for every
# bare `vi.mock('…')` / `jest.mock('…')` of the module beside it) or an `__init__.py` under a test directory (it
# changes how pytest names and imports every test beside it) — changes existing tests without touching them
_MOCKS_DIR = re.compile(r'(?:^|/)__mocks__/', re.IGNORECASE)
_INIT_PY = re.compile(r'(?:^|/)__init__\.py$', re.IGNORECASE)
# r4 (VERIFY-r3 m-1): every header line git reads a rename or copy path from — `rename old` / `rename new` are git's
# older spellings of `rename from` / `rename to` and git still applies them
_RENAME_LINE = re.compile(r'^(?:rename (from|to|old|new)|copy (from|to)) (.*)$')
# r4 (VERIFY-r3 m-3): a line indented 4+ columns is an indented code block (or a nested item) — never a grant
_INDENTED = re.compile(r'^(?: {0,3}\t| {4})')
# r5 (VERIFY-r4 m-1): a fence line is indented 0-3 spaces (CommonMark); a ``` indented 4+ inside a fence is content.
# Used by the grant reader only — the shared `_FENCE` is read by the daemon's in-memory allowed_paths /
# dependency_status, and is left as it is (no daemon restart owed).
_GRANT_FENCE = re.compile(r'^ {0,3}(?:```|~~~)')
_ZERO_WIDTH = re.compile('[\u200b-\u200f\u2060\ufeff]')
_HTML_NOTE = re.compile(r'<!--.*?(?:-->|\Z)', re.DOTALL)    # S7-CORE-56 (C2-c): an unclosed note runs to the end
_RULE8_HEADING = re.compile(r'^##\s*RULE\s*#\s*8\b', re.IGNORECASE)
_GRANT_WORD = re.compile(r'\bGRANT\b')                       # upper case: '**Grants:** none' is not a grant line
# r2 (verifier M-1): a grant counts only on a line that says it was given — `Granted: George` — an allow-list, not a
# deny-list; the deny words still refuse beside it, and a `Searches:` line never grants.
_GRANT_GIVEN = re.compile(r'\bGranted:\s*George\b')
_GRANT_NOT_YET = re.compile(r'\b(?:ASKED|OPEN|PENDING|TBD|OWED|REFUSED|DENIED|NOT\s+GRANTED)\b', re.IGNORECASE)
_SEARCH_LINE = re.compile(r'^[\s>*_`-]*Searches?\b', re.IGNORECASE)
_SPAN = re.compile(r'`([^`\n]+)`')
_STAMP = re.compile(r'^[\s>*_`-]*(Patch sha256|Verifier|Wrote any of this change|Verdict)[*_`]*\s*:[*_`\s]*(.*?)[*_`\s]*$',
                    re.IGNORECASE)
_WROTE_NO = re.compile(r'no[.!]?', re.IGNORECASE)            # r2 (m-3): exactly `no`, markdown and a full stop aside
APPLY_TEMP_ROOTS = ("/tmp/", "/var/tmp/", "/dev/shm/")   # G-1: never a temporary folder; $TMPDIR too (tests patch these)
APPLY_TMPDIR_ENV = "TMPDIR"
APPLY_PREFIX = "APPLY ❌ "
APPLY_RULING = "SD-1 trial, George 2026-11-16 17:40 / 17:52 (ORCH-APPLY-PATCH-1)"


def apply_line(filepath: Path) -> Optional[str]:
    """The `## Apply patch:` value as written, or None when the brief has no such line."""
    m = _APPLY_LINE.search(_read(filepath)[:_HEADER_CHARS])
    return m.group(1) if m else None


def parse_apply(filepath: Path) -> Optional[tuple[Path, str]]:
    """(patch path, ~ expanded; sha256, lower case) from a well-formed `## Apply patch:` line; None when absent or
    malformed."""
    raw = apply_line(filepath)
    m = _APPLY_VALUE.match(raw.strip()) if raw is not None else None
    return (Path(os.path.expanduser(m.group(1))), m.group(2).lower()) if m else None


def patch_author(filepath: Path) -> Optional[str]:
    """The `## Patch author:` value (markdown stripped), or None when absent or empty."""
    m = _AUTHOR_LINE.search(_read(filepath)[:_HEADER_CHARS])
    text = _MD.sub("", m.group(1)).strip() if m else ""
    return text or None


def _who(name: str) -> str:
    """An agent name as compared: markdown, case, spacing, punctuation, hyphens and zero-width characters aside (r3,
    n-3: 'Brief-author worker s55-a.' is 'brief author worker s55 a')."""
    return re.sub(r"[\W_]+", "", _ZERO_WIDTH.sub("", name).lower())


def is_test_path(path: str) -> bool:
    return bool(_TEST_PATH.search(path))


def is_runner_config(path: str, setup: tuple = ()) -> bool:
    """r2 (m-1): a conftest.py, a test runner's config or package.json — it changes how every existing test runs; r3
    (n-2): a `*.setup.*` / `setupTests.*` file, or any file in `setup` (the repo's own `setupFiles`)."""
    return bool(_RUNNER_PATH.search(path)) or path in setup


def needs_grant(path: str, kind: str, setup: tuple = ()) -> bool:
    """Condition 2: a change to an existing test file (modified, deleted, renamed away), or any change — new ones too —
    to a conftest.py / runner config / setup file / package.json. r4 (VERIFY-r3 M-1): a NEW file under a `__mocks__/`
    directory, or a new `__init__.py` under a test directory, too — the runner loads each on its own."""
    if is_runner_config(path, setup):
        return True
    if kind != "added":
        return is_test_path(path)
    return bool(_MOCKS_DIR.search(path)) or (bool(_INIT_PY.search(path)) and is_test_path(path))


def _repo_entry(repo: Optional[str]) -> dict:
    """config/repos.yaml `repos.<repo>`, or {} (unread, unnamed, or not there)."""
    repos = _config_value("repos")
    entry = repos.get(repo) if isinstance(repos, dict) and repo else None
    return entry if isinstance(entry, dict) else {}


def _runner_configs(project: Path) -> list[Path]:
    """The vite / vitest / jest / playwright configs at the project root and one folder down (dot-folders and
    node_modules aside), sorted by path."""
    out: list[Path] = []
    try:
        top = sorted(Path(project).iterdir())
    except OSError:
        return out
    for e in top:
        if e.is_file() and _RUNNER_CONFIG_NAME.match(e.name):
            out.append(e)
    for d in top:
        if not d.is_dir() or d.name.startswith(".") or d.name == "node_modules":
            continue
        try:
            out += [e for e in sorted(d.iterdir()) if e.is_file() and _RUNNER_CONFIG_NAME.match(e.name)]
        except OSError:
            continue
    return out


def setup_files(project: Optional[Path]) -> tuple:
    """r3 (n-2): every path a runner config of the repo names in `setupFiles`, repo-relative ('./' dropped); () when
    there is no such config or project. S7-CORE-56 (C2-b): `setupFilesAfterEnv`, `globalSetup`, `globalTeardown`
    too, in every config `_runner_configs` finds; a path in a config one folder down is listed both relative to that
    folder and to the root (fails closed: either may be how the runner resolves it). Read-only."""
    if project is None:
        return ()
    found: list[str] = []
    for cfg in _runner_configs(Path(project)):
        try:
            text = cfg.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sub_dir = cfg.parent.relative_to(Path(project)).as_posix()
        for m in _SETUP_FILES.finditer(text):
            for q in re.findall(r'["\']([^"\']+)["\']', m.group(1)):
                q = q[2:] if q.startswith("./") else q.lstrip("/")
                cands = [q] if sub_dir in ("", ".") else [posixpath.normpath(sub_dir + "/" + q), q]
                for c in cands:
                    if c and not c.startswith("..") and c not in found:
                        found.append(c)
    return tuple(found)


def temp_roots() -> list[str]:
    """APPLY_TEMP_ROOTS and $TMPDIR, each as its real path with a trailing '/'."""
    roots = list(APPLY_TEMP_ROOTS)
    extra = os.environ.get(APPLY_TMPDIR_ENV, "").strip() if APPLY_TMPDIR_ENV else ""
    if extra:
        roots.append(extra)
    return [os.path.realpath(r).rstrip("/") + "/" for r in roots if r]


def patch_files(text: str) -> tuple[list[tuple[str, str]], Optional[str]]:
    """([(path, kind)], None) — every path a `git diff` patch touches, kind 'added' | 'deleted' | 'modified' (a rename
    is its old path 'deleted' and its new path 'added'; a copy, the new path 'added'); ([], why) when the patch cannot
    be judged: no `diff --git` block, a quoted or spaced path (a quoted `rename`/`copy` value too, r4), a binary
    patch, a/b paths that differ with no rename, or
    (r2, verifier m-2) a `--- ` / `+++ ` / `@@` header outside a `diff --git` block's own header — hunks are counted by
    their line numbers, so a traditional block git would also apply cannot hide after a git one."""
    out: list[tuple[str, str]] = []
    cur = None                                    # [a, b, kind, rename_from, rename_to, copy_to] of the open block
    header = False
    old_left = new_left = 0                       # lines still owed by the open hunk

    def close() -> Optional[str]:
        if cur is None:
            return None
        a, b, kind, rfrom, rto, copy = cur
        if rfrom or rto:
            if not (rfrom and rto):
                return "a rename without both of its paths (%s)" % a
            out.extend([(rfrom, "deleted"), (rto, "added")])
        elif copy:
            out.append((copy, "added"))             # r4: the path git creates is `copy to`'s, not the b/ path
        elif a != b:
            return "a block whose a/ and b/ paths differ with no rename (%s, %s)" % (a, b)
        else:
            out.append((a, kind))
        return None

    for raw in text.splitlines():
        if old_left > 0 or new_left > 0:          # inside a hunk: its body, whatever it says
            tag = raw[:1]
            if tag == "\\":
                continue
            if tag not in (" ", "-", "+", ""):
                return [], "a hunk shorter than its header says (%s)" % raw[:80]
            if tag in (" ", ""):
                old_left, new_left = old_left - 1, new_left - 1
            elif tag == "-":
                old_left -= 1
            else:
                new_left -= 1
            if old_left < 0 or new_left < 0:
                return [], "a hunk longer than its header says (%s)" % raw[:80]
            continue
        if raw.startswith("diff --git "):
            why = close()
            if why:
                return [], why
            m = _DIFF_GIT.match(raw)
            if not m:
                return [], "a quoted or spaced path is not judged: %s" % raw[:120]
            cur, header = [m.group(1), m.group(2), "modified", None, None, None], True
            continue
        if raw.startswith(("GIT binary patch", "Binary files ")):
            return [], "a binary patch is not judged"
        h = _HUNK.match(raw)
        if h:
            if cur is None:
                return [], "a hunk outside a `diff --git` block is not judged: %s" % raw[:80]
            header = False
            old_left = int(h.group(1)) if h.group(1) is not None else 1
            new_left = int(h.group(2)) if h.group(2) is not None else 1
            continue
        if raw.startswith(("--- ", "+++ ")):
            if cur is None or not header:
                return [], "a `%s` header outside a `diff --git` block's header is not judged" % raw[:60]
            continue
        if cur is None or not header:
            continue
        if raw.startswith("new file mode"):
            cur[2] = "added"
        elif raw.startswith("deleted file mode"):
            cur[2] = "deleted"
        elif _RENAME_LINE.match(raw):
            rm = _RENAME_LINE.match(raw)
            val = rm.group(3)
            if val.startswith('"'):                 # r4 (VERIFY-r3 m-1): git un-quotes it; the judge would not
                return [], "a quoted path is not judged: %s" % raw[:120]
            if rm.group(1) in ("from", "old"):
                cur[3] = val
            elif rm.group(1) in ("to", "new"):
                cur[4] = val
            elif rm.group(2) == "to":
                cur[5] = val
    if old_left > 0 or new_left > 0:
        return [], "the patch ends inside a hunk"
    why = close()
    if why:
        return [], why
    if not out:
        return [], "no `diff --git` block — not a git patch"
    return out, None


def rule8_grants(filepath: Path) -> tuple[list[str], list[str]]:
    """(granted paths, lines not counted). A grant is a line under the brief's `## RULE #8` heading(s), outside a code
    fence and not indented 4+ columns (r4, VERIFY-r3 m-3: an indented code block), carrying the upper-case word GRANT AND
    `Granted: George` (r2, verifier M-1: an allow-list), and none of
    ASKED / OPEN / PENDING / TBD / OWED / REFUSED / DENIED / NOT GRANTED; a `Searches:` line never grants. Each `code
    span` on a grant line with a '/' or a file extension is a granted path (a `:<lines>` suffix dropped). A GRANT line
    not counted is returned in the second list, so a refusal can name it."""
    # r3 (n-1): an HTML note is not the brief — a GRANT (or a `Granted: George`) inside `<!-- … -->` does not count
    text = _HTML_NOTE.sub(lambda m: "\n" * m.group(0).count("\n"), _read(filepath))
    lines = _section(text, _RULE8_HEADING, every=True, fence=_GRANT_FENCE) or []
    granted: list[str] = []
    pending: list[str] = []
    fenced = False
    for raw in lines:
        if _GRANT_FENCE.match(raw):
            fenced = not fenced
            continue
        if fenced or not _GRANT_WORD.search(raw) or _SEARCH_LINE.match(raw):
            continue
        if _INDENTED.match(raw):                    # r4 (VERIFY-r3 m-3): an indented code block is not the brief
            pending.append("(indented 4+ columns, not counted) " + raw.strip()[:100])
            continue
        if not _GRANT_GIVEN.search(_MD.sub("", raw).replace("_", "")) or _GRANT_NOT_YET.search(raw):
            pending.append(raw.strip()[:120])
            continue
        for span in _SPAN.findall(raw):
            for w in span.split():
                w = re.sub(r":\d[\d,\-–]*$", "", w.strip("\"'“”‘’,;").rstrip(".:"))
                w = w[2:] if w.startswith("./") else w
                if w and ("/" in w or re.search(r"\.[A-Za-z]\w{0,5}$", w)) and w not in granted:
                    granted.append(w)
    return granted, pending


def verify_stamp(report: Path) -> dict[str, str]:
    """The trial stamp of a verifier report: the first 'Patch sha256:' / 'Verifier:' / 'Wrote any of this change:' /
    'Verdict:' line of each (markdown and a bullet aside), keyed in lower case; outside code fences."""
    stamp: dict[str, str] = {}
    try:
        text = report.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return stamp
    for _, raw in _unfenced(text):
        m = _STAMP.match(raw)
        if m and m.group(1).lower() not in stamp:
            stamp[m.group(1).lower()] = m.group(2).strip()
    return stamp


def _stamp_names(stamp: dict[str, str], sha: str) -> bool:
    return sha in [h.lower() for h in re.findall(r"[0-9a-fA-F]{64}", stamp.get("patch sha256", ""))]


def _stamp_problem(stamp: dict[str, str], sha: str, author: Optional[str]) -> Optional[str]:
    """Why a report does not clear the patch, or None."""
    if not _stamp_names(stamp, sha):
        return "names no 'Patch sha256: %s…' (the 64 hex of this patch)" % sha[:12]
    who = stamp.get("verifier", "")
    if not _who(who):
        return "names no 'Verifier:'"
    if author and _who(who) == _who(author):
        return "its verifier '%s' is the patch author — condition 1: a fresh verifier reviews it (G-17)" % who[:60]
    wrote = _MD.sub("", stamp.get("wrote any of this change", "")).strip()
    if wrote.lower().startswith("yes"):
        return ("its verifier '%s' wrote part of this change — condition 1: a fresh verifier reviews it (G-17)"
                % who[:60])
    if not _WROTE_NO.fullmatch(wrote):
        return "has no 'Wrote any of this change: no' line (it says '%s'; exactly `no`)" % wrote[:60]
    verdict = _MD.sub("", stamp.get("verdict", "")).strip().upper()
    if not verdict.startswith("READY"):
        return "its verdict is '%s', not READY" % (stamp.get("verdict", "") or "none")[:60]
    return None


def apply_patch_problems(filepath: Path, data: Optional[bytes] = None, project: Optional[Path] = None,
                         briefs_subdir: Optional[str] = None) -> list[str]:
    """APPLY. [] when the brief is not an apply-patch brief, or when its `## Apply patch:` patch may land with no
    executor; else one 'APPLY ❌ …' refusal per fault (fails closed: what cannot be judged is refused). `data`: the
    patch bytes the caller will apply (r2, m-6: judged and applied from one read); read from the path when None.
    `project` / `briefs_subdir`: the fire's checkout and briefs folder; from config/repos.yaml for the brief's repo
    when None (r3, n-2 / n-4)."""
    raw = apply_line(filepath)
    if raw is None:
        return []
    named = parse_apply(filepath)
    if named is None:
        return [APPLY_PREFIX + "'## Apply patch: %s' is not '<path> <sha256 (64 hex)>' (%s)" % (raw[:120], APPLY_RULING)]
    patch, sha = named
    if not patch.is_absolute():
        return [APPLY_PREFIX + "the patch path %s is not absolute (write ~/_eos/… or /home/…)" % patch]
    real = os.path.realpath(patch)
    hit = next((t for t in temp_roots() if (real + "/").startswith(t)), None)
    if hit:
        return [APPLY_PREFIX + "the patch %s is under /tmp (%s) — a saved change lives in a durable folder, never a "
                "temporary one (G-1)" % (patch, hit)]
    if data is None:
        try:
            data = patch.read_bytes()
        except OSError as e:
            return [APPLY_PREFIX + "the patch %s cannot be read (%s)" % (patch, e.strerror or e)]
    got = _sha256_bytes(data)
    if got != sha:
        return [APPLY_PREFIX + "the patch %s has sha256 %s…, the brief names %s… — not the patch that was verified"
                % (patch.name, got[:12], sha[:12])]
    files, why = patch_files(data.decode("utf-8", errors="replace"))
    if why:
        return [APPLY_PREFIX + "the patch %s cannot be judged: %s" % (patch.name, why)]
    out: list[str] = []
    paths = [p for p, _ in files]
    repo = queue_header(filepath).get("repo")
    entry = _repo_entry(repo)
    if project is None and entry.get("project_dir"):
        project = Path(os.path.expanduser(str(entry["project_dir"])))
    briefs = (briefs_subdir or entry.get("briefs_subdir") or "briefs").strip("/")
    own = [p for p in paths if p in ("%s/%s.handback.md" % (briefs, filepath.stem), "%s/%s" % (briefs, filepath.name))]
    if own:
        out.append(APPLY_PREFIX + "the patch carries %s — the route's handback and brief copy are the orchestrator's to "
                   "write; an apply-patch patch may not carry them (take them out of the patch)" % _list(own))
    setup = setup_files(project)
    try:
        protected = _named(paths, opex_paths("protected", repo))
    except ValueError as e:
        protected = None
        out.append(APPLY_PREFIX + "the protected path list cannot be read: %s (fails closed)" % e)
    if protected:
        out.append(APPLY_PREFIX + "the patch touches never-autonomous path(s) %s — protected areas are not in the "
                   "trial; they join later, with George's go by name (SD-1)" % _list(protected))
    allowed = allowed_paths(filepath)
    if allowed is None:
        out.append(APPLY_PREFIX + "the brief has no ALLOWED FILES section — a patch path cannot be checked against it")
    else:
        outside = [p for p in paths if not any(path_matches(p, a) for a in allowed)]
        if outside:
            out.append(APPLY_PREFIX + "the patch touches path(s) outside ALLOWED FILES: %s" % _list(outside))
    granted, pending = rule8_grants(filepath)
    edited = ["%s (%s)" % (p, k) for p, k in files if needs_grant(p, k, setup) and p not in granted]
    if edited:
        out.append(APPLY_PREFIX + "the patch changes test file(s) %s that no GRANT line under '## RULE #8' with "
                   "'Granted: George' names — condition 2: a test not granted in the brief is not changed%s"
                   % (_list(edited), "; GRANT line(s) not given: %s" % " | ".join(pending[:2]) if pending else ""))
    author = patch_author(filepath)
    if author is None:
        out.append(APPLY_PREFIX + "no '## Patch author:' line — the verifier cannot be shown to be someone else")
    reports, bad = verify_reports(filepath)
    out += [APPLY_PREFIX + b[len("VERIFY ❌ — "):] if b.startswith("VERIFY ❌ — ") else APPLY_PREFIX + b for b in bad]
    if not reports:
        out.append(APPLY_PREFIX + "no '## Verify report:' line — SD-1 lands only a change an independent verifier "
                   "checked")
    else:
        whys, clears = [], False
        for r in reports:
            if not r.is_file():
                whys.append("%s does not exist" % r.name)
                continue
            stamp = verify_stamp(r)
            # r2 (m-4): any report on this patch that says NOT READY refuses, whatever another one says
            if _stamp_names(stamp, sha) and "NOT READY" in _MD.sub("", stamp.get("verdict", "")).upper():
                out.append(APPLY_PREFIX + "%s says NOT READY on this patch (%s) — a READY report beside it does not "
                           "outvote it" % (r.name, stamp.get("verdict", "")[:60]))
            # r2 (m-8): 727's run-claim check at the fire too (--force and PREFIRE_DRYRUN=off skip prefire's)
            out += [APPLY_PREFIX + v[len("VERIFY ❌ — "):] if v.startswith("VERIFY ❌ — ") else APPLY_PREFIX + v
                    for v in verify_report_problems(r)]
            why = _stamp_problem(stamp, sha, author)
            if why is None:
                clears = True
            else:
                whys.append("%s %s" % (r.name, why))
        if not clears:
            out.append(APPLY_PREFIX + "no verifier report clears this patch: %s" % " | ".join(whys[:3]))
    return out


def apply_patch_summary(filepath: Path) -> str:
    """The pass line's detail for a clean apply-patch brief."""
    patch, sha = parse_apply(filepath)
    files, _ = patch_files(patch.read_text(encoding="utf-8", errors="replace"))
    entry = _repo_entry(queue_header(filepath).get("repo"))
    setup = setup_files(Path(os.path.expanduser(str(entry["project_dir"]))) if entry.get("project_dir") else None)
    edits = [p for p, k in files if needs_grant(p, k, setup)]
    who = next((verify_stamp(r).get("verifier", "") for r in verify_reports(filepath)[0]
                if r.is_file() and _stamp_problem(verify_stamp(r), sha, patch_author(filepath)) is None), "")
    return ("%s sha256 %s… — %d file(s), none protected, all in ALLOWED FILES; %d test edit(s), each granted; verifier "
            "'%s' ≠ author '%s'" % (patch.name, sha[:12], len(files), len(edits), who[:40],
                                    (patch_author(filepath) or "")[:40]))


def _sha256_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


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
    # [ORCH-QUEUE-LOOSEN-1] (4) D-S7CORE58: any other `targeted…` line is read as targeted with a warning — unless it
    # names a full suite on the same line (A10's patterns), which stays a refusal. 11-20: 791 / 792's
    # "targeted (one file)" refused the brief and paused the queue for a label.
    if text.lower().startswith("targeted") and not any(p.search(text) for p in _A10_SUITES):
        return "targeted", "%s — ⚠️ A9 read as `targeted (D-S7CORE30-05)`; write that exact text" % line
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
_ALLOWED_HEADING = re.compile(r'^#{2,6}\s.*\bALLOWED\s+FILES\b', re.IGNORECASE)   # any depth ## … ######
_HEADING = re.compile(r'^(#{1,6})(?:\s|$)')
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


def _section(text: str, heading: re.Pattern, every: bool = False, fence: Optional[re.Pattern] = None
             ) -> Optional[list[str]]:
    """The lines under the first `##` heading `heading` matches (every one's, when `every`), up to the next `#`/`##`
    heading outside a code fence; None when there is no such heading. `fence` (default `_FENCE`) is what opens and
    closes a fence (r5: `rule8_grants` passes `_GRANT_FENCE`)."""
    fence = fence or _FENCE
    out: Optional[list[str]] = None
    inside = fenced = False
    for raw in text.splitlines():
        if fence.match(raw):
            fenced = not fenced
        elif not fenced and _SECTION_END.match(raw):
            inside = bool(heading.match(raw)) and (every or out is None)
            if inside:
                out = out if out is not None else []
            continue
        if inside:
            out.append(raw)
    return out


def _allowed_section(text: str) -> Optional[list[str]]:
    """[ORCH-PREFIRE-ALLOWED-H3-MISSED-1] The lines under every ALLOWED FILES heading at any depth (## … ######), each
    up to the next heading of its own depth or shallower outside a code fence — so a `##` section ends exactly where
    `_section` ends it, and a deeper heading inside one (an ALLOWED FILES one too) is part of it. Fence lines are
    content. None when there is no such heading."""
    out: Optional[list[str]] = None
    depth = 0                                      # the open section's heading depth; 0 = none open
    fenced = False
    for raw in text.splitlines():
        if _FENCE.match(raw):
            fenced = not fenced
        elif not fenced and _HEADING.match(raw):
            d = len(_HEADING.match(raw).group(1))
            if depth and d <= depth:
                depth = 0
            if not depth:
                if _ALLOWED_HEADING.match(raw):
                    depth = d
                    out = out if out is not None else []
                continue
        if depth:
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
    not read. A `:<line>` suffix is dropped. None when the brief has no ALLOWED FILES section. A section's heading may
    be at any depth, ## … ###### (_allowed_section, ORCH-PREFIRE-ALLOWED-H3-MISSED-1)."""
    lines = _allowed_section(_read(filepath))
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


# ── DRY / VERIFY / INPUTS: the author's run, pasted (ORCH-PREFIRE-DRYRUN-GATE-1, Kanban 727) ─────────────────────
# D-S7CORE54-63 (3), SD-6(a) "now, not after T1" (George 2026-11-16 17:52). RETRO-reruns-2026-11-10-to-15 §6 fixes 1, 6
# and 7: 16 of 25 re-runs were brief errors a run before READY would have found; a verifier that only read wrote
# "holds" for a test that went red (675r); a named backup was never made (664r) and a sha256 had 63 hex (L-404).
# DRY      — a brief whose Kanban row reads READY (A1 passed), and every brief `queue_daemon.py enqueue` copies, has a
#            '## DRY RUN (pasted)' block (Toni template v1-5) outside a code fence, holding at least one run result
#            (an exit code or a count), no unfilled template placeholder, and no NOT READY (one under a condition —
#            "without G-1 → NOT READY" — is the verifier's to judge).
# VERIFY   — a '## Verify report: <path>[, <path>]' header line names the verifier's report(s); each exists, and a
#            report that says a test holds / is unchanged / keep-green / green has a run result in that claim's
#            paragraph, and one that claims any run holds at least one command + exit/count line. Also the CLI:
#            `python3 prefire.py --verify-report <file>…`.
# INPUTS   — every `~/_eos/…` input path the brief names exists (code fences, <!-- --> notes, placeholders, globs and
#            a path called an output aside); a sha256 that looks whole is 64 hex, and matches the file named before it.
# ON when config/repos.yaml says `prefire_dryrun: required` (top level) — the live config does, and
# tests/test_prefire_dryrun_gate.py pins that it does; a config without the key (every scratch config the guard tests
# build) judges as before. PREFIRE_DRYRUN=off skips all three and says so on every fire, like PREFIRE_OPEX.
DRYRUN_ENV = "PREFIRE_DRYRUN"
DRYRUN_CONFIG_KEY = "prefire_dryrun"
DRYRUN_REQUIRED = "required"
DRYRUN_RULING = "Toni template v1-5, D-S7CORE54-63 (3), SD-6(a)"
_DRY_HEADING = re.compile(r'^##[ \t]+DRY RUN \(pasted\)[ \t]*$')
_SECTION_END = re.compile(r'^#{1,2}[ \t]')              # the block runs to the next # or ## heading
# A run result: an exit code, or a count of what ran ("831 passed", "62 red", "2 files").
_RESULT = re.compile(r'\bexit(?:[ _]?code)?[ \t:=]*-?\d+\b'
                     r'|\b\d+\s+(?:passed|failed|failures?|skipped|errors?|tests?|files?|cases?|red|green|hits?)\b'
                     r'|(?<![\w/.-])\d+/\d+(?![\w/.-])',            # "224/224", "(19/19, 67/67)"
                     re.IGNORECASE)
# The v1-5 block's own placeholders, left as written.
_PLACEHOLDER = re.compile(r'<(?:repo|sha7|id|file sha256|n|f|t|x|s|u|path|files|file:line list|reason|cmd|list)>')
_NOT_READY = re.compile(r'\bNOT READY\b')
_VERIFY_LINE = re.compile(r'^##[ \t]*Verify report:[ \t]*(?P<text>.*?)[ \t]*$', re.MULTILINE)
# "named … as keep-green" is a label the template asks for, not an outcome claim
_CLAIM = re.compile(r'(?<!\bas )(?<![\w-])(?:holds|unchanged|keep-green|stays green|still green|green)\b', re.IGNORECASE)
_TEST_REF = re.compile(r'(?:[\w./-]+\.(?:test|spec)\.[cm]?[jt]sx?|\btest_\w+\.py|\btests?/[\w./-]+|\bsit/[\w./-]+)')
_RUN_CLAIM = re.compile(r'\b(?:ran|re-ran|reran|run in a copy|executed)\b', re.IGNORECASE)
_COMMAND = re.compile(r'\b(?:pytest|vitest|npx|npm|node|tsc|python3?|py_compile|git apply|bash|sh)\b')
_QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
_EOS_PATH = re.compile(r'(?:~|/home/[\w.-]+)/_eos/[^\s`\'"()\[\]|,;]+')
_SHA256 = re.compile(r'\bsha256\b[\s:`=]*(?:\(\w+\)[\s:`=]*)?(?P<hex>[0-9a-fA-F]{6,})(?![0-9a-fA-F])', re.IGNORECASE)
_PATH_GLOB = re.compile(r'[*?{}…<>]|\.\.\.')
_OUTPUT_WORD = re.compile(r'\b(?:outputs?|saves?|saved|saving|writes?|written|creates?|created)\b', re.IGNORECASE)
_OUTPUT_AFTER = re.compile(r'[`\'")\s]*(?:is|are)\b[^;·]*?\boutputs?\b', re.IGNORECASE)   # "… is an output"
_CONDITIONAL = re.compile(r'\b(?:without|unless|until|if|once|otherwise)\b', re.IGNORECASE)
_LINE_SUFFIX = re.compile(r':\d+(?:[-–]\d+)?$')


def dryrun_off() -> bool:
    """PREFIRE_DRYRUN=off (any case) — the kill switch. Anything else, or unset, is on."""
    return os.environ.get(DRYRUN_ENV, "").strip().lower() == "off"


def dryrun_on(config: Optional[Path] = None) -> bool:
    """DRY / VERIFY / INPUTS judge: `prefire_dryrun: required` in config/repos.yaml (or `config`, the caller's own copy
    of it — queue_daemon passes its REPOS_CONFIG), and no PREFIRE_DRYRUN=off."""
    if dryrun_off():
        return False
    if config is None:
        value = _config_value(DRYRUN_CONFIG_KEY)
    else:
        try:
            value = (yaml.safe_load(Path(config).read_text(encoding="utf-8")) or {}).get(DRYRUN_CONFIG_KEY)
        except Exception:
            value = None
    return str(value or "").strip().lower() == DRYRUN_REQUIRED


def _unfenced(text: str):
    """(line number, line) for every line outside a ``` / ~~~ fence; fence lines themselves are not given."""
    fenced = False
    for n, raw in enumerate(text.splitlines(), 1):
        if _FENCE.match(raw):
            fenced = not fenced
            continue
        if not fenced:
            yield n, raw


def dry_run_blocks(text: str) -> list[list[tuple[int, str]]]:
    """Every '## DRY RUN (pasted)' block outside a code fence: its lines, (number, text), heading excluded."""
    blocks: list[list[tuple[int, str]]] = []
    cur: Optional[list[tuple[int, str]]] = None
    for n, raw in _unfenced(text):
        if _DRY_HEADING.match(raw):
            cur = []
            blocks.append(cur)
            continue
        if cur is not None and _SECTION_END.match(raw):
            cur = None
        if cur is not None:
            cur.append((n, raw))
    return blocks


def dry_run_problems(filepath: Path) -> list[str]:
    """DRY. [] when the brief has a '## DRY RUN (pasted)' block that holds a run result, no unfilled v1-5 placeholder
    and no unconditional NOT READY; else one 'DRY ❌ …' refusal per fault."""
    blocks = dry_run_blocks(_read(filepath))
    if not blocks:
        return ["DRY ❌ DRY RUN — no '## DRY RUN (pasted)' block outside a code fence: a brief is not READY, and is not "
                "enqueued, without the author's pasted run (%s)" % DRYRUN_RULING]
    lines = [l for b in blocks for l in b]
    out: list[str] = []
    holes = ["line %d: %s" % (n, l.strip()[:100]) for n, l in lines if _PLACEHOLDER.search(l)]
    if holes:
        out.append("DRY ❌ DRY RUN — template placeholder(s) left unfilled: %s" % " | ".join(holes[:3]))
    results = [n for n, l in lines if _RESULT.search(l) and not _PLACEHOLDER.search(l)]
    if not results:
        out.append("DRY ❌ DRY RUN — the block holds no run result: no line gives an exit code or a count "
                   "(a reading of the code is not a result — %s)" % DRYRUN_RULING)
    stop = ["line %d: %s" % (n, l.strip()[:100]) for n, l in lines
            if _NOT_READY.search(l) and not _CONDITIONAL.search(l)]   # "without G-1 → NOT READY" is a condition
    if stop:
        out.append("DRY ❌ DRY RUN — the block says NOT READY: %s" % " | ".join(stop[:3]))
    return out


def dry_run_summary(filepath: Path) -> str:
    """The pass line's detail: where the block is and how many result lines it holds."""
    blocks = dry_run_blocks(_read(filepath))
    lines = [l for b in blocks for l in b]
    first = lines[0][0] - 1 if lines else 0
    return "'## DRY RUN (pasted)' at line %d — %d run-result line(s)" % (
        first, sum(1 for _, l in lines if _RESULT.search(l)))


def verify_report_problems(report: Path) -> list[str]:
    """VERIFY. [] when the verifier's report makes no test-outcome claim it did not run; else 'VERIFY ❌ …' lines.
    A claim — holds / unchanged / keep-green / green on a line that names a test file — needs a run result (exit code
    or count) in its own paragraph. A report that claims any run (or makes such a claim) needs at least one line
    with a command and a result. Words in quotes are a quotation, not a claim."""
    try:
        text = report.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return ["VERIFY ❌ — the verifier report %s cannot be read (%s)" % (report, e.strerror or e)]
    # paragraphs: split at a blank line or a bullet outside a fence; a fenced paste belongs to the paragraph it follows
    paras: list[list[tuple[int, str, bool]]] = [[]]
    fenced = False
    for n, raw in enumerate(text.splitlines(), 1):
        if _FENCE.match(raw):
            fenced = not fenced
            continue
        if not fenced and (not raw.strip() or _BULLET.match(raw)):
            paras.append([])
        if raw.strip():
            paras[-1].append((n, raw, fenced))
    out: list[str] = []
    claims = 0
    for para in paras:
        for n, raw, in_fence in para:
            bare = _QUOTED.sub(" ", raw)
            if not in_fence and _CLAIM.search(bare) and _TEST_REF.search(bare):
                claims += 1
                if not any(_RESULT.search(l) for _, l, _ in para):
                    out.append("VERIFY ❌ — %s line %d claims a test outcome with no run result beside it: %s"
                               % (report.name, n, raw.strip()[:120]))
    ran = claims or any(_RUN_CLAIM.search(_QUOTED.sub(" ", l)) for _, l in _unfenced(text))
    evidence = any(_COMMAND.search(l) and _RESULT.search(l) for l in text.splitlines()) or any(
        any(_COMMAND.search(l) for _, l, _ in para) and any(_RESULT.search(l) for _, l, _ in para) for para in paras)
    if ran and not evidence:
        out.append("VERIFY ❌ — %s claims a run but has no command + exit/count line (verifier checklist v1-5: run it "
                   "or don't claim it)" % report.name)
    return out


def verify_reports(filepath: Path) -> tuple[list[Path], list[str]]:
    """The reports a '## Verify report:' header line names, and the refusals for a line that names none."""
    paths: list[Path] = []
    problems: list[str] = []
    for m in _VERIFY_LINE.finditer(_read(filepath)[:_HEADER_CHARS]):
        named = [p.strip(" `*") for p in re.split(r"[,\s]+", m.group("text")) if p.strip(" `*")]
        named = [p for p in named if "/" in p]
        if not named:
            problems.append("VERIFY ❌ — '%s' names no report path" % m.group(0).strip()[:80])
        paths += [Path(os.path.expanduser(p)) for p in named]
    return paths, problems


def brief_verify_problems(filepath: Path) -> list[str]:
    """VERIFY for a brief: each report its header names exists and passes verify_report_problems."""
    paths, out = verify_reports(filepath)
    for p in paths:
        if not p.is_file():
            out.append("VERIFY ❌ — the verifier report %s named on '## Verify report:' does not exist" % p)
        else:
            out += verify_report_problems(p)
    return out


def _uncommented(text: str):
    """(line number, line) outside code fences and outside <!-- … --> author notes (fold and provenance comments)."""
    in_note = False
    for n, raw in _unfenced(text):
        if in_note:
            if "-->" in raw:
                in_note = False
            continue
        if raw.lstrip().startswith("<!--"):
            in_note = "-->" not in raw
            continue
        yield n, raw


def named_input_problems(filepath: Path) -> list[str]:
    """INPUTS. One 'INPUTS ❌ …' line per `~/_eos/…` input path that does not exist, per sha256 of 17-63 or 65+ hex
    (one that looks whole and is not 64 — L-404's 63; 16 or fewer is an abbreviation, not judged), and per 64-hex
    sha256 that does not match the existing file named just before it ("`<path>` sha256 <hex>"). Not judged: code
    fences, <!-- … --> notes, placeholders and globs, and a path the words beside it call an output ("a STOP saves
    it as …", "… is an output")."""
    out: list[str] = []
    for n, raw in _uncommented(_read(filepath)):
        found = list(_EOS_PATH.finditer(raw))
        named: list[tuple[int, Path]] = []                 # (end offset, existing file) — what a sha may name
        for i, m in enumerate(found):
            tok = _LINE_SUFFIX.sub("", m.group(0).rstrip(".:"))
            if _PATH_GLOB.search(tok):
                continue
            before = raw[max(found[i - 1].end() if i else 0, m.start() - 40):m.start()]
            after = raw[m.end():min(found[i + 1].start() if i + 1 < len(found) else len(raw), m.end() + 60)]
            p = Path(os.path.expanduser(tok))
            if p.is_file():
                named.append((m.end(), p))
            if _OUTPUT_WORD.search(before) or _OUTPUT_AFTER.match(after):
                continue
            if not p.exists():
                out.append("INPUTS ❌ — '%s' (line %d) does not exist (retro fix 6, L-404)" % (tok, n))
        for m in _SHA256.finditer(raw):
            hx = m.group("hex")
            if len(hx) <= 16:
                continue
            if len(hx) != 64:
                out.append("INPUTS ❌ — sha256 '%s…' (line %d) is %d hex, not 64 (L-404)" % (hx[:16], n, len(hx)))
                continue
            near = [f for end, f in named if end <= m.start() and m.start() - end <= 12]   # "`<path>` sha256 <hex>"
            if near and _sha256_of(near[-1]) != hx.lower():
                out.append("INPUTS ❌ — sha256 %s… (line %d) does not match %s" % (hx[:12], n, near[-1]))
    return out


def _sha256_of(path: Path) -> Optional[str]:
    import hashlib
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def named_inputs_summary(filepath: Path) -> str:
    paths = shas = 0
    for _, raw in _unfenced(_read(filepath)):
        paths += sum(1 for m in _EOS_PATH.finditer(raw) if not _PATH_GLOB.search(m.group(0)))
        shas += sum(1 for _ in _SHA256.finditer(raw))
    return "%d ~/_eos path(s) exist · %d sha256, each 64 hex and matching" % (paths, shas)


def enqueue_problems(filepath: Path, config: Optional[Path] = None) -> list[str]:
    """What `queue_daemon.py enqueue` refuses a brief for: DRY alone (SD-6(a): "or that is being enqueued"), switched
    by `config` (the daemon's config/repos.yaml). [] when DRY is not on (dryrun_on)."""
    return dry_run_problems(filepath) if dryrun_on(config) else []


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
    (_APPLY_LINE, _HEADER_CHARS, "prefire"),
    (_AUTHOR_LINE, _HEADER_CHARS, "prefire"),
    (_VERIFY_LINE, _HEADER_CHARS, "prefire"),
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
    elif dryrun_on():
        failures += dry_run_problems(filepath)                          # DRY [ORCH-PREFIRE-DRYRUN-GATE-1]

    line = _runtime_line(filepath)
    estimate = parse_declared_estimate(filepath)
    trigger = parse_microfire_trigger(filepath)
    # [ORCH-PREFIRE-PARSE-HAZARDS-1] (ii): an A2 SIZING failure says when the micro-fire line it saw is no trigger
    not_a_trigger = " " + MICROFIRE_NOT_A_TRIGGER if not trigger and microfire_line(filepath) is not None else ""
    regate_raw = regate_line(filepath)
    regate = parse_regate(filepath)
    applying = apply_line(filepath) is not None
    failures += apply_patch_problems(filepath)                          # APPLY [ORCH-APPLY-PATCH-1]

    if regate_raw is not None and regate is None:
        failures.append("A2 RE-GATE — '## Re-gate of: %s' is not '<route branch> <sha>' (ORCH-REGATE-GATE-ONLY-1)"
                        % regate_raw)
    elif regate is not None:
        pass  # [ORCH-REGATE-GATE-ONLY-1] gates only, no executor: the sizing floor is waived (report says so)
    elif applying:
        pass  # [ORCH-APPLY-PATCH-1] a saved patch, no executor: the sizing floor is waived (report says so)
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
    if dryrun_on():
        failures += brief_verify_problems(filepath)                     # VERIFY [ORCH-PREFIRE-DRYRUN-GATE-1]
        failures += named_input_problems(filepath)                      # INPUTS [ORCH-PREFIRE-DRYRUN-GATE-1]

    return failures


# [PREFIRE-NPM-HOOK-NOTE-1] (Kanban 886) — the executor's npm hook (executor/hooks/npm_frozen.py, ORCH-NPM-FROZEN-1)
# refuses `npm exec`, a bare `npx <tool>` (no `--no-install`) and every npm subcommand off its list. A brief that tells
# the executor to run one costs a refusal at best (865r, 2026-11-22: the executor re-wrote `npx vitest` as
# `npx --no-install vitest`) and a STOP at worst (873: its A0-3 `npm exec` was refused, nothing built, a re-fire owed).
# prefire now names each such command with the hook's own line — a NOTE printed beside the verdict, never a failure:
# the executor can still re-write it, and a brief already queued is never set aside for it.
NPM_HOOK = Path(__file__).resolve().parent / "executor" / "hooks" / "npm_frozen.py"     # tests patch it
NPM_NOTE_MAX = 5
_NPM_CMD_SPAN = re.compile(r"`((?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*(?:timeout\s+\S+\s+)?(?:npx|npm)\s[^`\n]*)`")
_DIFF_FENCE = re.compile(r"^```diff\b.*?^```", re.MULTILINE | re.DOTALL)


def _npm_hook():
    """The hook module, loaded from its file (it is a script, not a package); None when it cannot be loaded."""
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location("_prefire_npm_frozen", NPM_HOOK)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def npm_hook_notes(filepath: Path) -> list[str]:
    """Each distinct backticked `npx …` / `npm …` command in the brief (outside a ```diff fence — patch text is data)
    that the hook would refuse when run at the brief's repo root (`project_dir` of its `#!queue … repo=`), with the
    hook's line, at most NPM_NOTE_MAX. [] when the repo or the hook cannot be read (nothing judged, nothing said)."""
    entry = _repo_entry(queue_header(filepath).get("repo"))
    project = entry.get("project_dir")
    hook = _npm_hook() if project else None
    if hook is None:
        return []
    text = _DIFF_FENCE.sub("", _read(filepath))
    seen, notes = set(), []
    for m in _NPM_CMD_SPAN.finditer(text):
        cmd = m.group(1).strip()
        if cmd in seen:
            continue
        seen.add(cmd)
        try:
            why = hook.judge_text(cmd, str(project), {}, 0)
        except Exception:
            continue
        if why:
            notes.append("NPM ⚠ `%s` — the executor's npm hook refuses it: %s"
                         % (cmd if len(cmd) <= 90 else cmd[:89] + "…", " ".join(str(why).split())[:200]))
    return notes[:NPM_NOTE_MAX] + (["NPM ⚠ … and %d more" % (len(notes) - NPM_NOTE_MAX)] if len(notes) > NPM_NOTE_MAX else [])


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
    if dryrun_off():
        print("  ⚠⚠ %s=off — DRY / VERIFY / INPUTS (%s: the pasted dry run, the verifier's runs, the named inputs) "
              "SKIPPED for %s. Unset it to turn them back on." % (DRYRUN_ENV, DRYRUN_RULING, filepath.name))
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
        elif apply_line(filepath) is not None:
            detail = ("apply-patch %s: A2 sizing floor waived — no executor runs (ORCH-APPLY-PATCH-1)"
                      % parse_apply(filepath)[0].name)
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
        if apply_line(filepath) is not None:                            # [ORCH-APPLY-PATCH-1]
            print("  APPLY ✅ %s" % apply_patch_summary(filepath))
        for note in npm_hook_notes(filepath):                           # [PREFIRE-NPM-HOOK-NOTE-1] a note only
            print("  %s" % note)
        if dryrun_on():                                                 # [ORCH-PREFIRE-DRYRUN-GATE-1]
            print("  DRY ✅ %s" % dry_run_summary(filepath))
            reports, _ = verify_reports(filepath)
            print("  VERIFY ✅ %s" % (", ".join(r.name for r in reports) + " — every claim has a run beside it"
                                     if reports else "no '## Verify report:' line — no report judged"))
            print("  INPUTS ✅ %s" % named_inputs_summary(filepath))
        return True

    print("\n%s" % bar)
    print("  ⛔ PRE-FIRE ASSERTIONS FAILED — %s" % filepath.name)
    print("%s" % bar)
    for f in failures:
        print("  • %s" % f)
    for line in opex:
        print("  %s" % line)
    for note in npm_hook_notes(filepath):                               # [PREFIRE-NPM-HOOK-NOTE-1] a note only
        print("  %s" % note)
    print("\n  Fix the brief and re-fire. --force bypasses ALL safety checks.")
    print("%s\n" % bar)
    return False


if __name__ == "__main__":
    import sys
    ok = True
    if sys.argv[1:2] == ["--verify-report"]:                            # [ORCH-PREFIRE-DRYRUN-GATE-1] VERIFY
        for arg in sys.argv[2:]:
            problems = verify_report_problems(Path(arg))
            print("=== %s: %s" % (Path(arg).name, "VERIFY ✅ every claim has a run beside it" if not problems else
                                  "VERIFY ⛔ refused"))
            for line in problems:
                print("  • %s" % line)
            ok = ok and not problems
        raise SystemExit(0 if ok else 1)
    for arg in sys.argv[1:]:
        p = Path(arg)
        print("=== %s" % p.name)
        ok = report(p) and ok
    raise SystemExit(0 if ok else 1)
