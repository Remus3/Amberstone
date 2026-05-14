# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s190 wrap — 2026-05-13 (Phase 5.8 Sundered Sky Lightshield Strike in burst)

**Operator instruction:** "continue" — directly continuing the s189 carry-forward list. Top item: Sundered Sky Lightshield Strike (6610) — same "next AA after ability cast" mechanic as Spellblade but explicitly OUT of the spellblade unique-passive family. Single commit ship.

## Context

s189 closed the Spellblade gap in burst combos. Sundered Sky was carried forward because it carries a `PeriodicProc(name="Lightshield Strike", every_n_seconds=8.0)` — same arm-consume mechanic but with its own (intentionally absent) `unique_passive_key`. The schema comment at effects.py:539 spells it out: "Sundered Sky (6610) uses its own 'Lightshield Strike' label, not Spellblade — distinct mechanic, no dedup."

Two architectural decisions for this batch:
1. **Don't generalize** — second arm-consume helper, not an `is_ability_triggered_aa_proc` flag. Two items doesn't justify abstraction; if a third arm-consume mechanic ships, generalize then.
2. **Cap at 1 proc per combo** — Sundered Sky's real CD is 8s vs a typical 2-3s burst window. The cap is implicit: re-arming guards on `lightshield_procs_fired == 0`, so once the proc lands, subsequent ability casts in the same combo can't re-arm it. Spellblade's unlimited per-combo firing is correct because its 1.5s CD is well below combo length.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/dps.py](agents/daemon_slayer/dps.py) | New `LIGHTSHIELD_STRIKE_PROC_NAME = "Lightshield Strike"` constant + `_lightshield_strike_per_proc_damage()` helper (sibling of `_spellblade_per_proc_damage`). Filters by `proc.name == "Lightshield Strike"` rather than `unique_passive_key` because Sundered Sky has no dedup family. Returns `(per_proc_damage, item_name)` via the standard pipeline (`resolve_damage` → `_armor_factor` → mode → type-selective `magic_amp` for MAGIC only → `damage_amp`). `DpsResult` gains `lightshield_strike_per_proc_damage: float = 0.0` + `lightshield_strike_item_name: str = ""` fields; `to_dict()` carries them. `compute_dps` populates after the existing Spellblade block + emits a notes line when present. |
| [agents/daemon_slayer/burst.py](agents/daemon_slayer/burst.py) | Reads `aa_probe.lightshield_strike_per_proc_damage` + `aa_probe.lightshield_strike_item_name` alongside Spellblade. Combo walker gains parallel state vars `lightshield_armed` / `lightshield_procs_fired` / `lightshield_damage_total`. Ability token branch arms BOTH spellblade + lightshield, but lightshield arm is gated by `lightshield_procs_fired == 0` (8s CD cap). AA token branch consumes both independently — a build with both Sundered Sky + Trinity Force lands BOTH procs on the same AA. ComboCast AA notes block restructured to compose `base + on-hit + Spellblade + Lightshield Strike` parts; only present parts surface. `BurstResult` gains `lightshield_strike_procs: int = 0` + `lightshield_strike_damage: float = 0.0` + `lightshield_strike_item_name: str = ""` fields. Notes block reports fired count or idle state. |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | ENGINE_VERSION 0.74.0 → 0.75.0. Docstring extended with Phase 5.8 section (mirrors Phase 5.7 structure). |
| [agents/daemon_slayer/tests/test_lightshield_strike_burst.py](agents/daemon_slayer/tests/test_lightshield_strike_burst.py) | **NEW (~395 LOC, 28 tests).** Four classes mirroring s189's test_spellblade_burst.py structure. `LightshieldHelperTests` (8) — empty / non-lightshield / Sundered Sky returns 140 (20 + 2×60 base_ad) / armor mitigation / damage_amp / mode_multiplier / physical immune to magic_amp / independent of spellblade. `DpsResultLightshieldFieldsTests` (5) — naked = 0 / Spellblade-only = 0 lightshield / Sundered Sky surfaces / both items surface independently / to_dict. `BurstLightshieldIntegrationTests` (12) — naked / arms+fires once / capped at 1 per Q-AA-W-AA combo / pure AA combo / no AA combo / AA before spell / AA row carries Lightshield in final / Sundered Sky + TF stack on same AA / dual proc AA row carries both / Lightshield after fired doesn't re-arm / to_dict / Lightshield + Wit's End on-hit stack. `ServerBurstRouteLightshieldTests` (3) — naked / Sundered Sky surfaces / dual-proc build stacks (skipped when :8893 unavailable). |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Version-pin tests (Batch63 + Batch64) bumped 0.74.0 → 0.75.0 with the Phase 5.8 line in the history comment. |

