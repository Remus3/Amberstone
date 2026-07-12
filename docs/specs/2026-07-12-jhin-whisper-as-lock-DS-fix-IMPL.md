# Jhin Whisper AS-lock DS fix - IMPLEMENTATION SPEC

Status: grounded, file-cited (Plan agent 2026-07-12), verified-reproduced. FOLDED to the
next-session multi-agent per-champion DS build-plan sweep (operator 2026-07-12) as champion #1
/ the TEMPLATE. NOT built this session. Re-verify every cited anchor + the load-bearing Whisper
formula (A1/A2) at build time (RC verification discipline). ASCII-only (no arrows/em-dashes).

## Reproduced bug
`python -m agents.daemon_slayer.cli beam Jhin --mode SR --level 18` and
`core.build_order.plan_build_order('Jhin','carry',level=18,owned_item_ids=[],mode='SR')` top
Jhin's build with Runaan's Hurricane 3085 (delta ~103.9), Stormrazor, and boots Berserker's
Greaves 3006 - all attack-speed items, wasted on Jhin (Whisper locks AS + converts bonus AS/crit
to AD).

## Root cause (grounded)
Jhin DDragon: attackspeed 0.625, attackspeedperlevel 0 (level AS bonus already 0) - so the
over-credit is ITEM attack speed. engine.py _combine_items (engine.py:188-195) rebuilds
out["as"] = base_as*(1 + bonus_as_levels + item as_pct); dps.py:543 total_attacks = basic +
basic_time*eff_as inflates base-AA DPS (dps.py:547-550) AND Runaan's bolt procs
(dps.py:564-568). delta_dps the ranker sorts on (rank.py:420-421) compounds the AS error.
DDragon/Meraki strip Whisper's numbers (Jhin.json:35-47 prose only), so the engine has no
AS-lock / AS->AD signal. Runaan's ranged-only gate (rank.py:214-217) correctly does NOT fire
(Jhin is ranged); the bug is scoring, not purchasability.

## Part A - engine AS-lock override (DEFAULT-ON, not a seam)
Whisper is a permanent mechanic, so this lives at the load-time chokepoint build_champion where
every scorer (dps/burst/ability_dps/hybrid/ehp/rank/beam/build_order) resolves stats uniformly.
- NEW agents/daemon_slayer/_passive_as_lock_overrides.py - mirror the shape of
  agents/daemon_slayer/_passive_as_overrides.py (frozen dataclass + dict keyed by champion_id +
  accessor + wiki-cited note). Frozen AsLockEntry: locks_as: bool, level_ad_pct: tuple[18 floats],
  ad_per_bonus_as: float (0.30), ad_per_crit: float (0.35), note. ONE entry "Jhin".
  as_lock_entry(champion_id) -> AsLockEntry | None (None for every other champion).
- Consumer walk in build_champion (engine.py) AFTER the Overlord's bonus-AD walk (~engine.py:411)
  and immediately BEFORE final = _combine_items(...) (~engine.py:413):
    entry = as_lock_entry(champion_id)
    if entry is not None:
        base_ad = scaled.get("ad", 0.0)                 # leveled base AD = 61 flat
        as_frac = item_totals.get("as_pct", 0.0)
        crit_frac = min(1.0, item_totals.get("crit_flat", 0.0))
        whisper_ad = base_ad*(entry.level_ad_pct[level-1]/100.0
                              + entry.ad_per_bonus_as*as_frac + entry.ad_per_crit*crit_frac)
        if whisper_ad > 0: item_totals["ad_flat"] = item_totals.get("ad_flat",0.0) + whisper_ad
        if entry.locks_as: item_totals["as_pct"] = 0.0
  Guarded on entry is not None -> non-Jhin byte-identical. Zeroing as_pct makes the AS rebuild
  resolve out["as"]=base_as (0.625); converted AD folds via the generic flat-AD path
  (engine.py:210-214) into stats["ad"]; crit stays in stats["crit"] (no double-count).

## Jhin values (RE-VERIFY from wiki.leagueoflegends.com action=raw - A1/A2 load-bearing)
- locks_as=True (flat 0.625). level_ad_pct = [4,5,6,7,8,9,10,11,12,14,16,20,24,28,32,36,40,44] (L1-18).
- ad_per_bonus_as=0.30 (AD per 1% bonus AS). ad_per_crit=0.35 (AD per 1% crit). Base = leveled base AD 61 (flat).
- A1: confirm % applies to BASE AD (61), not total AD. A2: reconfirm 0.30/0.35 + level table against the raw
  Template:Data_Jhin/Whisper (WebFetch is lossy; crit coeff has 0.4->0.35 history). A3: confirm Stormrazor id (3095) in item.json.

## Part B - boots override (core/build_order.py; NOT Share-mirrored)
- Add _BOOTS_OVERRIDE_BY_CHAMP = {"Jhin": "3009"} (Boots of Swiftness, stocked in _BOOTS_IDS
  build_order.py:99) next to _BOOTSLESS_CHAMPS (build_order.py:222).
