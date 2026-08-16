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


# --------------------------------------------------------------------------- RM-81 shape
#
# Some stored ``base`` arrays are a per-RANK series concatenated with a per-LEVEL
# series, so the old ``base[-1]`` read returned a level-scaled number in place of
# the max-rank base. On Mordekaiser Q that turned a real 4.6% drift into a
# reported 389% one - and because those inflated rows were the loudest in the
# sweep, the bug did not merely add noise, it mis-ranked which champions were
# worth re-sourcing.
#
# Every fixture below is verbatim from the committed `champion_abilities.json`
# (patch 16.14.1) and the live wiki Data templates, and the wiki independently
# confirms the shape rather than the test merely asserting the implementation:
# Mordekaiser's Data page hoists BOTH series as named variables -
#
#     {{#vardefine:p1|0}}    <!-- Level 1 base damage
#     {{#vardefine:p18|45}}  <!-- Level 18 base damage
#     {{#vardefine:b1|80}}   <!-- Rank 1 base damage
#     {{#vardefine:b5|220}}  <!-- Rank 5 base damage
#
# so the 45.0 the old code reported as "the rank-5 base" is documented upstream as
# the LEVEL-18 value, and the true rank-5 endpoint is 220 live / 230.59 stored.

# --------------------------------------------------------------------------- fixtures

# Verbatim champion_abilities.json -> data.Mordekaiser.Q[0]. 18 entries: the 5
# real ranks, then the 13-entry level-6..18 tail ending at p18 = 45.
MORDEKAISER_Q_MERAKI = {
    "key": "Q",
    "name": "Obliterate",
    "cooldown": [8.0, 7.0, 6.0, 5.0, 4.0],
    "damage_blocks": [
        {
            "attribute": "Magic Damage",
            "attribute_kind": "damage",
            "base": [
                80.0, 117.6470588235294, 155.2941176470588,
                192.94117647058823, 230.58823529411765,
                13.235294117647058, 15.882352941176471, 18.52941176470588,
                21.176470588235293, 23.823529411764707, 26.470588235294116,
                29.11764705882353, 31.764705882352942, 34.411764705882355,
                37.05882352941176, 39.705882352941174, 42.35294117647059,
                45.0,
            ],
        }
    ],
}

# Verbatim Template:Data Mordekaiser/Obliterate, #vardefine block preserved.
MORDEKAISER_Q_WIKI = (
    "-->{{#vardefine:p1|0}}<!-- Level 1 base damage\n"
    "-->{{#vardefine:p18|45}}<!-- Level 18 base damage\n"
    "-->{{#vardefine:b1|80}}<!-- Rank 1 base damage\n"
    "-->{{#vardefine:b5|220}}<!-- Rank 5 base damage\n"
    "-->|leveling     = {{st|Magic Damage|{{ap|{{#var:b1}} to {{#var:b5}}}} "
    "{{as|(+ 70% AP)}}}}\n"
    "|cooldown     = {{ap|8 to 4}}\n"
)

# Verbatim data.Malzahar.W[0]. Ranks 17..39, then a tail that CLIMBS to 64.5 -
# the array does not decrease end to end, which is why the tell has to be an
# internal drop and not `base[-1] < base[0]`.
MALZAHAR_W_BASE = [
    17.0, 22.5, 28.0, 33.5, 39.0,
    22.5, 26.0, 29.5, 33.0, 36.5, 40.0, 43.5, 47.0, 50.5, 54.0, 57.5, 61.0,
    64.5,
]

# Verbatim data.Sona.Q[0]. Sona's Q cooldown is rank-INVARIANT, so Meraki stores
# a 1-entry cooldown against a 5-entry base. Wiki agrees: `{{ap|50 to 190}}`
# with a bare `|cooldown = 8`.
SONA_Q_MERAKI = {
    "key": "Q",
    "name": "Hymn of Valor",
    "cooldown": [8.0],
    "damage_blocks": [
        {"attribute": "Magic Damage", "base": [50.0, 85.0, 120.0, 155.0, 190.0]},
    ],
}
SONA_Q_WIKI = (
    "|leveling     = {{st|Magic Damage|{{ap|50 to 190}} {{as|(+ 40% AP)}}}}\n"
    "|cooldown     = 8\n"
)