## Verification

- DS suite **1605 pass** (was 1577 in s189 wrap; +28 from new test file)
- Wider RC suite **1013 pass** (no regression)
- `py_compile` clean for all 5 changed engine files
- DS server :8893 restarted from pid 12704 (s189 leftover) → pid 2968 (s190); `/health` reports `engine_version=0.75.0` patch=16.10.1

## Live A/B on :8893

**Aatrox lvl 11 vs 80 armor / 30 MR / 2000 HP (default combo Q-W-E-AA-R-AA, 2 AAs):**
- naked: 293.7 burst, AA 122.2
- +Sundered Sky (6610): 519.9 (+226), AA 305.6, LS=1× +133
- +Trinity Force (3078): 612.5 (+319), AA 406.7, SB=2× +244
- +TF + Sundered Sky: 838.7 (+545), AA 590.0, **SB=2× +244 AND LS=1× +133** — clean additive stacking

**Custom combo Q-AA-W-AA (2 AAs, 2 spell casts):**
- +Sundered Sky alone: LS=1× +133 (capped at 1 proc by 8s CD, confirms the gate works even with 2 eligible AAs)
- +Trinity Force alone: SB=2× +244 (no cap, fires on every armed-AA transition)
- +TF + Sundered Sky: SB=2× +244 AND LS=1× +133 (still independent state machines)

Math check: dual-item burst 838.7 - 293.7 = +545 = (Sundered Sky alone +226) + (TF alone +319) exactly. Confirms zero overlap; both procs land independently on the AA following the first ability cast.

## Findings

- **Helper sourced by proc-name, not item-id.** Sundered Sky has no `unique_passive_key`, so the helper filters on `proc.name == "Lightshield Strike"` instead. More future-proof — a future item adding a Lightshield Strike variant would auto-match. Trade-off: relies on the proc name string staying stable across patches (which it has for years).
- **Re-arming gate keeps the model simple.** Initial design considered tracking elapsed combo time + comparing against the 8s CD, but that requires a combo-timing model the engine doesn't have. The gate `if lightshield_procs_fired == 0: armed = True` produces correct behavior for typical bursts without needing time accounting.
- **Combined-build math validates the architecture.** Dual-item AA row's `final_damage` exactly equals `avg_attack_dmg + spellblade_per_proc + lightshield_per_proc` from the matched-build `compute_dps` probe. No double-counting, no overlap drift. The `test_dual_proc_aa_row_carries_both` test guards this invariant.
- **PowerShell `$pid` gotcha.** PowerShell reserves `$pid` as read-only (it's the current process's PID). The DS-restart command failed silently when I tried to assign to it; eventually killed a phantom PID 17580 (probably my own test runner). Renamed to `$proc` for the restart. Logged to memory.

## Open items carried forward

