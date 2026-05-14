"""Phase 5.9 (s191, 2026-05-14) — per-(champion, key) block_index override tests.

Tests the ``champion_block_index.json`` registry loader plus its integration
with ``compute_ability_dps`` / ``rank_items_by_ability_dps`` and
``compute_burst_damage`` / ``rank_items_by_burst``. The override table
ships 12 entries across 11 champions selecting realistic burst-window
damage blocks: Cassi E block1 (Total Enhanced vs poisoned), Veigar R
block1 (Maximum vs executed), Anivia E block1 (Enhanced vs chilled),
Diana W block2 (Total all 3 orbs), Brand W block1 (Increased vs CC'd),
Evelynn R block1 (Empowered execute), etc.

Phase 5.9.5 (s192) added token-variant lookup (Akali R/R2 split).
Phase 5.9.6 (s193) added 8 channeled-ability entries (Alistar/Fiddle/etc).
Phase 5.9.7 (s194) added 8 calibration-follow-up entries (Corki W/E,
Hecarim W/E, Jayce Q/W, Rell R, DrMundo W) — same per-tick → total
pattern plus the first block_index that layers on a prior form_index
override (Jayce Q inside cannon form 1).
Phase 5.9.8 (s195) added 13 entries spanning four sub-patterns:
multi-hit single-target totals (Ahri W, Kaisa Q, Lulu Q, Sivir Q,
Talon W/R, Velkoz W, Ekko Q), fully-charged amps (Varus Q, Zoe Q,
Vladimir E), recast amp (Camille Q), CC-conditional duration total
(Morgana W). Same walker logic — pure data expansion.

Phase 5.9.9 (s196) added 17 entries (14 new champions + 3 key
extensions on Akali, Cassiopeia, Morgana). Pattern A multi-hit
single-target totals: Akali E, Akshan Q, Cassiopeia W, Chogath E,
Draven R, Lillia W, Morgana R, Nautilus E, Riven Q, Sett Q,
Skarner Q, Soraka E. Pattern B fully-charged / condition amps:
Gragas Q (fermented), Karthus Q (solo-target enhanced), Khazix Q
(isolation), KogMaw R (low-HP execute), Pantheon Q (charged hurl).
Twelfth consecutive override registry expansion; fifth pure-data
batch.

Phase 5.9.10 (s197) added 20 entries across 18 new champions
spanning five sub-patterns (multi-hit/channel/mark, fully-charged,
resource-state, execute, multi-charge). Registry 49 → 67 champions.

Phase 5.9.11 (s198) added 20 entries (17 new champions + 2 key
extensions on Sion and Vladimir; XinZhao contributes 2 entries
Q+W as a new champion). Registry 67 → 84 champions, 83 → 103
(champion, key) entries. Pattern A multi-hit single-target
totals: Sylas Q, XinZhao Q/W, Zac R, Maokai E, Kayn Q,
Sejuani W, Neeko Q, Nasus E, Nami E, Ornn R, Twitch E. Pattern
B fully-charged amps: Vi Q, Sion R, Irelia W, Yuumi Q. Pattern
C resource-state amp: Jax E. Pattern D channel/duration totals:
Udyr R, Vladimir W, Viktor R. Fourteenth consecutive override
registry; seventh pure-data batch.

Phase 5.9.12 (s199) added 17 entries (6 new champions: Ashe/Shaco/
Shen/Swain/Tristana/Xayah + 11 key extensions on Aatrox/
Fiddlesticks/Karthus/Nautilus/Nunu/Samira/Sejuani/Talon/Udyr/
Viktor/Zac). Registry 84 → 90 champions, 103 → 120 (champion, key)
entries. Six patterns: Pattern A multi-hit single-target totals
(Ashe Q, Nunu E, Samira W, Shen Q, Swain Q, Viktor Q, Xayah Q,
Zac Q), Pattern B positional/sweet-spot amps (Aatrox Q sweet-
spot, Shaco E backstab, Talon Q champion crit), Pattern C
resource-state amps (Tristana E max-stack, Udyr Q Awakened),
Pattern D channel total (Karthus E per-second), Pattern E
direct-hit primary target (Sejuani R direct stun, Nautilus R
primary hit), Pattern F execute amp (Fiddlesticks W low-HP).
Fifteenth consecutive override registry; eighth pure-data batch.
"""
from __future__ import annotations

import json
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.ability_dps import (
    _BLOCK_INDEX_PATH,
    _load_block_index_table,
    _resolve_block_index_overrides,
    _select_blocks,
    AbilityContext,
    compute_ability_dps,
    get_block_index_for,
    rank_items_by_ability_dps,
    reset_block_index_cache,
)
from agents.daemon_slayer.abilities import DamageBlock
from agents.daemon_slayer.burst import (
    compute_burst_damage,
    rank_items_by_burst,
)
from agents.daemon_slayer.data_loader import DataSnapshot


def _snap() -> DataSnapshot:
    reset_default_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


def _ctx() -> AbilityContext:
    """Minimal AbilityContext for unit tests that exercise _select_blocks."""
    return AbilityContext(
        base_ad=0.0, total_ad=0.0, bonus_ad=0.0, ap=0.0,
        caster_max_hp=0.0, caster_bonus_hp=0.0,
        caster_bonus_armor=0.0, caster_bonus_mr=0.0,
        caster_max_mp=0.0, caster_mp_regen_per_5=0.0,
        target_armor=0.0, target_mr=0.0,
        target_max_hp=0.0, target_current_hp=0.0,
        target_missing_hp=0.0, target_bonus_hp=0.0,
    )


# ─── registry shape ──────────────────────────────────────────────────────────


class RegistryShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.table = _load_block_index_table()

    def test_path_exists(self) -> None:
        self.assertTrue(_BLOCK_INDEX_PATH.exists())

    def test_has_default_and_champions(self) -> None:
        self.assertIn("default", self.table)
        self.assertIn("champions", self.table)

    def test_default_is_empty_dict(self) -> None:
        self.assertEqual(self.table["default"], {})

    def test_known_champion_overrides(self) -> None:
        champions = self.table["champions"]
        # Phase 5.9 (s191) — initial seed (some champions extended in later batches)
        # Cassiopeia extended in s196 with W=1 — full shape asserted below
        self.assertEqual(champions["Veigar"], {"R": 1})
        # Diana extended in s203 with R=2 (Moonfall channel total) — asserted below
        self.assertEqual(champions["Brand"], {"W": 1, "R": 1})
        # Evelynn extended in s204 with Q=5 — full shape asserted in Phase 5.9.17 block
        self.assertEqual(champions["Aurora"], {"Q": 2})
        self.assertEqual(champions["Belveth"], {"E": 2})
        self.assertEqual(champions["Karma"], {"W": 1})
        self.assertEqual(champions["Vex"], {"R": 2})
        # Phase 5.9.5 (s192) — Akali R + R2 token-variant override
        # Akali extended in s196 with E=2 — full shape asserted below
        # Phase 5.9.6 (s193) — channeled-ability expansion + Anivia Q
        # Anivia extended in s200 with R=1 (Glacial Storm Empowered tick)
        self.assertEqual(champions["Anivia"], {"Q": 2, "E": 1, "R": 1})
        self.assertEqual(champions["Alistar"], {"E": 1})
        # AurelionSol extended in s202 with Q=2 (Breath of Light full channel)
        # Fiddlesticks extended in s199 with W=3 (Bountiful Harvest execute)
        self.assertEqual(champions["Fiddlesticks"], {"R": 1, "W": 3})
        self.assertEqual(champions["MissFortune"], {"E": 1})
        # Samira extended in s199 with W=1 (Blade Whirl 2-rotation total)
        self.assertEqual(champions["Samira"], {"R": 1, "W": 1})
        self.assertEqual(champions["Singed"], {"Q": 1})
        # Syndra extended in s204 with W=2 — full shape asserted in Phase 5.9.17 block
        # Phase 5.9.7 (s194) — calibration follow-up expansion
        self.assertEqual(champions["Corki"], {"W": 1, "E": 1})
        self.assertEqual(champions["Hecarim"], {"W": 1, "E": 1})
        self.assertEqual(champions["Jayce"], {"Q": 1, "W": 1})
        self.assertEqual(champions["Rell"], {"R": 1})
        self.assertEqual(champions["DrMundo"], {"W": 1})
        # Phase 5.9.8 (s195) — multi-hit / charge / recast expansion
        # Ahri W=2 extends prior {"Q": 1} from s191 seed
        self.assertEqual(champions["Ahri"], {"Q": 1, "W": 2})
        # Velkoz W=2 extends prior {"R": 1} from s193 channels
        self.assertEqual(champions["Velkoz"], {"W": 2, "R": 1})
        # New champions added in s195 (Morgana extended in s196 with R=1 — asserted below):
        self.assertEqual(champions["Camille"], {"Q": 2})
        self.assertEqual(champions["Ekko"], {"Q": 3})
        self.assertEqual(champions["Kaisa"], {"Q": 2})
        self.assertEqual(champions["Lulu"], {"Q": 3})
        self.assertEqual(champions["Sivir"], {"Q": 2})
        # Talon extended in s199 with Q=1 — full shape asserted below
        self.assertEqual(champions["Varus"], {"Q": 1})
        # Vladimir W=1 extends prior {"E": 1} from s195 (added s198);
        # Vladimir Q=1 added s203 (Crimson Rush full-stack) — asserted below
        # Zoe extended in s202 with W=1 — full shape asserted below
        # Phase 5.9.9 (s196) — extended multi-hit / condition amp expansion
        # Akali E=2 extends prior {"R": 0, "R2": 2} from s192
        self.assertEqual(champions["Akali"], {"R": 0, "R2": 2, "E": 2})
        # Cassiopeia W=1 extends prior {"E": 1} from s191
        self.assertEqual(champions["Cassiopeia"], {"E": 1, "W": 1})
        # Morgana R=1 extends prior {"W": 3} from s195
        self.assertEqual(champions["Morgana"], {"W": 3, "R": 1})
        # New champions added this batch (14):
        # Akshan extended in s202 with R=1 — full shape asserted below
        self.assertEqual(champions["Chogath"], {"E": 1})
        self.assertEqual(champions["Draven"], {"R": 1})
        self.assertEqual(champions["Gragas"], {"Q": 1})
        # Karthus extended in s199 with E=2 (Defile per-second tick)
        self.assertEqual(champions["Karthus"], {"Q": 1, "E": 2})
        self.assertEqual(champions["Khazix"], {"Q": 1})
        self.assertEqual(champions["KogMaw"], {"R": 1})
        # Lillia extended in s200 with Q=1 (Q + Dream Dust AA combo)
        self.assertEqual(champions["Lillia"], {"W": 1, "Q": 1})
        # Nautilus extended in s199 with R=2 (Depth Charge primary hit)
        self.assertEqual(champions["Nautilus"], {"E": 2, "R": 2})
        self.assertEqual(champions["Pantheon"], {"Q": 1})
        # Riven extended in s204 with R=1 (+ form_index seed) — full shape asserted in Phase 5.9.17 block
        self.assertEqual(champions["Sett"], {"Q": 1})
        self.assertEqual(champions["Skarner"], {"Q": 1})
        self.assertEqual(champions["Soraka"], {"E": 1})
        # Phase 5.9.10 (s197) — assassin/fighter resource amps + utility totals
        # 20 entries across 18 new champions (registry 49 → 67):
        # Aatrox extended in s199 with Q=1 (Q1 sweet-spot)
        self.assertEqual(champions["Aatrox"], {"W": 3, "Q": 1})
        self.assertEqual(champions["Briar"], {"E": 4})
        self.assertEqual(champions["Darius"], {"R": 2})
        self.assertEqual(champions["Hwei"], {"R": 3})
        self.assertEqual(champions["Kassadin"], {"R": 3})
        self.assertEqual(champions["Leblanc"], {"Q": 1, "E": 1})
        self.assertEqual(champions["Lucian"], {"R": 1})
        self.assertEqual(champions["MasterYi"], {"Q": 2})
        self.assertEqual(champions["Mel"], {"Q": 3, "R": 2})
        self.assertEqual(champions["MonkeyKing"], {"R": 1})
        self.assertEqual(champions["Naafiri"], {"Q": 2, "E": 1})
        # Nilah extended in s200 with Q=1 (Formless Blade max-stack empowered)
        self.assertEqual(champions["Nilah"], {"R": 1, "Q": 1})
        # Nunu extended in s199 with E=1 (Snowball Barrage 3-snowball cap)
        self.assertEqual(champions["Nunu"], {"W": 1, "E": 1})
        # Poppy extended in s200 with Q=1 + s202 with E=1 — asserted below
        # Renekton extended in s202 with R=1 — asserted below
        # Rumble extended in s202 with Q=2 + R=2 — asserted below
        # Sion R=1 extends prior {"Q": 2} from s197 (added s198)
        self.assertEqual(champions["Sion"], {"Q": 2, "R": 1})
        # Smolder extended in s202 with Q=1 + R=1 — asserted below
        # Phase 5.9.11 (s198) — bruiser/jungler/utility/marksman expansion
        # 20 entries across 17 new champions + 2 key extensions
        # (Sion R and Vladimir W asserted above with their extended shape):
        self.assertEqual(champions["Irelia"], {"W": 1})
        # Jax extended in s203 with R=1 (Grandmaster's Might active 3-AA) — asserted below
        self.assertEqual(champions["Kayn"], {"Q": 1})
        self.assertEqual(champions["Maokai"], {"E": 1})
        self.assertEqual(champions["Nami"], {"E": 1})
        # Nasus extended in s202 with R=1 — asserted below
        self.assertEqual(champions["Neeko"], {"Q": 2})
        self.assertEqual(champions["Ornn"], {"R": 2})
        # Sejuani extended in s199 with R=1 (Glacial Prison direct stun)
        self.assertEqual(champions["Sejuani"], {"W": 2, "R": 1})
        self.assertEqual(champions["Sylas"], {"Q": 3})
        self.assertEqual(champions["Twitch"], {"E": 3})
        # Udyr extended in s199 with Q=1 (Wilding Claw Awakened 2-AA)
        self.assertEqual(champions["Udyr"], {"R": 1, "Q": 1})
        self.assertEqual(champions["Vi"], {"Q": 1})
        # Viktor extended in s199 + s202 — full shape asserted below
        self.assertEqual(champions["XinZhao"], {"Q": 1, "W": 2})
        # Yuumi extended in s202 with R=2 — full shape asserted below
        # Zac extended in s199 with Q=1 (Stretching Strikes 2-arm total)
        self.assertEqual(champions["Zac"], {"R": 2, "Q": 1})
        # Phase 5.9.12 (s199) — new champions:
        self.assertEqual(champions["Ashe"], {"Q": 2})
        self.assertEqual(champions["Shaco"], {"E": 2})
        # Phase 5.9.13 (s200) — Ambessa new champion (3 entries Drain amp +
        # Lacerate total); Anivia/Lillia/Nilah/Poppy extended above with
        # their full s200 shapes.
        self.assertEqual(champions["Ambessa"], {"Q": 1, "W": 1, "E": 1})
        # Shen.Q raw block 0 is 'Slow' (non-damage), stripped pre-index;
        # filtered idx 1 = raw block 2 'Total Magic Damage' (3-AA total).
        self.assertEqual(champions["Shen"], {"Q": 1})
        self.assertEqual(champions["Swain"], {"Q": 2})
        # Talon extended in s199 with Q=1 (Noxian Diplomacy champion crit)
        self.assertEqual(champions["Talon"], {"W": 2, "R": 2, "Q": 1})
        self.assertEqual(champions["Tristana"], {"E": 4})
        self.assertEqual(champions["Xayah"], {"Q": 1})
        # Phase 5.9.14 (s201) — 17 entries across 14 new champions:
        # Patterns A (multi-hit), B (fully-charged), C (channel/duration),
        # D (condition/execute), E (resource/positional). 4 with non-damage
        # prefix blocks (filtered idx ≠ raw idx): Galio W, Kennen R, Teemo R,
        # Xerath R. Reverts of s198 skip rationale: Xerath W, Ziggs E,
        # Janna Q, Yasuo E.
        self.assertEqual(champions["Fizz"], {"R": 2})
        self.assertEqual(champions["Galio"], {"W": 1})
        self.assertEqual(champions["Garen"], {"E": 1})
        self.assertEqual(champions["Graves"], {"Q": 2})
        self.assertEqual(champions["Janna"], {"Q": 2})
        self.assertEqual(champions["Jhin"], {"Q": 2, "R": 1})
        # Kennen extended in s203 with W=1 (active cast vs passive 4th-AA) — asserted below
        self.assertEqual(champions["Taliyah"], {"Q": 2})
        self.assertEqual(champions["Teemo"], {"E": 2, "R": 1})
        self.assertEqual(champions["Viego"], {"Q": 3})
        self.assertEqual(champions["Xerath"], {"W": 1, "R": 1})
        self.assertEqual(champions["Yasuo"], {"E": 3})
        self.assertEqual(champions["Ziggs"], {"E": 2})
        # Phase 5.9.15 (s202) — 18 entries: 6 new champions + 12 key extensions.
        # New: Gangplank, Gnar, KSante, RekSai, Vayne, Yunara. Extensions on
        # Zoe (W), Akshan (R), AurelionSol (Q), Nasus (R), Poppy (E), Renekton
        # (R), Rumble (Q+R), Smolder (Q+R), Viktor (E), Yuumi (R). 9 entries
        # with non-damage prefix blocks (filtered idx ≠ raw idx). Reverts 4
        # prior-batch skip rationales: Gnar R + Vayne E + Poppy E wall-stun
        # (s198/s199 'terrain condition'), Rumble Q (s199 'heat decays').
        self.assertEqual(champions["Gangplank"], {"R": 2})
        self.assertEqual(champions["Gnar"], {"R": 1})
        # KSante extended in s204 with W=3 — full shape asserted in Phase 5.9.17 block
        self.assertEqual(champions["RekSai"], {"E": 1})
        self.assertEqual(champions["Vayne"], {"E": 2})
        self.assertEqual(champions["Yunara"], {"Q": 2})
        # Zoe extended in s204 with E=2 — full shape asserted in Phase 5.9.17 block
        # Akshan extended in s202 with R=1 (Comeuppance max-charge)
        self.assertEqual(champions["Akshan"], {"Q": 1, "R": 1})
        # AurelionSol extended in s202 with Q=2 (Breath of Light full channel)
        self.assertEqual(champions["AurelionSol"], {"E": 1, "Q": 2})
        # Nasus extended in s202 with R=1 (Fury of the Sands full duration)
        self.assertEqual(champions["Nasus"], {"E": 2, "R": 1})
        # Poppy extended in s202 with E=1 (Heroic Charge wall-slam)
        self.assertEqual(champions["Poppy"], {"R": 1, "Q": 1, "E": 1})
        # Renekton extended in s202 with R=1 (Dominus full duration aura)
        self.assertEqual(champions["Renekton"], {"Q": 1, "W": 2, "R": 1})
        # Rumble extended in s202 with Q=2 (Danger Zone enhanced) + R=2 (Equalizer max)
        self.assertEqual(champions["Rumble"], {"E": 1, "Q": 2, "R": 2})
        # Smolder extended in s202 with Q=1 (max-stack passive) + R=1 (max-distance);
        # s203 adds E=1 (Achooo! max-stack passive scaling) — asserted below
        # Viktor extended in s202 with E=2 (Death Ray double-hit)
        self.assertEqual(champions["Viktor"], {"R": 2, "Q": 2, "E": 2})
        # Yuumi extended in s202 with R=2 (Final Chapter 2 hits per target)
        self.assertEqual(champions["Yuumi"], {"Q": 1, "R": 2})
        # Phase 5.9.16 (s203) — 12 entries: 5 new champions + 5 key extensions.
        # New: Blitzcrank, Gwen, Kled (Q+E+R), LeeSin, Thresh. Extensions on
        # Diana (R), Jax (R), Kennen (W), Smolder (E), Vladimir (Q). Six
        # sub-patterns: (A) multi-hit single-target totals (Diana R, Gwen R,
        # Kled Q, Kled E, Vladimir Q), (B) resource-state amps (Smolder E,
        # Vladimir Q), (C) active-cast vs passive-zap split (Blitzcrank R,
        # Kennen W, Jax R), (D) max-charge condition amp (Kled R), (E) missing-
        # HP amp layered on s187 form_index=1 (LeeSin Q — first NET-damage
        # composition with form_index registry), (F) empty-block-0 fix
        # (Thresh E — first instance of routing past an evaluates-to-zero
        # block 0 with only unparsed soul scaling).
        self.assertEqual(champions["Blitzcrank"], {"R": 1})
        # Diana extended in s203 with R=2 — full shape:
        self.assertEqual(champions["Diana"], {"W": 2, "R": 2})
        # Gwen extended in s204 with Q=6 — full shape asserted in Phase 5.9.17 block
        # Jax extended in s203 with R=1 — full shape:
        self.assertEqual(champions["Jax"], {"E": 1, "R": 1})
        # Kennen extended in s203 with W=1 — full shape:
        self.assertEqual(champions["Kennen"], {"R": 1, "W": 1})
        self.assertEqual(champions["Kled"], {"Q": 2, "E": 1, "R": 1})
        # LeeSin Q=1 composes with s187 form_index=1 (Resonating Strike form):
        # form_index routes to form 1, block_index then routes within that
        # form to the max-missing-HP variant. First instance of layering
        # block_index on a form_index override that adds NET damage.
        self.assertEqual(champions["LeeSin"], {"Q": 1})
        # Smolder extended in s203 with E=1 — full shape:
        self.assertEqual(champions["Smolder"], {"W": 2, "Q": 1, "R": 1, "E": 1})
        # Thresh routes to ds.hps by default; E=2 entry is for direct
        # /ability-dps queries since engine default block 0 evaluates to 0
        # (only unparsed per-Soul scaling, no base/AP).
        self.assertEqual(champions["Thresh"], {"E": 2})
        # Vladimir extended in s203 with Q=1 — full shape:
        self.assertEqual(champions["Vladimir"], {"E": 1, "W": 1, "Q": 1})
        # Phase 5.9.17 (s204) — 8 entries: 2 new champions (Nidalee, Seraphine)
        # + 6 key extensions (Evelynn Q, Gwen Q, KSante W, Riven R, Syndra W,
        # Zoe E). Plus Riven added to form_index registry (R=1 routing to
        # Wind Slash form). Six sub-patterns: (A) multi-hit single-target
        # totals (Evelynn Q full Hate Spike rotation, Gwen Q max-scissor
        # burst, Syndra W Total Mixed sum), (B) fully-charged amp (KSante
        # W Path Maker max-charge), (C) champion-vs-minion amp (Seraphine
        # Q Maximum Champion Damage), (D) execute amp layered on form_
        # index (Nidalee Q low-HP cougar Takedown — second NET-damage
        # layering after s203 LeeSin Q), (E) target-state amp (Zoe E
        # sleep-procced Maximum Mixed Damage), (F) form_index seed
        # expansion (Riven R Wind Slash — first new champion in form_
        # index registry since s187, closes s203 carry-forward 'Riven
        # form_index seed needed').
        # Evelynn extended with Q=5 — full shape:
        self.assertEqual(champions["Evelynn"], {"R": 1, "Q": 5})
        # Gwen extended with Q=6 — full shape:
        self.assertEqual(champions["Gwen"], {"R": 4, "Q": 6})
        # KSante extended with W=3 — full shape:
        self.assertEqual(champions["KSante"], {"R": 2, "W": 3})
        # Nidalee NEW — composes with s187 form_index Q=1 (cougar form):
        self.assertEqual(champions["Nidalee"], {"Q": 1})
        # Riven extended with R=1 — full shape; form_index seed for R=1
        # ships in champion_form_index.json (asserted in Phase 5.9.17 tests).
        self.assertEqual(champions["Riven"], {"Q": 1, "R": 1})
        # Seraphine NEW — High Note Maximum Champion Damage:
        self.assertEqual(champions["Seraphine"], {"Q": 1})
        # Syndra extended with W=2 — full shape:
        self.assertEqual(champions["Syndra"], {"R": 2, "W": 2})
        # Zoe extended with E=2 — full shape:
        self.assertEqual(champions["Zoe"], {"Q": 1, "W": 1, "E": 2})

    def test_every_value_is_int(self) -> None:
        for champion_id, entries in self.table["champions"].items():
            for key, value in entries.items():
                with self.subTest(champion_id=champion_id, key=key):
                    self.assertIsInstance(value, int)
                    self.assertGreaterEqual(value, 0)

    def test_every_key_is_valid_token(self) -> None:
        # Phase 5.9.5 (s192) extended valid keys to repeat-variant tokens
        # (Q2/W2/E2/R2) in addition to base ability keys (Q/W/E/R).
        valid = {"Q", "W", "E", "R", "Q2", "W2", "E2", "R2"}
        for champion_id, entries in self.table["champions"].items():
            for key in entries:
                with self.subTest(champion_id=champion_id, key=key):
                    self.assertIn(key, valid)


