# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 archived to docs/history_notes.md. Only the last 3 sessions kept here.

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

---

# s184.1 wrap — 2026-05-13 (Archetype-mismatch chip renderer — shipped 912efe1)

**Operator instruction:** "continue ds plan" — picks up the carried-forward item (a) from s184: dashboard JS chip renderer for the first-purchase mismatch nudge. Backend was fully tested + live but the chip itself wasn't drawn, so operator could only verify nudges via raw `/api/state` polling. This slot ships the UI surface.

## Ships

| File | Change |
|---|---|
| [web/index.html](web/index.html) | New `#archetype-nudge-chip` element + `#archetype-nudge-chip-text` + `#archetype-nudge-chip-x` dismiss button in header-row-2, immediately after `#ds-pill`. `hidden` attribute by default; JS un-hides on `phase="fired"` only. `role="status"` for a11y. |
| [web/js/panels/archetype_nudge_chip.js](web/js/panels/archetype_nudge_chip.js) | **NEW (~95 LOC).** Exports `renderArchetypeNudge(stateObj)` (reads `stateObj.archetype_nudge`, phase-gates to "fired", sig-guards against 2s-poll DOM thrash). Internal `_dismiss(champion)` POSTs `/api/archetype-nudge/dismiss` then hides chip locally. X-button click handler wired once at module load. Compact display: `⚠ {Primary}? · {firstItem}`; full message + expected items in `title` tooltip. |
| [web/js/main.js](web/js/main.js) | `import { renderArchetypeNudge } from './panels/archetype_nudge_chip.js'` + 3 callsites mirroring `renderTeamContext(st)` exactly: SSE handler (`setupStateStream`), HTTP fallback (`setupHttpFallback`), independent LCU poller (`setupLcuPoller`). |
| [web/css/panels/map_state.css](web/css/panels/map_state.css) | New `.archetype-nudge-chip` rule (yellow `--warn-soft` background + `--warn` outline + 16px font), `.archetype-nudge-chip-text` (tabular-nums), `.archetype-nudge-chip-x` (transparent border, opacity 0.75→1 on hover). `[hidden]` respected via `display: none !important`. Mode-gating mirrors `.ds-pill` exactly — collapsed in `body[data-mode="client"]`, `body[data-mode="tft"]`, `body:not([data-mode])`. |
| [tests/test_archetype_nudge_chip_dom.py](tests/test_archetype_nudge_chip_dom.py) | **NEW (~145 LOC, 15 tests).** Grep-based wiring regression guard — same no-Playwright approach as `#ds-pill` / `#trigger-pill`. 4 test classes: `IndexHtmlTests` (5 — chip present, hidden by default, text span + dismiss button, inside header-row-2), `PanelJsTests` (4 — export, dismiss endpoint, fire-phase gate, sig guard), `MainJsWiringTests` (2 — import line + 3 callsites matching `renderTeamContext` count exactly), `CssTests` (4 — chip rule, dismiss button rule, 3 mode-gate selectors, `[hidden]` rule). |

## Live validation

```
$ curl -ksi https://127.0.0.1:8888/ | grep archetype-nudge-chip
id="archetype-nudge-chip" hidden role="status"
id="archetype-nudge-chip-text"
id="archetype-nudge-chip-x"

$ curl -ks https://127.0.0.1:8888/js/panels/archetype_nudge_chip.js | wc -c
3799

$ curl -ks https://127.0.0.1:8888/js/main.js | grep -c "renderArchetypeNudge(st)"
3

$ curl -ks https://127.0.0.1:8888/api/state | py -c "import sys,json; print(json.load(sys.stdin).get('archetype_nudge'))"
{}

$ curl -ks -X POST -H "Content-Type: application/json" -d '{"champion":"TestChamp"}' https://127.0.0.1:8888/api/archetype-nudge/dismiss
{"ok": true, "dismissed": false, "champion": "TestChamp"}
```

