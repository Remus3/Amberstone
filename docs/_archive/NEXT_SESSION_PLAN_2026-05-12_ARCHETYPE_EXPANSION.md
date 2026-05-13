# DS Archetype Expansion — Multi-Session Plan

Drafted s173.5 (2026-05-12) at the end of a design conversation about expanding Daemon Slayer beyond auto-attack DPS. This doc is the single self-contained reference for executing the expansion across the next ~10 sessions. Start any future session by reading this file + the current ENGINE_VERSION + CLAUDE.md.

> **Status check before each phase:** confirm DS-server `/health` engine_version matches `agents/daemon_slayer/__init__.py` ENGINE_VERSION. If they diverge, the DS server needs a `Stop-Process` + relaunch via `pythonw tools/start_daemon_slayer.py` per memory `reference_ds_server_not_supervisor_watched`.

---

## Architectural decisions locked in s173.5

These are operator-confirmed; do not re-litigate without explicit approval.

1. **One engine, six scorers** — keep `agents/daemon_slayer/` as the umbrella module; add five sibling scorer functions alongside `compute_dps()`. Internal naming: `ds.dps`, `ds.ehp`, `ds.hybrid`, `ds.ability`, `ds.burst`, `ds.hps`. Share `build_champion()`, `ItemEffect` registry, `CallContext`, snapshot loader, `:8893` server.
2. **Daemon Slayer keeps umbrella name** — operator brand, not algorithm name. Scorers expose via per-archetype routes on the existing server: `/rank-tank`, `/rank-mage`, etc.
3. **Top-2 archetypes always shown** in CS panel + in-game tab across **all champs** (not just flex ones — "congruence"). Meta default pre-selected from DDragon `tags[0]` + win-rate priors.
4. **Selection gates the coach + match-analysis pipelines.** Only the primary scorer runs per coach tick. Secondary panel freezes after initial CS + game-start passes; refreshes only on enemy/operator item-complete events.
5. **Mid-game switch path:** user clicks the secondary archetype → new primary fires immediately (one-shot warm pass) → subsequent coach ticks use it. Old primary's cached data stays in the secondary panel.
6. **First-purchase-item inference = soft nudge, not auto-override.** If primary is Tank but operator buys Liandry, show "switch to AP scorer? [yes/no]" prompt once per game.
7. **Cadence (verified s173.5):** DS runs every coach tick (8-25s normal, 3-5s fast-path on kill/death/item/level event). Each tick is ~125-175 `compute_dps()` calls per `rank_for()`. Sub-second on warm snapshot. Dashboard polls `/api/ds-preview` on its own cadence for the `#ds-pill` and CS view.

## Phase summary

| Phase | Scope | Sessions | Champs unlocked | Risk |
|---|---|---|---|---|
| **0 (DONE — s173.5)** | Dead-unique candidate filter | — | All champs benefit | Low — shipped 2026-05-12 |
| **1** | Tank EHP scorer (`ds.ehp`) + integrate `core/defensive_picks.py` | 1 | ~15 pure tanks | Low |
| **2** | Bruiser hybrid scorer (`ds.hybrid` = `α·dps + β·ehp`) + per-champ α/β table | 1 | ~20 bruisers | Low |
| **3** | CS scorer-picker UI + state.cs_archetype_pick + invalidation events | 1 | UX unlock for all flex champs | Low (pure UI) |
| **4** | Mage ability DPS (`ds.ability`) via Meraki bulk endpoint | 3 | ~30 mages | Med (ability formula schema parsing) |
| **5** | Assassin burst-window scorer (`ds.burst`) | 2 | ~15 assassins | Med (depends on Phase 4) |
| **6** | Enchanter healing throughput (`ds.hps`) — best-effort with avg-ally model | 2 | ~10 enchanters | Med (ally-state model imperfect by design) |

Total: ~10 sessions for ~90 champions with archetype-appropriate scoring.

---

## Phase 1 — Tank EHP Scorer

**Single session. Closed-form math, no new data sources. Highest ROI.**

### Files to create

- `agents/daemon_slayer/ehp.py` — `compute_ehp()` + `EhpResult` dataclass + `rank_items_by_ehp()`
- `agents/daemon_slayer/tests/test_ehp.py` — ~30 tests
- `agents/daemon_slayer/tests/test_rank_tank.py` — ~15 tests for the ranker side