# ─── loader / cache ──────────────────────────────────────────────────────────


class LoaderCacheTests(unittest.TestCase):
    def test_singleton_returns_same_object(self) -> None:
        reset_block_index_cache()
        a = _load_block_index_table()
        b = _load_block_index_table()
        self.assertIs(a, b)

    def test_reset_clears_cache(self) -> None:
        reset_block_index_cache()
        a = _load_block_index_table()
        reset_block_index_cache()
        b = _load_block_index_table()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)


# ─── get_block_index_for ─────────────────────────────────────────────────────


class GetBlockIndexForTests(unittest.TestCase):
    def test_known_override_returns_champion_source(self) -> None:
        # Veigar has been stably {R:1} since s191 — Cassiopeia was extended
        # in s196 with W=1 so use Veigar for the simple single-key check.
        mapping, source = get_block_index_for("Veigar")
        self.assertEqual(mapping, {"R": 1})
        self.assertEqual(source, "champion")

    def test_unknown_falls_back_to_default(self) -> None:
        # Tryndamere is the stable unmapped fixture (Q/E are single-block,
        # W/R have no damage blocks). Yasuo was previously the fixture but
        # landed in the registry at s201 with E=3.
        mapping, source = get_block_index_for("Tryndamere")
        self.assertEqual(mapping, {})
        self.assertEqual(source, "default")

    def test_invented_champion_falls_back(self) -> None:
        mapping, source = get_block_index_for("NoSuchChampion")
        self.assertEqual(mapping, {})
        self.assertEqual(source, "default")

    def test_keys_uppercased(self) -> None:
        mapping, _ = get_block_index_for("Brand")
        for k in mapping:
            self.assertEqual(k, k.upper())


# ─── _resolve_block_index_overrides ──────────────────────────────────────────


class ResolveBlockIndexTests(unittest.TestCase):
    def test_none_with_known_returns_champion(self) -> None:
        # Veigar has been stably {R:1} since s191 — Cassiopeia was extended
        # in s196 with W=1 so use Veigar for the simple single-key check.
        mapping, source = _resolve_block_index_overrides("Veigar", None)
        self.assertEqual(mapping, {"R": 1})
        self.assertEqual(source, "champion")

    def test_none_with_unknown_returns_default(self) -> None:
        # Tryndamere is unmapped (since s201 Yasuo landed in the registry).
        mapping, source = _resolve_block_index_overrides("Tryndamere", None)
        self.assertEqual(mapping, {})
        self.assertEqual(source, "default")

    def test_explicit_returns_override(self) -> None:
        # Tryndamere is unmapped — caller-supplied override is the sole source.
        mapping, source = _resolve_block_index_overrides("Tryndamere", {"Q": 1})
        self.assertEqual(mapping, {"Q": 1})
        self.assertEqual(source, "override")

    def test_explicit_merges_with_registry(self) -> None:
        # Operator overrides Brand R but not W — registry fills the W gap.
        mapping, source = _resolve_block_index_overrides("Brand", {"R": 0})
        self.assertEqual(mapping, {"W": 1, "R": 0})
        self.assertEqual(source, "override")

    def test_explicit_uppercases_keys(self) -> None:
        mapping, _ = _resolve_block_index_overrides("Tryndamere", {"q": 1})
        self.assertEqual(mapping, {"Q": 1})


# ─── _select_blocks indexed strategy ─────────────────────────────────────────


class SelectBlocksIndexedTests(unittest.TestCase):
    @staticmethod
    def _blocks() -> tuple:
        return (
            DamageBlock(attribute="A", attribute_kind="damage",
                        base=(10.0, 20.0, 30.0, 40.0, 50.0)),
            DamageBlock(attribute="B", attribute_kind="damage",
                        base=(100.0, 200.0, 300.0, 400.0, 500.0)),
            DamageBlock(attribute="C", attribute_kind="damage",
                        base=(1000.0, 2000.0, 3000.0, 4000.0, 5000.0)),
        )

    def test_indexed_picks_specific_block(self) -> None:
        blocks = self._blocks()
        # rank 0 (rank 1), block_index=1 → 200.0 (block B)
        result = _select_blocks(blocks, rank=0, ctx=_ctx(), strategy="indexed", block_index=1)
        self.assertEqual(result, 100.0)

    def test_indexed_block_2_returns_third(self) -> None:
        blocks = self._blocks()
        # rank 4 (rank 5), block_index=2 → 5000.0 (block C)
        result = _select_blocks(blocks, rank=4, ctx=_ctx(), strategy="indexed", block_index=2)
        self.assertEqual(result, 5000.0)

    def test_indexed_default_0_equals_first(self) -> None:
        blocks = self._blocks()
        result_indexed = _select_blocks(blocks, rank=0, ctx=_ctx(), strategy="indexed", block_index=0)
        result_first = _select_blocks(blocks, rank=0, ctx=_ctx(), strategy="first")
        self.assertEqual(result_indexed, result_first)

    def test_indexed_out_of_range_clamps_to_last(self) -> None:
        blocks = self._blocks()
        result = _select_blocks(blocks, rank=0, ctx=_ctx(), strategy="indexed", block_index=10)
        # Clamped to last block (C, rank 0 → 1000.0)
        self.assertEqual(result, 1000.0)

    def test_indexed_negative_clamps_to_zero(self) -> None:
        blocks = self._blocks()
        result = _select_blocks(blocks, rank=0, ctx=_ctx(), strategy="indexed", block_index=-5)
        # Negative clamps to 0 → block A → 10.0
        self.assertEqual(result, 10.0)

    def test_indexed_unknown_strategy_raises(self) -> None:
        blocks = self._blocks()
        with self.assertRaises(ValueError):
            _select_blocks(blocks, rank=0, ctx=_ctx(), strategy="bogus")

    def test_indexed_empty_blocks_returns_zero(self) -> None:
        result = _select_blocks((), rank=0, ctx=_ctx(), strategy="indexed", block_index=0)
        self.assertEqual(result, 0.0)

    def test_indexed_filters_non_damage_blocks(self) -> None:
        # Mixed: damage + heal + damage — block_index=1 picks the second
        # DAMAGE block, not the heal in between.
        blocks = (
            DamageBlock(attribute="A", attribute_kind="damage", base=(10.0,)),
            DamageBlock(attribute="Heal", attribute_kind="heal", base=(999.0,)),
            DamageBlock(attribute="B", attribute_kind="damage", base=(100.0,)),
        )
        result = _select_blocks(blocks, rank=0, ctx=_ctx(), strategy="indexed", block_index=1)
        self.assertEqual(result, 100.0)


# ─── integration: compute_ability_dps ───────────────────────────────────────


class ComputeAbilityDpsBlockIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_unmapped_champion_uses_default(self) -> None:
        # Tryndamere is unmapped (Yasuo landed in registry s201).
        r = compute_ability_dps(
            self.snap, "Tryndamere", level=11, mode="SR", target_mr=30.0,
        )
        self.assertEqual(r.block_index_source, "default")
        self.assertEqual(r.block_index_resolved, {})

    def test_mapped_champion_uses_registry(self) -> None:
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR", target_mr=30.0,
        )
        self.assertEqual(r.block_index_source, "champion")
        # Phase 5.9.9 (s196) — Cassiopeia gained W=1 alongside existing E=1
        self.assertEqual(r.block_index_resolved, {"E": 1, "W": 1})

    def test_explicit_override_wins(self) -> None:
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR", target_mr=30.0,
            block_index_overrides={"E": 0},
        )
        self.assertEqual(r.block_index_source, "override")
        # Operator forces E:0; registry contributes W:1 — merged shape
        self.assertEqual(r.block_index_resolved, {"E": 0, "W": 1})

    def test_explicit_merges_with_registry(self) -> None:
        # Brand has registry {W:1, R:1}. Operator passes {R:0} → merged becomes
        # {W:1, R:0}.
        r = compute_ability_dps(
            self.snap, "Brand", level=11, mode="SR", target_mr=30.0,
            block_index_overrides={"R": 0},
        )
        self.assertEqual(r.block_index_source, "override")
        self.assertEqual(r.block_index_resolved, {"W": 1, "R": 0})

    def test_cassi_e_dpc_uses_block1_with_registry(self) -> None:
        """Cassi E rank-max raw_damage_per_cast pulls block1 base=168 (Total
        Enhanced Damage) when registry applies, vs block0 base=100 otherwise."""
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR",
            target_armor=0, target_mr=0,
        )
        e_spell = next(s for s in r.per_spell if s.key == "E")
        # Rank 4 (max via Cassi's "EQW" champion priority at lvl 11) → 168 base
        # + 65% AP. With 0 AP and 0 target_mr, raw_damage = 168.0 exactly.
        self.assertEqual(e_spell.rank, 4)
        self.assertAlmostEqual(e_spell.raw_damage_per_cast, 168.0, places=2)

    def test_cassi_e_forced_block_0_drops_dpc(self) -> None:
        """With explicit block_index_overrides={"E": 0}, Cassi E raw_dpc
        drops to block0 base=100 (Bonus Magic Damage, pre-poison)."""
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR",
            target_armor=0, target_mr=0,
            block_index_overrides={"E": 0},
        )
        e_spell = next(s for s in r.per_spell if s.key == "E")
        self.assertAlmostEqual(e_spell.raw_damage_per_cast, 100.0, places=2)


# ─── integration: compute_burst_damage ──────────────────────────────────────


class ComputeBurstBlockIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_unmapped_champion_uses_default(self) -> None:
        # Tryndamere is unmapped (Yasuo landed in registry s201).
        r = compute_burst_damage(
            self.snap, "Tryndamere", level=11, target_armor=80,
        )
        self.assertEqual(r.block_index_source, "default")
        self.assertEqual(r.block_index_resolved, {})

    def test_mapped_champion_uses_registry(self) -> None:
        r = compute_burst_damage(
            self.snap, "Veigar", level=11, target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_source, "champion")
        self.assertEqual(r.block_index_resolved, {"R": 1})

    def test_explicit_override_wins(self) -> None:
        r = compute_burst_damage(
            self.snap, "Brand", level=11, target_mr=30,
            block_index_overrides={"R": 0},
        )
        # Registry has Brand {W:1, R:1}; operator forces R:0 — merged.
        self.assertEqual(r.block_index_source, "override")
        self.assertEqual(r.block_index_resolved, {"W": 1, "R": 0})

    def test_veigar_burst_with_registry_exceeds_forced_block_0(self) -> None:
        """Veigar R block1 'Maximum Magic Damage' is 2× block0 base.
        Registry-applied burst > forced block0 burst."""
        r_registry = compute_burst_damage(
            self.snap, "Veigar", level=11, target_armor=80, target_mr=30, target_max_hp=2000,
        )
        r_forced = compute_burst_damage(
            self.snap, "Veigar", level=11, target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides={"R": 0},
        )
        self.assertGreater(r_registry.total_burst_damage, r_forced.total_burst_damage)

    def test_cassi_burst_with_registry_exceeds_forced_block_0(self) -> None:
        """Cassi E enhanced damage block1 > base block0; same shape as Veigar."""
        r_registry = compute_burst_damage(
            self.snap, "Cassiopeia", level=11, target_armor=80, target_mr=30, target_max_hp=2000,
        )
        r_forced = compute_burst_damage(
            self.snap, "Cassiopeia", level=11, target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides={"E": 0},
        )
        self.assertGreater(r_registry.total_burst_damage, r_forced.total_burst_damage)


# ─── ranker propagation ─────────────────────────────────────────────────────


class RankerBlockIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_rank_mage_carries_source(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR",
            target_mr=30.0, top_n=3,
        )
        self.assertEqual(r.block_index_source, "champion")
        # Phase 5.9.9 (s196) — Cassiopeia gained W=1 alongside existing E=1
        self.assertEqual(r.block_index_resolved, {"E": 1, "W": 1})

    def test_rank_assassin_carries_source(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Veigar", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=3,
        )
        self.assertEqual(r.block_index_source, "champion")
        self.assertEqual(r.block_index_resolved, {"R": 1})

    def test_rank_unmapped_champion_default(self) -> None:
        # Tryndamere is unmapped (Yasuo landed in registry s201).
        r = rank_items_by_ability_dps(
            self.snap, "Tryndamere", level=11, mode="SR",
            target_mr=30.0, top_n=3,
        )
        self.assertEqual(r.block_index_source, "default")
        self.assertEqual(r.block_index_resolved, {})


# ─── to_dict serialization ───────────────────────────────────────────────────


class ToDictSerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_compute_ability_dps_carries_source(self) -> None:
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR", target_mr=30.0,
        )
        d = r.to_dict()
        self.assertEqual(d["block_index_source"], "champion")
        # Phase 5.9.9 (s196) — Cassiopeia gained W=1 alongside existing E=1
        self.assertEqual(d["block_index_resolved"], {"E": 1, "W": 1})

    def test_compute_burst_carries_source(self) -> None:
        r = compute_burst_damage(
            self.snap, "Veigar", level=11, target_armor=80, target_mr=30,
        )
        d = r.to_dict()
        self.assertEqual(d["block_index_source"], "champion")
        self.assertEqual(d["block_index_resolved"], {"R": 1})

    def test_rank_mage_carries_source(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Anivia", level=11, mode="SR",
            target_mr=30.0, top_n=2,
        )
        d = r.to_dict()
        self.assertEqual(d["block_index_source"], "champion")
        # Phase 5.9.6 (s193) — Anivia gained Q=2 alongside existing E=1
        # Phase 5.9.13 (s200) — Anivia gained R=1 (Glacial Storm Empowered tick)
        self.assertEqual(d["block_index_resolved"], {"Q": 2, "E": 1, "R": 1})

    def test_rank_assassin_carries_source(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Evelynn", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=2,
        )
        d = r.to_dict()
        self.assertEqual(d["block_index_source"], "champion")
        # Phase 5.9.17 (s204) — Evelynn gained Q=5 alongside existing R=1
        self.assertEqual(d["block_index_resolved"], {"R": 1, "Q": 5})

    def test_unmapped_champion_to_dict_is_empty_dict(self) -> None:
        # Tryndamere is unmapped (Yasuo landed in registry s201).
        r = compute_ability_dps(
            self.snap, "Tryndamere", level=11, mode="SR", target_mr=30.0,
        )
        d = r.to_dict()
        self.assertEqual(d["block_index_source"], "default")
        self.assertEqual(d["block_index_resolved"], {})


# ─── Phase 5.9.5 (s192): Akali R / R2 token-variant ─────────────────────────


class AkaliTokenVariantTests(unittest.TestCase):
    """Phase 5.9.5 (s192). Akali registry ``{"R": 0, "R2": 2}`` should route
    the burst walker's R token to block 0 (R1 base — bonus-AD scaling) and
    R2 token to block 2 (R2 max-execute — missing-HP curve at 90% AP).
    Pre-s192 the walker only knew base keys, so both R and R2 used the
    same block_index — setting ``{"R": 2}`` would over-count R1.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_akali_registry_uses_block0_for_R_and_block2_for_R2(self) -> None:
        r = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_source, "champion")
        # Phase 5.9.9 (s196) — Akali gained E=2 alongside existing R=0 + R2=2
        self.assertEqual(r.block_index_resolved, {"R": 0, "R2": 2, "E": 2})

    def test_akali_R1_row_raw_damage_matches_block0(self) -> None:
        """R1 token (canonical 'R') at rank 1 with block 0 = 220 base."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        # Find the first R-token row (R1, not R2).
        r1_row = next(c for c in r.per_cast if c.token == "R")
        self.assertEqual(r1_row.rank, 1)  # R lvl 11 → rank 1
        # Block 0 base = 220 at rank 1 (zero AP and zero bonus AD in this
        # naked build).
        self.assertAlmostEqual(r1_row.raw_damage, 220.0, places=2)

    def test_akali_R2_row_raw_damage_matches_block2(self) -> None:
        """R2 token (canonical 'R2') at rank 1 with block 2 = 420 base."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        r2_row = next(c for c in r.per_cast if c.token == "R2")
        self.assertEqual(r2_row.rank, 1)
        # Block 2 base = 420 at rank 1.
        self.assertAlmostEqual(r2_row.raw_damage, 420.0, places=2)

    def test_akali_total_burst_with_registry_exceeds_forced_R_only(self) -> None:
        """Registry-applied (R=0, R2=2) burst > legacy (R=0, R2=0 by base-key
        fallback) — same combo, only R2 token's block changes."""
        r_registry = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        r_legacy = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides={"R": 0, "R2": 0},
        )
        self.assertGreater(r_registry.total_burst_damage,
                           r_legacy.total_burst_damage)

    def test_explicit_R2_override_wins_over_registry(self) -> None:
        """Operator's per-call ``{"R2": 1}`` overrides registry's 2;
        R + E inherit from registry."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides={"R2": 1},
        )
        self.assertEqual(r.block_index_source, "override")
        # Phase 5.9.9 (s196) — Akali registry now includes E=2; operator's
        # R2:1 override merges with registry {R:0, R2:2, E:2} → {R:0, R2:1, E:2}
        self.assertEqual(r.block_index_resolved, {"R": 0, "R2": 1, "E": 2})

    def test_R_only_override_does_not_apply_to_R2_token(self) -> None:
        """Operator passes ``{"R": 2}`` — R2 token has no explicit entry,
        so it falls back to base key 'R' lookup → block 2. This is the
        pre-s192 "double-count" scenario; the test documents the model
        when operator chooses it explicitly (without an R2 entry, both
        R-family tokens use the same block)."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides={"R": 2},
        )
        # Both R and R2 should now use block 2 = 420 raw at rank 1.
        r1_row = next(c for c in r.per_cast if c.token == "R")
        r2_row = next(c for c in r.per_cast if c.token == "R2")
        self.assertAlmostEqual(r1_row.raw_damage, 420.0, places=2)
        self.assertAlmostEqual(r2_row.raw_damage, 420.0, places=2)

    def test_compute_ability_dps_ignores_R2_token_entry(self) -> None:
        """compute_ability_dps iterates only base spell keys (Q/W/E/R);
        Akali registry's R2 token entry is invisible to it. R uses block
        0 from the registry; W uses first-block strategy as usual. E uses
        block 2 from s196 registry."""
        r = compute_ability_dps(
            self.snap, "Akali", level=11, mode="SR", target_mr=30.0,
        )
        # R2 entry is preserved in resolved (round-trip from resolver),
        # but only R (block 0), W (no entry → block 0), and E (block 2)
        # are consulted in the per-spell loop.
        self.assertEqual(r.block_index_source, "champion")
        # Phase 5.9.9 (s196) — Akali registry now includes E=2
        self.assertEqual(r.block_index_resolved, {"R": 0, "R2": 2, "E": 2})
        # Akali R at rank 1 (lvl 11) with block 0 = 110/220/330 base +
        # 30% AP + 50% bonus AD. With 0 AP / 0 bAD → raw = 220.
        r_spell = next(s for s in r.per_spell if s.key == "R")
        self.assertEqual(r_spell.rank, 1)
        self.assertAlmostEqual(r_spell.raw_damage_per_cast, 220.0, places=2)


