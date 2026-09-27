#!/usr/bin/env python3
# filename: canon_assert.py
"""BOOT ASSERT as a program — B1–B9 over the Spectricom canon folder (BOOT-ASSERT-2 / 2b, S7-CORE-11).

Every verdict is decided from DISK and GIT only, never from memory or context — the same
principle as doc-sweep.sh, which is the sibling tool this one sits beside (doc-sweep answers
"is this slim STALE against its repo?"; canon_assert answers "do the pointers that a session
briefs from agree with each other and with disk?").

    python3 canon_assert.py                 # real canon folder, real repos under ~
    python3 canon_assert.py --canon DIR --repo-root DIR

Exit 0 only when every assertion is PASS. UNKNOWN (a file missing or unparseable) is never a
pass and is never counted as one.

What a "pointer" is here, because nine hand-written files disagree on the spelling:
  * a pointer is a `vN-M` token (optionally followed by DRAFT), classified into a FAMILY by an
    alias regex matched against the markdown-stripped text immediately before the token —
    so "Bugs **v1-41**", "Bug Registry v1-41" and "[SCA_Bug_Registry_v1-41](...)" are one
    family and "Yorsie_Bug_Registry_v1-32" is not;
  * a SOURCE's pointer for a family is the HIGHEST version it names for that family. Sources
    are layered by hand ("Kanban v0-33 · everything else as the S7-CORE-10 line below"), and
    the newest layer is by construction the highest version, so "max per family" is what a
    human reading the file top-down arrives at, without needing to order sessions;
  * Canon_Index carries THREE pointer sources: the frontmatter `updated:` line, the
    `> **Canon latest …**` blockquotes in the body preamble, and the `- **…**` pointer bullets
    in the body preamble (the preamble is everything between the frontmatter and the first
    `# ` heading). B6 exists because at S7-CORE-11 two of these disagreed inside one file.
  * Canon_Index is APPEND-ONLY: every session prepends a bullet and a blockquote and the old
    ones stay as history. So B6 reads the NEWEST BLOCK ONLY of each of the three sources
    (BOOT-ASSERT-2b). The newest block is identified by SESSION ID, not by position — every
    bullet, blockquote and `updated:` segment leads with its session id, and the live file
    has had a backfilled older block placed above the current one. The block is the current
    session (the first `updated:` segment) plus the one `prior:` session it is layered over,
    because the in-progress block is written as a delta ("Kanban v0-33 · everything else as
    the S7-CORE-10 EOS line below") and the EOS block it delegates to is the one that
    restates the full set. Nothing older is read. B1, B3, B4 and B7 keep reading the whole
    file as before.

Families not covered by the alias table (context slims, PDLC record, Gemma prompt) are not
asserted — say so rather than guess.

B8's FAIL scope is the CORE BRIEF SET (SESSION-BOOT.md: "the pointers a session briefs from,
not canon"): the canon folder is shared with other products and eras, so a stale family
outside that set is reported as INFO and never changes the exit code. The set is derived in
core_brief_set() and nowhere else.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

HERE = Path(__file__).resolve().parent
DOC_SWEEP = HERE / "doc-sweep.sh"

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"
ASSERTION_IDS = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9"]

Version = tuple[int, int]

# `v1-47`, `v2-12 DRAFT`, `v2-12_DRAFT` — never `v1.0` (only the Preference Codex uses dots,
# and it is not a pointer-bearing family).
VERSION_RE = re.compile(r"(?<![A-Za-z0-9])v(\d+)-(\d+)(?![0-9])(?P<draft>[ _]DRAFT)?")
# S6S48 · S7-CORE-11 · S7-OPS-1 · S7-CHAT · S7-FABLE-DIGDEEP
SESSION_RE = re.compile(r"\bS\d+(?:S\d+|(?:-[A-Z]+)+(?:-\d+)?)\b")
# Spectricom_Document_Registry_v5-214.md · spectricom-context-slim-v4-34-infra.md ·
# Spectricom_Product_Roadmap_v2-12_DRAFT.md · Spectricom_Document_Registry_v5-84-DRAFT.md
FILE_RE = re.compile(r"^(?P<stem>.+?)[_-]v(?P<maj>\d+)-(?P<min>\d+)(?P<suffix>[-_][A-Za-z0-9][A-Za-z0-9_-]*)?\.md$")
# B9 residue: a final extension ending in "bak" (.bak, .S7S3bak, .preUSAGE1bak) or a Gemma draft.
BAK_RE = re.compile(r"\.[A-Za-z0-9]*bak$", re.I)
GEMMA_RE = re.compile(r"_DRAFT_GEMMA")
# doc-sweep.sh's latest() ignores these too; they are never "the newest member" of a family.
NOT_A_MEMBER_RE = re.compile(r"BAD|_DRAFT_GEMMA|\.[A-Za-z0-9]*bak$", re.I)
ANCHOR_RE = re.compile(r"git-anchor:\s*([0-9a-f]{7,40})")


def vstr(v: Optional[Version], draft: bool = False) -> str:
    if v is None:
        return "—"
    return f"v{v[0]}-{v[1]}" + (" DRAFT" if draft else "")


def default_canon_dir() -> Optional[Path]:
    """The canon path is READ from doc-sweep.sh's `CANON="…"` line — one source, not two."""
    try:
        text = DOC_SWEEP.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r'^CANON="([^"]+)"', text, re.M)
    return Path(m.group(1)) if m else None


# ── where a value was read from ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Src:
    file: str
    line: int = 0          # 0 → not a line (a directory listing, a git command)

    def __str__(self) -> str:
        return f"{self.file}:{self.line}" if self.line else self.file


@dataclass
class Pointer:
    version: Version
    draft: bool
    src: Src
    text: str              # the snippet the version was read from, for the human


# ── families ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Family:
    key: str                       # printed id
    stem: str                      # regex for the on-disk filename stem (before `_vN-M`)
    aliases: tuple[str, ...]       # regexes; matched against the END of the stripped prefix


