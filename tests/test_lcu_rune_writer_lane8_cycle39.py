"""Lane 8 cycle 39 - lcu/lcu_rune_writer.py deep audit.

THE DEFECT. `build_perk_ids` (lcu/lcu_rune_writer.py:150) silently SUBSTITUTES
the secondary tree when a caller hands it primary == secondary:

    if primary_tree == secondary_tree:
        _log.warning("Primary and secondary trees are the same (%r) - using
                      Resolve as secondary", secondary_tree)
        secondary_tree = "Resolve" if primary_tree != "Resolve" else "Precision"

It then returns perk ids drawn from the SUBSTITUTED tree - but the substitution
is private. It is not returned, not recorded, and not observable in any way.

FOUR call sites therefore re-derive the LCU `subStyleId` themselves, from the
ORIGINAL name, with a bare `_TREES.get(secondary, 0)`:

    lcu/lcu_rune_writer.py:_apply_runes             sec_id = _TREES.get(secondary_tree, 0)
    dashboard/routes_sr_draft.py:_build_rune_cmd    sub_id = _TREES.get(secondary, 0)
    dashboard/routes_loadout.py:_resolve_user_build sub_id = _TREES.get(secondary, 0)
    coaches/loadout_resolver.py:resolve             sub_id = _TREES.get(secondary, 0)

A FIFTH site fails differently and must not be described as the same mechanism
(an earlier draft of this docstring did, and the verifier refuted it):
`coaches/rune_pages.py:resolve_page` computes no style id at all - it contains
no `_TREES` reference at HEAD - and instead ECHOES the requested
`"secondary": secondary` name into the page model the UI renders, beside perk
ids drawn from the substituted tree. Same root cause, different symptom: the
substitution is invisible, so whatever each consumer derives independently is
derived from the wrong name.

MEASURED, not inferred - build_perk_ids('Conqueror', 'Precision', 'Precision'):

    perk_ids            [8010, 9111, 9104, 8014, 8473, 8453, 5005, 5008, 5001]
    perk_ids[4:6]       [8473, 8453]   <- Bone Plating + Revitalize, RESOLVE runes
    caller subStyleId   8000           <- Precision, the un-substituted name

So the page POSTed to /lol-perks/v1/pages carries subStyleId == primaryStyleId
(which League rejects outright) AND two Resolve perks sitting in a Precision
sub-tree. Malformed on two independent counts.

WHY IT MATTERS. `_write_page` (:1008-1027) DELETES the existing RC-managed
pages BEFORE it POSTs the replacement. A rejected POST is retried three times
and then abandoned, so the operator is left with NO RC rune page at all - and
the only log line about the tree collision is that `_log.warning` above, which
reads as though the correction succeeded. It says "using Resolve as secondary"
while half the payload still says Precision.

REACHABILITY. The two shipped recommendation files are clean - measured, 164
ARAM rows and 24 SR rows, ZERO with primary == secondary. The reachable paths
are the operator-authored ones: `routes_sr_draft._build_rune_cmd` reads the
tree names straight out of an HTTP POST body, and `routes_loadout` /
`loadout_resolver` read them out of user-curated builds. This is dimension 4f
(merely WRONG input), not 4b (abuse).

THE FIX is root-cause-first, not per-caller: one shared primitive,
`resolve_tree_ids`, owns the substitution rule, `build_perk_ids` is rewritten
to call it so there is exactly ONE rule rather than two copies, the four
style-id sites resolve through it instead of reaching into _TREES, and
`resolve_page` reports the tree the perks actually came from.
"""
from __future__ import annotations

import threading

import pytest

from lcu.lcu_rune_writer import (_SECONDARY_PICKS, _TREES, RuneWriter,
                                 build_perk_ids, resolve_tree_ids)

# The perk-id slots build_perk_ids fills from the SECONDARY tree.
_SECONDARY_SLOTS = slice(4, 6)


def _perks_of(tree: str) -> list[int]:
    return list(_SECONDARY_PICKS[tree])


# ---------------------------------------------------------------------------
# Characterization - pin what build_perk_ids actually does today.
# ---------------------------------------------------------------------------

