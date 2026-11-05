"""Lane 8 (true-audit) s144 cycle 117 - core/aram_comp_verdict.py hardening.

One test group per finding (provisional ids, the merger mints RM ids):

  RM-1471 a failed champion-index load was cached FOREVER (the loaded flag
             was set before the read), and a concurrent caller saw the flag
             with a half-built (empty) index.
  RM-1472 a junk champions.json shape (top-level list, non-dict "data",
             a too-deep document) raised out of compute_factors.
  RM-1473 junk champion fields (info / stats as a list, tags as an int,
             a non-finite attack range) raised or counted a NaN / inf range as
             ranged.
  RM-1474 a UTF-8 BOM in current.txt (PowerShell 5.1 write) emptied the
             index.
  RM-1475 a current.txt token carrying a path segment read a
             champions.json outside the DS data dir.
  RM-1476 comp_verdict returned ok=True with a fabricated verdict when
             fewer than 3 names resolved (docstring: ok=False).
  RM-1477 junk call args (a str / dict / int team) were iterated as
             characters or keys, or raised.
  RM-1478 the POST /api/aram-comp-verdict body reaches comp_verdict
             verbatim: unbounded team / bench / name lengths cost unbounded
             lookups and echoed an unbounded my_champion into the reason.
  RM-1479 a DDragon id (MonkeyKing, Nunu, Renata) did not resolve, and the
             engage / sustain sets were matched on the raw string only.
  RM-1480 the comp_verdict backstop logged at DEBUG, so an unexpected
             failure was invisible in logs/.

Synthetic champions.json fixtures live under tmp_path; no live ports.
"""
from __future__ import annotations

import json
import logging
import threading

import pytest

from core import aram_comp_verdict as cv
from core import failed_load_gate


def _champ(name, *, cid=None, rng=125, attack=7, magic=2, tags=("Fighter",)):
    return {
        "id": cid or name.replace(" ", ""),
        "name": name,
        "stats": {"attackrange": rng},
        "info": {"attack": attack, "magic": magic},
        "tags": list(tags),
    }


_SYNTH = {
    "Malphite": _champ("Malphite", tags=("Tank",), attack=5, magic=7),
    "Ashe": _champ("Ashe", rng=600, tags=("Marksman",)),
    "Lux": _champ("Lux", rng=550, attack=2, magic=9, tags=("Mage",)),
    "Garen": _champ("Garen"),
    "Soraka": _champ("Soraka", rng=550, attack=2, magic=7, tags=("Support",)),
}


def _plant(root, patch="16.1.1", data=None, raw=None, current=None):
    pdir = root / patch
    pdir.mkdir(parents=True, exist_ok=True)
    body = raw if raw is not None else json.dumps({"data": data or _SYNTH})
    (pdir / "champions.json").write_text(body, encoding="utf-8")
    (root / "current.txt").write_text(
        patch if current is None else current, encoding="utf-8")
    return pdir


@pytest.fixture
def iso(tmp_path, monkeypatch):
    """Point the module at an empty tmp DS dir with a fresh cache."""
    root = tmp_path / "ds"
    root.mkdir()
    monkeypatch.setattr(cv, "_DS_DATA_DIR", root)
    cv._reset_cache()
    yield root
    cv._reset_cache()


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(failed_load_gate.time, "monotonic", lambda: now[0])
    return now


# --- RM-1471 failed load not cached; no half-built index -----------------

def test_t151_failed_load_heals_after_backoff(iso, clock, caplog):
    caplog.set_level(logging.WARNING, logger="rc.core.aram_comp_verdict")
    assert cv.compute_factors(["Malphite"])["n"] == 0
    # A second failure in the same streak (window elapsed, still missing)
    # does not warn again.
    clock[0] += 60.0
    assert cv.compute_factors(["Malphite"])["n"] == 0
    _plant(iso)
    # Inside the backoff window the loader stays off the disk.
    assert cv.compute_factors(["Malphite"])["n"] == 0
    clock[0] += 60.0
    assert cv.compute_factors(["Malphite"])["n"] == 1
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) == 1, [r.getMessage() for r in warns]


def test_t151_success_is_cached_by_identity(iso):
    _plant(iso)
    first = cv._load_index()
    assert first and cv._load_index() is first


def test_t151_concurrent_caller_never_sees_half_built_index(iso, monkeypatch):
    _plant(iso)
    real = cv._read_champions
    seen = {}

    def _other():
        seen["idx"] = dict(cv._load_index())

    def _slow_read(path):
        t = threading.Thread(target=_other, name="t151-reader", daemon=True)
        t.start()
        t.join(0.3)  # the reader must be held off while this load runs
        seen["thread"] = t
        return real(path)

    monkeypatch.setattr(cv, "_read_champions", _slow_read)
    assert cv._load_index()
    seen["thread"].join(5.0)
    assert set(seen["idx"]) == {cv._norm(n) for n in _SYNTH}