- 🟡 **Real internal CD in long combos.** Lightshield Strike still uses the implicit "once per combo" gate. An 8+ token combo lasting >3s might in theory permit a second proc (real CD 8s — still wouldn't fit a typical burst, but conceptually). Same edge case as s189's Spellblade CD handling.
- 🟡 **Conditional damage amps (Ahri R→Q, Zoe E→Q, Akali R1→QE→R2).** Inter-spell awareness still missing — burst is computed as additive single-spell hits. Carried since s180.
- 🟡 **Generalized arm-consume framework.** Two specific helpers now in the engine (`_spellblade_per_proc_damage` + `_lightshield_strike_per_proc_damage`). If a third arm-consume mechanic ships, generalize to `is_ability_triggered_aa_proc: bool` schema field at the PeriodicProc level rather than adding a third helper. Tracked but not pursued this batch.
- 🟡 **Pre-existing carry-forwards from s189:** Aphelios upstream data gap, Karma mantra runtime plumbing, Khazix evolved-form choice, live-game chip lifecycle validation, audit finding #1 frozen-file list duplication.

## Architectural pattern lock-in (continued from s189)

Sixth consecutive override / proc-shape modeling improvement on the same template (s185 max_priority / s186 combo_sequence / s187 form_index / s188 per-AA on-hit / s189 Spellblade-in-burst / s190 Lightshield-in-burst). Each shipped backend-first with live A/B verification before commit; each added per-item or per-champion-derived modeling without breaking backward-compat (default field values preserve pre-batch behavior).

---

# s189 wrap — 2026-05-13 (Phase 5.7 Spellblade-in-burst — armed by ability cast, consumed by next AA)

**Operator instruction:** "continue ds" — direct continuation of s188's deferral list. Top item: Spellblade CD modeling. Single commit ship.

## Context

s188 added `DpsResult.per_attack_on_hit_damage` and wired it into `burst.py` so each AA token in a combo picks up Wit's End / BotRK / Statikk contributions. The s188 hand-off claimed "Triforce/Lich Bane currently amortized as 1/N per AA via `every_n_attacks=N` schema" — but on re-reading effects.py this turned out to be **wrong**: Spellblade items use `every_n_seconds=3.0` (TF/LB/ER/IBG/Divine Sunderer) or `1.5` (Dusk+Dawn / Sheen / Bloodsong), and `_per_attack_proc_damage` explicitly **skips** time-based procs (`if proc.every_n_attacks <= 0: continue`). So in s188-era burst, Spellblade items contributed **zero** to AA damage — a bigger gap than the hand-off suggested.

The fix model: Spellblade fires once per ability-then-AA transition in a combo. Walk the combo with a `spellblade_armed: bool` flag — any ability token sets armed=True; AA token consumes (armed → fire proc → armed=False). Real 1.5s internal CD is irrelevant in a single-combo window because the arming gate is binding (a fresh spell-cast is required to re-arm). Same architectural decision pattern as s180's combo modeling — no cooldown sequencing within the window.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/dps.py](agents/daemon_slayer/dps.py) | New `_spellblade_per_proc_damage()` helper (sibling of `_per_attack_proc_damage`) iterates `item_effects`, finds the build's `unique_passive_key=="spellblade"` item (already deduped by `collect_effects` — at most one survives), evaluates the per-proc damage through the standard pipeline (`resolve_damage(call_ctx)` → `_armor_factor(armor/mr)` → `mode_dmg_mult` → type-selective `magic_amp` for MAGIC only → `damage_amp`). Returns `(per_proc_damage, item_name)`. `DpsResult` gains `spellblade_per_proc_damage: float = 0.0` + `spellblade_item_name: str = ""` fields with full `to_dict()` coverage. `compute_dps` populates both after the existing `per_attack_on_hit_damage` block; surfaces a `notes` line when Spellblade is present so /dps clients can see the per-proc value. |
| [agents/daemon_slayer/burst.py](agents/daemon_slayer/burst.py) | Reads `aa_probe.spellblade_per_proc_damage` + `aa_probe.spellblade_item_name` after the existing per-attack on-hit probe. Combo walker tracks new state vars `spellblade_armed: bool` / `spellblade_procs_fired: int` / `spellblade_damage_total: float`. Ability token branch sets `spellblade_armed = True`. AA token branch checks armed + per-proc>0; on hit, adds the proc damage to that ComboCast's `final_damage` (and `raw_damage` / `post_mode_damage` / `post_amps_damage` — already-mitigated value, mirrors how `aa_per_hit` is treated), resets armed, increments counter. `BurstResult` gains `spellblade_procs: int = 0` + `spellblade_damage: float = 0.0` + `spellblade_item_name: str = ""` fields; `to_dict()` carries them. Notes block now reports `Spellblade (Name) fired Nx in combo for +D damage`, or `Spellblade (Name) idle in combo — no AA followed an ability cast` when the build has Spellblade but the combo template doesn't exercise it. |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | ENGINE_VERSION 0.73.0 → 0.74.0. Docstring tail expanded with the Phase 5.7 explainer (combo walker arms Spellblade, AA consumes; 1.5s internal CD irrelevant in single-combo window per the s180 architectural pattern). |
| [agents/daemon_slayer/tests/test_spellblade_burst.py](agents/daemon_slayer/tests/test_spellblade_burst.py) | **NEW (~480 LOC, 32 tests).** Four classes. `SpellbladeHelperTests` (10) — direct exercise of `_spellblade_per_proc_damage`: empty effects / non-Spellblade build / TF returns 2.0×base_ad physical / TF armor mitigation / LB uses MR for magic / LB magic_amp applies / TF magic_amp does NOT apply to physical / damage_amp applies uniformly / mode_multiplier applies / dedup takes first Spellblade in build. `DpsResultSpellbladeFieldsTests` (5) — `compute_dps` end-to-end: naked = 0, per-attack-only items = 0 (sanity, s188 unchanged), TF surfaces, LB surfaces, `to_dict` carries fields. `BurstSpellbladeIntegrationTests` (14) — `compute_burst_damage` combo walker: naked zero / TF arms+fires / Q-AA-W-AA fires twice / Q-W-E-AA fires once / AA-Q-AA fires once / no-AA combo / only-AA combo / AA row picks up Spellblade in `final_damage` / Zed default-combo gets 1 proc / Essence Reaver in Talon / Divine Sunderer in Zed / dedup keeps one Spellblade in build / Spellblade + Wit's End both contribute / `to_dict` carries fields. `ServerBurstRouteSpellbladeTests` (2) — `/burst` route surfaces fields; skipped gracefully when :8893 unavailable. |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Version-pin tests (Batch63 + Batch64) bumped 0.73.0 → 0.74.0 with Phase 5.7 line in the history comment. |

## Verification

- DS suite **1577 pass** (was 1545; +32 new test file)
- Wider RC suite **1013 pass** (no regression)
- `py_compile` clean for dps.py + burst.py
- DS server :8893 restarted from pid 16324 → pid 12704; `/health` reports `engine_version=0.74.0`, patch=16.10.1, 172 champions, 705 items

## Live A/B on :8893

**Akali lvl 11 vs 80 armor / 30 MR / 2000 HP (combo Q-AA-E-R-Q2-AA-R2, 2 AAs eligible):**
- naked total_burst: 787.9
- +Trinity Force (3078): 1111.0 (+323), spellblade_procs=2, spellblade_damage=211.1
- +Lich Bane (3100): 1138.2 (+350), spellblade_procs=2, spellblade_damage=186.5 (AP scaling wins for Akali)
- +Essence Reaver (3508): 1119.5 (+332), spellblade_procs=2, spellblade_damage=145.8

**Zed lvl 11 vs 80 armor / 30 MR / 2000 HP (combo Q-W-E-R-Q2-AA, 1 AA from s186 registry):**
- naked total_burst: 413.3, AA=53.9
- +Trinity Force: 617.1 burst, AA=181.7, spellblade_procs=1 (+107.8)
- +Divine Sunderer: 654.0 burst, AA=210.1, spellblade_procs=1 (+134.0 — beats TF because target_max_hp scales the 6% modifier)
- +Sheen: 467.2 burst, AA=107.8, spellblade_procs=1 (+53.9 — cheapest spellblade, 1.0×base_ad)

**`/rank-assassin` shift on Zed (top 10):**
- Pre-s189 wrap (s180): Essence Reaver +203.6 at #5; Trinity Force outside top 10.
- Post-s189: **Essence Reaver +223.0 at #2** (#1 Infinity Edge +225.1); **Trinity Force +203.8 at #7**.
- Lethality + armor-pen still dominate top tier — Spellblade items climb but don't overtake (correct — Zed's combo has only 1 AA, so 1 Spellblade proc vs 5 ability casts × lethality).

