# filename: tests/test_prefire_traps_1.py
"""PREFIRE-TRAPS-1 (Kanban 988; S7-CORE-63 Lane P, the prefire traps authors kept hitting).

  T1  (a) a `## Agent policy: … ALLOWED FILES` header line opens no ALLOWED section: the `> note` under it (naming
          `.env` and `config/repos.yaml`) is not read as ALLOWED paths, and OPX-3 asks no George go for it.
  T2  (a) control: every section form the corpus uses still opens one — `## ALLOWED FILES`, `## A2 · ALLOWED FILES (…)`,
          `## 3 · SCOPE / ALLOWED FILES`, `## 2 ALLOWED FILES`, `### B2 · ALLOWED FILES`, `## FILES TO TOUCH · ALLOWED FILES`.
  T3  (b) the whole DRY RUN block pasted inside a ``` fence: still refused (no block outside a fence), and the
          refusal names the heading's line and says to remove the fence.
  T4  (b) heading outside, results inside a fence: still refused (no run result), and the refusal names the lines.
  T5  (b) control: results outside a fence pass; a fenced excerpt beside them changes nothing.
  T6  (c) a dependency named without `@repo` that merged on the other repo: still unmet, and the A11 refusal says
          "`<stem>` IS merged on otherrepo/main (<sha8>) — … named `<stem>@otherrepo`"; with `@otherrepo` it passes.
  T7  (c) control: a dependency merged nowhere gets no hint (the refusal is as before).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import prefire  # noqa: E402
from test_depends_on import World, _route, a11  # noqa: E402
from test_prefire_dryrun_gate import DRY_OK, _canon, brief, dry  # noqa: E402

HEAD = "#!queue model=claude-opus-5-5 effort=high repo=orchestrator\n\n# x\n"


@pytest.fixture
def dry_on(tmp_path, monkeypatch):
    """As test_prefire_dryrun_gate's `on`: a READY row, DRY on, HOME in tmp (T1–T5 only; T6/T7 use World's own)."""
    monkeypatch.setattr(prefire, "REPOS_CONFIG", _canon(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(prefire.DRYRUN_ENV, raising=False)
    (tmp_path / "_eos").mkdir()


def _write(tmp_path: Path, body: str, name: str = "00000999-x-1.md") -> Path:
    p = tmp_path / name
    p.write_text(HEAD + body, encoding="utf-8")
    return p


@pytest.mark.usefixtures("dry_on")
class TestA_HeaderLineIsNotASection:

    def test_t1_agent_policy_header_line_opens_no_section(self, tmp_path):
        body = ("## Agent policy: none — no agent-runtime path in ALLOWED FILES\n"
                "> The executor never reads `.env`; `config/repos.yaml` is read only.\n\n"
                "## ALLOWED FILES\n**New (1):** `tests/test_x.py`\n")
        assert prefire.allowed_paths(_write(tmp_path, body)) == ["tests/test_x.py"]
        for key in ("Predecessor", "George go", "Briefs", "Spec reference"):
            b = _write(tmp_path, body.replace("Agent policy", key))
            assert prefire.allowed_paths(b) == ["tests/test_x.py"], key

    def test_t1b_a_header_line_alone_is_no_allowed_list(self, tmp_path):
        body = "## Agent policy: none — no agent-runtime path in ALLOWED FILES\n> `.env` is never read\n"
        assert prefire.allowed_paths(_write(tmp_path, body)) is None

    @pytest.mark.parametrize("heading", [
        "## ALLOWED FILES", "## A2 · ALLOWED FILES (Part A)", "## 3 · SCOPE / ALLOWED FILES", "## 2 ALLOWED FILES",
        "### B2 · ALLOWED FILES", "## FILES TO TOUCH · ALLOWED FILES", "## A2 · ALLOWED FILES (src/x.ts:12 only)",
        "## **ALLOWED FILES**"])
    def test_t2_every_section_form_still_opens_one(self, tmp_path, heading):
        body = "## Briefs: 1\n\n%s\n- `executor/hooks/x.py`\n\n## STOP\n- `y/z.py`\n" % heading
        assert prefire.allowed_paths(_write(tmp_path, body)) == ["executor/hooks/x.py"], heading


@pytest.mark.usefixtures("dry_on")
class TestB_FencedDryRunIsNamed:

    def test_t3_the_block_inside_a_fence_is_refused_and_located(self, tmp_path):
        b = brief(tmp_path, "\n```\n" + DRY_OK.lstrip("\n") + "```\n")
        fails = dry(prefire.check(b))
        assert len(fails) == 1 and "no '## DRY RUN (pasted)' block" in fails[0], fails
        n = b.read_text().splitlines().index("## DRY RUN (pasted)") + 1
        assert "line %d holds the heading inside a" % n in fails[0] and "remove the fence" in fails[0], fails

    def test_t4_results_inside_a_fence_are_refused_and_located(self, tmp_path):
        body = ("\n## DRY RUN (pasted)\n- Base: orchestrator main 2e062f5\n```\n41 passed, 0 failed, exit 0\n"
                "3348 passed in 257s\n```\n- Reds outside a named RULE #8 grant: none\n")
        b = brief(tmp_path, body)
        fails = dry(prefire.check(b))
        assert len(fails) == 1 and "holds no run result" in fails[0], fails
        lines = b.read_text().splitlines()
        first = lines.index("41 passed, 0 failed, exit 0") + 1
        assert "line(s) %d, %d give results inside a" % (first, first + 1) in fails[0], fails
        assert "paste them as plain lines" in fails[0], fails

    def test_t5_plain_results_pass_and_a_fenced_excerpt_changes_nothing(self, tmp_path):
        assert dry(prefire.check(brief(tmp_path, DRY_OK))) == []
        with_excerpt = DRY_OK.replace("- Reds outside", "```\n$ pytest -q\n41 passed\n```\n- Reds outside")
        assert dry(prefire.check(brief(tmp_path, with_excerpt))) == []


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


class TestC_OtherRepoHint:

    def test_t6_merged_on_the_other_repo_is_named_with_its_at_repo(self, w):
        _route(w.other, "orch-o-00000981-server-green-1")
        (fail,) = a11(prefire.check(w.brief("00000983-gate-1", "00000981-server-green-1")))
        assert "not merged on testrepo/main" in fail, fail
        assert "`00000981-server-green-1` IS merged on otherrepo/main (" in fail, fail
        assert "named `00000981-server-green-1@otherrepo`" in fail, fail
        assert a11(prefire.check(w.brief("00000983-gate-1", "00000981-server-green-1@otherrepo"))) == []

    def test_t7_merged_nowhere_gets_no_hint(self, w):
        w.brief("00000981-server-green-1")                                  # queued, merged nowhere
        (fail,) = a11(prefire.check(w.brief("00000983-gate-1", "00000981-server-green-1")))
        assert "IS merged on" not in fail and "queue/" in fail, fail
