"""RM-125: pin the web/ comment tokeniser used by tools/web_ascii_sweep.py.

A normalizer is only correct if you measure the side where it must NOT fire
(memory feedback_normalizer_check_false_positive_side). web/ carries Terminal-
theme UI glyphs on LIVE spans - CSS `content:` values, JS strings and template
literals, HTML text nodes and attribute values - and every one of those renders.
So the bulk of the fixtures below are FALSE-POSITIVE pins: constructs that look
comment-shaped to a naive scanner and must classify LIVE.

Glyph literals are spelled \\uXXXX so this file stays 7-bit ASCII itself.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import unittest
from pathlib import Path

from tools import web_ascii_sweep as sweeper
from tools.web_ascii_sweep import (
    COMMENT,
    LIVE,
    comment_spans,
    lang_for_path,
    live_text,
    read_source,
    scan,
    sweep_text,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB = _REPO_ROOT / "web"

# SHA-256 over "<relpath>\n<live-span text>\n" for every web/ source, newlines
# folded to LF.
#
# RE-CAPTURED at the `${}` regex/comment tokeniser fix, superseding the
# 0910a449 capture. It HAD to move: the digest is computed with the tokeniser's
# own classifier, and that fix corrected the comment/live partition (114 spans
# across 3 panels stopped being mis-read as LIVE). So the old value could not
# survive, and re-stamping it proves nothing on its own - the digest cannot
# police a change to the thing that computes it.
#
# What was measured instead, at the moment of the re-stamp: run the CORRECTED
# tokeniser over both the 35c6730f tree and the swept tree and diff the live
# halves. They are byte-identical for all 168 web/ sources - one fixed
# classifier, two trees, so the comparison is not circular. The same diff under
# the OLD tokeniser flags web/js/panels/last_match.js, which is exactly the bug
# (it read a `/* */` banner as LIVE) and not a regression.
#
# It is pinned as a digest rather than read back out of git so the guard needs
# no history depth and can never degrade into a skip. If a later change
# legitimately edits a LIVE glyph in web/ this goes red on purpose: confirm the
# edit was intended, then re-capture with
#   python -c "import tests.test_web_ascii_sweep as t; print(t._live_half_digest())"
# A tokeniser change lands here too - re-run the two-tree diff above before
# trusting a fresh capture.
#
# RE-CAPTURED at R224 (RM-126, the overlay drag-listener leak fix), superseding
# the R223 capture. Ordinary case again: a LIVE web edit, no tokeniser change,
# so the classifier is fixed and the two-tree diff is a straight answer. Run
# over f124f67f and the post-fix tree with the SAME tokeniser, exactly one of
# 165 web/ sources differs in its live half - web/js/lib/overlay_layout.js -
# which is the slice's whole file set and nothing else.
# RE-CAPTURED at the 16.14.1 -> 16.15.1 DDragon patch refresh, superseding the
# R224 capture. Ordinary case: a LIVE web edit, no tokeniser change, so the
# classifier is fixed and the two-tree diff is a straight answer. Run over HEAD
# and the refreshed tree with the SAME tokeniser, exactly one of 165 web/
# sources differs in its live half - web/js/lib/items_index.js, whose
# DDRAGON_FALLBACK_VERSION const is the slice's only web edit and nothing else.
# RE-CAPTURED at Mission Control S4 (the dashboard panel wired to
# /api/loop-status), superseding the 16.15.1 capture. Ordinary case: LIVE web
# edits, no tokeniser change, so the classifier is fixed and the two-tree diff
# is a straight answer. Run over HEAD and the S4 tree with the SAME tokeniser,
# exactly 4 of 166 web/ sources differ in their live half - web/index.html (the
# new MISSION CONTROL card), web/css/panels/header.css (the S4 block),
# web/js/panels/dev.js (the lock rows + shortcuts, plus 10 pre-existing U+00B7
# middots swept to " - " per the ASCII hard rule) and web/js/lib/arm_confirm.js
# (new file, hence 166 sources rather than 165) - which is the slice's whole
# file set and nothing else.
# RE-CAPTURED at Mission Control S6+S7 (lanes 4-6 wired, steer channel),
# superseding the S5 capture. Ordinary case: LIVE web edits, no tokeniser
# change. Two-tree diff over HEAD: exactly 2 of 166 web/ sources differ in their
# live half - web/js/panels/dev.js (the steer row) and
# web/css/panels/header.css (the steer rules) - the slice's whole web file set.
# RE-CAPTURED at Mission Control S9 (the INTERRUPT tier), superseding the S6+S7
# capture. Ordinary case again: LIVE web edits, no tokeniser change, so the
# classifier is fixed and the two-tree diff is a straight answer. Run over HEAD
# and the S9 tree with the SAME tokeniser: 166 sources on both sides, none
# added and none removed, and exactly 2 differ in their live half -
# web/js/panels/dev.js (the interrupt preview/arm/fire block and its victim
# list) and web/css/panels/header.css (the .loop-irq-* rules) - which is the
# slice's whole web file set and nothing else.
# RE-CAPTURED at Mission Control S10 (arm_confirm.js and its test relocated out
# of web/js/lib/ into a new standalone web/mc/ tree, with web/mc/index.html,
# web/mc/mc.css and web/mc/mc.js added beside them), superseding the S9
# capture. Not quite the ordinary case: a file MOVE plus LIVE web edits, still
# no tokeniser change, so the classifier is fixed and the two-tree diff is
# still a straight answer, just over a set of paths that is not the same set on
# both sides. Run over 6ed2b0d1 (the S9 capture commit) and HEAD with the SAME
# tokeniser: 169 web/ sources rather than 166 - web/js/lib/arm_confirm.js is
# gone from that path and four are new (web/mc/arm_confirm.js,
# web/mc/index.html, web/mc/mc.css, web/mc/mc.js) - and of the sources present
# at an unchanged path on both sides, exactly one differs in its live half:
# web/js/panels/dev.js, whose one-line import path (kept transitionally until
# Task 9 deletes it) is the whole of its S10 edit. Which is the slice's whole
# web file set and nothing else.
# RE-CAPTURED at Mission Control S10 Task 9 (Mission Control removed from the
# RC dashboard - it is now served standalone on :8895 and shares nothing with
# web_dashboard), superseding the prior S10 capture. Ordinary case: LIVE web
# edits, no tokeniser change, no file added or removed (169 web/ sources on
# both sides), so the classifier is fixed and the two-tree diff is a straight
# answer. Run over de7f366d (the prior capture commit) and HEAD with the SAME
# tokeniser: exactly 4 of 169 web/ sources differ in their live half -
# web/index.html (the MISSION CONTROL settings-card removed), web/css/panels/
# header.css (the loop-status-body through loop-irq-victim block removed),
# web/js/panels/dev.js (the whole Headless-loop-status section, its export-list
# entry, and the S10 transitional arm_confirm.js import all removed) and
# web/js/main.js (the renderLoopStatus call and its import name removed) -
# which is the slice's whole web file set and nothing else.
# RE-CAPTURED 2026-08-01 (second-vendor decommission), superseding the S10 Task 9
# capture above. Ordinary case: a LIVE web edit, no tokeniser change, no file
# added or removed. Exactly ONE of the web/ sources differs in its live half -
# web/mc/mc.js, whose budget line stopped rendering the retired vendor's spend
# and ceiling (`b.gemini_usd` / `b.gemini_ceiling`) and now renders
# `b.adjudicator_usd` with no ceiling at all. The ceiling is deliberately absent
# rather than zeroed: it railed a metered vendor that no longer exists, so
# printing "/ $200" would state a limit that is not enforced anywhere. The
# sibling render site (dashboard/routes_loop_monitor.py) changed in the same
# commit but is Python, not web/, so it is outside this digest by construction.
# RE-CAPTURED 2026-08-01 (ADDENDUM A concepts 3/4/5 wired as real panels),
# superseding the second-vendor-decommission capture above. NOT the ordinary
# case: this slice ADDS web/ sources, so the file set differs on the two sides
# and the digest necessarily moves. MEASURED with the same tokeniser: 170 web/
# sources at HEAD before this slice, 173 with it applied (+3 new; the rename
# below moves no count), and the delta is exactly this slice's file set:
#   + web/js/panels/ops_panels.js    (new - renders the three ops panels)
#   + web/css/panels/ops_panels.css  (new - their stylesheet)
#   + web/ops.html                   (new - the page that hosts them)
#   M web/css/dashboard.css          (one @import line for the panel CSS, which
#                                     tests/test_dashboard_css_panel_imports_parity
#                                     requires of every panel stylesheet)
#   R web/mockups/addendum_a_concepts.html -> web/mock/addendum_a_concepts.html
#     (a RENAME, not an edit: the file was authored under web/mockups/, which no
#     static matcher serves, so it 404'd. web/mock/ is the served prefix. Its
#     bytes are unchanged, but its PATH is part of the digest input, so a pure
#     move still moves the hash.)
# No tokeniser change, and no pre-existing file's live half was edited.
# RE-CAPTURED 2026-08-01 (RM-132 overlay font-size token bypass), superseding
# the ADDENDUM A capture above. Ordinary case: a LIVE web edit, no tokeniser
# change, no file added or removed - 173 web/ sources on BOTH sides, and exactly
# TWO differ in their live half:
#   M web/js/lib/overlay_tooltip.js      (:67, :78)
#   M web/js/lib/overlay_item_radial.js  (:65, :74)
# Each replaced a hardcoded `font-size:13px` cssText literal with
# `var(--fs-ov-chip,13px)`. Renders byte-identical today, and the 13px FALLBACK
# is the ONLY thing that ever applies - measured, not assumed:
#   - `--fs-ov-chip: 13px` is declared on `body[data-shell="overlay"]`
#     (web/css/overlay.css:33), deliberately never on :root;
#   - but BOTH widgets mount to `document.documentElement`
#     (overlay_tooltip.js:52, overlay_item_radial.js:118), so they are SIBLINGS
#     of <body>, and custom properties inherit DOWNWARD only.
# So the var does not resolve in the overlay shell either, not just on the plain
# :8888 dashboard - the reference cannot track the token until the mount point
# or the token scope changes (filed as RM-139). Without the fallback this would
# fail SILENTLY to the inherited size, which is the whole reason it is there
# (memory reference_css_undefined_var_fails_silently).
# RE-CAPTURED 2026-08-02 (Mission Control: the `gated` lane + the arcane theme),
# superseding the RM-132 capture above. Ordinary case: LIVE web edits, no
# tokeniser change, no file added or removed - 173 web/ sources on BOTH sides,
# and exactly TWO differ in their live half (verified per-file against
# HEAD with this module's own comment_spans, not by eye):
#   M web/mc/mc.css  the inlined palette swapped from the dashboard's DEFAULT
#                    (hextech) values to the ARCANE ones it actually runs, plus
#                    a 3px gradient rule under .mc-head and a cyan
#                    :focus-visible outline. Colour-only; no rule was added or
#                    removed for a state that did not already have one.
#   M web/mc/mc.js   one new _LANE_LABELS entry ("gated"), which is the panel
#                    half of the seventh lane.
# Both are Mission Control only. web/mc/ is served by mc/handler.py, never by
# the dashboard, so nothing on :8888 renders a byte differently.
# RE-CAPTURED 2026-08-02 (the Mission Control lane-log panel), superseding the
# capture immediately above. Ordinary case again: 173 web/ sources on BOTH
# sides, no tokeniser change, and exactly ONE file differs in its live half:
#   M web/mc/mc.js   renders the new /api/loop-status `lane_log` field as its
#                    own LANE LOG block, and labels the pre-existing tail
#                    LOOP CONTROLLER LOG. Before this the card showed only the
#                    controller's log, which has been stopped since
#                    2026-07-28, so a running lane had no surface at all.
# Mission Control only; nothing on :8888 renders a byte differently.
# RE-CAPTURED 2026-08-02 (the first-render mode stamp), superseding the capture
# immediately above. Ordinary case again: 173 web/ sources on BOTH sides, no
# tokeniser change, no file added or removed, and exactly ONE file differs in
# its live half:
#   M web/js/main.js  `setMode` no longer early-returns when the resolved mode
#                     equals the seed, so a FIRST render stamps title, mode
#                     pill and body[data-mode] instead of only a later flip.
#                     The `_modeStamped` latch keeps the repeat call a no-op.
# THIS GUARD WENT RED ON THAT COMMIT (7705091d) AND THE RE-CAPTURE WAS MISSED,
# so main sat red from 16:34 until this stamp - the guard worked exactly as
# designed and the session that tripped it wrapped before its CI landed. If a
# push run is still in flight at wrap, collect it; a red that arrives after the
# banner is still a red main.
# RE-CAPTURED 2026-08-07 (the vision calibrator seed warning + UI-fixture
# audit), superseding the capture immediately above. Ordinary case: 173 web/
# sources on BOTH sides, no tokeniser change, no file added or removed, and
# exactly ONE file differs in its live half:
#   M web/vision_calibrator.html  four rendered changes, all deliberate.
#                     (1) The UNTUNED-SEED warning moved out of #status - which
#                     loadFrame() overwrites on every boot, so it was never
#                     read - into a #seedwarn banner, and now names the real
#                     base and the real provenance instead of saying "from
#                     legacy" and hardcoding "2560" (LEDGER 1227 filed it).
#                     (2) The toolbar hint's two &middot; separators became
#                     " - "; the entity was ASCII in source but painted U+00B7,
#                     and a rendered glyph is authored content.
#                     (3) A save-arming status string for the seed guard.
#                     (4) HIT-TARGETS: --hit-min 42px + :focus-visible.
# Verified before re-pinning rather than assumed: the digest at HEAD
# reproduces the superseded value byte for byte, so this is the only
# legitimate successor.
# RE-CAPTURED 2026-08-11 (Riot compliance removals), superseding the capture
# immediately above. NOT the ordinary case - the web/ source set SHRANK, which
# is why the digest moved. Seven files were deleted outright:
#   D web/js/panels/enemy_spells.js          enemy summoner-spell tap-tracker
#   D web/js/panels/enemy_spells_abbr.test.mjs
#   D web/js/panels/enemy_spells_timer.test.mjs
#   D web/js/panels/spike_cue.js             ultimate power-spike cue
#   D web/js/panels/spike_cue.test.mjs
#   D web/css/panels/spike_cue.css
#   D web/css/panels/cd_ledger.css           summoner + ultimate cooldown ledger
#   D web/js/panels/cd_ledger.js
# and five more differ in their live half, all from the same removals:
#   M web/index.html            the three pane / cue mounts stripped
#   M web/css/overlay.css       the .cd-* / .ovx-enemyspells / w-spike rules
#   M web/css/dashboard.css     two dropped @import lines
#   M web/js/main.js            imports, render dispatch, cooldown threading
#   M web/js/panels/active_match.js  the CD ledger import + dispatch
# Riot's third-party rules ban tracking enemy summoner-spell cooldowns,
# ultimate timers, and power-spike notifications. See
# docs/OVERLAY_COMPLIANCE_PLAN.md. Verified the same way as the capture above:
# the superseded digest reproduces byte for byte in a clean HEAD worktree, so
# nothing else moved the value.
# RE-CAPTURED 2026-08-11 (product rename, Tier 0), superseding the capture
# immediately above. ORDINARY case: same web/ source set on both sides, no
# tokeniser change, no file added or removed, and exactly ONE file differs in
# its live half:
#   M web/index.html  the <title> is the product name, and the product was
#                     renamed off Riot's trademark (Riot Commander -> Amberstone).
#                     See docs/RENAME_SWEEP_AMBERSTONE.md.
# Verified the same way as the captures above: the superseded digest reproduces
# byte for byte in a clean HEAD worktree, so nothing else moved the value.
# RE-CAPTURED 2026-08-11 (product rename, Tier 1 prose + comments), superseding
# the Tier-0 capture immediately above. Ordinary case: same web/ source set on
# both sides, no tokeniser change, no file added or removed. Six files differ in
# their live half, and only two of those changes RENDER:
#   M web/index.html          the visible brand label (RIOT COMMANDER -> AMBERSTONE)
#   M web/legacy_index.html   its <title>
#   M web/manifest.json       PWA "name" - public identity
#   M web/css/dashboard.css   header comment only
#   M web/css/panels/base.css comment naming the old brand label
#   M web/js/main.js          two comments
# Verified as before: the superseded digest reproduces byte for byte in a clean
# HEAD worktree, so nothing else moved the value.
# RE-CAPTURED 2026-08-12 (B4-b, RM-189 - client-side directive gate),
# superseding the Tier-1 capture immediately above. NOT the ordinary case: a
# file was ADDED to web/, so the digest covers one more source than before.
#   A web/js/lib/live_directive_gate.js  new module - isLiveGame /
#                                        directivesAllowed. Defence in depth
#                                        behind the server-side B4 gate.
#   M web/js/panels/coach_choices.js     import + coerce choices to [] while
#                                        live, so #rn-choices goes quiet.
#   M web/js/panels/callouts.js          import + the same coercion for
#                                        #rn-callouts and #rn-lead.
# All three changes RENDER, by construction - suppressing a render is the
# entire point of the slice. Riot's third-party rules ban notifications that
# dictate player action from live game state; see docs/OVERLAY_B4_DESIGN.md.
# Verified the same way as the captures above: the superseded digest
# 7e5e0d2c reproduces byte for byte in a clean HEAD worktree (measured
# 2026-08-12 at cfc5a8d1), so nothing else moved the value. Note the three
# modified web/data/*_index.json files in the tree at capture time are the
# uncommitted DDragon 16.16.1 bump and CANNOT affect this digest: _web_sources
# filters on lang_for_path, whose _LANGS map is .js / .css / .html only.
# RE-CAPTURED 2026-08-12 (B4-e, RM-189 - the post-game DECISION BRANCHES
# card), superseding the B4-b capture immediately above. Like that one, NOT the
# ordinary case: two files were ADDED to web/.
#   A web/css/panels/branch_review.css  new panel stylesheet
#   A web/js/panels/branch_review.js    new panel module
#   M web/index.html                    the #lm-branch-review mounts, inside
#                                       #view-last-match (post-game only)
#   M web/css/dashboard.css             one @import for the new stylesheet
#   M web/js/main.js                    import + the last-match view hook
# All of these RENDER - the slice adds a visible card to the Post Game Review
# view. It is post-game by construction and never mounts in the ?overlay=1
# shell; see docs/OVERLAY_B4_DESIGN.md section 5.
# Verified the same way as the captures above: the superseded digest 63f408b5
# reproduces byte for byte in a clean HEAD worktree (measured 2026-08-12 at
# afa42d9c), so nothing else moved the value. The three modified
# web/data/*_index.json in the tree remain the uncommitted DDragon 16.16.1
# bump (ROADMAP RM-190) and cannot affect this digest - _web_sources filters on
# _LANGS, which is .js / .css / .html only.
# RE-CAPTURED 2026-09-01 (lane-4 overlay slice: the launcher-menu focus fix +
# the B-OVL-4 draft-elo re-parent), superseding the B4-e capture immediately
# above. Ordinary case: same web/ source set on both sides (171 before and
# after, nothing added or removed), no tokeniser change. Exactly four files
# differ in their live half, and ALL FOUR render by construction:
#   M web/js/lib/overlay_layout.js    _captureMenuFocus / _restoreMenuFocus
#                                     around the _renderMenu rebuild, plus the
#                                     data-ovx-ctl key now stamped on every
#                                     menu control. Keyboard activation of a
#                                     panel toggle dropped document.activeElement
#                                     to <body>, so the 10-row overlay layout
#                                     menu was effectively mouse-only.
#   M web/index.html                  the draft-elo chip re-parented OUT of
#                                     .am-pane-head into a new .am-pane-chips
#                                     row. Inside the head it sat under a
#                                     display:none ancestor in the overlay and
#                                     painted a 0x0 box every tick.
#   M web/css/panels/active_match.css the .am-pane-chips base row + its :has()
#                                     collapse so a hidden chip leaves no strip.
#   M web/css/overlay.css             three blocks: the w-build .am-pane-chips
#                                     override (padding/margin), the overlay-only
#                                     collapse of that row in the chip's init /
#                                     empty / hidden states, and the overlay-only
#                                     re-map of the chip's bad band + low-sample
#                                     pill off lethal red onto neutral ink. The
#                                     pane-head hide rule is deliberately
#                                     UNTOUCHED - the queue fence is "re-parent,
#                                     not a CSS exception".
# The last two blocks are the two MUST-FIX the independent 5-phase audit raised
# against the re-parent: without them the row painted a content-free 18x8 box
# in-game in its default state, and an AMBIENT-tier widget painted the lethal red
# that docs/OVERLAY_DOCTRINE.md rule 4 reserves for the Emergency winner.
# Verified the same way as the captures above: the superseded digest 87d64958
# reproduces byte for byte in a clean HEAD worktree (measured 2026-09-01 at
# 35c6da51 via a throwaway detached worktree), so nothing else moved the value.
# Note web/js/lib/overlay_layout.drag.test.mjs also changed in this slice and
# correctly does NOT appear above: _LANGS is .js / .css / .html, so .mjs is
# outside _web_sources. Confirmed by per-file live-half diff, not assumed.
# RE-CAPTURED at the RM-208/209/220/326/327/328/338 six-slice batch,
# superseding the 06da4a45 capture. Ordinary case: LIVE web edits, no
# tokeniser change, so the classifier is fixed and the two-tree diff is a
# straight answer. Run over 8599f1adf and the merged tree with the SAME
# tokeniser: 171 web/ sources in BOTH trees (nothing added or removed), and
# exactly 11 differ in their live half - web/js/main.js (RM-326/327 render
# gates), web/index.html (RM-328 team-context mount), web/css/tokens.css plus
# build_module / build_order / champ_benchmarks / duration_winrate / op_score /
# perf_curve / snowball_elasticity (RM-209 token resolution) and
# web/css/panels/header.css (RM-338 hit-target overlay). That is the union of
# the four web-touching slices' file sets and nothing else. Deliberately NOT
# stamped by any single slice: a whole-tree digest cannot be computed on a
# partial tree, so the merger owns it once, after every slice lands.
# RE-CAPTURED at RM-339 (deletion of the s162 decommission residue and the
# never-live trend pill), superseding the six-slice-batch capture earlier the
# same day. Ordinary case: LIVE web edits, no tokeniser change, so the
# classifier is fixed and the two-tree diff is a straight answer. Run over
# f2906ce15 and the post-RM-339 tree with the SAME tokeniser: 171 web/ sources
# in BOTH trees, and exactly 6 differ in their live half - header.css,
# map_state.css, primitives.css (dead rule blocks), main.js (loadouts view +
# trend pill), dev.js (diagnostics view + live-metrics poll) and last_match.js
# (one dead id dropped from a list). web/index.html ALSO changed in that slice
# and correctly does NOT appear here: its edit was to stale prose inside an
# HTML comment, which is the swept half, not the live half. Confirmed by
# reading the diff, not assumed from the absence.
# RE-CAPTURED at RM-340 (the mountless `dev` view dropped from the router
# registry), superseding the RM-339 capture the same day. Ordinary case: LIVE
# web edits, no tokeniser change, so the classifier is fixed and the two-tree
# diff is a straight answer. Run over adaeae55e and the post-RM-340 tree with
# the SAME tokeniser: 171 web/ sources in BOTH trees, and exactly 2 differ in
# their live half - web/js/lib/state.js (the VIEW_IDS entry and its VIEW_LABELS
# orphan) and web/js/main.js (the unreachable `else if (v === "dev")` branch).
# That is the slice's whole file set and nothing else.
# RE-CAPTURED at the LANE 10 wiring (`queue` added to the lane roster),
# superseding the RM-340 capture. Ordinary case: one LIVE web edit, no
# tokeniser change. `git status --short web/` reports exactly ONE modified
# source, `web/mc/mc.js`, and `_web_sources()` still returns 171 - nothing was
# added or removed. The live-half change is the single `"queue":
# "Headless-Gated (live)"`-shaped entry appended to `_LANE_LABELS`; the comment
# block above it is the swept half and does not reach this digest. The roster
# it mirrors is pinned independently by
# tests/test_mc_lane_roster_contract.py, so this digest is not the thing
# stopping the panel from drifting - it is the thing that makes the drift
# deliberate.
# RE-CAPTURED at the pre-public name scrub (2026-09-07), superseding the LANE 10
# capture. Ordinary case: LIVE web edits, no tokeniser change. `_web_sources()`
# still returns 171 - nothing was added or removed - and a live-half diff of
# every one of those 171 against the pre-scrub tree names exactly TWO:
# web/js/main.js and web/js/panels/champ_select.js. Both changed for the same
# reason and it is the whole change: hardcoded personal Riot IDs in mock data
# ("<handle>#Trist", "<handle> Sock#NA1") became neutral placeholders, because
# the repo was going public with the operator's own game handle baked into
# rendered strings. Every other web/ file in this commit's diff changed only
# inside comments, which is the SWEPT half and does not reach this digest -
# confirmed by running that per-file live-half comparison, not inferred from
# the file list.
# RE-CAPTURED at RM-382 round 2 (2026-09-17), superseding the pre-public scrub
# capture. Ordinary case: one LIVE web edit, no tokeniser change.
# `_web_sources()` still returns 171. The drift is attributed, not inferred:
# substituting the pre-edit web/legacy_index.html (73a0dcf00) back into the
# digest reproduces the prior value exactly, so that one file is the whole
# change - renderLcuPanel's relay-offline gate and rawPhase fallback, which
# now read the null phase RM-382 emits instead of the retired truthy
# 'Offline' / 'Unknown' sentinels. Pinned behaviourally by
# tests/test_legacy_lcu_panel_phase_rm382.py.
# RE-CAPTURED at RM-462 (2026-09-17), superseding the RM-382 round 2 capture
# immediately above. Ordinary case: one LIVE web edit, no tokeniser change, no
# file added or removed; `_web_sources()` still returns 171. Attributed, not
# inferred: substituting the pre-edit web/legacy_index.html (HEAD 23e20e810)
# back into the digest reproduces the prior value exactly, so that one file is
# the whole change - the relay-offline text in renderLcuPanel no longer sends
# the operator to the retired Game-PC (ADR-011) and a deleted script; it names
# the RC-LCUAgent task and tools/lcu_agent.py. Pinned behaviourally by
# tests/test_legacy_index_retired_gamepc_rm462.py.
# RE-CAPTURED at the Mission Control web-UI retirement (2026-09-20),
# superseding the RM-462 capture immediately above. NOT the ordinary case: this
# is a pure DELETION, the first one this pin has seen. `_web_sources()` returns
# 167 rather than 171 - the four removed are web/mc/arm_confirm.js,
# web/mc/index.html, web/mc/mc.css and web/mc/mc.js, the whole of the retired
# page (web/mc/arm_confirm.test.mjs went with them but never counted here:
# tools/web_ascii_sweep.py:42 `_LANGS` covers .js/.css/.html and not .mjs).
# ATTRIBUTED, NOT INFERRED, and a deletion needs a different attribution move
# than an edit does: substituting one pre-edit file back cannot work when the
# file set itself changed, so the digest was instead recomputed from the HEAD
# BLOBS of the 167 SURVIVING paths. That reproduces this value EXACTLY, which
# proves the deletion is the whole change and that not one surviving web source
# altered its live half. Run it that way again next time a path leaves the set.
#
# One consequence worth stating rather than discovering later: the lane-label
# roster this digest used to co-observe lived in web/mc/mc.js and is gone, so
# tests/test_mc_lane_roster_contract.py was deleted with it. The lane roster is
# still pinned where it is authoritative - ops/loop/lanes.py and
# ops/loop/lane_launcher.py - but there is no longer a third, rendered copy to
# hold them to, because there is no longer a renderer.
#
# RE-CAPTURED at the 16.15.1 -> 16.18.1 DS patch refresh (2026-09-21). Ordinary
# case, no tokeniser change, but TWO sources of LIVE edits, both attributed by
# substitution rather than inferred: recomputing the digest with the pre-change
# blobs (commit 6ef3ca33e) of exactly three files - web/js/lib/items_index.js
# (this refresh: DDRAGON_FALLBACK_VERSION 16.15.1 -> 16.18.1) and
# web/js/panels/team_context.js + web/css/panels/team_context.css (a main-branch
# commit landed after 6ef3ca33e WITHOUT re-capturing, so this guard was already
# red on main) - reproduces the superseded 4e3f9f08... value EXACTLY over all
# 167 sources, so those three files are the whole change.
#
# RE-CAPTURED at RM-196 + RM-139 (2026-10-03, Wave1-state slice). Ordinary
# case, no tokeniser change, no file added or removed. ATTRIBUTED BY
# SUBSTITUTION: recomputing with the base blobs (800d186bc) of exactly
# web/js/panels/ds_statcheck.js (RM-196 strip rebind on champion change) and
# web/css/overlay.css (RM-139 type tokens moved to :root:has(...)) reproduces
# the superseded eeb2c6c9... value EXACTLY, so those two files are the whole
# change.
#
# Re-captured 2026-10-03 for two INTENDED live edits, attributed by swapping
# both files back to 800d186bc (digest returns to eeb2c6c9...): RM-244 (e)
# regenerated web/js/lib/state_schema.js, RM-240 added the X-RC-Token
# header in web/js/panels/coach_decisions.js. Neither is a glyph change.
# MERGED Wave1 (2026-10-03): both re-captures above landed together, so the
# pin below is the digest of the merged tree (recomputed, not either slice's).
#
# RE-CAPTURED 2026-10-04 at Y-04 (readiness unknown state + flags; external
# reference O + Q). Ordinary case, no tokeniser change, no file added or
# removed. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# web/js/panels/session_hygiene.js and web/css/panels/session_hygiene.css back
# to their origin/main d1d078aab blobs reproduces the superseded 3cc269ba...
# value EXACTLY, so those two files are the whole change. Neither is a glyph
# change. If another slice re-captures in parallel, the merger recomputes.
# superseded by the merged re-capture below: "5afd8b1d7f2c7972c4511c235fbafcb396674b684d94e2ad31e5499e756a8c45"
#
# Re-captured 2026-10-04 for Y-13 (external reference L2), three INTENDED live
# edits, attributed by swapping exactly web/js/main.js (health dot drops the
# "unknown" class + "unmeasured" tooltip line), web/css/panels/primitives.css
# (.health-dot.unknown) and web/js/lib/state_schema.js (regenerated: `why`)
# back to origin/main d1d078aab - the digest returns to 3cc269ba... EXACTLY, so
# those three files are the whole change. No glyph change.
# superseded by the merged re-capture below: "7d96dfb2081a61e2d99950e767cf5c10ed661ee834e46b7aaf2ef0eb0b77d219"
#
# MERGED lift-2 (2026-10-04): Y-04 and Y-13 re-captures landed together; the pin
# below is the digest of the merged tree (recomputed, not either slice's).
# superseded by the merged re-capture below: "214e8e2686705bd76424c05ddc01665a19b18c6a5a5c8717a71e55c098ee4985"
#
# RE-CAPTURED at Y-07 (2026-10-04, data-viz token tier, external reference P).
# Ordinary case, no tokeniser change, no file added or removed. ATTRIBUTED BY
# SUBSTITUTION: recomputing with the origin/main blobs (f46631a90) of exactly
# the nine web files this slice edits - web/css/tokens.css, overlay.css,
# panels/pgr_winprob.css, panels/ward_heat.css and web/js/panels/ds_sweep.js,
# map_state.js, spike_curve.js, threat_donut.js, ward_heat.js - reproduces the
# superseded 3cc269ba... value EXACTLY, so those nine files are the whole
# change. Parallel lift-2 slices touching web/ race on this pin: the merger
# recomputes it over the merged tree.
# superseded by the merged re-capture below: "e8530115360cc3ec548b74eb5696cbcaf2f78e3221e5a98c70d12eaf0b57d70f"
#
# MERGED lift-2 (2026-10-04): Y-07 re-capture landed on top of the above; the pin
# below is the digest of the merged tree (recomputed, not either slice's).
# superseded by the merged re-capture below: "32545c4d18605fc2cbdc6a3df4df838b524eab8f74482831f0236c5db226b23c"
#
#
# RE-CAPTURED 2026-10-04 at Y-08 (match-ingest freshness card; external
# reference M). Ordinary case, no tokeniser change. ATTRIBUTED BY
# SUBSTITUTION: swapping exactly web/js/panels/ops_panels.js,
# web/css/panels/ops_panels.css and web/ops.html back to their origin/main
# 0187629ed blobs reproduces the superseded 5afd8b1d... value EXACTLY. The new
# web/js/panels/ops_panels.test.mjs is not a swept language (lang_for_path
# returns None for .mjs), so it is outside this digest. No glyph change. If
# another slice re-captures in parallel, the merger recomputes.
# superseded by the merged re-capture below: "d2f4ed5e2b6d2513b04bd01fd2ea9d75c225c213dadb8b956e4fa232daa3eff6"
#
# MERGED lift-2 (2026-10-04): Y-08 re-capture landed on top of the above; the pin
# below is the digest of the merged tree (recomputed, not either slice's).
# superseded by the RM-612 re-capture below: "3a1f5b31e60e1be587e47b53df7474df367bfafce95a9103e980ffb75ce59c1f"
#
# RE-CAPTURED at RM-612 (2026-10-04, replay-scrubber minimap), rebased onto
# origin/main 24fdd8d8b. Ordinary case, no tokeniser change; one path ADDED
# (web/js/panels/replay_minimap.js) and LIVE edits to web/js/panels/dev.js,
# web/index.html and web/css/panels/primitives.css. ATTRIBUTED BY
# SUBSTITUTION: swapping exactly those four paths back to their 24fdd8d8b
# blobs (and removing the added one) reproduces the superseded 3a1f5b31...
# value EXACTLY, so they are the whole change. If another slice re-captures in
# parallel, the merger recomputes.
# superseded by the RM-612 fix-up re-capture below: "ed4bec34508935f9c3a9a8b34412247378af19aa534fa4fa2a3e01defebed839"
#
# RE-CAPTURED at the RM-612 verifier fix-up (measured halo table, strict
# _validPos). One LIVE-edited path, no file added or removed: swapping exactly
# web/js/panels/replay_minimap.js back to its ce871a447 blob reproduces the
# superseded ed4bec34... value EXACTLY.
# superseded by the merged re-capture below: "57f64cbb2305ae48c90ff2df149b242b5adf84c4fa07b8c4f7ff75f1225c72a0"
#
# MERGED external-lift intake (2026-10-04, RM-612 landed on 92a9e9906). That
# base had ALREADY drifted from the 3a1f5b31... pin (to d4a3b38a...): RM-638
# (73b738635, "you flagged" pins) edited LIVE spans and landed without a
# re-capture, so origin/main was red on this guard. ATTRIBUTED BY
# SUBSTITUTION on the merged tree: swapping exactly the RM-638 web files
# (web/css/panels/pgr_winprob.css, replay_events.css, web/js/panels/
# pgr_winprob.js, replay_events.js) back to their 73b738635~1 blobs AND the
# four RM-612 paths back to their 92a9e9906 blobs (removing the added
# replay_minimap.js) reproduces 3a1f5b31... EXACTLY; swapping only the RM-612
# paths reproduces d4a3b38a... EXACTLY. Those eight paths are the whole change.
# superseded by the RM-641 re-capture below: "8dcc72c66a1ac741d5ff515dec2fdba2fdf6ed855c13024094452ca020282433"
#
# RE-CAPTURED 2026-10-04 at RM-641 (review-player model + S5 Replay video
# lane; external reference E), rebased on 4b994fb35. Ordinary case, no
# tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# web/js/panels/dev.js, web/index.html and web/css/dashboard.css back to their
# 4b994fb35 blobs and removing the three added swept files
# web/js/panels/review_player_model.js, web/js/panels/review_player.js and
# web/css/panels/review_player.css reproduces the superseded 8dcc72c6... value
# EXACTLY. Those six paths are the whole change. No glyph change.
# superseded by the RM-522 re-capture below: "a4a299abc36efba7faeda61fb6f23d14be8150b9c39946ebe9e3c1ef9dac319c"
#
# RE-CAPTURED 2026-10-04 at RM-522 (DS patch 16.18.1 -> 16.19.1, landed as
# 1161a52e3, which shipped without this re-capture and left main red here).
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping
# exactly web/js/lib/items_index.js back to its 1161a52e3~1 blob (the
# DDRAGON_FALLBACK_VERSION literal 16.19.1 -> 16.18.1) reproduces the
# superseded a4a299ab... value EXACTLY. That one path is the whole change.
# No glyph change.
# superseded by the host-name scrub re-capture below: "3ed09b85944aa0a9cec18bdc4e8bf9a5321a7f0bcfc9c5f1206d2778782da6c8"
#
# RE-CAPTURED 2026-10-09 at the host-name / home-address scrub (MAIN 2246
# sec 3-4): the footer label in web/index.html no longer names the machine,
# and comments in web/js/main.js, web/ops.html and web/mock/oq3_index.html
# name loopback or a placeholder. Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping exactly those four paths back to their
# a50a9a616 blobs reproduces the superseded 3ed09b85... value EXACTLY. Those
# four paths are the whole change. No glyph change.
# superseded by the RM-680 re-capture below: "472be5a8f64f3abc9208fb95175396eaeb9564beffd40742210b28c9df471565"
#
# RE-CAPTURED 2026-10-09 at RM-680 (DS patch 16.19.1 -> 16.20.1), in the same
# batch as the bump this time. Ordinary case, no tokeniser change. ATTRIBUTED
# BY SUBSTITUTION: swapping exactly web/js/lib/items_index.js back to its
# b47d2f6f5 blob (the DDRAGON_FALLBACK_VERSION literal 16.20.1 -> 16.19.1)
# reproduces the superseded 472be5a8... value EXACTLY. That one path is the
# whole change. No glyph change.
# superseded by the PUBREPO 1g re-capture below: "010f94d1c878f49ea3cf6167d370ccb600a925a9d042e448f52daa53e6e91ad6"
#
# RE-CAPTURED 2026-10-15 at PUBREPO 1g (CodeQL JavaScript alerts, session 118
# C1 slice cq-js), base 9240474bc. Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping exactly these paths back to their
# 9240474bc blobs (and dropping the new test file) reproduces the superseded
# 010f94d1... value EXACTLY: web/js/panels/{champ_benchmarks,duration_winrate,
# op_score,patch_impact,perf_curve,playstyle_labels,session_hygiene}.js and
# web/js/panels/codeql_js_hardening.test.mjs (new). Those paths are the whole
# change. No glyph change.
# superseded by the PUBREPO 1g stripper re-capture below: "eaaec13b12598e164a5fd2089e49d142e64969bc14614e1a8fe8d2553a1af7c5"
#
# RE-CAPTURED 2026-10-15, PUBREPO 1g second commit (tag strippers + LoL
# tooltip cleaner). ATTRIBUTED BY SUBSTITUTION against the previous commit:
# swapping exactly web/js/lib/{helpers,lol_descriptions,items_index}.js,
# web/js/panels/build_insights.js, web/js/main.js and
# web/js/panels/codeql_js_hardening.test.mjs back reproduces eaaec13b...
# EXACTLY. No glyph change.
# superseded by the PUBREPO 1g xss-sink re-capture below: "e917b4bceb4b0c14faf05114b485792c2c34e5ce39829d6c95f430d4fd208553"
#
# RE-CAPTURED 2026-10-15, PUBREPO 1g third commit (js/xss sinks).
# ATTRIBUTED BY SUBSTITUTION against the previous commit: swapping exactly
# web/js/panels/{augment_reco,coach_choices,champ_select}.js back and dropping
# the new web/js/panels/codeql_xss_sinks.test.mjs reproduces e917b4bc...
# EXACTLY. No glyph change.
# superseded by the PUBREPO 1g tooltip-sink re-capture below: "53495e17ffef036574acb9538f45df11b4b34a7b611a9dcc1ceff0c573983c33"
#
# RE-CAPTURED 2026-10-15, PUBREPO 1g fourth commit (tooltip sink).
# ATTRIBUTED BY SUBSTITUTION against the previous commit: swapping exactly
# web/js/lib/helpers.js, web/js/main.js and
# web/js/panels/codeql_js_hardening.test.mjs back reproduces 53495e17...
# EXACTLY. No glyph change.
# superseded by the PUBREPO 1g champion_tags / legacy re-capture below: "29563cd6b10281f450243c6055cc59c85f8c93a74023c3001e441f9a90cb2690"
#
# RE-CAPTURED 2026-10-15, PUBREPO 1g fifth commit (champion_tags variant
# keys + legacy_index.html dedupe-key strip). ATTRIBUTED BY SUBSTITUTION
# against the previous commit: swapping exactly web/js/lib/champion_tags.js,
# web/legacy_index.html and web/js/panels/codeql_js_hardening.test.mjs back
# reproduces 29563cd6... EXACTLY. No glyph change.
# superseded by the PUBREPO 1g title-row fix-up re-capture below: "8c19101b6a11f9f8707433eeb37282ed238a702a606a956dc7ed6265519b94cb"
#
# RE-CAPTURED 2026-10-15, PUBREPO 1g seventh commit (verifier fix-up: the
# item title row of DDragon items 3901-3903). ATTRIBUTED BY SUBSTITUTION
# against the previous commit: swapping exactly web/js/lib/lol_descriptions.js
# and web/js/panels/codeql_js_hardening.test.mjs back reproduces 8c19101b...
# EXACTLY. No glyph change.
# superseded by the RM-766 re-capture below: "c0fb54b2ac48df4d851f16015c6415fc444bfa6a7e9cd1638403d2197960cf05"
#
# RE-CAPTURED 2026-10-22 at RM-766 (DS patch 16.20.1 -> 16.21.1), in the same
# batch as the bump. Ordinary case, no tokeniser change. ATTRIBUTED BY
# SUBSTITUTION: swapping exactly web/js/lib/items_index.js back to its
# 9aac2d261 blob (the DDRAGON_FALLBACK_VERSION literal 16.21.1 -> 16.20.1)
# reproduces the superseded c0fb54b2... value EXACTLY. That one path is the
# whole change. No glyph change.
# superseded by the RM-850 re-capture below: "3a3a40b47fea396edb10201ec723dc1d83e84daf14b396a3d010c2ac71416dd6"
#
# RE-CAPTURED 2026-10-24 at RM-850 (the ARAM comp-verdict POST carries the
# build variants + current_variant). Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION against 36cba0ea2: swapping exactly
# web/js/panels/champ_select.js back to its HEAD blob reproduces the
# superseded 3a3a40b4... value EXACTLY. That one path is the whole change.
# No glyph change.
# superseded by the RM-860 re-capture below: "26d42f61e1580575e4d2546c1a52af8111d94d2177406eae3c43b28736aa7dfc"
#
# RE-CAPTURED 2026-10-25 at RM-860 (the ARAM Mayhem augment reco; its UI
# audit found real CommunityDragon rarity tokens kGold / kSilver / kPrismatic
# never matching the .ar-rar tier classes). Ordinary case, no tokeniser
# change. ATTRIBUTED BY SUBSTITUTION against the RM-860 base: swapping
# exactly web/js/panels/augment_reco.js back to its HEAD blob reproduces the
# superseded 26d42f61... value EXACTLY. That one path is the whole change.
# No glyph change.
# superseded by the RM-860 verifier fix-up re-capture below: "1ec49f88fe51694d3f59f4516f384d3b2bd66347f7696601537786adf0b12c3e"
#
# RE-CAPTURED 2026-10-25 at the RM-860 verifier fix-up (kEventChoice and
# kBronze rarity tokens mapped to styled pip classes). Ordinary case, no
# tokeniser change. ATTRIBUTED BY SUBSTITUTION against the RM-860 commit:
# swapping exactly web/js/panels/augment_reco.js and
# web/css/panels/augment_reco.css back to their HEAD blobs reproduces the
# superseded 1ec49f88... value EXACTLY. Those two paths are the whole
# change. No glyph change.
# superseded by the RM-857 re-capture below: "971372e120d080d45a2ec569d494de0cb459c57be2078c59dac472ecf74ef5eb"
#
# RE-CAPTURED 2026-10-25 at RM-857 (the Replay scrubber's item icons load
# from the local DDragon mirror through last_match.js _itemIconUrl, now
# exported; the UI audit's alt-text MUST-FIX in the same slice). Ordinary
# case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION against d4ec01210:
# swapping exactly web/js/panels/dev.js and web/js/panels/last_match.js back
# to their HEAD blobs reproduces the superseded 971372e1... value EXACTLY.
# Those two paths are the whole change; the new
# web/js/panels/dev_replay_item_icon.test.mjs is not a swept language. No
# glyph change.
# superseded by the S134 T1 re-capture below: "6d356f2cf1f851c08625e7fcd528b1ce74581ae51daf9e860fa3a0d67901c68f"
#
# RE-CAPTURED 2026-10-25 at S134 T1 (TFT live dashboard + overlay: the honest
# no-:2999-feed Active Match panes, the B4 gate's LCU-phase arm, the
# state.latest.mode_key stamp, the TFT header-pill collapse and the overlay
# stat strip). Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION
# against 4023fa2a3: swapping exactly web/js/main.js,
# web/js/panels/active_match.js, web/js/lib/live_directive_gate.js,
# web/css/overlay.css, web/css/panels/header.css and
# web/css/panels/active_match.css back to their HEAD blobs reproduces the
# superseded 6d356f2c... value EXACTLY. Those six paths are the whole change;
# the new web/js/panels/active_match_tft.test.mjs is not a swept language. No
# glyph change. Parallel S134 slices touching web/ race on this pin: the
# merger recomputes it over the merged tree.
# superseded by the S134 T1 verifier follow-up re-capture below: "2f74201798554bac5361ec26257108b428cc6e3a33e03d1789cd1c27928f11f6"
#
# RE-CAPTURED 2026-10-25 at the S134 T1 verifier follow-up (leaving the TFT
# fallback restores the MAP pane's neutral scaffold text so "No map intel in
# TFT." cannot survive into the next League loading screen). Ordinary case, no
# tokeniser change. ATTRIBUTED BY SUBSTITUTION against 5861ebc86: swapping
# exactly web/js/panels/active_match.js back to its HEAD blob reproduces the
# superseded 2f742017... value EXACTLY. That one path is the whole change. No
# glyph change.
# superseded by the S134 post-match re-capture below: "94b87cba596b82e3171c4708769f69f25908b59206825ef4b572005708899bfe"
#
# RE-CAPTURED 2026-10-25 at S134 post-match (RM-616 / QA D4: the TFT Post
# Game Review card - the #lm-tft mount, last_match.js _renderTftLastMatch and
# its .lm-tft* styles). Ordinary case, no tokeniser change. ATTRIBUTED BY
# SUBSTITUTION against 9dab16aeb: swapping exactly web/index.html,
# web/js/panels/last_match.js and web/css/panels/last_match.css back to their
# HEAD blobs reproduces the superseded 94b87cba... value EXACTLY. Those three
# paths are the whole change. No glyph change. Parallel S134 slices touching
# web/ race on this pin: the merger recomputes it over the merged tree.
# superseded by the S134 TFT board / lobby re-capture below: "55397e313853b960a6d3c3168e500790d74d75d18a1893f18139cddf0ec0a530"
#
# RE-CAPTURED 2026-10-25 at the S134 TFT board / lobby slice (the Active Match
# TFT fallback renders the local board in the BUILD pane, head BOARD, and the
# 8-player lobby in the MAP pane inside fixed-height wrappers, with the round
# file's "as of" clock; the UI audit's contrast MUST-FIX moves every TFT
# secondary line to --text-dim). Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION against e9753d41c: swapping exactly
# web/js/panels/active_match.js and web/css/panels/active_match.css back to
# their e9753d41c blobs reproduces the superseded 55397e31... value EXACTLY.
# Those two paths are the whole change; web/js/panels/active_match_tft.test.mjs
# is not a swept language. No glyph change.
# superseded by the session 135 merger re-capture below (S134 lane uiux cycle 4, RM-896): "a811aac7c4da36d26815e4100f58c27783ff4fad9efe9d28799b271bae722d4e"
#
# RE-CAPTURED 2026-10-25 at S134 lane uiux cycle 4 (RM-896 next.js half:
# the NEXT panel reads the coach payload through the B4 client mirror
# withoutLiveDirectives while a game is live; plus the cycle-3 ?ui_mock=1
# mode=tft / tft_live routes in main.js _amMockUrl, which changed two live
# lines and were not re-captured then). Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION against local main 06777e6ab + the lane: swapping
# exactly web/js/panels/next.js and web/js/lib/live_directive_gate.js back to
# the lane HEAD blobs and web/js/main.js back to its main blob reproduces the
# superseded 94b87cba... value EXACTLY. Those three paths are the whole change.
# No glyph change. Parallel S134 slices touching web/ race on this pin: the
# merger recomputes it over the merged tree.
# REBASED 2026-10-25 at S134 lane uiux cycle 5: the cycle-4 lane re-capture
# (5fbe6e16...) and the post-match re-capture (55397e31...) were each taken
# against a tree missing the other side; this value is recomputed over the
# rebased tree (local main 91d56ed37 + the three lane commits). ATTRIBUTED BY
# SUBSTITUTION: swapping exactly web/js/panels/next.js,
# web/js/lib/live_directive_gate.js and web/js/main.js back to their main
# blobs reproduces the superseded 55397e31... value EXACTLY.
# MERGED 2026-10-25 by the session 135 merger onto s135-land (the TFT
# board / lobby slice and the earlier lanes already landed); recomputed over
# the merged tree. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# web/js/panels/next.js, web/js/lib/live_directive_gate.js and web/js/main.js
# back to their s135-land blobs before this landing (b134282e3)
# reproduces the superseded a811aac7... value EXACTLY. No glyph change.
# superseded by the session 135 merger re-capture below (S134 lane uiux cycle 5, RM-898): "f467715b6bebba93fb76178cd43bdc4f628ff94de341d5228cd5a4a30bae319a"
#
# RE-CAPTURED 2026-10-25 at S134 lane uiux cycle 5 (RM-898: the SSE,
# HTTP-fallback and E6 /api/state handlers in main.js stamp state.latest.lcu
# before they render, so the B4 gate sees the current LCU phase on the first
# live tick). Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION:
# swapping exactly web/js/main.js back to its lane HEAD blob reproduces the
# superseded 194bd1df... value EXACTLY. That one path is the whole change. No
# glyph change.
# MERGED 2026-10-25 by the session 135 merger onto s135-land (the TFT
# board / lobby slice and the earlier lanes already landed); recomputed over
# the merged tree. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# web/js/main.js back to its s135-land blob before this landing
# (a2f6ddcc6)
# reproduces the superseded f467715b... value EXACTLY. No glyph change.
# superseded by the session 135 merger re-capture below (S134 lane uiux cycle 6, RM-897): "1cf1a44e7b1d4648fd358c57c5a3f67cccc27a40eb7fcea44280356021c3d2ec"
#
# RE-CAPTURED 2026-10-25 at S134 lane uiux cycle 6 (RM-897: main.js
# _amMockLoad stamps setMode("tft") when a TFT ui_mock fixture lands, and
# onHealth holds that stamp against the no-game "client" downgrade, so the
# body[data-mode="tft"] overlay and header rules apply on the audit path).
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: hashing the
# tree with exactly web/js/main.js replaced by its lane HEAD blob (in memory)
# reproduces the superseded c0c64f3c... value EXACTLY. That one path is the
# whole change. No glyph change.
# MERGED 2026-10-25 by the session 135 merger onto s135-land (the TFT
# board / lobby slice and the earlier lanes already landed); recomputed over
# the merged tree. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# web/js/main.js back to its s135-land blob before this landing
# (ede09196e)
# reproduces the superseded 1cf1a44e... value EXACTLY. No glyph change.
# superseded by the session 135 merger re-capture below (S135 N9): "85fd1169eb04109bb40039e9ee42d7797855489c22d5d450cc05b40a115c2185"
#
# RE-CAPTURED 2026-10-25 at S135 N9 (the TFT in-game overlay panels: the new
# web/js/lib/overlay_tft.js vitals / board / lobby-HP widgets, the TFT widget
# set + game-family scoping + "TFT PANELS" menu + set-passive "Done" in
# web/js/lib/overlay_layout.js, and the renderTftOverlay calls in
# web/js/main.js). Ordinary case, no tokeniser change. ATTRIBUTED BY
# SUBSTITUTION against 3d190082a: swapping exactly web/js/main.js and
# web/js/lib/overlay_layout.js back to their HEAD blobs and dropping the new
# web/js/lib/overlay_tft.js reproduces the superseded 55397e31... value
# EXACTLY. Those three paths are the whole change. No glyph change. The S134
# P0-F board-panel branch also re-captures this pin: the merger recomputes it
# over the merged tree.
# MERGED 2026-10-25 by the session 135 merger onto s135-land (the TFT
# board / lobby slice and the earlier lanes already landed); recomputed over
# the merged tree. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# web/js/main.js and web/js/lib/overlay_layout.js back to their s135-land
# blobs before this landing (23d9c20d8) and dropping the new
# web/js/lib/overlay_tft.js
# reproduces the superseded 85fd1169... value EXACTLY. No glyph change.
# superseded by the s136-T12 re-capture below: "7e8a22671512b6446773302535f0a402405e9834a8652459c3ac579d7d7a22e1"
#
# RE-CAPTURED 2026-10-25 at s136-T12 (gentle stale / idle dim: new opacity
# values in web/css/panels/map_state.css, the light minimap-image desaturation
# + " - STALE" caption suffix in web/css/panels/grid.css, the overlay idle 0.85
# + section 6b STALE tag in web/css/overlay.css, and a one-line-longer comment
# in web/js/lib/overlay_idle.js). Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION against 7f3d9e124: swapping exactly those four
# paths back to their HEAD blobs (in memory) reproduces the superseded
# 7e8a2267... value EXACTLY; swapping only the three CSS files does not (the
# comment edit moves a newline in the live half). Those four paths are the
# whole change. No glyph change - the two new CSS content strings are ASCII.
# Re-checked after the rebase onto 15e39d167 (its web/js/lib/state_schema.js
# edit is comment-only): the same four-path swap against 15e39d167
# reproduces 7e8a2267... EXACTLY.
# superseded by the s142 PKG-6 re-capture below: "2b50f9cd70c36aa79ec0f501ea0ce19b181503ed91462ef1104d223287dd5e43"
#
# RE-CAPTURED 2026-10-26 at s142 PKG-6 (WA7: the auto-accept POST in
# web/js/main.js, the coach-choice POST in web/js/panels/coach_choices.js and
# the ingest POST in web/vision_calibrator.html now send X-RC-Token, plus the
# calibrator ingest placeholder / title naming data/vision_calib_reference).
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION against
# e6aa499aa: swapping exactly those three paths back to their HEAD blobs (in
# memory) reproduces the superseded 2b50f9cd... value EXACTLY. Those three
# paths are the whole change. No glyph change - every added byte is ASCII.
# If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-941 re-capture below: "fe43f2842c416d9fc7a7488a47ad4555218269fe8b2697d35f1bfa9163e20771"
#
# RE-CAPTURED 2026-10-25 at RM-941 (s134 uiux cycle 7: the TFT ui_mock
# overlay feeds renderTftOverlay a fixture-derived state - the new
# _amMockTftState helper, its call on the mock landing, and the two
# renderTftOverlay call sites in web/js/main.js). Ordinary case, no tokeniser
# change. ATTRIBUTED BY SUBSTITUTION against 3fff974a6: swapping exactly
# web/js/main.js back to its HEAD blob (in memory) reproduces the superseded
# 2b50f9cd... value EXACTLY. That one path is the whole change. No glyph
# change. If another slice re-captures in parallel, the merger recomputes.
# MERGED 2026-10-27 by the session 144 merger onto main (lane commit 8bef64ad2): main had moved
# this pin since the lane base, so the superseded value above is main's and
# the value below is recomputed over the merged tree.
# superseded by the RM-945 re-capture below: "334dfd868a3b774bb10659641615da7094cf193e0b3dba863308ee680a6b59f0"
#
# RE-CAPTURED 2026-10-26 at RM-945 (s134 uiux cycle 12). Two changes ride
# it. (1) Cycles 9-11 (RM-942 / -18 / -19) edited the live half without
# re-capturing: web/js/panels/active_match.js, web/js/lib/overlay_tft.js and
# web/js/main.js (their .json fixture and .test.mjs are not hashed), so this
# guard was red at lane HEAD c9b717940 (measured 5e41a303...). (2) RM-945:
# _line() paints its CALL pane eyebrow and table-key labels with
# var(--text-dim), not var(--text-faint), plus a 4-line comment. Ordinary
# case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION against 24e22fa54
# (the last lane commit whose tree hashed to the pin): swapping exactly those
# three paths back to their 24e22fa54 blobs (in memory) reproduces the
# superseded 3a151d85... value EXACTLY. Those three paths are the whole
# change (the cycle 9-11 lane commits are rebased, so the shas above are the
# post-rebase ones on lane/uiux). No glyph change: the
# added lines carry 0 non-ASCII bytes. If another slice re-captures in
# parallel, the merger recomputes.
# MERGED 2026-10-27 by the session 144 merger onto main (lane commit 6f0c49073): main had moved
# this pin since the lane base, so the superseded value above is main's and
# the value below is recomputed over the merged tree.
# superseded by the RM-948 re-capture below: "efe6594d398dc0d7a116f126046cd68e30574ca5a033cf7dd80966399b540a6d"
#
# RE-CAPTURED 2026-10-26 at RM-948 (s134 uiux cycle 15). Two changes ride
# it. (1) Cycle 14 (RM-947, the start-sentinel HP fall-through in
# web/js/panels/active_match.js) edited the live half without re-capturing,
# so this guard was red at lane HEAD 8c44e9b78 (measured 0c57a0a6...). (2)
# RM-948: web/js/lib/overlay_tft.js exports tftHpBand (the one TFT HP band
# source) and its vitals call it; web/js/panels/active_match.js imports it for
# the lobby bars. Ordinary case, no tokeniser change. ATTRIBUTED BY
# SUBSTITUTION against 87c000bc9 (the last lane commit whose tree hashed to the
# pin): swapping exactly those two paths back to their 87c000bc9 blobs (in
# memory) reproduces the superseded 2078227f... value EXACTLY. Those two paths
# are the whole change. No glyph change: the added lines carry 0 non-ASCII
# bytes. If another slice re-captures in parallel, the merger recomputes.
# MERGED 2026-10-27 by the session 144 merger onto main (lane commit 1c75b7471): main had moved
# this pin since the lane base, so the superseded value above is main's and
# the value below is recomputed over the merged tree.
# superseded by the RM-950 re-capture below: "d1adc684080412c0f1005763b19e506e4807c9097c89c015055512e19f37ef7c"
#
# RE-CAPTURED 2026-10-26 at RM-950 (s134 uiux cycle 17). Two changes ride
# it. (1) Cycle 16 (RM-949, the strip HP cell data-band in
# web/js/panels/active_match.js) edited the live half without re-capturing,
# so this guard was red at lane HEAD 9174dba43 (measured d6c9bda0...). (2)
# RM-950: web/js/lib/overlay_tft.js lobby rows carry tftHpBand, the chips
# stamp data-band, and the injected TFT_OVERLAY_CSS colours a crit chip with
# --ovx-warn. Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION:
# swapping exactly overlay_tft.js back to its 9174dba43 blob and
# active_match.js back to its 325d4cc10 blob (in memory) reproduces the
# superseded be19cbf2... value EXACTLY. Those two paths are the whole change.
# No glyph change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# MERGED 2026-10-27 by the session 144 merger onto main (lane commit ba558b2db): main had moved
# this pin since the lane base, so the superseded value above is main's and
# the value below is recomputed over the merged tree.
# superseded by the RM-951 re-capture below: "62da54c55e881d10bc0f1af8758adda98b22b0d6dcdfbc9d74bd84e7ea1d3c15"
#
# RE-CAPTURED 2026-10-26 at RM-951 (s134 uiux cycle 18). One change rides
# it: web/js/lib/overlay_tft.js gives the Lobby HP and Board chip grids list
# semantics (role list / listitem), each lobby row a spoken label, and empty
# slots aria-hidden. Ordinary case, no tokeniser change. ATTRIBUTED BY
# SUBSTITUTION: swapping exactly overlay_tft.js back to its fd1dd77aa blob (in
# memory) reproduces the superseded 9c77befd... value EXACTLY. That path is
# the whole change. No glyph change: the added lines carry 0 non-ASCII bytes.
# If another slice re-captures in parallel, the merger recomputes.
# MERGED 2026-10-27 by the session 144 merger onto main (lane commit 225c49d94): main had moved
# this pin since the lane base, so the superseded value above is main's and
# the value below is recomputed over the merged tree.
# superseded by the RM-952 re-capture below: "584a4433974d48bc8e88d5a746c0e9f098c5d5c2d82a46fc5b632695bec37e68"
#
# RE-CAPTURED 2026-10-26 at RM-952 (s134 uiux cycle 19). One change rides
# it: web/js/panels/last_match.js maps ?ui_mock=1&mode=tft to the new
# last_match_tft.json fixture and labels the TFT hero set from set_core_name
# ("TFTSet18" -> "Set 18") when set_number is null. Ordinary case, no
# tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# last_match.js back to its 5a2072bdd blob (in memory) reproduces the
# superseded ffb394c0... value EXACTLY. That path is the whole change. No
# glyph change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# MERGED 2026-10-27 by the session 144 merger onto main (lane commit 6eef215c5): main had moved
# this pin since the lane base, so the superseded value above is main's and
# the value below is recomputed over the merged tree.
# superseded by the RM-953 re-capture below: "5d361e88265809d2ac108ef53d2913408a4cfaf1cd6182be6c8eb5f056be9d82"
#
# RE-CAPTURED 2026-10-26 at RM-953 (s134 uiux cycle 20). One change rides
# it: web/js/lib/overlay_tft.js gives the TFT overlay Board and Lobby HP heads
# the per-round file's "as of <clock>" (model asOf / board.head, a new lobby
# head .ovt-time slot, "-" when no age). Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping exactly overlay_tft.js back to its
# 6eef215c5 blob (lane HEAD before this slice, in memory) reproduces the superseded
# bc17afce... value EXACTLY. That path is the whole change. No glyph change:
# the added lines carry 0 non-ASCII bytes. If another slice re-captures in
# parallel, the merger recomputes.
# MERGED 2026-10-27 by the session 144 merger onto main (lane commit f603ee914): main had moved
# this pin since the lane base, so the superseded value above is main's and
# the value below is recomputed over the merged tree.
# superseded by the RM-969 re-capture below: "0ffaff1daf8e0024251ed733de7a11a74caf5e0b8366a9f9b4bee7dc98b504b6"
#
# RE-CAPTURED 2026-10-27 at RM-969 (s144 uiux cycle 1). One change rides
# it: the ?ui_mock=1 Active Match ?mode= -> fixture map moves from main.js
# _amMockUrl into web/js/panels/active_match.js (AM_MOCK_FIXTURES /
# amMockFixtureUrl, plus the new mode=brawl entry), and the capability-gap
# mock fetch reads that map instead of active_match_sr.json for every mode.
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping
# exactly web/js/main.js and web/js/panels/active_match.js back to their
# 0747c8bdc blobs reproduces the superseded 0ffaff1d... value EXACTLY. Those
# two paths are the whole change. No glyph change: the added lines carry 0
# non-ASCII bytes. If another slice re-captures in parallel, the merger
# recomputes.
# superseded by the RM-970 re-capture below: "c97b0f8062f3b76918561564ebe17fff49980d05ec7f8676a44d60f4360ee4fc"
#
# RE-CAPTURED 2026-10-27 at RM-970 (s144 uiux cycle 2). One change rides
# it: the ?ui_mock=1 Champ Select ?mode= -> fixture map moves from main.js
# _csMockLoad into web/js/panels/champ_select.js (CS_MOCK_FIXTURES /
# csMockFixtureUrl), and the build-chooser and capability-gap mock fetches
# read that map instead of champ_select_sr.json for every mode. Ordinary
# case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# web/js/main.js and web/js/panels/champ_select.js back to their 082d31da2
# blobs reproduces the superseded c97b0f80... value EXACTLY. Those two paths
# are the whole change. No glyph change: the added lines carry 0 non-ASCII
# bytes. If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-971 re-capture below: "5303c0412a171b1bfb25147d20584bb3ad5eb5446e520f84e949b3329ffb5591"
#
# RE-CAPTURED 2026-10-27 at RM-971 (s144 uiux cycle 3). One change rides
# it: the Champ Select build-chooser rows become keyboard targets (role,
# tabindex, aria-pressed, Enter / Space, focus carried across the central
# pane rebuild) and gain a :focus-visible ring. Ordinary case, no tokeniser
# change. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# web/js/panels/champ_select.js and web/css/panels/champ_select_view.css back
# to their f0984d0d5 blobs reproduces the superseded 5303c041... value
# EXACTLY; either file alone does not. Those two paths are the whole change.
# No glyph change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# superseded by the RM-972 re-capture below: "bb12e57a88a878b41c3c29ffb54cfd46ba6555f13a7bcbb337623f541b89c38e"
#
# RE-CAPTURED 2026-10-27 at RM-972 (s144 uiux cycle 4). One change rides
# it: the Champ Select build-chooser focus ring is drawn inset (the aram
# legacy row's outer ring was clipped by an overflow-x: hidden card body)
# and aria-pressed is chooser-wide (one pressed target across every variant;
# _csvSyncChooserPressed). Ordinary case, no tokeniser change. ATTRIBUTED BY
# SUBSTITUTION: swapping exactly web/js/panels/champ_select.js and
# web/css/panels/champ_select_view.css back to their b25f042b8 blobs
# reproduces the superseded bb12e57a... value EXACTLY; either file alone
# does not. Those two paths are the whole change. No glyph change: the added
# lines carry 0 non-ASCII bytes. If another slice re-captures in parallel,
# the merger recomputes.
# superseded by the RM-973 re-capture below: "17a45e7e03c7cad9dbc3855256704d42a7debecf8ce859fa36cf6bed3b342d2b"
#
# RE-CAPTURED 2026-10-27 at RM-973 (s144 uiux cycle 5). One change rides
# it: a Champ Select path-row click moves the `selected` class onto its
# collapsed variant at once, and a saved "<variant>:<path>" whose path key
# no longer exists falls back to the primary path (_csvResolvePathKey, used
# by the chooser render and _csvActiveBuildSelection). Ordinary case, no
# tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# web/js/panels/champ_select.js back to its 630911636 blob reproduces the
# superseded 17a45e7e... value EXACTLY. That path is the whole change. No
# glyph change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# superseded by the RM-974 re-capture below: "2223974c446505c60c0c975d2f865efd8639a780b5f8a9758f086198c3b79a17"
#
# RE-CAPTURED 2026-10-27 at RM-974 (s144 uiux cycle 6). One change rides
# it: web/js/panels/last_match.js _lmMockUrl maps ?ui_mock=1&mode=brawl to
# the new last_match_brawl.json fixture (a URF game, match mode "BRAWL").
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping
# exactly web/js/panels/last_match.js back to its 2d580dec4 blob (in memory)
# reproduces the superseded 2223974c... value EXACTLY. That path is the
# whole change. No glyph change: the added lines carry 0 non-ASCII bytes. If
# another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-976 re-capture below: "571244f2fbe08589aaac6a34085baef618bb89269537cddfe738e0cc0981e081"
#
# RE-CAPTURED 2026-10-27 at RM-976 (s144 uiux cycle 7). One change rides
# it: web/js/panels/last_match.js _setChart picks its Dragons / Barons /
# Heralds rows by enriched.map_id (_LM_MAP_PIT_ROWS: 11 all three, 21 Heralds
# only, other known maps none, no map_id the old isSr default). Ordinary
# case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# web/js/panels/last_match.js back to its edcbdf0de blob reproduces the
# superseded 571244f2... value EXACTLY. That path is the whole change. No
# glyph change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# superseded by the RM-975 re-capture below: "a18ee00a25939e8999cd06af3939efae6613a2ebbd62753b946dd59b592126ae"
#
# RE-CAPTURED 2026-10-27 at RM-975 (s144 uiux cycle 8). One change rides
# it: web/css/panels/header.css .view-section-sub 12px -> var(--fs-sm),
# .view-section-sub.is-error 15px -> var(--fs-sm) and flex-shrink: 0 on
# .view-section-head h2 (the title keeps one line at the companion width),
# plus their comments.
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping
# exactly web/css/panels/header.css back to its b9f942aaf blob reproduces the
# superseded a18ee00a... value EXACTLY. That path is the whole change. No
# glyph change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# superseded by the RM-977 re-capture below: "0571242f7efd18a0e612756b5cad9955c9b7d648cae935cf80750172674cedbd"
#
# RE-CAPTURED 2026-10-27 at RM-977 (s144 uiux cycle 9). One change rides
# it: web/js/panels/last_match.js _setChart draws a Void Grubs row
# (teams[].horde_kills) as a map-11 pit row, only when a team row carries
# the key. Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION:
# swapping exactly web/js/panels/last_match.js back to its 4ee181d6d blob
# reproduces the superseded 0571242f... value EXACTLY. That path is the
# whole change. No glyph change: the added lines carry 0 non-ASCII bytes. If
# another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-979 + RM-980 re-capture below: "3fa759001f0bdd1439557c7374a891cc9ab998def1d02e1f4caaa524e17b23e7"
#
# RE-CAPTURED 2026-10-27 by the session 144 L3 merger, at the landing of the
# s144 uiux lane: its cycles for RM-979 (Lobby Top 8 search box on the
# --fs-xs floor, --hit-min tall, focus ring) and RM-980 (Top 8 rows drop the
# pointer no handler serves; the tag cell is a keyboard-reachable --hit-min
# button) edited the live half without re-capturing, so the lane tip itself
# read 624589f4... against this 3fa75900... pin. Ordinary case, no tokeniser
# change. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# web/css/panels/header.css and web/js/main.js back to their 1af7799f4 blobs
# (in memory) reproduces the superseded 3fa75900... value EXACTLY. Those
# paths are the whole change. No glyph change: the added web/ lines carry 0
# non-ASCII bytes.
# superseded by the RM-881 (b) re-capture below: "624589f47f47d313fd16da31fba81738c5943d3054244d6e640038c28562ad45"
#
# RE-CAPTURED 2026-10-27 at RM-881 (b) (s144 queue cycle 4, provisional
# until the merger lands it). One change rides it: the lobby DUO PICKS block
# - the new web/js/panels/lobby_duo_synergy.js, its wiring in web/js/main.js
# (_lvDuoCtl / _lvDuoRender, called from _lobbyViewRefresh), the
# #lv-duo-synergy mount in web/index.html and its .lv-duosyn rules in
# web/css/panels/header.css; the block is SR-queue only (isDuoQueue gets
# main.js SR_QUEUE_IDS). Ordinary case, no tokeniser change. ATTRIBUTED
# BY SUBSTITUTION: swapping exactly main.js, index.html and header.css back
# to their local-main f073b1ca1 blobs and dropping the new module (in memory)
# reproduces the superseded 0ffaff1d... value EXACTLY. Those paths are the
# whole change. No glyph change: the added lines carry 0 non-ASCII bytes.
# If another slice re-captures in parallel, the merger recomputes.
# MERGED 2026-10-27 by the session 144 L3 merger onto main (lane commit c7ee8c3d0): main had moved
# this pin since the lane base, so the superseded value above is main's and
# the value below is recomputed over the merged tree.
# superseded by the RM-1007 re-capture below: "4c75c2a807beaa734ce59aed29b89189fc285abdd9fdaf63eb01a8a871b96c64"
#
# RE-CAPTURED 2026-10-27 at RM-1007 (s144 uiux cycle 17, provisional
# until the merger lands it). One change rides it: User Builds row Edit /
# Delete (.ub-btn-tiny) keep the --hit-min floor and every .ub-btn gets an
# accent :focus-visible ring, both in web/css/panels/header.css. Ordinary
# case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# web/css/panels/header.css back to its lane-tip b0794d9c2 blob (in memory)
# reproduces the superseded 4c75c2a8... value EXACTLY. That path is the whole
# change. No glyph change: the added lines carry 0 non-ASCII bytes. If
# another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1009 re-capture below: "842b95b2830516ac030bd9e7831d23b8a0255ec27e20f87fbc4bed868f9c0f2c"
#
# RE-CAPTURED 2026-10-27 at RM-1009 (s144 uiux cycle 18, provisional
# until the merger lands it). One change rides it: the dashboard footer is
# --hit-min tall and flex-shrink:0, its text and controls sit on --fs-xs,
# its buttons get a full-height click band and an accent :focus-visible
# ring, and the lobby cards trim 8 -> 6px vertical padding to keep the
# 1920x920 no-scroll fit - in web/css/panels/header.css and
# web/css/panels/input_activity.css. Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping exactly those two files back to their
# lane-tip 32f57b73f blobs (in memory) reproduces the superseded 842b95b2...
# value EXACTLY. Those paths are the whole change. No glyph change: the
# added lines carry 0 non-ASCII bytes. If another slice re-captures in
# parallel, the merger recomputes.
# superseded by the RM-1010 re-capture below: "a0b0ed06b513d23b4b5c555a7c1b362cbcf81236deae92e2fede3cb0f0d7627c"
#
# RE-CAPTURED 2026-10-27 at RM-1010 (s144 uiux cycle 20, provisional
# until the merger lands it). One change rides it: the footer VOICE button
# and the prefs chip take the mode-pill box (3px padding, 1px transparent
# border, line-height 1) so every footer chip renders one height - in
# web/css/panels/header.css and web/css/panels/input_activity.css. Ordinary
# case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# those two files back to their lane-tip a9a44206f blobs (in memory)
# reproduces the superseded a0b0ed06... value EXACTLY. Those paths are the
# whole change. No glyph change: the added lines carry 0 non-ASCII bytes.
# If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1012 re-capture below: "63f0e105b1b3a53e98c725430bde95b53083d3fe74d5a440c68595aed6756732"
#
# RE-CAPTURED 2026-10-27 at RM-1012 (s144 uiux cycle 21, provisional
# until the merger lands it). One change rides it: the footer build stamp
# `footer .ui-version` takes the mode-pill box (3px padding, 1px transparent
# border) and computes display:none while empty - in
# web/css/panels/input_activity.css. Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping exactly that file back to its
# lane-tip 485d0c4ba blob reproduces the superseded 63f0e105... value
# EXACTLY. That path is the whole change. No glyph change: the added lines
# carry 0 non-ASCII bytes. If another slice re-captures in parallel, the
# merger recomputes.
# superseded by the RM-1013 re-capture below: "d04739f476e54171170b25c066cfea7d45de302f0532e41b4d1dee7c0df097e5"
#
# RE-CAPTURED 2026-10-27 at RM-1013 (s144 uiux cycle 22, provisional
# until the merger lands it). One change rides it: the footer holds one row
# (`footer > *` nowrap; the build stamp `footer .ui-version` is display
# block, min-width 0, ellipsis) in web/css/panels/input_activity.css, and
# web/js/main.js autoReload `stampFooter` copies the stamp into the span's
# title. Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION:
# swapping exactly those two files back to their lane-tip fc5d58121 blobs
# reproduces the superseded d04739f4... value EXACTLY. Those paths are the
# whole change. No glyph change: the added lines carry 0 non-ASCII bytes.
# If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1014 re-capture below: "14e99e48ba1f301ca7cb04bb83a6ac5987f603fa9d8bc373dd3b328d6c11e1c2"
#
# RE-CAPTURED 2026-10-27 at RM-1014 (s144 uiux cycle 23, provisional
# until the merger lands it). One change rides it: the hidden footer status
# items keep the one-row footer if their hide rules are removed -
# .latency-stat / .analyze-stat 12px -> --fs-xs in
# web/css/panels/map_state.css; min-width 0 + ellipsis on them and on the
# new `.frame-stat` class, and flex-shrink 1000 on the stamp, in
# web/css/panels/input_activity.css; class="frame-stat" on #frame-count in
# web/index.html. Ordinary case, no tokeniser change. ATTRIBUTED BY
# SUBSTITUTION: swapping exactly those three files back to their lane-tip
# f9f357a00 blobs (in memory) reproduces the superseded 14e99e48... value
# EXACTLY. Those paths are the whole change. No glyph change: the added
# lines carry 0 non-ASCII bytes. If another slice re-captures in parallel,
# the merger recomputes.
# superseded by the RM-1011 re-capture below: "c4e3e73fc2b1add6461692cef3cf484df9dec65a4477df277915aecd788c08f3"
#
# RE-CAPTURED 2026-10-27 at RM-1011 (s144 uiux cycle 24, provisional
# until the merger lands it). One change rides it: the dashboard view head
# keeps its height when Lato swaps in - `.view-section-head` line-height
# 1.2, head buttons inherit it, and `.view-section-tabs` align-self center
# - in web/css/panels/header.css. Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping exactly that file back to its
# lane-tip aff5e2ecd blob reproduces the superseded c4e3e73f... value
# EXACTLY. That path is the whole change. No glyph change: the added lines
# carry 0 non-ASCII bytes. If another slice re-captures in parallel, the
# merger recomputes.
# superseded by the RM-1017 re-capture below: "afebe58df410761c7fbfd8fd8684046c487d71a8fe0c76fbd8d47c5affd8301b"
#
# RE-CAPTURED 2026-10-27 at RM-1017 (s144 uiux cycle 26, provisional
# until the merger lands it). One change rides it: six :focus-visible rules
# that fed the box-shadow token --focus-ring to `outline:` (invalid, so no
# ring painted) now draw it as a box-shadow, and the Replay Timeline filter
# checkboxes gain a :focus-visible ring - in web/css/panels/build_insights.css,
# web/css/panels/duration_winrate.css and web/css/panels/replay_events.css.
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping
# exactly those three files back to their lane-tip 0efa3a6fd blobs (in
# memory) reproduces the superseded afebe58d... value EXACTLY. Those paths
# are the whole change. No glyph change: the added lines carry 0 non-ASCII
# bytes. If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1018 re-capture below: "8ea4a3cf29e6fd062c7535e9ab3ec788ea70a726c650d700afb7f73129254d73"
#
# RE-CAPTURED 2026-10-27 at RM-1018 (s144 uiux cycle 27, provisional
# until the merger lands it). One change rides it: the Replay RECENT
# MATCHES rows become keyboard buttons (tabindex 0, role button, Enter /
# Space load the match) in web/js/panels/dev.js, and the rows and
# #replay-slider paint the --focus-ring box-shadow under keyboard focus in
# web/css/panels/primitives.css. Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping exactly those two files back to their
# lane-tip 0b1c68229 blobs (in memory) reproduces the superseded 8ea4a3cf...
# value EXACTLY. Those paths are the whole change. No glyph change: the
# added lines carry 0 non-ASCII bytes. If another slice re-captures in
# parallel, the merger recomputes.
# superseded by the RM-1019 re-capture below: "aa31e3f33a90f5c93ace42508aaa0661c7220cd7df3799a1cf859b5fa58c5690"
#
# RE-CAPTURED 2026-10-28 at RM-1019 (s144 uiux cycle 28, provisional
# until the merger lands it). One change rides it: the Replay timeline rows
# take min-height: var(--hit-min) in web/css/panels/replay_events.css, and
# .replay-main-pane scrolls on y in web/css/panels/primitives.css, which
# folds in the recording-only overflow-y rule removed from
# web/css/panels/review_player.css. Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping exactly those three files back to
# their lane-tip fda3a44c2 blobs (in memory) reproduces the superseded
# aa31e3f3... value EXACTLY; no single file alone does. Those paths are the
# whole change. No glyph change: the added lines carry 0 non-ASCII bytes.
# If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1063 re-capture below: "89c8be0e7b589c7bab7febb4f2994f417c0da4ecd2b1bc68306edad946ccce92"
#
# RE-CAPTURED 2026-10-28 at RM-1063 (s144 uiux cycle 29, provisional
# until the merger lands it and maps the id). One change rides it: the
# active #view-replay becomes a flex column in web/css/panels/header.css,
# and .replay-body flex-grows under the view head instead of height: 100%
# in web/css/panels/primitives.css. Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping exactly those two files back to
# their main e14071faa blobs (in memory) reproduces the superseded
# 89c8be0e... value EXACTLY; no single file alone does. Those paths are the
# whole change. No glyph change: the added lines carry 0 non-ASCII bytes.
# If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1062 re-capture below: "2ad292b4e2acffc3cac72a43b9f84912c792288de038c3b52b702da47c45a0f6"
#
# RE-CAPTURED 2026-10-28 at RM-1062 (s144 uiux cycle 30, provisional
# until the merger lands it and maps the id). One change rides it: the
# Replay recording player reads rendered visibility in
# web/js/panels/review_player.js (its hotkeys were dead) and stands down on
# a key a closer handler consumed and on a plain Space a focused control
# activates (web/js/panels/review_player_model.js);
# the Replay match and timeline rows leave modifier+key to the player
# (web/js/panels/dev.js, web/js/panels/replay_events.js) and the loaded
# match row carries aria-current (dev.js). Ordinary case, no tokeniser
# change. ATTRIBUTED BY SUBSTITUTION: swapping exactly those four files
# back to their lane-tip 49192018e blobs (in memory) reproduces the
# superseded 2ad292b4... value EXACTLY; no single file alone does. Those
# paths are the whole change. No glyph change: the added lines carry 0
# non-ASCII bytes. If another slice re-captures in parallel, the merger
# recomputes.
# superseded by the RM-1061 re-capture below: "d4f71f55849a155c549d740953b857eb68d610a3cea6a73139ba078cde249095"
#
# RE-CAPTURED 2026-10-28 at RM-1061 (s144 uiux cycle 31, provisional
# until the merger lands it and maps the id). One change rides it: the
# .settings-row checkbox :focus-visible ring draws the system --focus-ring
# token instead of a one-off accent + glow, in web/css/panels/header.css.
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping
# exactly that one file back to its lane-tip b1c2302fa blob (in memory)
# reproduces the superseded d4f71f55... value EXACTLY. That path is the
# whole change. No glyph change: the added lines carry 0 non-ASCII bytes.
# If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1067 re-capture below: "a17b83545bbcfe6cf2949eda901cdf5104856599b2595cda4e26f210ca944970"
#
# RE-CAPTURED 2026-10-28 at RM-1067 (s144 uiux cycle 33, provisional
# until the merger lands it and maps the id). One change rides it: one
# Escape does one thing - the view menu, the task modal and the Home Find
# Match picker consume the Escape that closes them (capture phase,
# preventDefault) and the general Escape chain stands down on a consumed
# press, in web/js/main.js. Ordinary case, no tokeniser change. ATTRIBUTED
# BY SUBSTITUTION: swapping exactly that one file back to its lane-tip
# 60853812c blob (in memory) reproduces the superseded a17b8354... value
# EXACTLY. That path is the whole change. No glyph change: the added lines
# carry 0 non-ASCII bytes. If another slice re-captures in parallel, the
# merger recomputes.
# superseded by the RM-1068 re-capture below: "13794bf847867823c42de9fd92bd94b68752a7c97cf84e8d1d278ba234a1c03a"
#
# RE-CAPTURED 2026-10-28 at RM-1068 (s144 uiux cycle 34, provisional
# until the merger lands it and maps the id). One change rides it: the
# Right Now digest popover (web/js/panels/right_now.js) and the draft-elo
# contributions overlay (web/js/panels/draft_elo.js) consume the Escape
# they act on (capture phase, preventDefault), so it no longer also exits
# zen. Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION:
# swapping exactly those two files back to their lane-tip 970b7a2e5 blobs
# (in memory) reproduces the superseded 13794bf8... value EXACTLY; neither
# file alone does. Those paths are the whole change. No glyph change: the
# added lines carry 0 non-ASCII bytes. If another slice re-captures in
# parallel, the merger recomputes.
# superseded by the RM-1066 re-capture below: "add8c81218b76ee2ef3b83ef35a0c7e61a7649ce36513a5bb209fa2312fc020f"
#
# RE-CAPTURED 2026-10-28 at RM-1066 (s144 uiux cycle 35, provisional
# until the merger lands it and maps the id). One change rides it: every
# Replay row (RECENT MATCHES in web/js/panels/dev.js, the timeline ribbon
# in web/js/panels/replay_events.js) is a plain li holding a real
# <button type="button"> instead of an li with role=button, and the row
# rules in web/css/panels/primitives.css and replay_events.css reset the
# UA button chrome. Ordinary case, no tokeniser change. ATTRIBUTED BY
# SUBSTITUTION: swapping exactly those four files back to their lane-tip
# fcd452bb9 blobs (in memory) reproduces the superseded add8c812... value
# EXACTLY; no three of them do. Those paths are the whole change. No glyph
# change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# superseded by the RM-1069 re-capture below: "e7d890a5ea1dc18b58c648e5bd310a606cb06d4d8d2b0fb40990be93ba41e9be"
#
# RE-CAPTURED 2026-10-28 at RM-1069 (s144 uiux cycle 36, provisional
# until the merger lands it and maps the id). One change rides it: every
# capture-phase Escape layer (the task modal, view menu and Find Match
# picker in web/js/main.js, the digest popover in web/js/panels/right_now.js,
# the draft-elo overlay in web/js/panels/draft_elo.js) stands down on a
# press another layer already consumed (e.defaultPrevented), so stacked
# layers close one per press. Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping exactly those three files back to
# their lane-tip c773ce5de blobs (in memory) reproduces the superseded
# e7d890a5... value EXACTLY; no one or two of them do. Those paths are the
# whole change. No glyph change: the added lines carry 0 non-ASCII bytes.
# If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1064 re-capture below: "9060e9038cb07e04961a7b98314b8fc42c2dc110786be7408f0dff9742687494"
#
# RE-CAPTURED 2026-10-28 at RM-1064 (s144 uiux cycle 37, provisional
# until the merger lands it and maps the id). One change rides it: the
# .replay-main-pane gold corner brackets (web/css/panels/primitives.css)
# are background layers instead of ::before / ::after, so they stay on the
# pane's visible corners while it scrolls, and the pane styles a 12px
# scrollbar with a transparent gutter so the bottom-right one shows.
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping
# that one file back to its lane-tip fb6dcd6ce blob reproduces the
# superseded 9060e903... value EXACTLY. That path is the whole change. No
# glyph change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# superseded by the RM-1070 re-capture below: "3115dc8cf650d43614a0ae6fd722e8f27160518eb732e5785253d80f62bc2344"
#
# RE-CAPTURED 2026-10-28 at RM-1070 (s144 uiux cycle 38, provisional
# until the merger lands it and maps the id). One change rides it: the five
# Escape layers (task modal, view menu and Find Match picker in
# web/js/main.js, the digest popover in web/js/panels/right_now.js, the
# draft-elo overlay in web/js/panels/draft_elo.js) register with one
# dispatcher, the new web/js/lib/escape_layers.js, which closes the topmost
# open layer instead of the first registered one. Ordinary case, no
# tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping those three files
# back to their lane-tip 06aae01a3 blobs and leaving out the new module (in
# memory) reproduces the superseded 3115dc8c... value EXACTLY; no one or two
# of the three swapped alone do, nor the three without dropping the module.
# Those paths are the whole change (the new .test.mjs is not a swept
# language). No glyph change: the added lines carry 0 non-ASCII bytes. If
# another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1072 re-capture below: "780a2c7e34ff4953425ab6f40eff3e42ee66d8fdb4305e7b2949ad1087d1ef1e"
#
# RE-CAPTURED 2026-10-28 at RM-1072 (s144 uiux cycle 40, provisional
# until the merger lands it and maps the id). One change rides it: the
# Replay view body (.replay-body in web/css/panels/primitives.css) takes a
# fixed line-height: 1.2, so its text keeps its boxes when Lato swaps in.
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping
# that one file back to its lane-tip 1c1b2faf6 blob reproduces the
# superseded 780a2c7e... value EXACTLY. That path is the whole change. No
# glyph change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# superseded by the RM-1073 re-capture below: "2801677fdd16f0c5b7c5bb0af1b871930171b0bd73087ac6ea3c53f91c0348ac"
#
# RE-CAPTURED 2026-10-28 at RM-1073 (s144 uiux cycle 41, provisional
# until the merger lands it and maps the id). One change rides it: every
# view body (.view-section-body in web/css/panels/header.css) takes a fixed
# line-height: 1.2 and its button / input / textarea controls inherit it,
# so the body text keeps its boxes when Lato swaps in. Ordinary case, no
# tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping that one file back
# to its lane-tip bf4414c73 blob reproduces the superseded 2801677f...
# value EXACTLY. That path is the whole change. No glyph change: the added
# lines carry 0 non-ASCII bytes. If another slice re-captures in parallel,
# the merger recomputes.
# superseded by the RM-1074 re-capture below: "718bec48ed072db16f285e9ce6ace20a2230e96ef1ba8eed87678e491e8a60c6"
#
# RE-CAPTURED 2026-10-28 at RM-1074 (s144 uiux cycle 45, provisional
# until the merger lands it and maps the id). One change rides it: the
# Escape dispatcher (web/js/lib/escape_layers.js) ranks open layers by
# their stacking-context paths (stackingZ / compareStacking) instead of the
# outermost positioned z-index. Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping that one file back to its lane-tip
# a44d38871 blob reproduces the superseded 718bec48... value EXACTLY. That
# path is the whole change. No glyph change: the added lines carry 0
# non-ASCII bytes. If another slice re-captures in parallel, the merger
# recomputes.
# superseded by the RM-1075 re-capture below: "d7d6b9878b22c11a3048404ef444c1032f98a7c8f766468a379337f7547d1e30"
#
# RE-CAPTURED 2026-10-28 at RM-1075 (s144 uiux cycle 46, provisional
# until the merger lands it and maps the id). One change rides it: the
# Escape dispatcher (web/js/lib/escape_layers.js) learns four more
# stacking-context creators, skips display:contents boxes, and ranks two
# top-layer layers by open order (a capture beforetoggle stamp). Ordinary
# case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping that one
# file back to its lane-tip c3ba57a4f blob reproduces the superseded
# d7d6b987... value EXACTLY. That path is the whole change. No glyph
# change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# superseded by the RM-1076 re-capture below: "fd1764e185c9d85194384633ffc616f9b36dcd2aeae98d93e1f35b3532ce92cb"
#
# RE-CAPTURED 2026-10-28 at RM-1076 (s144 uiux cycle 48, provisional
# until the merger lands it and maps the id). One change rides it: a
# comment block in the Escape dispatcher (web/js/lib/escape_layers.js)
# naming the three assumptions behind the open-order rule (beforetoggle
# fires for showModal, beforetoggle is not composed, fullscreen is not
# detected as top layer). Comment-only, no behaviour change; the digest
# moves because the newline ending each added // line is a live byte
# (live_text keeps everything outside the comment spans). Ordinary
# case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping that one
# file back to its lane-tip d61245feb blob reproduces the superseded
# fd1764e1... value EXACTLY. That path is the whole change. No glyph
# change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# superseded by the RM-1083 re-capture below: "2c4794d9b4fbc31f0edb9b8fead4a02a3f57d749dc4dd1bf5e41c21f91139d9d"
#
# RE-CAPTURED 2026-10-28 at RM-1083 (s144 uiux cycle 55, provisional
# until the merger lands it and maps the id). THREE changes ride it.
# (1) RM-1081 (web/js/panels/panel_visibility.js, tab keyboard) and
# (2) RM-1082 (web/css/panels/panel_visibility.css, selected tab) moved
# the digest without re-capturing it, so this test was already red at the
# lane tip 6e72fe75a (241b920e...). (3) RM-1083 restyles the selected
# state of seven tab bars (web/css/panels/champ_benchmarks.css,
# duration_winrate.css, op_score.css, perf_curve.css, home.css,
# header.css). Ordinary case, no tokeniser change. ATTRIBUTED BY
# SUBSTITUTION: at this tree, reverting the six RM-1083 files AND
# swapping both panel_visibility files back to their b3f74344a blobs
# reproduces the superseded 2c4794d9... value EXACTLY; reverting only the
# six gives 241b920e... (the lane tip). Those eight paths are the whole
# change. No glyph change: the added lines carry 0 non-ASCII bytes. If
# another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1084 re-capture below: "26408507ccd0f052d5a90e0ae7bbb0738c454443fcfe8b15e63721ed2eb5a3f6"
#
# RE-CAPTURED 2026-10-28 at RM-1084 (s144 uiux cycle 56, provisional
# until the merger lands it and maps the id). One change rides it: the
# User Builds rune tree tabs gain aria-selected (and role="tab" on the
# secondary bar) in web/js/main.js _ubRpRenderTabs / _ubRpRenderSecTrees,
# plus a --text-dim / --text caption split and the system focus ring in
# web/css/panels/header.css. Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping those two files back to their lane
# tip 846db25c0 blobs reproduces the superseded 26408507... value EXACTLY.
# Those two paths are the whole change. No glyph change: the added lines
# carry 0 non-ASCII bytes. If another slice re-captures in parallel, the
# merger recomputes.
# superseded by the RM-1085 re-capture below: "b57cc4716a891730e036fa0f592bf590756f47debd153b70fb9a6ef6625e3042"
#
# RE-CAPTURED 2026-10-28 at RM-1085 + RM-1086 (s144 uiux cycle 57,
# provisional until the merger lands it and maps the ids). One change
# rides it: the
# User Builds rune tree tablists gain a roving tabindex, arrow / Home / End
# keys, focus carried across the innerHTML rebuild, and tab ids plus
# aria-controls in web/js/main.js, and the two rows panes become
# role="tabpanel" in web/index.html. Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping those two files back to their lane
# tip b4ed4cd74 blobs reproduces the superseded b57cc471... value EXACTLY.
# Those two paths are the whole change. No glyph change: the added lines
# carry 0 non-ASCII bytes. If another slice re-captures in parallel, the
# merger recomputes.
# superseded by the RM-1087 re-capture below: "3074e40873fc552aaa654960b6403b304ebf791f5d7f26098849319627a948be"
#
# RE-CAPTURED 2026-10-28 at RM-1087 (s144 uiux cycle 58, provisional
# until the merger lands it and maps the id). One change rides it: the
# User Builds rune cells (.ub-rp-rune) draw the system focus ring on
# :focus-visible in web/css/panels/header.css. Ordinary case, no
# tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping that file back
# to its lane tip b5a8dfe25 blob reproduces the superseded 3074e408...
# value EXACTLY. That one path is the whole change. No glyph change: the
# added lines carry 0 non-ASCII bytes. If another slice re-captures in
# parallel, the merger recomputes.
# superseded by the RM-1089 re-capture below: "e32f8d5c468ad15e6edfbe07f17382160ca8eeb38e21a28a11451262462d37f5"
#
# RE-CAPTURED 2026-10-28 at RM-1089 (s144 queue cycle 32, provisional
# until the merger lands it). One change rides it: the rc:champs-ready
# listener in web/js/main.js re-renders the lobby duo block, so portraits
# resolve when the champion index lands after the duo response. Ordinary
# case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# web/js/main.js back to its local-main e14071faa blob (in memory)
# reproduces the superseded 89c8be0e... value EXACTLY. That path is the
# whole change. No glyph change: the added lines carry 0 non-ASCII bytes.
# lane/uiux 49192018e re-captures this same line in parallel, so the merger
# recomputes.
# MERGED 2026-10-28 by the session 144 L5 merger onto main (lane commit 1767e37c6): main had moved
# this pin since the lane base, so the superseded value above is main's and
# the value below is recomputed over the merged tree.
# superseded by the RM-896 re-capture below: "45d25ab4e737296ea61cfaf26b3b4a34db56392d878eaafde7b73589494f28cf"
#
# RE-CAPTURED 2026-10-28 at RM-896 (s144 queue cycle 35, the right_now.js
# half; provisional until the merger lands it). One change rides it:
# renderRightNow in web/js/panels/right_now.js reads the coach payload
# through live_directive_gate.withoutLiveDirectives while a game is live.
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping
# exactly web/js/panels/right_now.js back to its lane/queue db297b1ef blob
# (in memory) reproduces the superseded f477037b... value EXACTLY. That path
# is the whole change. No glyph change: the added lines carry 0 non-ASCII
# bytes. lane/uiux re-captures this line in parallel, so the merger
# recomputes.
# MERGED 2026-10-28 by the session 144 L5 merger onto main (lane commit a7b165a45): main had moved
# this pin since the lane base, so the superseded value above is main's and
# the value below is recomputed over the merged tree.
# superseded by the RM-1093 re-capture below: "d249371e441175a285fc76471445c8d6510a1a75bb2a8d3c808fde0eb20b8f45"
#
# RE-CAPTURED 2026-10-28 at RM-1093 (s144 queue cycle 36, provisional
# until the merger lands it). One change rides it: renderActiveMatch in
# web/js/panels/active_match.js reads coach.action / immediate / next on the
# feed path through live_directive_gate.withoutLiveDirectives while a game is
# live. Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION:
# swapping exactly web/js/panels/active_match.js back to its lane/queue
# a7b165a45 blob (in memory) reproduces the superseded 11dceaa2... value
# EXACTLY. That path is the whole change. No glyph change: the added lines
# carry 0 non-ASCII bytes. lane/uiux re-captures this line in parallel, so
# the merger recomputes.
# MERGED 2026-10-28 by the session 144 L5 merger onto main (lane commit f9f786d71): main had moved
# this pin since the lane base, so the superseded value above is main's and
# the value below is recomputed over the merged tree.
# superseded by the RM-1133 re-capture below: "c3f3b3bf1767ce77fcaeab8f1af2e57d5b3758a3390b54df8d1ec596f087969e"
#
# RE-CAPTURED 2026-10-30 at RM-1133 (s144 uiux cycle 61, provisional
# until the merger lands it and maps the id). One change rides it: the
# User Builds spell chooser - the D / F slots and the grid cells draw the
# system focus ring and the slots carry aria-pressed (web/css/panels/
# header.css, web/index.html, web/js/main.js _ubSpellRenderCurrent).
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping
# those three files back to their lane HEAD 491949dc3 blobs (in memory)
# reproduces the superseded c3f3b3bf... value EXACTLY. Those three paths
# are the whole change. No glyph change: the added lines carry 0 non-ASCII
# bytes. If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1084 residue re-capture below: "80c1b8522089f13ad72543428c590f0604df98ce61293f3ca21c58ec1e00adfa"
#
# RE-CAPTURED 2026-10-30 at RM-1084 residue (s144 uiux cycle 62,
# provisional until the merger lands it and maps the id). One change rides
# it: the Lobby YOUR MAINS / PARTY MAINS tabs (.lv-mc-tab) take the
# --hit-min floor and draw the system focus ring (web/css/panels/
# header.css). Ordinary case, no tokeniser change. ATTRIBUTED BY
# SUBSTITUTION: swapping exactly web/css/panels/header.css back to its lane
# HEAD 9e677f2f4 blob (in memory) reproduces the superseded 80c1b852...
# value EXACTLY. That path is the whole change. No glyph change: the added
# lines carry 0 non-ASCII bytes. If another slice re-captures in parallel,
# the merger recomputes.
# superseded by the RM-1084 view-menu re-capture below: "478a1f4986c2a4867e877a999c0c69b5abd2148b93e8d71135502f98e0f9be4e"
#
# RE-CAPTURED 2026-10-30 at RM-1084 last residue (s144 uiux cycle 63,
# provisional until the merger lands it and maps the id). One change rides
# it: the title dropdown's view menu rows (.view-menu-item) - the current
# row takes --text, every row draws the system focus ring and meets the
# --fs-xs type floor (was 15px), and main.js
# _viewUpdateMenuActive stamps aria-current="page" (web/css/panels/
# header.css, web/js/main.js). Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping those two files back to their lane
# HEAD 0e1d2a7d1 blobs (in memory) reproduces the superseded 478a1f49...
# value EXACTLY. Those two paths are the whole change. No glyph change: the
# added lines carry 0 non-ASCII bytes. If another slice re-captures in
# parallel, the merger recomputes.
# superseded by the RM-1134 re-capture below: "82814d1763c8487beb9bfb33ccac2c40dbd93fe3507399b7f80d148d05a57108"
#
# RE-CAPTURED 2026-10-30 at RM-1134 (s144 uiux cycle 65, provisional
# until the merger lands it and maps the id). One change rides it: the dead
# section-button co-selector leaves the History .view-tab base / :hover
# rules and the arcane selected-tab underline list (web/css/panels/
# header.css, web/css/themes.css); no page or script ever rendered that
# class. Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION:
# swapping those two files back to their lane HEAD fcc68307a blobs (in
# memory) reproduces the superseded 82814d17... value EXACTLY. Those two
# paths are the whole change. No glyph change: the added lines carry 0
# non-ASCII bytes. If another slice re-captures in parallel, the merger
# recomputes.
# superseded by the RM-1136 re-capture below: "70459a3110c559322e4bae0074ce6b6ae9ab839eed568961d8c1997667a2f1b2"
#
# RE-CAPTURED 2026-10-30 at RM-1136 (s144 uiux cycle 67, provisional
# until the merger lands it and maps the id). One change rides it: the Post
# Game Review "Detailed stats" summary (.lm-hero-stats-summary) takes the
# --hit-min floor and draws the system focus ring (web/css/panels/
# last_match.css). Ordinary case, no tokeniser change. ATTRIBUTED BY
# SUBSTITUTION: swapping exactly web/css/panels/last_match.css back to its
# lane HEAD 8ddb269bc blob (in memory) reproduces the superseded 70459a31...
# value EXACTLY. That path is the whole change. No glyph change: the added
# lines carry 0 non-ASCII bytes. If another slice re-captures in parallel,
# the merger recomputes.
# superseded by the RM-1137 re-capture below: "eb16b9ec1744b55f742606c0a66fc7e2559eec859ec0aa2eee2b453262724475"
#
# RE-CAPTURED 2026-10-30 at RM-1137 (s144 uiux cycle 68, provisional
# until the merger lands it and maps the id). One change rides it: the
# Champ Select LOCK IN button (#csv-lock-btn) draws the inset system focus
# ring (web/css/panels/champ_select_view.css) and keeps keyboard focus across
# a central-pane rebuild (web/js/panels/champ_select.js
# _csvCaptureChooserFocus / _csvRestoreChooserFocus). Ordinary case, no
# tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly those two
# paths back to their lane HEAD f9c2ba452 blobs (in memory) reproduces the
# superseded eb16b9ec... value EXACTLY; swapping either one alone does not.
# Those two paths are the whole change. No glyph change: the added lines
# carry 0 non-ASCII bytes. If another slice re-captures in parallel, the
# merger recomputes.
# superseded by the RM-1138 re-capture below: "55c98a0d04dac475c5265d1a160491811b7a60bd000bd359507f4a77e5e8755c"
#
# RE-CAPTURED 2026-10-30 at RM-1138 (s144 uiux cycle 69, provisional
# until the merger lands it and maps the id). One change rides it: the
# Champ Select LOCK IN click hold moves from the clicked node (btn.disabled)
# to module scope and renders as aria-disabled="true", so a central-pane
# rebuild inside the 1.5s window cannot fire a second lock_pick and the
# button keeps keyboard focus (web/js/panels/champ_select.js
# _csvLockHeld / _csvSetLockHold, web/css/panels/champ_select_view.css the
# held-state rule). Ordinary case, no tokeniser change. ATTRIBUTED BY
# SUBSTITUTION: swapping exactly those two paths back to their lane HEAD
# 527c53bdb blobs (in memory) reproduces the superseded 55c98a0d... value
# EXACTLY; swapping either one alone does not. Those two paths are the whole
# change. No glyph change: the added lines carry 0 non-ASCII bytes. If
# another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1139 re-capture below: "f6e74fab3c3e66d4d7f0bcb6c7e26fdab6477c183ee2700d4790a332d4ed63f4"
#
# RE-CAPTURED 2026-10-30 at RM-1139 (s144 uiux cycle 70, provisional
# until the merger lands it and maps the id). One change rides it: the
# Lobby Find Match click hold moves from the node (find.disabled) to _LV and
# renders as aria-disabled="true", so the lobby refresh cannot re-arm it
# inside the 1.5s window and the button keeps keyboard focus; a search flip
# hands focus between Find Match and Cancel Queue (web/js/main.js
# _lvFindHeld / _lvSetFindHold and the _lobbyViewRefresh focus hand-off,
# web/css/panels/header.css the held-state rules). Ordinary case, no
# tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly those two
# paths back to their lane HEAD f944c06a3 blobs reproduces the superseded
# f6e74fab... value EXACTLY; swapping either one alone does not. Those two
# paths are the whole change. No glyph change: the added lines carry 0
# non-ASCII bytes. If another slice re-captures in parallel, the merger
# recomputes.
# superseded by the RM-1140 re-capture below: "2fccc2e2f484333d57dd83d211bf9c3ef9cea8a0c86f327525aa9bb8c98a0c55"
#
# RE-CAPTURED 2026-10-30 at RM-1140 (s144 uiux cycle 71, provisional
# until the merger lands it and maps the id). One change rides it: the
# Active Match combo timeline's action-queue input and keystone select
# (.dscombo-input / .dscombo-keystone) take the --hit-min floor and draw the
# system focus ring (web/css/panels/ds_combo.css). Ordinary case, no
# tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# web/css/panels/ds_combo.css back to its lane HEAD ddab05792 blob (in
# memory) reproduces the superseded 2fccc2e2... value EXACTLY. That path is
# the whole change. No glyph change: the added lines carry 0 non-ASCII
# bytes. If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1141 re-capture below: "c463b378f50e3074881e29afdf3b78922084947fccbcd3beb4c6ebcd4ff6ac69"
#
# RE-CAPTURED 2026-10-30 at RM-1141 (s144 uiux cycle 72, provisional
# until the merger lands it and maps the id). One change rides it: the
# Active Match DS knob inputs (.dsk-knob > input / .dss-knob input) draw the
# system focus ring on :focus-visible, inset on the flush Stat Sandbox strip
# (web/css/panels/ds_knobs.css and
# web/css/panels/ds_statcheck.css). Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping exactly those two files back to their
# lane HEAD 73f298473 blobs reproduces the superseded c463b378... value
# EXACTLY. Those paths are the whole change. No glyph change: the added
# lines carry 0 non-ASCII bytes. If another slice re-captures in parallel,
# the merger recomputes.
# superseded by the RM-1142 re-capture below: "49c4659148c2464c8db992e1cdf5234912205826ca1a1d3d0fa19b805e79d398"
#
# RE-CAPTURED 2026-10-30 at RM-1142 (s144 uiux cycle 73, provisional
# until the merger lands it and maps the id). One change rides it: every
# line of text on the Active Match DS matchup card reaches AA on its
# resolved surface - the pending "-" sentinels move to 0.55, the pending
# champion keeps its landed tint, and the red verdicts lighten
# --signal-bad through color-mix (web/css/panels/ds_matchup.css). Ordinary
# case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# that file back to its lane HEAD d9f8197a1 blob (in memory) reproduces the
# superseded 49c46591... value EXACTLY. That path is the whole change. No
# glyph change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# superseded by the RM-1143 re-capture below: "7b624e20490b3b7223839b46c0de73cac2ad9ee5cef3dfa8f48ab507290dbfa9"
#
# RE-CAPTURED 2026-10-30 at RM-1143 (s144 uiux cycle 74, provisional
# until the merger lands it and maps the id). One change rides it: the
# muted status lines on the Active Match DS relative-score card
# (.dsr-empty) and the Builds SHAPER row (.bm-shaper-note) move from white
# 0.45 to 0.55 so they reach AA on their resolved surface
# (web/css/panels/ds_relscore.css and web/css/panels/ds_shaper.css).
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping
# exactly those two files back to their lane HEAD 01fe43869 blobs (in
# memory) reproduces the superseded 7b624e20... value EXACTLY. Those paths
# are the whole change. No glyph change: the added lines carry 0 non-ASCII
# bytes. If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1144 re-capture below: "3d21cecbfd5c37ce82a5918cc57bc5fb1e7b014cbe1b19974edc0c5a36824a68"
#
# RE-CAPTURED 2026-10-30 at RM-1144 (s144 uiux cycle 75, provisional
# until the merger lands it and maps the id). One change rides it: the
# champ-select TEAM ANALYSIS label + caret and the ORDERED SEQUENCE tag /
# message / slot numbers move from --text-faint to --text-dim so they
# reach AA on their raised surfaces (web/css/panels/champ_select_view.css).
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping
# exactly that file back to its lane HEAD 4e86faea3 blob (in memory)
# reproduces the superseded 3d21cecb... value EXACTLY. That path is the
# whole change. No glyph change: the added lines carry 0 non-ASCII bytes.
# If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1197 re-capture below: "e14af6b480728c5f9e1a5eb4259c906267c60b6347cf6f46389a1802dd2019cd"
#
# RE-CAPTURED 2026-10-31 at RM-1197 (s144 uiux cycle 76, provisional
# until the merger lands it and maps the id). One change rides it: the
# Arena champ-select duo "ALLY" tag moves from --text-faint to --text-dim
# and the "pick one" augment title is mixed from --accent-2 toward --text,
# so both reach AA on their resolved surface
# (web/css/panels/champ_select_view.css). Ordinary case, no tokeniser
# change. ATTRIBUTED BY SUBSTITUTION: swapping exactly that file back to
# its lane HEAD fc123ec87 blob (in memory) reproduces the superseded
# e14af6b4... value EXACTLY. That path is the whole change. No glyph
# change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# superseded by the RM-1198 re-capture below: "2169c2067aa56128b69794a4a40af5105cb427679e77aca0c84860a64312f766"
#
# RE-CAPTURED 2026-10-31 at RM-1198 (s144 uiux cycle 77, provisional
# until the merger lands it and maps the id). One change rides it: the SR
# champ-select enemy win-rate slot's "--" no-games placeholder is mixed
# part-way from --text-faint toward --text-dim and its is-bad losing band
# from --bad toward --text, so both reach AA on the --surface-2 enemy cell
# (web/css/panels/champ_select_view.css). Ordinary case, no tokeniser
# change. ATTRIBUTED BY SUBSTITUTION: swapping exactly that file back to
# its lane HEAD d75f9b273 blob (in memory) reproduces the superseded
# 2169c206... value EXACTLY. That path is the whole change. No glyph
# change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# superseded by the RM-1199 re-capture below: "aa7662ceaf5f12b8043b54a5ccb1f165e4a2049ade359ea2f30537a9a6cbd8b4"
#
# RE-CAPTURED 2026-10-31 at RM-1199 (s144 uiux cycle 78, provisional
# until the merger lands it and maps the id). One change rides it: the SR
# champ-select enemy win-rate slot negative-caches a failed
# /api/personal-vs and repaints its last settled answer on a re-render
# (web/js/panels/champ_select.js _csvWrSlotFetch). Ordinary case, no
# tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly that file
# back to its lane HEAD b229ef1dd blob reproduces the superseded
# aa7662ce... value EXACTLY. That path is the whole change. No glyph
# change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# superseded by the RM-1200 re-capture below: "44bba1aa08ec13eab7d5b441f86cf82efe3e19735ce2265485410160c060f1aa"
#
# RE-CAPTURED 2026-10-31 at RM-1200 (s144 uiux cycle 79, provisional
# until the merger lands it and maps the id). One change rides it: the SR
# champ-select enemy win-rate slot fetch times out a request that never
# answers and keeps the last good win rate when a refetch fails
# (web/js/panels/champ_select.js _csvWrSlotFetch / _csvWrSlotApply).
# Ordinary case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION:
# swapping exactly that file back to its lane HEAD c7c9c726a blob
# reproduces the superseded 44bba1aa... value EXACTLY. That path is the
# whole change. No glyph change: the added lines carry 0 non-ASCII bytes.
# If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1201 re-capture below: "8f66c0891659c5d9005e2e9be23bbd78672e24f601ea5f77d7a4c5de75781cf2"
#
# RE-CAPTURED 2026-10-31 at RM-1201 (s144 uiux cycle 80, provisional
# until the merger lands it and maps the id). One change rides it: a win
# rate the SR champ-select enemy slot KEEPS after a failed refresh carries
# `is-stale` (italic + dotted underline, colour unchanged), and a 200
# ok:false /api/personal-vs body is settled as a failure, not "no games"
# (web/js/panels/champ_select.js _csvWrSlotApply / _csvWrSlotFetch and
# web/css/panels/champ_select_view.css). Ordinary case, no tokeniser
# change. ATTRIBUTED BY SUBSTITUTION: swapping exactly those two files
# back to their lane HEAD 8dd974d76 blobs reproduces the superseded
# 8f66c089... value EXACTLY. Those paths are the whole change. No glyph
# change: the added lines carry 0 non-ASCII bytes. If another slice
# re-captures in parallel, the merger recomputes.
# superseded by the RM-1202 re-capture below: "8d8ea8667068c023a41d864878f7b9d90771b45883168acf5fcc1329f1864cbc"
#
# RE-CAPTURED 2026-10-31 at RM-1202 (s144 uiux cycle 81, provisional
# until the merger lands it and maps the id). One change rides it: the
# Arena champ-select "pick one" augment option rows are keyboard buttons
# with the inset focus ring, keep their pick and focus across a pane
# rebuild, re-render on a new offer, and read an int round index
# (web/js/panels/champ_select.js _csvArenaPaneHtml / _csvWireArenaAugments
# / _csvComputeSig and web/css/panels/champ_select_view.css). Ordinary
# case, no tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly
# those two files back to their lane HEAD 6bde72f63 blobs reproduces the
# superseded 8d8ea866... value EXACTLY. Those paths are the whole change.
# No glyph change: the added lines carry 0 non-ASCII bytes. If another
# slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1204 re-capture below: "5dc46fc1fa2c9cef5b1f34f1824fd2969c388e93de81ffc07d9b76296e4c157a"
#
# RE-CAPTURED 2026-10-31 at RM-1204 (s144 uiux cycle 82, provisional
# until the merger lands it and maps the id). One change rides it: the
# Settings API SPEND GATES rows carry keyboard focus across their
# innerHTML rebuild by a data-gate key, repaint from the server after a
# failed toggle POST, and drop a response older than the newest request
# (web/js/panels/dev.js renderSpendGates). Ordinary case, no tokeniser
# change. ATTRIBUTED BY SUBSTITUTION: swapping exactly that one file back
# to its lane HEAD efbdf8eec blob reproduces the superseded 5dc46fc1...
# value EXACTLY. That path is the whole change. No glyph change: the
# added lines carry 0 non-ASCII bytes. The repo lane's unlanded dev.js
# header edit (RM-1182) is not in this tree; the merger recomputes on
# the merged tree.
# superseded by the RM-1205 re-capture below: "729e10eb70847c1b2a2a10c6a89065c68f1b8940b44e5e36565f446081fa20eb"
#
# RE-CAPTURED 2026-10-31 at RM-1205 (s144 uiux cycle 83, provisional
# until the merger lands it and maps the id). One change rides it: the
# Settings API SPEND GATES list is not fetched or shown while Dev mode is
# off (a #spend-gates-list[hidden] rule; the bare display:flex beat the UA
# [hidden]), a failed refresh keeps the rows and shows a role=status hint,
# a vanished focused gate hands focus to its neighbour row, and a toggle
# drops a render already in flight (web/js/panels/dev.js renderSpendGates /
# _spendGatesStale and web/css/panels/header.css). Ordinary case, no
# tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly those two
# files back to their lane HEAD 0a186439b blobs reproduces the superseded
# 729e10eb... value EXACTLY. Those paths are the whole change. No glyph
# change: the added lines carry 0 non-ASCII bytes. The repo lane's
# unlanded dev.js header edit (RM-1182) is not in this tree; the merger
# recomputes on the merged tree.
# superseded by the RM-1206 re-capture below: "675410e608e5c11d3c6ac5ea01a27d113726e23e20558afd1107d5c140b99ddd"
#
# RE-CAPTURED 2026-10-31 at RM-1206 (s144 uiux cycle 84, provisional
# until the merger lands it and maps the id). One change rides it: a hidden
# champ-select .csv-sugg-section and a hidden Home .home-rank-wl strip now
# compute display:none (a [hidden] rule each; the bare display:flex beat
# the UA [hidden]) (web/css/panels/champ_select_view.css and
# web/css/panels/home.css). Ordinary case, no tokeniser change. ATTRIBUTED
# BY SUBSTITUTION: swapping exactly those two files back to their lane HEAD
# b0da38c8c blobs reproduces the superseded 675410e6... value EXACTLY, and
# either file alone gives a third value, so both contribute. Those paths
# are the whole change. No glyph change: the added lines carry 0 non-ASCII
# bytes. If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1208 re-capture below: "c6d3ea8663923f203c98a42b97abbd3ace71cf410286337b92b231897602df76"
#
# RE-CAPTURED 2026-10-31 at RM-1208 (s144 uiux cycle 86, provisional
# until the merger lands it and maps the id). One change rides it: a queue
# pop (MatchFound / ReadyCheck) holds Lobby Cancel Queue aria-disabled
# instead of disabled, so the focused button of the Find / Cancel pair
# keeps keyboard focus or hands it to Cancel, and the held Cancel is inert
# with no hover fill (web/js/main.js the _lobbyViewRefresh cancel block
# and the Cancel Queue click guard, web/css/panels/header.css the
# .lq-cancel hover rule). Ordinary case, no tokeniser change. ATTRIBUTED
# BY SUBSTITUTION: swapping exactly those two paths back to their lane
# HEAD 3406e29d4 blobs (in memory) reproduces the superseded c6d3ea86...
# value EXACTLY; swapping either one alone does not. Those two paths are
# the whole change. No glyph change: the added lines carry 0 non-ASCII
# bytes. If another slice re-captures in parallel, the merger recomputes.
# superseded by the RM-1209 re-capture below: "60bc8b16fabba25f1da9debe946118bcb4c92ab07801506fe712ef11c2b59c84"
#
# RE-CAPTURED 2026-10-31 at RM-1209 (s144 uiux cycle 87, provisional
# until the merger lands it and maps the id). One change rides it: the
# Lobby queue strip buttons gain a keyboard focus ring,
# `.lq-btn:focus-visible { outline: 2px solid var(--accent); outline-offset:
# 2px; }` and the same ring on `.lq-lane-pref.is-conflict:focus-visible`,
# each with its comment (web/css/panels/header.css). Ordinary case, no
# tokeniser change. ATTRIBUTED BY SUBSTITUTION: swapping exactly that path
# back to its lane HEAD 58b7f926f blob reproduces the superseded 60bc8b16...
# value EXACTLY. That path is the whole change. No glyph change: the added
# lines carry 0 non-ASCII bytes. If another slice re-captures in parallel,
# the merger recomputes.
# superseded by the RM-1210 re-capture below: "506e723245df4f444e8fb0c997fdb9831fa29fb770d9eee1ea307037a5a37cc4"
#
# RE-CAPTURED 2026-10-31 at RM-1210 (s144 uiux cycle 88, provisional
# until the merger lands it and maps the id). One change rides it: the
# Home launcher tiles and the History scope tabs gain a keyboard focus
# ring, `.home-action-tile:focus-visible` (web/css/panels/home.css) and
# `.view-tab:focus-visible` (web/css/panels/header.css), each a 2px
# --accent outline with its comment. Ordinary case, no tokeniser change.
# ATTRIBUTED BY SUBSTITUTION: swapping exactly those two paths back to
# their lane HEAD f4c339287 blobs reproduces the superseded 506e7232...
# value EXACTLY; swapping either one alone does not. Those two paths are
# the whole change. No glyph change: the added lines carry 0 non-ASCII
# bytes. If another slice re-captures in parallel, the merger recomputes.
_LIVE_HALF_DIGEST = "0f7eb637b5fd048af8f2ecda0d0f841aee9683d86d5b9d5e1fdb542fccbcf1b4"


def _web_sources() -> list[Path]:
    return [p for p in sorted(_WEB.rglob("*")) if p.is_file() and lang_for_path(p) is not None]


def _kind_at(text: str, lang: str, needle: str) -> str:
    """Span kind covering the first occurrence of `needle`."""
    offset = text.index(needle)
    for span in scan(text, lang):
        if span.start <= offset < span.end:
            return span.kind
    raise AssertionError(f"offset {offset} not covered by any span")


def _live_half_digest() -> str:
    digest = hashlib.sha256()
    for path in _web_sources():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        live = live_text(read_source(path), lang_for_path(path)).replace("\r\n", "\n")
        digest.update(rel.encode())
        digest.update(b"\n")
        digest.update(live.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


class SpansCoverTheWholeText(unittest.TestCase):
    def test_spans_are_contiguous_and_total(self) -> None:
        text = "a \u00b7 b // c \u2500\nd /* e \u2500 */ f\n"
        spans = scan(text, "js")
        self.assertEqual(spans[0].start, 0)
        self.assertEqual(spans[-1].end, len(text))
        for prev, nxt in zip(spans, spans[1:]):
            self.assertEqual(prev.end, nxt.start)
        self.assertEqual("".join(text[s.start:s.end] for s in spans), text)

    def test_lang_for_path(self) -> None:
        self.assertEqual(lang_for_path(Path("a/b.js")), "js")
        self.assertEqual(lang_for_path(Path("a/b.CSS")), "css")
        self.assertEqual(lang_for_path(Path("a/b.html")), "html")
        self.assertIsNone(lang_for_path(Path("a/b.py")))
        self.assertIsNone(lang_for_path(Path("a/b.json")))


class JsFalsePositivePins(unittest.TestCase):
    """Constructs that must NOT be swept."""

    def test_glyph_in_double_quoted_string_is_live(self) -> None:
        text = 'const a = "x \u2500 y";\n'
        self.assertEqual(_kind_at(text, "js", "\u2500"), LIVE)
        self.assertEqual(sweep_text(text, "js").changes, [])

    def test_glyph_in_single_quoted_string_is_live(self) -> None:
        text = "const a = 'x \u2192 y';\n"
        self.assertEqual(_kind_at(text, "js", "\u2192"), LIVE)
        self.assertEqual(sweep_text(text, "js").changes, [])

    def test_glyph_in_template_literal_is_live(self) -> None:
        text = "const a = `x \u00b7 ${v} \u2192 z`;\n"
        self.assertEqual(_kind_at(text, "js", "\u00b7"), LIVE)
        self.assertEqual(_kind_at(text, "js", "\u2192"), LIVE)
        self.assertEqual(sweep_text(text, "js").changes, [])

    def test_glyph_in_template_substitution_is_live(self) -> None:
        # `${}` can nest strings, braces and further templates; the whole
        # template is held LIVE rather than re-entering code mode inside it.
        text = "const a = `${o[`k \u2500`] || \"\u00b7\"} tail`;\n"
        self.assertEqual(_kind_at(text, "js", "\u2500"), LIVE)
        self.assertEqual(_kind_at(text, "js", "\u00b7"), LIVE)
        self.assertEqual(sweep_text(text, "js").changes, [])

    def test_double_slash_inside_a_string_does_not_open_a_comment(self) -> None:
        text = 'const u = "https://x.test/a";  // banner \u2500\u2500\n'
        self.assertEqual(_kind_at(text, "js", "https"), LIVE)
        self.assertEqual(_kind_at(text, "js", "// banner"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text,
                         'const u = "https://x.test/a";  // banner --\n')

    def test_escaped_quote_does_not_terminate_the_string_early(self) -> None:
        text = 'const s = "a\\"//b\u2500"; // tail \u2500\n'
        self.assertEqual(_kind_at(text, "js", "//b"), LIVE)
        self.assertEqual(_kind_at(text, "js", "// tail"), COMMENT)
        result = sweep_text(text, "js")
        self.assertEqual(len(result.changes), 1)
        self.assertEqual(result.text, 'const s = "a\\"//b\u2500"; // tail -\n')

    def test_regex_literal_holding_a_block_comment_open_is_live(self) -> None:
        text = "const re = /a\\/\\*\u2500b/g;\nlet n = 1;\n"
        self.assertEqual(_kind_at(text, "js", "\u2500"), LIVE)
        self.assertEqual(sweep_text(text, "js").changes, [])

    def test_regex_literal_in_a_call_position_is_live(self) -> None:
        text = "if (/^[\u26a0\u2713\u25b6]?\\s*DEAD/i.test(s)) { n++; }\n"
        self.assertEqual(_kind_at(text, "js", "\u26a0"), LIVE)
        self.assertEqual(sweep_text(text, "js").changes, [])

    def test_html_comment_open_inside_js_is_not_a_comment(self) -> None:
        text = 'const s = "<!-- \u2500 -->";\n'
        self.assertEqual(_kind_at(text, "js", "\u2500"), LIVE)
        self.assertEqual(sweep_text(text, "js").changes, [])


class TemplateSubstitutionResync(unittest.TestCase):
    """A `${}` interior is JS CODE, so a bare quote can sit outside a string.

    Regex literals and comments both carry quotes that open nothing. Reading one
    as a string open desyncs the scanner, the template never closes, and every
    comment after it silently classifies LIVE - a guard that reports green by
    not looking. These pins measure the RESYNC point, not the interior: the
    substitution itself stays LIVE either way (that choice is pinned above by
    test_glyph_in_template_substitution_is_live), so the only observable is
    whether the code AFTER the template is tokenised at all.
    """

    def test_regex_literal_holding_quotes_does_not_run_the_template_away(self) -> None:
        text = ("const a = `x${s.replace(/['\"]/g, \"\")}y`;\n"
                "// banner \u2500\u2500\n")
        self.assertEqual(_kind_at(text, "js", "// banner"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text,
                         "const a = `x${s.replace(/['\"]/g, \"\")}y`;\n// banner --\n")

    def test_the_shape_that_actually_shipped_in_web(self) -> None:
        # web/js/panels/last_match.js, champ_select.js and historical_pgr.js all
        # build attribute markup this way; the `/"/g` is what blinded the sweep.
        text = ('const li = `<li data-tt="${w.replace(/"/g, "&quot;")}">${t}</li>`;\n'
                "// tail \u2192 note\n")
        self.assertEqual(_kind_at(text, "js", "// tail"), COMMENT)
        self.assertEqual(_kind_at(text, "js", "data-tt"), LIVE)
        self.assertEqual(sweep_text(text, "js").text,
                         'const li = `<li data-tt="${w.replace(/"/g, "&quot;")}">${t}</li>`;\n'
                         "// tail -> note\n")

    def test_division_inside_a_substitution_is_not_read_as_a_regex(self) -> None:
        # The false-positive side of the same predicate: `/` after an identifier
        # is division, so it must not swallow the rest of the substitution.
        text = "const a = `${w / h} ratio`;\n// tail \u2500\n"
        self.assertEqual(_kind_at(text, "js", "\u2500"), COMMENT)
        self.assertEqual(_kind_at(text, "js", "ratio"), LIVE)
        self.assertEqual(sweep_text(text, "js").text,
                         "const a = `${w / h} ratio`;\n// tail -\n")

    def test_comment_holding_a_quote_does_not_run_the_template_away(self) -> None:
        text = "const a = `p${ f(/* don't */ x) }e`;\n// tail \u2500\n"
        self.assertEqual(_kind_at(text, "js", "// tail"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text,
                         "const a = `p${ f(/* don't */ x) }e`;\n// tail -\n")

    def test_line_comment_holding_a_backtick_does_not_run_the_template_away(self) -> None:
        text = "const a = `p${ f(x) // a ` tick\n) }e`;\n// tail \u2500\n"
        self.assertEqual(_kind_at(text, "js", "// tail"), COMMENT)
        self.assertEqual(sweep_text(text, "js").changes[0].original, "\u2500")


class JsTruePositivePins(unittest.TestCase):
    """Constructs that MUST be swept."""

    def test_line_comment_glyph_is_swept(self) -> None:
        text = "// \u2500\u2500 Panel modules \u2500\u2500\nconst a = 1;\n"
        self.assertEqual(_kind_at(text, "js", "\u2500"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text, "// -- Panel modules --\nconst a = 1;\n")

    def test_block_comment_glyph_is_swept(self) -> None:
        text = "/* refresh 1-2s \u2192 stale at ~4s \u00b7 severe */\nconst a = 1;\n"
        self.assertEqual(_kind_at(text, "js", "\u2192"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text,
                         "/* refresh 1-2s -> stale at ~4s - severe */\nconst a = 1;\n")

    def test_division_does_not_swallow_the_following_comment(self) -> None:
        # `/` after an identifier is division, not a regex open - so the `//`
        # further along the line must still register as a comment.
        text = "const r = a / b; // note \u2500\n"
        self.assertEqual(_kind_at(text, "js", "// note"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text, "const r = a / b; // note -\n")

    def test_unterminated_regex_falls_back_to_division(self) -> None:
        # A `/` in regex-allowed position whose literal never closes on the
        # same line is division; the trailing comment must survive.
        text = "const r = (a + b) / c; // note \u2500\n"
        self.assertEqual(_kind_at(text, "js", "// note"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text, "const r = (a + b) / c; // note -\n")

    def test_unterminated_block_comment_runs_to_eof(self) -> None:
        text = "const a = 1;\n/* tail \u2500"
        self.assertEqual(_kind_at(text, "js", "\u2500"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text, "const a = 1;\n/* tail -")


class CssPins(unittest.TestCase):
    def test_content_value_glyph_is_live(self) -> None:
        text = '.a::before { content: "\u2500-ish glyph"; }\n'
        self.assertEqual(_kind_at(text, "css", "\u2500"), LIVE)
        self.assertEqual(sweep_text(text, "css").changes, [])

    def test_block_comment_open_inside_a_css_string_is_live(self) -> None:
        text = '.a::before { content: "/* \u2500 */"; }\n'
        self.assertEqual(_kind_at(text, "css", "\u2500"), LIVE)
        self.assertEqual(sweep_text(text, "css").changes, [])

    def test_css_comment_glyph_is_swept(self) -> None:
        text = "/* \u2500\u2500\u2500 Footer \u2500\u2500\u2500 */\n.a { color: red; }\n"
        self.assertEqual(_kind_at(text, "css", "\u2500"), COMMENT)
        self.assertEqual(sweep_text(text, "css").text,
                         "/* --- Footer --- */\n.a { color: red; }\n")

    def test_css_has_no_line_comment(self) -> None:
        # `//` is not a CSS comment; a URL value must stay LIVE.
        text = ".a { background: url(https://x.test/i.png); }\n"
        self.assertEqual(comment_spans(text, "css"), [])


class HtmlPins(unittest.TestCase):
    def test_text_node_and_attribute_glyphs_are_live(self) -> None:
        text = '<p title="t \u00b7 u">text \u2192 node</p>\n'
        self.assertEqual(_kind_at(text, "html", "\u00b7"), LIVE)
        self.assertEqual(_kind_at(text, "html", "\u2192"), LIVE)
        self.assertEqual(sweep_text(text, "html").changes, [])

    def test_html_comment_glyph_is_swept(self) -> None:
        text = '<!-- s162: \u21bb AUTO pill removed -->\n<p>\u2665 -</p>\n'
        self.assertEqual(_kind_at(text, "html", "\u21bb"), COMMENT)
        self.assertEqual(_kind_at(text, "html", "\u2665"), LIVE)
        self.assertEqual(sweep_text(text, "html").text,
                         "<!-- s162: (R) AUTO pill removed -->\n<p>\u2665 -</p>\n")

    def test_embedded_script_and_style_comments_are_left_alone(self) -> None:
        # PINNED CHOICE: .html is tokenised with the HTML recogniser ONLY.
        # Modelling the <script>/<style> content-model boundary correctly (raw
        # text elements, `</script>` inside a JS string, CDATA) buys nothing
        # here - MEASURED 2026-07-28, the two inline <script> blocks in
        # web/index.html carry ZERO non-ASCII bytes. Under-sweeping is the safe
        # direction; mis-sweeping a live glyph is not.
        text = "<script>\n// js banner \u2500\n</script>\n<style>/* \u2500 */</style>\n"
        self.assertEqual(_kind_at(text, "html", "\u2500"), LIVE)
        self.assertEqual(sweep_text(text, "html").changes, [])


class FailLoudlyOnUnmappedGlyphs(unittest.TestCase):
    def test_unmapped_comment_glyph_is_reported_and_not_mangled(self) -> None:
        text = "// snow \u2603 here\nconst a = 1;\n"
        result = sweep_text(text, "js")
        self.assertEqual(result.changes, [])
        self.assertEqual([u.char for u in result.unmapped], ["\u2603"])
        self.assertEqual(result.unmapped[0].offset, text.index("\u2603"))
        self.assertEqual(result.text, text)

    def test_unmapped_glyph_on_a_live_span_is_not_reported(self) -> None:
        text = 'const a = "\u2603";\n'
        result = sweep_text(text, "js")
        self.assertEqual(result.unmapped, [])
        self.assertEqual(result.text, text)

    def test_cli_exits_nonzero_and_names_file_line_offset_codepoint(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "x.js"
            target.write_bytes("const a = 1;\n// snow \u2603\n".encode())
            proc = subprocess.run(
                [sys.executable, str(_REPO_ROOT / "tools" / "web_ascii_sweep.py"),
                 "--dry-run", "--root", tmp],
                capture_output=True, text=True, check=False,
            )
            out = proc.stdout + proc.stderr
            self.assertNotEqual(proc.returncode, 0, out)
            self.assertIn("x.js", out)
            self.assertIn(":2", out)
            self.assertIn("U+2603", out)
            self.assertIn(str("const a = 1;\n// snow \u2603\n".index("\u2603")), out)


class ByteFidelity(unittest.TestCase):
    def test_crlf_is_preserved(self) -> None:
        text = "// a \u2500\r\nconst x = 1;\r\n"
        out = sweep_text(text, "js").text
        self.assertEqual(out, "// a -\r\nconst x = 1;\r\n")
        self.assertEqual(out.count("\r\n"), text.count("\r\n"))

    def test_no_trailing_newline_is_added(self) -> None:
        text = "// a \u2500"
        self.assertEqual(sweep_text(text, "js").text, "// a -")

    def test_read_source_does_not_translate_newlines(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "x.css"
            target.write_bytes(b"/* a */\r\n.b { c: d; }\r\n")
            self.assertEqual(read_source(target), "/* a */\r\n.b { c: d; }\r\n")


class ReplacementMap(unittest.TestCase):
    def test_map_values_are_ascii(self) -> None:
        for key, value in sweeper.REPLACEMENTS.items():
            self.assertTrue(
                all(ord(c) < 128 for c in value),
                f"replacement for U+{ord(key):04X} is not ASCII",
            )

    def test_map_keys_are_single_non_ascii_chars(self) -> None:
        for key in sweeper.REPLACEMENTS:
            self.assertEqual(len(key), 1, repr(key))
            self.assertGreater(ord(key), 127, repr(key))


class WebTreeInvariants(unittest.TestCase):
    """Whole-tree pins - these are the RM-125 acceptance."""

    def test_sweep_is_idempotent_over_web(self) -> None:
        dirty: list[str] = []
        for path in _web_sources():
            text = read_source(path)
            result = sweep_text(text, lang_for_path(path))
            if result.changes or result.unmapped:
                dirty.append(f"{path.relative_to(_REPO_ROOT).as_posix()} "
                             f"changes={len(result.changes)} unmapped={len(result.unmapped)}")
        self.assertEqual(dirty, [], "web/ is not swept clean:\n" + "\n".join(dirty))

    def test_changes_only_ever_land_in_comment_spans(self) -> None:
        # One fixture carrying the same glyph on BOTH sides of every construct
        # the tokeniser knows, so the containment property is measured rather
        # than inferred from sweep_text's control flow.
        text = (
            "// lead \u2500\n"
            'const s = "keep \u2500";\n'
            "const t = `keep \u2500 ${x} \u2500`;\n"
            "const re = /keep\u2500/g;\n"
            "/* mid \u2500 */\n"
            "const u = 'keep \u2500';  // trail \u2500\n"
        )
        spans = comment_spans(text, "js")
        result = sweep_text(text, "js")
        self.assertEqual(len(result.changes), 3, "expected exactly the 3 comment glyphs")
        for change in result.changes:
            self.assertTrue(
                any(s <= change.offset < e for s, e in spans),
                f"offset {change.offset} is outside every comment span",
            )
        self.assertEqual(result.text.count("\u2500"), 5, "a live glyph was swept")

    def test_live_half_digest_matches_the_pre_sweep_capture(self) -> None:
        # THE acceptance for RM-125: the concatenated LIVE half of web/ hashes
        # to the value captured before the sweep ran.
        self.assertEqual(
            _live_half_digest(),
            _LIVE_HALF_DIGEST,
            "web/ LIVE spans drifted - a rendered byte changed. See the "
            "re-capture note on _LIVE_HALF_DIGEST.",
        )


if __name__ == "__main__":
    unittest.main()
