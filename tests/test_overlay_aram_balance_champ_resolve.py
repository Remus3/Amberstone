"""ARAM balance panel: champion-name resolution contract (two defects).

MEASURED LIVE 2026-07-20 (ARAM Mayhem, queue 2400): the panel rendered
"ARAM balance - patch 16.14.1" + "Waiting for champion data..." for a whole
game because ``_abBuildRows`` produced ZERO rows while every input was
present (coach.champion = "Varus", 10 liveclient allPlayers, 134-key
/api/aram-balance map).

Two independent root causes, both pinned here:

  A) CONTRACT MISMATCH. ``items_index._resolveChampId`` is named + was
     documented as returning "a numeric ID string", but it reads
     ``CHAMPS.byName``, which maps normalized-name -> CANONICAL NAME
     ("aatrox" -> "Aatrox"). It returns a NAME. Every other caller in the
     dashboard already relies on that (they build DDragon icon URLs like
     /img/champion/<cid>.png), so the function is correct and the DOC was
     wrong. ``aram_balance._abCanonicalId`` fed that name into
     ``CHAMPS.byId`` - an id -> name map - which always missed and returned
     "". That alone killed the SELF row and every champion not already a
     literal key of the balance map.

  B) RAW NAME. ``_abBuildRows`` preferred ``pl.rawChampionName``, which the
     Live Client serves as the localization key
     "game_character_displayname_Singed". It normalizes to
     "gamecharacterdisplaynamesinged" and resolves to null, so all ten
     ally/enemy rows died even though the plain ``championName`` would have
     hit the balance map directly.

Grep-contract test, mirroring tests/test_overlay_a3_coach_tag_strip.py:
pathlib reads + substring asserts on the .js source, no DOM emulation
(there is no jsdom/node harness for web/js page code). The RESOLUTION
BEHAVIOR is verified by re-implementing the JS algorithm in Python against
the REAL web/data/champions_index.json, and the JS source is pinned to that
same algorithm by literal-presence asserts - the two together verify the
live path without a JS runtime. A deliberate re-implementation of the OLD
(buggy) algorithm reproduces the measured zero-row symptom, which proves
the mirror is faithful.

Why the existing headless capture (tests/snapshot_panels/
test_aram_balance_view.py) stayed green through this: its fixture
web/data/ui_mock/active_match_aram.json sets rawChampionName == the plain
display name (never the game_character_displayname_ form), and every
fixture champion is a literal key of the stubbed balance map, so the
"direct hit" short-circuit in _abCanonicalId ran and the broken byId branch
was never exercised.
"""

from __future__ import annotations

import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ITEMS_INDEX_JS = REPO / "web" / "js" / "lib" / "items_index.js"
ARAM_BALANCE_JS = REPO / "web" / "js" / "panels" / "aram_balance.js"
CHAMPS_INDEX_JSON = REPO / "web" / "data" / "champions_index.json"
OVERLAY_LAYOUT_JS = REPO / "web" / "js" / "lib" / "overlay_layout.js"
OVERLAY_CSS = REPO / "web" / "css" / "overlay.css"
INDEX_HTML = REPO / "web" / "index.html"

# The widget the ARAM balance grid was promoted to (operator 2026-07-20): once
# the resolution fix made the grid populate, its ~11 rows pushed META BUILD +
# the DS item row into a clipped scroll region inside .am-pane-build.
_AB_WIDGET_ID = "w-arambalance"
_AB_MOUNT_ID = "aram-balance-panel"
# Only the top-left corner of a widget is knowable statically (height is
# content-driven), so the collision guard below is anchor-in-box, which is
# exactly the failure LEDGER 873 (C) recorded (w-stats defaulting ON TOP of
# w-call). The populated ARAM grid MEASURED 436px at 10 rows in a headless
# overlay probe; 480 budgets a full 11-row lobby and keeps the guard
# conservative for the other widgets too.
_ASSUMED_H = 480
_DEFAULT_OVX_W = 210

