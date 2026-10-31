"""
tests/test_css_split_family_rm726.py
RM-726 (c) plan rule 5, READERS FIRST (docs/WEB_CSS_SPLIT_PLAN.md): before
the first slice moves a byte out of web/css/panels/header.css, every test
that reads that file as source text reads the helper tests/_css_split.py
instead. The helper returns the source plus its LANDED split targets,
joined in web/css/dashboard.css @import order (the cascade order).

Why: after a slice lands, a reader that still opens header.css alone reads
a file that no longer holds the moved rules. A presence check then fails
with a misleading message, and an ABSENCE check (a retired selector must
not come back) keeps passing while it checks nothing - a resurrected rule
in a new piece would be invisible to it.

This file pins:
- the helper's contract on a synthetic tree (landed targets only, import
  order, joined bytes, loud failures for an unimported or mis-ordered
  landed target and for a missing plan);
- today's tree: no header slice has landed, so the family of header.css
  is exactly header.css and the joined text is its bytes;
- a ratchet: no tracked test builds a path to header.css any more (the
  `/ "header.css"` pathlib form every reader used). Named blind spot: a
  reader that builds the path some other way (a joined string, a variable
  holding the name) is not seen; the ratchet pins the form that was there.
"""
from __future__ import annotations

import re

import pytest

from tests import _css_split
from tests._repo_walk import REPO_ROOT, tracked_relpaths

HEADER = "web/css/panels/header.css"
SELF = "test_css_split_family_rm726.py"

# Sources whose readers have been re-pointed (rule 5). The CV prep adds
# "champ_select_view.css" when its slices are cut.
PREPPED = ("header.css",)

PLAN_TMPL = """# plan

### HS-1 - first
- File: `web/css/panels/src.css`
- Target: `src_a.css`

### HS-2 - second
- File: `web/css/panels/src.css`
- Target: `src_b.css`

### CV-1 - other
- File: `web/css/panels/other.css`
- Target: `other_a.css`

## Order
"""


def _tree(tmp_path, imports, files):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "WEB_CSS_SPLIT_PLAN.md").write_text(
        PLAN_TMPL, encoding="utf-8", newline="\n")
    panels = tmp_path / "web" / "css" / "panels"
    panels.mkdir(parents=True)
    (tmp_path / "web" / "css" / "dashboard.css").write_text(
        "".join(f"@import './panels/{n}';\n" for n in imports),
        encoding="utf-8", newline="\n")
    for name, body in files.items():
        (panels / name).write_text(body, encoding="utf-8", newline="\n")
    return tmp_path


def test_unlanded_family_is_the_source_alone(tmp_path):
    root = _tree(tmp_path, ["src.css", "src_a.css"], {"src.css": ".a{}\n"})
    paths = _css_split.family_paths("web/css/panels/src.css", root=root)
    assert paths == [root / "web/css/panels/src.css"]
    assert _css_split.family_text("web/css/panels/src.css", root=root) == ".a{}\n"


def test_landed_targets_join_in_import_order(tmp_path):
    # Plan order is a then b; the import order says b then a. The helper
    # follows the import order, which is the cascade the browser applies.
    root = _tree(tmp_path, ["src.css", "src_b.css", "src_a.css", "other.css"],
                 {"src.css": ".s{}\n", "src_a.css": ".a{}\n",
                  "src_b.css": ".b{}\n", "other.css": ".o{}\n",
                  "other_a.css": ".oa{}\n"})
    panels = root / "web" / "css" / "panels"
    assert _css_split.family_paths("web/css/panels/src.css", root=root) == [
        panels / "src.css", panels / "src_b.css", panels / "src_a.css"]
    assert _css_split.family_text(
        "web/css/panels/src.css", root=root) == ".s{}\n.b{}\n.a{}\n"


