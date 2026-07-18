"""RM-81: detect champions whose stored Meraki ability data predates a rework.

The DS ability corpus (`champion_abilities.json`) is pinned to Meraki content
patch 25.15 while the live game is ~11 patches ahead, so a champion can be
PRESENT in the map (`champion_has_ability_data` -> True, the RM-79 guard stays
quiet) while carrying values that no longer exist. The existing CDragon drift
report is ratio-only (ap_pct / total_ad_pct / caster_max_hp_pct / bonus_ad_pct)
and cannot see the two fields that actually carry the evidence: base damage and
cooldowns.

These fixtures are verbatim from the live wiki Data templates on patch 16.14
and the committed `champion_abilities.json`, so the two regression cases below
are the real RM-81 findings, not synthetic ones:

  * Maokai Q Bramble Smash - stored base 65..245, live 75..255 (V26.03 buff).
    Cooldowns are UNCHANGED, so a cooldown-only detector misses him entirely.
  * Mel W Rebuttal - stored cooldown 35..23, live 38..26 (26.08 nerf). Its
    damage block carries no base, so a base-only detector misses her.

Together they pin both halves of the comparison.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import ds_wiki_staleness_check as M  # noqa: E402

# --------------------------------------------------------------------------- fixtures

MAOKAI_Q_WIKI = (
    "|leveling     = {{st|Magic Damage|{{ap|75 to 255}} {{as|(+ {{ap|2 to 4}}% "
    "of the target's '''maximum''' health)}} {{as|(+ 40% AP)}}}}\n"
    "|effect radius= {{tt|325|Knockback circle radius around Maokai}}\n"
    "|cost         = 40\n"
    "|costtype     = Mana\n"
    "|cooldown     = {{ap|7 to 5}}\n"
    "|damagetype   = Magic\n"
)

MEL_W_WIKI = (
    "|cast time    = 0.25\n"
    "|cooldown     = {{ap|38 to 26}}\n"
    "|damagetype   = Magic\n"
)

# Shape mirrors champion_abilities.json -> data[champ][slot] (a LIST of forms).
MAOKAI_Q_MERAKI = [
    {
        "key": "Q",
        "name": "Bramble Smash",
        "form_index": 0,
        "cooldown": [7.0, 6.5, 6.0, 5.5, 5.0],
        "damage_blocks": [
            {
                "attribute": "Magic Damage",
                "attribute_kind": "damage",
                "base": [65.0, 110.0, 155.0, 200.0, 245.0],
                "ap_pct": [40.0] * 5,
            },
            {"attribute": "Bonus Monster Damage", "attribute_kind": "modifier"},
        ],
    }
]

MEL_W_MERAKI = [
    {
        "key": "W",
        "name": "Rebuttal",
        "form_index": 0,
        "cooldown": [35.0, 32.0, 29.0, 26.0, 23.0],
        "damage_blocks": [
            {"attribute": "Replicated Projectile Damage Modifier"},
        ],
    }
]


# --------------------------------------------------------------------------- endpoint parsing

def test_parse_endpoints_ap_wrapper():
    assert M.parse_endpoints("{{ap|7 to 5}}") == (7.0, 5.0)
    assert M.parse_endpoints("{{ap|38 to 26}}") == (38.0, 26.0)


def test_parse_endpoints_bare_number_is_flat():
    assert M.parse_endpoints("40") == (40.0, 40.0)


def test_parse_endpoints_rejects_unparseable():
    assert M.parse_endpoints("") is None
    assert M.parse_endpoints("{{tip|cr}} 450 based on level") is None


def test_parse_leveling_bases_extracts_labelled_first_ratio():
    got = M.parse_leveling_bases(MAOKAI_Q_WIKI)
    assert got.get("Magic Damage") == (75.0, 255.0)


def test_parse_leveling_bases_ignores_trailing_percent_ratios():
    """The {{ap|2 to 4}}% maxHP term must not be mistaken for the base."""
    got = M.parse_leveling_bases(MAOKAI_Q_WIKI)
    assert (2.0, 4.0) not in got.values()


def test_parse_param_reads_cooldown():
    assert M.parse_param(MAOKAI_Q_WIKI, "cooldown") == "{{ap|7 to 5}}"
    assert M.parse_param(MEL_W_WIKI, "cooldown") == "{{ap|38 to 26}}"


# --------------------------------------------------------------------------- meraki side

def test_meraki_endpoints_reads_cooldown_and_base():
    got = M.meraki_endpoints(MAOKAI_Q_MERAKI[0])
    assert got["cooldown"] == (7.0, 5.0)
    assert got["bases"]["Magic Damage"] == (65.0, 245.0)


def test_meraki_endpoints_skips_blocks_without_base():
    got = M.meraki_endpoints(MEL_W_MERAKI[0])
    assert got["bases"] == {}
    assert got["cooldown"] == (35.0, 23.0)


# --------------------------------------------------------------------------- comparison

def test_maokai_base_drift_is_detected():
    """The base-damage half: Maokai's cooldowns match, only his base drifted."""
    findings = M.compare_ability("Maokai", "Q", MAOKAI_Q_MERAKI[0], MAOKAI_Q_WIKI)
    fields = {f["field"] for f in findings}
    assert "base:Magic Damage" in fields
    assert "cooldown" not in fields, "Maokai cooldowns are unchanged in 16.14"
    row = next(f for f in findings if f["field"] == "base:Magic Damage")
    assert row["meraki"] == [65.0, 245.0]
    assert row["wiki"] == [75.0, 255.0]
    assert row["champion"] == "Maokai"
    assert row["ability"] == "Q"


