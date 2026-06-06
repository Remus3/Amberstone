# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-05 - loop directive reconcile: both named DS slices already SHIPPED [docs-only]

Loop `ops/loop/control/directive.md` asked to implement "AurelionSol W cross-spell seam" + "conditional-gate for Brand W and Ekko W" via the orchestrator pattern. GROUND-TRUTH PROBE: both already shipped; directive was generated from STALE ROADMAP line 49 prose (written at item 250/251) that still listed them as "remain".

- **Slice A AurelionSol W cross-spell seam = item 257** (commit `c47f04b9`, ENGINE 1.87.0 -> 1.88.0). `_CROSS_SPELL_AMP_OVERRIDES` + `_cross_spell_amp_for` consumed at `agents/daemon_slayer/ability_dps.py:1111`. default-OFF byte-identical.
- **Slice B conditional-gate = item 255** (commit `db52d355`, ENGINE 1.86.0 -> 1.87.0). Brand P (Blaze max-HP ring, prob 0.5) + Ekko W (Parallel Convergence missing-HP sub-30%, prob 1.0 ctx-gated) in `_passive_damage_overrides.py`. NB directive said "Brand W"; the real conditional-gate damage slot is Brand P (W = plain AoE zone, no gate). default-OFF byte-identical.
- **No re-implementation.** Re-coding shipped entries would violate the CLAUDE saturation guard + risk duplicate registry rows. Did NOT spawn worktree agents (nothing to implement). Fixed the stale ROADMAP line 49 instead.
- **Tests:** named-slice files `test_cross_spell_amp_item257.py` + `test_passive_damage_conditional_gate_item255.py` = 45 passed. Full DS dir `agents/daemon_slayer/tests/` = 6644 passed / 1 skip / 1 xfail / 1936 subtests / EXIT 0. NO ENGINE bump, DS NOT restarted.
- **NEXT:** only Phase D live flag-flips remain for DS-completion - operator-gated, NOT headless (section 4b do-not-flip-blind).

---

# 2026-06-05 - P3.2: antitank.py dynamic %HP scaling via injected ResolvedStats [item 315]

DS engine SCHEMA LIFT, NO ENGINE bump (byte-identical live, ENGINE stays 1.118.0; DS NOT restarted; non-frozen). Operator-accepted design change (item 312 flagged antitank as intentionally STATIC per item 308). Full record = item 315 in `docs/LEDGER.md`.

- **Domain fork (one AskUserQuestion BEFORE coding):** pure %max-HP (Vayne W / Fiora P, the dominant MAX_HP kind) does NOT scale with caster AP/AD in-game; only Kog'Maw W cap / Gwen P bilinear carry a real caster-stat term. Operator chose the per-row coefficient schema lift over a blanket multiplier or a full quantitative rebuild.
- **Schema lift (`agents/daemon_slayer/antitank.py`):** `AntiTankEntry` gains optional `ap_ratio` / `ad_ratio` (default 0.0, appended at END - positional construction + item-308 `_mechanism_value(e)` single-arg stay valid); `compute_antitank` / `_mechanism_value` take an optional `stats` (a `ResolvedStats` or any `.get("ap"/"ad")` mapping; `ResolvedStats` imported under TYPE_CHECKING - engine.py does not import antitank, cycle-safe); NEW `_effective_magnitude(entry, stats)` = `base + ap*ap_ratio + ad*ad_ratio` when a seeded row meets stats, else base. SEEDED Gwen P (ap_ratio 0.0005) + KogMaw W (ap_ratio 0.0004); AD path proven via a synthetic test entry (no champion mis-seeded).
- **Additive guarantee:** `stats=None` (the default; the `/anti-tank` route passes no stats and was NOT touched) is byte-identical to item 308, as is any zero-ratio row even WITH stats injected -> NO ENGINE bump, NO downstream caller change, tight blast radius. `AntiTankResult` / `AntiTankSourceEntry` to_dict shapes unchanged (effective magnitude flows into existing `magnitude`/`value`; ratios live only on the registry entry).
- **TDD characterization-FIRST:** NEW `agents/daemon_slayer/tests/test_antitank_p3_2.py` (+24, RED-before-GREEN) - schema defaults, byte-identical static path, 12 un-seeded champs identical under ap=800/ad=800, seeded Gwen/KogMaw math at pinned AP, synthetic ap/ad/conditional, real-ResolvedStats==dict parity, exactly-2-rows-seeded.
- **Verify:** py_compile OK; DS-dir `agents/daemon_slayer/tests/` 6644 passed / 1 skip / 1 xfail / 1936 subtests; root `tests/` 5032 passed / 1 skip / 85 subtests / EXIT 0 (UNCHANGED - new tests are in the DS dir, live output byte-identical); ruff clean; `ds_share_sync.py` re-mirrored 315 files (--check 0); ASCII-only. Live: Gwen 0.85->0.95 @200AP / 0.85 @999AD; KogMaw 0.926->0.966 @200AP; Vayne 0.95 byte-identical @800AP/800AD.
- **NEXT (Phase D, gated):** the scaling is INERT until a caller passes stats - wire a live caster-stat producer into the `/anti-tank` route to ACTIVATE it, THEN bump ENGINE + restart DS (cdragon-seam precedent); seed the remaining caster-stat-scaled %HP rows (per-row scan open). The 6 UNIVERSAL_FILES convention update is still queued.

