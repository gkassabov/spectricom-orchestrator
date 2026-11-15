"""[ORCH-PREFIRE-PARSE-HAZARDS-1] Kanban 705 — prefire reads what a brief says, not a stray word.

  T-1 (i)   A1 passes a State cell only when its FIRST word is READY (markdown aside) and it carries no
            MERGED / COMPLETE / CUT; a refused cell is never named READY.
  T-2 (ii)  a '## Micro-fire trigger:' line waives A2's floor only when it begins with P0/P1 and does not negate it;
            an A2 SIZING failure says when the line it saw is not a trigger.
  T-3 (iii) OPX-2 credits only the ids on the brief's '## Agent policy:' line(s) and in its Operability Agent
            permissions answer; a listed id named only elsewhere is said, not credited.
  T-4 (iv)  a header line one of prefire's (6000-char) or admission.parse_brief_timeout's (4000-char) readers cannot
            see is a named HDR refusal; the admission pair's regexes and window have one owner, prefire.

Predicates P-1…P-5 of briefs/000000705-orch-prefire-parse-hazards-1.md. Synthetic briefs and canon only (tmp_path);
REPOS_CONFIG is patched as tests/test_opex_prefire.py does.
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admission  # noqa: E402
import prefire  # noqa: E402

SCOPE = "## Test scope: targeted (D-S7CORE30-05)\n"
RUNTIME = "## Estimated runtime: 60-90 min\n"
NOT_A_TRIGGER = (" The '## Micro-fire trigger:' line is not a trigger: it must begin with P0 or P1 and not negate it "
                 "(ORCH-PREFIRE-PARSE-HAZARDS-1).")
UNDER_FLOOR = ("A2 SIZING — declared estimate 8m is under the 30m floor (System Prompt 5.19.3). Re-scope, bundle per "
               "5.12, or add '## Micro-fire trigger:' naming the P0-infra or P1-safety trigger (5.9).")
FIVE = ("## Operability & safety\n"
        "- **Telemetry:** one prefire line per brief.\n"
        "- **Failure mode + degraded path:** an unreadable input fails closed, said on the line.\n"
        "- **Rollback / kill switch:** revert = one commit.\n"
        "- **Agent permissions (Rule of Two):** %s\n"
        "- **PHI & protected paths:** none — synthetic fixture data only here.\n\n")
NO_AGENT = "n/a — deterministic code, no agent runtime change."

# P-1 / P-1c: row -> State cell (as the canon writes it) and what A1 says of it ("" = passes).
ROWS = {
    10: ("DRAFTING — P1; goes to the front of the queue when READY", "DRAFTING"),
    11: ("DONE `717fb4b6` · was: READY 10:4x", "DONE"),
    12: ("PARTIAL — part A landed `a63cb7eb`; part B READY for authoring", "PARTIAL"),
    13: ("SUPERSEDED by row 362 · was READY", "SUPERSEDED"),
    14: ("`READY-REFIRE`", "READY-REFIRE"),
    15: ("superseded — was READY", "'superseded — was READY'"),
    20: ("**`READY`**", ""),
    21: ("**`READY`** — lands as 341g1 Part B", ""),
    22: ("READY 2026-11-14 — after 698 merges", ""),
    23: ("**`READY`** (600r) — re-authored", ""),
    24: ("**`READY`**, queued", ""),
    25: ("Ready", "'Ready'"),
    26: ("**`READY`** → **`CUT`** (George)", "CUT"),
    27: ("READY — P1, front of the queue (queue file 0701-)", ""),                 # 701 as v0-823 has it
    28: ("DRAFTING — P1; goes to the front of the queue once verified", "DRAFTING"),   # 701 as v0-820 had it
    393: ("**`READY`**", ""),
}
RED_ROWS = (10, 11, 12, 13, 14, 15)


@pytest.fixture(autouse=True)
def canon(tmp_path, monkeypatch):
    """A scratch canon folder (ROWS as SCP_Kanban_v0-1.md, no agent inventory — the P-3 tests add one) named by a
    patched repos.yaml; PREFIRE_OPEX and TONI_TIMEOUT_MIN unset."""
    d = tmp_path / "canon"
    d.mkdir()
    (d / "SCP_Kanban_v0-1.md").write_text(
        "| # | Item | Why | Brief | State | Executor |\n|---|---|---|---|---|---|\n"
        + "".join("| %d | `ITEM-%d` | why | `%d-x.md` | %s | same |\n" % (r, r, r, s) for r, (s, _) in ROWS.items()),
        encoding="utf-8")
    cfg = tmp_path / "repos.yaml"
    cfg.write_text(yaml.safe_dump({"kanban_dir": str(d), "repos": {}}))
    monkeypatch.setattr(prefire, "REPOS_CONFIG", cfg)
    monkeypatch.delenv("PREFIRE_OPEX", raising=False)
    monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)
    return d


def head(row=20, runtime=RUNTIME, scope=SCOPE, kanban=True, extra="", repo="clinical-mp") -> str:
    return (f"#!queue model=claude-opus-5-5 effort=high repo={repo}\n\n# X-1 — fixture\n\n"
            + (f"## Kanban: SCP_Kanban row {row}\n" if kanban else "") + runtime + scope + extra + "\n")


def write(tmp_path, text: str, name="b.md") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def ending_at(prefix: str, line: str, end: int) -> str:
    """`prefix`, a filler line, then `line` placed so that it ends at char `end` (its last char is text[end - 1])."""
    gap = end - len(line) - len(prefix)
    assert gap >= 2, "the prefix is longer than the window"
    return prefix + "x" * (gap - 1) + "\n" + line


def body(**kw) -> str:
    """A brief's body with no header line: a first step and a STOP list."""
    return "## 0 · FIRST STEP\nRead.\n\n## STOP\n(a) beyond §1.\n"


