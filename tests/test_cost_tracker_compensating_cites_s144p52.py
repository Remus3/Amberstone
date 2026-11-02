"""RM-1296 - the compensating sites' own cites into core/cost_tracker.py
and core/polled_json.py name the symbol, not the line.

Two comments explain why a handler is left broad, or narrowed to an exact
type set, by pointing at the callee's raise surface by line:

  coaches/_base_coach.py  BaseCoach._vision_loop (the "vision" spend-gate
                          LEFT BROAD comment) and BaseCoach._maybe_coach (the
                          daily-budget LEFT BROAD comment)
  core/cost_tracker.py    CostTracker.note_match_boundary (the enumerated
                          raise surface above its narrowed handler)

What the cites meant, in the tree each was written against:

  at 649c35d4d^ (parent of the silent no-op handler program, which wrote
  the LEFT BROAD and "Narrowed 2026-07-19" comments; it changed no line of
  core/cost_tracker.py above the comment it wrote):
    core/cost_tracker.py:218-222 -> CostTracker.__init__, its spend_dir
                                    mkdir through float(vision_burst)
    coach_disabled (:423-425)    -> CostTracker.coach_disabled, def + body
    core/cost_tracker.py:336-340 -> CostTracker.allow_call, def + body
    _purpose_to_gate (:165)      -> the module-level def _purpose_to_gate
    GATE_META literal (:134-158) -> the GATE_META dict literal, open to close
    CostTracker.__init__ (:218-222) -> as the first row above
  at e5ec9ee24 (lane 8 cycle 24, which rewrote the two polled_json cites in
  the note_match_boundary comment while it grew core/polled_json.py):
    core/polled_json.py:139-174  -> meant read_json_dict, but that commit's
                                    own tree puts line 139 inside the
                                    atomic_write_text docstring
    core/polled_json.py:104-116  -> meant atomic_write_json, but line 104 is
                                    the _replace_with_retry call inside
                                    _write_then_replace
  Both were STALE ON LANDING by exactly 9 lines: read_json_dict starts at
  148 and atomic_write_json at 113 in that commit's tree.

When this guard was written every cost_tracker cite had drifted 12 lines (the
__init__ mkdir was 230, coach_disabled 435, allow_call 348, _purpose_to_gate
177, GATE_META 146), and the polled_json ones sat 39 / 39 lines off. RM-1305
has since removed the float(vision_burst) half of the __init__ raise surface.

This guard pins:

(a) no cost_tracker.py / polled_json.py line cite, and no bare "(:<n>)"
    shorthand cite, in the two citers;
(b) every named symbol still exists and still carries what the prose says,
    _purpose_to_gate holds no raise statement and every GATE_META entry
    still has "purposes";
(c) each citer names its symbols in a COMMENT or STRING token;
(d) at 649c35d4d^ every old cost_tracker cite landed inside the symbol
    named for it, and at e5ec9ee24 both old polled_json cites missed theirs
    by exactly 9 lines (a commit absent from the clone FAILS:
    tests/test_ci_checkout_history_depth.py keeps these on full clones, and a
    shallow skip would hide on every CI run).

Other-family cites in the same two files are out of scope on purpose: the
_base_coach.py cites into core/hotkeys.py (register_coach) and
core/coach_trace.py stay for a later sweep.
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TRACKER = "core/cost_tracker.py"
POLLED = "core/polled_json.py"
DCLASS_PARENT = "649c35d4d^"
CYCLE24 = "e5ec9ee24"
STALE_BY = 9

# Each citer and the symbol names its prose must carry.
CITERS = {
    "coaches/_base_coach.py": ("core.cost_tracker.CostTracker.__init__",
                               "CostTracker.coach_disabled",
                               "core.cost_tracker.CostTracker.allow_call"),
    "core/cost_tracker.py": ("core.polled_json.read_json_dict",
                             "core.polled_json.atomic_write_json",
                             "_purpose_to_gate", "GATE_META",
                             "CostTracker.__init__"),
}

# A cost_tracker.py / polled_json.py line cite, or a bare "(:<n>)" /
# "(:<n>-<n>," shorthand that leans on an earlier cite's file. A cite into
# another module keeps its own "<name>.py:" prefix inside the parenthesis,
# and a port such as "(:8889 with" is followed by a space, so both are left
# alone.
BANNED = re.compile(r"\b(?:cost_tracker|polled_json)\.py:\d|\(:\d+(?:-\d+)?[),]")

# (file, qualified symbol, text its source must carry; whitespace is
# collapsed on both sides before the compare)
HOLDS = (
    (TRACKER, "CostTracker.__init__",
     "self._spend_dir.mkdir(parents=True, exist_ok=True)"),
    (TRACKER, "CostTracker.coach_disabled", "{str(m).lower() for m in modes}"),
    (TRACKER, "CostTracker.gate_disabled", "return self.coach_disabled(gate)"),
    (TRACKER, "CostTracker.allow_call",
     'self.daily_spend().get("total_usd", 0.0) < budget'),
    (TRACKER, "CostTracker.note_match_boundary",
     "except (OSError, TypeError, ValueError, AttributeError)"),
    (TRACKER, "_purpose_to_gate", 'meta["purposes"]'),
    (POLLED, "read_json_dict", "except OSError"),
    (POLLED, "read_json_dict", "except UnicodeDecodeError"),
    (POLLED, "read_json_dict", "except json.JSONDecodeError"),
    (POLLED, "atomic_write_json", "json.dumps("),
    (POLLED, "atomic_write_json", "_write_then_replace("),
)

# (old line in core/cost_tracker.py at DCLASS_PARENT, qualified symbol it
# sat in, text on that line)
OLD_TRACKER_CITES = (
    (218, "CostTracker.__init__", "self._spend_dir.mkdir("),
    (222, "CostTracker.__init__", "CFG_VISION_BURST"),
    (423, "CostTracker.coach_disabled", "def coach_disabled"),
    (425, "CostTracker.coach_disabled", "for m in modes"),
    (336, "CostTracker.allow_call", "def allow_call"),
    (340, "CostTracker.allow_call", '"total_usd"'),
    (165, "_purpose_to_gate", "def _purpose_to_gate"),
    (134, "GATE_META", "GATE_META = {"),
    (158, "GATE_META", "}"),
)

# (old first cited line in core/polled_json.py at CYCLE24, the symbol the
# prose meant, the symbol that line really sat in at that tree)
OLD_POLLED_CITES = (
    (139, "read_json_dict", "atomic_write_text"),
    (104, "atomic_write_json", "_write_then_replace"),
)


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _prose(rel: str) -> str:
    toks = tokenize.generate_tokens(io.StringIO(_src(rel)).readline)
    return "\n".join(t.string for t in toks
                     if t.type in (tokenize.COMMENT, tokenize.STRING))


def _node(src: str, rel: str, qual: str) -> ast.AST:
    node: ast.AST = ast.parse(src)
    for part in qual.split("."):
        found = [c for c in ast.iter_child_nodes(node)
                 if (isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef,
                                    ast.ClassDef)) and c.name == part)
                 or (isinstance(c, ast.Assign) and any(
                     isinstance(t, ast.Name) and t.id == part
                     for t in c.targets))]
        if not found:
            raise AssertionError(f"{rel}: {qual} not found - the "
                                 "compensating prose names it (RM-1296)")
        node = found[0]
    return node


def _have(rev: str) -> bool:
    probe = subprocess.run(["git", "cat-file", "-e", f"{rev}^{{commit}}"],
                           cwd=ROOT, capture_output=True)
    return probe.returncode == 0


def _git_show(spec: str) -> str:
    out = subprocess.run(["git", "show", spec], cwd=ROOT,
                         capture_output=True, check=True)
    return out.stdout.decode("utf-8")


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_carries_no_tracker_or_polled_line_cite(rel):
    hits = [(n, line.strip()) for n, line in enumerate(_src(rel).splitlines(), 1)
            if BANNED.search(line)]
    assert not hits, (
        f"{rel} cites core/cost_tracker.py or core/polled_json.py by line "
        f"again; cite the symbol (RM-1296): {hits}")


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_names_its_symbols_in_prose(rel):
    prose = " ".join(_prose(rel).split())
    missing = [s for s in CITERS[rel] if s not in prose]
    assert not missing, (
        f"{rel}: the compensating prose no longer names {missing} in a "
        "comment or docstring (RM-1296)")


@pytest.mark.parametrize(("rel", "qual", "text"), HOLDS,
                         ids=[f"{q}:{t[:24]}" for _, q, t in HOLDS])
def test_named_symbol_holds(rel, qual, text):
    src = _src(rel)
    seg = ast.get_source_segment(src, _node(src, rel, qual)) or ""
    assert " ".join(text.split()) in " ".join(seg.split()), (
        f"{rel} {qual} no longer carries {text!r}; re-word the compensating "
        "prose that names it (RM-1296)")


def test_purpose_to_gate_cannot_raise():
    # note_match_boundary's comment says _purpose_to_gate cannot raise
    # because it is pure str/dict work and every GATE_META entry has
    # "purposes". A raise statement, or an entry without the key (a KeyError
    # at meta["purposes"]), makes that comment wrong while the text checks
    # above still match.
    src = _src(TRACKER)
    raises = [n.lineno for n in ast.walk(_node(src, TRACKER, "_purpose_to_gate"))
              if isinstance(n, ast.Raise)]
    assert not raises, (
        f"{TRACKER} _purpose_to_gate now raises (lines {raises}); re-check "
        "the note_match_boundary raise-surface comment (RM-1296)")
    meta = ast.literal_eval(_node(src, TRACKER, "GATE_META").value)
    bare = sorted(g for g, m in meta.items() if "purposes" not in m)
    assert meta and not bare, (
        f"{TRACKER} GATE_META entries {bare} lack 'purposes'; "
        "_purpose_to_gate can now raise KeyError (RM-1296)")


def test_banned_pattern_still_bites():
    for sample in ("core/cost_tracker.py:218-222", "(core/cost_tracker.py:336)",
                   "read_json_dict (core/polled_json.py:139-174) swallows",
                   "coach_disabled (:423-425) builds",
                   "_purpose_to_gate (:165) is pure",
                   "literal (:134-158, every entry"):
        assert BANNED.search(sample), sample
    for other in ("register_coach (core/hotkeys.py:24-28) is",
                  "(core/coach_trace.py:65-77) runs", "core/cost_tracker.py",
                  "core.polled_json.read_json_dict", "body[:40]",
                  "(:8889 with", "1:55-2:00"):
        assert not BANNED.search(other), other


@pytest.mark.parametrize(("line", "qual", "text"), OLD_TRACKER_CITES,
                         ids=[f"{TRACKER}:{n}" for n, _, _ in OLD_TRACKER_CITES])
def test_old_tracker_cite_meant_the_named_symbol(line, qual, text):
    assert _have(DCLASS_PARENT), f"{DCLASS_PARENT} absent from this clone"
    src = _git_show(f"{DCLASS_PARENT}:{TRACKER}")
    node = _node(src, TRACKER, qual)
    assert node.lineno <= line <= node.end_lineno, (
        f"{TRACKER}:{line} at {DCLASS_PARENT} is outside {qual} "
        f"({node.lineno}-{node.end_lineno})")
    assert text in src.splitlines()[line - 1], (
        f"{TRACKER}:{line} at {DCLASS_PARENT} does not carry {text!r}")


@pytest.mark.parametrize(("line", "meant", "really"), OLD_POLLED_CITES,
                         ids=[f"{POLLED}:{n}" for n, _, _ in OLD_POLLED_CITES])
def test_old_polled_cite_was_stale_on_landing(line, meant, really):
    assert _have(CYCLE24), f"{CYCLE24} absent from this clone"
    src = _git_show(f"{CYCLE24}:{POLLED}")
    hit = _node(src, POLLED, really)
    assert hit.lineno <= line <= hit.end_lineno, (
        f"{POLLED}:{line} at {CYCLE24} is not inside {really} "
        f"({hit.lineno}-{hit.end_lineno})")
    assert _node(src, POLLED, meant).lineno == line + STALE_BY, (
        f"{POLLED} {meant} at {CYCLE24} does not start {STALE_BY} lines "
        f"below the old cite {line}")