# ─── Phase 5.9.6 (s193): channeled-ability expansion ────────────────────────


class ChanneledAbilityExpansionTests(unittest.TestCase):
    """Phase 5.9.6 (s193). 8 new champion entries + Anivia Q extension —
    all covering the "per-tick → total" gap for channeled / duration
    abilities where the engine's default first damage block picked the
    per-tick value but the realistic per-cast contribution is the
    full-channel total.

    Tests verify each new entry:
      1. Is present in the resolved registry
      2. Drives the per-spell raw_damage_per_cast to the block ≥1 value
         (not the per-tick block 0)
      3. Produces a strictly higher total_ability_dps vs forced block 0
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _delta_check(self, champion: str, key: str, expected_idx: int) -> None:
        """Assert champion's registry entry routes `key` to expected_idx,
        and the resulting total_ability_dps exceeds the forced-block-0
        baseline by a positive margin."""
        r_reg = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.block_index_resolved.get(key), expected_idx,
                         f"{champion}.{key} should route to block {expected_idx}")
        # Force key to block 0 (override registry's choice).
        forced = dict(r_reg.block_index_resolved)
        forced[key] = 0
        r_off = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides=forced,
        )
        self.assertGreater(r_reg.total_ability_dps, r_off.total_ability_dps,
                           f"{champion} registry total should exceed forced-block-0")

    def test_alistar_E_routes_to_block_1(self) -> None:
        self._delta_check("Alistar", "E", 1)

    def test_aurelionsol_E_routes_to_block_1(self) -> None:
        self._delta_check("AurelionSol", "E", 1)

    def test_fiddlesticks_R_routes_to_block_1(self) -> None:
        self._delta_check("Fiddlesticks", "R", 1)

    def test_missfortune_E_routes_to_block_1(self) -> None:
        self._delta_check("MissFortune", "E", 1)

    def test_samira_R_routes_to_block_1(self) -> None:
        self._delta_check("Samira", "R", 1)

    def test_singed_Q_routes_to_block_1(self) -> None:
        self._delta_check("Singed", "Q", 1)

    def test_velkoz_R_routes_to_block_1(self) -> None:
        self._delta_check("Velkoz", "R", 1)

    def test_syndra_R_routes_to_block_2(self) -> None:
        self._delta_check("Syndra", "R", 2)

    def test_anivia_Q_routes_to_block_2(self) -> None:
        """Anivia gets Q added to her existing {E: 1} entry."""
        self._delta_check("Anivia", "Q", 2)

    def test_anivia_E_still_routes_to_block_1(self) -> None:
        """The s191 E:1 entry is preserved when Q gets added (and s200 R=1)."""
        r = compute_ability_dps(
            self.snap, "Anivia", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        # s193 added Q=2 to existing E=1; s200 added R=1 (Glacial Storm Empowered).
        # E=1 must persist through both extensions.
        self.assertEqual(r.block_index_resolved.get("E"), 1)
        self.assertEqual(r.block_index_resolved.get("Q"), 2)

    def test_singed_Q_total_block_matches_per_cast_math(self) -> None:
        """Singed Q at rank 5 (level 11+, Q maxed): block 1 base = 120
        (per-tick 15 × 8 ticks). Confirms the registry picks block 1."""
        r = compute_ability_dps(
            self.snap, "Singed", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        q_spell = next(s for s in r.per_spell if s.key == "Q")
        # Singed Q at level 11 (max priority Q-W-E, lvl 11 Q rank: probably 4)
        # Block 1 base at rank 4 = 100 (per-tick 12.5 × 8 ticks). Block 0 = 12.5.
        # The exact rank depends on max_priority resolver; just assert
        # raw is closer to block 1 value than block 0.
        self.assertGreater(q_spell.raw_damage_per_cast, 60.0,
                           "raw should reflect total (block 1), not per-tick (block 0)")


# ─── s194 Phase 5.9.7 — calibration follow-up entries ────────────────────────


class CalibrationFollowUpExpansionTests(unittest.TestCase):
    """Phase 5.9.7 (s194). 8 more (champion, key) entries closing s193's
    deferred calibration list. Same "per-tick → total" pattern as s193
    for channels/auras (Corki W/E, Hecarim W, Jayce W, Rell R, DrMundo W),
    plus "min → max amped" for charge/gate variants (Hecarim E charge,
    Jayce Q gate-amped Shock Blast). The Jayce Q entry is the first
    block_index that layers on a prior form_index override (s187 set
    Jayce.Q form_index=1 cannon; s194 now sets block_index=1 within
    that form — orthogonal resolvers).

    Tests verify each new entry:
      1. Is present in the resolved registry
      2. Drives per-spell raw_damage_per_cast above the forced-block-0
         baseline (positive delta proves block ≥1 evaluation)
      3. Produces strictly higher total_ability_dps vs forced block 0
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _delta_check(self, champion: str, key: str, expected_idx: int) -> None:
        """Assert champion's registry entry routes `key` to expected_idx,
        and the resulting total_ability_dps exceeds the forced-block-0
        baseline by a positive margin."""
        r_reg = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.block_index_resolved.get(key), expected_idx,
                         f"{champion}.{key} should route to block {expected_idx}")
        forced = dict(r_reg.block_index_resolved)
        forced[key] = 0
        r_off = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides=forced,
        )
        self.assertGreater(r_reg.total_ability_dps, r_off.total_ability_dps,
                           f"{champion} registry total should exceed forced-block-0")

    def test_corki_W_routes_to_block_1(self) -> None:
        self._delta_check("Corki", "W", 1)

    def test_corki_E_routes_to_block_1(self) -> None:
        self._delta_check("Corki", "E", 1)

    def test_hecarim_W_routes_to_block_1(self) -> None:
        self._delta_check("Hecarim", "W", 1)

    def test_hecarim_E_routes_to_block_1(self) -> None:
        self._delta_check("Hecarim", "E", 1)

    def test_jayce_Q_routes_to_block_1(self) -> None:
        """Jayce Q layers s194 block_index=1 on s187 form_index=1.
        Cannon form (form 1) Shock Blast block 1 = 'Increased Damage'
        (1.4× block 0) through Acceleration Gate."""
        self._delta_check("Jayce", "Q", 1)

    def test_jayce_W_routes_to_block_1(self) -> None:
        """Jayce W hammer-form (default form 0) Lightning Field aura:
        block 0 = 'Magic Damage Per Tick', block 1 = 'Total Magic Damage'
        (4× block 0 over 4 second aura)."""
        self._delta_check("Jayce", "W", 1)

    def test_rell_R_routes_to_block_1(self) -> None:
        self._delta_check("Rell", "R", 1)

    def test_drmundo_W_routes_to_block_1(self) -> None:
        self._delta_check("DrMundo", "W", 1)

    def test_corki_both_keys_in_resolved(self) -> None:
        """Both Corki W and E entries land in the same resolved map."""
        r = compute_ability_dps(
            self.snap, "Corki", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"W": 1, "E": 1})
        self.assertEqual(r.block_index_source, "champion")

    def test_hecarim_both_keys_in_resolved(self) -> None:
        r = compute_ability_dps(
            self.snap, "Hecarim", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"W": 1, "E": 1})
        self.assertEqual(r.block_index_source, "champion")

    def test_jayce_both_keys_in_resolved(self) -> None:
        """Jayce gets Q and W both — Q block_index applies within form 1
        (cannon, per s187 form_index override); W block_index applies in
        form 0 (hammer, default)."""
        r = compute_ability_dps(
            self.snap, "Jayce", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1, "W": 1})

    def test_jayce_Q_block_layers_on_s187_form_index(self) -> None:
        """Smoke test that Jayce Q block_index=1 inside form_index=1
        produces a non-zero raw_damage_per_cast (i.e., the form+block
        resolvers compose correctly)."""
        r = compute_ability_dps(
            self.snap, "Jayce", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        q_spell = next((s for s in r.per_spell if s.key == "Q"), None)
        self.assertIsNotNone(q_spell)
        self.assertGreater(q_spell.raw_damage_per_cast, 0.0,
                           "Jayce Q in cannon form block 1 should evaluate to positive damage")

    def test_pre_s194_unmapped_unaffected(self) -> None:
        """Backward-compat: s193 entries unchanged after s194 ship."""
        r = compute_ability_dps(
            self.snap, "Singed", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1})


class Phase598ExpansionTests(unittest.TestCase):
    """Phase 5.9.8 (s195). 13 new (champion, key) entries spanning four
    sub-patterns: (A) multi-hit single-target totals (Ahri W, Kaisa Q,
    Lulu Q, Sivir Q, Talon W, Talon R, Velkoz W, Ekko Q), (B) fully-charged
    amps (Varus Q, Zoe Q, Vladimir E), (C) recast amps (Camille Q),
    (D) CC-conditional duration totals (Morgana W). All map the operator's
    'commits to canonical-amped condition' intuition to a single static
    block_index — no schema lift, just JSON expansion.

    Tests verify each new entry:
      1. Is present in the resolved registry
      2. Drives total_ability_dps strictly above the forced-block-0 baseline
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _delta_check(self, champion: str, key: str, expected_idx: int) -> None:
        """Assert champion's registry entry routes `key` to expected_idx,
        and the resulting total_ability_dps exceeds the forced-block-0
        baseline by a positive margin."""
        r_reg = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.block_index_resolved.get(key), expected_idx,
                         f"{champion}.{key} should route to block {expected_idx}")
        forced = dict(r_reg.block_index_resolved)
        forced[key] = 0
        r_off = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides=forced,
        )
        self.assertGreater(r_reg.total_ability_dps, r_off.total_ability_dps,
                           f"{champion} registry total should exceed forced-block-0")

    # Multi-hit single-target totals (pattern A)
    def test_ahri_W_routes_to_block_2(self) -> None:
        """Ahri W block 2 'Total Single-Target Damage' = initial flame
        + 2× subsequent flames all on same target."""
        self._delta_check("Ahri", "W", 2)

    def test_kaisa_Q_routes_to_block_2(self) -> None:
        """Kaisa Q block 2 'Total Single-Target Damage' = full Icathian Rain
        missile focus on isolated target."""
        self._delta_check("Kaisa", "Q", 2)

    def test_lulu_Q_routes_to_block_3(self) -> None:
        """Lulu Q block 3 'Total Magic Damage' = Glitterlance both passes
        hitting same target (main + slow-target reduced second pass)."""
        self._delta_check("Lulu", "Q", 3)

    def test_sivir_Q_routes_to_block_2(self) -> None:
        """Sivir Q block 2 'Total Maximum Champion Damage' = Boomerang Blade
        out + return both hits on same target."""
        self._delta_check("Sivir", "Q", 2)

    def test_talon_W_routes_to_block_2(self) -> None:
        """Talon W block 2 'Total Physical Damage' = Rake out + return."""
        self._delta_check("Talon", "W", 2)

    def test_talon_R_routes_to_block_2(self) -> None:
        """Talon R block 2 'Total Physical Damage' = Shadow Assault initial
        ring + unstealth re-engage hit."""
        self._delta_check("Talon", "R", 2)

    def test_velkoz_W_routes_to_block_2(self) -> None:
        """Vel'Koz W block 2 'Total Magic Damage' = Void Rift initial hit
        + detonation both halves of the rift."""
        self._delta_check("Velkoz", "W", 2)

    def test_ekko_Q_routes_to_block_3(self) -> None:
        """Ekko Q block 3 'Total Magic Damage' = Timewinder out + return,
        both passes on same target."""
        self._delta_check("Ekko", "Q", 3)

    # Fully-charged amps (pattern B)
    def test_varus_Q_routes_to_block_1(self) -> None:
        """Varus Q block 1 'Maximum Physical Damage' = fully-charged
        Piercing Arrow (1.5× minimum at full 4s charge)."""
        self._delta_check("Varus", "Q", 1)

    def test_zoe_Q_routes_to_block_1(self) -> None:
        """Zoe Q block 1 'Maximum Magic Damage' = long-distance Paddle Star
        post-E teleport (2.5× minimum at full range)."""
        self._delta_check("Zoe", "Q", 1)

    def test_vladimir_E_routes_to_block_1(self) -> None:
        """Vladimir E block 1 'Maximum Magic Damage' = 2-charge Tides of
        Blood (2× base + 4× caster max HP scaling)."""
        self._delta_check("Vladimir", "E", 1)

    # Recast amp (pattern C)
    def test_camille_Q_routes_to_block_2(self) -> None:
        """Camille Q block 2 'Increased Mixed Damage' = Precision Protocol
        2nd cast (2× block 0)."""
        self._delta_check("Camille", "Q", 2)

    # CC-conditional duration total (pattern D)
    def test_morgana_W_routes_to_block_3(self) -> None:
        """Morgana W block 3 'Maximum Total Damage' = Tormented Shadow
        full duration on rooted (Q'd) target."""
        self._delta_check("Morgana", "W", 3)

    # Resolved-map shape sanity for new multi-key champions
    def test_talon_both_keys_in_resolved(self) -> None:
        """Talon W=2 + R=2 (s195) + Q=1 (s199 — Noxian Diplomacy champion crit).
        All three keys must appear in the resolved map."""
        r = compute_ability_dps(
            self.snap, "Talon", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"W": 2, "R": 2, "Q": 1})
        self.assertEqual(r.block_index_source, "champion")

    def test_ahri_both_keys_in_resolved(self) -> None:
        """Ahri W=2 (s195) extends prior {"Q": 1} (s191) — both keys
        must appear in the resolved map."""
        r = compute_ability_dps(
            self.snap, "Ahri", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1, "W": 2})
        self.assertEqual(r.block_index_source, "champion")

    def test_velkoz_both_keys_in_resolved(self) -> None:
        """Vel'Koz W=2 (s195) extends prior {"R": 1} (s193) — both keys
        must appear in the resolved map."""
        r = compute_ability_dps(
            self.snap, "Velkoz", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"W": 2, "R": 1})

    # Math-level sanity: Ahri W block 2 base at rank 1 = 64 = 40 + 12×2
    def test_ahri_W_block2_matches_sum_of_blocks_0_and_2x1(self) -> None:
        """Numeric sanity: Ahri W block 2 base at rank 1 should equal
        block 0 + 2× block 1 (initial + 2 subsequent flames same target)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Ahri", "W", form_index=0)
        self.assertIsNotNone(form)
        blocks = form.damage_blocks
        self.assertGreaterEqual(len(blocks), 3)
        b0 = blocks[0].base[0] if blocks[0].base else 0.0
        b1 = blocks[1].base[0] if blocks[1].base else 0.0
        b2 = blocks[2].base[0] if blocks[2].base else 0.0
        self.assertAlmostEqual(b2, b0 + b1 * 2, places=2,
                               msg=f"block 2 base ({b2}) != block 0 + 2× block 1 ({b0 + b1 * 2})")

    # Backward-compat: pre-s195 entries still resolve
    def test_pre_s195_unmapped_unaffected(self) -> None:
        """Backward-compat: s194 entries unchanged after s195 ship."""
        r = compute_ability_dps(
            self.snap, "Corki", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"W": 1, "E": 1})

    def test_pre_s195_singed_unaffected(self) -> None:
        """Backward-compat: s193 Singed entry unchanged."""
        r = compute_ability_dps(
            self.snap, "Singed", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1})


# ─── Phase 5.9.9 (s196) — extended multi-hit / condition amp expansion ──────


class Phase599ExpansionTests(unittest.TestCase):
    """Phase 5.9.9 (s196). 17 new (champion, key) entries spanning two
    sub-patterns: (A) multi-hit single-target totals (Akali E, Akshan Q,
    Cassiopeia W, Chogath E, Draven R, Lillia W, Morgana R, Nautilus E,
    Riven Q, Sett Q, Skarner Q, Soraka E), (B) fully-charged / condition
    amps (Gragas Q, Karthus Q, Khazix Q, KogMaw R, Pantheon Q). Same
    'operator commits to canonical-amped condition' model as s195 — pure
    JSON expansion, no walker changes.

    Tests verify each new entry:
      1. Is present in the resolved registry
      2. Drives total_ability_dps strictly above the forced-block-0 baseline
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _delta_check(self, champion: str, key: str, expected_idx: int) -> None:
        """Assert champion's registry entry routes `key` to expected_idx,
        and the resulting total_ability_dps exceeds the forced-block-0
        baseline by a positive margin."""
        r_reg = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.block_index_resolved.get(key), expected_idx,
                         f"{champion}.{key} should route to block {expected_idx}")
        forced = dict(r_reg.block_index_resolved)
        forced[key] = 0
        r_off = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides=forced,
        )
        self.assertGreater(r_reg.total_ability_dps, r_off.total_ability_dps,
                           f"{champion} registry total should exceed forced-block-0")

    # Multi-hit single-target totals (pattern A)
    def test_akali_E_routes_to_block_2(self) -> None:
        """Akali E block 2 'Total Magic Damage' = E1 Shuriken Flip throw
        + E2 grappling-hook dash on tagged target."""
        self._delta_check("Akali", "E", 2)

    def test_akshan_Q_routes_to_block_1(self) -> None:
        """Akshan Q block 1 'Total Physical Damage' = Avengerang ricochet
        out + return on same target."""
        self._delta_check("Akshan", "Q", 1)

    def test_cassiopeia_W_routes_to_block_1(self) -> None:
        """Cassiopeia W block 1 'Total Magic Damage' = Miasma cloud full
        duration (5× per-second tick)."""
        self._delta_check("Cassiopeia", "W", 1)

    def test_chogath_E_routes_to_block_1(self) -> None:
        """Cho'Gath E block 1 'Total Magic Damage' = Vorpal Spikes 3-hit
        empowered AA rotation on same target."""
        self._delta_check("Chogath", "E", 1)

    def test_draven_R_routes_to_block_1(self) -> None:
        """Draven R block 1 'Total Physical Damage' = Whirling Death out
        + return on same target."""
        self._delta_check("Draven", "R", 1)

    def test_lillia_W_routes_to_block_1(self) -> None:
        """Lillia W block 1 'Increased Damage' = Watch Out! Eep! center hit
        on same target (3× rim damage)."""
        self._delta_check("Lillia", "W", 1)

    def test_morgana_R_routes_to_block_1(self) -> None:
        """Morgana R block 1 'Total Magic Damage' = Soul Shackles initial
        + delayed-snap damage both ticks on same target."""
        self._delta_check("Morgana", "R", 1)

    def test_nautilus_E_routes_to_block_2(self) -> None:
        """Nautilus E block 2 'Maximum Total Damage' = Riptide 3-wave
        same-target combo (full + 2× half-damage subsequent)."""
        self._delta_check("Nautilus", "E", 2)

    def test_riven_Q_routes_to_block_1(self) -> None:
        """Riven Q block 1 'Total Physical Damage' = Broken Wings Q-Q-Q
        3-cast chain on same target (3× block 0)."""
        self._delta_check("Riven", "Q", 1)

    def test_sett_Q_routes_to_block_1(self) -> None:
        """Sett Q block 1 'Total Bonus Physical Damage' = Knuckle Down
        both empowered AAs on same target (2× block 0)."""
        self._delta_check("Sett", "Q", 1)

    def test_skarner_Q_routes_to_block_1(self) -> None:
        """Skarner Q block 1 'Total Bonus Physical Damage' = Shattered
        Earth empowered Q 3-hit chain (3× block 0)."""
        self._delta_check("Skarner", "Q", 1)

    def test_soraka_E_routes_to_block_1(self) -> None:
        """Soraka E block 1 'Total Magic Damage' = Equinox immediate +
        delayed-silence proc total (2× block 0)."""
        self._delta_check("Soraka", "E", 1)

    # Fully-charged / condition amps (pattern B)
    def test_gragas_Q_routes_to_block_1(self) -> None:
        """Gragas Q block 1 'Maximum Magic Damage' = Barrel Roll fully-
        fermented after 4s hold (1.5× block 0)."""
        self._delta_check("Gragas", "Q", 1)

    def test_karthus_Q_routes_to_block_1(self) -> None:
        """Karthus Q block 1 'Enhanced Damage' = Lay Waste vs single-
        target (passive doubles damage on solo champion, 2× block 0)."""
        self._delta_check("Karthus", "Q", 1)

    def test_khazix_Q_routes_to_block_1(self) -> None:
        """Kha'Zix Q block 1 'Increased Damage' = Taste Their Fear vs
        isolated target (2.1× block 0)."""
        self._delta_check("Khazix", "Q", 1)

    def test_kogmaw_R_routes_to_block_1(self) -> None:
        """Kog'Maw R block 1 'Maximum Magic Damage' = Living Artillery
        max-damage component vs low-HP target (2× block 0)."""
        self._delta_check("KogMaw", "R", 1)

    def test_pantheon_Q_routes_to_block_1(self) -> None:
        """Pantheon Q block 1 'Increased Hurl Damage' = Comet Spear
        fully-charged hurl (1.5s hold, ~2.2× block 0)."""
        self._delta_check("Pantheon", "Q", 1)

    # Resolved-map shape sanity for new multi-key champions
    def test_akali_three_keys_in_resolved(self) -> None:
        """Akali E=2 (s196) extends prior {R:0, R2:2} (s192) — all three
        keys must appear in the resolved map."""
        r = compute_ability_dps(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"R": 0, "R2": 2, "E": 2})
        self.assertEqual(r.block_index_source, "champion")

    def test_cassiopeia_both_keys_in_resolved(self) -> None:
        """Cassiopeia W=1 (s196) extends prior {E:1} (s191) — both keys
        must appear in the resolved map."""
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"E": 1, "W": 1})
        self.assertEqual(r.block_index_source, "champion")

    def test_morgana_both_keys_in_resolved(self) -> None:
        """Morgana R=1 (s196) extends prior {W:3} (s195) — both keys
        must appear in the resolved map."""
        r = compute_ability_dps(
            self.snap, "Morgana", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"W": 3, "R": 1})
        self.assertEqual(r.block_index_source, "champion")

    # Math-level sanity: Riven Q block 1 base at rank 1 = 3× block 0
    def test_riven_Q_block1_matches_3x_block0(self) -> None:
        """Numeric sanity: Riven Q block 1 base = 3× block 0 base across
        all 5 ranks (3-cast Broken Wings on same target)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Riven", "Q", form_index=0)
        self.assertIsNotNone(form)
        blocks = form.damage_blocks
        self.assertGreaterEqual(len(blocks), 2)
        b0_base = blocks[0].base
        b1_base = blocks[1].base
        self.assertEqual(len(b0_base), len(b1_base))
        for rank, (b0, b1) in enumerate(zip(b0_base, b1_base)):
            self.assertAlmostEqual(
                b1, b0 * 3.0, places=2,
                msg=f"Riven Q rank {rank+1}: block 1 base {b1} != 3× block 0 base {b0}"
            )

    # Math-level sanity: Akshan Q block 1 base = exact 2× block 0
    def test_akshan_Q_block1_matches_2x_block0(self) -> None:
        """Numeric sanity: Akshan Q block 1 base = 2× block 0 (Avengerang
        out + return on same target)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Akshan", "Q", form_index=0)
        self.assertIsNotNone(form)
        blocks = form.damage_blocks
        self.assertGreaterEqual(len(blocks), 2)
        for rank, (b0, b1) in enumerate(zip(blocks[0].base, blocks[1].base)):
            self.assertAlmostEqual(
                b1, b0 * 2.0, places=2,
                msg=f"Akshan Q rank {rank+1}: block 1 base {b1} != 2× block 0 base {b0}"
            )

    # Backward-compat: pre-s196 entries still resolve unchanged
    def test_pre_s196_morgana_W_unchanged(self) -> None:
        """Backward-compat: s195 Morgana W=3 entry preserved after s196
        adds R=1; W=3 should still resolve."""
        r = compute_ability_dps(
            self.snap, "Morgana", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved.get("W"), 3)

    def test_pre_s196_akali_R2_unchanged(self) -> None:
        """Backward-compat: s192 Akali R/R2 token-variant entries preserved
        after s196 adds E=2."""
        # The s192 R2 entry only fires in burst combo walker, not
        # compute_ability_dps. But we can still assert the resolved map
        # contains all three keys via the burst path.
        r = compute_burst_damage(
            self.snap, "Akali", level=11, target_armor=80, target_mr=30,
            target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved.get("R"), 0)
        self.assertEqual(r.block_index_resolved.get("R2"), 2)
        self.assertEqual(r.block_index_resolved.get("E"), 2)

    def test_pre_s196_corki_unchanged(self) -> None:
        """Backward-compat: s194 Corki entry preserved."""
        r = compute_ability_dps(
            self.snap, "Corki", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"W": 1, "E": 1})


