# Boot Utility Scorer - Design Spec

- Status: DRAFT (awaiting operator review, then writing-plans)
- Date: 2026-07-09
- Author: Claude (Opus 4.8) with operator (SamplePlayer)
- Tier: 2 (DS engine + ENGINE_VERSION bump + dual suite + Share mirror + :8893 restart)
- Feature family: DS scorer calibration (BACKLOG "Daemon Slayer scorer calibration" - NEW enhancement #2)

## One-line

Replace the coarse hand-heuristic that picks a build's boots with a comp-conditioned
per-boot utility scorer, gated behind a DEFAULT-OFF `assume_boot_utility` seam so the
committed precompute tables stay byte-identical until a validated live flip.

## Problem

Boots are NOT engine-scored today. `core/build_order._select_boots(archetype,
target_armor, target_mr, mode)` (build_order.py:228) is a coarse hand-heuristic:

1. `target_mr >= 60` and not a DPS-axis champ -> Mercury's Treads (3111)
2. `target_armor >= 100` and not a caster-axis champ -> Plated Steelcaps (3047)
3. else -> `_DEFAULT_BOOTS_BY_ARCHETYPE` (carry/marksman/adc -> Berserker's 3006,
   mage/burst -> Sorcerer's 3020, tank/ehp/bruiser -> Steelcaps 3047,
   assassin/enchanter/hps/ability -> Ionian 3158)

Defects the operator called out (BACKLOG):

- DPS-axis champs are HARD-pinned to Berserker's regardless of comp. A marksman into
  a 5-CC lockdown comp never gets Mercury's, even when the tenacity + MR would save
  more effective uptime than the attack speed buys.
- The heuristic keys off the ENEMY's own resists (`target_mr` / `target_armor`) as a
  loose proxy, not the enemy DAMAGE-TYPE split (`enemy_ad_share` / `enemy_ap_share`)
  that actually decides whether armor or MR boots are correct.
- No boot's full utility profile is weighed: tenacity (Mercury's), ability + summoner
  haste (Ionian), MS + slow-resist (Swiftness), armor + the R80 AA-damage-reduction
  (Steelcaps) are all invisible to the pick. Boots are effectively chosen on a single
  axis per archetype.

The operator wants EVERY boot evaluated on its full utility profile against the comp,
"living-long-enough or one-extra-cast over pure DPS."

## Locked scope decisions

- Delivery: DEFAULT-OFF `assume_boot_utility` seam. Committed precompute tables stay
  BYTE-IDENTICAL this session. A non-committed preview diff shows exactly which boots
  would change per champ x mode x comp. The default-ON flip is a follow-up, validated
  in a live game (matches the established live-flip-seam pattern:
  `assume_ms_utility`, `prefer_survivability_by_win`, `apply_build_tenacity`).
- Module home: new `agents/daemon_slayer/boot_utility.py` (DS engine, Share-mirrored,
  ENGINE-versioned), consumed by `core/build_order._select_boots`. Sits alongside the
  sibling engine data primitives `_item_tenacity.py` / `_item_ability_haste.py`.
- Coverage: all tier-2 boots evaluated (full per-boot profile, not a 4-axis whitelist).
- v1 CC signal: MR-proxy + comp archetype only (no new plumbing). Threading real
  enemy-champion CC (cc_blended) into `_select_boots` is an explicit follow-up.

## Architecture

New pure module `agents/daemon_slayer/boot_utility.py`:

- `BOOT_UTILITY_PROFILE: dict[str, dict[str, float]]` - per tier-2 boot id, a
  normalized utility vector over axes {as_dps, magic_pen, ability_haste,
  armor_survival, mr_survival, tenacity, move_speed}. Values are seeded from each
  boot's real stats (parse-verified against DDragon 16.13.1, same convention as
  `_item_tenacity.py`) then normalized to [0, 1] within each axis.
- `score_boot(boot_id, ctx) -> float` - pure. `ctx` carries archetype axis affinities
  and the comp weights derived from `enemy_ad_share` / `enemy_ap_share` + the CC
  proxy. Returns `sum(profile[axis] * comp_weight[axis])`.
- `select_boot(pool, ctx, default_id, switch_margin) -> str` - argmax over the legal
  `pool`, but the challenger must beat the archetype `default_id`'s score by
  `switch_margin` to win (hysteresis, mirrors `_pick_top_safe`'s incumbent margin at
  build_order.py:360). Absent a decisive comp signal the archetype default holds -
  keeps the pick sane and damps jitter.
- Named, operator-tunable module constants for the axis weights and `switch_margin`
  (documented "conservative starter, tunable" exactly like `_MS_UTILITY_DPS_FRACTION`).

Consumer change in `core/build_order.py`:

- `_select_boots` gains `assume_boot_utility: bool = False` (appended at END with a
  default, per the Python-conventions rule) plus the comp signal it does not yet
  receive: `enemy_ad_share: float = 0.5`, `enemy_ap_share: float = 0.5` (also appended
  with defaults). OFF path = the current heuristic returned VERBATIM (byte-identical).
  ON path = resolve the archetype-default boot as the prior, build `ctx`, call
  `boot_utility.select_boot` over the mode's legal tier-2 pool, then apply the existing
  Arena 22-prefix mirror remap.
- The caller at build_order.py:526 threads `enemy_ad_share` / `enemy_ap_share` (already
  in `plan_build_order` scope) and the new flag into `_select_boots`.