## Findings

- **The s188 hand-off was inaccurate about the Spellblade schema.** Re-reading effects.py showed Spellblade items use `every_n_seconds` not `every_n_attacks`, which means the s188 `_per_attack_proc_damage` was skipping them entirely. The wider lesson: when a hand-off references schema details, verify against current code before designing a fix on top of it. The fix here is bigger-impact than the deferral text suggested — building TF on Akali pre-s189 contributed only the stat block; post-s189 the Spellblade adds 200+ extra burst per combo.
- **`unique_passive_key="spellblade"` is the right dedup signal.** All 8 SR Spellblade items + 6 Arena mirrors + Sheen + Bloodsong share the key. `collect_effects` first-seen-wins keeps the engine deterministic when operator builds two Spellblade items (rare but legal in beam search). The helper iterates `item_effects` (already deduped) so it returns at most one Spellblade per build.
- **AA row's `final_damage` carries the Spellblade contribution.** No sibling field on `ComboCast` for the Spellblade portion — keeps the per-cast row's `final_damage` as the canonical "damage this step contributed", consistent with the s188 pattern where on-hit goes straight into the AA total. Verified via `test_aa_row_includes_spellblade_in_final_damage`: AA row equals `compute_dps.avg_attack_dmg + compute_dps.spellblade_per_proc_damage` from a matched-build probe.
- **Test bug caught at first run:** initial `test_aa_row_includes_spellblade_in_final_damage` compared naked-AA vs TF-AA and asserted the delta equals the Spellblade per-proc value. The delta was off by ~20 because TF adds AD (+25), so the AA base damage also grew. Fixed by comparing the TF-AA row against `(naked-AA + spellblade) of THE SAME BUILD's probe` — single-build apples-to-apples.
- **Idle Spellblade note added.** When the build has TF but the operator passes `combo_sequence=("AA","AA","AA")` (no ability tokens), the engine surfaces a "Spellblade (Trinity Force) idle in combo — no AA followed an ability cast" note. Useful diagnostic for operators experimenting with custom combo templates that fail to exercise the passive.

