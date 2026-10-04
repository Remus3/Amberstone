"""
tests/snapshot_panels/test_overlay_root_type_tokens_rm139.py
RM-139 - the four overlay sub-floor type tokens (--fs-ov-chip / -sigil /
-head / -call) were declared on body[data-shell="overlay"], but
lib/overlay_tooltip.js and lib/overlay_item_radial.js mount on
document.documentElement - SIBLINGS of <body> - and custom properties
inherit downward only, so their var(--fs-ov-chip, 13px) ALWAYS took the
fallback and could never track a re-tuned overlay scale.

Route chosen (b): the four TYPE tokens now live on
`:root:has(> body[data-shell="overlay"])` in web/css/overlay.css (palette
stays body-scoped; the dashboard :root keeps its >=16px floor because the
:has never matches there). Proved by COMPUTED STYLE, not grep: a probe
mounted exactly where the widgets mount resolves each token to its value,
not to a sentinel fallback, and tracks a re-tune.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

_TOKENS = {"--fs-ov-chip": 13.0, "--fs-ov-sigil": 12.0,
           "--fs-ov-head": 11.0, "--fs-ov-call": 14.0}

_PROBE = """(tok) => {
  const el = document.createElement('div');
  el.textContent = 'x';
  el.style.cssText = 'font-size:var(' + tok + ',77px)';
  document.documentElement.appendChild(el);   // where the widgets mount
  const px = parseFloat(getComputedStyle(el).fontSize);
  el.remove();
  return px;
}"""


def _open(mock_server, pw_browser, overlay):
    from tests.snapshot_panels.conftest import _WS_STUB
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    q = "&overlay=1" if overlay else ""
    page.goto(mock_server.url + "/?ui_mock=1&mode=sr" + q,
              wait_until="domcontentloaded", timeout=15_000)
    if overlay:
        page.wait_for_function(
            "document.body && document.body.dataset.shell === 'overlay'",
            timeout=10_000)
    return ctx, page


def test_tokens_resolve_on_document_element_in_overlay(mock_server, pw_browser):
    ctx, page = _open(mock_server, pw_browser, overlay=True)
    try:
        for tok, want in _TOKENS.items():
            got = page.evaluate(_PROBE, tok)
            assert got == want, f"{tok} on <html> child resolved {got}px, want {want}"
        # Re-tuning the overlay scale must now reach a root-mounted widget.
        page.add_style_tag(content=(
            ':root:has(> body[data-shell="overlay"]) { --fs-ov-chip: 19px; }'))
        assert page.evaluate(_PROBE, "--fs-ov-chip") == 19.0
        # And body-descendant widgets still inherit the same value.
        body_px = page.evaluate("""() => {
          const el = document.createElement('div');
          el.style.cssText = 'font-size:var(--fs-ov-chip,77px)';
          document.body.appendChild(el);
          const px = parseFloat(getComputedStyle(el).fontSize);
          el.remove(); return px; }""")
        assert body_px == 19.0
    finally:
        page.close()
        ctx.close()


def test_dashboard_root_keeps_floor(mock_server, pw_browser):
    ctx, page = _open(mock_server, pw_browser, overlay=False)
    try:
        val = page.evaluate(
            "getComputedStyle(document.documentElement)"
            ".getPropertyValue('--fs-ov-chip').trim()")
        assert val == "", f"sub-floor token leaked onto the dashboard: {val!r}"
    finally:
        page.close()
        ctx.close()


def test_widgets_still_mount_where_the_token_scope_reaches():
    """If a widget moves its mount or the tokens move back to body-only, the
    computed-style test above is the proof; this pins the premise cheaply."""
    for rel in ("web/js/lib/overlay_tooltip.js",
                "web/js/lib/overlay_item_radial.js"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "var(--fs-ov-chip" in src, rel
        assert "document.documentElement.appendChild" in src, rel
    css = (ROOT / "web/css/overlay.css").read_text(encoding="utf-8")
    assert ':root:has(> body[data-shell="overlay"])' in css
