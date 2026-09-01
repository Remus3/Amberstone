"""Guard: the DS3 legibility harness and its spec cannot drift apart.

DS3 (`docs/qa/UI_UX_PROGRAM_QA_2026-07-22.md:72`) asks for a DOCUMENTED in-game
legibility variant. A variant that exists only in the render harness, or only in
the prose, is not documented - so this pins the two registries to the spec in
BOTH directions: a variant added to the tool and not the doc fails, and a
variant named in the doc and not the tool fails.

The tool is read as SOURCE (py_compile + ast), never imported. Importing it
would pull in playwright + PIL at collection time for a test that has nothing to
say about either, and would make this guard skip on a machine where the browser
deps are absent - exactly when the harness is most likely to have rotted.
"""
import ast
import py_compile
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "overlay_legibility_preview.py"
SPEC = REPO / "docs" / "qa" / "OVERLAY_LEGIBILITY_VARIANTS_2026-09-01.md"

# Registry names look like `v1_hairline_scrim` in both files. `baseline` is the
# reference cell, not a variant, and is matched separately.
_VARIANT_TOKEN = re.compile(r"\bv\d+_[a-z][a-z0-9_]*\b")


def _module_ast():
    return ast.parse(TOOL.read_text(encoding="utf-8"), filename=str(TOOL))


def _dict_keys(tree, name):
    """Return the literal string keys of a module-level `name = {...}` dict."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if name not in targets:
            continue
        if not isinstance(node.value, ast.Dict):
            raise AssertionError(f"{name} is not a dict literal")
        keys = []
        for k in node.value.keys:
            if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
                raise AssertionError(f"{name} has a non-string-literal key")
            keys.append(k.value)
        return keys
    raise AssertionError(f"{name} not found at module level in {TOOL}")


class TestOverlayLegibilityVariantsSpec(unittest.TestCase):
    def test_harness_exists(self):
        self.assertTrue(TOOL.is_file(), f"missing render harness: {TOOL}")

    def test_spec_exists(self):
        self.assertTrue(SPEC.is_file(), f"missing DS3 spec: {SPEC}")

    def test_harness_compiles(self):
        # Raises py_compile.PyCompileError on a syntax error.
        py_compile.compile(str(TOOL), doraise=True, cfile=None)

    def test_registries_are_declared(self):
        tree = _module_ast()
        variants = _dict_keys(tree, "VARIANTS")
        backdrops = _dict_keys(tree, "BACKDROPS")
        self.assertIn("baseline", variants,
                      "VARIANTS must carry the unmodified reference cell")
        self.assertGreaterEqual(len(variants), 4,
                                "DS3 asks for baseline plus 2-3 named variants")
        self.assertGreaterEqual(len(backdrops), 3,
                                "need a bright, a dark and a high-chroma proxy")

    def test_every_variant_is_documented(self):
        variants = set(_dict_keys(_module_ast(), "VARIANTS"))
        spec = SPEC.read_text(encoding="utf-8")
        for name in sorted(variants):
            self.assertIn(name, spec,
                          f"variant {name!r} is in VARIANTS but not named in {SPEC.name}")

    def test_spec_names_no_unknown_variant(self):
        variants = set(_dict_keys(_module_ast(), "VARIANTS"))
        documented = set(_VARIANT_TOKEN.findall(SPEC.read_text(encoding="utf-8")))
        unknown = documented - variants
        self.assertFalse(
            unknown,
            f"{SPEC.name} names variant(s) {sorted(unknown)} that VARIANTS does not define",
        )
        # And the doc must actually name the non-baseline registry keys, not
        # just the prose labels - otherwise the check above is vacuous.
        expected = {v for v in variants if v != "baseline"}
        self.assertEqual(documented, expected)

    def test_every_backdrop_is_documented(self):
        backdrops = _dict_keys(_module_ast(), "BACKDROPS")
        spec = SPEC.read_text(encoding="utf-8")
        for name in backdrops:
            self.assertIn(name, spec,
                          f"backdrop {name!r} is in BACKDROPS but not named in {SPEC.name}")

    def test_variants_carry_concrete_overlay_scoped_css(self):
        tree = _module_ast()
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "VARIANTS" for t in node.targets):
                continue
            for key, value in zip(node.value.keys, node.value.values):
                if key.value == "baseline":
                    continue
                self.assertIsInstance(value, ast.Dict)
                fields = {k.value: v for k, v in zip(value.keys, value.values)}
                self.assertIn("css", fields, f"{key.value} has no css entry")
                # The css entry is a Name pointing at a module-level constant.
                self.assertIsInstance(fields["css"], ast.Name)
                block = _const_str(tree, fields["css"].id)
                self.assertIn('body[data-shell="overlay"]', block,
                              f"{key.value} CSS is not overlay-scoped")
                # The repair must appear on BOTH the generic widget backing and
                # the w-call backing. active_match.css:92-100 outranks the
                # overlay's own .am-pane rule, so a variant that repairs only
                # one of the two leaves the other three .am-pane widgets
                # (w-call / w-build / w-ovds) on the opaque dashboard surface -
                # measured 2026-09-01, see the spec section 1.3.
                self.assertGreaterEqual(
                    block.count("#view-active-match .am-pane.ovx-widget"), 2,
                    f"{key.value} CSS carries the active_match.css specificity "
                    "repair on fewer than both backing rules, so the variant "
                    "cannot fully reach the .am-pane widgets",
                )

    def test_harness_never_writes_a_production_stylesheet(self):
        src = TOOL.read_text(encoding="utf-8")
        self.assertIn("add_style_tag", src,
                      "variants must be injected at render time, not written to disk")
        for forbidden in ("web/css", "web\\css"):
            self.assertNotIn(f'Path("{forbidden}', src)
            self.assertNotIn(f"open('{forbidden}", src)

    def test_spec_keeps_the_no_live_game_caveat(self):
        spec = SPEC.read_text(encoding="utf-8")
        self.assertIn("no live game", spec.lower())
        self.assertIn("synthetic", spec.lower())
        self.assertIn("WHAT THE OPERATOR MUST DECIDE", spec)
        self.assertIn("HOW TO RESUME", spec)

    def test_authored_files_are_ascii(self):
        for path in (TOOL, SPEC):
            raw = path.read_bytes()
            bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
            self.assertFalse(
                bad[:5],
                f"{path.name} has non-ASCII bytes at offsets {[i for i, _ in bad[:5]]}",
            )


def _const_str(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    raise AssertionError(f"{name} is not a module-level string constant")


if __name__ == "__main__":
    unittest.main()
