# arch: RM-331 Arena augment display-name alias resolution | section=daemon_slayer | frozen=no
"""RM-331: an Arena augment passed by DISPLAY name must resolve.

The defect (probed live, re-probed independently, source-read):
``DataSnapshot.arena_augment`` looked its key up EXACT-match against
``arena_augments_by_api``, so ``"The Brutalizer"`` (the display ``name``
that a human types, and that RC's own OCR layer surfaces) missed, the
miss was swallowed at ``agents/daemon_slayer/augments.py:227``
(``except (KeyError, AttributeError): continue``), and the request
scored BYTE-IDENTICALLY to sending no augment at all - a silent ~10 pct
DPS error that presents as a correct answer.

The asymmetry that makes this a bug rather than a documented contract:
the NUMERIC path was already spelling-tolerant (``82`` and ``"82"`` both
resolve, because ``arena_augment`` re-parses digit strings), so the same
parameter accepted two spellings of the id but rejected the one spelling
a human would type - and no route docstring anywhere states an
apiName-only contract for augments.

WHY THE EXISTING SUITE DID NOT CATCH IT:
``test_arena_augment_e2e_p1l26.py:245-259`` asserts that an UNREGISTERED
augment leaves the baseline byte-identical. That is exactly what a
MISSPELLED REAL augment produced, so that assertion could not tell the
two apart. Every test in this lane therefore carries BOTH halves:

  1. the alias arm equals the exact-apiName arm, AND
  2. both differ from the ``augments=[]`` baseline.

Without (2) the lane passes when BOTH arms silently drop the augment,
which is the precise failure mode being fixed here.

Discipline: no engine-output magic numbers. Every expected value is
either read from the snapshot's own augment record inside the test or
asserted RELATIONALLY against a control computed in the same test, so a
snapshot refresh cannot make this lane vacuously green.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps

# Snapshot anchors, re-validated against the snapshot in
# ArenaAugmentAliasSetupTests so a data refresh that moves them fails
# loudly here instead of silently weakening the lane.
_AUG_ID = 82                    # numeric id
_AUG_API = "TheBrutalizer"      # apiName (the only spelling that worked)
_AUG_NAME = "The Brutalizer"    # display name (silently dropped before RM-331)

# The RM-331 probe body: Jinx L13 ARENA, the exact request the defect was
# measured on. AD champion + AD augment, so a resolved augment MUST move
# weighted_dps.
_PROBE = dict(
    champion_id="Jinx",
    level=13,
    item_ids=["3031", "3006", "3094"],
    mode="ARENA",
    target_armor=80.0,
    target_mr=50.0,
)


def _norm(s: str) -> str:
    """Test-local copy of the alnum-lowercase convention, deliberately
    NOT imported from the module under test: the census below must be
    able to disagree with the implementation."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


class ArenaAugmentAliasSetupTests(unittest.TestCase):
    """State the data assumptions explicitly before relying on them."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_anchor_augment_row_shape(self) -> None:
        rec = self.snap.arena_augments_by_id[_AUG_ID]
        self.assertEqual(rec.get("apiName"), _AUG_API)
        self.assertEqual(rec.get("name"), _AUG_NAME)
        # The two spellings must be genuinely different strings that
        # collapse to the same normalized key, otherwise this lane is
        # testing nothing.
        self.assertNotEqual(_AUG_API, _AUG_NAME)
        self.assertEqual(_norm(_AUG_API), _norm(_AUG_NAME))

    def test_anchor_augment_actually_moves_arena_dps(self) -> None:
        # Control for the whole lane: the exact-apiName spelling really
        # does change weighted_dps on this body. If this ever stops
        # holding, every equality assertion below would be vacuous.
        base = compute_dps(self.snap, augments=[], **_PROBE).weighted_dps
        api = compute_dps(self.snap, augments=[_AUG_API], **_PROBE).weighted_dps
        self.assertGreater(api, base)


class ArenaAugmentDisplayNameResolvesTests(unittest.TestCase):
    """RM-331 acceptance, both halves load-bearing."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        cls.baseline = compute_dps(cls.snap, augments=[], **_PROBE).weighted_dps
        cls.expected = compute_dps(
            cls.snap, augments=[_AUG_API], **_PROBE
        ).weighted_dps

    def _assert_resolves(self, spelling) -> None:
        got = compute_dps(self.snap, augments=[spelling], **_PROBE).weighted_dps
        # Half 1: this spelling scores the same as the exact apiName.
        self.assertAlmostEqual(
            got, self.expected, places=9,
            msg=f"{spelling!r} must resolve to the same augment as "
                f"{_AUG_API!r}",
        )
        # Half 2 (load-bearing): and that value is NOT the no-augment
        # baseline, so the test cannot pass by both arms dropping it.
        self.assertNotAlmostEqual(
            got, self.baseline, places=9,
            msg=f"{spelling!r} scored identically to augments=[] - the "
                "augment was silently dropped in BOTH arms",
        )

    def test_display_name_with_space(self) -> None:
        self._assert_resolves(_AUG_NAME)

    def test_lowercase_no_space(self) -> None:
        self._assert_resolves("thebrutalizer")

    def test_lowercase_with_space(self) -> None:
        self._assert_resolves("the brutalizer")

    def test_punctuated_and_padded(self) -> None:
        self._assert_resolves("  The-Brutalizer!  ")

    def test_numeric_id_int_still_resolves(self) -> None:
        self._assert_resolves(_AUG_ID)

    def test_numeric_id_str_still_resolves(self) -> None:
        self._assert_resolves(str(_AUG_ID))

    def test_exact_api_name_still_resolves(self) -> None:
        # Regression fence on the path that already worked.
        self._assert_resolves(_AUG_API)

    def test_unknown_augment_is_still_a_no_op(self) -> None:
        # The alias index must not become a fuzzy matcher: a genuinely
        # unregistered string still resolves to nothing and leaves the
        # baseline byte-identical (the documented progressive contract
        # that test_arena_augment_e2e_p1l26.py pins at the rank layer).
        got = compute_dps(
            self.snap, augments=["NoSuchAugment_rm331_zzz"], **_PROBE
        ).weighted_dps
        self.assertAlmostEqual(got, self.baseline, places=9)
        # And an empty / whitespace-only key must not resolve either.
        for junk in ("", "   ", "!!!"):
            with self.subTest(junk=junk):
                self.assertAlmostEqual(
                    compute_dps(
                        self.snap, augments=[junk], **_PROBE
                    ).weighted_dps,
                    self.baseline,
                    places=9,
                )


