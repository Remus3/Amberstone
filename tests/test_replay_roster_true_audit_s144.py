"""True-audit (lane 8, s144 cycle 143) regression tests for core/replay_roster.py.

The roster pull (tools/replay_roster_pull.py, the hourly RC-ReplayRosterPull
run) feeds every listed replay URL through `plan_pull` / `match_id_of` and the
roster file through `load_roster`. Each test below pins one weakness found by
the audit (S144-T-355..364); the characterization tests at the bottom pin the
contracts the rewrite must keep byte-identical.

All ids are synthetic.
"""
from __future__ import annotations

import json
import urllib.parse

import pytest

from core import replay_roster as rr
from core import rofl_archive


def _cd_url(filename: str, path: str = "/bucket/opaque-object") -> str:
    """A pre-signed URL whose authoritative name rides in the disposition."""
    disp = urllib.parse.quote(f'attachment; filename="{filename}"', safe="")
    return (f"https://s3.example{path}?response-content-disposition={disp}"
            f"&X-Amz-Expires=3600")


def _write_roster(tmp_path, blob, *, raw: bytes | None = None):
    path = tmp_path / "roster.json"
    if raw is not None:
        path.write_bytes(raw)
    else:
        path.write_bytes(json.dumps(blob).encode("utf-8"))
    return path


# ------------------------------------------------ S144-T-355 non-str URL entry

@pytest.mark.parametrize("junk", [None, 123, 4.5, b"NA1_1.rofl", {"url": "x"},
                                  ["NA1_1.rofl"]])
def test_match_id_of_returns_none_for_a_non_string_entry(junk):
    # A shape drift in the /replays body (a dict or a null in matchFileURLs)
    # raised TypeError out of the regex and aborted the WHOLE roster run.
    assert rr.match_id_of(junk) is None


def test_plan_pull_files_a_non_string_entry_as_unparsed_and_keeps_going():
    good = "https://s3/NA1_5000000001.rofl?X-Amz-Expires=3600"
    plan = rr.plan_pull([None, {"u": 1}, good], lambda _m: 420)
    assert plan.keep == [good]
    assert plan.unparsed == [None, {"u": 1}]


# ------------------------------- S144-T-356 the plan agrees with the downloader

def test_match_id_of_reads_the_filename_not_a_platform_token_in_the_path():
    # The old unanchored whole-URL search took the FIRST platform-like token,
    # so a directory such as /kr-2/ named the wrong game: the plan looked up
    # KR_2 (unresolved -> rejected) and the real game rotated out unpulled.
    url = "https://s3.example/replays/kr-2/NA1_5000000002.rofl?X-Amz-Expires=3600"
    assert rofl_archive.match_id_from_replay_url(url) == "NA1_5000000002"
    assert rr.match_id_of(url) == "NA1_5000000002"


def test_match_id_of_prefers_the_content_disposition_name():
    url = _cd_url("NA1_5000000003.rofl", path="/replays/EUW1-7/obj")
    assert rr.match_id_of(url) == rofl_archive.match_id_from_replay_url(url)
    assert rr.match_id_of(url) == "NA1_5000000003"


def test_plan_pull_looks_up_the_downloaders_match_id():
    url = "https://s3.example/replays/kr-2/NA1_5000000004.rofl?X-Amz-Expires=3600"
    seen = []

    def lookup(mid):
        seen.append(mid)
        return 420

    plan = rr.plan_pull([url], lookup)
    assert seen == ["NA1_5000000004"]
    assert plan.keep == [url]


# ------------------------------------------------- S144-T-357 ME1 platform

def test_a_middle_east_replay_is_parsed_not_dropped():
    # ME1 was missing from the platform list, so every ME1 replay landed in
    # `unparsed` and was never pulled while download_replays accepts it.
    assert rr.match_id_of("https://s3/ME1_5000000005.rofl?x=1") == "ME1_5000000005"
    assert rr.match_id_of("ME1-5000000005") == "ME1_5000000005"
    plan = rr.plan_pull(["https://s3/ME1_5000000005.rofl?x=1"], lambda _m: 420)
    assert plan.keep == ["https://s3/ME1_5000000005.rofl?x=1"]
    assert plan.unparsed == []


# ---------------------------------------- S144-T-358 duplicate match in a window

def test_the_same_game_listed_twice_is_kept_and_looked_up_once():
    a = "https://s3/NA1-5000000006.rofl?x=1"
    b = "https://s3/NA1_5000000006.rofl?x=2"
    calls = []

    def lookup(mid):
        calls.append(mid)
        return 420

    plan = rr.plan_pull([a, b, a], lookup)
    assert plan.keep == [a]
    assert calls == ["NA1_5000000006"]
    assert plan.duplicate == [b, a]


