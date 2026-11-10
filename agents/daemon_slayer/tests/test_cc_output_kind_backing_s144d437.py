"""S144-D-437..439 - every cc_output row's CC kind is named by its own
slot in the shipped kit snapshot.

WHY. ``agents/daemon_slayer/cc_output_registry_notes.json`` keeps one row
per ``cc_output.py`` registry entry (champion, spell, cc_kind, duration,
conditional, source_quote). S144-D-215 (``test_registry_notes_sidecars_
s144d215.py``) pins the sidecar to the registry and S144-D-428 checks the
ability NAME a quote opens on, but nothing checked the CC KIND against the
kit: a row could claim a knock-up its ability does not have, with a quote
that invents the text ("Knock-up 1.25s on enemies hit by the dive landing"
- Smolder's R is a fire wave with no dive) and pass every guard.

* S144-D-437 (guard): the row's ``cc_kind`` must be named (one of a few
  stems per kind) in the effects_descriptions / notes / name of its own
  slot in ``data/daemon_slayer/<current.txt>/champion_abilities.json``.
  Departures are pinned below; each pin is asserted still present.
* S144-D-438 (fix, sidecar text only): three quotes invented a knock-up
  (Smolder R "dive landing", Volibear E "per wave-7 registry entry",
  Xin Zhao W "per registry wave-3 entry"). Each now quotes the snapshot
  slow clause verbatim and says the snapshot names no knock-up for that
  slot. The registry is untouched.
* S144-D-439 (Tier-2, NOT done here): those three AIRBORNE rows are
  unbacked registry data; re-keying one changes ``compute_cc_output``
  and needs an ENGINE_VERSION bump. Pinned in ``_UNBACKED`` until then.

MEASURED 2026-11-10 (patch 16.22.1, ENGINE 1.291.0, 315 rows): 8 rows
departed - the 3 unbacked AIRBORNE rows above, and 5 context rows: Annie's
Q / W / R stun is her passive Pyromania delivered through each cast,
Mordekaiser's Death Realm is modelled as STASIS, and Renata's berserk is
modelled as CHARM (the kind vocabulary has no BERSERK).

LIMITS (a clean run is not proof every kind is right): the stems are
loose on purpose ("knock" backs AIRBORNE and KNOCKBACK alike, so a
"knocks down" text would back a knock-up), only the kind is checked
(durations, magnitudes and the conditional flag are not), and a kind
named anywhere in the slot passes even if another form of that slot owns
it.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any, Iterable, Mapping

_REPO = Path(__file__).resolve().parents[3]
_DS_DIR = _REPO / "agents" / "daemon_slayer"
_DS_DATA = _REPO / "data" / "daemon_slayer"

# cc_kind -> lower-case stems; any one in the slot text backs the kind.
_STEMS: dict[str, tuple[str, ...]] = {
    "STUN": ("stun",),
    "ROOT": ("root", "snare", "immobiliz"),
    "AIRBORNE": ("knock", "airborne", "suspend", "toss"),
    "KNOCKBACK": ("knock", "push", "displace"),
    "PULL": ("pull", "drag"),
    "SLOW": ("slow",),
    "SUPPRESSION": ("suppress",),
    "FEAR": ("fear", "flee"),
    "CHARM": ("charm",),
    "SILENCE": ("silence",),
    "TAUNT": ("taunt",),
    "NEARSIGHT": ("nearsight",),
    "STASIS": ("stasis",),
    "GROUND": ("ground",),
    "SLEEP": ("sleep", "drows"),
    "CRIPPLE": ("cripple",),
    "POLYMORPH": ("polymorph",),
    "BLIND": ("blind",),
}

# S144-D-439: (champion, spell, cc_kind) rows the snapshot does not back.
_UNBACKED: dict[tuple[str, str, str], str] = {
    ("Smolder", "R", "AIRBORNE"): "MMOOOMMMM! is a fire wave that slows its center; no knock-up",
    ("Volibear", "E", "AIRBORNE"): "Sky Splitter's bolt slows 40% and shields; no knock-up",
    ("XinZhao", "W", "AIRBORNE"): "Wind Becomes Lightning slows 50%; the knock-up is Q's 3rd attack",
}

_CONTEXT: dict[tuple[str, str, str], str] = {
    ("Annie", "Q", "STUN"): "passive Pyromania stun delivered by the cast",
    ("Annie", "W", "STUN"): "passive Pyromania stun delivered by the cast",
    ("Annie", "R", "STUN"): "passive Pyromania stun delivered by the cast",
    ("Mordekaiser", "R", "STASIS"): "Death Realm isolation modelled as STASIS",
    ("Renata", "R", "CHARM"): "berserk modelled as CHARM (no BERSERK kind)",
}

# S144-D-438: the snapshot clause each rewritten quote must carry verbatim.
_SNAPSHOT_CLAUSE: dict[tuple[str, str], str] = {
    ("Smolder", "R"): "becoming slowed by 40% for 2 seconds",
    ("Volibear", "E"): "slows them by 40% for 2 seconds",
    ("XinZhao", "W"): "slows enemies hit by 50% for 1.5 seconds",
}
_INVENTED = ("dive landing", "wave-7 registry", "wave-3 entry")
_KNOCKUP_CLAIM = re.compile(r"knock(?:s|ed)?[ -]?up|airborne", re.IGNORECASE)


def _patch() -> str:
    return (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _slot_text(kit: Mapping[str, Any], slot: str) -> str:
    parts: list[str] = []
    for form in kit.get(slot) or []:
        for key in ("effects_descriptions", "notes", "name"):
            parts.append(str(form.get(key) or ""))
    return " ".join(parts).lower()


def kind_departures(
    entries: Iterable[Mapping[str, Any]],
    abilities: Mapping[str, Any],
) -> set[tuple[str, str, str]]:
    """(champion, spell, cc_kind) rows whose kind no stem of its own slot
    text names. An unknown kind is a departure (no stems to back it)."""
    out: set[tuple[str, str, str]] = set()
    for e in entries:
        champ, spell, kind = e["champion"], e["spell"], e["cc_kind"]
        text = _slot_text(abilities.get(champ, {}), spell)
        if not any(stem in text for stem in _STEMS.get(kind, ())):
            out.add((champ, spell, kind))
    return out


def _live() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entries = _load(_DS_DIR / "cc_output_registry_notes.json")["entries"]
    abilities = _load(_DS_DATA / _patch() / "champion_abilities.json")["data"]
    return entries, abilities


class TestCcOutputKindBacking(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entries, cls.abilities = _live()
        cls.departures = kind_departures(cls.entries, cls.abilities)

    def test_every_kind_has_stems(self) -> None:
        kinds = {e["cc_kind"] for e in self.entries}
        self.assertEqual(sorted(kinds - set(_STEMS)), [])

    def test_every_kind_is_named_by_its_own_slot(self) -> None:
        allowed = set(_UNBACKED) | set(_CONTEXT)
        self.assertEqual(sorted(self.departures - allowed), [])

    def test_every_pin_is_still_a_departure(self) -> None:
        # A re-keyed registry row (S144-D-439) must drop its pin.
        stale = (set(_UNBACKED) | set(_CONTEXT)) - self.departures
        self.assertEqual(sorted(stale), [])

    def test_pins_are_real_rows(self) -> None:
        rows = {(e["champion"], e["spell"], e["cc_kind"]) for e in self.entries}
        for key in set(_UNBACKED) | set(_CONTEXT):
            with self.subTest(row=key):
                self.assertIn(key, rows)

    def test_unbacked_quotes_quote_the_snapshot(self) -> None:
        # S144-D-438: no invented knock-up text; the snapshot slow clause
        # is quoted verbatim and the quote says no knock-up is named.
        for (champ, spell), clause in _SNAPSHOT_CLAUSE.items():
            with self.subTest(champion=champ, spell=spell):
                self.assertIn(clause, _slot_text(self.abilities[champ], spell))
                rows = [
                    e
                    for e in self.entries
                    if e["champion"] == champ and e["spell"] == spell and e["cc_kind"] == "AIRBORNE"
                ]
                self.assertEqual(len(rows), 1)
                quote = rows[0]["source_quote"]
                self.assertIn(clause, quote)
                for phrase in _INVENTED:
                    self.assertNotIn(phrase, quote)
                # The quoted part (before the "(snapshot ...)" note) makes
                # no knock-up claim; the note says the snapshot names none.
                quoted, sep, note = quote.partition(" (snapshot ")
                self.assertEqual(sep, " (snapshot ")
                self.assertEqual(_KNOCKUP_CLAIM.findall(quoted), [])
                self.assertIn(f"names no knock-up for {spell};", note)
                self.assertIn("row is unbacked", note)


class TestDetectorOnPlantedRows(unittest.TestCase):
    """The detector must see each defect shape, so an empty result is real."""

    _KIT = {
        "Ekko": {
            "Q": [{"name": "Timewinder", "effects_descriptions": "['slows them by 40%']"}],
            "W": [
                {
                    "name": "Parallel Convergence",
                    "effects_descriptions": "['stuns enemies inside']",
                    "notes": "Ekko is knocked back if ...",
                }
            ],
            "R": [{"name": "Chronobreak", "effects_descriptions": None}],
        }
    }

    def _run(self, spell: str, kind: str) -> set[tuple[str, str, str]]:
        rows = [{"champion": "Ekko", "spell": spell, "cc_kind": kind}]
        return kind_departures(rows, self._KIT)

    def test_backed_kind_passes(self) -> None:
        self.assertEqual(self._run("Q", "SLOW"), set())

    def test_kind_of_another_slot_is_a_departure(self) -> None:
        self.assertEqual(self._run("Q", "STUN"), {("Ekko", "Q", "STUN")})

    def test_notes_back_a_kind(self) -> None:
        self.assertEqual(self._run("W", "KNOCKBACK"), set())

    def test_empty_slot_text_is_a_departure(self) -> None:
        self.assertEqual(self._run("R", "SLOW"), {("Ekko", "R", "SLOW")})

    def test_missing_champion_is_a_departure(self) -> None:
        rows = [{"champion": "Nobody", "spell": "Q", "cc_kind": "SLOW"}]
        self.assertEqual(
            kind_departures(rows, self._KIT),
            {("Nobody", "Q", "SLOW")},
        )

    def test_unknown_kind_is_a_departure(self) -> None:
        self.assertEqual(self._run("Q", "BERSERK"), {("Ekko", "Q", "BERSERK")})

    def test_knockup_claim_regex(self) -> None:
        for text in ("knock-up", "knocks up", "knocked up", "knockup", "Airborne"):
            with self.subTest(text=text):
                self.assertIsNotNone(_KNOCKUP_CLAIM.search(text))
        self.assertIsNone(_KNOCKUP_CLAIM.search("knocks them back"))


if __name__ == "__main__":
    unittest.main()
