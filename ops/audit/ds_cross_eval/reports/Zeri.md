# Zeri DS Cross-Eval Report

**Verdict: MINOR**
Scorer (dps/carry) axis is correct for Zeri AD carry. Target-resist responsiveness is present (max shift +14 Serylda's). Two high-wr empirical staples are absent from scorer top-8, and BotRK (scorer rank 3) is an empirical loser. No axis mismatch, no EHP comp-blind defect.

---

## 1. archetype_ok: true

scorer = dps. Carry/bruiser archetype -> AD axis. Correct.
Zeri is a physical-damage AA-scaling carry. DPS scorer is the right tool.
No AP items in kit; secondary bruiser does not change the axis.

---

## 2. comp_ok: true

scorer = dps -> primary_axis = target_resist (confirmed in data).
target_resist.comp_blind = false. max_positive_shift = 14 (Serylda's Grudge +14 vs tanky AP targets). Top risers vs tanky: Serylda's +14, Mortal Reminder +6, Terminus +4, LDR +4, Liandry's +4. Good responsiveness.

enemy_damage_type.comp_blind = true (all 5 comp cells return identical scores).
For a pure DPS scorer this is EXPECTED: Zeri deals physical damage; what matters is the target's armor/MR, not whether enemies deal AP or AD. Enemy damage type is an EHP concern, not a DPS concern. Not a defect here.

Comp-cell ordering does shift vs tanky (Liandry's moves from rank 6 in squishy to rank 2 in tanky; Essence Reaver drops from rank 2 to rank 4). Target-resist axis is working.

---

## 3. outcome_ok: false

Using outcome_self (n=33 >= 8). Baseline wr = 66.7%.

Items strictly above baseline wr:
  Berserker's Greaves  78.3%  (n=23)
  Yun Tal Wildarrows   75.0%  (n=20)

Items at or near baseline (66.7%):
  Runaan's Hurricane   66.7%  (n=27, highest volume)
  Navori Flickerblade  66.7%  (n=9)

Scorer top-8 (ad_squishy):
  #1 Void Immolation    81.93
  #2 Essence Reaver     36.99
  #3 BotRK              32.24
  #4 Dusk and Dawn      31.50
  #5 Stormrazor         30.14
  #6 Liandry's Torment  28.73
  #7 Voltaic Cyclosword 28.53
  #8 Lich Bane          24.06

Problems:
- Yun Tal Wildarrows (75.0% wr, n=20, above baseline): NOT in scorer top-8. Empirically Zeri's second-best item is invisible to the scorer.
- Runaan's Hurricane (66.7% wr, n=27, most-built item): NOT in scorer top-8 at all.
- BotRK (scorer rank 3): empirical wr = 50.0% (n=10), well below 66.7% baseline. Scorer is over-ranking it.
- Stormrazor, Dusk and Dawn, Voltaic Cyclosword, Lich Bane: zero representation in empirical top items.
- IE at scorer rank 10 maps to empirical 60.9% wr (below baseline) - mild underperformer in pool but not a top-8 problem.

---

## 4. rune_ok: n/a

rune_relevant = false.

---

## Nominated Retune

Boost Runaan's Hurricane and Yun Tal Wildarrows in the Zeri DPS scorer pool (both are top empirical items absent from scorer top-8). Investigate BotRK overranking: %max-HP damage formula may be overcounting vs squishy targets in ARAM where BotRK is empirically at baseline. Consider a Zeri-specific weight adjustment or verify BotRK passive interaction with Zeri's kit scaling.
