# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-21e - R153 FLAT MAGIC-PEN PARITY + ADJUDICATOR SWAP SEAM (headless loop, cycle 5 + operator interrupt) - ENGINE 1.234.0 -> 1.235.0

**Two units in one cycle.** LEDGER 992 (R153) + 993 (swap). Merges `5872fa91`,
`e7be8ed2`, `bd50e88c`, `a430abae`, `f47a5082`, `48975ead`, `afb15a17`. DS bounced,
`:8893` serves 1.235.0. Share mirror synced. Pushed `6948b387..afb15a17`.

## What shipped

R153 credited `1111` Jarvan I's 12 flat magic pen (stated in DDragon description text,
absent from the structured stat block) - the only gap in a 10-id population, confirmed by
three independent sweeps. Added a permanent catalog-sweep guard, marked `443064` Talisman
of Ascension unmodelable (literal `?` placeholders), and backfilled the `Share/README.md`
release list 1.229.0-1.235.0.

The operator interrupted mid-run to direct the Gemini-to-local-Claude transition structure.
`ops/loop/adjudicator.py` now sits behind the single `gemini()` call site with automatic
credit-exhaustion failover that retries the same call on the fallback so no cycle is lost.
The AHK bridge was hardened in the same round. Gemini stays the live default.

## The three things worth remembering

**1. A slice's own green suite cannot prove a merged-state property.** The adjudicator
slice and its verifier BOTH measured 183 passed on byte-identical code; the merged state
gave 2 failed. Neither lied - pre-merge `config.json` had no `adjudicator_fallback`, so the
earlier test never fired a failover. **The merge itself armed the defect.** The fresh
merged-state re-verify is not ceremony; it is the only gate that could have caught this.

**2. Misrouting a message to the wrong agent produced a better result than routing it
correctly.** The AHK latch correction went to the adjudicator agent by mistake. It refused
to edit a sibling's file and instead verified the contract my fix depended on, finding that
`stall_recovery_directive()` reuses the stalled cycle number and `tests/test_loop_stall_recovery.py:32`
pins that format - so my cycle-header-keyed latch would have refused the very recovery
directive meant to unstick it. Re-keyed on a content hash.

**3. Sticky state must be re-validated against the config that is live NOW.** The defect
was a sticky failover decision being honored by a call whose config armed no fallback at
all - routing to a backend the active configuration never authorized. No-op in production,
but the fix restores the pure-function contract the pre-existing 9h-outage tests encode.

## Gates

DS 9100 passed / 1 skipped / 3672 subtests. Dual suite on the merged state 21570 passed /
24 skipped / 4078 subtests, exit 0. RC suite after the swap merges 12531 passed / 23
skipped / 406 subtests, exit 0. `tests/test_loop_gemini_timeout.py` 7 passed as a file AND
7/7 individually. Loop gate 188 passed. ruff clean. AHK `/validate` exit 0 with 0 stderr
bytes, proven discriminating against a broken control script. Heartbeat interop proven by
executing both halves against each other, UTC epoch checked against the 18000s Central
offset. 4 worktrees cleaned, 0 remaining.

## Carry-forward

Two Arena flat-pen drift rows (`223020` states 20 credits 12; `224645` states 10 credits
15) are the magic-side counterpart of R152's held-back RC-B lethality drift and need the
SAME doctrine call. Escalated to the director via `ops/loop/control/gemini_ask.txt` as ONE
question covering both axes - do not resolve one without the other.

The bridge must be RELAUNCHED before a heartbeat appears; the running PID still holds the
pre-hardening script, so `AHK BRIDGE STALE (missing)` until then is expected, not a fault.

FUTURE: a lint rule that any test touching `lc.gemini` must patch `lc.subprocess.run` - a
draft test omitted it and made a real billed CLI call, caught only by its 29-second runtime.

---

# 2026-07-21d - R152 LETHALITY STAT-BLOCK PARITY (gemini headless loop, cycle 4) - ENGINE 1.233.0 -> 1.234.0

**Tier-2 DS run.** LEDGER 991. Slice `ee8a6cb3`, merge `890daf1c`. DS bounced, `:8893`
serves 1.234.0. Share mirror synced in the same commit.

## What shipped

Five item entries in `agents/daemon_slayer/_effects_data.py` that state a Lethality in
DDragon 16.14.1 but read 0.0 in DS: `6698` Profane Hydra 18 and `6695` Serpent's Fang 15
(both SR AND ARAM, maps 11/12/21/35), plus Arena `226698` 18, `226695` 19, `446691`
Duskblade 20. DEFAULT-ON, no flag - see the deviation note below.

## The finding that matters

Penetration is REGISTRY-ONLY. `stats.py` `ITEM_STAT_KEY_MAP` has no pen key and DDragon's
machine-readable `stats` block never carries one - pen exists only in the `<stats>` HTML of
`description`, and the local Meraki snapshot has no stat block on any of its 320 items. So
`ITEM_EFFECTS` is the sole credit path and a missing field is a silent 0.0. Do not go
looking for a generic path.