# Order matters: the first family whose alias matches the prefix wins. Specific before generic.
STATIC_FAMILIES: list[Family] = [
    Family("Bug Registry", r"SCA_Bug_Registry",
           (r"(?<!Yorsie[_ ])(?<!Mini_Me[_ ])(?<!Mini-Me[_ ])(?:SCA[_ ])?Bug[_ ]Registry", r"(?<![A-Za-z])Bugs")),
    Family("Registry", r"Spectricom_Document_Registry",
           (r"(?<!PDLC[_ ])(?:Spectricom_)?Document[_ ]Registry",
            r"(?<!Bug[_ ])(?<!Document[_ ])(?<![A-Za-z])Registry",
            r"(?<![A-Za-z])Reg")),
    Family("Feature Index", r"SCA_Feature_Index", (r"(?:SCA[_ ])?Feature[_ ]Index", r"(?<![A-Za-z])FI")),
    Family("Coverage Matrix", r"SCA_UAT_Coverage_Matrix", (r"(?:SCA_UAT_)?(?:Coverage[_ ])?Matrix",)),
    Family("Kanban", r"SCP_Kanban", (r"(?:SCP_)?Kanban",)),
    Family("Roadmap", r"Spectricom_Product_Roadmap", (r"(?:Spectricom_)?(?:Product[_ ])?Roadmap",)),
    Family("Codex", r"George_Decision_Codex", (r"(?<!Pattern[_ ])(?:George_Decision_)?Codex",)),
    Family("Logs", r"Spectricom_Logs", (r"(?:Spectricom_)?Logs",)),
    Family("PCU", r"Spectricom_Pending_Canon_Updates",
           (r"(?:Spectricom_)?Pending_Canon_Updates", r"(?<![A-Za-z])PCU")),
    Family("Master Plan", r"Spectricom_Parallel_Dev_Master_Plan",
           (r"(?:Spectricom_Parallel_Dev_)?Master[_ ]Plan", r"(?<![A-Za-z])MP")),
    Family("EOS Protocol", r"EOS_Protocol", (r"EOS[_ ]Protocol",)),
]

SDLC_FILE_RE = re.compile(r"^SCP_SDLC_Decomposition_(?P<track>[A-Za-z0-9]+)_(?P<batch>Batch\d+)_v\d+-\d+")


def sdlc_families(canon: Path) -> list[Family]:
    """B7's SDLC family list is DERIVED from filenames — there is no list to rot."""
    found: dict[tuple[str, str], None] = {}
    for name in list_root(canon):
        m = SDLC_FILE_RE.match(name)
        if m and not NOT_A_MEMBER_RE.search(name):
            found[(m["track"], m["batch"])] = None
    batches = [b for _, b in found]
    fams = []
    for track, batch in found:
        aliases = [rf"(?:SCP_)?SDLC(?:_Decomposition)?[_ ]{track}[_ ]{batch}"]
        if batches.count(batch) == 1:      # "… / Batch4 v0-1" with the track implied is unambiguous
            aliases.append(rf"(?<![A-Za-z_]){batch}")
        fams.append(Family(f"SDLC {track} {batch}", rf"SCP_SDLC_Decomposition_{track}_{batch}", tuple(aliases)))
    return sorted(fams, key=lambda f: f.key)


def all_families(canon: Path) -> list[Family]:
    return STATIC_FAMILIES + sdlc_families(canon)


# The two context slims are briefed from but carry no pointer alias (their versions are cited
# as "clinical slim v1-67 · infra slim v4-34", never compared), so they are not Families.
CORE_SLIM_STEMS: tuple[str, ...] = (r"spectricom-context-slim-clinical", r"spectricom-context-slim-infra")


def core_brief_set(families: list[Family]) -> list[str]:
    """The Core brief set, as filename-stem regexes over root_families() keys — defined ONCE.

    Registry, PCU, Logs, Master Plan, Kanban, Codex, Feature Index, Coverage Matrix, Bug
    Registry, Roadmap, EOS Protocol and the SDLC families are exactly STATIC_FAMILIES plus
    sdlc_families() — the same objects B1–B7 read, so B7's list and B8's scope cannot drift
    apart. The context slims are the only members that are not pointer families.
    """
    return [f.stem for f in families] + list(CORE_SLIM_STEMS)


def is_core(key: str, core: list[str]) -> bool:
    return any(re.fullmatch(stem, key) for stem in core)


# ── pointer extraction ───────────────────────────────────────────────────────────────────
STRIP_MD = re.compile(r"[*`\[\]()]")


def classify(prefix: str, families: Iterable[Family]) -> Optional[Family]:
    for fam in families:
        for alias in fam.aliases:
            if re.search(alias + r"[ _]?$", prefix):
                return fam
    return None


def extract_pointers(lines: Iterable[tuple[int, str]], file: str, families: list[Family]) -> dict[str, Pointer]:
    """Max version per family over the given (lineno, text) lines."""
    out: dict[str, Pointer] = {}
    for lineno, text in lines:
        for m in VERSION_RE.finditer(text):
            prefix = STRIP_MD.sub("", text[: m.start()])[-80:]
            fam = classify(prefix, families)
            if fam is None:
                continue
            ver = (int(m.group(1)), int(m.group(2)))
            cur = out.get(fam.key)
            if cur is None or ver > cur.version:
                snippet = text[max(0, m.start() - 40): m.end() + 8].strip()
                out[fam.key] = Pointer(ver, bool(m.group("draft")), Src(file, lineno), snippet)
    return out


# ── file readers ─────────────────────────────────────────────────────────────────────────
def read_lines(path: Path) -> Optional[list[str]]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None


def list_root(canon: Path) -> list[str]:
    try:
        return sorted(p.name for p in canon.iterdir() if p.is_file())
    except OSError:
        return []


@dataclass
class DiskFamily:
    key: str
    members: list[tuple[Version, str]] = field(default_factory=list)   # (version, filename)

    @property
    def newest(self) -> Optional[tuple[Version, str]]:
        return max(self.members) if self.members else None


def disk_family(canon: Path, stem_re: str, key: str) -> DiskFamily:
    """Members of one family in the canon ROOT (Old/ is not scanned — that is the point of B8)."""
    rx = re.compile(rf"^{stem_re}[_-]v(\d+)-(\d+)(?:[-_][A-Za-z0-9_-]*)?\.md$")
    df = DiskFamily(key)
    for name in list_root(canon):
        m = rx.match(name)
        if m and not NOT_A_MEMBER_RE.search(name):
            df.members.append(((int(m.group(1)), int(m.group(2))), name))
    df.members.sort()
    return df


def h1(path: Path) -> Optional[tuple[int, str]]:
    lines = read_lines(path)
    if lines is None:
        return None
    for i, line in enumerate(lines, 1):
        if line.startswith("# "):
            return i, line
    return None


def h1_version(path: Path) -> Optional[tuple[Version, Src, str]]:
    got = h1(path)
    if not got:
        return None
    i, line = got
    m = VERSION_RE.search(line)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2))), Src(path.name, i), line.strip()


@dataclass
class CanonIndex:
    file: str
    frontmatter: dict[str, Pointer]      # the `updated:` line
    blockquotes: dict[str, Pointer]      # `> …` lines of the preamble
    bullets: dict[str, Pointer]          # `- …` lines of the preamble
    updated_line: Optional[tuple[int, str]]
    has_blockquotes: bool
    has_bullets: bool
    # BOOT-ASSERT-2b — the newest block only, keyed by session id (B6 reads these three).
    window: tuple[str, ...] = ()                                   # (current, prior) session ids
    newest_frontmatter: dict[str, Pointer] = field(default_factory=dict)
    newest_blockquotes: dict[str, Pointer] = field(default_factory=dict)
    newest_bullets: dict[str, Pointer] = field(default_factory=dict)
    newest_lines: dict[str, list[int]] = field(default_factory=dict)   # source → line numbers read
    body_sessions: dict[str, list[str]] = field(default_factory=dict)  # source → session ids seen

    @property
    def union(self) -> dict[str, Pointer]:
        out: dict[str, Pointer] = {}
        for src in (self.frontmatter, self.blockquotes, self.bullets):
            for k, p in src.items():
                if k not in out or p.version > out[k].version:
                    out[k] = p
        return out


