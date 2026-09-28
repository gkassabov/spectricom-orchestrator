#!queue model=claude-opus-5-5 effort=high repo=orchestrator

# TONI-BG-CEILING-1 — a wait that cannot outlive its route

## Repo: orchestrator
## Batch ID: s7core15-toni-bg-ceiling-1
## Briefs: 1
## Estimated runtime: 30-45 min
## Spec reference: [TONI-BG-CEILING-1] P1, Bug Registry v1-54; the prevention half of [TONI-BACKGROUND-EXIT]
## Predecessor: orchestrator main @ 66cb02c (ORCH-HANDBACK-GUARD-1), verified with git rev-parse --short main. The owner reports pytest -q tests/ at 583 passed; the brief author did NOT run the suite — you measure it at the merge-base.

> **DO NOT BACKGROUND ANYTHING.** Run every command in the foreground. Do not end your turn until each one has finished and you have its numbers. This brief exists because of exactly that failure. The handback guard shipped in `66cb02c` judges your closing words, and it will **stop this route** if they advertise outstanding work. §6 tells you how to check your handback against the guard before you print it.

## 0 · FIRST STEP

Read these in full before you design anything. Every name and line below was checked on `main` @ `66cb02c`. If a line has moved, find it by name with grep. Do not trust the number.

1. **The spawn site: `orchestrator.py:804` `fire_toni`.**
   - The command string is built at `:812-818`: `cd {project} && stdbuf -oL claude --dangerously-skip-permissions --model … --effort … "Read … and execute all briefs in order."`.
   - The child is spawned at **`:836-838`**: `subprocess.Popen(cmd, shell=True, executable="/bin/bash", stdout=lf, stderr=subprocess.STDOUT, cwd=str(project), preexec_fn=os.setsid)`.
   - **No `env=` is passed.** So the child inherits the orchestrator's `os.environ` implicitly, through `/bin/bash -c`, then `stdbuf` (which uses execvp), then `claude`. This changes the fix in two ways:
     - (a) the fix must construct an explicit `env`, not rely on inheritance;
     - (b) whatever `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS` the parent holds reaches the executor unchanged today, **including `0`**. The parent's value comes from the queue daemon's own inherited spawn at `queue_daemon.py:505-507` (also no `env=`), and that comes from whatever shell started the daemon. The fix must **override** the variable. It must not `setdefault` it.
2. **The route timeout at that point** is the module global **`TONI_TIMEOUT`**, in **seconds**.
   - It is defined at `:195` (`TONI_TIMEOUT_MIN` env or `TIMEOUT_DEFAULT_MIN = 45`, `:193`) × 60.
   - It is reassigned per route in `_run_batch_inner` at **`:3601-3603`** (`global TONI_TIMEOUT; timeout_min, timeout_src = resolve_timeout(batch_file); TONI_TIMEOUT = timeout_min * 60`).
   - `resolve_timeout` (`:595-621`) takes the value from the env var first, then the brief, then the default, and clamps at `TIMEOUT_HARD_CAP_MIN = 180` (`:194`, `:615-619`). **It has no lower bound.** `TONI_TIMEOUT_MIN=0` yields `0`.
   - `parse_brief_timeout` (`:564-592`) turns `## Estimated runtime: 30-45 min` into `int(45 × 1.25) = 56` minutes. That is this brief's own timeout.
   - The smallest timeout a prefire-clean brief can resolve to is **37 m** (`prefire.py:31` `SIZING_FLOOR_MIN = 30`, × 1.25). An env override can go lower.
   - `fire_toni` reads `TONI_TIMEOUT` at `:829`, `:839` (`proc.wait(timeout=TONI_TIMEOUT)`) and `:844`.
