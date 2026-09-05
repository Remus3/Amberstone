# arch: derive_view's output domain must exist in the canonical JS view registry | section=tests | frozen=no
"""
tests/test_view_router_registry_rm341.py

RM-341 - every view id that ``dashboard/view_router_state.derive_view`` can
return must exist in the canonical view registry ``VIEW_IDS`` at
``web/js/lib/state.js:36``.

WHY THIS NEEDS A GUARD AT ALL. The module under guard says it in its own first
paragraph: it is a TEST MIRROR of ``_viewAutoDerive`` in ``web/js/main.js``,
nothing imports it at runtime, and "if you change one, change both". A declared
mirror with no cross-language assertion rots in exactly one direction and rots
silently. Rename or drop a view in ``web/js/lib/state.js`` and this Python
mirror keeps deriving the old id forever. Its two existing test files
(``tests/test_view_router_state.py`` and
``tests/test_view_router_postgame_pgr_arm.py``) assert transitions between
Python-side string literals and never cross the language boundary, so they stay
green while the mirror describes a router that no longer exists. The runtime
does not fail either, because the runtime never reads this module. Nothing in
the repo is positioned to notice.

WHAT THIS FILE IS NOT. It is not the row as filed. RM-341 asked for a
containment guard between the JS registry and a second ``VIEW_IDS`` tuple that
``dashboard/view_router_state.py`` used to define. That tuple was read by
NOTHING - not the module itself, not its tests, not the runtime, with no
``import *`` and no dynamic access anywhere in the tree - and it was a stale
copy of an older JS list rather than a mirror or a meaningful subset. It was
deleted in the same change that added this file. Guarding it would have pinned
a dead constant against a live one and called that a contract. The mirror's
OUTPUT DOMAIN is the part with a real consumer contract, so that is what is
guarded here.

DO NOT MERGE THIS INTO ``tests/test_web_view_registry_rm340.py``. That file
asserts the JS registry resolves against the DOM - id to mount, id to label,
menu item to id. This one asserts a Python function's range sits inside that
registry. Same array is parsed; different contract, different failure, and
neither one subsumes the other.

SUBSET, NOT EQUALITY, AND THAT IS DELIBERATE. The JS registry legitimately
carries views the auto-derive router can never select.
``web/js/lib/state.js:49`` documents ``historical-pgr`` as exactly that
("Manual-only - the auto-derive view-router never selects it; it is reached
solely via a row click"). Asserting equality would go red on every menu-only
page. MANUAL_ONLY below records that reason as an assertion rather than a
waiver.

BOTH SIDES ARE READ OFF DISK. Neither list is restated as the contract: the JS
side is parsed out of ``state.js`` and the Python side is extracted from
``derive_view``'s own AST. The one literal list in this file, KNOWN_DERIVABLE,
exists solely so a broken extractor cannot read green - a parser that silently
found zero ids would otherwise make the subset assertion vacuously true.
"""
from __future__ import annotations

import ast
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import view_router_state as mirror  # noqa: E402

MIRROR_PY = Path("dashboard/view_router_state.py")
STATE_JS = Path("web/js/lib/state.js")

# ANTI-VACUITY PIN, NOT THE CONTRACT. The five ids derive_view resolves to as
# of RM-341. The guard itself never reads this - it runs off the extractor -
# but test_extractor_finds_the_known_five compares the extractor against it, so
# a parser that silently returns an empty set fails loudly instead of passing.
KNOWN_DERIVABLE = frozenset({
    "active-match", "champ-select", "home", "last-match", "lobby",
})

# A registry id the auto-derive router is not supposed to be able to produce,
# with the file:line that makes that deliberate. Same discipline as
# MOUNT_EXCEPTIONS in the RM-340 guard: the entry asserts, it does not skip.
MANUAL_ONLY: dict[str, str] = {
    "historical-pgr": (
        "HIST2 detached historical Post Game Review. web/js/lib/state.js:49 "
        "records it as manual-only in the registry itself - the auto-derive "
        "view-router never selects it, it is reached solely via a History or "
        "Session row click. It is the standing evidence that this guard must "
        "assert containment rather than equality, so if it ever becomes "
        "derivable the direction of the assertion needs revisiting and this "
        "entry has to go."
    ),
}

