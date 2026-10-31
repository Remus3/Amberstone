"""
tests/snapshot_panels/test_hidden_display_contract.py
RM-1206 (s144 uiux): a hidden element must not render. An author rule that
sets `display` on an element beats the UA `[hidden] { display: none }` rule,
so the element keeps painting while it is marked hidden. This is the lane
doc's STRUCTURE trap ("a bare display beats [hidden]", LEDGER 765; RM-1205
found one instance on #spend-gates-list).

Measured in headless Chromium under /?ui_mock=1, before the fix: every
champ-select `.csv-sugg-section` without its own `[hidden]` rule kept
`display: flex` while hidden (web/css/panels/champ_select_view.css). There
are three of them: #csv-sugg-counter-picks, #csv-team-analysis and
#csv-sugg-team-damage. The effects:
- at draft open, before any pick, champ_select.js hides #csv-team-analysis.
  Its static TEAM ANALYSIS head (role=button, tabindex=0, verdict "-",
  caret "[+]") still painted, took keyboard focus, and its click toggled a
  body with nothing in it;
- in ARAM / Arena, #csv-sugg-counter-picks is hidden and emptied (you can't
  counter-draft there), but it stayed a 0-height flex item. That added a
  phantom 10px gap to the suggestions card body.
The sweep found one more: `.home-rank-wl { display: flex }`
(web/css/panels/home.css) kept the hidden no-data ALL-tab W/L strip as a
0-height row with its margin-top, though its own CSS note says that state
"collapses via [hidden]".

The sweep below pins the contract for every element the page marks hidden,
across the ?ui_mock=1 views. Two exceptions are deliberate and named in
_EXCEPTIONS, each with the rule that makes it so. Anything else that keeps
a display while hidden is a regression.
"""
import json
import re
from pathlib import Path

from tests.snapshot_panels.conftest import _WS_STUB

VP = {"width": 1920, "height": 920}
_INDEX = Path(__file__).resolve().parents[2] / "web" / "index.html"
_CS_SR = Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock" / "champ_select_sr.json"

# Deliberate hidden-but-displayed elements. Matched by id or by class.
_EXCEPTIONS = {
    # header.css: body[data-view="<v>"] #view-<v> shows the active view
    # section by CSS route; .view-section[hidden] hides the rest. Only the
    # ACTIVE section (#view-<data-view>) is exempt in the sweep.
    "class:view-section": "view routing by body[data-view] (header.css)",
    # home.css .home-hero-headline[hidden]: the no-reflow contract keeps
    # the line box (visibility: hidden) so hero heights match across tabs.
    "id:home-hero-headline": "no-reflow line box, visibility:hidden (home.css)",
}

# (mode, hash) pairs swept. Arena / ARAM champ select carry the hidden
# counter-picks section; SR champ select carries the TEAM ANALYSIS cluster.
_VIEWS = [
    ("sr", ""), ("sr", "champ-select"), ("aram", "champ-select"),
    ("arena", "champ-select"), ("sr", "active-match"), ("tft", "active-match"),
    ("sr", "settings"), ("sr", "lobby"), ("sr", "session"), ("sr", "history"),
    ("sr", "build-insights"), ("sr", "last-match"),
]

_SWEEP = """
([staticIds, exClasses, exIds]) => {
  // A view-section is exempt only while it is the ACTIVE route; every
  // inactive one must still collapse through .view-section[hidden].
  const active = 'view-' + (document.body.dataset.view || '');
  const exempt = (el) => exIds.includes(el.id)
    || (exClasses.some((c) => el.classList.contains(c)) && el.id === active);
  const bad = [];
  const seen = new Set();
  const check = (el, forced) => {
    if (!el || seen.has(el) || exempt(el)) return;
    seen.add(el);
    const was = el.hidden;
    if (!was) el.hidden = true;
    const d = getComputedStyle(el).display;
    if (!was) el.hidden = false;
    if (d !== 'none') {
      bad.push({id: el.id || null, cls: el.getAttribute('class') || '',
                display: d, forced});
    }
  };
  for (const el of document.querySelectorAll('body [hidden]')) check(el, false);
  for (const id of staticIds) check(document.getElementById(id), true);
  return {bad, checked: seen.size};
}
"""


def _static_hidden_ids():
    """Ids that web/index.html declares with a `hidden` attribute."""
    html = _INDEX.read_text(encoding="utf-8")
    ids = []
    for tag in re.findall(r"<[a-zA-Z][^<>]*>", html):
        if re.search(r"\shidden(\s|>|/|=)", tag):
            m = re.search(r'\sid="([^"]+)"', tag)
            if m:
                ids.append(m.group(1))
    return ids


def _open(pw_browser, mock_server, mode, view, cs_override=None):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True, viewport=VP)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    if cs_override is not None:
        page.route(
            "**/data/ui_mock/champ_select_sr.json*",
            lambda route: route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(cs_override)),
        )
    page.goto(
        mock_server.url + f"/?ui_mock=1&mode={mode}#{view}",
        wait_until="domcontentloaded", timeout=15_000,
    )
    want = view or "home"
    page.wait_for_function(
        f"document.body.dataset.view === {json.dumps(want)}", timeout=10_000)
    if view == "champ-select":
        page.wait_for_selector(
            "#view-champ-select .csv-card-mypick .csv-card-body *", timeout=10_000)
    page.wait_for_timeout(800)
    return ctx, page, errors