3. **What happens at the route timeout: `:843-849`.** `fire_toni` logs `Toni TIMEOUT`, sends SIGTERM to the process group (`setsid` at `:838` makes `claude` the group leader), sleeps 3 s, sends SIGKILL and returns `-1`. **No trailer is written.** The exception path (`:850-852`) returns `-2`, also with no trailer.
4. **The only caller:** `_run_batch_inner`, `fire_toni(target, proj)` at **`:3655`**. It serves both the normal route lane (`worktree is None`) and the meta-fire/self-mod lane. `status = Status.PASSED if (ec == 0 or _produced_work) else Status.FAILED` is at `:3683`. In the normal lane `_produced_work` comes from the working tree and branch (`:3673-3680`). In the meta lane it is `ec == 0` (`:3682`).
5. **The predicate module: `canon_assert.py`.** `orchestrator.py:36-37` imports its fire-time assertions. The last three routes each extended it: `fbccabd` ORCH-CONFLICT-1, `3e34fbf` ORCH-STDOUT-1, `66cb02c` ORCH-HANDBACK-GUARD-1. Read the ORCH-STDOUT-1 section (`:705-790`) and the ORCH-HANDBACK-GUARD-1 section (`:792-914`). Your section goes **after `:914`**, before `# ── verdict building` (`:916`). ORCH-STDOUT-1 is the precedent for pairing a predicate with a **source guard** (`canon_assert.py:713-715`; the guard is `tests/test_queue_gate_log.py:321`).
6. **The guard rule that sees the CLI's own ceiling line:** `config/handback-guard.json`, id `cli-bg-ceiling`, regex `^Background tasks still running after \d+s; terminating\.`. It matches any number of seconds, so it keeps working at the new value.
7. **The evidence log (read-only):** `~/spectricom-orchestrator/logs/clinical-mp/toni-toni-batch-s7core7-drk-q10-q11-panel-rulings-01-20260911-190755.log`. It is 12 lines.
   - `Started: 19:07:55`.
   - Line 7 is the CLI's `Background tasks still running after 600s; terminating. Set CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 to wait indefinitely.`
   - Line 8 is the executor's closing message: *"…depends on the full-suite result still running in the background. Waiting on that notification."*
   - The route finished at `19:47:37` with `Exit: 0`.
   - Two facts follow. The wait began about **29 m 41 s** into the route (39 m 41 s wall time minus 600 s). And **in this invocation shape the CLI prints the executor's closing message at exit, after the ceiling line.** §2.3 depends on both.

## 1 · WHY THIS EXISTS

`orchestrator.py handback-scan logs/clinical-mp` over 814 Toni logs finds 27 with outstanding work. The executor is not being careless. The unit suite outgrew the CLI's foreground window, so the executor moved it to the background as designed. The CLI then stopped waiting at its **600 s default ceiling**, killed the suite and exited 0.

A grep over `orchestrator.py`, `queue_daemon.py`, `config/*.yaml`, `*.sh` and `*.json` finds `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS` set **nowhere**. Every fire this pipeline has ever made ran under the 600 s default. The suite is now 875 files / 8866 tests at about 265 s per run (owner-reported). A route that measures a branch **and** a baseline is at or over the ceiling.

ORCH-HANDBACK-GUARD-1 (`66cb02c`) **detects** such a route and refuses to merge it. This brief is the **prevention** half, the successor ORCH-HANDBACK-GUARD-1 named "ORCH-BG-WAIT-1". It stops the CLI from giving up on work the route still has time for.

**The decision is taken. Do not reopen it. Implement it.**
- Set the ceiling in the Toni child environment.
- **Bound it to the route's own timeout. Never set it to `0`.** `0` means wait indefinitely. That trades a silent half-merge for a route that hangs to its timeout and reports nothing, which is the same failure in different clothes.
- A wait must never be able to outlive the route that owns it.

## 2 · THE TARGET STATE (D-S7CORE13-02 — a runnable predicate)

### 2.1 The predicate

Let **V** = `"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"`.