---

# 2026-06-05 - P2.2 tail: choices decode unified onto shared Pydantic CoachOutput [item 314]

Follow-on to item 313, completing P2.2. Non-engine, non-frozen; DS NOT restarted; RC restart-deferred (byte-identical wire). Full record = item 314 in `docs/LEDGER.md`.

- **Shared model:** NEW `core/coach_output.py` - Pydantic v2 `CoachOutput` + `decode_choices(raw) -> list`. The native-emit `choices` JSON decode was duplicated verbatim in all 4 coaches (aram/arena/brawl `_run_coach` + SR `_write_fields`); now one validated seam. The 4 sites call `decode_choices(fields.get("choices"))`.
- **Extractors NOT merged (by design):** base `parse_fields` and SR `_parse_response` genuinely diverge (key remapping, multi-line join, different markdown regex, no 220-cap, no positional fallback) and are each golden-mastered/item244-pinned; only the duplicated choices decode was unified.
- **Tests:** NEW `tests/test_coach_output_p2_2.py` (11 + 11 subtests) parity golden master (decode_choices == old inline block byte-for-byte). Updated the 4 emit tests' `ParserPassthroughTests` source guards to the new wiring + behavioral checks. Item 313's 38 golden masters stayed green.
- **Verify:** FULL `tests/` 5032 passed / 1 skip / 85 subtests / 0 failed; ruff clean; ASCII-only.
- **NEXT:** P3.2 (antitank dynamic %HP) + the 6 UNIVERSAL_FILES convention update remain queued. P2.2 COMPLETE.

---

# 2026-06-05 - P2.2 structured-output / Pydantic v2 hardening of the coach parse seam [item 313]

Operator-gated focused session (P2.2, accepted in item 312). Characterization-FIRST per the operator standing rule "rigid tests before swapping the parsing logic so we don't break the live coach pipelines." Non-engine, non-frozen; DS NOT restarted; RC restart-deferred (pure-Python validation swap, byte-identical wire). Full record = item 313 in `docs/LEDGER.md`.

- **Golden masters (no prod change):** `tests/test_parse_fields_characterization_p2_2.py` (25) pins `coaches/_base_coach.parse_fields`/`parse_field` - lowercase-key contract, markdown strip, 220-trunc, positional-fallback threshold + whole-line footgun, choices-JSON passthrough, parse_field case-insensitive/no-strip/no-trunc asymmetry. `tests/test_coach_choices_characterization_p2_2.py` (13) locks the exact `core/coach_choices` wire dict (to_dict/to_jsonable) shape-agnostically so it survives the swap.
- **Swap:** `core/coach_choices.CoachChoice` `@dataclass(frozen=True)` -> `@pydantic.dataclasses.dataclass(frozen=True)`. Chosen over a literal `BaseModel` AFTER I surfaced the blast radius (a BaseModel breaks 5 existing tests - 4 emit tests call `dataclasses.fields()`, `test_frozen_dataclass` expects `AttributeError` not pydantic `ValidationError` - plus `to_dict`'s `asdict`). The pydantic dataclass stays a TRUE stdlib dataclass -> `fields`/`asdict`/`FrozenInstanceError` all keep working = 0 existing-test edits, wire byte-identical, + construction-time validation gained.
- **Verify:** targeted 212 passed (incl. the 4 emit + frozen tests unmodified); FULL root `tests/` 5020 passed / 1 skip / 74 subtests. The ONLY red was PRE-EXISTING + unrelated (`test_doc_size_budget::test_roadmap_md_under_budget`: ROADMAP 85458>81920B - item 312 skipped the relocate-on-add convention); FIXED here by relocating item 294 + the DS source-layering plan verbatim to `docs/ROADMAP_HISTORY.md`. py_compile OK; ASCII-only.
- **NEXT:** P2.2 tail (deferred) - migrate base-coach `parse_fields` callers + SR `_parse_response` onto a shared validated model (golden masters now guard it); P3.2 (antitank dynamic %HP) is the queued sibling.