def test_build_perk_ids_substitutes_resolve_when_trees_collide():
    """Characterization. The substitution itself is CORRECT and stays."""
    ids = build_perk_ids("Conqueror", "Precision", "Precision", is_aram=False)
    assert ids is not None
    assert ids[_SECONDARY_SLOTS] == _perks_of("Resolve")


def test_build_perk_ids_substitutes_precision_when_both_are_resolve():
    """The other arm of the substitution: Resolve/Resolve falls to Precision."""
    ids = build_perk_ids("Grasp of the Undying", "Resolve", "Resolve", is_aram=False)
    assert ids is not None
    assert ids[_SECONDARY_SLOTS] == _perks_of("Precision")


def test_build_perk_ids_leaves_distinct_trees_alone():
    """Guard the common path: no substitution when the trees already differ."""
    ids = build_perk_ids("Conqueror", "Precision", "Domination", is_aram=False)
    assert ids is not None
    assert ids[_SECONDARY_SLOTS] == _perks_of("Domination")


# ---------------------------------------------------------------------------
# The new primitive - one owner for the substitution rule.
# ---------------------------------------------------------------------------

def test_resolve_tree_ids_agrees_with_build_perk_ids_on_collision():
    """The whole point: the style ids must describe the perks that shipped."""
    pri_id, sub_id = resolve_tree_ids("Precision", "Precision")
    ids = build_perk_ids("Conqueror", "Precision", "Precision", is_aram=False)
    assert pri_id == _TREES["Precision"]
    assert sub_id == _TREES["Resolve"], "subStyleId must name the SUBSTITUTED tree"
    assert sub_id != pri_id, "League rejects a page whose subStyle equals its primary"
    assert ids[_SECONDARY_SLOTS] == _perks_of("Resolve")


def test_resolve_tree_ids_passes_distinct_trees_through():
    assert resolve_tree_ids("Precision", "Domination") == (
        _TREES["Precision"], _TREES["Domination"])


def test_resolve_tree_ids_rejects_unknown_names():
    """Unknown names resolve to (0, 0) so the existing `if not sub_id` guards
    at every call site keep rejecting them exactly as they do today."""
    assert resolve_tree_ids("Nonsense", "Domination") == (0, _TREES["Domination"])
    assert resolve_tree_ids("Precision", "Nonsense") == (_TREES["Precision"], 0)
    assert resolve_tree_ids("", "") == (0, 0)


@pytest.mark.parametrize("tree", sorted(_TREES))
def test_resolve_tree_ids_never_returns_a_collision(tree):
    """Exhaustive over all five trees: a same-tree request never yields a page
    whose subStyleId equals its primaryStyleId."""
    pri_id, sub_id = resolve_tree_ids(tree, tree)
    assert pri_id and sub_id
    assert pri_id != sub_id


@pytest.mark.parametrize("tree", sorted(_TREES))
def test_style_ids_and_perks_agree_for_every_collision(tree):
    """The invariant, over every tree: whatever subStyleId comes back, the
    secondary perk ids must be that tree's picks."""
    _, sub_id = resolve_tree_ids(tree, tree)
    keystone = next(k for k, v in _TREES.items() if v == sub_id)
    ids = build_perk_ids(_a_keystone_of(tree), tree, tree, is_aram=False)
    assert ids is not None
    assert ids[_SECONDARY_SLOTS] == _perks_of(keystone)


def _a_keystone_of(tree: str) -> str:
    """Any keystone belonging to `tree` - build_perk_ids needs a real one."""
    from lcu.lcu_rune_writer import _PRIMARY_ROWS
    per_tree = {
        "Precision": "Conqueror",
        "Domination": "Electrocute",
        "Sorcery": "Summon Aery",
        "Resolve": "Grasp of the Undying",
        "Inspiration": "Glacial Augment",
    }
    assert tree in _PRIMARY_ROWS
    return per_tree[tree]


# ---------------------------------------------------------------------------
# Call site 1 - RuneWriter._apply_runes (the live champ-select writer).
# ---------------------------------------------------------------------------

