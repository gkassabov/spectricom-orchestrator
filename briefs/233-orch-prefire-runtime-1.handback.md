# filename: briefs/233-orch-prefire-runtime-1.handback.md

# 233 · ORCH-PREFIRE-RUNTIME-1: handback

**The runtime line now has one parser.** `prefire.parse_declared_runtime` returns `(lower, upper)` in minutes. The sizing floor reads the lower bound (`parse_declared_estimate`). The route timeout reads the upper bound × 1.25 (`prefire.runtime_timeout`, which `orchestrator.parse_brief_timeout` returns after the two override headers). The grammar is today's prefire grammar, unchanged except for one fix: a unit may touch its number (`2-3h`, `1.5h`). Route 225's `2-3 h` now gives 225 min, clamped to 180. On `1e08671` it gave nothing, so the route ran under the 45-min default.

**What prefire does now:**
- A runtime line that gives no upper bound fails `A2 RUNTIME — '<line>' gives no route timeout; write '<n>-<m> min'`. A micro-fire trigger does not waive this.
- The pass line ends with `timeout <N> min (<source>)`.
- When the hard cap clamps that timeout, the pass line adds `⚠ clamped to 180 min from <asked>`. This is a warning, not a failure.

**`## Isolated deps: true` gives a route its own dependency trees.** The route worktree and its unit-baseline worktree each build their own (`npm ci`; a venv from `requirements.txt`) instead of linking the main checkout's. Teardown removes them with the worktree. Without the header nothing changes, and the route log says which mode ran.

P1–P4 are green. P1, P2 and P4 were RED first on `1e08671`, each with a negative control. P3 found no differences.

Things you need to know first:
- **The queue daemon's route wall still reads the runtime line with the old grammar.** That code is `admission.parse_brief_timeout` (`admission.py:295-315`), a restatement of the old orchestrator parser, and `admission.py` is outside §2.
  - So for a brief written in hours, the orchestrator now gives the executor 180 min, but the daemon's wall is still computed from 45 min.
  - The wall is 110–145 min depending on the repo. That is **below** the route's own 180-min timeout, so such a route can be killed by the wall rather than by its own timeout.
  - This is Found-and-LEFT 1, with the one-line remedy. A strict-xfail test pins it, so whoever fixes it sees the test flip.
  - **No brief queued today is affected** (P3).
- **No daemon restart is needed for this merge.** The daemon starts a fresh `orchestrator.py run` for every fire, and that process reads `prefire.py` and `orchestrator.py` new. The Found-and-LEFT 1 remedy *will* need a restart, because the live daemon holds `admission.py` in memory.
- **What is queued:** 233 (this route), 235, 238, 239, 240. All four of the others keep the same lower bound, timeout and A2 verdict (P3).

- **Branch:** `orch-orch-233-orch-prefire-runtime-1`, from `1e08671` (= `main` = merge-base). No commit since `1e08671` touches a named file.
- **Commits:** `5aa1c54` holds `prefire.py`, `orchestrator.py`, `tests/test_runtime_parse.py` (new) and `tests/test_isolated_deps.py` (new). The next commit is this file. I did not commit the brief, following routes 94, 104, 114, 123b, 123c and 135.
- **Tests:** `pytest -q tests/` gives **1062 passed** at `1e08671` (60.36 s) and **1148 passed, 1 xfailed** at `5aa1c54` (66.23 s). That is 0 failed, 0 skipped and 86 new tests. The xfail is the strict pin for Found-and-LEFT 1.

## §1 Found and LEFT

