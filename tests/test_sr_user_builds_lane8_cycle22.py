"""Lane 8 cycle 22 - deep audit of coaches/sr_user_builds.py + its CRUD route.

Every test here was RED before the fix in the same slice and names the
weakness it pins. The store is reached by an UNAUTHENTICATED CRUD route
(dashboard/routes_sr_user_builds.py, spliced into :8888 by
dashboard/_dispatch.py:168+208) and its reads feed three further consumers -
coaches/rune_pages.py:142, dashboard/routes_loadout.py:105 and :182 - so a
phantom or torn read does not stay inside this module.

Weaknesses pinned:
  W1 a corrupt user_builds.json was swallowed by _load's blanket except,
     served as an EMPTY store, and then permanently OVERWRITTEN by the next
     add() - measured destruction of operator-curated data.
  W2 _load() handed back the shared _CACHE dict AND the shared per-champion
     list; list_for read it with no lock while add/update/delete mutated
     that exact list in place.
  W3 the handler called payload.get() with no isinstance check, so a direct
     call with a JSON list or null answered 500 instead of 400. DEFENCE IN
     DEPTH only: a live probe showed dashboard/_handler.py:525 already
     rejects non-dict POST bodies at the single trust boundary, and this
     route has no :8895 surface (mc/routes.py:16 splices only
     routes_loop_status + routes_loop_control). Kept because the handler
     must not depend on a caller it does not control.
  W4 the 400 path echoed str(exc) verbatim - the un-scrubbed shape RM-134
     exists to prevent.
  W5 champion / label / notes / items / per-champion counts were unbounded
     on an unauthenticated write path.
  W6 an exhausted os.replace retry re-raised and orphaned the .tmp file.
  W7 mutators mutated the SHARED cache before the write was committed, so a
     failed save left a phantom build visible to every reader.
  W8 _gen_id's docstring claimed "~16M unique" for a 4-byte token (~4.3e9).
  W9 add() had no id-collision guard.
"""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from coaches import sr_user_builds
import dashboard.routes_sr_user_builds as routes