def _writer_capturing_pages():
    """A RuneWriter with every LCU touch stubbed, capturing _write_page args."""
    w = RuneWriter.__new__(RuneWriter)   # skip __init__ (no LCU, no ddragon read)
    w._lcu = None
    w._stop_event = threading.Event()
    w._champ_id_map = {}
    w.written = []

    def _write(name, primary_style_id, sub_style_id, selected_perk_ids):
        w.written.append({
            "name": name,
            "primary_style_id": primary_style_id,
            "sub_style_id": sub_style_id,
            "perk_ids": list(selected_perk_ids),
        })
        return True

    w._write_page = _write
    return w


def test_apply_runes_never_posts_substyle_equal_to_primary(monkeypatch):
    """The live path. A recommendation whose trees collide must NOT produce a
    page with subStyleId == primaryStyleId."""
    monkeypatch.setattr("lcu.lcu_rune_writer.load_rune_rec",
                        lambda champion, mode: ("Conqueror", "Precision", "Precision"))
    w = _writer_capturing_pages()
    assert w._apply_runes("Jinx", "CLASSIC") is True
    page = w.written[0]
    assert page["sub_style_id"] != page["primary_style_id"]


def test_apply_runes_substyle_names_the_tree_its_perks_came_from(monkeypatch):
    monkeypatch.setattr("lcu.lcu_rune_writer.load_rune_rec",
                        lambda champion, mode: ("Conqueror", "Precision", "Precision"))
    w = _writer_capturing_pages()
    w._apply_runes("Jinx", "CLASSIC")
    page = w.written[0]
    assert page["sub_style_id"] == _TREES["Resolve"]
    assert page["perk_ids"][_SECONDARY_SLOTS] == _perks_of("Resolve")


def test_apply_runes_unchanged_for_a_normal_recommendation(monkeypatch):
    """Regression fence: the ordinary path must be byte-identical to before."""
    monkeypatch.setattr("lcu.lcu_rune_writer.load_rune_rec",
                        lambda champion, mode: ("Lethal Tempo", "Precision", "Domination"))
    w = _writer_capturing_pages()
    w._apply_runes("Jinx", "CLASSIC")
    page = w.written[0]
    assert page["primary_style_id"] == _TREES["Precision"]
    assert page["sub_style_id"] == _TREES["Domination"]
    assert page["perk_ids"][_SECONDARY_SLOTS] == _perks_of("Domination")
    assert page["name"] == "RC: Jinx SR"


# ---------------------------------------------------------------------------
# Call site 2 - dashboard/routes_sr_draft._build_rune_cmd (reads a POST body).
# ---------------------------------------------------------------------------

def test_sr_draft_rune_cmd_style_ids_match_its_perks():
    from dashboard.routes_sr_draft import _build_rune_cmd
    cmd = _build_rune_cmd("Jinx", "poke", {
        "keystone": "Conqueror", "primary": "Precision", "secondary": "Precision"})
    assert cmd is not None
    assert cmd["sub_id"] != cmd["primary_id"]
    assert cmd["sub_id"] == _TREES["Resolve"]
    assert cmd["perk_ids"][_SECONDARY_SLOTS] == _perks_of("Resolve")


def test_sr_draft_rune_cmd_unchanged_for_distinct_trees():
    from dashboard.routes_sr_draft import _build_rune_cmd
    cmd = _build_rune_cmd("Jinx", "poke", {
        "keystone": "Conqueror", "primary": "Precision", "secondary": "Domination"})
    assert cmd is not None
    assert cmd["primary_id"] == _TREES["Precision"]
    assert cmd["sub_id"] == _TREES["Domination"]


def test_sr_draft_rune_cmd_still_rejects_unknown_trees():
    from dashboard.routes_sr_draft import _build_rune_cmd
    assert _build_rune_cmd("Jinx", "poke", {
        "keystone": "Conqueror", "primary": "Nonsense", "secondary": "Domination"}) is None


# ---------------------------------------------------------------------------
# Call site 3 - coaches/loadout_resolver.resolve (user-curated builds).
# ---------------------------------------------------------------------------

