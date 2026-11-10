"""Lane 8 (true-audit) s144 - tft/tft_placement.py hardening.

tft/tft_placement.py parses three LCU post-game documents RC does not author
(tft-eog-stats, gameclient-eog-stats-block, the TFT match-history route),
writes the RM-616 store data/tft_matches/ and serves it back to the Post Game
Review (dashboard/builders_last_match.py latest()) and /api/tft
(dashboard/routes_tft.py load()). Each test below pins one defect measured
at the pre-audit HEAD:

  S144-T-757  _int() ran int() on any str.isdigit() string: a superscript
              digit raised ValueError out of every parser, Arabic-Indic digits
              were read as a number and a 5000-digit string raised.
  S144-T-758  a game id beyond 19 digits was parsed and persisted, but the
              store lister (_FILE_RE) never lists it, so the record was
              written and then invisible to latest() for ever; the store now
              takes 1 .. 2**63 - 1 (listable AND a SQLite INTEGER, the bound
              tft/rounds/ground_truth.py already applies).
  S144-T-759  one non-finite time_eliminated / game_length or an
              out-of-range game_datetime in ONE history game raised out of
              parse_history, losing every game of that backfill read.
  S144-T-760  history_path() raised on a junk count and str()-ed a non-text
              puuid into the LCU route ("/tft/None/matches").
  S144-T-761  two players flagged isLocalPlayer were BOTH stored is_local,
              so a stranger's board read as the operator's.
  S144-T-762  the store reader validated only `schema`: a too-deep file
              raised RecursionError and a shape-invalid record raised
              TypeError out of load() / latest(), so ONE bad file blanked the
              TFT Post Game Review for every game; a record filed under the
              wrong game id was served as that game; persist() wrote a record
              the reader would reject, and append-only kept it for ever.

ASCII-only authored content (CLAUDE.md hard rule). Synthetic ids only.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tft import tft_placement as tp

FIX = Path(__file__).resolve().parent / "fixtures"
EOG_FIXTURE = FIX / "tft_eog_stats_set18.json"
HIST_FIXTURE = FIX / "tft_match_history_set18.json"
LOCAL_PUUID = "11111111-1111-1111-1111-111111111111"   # fixture placeholder
GID = 1000000001                                        # fixture game id


def _eog() -> dict:
    return json.loads(EOG_FIXTURE.read_text(encoding="utf-8"))


def _hist() -> dict:
    return json.loads(HIST_FIXTURE.read_text(encoding="utf-8"))


def _block() -> dict:
    from tests.test_postgame_tft_capture_rm616 import gameclient_block
    return gameclient_block()


def _hist_with(**fields) -> dict:
    doc = _hist()
    doc["games"][0]["json"].update(fields)
    return doc


def _hist_participant_with(**fields) -> dict:
    doc = _hist()
    doc["games"][0]["json"]["participants"][0].update(fields)
    return doc


# -- S144-T-756: digit strings -------------------------------------------------

@pytest.mark.parametrize("raw", ["\u00b2", "1\u00b2", "\u0661\u0662",
                                 "\uff11\uff12", "9" * 5000, "9" * 20])
def test_int_reads_only_short_ascii_digit_strings(raw):
    assert tp._int(raw) is None


def test_int_characterization_is_unchanged_for_real_input():
    assert tp._int(" 42 ") == 42
    assert tp._int("9" * 19) == int("9" * 19)
    assert tp._int(7) == 7 and tp._int(7.0) == 7
    assert tp._int(True) is None and tp._int(7.5) is None
    assert tp._int("+5") is None and tp._int("-5") is None
    assert tp._int(float("nan")) is None and tp._int(float("inf")) is None


def test_superscript_game_id_is_rejected_by_every_parser_not_raised():
    assert tp.parse_eog(dict(_eog(), gameId="\u00b2")) is None
    assert tp.parse_gameclient_eog(dict(_block(), gameId="\u00b2")) is None
    assert tp.parse_history(_hist_with(game_id="\u00b2", gameId="\u00b2"), LOCAL_PUUID) == []
    assert tp.session_game_id({"gameData": {"gameId": "\u00b2"}}) is None
    assert tp.has_record("\u00b2") is False and tp.load("\u00b2") is None


def test_superscript_member_values_read_as_absent_not_raised():
    doc = _eog()
    doc["players"][0]["ffaStanding"] = "\u00b2"
    doc["players"][0]["rank"] = "\u00b2"
    doc["players"][0]["boardPieces"][0]["level"] = "\u00b2"
    rec = tp.parse_eog(doc)
    assert rec is not None
    local = next(p for p in rec["players"] if p["is_local"])
    assert local["placement"] is None
    assert local["board"][0]["star"] is None


# -- S144-T-757: the game id range the store can list ---------------------------

@pytest.mark.parametrize("gid", [2 ** 63, 10 ** 19, 10 ** 25, 1e30])
def test_game_id_beyond_the_store_range_is_refused(gid, tmp_path):
    assert tp.parse_eog(dict(_eog(), gameId=gid)) is None
    assert tp.parse_gameclient_eog(dict(_block(), gameId=gid)) is None
    assert tp.parse_history(_hist_with(game_id=gid, gameId=gid), LOCAL_PUUID) == []
    assert tp.session_game_id({"gameData": {"gameId": gid}}) is None
    rec = dict(tp.parse_eog(_eog()), game_id=gid)
    assert tp.persist(rec, store_dir=tmp_path) is False
    assert list(tmp_path.iterdir()) == []
    assert tp.has_record(gid, store_dir=tmp_path) is False
    assert tp.load(gid, store_dir=tmp_path) is None


def test_largest_listable_game_id_round_trips(tmp_path):
    gid = 2 ** 63 - 1
    rec = tp.parse_eog(dict(_eog(), gameId=gid))
    assert rec["game_id"] == gid
    assert tp.persist(rec, store_dir=tmp_path) is True
    assert tp.latest(store_dir=tmp_path)["game_id"] == gid


# -- S144-T-758: one bad history game never loses the read ----------------------

@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"),
                                   1e300, 86_401, True, "2096"])
def test_history_junk_time_eliminated_reads_as_absent(value):
    doc = _hist_participant_with(time_eliminated=value)
    place = doc["games"][0]["json"]["participants"][0]["placement"]
    recs = tp.parse_history(doc, LOCAL_PUUID)
    assert len(recs) == 1
    by_place = {p["placement"]: p for p in recs[0]["players"]}
    assert by_place[place]["time_eliminated_s"] is None
    json.dumps(recs[0], allow_nan=False)


def test_history_time_eliminated_within_a_day_is_kept():
    doc = _hist_participant_with(time_eliminated=86_399.6)
    place = doc["games"][0]["json"]["participants"][0]["placement"]
    rec = tp.parse_history(doc, LOCAL_PUUID)[0]
    assert {p["placement"]: p for p in rec["players"]}[place]["time_eliminated_s"] == 86_400


@pytest.mark.parametrize("value", [float("inf"), float("nan"), 1e300])
def test_history_non_finite_game_length_reads_as_absent(value):
    recs = tp.parse_history(_hist_with(game_length=value), LOCAL_PUUID)
    assert len(recs) == 1 and recs[0]["game_length_s"] is None


@pytest.mark.parametrize("value", [10 ** 20, 10 ** 15, 9 * 10 ** 18])
def test_history_out_of_range_end_time_reads_as_absent(value):
    recs = tp.parse_history(_hist_with(game_datetime=value), LOCAL_PUUID)
    assert len(recs) == 1
    assert recs[0]["ended_at"] is None and recs[0]["ended_at_unix"] is None


def test_history_bad_game_does_not_cost_the_good_ones():
    doc = _hist()
    good = copy.deepcopy(doc["games"][0])
    good["json"]["game_id"] = GID + 1
    doc["games"][0]["json"]["participants"][0]["time_eliminated"] = float("inf")
    doc["games"][0]["json"]["game_datetime"] = 10 ** 20
    doc["games"].append(good)
    assert [r["game_id"] for r in tp.parse_history(doc, LOCAL_PUUID)] == [GID, GID + 1]


def test_history_real_values_are_unchanged():
    rec = tp.parse_history(_hist(), LOCAL_PUUID)[0]
    j = _hist()["games"][0]["json"]
    assert rec["ended_at_unix"] == int(j["game_datetime"]) / 1000.0
    assert rec["game_length_s"] == int(j["game_length"])
    p0 = j["participants"][0]
    by_place = {p["placement"]: p for p in rec["players"]}
    assert by_place[p0["placement"]]["time_eliminated_s"] == int(round(p0["time_eliminated"]))


# -- S144-T-759: history_path ---------------------------------------------------

@pytest.mark.parametrize("count", [float("nan"), float("inf"), "abc", None, True, [3]])
def test_history_path_junk_count_is_the_default(count):
    assert tp.history_path("p-1", count).endswith("?begin=0&count=5")


def test_history_path_bounds_are_unchanged():
    assert tp.history_path("p-1", 0).endswith("count=1")
    assert tp.history_path("p-1", 99).endswith("count=20")
    assert tp.history_path("p-1", 7).endswith("count=7")
    assert tp.history_path("p-1", "7").endswith("count=7")


@pytest.mark.parametrize("puuid", [None, 123, b"x", "", "   ", ["p"]])
def test_history_path_refuses_a_non_text_or_blank_puuid(puuid):
    with pytest.raises(ValueError):
        tp.history_path(puuid)


# -- S144-T-760: one local player at most ----------------------------------------

def test_eog_two_local_flags_mark_no_stranger_and_fall_back_to_local_block():
    doc = _eog()
    doc["players"][3]["isLocalPlayer"] = True          # placement 4, a stranger
    rec = tp.parse_eog(doc)
    assert [p["is_local"] for p in rec["players"]].count(True) == 0
    # the document's own localPlayer block still says placement 1 at 100 HP
    assert rec["local_placement"] == 1 and rec["local_hp"] == 100
    assert rec["set_core_name"] == "TFTSet18"


def test_eog_one_local_flag_is_unchanged():
    rec = tp.parse_eog(_eog())
    assert [p["is_local"] for p in rec["players"]] == [True] + [False] * 7
    assert rec["local_placement"] == 1 and rec["local_hp"] == 100
    assert rec["set_core_name"] == "TFTSet18"


# -- S144-T-761: the store reader ------------------------------------------------

def _store_good(tmp_path) -> None:
    tp.persist(tp.parse_eog(_eog(), now=1_700_000_000.0), store_dir=tmp_path)


def _write(tmp_path, name: str, payload) -> None:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    (tmp_path / name).write_text(text, encoding="utf-8")


def test_too_deep_store_file_is_skipped_not_raised(tmp_path):
    _store_good(tmp_path)
    _write(tmp_path, "1000000005.eog.json",
           '{"schema": 1, "a": ' + "[" * 100000 + "]" * 100000 + "}")
    assert tp.load(1000000005, store_dir=tmp_path) is None
    assert tp.latest(store_dir=tmp_path)["game_id"] == GID


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(players="junk"),
    lambda r: r.update(players=[5]),
    lambda r: r["players"][0].update(board="x"),
    lambda r: r["players"][0].update(traits=[{"name": ["x"], "id": None}]),
    lambda r: r["players"][0].update(placement="1"),
    lambda r: r["players"][0].update(augments=None),
    lambda r: r["players"][0]["board"][0].update(traits=None),
    lambda r: r.update(captured_at_unix="zz"),
    lambda r: r.update(ended_at_unix=[1]),
    lambda r: r.update(source="other"),
])
def test_shape_invalid_record_is_skipped_and_the_rest_still_serve(mutate, tmp_path):
    _store_good(tmp_path)
    bad_gid = 1000000005
    hist = tp.parse_history(_hist(), LOCAL_PUUID)[0]
    good_eog = dict(tp.parse_eog(_eog(), now=1_600_000_000.0), game_id=bad_gid)
    bad_hist = copy.deepcopy(dict(hist, game_id=bad_gid))
    mutate(bad_hist)
    _write(tmp_path, f"{bad_gid}.eog.json", good_eog)
    _write(tmp_path, f"{bad_gid}.history.json", bad_hist)
    rec = tp.load(bad_gid, store_dir=tmp_path)
    assert rec is not None and rec["sources"] == ["eog"]
    assert tp.latest(store_dir=tmp_path)["game_id"] in (GID, bad_gid)


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(players="junk"),
    lambda r: r["players"][0].update(is_local="yes"),
    lambda r: r["players"][0]["board"][0].update(star=float("nan")),
    lambda r: r.update(captured_at_unix=float("inf")),
    lambda r: r.update(schema=2),
])
def test_persist_refuses_a_record_the_reader_would_reject(mutate, tmp_path):
    rec = copy.deepcopy(tp.parse_eog(_eog()))
    mutate(rec)
    assert tp.persist(rec, store_dir=tmp_path) is False
    assert list(tmp_path.iterdir()) == []
    # the good record for the same game is still writable afterwards
    assert tp.persist(tp.parse_eog(_eog()), store_dir=tmp_path) is True


def test_store_with_only_a_bad_record_never_raises(tmp_path):
    rec = dict(tp.parse_eog(_eog()), captured_at_unix="zz")
    _write(tmp_path, f"{GID}.eog.json", rec)
    assert tp.load(GID, store_dir=tmp_path) is None
    assert tp.latest(store_dir=tmp_path) is None


def test_record_filed_under_another_game_id_is_not_served(tmp_path):
    rec = tp.parse_eog(_eog())                       # game GID
    _write(tmp_path, "1000000009.eog.json", rec)
    assert tp.load(1000000009, store_dir=tmp_path) is None


def test_record_filed_under_another_source_is_not_served(tmp_path):
    rec = tp.parse_eog(_eog())                       # source eog
    _write(tmp_path, f"{GID}.history.json", rec)
    assert tp.load(GID, store_dir=tmp_path) is None


def test_every_parser_output_round_trips_through_the_store_unchanged(tmp_path):
    eog = tp.parse_eog(_eog(), now=1_700_000_000.0)
    hist = tp.parse_history(_hist(), LOCAL_PUUID, now=1_700_000_100.0)[0]
    block = dict(tp.parse_gameclient_eog(_block(), now=1_800_000_000.0),
                 game_id=GID + 1)
    for r in (eog, hist, block):
        assert tp.persist(r, store_dir=tmp_path) is True
    assert tp.load(GID, store_dir=tmp_path) == tp.merge(eog, hist)
    assert tp.load(GID + 1, store_dir=tmp_path) == tp.merge(block, None)
    assert tp.latest(store_dir=tmp_path)["game_id"] == GID + 1


@pytest.mark.parametrize("stamp", ["NaN", "Infinity", "1e999"])
def test_record_with_a_non_finite_stamp_is_skipped(stamp, tmp_path):
    tp.persist(tp.parse_eog(_eog(), now=1_700_000_000.0), store_dir=tmp_path)
    b = dict(tp.parse_eog(_eog(), now=1_600_000_000.0), game_id=GID + 1)
    text = json.dumps(dict(b, captured_at_unix=12345.5)).replace("12345.5", stamp)
    _write(tmp_path, f"{GID + 1}.eog.json", text)
    assert tp.load(GID + 1, store_dir=tmp_path) is None
    assert tp.latest(store_dir=tmp_path)["game_id"] == GID
