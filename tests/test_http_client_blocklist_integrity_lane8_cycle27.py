"""Lane 8 cycle 27 - deep audit of lib/http/client.py blocklist integrity.

lib/http/client.py is the single chokepoint for every outbound third-party
fetch in the tree (DDragon, the icon CDN, the aggregator D / aggregator B scrapers).
The blocklist it enforces is a SECURITY CONTROL, and it currently has zero
tests. Measured against the shipped module, the control fails OPEN in every
degraded state and crashes in three of them:

  W1  MISSING FILE at construction. `_reload_blocklist` logs
      "blocklist missing ... allowing all", empties the host set, and
      `is_blocked("https://reddit.com/x")` returns False. A deny list that
      cannot be read must not silently become an empty deny list.

  W2  CORRUPT / HALF-WRITTEN JSON at construction. Same fail-open: logs
      "blocklist parse failed ... allowing all", empties the set, returns
      False. `blocklist.json` has no atomic-write contract with its editor,
      so a reader landing mid-write is the expected transient, not an
      exotic one.

  W3  SILENT LATCH-OFF AT RUNTIME. `is_blocked` calls
      `_maybe_reload_blocklist` on EVERY call, so a client that loaded a
      good list and answered True for reddit.com answers False on the very
      next call once the file is truncated or deleted underneath it. The
      control does not just fail open at startup - it can turn itself off
      mid-process, with one warning line and no other signal.

  W4  NO SHAPE VALIDATION, silent corruption branch. `{"hostnames":
      "reddit.com"}` (a bare string, not a list) is iterated CHARACTER BY
      CHARACTER into `_blocklist_hosts == {'.','c','d','e','i','m','o','r',
      't'}`. That is not a deny list at all: it blocks any single-character
      hostname and nothing else.

  W5  NO SHAPE VALIDATION, crashing branch. `{"hostnames": [123]}` raises
      `AttributeError: 'int' object has no attribute 'lower'` and a
      top-level `[]` raises `AttributeError: 'list' object has no attribute
      'get'` - both ESCAPE the constructor, and (because the reload runs
      inside `is_blocked`) both also escape `is_blocked()` at call time,
      from a method whose signature promises a bool.

TARGET BEHAVIOUR these tests are written against:

  R1  FAIL CLOSED at construction. If the list is missing, unparseable or
      structurally invalid and no good list was ever loaded, every url is
      blocked - ordinary ones included.
  R2  LAST-KNOWN-GOOD on reload failure. If a good list was loaded and the
      file later degrades, the previously loaded hosts and suffixes are
      RETAINED. The blocklist never silently widens. It deliberately does
      NOT fail closed here: that would convert a transient mid-write into a
      total outage of all outbound fetching.
  R3  Public read-only `blocklist_ok` (bool) - True when the last load
      attempt succeeded, False when fail-closed or on last-known-good.
  R4  Shape validation. Parsed JSON must be a dict; "hostnames" and
      "suffixes" must each be absent / None or a list of str. Any violation
      is treated exactly like a parse failure (R1 or R2). No AttributeError
      may escape the constructor or `is_blocked()`, and no string may ever
      be iterated into a set of characters.
  R5  The real shipped lib/http/blocklist.json still loads cleanly.

Every test here is OFFLINE by construction: `is_blocked()` does no I/O
beyond a stat plus a read of the blocklist path, and `request()` is never
called. Faults are injected by writing real files into `tmp_path`, never by
borrowing one from the operating system - a lane 8 cycle 26 lesson (an
"open the file and expect PermissionError" injector is win32-only and goes
vacuously green on a Linux runner).
"""
from __future__ import annotations

import itertools
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from lib.http import client as http_client

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GOOD_ONE = json.dumps({
    "version": 1,
    "hostnames": ["reddit.com", "WWW.Reddit.com"],
    "suffixes": [".ru", ".xyz"],
})

# A DIFFERENT valid list. Swapping to it proves a reload really happened,
# which is what keeps the retention assertions below from passing vacuously.
GOOD_TWO = json.dumps({
    "version": 1,
    "hostnames": ["blocked.example"],
    "suffixes": [".invalidtld"],
})

