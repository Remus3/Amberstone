# UI/UX QUEUE - next session (operator-requested 2026-07-20, end of the live-gated drain)

**Session shape the operator chose:** stop depending on a live game. Build **dev display data
for the out-of-game pages** + a **pseudo-screen for the in-game overlay**, then do UI/UX work
against those. Tonight proved the need: half the UI findings only surfaced because the operator
happened to be in a specific mode at a specific moment, and several are unreachable otherwise.

---

## A. OPERATOR-STATED, IN HIS OWN FRAMING (do not narrow these)

1. **Colour feels off for RC as a whole - out-of-game AND in-game.** Some colours mix well,
   others are "optically off when viewed". **Some panels do not match the rest thematically.**
   Operator asks for a **theme swap / change** to be explored, not a patch of individual cells.
2. **A few different LAYOUTS per page**, offered as alternatives to choose between - not one
   proposed layout to approve or reject.
3. **Daily-use data points are redundant or lacking.** Some things he reads every day are
   duplicated across panels; other things he wants are absent. This is a per-page content
   audit, not a styling pass.
4. Operator's own note: the earlier per-page UI reviews were **never finished** because larger
   issues kept pulling attention away. Treat the E11 sweep as INCOMPLETE, not done.

**IMPORTANT - do not close item 1 by citing the old palette pass.** Memory
`feedback_operator_ui_qa_method` records that E11 out-of-game surfaces were reskinned and says
"do NOT re-audit these for palette". That referred to a COMPLIANCE hunt (bare hex vs
`var(--hextech-token,...)`), which comes back near-empty. The operator's complaint is about
**optical result and cross-panel coherence**, which that pass never asked about. Different
question, explicitly re-opened by the operator.

---

## B. CONCRETE DEFECTS FOUND 2026-07-20 - free input for the same pass

Measured live during the drain. These are already-diagnosed and mostly one-liners; they belong
in whatever page slice touches them.

**Home**
- Games RC watched live still render `Unknown / 0-0-0` (RECENT 3, THIS WEEK, and the PGR
  headline). NOT an ingest failure - Match-V5 legitimately excludes ARAM Mayhem q2400 and
  customs. **See section C: the .rofl sidecars make this fixable.**
- "14D CS / MIN" renders a stray no-data dot next to the value.
- TONIGHT'S PICK "THE GOOD" / "THE BAD" render as a bare `.` when empty.
- The nav grid omits Champ Select / Active Match / Pre-Game Lobby / Build Insights, all of
  which exist in the header dropdown.
- Home panels strand on "loading..." FOREVER after one transient fetch failure (RC restarted
  at game end). `/api/home/summary` returned 200 with full data throughout; Ctrl+R fixes it.
  No retry, no error state.

**Post Game Review**
- Shows `-` / "No grade yet" AND `OVERALL D` at the same time.
- The BUILD tab points at a "Refresh-from-Riot button (v2) on the page header" that does not
  exist in the header.
- The reference block (VISION 36 / CS 260 / TANKED 32.0k) reads as the player's own stats;
  only a small italic "estimate / reference - not measured" disambiguates. Provenance needs to
  be unmissable, per `feedback_metric_provenance_tagging`.

**Replay**
- Right pane clips its table header ("GOL") and shows a dead slider.

**Settings**
- "Voice picker" has an empty option list.

**Global**
- Footer still reads **"Legion-PC"** (Game-PC retired, ADR-011; host is DESKTOP-JKZECV9).
- Large dead space below the fold on Home / PGR / Session.
- `performance_tracker.py:39` ships grade labels containing a real em-dash written as a
  BACKSLASH-U-2014 ESCAPE - byte-wise ASCII so every hygiene check passes it, but it renders in the UI
  and has been written into `data/ratings/last_sr.json` + `last_arena.json`. Repo-wide scope
  NOT reliably measured yet.

**In-game overlay**
- DS panel THREATS row renders 5 (SR) / 12 (Arena) EMPTY placeholder circles.
- DMG/SURV/UTIL knob steppers still render and read "DMG 50 -> 50 / SURV 50 -> 50 / UTIL 0 -> 0".
  RM-05 already ruled these steppers DEAD - the removal never landed.
- At a COMPLETE 6-item build the panel renders bare "DAEMON SLAYER" and "META BUILD" headers
  with nothing under them (`daemon_slayer_picks` empty, `item_build` ""), which reads as broken
  rather than "build complete".
- The R40 draft-elo chip is mounted INSIDE `.am-pane-head`, which `overlay.css:482` hides for
  `w-build` - it computes fine and can never paint. Needs a re-parent, not a CSS exception.
- Enemy-spell chip label contrast is low (dim text on green fill).
- The minimap ZOI renders an unlabeled live number (observed 50 / 39 / 21) with no legend.
- `health.overlay_visible` reports FALSE while the overlay is visibly rendering.
- The ARAM balance grid (fixed 2026-07-20, previously dead in every ARAM) is ~11 rows and was
  pushing the build panel into a scroll region. **OPERATOR RULED: it gets its OWN draggable
  widget.** Implementation was in flight at session end - verify it landed.
- G2-35 RULED: the stats panel must use a **pace-projected baseline** (scale the tier average
  to the current game clock) instead of comparing live CS against a full-game average.
- G2-34 RULED: objective gauges collapse **horizontally**.

---

## C. THE ONE THAT UNBLOCKS THE HOME/PGR CONTENT PROBLEM

Every game is archived as a `.rofl` within 15 minutes by `RC-RoflArchive`
(`C:\Users\Administrator\Documents\RC_ROFL_Archive`, verified working 2026-07-20 - it captured
that night's SR, Arena AND the q2400 ARAM Mayhem game). `.rofl` Layer-1 extraction yields
**365-367 stat fields x 10 players, no client and no patch gate**.

So the `Unknown / 0-0-0` rows are **backfillable from local replays with no API at all**. This
is the highest-leverage content fix available to the UI pass, because ARAM Mayhem is the mode
the operator plays most and the one Match-V5 will never return.

**Traps already on file - read before building:** join sidecar data on **participant ORDER,
never puuid** (raw file vs key-encrypted API disagree), and sidecars carry **no `queue_id`**.

---

## D. SUGGESTED METHOD

Run the operator's own per-page method (memory `feedback_operator_ui_qa_method`): MAP (fan out
read-only mappers -> inventory every element with file:line + data source + mode gating) ->
ADVOCATE ROUNDS (walk it top-to-bottom via batched questions, giving a keep/move/remove/fix
recommendation AND a counter-argument each time - he wants pushback, not compliance) -> ACT
(worktree slices, verifier gate, 5-phase fixture audit BEFORE commit).

Two deltas for this round:
- The theme question is **cross-page**, so it wants one design-system pass FIRST (palette,
  contrast pairs, panel-chrome consistency) before per-page layout work - otherwise each page
  re-litigates the same colours.
- Offer **2-3 layout alternatives per page** rather than a single proposal, per item A2.