def test_mel_cooldown_drift_is_detected():
    """The cooldown half: Mel's W block has no base, only her cooldown drifted."""
    findings = M.compare_ability("Mel", "W", MEL_W_MERAKI[0], MEL_W_WIKI)
    row = next(f for f in findings if f["field"] == "cooldown")
    assert row["meraki"] == [35.0, 23.0]
    assert row["wiki"] == [38.0, 26.0]


def test_matching_values_produce_no_finding():
    clean = dict(MAOKAI_Q_MERAKI[0])
    clean["damage_blocks"] = [
        {
            "attribute": "Magic Damage",
            "attribute_kind": "damage",
            "base": [75.0, 120.0, 165.0, 210.0, 255.0],
        }
    ]
    assert M.compare_ability("Maokai", "Q", clean, MAOKAI_Q_WIKI) == []


def test_float_noise_within_tolerance_is_not_a_finding():
    noisy = dict(MAOKAI_Q_MERAKI[0])
    noisy["cooldown"] = [7.0001, 6.5, 6.0, 5.5, 4.9999]
    noisy["damage_blocks"] = []
    assert M.compare_ability("Maokai", "Q", noisy, MAOKAI_Q_WIKI) == []


def test_compare_champion_matches_wiki_pages_by_ability_name():
    meraki_champ = {"Q": MAOKAI_Q_MERAKI}
    findings = M.compare_champion(
        "Maokai", meraki_champ, {"Bramble Smash": MAOKAI_Q_WIKI}
    )
    assert [f["field"] for f in findings] == ["base:Magic Damage"]


def test_compare_champion_ignores_abilities_with_no_wiki_page():
    meraki_champ = {"Q": MAOKAI_Q_MERAKI}
    assert M.compare_champion("Maokai", meraki_champ, {}) == []


# --------------------------------------------------------------------------- recent-changes feed

def test_champions_from_recent_titles_filters_to_data_templates():
    titles = [
        "Template:Data Mel/Rebuttal",
        "Template:Data Maokai/Bramble Smash",
        "Template:Map/Summoner's Rift",
        "Some other page",
    ]
    assert M.champions_from_titles(titles) == {"Mel", "Maokai"}


def test_champions_from_titles_handles_multiword_champion_names():
    assert M.champions_from_titles(
        ["Template:Data Master Yi/Alpha Strike"]
    ) == {"Master Yi"}


# --------------------------------------------------------------------------- mediawiki variables

# Verbatim from Template:Data Garen/Demacian Justice. Some Data pages hoist their
# numbers into #vardefine at the top and reference them indirectly, so the
# leveling line carries no literal digits at all. Garen was a measured recall
# miss: Riot's 26.14 notes cut his R from 150/250/350 to 125/200/275 and the
# detector saw nothing, because {{#var:b1}} does not match a number regex.
GAREN_R_WIKI = (
    "<!-- Damage values are defined as parameters.\n"
    "-->{{#vardefine:b1|125}}<!-- Rank 1 base damage\n"
    "-->{{#vardefine:b3|275}}<!-- Rank 3 base damage\n"
    "-->{{#vardefine:h1|25}}<!-- Rank 1 health damage as a PERCENTAGE\n"
    "-->{{#vardefine:h3|35}}<!-- Rank 3 health damage as a PERCENTAGE\n"
    "-->|champion     = Garen\n"
    "|leveling     = {{st|True Damage|{{ap|{{#var:b1}} to {{#var:b3}}}} "
    "{{as|(+ {{ap|{{#var:h1}} to {{#var:h3}}}}% of target's '''missing''' health)}}}}\n"
    "|cooldown     = {{ap|120 to 80}}\n"
)

