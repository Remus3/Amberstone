"""RM-894: scripts/tft_patch_delta.py - what changed in one TFT set between two
CommunityDragon patch directories.

No network and no downloaded payload: every fixture below is hand-written in
the SHAPE of raw.communitydragon.org/<dir>/cdragon/tft/en_us.json as measured
2026-10-28 at 16.20 / 16.21 (top-level items / setData / sets; a setData row
carries mutator / number plus champions and traits as full objects and items /
augments as apiName lists; the global `items` list carries isAugment, effects
and desc). The numbers mirror the filed 16.20 -> 16.21 read-back (Alune
attackSpeed 0.8 -> 0.85, Hecarim initialMana 30 -> 50) but are fixtures, not
captures.
"""
from __future__ import annotations

import json

import pytest

import scripts.fetch_cdragon_tft as fct
import scripts.tft_patch_delta as tpd

ELDER_KEY = "{0f90e7a4}"


def _champ(api, cost=1, traits=("Fae",), stats=None, variables=()):
    return {"apiName": api, "name": api.rsplit("_", 1)[-1], "cost": cost,
            "traits": list(traits),
            "stats": dict(stats or {"attackSpeed": 0.7, "initialMana": 30, "hp": 600.0}),
            "ability": {"name": "a", "desc": "d",
                        "variables": [{"name": n, "value": v} for n, v in variables]}}


def _trait(api, effects, desc="Trait desc"):
    return {"apiName": api, "name": api.rsplit("_", 1)[-1], "desc": desc,
            "effects": [{"minUnits": lo, "maxUnits": hi, "style": 1, "variables": dict(v)}
                        for lo, hi, v in effects]}


def _item(api, *, aug=False, effects=None, desc="desc"):
    return {"apiName": api, "name": api, "desc": desc, "isAugment": aug,
            "effects": dict(effects or {}), "composition": [], "associatedTraits": []}


def _payload(champions, traits, items, *, mutator="TFTSet18", number=18):
    row = {"mutator": mutator, "number": number, "name": "Set18",
           "champions": champions, "traits": traits,
           "items": [i["apiName"] for i in items if not i["isAugment"]],
           "augments": [i["apiName"] for i in items if i["isAugment"]]}
    other = {"mutator": "TFTSet17", "number": 17, "name": "Set17",
             "champions": [_champ("TFT17_Other")], "traits": [], "items": [], "augments": []}
    return {"items": items + [_item("TFT17_Item")], "setData": [other, row],
            "sets": {str(number): {"name": "Set18", "champions": champions, "traits": traits}}}


def _base():
    champs = [
        _champ("DA_18_Alune", 5, stats={"attackSpeed": 0.800000011920929, "initialMana": 0,
                                        "hp": 900.0}),
        _champ("DA_18_Hecarim", 3, stats={"attackSpeed": 0.75, "initialMana": 30, "hp": 850.0}),
        _champ("DA_18_Kobuko", 1),
    ]
    traits = [_trait("DA_18_Elderwood", [(3, 4, {ELDER_KEY: 0.25, "Flat": 10}),
                                         (5, 25000, {ELDER_KEY: 0.5, "Flat": 20})])]
    items = [_item("DA_18_BigGrabBag", aug=True, effects={"Gold": 2.0},
                   desc="Gain @Gold@ gold."),
             _item("DA_18_OldAug", aug=True),
             _item("TFT_Item_Rapidfire", effects={"ASPerStack": 0.08})]
    return champs, traits, items


def _pair():
    old = _payload(*_base())
    champs, traits, items = _base()
    champs[0]["stats"]["attackSpeed"] = 0.8500000238418579
    champs[1]["stats"]["initialMana"] = 50
    traits[0]["effects"][0]["variables"][ELDER_KEY] = 0.3
    items[0]["effects"]["Gold"] = 3.0
    items[2]["effects"]["ASPerStack"] = 0.07
    items = [i for i in items if i["apiName"] != "DA_18_OldAug"]
    items.append(_item("DA_18_NewAug", aug=True))
    return old, _payload(champs, traits, items)


# --- (1) unit stats ---------------------------------------------------------

def test_unit_stat_change_reports_old_and_new():
    old, new = _pair()
    d = tpd.diff_set(old, new)
    assert d["reason"] is None
    assert d["units"]["DA_18_Alune"]["stats"] == {
        "attackSpeed": {"old": 0.800000011920929, "new": 0.8500000238418579}}
    assert d["units"]["DA_18_Hecarim"]["stats"] == {"initialMana": {"old": 30, "new": 50}}
    assert "DA_18_Kobuko" not in d["units"]  # unchanged units are not listed


