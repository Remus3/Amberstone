# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-29, RM-222 pass (relocated `2026-08-16d` - markdown organizing; newest 3 = RM-222 flat-pen layout guard `2026-08-29b` + upstream processing `2026-08-29` + RM-221 mirror-rule `2026-08-16e`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-29b - RM-222: the flat pen axis gets the live-vs-pinned layout guard the percent axis has had since it broke

Commit `e5b5c9e6`, Tier-1, one test module plus its Share mirror. No engine change, no
`ENGINE_VERSION` bump.

**The gap was real and asymmetric.** `test_pen_pct_catalog_r160.py` compares live
`data/meta/ddragon_items.json` against the pinned `data/daemon_slayer/16.15.1/items.json`
under a `_PINNED_CARRY_FORWARD` allowlist. `test_magic_pen_flat_catalog_r153.py` had NO
layout test - confirmed by enumerating its 9 `def test_` names, not inferred. The percent
axis got hardened because it broke; the FLAT axis stayed quiet while carrying the only
live divergence in either sweep (item 3175, RM-190 carried 18 -> 20 with the snapshot left
pinned). A second such move would have landed silently.

**Measured before the allowlist was written, not copied from the row:** both layouts sweep
10 ids and diverge on exactly `{'3175': ('20', '18')}`. Predicting it is not measuring it.
**Proved non-hollow three ways** - a wrong magnitude, a wrong id, an empty allowlist each
turn the guard RED - then the file was restored byte-identical, sha256 checked both sides.
Two of the three new tests make that permanent rather than a one-time authoring act:
`_layout_divergences` is a free function taking both sides, so one test perturbs live and
one asserts a VANISHED divergence is caught (the half that makes a stale entry go red after
a snapshot bump - an RM-223 trigger).

**Do NOT redo:** the fence held - the flat regex was NOT folded into R160's pattern tuple.
Both Share doc recitals (`21 skipped`, `10684 collected`) were already refreshed from a
FRESH mirror run. `docs/DAEMON_SLAYER.md` needed nothing; RM-210 already deleted its recital.

