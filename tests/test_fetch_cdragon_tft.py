"""RM-840: scripts/fetch_cdragon_tft.py - set-agnostic CommunityDragon TFT ingest.

No network: every HTTP read goes through the module's `_http_get`, which the
tests replace with a fixture. The fixture mirrors the SHAPE of
raw.communitydragon.org/<branch>/cdragon/tft/en_us.json as measured
2026-10-24 (content version 16.21): top-level keys items / setData / sets;
sets["<N>"] = {name, champions, traits}; setData rows carry mutator / number /
augments / items as apiName lists; the global `items` list carries isAugment.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.fetch_cdragon_tft as fct

REPO_ROOT = Path(__file__).resolve().parent.parent
# Non-ASCII CDragon text, built from code points so this file stays ASCII.
ZWSP = chr(0x200B)
RSQUO = chr(0x2019)


def _champ(api, name, cost, traits, role=None):
    return {"apiName": api, "characterName": api, "name": name, "cost": cost,
            "traits": traits, "role": role, "stats": {"hp": 600.0},
            "ability": {"desc": "x", "name": "y", "variables": []}}


def _trait(api, name, mins):
    return {"apiName": api, "name": name, "desc": f"{name} desc{ZWSP}",
            "icon": "i.tex",
            "effects": [{"minUnits": m, "maxUnits": m + 1, "style": 1,
                         "variables": {}} for m in mins]}


def _item(api, name, *, aug=False, comp=(), traits=()):
    return {"apiName": api, "name": name, "desc": f"{name} {RSQUO}desc",
            "isAugment": aug, "composition": list(comp), "from": None,
            "associatedTraits": list(traits), "incompatibleTraits": [],
            "effects": {}, "icon": "i.tex", "id": None, "tags": [],
            "unique": False}


FIXTURE = {
    "sets": {
        "18": {
            "name": "Set10",
            "champions": [
                _champ("TFT_BlueGolem", "Golem", 1, []),          # PvE, no traits
                _champ("DA_18_Kobuko", "Kobuko", 1, ["Sprykin", "Brawler"], "APTank"),
                _champ("DA_18_Alune", "Alune", 5, ["Attuned", "Lunar"]),
                _champ("DA_18_Lux_Fae", "Lux (Fae)", 5, ["Fae", "Avatar"]),
                _champ("DA_18_Kobuko_Dup", "Kobuko", 1, ["Sprykin", "Fae"]),
            ],
            "traits": [
                _trait("DA_18_Sprykin", "Sprykin", [2, 4, 6]),
                _trait("DA_18_Fae", "Fae", [3, 5]),
                _trait("DA_18_Fae_Alt", "Fae", [7]),
            ],
        },
        "17": {"name": "Set17", "champions": [
            _champ("TFT17_Jinx", "Jinx", 2, ["Anima"])], "traits": []},
    },
    "setData": [
        {"mutator": "TFTSet18_PAIRS", "number": 18, "name": "Set10",
         "augments": [], "items": [], "champions": [], "traits": []},
        {"mutator": "TFTSet18", "number": 18, "name": "Set10",
         "augments": ["DA_18_BigGrabBag"],
         "items": ["DA_18_EmblemFae", "DA_18_AllOnes"],
         "champions": [], "traits": []},
    ],
    "items": [
        _item("DA_18_BigGrabBag", "Big Grab Bag", aug=True, traits=["DA_18_Fae"]),
        _item("DA_18_EmblemFae", "Fae Emblem",
              comp=["DA_Component_Spatula", "DA_Component_BFSword"]),
        _item("DA_18_AllOnes", "All Ones"),
        _item("TFT13_Unrelated", "Unrelated"),
    ],
}
META = {"version": "16.21.8298620+branch.releases-16-21.content.release"}


def _extract(n=18, **kw):
    kw.setdefault("branch", "latest")
    kw.setdefault("content_version", META["version"])
    kw.setdefault("fetched", "2026-10-24")
    return fct.build_extract(json.loads(json.dumps(FIXTURE)), n, **kw)


# -- build_extract ----------------------------------------------------------------

def test_extract_carries_the_meta_shape_keys():
    ex = _extract()
    assert ex["_set"] == 18
    # tft_set17_meta.json shape: champions / unit_costs / unit_traits / all_traits
    assert ex["champions"] == ["Alune", "Kobuko", "Lux (Fae)"]
    assert ex["unit_costs"] == {"Alune": 5, "Kobuko": 1, "Lux (Fae)": 5}
    assert ex["unit_traits"]["Kobuko"] == ["Sprykin", "Brawler", "Fae"]
    assert ex["all_traits"] == ["Fae", "Sprykin"]


def test_extract_keeps_raw_counts_and_drops_non_playables_from_the_roster():
    ex = _extract()
    assert ex["_counts"]["champions_raw"] == 5
    assert ex["_counts"]["units"] == 4
    assert ex["_counts"]["traits"] == 3
    assert "Golem" not in ex["champions"]
    assert [u["apiName"] for u in ex["units"]][0] == "DA_18_Kobuko"
    assert ex["units"][0] == {"apiName": "DA_18_Kobuko", "name": "Kobuko",
                              "cost": 1, "traits": ["Sprykin", "Brawler"],
                              "role": "APTank"}


def test_extract_traits_carry_breakpoints():
    tr = {t["apiName"]: t for t in _extract()["traits"]}
    assert tr["DA_18_Sprykin"]["breakpoints"] == [2, 4, 6]
    assert tr["DA_18_Fae"]["breakpoints"] == [3, 5]
    assert ZWSP not in tr["DA_18_Sprykin"]["desc"]


def test_extract_items_and_augments_come_from_the_base_mutator_row():
    ex = _extract()
    assert ex["_mutator"] == "TFTSet18"
    assert [i["apiName"] for i in ex["items"]] == ["DA_18_AllOnes", "DA_18_EmblemFae"]
    emb = [i for i in ex["items"] if i["apiName"] == "DA_18_EmblemFae"][0]
    assert emb["composition"] == ["DA_Component_Spatula", "DA_Component_BFSword"]
    assert [a["apiName"] for a in ex["augments"]] == ["DA_18_BigGrabBag"]
    assert ex["augments"][0]["associatedTraits"] == ["DA_18_Fae"]


def test_extract_records_provenance():
    ex = _extract(branch="pbe")
    assert ex["_branch"] == "pbe"
    assert ex["_content_version"] == META["version"]
    assert ex["_source_url"] == fct.tft_url("pbe")
    assert "CommunityDragon" in ex["_source"]
    assert ex["_cdragon_set_name"] == "Set10"


def test_unknown_set_is_refused():
    with pytest.raises(ValueError, match="19"):
        _extract(19)


# -- fetch_set / main: atomic, ASCII, LF ------------------------------------------

@pytest.fixture
def fake_http(monkeypatch):
    seen = []

    def _get(url, **_kw):
        seen.append(url)
        if url.endswith("/cdragon/tft/en_us.json"):
            return json.dumps(FIXTURE, ensure_ascii=False).encode("utf-8")
        if url.endswith("/content-metadata.json"):
            return json.dumps(META).encode("utf-8")
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(fct, "_http_get", _get)
    return seen


def test_main_writes_the_extract_atomically(tmp_path, fake_http):
    out = tmp_path / "data" / "meta" / "tft_set18_cdragon.json"
    out.parent.mkdir(parents=True)
    assert fct.main(["--set", "18", "--out", str(out)]) == 0
    assert fake_http[0] == "https://raw.communitydragon.org/latest/cdragon/tft/en_us.json"
    raw = out.read_bytes()
    assert all(b < 0x80 for b in raw), "extract must be 7-bit ASCII"
    assert b"\r\n" not in raw and raw.count(b"\n") > 1
    assert json.loads(raw)["champions"] == ["Alune", "Kobuko", "Lux (Fae)"]
    assert list(out.parent.glob("*.tmp")) == []


def test_main_pbe_branch_url(tmp_path, fake_http):
    out = tmp_path / "x.json"
    assert fct.main(["--set", "18", "--branch", "pbe", "--out", str(out)]) == 0
    assert fake_http[0] == "https://raw.communitydragon.org/pbe/cdragon/tft/en_us.json"
    assert json.loads(out.read_bytes())["_branch"] == "pbe"


def test_main_missing_set_writes_nothing(tmp_path, fake_http):
    out = tmp_path / "x.json"
    out.write_bytes(b'{"keep": true}\n')
    assert fct.main(["--set", "19", "--out", str(out)]) != 0
    assert out.read_bytes() == b'{"keep": true}\n'
    assert list(tmp_path.glob("*.tmp")) == []


def test_main_reads_a_local_source_without_network(tmp_path, monkeypatch):
    def _no_net(url, **_kw):
        raise AssertionError("network used with --source")

    monkeypatch.setattr(fct, "_http_get", _no_net)
    src = tmp_path / "en_us.json"
    src.write_bytes(json.dumps(FIXTURE).encode("utf-8"))
    out = tmp_path / "x.json"
    assert fct.main(["--set", "18", "--source", str(src), "--out", str(out)]) == 0
    assert json.loads(out.read_bytes())["_content_version"] is None


def test_default_out_path_is_the_set_file():
    assert fct.default_out(18) == REPO_ROOT / "data" / "meta" / "tft_set18_cdragon.json"


# -- the committed Set 18 extract -----------------------------------------------

def test_committed_set18_extract_shape():
    p = REPO_ROOT / "data" / "meta" / "tft_set18_cdragon.json"
    raw = p.read_bytes()
    assert all(b < 0x80 for b in raw) and b"\r\n" not in raw
    ex = json.loads(raw)
    assert ex["_set"] == 18 and ex["_mutator"] == "TFTSet18"
    # Measured 2026-10-24 on CDragon latest 16.21: 91 champion rows, 36 traits.
    assert ex["_counts"]["champions_raw"] == 91
    assert ex["_counts"]["traits"] == 36
    assert len(ex["champions"]) == len(set(ex["champions"])) >= 60
    assert set(ex["unit_costs"]) == set(ex["champions"]) == set(ex["unit_traits"])
    assert all(1 <= c <= 5 for c in ex["unit_costs"].values())
    assert {"Elderwood", "Fae", "Coven", "Lunar", "Primal"} <= set(ex["all_traits"])
    assert ex["items"] and ex["augments"]
    # Game data only: no third-party comps or tier list in the extract.
    assert not {"comps", "tier_list"} & set(ex)
