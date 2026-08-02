# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-02e - RM-144 + RM-145: two "confirmed" bug reports that were measurement artifacts

3 commits, pushed `ec55b133..8b91d13a`. Ledger 1165 / 1166 / 1167.

**RM-144 "vision is dead" was FALSE on both halves.** `/latest-frame` "0 bytes" was the
probe: `:8889` is plain HTTP and token-gated on `X-RC-Token`, so an `https://` call with no
header returns `http=000 size=0`, which through `wc -c` is indistinguishable from a live
server sending an empty body. Probed right it serves a fresh jpeg every time. `screen_read:
error` was the by-design click-only dwell field holding a 75-day-old click. **But clicking it
live moved the error `no_fresh_frame` -> `empty_note` and exposed a real bug:**
`GameVisionReader._extract` prefers `moon_proxy.extract_vision`, a transport carrying NO
prompt, so the relay answers with its fixed TFT schema and `self.PROMPT` only ships on the
direct fallback. `ScreenReadVision` asks for `{"note":...}` - so SCREEN READ could not return
`ok` on any click since s240. Fixed with a `USE_RELAY` flag (default True; frozen
`moon_proxy.py` untouched). Re-probed live: 200 / 150593 bytes and `{"status":"ok"}`.

**RM-145 was an ABSENCE** - `main.js` registered no display listener at all, so the scale
captured at overlay-window creation was kept for the process lifetime. Added
`display-metrics-changed`/`added`/`removed` on a 600ms settle, re-running the SAME
`primary.bounds` computation (item 567 doctrine pinned by a test that forbids
`primary.workArea`). Decision is pure `resolveOverlayDisplayChange`, splitting `reposition`
from `reload` (ovscale is a URL param baked in at loadURL). rc-shell MAIN relaunched on it
(pid 4140) - **G6-01 satisfied**.

**Third fix, found while verifying the second:** `setMode` early-returned on
`tag === state.mode`, and `state.mode` is SEEDED to "client", so a fresh renderer never
stamped title / mode pill / `body[data-mode]` at all. Only visible in a fresh page's first
seconds, which is why it survived since item 201. `_modeStamped` latch; verified live on the
same process with no restart and no mode flip.

**Do NOT redo:** never probe `:8889` over `https://` or without the token; a stale
`screen_read` is by design (but DO click it once and read the new code); vision needs no
scheduled task. **RM-145 is NOT closed live** - filed as `LIVE_GAME_GATED_SYNC` G6-04,
because the re-apply needs an overlay WINDOW and that is created lazily on first in-game
show, so a headless resolution flip proves nothing. Receipt is two `ovscale=N` access-log
lines around a flip AND a flip-back.

**Trap filed:** `rc-shell/package.json` lists test files BY NAME - a new
`rc-shell/test/*.test.js` runs nowhere until added (326 -> 339).

---

# 2026-08-02d - RM-141 JADE SHIPPED (offline half); the guard was excusing what it existed to catch

Headless-upgrade run `2026-08-02-01`, main tree. 8 commits, pushed
`0a9240b9..3f4e2ab8`. Full ledger entry: `docs/LEDGER.md` item 1163.
Spec: `docs/specs/RM-141_JADE_MODE.md`.

**TIER-1, and the continue-note said Tier-2.** Second run running where the
row's own tier guess was wrong. The 60 `Jade_*` champion rows and the 162-item
`[770000,780000)` band live ONLY in `data/meta_build/ddragon/16.15.1/`; they
reach `data/daemon_slayer/16.15.1/` zero times. Mirrored, ingested by nothing.
No ENGINE bump, no Share sync, no `:8860` bounce were owed and none were done.

**The bug fixed was WRONG output, not absent output.** A JADE game fell through
the SR catch-all, was rejected by `is_sr_mode`, fired no coach, built no
snapshot - and the dashboard kept serving the LAST SR game's advice.

**Do NOT redo:** what "League Classic" means is settled (JADE, three sessions
now). The three kCustom kJade ids are unmapped on purpose. `4311` is mapped at
`gameSelectPriority` 0 on purpose - the queue map is a designed SUPERSET of the
census and no guard asserts the converse. `history_notes.md` and `LEDGER.md`
keep their "alias" wording by design (append-only). Ingesting the throwback
registry is BLOCKED-UPSTREAM, not deferred - Meraki 404s all 60.

