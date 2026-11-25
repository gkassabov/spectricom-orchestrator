"""QUEUE-GUARDS-1 (Kanban 954 + 952; D-S7CORE62-04 / -03, George 2026-11-24 12:56 ET "all yes"; L-535, L-536).

`queue_daemon.py enqueue` refuses a brief whose line 1 is not the `#!queue … repo=` header (QHDR — 950r2 was refused
at fire, 11:34) and one whose `## HANDBACK` section names a handback the route cannot find (HBN — 950 and 950r3 merged
green with `handback-status: none`). The names the route finds are orchestrator.route_handback_path's: the stem's own
and its zero-less form.
"""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import prefire  # noqa: E402
import queue_daemon  # noqa: E402

HEAD = "#!queue model=claude-opus-5-5 effort=high repo=orchestrator\n"
BODY = "## Kanban: SCP_Kanban row 1\n## Estimated runtime: 30-45 min\n"


@pytest.fixture
def q(tmp_path, monkeypatch):
    canon = tmp_path / "canon"
    canon.mkdir()
    (canon / "SCP_Kanban_v0-1.md").write_text("| # | Item | State |\n|---|---|---|\n| 1 | x | **READY** |\n")
    cfg = tmp_path / "repos.yaml"
    cfg.write_text(yaml.safe_dump({"kanban_dir": str(canon), "repos": {}}))   # DRY off: the shape guards alone
    orch = tmp_path / "orch"
    queue = orch / "queue"
    for name, val in (("ORCH_DIR", orch), ("QUEUE_DIR", queue), ("QUEUE_DONE", queue / "done"),
                      ("QUEUE_FAILED", queue / "failed"), ("QUEUE_STATE", tmp_path / "queue-state.json"),
                      ("REPOS_CONFIG", cfg)):
        monkeypatch.setattr(queue_daemon, name, val)
    monkeypatch.setattr(prefire, "REPOS_CONFIG", cfg)
    return queue


def brief(tmp_path, text, name="0000000950r3-x-1r3.md") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def enq(path):
    return queue_daemon.QueueDaemon().enqueue(str(path))


class TestQHDR:
    def test_qg1_a_comment_above_the_header_is_refused_and_not_copied_in(self, tmp_path, q):
        p = brief(tmp_path, "<!-- provenance -->\n" + HEAD + BODY)
        r = enq(p)
        assert r["ok"] is False and "QHDR" in r["error"] and "line 1" in r["error"], r
        assert not (q / p.name).exists()

    def test_qg2_a_header_with_no_repo_is_refused(self, tmp_path, q):
        r = enq(brief(tmp_path, "#!queue model=claude-opus-5-5 effort=high\n" + BODY))
        assert r["ok"] is False and "QHDR" in r["error"] and "repo=" in r["error"], r

    def test_qg3_control_the_header_on_line_1_is_copied_in(self, tmp_path, q):
        p = brief(tmp_path, HEAD + BODY)
        assert enq(p)["ok"] is True and (q / p.name).exists()


class TestHBN:
    def test_qg4_a_stale_rerun_name_is_refused(self, tmp_path, q):
        p = brief(tmp_path, HEAD + BODY + "## HANDBACK\n`briefs/0000000950r2-x-1r2.handback.md`: STATUS line.\n")
        r = enq(p)
        assert r["ok"] is False and "HBN" in r["error"] and "0000000950r2-x-1r2.handback.md" in r["error"], r
        assert "briefs/0000000950r3-x-1r3.handback.md" in r["error"] and "briefs/950r3-x-1r3.handback.md" in r["error"]

    def test_qg5_a_wrong_zero_count_is_refused(self, tmp_path, q):
        p = brief(tmp_path, HEAD + BODY + "## HANDBACK\n`briefs/000000950-x-1.handback.md`\n", name="0000000950-x-1.md")
        assert "HBN" in enq(p)["error"]

    @pytest.mark.parametrize("named", ["0000000950r3-x-1r3", "950r3-x-1r3"])
    def test_qg6_control_the_stem_and_its_zero_less_form_pass(self, tmp_path, q, named):
        p = brief(tmp_path, HEAD + BODY + f"## HANDBACK / GATES\nHandback `briefs/{named}.handback.md`: status line.\n")
        assert enq(p)["ok"] is True, enq(p)

    def test_qg7_control_a_handback_named_outside_the_section_or_in_a_fence_is_not_judged(self, tmp_path, q):
        text = (HEAD + BODY + "## CONTEXT\nsee `briefs/0000000886-y.handback.md` (a predecessor)\n"
                "## HANDBACK\n```\nbriefs/old-z.handback.md\n```\n`briefs/950r3-x-1r3.handback.md`\n## RUN COMMAND\n"
                "`briefs/0000000887-w.handback.md`\n")
        assert prefire.handback_name_problems(brief(tmp_path, text)) == []

    def test_qg8_control_a_brief_naming_no_handback_is_not_judged(self, tmp_path, q):
        assert prefire.handback_name_problems(brief(tmp_path, HEAD + BODY)) == []

    def test_qg9_the_names_match_the_routes_own_reader(self, tmp_path, monkeypatch):
        import orchestrator
        monkeypatch.setattr(orchestrator, "ACTIVE_REPO_CONFIG", {"briefs_subdir": "briefs"})
        (tmp_path / "briefs").mkdir()
        for stem in ("0000000950r3-x-1r3", "000000906r-v-1r", "x-no-prefix"):
            for name in prefire.handback_names_ok(stem):
                f = tmp_path / "briefs" / name
                f.write_text("## STATUS: DONE\n")
                assert orchestrator.route_handback_path(tmp_path, stem) == f
                f.unlink()
