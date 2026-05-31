# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-30 - item 227: DS V2 bounded-combat-simulator substrate (5-slice parallel headless-upgrade run) (HEAD 7353be0; pushed acaf2fe..7353be0; CI green run 26703611726; NO ENGINE bump - 1.63.0 stays; NO DS restart; all 5 modules ADDITIVE, not wired into live :8893 scorers)

Operator: "continue DS missing-by-design + implement missing designs; review lolmath changelog; expand DS in parallel; V2; mana real-usage-not-infinite; cross-interaction fight sims; full + frozen rights; do not solely trust current DS for V2 - start implementation + put-off items." Re-issued same prompt mid-dispatch (no in-flight slice) -> task re-assert, continued.

V2 = steady-state DPS calculator -> BOUNDED COMBAT SIMULATOR. Plan + contracts in NEW docs/DS_V2_PLAN.md. 6 parallel worktree agents on disjoint files, orchestrator-merged (5 commit-bearing + 1 read-only); 0 conflicts. DS 5077 -> 5191 (+114). Full DS suite green, ruff clean, CI green.

5 substrate modules (ALL additive, nothing wired into live scorers - do NOT auto-wire):
- mana_sim.py (545/19t): finite-mana bounded rotation; pool=stats.scaled mp + item mana, regen/5; OOM-gates burst per-cast .cost; manaless/energy ungated (bounded==unbounded). Wait-to-ready cooldown (not combo skip) so the gate binds. Lux L9 14/24 OOM -> +Tear 18 -> +Archangel's 21 monotonic.
- rune_procs.py (396/32t): net-new rune layer (RC had ZERO). 8 runes; ALL coeffs verified+corrected vs LIVE DDragon 16.11.1 (brief numbers stale).
- ability_hps.py v2 (+154/-21; 17+22t): passive-P + target-relative/missing-HP units. HONEST: zero P-form heal damage_blocks in snapshot (heals in stripped effects-text) = data ceiling, asserted not fabricated. v1 byte-identical.
- self_shred.py (401/21t): target_shred -> own-DPS uplift; AD-reduction shreds (Trundle/Tryndamere) correctly skipped.
- scenario_matrix.py (431/25t): cross-interaction sweep + 5 invariants + violation probe (not a no-op).
- lolmath changelog: 0 NOW / 0 FUTURE / 7 CLOSED - all already correct in RC or by-design.

DON'T-REDO: all 5 additive (no auto-wire); ability_hps P-heal = data ceiling (do NOT re-hunt); rune coeffs DDragon-verified (trust formula strings); mana_sim wait-to-ready intentional; lolmath nothing actionable.

NEXT (operator-gated, ENGINE bump each, the repeatable continue picks up): (1) wire ability_hps v2 -> LIVE ds.hps enchanter scorer (re-ranks builds + lower-bound -> validate; DEFERRED from blind overnight); (2) unified V2 fight-report compose 5 modules; (3) wire rune_procs into burst/combo; (4) expand rune+champ coverage + mana_sim as scenario_matrix metric. Item 225's 6 data sidecar buckets still owed wiring.

CARRY: 6 R1 agent worktrees harness-locked (live pids 4044/20624) - next pre-flight cleans. Anomaly RC-CostHealthWatchdog last_result=1 (pre-existing watchdog; flag for operator). Frozen-file grant NOT used.

---

# 2026-05-30 - item 226: DS scraper-review 3-slice fix (lolmath chat) - ability heal/shield scorer + modifier taxonomy + bounded mana valuation (commit 5a303c2; CI green run 26702508176; NO ENGINE bump - 1.63.0 stays; NO DS restart; additive)

Operator pasted a lolmath dev-chat (a peer maintainer/Redymix) about moonbeam's scraper + 6 perceived issues; asked "review DS for the contents noted in here and provide a fix if needed - commenting on findings."

**VERDICT (verified vs ground truth, NOT agent-relayed - drift scan: committed 16.11.1 == current scraper, 1709 blocks 0 mismatch):**
- #1 Caitlyn W null damage_type -> no damage = NOT A BUG (Cait W has 0 `damage` blocks; Meraki omits trap damage; RC correctly scores 0).
- #3 MIXED mis-assignment / "two `_abil_damage_type` w/ F811" = NOT A BUG (no such dup exists - agent hallucinated; `_mitigation_factor` routes MIXED 50/50, null->MAGIC, per-block honored).
- #3b Akali electrocute proc-count / passive double-count = CANNOT EXIST (RC has ZERO rune-proc layer; Akali P = 0 damage blocks).
- #2 + #6 + #7 = real deferred-by-design gaps -> FIXED this session.

