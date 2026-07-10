# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05 + HZ-regrn+ARAM-leak-fix (2026-07-08, LEDGER 814-815) + enemy-spells CSS fix (2026-07-08, LEDGER 816) + /live-gated-drain (2026-07-08, LEDGER 820) archived 2026-07-09. Only the last 3 sessions kept here.

---

# 2026-07-10 (DS Forbidden Idol HSP registry credit - R90 sibling of R60; ENGINE 1.187.0 -> 1.188.0, Tier-2)

Gemini-loop DIRECTOR REFILL R90. Full detail: LEDGER 831. Commit `52fa7edb`. DS `:8893` bounced to 1.188.0.

- GAP (adversarial Meraki 16.13.1 vs registry refute on the R60 `assume_hsp_amp` seam): the 5 finished HSP
  carriers (Ardent 3504 / Staff 6616 / Redemption 3107 / Mikael 3222 / Echoes 6620) are credited in
  `enchanter_items.json`, but the shared COMPONENT they all build from - Forbidden Idol (3114) - was ABSENT,
  so `sum_wielder_hsp_pct(['3114'])==0.0` though it grants +8% HSP (wiki V12.14 10%->8%; finished carry 0.10).
- FIX: pure registry data-add (3114 -> `heal_shield_amp_pct` 0.08) reusing R60's EXISTING default-OFF
  `assume_hsp_amp` seam (ehp.py self-shield + sustain.py REGEN). NO new field/flag/engine-code. Default-OFF
  byte-identical; 3114 non-terminal -> no `rank_items_by_hps` leak. Armed -> shield pool + REGEN sustain *1.08.
- VERIFY: TDD RED-first (test_forbidden_idol_hsp_r90.py, 8 tests, 5 RED pre-fix); read-only verifier CONFIRM
  all 6 claims + re-reproduced DS 8098/0-fail. Value 0.08 wiki-verified + internal-consistency cross-checked.
- GATES: DS 8098 passed / 0 fail; RC 11244 passed + 3 transient reds (1 phase8 live-engine stale-anchor GREEN
  post-bounce, 2 pre-existing coach-poll flake) all pass in isolation, 0 R90 regressions; Share 419 --check green.
- Tier-2 sync: 105 test pins re-stamped (125 occ), CHANGELOG + DAEMON_SLAYER banner (1.188.0/8098), 6 HZ-B
  tables stamp-only regen, hps.py docstring 9->10.
- LIVE: default-ON HSP flip EXCLUDED / operator-gated; LIVE_GATED B43 extended to cover 3114.
- Don't-redo: wielder-HSP registry now COMPLETE for the SR enchanter line (5 finished + the Forbidden Idol
  component); next DS-sweep refill = a FRESH Meraki-vs-registry refute of a DIFFERENT mechanic, never HSP.

---

# 2026-07-10 (combat-style archetype chip on champ-select My Pick card - R89 Aggregator C lift; UI slice)

Gemini-loop DIRECTOR REFILL R89. Full detail: LEDGER 830. UI slice, presentation-only, NO ENGINE bump,
commit `e2ff5982`. No RC restart (asset-hash ADR-008), no DS bounce (ENGINE-IMPACT NONE).

- LIFT: Section-7b competitor teardown of the Aggregator C live companion (docs/COMPETITOR_LIFT_2026-07-10.md;
  pages fetched via an Apify full-browser render, Cloudflare 403'd WebFetch). Verdict SPLIT: F2 combat-style
  HIGH/LOW-risk -> SHIPPED; F1 lane-matchup MED -> BACKLOG.
- F2 shipped: read-only archetype tag chip (CARRY/BRUISER/TANK/MAGE/ASSASSIN/ENCHANTER) on the champ-select
  My Pick card (SR+ARAM), sourced from the archetype RC already resolves + client-caches
  (`_CSV_ARCH_CACHE.primary`, `/api/cs-archetype-pick`) but never rendered since the picker was removed
  (LEDGER 823). New `web/js/panels/archetype_chip.js` reuses the `.csv-build-badge` tint family; one compact
  `.csv-archetype-chip` CSS rule (width:auto; font inherits --fs-xs). No backend/Claude/schema change.
- VERIFY: research citations ground-truthed before build (`get_archetype_for` :32->:592 corrected). 5-phase
  UI audit PASS (MUST-FIX 200px width fixed in-slice); visual champ-select_aram.png = compact CARRY chip
  under Jinx. TDD: node 7/7 + CI contract 7/7 + a `/api/cs-archetype-pick` conftest fixture. snapshot_panels
  359 + CS regression 24 + hygiene 13; ruff clean; CI green.
- Tails (BACKLOG R89): F2a Arena chip parity (LOW); F1a WR best/worst counters list (MED); F1b prose tips +
  F2b behavioral player badges CLOSED. Don't-redo: the combat-style chip is SHIPPED for SR+ARAM.

---

# 2026-07-10 (DS Armored Advance Plating EHP credit - R86 sibling-carrier; ENGINE 1.187.0)

Gemini-loop DIRECTOR REFILL R88. Full detail: LEDGER 829. Tier-2, commit `b6a64836`, DS `:8893`
bounced to 1.187.0 (health engine 1.187.0, patch 16.13.1, 173 champs / 706 items).

- REFUTE PASS (inline, DDragon+Meraki 16.13.1 vs registry across all 3 anti-AA lanes x every map mirror):
  exactly ONE uncredited sibling carrier - Armored Advance (3174, tier-3 Steelcaps upgrade) carries the
  IDENTICAL "Plating -10% incoming basic-attack damage" that R80 gave Steelcaps 3047/223047, but its entry
  (`_effects_data.py:5397`) was a bare `defensive_only` NOTE-only -> ZERO EHP credit. crit-DR (Randuin's) +
  enemy-AS-slow (Frozen Heart) have NO sibling gap; no Arena/ARAM 3174 mirror; 3174 is poolable.
- FIX (2-file build-slice + verifier gate): set the PRE-EXISTING `basic_attack_damage_reduction=0.10` on
  3174. NO new field/flag, NO `ehp.py` change - reuses R80's EXISTING `assume_item_aa_dr` seam.
- LIVE STATUS: `assume_item_aa_dr` is DEFAULT-ON (`ehp.py:1070`, operator flip B45/B46 2026-07-06), so this
  is a live DATA-COMPLETION (Armored Advance now credited like the already-live Steelcaps), NOT a new gated
  flip - no LIVE_GATED row owed. (The commit body's "stays LIVE-GATED" line was imprecise; corrected in
  LEDGER 829 + ORCH R88.) Build orders unchanged (boots picked by `_select_boots`, not the EHP beam).
- Tier-2: 106 test-pin re-stamps + DAEMON_SLAYER banner 1.187.0/8090 + CHANGELOG 1.187.0 + the 6 HZ-B tables
  re-stamped (STAMP-ONLY, content byte-identical) + `ds_share_sync` 418 files `--check` green.
- GATES (fresh): DS 8090 passed / 1 skipped / 1943 subtests; RC 11238 passed / 2 failed (the PRE-EXISTING
  coach-poll asyncio flake, isolation = 2 passed, baseline == item 828, NOT a regression) / 22 skipped;
  new test 5 pass; verifier CONFIRM; CI green. done_sentinel --tests 19328 --regressions 0. Don't-redo: the
  Plating lane is SATURATED (3047/223047/3174); crit-DR + AS-slow have no siblings this patch.
