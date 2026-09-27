# filename: tests/test_route_landed.py
"""Tests for ORCH-CONFLICT-1's predicate, alone — `check_route_landed_invariants`.

EMPTY WHEN CLEAN. Clean ⇔ the caller-supplied route tip is an ancestor of the merge target AND
the repo is not mid-merge. Unreadable ⇒ []. All cases use real git repos.

  AC-CF-05  (i)   merged with `git merge --no-edit`              → []
            (ii)  fast-forwarded (`--ff-only`, the self-mod shape) → []
            (iii) tip not an ancestor of main                     → one violation, not mid-merge
            (iv)  repo left mid-merge by a real conflict          → one violation, mid_merge
            (v)   no .git / missing target / unresolvable tip     → []
            (vi)  a previous attempt's `Merge branch '<same>'` on main does not answer for
                  this attempt's tip — ancestry decides, not the subject scan
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import canon_assert
from canon_assert import QueueRepo, UnlandedRouteViolation, check_route_landed_invariants

BRIEF = "batch-rl.md"
BRANCH = "orch-batch-rl"


def _git(cmd: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True)


def _sha(rev: str, cwd: Path) -> str:
    return _git(f"git rev-parse {rev}", cwd).stdout.strip()


def _commit(path: Path, name: str, content: str, msg: str):
    (path / name).write_text(content)
    _git("git add -A", path)
    assert _git(f'git commit -m "{msg}"', path).returncode == 0


@pytest.fixture
def proj(tmp_path) -> Path:
    p = tmp_path / "repo"
    p.mkdir()
    _git("git init", p)
    _git("git config user.email test@test.com", p)
    _git("git config user.name Test", p)
    _git("git symbolic-ref HEAD refs/heads/main", p)
    _commit(p, "README.md", "init\n", "init")
    return p


def _repo(p: Path) -> QueueRepo:
    return QueueRepo("testrepo", p, "main", "orch")


def _route_with_work(p: Path, content: str = "work\n") -> str:
    """Cut the route branch from main, commit on it, return its tip. HEAD stays on the route."""
    assert _git(f"git checkout -b {BRANCH} main", p).returncode == 0
    _commit(p, "feature.txt", content, "feat: work")
    return _sha("HEAD", p)


def test_merged_with_a_merge_commit_is_clean(proj):
    """(i) the route lane's shape: main moved elsewhere, `git merge --no-edit` made a merge commit."""
    tip = _route_with_work(proj)
    _git("git checkout main", proj)
    _commit(proj, "other.txt", "elsewhere\n", "main: unrelated")
    assert _git(f"git merge {BRANCH} --no-edit", proj).returncode == 0
    assert _git("git rev-list --merges -n1 main", proj).stdout.strip(), "a real merge commit"
    assert check_route_landed_invariants(_repo(proj), BRIEF, tip) == []


def test_fast_forwarded_is_clean(proj):
    """(ii) the self-mod shape: `git merge --ff-only` leaves no merge commit of its own."""
    tip = _route_with_work(proj)
    _git("git checkout main", proj)
    assert _git(f"git merge --ff-only {BRANCH}", proj).returncode == 0
    assert _sha("main", proj) == tip
    assert check_route_landed_invariants(_repo(proj), BRIEF, tip) == []


def test_tip_not_on_target_is_one_violation(proj):
    """(iii) never merged: not landed, not mid-merge."""
    tip = _route_with_work(proj)
    _git("git checkout main", proj)
    out = check_route_landed_invariants(_repo(proj), BRIEF, tip)
    assert len(out) == 1
    v = out[0]
    assert isinstance(v, UnlandedRouteViolation)
    assert (v.landed, v.mid_merge) == (False, False)
    assert (v.repo, v.branch, v.merge_target) == ("testrepo", BRANCH, "main")
    assert (v.route_tip, v.target_tip) == (tip, _sha("main", proj))
    assert "not on main" in str(v) and tip[:8] in str(v) and "mid-merge" not in str(v)


def test_repo_left_mid_merge_is_one_violation(proj):
    """(iv) the incident's after-state: a real conflict, never aborted."""
    tip = _route_with_work(proj, "route\n")
    _git("git checkout main", proj)
    _commit(proj, "feature.txt", "main\n", "main: conflicting")
    assert _git(f"git merge {BRANCH} --no-edit", proj).returncode != 0
    assert _git("git rev-parse -q --verify MERGE_HEAD", proj).returncode == 0, "fixture is mid-merge"
    out = check_route_landed_invariants(_repo(proj), BRIEF, tip)
    assert len(out) == 1
    assert out[0].mid_merge is True
    assert out[0].landed is False
    assert "repo mid-merge" in str(out[0])


def test_unreadable_is_never_a_violation(proj, tmp_path):
    """(v) no .git, no merge target, unresolvable route tip ⇒ [] — the module's rule."""
    tip = _route_with_work(proj)
    _git("git checkout main", proj)       # an honest violation exists here; unreadability must hide it
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    assert check_route_landed_invariants(QueueRepo("x", bare, "main", "orch"), BRIEF, tip) == []
    assert check_route_landed_invariants(QueueRepo("testrepo", proj, "no-such-target", "orch"), BRIEF, tip) == []
    assert check_route_landed_invariants(_repo(proj), BRIEF, "deadbeef" * 5) == []


def test_previous_attempts_merge_commit_does_not_answer_for_this_one(proj):
    """(vi) attempt 1 merged as `Merge branch 'orch-batch-rl'`; attempt 2 re-cut the same name
    and its tip is not on main. The subject scan (_landed) says landed; ancestry says not."""
    _route_with_work(proj, "attempt 1\n")
    _git("git checkout main", proj)
    _commit(proj, "other.txt", "elsewhere\n", "main: unrelated")
    assert _git(f"git merge {BRANCH} --no-edit", proj).returncode == 0
    _git(f"git branch -d {BRANCH}", proj)
    tip2 = _route_with_work(proj, "attempt 2\n")
    _git("git checkout main", proj)

    assert f"Merge branch '{BRANCH}'" in _git("git log -1 --merges --format=%s main", proj).stdout
    assert canon_assert._landed(_repo(proj), BRANCH) is not None, "the subject scan is fooled"
    out = check_route_landed_invariants(_repo(proj), BRIEF, tip2)
    assert len(out) == 1
    assert out[0].landed is False and out[0].route_tip == tip2