**AskUserQuestion:** operator picked all 3 buildable (#6 + #2 + #7). 3 slices, all PURELY ADDITIVE (byte-identical when knobs unset) so NO ENGINE bump + NO DS :8893 restart (phase8 70/70 vs live 1.63.0 confirms).

**#6 NEW `agents/daemon_slayer/ability_hps.py`** (24 tests): champ-spell heal/shield was extracted (96 heal + 56 shield blocks) but never consumed. ROOT CAUSE found by probing: heal/shield numbers live ONLY in `raw_modifiers` (flat + % AP / % bonus AD / % max health), never the typed fields the damage `_evaluate_block` reads -> returns 0 for every heal/shield block. `compute_ability_hps` parses raw_modifiers directly: caster-side unit map + meta-attr denylist (`_META_HEAL_SHIELD_RE` skips cost-reductions/multipliers/HP-grants), mirrors ability_dps AP-amp chain, folds ARAM aramHealing/aramShielding per-side, measured cast rates. Verified vs raw data: Soraka W=130 heal, Janna E=80 shield, Sona W dual 60 heal + 65 shield.

**#2 NEW `agents/daemon_slayer/modifier_blocks.py`** (22 tests): the 180 modifier blocks ARE correctly dropped from DPS - they're heterogeneous (125 pve-only / 17 target-shred / 17 defensive-self / 15 self-amp / 6 other), NOT one clean multiplier. A blanket apply would multiply champ damage by minion numbers + double-count resist shred. `classify_modifier_kind` + `summarize_modifiers` make them queryable WITHOUT corrupting DPS; target_shred (Nasus E etc.) flagged as the one real-champ-DPS class for a future deliberate slice.

**#7 `rank.py` `rank_items`** (+12 tests): NEW optional `mana_value_per_point` param. DPS scorer values flat mana ~0 so Tear/Lost Chapter/Blackfire rank below burn/AP for mana casters. Adds `mana_value_per_point * mana_gained` to each candidate's `mana_adjusted_score`, sorts by it. `RankedItem` gains `mana_adjusted_score` + `mana_gained` (both default 0.0). None/0/negative = byte-identical; no effect under sort_by=efficiency or when fight_length engaged. Probed on Ziggs: Blackfire (mp+600) surfaces #5.

**Verified:** DS suite 5077 / RC 4091 (+1 skip +71 subtests) / phase8 70/70 green; ruff clean repo-wide. RankResult has NO `mana_value_per_point` field (knob surfaced via notes, mirrors fight_length).

**Don't-redo:** (a) Issues #1/#3/#3b are RC non-bugs - do NOT re-investigate. (b) NO ENGINE bump happened - 1.63.0 is current; all 3 slices additive. (c) `ability_hps.py` is v1 ACTIVE-only - passive-P heals (Aatrox/Vladimir/DrMundo) + target-relative units (Taric W % target max-HP) are OUT OF SCOPE v1, flagged lower-bound not silently zeroed. (d) NOTHING in the engine consumes ability_hps or modifier_blocks yet - they are data-driven substrate for a future enchanter-HPS scorer / coach surface / self-shred DPS slice (each its own engine slice + ENGINE bump when opened). (e) target_shred is the ONE modifier class with real unconditional champ-DPS impact RC does not model - future slice. (f) the 2 `.bak-units20260530-003054` files are pre-existing item-225 junk (NOT mine; left untracked).

---

# 2026-05-30 - item 225: DS/RC missing-data SOURCE SWEEP (5 agents) + "all 6 data only" 3-sidecar extraction + lolmath handoff (commit e2db0c2; CI green; DATA-ONLY - NO ENGINE bump, NO DS restart, NO engine wiring)

Operator: "what other sites can be deep-dive researched to lift DS/RC's missing data - investigate each + trace to upstream until exhausted." Then "apply all the gains ... all 6 data only, no engine." Then commit+push + a standalone lolmath handoff.

**SWEEP (`docs/DS_DATA_SOURCE_SWEEP_2026-05-30.md`):** 5 parallel agents, all verbatim-grounded. Verdict EXHAUSTED: 4 upstream layers only (DDragon, CommunityDragon RAW = deepest/game WAD bins, Meraki, LoL wiki). All 13 downstream sites CLOSED (calc.gg cites Meraki+DDragon/math server-side; lolmath DEAD/parked; aggregator P<-Aggregator B; aggregator B/aggregator A/aggregator D/aggregator C/overlay app E/overlay app F/esports stats site Z3/esports stats site Z2 = Match-V5 win-rate aggregators). CC-duration-seconds = TRUE CEILING (structured nowhere; CDragon buff scripts 404; wiki/Meraki free-text only).

**3 sidecars shipped (`data/daemon_slayer/16.11.1/`, e2db0c2):** wiki_stats.json +mode_modifiers (170 champs; urf/ofa/usb/nb MULTIPLIERS, ar/swift ADDEND stat-overrides; AA timing byte-reproduced 61 measured/110 default); cdragon_spell_stats.json (NEW; per-spell ammo 24/missile 416/cc_tags 186/geometry 619; 171/171, 0 err); wiki_ability_stats.json (NEW; per-ability static-CD 55/recharge 20/CC-flags 753; 1046 abilities). 3 extractors (stdlib, batched wiki query ~22 calls not 850) + offline tests (mode-mults 80 / cdragon 60 / wiki-ability 49). Stale dup `tests/test_wiki_stats_extract.py` DELETED.

**Fiddlesticks fix:** bin splits across two name casings (Root under FiddleSticks, spells under Fiddlesticks) - `_spells_index` now scans all Characters/*/Spells/ prefixes + `_char_root_name` prefers the spellNames root; +3 regression tests; errors 1->0 (171/171).

**lolmath handoff** `Desktop\lolmath_handoff\` (NON-repo): standalone README + 3 data files + 3 tools + sweep doc. a peer maintainer replied they do NOT pull the wiki + think it needs HTML scraping - README now explicitly answers: MediaWiki API not scraping (action=raw = whole roster in 1 GET; action=query batches Template:Data; non-browser UA gotcha). So the wiki-derived buckets are genuinely net-new to lolmath.

**Carries (tomorrow-you):** (a) ENGINE WIRING of the 6 buckets is the next slice IF operator opens it - data is staged on disk, consumers deferred (each its own batch + ENGINE bump + DS restart + DPS validation). DO NOT auto-wire. (b) DO NOT re-research: CC-duration-seconds (ceiling), 110 default-AA champs (ceiling), Arena/Swiftplay dmg-mult (does not exist - stat overrides only), all 13 downstream sites, anything below CDragon (byte-equiv). (c) wiki access: non-browser UA passes / Mozilla trips Cloudflare 403; CDragon URL 2-segment (16.11 not 16.11.1). (d) all item 224/223/221 carries unchanged.