**Two process lessons worth more than the feature:**
1. The full repo-root suite caught a defect that FIVE verifier gates and every
   per-slice run missed - and the defect was mine, from a bad slice brief ("skip
   if the file is absent" on a TRACKED file, which
   `tests/test_skip_condition_hygiene.py` correctly calls an always-passing
   guard). Per-slice greens do not compose into a suite green.
2. The alias guard shipped green while excusing exactly what it existed to
   catch. The verifier found one cause (`variant` was a refutation marker);
   removing it did NOT close the hole, because the marker was searched across a
   2-line window, so one legitimate correction excused every re-introduction in
   the same paragraph. Fixed by requiring the marker on the SAME line. A guard
   is not proven by its own green.

**Next:** the remaining half of RM-141 is LIVE-GATED as
`docs/LIVE_GAME_GATED_SYNC.md` GATE 8, rows G8-01..G8-06. G8-01 can invalidate
the rest: if liveclient `gameMode` reads `CLASSIC` rather than `JADE`, the
exact-match branch is dead code and the row re-scopes. Desktop
`RC-NEXT-SESSION.txt` carries the live-state fork.

---

# 2026-08-02c - RM-118 mana-as-damage SHIPPED; the seam was nearly shipped STRANDED

Lane `lane/ds` (worktree `C:/rc-worktrees/rc-lane-ds`, created this run - it did not
exist). 1 commit `a0438f14`, pushed. ENGINE 1.269.0 -> 1.270.0. Full ledger entry:
`docs/LEDGER.md` 1162.

**Shipped.** The third instance of the coupling lever, after RM-87 (resist) and RM-91
(health). `agents/daemon_slayer/_mana_damage_coupling.py` seeds **Blitzcrank only**,
DEFAULT-OFF, sort-only, byte-identical when off, route-exposed on `/rank-tank`.
Kassadin and Ryze pinned OUT by test (their own scorers already price the mana term).

**The near-miss worth remembering.** The build agent parked the flag in
`STRANDED_TODAY` because no route carried it. Measuring the two shipped siblings
instead of accepting that showed both ARE route-exposed (3/2 and 5/3 refs) while the
mana pair was 0/0. A flag-only seam is settable, guard-green and arithmetically INERT -
worse than an honestly stranded one, because the ledger shrinks and nothing works.

**RM-118's Janna UNRESOLVED line is RESOLVED: NOT PRICED, correctly.** `ds.hps` prices
no ability damage at all by design. Do NOT seed it as a fourth instance. The wider
observation (11 enchanter-primary champions, whole ability-damage axis unpriced) is in
`BACKLOG.md` as an observation, not a build row.

**Two mistakes I made, both worth carrying forward.**
1. `git checkout -- <file>` to revert a mutation probe DESTROYED the whole unstaged
   engine edit, because it restores from HEAD and cannot know which hunk was mine.
   Recovered from a subagent's sandbox copy and PROVED the recovery (`+165` matched the
   figure the verifier had independently observed before the loss). **Mutation probes
   restore from a COPY, never from git, while the change is unstaged.**
2. The post-commit hook corrupted the worktree index (the known
   `reference_gist_hook_worktree_index_corruption` class) - `git status` showed mass
   staged deletions right after a clean commit. `git reset` (mixed) restored it; the
   commit was never affected.

**State for the next session.** Lane `lane/ds` is CLEAN, pushed, stash empty.
**NOT merged to main.** `:8860` still serves 1.269.0 because `RC-DaemonSlayer` launches
from the MAIN tree, so `tests/phase8_smoke/...::test_live_three_profiles` is RED on the
lane by construction (live-server skew, not a defect) and goes green on merge. The
lane's engine was proven to boot and serve 1.270.0 on spare port 8871 rather than
bouncing the shared service onto an unmerged worktree. **CI did not run: all three
workflows are `branches: [main]` only, so a lane push triggers nothing - CI gates at
merge.** Merging `lane/ds` to main is the next action.