Let **S** = the set of **executor spawn sites in `orchestrator.py`**. An executor spawn site is a process-spawning call whose command runs the `claude` CLI. On this tree, **S = { the `subprocess.Popen` in `fire_toni`, `orchestrator.py:836` }**. It is reached only from `_run_batch_inner` `:3655`, which covers both the normal and the meta-fire lanes. The source guard in AC-BC-05 pins S to exactly this one site. A future route that adds a second `claude` spawn, or a second `Popen`, turns that test red until the new site passes through the same predicate.

For **every fire f through a site s ∈ S**:
- let **T_f** be the route timeout in seconds that `fire_toni` hands to `proc.wait` for that fire;
- let **env_f** be the mapping passed as `env=` to the spawn.

Then:

```
T_f is an int (not a bool) and T_f > 0
∧ env_f is not None                                   # explicit, never implicit inheritance
∧ V ∈ env_f ∧ env_f[V] matches ^[0-9]+$
∧ 0 < int(env_f[V]) < 1000 · T_f                      # positive, strictly below the route
```

`check_bg_ceiling_invariants(site, env_f, T_f)` returns `[]` exactly when this holds for that fire. On the current tree it fails for every fire: `env_f is None`.

**Not covered, named (A11):**
- `queue_daemon.py:505` spawns `orchestrator.py`, not the executor.
- `agents/*.py` and `loop/*.py` make API calls, not CLI spawns.
- `pcfg-chain.sh:18` is a `pgrep`, not a spawn.
- None of the gate subprocesses in §4 runs `claude`.

### 2.2 The value, and the margin (decided here)

```
BG_WAIT_MARGIN_S = 300
ceiling_ms(T) = (T − 300) · 1000     if T > 600
              = T · 1000 // 2        if T ≤ 600      # tiny env-override timeouts; still 0 < c < T
```

The two branches meet at T = 600 (both give 300 000). T ≤ 0 has no valid ceiling. The predicate reports `route-timeout-invalid` and the fire is refused (T2).

| T (route timeout) | ceiling |
|---|---|
| 60 s (`TONI_TIMEOUT_MIN=1`) | 30 000 ms |
| 600 s | 300 000 ms |
| 601 s | 301 000 ms |
| **1800 s — the 30 m floor** | **1 500 000 ms (25 m)** |
| 2220 s — 37 m, the smallest prefire-clean route | 1 920 000 ms (32 m) |
| **3360 s — 56 m, this brief's shape** | **3 060 000 ms (51 m)** |
| 10 800 s — 180 m hard cap | 10 500 000 ms (175 m) |

**Why 300 s.** The margin trades two things.
- A **larger** margin lets the CLI's own clean exit beat the route's SIGKILL for more of the route. The CLI's exit prints the ceiling line, which `cli-bg-ceiling` catches, and prints the executor's closing words. The CLI ceiling fires before the route kill only when the wait begins within the first *margin* seconds (see §2.3).
- A **smaller** margin permits a longer wait.

At 300 s, every legal route of 30 m or more still permits a wait of at least 25 m. That is about 2.8× the ~530 s a branch + baseline pair of suite runs needs, so the 600 s-shaped early exit cannot recur at any realistic timeout. 300 s is also 100× the 3 s SIGTERM→SIGKILL grace at `:846`.

A proportional margin such as T/2 would not have covered the evidenced case either: its wait began at 29 m 41 s. It would also cut the permitted wait to about 18 m on a 37 m route. So fixed and small wins.

### 2.3 What a static ceiling cannot do — say this in the handback, do not fix it here

The CLI measures the ceiling **from the moment its wait begins**. The env value is fixed **at spawn**. No spawn-time value can guarantee that the wait ends *margin* seconds before the route kill.

With C = T − 300, the ceiling fires first only if the wait began in the first 300 s. The evidenced wait began at about 29 m 41 s. For a route shaped like that, **the route timeout, not the ceiling, is the binding stop** whenever the background work hangs.

