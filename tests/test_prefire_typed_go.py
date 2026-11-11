"""[ORCH-PREFIRE-GO-TYPED-1] Kanban 658, D-S7CORE50-27 — OPX-3: a placeholder, an empty line or a text with no go
evidence in a George go line is no go ("any non-go text reads as no go"). Predicates P-B1..P-B5, P-B7 of
briefs/652-660-orch-prefire-bundle-1.md Part B; P-B6 (corpus) is in the handback."""
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

# Copied verbatim (2026-11-11): this bundle brief's own go line (briefs/652-660-orch-prefire-bundle-1.md:14),
# queue/done/341cfg1-practice-clinical-lists-1.md:14, queue/failed/282c-small-fixes-13.md:11,
# queue/done/487-careplans-layout-1.md:14.
BUNDLE_GO = '## George go: Part A — George 2026-11-10 19:05 "APPROVE: add server/simulation/** to prefire agent-runtime list in the NEXT orchestrator route" (`~/_eos/s7core50/s-sdlc/review-answers.md:29`, prefire gap m6); briefed under George\'s 21:16 go (S7-CORE-50). Part B — George 2026-11-11 07:00, D-S7CORE50-27 ("george_go() must not accept a placeholder on a protected path; any non-go text reads as no go"; Codex v2-119 `:19`). Parts C, D and the bundle of all four — George 2026-11-11 08:03 "go. approve." (D-S7CORE51-02, `~/_eos/s7core51/session-log.md:6,12`) and 08:09 "approve" (`~/_eos/s7core51/session-log.md:15`: two brief-author workers, "652+658+659+660 orchestrator bundle"). Gemma\'s rulings on the four open calls, 2026-11-11 08:3x (S7-CORE-51), are folded into Parts B and C. Rule #8 lines below carry these goes.'
CFG1_GO = '## George go: 2026-11-02 08:46 "Where practice-editable clinical lists live. - agree with recomm" (digest `~/_eos/s7core40/rulings-owed-2026-11-02.md`, 341h1b FL-1 rec (a): a new carrier in the voice-unit idiom; one placement for all three lists, 341h1c FL-1).'
SPEC_282C = '## Spec reference: SCA Bug Registry v1-118 — SCA-GDR-01, -03, -04, -05 (product half), -07, SCA-T1-AITPM-1. George 2026-10-17 14:31 "do all the checks and log the bugs and changes", 14:50 "go do the fixes now". SCA-GDR-02 ruled by George 14:56 (**D-S7CORE31-04**, D7 below). **Not in this route (ruling pending):** SCA-GDR-06 (A&P covers every problem — Dr K).'
GO_487 = '## George go: 2026-10-26 18:54 (George, chat: Care Plans fix tonight) — includes the rule #8 line in §3'


@pytest.fixture(autouse=True)
def canon(tmp_path, monkeypatch):
    d = tmp_path / "canon"
    d.mkdir()
    (d / "SCP_Kanban_v0-1.md").write_text("| # | Item | State |\n|---|---|---|\n| 393 | x | READY |\n")
    cfg = tmp_path / "repos.yaml"
    cfg.write_text(yaml.safe_dump({"kanban_dir": str(d), "repos": {}}))
    monkeypatch.setattr(prefire, "REPOS_CONFIG", cfg)
    monkeypatch.delenv("PREFIRE_OPEX", raising=False)
    return d


def brief(tmp_path, header, allowed="`src/lib/clinical/x.ts`") -> Path:
    p = tmp_path / "b.md"
    p.write_text("#!queue model=claude-opus-5-5 effort=xhigh repo=clinical-mp\n\n# X-1 — fixture\n\n"
                 "## Kanban: SCP_Kanban row 393\n## Estimated runtime: 60-90 min\n## Test scope: targeted (D-S7CORE30-05)\n"
                 + header + "\n" + FIVE + "## 0 · FIRST STEP\nRead.\n\n## 2 · ALLOWED FILES\n%s\n\n## STOP\n(a) x.\n" % allowed,
                 encoding="utf-8")
    return p


def opx3(path: Path) -> prefire.OpexVerdict:
    return prefire.check_george_go(path, prefire.allowed_paths(path))


def refused(text: str, why: str) -> str:
    return ("OPX-3 ❌ NEVER-AUTONOMOUS — ALLOWED FILES name protected path(s) src/lib/clinical/x.ts "
            "(src/lib/clinical/**) and the brief's George go is not a go: '%s' (%s) — any non-go text reads as no go "
            "(D-S7CORE50-27)" % (text[:80], why))


# ── P-B1 · an OWED go line is refused, with the reason ──────────────────────
def test_PB1_owed_go_line_is_refused_naming_the_placeholder(tmp_path):
    h = "## George go: OWED — George's go needed before enqueue"
    b = brief(tmp_path, h + "\n")
    v = opx3(b)
    assert not v.ok and v.line == refused(h, "placeholder 'OWED'")
    assert v.line in prefire.check(b)
    assert prefire.george_go(b) is None and prefire.george_go_verdict(b) == (None, "placeholder 'OWED'")