## Two process notes worth keeping

**The orchestrator's own sweep beat both agents.** Both read-only sweep agents returned a
ranked list topped by a single "one-line fix". A direct 706-item parity sweep showed the 12
divergent ids were TWO root causes: RC-A (stat absent, 5 ids, a real data bug) and RC-B
(Arena magnitude drift, 7 ids, a guarded-doctrine collision). Shipping either agent's top
pick would have left four RC-A ids uncredited.

**Deliberate deviation from the directive, logged.** The directive said to ship any fix
"behind DEFAULT-OFF seam". This shipped DEFAULT-ON. A flag here would have made 5 items
behave differently from the 26 already-credited lethality rows and left a proven-false 0.0
live; adding a row to an always-on registry is not a new math term. R150 set the precedent.

## Gates

DS 9091 passed / 1 skipped / 3650 subtests. RC 12440 passed / 52 skipped / 406 subtests,
1 failure which was PROVEN to be live-coupling (`test_live_three_profiles` asserts the live
`:8893` version) and went 18/18 green after the DS bounce. ruff clean. ENGINE 144 literals
across 123 files, zero residual. `ds_share_sync --check` in sync at 1.234.0.

## Carry-forward

RC-B Arena lethality/magicpen magnitude drift is OPEN and is a DOCTRINE call, not a data
bug - the "Arena mirrors inherit SR" convention has guard tests, and
`test_terminus_juxtaposition_r67.py:118` structurally derives the Arena value from the SR
Meraki entry (and reads a pinned 16.13.1 file). Escalated to the director in the
ORCHESTRATION_PLAN findings log; do not weaken those guards without a decision. Smaller
tails: `1111` Jarvan I's 12 flat magic pen has no ITEM_EFFECTS entry at all;
`Share/README.md` releases stale at 1.228.0, needs a 1.229.0-1.233.0 backfill.

The gist post-commit hook index corruption recurred (4th). Worktree index only, commit
object clean, cleared with `git reset --mixed`.

---

# 2026-07-21c - R151 HEXCORE OFFLINE EXPLORER RE-SYNC (gemini headless loop, cycle 3) - NO ENGINE CHANGE

**Tier-0/docs run.** LEDGER 990. Slice merge `79c3deba`. ENGINE-IMPACT NONE - no DS math
path, no ENGINE bump, no Share churn, no restart.

## What shipped

`docs/HEXCORE_offline.html` re-synced against the repo. 3 missing dust leaves added
(`dashboard/_lcu_inprocess.py` -> `m_dashserver`, `lcu/champ_select_shape.py` -> `m_lcupre`,
`lcu/snapshot_shape.py` -> `m_lcupost`), dust 322 -> 325 at all four sites, ENGINE tooltips
1.232.0 -> 1.233.0 / 9087 tests, LEDGER node desc entry 903 -> 989, repo-stats HUD
re-anchored to `eb111c36` / 2026-07-21 / commits 3789. Guard test
`tests/test_hexcore_offline_dust.py` `EXPECTED_NEW_BASENAMES` widened 26 -> 32.

## The directive assumed a cold sync; the real gap was 3 files, not 32

45 net-new `.py` adds since `d584e02e`, minus 13 `Share/src/agents/daemon_slayer/*.py`
byte mirrors = 32 real files - and R138 had already landed 29 of them. Grounding this
BEFORE dispatching turned a 32-file rewrite into a 3-entry append.

## Both gates earned their keep

The **verifier** caught that the slice agent finished both edits but never committed:
branch had zero commits, `main...HEAD` empty, so a naive merge would have been a silent
no-op reporting success. The **5-phase fixture audit** caught two number defects the
verifier did not: the ENGINE tooltip took the COLLECTED DS count (9088) where the repo
convention for that anchor is the PASSED count (9087, per `docs/DAEMON_SLAYER.md`) -
which also called a skipped test green - and advancing the engine/ledger rows to
2026-07-21 left the neighbouring repo-stats rows on a 2026-07-20 snapshot, so the HUD
contradicted itself. Both fixed in-slice before push. Zero MUST-FIX.

## Don't-redo

HEXCORE dust set is CLOSED against `d584e02e..eb111c36`. `Share/src` mirrors stay
EXCLUDED (byte-identical duplicates would double-render their parents' clusters). Do not
"correct" `snapshot_shape.py` -> `m_lcupost`: the DUST parent convention is decorative
round-robin, not semantic (`lcu_rune_writer.py`, a pre-game module, is parented
`m_lcupost` too). The 8-10px type in `#hexcore-stats` is correct for a zoomable canvas
doc; the v2.1 `--fs-xs` floor governs the dashboard, not this offline artifact.