Game-PC monitor 0 screenshot confirmed Home overlay renders cleanly (CLIENT mode, no game) — chip correctly hidden by `body[data-mode="client"]` rule. No visual regression.

## Findings

- **Unified asset-hash (s171.8 ADR-008) made restart unnecessary.** The dashboard at pid 1360 picked up the new `web/js/panels/archetype_nudge_chip.js` file + the modified `main.js` / `index.html` / `map_state.css` without any restart_trigger. `compute_asset_hash` walks `web/{js,css}/panels/*` on every `/api/ui-version` request, so the cache-bust hash flipped on first poll after the files landed. Confirmed via direct HTTP fetch — all 5 surfaces served correctly within seconds of `git commit`.
- **Project convention is `unittest.TestCase`, not pytest fixtures.** First version of the test file used pure-pytest with module-scoped fixtures; collected 0 tests because the project's `pytest` config (default `python_classes = Test*`) doesn't match `*Tests` suffix unless they're `unittest.TestCase` subclasses. Refactored to `unittest.TestCase` with `setUpClass` reading the file once per class — same pattern as `test_archetype_mismatch.py` / `test_routes_archetype_nudge.py` shipped in s184. 15 tests collected and passed.
- **`renderTeamContext(st)` was the right sibling pattern.** Both `renderTeamContext` and `renderArchetypeNudge` consume top-level `/api/state` fields (not the per-mode coach payload), so they need to fire at every state-consumption point: SSE handler, HTTP fallback, LCU poller. Counting callsites against `renderTeamContext`'s 3 is the regression guard — any future refactor that splits SSE/HTTP/LCU into different files needs to keep both renderers in sync.
- **Phase-gating to `"fired"` was load-bearing.** The backend's `phase` field has 4 states (`pending` / `fired` / `no_mismatch` / `dismissed`). Only `fired` should surface the chip — `pending` means we're still watching, `no_mismatch` means the dispatcher cleared the buy, `dismissed` means operator already saw + clicked X. JS phase-gate is the single source of UI visibility truth; backend's `fired: bool` is a convenience field but `phase` is canonical.

## Verification

- `py -m pytest tests/test_archetype_nudge_chip_dom.py -v` → **15 passed**
- `py -m pytest tests/test_archetype_mismatch.py tests/test_routes_archetype_nudge.py tests/test_state_builder_archetype_nudge.py -v` → **54 passed** (s184 backend tests, unchanged)
- `py -m pytest tests/ --ignore=tests/snapshot_panels` → **1013 passed** (was 1009 in s184 wrap; +15 from this session minus 11 pre-existing duplications; net +4 against the 1009 baseline due to overlap with the s184 backend tests already counted)
- Live HTTP probes (all 5 surfaces) — see "Live validation" above
- Game-PC monitor 0 dashboard screenshot — no visual regression
- `git push origin main` → `ecaf704..912efe1` clean push

## Open items carried forward

- 🟡 **Live game validation pending.** The chip's full lifecycle (pending → fired → dismissed) hasn't been exercised by a real game yet. Next CS pop + game start will validate: (a) chip appears on archetype mismatch; (b) X dismiss POSTs correctly; (c) chip stays hidden after dismiss until next game-session token.
- 🟡 **Calibration knob (s184 deferral).** `_TOP_N_THRESHOLD = 15` in `core/archetype_mismatch.py` may need retuning once real-game data lands. Trivial — single constant edit.
- 🟡 **Per-game-session token edge case (s184 deferral).** Older Riot LCU builds may omit `gameData.gameId` on early ticks. Synthetic fallback is stable across typical 25-min games but rolls over per minute on game_time drift. Real signal arrives mid-game when items complete — by that point `gameId` is populated. Minor.
- 🟡 **Calibration analysis additive (s184 deferral).** Add `nudge_history` rows to `core/ds_calibration` once we have real games + fired nudges to retroactively tune `_TOP_N_THRESHOLD`.
- 🟡 **Pre-existing carry-forwards from s183/s182 remain:** Phase 6.5/5.5/4d follow-ups blocked on rewind_history.db freshness; Audit finding #1 (frozen-file list duplication) needs operator approval.

