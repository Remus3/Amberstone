"""s144 true-audit cycle 78 - core/archetype_picks.py hardening.

One test group per finding (F1-F7 in the cycle report):

* F1 (RM-1219 part 1): the store enforces its own distinct-champion cap
  INSIDE ``_PICKS_LOCK``, against the freshly re-read map. The route cap
  (``dashboard/routes_archetype.py`` ``_MAX_PICKS``) is an unlocked pre-check
  over the cached list, so two concurrent saves at cap - 1 both passed it.
  A store refusal is ``PicksFullError`` (a ``ValueError``) and the route
  answers it with the same 409 as its own pre-check.
* F2 (RM-1219 part 2): ``source="default"`` is not saveable. A persisted
  override labelled "default" is skipped by the nudge evaluator as
  not-operator-intent while it still overrides the DDragon default.
* F3: the store checks the champion key itself - a non-string raised
  AttributeError instead of ValueError, and a padded, overlong or
  control-character key was persisted as a key no lookup can hit.
* F4: ``get_archetype_for`` validates the persisted entry instead of trusting
  disk. A non-dict entry raised out of the resolver (into every consumer), an
  unknown primary was routed as-is, and a missing secondary came back absent.
* F5: ``list_archetype_picks`` returns copies of the entries, so a caller
  mutating one no longer rewrites the cached map ``get_archetype_for`` reads.
* F6: the module text matches the code (no picker UI, no localStorage copy,
  coach integration shipped, single writer process).
* F7: ``clear_archetype_pick`` with a non-string returns False instead of
  raising TypeError.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import pytest

from core import archetype_picks
from dashboard import routes_archetype


@pytest.fixture
def picks(tmp_path, monkeypatch):
    path = tmp_path / "cs_archetype_picks.json"
    monkeypatch.setattr(archetype_picks, "_PICKS_PATH", path)
    monkeypatch.setattr(archetype_picks, "_DATA_DIR", tmp_path)
    archetype_picks._invalidate_picks_cache()
    yield path
    archetype_picks._invalidate_picks_cache()


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    archetype_picks._invalidate_picks_cache()


def _entry(champion, primary="tank", secondary="bruiser", source="user_cs"):
    return {"champion": champion, "primary": primary, "secondary": secondary,
            "source": source, "set_at": "2026-10-31T00:00:00Z"}


class _H:
    def __init__(self, path="/api/cs-archetype-pick"):
        self.path = path
        self.status = None
        self.body = b""

    def _send(self, status, body, ctype):
        self.status = status
        self.body = body

    def json(self):
        return json.loads(self.body.decode("utf-8"))


# ------------------------------------------------------------------ F1 cap

def test_f1_store_refuses_a_new_champion_at_the_cap(picks, monkeypatch):
    monkeypatch.setattr(archetype_picks, "MAX_PICKS", 2)
    archetype_picks.save_archetype_pick("Aatrox", "tank")
    archetype_picks.save_archetype_pick("Ahri", "mage")
    before = picks.read_bytes()
    with pytest.raises(archetype_picks.PicksFullError):
        archetype_picks.save_archetype_pick("Akali", "assassin")
    assert picks.read_bytes() == before
    assert "Akali" not in archetype_picks.list_archetype_picks()


def test_f1_picks_full_error_is_a_value_error():
    assert issubclass(archetype_picks.PicksFullError, ValueError)


def test_f1_resave_of_an_existing_champion_at_the_cap_works(picks, monkeypatch):
    monkeypatch.setattr(archetype_picks, "MAX_PICKS", 1)
    archetype_picks.save_archetype_pick("Aatrox", "tank")
    archetype_picks.save_archetype_pick("Aatrox", "bruiser")
    assert archetype_picks.get_archetype_for("Aatrox")["primary"] == "bruiser"


def test_f1_cap_is_checked_against_the_disk_map_not_the_cache(picks, monkeypatch):
    # Another writer filled the file after this process cached an empty map.
    monkeypatch.setattr(archetype_picks, "MAX_PICKS", 2)
    assert archetype_picks.list_archetype_picks() == {}
    picks.write_text(json.dumps({"Aatrox": _entry("Aatrox"),
                                 "Ahri": _entry("Ahri")}), encoding="utf-8")
    with pytest.raises(archetype_picks.PicksFullError):
        archetype_picks.save_archetype_pick("Akali", "assassin")


def test_f1_two_concurrent_saves_at_cap_minus_one_land_only_one(picks, monkeypatch):
    monkeypatch.setattr(archetype_picks, "MAX_PICKS", 3)
    _write(picks, {"Aatrox": _entry("Aatrox"), "Ahri": _entry("Ahri")})
    # Both threads finish every pre-lock step before either takes the lock,
    # so an unlocked check over the cached map would let both through.
    barrier = threading.Barrier(2, timeout=10)
    real_now = archetype_picks._now_iso

    def _now():
        barrier.wait()
        return real_now()

    monkeypatch.setattr(archetype_picks, "_now_iso", _now)
    results = {}

    def _save(name):
        try:
            archetype_picks.save_archetype_pick(name, "tank", "bruiser")
            results[name] = "ok"
        except archetype_picks.PicksFullError:
            results[name] = "full"

    threads = [threading.Thread(target=_save, args=(n,), name=f"t-{n}")
               for n in ("Akali", "Alistar")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert sorted(results.values()) == ["full", "ok"]
    on_disk = json.loads(picks.read_text(encoding="utf-8"))
    assert len(on_disk) == 3


def test_f1_refusal_is_logged_without_the_champion(picks, monkeypatch, caplog):
    monkeypatch.setattr(archetype_picks, "MAX_PICKS", 1)
    archetype_picks.save_archetype_pick("Aatrox", "tank")
    with caplog.at_level(logging.WARNING, logger="rc.archetype_picks"):
        with pytest.raises(archetype_picks.PicksFullError) as info:
            archetype_picks.save_archetype_pick("Zzsecretname", "tank")
    assert "Zzsecretname" not in caplog.text
    assert "Zzsecretname" not in str(info.value)
    assert "cap" in caplog.text


def test_f1_default_cap_covers_the_roster_with_room():
    assert 200 <= archetype_picks.MAX_PICKS <= 4096


def test_f1_route_answers_a_store_cap_refusal_with_409(picks, monkeypatch):
    # The route pre-check passes (its own cap is untouched); the store refuses.
    monkeypatch.setattr(archetype_picks, "MAX_PICKS", 1)
    archetype_picks.save_archetype_pick("Aatrox", "tank")
    before = picks.read_bytes()
    h = _H()
    routes_archetype._serve_archetype_post(h, {"champion": "Ahri",
                                               "primary": "tank"})
    assert h.status == 409
    assert h.json() == {"error": "too many saved picks - clear one first"}
    assert picks.read_bytes() == before


# --------------------------------------------------------------- F2 source

def test_f2_source_default_is_refused(picks):
    with pytest.raises(ValueError):
        archetype_picks.save_archetype_pick("Aatrox", "tank", source="default")
    assert not picks.exists()


def test_f2_refusal_text_does_not_list_default_as_valid(picks):
    with pytest.raises(ValueError) as info:
        archetype_picks.save_archetype_pick("Aatrox", "tank", source="bogus")
    assert "'default'" not in str(info.value)
    assert "'user_cs'" in str(info.value)


def test_f2_saveable_sources_are_valid_sources_minus_default():
    assert archetype_picks.SAVEABLE_SOURCES == (
        archetype_picks.VALID_SOURCES - {archetype_picks.SOURCE_DEFAULT})
    # The resolver label set is unchanged.
    assert archetype_picks.SOURCE_DEFAULT in archetype_picks.VALID_SOURCES


@pytest.mark.parametrize("source", ["user_cs", "user_ingame", "nudge"])
def test_f2_operator_sources_still_save(picks, source):
    entry = archetype_picks.save_archetype_pick("Aatrox", "tank", source=source)
    assert entry["source"] == source


# ------------------------------------------------------------- F3 champion

@pytest.mark.parametrize("bad", [5, None, b"Aatrox", ["Aatrox"]])
def test_f3_non_string_champion_is_a_value_error(picks, bad):
    with pytest.raises(ValueError):
        archetype_picks.save_archetype_pick(bad, "tank")
    assert not picks.exists()


@pytest.mark.parametrize("bad", [
    " Aatrox", "Aatrox ", "Aat\nrox", "Aat\x00rox", "Aat\x1brox",
    "A" * (archetype_picks.MAX_CHAMPION_LEN + 1),
])
def test_f3_unusable_champion_key_is_refused(picks, bad):
    with pytest.raises(ValueError) as info:
        archetype_picks.save_archetype_pick(bad, "tank")
    assert bad not in str(info.value)
    assert not picks.exists()


def test_f3_max_length_champion_still_saves(picks):
    name = "A" * archetype_picks.MAX_CHAMPION_LEN
    archetype_picks.save_archetype_pick(name, "tank")
    assert archetype_picks.get_archetype_for(name)["primary"] == "tank"


def test_f3_display_names_with_spaces_and_punctuation_save(picks):
    for name in ("Kai'Sa", "Nunu & Willump", "Dr. Mundo", "Tahm Kench"):
        archetype_picks.save_archetype_pick(name, "tank")
    assert set(archetype_picks.list_archetype_picks()) == {
        "Kai'Sa", "Nunu & Willump", "Dr. Mundo", "Tahm Kench"}


# ------------------------------------------------------- F4 on-disk entries

@pytest.mark.parametrize("raw", ["tank", 5, None, ["primary", "tank"], []])
def test_f4_non_dict_entry_falls_back_to_the_default(picks, raw):
    _write(picks, {"Aatrox": raw})
    got = archetype_picks.get_archetype_for("Aatrox")
    assert got["champion"] == "Aatrox"
    assert "set_at" not in got
    assert got["source"] == archetype_picks.SOURCE_DEFAULT
    assert (got["primary"], got["secondary"]) == \
        archetype_picks.default_for_champion("Aatrox")


@pytest.mark.parametrize("primary", ["bogus", None, 3, ["tank"], ""])
def test_f4_unknown_primary_falls_back_to_the_default(picks, primary):
    _write(picks, {"Aatrox": _entry("Aatrox", primary=primary)})
    got = archetype_picks.get_archetype_for("Aatrox")
    assert got["source"] == archetype_picks.SOURCE_DEFAULT
    assert got["primary"] == archetype_picks.default_for_champion("Aatrox")[0]


@pytest.mark.parametrize("secondary", ["bogus", None, 3, ["mage"]])
def test_f4_bad_secondary_is_rederived_and_the_pick_kept(picks, secondary):
    raw = _entry("Aatrox", primary="tank", secondary=secondary)
    _write(picks, {"Aatrox": raw})
    got = archetype_picks.get_archetype_for("Aatrox")
    assert got["primary"] == "tank"
    assert got["source"] == "user_cs"
    assert got["secondary"] in archetype_picks.ARCHETYPE_SET
    assert got["secondary"] != "tank"


def test_f4_missing_secondary_is_rederived(picks):
    raw = _entry("Aatrox", primary="tank")
    del raw["secondary"]
    _write(picks, {"Aatrox": raw})
    got = archetype_picks.get_archetype_for("Aatrox")
    assert got["secondary"] in archetype_picks.ARCHETYPE_SET


@pytest.mark.parametrize("source", [["user_cs"], 7, "bogus"])
def test_f4_bad_source_reads_as_default(picks, source):
    _write(picks, {"Aatrox": _entry("Aatrox", source=source)})
    got = archetype_picks.get_archetype_for("Aatrox")
    assert got["primary"] == "tank"
    assert got["source"] == archetype_picks.SOURCE_DEFAULT


def test_f4_valid_entry_is_returned_unchanged(picks):
    raw = _entry("Aatrox", primary="tank", secondary="mage", source="nudge")
    _write(picks, {"Aatrox": raw})
    assert archetype_picks.get_archetype_for("Aatrox") == raw


def test_f4_onhit_entry_is_routable(picks):
    # "onhit" is a dispatcher archetype the default path already returns.
    raw = _entry("Gwen", primary="onhit", secondary="bruiser")
    _write(picks, {"Gwen": raw})
    assert archetype_picks.get_archetype_for("Gwen") == raw


def test_f4_bad_entry_warns_once_not_per_read(picks, caplog):
    _write(picks, {"Aatrox": "tank"})
    with caplog.at_level(logging.WARNING, logger="rc.archetype_picks"):
        for _ in range(5):
            archetype_picks.get_archetype_for("Aatrox")
    lines = [r for r in caplog.records if "unusable" in r.getMessage()]
    assert len(lines) == 1


def test_f4_bad_entry_warning_cache_is_bounded(picks, monkeypatch, caplog):
    monkeypatch.setattr(archetype_picks, "_MAX_WARNED_KEYS", 3)
    _write(picks, {f"C{i}": "x" for i in range(10)})
    with caplog.at_level(logging.WARNING, logger="rc.archetype_picks"):
        for _ in range(4):
            for i in range(10):
                archetype_picks.get_archetype_for(f"C{i}")
    assert len(archetype_picks._WARNED_BAD_KEYS) <= 3
    # Past the bound, further bad keys stay quiet instead of warning per read.
    lines = [r for r in caplog.records if "unusable" in r.getMessage()]
    assert len(lines) == 3


# --------------------------------------------------------- F5 list aliasing

def test_f5_mutating_a_listed_entry_does_not_change_the_resolver(picks):
    archetype_picks.save_archetype_pick("Aatrox", "tank", "bruiser")
    listed = archetype_picks.list_archetype_picks()
    listed["Aatrox"]["primary"] = "mage"
    listed["Ahri"] = _entry("Ahri")
    assert archetype_picks.get_archetype_for("Aatrox")["primary"] == "tank"
    assert "Ahri" not in archetype_picks.list_archetype_picks()


def test_f5_mutating_a_resolved_entry_does_not_change_the_cache(picks):
    archetype_picks.save_archetype_pick("Aatrox", "tank", "bruiser")
    got = archetype_picks.get_archetype_for("Aatrox")
    got["primary"] = "mage"
    assert archetype_picks.get_archetype_for("Aatrox")["primary"] == "tank"


# ------------------------------------------------------------ F6 doc drift

def test_f6_module_text_matches_the_code():
    src = archetype_picks.__doc__ or ""
    assert "Coach integration (each coach reading" not in src
    assert "lands in a follow-up session" not in src
    text = Path(archetype_picks.__file__).read_text(encoding="utf-8")
    assert "atomic replace invalidates other readers" not in text
    assert "Keep stable - localStorage" not in text
    assert "single writer process" in text


# ------------------------------------------------------------ F7 clear type

@pytest.mark.parametrize("bad", [["Aatrox"], {"a": 1}, 5, None, b"Aatrox"])
def test_f7_clear_with_a_non_string_returns_false(picks, bad):
    archetype_picks.save_archetype_pick("Aatrox", "tank")
    before = picks.read_bytes()
    assert archetype_picks.clear_archetype_pick(bad) is False
    assert picks.read_bytes() == before


@pytest.mark.parametrize("bad", [["Aatrox"], {"a": 1}, 5])
def test_f7_resolve_with_a_non_string_is_the_blank_fallback(picks, bad):
    got = archetype_picks.get_archetype_for(bad)
    assert got == archetype_picks.get_archetype_for("")


def test_f7_clear_still_removes_a_real_pick(picks):
    archetype_picks.save_archetype_pick("Aatrox", "tank")
    assert archetype_picks.clear_archetype_pick("Aatrox") is True
    assert archetype_picks.list_archetype_picks() == {}
