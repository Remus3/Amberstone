"""Daemon Slayer — local item-build engine.

Phase 2 step 4 + Phase 3 + Phase 4: stat math + auto-attack DPS layered
with per-item conditional effects from ``effects.py``, single-slot item
ranking (``rank.py``), and full-build beam search (``beam.py``).

Effects coverage: IE / Kraken / Stormrazor / BT / Shieldbow (thin slice)
plus the energized family (Statikk Shiv, Rapid Firecannon, Voltaic),
scaling procs (Wit's End, Runaan's, Trinity Force, Sundered Sky,
Guinsoo's, Lich Bane, Nashor's Tooth), the armor pen / reduction layer
(LDR, Mortal Reminder, Black Cleaver), the symmetric magic pen layer
(Void Staff, Cryptbloom, Sorcerer's Shoes, Shadowflame — Phase 4
batch 4, 2026-05-04), the target-HP layer (BotRK Mist's Edge,
Eclipse Ever Rising Moon — Phase 4 batch 5, 2026-05-04), the
caster-HP layer (Titanic Hydra Cleave, Heartsteel Colossal
Consumption — Phase 4 batch 6, 2026-05-04), the multi-target rotation
layer (Ravenous Hydra Cleave — Phase 4 batch 7, 2026-05-04), the
multi-proc-per-item schema (Titanic Hydra cleave-to-others — Phase 4
batch 8, 2026-05-04), Immolate items (Sunfire Aegis, Hollow Radiance —
Phase 4 batch 9, 2026-05-04, reusing the caster-HP + multi-target
layers with no new schema), unique-passive enforcement (Phase 4
batch 10, 2026-05-04 — ItemEffect.unique_passive_key + dedup in
collect_effects; first user is "immolate" tagging Sunfire + Hollow
Radiance), spellblade unique-passive (Phase 4 batch 11, 2026-05-04 —
Trinity Force + Lich Bane share a "spellblade" key; Sundered Sky's
distinct "Lightshield Strike" and Essence Reaver's defensive_only
entry intentionally untagged), lifeline unique-passive (Phase 4
batch 12, 2026-05-04 — Immortal Shieldbow + Sterak's Gage + Maw of
Malmortius share a "lifeline" key; Phantom Dancer's distinct
"Spectral Waltz" Ghost effect intentionally untagged), Terminus
promoted from defensive_only (Phase 4 batch 13, 2026-05-04 — Shadow
on-hit 30 magic per basic + Juxtaposition Dark sustained 10% armor
pen + 10% magic pen), build-wide damage amplifier schema (Phase 4
batch 14, 2026-05-04 — ItemEffect.damage_amp_pct + multiplicative
stacking via total_damage_amp_multiplier; first user is Riftmaker's
8% Void Corruption at full ramp), HP→AP cross-derivation (Phase 4
batch 15, 2026-05-04 — ItemEffect.ap_per_bonus_hp_pct + additive
helper total_bonus_ap_from_hp; Riftmaker's Void Infusion 2% bonus
HP → AP wired so Lich Bane / Nashor's Tooth procs see the converted
total), and 26 defensive_only items spanning the Tier-1 SR / Arena
pool plus high-pickrate batch 2 + AP batch 3 additions.
CallContext + callable ``bonus_damage`` lets stat-scaling procs bind
to ``base_ad`` / ``bonus_ad`` / ``level`` / ``ap`` / ``target_max_hp`` /
``caster_max_hp`` / ``caster_bonus_hp`` / ``targets_in_rotation``.

Beam search (Phase 2 step 4) returns the top-N complete builds by final
weighted DPS, finding multi-item synergies the single-slot ranker
misses. Boots-uniqueness on by default; ``total_budget`` clamps total
build gold; ``current_item_ids`` pins the user's current build.

The local HTTP server (``server.py``) exposes ``/stats``, ``/dps``,
``/rank``, and ``/beam`` on :8893; the package stays importable for
direct use without spinning the engine.
"""

ENGINE_VERSION = "0.22.0"