class _HermeticStoreCase(unittest.TestCase):
    """Redirect _STORE_PATH to a tempdir so the real store is never touched."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store_path = Path(self._tmp.name) / "user_builds.json"
        self._patcher = mock.patch.object(
            sr_user_builds, "_STORE_PATH", self.store_path,
        )
        self._patcher.start()
        sr_user_builds.clear_cache()

    def tearDown(self):
        self._patcher.stop()
        sr_user_builds.clear_cache()
        self._tmp.cleanup()

    def _seed(self, payload):
        self.store_path.write_text(json.dumps(payload), encoding="utf-8")
        sr_user_builds.clear_cache()

    def _seed_one(self, champion="Tristana", label="real build"):
        self._seed({
            "champions": {champion: [
                {"id": "aabbccdd", "label": label, "mode": "sr",
                 "items": ["Kraken Slayer"], "runes": {}, "notes": "",
                 "summoner_spells": [4, 7],
                 "created_at": 1, "updated_at": 1},
            ]},
            "_schema_version": 1,
        })


class _FakeHandler:
    """Minimal stand-in for the dashboard handler - records the response."""

    def __init__(self, path="/api/sr-draft/user-builds"):
        self.path = path
        self.status = None
        self.body = None

    def _send(self, status, body, ctype):
        self.status = status
        self.body = body

    def json(self):
        return json.loads(self.body.decode("utf-8"))


# -- W1: a corrupt store must never be silently destroyed ---------------

class TestCorruptStoreIsPreserved(_HermeticStoreCase):

    def test_add_after_corruption_does_not_destroy_the_original_bytes(self):
        """W1. The pre-fix chain was: corrupt file -> blanket except ->
        empty store -> add() writes the empty store over it. The operator's
        builds were gone, with only a log warning."""
        original = '{"champions": {"Tristana": [{"id": "aa", '  # truncated JSON
        self.store_path.write_text(original, encoding="utf-8")
        sr_user_builds.clear_cache()

        sr_user_builds.add("Jhin", {"label": "new build"})

        quarantined = list(self.store_path.parent.glob("user_builds.corrupt-*.json"))
        self.assertEqual(len(quarantined), 1,
                         "the unparseable store must be quarantined, not dropped")
        self.assertEqual(quarantined[0].read_text(encoding="utf-8"), original,
                         "quarantine must preserve the original bytes verbatim")

    def test_corrupt_store_still_reads_as_empty_so_the_panel_renders(self):
        """The degraded read stays fail-soft - the dashboard must not hard-fail
        (feedback_no_reflow_on_data_absence)."""
        self.store_path.write_text("{ not json", encoding="utf-8")
        sr_user_builds.clear_cache()
        self.assertEqual(sr_user_builds.list_for("Tristana"), [])

    def test_quarantine_happens_once_not_on_every_read(self):
        """A repeated read must not spray one quarantine file per call."""
        self.store_path.write_text("{ not json", encoding="utf-8")
        sr_user_builds.clear_cache()
        for _ in range(5):
            sr_user_builds.list_for("Tristana")
        self.assertLessEqual(
            len(list(self.store_path.parent.glob("user_builds.corrupt-*.json"))), 1)


# -- W2 / W7: uncommitted mutations must never be visible ---------------

class TestNoPhantomStateOnFailedSave(_HermeticStoreCase):

    def test_failed_add_leaves_no_phantom_build_in_memory(self):
        """W7. Measured pre-fix: os.replace fails, add() raises, and
        list_for STILL reported the uncommitted build - which
        coaches/rune_pages.py:142 would then fold into a live rune page."""
        self._seed_one()
        with mock.patch.object(sr_user_builds.os, "replace",
                               side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                sr_user_builds.add("Tristana", {"label": "ghost build"})

        labels = [b["label"] for b in sr_user_builds.list_for("Tristana")]
        self.assertNotIn("ghost build", labels,
                         "an uncommitted build must not be visible to readers")
        self.assertEqual(labels, ["real build"])

    def test_failed_delete_does_not_drop_the_build_from_memory(self):
        """W7, the destructive direction: a failed save must not make a build
        disappear from the in-memory view while it is still on disk."""
        self._seed_one()
        with mock.patch.object(sr_user_builds.os, "replace",
                               side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                sr_user_builds.delete("Tristana", "aabbccdd")

        labels = [b["label"] for b in sr_user_builds.list_for("Tristana")]
        self.assertEqual(labels, ["real build"])

    def test_load_does_not_hand_out_the_shared_mutable_cache(self):
        """W2. _load() returned the shared _CACHE object and the shared
        per-champion list, so a caller could mutate the cache in place."""
        self._seed_one()
        first = sr_user_builds._load()
        first.setdefault("champions", {}).setdefault("Tristana", []).append(
            {"id": "zz", "label": "injected"})
        labels = [b["label"] for b in sr_user_builds.list_for("Tristana")]
        self.assertNotIn("injected", labels,
                         "mutating a _load() result must not reach the cache")

    def test_concurrent_reads_and_deletes_never_tear(self):
        """W2. list_for read the shared list with no lock while delete()
        popped from it. Every snapshot must be internally consistent."""
        builds = [{"id": f"{i:08x}", "label": f"b{i}", "mode": "sr",
                   "items": ["x"], "runes": {}, "notes": "",
                   "summoner_spells": [4, 7], "created_at": 1, "updated_at": 1}
                  for i in range(150)]
        self._seed({"champions": {"T": builds}, "_schema_version": 1})

        errors = []
        seen_bad = []

        def reader():
            for _ in range(200):
                try:
                    snap = sr_user_builds.list_for("T")
                except Exception as exc:  # noqa: BLE001
                    errors.append(repr(exc))
                    return
                ids = [b.get("id") for b in snap]
                if len(ids) != len(set(ids)):
                    seen_bad.append("duplicate ids in one snapshot")
                    return

        def deleter():
            for i in range(150):
                sr_user_builds.delete("T", f"{i:08x}")

        threads = [threading.Thread(target=reader) for _ in range(3)]
        threads.append(threading.Thread(target=deleter))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], "a concurrent read must not raise")
        self.assertEqual(seen_bad, [], "a snapshot must never be torn")


# -- W6: the tmp file must not leak --------------------------------------

class TestTempFileLifetime(_HermeticStoreCase):

    def test_exhausted_replace_retry_cleans_up_its_tmp(self):
        """W6. Pre-fix the retry re-raised and orphaned user_builds.json.tmp."""
        self._seed_one()
        with mock.patch.object(sr_user_builds.os, "replace",
                               side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                sr_user_builds.add("Tristana", {"label": "x"})

        leaked = [p.name for p in self.store_path.parent.iterdir()
                  if p.name.endswith(".tmp")]
        self.assertEqual(leaked, [], "the scratch file must not be orphaned")


# -- W5: bounded input on an unauthenticated write path -------------------

class TestInputBounds(_HermeticStoreCase):

    def test_champion_key_length_is_capped(self):
        with self.assertRaises(ValueError):
            sr_user_builds.add("T" * 500, {"label": "x"})

    def test_label_is_truncated_not_stored_unbounded(self):
        new_id = sr_user_builds.add("Tristana", {"label": "L" * 10_000})
        stored = sr_user_builds.list_for("Tristana")[0]
        self.assertEqual(stored["id"], new_id)
        self.assertLessEqual(len(stored["label"]), sr_user_builds.MAX_LABEL_LEN)

    def test_notes_are_truncated(self):
        sr_user_builds.add("Tristana", {"label": "x", "notes": "N" * 50_000})
        stored = sr_user_builds.list_for("Tristana")[0]
        self.assertLessEqual(len(stored["notes"]), sr_user_builds.MAX_NOTES_LEN)

    def test_items_list_is_capped(self):
        sr_user_builds.add("Tristana",
                           {"label": "x", "items": [f"i{i}" for i in range(500)]})
        stored = sr_user_builds.list_for("Tristana")[0]
        self.assertLessEqual(len(stored["items"]), sr_user_builds.MAX_ITEMS)

    def test_builds_per_champion_is_capped(self):
        for i in range(sr_user_builds.MAX_BUILDS_PER_CHAMPION):
            sr_user_builds.add("Tristana", {"label": f"b{i}"})
        with self.assertRaises(ValueError):
            sr_user_builds.add("Tristana", {"label": "one too many"})

    def test_champion_count_is_capped(self):
        with mock.patch.object(sr_user_builds, "MAX_CHAMPIONS", 3):
            for i in range(3):
                sr_user_builds.add(f"C{i}", {"label": "x"})
            with self.assertRaises(ValueError):
                sr_user_builds.add("C99", {"label": "x"})

    def test_an_existing_champion_still_accepts_writes_at_the_cap(self):
        """The champion cap must bound NEW keys only - it must not lock the
        operator out of a champion they already curate."""
        with mock.patch.object(sr_user_builds, "MAX_CHAMPIONS", 2):
            sr_user_builds.add("C0", {"label": "x"})
            sr_user_builds.add("C1", {"label": "x"})
            sr_user_builds.add("C0", {"label": "second build"})
        self.assertEqual(len(sr_user_builds.list_for("C0")), 2)


# -- W9: id collisions ----------------------------------------------------

class TestIdCollision(_HermeticStoreCase):

    def test_add_never_reuses_an_id_already_present(self):
        """W9. delete()/update() match the FIRST id, so a duplicate id makes
        them act on the wrong build."""
        self._seed_one()
        with mock.patch.object(sr_user_builds, "_gen_id",
                               side_effect=["aabbccdd", "aabbccdd", "11223344"]):
            new_id = sr_user_builds.add("Tristana", {"label": "second"})
        self.assertEqual(new_id, "11223344")
        ids = [b["id"] for b in sr_user_builds.list_for("Tristana")]
        self.assertEqual(len(ids), len(set(ids)))


# -- W8: the docstring must match the code -------------------------------

class TestDocstringMatchesCode(unittest.TestCase):

    def test_gen_id_docstring_states_the_real_id_space(self):
        """W8. The docstring claimed "~16M unique" - the figure for a 3-byte
        token. secrets.token_hex(4) is 4 bytes, so the space is 16**8, about
        4.3e9: the claim was wrong by 256x.

        Asserting merely that "16M" is absent would be the weaker test, and it
        fails against a docstring that quotes the old claim while correcting
        it. Pin the corrected magnitude instead
        (feedback_negative_assertion_rules_out_without_pinning_down)."""
        doc = sr_user_builds._gen_id.__doc__ or ""
        self.assertIn("4.3e9", doc)
        self.assertEqual(len(sr_user_builds._gen_id()) * 4, 32,
                         "8 hex chars is a 32-bit space, matching the docstring")

    def test_gen_id_really_returns_8_hex_chars(self):
        val = sr_user_builds._gen_id()
        self.assertEqual(len(val), 8)
        int(val, 16)


# -- W3 / W4: the route trust boundary -----------------------------------

class TestRouteTrustBoundary(_HermeticStoreCase):

    def test_non_dict_payload_is_a_400_not_a_500(self):
        """W3. payload.get() on a list/None raised AttributeError and the
        blanket handler turned a client error into a server error.

        This pins the HANDLER, which is the unit that must be correct on its
        own. On the live :8888 path dashboard/_handler.py:525 already returns
        400 first, so this is defence in depth, not a reachable 500 - the
        severity was downgraded after probing the running dashboard rather
        than inferring it from this direct call."""
        for bad in (["not", "a", "dict"], None, "string", 7):
            with self.subTest(bad=type(bad).__name__):
                h = _FakeHandler()
                routes._serve_user_builds_post(h, bad)
                self.assertEqual(h.status, 400)

    def test_validation_400_does_not_echo_raw_exception_text(self):
        """W4. The 400 path sent json.dumps({"error": str(exc)}) verbatim.

        Asserting only on the store's OWN short messages would be vacuous -
        they are RC-authored and harmless, so the pre-fix code passed such a
        check (feedback_negative_assertion_rules_out_without_pinning_down).
        The real question is what happens when a ValueError carries something
        the client must not see, so that is what this raises."""
        leaky = ("C:\\Riot Commander\\API-Key-Claude.txt "
                 "sk-ant-secret-value-do-not-leak")
        h = _FakeHandler()
        with mock.patch.object(sr_user_builds, "add",
                               side_effect=ValueError(leaky)):
            routes._serve_user_builds_post(
                h, {"champion": "Tristana", "action": "add",
                    "build": {"label": "x"}})
        self.assertEqual(h.status, 400)
        wire = h.body.decode("utf-8")
        self.assertNotIn("sk-ant-secret-value-do-not-leak", wire)
        self.assertNotIn("API-Key-Claude.txt", wire)

    def test_curated_validation_message_still_reaches_the_client(self):
        """The scrub must not flatten the useful 400s into one opaque line -
        a caller still needs to know WHICH field was wrong."""
        h = _FakeHandler()
        routes._serve_user_builds_post(
            h, {"champion": "Tristana", "action": "add", "build": {"label": ""}})
        self.assertEqual(h.status, 400)
        self.assertIn("label", h.json()["error"].lower())

    def test_unexpected_store_failure_is_scrubbed(self):
        """An unexpected exception must never reach the wire."""
        h = _FakeHandler()
        secret = "sk-ant-do-not-leak-abcdef"
        with mock.patch.object(sr_user_builds, "add",
                               side_effect=RuntimeError(secret)):
            routes._serve_user_builds_post(
                h, {"champion": "Tristana", "action": "add",
                    "build": {"label": "x"}})
        self.assertEqual(h.status, 500)
        self.assertNotIn(secret, h.body.decode("utf-8"))

    def test_over_long_champion_from_the_route_is_a_400(self):
        h = _FakeHandler()
        routes._serve_user_builds_post(
            h, {"champion": "T" * 5000, "action": "add",
                "build": {"label": "x"}})
        self.assertEqual(h.status, 400)

    def test_happy_path_still_works(self):
        """Characterization: the fix must not change the working contract."""
        h = _FakeHandler()
        routes._serve_user_builds_post(
            h, {"champion": "Tristana", "action": "add",
                "build": {"label": "lethality rush", "items": ["Opportunity"]}})
        self.assertEqual(h.status, 200)
        self.assertTrue(h.json()["ok"])

        h2 = _FakeHandler()
        routes._serve_user_builds_post(
            h2, {"champion": "Tristana", "action": "list"})
        self.assertEqual(h2.status, 200)
        self.assertEqual(len(h2.json()["builds"]), 1)


if __name__ == "__main__":
    unittest.main()