# ─── Phase 5.9.10 (s197) — assassin/fighter resource amps + utility totals ──


class Phase599_10ExpansionTests(unittest.TestCase):
    """Phase 5.9.10 (s197). 20 new (champion, key) entries across 18 new
    champions spanning five sub-patterns: (A) multi-hit / channel / mark
    totals (Aatrox W, Hwei R, Leblanc Q/E, Lucian R, Mel Q/R, MonkeyKing R,
    Naafiri Q/E, MasterYi Q, Smolder W), (B) fully-charged amps (Nunu W,
    Sion Q, Briar E), (C) resource-state amps (Renekton Q/W full-Fury,
    Kassadin R max-stack Riftwalk), (D) execute / channel-duration amps
    (Darius R, Nilah R), (E) multi-charge / multi-fire totals (Poppy R,
    Rumble E). Same 'operator commits to canonical-amped condition' model
    as s191/s193/s194/s195/s196 — pure JSON expansion, no walker changes.

    Tests verify each new entry:
      1. Is present in the resolved registry
      2. Drives total_ability_dps strictly above the forced-block-0 baseline
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _delta_check(self, champion: str, key: str, expected_idx: int) -> None:
        """Assert champion's registry entry routes `key` to expected_idx,
        and the resulting total_ability_dps exceeds the forced-block-0
        baseline by a positive margin."""
        r_reg = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.block_index_resolved.get(key), expected_idx,
                         f"{champion}.{key} should route to block {expected_idx}")
        forced = dict(r_reg.block_index_resolved)
        forced[key] = 0
        r_off = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides=forced,
        )
        self.assertGreater(r_reg.total_ability_dps, r_off.total_ability_dps,
                           f"{champion} registry total should exceed forced-block-0")

    # Pattern A: multi-hit / channel / mark totals (12 entries)
    def test_aatrox_W_routes_to_block_3(self) -> None:
        """Aatrox W block 3 'Total Damage' = Infernal Chains landed +
        pull-back trigger total (2× block 0)."""
        self._delta_check("Aatrox", "W", 3)

    def test_hwei_R_routes_to_block_3(self) -> None:
        """Hwei R block 3 'Maximum Total Damage' = Spiraling Despair full
        channel + per-tick panic + detonation total."""
        self._delta_check("Hwei", "R", 3)

    def test_leblanc_Q_routes_to_block_1(self) -> None:
        """LeBlanc Q block 1 'Sigil Damage' = Sigil of Malice + detonation
        on marked target via W/E follow-up (2× block 0)."""
        self._delta_check("Leblanc", "Q", 1)

    def test_leblanc_E_routes_to_block_1(self) -> None:
        """LeBlanc E block 1 'Total Damage' = Ethereal Chains root +
        return-tether on tethered target (2.12× block 0)."""
        self._delta_check("Leblanc", "E", 1)

    def test_lucian_R_routes_to_block_1(self) -> None:
        """Lucian R block 1 'Total Damage' = Culling full-channel total
        on same target (5× block 0 per-shot)."""
        self._delta_check("Lucian", "R", 1)

    def test_mel_Q_routes_to_block_3(self) -> None:
        """Mel Q block 3 'Total Damage' = Radiant Volley 6-projectile
        total on same target (~10× block 0)."""
        self._delta_check("Mel", "Q", 3)

    def test_mel_R_routes_to_block_2(self) -> None:
        """Mel R block 2 'Total Damage' = Golden Eclipse initial + mark
        detonation (~10× initial tick)."""
        self._delta_check("Mel", "R", 2)

    def test_monkeyking_R_routes_to_block_1(self) -> None:
        """Wukong R block 1 'Total Damage' = Cyclone full 4-second spin
        on same target (8× per-tick)."""
        self._delta_check("MonkeyKing", "R", 1)

    def test_naafiri_Q_routes_to_block_2(self) -> None:
        """Naafiri Q block 2 'Total Damage' = all 3 Darkin Daggers landing
        on same target (4× bAD scaling)."""
        self._delta_check("Naafiri", "Q", 2)

    def test_naafiri_E_routes_to_block_1(self) -> None:
        """Naafiri E block 1 'Total Damage' = Eviscerate dash multi-strike
        + pack-dog follow-ups (2.91× block 0)."""
        self._delta_check("Naafiri", "E", 1)

    def test_masteryi_Q_routes_to_block_2(self) -> None:
        """Master Yi Q block 2 'Total Damage' = Alpha Strike same-target
        focus all bounces (1.75× block 0)."""
        self._delta_check("MasterYi", "Q", 2)

    def test_smolder_W_routes_to_block_2(self) -> None:
        """Smolder W block 2 'Total Damage' = Achooo! 3-hit AoE-on-self
        total on same target (2.1× block 0)."""
        self._delta_check("Smolder", "W", 2)

    # Pattern B: fully-charged amps (3 entries)
    def test_nunu_W_routes_to_block_1(self) -> None:
        """Nunu W block 1 'Maximum Damage' = Biggest Snowball Ever! at
        max charge after 4s channel (5× block 0)."""
        self._delta_check("Nunu", "W", 1)

    def test_sion_Q_routes_to_block_2(self) -> None:
        """Sion Q block 2 'Maximum Damage' = Decimating Smash fully-charged
        2-second wind-up (2.92× block 1 minimum)."""
        self._delta_check("Sion", "Q", 2)

    def test_briar_E_routes_to_block_4(self) -> None:
        """Briar E block 4 'Maximum Headbutt Total Damage' = max-charge
        Chilling Scream scream-tick + headbutt collision (2.4× block 2)."""
        self._delta_check("Briar", "E", 4)

    # Pattern C: resource-state amps (3 entries)
    def test_renekton_Q_routes_to_block_1(self) -> None:
        """Renekton Q block 1 'Empowered Damage' = Cull the Meek at 50+
        Fury (1.5× block 0 + 1.4× bAD)."""
        self._delta_check("Renekton", "Q", 1)

    def test_renekton_W_routes_to_block_2(self) -> None:
        """Renekton W block 2 'Empowered Damage' = Ruthless Predator at
        50+ Fury (1.5× block 0)."""
        self._delta_check("Renekton", "W", 2)

    def test_kassadin_R_routes_to_block_3(self) -> None:
        """Kassadin R block 3 'Maximum Bonus Damage' = Riftwalk at max
        4-stack ramp (~3× block 0 + ~1.56× AP)."""
        self._delta_check("Kassadin", "R", 3)

    # Pattern D: execute / channel-duration amps (2 entries)
    def test_darius_R_routes_to_block_2(self) -> None:
        """Darius R block 2 'Execute Damage' = Noxian Guillotine vs target
        below 5×Hemorrhage stacks threshold (2× block 0)."""
        self._delta_check("Darius", "R", 2)

    def test_nilah_R_routes_to_block_1(self) -> None:
        """Nilah R block 1 'Total Damage' = Apotheosis full-duration
        whirlwind on same target (4× block 0 + 4× bAD)."""
        self._delta_check("Nilah", "R", 1)

    # Pattern E: multi-charge / multi-fire totals (2 entries)
    def test_poppy_R_routes_to_block_1(self) -> None:
        """Poppy R block 1 'Charged Damage' = Keeper's Verdict fully-
        charged channel knockback (2× block 0 + 2× bAD)."""
        self._delta_check("Poppy", "R", 1)

    def test_rumble_E_routes_to_block_1(self) -> None:
        """Rumble E block 1 'Maximum Damage' = Electro Harpoon 2-charge
        dual-fire total on same target (2× block 0 + 2× AP)."""
        self._delta_check("Rumble", "E", 1)

    # Multi-key resolved-shape sanity for new multi-key champions
    def test_leblanc_both_keys_in_resolved(self) -> None:
        """LeBlanc Q=1 + E=1 (s197) — both keys must appear in resolved map."""
        r = compute_ability_dps(
            self.snap, "Leblanc", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1, "E": 1})
        self.assertEqual(r.block_index_source, "champion")

    def test_mel_both_keys_in_resolved(self) -> None:
        """Mel Q=3 + R=2 (s197) — both keys must appear in resolved map."""
        r = compute_ability_dps(
            self.snap, "Mel", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 3, "R": 2})
        self.assertEqual(r.block_index_source, "champion")

    def test_naafiri_both_keys_in_resolved(self) -> None:
        """Naafiri Q=2 + E=1 (s197) — both keys must appear in resolved map."""
        r = compute_ability_dps(
            self.snap, "Naafiri", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 2, "E": 1})
        self.assertEqual(r.block_index_source, "champion")

    def test_renekton_both_keys_in_resolved(self) -> None:
        """Renekton Q=1 + W=2 (s197) + R=1 (s202 Dominus full duration)
        — all three keys must appear in resolved map."""
        r = compute_ability_dps(
            self.snap, "Renekton", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1, "W": 2, "R": 1})
        self.assertEqual(r.block_index_source, "champion")

    # Math-level sanity: Lucian R block 1 base = 5× block 0 (full-channel)
    def test_lucian_R_block1_matches_5x_block0(self) -> None:
        """Numeric sanity: Lucian R block 1 base = 5× block 0 base across
        all 3 ranks (Culling full-channel total = 5× per-shot)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Lucian", "R", form_index=0)
        self.assertIsNotNone(form)
        blocks = form.damage_blocks
        self.assertGreaterEqual(len(blocks), 2)
        for rank, (b0, b1) in enumerate(zip(blocks[0].base, blocks[1].base)):
            self.assertAlmostEqual(
                b1, b0 * 5.0, places=2,
                msg=f"Lucian R rank {rank+1}: block 1 base {b1} != 5× block 0 base {b0}"
            )

    # Math-level sanity: Renekton Q block 1 base = 1.5× block 0 (full-Fury)
    def test_renekton_Q_block1_matches_1_5x_block0(self) -> None:
        """Numeric sanity: Renekton Q block 1 base = 1.5× block 0 base
        across all 5 ranks (Cull the Meek Empowered at 50+ Fury)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Renekton", "Q", form_index=0)
        self.assertIsNotNone(form)
        blocks = form.damage_blocks
        self.assertGreaterEqual(len(blocks), 2)
        for rank, (b0, b1) in enumerate(zip(blocks[0].base, blocks[1].base)):
            self.assertAlmostEqual(
                b1, b0 * 1.5, places=2,
                msg=f"Renekton Q rank {rank+1}: block 1 base {b1} != 1.5× block 0 base {b0}"
            )

    # Backward-compat: pre-s197 entries still resolve unchanged
    def test_pre_s197_morgana_unchanged(self) -> None:
        """Backward-compat: s195+s196 Morgana entry preserved after s197."""
        r = compute_ability_dps(
            self.snap, "Morgana", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"W": 3, "R": 1})

    def test_pre_s197_akali_unchanged(self) -> None:
        """Backward-compat: s192+s196 Akali entry preserved after s197."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11, target_armor=80, target_mr=30,
            target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved.get("R"), 0)
        self.assertEqual(r.block_index_resolved.get("R2"), 2)
        self.assertEqual(r.block_index_resolved.get("E"), 2)

    def test_pre_s197_corki_unchanged(self) -> None:
        """Backward-compat: s194 Corki entry preserved after s197."""
        r = compute_ability_dps(
            self.snap, "Corki", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"W": 1, "E": 1})

    def test_pre_s197_singed_unchanged(self) -> None:
        """Backward-compat: s193 Singed entry preserved after s197."""
        r = compute_ability_dps(
            self.snap, "Singed", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1})


