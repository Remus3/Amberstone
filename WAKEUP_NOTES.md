# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-12, the five-slice DOC SYNC wrap (relocated `2026-09-11c`, the 8-cycle loop run stopped by operator STOP, VERBATIM via `scripts/wakeup_prune.py --keep 3`, proved line-set-identical against the archive addition rather than eyeballed; newest 3 = `2026-09-12b` the five-slice merge, `2026-09-12a` RM-412 C1 OSS extraction, `2026-09-11d` the lane-8 pre-flight). The prior pass at this line relocated `2026-09-11b` and `2026-09-11a` the same way. The 2026-09-11k RELOCATION DUE note that sat here is DISCHARGED and deleted - the file is back at keep-3. The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-12b - FIVE slices merged (RM-233 / RM-296d / RM-313 / RM-318 / RM-295a+b), and THREE filed specs were wrong in ways that mattered

LEDGER 1400-1404. Five `--no-ff` merges on `main`: `14c5b4571` (RM-233),
`adfcb195a` (RM-296d), `d7596d3d2` (RM-313), `8b688761f` (RM-318),
`1cb82683e` (RM-295a+b). All Tier-1, ENGINE-IMPACT NONE across all five - no
`ENGINE_VERSION` move, no DS `:8860` bounce, no Share mirror, no frozen file.
This session was DOCS ONLY: no source file was touched and nothing was pushed.

**WHAT SHIPPED, one line each.** RM-233 - `core/match_db.py` reads the WAL
pragma result, `save_match` widened to `-> bool` (still never raises), negative
`get_recent` limit clamped at the MODULE boundary. RM-296d - the three
`push_*` flags on `/api/loadout/apply` are PARSED, not bare-truthy. RM-313 -
`championId` routed through `_as_int`. RM-318 - a coercion seam over the six
decision detectors, NOT a bare except. RM-295a+b - `health()` exposing the
three staleness globals, `coverage()` adopted rather than deleted.

**THE DURABLE PART IS THAT THREE FILED SPECS WERE WRONG, and each was
corrected rather than followed.**
1. **RM-295a's `stale_for_s` parenthetical said "now minus `_LOADED_AT`".**
   `_LOADED_AT` is the **RETRY** stamp and is bumped by a refresh that landed
   nothing, so following the spec literally ships a staleness signal reading
   **`0` during the exact outage it exists to report**. Shipped code measures
   from `_LAST_GOOD_AT` and keeps the row's two key names.
2. **RM-295a's `source()` fence gave a REASON that is false in both halves.**
   "`dashboard/routes_duo_synergy.py` and the UI badge both read them" - that
   file has **ZERO** `source()` calls and there is no non-test `.source()`
   caller on the module repo-wide (re-probed at merge, independently of the
   slice). **The FENCE STANDS anyway**, on the row's own second reason plus the
   guard-widening ground. A dead reason is not a dead fence.
3. **RM-260 is STALE IN ALL THREE CITATIONS** - `performance_tracker.py:406`
   is not the key read (`:500` is), `experimental_builder.py:237` is not the
   `%s` site (`:241` is), and both hook functions moved. Its premise holds; its
   headline does not, because a `_redact` helper is now live at `:531`. Filed
   as RM-418 for RE-FILING, not building.
   **RM-255 is outright REFUTED at HEAD** - `lib/http/client.py` FAILS CLOSED
   (`:30`, `:111-113`) and `certifi==2026.2.25` IS at `requirements.txt:2`;
   closed same-day by lane 8 cycle 27, LEDGER 1293. Filed as RM-419 so nobody
   re-attempts it.

**A REFUSAL WORTH MORE THAN THE FEATURE: the `stale:live` / `stale:static`
prefix on `source()` was BUILT, MEASURED and DELIBERATELY REFUSED at merge.**
It shipped in `95c5fa2fa` and was reverted in `b51b05092`. The ground is not
taste - **shipping it REQUIRED widening the guard at
`tests/test_smoothed_rates_101qq_lock.py:375` so the change could pass**, and a
change whose cost is editing the test that exists to forbid it is a change the
guard already answered. Now guarded from BOTH sides: that lock test is
untouched and byte-identical across both slice commits, plus an inverted test
asserts the prefix is ABSENT and the domain is still exactly `live|static|none`.
**DO-NOT-RE-PITCH.**

