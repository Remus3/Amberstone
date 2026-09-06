# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-06e - operator session: repo re-case, 7th port block, slots.py re-pin, token rotation

> Filed as `e`: lane 10 already holds `d` (RM-367) and lane 8 holds `c`, both same day.

On main: `7ebdde80b` (slug), `dcd965f2d` (three queued items). LEDGER 1356.
Full RC suite 21023 passed / 96 skipped / 0 failed; ruff + hygiene + drift_guard clean.
DS untouched, so no Share sync.

Four items, and EVERY one had a second half its filing did not name:
- GitHub repo is now `Remus3/Amberstone`. `gh repo rename` rewrote `origin` in the
  shared config, so all 6 lane worktrees followed - no per-worktree action needed.
- Sibling-B owns 8790-8809 (7th block). The real finding: RSC had scaffolded onto
  **8870, inside DS's 8860-8879**, and it could never have surfaced from a scan - DS
  binds 8860/8861 only. Pinned by number now. RM's 8770-8789 is HELD, not freed.
- `ops/loop/slots.py`: **LW authored the bytes, RC followed.** Found by the digest
  guard going red, not by the note. Copied byte-level (never `write_text` - CRLF),
  re-pinned to `1c4f8af4...`. RSC vendors last.
- Vision token rotated + untracked. **The documented procedure was WRONG**: a
  supervisor restart does NOT re-credential `:8889` (detached child, one-shot
  self-heal at dashboard startup), so the OLD token still returned 200 after a
  by-the-book rotation. Fixed + docstring corrected. Also killed the MCP fallback
  coupling with `tools/mcp_token.txt` (gitignored).

Do NOT redo: all four are shipped. `restart_trigger.txt` alone will NOT rotate `:8889`.

NEXT is RM-383, **not RM-382** - lane 10 minted 382 the same day. Details in the
next-session prompt; note `tools/rm_id_registry.py` cannot confirm a named id.

---

# 2026-09-06c - LANE 8 true-audit: core/rofl_archive.py, and the verifier caught MY regression

On main: `387a593a2` (code+tests), `4fcf1980b` (LEDGER 1354), `66f167a90`
(gitignore fix). RM-310 CLOSED, RM-371 now PARTIAL (its rofl third done, the
`core/riot_api.py:319` and `core/sgp_client.py:167` thirds UNCHANGED).

Audited `core/rofl_archive.py` (repeat offender - lane 8 had done it twice
already, LEDGER 1176 + 1311, and it still carried two open lane-8 rows). Five
weaknesses, all fixed, 11 guards, 9 mutations all killed.

**The thing worth remembering: the verifier REFUTED the slice and it was right.**
Bounding the gunzip with `zlib.decompressobj` silently ACCEPTED truncated bodies
that `gzip.decompress` had rejected via EOFError - a 43-percent-truncated replay
kept its RIOT magic, passed validation, was written under its final name, and
was recorded in an index that is idempotent on match id, so every later pull
skipped it FOREVER. Neither the 8 guards nor the mutation driver could see it:
the driver only mutates lines the guards already cover. **Swapping a stdlib call
for a bounded equivalent changes its ERROR contract as well as its size
contract, and the error contract is the half nobody tests.** Fixed with
`not dec.eof` + a member loop.

Second verifier catch: my archive probe used a NON-recursive glob, so I reported
15 replays / 18.6 MB max when the truth is 13896 / 180.4 GiB / 28.48 MB max.
Corrected in code and ledger. The 64 MB ceiling is right either way, and it must
NOT inherit `lib/http/client.py`'s 16 MB default - real replays exceed it.

Do NOT redo: the 3 RC suite failures in the lane worktree are CRLF-environmental
(`core.autocrlf=true`, 1878 files), they pass on the clean main tree. An earlier
suite run reported "22 failed" - that was a crashed xdist worker aborting the
session, not regressions.