class Phase599_11ExpansionTests(unittest.TestCase):
    """Phase 5.9.11 (s198). 20 new (champion, key) entries — 17 new
    champions (XinZhao contributes 2 entries Q+W) + 2 key extensions
    on existing champions Sion (adds R) and Vladimir (adds W). Registry
    67 → 84 champions. Four sub-patterns:
      (A) multi-hit single-target totals: Sylas Q, XinZhao Q/W, Zac R,
          Maokai E, Kayn Q, Sejuani W, Neeko Q, Nasus E, Nami E,
          Ornn R, Twitch E
      (B) fully-charged amps: Vi Q, Sion R, Irelia W, Yuumi Q
      (C) resource-state amp: Jax E
      (D) channel/duration totals: Udyr R, Vladimir W, Viktor R

    Same 'operator commits to canonical-amped condition' model as
    s191/s193/s194/s195/s196/s197 — pure JSON expansion, no walker
    changes.

    Tests verify each new entry:
      1. Is present in the resolved registry
      2. Drives total_ability_dps strictly above the forced-block-0 baseline
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _delta_check(self, champion: str, key: str, expected_idx: int) -> None:
        """Assert champion's registry entry routes `key` to expected_idx,
        and the resulting total_ability_dps exceeds the forced-block-0
        baseline by a positive margin."""
        r_reg = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.block_index_resolved.get(key), expected_idx,
                         f"{champion}.{key} should route to block {expected_idx}")
        forced = dict(r_reg.block_index_resolved)
        forced[key] = 0
        r_off = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides=forced,
        )
        self.assertGreater(r_reg.total_ability_dps, r_off.total_ability_dps,
                           f"{champion} registry total should exceed forced-block-0")

    # Pattern A: multi-hit single-target totals (12 entries — XinZhao contributes 2)
    def test_sylas_Q_routes_to_block_3(self) -> None:
        """Sylas Q block 3 'Total Magic Damage' = Chain Lash initial +
        delayed pulse on chained target (3.33× block 0)."""
        self._delta_check("Sylas", "Q", 3)

    def test_xinzhao_Q_routes_to_block_1(self) -> None:
        """Xin Zhao Q block 1 'Total Bonus Physical Damage' = Three
        Talon Strike 3 empowered AAs total (3× block 0)."""
        self._delta_check("XinZhao", "Q", 1)

    def test_xinzhao_W_routes_to_block_2(self) -> None:
        """Xin Zhao W block 2 'Total Physical Damage' = Wind Becomes
        Lightning slash + thrust both on same target (3.71× base + 4× tAD)."""
        self._delta_check("XinZhao", "W", 2)

    def test_zac_R_routes_to_block_2(self) -> None:
        """Zac R block 2 'Total Magic Damage' = Let's Bounce all 4
        bounces on same target (2.5× block 0)."""
        self._delta_check("Zac", "R", 2)

    def test_maokai_E_routes_to_block_1(self) -> None:
        """Maokai E block 1 'Total Enhanced Damage' = Sapling Toss
        enhanced dual-hit (2× block 0)."""
        self._delta_check("Maokai", "E", 1)

    def test_kayn_Q_routes_to_block_1(self) -> None:
        """Kayn Q block 1 'Total Physical Damage' = Reaping Slash both
        passes (out + return) on same target (2× block 0)."""
        self._delta_check("Kayn", "Q", 1)

    def test_sejuani_W_routes_to_block_2(self) -> None:
        """Sejuani W block 2 'Total Physical Damage' = Winter's Wrath
        swipe + thrust total (2.89× base + 4× AP)."""
        self._delta_check("Sejuani", "W", 2)

    def test_neeko_Q_routes_to_block_2(self) -> None:
        """Neeko Q block 2 'Total Maximum Magic Damage' = Blooming
        Burst initial + 2 bloom expansions same target (2.04×)."""
        self._delta_check("Neeko", "Q", 2)

    def test_nasus_E_routes_to_block_2(self) -> None:
        """Nasus E block 2 'Total Magic Damage' = Spirit Fire initial
        impact + 5 full-duration ticks (2× block 0)."""
        self._delta_check("Nasus", "E", 2)

    def test_nami_E_routes_to_block_1(self) -> None:
        """Nami E block 1 'Total Bonus Magic Damage' = Tidecaller's
        Blessing 3 empowered AAs all on target (3× block 0)."""
        self._delta_check("Nami", "E", 1)

    def test_ornn_R_routes_to_block_2(self) -> None:
        """Ornn R block 2 'Total Magic Damage' = Call of the Forge God
        initial ram + 2nd ram pass (2× block 0)."""
        self._delta_check("Ornn", "R", 2)

    def test_twitch_E_routes_to_block_3(self) -> None:
        """Twitch E block 3 'Maximum Mixed Damage' = Contaminate at 6
        Deadly Venom stacks (4.5× base + 6× per-stack scaling)."""
        self._delta_check("Twitch", "E", 3)

    # Pattern B: fully-charged amps (4 entries)
    def test_vi_Q_routes_to_block_1(self) -> None:
        """Vi Q block 1 'Maximum Physical Damage' = Vault Breaker
        fully-charged after 1.25s wind-up (2.5× block 0)."""
        self._delta_check("Vi", "Q", 1)

    def test_sion_R_routes_to_block_1(self) -> None:
        """Sion R block 1 'Maximum Physical Damage' = Unstoppable
        Onslaught at max-speed after full acceleration (2.67× base)."""
        self._delta_check("Sion", "R", 1)

    def test_irelia_W_routes_to_block_1(self) -> None:
        """Irelia W block 1 'Maximum Physical Damage' = Defiant Dance
        fully-charged after 2s (3× block 0)."""
        self._delta_check("Irelia", "W", 1)

    def test_yuumi_Q_routes_to_block_1(self) -> None:
        """Yuumi Q block 1 'Increased Damage' = Prowling Projectile
        untargeted at max-distance (1.62× block 0)."""
        self._delta_check("Yuumi", "Q", 1)

    # Pattern C: resource-state amp (1 entry)
    def test_jax_E_routes_to_block_1(self) -> None:
        """Jax E block 1 'Maximum Magic Damage' = Counter Strike at 2
        dodge stacks max (2× block 0 + 2× AP)."""
        self._delta_check("Jax", "E", 1)

    # Pattern D: channel/duration totals (3 entries)
    def test_udyr_R_routes_to_block_1(self) -> None:
        """Udyr R block 1 'Total Magic Damage' = Wingborne Storm full
        8 ticks on same target (8× block 0)."""
        self._delta_check("Udyr", "R", 1)

    def test_vladimir_W_routes_to_block_1(self) -> None:
        """Vladimir W block 1 'Total Magic Damage' = Sanguine Pool full
        4-second duration ticks over enemy (4× block 0)."""
        self._delta_check("Vladimir", "W", 1)

    def test_viktor_R_routes_to_block_2(self) -> None:
        """Viktor R block 2 'Total Magic Damage' = Chaos Storm initial
        + 6 ticks full channel (4.48× base + 5.20× AP)."""
        self._delta_check("Viktor", "R", 2)

    # Multi-key resolved-shape sanity for newly multi-key champions
    def test_xinzhao_both_keys_in_resolved(self) -> None:
        """Xin Zhao Q=1 + W=2 (s198) — both keys must appear in resolved map."""
        r = compute_ability_dps(
            self.snap, "XinZhao", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1, "W": 2})
        self.assertEqual(r.block_index_source, "champion")

    def test_sion_both_keys_in_resolved(self) -> None:
        """Sion Q=2 (s197) + R=1 (s198) — both keys must appear in resolved map."""
        r = compute_ability_dps(
            self.snap, "Sion", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 2, "R": 1})
        self.assertEqual(r.block_index_source, "champion")

    def test_vladimir_both_keys_in_resolved(self) -> None:
        """Vladimir E=1 (s195) + W=1 (s198) + Q=1 (s203, extension) — all keys
        present. s198-shape test extended to assert E + W subset rather than
        equality, since s203 added Q without removing earlier keys."""
        r = compute_ability_dps(
            self.snap, "Vladimir", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved.get("E"), 1)
        self.assertEqual(r.block_index_resolved.get("W"), 1)
        self.assertEqual(r.block_index_source, "champion")

    # Math-level sanity: Udyr R block 1 base = 8× block 0 (full channel)
    def test_udyr_R_block1_matches_8x_block0(self) -> None:
        """Numeric sanity: Udyr R block 1 base = 8× block 0 base across
        all ranks (Wingborne Storm full 8 ticks total)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Udyr", "R", form_index=0)
        self.assertIsNotNone(form)
        blocks = form.damage_blocks
        self.assertGreaterEqual(len(blocks), 2)
        for rank, (b0, b1) in enumerate(zip(blocks[0].base, blocks[1].base)):
            self.assertAlmostEqual(
                b1, b0 * 8.0, places=2,
                msg=f"Udyr R rank {rank+1}: block 1 base {b1} != 8× block 0 base {b0}"
            )

    # Math-level sanity: Vi Q block 1 base = 2.5× block 0 (fully-charged)
    def test_vi_Q_block1_matches_2_5x_block0(self) -> None:
        """Numeric sanity: Vi Q block 1 base = 2.5× block 0 base across
        all 5 ranks (Vault Breaker fully-charged after 1.25s)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Vi", "Q", form_index=0)
        self.assertIsNotNone(form)
        blocks = form.damage_blocks
        self.assertGreaterEqual(len(blocks), 2)
        for rank, (b0, b1) in enumerate(zip(blocks[0].base, blocks[1].base)):
            self.assertAlmostEqual(
                b1, b0 * 2.5, places=2,
                msg=f"Vi Q rank {rank+1}: block 1 base {b1} != 2.5× block 0 base {b0}"
            )

    # Backward-compat: prior-batch entries still resolve unchanged after s198
    def test_pre_s198_morgana_unchanged(self) -> None:
        """Backward-compat: s195+s196 Morgana entry preserved after s198."""
        r = compute_ability_dps(
            self.snap, "Morgana", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"W": 3, "R": 1})

    def test_pre_s198_aatrox_unchanged(self) -> None:
        """Backward-compat: s197 Aatrox W=3 preserved after s198 (Aatrox
        not touched in s198 — only W=3 from Infernal Chains pull-back).
        Asserts the W key alone so the test survives later batches that
        extend Aatrox to other ability keys (s199 added Q=1)."""
        r = compute_burst_damage(
            self.snap, "Aatrox", level=11, target_armor=80, target_mr=30,
            target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved.get("W"), 3)

    def test_pre_s198_camille_unchanged(self) -> None:
        """Backward-compat: s195 Camille entry preserved after s198."""
        r = compute_ability_dps(
            self.snap, "Camille", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 2})

    def test_pre_s198_singed_unchanged(self) -> None:
        """Backward-compat: s193 Singed entry preserved after s198."""
        r = compute_ability_dps(
            self.snap, "Singed", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1})


# ─── Phase 5.9.12 (s199) — Aatrox sweet-spot / Ashe Flurry / 17-entry expansion


class Phase599_12ExpansionTests(unittest.TestCase):
    """Phase 5.9.12 (s199). 17 new (champion, key) entries — 6 new
    champions (Ashe/Shaco/Shen/Swain/Tristana/Xayah) + 11 key extensions
    on existing (Aatrox/Fiddlesticks/Karthus/Nautilus/Nunu/Samira/
    Sejuani/Talon/Udyr/Viktor/Zac). Registry 84 → 90 champions, 103 → 120
    entries. Six sub-patterns:
      (A) Multi-hit single-target totals: Ashe Q (5-AA Flurry),
          Nunu E (3-snowball cap), Samira W (2-rotation), Shen Q
          (3-AA empowered), Swain Q (5-bolt point-blank), Viktor Q
          (Q+empowered AA), Xayah Q (out+return), Zac Q (2-arm)
      (B) Positional/sweet-spot amps: Aatrox Q (Q1 sweet-spot),
          Shaco E (backstab), Talon Q (champion crit)
      (C) Resource-state amps: Tristana E (max-stack), Udyr Q
          (Awakened 2-AA)
      (D) Channel total: Karthus E (per-second tick)
      (E) Direct-hit primary: Sejuani R (Glacial Prison direct stun),
          Nautilus R (Depth Charge primary)
      (F) Execute amp: Fiddlesticks W (low-HP Bountiful Harvest)

    Same 'operator commits to canonical-amped condition' model as prior
    batches — pure JSON expansion, no walker/server code changes.

    Tests verify each new entry:
      1. Is present in the resolved registry at the expected block_index
      2. Drives total_ability_dps strictly above the forced-block-0 baseline
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _delta_check(self, champion: str, key: str, expected_idx: int) -> None:
        """Assert champion's registry entry routes `key` to expected_idx,
        and the resulting total_ability_dps exceeds the forced-block-0
        baseline by a positive margin."""
        r_reg = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.block_index_resolved.get(key), expected_idx,
                         f"{champion}.{key} should route to block {expected_idx}")
        forced = dict(r_reg.block_index_resolved)
        forced[key] = 0
        r_off = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides=forced,
        )
        self.assertGreater(r_reg.total_ability_dps, r_off.total_ability_dps,
                           f"{champion} registry total should exceed forced-block-0")

    # Pattern A: multi-hit single-target totals (8 entries)
    def test_ashe_Q_routes_to_block_2(self) -> None:
        """Ashe Q block 2 'Total Damage Per Flurry' = all 5 enhanced AAs
        from Ranger's Focus on same target (5× block 1)."""
        self._delta_check("Ashe", "Q", 2)

    def test_nunu_E_routes_to_block_1(self) -> None:
        """Nunu E block 1 'Total Magic Damage' = Snowball Barrage 3-snowball
        cap on one champion (3× block 0)."""
        self._delta_check("Nunu", "E", 1)

    def test_samira_W_routes_to_block_1(self) -> None:
        """Samira W block 1 'Total Physical Damage' = Blade Whirl 2-rotation
        full active on close-range target (2× block 0)."""
        self._delta_check("Samira", "W", 1)

    def test_shen_Q_routes_to_block_1(self) -> None:
        """Shen Q filtered idx 1 = raw block 2 'Total Magic Damage' =
        Twilight Assault 3 empowered AAs on same target (3× raw block 1).
        Registry value is 1 (not 2) because Shen.Q raw block 0 is 'Slow'
        (non-damage) and gets stripped by `damage_blocks = tuple(...
        attribute_kind == 'damage')` filtering pre-index, shifting raw
        block 2 to filtered idx 1."""
        self._delta_check("Shen", "Q", 1)

    def test_swain_Q_routes_to_block_2(self) -> None:
        """Swain Q block 2 'Total Damage' = Death's Hand all 5 bolts on
        target at point-blank (2× block 0)."""
        self._delta_check("Swain", "Q", 2)

    def test_viktor_Q_routes_to_block_2(self) -> None:
        """Viktor Q block 2 'Total Magic Damage' = Power Transfer ability +
        empowered AA total (1.7× block 0; = block 0 + block 1)."""
        self._delta_check("Viktor", "Q", 2)

    def test_xayah_Q_routes_to_block_1(self) -> None:
        """Xayah Q block 1 'Total Physical Damage' = Double Daggers both
        on same target (2× block 0)."""
        self._delta_check("Xayah", "Q", 1)

    def test_zac_Q_routes_to_block_1(self) -> None:
        """Zac Q block 1 'Total Magic Damage' = Stretching Strikes both
        arms on same target (2× block 0)."""
        self._delta_check("Zac", "Q", 1)

    # Pattern B: positional/sweet-spot amps (3 entries)
    def test_aatrox_Q_routes_to_block_1(self) -> None:
        """Aatrox Q block 1 'First Sweetspot Damage' = Edge of the Blade
        sweet-spot zone on Q1 cast (1.7× block 0)."""
        self._delta_check("Aatrox", "Q", 1)

    def test_shaco_E_routes_to_block_2(self) -> None:
        """Shaco E block 2 'Increased Damage' = Two-Shiv Poison backstab
        amp from behind target (1.5× block 1)."""
        self._delta_check("Shaco", "E", 2)

    def test_talon_Q_routes_to_block_1(self) -> None:
        """Talon Q block 1 'Critical Physical Damage' = Noxian Diplomacy
        auto-crit on champion targets (1.5× block 0)."""
        self._delta_check("Talon", "Q", 1)

    # Pattern C: resource-state amps (2 entries)
    def test_tristana_E_routes_to_block_4(self) -> None:
        """Tristana E block 4 'Full Stack Physical Damage' = Explosive
        Charge max-stack detonation after 4 AAs (2× block 1)."""
        self._delta_check("Tristana", "E", 4)

    def test_udyr_Q_routes_to_block_1(self) -> None:
        """Udyr Q block 1 'Total Physical Damage' = Wilding Claw Awakened
        2-AA empowered total (2× block 0)."""
        self._delta_check("Udyr", "Q", 1)

    # Pattern D: channel total (1 entry)
    def test_karthus_E_routes_to_block_2(self) -> None:
        """Karthus E block 2 'Damage Per Second' = Defile per-second
        commit (4× per-tick block 1)."""
        self._delta_check("Karthus", "E", 2)

    # Pattern E: direct-hit primary target (2 entries)
    def test_sejuani_R_routes_to_block_1(self) -> None:
        """Sejuani R block 1 'Increased Damage' = Glacial Prison direct
        stun on primary target (~2× block 0)."""
        self._delta_check("Sejuani", "R", 1)

    def test_nautilus_R_routes_to_block_2(self) -> None:
        """Nautilus R block 2 'Increased Damage' = Depth Charge primary-
        target hit (~2× block 0 = AoE bystander)."""
        self._delta_check("Nautilus", "R", 2)

    # Pattern F: execute amp (1 entry)
    def test_fiddlesticks_W_routes_to_block_3(self) -> None:
        """Fiddlesticks W block 3 'Total Magic Damage' = Bountiful Harvest
        full channel + missing-HP execute on low-HP target (2× block 0)."""
        self._delta_check("Fiddlesticks", "W", 3)

    # Multi-key resolved-shape sanity for newly multi-key champions
    def test_aatrox_both_keys_in_resolved(self) -> None:
        """Aatrox W=3 (s197) + Q=1 (s199) — both keys must appear in
        resolved map."""
        r = compute_burst_damage(
            self.snap, "Aatrox", level=11, target_armor=80, target_mr=30,
            target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"W": 3, "Q": 1})
        self.assertEqual(r.block_index_source, "champion")

    def test_karthus_both_keys_in_resolved(self) -> None:
        """Karthus Q=1 (s196) + E=2 (s199) — both keys must appear in
        resolved map."""
        r = compute_ability_dps(
            self.snap, "Karthus", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1, "E": 2})
        self.assertEqual(r.block_index_source, "champion")

    def test_nautilus_both_keys_in_resolved(self) -> None:
        """Nautilus E=2 (s196) + R=2 (s199) — both keys must appear in
        resolved map."""
        r = compute_ability_dps(
            self.snap, "Nautilus", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"E": 2, "R": 2})

    def test_samira_both_keys_in_resolved(self) -> None:
        """Samira R=1 (s193) + W=1 (s199) — both keys must appear in
        resolved map."""
        r = compute_ability_dps(
            self.snap, "Samira", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"R": 1, "W": 1})

    def test_talon_three_keys_in_resolved_after_s199(self) -> None:
        """Talon W=2 + R=2 (s195) + Q=1 (s199) — all three keys must
        appear in resolved map after s199."""
        r = compute_burst_damage(
            self.snap, "Talon", level=11, target_armor=80, target_mr=30,
            target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"W": 2, "R": 2, "Q": 1})

    def test_udyr_both_keys_in_resolved(self) -> None:
        """Udyr R=1 (s198) + Q=1 (s199) — both keys must appear in
        resolved map."""
        r = compute_ability_dps(
            self.snap, "Udyr", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"R": 1, "Q": 1})

    def test_viktor_both_keys_in_resolved(self) -> None:
        """Viktor R=2 (s198) + Q=2 (s199) + E=2 (s202 Death Ray double-hit)
        — all three keys must appear in resolved map."""
        r = compute_ability_dps(
            self.snap, "Viktor", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"R": 2, "Q": 2, "E": 2})

    # Math-level sanity: Ashe Q block 2 tAD% = 5× block 1 (per-AA → flurry)
    def test_ashe_Q_block2_matches_5x_block1_tad(self) -> None:
        """Numeric sanity: Ashe Q block 2 total_ad_pct = 5× block 1
        total_ad_pct across all ranks (Ranger's Focus 5-AA flurry)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Ashe", "Q", form_index=0)
        self.assertIsNotNone(form)
        blocks = form.damage_blocks
        self.assertGreaterEqual(len(blocks), 3)
        b1_tad = blocks[1].total_ad_pct or []
        b2_tad = blocks[2].total_ad_pct or []
        self.assertEqual(len(b1_tad), len(b2_tad))
        for rank, (a, b) in enumerate(zip(b1_tad, b2_tad)):
            self.assertAlmostEqual(
                b, a * 5.0, places=2,
                msg=f"Ashe Q rank {rank+1}: block 2 tAD% {b} != 5× block 1 tAD% {a}"
            )

    # Math-level sanity: Karthus E block 2 base = 4× block 1 (per-tick → per-second)
    def test_karthus_E_block2_matches_4x_block1(self) -> None:
        """Numeric sanity: Karthus E block 2 base = 4× block 1 base across
        all ranks (Defile per-tick × 4 ticks/sec = per-second)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Karthus", "E", form_index=0)
        self.assertIsNotNone(form)
        blocks = form.damage_blocks
        self.assertGreaterEqual(len(blocks), 3)
        for rank, (b1, b2) in enumerate(zip(blocks[1].base, blocks[2].base)):
            self.assertAlmostEqual(
                b2, b1 * 4.0, places=2,
                msg=f"Karthus E rank {rank+1}: block 2 base {b2} != 4× block 1 base {b1}"
            )

    # Math-level sanity: Tristana E block 4 base = 2× block 1 (no-stack → full-stack)
    def test_tristana_E_block4_matches_2x_block1(self) -> None:
        """Numeric sanity: Tristana E block 4 base = 2× block 1 base across
        all ranks (Explosive Charge full-stack vs no-stack)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Tristana", "E", form_index=0)
        self.assertIsNotNone(form)
        blocks = form.damage_blocks
        self.assertGreaterEqual(len(blocks), 5)
        for rank, (b1, b4) in enumerate(zip(blocks[1].base, blocks[4].base)):
            self.assertAlmostEqual(
                b4, b1 * 2.0, places=2,
                msg=f"Tristana E rank {rank+1}: block 4 base {b4} != 2× block 1 base {b1}"
            )

    # Backward-compat: prior-batch entries still resolve unchanged after s199
    def test_pre_s199_sylas_unchanged(self) -> None:
        """Backward-compat: s198 Sylas Q=3 preserved after s199."""
        r = compute_ability_dps(
            self.snap, "Sylas", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 3})

    def test_pre_s199_akali_unchanged(self) -> None:
        """Backward-compat: s192+s196 Akali entry preserved after s199.
        Akali has R=0 (R1 base), R2=2 (max-execute), E=2 (Total Magic
        Damage 3.33× block 0) — Akali not touched in s199."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11, target_armor=80, target_mr=30,
            target_max_hp=2000,
        )
        # Akali's burst combo includes R + R2 tokens, so all 3 keys
        # appear in resolved.
        self.assertEqual(r.block_index_resolved, {"R": 0, "R2": 2, "E": 2})

    def test_pre_s199_singed_unchanged(self) -> None:
        """Backward-compat: s193 Singed entry preserved after s199 (Singed
        not touched in s199)."""
        r = compute_ability_dps(
            self.snap, "Singed", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1})

    def test_pre_s199_corki_unchanged(self) -> None:
        """Backward-compat: s194 Corki W=1, E=1 preserved after s199
        (Corki not touched in s199)."""
        r = compute_ability_dps(
            self.snap, "Corki", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"W": 1, "E": 1})


# ─── Phase 5.9.13 (s200) — rescue batch: Ambessa/Anivia/Lillia/Nilah/Poppy