# Verbatim data.AurelionSol.Q[0]. 4 base entries against 5 cooldowns.
AURELIONSOL_Q_MERAKI = {
    "key": "Q",
    "name": "Breath of Light",
    "cooldown": [3.0, 3.0, 3.0, 3.0, 3.0],
    "damage_blocks": [
        {"attribute": "Total Maximum Magic Damage",
         "base": [146.25, 195.0, 243.75, 292.5]},
    ],
}

# Verbatim data.Shen.Q[0]. A LEGITIMATE 18-entry per-level series with no rank
# component at all - the wiki writes it `{{pp|10 to 40 for 6|1 to 16}}`, a
# per-level macro - so 40.0 is the correct endpoint and it must not be cut.
SHEN_Q_MERAKI = {
    "key": "Q",
    "name": "Twilight Assault",
    "cooldown": [8.0, 7.25, 6.5, 5.75, 5.0],
    "damage_blocks": [
        {
            "attribute": "Bonus Magic Damage",
            "base": [
                10.0, 11.764705882352942, 13.529411764705882,
                15.294117647058822, 17.058823529411764, 18.823529411764707,
                20.588235294117645, 22.352941176470587, 24.11764705882353,
                25.88235294117647, 27.647058823529413, 29.41176470588235,
                31.176470588235293, 32.94117647058823, 34.705882352941174,
                36.470588235294116, 38.23529411764706, 40.0,
            ],
        }
    ],
}


# --------------------------------------------------------------------------- the bug

def test_concatenated_per_level_tail_is_not_read_as_max_rank():
    """The core defect. `base[-1]` is 45.0, the LEVEL-18 value, not rank 5."""
    got = M.meraki_endpoints(MORDEKAISER_Q_MERAKI)
    lo, hi = got["bases"]["Magic Damage"]
    assert lo == 80.0
    assert 230.5 < hi < 230.7, f"expected the rank-5 base ~230.59, got {hi}"


def test_mordekaiser_q_delta_is_five_percent_not_three_hundred_eighty_nine():
    """End to end: the reported magnitude must match the real balance delta."""
    findings = M.compare_ability(
        "Mordekaiser", "Q", MORDEKAISER_Q_MERAKI, MORDEKAISER_Q_WIKI
    )
    row = next(f for f in findings if f["field"] == "base:Magic Damage")
    assert row["wiki"] == [80.0, 220.0]
    delta = abs(row["wiki"][1] - row["meraki"][1]) / row["meraki"][1]
    assert delta < 0.10, f"reported delta {delta:.1%}, true drift is 4.6%"


def test_shape_suspect_marker_is_emitted_for_a_concatenated_row():
    findings = M.compare_ability(
        "Mordekaiser", "Q", MORDEKAISER_Q_MERAKI, MORDEKAISER_Q_WIKI
    )
    row = next(f for f in findings if f["field"] == "base:Magic Damage")
    marker = row["SHAPE_SUSPECT"]
    assert marker["kept_ranks"] == 5
    assert marker["stored_len"] == 18
    assert marker["cooldown_ranks"] == 5
    assert marker["dropped_tail"][-1] == 45.0


def test_internal_drop_not_end_to_end_decrease_is_the_tell():
    """Malzahar W climbs 17..39 then restarts at 22.5 and ends ABOVE rank 1."""
    assert MALZAHAR_W_BASE[-1] > MALZAHAR_W_BASE[0]
    kept, marker = M.rank_series(MALZAHAR_W_BASE, [8.0] * 5)
    assert marker is not None
    assert kept == [17.0, 22.5, 28.0, 33.5, 39.0]