def test_unit_cost_trait_and_roster_changes():
    old = _payload(*_base())
    champs, traits, items = _base()
    champs[2]["cost"] = 2
    champs[2]["traits"] = ["Fae", "Brawler"]
    champs.append(_champ("DA_18_Taric", 4))
    champs = [c for c in champs if c["apiName"] != "DA_18_Hecarim"]
    d = tpd.diff_set(old, _payload(champs, traits, items))
    assert d["units"]["DA_18_Kobuko"]["cost"] == {"old": 1, "new": 2}
    assert d["units"]["DA_18_Kobuko"]["traits"] == {"old": ["Fae"], "new": ["Fae", "Brawler"]}
    assert d["added"]["units"] == ["DA_18_Taric"]
    assert d["removed"]["units"] == ["DA_18_Hecarim"]


def test_nan_stat_on_both_sides_is_not_a_change():
    champs, traits, items = _base()
    champs[2]["stats"]["critChance"] = float("nan")
    old = _payload(champs, traits, items)
    champs2, traits2, items2 = _base()
    champs2[2]["stats"]["critChance"] = float("nan")
    d = tpd.diff_set(old, _payload(champs2, traits2, items2))
    assert "DA_18_Kobuko" not in d["units"]
    champs3, traits3, items3 = _base()
    champs3[2]["stats"]["critChance"] = 0.25
    d2 = tpd.diff_set(old, _payload(champs3, traits3, items3))
    assert d2["units"]["DA_18_Kobuko"]["stats"] == {"critChance": {"old": None, "new": 0.25}}
    json.dumps(d2, allow_nan=False)  # no NaN token reaches the output


def test_only_the_named_mutator_is_diffed():
    old, new = _pair()
    for row in new["setData"]:
        if row["mutator"] == "TFTSet17":
            row["champions"][0]["stats"]["hp"] = 1.0
    d = tpd.diff_set(old, new)
    assert "TFT17_Other" not in d["units"]
    assert d["_mutator"] == "TFTSet18"


# --- (2) trait breakpoints, hashed keys verbatim ------------------------------

def test_trait_breakpoint_hashed_key_reported_verbatim():
    old, new = _pair()
    d = tpd.diff_set(old, new)
    bps = d["traits"]["DA_18_Elderwood"]["breakpoints"]
    assert bps == [{"index": 0, "minUnits": 3, "maxUnits": 4,
                    "variables": {ELDER_KEY: {"old": 0.25, "new": 0.3}}}]


def test_hashed_key_is_never_renamed_even_when_the_desc_names_it():
    name = "BonusAS"
    key = fct.bin_hash(name)
    old = _payload([], [_trait("DA_18_Fae", [(3, 4, {key: 0.1})], desc=f"+@{name}@ AS")], [])
    new = _payload([], [_trait("DA_18_Fae", [(3, 4, {key: 0.2})], desc=f"+@{name}@ AS")], [])
    bps = tpd.diff_set(old, new)["traits"]["DA_18_Fae"]["breakpoints"]
    assert bps[0]["variables"] == {key: {"old": 0.1, "new": 0.2}}


def test_trait_breakpoint_bounds_added_and_removed():
    old = _payload([], [_trait("DA_18_Fae", [(3, 4, {}), (5, 6, {"X": 1})])], [])
    new = _payload([], [_trait("DA_18_Fae", [(2, 4, {}), (5, 6, {"X": 1}), (7, 9, {"X": 2})])], [])
    bps = tpd.diff_set(old, new)["traits"]["DA_18_Fae"]["breakpoints"]
    assert bps[0] == {"index": 0, "minUnits": 2, "maxUnits": 4,
                      "bounds": {"minUnits": {"old": 3, "new": 2}}}
    assert bps[1] == {"index": 2, "minUnits": 7, "maxUnits": 9, "added": True,
                      "variables": {"X": {"old": None, "new": 2}}}
    gone = tpd.diff_set(new, old)["traits"]["DA_18_Fae"]["breakpoints"]
    assert gone[-1]["removed"] is True and gone[-1]["index"] == 2


# --- (3) augments and items ---------------------------------------------------