PRIOR_SPLIT_RE = re.compile(r"\s·\s*prior:")


def session_of(text: str) -> Optional[str]:
    """The session id a block belongs to: the FIRST id in its text (blocks lead with it)."""
    m = SESSION_RE.search(text)
    return m.group(0) if m else None


def session_window(updated: str) -> tuple[str, ...]:
    """(current, prior): the first `updated:` segment's session and the first `prior:` segment
    naming a different one. The frontmatter declares its own layering; nothing is ordered."""
    ids = [session_of(seg) for seg in PRIOR_SPLIT_RE.split(updated)]
    if not ids or ids[0] is None:
        return ()
    cur = ids[0]
    prior = next((i for i in ids[1:] if i and i != cur), None)
    return (cur, prior) if prior else (cur,)


def parse_canon_index(canon: Path, families: list[Family]) -> Optional[CanonIndex]:
    path = canon / "Canon_Index.md"
    lines = read_lines(path)
    if lines is None or not lines or lines[0].strip() != "---":
        return None
    try:
        fm_end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None
    updated = next(((i + 1, l) for i, l in enumerate(lines[:fm_end]) if l.startswith("updated:")), None)
    if updated is None:
        return None
    body = lines[fm_end + 1:]
    preamble: list[tuple[int, str]] = []
    for off, l in enumerate(body):
        if l.startswith("# "):
            break
        preamble.append((fm_end + 2 + off, l))
    bq = [(n, l) for n, l in preamble if l.startswith(">")]
    bl = [(n, l) for n, l in preamble if l.startswith("-")]
    window = session_window(updated[1])
    fm_segs = [(updated[0], seg) for seg in PRIOR_SPLIT_RE.split(updated[1]) if session_of(seg) in window]
    bq_new = [(n, l) for n, l in bq if session_of(l) in window]
    bl_new = [(n, l) for n, l in bl if session_of(l) in window]
    return CanonIndex(
        file=path.name,
        frontmatter=extract_pointers([updated], path.name, families),
        blockquotes=extract_pointers(bq, path.name, families),
        bullets=extract_pointers(bl, path.name, families),
        updated_line=updated, has_blockquotes=bool(bq), has_bullets=bool(bl),
        window=window,
        newest_frontmatter=extract_pointers(fm_segs, path.name, families),
        newest_blockquotes=extract_pointers(bq_new, path.name, families),
        newest_bullets=extract_pointers(bl_new, path.name, families),
        newest_lines={"blockquote": [n for n, _ in bq_new], "bullet": [n for n, _ in bl_new]},
        body_sessions={"blockquote": [s for _, l in bq if (s := session_of(l))],
                       "bullet": [s for _, l in bl if (s := session_of(l))]},
    )


@dataclass
class Hot:
    file: str
    h1: Optional[tuple[int, str]]
    canon_latest: dict[str, Pointer]
    has_canon_latest: bool
    repos: list[tuple[int, str, str, int]]     # (line, name, sha, unpushed)


def parse_hot(canon: Path, families: list[Family]) -> Optional[Hot]:
    path = canon / "hot.md"
    lines = read_lines(path)
    if lines is None:
        return None
    top = next(((i + 1, l) for i, l in enumerate(lines) if l.startswith("# ")), None)
    section: list[tuple[int, str]] = []
    in_sec = False
    for i, l in enumerate(lines, 1):
        if l.startswith("#"):
            in_sec = bool(re.match(r"#+\s*Canon latest\b", l))
            continue
        if in_sec:
            section.append((i, l))
    repos: list[tuple[int, str, str, int]] = []
    for i, l in enumerate(lines, 1):
        cells = [c.strip() for c in l.strip().strip("|").split("|")] if l.lstrip().startswith("|") else []
        if len(cells) < 3 or cells[0] in ("Repo", "") or set(cells[0]) <= {"-"}:
            continue
        sha = STRIP_MD.sub("", cells[1]).strip()
        if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
            continue
        m = re.search(r"(\d+)\s+unpushed", cells[2])
        repos.append((i, cells[0], sha, int(m.group(1)) if m else 0))
    return Hot(path.name, top, extract_pointers(section, path.name, families), bool(section), repos)


# ── git ──────────────────────────────────────────────────────────────────────────────────
def git(repo: Path, *args: str) -> Optional[str]:
    if not (repo / ".git").exists():
        return None
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def git_head(repo: Path) -> Optional[str]:
    return git(repo, "rev-parse", "HEAD")


def git_branch(repo: Path) -> str:
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "?"


def git_unpushed(repo: Path) -> Optional[int]:
    for rng in ("origin/main..HEAD", "@{u}..HEAD"):
        out = git(repo, "rev-list", "--count", rng)
        if out is not None and out.isdigit():
            return int(out)
    return None


# ── QUEUE-RETIRE-1 · the trunk invariant (S7-CORE-15 · D-S7CORE14-02) ────────────────────
# B6's other half, the one that is not about canon pointers:
#
#     no brief file remains in queue/ whose route has already merged to its repo's merge target
#
# It has been a human running two commands at boot. RESOLVER-1 shows what one missed run costs:
# merged 21 Sep as f1359634, the brief stayed in queue/ for five days, and the 26 Sep restart
# re-fired an already-merged route. Shipped here as a PREDICATE — empty list when clean — so the
# boot path and the tests read the same implementation and nobody writes a second copy.
#
# Disk and git only, like every other verdict in this file. It reports; it never moves a file,
# writes a ref or imports the fire path. The caller retires.
#
# EVIDENCE IS ALWAYS BRANCH-NAMED, never "the brief file is on the merge target". Briefs are
# committed to their repo BEFORE the route fires (`brief(s7core14): RESOLVER-1, MEDS-UI-2` at
# 8a9b6f46), so file presence is evidence of staging and not of a merge; keying on it would
# retire work that never ran. Three detectors, all keyed to the route branch
# `<branch_prefix>-<brief stem>`, strongest first:
#
#   1. MERGE COMMIT — a merge commit on the merge target naming the branch in its subject.
#   2. REFLOG — a `merge <branch>` entry in the merge target's reflog whose commit is still
#      reachable. The clinical-mp lane merges FAST-FORWARD, so for most routes there is no
#      merge commit to find at all (`merge orch-mp-40-…: Fast-forward`) and this is the only
#      record left once the branch is deleted.
#   3. BRANCH REF — the branch still exists and is an ancestor of the merge target. The
#      meta-fire `--ff-only` lane never deletes it, and RESOLVER-1's own branch tip IS
#      f1359634 — this is the detector that catches the incident that caused this brief.
#
# The asymmetry is deliberate and is the whole safety argument: a MISSED violation leaves B6 to
# the human for one brief; a WRONG one retires work that never ran. Detector 3 cannot tell a
# merged fast-forward from a branch created and never committed to, so it is tried last and is
# named in the violation it produces. Retirement moves a brief to queue/done/ — recoverable,
# never deleted.