1. **A third parser: the queue daemon's wall (`admission.py`, outside §2).**
   - **Where it is:** `admission.route_wall` (`admission.py:372`) is the daemon's kill for one route: route timeout + gate budget + 900 s slack. The daemon calls it at `queue_daemon.py:1125`. Its route timeout comes from `admission.route_timeout` → `admission.parse_brief_timeout` (`:295`). That function is the 1e08671 orchestrator parser restated, pinned to orchestrator's only by `tests/test_capacity.py:753-762`, and only for headers in minutes.
   - **What it does now (probe, at `5aa1c54`, `## Estimated runtime: 2-3 h`):**

     | repo | executor timeout (orchestrator) | daemon wall (admission) |
     |---|---|---|
     | clinical-mp | 180 min | 145 min = 45 (default) + 85 gates + 15 slack |
     | yorsie | 180 min | 120 min = 45 + 60 + 15 |
     | ai-foundation | 180 min | 110 min = 45 + 50 + 15 |
     | orchestrator | 180 min | 120 min = 45 + 60 + 15 |

   - **The consequence:**
     - **Before this merge:** a route whose runtime is written in hours was killed by its own executor timeout at 45 min. That was route 225's death, a hold with work on the branch.
     - **After it:** the executor may run up to 180 min, but the daemon's wall SIGKILLs the whole route at 110–145 min, in the executor or in its gates. It gets more time than before, and it dies a harder death if it overruns.
     - **Why it stays narrow:** every brief written in minutes, which is every brief in the live queue and in `done/` for 30 days (P3), gets the same number from both parsers.
   - **Remedy:**
     1. Make `admission.parse_brief_timeout`'s `Estimated runtime` branch return `prefire.runtime_timeout(Path(brief))`. That is one import and one line. `prefire` imports only stdlib, `yaml` and `canon_assert`, and writes no log.
     2. Remove the `xfail` marker from `tests/test_runtime_parse.py::test_found_and_left_the_daemons_wall_reads_the_same_route_timeout`, which will then XPASS. Optionally add `"## Estimated runtime: 2-3 h"` to `tests/test_capacity.py:753`'s list.
     3. **Restart the daemon.** It imported `admission` at start (`queue_daemon.py:37`).
2. **The parallel lane shares the mode global.**
   - `ISOLATED_DEPS` is a module global that `run_batch` sets once per route (`orchestrator.py:4358`), the same pattern as `TONI_TIMEOUT` (`:4477`).
   - `run_parallel` (`:4891`) runs `run_batch` in threads, so two parallel batches with different headers race on it. Its gates run afterwards with the value the last batch to start set.
   - Its worktrees (`create_worktree`) link nothing, so only that lane's unit baseline is exposed. The daemon never uses this lane.
3. **Single-stream repos get half the isolation.** clinical-mp, collateral, norra and orchestrator have no route worktree; the route runs in the main checkout. There, `Isolated deps: true` isolates only the unit-baseline worktree, which builds the merge base's tree from the merge base's lockfile. A dependency-upgrade route in clinical-mp still installs into `~/spectricom-clinical-mp/node_modules`, as every clinical-mp route always has. The run_batch log line says the trees are built for "a route worktree and a unit-baseline worktree", which is accurate, but it does not say the route has none.
4. **What isolation costs was not measured.** No real route was fired (tests only).
   - **Sizes:** Yorsie's `yorsie/node_modules` is 556 MB, and ai-foundation's `venv` is 6.1 GB (CUDA wheels, 180 pinned requirements).
   - **When it is paid:** each is built twice per isolated route, once in the route worktree and once in the baseline worktree on a cache miss.
   - **The clock:** each build has a 900 s timeout (`ISOLATED_DEPS_INSTALL_TIMEOUT_S`). The builds are not in admission's gate budget; they come out of the wall's 900 s slack.
   - **Expected ai-foundation outcome:** probably a refused route ("`venv`: … timed out after 900s") or a baseline BLOCKED(environment) `baseline-unmeasurable`.
   - **norra:** its main checkout has a `venv` but no `requirements.txt`, so an isolated norra route is refused with `venv: no requirements.txt in <wt> to build it from`. It is not given an empty venv.
5. **The baseline cache does not key on the deps mode.** A baseline measured on the linked tree at commit X is reused by an isolated route off X, and the other way round (`_unit_cache_lookup`, keyed on sha + cmd). That is correct only while the main checkout's tree matches X's lockfile, and L-92 is the case where it may not.
6. **Nothing checks the header's value before the fire.**
   - Only `true` / `false` are read (case, backticks and `**` aside). Anything else (`yes`, `on`) links as before and logs `⚠️ '## Isolated deps: yes' is not 'true' or 'false' — the dependency trees are LINKED` in the route log.
   - Prefire does not check this header, because D2 names A2 only. A typo would therefore fire a linked route.
