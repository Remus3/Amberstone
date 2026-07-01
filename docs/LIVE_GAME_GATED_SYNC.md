# Live-Game-Gated Sync Checklist

PURPOSE. One consolidated list of every RC/DS item that CANNOT be finished headless because
it needs a real game (live LCU, live `:2999`, rendered pixels, or a re-rank that must be eyeballed
against a real match). When the operator says "I am in live games" (planned: 2026-06-17+),
run these ALL IN SYNC, grouped by the game phase where each becomes testable, so one play
session clears the whole backlog.

The headless loop MAINTAINS this file: every DEFAULT-OFF seam it ships (DSV*/DSP*) appends its
live default-ON flip here. The loop NEVER flips these blind (charter 4b do-not-flip-blind).

How to use: operator queues one game per mode; tick each row; report results back so the loop's
next cycle can flip the validated seams default-ON. RC auto-serves UI via ADR-008 (no restart for
web changes); engine flips need a DS `:8893` restart.

---

## Next-session play order (bundle plan, 2026-06-17)

34 open gated boxes. Minimum game set to clear the ONE-SHOT items = 3 games
(the HZ + producer-census items below need a CORPUS, not one eyeball):

```
GAME 1  SR (ranked or normal)
  champ-select  -> section A (all 5: LCU push, CS2 spell push, brief-flip shadow, CC-pair UI)
  in-game       -> section B (build-chooser push; eyeball the flag-ready re-rank seams via the
                   harness output; inhibitor callout when an inhib is down; st-* census; vision :8889)
  overlay       -> section E (launch rc-shell IN this game: Alt+Shift+A capture + ACTIVE knob)
  post-game     -> section F (PGR S3/S4/S5 capture + @N metrics; 90s Match-V5 ingest freshness)
GAME 2  ARAM (KIWI)
  -> section A(aram) + section C (all 5) + re-eyeball the ARAM-validated DS seams
     (RF1/RF2/RF3+RF6, DSP11, DSP3 - the doc rows below say "eyeball in a real ARAM")
GAME 3  Arena (1750)
  -> section A(arena 6x3 capture) + section D (all 3: augment OCR, set_augment_intent probe, boots mirror)
```

PREP (built headless 2026-06-17, so live = eyeball-and-tick, no mid-game restarts):