class ArenaAugmentAliasIndexIntegrityTests(unittest.TestCase):
    """The alias index must be total, unambiguous and apiName-dominant,
    on EVERY shipped snapshot - not just the current one."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _shipped_patches(self):
        root = self.snap.data_root
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            if (d / "arena_augments.json").exists():
                yield d.name

    def test_every_augment_resolves_by_api_name_and_by_display_name(self) -> None:
        rows = list(self.snap.arena_augments_by_id.values())
        self.assertGreater(len(rows), 100, "snapshot lost its augment table")
        for rec in rows:
            api = rec.get("apiName")
            name = rec.get("name")
            if api:
                self.assertIs(self.snap.arena_augment(api), rec)
                self.assertIs(self.snap.arena_augment(api.lower()), rec)
            if name:
                # The display-name arm is what RM-331 adds.
                self.assertIs(self.snap.arena_augment(name), rec)
            self.assertIs(self.snap.arena_augment(int(rec["id"])), rec)
            self.assertIs(self.snap.arena_augment(str(rec["id"])), rec)

    def test_alias_collision_census_is_zero_on_every_shipped_snapshot(self) -> None:
        # RM-331 collision risk: two DIFFERENT augments whose normalized
        # name and apiName collide. Census every shipped snapshot; the
        # measured answer is zero, and this test is the guard that keeps
        # it that way (a future snapshot that introduces one fails HERE,
        # loudly, rather than silently shadowing an augment).
        checked = 0
        total_cross = 0
        for patch in self._shipped_patches():
            snap = DataSnapshot.load(patch=patch)
            by_api: dict[str, int] = {}
            by_name: dict[str, int] = {}
            for rec in snap.arena_augments_by_id.values():
                aid = int(rec["id"])
                if rec.get("apiName"):
                    k = _norm(rec["apiName"])
                    self.assertNotIn(
                        k, by_api,
                        msg=f"{patch}: two augments share normalized "
                            f"apiName {k!r}",
                    )
                    by_api[k] = aid
                if rec.get("name"):
                    k = _norm(rec["name"])
                    self.assertNotIn(
                        k, by_name,
                        msg=f"{patch}: two augments share normalized "
                            f"name {k!r}",
                    )
                    by_name[k] = aid
            cross = {
                k for k, aid in by_name.items()
                if k in by_api and by_api[k] != aid
            }
            total_cross += len(cross)
            checked += 1
            self.assertEqual(
                cross, set(),
                msg=f"{patch}: display name(s) {sorted(cross)} normalize "
                    "onto a DIFFERENT augment's apiName",
            )
        # Guard against a vacuous zero-iteration census. Deliberately NOT
        # "> 1": this is a floor on the census running at all, not a pin on
        # how many snapshots the tree happens to ship (6 today, 16.10.1
        # through 16.15.1), so pruning back to the current patch alone
        # still exercises the lane rather than breaking it.
        self.assertGreaterEqual(
            checked, 1, "census iterated no snapshots at all"
        )
        self.assertEqual(total_cross, 0)

    def test_api_name_wins_over_a_colliding_display_name(self) -> None:
        # Explicit tie-break contract, exercised on a synthetic table so
        # it is provable today even though the real census is zero.
        rows = [
            {"id": 900001, "apiName": "Alpha", "name": "Zulu"},
            {"id": 900002, "apiName": "Zulu", "name": "Something Else"},
        ]
        snap = DataSnapshot(
            patch="synthetic-rm331",
            manifest={},
            champions={},
            items={},
            scenarios_by_id={},
            scenarios_by_lolmath={},
            arena_augments_by_id={int(r["id"]): r for r in rows},
            arena_augments_by_api={r["apiName"]: r for r in rows},
            data_root=self.snap.data_root,
        )
        # "Zulu" is row 1's display name AND row 2's apiName: apiName wins.
        self.assertIs(snap.arena_augment("Zulu"), rows[1])
        self.assertIs(snap.arena_augment("zulu"), rows[1])
        # Row 1 is still reachable by its own apiName and its id.
        self.assertIs(snap.arena_augment("alpha"), rows[0])
        self.assertIs(snap.arena_augment(900001), rows[0])

    def test_unknown_key_still_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            self.snap.arena_augment("NoSuchAugment_rm331_zzz")
        with self.assertRaises(KeyError):
            self.snap.arena_augment(-12345)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