**THREE CAVEATS RECORDED RATHER THAN SMOOTHED AWAY.**
- **RM-233's non-`wal` WARN branch is UNFALSIFIABLE on this host.** This
  platform returns `wal`, so the verifier confirmed the branch READS the
  pragma - **not that it ever EMITS**. RM-413 inherits this limit for its 8
  sibling sites; do not claim the emit half is covered.
- **"byte-for-byte" on the `source()` revert was REFUTED as worded.** The
  function text grew **162 -> 1573 chars** (docstring only); executable body
  AST-identical, return domain unchanged. **The overstatement was the MERGER's,
  introduced in the verifier's own prompt** - the worst place to put one.
- **RM-313's one-pass acceptance is deliberately UNMET.** Only `championId`
  shipped, because the census found TWO LIVE consumer defects on ONE field
  (`champ_select.js:3516` badged the WRONG ARENA PLAYER AS ME; `:3523`/`:3612`
  read `"0"` as truthy) and that does not generalise by assumption. Siblings are
  RM-417, each needing its own census - and `arena_teams() :195` PARTIALLY
  LIMITS the `:3516` repair, since that line reads `arena_teams[].cells[]` first.

**TWO SUITE FIGURES, BOTH RECORDED WITH THE REASON so nobody later reads them
as a contradiction.** Merger's own run over the merged tree and all five slice
suites = **518 passed, 63 subtests**. Independent verifier's narrower combined
run = **394 passed, 60 subtests**. The **entire** delta is one directory versus
one file: the merger ran all of `tests/phase_b_champ_select`, the verifier ran
the single file inside it (12+145+**171**+151+25+14 = 518 against
12+145+**47**+151+25+14 = 394). Same tree, same result, different scope.

**SEVEN NEW ROWS FILED, ids RM-413..RM-419, pin advanced to RM-420.** RM-413
(8 more WAL-discard sites), RM-414 (5 more bare-truthiness route sites, two
inverting intent into the dangerous direction - `routes_state.py:773` turns the
seam ON with the correct `_parse_tristate` helper sitting FOUR LINES BELOW;
`routes_coach.py:226` engages the coach kill-switch AND PERSISTS it), RM-415
(the `or {}` idiom, 17 sites / 4 modules), RM-416 (wire `health()` - it shipped
with NO consumer, which is RM-295b's own mistake, so it is filed rather than
repeated silently), RM-417, RM-418, RM-419. **Each carries its
EXCLUDED-AFTER-CHECKING set** so the ruled-out candidates are not re-filed.

**DOC-SIZE NOTE, stated because the first pass got it backwards.** Appending
five closures plus a seven-id filing row GREW `ROADMAP.md` 67973 -> 70938. The
pass continued until it showed a net reduction rather than stopping there: six
rows relocated VERBATIM to `docs/ROADMAP_HISTORY.md` (`## 2026-09-12` block),
each proved byte-identical against `git show HEAD:ROADMAP.md` rather than
eyeballed. Final **68372 bytes**, 83.5 percent of the 81920 budget, +399 on the
session. RM-295 and RM-296 were edited IN PLACE, not relocated, because each
closed only PARTIALLY (RM-295c and RM-296a/b/c/e remain OPEN).

---

# 2026-09-12a - RM-412 SHIPPED: C1 of the OSS extraction blueprint is EXECUTED, and the verifier refuted the builder's "all green"

LEDGER 1399. Code commit `48ac8986a`, 17 files, +1619/-23. Tier-1,
ENGINE-IMPACT NONE, no RC restart required.

**WHAT SHIPPED.** `oss/win32_atomic_io/` - a stdlib-only src-layout package
holding `_replace_with_retry`, `_scratch_path`, `_write_then_replace`,
`atomic_write_json` / `_bytes` / `_text` and `read_json_dict`, extracted from
`core/polled_json.py`. **`core/polled_json.py` is UNMODIFIED and its diff is
empty** - 20-plus live importers, so the package is a SIBLING, not a
replacement. `PolledJsonFile` deliberately EXCLUDED (`core/polled_json.py:204`,
ZERO production instantiations; RM-264 holds adopt-or-remove). New guard
`tests/test_oss_win32_atomic_io_drift.py` pins the two copies by
AST-normalized EXECUTABLE LOGIC over 7 functions plus the retry-delay
constant - docstrings and comments ignored, because the RC-specific prose was
deliberately scrubbed for sharing - and declares exactly ONE textual
allowance, the log-message prefix, with an arm asserting EQUAL hit counts on
both sides so it cannot widen into a blanket forgiveness. Also touched:
`.github/workflows/ci.yml`, `docs/OPERATIONS.md`,
`tests/test_ci_collects_orphan_suite_trees.py`,
`tests/test_skip_condition_hygiene.py`.