HALF_WRITTEN = '{"hostnames": ["redd'

# Structurally invalid payloads. Each label is a plain str so the subTest
# kwargs stay execnet-channel-safe (tests/_subtest_channel_guard.py).
MALFORMED_SHAPES = (
    ("hostnames_is_a_bare_string", '{"hostnames": "reddit.com"}'),
    ("hostnames_holds_an_int", '{"hostnames": [123]}'),
    ("hostnames_holds_a_nested_list", '{"hostnames": [["reddit.com"]]}'),
    ("hostnames_is_an_object", '{"hostnames": {"reddit.com": true}}'),
    ("suffixes_is_a_bare_string", '{"suffixes": ".ru"}'),
    ("suffixes_holds_an_int", '{"suffixes": [1]}'),
    ("top_level_is_a_list", "[]"),
    ("top_level_is_null", "null"),
    ("top_level_is_a_string", '"reddit.com"'),
    ("top_level_is_a_number", "17"),
)

# Valid payloads that happen to select nothing. These must NOT be mistaken
# for a load failure - a fix that fails closed on an empty-but-well-formed
# list would block all outbound traffic on a legitimate configuration.
VALID_EMPTY_SHAPES = (
    ("no_keys_at_all", "{}"),
    ("both_keys_null", '{"hostnames": null, "suffixes": null}'),
    ("both_keys_empty_lists", '{"hostnames": [], "suffixes": []}'),
)

# An ordinary, never-blocked target used to detect fail-open / fail-closed.
ALLOWED_URL = "https://ddragon.leagueoflegends.com/api/versions.json"

# mtime stamps are handed out explicitly rather than left to the clock.
_MTIME_BASE = time.time() - 3600.0


def _write_blocklist(path: Path, text: str, tick: int) -> float:
    """Write `text` to `path` and stamp a DELIBERATELY distinct mtime.

    `_maybe_reload_blocklist` decides whether to re-parse by comparing
    `st_mtime` against the value cached at the last load. Two writes inside
    one clock tick can therefore land on an IDENTICAL mtime - and coarse
    filesystems quantise harder still (FAT to 2 seconds) - so the reload a
    test is trying to trigger silently does not happen, and the test then
    passes or fails for a reason that has nothing to do with the code under
    test. A test that is green because no reload occurred is a vacuous test.

    Stamping an explicit mtime 60 seconds apart per `tick` removes the
    dependency on timestamp resolution entirely. Callers additionally assert
    that consecutive stamps differ, so a filesystem that refused the stamp
    fails loudly instead of quietly weakening the test.
    """
    path.write_text(text, encoding="utf-8")
    stamp = _MTIME_BASE + 60.0 * tick
    os.utime(path, (stamp, stamp))
    return path.stat().st_mtime


