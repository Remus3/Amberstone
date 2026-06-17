# DS Cross-Eval: Ezreal

VERDICT: MISMATCH

Scorer: dps | Archetype: carry (secondary mage) | Anchor: ARAM
Evidence tier ARAM: outcome_self (n=41, baseline wr 46.3)

---

## Axis 1 - archetype_ok: PASS

carry = AD scorer axis. Ezreal is a hybrid AD/spell champion but his damage
deals physical (Q scales AD, W scales AP but is secondary, E/R are AD-scaling
poke). Empirically winning items in ARAM all (baseline 48.5) include
Muramana (wr 50.0), Last Whisper (wr 60.6), Long Sword (wr 59.3),
Mercury's Treads (wr 56.7) - all AD-side items. AD axis is correct.

---

## Axis 2 - comp_ok: PASS

Scorer = dps (offense-only). Target-resist responsiveness is present and
meaningful: max_positive_shift=23 (Liandry's Torment +23 ranks when tanky),
Serylda's Grudge +10, Mortal Reminder +8, Lord Dominik's +6, Eclipse +5.
target_resist.comp_blind=false. Correct behavior for a dps scorer.

Enemy damage type: max_positive_shift=0, comp_blind=true. A pure dps scorer
does not model the player's survivability, so enemy AD/AP mix not shifting
item ranks is expected - this is NOT a defect for an offense scorer. No
flag here.

---

## Axis 3 - outcome_ok: FAIL (MISMATCH)

Using ARAM self (n=41, baseline wr 46.3) per evidence_tier directive.

Scorer top-8 squishy cells (ad_squishy / bal_squishy):
  rank 1 Blade of the Ruined King (3153) score 85.1
  rank 2 Runaan's Hurricane (3085) score 53.6
  rank 3 Kraken Slayer (6672) score 51.8
  rank 4 Void Immolation (223069) score 51.6
  rank 5 Essence Reaver (3508) score 51.1
  rank 6 Stormrazor (3097) score 47.0
  rank 7 Infinity Edge (3031) score 44.8
  rank 8 Eclipse (6692) score 43.2

Empirical ARAM self items above baseline (46.3): NONE. All self items are
below baseline. Highest-n self items:
  Muramana (3042) n=35 wr=42.9 - below baseline, ABSENT from scorer top-8
  Trinity Force (3078) n=31 wr=38.7 - below baseline, ABSENT from scorer top-8
  BotRK (3153) n=12 wr=25.0 - scorer rank 1, empirical wr 25.0 (-21.3 vs baseline)

Critical finding: scorer top-1 item BotRK has ARAM self wr=25.0, 21 points
below baseline. Muramana (Ezreal's highest-volume item, n=35) and Trinity
Force (n=31) - both core Spellblade/mana-spend items - are completely absent
from scorer top-8.

ARAM all data (n=274, baseline 48.5) confirms: Muramana wr 50.0 (above
baseline), Serylda's Grudge 43.7, Last Whisper 60.6 (small n), Long Sword 59.3.
None of these appear in scorer top-8. BotRK wr=49.0 in all data (barely above
baseline) but scorer gives it score 85.1 - wildly inflated vs empirical signal.

This is a scorer pool + ranking mismatch. The dps scorer is modeling generic
auto-attack-crit ADC patterns (BotRK, Runaan's, Kraken, Stormrazor, IE) but
Ezreal is a spell-weaver whose DPS is gated by Q-hit frequency and Muramana
mana-spend procs, not autoattack chain speed. Runaan's Hurricane in particular
is actively bad on Ezreal (he doesn't spam autos) - n appears low and absent
from self empirical top-10 entirely.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Ezreal should be registered in a spell-carry sub-scorer or given a champion
override that credits Muramana (mana-spend DPS proc) and Trinity Force
(Spellblade proc) at their actual ability-DPS contribution. The current dps
scorer treats him as a generic auto-carry, inflating BotRK/Runaan's/IE and
missing the Muramana/Spellblade/armor-pen (Serylda's) core entirely.

Minimal retune: add champion-level item affinity weights for Ezreal so
Muramana and Trinity Force score above BotRK; demote Runaan's Hurricane
(no multi-target auto synergy on Ezreal).