- Flag-ready re-rank seams (11): DSV2/DSV3/DSV4, DSP2, DSP8, DSP11 (dps+burst),
  RF1, RF2, RF3+RF6, B1 (apply_melee_aa_gate, dps+hybrid), F2 (cost_ceiling,
  hybrid+ehp+dps). Run `python ops/audit/ds_perm_swarm/live_flip_eyeball.py`
  (or `--champions <csv>` / `--champion X --preset tank`) -> `report/live_flip_eyeball.{json,md}`
  dumps OFF-vs-ON top-6 per (champ, seam). Eyeball that diff in-session instead of
  flipping + restarting :8893 per seam. The seam-ON ranking matched every documented
  intent on the 5-champ smoke (Ezreal Trinity Force, Pyke Axiom Arc/Youmuu's, KSante
  Iceborn/Thornmail, Rakan Warmog's/Heartsteel, Rell Fimbulwinter).
- NOT in the harness: DSP4 (`score_completion_runes`) is a burst-NUMBER delta on
  `compute_burst_damage`/`compute_combo` (needs a runes set), not a re-rank - eyeball it
  with a direct call at flip. DSP3 is an RC-side resolver (no :8893 restart). DSP5/6/7 +
  anti-tank P3.2 need their consumer/producer wired first (in progress).

ACCRUAL items (NOT one-shot - need many games, then re-run the report; do NOT flip on one game):
HZ Lane-A laning agreement + HZ Lane-B build-flip gate (`tools/hz_shadow_report.py`,
`tools/replay_build_order_validate.py --limit 0` as `rewind_history.db` grows - both HOLD
until the rail clears); the ~88 `st-*` live-producer census; the champ-select brief Haiku-flip
shadow accrual. These ride along the 3 games but close on a later cycle, not this session.

---

## A. Champ-select (any mode - enter a lobby + lock a champ)

- [FIXED 2026-07-01] LCU push: rune pages + item sets + summoner spells push to the live client on champ-select enter
      (`lcu/lcu_rune_writer.py`; ROADMAP item 215/259/212). Verify the pushed page matches the DS pick.
      ROOT CAUSE (supersedes the 2026-06-17 re-arm theory): the champ-select-exit re-arm was ALREADY fixed
      (6-29 log shows a clean Caitlyn write + re-arm at L595). The recurring silence was `LcuClient` caching a
      STALE lockfile port across a League restart - a long-lived RC read the lockfile only once at connect()
      and never re-read the rotated port/password, so get_champ_select() returned None forever and RuneWriter
      (shares the one _lcu) went silent until an RC restart. PERMANENT FIX (`lcu/lcu_client.py`, frozen-grant):
      mtime-guarded `_refresh_conn_if_changed()` on the 1 Hz auto-accept tick + reactive reconnect-and-retry
      in `_request`, mirroring the RC-LCUAgent `ensure_lcu_conn()` pattern - a League restart now heals within
      ~1s with NO RC restart. Live re-confirm still worth a tick: push fires on the FIRST champ-select AFTER a
      League restart mid-RC-session. See reference_runewriter_dies_after_game1.
- [ ] CS2 summoner-spell auto-push: client defaults to wrong spells (Flash+Heal/TP random); confirm RC
      pushes the intended set via `/lol-champ-select/v1/session/my-selection` (ORCH CS2, commit 29cd2788).
- [ ] Champ-select brief Haiku -> deterministic flip: flip ONLY after shadow-log accrues on real
      champ-selects (`dashboard/_champ_select.py`; ROADMAP "champ-select brief flip", EXCLUDED until now).
- [ ] CC-conditional pairing UI renders on champ-select (ORCH CS1, commit 541cd9d3) - visual confirm.
- [ ] Arena 6x3 champ-select visual capture (3 ally + central me+2 + 5 enemy trio cards; ROADMAP #89).

## B. In-game SR (ranked or normal SR)

- [ ] Build-chooser pushes correct runes/items/spells mid-game to LCU (3-variant + Experimental row).
- [ ] DS Phase-D default-ON flag flips re-rank validation (each needs a real game, "saner not different"):
      `apply_passive_damage`, the 4 non-every-AA `on_hit`, per-stack `assumed_stacks` (ROADMAP DS Phase-D).
- [ ] DSV seam flips (default-OFF today): `assume_takedown` (DSV2), `assume_squishy_target` (DSV3),
      `assume_ability_amp` (DSV4) -> turn ON in the BURST / assassin scorer
      `agents/daemon_slayer/burst.py rank_items_by_burst(assume_takedown=/assume_squishy_target=/assume_ability_amp=True)`
      (assume_takedown + assume_ability_amp also gate `compute_burst_damage`); NOT `rank.py` - the dps/carry
      ranker `rank.py rank_items` carries only the DSP2/DSP11 seams. Confirm the re-ranked build is saner.
- [ ] Anti-tank P3.2 live caster-stat producer + survivability-scorer validation. (1) PRODUCER SHIPPED
      2026-06-17 (`antitank.compute_antitank_live`): it resolves the champion's AP/AD from its live build
      via `engine.build_champion` and feeds them to `compute_antitank(stats=)` so the P3.2 (item 315)
      `ap_ratio`/`ad_ratio` rows scale (Gwen P/KogMaw W/Varus W/Malzahar R AP; Vi W/Camille W/Udyr Q AD).
      Remaining live work: wire a survivability/draft surface to call `compute_antitank_live` with the live
      build + confirm the scaled %max-HP magnitudes match a real game (the /anti-tank route still calls the
      static `compute_antitank`, byte-identical). (2) The ehp ally-resist producer is now covered by DSP7's
      `dsp_live_consumers.ally_protected_ehp` (folds Orianna E / Braum W / Taric W via `ally_resist_grant`
      -> `external_resist_armor/mr`); the Anivia/Zac egg-resist (`apply_egg_resist`) is already default-ON
      (item 321). This is a LIVE-INPUT wire + an eyeball check, NOT a seam-flag flip. No DS `:8893` restart.
- [ ] DSP2 off-class WIN-exemption flip (default-OFF today): `rank.rank_items(exempt_offclass_by_win=True)`
      -> un-strips the items the caster-marksmen genuinely build (Ezreal/Corki/Smolder Trinity Force +
      Spear of Shojin, Senna Black Cleaver; `agents/daemon_slayer/marksman_offclass_exempt.json`). Flip ON
      where the live carry/dps scorer calls `rank_items` for a ranged marksman, then eyeball that Ezreal's
      build surfaces Trinity Force / Manamune and crit ADCs (Caitlyn/Jinx) are unchanged.
- [ ] DSP4 self-rune completion flip (default-OFF today, ENGINE 1.130.0): score Shield Bash 8401's
      proc by passing `compute_burst_damage(..., score_completion_runes=True)` (and
      `compute_combo(..., score_completion_runes=True)`) at the live burst/combo scorer call site that
      supplies a real `runes` set. Adds Shield Bash's 5-30-by-level + 2.5% bonus-HP floor to a shielded
      Resolve carrier's burst. Eyeball that a Shield-Bash tank's burst rises sanely and a non-Shield-Bash
      build is unchanged. Future completion runes join `COMPLETION_RUNE_IDS` and ride the same flag.
- [ ] DSP5 summoner-spell flip (substrate ENGINE 1.131.0): CONSUMER SHIPPED 1.140.0
      (`dsp_live_consumers.summoner_fight_adjustments`). Remaining live work: PLUMB the player's +
      enemy's live summoner set INTO it + eyeball. It adjusts the caster's effective survivability /
      antiheal / CC at the consuming surface (fight_report / matchup / a coach), keyed off the live set:
      Ignite antiheal+true (id 14), Exhaust incoming-DR 0.35 (id 3), Heal/Barrier flat EHP (7/21),
      Cleanse 0.75 cc-discount (id 1), Ghost MS (id 6). Re-anchor the wiki magnitudes to the live
      patch at flip time (DDragon/CDragon zero them). Eyeball the adjusted readout vs a real game.
- [ ] DSP6 enemy-rune threat flip (substrate ENGINE 1.132.0): CONSUMER SHIPPED 1.140.0
      (`dsp_live_consumers.enemy_rune_threat`). Remaining live work: PLUMB the ENEMY's live rune set
      INTO it + eyeball. It is an EHP / target-preset consumer reading the rune set to modulate the
      player's effective survivability
      and the enemy's poke-resist: enemy Press the Attack (id 8005) -> divide the player's EHP by
      1.08 (`enemy_incoming_amp_pct`); enemy Conqueror (id 8010) -> add `enemy_damage_ramp` raw
      bonus enemy damage (and treat its 8%/5% lifesteal as enemy fight-sustain in the target preset);
      enemy Grasp + Second Wind (8437/8444) -> raise the enemy's effective HP vs poke
      (`enemy_poke_sustain_hp`); ANY enemy antiheal source -> discount the player's heal-based EHP by
      `enemy_antiheal_pct(True)` 0.40. Re-anchor magnitudes to the live patch at flip (DDragon
      16.12.1 today). Eyeball that vs a real game the player's anti-tank / sustain build shifts
      sanely when the enemy runs PtA / Conqueror / Grasp, and a no-threat lobby is unchanged.
- [ ] DSP7 ally aura/enchanter flip (substrate ENGINE 1.133.0): CONSUMER SHIPPED 1.140.0
      (`dsp_live_consumers.ally_protected_ehp`, folds flat-HP AND resist grants - also the item-321
      ehp ally-resist producer surface). Remaining live work: PLUMB the live ally team INTO it +
      eyeball. It is a peel/EHP consumer that, for a
      protected ally, sources `_passive_ally_grant_overrides.ally_flat_hp_grant(granter, level, True)`
      from the live ally team's enchanter (Janna E / Lulu E / Karma E / Yuumi E / Seraphine W
      shields, Soraka W / Nami W heals) and feeds it as `external_flat_hp` into the protected ally's
      `compute_ehp`. Re-anchor the base shield/heal values + add the granter's live AP ratio at flip
      (the seam ships the base floor only). Eyeball that an ally beside a Janna/Lulu/Soraka shows a
      sanely higher effective-HP / peel-survivability and a solo ally is unchanged.
- [ ] DSP8 enemy-comp target-preset flip (seam shipped default-OFF, ENGINE 1.134.0): no live scorer
      passes `rank_items_by_burst(..., target_preset=)` yet (it defaults None -> the DSV3
      assume_squishy_target armor-only path or byte-identical). The flip WIRES the burst /
      `/rank-assassin` scorer to pass a `target_preset` ("squishy" / "bruiser" / "tank" / "high_cc")
      derived from the LIVE enemy comp (classify the enemy team's archetypes -> the dominant defensive
      profile of the priority burst target), so the assassin item ranking values lethality vs raw AD
      vs magic-pen against the comp it actually bursts. `_assumed_target_resists` substitutes the
      preset's (armor, MR); re-anchor the four (armor, MR) curves to the live patch's role-norm resists
      + representative defensive items at flip. Eyeball that vs a tank-heavy comp the assassin build
      surfaces more lethality / armor-pen, vs a high-CC enchanter comp more magic pen, and a balanced /
      squishy comp matches the DSV3 squishy baseline. NO live default change is shipped by the loop
      (do-not-flip-blind). Needs a DS `:8893` restart on flip.
- [LIVE-VALIDATED 2026-06-17 - FLIP-READY] DSP11 kit-axis item-credit flip (seam shipped default-OFF, ENGINE 1.135.0): no live scorer
      passes `rank_items(..., prefer_kit_axis_by_win=True)` or `rank_items_by_burst(...,
      prefer_kit_axis_by_win=True)` yet (defaults False -> byte-identical). The flip WIRES the dps
      (carry) + burst (assassin) scorer-dispatch (`core/daemon_slayer_client.rank_for_primary_archetype`
      + the `/rank` + `/rank-assassin` routes) to pass `prefer_kit_axis_by_win=True` so the 7 WIN-anchored
      Cluster-B2 champs (Pyke/Naafiri/Senna lethality, Nilah/Quinn crit, Ezreal/Corki manamune) surface
      their kit-axis winners above the generic AD template. Eyeball in a real ARAM that Pyke surfaces
      Opportunity/Youmuu's, Nilah surfaces IE/Navori/Shieldbow, Ezreal surfaces Trinity/Muramana/ER
      (un-stripped), and a non-tabled champ (Caitlyn) + any operator pick are byte-identical. Re-anchor
      `agents/daemon_slayer/kit_axis_item_credit.json` from a fresh rewind+DSP10 run each patch
      (`ops/audit/ds_perm_swarm/build_kit_axis_item_credit.py`). Needs a DS `:8893` restart on flip.
- [LIVE-VALIDATED 2026-06-18 Yasuo - FLIP-READY] RF1 generic-bruiser-template survivability flip (seam shipped default-OFF, ENGINE 1.136.0): no live
      scorer passes `rank_items_by_hybrid(..., prefer_survivability_by_win=True)` yet (defaults False ->
      byte-identical). The flip WIRES the HYBRID (bruiser) scorer-dispatch (`agents/daemon_slayer/server.py`
      `_route_hybrid` -> the `rank_items_by_hybrid` call ~L729, and/or the `core/daemon_slayer_client.hybrid_for`
      wrapper) to pass `prefer_survivability_by_win=True` so the 9 WIN-anchored bruiser champs (Darius, Yasuo,
      Urgot, JarvanIV, Gnar, Udyr, Tryndamere, RekSai, Briar) float their buried survivability winners (Spirit
      Visage / Jak'Sho / Sterak's Gage / Death's Dance / Force of Nature / Randuin's Omen / Thornmail / Titanic
      Hydra / Fimbulwinter) above the generic AD-DPS template (Void Immolation / BotRK / Trinity / Heartsteel /
      ER / Runaan's). Eyeball in a real ARAM that Darius surfaces Force of Nature/Sterak's, Udyr surfaces
      Jak'Sho/Spirit Visage, and a non-tabled bruiser (Garen) + any operator pick are byte-identical. MasterYi is
      deliberately NOT tabled (his buried winners are pure DPS - a DSP11/within-axis matter). Distinct from the
      DSP11 flip: that floats DPS/burst kit-axis items gated on `delta_dps>0`; survivability items add EHP not
      DPS so RF1 floats by WIN-table membership. Re-anchor `agents/daemon_slayer/survivability_item_credit.json`
      from a fresh rewind+DSP10 run each patch (`ops/audit/ds_perm_swarm/build_survivability_item_credit.py`).
      Needs a DS `:8893` restart on flip.
- [ ] RF2 enchanter-template survivability flip (seam shipped default-OFF, ENGINE 1.137.0): no live
      scorer passes `rank_items_by_hps(..., prefer_survivability_by_win=True)` yet (defaults False ->
      byte-identical). The flip WIRES the HPS/enchanter scorer-dispatch (`agents/daemon_slayer/server.py`
      `_route_rank_enchanter` -> the `rank_items_by_hps` call ~L1571, and/or the
      `core/daemon_slayer_client.rank_enchanter_for` wrapper) to pass `prefer_survivability_by_win=True`
      so the WIN-anchored tank-support champ (Rakan) INJECTS + floats its buried HP/tank winners
      (Guardian's Horn / Warmog's Armor / Heartsteel / Fimbulwinter) above the generic enchanter template
      (Helia / Ardent / Staff / Locket / Knight's Vow / Redemption). UNLIKE the RF1 hybrid flip (float-only -
      the bruiser scorer already pools survivability items), the enchanter `enchanter_only` pool EXCLUDES
      these HP/tank items so the seam must INJECT them into the pool first, then float. Eyeball in a real
      ARAM that Rakan-as-tank-support surfaces Warmog's / Heartsteel and a non-tabled enchanter
      (Soraka / Janna) + any operator pick are byte-identical. Cluster A (Zilean / Seraphine AP-in-ARAM,
      both with AP buried winners on the hps lane) deliberately NOT tabled. Re-anchor
      `agents/daemon_slayer/survivability_item_credit_enchanter.json` from a fresh rewind+DSP10 run each
      patch (`ops/audit/ds_perm_swarm/build_survivability_item_credit_enchanter.py`). Needs a DS `:8893`
      restart on flip.
- [ ] RF3+RF6 tank-template survivability flip (seam shipped default-OFF, ENGINE 1.138.0 float; RF6
      INJECT extended 1.139.0): no live scorer passes `rank_items_by_ehp(..., prefer_survivability_by_win=True)`
      yet (defaults False -> byte-identical). The flip WIRES the EHP/tank scorer-dispatch
      (`agents/daemon_slayer/server.py` the `rank_items_by_ehp` call ~L557, and/or the
      `core/daemon_slayer_client.rank_tank_for` wrapper) to pass `prefer_survivability_by_win=True` so the
      WIN-anchored tank champs surface their buried mid-tier resist/HP winners (KSante: Thornmail / Iceborn
      Gauntlet; Rell: Fimbulwinter) above the max-EHP ordering. The SAME flag does BOTH: KSante's winners
      are ALREADY POOLED so they FLOAT by WIN-table membership (RF3, RF1's shape), while Rell's Fimbulwinter
      3121 is a non-purchasable mana-line transform of Winter's Approach the pool DROPS (`gold.purchasable`
      =False), so RF6 INJECTS it (force-admit past `_is_purchasable` via `_filter_candidates(inject_ids=...)`)
      before the float lifts it - RF2's inject intent, extended to clear the purchasable gate the RF2 hps
      `only_ids` union could not. Eyeball in a real ARAM that KSante surfaces Thornmail / Iceborn AND Rell
      surfaces Fimbulwinter at the front, and a non-tabled tank (Malphite / Ornn) + any operator pick are
      byte-identical. Components (Giant's Belt / Negatron Cloak) + boots (Plated Steelcaps) + Cluster A
      deliberately NOT tabled. Re-anchor `agents/daemon_slayer/survivability_item_credit_tank.json` from
      a fresh rewind+DSP10 run each patch (`ops/audit/ds_perm_swarm/build_survivability_item_credit_tank.py`).
      Needs a DS `:8893` restart on flip.
- [ ] B1 melee-applicability flip (seam shipped default-OFF, ENGINE 1.141.0): no live scorer passes
      `compute_dps(..., apply_melee_aa_gate=True)` / `compute_hybrid(..., apply_melee_aa_gate=True)` yet
      (defaults False -> byte-identical). The flip WIRES the DPS / hybrid scorer-dispatch
      (`agents/daemon_slayer/server.py` the `compute_dps` + `compute_hybrid` call sites, and/or the
      `core/daemon_slayer_client` wrappers) to pass `apply_melee_aa_gate=True` so a MELEE champion
      (attackrange < `dps.MELEE_RANGE_CEILING` = 350) is no longer credited Runaan's Hurricane's two extra
      bolts (a ranged-basic-only on-hit). Evidence: `ops/audit/ds_cross_eval/TIER2_REPORT.md` (B1) - melee
      winners (Briar / XinZhao win on Sundered Sky / Death's Dance, never the mis-credited Runaan's / crit-AS
      template). Eyeball in a real game that a melee bruiser's ranked build drops Runaan's (saner not
      different) AND a ranged carry (Caitlyn / Senna / Xayah) is byte-identical. The B2 kit-agnostic AD-axis
      residual (Ezreal Muramana / TF caster-ADC) is a SEPARATE future slice, NOT this flip. Needs a DS
      `:8893` restart on flip.
- [ ] Live adaptation `st-*` producers: ~88 ADAPTATION rows render "-" in-game (no live producer;
      ROADMAP item 281 gap 1). Confirm which surface live vs stay post-game-only.
- [ ] Inhibitor-callout fires when an inhibitor is down (visual; ROADMAP item 283).
- [PARKED 2026-07-01] ZOI per-champion minimap detection. Native-res grab SHIPPED (`f9ebcd3f`,
      `RC_ZOI_NATIVE_GRAB` default ON -> ~416px vs 208px, `core/minimap_blob_detect.py`) - the resolution
      lever the operator asked for. But per-champion ISOLATION is a CONFIRMED dead-end (validated live over
      ~8 frames incl. a real SR game): color = 95-159 blobs, size = ARAM clusters merge with structures,
      MOTION = 159->73 (minions move AND are team-colored). Every turret/minion/ward is team-colored, so the
      presence detector cannot tell a champion from a minion/structure. Only template-matching the champion
      PORTRAITS (vs minion dots) could isolate them - a major risky CV build, operator-gated. NOTE: "v1
      worked" was a DEV-PREVIEW FIXTURE (`p.positions` has no live producer; Live Client exposes no
      positions), NEVER live-accurate. RECOMMEND shelve per-champion; native-res grab stays as the
      foundation. See LEDGER 711 + memory `project_zoi_minimap_reality`.
- [ ] Vision self-heal `:8889` validated in a real game (relay-first poller; ROADMAP item 275/276).

## C. ARAM / ARAM Mayhem (KIWI)

- [ ] HZ Lane-A laning-agreement read (HZU1 prep): after live ARAM games accrue, run
      `tools/hz_shadow_report.py` laning agreement (now unblocked, item 456) -> measures how often the
      HZ-A precompute trade/all-in/back-off verdict AGREES with the live Haiku laning call over real
      ALIVE laning ticks. Gate the precompute-vs-Haiku live LANING-coach FLIP on a high agreement rate
      (reference_hz_laning_agreement_gate: dead/disabled overlay states WAIT RESPAWN / COACHING DISABLED
      are excluded; alive capture falls back action->immediate via the in-process logger, which needs an
      RC restart - power it by accruing ALIVE ticks). Pairs with the HZ Lane-B build gate below: both
      are the cycle-52 HZ precompute->Haiku flip pair and both HOLD until validated.
- [ ] HZ Lane-B build-order item-level Haiku-flip gate (HZU1; item-level code shipped item 457
      @a30cbba4, re-verified this cycle): the flip is `core.precomputed_build_coach`'s anti_tank vs
      anti_squishy BUILD chip going OFF its Haiku "do I pivot anti-tank" call onto the deterministic
      HZ-B2 lean. Rail = `tools/replay_build_order_validate.py` (win-anchored over rewind SR replays;
      artifact `ops/runtime/build_order_validation.json`). VERDICT TODAY = HOLD: @651 SR matches the
      lean-level followed-vs-not win is a coin flip (+2.3pp, 95%=[-2.3,+6.9], flip_ready=False), and
      mining the 4627 lean-ambiguous rows at ITEM granularity surfaces only 1/51 clean per-item carriers
      - Infinity Edge on anti_squishy (+12.6pp, 95%=[+0.7,+24.4]); Serylda's Grudge +11.3pp just misses
      (lo=-0.9). FLIP only after the gate clears its rail (followed-minus-not 95% lo > 0 at >=300
      rows/arm, OR a broad set of per-item carriers) on a LARGER replay corpus, then eyeball the
      deterministic chip vs a real game. Re-run `replay_build_order_validate.py --limit 0` as
      `data/rewind_history.db` grows; one Infinity-Edge carrier is too thin to flip on. Do NOT flip
      blind (charter 4b). No DS `:8893` restart needed (RC-side coach, no engine math).
- [ ] Build-chooser populates + pushes for ARAM picks; comp-aware row-3 MAYHEM tip renders.
- [ ] ARAM comp-verdict swap/variant/stay surfaces correctly (`core/aram_comp_verdict.py`).
- [ ] DSP3 ARAM archetype-override flip (default-OFF today): `core.archetype_picks.get_archetype_for(
      prefer_aram_win_axis=True)` at the ARAM scorer-dispatch site -> re-bases the kit default to the
      rewind-WIN archetype for the 6 Cluster-A champs (Zilean/Shaco/Shyvana -> mage, Taric -> tank,
      KogMaw/Kayle -> carry; `core/aram_archetype_override.json`). Flip ON where the ARAM coach
      resolves the archetype, then eyeball that Kayle/KogMaw surface on-hit (BotRK/Wit's End), Zilean/
      Shaco/Shyvana surface AP, Taric surfaces tank, and a non-Cluster-A champ + any operator pick are
      unchanged. NO DS :8893 restart needed (RC-side resolver, no engine math change).

## D. Arena / Cherry (queue 1750)

- [ ] Augment recommender OCR -> rank vs the pick made (live Mayhem/Arena augment-select; ROADMAP medium).
- [ ] set_augment_intent 4-PATCH endpoint discovery: run the chain at a real Arena augment phase, log which
      of the 4 endpoints the live LCU exposes (`tools/gamepc_lcu_agent.py:1179`; ROADMAP item 187/188).
- [DONE 2026-06-18 PM7, ENGINE 1.144.0 - headless, NOT live-gated] Arena boots 22xxxx mirror SHIPPED
      (item 499, `c258c4ab`). `core.build_order._select_boots` now remaps the resolved tier-2 boot
      to its `22`-prefixed map30-legal Arena mirror (`_BOOTS_ARENA_MIRROR`) on Arena/CHERRY; the bare
      3xxx tier-2 boots were map30=False (illegal on map 30). All 3 Arena build tables regenerated
      (flat 510 + HZ-B1 684 + HZ-B2 342 boots swaps, 0 other changes); SR/ARAM byte-identical. This was
      a DATA-correctness fix, not a re-rank flip - it needed NO live game (ground-truthed vs items.json
      maps.30). The only OWED live piece = an Arena augment-phase VISUAL confirm that the pushed boot
      renders (icon may 404 per [[reference_items_index_alias_ids]], display name is correct).

## E. Electron overlay (rc-shell, in a real match)

- [x] In-game transparent overlay CAPTURE - DONE 2026-06-23 (item 598). Live SR game (Syndra AP
      mage vs a Braum/Gragas tank+CC comp); the rc-shell Electron overlay (PID 9736) ran over League.
      Playwright on the LIVE `https://legion-rc:8888/?overlay=1` read the real coach state + a Legion
      desktop screenshot showed the overlay compositing transparently over the game (see the live-flip
      ledger entry below for the exact DOM reads). The capture validated render + compositing.
- [ ] STILL OWED (operator-PHYSICAL only - NOT a headless build): the ACTIVE knob-interaction
      round-trip. R26 (2026-06-23) ground-truth correction: Alt+Shift+A (`rc-shell/src/main.js:1058`)
      is the click-through ACTIVE *toggle* (`overlayClickThrough` flip + 20s auto-revert), NOT a data
      "re-rank" - the old "re-rank live" name is a misnomer. A non-hotkey twin already EXISTS and is
      unit-tested (IPC `rc-shell:overlay-action {action:"set-active"}` -> `setOverlayActive()`,
      `rc-shell/test/overlay_settings_ipc.test.js`) but is UNREACHABLE headless: rc-shell launches via
      plain `electron .` (no `--remote-debugging-port`) and the `window.rcShell` bridge is
      preload-injected, so it is absent in any :8888 browser/Playwright session. The round-trip
      therefore needs a PHYSICAL Alt+Shift+A press over League (synthesized presses leak into the game;
      [[reference_overlay_live_verify_technique]]). Do NOT re-attempt headless. Shell relaunch picks up
      slices 1-4 (ROADMAP item 214; phases 1-5 code DONE).
- [ ] Operator packaging: `npx electron-builder` + first GitHub Release + packaged update check (private repo GH_TOKEN).

## F. Post-game (any completed match)

- [ ] PGR visual capture S3/S4/S5 + @N timeline metrics (gold@10/cs@10 need per-participant frames;
      ROADMAP item 275/276/277).
- [ ] Replay/Session/History live ingest freshness after a real game end (90s Match-V5 writer; ORCH REPLAY1).

---

## Live-flip ledger (loop appends; newest first)

- 2026-07-01 (R50, LOOP) K'Sante P "All Out Bonus" bilinear caster-resist seam - ENGINE 1.161.0 -> 1.162.0,
  DEFAULT-OFF, live default-ON flip EXCLUDED. New registry `_ALL_OUT_BONUS_OVERRIDES` + new
  `AbilitiesSnapshot.load(apply_all_out_bonus=...)` flag inject a SECOND K'Sante-P synthetic damage block modeling
  the R-empowered All Out Bonus (verbatim 16.13.1: "1% (+ 1% per 100 bonus armor) (+ 1% per 100 bonus magic
  resistance) of the target's maximum health") as a linear 1% max-HP plus two `_per_100` bilinear terms
  (`caster_bonus_armor` x `target_max_hp` + the `caster_bonus_mr` sibling), gated by `conditional_probability` 0.5
  (documented amortized All-Out-uptime firing midpoint, operator-tunable). Default OFF is byte-identical (no live
  consumer passes the flag; the base item-255 mark-consume entry is untouched). OWED (operator/Gemini-gated, NOT
  headless - charter 4b do-not-flip-blind): (1) wire a live rank / dps / burst consumer to pass
  `apply_all_out_bonus=True` (ideally only while K'Sante's R "All Out" is active) and confirm his in-All-Out
  empowered-mark value reads sane vs a real game; (2) tune `conditional_probability` 0.5 against real All-Out uptime
  (or feed a live All-Out-state gate so the full in-form value is credited only during R). A WRONG precompute is
  worse than none, so do NOT default-ON until validated in an actual All Out fight. DS `:8893` restart on flip.
  Does NOT block any further stage.

- 2026-07-01 RuneWriter silent-after-League-restart PERMANENT FIX (`lcu/lcu_client.py`, frozen-grant).
  Operator live-flagged rune push dead on the last champ-select. Root cause: the long-lived RC (up since
  6-29) held a STALE lockfile port after League restarted (the lockfile rotates port+password each launch);
  `LcuClient` read the lockfile only once at connect() and never re-read, so get_champ_select() returned None
  forever and RuneWriter (shares the one _lcu) went silent - NOT the 2026-06-17 re-arm theory (that path was
  already fixed; the 6-29 log shows a clean Caitlyn write + re-arm). Immediate remediation: RC restart re-read
  the lockfile (fresh port 50237). PERMANENT: ported the RC-LCUAgent `ensure_lcu_conn()` resilience into
  `LcuClient` - mtime-guarded `_refresh_conn_if_changed()` on the 1 Hz auto-accept tick (heals every consumer
  sharing the instance) + reactive reconnect-and-retry-once in `_request` on a dead-port connection error.
  TDD: 6 new tests (`tests/test_lcu_client_lockfile_reconnect.py`) - rotate / no-op / gone + dead-port retry +
  no-infinite-retry + tick-calls-refresh; the 114 prior LCU/RuneWriter/spell/loadout tests stay green. Tier-1
  (LCU client logic; no ENGINE bump / Share sync / DS restart). Activation needs an RC restart to load the
  edited frozen module - DEFERRED past the operator's live ARAM (do not bounce RC mid-game).

- 2026-06-23 (item 598, R25) IN-GAME OVERLAY CAPTURE - E.1 cleared (validation + 1 durable test,
  NO live flip). Live SR game (champ Syndra AP mage vs a Braum/Gragas tank+CC comp); the rc-shell
  Electron overlay (PID 9736, title "RC . Syndra") ran over League. Playwright on the LIVE
  `https://legion-rc:8888/?overlay=1` (not a fixture, not 127.0.0.1 - the legion-rc origin so wss://
  is real), read off the REAL coach state: `body[data-shell]="overlay"`; `#right-now` `s0Cue="choices"`
  `s0Tier="urgent"` `s0Pulse="0"` (a SUSTAINED one-shot-urgent CHOICES cue did NOT arm a pulse ->
  producer-side motion rationing verified live, no over-fire); the CALL action row
  `data-call-band="fight"`, border-left-color rgb(200,170,110) gold 3px, verb color rgb(236,242,255)
  white, glyph U+25BA (item 591 band channel, live-faithful); eye-line widgets rn-lead / rn-choices
  (showed "A / Trade now / Braum lvl 18 / Alt+1") / rn-callouts (WARD UP green pill) / am-ward-cue /
  am-mmrect present+positioned, am-spike-cue + am-pane-ovds fight-model correctly hidden in the coach
  panelset, primary CALL font-size 22px. Only console error: favicon.ico 404 (benign). A Legion desktop
  screenshot caught the REAL Electron overlay compositing transparently over the live Rift (CALL
  "SETUP DRAKE FIGHT" gold bar + WARD UP + minimap-rect box float over the game with no opaque backing).
  DURABLE: new `tests/snapshot_panels/test_overlay_view.py::test_overlay_s0_pulse_rations_sustained_choices_via_producer`
  pins the DOM-PRODUCER s0-pulse path (the node PulseDecisionChainTests never import right_now.js; the
  manual-stamp consumer tests set the attribute by hand - neither exercised the live producer render).
  Screenshot is local-only (`tests/snapshot_panels/screenshots/` gitignored), NOT committed. STILL OWED:
  the ACTIVE knob-interaction (Alt+Shift+A re-rank) round-trip - the capture validated render+compositing,
  not a live knob press.

- 2026-06-23 RC_COMP_HP_LEAN (DSV5) LIVE EYEBALL DONE (R24; validation only, NO code change).
  The OWED AP-mage-vs-2+-tank eyeball (ledger 592) cleared on a real live SR game: me=Seraphine
  vs enemy Braum / Master Yi / Cho'Gath / Ziggs / Gragas. `compute_enemy_stats` classified
  `tanky_count=3` (Braum + Cho'Gath = tank, Master Yi = bruiser) -> `hp_scale` **1.20x**, applied
  `target_max_hp` 2980 -> 3576 (+596) at L18. RANKER OFF-vs-ON (`dispatch_for_coach`, top-6):
  (a) Seraphine routes to the **HPS / enchanter** scorer, so the seam is a NO-OP for her
  (enchanters do not build %max-HP DoT) - the LIVE coach champ was unaffected; (b) pure mages
  (Veigar / Heimerdinger, the ability-DPS scorer) - the seam boosts ONLY the genuine %max-HP DoT
  item **Liandry's Torment** (+6.5 dps L18 / +5.4 dps L11, ~+17%, proportional to the 1.20x
  max-HP) and leaves flat-magic items (Void Staff / Rabadon's / Shadowflame / Mejai's / Blackfire)
  byte-identical. VERDICT: **SANER NOT DIFFERENT confirmed** - the seam can only nudge Liandry's
  UP, never reorder toward a worse pick, so do-not-flip-blind (charter 4b) is SATISFIED. CAVEAT:
  the visible top-6 IMPACT is narrow - Liandry's is already rank-1 in the mage build at these
  levels, so the 1.20x widens an existing lead WITHOUT reordering the top-6; the seam only changes
  a served ranking in the borderline case where Liandry's is NOT already top, AND only for
  mage-scorer champs (enchanters / non-AP unaffected). RECOMMENDATION: flip is validated-SAFE, ON
  recommended - but NOT auto-flipped this session because the supervisor-env route is a FROZEN-file
  edit (`ops/rc_supervisor.py`) and defaulting a global coaching heuristic ON is a deliberate
  operator call. Method: probed the live `/api/state` comp + ran `compute_enemy_stats` /
  `dispatch_for_coach` OFF (`comp_hp_lean=False`) vs ON (`=True`) headlessly - no live-process
  disruption, no env change.

- 2026-06-22 DSV5 no-comp-info guard (ledger 593, `coach_integration/enemy_stats.py`) - a
  PREREQUISITE-to-flip SAFETY FIX, not a new seam. Verify-the-premise against the live SR comp
  (Jinx vs Lucian/Sion/Wukong/Pantheon/Soraka, tanky_count 3) exposed that `_comp_hp_scale`
  applied a blind **0.90** max_hp discount whenever `RC_COMP_HP_LEAN` was ON with NO
  `enemy_champions` (`1 + 0.10*(0 - 1)`), conflating "no comp data" with "all-squishy comp" and
  contradicting its own docstring. The champ-select / preview routes (`routes_state` ds-preview
  Path 3, `routes_ds_knobs`, `routes_ds_relscore`, `routes_ds_statcheck`) ALL call
  `compute_enemy_stats(mode, level)` with no comp, so a global default-ON flip would have silently
  de-rated every preview ranking by 10%. FIX: `_comp_hp_scale` now short-circuits to `(1.0, 0)`
  when there is no classifiable comp (None / `[]` / all-blank), so no-info is byte-identical to the
  flat curve when ON; a REAL all-squishy comp (>=1 classifiable champ, 0 tanky) still earns the
  intended 0.90 discount, and a tank comp still earns the uplift. This RESOLVES the preview-route
  safety blocker on the RC_COMP_HP_LEAN default-ON flip below. Tier-1 (NO ENGINE bump / Share sync /
  DS :8893 restart - coach-integration heuristic). RED-first +4 tests (the bug-shaped
  `test_no_comp_info_on_is_neutral` assertion corrected to 1.0 to match its own name + the docstring,
  plus blank-comp, no-info-vs-known-squishy contrast, and an env-ON-no-comp byte-identical guard);
  43/43 enemy-stats tests green. The default-ON FLIP itself stays operator-gated (gemini ruling:
  hold for a separate operator-run) - see the DSV5 entry below.

- 2026-06-22 DSV5 comp-conditioned enemy max-HP seam (ledger 592, `coach_integration/enemy_stats.py`).
  DEFAULT-OFF env gate **`RC_COMP_HP_LEAN`** (set `=1` in the RC runtime env; the read is per-call so no
  restart is needed - it is a coach-integration heuristic, NOT a DS `:8893` engine flip, so do NOT restart
  DS for it). When ON, a tank-heavy enemy comp scales `target_max_hp` up (1 + 0.10*(tanky_count - 1),
  clamped [0.85, 1.30]) so DSV1's ability-burn / %max-HP valuation tilts the live item ranking toward DoT
  (Liandry's/Blackfire/Demonic) vs tanks, matching the rewind WIN-anchored signal (winning AP carries vs
  2+ tanks build DoT over burst +12.0pt; burst usage halves). OFF == byte-identical flat curve.
  LIVE EYEBALL DONE 2026-06-23 (R24 - see ledger top; do NOT flip blind, charter 4b): in a real SR/ARAM game on an AP mage facing a 2+
  tank/bruiser comp, set `RC_COMP_HP_LEAN=1` and confirm the build-chooser top-6 re-rank elevates the
  %max-HP DoT items (Liandry's especially) vs the OFF ranking, and that it stays "saner not different"
  for a squishy comp (scale 0.90 should NOT swing picks materially). Inspect the applied modifier via the
  `core.coach_trace.record_enemy_target` plumb (`kind:enemy_target` records: base vs applied max_hp +
  hp_scale + tanky_count). Only after the eyeball checks out, authorize the default-ON flip (drop the gate
  or default `RC_COMP_HP_LEAN=1` in the supervisor env). NO ENGINE_VERSION bump / Share sync (engine
  untouched - the seam only changes the TARGET fed to the already-shipped DSV1 scorer).

- 2026-06-20 RC2 rc-shell standalone-app live session (code fixes shipped `cac1df3a` + `81f74d88`;
  runtime recovery). LIVE-VERIFY OWED (needs a live ARAM/any lobby): `lcu.lobby.members[]` must render
  in the rc-shell PRE-GAME LOBBY panel (YOUR MAINS / PARTY / MY TOP-8). The agent DOES forward members[]
  (`tools/lcu_agent.py:706-717`) but the operator saw empty members during a live lobby; could NOT
  reproduce after they left it (LCU phase=None). Next lobby: confirm the panels populate; if empty,
  capture the agent's live `/lol-lobby/v2/lobby` read + `_slim_lobby_member` output to find why members
  drop (suspect event-mode 2400 member shape OR the post-RC-restart stale-agent window). ALSO eyeball
  the overlay surface gate (`cac1df3a`): companion dashboard shows in the lobby/champ-select and flips to
  the lean HUD only once `liveclient` populates (a real game starts). Separately tracked (NOT live-gated,
  headless next session): agent restart-resilience - RC-LCUAgent/Hotkey/Relay must survive boot + auto-
  resync after an RC restart (the systemic root cause of the whole session's cascade). NOT a DS seam.

- 2026-06-20 RC2 E-batch E12-L2 + E7a (RC-side, NOT DS seams; shipped code-safe, no flip flag).
  E7a (`64591d5f`) tightens the RC-LCUAgent bench-swap queue-drain (fast 0.1s re-poll on a
  latency-sensitive cmd vs the 0.5s idle wait). LIVE EYEBALL OWED: in a real ARAM champ-select,
  click a bench champ and confirm the swap registers visibly faster - cannot be exercised offline
  (needs a live LCU champ-select with a populated bench). The RC-LCUAgent runs as an ONLOGON task
  with no restart_trigger, so a code refresh needs `taskkill /F` the agent pid + `Start-ScheduledTask
  RC-LCUAgent`. E12-L2 (`48fcee51`) memoizes RuneWriter's lobby gameMode per champ-select session.
  LIVE EYEBALL OWED: confirm RuneWriter still pushes the correct mode-appropriate runes/spells on
  champ-select enter (cache is per-session, cleared on `_reset_spell_state`) and a mode change across
  back-to-back champ-selects re-detects. Neither blocks any further stage.

- 2026-06-20 RC2 P5.2 CV served integration (COACHING, NOT a DS seam; shipped code-safe
  DEFAULT-OFF). 5.1 built the CV override + shadow column; 5.2 builds the SERVED-FLIP
  MECHANISM: `core.laning_cv_overrides.apply_cv_to_choices` maps a fired override onto the
  served A/B chips (`cv_choice_pair`: enemy DEAD -> "Shove + take plates/prio" high;
  MISSING >=3s -> "Back off + ward" mid; my HP <0.35 vs an aggressive verdict -> "Disengage"
  high; source_tag `cv-laning`; a trailing build `C` choice is preserved). Wired through
  `core.laning_verdicts.laning_choices(apply_cv=, hp_fraction=, vision_state=)` (default
  apply_cv=False -> byte-identical) and gated in `dashboard/_deterministic_coaching._compute_uncached`
  behind `_cv_served_enabled()` (env `RC_LANING_CV_SERVED`, DEFAULT-OFF). `_build_game_state`
  now stamps `gs["hp_fraction"]` (lc-first; additive, only the gated path reads it). OFF is
  byte-identical (the `laning_choices(gs, mode=upper)` call is unchanged). THE SERVED FLIP =
  `RC_LANING_CV_SERVED=1` in the RC runtime env (no restart for the env read on next RC
  start; the producer runs in-process). OWED (operator/Gemini-gated, NOT headless): (a) accrue
  real laning games so `data/hz_choice_shadow.jsonl` `cv_override` rows fill (5.1's shadow);
  (b) re-run `tools/hz_shadow_report.py` and read det-vs-Haiku agreement WITH the CV layer;
  (c) when agreement climbs toward the >=70% target (`HZ_HAIKU_CALL_INVENTORY.md:75`), set
  `RC_LANING_CV_SERVED=1` to flip the served chips. KNOWN at flip time: the served `_CACHE`
  sig (`_cache_sig`) is intentionally UNCHANGED (off-path byte-identical), so a flipped-ON CV
  transition (enemy dies / my HP drops mid-bucket) can serve a stale chip for up to the 3.0s
  TTL + 5s game-time bucket - acceptable for a gated/eyeballed flip; tighten the sig (coarse
  low-HP bool + a cheap fog-freshness key) in the same flip slice if the live eyeball shows lag.
  Does NOT block any further stage.

- 2026-06-19 R7 per-stack self-AS passive (ENGINE 1.147.0): the per-stack champion self-Attack-Speed
  passive seam shipped DEFAULT-OFF on the AA DPS scorer. NEW `agents/daemon_slayer/_passive_as_overrides.py`
  registry (`PassiveAsEntry` per champion_id: per-stack bonus-AS FRACTION low/high by level + max_stacks +
  ap_per_stack_per_100) + `assume_passive_as_stacks` on `agents/daemon_slayer/dps.py compute_dps`; when ON,
  `passive_as_bonus(cid, level, ap, stack_fraction=_ASSUMED_PASSIVE_AS_STACK_FRACTION=1.0)` folds the
  champ's innate per-stack bonus AS at full stacks into the rotation AS (same 2.5 hard-cap re-clamp as the
  Yun Tal conditional-AS path; raw_attack_dps left at the no-conditional baseline). Seeded 4 from
  champion_abilities.json 16.12.1 effects_descriptions: Irelia Ionian Fervor (10%:25% by level/stack, max 4),
  Jax Relentless Assault (5%:12.5% by level/stack, max 8), Ezreal Rising Spell Force (10% flat/stack, max 5),
  Volibear The Relentless Storm ((5% + 4% per 100 AP)/stack, max 5 - the one AP-scaled passive, reads the
  resolved post-amp AP). A champion with no registered passive is byte-identical even with the flag on. No
  live scorer passes the flag yet (default False -> byte-identical). LIVE FLIP = wire the DPS / hybrid
  scorer-dispatch (`agents/daemon_slayer/server.py` the `compute_dps` call sites + `rank.py rank_items` /
  `core/daemon_slayer_client` wrappers - the same dispatch the B1 melee gate flips) to pass
  `assume_passive_as_stacks=True` for the 4 tabled champs (extend `core/archetype_picks` or the scorer call
  to thread the flag). Validate in a real game that Irelia/Jax/Ezreal/Volibear show a sanely higher
  auto-attack DPS / item ranking that favors AS-synergy items at full stacks, and a non-tabled champ
  (Caitlyn) + any operator pick are byte-identical. The assumed stack count
  (`_ASSUMED_PASSIVE_AS_STACK_FRACTION`) is operator-tunable; dial it below 1.0 if full-stack steady state
  over-credits a poke kit (Ezreal). Re-anchor the registry from the live patch's `champion_abilities.json`
  effects_descriptions each patch (re-scan for new per-stack self-AS passive lines). Needs a DS `:8893`
  restart on flip. Do NOT flip blind (charter 4b; CLAUDE-Settled "per-stack assumed_stacks").
- 2026-06-19 R5 missing-HP heal-amp (ENGINE 1.146.0): the missing-HP heal-AMPLIFICATION seam shipped
  DEFAULT-OFF on the ability-HPS scorer. NEW `assume_missing_hp_heal_amp` on
  `agents/daemon_slayer/ability_hps.py compute_ability_hps`; when ON, a `(champ, spell)` in
  `_MISSING_HP_HEAL_AMP` has its `heal_per_cast` multiplied by `1 + max_bonus * caster_missing_hp_pct`
  (Master Yi W Meditate / Lissandra R Frozen Tomb / Sylas W Kingslayer = 1.0; Briar P Crimson Curse =
  0.40). No live scorer passes the flag yet (default False -> byte-identical; full-HP / 0-missing also
  byte-identical). LIVE FLIP = wire the HPS/enchanter scorer-dispatch
  (`agents/daemon_slayer/server.py _route_rank_enchanter` -> `rank_items_by_hps`, and/or any coach
  surface calling `compute_ability_hps`) to pass `assume_missing_hp_heal_amp=True` AND feed the live
  caster's missing-HP fraction as `caster_missing_hp_pct`. Validate in a real game that a low-HP
  Sylas/Master Yi/Lissandra/Briar shows a sanely higher ability-heal throughput and a full-HP cast +
  any non-tabled champ are byte-identical. Re-anchor `_MISSING_HP_HEAL_AMP` from the live patch's
  `champion_abilities.json` effects_descriptions each patch (re-scan for new 0%:X%-based-on-missing-
  health heal lines). Needs a DS `:8893` restart on flip. Do NOT flip blind (charter 4b).
- 2026-06-18 PM7 Arena boots mirror (ENGINE 1.144.0): NOT a default-OFF seam - a DATA-correctness
  fix shipped LIVE (item 499). `core.build_order._select_boots` remaps Arena/CHERRY tier-2 boots to
  their `22`-prefixed map30-legal mirror; all 3 Arena build tables regenerated (boots-only). No flip
  pending (already live); the only live-OWED piece is the section-D visual confirm at an Arena augment
  phase. ALSO logged here: an operator ARAM Yasuo this run produced the first live RF1-tabled-bruiser
  eyeball - RF1 ON (hybrid `prefer_survivability_by_win`) floats Wit's End + Jak'Sho into Yasuo's top-6
  and drops Runaan's + Stormrazor = SANER, clearing the LGS2-open "RF1 needs a tabled champ to roll"
  gap. The RF1 default-ON flip itself stays operator-gated (section B; not flipped mid-game). NEW `cost_ceiling` param
  on the shared `_filter_candidates`, threaded through `rank_items`/`rank_items_by_ehp`/
  `rank_items_by_hybrid`; drops any candidate whose `gold.total` STRICTLY exceeds the ceiling. Live
  flip = pass `cost_ceiling=<N>` (e.g. 4000) at the build-chooser /rank-bruiser + /rank-tank call
  sites (section B), excluding the 6000g ARAM/Arena mega-item Void Immolation 223069 the
  `sort_by="delta"` absolute-gain surface floats to rank-1. Byte-identical OFF (reproduced live:
  Garen bruiser ARAM rank-1 = 223069). Validate the re-ranked ARAM/Arena bruiser+tank top-6 vs a
  real game before flipping (do-not-flip-blind).
- 2026-06-18 B1 (ENGINE 1.141.0): melee-applicability gate shipped DEFAULT-OFF (item 496, PM4). Live
  flip = `apply_melee_aa_gate=True` on the dps/hybrid scorer call sites (section B), zeroing a
  `PeriodicProc.ranged_only` proc (Runaan's Hurricane bolts) on a melee auto (attackrange <
  `MELEE_RANGE_CEILING`=350). Validate the re-rank vs a real melee ARAM game (Briar/XinZhao/Nilah)
  before flipping.
- 2026-06-17 LGS2 LIVE PLAY (no ENGINE bump - validation session, zero code change): operator ran
  6 ARAM Mayhem champ-selects (Olaf, Sivir, Senna->Mundo, Lissandra, Vex->Quinn, Caitlyn) under a
  persistent champ-select catcher (poll lcu.phase, emit on ChampSelect-enter; ARAM CS is too fast
  for a from-ReadyCheck poll) + per-champ `live_flip_eyeball.py` OFF-vs-ON re-rank.
  RESULTS:
  * DSP11 kit-axis = LIVE-VALIDATED both sub-cases + negative control -> FLIP-READY pending operator
    decision + DS :8893 restart. Senna (lethality) ON surfaces +Black Cleaver; Quinn (crit) ON
    surfaces +Infinity Edge(top)/The Collector/Statikk Shiv/Lord Dominik's; Caitlyn (the documented
    non-tabled control) shows ZERO DSP11 movement (byte-identical). Seam correctly scoped.
  * Comp-verdict (section C) renders correctly on SWAP (Senna->Lux HIGH, Lissandra->Hecarim MEDIUM,
    Vex->Garen MEDIUM) AND STAY (Caitlyn STAY LOW). VARIANT branch still unobserved. Bench-swap UI +
    build-chooser (3 variants + runes) + MAYHEM flag all render live; build reasons are comp-aware.
  * DSP3 / RF1 / RF2 / RF3+RF6 = no-op on every champ played (none tabled for those seams) ->
    byte-identical half re-confirmed; the TABLED half for RF1/RF2/RF3+RF6/DSP3 + the DSP11-manamune
    sub-case still needs a tabled champ to roll (RF1 bruiser / Rakan / KSante|Rell / Cluster-A /
    Ezreal|Corki).
  * DSP8/DSV3/DSV4 move saner per champ (theoretical - burst path, not the live ranker for most picks).
  OPEN FINDINGS:
  * SECTION A LCU PUSH = FAIL. RuneWriter (`lcu/lcu_rune_writer.py`) wrote runes ONLY on the first
    champ-select of the RC session (game1 Yuumi->Olaf 21:56); SILENT on every later champ-select
    despite RC detecting them (cs_pick updated). No crash/traceback -> champ-select re-detection does
    not re-arm after the first "champ select ended" (L451). Item-set + summoner-spell push share the
    CS-enter path = same suspect. Fix is post-session (needs RC restart), NOT frozen. See memory
    reference_runewriter_dies_after_game1.
  * Comp-verdict SOUNDNESS flag (low-confidence): Vex(AP)->Garen(AD) cited "all-AD comp - mix damage
    type", which reads inverted (swapping the only AP to AD removes the mix). Verify the ally-comp
    logic in `core/aram_comp_verdict.py`.
  CS2 spell push inconclusive (summoner_override=False every game; client default was already
  Flash+Mark, nothing to force). CC-pair UI not observed (no CC-pairing scenario rolled). HZ Lane-A/B
  accrued ~6 ARAM games to rewind_history.db (still HOLD - need corpus + rail clear).

- 2026-06-17 DSP5/6/7 CONSUMERS (ENGINE 1.140.0): the three DSP substrate seams now have a
  consumer layer - NEW `agents/daemon_slayer/dsp_live_consumers.py` (`summoner_fight_adjustments`
  / `enemy_rune_threat` / `ally_protected_ehp`). Previously a flag-flip did nothing (no scorer read
  the registries); now the seams are LIVE-TESTABLE - the remaining gated work is PLUMBING the real
  live-client summoner/rune/ally set INTO the consumer + eyeballing the adjusted readout (NOT
  building a consumer). Each is byte-identical on an EMPTY context. DSP7's `ally_protected_ehp` ALSO
  covers the item-321 ehp ally-resist producer (Orianna E / Braum W / Taric W via `ally_resist_grant`
  -> `external_resist_armor/mr`). +10 tests; DS 7334 / RC 8333 green; Share 364; DS :8893 restarted
  -> 1.140.0. NOT flipped (do-not-flip-blind).

- 2026-06-17 RF6 (ENGINE 1.139.0): tank-template survivability INJECT seam shipped DEFAULT-OFF -
  extends the RF3 ehp/tank float (no NEW scorer flag; the SAME `prefer_survivability_by_win` on
  `ehp.rank_items_by_ehp`). RF4 found RF3's float is a no-op for Rell: its sole tabled winner
  Fimbulwinter 3121 is the non-purchasable mana-line transform of Winter's Approach
  (`gold.purchasable`=False), so `_filter_candidates` drops it (RF4 `in_pool=False`) and the float has
  nothing to lift. NEW `inject_ids` force-admit param on `rank._filter_candidates` (bypasses the
  `only_ids` whitelist + `exclude_names` deny + `_is_purchasable` gate; still honors current /
  non-coachable / mode-legality / terminal / budget; `None` default = byte-identical for every caller);
  `rank_items_by_ehp` passes `inject_ids=surv_ids` only when the seam is ON. The LIVE flip is the SAME
  one tracked in section B above (wire `server.py` `rank_items_by_ehp` ~L557 / `rank_tank_for` to pass
  `prefer_survivability_by_win=True`) - flipping it now ALSO surfaces Rell's Fimbulwinter, not just
  KSante's already-pooled winners. NOT flipped (do-not-flip-blind); needs a real ARAM + a DS `:8893`
  restart. KNOWN SIBLING (FUTURE): RF2's hps `only_ids |= surv_ids` union likewise cannot surface
  Rakan's tabled 3121 (same purchasable gate) - the `inject_ids` mechanism now exists to fix it if a
  future RF wires the hps lane through it; not done here (RF2 is a DONE seam).
- 2026-06-17 RF2 (ENGINE 1.137.0): enchanter-template survivability item-credit seam shipped
  DEFAULT-OFF. NEW `prefer_survivability_by_win` on `hps.rank_items_by_hps` (the hps/enchanter scorer
  lane), driven by the WIN-anchored `agents/daemon_slayer/survivability_item_credit_enchanter.json`
  (1 champ / 4 items - Rakan: Guardian's Horn / Warmog's Armor / Heartsteel / Fimbulwinter). The flip
  wires `agents/daemon_slayer/server.py _route_rank_enchanter` (+/- the
  `core/daemon_slayer_client.rank_enchanter_for` wrapper) to pass `prefer_survivability_by_win=True`.
  KEY difference from RF1: the enchanter scorer's `enchanter_only` pool EXCLUDES HP/tank items entirely
  (zero HPS throughput) so the seam INJECTS the tabled ids into the pool BEFORE floating them (RF1's
  hybrid lane already pools them and only floats). NOT flipped (do-not-flip-blind) - validate the
  re-rank in a real ARAM (Rakan-as-tank-support surfaces Warmog's/Heartsteel; non-tabled Soraka/Janna
  byte-identical). Cluster A (Zilean/Seraphine AP-in-ARAM) NOT tabled. Re-anchor the table each patch
  via `ops/audit/ds_perm_swarm/build_survivability_item_credit_enchanter.py`. Needs a DS `:8893`
  restart on flip.
- 2026-06-17 RF1 (ENGINE 1.136.0): generic-bruiser-template survivability item-credit seam shipped
  DEFAULT-OFF. NEW `prefer_survivability_by_win` on `hybrid.rank_items_by_hybrid` (the hybrid/bruiser
  scorer lane), driven by the WIN-anchored `agents/daemon_slayer/survivability_item_credit.json` (9 bruiser
  champs / 28 items). The flip wires `agents/daemon_slayer/server.py _route_hybrid` (+/- the
  `core/daemon_slayer_client.hybrid_for` wrapper) to pass `prefer_survivability_by_win=True` so the buried
  survivability winners float above the generic AD-DPS template (section B row above). NOT flipped
  (do-not-flip-blind) - validate the re-rank in a real ARAM. Distinct from the DSP11 DPS/burst kit-axis
  flip (which gates on `delta_dps>0`); survivability items add EHP not DPS so RF1 floats by WIN-table
  membership. Re-anchor the table each patch via `ops/audit/ds_perm_swarm/build_survivability_item_credit.py`.
  Needs a DS `:8893` restart on flip.
- 2026-06-17 LGS1 (no ENGINE bump - pure docs audit): live-sync list audited authoritative. (1) CORRECTED
  the DSV seam-flip row's location - `assume_takedown`/`assume_squishy_target`/`assume_ability_amp` flip the
  BURST scorer `agents/daemon_slayer/burst.py rank_items_by_burst` (+ `compute_burst_damage`), NOT `rank.py`
  (verified by grep: `rank.py rank_items` carries ONLY the DSP2 `exempt_offclass_by_win` + DSP11
  `prefer_kit_axis_by_win` seams; the DSV/DSP8 seams live in `burst.py`, DSP4 `score_completion_runes` in
  `burst.py`+`combo.py`). (2) ADDED a section-B row for the EXCLUDED anti-tank P3.2 live caster-stat producer
  (`antitank.py effective_magnitude` ap/ad_ratio scaling) + the `ehp.py compute_ehp(external_resist_*)`
  Orianna-E/Braum-W/Taric-W ally-resist survivability producer (egg-resist already default-ON item 321) -
  previously the only EXCLUDED live item with no checklist row. Every other rank.py/burst.py/combo.py
  default-OFF seam (DSP2/DSP4/DSP8/DSP11) + the ROADMAP Phase-D flips + champ-select Haiku flip already had
  an accurately-located row. No new seam shipped; no new OPEN work discovered (OPEN1/OPEN2 still pending).
- 2026-06-17 HZU1 (no ENGINE bump - tooling + docs; the item-level CODE shipped item 457 @a30cbba4):
  the HZ Lane-B build-order Haiku-flip gate already mines item-level signal, but its VERDICT is HOLD.
  Fresh re-run @651 SR matches (`--limit 0`) independently REPRODUCED item 457 byte-for-byte: lean-level
  followed-vs-not +2.3pp (766 vs 1066 rows, 95%=[-2.3,+6.9], flip_ready=False); completion-timing also a
  coin flip (fast<=20.82min 56.1% vs slow 56.7%); and 1/51 per-item carriers over the 4627
  lean-ambiguous rows = Infinity Edge anti_squishy +12.6pp (95%=[+0.7,+24.4]), with Serylda's Grudge
  +11.3pp just missing (lo=-0.9). NO live flip is shipped - the build coach AND the laning coach both
  HOLD Haiku until the gate clears its flip rail on a larger corpus and is eyeballed live. The live-gated
  rows for both the Lane-A laning read and the Lane-B build flip are recorded in section C above; re-run
  the gate as `data/rewind_history.db` grows. Artifact: `ops/runtime/build_order_validation.json`.
- 2026-06-17 DSP11 (ENGINE 1.135.0): Cluster-B2 kit-axis item-credit seam shipped DEFAULT-OFF.
  NEW `prefer_kit_axis_by_win` on `rank_items` (dps) + `rank_items_by_burst` (burst), driven by
  the WIN-anchored `kit_axis_item_credit.json` table (7 champs / 21 terminal items, built by
  `ops/audit/ds_perm_swarm/build_kit_axis_item_credit.py` from the DSP10 buried-winner report +
  rewind). When ON: (1) un-strips the champ's kit-axis items from the ranged-marksman off-class
  deny set (Ezreal's hard-excluded Trinity Force becomes a candidate), and (2) floats every
  positive-delta kit-axis item above the generic AD template (model order preserved within tiers).
  NO live scorer passes the flag (default False -> byte-identical). FLIP = wire the dps + burst
  scorer-dispatch to pass `prefer_kit_axis_by_win=True` (section B above). Validate the re-rank vs a
  real Pyke/Nilah/Ezreal ARAM before flipping (do-not-flip-blind). Cluster A (Zilean/Shaco/Kayle/
  Seraphine AP-in-ARAM) is a SEPARATE operator-gated archetype-routing decision, NOT in this table.
- 2026-06-17 DSP9 (no ENGINE bump - offline AUDIT tooling): NO new seam, so NO new
  flip row. The G7 comp-aware parity harness (`ops/audit/lolmath_ds_sweep/g7_comp_harness.py`)
  found that feeding DS the comp-matched build variant does NOT improve parity vs
  lolmath-ULTIMATE (burst_heavy 1.49 < mixed 1.84 < poke 1.86 < frontline_heavy 2.00
  mean item-overlap); lolmath-ULTIMATE is the cost-ignoring raw-stat pile, so the
  residual is the G6 cost-model axis, not comp-awareness. IMPLICATION for the live
  pass: the existing DSP8 `target_preset` flip (section B) is still worth validating
  for assassin-vs-comp correctness, but do NOT expect it to move lolmath-ULTIMATE
  parity - that gap is G6 (deferred FUTURE/BACKLOG per the Gemini-consult, do NOT
  blind-build a gold cost model). No new live-gated work added by DSP9.
- 2026-06-17 DSP7 (ENGINE 1.133.0): ally aura/enchanter seam shipped DEFAULT-OFF. NEW separate
  registry `_ALLY_FLAT_HP_GRANT_OVERRIDES` (in `_passive_ally_grant_overrides.py`) models the flat
  EHP an enchanter's shield/heal CONFERS on a protected ally - the THIRD ally-grant EHP mode
  (after resist + revive) and the SHIELD/HEAL bucket item-289 excluded. 7 enchanter grants
  (Janna/Lulu/Karma/Yuumi E + Seraphine W shields, Soraka/Nami W heals), base values from
  `champion_abilities.json` 16.12.1. Generic consumer seam `compute_ehp(external_flat_hp=)` (default
  0.0 -> byte-identical); no live scorer passes it. Live flip = wire a peel/EHP consumer reading the
  live ally team's granter set (section B above). Re-anchor base + add the granter AP ratio at flip.
  Validate the protected-ally EHP uplift vs a real game before wiring.
- 2026-06-17 DSP6 (ENGINE 1.132.0): enemy-rune threat seam shipped DEFAULT-OFF. NEW
  `agents/daemon_slayer/enemy_runes.py` (the enemy-side mirror of `summoners.py`) models 4 enemy
  runes on the preset each threatens - Press the Attack 8005 (incoming_amp 0.08 on the player),
  Conqueror 8010 (damage_ramp 21.6-48.0 max-stack Adaptive Force + 8%/5% lifesteal), Grasp 8437 +
  Second Wind 8444 (poke_sustain) - plus the non-rune antiheal constant (`GRIEVOUS_WOUNDS_PCT`
  0.40 + `enemy_antiheal_pct`). No live scorer consumes it (`ENEMY_RUNE_SEAM_IDS` marks the ids),
  so /rank is byte-identical. Live flip = wire an EHP / target-preset consumer that reads the
  enemy's live rune set (section B above). Magnitudes are DDragon-16.12.1-cited and re-anchor at
  flip. Validate the re-ranked anti-tank / sustain build vs a real game before wiring.
- 2026-06-17 DSP5 (ENGINE 1.131.0): summoner-spell seam shipped DEFAULT-OFF. NEW
  `agents/daemon_slayer/summoners.py` registry models 6 combat summoner spells (Ignite/Exhaust/Heal/
  Barrier/Cleanse/Ghost) on their scoring axis; no live scorer consumes it (`SUMMONER_SEAM_IDS` marks
  the ids), so /rank is byte-identical. Live flip = wire a fight_report/matchup/coach consumer that
  reads `summoners.py` against the live summoner set (section B above). Magnitudes are LoL-wiki-cited
  (DDragon/CDragon zero them) and re-anchor to the live patch at flip. Validate the adjusted
  survivability/antiheal/CC readout vs a real game before wiring.
- 2026-06-17 DSP4 (ENGINE 1.130.0): self-rune completion seam shipped DEFAULT-OFF. Added Shield Bash
  8401 (Resolve) - the one unmodeled LIVE pickable direct-damage rune proc - to RUNE_PROCS behind
  `COMPLETION_RUNE_IDS`. Live flip = `score_completion_runes=True` on the burst/combo scorer call site
  (section B above). Adds the 5-30 + 2.5% bonus-HP shield-proc floor to a shielded carrier's burst.
  Validate vs a real Shield-Bash game (Leona/Braum/Shen) before flipping.
- 2026-06-17 DSP3 (no ENGINE bump - RC-side resolver, no engine math): ARAM archetype-override seam
  shipped DEFAULT-OFF. Live flip = `core.archetype_picks.get_archetype_for(champion,
  prefer_aram_win_axis=True)` at the ARAM archetype-dispatch site (section C above). Re-bases the
  kit-default archetype to the rewind-WIN archetype for 6 Cluster-A champs; operator picks untouched.
  Validate the re-ranked scorer vs a real Kayle/KogMaw/Zilean/Shaco/Shyvana/Taric ARAM game first.
- 2026-06-17 DSP2 (ENGINE 1.129.0): off-class WIN-exemption seam shipped DEFAULT-OFF. Live flip =
  `rank_items(exempt_offclass_by_win=True)` at the carry/dps scorer call site (the caster-marksman
  re-include; section B above). Validate the re-rank vs a real Ezreal/Corki game before flipping.
- 2026-06-17 seeded from ROADMAP open-tail consolidation. DSP* seam flips append here as they ship.
- 2026-06-20 RC2 P3.3 overlay pulse-rationing flip (UI behavior, NOT a DS seam; `87f41baf` shipped
  the SHADOW). Shadow: `right_now.js` stamps `data-s0-cue` / `data-s0-tier` / `data-s0-pulse` on
  `#right-now` each render via `overlay_priority.signalFromState` -> `selectPrimary` -> `shouldPulse`,
  with ZERO live pulse change. SHIPPED LIVE (operator-approved 2026-06-22, verify-next-game): the
  `.action` per-band pulse (`right_now.js`, the `if (isFreshAction && _s0Pulse)` site near line 540,
  was line 533; the shadow block hoists `_s0Pulse = shouldPulse(...)` near line 496) AND
  `overlay_pulse.js` (MutationObserver, now early-returns via `_s0PulseArmed()` reading
  `#right-now[data-s0-pulse="1"]`) now CONSUME the stamped decision - so motion fires ONLY for the
  Emergency tier (incl. the lethal cue carrying the `lethal_incoming` passthrough) + a one-shot Urgent
  cross (spike/choices) (spec section 5 / acceptance A5). The flip is conservative-only by construction
  (`isFreshAction && _s0Pulse` is a strict subset of the old `isFreshAction` per-band path; the overlay
  gate only adds an early-return) - it can never add a pulse that did not fire pre-flip, only suppress
  benign 'good' / sustained-same-cue re-emits. Regression coverage: `tests/test_overlay_pulse_flip_rc2.py`
  (decision chain a-d + conservative-subset proof + consumer wiring). REMAINING EYEBALL (verify-next-game,
  NOT headless): on a real game confirm the suppressed pulses were all benign re-emits and the Emergency /
  one-shot Urgent cross still glows. The arbitration single-winner (A2) + 44px choice hit-target already
  ship live.
- 2026-06-20 RC2 P4.1 DPI/resolution overlay sizing live eyeball (UI geometry, NOT a DS seam; `4d5d54f0`
  shipped the code). The shell now sizes the overlay window by the work-area scale (resolveOverlayMetrics)
  and zooms the dock content to match (overlay.css `--rc-overlay-scale`). Headless-verified via the
  real-Chromium `test_overlay_view` fixture audit at 2560x1440 (dock zooms to ~598px right-anchored,
  screenshot `overlay_sr_1440_scaled.png`) + baseline-1920 no-op. OWED (operator-gated, NOT headless):
  eyeball the overlay COMPOSITED OVER A REAL LEAGUE GAME at 2560x1440 borderless - confirm the zoomed
  dock reads cleanly over a bright game scene, does not clip the bottom panes against the work area, and
  the right-edge dock lands where expected over the HUD (stage 4.6, live-game visual validation). The
  rc-shell Electron MAIN process needs a relaunch first to pick up the new window-size logic (the web
  renderer half auto-reloads via ADR-008 asset-hash). Does NOT block any further stage.
- 2026-06-20 RC2 P4.2 non-intrusive overlay live eyeball (UI behavior + geometry, NOT a DS seam; this
  cycle shipped the code DEFAULT-ON safe). Three additive overlay behaviors: (1) operator opacity slider
  -> rc-shell `overlayWindow.setOpacity` (the HUD recedes into the game), (2) click-through ZONES
  (`overlay_state.effectiveIgnoreMouse` + `clickthrough_zones.js` hover detector over the preload bridge)
  so PASSIVE captures clicks ONLY over an interactive control (#ovset / #rn-choices / #am-pane-ovds /
  drag strip) without the global ACTIVE hotkey, (3) auto-hide idle recede (`web/js/lib/overlay_idle.js`
  stamps `data-rc-idle` after ~8s of no coach change + no pointer activity; `overlay.css` dims the dock
  to 0.35 opacity; snaps back on the next change / hover). Headless-verified: rc-shell node suite 220/220
  + `test_overlay_idle_rc2` 16 + `test_overlay_settings_panel_dom` (extended) + real-Chromium
  `test_overlay_view` 36, live `:8888` serves the assets. OWED (operator-gated, NOT headless): eyeball
  COMPOSITED OVER A REAL LEAGUE GAME at 2560x1440 borderless - confirm (a) the opacity recede reads
  cleanly and the idle dim is not distracting / wakes correctly on a real coach update, (b) hover-to-
  interact flips the cursor capture crisply over #ovset / choices without eating game clicks elsewhere,
  (c) the drag strip is grabbable on hover. The rc-shell Electron MAIN process needs a relaunch first to
  pick up the new shell logic (preload setZoneHover + main.js opacity/zones); the web renderer half (idle
  recede + the #ovset controls) auto-reloads via ADR-008 asset-hash. Does NOT block any further stage.
- 2026-06-20 RC2 P4.3 single-monitor separated-window arrangement (window-management geometry, NOT a DS
  seam; this cycle shipped the code DEFAULT-ON safe). When the in-game overlay shows alongside the kept
  dashboard (E1/3.4 keepCompanion) on a SINGLE monitor, the shell now arranges them as SEPARATED side-by-
  side windows: an overlapping companion is repositioned (never resized - the size preset survives) to the
  work-area edge on whichever side of the overlay has more free room, top-aligned, so the dashboard sits
  BESIDE the HUD instead of under it. `overlay_state.resolveSeparatedCompanionBounds` is the pure decision
  (respects a companion already clear of the overlay -> moved:false); `main.js applySingleMonitorLayout`
  gates on `screen.getAllDisplays().length === 1` (multi-monitor untouched) + the new `separateWindows`
  setting (no-hotkey #ovset kill switch, default ON). Headless-verified: rc-shell node suite 232/232 (+15
  overlay_state geometry/setting), `test_overlay_settings_rc2` + `test_overlay_settings_panel_dom`
  (extended), real-Chromium `test_overlay_view` 44 (the #ovset Separate-windows toggle renders, defaults
  checked, ASCII label, clears the 42px hit floor), live `:8888` serves the assets. OWED (operator-gated,
  NOT headless): eyeball it OVER A REAL LEAGUE GAME at 2560x1440 borderless - start a game with the
  dashboard parked centered/over-the-right-dock and confirm (a) the dashboard auto-jumps to the free left
  side fully clear of the overlay, (b) it keeps its size (no preset corruption), (c) toggling "Separate
  windows" off in #ovset leaves an overlapping dashboard where the operator put it. The rc-shell Electron
  MAIN process needs a relaunch first to pick up the new main.js logic + the separateWindows authority;
  the web renderer half (the #ovset toggle) auto-reloads via ADR-008 asset-hash. Does NOT block any
  further stage.
- 2026-06-20 RC2 P4.4 settings-UI no-hotkey overlay actions (UI control surface, NOT a DS seam; this
  cycle shipped the code safe - additive #ovset controls, no render-path flip). The overlay's last
  keyboard-only behaviors are now on-screen #ovset controls over a new one-way `overlay-action` IPC: a
  Coach/Build/Threat panel-set segmented selector (the twin of Alt+Shift+C; lights the active segment from
  the body panelset, a pick fires `set-panel` and the shell persists + reloads the overlay onto that set)
  and an "Interact now" button (twin of Alt+Shift+A; fires `set-active`, forces ACTIVE with the same 20s
  auto-revert). `overlay_state.normOverlayAction` is the pure allow-list the main process trusts;
  `main.js applyPanelSet`/`setOverlayActive` are shared by the hotkeys AND the IPC so the two paths never
  drift. Hide/show (Alt+Shift+O) STAYS a hotkey by design (it clears BOTH surfaces, so a self-hiding on-
  screen control would have no way back). Headless-verified: rc-shell node 240/240 (+5 normOverlayAction,
  +3 action-IPC wiring), `test_overlay_settings_panel_dom` 33 (+8), real-Chromium `test_overlay_view` 19
  (+2: the selector + button render at the 42px floor with ASCII labels; panelset=build lights exactly the
  Build segment), live `:8888` serves the controls. OWED (operator-gated, NOT headless): eyeball it OVER A
  REAL LEAGUE GAME at 2560x1440 borderless - confirm (a) clicking Coach/Build/Threat in #ovset swaps the
  overlay panel set (no Alt+Shift+C), (b) the lit segment matches the shown set, (c) "Interact now" makes
  the HUD interactive then auto-reverts after ~20s. The rc-shell Electron MAIN process needs a relaunch
  first to pick up the new IPC handler + applyPanelSet/setOverlayActive; the web renderer half (the #ovset
  selector + button) auto-reloads via ADR-008 asset-hash. Does NOT block any further stage.
- 2026-06-20 RC2 P4.5 overlay + dashboard coexistence (UI control surface, NOT a DS seam; shipped
  code-safe - two additive #ovset action buttons over the existing 4.4 IPC, no render-path flip). Two
  payload-free coexistence commands on the `rc-shell:overlay-action` channel: `rearrange` (re-separate
  the overlay + kept dashboard NOW, forcing past the separateWindows auto kill switch) + `raise-companion`
  (showInactive-if-hidden + moveTop the kept dashboard, then a forced re-arrange). overlay_state
  OVERLAY_ACTIONS grew to 4 members (still frozen); main.js applySingleMonitorLayout({force}) bypasses the
  auto gate; raiseCompanion() reposition-only (no resize). #ovset .ovset-actpair = Re-arrange + Show
  dashboard. Headless-verified: rc-shell node 245/245, test_overlay_settings_panel_dom 37 (+4),
  real-Chromium test_overlay_view 20 (+1: both buttons at the 42px floor, ASCII labels, one row); 0 banned
  glyphs; live `:8888` serves the controls + CSS HTTP 200. OWED (operator-gated, NOT headless): eyeball it
  OVER A REAL LEAGUE GAME at 2560x1440 borderless - with the dashboard kept beside the HUD, confirm (a)
  dragging the dashboard under the overlay then clicking Re-arrange re-separates them side-by-side, (b)
  Show dashboard brings a buried/behind dashboard forward beside the HUD without resizing it, (c) neither
  button ever hides the overlay (no stranding). The rc-shell Electron MAIN process needs a relaunch first
  to pick up the new IPC dispatch + raiseCompanion/force-layout; the web renderer half (the #ovset buttons)
  auto-reloads via ADR-008 asset-hash. P4.6 (live-game visual validation, flipped LIVE) IS this whole-of-
  Phase-4 eyeball - this entry plus the P4.1-4.4 entries above are its checklist. Does NOT block any stage.
- 2026-06-20 RC2 P5.1 local-CV laning overrides (COACHING, NOT a DS seam; shipped code-safe SHADOW-ONLY -
  the served `choices` are NOT altered). The CV override (`core/laning_cv_overrides.py`: enemy DEAD ->
  shove, MISSING >=3s -> back off, my HP <0.35 vs an aggressive verdict -> disengage) currently rides ONLY
  the `data/hz_choice_shadow.jsonl` `cv_override` column. The SERVED FLIP (let the CV override drive the
  live A/B chips in `dashboard/_deterministic_coaching._compute_uncached`) is stage 5.2 and is GATED on the
  agreement re-measurement, NEVER a blind overnight flip. OWED (operator/Gemini-gated, NOT headless):
  (a) accrue real laning games so the new `cv_override` column fills (the live producer runs in-process on
  next RC restart - confirm rows appear with kind enemy_dead / enemy_missing / low_hp at the right moments);
  (b) re-run `tools/hz_shadow_report.py` and read det-vs-Haiku agreement WITH the CV layer applied; (c) when
  agreement climbs toward the >=70% target (`HZ_HAIKU_CALL_INVENTORY.md:75`), authorize the 5.2 served flip.
  Does NOT block any further stage.
- 2026-06-20 RC2 P6.4 port-safety pooled LCU connection (`RC_LCU_POOL` default-ON flip). The L6 keep-alive
  connection pool (`core/lcu_pool.py`) ships DEFAULT-OFF; the live path is byte-identical until `RC_LCU_POOL=1`.
  OWED (operator-gated, NOT headless): over a REAL champ-select + match, set `RC_LCU_POOL=1` and confirm
  (a) champ-select reads (`game_reader/poller._lcu_get`) still return correct sessions with the pool active,
  (b) no `UNEXPECTED_EOF_WHILE_READING` / SSL EOF on the reused socket (if it appears, check
  `netsh interface portproxy show all` FIRST per `reference_iphlpsvc_portproxy_2999` - that is a self-loop
  rule, not a pool bug), (c) the reconnect-on-drop path self-heals across a client restart mid-session, and
  (d) loopback socket count stays bounded (one long-lived socket per LCU port instead of one-per-call) under
  a tightened poll cadence. Only after (a)-(d) check out over a live game, authorize the default-ON flip.
  UPDATE 2026-06-30 (E7): the frozen `lcu/lcu_client.py._request` is NOW wired onto the same pool (commit
  `453b9ddd`, operator frozen-grant, still DEFAULT-OFF), so the every-tick auto-accept path
  (`LcuClient._auto_accept_tick`, ~2 LCU GETs/s) pools too once flipped - extend check (a) to also confirm
  auto-accept + rune-apply read correctly with the pool active. After (a)-(d) pass, the flip is a one-liner
  (`core/lcu_pool.py:40` default or `RC_LCU_POOL=1` in the runtime env). Does NOT block any further stage.
  Bench-swap state-render responsiveness (E7 TODO-1, commit `fe34040c`) shipped independently, NOT gated.
  **VALIDATED + FLIPPED 2026-07-01 (`c699b915`):** all four checks passed over a real live game - (a) auto-accept +
  poller reads correct with the pool active (game started clean), (b) 0 SSL EOF on the reused socket (log + a raw
  60-GET keep-alive control), (c) a forced-drop reconnect recovered HTTP 200, (d) main RC held exactly ONE persistent
  loopback socket to the LCU port past 169s (bounded, no per-call churn). Flipped `core/lcu_pool.py:40` default 0->1 +
  the tests to the default-ON contract. E7 default-ON flip is DONE - do NOT re-open this gate.
- 2026-06-21 R9 DS flat damage-reduction EHP seam (`assume_passive_flat_mitigation`, default-OFF). The NEW
  per-instance flat-DR registry (`agents/daemon_slayer/_passive_flat_mitigation_overrides.py`: Fizz P / Amumu E /
  Leona W) ships DEFAULT-OFF on `compute_ehp` + `rank_items_by_ehp` - the EHP math is byte-identical until
  `assume_passive_flat_mitigation=True`. OWED (operator/Gemini-gated, NOT headless - charter 4b "do not flip
  blind"): (a) over a real/replayed game, flip the seam on in the live survivability scorer path and confirm the
  flat-DR champions' (Amumu / Leona / Fizz) EHP-ranking shifts read sane vs eyeball + rewind-WIN data; (b) validate
  the two operator-tunable midpoints against live per-instance data - `_ASSUMED_FLAT_DR_INSTANCES`=6 (the
  representative count of mitigated instances over a fight - the live per-instance damage feed we lack) and
  `_ASSUMED_ABILITY_RANK`=4 (the per-rank Amumu/Leona flat-block read level). A WRONG precompute is worse than no
  credit, so do NOT default-ON until the midpoints are tuned to a live fight clock. Does NOT block any further
  stage.
- 2026-06-21 R12 all-source target-vulnerability mark seam (`apply_target_vuln`, ENGINE 1.149.0, default-OFF).
  The NEW cross-source vulnerability registry (`agents/daemon_slayer/_target_vulnerability_overrides.py`:
  Vladimir R Hemoplague 10% all-source + Evenshroud 3001 / Arena 223001 Coruscation 7%) ships DEFAULT-OFF on
  `agents/daemon_slayer/dps.py compute_dps` - the AA-DPS math is byte-identical until `apply_target_vuln=True`,
  when the wielder's whole DPS is multiplied by the product of every mark she owns (champion ability x each
  registered item, multiplicative). OWED (operator/Gemini-gated, NOT headless - charter 4b "do not flip blind"):
  (a) wire the scorer-dispatch (`agents/daemon_slayer/server.py` compute_dps call sites + `rank.py` / coach
  surfaces) to pass `apply_target_vuln=True` for a marked wielder (Vladimir, or any build holding Evenshroud),
  AND broaden the consumer beyond AA DPS to ability_dps + burst (the all-source mark amplifies those too - this
  seam wires the AA-DPS scorer first); (b) validate in a real game that a marked-target scenario shows a sanely
  higher effective DPS / item ranking, and an unmarked wielder stays byte-identical. The seam models the
  fully-marked target at full magnitude (the assume_takedown / assume_ability_amp developed-fight doctrine);
  uptime gating (Vlad R cooldown, Evenshroud's 5s post-immobilize window) is a live-consumer concern not baked
  here. Imperial Mandate (4005) is EXCLUDED as a non-fit (current-HP detonation, not an all-source %amp). A
  WRONG precompute is worse than no credit, so do NOT default-ON until validated. DS `:8893` restart on flip.
  Does NOT block any further stage.
- 2026-06-30 R43 Imperial Mandate target-vulnerability mark SEEDED (ENGINE 1.158.0, default-OFF) - SUPERSEDES
  the R12 bullet's "Imperial Mandate (4005) is EXCLUDED" note above. DDragon 16.13.1 `item.json` reworked
  Imperial Mandate to "Command: On Immobilizing an enemy champion, mark them as 7% Vulnerable for 4 seconds" -
  a +7% all-source mark - so 4005 / Arena 224005 / ARAM 324005 are now seeded at 0.07 in
  `_target_vulnerability_overrides._ITEM_VULN_OVERRIDES` (R41's handoff, executed; the stale Meraki Coordinated
  Fire mirror is overridden by the official Riot rework). This rides the EXISTING R12 `apply_target_vuln` seam
  and carries NO new flag: a build holding Imperial Mandate is amplified x1.07 only when that flag flips ON, so
  it is folded into the R12 flip already OWED above (wire the scorer-dispatch / rank / coach surfaces to pass
  `apply_target_vuln=True` for a marked wielder). OWED (operator/Gemini-gated, NOT headless): when the R12 seam
  is validated in a real game, also confirm an Imperial Mandate build's marked-target effective DPS / item
  ranking reads sanely higher, and an unmarked wielder stays byte-identical. A WRONG precompute is worse than no
  credit, so do NOT default-ON until validated. DS `:8893` restart on flip. Does NOT block any further stage.
- 2026-06-22 R14 cc_conditional durations_floor_s CC-floor seam (`apply_cc_floor`, ENGINE 1.150.0, default-OFF).
  The NEW guaranteed-minimum floor band on distance / channel-scaled conditional CC
  (`agents/daemon_slayer/cc_conditional.py` ConditionalCcEntry.durations_floor_s: Maokai R 0.75 / Hecarim R 0.75 /
  Ashe R 1.0 / KSante W 0.5 / Sion R 0.25) ships DEFAULT-OFF on `agents/daemon_slayer/cc_pressure.py`
  compute_cc_pressure - the CC-pressure math is byte-identical until `apply_cc_floor=True`, when a floor-tagged
  entry is credited floor + probability * (max - floor) instead of max * probability (in BOTH the standalone and
  the coexistence MAX-rule paths). OWED (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind):
  (a) wire the seam ON through the live consumer chain - compute_cc_pressure is consulted by compute_ehp /
  compute_hybrid (via include_conditional) and the cc-blended-EHP threat surface, none of which thread
  apply_cc_floor yet; thread it (default-OFF preserved) and confirm the floor-tagged champions' CC-pressure /
  blended-EHP-threat read sane vs eyeball; (b) validate the floor model (floor + prob*(max-floor)) reads better
  than the prior max*prob for a close-range Maokai/Ashe/Hecarim R or a short-channel KSante/Sion vs a real game -
  e.g. Ashe R OFF credits 3.5*0.4=1.4s (< unconditional 1.5s, the flat baseline wins) but ON credits
  1.0+0.4*(3.5-1.0)=2.0s (the floor-aware credit wins the coexistence MAX). A WRONG precompute is worse than no
  credit, so do NOT default-ON until validated. DS `:8893` restart on flip. Does NOT block any further stage.
- 2026-06-22 R17 anti-tank level-ramp %max-HP seam (`compute_antitank(level=)`, ENGINE 1.151.0, default-OFF).
  A real subset of antitank %max-HP rows scale their percentage with the CASTER's champion level
  (`agents/daemon_slayer/antitank.py` AntiTankEntry.ramp_lo/ramp_hi: Aatrox P 4:8, Brand P 8:12, KSante P 1:2,
  Mordekaiser P 1:5, Ornn P 10:18, Renata P 1:2, Skarner P 5:9, Urgot P 2:6, Zed P 6:10, Zeri P 1:11). The
  hand-tuned magnitude encodes the max-ramp (late-game) reliability; compute_antitank stays byte-identical until a
  `level` is injected, when a ramp-seeded row's effective magnitude scales by lerp(ramp_lo, ramp_hi,(level-1)/17)/
  ramp_hi (level=18 and level=None both byte-identical; un-ramped rows byte-identical at any level). OWED
  (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire a survivability / draft consumer to
  call compute_antitank with the live champion level (the /anti-tank route still passes no level, byte-identical),
  and confirm the early-vs-late level-discounted anti-tank scores read sane vs a real game (e.g. a level-3 Aatrox
  ranks below a level-16 Aatrox on the same tank). A WRONG ramp is worse than the flat magnitude, so do NOT
  default-ON until validated. DS `:8893` restart on flip. Does NOT block any further stage.
- 2026-06-30 R39 anti-tank current-HP level-ramp %current-HP seam (`compute_antitank(level=)`, ENGINE 1.155.0,
  default-OFF). The CURRENT_HP sibling of R17: a real subset of antitank %current-HP rows scale their percentage
  with the CASTER's champion level (`agents/daemon_slayer/antitank.py`
  AntiTankEntry.current_hp_ramp_lo/current_hp_ramp_hi: Senna P 1:10 - Absolution "1% : 10% (based on level) of
  target's current health"). The hand-tuned magnitude encodes the max-ramp (late-game) reliability;
  compute_antitank stays byte-identical until a `level` is injected, when a current-HP-ramp-seeded row's effective
  magnitude scales by lerp(lo, hi,(level-1)/17)/hi via the shared _current_hp_level_ramp_factor (level=18 and
  level=None both byte-identical; rows with no current-HP ramp byte-identical at any level - the same additive
  contract R17 holds, and the two ramp kinds never compound since a row carries at most one pair). OWED
  (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire a survivability / draft consumer to
  call compute_antitank with the live champion level (the /anti-tank route still passes no level, byte-identical),
  and confirm the early-vs-late level-discounted Senna anti-tank score reads sane vs a real game (a level-3 Senna
  ranks below a level-16 Senna on the same target). A WRONG ramp is worse than the flat magnitude, so do NOT
  default-ON until validated. DS `:8893` restart on flip. Does NOT block any further stage.
- 2026-06-27 R30 / DSV6 on-cast magic-burst seam (`compute_burst_damage(assume_magic_burst=)`, ENGINE 1.152.0,
  default-OFF). Item on-cast magic procs the per-cast burst combo loop never credited
  (`agents/daemon_slayer/_effects_data.py` magic_burst_base/magic_burst_ap_ratio: Luden's Echo 6655 75+5%AP,
  Stormsurge Squall 4646 125+10%AP, Malignance Hatefog 3118 180+15%AP one ult-zone). compute_burst_damage stays
  byte-identical until `assume_magic_burst=True`, when sum(base + ap_ratio*ap) is credited MR-mitigated (MAGIC
  routing) x mode_mult x magic_amp into total_burst (after the rune + execute layers). compute_ability_dps takes
  the same kwarg but is DELIBERATELY INERT (a one-shot magnitude has no place in a per-second metric; compute_dps
  already values these at their PeriodicProc rate, so folding them in the ability-DPS scorer would be wrong-units
  AND a partial double-count). OWED (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire a
  burst-scoring / rank consumer (burst.rank_items_by_burst, /rank-assassin, the offense-burst surface) to call
  compute_burst_damage with assume_magic_burst=True, and confirm an AP/magic burst build (Veigar/Syndra/Annie with
  Luden's or Stormsurge) ranks its on-cast magic item ABOVE where the seam-OFF engine placed it, vs a real game.
  A WRONG burst credit is worse than no credit, so do NOT default-ON until validated. DS `:8893` restart on flip.
  Does NOT block any further stage.
- 2026-06-27 R35 survivability percent-DR LIVE consumer (`mitigation_multipliers(snapshot=)` /
  `compute_ehp(apply_passive_mitigation=)`, ENGINE 1.153.0, default-OFF). The R19 forward-marker accessor
  `DataSnapshot.spell_damage_reduction_pct(champ, slot)` (per-rank PERCENT damage reduction from
  champion_abilities.json defensive modifier blocks) now has a consumer: when `apply_passive_mitigation=True` AND a
  snapshot is passed, each (champ, slot) percent-DR block folds into the EHP DENOMINATOR (mit_phys / mit_mag /
  mit_true) read at `_ASSUMED_ABILITY_RANK`=4, amortized by `_ACTIVE_DR_PROB`=0.3, axis by substring (8 snapshot
  champs: Alistar R / Belveth E / Braum E / Galio W split phys+mag / Garen W / Gragas W / MasterYi W / Warwick E).
  compute_ehp stays byte-identical until `apply_passive_mitigation=True` is flipped (the default-False path
  short-circuits to (1,1,1) before the snapshot is consulted; no live scorer/rank call passes the flag today). OWED
  (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): wire a survivability / EHP-rank consumer
  (rank_items_by_ehp, compute_hybrid_mitigation, the tank/bruiser survivability surface) to call with
  `apply_passive_mitigation=True` + the live snapshot, and confirm a percent-DR champ (Galio / Garen / MasterYi
  mid-fight) ranks its EHP / defensive items ABOVE where the seam-OFF engine placed it, vs a real game - and that the
  rank-4 + 0.3-uptime assumption reads sane (a Galio with W up survives the magic burst the OFF engine under-credited).
  A WRONG DR credit is worse than none, so do NOT default-ON until validated. DS `:8893` restart on flip. Does NOT
  block any further stage.
- 2026-06-30 R41 ally mark-detonation seam (`compute_dps(assume_ally_detonation=)` /
  `compute_burst_damage(assume_ally_detonation=)`, ENGINE 1.156.0, default-OFF). A champion whose MARK an ALLY
  consumes for bonus damage (the new PURE registry `agents/daemon_slayer/_ally_detonation_overrides.py`; seeded
  Leona P Sunlight FLAT_MAGIC 32:151 based-on-level, 2.5s mark cadence, verified vs champion_abilities.json
  16.13.1) is credited the amortized TEAM damage her mark enables: per-event magic for burst, per-event/cadence for
  the DPS rate, each MR-mitigated (MAGIC routing) x mode_mult x magic_amp x `_ASSUMED_ALLY_DETONATION_PROB`=0.5.
  Both compute_* stay byte-identical until the flag is True; an unmarked champion contributes 0 even with the flag
  on (the AA-probe call inside compute_burst_damage leaves the seam OFF, so the detonation is credited once in the
  burst total - no double-count). Imperial Mandate 4005 (the directive's named "10% current-HP" detonation) is a
  documented NON-FIT: DDragon 16.13.1 shows it REWORKED to a 7% Vulnerable all-source amp (Control / Command
  passives); the 16.12.1 Coordinated Fire detonation is gone (only the stale Meraki items mirror, content_patch
  None, still carries it), so seeding it would be a WRONG precompute - it now belongs in
  _target_vulnerability_overrides, not this detonation seam. OWED (operator/Gemini-gated, NOT headless - charter 4b
  do-not-flip-blind): wire a DPS / burst / rank consumer (compute_dps / compute_burst_damage / a rank surface) to
  call with `assume_ally_detonation=True` and confirm Leona's mark-enabling team value ranks ABOVE the seam-OFF
  placement vs a real game, and that the 2.5s Sunlight cadence + 0.5 proc-rate assumptions read sane. A WRONG
  detonation credit is worse than none, so do NOT default-ON until validated. DS `:8893` restart on flip. Does NOT
  block any further stage.
- 2026-06-30 R45 Poppy W low-HP doubled percent-of-resist tier (`resist_grants(caster_current_hp_pct=)` /
  `compute_ehp(caster_current_hp_pct=)` / `compute_hybrid(caster_current_hp_pct=)`, ENGINE 1.159.0, default-OFF).
  Poppy W "Stubborn to a Fault" already credited +12% of TOTAL armor + MR; R45 adds the Meraki-16.13.1 "doubled to
  24% while below 40% maximum health" tier as an INCREMENTAL percent applied when the caster's current-HP fraction
  drops below `low_hp_threshold` (Poppy 0.40), i.e. +12% more (24% total) at low HP. DEFAULT-OFF byte-identical on
  two axes: the seam rides the EXISTING `apply_passive_resist` flag AND the new `caster_current_hp_pct` defaults to
  1.0 (full HP) so the low-HP branch is dormant (1.0 not < 0.40) -> identical to 1.158.0. OWED (operator/Gemini-gated,
  NOT headless - charter 4b do-not-flip-blind): wire a live EHP / survivability consumer to pass Poppy's real
  current-HP fraction (the scorer today never reads caster HP) and confirm her sub-40%-HP EHP ranking reads sane vs a
  real game. A WRONG precompute is worse than none, so do NOT default-ON until validated. DS `:8893` restart on flip.
  Does NOT block any further stage.
- 2026-06-30 R46 stacking permanent max-HP passive registry (`compute_ehp(assume_passive_health_stacks=)`, ENGINE
  1.160.0, default-OFF). A NEW survivability axis + the SECOND EHP-NUMERATOR term: champion passives that grant
  PERMANENT bonus max health PER STACK (the new PURE registry `agents/daemon_slayer/_passive_health_overrides.py`;
  seeded Sion W Soul Furnace +4/kill, Cho'Gath R Feast +80/120/160 per stack by rank, Swain P Ravenous Flock +15 per
  Soul Fragment, all verified vs champion_abilities.json 16.13.1). When the flag is True the per-champ bonus max-HP is
  added RAW to every per-type EHP numerator (physical/magical/true), riding the same armor/MR curve. The per-stack HP
  is EXACT Meraki; the assumed STACK COUNT by level is an operator-tunable CONSERVATIVE midpoint (the live stack feed
  we lack). DEFAULT-OFF byte-identical (flag False -> 0.0; no live consumer passes it). OWED (operator/Gemini-gated,
  NOT headless - charter 4b do-not-flip-blind): (1) wire a live EHP / survivability consumer to pass
  `assume_passive_health_stacks=True` for Sion/Cho'Gath/Swain and confirm their stacked EHP ranks ABOVE the seam-OFF
  placement vs a real game; (2) ideally replace the conservative assumed-stack curve with the LIVE stack count (the
  in-game buff/stack reading from the Live Client buff list, if/when that surfaces) so the credit tracks the real
  game state, not a midpoint. A WRONG precompute is worse than none, so do NOT default-ON until validated. DS `:8893`
  restart on flip. Does NOT block any further stage.
- 2026-06-30 R49 on-being-hit reflect damage seam (`compute_dps(assume_passive_reflect=)` /
  `compute_burst_damage(assume_passive_reflect=)`, ENGINE 1.161.0, default-OFF). Rammus W Defensive Ball Curl reflects
  magic damage to basic attackers - a REACTIVE (incoming-triggered) TOTAL-resist form the empowered-AA
  `_passive_damage` seam could not carry. The new registry `agents/daemon_slayer/_passive_reflect_overrides.py`
  (seeded 1 vs verbatim 16.13.1 Meraki: Rammus W "15 (+ 10% total armor) (+ 10% total magic resistance) magic")
  computes the per-incoming-attack magnitude on the caster's resolved TOTAL armor/MR (full-MR via the new
  `caster_mr` scaling target). When the flag is True the reflect is MR-mitigated by the duel target's effective MR
  and amortized into DPS by the assumed incoming attack rate (1 / `reflect_cadence_s`, default 1.0s), or into burst
  over the `_ASSUMED_REFLECT_BURST_WINDOW_S` exposure window. The % terms scale on the build's resolved resists which
  do NOT include W's own active self-buff resists (the `_passive_resist` EHP seam) - a documented LOWER BOUND.
  DEFAULT-OFF byte-identical (both flags False -> the registry is never read; unregistered champ contributes 0 even
  ON). OWED (operator/Gemini-gated, NOT headless - charter 4b do-not-flip-blind): (1) wire a live DPS / burst / rank
  consumer to pass `assume_passive_reflect=True` for Rammus and confirm his W-tank reflect value ranks ABOVE the
  seam-OFF placement vs a real game, and that the `reflect_cadence_s` 1.0s incoming-attack + 3.0s burst-window
  assumptions read sane; (2) ideally feed the W-ACTIVE buffed total armor/MR (so the % terms match League's
  recalculate-over-duration) instead of the resting build resists. A WRONG precompute is worse than none, so do NOT
  default-ON until validated. DS `:8893` restart on flip. Does NOT block any further stage.
