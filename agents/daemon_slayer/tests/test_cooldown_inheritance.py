"""Phase 5.9.19 (s206, 2026-05-14) - cooldown inheritance from form 0.

Closes the s205 carry-forward "Engine None-cooldown fallback". Meraki
ability snapshots set ``cooldown=None`` for every non-form-0 entry of a
form-swap ability - Riven R form 1 (Wind Slash), Renekton E form 1
(Dice), AurelionSol R form 1 (The Skies Descend), Qiyana Q form 1
(Elemental Wrath). Pre-s206, ``_form_cooldown_at_rank`` returned a
generic 60s default for these - wrong for the per-spell cooldown
metadata, and wrong for the theoretical-fallback DPS conversion when no
measured cast rate exists in ``spell_cast_rates.json``.

s206 extends the helper signature with an optional ``fallback_form``
argument and updates both call sites (``ability_dps.py`` and
``burst.py``) to pass ``forms[0]`` when the resolved form_index is not
0. Form-swap mechanics share the actual game cooldown with their parent
form, so inheritance is the correct semantics.

Coverage: helper unit tests, integration through ``compute_ability_dps``
and ``compute_burst_damage`` for the 4 affected entries, backward-compat
guards (form-0 path unaffected, generic 60s fallback still works when
both forms lack CD), and live server route assertions on the 4 entries.
"""
from __future__ import annotations

import json
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import AbilityForm, reset_default_cache
from agents.daemon_slayer.ability_dps import (
    _form_cooldown_at_rank,
    compute_ability_dps,
    reset_form_index_cache,
)
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot


def _snap() -> DataSnapshot:
    reset_default_cache()
    reset_form_index_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


def _form(name: str, *, cooldown: tuple[float, ...] | None) -> AbilityForm:
    """Minimal AbilityForm fixture for unit tests."""
    return AbilityForm(
        key="R",
        name=name,
        form_index=0,
        icon=None,
        cooldown=cooldown,
        cost=None,
        damage_type="MAGIC",
        targeting=None,
        affects=None,
        resource=None,
        is_aoe=False,
        damage_blocks=(),
        raw_effects_count=0,
        raw_leveling_count=0,
        parse_status="ok",
        parse_notes=(),
    )


# ─── _form_cooldown_at_rank - helper unit tests ──────────────────────────────


class CooldownHelperBackwardCompatTests(unittest.TestCase):
    """Pre-s206 behavior preserved when no fallback is supplied."""

    def test_form_with_cd_returns_per_rank(self) -> None:
        f = _form("Has CD", cooldown=(120.0, 90.0, 60.0))
        self.assertEqual(_form_cooldown_at_rank(f, 0), 120.0)
        self.assertEqual(_form_cooldown_at_rank(f, 1), 90.0)
        self.assertEqual(_form_cooldown_at_rank(f, 2), 60.0)

    def test_form_with_cd_clamps_negative_rank_to_zero(self) -> None:
        f = _form("Has CD", cooldown=(120.0, 90.0, 60.0))
        self.assertEqual(_form_cooldown_at_rank(f, -1), 120.0)

    def test_form_with_cd_clamps_overflow_rank_to_last(self) -> None:
        f = _form("Has CD", cooldown=(120.0, 90.0, 60.0))
        self.assertEqual(_form_cooldown_at_rank(f, 10), 60.0)

    def test_form_with_no_cd_no_fallback_returns_60s_default(self) -> None:
        f = _form("No CD", cooldown=None)
        self.assertEqual(_form_cooldown_at_rank(f, 2), 60.0)

    def test_form_with_empty_cd_no_fallback_returns_60s_default(self) -> None:
        f = _form("Empty CD", cooldown=())
        self.assertEqual(_form_cooldown_at_rank(f, 2), 60.0)


