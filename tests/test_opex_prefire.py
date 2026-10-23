"""[ORCH-OPEX-PREFIRE-1] D-S7CORE33-20 OPX-1/-2/-3 as prefire A12 (Operability & safety), A13 (agent policy) and
A14 (George go) — predicates P1-P5 of briefs/330c-orch-opex-prefire-1.md, and their controls."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prefire  # noqa: E402
import pytest  # noqa: E402
import yaml  # noqa: E402

FIVE = ("## Operability & safety\n"
        "- **Telemetry:** each new assertion prints one line per brief in prefire output and the fire log.\n"
        "- **Failure mode + degraded path:** an unreadable input fails closed, said on the line.\n"
        "- **Rollback / kill switch:** `PREFIRE_OPEX=off`; revert = one commit.\n"
        "- **Agent permissions (Rule of Two):** n/a — deterministic code, no agent runtime change.\n"
        "- **PHI & protected paths:** none — reads brief text and canon file names only.\n\n")
INVENTORY = ("# SCP Agent Inventory — v0-1\n\n| Policy ID | Agent |\n|---|---|\n"
             "| `AP-DAEMON` | agentic background daemon |\n| `AP-TONI` | executor |\n")


@pytest.fixture(autouse=True)
def canon(tmp_path, monkeypatch):
    """A scratch canon folder whose Kanban has READY rows 1, 390 and 393, and no agent inventory (P3 adds one)."""
    d = tmp_path / "canon"
    d.mkdir()
    (d / "SCP_Kanban_v0-1.md").write_text("| # | Item | State |\n|---|---|---|\n" + "".join(
        "| %d | x | READY |\n" % r for r in (1, 390, 393)))
    cfg = tmp_path / "repos.yaml"
    cfg.write_text(yaml.safe_dump({"kanban_dir": str(d), "repos": {}}))
    monkeypatch.setattr(prefire, "REPOS_CONFIG", cfg)
    monkeypatch.delenv("PREFIRE_OPEX", raising=False)
    return d


def brief(tmp_path, row=393, opex=FIVE, allowed="`src/x.ts`", header="", repo="clinical-mp") -> Path:
    """A brief that passes A1/A2/A8/A9/A10/A11 on `row`, with `opex` as its Operability section and `allowed` (None:
    no section) as its ALLOWED FILES."""
    p = tmp_path / "b.md"
    p.write_text(("#!queue model=claude-opus-5-5 effort=xhigh repo=%s\n\n" % repo if repo else "")
                 + "# X-1 — fixture\n\n## Kanban: SCP_Kanban row %d\n## Estimated runtime: 60-90 min\n"
                   "## Test scope: targeted (D-S7CORE30-05)\n" % row + header + "\n" + opex
                 + "## 0 · FIRST STEP\nRead.\n\n"
                 + ("## 2 · ALLOWED FILES\n%s\n\n" % allowed if allowed is not None else "")
                 + "## STOP\n(a) beyond §1.\n", encoding="utf-8")
    return p


def opex(path: Path) -> dict:
    return {v.line.split()[0]: v for v in prefire.check_opex(path)}


# ── P1 · A12: a row-393 brief carries its Operability & safety section ──────
def test_P1_row_393_without_the_section_is_refused(tmp_path):
    fails = prefire.check(brief(tmp_path, opex=""))
    assert [f for f in fails if f.startswith("A12")] == [
        "A12 ❌ OPERABILITY — row 393 ≥ 393 (D-S7CORE33-20 OPX-1) and the brief has no '## Operability & safety' "
        "section. Five non-empty lines are required — Telemetry: · Failure mode + degraded path: · Rollback / kill "
        "switch: · Agent permissions (Rule of Two): · PHI & protected paths: — 'none' / 'n/a' only with a reason"]
    assert len(fails) == 1, fails


def test_P1_row_393_with_all_five_lines_passes(tmp_path):
    b = brief(tmp_path, allowed="`prefire.py`, `tests/test_opex_prefire.py`")
    assert prefire.check(b) == []
    assert opex(b)["A12"].line == ("A12 ✅ Operability & safety — Telemetry · Failure mode · Rollback · Agent "
                                   "permissions · PHI answered (row 393 ≥ 393)")


def test_P1_telemetry_none_without_a_reason_is_refused(tmp_path):
    b = brief(tmp_path, opex=FIVE.replace("- **Telemetry:** each new assertion prints one line per brief in prefire "
                                          "output and the fire log.", "- **Telemetry:** none"))
    fails = prefire.check(b)
    assert len(fails) == 1 and fails[0].startswith("A12 ❌ OPERABILITY — row 393 ≥ 393"), fails
    assert "is not complete: Telemetry: 'none' with no reason (≥ 3 words after it)" in fails[0]


@pytest.mark.parametrize("answer, ok", [
    ("none", False), ("none.", False), ("None needed", False), ("n/a (none)", False), ("N/A — two words", False),
    ("none — reads brief text only", True), ("n/a: no agent is involved here", True),
    ("Not applicable, no agent involved", True), ("none, because nothing is logged", True),
    ("native log line per fire", True), ("—", False), ("", False),
])
def test_P1_control_none_or_na_needs_three_words_of_reason(tmp_path, answer, ok):
    b = brief(tmp_path, opex=FIVE.replace("n/a — deterministic code, no agent runtime change.", answer))
    assert opex(b)["A12"].ok is ok, opex(b)["A12"].line


def test_P1_control_each_missing_label_is_named(tmp_path):
    b = brief(tmp_path, opex="\n".join(l for l in FIVE.splitlines() if "Rollback" not in l and "PHI" not in l) + "\n")
    line = opex(b)["A12"].line
    assert not opex(b)["A12"].ok and "'## Operability & safety' has no Rollback, PHI line" in line


def test_P1_control_template_heading_wrapped_answer_and_plain_labels_pass(tmp_path):
    text = ("## Operability & safety [REQUIRED]\n\nD-S7CORE33-20 (OPX-1). Five short lines, each answered:\n\n"
            "* Telemetry:\n  one log line per fire, no PHI in it\n"
            "* Failure mode: the fire refuses with a line\n* Rollback: revert one commit\n"
            "* Agent permissions: AP-TONI only; untrusted input + state change\n* PHI: none — synthetic data only here\n\n")
    assert opex(brief(tmp_path, opex=text))["A12"].ok


def test_P1_control_a_label_is_a_whole_word(tmp_path):
    b = brief(tmp_path, opex=FIVE.replace("- **PHI & protected paths:**", "- **Phishing risk:**"))
    assert not opex(b)["A12"].ok and "has no PHI line" in opex(b)["A12"].line


def test_P1_control_an_empty_label_line_is_refused(tmp_path):
    b = brief(tmp_path, opex=FIVE.replace("`PREFIRE_OPEX=off`; revert = one commit.", ""))
    assert not opex(b)["A12"].ok and "Rollback: empty" in opex(b)["A12"].line


def test_P1_control_a_section_after_a_code_fence_heading_is_still_read(tmp_path):
    fenced = FIVE.replace("- **Rollback", "```\n# filename: x.py\n```\n- **Rollback")
    assert opex(brief(tmp_path, opex=fenced))["A12"].ok


# ── P2 · A12: rows below 393 are grandfathered ──────────────────────────────
def test_P2_row_390_without_the_section_is_grandfathered(tmp_path):
    b = brief(tmp_path, row=390, opex="", allowed="`src/components/x.tsx`")
    assert prefire.check(b) == []
    assert opex(b)["A12"] == prefire.OpexVerdict(True, "A12 — grandfathered (row 390 < 393)")


def test_P2_control_no_kanban_row_is_left_to_a1(tmp_path):
    b = brief(tmp_path, opex="")
    b.write_text(b.read_text().replace("## Kanban: SCP_Kanban row 393\n", ""))
    fails = prefire.check(b)
    assert [f[:9] for f in fails] == ["A1 KANBAN"], fails
    assert opex(b)["A12"].line == "A12 — not judged: no Kanban row number (A1 refuses the brief)"


# ── P3 · A13: agent-runtime code is changed under a listed Agent Policy ─────
def test_P3_daemon_path_citing_a_listed_policy_passes(tmp_path, canon):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text(INVENTORY)
    b = brief(tmp_path, allowed="`src/daemon/x.ts` (additive), its `__tests__`", header="## Agent policy: AP-DAEMON\n")
    assert prefire.check(b) == []
    assert opex(b)["A13"].line == ("A13 ✅ agent-runtime path(s) src/daemon/x.ts (src/daemon/**) under AP-DAEMON "
                                   "(SCP_Agent_Inventory_v0-1.md)")


def test_P3_daemon_path_citing_no_listed_policy_is_refused(tmp_path, canon):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text(INVENTORY)
    b = brief(tmp_path, allowed="`src/daemon/x.ts`", header="## Agent policy: AP-NOT-LISTED\n")
    assert prefire.check(b) == [
        "A13 ❌ AGENT-POLICY — ALLOWED FILES name agent-runtime path(s) src/daemon/x.ts (src/daemon/**) and the brief "
        "cites no Agent Policy id that SCP_Agent_Inventory_v0-1.md lists (AP-DAEMON, AP-TONI); cited but not listed: "
        "AP-NOT-LISTED. Cite one, e.g. '## Agent policy: AP-…' (D-S7CORE33-20 OPX-2)"]


def test_P3_no_inventory_warns_and_passes(tmp_path, canon):
    b = brief(tmp_path, allowed="`src/daemon/x.ts`")
    assert prefire.check(b) == []
    assert opex(b)["A13"].line == ("A13 ⚠ agent-runtime path(s) src/daemon/x.ts (src/daemon/**) — no "
                                   "SCP_Agent_Inventory_v*.md in %s yet, so no policy id can be checked: warning, "
                                   "pass (D-S7CORE33-20 OPX-2)" % canon)


def test_P3_control_the_newest_inventory_is_read(tmp_path, canon):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text(INVENTORY)
    (canon / "SCP_Agent_Inventory_v0-10.md").write_text("| `AP-TONI` | executor |\n")
    b = brief(tmp_path, allowed="`src/daemon/x.ts`", header="## Agent policy: AP-DAEMON\n")
    assert not opex(b)["A13"].ok and "SCP_Agent_Inventory_v0-10.md lists (AP-TONI)" in opex(b)["A13"].line


def test_P3_control_an_unreadable_canon_folder_fails_closed(tmp_path, monkeypatch):
    b = brief(tmp_path, allowed="`src/lib/agentic-runtime/tools.ts`", header="## Agent policy: AP-DAEMON\n")
    monkeypatch.setattr(prefire, "kanban_dir", lambda: tmp_path / "no-such-mount")
    v = prefire.check_agent_policy(b, prefire.allowed_paths(b))
    assert not v.ok and "is unreadable, so no policy id can be checked (fails closed)" in v.line


@pytest.mark.parametrize("path", ["src/lib/agentic-runtime/tools.ts", "src/lib/agentic-drafts/draft-queue.ts",
                                  "server/routes/agent-runner.ts", "server/agents/x.ts", "src/daemon/**"])
def test_P3_control_every_clinical_mp_agent_path_is_named(tmp_path, canon, path):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text(INVENTORY)
    assert not opex(brief(tmp_path, allowed="`%s`" % path))["A13"].ok


@pytest.mark.parametrize("allowed", ["`orchestrator.py` (fire command only)", "`executor/hooks/kill_switch.sh`"])
def test_P3_control_the_orchestrator_fire_path_and_executor_need_a_policy(tmp_path, canon, allowed):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text(INVENTORY)
    assert not opex(brief(tmp_path, allowed=allowed, repo="orchestrator"))["A13"].ok
    assert opex(brief(tmp_path, allowed=allowed, repo="orchestrator", header="## Agent policy: AP-TONI\n"))["A13"].ok


# ── P4 · A14: a never-autonomous path is changed only on George's go ────────
def test_P4_cds_path_with_a_briefs_line_george_go_passes(tmp_path):
    b = brief(tmp_path, allowed="`src/lib/cds/x.ts`", header="## Briefs: 1 (George go 10-23)\n")
    assert prefire.check(b) == []
    assert opex(b)["A14"].line == "A14 ✅ never-autonomous path(s) src/lib/cds/x.ts (src/lib/cds/**) — George go: 'George go'"


def test_P4_cds_path_without_a_george_go_is_refused_naming_the_path(tmp_path):
    b = brief(tmp_path, allowed="`src/lib/cds/x.ts`", header="## Briefs: 1 (one increment)\n")
    assert prefire.check(b) == [
        "A14 ❌ NEVER-AUTONOMOUS — ALLOWED FILES name protected path(s) src/lib/cds/x.ts (src/lib/cds/**) and the brief "
        "carries no George go: a '## George go:' line, or a '## Briefs:' / '## Spec reference:' line saying George … "
        "go / agreed (D-S7CORE33-20 OPX-3)"]


@pytest.mark.parametrize("header", ["## George go: 10-23 18:08 \"agree\"\n",
                                    "## Spec reference: George T0 10-23 13:45, George 13:47 agreed\n",
                                    "## Briefs: 1 (George go 10-23 18:15 \"Agree\")\n"])
def test_P4_control_every_go_shape_the_brief_names(tmp_path, header):
    assert opex(brief(tmp_path, allowed="`src/lib/clinical/x.ts`", header=header))["A14"].ok


@pytest.mark.parametrize("header", ["## George go:\n", "## Notes: George go 10-23\n",
                                    "## Briefs: 1 (George asked for this; " + "x" * 80 + " go)\n",
                                    "## Spec reference: George said ago\n"])
def test_P4_control_what_is_not_a_go(tmp_path, header):
    assert not opex(brief(tmp_path, allowed="`src/lib/clinical/x.ts`", header=header))["A14"].ok


@pytest.mark.parametrize("path", ["src/lib/clinical/longevity/x.ts", "src/lib/fhir/mappings.ts", "src/lib/pros/score.ts",
                                  "src/lib/auth/x.ts", "src/components/auth/RoleGate.tsx", "server/auth.ts",
                                  "src/lib/release/member-access-policy.ts", "ClientApplication.ts",
                                  "scripts/migrate-practice-verticals.ts", ".env.example", "vercel.json",
                                  "Dockerfile", ".github/workflows/ci.yml", "src/lib/cds/", "src/**"])
def test_P4_control_every_protected_path_is_named(tmp_path, path):
    assert not opex(brief(tmp_path, allowed="`%s`" % path))["A14"].ok


@pytest.mark.parametrize("path", ["src/components/care-plans/**", "src/lib/clinicalish/x.ts", "scripts/synth-scribe.ts",
                                  "src/lib/environment.ts", "server/allowlist.generated.ts", "negation.ts"])
def test_P4_control_what_is_not_protected(tmp_path, path):
    assert opex(brief(tmp_path, allowed="`%s`" % path))["A14"].ok


def test_P4_control_read_only_and_not_clauses_are_not_edits(tmp_path):
    b = brief(tmp_path, allowed="New: `src/lib/x.ts`. **Not** `src/lib/clinical/y.ts`.\n"
                                "**Read only:** `server/auth.ts`, `member-access-policy.ts`.")
    assert prefire.allowed_paths(b) == ["src/lib/x.ts"]
    assert opex(b)["A14"].ok


def test_P4_control_bare_paths_and_line_suffixes_are_read(tmp_path):
    b = brief(tmp_path, allowed="their tests, src/lib/cds/a.ts, and `src/pages/x.test.tsx:137`.")
    assert prefire.allowed_paths(b) == ["src/lib/cds/a.ts", "src/pages/x.test.tsx"]


def test_P4_control_a_bare_file_name_is_said_to_be_matched_by_name_only(tmp_path):
    line = opex(brief(tmp_path, allowed="`negation.ts`, `check-soap-draft.ts`, their `__tests__`"))["A14"].line
    assert line == ("A14 ✅ no never-autonomous path in ALLOWED FILES (2 named without a directory — matched by file "
                    "name only)")


def test_P4_control_every_allowed_files_section_is_read(tmp_path):
    b = brief(tmp_path, allowed="`src/x.ts`\n\n## 2b · ALLOWED FILES (second brief)\n`src/lib/cds/y.ts`")
    assert not opex(b)["A14"].ok


def test_P4_control_no_repo_is_judged_against_every_list(tmp_path):
    assert not opex(brief(tmp_path, allowed="`executor/x.sh`", repo=None))["A14"].ok


@pytest.mark.parametrize("row, ok", [(393, False), (390, True)])
def test_P4_control_no_allowed_files_section_fails_closed_from_row_393(tmp_path, row, ok):
    v = opex(brief(tmp_path, row=row, allowed=None))
    assert (v["A13"].ok, v["A14"].ok) == (ok, ok), (v["A13"].line, v["A14"].line)


def test_P4_control_an_unreadable_path_list_fails_closed(tmp_path, monkeypatch):
    bad = tmp_path / "paths.json"
    bad.write_text("{not json")
    monkeypatch.setattr(prefire, "OPEX_PATHS", bad)
    v = opex(brief(tmp_path, allowed="`src/x.ts`"))
    assert not v["A13"].ok and not v["A14"].ok
    assert "paths.json unreadable" in v["A14"].line and "(fails closed)" in v["A14"].line


def test_P4_control_the_path_lists_are_data_and_carry_the_briefs_paths():
    data = json.loads(prefire.OPEX_PATHS.read_text(encoding="utf-8"))
    assert {"src/lib/agentic-runtime/**", "src/daemon/**", "src/lib/agentic-drafts/**",
            "server/**/agent*"} <= set(data["agent_runtime"]["clinical-mp"])
    assert {"orchestrator.py", "executor/**"} <= set(data["agent_runtime"]["orchestrator"])
    assert {"src/lib/cds/**", "src/lib/clinical/**", "src/lib/fhir/**", "src/lib/pros/**",
            "scripts/migrat*"} <= set(data["protected"]["clinical-mp"])
    assert {"executor/**", "orchestrator.py"} <= set(data["protected"]["orchestrator"])
    assert "*.env*" in data["protected"]["*"]


# ── P5 · PREFIRE_OPEX=off skips A12-A14, loudly ─────────────────────────────
def test_P5_prefire_opex_off_skips_a12_to_a14_with_a_loud_line(tmp_path, monkeypatch, capsys):
    b = brief(tmp_path, opex="", allowed="`src/lib/cds/x.ts`, `src/daemon/x.ts`")
    assert len(prefire.check(b)) == 2                      # A12 + A14 (no inventory: A13 warns)
    monkeypatch.setenv("PREFIRE_OPEX", "Off")
    assert prefire.check_opex(b) == [] and prefire.check(b) == []
    assert prefire.report(b) is True
    out = capsys.readouterr().out
    assert ("⚠⚠ PREFIRE_OPEX=off — A12/A13/A14 (D-S7CORE33-20 OPX-1/-2/-3: Operability & safety, agent policy, "
            "George go) SKIPPED for b.md. Unset it to turn the OpEx pre-checks back on.") in out
    assert "A12 " not in out.replace("A12/A13/A14", "")


@pytest.mark.parametrize("value", ["", "on", "of", "0"])
def test_P5_control_anything_but_off_keeps_them_on(tmp_path, monkeypatch, value):
    monkeypatch.setenv("PREFIRE_OPEX", value)
    assert [f[:3] for f in prefire.check(brief(tmp_path, opex=""))] == ["A12"]


# ── report: one line per assertion per brief ────────────────────────────────
def test_report_prints_a12_a13_a14_after_the_unchanged_pass_line(tmp_path, capsys):
    assert prefire.report(brief(tmp_path, allowed="`prefire.py`")) is True
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("  Assertions: ✅ A1/A2/A8/A9/A10/A11 pass — SCP_Kanban row 393 READY")
    assert [l.split()[0:2] for l in out[2:]] == [["A12", "✅"], ["A13", "✅"], ["A14", "✅"]]


def test_report_lists_a_refusal_as_a_bullet_and_the_rest_as_lines(tmp_path, capsys):
    assert prefire.report(brief(tmp_path, row=390, allowed="`src/lib/cds/x.ts`")) is False
    out = capsys.readouterr().out
    assert "  • A14 ❌ NEVER-AUTONOMOUS — ALLOWED FILES name protected path(s) src/lib/cds/x.ts" in out
    assert "  A12 — grandfathered (row 390 < 393)\n  A13 ✅ no agent-runtime path in ALLOWED FILES\n" in out