class _BlocklistTestCase(unittest.TestCase):
    """Shared helpers. `tmp_path` is not used - unittest gets its own dir."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="rc_lane8_c27_")
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp = Path(self._tmpdir.name)
        self._sub_counter = itertools.count()
        self.path = self.tmp / "blocklist.json"

    # -- helpers ---------------------------------------------------------
    def _fresh_path(self) -> Path:
        """Point `self.path` at an unused directory.

        Used by the subTest matrices so each shape gets a virgin file and a
        virgin client, with no state carried over from the previous shape.
        """
        sub = self.tmp / f"case{next(self._sub_counter)}"
        sub.mkdir()
        self.path = sub / "blocklist.json"
        return self.path

    def _construct(self, path: Path) -> http_client.HttpClient:
        """Build an HttpClient, failing the test if ANY exception escapes.

        Pins W5: a malformed blocklist currently raises AttributeError out
        of `__init__`, so the process that merely CONSTRUCTS the shared
        client dies on a bad config file.
        """
        try:
            return http_client.HttpClient(blocklist_path=path)
        except Exception as exc:  # noqa: BLE001 - an escaping exception IS the defect
            self.fail(
                f"HttpClient(blocklist_path=...) raised "
                f"{type(exc).__name__}: {exc} - a malformed blocklist must be "
                f"handled like a parse failure, never propagated (R4)"
            )

    def _blocklist_ok(self, client: http_client.HttpClient) -> bool:
        """Read the R3 public flag, with a readable failure when it is absent."""
        self.assertTrue(
            hasattr(client, "blocklist_ok"),
            "HttpClient exposes no public `blocklist_ok` flag, so a caller "
            "cannot tell an enforcing client from a fail-open one (R3)",
        )
        return bool(client.blocklist_ok)


# ---------------------------------------------------------------------------
# Characterization - already correct, must stay correct through the fix.
# ---------------------------------------------------------------------------

class TestBlocklistCharacterization(_BlocklistTestCase):

    def test_a_good_blocklist_blocks_listed_hosts_and_suffixes(self):
        """Baseline enforcement. Guards against a fix that breaks matching."""
        _write_blocklist(self.path, GOOD_ONE, 1)
        client = self._construct(self.path)
        self.assertTrue(client.is_blocked("https://reddit.com/r/leagueoflegends"))
        self.assertTrue(client.is_blocked("https://something.ru/x"))
        self.assertFalse(client.is_blocked(ALLOWED_URL))

    def test_matching_is_case_insensitive(self):
        """Guards the .lower() normalisation on both sides of the compare."""
        _write_blocklist(self.path, GOOD_ONE, 1)
        client = self._construct(self.path)
        self.assertTrue(client.is_blocked("https://REDDIT.com/x"))
        self.assertTrue(client.is_blocked("https://WWW.REDDIT.COM/x"))
        self.assertTrue(client.is_blocked("https://EVIL.RU/x"))

    def test_a_url_with_no_hostname_is_blocked(self):
        """Fail-closed on an unparseable target. Already correct today."""
        _write_blocklist(self.path, GOOD_ONE, 1)
        client = self._construct(self.path)
        self.assertTrue(client.is_blocked("not-a-url"))
        self.assertTrue(client.is_blocked(""))

    def test_a_valid_edit_is_picked_up_without_a_manual_reload(self):
        """Proves the mtime stamp really drives a reload.

        This is the control for every retention test below: if this one is
        green, a later "still blocked" assertion cannot be explained away as
        "no reload ever ran".
        """
        m1 = _write_blocklist(self.path, GOOD_ONE, 1)
        client = self._construct(self.path)
        self.assertTrue(client.is_blocked("https://reddit.com/x"))

        m2 = _write_blocklist(self.path, GOOD_TWO, 2)
        self.assertNotEqual(m1, m2, "the injected mtime stamp did not land on disk")
        self.assertTrue(client.is_blocked("https://blocked.example/x"))
        self.assertFalse(
            client.is_blocked("https://reddit.com/x"),
            "the superseded entry survived the reload",
        )


# ---------------------------------------------------------------------------
# R1 - fail closed at construction when no good list was ever loaded.
# ---------------------------------------------------------------------------

class TestFailClosedAtConstruction(_BlocklistTestCase):

    def test_missing_blocklist_at_construction_blocks_everything(self):
        """Pins W1: a missing deny list currently allows every host."""
        self.assertFalse(self.path.exists())
        client = self._construct(self.path)
        self.assertTrue(
            client.is_blocked("https://reddit.com/x"),
            "a missing blocklist allowed a LISTED host through (W1 fail-open)",
        )
        self.assertTrue(
            client.is_blocked(ALLOWED_URL),
            "a missing blocklist must fail CLOSED - a security control that "
            "cannot load must not silently allow everything (R1)",
        )

    def test_corrupt_blocklist_at_construction_blocks_everything(self):
        """Pins W2: half-written JSON currently allows every host."""
        _write_blocklist(self.path, HALF_WRITTEN, 1)
        client = self._construct(self.path)
        self.assertTrue(
            client.is_blocked(ALLOWED_URL),
            "an unparseable blocklist must fail CLOSED, not empty the deny "
            "set and log a warning nobody reads (R1)",
        )

    def test_malformed_shapes_at_construction_block_everything(self):
        """Pins W4 + W5: every invalid shape must behave like a parse failure."""
        for label, payload in MALFORMED_SHAPES:
            with self.subTest(shape=label):
                _write_blocklist(self._fresh_path(), payload, 1)
                client = self._construct(self.path)
                self.assertTrue(
                    client.is_blocked(ALLOWED_URL),
                    f"structurally invalid blocklist ({label}) did not fail "
                    f"closed - it must be treated exactly like a parse "
                    f"failure (R4 -> R1)",
                )

    def test_a_bare_string_hostnames_value_is_never_iterated_into_characters(self):
        """Pins W4 directly: {"hostnames": "reddit.com"} -> a set of letters.

        The character set is not merely useless, it is actively wrong: it
        blocks single-character hostnames and lets reddit.com through.
        """
        _write_blocklist(self.path, '{"hostnames": "reddit.com"}', 1)
        client = self._construct(self.path)
        hosts = getattr(client, "_blocklist_hosts", set())
        singles = sorted(h for h in hosts if len(h) == 1)
        self.assertEqual(
            singles, [],
            f"a bare string was iterated character by character into the host "
            f"set {singles} - a str is not a list of hostnames (R4)",
        )
        self.assertTrue(
            client.is_blocked(ALLOWED_URL),
            "an invalid hostnames type must fail closed (R4 -> R1)",
        )

    def test_a_valid_but_empty_blocklist_is_not_a_failure(self):
        """Guards the fix from over-rotating.

        An empty, well-formed list is a legitimate configuration. Failing
        closed on it would block ALL outbound fetching, which is a worse
        outage than the bug being fixed.
        """
        for label, payload in VALID_EMPTY_SHAPES:
            with self.subTest(shape=label):
                _write_blocklist(self._fresh_path(), payload, 1)
                client = self._construct(self.path)
                self.assertFalse(
                    client.is_blocked(ALLOWED_URL),
                    f"a valid-but-empty blocklist ({label}) must allow "
                    f"ordinary traffic",
                )
                self.assertTrue(
                    self._blocklist_ok(client),
                    f"a valid-but-empty blocklist ({label}) loaded fine and "
                    f"must report blocklist_ok True (R3)",
                )


# ---------------------------------------------------------------------------
# R2 - last-known-good on reload failure. The blocklist never widens.
# ---------------------------------------------------------------------------

class TestLastKnownGoodOnReloadFailure(_BlocklistTestCase):

    def _good_client_then(self, degraded: str) -> http_client.HttpClient:
        """Load GOOD_ONE, swap to GOOD_TWO (reload proof), then degrade.

        The middle swap is the non-vacuity control: it establishes that the
        mtime stamps really do drive a re-parse, so the retention assertion
        afterwards cannot pass merely because nothing reloaded.
        """
        m1 = _write_blocklist(self.path, GOOD_ONE, 1)
        client = self._construct(self.path)
        self.assertTrue(client.is_blocked("https://reddit.com/x"))

        m2 = _write_blocklist(self.path, GOOD_TWO, 2)
        self.assertNotEqual(m1, m2, "the injected mtime stamp did not land on disk")
        self.assertTrue(client.is_blocked("https://blocked.example/x"))
        self.assertFalse(client.is_blocked("https://reddit.com/x"))

        if degraded == "__missing__":
            self.path.unlink()
            self.assertFalse(self.path.exists())
        else:
            m3 = _write_blocklist(self.path, degraded, 3)
            self.assertNotEqual(m2, m3, "the injected mtime stamp did not land on disk")
        return client

    def test_corrupt_reload_retains_the_last_known_good_list(self):
        """Pins W3: good -> half-written file turns the control OFF mid-process."""
        client = self._good_client_then(HALF_WRITTEN)
        self.assertTrue(
            client.is_blocked("https://blocked.example/x"),
            "a half-written blocklist SILENTLY WIDENED the allow set - the "
            "previously loaded hosts must be retained (R2)",
        )
        self.assertFalse(
            client.is_blocked(ALLOWED_URL),
            "last-known-good must not fail closed - a transient mid-write "
            "must not become a total outbound outage (R2)",
        )
        self.assertFalse(
            self._blocklist_ok(client),
            "a client running on last-known-good must report blocklist_ok "
            "False (R3) - this is also the proof the failed reload was "
            "actually observed",
        )

    def test_missing_after_good_retains_the_last_known_good_list(self):
        """Pins W3 for deletion: unlinking the file disarms a live client."""
        client = self._good_client_then("__missing__")
        self.assertTrue(
            client.is_blocked("https://blocked.example/x"),
            "deleting the blocklist SILENTLY WIDENED the allow set - the "
            "previously loaded hosts must be retained (R2)",
        )
        self.assertFalse(client.is_blocked(ALLOWED_URL))
        self.assertFalse(
            self._blocklist_ok(client),
            "a client whose blocklist vanished must report blocklist_ok "
            "False (R3)",
        )

    def test_suffix_matching_also_survives_a_failed_reload(self):
        """Retention covers suffixes, not just hostnames (R2 names both)."""
        client = self._good_client_then(HALF_WRITTEN)
        self.assertTrue(
            client.is_blocked("https://host.invalidtld/x"),
            "the retained suffix list was dropped on a failed reload (R2)",
        )

    def test_invalid_shape_reload_retains_the_last_known_good_list(self):
        """Pins W4/W5 on the reload path, not just at construction."""
        for label, payload in MALFORMED_SHAPES:
            with self.subTest(shape=label):
                self._fresh_path()  # virgin file + virgin client per shape
                client = self._good_client_then(payload)
                self.assertTrue(
                    client.is_blocked("https://blocked.example/x"),
                    f"a structurally invalid reload ({label}) widened the "
                    f"allow set instead of retaining last-known-good (R2)",
                )

    def test_is_blocked_never_raises_on_a_degraded_reload(self):
        """Pins W5 at CALL time.

        The reload runs inside `is_blocked`, so today an AttributeError
        escapes a method whose signature promises a bool - from a call site
        that has no reason to guard a blocklist lookup.
        """
        for label, payload in MALFORMED_SHAPES:
            with self.subTest(shape=label):
                self._fresh_path()
                m1 = _write_blocklist(self.path, GOOD_ONE, 1)
                client = self._construct(self.path)
                self.assertTrue(client.is_blocked("https://reddit.com/x"))
                m2 = _write_blocklist(self.path, payload, 2)
                self.assertNotEqual(m1, m2, "the injected mtime stamp did not land on disk")
                try:
                    verdict = client.is_blocked("https://reddit.com/x")
                except Exception as exc:  # noqa: BLE001 - an escaping exception IS the defect
                    self.fail(
                        f"is_blocked() raised {type(exc).__name__}: {exc} on a "
                        f"{label} blocklist - it must return a bool for every "
                        f"on-disk state (R4)"
                    )
                self.assertIsInstance(verdict, bool)


# ---------------------------------------------------------------------------
# R3 - blocklist_ok, asserted in both directions.
# ---------------------------------------------------------------------------

class TestBlocklistOkFlag(_BlocklistTestCase):

    def test_blocklist_ok_is_true_after_a_clean_load(self):
        """R3 positive direction. No such flag exists today."""
        _write_blocklist(self.path, GOOD_ONE, 1)
        client = self._construct(self.path)
        self.assertTrue(
            self._blocklist_ok(client),
            "a cleanly loaded blocklist must report blocklist_ok True (R3)",
        )

    def test_blocklist_ok_is_false_when_fail_closed(self):
        """R3 negative direction, fail-closed branch."""
        client = self._construct(self.path)  # file never created
        self.assertFalse(
            self._blocklist_ok(client),
            "a fail-closed client must report blocklist_ok False (R3)",
        )

    def test_blocklist_ok_is_false_for_every_malformed_shape(self):
        """R3 negative direction across the whole R4 shape matrix."""
        for label, payload in MALFORMED_SHAPES:
            with self.subTest(shape=label):
                _write_blocklist(self._fresh_path(), payload, 1)
                client = self._construct(self.path)
                self.assertFalse(
                    self._blocklist_ok(client),
                    f"a structurally invalid blocklist ({label}) must report "
                    f"blocklist_ok False (R3)",
                )

    def test_blocklist_ok_recovers_when_the_file_is_repaired(self):
        """A degraded client must not latch OFF permanently.

        Fail-closed and last-known-good are both transient states; once the
        file parses again the client returns to normal enforcement.
        """
        m1 = _write_blocklist(self.path, HALF_WRITTEN, 1)
        client = self._construct(self.path)
        self.assertFalse(self._blocklist_ok(client))

        m2 = _write_blocklist(self.path, GOOD_ONE, 2)
        self.assertNotEqual(m1, m2, "the injected mtime stamp did not land on disk")
        self.assertTrue(client.is_blocked("https://reddit.com/x"))
        self.assertFalse(client.is_blocked(ALLOWED_URL))
        self.assertTrue(
            self._blocklist_ok(client),
            "a repaired blocklist must clear the degraded flag (R3)",
        )

    def test_a_repair_that_reuses_the_same_mtime_still_recovers(self):
        """BEYOND R1-R5, deliberately - a permanent-degradation hole.

        The shipped `_reload_blocklist` caches `stat.st_mtime` even on the
        parse-failure branch, and `_maybe_reload_blocklist` re-parses only
        when the mtime CHANGES. So the most likely real sequence -

            writer truncates the file
            reader stats + reads the truncated content, caches that mtime
            writer finishes the write inside the SAME clock tick

        - leaves a perfectly good file on disk that the client never looks
        at again. Today that is a permanent fail-open; under R1/R2 it
        becomes a permanent fail-closed or a permanently stale list, which
        is worse. A degraded client must therefore RETRY the parse rather
        than trust the mtime of a load it already knows failed.

        The cost is one extra read per is_blocked() call while degraded,
        which is the right trade for a control that is currently wrong.
        """
        m1 = _write_blocklist(self.path, HALF_WRITTEN, 1)
        client = self._construct(self.path)

        m2 = _write_blocklist(self.path, GOOD_ONE, 1)  # same tick on purpose
        self.assertEqual(m1, m2, "this test needs an IDENTICAL mtime to be meaningful")
        self.assertTrue(
            client.is_blocked("https://reddit.com/x"),
            "a degraded client cached the mtime of a load it knew had FAILED, "
            "so a repaired file is never re-read and the degradation is "
            "permanent",
        )
        self.assertTrue(self._blocklist_ok(client))


# ---------------------------------------------------------------------------
# R5 - the real shipped policy file still loads.
# ---------------------------------------------------------------------------

class TestShippedBlocklist(unittest.TestCase):
    """Read-only against the repo's own blocklist.json. Never mutated.

    The path is taken from the module's own constant rather than written
    out, so nothing here depends on the absolute path of the worktree it
    runs in.
    """

    def setUp(self) -> None:
        self.shipped = Path(http_client._BLOCKLIST_PATH)

    def test_the_shipped_blocklist_exists_where_the_module_looks_for_it(self):
        """Guards the packaged-path assumption the whole control rests on."""
        self.assertTrue(
            self.shipped.is_file(),
            f"the shipped blocklist is missing at {self.shipped.name} under "
            f"{self.shipped.parent.name}/",
        )
        self.assertEqual(self.shipped.name, "blocklist.json")

    def test_the_shipped_blocklist_still_enforces_its_policy(self):
        """R5 enforcement half. Green today, must survive the fix."""
        client = http_client.HttpClient()
        self.assertTrue(client.is_blocked("https://reddit.com/r/leagueoflegends"))
        self.assertTrue(client.is_blocked("https://www.tiktok.com/x"))
        self.assertTrue(client.is_blocked("https://example.ru/x"))
        self.assertFalse(client.is_blocked(ALLOWED_URL))

    def test_the_shipped_blocklist_reports_a_clean_load(self):
        """R5 signal half - the real policy file must not read as degraded."""
        client = http_client.HttpClient()
        self.assertTrue(
            hasattr(client, "blocklist_ok"),
            "HttpClient exposes no public `blocklist_ok` flag (R3)",
        )
        self.assertTrue(
            client.blocklist_ok,
            "the shipped blocklist.json must load cleanly (R5)",
        )


if __name__ == "__main__":
    unittest.main()
