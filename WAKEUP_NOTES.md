# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-14, orchestrated-run docs sync (relocated BOTH `2026-08-12` blocks - RM-190 decided + the 3-day-outage recovery; newest 3 = orchestrated run `2026-08-14` + new-project design QA `2026-08-13b` + /sync-all-md `2026-08-13`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-16c - RM-218 closed by refuting it: no vocabulary gap, a parser reading one pair out of many

**Shape: single-thread, TDD, Tier-1.** 12 tests first, RED at `8 failed, 55 passed`, GREEN at `63 passed`. DS 10684 / 13482 subtests, RC 19164 / 96 skipped / 4438 subtests, ruff clean.

**I FILED THIS ROW YESTERDAY AND ITS CENTRAL CLAIM WAS FALSE.** RM-218 said Meraki publishes derived aggregates the wiki does not publish. The pages say otherwise: Alistar Trample reads `{{st|Magic Damage Per Tick|{{ap|80/10 to 200/10}}...|Total Magic Damage|{{ap|80 to 200}}...}}` - the "missing" label is the SECOND pair of the same block. **The row inferred a DATA problem from a PARSER artifact, because the evidence it reasoned over was the parser's own incomplete output.** When instrumentation reports what it could not find, its list of what it DID find is not a survey of reality - it is a survey of the instrument.

**THREE MECHANISMS, ONE PARSER, AND THEY COMPOSE - which is why single-mechanism reasoning kept reading as a data problem.** (1) `parse_leveling_bases` did `block.partition("|")`, reading only pair one of an `{{st|}}` block. (2) An arithmetic endpoint (`80/10`, `40*12+40*3`) failed to parse and took the whole LABEL down with it. (3) A label embedding `{{ii|Death's Daughter}}` never matched the plain stored spelling. Alistar needed the split AND the arithmetic before EITHER of its labels resolved.

**THE ROW'S OWN FENCE WAS WRONG TOO:** it said "do not fold (B) into (A), they have different fixes". Same root cause - the 54 zero-label rows fell to 27 with no work aimed at them. **A fence written from an unverified mechanism fences off the fix.**

**Measured, both numbers, because a falling skip count is only good news if findings do not fall with it:** `skipped_labels` **357 to 109** (-69pct), `findings` ROSE 146 to **208**, stale 84 to 87, zero champions lost, and **zero existing findings changed value** - the parser added comparisons without perturbing settled ones. That last check is the non-regression proof that matters more than a green suite. Two net-new findings were verified against raw wikitext, not trusted: Ahri Q `{{ap|35*2 to 135*2}}` = 70-270 against a stored 80-280.

**Blast radius held deliberately:** the shared `_AP_WRAPPER_RE` in `daemon_slayer_wiki_ability_extract.py` was NOT touched - it is Share-mirrored and feeds the engine, so widening it is a Tier-2 change to a data PRODUCER. This reader got its own regex. Arithmetic is a whitelist AST walk with no `eval`; `2**9999999`, names and calls are rejected by test.

**One test relaxed after green, named rather than hidden:** `350*0.7` is 244.99999999999997, so exact equality became `pytest.approx`. The production path was already right - `_differs` compares within `_TOL` - and the over-precise assertion was the defect.

**I walked into a documented trap:** the first full suite after `ds_share_sync` reported 1 FAILED in `phase8_smoke/test_sr_draft_profile_engine.py`. That is the mid-suite DS-bounce artifact CLAUDE.md already warns about; confirmed transient by an 18/18 isolated run and a clean full re-run. **Let the Share sync settle before starting a suite.**

**Residue FILED as RM-220 (109 skips), and this time the mechanisms were verified against live wikitext BEFORE filing** - the direct lesson of having two rows in two days turn out to rest on inferred mechanisms. Three separated parts: **(A)** 27 zero-label rows caused by three more `{{ap|}}` forms the endpoint parser cannot read - a rank-count suffix (`{{ap|35 to 110 6}}`, Jayce), enumerated ranks (`{{ap|150|275|400}}`, Nocturne) and a named parameter (`|round=2`, Rumble); **(B)** a SMALL real synonym set - Ahri W's `Subsequent Flame Magic Damage` vs live `Subsequent Magic Damage` - which is the hypothesis RM-218 was refuted for, true of different rows than the ones it named, and explicitly not to be generalized since the same residue holds one-to-many splits (Ekko) and genuinely different quantities (Chogath); **(C)** a design question worth more than either - **an unmatched label may itself BE the drift.** Briar Q stores `Magic Damage` against a page carrying only `Physical Damage`. A stored label that no longer exists upstream is exactly the staleness this tool exists to find, and today it is discarded as "cannot compare". Next free id = RM-221.