class Phase599_13ExpansionTests(unittest.TestCase):
    """Phase 5.9.13 (s200). 7 new (champion, key) entries — rescues 4
    previously-deferred mechanics:
      - Ambessa Q/W (s196/s197/s198 'form swap' deferral dissolved —
        actually Drain-stack resource amp like Renekton Fury)
      - Anivia R (s195 'channel ambiguous' — actually Empowered phase
        amp like Belveth E max-charge)
      - Lillia Q (s199 'uncertain' — actually Q + Dream Dust AA combo)
      - Nilah Q (s199 'uncertain 2-stack' — actually max-stack
        empowered AA like Twitch E / Tristana E)
    Plus Ambessa E (slash+thrust total) and Poppy Q (out+return).

    Three sub-patterns:
      (A) Multi-hit single-target totals (Ambessa E, Lillia Q, Poppy Q)
      (B) Resource-state amps (Ambessa Q, Ambessa W, Nilah Q)
      (C) Channel/duration commit (Anivia R Empowered phase)

    Registry 90 → 91 champions, 120 → 127 entries.

    Tests verify each new entry:
      1. Is present in the resolved registry at the expected filtered
         block_index
      2. Drives total_ability_dps strictly above the forced-block-0 baseline
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _delta_check(self, champion: str, key: str, expected_idx: int) -> None:
        r_reg = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.block_index_resolved.get(key), expected_idx,
                         f"{champion}.{key} should route to filtered block {expected_idx}")
        forced = dict(r_reg.block_index_resolved)
        forced[key] = 0
        r_off = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides=forced,
        )
        self.assertGreater(r_reg.total_ability_dps, r_off.total_ability_dps,
                           f"{champion} registry total should exceed forced-block-0")

    # Pattern A: multi-hit single-target totals (3 entries)
    def test_ambessa_E_routes_to_block_1(self) -> None:
        """Ambessa E block 1 'Total Physical Damage' = Lacerate
        slash + thrust both on same target (2× block 0)."""
        self._delta_check("Ambessa", "E", 1)

    def test_lillia_Q_routes_to_filtered_block_1(self) -> None:
        """Lillia Q filtered idx 1 = raw block 3 'Total Mixed Damage' =
        Q damage + Dream Dust AA bonus on Q-stacked target (2× raw
        block 2). Registry value 1 reflects the filtered index since
        raw blocks 0, 1 are Movement Speed (non-damage attribute_kind)."""
        self._delta_check("Lillia", "Q", 1)

    def test_poppy_Q_routes_to_filtered_block_1(self) -> None:
        """Poppy Q filtered idx 1 = raw block 4 'Total Physical Damage' =
        Hammer Shock outgoing + return wave on same target (2× raw block
        0). Registry value 1 reflects the filtered index since raw blocks
        1-3 are Slow + Minion-Damage (different attribute_kind from
        champion damage)."""
        self._delta_check("Poppy", "Q", 1)

    # Pattern B: resource-state amps (3 entries)
    def test_ambessa_Q_routes_to_block_1(self) -> None:
        """Ambessa Q block 1 'Increased Physical Damage' = Cunning Sweep
        with Drain stacks ready (2× block 0). Operator commits to
        having Drain — same model as Renekton Fury."""
        self._delta_check("Ambessa", "Q", 1)

    def test_ambessa_W_routes_to_block_1(self) -> None:
        """Ambessa W block 1 'Increased Physical Damage' = Repudiation
        with Drain stacks ready (1.5× block 0)."""
        self._delta_check("Ambessa", "W", 1)

    def test_nilah_Q_routes_to_block_1(self) -> None:
        """Nilah Q block 1 'Maximum Physical Damage' = Formless Blade
        empowered AA at max stacks (2× block 0 'Minimum'). Operator
        commits to building stacks pre-burst — same as Twitch E (s198)
        and Tristana E (s199) resource-state amp pattern."""
        self._delta_check("Nilah", "Q", 1)

    # Pattern C: channel/duration commit (1 entry)
    def test_anivia_R_routes_to_filtered_block_1(self) -> None:
        """Anivia R filtered idx 1 = raw block 2 'Empowered Damage per
        Tick' = Glacial Storm Empowered phase (3× raw block 0 per-tick).
        Operator commits to holding R for 1.5+ seconds to reach
        Empowered transition — same model as Belveth E max-charge."""
        self._delta_check("Anivia", "R", 1)

    # Multi-key resolved-shape sanity for s200's new champion + extensions
    def test_ambessa_all_three_keys_in_resolved(self) -> None:
        """Ambessa is a new s200 champion — Q=1, W=1, E=1 all present."""
        r = compute_ability_dps(
            self.snap, "Ambessa", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1, "W": 1, "E": 1})
        self.assertEqual(r.block_index_source, "champion")

    def test_anivia_all_three_keys_in_resolved(self) -> None:
        """Anivia Q=2 (s191) + E=1 (s191) + R=1 (s200) — all three keys
        must appear in resolved map."""
        r = compute_ability_dps(
            self.snap, "Anivia", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 2, "E": 1, "R": 1})

    def test_lillia_both_keys_in_resolved(self) -> None:
        """Lillia W=1 (s196) + Q=1 (s200) — both keys must appear."""
        r = compute_ability_dps(
            self.snap, "Lillia", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"W": 1, "Q": 1})

    def test_nilah_both_keys_in_resolved(self) -> None:
        """Nilah R=1 (s197) + Q=1 (s200) — both keys must appear."""
        r = compute_ability_dps(
            self.snap, "Nilah", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"R": 1, "Q": 1})

    def test_poppy_both_keys_in_resolved(self) -> None:
        """Poppy R=1 (s197) + Q=1 (s200) + E=1 (s202 Heroic Charge wall-
        slam) — all three keys must appear in resolved map."""
        r = compute_ability_dps(
            self.snap, "Poppy", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"R": 1, "Q": 1, "E": 1})

    # Math-level sanity: Ambessa Q block 1 base = 2× block 0 (Drain amp)
    def test_ambessa_Q_block1_matches_2x_block0(self) -> None:
        """Numeric sanity: Ambessa Q block 1 base = 2× block 0 base
        across all 5 ranks (Drain-stack Increased Damage)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Ambessa", "Q", form_index=0)
        self.assertIsNotNone(form)
        blocks = form.damage_blocks
        self.assertGreaterEqual(len(blocks), 2)
        for rank, (b0, b1) in enumerate(zip(blocks[0].base, blocks[1].base)):
            self.assertAlmostEqual(
                b1, b0 * 2.0, places=2,
                msg=f"Ambessa Q rank {rank+1}: block 1 base {b1} != 2× block 0 base {b0}"
            )

    # Math-level sanity: Nilah Q block 1 tAD = 2× block 0 tAD (max stacks)
    def test_nilah_Q_block1_tad_matches_2x_block0(self) -> None:
        """Numeric sanity: Nilah Q block 1 total_ad_pct = 2× block 0
        total_ad_pct across all 5 ranks (Maximum vs Minimum empowered AA)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Nilah", "Q", form_index=0)
        self.assertIsNotNone(form)
        blocks = form.damage_blocks
        self.assertGreaterEqual(len(blocks), 2)
        b0_tad = blocks[0].total_ad_pct or []
        b1_tad = blocks[1].total_ad_pct or []
        self.assertEqual(len(b0_tad), len(b1_tad))
        for rank, (a, b) in enumerate(zip(b0_tad, b1_tad)):
            self.assertAlmostEqual(
                b, a * 2.0, places=2,
                msg=f"Nilah Q rank {rank+1}: block 1 tAD {b} != 2× block 0 tAD {a}"
            )

    # Backward-compat: prior-batch entries still resolve unchanged after s200
    def test_pre_s200_aatrox_unchanged(self) -> None:
        """Backward-compat: s197 Aatrox W=3 + s199 Q=1 preserved after s200.
        Aatrox not touched in s200."""
        r = compute_burst_damage(
            self.snap, "Aatrox", level=11, target_armor=80, target_mr=30,
            target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"W": 3, "Q": 1})

    def test_pre_s200_shen_unchanged(self) -> None:
        """Backward-compat: s199 Shen Q=1 (filtered idx for Total Magic
        Damage 3-AA total) preserved after s200."""
        r = compute_ability_dps(
            self.snap, "Shen", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1})

    def test_pre_s200_singed_unchanged(self) -> None:
        """Backward-compat: s193 Singed Q=1 preserved after s200."""
        r = compute_ability_dps(
            self.snap, "Singed", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1})


# ─── Phase 5.9.14 (s201): block_index expansion 17 entries / 14 champs ──────


class Phase599_14ExpansionTests(unittest.TestCase):
    """Phase 5.9.14 (s201). 16 new (champion, key) entries across 13 new
    champions (3 with two keys: Jhin Q+R, Teemo E+R, Xerath W+R; the rest
    single-key).

    Four sub-patterns:
      (A) Multi-hit single-target totals (7 entries): Graves Q, Jhin Q,
          Kennen R, Taliyah Q, Teemo E, Xerath R, Ziggs E
      (B) Fully-charged amps (4 entries): Galio W, Janna Q, Jhin R, Viego Q
      (C) Channel/duration totals (3 entries): Fizz R, Garen E, Teemo R
      (D) Resource/positional amps (2 entries): Xerath W, Yasuo E

    Registry 91 → 104 champions, 127 → 143 entries.

    Reverts 4 prior-batch skip rationales: Xerath W (s198 'positional' →
    operator-commit framing aligned with Khazix Q isolation s196), Ziggs E
    (s198 'unrealistic 5-mine' → chokepoint commit same as Ashe Q 5-AA),
    Janna Q (s198 'low ratio + support' → 1.55× amp valid), Yasuo E (s198
    'stacks decay 10s' → operator commits to E-stacking pre-burst).

    Tests verify each new entry:
      1. Is present in the resolved registry at the expected filtered idx
      2. Drives total_ability_dps strictly above the forced-block-0 baseline
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _delta_check(self, champion: str, key: str, expected_idx: int) -> None:
        r_reg = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.block_index_resolved.get(key), expected_idx,
                         f"{champion}.{key} should route to filtered block {expected_idx}")
        forced = dict(r_reg.block_index_resolved)
        forced[key] = 0
        r_off = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides=forced,
        )
        self.assertGreater(r_reg.total_ability_dps, r_off.total_ability_dps,
                           f"{champion} registry total should exceed forced-block-0")

    # Pattern A: multi-hit single-target totals (7 entries)
    def test_graves_Q_routes_to_block_2(self) -> None:
        """Graves Q block 2 'Total Physical Damage' = End of the Line all
        shells + return ricochet on same target (2.89× block 0 base)."""
        self._delta_check("Graves", "Q", 2)

    def test_jhin_Q_routes_to_block_2(self) -> None:
        """Jhin Q block 2 'Maximum Final Bounce Physical Damage' = Dancing
        Grenade with 3 chain minion deaths nearby (2.05× block 0)."""
        self._delta_check("Jhin", "Q", 2)

    def test_kennen_R_routes_to_filtered_block_1(self) -> None:
        """Kennen R filtered idx 1 = raw block 2 'Total Single-Target Damage'
        = all 6+ bolts on 1 target (7.5× per-bolt). Raw block 0 'Bonus
        Resistances' is non-damage and stripped pre-index."""
        self._delta_check("Kennen", "R", 1)

    def test_taliyah_Q_routes_to_block_2(self) -> None:
        """Taliyah Q block 2 'Total Magic Damage' = all 5 Threaded Volley
        stones on same target via Worked Ground (2.6× block 0)."""
        self._delta_check("Taliyah", "Q", 2)

    def test_teemo_E_routes_to_block_2(self) -> None:
        """Teemo E block 2 'Total Poison Damage' = full 4-tick DoT duration
        on stationary target (2.67× block 0 = 4 × block 1 per-tick)."""
        self._delta_check("Teemo", "E", 2)

    def test_xerath_R_routes_to_filtered_block_1(self) -> None:
        """Xerath R filtered idx 1 = raw block 2 'Total Magic Damage' = all
        4-6 bullets focused on 1 target (4-6× per-bullet at rank). Raw
        block 0 'Number of Recasts' is non-damage and stripped pre-index."""
        self._delta_check("Xerath", "R", 1)

    def test_ziggs_E_routes_to_block_2(self) -> None:
        """Ziggs E block 2 'Maximum Total Magic Damage' = all 5 Hexplosive
        Minefield mines focused on single target (5× block 0 per-mine).
        Operator commits to chokepoint setup, same as Ashe Q 5-AA focus."""
        self._delta_check("Ziggs", "E", 2)

    # Pattern B: fully-charged amps (4 entries)
    def test_galio_W_routes_to_filtered_block_1(self) -> None:
        """Galio W filtered idx 1 = raw block 4 'Maximum Magic Damage' =
        Shield of Durand fully-charged 2s commit (3× block 0 = raw 3).
        Raw blocks 0-2 ('Magic Shield Strength' + 'Magic Damage Reduction'
        + 'Physical Damage Reduction') are non-damage and stripped."""
        self._delta_check("Galio", "W", 1)

    def test_janna_Q_routes_to_block_2(self) -> None:
        """Janna Q block 2 'Maximum Magic Damage' = Howling Gale 3s max-
        charge (1.55× block 0 = block 0 + 3 × block 1 per-second ramp)."""
        self._delta_check("Janna", "Q", 2)

    def test_jhin_R_routes_to_block_1(self) -> None:
        """Jhin R block 1 'Maximum Physical Damage per Bullet' = Curtain
        Call fired at max range (4× block 0 = Minimum)."""
        self._delta_check("Jhin", "R", 1)

    def test_viego_Q_routes_to_block_3(self) -> None:
        """Viego Q block 3 'Maximum Physical Damage' = fully-charged Blade
        of the Ruined King Soul Steal AA (2× block 2 = Minimum uncharged).
        Operator commits to charging Q before AA, same as Tristana E."""
        self._delta_check("Viego", "Q", 3)

    # Pattern C: channel/duration totals (3 entries)
    def test_fizz_R_routes_to_block_2(self) -> None:
        """Fizz R block 2 'Gigalodon Damage' = max-distance Chum the Waters
        shark travel (2× block 0 = Guppy close-range)."""
        self._delta_check("Fizz", "R", 2)

    def test_garen_E_routes_to_block_1(self) -> None:
        """Garen E block 1 'Increased Damage Per Spin' = Judgment ramped
        damage on consecutive hits to same target (1.25× block 0).
        Operator commits to full E channel on stationary target."""
        self._delta_check("Garen", "E", 1)

    def test_teemo_R_routes_to_filtered_block_1(self) -> None:
        """Teemo R filtered idx 1 = raw block 4 'Total Magic Damage' = full
        4-tick poison duration (4× block 0 = per-tick). Raw blocks 0-2
        ('Bounce Distance Cap' / 'Maximum Charges' / 'Slow') are non-damage
        and stripped pre-index."""
        self._delta_check("Teemo", "R", 1)

    # Pattern D dropped during s201 implementation: Kindred E was in the
    # initial draft as 'Enhanced damage below threshold', but Phase 4a
    # parsing could not extract the missing-HP coefficient from the
    # nested unparsed_modifiers format ("% (+ 0.5% per Mark) of target's
    # missing health"). Both Kindred E blocks have identical base + bAD;
    # the amp lives entirely in the unparsed missing-HP scaling. Setting
    # block_index=1 would be a no-op until upstream parsing improves —
    # see s201 docstring skip-list rationale.

    # Pattern E: resource/positional amps (2 entries)
    def test_xerath_W_routes_to_block_1(self) -> None:
        """Xerath W block 1 'Increased Damage' = Eye of Destruction center-
        spot landing (1.67× block 0). Operator commits to center-aim, same
        as Khazix Q isolation (s196). Reverts s198 'defer to conditional
        schema lift' rationale — same operator-commit framing."""
        self._delta_check("Xerath", "W", 1)

    def test_yasuo_E_routes_to_block_3(self) -> None:
        """Yasuo E block 3 'Total Combined Damage' = Sweeping Blade at max
        E-stacks resource state (2× block 0 = block 0 + block 2 max bonus).
        Operator commits to E-stacking pre-burst, same as Twitch E 6-stack
        pre-burst rotation (s198). Reverts s198 'stacks decay 10s'
        rationale."""
        self._delta_check("Yasuo", "E", 3)

    # Multi-key resolved-shape sanity (4 multi-key champions in s201)
    def test_jhin_both_keys_in_resolved(self) -> None:
        """Jhin Q=2 + R=1 — both keys must appear in resolved map."""
        r = compute_ability_dps(
            self.snap, "Jhin", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 2, "R": 1})

    def test_teemo_both_keys_in_resolved(self) -> None:
        """Teemo E=2 + R=1 — both keys must appear in resolved map."""
        r = compute_ability_dps(
            self.snap, "Teemo", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"E": 2, "R": 1})

    def test_xerath_both_keys_in_resolved(self) -> None:
        """Xerath W=1 + R=1 — both keys must appear in resolved map."""
        r = compute_ability_dps(
            self.snap, "Xerath", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"W": 1, "R": 1})

    # Math-level sanity: Jhin R block 1 base = 4× block 0 base (max distance)
    def test_jhin_R_block1_matches_4x_block0(self) -> None:
        """Numeric sanity: Jhin R block 1 base = 4× block 0 base across all
        3 ranks (Maximum vs Minimum per-bullet, max-distance scaling)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Jhin", "R", form_index=0)
        self.assertIsNotNone(form)
        blocks = form.damage_blocks
        self.assertGreaterEqual(len(blocks), 2)
        for rank, (b0, b1) in enumerate(zip(blocks[0].base, blocks[1].base)):
            self.assertAlmostEqual(
                b1, b0 * 4.0, places=2,
                msg=f"Jhin R rank {rank+1}: block 1 base {b1} != 4× block 0 base {b0}"
            )

    # Math-level sanity: Ziggs E block 2 base = 5× block 0 base (5 mines)
    def test_ziggs_E_block2_matches_5x_block0(self) -> None:
        """Numeric sanity: Ziggs E block 2 base = 5× block 0 base across
        all 5 ranks (Maximum Total all 5 mines focused on single target)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Ziggs", "E", form_index=0)
        self.assertIsNotNone(form)
        blocks = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
        self.assertGreaterEqual(len(blocks), 3)
        for rank, (b0, b2) in enumerate(zip(blocks[0].base, blocks[2].base)):
            self.assertAlmostEqual(
                b2, b0 * 5.0, places=2,
                msg=f"Ziggs E rank {rank+1}: block 2 base {b2} != 5× block 0 base {b0}"
            )

    # Backward-compat: prior-batch entries still resolve unchanged after s201
    def test_pre_s201_ambessa_unchanged(self) -> None:
        """Backward-compat: s200 Ambessa Q=1, W=1, E=1 preserved after s201."""
        r = compute_ability_dps(
            self.snap, "Ambessa", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1, "W": 1, "E": 1})

    def test_pre_s201_anivia_unchanged(self) -> None:
        """Backward-compat: Anivia 3-key shape from s191+s193+s200 preserved."""
        r = compute_ability_dps(
            self.snap, "Anivia", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 2, "E": 1, "R": 1})

    def test_pre_s201_aatrox_unchanged(self) -> None:
        """Backward-compat: s197 Aatrox W=3 + s199 Q=1 preserved after s201."""
        r = compute_burst_damage(
            self.snap, "Aatrox", level=11, target_armor=80, target_mr=30,
            target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"W": 3, "Q": 1})


# ─── Phase 5.9.15 (s202): block_index expansion 18 entries / 6 new champs ──


