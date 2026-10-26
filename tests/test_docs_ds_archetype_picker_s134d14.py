"""Guard (RM-922): the DS doc's Phase 3 archetype section stays true.

``docs/DAEMON_SLAYER.md`` "Phase 3 archetype picker + dispatcher (s176)"
still described the s176 operator picker as live, measured 2026-10-26:

* its UI bullet said a 6-button 3x2 picker grid in the My Pick card saves
  clicks to ``localStorage.rc-cs-archetype-<champion>`` and POSTs them, but
  LEDGER 824 (2026-07-09) deleted that picker and the in-game right-click
  archetype cycle, because a ``user_cs`` POST into the shared
  ``data/cs_archetype_picks.json`` polluted the committed build-order
  precompute; champ-select now only GETs the resolved pick and shows it as a
  read-only chip;
* its ``.gitignore:77`` citation no longer pointed at the
  ``data/cs_archetype_picks.json`` ignore line.

The section's claims are pinned to the code in both directions: a picker that
comes back (any shipped web module writing the pick) turns this red as surely
as the refuted wording returning. ``core/archetype_picks.py``'s module
docstring carried the same localStorage-mirror claim and is pinned too.
ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"
_HEADING = "## Phase 3 archetype picker + dispatcher (s176)"
_PICKS_FILE = "data/cs_archetype_picks.json"
_CHAMP_SELECT = _REPO_ROOT / "web" / "js" / "panels" / "champ_select.js"
_CHIP = _REPO_ROOT / "web" / "js" / "panels" / "archetype_chip.js"
_ROUTES = _REPO_ROOT / "dashboard" / "routes_archetype.py"
_PICKS_MODULE = _REPO_ROOT / "core" / "archetype_picks.py"

_CITE = re.compile(r"`([A-Za-z0-9_./-]+):(\d+)(?:-(\d+))?`")
_ROUTE = "/api/cs-archetype-pick"
_LS_KEY = "rc-cs-archetype-"

# Wording the section must not carry again (whitespace-normalised, lowercased).
_REFUTED = (
    "clicks save to",
    "unimplemented scorers grayed",
    "no manual on-hit button yet",
    "operator-facing scorer selection lands in three layers",
)


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def _section() -> str:
    text = _DOC.read_text(encoding="utf-8")
    start = text.index(_HEADING)
    end = text.index("\n## ", start + len(_HEADING))
    return text[start:end]


def _bullet(label: str) -> str:
    sec = _section()
    marker = f"- **{label}**:"
    start = sec.index(marker)
    nxt = sec.find("\n- **", start + len(marker))
    return sec[start:] if nxt == -1 else sec[start:nxt]


def _tracked(*pathspecs: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--", *pathspecs],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def _shipped_web_modules() -> list[Path]:
    """Tracked, non-test JS / HTML under the two UI roots."""
    rels = _tracked("web", "rc-shell")
    keep = []
    for rel in rels:
        if not rel.endswith((".js", ".mjs", ".html")):
            continue
        name = rel.rsplit("/", 1)[-1]
        if ".test." in name or "/test/" in rel or "/tests/" in rel:
            continue
        keep.append(_REPO_ROOT / rel)
    return keep


def _strip_js_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    # Not after ":" so a "http://.../api/..." string literal survives.
    return re.sub(r"(?m)(?<!:)//.*$", "", src)


def test_gitignore_citation_points_at_the_picks_ignore_line():
    cites = [c for c in _CITE.finditer(_section()) if c.group(1) == ".gitignore"]
    assert cites, "the Storage bullet must cite the .gitignore line"
    lines = (_REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for c in cites:
        n = int(c.group(2))
        assert c.group(3) is None, "cite the single ignore line"
        assert lines[n - 1].strip() == _PICKS_FILE, (
            f".gitignore:{n} is {lines[n - 1]!r}, not the {_PICKS_FILE} line"
        )


def test_picks_file_is_gitignored_and_untracked():
    assert "GITIGNORED" in _bullet("Storage")
    assert _tracked(_PICKS_FILE) == []
    res = subprocess.run(
        ["git", "check-ignore", "-q", _PICKS_FILE], cwd=_REPO_ROOT,
    )
    assert res.returncode == 0, f"{_PICKS_FILE} is no longer ignored"


def test_refuted_wording_does_not_return():
    sec = _norm(_section())
    for phrase in _REFUTED:
        assert phrase not in sec, f"refuted wording back in the section: {phrase!r}"


def test_ui_bullet_records_the_removal_and_the_read_only_chip():
    ui = _norm(_bullet("UI"))
    for needle in (
        "read-only",
        "ledger 824",
        "2026-07-09",
        "right-click",
        "_csvfetcharchetype",
        "_csvresolvearchetype",
        "archetypechiphtml",
        "web/js/panels/archetype_chip.js",
        "web/js/panels/champ_select.js",
    ):
        assert needle in ui, f"UI bullet must name {needle!r}"


def test_no_shipped_web_module_writes_the_pick():
    """The doc says nothing in the UI writes the pick; hold the code to it."""
    writers = []
    for path in _shipped_web_modules():
        src = _strip_js_comments(path.read_text(encoding="utf-8", errors="replace"))
        if _LS_KEY in src:
            writers.append(f"{path.relative_to(_REPO_ROOT)} uses {_LS_KEY}")
        # Either side of the route string, so an options object that names the
        # method first, a hoisted options variable, a post helper or a beacon
        # all count; the one shipped reader (a bare GET fetch) has none nearby.
        for m in re.finditer(re.escape(_ROUTE), src):
            window = src[max(0, m.start() - 400):m.end() + 400]
            if re.search(
                r"""["'](?:POST|PUT|PATCH|DELETE)["']|\bsendBeacon\b|\bpost\w*\s*\(""",
                window, re.I,
            ):
                writers.append(f"{path.relative_to(_REPO_ROOT)} POSTs {_ROUTE}")
    assert not writers, (
        "a UI surface writes the archetype pick again - update the Phase 3 "
        f"section of docs/DAEMON_SLAYER.md: {writers}"
    )