**FINDINGS - these are the durable value, not the code.**
1. **An independent verifier REFUTED the builder's "all green"** and found a
   hard red the builder never reported: adding a tree to `_TEST_TREES` obliges
   a same-commit row in the `docs/OPERATIONS.md` test-scope table, which calls
   itself authoritative. Fixed in the same commit.
2. **The empty-enumeration false green, hit LIVE.** 16 repo-root-enumerating
   guards returned **317 passed** and proved nothing - they enumerate the GIT
   INDEX (ADR-015) and the new files were untracked, hence invisible.
   `git add -N` surfaced **2 real failures**.
3. **The one real sibling-name leak was in `__pycache__`, not source.** Source
   swept clean over 31 banned identifiers x 3 variants plus a 17-term domain
   probe; the `.pyc` files embedded the absolute repo path and leaked the
   project name - invisible to a `git` publish, SHIPPED by `tar` / `cp -r`.
   Deleted, and the package now carries its own `.gitignore`. **Residual: that
   sweep is TRANSIENT - any pytest run repopulates `__pycache__`.**
4. **A self-contradicting license, built by this session.** The package
   declared itself all-rights-reserved and "not yet distributable" inside a
   PUBLIC repo whose root `LICENSE` grants Apache-2.0 - the exact
   self-contradicting-repo trap CLAUDE.md's own license gate warns about,
   committed against our OWN tree. Fixed with a byte-identical Apache-2.0 copy
   (sha256 `5bfe6fb7f5a2`, grantor line `Copyright 2026 Moonbeam` present and
   unedited), declared in `pyproject.toml`, plus three guards.
5. **Docs corrected to match real behaviour, not the reverse** (the drift guard
   pins logic, so prose moved): TWO degraded inputs are silent, not one; a bare
   `PermissionError` catch means `EACCES` DOES fire the retry on POSIX (4
   attempts / ~275 ms on an ACL denial); and "never left behind" is false for
   `SIGKILL` / `taskkill /F` / power loss.

**TWO LIMITS STATED, NOT PAPERED OVER.** `py.typed` is verified STRUCTURALLY
only - `setuptools` is absent from this interpreter, so no wheel was ever
built and the marker has never been observed inside an artifact. And a
package-local `.gitattributes` pinning `eol=lf` was REQUIRED: `core.autocrlf=true`
plus a root `.gitattributes` covering only `*.py` / `*.md` would have checked
the new `.gitignore` out as CRLF in a fresh clone - green locally, red on clone.

**MEASURED on a frozen tree after every agent exited:** package suite 38
passed; drift guard 51 passed; `tests/test_docs_operations_test_scope_rm322.py`
3 passed; `tests/test_polled_json_lane8_cycle24.py` +
`tests/test_atomic_write_fault_injection_is_portable.py` 37 passed;
index-dependent guards 75 passed once staged; `ruff check` clean; 0 CR / 0
non-ASCII; `core/polled_json.py` diff empty; pre-commit `py_compile OK (9 files)`.

**NEXT SESSION**
(a) Narrow the `PermissionError` catch to WinError 5 / `EACCES` - a LOGIC
    change, so it needs a SAME-SLICE edit to BOTH copies (the drift guard pins
    them) and its blast radius is `core/polled_json.py`'s 20-plus importers.
(b) Install `setuptools`, build a wheel, and OBSERVE `py.typed` inside the
    BUILT artifact. Re-reading the source layout is the check that already passes.
(c) DECIDE whether `core/polled_json.py` should ADOPT the package rather than
    duplicate it - that retires the drift guard, and it inverts the
    "sibling, not a replacement" property RM-412 shipped on purpose. Do NOT do
    it as a tidy-up inside another slice.
(d) Still carried from `2026-09-11d`: Slice D block-mode follow-up, Slice E
    residuals, `ops/loop/control/STOP` still present, and the
    `moon_sync_inbox` Apache-2.0 file awaiting license-gated evaluation.

---

# 2026-09-11d - operator-directed lane-8 pre-flight: 4 hardening slices shipped, 5 directive claims refuted or already-shipped