### Files to edit

- `agents/daemon_slayer/__init__.py` — `ENGINE_VERSION = "0.62.0"` → `"0.63.0"`; add `compute_ehp` to module docstring
- `agents/daemon_slayer/server.py` — add `/rank-tank` route mirroring `/rank` shape
- `core/daemon_slayer_client.py` — add `rank_tank_for()` client helper
- `core/defensive_picks.py` — promote from threat-classifier to ranker that calls `compute_ehp` under the hood (or refactor it to feed `rank_items_by_ehp` instead — discuss before doing)
- `CLAUDE.md` · `README.md` · `docs/DAEMON_SLAYER.md` · `docs/ARCHITECTURE.md` · `ROADMAP.md` · `BRIEF.md` — version + test count + scorer mention sync
- `WAKEUP_NOTES.md` — s174 wrap

### API shape

```python
@dataclass(frozen=True)
class EhpResult:
    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]
    mode: str
    hp: float
    armor: float
    mr: float
    physical_ehp: float       # HP / (1 - 100/(100+armor))
    magical_ehp: float        # HP / (1 - 100/(100+mr))
    blended_ehp: float        # weighted by enemy AD/AP profile
    enemy_ad_share: float     # 0.0-1.0; default 0.5
    enemy_ap_share: float     # 0.0-1.0; default 0.5
    # Optional layers:
    bonus_hp_amp: float       # Jak'Sho, Heartsteel +HP scaling
    shield_throughput: float  # Sterak's, Doran's Shield avg shield/min — defer to phase 1.5

def compute_ehp(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Iterable[str | int] = (),
    mode: str = "SR",
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
    augments: Optional[Iterable] = None,
) -> EhpResult: ...

def rank_items_by_ehp(
    snapshot, champion_id, level, current_item_ids=None, mode="SR",
    enemy_ad_share=0.5, enemy_ap_share=0.5,
    budget=None, slot_count=6, top_n=20,
    include_components=False, only_item_ids=None, sort_by="delta",
    augments=None, filter_shared_uniques=True,
) -> RankResult: ...
```

Sort keys for tank ranker: `delta` (absolute EHP gained) and `efficiency` (EHP per 1000 gold).

### Math

