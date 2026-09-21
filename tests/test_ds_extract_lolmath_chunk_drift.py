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
            'statPreference:{},"static/chunks/never.js"'
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
