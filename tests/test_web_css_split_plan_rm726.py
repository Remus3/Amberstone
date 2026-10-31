"""
tests/test_web_css_split_plan_rm726.py
RM-726 (c) (s144 queue lane): two panel stylesheets are over the row's 60 KB
cap (web/css/panels/header.css and web/css/panels/champ_select_view.css).
The plan to cut them is docs/WEB_CSS_SPLIT_PLAN.md. This guard keeps it
honest while it waits and while it is carried out:

- every slice block names its source file, its target stylesheet, the line
  it starts at, the class anchors it moves, its coupled files, the views its
  UI audit renders, and all five audit phases;
- a CSS cut is CONTIGUOUS, so cascade order survives only if each moved range
  is a run of whole top-level rules imported right after what precedes it.
  So: every Start line of a slice that has not landed occurs exactly once in
  the source, at brace depth 0, in plan order; a landed slice's Start line
  is in its target and no longer in the source;
- every anchor class sits only inside its slice: before landing, every
  `.anchor` occurrence in the source is inside the slice's range; after
  landing, none is left in the source and the target has it. A copied range
  goes red;
- the pieces the plan cuts are each at most 60 KB (61,440 bytes): the source
  split at the Start lines of the slices that have not landed, plus every
  landed target. So the plan really meets the row's cap, and a lane that
  grows one range past it turns this red and the plan is re-cut;
- web/css/dashboard.css imports the source and its landed targets on
  consecutive lines, in plan order (the @import order IS the cascade order);
- every coupled file exists and names the source or target AND one anchor;
  a "none" Coupled line is re-measured over the tracked tests and tools;
- every view is a real view id (web/js/lib/state.js VIEW_IDS) or "all";
- a landed slice (its target exists) carries `(LANDED <sha>)` in its
  heading, and an unlanded one does not;
- the enumeration cannot be empty.

Not enforced here, by design: that the joined pieces equal the old source
bytes. This guard cannot know the old bytes; the slice's own landing check
and its verifier do (plan rule 2). Rules with no anchor that stay behind are
caught by that byte check, not by this guard.

Start lines and anchors are text, never line numbers: these files grow on
every lane.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs" / "WEB_CSS_SPLIT_PLAN.md"
ARCH = ROOT / "docs" / "ARCHITECTURE.md"
STATE_JS = ROOT / "web" / "js" / "lib" / "state.js"
DASHBOARD_CSS = ROOT / "web" / "css" / "dashboard.css"

CAP_BYTES = 60 * 1024
SOURCES = {
    "HS": "web/css/panels/header.css",
    "CV": "web/css/panels/champ_select_view.css",
}
MIN_SLICES = {"HS": 3, "CV": 2}
PHASES = ("STRUCTURE", "TYPOGRAPHY", "HIT-TARGETS", "ASCII", "HIERARCHY")
FIELDS = ("File", "Target", "Start", "Anchors", "Coupled", "Views",
          "UI audit")

_HEAD = re.compile(r"^### (HS|CV)-(\d+)\b.*$", re.MULTILINE)
_FIELD = re.compile(
    r"^- (File|Target|Start|Anchors|Coupled|Views|UI audit):(.*)$",
    re.MULTILINE)
_TICKED = re.compile(r"`([^`]+)`")
_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_IMPORT = re.compile(r"""^@import\s+['"]\./([^'"]+)['"]\s*;""", re.MULTILINE)


def _plan_text():
    assert PLAN.is_file(), "docs/WEB_CSS_SPLIT_PLAN.md is missing (RM-726 (c))"
    return PLAN.read_text(encoding="utf-8")


def _slices(text):
    """Split the plan into slice blocks: {"id", "prefix", "num", "fields"}."""
    heads = list(_HEAD.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        nxt = text.find("\n## ", m.end(), end)
        if nxt != -1:
            end = nxt
        body = text[m.end():end]
        fields = {}
        for f in _FIELD.finditer(body):
            assert f.group(1) not in fields, (
                f"{m.group(1)}-{m.group(2)} repeats the field {f.group(1)}")
            fields[f.group(1)] = f.group(2).strip()
        out.append({"id": f"{m.group(1)}-{m.group(2)}",
                    "prefix": m.group(1), "num": int(m.group(2)),
                    "head": m.group(0), "fields": fields, "body": body})
    return out


SLICES = _slices(_plan_text()) if PLAN.is_file() else []


def _read(rel):
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _uncomment(css):
    """Blank comments but keep every offset, so positions line up."""
    return _COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), css)


def _target(s):
    return "web/css/panels/" + _TICKED.findall(s["fields"]["Target"])[0]


def _start(s):
    """The Start field is exactly one backticked line of CSS text."""
    ticked = _TICKED.findall(s["fields"].get("Start", ""))
    assert len(ticked) == 1, f"{s['id']} Start must be one backticked line"
    return ticked[0]


def _line_offsets(text, line):
    offs, off = [], 0
    for raw in text.split("\n"):
        if raw.rstrip() == line:
            offs.append(off)
        off += len(raw) + 1
    return offs


def _landed(s):
    return (ROOT / _target(s)).is_file()


def _ranges(prefix):
    """{slice id: (lo, hi)} char ranges in the CURRENT source for every
    slice that has not landed. A range runs from its Start line to the next
    unlanded Start line, or to the end of the file."""
    src = _read(SOURCES[prefix])
    pend = [s for s in SLICES if s["prefix"] == prefix and not _landed(s)]
    starts = []
    for s in pend:
        offs = _line_offsets(src, _start(s))
        starts.append((s["id"], offs[0] if len(offs) == 1 else None))
    out = {}
    known = [(sid, o) for sid, o in starts if o is not None]
    for i, (sid, lo) in enumerate(known):
        hi = known[i + 1][1] if i + 1 < len(known) else len(src)
        out[sid] = (lo, hi)
    return out


def _class_hits(css, name):
    rx = re.compile(r"\." + re.escape(name) + r"(?![\w-])")
    return [m.start() for m in rx.finditer(_uncomment(css))]


def _view_ids():
    src = STATE_JS.read_text(encoding="utf-8")
    m = re.search(r"export const VIEW_IDS = \[(.*?)\];", src, re.DOTALL)
    assert m, "premise: VIEW_IDS found in web/js/lib/state.js"
    ids = set(re.findall(r'"([a-z-]+)"', m.group(1)))
    assert len(ids) >= 10, f"premise: VIEW_IDS parsed ({len(ids)} ids)"
    return ids


def _ids():
    return [s["id"] for s in SLICES] or ["no-slices"]


def _slice(sid):
    s = {x["id"]: x for x in SLICES}.get(sid)
    assert s is not None, "the plan has no slice blocks"
    return s


def test_plan_exists_and_names_both_files():
    text = _plan_text()
    for path in SOURCES.values():
        assert path in text, f"the plan does not name {path}"
    assert "RM-726" in text


def test_enumeration_is_not_empty():
    _plan_text()
    for prefix, need in MIN_SLICES.items():
        n = sum(1 for s in SLICES if s["prefix"] == prefix)
        assert n >= need, f"{prefix}: {n} slices, the plan needs {need}"
    anchors = sum(len(_TICKED.findall(s["fields"].get("Anchors", "")))
                  for s in SLICES)
    assert anchors >= 40, f"only {anchors} anchors named across the plan"


def test_slice_ids_are_numbered_in_order():
    _plan_text()
    for prefix in SOURCES:
        nums = [s["num"] for s in SLICES if s["prefix"] == prefix]
        assert nums == list(range(1, len(nums) + 1)), (
            f"{prefix} slices out of order or duplicated: {nums}")


@pytest.mark.parametrize("sid", _ids())
def test_slice_has_every_field(sid):
    s = _slice(sid)
    missing = [k for k in FIELDS if k not in s["fields"]]
    assert not missing, f"{sid} lacks {missing}"
    assert _TICKED.findall(s["fields"]["File"]) == [SOURCES[s["prefix"]]], (
        f"{sid} File must be `{SOURCES[s['prefix']]}`")
    target = _TICKED.findall(s["fields"]["Target"])
    assert len(target) == 1 and re.fullmatch(r"[a-z0-9_]+\.css", target[0]), (
        f"{sid} Target must be one bare file name under web/css/panels/")
    assert _target(s) != SOURCES[s["prefix"]], f"{sid} targets its own source"
    others = [_target(o) for o in SLICES if o is not s]
    assert _target(s) not in others, f"{sid} shares its target with a slice"


@pytest.mark.parametrize("sid", _ids())
def test_slice_audit_names_all_five_phases(sid):
    audit = _slice(sid)["fields"].get("UI audit", "")
    missing = [p for p in PHASES if p not in audit]
    assert not missing, f"{sid} UI audit lacks {missing}"


@pytest.mark.parametrize("sid", _ids())
def test_slice_views_are_real_view_ids(sid):
    views = _TICKED.findall(_slice(sid)["fields"].get("Views", ""))
    assert views, f"{sid} names no view to audit"
    bad = [v for v in views if v not in _view_ids() | {"all"}]
    assert not bad, f"{sid} names unknown views {bad}"


@pytest.mark.parametrize("sid", _ids())
def test_slice_start_line_is_a_top_level_cut(sid):
    s = _slice(sid)
    line = _start(s)
    src = _read(SOURCES[s["prefix"]])
    in_src = _line_offsets(src, line)
    if _landed(s):
        assert not in_src, f"{sid} landed but its Start line is still in source"
        assert len(_line_offsets(_read(_target(s)), line)) == 1, (
            f"{sid} landed but its Start line is not once in {_target(s)}")
        return
    assert len(in_src) == 1, (
        f"{sid} Start line occurs {len(in_src)} times in {SOURCES[s['prefix']]}")
    head = _uncomment(src[:in_src[0]])
    depth = head.count("{") - head.count("}")
    assert depth == 0, f"{sid} Start line sits inside a block (depth {depth})"


@pytest.mark.parametrize("sid", _ids())
def test_landed_heading_matches_the_tree(sid):
    """A slice is landed when its target file exists; its heading must say
    so with `(LANDED <sha>)`, and an unlanded heading must not."""
    s = _slice(sid)
    marked = re.search(r"\(LANDED [0-9a-f]{7,40}\)", s["head"]) is not None
    assert marked == _landed(s), (
        f"{sid} heading says landed={marked} but {_target(s)} "
        f"exists={_landed(s)}")


def test_unlanded_start_lines_run_in_plan_order():
    _plan_text()
    for prefix in SOURCES:
        src = _read(SOURCES[prefix])
        offs = []
        for s in SLICES:
            if s["prefix"] == prefix and not _landed(s):
                hit = _line_offsets(src, _start(s))
                if len(hit) == 1:
                    offs.append((s["id"], hit[0]))
        assert [o for _, o in offs] == sorted(o for _, o in offs), (
            f"{prefix} Start lines are out of plan order: {offs}")


@pytest.mark.parametrize("sid", _ids())
def test_slice_anchors_sit_only_inside_the_slice(sid):
    s = _slice(sid)
    anchors = _TICKED.findall(s["fields"].get("Anchors", ""))
    assert anchors, f"{sid} names no anchor"
    src = _read(SOURCES[s["prefix"]])
    wrong = {}
    if _landed(s):
        tgt = _read(_target(s))
        for name in anchors:
            left, there = len(_class_hits(src, name)), len(_class_hits(tgt, name))
            if left or not there:
                wrong[name] = f"source {left}, target {there}"
    else:
        rng = _ranges(s["prefix"]).get(sid)
        assert rng is not None, f"{sid} has no range (Start line not found)"
        lo, hi = rng
        for name in anchors:
            hits = _class_hits(src, name)
            outside = [h for h in hits if not lo <= h < hi]
            if not hits or outside:
                wrong[name] = f"{len(hits)} hits, {len(outside)} outside"
    assert not wrong, f"{sid} anchors not confined to the slice: {wrong}"


def test_every_planned_piece_is_within_the_cap():
    _plan_text()
    sizes = {}
    for prefix, rel in SOURCES.items():
        src = _read(rel)
        assert src, f"premise: {rel} exists"
        rngs = sorted(_ranges(prefix).values())
        cuts = [0] + [lo for lo, _ in rngs] + [len(src)]
        for i in range(len(cuts) - 1):
            piece = src[cuts[i]:cuts[i + 1]]
            sizes[f"{rel} piece {i}"] = len(piece.encode("utf-8"))
    for s in SLICES:
        if _landed(s):
            sizes[_target(s)] = (ROOT / _target(s)).stat().st_size
    over = {k: v for k, v in sizes.items() if v > CAP_BYTES}
    assert not over, f"pieces over {CAP_BYTES} bytes: {over}"
    assert len(sizes) >= sum(MIN_SLICES.values()) + len(SOURCES), (
        f"premise: the cut produced pieces ({sizes})")


def test_dashboard_imports_landed_targets_in_cascade_order():
    css = DASHBOARD_CSS.read_text(encoding="utf-8")
    imports = ["web/css/" + m for m in _IMPORT.findall(css)]
    for prefix, rel in SOURCES.items():
        assert imports.count(rel) == 1, f"premise: dashboard.css imports {rel}"
        want = [rel] + [_target(s) for s in SLICES
                        if s["prefix"] == prefix and _landed(s)]
        i = imports.index(rel)
        got = imports[i:i + len(want)]
        assert got == want, (
            f"dashboard.css must import {want} on consecutive lines, got {got}")


@pytest.mark.parametrize("sid", _ids())
def test_slice_coupled_files_exist_and_name_the_code(sid):
    s = _slice(sid)
    raw = s["fields"].get("Coupled", "")
    anchors = _TICKED.findall(s["fields"].get("Anchors", ""))
    names = {Path(SOURCES[s["prefix"]]).name, Path(_target(s)).name}
    if raw.startswith("none"):
        found = [rel for rel, text in _coupling_universe()
                 if _co_mentions(text, names, anchors)]
        assert not found, f"{sid} says none but these co-mention: {found}"
        return
    coupled = _TICKED.findall(raw)
    assert coupled, f"{sid} Coupled is blank (write 'none ...' if it is)"
    bad = []
    for rel in coupled:
        p = ROOT / rel
        if not p.is_file():
            bad.append(f"{rel} (missing)")
            continue
        if not _co_mentions(p.read_text(encoding="utf-8", errors="replace"),
                            names, anchors):
            bad.append(f"{rel} (names neither {sorted(names)} with an anchor)")
    assert not bad, f"{sid} coupled list is stale: {bad}"


def _co_mentions(text, names, anchors):
    return any(n in text for n in names) and any(
        re.search(r"(?<![\w-])" + re.escape(a) + r"(?![\w-])", text)
        for a in anchors)


_UNIVERSE = []


def _coupling_universe():
    """Tracked tests/ and tools/ .py and .mjs files, plus web/js node tests."""
    if not _UNIVERSE:
        out = subprocess.run(
            ["git", "ls-files", "tests", "tools", "web/js"], cwd=ROOT,
            capture_output=True, text=True, check=True).stdout.split()
        rels = [r for r in out
                if (r.startswith(("tests/", "tools/"))
                    and r.endswith((".py", ".mjs")))
                or r.endswith(".test.mjs")]
        assert len(rels) > 500, f"premise: tracked universe ({len(rels)})"
        for rel in rels:
            p = ROOT / rel
            if p.is_file():
                _UNIVERSE.append(
                    (rel, p.read_text(encoding="utf-8", errors="replace")))
    return _UNIVERSE


def test_architecture_points_at_the_plan():
    arch = ARCH.read_text(encoding="utf-8")
    assert "docs/WEB_CSS_SPLIT_PLAN.md" in arch, (
        "docs/ARCHITECTURE.md does not point at the CSS split plan")