class CooldownHelperFallbackTests(unittest.TestCase):
    """s206 - fallback_form inherits when primary form has no CD."""

    def test_form_with_cd_ignores_fallback(self) -> None:
        f = _form("Has CD", cooldown=(120.0, 90.0, 60.0))
        fb = _form("Fallback CD", cooldown=(7.0, 7.0, 7.0))
        # Primary form has its own CD - fallback ignored.
        self.assertEqual(_form_cooldown_at_rank(f, 1, fallback_form=fb), 90.0)

    def test_form_with_no_cd_inherits_from_fallback(self) -> None:
        f = _form("No CD", cooldown=None)
        fb = _form("Fallback CD", cooldown=(120.0, 90.0, 60.0))
        self.assertEqual(_form_cooldown_at_rank(f, 0, fallback_form=fb), 120.0)
        self.assertEqual(_form_cooldown_at_rank(f, 1, fallback_form=fb), 90.0)
        self.assertEqual(_form_cooldown_at_rank(f, 2, fallback_form=fb), 60.0)

    def test_form_with_empty_cd_inherits_from_fallback(self) -> None:
        f = _form("Empty CD", cooldown=())
        fb = _form("Fallback CD", cooldown=(7.0, 7.0, 7.0, 7.0, 7.0))
        self.assertEqual(_form_cooldown_at_rank(f, 0, fallback_form=fb), 7.0)

    def test_form_no_cd_fallback_no_cd_returns_60s_default(self) -> None:
        f = _form("No CD", cooldown=None)
        fb = _form("Fallback also empty", cooldown=None)
        self.assertEqual(_form_cooldown_at_rank(f, 2, fallback_form=fb), 60.0)

    def test_fallback_clamps_overflow_rank_to_last(self) -> None:
        f = _form("No CD", cooldown=None)
        fb = _form("Fallback CD", cooldown=(120.0, 90.0, 60.0))
        # rank 5 > len(fallback.cooldown) - clamps to last entry.
        self.assertEqual(_form_cooldown_at_rank(f, 5, fallback_form=fb), 60.0)

    def test_fallback_clamps_negative_rank_to_zero(self) -> None:
        f = _form("No CD", cooldown=None)
        fb = _form("Fallback CD", cooldown=(120.0, 90.0, 60.0))
        self.assertEqual(_form_cooldown_at_rank(f, -1, fallback_form=fb), 120.0)

    def test_explicit_none_fallback_returns_60s_default(self) -> None:
        f = _form("No CD", cooldown=None)
        # Explicit None fallback - same as no fallback.
        self.assertEqual(
            _form_cooldown_at_rank(f, 2, fallback_form=None), 60.0
        )


# ─── compute_ability_dps integration - 4 affected form-1 entries ─────────────


class AbilityDpsCooldownInheritanceTests(unittest.TestCase):
    """The 4 form_index registry entries with form 1 cooldown=None now
    inherit their parent form's per-rank CD."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _spell(self, champion: str, key: str, *, level: int = 11):
        out = compute_ability_dps(
            self.snap, champion, level=level, item_ids=[],
            mode="SR", target_armor=80.0, target_mr=30.0,
            target_max_hp=2000.0,
        )
        return next((s for s in out.per_spell if s.key == key), None)

    def test_riven_R_inherits_form0_cooldown(self) -> None:
        # Riven R form 0 cd=[120, 90, 60]; at lvl 11 R is rank 2 → 90.0.
        # Pre-s206 returned 60.0 (generic default).
        s = self._spell("Riven", "R", level=11)
        self.assertIsNotNone(s)
        self.assertEqual(s.form_index, 1)
        self.assertEqual(s.form_name, "Wind Slash")
        self.assertEqual(s.cooldown, 90.0)

    def test_riven_R_inherits_at_rank_3(self) -> None:
        # At lvl 16 R is rank 3 → 60.0 (form 0 cd[2]).
        s = self._spell("Riven", "R", level=16)
        self.assertIsNotNone(s)
        self.assertEqual(s.cooldown, 60.0)

    def test_renekton_E_inherits_form0_cooldown(self) -> None:
        # Renekton E form 0 cd=[16, 14.5, 13, 11.5, 10]; at lvl 11 E is
        # rank 3 (Q maxed first lvl 9 + W up to rank 1, E starts rank 2)
        # - actual rank depends on max_priority. Assert it's NOT 60s.
        s = self._spell("Renekton", "E", level=11)
        self.assertIsNotNone(s)
        self.assertEqual(s.form_index, 1)
        self.assertEqual(s.form_name, "Dice")
        self.assertNotEqual(s.cooldown, 60.0)
        self.assertIn(s.cooldown, (16.0, 14.5, 13.0, 11.5, 10.0))

    def test_aurelionsol_R_inherits_form0_cooldown(self) -> None:
        # AurelionSol R form 0 cd=[120, 110, 100]; at lvl 11 R is rank 2 → 110.
        s = self._spell("AurelionSol", "R", level=11)
        self.assertIsNotNone(s)
        self.assertEqual(s.form_index, 1)
        self.assertEqual(s.form_name, "The Skies Descend")
        self.assertEqual(s.cooldown, 110.0)

    def test_qiyana_Q_inherits_form0_cooldown(self) -> None:
        # Qiyana Q form 0 cd=[7, 7, 7, 7, 7]; flat 7s at any rank.
        s = self._spell("Qiyana", "Q", level=11)
        self.assertIsNotNone(s)
        self.assertEqual(s.form_index, 1)
        self.assertEqual(s.form_name, "Elemental Wrath")
        self.assertEqual(s.cooldown, 7.0)

    def test_form0_unaffected(self) -> None:
        # Riven Q form 0 cd=[13, 13, 13, 13, 13]; flat 13s.
        # form_idx == 0, so fallback is None - uses primary form's CD.
        s = self._spell("Riven", "Q", level=11)
        self.assertIsNotNone(s)
        self.assertEqual(s.form_index, 0)
        self.assertEqual(s.cooldown, 13.0)

    def test_unmapped_form_swap_champion_unaffected(self) -> None:
        # Champions WITHOUT a form_index registry entry still default to
        # form 0 - fallback is None, so behavior is identical to pre-s206.
        s = self._spell("Veigar", "R", level=11)
        self.assertIsNotNone(s)
        self.assertEqual(s.form_index, 0)
        # Veigar R form 0 cd=[100, 80, 60] at rank 2 → 80.
        self.assertEqual(s.cooldown, 80.0)


# ─── compute_burst_damage integration ────────────────────────────────────────


class BurstCooldownInheritanceTests(unittest.TestCase):
    """ComboCast rows for form-1 R entries surface inherited CD."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _r_cast(self, champion: str, level: int = 11):
        out = compute_burst_damage(
            self.snap, champion, level=level, item_ids=[],
            mode="SR", target_armor=80.0, target_mr=30.0,
            target_max_hp=2000.0,
        )
        # Find the first ability cast for key R.
        return next(
            (c for c in out.per_cast if c.is_ability and c.ability_key == "R"),
            None,
        )

    def test_riven_R_burst_row_inherits_cooldown(self) -> None:
        c = self._r_cast("Riven", level=11)
        self.assertIsNotNone(c)
        self.assertEqual(c.form_index, 1)
        self.assertEqual(c.cooldown, 90.0)  # form 0 cd[1] @ rank 2

    def test_aurelionsol_R_burst_row_inherits_cooldown(self) -> None:
        c = self._r_cast("AurelionSol", level=11)
        self.assertIsNotNone(c)
        self.assertEqual(c.form_index, 1)
        self.assertEqual(c.cooldown, 110.0)

    def test_unmapped_burst_row_unaffected(self) -> None:
        c = self._r_cast("Veigar", level=11)
        self.assertIsNotNone(c)
        self.assertEqual(c.form_index, 0)
        # Veigar R form 0 cd=[100, 80, 60] at rank 2 → 80.
        self.assertEqual(c.cooldown, 80.0)


