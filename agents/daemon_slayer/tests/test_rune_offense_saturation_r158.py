"""R158: turn the rune-offense prose saturation claim into a MACHINE GUARD.

``_rune_offense_grants`` is a seeded ALLOWLIST, and its module docstring carries
a DELIBERATE EXCLUSIONS block adjudicating every rune it declined. That block is
PROSE: it cannot fail CI. When a patch adds a new stat-granting rune to a tree
this registry has already swept, nothing in the repo notices - the new rune just
silently contributes 0.0 forever, which is indistinguishable from a rune that
was read and rejected.

``_ADJUDICATED_NON_GRANTS`` is the machine-readable half of that same claim, and
this file is what makes it bite. For the two trees swept to saturation as of
R158 - Domination 8100 and Sorcery 8200 - every rune id in the live DDragon
``runesReforged.json`` feed must be either REGISTERED (it grants an offensive
stat) or ADJUDICATED (it was read and rejected, with the reason recorded). A
patch that introduces a thirteenth Domination rune reds this suite by name.

The third guard runs the claim in the OTHER direction and is the one that
catches the specific error that produced this directive: an id can only be
adjudicated if it actually EXISTS in the feed. Adjudicating Eyeball Collection
8138 / Ghost Poro 8120 / Zombie Ward - all removed from the game and absent from
16.14.1 - would be recording a decision about a rune nobody can equip, which is
worse than no record at all because it reads as coverage.

SCOPE IS DELIBERATELY TWO TREES. Precision, Resolve and Inspiration are NOT
machine-guarded yet: the registry has entries in Precision (8010, 9104) and
Inspiration (8316) but has never swept either tree to saturation, so asserting
completeness over them would be asserting something unmeasured. That is the
future pass, and this file's tree list is where it lands.

NO BEHAVIOR MAY CHANGE. The last test pins that: the new mapping is a pure
record and credits nothing, so ranking the full 25-rune Domination + Sorcery id
list returns exactly what ranking the two REGISTERED ids returns.

OFFLINE ONLY: no live :8893, no network. Skips cleanly when the vendored feed is
absent so a data-less checkout does not red the suite.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer._rune_offense_grants import (
    _ADJUDICATED_NON_GRANTS,
    _RUNE_OFFENSE_GRANTS,
    rune_offense_grants,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CURRENT_TXT = _REPO_ROOT / "data" / "daemon_slayer" / "current.txt"

# The two trees this registry has swept to saturation as of R158. Precision
# 8000, Resolve 8400 and Inspiration 8300 are deliberately absent - see the
# module docstring.
_SATURATED_TREE_IDS: tuple[int, ...] = (8100, 8200)


def _feed_path() -> Path | None:
    """Resolve the vendored ``runesReforged.json`` the same way sibling DS tests do.

    Patch comes from ``data/daemon_slayer/current.txt`` (the same source
    ``test_r144_mirror_slice_e._patch`` uses); if that file or the patch
    directory is missing, fall back to the newest vendored snapshot the way
    ``test_rune_hsp_amp_r136._rune_files`` globs for one. Returns None when no
    snapshot exists at all, so the caller can skip rather than fail.
    """
    if _CURRENT_TXT.exists():
        patch = _CURRENT_TXT.read_text(encoding="utf-8").strip()
        candidate = (
            _REPO_ROOT / "data" / "meta_build" / "ddragon" / patch / "runesReforged.json"
        )
        if candidate.exists():
            return candidate
    vendored = sorted(
        (_REPO_ROOT / "data" / "meta_build" / "ddragon").glob("*/runesReforged.json")
    )
    return vendored[-1] if vendored else None


def _saturated_tree_runes() -> dict[str, str]:
    """Return ``{rune_id: "<TreeKey>/<RuneKey>"}`` for every rune in the swept trees."""
    path = _feed_path()
    if path is None:
        raise unittest.SkipTest("no vendored runesReforged.json snapshot on disk")
    trees = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for tree in trees:
        if tree.get("id") not in _SATURATED_TREE_IDS:
            continue
        for slot in tree.get("slots", []):
            for rune in slot.get("runes", []):
                out[str(rune["id"])] = f"{tree.get('key')}/{rune.get('key')}"
    return out


class RuneOffenseSaturationTests(unittest.TestCase):
    """Domination 8100 + Sorcery 8200 are adjudicated to saturation."""

    def test_every_swept_tree_rune_is_registered_or_adjudicated(self) -> None:
        runes = _saturated_tree_runes()
        self.assertGreaterEqual(
            len(runes), 20, "the swept-tree rune list looks truncated"
        )
        unadjudicated = sorted(
            (rid, key)
            for rid, key in runes.items()
            if rid not in _RUNE_OFFENSE_GRANTS and rid not in _ADJUDICATED_NON_GRANTS
        )
        self.assertEqual(
            unadjudicated,
            [],
            msg=(
                "unadjudicated rune(s) in a tree this registry claims is "
                "saturated: "
                + ", ".join(f"{rid} {key}" for rid, key in unadjudicated)
                + ". A patch added a rune. Read its longDesc VERBATIM: if it "
                "grants AD / AP / attack speed, seed it into "
                "_RUNE_OFFENSE_GRANTS; otherwise record the reason in "
                "_ADJUDICATED_NON_GRANTS."
            ),
        )

    def test_registered_and_adjudicated_sets_are_disjoint(self) -> None:
        overlap = sorted(set(_RUNE_OFFENSE_GRANTS) & set(_ADJUDICATED_NON_GRANTS))
        self.assertEqual(
            overlap,
            [],
            msg=(
                "rune id(s) both credited and excluded: "
                + ", ".join(overlap)
                + ". An id can be one or the other, never both - a duplicate "
                "here means an entry was seeded without removing its exclusion."
            ),
        )

    def test_every_adjudicated_id_exists_in_the_feed(self) -> None:
        runes = _saturated_tree_runes()
        phantom = sorted(rid for rid in _ADJUDICATED_NON_GRANTS if rid not in runes)
        self.assertEqual(
            phantom,
            [],
            msg=(
                "adjudicated rune id(s) absent from the live feed: "
                + ", ".join(phantom)
                + ". Removed runes (Eyeball Collection 8138, Ghost Poro 8120, "
                "Zombie Ward) must NOT be recorded here - an exclusion for a "
                "rune nobody can equip reads as coverage and is not."
            ),
        )

    def test_every_reason_is_nonempty_ascii(self) -> None:
        for rid, reason in sorted(_ADJUDICATED_NON_GRANTS.items()):
            with self.subTest(rune_id=rid):
                self.assertIsInstance(reason, str)
                self.assertTrue(reason.strip(), "reason must not be empty")
                self.assertTrue(
                    reason.isascii(),
                    "authored text is 7-bit ASCII only - no em-dash, en-dash "
                    "or smart quotes",
                )


class RuneOffenseSaturationInvarianceTests(unittest.TestCase):
    """The new mapping is a pure RECORD: it must credit nothing."""

    _REGISTERED_IN_SWEPT_TREES = ("8236", "8233")

    def _grants(self, ids, *, bonus_ad: float, ap: float):
        return rune_offense_grants(
            ids,
            level=11,
            bonus_ad=bonus_ad,
            ap=ap,
            game_minute=25.0,
            caster_hp_pct=1.0,
        )

    def test_full_swept_tree_page_matches_the_registered_pair_on_an_ad_build(
        self,
    ) -> None:
        every_id = sorted(_saturated_tree_runes())
        full = self._grants(every_id, bonus_ad=140.0, ap=0.0)
        pair = self._grants(
            self._REGISTERED_IN_SWEPT_TREES, bonus_ad=140.0, ap=0.0
        )
        for got, want, axis in zip(full, pair, ("ad", "ap", "as_fraction")):
            with self.subTest(axis=axis):
                self.assertAlmostEqual(got, want, places=9)
        self.assertGreater(full[0], 0.0, "the two registered entries must still pay")

    def test_full_swept_tree_page_matches_the_registered_pair_on_an_ap_build(
        self,
    ) -> None:
        every_id = sorted(_saturated_tree_runes())
        full = self._grants(every_id, bonus_ad=0.0, ap=400.0)
        pair = self._grants(self._REGISTERED_IN_SWEPT_TREES, bonus_ad=0.0, ap=400.0)
        for got, want, axis in zip(full, pair, ("ad", "ap", "as_fraction")):
            with self.subTest(axis=axis):
                self.assertAlmostEqual(got, want, places=9)
        self.assertGreater(full[1], 0.0, "the two registered entries must still pay")

    def test_no_adjudicated_id_credits_anything_on_its_own(self) -> None:
        for rid in sorted(_ADJUDICATED_NON_GRANTS):
            with self.subTest(rune_id=rid):
                self.assertEqual(
                    self._grants([rid], bonus_ad=140.0, ap=0.0), (0.0, 0.0, 0.0)
                )
                self.assertEqual(
                    self._grants([rid], bonus_ad=0.0, ap=400.0), (0.0, 0.0, 0.0)
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
