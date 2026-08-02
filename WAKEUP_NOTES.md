# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-02a - RM-140 was a no-op ingest and a ten-gap reconcile; RM-141 answered as JADE

2 commits, pushed (`d59bad88`, `50f8b35a`). Tier-1, NOT the Tier-2 the row assumed.
Zero ENGINE bump, zero Share sync, zero DS bounce. RC + RC-LCUAgent both restarted and
both process start times verified to POSTDATE the edited files (pid 18636 / pid 116).

**The finding worth carrying: a green `upstream_drift_check` proves less than it looks.**
It compares upstream-now against upstream-LAST-RECORDED. It says NOTHING about whether RC
actually ingested what it recorded. All 5 signals read `ok`, so the ingest half was a
genuine no-op - but that was only establishable by probing the on-disk half separately:
mirror `--check-changed` = 7365 assets `new=0 chg=0 fail=0`, the DS extract manifest at
`data/daemon_slayer/16.15.1/manifest.json` (173 champs / 706 items), and `:8860` `/health`.
Probe those three, never infer them from a green drift check.

**Shipped**
- **RM-140** (LEDGER 1160). All the value was in reconciling the queue map BACKWARDS.
  RM-128 grounded it one way (every mapped id still exists upstream) and refuted the
  converse for whole GROUPS - correctly. But `gameSelectPriority > 0` (the client's own
  menu-placement field), restricted to `kARAM` + `kSummonersRift` and excluding `kCustom`,
  makes the narrow converse implementable, and it found **ten real gaps**: the ARAM Mayhem
  family beyond 2400 (`2401/2403/2405/2410/2450`) and SR `870/880/890/893` + `710`.
  870/880/890 OUTRANK the legacy 830/840/850 RC had mapped - RC was on the superseded bot
  ids. Guarded by a `coverage_candidates` census + `CoverageCensusTests`, mutation-proved
  RED at exactly those ten. Map 21 -> 34. Operator also directed TFT `1090/1100/1130`.
- **RM-33 CLOSED-STALE** - `auto_ops_verbs` exists in NO code or config (prose only), the
  95 percent gate has no meter anywhere, and `OVERLAY_BUILD_MASTER_PLAN.md:169` had already
  recorded it as an EXPLICIT PARK. ROADMAP just never caught up.
- **NEXT-5 triage banner** in the NOW section, each blocker probed rather than inherited.
- **Doc-budget repair** `85488a9f`. This session's own additions pushed ROADMAP to 96 percent
  of its 81920-byte budget and `drift_guard` breached. Relocated VERBATIM to
  `docs/ROADMAP_HISTORY.md` rather than loosening the check: 96 -> 90 percent, guard clean.

**RM-141 is ANSWERED, not built - and that distinction is deliberate.**
The same probe surfaced a `kJade` group (17 client-visible "Classic" queues) the row's three
readings did not have; put to the operator, who picked it. "League Classic" = Riot's JADE
throwback mode. JADE is upstream-present on four surfaces and `docs/history_notes.md:701`
predicted this exact moment. It is a large build and gets its own session AFTER RM-142.

**Do NOT redo**
- Do not widen the coverage census to `kAlternativeLeagueGameModes` - RM-128 refuted that by
  measurement and eight already-mapped ids sit there under three different mode_keys.
- Do not re-ask what "League Classic" means. Do not re-open RM-33.
- `3280` (kCustom), `1101`/`1102`, Brawl `2300`-`2305` and all of `kJade` are DELIBERATELY
  unmapped, each with the reason written at the site. None is an oversight.
- `BACKLOG.md:47` still carries the REFUTED "Jade_ rows are aliases" wording; the correction
  is `docs/history_notes.md:697`. Re-derive from `agents/daemon_slayer/mode_variants.py`.

---

# 2026-08-01g - /insights triage: two of three "ambitious workflows" were already shipped, the third became RM-143

