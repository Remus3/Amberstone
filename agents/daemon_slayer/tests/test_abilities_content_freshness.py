"""DS source-adoption WIN 2 - Meraki content-freshness guard.

The Meraki ``latest`` champions endpoint is mutable but ships a CONTENT
snapshot frozen at a past game patch; its per-record ``patchLastChanged``
(YY.MM) is the only honest freshness signal - the snapshot ``fetched_at``
reflects the download wall-clock, which lies about the content's age. The
balance-sensitive blast radius is ``champion_abilities.json`` ratios + base
damage. These tests pin:

  * ``_patch_sort_key`` - numeric YY.MM ordering (not lexical, so 25.15 > 25.9).
  * ``_meraki_content_patch`` - newest ``patchLastChanged`` across all records,
    skipping records that lack the field / are not dicts; None when absent.
  * ``_EXPECTED_MERAKI_CONTENT_PATCH`` - the pinned known content patch; a
    Meraki refresh trips this so the operator re-pins + re-validates ratios.
  * The committed live ``champion_abilities.json`` records ``meraki_content_patch``
    and it matches the pin (drift alarm).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.daemon_slayer_abilities_extract import (
    _EXPECTED_MERAKI_CONTENT_PATCH,
    _meraki_content_patch,
    _patch_sort_key,
)
from tools.daemon_slayer_extract import _meraki_content_patch_from_abilities

_REPO_ROOT = Path(__file__).resolve().parents[3]


class PatchSortKeyTests(unittest.TestCase):
    def test_numeric_minor_beats_lexical(self) -> None:
        # "25.9" < "25.15" numerically; a lexical string compare would
        # wrongly rank "25.9" higher. The key must be numeric.
        self.assertGreater(_patch_sort_key("25.15"), _patch_sort_key("25.9"))

    def test_major_dominates_minor(self) -> None:
        self.assertGreater(_patch_sort_key("26.1"), _patch_sort_key("25.99"))

    def test_unparseable_sorts_lowest(self) -> None:
        self.assertEqual(_patch_sort_key("garbage"), (-1, -1))
        self.assertEqual(_patch_sort_key(None), (-1, -1))
        self.assertEqual(_patch_sort_key("25"), (-1, -1))


class MerakiContentPatchTests(unittest.TestCase):
    def test_returns_numeric_max_not_lexical(self) -> None:
        raw = {
            "A": {"patchLastChanged": "25.9"},
            "B": {"patchLastChanged": "25.15"},
            "C": {"patchLastChanged": "25.14"},
        }
        self.assertEqual(_meraki_content_patch(raw), "25.15")

    def test_skips_missing_field_and_non_dict_records(self) -> None:
        raw = {
            "A": {"patchLastChanged": "25.10"},
            "B": {"name": "no patch field"},
            "C": "not a dict",
            "D": {"patchLastChanged": "25.12"},
        }
        self.assertEqual(_meraki_content_patch(raw), "25.12")

    def test_none_when_no_patch_anywhere(self) -> None:
        self.assertIsNone(_meraki_content_patch({"A": {"name": "x"}}))
        self.assertIsNone(_meraki_content_patch({}))


class ExpectedPinTests(unittest.TestCase):
    def test_pin_is_yy_dot_mm_string(self) -> None:
        self.assertRegex(_EXPECTED_MERAKI_CONTENT_PATCH, r"^\d+\.\d+$")

    def test_live_snapshot_records_matching_content_patch(self) -> None:
        """The committed champion_abilities.json for the live patch must
        carry ``meraki_content_patch`` (WIN 2 regen) equal to the pin. If
        Meraki refreshes its frozen ``latest`` content, the extractor pin
        drifts and this fails until ratios are re-validated + re-pinned."""
        patch = (
            _REPO_ROOT / "data" / "daemon_slayer" / "current.txt"
        ).read_text(encoding="utf-8").strip()
        path = (
            _REPO_ROOT / "data" / "daemon_slayer" / patch
            / "champion_abilities.json"
        )
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("meraki_content_patch", doc)
        self.assertEqual(
            doc["meraki_content_patch"], _EXPECTED_MERAKI_CONTENT_PATCH
        )


class ManifestContentPatchTests(unittest.TestCase):
    """The phase-1.5 manifest propagates the Meraki content patch from the
    sibling champion_abilities.json so manifest provenance never lies that
    the Meraki data is as fresh as ``fetched_at`` implies."""

    def test_reads_field_from_sibling_abilities(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pd = Path(d)
            (pd / "champion_abilities.json").write_text(
                json.dumps({"meraki_content_patch": "25.15"}),
                encoding="utf-8",
            )
            self.assertEqual(
                _meraki_content_patch_from_abilities(pd), "25.15"
            )

    def test_none_when_sibling_absent(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(
                _meraki_content_patch_from_abilities(Path(d))
            )

    def test_none_when_field_missing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pd = Path(d)
            (pd / "champion_abilities.json").write_text(
                json.dumps({"version": "16.11.1"}), encoding="utf-8"
            )
            self.assertIsNone(_meraki_content_patch_from_abilities(pd))

    def test_live_manifest_records_content_patch(self) -> None:
        """The committed manifest.json for the live patch carries
        ``meraki_items.content_patch`` matching the pin (WIN 2 backfill)."""
        patch = (
            _REPO_ROOT / "data" / "daemon_slayer" / "current.txt"
        ).read_text(encoding="utf-8").strip()
        manifest = json.loads(
            (
                _REPO_ROOT / "data" / "daemon_slayer" / patch / "manifest.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["meraki_items"].get("content_patch"),
            _EXPECTED_MERAKI_CONTENT_PATCH,
        )


if __name__ == "__main__":
    unittest.main()