def test_loadout_resolver_rune_cmd_style_ids_match_its_perks(monkeypatch):
    import coaches.loadout_resolver as lr

    # Shape verified against coaches/loadout_resolver.py:377 (`.get("champions")`)
    # and :400 (the variant must list the mode) - not assumed.
    monkeypatch.setattr(lr, "_load_loadouts", lambda: {"champions": {"Jinx": {
        "variants": {"poke": {
            "modes": ["sr"],
            "runes": {"keystone": "Conqueror",
                      "primary": "Precision",
                      "secondary": "Precision"},
            "items": []}}}}})
    out = lr.resolve("Jinx", "poke", "sr")
    cmd = out.get("rune_cmd")
    assert cmd is not None, "resolve() produced no rune_cmd"
    assert cmd["sub_id"] != cmd["primary_id"]
    assert cmd["perk_ids"][_SECONDARY_SLOTS] == _perks_of("Resolve")


# ---------------------------------------------------------------------------
# Call site 4 - coaches/rune_pages.resolve_page (the model the UI renders).
# ---------------------------------------------------------------------------

def test_rune_pages_model_reports_the_tree_it_actually_used():
    """The page model echoed the REQUESTED secondary, so the UI showed a tree
    whose runes were not in the page. It must report the resolved one."""
    from coaches.rune_pages import resolve_page
    page = resolve_page("Conqueror", "Precision", "Precision", is_aram=False)
    assert page is not None
    assert page["secondary"] == "Resolve"
    assert page["perk_ids"][_SECONDARY_SLOTS] == _perks_of("Resolve")


def test_rune_pages_model_unchanged_for_distinct_trees():
    from coaches.rune_pages import resolve_page
    page = resolve_page("Conqueror", "Precision", "Domination", is_aram=False)
    assert page is not None
    assert page["primary"] == "Precision"
    assert page["secondary"] == "Domination"


# ---------------------------------------------------------------------------
# Dimension 4a - prove the module docstring's safety claim by test.
# "Manages only pages prefixed 'RC: ' - never touches user-created pages."
# ---------------------------------------------------------------------------

class _RecordingLcu:
    """Captures every _request the writer issues, answers a fixed page list."""

    def __init__(self, pages):
        self._pages = pages
        self.requests = []

    def get_all_rune_pages(self):
        return self._pages

    def _request(self, method, path, data=None):
        self.requests.append((method, path, data))
        if method == "POST":
            return {"id": 999}
        return {}

    def deleted_ids(self):
        return [p.rsplit("/", 1)[-1]
                for m, p, _ in self.requests
                if m == "DELETE" and p.startswith("/lol-perks/v1/pages/")]


def _writer_with(lcu):
    w = RuneWriter.__new__(RuneWriter)
    w._lcu = lcu
    w._stop_event = threading.Event()
    w._champ_id_map = {}
    return w


def test_write_page_deletes_only_rc_prefixed_pages():
    lcu = _RecordingLcu([
        {"id": 1, "name": "My Jinx Page", "isDeletable": True},
        {"id": 2, "name": "RC: Jinx SR", "isDeletable": True},
        {"id": 3, "name": "Sivir - ranked", "isDeletable": True},
        {"id": 4, "name": "rc: lowercase decoy", "isDeletable": True},
        {"id": 5, "name": "Not RC: prefixed", "isDeletable": True},
    ])
    _writer_with(lcu)._write_page("RC: Jinx SR", 8000, 8100, [1] * 9)
    assert lcu.deleted_ids() == ["2"], "only the RC-prefixed page may be deleted"


def test_write_page_honours_is_deletable():
    """A page League marks non-deletable is never targeted, prefix or not."""
    lcu = _RecordingLcu([
        {"id": 7, "name": "RC: Jinx SR", "isDeletable": False},
    ])
    _writer_with(lcu)._write_page("RC: Jinx SR", 8000, 8100, [1] * 9)
    assert lcu.deleted_ids() == []


