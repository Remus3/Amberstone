"""S144-D-279..281 - the DS ability-amp registry's prose cites, bucket coverage and patch labels.

WHY. ``_ability_amp_overrides`` justifies each row with ``ed[N]`` quotes from
the Meraki ``effects_descriptions`` prose, and its docstring said every value
was "verified ... at patch 16.11.1". S144-D-272..277 tied the MAGNITUDES to the
live forms, but nothing tied the PROSE cites, nothing checked that every
``damage_amp_self`` modifier block the taxonomy reports has a disposition, and
the "verified at 16.11.1" labels kept claiming a check nobody re-runs.

* S144-D-279: every ``ed[N]`` cite in a registry row's comment or note names
  an entry that exists on the LIVE form and carries the quoted claim. The
  Jayce W f1 comment said "+360% bonus AS (4x hits in the window)"; the live
  ed[0] says the next 3 basic attacks within 4 seconds gain 360% bonus attack
  speed, so "4x hits" was unsupported. The comment now cites the live count,
  window and AS figure, and they are rebuilt from the live prose here.
* S144-D-280: every live ``damage_amp_self`` modifier block
  (``modifier_blocks.classify_modifier_kind``) has exactly one disposition:
  an ``_ABILITY_AMP_OVERRIDES`` row, the ``_STAGED_AMP_BLOCK_ROUTES`` route,
  the cross-spell SOURCE, the Sion block index, or the module docstring's
  out-of-seam list (Mel R / Yone E). A new or renamed
  block fails until someone dispositions it; a disposition whose block left
  the live data fails too.
* S144-D-281: no sentence in the module claims a value was "verified" at a
  dated patch. Values were authored at 16.11.1 and are now re-checked live,
  so the module names the live guards instead, and every guard it names
  exists on disk.

MEASURED 2026-11-09 (``load_default()`` and the raw snapshot, patch 16.22.1,
Meraki content patch 25.15): 15 ``damage_amp_self`` blocks, 10 inside the
seam and 5 out of it; every ``ed[N]`` cite resolved except the Jayce "4x
hits" wording. S144-D-282 then moved the Mel W replicated-projectile and the
two TahmKench E grey-health blocks to ``other``, leaving 12 blocks, 2 of
them out of the seam. The engine edits are comments and docstring only, so scorer
output is byte-identical.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _ability_amp_overrides as amp_mod
from agents.daemon_slayer._ability_amp_overrides import (
    _ABILITY_AMP_OVERRIDES,
    _CROSS_SPELL_AMP_OVERRIDES,
    _STAGED_AMP_BLOCK_ROUTES,
)
from agents.daemon_slayer.abilities import load_default
from agents.daemon_slayer.modifier_blocks import classify_modifier_kind

Key = tuple[str, str, int]

PKG = Path(amp_mod.__file__).resolve().parent
REPO = PKG.parents[1]
DS_DATA = REPO / "data" / "daemon_slayer"
BLOCK_INDEX_JSON = PKG / "champion_block_index.json"


@pytest.fixture(scope="module")
def ab() -> Any:
    return load_default()


@pytest.fixture(scope="module")
def raw() -> dict:
    patch = (DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
    path = DS_DATA / patch / "champion_abilities.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


@pytest.fixture(scope="module")
def amp_src() -> str:
    return Path(amp_mod.__file__).read_text(encoding="utf-8")


def _live_eds(raw: dict, key: Key) -> list[str]:
    cid, slot, fi = key
    forms = raw.get(cid, {}).get(slot) or []
    for form in forms:
        if form.get("form_index") == fi:
            return list(form.get("effects_descriptions") or [])
    return []


# --------------------------------------------------------------- S144-D-279

# Row -> {cited ed index: phrases the LIVE ed[N] must contain}. Every cited
# index of every row must be named here, so a new cite fails until its claim
# is written down.
ED_CLAIMS: dict[Key, dict[int, tuple[str, ...]]] = {
    ("Illaoi", "Q", 0): {0: ("Passive:", "Tentacle damage is increased")},
    ("Mordekaiser", "Q", 0): {0: ("increased if only one enemy is hit",)},
    ("Caitlyn", "W", 0): {2: ("springs the trap", "Headshot")},
    ("Fiora", "E", 0): {
        0: ("next two basic attacks",),
        1: ("cannot critically strike", "critically strike for modified critical damage"),
    },
    ("Jayce", "W", 1): {0: ("modified physical damage", "bonus attack speed")},
    ("Sivir", "W", 0): {
        0: ("bonus attack speed", "bounce to additional surrounding enemies"),
        1: ("Bounces",),
    },
}

_ED_RE = re.compile(r"\bed\[(\d+)\]")


def _row_text(src: str, key: Key) -> str:
    """The comment block above a registry row plus the row body up to its close."""
    lines = src.splitlines()
    head = f'("{key[0]}", "{key[1]}", {key[2]}): '
    starts = [i for i, ln in enumerate(lines) if ln.strip().startswith(head)]
    assert len(starts) == 1, (key, starts)
    i = starts[0]
    j = i - 1
    while j >= 0 and lines[j].strip().startswith("#"):
        j -= 1
    k = i
    while k < len(lines) and lines[k].strip() != "),":
        k += 1
    return "\n".join(lines[j + 1 : k + 1])


def _registry_rows() -> list[Key]:
    return sorted(set(_ABILITY_AMP_OVERRIDES) | set(_CROSS_SPELL_AMP_OVERRIDES))


def check_ed_cites(raw: dict, src: str, claims: dict[Key, dict[int, tuple[str, ...]]]) -> list[str]:
    out: list[str] = []
    cited_rows: set[Key] = set()
    for key in _registry_rows():
        cited = {int(n) for n in _ED_RE.findall(_row_text(src, key))}
        if not cited:
            continue
        cited_rows.add(key)
        want = claims.get(key, {})
        if cited != set(want):
            out.append(f"{key}: cites ed{sorted(cited)}, claims table names ed{sorted(want)}")
        eds = _live_eds(raw, key)
        for n in sorted(cited):
            if n >= len(eds):
                out.append(f"{key}: cites ed[{n}], live form has {len(eds)} entries")
                continue
            for phrase in want.get(n, ()):
                if phrase not in eds[n]:
                    out.append(f"{key}: live ed[{n}] lacks {phrase!r}")
    for key in sorted(set(claims) - cited_rows):
        out.append(f"{key}: claims table names a row whose text cites no ed[N]")
    return out


def check_jayce_window(raw: dict, src: str) -> list[str]:
    """The Jayce W f1 comment cites the live AA count, window and AS figure."""
    ed0 = _live_eds(raw, ("Jayce", "W", 1))[0]
    m_n = re.search(r"next (\d+) basic attacks within (\d+) seconds", ed0)
    m_as = re.search(r"(\d+)% bonus attack speed", ed0)
    if not (m_n and m_as):
        return [f"live Jayce W f1 ed[0] no longer states the count / window / AS: {ed0!r}"]
    text = _row_text(src, ("Jayce", "W", 1))
    flat = " ".join(ln.strip().lstrip("#").strip() for ln in text.splitlines())
    out = []
    for want in (
        f"next {m_n.group(1)} AAs within {m_n.group(2)} s",
        f"+{m_as.group(1)}% bonus AS",
    ):
        if want not in flat:
            out.append(f"Jayce W f1 comment lacks the live {want!r}")
    if "4x hits" in flat:
        out.append("Jayce W f1 comment still claims '4x hits', which the live prose does not state")
    return out


def test_every_ed_cite_resolves_to_its_live_claim(raw: dict, amp_src: str) -> None:
    assert check_ed_cites(raw, amp_src, ED_CLAIMS) == []


def test_jayce_comment_cites_the_live_window(raw: dict, amp_src: str) -> None:
    assert check_jayce_window(raw, amp_src) == []


@pytest.mark.parametrize(
    ("old", "new", "needle"),
    [
        ('Tentacle Smash: ed[0] "Passive', 'Tentacle Smash: ed[1] "Passive', "claims table names"),
        ("springs the trap (ed[2])", "springs the trap (ed[7])", "cites ed[7], live form has"),
        ("ed[0]/ed[1] empower", "ed[0]/ed[1]/ed[2] empower", "claims table names"),
    ],
)
def test_ed_check_catches_planted_cites(raw: dict, amp_src: str, old: str, new: str, needle: str) -> None:
    assert old in amp_src
    errs = check_ed_cites(raw, amp_src.replace(old, new, 1), ED_CLAIMS)
    assert any(needle in e for e in errs), errs


def test_ed_check_catches_a_phrase_missing_from_live_prose(raw: dict, amp_src: str) -> None:
    claims = dict(ED_CLAIMS)
    claims[("Mordekaiser", "Q", 0)] = {0: ("increased if two enemies are hit",)}
    errs = check_ed_cites(raw, amp_src, claims)
    assert any("Mordekaiser" in e and "lacks" in e for e in errs), errs


def test_jayce_check_catches_planted_wording(raw: dict, amp_src: str) -> None:
    text = _row_text(amp_src, ("Jayce", "W", 1))
    planted = text.replace("next 3 AAs within 4 s", "next 3 AAs (4x hits in the window)", 1)
    assert planted != text
    errs = check_jayce_window(raw, amp_src.replace(text, planted, 1))
    assert any("next 3 AAs within 4 s" in e for e in errs), errs
    assert any("4x hits" in e for e in errs), errs


# --------------------------------------------------------------- S144-D-280

Block = tuple[str, str, int, str]

# Every live damage_amp_self block -> how the seam handles it. "out" rows are
# outside the seam and must be named in the module docstring's out-of-seam list.
DISPOSITION: dict[Block, str] = {
    ("AurelionSol", "W", 0, "Breath of Light Flat Damage Modifier"): "cross_source",
    ("Caitlyn", "W", 0, "Headshot Damage Increase"): "amp",
    ("Fiora", "E", 0, "Critical damage"): "amp",
    ("Hwei", "Q", 2, "Maximum Damage Increase"): "route",
    ("Illaoi", "Q", 0, "Damage Increase"): "amp",
    ("Jayce", "W", 1, "Damage Modifier"): "amp",
    ("Mordekaiser", "Q", 0, "Damage Increase"): "amp",
    ("Nidalee", "Q", 1, "Increased Damage Modifier"): "amp",
    ("Sion", "Q", 0, "Maximum Base Damage Increase"): "block_index",
    ("Sivir", "W", 0, "Bounce Critical Damage"): "amp",
    ("Mel", "R", 0, "Stored Damage Increase per Stack"): "out",
    ("Yone", "E", 0, "Damage Stored"): "out",
}


def _live_amp_self_blocks(ab: Any) -> set[Block]:
    out: set[Block] = set()
    for cid, key, form in ab.iter_forms():
        for b in form.damage_blocks:
            if b.attribute_kind == "modifier" and classify_modifier_kind(b.attribute) == "damage_amp_self":
                out.add((cid, key, form.form_index, b.attribute))
    return out


def _out_of_seam_section(src: str) -> str:
    start = src.find("Out of seam")
    if start < 0:
        return ""
    end = src.find("\n\n", start)
    return " ".join(src[start : end if end > 0 else len(src)].split())


def check_disposition(live: set[Block], disposition: dict[Block, str], src: str, block_index: dict) -> list[str]:
    out: list[str] = []
    for blk in sorted(live - set(disposition)):
        out.append(f"live damage_amp_self block {blk} has no disposition")
    for blk in sorted(set(disposition) - live):
        out.append(f"disposition {blk} names a block absent from the live data")
    cross_sources = {(cid, e.source_key, 0) for (cid, _k, _f), e in _CROSS_SPELL_AMP_OVERRIDES.items()}
    section = _out_of_seam_section(src)
    for blk, how in sorted(disposition.items()):
        key = blk[:3]
        ok = {
            "amp": key in _ABILITY_AMP_OVERRIDES,
            "route": key in _STAGED_AMP_BLOCK_ROUTES,
            "cross_source": key in cross_sources,
            "block_index": isinstance(block_index.get(blk[0], {}).get(blk[1]), int),
            "out": f"{blk[0]} {blk[1]}" in section and blk[3] in section,
        }.get(how)
        if not ok:
            out.append(f"{blk}: disposition {how!r} not backed by the module")
    return out


def _block_index() -> dict:
    return json.loads(BLOCK_INDEX_JSON.read_text(encoding="utf-8"))["champions"]


def test_every_live_damage_amp_self_block_has_one_disposition(ab: Any, amp_src: str) -> None:
    assert check_disposition(_live_amp_self_blocks(ab), DISPOSITION, amp_src, _block_index()) == []


def test_disposition_check_catches_planted_defects(ab: Any, amp_src: str) -> None:
    live = _live_amp_self_blocks(ab)
    bi = _block_index()
    extra = set(live) | {("Zed", "E", 0, "Damage Increase")}
    assert any("Zed" in e and "no disposition" in e for e in check_disposition(extra, DISPOSITION, amp_src, bi))
    gone = dict(DISPOSITION)
    gone[("Zed", "E", 0, "Damage Increase")] = "amp"
    errs = check_disposition(live, gone, amp_src, bi)
    assert any("absent from the live data" in e for e in errs), errs
    assert any("Zed" in e and "not backed" in e for e in errs), errs
    wrong = dict(DISPOSITION)
    wrong[("Mel", "R", 0, "Stored Damage Increase per Stack")] = "amp"
    errs = check_disposition(live, wrong, amp_src, bi)
    assert any("Mel" in e and "not backed" in e for e in errs), errs
    assert 'Yone E "Damage Stored"' in amp_src
    unlisted = amp_src.replace('Yone E "Damage Stored"', 'Yone Q "Damage Stored"', 1)
    errs = check_disposition(live, DISPOSITION, unlisted, bi)
    assert any("Yone" in e and "not backed" in e for e in errs), errs


def test_out_of_seam_reasons_match_the_live_forms(ab: Any) -> None:
    """Pin the docstring's out-of-seam reasons against the live forms.

    Mel R already carries the stored-damage block; Yone E carries no damage
    block an amp could scale.
    """
    forms = {(c, k, f.form_index): f for c, k, f in ab.iter_forms()}

    def dmg(key: Key) -> list[str]:
        return [b.attribute for b in forms[key].damage_blocks if b.attribute_kind == "damage"]

    assert "Increased Stored Damage" in dmg(("Mel", "R", 0))
    assert dmg(("Yone", "E", 0)) == []


# --------------------------------------------------------------- S144-D-281

_PATCH_RE = re.compile(r"\b\d+\.\d+\.\d+\b")
_GUARD_RE = re.compile(r"\btest_[a-z0-9_]+\.py\b")


def _sentences(src: str) -> list[str]:
    flat = " ".join(ln.strip().lstrip("#").strip() for ln in src.splitlines())
    return [s for s in re.split(r"(?<=[.;])\s+", flat) if s]


def check_patch_labels(src: str) -> list[str]:
    out = []
    for s in _sentences(src):
        if "erified" in s and _PATCH_RE.search(s):
            out.append(f"sentence claims a dated-patch verification: {s[:120]!r}")
    named = set(_GUARD_RE.findall(src))
    if not named:
        out.append("module names no live guard")
    for name in sorted(named):
        if not (PKG / "tests" / name).is_file():
            out.append(f"module names a guard that does not exist: {name}")
    return out


def test_no_dated_patch_verification_claim_and_named_guards_exist(amp_src: str) -> None:
    assert check_patch_labels(amp_src) == []


def test_patch_label_check_catches_planted_defects(amp_src: str) -> None:
    planted = amp_src + "\n# Verified 2026-05-31 against raw_modifiers at 16.11.1.\n"
    assert any("dated-patch" in e for e in check_patch_labels(planted))
    planted = amp_src + "\n# See test_no_such_guard_s144d999.py.\n"
    assert any("does not exist" in e for e in check_patch_labels(planted))