# ------------------------------------------------------- guards on the cure itself
# len(cooldown) is NOT a usable rank count. These three pin the cases that a
# cooldown-indexed truncation gets wrong on live 16.14.1 data.

def test_rank_invariant_cooldown_does_not_collapse_base_to_rank_one():
    """Sona Q: 1 cooldown, 5 ranks. Indexing by len(cooldown) reports 50 for 190."""
    got = M.meraki_endpoints(SONA_Q_MERAKI)
    assert got["bases"]["Magic Damage"] == (50.0, 190.0)
    assert M.compare_ability("Sona", "Q", SONA_Q_MERAKI, SONA_Q_WIKI) == []


def test_base_shorter_than_cooldown_does_not_raise():
    """Aurelion Sol Q: 4 base entries, 5 cooldowns. base[len(cd)-1] IndexErrors."""
    got = M.meraki_endpoints(AURELIONSOL_Q_MERAKI)
    assert got["bases"]["Total Maximum Magic Damage"] == (146.25, 292.5)


def test_legitimate_per_level_base_is_not_truncated():
    """Shen Q is per-level all the way down: 40.0 is right, 17.06 is not."""
    got = M.meraki_endpoints(SHEN_Q_MERAKI)
    assert got["bases"]["Bonus Magic Damage"] == (10.0, 40.0)
    assert got["shape_suspect"] == {}


def test_clean_rank_series_is_untouched_and_unmarked():
    got = M.meraki_endpoints(MAOKAI_Q_MERAKI[0])
    assert got["bases"]["Magic Damage"] == (65.0, 245.0)
    assert got["shape_suspect"] == {}


def test_per_level_passive_cooldown_may_legitimately_decrease():
    """Cooldowns are exempt from the drop rule - Maokai's passive runs 30 -> 20."""
    entry = {"key": "P", "name": "Sap Magic",
             "cooldown": [30.0 - i * (10.0 / 17.0) for i in range(18)],
             "damage_blocks": []}
    assert M.meraki_endpoints(entry)["cooldown"] == (30.0, 20.0)


# --------------------------------------------------------------------------- RM-216
#
# Both skip paths used to `continue` without a counter or a log line, so a
# champion could DROP OUT of the report entirely and the shrinking stale set
# read as convergence. The two renames below are the realistic triggers: the
# wiki moves a Data page when an ability is renamed (the page-level skip), and
# it relabels a damage line on a rework (the label-level skip). Neither is a
# data error, so the run must keep going - but it must SAY SO.

# MAOKAI_Q_WIKI with only the damage LABEL renamed. Same numbers, and those
# numbers still disagree with the stored 65..245, so a finding is owed unless
# the label miss is what suppressed it.
MAOKAI_Q_WIKI_RELABELLED = MAOKAI_Q_WIKI.replace(
    "{{st|Magic Damage|", "{{st|Magic Damage Per Hit|"
)


def test_renamed_damage_label_is_recorded_not_silently_dropped():
    skipped: list = []
    findings = M.compare_ability(
        "Maokai", "Q", MAOKAI_Q_MERAKI[0], MAOKAI_Q_WIKI_RELABELLED,
        skipped_labels=skipped,
    )
    assert findings == [], "cooldowns match; only the label miss is in play"
    assert [(s["champion"], s["ability"], s["label"]) for s in skipped] == [
        ("Maokai", "Q", "Magic Damage")
    ]


def test_matched_damage_label_records_no_skip():
    """Negative control: the counter must not fire on a healthy compare."""
    skipped: list = []
    M.compare_ability(
        "Maokai", "Q", MAOKAI_Q_MERAKI[0], MAOKAI_Q_WIKI, skipped_labels=skipped
    )
    assert skipped == []


