"""True-audit s144 cycle 105 - core/augment_shadow.py.

core.augment_shadow is the do-not-flip-blind corpus writer behind the arena
augment-select Haiku call (coaches/arena_coach.py `_handle_augment_select`)
and the offline agreement reader over that corpus. One test (or one group)
per finding; line numbers in the names refer to the pre-fix file at
54756d93b.

  F1  rows were appended in text mode, so Windows wrote CRLF.
  F2  a torn last line (crash mid-append) glued the next row onto it.
  F3  summarize_agreement: ONE bad line (invalid JSON or non-UTF-8) set the
      whole corpus to [] - the report read zero rows, not "skips malformed".
  F4  summarize_agreement raised TypeError on a row whose "ranked" is a
      truthy non-list, breaking its "Never raises" contract.
  F5  _take_rank took the FIRST substring match, so a take that is a
      substring of a higher-ranked name scored false top-1 agreement. The
      live 16.21.1 augment table has 24 such pairs ("Stats!" /
      "Stats on Stats!", "DOOM" / "Doomsayer", ...).
  F6  a string-valued offered / picked was iterated one character at a time,
      and a non-list aug_reco passed the "has a ranking" gate.
  F7  non-string / padded names, non-string native fields and non-finite
      scores were written raw: an unserialisable value lost the row, NaN
      wrote a token strict JSON rejects.
  F8  the dedup signature was order-sensitive on offered while the docstring
      keys on the offered SET: a re-scan in another order wrote a duplicate.
  F9  the dedup check and the append were not serialised across threads.
  F10 failures were logged at DEBUG only (a silent empty corpus).
  F11 the docstring claimed "at most one record per distinct offer
      situation"; the dedup is consecutive (pinned here).
"""
from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path

import pytest

from core import augment_shadow as aug


@pytest.fixture(autouse=True)
def _fresh_dedup_state(monkeypatch):
    monkeypatch.setattr(aug, "_LAST_SIG", {})
    monkeypatch.setattr(aug, "_WARNED", set(), raising=False)


def _det(ranked=None, **over):
    if ranked is None:
        ranked = [
            {"id": 1, "name": "Blade Waltz", "score": 0.61, "conf": 0.4},
            {"id": 2, "name": "Goliath", "score": 0.55, "conf": 0.3},
        ]
    d = {
        "aug_reco": ranked,
        "aug_reco_top": "Blade Waltz",
        "aug_reco_top_score": 0.61,
        "aug_reco_conf": 0.4,
        "aug_reco_n_matches": 12,
        "aug_reco_external": True,
    }
    d.update(over)
    return d


def _state(**over):
    s = {
        "mode": "arena",
        "champion": "Jinx",
        "round": 2,
        "stage": None,
        "offered": ["Blade Waltz", "Goliath"],
        "picked": [],
    }
    s.update(over)
    return s


_NATIVE = {"take": "Blade Waltz", "why": "scales", "plan": "all-in"}


def _rows(p: Path) -> list[dict]:
    return [json.loads(ln) for ln in p.read_bytes().split(b"\n") if ln.strip()]


# ---------------------------------------------------------------- F1


def test_f1_rows_are_lf_terminated_ascii_bytes(tmp_path):
    p = tmp_path / "aug.jsonl"
    aug.log_augment_advice(_state(champion="Kai'Sa"), _NATIVE, _det(), path=p)
    aug.log_augment_advice(_state(champion="Nunu & Willump"), _NATIVE, _det(), path=p)
    data = p.read_bytes()
    assert b"\r" not in data
    assert data.endswith(b"\n")
    assert data.count(b"\n") == 2
    data.decode("ascii")


# ---------------------------------------------------------------- F2


def test_f2_torn_last_line_does_not_swallow_the_next_record(tmp_path):
    p = tmp_path / "aug.jsonl"
    p.write_bytes(b'{"ts": "torn", "offe')
    assert aug.log_augment_advice(_state(), _NATIVE, _det(), path=p) is not None
    lines = p.read_bytes().split(b"\n")
    assert lines[0] == b'{"ts": "torn", "offe'
    assert json.loads(lines[1])["native"]["take"] == "Blade Waltz"


# ---------------------------------------------------------------- F3


_GOOD = {"native": {"take": "Goliath"},
         "deterministic": {"ranked": [{"name": "Goliath"}]}}