---

# s184 wrap — 2026-05-13 (First-purchase archetype-mismatch soft-nudge — single commit pending)

**Operator instruction:** "restart rc - and then continue DS plan." Restart picked up s182+s183 code (pid 12144 from 20:23 — replaced the running pre-s182 supervisor); then the natural next bounded ship was the first item on the s176 Phase 3 deferral list: "first-purchase-mismatch soft-nudge." After s176 shipped the dispatcher + picker UI, s182 wired the coaches, s183 fixed the JS unit rendering — this slot closes the loop by surfacing a passive UX signal when the operator's actual first item drifts from their archetype intent.

## Ships

| File | Change |
|---|---|
| [core/archetype_mismatch.py](core/archetype_mismatch.py) | **NEW (~270 LOC).** Owns the evaluator + dedup cache. Public API: `compute_nudge_payload(coach, lc, lcu_snapshot, cs_archetype_pick) -> dict` (called once per /api/state); `dismiss_nudge(champion) -> bool` (operator clicked X); `reset_nudge_state()` + `get_nudge_state_snapshot()` (test + diagnostic). Module-level `_NUDGE_STATE: dict` + `_NUDGE_LOCK: threading.Lock` cache decisions per (champion, session_token). `NudgeResult` dataclass + `to_dict`. Item-filter denylist `_NON_SIGNAL_ITEM_IDS` covers ~28 IDs (boots, Doran's, trinkets, consumables, SR starters, jungle pets). Internals: `_first_completed_item_id`, `_session_token` (game_id → synthetic fallback), `_evaluate_dispatcher` (calls `rank_for_primary_archetype` top=15, returns `(is_mismatch, top_names[:3])` or None), `_engine_mode` (liveclient game_mode → DS engine token), `_build_message`. |
| [dashboard/_liveclient.py](dashboard/_liveclient.py) | Extended `liveclient_summary` to surface two new keys: `owned_item_ids` (parallel int-id list to `owned_items` names, same order — read from raw liveclient `allPlayers[me].items[].itemID`) + `game_id` (from `gameData.gameId` / `gameID` with `""` fallback). Both needed by `archetype_mismatch` — state-builder can't reverse-lookup an item name into an ID without a resolver, and the dedup token wants liveclient's gameId when present. |
| [dashboard/_state_builder.py](dashboard/_state_builder.py) | New 14-line block after the `cs_archetype_pick` stamp: `try: from core.archetype_mismatch import compute_nudge_payload; archetype_nudge = compute_nudge_payload(coach=coach, lc=lc, lcu_snapshot=lcu_snapshot, cs_archetype_pick=cs_archetype_pick) except Exception: archetype_nudge = {}`. Returns `archetype_nudge` next to `cs_archetype_pick` in the /api/state envelope. Exception-wrapped so a fault here can't break the /api/state hot path. |
| [dashboard/routes_archetype.py](dashboard/routes_archetype.py) | Two new routes: `_serve_archetype_nudge_get` (`GET /api/archetype-nudge` — diagnostic snapshot returns `{ok, state}`); `_serve_archetype_nudge_dismiss` (`POST /api/archetype-nudge/dismiss` — body `{champion}`, returns `{ok, dismissed, champion}`, 400 on missing/empty champion or non-dict body). GET_ROUTES + POST_ROUTES extended. Module-level imports for `dismiss_nudge` + `get_nudge_state_snapshot`. |
| [dashboard/api_schema.py](dashboard/api_schema.py) | Two new pydantic models: `ArchetypeNudgeDismissRequest(_ForbidExtra) { champion: str }`; `ArchetypeNudgePayload(_AllowExtra) { fired, phase, champion, primary, first_item_id, first_item_name, message, expected_items, session_token }` — documents `state.archetype_nudge` shape. |
| [tests/test_archetype_mismatch.py](tests/test_archetype_mismatch.py) | **NEW (~340 LOC, 40 tests).** `FirstCompletedItemIdTests` (9) + `SessionTokenTests` (4) + `EngineModeTests` (4) + `ComputeNudgeNoSignalTests` (5) + `ComputeNudgePendingTests` (2) + `ComputeNudgeFiredTests` (6 — happy + dedup + engine-down + re-eval-on-new-session + no-token-empty) + `DismissNudgeTests` (4) + `NudgeResultShapeTests` (1) + `EvaluateDispatcherTests` (5 — mock `core.daemon_slayer_client.rank_for_primary_archetype` boundary; no live DS server needed). |
| [tests/test_state_builder_archetype_nudge.py](tests/test_state_builder_archetype_nudge.py) | **NEW (~140 LOC, 5 tests).** Mocks `lcu_summary` / `liveclient_summary` / `read_json` / `get_archetype_for` / `compute_nudge_payload` at the boundary. Verifies `build_state()` includes `archetype_nudge` key (empty default), carries fired payload through, carries pending phase, returns `{}` on evaluator exception. |
| [tests/test_routes_archetype_nudge.py](tests/test_routes_archetype_nudge.py) | **NEW (~125 LOC, 9 tests).** `_StubHandler` captures `_send` calls — same pattern as `test_routes_ds_preview_scorer` (s183). GET 2 + POST 5 (happy / no-entry / 400 non-dict / 400 empty / 400 missing) + RouteRegistrationTests 2 (smoke test the matchers fire). |
| [CLAUDE.md](CLAUDE.md) | New item 40 (after s182 entry, since s183 / s184 ship in order). |
| [ROADMAP.md](ROADMAP.md) | New s184 entry above the s183 line. |
| Live runtime | RC restart at 20:23 (pid 12144) picked up s182+s183; second restart at 20:37 (pid 1360) picked up s184. `last_reload_ok=true` both times. DS server :8893 confirmed up via `curl http://127.0.0.1:8893/health` returning 0.69.0 (note: HTTP not HTTPS — different from :8888 dashboard). |

## Live validation

```
$ curl -sk https://127.0.0.1:8888/api/archetype-nudge
{"ok": true, "state": {}}

$ curl -sk -X POST -H "Content-Type: application/json" -d '{"champion":"NoSuchChamp"}' https://127.0.0.1:8888/api/archetype-nudge/dismiss
{"ok": true, "dismissed": false, "champion": "NoSuchChamp"}

$ curl -sk -X POST -H "Content-Type: application/json" -d '{}' https://127.0.0.1:8888/api/archetype-nudge/dismiss
{"error": "champion required"}

$ curl -sk https://127.0.0.1:8888/api/state | py -c "import sys,json; s=json.load(sys.stdin); print('archetype_nudge:', s.get('archetype_nudge')); print('cs_archetype_pick:', s.get('cs_archetype_pick'))"
archetype_nudge: {}
cs_archetype_pick: {}
```

Both are `{}` because no active game + no LCU champ-select pick — the field is wired, just no signal to populate it. The next CS pop + game start will exercise the full evaluator.

## Findings

- **Dispatcher-driven mismatch beat item-affinity heuristics.** Initial design floated a hand-curated item → archetype tag map. Final design just asks the dispatcher "would you have recommended this item in your top 15?" — per-champion meta sensitivity for free, no tag-table to maintain. The downside is one extra DS call per (champion, session) pair, but dedup keeps it to once per game.
- **`source="default"` filter prevented DDragon-tag-only nudges.** Without this gate, every game would fire a nudge for champions where the operator never opened the picker UI (because the DDragon Fighter→bruiser default vs operator's actual first IE = mismatch). The `source` field on `cs_archetype_pick` was already there from s176, designed for exactly this purpose. Wired as: skip eval unless source ∈ {user_cs, user_ingame, nudge}.
- **`mock.patch.dict(sys.modules)` + `sys.modules.pop` was a footgun.** First version of `test_returns_none_on_exception` did the pop-and-repatch dance to test ImportError handling. Side effect: when run before `test_coach_archetype_dispatch.py`, the dispatcher mocks didn't bind to the right module object, 8 tests failed downstream. Simplified to plain `mock.patch(side_effect=RuntimeError)` — the broad `except` in `_evaluate_dispatcher` catches it regardless. Faster + isolation-safe + same coverage.
- **`owned_item_ids` extension was a 2-line liveclient change.** Already had `owned_items` as displayName list; just parallel-walk `me_pl.get("items")` for `itemID`. Same order, same length. No frontend changes needed (yet).
- **In-memory dedup vs file-persisted.** Considered `data/archetype_nudge_state.json` for restart-survival; rejected because RC restarts are common (`restart_trigger.txt` ~daily during dev) and a nudge dismissed last session has zero relevance next session. Module-level dict wins for simplicity + zero I/O. Operator's chip-dismiss survives across /api/state polls but not across restarts.

## Verification

- `py -m pytest tests/test_archetype_mismatch.py tests/test_state_builder_archetype_nudge.py tests/test_routes_archetype_nudge.py -v` → **54 passed**
- `py -m pytest tests/` → **1009 passed** (was 955 in s183 wrap; +54 new)
- `py -m pytest agents/daemon_slayer/tests/` → **1426 passed** (unchanged — DS engine math untouched)
- `py -m pytest tests/snapshot_panels/` → **11 passed** (panel JS render unchanged)
- `py -m py_compile core/archetype_mismatch.py dashboard/_state_builder.py dashboard/_liveclient.py dashboard/routes_archetype.py` → clean
- `py -m ruff check core/archetype_mismatch.py dashboard/_state_builder.py dashboard/_liveclient.py dashboard/routes_archetype.py tests/test_archetype_mismatch.py tests/test_state_builder_archetype_nudge.py tests/test_routes_archetype_nudge.py` → All checks passed
- RC restart (pid 12144 → pid 1360) verified via /api/state shape

## Open items carried forward

- 🟡 **JS chip renderer — s184.1.** Needs a small yellow info-style chip near `#ds-pill` (in `web/js/panels/item_build.js`) that polls `state.archetype_nudge.fired === true` + shows `state.archetype_nudge.message` + an X button calling `POST /api/archetype-nudge/dismiss {champion}`. Pattern: same as `#ds-pill` itself (mode-gated, fade-in on first appearance). Estimate ~50 LOC + snapshot test.
- 🟡 **Live game validation.** No game ran during s184 — the new eval logic is exercised only by unit tests. Next real CS + game start will validate: (a) `lc.owned_item_ids` actually populates from Game-PC liveclient relay; (b) `lc.game_id` actually populates (depends on Riot's LCU schema for current patch); (c) the dispatcher round-trip happens within /api/state's tick budget. Engine-down fault path is already proven.
- 🟡 **Calibration knob — top-15 threshold.** 15 is generous but arbitrary. After a few real games with fired nudges, the operator may want it tighter (top-10) or looser (top-20). Single constant `_TOP_N_THRESHOLD` in `archetype_mismatch.py`; trivial to retune.
- 🟡 **Item-filter denylist maintenance.** ~28 hardcoded IDs covering boots/Doran/trinkets/consumables/starters/jungle-pets. When Riot adds new items in next patch (16.10+), the list needs review — false-positive risk if a new starter or trinket isn't denylisted (would fire nudge for "I bought starter X first, did you mean to?").
- 🟡 **Per-game-session token edge case.** When liveclient `gameData.gameId` is absent (older LCU builds; first-tick race conditions), the synthetic fallback `{champion}@{start-floor-min}` is stable across the typical 25-min game but rolls over per minute if `game_time_s` drifts. In practice the real signal arrives mid-game when items complete — by that point `gameId` is populated. Minor edge case; flagging for awareness.
- 🟡 **Pre-existing carry-forwards from s183 remain:** Phase 6.5/5.5/4d calibration follow-ups blocked on rewind_history.db freshness; Audit finding #1 (frozen-file list duplication) needs operator approval.
