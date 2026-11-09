"""S144-D-272..274 - the DS ability-amp registries match the live forms they cite.

WHY. ``_ability_amp_overrides`` hand-authors every amp magnitude and every
block route from Meraki ``raw_modifiers`` and block labels "verified ... at
patch 16.11.1". Existing tests pin the literals (item 239 / 246 / 257) and the
registry-wide shape (S144-D-266..268), but nothing compares a literal with the
live form it was copied from, so a patch that moves a modifier, renames a block
or adds the damage block a forward-marker waits for changes the real value
while every guard stays green.

* S144-D-272: the Hwei Q form-2 staged route (``_STAGED_AMP_BLOCK_ROUTES``)
  selects the live "Maximum Damage" block, the default "first" strategy
  selects "Magic Damage", and the identity the route comment relies on holds
  per rank for base AND AP ratio: Maximum Damage == Magic Damage x the
  "Maximum Damage Increase" modifier % (that is why no separate missing-HP
  coefficient is modelled). The routed form carries no
  ``_ABILITY_AMP_OVERRIDES`` row (route plus amp would double-model). The
  registry comment said "out-of-range clamps to the last" as if the clamp were
  authored semantics; since F2 the clamp is a logged defect signal and the
  registry is guarded in range, so the comment is corrected and pinned.
* S144-D-273: every non-zero ``base="ability"`` row and every cross-spell row
  equals its live modifier block, per rank: an "increase" modifier (Illaoi Q,
  Mordekaiser Q "Damage Increase" 10:30 / 30:50 %) is the addend x 100; a
  "multiplier" modifier (AurelionSol W "Breath of Light Flat Damage Modifier"
  108:112 %) is (1 + addend) x 100. Every such row must have an expectation
  here, so a new row fails until its source is named.
* S144-D-274: the docstring's live-shape claims. Illaoi Q f0 holds NO damage
  block (the always_on amp is LIVE-INERT; the day a damage block appears the
  amp goes live and this fails so someone re-checks it); every other
  ``base="ability"`` row sits on a form with exactly the damage block it
  scales and no second damage block naming the amplified case; the
  cross-spell SOURCE form has no damage block and the TARGET form has no
  ``_ABILITY_AMP_OVERRIDES`` row (the module's no-double-count claim).

MEASURED 2026-11-09 (``load_default()``, patch 16.22.1): Hwei Q f2 blocks
"Magic Damage" 60:160 + 25 AP, modifier "Maximum Damage Increase" 200:350 %,
"Maximum Damage" 120:560 + 50:87.5 AP; Illaoi Q f0 modifier only; Mordekaiser
Q f0 one damage block "Magic Damage"; AurelionSol W f0 modifier only. Every
literal matched. A guard plus a comment fix; no registry value changes, so the
scorer output is byte-identical.
"""

from __future__ import annotations

import dataclasses
import inspect
import math
from typing import Any

import pytest

from agents.daemon_slayer import _ability_amp_overrides as amp_mod
from agents.daemon_slayer._ability_amp_overrides import (
    _ABILITY_AMP_OVERRIDES,
    _CROSS_SPELL_AMP_OVERRIDES,
    _STAGED_AMP_BLOCK_ROUTES,
)
from agents.daemon_slayer.abilities import load_default

Key = tuple[str, str, int]

# (target key) -> (source slot, modifier label, convention).
# "increase": raw % == addend * 100. "multiplier": raw % == (1 + addend) * 100.
MAGNITUDE_SOURCES: dict[Key, tuple[str, str, str]] = {
    ("Illaoi", "Q", 0): ("Q", "Damage Increase", "increase"),
    ("Mordekaiser", "Q", 0): ("Q", "Damage Increase", "increase"),
    ("AurelionSol", "Q", 0): ("W", "Breath of Light Flat Damage Modifier", "multiplier"),
}

# base="ability" rows whose live form holds no damage block (documented LIVE-INERT).
LIVE_INERT_ABILITY_ROWS: frozenset[Key] = frozenset({("Illaoi", "Q", 0)})

HWEI_ROUTE: Key = ("Hwei", "Q", 2)


@pytest.fixture(scope="module")
def ab() -> Any:
    return load_default()


def _form(ab: Any, champ: str, slot: str, form_index: int) -> Any:
    assert ab.has_champion(champ), champ
    forms = ab.get_abilities(champ).get(slot) or ()
    assert 0 <= form_index < len(forms), (champ, slot, form_index, len(forms))
    return forms[form_index]


def _damage(form: Any) -> list[Any]:
    return [b for b in form.damage_blocks if b.attribute_kind == "damage"]


