"""B-OVL-4 (docs/qa/UI_UX_QUEUE_2026-07-21.md): the R40 draft-elo chip must
actually PAINT in the in-game overlay, not just compute.

Measured defect (headless Chromium, /?overlay=1&ui_mock=1&mode=sr): the chip
was mounted inside `.am-pane-head`, which overlay.css hides outright for the
`w-build` widget (BATCH A 2026-07-06 drops the "BUILD" title bar in-game). The
chip therefore reported display:inline-flex / visibility:visible / opacity:1
with a fully rendered `data-de-state` payload, and a getBoundingClientRect() of
0x0 - it computed every tick and painted zero pixels. Its own computed style is
NOT the signal; the hidden ANCESTOR is, which is why the existing
test_active_match_view.py mode-gate case (computed display on the chip itself)
stayed green through the whole defect.

The queue ruled: "Needs a re-parent, not a CSS exception." The pane head is
hidden in the overlay BY DESIGN (data-ink doctrine - the overlay strips pane
chrome), so un-hiding it or carving the chip out of the hide rule is the wrong
fix. The chip is re-parented into a dedicated `.am-pane-chips` row that is a
direct child of `.am-pane-build`, rendered on BOTH surfaces:

  - it stays INSIDE `.am-pane-build` so it travels with the w-build widget when
    the operator drags it (overlay widgets are absolutely positioned per-widget)
  - it stays OUT of `#am-build-body`, whose subtree active_match.js destroys
    (`build.innerHTML = ""`) on every build-signature change
  - it no longer depends on `.am-pane-head` being visible

Drive path mirrors test_overlay_view.py (the `_open_overlay` helper) and
test_active_match_view.py (the dashboard shell). The one harness addition is an
OPT-IN `/api/draft-elo` stub (conftest `DRAFT_ELO_BAD_BAND` /
`DRAFT_ELO_GOOD_BAND` + `mock_server.set_draft_elo`): without it the route
answered `{}`, the chip stayed in its content-free `empty` state, and a
`w > 0 and h > 0` assertion passed against an 18.00x8.00 box - proving the chip
had a BOX, never that it rendered CONTENT. That was vacuous with respect to
this file's own headline, and the audit called it.

Two more defects the re-parent exposed, both fixed here and pinned below:

  MUST-FIX 1 - `.am-pane-chips` only collapsed for `data-de-state="hidden"`,
  but `init` is the SHIPPED DEFAULT (web/index.html) and `empty` is reached on
  any not-ok `/api/draft-elo`. In-game both painted a content-free chip box
  (18.00x8.00 at ovscale 1.0, 23.31x9.97 at 1.333, background
  rgba(20,22,30,0.85)) - NEW litter the re-parent introduced, since before it
  the chip sat under a display:none ancestor. Collapsed OVERLAY-ONLY: the
  dashboard's dimmed `empty` chip is documented, deliberate
  (panels/draft_elo.css) and pinned by test_active_match_draft_elo_mode_gate.

  MUST-FIX 2 - `.de-wr.de-band-red` painted `--signal-bad` rgb(232,64,87) and
  `.de-sample-low` rgb(255,128,128) inside `w-build`, whose `data-ovx-tier` is
  AMBIENT. docs/OVERLAY_DOCTRINE.md rule 4 + section 5 reserve lethal red for
  the single Emergency winner ("NOTHING else paints red"). Re-mapped
  OVERLAY-ONLY to neutral `--ovx-text` ink; the dashboard keeps its reds.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

CHIP = "#am-draft-elo"
BUILD_PANE = "#view-active-match .am-pane-build"

# checkVisibility is the browser's own "would this paint" answer - it walks the
# ancestor chain, which is exactly the axis the defect lived on.
_CHECK_VISIBILITY = (
    "el => el.checkVisibility("
    "{checkOpacity: true, checkVisibilityCSS: true})"
)


# The one lethal-red token (docs/OVERLAY_DOCTRINE.md section 5, #E84057) and the
# low-sample pink, as Chromium serializes them.
LETHAL_RED = "rgb(232, 64, 87)"
SAMPLE_PINK = "rgb(255, 128, 128)"


def _rect(page, selector):
    return page.eval_on_selector(
        selector,
        "el => { const r = el.getBoundingClientRect();"
        " return {w: r.width, h: r.height, x: r.x, y: r.y}; }",
    )


def _rgb(css_color):
    """`rgb(r, g, b)` / `rgba(r, g, b, a)` -> (r, g, b) ints."""
    nums = re.findall(r"[\d.]+", css_color or "")
    assert len(nums) >= 3, f"unparsable colour {css_color!r}"
    return tuple(int(round(float(n))) for n in nums[:3])


def _is_reddish(css_color):
    """True for any hue that reads as red on a HUD: the red channel clearly
    dominates BOTH others. Catches the lethal red (232,64,87) and the pink
    (255,128,128) without banning warm neutrals or the amber band."""
    r, g, b = _rgb(css_color)
    return r >= 150 and r - g >= 60 and r - b >= 60


def _row_display(page):
    return page.eval_on_selector(
        CHIP, "el => getComputedStyle(el.parentElement).display"
    )


# Force one chip state without waiting on a network round-trip. `init` in
# particular is the markup default that a settled page has already left, so a
# live test cannot otherwise observe it.
_SET_STATE = """
([state, html]) => {
  const c = document.querySelector('#am-draft-elo');
  c.dataset.deState = state;
  c.innerHTML = html;
  if (state === 'hidden') { c.style.display = 'none'; }
  return getComputedStyle(c.parentElement).display;
}
"""


def test_overlay_draft_elo_chip_paints(mock_server, pw_browser):
    """OVERLAY shell, POPULATED chip: it renders real backend content, has a
    real box, passes checkVisibility, and is parented outside `.am-pane-head`
    but inside `.am-pane-build`.

    The stub is what makes this non-vacuous. Unstubbed, `/api/draft-elo`
    answered `{}`, `renderDraftElo` took its not-ok branch, and the chip was an
    18.00x8.00 content-free box that satisfied `w > 0 and h > 0` just fine.
    """
    from tests.snapshot_panels.conftest import DRAFT_ELO_BAD_BAND
    from tests.snapshot_panels.test_overlay_view import _open_overlay

    mock_server.set_draft_elo(DRAFT_ELO_BAD_BAND)
    try:
        ctx, page, errors = _open_overlay(pw_browser, mock_server)
        try:
            # The populated render lands on the tick AFTER the fetch resolves
            # (fetchDraftElo caches, the next _renderDraftEloFromCtx paints), so
            # wait on the state stamp rather than a fixed sleep.
            page.wait_for_function(
                "document.querySelector('#am-draft-elo') && "
                "document.querySelector('#am-draft-elo').dataset.deState "
                "=== 'ready'",
                timeout=15_000,
            )

            # The pane head IS hidden in the overlay - that is the design, and
            # the chip must not depend on it. Assert the hide is still in force
            # so this test cannot pass by someone un-hiding the head (the
            # forbidden fix).
            head_display = page.eval_on_selector(
                f"{BUILD_PANE} .am-pane-head",
                "el => getComputedStyle(el).display",
            )
            assert head_display == "none", (
                "the w-build pane head must stay hidden in the overlay "
                f"(data-ink doctrine); got display={head_display}. B-OVL-4 "
                "rules out a CSS exception - re-parent the chip instead."
            )

            # 1. CONTENT, not just a box. Every readout the payload feeds.
            parts = page.eval_on_selector(
                CHIP,
                "el => ({label: (el.querySelector('.de-label')||{}).textContent,"
                " wr: (el.querySelector('.de-wr')||{}).textContent,"
                " score: (el.querySelector('.de-score')||{}).textContent,"
                " sample: (el.querySelector('.de-sample')||{}).textContent})",
            )
            assert parts["label"] == "DRAFT", (
                f"chip lost its DRAFT micro-label: {parts!r}"
            )
            # predicted_wr 0.38 -> "38%", team_score -42.0 -> "-42",
            # sample min_solo 4 / min_pair 1 -> "n=4/1".
            assert parts["wr"] == "38%", f"chip WR readout wrong: {parts!r}"
            assert parts["score"] == "-42", f"chip score readout wrong: {parts!r}"
            assert parts["sample"] == "n=4/1", (
                f"chip sample readout wrong: {parts!r}"
            )

            # 2. The row is NOT collapsed while the chip has content.
            assert _row_display(page) != "none", (
                "the .am-pane-chips row collapsed on a POPULATED chip - the "
                "MUST-FIX 1 collapse must key on empty states only"
            )

            # 3. NOT a descendant of the hidden pane head.
            assert page.eval_on_selector(
                CHIP, "el => el.closest('.am-pane-head') === null"
            ), "draft-elo chip is still parented inside the hidden .am-pane-head"

            # 4. Still inside the build pane, so it rides the dragged widget.
            assert page.eval_on_selector(
                CHIP, "el => el.closest('.am-pane-build') !== null"
            ), (
                "draft-elo chip escaped .am-pane-build (it must ride the "
                "w-build widget)"
            )

            # 5. Not inside the JS-destroyed build body subtree.
            assert page.eval_on_selector(
                CHIP, "el => el.closest('#am-build-body') === null"
            ), (
                "draft-elo chip is inside #am-build-body, which active_match.js "
                "wipes with innerHTML = '' on every build-signature change"
            )

            # 6. A real painted box - and one big enough to be the CONTENT box,
            # not the 18.00x8.00 empty shell the old assertion accepted.
            box = _rect(page, CHIP)
            assert box["w"] >= 80 and box["h"] >= 16, (
                "draft-elo chip box is empty-shell sized in the overlay - a "
                f"populated chip cannot be this small: {box}"
            )

            # 7. The browser's own visibility verdict.
            assert page.eval_on_selector(CHIP, _CHECK_VISIBILITY), (
                "checkVisibility() is false for the draft-elo chip in the overlay"
            )

            # 8. The box lands INSIDE the w-build widget box (it rides it).
            wb = _rect(page, BUILD_PANE)
            assert wb["w"] > 0 and wb["h"] > 0, f"w-build widget has no box: {wb}"
            assert (
                box["x"] >= wb["x"] - 1
                and box["y"] >= wb["y"] - 1
                and box["x"] + box["w"] <= wb["x"] + wb["w"] + 1
                and box["y"] + box["h"] <= wb["y"] + wb["h"] + 1
            ), f"draft-elo chip box {box} is outside the w-build widget box {wb}"

            # 9. No horizontal overflow introduced in the w-build widget.
            for sel in (BUILD_PANE, f"{BUILD_PANE} .am-pane-chips"):
                over = page.eval_on_selector(
                    sel, "el => el.scrollWidth - el.clientWidth"
                )
                assert over <= 1, (
                    f"{sel} overflows horizontally by {over}px in the overlay"
                )
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors: {errors[:3]}"
    finally:
        mock_server.set_draft_elo(None)


def test_overlay_empty_chip_collapses_the_row(mock_server, pw_browser):
    """MUST-FIX 1: in the overlay the `.am-pane-chips` row must collapse to
    nothing for EVERY content-free chip state - `init` (the shipped default in
    web/index.html), `empty` (any not-ok /api/draft-elo) and `hidden` (the
    Arena mode gate) - not just `hidden`.

    Before the B-OVL-4 re-parent the chip sat under a display:none ancestor and
    painted nothing in-game. After it, `init`/`empty` painted a content-free
    chip box - measured 18.00x8.00 at ovscale 1.0 and 23.31x9.97 at 1.333,
    background rgba(20,22,30,0.85). That is new litter on the in-game HUD.
    """
    from tests.snapshot_panels.test_overlay_view import _open_overlay

    # No stub armed -> /api/draft-elo answers not-ok -> the chip settles empty,
    # which is the state a real not-ok backend produces.
    mock_server.set_draft_elo(None)
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.wait_for_function(
            "document.querySelector('#am-draft-elo') && "
            "document.querySelector('#am-draft-elo').dataset.deState "
            "=== 'empty'",
            timeout=15_000,
        )

        # The naturally-reached empty state collapses the row...
        assert _row_display(page) == "none", (
            "the .am-pane-chips row still paints for an EMPTY chip in the "
            "overlay - a content-free chip box is litter on the in-game HUD"
        )
        # ...and therefore paints no box at all.
        box = _rect(page, CHIP)
        assert box["w"] == 0 and box["h"] == 0, (
            f"empty draft-elo chip still paints {box} in the overlay"
        )
        assert not page.eval_on_selector(CHIP, _CHECK_VISIBILITY), (
            "checkVisibility() is true for an empty overlay draft-elo chip"
        )

        # `init` is the markup default a settled page has already left, so drive
        # it directly. Same for `hidden` (the pre-existing Arena gate, which
        # must not regress).
        for state, html in (
            ("init", ""),
            ("empty", '<div class="de-empty"></div>'),
            ("hidden", ""),
        ):
            disp = page.evaluate(_SET_STATE, [state, html])
            assert disp == "none", (
                f"overlay .am-pane-chips does not collapse for a "
                f"data-de-state={state!r} chip (display={disp})"
            )

        # A populated chip must still open the row (the collapse is not a
        # blanket hide of the row in the overlay).
        disp = page.evaluate(
            _SET_STATE,
            ["ready",
             '<span class="de-label">DRAFT</span>'
             '<span class="de-wr de-band-green">63%</span>'],
        )
        assert disp != "none", (
            "overlay .am-pane-chips collapsed a READY chip - the collapse must "
            f"key on the content-free states only (display={disp})"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_dashboard_empty_chip_keeps_the_row(mock_server, pw_browser):
    """The MUST-FIX 1 collapse is OVERLAY-SCOPED. On the dashboard the dimmed
    `empty` chip is deliberate and documented: panels/draft_elo.css carries a
    `[data-de-state="empty"]` rule whose comment says the chip "stays VISIBLE -
    it is a 5v5-only surface that must be present (enabled) in SR/ARAM and
    hidden only in Arena (the mode gate)", and
    test_active_match_view.test_active_match_draft_elo_mode_gate pins exactly
    that. Collapsing the dashboard row would gut both.
    """
    from tests.snapshot_panels.test_active_match_view import _open_active_match

    mock_server.set_draft_elo(None)
    ctx, page, errors = _open_active_match(pw_browser, mock_server, "sr")
    try:
        page.wait_for_selector(CHIP, state="attached", timeout=10_000)
        for state, html in (
            ("init", ""),
            ("empty", '<div class="de-empty"></div>'),
        ):
            disp = page.evaluate(_SET_STATE, [state, html])
            assert disp != "none", (
                f"the dashboard .am-pane-chips row collapsed for "
                f"data-de-state={state!r} - the MUST-FIX 1 collapse must not "
                "reach the dashboard shell"
            )
        # `hidden` is the pre-existing mode gate and DOES collapse on both
        # surfaces (Arena); that behaviour is unchanged.
        assert page.evaluate(_SET_STATE, ["hidden", ""]) == "none", (
            "the pre-existing data-de-state='hidden' collapse regressed on the "
            "dashboard"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_overlay_bad_band_paints_no_lethal_red(mock_server, pw_browser):
    """MUST-FIX 2: the chip is an AMBIENT widget (w-build carries
    data-ovx-tier="ambient"), so it must not paint the reserved lethal red.

    docs/OVERLAY_DOCTRINE.md rule 4: "at any instant exactly ONE element is the
    ONLY red / ONLY moving / ONLY large thing on screen... Five reds = nothing
    pops." Section 5: "lethal red is RESERVED for the current Emergency
    winner... NOTHING else paints red."

    Measured before the fix: `.de-wr.de-band-red` -> rgb(232, 64, 87) (the
    `--ovx-red` token itself) at 13px/700, and `.de-sample-low` ->
    rgb(255, 128, 128). Both inside `w-build`.
    """
    from tests.snapshot_panels.conftest import (
        DRAFT_ELO_BAD_BAND,
        DRAFT_ELO_GOOD_BAND,
    )
    from tests.snapshot_panels.test_overlay_view import _open_overlay

    mock_server.set_draft_elo(DRAFT_ELO_BAD_BAND)
    try:
        ctx, page, errors = _open_overlay(pw_browser, mock_server)
        try:
            page.wait_for_function(
                "document.querySelector('#am-draft-elo') && "
                "document.querySelector('#am-draft-elo').dataset.deBand "
                "=== 'red'",
                timeout=15_000,
            )
            wr = page.eval_on_selector(
                f"{CHIP} .de-wr", "el => getComputedStyle(el).color"
            )
            assert wr != LETHAL_RED, (
                "the overlay draft-elo chip paints the RESERVED lethal red "
                f"{LETHAL_RED} on a bad band - doctrine rule 4 allows exactly "
                "one red on screen and it belongs to the Emergency winner"
            )
            assert not _is_reddish(wr), (
                f"the overlay bad band still reads as red ({wr})"
            )

            sample = page.eval_on_selector(
                f"{CHIP} .de-sample", "el => getComputedStyle(el).color"
            )
            assert sample != SAMPLE_PINK, (
                f"the overlay low-sample pill paints {SAMPLE_PINK}"
            )
            assert not _is_reddish(sample), (
                f"the overlay low-sample pill still reads as red ({sample})"
            )

            # The information must survive the re-map: a bad band still has to
            # look different from a good one. Re-render the SAME chip green and
            # then amber and require three distinct colours.
            green = page.evaluate(
                """() => {
                  const c = document.querySelector('#am-draft-elo');
                  c.innerHTML = '<span class="de-wr de-band-green">63%</span>';
                  return getComputedStyle(c.querySelector('.de-wr')).color;
                }"""
            )
            assert green != wr, (
                "bad and good bands render the SAME colour in the overlay "
                f"({wr}) - the re-map dropped the category distinction"
            )
            amber = page.evaluate(
                """() => {
                  const c = document.querySelector('#am-draft-elo');
                  c.innerHTML = '<span class="de-wr de-band-amber">50%</span>';
                  return getComputedStyle(c.querySelector('.de-wr')).color;
                }"""
            )
            assert amber not in (wr, green), (
                "the three WR bands are not three colours in the overlay: "
                f"bad={wr} amber={amber} green={green}"
            )
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors: {errors[:3]}"

        # Control: the GOOD band was measured fine (8.65:1) and must be left
        # alone - it still paints the --ovx-good green token in the overlay.
        mock_server.set_draft_elo(DRAFT_ELO_GOOD_BAND)
        ctx, page, errors = _open_overlay(pw_browser, mock_server)
        try:
            page.wait_for_function(
                "document.querySelector('#am-draft-elo') && "
                "document.querySelector('#am-draft-elo').dataset.deBand "
                "=== 'green'",
                timeout=15_000,
            )
            good = page.eval_on_selector(
                f"{CHIP} .de-wr", "el => getComputedStyle(el).color"
            )
            assert _rgb(good) == (55, 208, 138), (
                f"the overlay good band is no longer --ovx-good #37D08A: {good}"
            )
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors: {errors[:3]}"
    finally:
        mock_server.set_draft_elo(None)


def test_dashboard_bad_band_keeps_its_red(mock_server, pw_browser):
    """The MUST-FIX 2 re-map is OVERLAY-SCOPED. The dashboard is not a HUD over
    a live game, has no Emergency tier competing for the one red, and keeps the
    `--signal-bad` band + low-sample pink it has always used."""
    from tests.snapshot_panels.conftest import DRAFT_ELO_BAD_BAND
    from tests.snapshot_panels.test_active_match_view import _open_active_match

    mock_server.set_draft_elo(DRAFT_ELO_BAD_BAND)
    try:
        ctx, page, errors = _open_active_match(pw_browser, mock_server, "sr")
        try:
            page.wait_for_function(
                "document.querySelector('#am-draft-elo') && "
                "document.querySelector('#am-draft-elo').dataset.deBand "
                "=== 'red'",
                timeout=15_000,
            )
            wr = page.eval_on_selector(
                f"{CHIP} .de-wr", "el => getComputedStyle(el).color"
            )
            assert wr == LETHAL_RED, (
                f"the dashboard bad band lost its --signal-bad red: {wr}"
            )
            sample = page.eval_on_selector(
                f"{CHIP} .de-sample", "el => getComputedStyle(el).color"
            )
            assert sample == SAMPLE_PINK, (
                f"the dashboard low-sample pill lost its pink: {sample}"
            )
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors: {errors[:3]}"
    finally:
        mock_server.set_draft_elo(None)


def test_dashboard_draft_elo_chip_still_paints(mock_server, pw_browser):
    """DASHBOARD shell (same web/index.html): the re-parent must not regress the
    surface where the chip already worked. The pane head keeps its BUILD label,
    and the chip renders the same populated content it does in the overlay."""
    from tests.snapshot_panels.conftest import DRAFT_ELO_BAD_BAND
    from tests.snapshot_panels.test_active_match_view import _open_active_match

    mock_server.set_draft_elo(DRAFT_ELO_BAD_BAND)
    try:
        ctx, page, errors = _open_active_match(pw_browser, mock_server, "sr")
        try:
            page.wait_for_function(
                "document.querySelector('#am-draft-elo') && "
                "document.querySelector('#am-draft-elo').dataset.deState "
                "=== 'ready'",
                timeout=15_000,
            )

            # The dashboard KEEPS the pane head + its literal BUILD label.
            head_text = page.eval_on_selector(
                f"{BUILD_PANE} .am-pane-head", "el => el.textContent.trim()"
            )
            assert head_text.startswith("BUILD"), (
                f"dashboard BUILD pane head lost its label: {head_text!r}"
            )
            assert page.eval_on_selector(
                f"{BUILD_PANE} .am-pane-head",
                "el => getComputedStyle(el).display",
            ) != "none", "dashboard BUILD pane head must stay visible"

            parts = page.eval_on_selector(
                CHIP,
                "el => ({label: (el.querySelector('.de-label')||{}).textContent,"
                " wr: (el.querySelector('.de-wr')||{}).textContent,"
                " sample: (el.querySelector('.de-sample')||{}).textContent})",
            )
            assert (
                parts["label"] == "DRAFT"
                and parts["wr"] == "38%"
                and parts["sample"] == "n=4/1"
            ), f"dashboard chip did not render the payload: {parts!r}"

            box = _rect(page, CHIP)
            assert box["w"] >= 80 and box["h"] >= 16, (
                f"draft-elo chip box is empty-shell sized on the dashboard: {box}"
            )
            assert page.eval_on_selector(CHIP, _CHECK_VISIBILITY), (
                "checkVisibility() is false for the draft-elo chip on the dashboard"
            )
            assert page.eval_on_selector(
                CHIP, "el => el.closest('.am-pane-build') !== null"
            ), "draft-elo chip escaped .am-pane-build on the dashboard"
            assert page.eval_on_selector(
                CHIP, "el => el.closest('#am-build-body') === null"
            ), "draft-elo chip must stay out of the JS-wiped #am-build-body"

            over = page.eval_on_selector(
                BUILD_PANE, "el => el.scrollWidth - el.clientWidth"
            )
            assert over <= 1, (
                f"dashboard BUILD pane overflows horizontally by {over}px"
            )
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors: {errors[:3]}"
    finally:
        mock_server.set_draft_elo(None)