# ─── Live server route checks (skipped if DS down) ───────────────────────────


class ServerRouteCooldownTests(unittest.TestCase):
    BASE_URL = "http://127.0.0.1:8893"

    @classmethod
    def setUpClass(cls) -> None:
        try:
            urlopen(f"{cls.BASE_URL}/health", timeout=2).read()
        except Exception as e:  # pragma: no cover - env-dependent
            raise unittest.SkipTest(f"DS server unavailable: {e}")

    def _ability_dps_spell(self, champion: str, key: str, level: int = 11):
        req = Request(
            f"{self.BASE_URL}/ability-dps",
            data=json.dumps({
                "champion": champion, "level": level, "mode": "SR",
                "target_armor": 80, "target_mr": 30, "target_max_hp": 2000,
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        out = json.loads(urlopen(req, timeout=10).read())
        spells = out.get("per_spell", [])
        return next((s for s in spells if s["key"] == key), None)

    def test_riven_R_cooldown_inherited_via_route(self) -> None:
        s = self._ability_dps_spell("Riven", "R", level=11)
        self.assertIsNotNone(s)
        self.assertEqual(s["form_index"], 1)
        self.assertNotEqual(s["cooldown"], 60.0)
        self.assertEqual(s["cooldown"], 90.0)

    def test_renekton_E_cooldown_inherited_via_route(self) -> None:
        s = self._ability_dps_spell("Renekton", "E", level=11)
        self.assertIsNotNone(s)
        self.assertEqual(s["form_index"], 1)
        self.assertNotEqual(s["cooldown"], 60.0)

    def test_aurelionsol_R_cooldown_inherited_via_route(self) -> None:
        s = self._ability_dps_spell("AurelionSol", "R", level=11)
        self.assertIsNotNone(s)
        self.assertEqual(s["form_index"], 1)
        self.assertEqual(s["cooldown"], 110.0)

    def test_qiyana_Q_cooldown_inherited_via_route(self) -> None:
        s = self._ability_dps_spell("Qiyana", "Q", level=11)
        self.assertIsNotNone(s)
        self.assertEqual(s["form_index"], 1)
        self.assertEqual(s["cooldown"], 7.0)


if __name__ == "__main__":
    unittest.main()