def hdr(line: str, n: int, end: int, reader="prefire", window=6000) -> str:
    return ("HDR ❌ HEADER-WINDOW — '%s' (line %d) ends at char %d, past %s's %d-char header window, so it is not "
            "read. Move it above char %d (ORCH-PREFIRE-PARSE-HAZARDS-1)" % (line.strip()[:60], n, end, reader, window,
                                                                          window))


def line_no(text: str, line: str) -> int:
    """The 1-based number of the LAST line of `text` that is `line` (the past-window copy)."""
    lines = text.split("\n")
    return len(lines) - lines[::-1].index(line)


# ── P-1 · A1 reads the State cell's first word ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("row", RED_ROWS)
def test_P1_a_cell_that_does_not_begin_with_READY_is_refused_and_named(tmp_path, row):
    fails = prefire.check(write(tmp_path, head(row) + body()))
    assert fails == ["A1 KANBAN — SCP_Kanban row %d is %s, not READY" % (row, ROWS[row][1])], fails


@pytest.mark.parametrize("row", [r for r, (_, said) in ROWS.items() if not said and r < 393])
def test_P1c_a_cell_whose_first_word_is_READY_passes(tmp_path, row):
    assert prefire.check(write(tmp_path, head(row) + body())) == []
    assert prefire.check_kanban(write(tmp_path, head(row) + body()))[1].startswith("SCP_Kanban row %d READY" % row)


@pytest.mark.parametrize("row", (25, 26, 28))
def test_P1c_controls_Ready_CUT_and_the_v0_820_701_cell_still_fail(tmp_path, row):
    fails = prefire.check(write(tmp_path, head(row) + body()))
    assert fails == ["A1 KANBAN — SCP_Kanban row %d is %s, not READY" % (row, ROWS[row][1])], fails


@pytest.mark.parametrize("state, word", [
    ("superseded — was READY", "'superseded — was READY'"), ("Ready", "'Ready'"), ("", "empty"),
    ("BACKLOG — after 2 merges", "BACKLOG"), ("READY → CUT", "CUT"), ("was READY, now HELD", "'was READY, now HELD'"),
    ("x" * 70, "'%s'" % ("x" * 60))])
