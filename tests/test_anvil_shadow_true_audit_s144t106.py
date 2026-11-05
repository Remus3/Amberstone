"""s144 true-audit cycle 106 - core/anvil_shadow.py writer and reader.

core.anvil_shadow records the arena item-anvil Haiku take next to the
deterministic core.precomputed_anvil_advisor ranking (coaches/arena_coach.py
_handle_anvil) and summarises their agreement offline. It is the direct
sibling of core.augment_shadow (cycle 105, RM-1382) and carried the same
writer and reader defects. Each test below names its finding; 22 failed on
the pre-fix module. Six are characterization guards that also passed on it
(concurrent distinct rows, a string round, a display variant, the no-ranking
top-1 fallback, and a str / dict ranking): they pin behaviour the rewrite
had to keep.

Writer:
  F1  rows were appended in text mode, so Windows wrote CRLF.
  F2  a torn last line glued the next row onto it (two rows lost, not one).
  F3  the dedup check and the append ran without a lock, so two threads with
      the same state both passed the check.
  F4  a failed write was logged at DEBUG only.
  F10 the dedup key was order-sensitive on offered, although the docstring
      calls it the offered set.
  F11 the docstring claimed "at most one record per distinct offer"; the
      dedup is consecutive.
  F12 a string offered was iterated per character.
  F13 non-string, blank or padded names were written raw.
  F14 an unserialisable scalar lost the row, and NaN wrote a non-JSON token.
  F15 a non-string native take / why was written raw.

Reader (summarize_agreement):
  F5  one invalid or non-UTF-8 line made the whole report read zero rows.
  F6  the first substring match won, so "Boots" scored the rank and the top-1
      of "Boots of Swiftness" (a real DDragon pair).
  F7  a truthy non-iterable "ranked" raised TypeError despite "Never raises".
  F8  a non-string take counted as a take.
  F9  a bool rank (bool is an int) became the bucket "True".
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
import types

import pytest

from core import anvil_shadow as anv


@pytest.fixture(autouse=True)
def _reset_state():
    anv._LAST_SIG.clear()
    warned = getattr(anv, "_WARNED", None)
    if warned is not None:
        warned.clear()
    yield
    anv._LAST_SIG.clear()
    if warned is not None:
        warned.clear()


def _det(take="Kraken Slayer", ranked=None):
    if ranked is None:
        ranked = [
            {"name": "Kraken Slayer", "rank": 1, "in_ideal_path": True},
            {"name": "Bloodthirster", "rank": 3, "in_ideal_path": True},
        ]
    return {"take": take, "take_rank": 1, "n_matches": 2, "conf": "ok",
            "ranked": ranked, "ideal_path": ["Kraken Slayer", "Bloodthirster"]}


def _state(offered=None, owned=None, champ="ChampA", **extra):
    st = {"mode": "arena", "champion": champ, "round": 3,
          "offered": ["Kraken Slayer", "Bloodthirster"] if offered is None else offered,
          "owned": [] if owned is None else owned}
    st.update(extra)
    return st


def _strict_rows(path):
    """Every line parsed as STRICT JSON (NaN / Infinity refused)."""
    def _no_constant(tok):
        raise ValueError(f"non-JSON token {tok}")
    out = []
    for raw in path.read_bytes().split(b"\n"):
        if raw.strip():
            out.append(json.loads(raw.decode("ascii"), parse_constant=_no_constant))
    return out


# --- writer -----------------------------------------------------------------

def test_f1_rows_are_lf_terminated_ascii_bytes(tmp_path):
    p = tmp_path / "anv.jsonl"
    assert anv.log_anvil_advice(_state(), {"take": "Kraken Slayer"}, _det(), path=p)
    assert anv.log_anvil_advice(_state(owned=["Boots"]), {"take": "Kraken Slayer"},
                                _det(), path=p)
    data = p.read_bytes()
    assert b"\r" not in data
    assert data.endswith(b"\n") and data.count(b"\n") == 2
    data.decode("ascii")


def test_f2_a_torn_last_line_costs_one_row_not_two(tmp_path):
    p = tmp_path / "anv.jsonl"
    p.write_bytes(b'{"ts": "torn')
    rec = anv.log_anvil_advice(_state(), {"take": "Kraken Slayer"}, _det(), path=p)
    assert rec is not None
    lines = p.read_bytes().split(b"\n")
    assert lines[0] == b'{"ts": "torn'
    assert json.loads(lines[1])["offered"] == ["Kraken Slayer", "Bloodthirster"]
    assert anv.summarize_agreement(p)["n"] == 1


def test_f3_dedup_check_and_append_are_one_critical_section(tmp_path, monkeypatch):
    """Two threads with the same state: exactly one row. json.dumps is slowed
    so an unlocked check-then-write lets both threads pass the dedup."""
    p = tmp_path / "anv.jsonl"
    real = json.dumps

    def slow_dumps(*a, **k):
        time.sleep(0.05)
        return real(*a, **k)

    monkeypatch.setattr(anv, "json", types.SimpleNamespace(
        dumps=slow_dumps, loads=json.loads, JSONDecodeError=json.JSONDecodeError))
    gate = threading.Barrier(4)
    results = []

    def worker():
        gate.wait()
        results.append(anv.log_anvil_advice(_state(), {"take": "Kraken Slayer"},
                                            _det(), path=p))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sum(r is not None for r in results) == 1
    assert len(_strict_rows(p)) == 1


def test_f3_concurrent_distinct_rows_all_parse(tmp_path):
    p = tmp_path / "anv.jsonl"

    def worker(i):
        for j in range(25):
            anv.log_anvil_advice(_state(owned=[f"Item{i}_{j}"]),
                                 {"take": "Kraken Slayer"}, _det(), path=p)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(_strict_rows(p)) == 100


def test_f4_a_failed_write_warns_once_per_target_until_a_success(tmp_path, caplog):
    bad = tmp_path / "is_a_dir"
    bad.mkdir()
    caplog.set_level(logging.DEBUG, logger="rc.anvil_shadow")
    assert anv.log_anvil_advice(_state(), {"take": "x"}, _det(), path=bad) is None
    assert anv.log_anvil_advice(_state(owned=["B"]), {"take": "x"}, _det(),
                                path=bad) is None
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1
    assert "is_a_dir" in warns[0].getMessage()


def test_f4_a_success_rearms_the_warning(tmp_path, caplog):
    p = tmp_path / "anv.jsonl"
    caplog.set_level(logging.DEBUG, logger="rc.anvil_shadow")
    p.mkdir()
    assert anv.log_anvil_advice(_state(), {"take": "x"}, _det(), path=p) is None
    p.rmdir()
    assert anv.log_anvil_advice(_state(owned=["B"]), {"take": "x"}, _det(), path=p)
    p.unlink()
    p.mkdir()
    assert anv.log_anvil_advice(_state(owned=["C"]), {"take": "x"}, _det(),
                                path=p) is None
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 2


def test_f10_dedup_keys_on_the_offered_set(tmp_path):
    p = tmp_path / "anv.jsonl"
    assert anv.log_anvil_advice(_state(["Kraken Slayer", "Bloodthirster"]),
                                {"take": "x"}, _det(), path=p)
    assert anv.log_anvil_advice(_state(["Bloodthirster", "Kraken Slayer"]),
                                {"take": "x"}, _det(), path=p) is None
    assert len(_strict_rows(p)) == 1


def test_f11_dedup_is_consecutive_and_the_docstring_says_so(tmp_path):
    p = tmp_path / "anv.jsonl"
    a, b = _state(["Kraken Slayer"]), _state(["Bloodthirster"])
    for st in (a, b, a):
        assert anv.log_anvil_advice(st, {"take": "x"}, _det(), path=p) is not None
    assert len(_strict_rows(p)) == 3
    doc = anv.__doc__ or ""
    assert "at most one record per distinct offer" not in doc
    assert "CONSECUTIVE" in doc


def test_f12_a_string_offer_is_not_read_per_character(tmp_path):
    p = tmp_path / "anv.jsonl"
    assert anv.log_anvil_advice(_state("Kraken Slayer"), {"take": "x"}, _det(),
                                path=p) is None
    assert not p.exists()
    assert anv.log_anvil_advice(_state(["Kraken Slayer"], owned="Boots"),
                                {"take": "x"}, _det(), path=p)
    assert _strict_rows(p)[0]["owned"] == []


def test_f13_names_are_stripped_strings_only(tmp_path):
    p = tmp_path / "anv.jsonl"
    rec = anv.log_anvil_advice(
        _state([" Kraken Slayer ", 5, None, {"x": 1}, "   ", "Bloodthirster"],
               owned=[" Boots ", 7, ""]),
        {"take": "x"}, _det(), path=p)
    assert rec is not None
    row = _strict_rows(p)[0]
    assert row["offered"] == ["Kraken Slayer", "Bloodthirster"]
    assert row["owned"] == ["Boots"]
    assert anv.log_anvil_advice(_state([5, None, "  "]), {"take": "x"}, _det(),
                                path=tmp_path / "none.jsonl") is None


def test_f14_unserialisable_and_non_finite_values_write_null(tmp_path):
    p = tmp_path / "anv.jsonl"
    det = _det(ranked=[
        {"name": "Kraken Slayer", "rank": float("nan"), "in_ideal_path": "yes"},
        {"name": 9, "rank": True, "in_ideal_path": True},
        "not-a-row",
    ])
    det["take_rank"] = math.inf
    det["n_matches"] = {1, 2}
    det["conf"] = object()
    rec = anv.log_anvil_advice(_state(round=object(), champion=["x"]),
                               {"take": "Kraken Slayer"}, det, path=p)
    assert rec is not None
    row = _strict_rows(p)[0]
    assert row["round"] is None
    assert row["champion"] is None
    d = row["deterministic"]
    assert d["take_rank"] is None and d["n_matches"] is None and d["conf"] is None
    assert d["ranked"] == [
        {"name": "Kraken Slayer", "rank": None, "in_ideal_path": None},
        {"name": None, "rank": None, "in_ideal_path": True},
    ]


def test_f14_a_string_round_is_kept(tmp_path):
    """The gated read-back carries a string round ("~5"); a JSON-safe scalar
    is written as is."""
    p = tmp_path / "anv.jsonl"
    assert anv.log_anvil_advice(_state(round="~5"), {"take": "x"}, _det(), path=p)
    assert _strict_rows(p)[0]["round"] == "~5"


def test_f15_native_fields_are_strings(tmp_path):
    p = tmp_path / "anv.jsonl"
    assert anv.log_anvil_advice(_state(), {"take": 5, "why": None}, _det(), path=p)
    assert _strict_rows(p)[0]["native"] == {"take": "", "why": ""}


# --- reader -----------------------------------------------------------------

def _row(take, det_take, ranked):
    return {"offered": [r["name"] for r in ranked], "native": {"take": take},
            "deterministic": {"take": det_take, "ranked": ranked}}


def test_f5_one_bad_line_skips_only_itself(tmp_path):
    p = tmp_path / "anv.jsonl"
    good = json.dumps(_row("Kraken Slayer", "Kraken Slayer",
                           [{"name": "Kraken Slayer", "rank": 1}])).encode("ascii")
    p.write_bytes(good + b"\r\n" + b"{not json\n" + b"\xff\xfe\n" + good + b"\n")
    s = anv.summarize_agreement(p)
    assert s["n"] == 2
    assert s["top1_agree"] == 2


def test_f6_an_exact_name_beats_an_earlier_substring():
    ranked = [{"name": "Boots of Swiftness", "rank": 1},
              {"name": "Boots", "rank": 4}]
    s = anv.summarize_agreement([_row("Boots", "Boots of Swiftness", ranked)])
    assert s["take_rank_dist"] == {"4": 1}
    assert s["top1_agree"] == 0


def test_f6_the_longest_substring_wins():
    ranked = [{"name": "Boots", "rank": 1},
              {"name": "Boots of Swiftness", "rank": 3}]
    s = anv.summarize_agreement([_row("Boots of Swiftness (Arena)", "Boots", ranked)])
    assert s["take_rank_dist"] == {"3": 1}
    assert s["top1_agree"] == 0


def test_f6_a_display_variant_still_agrees():
    ranked = [{"name": "Talisman Of Ascension", "rank": 2},
              {"name": "Bloodthirster", "rank": 5}]
    s = anv.summarize_agreement(
        [_row("Veigar's Talisman of Ascension", "Talisman Of Ascension", ranked)])
    assert s["take_rank_dist"] == {"2": 1}
    assert s["top1_agree"] == 1


def test_f6_top1_without_a_ranking_falls_back_to_the_name():
    rows = [{"native": {"take": "kraken slayer"},
             "deterministic": {"take": "Kraken Slayer"}}]
    s = anv.summarize_agreement(rows)
    assert s["top1_agree"] == 1
    assert s["take_rank_dist"] == {"none": 1}


@pytest.mark.parametrize("ranked", [5, 2.5, True, "Kraken Slayer", {"name": "x"}])
def test_f7_a_non_list_ranking_never_raises(ranked):
    rows = [{"native": {"take": "Kraken Slayer"},
             "deterministic": {"take": "Kraken Slayer", "ranked": ranked}}]
    s = anv.summarize_agreement(rows)
    assert s["n"] == 1 and s["n_with_native_take"] == 1
    assert s["take_rank_dist"] == {"none": 1}


@pytest.mark.parametrize("take", [5, ["Kraken Slayer"], {"x": 1}, "   "])
def test_f8_only_a_non_blank_string_is_a_take(take):
    rows = [{"native": {"take": take},
             "deterministic": {"take": "Kraken Slayer",
                               "ranked": [{"name": "Kraken Slayer", "rank": 1}]}}]
    s = anv.summarize_agreement(rows)
    assert s["n"] == 1
    assert s["n_with_native_take"] == 0
    assert s["take_rank_dist"] == {}


def test_f9_a_bool_rank_is_not_a_rank():
    ranked = [{"name": "Kraken Slayer", "rank": True}]
    s = anv.summarize_agreement([_row("Kraken Slayer", "Kraken Slayer", ranked)])
    assert s["take_rank_dist"] == {"none": 1}
