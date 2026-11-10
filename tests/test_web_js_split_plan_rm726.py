"""RM-726 (d): guard that keeps the web JS split plan honest.

tests/test_web_js_split_plan_rm726.py
RM-726 (d) (s144 queue lane): web/js/main.js and web/js/panels/champ_select.js
are the two oversize dashboard scripts, and the row's acceptance is "a split
plan per file with the 5-phase UI audit per slice, before any split". The
plan is docs/WEB_JS_SPLIT_PLAN.md. This guard keeps it honest while it waits
and while it is carried out:

- every slice block names its source file, its target module, the anchor
  symbols it moves, the views its UI audit renders, and all five audit
  phases (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY);
- every anchor is DEFINED exactly once across the slice's source file and its
  target module, so the plan cannot name a symbol that does not exist, and a
  landed slice that copied a symbol instead of moving it goes red;
- every coupled file the slice names exists and still names the source or
  the target module AND one of the slice's anchors, so the re-point list
  cannot rot silently; a slice that says "none" is re-measured over the
  tracked tests, tools and web/js node tests;
- slices that share one target module (MJ-1 and CS-1) each say they land in
  the same commit as the other, because after either alone the shared
  symbols are defined twice and the once-defined check is red;
- every view is a real view id (web/js/lib/state.js VIEW_IDS) or "all";
- the enumeration cannot be empty: both files carry at least four slices and
  the plan names at least forty anchors.

Anchors are symbols, never line numbers: the files grow on every lane, and a
line-cited plan is stale on arrival.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs" / "WEB_JS_SPLIT_PLAN.md"
ARCH = ROOT / "docs" / "ARCHITECTURE.md"
STATE_JS = ROOT / "web" / "js" / "lib" / "state.js"

SOURCES = {
    "MJ": "web/js/main.js",
    "CS": "web/js/panels/champ_select.js",
}
PHASES = ("STRUCTURE", "TYPOGRAPHY", "HIT-TARGETS", "ASCII", "HIERARCHY")

_HEAD = re.compile(r"^### (MJ|CS)-(\d+)\b.*$", re.MULTILINE)
_FIELD = re.compile(r"^- (File|Target|Anchors|Coupled|Views|UI audit):(.*)$",
                    re.MULTILINE)
_TICKED = re.compile(r"`([^`]+)`")


def _plan_text():
    assert PLAN.is_file(), "docs/WEB_JS_SPLIT_PLAN.md is missing (RM-726 (d))"
    return PLAN.read_text(encoding="utf-8")


def _slices(text):
    """Split the plan into slice blocks: {"id", "prefix", "fields"}."""
    heads = list(_HEAD.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        # A block also ends at the next level-2 heading.
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
                    "prefix": m.group(1), "fields": fields, "body": body})
    return out


def _defs(src, name):
    rx = re.compile(r"(?:\bfunction\s*\*?\s*|\b(?:const|let|var)\s+)"
                    + re.escape(name) + r"\b")
    return len(rx.findall(src))


def _view_ids():
    src = STATE_JS.read_text(encoding="utf-8")
    m = re.search(r"export const VIEW_IDS = \[(.*?)\];", src, re.DOTALL)
    assert m, "premise: VIEW_IDS found in web/js/lib/state.js"
    ids = set(re.findall(r'"([a-z-]+)"', m.group(1)))
    assert len(ids) >= 10, f"premise: VIEW_IDS parsed ({len(ids)} ids)"
    return ids


SLICES = _slices(_plan_text()) if PLAN.is_file() else []


def test_plan_exists_and_names_both_files():
    text = _plan_text()
    for path in SOURCES.values():
        assert path in text, f"the plan does not name {path}"
    assert "RM-726" in text


def test_enumeration_is_not_empty():
    _plan_text()
    for prefix in SOURCES:
        n = sum(1 for s in SLICES if s["prefix"] == prefix)
        assert n >= 4, f"{prefix}: {n} slices, the plan needs at least 4"
    anchors = sum(len(_TICKED.findall(s["fields"].get("Anchors", "")))
                  for s in SLICES)
    assert anchors >= 40, f"only {anchors} anchors named across the plan"


def test_slice_ids_are_unique_and_numbered_in_order():
    _plan_text()
    for prefix in SOURCES:
        nums = [int(s["id"].split("-")[1]) for s in SLICES
                if s["prefix"] == prefix]
        assert nums == list(range(1, len(nums) + 1)), (
            f"{prefix} slices out of order or duplicated: {nums}")


def _ids():
    return [s["id"] for s in SLICES] or ["no-slices"]


@pytest.mark.parametrize("sid", _ids())
def test_slice_has_every_field(sid):
    s = {x["id"]: x for x in SLICES}.get(sid)
    assert s is not None, "the plan has no slice blocks"
    missing = [k for k in ("File", "Target", "Anchors", "Coupled", "Views",
                           "UI audit") if k not in s["fields"]]
    assert not missing, f"{sid} lacks {missing}"
    file_paths = _TICKED.findall(s["fields"]["File"])
    assert file_paths == [SOURCES[s["prefix"]]], (
        f"{sid} File must be `{SOURCES[s['prefix']]}`, got {file_paths}")
    target = _TICKED.findall(s["fields"]["Target"])
    assert len(target) == 1 and target[0].startswith("web/js/") \
        and target[0].endswith(".js"), f"{sid} Target must be one web/js module"
    assert target[0] != SOURCES[s["prefix"]], f"{sid} targets its own source"


@pytest.mark.parametrize("sid", _ids())
def test_slice_audit_names_all_five_phases(sid):
    s = {x["id"]: x for x in SLICES}.get(sid)
    assert s is not None, "the plan has no slice blocks"
    audit = s["fields"].get("UI audit", "")
    missing = [p for p in PHASES if p not in audit]
    assert not missing, f"{sid} UI audit lacks {missing}"


@pytest.mark.parametrize("sid", _ids())
def test_slice_views_are_real_view_ids(sid):
    s = {x["id"]: x for x in SLICES}.get(sid)
    assert s is not None, "the plan has no slice blocks"
    views = _TICKED.findall(s["fields"].get("Views", ""))
    assert views, f"{sid} names no view to audit"
    known = _view_ids() | {"all"}
    bad = [v for v in views if v not in known]
    assert not bad, f"{sid} names unknown views {bad}"


@pytest.mark.parametrize("sid", _ids())
def test_slice_anchors_are_defined_once_in_source_or_target(sid):
    s = {x["id"]: x for x in SLICES}.get(sid)
    assert s is not None, "the plan has no slice blocks"
    anchors = _TICKED.findall(s["fields"].get("Anchors", ""))
    assert anchors, f"{sid} names no anchor"
    src = (ROOT / SOURCES[s["prefix"]]).read_text(encoding="utf-8")
    target = ROOT / _TICKED.findall(s["fields"]["Target"])[0]
    tgt = target.read_text(encoding="utf-8") if target.is_file() else ""
    wrong = {}
    for name in anchors:
        n = _defs(src, name) + _defs(tgt, name)
        if n != 1:
            wrong[name] = n
    assert not wrong, (
        f"{sid}: anchors not defined exactly once across "
        f"{SOURCES[s['prefix']]} + {target.relative_to(ROOT).as_posix()}: "
        f"{wrong}")


@pytest.mark.parametrize("sid", _ids())
def test_slice_coupled_files_exist_and_name_the_code(sid):
    s = {x["id"]: x for x in SLICES}.get(sid)
    assert s is not None, "the plan has no slice blocks"
    raw = s["fields"].get("Coupled", "")
    anchors = _TICKED.findall(s["fields"].get("Anchors", ""))
    names = {Path(SOURCES[s["prefix"]]).name,
             Path(_TICKED.findall(s["fields"]["Target"])[0]).name}
    if raw.startswith("none"):
        # An honest empty list is spelled out, never left blank, and it is
        # re-measured: no tracked test, tool or node test may co-mention.
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
        text = p.read_text(encoding="utf-8", errors="replace")
        if not _co_mentions(text, names, anchors):
            bad.append(f"{rel} (names neither {sorted(names)} with an anchor)")
    assert not bad, f"{sid} coupled list is stale: {bad}"


def _co_mentions(text, names, anchors):
    return any(n in text for n in names) and any(
        re.search(r"\b" + re.escape(a) + r"\b", text) for a in anchors)


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


def test_slices_sharing_a_target_land_in_one_commit():
    _plan_text()
    by_target = {}
    for s in SLICES:
        tgt = _TICKED.findall(s["fields"].get("Target", ""))
        if tgt:
            by_target.setdefault(tgt[0], []).append(s)
    shared = {k: v for k, v in by_target.items() if len(v) > 1}
    assert shared, "premise: MJ-1 and CS-1 share web/js/lib/lcu_cmd.js"
    bad = []
    for tgt, group in shared.items():
        for s in group:
            others = [o["id"] for o in group if o is not s]
            body = s["body"]
            if "same commit as" not in body or not all(
                    re.search(r"\b" + re.escape(o) + r"\b", body)
                    for o in others):
                bad.append(f"{s['id']} (shares {tgt} with {others})")
    assert not bad, f"shared-target slices must say 'same commit': {bad}"


def test_architecture_points_at_the_plan():
    arch = ARCH.read_text(encoding="utf-8")
    assert "docs/WEB_JS_SPLIT_PLAN.md" in arch, (
        "docs/ARCHITECTURE.md does not point at the split plan")
