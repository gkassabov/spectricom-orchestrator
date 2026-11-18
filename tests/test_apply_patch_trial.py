# filename: tests/test_apply_patch_trial.py
"""Tests for ORCH-APPLY-PATCH-1 (S7-CORE-55, Kanban row 735) — SD-1 "Build each change once": George 2026-11-16 17:40
"approved" (trial on the next five small changes off protected areas; what lands is the patch the author's dry run built
and the verifier checked), conditions 17:52 "Yes" (1: a fresh verifier reviews any change its reviewer helped write,
G-17; 2: the apply step refuses a change to any test not granted in the brief).

A queue file with `## Apply patch: <path> <sha256>` builds no executor command. The fire checks the sha256, refuses a
patch on a never-autonomous path (OPX-3 list), outside ALLOWED FILES, or changing an existing test file no GRANT line
under `## RULE #8` names; refuses unless a `## Verify report:` report names the patch's sha256, a verifier other than
the `## Patch author:`, "Wrote any of this change: no" and a READY verdict; caps the trial at APPLY_TRIAL_CAP routes.
Then it cuts the route branch from the merge target, `git apply --index`es the exact patch, writes the handback,
commits, and the normal gate decides the landing.

  P-1  a cleared patch lands with no executor; a red gate does not merge; a stale patch is refused   (TestP1*)
  P-2  scope: protected path, outside ALLOWED FILES, sha256, /tmp, malformed, unjudgeable patch      (TestP2*)
  P-3  condition 2 — a test file the brief does not grant is not changed                             (TestP3*)
  P-4  condition 1 — the verifier is someone else, wrote none of it, said READY                      (TestP4*)
  P-5  the trial: the cap, the ledger, the off switch, the meta-fire lane, a re-gate beside it        (TestP5*)
  P-6  prefire: the same judge, the A2 waiver, the pass line, the header window, the parsers         (TestP6*)
  P-7  r2 — the independent verifier's probes (VERIFY-REPORT-735), each red on r1 and green on r2     (TestP7*)
  P-8  r3 — the verifier's r2 delta minors n-1..n-4, each red on r2 and green on r3                  (TestP8*)
  P-9  r3 (S7-CORE-56) — the author's condition-2 probes C2-a..C2-d, each red on the r3 draft         (TestP9*)
  P-10 r4 (S7-CORE-56) — VERIFY-r3 M-1, m-1, m-3: each red on r3, green on r4                          (TestP10*)

Harness: tests.test_gate_cost's lane (a real repo, the leg commands scripted), as tests.test_regate_gates_only.
"""

import hashlib
import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
import prefire  # noqa: E402
from tests.test_gate_cost import Legs, _activate, _git, _msgs, _repo  # noqa: E402

AUTHOR = "brief-author worker s55-a"
VERIFIER = "verifier s55-v"
TEST_FILE = "src/__tests__/a.test.ts"
BLOCKED_NOTE = "PRE-MERGE GATE: BLOCKED(environment) — sit: rate-limited"