def test_f3_one_invalid_line_does_not_zero_the_report(tmp_path):
    p = tmp_path / "aug.jsonl"
    p.write_bytes(json.dumps(_GOOD).encode() + b"\n{\"torn\n"
                  + json.dumps(_GOOD).encode() + b"\n")
    s = aug.summarize_agreement(p)
    assert s["n"] == 2
    assert s["top1_agree"] == 2


def test_f3_one_non_utf8_line_does_not_zero_the_report(tmp_path):
    p = tmp_path / "aug.jsonl"
    p.write_bytes(json.dumps(_GOOD).encode() + b"\n\xff\xfe junk\n")
    s = aug.summarize_agreement(p)
    assert s["n"] == 1
    assert s["top1_agree"] == 1


def test_f3_crlf_rows_written_before_the_fix_still_read(tmp_path):
    p = tmp_path / "aug.jsonl"
    p.write_bytes(json.dumps(_GOOD).encode() + b"\r\n"
                  + json.dumps(_GOOD).encode() + b"\r\n")
    assert aug.summarize_agreement(p)["n"] == 2


# ---------------------------------------------------------------- F4


@pytest.mark.parametrize("ranked", [5, 2.5, True, object()])
def test_f4_non_list_ranked_never_raises(ranked):
    rows = [{"native": {"take": "Goliath"}, "deterministic": {"ranked": ranked}},
            _GOOD]
    s = aug.summarize_agreement(rows)
    assert s["n"] == 2
    assert s["n_with_native_take"] == 2
    assert s["take_rank_dist"] == {"none": 1, "1": 1}


def test_f4_non_string_take_is_not_a_take():
    rows = [{"native": {"take": 5}, "deterministic": {"ranked": [{"name": "5"}]}}]
    s = aug.summarize_agreement(rows)
    assert s["n"] == 1
    assert s["n_with_native_take"] == 0


# ---------------------------------------------------------------- F5


@pytest.mark.parametrize(("short", "long"), [
    ("Stats!", "Stats on Stats!"),
    ("DOOM", "Doomsayer"),
    ("Recursion", "Ultimate Recursion"),
])
def test_f5_exact_name_beats_an_earlier_substring_match(short, long):
    ranked = [{"name": long}, {"name": short}]
    rows = [{"native": {"take": short}, "deterministic": {"ranked": ranked}}]
    s = aug.summarize_agreement(rows)
    assert s["top1_agree"] == 0
    assert s["take_rank_dist"] == {"2": 1}


def test_f5_longer_take_matches_its_own_name_not_its_prefix():
    ranked = [{"name": "Urf's Champion"}, {"name": "Quest: Urf's Champion"}]
    rows = [{"native": {"take": "Quest: Urf's Champion"},
             "deterministic": {"ranked": ranked}}]
    assert aug.summarize_agreement(rows)["take_rank_dist"] == {"2": 1}


def test_f5_variant_suffix_still_matches_the_most_specific_name():
    ranked = [{"name": "Stats!"}, {"name": "Stats on Stats!"}]
    rows = [{"native": {"take": "Stats on Stats! (Prismatic)"},
             "deterministic": {"ranked": ranked}}]
    assert aug.summarize_agreement(rows)["take_rank_dist"] == {"2": 1}


def test_f5_display_variant_fallback_kept():
    rows = [{"native": {"take": "Blade Waltz (Prismatic)"},
             "deterministic": {"ranked": [{"name": "Goliath"},
                                          {"name": "Blade Waltz"}]}}]
    assert aug.summarize_agreement(rows)["take_rank_dist"] == {"2": 1}


# ---------------------------------------------------------------- F6


def test_f6_string_offered_is_not_split_into_characters(tmp_path):
    p = tmp_path / "aug.jsonl"
    assert aug.log_augment_advice(_state(offered="Blade Waltz"), _NATIVE,
                                  _det(), path=p) is None
    assert not p.exists()


def test_f6_string_picked_is_not_split_into_characters(tmp_path):
    p = tmp_path / "aug.jsonl"
    rec = aug.log_augment_advice(_state(picked="Goliath"), _NATIVE, _det(), path=p)
    assert rec is not None
    assert _rows(p)[0]["picked"] == []


