"""S144-D-397: the rune_procs prose matches the vendored DDragon feeds.

Measured at patch 16.22.1 (ENGINE 1.291.0) against the vendored
``runesReforged.json`` snapshots under ``data/meta_build/ddragon/``.

Four pieces of ``agents/daemon_slayer/rune_procs.py`` prose are pinned WHOLE,
whitespace aside (compared after collapsing whitespace runs to one space), so
an edited, dropped or inserted sentence anywhere in them fails:

- the module docstring's "Re-checked at" paragraph;
- the comment block inside ``_hail_of_blades``;
- the comment block inside ``_gathering_storm``;
- the module-level comment block that starts "Honest exclusion (NOT in
  RUNE_PROCS): Fleet Footwork 8021".

The Hail of Blades ``formula`` string must end with its staleness note.

In the sentences S144-D-397 added, every patch and every quoted live number
is derived from the vendored feeds, never typed: the oldest snapshot, the
newest one (which must be the one ``data/daemon_slayer/current.txt`` names),
the patch where 9923 and 8021 first changed, the live 9923 on-hit, the live
and old 8021 heal, and the live Gathering Storm 30 min AD. The text the
blocks already carried is pinned as literal text. The code facts the added
sentences state are asserted too: every modeled rune but 9923 has one
longDesc across every snapshot and 9923 does not; 9923 still computes the
oldest snapshot's on-hit; no DS registry models the 8021 heal; Gathering
Storm's closure matches only the feed's 10 min row; ``_rune_offense_grants``
carries the feed's step table; ``burst.py`` and ``fight_report.py`` (the only
DS modules that import ``compute_rune_proc_damage``) keep ``adaptive`` procs
out of their burst totals. Both test files the docstring cites resolve.

No closure changed, so every scorer output is byte-identical.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import rune_procs
from agents.daemon_slayer.rune_procs import RUNE_PROCS, compute_rune_proc_damage
from agents.daemon_slayer.tests.test_rune_hsp_resist_shield_live_text_s144d386 import (
    _CURRENT_TXT,
    _DDRAGON_ROOT,
    _REPO_ROOT,
    _spaced,
    _vendored,
)

_TAG_RE = re.compile(r"<[^>]+>")
_DS_DIR = Path(rune_procs.__file__).resolve().parent


@pytest.fixture(scope="module")
def vendored() -> dict[str, dict[int, tuple[str, str, str]]]:
    if not _DDRAGON_ROOT.is_dir():
        pytest.skip("no vendored DDragon snapshots")
    return _vendored()


@pytest.fixture(scope="module")
def order(vendored) -> list[str]:
    return sorted(vendored, key=lambda p: tuple(int(x) for x in p.split(".")))


@pytest.fixture(scope="module")
def live(vendored, order) -> dict[int, str]:
    patch = _CURRENT_TXT.read_text(encoding="utf-8").strip()
    assert patch == order[-1], (patch, order[-1])
    return {rid: row[2] for rid, row in vendored[patch].items()}


def _text(desc: str) -> str:
    return _spaced(_TAG_RE.sub(" ", desc))


def _first_change(vendored, order, rid: int) -> str:
    changed = [p for p in order if vendored[p][rid][2] != vendored[order[0]][rid][2]]
    assert changed, rid
    return changed[0]


def _hail_on_hit(desc: str) -> str:
    m = re.search(r"On-Hit Damage: (\d+ - \d+ \(\+[\d.]+ bonus AD, \+[\d.]+ AP\))", _text(desc))
    assert m, desc
    return m.group(1)


def _comment_lines_of(func) -> list[str]:
    """The ``#`` lines of ``func``; they must form ONE contiguous block."""
    lines = inspect.getsource(func).splitlines()
    idx = [i for i, line in enumerate(lines) if line.strip().startswith("#")]
    assert idx, func.__name__
    assert idx == list(range(idx[0], idx[-1] + 1)), func.__name__
    return [lines[i] for i in idx]


def _module_block(anchor: str) -> list[str]:
    """The contiguous module-level ``#`` block that starts with ``anchor``."""
    lines = Path(rune_procs.__file__).read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(f"# {anchor}")]
    assert len(starts) == 1, starts
    start = starts[0]
    assert not lines[start - 1].startswith("#"), "the block must start at the anchor"
    end = start
    while end < len(lines) and lines[end].startswith("#"):
        end += 1
    return lines[start:end]


def _importers(name: str) -> list[str]:
    """Every DS module (``rune_procs.py`` aside) that imports ``name``."""
    out = []
    for path in sorted(_DS_DIR.glob("*.py")):
        if path.name == "rune_procs.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.ImportFrom) and any(alias.name == name for alias in node.names)
            for node in ast.walk(tree)
        ):
            out.append(path.name)
    return out


def _uncomment(lines: list[str]) -> str:
    return _spaced(" ".join(line.strip().removeprefix("#") for line in lines))


# ---- the docstring paragraph ---------------------------------------------------