def test_landed_target_not_imported_fails_loudly(tmp_path):
    root = _tree(tmp_path, ["src.css"],
                 {"src.css": ".s{}\n", "src_a.css": ".a{}\n"})
    with pytest.raises(AssertionError, match="src_a.css"):
        _css_split.family_paths("web/css/panels/src.css", root=root)


def test_landed_target_imported_before_source_fails_loudly(tmp_path):
    root = _tree(tmp_path, ["src_a.css", "src.css"],
                 {"src.css": ".s{}\n", "src_a.css": ".a{}\n"})
    with pytest.raises(AssertionError, match="before"):
        _css_split.family_paths("web/css/panels/src.css", root=root)


def test_missing_source_or_plan_fails_loudly(tmp_path):
    root = _tree(tmp_path, ["src.css"], {})
    with pytest.raises(AssertionError, match="src.css"):
        _css_split.family_paths("web/css/panels/src.css", root=root)
    (root / "docs" / "WEB_CSS_SPLIT_PLAN.md").unlink()
    (root / "web" / "css" / "panels" / "src.css").write_text(
        ".s{}\n", encoding="utf-8", newline="\n")
    with pytest.raises(AssertionError, match="WEB_CSS_SPLIT_PLAN"):
        _css_split.family_paths("web/css/panels/src.css", root=root)


def test_header_family_on_this_tree():
    """No header slice has landed at this commit: the family is header.css
    alone. A later slice commit lands a target, and this then reads the
    joined pieces with no edit here."""
    targets = _css_split.planned_targets(HEADER)
    assert len(targets) >= 3, f"premise: the plan cuts header.css ({targets})"
    paths = _css_split.family_paths(HEADER)
    assert paths[0] == REPO_ROOT / HEADER
    landed = [p.name for p in paths[1:]]
    assert landed == [t for t in landed if t in targets]
    text = _css_split.family_text(HEADER)
    assert text == "".join(p.read_text(encoding="utf-8") for p in paths)
    assert ".view-tab" in text, "premise: the family holds header.css rules"


_PATH_FORM = r"/\s*[rbu]?[\"'](?:[\w./-]*/)?%s[\"']"


@pytest.mark.parametrize("name", PREPPED)
def test_no_test_builds_a_path_to_a_prepped_source(name):
    # tracked_relpaths answers relative to the directory it is given.
    tracked = tracked_relpaths(str(REPO_ROOT / "tests"))
    assert tracked, "premise: git index readable for tests/"
    # This file quotes the reader forms on purpose (docstring and the
    # pattern self-test below), so it is the one file the scan skips.
    rels = sorted("tests/" + r for r in tracked
                  if r.endswith(".py") and r != SELF)
    rx = re.compile(_PATH_FORM % re.escape(name))
    hits, read = [], 0
    for rel in rels:
        p = REPO_ROOT / rel
        if not p.is_file():
            continue
        read += 1
        if rx.search(p.read_text(encoding="utf-8", errors="replace")):
            hits.append(rel)
    # Anchor on files READ, not names listed: a wrong base path lists 2000
    # names and reads none, and the ratchet then passes vacuously.
    assert read > 500, f"premise: tracked test files read ({read})"
    assert hits == [], (
        f"these tests open {name} directly; read it through "
        f"tests/_css_split.family_text (plan rule 5): {hits}")


def test_ratchet_pattern_matches_the_reader_forms():
    """The ratchet's regex must see each form the readers used, or an empty
    hit list proves nothing about them."""
    rx = re.compile(_PATH_FORM % re.escape("header.css"))
    for form in ('WEB / "css" / "panels" / "header.css"',
                 'ROOT / "web" / "css" / "panels" / "header.css",',
                 "ROOT / 'web/css/panels/header.css'"):
        assert rx.search(form), form
    for prose in ('"web/css/panels/header.css": 5,',
                  "web/css/panels/header.css (the S4 block)",
                  '_css_split.family_text("web/css/panels/header.css")'):
        assert not rx.search(prose), prose