@dataclass(frozen=True)
class QueueRepo:
    """The four facts about a repo that decide whether a brief's route has landed.

    Resolved by the caller from its own config (the daemon reads config/repos.yaml); this
    module stays free of the fire path's configuration.
    """
    name: str
    path: Path
    merge_target: str = "main"
    branch_prefix: str = "orch"

    def branch_for(self, brief: str) -> str:
        """`39-resolver-1-….md` → `orch-mp-39-resolver-1-…` — the route branch the orchestrator
        creates from the batch file's stem."""
        return f"{self.branch_prefix}-{Path(brief).stem}"


@dataclass(frozen=True)
class Violation:
    """One brief that is still queued although its route is already on the merge target."""
    brief: str            # filename, as it sits in queue/
    path: Path            # where it sits — the caller should not have to re-join
    repo: str
    branch: str
    commit: str           # the merge commit that already carries it
    subject: str          # that commit's subject line, for the human
    evidence: str         # which detector fired, in words

    def __str__(self) -> str:
        return (f"{self.brief}: route {self.branch} is already on {self.repo}/"
                f"{self.commit[:8]} [{self.evidence}] {self.subject}").strip()


def _git_rc(repo: Path, *args: str) -> int:
    """Exit code only — for the git commands whose answer IS the exit code (`--is-ancestor`)."""
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).returncode


def _is_ancestor(repo: Path, rev: str, of: str) -> bool:
    return _git_rc(repo, "merge-base", "--is-ancestor", rev, of) == 0


def _subject(repo: Path, sha: str) -> str:
    return git(repo, "log", "-1", "--format=%s", sha) or ""


def _landed(repo: QueueRepo, branch: str) -> Optional[tuple[str, str, str]]:
    """(commit, subject, evidence) if `branch` is already on repo's merge target, else None.

    Nothing readable (no repo, no .git, no merge target) ⇒ None: unreadable is never a
    violation, because a violation authorises a retirement.
    """
    target = repo.merge_target
    if git(repo.path, "rev-parse", "--verify", "--quiet", target) is None:
        return None

    # 1 · a merge commit that names the branch. `git merge X` writes `Merge branch 'X'`.
    merges = git(repo.path, "log", target, "--merges", "-n", "500", "--format=%H\x1f%s") or ""
    for line in merges.splitlines():
        sha, _, subject = line.partition("\x1f")
        if f"'{branch}'" in subject:
            return sha, subject, "merge commit"

    # 2 · the merge target's reflog. A fast-forward merge leaves no commit of its own, only
    #     `merge <branch>: Fast-forward` here. Reachability is re-checked: a reflog entry
    #     survives a reset, and a reset-away merge has not landed.
    reflog = git(repo.path, "reflog", "show", "--format=%H\x1f%gs", target) or ""
    for line in reflog.splitlines():
        sha, _, msg = line.partition("\x1f")
        if msg.startswith(f"merge {branch}:") and _is_ancestor(repo.path, sha, target):
            return sha, _subject(repo.path, sha), "reflog merge into " + target

    # 3 · the branch ref itself, still there and wholly contained in the merge target. Last,
    #     because it is the one detector that cannot distinguish a merged fast-forward from a
    #     branch that was created and never committed to.
    tip = git(repo.path, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    if tip and _is_ancestor(repo.path, tip, target):
        return tip, _subject(repo.path, tip), f"branch ref merged into {target}"

    return None


def queue_header(path: Path) -> dict[str, str]:
    """`#!queue model=… effort=… repo=…` on line 1 → {key: value}; no header ⇒ {}.

    The queue's own one-line dialect, parsed in ONE place — the scheduler reads it to decide
    how to fire a brief, the trunk invariant reads it to decide which repo the brief belongs
    to, and they must never disagree about what it says.
    """
    try:
        first = Path(path).read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError, UnicodeDecodeError):
        return {}
    if not first.startswith("#!queue"):
        return {}
    return dict(tok.split("=", 1) for tok in first.split()[1:] if "=" in tok)


def check_queue_trunk_invariants(queue_dir: Path, repo: QueueRepo) -> list[Violation]:
    """Briefs still in `queue_dir` whose route has already merged to `repo`'s merge target.

    EMPTY WHEN CLEAN. That is the acceptance oracle for QUEUE-RETIRE-1 and the automated form
    of boot assert B6.

    Scans the TOP LEVEL of queue_dir only: `done/`, `failed/` and `held/` are the scheduler's
    own trays and a brief parked there is not queued. A queue holds briefs for several repos,
    each brief naming its own (`#!queue repo=…`): a brief that names a DIFFERENT repo is
    skipped rather than looked for here, so two repos that happen to share a branch prefix
    cannot answer for each other's routes. A brief naming none is taken as this repo's — the
    same default the scheduler applies when it fires one. Call once per repo the queue names.
    """
    queue_dir = Path(queue_dir)
    if not queue_dir.is_dir():
        return []
    out: list[Violation] = []
    for brief in sorted(p for p in queue_dir.glob("*.md") if p.is_file()):
        declared = queue_header(brief).get("repo")
        if declared and declared != repo.name:
            continue
        branch = repo.branch_for(brief.name)
        landed = _landed(repo, branch)
        if landed is None:
            continue
        sha, subject, evidence = landed
        out.append(Violation(brief=brief.name, path=brief, repo=repo.name, branch=branch,
                             commit=sha, subject=subject, evidence=evidence))
    return out


# ── ORCH-STALEBASE-1 · the branch-side invariant (S7-CORE-15 · BUG-S7CORE14-ORCH-STALEBASE-01) ──
# The trunk invariant above asks "has this route already landed?". This one asks the question
# before the route runs at all:
#
#     a route branch contains its merge target's current tip
#
# L-UI-SAFETY-1 (clinical-mp) is what its absence costs: attempt 1 went red and its branch was
# preserved on purpose; main moved 7 commits; attempt 2 `git checkout -b` failed on the existing
# name and the orchestrator switched to the old branch. The gate measured against a base main no
# longer looked like, said PASS, and the merge conflicted. The orchestrator asserts this at the
# moment of action, right after it cuts the branch and before it hands off to the executor.
#
# The set is QUANTIFIED by the caller: exactly `repo.branch_for(b)` for the briefs it names,
# never "every orch-* head". A retired `<branch>--stale-<ts>` is not `branch_for` of any brief
# (a brief stem never contains `--stale-`), so it is never in the set.


