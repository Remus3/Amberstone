"""Roster-driven replay corpus: folder layout + ranked-only selection.

The pull itself is `core.rofl_archive.download_replays` (already proven live);
everything tested here is the layer that decides WHERE a tracked player's
replay lands and WHETHER it is wanted at all.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core import replay_roster as rr


# ---------------------------------------------------------------- roster load

def test_the_shipped_roster_parses_and_carries_a_top_laner():
    # The live roster is gitignored (it names other people's accounts), so a
    # fresh clone reads the tracked example. Either way the loader must yield
    # a parseable non-empty roster with a TOP entry - that is what is being
    # tested here, not any one account.
    entries = rr.load_roster()
    assert entries, "the shipped roster must not be empty"
    tops = [e for e in entries if e.role == "TOP"]
    assert tops, "the shipped roster must seed at least one TOP account"
    assert all(e.name and e.tag for e in tops)


def test_the_tracked_example_roster_is_always_loadable():
    # Guards the fresh-clone path explicitly: the example must stay valid even
    # on a machine that HAS a live roster, where the fallback never fires.
    entries = rr.load_roster(rr.EXAMPLE_ROSTER)
    assert entries
    assert {e.role for e in entries} <= set(rr.ROLES)


def test_every_shipped_roster_role_is_a_known_role():
    for entry in rr.load_roster():
        assert entry.role in rr.ROLES


def test_an_unknown_role_is_rejected_loudly(tmp_path):
    bad = tmp_path / "roster.json"
    bad.write_text('{"players": [{"role": "CARRY", "riot_id": "A#B"}]}',
                   encoding="utf-8")
    with pytest.raises(ValueError, match="CARRY"):
        rr.load_roster(bad)


def test_a_riot_id_without_a_tag_is_rejected(tmp_path):
    bad = tmp_path / "roster.json"
    bad.write_text('{"players": [{"role": "TOP", "riot_id": "NoTagHere"}]}',
                   encoding="utf-8")
    with pytest.raises(ValueError, match="NoTagHere"):
        rr.load_roster(bad)


# ------------------------------------------------------------- folder layout

def test_player_dir_is_role_partitioned_under_a_players_root(tmp_path):
    got = rr.player_dir(tmp_path, "TOP", "SamplePlayer2", "BIG")
    assert got == tmp_path / "players" / "TOP" / "SamplePlayer2-BIG"


def test_player_slug_sanitises_characters_that_cannot_be_a_windows_dir():
    # Riot IDs allow spaces; a path separator must never survive into a dir name.
    assert rr.player_slug("Big Daddy", "NA 1") == "Big_Daddy-NA_1"
    assert "/" not in rr.player_slug("a/b", "c\\d")
    assert "\\" not in rr.player_slug("a/b", "c\\d")


def test_two_different_unicode_names_do_not_collide(tmp_path):
    # Collapsing CJK to underscores is lossy: without a disambiguating digest
    # these two distinct players share a directory and their replays merge.
    a = rr.player_slug("我依然", "我不")
    b = rr.player_slug("東方树", "爱七")
    assert a != b
    assert len(a.split("-")) == 3      # name-tag-digest


def test_an_ascii_riot_id_keeps_its_plain_slug():
    # The guard must NOT rename directories that already hold pulled replays.
    # never_type-1998 exists on disk with 5 files in it; adding a digest here
    # would orphan them.
    assert rr.player_slug("blaberfish2", "NA1") == "blaberfish2-NA1"
    assert rr.player_slug("never type", "1998") == "never_type-1998"
    assert rr.player_slug("Big Daddy", "NA 1") == "Big_Daddy-NA_1"


def test_the_digest_is_stable_across_calls():
    assert rr.player_slug("我依", "x") == rr.player_slug("我依", "x")


def test_stats_dir_sits_inside_the_player_dir(tmp_path):
    pdir = rr.player_dir(tmp_path, "TOP", "SamplePlayer2", "BIG")
    assert rr.stats_dir(pdir) == pdir / "stats"


# ---------------------------------------------------------- ranked selection

_URLS = [
    "https://s3/NA1_5609054331.rofl?X-Amz-Expires=3600",
    "https://s3/NA1_5608992935.rofl?X-Amz-Expires=3600",
    "https://s3/NA1_5608704730.rofl?X-Amz-Expires=3600",
]


def test_plan_pull_keeps_only_ranked_queues():
    queues = {
        "NA1_5609054331": 420,   # ranked solo
        "NA1_5608992935": 1740,  # not ranked
        "NA1_5608704730": 440,   # ranked flex
    }
    plan = rr.plan_pull(_URLS, queues.get)
    assert [rr.match_id_of(u) for u in plan.keep] == [
        "NA1_5609054331", "NA1_5608704730"]
    assert plan.rejected == {"NA1_5608992935": 1740}


def test_an_unresolvable_queue_fails_closed_rather_than_being_pulled():
    # A queue we could not look up must NOT be assumed ranked - 10 MB per guess.
    plan = rr.plan_pull(_URLS[:1], lambda _mid: None)
    assert plan.keep == []
    assert plan.rejected == {"NA1_5609054331": None}


def test_the_ranked_queue_set_is_solo_plus_flex_only():
    assert set(rr.RANKED_QUEUES) == {420, 440}


def test_plan_pull_honours_an_explicit_queue_override():
    plan = rr.plan_pull(_URLS[1:2], lambda _mid: 1740, queues=(1740,))
    assert [rr.match_id_of(u) for u in plan.keep] == ["NA1_5608992935"]
    assert plan.rejected == {}


def test_a_url_with_no_parseable_match_id_is_rejected_not_pulled():
    plan = rr.plan_pull(["https://s3/garbage?X-Amz-Expires=3600"], lambda _m: 420)
    assert plan.keep == []
    assert plan.unparsed == ["https://s3/garbage?X-Amz-Expires=3600"]


def test_plan_pull_skips_a_match_already_on_disk(tmp_path):
    (tmp_path / "NA1_5609054331.rofl").write_bytes(b"RIOT\x02\x00")
    plan = rr.plan_pull(_URLS[:1], lambda _m: 420, archive_dir=tmp_path)
    assert plan.keep == []
    assert plan.already == ["NA1_5609054331"]


def test_plan_pull_skips_the_hyphen_spelling_on_disk_too(tmp_path):
    # The client writes NA1-x.rofl, the API writes NA1_x.rofl; one game.
    (tmp_path / "NA1-5609054331.rofl").write_bytes(b"RIOT\x02\x00")
    plan = rr.plan_pull(_URLS[:1], lambda _m: 420, archive_dir=tmp_path)
    assert plan.already == ["NA1_5609054331"]


def test_match_id_of_accepts_both_spellings():
    assert rr.match_id_of("https://s3/NA1-123.rofl?x=1") == "NA1_123"
    assert rr.match_id_of("https://s3/NA1_123.rofl?x=1") == "NA1_123"


def test_roster_root_default_lives_beside_the_operator_archive():
    root = rr.default_corpus_root()
    assert isinstance(root, Path)
    assert root.name == "RC_ROFL_Archive"
