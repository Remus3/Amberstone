"""The gate that replaces `462f1255`'s by-eye sweep of 461 subTest sites.

`462f1255` fixed the five `subTest`-serialization instances and recorded
"swept every other subTest call site" in its commit body. Prose is not a
gate. These tests pin the guard installed by the repo-root `conftest.py`,
which turns an xdist-only failure into an every-run failure at the call
site.

The measured serializer grammar is asserted directly, because the whole
defect is that people guess at it - `test_aram_action_rule.py` shipped a
docstring claiming `set()` fails, and it does not.
"""
from __future__ import annotations

import unittest

from tests._subtest_channel_guard import (
    is_channel_safe,
    offending_params,
)


class ChannelSafetyGrammarTests(unittest.TestCase):
    """What execnet will and will not put on the worker->master channel."""

    SAFE = [None, True, 7, 1.5, complex(1, 2), "x", b"y",
            [1, 2], (1, "a"), {"k": 1}, {1, 2}, frozenset([3]),
            [None, "x", 5]]

    def test_primitives_and_their_containers_are_safe(self) -> None:
        for value in self.SAFE:
            with self.subTest(value=repr(value)):
                self.assertTrue(is_channel_safe(value))

    def test_a_bare_object_is_not_safe(self) -> None:
        self.assertFalse(is_channel_safe(object()))

    def test_a_container_of_objects_is_not_safe(self) -> None:
        # The serializer recurses, so the container type does not launder it.
        for value in ([object()], (object(),), {"k": object()}):
            with self.subTest(value=type(value).__name__):
                self.assertFalse(is_channel_safe(value))

    def test_a_set_is_safe_correcting_the_shipped_docstring(self) -> None:
        # test_aram_action_rule.py claimed a set() raises DumpError. Measured
        # 2026-07-28: it does not. Pinned so the claim cannot drift back.
        self.assertTrue(is_channel_safe(set()))
        self.assertTrue(is_channel_safe({1, "a"}))


class OffendingParamsTests(unittest.TestCase):
    """The reporting half - which argument names are named."""

    _SENTINEL = unittest.case._subtest_msg_sentinel

    def test_clean_params_report_nothing(self) -> None:
        self.assertEqual(offending_params(self._SENTINEL, {"a": 1}), [])

    def test_the_offending_kwarg_is_named(self) -> None:
        self.assertEqual(
            offending_params(self._SENTINEL, {"ok": 1, "bad": object()}),
            ["bad"])

    def test_an_unserializable_msg_is_caught_too(self) -> None:
        self.assertEqual(offending_params(object(), {}), ["msg"])

    def test_a_plain_string_msg_is_fine(self) -> None:
        self.assertEqual(offending_params("scenario 1", {"a": 1}), [])


class GuardIsInstalledTests(unittest.TestCase):
    """End-to-end: the live `self.subTest` raises on a hostile kwarg."""

    def test_the_guard_is_the_active_subtest(self) -> None:
        self.assertTrue(
            getattr(unittest.TestCase.subTest, "_rc_channel_guard", False),
            "repo-root conftest.py did not install the subTest channel guard")

    def test_a_hostile_kwarg_raises_here_not_under_xdist_only(self) -> None:
        with self.assertRaises(TypeError) as caught:
            with self.subTest(bad=object()):
                pass
        message = str(caught.exception)
        self.assertIn("'bad'", message)
        self.assertIn("repr(", message)

    def test_a_safe_kwarg_still_runs_the_body(self) -> None:
        ran = []
        with self.subTest(good="value"):
            ran.append(1)
        self.assertEqual(ran, [1])

    def test_installation_is_idempotent(self) -> None:
        from tests._subtest_channel_guard import install

        before = unittest.TestCase.subTest
        install()
        self.assertIs(unittest.TestCase.subTest, before)


if __name__ == "__main__":
    unittest.main()
