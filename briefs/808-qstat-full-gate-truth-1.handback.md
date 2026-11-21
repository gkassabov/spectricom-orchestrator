## STATUS: DONE

# 808 QSTAT-FULL-GATE-TRUTH-1 — handback

Branch `orch-orch-000000808-qstat-full-gate-truth-1`. Base by ancestry: `git merge-base --is-ancestor 4df1c96 HEAD` → true.

## A0 at HEAD, before any edit (all three match the brief)
```
--1  git grep -n 'STALE_AFTER_H' -- qstat.sh
(none)
--2  git grep -nF 'print(f"🌙 FULL-GATE {name} | ⚪ never run | nightly {r[' -- qstat.sh
qstat.sh:88:        print(f"🌙 FULL-GATE {name} | ⚪ never run | nightly {r['full_gate_nightly']}")
--3  git grep -nF 'except (OSError, ValueError):' -- qstat.sh
qstat.sh:74:    except (OSError, ValueError):
```

## G-1
`~/_eos/s7core58/dry/808.patch` sha256 `b4c05b1bd3fa3147e6c2c39010de906b5ca7fd32214c8d3fd2591924ba3b576c`, which matches the brief. Applied exactly with `git apply`, in two steps: first the test file alone (for RED), then `qstat.sh`. No other edits.

## RED (base `qstat.sh`, new test file alone): 2 failed / 4
```
E       AssertionError: ['🌙 FULL-GATE clinical-mp | ⚪ never run | nightly 02:30']                       (Q-1)
E       AssertionError: ['🌙 FULL-GATE clinical-mp | ✅ PASS | 2026-11-18T08:02 | sha a1b2c3d | nightly']   (Q-2)
FAILED tests/test_qstat_full_gate_truth.py::test_q1_unreadable_is_said - Asse...
FAILED tests/test_qstat_full_gate_truth.py::test_q2_old_nightly_pass_is_stale
2 failed, 2 passed in 0.24s
```

## GREEN (after G-1): 4 / 4
```
[Q-1] ['🌙 FULL-GATE clinical-mp | ⚠️ unreadable state file full-gate-clinical-mp.json (JSONDecodeError)']
[Q-2] ['🌙 FULL-GATE clinical-mp | ✅ PASS | 2026-11-18T08:02 | sha a1b2c3d | nightly', "   ⚠️ STALE — clinical-mp's last full gate finished 3.0 days ago (nightly 02:30; over 26 h)"]
4 passed in 0.22s
```
`bash -n qstat.sh` → ok.

## Whole suite: not run by the executor
The fire prompt says to run only the test files added or changed, by path, and never a full suite (ORCH-LEAN-GATE-1 / CLAUDE.md test scope). That overrides the brief's "`python3 -m pytest -q tests/` → all green" and its "every test file naming `qstat`" run. The pre-merge gate runs the full unit suite, including `test_gate_cost`'s exact-line pin. The dry run reported 3260 passed, 1 skipped and qstat tests 181 / 181.

## Commit
One commit on this branch: `qstat.sh`, `tests/test_qstat_full_gate_truth.py` (new) and this handback. Bugs SCA-ORCH-QSTAT-UNREADABLE-NEVERRUN-1 and SCA-ORCH-QSTAT-STALE-PASS-1 close on merge.
