# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-28m - R222 RM-125. The tool I shipped in slice A had a bug, and slice B found it.

**Cycle 29, gemini-loop. Tier-1. ENGINE-IMPACT NONE - no DS math, no schema, no served path, no `ENGINE_VERSION`, no `:8893` bounce, no RC restart.** HEAD `c7900b8c` -> `4ef1a805`. RC 13935 passed / 106 skipped / 1342 subtests, fresh.

**The premise held for once, and I checked before dispatching.** The directive tagged its own headline claim `[UNVERIFIED]`. A whole-file byte scan read **3153** non-ASCII chars across **31** `.js`/`.css`/`.html` files against the 3154 filed in ROADMAP prose - off by one, substantially correct - so the unit was real rather than a no-op. `tools/p3_ascii_sweep.py` re-read and confirmed `ast`-based Python-only, which is why it has never once looked at `web/`.

**The directive's 4-agent parallel block was REFUSED and the cycle ran SERIALIZED.** The executor override flagged colliding write sets. It was right for a second reason it did not give: slice A is a genuine PREREQUISITE, not a peer - its tokeniser DEFINES the comment/live partition that slice B censuses, so B could not have run first or concurrently and produced a correct answer.

**Slice A** shipped `tools/web_ascii_sweep.py` (JS `//` + `/* */` with string/template/regex awareness, CSS `/* */`, HTML `<!-- -->` only), TDD RED 2 failed / 34 passed -> GREEN 36, sweeping 2833 comment chars for 3153 -> 320. The false-positive side was MEASURED, not claimed: the verifier built two deliberately broken copies of the sweeper and watched the escaped-quote pin and the CSS-string pin each go red. The live half was proven untouched two independent ways - the verifier wrote its OWN tokeniser before reading the slice's, sentinel-replaced every comment span in both trees (0 of 28 files differed outside a comment), then eyeballed all 253 changed lines.

**Slice B is a docs slice that found a code bug, which is the shape worth remembering.** Its census showed the tool's 320 over-counts the RENDERED set - 59 were unreachable JS comment glyphs and 26 sit in `legacy_index.html`'s inline blocks - leaving **235** rendered chars across 16 files: STRIP-candidate-deferred 152, KEEP-deliberate-UI-glyph 52, **LOAD-BEARING 31**. Tracing why those 59 were unreachable is what exposed the defect.

**Slice C, unplanned: `_scan_template_subst` had no regex-literal case.** The `.replace(/"/g, "&quot;")` attribute-escaping idiom inside a `${...}` opened a phantom string that ate the closing brace and backtick, and three template literals ran away. Failure direction is UNDER-sweep and that was measured, not assumed (shipped-only comment territory was 0 bytes in every file, so no live byte could ever have been stripped) - but `tests/test_web_comment_lines_ascii.py` was passing VACUOUSLY over those regions, which is the guard-reports-green-by-not-looking class. Repro RED 4 failed / 1 passed first; the fix extracts `_scan_comment` and reuses the existing `_regex_may_start` predicate rather than copying the regex-vs-division heuristic, and caught a second instance of the same blindness the audit missed. Residue 320 -> 261.

**`_LIVE_HALF_DIGEST` is CIRCULAR across a tokeniser change and was not re-stamped blind.** The partition delta was proven gains-only (114 spans gained, 0 lost), the corrected classifier was run over BOTH trees to show byte-identical live halves for all 168 sources, and only then was the constant re-captured with its provenance comment rewritten to say what it now actually pins.

**Two things that must survive into the next session:**
1. **31 glyphs are LOAD-BEARING - a strip breaks BEHAVIOR, not looks.** `web/js/lib/items_index.js:62` carries `U+2192` as an alternation branch in the build-string split regex, and `web/js/panels/right_now.js:563-566` is a producer/matcher COUPLING where the three emitted glyphs are exactly the char class the next line's regex tests; the file's own comment at `:562` names the failure ("double DEFEAT"). Read `docs/RM125_web_live_glyph_adjudication.md` before touching one.
2. **`web/legacy_index.html` is NOT dead** - the opposite of the brief's hypothesis. `dashboard/routes_static.py:23-41` serves it at `?ui=legacy` AND as the automatic fallback when `index.html` throws. Its glyphs are live pixels. It also holds a raw `U+0081` C1 control char in a `content:` value at `:951` - mojibake, not design.

**Defect class closed, not just the directory.** Class = "non-ASCII in authored `.js`/`.css`/`.html`". Repo-wide byte scan found exactly ONE authored file outside `web/`: `tools/usage-mcp-server.js`, 218 -> 9, swept with the live-span text asserted byte-identical pre/post, and the guard widened to cover it. Everything else that scanned dirty is third-party (`data/meta_build` scraped pages, `.obsidian` vendored plugin) and is OUT-OF-SCOPE with reason in the commit body.