@pytest.mark.parametrize("reco", ["Blade Waltz", {"name": "x"}, 7, [1, "x", None]])
def test_f6_aug_reco_without_a_dict_row_is_a_gate_miss(tmp_path, reco):
    p = tmp_path / "aug.jsonl"
    assert aug.log_augment_advice(_state(), _NATIVE, _det(ranked=reco), path=p) is None
    assert not p.exists()


# ---------------------------------------------------------------- F7


def test_f7_names_stripped_and_non_strings_dropped(tmp_path):
    p = tmp_path / "aug.jsonl"
    rec = aug.log_augment_advice(
        _state(offered=["  Blade Waltz ", 5, None, {"x": 1}, "   ", "Goliath"],
               picked=[" Goliath", 3]),
        _NATIVE, _det(), path=p)
    assert rec is not None
    row = _rows(p)[0]
    assert row["offered"] == ["Blade Waltz", "Goliath"]
    assert row["picked"] == ["Goliath"]


def test_f7_only_non_string_offers_is_a_gate_miss(tmp_path):
    p = tmp_path / "aug.jsonl"
    assert aug.log_augment_advice(_state(offered=[1, None, "  "]), _NATIVE,
                                  _det(), path=p) is None
    assert not p.exists()


def test_f7_unserialisable_scalars_do_not_lose_the_row(tmp_path):
    p = tmp_path / "aug.jsonl"
    rec = aug.log_augment_advice(
        _state(mode=object(), champion={"n": 1}, round={1, 2}, stage=object()),
        {"take": object(), "why": 5, "plan": "go"},
        _det(ranked=[{"id": object(), "name": 7, "score": object(), "conf": "x"}],
             aug_reco_top=object(), aug_reco_n_matches=object()),
        path=p)
    assert rec is not None
    row = _rows(p)[0]
    assert row["mode"] is None and row["champion"] is None
    assert row["round"] is None and row["stage"] is None
    assert row["native"] == {"take": "", "why": "", "plan": "go"}
    assert row["deterministic"]["ranked"] == [
        {"id": None, "name": None, "score": None, "conf": None}]
    assert row["deterministic"]["top"] is None
    assert row["deterministic"]["n_matches"] is None


def test_f7_live_round_string_is_kept(tmp_path):
    # The live corpus records round "~30" (a string); it stays as written.
    p = tmp_path / "aug.jsonl"
    aug.log_augment_advice(_state(round="~30", stage=3), _NATIVE, _det(), path=p)
    row = _rows(p)[0]
    assert row["round"] == "~30" and row["stage"] == 3


def test_f7_non_finite_scores_become_null(tmp_path):
    p = tmp_path / "aug.jsonl"
    nan = float("nan")
    rec = aug.log_augment_advice(
        _state(),
        _NATIVE,
        _det(ranked=[{"id": 1, "name": "Blade Waltz", "score": nan,
                      "conf": float("inf")}],
             aug_reco_top_score=nan, aug_reco_conf=float("-inf")),
        path=p)
    assert rec is not None
    raw = p.read_bytes()
    assert b"NaN" not in raw and b"Infinity" not in raw
    row = _rows(p)[0]
    assert row["deterministic"]["ranked"][0]["score"] is None
    assert row["deterministic"]["ranked"][0]["conf"] is None
    assert row["deterministic"]["top_score"] is None
    assert row["deterministic"]["conf"] is None


def test_f7_finite_numbers_and_bools_kept(tmp_path):
    p = tmp_path / "aug.jsonl"
    aug.log_augment_advice(_state(), _NATIVE,
                           _det(aug_reco_external=False, aug_reco_n_matches=0),
                           path=p)
    det = _rows(p)[0]["deterministic"]
    assert det["external"] is False and det["n_matches"] == 0
    assert det["ranked"][0] == {"id": 1, "name": "Blade Waltz",
                                "score": 0.61, "conf": 0.4}
    assert not any(isinstance(v, float) and math.isnan(v)
                   for v in det["ranked"][0].values())


# ---------------------------------------------------------------- F8


def test_f8_reordered_offer_is_the_same_state(tmp_path):
    p = tmp_path / "aug.jsonl"
    assert aug.log_augment_advice(_state(offered=["Blade Waltz", "Goliath"]),
                                  _NATIVE, _det(), path=p) is not None
    assert aug.log_augment_advice(_state(offered=["Goliath", "Blade Waltz"]),
                                  _NATIVE, _det(), path=p) is None
    rows = _rows(p)
    assert len(rows) == 1
    assert rows[0]["offered"] == ["Blade Waltz", "Goliath"]


