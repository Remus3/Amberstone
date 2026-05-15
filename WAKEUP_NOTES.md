# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 archived to docs/history_notes.md. Only the last 3 sessions kept here.

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

---

# s204 wrap — 2026-05-14 (Phase 5.9.17 block_index expansion — 8 entries / 2 new champs + 6 extensions + form_index seed)

**Operator instruction:** "continue DS" — direct continuation of s203 (now the **twentieth** consecutive override / proc-shape ship on the same template, **thirteenth** pure-data batch in the block_index family). This batch closes the s203 carry-forward "Riven form_index seed needed for form-conditional block_index entries" — Riven becomes the first new champion added to the form_index registry since s187 (Nidalee/Elise/Jayce/Hwei/LeeSin). Cumulative coverage 67% → 68% of the 171-champion roster.

## One new architectural pattern discovered s204

**Second NET-damage layering of block_index on form_index** (after s203 LeeSin Q). Riven is a particularly clean case: form 0 "Blade of the Exile" has ZERO damage blocks (pure buff/empower form), and form 1 "Wind Slash" carries the only damage. The form_index seed routes the parser to form 1; block_index = 1 then selects max-missing-HP execute within that form. No information loss from routing past form 0 since it's data-empty. Nidalee Q (Cougar Takedown) form 1 block 1 ships in the same batch — both are execute-amp layers, both compose orthogonally with their prior form_index entries.

## Sub-patterns reused

- **Multi-hit single-target totals (3 entries):** Evelynn Q (Hate Spike 7-missile rotation, 175% AP scaling), Gwen Q (max-stack 6-snip burst, 10.3× block 0 base), Syndra W (Force of Will Total Mixed sum, 1.12× — small additive but consistent under-count).
- **Fully-charged amp (1 entry):** KSante W (Path Maker full 2s charge Total Maximum Mixed, 1.8× block 0).
- **Champion-vs-minion amp (1 entry):** Seraphine Q (High Note Maximum Champion Damage 1.75×). Revives s198/s202 'enchanter-class' skip under archetype-mismatch framing — direct /ability-dps queries benefit even though Seraphine dispatches to ds.hps.
- **Execute amp layered on form_index (1 entry):** Nidalee Q (Cougar Takedown low-HP execute via s187 form_index=1). Second NET-damage layering after s203 LeeSin Q.
- **Target-state amp (1 entry):** Zoe E (Maximum Mixed on sleep-procced target, 2× block 0). First entry reviving the conditional target-state schema lift bucket under unconditional operator-commits framing — same as Khazix Q isolation s196 / Xerath W center-spot s201 / Vayne E wall-stun s202.
- **Form_index seed expansion (1 entry):** Riven R + new form_index Riven.R = 1 (Wind Slash max-missing-HP execute). Closes s203 carry-forward. First new champion added to form_index registry since s187.

## s204 ship — Phase 5.9.17 — 8 entries

Live A/B headlines on :8893 (/ability-dps lvl 11 vs 80 armor / 30 MR / 2000 HP) — TOTAL ability_dps deltas (per-spell preview deltas in parens):

| Champion | Key | Pattern | total adps off → on | Lift |
|----------|-----|---------|---------------------|------|
| Evelynn | Q | full Hate Spike (7× missile) | 19.78 → 86.98 | **+339.7%** (per-spell +667%) |
| Gwen | Q | max-stack Snip Snip (10× base) | 8.80 → 23.65 | **+168.7%** (per-spell +934%) |
| Nidalee | Q | cougar Takedown low-HP exec | 39.02 → 68.51 | **+75.6%** (per-spell +175%) |
| Seraphine | Q | Max Champion Damage | 11.11 → 17.02 | **+53.2%** |
| KSante | W | Path Maker full charge | 8.48 → 9.99 | **+17.8%** |
| Syndra | W | Total Mixed sum | 28.06 → 29.23 | **+4.2%** |
| Zoe | E | sleep-procced Max Mixed | 44.53 → 45.99 | **+3.3%** |
| Riven | R | Wind Slash form 1 exec | 57.80 → 59.43 | **+2.8%** (was 0.00 baseline) |

**Spell-share dilution** explains why Gwen Q's per-spell +934% translates to total +168.7% (Gwen R already contributes 6.79 dps so Q is one of 3 contributors). Riven R total lift +2.8% is small because Riven's Q (Broken Wings) dominates at 54.84 dps — but architecturally significant since R was contributing 0.00 pre-s204 due to form 0 having no damage blocks. Zoe E +3.3% similar — Zoe's Q dominates at 42.17 dps.