At that stop `fire_toni` sends SIGKILL with no trailer (`:843-849`). Per §0.7, the CLI prints the closing message at exit, so the executor output is **probably empty**. The handback guard therefore flags nothing. In the normal lane, `ec != 0 and _produced_work` is `PASSED` (`:3683`), so the tree is gated and **can merge**. This is ORCH-HANDBACK-GUARD-1's "Found, not fixed: a timed-out executor with work on the branch is gated and can merge". **This brief makes that path more reachable.** Name it in §7 as the successor that must follow: candidate **ORCH-TIMEOUT-HOLD-1**, "a route killed at its timeout does not merge".

## 3 · SCOPE — exactly what to change

### T1 · the predicate (`canon_assert.py`, new section after `:914`)

Add a header comment in the house style (`# ── TONI-BG-CEILING-1 · the executor wait ceiling (S7-CORE-15) ──…`). It restates §2.1 and says the source-guard half lives in `tests/test_bg_ceiling.py`. Add:

- `BG_WAIT_CEILING_VAR = "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"`. This is the single definition. `orchestrator.py` imports it.
- `@dataclass(frozen=True) class BgCeilingViolation` with fields `site: str`, `route_timeout_s: object`, `value: Optional[str]` (`env.get(V)`, or `None` when env is `None`) and `reason: str`. Give it a `__str__` in the style of `GateLogViolation`.
- `check_bg_ceiling_invariants(site: str, env: Optional[Mapping[str, str]], route_timeout_s: object) -> list[BgCeilingViolation]`. It is **EMPTY WHEN CLEAN**. It returns **at most one** violation: the first that applies, in this order:
  1. `route-timeout-invalid`: not an `int`, a `bool`, or ≤ 0;
  2. `env-not-explicit`: `env is None`, meaning the spawn inherits implicitly. The predicate will not vouch for an environment the site did not construct;
  3. `ceiling-absent`;
  4. `ceiling-not-an-integer`: not `re.fullmatch(r"[0-9]+", value)`, which rejects `" 5"`, `"+5"`, `"5.0"` and `""`;
  5. `ceiling-not-positive`: `"0"` and `"000"` land here;
  6. `ceiling-not-below-route-timeout`: `int(value) >= 1000 * route_timeout_s`.

  The docstring states the set, meaning one spawn at one site, and the order. The module stays stdlib-only.

### T2 · the one site (`orchestrator.py`, `fire_toni` only, plus two constants and an import)

1. Next to `TIMEOUT_DEFAULT_MIN` / `TIMEOUT_HARD_CAP_MIN` / `TONI_TIMEOUT` (`:193-195`), add `BG_WAIT_MARGIN_S = 300` with a one-line comment pointing at §2.2's reasoning.
2. Extend the `from canon_assert import (...)` at `:36-37` with `BG_WAIT_CEILING_VAR, check_bg_ceiling_invariants`.
3. Add two small pure functions just above `fire_toni`:
   - `bg_wait_ceiling_ms(route_timeout_s: int) -> int`: §2.2's formula, and nothing else.
   - `toni_child_env(route_timeout_s: int, base: Optional[Mapping[str, str]] = None) -> dict[str, str]`: `dict(os.environ if base is None else base)` read **at call time**, then `env[BG_WAIT_CEILING_VAR] = str(bg_wait_ceiling_ms(route_timeout_s))`. This **overrides** any inherited value. It must not mutate `os.environ` or `base`.
