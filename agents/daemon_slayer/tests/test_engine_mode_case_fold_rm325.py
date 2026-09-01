"""Guard: ``engine.build_champion`` folds mode case at its OWN door (RM-325).

The RM-325 slice folded ``canonical_mode`` into the 12 public SCORER entry
points, which makes every scorer-routed call correct. It does not reach the
five modules that call ``build_champion`` DIRECTLY with a caller-supplied
mode - ``antitank.py:856``, ``cli.py:58``, ``fight_report.py:312``,
``matchup.py:153``, ``server.py:443``. A lowercase mode arriving through any
of those still failed the bare ``mode != "ARAM"`` gate at ``engine.py:254``
and silently skipped the ARAM stat modifiers (aramAttackSpeed /
aramAbilityHaste / aramTenacity), which is the SAME defect RM-325 exists to
close, one layer down.

Folding at ``build_champion`` itself is the strictly better home than five
more call-site folds: it is one site that covers every current and future
direct caller. The scorer-level folds stay because they also canonicalize
the ``mode`` echoed back on the result object, and the fold is idempotent.

ASCII only (CLAUDE.md hard rule).
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.engine import build_champion

_CHAMPION = "Ziggs"
_LEVEL = 13


class EngineModeCaseFoldTests(unittest.TestCase):
    """A lowercase mode must resolve identically to its uppercase spelling."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _build(self, mode: str):
        return build_champion(
            self.snap,
            champion_id=_CHAMPION,
            level=_LEVEL,
            item_ids=[],
            mode=mode,
            apply_mode_modifiers=True,
        )

    def test_aram_stat_modifiers_actually_move_stats(self) -> None:
        """Anti-vacuity precondition for every parity assertion below.

        If ARAM ever stopped moving this champion's stats, the parity tests
        would pass for the wrong reason - both spellings agreeing on the
        untouched SR value. This fails loudly instead.
        """
        sr = self._build("SR").stats
        aram = self._build("ARAM").stats
        self.assertNotEqual(
            sr,
            aram,
            f"ARAM applies no stat modifier to {_CHAMPION} L{_LEVEL} - the "
            f"parity tests below would be vacuous",
        )

    def test_lowercase_mode_resolves_identically_to_uppercase(self) -> None:
        upper = self._build("ARAM")
        lower = self._build("aram")
        self.assertEqual(
            upper.stats,
            lower.stats,
            "mode='aram' skipped the engine ARAM stat modifiers that "
            "mode='ARAM' applied",
        )
        self.assertEqual(upper.base_stats, lower.base_stats)
        self.assertEqual(list(upper.notes), list(lower.notes))

    def test_mixed_case_mode_resolves_identically_to_uppercase(self) -> None:
        self.assertEqual(self._build("ARAM").stats, self._build("Aram").stats)

    def test_resolved_mode_field_echoes_the_canonical_spelling(self) -> None:
        self.assertEqual(self._build("aram").mode, "ARAM")

    def test_unknown_mode_is_not_invented_into_a_real_one(self) -> None:
        """Folding case must not turn an unrecognised mode into a handled one."""
        resolved = self._build("foo")
        self.assertEqual(resolved.mode, "FOO")
        self.assertEqual(resolved.stats, self._build("SR").stats)

    def test_non_str_mode_passes_through_untouched(self) -> None:
        """``None`` must not become the string 'NONE' - it has no .upper()."""
        resolved = build_champion(
            self.snap,
            champion_id=_CHAMPION,
            level=_LEVEL,
            item_ids=[],
            mode=None,
            apply_mode_modifiers=False,
        )
        self.assertIsNone(resolved.mode)


if __name__ == "__main__":
    unittest.main()
