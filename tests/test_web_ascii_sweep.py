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
# c7900b8c capture. It HAD to move: the digest is computed with the tokeniser's
# own classifier, and that fix corrected the comment/live partition (114 spans
# across 3 panels stopped being mis-read as LIVE). So the old value could not
# survive, and re-stamping it proves nothing on its own - the digest cannot
# police a change to the thing that computes it.
#
# What was measured instead, at the moment of the re-stamp: run the CORRECTED
# tokeniser over both the 525354ee tree and the swept tree and diff the live
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
# over 08c8aade and the post-fix tree with the SAME tokeniser, exactly one of
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
# both sides. Run over 97c74550 (the S9 capture commit) and HEAD with the SAME
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
# answer. Run over c0432e11 (the prior capture commit) and HEAD with the SAME
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
# THIS GUARD WENT RED ON THAT COMMIT (8b91d13a) AND THE RE-CAPTURE WAS MISSED,
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
# 2026-08-12 at f0501048), so nothing else moved the value. Note the three
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
# 149468f9), so nothing else moved the value. The three modified
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
# 30156a0b via a throwaway detached worktree), so nothing else moved the value.
# Note web/js/lib/overlay_layout.drag.test.mjs also changed in this slice and
# correctly does NOT appear above: _LANGS is .js / .css / .html, so .mjs is
# outside _web_sources. Confirmed by per-file live-half diff, not assumed.
# RE-CAPTURED at the RM-208/209/220/326/327/328/338 six-slice batch,
# superseding the 06da4a45 capture. Ordinary case: LIVE web edits, no
# tokeniser change, so the classifier is fixed and the two-tree diff is a
# straight answer. Run over a55ece97e and the merged tree with the SAME
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
# 9c6de1b68 and the post-RM-339 tree with the SAME tokeniser: 171 web/ sources
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
# diff is a straight answer. Run over 24bb113af and the post-RM-340 tree with
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
_LIVE_HALF_DIGEST = "6886c75f942c613c639c038bc4e50436ee7b25140ed028d2c0de1384852bda9e"


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