6 commits, pushed. Tier-0/1. DS engine untouched (server.py was mutated twice for proofs and
reverted both times; `git status` clean each time).

**Shipped**
- **RM-143 P1+P2+P3** (LEDGER 1159). Spec `ca7e194c`, map `dda07d08`, runner `3e2fd192`.
  REPORT-ONLY, nothing armed. Live parity 8/8 at ENGINE 1.268.0.
- **`tools/repo_insights.py`** `ca6a0799` + `2a47480e` - ledger regex missed the paren-form
  header (0 items -> 419), plus a generated synthesis section and two label fixes.
- **README** `15dfe4e1` rewritten for an outward reader: why-it-is-different, a Limitations
  section, upstream source credits, and the Riot non-affiliation disclaimer it never had.

**The useful finding: /insights re-pitches shipped work, because it reads transcripts not the repo.**
Of its three "ambitious workflows", the refute-executor is R7 + Session Default + the director's
PREMISE-CHECK + `verifier.md` + `truth_gate.py`, and its one novel delta was ALREADY MEASURED
(14 agents over 124 gated rows, 2026-07-18, closed 6). The nightly fleet is `RC-CIWatchdog` +
`RC-UpstreamDriftCheck` + `RC-WeeklyHygiene` + `lanes.py`. Every `claude_md_additions` item it
suggested is already in CLAUDE.md. Only the parity harness was real work.

**Do NOT redo**
- Do not re-spec the parity harness or add a third client-reachability guard: two exist
  (`test_route_seams_reach_the_client*.py`) and P1 deliberately asks the server-vs-ENGINE
  question they cannot ask, because their `_SEAM_PREFIXES` filter hides transports.
- Do not arm P4 yet. It waits on several quiet real DS batches, and `--arm` must never exit
  non-zero on SKEW.

**Next:** P4 when the observation window is satisfied; otherwise the top open ROADMAP row.

---

# 2026-08-01f - five non-gated rows, and the verifier caught three of my own defects

1 commit, pushed. Tier-1. DS untouched. Full `tests/` 17831 passed / 108 skipped / 0 failed.

**Shipped** - RM-128, RM-130, RM-131, RM-132, RM-134 (LEDGER 1157).
- **RM-134** `dashboard/_errors.send_error` stops leaking `str(exc)[:200]`; one back-compatible
  edit covers 21 call sites and BOTH surfaces (`mc/routes.py` splices the same handlers into
  `:8895`). Leak proven end-to-end through the MC route first, then fixed. 7 of 8 tests kill
  the old body.
- **RM-131 + RM-128** take `tools/upstream_drift_check.py` from 3 signals to 5. Both
  fingerprints are SHAPE-only - a value-sensitive signal would report drift every single run,
  which is the same as reporting nothing.
- **RM-130** 24 `U+2192` in `tft/` -> `->`, byte-level so the mixed CRLF/LF survived.
- **RM-132** met its acceptance and is still INERT - see below.

**Three defects the adversarial verifier found in my own work**
- **RM-132's token reference can never resolve.** `--fs-ov-chip` is on
  `body[data-shell="overlay"]`; both widgets `documentElement.appendChild(...)`, so they are
  SIBLINGS of `<body>` and custom props inherit downward only. Renders fine (the 13px fallback
  is load-bearing), tracks nothing. I reasoned about the scope and still got it half wrong.
  Filed **RM-139** with three costed routes and a computed-style acceptance.
- **A tautological test.** The qq carry-forward case re-implemented
  `upstream_drift_check.py:387` in its own body. Rewritten to exercise `advance_sentinel`
  against a tmp sentinel; mutation-proven red, plus a negative control.
- **An overclaiming docstring.** RM-128's offline half does NOT catch a regroup between two
  known groups (mutant M2 survives); only the live fingerprint does. Docstring says so now.

