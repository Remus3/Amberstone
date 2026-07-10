"""Preview which boots the ON path would change vs the committed OFF output.

Prints an archetype x mode x comp -> (off_boot -> on_boot) report. Writes NO
table file - purely advisory so the operator can eyeball the effect before
deciding to flip assume_boot_utility default-ON (the seam ships DEFAULT-OFF).

Run: python ops/audit/boot_utility_preview_diff.py
"""
from __future__ import annotations

from core.build_order import _select_boots
from core.build_order_precompute import COMP_BIAS

ARCHES = ["marksman", "mage", "assassin", "tank", "enchanter", "bruiser"]
MODES = ["SR", "ARAM", "CHERRY"]


def main() -> None:
    changes = 0
    total = 0
    for arch in ARCHES:
        for comp, bias in COMP_BIAS.items():
            ad = float(bias.get("enemy_ad_share", 0.5))
            ap = float(bias.get("enemy_ap_share", 0.5))
            armor = float(bias.get("target_armor", 0.0))
            mr = float(bias.get("target_mr", 0.0))
            for mode in MODES:
                total += 1
                off, off_n = _select_boots(arch, armor, mr, mode=mode,
                                           enemy_ad_share=ad, enemy_ap_share=ap,
                                           assume_boot_utility=False)
                on, on_n = _select_boots(arch, armor, mr, mode=mode,
                                         enemy_ad_share=ad, enemy_ap_share=ap,
                                         assume_boot_utility=True)
                if off != on:
                    changes += 1
                    print(f"{arch:10s} {mode:7s} {comp:16s}  "
                          f"{off_n} ({off}) -> {on_n} ({on})  "
                          f"[ad={ad:.2f} ap={ap:.2f}]")
    print(f"\n{changes}/{total} cells change if assume_boot_utility flips default-ON.")


if __name__ == "__main__":
    main()
