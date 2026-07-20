# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-20g - R141 RM-100 CLOSED: asyncio leak accepted as a priced tradeoff

**Head `bacc559f` (`ba23bae0` is the content commit). ENGINE-IMPACT NONE** - Tier-0 docs +
guard-verify, no ENGINE_VERSION bump (stays 1.228.0 / patch 16.14.1), no Share resync, no `:8893`
bounce owed, no route change.

Gemini-loop cycle 4. This cycle answered the PART-C escalation R140 wrote: R140 closed the
consolidation half of RM-100 and deliberately left the LEAK half standing, so something had to
decide fix-or-accept. **Decision: option (B), leave it LATENT - and the reason is a priced trade.**

The fix has a known shape and a known price: narrow `pw_browser` off `scope="session"`
(`tests/snapshot_panels/conftest.py:246`) and pay a browser launch across ~387 snapshot_panels
tests, permanently. What that buys is bounding a leak that is **already bounded** by
`PlaywrightContextManager.__exit__` (measured py3.14 + playwright 1.59.0, recorded in R137) and that
has **zero live trigger** - no bare `asyncio.run(` calls exist under `tests/` at all. Bad trade.

Accepting a latent bug is only defensible if a test fails the moment it stops being latent. It does,
and it was re-run THIS cycle rather than inherited from the escalation text:
`tests/test_asyncio_isolation_guard.py` = **7 passed in 2.57s**, pinning both invariants (no bare
`asyncio.run(` under `tests/`; no sixth local runner copy).

`ROADMAP.md:20` is now a CLOSED bullet that states the tradeoff, its price, and the guard, with an
explicit do-not-re-pitch. That sentence is the deliverable - it is the same stale-prose failure mode
R140 root-caused, one level up: an open-reading bullet with no verdict re-picks every director cycle.

**One deliberate deviation, logged not silent.** The directive said mark RM-100 fully CLOSED. The
RC-GeminiAudit `0xC000013A` last-run result is still genuinely UNPROVEN (six hypotheses refuted), so
it rides inside the closed bullet as a labelled watch-item. Writing "closed" over an unproven fault
in a living doc is a false claim, and living docs are where false claims compound.

No subagents / worktrees (R9 inline - one ROADMAP bullet, one plan row, one guard run). Fresh
verification: **RC 12290 passed / 23 skipped / 359 subtests in 1325s** (exit 0), ruff clean, zero
non-ASCII bytes on any added line. LEDGER 979.

---

# 2026-07-20f - R140 RM-100 consolidation: CLEAN / REFUTED-PREMISE

**Head `60ee6289`. ENGINE-IMPACT NONE** - docs-only Tier-0, no ENGINE_VERSION bump (stays 1.228.0 /
patch 16.14.1), no Share resync, no `:8893` bounce owed. Doc-hygiene guards 13/13 green.

Gemini-loop cycle 2, directive R140: fan out worktree agents to consolidate 5 near-identical local
`_run_coro` / `_run_poll_loop` copies into `tests/_asyncio_isolation.py`. **Nothing was built, because
the work had already shipped one cycle earlier in this same loop run** (R137, `114977ee`).

Refuted on ground truth before any dispatch: `tests/_asyncio_isolation.py` on disk since 03:23
(`run_coro` + `run_coro_capturing_thread`); grep for `def _run_coro` / `def _run_poll_loop` /
`def run_coro` returns ZERO local definitions under `tests/` or `agents/`; all 5 named files already
import the shared runner; `tests/test_asyncio_isolation_guard.py` already blocks a sixth copy and
pins zero bare `asyncio.run(` under `tests/`. Fresh this run: **73 passed in 3.71s**.

**The real defect was the stale prose that manufactured the directive.** `ROADMAP.md:20` still read
"(5 near-identical copies; consolidating them is the open follow-up)" - R137 shipped the code but
never cleared the text, and the director builds its refill digest from ROADMAP prose, so a follow-up
closed in code but open in prose re-picks every cycle. That line now states CLOSED, names the shared
module and both runners, names the 5 migrated files, and cites `114977ee`.