**RM-128's filed acceptance was REFUTED in two places** - implementing it as written would
have shipped a forever-red test. (a) 16 kARAM / 256 kAlt records vs a 21-entry map, so
"every live kARAM/kAlt id must be mapped" is impossible. (b) 8 ids (900/920/1020/1400/1700/
1710/1750/1900) sit in `kAlternativeLeagueGameModes` while mapping to sr/aram/arena -
`gameSelectModeGroup` is a client MENU grouping, not a mode classifier.

**Two process notes**
- The LEDGER-1155 lesson repeated the same day: the first full run went RED on
  `test_web_ascii_sweep.py` (RM-132 moved the web LIVE-half digest), invisible from any
  touched-module scoping. Re-captured per the file's ritual after measuring 173 sources on
  both sides. **Run the repo-wide guards whenever a web/ byte or a test FILE changes.**
- The Stop gate flagged my wrap summary and was RIGHT: I called the queue snapshot
  "committed" while it was `??` and HEAD was unchanged. Retracted the wording, parser untouched.

**Do NOT redo**
- Do NOT reinstate either refuted half of RM-128's acceptance. Both are measured.
- Do NOT "fix" RM-132 by adding the overlay type tokens to `:root` without reading RM-139 -
  the body-scoping is deliberate (the `tokens.css` >=16px floor is relaxed only in overlay).
- A bash ANSI-C quoted grep for the arrow (a raw U+2192 inside `$'...'`) does NOT expand the
  escape - it reports a false 0. Count with ripgrep `-o`; ripgrep `--count` gives LINES,
  not occurrences (14 vs 24 here).

**Next (operator-directed at wrap 2026-08-01):** THREE things in one session, orchestrated
subagent-first / parallel as standing protocol requires.
1. **RM-140** - a COMPLETE upstream patch + data check / ingest / coverage-expand pass. This
   is the INGEST half; RM-128/RM-131 shipped only the DETECT half. Probe `current.txt` +
   ENGINE_VERSION + DS `:8860` `/health` + the now-5-signal `ops/runtime/upstream_drift.json`
   before anything else. Never `--force` a Meraki re-extract.
2. **RM-141** - QA THE OPERATOR on "League Classic" before scoping it. Three readings are on
   the table (the `CLASSIC` gameMode / SR depth, a distinct legacy-client offering, or the
   retired-mode class). Ask, do not guess.
3. **Then the next 5 open items** as usual: RM-135 (backup of irreplaceable single-copy data -
   big enough to own a session), RM-139 (overlay tokens unreachable from documentElement),
   RM-133, RM-122 residue, or the DS RM-118 wireable seams (exactly 4).
4. **AFTER 1-3 are done AND cleared, a WHOLE SESSION dedicated to nothing but
   `ops/audit/P6_LOLMATH_PARITY.md`** (184 lines, operator-appended 2026-06-15). Own session,
   not a slice appended to this batch - the operator asked for it explicitly. Highest-priority
   slice in the doc is **G1: DS builds the WRONG damage axis on 20 champions** (18 AD-on-AP
   kits incl. Gwen / Teemo / Rumble / Diana, plus Pyke / Taric inverse), which is a
   correctness bug, not a tuning gap. Inputs are in-repo: `ops/audit/LOLMATH_VS_DS_SWEEP.md`
   + `ops/audit/lolmath_ds_sweep/` (reproducer; `npm install` to re-scrape, `node_modules`
   gitignored). **The doc's own numbers are STALE by design and it says so** - it cites engine
   1.120.0 / patch 16.12.1 against today's 1.268.0 / 16.15.1, so RE-DERIVE off live
   `data/daemon_slayer/current.txt` + `:8860` `/health` + the current `build_orders_sr.json`
   before acting on any row. Tier-2: ENGINE bump, four doc anchor sites, Share mirror, dual
   suite. Root-cause-first, validated PER CHAMPION (Engine/Build Conventions hard rule - a
   single generic ADC-crit shape is exactly how the last two build fixes shipped incomplete).