def test_augment_effects_change_plus_add_and_remove():
    old, new = _pair()
    d = tpd.diff_set(old, new)
    assert d["augments"]["DA_18_BigGrabBag"]["effects"] == {"Gold": {"old": 2.0, "new": 3.0}}
    assert d["added"]["augments"] == ["DA_18_NewAug"]
    assert d["removed"]["augments"] == ["DA_18_OldAug"]
    assert d["items"]["TFT_Item_Rapidfire"]["effects"] == {
        "ASPerStack": {"old": 0.08, "new": 0.07}}
    assert d["added"]["items"] == [] and d["removed"]["items"] == []


def test_desc_change_is_reported_and_unchanged_desc_is_not():
    old, new = _pair()
    assert "desc" not in tpd.diff_set(old, new)["augments"]["DA_18_BigGrabBag"]
    for it in new["items"]:
        if it["apiName"] == "DA_18_BigGrabBag":
            it["desc"] = "Gain @Gold@ gold and a Reforger."
    entry = tpd.diff_set(old, new)["augments"]["DA_18_BigGrabBag"]
    assert entry["desc"] == {"old": "Gain @Gold@ gold.", "new": "Gain @Gold@ gold and a Reforger."}


# --- (4) ability values -------------------------------------------------------

def test_empty_ability_variables_yield_no_ability_entry_and_the_top_level_note():
    old, new = _pair()
    d = tpd.diff_set(old, new)
    assert "ability" not in d["units"]["DA_18_Alune"]
    assert d["ability_values"] == "not carried by source"
    assert d["_kind"] == "client_file_delta"


def test_ability_variables_are_diffed_where_the_source_carries_them():
    champs, traits, items = _base()
    champs[2] = _champ("DA_18_Kobuko", variables=[("Damage", [0, 100, 150, 225])])
    old = _payload(champs, traits, items)
    champs2, traits2, items2 = _base()
    champs2[2] = _champ("DA_18_Kobuko", variables=[("Damage", [0, 110, 165, 250])])
    d = tpd.diff_set(old, _payload(champs2, traits2, items2))
    assert d["units"]["DA_18_Kobuko"]["ability"] == {
        "Damage": {"old": [0, 100, 150, 225], "new": [0, 110, 165, 250]}}
    assert d["ability_values"] != "not carried by source"
    assert "1 of 3" in d["ability_values"]


# --- (5) URL builder ----------------------------------------------------------

@pytest.mark.parametrize("directory", ["latest", "pbe", "16.21", "16.9", "17.1"])
def test_url_builder_accepts_branches_and_patch_directories(directory):
    assert tpd.patch_url(directory) == f"https://raw.communitydragon.org/{directory}/cdragon/tft/en_us.json"
    assert tpd.patch_metadata_url(directory).endswith(f"/{directory}/content-metadata.json")


@pytest.mark.parametrize("directory", [
    "", "LATEST", "16", "16.21.1", "../16.21", "16.21/..", "16.21/x", " 16.21",
    "16.21 ", "16.2a", "1621", "v16.21", "16.21\n", "pbe/../latest", None, 16.21,
])
def test_url_builder_rejects_everything_else(directory):
    with pytest.raises(ValueError):
        tpd.patch_url(directory)


def test_tracked_extract_fetcher_still_refuses_a_patch_directory():
    with pytest.raises(ValueError):
        fct.fetch_set(18, branch="16.21")


# --- (6) missing mutator ------------------------------------------------------

@pytest.mark.parametrize("side", ["old", "new", "both"])
def test_missing_mutator_returns_an_empty_delta_with_a_reason(side):
    good = _payload(*_base())
    bad = _payload(*_base(), mutator="TFTSet19", number=19)
    old = bad if side in ("old", "both") else good
    new = bad if side in ("new", "both") else good
    d = tpd.diff_set(old, new)
    assert d["reason"] and "TFTSet18" in d["reason"]
    assert d["units"] == {} and d["traits"] == {} and d["augments"] == {} and d["items"] == {}
    assert all(v == [] for v in d["added"].values())
    assert all(v == [] for v in d["removed"].values())


@pytest.mark.parametrize("junk", [None, [], "x", {"setData": "nope"}, {"setData": [None, 3]},
                                  {"setData": [{"mutator": "TFTSet18", "champions": "x",
                                                "traits": None, "items": 5}]}])