def test_a_rejected_duplicate_is_not_looked_up_again():
    a = "https://s3/NA1_5000000007.rofl?x=1"
    calls = []
    plan = rr.plan_pull([a, a], lambda m: calls.append(m))
    assert calls == ["NA1_5000000007"]
    assert plan.rejected == {"NA1_5000000007": None}
    assert plan.duplicate == [a]


# ---------------------------------- S144-T-359 lookup / urls shape tolerance

@pytest.mark.parametrize("queue", [[420], {"q": 420}, {420}])
def test_an_unhashable_queue_value_is_rejected_not_raised(queue):
    url = "https://s3/NA1_5000000008.rofl?x=1"
    plan = rr.plan_pull([url], lambda _m: queue)
    assert plan.keep == []
    assert list(plan.rejected) == ["NA1_5000000008"]


def test_a_bool_queue_value_is_never_ranked():
    # True == 1 and False == 0; neither is a queue id. An override set that
    # holds 1 must not admit a lookup that answered True.
    url = "https://s3/NA1_5000000009.rofl?x=1"
    plan = rr.plan_pull([url], lambda _m: True, queues=(1,))
    assert plan.keep == []


def test_a_single_url_string_is_one_url_not_one_per_character():
    url = "https://s3/NA1_5000000010.rofl?x=1"
    plan = rr.plan_pull(url, lambda _m: 420)
    assert plan.keep == [url]
    assert plan.unparsed == []


# ------------------------------------------------------- S144-T-360 UTF-8 BOM

def test_a_roster_saved_with_a_utf8_bom_still_loads(tmp_path):
    # PowerShell 5.1 Set-Content -Encoding UTF8 and older Notepad write a BOM;
    # json.loads raised "Unexpected UTF-8 BOM" and the hourly pull died.
    body = json.dumps({"players": [{"role": "TOP", "riot_id": "Alpha#NA1"}]})
    path = _write_roster(tmp_path, None, raw=b"\xef\xbb\xbf" + body.encode())
    entries = rr.load_roster(path)
    assert [(e.role, e.name, e.tag) for e in entries] == [("TOP", "Alpha", "NA1")]


# ------------------------------------------- S144-T-361 wrong shape -> ValueError

@pytest.mark.parametrize("blob", [
    [],
    "players",
    {"players": {"role": "TOP", "riot_id": "Alpha#NA1"}},
    {"players": "Alpha#NA1"},
    {"players": 7},
    {"players": True},
    {"players": ["Alpha#NA1"]},
    {"players": [None]},
    {"players": [{"role": "TOP", "riot_id": "Alpha#NA1"}, 7]},
])
def test_a_roster_of_the_wrong_shape_fails_with_a_value_error(tmp_path, blob):
    # The docstring promises a loud, named failure; a list top level or a
    # non-object row raised AttributeError / TypeError instead.
    path = _write_roster(tmp_path, blob)
    with pytest.raises(ValueError):
        rr.load_roster(path)


def test_a_roster_that_is_not_json_still_fails_loudly(tmp_path):
    path = _write_roster(tmp_path, None, raw=b"{not json")
    with pytest.raises(ValueError):
        rr.load_roster(path)


# ---------------------------------- S144-T-362 riot_id hygiene (#, whitespace)

def test_a_riot_id_with_a_second_hash_is_rejected(tmp_path):
    # "a#b#c" became tag "b#c": the account lookup could never match it, so
    # the player was reported as a stale id every run instead of a typo.
    path = _write_roster(tmp_path, {"players": [
        {"role": "MID", "riot_id": "Alpha#NA1#x"}]})
    with pytest.raises(ValueError, match="Alpha#NA1#x"):
        rr.load_roster(path)


def test_surrounding_whitespace_is_stripped_from_name_and_tag(tmp_path):
    path = _write_roster(tmp_path, {"players": [
        {"role": "MID", "riot_id": "  Alpha Beta #  NA1 "}]})
    (entry,) = rr.load_roster(path)
    assert (entry.name, entry.tag) == ("Alpha Beta", "NA1")
    assert entry.riot_id == "Alpha Beta#NA1"
    assert entry.slug == "Alpha_Beta-NA1"


@pytest.mark.parametrize("riot_id", ["   #NA1", "Alpha#   ", " # "])
def test_a_whitespace_only_half_is_rejected(tmp_path, riot_id):
    path = _write_roster(tmp_path, {"players": [
        {"role": "MID", "riot_id": riot_id}]})
    with pytest.raises(ValueError):
        rr.load_roster(path)


# ------------------------------------------- S144-T-363 duplicate account

