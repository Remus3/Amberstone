"""Regression guards for the lolmath chunk-topology drift found at 16.18.1.

The DS 16.15.1 -> 16.18.1 refresh (2026-09-20) found that lolmath.net had
redeployed with a different shape, and ``tools/daemon_slayer_extract.py``
failed in two independent ways:

1. DISCOVERY. The ARAM-modifier ``JSON.parse`` block (anchor
   ``aramDamageTaken``) no longer ships in any chunk the root HTML names. It
   lives in a LAZILY loaded chunk two hops down the chunk graph (root chunk ->
   a chunk that lists worker chunks as ``"static/chunks/<id>.js"``). The other
   two Phase 1.5 blocks moved too: the damage distribution now sits in the
   scenarios chunk and the skill orders in a third chunk. The extractor
   assumed all three live in ONE "data chunk" and raised on discovery.

2. PARSE. The minifier re-rolled its enum aliases (``A.ChampionKey`` became
   ``x.ChampionKey``, ``k.DamageType`` became ``I.DamageType``,
   ``w.LanePosition`` became ``A.LanePosition``, ``I.GameModes`` became
   ``k.GameModes``). The substitution table pinned the LETTER, so every enum
   fell through to the generic dotted-ref -> null rule, every scenario lost
   its ``championKey`` and the extract produced ``scenarios=0`` and
   ``lanes=0`` - silently, with no exception.

The DS 16.20.1 -> 16.21.1 refresh (RM-766, 2026-10-22) found a third shape:

3. SPLIT SCENARIO PIECES. The one "scenarios chunk" that used to carry the
   cooldown table, the roles factory, the ratings dict, the lane list and
   every scenario record is now three chunks: the cooldown table and the
   DEFAULT champion's (Aatrox) scenario in a root chunk (one
   ``statPreference:`` hit), roles + ratings + lanes in a second root chunk,
   and the other 172 scenarios in a LAZILY loaded chunk (175 hits). The
   minifier also renamed the factory parameters (``(e,a,t)=>{a.exports=``
   became ``(a,i,e)=>{i.exports=``, ``e=>{"use strict";`` became
   ``a=>``/``l=>``), so the roles regex found nothing and raised.

Every test here is synthetic (no network, no live tree).
"""
from __future__ import annotations

import sys
from pathlib import Path

import json5
import pytest