def _close(ctx, page):
    try:
        page.close()
    finally:
        ctx.close()


_PROBE = """
(sel) => {
  const el = document.querySelector(sel);
  const r = el.getBoundingClientRect();
  return {hidden: el.hidden, display: getComputedStyle(el).display,
          rects: el.getClientRects().length, h: r.height};
}
"""


def _draft_open_fixture():
    """The SR champ-select fixture at draft open: no ally or enemy has a
    champion yet (championId 0), so no team-analysis chip has anything to
    read, and no hover either (championPickIntent 0). Ids are the fixture's
    own synthetic values."""
    d = json.loads(_CS_SR.read_text(encoding="utf-8"))
    cs = d["champ_select"]
    for side in ("my_team", "their_team"):
        for p in cs.get(side, []):
            p["championId"] = 0
            if "championPickIntent" in p:
                p["championPickIntent"] = 0
            for k in ("championName", "champion_name", "champion"):
                if k in p:
                    p[k] = ""
    for k in ("my_champion", "my_champion_id"):
        if k in cs:
            cs[k] = 0
    return d


def test_draft_open_team_analysis_is_hidden_and_unfocusable(mock_server, pw_browser):
    ctx, page, errors = _open(
        pw_browser, mock_server, "sr", "champ-select",
        cs_override=_draft_open_fixture())
    try:
        page.wait_for_function(
            "document.getElementById('csv-team-analysis').hidden === true",
            timeout=10_000)
        st = page.evaluate(_PROBE, "#csv-team-analysis")
        assert st["display"] == "none", f"hidden TEAM ANALYSIS still displayed: {st}"
        head = page.evaluate(_PROBE, "#csv-ta-head")
        assert head["rects"] == 0, f"ghost TEAM ANALYSIS head still painted: {head}"
        # A hidden cluster's head must be out of the tab order: focus() on a
        # display:none subtree is a no-op.
        took = page.evaluate(
            "() => { const h = document.getElementById('csv-ta-head');"
            " h.focus(); return document.activeElement === h; }")
        assert took is False, "hidden TEAM ANALYSIS head still takes focus"
        cp = page.evaluate(_PROBE, "#csv-sugg-counter-picks")
        assert cp["hidden"] is True and cp["display"] == "none", cp
    finally:
        _close(ctx, page)
    assert not errors, f"JS errors: {errors[:3]}"


def test_non_sr_counter_picks_leaves_no_gap(mock_server, pw_browser):
    for mode in ("aram", "arena"):
        ctx, page, errors = _open(pw_browser, mock_server, mode, "champ-select")
        try:
            st = page.evaluate(_PROBE, "#csv-sugg-counter-picks")
            assert st["hidden"] is True, f"{mode}: counter-picks shown: {st}"
            assert st["display"] == "none", f"{mode}: hidden counter-picks still a flex item: {st}"
            assert st["rects"] == 0, f"{mode}: {st}"
        finally:
            _close(ctx, page)
        assert not errors, f"{mode} JS errors: {errors[:3]}"


def test_every_hidden_element_computes_display_none(mock_server, pw_browser):
    static_ids = _static_hidden_ids()
    # Anchor: the static universe is not empty and includes the sections
    # this slice fixed, so an empty enumeration cannot pass.
    for must in ("csv-sugg-counter-picks", "csv-team-analysis",
                 "csv-sugg-team-damage", "spend-gates-list",
                 "home-hero-rank-wl"):
        assert must in static_ids, f"{must} not found as a static hidden id"
    ex_classes = [k[6:] for k in _EXCEPTIONS if k.startswith("class:")]
    ex_ids = [k[3:] for k in _EXCEPTIONS if k.startswith("id:")]
    failures = []
    total = 0
    for mode, view in _VIEWS:
        ctx, page, errors = _open(pw_browser, mock_server, mode, view)
        try:
            res = page.evaluate(_SWEEP, [static_ids, ex_classes, ex_ids])
        finally:
            _close(ctx, page)
        total += res["checked"]
        for b in res["bad"]:
            failures.append(f"{mode}:#{view or 'home'} {b}")
        assert not errors, f"{mode}:#{view} JS errors: {errors[:3]}"
    assert total > 100, f"sweep checked only {total} elements"
    assert not failures, (
        "hidden elements that still compute a display (add a [hidden] rule, "
        "or name a deliberate exception in _EXCEPTIONS):\n" + "\n".join(failures))


def test_exceptions_are_still_real():
    """Each named exception must still be backed by the rule it cites, so
    the allowance dies with the rule."""
    css = (_INDEX.parent / "css" / "panels")
    header = (css / "header.css").read_text(encoding="utf-8")
    home = (css / "home.css").read_text(encoding="utf-8")
    assert re.search(r'body\[data-view="settings"\]\s*#view-settings', header), \
        "view-section CSS routing rule gone; drop the class:view-section exception"
    assert re.search(r"\.home-hero-headline\[hidden\]\s*\{[^}]*visibility:\s*hidden",
                     home), \
        "home-hero-headline no-reflow rule gone; drop its exception"
    assert set(_EXCEPTIONS) == {"class:view-section", "id:home-hero-headline"}
