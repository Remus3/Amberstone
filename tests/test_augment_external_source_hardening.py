"""
tests/test_augment_external_source_hardening.py - lane 8 cycle 33.

core/augment_external_source.py parses a payload from a host RC does not
own (Overlay App E's unauthenticated data backend) and a CommunityDragon
mirror. Its module docstring promises "This module never raises into its
callers except via the explicit refresh_cache ``force`` path", and both
public accessors repeat that in their own docstrings - get_priors says
"Never raises - degrades to empty on every failure" and get_augment_meta
says "never-raises accessor".

That contract was FALSE on three independent paths, each proven by a probe
before this file was written:

  W1  _normalize coerced third-party numerics with bare int()/float().
      The payload demonstrably string-encodes numbers - augment_id is a
      numeric STRING in this very feed - so a num_games of "1500.0" or a
      pick_rate of "n/a" raised ValueError, which is not AugmentSourceError
      and therefore walked straight past refresh_cache's handler.
  W2  _table_from_meta_snapshot rebuilt the reverse index with int(v) over
      whatever the cached file held, so one junk name_index value raised.
  W3  _current_patch caught OSError only. read_text raises UnicodeDecodeError
      (a ValueError, NOT an OSError) on a non-UTF-8 file, so a corrupt
      current.txt escaped. core/polled_json.py fixed this exact class in lane
      8 cycle 24 and its comment names three callers that had widened their
      own handlers instead of fixing the root - this module is a fourth site
      of the same bug, fixed here at the root rather than by widening a
      caller.

Blast radius when this fired: coaches/arena_coach.py absorbs it in a broad
except Exception, so the augment recommendation silently vanishes; but
core/augment_recommender.py recommend() calls get_priors/get_augment_meta
OUTSIDE its two except (TypeError, ValueError) blocks (those guard only the
id coercions above), so there it propagates.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import augment_external_source as X


def _payload(stats: dict) -> dict:
    """Minimal well-formed envelope carrying one augment row."""
    return {
        "meta": {"generated_at": "2026-08-30T00:00:00Z"},
        "data": [{"augment_id": "1088", "patch": "16.15", "stats": stats}],
    }


class NormalizeNumericCoercionTest(unittest.TestCase):
    """W1 - a string-encoded or junk numeric must not raise past the
    module's AugmentSourceError contract."""

    def test_string_encoded_float_num_games_does_not_raise(self):
        snap = X._normalize("mayhem", "tp", _payload(
            {"win_rate": 0.52, "num_games": "1500.0"}))
        self.assertEqual(snap["augments"]["1088"]["num_games"], 1500)

    def test_string_encoded_int_num_games_is_kept(self):
        snap = X._normalize("mayhem", "tp", _payload(
            {"win_rate": 0.52, "num_games": "1500"}))
        self.assertEqual(snap["augments"]["1088"]["num_games"], 1500)

    def test_junk_pick_rate_degrades_to_zero_not_a_raise(self):
        snap = X._normalize("mayhem", "tp", _payload(
            {"win_rate": 0.52, "pick_rate": "n/a"}))
        self.assertEqual(snap["augments"]["1088"]["pick_rate"], 0.0)
        # The row survives: win_rate is the field the recommender needs.
        self.assertEqual(snap["augments"]["1088"]["win_rate"], 0.52)

    def test_junk_num_win_games_degrades_to_zero(self):
        snap = X._normalize("mayhem", "tp", _payload(
            {"win_rate": 0.52, "num_win_games": {"bad": 1}}))
        self.assertEqual(snap["augments"]["1088"]["num_win_games"], 0)

    def test_string_encoded_win_rate_is_still_dropped(self):
        """Guard against over-widening: win_rate is the ONE field whose
        absence must drop the row, so a non-numeric win_rate stays a drop
        rather than becoming a silent 0.0 that scores as a 0 percent
        augment."""
        with self.assertRaises(X.AugmentSourceError):
            X._normalize("mayhem", "tp", _payload(
                {"win_rate": "0.52", "num_games": 10}))


class MetaSnapshotIndexTest(unittest.TestCase):
    """W2 - a corrupt cached name_index must not raise."""

    def test_junk_name_index_value_is_skipped_not_raised(self):
        t = X._table_from_meta_snapshot(
            {"augments": {"7": {"name": "Ok"}},
             "name_index": {"good": 7, "bad": "notanint"}})
        self.assertEqual(t.resolve_id("good"), 7)
        self.assertIsNone(t.resolve_id("bad"))

    def test_unhashable_name_index_value_is_skipped(self):
        t = X._table_from_meta_snapshot(
            {"augments": {}, "name_index": {"good": 7, "bad": {"x": 1}}})
        self.assertEqual(t._name_index, {"good": 7})