**The one RC `tests/` red is NOT a regression and must not be "fixed" by bumping the pin.**
`test_cli_version_still_matches_the_pin` moved skip -> fail since LEDGER 1272 because
Legion's `claude.exe` got FIXED: it now runs, reports 2.1.251 against `PINNED_CLI =
"2.1.220"`, and correctly fires the genuine-drift branch. The guard is right in both states;
that is also why the skip tally moved 97 -> 96. The pin needs the undocumented-flag canary
re-run first, which needs an authenticated CLI - still blocked on `claude login`.

**Measured this session:** DS **10687 passed / 13483 subtests / 0 failed**, collect-only
10687. RC `tests/` 19177 passed / 96 skipped / 1 failed (the CLI pin above). Share mirror
**8251 passed / 0 failed / 24 skipped / 11124 subtests**. `ds_share_sync --check` in sync at
529 files; `drift_guard` 0 breaches; ruff clean; hygiene 14 passed.

---

# 2026-08-29 - upstream processing: a 4-day CI red, DDragon 16.17.1 into the engine, and the Share mirror off its knowingly-red baseline

Operator asked to "check for upstream changes and updates and process them". There were
TWO upstreams and both were unprocessed.

**CI had been red for four days, and the cause arrived by `git pull`.** Commit `39ba69c8`,
authored by `weekly-rc-health@anthropic-routines` - a CLOUD routine, not a Legion task -
carried 27 non-ASCII bytes. Cloud clones have no `core.hooksPath`, so `precommit_gate.py`
never sees these files; CI is the only gate, and it had been failing since 08-25.

**DDragon 16.17.1 (mirror auto-pulled 08-26, nothing downstream run).** Canonical partition
holds at 706 / 173 in BOTH patches. Four percent-pen magnitudes moved and every one is on an
Arena-band `22xxxx` id - all four SR twins held. Exactly ONE reaches the registry: Serylda's
Grudge Arena `226694` armor pen 40 -> 45. It MOVES DEFAULT OUTPUT: the Arena planner now
prefers it over Lord Dominik's `223036`, diffed field-by-field rather than assumed. ENGINE
1.278.0 -> 1.278.1, 150 anchored sites / 128 files, provenance recitals verified untouched.

**The thing to carry forward: I got the Share-mirror history WRONG and the repo corrected me.**
I reported the mirror's 2 failures as an unnoticed 17-day regression that read "green
throughout". LEDGER 1271 refutes that in writing - RM-221 MEASURED those exact two reds on
08-16, diagnosed them correctly, and deliberately declined to exclude the test, reasoning that
excluding it would delete a true signal. They were known and accepted on purpose. The narrower
true statement: nobody ran the mirror suite at RM-190 time, and `--check` verifies FILES, not
TESTS. **Read the ledger before characterising history; a "nobody noticed" claim is a claim
about the record, and the record was right there.**

The fix is not the exclusion RM-221 refused: magnitude parity now SKIPS only where the live
catalogue is absent, so the signal survives where it can be evaluated. Gated on the
`SHARE_MIRROR` sentinel, NOT `_META_CATALOG.is_file()` - that file is TRACKED, so a skip on its
absence is an always-passing guard, and `test_skip_condition_hygiene` caught it on my first
attempt. Mirror 8256/2-failed -> **8251 passed / 0 failed**.

**The ASCII recurrence had a mechanical cause nobody had named:** the guard's own docstring
prescribed `strip_smart_quotes.py`, which has no notion of U+2713 - the dominant glyph these
routines emit. The prescribed fix could never clear the guard, so all three incidents were
hand-repaired. New `tools/sanitize_agent6_reports.py` + 11 tests; `docs-guards` elevated to
JOB-level `contents: write` with a fenced auto-repair step.

**NEXT SESSION should know:**
- **RM-225: the auto-repair branch has NEVER fired.** Only the clean early-exit path has run.
  Do not describe it as proven.
- **RM-222: the FLAT pen axis has no live-vs-pinned layout guard** - and it is the axis that
  already carries a divergence (3175: 18 pinned vs 20 live). The percent axis got hardened
  because it broke; the flat one stayed quiet.
- **The `claude` CLI binary is FIXED; the OAuth session is NOT, and that is the bigger problem.**
  The npm install shipped a 500-byte SHELL-SCRIPT STUB where `bin/claude.exe` should be - an
  interrupted install had left the real 253 MB `claude-code-win32-x64` package sitting in npm's
  `.claude-code-lEZNDFsD` staging dir, never moved into place. `npm install -g
  @anthropic-ai/claude-code@latest` fixed it (now a real 207 MB binary, reports 2.1.251) and
  npm reclaimed the staging dir. npm config was clean throughout - not a `--ignore-scripts` or
  `--omit=optional` misconfiguration. **The stub's "not compatible with the version of Windows
  you're running" message was Windows failing to exec a shell script as a PE, NOT an
  architecture mismatch - do not chase that.**
  **STILL BROKEN, and operator-only:** every CLI binary on this box fails with `Failed to
  authenticate: OAuth session expired and could not be refreshed` - measured on BOTH the npm
  2.1.251 and the desktop-managed 2.1.247, so it is NOT version-specific. `~/.claude/.credentials.json`
  exists and was touched 2026-08-29 09:47, so presence is not the issue. **Headless `claude -p`
  therefore cannot run AT ALL on Legion**, which takes out the whole `ops/loop` headless program,
  not just one test. Needs `claude login`; I will not perform a credential action.
- **`test_cli_version_still_matches_the_pin` is now legitimately RED on Legion** (2.1.251 vs
  pinned 2.1.220) and that is CORRECT - the broken binary had been masking it. **Do NOT bump
  `PINNED_CLI`:** its contract requires the propagation canary with a negative control first, and
  the canary needs a working authenticated CLI, so it is blocked behind the login above. CI is
  unaffected - `claude` is not on PATH there, so the test skips.
- **RM-226: `stop_claim_gate` blocked THIS session and could not be satisfied.** It admits
  counts only from test-runner output, so a figure quoted off disk while CORRECTING it reads
  as fabricated; and it scans the whole transcript, so retraction cannot clear the line. Do
  not edit that gate from a session it is blocking.
- **`gh run watch --exit-status` returns 0 on a CANCELLED run.** I reported a cancelled `ci`
  as passing before reading `conclusion`. Read the conclusion field, never the watch exit code.
- DS stays PINNED at data patch 16.15.1 while live DDragon is 16.17.1. `:8860` reporting
  16.15.1 is CORRECT - do not file it as drift (RM-223 tracks the accruing carry-forward debt).

---

# 2026-08-16e - RM-221: the Share mirror's exclusion list becomes a RULE, and reproducing first corrected four of the row's particulars

Closed RM-221. The reviewer's own Start-here command now reports **8256 passed, 2 failed,
15 skipped, 11133 subtests in 96s** on a clean copy unpacked outside the repo and
deliberately RENAMED to `ds-engine-review`, against 58 failed / 5 errors before. Both
survivors are the SAME RM-190 divergence on item 3175 Spellslinger's Shoes - engine 20
flat magic pen, pinned 16.15.1 snapshot states 18 - reported engine-side by
`test_magic_pen_flat_catalog_r153.py` and feed-side by `test_pen_pct_catalog_r160.py`.

**The row was right that the package was broken and wrong about four particulars, and the
only reason that surfaced is that I reproduced before building.** (a) The filed **73 is not
reproducible from the bytes**: a copy that KEEPS the name `Share` gives 58. The 15-failure
delta was an ancestor-directory-NAME check in four engine tests, so the number moved when
the reproduction renamed the folder. (b) **Four** files import `core`, not six, and all four
do it DEFERRED inside test bodies - which is why the pre-existing guard stayed green
throughout: its `_CORE_IMPORT` was anchored at column 0 because "only a collection abort
counts". True, wrong bar. (c) The two biggest offenders are neither a `core` import nor a
`data/meta` read - `test_health_damage_coupling_rm91.py` (50 of 58) and
`test_item_proc_heal_rm103.py` (all 5 errors) pin the historical 16.14.1 snapshot, and
`test_antitank_axis_score_invariance_r196.py` is a host-tree POPULATION scan. (d)
`test_pen_pct_catalog_r160.py` was filed as a packaging artifact and is the same TRUE
signal as r153 - excluding it would have deleted it, the exact trap the row raised for r153.

**Shipped:** two rules in `tools/ds_share_sync._is_host_dependent_test` (any-indent `core`
import; an AST check for a `data/daemon_slayer/<patch>` read other than the shipped patch,
in two shapes only) plus ONE named entry for r196 with its reason written down. Rule 2's
narrowness is MEASURED: a blunt stale-patch-literal scan hits 10 modules and 8 of them pass,
because they build their own snapshot; the shipped rule hits exactly 2 with 0 false
positives. Also the `SHARE_MIRROR` sentinel the generator emits, replacing the name check in
all four tests, pinned `eol=lf` in `.gitattributes` so `core.autocrlf` cannot fail `--check`
on the next clone.

**Two things worth carrying forward.** The sentinel sites walk `parents` NON-INDEXED on
purpose: `tests/test_skip_condition_hygiene.py` credits that exact form as a tree-shape
capability and names the case "is this the Share mirror" in its own source. My first attempt
indexed `parents[3]`, resolved to a suffix-tracked artifact, and turned all four skips into
class-B5 DEFECTs - caught by the RC suite, not by inspection, and fixed on the guard's own
terms rather than by buying an `_ALLOWLIST` exemption. Second: the first mutation probe of
the new snapshot guard SURVIVED, because flipping `_PATCH` moves the generator and the guard
together - an EQUIVALENT mutant. Re-aimed at a generator that stops applying the rule, it
goes red. All four guards are mutation-proved with non-equivalent mutants.

**Gate note that cost a re-run:** the DS suite under `-n 8` reports 19 failures, ALL in
`test_ehp_family_seams_reach_the_client_rm115.py`, which drives the shared live DS `:8860`
server; serially the same tree is **10684 passed / 13482 subtests, 0 failed**. Run that file
serially or expect phantom reds.
