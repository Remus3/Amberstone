"""Overlay widget fixed-size + on-screen-fit, proven in a real overlay render
(operator 2026-06-29). The unit sibling tests/test_overlay_widget_fixed_size.py
grep-locks the CSS/JS; this proves the rendered result: the opacity slider is
on-screen + clickable, no widget spills past the 1080 viewport bottom, and the
widget box width is fixed.
"""
VH = 1080
VW = 1920


def test_overlay_slider_on_screen_and_widgets_capped(mock_server, pw_browser):
    from tests.snapshot_panels.test_overlay_view import _open_overlay

    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.wait_for_selector("#ovset-opacity", timeout=10_000)

        # 1. The opacity slider sits fully ON-SCREEN (the off-screen-at-y1066 bug).
        sb = page.locator("#ovset-opacity").bounding_box()
        assert sb is not None, "opacity slider has no box"
        assert sb["y"] + sb["height"] <= VH, (
            f"opacity slider runs off the viewport bottom: y={sb['y']} h={sb['height']}"
        )
        assert sb["width"] >= 40, f"slider too narrow to click: {sb['width']}"

        # 2. The settings + build widgets are bounded to the screen (no off-screen
        #    spill); each fits from its anchor to the viewport bottom, and a real
        #    max-height is set (the --ovx-maxh cap), so content past the bound is
        #    clipped to a fixed size instead of running off-screen.
        for sel in ("#am-pane-ovds", "#view-active-match .am-pane-build"):
            box = page.locator(sel).bounding_box()
            assert box is not None, f"{sel} has no box"
            assert box["y"] + box["height"] <= VH + 1, (
                f"{sel} spills past the viewport bottom: "
                f"y={box['y']} h={box['height']} (bottom={box['y'] + box['height']})"
            )
            mh = page.eval_on_selector(sel, "el => getComputedStyle(el).maxHeight")
            assert mh not in ("none", ""), f"{sel} has no max-height cap: {mh}"

        # 3. Fixed width (not content-driven): the call widget is its fixed --ovx-w.
        cw = page.eval_on_selector(
            "#view-active-match .am-pane-call", "el => getComputedStyle(el).width")
        assert cw == "210px", f"call widget width not fixed at 210px: {cw}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