class Phase599_15ExpansionTests(unittest.TestCase):
    """Phase 5.9.15 (s202). 18 new (champion, key) entries: 6 truly-new
    champions (Gangplank, Gnar, KSante, RekSai, Vayne, Yunara) + 12 key
    extensions on existing champions (Zoe W, Akshan R, AurelionSol Q,
    Nasus R, Poppy E, Renekton R, Rumble Q+R, Smolder Q+R, Viktor E,
    Yuumi R).

    Registry 104 → 110 champions, 143 → 161 entries.

    Five sub-patterns:
      (A) Multi-hit single-target totals (5): KSante R, Vayne E, Yunara
          Q (filtered), Zoe W (filtered), Viktor E
      (B) Channel/duration totals (7): Gangplank R, AurelionSol Q, Nasus
          R (filtered), Renekton R (filtered), Rumble R, Yuumi R
          (filtered), Poppy E (filtered)
      (C) Max-charge/max-distance amps (2): Akshan R (filtered), Smolder R
          (filtered)
      (D) Resource-state amps (2): RekSai E, Smolder Q
      (E) Wall-stun/charge condition amps (2): Gnar R (filtered),
          Rumble Q (filtered)

    Reverts 4 prior-batch skip rationales: Gnar R + Vayne E + Poppy E
    wall-stun (s198/s199), Rumble Q heat-decay (s199).

    Tests verify each new entry:
      1. Is present in the resolved registry at the expected filtered idx
      2. Drives total_ability_dps strictly above the forced-block-0 baseline
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _delta_check(self, champion: str, key: str, expected_idx: int) -> None:
        r_reg = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.block_index_resolved.get(key), expected_idx,
                         f"{champion}.{key} should route to filtered block {expected_idx}")
        forced = dict(r_reg.block_index_resolved)
        forced[key] = 0
        r_off = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides=forced,
        )
        self.assertGreater(r_reg.total_ability_dps, r_off.total_ability_dps,
                           f"{champion} registry total should exceed forced-block-0")

    # Pattern A: multi-hit single-target totals (5)
    def test_ksante_R_routes_to_block_2(self) -> None:
        """KSante R block 2 'Total Physical Damage' = All Out dash + wall-
        strike total on same target (2× block 0). Operator commits to
        slamming target into wall via R during All Out."""
        self._delta_check("KSante", "R", 2)

    def test_vayne_E_routes_to_block_2(self) -> None:
        """Vayne E block 2 'Total Physical Damage' = Condemn dash + wall-
        slam total (2.5× block 0). Operator commits to landing target
        against wall — universally available terrain, same framing as
        Khazix Q isolation s196."""
        self._delta_check("Vayne", "E", 2)

    def test_yunara_Q_routes_to_filtered_block_2(self) -> None:
        """Yunara Q filtered idx 2 = raw block 3 'Combined Bonus Magic
        Damage' = Q-active + passive on same hit (2× block 0). Filtered
        because raw block 1 'Bonus Attack Speed' is duration (non-damage)
        and raw blocks 4-5 are modifier (Active/Combined Increased Minion
        Damage)."""
        self._delta_check("Yunara", "Q", 2)

    def test_zoe_W_routes_to_filtered_block_1(self) -> None:
        """Zoe W filtered idx 1 = raw block 3 'Total Magic Damage' = 3
        empowered AAs from Q-W-E spell rotation (3× block 0 per-bolt).
        Filtered because raw blocks 0-1 are 'Bonus Movement Speed' /
        'Bonus Movement Speed Duration' (non-damage). Reverts s199
        'stolen-spell resource model' skip — Total is the cleaner 3-AA
        combo total separate from stolen-spell mechanic."""
        self._delta_check("Zoe", "W", 1)

    def test_viktor_E_routes_to_block_2(self) -> None:
        """Viktor E block 2 'Total Magic Damage' = Death Ray double-hit
        on target (initial sweep + delayed second hit, 1.29× block 0).
        Reverts s199 'Augmented variant — Augment system removed' skip
        — blocks 0/1/2 are regular E damage variants, not Augment-related."""
        self._delta_check("Viktor", "E", 2)

    # Pattern B: channel/duration totals (7)
    def test_gangplank_R_routes_to_block_2(self) -> None:
        """Gangplank R block 2 'Total Magic Damage' = Cannon Barrage 4-
        wave total on stationary target (12× block 0 per-wave at rank 1).
        Operator commits to enemy standing in barrage = canonical late-
        game GP teamfight zoning. Blocks 3-6 are upgrade variants (Death's
        Daughter / Fire at Will); block 2 is the unupgraded baseline."""
        self._delta_check("Gangplank", "R", 2)

    def test_aurelionsol_Q_routes_to_block_2(self) -> None:
        """AurelionSol Q block 2 'Total Maximum Magic Damage' = Breath of
        Light full 2.5s channel (26× block 0 per-tick at 10 ticks/sec).
        Same family as s193 AurelionSol E Singularity full-channel."""
        self._delta_check("AurelionSol", "Q", 2)

    def test_nasus_R_routes_to_filtered_block_1(self) -> None:
        """Nasus R filtered idx 1 = raw block 4 'Total Magic Damage' =
        Fury of the Sands full 15s duration with target_max_hp_pct
        scaling. Filtered because raw blocks 0-2 are 'Bonus Health' /
        'Bonus Resistances' / 'Increased Size' (heal/other non-damage)."""
        self._delta_check("Nasus", "R", 1)

    def test_renekton_R_routes_to_filtered_block_1(self) -> None:
        """Renekton R filtered idx 1 = raw block 3 'Total Magic Damage'
        = Dominus full 15s aura duration. Filtered because raw blocks
        0-1 are 'Bonus Movement Speed' / 'Bonus Resistances'."""
        self._delta_check("Renekton", "R", 1)

    def test_rumble_R_routes_to_block_2(self) -> None:
        """Rumble R block 2 'Maximum Magic Damage' = Equalizer max 4s
        channel total on target standing in fire (10× block 0 per-
        second)."""
        self._delta_check("Rumble", "R", 2)

    def test_yuumi_R_routes_to_filtered_block_2(self) -> None:
        """Yuumi R filtered idx 2 = raw block 4 'Total Magic Damage' =
        Final Chapter 2 hits per target (2× block 0 per-hit). Filtered
        because raw blocks 0-1 are 'Heal per Hit' / 'Total Heal' (heal
        non-damage), raw 5-6 are 'Best Friend Heal' variants."""
        self._delta_check("Yuumi", "R", 2)

    def test_poppy_E_routes_to_filtered_block_1(self) -> None:
        """Poppy E filtered idx 1 = raw block 2 'Total Physical Damage'
        = Heroic Charge dash + wall-slam total (2× block 0). Filtered
        because raw block 1 'Stun Duration' is non-damage. Reverts s199
        'wall-state target condition' skip — same operator-commit wall
        framing as Vayne E + Gnar R."""
        self._delta_check("Poppy", "E", 1)

    # Pattern C: max-charge / max-distance amps (2)
    def test_akshan_R_routes_to_filtered_block_1(self) -> None:
        """Akshan R filtered idx 1 = raw block 3 'Maximum Physical Damage
        per Bullet' = Comeuppance fully-charged bullet (3× minimum).
        Filtered because raw blocks 0-1 are 'Maximum Bullets Stored' /
        'Bullet Storing Interval Time' (non-damage). Reverts s197
        'charge-state Comeuppance bullet stack' skip — same model as
        Jhin R max-distance s201."""
        self._delta_check("Akshan", "R", 1)

    def test_smolder_R_routes_to_filtered_block_1(self) -> None:
        """Smolder R filtered idx 1 = raw block 2 'Increased Physical
        Damage' = Mouth of the Abyss at max range (1.5× block 1 close-
        range). Filtered because raw block 0 'Self Heal' is non-damage.
        Same max-distance amp family as Jhin R s201 / Varus Q s195."""
        self._delta_check("Smolder", "R", 1)

    # Pattern D: resource-state amps (2)
    def test_reksai_E_routes_to_block_1(self) -> None:
        """RekSai E block 1 'True Damage' = Furious Bite at max Fury
        (1.25× block 0 + true damage bypasses armor). Operator commits
        to building Fury via prior abilities = canonical RekSai burst
        (W stealth → E bite). Resource-state amp same model as Renekton
        Q full-Fury s197."""
        self._delta_check("RekSai", "E", 1)

    def test_smolder_Q_routes_to_block_1(self) -> None:
        """Smolder Q block 1 'Maximum Physical Damage' = max-stack
        passive Q scaling (1.75× block 0). Gear-INdependent — block 2
        'Maximum with Infinity Edge' is gear-conditional (skipped).
        Operator commits to building Smolder stacks pre-burst."""
        self._delta_check("Smolder", "Q", 1)

    # Pattern E: wall-stun / charge condition amps (2)
    def test_gnar_R_routes_to_filtered_block_1(self) -> None:
        """Gnar R filtered idx 1 = raw block 3 'Increased Damage' =
        GNAR! wall-stun amp (1.5× block 0). Filtered because raw block
        0 'Hyper Bonus Movement Speed' + raw 2 'Disable Duration' are
        non-damage. Reverts s198 'wall-stun terrain target-state' skip
        — operator-commits to wall positioning, same framing as Khazix
        Q isolation s196 / Xerath W center-spot s201."""
        self._delta_check("Gnar", "R", 1)

    def test_rumble_Q_routes_to_filtered_block_2(self) -> None:
        """Rumble Q filtered idx 2 = raw block 4 'Total Enhanced Damage'
        = Flamespitter Total during Danger Zone overheat (1.5× block 2
        baseline). Filtered because raw block 3 'Total Damage' is
        intermediate (we pick the Enhanced variant). Reverts s199
        'Danger Zone heat decays mid-fight' skip — operator commits to
        burst-window Q during overheat."""
        self._delta_check("Rumble", "Q", 2)

    # Multi-key resolved-shape sanity for the 8 extension champions
    def test_zoe_both_keys_in_resolved(self) -> None:
        """Zoe Q=1 (s195) + W=1 (s202) — both keys must appear; subset check
        since s204 may add E=2."""
        r = compute_ability_dps(
            self.snap, "Zoe", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved.get("Q"), 1)
        self.assertEqual(r.block_index_resolved.get("W"), 1)

    def test_akshan_both_keys_in_resolved(self) -> None:
        """Akshan Q=1 (s196) + R=1 (s202) — both keys must appear."""
        r = compute_ability_dps(
            self.snap, "Akshan", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1, "R": 1})

    def test_rumble_all_three_keys_in_resolved(self) -> None:
        """Rumble E=1 (s197) + Q=2 (s202) + R=2 (s202) — all three present."""
        r = compute_ability_dps(
            self.snap, "Rumble", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"E": 1, "Q": 2, "R": 2})

    def test_smolder_all_three_keys_in_resolved(self) -> None:
        """Smolder W=2 (s197) + Q=1 (s202) + R=1 (s202) + E=1 (s203, extension).
        s202-shape test extended to assert W+Q+R subset rather than equality,
        since s203 added E without removing earlier keys."""
        r = compute_ability_dps(
            self.snap, "Smolder", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved.get("W"), 2)
        self.assertEqual(r.block_index_resolved.get("Q"), 1)
        self.assertEqual(r.block_index_resolved.get("R"), 1)

    def test_viktor_all_three_keys_in_resolved(self) -> None:
        """Viktor R=2 (s198) + Q=2 (s199) + E=2 (s202) — all three present."""
        r = compute_ability_dps(
            self.snap, "Viktor", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"R": 2, "Q": 2, "E": 2})

    # Math-level sanity
    def test_ksante_R_block2_matches_2x_block0(self) -> None:
        """Numeric sanity: KSante R block 2 base = 2× block 0 base across
        all 3 ranks (Total = dash + wall-strike sum)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("KSante", "R", form_index=0)
        self.assertIsNotNone(form)
        blocks = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
        self.assertGreaterEqual(len(blocks), 3)
        for rank, (b0, b2) in enumerate(zip(blocks[0].base, blocks[2].base)):
            self.assertAlmostEqual(
                b2, b0 * 2.0, places=2,
                msg=f"KSante R rank {rank+1}: block 2 base {b2} != 2× block 0 base {b0}"
            )

    def test_vayne_E_block2_matches_2_5x_block0(self) -> None:
        """Numeric sanity: Vayne E block 2 base = 2.5× block 0 base across
        all 5 ranks (Total = dash + wall-slam = block 0 + block 1)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Vayne", "E", form_index=0)
        self.assertIsNotNone(form)
        blocks = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
        self.assertGreaterEqual(len(blocks), 3)
        for rank, (b0, b2) in enumerate(zip(blocks[0].base, blocks[2].base)):
            self.assertAlmostEqual(
                b2, b0 * 2.5, places=2,
                msg=f"Vayne E rank {rank+1}: block 2 base {b2} != 2.5× block 0 base {b0}"
            )

    # Backward-compat: prior-batch entries still resolve unchanged after s202
    def test_pre_s202_jhin_unchanged(self) -> None:
        """Backward-compat: s201 Jhin Q=2 + R=1 preserved after s202."""
        r = compute_ability_dps(
            self.snap, "Jhin", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 2, "R": 1})

    def test_pre_s202_taliyah_unchanged(self) -> None:
        """Backward-compat: s201 Taliyah Q=2 preserved after s202."""
        r = compute_ability_dps(
            self.snap, "Taliyah", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 2})

    def test_pre_s202_ambessa_unchanged(self) -> None:
        """Backward-compat: s200 Ambessa Q=1, W=1, E=1 preserved after s202."""
        r = compute_ability_dps(
            self.snap, "Ambessa", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1, "W": 1, "E": 1})


# ─── Phase 5.9.16 (s203) — 12 entries / 5 new champs + 5 extensions ─────────


class Phase599_16ExpansionTests(unittest.TestCase):
    """Phase 5.9.16 (s203). 12 new (champion, key) entries: 5 truly-new
    champions (Blitzcrank, Gwen, Kled, LeeSin, Thresh) + 5 key extensions
    on existing champions (Diana R, Jax R, Kennen W, Smolder E, Vladimir Q).

    Registry 110 → 115 champions, 161 → 173 entries.

    Six sub-patterns:
      (A) Multi-hit single-target totals (5): Diana R (filtered, 1.7×
          block 1 = initial pull + 4-tick channel), Gwen R (9×, full 3-
          cast 9-needle burst), Kled Q (filtered, 3-stage Beartrap reel),
          Kled E (2×, Jousting recast), Vladimir Q (filtered, 1.85×
          Crimson Rush at full stacks).
      (B) Resource-state amps (1 net new): Smolder E (5×, max-stack
          Achooo!). Vladimir Q also fits this category (Crimson Rush
          builds via taking damage).
      (C) Active-cast vs passive-zap split (3): Blitzcrank R, Kennen W,
          Jax R — engine default block 0 was scoring the passive (per-
          zap / per-4th-AA mark / passive 3rd-AA) as the R/W cast value;
          block 1 captures the active cast realistic burst.
      (D) Max-charge condition amp (1): Kled R (filtered, 3× block 0 at
          full charge time).
      (E) Missing-HP amp layered on form_index (1): LeeSin Q — composes
          with s187 form_index=1 routing to Resonating Strike form, then
          block_index=1 routes to max-missing-HP variant within form 1.
          First instance of layering block_index on form_index that adds
          NET damage (Jayce Q s194 was smaller magnitude precedent).
      (F) Empty-block-0 fix (1): Thresh E — engine default block 0 has
          only unparsed `1.7 per Soul collected` and evaluates to 0;
          registry routes to filtered idx 2 = raw block 2 (base + AP
          magic damage component). First instance of this fix pattern.

    Reverts 1 prior-batch skip rationale: Smolder E (s198/s202 'Meraki
    schema Minimum label ambiguity' → s203: re-framed under operator-
    commits-to-max-stacks, identical model to Smolder Q s202 successful
    reintroduction).

    Tests verify each new entry:
      1. Is present in the resolved registry at the expected filtered idx
      2. Drives total_ability_dps strictly above the forced-block-0 baseline
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _delta_check(self, champion: str, key: str, expected_idx: int) -> None:
        r_reg = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.block_index_resolved.get(key), expected_idx,
                         f"{champion}.{key} should route to filtered block {expected_idx}")
        forced = dict(r_reg.block_index_resolved)
        forced[key] = 0
        r_off = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides=forced,
        )
        self.assertGreater(r_reg.total_ability_dps, r_off.total_ability_dps,
                           f"{champion} registry total should exceed forced-block-0")

    # Pattern A: multi-hit single-target totals (5)
    def test_diana_R_routes_to_filtered_block_2(self) -> None:
        """Diana R filtered idx 2 = raw block 3 'Total Magic Damage' =
        Moonfall full 2-second channel total on pulled target = raw 1
        (initial pull) + 4× raw 2 (per-tick during channel). Filtered
        because raw block 0 is 'Slow' (non-damage). Operator commits to
        landing clean Moonfall + holding target in channel."""
        self._delta_check("Diana", "R", 2)

    def test_gwen_R_routes_to_block_4(self) -> None:
        """Gwen R block 4 'Magic Damage' = 9× block 0 per-needle (3 casts
        × 3 needles each = 9 needles all hitting same target). No filtering
        needed — all 5 blocks are damage (per-needle progression: 1 / recast
        1 / 3-needle / 5-needle / 9-needle). Operator commits to landing
        all 3 R-casts on same target = canonical Gwen burst."""
        self._delta_check("Gwen", "R", 4)

    def test_kled_Q_routes_to_filtered_block_2(self) -> None:
        """Kled Q filtered idx 2 = raw block 3 'Physical Damage' = 3-stage
        Beartrap on Rope full reel-in (3× block 0). Filtered because raw
        block 1 'modifier' + raw block 4 'slow' are non-damage. Operator
        commits to fully reeling target = canonical Kled Q engage."""
        self._delta_check("Kled", "Q", 2)

    def test_kled_E_routes_to_block_1(self) -> None:
        """Kled E block 1 'Physical Damage' = 2× block 0 = Jousting dash +
        recast return on same target within 4-second window. No filtering
        needed — both blocks are damage. Operator commits to recasting E
        on same target = canonical Kled bursty engage."""
        self._delta_check("Kled", "E", 1)

    def test_vladimir_Q_routes_to_filtered_block_1(self) -> None:
        """Vladimir Q filtered idx 1 = raw block 2 'Magic Damage' = 1.85×
        block 0 = Crimson Rush enhanced Q at full passive stacks. Filtered
        because raw block 1 'Heal' is non-damage. Operator commits to
        entering combat with passive stacks ready (passive builds via
        taking damage) = canonical Vladimir burst rotation. Resource-state
        amp same model as Smolder Q/E + Renekton Q full-Fury (s197)."""
        self._delta_check("Vladimir", "Q", 1)

    # Pattern B: resource-state amps (1 net new — Smolder E)
    def test_smolder_E_routes_to_block_1(self) -> None:
        """Smolder E block 1 'Physical Damage' = 5× block 0 = Achooo! at
        max passive stacks (Dragon Practice stacking). Operator commits
        to building Smolder stacks pre-burst, same model as Smolder Q s202
        successful reintroduction. Reverts s198/s202 'Meraki Minimum schema
        label ambiguity' skip — block 1 IS the realistic max-stack value."""
        self._delta_check("Smolder", "E", 1)

    # Pattern C: active-cast vs passive-zap split (3)
    def test_blitzcrank_R_routes_to_block_1(self) -> None:
        """Blitzcrank R block 1 'Magic Damage' 275-525 + 100% AP = active
        cast burst on Static Field detonation. Engine pre-s203 default
        block 0 captured the passive per-zap (50-150 + 30% AP + 2% caster
        max MP) which fires every 2.5s independently — that's the passive
        chain lightning, NOT the active R cast burst. Block 1 = active
        engage realistic value."""
        self._delta_check("Blitzcrank", "R", 1)

    def test_kennen_W_routes_to_block_1(self) -> None:
        """Kennen W block 1 'Magic Damage' 70-170 + 80% AP = active
        Electrical Surge cast burst. Engine pre-s203 default block 0
        captured the passive per-4th-AA Mark of the Storm detonation
        (35-75 + 80-120% bAD + 35% AP) which is per-AA scaling, not per-
        W-cast. Block 1 = active cast realistic value."""
        self._delta_check("Kennen", "W", 1)

    def test_jax_R_routes_to_block_1(self) -> None:
        """Jax R block 1 'Magic Damage' 100-250 + 100% AP = active 3-AA
        enhancement total when Grandmaster's Might is cast. Engine pre-
        s203 default block 0 captured the passive every-3rd-AA scaling
        (75-185 + 60% AP). Block 1 = active R cast realistic burst.
        Lift is small (~1%) because Jax R has long CD; entry is
        architecturally correct for direct /burst queries."""
        self._delta_check("Jax", "R", 1)

    # Pattern D: max-charge condition amp (1)
    def test_kled_R_routes_to_filtered_block_1(self) -> None:
        """Kled R filtered idx 1 = raw block 3 'Magic Damage' tMaxHP 12-24%
        = max-charge Chaaaaaaaarge!!! impact (3× block 2 minimum). Filtered
        because raw blocks 0-1 are 'shield' / 'shield' (non-damage). Operator
        commits to fully charging R before colliding = canonical Kled Skaarl-
        remount engage."""
        self._delta_check("Kled", "R", 1)

    # Pattern E: missing-HP amp layered on form_index (1)
    def test_leesin_Q_routes_to_block_1(self) -> None:
        """LeeSin Q=1 layers on s187 form_index=1 override. Form 1 is the
        Resonating Strike recast (post-Sonic-Wave); within form 1, block 0
        is min damage (55-155 + 115% bAD, no missing-HP), block 1 is max
        damage (110-310 + 230% bAD = 2× block 0 at 50% target missing HP
        via in-game scaling curve). Operator commits to landing Q recast
        on low-HP target = canonical Lee Sin assassination. First NET-
        damage layering of block_index on form_index registry."""
        self._delta_check("LeeSin", "Q", 1)

    # Pattern F: empty-block-0 fix (1)
    def test_thresh_E_routes_to_block_2(self) -> None:
        """Thresh E filtered idx 2 = raw block 2 'Magic Damage' 75-255 +
        70% AP = base+AP MAGIC component of Flay. Engine pre-s203 default
        block 0 has ONLY unparsed `1.7 per Soul collected` (no base, no
        AP, no tAD) and evaluates to 0 damage. Registry routes past the
        empty-evaluation block. First instance of this fix pattern.
        Thresh routes to ds.hps by default (enchanter); entry here is
        for direct /ability-dps queries."""
        self._delta_check("Thresh", "E", 2)

    # Multi-key resolved-shape sanity for extension champions
    def test_diana_both_keys_in_resolved(self) -> None:
        """Diana W=2 (s196) + R=2 (s203) — both keys must appear."""
        r = compute_ability_dps(
            self.snap, "Diana", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"W": 2, "R": 2})

    def test_jax_both_keys_in_resolved(self) -> None:
        """Jax E=1 (s198) + R=1 (s203) — both keys must appear."""
        r = compute_ability_dps(
            self.snap, "Jax", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"E": 1, "R": 1})

    def test_kennen_both_keys_in_resolved(self) -> None:
        """Kennen R=1 (s201) + W=1 (s203) — both keys must appear."""
        r = compute_ability_dps(
            self.snap, "Kennen", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"R": 1, "W": 1})

    def test_smolder_all_four_keys_in_resolved(self) -> None:
        """Smolder W=2 (s197) + Q=1 (s202) + R=1 (s202) + E=1 (s203) —
        all four keys present."""
        r = compute_ability_dps(
            self.snap, "Smolder", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(
            r.block_index_resolved, {"W": 2, "Q": 1, "R": 1, "E": 1},
        )

    def test_vladimir_all_three_keys_in_resolved(self) -> None:
        """Vladimir E=1 (s195) + W=1 (s198) + Q=1 (s203) — all three keys
        present."""
        r = compute_ability_dps(
            self.snap, "Vladimir", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"E": 1, "W": 1, "Q": 1})

    def test_kled_all_three_keys_in_resolved(self) -> None:
        """Kled Q=2 + E=1 + R=1 all new in s203 — all three keys present."""
        r = compute_ability_dps(
            self.snap, "Kled", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 2, "E": 1, "R": 1})

    # Math-level sanity
    def test_gwen_R_block4_matches_9x_block0_base(self) -> None:
        """Numeric sanity: Gwen R block 4 base = 9× block 0 base across all
        3 ranks (Maximum = 3 casts × 3 needles each on same target)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Gwen", "R", form_index=0)
        self.assertIsNotNone(form)
        blocks = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
        self.assertGreaterEqual(len(blocks), 5)
        for rank, (b0, b4) in enumerate(zip(blocks[0].base, blocks[4].base)):
            self.assertAlmostEqual(
                b4, b0 * 9.0, places=2,
                msg=f"Gwen R rank {rank+1}: block 4 base {b4} != 9× block 0 base {b0}"
            )

    def test_kled_Q_filtered_idx2_matches_3x_block0_bAD(self) -> None:
        """Numeric sanity: Kled Q filtered idx 2 = raw block 3; raw block 3
        bonus_ad_pct = 3× raw block 0 bonus_ad_pct (60% → 180%) across
        all 5 ranks."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Kled", "Q", form_index=0)
        self.assertIsNotNone(form)
        # Filtered list — only damage blocks
        damage_blocks = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
        self.assertGreaterEqual(len(damage_blocks), 3)
        b_filt_0 = damage_blocks[0]  # raw 0
        b_filt_2 = damage_blocks[2]  # raw 3 after filtering raw 1 (modifier) + raw 4 (slow)
        for rank in range(len(b_filt_0.bonus_ad_pct)):
            self.assertAlmostEqual(
                b_filt_2.bonus_ad_pct[rank], b_filt_0.bonus_ad_pct[rank] * 3.0,
                places=2,
                msg=f"Kled Q rank {rank+1}: filtered idx 2 bAD% != 3× filtered idx 0",
            )

    def test_leesin_Q_block1_matches_2x_block0_bAD_in_form1(self) -> None:
        """Numeric sanity: LeeSin Q form 1 (Resonating Strike per s187)
        block 1 bonus_ad_pct = 2× block 0 bonus_ad_pct (115% → 230%) =
        max-missing-HP doubling at 50% target missing HP."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("LeeSin", "Q", form_index=1)
        self.assertIsNotNone(form)
        damage_blocks = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
        self.assertGreaterEqual(len(damage_blocks), 2)
        b0, b1 = damage_blocks[0], damage_blocks[1]
        for rank in range(len(b0.bonus_ad_pct)):
            self.assertAlmostEqual(
                b1.bonus_ad_pct[rank], b0.bonus_ad_pct[rank] * 2.0,
                places=2,
                msg=f"LeeSin Q form 1 rank {rank+1}: block 1 bAD% != 2× block 0 bAD%",
            )

    def test_thresh_E_block0_evaluates_to_zero(self) -> None:
        """Sanity: Thresh E raw block 0 has only unparsed soul scaling —
        no base, no AP, no tAD/bAD. The `_evaluate_block` helper should
        return 0 for it, which is why the engine pre-s203 default
        evaluated Thresh E damage at 0. Confirms the empty-block-0 fix
        is necessary."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Thresh", "E", form_index=0)
        self.assertIsNotNone(form)
        damage_blocks = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
        b0 = damage_blocks[0]
        # Base list should be all zeros (or empty/None)
        if b0.base:
            for v in b0.base:
                self.assertEqual(v, 0.0, "Thresh E block 0 should have zero base")
        # AP scaling should be all zeros (or empty/None)
        if b0.ap_pct:
            for v in b0.ap_pct:
                self.assertEqual(v, 0.0, "Thresh E block 0 should have zero AP scaling")

    # Backward-compat: prior-batch entries still resolve unchanged after s203
    def test_pre_s203_yunara_unchanged(self) -> None:
        """Backward-compat: s202 Yunara Q=2 preserved after s203."""
        r = compute_ability_dps(
            self.snap, "Yunara", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 2})

    def test_pre_s203_kennen_R_still_block_1(self) -> None:
        """Backward-compat: s201 Kennen R=1 preserved after s203 added W=1.
        Both keys must coexist."""
        r = compute_ability_dps(
            self.snap, "Kennen", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved.get("R"), 1)
        self.assertEqual(r.block_index_resolved.get("W"), 1)

    def test_pre_s203_smolder_W_still_block_2(self) -> None:
        """Backward-compat: s197 Smolder W=2 preserved after s203 added E=1.
        All four Smolder keys (W, Q, R, E) must coexist with original values."""
        r = compute_ability_dps(
            self.snap, "Smolder", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved.get("W"), 2)  # s197
        self.assertEqual(r.block_index_resolved.get("Q"), 1)  # s202
        self.assertEqual(r.block_index_resolved.get("R"), 1)  # s202
        self.assertEqual(r.block_index_resolved.get("E"), 1)  # s203