# ── P-B2 · every placeholder shape, template marker and empty line ─────────
@pytest.mark.parametrize("text, why", [
    ("pending", "placeholder 'pending'"), ("TBD", "placeholder 'TBD'"), ("TBC", "placeholder 'TBC'"),
    ("TODO — ask George", "placeholder 'TODO'"), ("awaiting George", "placeholder 'awaiting'"),
    ("not yet given", "placeholder 'not yet'"), ("to be asked at EOS", "placeholder 'to be asked'"),
    ("<George's words>", "template marker '<George's words>'"), ("{go}", "template marker '{go}'"),
    ("?", "placeholder '?'"), ("n/a", "placeholder 'n/a'"), ("", "empty")])
def test_PB2_each_non_go_text_is_refused_with_its_reason(tmp_path, text, why):
    h = ("## George go: " + text).rstrip() if text else "## George go:"
    v = opx3(brief(tmp_path, h + "\n"))
    assert not v.ok and v.line == refused(h, why)


# ── P-B3 · the fallback's clause is judged too ──────────────────────────────
@pytest.mark.parametrize("header", ["## Briefs: 1 (George go OWED)", "## Briefs: 1 (George go) OWED"])
def test_PB3_fallback_clause_with_a_placeholder_is_refused(tmp_path, header):
    v = opx3(brief(tmp_path, header + "\n"))
    assert not v.ok and v.line.endswith("(placeholder 'OWED') — any non-go text reads as no go (D-S7CORE50-27)")


# ── P-B4 · every go line must pass ──────────────────────────────────────────
def test_PB4_a_later_owed_go_line_refuses_the_brief(tmp_path):
    v = opx3(brief(tmp_path, '## George go: 2026-11-11 08:03 "go. approve."\n## George go: OWED (Part B)\n'))
    assert not v.ok and v.line == refused("## George go: OWED (Part B)", "placeholder 'OWED'")


# ── P-B5 · controls: real go shapes pass ────────────────────────────────────
@pytest.mark.parametrize("header", [
    '## George go: 10-23 18:08 "agree"', "## George go: D-S7CORE50-27", '## George go: 10-23 21:1x EOS "Evaluate OpenShell"',
    '## George go: 2026-11-11 07:00 "656 FL-1 preliminary pending Dr K co-sign"',
    "## Spec reference: George T0 10-23 13:45, George 13:47 agreed", BUNDLE_GO, CFG1_GO,
    '## George go: 08:53 "go h2" (digest `~/_eos/s7core40/rulings-owed-2026-11-02.md`)',
    '## George go: 2026-11-11 08:03 "go" — worktree `/tmp/orch-fire-<ts>`, files `server/simulation/{loop,route}.ts`',
    SPEC_282C])
def test_PB5_control_go_shapes_pass(tmp_path, header):
    v = opx3(brief(tmp_path, header + "\n"))
    assert v.ok, v.line


@pytest.mark.parametrize("header", ['## George go: 10-23 18:08 "agree"', BUNDLE_GO, CFG1_GO, SPEC_282C])
def test_PB5_george_go_verdict_says_no_why_not_for_a_go(tmp_path, header):
    b = brief(tmp_path, header + "\n")
    assert prefire.george_go_verdict(b) == (prefire.george_go(b), None) and prefire.george_go(b)


def test_PB5_control_a_briefs_line_go_keeps_its_pass_line(tmp_path):
    v = opx3(brief(tmp_path, "## Briefs: 1 (George go 10-23)\n"))
    assert v.ok and v.line.endswith("— George go: 'George go'")


def test_PB5_control_a_go_line_pass_text_is_the_line(tmp_path):
    v = opx3(brief(tmp_path, '## George go: 10-23 18:08 "agree"\n'))
    assert v.line.endswith("""— George go: '## George go: 10-23 18:08 "agree"'""")


def test_PB5_control_no_protected_path_is_never_judged(tmp_path):
    v = opx3(brief(tmp_path, "## George go: OWED — George's go needed before enqueue\n", allowed="`src/components/x.tsx`"))
    assert v.ok and v.line == "OPX-3 ✅ no never-autonomous path in ALLOWED FILES"


def test_PB5_control_no_go_at_all_keeps_todays_refusal(tmp_path):
    v = opx3(brief(tmp_path, "## Briefs: 1 (one increment)\n"))
    assert v.line == ("OPX-3 ❌ NEVER-AUTONOMOUS — ALLOWED FILES name protected path(s) src/lib/clinical/x.ts "
                      "(src/lib/clinical/**) and the brief carries no George go: a '## George go:' line, or a "
                      "'## Briefs:' / '## Spec reference:' line saying George … go / agreed (D-S7CORE33-20)")


def test_PB5_george_go_verdict_with_no_go_at_all(tmp_path):
    assert prefire.george_go_verdict(brief(tmp_path, "## Briefs: 1 (one increment)\n")) == (None, None)


# ── P-B7 · refused on purpose: a time and George's attribution, no go evidence ──
def test_PB7_the_487_shape_is_no_go(tmp_path):
    v = opx3(brief(tmp_path, GO_487 + "\n"))
    assert not v.ok and v.line == refused(GO_487, "no ruling id, go word or timed quote")


def test_PB7_the_487_shape_with_a_quoted_go_passes(tmp_path):
    v = opx3(brief(tmp_path, GO_487.replace("18:54 ", '18:54 "go" ', 1) + "\n"))
    assert v.ok, v.line


def test_go_text_problem_is_pure():
    assert prefire._go_text_problem('10-23 18:08 "agree"') is None
    assert prefire._go_text_problem("   ") == "empty"
    assert prefire._go_text_problem("2026-10-26 18:54 (George, chat)") == "no ruling id, go word or timed quote"
