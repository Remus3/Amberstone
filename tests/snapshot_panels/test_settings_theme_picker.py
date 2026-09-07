"""
tests/snapshot_panels/test_settings_theme_picker.py
Settings THEME PICKER coverage (DS2 theme selector, shipped 3e39facf).

Contract under test:

  * a <select id="set-theme"> mounted inside the Settings view, in the
    DISPLAY settings-card, carrying exactly six options in order:
    hextech, terminal, ember, bloodmoon, moonlit, arcane.
  * persistence key "rc-theme" in localStorage (kebab-case, matching the
    existing rc-view-manual / rc-home-mode-tab / rc-ui-mock convention).
  * boot resolution order:
        ?theme=<whitelisted>  WINS (session only - must NOT write storage)
        else localStorage "rc-theme" (whitelisted)
        else the operator default (see DEFAULT_THEME below)
  * "hextech" stamps NO attribute at all (base.css :root owns the gold
    Hextech palette, so document.documentElement.getAttribute("data-theme")
    must read null). Every other theme stamps data-theme="<name>", which is
    what web/css/themes.css keys its :root[data-theme="..."] blocks on.
  * changing the select applies live - no page navigation - and writes
    localStorage.

web/js/lib/theme.js is the single source of truth; the inline pre-paint
guard in web/index.html hand-copies the whitelist + default because it runs
before the module graph loads, so a static drift test pins the two copies.

Harness: the same headless mock-server + Playwright rig as
test_settings_view.py (session-scoped mock_server + pw_browser fixtures from
conftest.py, _WS_STUB init script, empty SSE state so the router lands on
the sticky #settings hash). localStorage is seeded with page.add_init_script
BEFORE page.goto so main.js boot sees it. Every browser test asserts an
empty "pageerror" list, mirroring test_settings_view.py.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
THEMES_CSS = ROOT / "web" / "css" / "themes.css"

# Option order is part of the contract - hextech first (it is the base
# palette / no-attribute case). Order is asserted, not the default.
EXPECTED_THEMES = [
    "hextech",
    "terminal",
    "ember",
    "bloodmoon",
    "moonlit",
    "arcane",
]

STORAGE_KEY = "rc-theme"

# Operator default when nothing else resolves. Must track DEFAULT_THEME in
# web/js/lib/theme.js and the inline FOUC guard in web/index.html; the drift
# test at the bottom of this file pins all three together.
DEFAULT_THEME = "arcane"


def _seed_script(items: dict) -> str:
    """Init script that primes localStorage before any page script runs.

    Wrapped in try/catch because an init script also evaluates on frames
    whose origin may deny storage; a throw there would surface as a
    pageerror and poison the no-JS-errors assertion.
    """
    lines = [
        f"  try {{ window.localStorage.setItem("
        f"{json.dumps(str(k))}, {json.dumps(str(v))}); }} catch (e) {{}}"
        for k, v in items.items()
    ]
    return "(function () {\n" + "\n".join(lines) + "\n})();"


def _open_settings(pw_browser, mock_server, query: str = "", storage: dict = None):
    """Boot the dashboard on the Settings view.

    Mirrors test_settings_view.py._open_settings, plus two knobs this slice
    needs: extra query string (for ?theme=) and a localStorage seed applied
    before navigation.
    """
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home" (mode
    # client / no liveclient); #settings is a sticky non-game-state hash,
    # so the settings view wins the router.
    mock_server._store["data"] = {}

    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    if storage:
        page.add_init_script(_seed_script(storage))
    errors: list = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    url = mock_server.url + "/?ui_mock=1" + query + "#settings"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "document.body.dataset.view === 'settings' && "
        "document.querySelector('#view-settings .settings-card') !== null",
        timeout=10_000,
    )
    return ctx, page, errors


def _stamped_theme(page):
    """Value of <html data-theme> as the DOM reports it (None when absent)."""
    return page.evaluate(
        "document.documentElement.getAttribute('data-theme')"
    )


def test_theme_select_mounted_with_six_options(mock_server, pw_browser):
    """#set-theme lives inside the Settings view and offers exactly the six
    whitelisted themes, hextech first."""
    ctx, page, errors = _open_settings(pw_browser, mock_server)
    try:
        sel = page.locator("#view-settings #set-theme")
        assert sel.count() == 1, (
            "expected exactly one #set-theme select inside #view-settings, "
            f"found {sel.count()}"
        )
        values = page.eval_on_selector_all(
            "#view-settings #set-theme option",
            "els => els.map(e => e.value)",
        )
        assert values == EXPECTED_THEMES, (
            f"#set-theme option values {values!r} != {EXPECTED_THEMES!r}"
        )
        # The picker belongs to the DISPLAY card, not some other card.
        head = page.eval_on_selector(
            "#view-settings .settings-card:has(#set-theme) .settings-card-head",
            "el => el.textContent.trim()",
        )
        assert head == "DISPLAY", (
            f"#set-theme mounted under card {head!r}, expected 'DISPLAY'"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [theme select mounted]: {errors[:3]}"


def test_theme_defaults_to_operator_default(mock_server, pw_browser):
    """No ?theme=, no stored preference -> the operator default."""
    ctx, page, errors = _open_settings(pw_browser, mock_server)
    try:
        stamped = _stamped_theme(page)
        assert stamped == DEFAULT_THEME, (
            f"default boot stamped data-theme={stamped!r}, "
            f"expected {DEFAULT_THEME!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [theme default]: {errors[:3]}"


def test_stored_theme_applies_and_selects(mock_server, pw_browser):
    """A stored preference stamps and preselects that theme.

    The seeded value MUST NOT be DEFAULT_THEME, or this passes even when
    the storage read is broken and boot merely falls through to the
    default."""
    stored = next(t for t in EXPECTED_THEMES
                  if t not in (DEFAULT_THEME, "hextech"))
    ctx, page, errors = _open_settings(
        pw_browser, mock_server, storage={STORAGE_KEY: stored}
    )
    try:
        stamped = _stamped_theme(page)
        assert stamped == stored, (
            f"stored rc-theme={stored!r} stamped data-theme={stamped!r}"
        )
        sel = page.locator("#view-settings #set-theme")
        assert sel.count() == 1, "no #set-theme select to reflect stored theme"
        assert sel.input_value() == stored, (
            f"#set-theme value {sel.input_value()!r} != {stored!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [theme stored]: {errors[:3]}"


def test_stored_hextech_stamps_no_attribute(mock_server, pw_browser):
    """hextech is the BASE palette: it must stamp no data-theme at all, so
    base.css :root wins instead of a themes.css override block."""
    ctx, page, errors = _open_settings(
        pw_browser, mock_server, storage={STORAGE_KEY: "hextech"}
    )
    try:
        stamped = _stamped_theme(page)
        assert stamped is None, (
            "hextech must leave <html> unstamped, got "
            f"data-theme={stamped!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [theme hextech]: {errors[:3]}"


def test_query_param_wins_and_does_not_persist(mock_server, pw_browser):
    """?theme= is a session override: it beats the stored preference AND
    must not overwrite it."""
    ctx, page, errors = _open_settings(
        pw_browser,
        mock_server,
        query="&theme=moonlit",
        storage={STORAGE_KEY: "ember"},
    )
    try:
        stamped = _stamped_theme(page)
        assert stamped == "moonlit", (
            f"?theme=moonlit stamped data-theme={stamped!r}, expected 'moonlit'"
        )
        stored = page.evaluate(
            f"window.localStorage.getItem({json.dumps(STORAGE_KEY)})"
        )
        assert stored == "ember", (
            "query-param theme must not persist - localStorage rc-theme is "
            f"{stored!r}, expected the untouched 'ember'"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [theme query wins]: {errors[:3]}"


def test_selecting_theme_applies_live_and_persists(mock_server, pw_browser):
    """Changing the select restamps <html>, writes rc-theme, and does NOT
    navigate (no reload - the swap is pure CSS-variable rebinding)."""
    ctx, page, errors = _open_settings(pw_browser, mock_server)
    try:
        sel = page.locator("#view-settings #set-theme")
        assert sel.count() == 1, "no #set-theme select to change"

        # Navigation sentinel: a reload wipes this window property.
        page.evaluate("window.__rcThemeNavSentinel = 'alive'")

        sel.select_option("bloodmoon")
        page.wait_for_function(
            "document.documentElement.getAttribute('data-theme') === 'bloodmoon'",
            timeout=5_000,
        )

        stamped = _stamped_theme(page)
        assert stamped == "bloodmoon", (
            f"select_option('bloodmoon') stamped data-theme={stamped!r}"
        )
        stored = page.evaluate(
            f"window.localStorage.getItem({json.dumps(STORAGE_KEY)})"
        )
        assert stored == "bloodmoon", (
            f"localStorage rc-theme {stored!r} != 'bloodmoon' after select"
        )
        sentinel = page.evaluate("window.__rcThemeNavSentinel")
        assert sentinel == "alive", (
            "theme change navigated/reloaded the page (nav sentinel lost) - "
            "the swap must apply live"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [theme live apply]: {errors[:3]}"


def test_garbage_stored_theme_falls_back_to_default(mock_server, pw_browser):
    """A non-whitelisted stored value is rejected (no attribute injection)
    and boot falls back to the operator default."""
    ctx, page, errors = _open_settings(
        pw_browser, mock_server, storage={STORAGE_KEY: "../evil"}
    )
    try:
        stamped = _stamped_theme(page)
        assert stamped == DEFAULT_THEME, (
            f"garbage rc-theme stamped data-theme={stamped!r}, expected "
            f"the {DEFAULT_THEME!r} fallback"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [theme garbage]: {errors[:3]}"


def test_themes_css_declares_every_non_hextech_theme():
    """Static contract (no browser): themes.css must carry a
    :root[data-theme="<name>"] block for every theme EXCEPT hextech, which
    is the unstamped base palette and must have no block."""
    css = THEMES_CSS.read_text(encoding="utf-8")
    missing = [
        name
        for name in EXPECTED_THEMES
        if name != "hextech" and f':root[data-theme="{name}"]' not in css
    ]
    assert not missing, (
        f"themes.css has no :root[data-theme=...] block for: {missing}"
    )
    assert ':root[data-theme="hextech"]' not in css, (
        "themes.css declares a hextech block - hextech is the unstamped "
        "base palette owned by base.css :root"
    )


def test_fouc_guard_whitelist_matches_theme_module():
    """Static drift guard: the inline pre-paint <head> script in index.html
    hand-copies the THEMES whitelist + the DEFAULT_THEME + the storage key
    from web/js/lib/theme.js (it must run before the module graph loads, so
    it cannot import them). Both copies must stay identical."""
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    mod = (ROOT / "web" / "js" / "lib" / "theme.js").read_text(encoding="utf-8")

    names = re.compile(r'"([a-z]+)"')
    inline = names.findall(
        re.search(r"var T = \[(.*?)\]", html, re.S).group(1)
    )
    canon = names.findall(
        re.search(r"export const THEMES = \[(.*?)\]", mod, re.S).group(1)
    )
    assert inline == canon == EXPECTED_THEMES, (
        f"FOUC guard whitelist {inline} drifted from theme.js {canon} "
        f"(expected {EXPECTED_THEMES})"
    )
    assert 'localStorage.getItem("rc-theme")' in html, (
        "FOUC guard reads a storage key other than rc-theme"
    )
    assert f't = "{DEFAULT_THEME}"' in html, (
        f"FOUC guard default drifted from DEFAULT_THEME {DEFAULT_THEME!r}"
    )
    assert f'export const DEFAULT_THEME = "{DEFAULT_THEME}";' in mod, (
        f"theme.js DEFAULT_THEME drifted from {DEFAULT_THEME!r}"
    )


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F in this
    test file."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s) in {__file__}: {offenders[:5]}"