class CurrentPatchDecodeTest(unittest.TestCase):
    """W3 - a non-UTF-8 current.txt must degrade, not raise."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pf = Path(self._tmp.name) / "current.txt"

    def test_non_utf8_patch_file_returns_empty_string(self):
        self.pf.write_bytes(b"16.15.1\xff\xfe")
        with mock.patch.object(X, "_PATCH_FILE", self.pf):
            self.assertEqual(X._current_patch(), "")

    def test_get_augment_meta_never_raises_on_corrupt_patch_file(self):
        self.pf.write_bytes(b"\xff\xfe\xff")
        boom = mock.Mock(side_effect=X.AugmentSourceError("no network"))
        with mock.patch.object(X, "_PATCH_FILE", self.pf), \
                mock.patch.object(X, "_DS_DATA_DIR", Path(self._tmp.name)), \
                mock.patch.object(X, "_http_get", boom):
            X.reset_cache()
            self.addCleanup(X.reset_cache)
            table = X.get_augment_meta()
        self.assertFalse(table.has_data)

    def test_get_priors_never_raises_on_corrupt_patch_file(self):
        self.pf.write_bytes(b"\xff\xfe\xff")
        boom = mock.Mock(side_effect=X.AugmentSourceError("no network"))
        with mock.patch.object(X, "_PATCH_FILE", self.pf), \
                mock.patch.object(X, "_DS_DATA_DIR", Path(self._tmp.name)), \
                mock.patch.object(X, "_http_get_json", boom):
            X.reset_cache()
            self.addCleanup(X.reset_cache)
            table = X.get_priors("mayhem")
        self.assertFalse(table.has_data)


class ResponseSizeCapTest(unittest.TestCase):
    """W5 - the body of a host RC does not control is read under a cap."""

    def test_oversized_body_raises_augment_source_error(self):
        """The stub HONOURS the n argument, so this pins the bounded-read
        property and not merely the length check.

        The cycle-33 verifier refuted the first version of this test: its
        stub ignored n, so a mutant that kept `if len(body) > cap` but went
        back to an unbounded `r.read()` would still have passed - i.e. it
        tested the raise and not the memory bound, which is the whole stated
        rationale for the cap. Now `read` records what it was asked for and
        returns at most that, so an unbounded read yields cap bytes exactly,
        trips no raise, and the assertions below fail.

        ISOLATION (2026-09-01): the recording stub is served ONLY for this
        test's own URL. `mock.patch.object` replaces the process-global
        `urllib.request.urlopen`, and under the full `-n 8` suite a leaked
        background thread from another test can call it inside this patch
        window; served the recording stub, its `read(-1)` appends a stray
        entry to `seen` and the exact-list assertion below fails on correct
        code - observed once in CI as `seen == [cap+1, -1]`
        (reference_flaky_only_under_full_parallel_suite). Any non-test URL now
        gets a benign non-recording response, so `seen` holds this test's read
        alone and the exact-list assertion - which is what catches an
        unbounded-read mutant - stays sound."""
        seen = []
        test_url = "https://example.invalid/x"

        class _Resp:
            status = 200
            headers = {}

            def read(self, n=-1):
                seen.append(n)
                body = b"x" * (X._MAX_BODY_BYTES * 4)
                return body if n is None or n < 0 else body[:n]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class _Benign:
            # Served to any OTHER url (a leaked concurrent call under -n 8).
            # Records nothing, so it cannot pollute `seen`.
            status = 200
            headers = {}

            def read(self, n=-1):
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def _urlopen(req, *a, **k):
            url = getattr(req, "full_url", req)
            return _Resp() if url == test_url else _Benign()

        with mock.patch.object(X.urllib.request, "urlopen", _urlopen):
            with self.assertRaises(X.AugmentSourceError) as ctx:
                X._http_get(test_url, 1.0)
        self.assertIn("too large", str(ctx.exception).lower())
        # The bound itself: read was asked for a finite cap, not everything.
        self.assertEqual(seen, [X._MAX_BODY_BYTES + 1])


class NonFiniteTest(unittest.TestCase):
    """W6 - the sibling case, found by grepping for this root cause rather
    than by reading this file.

    core/synergy_external_source.py:135-147 is the twin this module's own
    docstring is cited by, and it already kills NaN/Infinity at the door.
    This module did not. json.loads accepts those three NON-STANDARD
    literals by default, isinstance(float("nan"), float) is True so a
    non-finite survives every downstream type check, and json.dumps
    re-emits it as a bare NaN token (allow_nan defaults True) - which is
    not valid JSON, so the written cache file becomes unparseable by any
    strict reader. Downstream it is worse than a crash: every comparison
    against NaN is False, so the recommender's ranking silently degrades
    rather than failing.

    SEVERITY, stated honestly: latent. All 18 live snapshot files under
    data/daemon_slayer/ (6 patch dirs x arena_augments / cherry_augments /
    mayhem_augment_stats) were strict-parsed with parse_constant during this
    audit and ZERO carry a non-finite literal, so nothing on disk needed
    backfilling. It is fixed because the upstream host is not RC's to
    control and the twin module already treats this as a live risk.

    That count read "24" when this file was first committed (1f4908d4) and
    the cycle-33 verifier refuted it: the measuring glob unioned
    "*augment*.json" with "cherry_augments.json", and the second pattern is
    a SUBSET of the first, so every cherry file was counted twice. The
    substantive half - zero non-finite literals - survived re-derivation
    unchanged. Recorded rather than quietly corrected because a filed count
    that nobody re-derives is how a wrong number becomes durable.
    """

    def test_http_get_rejects_nan_literal_in_body(self):
        class _Resp:
            status = 200

            def read(self, n=-1):
                return b'{"data": [{"stats": {"win_rate": NaN}}]}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(X.urllib.request, "urlopen",
                               lambda *a, **k: _Resp()):
            with self.assertRaises(X.AugmentSourceError):
                X._http_get("https://example.invalid/x", 1.0)

    def test_http_get_still_accepts_an_ordinary_body(self):
        """Negative control: the guard must not reject valid JSON."""
        class _Resp:
            status = 200

            def read(self, n=-1):
                return b'{"data": [], "meta": {"count": 0}}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(X.urllib.request, "urlopen",
                               lambda *a, **k: _Resp()):
            self.assertEqual(
                X._http_get("https://example.invalid/x", 1.0),
                {"data": [], "meta": {"count": 0}})

    def test_normalize_drops_a_non_finite_win_rate_row(self):
        with self.assertRaises(X.AugmentSourceError):
            X._normalize("mayhem", "tp", _payload(
                {"win_rate": float("nan"), "num_games": 10}))

    def test_cached_non_finite_win_rate_reads_back_as_none(self):
        """Defence in depth for a snapshot written before this fix:
        read_json_dict goes through json.loads, which ACCEPTS NaN, so the
        accessor is the last line that can keep it out of the scorer."""
        t = X._table_from_snapshot("mayhem", {
            "augments": {"7": {"win_rate": float("inf"), "num_games": 5},
                         "8": {"win_rate": 0.51, "num_games": 5}}})
        self.assertIsNone(t.win_rate(7))
        self.assertEqual(t.win_rate(8), 0.51)

    def test_bool_win_rate_is_dropped_not_scored_as_one(self):
        """_finite rejects bool, which isinstance(x, (int, float)) would
        have accepted - True would have scored as a 100 percent win rate.
        The production comment claimed this; the cycle-33 verifier noted no
        test asserted it, so it is asserted here."""
        with self.assertRaises(X.AugmentSourceError):
            X._normalize("mayhem", "tp", _payload(
                {"win_rate": True, "num_games": 10}))
        t = X._table_from_snapshot("mayhem", {
            "augments": {"7": {"win_rate": True}}})
        self.assertIsNone(t.win_rate(7))

    def test_cached_non_finite_stage_win_rate_reads_back_as_none(self):
        t = X._table_from_snapshot("mayhem", {
            "augments": {"7": {"win_rate": 0.5,
                               "stage_win_rate": {"1": float("nan"),
                                                  "2": 0.6}}}})
        self.assertIsNone(t.stage_win_rate(7, 1))
        self.assertEqual(t.stage_win_rate(7, 2), 0.6)


class ModuleHygieneTest(unittest.TestCase):
    """W4 - the repo is 7-bit ASCII in every authored byte. This module
    carried U+2192 in a raised error string at line 153."""

    def test_module_source_is_pure_ascii(self):
        src = (_PROJECT_ROOT / "core" / "augment_external_source.py").read_bytes()
        offenders = [(i, b) for i, b in enumerate(src) if b > 127]
        self.assertEqual(offenders, [], f"non-ASCII bytes at {offenders[:5]}")


if __name__ == "__main__":
    unittest.main()