def test_write_page_survives_a_malformed_page_list():
    """The LCU list is untrusted input: non-dict rows, missing keys, wrong
    types. None of it may crash the writer or misfire a delete."""
    lcu = _RecordingLcu([
        None,
        "not-a-dict",
        42,
        {},                                      # no name, no isDeletable
        {"name": None, "isDeletable": True},     # name is null
        {"name": 12345, "isDeletable": True},    # name is a number
        {"name": "RC: Jinx SR", "isDeletable": True},   # no id
        {"id": 0, "name": "RC: Jinx SR", "isDeletable": True},  # falsy id
    ])
    assert _writer_with(lcu)._write_page("RC: Jinx SR", 8000, 8100, [1] * 9) is True
    assert lcu.deleted_ids() == []


# ---------------------------------------------------------------------------
# Call site 5 - dashboard/routes_loadout._resolve_user_build.
#
# ADDED BY THE MUTATION HARNESS, not by inspection. Reverting this call site to
# the pre-fix `_TREES.get(secondary, 0)` left the whole suite GREEN, because
# nothing exercised it - the exact "guard on a non-default call path is
# UNTESTED" class. The mutant is killed only with the test below.
# ---------------------------------------------------------------------------

def test_routes_loadout_user_build_style_ids_match_its_perks(monkeypatch):
    import coaches.sr_user_builds as sub
    import dashboard.routes_loadout as rl

    build = {
        "id": "u1",
        "label": "collide",
        "items": ["Infinity Edge"],
        "runes": {"keystone": "Conqueror",
                  "primary": "Precision",
                  "secondary": "Precision"},
    }
    monkeypatch.setattr(sub, "list_for", lambda champion: [build])
    monkeypatch.setattr(sub, "format_for_display", lambda rec, **kw: {
        "label": "collide",
        "runes": rec["runes"],
        "item_ids": ["3031"],
    })

    out = rl._resolve_user_build("Jinx", "userbuild_u1", "sr", None)
    cmd = out.get("rune_cmd")
    assert cmd is not None, "no rune_cmd produced"
    assert cmd["sub_id"] != cmd["primary_id"]
    assert cmd["sub_id"] == _TREES["Resolve"]
    assert cmd["perk_ids"][_SECONDARY_SLOTS] == _perks_of("Resolve")


def test_routes_loadout_user_build_unchanged_for_distinct_trees(monkeypatch):
    import coaches.sr_user_builds as sub
    import dashboard.routes_loadout as rl

    build = {"id": "u2", "label": "normal", "items": ["Infinity Edge"],
             "runes": {"keystone": "Conqueror", "primary": "Precision",
                       "secondary": "Domination"}}
    monkeypatch.setattr(sub, "list_for", lambda champion: [build])
    monkeypatch.setattr(sub, "format_for_display", lambda rec, **kw: {
        "label": "normal", "runes": rec["runes"], "item_ids": ["3031"]})

    cmd = rl._resolve_user_build("Jinx", "userbuild_u2", "sr", None).get("rune_cmd")
    assert cmd is not None
    assert cmd["primary_id"] == _TREES["Precision"]
    assert cmd["sub_id"] == _TREES["Domination"]


# ---------------------------------------------------------------------------
# Dimension 4d / 4f - RC_RUNEWRITER_POLL_SEC was read straight into a class
# attribute with no validation:
#
#     POLL_INTERVAL = float(os.environ.get("RC_RUNEWRITER_POLL_SEC", "1.0"))
#
# MEASURED, both arms:
#   RC_RUNEWRITER_POLL_SEC=0    -> POLL_INTERVAL 0.0, and _stop_event.wait(0.0)
#                                  returns instantly: 2000 waits in 0.0011s. The
#                                  poll becomes an unbounded spin issuing LCU
#                                  HTTP requests as fast as the client answers.
#   RC_RUNEWRITER_POLL_SEC=abc  -> ValueError at MODULE IMPORT. main.py catches
#                                  it as "RuneWriter init failed", so rune
#                                  auto-apply is silently off, and the same
#                                  import failure breaks coaches/rune_pages.py,
#                                  coaches/loadout_resolver.py,
#                                  dashboard/routes_loadout.py and
#                                  dashboard/routes_sr_draft.py.
#
# A FLOOR is applied rather than a ceiling: a deliberate slow poll is the
# operator's business, an unbounded spin against the League client is not.
# ---------------------------------------------------------------------------