@dataclass(frozen=True)
class StaleBaseViolation:
    """A route branch whose base is behind the merge target's current tip."""
    repo: str
    branch: str
    merge_target: str
    target_tip: str          # sha the merge target is at now
    branch_tip: str          # sha the branch is at now
    merge_base: str          # git merge-base <target> <branch>
    behind: int              # git rev-list --count <branch>..<target>  (>0 by construction)

    def __str__(self) -> str:
        return (f"{self.branch} is {self.behind} commit(s) behind {self.merge_target} "
                f"({self.target_tip[:8]}): cut at {self.merge_base[:8]}, tip {self.branch_tip[:8]}")


def check_branch_freshness_invariants(repo: QueueRepo, briefs: Iterable[str]) -> list[StaleBaseViolation]:
    """For each brief name in `briefs`, the route branch `repo.branch_for(brief)`, IF it
    exists as refs/heads/<branch>, must contain the merge target's current tip:
    `git merge-base --is-ancestor <merge_target> <branch>` must succeed.
    EMPTY WHEN CLEAN. A branch that does not exist is not a violation (nothing to be
    stale). An unreadable repo / missing merge target ⇒ [] (unreadable is never a
    violation — same rule as _landed). Retired branches are never in the set:
    they are not `branch_for(any brief)`.
    """
    target = repo.merge_target
    target_tip = git(repo.path, "rev-parse", "--verify", "--quiet", target)
    if target_tip is None:
        return []
    out: list[StaleBaseViolation] = []
    for brief in briefs:
        branch = repo.branch_for(brief)
        branch_tip = git(repo.path, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        if branch_tip is None or _is_ancestor(repo.path, target_tip, branch_tip):
            continue
        behind = git(repo.path, "rev-list", "--count", f"{branch_tip}..{target_tip}")
        if behind is None or not behind.isdigit():
            continue  # unreadable is never a violation
        # Unrelated histories have no merge base; the branch is still not cut from the target.
        merge_base = git(repo.path, "merge-base", target_tip, branch_tip) or ""
        out.append(StaleBaseViolation(repo=repo.name, branch=branch, merge_target=target,
                                      target_tip=target_tip, branch_tip=branch_tip,
                                      merge_base=merge_base, behind=int(behind)))
    return out


# ── ORCH-CONFLICT-1 · the landed invariant (S7-CORE-15) ──────────────────────────────────
# The freshness invariant above is asserted before a route runs; this one is asserted as it
# ends, at the one line every downstream claim is built on (`🏁 FINAL STATUS: passed`):
#
#     a route reported passed has its tip on the merge target, and leaves the repo not mid-merge
#
# L-UI-SAFETY-1 attempt 2 (2026-09-21 02:27:25) passed its gate, conflicted on merge, and still
# printed `FINAL STATUS: passed`. The route tip is supplied by the CALLER, captured as the merge
# was attempted: a good merge deletes the branch, so refs/heads/<branch> cannot be the evidence.
# Ancestry of that tip is also stricter than _landed's subject scan — a previous attempt's
# `Merge branch '<same name>'` cannot answer for this one.


@dataclass(frozen=True)
class UnlandedRouteViolation:
    """A route reported ready to pass whose tip is not on the merge target, or whose repo is mid-merge."""
    repo: str
    branch: str
    merge_target: str
    route_tip: str      # the route branch's tip as the merge was attempted (caller-supplied)
    target_tip: str     # the merge target's tip now
    landed: bool        # git merge-base --is-ancestor <route_tip> <merge_target>
    mid_merge: bool     # MERGE_HEAD resolves in repo.path

    def __str__(self) -> str:
        legs = ([] if self.landed else [f"not on {self.merge_target}"]) + \
               (["repo mid-merge"] if self.mid_merge else [])
        return (f"{self.branch} tip {self.route_tip[:8]} vs {self.merge_target} "
                f"{self.target_tip[:8]}: {', '.join(legs)}")


def check_route_landed_invariants(repo: QueueRepo, brief: str, route_tip: str) -> list[UnlandedRouteViolation]:
    """EMPTY WHEN CLEAN. Clean ⇔ `route_tip` is an ancestor of `repo.merge_target` AND
    `git rev-parse -q --verify MERGE_HEAD` fails in repo.path. The set is exactly ONE route,
    `repo.branch_for(brief)`, named by the caller. Unreadable (no .git, merge target or
    route_tip unresolvable) ⇒ [] — the module's rule, same as _landed and
    check_branch_freshness_invariants."""
    target = repo.merge_target
    target_tip = git(repo.path, "rev-parse", "--verify", "--quiet", target)
    if target_tip is None or not route_tip:
        return []
    tip = git(repo.path, "rev-parse", "--verify", "--quiet", f"{route_tip}^{{commit}}")
    if tip is None:
        return []
    landed = _is_ancestor(repo.path, tip, target_tip)
    mid_merge = git(repo.path, "rev-parse", "-q", "--verify", "MERGE_HEAD") is not None
    if landed and not mid_merge:
        return []
    return [UnlandedRouteViolation(repo=repo.name, branch=repo.branch_for(brief), merge_target=target,
                                   route_tip=tip, target_tip=target_tip, landed=landed,
                                   mid_merge=mid_merge)]


# ── verdict building ─────────────────────────────────────────────────────────────────────
@dataclass
class Verdict:
    id: str
    title: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)

    def render(self) -> str:
        head = f"{self.id} {self.status:<7} {self.title} — {self.summary}"
        return "\n".join([head] + [f"      {d}" for d in self.details])


class Builder:
    def __init__(self, id: str, title: str):
        self.id, self.title = id, title
        self.fails: list[str] = []
        self.unknowns: list[str] = []
        self.passes: list[str] = []
        self.infos: list[str] = []
        self.details: list[str] = []

    @staticmethod
    def _row(label: str, value: str, where: str) -> str:
        return f"{label:<44} {value:<22} ← {where}"

    def ok(self, what: str) -> None:
        self.passes.append(what)

    def fail(self, what: str, *rows: tuple[str, str, str]) -> None:
        self.fails.append(what)
        self.details.append(f"FAIL {self.id}: {what}")
        self.details.extend("  " + self._row(*r) for r in rows)

    def unknown(self, what: str, *rows: tuple[str, str, str]) -> None:
        self.unknowns.append(what)
        self.details.append(f"UNKNOWN {self.id}: {what}")
        self.details.extend("  " + self._row(*r) for r in rows)

    def heading(self, text: str) -> None:
        self.details.append(text)

    def info(self, what: str) -> None:
        """Reported, counted, never a fail — the status and the exit code ignore it."""
        self.infos.append(what)
        self.details.append(f"  INFO {self.id}: {what}")

    def verdict(self) -> Verdict:
        if self.fails:
            st, summ = FAIL, f"{len(self.fails)} mismatch(es)" + (f", {len(self.unknowns)} unknown" if self.unknowns else "")
        elif self.unknowns:
            st, summ = UNKNOWN, "; ".join(self.unknowns)
        elif self.passes:
            st, summ = PASS, "; ".join(self.passes)
        else:
            st, summ = UNKNOWN, "nothing was checked"
        if self.infos:
            summ += f" · {len(self.infos)} INFO (not asserted)"
        return Verdict(self.id, self.title, st, summ, self.details)


