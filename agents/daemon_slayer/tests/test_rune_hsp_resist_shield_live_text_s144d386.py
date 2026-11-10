"""S144-D-386..388: the rune HSP, resist and shield registries match the live text they cite.

Measured at patch 16.22.1 (ENGINE 1.291.0) against the vendored DDragon
``runesReforged.json`` snapshots under ``data/meta_build/ddragon/``.

- S144-D-386 ``_rune_hsp_amp``: the Revitalize quote is live, and the "every
  other Resolve rune ... read and rejected" list now names all 12 live Resolve
  runes (it skipped 8437 Grasp of the Undying, 8401 Shield Bash and 8444 Second
  Wind).
- S144-D-387 ``_rune_resist_grants``: the Aftershock / Conditioning / Unflinching
  quotes are live, the "other Resolve runes ... read and rejected" list names
  all 12 (same three were skipped), and Bone Plating names the
  ``_rune_flat_mitigation`` lane that registers 8473.
- S144-D-388 ``_rune_shield_grants``: the Guardian quote is live; the "every
  other current-patch Resolve rune" comment block names 8401 Shield Bash (it
  had 10 of the 11); 8444 Second Wind is no longer "being built in a PARALLEL
  SLICE" - ``_rune_self_heal`` registers it; the Font of Life ``@BaseHeal@``
  claim is no longer "ALL FOUR vendored snapshots"; the old "All 27 'ap'
  substring hits" count is replaced by the identifier set this test
  re-derives from ``ehp.py``; and the GUARD 2 test path resolves.

Each "unchanged across a vendored range" sentence in the three docstrings is
checked as a claim: every vendored snapshot inside the named range carries the
same longDesc as the current patch. A future patch that changes a quoted
longDesc fails the quote check, not a hand-typed date.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import _rune_hsp_amp, _rune_resist_grants, _rune_shield_grants
from agents.daemon_slayer._rune_flat_mitigation import _RUNE_FLAT_MITIGATION
from agents.daemon_slayer._rune_health_grants import _RUNE_HEALTH_GRANTS
from agents.daemon_slayer._rune_self_heal import _RUNE_SELF_HEAL
from agents.daemon_slayer.rune_procs import COMPLETION_RUNE_IDS

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DS_DIR = _REPO_ROOT / "agents" / "daemon_slayer"
_CURRENT_TXT = _REPO_ROOT / "data" / "daemon_slayer" / "current.txt"
_DDRAGON_ROOT = _REPO_ROOT / "data" / "meta_build" / "ddragon"

_RANGE_RE = re.compile(
    r"identical in every vendored snapshot (\d+\.\d+\.\d+)\.\.(\d+\.\d+\.\d+)"
)


def _ver(patch: str) -> tuple[int, ...]:
    return tuple(int(p) for p in patch.split("."))


def _squash(text: str) -> str:
    return "".join(text.split())


def _spaced(text: str) -> str:
    return " ".join(text.split())


def _load_runes(patch_dir: Path) -> dict[int, tuple[str, str, str]]:
    """rune id -> (tree name, rune name, longDesc)."""
    trees = json.loads((patch_dir / "runesReforged.json").read_text(encoding="utf-8"))
    out: dict[int, tuple[str, str, str]] = {}
    for tree in trees:
        for slot in tree["slots"]:
            for rune in slot["runes"]:
                out[int(rune["id"])] = (tree["name"], rune["name"], rune["longDesc"])
    return out


def _vendored() -> dict[str, dict[int, tuple[str, str, str]]]:
    out: dict[str, dict[int, tuple[str, str, str]]] = {}
    for child in sorted(_DDRAGON_ROOT.iterdir()):
        if child.is_dir() and (child / "runesReforged.json").exists():
            out[child.name] = _load_runes(child)
    return out


@pytest.fixture(scope="module")
def vendored() -> dict[str, dict[int, tuple[str, str, str]]]:
    if not _DDRAGON_ROOT.is_dir():
        pytest.skip("no vendored DDragon snapshots")
    return _vendored()


@pytest.fixture(scope="module")
def live(vendored) -> dict[int, tuple[str, str, str]]:
    if not _CURRENT_TXT.exists():
        pytest.skip("no data/daemon_slayer/current.txt")
    patch = _CURRENT_TXT.read_text(encoding="utf-8").strip()
    if patch not in vendored:
        pytest.skip(f"no vendored runesReforged.json for {patch}")
    return vendored[patch]


def _source(module) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


def _shield_allowlist_block() -> str:
    src = _source(_rune_shield_grants)
    start = src.index("# DELIBERATE ONE-ID ALLOWLIST")
    end = src.index("__all__", start)
    return src[start:end]


# ---- checkers (pure, so planted defects can exercise them) -------------------


def missing_rune_mentions(
    text: str, live: dict[int, tuple[str, str, str]], tree: str, skip: set[int]
) -> list[str]:
    """Live ``tree`` runes the text does not name as "<id> <live name>"."""
    flat = _spaced(text)
    return sorted(
        f"{rid} {name}"
        for rid, (tree_name, name, _desc) in live.items()
        if tree_name == tree and rid not in skip and f"{rid} {name}" not in flat
    )


def unquoted_longdescs(
    text: str, live: dict[int, tuple[str, str, str]], ids: tuple[int, ...]
) -> list[int]:
    """Ids whose live longDesc is not quoted verbatim (whitespace-insensitive)."""
    flat = _squash(text)
    return [rid for rid in ids if _squash(live[rid][2]) not in flat]


def false_range_claims(
    text: str,
    vendored: dict[str, dict[int, tuple[str, str, str]]],
    ids: tuple[int, ...],
) -> list[str]:
    """Problems with every "identical in every vendored snapshot A..B" claim."""
    claims = _RANGE_RE.findall(_spaced(text))
    if not claims:
        return ["no 'identical in every vendored snapshot A..B' claim"]
    problems: list[str] = []
    for low, high in claims:
        for end in (low, high):
            if end not in vendored:
                problems.append(f"{end} is not a vendored snapshot")
        inside = [p for p in vendored if _ver(low) <= _ver(p) <= _ver(high)]
        for rid in ids:
            texts = {vendored[p][rid][2] for p in inside if rid in vendored[p]}
            missing = [p for p in inside if rid not in vendored[p]]
            if missing or len(texts) != 1:
                problems.append(f"{rid} differs or is absent inside {low}..{high}")
    return problems


def _ap_identifiers(src: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", src)
        if "ap" in word.split("_")
    }


# ---- S144-D-386: _rune_hsp_amp ----------------------------------------------


def test_hsp_revitalize_quote_is_live(live, vendored) -> None:
    doc = _rune_hsp_amp.__doc__ or ""
    assert unquoted_longdescs(doc, live, (8453,)) == []
    assert false_range_claims(doc, vendored, (8453,)) == []
    assert "DDragon 16.14.1" not in doc


def test_hsp_rejection_list_names_every_live_resolve_rune(live) -> None:
    doc = _rune_hsp_amp.__doc__ or ""
    assert missing_rune_mentions(doc, live, "Resolve", set()) == []


def test_hsp_rejected_glacial_augment_is_the_only_other_live_hsp_mention(live) -> None:
    mentions = sorted(
        rid for rid, (_t, _n, desc) in live.items() if "Heal and Shield Power" in desc
    )
    assert mentions == [8351, 8453]
    assert len(live) == 62
    doc = _spaced(_rune_hsp_amp.__doc__ or "")
    assert "all 62 current-patch runes" in doc
    assert "8351 Glacial Augment" in doc


# ---- S144-D-387: _rune_resist_grants ----------------------------------------


def test_resist_quotes_are_live(live, vendored) -> None:
    doc = _rune_resist_grants.__doc__ or ""
    ids = (8439, 8429, 8242)
    assert unquoted_longdescs(doc, live, ids) == []
    assert false_range_claims(doc, vendored, ids) == []
    assert "DDragon 16.14.1" not in doc


def test_resist_rejection_list_names_every_live_resolve_rune(live) -> None:
    doc = _rune_resist_grants.__doc__ or ""
    assert missing_rune_mentions(doc, live, "Resolve", set()) == []


def test_resist_only_seeded_runes_mention_armor_or_magic_resist(live) -> None:
    grants = sorted(
        rid
        for rid, (_t, _n, desc) in live.items()
        if "Armor" in desc or "Magic Resist" in desc
    )
    assert grants == sorted(int(k) for k in _rune_resist_grants._RUNE_RESIST_GRANTS)


def test_resist_bone_plating_names_its_live_lane() -> None:
    doc = _spaced(_rune_resist_grants.__doc__ or "")
    assert "8473" in _RUNE_FLAT_MITIGATION
    assert "``_rune_flat_mitigation``" in doc
    assert "is the ``_passive_mitigation_overrides`` lane" not in doc


def test_resist_unflinching_comment_is_not_dated_to_one_patch(live, vendored) -> None:
    src = _source(_rune_resist_grants)
    assert "absent from this longDesc in 16.14.1" not in src
    assert "tenacity" not in live[8242][2].lower()
    assert "slow" not in live[8242][2].lower()


def test_resist_rune_procs_still_says_resist_side_not_modeled() -> None:
    assert "(resist-bonus side not modeled)" in (_DS_DIR / "rune_procs.py").read_text(
        encoding="utf-8"
    )


# ---- S144-D-388: _rune_shield_grants ----------------------------------------


def test_shield_guardian_quote_is_live(live, vendored) -> None:
    doc = _rune_shield_grants.__doc__ or ""
    assert unquoted_longdescs(doc, live, (8465,)) == []
    assert false_range_claims(doc, vendored, (8465,)) == []
    src = _source(_rune_shield_grants)
    assert "DDragon 16.14.1" not in src


def test_shield_allowlist_block_names_every_other_live_resolve_rune(live) -> None:
    block = _shield_allowlist_block()
    assert missing_rune_mentions(block, live, "Resolve", {8465}) == []


def test_shield_allowlist_block_owner_lanes_are_live() -> None:
    block = _spaced(_shield_allowlist_block())
    assert "PARALLEL SLICE" not in block
    assert "8444" in _RUNE_SELF_HEAL
    assert "_rune_self_heal" in block[block.index("8444 Second Wind") :]
    assert "8437" in _RUNE_HEALTH_GRANTS and "8451" in _RUNE_HEALTH_GRANTS
    assert "8473" in _RUNE_FLAT_MITIGATION
    assert 8401 in COMPLETION_RUNE_IDS
    assert "rune_procs.py" in block[block.index("8401 Shield Bash") :]


def test_shield_font_of_life_template_claim_spans_every_snapshot(vendored) -> None:
    src = _source(_rune_shield_grants)
    assert "ALL FOUR vendored snapshots" not in src
    for patch, runes in vendored.items():
        assert "@BaseHeal@" in runes[8463][2], patch
    block = _spaced(_shield_allowlist_block())
    font = block[block.index("8463 Font of Life") : block.index("8444 Second Wind")]
    assert "in every vendored snapshot" in font


def test_shield_ap_claim_matches_ehp_identifiers() -> None:
    ehp_src = (_DS_DIR / "ehp.py").read_text(encoding="utf-8")
    assert not re.search(
        r"ability_power|abilitypower|total_ap|bonus_ap|ap_flat", ehp_src
    )
    assert _ap_identifiers(ehp_src) <= {
        "ap",
        "ap_share",
        "enemy_ap_share",
        "ap_ad_coherence",
    }
    doc = _spaced(_rune_shield_grants.__doc__ or "")
    assert 'All 27 "ap" substring hits' not in doc
    for name in ("enemy_ap_share", "ap_share", "ap_ad_coherence"):
        assert f"``{name}``" in doc


def test_shield_cited_test_paths_resolve() -> None:
    doc = _rune_shield_grants.__doc__ or ""
    cited = re.findall(r"``((?:agents/daemon_slayer/)?tests/[\w/]+\.py)``", doc)
    assert cited
    for rel in cited:
        assert (_REPO_ROOT / rel).exists(), rel


# ---- planted defects ---------------------------------------------------------


_FAKE = {
    1: ("Resolve", "Alpha", "Gain 5 Armor."),
    2: ("Resolve", "Beta Two", "Heal 3."),
    3: ("Domination", "Gamma", "Deal 9."),
}


def test_missing_rune_mentions_catches_an_unnamed_rune() -> None:
    assert missing_rune_mentions("1 Alpha and 2 Beta\n Two", _FAKE, "Resolve", set()) == []
    assert missing_rune_mentions("1 Alpha only", _FAKE, "Resolve", set()) == ["2 Beta Two"]
    assert missing_rune_mentions("1 Alpha only", _FAKE, "Resolve", {2}) == []


def test_unquoted_longdescs_catches_a_drifted_quote() -> None:
    assert unquoted_longdescs('"Gain 5\n   Armor."', _FAKE, (1,)) == []
    assert unquoted_longdescs('"Gain 6 Armor."', _FAKE, (1,)) == [1]


def test_false_range_claims_catches_a_changed_or_unvendored_range() -> None:
    same = {"16.1.1": _FAKE, "16.2.1": _FAKE}
    changed = {"16.1.1": _FAKE, "16.2.1": {**_FAKE, 1: ("Resolve", "Alpha", "Gain 6 Armor.")}}
    claim = "identical in every vendored snapshot 16.1.1..16.2.1"
    assert false_range_claims(claim, same, (1,)) == []
    assert false_range_claims(claim, changed, (1,)) != []
    assert false_range_claims("identical in every vendored snapshot 16.1.1..16.3.1", same, (1,)) != []
    assert false_range_claims("no claim here", same, (1,)) != []


def test_ap_identifiers_catches_a_wielder_ap_token() -> None:
    assert _ap_identifiers("enemy_ap_share = 1") == {"enemy_ap_share"}
    assert "wielder_ap" in _ap_identifiers("wielder_ap = 3")