def _modifier_values(form: Any, label: str) -> list[float] | None:
    for b in form.damage_blocks:
        if b.attribute_kind == "modifier" and b.attribute == label:
            mods = [m for m in b.raw_modifiers if isinstance(m, dict)]
            if len(mods) != 1:
                return None
            units = set(mods[0].get("units") or ())
            if units != {"%"}:
                return None
            return [float(v) for v in mods[0]["values"]]
    return None


# --------------------------------------------------------------- S144-D-272


def check_hwei_route(ab: Any, routes: dict[Key, int], amp_rows: dict[Key, Any]) -> list[str]:
    out: list[str] = []
    if HWEI_ROUTE not in routes:
        return [f"{HWEI_ROUTE} missing from the staged routes"]
    form = _form(ab, *HWEI_ROUTE)
    dmg = _damage(form)
    idx = routes[HWEI_ROUTE]
    if not 0 <= idx < len(dmg):
        return [f"route {idx} out of range for {len(dmg)} damage blocks"]
    if dmg[0].attribute != "Magic Damage":
        out.append(f"default first block is {dmg[0].attribute!r}")
    if dmg[idx].attribute != "Maximum Damage":
        out.append(f"route {idx} selects {dmg[idx].attribute!r}")
    pct = _modifier_values(form, "Maximum Damage Increase")
    if pct is None:
        out.append("no single-% 'Maximum Damage Increase' modifier")
    else:
        lo, hi = dmg[0], dmg[idx]
        for field in ("base", "ap_pct"):
            a, b = getattr(lo, field), getattr(hi, field)
            if not a or not b or len(b) != len(pct):
                out.append(f"{field}: shapes {a} / {b} / {pct}")
                continue
            for r, p in enumerate(pct):
                want = a[r if len(a) > 1 else 0] * p / 100.0
                if not math.isclose(b[r], want, rel_tol=1e-9, abs_tol=1e-9):
                    out.append(f"{field} rank {r}: {b[r]} != {want}")
    if HWEI_ROUTE in amp_rows:
        out.append("routed form also carries an amp row (double model)")
    return out


def _route_comment() -> str:
    lines, _ = inspect.getsourcelines(amp_mod)
    end = next(i for i, ln in enumerate(lines) if ln.startswith("_STAGED_AMP_BLOCK_ROUTES"))
    start = end
    while start > 0 and lines[start - 1].startswith("#"):
        start -= 1
    return " ".join(ln.lstrip("# ").rstrip() for ln in lines[start:end])


def test_s144d272_hwei_route_selects_the_live_maximum_block(ab: Any) -> None:
    assert check_hwei_route(ab, _STAGED_AMP_BLOCK_ROUTES, _ABILITY_AMP_OVERRIDES) == []


def test_s144d272_checker_flags_planted_defects(ab: Any) -> None:
    wrong_block = check_hwei_route(ab, {HWEI_ROUTE: 0}, {})
    assert wrong_block[0] == "route 0 selects 'Magic Damage'"
    assert "base rank 4: 160.0 != 560.0" in wrong_block
    assert check_hwei_route(ab, {HWEI_ROUTE: 5}, {})[0].startswith("route 5 out of range")
    assert check_hwei_route(ab, {}, {}) != []
    doubled = check_hwei_route(ab, _STAGED_AMP_BLOCK_ROUTES, {HWEI_ROUTE: object()})
    assert doubled == ["routed form also carries an amp row (double model)"]


def test_s144d272_route_comment_does_not_author_the_clamp() -> None:
    text = _route_comment()
    assert "damage-block index" in text.lower(), "comment walk missed the block"
    assert "out-of-range clamps to the last" not in text
    assert "defect signal" in text
    assert "test_block_index_damage_ordinal_f2" in text


# --------------------------------------------------------------- S144-D-273


def check_magnitudes(ab: Any, rows: dict[Key, Any], sources: dict[Key, tuple[str, str, str]]) -> list[str]:
    out: list[str] = []
    for key, entry in rows.items():
        if not any(entry.amp_per_rank):
            continue
        if getattr(entry, "base", "ability") != "ability":
            continue
        if key not in sources:
            out.append(f"{key}: no named live source for a non-zero amp")
            continue
        slot, label, conv = sources[key]
        form = _form(ab, key[0], slot, 0 if slot != key[1] else key[2])
        pct = _modifier_values(form, label)
        if pct is None:
            out.append(f"{key}: no single-% {label!r} modifier on {slot}")
            continue
        ranks = tuple(entry.amp_per_rank)
        if len(ranks) != len(pct):
            out.append(f"{key}: {len(ranks)} ranks vs {len(pct)} live")
            continue
        for r, (addend, raw) in enumerate(zip(ranks, pct, strict=True)):
            want = addend * 100.0 if conv == "increase" else (1.0 + addend) * 100.0
            if not math.isclose(raw, want, rel_tol=1e-9, abs_tol=1e-9):
                out.append(f"{key} rank {r}: live {raw} vs authored {want}")
    return out


