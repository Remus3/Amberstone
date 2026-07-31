# arch: source-contract tests for the INTERRUPT panel block (S9) | section=tests | frozen=no
"""Mission Control S9 - the panel half of the tier that kills.

The pure arm-then-confirm lifecycle is covered by
`node --test web/js/lib/arm_confirm.test.mjs`. What cannot be covered there is
the property S9 exists for and that lives only in dev.js: **a confirm may only
be reached through a preview that named the victims.**

That is a wiring fact, not a logic fact. `_mcArm.arm()` for the interrupt is
called from INSIDE the preview response handler, never from the raw click, so
there is no code path that arms the kill without first putting names on screen.
A future edit that moves the arm up to the click handler would keep every
arm_confirm test green, keep the route tests green, and quietly turn the
button into a blind kill. This file is what catches that.

Source-level, same technique as tests/test_mission_control_panel.py: the three
files involved (dev.js, header.css, and the arm controller) only meet in a
browser.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV_JS = ROOT / "web" / "js" / "panels" / "dev.js"
CSS = ROOT / "web" / "css" / "panels" / "header.css"

_DEV = DEV_JS.read_text(encoding="utf-8")
_CSS = CSS.read_text(encoding="utf-8")


def _fn(name: str) -> str:
    """The body of one top-level function in dev.js."""
    start = _DEV.index(f"function {name}(")
    nxt = _DEV.find("\nfunction ", start + 1)
    return _DEV[start:nxt if nxt > 0 else len(_DEV)]


# --------------------------------------------------------------------------- name before kill
def test_the_raw_click_previews_and_never_arms_directly():
    """The click that has not yet seen a victim list must not arm the kill.

    This is the whole safety property. `_mcIrqPreview()` is what the unarmed
    click calls; the arm happens in its response handler once names exist.
    """
    body = _fn("_mcPaintInterrupt")
    handler = body[body.index("b.addEventListener"):]
    assert "_mcIrqPreview()" in handler
    assert "_mcArm.arm(" not in handler, (
        "arming straight from the click skips the preview, so the confirm "
        "would kill processes the operator was never shown")


def test_the_arm_happens_inside_the_preview_response():
    assert "_mcArm.arm(_MC_IRQ_ID)" in _fn("_mcIrqPreview")


def test_an_empty_victim_set_does_not_arm():
    """Nothing running means nothing to name, so there is nothing to confirm."""
    body = _fn("_mcIrqPreview")
    guard = body[body.index("if (!d.count)"):]
    armed_at = body.find("_mcArm.arm(")
    assert body.index("if (!d.count)") < armed_at, (
        "the zero-victim guard must short-circuit BEFORE the arm")
    assert "return;" in guard.split("_mcArm.arm(")[0]


def test_the_named_victims_are_rendered_while_armed():
    """The list IS the safety property - it must be on screen, not behind a
    disclosure, before the confirm is reachable."""
    body = _fn("_mcPaintInterrupt")
    assert "loop-irq-victims" in body
    assert "_mcIrq.victims.forEach" in body
    assert "armed && _mcIrq.victims.length" in body


def test_the_armed_label_counts_the_real_victims():
    """The count on the button comes from the list, so the two cannot disagree."""
    body = _fn("_mcPaintInterrupt")
    label = body[body.index('"Confirm INTERRUPT'):]
    label = label[:label.index("\n")]
    assert "_mcIrq.victims.length" in label, (
        "a label that does not read the victim array can claim a count the "
        "list below it does not show")


# --------------------------------------------------------------------------- fingerprint lifetime
def test_a_lapsed_arm_discards_the_fingerprint():
    """Same lifecycle as the idempotency key. A fingerprint outliving its arm
    would let a later confirm fire against a list nobody is looking at."""
    body = _fn("_mcPaintInterrupt")
    assert "if (!armed && _mcIrq.fp) _mcIrqForget();" in body


def test_firing_consumes_the_fingerprint():
    body = _fn("_mcIrqFire")
    assert body.index("_mcIrqForget()") < body.index("fetch("), (
        "the fingerprint must be spent before the request goes out, so a "
        "double-fire cannot reuse it")


def test_the_fingerprint_is_read_before_confirm_disarms():
    """MEASURED live: confirm() disarms and notifies SYNCHRONOUSLY.

    That notify repaints, the repaint sees armed === false and calls
    `_mcIrqForget()`, so a fire that reads `_mcIrq.fp` AFTER `confirm()` reads
    null and the server answers 400 "requires 'fingerprint'". The tier failed
    safe - nothing died - but it could never kill anything either, and every
    source-level test here passed while it was broken. The click handler must
    capture the fingerprint before confirm() and pass it in.
    """
    body = _fn("_mcPaintInterrupt")
    handler = body[body.index("b.addEventListener"):]
    read = handler.find("const fp = _mcIrq.fp")
    conf = handler.find("_mcArm.confirm(")
    assert read >= 0, "the click handler must capture the fingerprint itself"
    assert read < conf, (
        "the fingerprint is read AFTER confirm() disarms - the repaint that "
        "confirm triggers will already have cleared it")
    assert "_mcIrqFire(res.key, fp)" in handler, (
        "the captured fingerprint must be handed to the fire, not re-read")


def test_the_fire_never_re_reads_the_fingerprint_from_state():
    body = _fn("_mcIrqFire")
    sig = body[:body.index("{")]
    assert "fp" in sig, "_mcIrqFire must take the fingerprint as a parameter"
    after_sig = body[body.index("{"):]
    assert "= _mcIrq.fp" not in after_sig, (
        "re-reading _mcIrq.fp inside the fire reintroduces the null-by-repaint "
        "bug the parameter exists to avoid")


# --------------------------------------------------------------------------- the request
def test_the_confirm_sends_both_the_fingerprint_and_a_key():
    body = _fn("_mcIrqFire")
    assert '"interrupt"' in body and "fingerprint: fp" in body
    assert "idempotency_key: key" in body


def test_the_preview_sends_no_idempotency_key():
    """A remembered preview would freeze one stale victim list into every arm."""
    body = _fn("_mcIrqPreview")
    assert '"interrupt_preview"' in body
    assert "idempotency_key" not in body


def test_a_changed_victim_set_reports_that_nothing_was_killed():
    """The honest failure. Silence here reads as a successful interrupt."""
    body = _fn("_mcIrqFire")
    assert 'd.refused === "victims_changed"' in body
    assert "Nothing was killed" in body


# --------------------------------------------------------------------------- vocabulary
def test_the_interrupt_button_does_not_share_the_lane_amber():
    """--accent and --warn are the same gold in five of six themes, so an amber
    INTERRUPT would look identical to the lane fire inches above it - two
    buttons with opposite consequences and the same pixels."""
    rule = re.search(r"\.loop-irq-btn:not\(\.loop-btn-armed\)\s*\{([^}]*)\}", _CSS)
    assert rule, "no unarmed .loop-irq-btn rule"
    assert "--bad" in rule.group(1)
    assert "--warn" not in rule.group(1)


def test_the_armed_interrupt_outranks_the_shared_armed_rule():
    """(0,2,0) beats (0,1,0) on specificity, so it survives a source reorder -
    the trap .loop-lane-btn had to solve with :not()."""
    armed = re.search(r"\.loop-irq-btn\.loop-btn-armed\s*\{([^}]*)\}", _CSS)
    assert armed, "no armed .loop-irq-btn rule"
    assert "--bad" in armed.group(1)
    assert "--canvas" in armed.group(1), (
        "ink must be --canvas, not the inherited near-white that measured "
        "1.9:1 in the S4 audit")


def test_the_victim_list_is_not_the_faintest_text_in_the_card():
    """S4 shipped the load-bearing note quieter than the incidental metadata."""
    rule = re.search(r"\.loop-irq-victim\s*\{([^}]*)\}", _CSS)
    assert rule, "no .loop-irq-victim rule"
    assert "--text-faint" not in rule.group(1)
    assert "var(--text)" in rule.group(1)


def test_the_interrupt_css_defines_every_property_it_uses():
    """The S4 lesson: var(--bg) named nothing, failed silently, and fell back to
    inherited near-white on the highest-stakes state in the panel."""
    block = _CSS[_CSS.index(".loop-irq-row"):]
    block = block[:block.index(".mode-pill")]
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", block))
    defined = set()
    for sheet in sorted((ROOT / "web" / "css").rglob("*.css")):
        defined |= set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:",
                                  sheet.read_text(encoding="utf-8"), re.M))
    assert not (used - defined), f"undefined custom properties: {sorted(used - defined)}"


# --------------------------------------------------------------------------- scope
def test_no_module_scope_function_calls_the_local_mk_helper():
    """`mk` is a function-LOCAL const, so at module scope it is a ReferenceError.

    This is the defect the 5-phase UI audit caught and that every source-level
    test in this file missed: the text `mk("ul", ...)` is present and correct
    LOOKING, and only the runtime knows the binding does not reach. It threw
    inside `_mcPaintInterrupt`, the preview's own `.catch` swallowed it as
    "request failed", and the armed button still rendered
    "Confirm INTERRUPT - kill 3" with NO victim list under it - a blind kill
    wearing the safety feature's clothes.

    Generalised past the one call site on purpose. `mk` is defined only at
    dev.js:168 and dev.js:778, both inside enclosing functions, so ANY
    module-scope function reaching for it has the same bug.
    """
    defs = [m for m in re.finditer(r"^const mk = |^function mk\(", _DEV, re.M)]
    assert not defs, (
        "mk is now module-scope - this guard is obsolete, delete it rather "
        "than letting it pass vacuously")

    offenders = []
    for m in re.finditer(r"^function (\w+)\(([^)]*)\)", _DEV, re.M):
        name, params = m.group(1), m.group(2)
        nxt = _DEV.find("\nfunction ", m.end())
        body = _DEV[m.start():nxt if nxt > 0 else len(_DEV)]
        # Strip comments - the fix note deliberately mentions mk by name.
        body = re.sub(r"//[^\n]*", "", body)
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        if not re.search(r"[^.\w]mk\(", body):
            continue
        # Two legitimate ways to reach it, both already used in this file:
        # define your own local (renderLoopStatus, renderSpendGates) or take it
        # as a parameter (_loopLockRow, called as _loopLockRow(mk, ...)).
        if "const mk =" in body or re.match(r"\s*mk\b", params):
            continue
        offenders.append(name)
    assert not offenders, (
        f"module-scope function(s) {offenders} call the function-local `mk` - "
        "guaranteed ReferenceError at runtime; use document.createElement, or "
        "take mk as a parameter the way _loopLockRow does")


# --------------------------------------------------------------------------- mounting
def test_the_interrupt_host_is_painted_after_it_is_mounted():
    """The S4 failure mode: a renderer whose host is created after the paint.

    `_mcPaint()` runs once above this block while `_mcIrq.host` is still null,
    so without a second call the button is absent until the next poll.
    """
    mount = _DEV.index("_mcIrq.host = mk(")
    tail = _DEV[mount:mount + 900]
    assert "_mcPaint();" in tail


def test_the_interrupt_has_its_own_sub_head_not_a_steer_tier():
    """INTERRUPT is a different ACT, not a louder tier of guidance. Sharing the
    STEER heading would present it as one."""
    assert "INTERRUPT - STOPS THE TURN AND KILLS AGENTS" in _DEV
    assert "STEER - GUIDANCE, NEVER AN INTERRUPT" in _DEV
