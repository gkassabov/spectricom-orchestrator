# filename: tests/test_canon_assert.py
"""BOOT-ASSERT-2 — every assertion B1–B9 is shown to FAIL before it is trusted to PASS.

The fixture canon lives in tests/fixtures/canon/ (real shapes, not real content). Each drift
test copies it to tmp_path, builds two tiny git repos so B2/B5 have something live to read,
applies exactly one drift, and asserts that assertion — and only that assertion, where the
drift is separable — goes red with its own id in the text.

`@CLINICAL_HEAD@` / `@ORCH_HEAD@` in the fixture are replaced with the short HEAD of the tmp
repos at materialisation, so the consistent fixture is consistent against git too.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import canon_assert as ca  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "canon"
IDS = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9"]


# ── fixture materialisation ──────────────────────────────────────────────────────────────
def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       check=True, capture_output=True, text=True)
    return r.stdout.strip()


def make_repo(path: Path, unpushed: int) -> str:
    """A repo whose origin/main sits `unpushed` commits behind HEAD. Returns short HEAD."""
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "f").write_text("0")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "base")
    _git(path, "update-ref", "refs/remotes/origin/main", "HEAD")
    for i in range(unpushed):
        (path / "f").write_text(str(i + 1))
        _git(path, "add", ".")
        _git(path, "commit", "-q", "-m", f"c{i + 1}")
    return _git(path, "rev-parse", "--short", "HEAD")


def add_commit(repo: Path) -> str:
    (repo / "f").write_text("more")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "after-handoff")
    return _git(repo, "rev-parse", "--short", "HEAD")


def materialize(tmp_path: Path):
    canon = tmp_path / "canon"
    shutil.copytree(FIXTURE, canon)
    repos = tmp_path / "repos"
    heads = {"@CLINICAL_HEAD@": make_repo(repos / "spectricom-clinical-mp", 3),
             "@ORCH_HEAD@": make_repo(repos / "spectricom-orchestrator", 1)}
    for p in canon.rglob("*.md"):
        t = p.read_text(encoding="utf-8")
        for k, v in heads.items():
            t = t.replace(k, v)
        p.write_text(t, encoding="utf-8")
    return canon, repos


def run(canon: Path, repos: Path):
    verdicts = ca.run(canon, repos)
    text, code = ca.render(verdicts, canon, repos)
    return {v.id: v for v in verdicts}, text, code


def edit(path: Path, old: str, new: str, count: int = 1) -> None:
    t = path.read_text(encoding="utf-8")
    assert old in t, f"fixture drifted: {old!r} not in {path.name}"
    path.write_text(t.replace(old, new, count), encoding="utf-8")


def block(verdict: ca.Verdict) -> str:
    return verdict.render()


# ── the consistent fixture is green, and the summary reconciles ──────────────────────────
def test_consistent_fixture_passes_all_nine_and_exits_zero(tmp_path):
    canon, repos = materialize(tmp_path)
    by, text, code = run(canon, repos)
    assert [v.status for v in by.values()] == ["PASS"] * 9, text
    assert code == 0
    assert "SUMMARY 9 assertions: 9 PASS · 0 FAIL · 0 UNKNOWN" in text


def test_verdict_lines_print_in_id_order_and_summary_reconciles(tmp_path):
    canon, repos = materialize(tmp_path)
    (canon / "hot.md").unlink()                      # some UNKNOWN, some PASS
    _, text, code = run(canon, repos)
    verdict_lines = [l for l in text.splitlines() if re.match(r"^B\d (PASS|FAIL|UNKNOWN)\b", l)]
    assert [l.split()[0] for l in verdict_lines] == IDS
    m = re.search(r"SUMMARY (\d+) assertions: (\d+) PASS · (\d+) FAIL · (\d+) UNKNOWN", text)
    assert m and int(m[1]) == len(verdict_lines) == int(m[2]) + int(m[3]) + int(m[4])
    assert code != 0


# ── B1 ───────────────────────────────────────────────────────────────────────────────────
def test_b1_drift_hot_md_cites_old_registry(tmp_path):
    canon, repos = materialize(tmp_path)
    edit(canon / "hot.md", "Registry **v5-214**", "Registry **v5-213**")
    by, text, _ = run(canon, repos)
    assert by["B1"].status == "FAIL"
    out = block(by["B1"])
    assert "FAIL B1" in out and "v5-214" in out and "v5-213" in out
    assert re.search(r"hot\.md:\d+", out) and "Spectricom_Document_Registry_v5-214.md:1" in out
    assert all(by[i].status == "PASS" for i in IDS if i != "B1"), text


# ── B2 ───────────────────────────────────────────────────────────────────────────────────
def test_b2_drift_route_merged_after_handoff(tmp_path):
    canon, repos = materialize(tmp_path)
    new_head = add_commit(repos / "spectricom-clinical-mp")
    by, _, _ = run(canon, repos)
    assert by["B2"].status == "FAIL"
    out = block(by["B2"])
    assert "FAIL B2" in out and new_head in out and "SCA_Feature_Index_v1-47.md:1" in out and "rev-parse HEAD" in out


def test_b2_unknown_when_feature_index_has_no_anchor(tmp_path):
    canon, repos = materialize(tmp_path)
    edit(canon / "SCA_Feature_Index_v1-47.md", "git-anchor:", "anchor:")
    by, _, code = run(canon, repos)
    assert by["B2"].status == "UNKNOWN" and code != 0


def test_b2_unknown_when_repo_missing(tmp_path):
    canon, repos = materialize(tmp_path)
    shutil.rmtree(repos / "spectricom-clinical-mp")
    by, _, code = run(canon, repos)
    assert by["B2"].status == "UNKNOWN" and code != 0


# ── B3 ───────────────────────────────────────────────────────────────────────────────────
def test_b3_drift_canon_index_lags_sessions(tmp_path):
    canon, repos = materialize(tmp_path)
    edit(canon / "Canon_Index.md", "(**S7-CORE-11, in progress**", "(**S7-CORE-8, in progress**")
    by, text, _ = run(canon, repos)
    assert by["B3"].status == "FAIL"
    out = block(by["B3"])
    assert "FAIL B3" in out and "S7-CORE-8" in out and "S7-CORE-10" in out
    assert "Canon_Index.md:7" in out and "hot.md:1" in out
    assert all(by[i].status == "PASS" for i in IDS if i != "B3"), text


def test_b3_drift_frontmatter_registry_pointer_stale(tmp_path):
    canon, repos = materialize(tmp_path)
    edit(canon / "Canon_Index.md", "Reg **v5-214**", "Reg **v5-212**")
    by, _, _ = run(canon, repos)
    assert by["B3"].status == "FAIL"
    out = block(by["B3"])
    assert "v5-213" in out and "v5-214" in out and "Canon_Index.md:7" in out    # max of what is left is v5-213
    assert by["B1"].status == "FAIL"                                             # the same drift, seen from B1


def test_b3_two_sessions_ahead_is_not_a_successor(tmp_path):
    canon, repos = materialize(tmp_path)
    edit(canon / "Canon_Index.md", "(**S7-CORE-11, in progress**", "(**S7-CORE-12, in progress**")
    by, _, _ = run(canon, repos)
    assert by["B3"].status == "FAIL"


# ── B4 ───────────────────────────────────────────────────────────────────────────────────
def test_b4_drift_pointer_bullet_stale(tmp_path):
    canon, repos = materialize(tmp_path)
    edit(canon / "Canon_Index.md", "[SCA_UAT_Coverage_Matrix_v0-18](SCA_UAT_Coverage_Matrix_v0-18.md)",
         "[SCA_UAT_Coverage_Matrix_v0-17](SCA_UAT_Coverage_Matrix_v0-17.md)")
    by, _, _ = run(canon, repos)
    assert by["B4"].status == "FAIL"
    out = block(by["B4"])
    assert "FAIL B4" in out and "Coverage Matrix" in out and "v0-18" in out and "v0-17" in out
    assert "SCA_UAT_Coverage_Matrix_v0-18.md:1" in out and re.search(r"Canon_Index\.md:\d+", out)
    assert by["B6"].status == "FAIL"        # the bullet now disagrees with the frontmatter too


def test_b4_is_not_fooled_by_the_yorsie_bug_registry(tmp_path):
    canon, repos = materialize(tmp_path)
    edit(canon / "Canon_Index.md", "[Yorsie_Bug_Registry_v1-32](Yorsie_Bug_Registry_v1-32.md)",
         "[Yorsie_Bug_Registry_v1-99](Yorsie_Bug_Registry_v1-99.md)")
    by, text, _ = run(canon, repos)
    assert by["B4"].status == "PASS" and by["B6"].status == "PASS", text


# ── B5 ───────────────────────────────────────────────────────────────────────────────────
def test_b5_drift_repo_moved_after_hot_md_was_written(tmp_path):
    canon, repos = materialize(tmp_path)
    new_head = add_commit(repos / "spectricom-orchestrator")
    by, text, _ = run(canon, repos)
    assert by["B5"].status == "FAIL"
    out = block(by["B5"])
    assert "FAIL B5" in out and "orchestrator" in out and new_head in out and "2 unpushed" in out and "1 unpushed" in out
    assert re.search(r"hot\.md:\d+", out) and "git -C" in out
    assert all(by[i].status == "PASS" for i in IDS if i != "B5"), text


def test_b5_unknown_when_no_origin_to_count_against(tmp_path):
    canon, repos = materialize(tmp_path)
    _git(repos / "spectricom-orchestrator", "update-ref", "-d", "refs/remotes/origin/main")
    by, _, code = run(canon, repos)
    assert by["B5"].status == "UNKNOWN" and code != 0


# ── B6 ───────────────────────────────────────────────────────────────────────────────────
def test_b6_drift_the_s7core11_mechanism_frontmatter_written_body_not(tmp_path):
    canon, repos = materialize(tmp_path)
    ci = canon / "Canon_Index.md"
    edit(ci, "Bugs **v1-41**", "Bugs **v1-42**")            # frontmatter moved on
    edit(ci, "Matrix **v0-18**", "Matrix **v0-19**")        # (Bug Registry v1-41 / Matrix v0-18 stay in the body)
    by, _, _ = run(canon, repos)
    assert by["B6"].status == "FAIL"
    out = block(by["B6"])
    assert "FAIL B6" in out
    for needle in ("Bug Registry", "v1-42", "v1-41", "Coverage Matrix", "v0-19", "v0-18",
                   "frontmatter updated:", "body blockquote", "body bullet", "Canon_Index.md:7"):
        assert needle in out, needle
    assert re.search(r"body blockquote\s+v1-41\s+← Canon_Index\.md:\d+", out)
    assert re.search(r"body bullet\s+v1-41\s+← Canon_Index\.md:\d+", out)


def test_b6_drift_blockquote_refreshed_but_bullet_not(tmp_path):
    canon, repos = materialize(tmp_path)
    edit(canon / "Canon_Index.md", "Kanban **v0-33** · everything else", "Kanban **v0-34** · everything else")
    by, _, _ = run(canon, repos)
    assert by["B6"].status == "FAIL"
    out = block(by["B6"])
    assert "Kanban" in out and "v0-34" in out and "v0-33" in out and "body bullet" in out


def test_b6_unknown_when_body_has_no_blockquote(tmp_path):
    canon, repos = materialize(tmp_path)
    ci = canon / "Canon_Index.md"
    ci.write_text("\n".join(l for l in ci.read_text().splitlines() if not l.startswith(">")) + "\n")
    by, _, code = run(canon, repos)
    assert by["B6"].status == "UNKNOWN" and code != 0


# ── B7 ───────────────────────────────────────────────────────────────────────────────────
def test_b7_drift_hot_md_cites_old_kanban(tmp_path):
    canon, repos = materialize(tmp_path)
    edit(canon / "hot.md", "Kanban **v0-33**", "Kanban **v0-32**")
    by, text, _ = run(canon, repos)
    assert by["B7"].status == "FAIL"
    out = block(by["B7"])
    assert "FAIL B7" in out and "Kanban" in out
    assert re.search(r"Kanban on disk\s+v0-33\s+← SCP_Kanban_v0-33\.md", out)
    assert re.search(r"Kanban hot\.md\s+v0-32\s+← hot\.md:\d+", out)
    assert re.search(r"Kanban Canon_Index\s+v0-33\s+← Canon_Index\.md:\d+", out)
    assert all(by[i].status == "PASS" for i in IDS if i != "B7"), text


def test_b7_drift_new_sdlc_batch_on_disk_uncited(tmp_path):
    canon, repos = materialize(tmp_path)
    (canon / "SCP_SDLC_Decomposition_L_Batch7_v0-1.md").write_text("# SDLC Decomposition — Batch 7 · v0-1\n")
    by, _, _ = run(canon, repos)
    assert by["B7"].status == "FAIL"
    out = block(by["B7"])
    assert "SDLC L Batch7" in out and "not cited" in out and "SCP_SDLC_Decomposition_L_Batch7_v0-1.md" in out
    assert by["B8"].status == "PASS"        # one member — B8 has no opinion on it


def test_b7_family_list_is_derived_from_disk(tmp_path):
    canon, _ = materialize(tmp_path)
    keys = [f.key for f in ca.sdlc_families(canon)]
    assert keys == ["SDLC L Batch1", "SDLC L Batch6", "SDLC PlatformConfig Batch1"]


# ── B8 ───────────────────────────────────────────────────────────────────────────────────
def test_b8_drift_predecessor_survives_beside_successor(tmp_path):
    canon, repos = materialize(tmp_path)
    (canon / "Spectricom_Document_Registry_v5-213.md").write_text("# Spectricom Document Registry — v5-213\n")
    by, text, _ = run(canon, repos)
    assert by["B8"].status == "FAIL"
    out = block(by["B8"])
    assert "FAIL B8" in out and "Spectricom_Document_Registry_v5-214.md" in out and "Spectricom_Document_Registry_v5-213.md" in out
    assert all(by[i].status == "PASS" for i in IDS if i != "B8"), text   # latest() still picks v5-214


def test_b8_old_dir_and_draft_marker_do_not_count(tmp_path):
    canon, repos = materialize(tmp_path)
    assert (canon / "Old" / "Spectricom_Document_Registry_v5-213.md").exists()
    by, _, _ = run(canon, repos)
    assert by["B8"].status == "PASS"
    fams = ca.root_families(canon)
    assert "Spectricom_Product_Roadmap" in fams and "Spectricom_Product_Roadmap_DRAFT" not in fams


# ── B9 ───────────────────────────────────────────────────────────────────────────────────
def test_b9_drift_bak_and_gemma_residue(tmp_path):
    canon, repos = materialize(tmp_path)
    (canon / "hot.md.S7CORE8bak").write_text("old")
    (canon / "Something_v1-0.md.bak").write_text("old")
    (canon / "Spectricom_Pending_Canon_Updates_v1-45_DRAFT_GEMMA.md").write_text("# staging\n")
    by, text, _ = run(canon, repos)
    assert by["B9"].status == "FAIL"
    out = block(by["B9"])
    assert "FAIL B9" in out
    for name in ("hot.md.S7CORE8bak", "Something_v1-0.md.bak", "Spectricom_Pending_Canon_Updates_v1-45_DRAFT_GEMMA.md"):
        assert name in out, name
    assert "Spectricom_Product_Roadmap_v2-12_DRAFT.md" not in out
    assert all(by[i].status == "PASS" for i in IDS if i != "B9"), text


def test_b9_does_not_flag_a_plain_draft(tmp_path):
    canon, repos = materialize(tmp_path)
    assert (canon / "Spectricom_Product_Roadmap_v2-12_DRAFT.md").exists()
    by, _, _ = run(canon, repos)
    assert by["B9"].status == "PASS"
    assert "Roadmap" not in block(by["B9"])


# ── UNKNOWN is never green ───────────────────────────────────────────────────────────────
def test_missing_hot_md_is_unknown_not_pass(tmp_path):
    canon, repos = materialize(tmp_path)
    (canon / "hot.md").unlink()
    by, text, code = run(canon, repos)
    assert code != 0
    for i in ("B1", "B3", "B5", "B7"):
        assert by[i].status == "UNKNOWN", i
    assert "PASS" not in block(by["B1"])
    assert re.search(r"SUMMARY 9 assertions: \d+ PASS · 0 FAIL · 4 UNKNOWN", text)


def test_missing_canon_index_is_unknown_not_pass(tmp_path):
    canon, repos = materialize(tmp_path)
    (canon / "Canon_Index.md").unlink()
    by, _, code = run(canon, repos)
    assert code != 0
    for i in ("B1", "B3", "B4", "B6", "B7"):
        assert by[i].status == "UNKNOWN", i


def test_unparseable_canon_index_is_unknown(tmp_path):
    canon, repos = materialize(tmp_path)
    (canon / "Canon_Index.md").write_text("# Canon Index\n\nno frontmatter at all\n")
    by, _, _ = run(canon, repos)
    assert by["B6"].status == "UNKNOWN" and by["B3"].status == "UNKNOWN"


def test_empty_canon_dir_is_all_unknown(tmp_path):
    canon = tmp_path / "empty"
    canon.mkdir()
    verdicts = ca.run(canon, tmp_path)
    assert [v.status for v in verdicts] == ["UNKNOWN"] * 9
    assert ca.summarize(verdicts)[1] != 0


# ── the CLI, and the path being one source ───────────────────────────────────────────────
def test_cli_exit_code_and_line_count(tmp_path, capsys):
    canon, repos = materialize(tmp_path)
    assert ca.main(["--canon", str(canon), "--repo-root", str(repos)]) == 0
    out = capsys.readouterr().out
    assert len([l for l in out.splitlines() if re.match(r"^B\d ", l)]) == 9
    edit(canon / "hot.md", "Registry **v5-214**", "Registry **v5-213**")
    assert ca.main(["--canon", str(canon), "--repo-root", str(repos)]) == 1


def test_cli_only_filters_assertions(tmp_path, capsys):
    canon, repos = materialize(tmp_path)
    ca.main(["--canon", str(canon), "--repo-root", str(repos), "--only", "B6,B9"])
    out = capsys.readouterr().out
    assert [l.split()[0] for l in out.splitlines() if re.match(r"^B\d ", l)] == ["B6", "B9"]
    assert "SUMMARY 2 assertions" in out


def test_default_canon_dir_is_read_from_doc_sweep():
    text = (Path(__file__).resolve().parents[1] / "doc-sweep.sh").read_text()
    expected = re.search(r'^CANON="([^"]+)"', text, re.M).group(1)
    assert str(ca.default_canon_dir()) == expected == "/mnt/c/Users/gkass/OneDrive/Documents/Spectricom"


def test_orchestrator_py_is_not_imported_or_touched():
    src = Path(ca.__file__).read_text()
    assert "import orchestrator" not in src and "orchestrator.py" not in src