- Physical EHP: `hp / armor_mitigation_factor(armor)` — reuse `_armor_factor` from `dps.py`
- Magical EHP: `hp / armor_mitigation_factor(mr)` (same formula, different stat)
- Blended: `physical_ehp · enemy_ad_share + magical_ehp · enemy_ap_share + true_ehp · (1 - ad_share - ap_share)` where true_ehp = hp
- Enemy share inputs come from `core/defensive_picks.py` classification (currently emits `burst/ad/ap/tank` profile — adapt to `enemy_ad_share` / `enemy_ap_share` floats)
- Bonus HP amps (Jak'Sho 8% bonus HP, Cinderhulk 15% bonus HP) feed into the build resolver via existing schema — no new field needed

### Tests to write (~30 in test_ehp.py)

1. `test_naked_aatrox_ehp_equals_raw_hp` — no resists from items, no amps
2. `test_thornmail_lifts_physical_ehp` — adding Thornmail increases physical_ehp by >10%
3. `test_force_of_nature_lifts_magical_ehp_more_than_physical` — pure-MR item
4. `test_jaksho_bonus_hp_amp_scales_with_stacks` — Jak'Sho passive at full stacks
5. `test_blended_ehp_60_40_ad_split` — 60% AD, 40% AP enemy → physical_ehp dominates
6. `test_pure_ap_enemy_doesnt_value_armor` — enemy_ad_share=0.0 → armor adds zero to blended_ehp
7. `test_bonus_hp_components_count` — Giant's Belt, Kindlegem add raw HP
8. `test_negative_armor_uses_inverted_formula` — Black Cleaver shred → `2 - 100/(100-armor)`
9. `test_compute_ehp_matches_build_resolver_stats` — `hp` field on EhpResult == build_champion(...).stats["hp"]
10-30: edge cases (level clamp, unknown champion, ARAM mode amp, Arena augments, missing snapshot, dead-unique filter on ranker, sort by efficiency, budget filter, top_n clipping, shared-unique dedup matches DPS scorer behavior)

### Integration with `core/defensive_picks.py`

Current state (s171): emits classified threat profile (burst/ad/ap/tank counts) + recommends from a 22-item curated catalog. The catalog overlaps heavily with what `rank_items_by_ehp` would naturally surface from the EHP math.

**Option A — Replace**: rip out the curated catalog, let `rank_items_by_ehp` produce the list. Coach reads ranker output directly. Pros: single source of truth. Cons: loses some hand-tuned ordering (e.g., "Plated Steelcaps over Mercury's when burst≥5 even if EHP-per-gold favors Mercs").

**Option B — Layer**: keep curated catalog as a whitelist filter for `rank_items_by_ehp` via `only_item_ids`. Best of both — math-driven ranking within an operator-vetted candidate pool.

Recommend Option B for Phase 1. Reduces risk and preserves the s171 work that's already operator-validated. Migrate to Option A later if calibration shows Option B's curated list adds no value.

### Verification

- `py -m pytest agents/daemon_slayer/tests/test_ehp.py -v` → all green
- `py -m pytest agents/daemon_slayer/tests/test_rank_tank.py -v` → all green
- Full DS suite `py -m pytest agents/daemon_slayer/tests/` → ~985 passing (was 955)
- DS server restart + `/health` check shows engine_version 0.63.0
- Probe `/rank-tank` endpoint with Malphite + ([3068]) → returns Thornmail / Frozen Heart / Force of Nature in top 5
- Game-PC monitor 1 capture: no visible regression in current dashboard

### Out of scope for Phase 1

- Shield-throughput modeling (Doran's Shield, Sterak's lifeline) — defer to Phase 1.5
- Healing-throughput modeling (Lifesteal, Spirit Visage healing amp) — fits better in Phase 6 enchanter scorer
- Coach prompt integration — operator decides at start of Phase 1 whether tank coach should use ds.ehp or wait

---

## Phase 2 — Bruiser Hybrid Scorer

**Single session. Depends on Phase 1 only.**

### Concept

Bruisers want both DPS and EHP. The scorer combines them:

```
hybrid_score = α · dps_score + β · ehp_score
```

with per-champion (α, β) tuples in a new lookup table `agents/daemon_slayer/archetype_weights.json`. Defaults:

| Champion | α (DPS weight) | β (EHP weight) | Reasoning |
|---|---|---|---|
| Jarvan IV | 0.55 | 0.45 | Engage-fighter; needs to live through R |
| Darius | 0.65 | 0.35 | Sustain-AD bruiser; pressure-oriented |
| Garen | 0.55 | 0.45 | Survival-first toplaner |
| Camille | 0.65 | 0.35 | Lane-bully → splitpush DPS |
| Renekton | 0.65 | 0.35 | Lane bully; Fury-up burst |
| Sett | 0.55 | 0.45 | Frontline brawler |
| Mordekaiser | 0.50 | 0.50 | Pure 1v1 isolate; needs both |
| Riven | 0.70 | 0.30 | Snowball-fighter; outplays > sustain |
| Volibear | 0.55 | 0.45 | Engage-fighter; ult survival |
| Nasus | 0.50 | 0.50 | Hyperscaling; Q damage + tank |
| Olaf | 0.60 | 0.40 | All-in fighter |
| Skarner | 0.50 | 0.50 | Pick-engage; ult survival |
| Hecarim | 0.55 | 0.45 | Engage-fighter |
| Udyr | 0.55 | 0.45 | Phoenix/Wolf hybrid |
| Vi | 0.55 | 0.45 | Engage-fighter |
| Xin Zhao | 0.60 | 0.40 | Skirmish-fighter |
| Lee Sin | 0.65 | 0.35 | Skirmish; outplay-dependent |
| Wukong | 0.60 | 0.40 | Engage-fighter; clone trick |
| Warwick | 0.55 | 0.45 | Engage-sustain |
| Trundle | 0.60 | 0.40 | Pillar-shutdown fighter |

Default fallback for un-listed champions: `(0.50, 0.50)`.

### Files

- New: `agents/daemon_slayer/hybrid.py` (~200 LOC)
- New: `agents/daemon_slayer/archetype_weights.json` (the table above)
- New: `agents/daemon_slayer/tests/test_hybrid.py` (~20 tests)
- Edits: `__init__.py` (ENGINE → 0.64.0), `server.py` (new `/rank-bruiser` route), `core/daemon_slayer_client.py`, docs

### Test coverage

- α/β table load + fallback to default
- Hybrid score linearity: `0.5*dps + 0.5*ehp == 0.5*(dps + ehp)`
- Jarvan with bruiser build outscores Jarvan with pure tank build
- Jarvan with pure AD/AS build outscores Jarvan with pure tank build only when α > 0.5
- Per-champion α/β override works (set Riven 0.80 → AD items rank higher)
- ARAM mode multiplier flows through both component scores

### Future calibration (Phase 2.5 — deferred)

Once enough rewind_history.db data accumulates with hybrid-scorer outputs logged, calibrate α/β per champion per match outcome. Compare predicted ranking to actual item-buy-order success rate.

---

## Phase 3 — CS Scorer-Picker UI

**Single session. Pure UI work, depends on Phase 2 for the dual-scorer surfaces.**

### Files to edit

- `web/js/panels/champ_select.js` — new `#cs-archetype-picker` row in the My Pick card
- `web/css/panels/champ_select_view.css` — picker styling
- `web/js/main.js` — state.cs_archetype_pick wiring + persistence (localStorage key `rc-cs-archetype-<champion>`)
- `web/js/panels/dev.js` or new `in_game_archetype_tab.js` — in-game switch UI
- `dashboard/routes_state.py` — emit `state.cs_archetype_pick` in `/api/state` envelope
- `dashboard/_state_builder.py` — derive default from DDragon tags when no pick is set
- `coaches/aram_coach.py` + `arena_coach.py` + `brawl_coach.py` + `coach_integration/_coach.py` — read state.cs_archetype_pick, route to ds.dps / ds.ehp / ds.hybrid accordingly

### State shape

```json
{
  "cs_archetype_pick": {
    "champion": "Nunu",
    "primary": "tank",
    "secondary": "mage",
    "source": "user_cs",
    "set_at": "2026-05-12T14:30:00Z"
  }
}
```

`source` enum: `default` (from DDragon tags) · `user_cs` (explicit CS pick) · `user_ingame` (mid-match switch) · `nudge` (accepted first-purchase nudge).

### Invalidation events for secondary refresh

Pin these in `dashboard/_state_builder.py`:
1. `enemy_item_complete` — any enemy completes a build item (state event)
2. `self_item_complete` — operator completes a build item
3. `level_threshold_crossed` — operator hits 6/11/16/18

On any of these, mark the secondary scorer's cache as stale; next request recomputes.

### Soft-nudge: first-purchase mismatch

When state.cs_archetype_pick.primary = "tank" but operator buys a clear non-tank item (Liandry, Luden's, IE, etc.) in the first ~3 minutes, surface a one-time toast in the dashboard:

```
Looks like you're going AP — switch primary scorer to mage? [Yes] [No, keep tank]
```

Track shown count per match in localStorage so it never re-appears.

---

## Phase 4 — Mage Ability DPS Scorer

**Three sessions. Largest data lift. Splits naturally into 4a + 4b + 4c.**

### Phase 4a (session 1) — Meraki ability ingest

- Hit Meraki bulk endpoint (https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions.json) — same source as `tools/daemon_slayer_extract.py` already uses for items
- Parse champion `abilities` array; extract: cost, cooldown, damage formula (base + AP scaling + bonus AD scaling), damage type, area-of-effect flag
- Store in `data/daemon_slayer/<patch>/champion_abilities.json` — versioned alongside existing snapshot
- Coverage check: ~172 champions × 5 abilities (P/Q/W/E/R) = ~860 ability records; expect ~80% clean parse, ~20% manual schema patches
- New: `agents/daemon_slayer/abilities.py` data loader

### Phase 4b (session 2) — `compute_ability_dps()` scorer

- New file: `agents/daemon_slayer/ability_dps.py`
- Per-cast damage: resolve formula at current level + AP/AD/HP context (CallContext is reusable)
- Cast rate: extend `ult_rates.py` from ult-only to all 4 spells; derive from `rewind_history.db.participants.spell1_casts...spell4_casts` divided by `game_duration_s`
- Ability DPS per spell: `(damage_per_cast / cooldown) * uptime_factor` where uptime_factor handles mana economy + downtime
- Total: sum across all 4 spells, weighted by which spell scales primarily off AP/AD/HP for the champion

### Phase 4c (session 3) — `rank_items_by_ability_dps()` + tests + integration

- Mirror `rank_items` shape but score by `ability_dps_total` delta
- Wire `/rank-mage` route + `rank_mage_for()` client helper
- Tests: ~40 cases covering parse correctness, formula evaluation, item-AP-amp flow-through, ARAM mode amp, augments, dead-unique filter, mana economy edge cases
- Integration: ARAM coach and (future) SR mage path use `rank_mage_for()` when state.cs_archetype_pick.primary = "mage"

### Risk areas

- Meraki schema variations (some champions have unique fields: Aphelios, Jhin, Yasuo)
- Mana economy modeling — simple "mana-per-rotation / max-mana" denominator vs full Mana flow simulation
- Ability scaling beyond P/AP/Bonus AD (HP scalers, AP+Bonus AD hybrid, target max HP)
- Conditional damage (Ahri R-into-Q amplification, Zoe E-into-Q amplification) — model as `damage_amp_multiplier` per-champion or skip

---

## Phase 5 — Assassin Burst-Window Scorer

**Two sessions. Reuses Phase 4 ability data.**

### Concept

Assassins don't sustain DPS — they delete one target in a 1.5-2s window. Score by max damage in a single combo rotation: `Q → W → E → AA → R → AA` (or champion-specific sequence).

### Files

- New: `agents/daemon_slayer/burst.py` — `compute_burst_damage()` + `rank_items_by_burst()`
- Edits: existing infrastructure (server route, client helper, docs)

### Math

- Per-combo: sum ability damages assuming they all hit within the window
- Lethality scaling: at this point in `effective_target_armor`, apply lethality before % pen — fully modeled already
- Lethality vs armor below threshold: when target armor < lethality value, lethality bypasses 100% — track and surface as warning
- True damage components (Talon E true, Wukong R true) bypass all resists

### Champion list (~15)

Zed, Talon, Akali, Kha'Zix, Rengar, Fizz, Diana, Kassadin, Katarina, LeBlanc, Qiyana, Pyke, Naafiri, Briar, plus Yone burst-build variant.

---

## Phase 6 — Enchanter Healing Throughput

**Two sessions. Lowest fidelity tier — "good enough" is the bar.**

### Approach

- Score items by heal/shield amount per gold, against a "average teammate" model (avg ally HP pool = (4 × champion-baseline-HP-at-level), proximity = always-in-range)
- Items to model: Moonstone Renewer, Redemption, Mikael's Blessing, Helia, Ardent Censer, Staff of Flowing Water, Locket of the Iron Solari, Imperial Mandate, Knight's Vow
- Throughput per item: `(heal_amount_per_proc · procs_per_second) / item_gold`

### Limitations to document upfront

- No ally-state plumbing (positions, current HP, ability usage) — by design
- Single-target heals (Mikael's tap) scored as 1× throughput; AOE heals (Redemption ult) scored as 5× throughput
- Buff items (Ardent Censer AS to allies) get a flat "supportive value" credit, not a heal score
- Phase 6.5 candidate: actual ally-state plumbing via WebSocket → `state.allies[i].hp/mp/position` from liveclient

### Files

- New: `agents/daemon_slayer/hps.py` (~250 LOC)
- New: `data/daemon_slayer/<patch>/enchanter_items.json` — curated list of healing items with throughput formulas
- New: `agents/daemon_slayer/tests/test_hps.py` (~20 tests)
- Edits: server, client, docs

### Champion list (~10)

Lulu, Soraka, Janna, Karma, Sona, Yuumi, Nami, Seraphine, Renata Glasc, Senna (support variant), Maokai (support variant), Galio (support variant).

---

## Cross-phase concerns

### Bloat budget

Today: 13 files / ~5000 LOC / 955 tests in `agents/daemon_slayer/`. Projected end-of-Phase-6:
- 5 new scorer modules (ehp, hybrid, ability_dps, burst, hps) at ~200-400 LOC each
- 5 new test modules at ~200-400 LOC each
- Total: ~9000-11000 LOC / ~1700-1800 tests
- Test suite runtime: ~50-60s (today 13s) — still under the 60s timeout

### Coach prompt budget

Per memory `feedback_metric_provenance_tagging` and the s173.5 architecture spec: coach gets ONE primary scorer's output per tick. No prompt bloat from running all 6 in parallel.

### Calibration

Each scorer logs picks to `data/ds_calibration.jsonl` (existing infra, just extended with `scorer="ehp"` / `"hybrid"` etc. tag). After ~50 games per scorer, run Phase 7-style calibration analysis joining picks vs match outcomes.

### Backward compat

All new scorers default-on filter_shared_uniques (Phase 0 contract). Same dead-unique logic applies to EHP scorer (no item EHP-stacks an existing lifeline) and to ability scorer (no second Spellblade ability damage).

---

## Open design questions for next session start

These do NOT block Phase 1 but should be confirmed before scope finalizes:

1. **Phase 1 Option A vs B** — replace `core/defensive_picks.py` curated catalog, or layer it as a whitelist filter on `rank_items_by_ehp`?
2. **`ds.ehp` mode semantics** — does ARAM `aramDamageDealt` (which reduces damage taken in ARAM) apply to EHP calc? It's not actually `aramDamageDealt`; ARAM has a separate `aramDamageTaken` modifier. Verify the snapshot field name + apply if relevant.
3. **Where does scorer dispatch live?** Coach reads `state.cs_archetype_pick.primary` and chooses which `rank_*_for()` to call — should there be a dispatcher in `core/daemon_slayer_client.py` (e.g., `rank_for_primary_archetype(...)`) that abstracts the choice, or do coaches explicitly call the right one each time?
4. **Shield-throughput in Phase 1 vs 1.5** — Sterak's lifeline shield + Cinderhulk passive HP both feel EHP-relevant. Operator's call: include in Phase 1 or defer.

---

## Phase 0 (s173.5) — what shipped

For provenance and context:

- `agents/daemon_slayer/rank.py` — added `shares_dead_unique` + `dead_unique_key` fields to `RankedItem`; added `filter_shared_uniques: bool = True` parameter to `rank_items`; computed dead-unique flag in candidate loop BEFORE compute_dps call (saves work on default-filtered path); added 6 unit tests covering Trinity→ER, Sterak's→Maw, Sunfire→Hollow Radiance families.
- `agents/daemon_slayer/server.py` — `/rank` route forwards `filter_shared_uniques` from body (default true).
- `core/daemon_slayer_client.py` — RankedItem mirrors new fields; `rank_for()` exposes `filter_shared_uniques` param (default true).
- `agents/daemon_slayer/__init__.py` — ENGINE_VERSION 0.61.0 → 0.62.0.
- DS server restarted on Legion; `/health` confirms 0.62.0 live.
- Doc sync across CLAUDE.md / README.md / docs/DAEMON_SLAYER.md / docs/ARCHITECTURE.md / ROADMAP.md / BRIEF.md.
- Test counts: 949 → 955 in DS suite; 838 → 838 in main suite (unaffected).

The Phase 0 fix is operator-visible: when you have Trinity Force, ER will no longer appear in dashboard picks, coach prompts, or champ-select build chooser. To inspect the filtered candidates explicitly, pass `filter_shared_uniques=false` to `/rank`.

---

## How to start the next session

1. Run `/clear` to drop context
2. Bootstrap prompt for new session:

```
Read NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md. We're starting Phase 1
— Tank EHP scorer. Before writing any code, confirm decisions on the four open
design questions at the bottom of that doc. Then implement compute_ehp() +
rank_items_by_ehp() + integrate with core/defensive_picks.py per the chosen
option. Bump ENGINE_VERSION to 0.63.0; add tests; restart DS server; verify
via /health + Game-PC monitor 1 capture before reporting done.
```

3. Each subsequent phase: same pattern. Read the plan, confirm any open design questions, ship one phase per session, verify before reporting.
