"""Regression guard: RC's Anthropic clients pin base_url to the direct API.

RC coaching authenticates with the Console API key (API-Key-Claude.txt). A
user-wide ANTHROPIC_BASE_URL - set so the Claude subscription GUI/CLI routes
through the teamclaude failover proxy on :3456 (docs/OPERATIONS.md) - must NOT
redirect RC's own coaching traffic. Doing so would send an API-key request to a
subscription-OAuth proxy (broken auth) or burn the subscription weekly quota.
So every production anthropic.Anthropic(...) construction pins
base_url="https://api.anthropic.com" and ignores the env var.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests import _repo_walk

REPO = Path(__file__).resolve().parent.parent
DIRECT = "https://api.anthropic.com"

# Every production module that constructs an Anthropic client. Tests are
# excluded (they monkeypatch the anthropic module). Keep in sync with
# test_construction_files_list_is_exhaustive below.
CONSTRUCT_FILES = [
    "modes/shared_vision.py",
    "coach_integration/_coach.py",
    "coaches/_base_coach.py",
    "vision_server/_config.py",
    "coaches/replay_coach.py",
    "coaches/experimental_builder.py",
    "coaches/champ_select_coach.py",
    "coaches/brawl_coach.py",
    "coaches/arena_coach.py",
    "coaches/aram_team_analyzer.py",
    "coaches/aram_coach.py",
    "core/anthropic_client.py",
    "agents/agent7_context/warm_session.py",
    "tft/tft_coach_engine.py",
    "tft/tft_live_analysis.py",
    "tft/tft_pbe_engine.py",
    "tft/tft_vision_reader.py",
]

# Per-line pin check: an actual construction is `= anthropic.Anthropic(`.
# The `=` prefix skips the docstring mention in core/anthropic_client.py.
_CTOR_LINE = re.compile(r"=\s*anthropic\.Anthropic\s*\(")
# File-level scan (bare) for the exhaustiveness guard.
_CTOR_FILE = re.compile(r"anthropic\.Anthropic\s*\(")
# This guard's OWN scope choice, applied ON TOP of `tests/_repo_walk`. Tests
# monkeypatch the anthropic module and docs quote the constructor in prose, so
# neither is a production call site - that judgement belongs to this guard and
# to nobody else, which is why it stays here.
#
# Everything else the old hand-list carried (`_archive`, `.git`,
# `node_modules`, `.claude`) is INFRASTRUCTURE exclusion and now comes from
# `tests/_repo_walk.EXCLUDED_DIRS` plus its git tracked-set filter, so it is
# deleted here rather than duplicated. That shared list is also what kills the
# RM-394 false red: `ops/runtime/responder_export/<sha>/` is a full, gitignored
# COPY OF THE REPO written by the inbox responder, and it reported 34 phantom
# net-new sites on this box while CI - which has no such tree - stayed green. A
# copy of our own source is not a new call site, and the fix for that belongs
# in the one shared list, not in a per-guard hand-list here.
_SKIP_DIRS = {
    "tests", "docs",
}


def test_no_unpinned_anthropic_construction():
    offenders = []
    for rel in CONSTRUCT_FILES:
        p = REPO / rel
        assert p.exists(), f"{rel} missing - update CONSTRUCT_FILES"
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if _CTOR_LINE.search(line) and "base_url" not in line:
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, "unpinned Anthropic() construction:\n" + "\n".join(offenders)


def _scan_ctor_sites(root: Path, *, tracked_only: bool = True) -> set[Path]:
    """Every .py under `root` whose text carries an `anthropic.Anthropic(`.

    Enumeration comes from `tests/_repo_walk` - the repo's canonical sweep -
    with this guard's own `_SKIP_DIRS` applied on top, against the path
    RELATIVE to `root`. Matching absolute parts is the trap the walker's
    docstring records: a checkout that itself lives under `.claude/worktrees/`
    would match on every file and return nothing, which is indistinguishable
    from a clean tree.
    """
    # Resolve first: the walker resolves its own base, and on Windows a short
    # 8.3 tmp path resolves to a different string, which would make
    # `relative_to` raise on every file.
    base = Path(root).resolve()
    found: set[Path] = set()
    for path in _repo_walk.iter_repo_files(
        base, patterns=("*.py",), tracked_only=tracked_only
    ):
        if any(part in _SKIP_DIRS for part in path.relative_to(base).parts):
            continue
        try:
            txt = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _CTOR_FILE.search(txt):
            found.add(path.resolve())
    return found


def test_construction_files_list_is_exhaustive():
    known = {(REPO / f).resolve() for f in CONSTRUCT_FILES}
    found = _scan_ctor_sites(REPO)

    # Non-vacuity, asserted BEFORE the offender check: an enumeration that
    # collapsed to nothing produces the same "no new sites" verdict as a clean
    # tree, so the guard has to prove it still reaches the real population.
    missing = known - found
    assert not missing, (
        "the exhaustiveness scan no longer reaches known construction site(s) - "
        "the enumeration is broken (or the file moved), and a scan that cannot "
        "see these cannot see a net-new one either:\n"
        + "\n".join(str(x) for x in sorted(missing))
    )

    new = found - known
    assert not new, (
        "new Anthropic() site(s) outside CONSTRUCT_FILES - pin base_url and add "
        "here:\n" + "\n".join(str(x) for x in sorted(new))
    )


def test_exhaustiveness_scan_still_flags_a_net_new_site(tmp_path):
    """Negative control: the scan discriminates, it does not just skip.

    Any exclusion is only safe if the scan still catches a real net-new
    construction, so this drives the guard's OWN scanner - `_scan_ctor_sites`,
    the same function `test_construction_files_list_is_exhaustive` calls - over
    a synthetic tree. A file outside CONSTRUCT_FILES must be found; its copies
    under `.claude/worktrees/` and under `ops/runtime/responder_export/<sha>/`
    must not. Without this, a future entry in either skip list could quietly
    hollow the guard out.

    Two things changed here when the enumeration moved to `tests/_repo_walk`:

    1. `tracked_only=False` is passed EXPLICITLY. `tmp_path` sits outside any
       git work tree, so the tracked filter would fall back on its own - but a
       test that depends on git failing is a test that silently changes meaning
       the day someone runs it inside a repo. Stating it names the half being
       proven: the EXCLUDED_DIRS segment backstop.
    2. The tracked-set half is proven separately, below, against the real repo,
       because a synthetic tree cannot exercise it at all.

    The honest design consequence of the tracked-set primary: in the real
    checkout an UNTRACKED brand-new .py is no longer flagged. It is flagged the
    moment it is `git add`-ed, which is the state the pre-commit hook and CI
    both see, so nothing reaches main unguarded - and that is the deliberate
    trade for not reporting 34 phantom sites out of a gitignored repo copy.
    """
    (tmp_path / "coaches").mkdir()
    new_site = tmp_path / "coaches" / "brand_new_coach.py"
    new_site.write_text("c = anthropic.Anthropic(api_key=k)\n", encoding="utf-8")

    for shadow_rel in (
        Path(".claude") / "worktrees" / "agent-x" / "coaches",
        Path("ops") / "runtime" / "responder_export" / "42e480322956" / "coaches",
    ):
        shadow = tmp_path / shadow_rel
        shadow.mkdir(parents=True)
        (shadow / "brand_new_coach.py").write_text(
            "c = anthropic.Anthropic(api_key=k)\n", encoding="utf-8"
        )

    assert _scan_ctor_sites(tmp_path, tracked_only=False) == {new_site.resolve()}

    # A file this guard's own scope skips must stay skipped, so the trimmed
    # _SKIP_DIRS is proven to still bite rather than merely to be harmless.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "c = anthropic.Anthropic(api_key=k)\n", encoding="utf-8"
    )
    assert _scan_ctor_sites(tmp_path, tracked_only=False) == {new_site.resolve()}

    # Tracked-set half, on the REAL repo: prove the filter is actually live
    # here and did not fail open to the directory skips. `tracked_relpaths`
    # returns None on any git failure precisely so that case is visible; if it
    # were None, the main test would be passing through the fallback path and
    # this file's whole RM-394 fix would be untested on this box.
    tracked = _repo_walk.tracked_relpaths(str(REPO))
    assert tracked is not None, "git index unreadable - tracked filter failed open"
    assert set(CONSTRUCT_FILES) <= tracked, (
        "CONSTRUCT_FILES entries missing from the git index: "
        f"{sorted(set(CONSTRUCT_FILES) - tracked)}"
    )


def test_tracked_anthropic_ignores_env_base_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:3456")
    pytest.importorskip("anthropic")
    from core.anthropic_client import tracked_anthropic

    client = tracked_anthropic("sk-ant-test-dummy", purpose="test")
    assert str(client.base_url).rstrip("/") == DIRECT