def test_renamed_wiki_page_is_recorded_not_silently_dropped():
    skipped: list = []
    findings = M.compare_champion(
        "Maokai", {"Q": MAOKAI_Q_MERAKI},
        {"Bramble Smash (Rework)": MAOKAI_Q_WIKI},
        skipped_pages=skipped,
    )
    assert findings == []
    assert [(s["champion"], s["ability"], s["name"]) for s in skipped] == [
        ("Maokai", "Q", "Bramble Smash")
    ]


def test_matched_wiki_page_records_no_skip():
    skipped: list = []
    M.compare_champion(
        "Maokai", {"Q": MAOKAI_Q_MERAKI}, {"Bramble Smash": MAOKAI_Q_WIKI},
        skipped_pages=skipped,
    )
    assert skipped == []


def _stub_run(monkeypatch, wiki_by_title):
    """Drive `run()` with no network: one champion, one ability, one page."""
    monkeypatch.setattr(
        M, "_load_abilities",
        lambda patch: {"meraki_content_patch": "25.15",
                       "data": {"Maokai": {"Q": MAOKAI_Q_MERAKI}}},
    )
    monkeypatch.setattr(M, "fetch_pages", lambda titles: dict(wiki_by_title))


def test_run_report_counts_and_names_the_page_skip(monkeypatch):
    """The champion must appear in the report body, not vanish from it."""
    _stub_run(monkeypatch, {"Template:Data Maokai/Bramble Smash (Rework)":
                            MAOKAI_Q_WIKI})
    rep = M.run("16.15.1")

    assert rep["stale_champions"] == []
    assert rep["_skipped_pages"] == 1
    assert rep["skipped_champions"] == ["Maokai"]
    assert rep["skipped_pages"][0]["name"] == "Bramble Smash"


def test_run_report_counts_and_names_the_label_skip(monkeypatch):
    _stub_run(monkeypatch, {"Template:Data Maokai/Bramble Smash":
                            MAOKAI_Q_WIKI_RELABELLED})
    rep = M.run("16.15.1")

    assert rep["_skipped_labels"] == 1
    assert rep["skipped_champions"] == ["Maokai"]
    assert rep["skipped_labels"][0]["label"] == "Magic Damage"


def test_run_report_is_quiet_when_nothing_is_skipped(monkeypatch):
    _stub_run(monkeypatch, {"Template:Data Maokai/Bramble Smash": MAOKAI_Q_WIKI})
    rep = M.run("16.15.1")

    assert rep["stale_champions"] == ["Maokai"]
    assert rep["_skipped_pages"] == 0
    assert rep["_skipped_labels"] == 0
    assert rep["skipped_champions"] == []


def test_partial_run_carries_forward_prior_skips(tmp_path, monkeypatch):
    """Same hazard `write_report` already fixes for findings: a --recent pass
    over one champion must not erase everyone else's skip record."""
    monkeypatch.setattr(M, "DATA_DIR", tmp_path)
    (tmp_path / "16.15.1").mkdir(parents=True)
    full = _report({"Mel"}, mode="full")
    full["skipped_pages"] = [{"champion": "Ahri", "ability": "Q", "name": "Orb"}]
    full["skipped_labels"] = [{"champion": "Zyra", "ability": "W",
                               "label": "Magic Damage"}]
    M.write_report(full, "16.15.1")

    partial = _report({"Mel"})
    partial["skipped_pages"] = []
    partial["skipped_labels"] = []
    M.write_report(partial, "16.15.1", checked={"Mel"})

    got = json.loads(
        (tmp_path / "16.15.1" / M.REPORT_NAME).read_text(encoding="utf-8")
    )
    assert [s["champion"] for s in got["skipped_pages"]] == ["Ahri"]
    assert [s["champion"] for s in got["skipped_labels"]] == ["Zyra"]
    assert got["skipped_champions"] == ["Ahri", "Zyra"]
    assert got["_skipped_pages"] == 1