- Thread champion: str = "" into _select_boots (build_order.py:244) + _select_boots_utility
  (build_order.py:228); consult the override ONLY in the default branch - replace
  _DEFAULT_BOOTS_BY_ARCHETYPE.get(arch,"3006") (build_order.py:290, OFF-path) + default_id
  (build_order.py:236, ON-path). Leave the situational Mercury/Steelcaps branches (build_order.py:285-288)
  intact. Pass champion=champ_name_norm at the call site (build_order.py:550-559). A4: 3009 (Swiftness,
  Whisper MS synergy + immobile backline) vs 3158 Ionian (haste) - design; do NOT default 3006/3020.

## Sibling sweep (Jhin UNIQUE - anti-narrow)
NEEDS-OVERRIDE: Jhin only. MUST-NOT-TOUCH: Bel'Veth (SAME attackspeedperlevel:0 signature but scales
with UNCAPPED AS - proves the override must be an explicit dict, NEVER an automatic perlevel==0 rule);
Senna (0.625/2.6), Graves (0.475/3, reload scales WITH AS), Kalista (0.694/4.5), Kog'Maw (0.665/2.65,
canonical AS-inverse). Both override dicts contain exactly ONE entry (Jhin).

## Backfill (REQUIRED - served precomputed tables carry the wrong build)
1. data/daemon_slayer/build_orders/16.13.1/build_orders_sr.json (Jhin :4349) - regen via
   tools/daemon_slayer_build_orders_generate.py (sr/aram/arena + build_order_variants_*).
2. data/champion_loadouts.json (Jhin :14491, BotRK/Berserker's/Runaan's) - re-align via
   tools/champion_loadout_align.py / tools/champion_loadout_validate_meta.py (or hand-swap).
3. Old-patch tables (16.11.1/16.12.1) - historical, leave unless the operator asks.

## Tests (RED-first) agents/daemon_slayer/tests/test_jhin_whisper_as_lock.py (Share-mirrored)
Jhin (RED->GREEN): AS locked with Runaan's == naked (~0.625); bonus-AS->AD (~0.30*0.40*61);
crit->AD (~0.35*crit_frac*61); rank_items top excludes 3085/3095/3006; plan_build_order + beam
exclude them and boots slot == 3009; _select_boots("marksman",...,champion="Jhin") == ("3009","Boots of Swiftness").
Control (STAY GREEN): Jinx AS still scales with 3085 + boots==3006; Kog'Maw AND Bel'Veth AS still rise
with an AS item (must-not-touch + anti-narrow guards).

## Release (Tier-2)
1. Bump agents/daemon_slayer/__init__.py:18 ENGINE_VERSION 1.203.0 -> 1.204.0 (A5 minor, behavior change).
2. Update the exact-match pin agents/daemon_slayer/tests/test_dsp_live_consumers.py:104.
3. Full pytest: agents/daemon_slayer then tests/ - green.
4. Share mirror: python tools/ds_share_sync.py then --check (mirrors agents/daemon_slayer/**; core/build_order.py NOT mirrored - repo-only).
5. Backfill regen (above).
6. py_compile all changed .py; commit fix(daemon-slayer): model Jhin Whisper AS-lock + AS/crit->AD, boots override (ENGINE 1.203.0 -> 1.204.0); push.
7. Restart DS :8893 (not supervisor-watched): schtasks /End /TN RC-DaemonSlayer then /Run (confirm port free first; taskkill /F fallback; never Stop-Process).
8. Verify /health engine_version 1.204.0; /beam Jhin no longer tops Runaan's/Berserker's; Jinx unchanged.
9. Living docs (CLAUDE.md/docs/DAEMON_SLAYER.md/README engine version + DS test count) + LEDGER + WAKEUP.

## Stays LIVE-GATED (do not assert from tests)
Real SR Jhin game: overlay/coach build renders the corrected crit build + Boots of Swiftness (not
Runaan's/Stormrazor/Berserker's) vs the live client; Jhin's in-game AD/AS matches modeled locked-0.625
+ converted-AD. Record in docs/LIVE_GAME_GATED_SYNC.md (do-not-flip-blind).

## Assumptions to resolve at build (A1-A6)
A1 (load-bearing) base-vs-total AD; A2 coefficients + level table reconfirm; A3 Stormrazor id;
A4 boot 3009 vs 3158; A5 semver 1.204.0 vs 1.203.1; A6 crit->AD capped, Arena/ARAM AS paths inert for the SR bug.

## Sweep-template note
This spec is the TEMPLATE for the next-session multi-agent per-champion build-plan sweep: for each
champion, (1) detect an unmodeled-passive scoring gap (AS-lock like Jhin, or other stat conversions/
caps), (2) add a per-champion override at the build_champion chokepoint, (3) RED-first tests + control
champs that MUST stay unchanged, (4) Tier-2 ENGINE bump + Share + backfill. See memory
project_next_ingame_ui_finish + project_daemon_slayer_engine.
