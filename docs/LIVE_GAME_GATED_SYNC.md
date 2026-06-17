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
- [ ] DSP seam flips (as each ships): self-rune (DSP4), summoner-spell (DSP5), enemy-rune (DSP6),
      ally-aura (DSP7), enemy-comp target-preset (DSP8) - flip default-ON + eyeball the re-rank.
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

- 2026-06-17 DSP3 (no ENGINE bump - RC-side resolver, no engine math): ARAM archetype-override seam
  shipped DEFAULT-OFF. Live flip = `core.archetype_picks.get_archetype_for(champion,
  prefer_aram_win_axis=True)` at the ARAM archetype-dispatch site (section C above). Re-bases the
  kit-default archetype to the rewind-WIN archetype for 6 Cluster-A champs; operator picks untouched.
  Validate the re-ranked scorer vs a real Kayle/KogMaw/Zilean/Shaco/Shyvana/Taric ARAM game first.
- 2026-06-17 DSP2 (ENGINE 1.129.0): off-class WIN-exemption seam shipped DEFAULT-OFF. Live flip =
  `rank_items(exempt_offclass_by_win=True)` at the carry/dps scorer call site (the caster-marksman
  re-include; section B above). Validate the re-rank vs a real Ezreal/Corki game before flipping.
- 2026-06-17 seeded from ROADMAP open-tail consolidation. DSP* seam flips append here as they ship.