ROOT = Path(__file__).resolve().parent.parent
_TOOLS = str(ROOT / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import daemon_slayer_extract as dse  # noqa: E402


def _jp(payload: str) -> str:
    """Wrap a JSON payload the way the minified chunks do."""
    return "x=JSON.parse('" + payload + "');"


ARAM = '{"Aatrox":{"aramDamageTaken":1,"aramDamageDealt":1.05}}'
DAMAGE = '{"Aatrox":{"physical":0.8,"magical":0.1,"trued":0.1}}'
SKILLS = '{"Aatrox":["Q","E","W","Q","Q","R"]}'
COOLDOWN_LIKE = '{"Aatrox":{"Q":[0,0,0,0,0,null]}}'


# --- (2) enum substitution is minifier-letter agnostic -----------------------

@pytest.mark.parametrize("prefix", ["A", "x", "I", "k", "w", "H", "_a", "$b"])
def test_enum_substitution_ignores_the_minifier_alias_letter(prefix):
    src = (
        "{championKey:%s.ChampionKey.aatrox,damageType:%s.DamageType.magic,"
        "target:%s.TargetType.enemy,usage:%s.UsageType.cast,"
        "lane:%s.LanePosition.mid,mode:%s.GameModes.aram,map:%s.MapId.arena}"
    ) % ((prefix,) * 7)
    parsed = json5.loads(dse._substitute(src))
    assert parsed == {
        "championKey": "aatrox",
        "damageType": "magic",
        "target": "enemy",
        "usage": "cast",
        "lane": "mid",
        "mode": "aram",
        "map": "arena",
    }


@pytest.mark.parametrize("helper", ["C", "ab", "$", "_", "$x"])
def test_cooldown_helper_call_collapses_for_any_minified_name(helper):
    # 16.18.1 minified Ashe's cooldown helper to `$`, which the old `\\b`
    # anchor could not see (no word boundary before `$`), so Ashe's whole
    # scenario binding failed to parse and she dropped out of scenarios.json.
    src = "{P:{cooldown:" + helper + '("P")},R:{cooldown:' + helper + '("R")}}'
    assert json5.loads(dse._substitute(src)) == {
        "P": {"cooldown": None},
        "R": {"cooldown": None},
    }


def test_unknown_dotted_value_refs_still_collapse_to_null():
    # The generic fallback must keep working for non-enum member refs.
    parsed = json5.loads(dse._substitute("{a:q.Something.else,b:1}"))
    assert parsed == {"a": None, "b": 1}


# --- (3) roles: pick the CLASS-LIST factory, not the first Aatrox: object ------

_KNOWN_CLASSES = {"FIGHTER", "TANK", "MAGE", "ASSASSIN", "MARKSMAN", "SUPPORT"}


def _factory(num: int, body: str) -> str:
    return "," + str(num) + ",(e,a,t)=>{a.exports=" + body + "}"


def test_roles_skip_a_string_valued_aatrox_factory():
    # 16.18.1 ships a {Aatrox:"General",...} survivability-label object AHEAD
    # of the class lists; the old "first factory with Aatrox:" rule picked it
    # and roles became a bare string.
    chunk = (
        _factory(26080, '{Aatrox:"General",Ahri:"General"}')
        + _factory(170996, '{Aatrox:["FIGHTER"],Ahri:["MAGE","ASSASSIN"]}')
        + _factory(265481, '{Aatrox:"top",Ahri:"mid"}')
    )
    assert dse._extract_roles(chunk) == {
        "Aatrox": ["FIGHTER"], "Ahri": ["MAGE", "ASSASSIN"],
    }


def test_roles_raise_when_no_class_list_factory_exists():
    chunk = _factory(1, '{Aatrox:"General",Ahri:"Squishy"}')
    with pytest.raises(RuntimeError, match="roles"):
        dse._extract_roles(chunk)


def test_current_snapshot_roles_are_class_token_lists():
    # Data guard on the COMMITTED current snapshot: a string here is iterated
    # character-by-character by core/build_planner/champ_kit_data.py.
    import json

    patch = (ROOT / "data" / "daemon_slayer" / "current.txt").read_text(
        encoding="utf-8").strip()
    champs = json.loads(
        (ROOT / "data" / "daemon_slayer" / patch / "champions.json").read_text(
            encoding="utf-8"))["data"]
    assert len(champs) >= 170
    bad = {
        cid: (rec.get("lolmath") or {}).get("roles")
        for cid, rec in champs.items()
        if not (
            isinstance((rec.get("lolmath") or {}).get("roles"), list)
            and (rec["lolmath"]["roles"])
            and set(rec["lolmath"]["roles"]) <= _KNOWN_CLASSES
        )
    }
    assert bad == {}, f"{len(bad)} champions carry non-class roles: {dict(list(bad.items())[:5])}"


# --- silent partial output is now loud ----------------------------------------

def _lolmath(cooldowns, scenarios, lanes):
    return dse.LolmathExtract(
        cooldowns=cooldowns, roles={}, ratings={}, lane_positions=lanes,
        scenarios=scenarios, chunk_url="u", chunk_bytes=1,
        aram_modifiers={}, damage_distribution={}, skill_orders={},
        data_chunk_url="", data_chunk_bytes=0,
    )


def test_coverage_check_raises_on_an_empty_scenario_or_lane_table():
    with pytest.raises(RuntimeError, match="scenarios"):
        dse.check_lolmath_coverage(_lolmath({"aatrox": {}}, {}, ["top"]))
    with pytest.raises(RuntimeError, match="lane"):
        dse.check_lolmath_coverage(_lolmath({"aatrox": {}}, {"aatrox": [{}]}, []))


def test_coverage_check_names_champions_missing_a_scenario():
    missing = dse.check_lolmath_coverage(
        _lolmath({"Aatrox": {}, "Ashe": {}}, {"aatrox": [{}]}, ["top"])
    )
    assert missing == ["Ashe"]


# --- (1) per-block extraction across split chunks ----------------------------

def test_data_blocks_are_found_when_split_across_three_chunks():
    bodies = {
        "u/aram.js": "noise;" + _jp(ARAM),
        "u/scen.js": _jp(COOLDOWN_LIKE) + _jp(DAMAGE),
        "u/skills.js": _jp(COOLDOWN_LIKE) + _jp(SKILLS),
    }
    out = dse.extract_data_blocks(bodies, preferred="u/aram.js")
    assert out["aram_modifiers"]["Aatrox"]["aramDamageDealt"] == 1.05
    assert out["damage_distribution"]["Aatrox"]["trued"] == 0.1
    assert out["skill_orders"]["Aatrox"][:3] == ["Q", "E", "W"]
    assert out["block_sources"] == {
        "aram_modifiers": "u/aram.js",
        "damage_distribution": "u/scen.js",
        "skill_orders": "u/skills.js",
    }
    # The manifest's single "data chunk" pointer stays the ARAM chunk.
    assert out["data_chunk_url"] == "u/aram.js"
    assert out["data_chunk_bytes"] == len(bodies["u/aram.js"])


def test_data_blocks_single_chunk_layout_still_works():
    body = _jp(ARAM) + _jp(DAMAGE) + _jp(SKILLS)
    out = dse.extract_data_blocks({"u/data.js": body}, preferred="u/data.js")
    assert set(out["block_sources"].values()) == {"u/data.js"}
    assert out["skill_orders"]["Aatrox"][0] == "Q"


def test_a_missing_block_raises_naming_the_block():
    bodies = {"u/aram.js": _jp(ARAM), "u/scen.js": _jp(DAMAGE)}
    with pytest.raises(RuntimeError, match="skill_orders"):
        dse.extract_data_blocks(bodies, preferred="u/aram.js")


# --- (1) discovery follows the lazy chunk graph ------------------------------

def test_discovery_follows_lazy_chunk_references(monkeypatch):
    base = "https://lolmath.net/_next/static/chunks/"
    html = '<script src="/_next/static/chunks/root1.js"></script>'
    pages = {
        dse.LOLMATH_ROOT: html,
        # root chunk: carries the scenarios anchor and names a loader chunk
        base + "root1.js": 'statPreference:{},e.l("hop11111.js")' + _jp(DAMAGE),
        # hop 1: a worker manifest listing chunks in the static/chunks form
        base + "hop11111.js": '["static/chunks/lazy2222.js","static/chunks/x.js"]',
        # hop 2: the lazily loaded chunk carrying the ARAM table
        base + "lazy2222.js": _jp(ARAM),
        base + "x.js": _jp(SKILLS),
    }
    fetched: list[str] = []

    def fake_fetch(url, timeout=30):
        fetched.append(url)
        return pages[url]

    monkeypatch.setattr(dse, "_fetch_text", fake_fetch)
    monkeypatch.setattr(dse, "_CHUNK_BODIES", {})

    scen_url, data_url = dse.discover_chunks()
    assert scen_url == base + "root1.js"
    assert data_url == base + "lazy2222.js"
    out = dse.extract_data_blocks(dse._CHUNK_BODIES, preferred=data_url)
    assert out["block_sources"]["skill_orders"] == base + "x.js"


def test_discovery_does_not_crawl_when_root_chunks_already_suffice(monkeypatch):
    base = "https://lolmath.net/_next/static/chunks/"
    html = '<script src="/_next/static/chunks/root1.js"></script>'
    pages = {
        dse.LOLMATH_ROOT: html,
        base + "root1.js": (
            "statPreference:{}," * dse.SCENARIO_ANCHOR_MIN_HITS
            + '"static/chunks/never.js"'
            + _jp(ARAM) + _jp(DAMAGE) + _jp(SKILLS)
        ),
    }
    fetched: list[str] = []

    def fake_fetch(url, timeout=30):
        fetched.append(url)
        return pages[url]

    monkeypatch.setattr(dse, "_fetch_text", fake_fetch)
    monkeypatch.setattr(dse, "_CHUNK_BODIES", {})
    dse.discover_chunks()
    assert base + "never.js" not in fetched


def test_discovery_still_raises_when_the_graph_has_no_aram_block(monkeypatch):
    base = "https://lolmath.net/_next/static/chunks/"
    pages = {
        dse.LOLMATH_ROOT: '<script src="/_next/static/chunks/root1.js"></script>',
        base + "root1.js": 'statPreference:{},"static/chunks/leaf.js"',
        base + "leaf.js": "nothing here",
    }
    monkeypatch.setattr(dse, "_fetch_text", lambda url, timeout=30: pages[url])
    monkeypatch.setattr(dse, "_CHUNK_BODIES", {})
    with pytest.raises(RuntimeError, match="aramDamageTaken"):
        dse.discover_chunks()


# --- (3) 16.21.1: factory parameter names are not pinned ----------------------

def test_roles_factory_header_parameter_names_are_not_pinned():
    # 16.21.1 minified the module factory as `(a,i,e)=>{i.exports=` instead of
    # `(e,a,t)=>{a.exports=`; the pinned `a.exports` matched nothing.
    chunk = (
        ",26080,(a,i,e)=>{i.exports={Aatrox:\"General\",Ahri:\"General\"}}"
        + ",34919,(a,i,e)=>{i.exports={Aatrox:[\"FIGHTER\"],Ahri:[\"MAGE\"]}}"
    )
    assert dse._extract_roles(chunk) == {"Aatrox": ["FIGHTER"], "Ahri": ["MAGE"]}


@pytest.mark.parametrize("param", ["e", "a", "l", "$t"])
def test_use_strict_factory_parameter_name_is_not_pinned(param):
    chunk = '[0,1,' + param + '=>{"use strict";let w=[1,2]}]'
    assert dse._extract_use_strict_factory_body(chunk) == '"use strict";let w=[1,2]'


# --- (3) 16.21.1: scenario pieces split across chunks --------------------------

_LANES = (
    "[t.LanePosition.top,t.LanePosition.jungle,t.LanePosition.mid,"
    "t.LanePosition.adc,t.LanePosition.support]"
)


def _scen(param: str, key: str) -> str:
    return (
        "," + param + '=>{"use strict";let w=[{name:"default",settings:'
        "{championKey:h.ChampionKey." + key + "},statPreference:{}}];e.s([w])}"
    )


def _split_bodies() -> dict[str, str]:
    return {
        # root chunk: the cooldown table + the default champion's scenario
        "u/root_cd.js": (
            _jp('{"Aatrox":{"Q":[4,4]},"Ahri":{"Q":[7,7]}}')
            + ',1,l=>{"use strict";let q={};}'
            + _scen("l", "aatrox")
        ),
        # root chunk: roles + ratings + lanes, plus a lane-token decoy list
        "u/root_meta.js": (
            ',2,(a,i,e)=>{i.exports={Aatrox:"General",Ahri:"Squishy"}}'
            + ',3,(a,i,e)=>{i.exports={Aatrox:["FIGHTER"],Ahri:["MAGE"]}}'
            + ',4,a=>{"use strict";let i={Aatrox:{ratings:{healing:10,shielding:0}},'
            + "Ahri:{ratings:{healing:4,shielding:0}}};"
            + 'let z=["top","Aatrox","mid","x"];let u=' + _LANES + ";}"
        ),
        # lazily loaded chunk: every other champion's scenario
        "u/lazy_scen.js": _scen("e", "ahri"),
    }


def test_scenario_pieces_are_found_when_split_across_chunks():
    bodies = _split_bodies()
    out = dse.extract_from_bodies(bodies, preferred="u/lazy_scen.js")
    assert set(out.cooldowns) == {"Aatrox", "Ahri"}
    assert out.roles == {"Aatrox": ["FIGHTER"], "Ahri": ["MAGE"]}
    assert set(out.ratings) == {"Aatrox", "Ahri"}
    assert out.lane_positions == ["top", "jungle", "mid", "adc", "support"]
    assert set(out.scenarios) == {"aatrox", "ahri"}
    assert out.chunk_url == "u/lazy_scen.js"
    assert out.chunk_bytes == len(bodies["u/lazy_scen.js"])
    assert out.scenario_sources == {
        "cooldowns": "u/root_cd.js",
        "roles": "u/root_meta.js",
        "ratings": "u/root_meta.js",
        "lane_positions": "u/root_meta.js",
        "scenarios": ["u/lazy_scen.js", "u/root_cd.js"],
    }
    assert dse.check_lolmath_coverage(out) == []


def test_single_chunk_layout_still_resolves_through_extract_from_chunk():
    chunk = "".join(_split_bodies().values())
    out = dse.extract_from_chunk(chunk, "u/one.js")
    assert set(out.scenarios) == {"aatrox", "ahri"}
    assert out.lane_positions == ["top", "jungle", "mid", "adc", "support"]
    assert out.scenario_sources["scenarios"] == ["u/one.js"]
    assert {
        k: v for k, v in out.scenario_sources.items() if k != "scenarios"
    } == dict.fromkeys(("cooldowns", "roles", "ratings", "lane_positions"), "u/one.js")


def test_a_missing_cooldown_table_raises_naming_the_anchor():
    bodies = _split_bodies()
    del bodies["u/root_cd.js"]
    with pytest.raises(RuntimeError, match="Aatrox"):
        dse.extract_from_bodies(bodies, preferred="u/lazy_scen.js")


def test_discovery_crawls_for_a_lazily_loaded_scenario_table(monkeypatch):
    # 16.21.1: the root set carries every data block and ONE statPreference:
    # hit (the default champion); the full scenario table is a lazy chunk.
    base = "https://lolmath.net/_next/static/chunks/"
    html = '<script src="/_next/static/chunks/root1.js"></script>'
    pages = {
        dse.LOLMATH_ROOT: html,
        base + "root1.js": (
            'statPreference:{},"static/chunks/hop11111.js"'
            + _jp(ARAM) + _jp(DAMAGE) + _jp(SKILLS)
        ),
        base + "hop11111.js": '["static/chunks/lazyscen.js"]',
        base + "lazyscen.js": "statPreference:{}," * (dse.SCENARIO_ANCHOR_MIN_HITS + 5),
    }
    monkeypatch.setattr(dse, "_fetch_text", lambda url, timeout=30: pages[url])
    monkeypatch.setattr(dse, "_CHUNK_BODIES", {})
    scen_url, data_url = dse.discover_chunks()
    assert scen_url == base + "lazyscen.js"
    assert data_url == base + "root1.js"
