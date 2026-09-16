# BOOT-ASSERT-2b — calibrate B6 and B8 against the live canon folder

**Repo:** orchestrator · **Base:** `main` `03d0dff` · **Session:** S7-CORE-11 (2026-09-16)
**Predecessor:** BOOT-ASSERT-2 `03d0dff` — `canon_assert.py`, B1–B9, 357 pytest green.

## Estimated runtime: 45–75 min

## Micro-fire trigger: P0 infra — the boot assert is the control every session briefs from, and two
of its nine assertions currently report drift that is not drift. An assert nobody trusts is an
assert nobody runs, and `[BOOT-ASSERT-1]` was open for three sessions precisely because the
previous one was believed to cover more than it did.

## Executor
`claude-fable-5-1 --effort high` (`D-S7CORE10-01`). Same executor as the route that built it,
because both findings are about **which text in a hand-written markdown file is authoritative** —
the same judgement call the original route made well.

**Run every command in the FOREGROUND and wait.**

---

## 0 · FIRST STEP — reproduce both findings before changing anything

```
cd ~/spectricom-orchestrator
python3 canon_assert.py > /tmp/before.txt 2>&1; echo "exit=$?"
grep -E "^B[0-9] " /tmp/before.txt
```

Expected at the time of writing (Gemma's own run, 2026-09-16 12:1x ET): exit **1**,
`SUMMARY 9 assertions: 3 PASS · 6 FAIL · 0 UNKNOWN`. **Keep `/tmp/before.txt`** — the report must
diff against it so the effect of this route is visible rather than asserted.

---

## 1 · Finding 1 — B6 reads history as if it were current

`Canon_Index.md` is **append-only**: every session prepends a pointer bullet and a
`> **Canon latest …**` blockquote, and the older ones stay forever as history. B6 compares *every*
blockquote and bullet it finds against the frontmatter, so it reports drift that is simply the past.

Observed, verbatim:

```
FAIL B6: SDLC L Batch1: the pointer sets inside Canon_Index disagree
  SDLC L Batch1 · body blockquote   v0-3    ← Canon_Index.md:35
  SDLC L Batch1 · body bullet       v0-10   ← Canon_Index.md:23
```

Line 35 is the **S7-CORE-3** blockquote. v0-3 was correct *then*. The current value is v0-10 and
both the bullet and the disk agree on it.

**The fix:** B6 reads the **newest block only** — the first pointer bullet and the first
`> **Canon latest …**` blockquote below the frontmatter close, and the frontmatter's own `updated:`
value, and compares those three. This is not a new convention: *"Ledgers — read the newest block
only"* is already the standing instruction in the session-boot invocation.

**Do not** solve this by loosening B6 into "any block may match." That converts a real assert into
one that cannot fail, which is the failure mode this whole family exists to end.

## 2 · Finding 2 — B8's scope is wider than the thing being asserted

B8 reports **78** mismatches. Many are real Spectricom Core residue. But the canon folder is shared,
and these are other products' or other eras' families:

```
FAIL B8: yorsie-bug-registry: 8 members in canon root
FAIL B8: spectricom-layout-canon: 2 members in canon root
FAIL B8: spectricom-interaction-canon: 2 members in canon root
FAIL B8: toni-brief-spec-overview-001-journey-of-a-heartbeat: 2 members in canon root
```

`SESSION-BOOT.md` already states the honest scope of this assert: *"the pointers a session briefs
from, not canon."*

**The fix:** B8 partitions its output. Families **in the Core brief set** (Registry, PCU, Logs,
Master Plan, Kanban, Codex, Feature Index, Coverage Matrix, Bug Registry, Roadmap, the SDLC
families, the two context slims, EOS Protocol) are **FAIL**. Everything else in the folder is
reported under a separate heading as **INFO**, counted separately, and **does not fail the run**.

Derive the Core set from **one named constant in one place**, and make it the same list B7 already
walks where they overlap. Two hard-coded lists that must agree is a third drift to maintain.

⚠ **Do not delete or move any file in the canon folder.** Not the `.bak` residue B9 names, not a
predecessor B8 names. Canon is George's and Gemma's to write — `AC-BA2-08` from the predecessor
brief still stands and this route does not relax it.

## 3 · Out of scope

B1, B2, B3, B4, B5, B7 and **B9** are correct as built and are **not** touched. B9's nine hits are
genuine residue awaiting a human sweep; leaving them failing is the assert working. `orchestrator.py`
is not touched. `doc-sweep.sh` is not touched.

## 4 · Acceptance criteria

- **AC-BA2b-01** — B6 compares exactly three sources: the frontmatter `updated:` line, the **first**
  pointer bullet below the frontmatter close, and the **first** `> **Canon latest …**` blockquote.
  A test over a fixture whose **older** blocks disagree with the newest — which is the normal,
  correct state of this file — passes B6.
- **AC-BA2b-02** — a test over a fixture whose **newest** block disagrees with the frontmatter still
  **FAILS** B6, naming both values and their lines. **Prove this red before trusting the green**;
  paste the failing output. B6 that cannot fail is worse than no B6.
- **AC-BA2b-03** — B8 fails only on families in the Core brief set; every other family is reported
  as **INFO** under its own heading with its own count, and an INFO does not change the exit code.
  A test asserts a fixture containing only a stale non-Core family exits **0**.
- **AC-BA2b-04** — a test asserts a fixture with a stale **Core** family (two Kanban versions in
  root) still exits non-zero and names B8.
- **AC-BA2b-05** — the Core family set is defined **once**, in one named constant. `grep` shows no
  second literal list of those family names in `canon_assert.py`; paste the grep.
- **AC-BA2b-06** — B1–B5, B7 and B9 produce **byte-identical verdict lines** against the live canon
  folder before and after. `diff` the `^B[0-9] ` lines of `/tmp/before.txt` and the new run for those
  seven ids and paste the diff — it must be empty except for B6's and B8's own lines.
- **AC-BA2b-07** — `python3 -m pytest tests -q` passes with no new failures versus the baseline you
  take at the start. Baseline at `03d0dff` is **357 passed, 0 failed**; state both numbers.
- **AC-BA2b-08** — the live run is reported verbatim, whatever it says, and **no file in the canon
  folder is created, modified, moved or deleted by this route**. State that explicitly.

## 5 · Halt and report

Halt if: the "newest block" cannot be identified unambiguously from the real file's structure; the
Core family set cannot be derived without a list that will rot; or B6's fix would make it unable to
fail. Name what you found and where you looked.

## 6 · Return

Commit on the route branch. Self-modifying repo route: the orchestrator gates before merging and
correctly withholds the merge on a red. Every gate runs; none is to be bypassed or suppressed by
any flag.

Report, in this order: the §0 before-run verdict lines · the AC-BA2b-02 red proof · the AC-BA2b-06
empty diff · the AC-BA2b-05 grep · the new live run verbatim · pytest before/after · `git diff
--stat` · the explicit statement that canon was not touched.
