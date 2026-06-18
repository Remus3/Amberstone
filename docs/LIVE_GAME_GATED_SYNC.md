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

- Flag-ready re-rank seams (9): DSV2/DSV3/DSV4, DSP2, DSP8, DSP11 (dps+burst),
  RF1, RF2, RF3+RF6. Run `python ops/audit/ds_perm_swarm/live_flip_eyeball.py`
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

- [ ] LCU push: rune pages + item sets + summoner spells push to the live client on champ-select enter
      (`lcu/lcu_rune_writer.py`; ROADMAP item 215/259/212). Verify the pushed page matches the DS pick.
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
- [ ] DSP11 kit-axis item-credit flip (seam shipped default-OFF, ENGINE 1.135.0): no live scorer
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
- [ ] RF1 generic-bruiser-template survivability flip (seam shipped default-OFF, ENGINE 1.136.0): no live
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
- [ ] Live adaptation `st-*` producers: ~88 ADAPTATION rows render "-" in-game (no live producer;
      ROADMAP item 281 gap 1). Confirm which surface live vs stay post-game-only.
- [ ] Inhibitor-callout fires when an inhibitor is down (visual; ROADMAP item 283).
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
- [ ] Arena boots 22xxxx mirror: SR uses tier-3 3xxx, Arena needs the 22xxxx map30 mirror (P6-G4 deferred).

## E. Electron overlay (rc-shell, in a real match)

- [ ] In-game transparent overlay capture WITH ACTIVE knob interaction (Alt+Shift+A; re-rank live).
      Shell relaunch picks up slices 1-4 (ROADMAP item 214; phases 1-5 code DONE).
- [ ] Operator packaging: `npx electron-builder` + first GitHub Release + packaged update check (private repo GH_TOKEN).

## F. Post-game (any completed match)

- [ ] PGR visual capture S3/S4/S5 + @N timeline metrics (gold@10/cs@10 need per-participant frames;
      ROADMAP item 275/276/277).
- [ ] Replay/Session/History live ingest freshness after a real game end (90s Match-V5 writer; ORCH REPLAY1).

---

## Live-flip ledger (loop appends; newest first)

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