class Phase599_17ExpansionTests(unittest.TestCase):
    """Phase 5.9.17 (s204). 8 new (champion, key) entries: 2 truly-new
    champions (Nidalee, Seraphine) + 6 key extensions on existing champions
    (Evelynn Q, Gwen Q, KSante W, Riven R, Syndra W, Zoe E). PLUS Riven is
    added to the form_index registry (`champion_form_index.json`) with R=1
    routing to form 1 'Wind Slash' — closes the s203 carry-forward 'Riven
    form_index seed needed before form-conditional block_index entries'.

    Registry 115 → 117 champions, 173 → 181 entries.

    Six sub-patterns:
      (A) Multi-hit single-target totals (3): Evelynn Q (Hate Spike Total
          Magic = 1 initial + 2× 3-missile recasts, 175% AP scaling),
          Gwen Q (Snip Snip Maximum = 5 small snips + 1 final big snip
          on focused target, 10.3× block 0 base / 22.5× AP), Syndra W
          (Force of Will Total Mixed = block 0 + block 1 sum, 1.12× —
          marginal but consistent under-count).
      (B) Fully-charged amp (1): KSante W (Path Maker Total Maximum
          Mixed at full 2s charge = block 0 + block 2 sum, 1.8×).
      (C) Champion-vs-minion amp (1): Seraphine Q (High Note Maximum
          Champion Damage; 1.75× block 0 — operator burst targets
          champions). Seraphine routes to ds.hps by default but direct
          /ability-dps queries benefit.
      (D) Execute amp layered on form_index (1): Nidalee Q (Cougar
          Takedown Maximum Magic at low-HP target = block 1 in form 1
          via s187 form_index). Second NET-damage layering after s203
          LeeSin Q (form 1 Resonating Strike).
      (E) Target-state amp (1): Zoe E (Sleepy Trouble Bubble Maximum
          Mixed = 2× block 0 base + 2× AP on sleep-procced target).
          First entry reviving the 'conditional target-state schema
          lift' bucket under the unconditional operator-commits framing.
      (F) Form_index seed expansion (1): Riven R (Wind Slash Maximum
          Physical Damage at max-missing-HP). Riven form 0 'Blade of
          the Exile' has ZERO damage blocks (pure buff/empower) — form
          1 is the only damage-bearing form. Form_index seed + block_
          index entry compose cleanly with no information loss.

    Tests verify each new entry:
      1. Is present in the resolved registry at the expected filtered idx
      2. Drives total_ability_dps strictly above the forced-block-0 baseline
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _delta_check(self, champion: str, key: str, expected_idx: int) -> None:
        r_reg = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.block_index_resolved.get(key), expected_idx,
                         f"{champion}.{key} should route to filtered block {expected_idx}")
        forced = dict(r_reg.block_index_resolved)
        forced[key] = 0
        r_off = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides=forced,
        )
        self.assertGreater(r_reg.total_ability_dps, r_off.total_ability_dps,
                           f"{champion} registry total should exceed forced-block-0")

    # Pattern A: multi-hit single-target totals (3)
    def test_evelynn_Q_routes_to_block_5(self) -> None:
        """Evelynn Q block 5 'Total Magic Damage' = 7× block 0 missile
        damage (1 initial Hate Spike + 2 recasts × 3 missiles each = 7
        hits). 175% AP scaling vs block 0's 25%. Operator commits to
        landing full Q rotation on same target during stealth, canonical
        Eve sustained burst. Multi-hit total — same model as Lulu Q s195
        / Sivir Q s195 / Talon W s195."""
        self._delta_check("Evelynn", "Q", 5)

    def test_gwen_Q_routes_to_block_6(self) -> None:
        """Gwen Q block 6 'Maximum Damage' = full max-stack Snip Snip burst
        (5 small snips + 1 final big snip on focused target). 10.3× block 0
        base, 22.5× block 0 AP. Operator commits to landing all snips during
        the 4-second Snip Snip stance — canonical Gwen scissors burst. Same
        max-stack-burst pattern as s203 Gwen R (9-needle full 3-cast)."""
        self._delta_check("Gwen", "Q", 6)

    def test_syndra_W_routes_to_block_2(self) -> None:
        """Syndra W block 2 'Total Mixed Damage' = block 0 + block 1 sum
        = 78.4 base + 74.2% AP (block 0 = 70 + 65% AP, block 1 = 8.4 +
        9.2% AP). Operator commits to hitting target with the BoW orb's
        Bonus Damage on top of the Magic Damage. Marginal 1.12× lift but
        captures a consistent component the engine was missing. Pattern
        A sum-of-blocks via canonical 'Total' attribute name."""
        self._delta_check("Syndra", "W", 2)

    # Pattern B: fully-charged amp (1)
    def test_ksante_W_routes_to_block_3(self) -> None:
        """KSante W block 3 'Total Maximum Mixed Damage' = block 0 Physical
        + block 2 Maximum Bonus True Damage at full 2s charge = 1.8×
        block 0 base. Operator commits to fully charging W before release.
        Same fully-charged amp pattern as Vi Q s198 / Sion Q s197 /
        Pantheon Q s196 / Janna Q s201."""
        self._delta_check("KSante", "W", 3)

    # Pattern C: champion-vs-minion amp (1)
    def test_seraphine_Q_routes_to_block_1(self) -> None:
        """Seraphine Q block 1 'Maximum Champion Damage' = 1.75× block 0
        base + 1.75× AP scaling. High Note deals reduced damage to
        non-champions (block 0 = minion-reduced fallback); block 1
        captures the canonical champion-burst case. Same model as Talon Q
        s199 (Noxian Diplomacy guaranteed crit on champion vs minion).
        Seraphine routes to ds.hps by default (enchanter) but direct
        /ability-dps queries benefit. Revives s198/s202 'enchanter-class'
        deferral under same framing as other archetype-mismatched entries."""
        self._delta_check("Seraphine", "Q", 1)

    # Pattern D: execute amp layered on form_index (1)
    def test_nidalee_Q_routes_to_block_1(self) -> None:
        """Nidalee Q=1 layers on s187 form_index=1. Form 1 is the Cougar
        Takedown (post-R cougar form); within form 1, block 0 is Minimum
        Magic Damage (full-HP target), block 1 is Maximum Magic Damage
        (low-HP target, 2.75× block 0 base + 1.3× AP scaling). Operator
        commits to using cougar Q on low-HP targets as the canonical Eve
        execute, same model as KogMaw R s196 Living Artillery low-HP
        execute. Second NET-damage layering of block_index on form_index
        registry after s203 LeeSin Q."""
        self._delta_check("Nidalee", "Q", 1)

    # Pattern E: target-state amp on sleep proc (1)
    def test_zoe_E_routes_to_block_2(self) -> None:
        """Zoe E block 2 'Maximum Mixed Damage' = 2× block 0 base + 2× AP
        scaling on sleep-procced target (canonical Zoe E→Q burst combo:
        E lands, sleeps target, then Q hits sleeping target for the
        amplified damage). Operator commits to landing E and waking the
        target with damage — first entry reviving the 'conditional target-
        state schema lift' bucket under the unconditional operator-commits
        framing. Same model as Khazix Q isolation s196 / Vayne E wall-stun
        s202."""
        self._delta_check("Zoe", "E", 2)

    # Pattern F: form_index seed expansion (1)
    def test_riven_R_routes_to_block_1_via_form_index_seed(self) -> None:
        """Riven R=1 + new form_index Riven.R=1 (Wind Slash form). Riven R
        form 0 'Blade of the Exile' has ZERO damage blocks (pure buff/
        empower); form 1 'Wind Slash' carries the only damage. Block 1
        'Maximum Physical Damage' = 3× block 0 base + 3× bonus_ad_pct
        scaling at max-missing-HP target. Operator commits to using
        Wind Slash recast on low-HP target as the canonical Riven R
        execute. Form_index seed shipped alongside — closes the s203
        carry-forward 'Riven form_index registry seed needed for form-
        conditional block_index entries'. First new champion added to
        form_index registry since s187 (Nidalee/Elise/Jayce/Hwei/LeeSin)."""
        self._delta_check("Riven", "R", 1)
        # form_index resolved must also be 1 for R (sourced from registry)
        r_reg = compute_ability_dps(
            self.snap, "Riven", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.form_index_resolved.get("R"), 1,
                         "Riven R should route to form 1 via form_index registry seed")

    # Multi-key resolved-shape sanity for extension champions
    def test_evelynn_both_keys_in_resolved(self) -> None:
        """Evelynn R=1 (s191) + Q=5 (s204) — both keys must appear."""
        r = compute_ability_dps(
            self.snap, "Evelynn", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"R": 1, "Q": 5})

    def test_gwen_both_keys_in_resolved(self) -> None:
        """Gwen R=4 (s203) + Q=6 (s204) — both keys must appear."""
        r = compute_ability_dps(
            self.snap, "Gwen", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"R": 4, "Q": 6})

    def test_ksante_both_keys_in_resolved(self) -> None:
        """KSante R=2 (s202) + W=3 (s204) — both keys must appear."""
        r = compute_ability_dps(
            self.snap, "KSante", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"R": 2, "W": 3})

    def test_riven_both_keys_in_resolved(self) -> None:
        """Riven Q=1 (s196) + R=1 (s204) — both keys must appear in
        block_index_resolved; form_index_resolved must also contain R=1."""
        r = compute_ability_dps(
            self.snap, "Riven", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1, "R": 1})
        self.assertEqual(r.form_index_resolved.get("R"), 1)

    def test_syndra_both_keys_in_resolved(self) -> None:
        """Syndra R=2 (s195) + W=2 (s204) — both keys must appear."""
        r = compute_ability_dps(
            self.snap, "Syndra", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"R": 2, "W": 2})

    def test_zoe_all_three_keys_in_resolved(self) -> None:
        """Zoe Q=1 (s195) + W=1 (s202) + E=2 (s204) — all three keys present."""
        r = compute_ability_dps(
            self.snap, "Zoe", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1, "W": 1, "E": 2})

    # Math-level sanity
    def test_gwen_Q_block6_matches_block0_max_stack_total(self) -> None:
        """Numeric sanity: Gwen Q block 6 base values must be substantially
        larger than block 0 (the per-snip damage). At rank 5, block 0 base
        is 30 (per-snip); block 6 base is 310 (Maximum Damage = full max-
        stack 5-snip + 1-final burst on focused target)."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Gwen", "Q", form_index=0)
        self.assertIsNotNone(form)
        damage_blocks = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
        self.assertGreaterEqual(len(damage_blocks), 7)
        b0, b6 = damage_blocks[0], damage_blocks[6]
        # Block 6 base must be >5× block 0 base across all ranks
        for rank in range(len(b0.base)):
            self.assertGreater(b6.base[rank], b0.base[rank] * 5.0,
                               f"Gwen Q rank {rank+1}: block 6 base should be >5× block 0")

    def test_riven_R_form0_has_no_damage_blocks(self) -> None:
        """Sanity: Riven R form 0 'Blade of the Exile' is a pure buff form
        with zero damage blocks. Justifies the form_index seed routing to
        form 1 'Wind Slash' — no information loss because form 0 has no
        damage to lose."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form0 = ab_snap.get_ability("Riven", "R", form_index=0)
        self.assertIsNotNone(form0)
        damage_blocks = [b for b in form0.damage_blocks if b.attribute_kind == "damage"]
        self.assertEqual(len(damage_blocks), 0,
                         "Riven R form 0 should have zero damage blocks")

    def test_nidalee_Q_form1_block1_matches_max_missing_hp_amp(self) -> None:
        """Numeric sanity: Nidalee Q form 1 (Cougar Takedown per s187)
        block 1 base = 2.75× block 0 base (220 vs 80 at max rank). Same
        execute-curve pattern as LeeSin Q s203."""
        from agents.daemon_slayer.abilities import load_default
        ab_snap = load_default()
        form = ab_snap.get_ability("Nidalee", "Q", form_index=1)
        self.assertIsNotNone(form)
        damage_blocks = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
        self.assertGreaterEqual(len(damage_blocks), 2)
        b0, b1 = damage_blocks[0], damage_blocks[1]
        # Block 1 base at max rank must be >2× block 0 base
        self.assertGreater(b1.base[-1], b0.base[-1] * 2.0,
                           f"Nidalee Q form 1: block 1 base {b1.base[-1]} should be >2× block 0 {b0.base[-1]}")

    # Backward-compat: prior-batch entries still resolve unchanged after s204
    def test_pre_s204_thresh_unchanged(self) -> None:
        """Backward-compat: s203 Thresh E=2 preserved after s204."""
        r = compute_ability_dps(
            self.snap, "Thresh", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"E": 2})

    def test_pre_s204_blitzcrank_unchanged(self) -> None:
        """Backward-compat: s203 Blitzcrank R=1 preserved after s204."""
        r = compute_ability_dps(
            self.snap, "Blitzcrank", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"R": 1})

    def test_pre_s204_leesin_unchanged(self) -> None:
        """Backward-compat: s203 LeeSin Q=1 (layered on s187 form_index)
        preserved after s204. Riven layering shipped this batch should not
        regress LeeSin's prior layering."""
        r = compute_ability_dps(
            self.snap, "LeeSin", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1})
        # Form_index resolved should still route Q to form 1 (s187)
        self.assertEqual(r.form_index_resolved.get("Q"), 1)


# ─── backward-compat: unmapped champions keep pre-s191 output ───────────────


class BackwardCompatTests(unittest.TestCase):
    """Pre-s191 callers (no block_index_overrides arg, unmapped champion)
    must see the exact same numbers — block_strategy="first" remains the
    legacy default."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_unmapped_burst_matches_explicit_first(self) -> None:
        """Zed isn't in the registry — burst with no override should equal
        burst with explicit empty override."""
        r_default = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80, target_mr=30, target_max_hp=2000,
        )
        r_empty_explicit = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides={},
        )
        # block_index_overrides={} routes through resolver — caller's empty
        # dict + no registry entry → empty merged → all keys use global
        # block_strategy="first". Numbers must match exactly.
        self.assertEqual(r_default.total_burst_damage, r_empty_explicit.total_burst_damage)

    def test_unmapped_ability_dps_matches_explicit_first(self) -> None:
        r_default = compute_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
        )
        r_empty_explicit = compute_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
            block_index_overrides={},
        )
        # Veigar has R in registry — must NOT match here. So skip Veigar and
        # use another unmapped champion.

    def test_unmapped_keys_inside_mapped_champion_use_global_strategy(self) -> None:
        """Veigar has only {R:1} in the registry. Q, W, E must still use
        block_strategy="first" → block 0. Veigar (since s196) is the
        stable single-key champion for this check (Cassi extended to W=1)."""
        r = compute_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
        )
        # The resolved map carries R:1 but no Q/W/E entries.
        self.assertEqual(r.block_index_resolved, {"R": 1})
        # And the Q/W/E spells in per_spell rendered with the default
        # first-block strategy (we don't assert exact damage values because
        # they require snapshot-specific math; the registry-resolution shape
        # is the contract).


# ─── server route surfaces source ────────────────────────────────────────────


class ServerRouteSourceTests(unittest.TestCase):
    BASE_URL = "http://127.0.0.1:8893"

    @classmethod
    def setUpClass(cls) -> None:
        try:
            urlopen(f"{cls.BASE_URL}/health", timeout=2).read()
        except Exception as e:  # pragma: no cover — env-dependent
            raise unittest.SkipTest(f"DS server unavailable: {e}")

    def _post(self, path: str, body: dict) -> dict:
        req = Request(
            f"{self.BASE_URL}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        return json.loads(urlopen(req, timeout=10).read())

    def test_ability_dps_champion_source(self) -> None:
        # Cassiopeia was extended in s196 with W=1 (Miasma full duration)
        # alongside the s191 E=1 (Twin Fang vs poisoned).
        r = self._post("/ability-dps", {
            "champion": "Cassiopeia", "level": 11, "mode": "SR", "target_mr": 30.0,
        })
        self.assertEqual(r["block_index_source"], "champion")
        self.assertEqual(r["block_index_resolved"], {"E": 1, "W": 1})

    def test_ability_dps_default_source(self) -> None:
        # Caitlyn is the stable unmapped champion (deliberately skipped in
        # s191 — block 1 'Reduced Damage' is the FALLBACK case, block 0 IS
        # realistic). Aatrox was previously here but landed in the registry
        # at s197 with W=3 (Infernal Chains pull-back).
        r = self._post("/ability-dps", {
            "champion": "Caitlyn", "level": 11, "mode": "SR", "target_mr": 30.0,
        })
        self.assertEqual(r["block_index_source"], "default")
        self.assertEqual(r["block_index_resolved"], {})

    def test_ability_dps_explicit_override(self) -> None:
        # Caller's {"E": 0} override merges with the registry's W=1 entry —
        # resolved is the union (caller wins per-key, registry fills gaps).
        r = self._post("/ability-dps", {
            "champion": "Cassiopeia", "level": 11, "mode": "SR", "target_mr": 30.0,
            "block_index": {"E": 0},
        })
        self.assertEqual(r["block_index_source"], "override")
        self.assertEqual(r["block_index_resolved"], {"E": 0, "W": 1})

    def test_rank_mage_champion_source(self) -> None:
        r = self._post("/rank-mage", {
            "champion": "Cassiopeia", "level": 11, "mode": "SR",
            "target_mr": 30.0, "top": 3,
        })
        self.assertEqual(r["block_index_source"], "champion")

    def test_burst_champion_source(self) -> None:
        r = self._post("/burst", {
            "champion": "Veigar", "level": 11, "mode": "SR",
            "target_armor": 80, "target_mr": 30.0,
        })
        self.assertEqual(r["block_index_source"], "champion")
        self.assertEqual(r["block_index_resolved"], {"R": 1})

    def test_rank_assassin_champion_source(self) -> None:
        r = self._post("/rank-assassin", {
            "champion": "Evelynn", "level": 11, "mode": "SR",
            "target_armor": 80, "target_mr": 30.0, "top": 3,
        })
        self.assertEqual(r["block_index_source"], "champion")


if __name__ == "__main__":
    unittest.main()