def where(p: Pointer) -> str:
    return f"{p.src}  «{p.text}»"


# ── the assertions ───────────────────────────────────────────────────────────────────────
@dataclass
class Ctx:
    canon: Path
    repo_root: Path
    families: list[Family]
    ci: Optional[CanonIndex]
    hot: Optional[Hot]

    def fam(self, key: str) -> Family:
        return next(f for f in self.families if f.key == key)

    def disk(self, key: str) -> DiskFamily:
        return disk_family(self.canon, self.fam(key).stem, key)

    def repo(self, name: str) -> Path:
        return self.repo_root / f"spectricom-{name}"

    def listing(self, key: str) -> str:
        return f"{self.canon.name}/ (newest {self.fam(key).stem}_v*.md in canon root)"


def registry_truth(ctx: Ctx, b: Builder) -> Optional[tuple[Version, str, Version, Src]]:
    """(filename version, filename, H1 version, H1 src) of the newest Registry on disk, or None."""
    d = ctx.disk("Registry")
    if not d.newest:
        b.unknown("no Spectricom_Document_Registry_v*.md in canon root", ("Registry on disk", "—", ctx.listing("Registry")))
        return None
    ver, name = d.newest
    got = h1_version(ctx.canon / name)
    if not got:
        b.unknown(f"{name} has no H1 carrying a vN-M", ("Registry H1", "—", f"{name}:1"))
        return None
    return ver, name, got[0], got[1]


def assert_b1(ctx: Ctx) -> Verdict:
    b = Builder("B1", "Registry family agrees (H1 == filename == hot.md == Canon_Index)")
    truth = registry_truth(ctx, b)
    if ctx.hot is None:
        b.unknown("hot.md missing or unreadable", ("hot.md Canon latest", "—", "hot.md"))
    if ctx.ci is None:
        b.unknown("Canon_Index.md missing, or no frontmatter / `updated:` line", ("Canon_Index frontmatter", "—", "Canon_Index.md"))
    if truth is None or ctx.hot is None or ctx.ci is None:
        return b.verdict()
    fver, fname, hver, hsrc = truth
    rows = [("Registry filename", vstr(fver), ctx.listing("Registry")), ("Registry H1", vstr(hver), str(hsrc))]
    hp = ctx.hot.canon_latest.get("Registry")
    cp = ctx.ci.frontmatter.get("Registry")
    if hp is None:
        b.unknown("hot.md `## Canon latest` names no Registry version", *rows, ("hot.md Canon latest", "not cited", "hot.md"))
    if cp is None:
        b.unknown("Canon_Index `updated:` names no Registry version", *rows, ("Canon_Index frontmatter", "not cited", f"Canon_Index.md:{ctx.ci.updated_line[0]}"))
    if hp is None or cp is None:
        return b.verdict()
    rows += [("hot.md Canon latest", vstr(hp.version), where(hp)), ("Canon_Index frontmatter", vstr(cp.version), where(cp))]
    if len({fver, hver, hp.version, cp.version}) == 1:
        b.ok(f"all four say {vstr(fver)}")
    else:
        b.fail("the four Registry pointers disagree", *rows)
    return b.verdict()


def assert_b2(ctx: Ctx) -> Verdict:
    b = Builder("B2", "Feature Index git-anchor == clinical-mp HEAD")
    d = ctx.disk("Feature Index")
    if not d.newest:
        b.unknown("no SCA_Feature_Index_v*.md in canon root", ("Feature Index on disk", "—", ctx.listing("Feature Index")))
        return b.verdict()
    _, name = d.newest
    lines = read_lines(ctx.canon / name)
    m = ANCHOR_RE.search(lines[0]) if lines else None
    if not m:
        b.unknown(f"{name} line 1 carries no `git-anchor:`", ("git-anchor", "—", f"{name}:1"))
        return b.verdict()
    anchor = m.group(1)
    repo = ctx.repo("clinical-mp")
    head = git_head(repo)
    git_where = f"git -C {repo} rev-parse HEAD (branch {git_branch(repo)})"
    if head is None:
        b.unknown("clinical-mp repo missing or not a git repo", ("git-anchor", anchor, f"{name}:1"), ("HEAD", "—", git_where))
        return b.verdict()
    rows = [("git-anchor", anchor, f"{name}:1"), ("HEAD", head[:7], git_where)]
    if head.startswith(anchor):
        b.ok(f"anchor {anchor} == HEAD")
    else:
        b.fail("anchor is not HEAD", *rows)
    return b.verdict()


def session_key(sid: str) -> tuple[str, Optional[int]]:
    m = re.match(r"^(.*?)(\d+)$", sid)
    return (m.group(1), int(m.group(2))) if m else (sid, None)


def assert_b3(ctx: Ctx) -> Verdict:
    b = Builder("B3", "Canon_Index is not lagging (updated: session, and its Registry pointer)")
    if ctx.ci is None:
        b.unknown("Canon_Index.md missing, or no frontmatter / `updated:` line", ("Canon_Index frontmatter", "—", "Canon_Index.md"))
        return b.verdict()
    if ctx.hot is None or ctx.hot.h1 is None:
        b.unknown("hot.md missing or has no H1", ("hot.md H1", "—", "hot.md:1"))
        return b.verdict()
    ln, upd = ctx.ci.updated_line
    first_segment = re.split(r"\s·\s*prior:", upd)[0]
    ci_sid = SESSION_RE.search(first_segment)
    hot_sid = SESSION_RE.search(ctx.hot.h1[1])
    ci_where, hot_where = f"Canon_Index.md:{ln}  «{first_segment[:70]}…»", f"hot.md:{ctx.hot.h1[0]}  «{ctx.hot.h1[1][:70]}»"
    if not ci_sid:
        b.unknown("`updated:` first segment names no session id", ("Canon_Index updated:", "no session id", ci_where))
    if not hot_sid:
        b.unknown("hot.md H1 names no session id", ("hot.md H1", "no session id", hot_where))
    if ci_sid and hot_sid:
        c, h = ci_sid.group(0), hot_sid.group(0)
        ct, cn = session_key(c)
        ht, hn = session_key(h)
        if c == h or (ct == ht and cn is not None and hn is not None and cn == hn + 1):
            b.ok(f"updated: names {c} (hot.md: {h})")
        else:
            b.fail("`updated:` names a session that is not hot.md's session or its successor",
                   ("Canon_Index updated:", c, ci_where), ("hot.md H1", h, hot_where))
    truth = registry_truth(ctx, b)
    cp = ctx.ci.frontmatter.get("Registry")
    if truth and cp is None:
        b.unknown("`updated:` names no Registry version", ("Canon_Index frontmatter", "not cited", f"Canon_Index.md:{ln}"))
    elif truth and cp:
        _, name, hver, hsrc = truth
        if cp.version == hver:
            b.ok(f"frontmatter Registry {vstr(hver)} == Registry H1")
        else:
            b.fail("frontmatter Registry pointer != Registry H1", ("Canon_Index frontmatter", vstr(cp.version), where(cp)), ("Registry H1", vstr(hver), str(hsrc)))
    return b.verdict()


