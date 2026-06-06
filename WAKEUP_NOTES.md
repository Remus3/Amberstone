# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) archived to docs/history_notes.md. Only the last 3 sessions kept here.

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

---

# 2026-06-05 - external refactor-plan triage + P4.2 Tesseract env-config + UNIVERSAL_FILES cleanup [item 312]

Operator handed 3 Desktop review docs (`Claude_Refactor_Plan.md` + `Riot_Commander_Review.md` + `Riot_Commander_Deep_Dive.md` - external AI audits) to read + act on, plus a `Desktop\UNIVERSAL_FILES\` cleanup. Docs kept OUT of repo (`feedback_keep_outreach_out_of_repo` - competitor/strategy/outreach content). Full record = item 312 in `docs/LEDGER.md`.

- **UNIVERSAL_FILES cleaned to the 6 originals:** 19 item-310 lolmath scratch artifacts -> gitignored `_scratch/uf_dump_item310/` (reversible; hard-delete on request); `BRIEF.md` -> `Desktop\` (out of folder + out of repo).
- **5-phase refactor triaged (proposals = INTENT, verified vs live code):** SHIPPED **P4.2** `RC_TESSERACT_CMD` env override (`core/vision_tesseract.py`, +5 CI-safe tests, byte-identical when unset). REJECTED **P3.1** (amp-DRY already done in `effects.py` - both dps.py/burst.py import it) + **P5.1** (em-dash ban is the settled PS-ParseFile rule). GATED: **P1.2/P1.3/P4.1** (frozen files), **P2.1** FastAPI rewrite, **P5.2** SQLite ledger. ACCEPTED own-session: **P2.2** (live coach parse + partly redundant), **P3.2** (antitank dynamic = design change).
- **Loop-relaunch (operator Q):** the Gemini director reads repo-only (commits + LEDGER/ROADMAP tails + claude.done + last audit), NEVER the Desktop; it picks ONE bounded item/cycle. To route any accepted item through the loop, pin it in ROADMAP NOW.
- **NEXT (operator-gated):** P2.2 + P3.2 focused sessions; update the 6 UNIVERSAL_FILES templates to current conventions; frozen-file + big-rewrite phases need explicit approval.
- **WRAP (/done):** deleted merged remote branch `origin/refactor/pickban-routes` (0 unique commits, no PR; only `origin/main` left) + stale `Desktop\todo.md` (Win1=item295/Win2=item296 shipped) + `Desktop\BRIEF.md`. Set ROADMAP NEXT-UP block (item-311 cdragon extractor fix is priority 1) + queued 2 NEW items: daily upstream content-drift poll, phone monitor/loop remote-control (Tailscale dashboard already monitors from a phone). Loop STOPPED ("max_cycles 1"); relaunch via `ops/loop/config.json` max_cycles + `launch_loop.ps1`.