# state.js is an ES module, so there is no import path from Python. Parse it.
_VIEW_IDS_BLOCK = re.compile(r"export\s+const\s+VIEW_IDS\s*=\s*\[(.*?)\]\s*;", re.S)
_QUOTED = re.compile(r'"([^"]+)"')
_LINE_COMMENT = re.compile(r"//[^\n]*")


# --------------------------------------------------------------------- parsers
def _read(root: Path, rel: Path) -> str:
    return (root / rel).read_text(encoding="utf-8", errors="replace")


def _js_view_ids(root: Path) -> list[str]:
    """The canonical registry, read out of state.js.

    Line comments are stripped first so a commented-out id can never register
    as a live one - VIEW_IDS carries an s209 note directly above it today.
    """
    text = _read(root, STATE_JS)
    match = _VIEW_IDS_BLOCK.search(text)
    assert match, (
        f"VIEW_IDS array not found in {STATE_JS.as_posix()} - the parser is "
        "broken, which would make every assertion in this file vacuous"
    )
    ids = _QUOTED.findall(_LINE_COMMENT.sub("", match.group(1)))
    assert ids, f"VIEW_IDS in {STATE_JS.as_posix()} parsed to an empty list"
    return ids


def _string_choices(node: ast.expr) -> set[str]:
    """Every string a view-id expression can evaluate to.

    Two shapes occur in derive_view today: a bare literal, and the single
    ternary at dashboard/view_router_state.py:197
    (active-match if active_match_enabled else last-match). Anything else
    raises rather than contributing nothing - an extractor that quietly skips
    a return it does not recognise is precisely how this guard would go
    vacuously green after a refactor.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _string_choices(node.body) | _string_choices(node.orelse)
    raise AssertionError(
        f"unrecognised view-id expression {type(node).__name__} at "
        f"{MIRROR_PY.as_posix()}:{getattr(node, 'lineno', '?')}. Teach "
        "_string_choices the new shape - do not let it fall through, or the "
        "ids behind it stop being guarded."
    )


def _derivable_view_ids(root: Path) -> set[str]:
    """The ids derive_view can return, extracted from its own source.

    AST rather than a regex, and every RETURN statement is inspected rather
    than every string literal in the body: derive_view is full of strings that
    are not view ids (phase names, mode names, the "in-progress" sticky value),
    and a literal scan would sweep all of them in.
    """
    tree = ast.parse(_read(root, MIRROR_PY))
    fn = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "derive_view"
        ),
        None,
    )
    assert fn is not None, (
        f"derive_view is not defined at module scope in {MIRROR_PY.as_posix()} "
        "- the extractor is broken, not the code under guard"
    )

    found: set[str] = set()
    returns = 0
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return):
            continue
        returns += 1
        call = node.value
        assert (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "DeriveResult"
        ), (
            f"return at {MIRROR_PY.as_posix()}:{node.lineno} is not a "
            "DeriveResult(...) call. Every derive_view return builds one; if "
            "that changed, update this extractor in the same commit rather "
            "than letting the new shape go unguarded."
        )
        assert call.args, (
            f"DeriveResult at {MIRROR_PY.as_posix()}:{node.lineno} is called "
            "with no positional view id"
        )
        found |= _string_choices(call.args[0])

    assert returns, (
        f"derive_view in {MIRROR_PY.as_posix()} has no return statements - "
        "the extractor found the function but read nothing out of it"
    )
    return found


def _unregistered(root: Path) -> set[str]:
    """Derivable ids the JS registry does not carry. This is the contract."""
    return _derivable_view_ids(root) - set(_js_view_ids(root))


# ------------------------------------------------- the extractor is not broken
def test_extractor_finds_the_known_five():
    """A parser that found nothing would make the subset assertion vacuous.

    This is the only assertion in the file that names ids literally, and it is
    here to falsify the extractor rather than to state the contract.
    """
    found = _derivable_view_ids(ROOT)
    assert found == set(KNOWN_DERIVABLE), (
        "the AST extractor no longer agrees with the pinned output domain of "
        f"derive_view.\n  extracted: {sorted(found)}\n  pinned:    "
        f"{sorted(KNOWN_DERIVABLE)}\nIf derive_view genuinely gained or lost a "
        "view id, update KNOWN_DERIVABLE in the same change. If it did not, "
        "the extractor is broken and the guard below is no longer proving "
        "anything."
    )


def test_static_extraction_covers_what_the_function_actually_returns():
    """Cross-check the static read against the running function.

    Drives derive_view over the full cross product of its inputs and asserts
    the observed views sit inside the statically extracted set. That is the
    direction that matters: an extractor which UNDER-reports would let a real
    derivable id escape the containment assertion entirely.
    """
    phases: list[Optional[str]] = sorted(
        set(mirror._STICKY_CLEAR_PHASES)
        | set(mirror._POSTGAME_PHASES)
        | set(mirror._DODGE_PHASES)
        | set(mirror._LOBBY_PHASES)
        | {"ChampSelect", "GameStart", "InProgress", "Zzz-unknown-phase"}
    )
    phases += [None, ""]
    modes: list[Optional[str]] = sorted(mirror.IN_GAME_MODES)
    modes += [None, "", "client", "lobby", "zzz-unknown-mode"]

    observed: set[str] = set()
    for phase in phases:
        for mode in modes:
            for prior in (None, "champ-select", "in-progress"):
                for active in (True, False):
                    for live in (True, False):
                        observed.add(
                            mirror.derive_view(
                                phase,
                                mode,
                                prior,
                                active_match_enabled=active,
                                live=live,
                            ).view
                        )

    extracted = _derivable_view_ids(ROOT)
    escaped = observed - extracted
    assert not escaped, (
        f"derive_view returned {sorted(escaped)}, which the AST extractor did "
        "not find. The guard is under-reporting, so those ids are not being "
        "checked against the JS registry at all."
    )
    assert observed == set(KNOWN_DERIVABLE), (
        "the live sweep no longer reaches the pinned five view ids: "
        f"{sorted(observed)}. Either a branch of derive_view became "
        "unreachable, or the sweep's input space no longer covers it."
    )


# --------------------------------------------------------------- the contract
def test_every_derivable_view_id_is_in_the_js_registry():
    """The mirror's output domain must resolve against the canonical registry.

    Both sides are read off disk. A view renamed or dropped in
    web/js/lib/state.js while this Python mirror keeps deriving the old id is
    invisible to every other test of this module, because they compare
    Python-side literals to Python-side literals.
    """
    unregistered = _unregistered(ROOT)
    report = "\n".join(f"  {view_id}" for view_id in sorted(unregistered))
    assert not unregistered, (
        f"{len(unregistered)} view id(s) that derive_view can return are not "
        f"in VIEW_IDS at {STATE_JS.as_posix()}. The Python mirror at "
        f"{MIRROR_PY.as_posix()} has drifted from the JS router it declares "
        "itself a mirror of, and the runtime cannot tell you - it never "
        "imports this module. Fix at the source: correct the id in "
        "derive_view, or register the view in state.js if the mirror is the "
        "one that is right.\n" + report
    )


def test_manual_only_views_are_live_and_reasoned():
    """The recorded reason for asserting subset instead of equality must hold.

    Three ways this entry rots: the id leaves the registry (dead weight), the
    id becomes derivable (the reason is now false and the direction of the
    assertion is worth revisiting), or the reason stops citing evidence.
    """
    ids = set(_js_view_ids(ROOT))
    derivable = _derivable_view_ids(ROOT)
    for view_id, reason in MANUAL_ONLY.items():
        assert view_id in ids, (
            f"MANUAL_ONLY carries {view_id!r} but it is no longer in VIEW_IDS "
            f"at {STATE_JS.as_posix()} - delete the entry rather than leaving "
            "a standing note about a view that does not exist"
        )
        assert view_id not in derivable, (
            f"MANUAL_ONLY records {view_id!r} as a view the auto-derive router "
            "never selects, but derive_view can now return it. Either the "
            "registry comment at web/js/lib/state.js:49 is stale, or this "
            "guard should be reconsidered for equality."
        )
        assert re.search(r"\.(?:js|mjs|py|html):\d+", reason), (
            f"MANUAL_ONLY reason for {view_id!r} cites no file:line. An "
            "exemption has to point at the evidence that makes it deliberate."
        )
        assert len(reason) > 80, (
            f"MANUAL_ONLY reason for {view_id!r} is too thin to audit"
        )


def test_the_dead_python_view_id_registry_stays_deleted():
    """Named pin for RM-341, so the tuple is not restored as an oversight.

    dashboard/view_router_state.py used to define its own 10-entry VIEW_IDS
    that nothing read. It was not a subset with a meaning and not a second
    registry; it was a stale copy of an older JS list. If a Python-side list is
    ever genuinely needed, derive it from _js_view_ids rather than retyping it.
    """
    tree = ast.parse(_read(ROOT, MIRROR_PY))
    module_names = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert "VIEW_IDS" not in module_names, (
        f"a module-level VIEW_IDS is back in {MIRROR_PY.as_posix()}. The "
        "canonical registry is VIEW_IDS in web/js/lib/state.js; a second copy "
        "on the Python side has no reader and drifts silently, which is what "
        "RM-341 removed. Guard the derived ids instead - this file already "
        "does."
    )


# ----------------------------------------------------- anti-vacuity, both ways
def _scratch_corpus(tmp_path: Path) -> Path:
    """A scratch copy of the two real parsed files, so the probes below run
    against the tree as it actually is rather than a toy fixture."""
    for rel in (MIRROR_PY, STATE_JS):
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


def test_guard_catches_a_bogus_derived_view_id(tmp_path):
    """A guard that cannot fail is not a guard. Plant an id no registry has."""
    root = _scratch_corpus(tmp_path)
    assert not _unregistered(root), "scratch copy is not clean to begin with"
    _patch(
        root,
        MIRROR_PY,
        'return DeriveResult("lobby", game_started)',
        'return DeriveResult("totally-bogus-view", game_started)',
    )
    assert "totally-bogus-view" in _derivable_view_ids(root), (
        "the extractor did not even see the planted id"
    )
    assert _unregistered(root) == {"totally-bogus-view"}, (
        "planting an unregistered view id in derive_view did not go red: "
        f"{_unregistered(root)}"
    )


def test_guard_catches_a_view_dropped_from_the_js_registry(tmp_path):
    """The direction the whole file exists for: the JS side moves, not this one.

    This is the silent-rot channel. Nothing else in the repo notices a view
    leaving state.js while the Python mirror keeps deriving it.
    """
    root = _scratch_corpus(tmp_path)
    assert not _unregistered(root), "scratch copy is not clean to begin with"
    _patch(
        root,
        STATE_JS,
        '"home", "lobby", "champ-select", "active-match", "last-match",',
        '"home", "champ-select", "active-match", "last-match",',
    )
    assert "lobby" not in _js_view_ids(root), "the probe did not remove lobby"
    assert _unregistered(root) == {"lobby"}, (
        "dropping a still-derivable view from the JS registry did not go red: "
        f"{_unregistered(root)}"
    )


def test_extractor_refuses_an_unrecognised_return_shape(tmp_path):
    """A silently-skipped return is how this guard would rot into a no-op.

    An extractor that shrugged at a shape it did not know would keep passing
    while the ids behind that return went unchecked, which is worse than the
    drift it exists to catch.
    """
    root = _scratch_corpus(tmp_path)
    _patch(
        root,
        MIRROR_PY,
        'return DeriveResult("lobby", game_started)',
        "return _some_helper(game_started)",
    )
    with pytest.raises(AssertionError, match="not a DeriveResult"):
        _derivable_view_ids(root)