def test_docstring_paragraph_is_pinned_whole(vendored, order, live) -> None:
    doc = rune_procs.__doc__ or ""
    paragraphs = [_spaced(p) for p in doc.split("\n\n") if p.strip().startswith("Re-checked at")]
    assert len(paragraphs) == 1
    low, high = order[0], order[-1]
    expected = (
        f"Re-checked at {high} (S144-D-397): the longDesc of every modeled rune except Hail of Blades 9923 "
        f"is identical in every vendored snapshot {low}..{high}, so its DDragon quote below is still the "
        f"live text. Hail of Blades 9923 changed at {_first_change(vendored, order, 9923)} "
        f'(on-hit "{_hail_on_hit(live[9923])}"); the closure still computes the {low} numbers, filed as '
        "S144-D-394 (Tier-2 re-seed). The Fleet Footwork 8021 exclusion quote changed at "
        f"{_first_change(vendored, order, 8021)}; its comment below quotes both texts. The closures are "
        "checked against the live text by "
        "``agents/daemon_slayer/tests/test_rune_procs_live_text_s144d395.py`` (its docstring names what "
        "it does not check), and this paragraph plus the Hail of Blades, Gathering Storm and Fleet "
        "Footwork comment blocks by "
        f"``{Path(__file__).resolve().relative_to(_REPO_ROOT).as_posix()}``."
    )
    assert paragraphs[0] == expected


def test_docstring_unchanged_claim_is_true(vendored, order) -> None:
    for rid in RUNE_PROCS:
        texts = {vendored[p][rid][2] for p in order}
        if rid == 9923:
            assert len(texts) > 1
        else:
            assert len(texts) == 1, rid


def test_docstring_cited_tests_resolve() -> None:
    cited = re.findall(r"``(agents/daemon_slayer/tests/\w+\.py)``", rune_procs.__doc__ or "")
    assert len(cited) == 2, cited
    for cite in cited:
        assert (_REPO_ROOT / Path(*cite.split("/"))).is_file(), cite
    assert Path(__file__).resolve().relative_to(_REPO_ROOT).as_posix() in cited


# ---- Hail of Blades ----------------------------------------------------------


def test_hail_of_blades_still_computes_the_oldest_snapshot(vendored, order) -> None:
    got = re.search(
        r"(\d+) - (\d+) \(\+([\d.]+) bonus AD, \+([\d.]+) AP\)",
        _hail_on_hit(vendored[order[0]][9923][2]),
    )
    assert got
    lo, hi, ad, ap = (float(g) for g in got.groups())
    base = compute_rune_proc_damage(9923, 1.0)
    assert base == pytest.approx(lo)
    assert compute_rune_proc_damage(9923, 18.0) == pytest.approx(hi)
    assert compute_rune_proc_damage(9923, 1.0, ad=100.0) - base == pytest.approx(100.0 * ad)
    assert compute_rune_proc_damage(9923, 1.0, ap=100.0) - base == pytest.approx(100.0 * ap)


def test_hail_of_blades_comment_block_is_pinned_whole(vendored, order, live) -> None:
    old = _hail_on_hit(vendored[order[0]][9923][2])
    expected = (
        f'DDragon 16.11.1 longDesc: "On-Hit Damage: {old} damage" as TRUE damage, up to 3 attacks, CD 10s. '
        'This is ADDITIVE (BOTH 0.08 bonus AD AND 0.06 AP per the "+0.08 bonus AD, +0.06 AP" wording) - '
        'NOT adaptive. Returns the per-AA (single-attack) contribution; the "up to 3 attacks" multiplier '
        "is the caller's concern (do NOT multiply by 3 here). Item 232: role accepted for signature "
        "parity with Lethal Tempo, but Hail of Blades' On-Hit Damage does NOT vary by role (DDragon "
        "gives one number, not a melee||ranged split), so role is unused and the melee default value "
        f"is byte-identical. STALE from {_first_change(vendored, order, 9923)}: the live on-hit reads "
        f'"{_hail_on_hit(live[9923])}". The re-seed is Tier-2 (ENGINE_VERSION bump), filed as S144-D-394.'
    )
    assert order[0] == "16.11.1"
    assert _uncomment(_comment_lines_of(rune_procs._hail_of_blades)) == expected


def test_hail_of_blades_formula_names_the_staleness(vendored, order) -> None:
    changed = _first_change(vendored, order, 9923)
    tail = f"(DDragon {order[0]}; the live text changed at {changed}, re-seed filed as S144-D-394)"
    assert _spaced(RUNE_PROCS[9923].formula).endswith(tail)


# ---- Gathering Storm -----------------------------------------------------------


def _storm_rows(desc: str) -> list[tuple[float, float, float]]:
    """(minute, AD, AP) per row of the live step table."""
    rows = re.findall(r"(\d+) min\s*:\s*\+\s*(\d+) AP or (\d+) AD", _text(desc))
    return [(float(minute), float(ad), float(ap)) for minute, ap, ad in rows]


