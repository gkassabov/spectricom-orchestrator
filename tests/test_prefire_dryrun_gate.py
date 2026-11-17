"""ORCH-PREFIRE-DRYRUN-GATE-1 (Kanban 727; D-S7CORE54-63 (3), SD-6(a) George 2026-11-16 17:52 "now, not after T1").

prefire refuses a READY brief with no pasted `## DRY RUN (pasted)` run (DRY) and `queue_daemon.py enqueue` refuses to copy
one in; a verifier report that claims a test outcome with no run beside it is refused (VERIFY, and the CLI
`prefire.py --verify-report`); every `~/_eos/…` input exists and every sha256 is 64 hex and matches (INPUTS).
RETRO-reruns-2026-11-10-to-15 §6 fixes 1, 6, 7.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import prefire  # noqa: E402
import queue_daemon  # noqa: E402

HEAD = ("#!queue model=claude-opus-5-5 effort=high repo=orchestrator\n"
        "## Kanban: SCP_Kanban row 1\n"
        "## Estimated runtime: 30-45 min\n"
        "## Test scope: targeted (D-S7CORE30-05)\n")
DRY_OK = ("\n## DRY RUN (pasted)\n"
          "- Base: orchestrator main 2e062f5 · copy /tmp/dry-x (git clone, branch with the change committed)\n"
          "- Targeted pytest: 41 passed, 0 failed, exit 0 — log /tmp/x.log\n"
          "- Reds outside a named RULE #8 grant: none\n"
          "\n## RUN COMMAND\nrun it\n")
TEMPLATE_BLOCK = ("\n## DRY RUN (pasted)\n"
                  "- Base: <repo> main <sha> · copy /tmp/dry-<id> (git archive) · patch(es): <file sha256> | none\n"
                  "- vitest related (<n> ALLOWED FILES): <f> files, <t> tests, <x> failed — log <path>\n"
                  "- tsc on the new lines: exit <n>\n"
                  "- Reds outside a named RULE #8 grant: none | <list> → NOT READY\n")


def _canon(tmp_path, state="**`READY`**", dryrun="required"):
    canon = tmp_path / "canon"
    canon.mkdir(exist_ok=True)
    (canon / "SCP_Kanban_v0-1.md").write_text(f"| # | Item | State |\n|---|---|---|\n| 1 | x | {state} |\n")
    cfg = tmp_path / "repos.yaml"
    data = {"kanban_dir": str(canon), "repos": {}}
    if dryrun is not None:
        data["prefire_dryrun"] = dryrun
    cfg.write_text(yaml.safe_dump(data))
    return cfg


@pytest.fixture(autouse=True)
def on(tmp_path, monkeypatch):
    """A READY row, DRY on (`prefire_dryrun: required`), HOME in tmp so `~/_eos/…` resolves under it."""
    monkeypatch.setattr(prefire, "REPOS_CONFIG", _canon(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(prefire.DRYRUN_ENV, raising=False)
    (tmp_path / "_eos").mkdir()


def brief(tmp_path, body="", name="00000727-x.md") -> Path:
    p = tmp_path / name
    p.write_text(HEAD + body, encoding="utf-8")
    return p


def dry(fails):
    return [f for f in fails if f.startswith("DRY")]


# ── D-1 · DRY: a READY brief carries its pasted run ─────────────────────────────────────────────────────────────
class TestD1DryRun:

    def test_a_ready_brief_with_no_dry_run_block_is_refused(self, tmp_path):
        fails = prefire.check(brief(tmp_path, "## Repo: orchestrator\n"))
        assert len(dry(fails)) == 1 and "no '## DRY RUN (pasted)' block" in dry(fails)[0], fails
        assert "D-S7CORE54-63" in dry(fails)[0]

    def test_a_block_with_a_run_result_passes(self, tmp_path):
        assert prefire.check(brief(tmp_path, DRY_OK)) == []

    def test_a_block_only_inside_a_code_fence_is_no_block(self, tmp_path):
        fails = prefire.check(brief(tmp_path, "```\n" + DRY_OK + "```\n"))
        assert any("no '## DRY RUN (pasted)' block" in f for f in dry(fails)), fails

    def test_the_template_block_left_unfilled_is_refused_three_ways(self, tmp_path):
        fails = dry(prefire.check(brief(tmp_path, TEMPLATE_BLOCK)))
        assert any("placeholder(s) left unfilled" in f for f in fails), fails
        assert any("holds no run result" in f for f in fails), fails
        assert any("says NOT READY" in f for f in fails), fails

    def test_a_block_that_only_reads_is_refused(self, tmp_path):
        body = ("\n## DRY RUN (pasted)\n- Read orchestrator.py:5739 — the gate looks right.\n"
                "- Reds outside a named RULE #8 grant: none\n")
        fails = dry(prefire.check(brief(tmp_path, body)))
        assert fails and "holds no run result" in fails[0], fails

    def test_a_block_that_says_not_ready_is_refused(self, tmp_path):
        body = DRY_OK.replace("grant: none", "grant: tests/test_x.py:12 → NOT READY")
        fails = dry(prefire.check(brief(tmp_path, body)))
        assert fails and "says NOT READY" in fails[0] and "tests/test_x.py:12" in fails[0], fails

    def test_control_a_conditional_not_ready_is_the_verifiers(self, tmp_path):
        body = DRY_OK.replace("grant: none", "grant: none once G-1 is granted → READY; without G-1 → NOT READY")
        assert dry(prefire.check(brief(tmp_path, body))) == []

    def test_the_block_ends_at_the_next_heading(self, tmp_path):
        body = "\n## DRY RUN (pasted)\n- read only\n\n## Results elsewhere\n- 12 passed, exit 0\n"
        assert any("holds no run result" in f for f in dry(prefire.check(brief(tmp_path, body))))

    @pytest.mark.parametrize("line", ["- full: 2764 passed, 1 skipped, 0 failed (exit 0)",
                                      "- py_compile: exit 0", "- predicates at base: 62 red / 5 passed"])
    def test_each_result_shape_counts(self, tmp_path, line):
        body = f"\n## DRY RUN (pasted)\n{line}\n"
        assert dry(prefire.check(brief(tmp_path, body))) == []

    def test_control_a_row_not_ready_gets_a1_alone(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prefire, "REPOS_CONFIG", _canon(tmp_path, state="PROPOSED"))
        fails = prefire.check(brief(tmp_path, "## Repo: orchestrator\n"))
        assert any(f.startswith("A1") for f in fails) and dry(fails) == [], fails

    def test_control_a_config_without_the_key_judges_as_before(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prefire, "REPOS_CONFIG", _canon(tmp_path, dryrun=None))
        assert prefire.check(brief(tmp_path, "## Repo: orchestrator\n")) == []

    def test_control_the_kill_switch_skips_and_the_fire_says_so(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv(prefire.DRYRUN_ENV, "off")
        b = brief(tmp_path, "## Repo: orchestrator\n")
        assert prefire.check(b) == []
        assert prefire.report(b) is True
        assert "⚠⚠ PREFIRE_DRYRUN=off" in capsys.readouterr().out

    def test_the_fire_report_refuses_and_names_dry(self, tmp_path, capsys):
        assert prefire.report(brief(tmp_path, "## Repo: orchestrator\n")) is False
        out = capsys.readouterr().out
        assert "PRE-FIRE ASSERTIONS FAILED" in out and "DRY ❌ DRY RUN" in out

    def test_the_pass_report_names_the_block_and_its_results(self, tmp_path, capsys):
        assert prefire.report(brief(tmp_path, DRY_OK)) is True
        out = capsys.readouterr().out
        assert "DRY ✅ '## DRY RUN (pasted)' at line" in out and "run-result line(s)" in out, out
        assert "VERIFY ✅ no '## Verify report:' line" in out and "INPUTS ✅" in out


# ── D-2 · enqueue refuses the same brief ────────────────────────────────────────────────────────────────────────
class TestD2Enqueue:

    @pytest.fixture
    def q(self, tmp_path, monkeypatch):
        orch = tmp_path / "orch"
        queue = orch / "queue"
        for name, val in (("ORCH_DIR", orch), ("QUEUE_DIR", queue), ("QUEUE_DONE", queue / "done"),
                          ("QUEUE_FAILED", queue / "failed"), ("QUEUE_STATE", tmp_path / "queue-state.json"),
                          ("REPOS_CONFIG", prefire.REPOS_CONFIG)):
            monkeypatch.setattr(queue_daemon, name, val)
        return queue

    def test_a_brief_with_no_dry_run_is_not_copied_in(self, tmp_path, q):
        r = queue_daemon.QueueDaemon().enqueue(str(brief(tmp_path, "## Repo: orchestrator\n")))
        assert r["ok"] is False and "not enqueued" in r["error"] and "DRY RUN" in r["error"], r
        assert not (q / "00000727-x.md").exists()

    def test_a_brief_with_its_dry_run_is_copied_in(self, tmp_path, q):
        r = queue_daemon.QueueDaemon().enqueue(str(brief(tmp_path, DRY_OK)))
        assert r["ok"] is True and (q / "00000727-x.md").exists(), r

    def test_the_cli_exits_1_on_a_refused_enqueue(self, tmp_path, q, capsys):
        assert queue_daemon.main(["enqueue", str(brief(tmp_path, "## Repo: orchestrator\n"))]) == 1
        assert json.loads(capsys.readouterr().out)["ok"] is False

    def test_control_the_kill_switch_copies_it_in(self, tmp_path, q, monkeypatch):
        monkeypatch.setenv(prefire.DRYRUN_ENV, "off")
        assert queue_daemon.QueueDaemon().enqueue(str(brief(tmp_path, "## Repo: orchestrator\n")))["ok"] is True

    def test_the_switch_is_the_daemons_own_config(self, tmp_path, q, monkeypatch):
        monkeypatch.setattr(queue_daemon, "REPOS_CONFIG", _canon(tmp_path / "x" if (tmp_path / "x").mkdir() is None
                                                                 else tmp_path, dryrun=None))
        assert queue_daemon.QueueDaemon().enqueue(str(brief(tmp_path, "## Repo: orchestrator\n")))["ok"] is True

    def test_control_enqueue_judges_dry_alone(self, tmp_path, q):
        body = DRY_OK + "Input: ~/_eos/missing.patch\n"          # INPUTS is the fire's, not enqueue's
        assert queue_daemon.QueueDaemon().enqueue(str(brief(tmp_path, body)))["ok"] is True


# ── D-3 · VERIFY: run it or don't claim it ──────────────────────────────────────────────────────────────────────
def report(tmp_path, text, name="VERIFY-REPORT-x.md") -> Path:
    p = tmp_path / "_eos" / name
    p.write_text(text, encoding="utf-8")
    return p


class TestD3Verify:

    def test_a_holds_claim_with_no_run_is_refused(self, tmp_path):
        r = report(tmp_path, "## Findings\n- `tests/test_unit_related.py` holds after the patch.\n")
        out = prefire.verify_report_problems(r)
        assert any("line 2 claims a test outcome with no run result" in o for o in out), out
        assert any("claims a run but has no command + exit/count line" in o for o in out), out

    @pytest.mark.parametrize("word", ["unchanged", "keep-green", "green", "still green"])
    def test_each_claim_word_is_judged(self, tmp_path, word):
        r = report(tmp_path, f"- src/a/b.test.ts is {word}.\n")
        assert prefire.verify_report_problems(r), word

    def test_a_claim_with_its_run_in_the_same_bullet_passes(self, tmp_path):
        r = report(tmp_path, "- `tests/test_prelist.py` holds:\n  `python3 -m pytest -q tests/test_prelist.py` → "
                             "18 passed, exit 0\n- next point\n")
        assert prefire.verify_report_problems(r) == []

    def test_a_claim_with_its_run_in_a_fence_below_passes(self, tmp_path):
        r = report(tmp_path, "tests/test_lean_gate.py stays green on r5:\n```\n$ pytest -q tests/test_lean_gate.py\n"
                             "67 passed in 4.1s\n```\n")
        assert prefire.verify_report_problems(r) == []

    def test_a_run_elsewhere_does_not_cover_a_claim_in_another_paragraph(self, tmp_path):
        r = report(tmp_path, "- `pytest -q tests/test_a.py` → 3 passed, exit 0\n\n- tests/test_b.py holds.\n")
        out = prefire.verify_report_problems(r)
        assert len(out) == 1 and "line 3 claims" in out[0], out

    def test_a_quoted_claim_is_a_quotation(self, tmp_path):
        r = report(tmp_path, '- The brief writes "tests/test_x.py holds" with no run — major M-1.\n')
        assert prefire.verify_report_problems(r) == []

    def test_a_report_that_says_it_ran_needs_a_command_and_a_count(self, tmp_path):
        r = report(tmp_path, "I ran the targeted set in a copy; all good.\n")
        out = prefire.verify_report_problems(r)
        assert len(out) == 1 and "claims a run" in out[0], out
        r.write_text("I ran the targeted set in a copy:\n`pytest -q tests/` 2764 passed, exit 0\n")
        assert prefire.verify_report_problems(r) == []

    def test_a_label_is_not_a_claim_and_a_ratio_is_a_result(self, tmp_path):
        r = report(tmp_path, "- Every hit is named, as a grant or as keep-green: `src/a.test.ts`.\n"
                             "- `src/b.test.ts` stays green alone (19/19, run [5]); `npx vitest run src/b.test.ts`\n")
        assert prefire.verify_report_problems(r) == []

    def test_control_a_read_only_report_with_no_claim_passes(self, tmp_path):
        r = report(tmp_path, "## Findings\n- M-1: the brief's A0 line cites the wrong function.\n")
        assert prefire.verify_report_problems(r) == []

    def test_the_brief_header_names_its_report_and_the_fire_judges_it(self, tmp_path):
        r = report(tmp_path, "- tests/test_x.py holds.\n")
        fails = prefire.check(brief(tmp_path, f"## Verify report: {r}\n" + DRY_OK))
        assert any(f.startswith("VERIFY ❌") and "claims a test outcome" in f for f in fails), fails

    def test_a_named_report_that_does_not_exist_is_refused(self, tmp_path):
        fails = prefire.check(brief(tmp_path, "## Verify report: ~/_eos/nope/VERIFY-REPORT-9.md\n" + DRY_OK))
        assert any("does not exist" in f and f.startswith("VERIFY") for f in fails), fails

    def test_a_good_named_report_passes(self, tmp_path):
        r = report(tmp_path, "- tests/test_x.py holds: `pytest -q tests/test_x.py` 4 passed, exit 0\n")
        assert prefire.check(brief(tmp_path, f"## Verify report: {r}\n" + DRY_OK)) == []

    def test_the_cli_refuses_and_passes(self, tmp_path):
        bad = report(tmp_path, "- tests/test_x.py holds.\n", "bad.md")
        good = report(tmp_path, "- tests/test_x.py holds: pytest -q tests/test_x.py 4 passed\n", "good.md")
        run = lambda *a: subprocess.run([sys.executable, str(ROOT / "prefire.py"), "--verify-report", *a],
                                        capture_output=True, text=True, cwd=str(ROOT))
        assert run(str(bad)).returncode == 1 and "VERIFY ⛔ refused" in run(str(bad)).stdout
        assert run(str(good)).returncode == 0

    def test_the_verify_line_is_in_the_header_window(self, tmp_path):
        b = brief(tmp_path, "x" * 6100 + "\n## Verify report: ~/_eos/r.md\n" + DRY_OK)
        assert any(f.startswith("HDR") and "Verify report" in f for f in prefire.check(b))


# ── D-4 · INPUTS: the named `~/_eos/…` inputs exist; each sha256 is 64 hex and matches ─────────────────────────────
class TestD4Inputs:

    def _patch(self, tmp_path, data=b"diff --git a/x b/x\n"):
        p = tmp_path / "_eos" / "s7" / "a.patch"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p, hashlib.sha256(data).hexdigest()

    def inputs(self, tmp_path, line):
        return [f for f in prefire.check(brief(tmp_path, line + "\n" + DRY_OK)) if f.startswith("INPUTS")]

    def test_a_missing_input_is_refused_by_name(self, tmp_path):
        out = self.inputs(tmp_path, "Patch: `~/_eos/s7/never-made.patch`")
        assert len(out) == 1 and "'~/_eos/s7/never-made.patch' (line 5) does not exist" in out[0], out

    def test_a_present_input_with_its_sha256_passes(self, tmp_path):
        _, sha = self._patch(tmp_path)
        assert self.inputs(tmp_path, f"**Patch:** `~/_eos/s7/a.patch` sha256 `{sha}` (16 files)") == []

    def test_a_sha256_that_is_not_64_hex_is_refused(self, tmp_path):
        _, sha = self._patch(tmp_path)
        out = self.inputs(tmp_path, f"Patch `~/_eos/s7/a.patch` sha256 {sha[:63]}")
        assert len(out) == 1 and "is 63 hex, not 64" in out[0], out

    def test_control_an_abbreviated_sha256_is_not_judged(self, tmp_path):
        assert self.inputs(tmp_path, "patch r2 sha256 7c62cffaee374ed4 (abbreviated in prose)") == []

    def test_a_sha256_of_40_hex_is_refused(self, tmp_path):
        out = self.inputs(tmp_path, "patch sha256 " + "a" * 40)
        assert len(out) == 1 and "is 40 hex, not 64" in out[0], out

    def test_a_sha256_is_judged_against_the_nearest_path_before_it(self, tmp_path):
        p, sha = self._patch(tmp_path)
        other = tmp_path / "_eos" / "s7" / "b.py"
        other.write_text("x")
        assert self.inputs(tmp_path, f"`~/_eos/s7/a.patch` sha256 {sha}, then `~/_eos/s7/b.py`") == []
        assert self.inputs(tmp_path, f"`~/_eos/s7/b.py` then `~/_eos/s7/a.patch` sha256 {sha}") == []
        assert self.inputs(tmp_path, f"`~/_eos/s7/a.patch`, then `~/_eos/s7/b.py` sha256 {sha}")

    @pytest.mark.parametrize("line", ["a STOP saves the work as `~/_eos/routeX/x.patch` and commits nothing",
                                      "`~/_eos/routeX/` is an output (the executor's STOP patch dir), not an input",
                                      "<!-- FOLD r1: ~/_eos/s7/gone.md, sha256 " + "b" * 40 + " -->",
                                      "<!-- a note\n~/_eos/s7/gone.md\n-->"])
    def test_an_output_path_and_an_author_note_are_not_judged(self, tmp_path, line):
        assert self.inputs(tmp_path, line) == []

    def test_control_an_input_beside_an_output_is_still_judged(self, tmp_path):
        out = self.inputs(tmp_path, "inputs `~/_eos/s7/never.md`, `~/_eos/s7/never2.md`; "
                                    "a STOP saves it as `~/_eos/routeX/x.patch`")
        assert len(out) == 2 and "never.md" in out[0] and "never2.md" in out[1], out

    def test_a_64_hex_sha256_that_does_not_match_the_file_is_refused(self, tmp_path):
        self._patch(tmp_path)
        out = self.inputs(tmp_path, "Patch `~/_eos/s7/a.patch` sha256 " + "0" * 64)
        assert len(out) == 1 and "does not match" in out[0], out

    @pytest.mark.parametrize("line", ["log `~/_eos/s7/orch-<ts>.log`", "every `~/_eos/s7/*.out`",
                                      "```\n~/_eos/s7/in-a-fence.md\n```", "see ~/_eos/s7/…"])
    def test_placeholders_globs_and_fences_are_not_judged(self, tmp_path, line):
        assert self.inputs(tmp_path, line) == []

    def test_a_line_suffix_and_trailing_dot_are_not_the_path(self, tmp_path):
        p, _ = self._patch(tmp_path)
        assert self.inputs(tmp_path, "at `~/_eos/s7/a.patch:12-14` and ~/_eos/s7/a.patch.") == []

    def test_a_directory_input_is_a_path(self, tmp_path):
        self._patch(tmp_path)
        assert self.inputs(tmp_path, "evidence ~/_eos/s7/") == []
        assert self.inputs(tmp_path, "evidence ~/_eos/s9/")


# ── D-5 · the ruling stays on in the live config (SD-6(b): closed when a check enforces it) ─────────────────────────
def test_D5_the_live_config_requires_the_dry_run():
    live = yaml.safe_load((ROOT / "config" / "repos.yaml").read_text(encoding="utf-8"))
    assert live.get(prefire.DRYRUN_CONFIG_KEY) == prefire.DRYRUN_REQUIRED


def test_D5_the_template_block_shape_is_the_one_judged():
    """The v1-5 block's heading, as Gemma pastes it, is the one DRY reads; a heading with a suffix is not it."""
    assert prefire._DRY_HEADING.match("## DRY RUN (pasted)")
    assert not prefire._DRY_HEADING.match("## DRY RUN (pasted) [REQUIRED — a brief without it is not READY]")
