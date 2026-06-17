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
      `assume_ability_amp` (DSV4) -> turn ON in `rank.py`, confirm the re-ranked build is saner.
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
- [ ] DSP5 summoner-spell flip (substrate shipped default-OFF, ENGINE 1.131.0): no scorer consumes
      `agents/daemon_slayer/summoners.py` yet. The flip WIRES a consumer that reads the registry to
      adjust the caster's effective survivability / antiheal / CC at the right surface (fight_report /
      matchup / a coach), keyed off the player's + enemy's actual summoner set from the live client:
      Ignite antiheal+true (id 14), Exhaust incoming-DR 0.35 (id 3), Heal/Barrier flat EHP (7/21),
      Cleanse 0.75 cc-discount (id 1), Ghost MS (id 6). Re-anchor the wiki magnitudes to the live
      patch at flip time (DDragon/CDragon zero them). Eyeball the adjusted readout vs a real game.
- [ ] DSP6 enemy-rune threat flip (substrate shipped default-OFF, ENGINE 1.132.0): no scorer
      consumes `agents/daemon_slayer/enemy_runes.py` yet. The flip WIRES an EHP / target-preset
      consumer that reads the ENEMY's live rune set to modulate the player's effective survivability
      and the enemy's poke-resist: enemy Press the Attack (id 8005) -> divide the player's EHP by
      1.08 (`enemy_incoming_amp_pct`); enemy Conqueror (id 8010) -> add `enemy_damage_ramp` raw
      bonus enemy damage (and treat its 8%/5% lifesteal as enemy fight-sustain in the target preset);
      enemy Grasp + Second Wind (8437/8444) -> raise the enemy's effective HP vs poke
      (`enemy_poke_sustain_hp`); ANY enemy antiheal source -> discount the player's heal-based EHP by
      `enemy_antiheal_pct(True)` 0.40. Re-anchor magnitudes to the live patch at flip (DDragon
      16.12.1 today). Eyeball that vs a real game the player's anti-tank / sustain build shifts
      sanely when the enemy runs PtA / Conqueror / Grasp, and a no-threat lobby is unchanged.
- [ ] DSP7 ally aura/enchanter flip (substrate shipped default-OFF, ENGINE 1.133.0): no scorer
      passes `compute_ehp(external_flat_hp=)` yet. The flip WIRES a peel/EHP consumer that, for a
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
- [ ] Live adaptation `st-*` producers: ~88 ADAPTATION rows render "-" in-game (no live producer;
      ROADMAP item 281 gap 1). Confirm which surface live vs stay post-game-only.
- [ ] Inhibitor-callout fires when an inhibitor is down (visual; ROADMAP item 283).
- [ ] Vision self-heal `:8889` validated in a real game (relay-first poller; ROADMAP item 275/276).

## C. ARAM / ARAM Mayhem (KIWI)

- [ ] HZ laning agreement read: after live ARAM games accrue, run `tools/hz_shadow_report.py` laning
      agreement (now unblocked, item 456) -> gate the precompute-vs-Haiku live coach FLIP (cycle 52 NEXT).
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