def assert_b4(ctx: Ctx) -> Verdict:
    b = Builder("B4", "Coverage Matrix and Bug Registry H1 == Canon_Index pointer bullet")
    if ctx.ci is None:
        b.unknown("Canon_Index.md missing, or no frontmatter / `updated:` line", ("Canon_Index bullets", "—", "Canon_Index.md"))
        return b.verdict()
    if not ctx.ci.has_bullets:
        b.unknown("Canon_Index preamble has no pointer bullets", ("Canon_Index bullets", "—", "Canon_Index.md (preamble)"))
        return b.verdict()
    for key in ("Coverage Matrix", "Bug Registry"):
        d = ctx.disk(key)
        if not d.newest:
            b.unknown(f"no {ctx.fam(key).stem}_v*.md in canon root", (f"{key} on disk", "—", ctx.listing(key)))
            continue
        _, name = d.newest
        got = h1_version(ctx.canon / name)
        if not got:
            b.unknown(f"{name} has no H1 carrying a vN-M", (f"{key} H1", "—", f"{name}:1"))
            continue
        hver, hsrc, _ = got
        bp = ctx.ci.bullets.get(key)
        if bp is None:
            b.fail(f"{key}: no pointer bullet names it", (f"{key} H1", vstr(hver), str(hsrc)), ("Canon_Index bullet", "not cited", "Canon_Index.md (preamble bullets)"))
        elif bp.version == hver:
            b.ok(f"{key} {vstr(hver)}")
        else:
            b.fail(f"{key}: H1 != pointer bullet", (f"{key} H1", vstr(hver), str(hsrc)), ("Canon_Index bullet", vstr(bp.version), where(bp)))
    return b.verdict()


def assert_b5(ctx: Ctx) -> Verdict:
    b = Builder("B5", "hot.md repo table (HEAD, unpushed) == git live, per repo")
    if ctx.hot is None:
        b.unknown("hot.md missing or unreadable", ("hot.md repo table", "—", "hot.md"))
        return b.verdict()
    if not ctx.hot.repos:
        b.unknown("hot.md has no repo table rows", ("hot.md repo table", "—", "hot.md"))
        return b.verdict()
    for ln, name, sha, unpushed in ctx.hot.repos:
        repo = ctx.repo(name)
        head, live_un = git_head(repo), git_unpushed(repo)
        hot_where = f"hot.md:{ln}"
        git_where = f"git -C {repo} (branch {git_branch(repo)})"
        if head is None:
            b.unknown(f"{name}: repo missing or not a git repo", (f"{name} hot.md", f"{sha} / {unpushed} unpushed", hot_where), (f"{name} git", "—", git_where))
            continue
        if live_un is None:
            b.unknown(f"{name}: no origin/main or upstream to count unpushed against", (f"{name} hot.md", f"{sha} / {unpushed} unpushed", hot_where), (f"{name} git", f"{head[:7]} / ? unpushed", git_where))
            continue
        rows = [(f"{name} hot.md", f"{sha} / {unpushed} unpushed", hot_where), (f"{name} git", f"{head[:7]} / {live_un} unpushed", git_where)]
        if head.startswith(sha) and live_un == unpushed:
            b.ok(f"{name} {sha}/{unpushed}")
        else:
            b.fail(f"{name}: hot.md != git", *rows)
    return b.verdict()


def assert_b6(ctx: Ctx) -> Verdict:
    b = Builder("B6", "Canon_Index frontmatter, blockquote and bullet pointer sets agree (newest block only)")
    if ctx.ci is None:
        b.unknown("Canon_Index.md missing, or no frontmatter / `updated:` line", ("Canon_Index", "—", "Canon_Index.md"))
        return b.verdict()
    if not ctx.ci.has_blockquotes:
        b.unknown("Canon_Index preamble has no `> Canon latest` blockquote", ("Canon_Index blockquotes", "—", "Canon_Index.md (preamble)"))
    if not ctx.ci.has_bullets:
        b.unknown("Canon_Index preamble has no pointer bullets", ("Canon_Index bullets", "—", "Canon_Index.md (preamble)"))
    if not ctx.ci.window:
        b.unknown("`updated:` first segment names no session id — the newest block cannot be identified",
                  ("Canon_Index updated:", "no session id", f"Canon_Index.md:{ctx.ci.updated_line[0]}"))
    if b.unknowns:
        return b.verdict()
    win = " + prior ".join(ctx.ci.window)
    # The body must carry the newest block at all: a frontmatter written for a session whose
    # bullet / blockquote was never written is the S7-CORE-11 mechanism, and it is a FAIL.
    for label, key in (("body bullet", "bullet"), ("body blockquote", "blockquote")):
        if not ctx.ci.newest_lines[key]:
            seen = ctx.ci.body_sessions[key]
            b.fail(f"{label}: no block for the newest session(s) {win} — the body was not written",
                   ("Canon_Index updated: session", win, f"Canon_Index.md:{ctx.ci.updated_line[0]}"),
                   (f"{label} sessions present", ", ".join(dict.fromkeys(seen)) or "none", "Canon_Index.md (preamble)"))
    if b.fails:
        return b.verdict()
    sources = [("frontmatter updated:", ctx.ci.newest_frontmatter),
               ("body blockquote", ctx.ci.newest_blockquotes),
               ("body bullet", ctx.ci.newest_bullets)]
    compared = 0
    for fam in ctx.families:
        present = [(label, s[fam.key]) for label, s in sources if fam.key in s]
        if len(present) < 2:
            continue
        compared += 1
        if len({p.version for _, p in present}) == 1:
            continue
        b.fail(f"{fam.key}: the pointer sets inside Canon_Index disagree",
               *[(f"{fam.key} · {label}", vstr(p.version, p.draft), where(p)) for label, p in present])
    read = ", ".join(f"{k} {'/'.join(map(str, v))}" for k, v in ctx.ci.newest_lines.items())
    if compared == 0:
        b.unknown(f"newest block ({win}) names no family in two or more of the three pointer sets", ("Canon_Index", "—", f"Canon_Index.md lines {read}"))
    elif not b.fails:
        b.ok(f"newest block = {win} (Canon_Index.md:{ctx.ci.updated_line[0]} + {read}); {compared} families agree across the sets that name them")
    return b.verdict()