# The exact prefix the Live Client puts on rawChampionName.
_RAW_PREFIX = re.compile(r"^game_character_displayname_", re.I)

# MEASURED live roster (ARAM Mayhem, queue 2400, 2026-07-20). Varus is the
# operator's champion and is legitimately ABSENT from the balance map this
# patch; the other nine are keys of it.
_LIVE_SELF = "Varus"
_LIVE_ROSTER = [
    "Singed", "Zed", "Vayne", "Alistar", "Jhin",
    "Viego", "Lillia", "Ryze", "Fiddlesticks",
]
_BALANCE_MAP = {
    "Singed": {"aramDamageDealt": 1.05},
    "Zed": {"aramDamageTaken": 1.05},
    "Vayne": {"aramDamageDealt": 0.95},
    "Alistar": {"aramDamageTaken": 0.95},
    "Jhin": {"aramDamageDealt": 0.95},
    "Viego": {"aramDamageDealt": 0.93},
    "Lillia": {"aramDamageDealt": 1.05},
    "Ryze": {"aramDamageDealt": 1.05},
    "Fiddlesticks": {"aramAbilityHaste": 5},
}


def _champs_index() -> dict:
    return json.loads(CHAMPS_INDEX_JSON.read_text(encoding="utf-8"))


def _norm(s) -> str:
    """Mirror of items_index._normItemName / the _resolveChampId normalizer."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _resolve_champ_id(name, by_name: dict):
    """Reference re-impl of items_index._resolveChampId (byName lookup only;
    the rename-override map is a second byName-shaped table)."""
    n = _norm(name)
    if not n:
        return None
    return by_name.get(n) or None


def _strip_raw(name) -> str:
    """Reference re-impl of aram_balance._abStripRawName."""
    return _RAW_PREFIX.sub("", str(name or ""))


def _canonical_id(name, by_name: dict, champions: dict) -> str:
    """Reference re-impl of the FIXED aram_balance._abCanonicalId."""
    nm = _strip_raw(name)
    if not nm:
        return ""
    if nm in champions:
        return nm
    return _resolve_champ_id(nm, by_name) or ""


def _canonical_id_buggy(name, by_name: dict, by_id: dict, champions: dict) -> str:
    """Reference re-impl of the ORIGINAL (broken) _abCanonicalId - kept so the
    measured zero-row symptom is reproduced, not asserted from memory."""
    if not name:
        return ""
    if name in champions:
        return name
    num_key = _resolve_champ_id(name, by_name)
    if num_key and by_id.get(num_key):
        return by_id[num_key]
    return ""


def _build_rows(self_name, roster, by_name, champions, raw_form=True):
    """Reference re-impl of the FIXED _abBuildRows row set (ids only)."""
    rows, seen = [], set()

    def push(raw):
        cid = _canonical_id(raw, by_name, champions)
        if not cid or cid in seen:
            return
        seen.add(cid)
        rows.append(cid)

    push(self_name)
    for nm in roster:
        # The FIXED panel prefers championName; rawChampionName is only the
        # fallback. Both must work, so exercise the raw form too.
        push("game_character_displayname_" + nm if raw_form else nm)
    return rows


class ChampionsIndexShape(unittest.TestCase):
    """The premise of defect A, read off the REAL shipped index."""

    def setUp(self):
        self.idx = _champs_index()

    def test_by_name_values_are_canonical_names_not_numeric_ids(self):
        by_name = self.idx["byName"]
        self.assertEqual(by_name.get("aatrox"), "Aatrox")
        for k, v in list(by_name.items())[:25]:
            self.assertFalse(
                str(v).isdigit(),
                f"byName[{k!r}] = {v!r} - byName maps name -> NAME, so any "
                "caller treating _resolveChampId's return as a numeric id "
                "is broken",
            )

    def test_by_id_keys_are_numeric_and_values_are_names(self):
        by_id = self.idx["byId"]
        self.assertEqual(by_id.get("110"), "Varus")
        for k, v in list(by_id.items())[:25]:
            self.assertTrue(str(k).isdigit(), f"byId key {k!r} is not numeric")
            self.assertFalse(str(v).isdigit(), f"byId[{k!r}] = {v!r}")

    def test_a_name_is_never_a_key_of_by_id(self):
        # This is the exact miss: CHAMPS.byId["Varus"] is undefined.
        self.assertIsNone(self.idx["byId"].get("Varus"))


class ResolverBehavior(unittest.TestCase):
    """The re-implemented algorithm, against the real index."""

    def setUp(self):
        idx = _champs_index()
        self.by_name = idx["byName"]
        self.by_id = idx["byId"]

    def test_plain_display_name_resolves_to_canonical_name(self):
        self.assertEqual(_resolve_champ_id("Singed", self.by_name), "Singed")
        self.assertEqual(_resolve_champ_id("Varus", self.by_name), "Varus")

    def test_raw_live_client_name_does_not_resolve(self):
        # Defect B in one line: the raw form is a localization key.
        self.assertIsNone(
            _resolve_champ_id("game_character_displayname_Singed", self.by_name)
        )

    def test_prefix_strip_makes_the_raw_form_resolve(self):
        self.assertEqual(_strip_raw("game_character_displayname_Singed"), "Singed")
        self.assertEqual(
            _resolve_champ_id(_strip_raw("game_character_displayname_Singed"),
                              self.by_name),
            "Singed",
        )

    def test_strip_is_a_no_op_on_a_plain_name(self):
        self.assertEqual(_strip_raw("Varus"), "Varus")
        self.assertEqual(_strip_raw(""), "")

    def test_buggy_canonical_id_reproduces_the_measured_empty_panel(self):
        # SELF: "Varus" is not a key of the map (no ARAM changes this patch),
        # resolves to the NAME "Varus", byId["Varus"] is undefined -> "".
        self.assertEqual(
            _canonical_id_buggy("Varus", self.by_name, self.by_id, _BALANCE_MAP),
            "",
        )
        # ALLY/ENEMY: the raw form resolves to null -> "".
        self.assertEqual(
            _canonical_id_buggy("game_character_displayname_Singed",
                                self.by_name, self.by_id, _BALANCE_MAP),
            "",
        )

    def test_fixed_canonical_id_resolves_self_ally_and_enemy(self):
        self.assertEqual(
            _canonical_id("Varus", self.by_name, _BALANCE_MAP), "Varus")
        self.assertEqual(
            _canonical_id("game_character_displayname_Singed",
                          self.by_name, _BALANCE_MAP),
            "Singed",
        )
        self.assertEqual(
            _canonical_id("Singed", self.by_name, _BALANCE_MAP), "Singed")

    def test_unresolvable_name_still_returns_empty(self):
        # "absent from the balance map" must stay distinguishable from
        # "failed to resolve": only the latter yields "" (and thus no row).
        self.assertEqual(
            _canonical_id("NotAChampionXyz", self.by_name, _BALANCE_MAP), "")

    def test_full_live_roster_builds_ten_rows_from_raw_names(self):
        rows = _build_rows(_LIVE_SELF, _LIVE_ROSTER, self.by_name,
                           _BALANCE_MAP, raw_form=True)
        self.assertEqual(len(rows), 10, rows)
        self.assertEqual(rows[0], "Varus")
        for nm in _LIVE_ROSTER:
            self.assertIn(nm, rows)

    def test_full_live_roster_builds_ten_rows_from_display_names(self):
        rows = _build_rows(_LIVE_SELF, _LIVE_ROSTER, self.by_name,
                           _BALANCE_MAP, raw_form=False)
        self.assertEqual(len(rows), 10, rows)

    def test_champion_absent_from_map_still_gets_a_row(self):
        # Varus has NO entry in the balance map; the row must still exist so
        # the operator can tell "no ARAM changes" from "panel is broken".
        rows = _build_rows(_LIVE_SELF, _LIVE_ROSTER, self.by_name,
                           _BALANCE_MAP, raw_form=True)
        self.assertIn("Varus", rows)
        self.assertEqual(_BALANCE_MAP.get("Varus"), None)

    def test_buggy_algorithm_yields_zero_rows(self):
        # The measured symptom, end to end.
        ids = [
            _canonical_id_buggy(n, self.by_name, self.by_id, _BALANCE_MAP)
            for n in [_LIVE_SELF]
            + ["game_character_displayname_" + c for c in _LIVE_ROSTER]
        ]
        self.assertEqual([i for i in ids if i], [])


class ItemsIndexDocContract(unittest.TestCase):
    """Defect A, doc half: the resolver must not claim a numeric id."""

    def setUp(self):
        self.src = ITEMS_INDEX_JS.read_text(encoding="utf-8")

    def test_resolver_still_exported(self):
        self.assertIn("export function _resolveChampId", self.src)

    def test_resolver_still_reads_by_name(self):
        # Behavior must NOT change - every other caller builds a DDragon
        # icon URL from the returned NAME.
        self.assertIn("CHAMPS.byName[n]", self.src)

    def _doc_block(self) -> str:
        """The contiguous `//` comment block directly above the resolver."""
        lines = self.src.splitlines()
        i = next(n for n, ln in enumerate(lines)
                 if ln.startswith("export function _resolveChampId"))
        block, j = [], i - 1
        while j >= 0 and lines[j].lstrip().startswith("//"):
            block.append(lines[j])
            j -= 1
        return "\n".join(reversed(block))

    def test_docstring_does_not_claim_a_numeric_id_return(self):
        # The original claim ("Resolve a champion name to its numeric ID
        # string.") is what led aram_balance.js to feed the return into
        # CHAMPS.byId.
        self.assertNotIn("numeric ID string", self._doc_block())

    def test_docstring_warns_that_by_id_is_a_separate_map(self):
        self.assertIn(
            "CHAMPS.byId", self._doc_block(),
            "the resolver doc must name CHAMPS.byId as a SEPARATE map so the "
            "next reader does not repeat the aram_balance.js mistake",
        )


class AramBalanceSourceContract(unittest.TestCase):
    """Both defects, pinned in the panel source."""

    def setUp(self):
        self.src = ARAM_BALANCE_JS.read_text(encoding="utf-8")

    def _has(self, needle):
        # assertIn on a whole source file dumps the file into the failure;
        # keep the diagnostic to one line.
        return needle in self.src

    def _has_code(self, needle):
        # Same, but with `//` line comments stripped - the fix leaves a
        # comment NAMING the old broken lookup, which must not re-trip the
        # guard.
        code = re.sub(r"^\s*//.*$", "", self.src, flags=re.M)
        return needle in code

    def test_does_not_index_by_id_with_a_name(self):
        # Defect A: CHAMPS.byId is an id -> name map; _resolveChampId returns
        # a name, so this lookup can never hit.
        self.assertFalse(
            self._has_code("CHAMPS.byId"),
            "aram_balance.js must not index CHAMPS.byId with the "
            "_resolveChampId return (that value is a NAME, byId is keyed by "
            "the numeric id) - this is what emptied the panel",
        )

    def test_does_not_import_champs(self):
        # The byId map is no longer needed at all here.
        self.assertFalse(
            self._has_code("CHAMPS"),
            "aram_balance.js should no longer import or reference CHAMPS",
        )

    def test_strips_the_live_client_raw_prefix(self):
        # Defect B: the localization-key prefix must be stripped.
        self.assertTrue(
            self._has("game_character_displayname_"),
            "aram_balance.js must strip the Live Client rawChampionName "
            "prefix 'game_character_displayname_' before resolving",
        )

    def test_prefers_display_name_over_raw_name(self):
        # Defect B: rawChampionName is the FALLBACK, not the preference.
        self.assertTrue(
            self._has("pl.championName || pl.rawChampionName"),
            "_abBuildRows must prefer pl.championName (the display name) "
            "over pl.rawChampionName (the localization key)",
        )
        self.assertFalse(
            self._has("pl.rawChampionName || pl.championName"),
            "_abBuildRows still prefers the raw localization-key form",
        )

    def test_absent_champion_renders_an_explicit_no_change_row(self):
        # A champion with no ARAM modifiers keeps its row and says so.
        self.assertTrue(
            self._has("no ARAM changes"),
            "a resolved champion with no modifiers must render an explicit "
            "'no ARAM changes' row, not a bare 'neutral'",
        )


class _MountParentFinder(HTMLParser):
    """Record the open-element stack at the moment an id is opened.

    A substring search cannot answer "is this a DIRECT child of .am-grid" -
    the mount used to be nested two levels deeper inside .am-pane-build. This
    walks the real tag structure instead. Void elements never open a scope.
    """

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, want_id: str):
        super().__init__(convert_charrefs=True)
        self.want_id = want_id
        self.stack: list = []
        self.found_stack = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id") == self.want_id and self.found_stack is None:
            self.found_stack = list(self.stack)
        if tag not in self.VOID:
            self.stack.append((tag, a.get("class") or "", a.get("id") or ""))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return


def _widget_defaults() -> dict:
    """Parse the overlay_layout.js WIDGETS registry into {id: (x, y)}."""
    src = OVERLAY_LAYOUT_JS.read_text(encoding="utf-8")
    body = src[src.index("const WIDGETS = ["): src.index("\n];", src.index("const WIDGETS = ["))]
    out = {}
    for m in re.finditer(
        r'\{\s*id:\s*"([^"]+)"[^}]*?\bx:\s*(-?\d+)\s*,\s*y:\s*(-?\d+)', body
    ):
        out[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return out


def _ovx_widths() -> dict:
    """Per-widget --ovx-w overrides declared in overlay.css."""
    css = OVERLAY_CSS.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(
        r'\[data-ovx-id="([^"]+)"\]\s*\{(.*?)\}', css, flags=re.S
    ):
        w = re.search(r"--ovx-w:\s*(\d+)px", m.group(2))
        if w:
            out[m.group(1)] = int(w.group(1))
    return out


class OverlayWidgetRegistration(unittest.TestCase):
    """The grid is its own draggable widget, not a row inside the BUILD pane."""

    def setUp(self):
        self.src = OVERLAY_LAYOUT_JS.read_text(encoding="utf-8")
        self.defaults = _widget_defaults()
        self.widths = _ovx_widths()

    def test_registry_entry_exists(self):
        self.assertIn(
            _AB_WIDGET_ID, self.defaults,
            "overlay_layout.js WIDGETS must register the ARAM balance grid",
        )

    def test_entry_targets_the_panel_mount_and_is_ambient(self):
        m = re.search(
            r'\{\s*id:\s*"' + _AB_WIDGET_ID + r'"[^}]*\}', self.src)
        self.assertIsNotNone(m, "registry entry not found")
        entry = m.group(0)
        self.assertIn('sel: "#' + _AB_MOUNT_ID + '"', entry)
        self.assertIn('tier: "ambient"', entry)
        self.assertIn("label:", entry)

    def test_has_a_width_override_wide_enough_for_a_three_chip_row(self):
        # Below ~615px the chips wrap and every one of the 11 rows doubles in
        # height - the same widen-to-fit law as w-build / w-enemyspells.
        self.assertIn(_AB_WIDGET_ID, self.widths,
                      "overlay.css must declare an --ovx-w for the widget")
        self.assertGreaterEqual(self.widths[_AB_WIDGET_ID], 615)

    def test_no_two_widget_defaults_share_an_anchor(self):
        seen = {}
        for wid, xy in self.defaults.items():
            self.assertNotIn(
                xy, seen,
                f"{wid} defaults on top of {seen.get(xy)} at {xy} "
                "(LEDGER 873 (C) collision class)",
            )
            seen[xy] = wid

    def test_default_anchor_collides_with_no_other_widget(self):
        # LEDGER 873 (C): a new widget must not default INSIDE an existing
        # one's box, nor host an existing one's anchor inside its own.
        mine = self.defaults[_AB_WIDGET_ID]
        my_w = self.widths.get(_AB_WIDGET_ID, _DEFAULT_OVX_W)
        for wid, (ox, oy) in self.defaults.items():
            if wid == _AB_WIDGET_ID:
                continue
            ow = self.widths.get(wid, _DEFAULT_OVX_W)
            inside_mine = (mine[0] <= ox <= mine[0] + my_w
                           and mine[1] <= oy <= mine[1] + _ASSUMED_H)
            self.assertFalse(
                inside_mine,
                f"{wid} anchor {(ox, oy)} falls inside the {_AB_WIDGET_ID} "
                f"default box x{mine[0]}..{mine[0] + my_w} "
                f"y{mine[1]}..{mine[1] + _ASSUMED_H}",
            )
            inside_theirs = (ox <= mine[0] <= ox + ow
                             and oy <= mine[1] <= oy + _ASSUMED_H)
            self.assertFalse(
                inside_theirs,
                f"{_AB_WIDGET_ID} anchor {mine} falls inside {wid}'s box",
            )


class MountRelocation(unittest.TestCase):
    """The mount moved out of the transformed BUILD pane to an am-grid child."""

    def setUp(self):
        self.html = INDEX_HTML.read_text(encoding="utf-8")
        p = _MountParentFinder(_AB_MOUNT_ID)
        p.feed(self.html)
        self.stack = p.found_stack

    def test_mount_exists(self):
        self.assertIsNotNone(self.stack, f"#{_AB_MOUNT_ID} not found")

    def test_parent_is_the_am_grid(self):
        # Direct child: position:fixed must be viewport-relative, not trapped
        # by a transformed .ovx-widget pane (the w-spike precedent).
        parent = self.stack[-1]
        self.assertIn(
            "am-grid", parent[1],
            f"#{_AB_MOUNT_ID} parent is <{parent[0]} class={parent[1]!r}>, "
            "expected the .am-grid container",
        )

    def test_not_nested_in_the_build_pane(self):
        for _tag, cls, _eid in self.stack:
            self.assertNotIn(
                "am-pane-build", cls,
                f"#{_AB_MOUNT_ID} is still inside .am-pane-build - its rows "
                "push META BUILD + the DS item row into a clipped scroll box",
            )

    def test_mount_keeps_its_inline_display_gate(self):
        # Unlike its overlay-only am-grid siblings this panel ALSO renders on
        # the dashboard, so it self-gates via style.display (renderAramBalance)
        # rather than the `hidden` attribute - mixing the two would let the
        # inline display always win and strand the attribute.
        m = re.search(r'<div id="' + _AB_MOUNT_ID + r'"[^>]*>', self.html)
        self.assertIsNotNone(m)
        self.assertIn("display:none", m.group(0))
        self.assertNotIn(" hidden", m.group(0))


class ModeGate(unittest.TestCase):
    """ARAM-only: the widget must cost nothing in SR / Arena."""

    def setUp(self):
        self.src = ARAM_BALANCE_JS.read_text(encoding="utf-8")

    def test_renderer_hides_the_mount_outside_aram(self):
        body = self.src[self.src.index("export function renderAramBalance"):]
        self.assertIn("_abIsAram(ctx)", body)
        self.assertIn('host.style.display = "none"', body)

    def test_aram_mode_set_is_the_gate(self):
        self.assertIn('_AB_ARAM_MODES = new Set(["aram", "kiwi"])', self.src)


class AsciiOnly(unittest.TestCase):
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""

    def test_this_test_is_ascii(self):
        raw = Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])

    def test_panel_source_is_ascii(self):
        raw = ARAM_BALANCE_JS.read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])

    def test_overlay_layout_source_is_ascii(self):
        raw = OVERLAY_LAYOUT_JS.read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