def test_P1c_state_word_never_answers_READY(state, word):
    assert prefire._state_word(state) == word


# ── P-2 · micro-fire: the positive form only ──────────────────────────────────────────────────────────────────
NEGATED = ["none — no P1-safety trigger here", "not P0", "P1-safety: none", "P1 — n/a", "**none**; see P1 row"]
CORPUS_TRIGGERS = ["P0-infra — the queue cannot fire", "P0 infra — this SIT error blocks every gate",
                   "P1-safety — fail-open guard", "P1 — SCA-WND-33 regression", "P1-shaped safety defect in the guard",
                   "P1-shaped privacy defect in the log", "P1 privacy data fix (canon) — not bundled with code",
                   "**P1** clinical-safety defect"]


@pytest.mark.parametrize("value", NEGATED)
def test_P2_a_line_that_does_not_begin_with_P0_P1_or_negates_it_does_not_waive(tmp_path, value):
    p = write(tmp_path, head(runtime="## Estimated runtime: 8 min\n", extra="## Micro-fire trigger: %s\n" % value)
              + body())
    assert prefire.parse_microfire_trigger(p) is None
    assert prefire.check(p) == [UNDER_FLOOR + NOT_A_TRIGGER]


@pytest.mark.parametrize("value", CORPUS_TRIGGERS)
def test_P2c_the_corpus_forms_waive_the_floor(tmp_path, value):
    p = write(tmp_path, head(runtime="## Estimated runtime: 8 min\n", extra="## Micro-fire trigger: %s\n" % value)
              + body())
    assert prefire.parse_microfire_trigger(p) == value
    assert prefire.check(p) == []


def test_P2c_a_bare_line_fails_as_today_and_now_says_why(tmp_path):
    p = write(tmp_path, head(runtime="## Estimated runtime: 8 min\n", extra="## Micro-fire trigger: it is small\n")
              + body())
    fails = prefire.check(p)
    assert fails == [UNDER_FLOOR + NOT_A_TRIGGER]
    assert fails[0].startswith("A2 SIZING — declared estimate 8m ")
    assert prefire.microfire_line(p) == "it is small"


def test_P2c_the_no_runtime_branch_says_it_too(tmp_path):
    p = write(tmp_path, head(runtime="", extra="## Micro-fire trigger: not P0\n") + body())
    fails = prefire.check(p)
    assert len(fails) == 1 and fails[0].startswith("A2 SIZING — no '## Estimated runtime:' declared.")
    assert fails[0].endswith("(5.9)." + NOT_A_TRIGGER)


def test_P2c_without_a_micro_fire_line_the_failure_is_todays(tmp_path):
    p = write(tmp_path, head(runtime="## Estimated runtime: 8 min\n") + body())
    assert prefire.microfire_line(p) is None
    assert prefire.check(p) == [UNDER_FLOOR]


def test_P2c_a_runtime_less_P0_brief_passes_on_the_default_timeout(tmp_path, capsys):
    p = write(tmp_path, head(runtime="", extra="## Micro-fire trigger: P0 infra — the queue is down\n") + body())
    assert prefire.report(p) is True
    out = capsys.readouterr().out
    assert "micro-fire: P0 infra — the queue is down; timeout: none declared — the fire's default" in out


# ── P-3 · OPX-2 credits only the brief's own policy sites ─────────────────────────────────────────────────────
OPX2_REFUSAL = ("OPX-2 ❌ AGENT-POLICY — ALLOWED FILES name agent-runtime path(s) src/daemon/x.ts (src/daemon/**) and the "
                "brief cites no Agent Policy id that SCP_Agent_Inventory_v0-1.md lists (AP-DAEMON, AP-SYNTH)%s. Cite "
                "one, e.g. '## Agent policy: AP-…' (D-S7CORE33-20)")