# --- RM-1472 junk champions.json shapes ---------------------------------

@pytest.mark.parametrize("raw", [
    "[1, 2, 3]",
    '{"data": [1, 2]}',
    '{"data": "Malphite"}',
    '"just a string"',
    "[" * 100000 + "]" * 100000,
    "not json at all",
], ids=["list", "data-list", "data-str", "str", "too-deep", "not-json"])
def test_t152_junk_document_never_raises(iso, raw):
    _plant(iso, raw=raw)
    f = cv.compute_factors(["Malphite", "Ashe", "Lux"])
    assert f["n"] == 0
    out = cv.comp_verdict({"my_team": ["Malphite", "Ashe", "Lux"]})
    assert out["ok"] is False


# --- RM-1473 junk champion fields ---------------------------------------

def test_t153_junk_fields_never_raise(iso):
    data = {
        "A": {"name": "Alpha", "info": [1, 2], "stats": [3], "tags": 5},
        "B": {"name": "Beta", "info": "x", "stats": "y", "tags": None},
        "C": {"name": 12345},
        "D": "not a dict",
    }
    _plant(iso, data=data)
    f = cv.compute_factors(["Alpha", "Beta"])
    assert f["n"] == 2
    assert f["ranged_count"] == 0 and f["frontline_count"] == 0
    assert f["hybrid_count"] == 2


@pytest.mark.parametrize("rng", [float("nan"), float("inf"), -900.0, True])
def test_t153_nonsense_range_is_not_ranged(rng):
    assert cv._stat_range({"stats": {"attackrange": rng}}) == 0.0


def test_t153_tag_substring_is_not_a_tag():
    champ = {"tags": "Tanky Fighters", "stats": {"attackrange": 125}}
    assert cv._is_frontline(champ) is False


def test_t153_nonfinite_rating_reads_hybrid():
    assert cv._damage_lean({"info": {"attack": float("nan"), "magic": 3}}) == "hybrid"
    assert cv._damage_lean({"info": {"attack": float("inf"), "magic": 3}}) == "hybrid"


# --- RM-1474 BOM in current.txt -----------------------------------------

def test_t154_bom_current_txt_resolves(iso):
    _plant(iso, current=chr(0xFEFF) + "16.1.1\n")
    assert cv._resolve_patch() == "16.1.1"
    assert cv.compute_factors(["Malphite"])["n"] == 1


# --- RM-1475 path-segment patch token refused ---------------------------

@pytest.mark.parametrize("token", ["../outside", "..\\outside", "C:outside",
                                   "a/b", ".."])
def test_t155_path_segment_token_refused(iso, token):
    outside = iso.parent / "outside"
    outside.mkdir(exist_ok=True)
    (outside / "champions.json").write_text(
        json.dumps({"data": _SYNTH}), encoding="utf-8")
    (iso / "current.txt").write_text(token, encoding="utf-8")
    assert cv._resolve_patch() is None
    assert cv.compute_factors(["Malphite"])["n"] == 0


# --- RM-1476 ok=False when fewer than 3 names resolve -------------------

def test_t156_unresolvable_team_is_ok_false():
    out = cv.comp_verdict({"my_team": ["Zzz1", "Zzz2", "Zzz3", "Malphite"],
                           "my_champion": "Malphite"})
    assert out["ok"] is False
    assert out["reason"] == "(insufficient team data)"


def test_t156_empty_index_is_ok_false(iso):
    out = cv.comp_verdict({"my_team": ["Malphite", "Ashe", "Lux", "Garen"],
                           "my_champion": "Malphite"})
    assert out["ok"] is False


def test_t156_three_resolvable_plus_junk_still_judged():
    out = cv.comp_verdict({"my_team": ["Malphite", "Ashe", "Lux", "Zzz1", "Zzz2"],
                           "my_champion": "Malphite"})
    assert out["ok"] is True
    assert out["factors"]["n"] == 3


# --- RM-1477 junk call args ---------------------------------------------

@pytest.mark.parametrize("team", [5, 3.5, object(), "Malphite",
                                  {"Malphite": 1, "Ashe": 2, "Lux": 3}, b"Lux"])
def test_t157_junk_team_arg_is_empty(team):
    f = cv.compute_factors(team)
    assert f["n"] == 0 and f["engage_count"] == 0 and f["sustain_count"] == 0


