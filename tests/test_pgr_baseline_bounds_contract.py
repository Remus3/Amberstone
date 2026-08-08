# arch: contract guard tying every PGR baseline-window clamp to the server authority | section=tests | frozen=no
"""Guard: the s220 PGR baseline-window bounds have FIVE representations.

RM-166 filed ONE mirror. Re-derivation on 2026-08-08 found FOUR - the filed
row said `web/js/panels/last_match.js:385` held "a SECOND copy", but the same
`(5, 50)` pair also lives in `web/js/panels/historical_pgr.js`,
`web/js/panels/dev.js` and, as `min=` / `max=` attributes, in the Settings
slider markup in `web/index.html`. The row was right about the defect and
wrong about its size, which is the whole reason this file discovers its
mirrors instead of listing them.

The representations:

  1. `dashboard/builders_last_match.py::_clamp_baseline` - THE AUTHORITY.
     Every request is re-clamped server-side, so a client that disagrees
     produces a confusing UI, never a wrong payload.
  2. `web/js/panels/last_match.js`      - clamps before building `?baseline=`.
  3. `web/js/panels/historical_pgr.js`  - same, for the detached historical PGR.
  4. `web/js/panels/dev.js`             - clamps the Settings slider's restored
     value out of `localStorage`.
  5. `web/index.html` `#set-pgr-baseline` `min=` / `max=` - the slider's own
     travel, which is what actually stops the operator authoring an
     out-of-range value in the first place.

WHY A CONTRACT TEST AND NOT A SINGLE SOURCE. JS cannot import a Python
constant, so 1 can never literally feed 2-4. The three routes that were
weighed and rejected:

  - Serve the bounds from the server. The clamp runs BEFORE the fetch, to
    build the query string, so the client would need the bounds in order to
    ask for them. Representation 5 is a static HTML attribute pair with no
    fetch at all. Circular for a defensive client-side clamp.
  - Emit a generated constants module. `tools/gen_state_schema.py` is the
    only generator aimed at `web/js/`, and it emits JSDoc `@typedef` blocks -
    type information, not runtime values. Extending it would add a new
    generated-values surface plus a `--check` coupling to guard a LOW row,
    and would still leave representation 5 uncovered.
  - This file. It costs nothing at runtime, and it covers all five.

THIS MODULE READS THE CONTRACT OFF DISK AND NEVER RESTATES IT. There is no
literal 5 and no literal 50 anywhere below: the authority is probed
BEHAVIOURALLY (clamp a huge negative and a huge positive and see where they
land), and every mirror is parsed out of its own source file. A hardcoded
expectation here would simply be a SIXTH representation and would reproduce
the exact drift class it is meant to close - the same reasoning as
`tests/test_frozen_file_list_contract.py`.

Static parsing, not node execution, is deliberate. `tests/test_web_js_esm_parse.py`
shows web/js CAN be node-parsed, and `.test.mjs` harnesses exist for panels -
but all three clamps sit mid-function in bodies that immediately touch
`localStorage`, `document` and `fetch`, so isolating the clamp would mean
stubbing the whole panel to read back two integers. The regexes below are
anchored on the identifier that was assigned from the `rc-pgr-baseline`
read, so they cannot drift onto an unrelated `Math.max(a, Math.min(b, x))`
(`dev.js` and `historical_pgr.js` each contain one).
"""
from __future__ import annotations

import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The shared localStorage key every client-side baseline reader goes through.
# Discovery is keyed off this rather than off a file list, so a NEW panel that
# reads the baseline is covered the day it lands instead of the day someone
# remembers this file.
LS_KEY = "rc-pgr-baseline"

# A change to this number is not a failure to "fix" - it means a client-side
# baseline reader was added or removed, which is exactly the event that should
# make a human look at whether it clamps correctly. (Deduping the three JS
# copies behind one shared module is a legitimate reason for this to drop.)
EXPECTED_JS_CLAMP_SITES = 3

# `<ident> = parseInt( ... "rc-pgr-baseline" ... )`
_ASSIGN_RE = re.compile(
    r"(?:let\s+|const\s+|var\s+)?(\w+)\s*=\s*parseInt\([^;\n]*" + re.escape(LS_KEY)
)

_SLIDER_RE = re.compile(
    r"<input\b[^>]*\bid=\"set-pgr-baseline\"[^>]*>", re.IGNORECASE
)


