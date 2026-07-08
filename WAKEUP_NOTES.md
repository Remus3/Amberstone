# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05 + HZ-regrn+ARAM-leak-fix (2026-07-08, LEDGER 814-815) + enemy-spells CSS fix (2026-07-08, LEDGER 816) + ARAM Mayhem drain (2026-07-08, LEDGER 817). Only the last 3 sessions kept here.

---

# 2026-07-08 (HZ build-order regen + ARAM coach SR-leak fixes)

Session 1 -- HZ build-order table regen + accrual rails:
- Regen all 3 mode build-order tables (173 champs) from live DS :8893
- HZ precompute tables (build_orders/16.13.1/) static regen all 173
- Zero Gunmetal Greaves (3172) in any build_orders_sr.json
- G1 laning: 98.02% coverage, 46.88% agreement
- G2 build-order: followed +3.6% winrate, flip_ready=False
- Commit 268e0952.

Session 2 -- ARAM coach showing SR prompts:
- recall_callout now gated SR-only via _RECALL_MODES frozenset (ARAM has no fountain recall)
- ZOI map_control callout gated SR-only in _compute_uncached (quadrant labels "bot river / dragon" are Summoner's Rift concepts)
- resolve_coach_fields no longer fills blank immediate when coach already filled action (ARAM coach intentionally retires immediate in favor of choices)
- Commit 2a72be50. All 166 related tests green. CI green.

DO NOT redo: T3 boot fix (19a76d8b + 415c1795), map_control dupe fix (2ddbc331), BATCH B/C verify, recall_callout/ARAM leak (2a72be50), HZ build-order regen (268e0952).

NEXT: Section J OPEN WPs, or DS engine gaps (Aphelios rotation-DPS/A).

---

# 2026-07-08 (enemy-spells CSS overflow fix)

Session -- overlay enemy-spells chip wrapping:
- Root cause: w-enemyspells default --ovx-w:210px too narrow. 5 enemy rows (name ~140px + 2 chips min 54px each) forced chips to wrap to second line per row, inflating height causing scrollbar at 2560x1440.
- Fix: set --ovx-w:280px on [data-ovx-id="w-enemyspells"] so every row fits name + 2 chips on ONE line. Interior 264px > name (126px) + 2 chips (109px) + gaps (10px) = 245px. No wrap, no scrollbar.
- 5/5 enemy_spells_abbr tests green.
- Commit fb08ea23.
- VISUAL VERIFY PENDING: overlay_visible=false at commit time; verify with /overlay snapshot next time game is foreground.

DO NOT redo: T3 boot fix, map_control dupe, recall_callout/ARAM leak, HZ build-order regen, BATCH B/C verify.

---

# 2026-07-08 (/live-gated-drain ARAM Mayhem Kai'Sa)

Session -- live ARAM drain, 1 Mayhem game (Kai'Sa, enemy Leona/Renata/Kennen/Hwei/Ekko):
- PASS (4 items): C13 enemy_spells data path (5 enemies x 2 spells correct), A/B choices (3 choices with labels/outcomes), reset_item ARAM-aware ("No fountain"), R78 item_extra shadow-only.
- NOT CHECKED (wrong conditions): C12 antiheal, C15/C16 augment, C3/C5/C8 (Kai'Sa not tabled), C11 cc ecosystem, B28-DS level-tick stability, C13 pixel capture (overlay hidden).
- 2 LIVE BUGS FOUND (code patches not yet written):
  1. STALE COACH ARTIFACT: aram_coaching_data.json fight_rule/risk referenced Annie/Morgana from previous game vs current enemies Leona/Renata/Kennen/Hwei/Ekko. Root cause: _base_coach.py _ensure_data() only writes blank on missing file; stale daemon_slayer_picks/scorer/fight_rule survive game restart. Artifact has no game_id for cross-game invalidation.
  2. VOID IMMOLATION LEAK (symptom of #1): daemon_slayer_picks showed 223069 #1 with scorer="hybrid" for Kai'Sa. DS /rank correctly excludes it. The stale hybrid scorer picks were from a previous bruiser game.
- NEXT: fix stale-artifact bug (blank on game_id change), then continue ARAM Mayhem drain.

DO NOT redo: T3 boot fix, map_control dupe, recall_callout/ARAM leak, HZ build-order, enemy-spells CSS.