## Open items carried forward

- 🟡 **Sundered Sky Lightshield Strike (6610).** Same "next AA after ability cast" mechanic but with `unique_passive_key="lightshield_strike"` (separate from "spellblade"). Out of scope this batch — needs its own helper or a generalized `is_ability_triggered_aa_proc` flag. Single-item lift if added.
- 🟡 **Real Spellblade CD in long combos.** Current model ignores the 1.5s internal CD because typical 6-token combos run <2s. Edge case: a slow 8-token combo with multiple AA-after-spell transitions might over-count Spellblade procs. Tighter model would track combo elapsed time, but the engine has no per-token timing right now.
- 🟡 **Pre-existing carry-forwards from s188:** Aphelios upstream data gap, Karma mantra runtime plumbing, Khazix evolved-form choice, conditional damage amps (Ahri R→Q, Zoe E→Q), live-game chip lifecycle validation, calibration knob retune, audit finding #1 frozen-file list duplication.

## Architectural pattern lock-in (continued from s188)

Five consecutive override / proc-shape registries (s185 max_priority / s186 combo / s187 form_index / s188 per-AA on-hit / s189 Spellblade-armed) all ship on the same template:
- JSON sibling or in-effects schema declaration
- Helper function exposing `(value, source)` or `(damage, name)` tuple
- Result-type field surfaced in `to_dict()`
- Backward-compat preserved by defaulting to "no contribution"
- Live A/B comparison demonstrating the new modeling is load-bearing

The DS engine now ships with reliable scoring for all 6 archetype dispatcher paths × the s185-s189 modeling improvements. Coach-side dispatch (s182) and dashboard JS (s183) auto-pick up new fields via `to_dict()` shape — no UI changes required this batch.

---

# s188 wrap — 2026-05-13 (DDragon 16.10.1 refresh + per-champion DS override registries — 5 commits da67555..9953c23 covering s185/s186/s187/s188)

**Operator instruction:** "CONTINUE DS" → "continue" × 4. Single long session covering one DS data refresh + four registry-pattern follow-ups to the s174-s181 archetype-expansion plan. All shipped backend-first with live `/health` + ranker verification before commit.

## Ships

