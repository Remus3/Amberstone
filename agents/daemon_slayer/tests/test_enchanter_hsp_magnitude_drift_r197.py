"""R197 - DERIVED drift guard for curated enchanter Heal-and-Shield-Power magnitudes.

Why this file exists
--------------------
``data/daemon_slayer/<patch>/enchanter_items.json`` carries 34 hand-curated rows.
Their ``heal_shield_amp_pct`` values were typed in by hand at R143 and re-typed by
hand across six later passes. Every existing test pins those numbers as LITERALS
(see ``test_hsp_mirror_ids_r143.py`` TRUTH), which means a patch refresh that moves
a printed magnitude leaves the literals and the curated JSON agreeing with each
other while both silently disagree with the shipped DDragon snapshot. Agreement
between two hand-typed copies is not evidence.

This guard is DERIVED: it re-extracts the printed percent straight out of the
``items.json`` DDragon description that ships in the SAME patch directory and
compares it to the curated row. A patch bump that changes a printed magnitude now
goes RED with the id and both values named, instead of rotting.

R161 doctrine B - a mirror credits its OWN data line
----------------------------------------------------
Arena (``22<base>``) and SR/ARAM (``32<base>``) mirrors are separate DDragon
entries with independently balanced stat lines. Redemption is 10 / 12 / 10,
Mikael's is 12 / 12 / 15, Dawncore is 16 / 12 / 20 across base / arena / aram.
The mirror-asymmetry test below asserts each mirror matches ITS OWN entry and
proves the check is load-bearing by requiring genuine asymmetry to be present -
so it cannot go green by finding all three ids equal.

The extraction helper reads the ``<stats>`` block, not the whole description.
Dawncore's First Light passive also prints "2% Heal and Shield Power" as a
conditional grant per 100% Base Mana Regen; that is not the flat printed stat.

Nothing here writes to disk. The self-tests mutate deep copies in memory.
"""
from __future__ import annotations

import json
import re
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

# Curated row count when this guard was authored. Adding or removing an enchanter
# row is a deliberate act - bump this literal in the same commit that does it.
EXPECTED_CURATED_ROWS = 34

ARENA_PREFIX = "22"
ARAM_PREFIX = "32"
_MIRROR_PREFIXES = (ARENA_PREFIX, ARAM_PREFIX)

_TAG_RE = re.compile(r"<[^>]+>")
_STATS_RE = re.compile(r"<stats>(.*?)</stats>", re.DOTALL | re.IGNORECASE)
_HSP_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*Heal\s+and\s+Shield\s+Power", re.IGNORECASE)

# Entity decode runs AFTER tag stripping so a decoded &lt; can never look like a tag.
_ENTITIES = (
    ("&nbsp;", " "),
    ("\xa0", " "),
    ("&amp;", "&"),
    ("&lt;", "<"),
    ("&gt;", ">"),
    ("&quot;", '"'),
    ("&#39;", "'"),
)

TOLERANCE = 1e-9


# ---------------------------------------------------------------------------
# Module-level pure helpers (no disk access, no fixtures)
# ---------------------------------------------------------------------------
def plain_text(fragment: Optional[str]) -> str:
    """Flatten a DDragon markup fragment to single-spaced plain text."""
    if not fragment:
        return ""
    out = _TAG_RE.sub(" ", fragment)
    for src, dst in _ENTITIES:
        out = out.replace(src, dst)
    return re.sub(r"\s+", " ", out).strip()


def extract_printed_hsp_pct(description: Optional[str]) -> Optional[float]:
    """Return the printed Heal and Shield Power percent, or None if none is printed.

    Prefers the ``<stats>`` block, which is where DDragon prints the flat stat
    line. Passive prose that mentions Heal and Shield Power (Dawncore First Light)
    is a conditional grant and is deliberately NOT the value this guard pins.
    Returns a percent in printed units - 16.0 for "16% Heal and Shield Power".
    """
    if not description:
        return None
    block = _STATS_RE.search(description)
    segment = block.group(1) if block is not None else description
    match = _HSP_RE.search(plain_text(segment))
    if match is None:
        return None
    return float(match.group(1))


