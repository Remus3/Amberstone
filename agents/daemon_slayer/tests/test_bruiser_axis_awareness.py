"""RED-first regression: the bruiser (hybrid) scorer must be damage-axis-aware.

Before this fix, ``rank_items_by_hybrid`` scored damage purely by auto-attack
``compute_dps().weighted_dps``, so an AP champion routed to the bruiser archetype
(an operator archetype-pick pre-LEDGER-824, or any ``/rank-bruiser`` caller) built
full AD (Trinity/Heartsteel/on-hit) - identical to an AD bruiser, zero AP items.

This pins the axis-aware behavior: AP-axis champions (``merged_info`` magic >
attack) get AP damage items through the bruiser scorer, while AD-axis champions
stay byte-identical (no AP items float in).
"""
import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hybrid import rank_items_by_hybrid

# AP damage / power legendaries + mythics (magic scaling).
AP_ITEM_IDS = {
    "6653",  # Liandry's Torment
    "3089",  # Rabadon's Deathcap
    "3115",  # Nashor's Tooth
    "4645",  # Shadowflame
    "3135",  # Void Staff
    "2503",  # Blackfire Torch
    "4633",  # Riftmaker
    "3157",  # Zhonya's Hourglass
    "3100",  # Lich Bane
    "6655",  # Luden's Companion
    "3152",  # Hextech Rocketbelt
    "6656",  # Everfrost
    "4629",  # Cosmic Drive
    "4646",  # Stormsurge
    "3116",  # Rylai's Crystal Scepter
    "6620",  # Malignance
}

AP_CHAMPS = ["Mordekaiser", "Sylas", "Vladimir", "Rumble"]
AD_CHAMPS = ["Aatrox", "Darius", "Renekton"]


class BruiserAxisAwarenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _top_ids(self, champ: str, n: int = 8) -> list[str]:
        res = rank_items_by_hybrid(self.snap, champ, 11, mode="SR", top_n=n)
        return [it.item_id for it in res.ranked[:n]]

    def test_ap_champs_build_ap_through_bruiser_scorer(self) -> None:
        for champ in AP_CHAMPS:
            ids = self._top_ids(champ)
            ap = sum(1 for i in ids if i in AP_ITEM_IDS)
            self.assertGreaterEqual(
                ap, 3,
                f"{champ} (AP-axis) via bruiser scorer surfaced {ap} AP items "
                f"in top-8 {ids} - expected >=3",
            )

    def test_ad_champs_stay_ad_through_bruiser_scorer(self) -> None:
        for champ in AD_CHAMPS:
            ids = self._top_ids(champ)
            ap = sum(1 for i in ids if i in AP_ITEM_IDS)
            self.assertEqual(
                ap, 0,
                f"{champ} (AD-axis) via bruiser scorer surfaced {ap} AP items "
                f"in top-8 {ids} - expected 0 (byte-identical AD path)",
            )