4. In `fire_toni`:
   - Read `route_timeout_s = TONI_TIMEOUT` **once**, before anything else.
   - Use that local at `:829`, `:839` and `:844`, so that the wait bound and the ceiling cannot diverge.
   - Before `open(out_log, "w")`, build `env = toni_child_env(route_timeout_s)` and run `v = check_bg_ceiling_invariants("orchestrator.fire_toni", env, route_timeout_s)`.
   - If `v` is non-empty: `log.error(f"⛔ Toni NOT fired — bg-wait ceiling: {v[0]}")` and `return -2, str(out_log)`. **Do not spawn.**
   - Otherwise add `log.info(f"  BG wait ceiling: {ms}ms ({BG_WAIT_CEILING_VAR}; route timeout {route_timeout_s}s, margin {BG_WAIT_MARGIN_S}s)")` after the `Timeout:` line.
   - Write one header line `BgWaitCeilingMs: <ms> (route timeout <T>s, margin 300s)` after the `Command:` line and **before** the 60-`=` rule. It must not start with `Background`, because `cli-bg-ceiling` is anchored at `^Background`.
   - Pass **`env=env`** to the `Popen` at `:836`. Change nothing else in the `Popen`.

   A refused fire ends `FAILED`: `ec = -2`, and a freshly cut branch has no produced work (`:3673-3683`). That is loud, and it is not `passed`.

That is the whole production change. Do not touch `queue_daemon.py`, any shell profile, `startup.sh`, `spectricom-tmux.sh`, `watchdog.sh` or `config/*`. The value depends on the route's timeout, and only `fire_toni` knows that.

### T3 · tests (`tests/test_bg_ceiling.py`, new)

The **red** tests (R1–R3) must be runnable against **unmodified** `orchestrator.py` / `canon_assert.py`. Import new names **inside** the tests that need them, never at module level. That way the red run fails on assertions, not on an `ImportError`.

Shared fixture for R1, R2, G4 and G6:
- A temporary `bin/` holding an executable file **named `claude`**, with shebang `#!{sys.executable}`. It prints `CEILING=<os.environ.get(V, "<unset>")>` and writes a marker file at `os.environ["BC_MARKER"]`.
- `monkeypatch.setenv("PATH", f"{bin}:{os.environ['PATH']}")` and `monkeypatch.setenv("BC_MARKER", …)`.
- `monkeypatch.setattr(orchestrator, "ensure_log_subdir", lambda _s: tmp_logs)`.
- `monkeypatch.setattr(orchestrator, "RUNNING_FILE", tmp_path / "running.json")`, which does not exist. **Never** let a test touch the live `running.json` or the live `logs/`. A route may be running.
- A project dir under `tmp_path` holding the batch file.
- A test that calls the **real** `fire_toni` goes through the real `Popen`, `/bin/bash -c`, `cd`, `stdbuf` and PATH lookup. The fake is therefore **the process the real `claude` would be**. It reports its own `os.environ`, not a dict the test built. If `stdbuf` is missing, the test **fails**. It does not skip: the real route needs `stdbuf` too.

The tests:
- **R1 · the child sees the bounded ceiling; the parent has none.** `monkeypatch.delenv(V, raising=False)`, `orchestrator.TONI_TIMEOUT = 1800`. Expect the log to contain `CEILING=1500000`. **At the merge-base it contains `CEILING=<unset>`. That is the red: the variable is ABSENT on the current tree.**
- **R2 · override, not inherit.** `monkeypatch.setenv(V, "0")`, `TONI_TIMEOUT = 3360`. Expect `CEILING=3060000`. At the merge-base: `CEILING=0`.
- **R3 · source guard: the spawn passes `env=`.** Parse `orchestrator.py` with `ast`. The `subprocess.Popen` call inside `fire_toni` has an `env` keyword. At the merge-base: red.
- **G1 · predicate cases (parametrised).** One case for each of the six reasons, plus the order:
  - `T=0` with `env=None` gives `route-timeout-invalid`, not `env-not-explicit`.
  - `T=True`, `T=-60`, `T="1800"` and `T=None` each give `route-timeout-invalid`.
  - `"1799999"` at T=1800 is clean. `"1800000"` at T=1800 gives `ceiling-not-below-route-timeout`.
  - `"0"` gives `ceiling-not-positive`. `"-1"`, `" 5"` and `"5.0"` give `ceiling-not-an-integer`.
  - At most one violation per call.