def test_gathering_storm_comment_block_is_pinned_whole(live) -> None:
    rows = _storm_rows(live[8236])
    assert len(rows) >= 3
    first_minute, third_minute, third_ad = rows[0][0], rows[2][0], rows[2][1]
    expected = (
        'DDragon 16.11.1 longDesc: "Every 10 min gain AP or AD, adaptive. 10 min: +8 AP or 5 AD 20 min: '
        "+24 AP or 14 AD 30 min: +48 AP or 29 AD 40 min: +80 AP or 48 AD 50 min: +120 AP or 72 AD 60 "
        'min: +168 AP or 101 AD." A game-time-gated adaptive STAT GRANT (not proc damage). proc_type '
        '"adaptive" -> the BURST CONSUMER SKIPS it (does NOT enter the burst total) -> burst '
        "BYTE-IDENTICAL. Modeled as the AD-side 5-per-10-min / AP-side 8-per-10-min linear ramp "
        "(game_time_s / 600.0 * milestone); the longDesc accelerates at later milestones but the 10-min "
        "cadence anchor is the honest first-order ramp. At the DEFAULT game_time_s=0.0 -> 0.0 (a burst "
        "scorer at t=0 has the rune contribute nothing, matching the exclusion). game_time_s=600 (10 "
        "min) -> 5 AD (AD-side); game_time_s=1800 (30 min) -> 15 AD. AD-side on the default ad>=ap tie. "
        f"Only the {first_minute:g}-min row matches the feed: it is a STEP table ({third_ad:g} AD at "
        f"{third_minute:g} min, nothing before {first_minute:g} min), which ``_rune_offense_grants`` "
        "transcribes for the sustained scorers. This ramp never reaches a burst total."
    )
    assert _uncomment(_comment_lines_of(rune_procs._gathering_storm)) == expected


def test_gathering_storm_code_facts(live) -> None:
    from agents.daemon_slayer import _rune_offense_grants, fight_report

    rows = _storm_rows(live[8236])
    assert tuple(rows) == _rune_offense_grants._GATHERING_STORM_STEPS
    first_minute, first_ad, _ap = rows[0]
    assert compute_rune_proc_damage(8236, 1.0, game_time_s=60.0 * first_minute) == pytest.approx(first_ad)
    for minute, ad, _ap in rows[1:]:
        assert compute_rune_proc_damage(8236, 1.0, game_time_s=60.0 * minute) != pytest.approx(ad), minute
    assert compute_rune_proc_damage(8236, 1.0, game_time_s=60.0 * first_minute - 60.0) > 0.0
    assert RUNE_PROCS[8236].proc_type == "adaptive"
    assert _importers("compute_rune_proc_damage") == ["burst.py", "fight_report.py"]
    burst = _spaced((_DS_DIR / "burst.py").read_text(encoding="utf-8"))
    assert 'proc = RUNE_PROCS.get(_rid) if proc is None or proc.proc_type == "adaptive": continue' in burst
    assert "adaptive" not in fight_report._BURST_PROC_TYPES
    report = _spaced((_DS_DIR / "fight_report.py").read_text(encoding="utf-8"))
    assert report.count("rune_burst_total +=") == 1
    assert 'if entry["proc_type"] in _BURST_PROC_TYPES: rune_burst_total += val' in report


# ---- Fleet Footwork --------------------------------------------------------------


def test_fleet_footwork_comment_block_is_pinned_whole(vendored, order, live) -> None:
    sentence = re.search(r"Energized attacks heal you for .*?for 1s\.", _text(live[8021]))
    assert sentence
    old_heal = re.search(r"heal you for (\d+ - \d+)", _text(vendored[order[0]][8021][2]))
    assert old_heal
    old = [p for p in order if old_heal.group(1) in vendored[p][8021][2]]
    new = [p for p in order if vendored[p][8021][2] == live[8021]]
    assert old + new == order
    assert new[0] == _first_change(vendored, order, 8021)
    expected = (
        "Honest exclusion (NOT in RUNE_PROCS): Fleet Footwork 8021 (Precision). "
        f'DDragon {new[0]} onward longDesc: "{sentence.group(0)}" ({old[0]}..{old[-1]} read '
        f'"{old_heal.group(1)}"; no registry models this heal.) It is a HEAL + MOVE SPEED sustain '
        "keystone with NO damage component - modeling it as a damage rune would invent numbers that do "
        "not exist. Same data-availability-ceiling discipline as the Summon Aery shield side "
        "(mitigation, not burst) and the Grasp heal side (heal + permanent-HP not modeled): we only "
        "register the DAMAGE a rune deals. Do NOT add 8021 to RUNE_PROCS as a burst rune."
    )
    assert _uncomment(_module_block("Honest exclusion (NOT in RUNE_PROCS): Fleet Footwork 8021")) == expected


def test_no_ds_registry_models_the_fleet_footwork_heal() -> None:
    from agents.daemon_slayer import _rune_offense_grants, _rune_self_heal

    holders = sorted(p.name for p in _DS_DIR.glob("*.py") if "8021" in p.read_text(encoding="utf-8"))
    assert holders == ["_rune_offense_grants.py", "rune_procs.py"]
    assert 8021 not in RUNE_PROCS
    assert "8021" not in _rune_self_heal._RUNE_SELF_HEAL
    assert "8021" in _rune_offense_grants._ADJUDICATED_NON_GRANTS