| Commit | Summary |
|--------|---------|
| [`1003ed9`](https://github.com/Remus3/riot-commander/commit/1003ed9) | s204 feat — 8-entry Phase 5.9.17 block_index + Riven form_index seed + 2 NET-damage form_index×block_index layerings |

Registry: 115 → 117 champions. Entries: 173 → 181. Form_index registry: 5 → 6 champions, 9 → 10 entries (Riven R=1 new). ENGINE_VERSION: 0.88.0 → 0.89.0. DS suite: 1919 → 1939 (+20 net tests). Wider RC: 1023 + 1 expected phase8_smoke pass post-restart.

**Test-fixture maintenance:** 5 stale assertions in `test_known_champion_overrides` converted from full-shape `assertEqual` to either commented-out OR migrated to Phase599_17 block (Evelynn / Syndra / Riven / KSante / Zoe — all extended this batch). 1 stale `test_zoe_both_keys_in_resolved` in `Phase599_15ExpansionTests` converted from full-shape `assertEqual` to per-key `.get()` subset check (Zoe now has 3 keys after s204 added E=2). 1 `test_rank_assassin_carries_source` updated for new Evelynn shape `{R:1, Q:5}`.

## Tomorrow / future sessions

**All s203 carry-forwards remain unchanged except Riven (closed):**

- 🟡 **Token-variant for multi-stage Q chains** — Aatrox Q1/Q2/Q3 (combo_sequence-aware), Gwen R needlework recasts (already partially handled via block_index=4 for full burst).
- 🟡 **Form-swap block_index schema** — KSante R full per-form indexing, Kayn (Rhaast/Shadow Q), Hwei (Q/W/E forms 0/1/2/3), **Qiyana Q** (s203 + s204 deferred — needs form_index registry seed for elemental form, same pattern Riven shipped this batch).
- 🟡 **Sequence-state block_index** — Jhin R 4th-shot, Corki R Big One every-4th-missile, Akshan R Comeuppance charge.
- 🟡 **Conditional target-state block_index** — Zoe sleep amp now SHIPPED (s204) under operator-commits framing. Remaining: Lux Illumination, DrMundo E missing-HP threshold, Evelynn Q charm, Vayne E wall-stun, Kayle E missing-HP, Kindred E mark detonation. 6+ candidates still queued — schema lift becomes warranted if 3+ ship under operator-commits framing first.
- 🟡 **Sum-of-blocks schema** — STILL 8+ candidates: Thresh E souls+magic, Taliyah E impact+detonations, Sona Q spell+Power Chord, Camille W flat+max-HP (s202) + Katarina R bAD+AP, Malphite W first+subsequent, Malzahar E/R on-cast+DOT, Kalista E per-stack, Jinx R distance-scaled (s203). Lift continues to be warranted.
- 🟡 **Nested missing-HP parser** — Kindred E (s201 drop), Kayle E (s202 drop), Belveth R execute curve (s203 drop). Phase 4a `unparsed_modifiers` extractor needs upgrade to handle "X% (+ Y% per Mark) of target's missing health" format.

## Hand-off notes

- **Tryndamere remains canonical unmapped fixture** (s201 rotation). No change s204.
- **Evelynn now has 2 keys** (R s191 + Q s204). Assassin archetype.
- **Gwen now has 2 keys** (R s203 + Q s204). Mage/bruiser hybrid.
- **KSante now has 2 keys** (R s202 + W s204). Tank/bruiser hybrid.
- **Riven now has 2 keys** (Q s196 + R s204) + form_index R=1 entry. Bruiser archetype.
- **Syndra now has 2 keys** (R s195 + W s204). Mage archetype.
- **Zoe now has 3 keys** (Q s195 + W s202 + E s204). Mage archetype.
- **Nidalee + Seraphine** are the 2 truly-new champions this batch.
- **DS server restart required** after ENGINE_VERSION bump. Via PowerShell `Stop-Process -Id <pid> -Force` then `Start-Process pythonw start_daemon_slayer.py -WindowStyle Hidden -WorkingDirectory "C:\Riot Commander"`. /health confirms 0.89.0.

## s204 architectural delta

Twentieth consecutive override / proc-shape modeling improvement on the same template (s185 max_priority → s186 combo → s187 form → s188 per-AA on-hit → s189 Spellblade → s190 Lightshield → s191 block_index → s192 token-variant → s193 channels → s194 calibration → s195 multi-hit → s196 condition-amp → s197 assassin/fighter → s198 bruiser broadening → s199 standard sweep → s200 rescue → s201 framing revert → s202 wall-stun framing revert + broadening → s203 active-cast vs passive-zap split + empty-block-0 fix + form_index×block_index NET-damage layering → s204 form_index seed expansion + second NET-damage layering + target-state amp revival). Thirteenth pure-data batch in the channel/total/charge family. Second batch to expand form_index registry (s187 was the seed). **Cumulative coverage: 181 (champion, key) entries across 117 champions** (68% of the 171-champion roster touched). Pattern remains rock-solid; rate-limit is now (a) sum-of-blocks schema lift becoming necessary (8+ candidates queued), (b) Qiyana Q form_index seed needed before next form-conditional block_index batch.