GAREN_R_MERAKI = {
    "key": "R",
    "name": "Demacian Justice",
    "cooldown": [120.0, 100.0, 80.0],
    "damage_blocks": [
        {"attribute": "True Damage", "attribute_kind": "damage",
         "base": [150.0, 250.0, 350.0]},
    ],
}


def test_resolves_vardefine_indirection():
    assert M.parse_leveling_bases(GAREN_R_WIKI).get("True Damage") == (125.0, 275.0)


def test_vardefine_recall_miss_is_now_caught():
    """The Garen regression: a real base change that used to be invisible."""
    findings = M.compare_ability("Garen", "R", GAREN_R_MERAKI, GAREN_R_WIKI)
    row = next(f for f in findings if f["field"] == "base:True Damage")
    assert row["meraki"] == [150.0, 350.0]
    assert row["wiki"] == [125.0, 275.0]


def test_vardefine_percent_term_still_not_read_as_base():
    """The missing-health term is also #var-driven; it must stay out of bases."""
    got = M.parse_leveling_bases(GAREN_R_WIKI)
    assert (25.0, 35.0) not in got.values()


def test_unresolvable_var_yields_no_finding():
    """A #var with no matching #vardefine must skip, not guess."""
    text = "|leveling = {{st|True Damage|{{ap|{{#var:zz1}} to {{#var:zz3}}}}}}\n"
    assert M.parse_leveling_bases(text) == {}


# --------------------------------------------------------------------------- report merge

def _report(champs, mode="recent"):
    return {
        "_patch": "16.14.1",
        "_mode": mode,
        "stale_champions": sorted(champs),
        "findings": [
            {"champion": c, "ability": "Q", "field": "cooldown",
             "meraki": [1.0, 1.0], "wiki": [2.0, 2.0]}
            for c in sorted(champs)
        ],
    }


def test_partial_run_must_not_clobber_a_full_report(tmp_path, monkeypatch):
    """A --recent pass re-checks a handful of champions. Writing its result
    verbatim would erase everything --full established - turning a 71-champion
    report into a 1-champion one and silently marking 70 champions current."""
    monkeypatch.setattr(M, "DATA_DIR", tmp_path)
    (tmp_path / "16.14.1").mkdir(parents=True)
    M.write_report(_report({"Mel", "Maokai", "Ahri"}, mode="full"), "16.14.1")

    M.write_report(_report({"Zyra"}), "16.14.1", checked={"Zyra"})

    got = json.loads(
        (tmp_path / "16.14.1" / M.REPORT_NAME).read_text(encoding="utf-8")
    )
    assert got["stale_champions"] == ["Ahri", "Maokai", "Mel", "Zyra"]


def test_partial_run_clears_a_champion_that_became_current(tmp_path, monkeypatch):
    """If a re-checked champion no longer drifts, its stale rows must go away."""
    monkeypatch.setattr(M, "DATA_DIR", tmp_path)
    (tmp_path / "16.14.1").mkdir(parents=True)
    M.write_report(_report({"Mel", "Maokai"}, mode="full"), "16.14.1")

    cleared = {"_patch": "16.14.1", "stale_champions": [], "findings": []}
    M.write_report(cleared, "16.14.1", checked={"Mel"})

    got = json.loads(
        (tmp_path / "16.14.1" / M.REPORT_NAME).read_text(encoding="utf-8")
    )
    assert got["stale_champions"] == ["Maokai"]


def test_full_run_replaces_the_report_wholesale(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "DATA_DIR", tmp_path)
    (tmp_path / "16.14.1").mkdir(parents=True)
    M.write_report(_report({"Mel", "Maokai"}, mode="full"), "16.14.1")

    M.write_report(_report({"Zyra"}, mode="full"), "16.14.1", checked=None)

    got = json.loads(
        (tmp_path / "16.14.1" / M.REPORT_NAME).read_text(encoding="utf-8")
    )
    assert got["stale_champions"] == ["Zyra"]


# --------------------------------------------------------------------------- patch discovery

def test_current_patch_ignores_non_version_dirs_and_sorts_numerically(tmp_path, monkeypatch):
    """`data/daemon_slayer/` also holds `laning_scenarios`, and a lexical sort
    would rank 16.9.1 above 16.14.1."""
    for name in ("16.9.1", "16.13.1", "16.14.1", "laning_scenarios"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(M, "DATA_DIR", tmp_path)
    assert M._current_patch() == "16.14.1"