- **G2 · the bound (parametrised over §2.2's table).** For T ∈ {1, 60, 600, 601, **1800**, 2220, **3360**, **10800**}: `bg_wait_ceiling_ms(T)` equals the table value, and `check_bg_ceiling_invariants("x", toni_child_env(T, base={}), T) == []`. Also T ∈ {0, −60}: the predicate returns `route-timeout-invalid`.
- **G3 · `toni_child_env` hygiene.** It preserves every other key of `base` (`PATH`, `ANTHROPIC_API_KEY`). It overrides a pre-existing `V` of `"0"` and of `"999999999999"`. It mutates neither `base` nor `os.environ`. With `base=None` it reads `os.environ` at call time: set a key after import, and it appears.
- **G4 · refusal.** Run `TONI_TIMEOUT = 0` and `TONI_TIMEOUT = -60` through the real `fire_toni`. Each returns `-2`. The marker file does **not** exist: the fake never ran. caplog has one `Toni NOT fired — bg-wait ceiling: … route-timeout-invalid` line.
- **G5 · source guard: S is exactly one site.** In `orchestrator.py`, via `ast`:
  - (a) there is exactly one `subprocess.Popen` call, and it lies inside `fire_toni`;
  - (b) every string constant or f-string fragment matching `\bclaude\s+--` lies inside `fire_toni`. **Exclude docstrings**: the first `Expr(Constant(str))` of the module and of each function or class body. Comments are not in the AST;
  - (c) `os.system`, `os.exec*`, `os.spawn*`, `pty.spawn` and `subprocess.call/check_call/check_output` are not used on any string matching `\bclaude\b`.

  **Green at the merge-base too.** Say so. It pins S, and it goes red when a future route adds a second spawn.
- **G6 · reachability (D-S7CORE9-01).** Wrap the real `orchestrator.check_bg_ceiling_invariants` in a spy and run R1's fire. The spy is called **exactly once**:
  - with `site == "orchestrator.fire_toni"`;
  - with `route_timeout_s == orchestrator.TONI_TIMEOUT`;
  - with an `env` whose `V` equals the `CEILING=` value the child printed.
- **G7 · the header line does not trip the guard.** After R1's fire, the log holds `BgWaitCeilingMs: 1500000 …` **above** the 60-`=` rule. `check_handback_invariants(log, load_outstanding_work_rules(HANDBACK_GUARD_CONFIG)) == []`.

**No existing test file should change.** If one must, justify every changed line in the handback.

### T4 · the live probe: does the CLI honour it, and what does waiting buy?

T3 proves the value reaches the process. It cannot prove that the CLI **honours** the value, or that a wait which **completes** gives the executor another turn. The executor's words in §0.7 assume it does ("Waiting on that notification"). The brief author has not verified that.

If it does not, this brief makes routes wait longer and changes nothing else. Find out, **in the foreground**, in two runs of about 2 minutes each. Mirror `fire_toni`'s shape exactly: no `-p`, and stdout to a file.

```bash
P='Use the Bash tool with run_in_background=true to run: sleep 45 && echo PROBE-BG-DONE . Then end your turn at once with the single word WAITING. If you are later told that background command finished, reply with exactly PROBE-RESUMED.'
d=$(mktemp -d); cd "$d"
claude --version
CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=10000  timeout 300 stdbuf -oL claude --dangerously-skip-permissions --model claude-haiku-4-5-20251001 "$P" > short.log 2>&1; echo "short exit $?"
CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=120000 timeout 300 stdbuf -oL claude --dangerously-skip-permissions --model claude-haiku-4-5-20251001 "$P" > long.log  2>&1; echo "long exit $?"
cat short.log long.log
```

Time each run with `date +%s` before and after it. Expected:
- `short.log` holds the CLI's ceiling line reading **`10s`**, not `600s`. That proves the CLI honours the variable in this shape.
- `long.log` has no ceiling line. **Record whether `PROBE-RESUMED` appears.**

**The probe does NOT background anything of yours.** Your command runs in the foreground under `timeout 300`. Only the nested CLI backgrounds its own `sleep`, and it does so on purpose.

If the probe cannot run, report `AC-BC-07 BLOCKED(environment)` with the error. Examples: no CLI auth in the route environment, or the model will not background the sleep after 2 attempts. Do not fake it. Do not retry more than twice.

## 4 · OUT OF SCOPE — name it, leave it

- **Other long children in `orchestrator.py` (bounded sweep).** None of them runs `claude`, so V means nothing to them. Each has its own `subprocess` timeout. Leave them all:
  - `run_playwright` `:860` (`npx playwright test`, `timeout=300`; dead by default, `RUN_PLAYWRIGHT = False` `:204`);
  - build gate `:1546` (`BUILD_GATE_TIMEOUT = 600`, `:212`);
  - SIT runs `:1784`, `:1849`, `:1938`, `:2013` (`SIT_TIMEOUT = 600`, `:213`);
  - unit suite `_run_unit_suite` `:2471`. Its budget is 900 / 1800 / 300 s, from `:279`, `:287` and `:295`, with per-repo overrides via `_unit_repo_timeout` `:2422`.

  The remaining 40-odd `subprocess.run` calls are one-shot `git` / worktree commands.
- **`queue_daemon.py:505`.** It spawns the orchestrator with no `env=`, and its 11 400 s kill (`:149`) stays above the 180 m cap. Unchanged.
- **The timeout-with-work merge path** (§2.3; `:843-849` with `:3683`). Successor ORCH-TIMEOUT-HOLD-1.
- **Adding `-p` / `--output-format` to the fire command, or changing the prompt.**
- **Retro-action on the 27 corpus routes.**

## 5 · ACCEPTANCE

- **AC-BC-01 · red before green, on unmodified code.** Write T3 first. Run `pytest -q tests/test_bg_ceiling.py -k "R1 or R2 or R3"` (name the tests so that works) against unmodified `orchestrator.py` / `canon_assert.py`.
  - **Expected: 3 failed.** R1 shows `CEILING=<unset>`. R2 shows `CEILING=0`. R3 shows no `env` keyword.
  - Separately, G5 is green at the merge-base.
  - State the observed counts and each failure line.
  - **Set:** R1–R3 and G5.
- **AC-BC-02 · the value reaches the child.** After T2, R1 and R2 pass. The strings the child printed (`CEILING=1500000`, `CEILING=3060000`) are quoted in the handback, copied from the test logs, not retyped.
- **AC-BC-03 · the bound holds.** G2 is green, including **T=1800 (30 m floor) → 1 500 000 < 1 800 000** and **T=10 800 (long, the 180 m cap) → 10 500 000 < 10 800 000**, plus 3360 and 2220. T ≤ 0 is refused (G4).
- **AC-BC-04 · the predicate.** G1 is green, with one case per reason and the order proven.
- **AC-BC-05 · S is pinned.** G5 is green. The handback states S as found: one `Popen` at `fire_toni`, one `claude --` literal at `:815`.
- **AC-BC-06 · reachability and the header.** G6 and G7 are green. The non-test caller of `check_bg_ceiling_invariants` is `fire_toni`, and only `fire_toni`. Show the grep.
- **AC-BC-07 · the live probe.** The two T4 runs, each with its exit code, wall-clock seconds, `claude --version`, whether the `10s` ceiling line appeared, and whether `PROBE-RESUMED` appeared. The alternative is `BLOCKED(environment)` with the reason.
- **AC-BC-08 · the gate: no new failures against the merge-base.** Run `pytest -q tests/` at the merge-base and on the branch, both **in the foreground**, and state **both** counts.
  - Expected baseline: 583 passed, owner-reported and not re-measured by the brief author.
  - Branch: `baseline + new tests` passed, 0 failed.
  - **Set:** every test under `tests/`, none excluded or deselected. Any test that fails on the branch and passed at the merge-base is a new failure, whatever its cause.
- **AC-BC-09 · scope of the diff.** `git diff --stat <merge-base>` lists only `canon_assert.py`, `orchestrator.py` and `tests/test_bg_ceiling.py`. Within `orchestrator.py`, only the constant, the import, the two helpers and `fire_toni` change.

## 6 · HANDBACK

Write the handback as your closing message, in full.

**Check it against the guard before you print it.** Write the draft to `/tmp/bc-handback.txt`, then run:

```bash
python3 - <<'EOF'
from pathlib import Path
from canon_assert import load_outstanding_work_rules
rules = load_outstanding_work_rules(Path("config/handback-guard.json"))
hits = [(r.id, i, l[:120]) for i, l in enumerate(Path("/tmp/bc-handback.txt").read_text().splitlines(), 1)
        for r in rules if l.strip() and r.pattern.search(l)]
print(hits or "CLEAN")
EOF
```

It must print `CLEAN`. Then print that text, unchanged, as your closing message.
- When you quote the probe's CLI line, keep it off the start of a line, e.g. ``P1 printed `Background tasks …` ``. `cli-bg-ceiling` is anchored at `^`.
- Avoid phrasing a *finished* measurement as if it were still in flight. The `background`, `waiting` and `in-flight` rules cannot tell the difference.

**§7 first: what you found and LEFT, and why.** At minimum:
- §2.3 and ORCH-TIMEOUT-HOLD-1;
- the §4 sweep list;
- anything the probe revealed.

Then report:
- **What shipped:** T1–T3 by function name and file:line.
- **The red:** AC-BC-01's counts and failure lines.
- **The child's own words:** AC-BC-02.
- **The bound table:** AC-BC-03, measured.
- **The probe:** AC-BC-07.
- **The gate table:** merge-base count against branch count, **both**, with failures in each.
- **Canon choice:** you extended `canon_assert.py` rather than adding a module. Say why in one line: it is the stdlib-only home of the fire-time assertions `orchestrator.py:36` already imports, and ORCH-CONFLICT-1, ORCH-STDOUT-1 and ORCH-HANDBACK-GUARD-1 each extended it.

Then **D-S7CORE13-03, the consequence**, stated plainly:

1. **Routes that background work at the end now wait instead of quitting at 600 s.**
   - Before: the CLI waited at most 600 s, then killed the background work and exited 0.
   - After: it waits until the work finishes, up to T − 300 s (51 m on a 56 m route).
   - At about 265 s per suite run, a branch + baseline pair is about 9 minutes. An affected route's wall-clock rises by the unfinished remainder of that work, typically a few minutes, plus one follow-up executor turn if AC-BC-07 shows the CLI resumes it.
   - Frequency: the CLI ceiling line appears in 1 of 814 corpus logs, and outstanding work in 27 (3.3%). So the average queue slowdown is small. The drk-q10-shaped worst case is +16 m (wait from 29 m 41 s to a 56 m kill, less the 10 m it already spent).
2. **At the route timeout boundary**, a hung background job (a watch-mode run, a stuck worker) is no longer cut at 600 s. It holds the route until T. `fire_toni` then sends SIGTERM and, 3 s later, SIGKILL (`:843-849`), writes no trailer and returns `-1`. The queue is blocked for the full T.
3. **The failure that grows:** §2.3. The executor's closing words are probably lost at a SIGKILL. The handback guard sees nothing, and in the normal lane a tree with work on it is `PASSED` → gated → mergeable (`:3683`). **The margin does not fix this. ORCH-TIMEOUT-HOLD-1 should be fired next.**
4. **A route with an invalid timeout is refused, not fired.** `TONI_TIMEOUT_MIN=0` or less ends `FAILED`, with `Toni NOT fired — bg-wait ceiling: route-timeout-invalid`. Before this change it spawned and was killed at once.
5. **An operator-exported `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`, including `0`, is now overridden for every fire.** The only way to change the ceiling is the route timeout.
6. **The live daemon and any running orchestrator keep the old code until the next fire or restart.** Say whether either was restarted.
