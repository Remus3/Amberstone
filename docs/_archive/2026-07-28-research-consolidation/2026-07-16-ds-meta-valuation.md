# DS Meta-Valuation Sweep - Real Meta Build Habits vs DS Ranking (2026-07-16)

Night-run research (LANE R). Question set from memory
`feedback_ds_sweep_meta_valuation_research` +
`project_ds_sweep_kaisa_poke_manamune`: for each flagged champion, does the
real current-patch meta build match what the Daemon Slayer (DS) ranking model
surfaces, and where they diverge, WHY (which scorer path, cite file:line).

- Live patch when accessed: 16.13 / 16.14 (some aggregators label it 26.13 /
  26.14; same live patch). All web sources accessed 2026-07-16.
- DS engine cited against the worktree checkout of branch
  `docs/research-20260716` (ENGINE line family 1.216.0, DS patch anchor
  16.13.1 per `agents/daemon_slayer/kit_axis_item_credit.json` _meta).
- This file is analysis only. NO engine or code change was made. Any fix is a
  separate Tier-2 session per the sweep template.

## How DS ranks a carry live (the shared mechanism)

The live build reco routes an AD carry through the carry / `ds.dps` scorer:
`rank_items` (`agents/daemon_slayer/rank.py:812`). That scorer optimizes
SUSTAINED auto-attack DPS integrated over a long fight, sorted by
`sort_by="delta"` (pure simulation, no win-rate blend). Two seams can tilt it
toward a champion's real burst / kit core, and BOTH matter to this sweep:

1. Burst-vs-sustained blend. `rank_items` takes an optional `fight_length`
   (`rank.py:831`); when a positive value is passed the score becomes
   `effective = burst_delta + delta_dps * fight_length` (`rank.py:871`) and rows
   sort by `(effective_score, delta_dps)` (`rank.py:800`). A SHORT fight_length
   tilts toward the one-rotation burst core. The value is set caller-side from a
   GATED allow-map, `core/ds_champion_fight_length.py:105-121`
   (`champion_fight_length`, `:135`), forwarded through
   `agents/daemon_slayer/server.py:462-466`. The allow-map has exactly SIX
   entries: `jhin` 0.5, `draven` 0.3, `samira` 0.3, `twitch` 0.5, `caitlyn`
   0.5, `jinx` 0.5. Every champion ABSENT resolves to `None` -> no burst term
   paid -> byte-identical sustained ranking.