def inventory(canon, *ids):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text(
        "| Policy ID | Agent |\n|---|---|\n" + "".join("| `%s` | agent |\n" % i for i in ids), encoding="utf-8")


def agent_brief(tmp_path, extra="", permissions=NO_AGENT, middle="", allowed="`src/daemon/x.ts`"):
    return write(tmp_path, head(row=393, extra=extra) + FIVE % permissions + "## 0 · FIRST STEP\nRead.\n\n" + middle
                 + "## 2 · ALLOWED FILES\n%s\n\n## STOP\n(a) beyond §1.\n" % allowed)


def opx2(p: Path) -> prefire.OpexVerdict:
    return prefire.check_agent_policy(p, prefire.allowed_paths(p))


@pytest.mark.parametrize("where", ["not-in-route", "body"])
def test_P3_a_listed_id_named_only_outside_the_policy_sites_is_not_credited(tmp_path, canon, where):
    inventory(canon, "AP-DAEMON", "AP-SYNTH")
    if where == "not-in-route":
        p = agent_brief(tmp_path, extra="## Not in this route: G-11 (the next AP-SYNTH route)\n")
    else:
        p = agent_brief(tmp_path, middle="## A1 · TARGET STATE\n- the AP-SYNTH drafter is left as it is.\n\n")
    clause = "; named only outside '## Agent policy:' and Agent permissions (not credited): AP-SYNTH"
    assert prefire.check(p) == [OPX2_REFUSAL % clause]
    assert prefire.cited_policy_ids(p) == []


def test_P3_an_unlisted_body_id_is_no_longer_cited_but_a_header_one_is(tmp_path, canon):
    inventory(canon, "AP-DAEMON", "AP-SYNTH")
    p = agent_brief(tmp_path, extra="## Agent policy: AP-NOT-LISTED\n## Not in this route: AP-OTHER work\n")
    assert prefire.check(p) == [OPX2_REFUSAL % "; cited but not listed: AP-NOT-LISTED"]


@pytest.mark.parametrize("extra, permissions, credited", [
    ("## Agent policy: AP-DAEMON\n", NO_AGENT, ["AP-DAEMON"]),
    ("## Agent policy (OPX-2): AP-DAEMON\n", NO_AGENT, ["AP-DAEMON"]),
    ("## Agent policies: AP-ORCH · AP-TONI\n", NO_AGENT, ["AP-ORCH", "AP-TONI"]),
    ("", "AP-TONI only; untrusted input + state change.", ["AP-TONI"]),
])
def test_P3c_the_policy_sites_are_credited(tmp_path, canon, extra, permissions, credited):
    inventory(canon, "AP-DAEMON", "AP-ORCH", "AP-TONI", "AP-SYNTH")
    p = agent_brief(tmp_path, extra=extra, permissions=permissions)
    assert prefire.cited_policy_ids(p) == credited
    v = opx2(p)
    assert v.ok and v.line == ("OPX-2 ✅ agent-runtime path(s) src/daemon/x.ts (src/daemon/**) under %s "
                               "(SCP_Agent_Inventory_v0-1.md)" % ", ".join(credited))


def test_P3c_the_701_v1_shape_credits_its_own_two_ids_only(tmp_path, canon):
    """701 v1: AP-CAREMGR on '## Agent policy:', AP-SYNTH only on '## Not in this route:', 'AP-CAREMGR / AP-DAEMON' in
    Agent permissions (VERIFY-REPORT-701-r1 m-11 (ii))."""
    inventory(canon, "AP-CAREMGR", "AP-DAEMON", "AP-SYNTH")
    p = agent_brief(tmp_path,
                    extra=("## Agent policy: AP-CAREMGR (care-manager reply drafter — G-09, Inventory v0-8 `:158`)\n"
                           "## Not in this route: the portal banner; G-11 (next AP-SYNTH route, OC-14 rec 3)\n"),
                    permissions="AP-CAREMGR / AP-DAEMON. The deterministic check, not the model, decides.",
                    middle="8. **Canon.** Inventory v0-8 `:37` (AP-CAREMGR), `:38` (AP-DAEMON).\n\n")
    assert prefire.cited_policy_ids(p) == ["AP-CAREMGR", "AP-DAEMON"]
    assert opx2(p).line.endswith("under AP-CAREMGR, AP-DAEMON (SCP_Agent_Inventory_v0-1.md)")