LEDGER 1398 (`2026-09-11k` there). NOT a loop cycle: operator-directed while
`ops/loop/control/STOP` sat on disk. Worktree `lane/true-audit`, merge sha in
LEDGER 1398 at wrap. Tier-1, ENGINE-IMPACT NONE, RC restart required. 7
agents, 993884 subagent tokens, 18.4 min. Verifier: 9 pytest commands, 0
failed / 0 errors; `py_compile` OK on all 8 changed files; ruff clean; 0
non-ASCII, 0 CR bytes.

**TRIAGE FIRST - five directive claims did not survive it.** (1) REFUTED:
`dashboard/_state_builder.py` "duplicate `/activeplayerrunes` request tax" -
zero rune hits in that file. (2) REFUTED: "move `PolledJsonFile` onto
`NamedMutex`" - `core/polled_json.py:204` records ZERO production
instantiations (RM-264 holds adopt-or-remove); `ops/loop/winmutex.py` has NO
`NamedMutex` (only `hold()` `:51` + `MutexTimeout` `:46`); both byte-pinned,
nothing changed. (3) orphan tree wiring = RM-407, ALREADY SHIPPED today. (4)
split-form sibling-name scanner = RM-399 (`tools/sibling_name_sweep.py:113`),
ALREADY SHIPPED. (5) `SHARED_SHA256` pins MATCH live bytes. STOP (operator
17:32, "No cycle 9") deliberately NOT cleared - clearing re-arms the loop,
the arming halt point. `RUNNING.lock` pid 22888 = electron.exe, left alone.

**SLICE A - RM-234 CLOSED as DEDUPE.** `game_reader/snapshot_normalizer.py`
derives `my_runes` from `runes_full` via new pure `_runes_text_from_structured`
(`:136-164`, `:596`); second GET gone. `tests/test_rm234_runes_single_get.py`
8 tests RED "got 2" -> GREEN; 38 named existing tests green; refuter PASS.
PREMISE CORRECTION: BACKLOG RM-234 and LEDGER 1117 claimed "no production
consumer of `my_runes`" - FALSE, `coaches/aram_coach.py:430` + `:1031` feed it
into the Haiku prompt. True only for `runes_full` / `stat_shards`.

**SLICE B - FROZEN `app/_state_authority.py`, operator-named, refuter APPROVE.**
`calc_win_pct` +6/-3: keeps str, decodes bytes, skips int/None/dict/list;
`tests/test_calc_win_pct_type_clamp.py` 23 tests, mutation-red. Correction:
`app/_game_lifecycle.py:465-467` already caught the crash - effect was STALE `win_pct`.

**SLICE D - `tools/precommit_gate.py` +129, `RC_ATOMIC_WRITE_GATE` warn
(default) / block / off.** 43 tests (41 red with the scanner reverted); gate
family 90 green. Whole tree: strict 4 hits / 2 files, lenient 11 / 9. BLOCK
MODE NOT VIABLE YET, and that is the finding - the BACKLOG row carries the
false-negative / false-positive lists and the `ops/` + root scope gap.

**SLICE E - `item_advisor.py` +45/-11.** H1 REAL (failed loads cached as `{}`
for the process lifetime, no log - now not cached, one WARNING per path); H3
REAL (fully-bought curated champion read "Unknown champion" - now gates on
`CHAMPION_BUILDS`); H2 aliasing REFUTED. 14 tests, mutation-red 8. The
directive's `:79` / `:89` cites belonged to `coaches/_arena_item_advisor.py`,
NOT edited. **OSS extraction blueprint** (operator message) ASSESSED, NOT
executed: C1 extractable, C2 partial, C3 NO (byte-pinned across three repos,
API mismatch, carries the known sibling-name escape). Filed to BACKLOG.

**NEXT SESSION**
(a) Slice D block-mode follow-up: `ops/` + root into scope, fix the hunk-level
    `str.replace(` exemption, one red-first case per listed false negative.
(b) Slice E residuals: `dashboard/_liveclient.py:455` predicate;
    `coaches/_arena_item_advisor.py:73-90` + `:110-127` H1 pattern.
(c) `ops/loop/control/STOP` is STILL PRESENT - operator decides whether to
    clear it before the next loop launch.
(d) `moon_sync_inbox` 2026-09-11-1415 `lw_write_tracer.py.from-lw` (Apache-2.0): license-gated evaluation pending, not vendored.
(e) Inert stubs `r._read_my_runes = lambda: ""` at `tests/test_liveclient_championstats_ingestion.py:163`
    + `tests/test_p2w1_app_a.py:61` - harmless, deletable in a later cleanup.