---

# 2026-08-16b - RM-219 closed: the checker was asking the wiki for "MonkeyKing", and 10 champions were stale the whole time

**Shape: single-thread, TDD, Tier-1.** 10 tests first, RED at `13 failed, 38 passed`, GREEN at `51 passed`. DS 10684 / 13482 subtests, RC 19152 / 96 skipped / 4438 subtests, ruff clean.

**BEFORE AND AFTER, both live read-only full sweeps:** `skipped_pages` **101 to 1**, `stale` **74 to 84**, `findings` 127 to 146, and **zero champions dropped out of stale** - coverage added, none traded. Newly stale: Belveth, Kaisa, Khazix, Leblanc, LeeSin, MonkeyKing, RekSai, TahmKench, Velkoz, XinZhao. The one surviving page skip is Renekton E, a genuine per-ability case.

**THE REUSABLE PART IS WHY THE FIX ADDS A SPELLING INSTEAD OF REPLACING ONE.** 21 keys differ from their display name but only 20 failed. The 21st is Nunu, and a live probe showed `Template:Data Nunu/Consume` AND `Template:Data Nunu & Willump/Consume` BOTH resolve. The obvious swap would have been **green on all 20 headline cases** while silently betting that no Data page is titled by the key. **When a population splits 20/21, the odd one out is the design constraint, not a rounding error** - I only found it because the count of differing keys did not match the count of failures, and that mismatch was worth one probe.

**The row's own predicted trap also held:** a punctuation-stripping rule reaches 19 of 20 and misses `MonkeyKing` to `Wukong`. That is a named mandatory test, not one row in a parametrized sweep, precisely so it cannot be lost in an aggregate green.

**No new alias table:** `champions.json` was already sitting in the same patch dir the tool reads. **Check what the directory already holds before writing a mapping** - the fix needed zero new data and zero new fetches.

**DATA BACKFILLED IN THE SAME PASS**, per the CLAUDE.md rule that preventing future occurrences is not a fix while the corrupted rows stand: `ability_staleness.json` regenerated 74 to 84, then `ds_feed_index.py --write` AFTER the data moved (the ordering LEDGER 1266 was burned by), then `ds_share_sync.py`; both `--check` IN SYNC at 535 files.

**RM-218 counts were RESTATED, not left:** `skipped_labels` rose 323 to 357 because 20 champions became comparable. A rising number after a fix can be the fix working - but a follow-up row quoting the pre-fix figure would have started from a wrong population, so the row now says so at the top.

---

# 2026-08-16 - RM-216 closed: instrumenting a silent skip measured it at 3x the signal it was hiding

**Shape: single-thread, TDD, Tier-1.** Commit `d6fc0927`. Files: `tools/ds_wiki_staleness_check.py`, `tests/test_ds_wiki_staleness_check.py`, plus BACKLOG + LEDGER 1267. RED confirmed first at `8 failed, 33 passed`, GREEN at `41 passed`. Full `pytest tests` 19142 / 96 skipped / 4438 subtests, ruff clean.

**THE INSTRUMENTATION PAID FOR ITSELF IMMEDIATELY, AND THEN CORRECTED ME.** A live `--recent --days 3` run over 13 champions reported `stale=7 findings=11 skipped_pages=0 skipped_labels=31`, and I wrote that up as "the row led with the wrong half - the page site fires zero." **That was a sampling artifact and it is withdrawn.** A read-only `--full` sweep run later the same day to size the follow-up rows reports `checked=171 pages=754 stale=74 findings=127 skipped_pages=101 skipped_labels=323`, with **137 of 171 champions in at least one skip list and only 34 wholly clean.** The page site fires 101 times at roster scale and is the MORE severe half. **A `--recent` window is a convenience sample drawn from whatever the wiki edited lately, which systematically EXCLUDES the champions the tool cannot address at all - the population and the sample disagree precisely where the defect lives.** Size a defect on the population before you rank its halves.