The RM-100 **LATENT half is deliberately left standing**: `tests/snapshot_panels` still leaks
asyncio's per-thread running-loop marker via its `scope="session"` `pw_browser` fixture, so a new
test calling bare `asyncio.run()` on the main thread still fails. Closing consolidation is NOT
closing the leak - do not conflate them.

No subagents / worktrees (R9 inline - the build slice was cancelled by ground truth). PART C durable
steer in `ops/loop/control/gemini_ask.txt`: this loop has now produced several refuted-premise cycles
(R114, R115, R137, R140) from the same lag, so the director is asked to ground "X is still open"
premises in a grep checked THIS cycle rather than digest prose.

---

# 2026-07-20e - R139 Share/ external-presentation pass

**Head `a700b414`. ENGINE-IMPACT NONE** - docs and presentation only, no DS path, no ENGINE_VERSION bump
(stays 1.228.0 / patch 16.14.1), no `:8893` restart owed. `tools/ds_share_sync.py --check` green throughout.

Gemini-loop cycle, directive R139: read the entire `Share/` package end-to-end and raise it to external-presentation
quality, credit upstream data sources explicitly, keep the sync guard green. Two worktree slices, Claude sole merger,
verifier gate CONFIRM/CONFIRM before merge (6 of 6 factual spot-checks independently re-derived).

**The directive's premise was already on disk.** It claimed the Riot credits were missing from `Share/README.md`;
they have been there as a four-row "Sources of truth (credited upfront)" table at `Share/README.md:19-32`. Following
the brief literally would have shipped a duplicate credit block. The real defect was one section below it.

**The guard was green over a five-versions-stale public doc, by design.** The README "Changelog (recent)" list topped
out at `1.222.0 -> 1.223.0` against a live 1.228.0 engine. `_doc_anchor_rules` in `tools/ds_share_sync.py` deliberately
EXCLUDES changelog history from the anchor auto-rewrite - so the `**Engine version:**` header stays fresh forever while
the release list beneath it rots silently. Worth remembering the shape: an anchor guard that covers the header but not
the body makes staleness invisible rather than loud. Five hand-written bullets now cover 1.224.0 through 1.228.0, each
grounded in the matching `Share/CHANGELOG.md` entry; the CHANGELOG preamble gained the upstream credit it never had.

**Docs half was the heavy half:** 100-plus stale `file:line` citations across `Share/docs/01..05` plus
`Share/lolmath_ingest/*` (104 table citations and 27 route refs in `02_FUNCTION_REFERENCE.md` alone), and every drifted
count re-derived against live ground truth - 172/705 -> 173/706 champs/items, 13 -> 20 snapshot JSONs, 328 -> 339 test
files, RUNE_PROCS 19 -> 20, NON_DAMAGE_BLOCKS 7 -> 9, `_effects_data.py` 5335 -> 5843 lines, explicit AA cast times
61 -> 49. One correction was substantive rather than numeric: `04_GAPS_AND_ROADMAP.md` justified the replay-parsing
ceiling with a reason this repo retired on 2026-06-03 (that a parsed `.rofl` is a strict subset of Match-V5 - it is not;
367 engine-named stat fields x 10 players, no patch gate). A wrong reason for a right conclusion forecloses the option
for the next reader, so it now states the honest bound: per-patch Layer-2 re-RE cost.

**Prunes: zero, and that is correct.** Every candidate resolved to load-bearing against the sync tool itself
(`_DOC_FILES` :71-78, `_INGEST_DOC_FILES` :90-95, `_INGEST_BUNDLE_REL` :96, MANIFEST machine-stamped). Only disposable
artifact was an untracked gitignored `__pycache__`.

Suites fresh this run: **DS 8866 passed / 1 skipped / 2518 subtests; RC 12290 passed / 23 skipped / 359 subtests.**
Share `.md` non-ASCII bytes: 0. Worktrees + slice branches cleaned (local and remote).