2. Kit-axis win-float. `prefer_kit_axis_by_win` (`rank.py:907-919`) is the seam
   that floats a champion's real win-axis items (its docstring names "Ezreal Q +
   Manamune ramp" and "Nilah doubles crit") above the generic AD template. It
   reads `agents/daemon_slayer/kit_axis_item_credit.json` (champs present:
   Corki, Ezreal, Nilah, Pyke, Quinn, Senna - each with an `axis`). It is
   DEFAULT-OFF live (the _meta note calls it a "DEFAULT-OFF prefer_kit_axis_by_win
   seam input"; live path is `sort_by="delta"` with the seam False).

AD assassins do NOT use `rank_items`; they route to `arch == "assassin"` ->
`rank_assassin_for` (`core/daemon_slayer_client.py:1371-1372`, def at `:623`) ->
POST `/rank-assassin` -> the `ds.burst` window scorer, which values lethality /
burst natively. Note `rank_assassin_for` (`:623-647`) does NOT pass
`assume_takedown`, so the engine default `assume_takedown=False`
(`agents/daemon_slayer/burst.py:517`) holds live: the kill-state execute credit
(Collector / Hubris finisher, `burst.py:1073`) is DORMANT. Assassins do still
get a `target_current_hp_pct` execute-threshold hook (Zed R execute,
`rank_assassin_for` docstring `:653-655`).

## Summary table

| Champ | Meta build (2026-07-16) | Meta archetype | DS live path | Divergence |
|---|---|---|---|---|
| Ezreal | Tear -> Trinity Force -> Manamune/Muramana -> Spear of Shojin | mana-AD-caster poke | sustained `rank_items`, kit-axis seam OFF | HIGH - meta #1 core buried by dormant seam |
| Jhin | Collector -> IE -> RFC -> LDR (+ Youmuu's) | lethality-crit burst | `rank_items` + fight_length 0.5 (MAPPED) | PARTIAL - blend on, but execute core still buried vs tanky target |
| Zed | Voltaic -> Axiom Arc -> Serylda's -> Edge of Night | lethality burst assassin | `ds.burst` (`/rank-assassin`) | LOW-MED - burst aligned, execute credit dormant |
| Talon | Youmuu's -> Voltaic -> Edge of Night -> Serylda's | lethality roam-burst assassin | `ds.burst` (`/rank-assassin`) | LOW-MED - as Zed |
| Varus | Statikk -> Guinsoo's -> Terminus (on-hit) | on-hit sustained (dominant) | sustained `rank_items` | LOW - DS favors the DOMINANT build correctly |
| Kai'Sa | Kraken -> Guinsoo's -> Nashor's (on-hit) | on-hit sustained | sustained `rank_items` | NONE - poke->Manamune is fringe; DS correctly omits |

## 1. Kai'Sa - the specific research question (poke -> Manamune)

VERDICT: NEGATIVE. Poke Kai'Sa -> Manamune is REAL but FRINGE, and DS is CORRECT
to rank it low. This closes the `project_ds_sweep_kaisa_poke_manamune` question.

- Meta core (dominant): on-hit hypercarry Kraken Slayer -> Guinsoo's Rageblade
  -> Nashor's Tooth, Berserker's Greaves. Full core 35.53% pick / 51.62% WR;
  Kraken+Guinsoo's 54.71% WR over 3,906 games. Archetype: on-hit sustained
  (Guinsoo's double-proc + Kraken true damage feed Q stacking + evolution
  thresholds).
- The Manamune angle: it EXISTS only as an off-meta Mid/Top AP First-Strike poke
  build (Manamune -> Sorcerer's Shoes -> Luden's -> Shadowflame -> Rabadon's),
  i.e. Manamune paired with AP items for Q-spam mana refund, NOT a pure-AD
  Muramana core. Rates are fringe: Kai'Sa Mid ~44.6% WR / 0.2% pick (Emerald+),
  one AP-poke variant 36.6% WR over 71 matches; Kai'Sa Top 43.0% WR / 0.1% pick
  (D tier). No aggregator lists Manamune/Muramana in any recommended BOTTOM
  build path.
- DS treatment: Kai'Sa runs the sustained `rank_items` path. She is ABSENT from
  the fight_length allow-map (`core/ds_champion_fight_length.py:105-121`), ABSENT
  from `kit_axis_item_credit.json`, and ABSENT from
  `marksman_offclass_exempt.json`. So DS ranks her on-hit / crit template and
  never surfaces Manamune. Because Manamune-poke Kai'Sa is a sub-45% WR /
  0.1-0.2% pick niche, this omission is CORRECT, not a defect. Manamune
  mechanics are already modeled in the engine (bonus-AD-per-max-mana walk,
  `agents/daemon_slayer/mana_sim.py`), so if a future AP-poke scenario is ever
  targeted the item math is ready; it is a valuation choice, not a missing
  effect.
- Sources: aggregator A/lol/champions/kaisa/build; aggregator D/lol/kaisa/build/;
  aggregator C/lol/champions/kaisa/build/mid (accessed 2026-07-16).

## 2. Ezreal - HIGH divergence (the real find)

- Meta core (dominant): Tear of the Goddess rush -> Trinity Force -> Manamune
  (transforms to Muramana) -> Spear of Shojin -> Serylda's Grudge. Trinity Force
  51.38% WR / 37.43% pick; Spear of Shojin 54.33% WR as 4th. Archetype:
  mana-AD-caster poke (spellblade Q-spam). Essence Reaver is NO LONGER in the
  top build. Ezreal Bot 47.04% WR / 13.38% pick (A tier).
- DS treatment: Ezreal runs the sustained `rank_items` path, which ranks the
  generic on-hit / crit AD template (`rank.py:907-911` explicitly calls out that
  the model "cannot encode a kit's win-axis ... Ezreal Q + Manamune ramp"). The
  fix ALREADY EXISTS but is dormant: `kit_axis_item_credit.json` carries an
  Ezreal `manamune` axis (Muramana id 3042 lift +1.2 rewind_wr 48.6; Trinity
  3078), and `marksman_offclass_exempt.json` un-strips Ezreal's Trinity + Spear
  of Shojin. BUT both seams (`prefer_kit_axis_by_win`, `exempt_offclass_by_win`)
  are DEFAULT-OFF live, so on the live `sort_by="delta"` path Ezreal's meta #1
  core is buried under the generic template. This is the cleanest divergence in
  the set: the meta's single dominant build IS what the built-but-dormant seam
  was written to surface.
- Recommendation (separate Tier-2 session): Ezreal is the strongest candidate to
  evaluate a live kit-axis wiring OR a per-champ Manamune-anchor override. Note
  the standing operator guidance that all win-rate seams stay default-off
  (`project_ds_build_reco_optimal_not_winrate`); the honest framing here is that
  the OPTIMAL simulated build for Ezreal genuinely is the mana-caster core
  (spellblade Q is his damage engine), so this is a sim-coherence gap, not a
  win-rate lean. Validate that compute_dps credits Ezreal Q spellblade repeats
  before assuming the seam is the only lever.
- Sources: aggregator A/lol/champions/ezreal/build; aggregator C/lol/champions/ezreal/build;
  pro-build site Z4.com/champion/ezreal (accessed 2026-07-16).

## 3. Jhin - PARTIAL (pilot already mapped, execute tail remains)

- Meta core: Doran's Blade -> Boots of Swiftness -> The Collector -> Infinity
  Edge -> Rapid Firecannon (-> Lord Dominik's); some open Hubris. Archetype:
  lethality-crit burst hybrid (confirmed). The Collector ~48.9-49.8% WR (most
  built); Youmuu's 51.2-54.23% WR; IE 53.8-56.41% WR; RFC 54.9% WR.
- DS treatment: Jhin IS the pilot - MAPPED at fight_length 0.5
  (`core/ds_champion_fight_length.py:108`), which surfaces the lethality-crit
  core (IE ~#4, Serylda's ~#7, Collector ~#8, Hubris ~#9, Youmuu's ~#11 per the
  module docstring) and sinks sustained on-hit below it. Complementary to the
  AS-lock override (`_passive_as_lock_overrides.py`). RESIDUAL divergence: at the
  live TANKY mode-curve target the Collector / execute core stays buried
  (~#8-13) even with fight_length engaged; fully surfacing execute needs the
  squishy-carry target scenario (lever L4, out of the shipped L3 scope, per the
  same docstring). So Jhin is mostly aligned but still under-values the
  execute-snowball tail.
- Sources: aggregator A/lol/champions/jhin/build; aggregator B/lol/champions/jhin/build;
  aggregator Z13.com/champion/builds/Jhin (accessed 2026-07-16).

## 4. Zed and Talon - LOW-MED (assassin burst path, execute credit dormant)

- Zed meta core: Voltaic Cyclosword -> Ionian Boots -> Axiom Arc -> Serylda's
  Grudge -> Edge of Night. Voltaic 50.7% WR (most built); Serylda's a top-WR
  completion.
- Talon meta core: Youmuu's Ghostblade -> Ionian Boots -> Voltaic Cyclosword ->
  Edge of Night -> Serylda's Grudge. Serylda's ~55.9-58% WR / ~16% pick;
  Edge of Night 55.0% WR.
- DS treatment: both route to `arch == "assassin"` -> `ds.burst`
  (`core/daemon_slayer_client.py:1371`), a native burst-window scorer that values
  lethality + one-combo damage, which is the RIGHT axis for these two - so the
  core divergence is low. The residual: `rank_assassin_for` (`:623-647`) does not
  forward `assume_takedown`, so the kill-state execute credit stays OFF live
  (`burst.py:517`, `:1073`). Execute / snowball items (The Collector, Hubris)
  that reward securing a kill are therefore modestly under-credited relative to
  their meta prominence, though the Zed-R `target_current_hp_pct` execute
  threshold hook does partially model the finisher. Worth a live-gated check
  before any change.
- Sources: aggregator C/lol/champions/zed/build; aggregator A/lol/champions/zed/build/mid;
  aggregator A/lol/champions/talon/build; aggregator C/lol/champions/talon/build/mid;
  aggregator N/lol/build/zed (accessed 2026-07-16).

## 5. Varus - LOW (DS favors the dominant build correctly)

- Meta: TWO real builds. ON-HIT dominant: Statikk Shiv -> Guinsoo's Rageblade ->
  Terminus (Lethal Tempo), pick 33.02% / WR 51.03%; Terminus 52.97% WR.
  LETHALITY-POKE secondary: Youmuu's -> Muramana -> Edge of Night, pick 10.23% /
  WR 48.92%. Overall 47.24% WR / 2.32% pick (B tier).
- DS treatment: Varus runs the sustained `rank_items` path and is absent from all
  three override tables, so DS ranks the on-hit / AS template - which is the
  DOMINANT meta build on BOTH pick (33% vs 10%) and win (51.03% vs 48.92%). So DS
  is aligned with Varus's primary. It will not surface the secondary
  lethality-poke Muramana path, but that path is the minority build, so this is
  low priority. (Varus is the one champ here where the same Manamune -> Muramana
  pattern the Kai'Sa question probes IS a real secondary path, unlike Kai'Sa.)
- Sources: aggregator A/lol/champions/varus/build; aggregator D/lol/varus/build/;
  aggregator N/lol/build/varus (accessed 2026-07-16).

## Divergence ranking + recommended next actions

1. Ezreal (HIGH) - live path buries the meta #1 mana-caster core; the kit-axis +
   off-class-exempt seams that would fix it exist but are default-off. Best
   single Tier-2 candidate. First validate compute_dps Q-spellblade crediting.
2. Jhin (PARTIAL) - pilot mapped; only the execute / squishy-target tail (L4)
   remains, which is a known deferred lever.
3. Zed / Talon (LOW-MED) - correct burst axis; only the dormant kill-state
   execute credit (`assume_takedown`) is under-weighted. Live-gate before touch.
4. Varus (LOW) - DS already favors the dominant on-hit build; secondary poke
   path unsurfaced but minority.
5. Kai'Sa (NONE) - research question closed NEGATIVE: poke->Manamune is fringe,
   DS correctly omits it.

Cross-cut: a sustained-DPS scorer that ignores the mana-AD poke pattern is
CORRECT for Kai'Sa (fringe), acceptable for Varus (minority), but WRONG for
Ezreal (primary). The pattern is not "always lift Manamune" - it is champion-
specific, which is exactly why the per-champ allow-map / kit-axis table design
(not a global heuristic) is the right shape.

## Sources (accessed 2026-07-16)

- aggregator A/lol/champions/{kaisa,jhin,zed,talon,varus,ezreal}/build
- aggregator B/lol/champions/jhin/build
- aggregator D/lol/{kaisa,varus}/build/
- aggregator C/lol/champions/{kaisa,zed,talon,ezreal}/build
- aggregator N/lol/build/{zed,varus}
- aggregator Z13.com/champion/builds/{Jhin,Talon}
- pro-build site Z4.com/champion/ezreal

Repo citations verified live in the worktree checkout of
`docs/research-20260716`:
`agents/daemon_slayer/rank.py`, `.../burst.py`, `.../kit_axis_item_credit.json`,
`.../marksman_offclass_exempt.json`, `.../server.py`,
`core/ds_champion_fight_length.py`, `core/daemon_slayer_client.py`.