@pytest.fixture
def ap(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    (repo / TEST_FILE).parent.mkdir(parents=True)
    (repo / TEST_FILE).write_text("expect(a).toBe(1);\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "M1 a test")
    _activate(monkeypatch, tmp_path, repo)
    orch = tmp_path / "orch"
    (orch / "state").mkdir(parents=True)
    for name, val in (("IS_META_FIRE", False), ("RUN_PLAYWRIGHT", False), ("PREFIRE_BYPASS", True),
                      ("ORCH_DIR", orch), ("RUNNING_FILE", orch / "running.json"), ("WORKTREE_MODE", "single-stream")):
        monkeypatch.setattr(orchestrator, name, val)
    monkeypatch.setattr(orchestrator, "get_migrations", lambda: set())
    monkeypatch.setattr(orchestrator, "notify", lambda r: None)
    monkeypatch.setattr(orchestrator, "find_unblocked", lambda *a, **k: [])
    monkeypatch.setattr(orchestrator.rate_limiter, "record", lambda *a, **k: None)
    monkeypatch.setattr(prefire, "APPLY_TEMP_ROOTS", ())        # pytest's tmp_path is under /tmp (P-2 tests the root)
    monkeypatch.setattr(prefire, "APPLY_TMPDIR_ENV", None, raising=False)   # … and $TMPDIR (P-7 tests it)
    for var in ("ORCH_APPLY_PATCH", "ORCH_REGATE_GATES_ONLY", "PREFIRE_OPEX"):
        monkeypatch.delenv(var, raising=False)
    fired = []

    def no_executor(*a, **k):
        fired.append(a)
        raise AssertionError("the executor command was built")
    for fn in ("fire_toni", "toni_child_env", "toni_guards"):
        monkeypatch.setattr(orchestrator, fn, no_executor)

    class R:
        pass
    r = R()
    r.repo, r.tmp, r.fired, r.monkeypatch, r.orch = repo, tmp_path, fired, monkeypatch, orch
    r.eos = tmp_path / "eos"
    r.eos.mkdir()
    r.legs = Legs(monkeypatch)
    r.ledger = orch / "state" / orchestrator.APPLY_TRIAL_LEDGER

    def patch(write=None, delete=(), rename=(), name="x.patch"):
        """A `git diff` of one commit off main, saved outside the repo; (path, sha256)."""
        _git(repo, "checkout", "-q", "-b", "author-build", "main")
        for rel, text in (write or {}).items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(text)
        for rel in delete:
            _git(repo, "rm", "-q", rel)
        for old, new in rename:
            (repo / new).parent.mkdir(parents=True, exist_ok=True)
            _git(repo, "mv", old, new)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "author build")
        diff = subprocess.run(["git", "-C", str(repo), "diff", "-M", "main", "author-build"], capture_output=True,
                              text=True).stdout
        _git(repo, "checkout", "-q", "main")
        _git(repo, "branch", "-qD", "author-build")
        p = r.eos / name
        p.write_text(diff)
        return p, hashlib.sha256(p.read_bytes()).hexdigest()
    r.patch = patch

    def report(sha, verifier=VERIFIER, wrote="no", verdict="READY-with-minors (0B/0M/1m)", name="VERIFY-REPORT.md"):
        p = r.eos / name
        lines = [f"# VERIFY-REPORT", "", f"- **Patch sha256:** `{sha}`" if sha else "", f"- **Verifier:** {verifier}"
                 if verifier else "", f"- **Wrote any of this change:** {wrote}" if wrote else "",
                 f"- **Verdict:** {verdict}" if verdict else "", ""]
        p.write_text("\n".join(lines))
        return p
    r.report = report

    def brief(p, sha, rep=None, name="400-x.md", allowed=("src/a.ts", "new `src/__tests__/a-new.test.ts`"),
              grants=(), author=AUTHOR, extra="", line=None):
        rep = r.report(sha) if rep is None else rep
        b = tmp_path / "queue" / name
        b.parent.mkdir(exist_ok=True)
        head = ["#!queue repo=cost-repo", "", "# 400 apply", "## Kanban: SCP_Kanban row 400",
                line if line is not None else f"## Apply patch: {p} {sha}",
                f"## Patch author: {author}" if author else "", f"## Verify report: {rep}" if rep else "",
                "## Test scope: targeted (D-S7CORE30-05)", extra, "", "## ALLOWED FILES",
                " · ".join(a if "`" in a else f"`{a}`" for a in allowed), "", "## RULE #8",
                "- Searches: `git grep -n a -- src/` → `src/a.ts:1`", "- **Grants:** none" if not grants else ""]
        head += list(grants)
        b.write_text("\n".join(head) + "\n")
        return b
    r.brief = brief
    return r


def _run(b):
    return orchestrator.run_batch(b)


def _refused(res, *words):
    assert res.status is orchestrator.Status.FAILED and "APPLY-PATCH REFUSED" in (res.error or ""), res.error
    for w in words:
        assert w in res.error, (w, res.error)


def _untouched(ap, main_before):
    assert _git(ap.repo, "rev-parse", "main") == main_before
    assert ap.legs.calls == [] and ap.fired == []
    assert _git(ap.repo, "status", "--porcelain") == ""
    assert _git(ap.repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert not ap.ledger.exists() or ap.ledger.read_text() == ""


# ═══════════════════════════════════════════════════════
class TestP1Lands:

    def test_a_cleared_patch_lands_with_no_executor_onto_the_current_main(self, ap, caplog):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        (ap.repo / "docs" / "later.md").write_text("later\n")             # main moves on after the author's build
        _git(ap.repo, "add", "-A")
        _git(ap.repo, "commit", "-qm", "later work on main")
        with caplog.at_level(logging.INFO, logger="orch"):
            res = _run(ap.brief(p, sha))
        assert ap.fired == [], "the executor command was never built"
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error
        assert (ap.legs.count("build"), ap.legs.count("sit"), ap.legs.count("unit")) == (1, 1, 1)
        assert (ap.repo / "src" / "a.ts").read_text() == "export const a = 400;\n"
        assert (ap.repo / "docs" / "later.md").exists()
        log = _git(ap.repo, "log", "--format=%s", "main")
        assert f"apply-patch: 400-x — x.patch sha256 {sha[:12]} (ORCH-APPLY-PATCH-1, SD-1 trial 1/5)" in log
        assert any(m.startswith(f"🩹 Apply patch (no executor): x.patch sha256 {sha[:12]} — 1 file(s); SD-1 trial "
                                f"route 1/5; author {AUTHOR}") for m in _msgs(caplog)), _msgs(caplog)

    def test_the_handback_is_written_by_the_orchestrator_and_reads_done(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        _run(ap.brief(p, sha))
        hb = (ap.repo / "briefs" / "400-x.handback.md").read_text()
        assert hb.startswith("## STATUS: DONE\n")
        assert sha in hb and "No executor ran" in hb and AUTHOR in hb and "`src/a.ts` (modified)" in hb
        assert orchestrator.handback_status(ap.repo / "briefs" / "400-x.handback.md").is_stop is False

    def test_the_trial_ledger_counts_the_route(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        _run(ap.brief(p, sha))
        rows = [json.loads(l) for l in ap.ledger.read_text().splitlines()]
        assert [(x["stem"], x["sha256"], x["repo"]) for x in rows] == [("400-x", sha, "cost-repo")]

    def test_a_red_gate_does_not_merge_and_still_counts_in_the_trial(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        ap.legs.out["build"] = (2, "error TS2304: Cannot find name 'x'.\n")
        main_before = _git(ap.repo, "rev-parse", "main")
        res = _run(ap.brief(p, sha))
        assert res.status is not orchestrator.Status.PASSED and ap.fired == []
        assert _git(ap.repo, "rev-parse", "main") == main_before
        assert "PRE-MERGE GATE: FAIL(product)" in _git(ap.repo, "notes", "show", "orch-400-x")
        assert len(ap.ledger.read_text().splitlines()) == 1

    def test_a_patch_that_no_longer_applies_is_refused_and_leaves_main_clean(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        (ap.repo / "src" / "a.ts").write_text("export const a = 999;\n")
        _git(ap.repo, "commit", "-qam", "main changes a.ts too")
        main_before = _git(ap.repo, "rev-parse", "main")
        res = _run(ap.brief(p, sha))
        _refused(res, "does not apply clean on main@", "the author re-bases it")
        _untouched(ap, main_before)
        assert "orch-400-x" not in _git(ap.repo, "branch", "--list", "orch-400-x")
        assert not (ap.repo / "briefs" / "400-x.md").exists()

    def test_a_new_test_file_in_allowed_files_needs_no_grant(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", "src/__tests__/a-new.test.ts": "expect(1);\n"})
        res = _run(ap.brief(p, sha))
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error
        assert (ap.repo / "src" / "__tests__" / "a-new.test.ts").exists()


# ═══════════════════════════════════════════════════════
class TestP2Scope:

    def test_a_never_autonomous_path_is_refused(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", "deploy/run.sh": "echo\n"})
        main_before = _git(ap.repo, "rev-parse", "main")
        res = _run(ap.brief(p, sha, allowed=("src/a.ts", "deploy/run.sh")))
        _refused(res, "never-autonomous path(s) deploy/run.sh (deploy/**)", "George's go by name")
        _untouched(ap, main_before)

    def test_a_path_outside_allowed_files_is_refused(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", "docs/readme.md": "changed\n"})
        main_before = _git(ap.repo, "rev-parse", "main")
        _refused(_run(ap.brief(p, sha)), "outside ALLOWED FILES: docs/readme.md")
        _untouched(ap, main_before)

    def test_a_patch_of_another_sha256_is_refused(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        b = ap.brief(p, sha)
        p.write_text(p.read_text().replace("400", "401"))
        main_before = _git(ap.repo, "rev-parse", "main")
        _refused(_run(b), "not the patch that was verified")
        _untouched(ap, main_before)

    def test_a_patch_under_tmp_is_refused(self, ap):
        ap.monkeypatch.setattr(prefire, "APPLY_TEMP_ROOTS", ("/tmp/",))
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        if not str(p.resolve()).startswith("/tmp/"):
            pytest.skip("tmp_path is not under /tmp here")
        _refused(_run(ap.brief(p, sha)), "under /tmp", "(G-1)")

    @pytest.mark.parametrize("line", ["## Apply patch: x.patch", "## Apply patch: /a/x.patch 0123abcd",
                                      "## Apply patch: "])
    def test_a_malformed_line_is_refused(self, ap, line):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        _refused(_run(ap.brief(p, sha, line=line)), "is not '<path> <sha256 (64 hex)>'")

    def test_a_missing_patch_is_refused(self, ap):
        sha = "0" * 64
        _refused(_run(ap.brief(ap.eos / "gone.patch", sha)), "cannot be read")

    def test_a_patch_that_cannot_be_judged_is_refused(self, ap):
        p = ap.eos / "bin.patch"
        p.write_text("diff --git a/img.png b/img.png\nnew file mode 100644\nGIT binary patch\nliteral 3\n")
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        _refused(_run(ap.brief(p, sha, allowed=("img.png",))), "binary patch is not judged")


# ═══════════════════════════════════════════════════════
class TestP3Tests:

    GRANT = f"- **GRANT 400-G1 — `{TEST_FILE}:1`** the pin moves to 400. Granted: George 2026-11-17 09:01 \"yes\"."

    def test_an_ungranted_change_to_an_existing_test_is_refused(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", TEST_FILE: "expect(a).toBe(400);\n"})
        main_before = _git(ap.repo, "rev-parse", "main")
        res = _run(ap.brief(p, sha, allowed=("src/a.ts", TEST_FILE)))
        _refused(res, f"test file(s) {TEST_FILE} (modified)", "condition 2")
        _untouched(ap, main_before)

    def test_control_the_same_change_lands_when_granted_by_name(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", TEST_FILE: "expect(a).toBe(400);\n"})
        res = _run(ap.brief(p, sha, allowed=("src/a.ts", TEST_FILE), grants=(self.GRANT,)))
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error
        assert (ap.repo / TEST_FILE).read_text() == "expect(a).toBe(400);\n"

    @pytest.mark.parametrize("word", ["ASKED", "OPEN", "pending", "TBD", "OWED", "NOT GRANTED"])
    def test_a_grant_not_yet_given_is_no_grant_and_is_named(self, ap, word):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", TEST_FILE: "expect(a).toBe(400);\n"})
        grant = f"- **GRANT 400-G1 {word} — `{TEST_FILE}:1`** the pin moves to 400. Granted: George 09:01 \"yes\"."
        res = _run(ap.brief(p, sha, allowed=("src/a.ts", TEST_FILE), grants=(grant,)))
        _refused(res, "condition 2", "GRANT line(s) not given")

    def test_a_grant_for_another_test_does_not_cover_this_one(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", TEST_FILE: "expect(a).toBe(400);\n"})
        other = "- **GRANT 400-G1 — `src/__tests__/b.test.ts:1`** Granted: George 2026-11-17 09:01 \"yes\"."
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", TEST_FILE), grants=(other,))), "condition 2")

    def test_a_grant_outside_rule_8_does_not_count(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", TEST_FILE: "expect(a).toBe(400);\n"})
        b = ap.brief(p, sha, allowed=("src/a.ts", TEST_FILE), extra="\n## Notes\n" + self.GRANT)
        _refused(_run(b), "condition 2")

    def test_deleting_or_renaming_an_existing_test_needs_a_grant(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"}, delete=(TEST_FILE,))
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", TEST_FILE))), f"{TEST_FILE} (deleted)")
        p, sha = ap.patch({"src/a.ts": "export const a = 401;\n"}, rename=((TEST_FILE, "src/__tests__/a2.test.ts"),),
                          name="y.patch")
        res = _run(ap.brief(p, sha, name="401-y.md", allowed=("src/a.ts", "src/__tests__/")))
        _refused(res, f"{TEST_FILE} (deleted)")


# ═══════════════════════════════════════════════════════
class TestP4Verifier:

    def _patch(self, ap):
        return ap.patch({"src/a.ts": "export const a = 400;\n"})

    def test_the_author_as_verifier_is_refused(self, ap):
        p, sha = self._patch(ap)
        res = _run(ap.brief(p, sha, rep=ap.report(sha, verifier="Brief-Author  worker S55-A")))
        _refused(res, "is the patch author", "a fresh verifier reviews it (G-17)")

    def test_a_verifier_who_wrote_part_of_the_change_is_refused(self, ap):
        p, sha = self._patch(ap)
        res = _run(ap.brief(p, sha, rep=ap.report(sha, wrote="yes — I rewrote 2 files")))
        _refused(res, "wrote part of this change", "(G-17)")

    def test_control_a_fresh_verifier_beside_one_who_wrote_clears_it(self, ap):
        p, sha = self._patch(ap)
        r1 = ap.report(sha, wrote="yes", name="r1.md")
        r2 = ap.report(sha, verifier="verifier s55-v2", name="r2.md")
        b = ap.brief(p, sha, rep=f"{r1}, {r2}")
        res = _run(b)
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error

    def test_no_verify_report_is_refused(self, ap):
        p, sha = self._patch(ap)
        _refused(_run(ap.brief(p, sha, rep="")), "no '## Verify report:' line")

    def test_a_report_of_another_patch_is_refused(self, ap):
        p, sha = self._patch(ap)
        _refused(_run(ap.brief(p, sha, rep=ap.report("a" * 64))), "names no 'Patch sha256:")

    @pytest.mark.parametrize("verdict", ["NOT READY 0B/1M/0m", ""])
    def test_a_report_that_is_not_ready_is_refused(self, ap, verdict):
        p, sha = self._patch(ap)
        _refused(_run(ap.brief(p, sha, rep=ap.report(sha, verdict=verdict))), "not READY")

    def test_no_wrote_line_is_refused(self, ap):
        p, sha = self._patch(ap)
        _refused(_run(ap.brief(p, sha, rep=ap.report(sha, wrote=""))), "has no 'Wrote any of this change: no'")

    def test_no_patch_author_is_refused(self, ap):
        p, sha = self._patch(ap)
        _refused(_run(ap.brief(p, sha, author="")), "no '## Patch author:' line")

    def test_a_missing_report_file_is_refused(self, ap):
        p, sha = self._patch(ap)
        _refused(_run(ap.brief(p, sha, rep=ap.eos / "nope" / "R.md")), "does not exist")


# ═══════════════════════════════════════════════════════
class TestP5Trial:

    def _ledger(self, ap, stems, sha="0" * 64):
        ap.ledger.write_text("".join(json.dumps({"stem": s, "sha256": sha if s == "400-x" else "0" * 64}) + "\n"
                                     for s in stems))

    def test_the_cap_is_five(self):
        assert orchestrator.APPLY_TRIAL_CAP == 5

    def test_a_sixth_route_is_refused_until_george_extends_it(self, ap):
        self._ledger(ap, ["301-a", "302-b", "303-c", "304-d", "305-e"])
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        main_before = _git(ap.repo, "rev-parse", "main")
        res = _run(ap.brief(p, sha))
        _refused(res, "has had its 5 routes (301-a@0000000, 302-b@0000000, 303-c@0000000, 304-d@0000000, "
                      "305-e@0000000)", "George extends it by name")
        assert _git(ap.repo, "rev-parse", "main") == main_before and ap.legs.calls == [] and ap.fired == []
        assert len(ap.ledger.read_text().splitlines()) == 5

    def test_a_re_fire_of_the_same_patch_is_the_same_trial_route(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        self._ledger(ap, ["301-a", "400-x", "303-c", "304-d", "305-e"], sha=sha)
        res = _run(ap.brief(p, sha))
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error
        assert "SD-1 trial 2/5" in _git(ap.repo, "log", "--format=%s", "main")
        assert [s for s, _ in orchestrator._apply_trial_routes()] == ["301-a", "400-x", "303-c", "304-d", "305-e"]

    def test_an_unreadable_ledger_fails_closed(self, ap):
        ap.ledger.write_text("{not json\n")
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        _refused(_run(ap.brief(p, sha)), "cannot be read", "fails closed")

    def test_off_refuses_the_file(self, ap):
        ap.monkeypatch.setenv("ORCH_APPLY_PATCH", "off")
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        main_before = _git(ap.repo, "rev-parse", "main")
        _refused(_run(ap.brief(p, sha)), "ORCH_APPLY_PATCH=off")
        _untouched(ap, main_before)

    def test_the_meta_fire_lane_is_refused(self, ap):
        ap.monkeypatch.setattr(orchestrator, "IS_META_FIRE", True)
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        _refused(_run(ap.brief(p, sha)), "meta-fire lane does not land a saved patch")

    def test_a_re_gate_line_beside_it_wins_and_the_patch_is_not_applied_again(self, ap, caplog):
        # an applied route, gated BLOCKED(environment): SD-2's automatic re-check adds `## Re-gate of:` to its brief
        _git(ap.repo, "checkout", "-q", "-b", "orch-400-x", "main")
        (ap.repo / "src" / "a.ts").write_text("export const a = 400;\n")
        _git(ap.repo, "commit", "-qam", "apply-patch: 400-x")
        tip = _git(ap.repo, "rev-parse", "HEAD")
        _git(ap.repo, "checkout", "-q", "main")
        _git(ap.repo, "notes", "add", "-f", "-m", BLOCKED_NOTE, tip)
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        b = ap.brief(p, sha, name="400-x-recheck.md", extra=f"## Re-gate of: orch-400-x {tip[:8]}")
        with caplog.at_level(logging.INFO, logger="orch"):
            res = _run(b)
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error
        assert ap.fired == [] and not ap.ledger.exists()
        assert "🩹 the `## Apply patch:` line is not applied again — the re-gate brings the route branch as built" \
            in _msgs(caplog)

    def test_negative_control_a_normal_brief_still_fires_the_executor(self, ap):
        b = ap.tmp / "queue" / "401-y.md"
        b.parent.mkdir(exist_ok=True)
        b.write_text("#!queue repo=cost-repo\n\n# 401\n")
        with pytest.raises(AssertionError, match="executor command was built"):
            _run(b)
        assert ap.fired


# ═══════════════════════════════════════════════════════
class TestP6Prefire:

    def test_prefire_asks_the_same_question(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", "deploy/run.sh": "echo\n"})
        b = ap.brief(p, sha, allowed=("src/a.ts", "deploy/run.sh"))
        fails = prefire.check(b)
        assert any(f.startswith("APPLY ❌ the patch touches never-autonomous path(s) deploy/run.sh") for f in fails)

    def test_a_clean_apply_brief_has_no_a2_or_apply_failure_and_says_so(self, ap, capsys, monkeypatch):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        b = ap.brief(p, sha)
        assert [f for f in prefire.check(b) if f.startswith(("A2", "APPLY"))] == []
        monkeypatch.setattr(prefire, "check", lambda f: [])
        assert prefire.report(b) is True
        out = capsys.readouterr().out
        assert "apply-patch x.patch: A2 sizing floor waived — no executor runs (ORCH-APPLY-PATCH-1)" in out
        assert (f"APPLY ✅ x.patch sha256 {sha[:12]}… — 1 file(s), none protected, all in ALLOWED FILES; 0 test "
                f"edit(s), each granted; verifier '{VERIFIER}' ≠ author '{AUTHOR}'") in out

    def test_a_normal_brief_is_not_judged(self, tmp_path):
        b = tmp_path / "300-x.md"
        b.write_text("## Kanban: SCP_Kanban row 300\n")
        assert prefire.apply_patch_problems(b) == []

    def test_the_apply_and_author_lines_are_in_the_header_window(self, tmp_path):
        b = tmp_path / "300-x.md"
        b.write_text("x" * 6100 + "\n## Apply patch: /a/x.patch " + "0" * 64 + "\n## Patch author: a\n")
        hdr = prefire.header_window_problems(b)
        assert any("'## Apply patch:" in h for h in hdr) and any("'## Patch author:" in h for h in hdr)

    def test_the_clinical_protected_list_is_the_live_one(self, tmp_path):
        patch = tmp_path / "eos" / "c.patch"
        patch.parent.mkdir()
        patch.write_text("diff --git a/src/lib/cds/rule.ts b/src/lib/cds/rule.ts\n--- a/src/lib/cds/rule.ts\n"
                         "+++ b/src/lib/cds/rule.ts\n@@ -1 +1 @@\n-a\n+b\n")
        sha = hashlib.sha256(patch.read_bytes()).hexdigest()
        b = tmp_path / "500-c.md"
        b.write_text(f"#!queue repo=clinical-mp\n## Apply patch: {patch} {sha}\n## ALLOWED FILES\n`src/lib/cds/rule.ts`\n")
        orig = prefire.APPLY_TEMP_ROOTS
        try:
            prefire.APPLY_TEMP_ROOTS = ()
            fails = prefire.apply_patch_problems(b)
        finally:
            prefire.APPLY_TEMP_ROOTS = orig
        assert any("never-autonomous path(s) src/lib/cds/rule.ts (src/lib/cds/**)" in f for f in fails), fails

    def test_patch_files_table(self):
        pf = prefire.patch_files
        assert pf("diff --git a/x.ts b/x.ts\nindex 1..2 100644\n--- a/x.ts\n+++ b/x.ts\n@@ -1 +1 @@\n-a\n+b\n") == \
            ([("x.ts", "modified")], None)
        assert pf("diff --git a/n.ts b/n.ts\nnew file mode 100644\n--- /dev/null\n+++ b/n.ts\n@@ -0,0 +1 @@\n+a\n"
                  "diff --git a/d.ts b/d.ts\ndeleted file mode 100644\n--- a/d.ts\n+++ /dev/null\n@@ -1 +0,0 @@\n-a\n") \
            == ([("n.ts", "added"), ("d.ts", "deleted")], None)
        assert pf("diff --git a/o.ts b/p.ts\nsimilarity index 100%\nrename from o.ts\nrename to p.ts\n") == \
            ([("o.ts", "deleted"), ("p.ts", "added")], None)
        assert pf("diff --git a/x.ts b/x.ts\n@@ -1 +1 @@\n-a\n+diff --git a/y.ts b/y.ts\n")[0] == [("x.ts", "modified")]
        assert pf('diff --git "a/s p.ts" "b/s p.ts"\n')[1].startswith("a quoted or spaced path")
        assert pf("diff --git a/i.png b/i.png\nBinary files a/i.png and b/i.png differ\n")[1] == \
            "a binary patch is not judged"
        assert pf("")[1].startswith("no `diff --git` block")
        assert pf("diff --git a/a.ts b/b.ts\n@@ -1 +1 @@\n-a\n+b\n")[1].startswith("a block whose a/ and b/ paths "
                                                                          "differ")
        assert pf("diff --git a/a.ts b/a.ts\n@@ -1 +1 @@\n-a\n")[1] == "the patch ends inside a hunk"
        assert pf("diff --git a/a.ts b/a.ts\n@@ -1,2 +1,2 @@\n--- x\n+++ y\n a\n")[0] == [("a.ts", "modified")]

    @pytest.mark.parametrize("path,test", [
        ("tests/test_x.py", True), ("src/__tests__/a.test.ts", True), ("src/a.test.tsx", True),
        ("e2e/login.spec.ts", True), ("conftest.py", True), ("vitest.config.ts", True), ("src/lib/test-utils/x.ts", True),
        ("server/__mocks__/m.ts", True), ("pkg/x_test.py", True),
        ("src/a.ts", False), ("src/lib/testimony.ts", False), ("docs/tests.md", False), ("src/latest/a.ts", False)])
    def test_is_test_path_table(self, path, test):
        assert prefire.is_test_path(path) is test

    def test_rule8_grants_reads_only_given_grant_lines_under_rule_8(self, tmp_path):
        b = tmp_path / "b.md"
        b.write_text("## RULE #8 (re-run each search)\n- Searches: `tests/a.py:3`\n- **Grants:** see below\n"
                     "- **GRANT G1 — `tests/b.py:10,12`** Granted: George \"yes\".\n"
                     "- **GRANT G2 ASKED — `tests/c.py:4`** Granted: George\n```\n- GRANT `tests/d.py`\n```\n"
                     "- Searches: `git grep GRANT` → `tests/f.py` Granted: George\n"
                     "## STOP\n- **GRANT G3 — `tests/e.py`**\n")
        granted, pending = prefire.rule8_grants(b)
        assert granted == ["tests/b.py"] and len(pending) == 1 and "G2 ASKED" in pending[0]


# ═══════════════════════════════════════════════════════
# P-7 · r2 — the verifier's probes (`~/_eos/s7core55/verify/735/test_v735_probes.py`, VERIFY-REPORT-735), flipped from
# "the hole is real" to "the hole is closed": each was green as a GAP probe on r1, so each is red on r1 and green on r2.
# ═══════════════════════════════════════════════════════
class TestP7Verifier735:

    GIVEN = "Granted: George 2026-11-17 09:01 \"yes\"."

    def _test_edit(self, ap):
        return ap.patch({"src/a.ts": "export const a = 400;\n", TEST_FILE: "expect(a).toBe(400);\n"})

    # M-1 · a grant counts only on a line that says it was given
    @pytest.mark.parametrize("words", ["requested — awaiting George", "proposed", "needs George's go by name",
                                       "to be granted at the morning card", "draft"])
    def test_M1_a_grant_line_never_given_is_no_grant(self, ap, words):
        p, sha = self._test_edit(ap)
        grant = f"- **GRANT 400-G1 — `{TEST_FILE}:1`** {words}."
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", TEST_FILE), grants=(grant,))), "condition 2",
                 "GRANT line(s) not given")

    def test_M1_a_searches_line_never_grants(self, ap):
        p, sha = self._test_edit(ap)
        search = f"- Searches: `git grep -n GRANT -- src/` → `{TEST_FILE}:1` {self.GIVEN}"
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", TEST_FILE), grants=(search,))), "condition 2")

    # M-2 · the brief's repo must be the fire's
    def test_M2_a_brief_for_another_repo_is_refused(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        b = ap.brief(p, sha)
        b.write_text(b.read_text().replace("#!queue repo=cost-repo", "#!queue repo=yorsie", 1))
        main_before = _git(ap.repo, "rev-parse", "main")
        _refused(_run(b), "the brief names repo yorsie and this fire is for cost-repo")
        _untouched(ap, main_before)

    def test_M2_the_verifiers_clinical_case_is_refused(self, ap, monkeypatch):
        patch = ap.eos / "c.patch"
        patch.write_text("diff --git a/src/lib/cds/rule.ts b/src/lib/cds/rule.ts\nnew file mode 100644\n--- /dev/null\n"
                         "+++ b/src/lib/cds/rule.ts\n@@ -0,0 +1 @@\n+export const r = 1;\n")
        sha = hashlib.sha256(patch.read_bytes()).hexdigest()
        rep = ap.report(sha)
        b = ap.tmp / "queue" / "500-yorsie.md"
        b.parent.mkdir(exist_ok=True)
        b.write_text(f"#!queue repo=yorsie\n## Kanban: SCP_Kanban row 500\n## Apply patch: {patch} {sha}\n"
                     f"## Patch author: {AUTHOR}\n## Verify report: {rep}\n\n## ALLOWED FILES\n`src/lib/cds/rule.ts`\n"
                     f"\n## RULE #8\n- **Grants:** none\n")
        monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "clinical-mp")
        spec, why = orchestrator._applypatch_check(b)
        assert spec is None and "names repo yorsie" in why, why

    # M-3 · the cap counts distinct (stem, sha256) pairs
    def test_M3_a_reused_stem_with_a_new_patch_takes_a_new_slot(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        res = _run(ap.brief(p, sha))
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error
        with ap.ledger.open("a") as f:
            for s in ("302-b", "303-c", "304-d", "305-e"):
                f.write(json.dumps({"stem": s, "sha256": "0" * 64}) + "\n")
        q, sha2 = ap.patch({"src/a.ts": "export const a = 999;\n"}, name="y.patch")
        main_before = _git(ap.repo, "rev-parse", "main")
        _refused(_run(ap.brief(q, sha2)), "has had its 5 routes")
        assert _git(ap.repo, "rev-parse", "main") == main_before
        assert (ap.repo / "src" / "a.ts").read_text() == "export const a = 400;\n"

    # m-1 · a new conftest.py, a runner config or package.json needs a grant
    @pytest.mark.parametrize("rel", ["tests/conftest.py", "src/conftest.py", "pytest.ini", "pyproject.toml",
                                     "package.json", "vitest.config.ts"])
    def test_m1_a_new_conftest_or_runner_config_needs_a_grant(self, ap, rel):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", rel: "x = 1\n"})
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", rel))), f"{rel} (added)", "condition 2")

    def test_m1_control_a_granted_new_conftest_lands(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", "tests/conftest.py": "import pytest\n"})
        grant = f"- **GRANT 400-G2 — `tests/conftest.py`** a fixture for the new test. {self.GIVEN}"
        res = _run(ap.brief(p, sha, allowed=("src/a.ts", "tests/conftest.py"), grants=(grant,)))
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error

    # m-2 · a traditional ---/+++ block after a git block is caught at prefire, not only at the fire
    def test_m2_prefire_sees_a_traditional_block_after_a_git_block(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        p.write_text(p.read_text() + "--- a/docs/readme.md\n+++ b/docs/readme.md\n@@ -1 +1 @@\n-docs\n+smuggled\n")
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        assert prefire.patch_files(p.read_text())[1].startswith("a `--- a/docs/readme.md` header outside")
        assert any("cannot be judged" in f for f in prefire.apply_patch_problems(ap.brief(p, sha)))

    # m-3 · "Wrote any of this change:" is exactly `no`
    @pytest.mark.parametrize("wrote", ["not sure", "no — except I fixed two of its tests", "nominally"])
    def test_m3_wrote_must_be_exactly_no(self, ap, wrote):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        _refused(_run(ap.brief(p, sha, rep=ap.report(sha, wrote=wrote))), "exactly `no`")

    # m-4 · a NOT READY report on the patch refuses, whatever another report says
    def test_m4_a_not_ready_report_beside_a_ready_one_refuses(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        r1 = ap.report(sha, name="ok.md")
        r2 = ap.report(sha, verifier="verifier s55-v3", verdict="NOT READY 1B/0M/0m", name="later.md")
        _refused(_run(ap.brief(p, sha, rep=f"{r1}, {r2}")), "later.md says NOT READY on this patch")

    # m-5 · nothing beyond the patch, the handback and the brief copy lands
    def test_m5_an_untracked_file_in_the_checkout_does_not_land(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        (ap.repo / "src" / "stray.ts").write_text("export const stray = 1;\n")
        res = _run(ap.brief(p, sha))
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error
        assert "src/stray.ts" not in _git(ap.repo, "ls-files").split()
        assert (ap.repo / "src" / "stray.ts").exists(), "left where it was, untracked"
        names = set(_git(ap.repo, "diff", "--name-only", "HEAD~1", "HEAD").split())
        assert names == {"src/a.ts", "briefs/400-x.handback.md", "briefs/400-x.md"}, names

    # m-6 · the bytes hashed are the bytes applied
    def test_m6_a_patch_swapped_after_its_hash_is_not_what_lands(self, ap, monkeypatch):
        evil, _ = ap.patch({"src/a.ts": "export const a = 666;\n"}, name="evil.patch")
        evil_text = evil.read_text()
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        good = p.read_bytes()
        real = hashlib

        class H:
            def __getattr__(self, name):
                return getattr(real, name)

            def sha256(self, b=b"", **k):
                d = real.sha256(b, **k)
                if b == good:
                    p.write_text(evil_text)            # swapped between the hash and the apply
                return d
        monkeypatch.setattr(orchestrator, "hashlib", H())
        res = _run(ap.brief(p, sha))
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error
        assert (ap.repo / "src" / "a.ts").read_text() == "export const a = 400;\n"

    # m-7 · /var/tmp, /dev/shm and $TMPDIR are temporary too
    def test_m7_the_temp_roots(self, ap, monkeypatch):
        monkeypatch.setattr(prefire, "APPLY_TEMP_ROOTS", ("/tmp/", "/var/tmp/", "/dev/shm/"))
        monkeypatch.setattr(prefire, "APPLY_TMPDIR_ENV", "TMPDIR")
        roots = prefire.temp_roots()
        assert str(Path("/var/tmp").resolve()) + "/" in roots and str(Path("/dev/shm").resolve()) + "/" in roots, roots
        monkeypatch.setattr(prefire, "APPLY_TEMP_ROOTS", ())
        monkeypatch.setenv("TMPDIR", str(ap.eos))
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        _refused(_run(ap.brief(p, sha)), "a temporary one (G-1)")

    # m-8 · 727's run-claim check on the reports at the fire (the rig runs with PREFIRE_BYPASS, as --force)
    def test_m8_a_report_claiming_an_unrun_test_outcome_is_refused_at_the_fire(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        rep = ap.report(sha)
        rep.write_text(rep.read_text() + "\n- `tests/test_x.py` holds green.\n")
        _refused(_run(ap.brief(p, sha, rep=rep)), "claims a test outcome with no run result")

    # m-9 · an apply route handed a worktree is refused, never sent to the executor
    def test_m9_an_apply_route_with_a_worktree_is_refused(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        res = orchestrator.run_batch(ap.brief(p, sha), worktree=ap.repo)
        _refused(res, "runs only in the route lane")
        assert ap.fired == []


# ═══════════════════════════════════════════════════════
# P-8 · r3 — the verifier's r2 delta minors (VERIFY-REPORT-735 "r2 delta", n-1..n-4): each red on r2, green on r3
# ═══════════════════════════════════════════════════════
class TestP8Delta735:

    GIVEN = "Granted: George 2026-11-17 09:01 \"yes\"."

    def _commit_main(self, ap, files):
        for rel, text in files.items():
            (ap.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (ap.repo / rel).write_text(text)
        _git(ap.repo, "add", "-A")
        _git(ap.repo, "commit", "-qm", "main: " + ", ".join(files))

    # n-1 · a grant inside an HTML note does not count
    def test_n1_a_grant_inside_an_html_note_is_no_grant(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", TEST_FILE: "expect(a).toBe(400);\n"})
        note = ("<!-- fold note:\n"
                f"- **GRANT 400-G1 — `{TEST_FILE}:1`** the pin moves to 400. {self.GIVEN}\n-->")
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", TEST_FILE), grants=(note,))), "condition 2")

    def test_n1_a_given_marker_forged_inside_an_inline_note_is_no_grant(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", TEST_FILE: "expect(a).toBe(400);\n"})
        grant = f"- **GRANT 400-G1 — `{TEST_FILE}:1`** the pin moves to 400. <!-- {self.GIVEN} -->"
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", TEST_FILE), grants=(grant,))), "condition 2",
                 "GRANT line(s) not given")

    # n-2 · setup files are runner config: by name, and whatever the repo's vite/vitest config names in setupFiles
    def test_n2_a_change_to_test_setup_ts_needs_a_grant(self, ap):
        self._commit_main(ap, {"src/test.setup.ts": "import '@testing-library/jest-dom';\n"})
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", "src/test.setup.ts": "// changed\n"})
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", "src/test.setup.ts"))),
                 "src/test.setup.ts (modified)", "condition 2")

    def test_n2_a_file_the_runner_config_names_in_setupfiles_needs_a_grant(self, ap):
        self._commit_main(ap, {"vite.config.ts": "export default { test: { setupFiles: ['./src/harness/boot.ts'] } };\n",
                               "src/harness/boot.ts": "export {};\n"})
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", "src/harness/boot.ts": "globalThis.x = 1;\n"})
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", "src/harness/boot.ts"))),
                 "src/harness/boot.ts (modified)", "condition 2")

    def test_n2_control_a_granted_setup_file_lands(self, ap):
        self._commit_main(ap, {"src/test.setup.ts": "export {};\n"})
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", "src/test.setup.ts": "// changed\n"})
        grant = f"- **GRANT 400-G3 — `src/test.setup.ts`** one import moves. {self.GIVEN}"
        res = _run(ap.brief(p, sha, allowed=("src/a.ts", "src/test.setup.ts"), grants=(grant,)))
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error

    def test_n2_setup_files_reads_both_forms(self, tmp_path):
        (tmp_path / "vite.config.ts").write_text("test: { setupFiles: './src/test.setup.ts', globals: true }\n")
        (tmp_path / "vitest.config.mts").write_text('setupFiles: ["./a/one.ts", "b/two.ts"],\n')
        assert prefire.setup_files(tmp_path) == ("src/test.setup.ts", "a/one.ts", "b/two.ts")
        assert prefire.setup_files(None) == () and prefire.setup_files(tmp_path / "none") == ()
        assert prefire.is_runner_config("src/setupTests.tsx") and prefire.is_runner_config("x/vitest.setup.ts")

    # n-3 · names compared with punctuation, hyphen/space and zero-width characters aside
    @pytest.mark.parametrize("name", [f"{AUTHOR}.", "brief author worker s55 a", "brief-author​ worker s55-a",
                                      "Brief-Author Worker S55-A!", "brief-author worker﻿ s55-a"])
    def test_n3_the_author_under_another_spelling_is_still_the_author(self, ap, name):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"})
        _refused(_run(ap.brief(p, sha, rep=ap.report(sha, verifier=name))), "is the patch author")

    # n-4 · a patch carrying the route's own handback is refused, and says so
    def test_n4_a_patch_carrying_its_own_handback_is_refused_by_name(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", "briefs/400-x.handback.md": "## STATUS: DONE\n"})
        main_before = _git(ap.repo, "rev-parse", "main")
        res = _run(ap.brief(p, sha, allowed=("src/a.ts", "briefs/400-x.handback.md")))
        _refused(res, "the patch carries briefs/400-x.handback.md", "the orchestrator's to write")
        _untouched(ap, main_before)


# ═══════════════════════════════════════════════════════
# P-9 · r3 (S7-CORE-56) — the author's own condition-2 probes on the r3 draft: snapshots, fixtures, sit/, globalSetup,
# sub-folder runner configs, an unclosed HTML note, the pass line's count. Each red on the draft, green on r3.
# ═══════════════════════════════════════════════════════
class TestP9Condition2Harness:

    GIVEN = "Granted: George 2026-11-17 13:30 \"yes\"."

    def _commit_main(self, ap, files):
        for rel, text in files.items():
            (ap.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (ap.repo / rel).write_text(text)
        _git(ap.repo, "add", "-A")
        _git(ap.repo, "commit", "-qm", "main: " + ", ".join(files))

    @pytest.mark.parametrize("rel", ["src/pages/tabs/__snapshots__/LabsTab.test.tsx.snap",
                                     "src/hooks/__fixtures__/lindqvist.fixture.ts",
                                     "src/lib/llm/fixtures/reply.json",
                                     "sit/journey/l-enrol/invariants.ts"])
    def test_c2a_an_ungranted_change_to_a_snapshot_fixture_or_sit_file_is_refused(self, ap, rel):
        self._commit_main(ap, {rel: "old\n"})
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", rel: "new\n"})
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", rel))), f"{rel} (modified)", "condition 2")

    def test_c2a_control_a_granted_snapshot_lands(self, ap):
        rel = "src/pages/tabs/__snapshots__/LabsTab.test.tsx.snap"
        self._commit_main(ap, {rel: "old\n"})
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", rel: "new\n"})
        grant = f"- **GRANT 400-G4 — `{rel}`** the snapshot moves with the label. {self.GIVEN}"
        res = _run(ap.brief(p, sha, allowed=("src/a.ts", rel), grants=(grant,)))
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error

    @pytest.mark.parametrize("path,test", [
        ("src/x/__snapshots__/A.test.tsx.snap", True), ("a.snap", True), ("src/hooks/__fixtures__/p.ts", True),
        ("scripts/__fixtures__/icd/Code", True), ("src/eval/fixtures/x.json", True), ("src/a.fixture.ts", True),
        ("sit/integration/medplum-harness.ts", True), ("vitest.sit.config.ts", True),
        ("src/visit/a.ts", False), ("src/lib/analytics/productivity/fixtures.ts", False), ("docs/sit.md", False),
        ("src/lib/snapshot.ts", False)])
    def test_c2a_is_test_path_table(self, path, test):
        assert prefire.is_test_path(path) is test

    def test_c2b_a_file_playwright_names_in_globalsetup_needs_a_grant(self, ap):
        self._commit_main(ap, {"playwright.config.ts": "export default { globalSetup: './harness/e2e-boot.ts' };\n",
                               "harness/e2e-boot.ts": "export default async () => {};\n"})
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", "harness/e2e-boot.ts": "// changed\n"})
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", "harness/e2e-boot.ts"))),
                 "harness/e2e-boot.ts (modified)", "condition 2")

    def test_c2b_setup_files_reads_sub_folder_configs_and_every_setup_key(self, tmp_path):
        (tmp_path / "playwright.config.ts").write_text("globalSetup: './harness/g.ts', globalTeardown: 'harness/t.ts'\n")
        (tmp_path / "vitest.sit.config.ts").write_text("setupFilesAfterEnv: ['./sit/env.ts']\n")
        (tmp_path / "server").mkdir()
        (tmp_path / "server" / "vitest.config.ts").write_text("test: { setupFiles: ['./boot.ts'] }\n")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "vitest.config.ts").write_text("setupFiles: './nm.ts'\n")
        got = prefire.setup_files(tmp_path)
        assert set(got) == {"harness/g.ts", "harness/t.ts", "sit/env.ts", "server/boot.ts", "boot.ts"}, got
        assert prefire.is_runner_config("vitest.sit.config.ts") and prefire.is_runner_config("server/vitest.config.ts")
        assert not prefire.is_runner_config("src/lib/config.ts")

    def test_c2c_a_grant_after_an_unclosed_html_note_is_no_grant(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", TEST_FILE: "expect(a).toBe(400);\n"})
        grant = f"<!-- fold note, never closed\n- **GRANT 400-G1 — `{TEST_FILE}:1`** the pin moves to 400. {self.GIVEN}"
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", TEST_FILE), grants=(grant,))), "condition 2")

    def test_c2d_the_pass_line_counts_a_granted_setup_file(self, ap, monkeypatch):
        self._commit_main(ap, {"vite.config.ts": "export default { test: { setupFiles: ['./src/harness/boot.ts'] } };\n",
                               "src/harness/boot.ts": "export {};\n"})
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", "src/harness/boot.ts": "globalThis.x = 1;\n"})
        grant = f"- **GRANT 400-G5 — `src/harness/boot.ts`** one global moves. {self.GIVEN}"
        b = ap.brief(p, sha, allowed=("src/a.ts", "src/harness/boot.ts"), grants=(grant,))
        monkeypatch.setattr(prefire, "_repo_entry", lambda repo: {"project_dir": str(ap.repo)})
        assert "1 test edit(s), each granted" in prefire.apply_patch_summary(b)


# ═══════════════════════════════════════════════════════
# P-10 · r4 (S7-CORE-56) — VERIFY-r3: M-1 (new files the runner loads on its own), m-1 (quoted / old-spelling rename and
# copy headers), m-3 (a GRANT in an indented code block). Each red on r3, green on r4.
# ═══════════════════════════════════════════════════════
class TestP10Verify735r3:

    GIVEN = "Granted: George 2026-11-18 01:00 \"yes\"."

    # M-1 · a new __mocks__ neighbour, a new .pytest.ini, a new tests/__init__.py: refused ungranted at the apply step
    @pytest.mark.parametrize("rel", ["src/utils/__mocks__/x.ts", ".pytest.ini", "tests/.pytest.ini",
                                     "tests/__init__.py", "pytest.toml", ".pytest.toml", "tests/pytest.toml",
                                     "tests/.pytest.toml"])
    def test_M1_a_new_file_the_runner_loads_on_its_own_needs_a_grant(self, ap, rel):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", rel: "x = 1\n"})
        main_before = _git(ap.repo, "rev-parse", "main")
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", rel))), f"{rel} (added)", "condition 2")
        _untouched(ap, main_before)

    def test_M1_control_a_granted_new_mocks_file_lands(self, ap):
        rel = "src/utils/__mocks__/x.ts"
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", rel: "export const x = vi.fn();\n"})
        grant = f"- **GRANT 400-G6 — `{rel}`** a manual mock for the new test. {self.GIVEN}"
        res = _run(ap.brief(p, sha, allowed=("src/a.ts", rel), grants=(grant,)))
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error

    @pytest.mark.parametrize("path,kind,need", [
        ("src/utils/__mocks__/x.ts", "added", True), ("__mocks__/fs.js", "added", True), (".pytest.ini", "added", True),
        ("tests/.pytest.ini", "added", True), ("tests/__init__.py", "added", True), ("tests/a/__init__.py", "added", True),
        ("src/pkg/__init__.py", "added", False), ("tests/test_new.py", "added", False),
        ("src/__tests__/b.test.ts", "added", False), ("src/pkg/__init__.py", "modified", False),
        ("pytest.toml", "added", True), (".pytest.toml", "added", True), ("tests/pytest.toml", "added", True),
        ("tests/.pytest.toml", "added", True)])
    def test_M1_needs_grant_table(self, path, kind, need):
        assert prefire.needs_grant(path, kind) is need

    # m-1 · a quoted rename/copy value is refused; `rename old/new` and `copy to` are read as git reads them
    def test_m1_a_quoted_rename_from_is_refused(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n"}, rename=((TEST_FILE, "src/b.ts"),))
        text = p.read_text()
        assert f"rename from {TEST_FILE}\n" in text
        p.write_text(text.replace(f"rename from {TEST_FILE}\n", f'rename from "{TEST_FILE}"\n'))
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        main_before = _git(ap.repo, "rev-parse", "main")
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", "src/b.ts", TEST_FILE))), "cannot be judged",
                 "a quoted path is not judged")
        _untouched(ap, main_before)

    @pytest.mark.parametrize("line", ['rename to "src/b.ts"', 'copy from "src/a.ts"', 'copy to "src/c.ts"'])
    def test_m1_patch_files_refuses_every_quoted_rename_or_copy_value(self, line):
        text = f"diff --git a/src/a.ts b/src/c.ts\nsimilarity index 100%\n{line}\n"
        assert prefire.patch_files(text) == ([], f"a quoted path is not judged: {line}")

    def test_m1_rename_old_new_and_copy_to_are_read_as_git_reads_them(self):
        old_new = ("diff --git a/src/q.ts b/src/q.ts\nsimilarity index 100%\n"
                   f"rename old {TEST_FILE}\nrename new src/b.ts\n")
        assert prefire.patch_files(old_new) == ([(TEST_FILE, "deleted"), ("src/b.ts", "added")], None)
        copy = "diff --git a/src/a.ts b/src/c.ts\nsimilarity index 100%\ncopy from src/a.ts\ncopy to tests/z.py\n"
        assert prefire.patch_files(copy) == ([("tests/z.py", "added")], None)

    # m-3 · a GRANT inside a 4-space-indented code block is no grant, and is named
    @pytest.mark.parametrize("indent", ["    ", "\t", "  \t"])
    def test_m3_a_grant_in_an_indented_code_block_is_no_grant(self, ap, indent):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", TEST_FILE: "expect(a).toBe(400);\n"})
        grant = f"{indent}- **GRANT 400-G1 — `{TEST_FILE}:1`** the pin moves to 400. {self.GIVEN}"
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", TEST_FILE), grants=("", grant))), "condition 2",
                 "indented 4+ columns, not counted")

    def test_m3_control_the_same_grant_unindented_lands(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", TEST_FILE: "expect(a).toBe(400);\n"})
        grant = f"- **GRANT 400-G1 — `{TEST_FILE}:1`** the pin moves to 400. {self.GIVEN}"
        res = _run(ap.brief(p, sha, allowed=("src/a.ts", TEST_FILE), grants=("", grant)))
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error

    # r5 (VERIFY-r4 m-1) · a ``` indented 4+ spaces inside a fence is content: it does not close the fence
    def test_m1r5_an_indented_fence_line_does_not_end_the_fence_around_a_grant(self, ap):
        p, sha = ap.patch({"src/a.ts": "export const a = 400;\n", TEST_FILE: "expect(a).toBe(400);\n"})
        block = ("```text\n    ```\n"
                 f"- **GRANT 400-G1 — `{TEST_FILE}:1`** the pin moves to 400. {self.GIVEN}\n```")
        main_before = _git(ap.repo, "rev-parse", "main")
        _refused(_run(ap.brief(p, sha, allowed=("src/a.ts", TEST_FILE), grants=("", block))), "condition 2")
        _untouched(ap, main_before)