def test_f8_padding_does_not_make_a_new_state(tmp_path):
    p = tmp_path / "aug.jsonl"
    aug.log_augment_advice(_state(), _NATIVE, _det(), path=p)
    assert aug.log_augment_advice(_state(offered=[" Blade Waltz", "Goliath "]),
                                  _NATIVE, _det(), path=p) is None


# ---------------------------------------------------------------- F9


class _SlowJson:
    """json stand-in whose dumps sleeps, holding the check-then-write window
    open long enough for every thread to enter it."""

    def __init__(self, ev: threading.Event):
        self._ev = ev

    def dumps(self, *a, **k):
        self._ev.wait(0.05)
        return json.dumps(*a, **k)

    def __getattr__(self, name):
        return getattr(json, name)


def test_f9_concurrent_identical_offers_write_one_row(tmp_path, monkeypatch):
    p = tmp_path / "aug.jsonl"
    monkeypatch.setattr(aug, "json", _SlowJson(threading.Event()))
    n = 8
    barrier = threading.Barrier(n)
    results = []

    def _post():
        barrier.wait()
        results.append(aug.log_augment_advice(_state(), _NATIVE, _det(), path=p))

    threads = [threading.Thread(target=_post, name=f"aug-shadow-{i}")
               for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(results) == n
    assert sum(r is not None for r in results) == 1
    assert len(_rows(p)) == 1


# ---------------------------------------------------------------- F10


def _warns(caplog):
    return [r for r in caplog.records
            if r.name == "rc.augment_shadow" and r.levelno == logging.WARNING]


def test_f10_write_failure_warns_once_and_never_raises(tmp_path, caplog):
    target = tmp_path / "is_a_dir.jsonl"
    target.mkdir()
    caplog.set_level(logging.WARNING, logger="rc.augment_shadow")
    assert aug.log_augment_advice(_state(), _NATIVE, _det(), path=target) is None
    assert aug.log_augment_advice(_state(champion="Lux"), _NATIVE, _det(),
                                  path=target) is None
    assert len(_warns(caplog)) == 1


def test_f10_warning_rearms_after_a_successful_write(tmp_path, caplog, monkeypatch):
    p = tmp_path / "aug.jsonl"
    caplog.set_level(logging.WARNING, logger="rc.augment_shadow")
    real_open = Path.open

    def _boom(self, *a, **k):
        if self == p:
            raise PermissionError("locked")
        return real_open(self, *a, **k)

    monkeypatch.setattr(Path, "open", _boom)
    assert aug.log_augment_advice(_state(), _NATIVE, _det(), path=p) is None
    monkeypatch.setattr(Path, "open", real_open)
    assert aug.log_augment_advice(_state(), _NATIVE, _det(), path=p) is not None
    monkeypatch.setattr(Path, "open", _boom)
    assert aug.log_augment_advice(_state(champion="Lux"), _NATIVE, _det(),
                                  path=p) is None
    assert len(_warns(caplog)) == 2


def test_f10_failed_write_does_not_take_the_dedup_slot(tmp_path, monkeypatch):
    p = tmp_path / "aug.jsonl"
    real_open = Path.open

    def _boom(self, *a, **k):
        if self == p:
            raise PermissionError("locked")
        return real_open(self, *a, **k)

    monkeypatch.setattr(Path, "open", _boom)
    assert aug.log_augment_advice(_state(), _NATIVE, _det(), path=p) is None
    monkeypatch.setattr(Path, "open", real_open)
    assert aug.log_augment_advice(_state(), _NATIVE, _det(), path=p) is not None


# ---------------------------------------------------------------- F11


def test_f11_dedup_is_consecutive_only(tmp_path):
    p = tmp_path / "aug.jsonl"
    a = _state()
    b = _state(picked=["Goliath"])
    for st in (a, b, a):
        assert aug.log_augment_advice(st, _NATIVE, _det(), path=p) is not None
    assert len(_rows(p)) == 3
    assert "consecutive" in (aug.__doc__ or "").lower()
    assert "at most one record per distinct" not in " ".join((aug.__doc__ or "").split())