- `plan_build_order` gains `assume_boot_utility: bool = False` (appended), forwarded to
  `_select_boots`. `core/build_order_precompute.py` and the live callers pass it
  through, all defaulting OFF.

## Data flow

precompute / live caller (flag defaults OFF)
  -> plan_build_order(assume_boot_utility=...)
    -> _select_boots(arch, target_armor, target_mr, mode, enemy_ad_share,
                     enemy_ap_share, assume_boot_utility)
      -> OFF: current heuristic (byte-identical)
      -> ON:  boot_utility.select_boot(pool, ctx, default_id, margin)

Comp signal at each layer:
- Committed comp-archetype table: `COMP_BIAS[frontline_heavy|burst_heavy|poke|mixed]`
  supplies `enemy_ad_share` / `enemy_ap_share` + `target_armor` / `target_mr`. CC
  pressure is proxied (frontline_heavy + high MR -> higher tenacity weight).
- Live coach / :8893 / ds-preview: real `enemy_ad_share` / `enemy_ap_share` from the
  game. (Real per-champion CC via enemy_champions is the follow-up.)

## Per-boot utility profile (v1 seed)

| id | boot | primary axes | strongest comp trigger |
|---|---|---|---|
| 3006 | Berserker's Greaves | as_dps | DPS/marksman axis, no decisive defensive need |
| 3020 | Sorcerer's Shoes | magic_pen | mage/AP axis |
| 3158 | Ionian Boots of Lucidity | ability_haste | ability-reliant kits (assassin/enchanter/mage) |
| 3047 | Plated Steelcaps | armor_survival | high enemy_ad_share |
| 3111 | Mercury's Treads | mr_survival, tenacity | high enemy_ap_share + CC proxy |
| 3009 | Boots of Swiftness | move_speed | poke/kite/heavy-slow comps |
| 3010 | Symbiotic Soles | move_speed | rune-granted roam hold |

Data sources (all already in-repo): `_item_tenacity.py` (3111 = 30%),
`_item_ability_haste.py` (3158 = 10 AH), DDragon item stats for AS / magic-pen / armor
/ MR / MS, and the R80 AA-damage-reduction registry for Steelcaps 3047.

## Byte-identical OFF contract

With `assume_boot_utility=False` (every committed-table + live caller today),
`_select_boots` returns exactly the current heuristic result. A parity test regenerates
a representative champ x mode x comp grid with the flag OFF and asserts the boot id is
unchanged from the current engine for every cell. This is the primary safety guarantee.

## Preview diff (non-committed)

A throwaway script (ops/audit/, NOT committed to the tables) regenerates the
comp-archetype grid with `assume_boot_utility=True` and diffs the boot slot vs the
committed OFF output, emitting a champ x mode x comp -> (old boot -> new boot) report
for the operator to eyeball before deciding to flip. No table file is written.

## Error handling / fail-soft

- Unknown boot id or missing profile entry -> contributes 0 utility (never raises);
  `select_boot` still returns the archetype default, so an unmapped boot degrades to
  today's behavior rather than crashing.
- Zero / missing comp shares -> the 0.5 / 0.5 neutral default; the archetype prior wins
  by the switch-margin, so a no-signal call reproduces the archetype default.
- The seam never PENALIZES: it only re-weights among legal boots; it cannot pick an
  illegal / non-purchasable boot (pool is the existing tier-2 set, Arena mirror applied
  after selection).

## Testing / acceptance (RED-first)

New `agents/daemon_slayer/tests/test_boot_utility.py`:

1. OFF byte-identical: grid parity vs the current `_select_boots` for a representative
   champ x mode x comp set (the safety gate).
2. Comp re-rank ON: a marksman (DPS-axis, today hard-pinned to Berserker's) into a
   high-`enemy_ap_share` + CC-proxy comp selects Mercury's 3111; the same marksman into
   a squishy no-CC comp keeps Berserker's 3006.
3. AD comp ON: a champ into high `enemy_ad_share` selects Steelcaps 3047 over its
   archetype default when the margin is decisive.
4. Ability kit ON: an assassin/enchanter keeps / gains Ionian 3158 for haste.
5. Hysteresis: a marginal comp signal below `switch_margin` holds the archetype default
   (no jitter).
6. Fail-soft: unknown boot / empty comp shares degrade to the archetype default without
   raising.
7. Arena mirror: an ON selection of 3111 on Arena returns 223111.

Tier-2 verification: full DS-dir suite + `tests/` subset green, ENGINE_VERSION bumped
(scorer change), `ds_share_sync --check` clean, DS :8893 restarted and `/health`
confirms the new engine + patch 16.13.1.

## Engine version

`assume_boot_utility` is a new default-OFF scorer seam -> bump ENGINE_VERSION
1.185.0 -> 1.186.0 (quoted-literal replace only, per the engine-bump rule). Committed
table output is byte-identical, so the version stamp advances without a table diff (the
same "capability added, output unchanged" shape as R58 `assume_ms_utility`).

## Out of scope (explicit follow-ups)

- The default-ON flip (1-line RC-side caller default + live-game "saner not different"
  validation).
- Real per-champion enemy CC (cc_blended) threaded into `_select_boots` for exact
  tenacity conditioning (v1 uses the MR + archetype proxy).
- The sibling BACKLOG enhancement #1 (situational / matchup-keyed ALTERNATIVE builds,
  crit-vs-on-hit) - a separate, larger feature.
- Any change to the boot-eligibility gates (quest-T3 exclusions) or `boots_unique` -
  those stay as-is.
