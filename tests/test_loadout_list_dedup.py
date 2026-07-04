"""Pin the dedup-fetch wire-in across the wired call sites (item 186).

web/js/lib/dedup_fetch.js coalesces concurrent identical fetches so
parallel panels (coach_decisions on /api/decisions; champ_select +
item_build on /api/loadout/list) share one in-flight request within a
small render-storm grace TTL. ~50-150ms saved per consolidated fetch.

(2026-07-04: trigger_pill.js - the 4th wired site - was retired with
header row 2; its pins were removed rather than converted since the
whole module is gone. coach_decisions keeps dedupFetch: it still
coalesces its own render-storm duplicates.)

These grep-pin tests fail CI if a future refactor silently rips a wire
out (mirrors item 152 WiredSitesGrepTests precedent for the cost-trace
record_anthropic_response wire-in).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEDUP_LIB = REPO_ROOT / "web" / "js" / "lib" / "dedup_fetch.js"

# Call sites that MUST consume dedupFetch (NOT raw fetch) for the
# coalesced endpoints. Each entry: (panel file, endpoint substring).
_WIRED_SITES = (
    ("web/js/panels/coach_decisions.js", "/api/decisions"),
    ("web/js/panels/champ_select.js",   "/api/loadout/list"),
    ("web/js/panels/item_build.js",     "/api/loadout/list"),
)


class DedupFetchLibTests(unittest.TestCase):
    """The helper module exists and exports the expected API."""

    def test_dedup_fetch_lib_exists(self):
        self.assertTrue(
            DEDUP_LIB.exists(),
            f"missing dedup helper at {DEDUP_LIB}",
        )

    def test_exports_dedup_fetch(self):
        src = DEDUP_LIB.read_text(encoding="utf-8")
        self.assertIn("export function dedupFetch", src)

    def test_module_uses_inflight_map(self):
        # The coalescing primitive is a module-level Map<key, entry>.
        src = DEDUP_LIB.read_text(encoding="utf-8")
        self.assertIn("const _inflight = new Map()", src)

    def test_evicts_on_settle_with_ttl(self):
        # setTimeout-based eviction is the cheapest way to grant a
        # render-storm grace window without holding entries forever.
        src = DEDUP_LIB.read_text(encoding="utf-8")
        self.assertIn("setTimeout", src)
        self.assertIn("_inflight.delete", src)

    def test_evicts_immediately_on_reject(self):
        # No stuck negative cache - errors evict synchronously so the
        # next retry goes fresh.
        src = DEDUP_LIB.read_text(encoding="utf-8")
        # The catch arm must contain delete; loose check via regex.
        self.assertTrue(
            re.search(r"\(err\)\s*=>\s*\{[^}]*_inflight\.delete", src,
                      re.DOTALL),
            "reject handler missing immediate _inflight.delete",
        )

    def test_clones_response_for_secondary_callers(self):
        # First waiter gets the master Response; later waiters need
        # .clone() so each can independently read the body.
        src = DEDUP_LIB.read_text(encoding="utf-8")
        self.assertIn("resp.clone()", src)


class WiredSitesGrepTests(unittest.TestCase):
    """Each of the 4 call sites grep-matches dedupFetch + endpoint."""

    def _read(self, rel: str) -> str:
        return (REPO_ROOT / rel).read_text(encoding="utf-8")

    def test_coach_decisions_uses_dedup_fetch_decisions(self):
        src = self._read("web/js/panels/coach_decisions.js")
        self.assertIn("import { dedupFetch } from '../lib/dedup_fetch.js'",
                      src)
        # The poll site MUST call dedupFetch (not bare fetch) for
        # /api/decisions. We pin the exact one-line call.
        self.assertIn('dedupFetch("/api/decisions")', src)

    def test_champ_select_uses_dedup_fetch_loadout(self):
        src = self._read("web/js/panels/champ_select.js")
        self.assertIn("import { dedupFetch } from '../lib/dedup_fetch.js'",
                      src)
        self.assertIn('dedupFetch("/api/loadout/list"', src)

    def test_item_build_uses_dedup_fetch_loadout(self):
        src = self._read("web/js/panels/item_build.js")
        self.assertIn("import { dedupFetch } from '../lib/dedup_fetch.js'",
                      src)
        # item_build.js has TWO call sites - both must consume dedupFetch.
        count = src.count('dedupFetch("/api/loadout/list"')
        self.assertGreaterEqual(
            count, 2,
            f"item_build.js should call dedupFetch twice for "
            f"/api/loadout/list (label + builds); got {count}",
        )


class NoRawFetchRegressionTests(unittest.TestCase):
    """Defense-in-depth: the wired endpoints should NOT have bare
    fetch(...) calls in the 4 panels. If a future maintainer adds a
    new bare fetch for these paths, this test fails before the
    coalescing benefit is lost in production."""

    # (panel file, endpoint, expected raw-fetch count)
    # /api/decisions: 0 raw fetches (wired to dedupFetch).
    # /api/loadout/list: 0 raw fetches in either panel.
    # /api/decisions/heartbeat + /api/decisions/log + /api/decisions/<id>
    # are DIFFERENT endpoints (sub-paths) and intentionally NOT deduped
    # (lower cadence + per-id semantics) - they may still use bare fetch.
    _CASES = (
        ("web/js/panels/coach_decisions.js", r'fetch\("/api/decisions"\)', 0),
        ("web/js/panels/champ_select.js",   r'fetch\("/api/loadout/list"', 0),
        ("web/js/panels/item_build.js",     r'fetch\("/api/loadout/list"', 0),
    )

    def test_no_bare_fetch_for_wired_endpoints(self):
        for rel, pattern, expected in self._CASES:
            with self.subTest(file=rel, pattern=pattern):
                src = (REPO_ROOT / rel).read_text(encoding="utf-8")
                # Match `fetch(` but NOT `dedupFetch(` - leading word
                # boundary excludes the dedup-prefixed name.
                hits = re.findall(r"(?<![A-Za-z_])" + pattern, src)
                self.assertEqual(
                    len(hits), expected,
                    f"{rel}: {len(hits)} bare fetch hit(s) for "
                    f"{pattern!r}; expected {expected}",
                )


class AsciiHygieneTests(unittest.TestCase):
    def test_dedup_lib_is_ascii(self):
        raw = DEDUP_LIB.read_bytes()
        for i, b in enumerate(raw):
            self.assertLess(
                b, 0x80,
                f"non-ASCII byte 0x{b:02x} at offset {i} in dedup_fetch.js",
            )

    def test_test_file_is_ascii(self):
        raw = Path(__file__).read_bytes()
        for i, b in enumerate(raw):
            self.assertLess(
                b, 0x80,
                f"non-ASCII byte 0x{b:02x} at offset {i} in this test file",
            )


if __name__ == "__main__":
    unittest.main()