def curated_pct(curated_row: Dict) -> float:
    """Curated unit-fraction amp for a row (0.10 = 10%). Missing key reads 0.0."""
    return float(curated_row.get("heal_shield_amp_pct", 0.0) or 0.0)


def is_ally_chain_only(curated_row: Dict) -> bool:
    """Read the optional ally_chain_only flag without ever writing it back."""
    return bool(curated_row.get("ally_chain_only", False))


def assert_row_matches_ddragon(
    item_id: str,
    curated_row: Dict,
    ddragon_entry: Optional[Dict],
) -> None:
    """Raise AssertionError when a curated magnitude disagrees with its OWN DDragon line.

    This is the whole guard for a single id. Both the live test and the self-test
    call it, so proving it can raise proves the shipped assertion can go red.
    """
    if not ddragon_entry:
        raise AssertionError(
            f"curated enchanter id {item_id} does not resolve in the DDragon items snapshot"
        )
    name = curated_row.get("name") or ddragon_entry.get("name") or "<unnamed>"
    curated = curated_pct(curated_row)
    printed = extract_printed_hsp_pct(ddragon_entry.get("description", ""))

    if printed is None:
        if curated == 0.0 or is_ally_chain_only(curated_row):
            return
        raise AssertionError(
            f"id {item_id} ({name}) carries curated heal_shield_amp_pct {curated!r} but "
            "DDragon prints NO Heal and Shield Power stat line and the row is not "
            "flagged ally_chain_only"
        )

    expected = printed / 100.0
    if abs(curated - expected) > TOLERANCE:
        raise AssertionError(
            f"HSP MAGNITUDE DRIFT id {item_id} ({name}): curated {curated!r} vs DDragon "
            f"printed {_fmt_pct(printed)}% (expected {expected!r}) - the shipped patch "
            "moved and the curated row did not"
        )


def _fmt_pct(value: float) -> str:
    """Render a printed percent without a trailing .0 on whole numbers."""
    return f"{value:g}"


def is_mirror_id(item_id: str, curated: Dict[str, Dict]) -> bool:
    """True when item_id is a 22xxxx / 32xxxx mirror of another curated base id."""
    for prefix in _MIRROR_PREFIXES:
        if item_id.startswith(prefix):
            remainder = item_id[len(prefix):]
            if len(remainder) >= 4 and remainder in curated:
                return True
    return False


def base_ids(curated: Dict[str, Dict]) -> List[str]:
    """Curated ids that are not themselves a mirror, in numeric order."""
    return sorted(
        (iid for iid in curated if not is_mirror_id(iid, curated)),
        key=int,
    )


def mirror_triple_ids(base_id: str) -> Tuple[Tuple[str, str], ...]:
    """The (label, id) pairs of a base / arena / aram triple - existence not checked."""
    return (
        ("base", base_id),
        ("arena", ARENA_PREFIX + base_id),
        ("aram", ARAM_PREFIX + base_id),
    )


def triple_rows(
    base_id: str,
    curated: Dict[str, Dict],
    ddragon: Dict[str, Dict],
) -> List[Tuple[str, str, float, Optional[float]]]:
    """(label, id, curated_unit_fraction, printed_percent_or_None) for present rows."""
    rows = []
    for label, iid in mirror_triple_ids(base_id):
        if iid not in curated:
            continue
        entry = ddragon.get(iid) or {}
        rows.append(
            (
                label,
                iid,
                curated_pct(curated[iid]),
                extract_printed_hsp_pct(entry.get("description", "")),
            )
        )
    return rows