**Pre-publication audit run this session (operator is considering going public,
chose MIT).** Findings in chat; the actionable set: `config/vision_token.txt` is
a TRACKED live 32-hex `X-RC-Token` secret from the initial commit (rotate per
`core/vision_token.py:12-30`; `:8889` is loopback-only so it was never a remote
vector); 48.9 MB of scraped Aggregator J HTML nothing reads; lolmath/Overlay App E/101qq
data shipped as verbatim vendor payloads. Operator decided: delete Aggregator J,
obfuscate lolmath + its history, drop `Share/` at publish. NOTE Overlay App E
`mayhem_augment_stats` IS referenced by `tools/ds_feed_index.py` +
`tools/ds_share_sync.py`, and the 101qq raw capture IS the live duo-synergy
fallback seed - neither is dead, both need re-expression, not deletion.
**A history rewrite is NOT safe to start opportunistically: 6 live worktrees and
lane 10 pushes to main continuously. It needs a quiet window.**
MIT should land in the SAME pass as the data purge, not before - otherwise it
asserts an MIT grant over data that is not ours.

---

# 2026-09-06d - LANE 10 cycle 16: RM-367 shipped, and the DECISION was the work

> Filed as `d` because lane 8's true-audit hand-off took the `c` suffix in the
> same rebase. It sits BELOW that block despite landing after it; both are the
> same day and neither was reordered, since rewriting another lane's record to
> tidy ordering costs more than it buys.

RM-367 is on main (`4af7b9fc1` code, `ec32561d4` ledger). **LEDGER 1355, not
1354** - lane 8 took 1354 while this row was in flight, so the code commit's
message cites 1354 and is stale by one. Not amended, per the no-amend rule.

An empty gameflow body is now a FALSY NO-PHASE, emitted as Python `None`.

DO NOT REDO / read before touching this area:
- **The obvious fix is the bug.** `"Unknown"` - the value the very next branch
  in `snapshot_shape` already uses - is TRUTHY, and both `web/js/main.js` arms
  that recover a lost sticky test `!phase` (`:711` s209, `:728` item-281, off
  `const phase = lcu && lcu.phase` at `:629`). "Unifying the two conventions"
  would silently disarm them. Measured in the transition table, not reasoned.
- **Omitting the key is not available either** - `shape_snapshot` reads
  `state["phase"]` by BRACKET at SIX sites, the nearest two lines below.
- The predicate is IMPORTED from `lcu/lcu_pregame._phase_or_none` (RM-347's),
  not re-implemented. Do not add a private copy in `snapshot_shape`.
- Sibling sweep found NO other defect: `phase_watcher` already validates type
  plus an allowlist, `lcu_postgame_collector` returns `""` as its DECLARED
  sentinel under a caller that guards on falsiness, and `lcu_agent` holds no
  phase read at all. Do not "fix" any of the three.

**RESIDUE: RM-382 OPEN** - `"Unknown"` (`snapshot_shape.py:440`) and
`"Offline"` (`tools/lcu_agent.py:330`) are TWO truthy non-phase sentinels that
each disarm those same two arms. Mechanism and consequence both measured;
`lcu_agent` never reaches `shape_snapshot`, so fixing the shaper alone leaves
half of it live.

**NEXT ROW: RM-343** (row 18, the last in the lane's table). Read its fence
first - do NOT close it by re-materializing 1884 paths in a feature branch.
One datum already banked by cycle 15: `.gitattributes` pins `eol=lf` and
overrides `core.autocrlf=true` in the SHARED `.git/config`. Note this cycle's
full suite ran GREEN in this worktree (`tests/test_text_line_endings.py`
included), so the inherited red is NOT currently reproducing here - measure
before inheriting the row's premise.

**ROADMAP is at 89.76 pct of budget, 197 bytes below the 90 pct warn.** The
next cycle should plan to relocate a closed body to `docs/ROADMAP_HISTORY.md`
rather than expect room for a new line.