7. **Grammar limits I kept** (today's prefire grammar; D1 said not to reopen it):
   - Mixed units, `1 h 30 min`, read as `(1, 30)`. That is a loud floor failure, not a silent timeout.
   - A stray number outside parentheses, `60-90 min, 2 briefs`, makes the lower bound 2: also a loud floor failure.
   - **The one change:** `_MINUTES` / `_HOURS` (`prefire.py:71-72`) now match a unit touching its number. Before, `2h` / `1.5h` / `2-3h` read as 2 / 1 / 2–3 *minutes*, a floor failure. Under the shared parse, a micro-fire brief written that way would also have got a 2-minute timeout. The old orchestrator grammar gave it the 45-min default.
   - The lower bound changes only for lines like that, and there are none in the corpus (P3).
8. **A2 RUNTIME fires even when an override header gives the route a timeout.** `## Estimated runtime: TBD` with `## TONI_TIMEOUT_MIN: 60` fails, because D2 says "the line exists but yields no upper bound". The sizing floor cannot be read off that line either.
9. **Header windows.** The timeout now finds the runtime line anywhere in prefire's 6000-character header. The old orchestrator parser looked only in the first 4000 characters (test: `test_D1_the_runtime_line_is_read_where_prefire_reads_it`). The two override headers are still read in the first 4000, unchanged. `admission.py` reads 4000 throughout.
10. **The CLI cannot resolve the timeout.**
    - `python3 prefire.py <brief>` does not import `orchestrator`, because importing it writes a log and exits on `ANTHROPIC_API_KEY`. So its pass line says what the runtime line asks for, not what the fire resolves: `timeout 225 min (Estimated runtime × 1.25 — the fire applies TONI_TIMEOUT_MIN and the hard cap)`.
    - The clamp warning appears on the fire's pass line, where `run_batch` hands prefire `orchestrator.prefire_timeout(batch_file)`. That is the one line I changed in `run_batch` outside the named functions. The other is the mode line, which D3's "the route log names which mode ran" needs.
11. **README.md is stale.** It describes a YAML task queue, with no brief-header section. The new headers are documented in `orchestrator.py`'s usage block (lines 24-28), next to `depends_on_batches`.

## §0 as-built (pastes, at `1e08671`)

1. **`git log --oneline -1`** → `1e08671 handback: 135-orch-aif-worktree-flip-1 — found-and-left, gate table, the consequence, remedy step 3 for George (ORCH-AIF-WORKTREE-FLIP-1, S7-CORE-21)`.
   - **`git status --short` in this worktree** → `?? briefs/233-orch-prefire-runtime-1.md`.
   - **In the main checkout** (read-only) → `?? running.json.killed-20261005-214518`, the pre-existing untracked file the brief names, left as it is.
   - `main` = `1e08671` = predecessor, so §1 has no re-read.
2. **`sed -n 610,675p orchestrator.py`:**
   ```
           dep = f" (deps: {b.depends_on})" if b.depends_on else ""
           log.info(f"  -> {b.id}: {b.title}{dep}")
       return briefs

   # ═══════════════════════════════════════════════════════
   # BRIEF TIMEOUT PARSING (A62)
   # ═══════════════════════════════════════════════════════
   def parse_brief_timeout(filepath: Path) -> Optional[int]:
       """Parse TONI_TIMEOUT_MIN advisory from brief file header.
       Returns timeout in minutes, or None if not declared.
       """
       try:
           content = filepath.read_text(encoding="utf-8")[:4000]
       except Exception:
           return None

       m = re.search(r'^## TONI_TIMEOUT_MIN:\s*(\d+)', content, re.MULTILINE)
       if m:
           return int(m.group(1))

       m = re.search(r'^## Fire mechanism:.*TONI_TIMEOUT_MIN=(\d+)', content, re.MULTILINE)
       if m:
           return int(m.group(1))

       m = re.search(r'^## Estimated runtime:\s*(.+)', content, re.MULTILINE)
       if m:
           runtime_line = m.group(1)
           rm = re.search(r'(\d+)\s*-\s*(\d+)\s*m', runtime_line)
           if rm:
               upper = int(rm.group(2))
               return int(upper * 1.25)
           rm = re.search(r'(\d+)\s*m', runtime_line)
           if rm:
               return int(int(rm.group(1)) * 1.25)

       return None


   def resolve_timeout(brief_path: Optional[Path] = None) -> tuple[int, str]:
       """Resolve timeout with precedence: env-var > brief-declared > default.
       Returns (timeout_minutes, source_label). Hard cap at 180m.
       """
       env_raw = os.environ.get("TONI_TIMEOUT_MIN", "")
       if env_raw:
           timeout = int(env_raw)
           source = "env-var"
       elif brief_path:
           brief_val = parse_brief_timeout(brief_path)
           if brief_val is not None:
               timeout = brief_val
               source = "brief-declared"
           else:
               timeout = TIMEOUT_DEFAULT_MIN
               source = "default"
       else:
           timeout = TIMEOUT_DEFAULT_MIN
           source = "default"

       if timeout > TIMEOUT_HARD_CAP_MIN:
           log.warning(
               f"Timeout {timeout}min exceeds hard cap {TIMEOUT_HARD_CAP_MIN}min; clamping"
           )
           timeout = TIMEOUT_HARD_CAP_MIN

       return timeout, source
   ```
   **`sed -n 55,95p prefire.py`:**
   ```
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
   ```
   (The docstring's `'1.5h' -> 90` was not true at `1e08671`. `\bh` does not match after a digit, so `1.5h` read as 1 min. It is true now.)

   **`grep -n "parse_brief_timeout\|resolve_timeout\|parse_declared_estimate" *.py tests/*.py`:**
   ```
   admission.py:295:def parse_brief_timeout(brief) -> Optional[int]:
   admission.py:296:    """orchestrator.parse_brief_timeout, restated: minutes the brief declares, or None."""
   admission.py:319:    """(minutes, source) by orchestrator.resolve_timeout's rule: TONI_TIMEOUT_MIN > brief-declared > the
   admission.py:330:        declared = parse_brief_timeout(brief) if brief else None
   orchestrator.py:617:def parse_brief_timeout(filepath: Path) -> Optional[int]:
   orchestrator.py:648:def resolve_timeout(brief_path: Optional[Path] = None) -> tuple[int, str]:
   orchestrator.py:657:        brief_val = parse_brief_timeout(brief_path)
   orchestrator.py:4372:    timeout_min, timeout_src = resolve_timeout(batch_file)
   prefire.py:65:def parse_declared_estimate(filepath: Path) -> Optional[int]:
   prefire.py:249:    estimate = parse_declared_estimate(filepath)
   prefire.py:287:        est = parse_declared_estimate(filepath)
   tests/test_capacity.py:762:        assert admission.route_timeout(b) == orchestrator.resolve_timeout(b)
   tests/test_prefire.py:33/38/44/49/54:  prefire.parse_declared_estimate(...)
   tests/test_timeout_resolution.py:18:from orchestrator import parse_brief_timeout, resolve_timeout, TIMEOUT_DEFAULT_MIN
   tests/test_timeout_resolution.py:31/38/42/46/50:  parse_brief_timeout(f) == 60 / 90 / 50 / 25 / None
   tests/test_timeout_resolution.py:58/67/76/86:  resolve_timeout(f)
   ```
   The `admission.py` lines are the third parser: Found-and-LEFT 1.
3. **The 225 gap on HEAD.** The fixture `/tmp/p233/brief-2-3h.md` has `## Kanban: SCP_Kanban row 233` (a scratch READY row) and `## Estimated runtime: 2-3 h`. `TONI_TIMEOUT_MIN` was unset.
   ```
   parse_declared_estimate: 120
   prefire.check: []
     Assertions: ✅ A1/A2/A8 pass — SCP_Kanban row 233 READY (SCP_Kanban_v1-0.md); declared 120m (floor 30m)
   prefire.report -> True
   parse_brief_timeout: None
   resolve_timeout: (45, 'default')
   ```
   `admission.route_timeout(b, env={})` → `(45, 'default')`.
4. **Every place the main checkout's dependency trees reach a worktree.**
   - **`sed -n 330,340p`:**
     ```
     # reasons that have nothing to do with the code. These git-ignored paths are symlinked in
     # from the gated checkout so both sides run the same suite. Read-only use — a concurrent
     # route sharing them is unaffected. The repo's declared env_file (PRE_MERGE_GATES) is
     # linked too; its NAME is used, its values are never read or logged (canon §23.9d).
     UNIT_BASELINE_LINK_PATHS = ("node_modules", "venv", ".venv", "yorsie/node_modules")
     # A fully-green branch cannot be a regression against ANY baseline: 0 > n is false for
     # every n >= 0, and an empty failing-file set cannot contain a newly-failing file. So the
     # baseline run is skipped in that case and the gate costs one suite run, not two.
     # Set False to always measure both sides.
     UNIT_GATE_SKIP_BASELINE_WHEN_GREEN = True
     # S7-CORE-9 [ORCH-7] AC-O7-04: named once is noise; named this many times is a file to
     ```
   - **`sed -n 1585,1600p`** (`_finish_route_worktree`):
     ```
         """A route that merged, or changed nothing, leaves no worktree; any other keeps it, named in the log.
         The dependency links are removed first, so the removal can never reach into the main checkout."""
         branch = _git_read("git rev-parse --abbrev-ref HEAD", wt) or "?"
         if result is None or result.status != Status.PASSED:
             log.warning(f"🌳 Route worktree preserved: {wt} (branch {branch}). After review: "
                         f"git -C {PROJECT_ROOT} worktree remove {wt}")
             return
         env_name, _ = _gate_env_file(PROJECT_ROOT)
         for rel in list(UNIT_BASELINE_LINK_PATHS) + ([env_name] if env_name else []):
             if (wt / rel).is_symlink():
                 try:
                     (wt / rel).unlink()
                 except OSError as e:
                     log.warning(f"⚠️ Route worktree: could not unlink {rel}: {e}")
         subprocess.run(f"git -C {shlex.quote(str(PROJECT_ROOT))} worktree remove --force {shlex.quote(str(wt))}",
                        shell=True, capture_output=True)
     ```
   - **`sed -n 2812,2840p`** (`_link_unit_deps`):
     ```
     def _link_unit_deps(src: Path, dst: Path) -> list:
         """Symlink the git-ignored dependency paths (and the declared env_file) from the gated
         checkout into the detached baseline worktree, so the baseline runs the same suite the
         branch does. Returns the links created, for teardown. Never reads any file's contents.

         [ORCH-9]: the env_file is linked for PARITY, not for use — the unit suite is no longer run
         through the env-sourcing shell. The branch leg runs in a checkout that has the file on
         disk, so the baseline leg gets one too; whether a repo's own config reads it is the
         repo's decision to make identically on both sides."""
         created = []
         names = list(UNIT_BASELINE_LINK_PATHS)
         env_name, _ = _gate_env_file(src)
         if env_name:
             names.append(env_name)
         for rel in names:
             s, d = src / rel, dst / rel
             if not s.exists() or d.exists():
                 continue
             try:
                 d.parent.mkdir(parents=True, exist_ok=True)
                 d.symlink_to(s.resolve(), target_is_directory=s.is_dir())
                 created.append(d)
             except OSError as e:
                 log.warning(f"⚠️  Unit baseline: could not link {rel}: {e}")
         return created
     ```
   - **Call sites** (`grep -n "_link_unit_deps(" orchestrator.py`): `:1578`, the route worktree (`_create_route_worktree`, `worktree_mode: parallel` repos: yorsie, ai-foundation), and `:2925`, the unit-baseline worktree (`_run_unit_baseline`, every repo with a `test_cmd`). There are no others. The meta-fire worktree (`/tmp/orch-fire-*`) and the parallel lane's `create_worktree` link nothing.
   - **The L-92 path, end to end:** for a Yorsie route, `:2925` runs with `repo_path` = the route worktree. Its `yorsie/node_modules` is the link from `:1578`, and `s.resolve()` follows it to the dev tree. So the baseline links the dev tree's node_modules, which a dependency-upgrade route has just installed into.
   - **What the real checkouts hold** (read-only `ls`): dev-pipeline has `yorsie/node_modules` (dir, 556 MB) with `yorsie/package-lock.json`; ai-foundation has `venv` (dir, 6.1 GB, `python3 -m venv`, 3.12.3) with `requirements.txt`; clinical-mp has `node_modules` (dir) with `package-lock.json`; norra has `venv` (dir) and no `requirements.txt`. Every one of them is git-ignored as a directory (`node_modules`, `venv`; norra's line reads `venv/`).

## Shipped (`5aa1c54`)

### `prefire.py`
- **`parse_declared_runtime(filepath) -> (lower, upper) | None`** (`:81`): the one parse.
  - Unchanged from today's grammar: the header regex, parenthetical stripping, en/em dash, every number in the line, and hours scaled ×60 when no minutes unit is present.
  - Changed: `_MINUTES` / `_HOURS` use `(?<![a-z])` instead of `\b`, so a unit may touch its number.
- **`parse_declared_estimate`** (`:110`) is now its lower bound. **`runtime_timeout`** (`:120`) is `int(upper × RUNTIME_TIMEOUT_FACTOR)`, with the factor 1.25 named once (`:74`).
- **`check`:**
  - `A2 RUNTIME — '<line>' gives no route timeout; write '<n>-<m> min'` (`:290`) when the line exists and gives no bound, micro-fire trigger or not.
  - A missing line and an under-floor line fail exactly as before.
- **`report(filepath, timeout=None)`:** the pass line gets `; timeout <N> min (<source>)`, plus `⚠ clamped to <N> min from <asked>` when the cap applied (`_timeout_detail`, `:321`).

### `orchestrator.py`
- **`parse_brief_timeout`** (`:630`): the two override headers as before, then `return prefire.runtime_timeout(filepath)`. Its own runtime grammar is deleted.
- **`resolve_timeout`** (`:667`):
  - Same precedence and return value. Precedence now lives in `_requested_timeout` (`:655`), which is the old body minus the cap.
  - The clamp warning names its source: `Timeout 225min (brief-declared) exceeds hard cap 180min; clamping`.
  - The route log's `timeout=<N>min source=<s>` line is unchanged.
- **`prefire_timeout`** (`:682`): `(resolved, source, asked)` for prefire's pass line, or None when `TONI_TIMEOUT_MIN` is not a number. The route then fails at its own `resolve_timeout`, as before.
- **D3:**
  - **Constants:** `ISOLATED_DEPS`, `ISOLATED_DEPS_HEADER`, `ISOLATED_DEPS_INSTALL_TIMEOUT_S = 900` (`:345-347`).
  - **`parse_isolated_deps`** (`:2877`): reads the header.
  - **`_install_unit_deps(src, dst)`** (`:2892`) builds each tree `src` has, the same paths `_link_unit_deps` would link:
    - `npm ci` beside a `node_modules`, which needs a `package.json` there; `npm ci` itself needs the lockfile.
    - For `venv` / `.venv`: `python3 -m venv <name> && <name>/bin/pip install -q -r requirements.txt`, refused when there is no `requirements.txt`.
    - A built tree must pass `git check-ignore` in `dst`, or it is refused: the route lane's `git add -A` would commit it. (For contrast, a *link* under a `node_modules/` pattern is not ignored; checked: `git check-ignore` exit 1 for a symlink, 0 for a directory.)
  - **`_link_unit_deps(src, dst, isolated=False)`** (`:2847`): `isolated` links the env_file alone.
  - **`_create_route_worktree`** (`:1573`): isolated, it builds, or removes the half-built worktree and returns `isolated deps: <why>`. `run_batch` then refuses the route, exit 2, as for any route-worktree failure. It never falls back to the link.
  - **`_finish_route_worktree`** (`:1615`): the trees go with `git worktree remove --force`. If the directory survives, it warns and gives the command.
  - **`_run_unit_baseline`** (`:2994`): isolated, it builds the merge base's own trees from the merge base's lockfile. A failed build returns `UnitSuiteRun(error="baseline-deps-install-failed")`, which takes the existing unmeasured-baseline path.
  - **`run_batch`** (`:4347`): passes `prefire_timeout(batch_file)` to `prefire.report`. Sets `ISOLATED_DEPS` once and logs `📦 deps: ISOLATED (## Isolated deps: true) — …` or `📦 deps: linked — …`.
  - **The two worktree lines name the mode:**
    - `🌳 Route worktree: <wt> (from main; isolated deps — built its own yorsie/node_modules (npm ci); linked from <root>: nothing) — the main checkout is not the route's, nor are its dependency trees`
    - `🧬 Unit baseline: measuring … in a detached worktree (isolated deps — built its own node_modules (npm ci))`
    - The linked-mode lines are byte-identical to `1e08671`'s.
- **Usage block** (`:24-28`): `## Estimated runtime:` and `## Isolated deps: true`.

### Tests
- **`tests/test_runtime_parse.py`** (61 + 1 strict xfail):
  - The 20-line grammar table (corpus shapes plus route 225). Each line is checked three ways: bounds, estimate and timeout.
  - "A line prefire accepts always yields a timeout" over the same table.
  - The timeout provably comes from prefire's parse (monkeypatched to `(10, 100)` → 125).
  - P1, P2, the CLI pass line, and the Found-and-LEFT 1 pin.
- **`tests/test_isolated_deps.py`** (25):
  - The header (8 shapes, plus an unreadable value).
  - P4 through the real `run_batch`, reusing `tests/test_control_scope.py`'s `WorktreeRoute` Yorsie-shaped fixture route. `npm ci` is faked by an `npm` on `PATH`; `npm run build` is the real npm.
  - Refusals (no lockfile; tree not ignored).
  - The unit-baseline worktree, both modes plus a failed build.
  - A real venv for a Python repo; refusal without `requirements.txt`.
  - Only the checkout's trees are built; the env_file is still linked.

## §2 Predicates

| # | RED on `1e08671` | GREEN at `5aa1c54` | Negative control | Verdict |
|---|---|---|---|---|
| **P1** `2-3 h` | `parse_brief_timeout` → **None**; `resolve_timeout` → `(45, 'default')`; prefire passed at 120 (§0.3). New tests: `test_D1_a_line_prefire_accepts_always_yields_a_timeout[2-3 h]`, `[3-4 hours Toni session]`, `[1.5 hours]` fail (accepted, no timeout) | `parse_brief_timeout` → **225**; `resolve_timeout` → `(180, 'brief-declared')` and `WARNING Timeout 225min (brief-declared) exceeds hard cap 180min; clamping`. Pass line: `… declared 120m (floor 30m); timeout 180 min (brief-declared) ⚠ clamped to 180 min from 225`. `report` → True (a warning, not a failure) | `90-120 min` → **150** at `1e08671` (§0 probe) and at `5aa1c54`, no `⚠`. `## TONI_TIMEOUT_MIN: 40` + `2-3 h` → **40** both. `Fire mechanism … TONI_TIMEOUT_MIN=75` → 75 (also green on HEAD). Env `TONI_TIMEOUT_MIN=30` → `(30, 'env-var')` | **PASS** |
| **P2** no number | **What HEAD did:** `## Estimated runtime: TBD` failed, but as `A2 SIZING — no '## Estimated runtime:' declared. …`, which names a line that *was* there. With a P0/P1 micro-fire trigger, HEAD **passed** it and the route ran on the 45-min default | `A2 RUNTIME — '## Estimated runtime: TBD' gives no route timeout; write '<n>-<m> min'`; the same for `(see §5)` and `two to three hours`, and with a micro-fire trigger | A missing line → `A2 SIZING — no '## Estimated runtime:' declared. …`, unchanged (green on HEAD). Missing line + micro-fire trigger passes on `timeout 45 min (default)`. `12 min` → the floor failure, unchanged (green on HEAD) | **PASS** |
| **P3** corpus | — | **177** briefs in live `queue/` + `queue/done/` modified in the last 30 days (since 2026-09-11 05:43), all with a runtime line. Lower bound old ≠ new: **0**. Line present but no new timeout: **0**. Route timeout old ≠ new: **0**. A2 verdict old ≠ new: **0** | **For information**, `queue/failed/` + `queue/held/` (16): one difference, `failed/225-provider-task-privacy-1.md`, `'2-3 h'`: **None → 225**. 228, the other L-102 brief, is in `done/` reading `120-140 min` (corrected before it fired) | **PASS** (no differences to report) |
| **P4** isolated deps | `orchestrator.ISOLATED_DEPS` / `parse_isolated_deps` / `_install_unit_deps` do not exist; all 25 tests fail or error at setup | Fixture route through the real `run_batch` (status PASSED, gate PASS). The worktree's `yorsie/node_modules` is a **directory, not a link**, built by one `npm ci` in `<wt>/yorsie`. The build gate saw it (`deps`). The route's "upgrade" (`upgraded-pkg.txt`) **never reaches the dev tree**. After the merge the worktree **is gone** with its tree, and the dev tree's `dep.txt` is byte-identical. The log names the mode. Baseline worktree: its own `node_modules`, removed with it | Header absent: the worktree's `node_modules` **is a link** to the dev tree's, no `npm ci` ran, and the linked-mode log lines are unchanged. **The same upgrade lands in the dev tree** (`upgraded-pkg.txt` = `v2`): L-92 reproduced | **PASS** |

**RED run** (the two new files against `1e08671`'s `prefire.py` / `orchestrator.py`): **60 failed, 15 passed, 11 errors.** The errors are fixtures setting `orchestrator.ISOLATED_DEPS`, which did not exist. The 15 that passed are the controls that need no new API:
- `test_D1_a_line_prefire_accepts_always_yields_a_timeout` for the 12 lines in minutes (`75-95 min` … `180 min (CODE PORTION ONLY …)`)
- `TestP1::test_negative_control_a_fire_mechanism_override_still_wins`
- `TestP2::test_negative_control_a_missing_line_fails_as_before`
- `TestP2::test_negative_control_under_the_floor_still_fails_as_sizing`

### P3 probe

`/tmp/p233/p3.py` is read-only. It compares old (`git show 1e08671:prefire.py`, plus the `parse_brief_timeout` source from `git show 1e08671:orchestrator.py`) against new (this tree's), and it judges A2 alone because A1 reads the live Kanban.
```
== P3 queue/ + queue/done/: 177 briefs modified since 2026-09-11 05:43; 177 carry '## Estimated runtime:'
   lower bound old != new: 0
   runtime line present but NEW gives no timeout: 0
   route timeout old != new: 0
   A2 verdict old != new: 0
== (info) queue/failed/ + queue/held/: 16 briefs modified since 2026-09-11 05:43; 16 carry '## Estimated runtime:'
   lower bound old != new: 0
   runtime line present but NEW gives no timeout: 0
   route timeout old != new: 1
     failed/225-provider-task-privacy-1.md: '2-3 h': None -> 225
   A2 verdict old != new: 0
```

### P1 / P2 probe at `5aa1c54` (the §0.3 fixtures)
```
--- 2-3h: runtime=(120, 180) est=120 parse_brief_timeout=225 resolve=(180, 'brief-declared') prefire_timeout=(180, 'brief-declared', 225)
  Assertions: ✅ A1/A2/A8 pass — SCP_Kanban row 233 READY (SCP_Kanban_v1-0.md); declared 120m (floor 30m); timeout 180 min (brief-declared) ⚠ clamped to 180 min from 225
--- 90-120: runtime=(90, 120) est=90 parse_brief_timeout=150 resolve=(150, 'brief-declared') prefire_timeout=(150, 'brief-declared', 150)
  Assertions: ✅ A1/A2/A8 pass — SCP_Kanban row 233 READY (SCP_Kanban_v1-0.md); declared 90m (floor 30m); timeout 150 min (brief-declared)
--- toni40: runtime=(120, 180) est=120 parse_brief_timeout=40 resolve=(40, 'brief-declared') prefire_timeout=(40, 'brief-declared', 40)
  Assertions: ✅ A1/A2/A8 pass — SCP_Kanban row 233 READY (SCP_Kanban_v1-0.md); declared 120m (floor 30m); timeout 40 min (brief-declared)
--- tbd: runtime=None est=None parse_brief_timeout=None resolve=(45, 'default') prefire_timeout=(45, 'default', 45)
  • A2 RUNTIME — '## Estimated runtime: TBD' gives no route timeout; write '<n>-<m> min'
--- missing: runtime=None est=None parse_brief_timeout=None resolve=(45, 'default') prefire_timeout=(45, 'default', 45)
  • A2 SIZING — no '## Estimated runtime:' declared. Declare it (>= 30m, ideally 45-90 — System Prompt 5.19.3), or add '## Micro-fire trigger:' naming the P0-infra or P1-safety trigger (5.9).
```

## §3 Gates

| Gate | Result |
|---|---|
| `pytest -q tests/` at merge-base `1e08671` (this worktree, before any edit; load 4.59) | **1062 passed** in 60.36 s |
| `pytest -q tests/` at `5aa1c54` (load 4.39) | **1148 passed, 1 xfailed** in 66.23 s. **0 new failures**, 0 skipped. +86 tests (61 + 25); the xfail is the strict Found-and-LEFT 1 pin |
| Targeted: `test_runtime_parse.py`, `test_isolated_deps.py`, `test_prefire.py`, `test_timeout_resolution.py` | 107 passed (before the xfail was added); `test_runtime_parse.py` 61 passed, 1 xfailed after |
| The orchestrator's self-mod gate (`build` = `pytest -q tests/` on this worktree, then `_self_mod_auto_merge`) | The orchestrator runs it after this executor exits. It cannot be run from here without firing a route ("Tests only"). The suite it runs is the one above, green at `5aa1c54` |
| Daemon, `queue/`, `state/`, `logs/` of the live checkout | Not touched. The live checkout was only read: `git status`, `ls state/`, the P3 corpus, and dependency-tree `ls`/`du` in the four repos |

## THE CONSEQUENCE (D-S7CORE13-03)

From the first route fired after this merges (no restart needed):
1. **Every route's prefire pass line grows a timeout:** `; timeout <N> min (<source>)`.
2. **Every route log gets one line:** `📦 deps: linked — …`, or `ISOLATED` when the header says so.
3. **A runtime line in hours** (`2-3 h`, `3-4 hours`, `1.5 hours`) **now sets the route timeout:** upper × 1.25, capped at 180 with a `⚠` on the pass line. Before, it set nothing and the route got 45 min.
   - **Until Found-and-LEFT 1 is fixed and the daemon restarted**, a daemon-fired route like that runs under the daemon's wall of 110–145 min, not its 180-min timeout. If it overruns, the daemon kills it, where before its own timeout held it at 45 min.
   - **None of the 5 queued briefs is like that** (P3).
4. **A runtime line with no number is refused with the right reason.** It was refused before too, under the wrong one.
   - **The one behaviour change:** a micro-fire brief whose runtime line has no number used to pass and run on the default. It is now refused (`A2 RUNTIME`).
   - None in the corpus.
5. **A brief that says `## Isolated deps: true`:**
   - **Yorsie / ai-foundation:** the route worktree gets its own trees.
   - **Every repo with a `test_cmd`:** the unit-baseline worktree gets its own trees.
   - **Cost:** two installs per route, out of the wall's 900 s slack (Found-and-LEFT 4).
   - **Single-stream repos:** the route itself still runs in the main checkout (Found-and-LEFT 3).
   - A build that fails refuses the route (exit 2, `⛔ ROUTE WORKTREE — isolated deps: …`). In the baseline it gives BLOCKED(environment). It never links instead.
6. **Nothing changes for a brief without the header**, apart from the log line in item 2: same links, same log lines, same teardown.