def test_named_ui_symbols_exist_where_the_doc_says():
    cs = _strip_js_comments(_CHAMP_SELECT.read_text(encoding="utf-8"))
    for fn in ("_csvFetchArchetype", "_csvResolveArchetype"):
        assert re.search(rf"\bfunction\s+{fn}\s*\(", cs), f"{fn} gone from champ_select.js"
    assert "_csvArchetypePickerHtml" not in cs
    assert "_csvWireArchetypePicker" not in cs
    assert re.search(
        r"""import\s*\{[^}]*\barchetypeChipHtml\b[^}]*\}\s*from\s*["']\./archetype_chip\.js["']""",
        cs,
    ), "champ_select.js no longer imports the chip"
    assert re.search(r"\barchetypeChipHtml\s*\(", cs), "champ_select.js no longer renders the chip"
    chip = _strip_js_comments(_CHIP.read_text(encoding="utf-8"))
    assert re.search(r"\bexport\s+function\s+archetypeChipHtml\s*\(", chip)
    assert "fetch(" not in chip, "the chip is documented as fetch-free presentation"


def test_rest_bullet_matches_the_route_table():
    """GET and POST both stay registered; the doc says no UI sends the POST."""
    tree = ast.parse(_ROUTES.read_text(encoding="utf-8"))
    tables: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in ("GET_ROUTES", "POST_ROUTES"):
                    tables[tgt.id] = [
                        ast.literal_eval(elt.elts[0].args[0])
                        for elt in node.value.elts
                        if isinstance(elt, ast.Tuple) and isinstance(elt.elts[0], ast.Call)
                    ]
    assert _ROUTE in tables.get("GET_ROUTES", [])
    assert _ROUTE in tables.get("POST_ROUTES", [])
    rest = _norm(_bullet("REST"))
    assert "no dashboard surface sends the post" in rest


def test_archetype_picks_docstring_drops_the_localstorage_mirror():
    doc = _norm(ast.get_docstring(ast.parse(_PICKS_MODULE.read_text(encoding="utf-8"))) or "")
    assert "mirrors it" not in doc
    assert "can override the primary via" not in doc
    assert "ledger 824" in doc
    assert "only gets the resolved pick" in doc