def triple_is_asymmetric(rows: List[Tuple[str, str, float, Optional[float]]]) -> bool:
    """True when the triple's DDragon PRINTED magnitudes are not all identical."""
    printed = {row[3] for row in rows}
    return len(printed) > 1


# ---------------------------------------------------------------------------
# Disk loaders (patch-agnostic - the patch comes from current.txt)
# ---------------------------------------------------------------------------
def current_patch() -> str:
    return (_DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()


def load_curated_items(patch: Optional[str] = None) -> Dict[str, Dict]:
    path = _DATA_ROOT / (patch or current_patch()) / "enchanter_items.json"
    return json.loads(path.read_text(encoding="utf-8"))["items"]


def load_ddragon_items(patch: Optional[str] = None) -> Dict[str, Dict]:
    path = _DATA_ROOT / (patch or current_patch()) / "items.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


# Base / arena / aram printed percents that MUST stay asymmetric for the
# mirror-doctrine test to be load-bearing. Measured from the shipped snapshot.
EXPECTED_ASYMMETRIC_TRIPLES: Tuple[Tuple[str, str, float, float, float], ...] = (
    ("3107", "Redemption", 10.0, 12.0, 10.0),
    ("3222", "Mikael's Blessing", 12.0, 12.0, 15.0),
    ("6621", "Dawncore", 16.0, 12.0, 20.0),
)
MIN_ASYMMETRIC_TRIPLES = 3


class PrintedHspExtractorTests(unittest.TestCase):
    """Unit-level proof that the helper handles the markup shapes DDragon ships."""

    def test_reads_percent_out_of_the_stats_block(self) -> None:
        desc = (
            "<mainText><stats><attention>45</attention> Ability Power<br>"
            "<attention>16%</attention> Heal and Shield Power</stats></mainText>"
        )
        self.assertAlmostEqual(extract_printed_hsp_pct(desc), 16.0, places=9)

    def test_passive_prose_does_not_shadow_the_printed_stat(self) -> None:
        # Dawncore prints 16% flat and grants a further 2% conditionally.
        desc = (
            "<mainText><stats><attention>16%</attention> Heal and Shield Power</stats>"
            "<br><passive>First Light</passive><br>Gain "
            "<healing>2% Heal and Shield Power</healing> per 100% Base Mana Regen.</mainText>"
        )
        self.assertAlmostEqual(extract_printed_hsp_pct(desc), 16.0, places=9)

    def test_handles_nbsp_and_runaway_whitespace(self) -> None:
        desc = (
            "<mainText><stats><attention>12%</attention>&nbsp;&nbsp;Heal\n\n and   Shield\tPower"
            "</stats></mainText>"
        )
        self.assertAlmostEqual(extract_printed_hsp_pct(desc), 12.0, places=9)

    def test_handles_a_decimal_magnitude(self) -> None:
        desc = "<stats><attention>7.5%</attention> Heal and Shield Power</stats>"
        self.assertAlmostEqual(extract_printed_hsp_pct(desc), 7.5, places=9)

    def test_returns_none_when_no_hsp_line_is_printed(self) -> None:
        locket = (
            "<mainText><stats><attention>200</attention> Health<br>"
            "<attention>30</attention> Armor</stats><br><active>Devotion</active><br>"
            "Grant nearby allies a <shield>290 - 360 Shield</shield>.</mainText>"
        )
        self.assertIsNone(extract_printed_hsp_pct(locket))
        self.assertIsNone(extract_printed_hsp_pct(""))
        self.assertIsNone(extract_printed_hsp_pct(None))

    def test_bare_percent_without_a_number_is_not_a_magnitude(self) -> None:
        # Whispering Circlet's Harmony passive literally reads "Gain % Heal and
        # Shield Power" with no number - that must never parse as a value.
        self.assertIsNone(extract_printed_hsp_pct("<stats>Gain % Heal and Shield Power</stats>"))

    def test_falls_back_to_the_whole_description_without_a_stats_block(self) -> None:
        self.assertAlmostEqual(
            extract_printed_hsp_pct("<healing>9% Heal and Shield Power</healing>"),
            9.0,
            places=9,
        )

    def test_plain_text_collapses_markup_and_entities(self) -> None:
        self.assertEqual(plain_text("<b>a</b>&nbsp;&amp;\n b"), "a & b")
        self.assertEqual(plain_text(None), "")


class CuratedMagnitudeDerivedFromDdragonTests(unittest.TestCase):
    """Requirement 2 - every curated row is re-derived from its own DDragon line."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = current_patch()
        cls.curated = load_curated_items(cls.patch)
        cls.ddragon = load_ddragon_items(cls.patch)

    def test_every_curated_magnitude_matches_its_ddragon_line(self) -> None:
        for item_id in sorted(self.curated, key=int):
            row = self.curated[item_id]
            with self.subTest(item_id=item_id, name=row.get("name")):
                assert_row_matches_ddragon(item_id, row, self.ddragon.get(item_id))

    def test_zero_magnitude_rows_really_print_no_hsp_line(self) -> None:
        # The inverse direction: a row curated 0.0 must not be sitting on top of a
        # printed magnitude that a patch quietly introduced.
        for item_id in sorted(self.curated, key=int):
            row = self.curated[item_id]
            if curated_pct(row) != 0.0:
                continue
            entry = self.ddragon.get(item_id) or {}
            printed = extract_printed_hsp_pct(entry.get("description", ""))
            shown = _fmt_pct(printed) if printed is not None else "?"
            with self.subTest(item_id=item_id, name=row.get("name")):
                self.assertIsNone(
                    printed,
                    f"id {item_id} ({row.get('name')}) is curated 0.0 but DDragon now "
                    f"prints {shown}% Heal and Shield Power",
                )

    def test_ally_chain_only_escape_is_used_by_moonstone_only(self) -> None:
        # The chain-only escape hatch bypasses the printed-line comparison, so it
        # must stay narrow. Moonstone's 30% is a chain ratio, not an HSP stat.
        flagged = sorted(
            (iid for iid, row in self.curated.items() if is_ally_chain_only(row)),
            key=int,
        )
        self.assertEqual(flagged, ["6617", "226617", "326617"])
        for iid in flagged:
            with self.subTest(item_id=iid):
                entry = self.ddragon.get(iid) or {}
                self.assertIsNone(extract_printed_hsp_pct(entry.get("description", "")))


class MirrorAsymmetryDoctrineTests(unittest.TestCase):
    """Requirement 3 - R161 doctrine B: a mirror credits its OWN data line."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = current_patch()
        cls.curated = load_curated_items(cls.patch)
        cls.ddragon = load_ddragon_items(cls.patch)

    def test_each_mirror_matches_its_own_entry_not_the_base_entry(self) -> None:
        for base in base_ids(self.curated):
            rows = triple_rows(base, self.curated, self.ddragon)
            base_printed = rows[0][3] if rows else None
            for label, iid, curated_value, printed in rows:
                with self.subTest(base=base, label=label, item_id=iid):
                    assert_row_matches_ddragon(iid, self.curated[iid], self.ddragon.get(iid))
                    if label == "base" or printed is None or base_printed is None:
                        continue
                    if printed == base_printed:
                        continue
                    self.assertAlmostEqual(curated_value, printed / 100.0, places=9)
                    self.assertNotAlmostEqual(
                        curated_value,
                        base_printed / 100.0,
                        places=9,
                        msg=f"mirror {iid} was credited the BASE magnitude "
                        f"{_fmt_pct(base_printed)}% instead of its own "
                        f"{_fmt_pct(printed)}% - that is the R161 doctrine B violation",
                    )

    def test_named_asymmetric_triples_are_still_asymmetric(self) -> None:
        for base, name, want_base, want_arena, want_aram in EXPECTED_ASYMMETRIC_TRIPLES:
            with self.subTest(base=base, name=name):
                rows = {row[0]: row for row in triple_rows(base, self.curated, self.ddragon)}
                self.assertEqual(sorted(rows), ["aram", "arena", "base"])
                self.assertAlmostEqual(rows["base"][3], want_base, places=9)
                self.assertAlmostEqual(rows["arena"][3], want_arena, places=9)
                self.assertAlmostEqual(rows["aram"][3], want_aram, places=9)
                self.assertTrue(
                    triple_is_asymmetric(list(rows.values())),
                    f"{base} ({name}) collapsed to a symmetric triple - the mirror "
                    "doctrine test would now pass vacuously",
                )

    def test_enough_triples_are_genuinely_asymmetric(self) -> None:
        asymmetric = [
            base
            for base in base_ids(self.curated)
            if triple_is_asymmetric(triple_rows(base, self.curated, self.ddragon))
        ]
        self.assertGreaterEqual(
            len(asymmetric),
            MIN_ASYMMETRIC_TRIPLES,
            f"only {len(asymmetric)} asymmetric mirror triples found ({asymmetric}) - "
            f"below the {MIN_ASYMMETRIC_TRIPLES} needed for this guard to be load-bearing",
        )


class CuratedPopulationTests(unittest.TestCase):
    """Requirement 4 - the population itself is pinned and fully resolvable."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = current_patch()
        cls.curated = load_curated_items(cls.patch)
        cls.ddragon = load_ddragon_items(cls.patch)

    def test_curated_row_count_is_pinned(self) -> None:
        self.assertEqual(
            len(self.curated),
            EXPECTED_CURATED_ROWS,
            f"enchanter_items.json now holds {len(self.curated)} rows, guard expects "
            f"{EXPECTED_CURATED_ROWS} - bump EXPECTED_CURATED_ROWS in the same commit "
            "that adds or drops a row",
        )

    def test_every_curated_id_resolves_in_ddragon(self) -> None:
        missing = sorted((iid for iid in self.curated if iid not in self.ddragon), key=int)
        self.assertEqual(
            missing,
            [],
            f"curated enchanter ids absent from the {self.patch} DDragon snapshot: {missing}",
        )

    def test_patch_pointer_drives_the_load(self) -> None:
        # Patch-agnostic: nothing here hardcodes a patch label.
        patch = current_patch()
        self.assertTrue(patch)
        self.assertTrue((_DATA_ROOT / patch / "enchanter_items.json").is_file())
        self.assertTrue((_DATA_ROOT / patch / "items.json").is_file())

    def test_curated_meta_patch_matches_the_pointer(self) -> None:
        payload = json.loads(
            (_DATA_ROOT / self.patch / "enchanter_items.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["_meta"]["patch"], self.patch)


class GuardSelfTests(unittest.TestCase):
    """Proof the guard can FAIL. All mutation happens on in-memory deep copies."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = current_patch()
        cls.curated = load_curated_items(cls.patch)
        cls.ddragon = load_ddragon_items(cls.patch)

    def test_control_unmutated_rows_do_not_raise(self) -> None:
        for iid in ("3107", "223107", "6621", "6617", "3190"):
            with self.subTest(item_id=iid):
                assert_row_matches_ddragon(iid, self.curated[iid], self.ddragon[iid])

    def test_mutated_ddragon_printed_magnitude_goes_red(self) -> None:
        entry = deepcopy(self.ddragon["6621"])
        entry["description"] = entry["description"].replace(
            "<attention>16%</attention> Heal and Shield Power",
            "<attention>18%</attention> Heal and Shield Power",
        )
        self.assertAlmostEqual(extract_printed_hsp_pct(entry["description"]), 18.0, places=9)
        with self.assertRaises(AssertionError) as ctx:
            assert_row_matches_ddragon("6621", self.curated["6621"], entry)
        message = str(ctx.exception)
        self.assertIn("6621", message)
        self.assertIn("0.16", message)
        self.assertIn("18%", message)

    def test_mutated_curated_magnitude_goes_red(self) -> None:
        row = deepcopy(self.curated["3107"])
        row["heal_shield_amp_pct"] = 0.11
        with self.assertRaises(AssertionError) as ctx:
            assert_row_matches_ddragon("3107", row, self.ddragon["3107"])
        self.assertIn("MAGNITUDE DRIFT", str(ctx.exception))
        self.assertIn("Redemption", str(ctx.exception))

    def test_a_disappearing_printed_line_goes_red_for_a_nonzero_row(self) -> None:
        entry = deepcopy(self.ddragon["3222"])
        entry["description"] = entry["description"].replace(
            "Heal and Shield Power", "Ability Haste"
        )
        self.assertIsNone(extract_printed_hsp_pct(entry["description"]))
        with self.assertRaises(AssertionError) as ctx:
            assert_row_matches_ddragon("3222", self.curated["3222"], entry)
        self.assertIn("prints NO", str(ctx.exception))

    def test_a_missing_ddragon_entry_goes_red_with_the_id_named(self) -> None:
        with self.assertRaises(AssertionError) as ctx:
            assert_row_matches_ddragon("999999", {"name": "Ghost Item"}, None)
        self.assertIn("999999", str(ctx.exception))

    def test_a_mirror_credited_from_the_base_line_goes_red(self) -> None:
        # Arena Redemption prints 12%; retyping the SR 10% onto it is exactly the
        # R161 doctrine B violation this suite exists to catch.
        row = deepcopy(self.curated["223107"])
        row["heal_shield_amp_pct"] = curated_pct(self.curated["3107"])
        with self.assertRaises(AssertionError) as ctx:
            assert_row_matches_ddragon("223107", row, self.ddragon["223107"])
        self.assertIn("223107", str(ctx.exception))
        self.assertIn("12%", str(ctx.exception))

    def test_the_chain_only_escape_does_not_swallow_a_printed_drift(self) -> None:
        # Moonstone is chain-only today. If a patch ever prints an HSP stat on it,
        # the 0.30 chain ratio must NOT be waved through as if it were that stat.
        entry = deepcopy(self.ddragon["6617"])
        entry["description"] = entry["description"].replace(
            "<stats>", "<stats><attention>10%</attention> Heal and Shield Power<br>"
        )
        self.assertAlmostEqual(extract_printed_hsp_pct(entry["description"]), 10.0, places=9)
        with self.assertRaises(AssertionError) as ctx:
            assert_row_matches_ddragon("6617", self.curated["6617"], entry)
        self.assertIn("MAGNITUDE DRIFT", str(ctx.exception))

    def test_asymmetry_detector_rejects_a_flattened_triple(self) -> None:
        # If a future patch made all three Dawncore entries print the same value,
        # triple_is_asymmetric must report False so the named-triple test goes red
        # rather than passing vacuously.
        flat = [
            ("base", "6621", 0.16, 16.0),
            ("arena", "226621", 0.16, 16.0),
            ("aram", "326621", 0.16, 16.0),
        ]
        self.assertFalse(triple_is_asymmetric(flat))
        live = triple_rows("6621", self.curated, self.ddragon)
        self.assertTrue(triple_is_asymmetric(live))

    def test_mirror_id_classification(self) -> None:
        self.assertTrue(is_mirror_id("223107", self.curated))
        self.assertTrue(is_mirror_id("323107", self.curated))
        self.assertFalse(is_mirror_id("3107", self.curated))
        # 3222 starts with "32" but "22" is not a curated base id.
        self.assertFalse(is_mirror_id("3222", self.curated))
        self.assertIn("3222", base_ids(self.curated))
        self.assertNotIn("223222", base_ids(self.curated))


if __name__ == "__main__":
    unittest.main()
