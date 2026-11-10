"""S144-D-275..277 - the DS AA-empower amp rows and the Sion Q block note match live data.

WHY. ``_ability_amp_overrides`` hand-authors the ``base="aa"`` rows from the
live forms and cites their magnitudes in prose. S144-D-272..274 tied the
``base="ability"`` and cross-spell rows to the live snapshot; the AA rows and
the Sion Q note were still checked only against their own literals.

* S144-D-275: the one real AA amp (Fiora E) is ``(m - 1) / cd`` per rank, and
  test_aa_empower_authored_item258 rebuilds it from HAND-TYPED cooldowns and
  crit multipliers. Here ``m`` and ``cd`` come from the live E form (the
  "Critical damage" modifier % and the form cooldown), the authored tuple must
  equal them rounded to 4 places, and the comment / note magnitudes
  ("cd 11/10/9/8/7s", "160:200%") are derived from the same live values.
* S144-D-276: the four INERT AA rows justify ``(0.0,)`` with live magnitudes
  (Caitlyn W Headshot 35:215 flat + 30% bonus AD; Jayce W f1 70:110 % AD,
  below 1.0 x AD at ranks 1-4 only, delta -0.30..-0.06; Sivir W bounce 40:50%
  total AD plus bonus AS; Nidalee Q f1 75:206% total AD + 40:110% AP). Each
  cited string is rebuilt from the live form, so a patch that moves one fails
  until someone re-reads the non-fit argument. Every ``base="aa"`` row must
  have an expectation here.
* S144-D-277: five comments said Sion Q is routed by
  ``champion_block_index.json`` "{Q:2}". Since the F2 damage-ordinal renumber
  the registry holds ``{"Q": 1}``: damage-block ordinal 1 of the live Sion Q
  form is "Maximum Physical Damage", which is what the comments claim it
  selects. Every such citation in the DS package must carry the live value.

MEASURED 2026-11-09 (``load_default()``, patch 16.22.1): Fiora E cooldown
11/10/9/8/7, "Critical damage" 160..200 %; every AA magnitude above matched;
Sion Q damage blocks "Minimum Physical Damage", "Maximum Physical Damage";
champion_block_index Sion {"Q": 1, "R": 1}. Comment-only fixes; no registry
value changes, so scorer output is byte-identical.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _ability_amp_overrides as amp_mod
from agents.daemon_slayer._ability_amp_overrides import (
    _ABILITY_AMP_OVERRIDES,
    _STAGED_AMP_BLOCK_ROUTES,
)
from agents.daemon_slayer.abilities import load_default

Key = tuple[str, str, int]

PKG = Path(amp_mod.__file__).resolve().parent
BLOCK_INDEX_JSON = PKG / "champion_block_index.json"
FIORA_E: Key = ("Fiora", "E", 0)
INERT_AA_ROWS: frozenset[Key] = frozenset(
    {("Caitlyn", "W", 0), ("Jayce", "W", 1), ("Sivir", "W", 0), ("Nidalee", "Q", 1)}
)
SION_Q: Key = ("Sion", "Q", 0)
SION_CITING_FILES = (
    "_ability_amp_overrides.py",
    "ability_dps.py",
    "tests/test_staged_amp_block_route_item246.py",
)


@pytest.fixture(scope="module")
def ab() -> Any:
    return load_default()


@pytest.fixture(scope="module")
def amp_src() -> str:
    return Path(amp_mod.__file__).read_text(encoding="utf-8")


def _form(ab: Any, champ: str, slot: str, form_index: int) -> Any:
    assert ab.has_champion(champ), champ
    forms = ab.get_abilities(champ).get(slot) or ()
    assert 0 <= form_index < len(forms), (champ, slot, form_index, len(forms))
    return forms[form_index]


def _damage(form: Any) -> list[Any]:
    return [b for b in form.damage_blocks if b.attribute_kind == "damage"]


def _block(form: Any, kind: str, label: str) -> Any | None:
    for b in form.damage_blocks:
        if b.attribute_kind == kind and b.attribute == label:
            return b
    return None


def _mods(block: Any) -> list[dict]:
    return [m for m in block.raw_modifiers if isinstance(m, dict)]


def _g(x: float) -> str:
    return f"{x:g}"


# --------------------------------------------------------------- S144-D-275


def check_fiora(form: Any, amp: tuple[float, ...], note: str, src: str) -> list[str]:
    out: list[str] = []
    crit_block = _block(form, "modifier", "Critical damage")
    if crit_block is None or len(_mods(crit_block)) != 1:
        return ["no single 'Critical damage' modifier on the live form"]
    mod = _mods(crit_block)[0]
    if set(mod.get("units") or ()) != {"%"}:
        return [f"'Critical damage' units {mod.get('units')}"]
    crit = [float(v) for v in mod["values"]]
    cd = [float(c) for c in (form.cooldown or ())]
    if not (len(crit) == len(cd) == len(amp)):
        return [f"lengths crit {len(crit)} cd {len(cd)} amp {len(amp)}"]
    for r, (m_pct, c) in enumerate(zip(crit, cd, strict=True)):
        want = (m_pct / 100.0 - 1.0) / c
        if abs(amp[r] - want) > 0.5e-4 + 1e-12:
            out.append(f"rank {r}: authored {amp[r]} != live (m-1)/cd {want:.6f}")
    crit_txt = f"{_g(crit[0])}:{_g(crit[-1])}%"
    if crit_txt not in note:
        out.append(f"note does not cite the live crit range {crit_txt!r}")
    cd_txt = "cd " + "/".join(_g(c) for c in cd) + "s"
    if cd_txt not in src:
        out.append(f"comment does not cite the live cooldowns {cd_txt!r}")
    return out


def test_fiora_e_amp_is_live_m_minus_1_over_cd(ab: Any, amp_src: str) -> None:
    entry = _ABILITY_AMP_OVERRIDES[FIORA_E]
    form = _form(ab, *FIORA_E)
    assert check_fiora(form, entry.amp_per_rank, entry.note, amp_src) == []


def test_fiora_check_catches_planted_defects(ab: Any, amp_src: str) -> None:
    entry = _ABILITY_AMP_OVERRIDES[FIORA_E]
    form = _form(ab, *FIORA_E)
    bad_amp = (entry.amp_per_rank[0] + 0.001, *entry.amp_per_rank[1:])
    assert any("rank 0" in e for e in check_fiora(form, bad_amp, entry.note, amp_src))
    short = entry.amp_per_rank[:-1]
    assert any("lengths" in e for e in check_fiora(form, short, entry.note, amp_src))
    bad_note = entry.note.replace("160:200%", "150:200%")
    assert any("crit range" in e for e in check_fiora(form, entry.amp_per_rank, bad_note, amp_src))
    bad_src = amp_src.replace("cd 11/10/9/8/7s", "cd 12/10/9/8/7s")
    assert any("cooldowns" in e for e in check_fiora(form, entry.amp_per_rank, entry.note, bad_src))


# --------------------------------------------------------------- S144-D-276


def _caitlyn(form: Any) -> tuple[list[str], list[str]]:
    b = _block(form, "modifier", "Headshot Damage Increase")
    if b is None or len(_mods(b)) != 2:
        return ["no two-part 'Headshot Damage Increase' modifier"], []
    flat, ratio = _mods(b)
    if set(ratio.get("units") or ()) != {"% bonus AD"} or len(set(ratio["values"])) != 1:
        return [f"Headshot ratio part {ratio}"], []
    txt = f"{_g(flat['values'][0])}:{_g(flat['values'][-1])} flat + {_g(ratio['values'][0])}% bonus AD"
    return [], [txt]


def _jayce(form: Any) -> tuple[list[str], list[str]]:
    b = _block(form, "modifier", "Damage Modifier")
    if b is None or len(_mods(b)) != 1 or set(_mods(b)[0].get("units") or ()) != {"% AD"}:
        return ["no single '% AD' 'Damage Modifier' modifier"], []
    vals = [float(v) for v in _mods(b)[0]["values"]]
    errs: list[str] = []
    above = [r + 1 for r, v in enumerate(vals) if v > 100.0]
    below = [v for v in vals if v < 100.0]
    if above != list(range(len(vals) - len(above) + 1, len(vals) + 1)):
        errs.append(f"ranks above 1.0 x AD are not a tail: {above}")
    if not below:
        errs.append("no rank below 1.0 x AD")
        return errs, []
    rng = f"{_g(vals[0])}:{_g(vals[-1])}"
    texts = [
        f"{rng} % AD",
        f"{rng}% AD",
        "only rank " + "/".join(str(r) for r in above) + " exceed it",
        f"ranks 1-{len(below)}",
        f"delta {(below[0] - 100) / 100:.2f}..{(below[-1] - 100) / 100:.2f}",
    ]
    return errs, texts


def _sivir(form: Any) -> tuple[list[str], list[str]]:
    b = _block(form, "damage", "Bounce Damage")
    if b is None or not b.total_ad_pct:
        return ["no 'Bounce Damage' total-AD damage block"], []
    errs = []
    if _block(form, "duration", "Bonus Attack Speed") is None:
        errs.append("no 'Bonus Attack Speed' block (the cited AS gain)")
    rng = f"{_g(b.total_ad_pct[0])}:{_g(b.total_ad_pct[-1])}%"
    return errs, [f"{rng} total AD", f"{rng} AD"]


def _nidalee(form: Any) -> tuple[list[str], list[str]]:
    lo = _block(form, "damage", "Minimum Magic Damage")
    hi = _block(form, "damage", "Maximum Magic Damage")
    if lo is None or hi is None or not (lo.total_ad_pct and hi.total_ad_pct):
        return ["no Minimum / Maximum Magic Damage total-AD blocks"], []
    if not (lo.ap_pct and hi.ap_pct):
        return ["Minimum / Maximum Magic Damage carry no AP ratio"], []
    txt = f"{_g(lo.total_ad_pct[0])}:{int(hi.total_ad_pct[-1])}% total AD + {_g(lo.ap_pct[0])}:{_g(hi.ap_pct[-1])}% AP"
    return [], [txt]


AA_EXPECTATIONS = {
    ("Caitlyn", "W", 0): _caitlyn,
    ("Jayce", "W", 1): _jayce,
    ("Sivir", "W", 0): _sivir,
    ("Nidalee", "Q", 1): _nidalee,
}


def check_inert_row(ab: Any, key: Key, rows: dict[Key, Any], src: str) -> list[str]:
    entry = rows[key]
    out: list[str] = []
    if entry.base != "aa" or tuple(entry.amp_per_rank) != (0.0,):
        out.append(f"{key}: not an INERT (0.0,) aa row")
    errs, texts = AA_EXPECTATIONS[key](_form(ab, *key))
    out += [f"{key}: {e}" for e in errs]
    hay = src + "\n" + entry.note
    out += [f"{key}: live text {t!r} not cited" for t in texts if t not in hay]
    return out


def test_every_aa_row_has_a_live_expectation() -> None:
    aa = {k for k, e in _ABILITY_AMP_OVERRIDES.items() if e.base == "aa"}
    assert aa == set(AA_EXPECTATIONS) | {FIORA_E}
    assert set(AA_EXPECTATIONS) == INERT_AA_ROWS


@pytest.mark.parametrize("key", sorted(INERT_AA_ROWS))
def test_inert_aa_row_cites_live_magnitudes(ab: Any, amp_src: str, key: Key) -> None:
    assert check_inert_row(ab, key, _ABILITY_AMP_OVERRIDES, amp_src) == []


@pytest.mark.parametrize(
    ("key", "old", "new"),
    [
        (("Caitlyn", "W", 0), "35:215 flat", "35:200 flat"),
        (("Jayce", "W", 1), "-0.30..-0.06", "-0.30..-0.10"),
        (("Jayce", "W", 1), "only rank 5/6 exceed it", "only rank 6 exceed it"),
        (("Sivir", "W", 0), "40:50% total AD", "40:55% total AD"),
        (("Nidalee", "Q", 1), "75:206% total AD", "75:200% total AD"),
    ],
)
def test_inert_row_check_catches_planted_text(ab: Any, amp_src: str, key: Key, old: str, new: str) -> None:
    assert old in amp_src, old
    rows = dict(_ABILITY_AMP_OVERRIDES)
    entry = rows[key]
    rows[key] = dataclasses.replace(entry, note=entry.note.replace(old, new))
    errs = check_inert_row(ab, key, rows, amp_src.replace(old, new))
    assert any("not cited" in e for e in errs), errs


def test_inert_row_check_catches_planted_nonzero_amp(ab: Any, amp_src: str) -> None:
    key = ("Sivir", "W", 0)
    rows = dict(_ABILITY_AMP_OVERRIDES)
    entry = rows[key]
    rows[key] = dataclasses.replace(entry, amp_per_rank=(0.1,))
    assert any("not an INERT" in e for e in check_inert_row(ab, key, rows, amp_src))


# --------------------------------------------------------------- S144-D-277

_CITE = re.compile(r'champion_block_index\.json[`\s#]*\{\s*"?Q"?\s*:\s*(\d+)\s*\}')


def check_sion_citations(texts: dict[str, str], live_q: int) -> list[str]:
    out: list[str] = []
    for name, text in sorted(texts.items()):
        for m in _CITE.finditer(text):
            if "Sion" not in text[max(0, m.start() - 200) : m.start()]:
                out.append(f"{name}: block-index citation not attributed to Sion")
            elif int(m.group(1)) != live_q:
                out.append(f"{name}: cites Sion Q:{m.group(1)}, live is Q:{live_q}")
    return out


def _package_texts() -> dict[str, str]:
    return {p.relative_to(PKG).as_posix(): p.read_text(encoding="utf-8") for p in sorted(PKG.rglob("*.py"))}


def test_sion_q_block_index_selects_the_live_maximum_block(ab: Any) -> None:
    doc = json.loads(BLOCK_INDEX_JSON.read_text(encoding="utf-8"))
    live_q = doc["champions"]["Sion"]["Q"]
    assert isinstance(live_q, int)
    dmg = _damage(_form(ab, *SION_Q))
    assert 0 <= live_q < len(dmg)
    assert dmg[live_q].attribute == "Maximum Physical Damage"
    assert dmg[0].attribute != "Maximum Physical Damage"
    assert SION_Q not in _STAGED_AMP_BLOCK_ROUTES
    assert SION_Q not in _ABILITY_AMP_OVERRIDES


def test_every_sion_block_index_citation_carries_the_live_value() -> None:
    live_q = json.loads(BLOCK_INDEX_JSON.read_text(encoding="utf-8"))["champions"]["Sion"]["Q"]
    texts = _package_texts()
    citing = {n for n, t in texts.items() if _CITE.search(t)}
    assert set(SION_CITING_FILES) <= citing, sorted(citing)
    assert check_sion_citations(texts, live_q) == []


def test_sion_citation_check_catches_planted_defects() -> None:
    head = "Sion Q needs no route: champion_block_index"
    stale = {"x.py": head + ".json {Q:7} selects it"}
    assert any("live is Q:1" in e for e in check_sion_citations(stale, 1))
    quoted = {"x.py": head + '.json``\n  ``{"Q": 7}``'}
    assert any("live is Q:1" in e for e in check_sion_citations(quoted, 1))
    other = {"x.py": "Hwei Q: champion_block_index" + ".json {Q:1}"}
    assert any("not attributed" in e for e in check_sion_citations(other, 1))
    good = {"x.py": head + ".json {Q:1} selects it"}
    assert check_sion_citations(good, 1) == []