**THE 101 PAGE SKIPS ARE NOT RENAMES EITHER - they are a title-construction bug, and it is the worst thing found this session.** `:473` builds `Template:Data {champion}/{ability}` from the DDRAGON KEY, so it requests `MonkeyKing`, `KogMaw`, `DrMundo` instead of `Wukong`, `Kog'Maw`, `Dr. Mundo`. **20 champions are 100 percent uncomparable and ZERO of them appear in `stale_champions`** - the report positively certifies 12 percent of the roster it never looked at. Filed RM-219. Note for whoever takes it: a punctuation-stripping fix passes 19 of 20 and looks done; `MonkeyKing` to `Wukong` is the case that no such rule reaches.

**THE LABEL SKIPS (323 at full scale) ARE NOT THE RENAME THE ROW PREDICTED EITHER, and that distinction is the reason not to widen the fix.** They are a systematic Meraki-vs-wiki VOCABULARY gap - 125 distinct unmatched stored labels, headed by `Total Magic Damage` (37) and `Total Physical Damage` (21), because Meraki publishes DERIVED AGGREGATES where the wiki publishes the COMPONENT: stored `Total Physical Damage` against live `Physical Damage per Hit` (Samira W), stored `Total Magic Damage` against live `Magic Damage` + `Magic Damage Per Tick` (Nasus E), six Gangplank R labels against one live `Magic Damage Per Wave`. Fixing that means a label-aliasing table, and there was zero test evidence for any specific alias. Left as a separate unfiled defect. **RM-216 was about the SILENCE, not about making the comparison succeed.**

**A THIRD CLASS SURFACED THAT NOBODY FILED AND NOTHING COULD SEE BEFORE:** 50 rows across 23 champions report `live labels []` - the page was fetched and parsed to ZERO labels. That is a parse gap, not a name mismatch, and it is only distinguishable because each skip row carries the labels that WERE found. **When you instrument a skip, record what the lookup DID find, not just that it missed** - the found-set is what separates a rename from a parse failure without a second live fetch.

**Design kept it Tier-1:** optional out-param accumulators rather than a changed return type, so the pre-existing `compare_champion(...) == []` assertion and every caller stayed untouched. Two negative-control tests assert the counters stay at zero on a healthy compare, so the guard cannot pass by always firing. `write_report` carries skip rows forward on a partial merge - the same hazard its own docstring already documents for findings - and recomputes counts from the MERGED lists, not the partial run's own.

**NOT done, deliberately:** no regen of `ability_staleness.json` (needs a live 173-champion sweep; a regen owes Share resync + `ds_feed_index.py --write` AFTER the data moves), so no feed-index churn. No Share resync owed at all - `tools/ds_wiki_staleness_check.py` is NOT in the mirror, checked by listing `Share/src/tools/` (14 files) rather than assumed.

**PROCESS COST, do not repeat:** the suite was run four times and only the uncontended runs agreed. One pass reported 3 ERRORs in `tests/test_unresolved_template_tokens_rm108.py`, another 1 FAILED in `tests/test_mission_control_server.py` - both files untouched by the change, both green standalone and green in the clean run. Two of those runs overlapped because a background suite was started and then a second suite was run in the FOREGROUND against the same ports and files. **Never report a full-suite verdict from a run sharing the box with another suite; on this machine RC + DS + Mission Control are live during every run as it is.**

**FILED, not fixed here:** RM-218 (label vocabulary gap, 273 rows page-found-label-unmatched plus 50 rows page-parsed-to-zero) and RM-219 (title construction, 20 wholly-uncomparable champions). **Take RM-219 first** - it is the one that certifies champions current without looking at them, and fixing it will make `stale_champions` RISE from 74, which is the fix working, not a regression. Neither belongs to RM-216, which is CLOSED; the instrumentation already exists, so do not re-file the silence and do not re-derive these counts by reading code - run the tool. **Next free id = RM-220.**

**Left alone on purpose:** `ROADMAP.md:40` still lists RM-203 as OPEN against a CLOSED record in BACKLOG + LEDGER 1265. The hand-off flagged it as a quick win for a session that owns that work, and this session did not.