def test_malformed_payload_never_raises(junk):
    d = tpd.diff_set(junk, _payload(*_base()))
    assert isinstance(d, dict)
    json.dumps(d, allow_nan=False)


def test_header_carries_both_content_versions_and_labels():
    old, new = _pair()
    d = tpd.diff_set(old, new, old_label="16.20", new_label="16.21",
                     old_version="16.20.1+x", new_version="16.21.2+y")
    assert d["_old"] == {"directory": "16.20", "content_version": "16.20.1+x"}
    assert d["_new"] == {"directory": "16.21", "content_version": "16.21.2+y"}
    assert "patch notes" in d["_note"]


# --- CLI ----------------------------------------------------------------------

def _write(path, obj):
    path.write_bytes(json.dumps(obj).encode("ascii"))
    return path


def test_cli_with_local_sources_writes_ascii_lf_json_and_no_network(tmp_path, monkeypatch):
    def _no_net(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(fct, "_http_get", _no_net)
    old, new = _pair()
    out = tmp_path / "delta.json"
    rc = tpd.main(["16.20", "16.21",
                   "--old-source", str(_write(tmp_path / "a.json", old)),
                   "--new-source", str(_write(tmp_path / "b.json", new)),
                   "--out", str(out)])
    assert rc == 0
    data = out.read_bytes()
    assert b"\r" not in data and max(data) < 128
    d = json.loads(data)
    assert d["units"]["DA_18_Hecarim"]["stats"]["initialMana"] == {"old": 30, "new": 50}
    assert d["_old"]["directory"] == "16.20"
    # RM-1094: no flag and no content-metadata.json beside a source = None.
    assert d["_old"]["content_version"] is None
    assert d["_new"]["content_version"] is None


def _sources(tmp_path):
    old, new = _pair()
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    return (_write(tmp_path / "a" / "en_us.json", old),
            _write(tmp_path / "b" / "en_us.json", new))


def test_cli_version_flags_reach_the_header_for_local_sources(tmp_path, monkeypatch):
    """RM-1094: --old-version / --new-version state the content version of a
    local --old-source / --new-source payload."""
    monkeypatch.setattr(fct, "_http_get", lambda *a, **k: pytest.fail("network used"))
    a, b = _sources(tmp_path)
    out = tmp_path / "d.json"
    assert tpd.main(["16.20", "16.21", "--old-source", str(a), "--new-source", str(b),
                     "--old-version", "16.20.1+x", "--new-version", "16.21.2+y",
                     "--out", str(out)]) == 0
    d = json.loads(out.read_bytes())
    assert d["_old"] == {"directory": "16.20", "content_version": "16.20.1+x"}
    assert d["_new"] == {"directory": "16.21", "content_version": "16.21.2+y"}


def test_cli_reads_a_content_metadata_file_beside_a_local_source(tmp_path, monkeypatch):
    """RM-1094: with no flag, a content-metadata.json in the source's own
    directory (the shape load_payload caches) supplies the version; a flag
    wins over it; the side without one stays None."""
    monkeypatch.setattr(fct, "_http_get", lambda *a, **k: pytest.fail("network used"))
    a, b = _sources(tmp_path)
    _write(a.parent / "content-metadata.json", {"version": "16.20.7+meta"})
    out = tmp_path / "d.json"
    assert tpd.main(["16.20", "16.21", "--old-source", str(a), "--new-source", str(b),
                     "--out", str(out)]) == 0
    d = json.loads(out.read_bytes())
    assert d["_old"]["content_version"] == "16.20.7+meta"
    assert d["_new"]["content_version"] is None
    assert tpd.main(["16.20", "16.21", "--old-source", str(a), "--new-source", str(b),
                     "--old-version", "16.20.8+flag", "--out", str(out)]) == 0
    assert json.loads(out.read_bytes())["_old"]["content_version"] == "16.20.8+flag"


@pytest.mark.parametrize("version", ["", " ", "16.21\u2013x", "a b", "x\n", "v" * 129])
def test_cli_refuses_a_version_that_is_not_printable_ascii(tmp_path, monkeypatch, version):
    monkeypatch.setattr(fct, "_http_get", lambda *a, **k: pytest.fail("network used"))
    a, b = _sources(tmp_path)
    out = tmp_path / "d.json"
    assert tpd.main(["16.20", "16.21", "--old-source", str(a), "--new-source", str(b),
                     "--new-version", version, "--out", str(out)]) == 1
    assert not out.exists()


def test_cli_refuses_a_bad_version_before_the_other_side_is_fetched(tmp_path, monkeypatch):
    monkeypatch.setattr(fct, "_http_get", lambda *a, **k: pytest.fail("network used"))
    _, b = _sources(tmp_path)
    out = tmp_path / "d.json"
    assert tpd.main(["16.20", "16.21", "--new-source", str(b), "--new-version", "a b",
                     "--cache-dir", str(tmp_path / "cache"), "--out", str(out)]) == 1
    assert not out.exists() and not (tmp_path / "cache").exists()


def test_cli_refuses_a_version_flag_without_its_local_source(tmp_path, monkeypatch, capsys):
    """A fetched or cached directory carries its own content-metadata.json; a
    flag would only be able to mislabel it, so it is refused before a fetch."""
    monkeypatch.setattr(fct, "_http_get", lambda *a, **k: pytest.fail("network used"))
    a, _ = _sources(tmp_path)
    out = tmp_path / "d.json"
    assert tpd.main(["16.20", "16.21", "--old-source", str(a), "--new-version", "16.21.1",
                     "--cache-dir", str(tmp_path / "cache"), "--out", str(out)]) == 1
    assert "--new-version" in capsys.readouterr().err
    assert not out.exists()


def test_cli_fetches_through_the_fetcher_and_caches_numbered_directories_only(tmp_path, monkeypatch):
    old, new = _pair()
    calls = []

    def _fake_get(url, **k):
        calls.append(url)
        if url.endswith("content-metadata.json"):
            return json.dumps({"version": url.split("/")[3] + ".9+b"}).encode("ascii")
        return json.dumps(old if "/16.20/" in url else new).encode("ascii")

    monkeypatch.setattr(fct, "_http_get", _fake_get)
    cache = tmp_path / "cache"
    out = tmp_path / "d.json"
    assert tpd.main(["16.20", "latest", "--cache-dir", str(cache), "--out", str(out)]) == 0
    assert (cache / "16.20" / "en_us.json").is_file()
    assert (cache / "16.20" / "content-metadata.json").is_file()
    assert not (cache / "latest").exists()
    d = json.loads(out.read_bytes())
    assert d["_old"]["content_version"] == "16.20.9+b"
    assert d["_new"]["content_version"] == "latest.9+b"
    n = len(calls)
    assert tpd.main(["16.20", "latest", "--cache-dir", str(cache), "--out", str(out)]) == 0
    assert not any("/16.20/" in u for u in calls[n:])  # the numbered dir came from the cache
    assert any("/latest/" in u for u in calls[n:])  # a moving branch is re-read


def test_cli_rejects_a_bad_directory_without_a_fetch(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fct, "_http_get", lambda *a, **k: pytest.fail("network used"))
    assert tpd.main(["../x", "16.21", "--cache-dir", str(tmp_path), "--out",
                     str(tmp_path / "o.json")]) == 1
    assert "tft_patch_delta:" in capsys.readouterr().err
    assert not (tmp_path / "o.json").exists()


def test_cli_missing_mutator_exits_nonzero_but_writes_the_reasoned_delta(tmp_path, monkeypatch):
    monkeypatch.setattr(fct, "_http_get", lambda *a, **k: pytest.fail("network used"))
    old, new = _pair()
    out = tmp_path / "d.json"
    rc = tpd.main(["16.20", "16.21", "--mutator", "TFTSet99",
                   "--old-source", str(_write(tmp_path / "a.json", old)),
                   "--new-source", str(_write(tmp_path / "b.json", new)),
                   "--out", str(out)])
    assert rc == 2
    assert "TFTSet99" in json.loads(out.read_bytes())["reason"]


@pytest.mark.parametrize("mutator", ["../x", "TFT Set18", "", "TFTSet18/..", "a" * 65])
def test_cli_refuses_a_mutator_that_is_not_a_file_name_segment(tmp_path, monkeypatch, mutator):
    monkeypatch.setattr(fct, "_http_get", lambda *a, **k: pytest.fail("network used"))
    assert tpd.main(["16.20", "16.21", "--mutator", mutator,
                     "--cache-dir", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == []


def test_default_out_is_under_the_gitignored_tft_tree():
    p = tpd.default_out("TFTSet18", "16.20", "16.21")
    rel = p.relative_to(tpd.ROOT).as_posix()
    assert rel == "data/tft/patch_delta/TFTSet18_16.20_16.21.json"
