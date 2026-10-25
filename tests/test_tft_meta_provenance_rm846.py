"""Guard (RM-846): a tracked TFT meta file names no source NOTICE does not
credit, and carries no third-party-derived field without a NOTICE entry.

WHY
---
RC is Apache-2.0 and PUBLIC. Until 2026-10-24 data/meta/tft_set17_meta.json,
its PBE twin and tft_set16_meta.json carried comps, a tier list, augment
ratings, leveling plans and ladder statistics (top-4 rate, average placement,
play rate) whose own provenance fields named third-party guide sites and
stats aggregators - the scrubbed descriptors "aggregator C", "TFT guide author
X", "TFT guide site W" / "Y", "overlay app E", "aggregator J", plus the
abbreviated display_source tokens the 2026-09-07 name scrub missed. NOTICE
credited none of them, and none publishes that content under terms that allow
redistribution in a public Apache-2.0 repo (the licence gate in CLAUDE.md:
unlicensed = cannot be absorbed). RM-846 removed the payloads; this guard
keeps them out.

THE RULES, per tracked data/meta/tft_set*.json
----------------------------------------------
1. A top-level "_source" string is required: a file with no provenance cannot
   be audited.
2. Every provenance string, at any depth (PROVENANCE_KEYS), must name a party
   NOTICE credits (CREDITED) or an RC-own marker (RC_OWN); must not carry a
   scrubbed third-party descriptor ("aggregator C", "overlay app E", ...); and
   every host name in it must belong to a credited party.
3. A ladder statistic (STAT_KEYS) needs a provenance string in its own row or
   an ancestor that names a credited party able to produce one. Game files
   (CommunityDragon) carry no ladder statistics, and one operator's games
   cannot produce a play rate, so today only a Riot API / Match-V5 measurement
   qualifies.
4. Every CREDITED party is named in NOTICE, and NOTICE carries a TFT entry
   for data/meta/tft_set*: deleting the attribution turns this guard red.

Adding a genuinely clearable source = a NOTICE entry plus a CREDITED row, in
the same commit. Never relabel third-party rows as RC-authored.

ENUMERATION: the git index via tests/_repo_walk (tracked files only, so a
gitignored local dump under data/meta/ cannot turn the operator's box red
while CI stays green). An empty enumeration FAILS (test_enumeration_is_anchored),
and the checker is proven to fire on the removed payload's shape
(test_checker_fires_on_the_removed_payload_shape) so a green run is not a
checker that sees nothing. Old revisions in git history still hold the removed
blobs; a history rewrite runs only on MAIN's ORDER (fleet_rewrite.py).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests import _repo_walk
from tft import tft_set

REPO_ROOT = Path(__file__).resolve().parent.parent
META_DIR = REPO_ROOT / "data" / "meta"
NOTICE = REPO_ROOT / "NOTICE"

# Parties NOTICE credits for TFT meta files. aliases: lowercase substrings
# that count as naming the party; notice: the text NOTICE must carry; stats:
# whether the party can be the source of a ladder statistic (rule 3).
CREDITED = {
    "CommunityDragon": {
        "aliases": ("communitydragon", "cdragon"),
        "notice": "CommunityDragon",
        "stats": False,
    },
    "Riot API / Match-V5": {
        "aliases": ("riot api", "match-v5"),
        "notice": "Riot API / Match-V5",
        "stats": True,
    },
    "Riot": {
        "aliases": ("riot",),
        "notice": "Riot Games",
        "stats": False,
    },
}
CREDITED_HOSTS = ("communitydragon.org", "riotgames.com", "leagueoflegends.com")
RC_OWN = ("rc-authored", "rc-measured", "operator-measured")

PROVENANCE_KEYS = frozenset({
    "_source", "_sources", "source", "sources", "_bm_source",
    "display_source", "_source_url", "source_url", "_provenance",
    "provenance", "credit", "_credit",
})
STAT_KEYS = frozenset({
    "top4_pct", "top4_rate", "top_4_rate", "top4", "win_rate", "winrate",
    "win_pct", "avg_placement", "average_placement", "avg_place",
    "play_rate", "playrate", "pick_rate", "pickrate", "games_played",
    "sample_size",
})
# The scrubbed-descriptor shape the 2026-09-07 pass left in place of real
# names: a category noun then ONE capital letter ("aggregator C").
DESCRIPTOR_RE = re.compile(
    r"\b(?i:aggregator|guide site|guide author|guide|overlay app|overlay|"
    r"draft tool|stats site|tool|site|app|platform|tracker)\s+[A-Z]\b")
HOST_RE = re.compile(
    r"\b((?:[a-z0-9-]+\.)+(?:gg|com|net|org|io|lol|app|co|kr|cn|tv|me|xyz))\b",
    re.IGNORECASE)

# Tracked data/meta/tft_set*.json files with no provenance slot, each with
# the reason. A stale entry (file no longer tracked) fails
# test_exemptions_are_live_and_carry_no_fields.
EXEMPT = {
    "tft_set17_champion_codes.json": (
        "flat champion name -> team-planner code map read from the local "
        "League client (scripts/discover_champion_codes.py); no prose, no "
        "provenance slot, values must stay plain ints"),
}

# Sections that hold coaching opinion (comps, tier list, augment ratings,
# Double Up advice). RC-authored skeletons keep them EMPTY until filled from
# operator-measured play.
OPINION_SECTIONS = ("comps", "tier_list", "trait_augments", "double_up")


# -- the checker ------------------------------------------------------------------

def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _names_party(text: str, *, stats_only: bool = False) -> bool:
    low = text.lower()
    return any(
        alias in low
        for party in CREDITED.values()
        if party["stats"] or not stats_only
        for alias in party["aliases"]
    )


def _names_rc_own(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in RC_OWN)


def _host_credited(host: str) -> bool:
    host = host.lower()
    return any(host == h or host.endswith("." + h) for h in CREDITED_HOSTS)


def _string_problems(text: str) -> list[str]:
    problems = []
    if not (_names_party(text) or _names_rc_own(text)):
        problems.append(f"names no NOTICE-credited source: {text[:80]!r}")
    for m in DESCRIPTOR_RE.finditer(text):
        problems.append(f"names an uncredited third party ({m.group(0)!r})")
    for m in HOST_RE.finditer(text):
        if not _host_credited(m.group(1)):
            problems.append(f"names an uncredited host ({m.group(1)!r})")
    return problems


def provenance_violations(doc, name: str = "<doc>") -> list[str]:
    """Every rule-1..3 violation in one parsed meta document."""
    if not isinstance(doc, dict):
        return [f"{name}: not a JSON object"]
    out = []
    top = doc.get("_source")
    if not (isinstance(top, str) and top.strip()):
        out.append(f"{name}: no top-level _source (rule 1)")

    def walk(node, path, chain):
        if isinstance(node, dict):
            here = [s for k in sorted(PROVENANCE_KEYS & set(node))
                    for s in _strings(node[k])]
            for s in here:
                out.extend(f"{name}{path or '/'}: {p}" for p in _string_problems(s))
            chain = chain + here
            for key, value in node.items():
                if key in STAT_KEYS and not any(
                        _names_party(s, stats_only=True) for s in chain):
                    out.append(
                        f"{name}{path}/{key}: ladder statistic with no "
                        "NOTICE-credited source able to produce it (rule 3)")
                walk(value, f"{path}/{key}", chain)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]", chain)

    walk(doc, "", [])
    return out


# -- the enumeration -------------------------------------------------------------

def _tracked_tft_meta() -> list[Path]:
    """Tracked data/meta/tft_set*.json, straight from the git index."""
    return [
        p for p in _repo_walk.repo_files(META_DIR, ("tft_set*.json",))
        if p.parent == META_DIR
    ]


def _guarded() -> list[Path]:
    return [p for p in _tracked_tft_meta() if p.name not in EXEMPT]


def test_enumeration_is_anchored():
    """An empty walk must fail, not pass: the guard has to be guarding the
    files the TFT lane actually reads."""
    names = {p.name for p in _guarded()}
    assert {"tft_set17_meta.json", "tft_set18_meta.json",
            "tft_set18_cdragon.json"} <= names, sorted(names)
    # Every tracked file tft/tft_set.py can resolve is covered.
    resolvable = {
        p.name for p in _tracked_tft_meta()
        if re.match(r"^tft_set\d{1,3}_(?:pbe_)?(?:meta|cdragon)\.json$", p.name)
    }
    assert resolvable and resolvable <= names


def test_exemptions_are_live_and_carry_no_fields():
    tracked = {p.name: p for p in _tracked_tft_meta()}
    for name, why in EXEMPT.items():
        assert name in tracked, f"stale exemption {name} ({why})"
        doc = json.loads(tracked[name].read_text(encoding="utf-8"))
        assert isinstance(doc, dict) and doc
        assert all(isinstance(k, str) and type(v) is int for k, v in doc.items()), (
            f"{name} is exempt only while it is a flat name -> int map")


@pytest.mark.parametrize("path", _guarded(), ids=lambda p: p.name)
def test_tracked_tft_meta_names_only_credited_sources(path: Path):
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    problems = provenance_violations(doc, path.name)
    assert not problems, (
        f"{len(problems)} provenance problem(s) in data/meta/{path.name} - "
        "third-party TFT content needs a NOTICE entry and a CREDITED row, or "
        "it stays out of this public repo (RM-846):\n  "
        + "\n  ".join(problems[:25]))


def test_notice_credits_every_credited_party_and_has_a_tft_entry():
    text = NOTICE.read_text(encoding="utf-8")
    for label, party in CREDITED.items():
        assert party["notice"] in text, f"NOTICE does not credit {label}"
    assert "data/meta/tft_set" in text, "NOTICE has no TFT meta entry"


# -- the checker is proven to fire --------------------------------------------------

def test_checker_fires_on_the_removed_payload_shape():
    """The shape RM-846 removed, rebuilt from its own provenance fields."""
    legacy = {
        "_source": "aggregator C Apr 9 2026 + TFT guide author X + TFT guide site W",
        "_bm_source": "TFT guide author X/meta/ patch 17.1",
        "comps": {"Some Comp": {
            "source": "aggregator C", "display_source": "moba",
            "top4_pct": 64, "avg_placement": 3.5, "play_rate": 10}},
    }
    problems = provenance_violations(legacy, "legacy")
    blob = "\n".join(problems)
    assert "'aggregator C'" in blob
    assert "'guide author X'" in blob
    assert "'guide site W'" in blob
    assert "names no NOTICE-credited source: 'moba'" in blob
    for stat in ("top4_pct", "avg_placement", "play_rate"):
        assert f"/{stat}: ladder statistic" in blob, stat


@pytest.mark.parametrize("doc,needle", [
    ({"comps": {}}, "no top-level _source"),
    ({"_source": "RC-authored, numbers from example-tft.gg"}, "uncredited host"),
    ({"_source": "CommunityDragon extract", "comps": {"A": {"top4_pct": 60}}},
     "ladder statistic"),
    ({"_source": "RC-authored", "comps": {"A": {"source": "Overlay App E"}}},
     "uncredited third party"),
])
def test_checker_fires_on_each_rule(doc, needle):
    assert any(needle in p for p in provenance_violations(doc)), needle


@pytest.mark.parametrize("doc", [
    {"_source": "RC-authored skeleton (RM-840). Game data lives in "
                "tft_set18_cdragon.json (CommunityDragon).", "comps": {}},
    {"_source": "CommunityDragon cdragon/tft/en_us.json",
     "_source_url": "https://raw.communitydragon.org/latest/cdragon/tft/en_us.json"},
    {"_source": "RC-measured from Riot API / Match-V5 matches",
     "comps": {"A": {"top4_pct": 60}}},
])
def test_checker_passes_credited_shapes(doc):
    assert provenance_violations(doc) == []


# -- consumers keep working on the game-data-only Set 17 file -------------------

@pytest.fixture
def _no_live_set_or_pin(monkeypatch):
    monkeypatch.delenv(tft_set.ENV_PIN, raising=False)
    tft_set.clear_live_set()
    yield
    tft_set.clear_live_set()


def test_committed_set17_meta_is_a_game_data_skeleton():
    meta = tft_set.load_meta(17, root=REPO_ROOT)
    assert meta["_set"] == 17
    for key in OPINION_SECTIONS:
        assert meta[key] == {}, key
    assert "unverified" in meta["_note"].lower()
    for gone in ("leveling", "_bm_source"):
        assert gone not in meta, gone


def test_set17_roster_survives_as_game_data():
    meta = tft_set.load_meta(17, root=REPO_ROOT)
    roster = tft_set.roster(17, root=REPO_ROOT)
    assert len(roster) >= 60
    assert roster == meta["champions_set17"]
    assert set(meta["unit_costs"]) == set(roster) == set(meta["unit_traits"])
    assert tft_set.trait_names(17, root=REPO_ROOT) == meta["all_traits"]
    assert len(meta["all_traits"]) >= 30


def test_set17_pbe_flag_reads_set17_own_file():
    """No Set 17 PBE twin: the pbe flag reads Set 17's own file, never
    another set's."""
    assert tft_set.meta_path(17, pbe=True, root=REPO_ROOT).name == "tft_set17_meta.json"


def test_a_removed_set_degrades_to_empty_never_to_another_set():
    assert tft_set.meta_path(16, root=REPO_ROOT).name == "tft_set16_meta.json"
    assert tft_set.load_meta(16, root=REPO_ROOT) == {}
    assert tft_set.load_meta(16, pbe=True, root=REPO_ROOT) == {}


def test_coach_engine_on_set17_skeleton_degrades_quietly(monkeypatch, _no_live_set_or_pin):
    from tft import tft_coach_engine as eng

    monkeypatch.setattr(eng, "_META_SECTION_CACHE", {})
    monkeypatch.setattr(tft_set, "ROOT", REPO_ROOT)
    monkeypatch.setattr(tft_set, "comp_state",
                        lambda root=None: {"selected": "N.O.V.A."})
    tft_set.note_live_set(17)
    assert eng._load_trait_augment_data() == {}
    assert eng._load_double_up_rules() == {}
    prompt = eng._build_prompt({"level": 4})
    assert "SELECTED COMP" not in prompt
    assert "Roll odds at Lv4" in prompt
