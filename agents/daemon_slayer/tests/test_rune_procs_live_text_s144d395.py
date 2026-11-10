"""S144-D-395, 396 and 398: the rune_procs registry matches the live text it cites.

Measured at patch 16.22.1 (ENGINE 1.291.0) against the vendored DDragon
``runesReforged.json`` snapshots under ``data/meta_build/ddragon/``; the
checks read the snapshot ``data/daemon_slayer/current.txt`` names.

- S144-D-395 (``parity_mismatches``), for every RUNE_PROCS id but Hail of
  Blades 9923:

  * the closure's value at level 1 and at level 18 is the live number; a
    closure whose text states no level ramp (Dark Harvest 8128, Grasp of the
    Undying 8437, Gathering Storm 8236) gives the same value at level 18 as
    at level 1;
  * every coefficient the text states (bonus AD, AP, bonus health, new
    shield amount, caster max health, souls, Lethal Tempo's bonus attack
    speed) is the live one at level 1 and at level 18;
  * at level 1 and 18 the closure ignores each of seven probed inputs
    (bonus AD, AP, bonus health, shield amount, target max health, caster
    max health, souls) its text states no term for; the adaptive grants
    8233 / 8236 pick a side but do not scale with AP;
  * the four amp-only closures (8014, 8017, 8299, 8369) return exactly 0.0
    under every probe and gate context; their percentages are S144-D-396's.

  For 9923 only the unstated inputs and the cooldown are checked; its
  magnitudes are S144-D-394's strict xfail in
  ``agents/daemon_slayer/tests/test_rune_heal_health_block_offense_live_text_s144d389.py``.
  Every ``cooldown_s`` the text states is the live level-1 value; a rune
  whose text states no cooldown carries 0.0, except Summon Aery 8214, whose
  2.0 is the "~2s effective" return trip its ``formula`` names.
  NOT checked: Grasp's ranged "40% effective" (the closure models the melee
  value; its comment leaves the ranged scale to the caller), the ranged side
  of every rune but Lethal Tempo, Aery's shield, Conqueror's heal, and
  Gathering Storm past its 10 min row (the feed's later rows are a step
  table ``_rune_offense_grants`` transcribes; the burst closure does not).
- S144-D-396: the amp multipliers and HP gates (Press the Attack, First
  Strike, Coup de Grace, Cut Down, Last Stand) are the live percentages, and
  Conqueror's ``formula`` names the live stack cap. Absolute Focus's 70%
  gate is S144-D-395's.
- S144-D-398: the parity checker catches every mutation of an in-memory
  sweep over every RUNE_PROCS id: the value x1.01 at level 18 only, +0.5,
  +0.01 x each of the seven probed inputs, and ``cooldown_s`` + 1. For 9923
  only the unstated-input and cooldown mutations run; the amp-only closures
  skip the x1.01 mutation, which leaves 0.0 unchanged. It also catches
  planted drifts in the live text.

Tests only; ``rune_procs.py`` is unchanged. The module-prose half
(S144-D-397) is a separate slice.
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from agents.daemon_slayer.rune_procs import RUNE_PROCS, compute_rune_proc_damage, keystone_amp
from agents.daemon_slayer.tests.test_rune_hsp_resist_shield_live_text_s144d386 import (
    _CURRENT_TXT,
    _DDRAGON_ROOT,
    _squash,
    _vendored,
)
from itertools import starmap

_TAG_RE = re.compile(r"<[^>]+>")


@pytest.fixture(scope="module")
def vendored() -> dict[str, dict[int, tuple[str, str, str]]]:
    assert _DDRAGON_ROOT.is_dir(), "no vendored DDragon snapshots"
    return _vendored()


@pytest.fixture(scope="module")
def live(vendored) -> dict[int, str]:
    assert _CURRENT_TXT.exists(), "no data/daemon_slayer/current.txt"
    patch = _CURRENT_TXT.read_text(encoding="utf-8").strip()
    assert patch in vendored, f"no vendored runesReforged.json for {patch}"
    return {rid: row[2] for rid, row in vendored[patch].items()}


def _flat(desc: str) -> str:
    """The longDesc with every tag and every whitespace character removed."""
    return _squash(_TAG_RE.sub(" ", desc))


def _nums(pattern: str, desc: str) -> tuple[float, ...] | None:
    m = re.search(pattern, _flat(desc))
    return tuple(float(g) for g in m.groups()) if m else None


def _c(rid: int, level: float = 1.0, **kw) -> float:
    return compute_rune_proc_damage(rid, level, **kw)


def _close(a: float, b: float) -> bool:
    return a == pytest.approx(b, abs=1e-9)


# ---- S144-D-395 checker (pure, so planted drifts can exercise it) ------------

# rid -> (squashed pattern, group roles). "lo" / "hi" = level-1 / level-18 ends;
# "ad" / "ap" = adaptive stat coefficients; "bhp%" / "shield%" = percent terms.
_RAMPS: dict[int, tuple[str, tuple[str, ...]]] = {
    8112: (r"Damage:(\d+)-(\d+)\(\+([\d.]+)bonusAD,\+([\d.]+)AP\)", ("lo", "hi", "ad", "ap")),
    8229: (r"AdaptiveDamage:(\d+)-(\d+)basedonlevel\(\+([\d.]+)APand\+([\d.]+)bonusAD\)", ("lo", "hi", "ap", "ad")),
    8214: (r"dealing(\d+)-(\d+)basedonlevel\(\+([\d.]+)AP\)\(\+([\d.]+)bonusAD\)", ("lo", "hi", "ap", "ad")),
    8143: (r"bonus(\d+)-(\d+)TrueDamagebasedonlevel", ("lo", "hi")),
    8126: (r"deals(\d+)-(\d+)bonustruedamage\(basedonlevel\)", ("lo", "hi")),
    8237: (r"dealing(\d+)-(\d+)bonusmagicdamagebasedonlevel", ("lo", "hi")),
    8005: (r"deals(\d+)-(\d+)bonusadaptivedamage\(basedonlevel\)", ("lo", "hi")),
    8010: (r"gaining([\d.]+)-([\d.]+)AdaptiveForceperstack", ("lo", "hi")),
    8439: (r"Damage:(\d+)-(\d+)\(\+([\d.]+)%ofyourbonushealth\)", ("lo", "hi", "bhp%")),
    8401: (
        r"deals(\d+)-(\d+)\(\+([\d.]+)%BonusHealth\)\(\+([\d.]+)%NewShieldAmount\)",
        ("lo", "hi", "bhp%", "shield%"),
    ),
}

# rid -> pattern whose first group is the cooldown ``cooldown_s`` must equal.
_COOLDOWNS: dict[int, str] = {
    8112: r"Cooldown:(\d+)s",
    8128: r"Cooldown:(\d+)s",
    8229: r"Cooldown:(\d+)-\d+s",
    8143: r"Cooldown:(\d+)s",
    8126: r"Cooldown:(\d+)s",
    8237: r"Cooldown:(\d+)s",
    8437: r"Every(\d+)sincombat",
    8439: r"Cooldown:(\d+)s",
    8369: r"Cooldown:(\d+)-\d+s",
    9923: r"Cooldown:(\d+)s",
}

# Ids the checker covers some other way (special shapes or S144-D-396 amps).
_SPECIAL = {8128, 8437, 8008, 8233, 8236, 8014, 8017, 8299, 8369, 9923}


def _ramp_mismatches(rid: int, desc: str) -> list[str]:
    pattern, roles = _RAMPS[rid]
    got = _nums(pattern, desc)
    if got is None:
        return [f"{rid}: live shape not found"]
    v = dict(zip(roles, got))
    out: list[str] = []
    if not _close(_c(rid, 1.0), v["lo"]):
        out.append(f"{rid}: level 1 {_c(rid, 1.0)} != live {v['lo']}")
    if not _close(_c(rid, 18.0), v["hi"]):
        out.append(f"{rid}: level 18 {_c(rid, 18.0)} != live {v['hi']}")
    for level in (1.0, 18.0):
        base = _c(rid, level)
        if not _close(_c(rid, level, ad=100.0) - base, 100.0 * v.get("ad", 0.0)):
            out.append(f"{rid}: bonus AD coefficient at level {level} is not the live {v.get('ad', 0.0)}")
        if not _close(_c(rid, level, ap=100.0) - base, 100.0 * v.get("ap", 0.0)):
            out.append(f"{rid}: AP coefficient at level {level} is not the live {v.get('ap', 0.0)}")
        if not _close(_c(rid, level, bonus_hp=1000.0) - base, 10.0 * v.get("bhp%", 0.0)):
            out.append(f"{rid}: bonus health ratio at level {level} is not the live {v.get('bhp%', 0.0)}%")
        if not _close(_c(rid, level, shield_amount=100.0) - base, v.get("shield%", 0.0)):
            out.append(f"{rid}: shield ratio at level {level} is not the live {v.get('shield%', 0.0)}%")
    return out


def _special_mismatches(live: dict[int, str]) -> list[str]:
    out: list[str] = []
    dh = _nums(r"DarkHarvestdamage:(\d+)\(\+(\d+)damagepersoul\)\(\+([\d.]+)bonusAD\)\(\+([\d.]+)AP\)", live[8128])
    if dh is None:
        out.append("8128: live shape not found")
    else:
        base, per_soul, ad, ap = dh
        for level in (1.0, 18.0):
            if not _close(_c(8128, level), base):
                out.append(f"8128: base at level {level} {_c(8128, level)} != live {base}")
            if not _close(_c(8128, level, souls=3.0) - _c(8128, level), 3.0 * per_soul):
                out.append(f"8128: per-soul at level {level} is not the live {per_soul}")
            if not _close(_c(8128, level, ad=100.0) - _c(8128, level), 100.0 * ad):
                out.append(f"8128: bonus AD coefficient at level {level} is not the live {ad}")
            if not _close(_c(8128, level, ap=100.0) - _c(8128, level), 100.0 * ap):
                out.append(f"8128: AP coefficient at level {level} is not the live {ap}")
    grasp = _nums(r"equalto([\d.]+)%ofyourmaxhealth", live[8437])
    for level in (1.0, 18.0):
        if grasp is None or not (
            _close(_c(8437, level, caster_max_hp=1000.0), 10.0 * grasp[0])
            and _close(_c(8437, level, caster_max_hp=0.0), 0.0)
        ):
            out.append(f"8437: max-health ratio at level {level} is not the live {grasp}")
    lt = _nums(r"\[(\d+)-(\d+)Melee\|\|(\d+)-(\d+)Ranged\]bonusadaptivedamageOn-Attack,increasedby1%per1%", live[8008])
    if lt is None:
        out.append("8008: live shape not found")
    else:
        m_lo, m_hi, r_lo, r_hi = lt
        pairs = [
            (_c(8008, 1.0), m_lo),
            (_c(8008, 18.0), m_hi),
            (_c(8008, 1.0, role="ranged"), r_lo),
            (_c(8008, 18.0, role="ranged"), r_hi),
        ]
        for level, melee, ranged in ((1.0, m_lo, r_lo), (18.0, m_hi, r_hi)):
            pairs.append((_c(8008, level, bonus_as=0.5), 1.5 * melee))
            pairs.append((_c(8008, level, role="ranged", bonus_as=0.5), 1.5 * ranged))
        if not all(starmap(_close, pairs)):
            out.append(f"8008: melee / ranged ends or the 1%-per-1% AS amp drift from live {lt}")
    af = _nums(
        r"Whileabove(\d+)%health,gainanadaptivebonusofupto(\d+)AttackDamageor(\d+)AbilityPower"
        r"\(basedonlevel\)\.Grants([\d.]+)AttackDamageor([\d.]+)AbilityPoweratlevel1",
        live[8233],
    )
    if af is None:
        out.append("8233: live shape not found")
    else:
        gate, ad_hi, ap_hi, ad_lo, ap_lo = af
        g = gate / 100.0
        pairs = [
            (_c(8233, 1.0), ad_lo),
            (_c(8233, 18.0), ad_hi),
            (_c(8233, 1.0, ap=1.0), ap_lo),
            (_c(8233, 18.0, ap=1.0), ap_hi),
        ]
        for level, ad_end, ap_end in ((1.0, ad_lo, ap_lo), (18.0, ad_hi, ap_hi)):
            pairs.append((_c(8233, level, caster_hp_pct=g), 0.0))
            pairs.append((_c(8233, level, caster_hp_pct=g + 0.01), ad_end))
            pairs.append((_c(8233, level, ap=1.0, caster_hp_pct=g), 0.0))
            pairs.append((_c(8233, level, ap=1.0, caster_hp_pct=g + 0.01), ap_end))
        if not all(starmap(_close, pairs)):
            out.append(f"8233: grant ends or the {gate}% health gate drift from live {af}")
    gs = _nums(r"10min:\+(\d+)APor(\d+)AD", live[8236])
    if gs is None:
        out.append("8236: live shape not found")
    else:
        ap10, ad10 = gs
        for level in (1.0, 18.0):
            ad_side = _c(8236, level, game_time_s=600.0)
            ap_side = _c(8236, level, ap=1.0, game_time_s=600.0)
            if not (_close(ad_side, ad10) and _close(ap_side, ap10)):
                out.append(f"8236: the 10 min row at level {level} is not the live {ad10} AD / {ap10} AP")
    return out


# Closures whose text states no level ramp: level 18 must equal level 1 under
# every probe (base kwargs merged in).
_LEVEL_FLAT: dict[int, dict[str, float]] = {
    8128: {},
    8437: {"caster_max_hp": 1000.0},
    8236: {"game_time_s": 600.0},
}

# Amp-only closures: the burst value is 0.0 whatever the input or gate context.
_ZERO = (8014, 8017, 8299, 8369)
_GATE_CONTEXTS: tuple[dict[str, float], ...] = (
    {},
    {"caster_hp_pct": 0.1},
    {"target_hp_pct": 0.1},
    {"target_hp_pct": 0.9},
    {"game_time_s": 600.0},
)


# One input at a time; a closure must ignore every input its text states no
# term for.
_PROBES: dict[str, dict[str, float]] = {
    "ad": {"ad": 100.0},
    "ap": {"ap": 100.0},
    "bonus_hp": {"bonus_hp": 1000.0},
    "shield_amount": {"shield_amount": 100.0},
    "target_max_hp": {"target_max_hp": 3000.0},
    "caster_max_hp": {"caster_max_hp": 1000.0},
    "souls": {"souls": 3.0},
}

_ROLE_INPUT = {"ad": "ad", "ap": "ap", "bhp%": "bonus_hp", "shield%": "shield_amount"}

# rid -> (base kwargs, inputs the live text states a term for).
_STATED: dict[int, tuple[dict[str, float], set[str]]] = {
    **{rid: ({}, {_ROLE_INPUT[r] for r in roles if r in _ROLE_INPUT}) for rid, (_p, roles) in _RAMPS.items()},
    8128: ({}, {"ad", "ap", "souls"}),
    8437: ({"caster_max_hp": 1000.0}, {"caster_max_hp"}),
    8008: ({}, set()),
    8233: ({}, {"ap"}),
    8236: ({"game_time_s": 600.0}, {"ap"}),
    8014: ({}, set()),
    8017: ({}, set()),
    8299: ({}, set()),
    8369: ({}, set()),
    9923: ({}, {"ad", "ap"}),
}

# Adaptive STAT grants: a larger AP picks the AP side but must not scale it.
_GRANTS = {8233: {}, 8236: {"game_time_s": 600.0}}


def _unstated_mismatches() -> list[str]:
    out: list[str] = []
    for rid, (kw, stated) in _STATED.items():
        for level in (1.0, 18.0):
            base = _c(rid, level, **kw)
            for name, probe in _PROBES.items():
                if name not in stated and not _close(_c(rid, level, **{**kw, **probe}), base):
                    out.append(f"{rid}: reads {name}, which its text states no term for")
    for rid, kw in _GRANTS.items():
        for level in (1.0, 18.0):
            if not _close(_c(rid, level, ap=100.0, **kw), _c(rid, level, ap=200.0, **kw)):
                out.append(f"{rid}: the AP-side grant scales with AP")
    return sorted(set(out))


def _shape_mismatches() -> list[str]:
    """Level-flat closures stay flat; amp-only closures stay 0.0."""
    out: list[str] = []
    for rid, kw in _LEVEL_FLAT.items():
        for probe in ({}, *_PROBES.values()):
            args = {**kw, **probe}
            if not _close(_c(rid, 18.0, **args), _c(rid, 1.0, **args)):
                out.append(f"{rid}: level 18 differs from level 1 under {probe}, but the text states no level ramp")
    for rid in _ZERO:
        for level in (1.0, 18.0):
            for gate in _GATE_CONTEXTS:
                for probe in ({}, *_PROBES.values()):
                    got = _c(rid, level, **{**gate, **probe})
                    if got != 0.0:
                        out.append(f"{rid}: amp-only closure returns {got} at level {level} under {gate} {probe}")
    return sorted(set(out))


# Summon Aery's text states no cooldown; its 2.0 models the return trip.
_MODELED_COOLDOWNS = {8214: (2.0, "~2s effective")}


def _cooldown_mismatches(live: dict[int, str]) -> list[str]:
    out: list[str] = []
    for rid, proc in RUNE_PROCS.items():
        if rid in _COOLDOWNS:
            got = _nums(_COOLDOWNS[rid], live[rid])
            if got is None or not _close(proc.cooldown_s, got[0]):
                out.append(f"{rid}: cooldown_s {proc.cooldown_s} != live {got}")
            continue
        if "cooldown" in _flat(live[rid]).lower():
            out.append(f"{rid}: the live text states a cooldown the checker does not read")
        value, phrase = _MODELED_COOLDOWNS.get(rid, (0.0, ""))
        if not _close(proc.cooldown_s, value) or phrase not in proc.formula:
            out.append(f"{rid}: cooldown_s {proc.cooldown_s} != {value} for a text that states no cooldown")
    return out


def parity_mismatches(live: dict[int, str]) -> list[str]:
    """Every way a RUNE_PROCS closure or cooldown disagrees with ``live``."""
    out: list[str] = []
    for rid in _RAMPS:
        out.extend(_ramp_mismatches(rid, live[rid]))
    out.extend(_special_mismatches(live))
    out.extend(_unstated_mismatches())
    out.extend(_shape_mismatches())
    out.extend(_cooldown_mismatches(live))
    return out


# ---- S144-D-395 -------------------------------------------------------------


def test_every_registered_rune_is_checked() -> None:
    assert set(_RAMPS) | _SPECIAL == set(RUNE_PROCS)
    assert set(_RAMPS).isdisjoint(_SPECIAL)
    assert set(_STATED) == set(RUNE_PROCS)
    assert set(_LEVEL_FLAT) | set(_ZERO) <= _SPECIAL


def test_closures_and_cooldowns_match_the_live_text(live) -> None:
    assert parity_mismatches(live) == []


# ---- S144-D-396: amp multipliers and HP gates --------------------------------


def test_flat_amps_are_the_live_percentages(live) -> None:
    pta = _nums(r"amplifiesyourdamagedealtby(\d+)%", live[8005])
    fs = _nums(r"causingyoutodeal(\d+)%extradamageagainstchampions", live[8369])
    assert pta and fs
    assert RUNE_PROCS[8005].amp_mult == pytest.approx(1.0 + pta[0] / 100.0)
    assert RUNE_PROCS[8369].amp_mult == pytest.approx(1.0 + fs[0] / 100.0)
    assert keystone_amp(8005, 100.0) == pytest.approx(100.0 + pta[0])
    assert keystone_amp(8369, 100.0) == pytest.approx(100.0 + fs[0])
    assert _c(8369, 18.0, ad=999.0, ap=999.0) == 0.0


@pytest.mark.parametrize(
    ("rid", "word", "inside", "outside"),
    [(8014, "less", -0.01, 0.0), (8017, "more", 0.01, 0.0)],
)
def test_target_hp_amps_are_the_live_percentages(live, rid, word, inside, outside) -> None:
    got = _nums(rf"Deal(\d+)%moredamagetochampionswhohave{word}than(\d+)%health", live[rid])
    assert got
    pct, gate = got[0], got[1] / 100.0
    assert RUNE_PROCS[rid].amp_mult == pytest.approx(1.0 + pct / 100.0)
    amped = keystone_amp(rid, 100.0, gate_target_hp=True, target_hp_pct=gate + inside)
    flat = keystone_amp(rid, 100.0, gate_target_hp=True, target_hp_pct=gate + outside)
    assert amped == pytest.approx(100.0 + pct)
    assert flat == pytest.approx(100.0)


def test_last_stand_ramp_is_the_live_text(live) -> None:
    got = _nums(
        r"Deal(\d+)%-(\d+)%increaseddamagetochampionswhileyouarebelow(\d+)%health\.Maxdamagegainedat(\d+)%health",
        live[8299],
    )
    assert got
    lo, hi, below, full = got
    assert keystone_amp(8299, 100.0, caster_hp_pct=below / 100.0) == pytest.approx(100.0)
    assert keystone_amp(8299, 100.0, caster_hp_pct=below / 100.0 - 1e-9) == pytest.approx(100.0 + lo)
    assert keystone_amp(8299, 100.0, caster_hp_pct=full / 100.0) == pytest.approx(100.0 + hi)
    assert keystone_amp(8299, 100.0, caster_hp_pct=0.05) == pytest.approx(100.0 + hi)


def test_conqueror_stack_cap_in_the_formula_is_live(live) -> None:
    got = _nums(r"Stacksupto(\d+)times", live[8010])
    assert got
    assert f"up to {int(got[0])} stacks" in RUNE_PROCS[8010].formula


# ---- S144-D-398: planted drifts --------------------------------------------


@pytest.mark.parametrize(
    ("rid", "old", "new", "needle"),
    [
        (8112, "70 - 240", "75 - 240", "8112: level 1"),
        (8112, "+0.05 AP", "+0.07 AP", "8112: AP coefficient"),
        (8229, "Cooldown: 20 - 8s", "Cooldown: 18 - 8s", "8229: cooldown_s"),
        (8128, "+11 damage per soul", "+12 damage per soul", "8128: per-soul"),
        (8439, "+8% of your bonus health", "+9% of your bonus health", "8439: bonus health"),
        (8401, "+15.0% New Shield Amount", "+20.0% New Shield Amount", "8401: shield"),
        (8008, "9 - 30 Melee", "8 - 30 Melee", "8008:"),
        (8233, "While above 70% health", "While above 60% health", "8233:"),
        (8236, "10 min : + 8 AP", "10 min : + 9 AP", "8236: the 10 min row"),
        (8437, "3.5% of your max health", "4% of your max health", "8437:"),
    ],
)
def test_checker_flags_a_planted_drift(live, rid, old, new, needle) -> None:
    flat_old = _flat(old)
    assert flat_old in _flat(live[rid])
    planted = dict(live)
    planted[rid] = _flat(live[rid]).replace(flat_old, _flat(new), 1)
    assert any(m.startswith(needle) for m in parity_mismatches(planted)), parity_mismatches(planted)


def _mutations() -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for rid in sorted(RUNE_PROCS):
        names = ["cooldown+1"]
        stated = _STATED[rid][1]
        if rid != 9923:
            names.append("+0.5")
            if rid not in _ZERO:
                names.append("x1.01@18")
        names.extend(f"+0.01*{name}" for name in _PROBES if rid != 9923 or name not in stated)
        out.extend((rid, name) for name in names)
    return out


def _mutated(proc, name: str):
    orig = proc.compute
    if name == "cooldown+1":
        return dataclasses.replace(proc, cooldown_s=proc.cooldown_s + 1.0)
    if name == "+0.5":

        def compute(**kw):
            return orig(**kw) + 0.5

    elif name == "x1.01@18":

        def compute(**kw):
            return orig(**kw) * (1.01 if float(kw.get("level", 1.0)) >= 18.0 else 1.0)

    else:
        stat = name.removeprefix("+0.01*")

        def compute(**kw):
            return orig(**kw) + 0.01 * float(kw.get(stat, 0.0))

    return dataclasses.replace(proc, compute=compute)


@pytest.mark.parametrize(("rid", "name"), _mutations())
def test_checker_catches_every_sweep_mutation(live, monkeypatch, rid, name) -> None:
    assert parity_mismatches(live) == []
    monkeypatch.setitem(RUNE_PROCS, rid, _mutated(RUNE_PROCS[rid], name))
    assert any(m.startswith(f"{rid}:") for m in parity_mismatches(live)), (rid, name)


def test_the_sweep_covers_every_id_and_input() -> None:
    swept = _mutations()
    assert {rid for rid, _n in swept} == set(RUNE_PROCS)
    for rid in RUNE_PROCS:
        names = {n for r, n in swept if r == rid}
        assert "cooldown+1" in names
        expected = {f"+0.01*{p}" for p in _PROBES}
        if rid == 9923:
            expected -= {"+0.01*ad", "+0.01*ap"}
        else:
            expected.add("+0.5")
            if rid not in _ZERO:
                expected.add("x1.01@18")
        assert names == expected | {"cooldown+1"}, rid


def test_checker_flags_a_missing_shape(live) -> None:
    planted = dict(live)
    planted[8143] = "No damage here."
    assert "8143: live shape not found" in parity_mismatches(planted)