# ── P-4 · a header line a reader cannot see is a named refusal ────────────────────────────────────────────────
PAST = [  # (the line, the head() keywords that leave its in-window copy out)
    ("## Depends-on: 600-x-1", {}),
    ("## Test scope: targeted (D-S7CORE30-05)", {"scope": ""}),
    ("## Test scope: targeted (D-S7CORE30-05)", {}),               # a second, in-window line does not hide it
    ("## Estimated runtime: 60-90 min", {"runtime": ""}),
    ("## Kanban: SCP_Kanban row 20", {"kanban": False}),
    ("## Micro-fire trigger: P1-safety — fail-open guard", {}),
    ("## Re-gate of: orch-mp-300-x 0123abcd", {}),
]


@pytest.mark.parametrize("line, kw", PAST)
def test_P4_a_prefire_header_line_past_6000_is_refused(tmp_path, line, kw):
    text = ending_at(head(**kw), line, 6400) + "\n" + body()
    fails = prefire.check(write(tmp_path, text))
    assert hdr(line, line_no(text, line), 6400) in fails, fails
    assert not any(f.startswith("A11") for f in fails), fails
    if not kw:                                       # its reader's own line is in the window: HDR is the one refusal
        assert fails == [hdr(line, line_no(text, line), 6400)], fails


def test_P4_a_line_cut_mid_way_by_the_window_is_refused(tmp_path):
    line = "## Estimated runtime: 60-90 min"
    text = head(runtime="") + "x" * (5990 - len(head(runtime="")) - 1) + "\n" + line + "\n" + body()
    assert text.index(line) == 5990
    fails = prefire.check(write(tmp_path, text))
    assert hdr(line, line_no(text, line), 5990 + len(line)) in fails, fails


@pytest.mark.parametrize("line", ["## TONI_TIMEOUT_MIN: 170", "## Fire mechanism: queue TONI_TIMEOUT_MIN=170"])
def test_P4_an_admission_line_past_4000_is_refused_and_is_indeed_not_read(tmp_path, line):
    text = ending_at(head(), line, 4300) + "\n" + body()
    p = write(tmp_path, text)
    assert prefire.check(p) == [hdr(line, line_no(text, line), 4300, "admission.parse_brief_timeout", 4000)]
    assert admission.parse_brief_timeout(p) == 112 != 170       # the runtime line's 90 × 1.25


# ── P-4c · the boundary, and what HDR does not read ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("line, parse, value, window", [
    ("## Estimated runtime: 7", prefire.parse_declared_runtime, (7, 7), 6000),
    ("## Depends-on: a-1", prefire.parse_depends_on, ([("a-1", None)], None), 6000),
    ("## TONI_TIMEOUT_MIN: 170", admission.parse_brief_timeout, 170, 4000),
    ("## Fire mechanism: queue TONI_TIMEOUT_MIN=170", admission.parse_brief_timeout, 170, 4000),
])
def test_P4c_a_line_ending_at_the_window_is_read_and_one_char_later_is_refused(tmp_path, line, parse, value, window):
    pre = head(runtime="")
    at = write(tmp_path, ending_at(pre, line, window) + "\n" + body(), "at.md")
    assert parse(at) == value
    assert prefire.header_window_problems(at) == []
    text = ending_at(pre, line, window + 1) + "\n" + body()
    past = write(tmp_path, text, "past.md")
    assert parse(past) != value
    reader = "prefire" if window == 6000 else "admission.parse_brief_timeout"
    assert prefire.header_window_problems(past) == [hdr(line, line_no(text, line), window + 1, reader, window)]