**NEXT:** RM-125 stays OPEN for the 235 rendered chars ONLY, routed to RM-122 (operator-present, rendered-pixel judgement, headless-forbidden). Do NOT let a future directive re-open the comment half - it is done and machine-guarded.

---

# 2026-07-28k - R220 competitor lift. The directive's target was fenced, and the best find was ours.

**Cycle 27, gemini-loop. Tier-0 docs-only. ENGINE-IMPACT NONE (repo + live DS both 1.262.0, no bounce, no Share sync).**

**The directive named "Overlay App F or Aggregator B live-game overlay" and three places on disk say do not.** `ROADMAP.md` RM-01 retires the rotation by name; the R100 and 2026-07-16 blocks in `COMPETITOR_LIFT_INDEX.md` both declare the live-overlay family DRAINED (the second counting five passes); Overlay App F already has two teardowns in `docs/_archive/`. So the INTENT was kept and the TARGET rotated, which is what the drain notes themselves instruct. Replacement picked by search, not preference: six keyword probes across every prior `COMPETITOR_LIFT_*.md` returned zero hits for wave management, wave simulators, CS trainers, minion waves, freezing, slow pushing. Lane / wave / minion-economy had never been looked at.

**Three premise corrections, all verified against files, and the first one matters beyond this cycle:**
1. **The laning `hold` band ALREADY SHIPPED.** `core/precomputed_laning_coach.py:68-74` carries five labels, `laning_band()` at `:271-309` implements the precedence off `_HOLD_LOW`/`_BACK_OFF`/`_TRADE` (`:79-81`). Only the raw engine is still 4-band (`agents/daemon_slayer/matchup.py:184-206`). **The open Lane-A work is the FLIP, not the band.** Any brief still saying "the vocabulary lacks a hold band" is stale.
2. **The Live Client emits `MinionsSpawning` and RC has never read it.** `dashboard/_state_cooldowns.py:18` names it; `:20-21` then passes an EMPTY event list because it wanted summoner-spell events that do not exist. Repo-wide grep returns that one comment.
3. Corpus is 2966 matches, not 3005.

**Deliverable `docs/COMPETITOR_LIFT_2026-07-28.md`, 7 findings. F1 filed as ROADMAP RM-124 (new, unbuilt):** a deterministic wave + cannon clock anchored on the live event - structurally `core/decision_detector.py:158-176` with a piecewise cadence - as a 4th event extract beside `dashboard/_liveclient.py:302-313` plus a pure `wave_callout()` beside `core/event_callouts.py:414`. Tier-1, no new data source, no key, no Claude, no schema lift, no ENGINE bump. **Its risk is real and is written into the row: three sources disagree on first-wave time (0:30 / 1:05 / 1:30) and the cannon breakpoint (14:00 / 15:00), and a 2025 change moved first-cannon arrival 2:05 -> 2:35** - anchor on the live `EventTime`, validate the cadence table in one real game before any flip. F4 CLOSED, data-blocked three ways (no minion entities on `:2999`, GEP gives kill counts only, Match-V5 has no minion event type) - do not re-pitch a live wave state machine.

**The best finding was RC-internal and the HAVE column found it by accident: RC renders a complete wave feature nobody built.** `web/js/panels/next.js:16-83` is a finished 3-lane FREEZE/TRADE/CRASH/DISENGAGE readout whose only writers repo-wide are test fixtures (`scripts/rebuild_sim_fixtures.py:166,191,229`) - it has rendered the "-" sentinel in every live game ever played. Five more producer-less identifiers beside it (`wave_state_now`/`wave_control`/`wave_freezes`/`cannon_cs_summary`/`gd_at_15`), plus an ARAM tier-shift rule that is dead because its live call site passes `wave_pct=None`. **Durable lesson: a rendered surface with a plausible name is not evidence of a producer, and the fixtures that make it look alive in tests are exactly what hides that.**

**Tempering note, in the RM-124 row so nobody oversells it:** `tools/hz_shadow_report.py:196-201` excludes crash/freeze/push from the laning agreement sample, so a wave clock will NOT move the Lane A number.

**Honest negative:** there is no standalone wave-simulator product. Six search angles, three targets torn down properly instead of eight skimmed. Realistic yield of this category is two findings plus two negatives.

**Gates (fresh, `-n 8 --dist loadfile`): DS 10100 passed / 5701 subtests; RC 13829 passed / 106 skipped / 522 subtests; 23929 total, 0 failed** - byte-identical to the R219 baseline, expected for docs-only. 0 non-ASCII across all touched docs. Plan tail-window protocol honored (R219 block relocated verbatim to `docs/ORCHESTRATION_PLAN_HISTORY.md`; newest row 9439 bytes from EOF vs the 16000 cap). ROADMAP 76513 / 81920.

