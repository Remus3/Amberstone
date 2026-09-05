# arch: every VIEW_IDS entry must have a real mount | section=tests | frozen=no
"""
tests/test_web_view_registry_rm340.py

RM-340 - the view registry in ``web/js/lib/state.js`` must stay resolvable
against the DOM: every id in ``VIEW_IDS`` mounts something real, every id has
exactly one label and every label key is an id, and every menu item points at a
view that exists.

WHY THIS NEEDS A GUARD AT ALL. A registered view with no mount does not throw
and does not warn. ``applyView`` accepts the id, stamps
``document.body.dataset.view``, matches no CSS rule and reveals no section, so
the user gets a REACHABLE BLANK DASHBOARD - a route that looks wired from every
angle a grep can see. That was the live state of ``"dev"``: it sat in
``VIEW_IDS`` and in ``VIEW_LABELS`` with no ``#view-dev`` section, no
``data-view="dev"`` menu button, no ``body[data-view="dev"]`` CSS rule, and a
dead ``else if (v === "dev")`` branch in the menu click handler that could
never fire because the button it read from did not exist. Navigating to
``#dev`` - or restoring a stale ``"dev"`` left in ``localStorage`` under
``rc-view-manual`` - landed on it.

THE DEFECT IS CROSS-LANGUAGE, WHICH IS THE WHOLE REASON THIS FILE EXISTS. The
registry is a JS array; the mounts are HTML id attributes; the menu is HTML
data- attributes. No single-language linter can see across that seam, and
source review does not either, because the reference in each language reads
perfectly well on its own.

DO NOT CONFUSE THIS WITH ``web/js/panels/dev.js``. That module is the live
Settings / fixture-viewer / replay-scrubber panel and has nothing to do with
the dead ``dev`` VIEW that shares its name. It is deliberately NOT referenced
by any assertion here.

THREE DIRECTIONS ARE CHECKED, AND EACH CATCHES A DIFFERENT DEFECT:
  1. id -> mount. A view nothing can show. This is what ``"dev"`` was.
  2. id <-> label, BOTH ways. The orphan ``"dev": "Dev"`` label survives a
     one-directional check, which is why the label direction is asserted in
     its own right rather than folded into direction 1.
  3. menu -> id. The mirror defect of direction 1: a button that navigates to
     a view that does not exist.

EXEMPTIONS ASSERT, THEY DO NOT SKIP. ``home`` has no ``section#view-home``; it
mounts as ``div#home-overlay`` (``web/index.html:119``) and is special-cased at
``web/js/main.js:796``. It is therefore recorded as a REDIRECTED mount, not as
a waiver: the guard still proves ``#home-overlay`` exists, and
``test_mount_exceptions_are_live_and_reasoned`` fails if the redirect ever
becomes unnecessary. An exemption that asserts nothing is how this class comes
back.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_JS = Path("web/js/lib/state.js")
INDEX_HTML = Path("web/index.html")

# state.js is an ES module, so there is no import path from Python. Parse it.
_VIEW_IDS_BLOCK = re.compile(r"export\s+const\s+VIEW_IDS\s*=\s*\[(.*?)\]\s*;", re.S)
_VIEW_LABELS_BLOCK = re.compile(
    r"export\s+const\s+VIEW_LABELS\s*=\s*\{(.*?)\n\}\s*;", re.S
)
_QUOTED = re.compile(r'"([^"]+)"')
_LABEL_PAIR = re.compile(r'"([^"]+)"\s*:\s*"([^"]*)"')
_LINE_COMMENT = re.compile(r"//[^\n]*")

# HTML: id attributes, and the menu buttons that carry data-view.
_ID_ATTR = re.compile(r'\bid\s*=\s*"([^"]+)"')
_BUTTON_TAG = re.compile(r"<button\b[^>]*>", re.S)
_DATA_VIEW = re.compile(r'\bdata-view\s*=\s*"([^"]+)"')

# The default mount for a view id, when no exception redirects it.
MOUNT_ID_TEMPLATE = "view-{view_id}"


# ------------------------------------------------------------------ exemptions
# A REDIRECTED mount, not a waiver. The guard still resolves the id against the
# DOM - it just resolves it somewhere other than section#view-<id>. Every entry
# carries the file:line that makes the redirect real, and
# test_mount_exceptions_are_live_and_reasoned fails if the default mount ever
# appears (which would make the entry obsolete) or if the redirect target is
# missing (which would make it a lie).
MOUNT_EXCEPTIONS: dict[str, tuple[str, str]] = {
    "home": (
        "home-overlay",
        "home does not mount as section#view-home. It mounts as the "
        "full-bleed div#home-overlay declared at web/index.html:119, and "
        'web/js/main.js:796 special-cases `if (viewId === "home")` inside '
        "applyView to re-fetch and repaint that overlay on activation. The "
        "overlay predates the section-per-view layout. This entry redirects "
        "the resolution; it does not skip it - #home-overlay is still asserted "
        "to exist. Delete this entry if home is ever given a real "
        "section#view-home mount."
    ),
}

# Menu data-view values that are SENTINELS rather than view ids. Same rule: the
# entry has to point at the code that consumes it, and the sentinel has to
# still be present in the DOM.
MENU_SENTINELS: dict[str, str] = {
    "auto": (
        "Not a view. It is the `(R) Auto (clear manual)` control at "
        'web/index.html:73, consumed by the dedicated `if (v === "auto")` '
        "branch at web/js/main.js:926, which clears the rc-view-manual sticky "
        "and empties location.hash so the auto-derive router takes over. It "
        "must never resolve to a view id."
    ),
}


# --------------------------------------------------------------------- parsers
def _read(root: Path, rel: Path) -> str:
    return (root / rel).read_text(encoding="utf-8", errors="replace")


def _strip_line_comments(text: str) -> str:
    """Comments inside the registry blocks must not be parsed as data.

    VIEW_LABELS carries a three-line HIST2 note today. A comment that ever
    contained a quoted colon pair would otherwise register as a phantom label.
    """
    return _LINE_COMMENT.sub("", text)


def _view_ids(root: Path) -> list[str]:
    text = _read(root, STATE_JS)
    match = _VIEW_IDS_BLOCK.search(text)
    assert match, f"VIEW_IDS array not found in {STATE_JS.as_posix()} - parser is broken"
    return _QUOTED.findall(_strip_line_comments(match.group(1)))


def _view_labels(root: Path) -> dict[str, str]:
    text = _read(root, STATE_JS)
    match = _VIEW_LABELS_BLOCK.search(text)
    assert match, (
        f"VIEW_LABELS object not found in {STATE_JS.as_posix()} - parser is broken"
    )
    return dict(_LABEL_PAIR.findall(_strip_line_comments(match.group(1))))


def _html_ids(root: Path) -> dict[str, str]:
    """{id: web/index.html:NN} for every literal id attribute in the page."""
    text = _read(root, INDEX_HTML)
    found: dict[str, str] = {}
    for match in _ID_ATTR.finditer(text):
        found.setdefault(
            match.group(1),
            f"{INDEX_HTML.as_posix()}:{text.count(chr(10), 0, match.start()) + 1}",
        )
    return found


def _menu_views(root: Path) -> dict[str, str]:
    """{data-view value: site} for every .view-menu-item button in the page.

    Scoped to the BUTTON TAG, not the line, so attribute order cannot change
    the answer - and so `<body data-view="home">` at web/index.html:36, which
    is the cold-load pre-stamp rather than a menu item, is never counted.
    """
    text = _read(root, INDEX_HTML)
    found: dict[str, str] = {}
    for tag in _BUTTON_TAG.finditer(text):
        if "view-menu-item" not in tag.group(0):
            continue
        value = _DATA_VIEW.search(tag.group(0))
        if not value:
            continue
        found.setdefault(
            value.group(1),
            f"{INDEX_HTML.as_posix()}:{text.count(chr(10), 0, tag.start()) + 1}",
        )
    return found


# ------------------------------------------------------------------ resolution
def _expected_mount(view_id: str) -> str:
    if view_id in MOUNT_EXCEPTIONS:
        return MOUNT_EXCEPTIONS[view_id][0]
    return MOUNT_ID_TEMPLATE.format(view_id=view_id)


def _mountless(root: Path) -> dict[str, str]:
    """{view id: the mount id it expected and did not find}."""
    ids = _html_ids(root)
    return {
        view_id: _expected_mount(view_id)
        for view_id in _view_ids(root)
        if _expected_mount(view_id) not in ids
    }


def _unknown_menu_views(root: Path) -> dict[str, str]:
    """{data-view value: site} for menu items naming no known view."""
    known = set(_view_ids(root))
    return {
        value: site
        for value, site in _menu_views(root).items()
        if value not in known and value not in MENU_SENTINELS
    }


# ------------------------------------------------ direction 1: id -> mount
def test_every_view_id_has_a_real_mount():
    """A registered view with no mount is a reachable blank dashboard.

    RM-340: `dev` was exactly this. applyView accepts any id in VIEW_IDS
    (web/js/main.js:776), _viewFromHash accepts it from the URL
    (web/js/main.js:611) and _viewFromStorage replays it from localStorage
    (web/js/main.js:614), so a mountless id is navigable and silent.
    """
    mountless = _mountless(ROOT)
    report = "\n".join(
        f"  {view_id:<18} expected #{mount} in {INDEX_HTML.as_posix()}"
        for view_id, mount in sorted(mountless.items())
    )
    assert not mountless, (
        f"{len(mountless)} view id(s) in VIEW_IDS mount nothing. Each one is "
        "navigable by hash and by a stale rc-view-manual value, stamps "
        "body[data-view=...], matches no CSS and shows no section. Fix at the "
        "source: add the mount, drop the id from VIEW_IDS (and its "
        "VIEW_LABELS entry), or - if the view genuinely mounts somewhere other "
        "than section#view-<id> - add it to MOUNT_EXCEPTIONS above WITH the "
        "file:line that makes the redirect real.\n" + report
    )


def test_mount_exceptions_are_live_and_reasoned():
    """A redirected mount must still assert, and must still be necessary.

    Three halves, each a way an exemption rots: the id stops being a view, the
    redirect target vanishes (so the entry waives instead of asserting), or the
    default mount appears (so the entry is obsolete and now silently
    pre-approves the id if the real mount is ever deleted).
    """
    ids = set(_view_ids(ROOT))
    html_ids = _html_ids(ROOT)
    for view_id, (mount, reason) in MOUNT_EXCEPTIONS.items():
        assert view_id in ids, (
            f"MOUNT_EXCEPTIONS carries {view_id!r} but it is no longer in "
            "VIEW_IDS - delete the entry rather than leaving a standing "
            "pre-approval"
        )
        assert mount in html_ids, (
            f"MOUNT_EXCEPTIONS redirects {view_id!r} to #{mount}, which does "
            f"not exist in {INDEX_HTML.as_posix()}. The exemption is waiving "
            "rather than asserting - that is the failure mode it exists to "
            "avoid."
        )
        default = MOUNT_ID_TEMPLATE.format(view_id=view_id)
        assert default not in html_ids, (
            f"MOUNT_EXCEPTIONS carries {view_id!r} but #{default} now exists "
            f"at {html_ids.get(default)} - the redirect is obsolete, delete it"
        )
        assert re.search(r"\.(?:js|mjs|html):\d+", reason), (
            f"MOUNT_EXCEPTIONS reason for {view_id!r} cites no file:line. An "
            "exemption has to point at the evidence that makes it deliberate."
        )
        assert len(reason) > 80, (
            f"MOUNT_EXCEPTIONS reason for {view_id!r} is too thin to audit"
        )


# --------------------------------------------- direction 2: id <-> label
def test_every_view_id_has_a_label():
    ids = _view_ids(ROOT)
    labels = _view_labels(ROOT)
    missing = sorted(set(ids) - set(labels))
    assert not missing, (
        f"{len(missing)} view id(s) have no VIEW_LABELS entry, so the title "
        "dropdown renders an empty label for them: " + ", ".join(missing)
    )


def test_every_label_key_is_a_view_id():
    """The direction a one-way guard misses, and the one that caught RM-340.

    The orphan `"dev": "Dev"` label outlived nothing that referenced it. A
    check that only walked VIEW_IDS would have reported the registry clean
    with the label still sitting there.
    """
    ids = _view_ids(ROOT)
    labels = _view_labels(ROOT)
    orphans = sorted(set(labels) - set(ids))
    assert not orphans, (
        f"{len(orphans)} VIEW_LABELS key(s) name no view in VIEW_IDS. A label "
        "for a view that does not exist is dead weight that reads as evidence "
        "the view is real: " + ", ".join(orphans)
    )


def test_no_view_id_is_registered_twice():
    ids = _view_ids(ROOT)
    dupes = sorted({view_id for view_id in ids if ids.count(view_id) > 1})
    assert not dupes, f"VIEW_IDS lists duplicate id(s): {', '.join(dupes)}"


# ------------------------------------------------ direction 3: menu -> id
def test_every_menu_item_points_at_a_known_view():
    """The mirror defect of direction 1: a button that goes nowhere.

    The .view-menu-item click handler (web/js/main.js:922) reads
    btn.dataset.view and hands it straight to location.hash, where
    _viewFromHash rejects anything outside VIEW_IDS and applyView falls back to
    home. A menu item naming a nonexistent view is therefore a control that
    silently does the wrong thing.
    """
    unknown = _unknown_menu_views(ROOT)
    report = "\n".join(
        f"  {value:<18} {site}" for value, site in sorted(unknown.items())
    )
    assert not unknown, (
        f"{len(unknown)} menu item(s) carry a data-view that is not in "
        "VIEW_IDS. Fix at the source: correct the attribute, register the "
        "view, or - if the value is a control sentinel rather than a view - "
        "add it to MENU_SENTINELS above WITH the file:line that consumes "
        "it.\n" + report
    )


def test_menu_sentinels_are_live_and_reasoned():
    """A sentinel exemption must stay attached to a real control.

    If the button is gone the entry is dead weight that pre-approves the value
    if it ever returns; if the value has become a real view id the entry is
    hiding it from direction 3.
    """
    menu = _menu_views(ROOT)
    ids = set(_view_ids(ROOT))
    for value, reason in MENU_SENTINELS.items():
        assert value in menu, (
            f"MENU_SENTINELS carries {value!r} but no .view-menu-item button "
            f"in {INDEX_HTML.as_posix()} uses it any more - delete the entry"
        )
        assert value not in ids, (
            f"MENU_SENTINELS carries {value!r} but it is now a real view id - "
            "the exemption hides it from the menu guard, delete it"
        )
        assert re.search(r"\.(?:js|mjs|html):\d+", reason), (
            f"MENU_SENTINELS reason for {value!r} cites no file:line"
        )
        assert len(reason) > 80, (
            f"MENU_SENTINELS reason for {value!r} is too thin to audit"
        )


# ------------------------------------------------------------ the RM-340 pin
def test_the_mountless_dev_view_stays_removed():
    """Named regression pin for RM-340, in all four places it lived.

    The generic guards above would each catch a partial restore; this one says
    out loud what was removed, so a future reader does not re-add it thinking
    the omission was an oversight. web/js/panels/dev.js is a DIFFERENT thing -
    a live panel - and is deliberately not named here.
    """
    assert "dev" not in _view_ids(ROOT), "the mountless dev view is back in VIEW_IDS"
    assert "dev" not in _view_labels(ROOT), (
        "the orphan dev label is back in VIEW_LABELS"
    )
    assert "view-dev" not in _html_ids(ROOT), (
        "a #view-dev mount appeared. If the dev view is being restored on "
        "purpose, restore its VIEW_IDS entry, its label and its menu item in "
        "the same change and delete this pin."
    )
    assert "dev" not in _menu_views(ROOT), 'a data-view="dev" menu item is back'
    main_js = (ROOT / "web" / "js" / "main.js").read_text(
        encoding="utf-8", errors="replace"
    )
    assert 'v === "dev"' not in main_js, (
        'the unreachable `else if (v === "dev")` branch is back in the '
        "view-menu click handler. It is redundant with the generic else two "
        "lines below it even when a dev menu item exists."
    )


# ----------------------------------------------------- anti-vacuity, both ways
def _scratch_corpus(tmp_path: Path) -> Path:
    """A scratch copy of the two real parsed files, so the probes below run
    against the tree as it actually is rather than a toy fixture."""
    for rel in (STATE_JS, INDEX_HTML):
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dst)
    return tmp_path


def _patch(root: Path, rel: Path, old: str, new: str) -> None:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, (
        f"anchor {old!r} appears {text.count(old)} times in {rel.as_posix()} - "
        "the probe would not be planting what it thinks it is"
    )
    path.write_text(text.replace(old, new), encoding="utf-8", newline="")


def test_guard_catches_a_view_id_with_no_mount(tmp_path):
    """A guard that cannot fail is not a guard. Restore `dev` and watch it fire."""
    root = _scratch_corpus(tmp_path)
    assert not _mountless(root), "scratch copy is not clean to begin with"
    _patch(root, STATE_JS, '"settings",\n]', '"settings", "dev",\n]')
    mountless = _mountless(root)
    assert mountless == {"dev": "view-dev"}, (
        f"restoring dev to VIEW_IDS did not go red as expected: {mountless}"
    )


def test_guard_catches_an_orphan_label(tmp_path):
    """The direction a naive one-way guard misses.

    Restoring ONLY the label leaves the mount guard green - VIEW_IDS is
    untouched - so this is the assertion that has to catch it.
    """
    root = _scratch_corpus(tmp_path)
    _patch(
        root,
        STATE_JS,
        '  "settings": "Settings",\n',
        '  "settings": "Settings",\n  "dev": "Dev",\n',
    )
    ids = set(_view_ids(root))
    labels = _view_labels(root)
    assert not _mountless(root), (
        "a label-only restore must NOT move the mount guard - if it does, the "
        "two directions are not independent and this probe proves nothing"
    )
    assert sorted(set(labels) - ids) == ["dev"], (
        "the label direction did not catch the orphan dev label"
    )


def test_guard_catches_a_menu_item_pointing_at_a_missing_view(tmp_path):
    """Direction 3, planted on a real menu button."""
    root = _scratch_corpus(tmp_path)
    assert not _unknown_menu_views(root), "scratch copy is not clean to begin with"
    _patch(
        root,
        INDEX_HTML,
        'class="view-menu-item" data-view="lobby"',
        'class="view-menu-item" data-view="rm340-no-such-view"',
    )
    unknown = _unknown_menu_views(root)
    assert set(unknown) == {"rm340-no-such-view"}, (
        f"planted menu item was not detected: {unknown}"
    )
    assert unknown["rm340-no-such-view"].startswith("web/index.html:")


def test_guard_stays_silent_on_a_new_view_that_has_a_mount(tmp_path):
    """The other direction. A guard that fires on everything is as useless as
    one that fires on nothing, so a properly wired new view must move nothing.
    """
    root = _scratch_corpus(tmp_path)
    _patch(root, STATE_JS, '"settings",\n]', '"settings", "rm340-ok",\n]')
    _patch(
        root,
        INDEX_HTML,
        '<div id="view-content" class="view-content">',
        '<div id="view-content" class="view-content">\n'
        '    <section id="view-rm340-ok" class="view-section" hidden></section>',
    )
    assert not _mountless(root), (
        "a view id with a real section#view-<id> mount was flagged"
    )


# -------------------------------------------------------------- parser pins
def test_parsed_registry_is_populated():
    """A parser that silently matched nothing would report a clean registry.

    Measured 2026-09-04 after the RM-340 removal: 12 view ids, 12 labels, 11
    section#view-* mounts plus div#home-overlay, 12 menu items (11 views plus
    the auto sentinel).
    """
    ids = _view_ids(ROOT)
    labels = _view_labels(ROOT)
    menu = _menu_views(ROOT)
    assert len(ids) >= 10, f"only {len(ids)} view ids parsed out of state.js"
    assert len(labels) >= 10, f"only {len(labels)} labels parsed out of state.js"
    assert len(menu) >= 10, f"only {len(menu)} menu items parsed out of index.html"
    for must in ("home", "lobby", "champ-select", "active-match", "settings"):
        assert must in ids, f"registry parse lost {must!r}"
    assert len(_html_ids(ROOT)) > 300, "index.html id scan collapsed"


def test_body_pre_stamp_is_not_read_as_a_menu_item():
    """web/index.html:36 is `<body data-view="home">`, the s209 cold-load
    pre-stamp. A line-scoped scanner would count it as a menu item; the
    tag-scoped one must not, or the menu census is wrong by one."""
    text = _read(ROOT, INDEX_HTML)
    assert '<body data-view="home">' in text, "the pre-stamp moved - repoint this test"
    for tag in _BUTTON_TAG.finditer(text):
        assert "<body" not in tag.group(0)
    assert len(_menu_views(ROOT)) < len(_DATA_VIEW.findall(text)), (
        "every data-view in the page was counted as a menu item"
    )


def test_registry_comments_are_not_parsed_as_data():
    """VIEW_LABELS carries a prose note today. A comment must never register."""
    assert _LABEL_PAIR.findall(_strip_line_comments('  // "ghost": "Ghost",\n')) == []
    assert _LABEL_PAIR.findall('  "real": "Real",') == [("real", "Real")]
    assert _QUOTED.findall(_strip_line_comments('  "keep", // "drop",\n')) == ["keep"]