def test_P4c_george_go_and_dependency_change_are_read_whole(tmp_path):
    go = '## George go: George 2026-11-14 17:38 "go on src/lib/clinical" (D-S7CORE54-99)'
    dep = '## Dependency change: left-pad@1.3.0 (dev) — George go "yes, add it" (D-S7CORE54-99)'
    text = ending_at(head(row=393) + FIVE % NO_AGENT, go, 7200) + "\n" + dep + "\n\n" + \
        "## 2 · ALLOWED FILES\n`src/lib/clinical/x.ts`\n\n" + body()
    p = write(tmp_path, text)
    assert text.index(dep) > 7000
    assert prefire.header_window_problems(p) == []
    assert prefire.check(p) == []
    assert prefire.check_george_go(p, prefire.allowed_paths(p)).ok
    assert prefire.dependency_changes(p) == ([{"pkg": "left-pad", "version": "1.3.0", "kind": "dev"}], [])


def test_P4c_a_header_line_inside_a_code_fence_is_not_refused(tmp_path):
    text = ending_at(head() + "```\n", "## Depends-on: 600-x-1", 6400) + "\n```\n" + body()
    p = write(tmp_path, text)
    assert prefire.header_window_problems(p) == [] and prefire.check(p) == []


def test_P4c_a_fire_mechanism_line_without_the_override_is_not_refused(tmp_path):
    p = write(tmp_path, ending_at(head(), "## Fire mechanism: queue, the daemon fires it", 4300) + "\n" + body())
    assert prefire.header_window_problems(p) == [] and prefire.check(p) == []


def test_P4c_PREFIRE_OPEX_off_does_not_silence_HDR(tmp_path, monkeypatch):
    monkeypatch.setenv("PREFIRE_OPEX", "off")
    line = "## Depends-on: 600-x-1"
    text = ending_at(head(), line, 6400) + "\n" + body()
    assert prefire.check(write(tmp_path, text)) == [hdr(line, line_no(text, line), 6400)]


def test_P4c_a_brief_with_every_header_in_window_is_untouched(tmp_path, capsys):
    p = write(tmp_path, head(row=20, extra="## Micro-fire trigger: P1-safety — fail-open guard\n") + "y" * 9000
              + "\n" + body())
    assert prefire.header_window_problems(p) == [] and prefire.check(p) == []
    assert prefire.report(p) is True
    assert capsys.readouterr().out.splitlines()[0] == (
        "  Assertions: ✅ A1/A2/A8/A9/A10/A11 pass — SCP_Kanban row 20 READY (SCP_Kanban_v0-1.md); declared 60m "
        "(floor 30m); timeout 112 min (Estimated runtime × 1.25 — the fire applies TONI_TIMEOUT_MIN and the hard cap)")


# ── P-5 · admission.parse_brief_timeout answers as on the base ────────────────────────────────────────────────
def test_P5_admission_reads_the_override_lines_from_their_one_owner(tmp_path):
    assert admission.parse_brief_timeout(write(tmp_path, "x" * 99 + "\n## TONI_TIMEOUT_MIN: 99\n")) == 99
    assert admission.parse_brief_timeout(write(tmp_path, "## Fire mechanism: queue TONI_TIMEOUT_MIN=77\n")) == 77
    both = "x" * 4100 + "\n## TONI_TIMEOUT_MIN: 99\n## Fire mechanism: queue TONI_TIMEOUT_MIN=77\n" + RUNTIME
    assert admission.parse_brief_timeout(write(tmp_path, both)) == 112
    assert admission.parse_brief_timeout(write(tmp_path, "# nothing declared\n")) is None
    assert prefire.ADMISSION_HEADER_CHARS == 4000
    assert prefire.TIMEOUT_MIN_LINE.pattern == r'^## TONI_TIMEOUT_MIN:\s*(\d+)'
    assert prefire.FIRE_MECHANISM_TIMEOUT_LINE.pattern == r'^## Fire mechanism:.*TONI_TIMEOUT_MIN=(\d+)'