def test_t157_sequence_kinds_accepted():
    for team in (["Malphite", "Ashe"], ("Malphite", "Ashe"),
                 {"Malphite", "Ashe"}, frozenset({"Malphite", "Ashe"})):
        assert cv.compute_factors(team)["n"] == 2


def test_t157_junk_entries_skipped():
    f = cv.compute_factors([None, 5, {"x": 1}, ["Lux"], "Malphite", True])
    assert f["n"] == 1


@pytest.mark.parametrize("field", ["my_team", "bench"])
def test_t157_dict_or_str_state_lists_ignored(field):
    state = {"my_team": ["Garen", "Darius", "Jax", "Sett", "Aatrox"],
             "my_champion": "Garen", "bench": ["Ashe"]}
    state[field] = {"Malphite": 1, "Ashe": 2, "Lux": 3, "Leona": 4}
    out = cv.comp_verdict(state)
    if field == "my_team":
        assert out["ok"] is False
    else:
        assert out["swap_to"] == ""


@pytest.mark.parametrize("variants", ["ap", 5, {"key": "ap"},
                                      [{"key": 7}, {"key": ""}, "ap"]])
def test_t157_junk_variants_skipped(variants):
    state = {"my_team": ["Garen", "Darius", "Jax", "Sett", "Aatrox"],
             "my_champion": "Garen",
             "variants": variants, "current_variant": ["x"]}
    out = cv.comp_verdict(state)
    assert out["ok"] is True and out["variant_to"] == ""


# --- RM-1478 bounded request body ---------------------------------------

def test_t158_lookups_bounded_on_huge_lists(monkeypatch):
    calls = [0]
    real = cv._lookup

    def _count(name):
        calls[0] += 1
        return real(name)

    monkeypatch.setattr(cv, "_lookup", _count)
    junk = [f"Junk{i}" for i in range(20000)]
    state = {"my_team": ["Garen", "Darius", "Jax", "Sett", "Aatrox", *junk],
             "my_champion": "Garen",
             "bench": [*junk, "Ashe"]}
    cv.comp_verdict(state)
    assert calls[0] < 2000, calls[0]


def test_t158_huge_names_not_echoed():
    huge = "Q" * 100000
    out = cv.comp_verdict({"my_team": ["Garen", "Darius", "Jax", "Sett", "Aatrox"],
                           "my_champion": huge, "bench": ["Ashe", huge]})
    assert huge[:200] not in json.dumps(out)


def test_t158_huge_variant_label_not_echoed():
    huge = "L" * 100000
    out = cv.comp_verdict({"my_team": ["Garen", "Darius", "Jax", "Sett", "Aatrox"],
                           "my_champion": "Garen",
                           "variants": [{"key": "ap", "label": huge}]})
    assert out["recommendation"] == "variant"
    assert len(out["reason"]) < 500


# --- RM-1479 DDragon id aliases -----------------------------------------

def test_t159_ddragon_ids_resolve_and_match_curated_sets():
    f = cv.compute_factors(["MonkeyKing", "Nunu", "Renata"])
    assert f["n"] == 3
    assert f["engage_count"] == 2  # Wukong + Nunu & Willump
    assert f["sustain_count"] == 1  # Renata Glasc


def test_t159_bench_id_alias_fixes_engage_and_sustain():
    assert cv._bench_addresses("MonkeyKing", "engage", None, {}) is True
    assert cv._bench_addresses("Renata", "sustain", None, {}) is True
    assert cv._bench_addresses("Renata", "engage", None, {}) is False


def test_t159_display_names_unchanged():
    f = cv.compute_factors(["Wukong", "Nunu & Willump", "Renata Glasc"])
    assert f["n"] == 3 and f["engage_count"] == 2 and f["sustain_count"] == 1


def test_t159_index_values_stay_one_per_champion():
    vals = list(cv._load_index().values())
    names = [c["name"] for c in vals]
    assert len(names) == len(set(names))


def test_t159_name_beats_a_colliding_id(iso):
    data = {
        "Alpha": _champ("Beta", cid="Alpha", rng=600),
        "Beta": _champ("Alpha", cid="Beta", rng=125),
    }
    _plant(iso, data=data)
    assert cv._lookup("Alpha")["stats"]["attackrange"] == 125


# --- RM-1480 backstop logs at WARNING -----------------------------------

def test_t160_backstop_warns(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="rc.core.aram_comp_verdict")

    def _boom(_f):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(cv, "_ordered_gaps", _boom)
    out = cv.comp_verdict({"my_team": ["Garen", "Darius", "Jax", "Sett"],
                           "my_champion": "Garen"})
    assert out["ok"] is False
    assert any("comp_verdict" in r.getMessage() for r in caplog.records)