def _reload_with(monkeypatch, value):
    import importlib

    import lcu.lcu_rune_writer as m
    if value is None:
        monkeypatch.delenv("RC_RUNEWRITER_POLL_SEC", raising=False)
    else:
        monkeypatch.setenv("RC_RUNEWRITER_POLL_SEC", value)
    return importlib.reload(m)


@pytest.fixture(autouse=False)
def _restore_module():
    yield
    import importlib

    import lcu.lcu_rune_writer as m
    importlib.reload(m)


def test_poll_interval_default_is_one_second(monkeypatch, _restore_module):
    assert _reload_with(monkeypatch, None).RuneWriter.POLL_INTERVAL == 1.0


def test_poll_interval_honours_a_sane_override(monkeypatch, _restore_module):
    assert _reload_with(monkeypatch, "2.5").RuneWriter.POLL_INTERVAL == 2.5


@pytest.mark.parametrize("value", ["0", "0.0", "-1", "-0.5", "0.0001"])
def test_poll_interval_never_spins_the_lcu(monkeypatch, _restore_module, value):
    """Zero, negative and absurdly small values must not produce a hot loop."""
    m = _reload_with(monkeypatch, value)
    assert m.RuneWriter.POLL_INTERVAL >= m._MIN_POLL_INTERVAL > 0


@pytest.mark.parametrize("value", ["abc", "", "1.0.0", "nan-ish", "1,0"])
def test_poll_interval_bad_value_does_not_break_module_import(
        monkeypatch, _restore_module, value):
    """An unparseable value must fall back, not raise at import - the import
    failure took four other modules down with it."""
    m = _reload_with(monkeypatch, value)
    assert m.RuneWriter.POLL_INTERVAL == 1.0


def test_poll_interval_rejects_nan_and_inf(monkeypatch, _restore_module):
    """float() accepts 'nan' and 'inf'. nan fails every comparison, so a naive
    floor check lets it through; inf would wedge the loop until process exit."""
    assert _reload_with(monkeypatch, "nan").RuneWriter.POLL_INTERVAL == 1.0
    assert _reload_with(monkeypatch, "inf").RuneWriter.POLL_INTERVAL == 1.0


# ---------------------------------------------------------------------------
# MUTATION LEDGER for this file. 13 mutants, 12 killed, 1 proven EQUIVALENT.
#
#   M1  substitution neutered (returns the colliding tree)          KILLED
#   M2  resolve_tree_ids reverted to the bare _TREES.get            KILLED
#   M3  _apply_runes reverted to the pre-fix derivation             KILLED
#   M4  routes_sr_draft reverted                                    KILLED
#   M5  routes_loadout reverted                    SURVIVED -> then KILLED
#   M6  loadout_resolver reverted                                   KILLED
#   M7  rune_pages echoes the requested tree again                  KILLED
#   M8  isDeletable guard deleted from the DELETE path              KILLED
#   M9  RC-prefix guard deleted from the DELETE path                KILLED
#   M10 nan/inf guard deleted                                       KILLED
#   M11 floor clamp deleted                                         KILLED
#   M12 unparseable-value fallback narrowed to TypeError            KILLED
#   M13 POLL_INTERVAL class attribute reverted to the pre-fix line  KILLED
#   M14 empty-string arm removed                              EQUIVALENT
#
# M5 is the one worth reading. Reverting dashboard/routes_loadout.py to the
# pre-fix `_TREES.get(secondary, 0)` left the ENTIRE suite green, because
# nothing exercised that call site - the "guard on a non-default call path is
# UNTESTED" class. The two routes_loadout tests above exist only because the
# mutation harness found that hole; inspection had not.
#
# M14 cannot change behaviour and so is not a test gap. With the arm removed,
# an empty RC_RUNEWRITER_POLL_SEC reaches `float("")`, which raises ValueError,
# which the handler already converts to the same 1.0 default - verified. The
# arm is kept because `set RC_RUNEWRITER_POLL_SEC=` is the ordinary Windows
# idiom for "unset", and it should not log a warning. The mutant was swapped
# rather than the test weakened.
