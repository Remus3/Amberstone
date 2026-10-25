"""TFT-03 (docs/TFT_PROGRAM.md section 3.6 + section 7): the runtime TFT icon cache.

Acceptance: `scripts/fetch_tft_icons.py --set 18` fills the gitignored icon
cache with an index, from the LCU-local `lol-game-data` assets first and
CommunityDragon second; offline-safe, rate-limited, passive GET only; guard:
no tracked file under `data/tft/` and no new tracked png under `tft/`; NOTICE
line added.

NO NETWORK. Every source here is a fake, or the module's own sources with
`urllib.request.urlopen` replaced by a recorder. Icon bytes are tiny
synthetic PNG / JPEG headers, never Riot art.

Measured shapes the fakes mirror (passive LCU GET-only, live Set 18 client,
2026-10-25, session 134):
- `/lol-game-data/assets/v1/tftsets.json` = {"LCTFTModeData": {"mDefaultSet":
  {"SetName": "TFTSet18", "SetCoreName": "TFTSet18", ...}, "mActiveSets": [...],
  "mEventSet": {...}, ...}}.
- `tftchampions.json` = list of {"name", "character_record": {"character_id",
  "display_name", "traits", "squareIconPath" (.png)}} - 826 rows; every one of
  the 74 Set 18 extract units has a path.
- `tftchampions-teamplanner.json` = {"TFTSet17": [...], "TFTSet18": [65 rows of
  {"character_id", "squareIconPath" (.jpg), "team_planner_code", ...}]}.
- `tfttraits.json` = list of {"trait_id", "set" ("TFTSet18"), "icon_path"} -
  534 rows, 36 for TFTSet18, no duplicate trait_id.
- `tftitems.json` = list of {"nameId", "squareIconPath", "name", "guid", "id",
  "color"} - 6474 rows, NO set field, 4140 duplicate nameIds (every duplicate
  of a Set 18 member carries the same path); augments live here too.
- Icon GETs answer 200 image/png (or image/jpeg for the planner .jpg); an
  unknown asset answers 400.
- CommunityDragon serves the same plugin files and assets under
  raw.communitydragon.org/<branch>/plugins/rcp-be-lol-game-data/global/default/
  with the path after `/lol-game-data/assets/` lowercased (two icons measured
  200 image/png).

Existing APIs used (file:line at HEAD 5004e7986):
- tft/tft_set.py:67 `parse_set_id`, :193 `load_cdragon` (the tracked reduced
  extract supplies set membership: units / traits / items / augments apiNames,
  scripts/fetch_cdragon_tft.py:103 `build_extract`).
- lcu/lcu_client.py:54 `_parse_lockfile_fields` (lockfile -> port, password).
- tests/_repo_walk.py:121 `tracked_relpaths` (the git index, ADR-015).
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests import _repo_walk
from tests._module_view import bind_urlopen
from tft.assets import icon_cache as ic

REPO_ROOT = Path(__file__).resolve().parent.parent
P = "/lol-game-data/assets/ASSETS/"
PNG = b"\x89PNG\r\n\x1a\n"
JPG = b"\xff\xd8\xff\xe0\x00\x10JFIF"


def png(tag: str) -> bytes:
    return PNG + b"synthetic-" + tag.encode("ascii")


def jpg(tag: str) -> bytes:
    return JPG + b"synthetic-" + tag.encode("ascii")


YORICK_PNG = P + "Characters/TFT18_Yorick/TFT18_Yorick_Square.TFT_Set18.png"
YORICK_JPG = P + "Characters/TFT18_Yorick/TFT18_Yorick_Square.TFT_Set18.jpg"
GROMP_PNG = P + "Characters/TFT18_Gromp/TFT18_Gromp_Square.TFT_Set18.png"
KOBUKO_JPG = P + "Characters/TFT18_Kobuko/TFT18_Kobuko_Square.TFT_Set18.jpg"
ADAPTOR = P + "UX/TraitIcons/Trait_Icon_18_Adaptor.TFT_Set18.png"
BFSWORD = P + "Maps/TFT/Icons/Items/Hexcore/TFT_Item_BFSword.png"
SHARED = P + "Maps/TFT/Icons/Items/Hexcore/Shared.png"
GRABBAG = P + "Maps/TFT/Icons/Augments/Hexcore/Grab-Bag-II.png"

DOCS = {
    "tftchampions.json": [
        {"name": "TFT_BlueGolem", "character_record": {
            "character_id": "TFT_BlueGolem", "traits": [],
            "squareIconPath": P + "Characters/TFT_BlueGolem/HUD/TFT_BlueGolem_Spell.png"}},
        {"name": "DA_18_Yorick", "character_record": {
            "character_id": "DA_18_Yorick", "display_name": "Yorick",
            "squareIconPath": YORICK_PNG}},
        {"name": "DA_Gromp18_AP", "character_record": {
            "character_id": "DA_Gromp18_AP", "display_name": "Gromp",
            "squareIconPath": GROMP_PNG}},
    ],
    "tftchampions-teamplanner.json": {
        "TFTSet17": [{"character_id": "TFT17_Jinx", "squareIconPath": P + "x/jinx.jpg"}],
        "TFTSet18": [
            {"character_id": "DA_18_Yorick", "squareIconPath": YORICK_JPG,
             "team_planner_code": 1001},
            {"character_id": "DA_18_Kobuko", "squareIconPath": KOBUKO_JPG,
             "team_planner_code": 1002},
        ],
    },
    "tfttraits.json": [
        {"trait_id": "Assassin", "set": "TFTSet1",
         "icon_path": P + "UX/TraitIcons/Trait_Icon_Assassin.png"},
        {"trait_id": "DA_18_Adaptor", "set": "TFTSet18", "icon_path": ADAPTOR},
    ],
    "tftitems.json": [
        {"nameId": "TFT_Item_BFSword", "squareIconPath": BFSWORD},
        {"nameId": "TFT_Item_BFSword", "squareIconPath": BFSWORD},
        {"nameId": "DA_18_SharedA", "squareIconPath": SHARED},
        {"nameId": "DA_18_SharedB", "squareIconPath": SHARED},
        {"nameId": "DA_18_NoPath", "squareIconPath": ""},
        {"nameId": "DA_18_BigGrabBag", "squareIconPath": GRABBAG},
    ],
}

EXTRACT = {
    "_set": 18,
    "units": [{"apiName": "DA_18_Yorick"}, {"apiName": "DA_Gromp18_AP"},
              {"apiName": "DA_18_Kobuko"}],
    "traits": [{"apiName": "DA_18_Adaptor"}, {"apiName": "DA_18_Gone"}],
    "items": [{"apiName": "TFT_Item_BFSword"}, {"apiName": "DA_18_SharedA"},
              {"apiName": "DA_18_SharedB"}, {"apiName": "DA_18_NoPath"}],
    "augments": [{"apiName": "DA_18_BigGrabBag"}],
}

ASSETS = {
    YORICK_PNG: png("yorick"), YORICK_JPG: jpg("yorick"), GROMP_PNG: png("gromp"),
    KOBUKO_JPG: jpg("kobuko"), ADAPTOR: png("adaptor"), BFSWORD: png("bfsword"),
    SHARED: png("shared"), GRABBAG: png("grabbag"),
}

TFTSETS = {"LCTFTModeData": {
    "mDefaultSet": {"SetName": "TFTSet18", "SetCoreName": "TFTSet18",
                    "SetDisplayName": "Enchanted Wilds"},
    "mEventSet": {"SetName": "TFTSet17", "SetCoreName": "TFTSet17"},
    "mActiveSets": [{"SetName": "TFTSet17", "SetCoreName": "TFTSet17"},
                    {"SetName": "TFTSet18", "SetCoreName": "TFTSet18"}],
}}


class FakeSource:
    def __init__(self, name, docs=None, assets=None, *, tftsets=None, queue=None,
                 min_interval_s=0.0):
        self.name = name
        self.docs = docs if docs is not None else {}
        self.assets = assets if assets is not None else {}
        self.min_interval_s = min_interval_s
        self._tftsets = tftsets
        self._queue = queue
        self.doc_calls: list = []
        self.asset_calls: list = []

    def game_data(self, doc):
        self.doc_calls.append(doc)
        return copy.deepcopy(self.docs.get(doc))

    def asset(self, path):
        self.asset_calls.append(path)
        return self.assets.get(path)

    def tftsets(self):
        return copy.deepcopy(self._tftsets)

    def queue_id(self):
        return self._queue


def lcu(**kw):
    kw.setdefault("docs", DOCS)
    kw.setdefault("assets", ASSETS)
    return FakeSource("lcu", **kw)


def cdragon(**kw):
    kw.setdefault("docs", DOCS)
    kw.setdefault("assets", ASSETS)
    return FakeSource("cdragon", **kw)


def fill(tmp_path, sources, **kw):
    kw.setdefault("extract", EXTRACT)
    kw.setdefault("sleep", lambda s: None)
    return ic.fill_cache(18, sources, root=tmp_path, **kw)


def index(tmp_path, n=18):
    return json.loads((ic.set_dir(n, root=tmp_path) / ic.INDEX_NAME).read_bytes())


# -- set detection: tftsets.json mDefaultSet + queue id --------------------------

def test_running_set_reads_the_default_set_core_name():
    assert ic.running_set(TFTSETS) == 18
    assert ic.running_set(TFTSETS, queue_id=1100) == 18


def test_queue_6110_runs_set_17_whatever_the_default_set_says():
    # LCU inventory 2026-10-25: queue 6110 is the "Set 17 (Normal)" revival.
    # One table: tft/tft_set.py QUEUE_SETS (LT-01), aliased, never copied.
    from tft import tft_set
    assert ic.QUEUE_SET is tft_set.QUEUE_SETS
    assert ic.QUEUE_SET[6110] == 17
    assert ic.running_set(TFTSETS, queue_id=6110) == 17
    assert ic.running_set(None, queue_id=6110) == 17


@pytest.mark.parametrize("doc", [None, {}, [], {"LCTFTModeData": None},
                                 {"LCTFTModeData": {"mDefaultSet": None}},
                                 {"LCTFTModeData": {"mDefaultSet": {"SetCoreName": "x"}}}])
def test_running_set_is_none_when_unreadable(doc):
    assert ic.running_set(doc) is None


def test_detect_set_asks_the_first_source_that_can_answer():
    no_lcu = FakeSource("cdragon")
    assert ic.detect_set([no_lcu]) is None
    src = lcu(tftsets=TFTSETS, queue=6110)
    assert ic.detect_set([src, no_lcu]) == 17
    assert ic.detect_set([lcu(tftsets=TFTSETS, queue=1090)]) == 18
    assert ic.detect_set([lcu(tftsets=TFTSETS, queue=1090)], queue_id=6110) == 17


# -- catalogue: membership from the extract, paths from game data ----------------

def test_catalogue_takes_membership_from_the_extract_and_paths_from_game_data():
    cat = ic.build_catalogue(18, DOCS, EXTRACT)
    assert cat.membership == "extract"
    assert cat.paths["champion"] == {
        "DA_18_Yorick": YORICK_PNG,      # tftchampions.json png beats the planner jpg
        "DA_Gromp18_AP": GROMP_PNG,
        "DA_18_Kobuko": KOBUKO_JPG,      # planner only
    }
    assert cat.paths["trait"] == {"DA_18_Adaptor": ADAPTOR}
    assert cat.paths["item"] == {"TFT_Item_BFSword": BFSWORD, "DA_18_SharedA": SHARED,
                                 "DA_18_SharedB": SHARED}
    assert cat.paths["augment"] == {"DA_18_BigGrabBag": GRABBAG}
    assert cat.missing == {"champion": [], "trait": ["DA_18_Gone"],
                           "item": ["DA_18_NoPath"], "augment": []}
    # The non-member PvE golem and the Set 1 trait never enter the catalogue.
    flat = {a for paths in cat.paths.values() for a in paths}
    assert "TFT_BlueGolem" not in flat and "Assassin" not in flat


def test_catalogue_without_an_extract_falls_back_to_game_data_membership():
    cat = ic.build_catalogue(18, DOCS, None)
    assert cat.membership == "game_data"
    assert cat.paths["champion"] == {"DA_18_Yorick": YORICK_PNG, "DA_18_Kobuko": KOBUKO_JPG}
    assert cat.paths["trait"] == {"DA_18_Adaptor": ADAPTOR}
    # tftitems.json carries no set field (measured), so no item membership.
    assert cat.paths["item"] == {} and cat.paths["augment"] == {}


def test_catalogue_drops_unsafe_asset_paths():
    docs = copy.deepcopy(DOCS)
    docs["tfttraits.json"][1]["icon_path"] = "/lol-game-data/assets/../../etc/x.png"
    cat = ic.build_catalogue(18, docs, EXTRACT)
    assert "DA_18_Adaptor" not in cat.paths["trait"]
    assert "DA_18_Adaptor" in cat.missing["trait"]


def test_catalogue_membership_matches_the_tracked_set18_extract_counts():
    from tft import tft_set
    extract = tft_set.load_cdragon(18, root=REPO_ROOT)
    assert extract.get("_counts"), "tracked data/meta/tft_set18_cdragon.json missing"
    cat = ic.build_catalogue(18, {}, extract)
    counts = extract["_counts"]
    wanted = {c: len(cat.paths[c]) + len(cat.missing[c]) for c in ic.CATEGORIES}
    assert wanted == {"champion": counts["units"], "trait": counts["traits"],
                      "item": counts["items"], "augment": counts["augments"]}


# -- path + URL hygiene ----------------------------------------------------------

@pytest.mark.parametrize("path", [
    YORICK_PNG, YORICK_JPG, ADAPTOR,
    "/lol-game-data/assets/ASSETS/Maps/TFT/Icons/Augments/Hexcore/Grab-Bag-II.png",
])
def test_valid_asset_paths(path):
    assert ic.valid_asset_path(path)


@pytest.mark.parametrize("path", [
    None, "", 5, "ASSETS/UX/x.png", "/lol-game-data/assets/../x.png",
    "/lol-game-data/assets/ASSETS/a/../../b.png", "/lol-game-data/assets/ASSETS\\x.png",
    "/lol-game-data/assets/ASSETS/x.png?y=1", "/lol-game-data/assets/ASSETS/x.png#y",
    "/lol-game-data/assets/ASSETS/x.json", "https://example.invalid/x.png",
    "/lol-game-data/assets/ASSETS/x .png", "/lol-game-data/assets/ASSETS//x.png",
    "/lol-game-data/assets/ASSETS/" + chr(0xE9) + ".png",
])
def test_invalid_asset_paths(path):
    assert not ic.valid_asset_path(path)


def test_cdragon_url_maps_the_plugin_path_lowercased():
    # Both URLs below answered 200 image/png on 2026-10-25.
    assert ic.cdragon_url(ADAPTOR) == (
        "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/"
        "default/assets/ux/traiticons/trait_icon_18_adaptor.tft_set18.png")
    assert ic.cdragon_url(YORICK_PNG, branch="pbe").startswith(
        "https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/"
        "assets/characters/tft18_yorick/")
    with pytest.raises(ValueError):
        ic.cdragon_url("/lol-game-data/assets/../x.png")
    with pytest.raises(ValueError):
        ic.cdragon_url(ADAPTOR, branch="evil/../x")


def test_image_kind_sniffs_magic_bytes_only():
    assert ic.image_kind(png("a")) == "png"
    assert ic.image_kind(jpg("a")) == "jpg"
    assert ic.image_kind(b"<html>nope</html>") is None
    assert ic.image_kind(b"") is None
    assert ic.image_kind(None) is None


def test_file_stem_is_safe_and_case_collision_free():
    assert ic.file_stem("DA_18_Yorick") == "DA_18_Yorick"
    bad = ic.file_stem("../evil/name")
    assert "/" not in bad and "\\" not in bad and not bad.startswith(".")
    assert re.fullmatch(r"[A-Za-z0-9_.-]+", bad)
    assert ic.file_stem("CON").upper() != "CON"
    assert ic.file_stem("a b") != ic.file_stem("a_b")
    used: dict = {}
    first = ic.file_stem("DA_18_Lux", used=used)
    second = ic.file_stem("da_18_lux", used=used)
    assert first.casefold() != second.casefold()
    assert ic.file_stem("DA_18_Lux", used=used) == first   # same api, same stem


# -- fill: LCU first, CommunityDragon second -------------------------------------

def test_fill_writes_icons_and_an_index_with_sha256(tmp_path):
    rep = fill(tmp_path, [lcu(), cdragon()])
    assert rep.status == "partial"          # DA_18_Gone + DA_18_NoPath have no path
    assert rep.catalogue_source == "lcu"
    idx = index(tmp_path)
    assert idx["schema"] == ic.INDEX_SCHEMA and idx["set"] == 18
    ent = idx["entries"]
    assert sorted(ent) == sorted(ic.CATEGORIES)
    yorick = ent["champion"]["DA_18_Yorick"]
    assert yorick["file"] == "champion/DA_18_Yorick.png"
    assert yorick["src"] == "lcu" and yorick["asset"] == YORICK_PNG
    body = (ic.set_dir(18, root=tmp_path) / yorick["file"]).read_bytes()
    assert body == png("yorick")
    assert yorick["sha256"] == hashlib.sha256(body).hexdigest()
    assert yorick["bytes"] == len(body)
    kobuko = ent["champion"]["DA_18_Kobuko"]
    assert kobuko["file"] == "champion/DA_18_Kobuko.jpg"     # extension from magic
    assert set(ent["item"]) == {"TFT_Item_BFSword", "DA_18_SharedA", "DA_18_SharedB"}
    assert ent["augment"]["DA_18_BigGrabBag"]["file"] == "augment/DA_18_BigGrabBag.png"
    assert idx["missing"]["trait"] == ["DA_18_Gone"]
    assert idx["missing"]["item"] == ["DA_18_NoPath"]
    assert rep.counts["champion"]["fetched"] == 3
    assert rep.by_source == {"lcu": 7}       # 8 icons, SharedA/SharedB share one GET
    raw = (ic.set_dir(18, root=tmp_path) / ic.INDEX_NAME).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_each_icon_tries_the_lcu_first_then_cdragon(tmp_path):
    assets = dict(ASSETS)
    del assets[ADAPTOR]
    first = lcu(assets=assets)
    second = cdragon()
    rep = fill(tmp_path, [first, second])
    ent = index(tmp_path)["entries"]
    assert ent["trait"]["DA_18_Adaptor"]["src"] == "cdragon"
    assert ent["champion"]["DA_18_Yorick"]["src"] == "lcu"
    assert second.asset_calls == [ADAPTOR]
    assert second.doc_calls == []            # the LCU answered every game-data doc
    assert rep.by_source == {"lcu": 6, "cdragon": 1}


def test_catalogue_comes_from_cdragon_when_the_lcu_is_absent(tmp_path):
    down = lcu(docs={}, assets={})
    rep = fill(tmp_path, [down, cdragon()])
    assert rep.catalogue_source == "cdragon"
    ent = index(tmp_path)["entries"]
    assert {e["src"] for c in ent.values() for e in c.values()} == {"cdragon"}
    assert down.doc_calls == [ic.DOC_CHAMPIONS]   # first unanswered doc ends the try
    assert down.asset_calls == []                 # a source that failed the catalogue is not asked


def test_a_source_that_keeps_failing_is_dropped_for_the_rest_of_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(ic, "SOURCE_FAIL_LIMIT", 2)
    dying = lcu(assets={})
    backup = cdragon()
    rep = fill(tmp_path, [dying, backup])
    assert len(dying.asset_calls) == 2
    assert rep.by_source == {"cdragon": 7}


def test_offline_leaves_the_cache_untouched(tmp_path):
    fill(tmp_path, [lcu()])
    idx_path = ic.set_dir(18, root=tmp_path) / ic.INDEX_NAME
    before = idx_path.read_bytes()
    files_before = sorted(p.name for p in ic.set_dir(18, root=tmp_path).rglob("*"))
    rep = fill(tmp_path, [lcu(docs={}, assets={}), cdragon(docs={}, assets={})],
               force=True)
    assert rep.status == "offline"
    assert idx_path.read_bytes() == before
    assert sorted(p.name for p in ic.set_dir(18, root=tmp_path).rglob("*")) == files_before


def test_offline_with_no_cache_writes_nothing(tmp_path):
    rep = fill(tmp_path, [lcu(docs={}, assets={})])
    assert rep.status == "offline"
    assert not (tmp_path / "data").exists()


def test_no_sources_is_offline_not_an_error(tmp_path):
    assert fill(tmp_path, []).status == "offline"


def test_rerun_reuses_the_cache_and_fetches_nothing(tmp_path):
    fill(tmp_path, [lcu()])
    again = lcu()
    rep = fill(tmp_path, [again])
    assert again.asset_calls == []
    assert rep.counts["champion"] == {"wanted": 3, "cached": 3, "fetched": 0,
                                      "failed": 0, "skipped": 0}
    assert rep.status == "partial"


def test_a_changed_asset_path_or_a_tampered_file_is_refetched(tmp_path):
    fill(tmp_path, [lcu()])
    d = ic.set_dir(18, root=tmp_path)
    (d / "champion" / "DA_Gromp18_AP.png").write_bytes(png("tampered"))
    docs = copy.deepcopy(DOCS)
    new_adaptor = P + "UX/TraitIcons/Trait_Icon_18_Adaptor_v2.TFT_Set18.png"
    docs["tfttraits.json"][1]["icon_path"] = new_adaptor
    assets = dict(ASSETS)
    assets[new_adaptor] = png("adaptor-v2")
    again = lcu(docs=docs, assets=assets)
    fill(tmp_path, [again])
    assert sorted(again.asset_calls) == sorted([GROMP_PNG, new_adaptor])
    ent = index(tmp_path)["entries"]
    assert (d / ent["champion"]["DA_Gromp18_AP"]["file"]).read_bytes() == png("gromp")
    assert ent["trait"]["DA_18_Adaptor"]["asset"] == new_adaptor


def test_force_refetches_everything(tmp_path):
    fill(tmp_path, [lcu()])
    again = lcu()
    fill(tmp_path, [again], force=True)
    assert len(again.asset_calls) == 7


def test_non_image_bytes_are_refused_and_never_written(tmp_path):
    assets = dict(ASSETS)
    assets[GRABBAG] = b"<html>error page</html>"
    rep = fill(tmp_path, [lcu(assets=assets)])
    assert "DA_18_BigGrabBag" not in index(tmp_path)["entries"]["augment"]
    assert not (ic.set_dir(18, root=tmp_path) / "augment").exists() or not any(
        (ic.set_dir(18, root=tmp_path) / "augment").iterdir())
    assert rep.counts["augment"]["failed"] == 1
    assert ("augment", "DA_18_BigGrabBag", "no source returned an image") in rep.failures


def test_limit_caps_network_fetches_per_run(tmp_path):
    src = lcu()
    rep = fill(tmp_path, [src], limit=2)
    assert len(src.asset_calls) == 2
    assert sum(c["skipped"] for c in rep.counts.values()) > 0


def test_dry_run_fetches_no_icon_and_writes_nothing(tmp_path):
    src = lcu()
    rep = fill(tmp_path, [src], dry_run=True)
    assert rep.status == "dry_run"
    assert src.asset_calls == []
    assert not (tmp_path / "data").exists()
    assert rep.counts["champion"]["wanted"] == 3
    assert (rep.planned, rep.planned_gets) == (8, 7)   # SharedA + SharedB = one GET
    assert "would fetch 8 icons in 7 GETs" in rep.summary()


def test_categories_filter(tmp_path):
    rep = fill(tmp_path, [lcu()], categories=("trait",))
    ent = index(tmp_path)["entries"]
    assert ent["trait"] and not ent["champion"] and not ent["item"]
    assert set(rep.counts) == {"trait"}
    with pytest.raises(ValueError):
        fill(tmp_path, [lcu()], categories=("skins",))


def test_network_gets_are_rate_limited_per_source(tmp_path):
    now = [0.0]
    slept: list = []

    def clock():
        return now[0]

    def sleep(s):
        slept.append(round(s, 6))
        now[0] += s

    src = lcu(min_interval_s=0.25)
    fill(tmp_path, [src], sleep=sleep, clock=clock)
    calls = len(src.doc_calls) + len(src.asset_calls)
    assert calls == 4 + 7
    # Each call after the first waits the full interval (the fake clock does
    # not advance on its own), so total sleep = (calls - 1) * interval.
    assert sum(slept) == pytest.approx((calls - 1) * 0.25)
    assert all(s <= 0.25 for s in slept)


def test_the_cache_root_lives_under_data_tft_and_ignores_itself(tmp_path):
    assert ic.cache_root(tmp_path) == tmp_path / "data" / "tft" / "icon_cache"
    assert ic.set_dir(18, root=tmp_path) == tmp_path / "data" / "tft" / "icon_cache" / "18"
    assert ic.category_dir(18, "item", root=tmp_path) == ic.set_dir(18, root=tmp_path) / "item"
    with pytest.raises(ValueError):
        ic.category_dir(18, "../x", root=tmp_path)
    fill(tmp_path, [lcu()])
    marker = ic.cache_root(tmp_path) / ".gitignore"
    assert marker.read_bytes() == b"*\n"


def test_git_never_sees_the_cache_even_without_a_repo_gitignore_rule(tmp_path):
    # git is a hard requirement of this suite (tests/_repo_walk), so no skip.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True,
                   capture_output=True, timeout=60)
    fill(tmp_path, [lcu()])
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                         cwd=str(tmp_path), capture_output=True, text=True,
                         timeout=60, check=True).stdout
    assert out.strip() == "", out


# -- read side: lookups for TFT-05 / TFT-09 --------------------------------------

def test_icon_path_lookup(tmp_path):
    assert ic.load_index(18, root=tmp_path) == {}
    assert ic.icon_path(18, "champion", "DA_18_Yorick", root=tmp_path) is None
    fill(tmp_path, [lcu()])
    p = ic.icon_path(18, "champion", "DA_18_Yorick", root=tmp_path)
    assert p == ic.set_dir(18, root=tmp_path) / "champion" / "DA_18_Yorick.png"
    assert ic.icon_path(18, "champion", "DA_18_Yorick", root=tmp_path, verify=True) == p
    assert ic.icon_path(18, "champion", "Nobody", root=tmp_path) is None
    assert ic.icon_path(18, "skins", "DA_18_Yorick", root=tmp_path) is None
    assert ic.icon_path(17, "champion", "DA_18_Yorick", root=tmp_path) is None
    p.write_bytes(png("tampered"))
    assert ic.icon_path(18, "champion", "DA_18_Yorick", root=tmp_path) == p
    assert ic.icon_path(18, "champion", "DA_18_Yorick", root=tmp_path, verify=True) is None
    p.unlink()
    assert ic.icon_path(18, "champion", "DA_18_Yorick", root=tmp_path) is None


def test_icon_path_refuses_an_index_file_entry_that_escapes_the_cache(tmp_path):
    fill(tmp_path, [lcu()])
    idx_path = ic.set_dir(18, root=tmp_path) / ic.INDEX_NAME
    idx = json.loads(idx_path.read_bytes())
    idx["entries"]["champion"]["DA_18_Yorick"]["file"] = "../../../../outside.png"
    (tmp_path / "outside.png").write_bytes(png("outside"))
    idx_path.write_text(json.dumps(idx), encoding="ascii")
    assert ic.icon_path(18, "champion", "DA_18_Yorick", root=tmp_path) is None


# -- the real sources: passive GET only, no network in the test ------------------

class _Resp:
    def __init__(self, body, status=200):
        self._body = body
        self.status = status

    def read(self, n=-1):
        return self._body if n is None or n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def recorder(monkeypatch):
    """Replaces urlopen: exact-URL bodies, everything else answers 400."""
    seen: list = []
    bodies: dict = {}

    def fake_urlopen(req, *a, **kw):
        seen.append(req)
        url = req.full_url
        if url in bodies:
            return _Resp(bodies[url])
        raise urllib.error.HTTPError(url, 400, "bad", {}, None)

    # The module's OWN urllib.request name only, never the shared module
    # (RM-801; tests/_module_view.py:178 bind_urlopen).
    assert bind_urlopen(monkeypatch, ic, fake_urlopen) >= 1
    return seen, bodies


def test_lcu_source_from_a_lockfile(tmp_path):
    lf = tmp_path / "lockfile"
    lf.write_text("LeagueClient:1234:54321:s3cret:https", encoding="ascii")
    src = ic.LcuSource.discover(lockfiles=[tmp_path / "absent", lf], host="127.0.0.1")
    assert src is not None and src.port == 54321 and src.name == "lcu"
    lf.write_text("garbage", encoding="ascii")
    assert ic.LcuSource.discover(lockfiles=[lf]) is None
    assert ic.LcuSource.discover(lockfiles=[tmp_path / "absent"]) is None


def test_real_sources_issue_get_requests_only(recorder):
    seen, bodies = recorder
    base = "https://127.0.0.1:54321"
    bodies[base + "/lol-game-data/assets/v1/tfttraits.json"] = json.dumps(
        DOCS["tfttraits.json"]).encode()
    bodies[base + "/lol-game-data/assets/v1/tftsets.json"] = json.dumps(TFTSETS).encode()
    bodies[base + "/lol-gameflow/v1/session"] = json.dumps(
        {"gameData": {"queue": {"id": 6110}}}).encode()
    bodies[base + ADAPTOR] = png("adaptor")
    bodies[ic.cdragon_url(ADAPTOR)] = png("adaptor")
    lsrc = ic.LcuSource(54321, "s3cret", host="127.0.0.1")
    csrc = ic.CDragonSource()
    assert lsrc.game_data("tfttraits.json") == DOCS["tfttraits.json"]
    assert lsrc.asset(ADAPTOR) == png("adaptor")
    assert lsrc.tftsets() == TFTSETS
    assert lsrc.queue_id() == 6110
    assert csrc.asset(ADAPTOR) == png("adaptor")
    assert csrc.game_data("tfttraits.json") is None        # 400 -> None, no raise
    n_before = len(seen)
    assert lsrc.asset("/lol-game-data/assets/../x.png") is None   # refused pre-request
    assert csrc.asset("/lol-game-data/assets/../x.png") is None
    assert lsrc.game_data("../../lol-summoner/v1/current-summoner") is None
    assert len(seen) == n_before
    assert seen and all(r.get_method() == "GET" for r in seen)
    assert all(r.data is None for r in seen)
    lcu_reqs = [r for r in seen if r.full_url.startswith("https://127.0.0.1:54321/")]
    cd_reqs = [r for r in seen if r.full_url.startswith("https://raw.communitydragon.org/")]
    assert len(lcu_reqs) + len(cd_reqs) == len(seen)
    assert all(r.get_header("Authorization") for r in lcu_reqs)
    # Unredirected only: urllib never copies it onto a redirect to another host.
    assert all("Authorization" in r.unredirected_hdrs and "Authorization" not in r.headers
               for r in lcu_reqs)
    # The LCU password must never travel to the internet.
    assert cd_reqs and not any(r.get_header("Authorization") for r in cd_reqs)
    assert all("s3cret" not in json.dumps(r.header_items()) for r in cd_reqs)


def test_http_get_caps_the_read(recorder):
    seen, bodies = recorder
    url = "https://raw.communitydragon.org/latest/big.png"
    bodies[url] = PNG + b"x" * 100
    assert ic._http_get(url, max_bytes=50) is None
    assert ic._http_get(url, max_bytes=500) == PNG + b"x" * 100
    assert ic._http_get("https://raw.communitydragon.org/latest/absent.png") is None


def test_no_write_shaped_http_method_appears_in_the_slice_source():
    for rel in ("tft/assets/icon_cache.py", "scripts/fetch_tft_icons.py",
                "tft/assets/__init__.py"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for verb in ("POST", "PUT", "PATCH", "DELETE"):
            assert not re.search(rf"[\"']{verb}[\"']", text), (rel, verb)
        for m in re.finditer(r"method\s*=\s*([^,)\s]+)", text):
            assert m.group(1) in ('"GET"', "'GET'"), (rel, m.group(0))


# -- script ----------------------------------------------------------------------

def test_script_fills_set_18_and_prints_a_summary(tmp_path, capsys):
    import scripts.fetch_tft_icons as fti
    meta = tmp_path / "data" / "meta"
    meta.mkdir(parents=True)
    (meta / "tft_set18_cdragon.json").write_text(json.dumps(EXTRACT), encoding="ascii")
    rc = fti.main(["--set", "18", "--root", str(tmp_path), "--rate-limit", "0"],
                  sources=[lcu(), cdragon()])
    assert rc == 0
    out = capsys.readouterr().out
    assert "set 18" in out and "champion 3/3" in out and "augment 1/1" in out
    assert ic.icon_path(18, "trait", "DA_18_Adaptor", root=tmp_path) is not None


def test_script_detects_the_running_set_from_the_lcu(tmp_path, capsys):
    import scripts.fetch_tft_icons as fti
    rc = fti.main(["--root", str(tmp_path), "--dry-run"],
                  sources=[lcu(tftsets=TFTSETS, queue=6110)])
    assert rc == 0
    assert "set 17" in capsys.readouterr().out
    assert not (tmp_path / "data" / "tft").exists()


def test_script_offline_exit_code(tmp_path, capsys):
    import scripts.fetch_tft_icons as fti
    rc = fti.main(["--set", "18", "--root", str(tmp_path)],
                  sources=[lcu(docs={}, assets={})])
    assert rc == fti.EXIT_OFFLINE == 2
    assert "offline" in capsys.readouterr().out


def test_script_source_selection_never_builds_a_network_source_in_tests(monkeypatch):
    import scripts.fetch_tft_icons as fti
    monkeypatch.setattr(ic.LcuSource, "discover", classmethod(lambda cls, **k: None))
    args = fti.parse_args(["--source", "auto", "--branch", "pbe", "--rate-limit", "0.5"])
    srcs = fti.build_sources(args)
    assert [s.name for s in srcs] == ["cdragon"]
    assert srcs[0].branch == "pbe" and srcs[0].min_interval_s == 0.5
    assert fti.build_sources(fti.parse_args(["--source", "lcu"])) == []


# -- repo guards (acceptance) ----------------------------------------------------

def _tracked() -> frozenset:
    tracked = _repo_walk.tracked_relpaths()
    assert tracked is not None, "git index unreadable: the guard cannot run"
    # Anchor: an empty or collapsed enumeration must not read as clean.
    assert "tft/tft_set.py" in tracked and "NOTICE" in tracked
    return tracked


def test_no_tracked_file_under_data_tft():
    offenders = sorted(p for p in _tracked() if p.startswith("data/tft/"))
    assert offenders == [], offenders


def test_no_tracked_image_under_tft():
    tracked = _tracked()
    under = [p for p in tracked if p.startswith("tft/")]
    assert len(under) >= 10                       # anchored on the real package
    images = re.compile(r"\.(png|jpe?g|gif|webp|bmp|tex|dds)$", re.IGNORECASE)
    offenders = sorted(p for p in under if images.search(p))
    assert offenders == [], offenders


def test_notice_says_the_icon_cache_is_never_committed():
    text = (REPO_ROOT / "NOTICE").read_text(encoding="utf-8")
    flat = " ".join(text.split())
    assert "data/tft/icon_cache/" in flat
    assert "scripts/fetch_tft_icons.py" in flat
    assert "never committed" in flat
