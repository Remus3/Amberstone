"""2026-05-31 (item 238) - null-damage-type ability correction registry.

Context: a sibling project's scraper-refactor chat (validated against DS
2026-05-31) flagged that abilities with a null ``damageType`` in the Meraki
bulk dump lose their mitigation type. RC's evaluator defaults a null
``damage_type`` to MAGIC (``ability_dps._mitigation_factor`` /
``compute_ability_dps`` ``(form.damage_type or "MAGIC")``). A roster scan of
patch 16.11.1 found 27 ability forms with a null ``damage_type`` AND a real
``attribute_kind == "damage"`` block. Two correction classes, both verified
against the form's actual damage_blocks + the Meraki effects-text:

1. DAMAGE_TYPE_OVERRIDES - the form deals real damage but the engine
   mis-mitigates it as MAGIC. Each entry corrects ``form.damage_type`` so
   the mitigation pipeline uses the right resist. Strictly improves accuracy
   vs a resisted target; byte-identical vs a 0-armor / 0-MR target.
   - PHYSICAL: block[0] is pure physical (currently routed through MR).
   - MIXED: block[0] is the combined equal-parts physical+magic block
     (Yone W/R "Total Mixed Damage"); the engine's MIXED = 50/50 armor/MR
     is exact for an equal phys+magic split.

2. NON_DAMAGE_BLOCKS - block[0] (the one ``block_strategy="first"`` picks)
   is NOT damage dealt - it is a self attack-damage GRANT (World Ender /
   Ragnarok / Final Hour / Bloodlust bonus AD, Eye of the Storm's AD grant,
   Aphelios weapon AD) or a shield value (Aria of Perseverance "Minimum
   Damage Mitigated"). The Meraki ``_classify_attribute`` labeled it
   ``"damage"`` because the attribute name contains "Damage". Summing it is
   PHANTOM damage that inflates DPS at every target. We flip the matching
   block's ``attribute_kind`` to ``"other"`` so every damage consumer skips
   it. The honest extractor fix is a ``_classify_attribute`` rule + a
   re-extract; that is deferred (the Meraki ``latest`` endpoint is mutable),
   so this score-time override is the grounded interim.

Magic abilities whose null-type block IS genuinely magic (Skarner W, Zeri
E/R, Nunu Q, Ahri/Fizz/Gwen/Lillia/Velkoz/Pantheon block[0], Yunara Q) are
INTENTIONALLY ABSENT - the MAGIC default is already correct for them. Ryze R
has an empty block (evaluates to 0, no phantom). Yunara R is left untouched
(new champion, ambiguous block - do not guess).

Applied at load time in ``abilities.AbilitiesSnapshot.load`` so every
consumer (ability_dps / burst / dps / fight_report / scenario / hps) sees the
corrected form uniformly. Keyed ``(champion_id, key, form_index)``.
"""
from __future__ import annotations

# (champion_id, key, form_index) -> corrected damage_type.
# Verified 2026-05-31 against block[0] + Meraki effects-text at patch 16.11.1.
DAMAGE_TYPE_OVERRIDES: dict[tuple[str, str, int], str] = {
    ("Camille", "Q", 0): "PHYSICAL",   # "Bonus Physical Damage" (block[0]); 2nd cast adds true
    ("Sett", "W", 0): "PHYSICAL",      # Haymaker physical to all (center line is true)
    ("Smolder", "Q", 0): "PHYSICAL",   # "Physical Damage" base + 130% bonus AD
    ("Udyr", "Q", 0): "PHYSICAL",      # "Bonus Physical Damage" %max-hp (block[0])
    ("Urgot", "R", 0): "PHYSICAL",     # Fear Beyond Death first-cast physical
    ("Yone", "W", 0): "MIXED",         # "Total Mixed Damage" = equal phys+magic
    ("Yone", "R", 0): "MIXED",         # "Total Mixed Damage" = equal phys+magic
}

# (champion_id, key, form_index) -> set of block "attribute" names whose
# attribute_kind must flip "damage" -> "other" (phantom: self-buff / shield,
# not damage dealt). Verified 2026-05-31 against block values + effects-text.
#
# Residual sweep (2026-05-31): a follow-up pass over every
# attribute_kind=="damage" block whose NAME suggests a non-damage value found
# 2 more of the same mislabel class, each confirmed via the form's ed[0] text
# and a live block-eval (block[0] is the one block_strategy="first" selects):
#   DrMundo E - block[0] "Bonus Attack Damage" is the Blunt Force Trauma AD
#     grant (caster_max_hp scaled); the real damage is block[1]/[2].
#   Twitch R  - block[0] "Bonus Attack Damage" is the Spray and Pray steroid;
#     it is R's only block (R empowers basic attacks, so cast damage is 0).
# Three candidates were checked and intentionally NOT flipped:
#   Mel R - block[0] "Increased Stored Damage" looks phantom (ed[0] "Passive:
#     Overwhelm stacks store more damage"), but Mel R is routed to block 2
#     ("Total Damage") by the block-index registry, so block[0] is never the
#     default-selected block; flipping it would change the forced-block-0
#     delta baseline that test_block_index_overrides pins, with no default-path
#     benefit (Mel is a new champ with ambiguous storage-block semantics - left
#     to the existing block-index model).
#   Nocturne Q / Trundle Q - each carries a grant block, but it is block[1],
#     never selected under block_strategy="first", so summing it cannot occur
#     (a flip would be a no-op today and a latent regression if a future patch
#     reorders the blocks).
NON_DAMAGE_BLOCKS: dict[tuple[str, str, int], frozenset[str]] = {
    ("Aatrox", "R", 0): frozenset({"Bonus Attack Damage"}),     # World Ender +AD buff
    ("Aphelios", "P", 0): frozenset({"Bonus Attack Damage"}),   # weapon-system AD grant
    ("DrMundo", "E", 0): frozenset({"Bonus Attack Damage"}),    # Blunt Force Trauma AD grant
    ("Janna", "E", 0): frozenset({"Bonus Attack Damage"}),      # Eye of the Storm AD grant
    ("Olaf", "R", 0): frozenset({"Bonus Attack Damage"}),       # Ragnarok +AD buff
    ("Sona", "W", 0): frozenset({"Minimum Damage Mitigated"}),  # Aria shield value
    ("Tryndamere", "Q", 0): frozenset({"Bonus Attack Damage"}),  # Bloodlust +AD buff
    ("Twitch", "R", 0): frozenset({"Bonus Attack Damage"}),     # Spray and Pray AD steroid
    ("Vayne", "R", 0): frozenset({"Bonus Attack Damage"}),      # Final Hour +AD buff
}
