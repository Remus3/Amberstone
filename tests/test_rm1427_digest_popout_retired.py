"""
tests/test_rm1427_digest_popout_retired.py
RM-1427 (s150, adjudicated SPLIT): the cross-session digest popout is retired,
and the task detail modal stays dormant.

Why the popout goes (measured at HEAD before the change):
- its last entry point, the Home `#home-alerts-digest` pip, was deleted by name
  in 3626bb00d (s218, "wireAlertRow calls for removed pip buttons"), after
  77c5b7297 had already hidden the footer `#digest-icon` and re-homed it there;
- `#digest-icon` ships `hidden`, `.digest-icon[hidden]` forces it shut with
  !important, and no script clears it;
- 7 of its 8 blocks read `digest_*` keys that no producer writes
  (core/aftergame_summary.py `_pick_digest` is an MVP stub that emits only
  digest_state / digest_label / digest_tooltip);
- the one live block, TOP INSIGHTS from /api/digest, already shows on other
  surfaces (Adaptation streak rows, Session hygiene factors, the duration panel).

Why the task modal stays: its only opener is the activity row inside
`#activity-strip`, hidden by an in-place, visual-only operator request
(2026-04-29) that documents its own one-line restore. The modal, its binder and
its backend are live, so it is dormant, not dead.

The removal is visual only (memory feedback_field_remove_visual_only): the
payload keys, the /api/digest route and its :8888 proxy entry stay, and the
hidden `#digest-icon` / `#digest-label` stay as the write target renderDigest
keeps filling.

Static, no browser. Every walk is anchored (the files it must find are asserted
found), so an empty enumeration cannot pass.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX = WEB / "index.html"
MAIN_JS = WEB / "js" / "main.js"
RIGHT_NOW_JS = WEB / "js" / "panels" / "right_now.js"
HEADER_CSS = WEB / "css" / "panels" / "header.css"
ACTIVITY_CSS = WEB / "css" / "panels" / "input_activity.css"

_POPOUT_IDS = (
    "digest-popout", "digest-popout-close", "digest-popout-title",
    "dig-state", "dig-streak", "dig-recent", "dig-kda-trend", "dig-tod",
    "dig-fatigue", "dig-advice", "dig-insights", "dig-insights-count",
)
_JS_NEEDLES = ("digest-popout", "digest-popover", "dig-insights", "/api/digest")
_CSS_NEEDLES = (".digest-popout", "#digest-popout", ".digest-insights")


def _read(p):
    assert p.is_file(), f"premise: {p.relative_to(ROOT).as_posix()} exists"
    return p.read_text(encoding="utf-8")


def _html_ids():
    ids = re.findall(r"""\bid\s*=\s*["']([^"']+)["']""", _read(INDEX))
    assert len(ids) > 200, f"premise: index.html ids parsed ({len(ids)})"
    return set(ids)


def _walk(sub, suffix, must):
    """{posix relpath: text} under web/<sub>, anchored on the files in must."""
    files = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8")
             for p in sorted((WEB / sub).rglob("*" + suffix)) if p.is_file()}
    missing = [m for m in must if m not in files]
    assert not missing, f"premise: the walk did not find {missing}"
    return files


def _block_end(src, start):
    """Index just past the brace that closes the `{` at src[start], skipping
    strings, template literals and comments."""
    depth, i, n = 0, start, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            i = src.find("\n", i)
            i = n if i == -1 else i
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if c in "\"'`":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            i = j + 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise AssertionError(f"unbalanced registerEscapeLayer block at {start}")


def _escape_layers():
    """[(relpath, name, modal)] for every registerEscapeLayer({...}) call."""
    files = _walk("js", ".js", ("web/js/main.js", "web/js/panels/right_now.js"))
    out = []
    for rel, src in files.items():
        for m in re.finditer(r"registerEscapeLayer\(\{", src):
            lo = m.end() - 1
            block = src[lo:_block_end(src, lo)]
            name = re.search(r"""\bname:\s*["']([^"']+)["']""", block)
            assert name, f"premise: a literal layer name in {rel} at {lo}"
            modal = re.search(r"(?m)^\s*modal:\s*true\b", block) is not None
            out.append((rel, name.group(1), modal))
    assert len(out) >= 6, f"premise: escape layers parsed ({out})"
    assert ("web/js/main.js", "task-modal", True) in out, out
    return out


def _tag(html, elem_id):
    m = re.search(r"<[a-z]+\b[^>]*\bid=\"" + re.escape(elem_id) + r"\"[^>]*>",
                  html)
    assert m, f"premise: #{elem_id} is in index.html"
    return m.group(0)


def _render_digest_body():
    src = _read(RIGHT_NOW_JS)
    m = re.search(r"function renderDigest\(p\) \{", src)
    assert m, "premise: right_now.js defines renderDigest(p)"
    lo = m.end() - 1
    return src[lo:_block_end(src, lo)]


# -- RED before RM-1427: the popout is gone ---------------------------------

def test_index_html_carries_no_digest_popout_id():
    left = sorted(i for i in _POPOUT_IDS if i in _html_ids())
    assert not left, f"web/index.html still carries popout ids: {left}"


def test_no_web_js_names_the_popout_or_its_fetch():
    files = _walk("js", ".js", ("web/js/main.js", "web/js/panels/right_now.js"))
    hits = sorted(f"{rel}: {n}" for rel, src in files.items()
                  for n in _JS_NEEDLES if n in src)
    assert not hits, f"web/js still names the digest popout: {hits}"


def test_no_web_css_styles_the_popout():
    files = _walk("css", ".css", ("web/css/panels/header.css",
                                  "web/css/overlay.css"))
    hits = sorted(f"{rel}: {n}" for rel, src in files.items()
                  for n in _CSS_NEEDLES if n in src)
    assert not hits, f"web/css still styles the digest popout: {hits}"


def test_the_only_modal_escape_layer_is_the_task_modal():
    modal = sorted(name for _rel, name, is_modal in _escape_layers() if is_modal)
    assert modal == ["task-modal"], f"modal escape layers: {modal}"


def test_digest_icon_stays_a_hidden_write_target_without_a_button_role():
    html = _read(INDEX)
    icon = _tag(html, "digest-icon")
    assert re.search(r"\shidden(\s|>|=)", icon), f"#digest-icon lost hidden: {icon}"
    assert 'role="button"' not in icon, f"#digest-icon still claims a button: {icon}"
    assert "aria-label" not in icon, f"#digest-icon still names an opener: {icon}"
    assert "digest-label" in _html_ids(), "#digest-label is gone"
    body = _render_digest_body()
    assert 'el("digest-label")' in body and "label.textContent" in body, (
        "renderDigest no longer writes #digest-label")


# -- GREEN before and after: what RM-1427 keeps -----------------------------

def test_the_task_modal_is_kept_with_its_opener_and_its_modal_layer():
    ids = _html_ids()
    gone = [i for i in ("task-modal", "task-modal-close", "task-modal-title",
                        "tm-events") if i not in ids]
    assert not gone, f"the task modal lost {gone}"
    main = _read(MAIN_JS)
    assert re.search(r'span\.addEventListener\("click",\s*\(\)\s*=>\s*'
                     r"openTaskModal\(e\.task_id\)\)", main), (
        "main.js no longer opens the task modal from an activity row")
    assert ("web/js/main.js", "task-modal", True) in _escape_layers()


def test_the_activity_strip_stays_hidden():
    css = _read(ACTIVITY_CSS)
    rules = re.findall(r"(?m)^\.activity-strip \{([^}]*)\}", css)
    assert len(rules) == 1, f"premise: one top-level .activity-strip rule ({len(rules)})"
    assert re.search(r"(?m)^\s*display:\s*none;", rules[0]), (
        "the .activity-strip rule no longer hides the strip; RM-1427 restores nothing")


def test_the_digest_data_path_is_kept():
    from dashboard import _handler

    assert "/api/digest" in _handler.SUPERVISOR_PROXY_PATHS
    sup = _read(ROOT / "agents" / "_supervisor_http.py")
    assert "def _handle_digest(" in sup, "the supervisor /api/digest handler is gone"
    from core import aftergame_summary

    assert "digest_state" in aftergame_summary._pick_digest({}, {}), (
        "the aftergame payload no longer carries digest_state")
