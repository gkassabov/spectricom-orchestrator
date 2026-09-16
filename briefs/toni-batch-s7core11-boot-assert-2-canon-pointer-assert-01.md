# BOOT-ASSERT-2 — make the boot assert a program, and extend it past the Registry family

**Repo:** orchestrator · **Base:** `main` `79bfea3` · **Session:** S7-CORE-11 (2026-09-16)
**Closes:** `[BOOT-ASSERT-1]`, open since S7-CORE-8 and named in `SESSION-BOOT.md` as
*"the standing hole"*.

## Estimated runtime: 75–120 min

## Executor
`claude-fable-5-1 --effort high` (`D-S7CORE10-01`). Chosen for this route specifically because the
hard part is **deciding what a pointer set even is** across nine differently-shaped markdown files
written by hand over two weeks — a parsing-and-judgement problem where the wrong call produces an
assert that is green and blind, which is the exact failure this route exists to end.

**Run every command in the FOREGROUND and wait.** No background runs; there is no callback.

---

## 0 · FIRST STEP — read the assert as it exists, and the three drifts it did not catch

```
grep -n "BOOT ASSERT v2" -A 24 /mnt/c/Users/gkass/OneDrive/Documents/Spectricom/SESSION-BOOT.md
head -30 ~/spectricom-orchestrator/doc-sweep.sh
```

The assert is **B1–B5, executed by a human reading files.** It has never been code. `doc-sweep.sh`
is the nearest existing thing — same canon path, same "decide from disk and git, never from
memory" principle — and it is the shape to follow.

**The three drifts it has been blind to, recorded so the extension is aimed rather than guessed:**

1. **S7-CORE-7:** `Canon_Index.md` lagged **four sessions**.
2. **S7-CORE-8 and S7-CORE-10:** the Coverage Matrix and Bug Registry pointers drifted; B4 was
   added for exactly this and fired twice.
3. **S7-CORE-11 (today, and this is the new one):** `Canon_Index.md` carries **two independent
   pointer sets** — a `updated:` line inside the YAML frontmatter, and a `> **Canon latest …**`
   blockquote plus a pointer bullet in the body. The S7-CORE-10 EOS wrote the frontmatter and
   **not the body**, so B3 read a correct pointer set while B4 read a stale one, **in the same
   file**. Third consecutive session of a Canon_Index mismatch, and the first time the mechanism
   was named. **B6 below exists because of this.**

---

## 1 · What to build

A module `canon_assert.py` in the orchestrator repo, plus a CLI entry point, that runs every
assertion from **disk and git only** and prints a verdict per line. `CANON` is
`/mnt/c/Users/gkass/OneDrive/Documents/Spectricom`, as `doc-sweep.sh` already hard-codes it —
reuse that constant's value, do not invent a second source for the path.

**Port B1–B5 as they stand, then add B6–B9:**

| # | Assertion |
|---|---|
| **B1** | Registry family agrees: Registry H1 == Registry filename == `hot.md` "Canon latest" == `Canon_Index` pointer |
| **B2** | `SCA_Feature_Index_v*.md` line 1 `git-anchor:` == `git -C ~/spectricom-clinical-mp rev-parse --short HEAD` |
| **B3** | `Canon_Index` `updated:` frontmatter names the latest session id, and its pointer set matches B1's Registry version |
| **B4** | Coverage Matrix and Bug Registry H1 versions match the `Canon_Index` pointer bullet |
| **B5** | `hot.md`'s repo table HEAD and unpushed counts match `git` live, per repo |
| **B6** | **NEW — `Canon_Index`'s frontmatter pointer set and its body pointer set agree with each other.** Every family named in both must carry the same version in both. This is the S7-CORE-11 mechanism |
| **B7** | **NEW — the unasserted pointer-bearing families**: `SCP_Kanban_v*`, every `SCP_SDLC_Decomposition_*_v*` family, the Roadmap slice `Spectricom_Product_Roadmap_v*_DRAFT`, and `George_Decision_Codex_v*`. For each: newest file on disk == the version `hot.md` cites == the version `Canon_Index` cites |
| **B8** | **NEW — the `Old/` sweep**: for every versioned canon family, **exactly one** member sits in the canon root. A surviving predecessor beside its successor is a mismatch, because it is what makes `latest()` and a human disagree |
| **B9** | **NEW — no `.bak` and no `*_DRAFT_GEMMA*` file is left in the canon root.** They are staging residue; `_DRAFT` alone is legitimate (the Roadmap ships as a DRAFT) and must NOT be flagged |

## 2 · The part that decides whether this is worth anything

**Every assertion must be shown to FAIL before it is trusted to pass.** A guard only ever seen
green is not known to be a guard — this repo learned that at `9a656fc` and again last night.

