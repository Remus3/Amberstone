"""RM-95a - champion ability-data lookups resolve DISPLAY names, not just ids.

``champion_abilities.json`` is keyed by canonical DDragon id, and the two guards
that read it - :func:`champion_has_ability_data` and
:func:`champion_ability_data_is_current` - normalized the caller's string with
``_norm_champ_key``, which only lowercases and strips non-alphanumerics.

That reconciles a display name IFF the display name is the id plus punctuation or
case ("Cho'Gath" -> chogath == "Chogath" -> chogath), which covers 18 of the 21
champions whose name differs from their id. It CANNOT reconcile the 3 whose
display name carries extra words or a different word entirely:

    "Wukong"          -> MonkeyKing
    "Nunu & Willump"  -> Nunu
    "Renata Glasc"    -> Renata

Callers holding a Live Client display name (which is what the Live Client API
returns - see memory reference_liveclient_name_vs_ddragon_id) therefore got
False/stale for those three even though the data was present.

MEASURED IMPACT - this does NOT change any ranking. rank(Wukong) and
rank(MonkeyKing) at :8893 are byte-identical across the whole response body. The
real defect is STALENESS MASKING: ``champion_ability_data_is_current`` returns
``not _champ_stale_index.get(key, False)``, so an unresolved key returns the
default False and the champion is certified CURRENT - a champion with drifted
data silently passes the freshness check. Fail-open on a miss, in a guard whose
whole job is to catch drift.

The fix reuses the single canonical resolver
(:func:`core.archetype_picks.canonical_champion_id`, itself derived from
``ddragon_champions.json``) rather than introducing a second alias dict, so a
future champion rename is picked up by a data refresh with no code change.
"""

import unittest

from core.daemon_slayer_client import (
    champion_ability_data_is_current,
    champion_attackrange,
    champion_has_ability_data,
)

# (display_name, ddragon_id) - the ONLY 3 of the 21 name-differs-from-id pairs
# that plain normalization cannot bridge. Verified exhaustively against
# data/meta/ddragon_champions.json.
NON_NORMALIZABLE_ALIASES = [
    ("Wukong", "MonkeyKing"),
    ("Nunu & Willump", "Nunu"),
    ("Renata Glasc", "Renata"),
]

# Punctuation / space variants that ALREADY resolved pre-fix. These must never
# regress - the fix is required to be a strict superset of the old behavior.
ALREADY_RESOLVING = [
    ("Cho'Gath", "Chogath"),
    ("Kai'Sa", "Kaisa"),
    ("Kha'Zix", "Khazix"),
    ("Vel'Koz", "Velkoz"),
    ("Rek'Sai", "RekSai"),
    ("Tahm Kench", "TahmKench"),
    ("Lee Sin", "LeeSin"),
    ("Master Yi", "MasterYi"),
    ("Miss Fortune", "MissFortune"),
    ("Twisted Fate", "TwistedFate"),
    ("Xin Zhao", "XinZhao"),
    ("Jarvan IV", "JarvanIV"),
    ("Aurelion Sol", "AurelionSol"),
]


class AliasAbilityDataTests(unittest.TestCase):
    """A display name must resolve exactly like its canonical id."""

    def test_non_normalizable_display_names_have_ability_data(self) -> None:
        """RED pre-fix for all three."""
        for display, ddragon_id in NON_NORMALIZABLE_ALIASES:
            with self.subTest(champion=display):
                self.assertEqual(
                    champion_has_ability_data(display),
                    champion_has_ability_data(ddragon_id),
                    f"{display!r} must resolve identically to its DDragon id "
                    f"{ddragon_id!r}; the ability data is present under the id.",
                )

    def test_non_normalizable_display_names_report_true_staleness(self) -> None:
        """RED pre-fix - the staleness-masking half of the defect.

        An unresolved key hits the ``.get(key, False)`` default, so the guard
        returns "current" for a champion it never actually looked up.
        """
        for display, ddragon_id in NON_NORMALIZABLE_ALIASES:
            with self.subTest(champion=display):
                self.assertEqual(
                    champion_ability_data_is_current(display),
                    champion_ability_data_is_current(ddragon_id),
                    f"{display!r} must report the same freshness as {ddragon_id!r}; "
                    "a lookup miss silently certifies a stale champion as current.",
                )


class AliasNonRegressionTests(unittest.TestCase):
    """The fix must be a strict superset of plain normalization."""

    def test_punctuation_variants_still_resolve(self) -> None:
        for display, ddragon_id in ALREADY_RESOLVING:
            with self.subTest(champion=display):
                self.assertEqual(
                    champion_has_ability_data(display),
                    champion_has_ability_data(ddragon_id),
                )

    def test_attackrange_parity_across_name_forms(self) -> None:
        for display, ddragon_id in NON_NORMALIZABLE_ALIASES + ALREADY_RESOLVING:
            with self.subTest(champion=display):
                self.assertEqual(
                    champion_attackrange(display),
                    champion_attackrange(ddragon_id),
                )

    def test_unknown_champion_fails_soft(self) -> None:
        """An unresolvable name must not raise - it passes through unchanged."""
        for junk in ["", "NotAChampion", "   ", "Zzzzz'Qqqq"]:
            with self.subTest(value=junk):
                self.assertIsInstance(champion_has_ability_data(junk), bool)
                self.assertIsInstance(champion_ability_data_is_current(junk), bool)


if __name__ == "__main__":
    unittest.main()
