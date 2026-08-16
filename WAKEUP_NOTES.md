# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-14, orchestrated-run docs sync (relocated BOTH `2026-08-12` blocks - RM-190 decided + the 3-day-outage recovery; newest 3 = orchestrated run `2026-08-14` + new-project design QA `2026-08-13b` + /sync-all-md `2026-08-13`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-16d - markdown organizing pass: the Share package's own Start-here command had not exited green for weeks

Structure and contents sweep over every tracked `.md` outside `docs/_archive`, plus a
full rewrite of both READMEs. 42 files, 451 insertions, 249 deletions; exactly ONE
non-`.md` file touched (a guard I broke and fixed, below).

**The find that justified the session was not a doc fact.** `Share/README.md` and
`Share/docs/05_AUDIT_AND_REFACTOR.md` both promised that the package's own Start-here
command exits green - "0 failed, 0 errors, exit code 0. The plain command exits green -
no pytest flag, no `--ignore` list." Measured on a genuinely clean copy (`Share/` copied
out of the tree, run from its own `src`), reproduced identically twice: **8376 passed,
73 failed, 5 errors, 11182 subtests**. An external reviewer's FIRST action produces 73
failures against a doc promising none.

**Root-caused by opening them, not inferred.** Three classes, all packaging-exclusion
gaps and none an engine defect: `ModuleNotFoundError: No module named 'core'` (host
application, deliberately not shipped); a missing `data/meta/ddragon_items.json` (live
upstream mirror, not the pinned snapshot - `Share/src/data/meta/` does not exist); and
`test_changelog_tracks_engine_version.py` looking for `agents/daemon_slayer/CHANGELOG.md`
while the package ships it at the package ROOT one level up. The generator already drops
66 of the repo's 429 engine test files; these 11 should have gone with them. **Filed as
RM-221**, with the fence that matters: a TWELFTH failure is CORRECT and must survive any
fix - `test_magic_pen_flat_catalog_r153.py` reports Spellslinger's Shoes at 20 flat magic
pen against the pinned 16.15.1 snapshot's 18, which is release 1.277.1 working as
designed. Excluding that file would delete a true signal. Deselect command shipped in the
README is verified, not asserted: it leaves 8152 passed and exactly that one subtest.

**A first-run measurement was invalid and I threw it away rather than publish it.** The
in-repo run gave 53 failed; that is not the claim's condition, because in-repo the
catalog sweeps read the repo's refreshed mirrors. Re-ran from a real clean copy. The
first clean run was also truncated by my own `tail -20`, which is why only 13 of 73
FAILED lines were visible - re-ran with full capture before writing any number.

**Recital drift, deleted rather than refreshed** (three sites, same disease):
`docs/DAEMON_SLAYER.md` carried `10653 tests` twice; RM-210 was filed at "stale by 27"
and by closing had drifted twice more to 31, which is the row's own argument. Both
recitals gone, replaced by the measure command; `docs/ARCHITECTURE.md` stops calling the
banner drift-guarded for counts no guard pins and now names what IS guarded. RM-210 CLOSED.

`docs/DS_SWEEP_TRACKER.md` had accreted **five layers of superseded RM id-pointer
corrections that contradicted each other** - one line read RM-208, another asserted
RM-205 was "CURRENT as of 2026-08-15". Each layer was a dated correction of a pointer
that then went stale itself. Relocated verbatim to `history_notes`; replaced with one
pointer re-derived across the working tree AND all three lane branches (RM-221) plus the
derivation command, since the doc's own advice is to derive it.

**Majority is not authority.** 17 of 20 `tools/*.md` carried a SUBAGENT-FIRST block that
`CLAUDE.md:226` explicitly marks SUPERSEDED - it cites the retired "Subagent-First
Protocol" heading and omits the self-adjudicating / self-adversarial point entirely. The
audit called the 17 "current" and the 3 "drifted" on a head count, and my first
instruction to an apply-agent repeated that. **The agent refused half of it and was
right**, then propagated the superseded block to two more files anyway, making it 19.
Resolved by merging the canonical block from `CLAUDE.md` "Session Default" itself and
writing it to all 20 plus all 20 `.claude/commands` mirrors; parity byte-identical.

**Three MUST-FIX audit findings were REFUTED and deliberately not applied** - all one
class: `core/_rune_stat_grants.py`, `core/zoi_mia.py`, `lcu/lcu_events.py` are cited
inside green-field proposal and refutation contexts, so they do not exist ON PURPOSE.
One exists in neither the claimed old nor the claimed new location. Applying those
"fixes" would have corrupted three records of work being correctly refused. **The lesson
is the shape: a path that resolves to nothing is not automatically a broken citation -
read the sentence around it.**

**I broke a guard and fixed it rather than dropping it.**
`tests/test_ds_share_changelog_freshness.py` parsed `- <old> -> <new> - ` release
BULLETS out of `Share/README.md`; converting that section to a table broke it. Its own
failure message says to update the pattern rather than drop the check. Widened to accept
both shapes and **mutation-proved it still has teeth** - removing the newest row drops
the parse to 1.277.1.

**READMEs.** `Share/README.md` 33473 -> 15889 bytes while gaining accuracy: its Release
history was reproducing 25 full CHANGELOG entries verbatim, ~21 KB duplicating the file
it points at, now a six-row index into the 66-entry `CHANGELOG.md`. Both READMEs gained a
Contents index (21 anchors, all verified to resolve). Main README's mode list corrected -
a fifth rotating-game-mode path (URF / One for All / Nexus Blitz) is routed in
`core/game_snapshot.py` and flag-enabled in `config/feature_flags.json`, phrased as
"unexercised, not unreachable" per the CLAUDE.md fence.

**Also fixed:** `docs/API.md` documented `/api/cooldown-watch`, a surface REMOVED to pass
Riot review (compliance-relevant), and listed two Mission Control `:8895` routes under
`:8888`; ARCHITECTURE said 6 scored axes where `server.py` registers 11, and 13 residual
`.after()` files where there are 3 (all frozen); `DS_COMPLETENESS_GAP` had a staleness
banner 94 engine versions stale, now a pointer; ADR-004 had two contradicting Status
lines; two handoff docs hardcoded a machine name CLAUDE.md forbids recording and claimed
Tailscale was not installed (the binary is on disk); `PORTABLE_PROJECT_CONVENTIONS`
budget table (40/60 KB) read as this repo's limits, actually 60/80.
`docs/HEADLESS_LOOP_SPEC.md` archived - a true orphan describing a retired vendor as a
live participant. Quick win taken: ROADMAP RM-203 was OPEN against LEDGER 1265.

**Measured this session, never quoted:** DS **10684** collected, RC `tests/` **19260**
collected, `/health` 1.278.0 / 16.15.1 / 173 / 706. Gates: `drift_guard` 0 breaches;
CI-selected doc-guard set **1521 passed, 0 failed**; zero em-dash / en-dash / smart
quotes in every changed file. **Next free id = RM-222.**

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