def _clamp_site(text: str):
    """Return (lo, hi) for the baseline clamp in one JS source, or None.

    Anchored both ways: the clamped identifier must be the SAME one the
    localStorage read assigned to, and it must also be the value being
    clamped. That rules out every unrelated Math.max/Math.min pair.
    """
    m = _ASSIGN_RE.search(text)
    if not m:
        return None
    ident = re.escape(m.group(1))
    clamp = re.search(
        ident + r"\s*=\s*Math\.max\(\s*(\d+)\s*,\s*Math\.min\(\s*(\d+)\s*,\s*"
        + ident + r"\s*\)\s*\)",
        text,
    )
    if not clamp:
        return None
    return int(clamp.group(1)), int(clamp.group(2))


def _js_baseline_readers():
    """Every web/js module that reads the shared baseline key, sorted."""
    return sorted(
        p for p in (ROOT / "web" / "js").rglob("*.js")
        if LS_KEY in p.read_text(encoding="utf-8", errors="replace")
    )


def _authority_bounds():
    """Probe the server clamp for its bounds instead of restating them."""
    from dashboard.builders_last_match import _clamp_baseline
    return _clamp_baseline(-(10 ** 9)), _clamp_baseline(10 ** 9)


class PgrBaselineBoundsContract(unittest.TestCase):

    def test_authority_probe_is_meaningful(self):
        """Guards the probe itself: a clamp that ignored its input would make
        every assertion below vacuously true."""
        lo, hi = _authority_bounds()
        self.assertIsInstance(lo, int)
        self.assertIsInstance(hi, int)
        self.assertLess(lo, hi, "server clamp bounds are inverted or collapsed")
        from dashboard.builders_last_match import _clamp_baseline
        # Idempotent, and the probed extremes really are attainable outputs.
        self.assertEqual(_clamp_baseline(lo), lo)
        self.assertEqual(_clamp_baseline(hi), hi)
        # A mid value must pass through untouched, or the "clamp" is a constant.
        mid = (lo + hi) // 2
        self.assertEqual(_clamp_baseline(mid), mid)

    def test_js_baseline_readers_are_discovered(self):
        """Non-vacuity guard: if discovery finds nothing, the clamp assertions
        below iterate over an empty list and pass while proving nothing."""
        readers = _js_baseline_readers()
        rel = sorted(p.relative_to(ROOT).as_posix() for p in readers)
        self.assertEqual(
            len(readers), EXPECTED_JS_CLAMP_SITES,
            "client-side readers of " + LS_KEY + " changed: " + repr(rel)
            + " - update EXPECTED_JS_CLAMP_SITES only after confirming each "
            "new site clamps to the server bounds (see RM-166).",
        )

    def test_every_js_clamp_matches_the_server_authority(self):
        lo, hi = _authority_bounds()
        for path in _js_baseline_readers():
            rel = path.relative_to(ROOT).as_posix()
            with self.subTest(source=rel):
                found = _clamp_site(path.read_text(encoding="utf-8"))
                self.assertIsNotNone(
                    found,
                    rel + " reads " + LS_KEY + " but no anchored "
                    "Math.max(lo, Math.min(hi, x)) clamp was found - either it "
                    "stopped clamping, or it was restructured and this guard "
                    "can no longer see it. Both need a human.",
                )
                self.assertEqual(
                    found, (lo, hi),
                    rel + " clamps to " + repr(found) + " but "
                    "dashboard/builders_last_match._clamp_baseline clamps to "
                    + repr((lo, hi)) + ". The server is authoritative.",
                )

    def test_settings_slider_range_matches_the_server_authority(self):
        """The slider's own travel is the fifth representation, and the only
        one that stops an out-of-range value being authored at all."""
        lo, hi = _authority_bounds()
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        tag = _SLIDER_RE.search(html)
        self.assertIsNotNone(
            tag, "#set-pgr-baseline input not found in web/index.html"
        )
        markup = tag.group(0)
        got = {}
        for attr in ("min", "max"):
            m = re.search(r"\b" + attr + r"=\"(-?\d+)\"", markup)
            self.assertIsNotNone(
                m, "#set-pgr-baseline has no " + attr + " attribute: " + markup
            )
            got[attr] = int(m.group(1))
        self.assertEqual(
            (got["min"], got["max"]), (lo, hi),
            "Settings baseline slider travels " + repr((got["min"], got["max"]))
            + " but the server clamps to " + repr((lo, hi)) + ".",
        )


if __name__ == "__main__":
    unittest.main()
