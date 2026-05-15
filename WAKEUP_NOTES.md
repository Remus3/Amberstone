# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s207 wrap — 2026-05-14 (Phase 5.9.20 sum-of-blocks schema lift + 4 seed entries + README rewrite)

**Operator instruction:** "have the readme be in a more summary overview than technical, remove the parts for the cross-machine specifics, mentioning it is fine details are not needed, bridge application is fine, remove the 2 machine installation part. change how the check lists of things done and stuff to do is presented. remove the RC Tutor section entirely since i am slowly getting RC Tutor to be one and the same with RC, it is redundant. Simplify some descriptions for non technical non league people reading it. then continue ds" — two-part session. Part 1 is a deep README rewrite. Part 2 is the s205+s206-deferred sum-of-blocks schema lift.

## Part 1 — README rewrite (313 → 86 lines)

**Removed entirely:**
- Topology table (Legion / Game-PC / Peer with IPs / hostnames / scheduled tasks)
- Architecture file tree
- Phase 3 agent framework table (8-row internal coordination)
- Cross-Claude infrastructure deep details (Tailscale config, bearer tokens, bridge wire format)
- Bridge Watcher daemon table (4 phases + per-phase rules)
- Bring-up section (per-machine install workflow — operator's explicit ask)
- Engineering audit table (Tier 1-3)
- Roadmap section (cross-Claude learning sync, Bridge Watcher hardening, vision calibration phases)
- RC Tutor — Future Direction (operator: "redundant since RC Tutor is becoming RC")
- Operational notes (atomic writes, restart workflow, frozen files — internal dev knowledge)

**Restructured:**
- One-paragraph elevator pitch up top
- "What it does" — 5 prose paragraphs (no bullets-of-bullets), simplified for non-League readers (e.g. "champion select" glossed as "the picking phase before each match")
- "How it works" — 2 paragraphs covering the coaching tick + build engine
- "Daemon Slayer build engine" — preserved as the technical centerpiece, with the 6-archetype scoring table (the only retained checklist-style structure in the README)
- "Where it runs" — 2 sentences mentioning the 2-machine + bridge architecture as background only, no IPs / hostnames / task names
- "Project status" — narrative paragraph + 4 plain-prose bullets describing active work direction (replaced the multi-tier ✅/🟡/🔴 checklist)
- "More" — pointer list to CLAUDE.md / ROADMAP.md / docs/DAEMON_SLAYER.md / docs/ARCHITECTURE.md / docs/adr/

## Part 2 — Phase 5.9.20 sum-of-blocks schema lift

**Schema change** in `champion_block_index.json`:
```diff
- "Camille":  { "Q": 2 }
+ "Camille":  { "Q": 2, "W": [0, 1] }
+ "Heimerdinger": { "W": [0, 1, 1, 1, 1] }
+ "Katarina": { "R": [1, 3] }
+ "Malphite": { "W": [2, 3] }
```

Value type widens from `int` to `int | list[int]`. List values express "operator commits to landing every component" — when the realistic single-target damage is the sum across multiple Meraki damage blocks. Index repetition (`[0, 1, 1, 1, 1]`) elegantly expresses multipliers without needing dedicated multiplier syntax.

**Engine signature changes** (`ability_dps.py`):
- New `_normalize_block_index_value(v)` — rejects bool / str / float / None; accepts int + list[int] + empty list. ValueError on garbage with explicit reason.
- `_select_blocks(... block_index: int | Sequence[int] = 0, ...)` — when sequence supplied under "indexed" strategy, loops + sums per-element with same clamp semantics.
- `get_block_index_for(champion_id) -> tuple[dict[str, int | list[int]], str]`
- `_resolve_block_index_overrides(...) -> tuple[dict[str, int | list[int]], str]`
- 5 sites of `Optional[dict[str, int]]` widened to `Optional[dict[str, int | list[int]]]` (in `compute_ability_dps` / `rank_items_by_ability_dps` / `compute_burst_damage` / `rank_items_by_burst` parameters)

**Server `_parse_block_index`** in `server.py` — accepts JSON arrays alongside ints; defensively skips bool / non-int payloads silently (matches `_parse_form_index` / `_parse_max_priority` defensive policy).

## Live A/B headlines (Legion :8893 /ability-dps lvl 11 vs 80/30/2000)

| Champion | Key | Registry | block-0 only | sum | Delta | Ratio |
|---|---|---|---|---|---|---|
| Camille | W | [0, 1] | 100.0 | 240.0 | +140 | **2.4×** |
| Malphite | W | [2, 3] | 50.0 | 70.0 | +20 | **1.4×** |
| Heimerdinger | W | [0, 1, 1, 1, 1] | 140.0 | 260.0 | +120 | **1.86×** |
| Katarina | R | [1, 3] | 0.0 | 562.5 | +562.5 | (block 0 was bAD-only at naked AD = 0; sum captures full physical+magic volley) |

**Heimerdinger sanity check:** the sum result (260 raw) exactly matches the precomputed "Combined Total Non-Minion Damage" block (raw_modifiers values=[80, 125, 170, 215, 260] at ranks 1-5) which the engine couldn't address before because that block is `kind=modifier` and gets filtered out pre-index. The sum [0, 1, 1, 1, 1] reaches the same number through `kind=damage` blocks the indexed strategy CAN see.

## Test counts

- DS suite: **1979 → 2022** (+43 in new `test_sum_of_blocks.py`)
- Wider RC: **1013** (no regressions)

Test classes:
- `NormalizeBlockIndexValueTests` (9) — validator behavior, bool rejection, list rejection of non-ints
- `SelectBlocksListTests` (8) — int-path unchanged, list path semantics, clamping, empty-list, tuple support
- `RegistrySeedEntriesTests` (4) — 4 new entries present + correct shape
- `ResolveBlockIndexListMergeTests` (4) — caller-int wins over registry-list and vice versa, list preservation
- `AbilityDpsSumOfBlocksTests` (7) — integration: sum > forced-single + arithmetic equality (Camille / Malphite / Heimerdinger / Katarina)
- `BurstSumOfBlocksTests` (3) — burst.py call site mirrors
- `BackwardCompatIntEntriesTests` (3) — Veigar R / Cassi E still int-typed
- `ServerRouteSumOfBlocksTests` (5) — live :8893 verification including caller-supplied list via JSON body

Plus 2 existing-test updates:
- `test_every_value_is_int` → `test_every_value_is_int_or_list_of_ints` (widened to validate both shapes)
- `test_pre_s198_camille_unchanged` extended for new W=[0,1] entry

## Files touched

| File | Change |
|------|--------|
| `README.md` | Full rewrite 313 → 86 lines per operator restructure ask |
| `agents/daemon_slayer/__init__.py` | ENGINE_VERSION 0.91.0 → 0.92.0 |
| `agents/daemon_slayer/ability_dps.py` | `_normalize_block_index_value` + `_select_blocks` list path + 4 type-hint widenings |
| `agents/daemon_slayer/burst.py` | 2 type-hint widenings |
| `agents/daemon_slayer/server.py` | `_parse_block_index` accepts arrays |
| `agents/daemon_slayer/champion_block_index.json` | 4 seed entries (Camille W extension + 3 new champs) + _meta description extended |
| `agents/daemon_slayer/tests/test_sum_of_blocks.py` | NEW — 43 tests |
| `agents/daemon_slayer/tests/test_block_index_overrides.py` | 2 existing-test updates for new schema |
| `agents/daemon_slayer/tests/test_effects_expansion.py` | 2 ENGINE_VERSION pin bumps + 0.92.0 changelog comment |
| `CLAUDE.md` | Deep-references ENGINE_VERSION ref bumped + priority #65 added |
| `docs/DAEMON_SLAYER.md` | Test count + ENGINE_VERSION refs synced |
| `docs/ARCHITECTURE.md` | Test count + ENGINE_VERSION refs synced |

## Hand-off notes

- **DS server pid 14476** running 0.92.0 / 16.10.1 (was pid 11352 on 0.91.0); verified `/health` + 4 A/B routes post-restart.
- **No RC supervisor restart needed** — s207 only touched DS engine code.
- **Cumulative override coverage** now at 189 entries / 121 champions / 71% roster (was 185/118/69% pre-s207).
- **README is now a summary overview**, not a technical reference. Future sessions should resist the temptation to re-add detailed sections — use `CLAUDE.md` or `docs/DAEMON_SLAYER.md` for technical context.

## Carried forward to s208+

- 🟢 **Sum-of-blocks data batch** — 6+ remaining candidates queued (Thresh E souls+magic, Taliyah E impact+detonations, Sona Q spell+Power Chord, Malzahar E/R on-cast+DOT, Kalista E per-stack, Jinx R distance-scaled). Schema is in place; just need to add JSON entries + test assertions.
- 🟡 **Nested missing-HP parser** — Kindred E, Kayle E, Belveth R execute curve. Phase 4a `unparsed_modifiers` extractor needs upgrade to handle "X% (+ Y% per Mark) of target's missing health" format.
- 🟡 **Conditional target-state schema lift** — 6+ candidates remain (Lux Illumination, DrMundo E missing-HP, Evelynn Q charm, Kayle E missing-HP, Kindred E mark, Vayne E wall-stun). Defer until sum-of-blocks data batch ships.

## Don't redo

- Sum-of-blocks SCHEMA — shipped this session. Don't re-architect the `int | list[int]` shape; the index-repetition pattern is the canonical way to express multipliers.
- README compression — done. Future sessions should add to `CLAUDE.md` or `docs/DAEMON_SLAYER.md` instead of re-bloating the README with monotonic enumerations.

---

# s206 wrap — 2026-05-14 (Phase 5.9.19 cooldown inheritance from form 0 + README cleanup)

**Operator instruction:** "clean up readme.md and then continue ds" — two-part session. Part 1 compresses the monotonic s174-s182 enumeration that grew across recent sessions. Part 2 closes the s205 carry-forward "Engine None-cooldown fallback" — but with a re-framing because the original diagnosis was wrong about the impact magnitude.

## Part 1 — README cleanup

3 paragraphs compressed:

| README location | Before | After |
|----|----|----|
| Line 12 "Daemon Slayer build engine" bullet | ~1.5KB enumerating s174 → s182 inline | Stable summary: 6 archetype scorers + per-(champion, key) override registries + coach integration |
| Line 244 "Daemon Slayer engine — current state and remaining work" | ~2KB enumerating s174 → s181 inline | 2 tables (scorer routing + override registries) + coach wire-in checklist |
| Line 311 RC Tutor capability table row | ~600B enumerating s174 → s181 | Stable one-liner: "1979 tests, ENGINE 0.91.0, all 6 archetype scorers fully wired" |

Plus same compression pass on `docs/DAEMON_SLAYER.md` line 5 status header + `docs/ARCHITECTURE.md` line 151 DS section. Living docs now describe **what RC is**, not the changelog of how it got there.

## Part 2 — Phase 5.9.19 cooldown inheritance

**Engine signature change** (`ability_dps.py`):
```python
def _form_cooldown_at_rank(form, rank, fallback_form: AbilityForm | None = None) -> float:
    if form.cooldown:
        # use primary form's per-rank CD
    if fallback_form is not None and fallback_form.cooldown:
        # inherit from fallback (typically forms[0])
    return 60.0  # generic fallback (preserves pre-s206 behavior)
```

Both call sites (`ability_dps.py:1021` + `burst.py:731`) now pass `forms[0] if form_idx != 0 else None`. Form-swap mechanics share the actual game cooldown with their parent form, so inheritance is correct.

## Re-framing the s205 carry-forward

The s205 hand-off claimed "engine None-cooldown fallback ... under-counts by ~8.5× per-cast DPS conversion". Investigation found that diagnosis was incorrect because **all 4 affected entries have `casts_per_sec_source: "measured"`** from `spell_cast_rates.json` (covering 172 champs × Q/W/E/R × 3 modes from 2851 rewind matches). The cooldown lookup is only used for DPS when measured rate is absent — which it isn't for any of these.

**Actual s206 impact:**
1. `per_spell.cooldown` metadata now correct (was uniformly wrong 60s for 4 entries)
2. ComboCast row metadata in burst output now correct
3. Theoretical-fallback DPS conversion (only fires when measured rate absent) now uses correct CD — forward-compat for new form-swap champions before their measured rates ship

So this is a **metadata + theoretical-fallback correctness fix**, not a DPS-scoring lift. Total ability_dps for the 4 entries unchanged.

## Live A/B (Legion :8893 /ability-dps lvl 11 vs 80/30/2000)

| Champion | Key | Pre-s206 cd | Post-s206 cd | DPS unchanged? |
|---|---|---|---|---|
| Riven | R | 60.0s | **90.0s** (form 0 cd[1] @ rank 2) | ✅ 2.45 unchanged |
| Renekton | E | 60.0s | **16.0s** (form 0 cd[0] @ rank 0) | ✅ 3.16 unchanged |
| AurelionSol | R | 60.0s | **110.0s** (form 0 cd[1] @ rank 2) | ✅ 1.73 unchanged |
| Qiyana | Q | 60.0s | **7.0s** (form 0 cd[0] @ flat 7s) | ✅ 10.26 unchanged |

DPS values unchanged because all 4 use measured cps_source — confirms the intended s206 framing.

## Test counts

- DS suite: 1953 → 1979 (+26 in new `test_cooldown_inheritance.py`)
- Wider RC: 1013 (no regressions)

Test classes:
- `CooldownHelperBackwardCompatTests` (5) — pre-s206 behavior preserved when no fallback supplied
- `CooldownHelperFallbackTests` (7) — fallback inherits when primary has None; explicit None fallback returns 60s; clamping
- `AbilityDpsCooldownInheritanceTests` (7) — Riven R / Renekton E / ASol R / Qiyana Q + form-0 unaffected + unmapped Veigar R unaffected
- `BurstCooldownInheritanceTests` (3) — burst.py call site mirrors
- `ServerRouteCooldownTests` (4) — live :8893 verification

## Files touched

| File | Change |
|------|--------|
| `agents/daemon_slayer/__init__.py` | ENGINE_VERSION 0.90.0 → 0.91.0 |
| `agents/daemon_slayer/ability_dps.py` | `_form_cooldown_at_rank` signature + s206 inline comment at call site |
| `agents/daemon_slayer/burst.py` | Mirror call site update |
| `agents/daemon_slayer/tests/test_cooldown_inheritance.py` | NEW — 26 tests |
| `agents/daemon_slayer/tests/test_effects_expansion.py` | 2 ENGINE_VERSION pin bumps + 0.91.0 changelog comment |
| `README.md` | 3 paragraphs compressed + version refs bumped |
| `docs/DAEMON_SLAYER.md` | Status header compressed + version bumped |
| `docs/ARCHITECTURE.md` | DS section compressed + version bumped |
| `CLAUDE.md` | Deep-references ENGINE_VERSION ref bumped + priority #64 added |

## Hand-off notes

- **DS server pid 11352** running 0.91.0 / 16.10.1 (was pid 6052 on 0.90.0); verified `/health` + `/ability-dps` post-restart.
- **DS server is HTTP not HTTPS** on :8893 — curl --insecure fails with `schannel SEC_E_INVALID_TOKEN` because the schannel implementation rejects mkcert. Use `http://127.0.0.1:8893/health` directly.
- **No RC supervisor restart needed** — s206 only touched DS engine code; web dashboard + state-builder unchanged.
- **Dispatcher coverage unchanged** at 6/6 archetypes, no fallbacks. Cumulative override coverage stays at 185 entries / 118 champions / 69% roster.

## Carried forward to s207+

- 🟢 **Sum-of-blocks schema lift** — now 10+ candidates queued (Heimerdinger W, Thresh E souls+magic, Taliyah E impact+detonations, Sona Q spell+Power Chord, Camille W flat+max-HP, Katarina R bAD+AP, Malphite W first+subsequent, Malzahar E/R on-cast+DOT, Kalista E per-stack, Jinx R distance-scaled). Schema: extend `block_index_overrides` value type from `int` to `int | list[int]` where list means sum. **Lift warranted next session.**
- 🟡 **Nested missing-HP parser** — Kindred E, Kayle E, Belveth R execute curve. Phase 4a `unparsed_modifiers` extractor needs upgrade to handle "X% (+ Y% per Mark) of target's missing health" format.
- 🟡 **Conditional target-state schema lift** — 6+ candidates (Lux Illumination, DrMundo E missing-HP, Evelynn Q charm, Kayle E missing-HP, Kindred E mark, Vayne E wall-stun). Defer until Sum-of-blocks ships.
- 🟢 **form_index registry expansion** — TwistedFate W (Pick a Card), TahmKench R Regurgitate, Annie R Tibbers — needs runtime player-choice plumbing, not registry-only.

## Don't redo

- Cooldown inheritance — shipped this session. Don't add more inheritance layers; the form_0 → form_N pattern is the only one Meraki actually uses.
- README cleanup — done. Future sessions add to the s174-style monotonic enumeration only at their peril; instead, update the stable summary fields (test count, ENGINE_VERSION, archetype count, coverage %).

---

# s205 wrap — 2026-05-14 (Phase 5.9.18 form_index + block_index layered expansion — 4 block_index entries + 3 form_index seeds)

**Operator instruction:** "continue DS" — direct continuation of s204 (twenty-first consecutive override / proc-shape ship on the same template, fourteenth pure-data batch in the block_index family). Closes the s204 carry-forward "Qiyana Q form_index seed expansion still pending". Cumulative coverage 68% → 69% of the 171-champion roster.

## What shipped

**Two commits pushed to main:**
- [`24ed6aa`](https://github.com/Remus3/riot-commander/commit/24ed6aa) — feat: 4 block_index entries (Qiyana Q=2 NEW + Hwei W=1 / Renekton E=3 / Shaco W=1 extensions) + 3 form_index seeds (Qiyana Q=1 / AurelionSol R=1 / Renekton E=1)
- [`35638ca`](https://github.com/Remus3/riot-commander/commit/35638ca) — docs: CLAUDE.md priority #63 sync

**Three sub-patterns:**
- **Pattern A operator-commits-to-resource form layer (3):** Qiyana Q (form 1 Elemental Wrath + block 2 Increased Damage, 1.6× base; form 0/1 share block 0 so form_index alone is no-op, block_index is load-bearing), AurelionSol R (form 1 The Skies Descend, 1.25× base + 1.25× AP, default block 0 within form 1 correct), Renekton E (form 1 Dice + block 3 Total Physical Damage = block 0 + block 1 sum = full Slice+Dice+Fury combo, 2.75× form 0 at rank 1; closes Renekton Q/W/E full-Fury coverage after s197 Q=1 + W=2).
- **Pattern B multi-hit single-target totals (1):** Hwei W form 3 block 1 Maximum Magic Damage = 3× block 0 (Stirring Lights 3 lights converging).
- **Pattern C condition-amp vs target-state (1):** Shaco W block 1 Increased Damage = 2.5× block 0 base + 1.5× AP (Box vs already-Feared target).

**Third instance of form_index + block_index NET-damage composition** after s203 LeeSin Q + s204 Riven R + s204 Nidalee Q.

## Live A/B (lvl 11 vs 80/30/2000 — per-spell DPS lifts since most spells aren't the champion's dominant DPS contributor)

| Champion | Key | Pattern | per-spell dps off → on | Lift | Total |
|----------|-----|---------|------------------------|------|-------|
| Hwei | W | 3 lights converging | 1.26 → 3.79 | **+200%** | +12.1% |
| Shaco | W | Box vs Feared | 0.69 → 1.91 | **+175%** | +7.7% |
| Renekton | E | full-Fury combo (form+block layer) | 1.15 → 3.16 | **+175%** | +10.4% |
| Qiyana | Q | Elemental Wrath (form+block layer) | 6.41 → 10.26 | **+60%** | +40.1% |
| AurelionSol | R | The Skies Descend (form seed only) | 1.38 → 1.73 | **+25%** | +2.3% |

Per-cast raw damage lifts match Meraki block ratios exactly: Hwei W 40 → 120 (3× verified), Shaco W 20 → 55 (2.5× verified), Renekton E 40 → 110 (2.75× form 0 = block 0 + block 1 sum), Qiyana Q 180 → 288 (1.6× verified), AurelionSol R 250 → 312.5 (1.25× verified).

## Engine limitation discovered (carry-forward)

Meraki snapshots set `cooldown=None` for non-form-0 forms. DS engine falls back to default 60s CD when computing DPS conversion, dampening total ability_dps lift. Affects every form_index + non-form-0 entry currently shipped: Riven R (s204) / Renekton E / AurelionSol R / Qiyana Q (s205). For Qiyana Q the per-cast raw lift is +60% but the engine reports 60s CD vs 7s real CD — so the DPS conversion is under-counted by ~8.5×. Calibration follow-up candidate — needs an engine-side "inherit form 0 cooldown when None" fallback.

## Test counts

- DS suite: 1939 → 1953 (+14 net, 21 new in `Phase599_18ExpansionTests` minus 5 stale assertions converted/extended)
- Wider RC: 1023 → 1024 (phase8_smoke restored after DS server restart picked up ENGINE_VERSION 0.90.0)

## Multi-key extensions

- Hwei now `{R:3, W:1}` (W=1 new)
- Renekton now `{Q:1, W:2, R:1, E:3}` — full Q/W/E/R coverage (E=3 new + form_index seed E=1)
- Shaco now `{E:2, W:1}` (W=1 new)
- AurelionSol stays `{E:1, Q:2}` on block_index side — R adds via form_index registry only

## Carried forward to s206+

- **Sum-of-blocks bucket grows:** Heimerdinger W (Initial + 4× Subsequent on focused non-minion target) joins Thresh E + Taliyah E + Sona Q + Camille W + Katarina R + Malphite W + Malzahar E/R + Kalista E + Jinx R distance + Sona Q Power Chord — 10+ candidates queued. Lift warranted soon.
- **Engine None-cooldown fallback** — needed for s204/s205 form-1 entries to score correctly. Currently the registry entries are net-positive but dampened.
- **Nested missing-HP parser bucket** (Kindred E, Kayle E, Belveth R execute curve) unchanged.
- **Conditional target-state schema lift bucket** (6+ candidates) unchanged.
- **form_index registry expansion** — Qiyana / AurelionSol / Renekton joined Riven. Future candidates from this session's audit: TwistedFate W (3-form Pick a Card — player choice, deferred), TahmKench R form 1 Regurgitate (player choice, deferred), Annie R Tibbers pet damage (data gap upstream).

## Skip list expanded this session

Inspected and rejected 50+ candidates from unmapped + extension scans. Key deferrals documented inline in `champion_block_index.json` `_meta` description:
- Caitlyn Q / Orianna Q / Zed Q / Yone W+R — engine default block 0 already correct (primary target full damage)
- Ezreal R / Jhin R / Pantheon R — engine default block 0 already correct (primary/max distance)
- Annie R / Mordekaiser Q/W/R — single-block or non-damage (pet damage not in snapshot)
- Heimerdinger W — sum-of-blocks needed (Initial + 4× Subsequent on non-minion)
- Kayle E / Kindred E / DrMundo E — nested missing-HP parser bucket
- Malphite W / Sona Q — sum-of-blocks
- Tryndamere Q / Fiddlesticks Q — Meraki data parsing gap (broken block schemas)
- Karma Q form 1 / Khazix evolved / TwistedFate W — player-choice forms not default

## Don't redo

- Qiyana Q form_index seed — shipped this batch via form_index=1 + block_index=2 composition. Don't re-investigate without sum-of-blocks support, since form 0/1 share block 0.
- AurelionSol R form_index seed — shipped. Don't add block_index entry; default 0 within form 1 is correct.
- Renekton E full-Fury combo — shipped via block 3 sum.
- Hwei W 3-light Maximum — shipped via block 1.
- Shaco W Feared target — shipped via block 1.
