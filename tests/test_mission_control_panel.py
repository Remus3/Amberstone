# arch: source-contract tests for the Mission Control panel (S4) | section=tests | frozen=no
"""Mission Control S4 - the dashboard panel wired to GET /api/loop-status.

The pure arm-then-confirm logic is covered by `node --test
web/mc/arm_confirm.test.mjs`. What CANNOT be covered there is the wiring
between three files that only meet in a browser: the host element in
index.html, the renderer in mc.js, and the classes in mc.css. Those are
pinned here at source level, the same way tests/test_panel_visibility_permode.py
pins its DOM/CSS contract.

The regression that motivates the first test is not hypothetical. Before S4,
`#loop-status-body` existed ONLY as a CSS class and a getElementById call - it
was in no markup anywhere - so `renderLoopStatus` returned on its first line and
the panel shipped 2026-06-07 had never rendered once.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "web" / "mc" / "index.html"
MC_JS = ROOT / "web" / "mc" / "mc.js"
ARM_JS = ROOT / "web" / "mc" / "arm_confirm.js"
CSS = ROOT / "web" / "mc" / "mc.css"

_INDEX = INDEX.read_text(encoding="utf-8")
_MC = MC_JS.read_text(encoding="utf-8")
_ARM = ARM_JS.read_text(encoding="utf-8")
_CSS = CSS.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- the host exists
def test_loop_status_host_element_exists_in_the_markup():
    assert 'id="loop-status-body"' in _INDEX, (
        "renderLoopStatus() looks up #loop-status-body and returns immediately "
        "when it is absent - the panel then silently never renders")


def test_every_getelementbyid_the_loop_panel_needs_is_in_the_markup():
    # The renderer creates #loop-ctl-msg itself; #loop-status-body must pre-exist.
    assert 'getElementById("loop-status-body")' in _MC
    assert 'class="loop-status-body"' in _INDEX


def test_the_host_sits_below_a_visible_page_heading():
    """Renamed from ...with_a_settings_card_head (S10).

    web/mc/index.html is a standalone page, not a panel embedded in the shared
    dashboard's `.settings-card` widget, so there is no `settings-card-head` to
    find. `.mc-head` is the standalone page's equivalent: the heading a reader
    sees before the host, same protective intent as before.
    """
    idx = _INDEX.index('id="loop-status-body"')
    before = _INDEX[max(0, idx - 600):idx]
    assert "mc-head" in before, "the page needs a visible heading before the host"
    assert "MISSION CONTROL" in before


# --------------------------------------------------------------------------- three lock states
def test_renderer_knows_all_three_lock_states():
    for state in ("FREE", "RUNNING", "RECLAIMABLE"):
        assert state in _MC, f"{state} is never referenced by the renderer"


def test_reclaimable_is_styled_apart_from_running():
    """RECLAIMABLE must never render as RUNNING - they differ by a pid probe."""
    def rule(selector):
        m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", _CSS)
        assert m, f"missing CSS rule for {selector}"
        return m.group(1)

    run_dot = rule(".loop-lock-dot.running")
    rec_dot = rule(".loop-lock-dot.reclaimable")
    assert run_dot.strip() != rec_dot.strip()
    assert "--good" in run_dot and "--warn" in rec_dot

    run_txt = rule(".loop-lock-state.running")
    rec_txt = rule(".loop-lock-state.reclaimable")
    assert run_txt.strip() != rec_txt.strip()


def test_reclaimable_carries_an_explanatory_note():
    assert 'st === "RECLAIMABLE"' in _MC
    assert "holder is gone" in _MC


def test_an_absent_lock_block_still_renders_a_row():
    # feedback_no_reflow_on_data_absence: a vanishing row shifts everything below it.
    assert "UNAVAILABLE" in _MC
    assert ".loop-lock-meta" in _CSS and "min-height" in _CSS


def test_both_locks_are_rendered_separately():
    assert '_loopLockRow(mk, "LANE", d.lanes)' in _MC
    assert '_loopLockRow(mk, "LOOP", d.controller_lock)' in _MC


# --------------------------------------------------------------------------- arm-then-confirm
def test_panel_uses_the_arm_controller():
    assert "from './arm_confirm.js'" in _MC
    assert "createArmController(" in _MC


def test_the_idempotency_key_comes_from_the_confirm_result():
    """Minted at ARM, consumed at FIRE - never a page-load constant.

    MEASURED (docs/MISSION_CONTROL_PLAN.md): a refusal is remembered like any
    settled 200, so one key reused across arms replays "refused" forever.
    """
    assert "idempotency_key: key" in _MC
    fire = _MC[_MC.index("function _mcFire("):]
    fire = fire[:fire.index("\n}\n")]
    assert "key" in fire.split("(", 1)[1].split(")", 1)[0], (
        "_mcFire must take the key as an argument, not read a module-scope one")
    assert "_mcArm.confirm(sc.id)" in _MC
    assert "if (res.fired) _mcFire(sc, res.key);" in _MC


def test_disarm_discards_the_key():
    body = _ARM[_ARM.index("function disarm("):]
    body = body[:body.index("\n  }")]
    assert re.search(r"^\s*key = null;", body, re.M), (
        "disarm must null the key - keeping it lets the next arm reuse a "
        "already-settled key")


def test_the_queued_shortcuts_are_wired():
    assert '"halt_save"' in _MC and '"done_continue"' in _MC


def test_a_lane_fire_goes_through_arm_then_confirm_like_everything_else():
    """S5 wires fire_lane. It must NOT get a cheaper path than the shortcuts.

    A lane fire starts a real headless run, so if any control in this panel
    deserves the confirm window it is this one.
    """
    assert 'action: "fire_lane"' in _MC
    assert "_mcArm.confirm(id)" in _MC
    assert "if (res.fired) _mcFireLane(lane, res.key);" in _MC
    assert "idempotency_key: key" in _MC


def test_the_client_never_sends_a_worktree_path():
    """Filesystem layout is the server's business.

    A hardcoded client path is how a lane ends up pointed somewhere it must
    never run - and the main-tree ban is the one thing that cannot be allowed
    to depend on a string in a browser.
    """
    fire = _MC[_MC.index("function _mcFireLane("):]
    fire = fire[:fire.index("\n}\n")]
    assert "worktree" not in fire


def test_the_armed_state_wins_over_the_lane_colour():
    """`.loop-lane-btn` sits AFTER `.loop-btn-armed` at equal specificity.

    Unscoped, source order handed it the colour and the armed lane rendered
    --warn on --warn: 1.00:1, invisible, on the 3s window before a REAL
    headless run starts. Measured in Chrome.
    """
    assert ".loop-lane-btn:not(.loop-btn-armed)" in _CSS
    assert not re.search(r"^\.loop-lane-btn\s*\{", _CSS, re.M), (
        "an unscoped .loop-lane-btn rule would clobber the armed ink again")


def test_every_armable_action_still_offers_cancel():
    """The heavier actions must not have the weaker abort affordance.

    Widened for S9. The literal `if (anyArmed || laneArmed)` this used to match
    was true and brittle: adding a THIRD armable action (INTERRUPT, the only
    one that kills) broke the assertion without breaking the property, which is
    the wrong way round. Assert the property - every armable flag reaches both
    the cancel affordance and the countdown timer.
    """
    import re
    cancel = re.search(r"if \(([^)]*Armed[^)]*)\) \{", _MC)
    assert cancel, "no armed-gated cancel block found at all"
    for flag in ("anyArmed", "laneArmed", "irqArmed"):
        assert flag in cancel.group(1), (
            f"{flag} can arm but has no visible abort - the heavier the act, "
            "the more it needs one")
        assert flag in _MC[_MC.index("_mcSetTimer(anyArmed"):], (
            f"{flag} arms without starting the countdown, so its 3s "
            "auto-disarm never fires and the arm is effectively permanent")


def test_the_lane_sub_head_states_the_contract_and_the_wired_count():
    """Five permanently-dim buttons need a permanent explanation.

    "REFUSED IF HELD" alone is a transient reason for a permanent state, and
    the real one lived only in a title a disabled button does not announce.
    """
    assert "ARM, THEN CONFIRM" in _MC
    assert '" of "' in _MC and "wired" in _MC


def test_the_steer_row_offers_note_and_steer_but_not_interrupt():
    """INTERRUPT is stage S9 and needs operator sign-off.

    A button that looked like it worked would be worse than no button - the
    whole point of the tier ladder is that escalating is a decision.
    """
    assert 'action: "steer"' in _MC
    assert '_sendSteer("note")' in _MC and '_sendSteer("steer")' in _MC
    assert "loop-btn-interrupt" not in _MC
    assert '_sendSteer("interrupt")' not in _MC


def test_a_steer_mints_its_own_idempotency_key_per_send():
    """Same rule as the arm path: one key per operator INTENT, never per page."""
    assert "idempotency_key: _mcSteerKey()" in _MC


def test_an_empty_steer_is_refused_client_side_too():
    assert "steer: type something first" in _MC


def test_send_steer_does_not_wear_the_lane_or_shortcut_colour():
    """MEASURED: --accent and --warn are the same gold in 5 of 6 themes.

    An accented Send STEER rendered identically to a lane button that starts a
    real headless worker, and declaration-for-declaration identical to
    .loop-shortcut, whose single click only ARMS. Two identical-looking buttons
    with opposite click contracts is the confusion arm-then-confirm prevents.
    """
    # Match a RULE, not a mention - the comment above these deletions names
    # both classes to explain why they are gone. Third time this trap has bitten
    # in this file; scan comment-stripped CSS.
    css = re.sub(r"/\*.*?\*/", "", _CSS, flags=re.S)
    assert not re.search(r"\.loop-btn-steer\s*[,:{]", css)
    assert not re.search(r"\.loop-btn-note\s*[,:{]", css), (
        ".loop-btn already sets color: var(--text) - the rule was a no-op "
        "pretending to be a decision")
    assert 'btn("Send STEER", ""' in _MC
    assert 'btn("Send NOTE", ""' in _MC


def test_both_textareas_have_an_accessible_name():
    """A placeholder is not a name - it vanishes on the first keystroke."""
    for tid in ("loop-steer-input", "loop-directive-input"):
        seg = _MC[_MC.index(f'"{tid}"'):]
        seg = seg[:600]
        assert "aria-label" in seg, f"#{tid} has no accessible name"


def test_every_group_in_the_card_is_headed():
    """The directive block became the only unheaded group when S7 landed above
    it, so both textareas read as one STEER control."""
    for head in ("SHORTCUTS", "LANES", "STEER", "DIRECTIVE OVERRIDE"):
        assert head in _MC, f"missing sub-head: {head}"


def test_the_steer_row_is_not_gated_behind_arm_then_confirm():
    """Deliberate: a steer executes nothing and kills nothing, and the text has
    to be typed first, which IS the deliberate act. The confirm window is for
    things that cannot be taken back."""
    send = _MC[_MC.index("const _sendSteer ="):]
    send = send[:send.index("\n      };")]
    assert "_mcArm" not in send


def test_the_wired_lane_list_comes_from_the_server():
    """A client-side list drifts the moment a later stage wires a lane."""
    assert "d.lanes_available" in _MC
    assert ".wired" in _MC


def test_shortcuts_post_queue_intent():
    assert 'action: "queue_intent"' in _MC


def test_arm_window_is_short_enough_to_decay():
    m = re.search(r"ARM_WINDOW_MS\s*=\s*(\d+)", _ARM)
    assert m, "ARM_WINDOW_MS is not defined"
    assert 1000 <= int(m.group(1)) <= 5000, (
        "a stray click must decay faster than the operator forgets it")


# --------------------------------------------------------------------------- no dead classes
def test_every_new_class_the_renderer_emits_is_defined_in_css():
    emitted = [
        "loop-locks", "loop-lock-row", "loop-lock-label", "loop-lock-dot",
        "loop-lock-state", "loop-lock-meta", "loop-lock-note", "loop-sub-head",
        "loop-shortcuts", "loop-shortcut", "loop-btn-armed", "loop-btn-cancel",
    ]
    missing = [c for c in emitted if f".{c}" not in _CSS]
    assert not missing, f"classes emitted with no CSS rule: {missing}"


def test_every_custom_property_the_s4_css_uses_is_actually_defined():
    """A `var(--x)` naming a property no stylesheet defines is INVALID at
    computed-value time and silently falls back to the inherited value.

    MEASURED live: `.loop-btn-armed { color: var(--bg) }` rendered near-white on
    amber at 1.9:1, because `--bg` is defined in no stylesheet at all. It looked
    styled, it passed every source grep for the token name, and it was wrong on
    the one state where misreading the button costs the most.

    web/mc/mc.css carries no S4-only marker (S10 made it a standalone file that
    is entirely Mission Control), so this now checks the whole file rather than
    a sliced region - a widening, not a narrowing: it catches an undefined
    custom property anywhere in mc.css, not only in what used to be the S4 slice.

    THE AUTHORITY IS mc.css ITSELF (corrected 2026-08-02). Until now this
    resolved names against `web/css/**.css` - the game dashboard's token stack -
    which is a sheet the Mission Control page does not load. That was wrong in
    BOTH directions and only passed by coincidence, because the inlined palette
    happened to reuse dashboard token names:

      - false PASS: a name defined only in web/css/ and NOT inlined here reads
        as "defined" while resolving to nothing in the browser. That is the
        exact --bg failure above, and this test would have missed it.
      - false FAIL: a name this file legitimately defines for itself, like the
        arcane --pop, is reported missing because the dashboard has never heard
        of it.

    index.html links exactly one stylesheet, so mc.css defining every property
    mc.css uses IS the property under test. Resolving against anything else
    measures a page that does not exist.
    """
    block = _CSS
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)   # comments cite the bug
    used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", block))
    defined = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", block, re.M))
    missing = sorted(used - defined)
    assert not missing, (
        "mc.css references custom properties it does not define, and it is the "
        f"only stylesheet the page loads: {missing}")


def test_the_armed_ink_token_is_defined_in_the_default_layer():
    """Not merely defined SOMEWHERE - defined in THIS page's default layer.

    A token that only a theme defines still resolves to nothing when that theme
    is not active, which is the same silent failure as an undefined one. For a
    standalone page the default layer is its own unconditional `:root` block,
    NOT the dashboard's base.css - see the authority note on
    test_every_custom_property_the_s4_css_uses_is_actually_defined. This
    assertion was pointed at base.css and passed only because the armed ink
    token happens to share a name with a dashboard token; it would have gone on
    passing if mc.css had stopped defining it entirely.
    """
    m = re.search(r"\.loop-btn-armed\s*\{([^}]*)\}", _CSS)
    assert m, "missing .loop-btn-armed rule"
    ink = re.search(r"color:\s*var\(\s*(--[a-z0-9-]+)", m.group(1))
    assert ink, "the armed ink should come from a token, not a hardcoded literal"
    root = re.search(r"^:root\s*\{(.*?)^\}", _CSS, re.M | re.S)
    assert root, "mc.css no longer carries an unconditional :root block"
    assert re.search(rf"^\s*{ink.group(1)}\s*:", root.group(1), re.M), (
        f"{ink.group(1)} is not defined in mc.css's own :root, this page's "
        "only default layer")


def test_no_class_the_panel_emits_relies_on_a_bare_dim_rule():
    """`dim` is inert in web/css - every rule for it is descendant-scoped.

    The first cut put it on .loop-lock-meta, so the incidental pid/run metadata
    rendered BRIGHTER than the note explaining the RECLAIMABLE state next to it.
    """
    assert not re.search(r"^\s*\.dim\s*[,{]", _CSS, re.M)
    assert '"loop-lock-meta dim"' not in _MC
    meta = re.search(r"\.loop-lock-meta\s*\{([^}]*)\}", _CSS)
    assert meta and "color:" in meta.group(1), (
        ".loop-lock-meta must own its colour since `dim` does nothing")


def test_the_accent_border_survives_hover():
    """.loop-btn:hover is (0,2,0) and outranks .loop-shortcut (0,1,0)."""
    assert re.search(r"\.loop-shortcut:hover\s*\{[^}]*border-color", _CSS)


def test_the_buttons_have_a_focus_affordance():
    assert re.search(r"\.loop-btn:focus-visible\s*\{[^}]*outline", _CSS)


def test_the_countdown_repaint_preserves_keyboard_focus():
    """The armed row is rebuilt 4x/second; focus must survive the rebuild.

    Without this, arming from the keyboard threw focus to <body> and the confirm
    click inside the 3s window was unreachable - the flow was mouse-only.
    """
    paint = _MC[_MC.index("function _mcPaint("):]
    paint = paint[:paint.index("\n}\n")]
    assert "document.activeElement" in paint
    assert "refocus.focus()" in paint
    assert "dataset.mcId" in paint


def test_the_status_line_is_a_live_region():
    assert 'aria-live", "polite"' in _MC


def test_hit_targets_meet_the_minimum():
    m = re.search(r"\.loop-btn\s*\{([^}]*)\}", _CSS)
    assert m and "--hit-min" in m.group(1), (
        "shortcut buttons inherit .loop-btn sizing and must meet --hit-min")


# --------------------------------------------------------------------------- hygiene
def test_the_js_sources_are_ascii_only():
    for path, text in ((ARM_JS, _ARM), (MC_JS, _MC)):
        bad = sorted({ch for ch in text if ord(ch) > 127})
        assert not bad, f"{path.name} carries non-ASCII: {bad!r}"


def test_the_s4_markup_and_css_are_ascii_only():
    """Both files are entirely Mission Control now (S10 standalone move).

    Historically this sliced a marked S4 region out of the shared web/index.html
    and web/css/panels/header.css, because those files also carried PRE-EXISTING
    icon glyphs (arrows, a times, a mute speaker) unrelated to this change -
    sweeping the whole file would have silently broken icons. web/mc/index.html
    and web/mc/mc.css carry no other content and no S4 marker, so the whole file
    is the region now.
    """
    regions = {
        "index.html card": _INDEX,
        "mc.css block": _CSS,
    }
    for name, text in regions.items():
        bad = sorted({ch for ch in text if ord(ch) > 127})
        assert not bad, f"{name} carries non-ASCII: {bad!r}"