def _all_rows() -> dict[Key, Any]:
    return {**_ABILITY_AMP_OVERRIDES, **_CROSS_SPELL_AMP_OVERRIDES}


def test_s144d273_every_ability_and_cross_spell_amp_matches_its_live_modifier(ab: Any) -> None:
    rows = _all_rows()
    checked = [k for k in rows if k in MAGNITUDE_SOURCES]
    assert len(checked) == len(MAGNITUDE_SOURCES) >= 3, "registry walk went empty"
    assert check_magnitudes(ab, rows, MAGNITUDE_SOURCES) == []


def test_s144d273_checker_flags_planted_defects(ab: Any) -> None:
    mord = ("Mordekaiser", "Q", 0)
    entry = _ABILITY_AMP_OVERRIDES[mord]
    off = amp_mod.AmpEntry(
        amp_per_rank=(0.30, 0.35, 0.40, 0.45, 0.55),
        base="ability",
        condition=entry.condition,
        note=entry.note,
    )
    planted = check_magnitudes(ab, {mord: off}, MAGNITUDE_SOURCES)
    assert len(planted) == 1 and planted[0].startswith(f"{mord} rank 4: live 50.0 vs authored 55.0")
    assert check_magnitudes(ab, {mord: entry}, {}) == [f"{mord}: no named live source for a non-zero amp"]
    wrong_conv = {mord: ("Q", "Damage Increase", "multiplier")}
    assert len(check_magnitudes(ab, {mord: entry}, wrong_conv)) == 5
    wrong_label = {mord: ("Q", "Damage Bonus", "increase")}
    assert check_magnitudes(ab, {mord: entry}, wrong_label)[0].endswith("modifier on Q")


# --------------------------------------------------------------- S144-D-274


def check_live_shapes(
    ab: Any, amp_rows: dict[Key, Any], cross_rows: dict[Key, Any], inert: frozenset[Key]
) -> list[str]:
    out: list[str] = []
    for key, entry in amp_rows.items():
        if entry.base != "ability":
            continue
        dmg = _damage(_form(ab, *key))
        if key in inert:
            if dmg:
                out.append(f"{key}: documented LIVE-INERT but the form now has {len(dmg)} damage block(s)")
        elif len(dmg) != 1:
            out.append(f"{key}: {len(dmg)} damage blocks (expected the one the amp scales)")
    for key, entry in cross_rows.items():
        src = _form(ab, key[0], entry.source_key, 0)
        if _damage(src):
            out.append(f"{key}: source {entry.source_key} has its own damage block")
        if key in amp_rows:
            out.append(f"{key}: target also carries an _ABILITY_AMP_OVERRIDES row")
    return out


def test_s144d274_docstring_live_shape_claims_hold(ab: Any) -> None:
    ability_rows = [k for k, e in _ABILITY_AMP_OVERRIDES.items() if e.base == "ability"]
    assert len(ability_rows) >= 2 and _CROSS_SPELL_AMP_OVERRIDES, "registry walk went empty"
    assert LIVE_INERT_ABILITY_ROWS <= set(ability_rows)
    assert check_live_shapes(ab, _ABILITY_AMP_OVERRIDES, _CROSS_SPELL_AMP_OVERRIDES, LIVE_INERT_ABILITY_ROWS) == []


def test_s144d274_checker_flags_planted_defects(ab: Any) -> None:
    mord = ("Mordekaiser", "Q", 0)
    got = check_live_shapes(ab, {mord: _ABILITY_AMP_OVERRIDES[mord]}, {}, frozenset({mord}))
    assert got == [f"{mord}: documented LIVE-INERT but the form now has 1 damage block(s)"]
    illaoi = ("Illaoi", "Q", 0)
    got = check_live_shapes(ab, {illaoi: _ABILITY_AMP_OVERRIDES[illaoi]}, {}, frozenset())
    assert got == [f"{illaoi}: 0 damage blocks (expected the one the amp scales)"]
    asol = ("AurelionSol", "Q", 0)
    xs = _CROSS_SPELL_AMP_OVERRIDES[asol]
    both = {asol: _ABILITY_AMP_OVERRIDES[mord]}
    assert check_live_shapes(ab, both, {asol: xs}, frozenset()) == [
        f"{asol}: 4 damage blocks (expected the one the amp scales)",
        f"{asol}: target also carries an _ABILITY_AMP_OVERRIDES row",
    ]
    mord_src = dataclasses.replace(xs, source_key="Q")
    got = check_live_shapes(ab, {}, {("Mordekaiser", "W", 0): mord_src}, frozenset())
    assert got == ["('Mordekaiser', 'W', 0): source Q has its own damage block"]