**NEXT:** RM-124 is a clean Tier-1 slice - the event extract, the pure callout, and one live game to validate the cadence before any flip.

---

# 2026-07-28j - R219 DS sweep. The directive's truth source does not contain the truth.

Gemini-loop cycle 26. Full detail in `docs/LEDGER.md` 1098. Commits `1fb60109` +
`a77e1cee` (work) + this sync. Two `core/` slices: no engine, no ENGINE bump, no DS
path, no Share mirror, no restart, no route or panel.

- **The ordered sweep had no data to sweep against, and that is measured.** The
  directive said "champion base stats vs Meraki bulk truth".
  `data/daemon_slayer/16.14.1/items_meraki.json` is 320 ITEMS whose key census across
  all 320 entries is exactly `name/id/tier/rank/removed/simpleDescription/passives/
  active/shop/noEffects` - no `stats` block anywhere and no champion half. The mirror
  was fetched with an effects-shaped projection, which is right for how DS uses it (a
  Meraki clause lives in the effects PROSE field), but it means the Meraki side of a
  stat comparison does not exist offline. Re-aimed both slices at the DDragon mirror.
  A real Meraki champion sweep needs a mirror refresh with the champion endpoint and
  the full stat projection - data plumbing, its own slice.
- **A prose-based substitute produced a fake 178 and is recorded so nobody rediscovers
  it.** Matching `move ?speed` against `str()` of the `passives` structure scored
  Doran's Shield and Recurve Bow. Prose is a source for CLAUSES, not a stat census.
- **ENGINE-IMPACT corrected BUMP -> NONE, on precedent.** Both modules are in `core/`,
  import no DS, and no DS path reads them. R135 (LEDGER 962) already made this exact
  correction for `core/champion_movespeed.py`. The 7 bump sites went untouched and the
  pre-commit gate agreed on its own: "no mirrored DS source staged - skipping Share
  sync".
- **Neither slice found a wrong number. Both found a correct population with nothing
  defending it.** That is the outcome worth carrying forward: when a sweep finds the
  data already right, the deliverable is the guard that makes the next drift loud -
  and the guard is only worth shipping if its teeth are demonstrated rather than
  claimed. Slice A fabricates a zeroed champion and watches the universe grow; Slice B
  swaps `_FALLBACK_MS` for a `-1.0` sentinel so the 28 champions whose real movespeed
  IS 345 cannot mask a fallthrough. Without that sentinel the coverage test would have
  passed while measuring nothing.
- **Slice A**: all 9 DDragon-zeroed champions enumerated off disk. 5 have overrides, 4
  (Ambessa/Naafiri/Yunara/Lillia) are correct without one. The guard parses the mirror
  for its universe and never reads `CHAMPION_INFO_OVERRIDES.keys()`, which would be
  circular; every champion goes through the three REAL consumers.
- **Slice B**: `_FALLBACK_MS = 345.0` was justified as "the most common base MS".
  Measured: the mode is 335 (42 of 173), 345 is fourth (28). Prose fixed, constant
  KEPT - "conservative for reachability" is separately true (345 is at or above 165 of
  173), so moving it to the mode would contradict its own purpose. Zero executable
  lines changed.
- **The best thing this cycle produced is filed, not built - RM-123.**
  `agents/daemon_slayer/burst.py:124-127` claims no champion sits between melee and
  ranged and picks 350 on that basis. Eight do; Urgot sits exactly on the strict-`>`
  boundary; and the engine already has a canonical split at 250 in `ehp.py:254` that
  `rank.py` documents as authoritative. Two thresholds for one concept, disagreeing on
  Rakan/Lillia/Urgot in a live rune-scaling branch. Tier-2, ENGINE-IMPACT BUMP.
- **The orchestrator's own brief carried a defect and only the tree-level gate saw
  it.** I told Slice A to `skipTest` when the mirror is absent. The mirror is TRACKED,
  so an absent one is a broken tree, not an absent capability, and
  `tests/test_skip_condition_hygiene.py` failed it as a B5 masking skip - the RM-119
  class that "reports green by not running". The slice agent passed it and so did its
  verifier, because both were scoped to the slice, where the two files run 100 passed.
  Run the full suite even when the tier rules say a two-file `core/` change is exempt.
- Gates: full dual `-n 8 --dist loadfile` **23929 passed / 106 skipped / 6223 subtests
  / 0 failed** in 130.89s, ruff clean, 0 non-ASCII in the touched files. ROADMAP
  doc-budget warn is PRE-EXISTING (77489 bytes / 94.6 pct before this cycle); R219
  relocated the RM-119 skip audit and compressed RM-113, landing at 77229 - below
  where it started, still over the 90 pct threshold. ~3500 bytes of relocation left,
  its own unit.
