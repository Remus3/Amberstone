"""Guards for tools/rewrite_sha_citations.py.

The tool runs exactly once, immediately after an irreversible history rewrite,
against the repo's only durable record of what shipped. There is no second
attempt and no undo, so the failure modes that matter are the QUIET ones: a
prefix silently resolved to the wrong commit, a dropped commit's citation
rewritten to garbage, or a citation length changed so the prose reflows.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.rewrite_sha_citations import (  # noqa: E402
    BACKTICKED_SHA_RE,
    SHA_RE,
    CommitMap,
    rewrite_text,
)

OLD_A = "aaaaaaaa" + "1" * 32
NEW_A = "bbbbbbbb" + "2" * 32
OLD_B = "aaaaaaab" + "3" * 32
NEW_B = "cccccccc" + "4" * 32
OLD_DROPPED = "dddddddd" + "5" * 32
ZERO = "0" * 40


@pytest.fixture()
def cmap() -> CommitMap:
    return CommitMap({OLD_A: NEW_A, OLD_B: NEW_B, OLD_DROPPED: ZERO})


def test_full_sha_is_remapped(cmap):
    out, stats, _ = rewrite_text(f"see {OLD_A} for detail", cmap, SHA_RE)
    assert out == f"see {NEW_A} for detail"
    assert stats["ok"] == 1


def test_abbreviation_length_is_preserved(cmap):
    """An 8-char citation must stay 8 chars or every table cell reflows."""
    out, _, _ = rewrite_text(f"`{OLD_A[:8]}`", cmap, SHA_RE)
    assert out == f"`{NEW_A[:8]}`"
    assert len(out) == len(f"`{OLD_A[:8]}`")


def test_ambiguous_prefix_is_left_alone_not_guessed(cmap):
    """OLD_A and OLD_B share 'aaaaaaa'. Guessing either one would be wrong."""
    text = f"commit {OLD_A[:7]} landed"
    out, stats, problems = rewrite_text(text, cmap, SHA_RE)
    assert out == text, "an ambiguous prefix must be left untouched"
    assert stats["ambiguous"] == 1
    assert stats["ok"] == 0
    assert problems[0][2] == "ambiguous"


def test_dropped_commit_is_reported_and_not_zeroed(cmap):
    """A citation to a purged commit is a permanent loss; it must be visible.

    Writing forty zeros into the ledger would be strictly worse than leaving
    the stale sha: it destroys the only clue about what was cited.
    """
    text = f"see {OLD_DROPPED[:10]}"
    out, stats, problems = rewrite_text(text, cmap, SHA_RE)
    assert out == text
    assert stats["dropped"] == 1
    assert ZERO not in out
    assert problems[0][2] == "dropped"


def test_unknown_sha_is_untouched(cmap):
    text = "hash 9f9f9f9f is not a commit here"
    out, stats, _ = rewrite_text(text, cmap, SHA_RE)
    assert out == text
    assert stats["unknown"] == 1


def test_problem_line_numbers_are_reported(cmap):
    text = "\n".join(["intro", "middle", f"bad {OLD_DROPPED[:8]}"])
    _, _, problems = rewrite_text(text, cmap, SHA_RE)
    assert problems[0][0] == 3


def test_backticks_mode_ignores_bare_hex(cmap):
    """`--require-backticks` exists so prose hex cannot be mangled."""
    text = f"bare {OLD_A[:8]} and quoted `{OLD_A[:8]}`"
    out, stats, _ = rewrite_text(text, cmap, BACKTICKED_SHA_RE)
    assert stats["ok"] == 1
    assert f"bare {OLD_A[:8]}" in out
    assert f"`{NEW_A[:8]}`" in out


def test_short_hex_below_seven_is_not_a_citation(cmap):
    text = "value abc123 unchanged"
    out, stats, _ = rewrite_text(text, cmap, SHA_RE)
    assert out == text
    assert sum(stats.values()) == 0


def test_hex_embedded_in_a_longer_token_is_not_matched(cmap):
    """Guards the lookaround: a 41+ char hex run is not an abbreviation."""
    text = f"{OLD_A}ff is a longer token"
    out, stats, _ = rewrite_text(text, cmap, SHA_RE)
    assert out == text
    assert sum(stats.values()) == 0


def test_commit_map_rejects_a_file_with_no_pairs(tmp_path):
    p = tmp_path / "commit-map"
    p.write_text("old new\n", encoding="utf-8")
    with pytest.raises(ValueError):
        CommitMap.from_file(p)


def test_commit_map_parses_a_real_shaped_file(tmp_path):
    p = tmp_path / "commit-map"
    p.write_text(f"old new\n{OLD_A} {NEW_A}\n{OLD_DROPPED} {ZERO}\n", encoding="utf-8")
    cm = CommitMap.from_file(p)
    assert cm.resolve(OLD_A[:8]) == ("ok", NEW_A)
    assert cm.resolve(OLD_DROPPED[:8])[0] == "dropped"


def test_several_old_commits_collapsing_onto_one_new_is_not_ambiguous():
    """filter-repo collapses commits; two olds sharing a prefix AND a new
    target is a single answer, not a conflict."""
    cm = CommitMap({"aaaaaaaa" + "1" * 32: NEW_A, "aaaaaaaa" + "9" * 32: NEW_A})
    assert cm.resolve("aaaaaaaa") == ("ok", NEW_A)


def test_the_sha_pattern_is_case_sensitive_to_lowercase_git_output():
    """git emits lowercase; an uppercase run is prose, not a citation."""
    assert SHA_RE.search("DEADBEEF1") is None
    assert SHA_RE.search("deadbeef1") is not None


def test_ledger_citation_shape_is_actually_matched_by_the_pattern():
    """Pin the real-world shape this tool exists to fix."""
    sample = "landed (`54bad078` + `05319608`)"
    found = re.findall(BACKTICKED_SHA_RE, sample)
    assert found == ["54bad078", "05319608"]