Build a **fixture canon directory** under `tests/fixtures/canon/` — a handful of small markdown
files with the real shapes, not the real content — and for **each of B1–B9** write a pair of tests:
one over a consistent fixture that passes, one over a fixture carrying exactly that drift, which
must fail **with that assertion's own name in the message**. Nine pairs, eighteen tests minimum.

**Point the assert at the fixtures first, prove the reds, and only then point it at the real canon
folder.** Say in your report which order you did it in.

## 3 · Output contract

- Exit **0** when every assertion passes, **non-zero** when any fails.
- Print one line per assertion: its id, `PASS` / `FAIL`, and on failure **both values it compared
  and where each was read from** (file and line). A failure a human cannot act on without
  re-deriving it is the failure mode this repo has paid for repeatedly — see `[ORCH-8]`'s
  `failures_source`, which exists for the same reason.
- **A file that cannot be parsed is `UNKNOWN`, never `PASS`.** An assert that goes green because it
  found nothing to check is worse than no assert.
- Verdicts print in id order and the summary states how many were `PASS` / `FAIL` / `UNKNOWN`, so
  the counts reconcile against the line count by inspection.

## 4 · Scope guard — READ THIS

**This route does not touch `orchestrator.py`.** Not the gate lane, not the fire lane, not the
merge lane. It adds a new module, a CLI entry and tests. If you believe you need to change
`orchestrator.py`, **halt and report** — you have found something the brief did not anticipate.

⚠ **`tests/test_unit_baseline_gate.py` contains two guards that diff `main..HEAD` / `main...HEAD`**
— at the `no-scheduling-knob` check (~line 611) and the `config/repos.yaml` check (~line 1031). A
third guard of that shape sprang on `[SIT-RATE-1]` last night and cost it a route; it was repaired
at `79bfea3` by pinning it to a fixed commit range and excluding comment-only lines. **These two
are NOT your work and you must not sweep them.** They are named here only so that, if one of them
fires against *your* branch, you recognise it immediately as `[ORCH-2b]` a fourth time — and in
that case: fix that one assertion minimally, name it in the report, and carry on. Do not treat it
as a reason to redesign anything.

## 5 · Acceptance criteria

- **AC-BA2-01** — `canon_assert.py` exists with a CLI entry; running it against the real canon
  folder prints nine verdict lines and a reconciling summary.
- **AC-BA2-02** — over **all nine** assertions B1–B9, a fixture pair exists: one passing, one
  failing with that assertion's id in the failure text. Paste the failing run's output.
- **AC-BA2-03** — the failure message for every assertion names **both compared values and the
  file each was read from**. Demonstrate on at least B6 and B7, the two with more than one source.
- **AC-BA2-04** — an unparseable or missing file yields `UNKNOWN`, and `UNKNOWN` is **not** counted
  as a pass. A test asserts a missing file does not produce a green run.
- **AC-BA2-05** — `B9` flags `.bak` and `_DRAFT_GEMMA` but **does not** flag a plain `_DRAFT` file.
  The Roadmap legitimately ships as `Spectricom_Product_Roadmap_v2-12_DRAFT.md`; a test asserts it
  is not flagged.
- **AC-BA2-06** — `orchestrator.py` is **byte-identical**. Paste `git diff --stat -- orchestrator.py`
  showing no change.
- **AC-BA2-07** — `python3 -m pytest tests -q` passes with **no new failures** versus the baseline
  you take at the start of the route. The baseline at `79bfea3` is **326 passed, 0 failed**; state
  both numbers. Note it is `python3 -m pytest tests`, not bare `pytest`, which fails collection.
- **AC-BA2-08** — running the assert against the **live** canon folder is reported verbatim,
  whatever it says. **If it reports failures, that is a finding and not a defect of this route** —
  do not edit canon to make your own assert green. Canon is George's and Gemma's to write.
- **AC-BA2-09** — `doc-sweep.sh` is unmodified. This is a sibling tool, not a replacement; the
  report states in one line how they differ so nobody later merges them by accident.

## 6 · Halt and report

Halt if: an assertion cannot be expressed against the real file shapes without guessing; B7's
family list cannot be derived from filenames without a hard-coded list that will rot; or the work
requires touching `orchestrator.py`.

**A halt with a good finding is a pass here.** The worst outcome available is a green assert that
checks less than it claims, which is precisely what B1–B5 turned out to be.

## 7 · Return

Commit on the route branch. This is a **self-modifying** repo route: the orchestrator gates before
merging and correctly withholds the merge on a red. Every gate runs; none is to be bypassed or
suppressed by any flag.

Report, in this order: the fixtures-before-real ordering statement · the AC-BA2-02 failing output ·
the B6/B7 failure messages · the live canon run verbatim · the pytest before/after numbers ·
`git diff --stat` · anything you halted on.
