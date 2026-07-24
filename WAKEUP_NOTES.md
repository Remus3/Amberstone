# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-24 - R188 HEXCORE offline explorer re-sync (docs, commit `bb847bd0`)

gemini-loop DIRECTOR REFILL unit (a), second pass. Tier-0 docs + guard.
LEDGER 1038, ZERO API / ZERO LLM. No ENGINE bump, no Share sync, no DS bounce,
no RC restart.

- **The drift was ONE file, not a batch.** R164 already landed 44 of the 45
  net-new non-test .py files added since `d584e02e`. The 45th is
  `_burst_off_axis.py`, added by `534096e6` (R186 / RM-41) EARLIER IN THIS SAME
  LOOP CHAIN - the directive was written against a tree its own predecessor
  cycle had just moved. Verify the premise, then size the slice to it.
- **RED first.** Widened `EXPECTED_NEW_BASENAMES` 44 -> 45 and watched
  `tests/test_hexcore_offline_dust.py` fail before touching the HTML.
- Added dust triple `_burst_off_axis.py|modules|m_dsengine`, bumped all four
  dust-count literals 340 -> 341.
- **Stats HUD re-ground against live truth:** ENGINE 1.239.0 -> 1.240.0 on the
  HUD row AND its `title=` tooltip (checked against `:8893/health` + the repo
  `ENGINE_VERSION`), a second staler 1.237.0 in the DAEMON_SLAYER node desc,
  DS tests -> 9238 (measured this run), commits -> 3931, last -> `b9412b51`.
- **Verifier gate 7/7 CONFIRM** before commit. It surfaced a durable gotcha:
  the file embeds ~957KB of base64 JPEG snapshots, so a shell `grep -c` on a
  short numeric literal returns ~1.8MB of noise - count checks on this file
  must be base64-aware Python regex, never shell grep.
- Live render proof: browser pane, zero console errors, HUD read back
  `commits: 3931 / engine: DS 1.240.0 / nodes: 142 / dust: 341 files`.
- Suites: DS 9238 passed / 1 skipped / 3928 subtests; RC 12765 passed /
  22 skipped / 406 subtests (exit 0, no RF5 flake this run). ruff clean.
- **ROADMAP.md deliberately untouched** - 81472 of 81920 bytes (448 free) and
  R188 opens no roadmap work.

**Next:** the dust field is guard-locked; the stats HUD is a hand-maintained
snapshot with no auto-refresh - treat its numbers as stale-by-default.

---

# 2026-07-24 - R186 RM-41 burst off-class exclusion SHIPPED (ENGINE 1.240.0)

First ROADMAP GAP-spec build since the gemini loop halted. Tier-2, LEDGER 1036,
DEFAULT-OFF `exclude_off_axis_items`, ZERO API / ZERO LLM.

- **RM-41 BUILT.** NEW `agents/daemon_slayer/_burst_off_axis.py` strips a burst
  candidate whose offense sits entirely on the champion's OFF damage axis,
  applied at the `_filter_candidates` seam in `burst.rank_items_by_burst` and
  route-surfaced on `/rank-assassin`. Built SYMMETRIC, so the RM-35 mirror
  clause is covered - RM-35's own crit-burst cohort work is NOT.
- **Defect re-probed live at 1.239.0 before building** (the sweep filed it at
  1.216.0): Akali served Essence Reaver #4 / Trinity #5 / BotRK #7 / IE #12 with
  Gunblade at #11. Flag-ON: cohort pool 140 -> 88, 6 of 7 top-8 changes, Gunblade
  #11 -> #8. **Leblanc top-8 byte-identical** - reproduces the sweep's
  no-empowered-auto-hook prediction. Zed top-8 byte-identical (AD core intact).
  Shaco a no-op (inside the axis margin).
- **Neither gate is a curated list** - champion axis from the snapshot's own
  `lolmath.damage_distribution` at the archetype_picks thresholds, item gate from
  its own stat line. **Do NOT re-add the spec's hand-curated deny list:** it named
  Statikk Shiv, which is 45 AP + 45 AD and correctly survives.
- **Ritual in memory-prescribed order:** bump (125 files, quoted-literal only, zero
  forged JSON stamps) -> DS restart -> 9-table regen -> Share sync (463 files) ->
  docs. **All 9 tables stamp-only diffs, zero content lines** - byte-identity at
  the default proven, not asserted.
- **Dual suite 22002 passed / 23 skip / 4334 subtests, 1 failed.** The failure was
  `test_doc_size_budget` tripped by this work's own ROADMAP prose, not a
  regression; fixed by relocating the RM-41 narrative + the superseded
  RM-112-original block to `docs/ROADMAP_HISTORY.md`. Re-verified green.
  **ROADMAP had only 486 bytes of headroom - budget every future NOW-row.**
- Default-ON flip is new gated row **G2-43**. Do not flip blind: a strip is
  invisible in the UI, so a wrong exclusion cannot be caught by looking at what
  IS shown.

---

# 2026-07-24 - R185 ui-audit-spike-cue (CLEAN) + operator halt

Gemini-loop DIRECTOR REFILL cycle 15 (REFILL PROTOCOL 3). Commit `850c577f`,
LEDGER 1035, Tier-0/1 test+docs, ENGINE-IMPACT NONE, ZERO API / ZERO LLM.

- **R185 = CLEAN, ZERO MUST-FIX.** 5-phase Section-3b UI audit of the in-game
  Spike Cue overlay widget (`web/js/panels/spike_cue.js` 158L + `.css` 68L,
  mount `#am-spike-cue`, `w-spike` urgent). Un-audited IN-GAME overlay pick via
  read-only Explore recon; champ-select set CLOSED. STRUCTURE/HIERARCHY clean,
  HIT-TARGETS N/A (zero clickables), ASCII 0 non-ASCII bytes (up-triangle is a
  CSS `\25B2` escape), TYPOGRAPHY already R33-guarded (spike_cue.css is in
  `test_overlay_css_typography_tokens.py` `_OVERLAY_CUE_CSS`, rides `--fs-ov-chip`).
- Drift-guard `tests/test_spike_cue_ascii.py` (3 tests) added. Full RC `tests/`:
  12765 passed / 22 skip / 1 error - the error is the documented RF5 hermeticity
  flake (live loop controller grew `controller.log` mid-suite, conftest.py:145),
  DISJOINT from R185; re-ran isolated = 4 passed. Regressions 0.
- **Operator interrupted -> requested loop halt + /done for a fresh claude
  restart.** Dropped `ops/loop/control/STOP`; controller.log confirms "external
  STOP seen" (cycle 15). Loop is halted. Do NOT relaunch it unless the operator
  re-invokes /gemini-headless-upgrade.
- Do NOT redo: the in-game overlay glance-cue set (ward/spike/objective) + the
  champ-select audit set (R173/R180/R182/R183/R184) are all UI-audit CLEAN.