def assert_b7(ctx: Ctx) -> Verdict:
    b = Builder("B7", "Kanban, SDLC families, Roadmap, Codex: disk newest == hot.md == Canon_Index")
    keys = ["Kanban"] + [f.key for f in ctx.families if f.key.startswith("SDLC ")] + ["Roadmap", "Codex"]
    if not any(k.startswith("SDLC ") for k in keys):
        b.unknown("no SCP_SDLC_Decomposition_*_v*.md in canon root — no SDLC family to assert", ("SDLC on disk", "—", str(ctx.canon)))
    if ctx.hot is None:
        b.unknown("hot.md missing or unreadable", ("hot.md Canon latest", "—", "hot.md"))
    if ctx.ci is None:
        b.unknown("Canon_Index.md missing, or no frontmatter / `updated:` line", ("Canon_Index", "—", "Canon_Index.md"))
    if ctx.hot is None or ctx.ci is None:
        return b.verdict()
    union = ctx.ci.union
    for key in keys:
        d = ctx.disk(key)
        if not d.newest:
            b.unknown(f"{key}: no {ctx.fam(key).stem}_v*.md in canon root", (f"{key} on disk", "—", ctx.listing(key)))
            continue
        dver, dname = d.newest
        hp, cp = ctx.hot.canon_latest.get(key), union.get(key)
        rows = [(f"{key} on disk", vstr(dver), f"{dname}  ({ctx.listing(key)})"),
                (f"{key} hot.md", vstr(hp.version, hp.draft) if hp else "not cited", where(hp) if hp else "hot.md (## Canon latest)"),
                (f"{key} Canon_Index", vstr(cp.version, cp.draft) if cp else "not cited", where(cp) if cp else "Canon_Index.md (frontmatter + preamble)")]
        if hp and cp and hp.version == dver == cp.version:
            b.ok(f"{key} {vstr(dver)}")
        else:
            b.fail(f"{key}: disk / hot.md / Canon_Index disagree", *rows)
    return b.verdict()


def root_families(canon: Path) -> dict[str, list[tuple[Version, str]]]:
    fams: dict[str, list[tuple[Version, str]]] = {}
    for name in list_root(canon):
        m = FILE_RE.match(name)
        if not m or NOT_A_MEMBER_RE.search(name):
            continue
        suffix = re.sub(r"[-_]DRAFT", "", m["suffix"] or "")
        fams.setdefault(m["stem"] + suffix, []).append(((int(m["maj"]), int(m["min"])), name))
    return fams


def assert_b8(ctx: Ctx) -> Verdict:
    b = Builder("B8", "Old/ sweep — exactly one member of each Core brief-set family in the canon root")
    fams = root_families(ctx.canon)
    if not fams:
        b.unknown("no versioned *_vN-M.md file in canon root", ("canon root", "—", str(ctx.canon)))
        return b.verdict()
    core = core_brief_set(ctx.families)
    core_keys = [k for k in sorted(fams) if is_core(k, core)]
    stale_core = {k: sorted(fams[k]) for k in core_keys if len(fams[k]) > 1}
    stale_other = {k: sorted(fams[k]) for k in sorted(fams) if k not in core_keys and len(fams[k]) > 1}
    for key, members in stale_core.items():
        newest = members[-1][1]
        preds = [n for _, n in members[:-1]]
        shown = ", ".join(preds[:4]) + (f", … and {len(preds) - 4} more" if len(preds) > 4 else "")
        b.fail(f"{key}: {len(members)} members in canon root", (f"{key} newest", newest, str(ctx.canon)), (f"{key} predecessors", f"{len(preds)} surviving", shown))
    if stale_other:
        b.heading(f"INFO B8 — not in the Core brief set, reported not asserted "
                  f"({len(stale_other)} of {len(fams) - len(core_keys)} non-Core families have predecessors in the canon root):")
        for key, members in stale_other.items():
            b.info(f"{key}: {len(members)} members in canon root (newest {members[-1][1]})")
    if not b.fails:
        b.ok(f"{len(core_keys)} Core brief-set families in the canon root, one member each")
    return b.verdict()


def assert_b9(ctx: Ctx) -> Verdict:
    b = Builder("B9", "no .bak and no *_DRAFT_GEMMA* residue in the canon root")
    names = list_root(ctx.canon)
    if not names:
        b.unknown("canon root is empty or unreadable", ("canon root", "—", str(ctx.canon)))
        return b.verdict()
    for name in names:
        if BAK_RE.search(name):
            b.fail(f"{name}: .bak residue", ("file", name, str(ctx.canon)), ("rule", "final extension ends in bak", "B9"))
        elif GEMMA_RE.search(name):
            b.fail(f"{name}: _DRAFT_GEMMA residue", ("file", name, str(ctx.canon)), ("rule", "_DRAFT_GEMMA in name", "B9"))
    if not b.fails:
        b.ok(f"{len(names)} root files, no residue (plain _DRAFT is legitimate)")
    return b.verdict()


ASSERTIONS = {"B1": assert_b1, "B2": assert_b2, "B3": assert_b3, "B4": assert_b4, "B5": assert_b5,
              "B6": assert_b6, "B7": assert_b7, "B8": assert_b8, "B9": assert_b9}


def run(canon: Path, repo_root: Path, only: Optional[Iterable[str]] = None) -> list[Verdict]:
    families = all_families(canon)
    ctx = Ctx(canon=canon, repo_root=repo_root, families=families,
              ci=parse_canon_index(canon, families), hot=parse_hot(canon, families))
    ids = [i for i in ASSERTION_IDS if only is None or i in set(only)]
    return [ASSERTIONS[i](ctx) for i in ids]


def summarize(verdicts: list[Verdict]) -> tuple[str, int]:
    n = {s: sum(1 for v in verdicts if v.status == s) for s in (PASS, FAIL, UNKNOWN)}
    line = f"SUMMARY {len(verdicts)} assertions: {n[PASS]} PASS · {n[FAIL]} FAIL · {n[UNKNOWN]} UNKNOWN"
    return line, 0 if n[FAIL] == 0 and n[UNKNOWN] == 0 and verdicts else 1


def render(verdicts: list[Verdict], canon: Path, repo_root: Path) -> tuple[str, int]:
    out = [f"CANON ASSERT — {canon} · repos under {repo_root} · disk+git only"]
    out += [v.render() for v in verdicts]
    line, code = summarize(verdicts)
    out.append(line)
    return "\n".join(out), code


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--canon", type=Path, default=None, help="canon folder (default: CANON= in doc-sweep.sh)")
    ap.add_argument("--repo-root", type=Path, default=Path.home(), help="directory holding spectricom-<repo> checkouts (default: ~)")
    ap.add_argument("--only", default=None, help="comma-separated assertion ids, e.g. B1,B6")
    a = ap.parse_args(argv)
    canon = a.canon or default_canon_dir()
    if canon is None:
        print(f"UNKNOWN: no --canon given and no CANON= line in {DOC_SWEEP}", file=sys.stderr)
        return 2
    only = [s.strip().upper() for s in a.only.split(",")] if a.only else None
    text, code = render(run(canon, a.repo_root, only), canon, a.repo_root)
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
