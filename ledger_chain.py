"""ORCH-LEDGER-CHAIN-1 (route 623; RM-OPS-04-F-02 US-01; T-OPX-04; C-OPX05) — the append-only control ledger.

Every merge, gate verdict, hold, kill, unkill, verdict override and merge-hold release appends one JSON line to
`logs/ledger.jsonl`. Each line carries `seq` (1, 2, 3, ...), `prev` (the previous line's `hash`, GENESIS for the first)
and `hash` = sha256 of the line's own canonical JSON without `hash`. `logs/ledger.head.json` names the last
`seq` and `hash` written, so a deleted tail is caught too. `scripts/ledger-verify.py` fails on any edit, deletion or
reorder (OC-8, D-S7CORE51-26: JSON Lines + sha256, the standard format Part AGT adopts).

Writers are the orchestrator (a fresh process per route) and the queue daemon, so an append holds an exclusive
`flock` on the ledger file for its read-tail / write / fsync / head-update. An append never raises: a ledger that
cannot be written returns None and the caller logs it; a route's outcome never depends on the ledger (OPEN (b)).

Not here (US-02, OC-9, D-S7CORE51-27): the off-host copy owned by a separate Linux user — George's one-time setup.
Until then a writer with the orchestrator's own rights can rewrite the whole file and its head consistently; the
chain catches every partial edit, not a full rewrite.
"""
import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LEDGER_VERSION = 1
GENESIS = "0" * 64
LEDGER_NAME = "ledger.jsonl"
HEAD_NAME = "ledger.head.json"
DIR_ENV = "SPECTRICOM_LEDGER_DIR"   # tests (tests/conftest.py) and a sandbox point it elsewhere
KINDS = ("gate", "hold", "merge", "kill", "unkill", "override", "release-hold")
RESERVED = ("v", "seq", "ts", "kind", "prev", "hash")
_TAIL_BYTES = 65536


def ledger_dir(default: Optional[Path] = None) -> Path:
    """$SPECTRICOM_LEDGER_DIR when set (tests/conftest.py sets it for every test), else the caller's log dir
    (orchestrator.LOG_DIR / queue_daemon.LOG_DIR — so a sandbox that moves LOG_DIR moves the ledger with it), else
    this file's logs/."""
    env = os.environ.get(DIR_ENV)
    if env:
        return Path(env)
    return Path(default) if default is not None else Path(__file__).resolve().parent / "logs"


def ledger_path(d: Optional[Path] = None) -> Path:
    return (d or ledger_dir()) / LEDGER_NAME


def head_path(d: Optional[Path] = None) -> Path:
    return (d or ledger_dir()) / HEAD_NAME


def canonical(rec: dict) -> str:
    return json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_hash(rec: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in rec.items() if k != "hash"}).encode("utf-8")).hexdigest()


def _last_record(f) -> Optional[dict]:
    f.seek(0, os.SEEK_END)
    size = f.tell()
    if size == 0:
        return None
    f.seek(max(0, size - _TAIL_BYTES))
    lines = [l for l in f.read().splitlines() if l.strip()]
    if not lines:
        return None
    return json.loads(lines[-1])


def _write_head(d: Path, rec: dict) -> None:
    tmp = head_path(d).with_suffix(".tmp")
    tmp.write_text(json.dumps({"seq": rec["seq"], "hash": rec["hash"], "ts": rec["ts"]}) + "\n", encoding="utf-8")
    os.replace(tmp, head_path(d))


def append(kind: str, d: Optional[Path] = None, **fields) -> Optional[dict]:
    """Append one record; the record as written, or None when it could not be written (never raises on I/O).
    An unknown kind or a reserved field name is a programming error and raises ValueError."""
    if kind not in KINDS:
        raise ValueError(f"ledger: unknown kind {kind!r} (one of {', '.join(KINDS)})")
    clash = sorted(set(fields) & set(RESERVED))
    if clash:
        raise ValueError(f"ledger: reserved field name(s) {', '.join(clash)}")
    body = json.loads(json.dumps(fields, default=str))   # what is hashed is exactly what is stored
    d = d or ledger_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        with open(ledger_path(d), "a+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                last = _last_record(f)
            except ValueError:
                last = {"seq": None, "hash": "unreadable-tail"}   # still appended; verify names the break
            seq = (last.get("seq") or 0) + 1 if last else 1
            rec = {"v": LEDGER_VERSION, "seq": seq, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "kind": kind, **body, "prev": last.get("hash", GENESIS) if last else GENESIS}
            rec["hash"] = record_hash(rec)
            f.seek(0, os.SEEK_END)
            f.write(canonical(rec) + "\n")
            f.flush()
            os.fsync(f.fileno())
            _write_head(d, rec)
            return rec
    except OSError:
        return None


def verify(d: Optional[Path] = None) -> tuple:
    """(records, problems). No problems = the chain is whole from GENESIS to the head anchor."""
    d = d or ledger_dir()
    p, h = ledger_path(d), head_path(d)
    problems, prev, n, last = [], GENESIS, 0, None
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    for i, line in enumerate(lines, start=1):
        try:
            rec = json.loads(line)
        except ValueError:
            problems.append(f"line {i}: not JSON")
            prev = None
            continue
        if not isinstance(rec, dict):
            problems.append(f"line {i}: not a JSON object")
            prev = None
            continue
        n += 1
        if canonical(rec) != line:
            problems.append(f"line {i}: not in canonical form (edited by hand?)")
        if rec.get("v") != LEDGER_VERSION:
            problems.append(f"line {i}: version {rec.get('v')!r}, expected {LEDGER_VERSION}")
        if rec.get("seq") != i:
            problems.append(f"line {i}: seq {rec.get('seq')!r}, expected {i} (a line deleted, inserted or reordered)")
        if rec.get("kind") not in KINDS:
            problems.append(f"line {i}: unknown kind {rec.get('kind')!r}")
        if prev is not None and rec.get("prev") != prev:
            problems.append(f"line {i}: prev does not match line {i - 1}'s hash (the chain is broken here)")
        if rec.get("hash") != record_hash(rec):
            problems.append(f"line {i}: hash does not match its content (edited)")
        prev, last = rec.get("hash"), rec
    if h.exists():
        try:
            head = json.loads(h.read_text(encoding="utf-8"))
        except ValueError:
            problems.append(f"{h.name}: not JSON")
        else:
            if last is None:
                problems.append(f"{h.name} names seq {head.get('seq')} but {p.name} has no records (deleted)")
            elif (head.get("seq"), head.get("hash")) != (last.get("seq"), last.get("hash")):
                problems.append(f"{h.name} names seq {head.get('seq')} {str(head.get('hash'))[:12]}, the last line is "
                                f"seq {last.get('seq')} {str(last.get('hash'))[:12]} (the tail was cut or rewritten)")
    elif lines:
        problems.append(f"{h.name} is missing while {p.name} has {len(lines)} line(s)")
    return n, problems