def test_a_duplicate_account_is_rejected_case_insensitively(tmp_path):
    # Listed twice, an account is pulled twice per run; listed under two
    # roles, the same games land in two role directories and are counted
    # twice by every corpus-wide statistic (tools/build_cohort_baseline.py).
    path = _write_roster(tmp_path, {"players": [
        {"role": "TOP", "riot_id": "Alpha#NA1"},
        {"role": "MID", "riot_id": "alpha#na1"}]})
    with pytest.raises(ValueError, match=r"(?i)duplicate"):
        rr.load_roster(path)


# ------------------------------------------------- S144-T-364 null note

def test_a_null_note_is_empty_not_the_string_none(tmp_path):
    path = _write_roster(tmp_path, {"players": [
        {"role": "TOP", "riot_id": "Alpha#NA1", "note": None}]})
    (entry,) = rr.load_roster(path)
    assert entry.note == ""


# --------------------------------------------- characterization (must not move)

def test_well_formed_roster_loads_unchanged(tmp_path):
    path = _write_roster(tmp_path, {"_comment": ["x"], "players": [
        {"role": "top", "riot_id": "Alpha#NA1", "note": "n"},
        {"role": "SUPPORT", "riot_id": "Big Daddy#NA 1"},
        {"role": "BOT", "riot_id": "\u6211\u4f9d\u7136#\u6211\u4e0d"}]})
    got = [(e.role, e.name, e.tag, e.note) for e in rr.load_roster(path)]
    assert got == [("TOP", "Alpha", "NA1", "n"),
                   ("SUPPORT", "Big Daddy", "NA 1", ""),
                   ("BOT", "\u6211\u4f9d\u7136", "\u6211\u4e0d", "")]


def test_an_empty_or_missing_players_list_is_an_empty_roster(tmp_path):
    assert rr.load_roster(_write_roster(tmp_path, {})) == []
    assert rr.load_roster(_write_roster(tmp_path, {"players": None})) == []
    assert rr.load_roster(_write_roster(tmp_path, {"players": []})) == []


@pytest.mark.parametrize("raw, expected", [
    ("https://s3/NA1-123.rofl?x=1", "NA1_123"),
    ("https://s3/na1_123.rofl?x=1", "NA1_123"),
    ("NA1_123", "NA1_123"),
    ("EUW1-42", "EUW1_42"),
    ("kr_9", "KR_9"),
    ("https://s3/NA1_123?sig=1", "NA1_123"),
    ("https://s3/garbage?X-Amz-Expires=3600", None),
    ("", None),
])
def test_match_id_of_characterization(raw, expected):
    assert rr.match_id_of(raw) == expected


def test_every_parsed_match_id_is_filename_safe():
    import re
    for raw in ["https://s3/NA1_1.rofl", _cd_url("../../EUW1_2.rofl"),
                _cd_url("ME1-3.rofl"), "kr-4", "https://x/a/OC1_5.rofl?q"]:
        mid = rr.match_id_of(raw)
        assert mid is not None and re.fullmatch(r"[A-Z0-9]+_\d+", mid), raw


def test_plan_pull_buckets_are_unchanged_for_a_clean_window(tmp_path):
    (tmp_path / "NA1-5000000020.rofl").write_bytes(b"RIOT")
    urls = ["https://s3/NA1_5000000020.rofl?x=1",
            "https://s3/NA1_5000000021.rofl?x=1",
            "https://s3/NA1_5000000022.rofl?x=1",
            "https://s3/garbage"]
    queues = {"NA1_5000000021": 420, "NA1_5000000022": 1700}
    plan = rr.plan_pull(urls, queues.get, archive_dir=tmp_path)
    assert plan.already == ["NA1_5000000020"]
    assert plan.keep == [urls[1]]
    assert plan.rejected == {"NA1_5000000022": 1700}
    assert plan.unparsed == ["https://s3/garbage"]
    assert plan.duplicate == []


@pytest.mark.parametrize("raw", ["https://s3/NA1_\u0661\u0662.rofl?x=1",
                                 "NA1_\u0661\u0662", "\u212aR_12"])
def test_a_non_ascii_digit_or_letter_is_not_a_match_id(raw):
    # A bare unicode digit class admits Arabic-Indic digits and IGNORECASE
    # admits the Kelvin sign for K; neither names a Riot game.
    assert rr.match_id_of(raw) is None


def test_the_fallback_skips_a_non_ascii_platform_and_finds_the_real_one():
    # The ASCII-only search moves past a Kelvin-sign "KR" token to the real
    # platform instead of matching it and then discarding the whole input.
    assert rr.match_id_of("\u212aR_1 NA1_2") == "NA1_2"
