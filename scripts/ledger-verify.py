#!/usr/bin/env python3
"""ORCH-LEDGER-CHAIN-1 (route 623): verify logs/ledger.jsonl's sha256 chain and its head anchor.

  python3 scripts/ledger-verify.py [--dir <ledger dir>]

Exit 0: `LEDGER OK — N record(s)` (an absent ledger is 0 records, OK). Exit 1: one line per problem (an edit, a
deletion, an insertion, a reorder, a cut tail). Exit 2: usage.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_chain  # noqa: E402


def main(argv: list) -> int:
    d = None
    if argv:
        if len(argv) != 2 or argv[0] != "--dir":
            print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
            return 2
        d = Path(argv[1])
    n, problems = ledger_chain.verify(d)
    where = ledger_chain.ledger_path(d)
    if problems:
        print(f"LEDGER BROKEN — {where}: {len(problems)} problem(s) in {n} record(s)")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"LEDGER OK — {n} record(s) in {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