| Commit | Slot | Topic |
|---|---|---|
| [da67555](https://github.com/Remus3/riot-commander/commit/da67555) | data refresh | DS engine data `16.9.1 → 16.10.1` (re-extract via `tools/daemon_slayer_extract.py` + `tools/daemon_slayer_abilities_extract.py`; copied hand-curated `enchanter_items.json` forward; flipped `current.txt`). Doran's Bow 6→8 AD, Doran's Helm 110→140 HP, Gluttonous Greaves rebalanced 650g→700g + 1%/6→0.6%/10. Arena augments 219→220. |
| [d0c604b](https://github.com/Remus3/riot-commander/commit/d0c604b) | s185 Phase 4d | New [champion_max_priority.json](agents/daemon_slayer/champion_max_priority.json) — 12 entries (Cassiopeia/Kayle/Akali/Kassadin/Rumble/Anivia → E-Q-W; TwistedFate/Leblanc/Heimerdinger/Lillia → W-Q-E; Karthus/Vladimir → Q-E-W). Resolver in `ability_dps.py`; consumed by mage + assassin scorers. Result types gain `max_priority_source`. ENGINE 0.69.0 → 0.70.0. Cassi lvl 9 baseline +40% (17.82 → 25.08 adps). |
| [e8a9a1e](https://github.com/Remus3/riot-commander/commit/e8a9a1e) | s186 Phase 5.5 | New [champion_combo_sequences.json](agents/daemon_slayer/champion_combo_sequences.json) — 15 entries for all 14 canonical assassins + Briar. Zed → Q-W-E-R-Q2-AA (shadow); Yone → Q-Q2-Q3-AA-E-W-R; Akali → Q-AA-E-R-Q2-AA-R2; Leblanc → R-mimic-Q. Loader in `burst.py`. Result types gain `combo_sequence_source`. ENGINE 0.70.0 → 0.71.0. Zed baseline +24% (333.89 → 413.33 burst). |
| [b48ff97](https://github.com/Remus3/riot-commander/commit/b48ff97) | s187 Phase 4e | New [champion_form_index.json](agents/daemon_slayer/champion_form_index.json) — 5 entries: Nidalee Q/W/E → 1 (cougar); Elise Q → 1 (Venomous Bite); Jayce Q → 1 (Shock Blast); Hwei Q/W/E → 1/3/1 (first damage-bearing form per key); LeeSin Q → 1 (Resonating Strike). Resolver merges caller dict with registry per-key. Both scorers + result types updated. ENGINE 0.71.0 → 0.72.0. Hwei DPS collapses 11.95 → 0.02 when forced to form 0 (the `Subject:` stance setups carry zero damage blocks). |
| [9953c23](https://github.com/Remus3/riot-commander/commit/9953c23) | s188 Phase 5.6 | New `dps._per_attack_proc_damage()` + `DpsResult.per_attack_on_hit_damage` field. burst.py's `aa_per_hit = base + on-hit`. Wit's End / BotRK / Statikk / Spellblade now land in assassin item rankings. ENGINE 0.72.0 → 0.73.0. Akali +Wit's End AA contribution +82 (105.6 → 187.5); Zed +BotRK AA contribution +111 (53.9 → 165.0). |

## Verification

- DS suite        **1545 pass** (was 1426 at session start; +119 from s185/s186/s187/s188 new test files)
- Wider RC suite  **1013 pass** (no regression across all 5 commits)
- DS server :8893 restarted 5×; `/health` reports 0.73.0 + patch 16.10.1 + 172 champions + 705 items
- Each registry shipped with live A/B comparison demonstrating the override is load-bearing (e.g. Hwei drops to 0.02 DPS without form_index override — confirms form 0 is unparseable stance metadata)

## Open items carried forward

- 🟡 **Aphelios data gap.** All 6 Q forms in Meraki bulk show `parse_status=no_damage`; the per-weapon damage formulas aren't ingested. Blocked on upstream Meraki update — DS can't score Aphelios abilities until then.
- 🟡 **Karma mantra runtime plumbing.** Karma form 1 is mantra-amped; defaulting to it would over-count (mantra is a player-choice mid-combat). Needs `state.lcu.mantra_active` or similar to switch dynamically.
- 🟡 **Khazix evolved-form choice.** Same shape — evolved Q/W/E/R is a per-game decision. Could expose as a champ-select picker UI later.
- 🟡 **Spellblade CD modeling (s188 deferral).** Triforce/Lich Bane currently amortized as 1/N per AA via `every_n_attacks=N` schema; a tighter model would count one proc per spell-cast in the combo gated on 1.5s CD.
- 🟡 **Conditional damage amps for burst (carried since s180).** Ahri R→Q, Zoe E→Q, Akali R1→QE→R2 amps — inter-spell awareness still missing.
- 🟡 **Pre-existing carry-forwards from s184/s183/s182** all remain unchanged: live-game chip lifecycle validation pending CS pop; `_TOP_N_THRESHOLD` retune blocked on real-game fired nudges; `nudge_history` calibration additive.

## Architectural pattern lock-in

Four consecutive override registries (s185/s186/s187/s188) shipped on the same template, now a stable engine pattern: JSON sibling to `archetype_weights.json` in `agents/daemon_slayer/` + lazy-cache singleton loader + `get_X_for(champion_id) -> (value, source)` resolver + `_resolve_X(champion_id, explicit) -> (value, source)` merger + result-type `X_source: str` field surfaced in `to_dict()` + server route returns `Optional`. Future per-champion overrides (combo dynamic amps, cooldown gates, runtime form switches) drop into this template. Verified by 5 successive commits passing the same DS regression suite with no test fragility.

## DDragon vs DS data split

Confirmed during the s184.1 → 16.10.1 refresh: DDragon meta (`data/meta/ddragon_*.json`) and DS engine snapshot (`data/daemon_slayer/<patch>/`) are independent. The auto `RC-PatchRefresh` task refreshes DDragon meta only; DS refresh is a manual `daemon_slayer_extract.py` invocation per patch.
