"""S144-D-428..430 - the axis registry-notes sidecars name the ability their
row is keyed to.

WHY. Each of the eleven ``agents/daemon_slayer/<axis>_registry_notes.json``
sidecars keeps a ``source_quote`` per registry row: the provenance a reader
uses to see WHICH ability a row models. S144-D-215..218
(``test_registry_notes_sidecars_s144d215.py``) pin the sidecar rows to the
engine registries, but nothing checked a quote against the ability names in
the shipped kit snapshot, so a quote could open on another slot's ability
("Ekko Q Z-Drive Resonance" - that is Ekko's passive; his Q is Timewinder)
or on a name the kit does not have ("Tormented Soil (QE)" - Hwei's QE is
Molten Fissure) and still pass every guard.

* S144-D-428 (fix, sidecar text only): nine quotes opened on the wrong name
  (or on a non-ability: "Stardust (P)", "Chime collection (P)", "Tormented
  Soil (QE)") for the mechanism they describe; each now names the ability
  that owns it in ``data/daemon_slayer/<current.txt>/champion_abilities.json``,
  and the claims the snapshot contradicts went with the name (Bel'Veth's
  Lavender comes from takedowns, not void coral; Aurelion Sol's Stardust from
  damaging abilities, and his Q is Breath of Light, not the pre-rework Star
  Surge, also fixed in his BASE row; Bard's Chime movement speed is
  temporary, and Meeps ride his passive, not Q). The registries are
  untouched.
* S144-D-429 (guard): a quote's LEADING ability name (after an optional
  champion name and slot letter) must be an ability of the row's own slot,
  and a leading ``<Name> (<slot>)`` must name a real ability of the champion.
* S144-D-430 (pins): the rows whose quote describes another slot's
  MECHANISM, not just its name, are mis-keyed REGISTRY rows. Moving a row
  changes engine data (Tier-2), so they are pinned below as known departures,
  each asserted still present; fixing one fails the pin until it is removed.
  Other leads are legitimate context, also pinned: Aphelios's weapon names
  (his passive forms) open his weapon-dependent Q / W rows, Karma's Q rows
  are the Mantra-empowered cast, and the Pantheon E, Renekton E and Tahm
  Kench Q texts quote their empowered or stack-bonus versions.

MEASURED 2026-11-10 (patch 16.22.1, ENGINE 1.291.0, 2826 sidecar rows):
before the fix 29 quotes led on another slot's ability (6 name slips, 12
mis-keyed rows, 11 context leads) and 3 led on a non-ability "<Name>
(<slot>)"; one more quote (Aurelion Sol BASE) named the pre-rework Star
Surge. The ten slips are fixed; the 23 others are pinned below.
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

_AXES = (
    "allyamp", "antitank", "cc_output", "extendedduel", "mobility",
    "objdamage", "scaling", "sustain", "threatrange", "waveclear",
    "zonecontrol",
)
_SLOTS = ("P", "Q", "W", "E", "R")

# S144-D-430: (axis, champion, row slot, leading name) -> why it stays.
_MIS_KEYED: dict[tuple[str, str, str, str], str] = {
    ("waveclear", "Lissandra", "E", "Ring of Frost"):
        "W's self-centred ring; her E is the Glacial Path claw",
    ("waveclear", "Smolder", "E", "Achooo!"):
        "W's cone; his E is the Flap, Flap, Flap flight",
    ("waveclear", "Vex", "E", "Personal Space"):
        "W's shield burst; her E is Looming Darkness",
    ("waveclear", "Udyr", "E", "Wingborne Storm"):
        "R's storm; his E is the Blazing Stampede charge",
    ("waveclear", "Aurora", "W", "Between Worlds"):
        "R's zone; her W is the Across the Veil hop",
    ("mobility", "Smolder", "W", "Flap, Flap, Flap"):
        "E's flight text keyed to W (Achooo! grants no movement speed)",
    ("zonecontrol", "Udyr", "Q", "Wingborne Storm"):
        "R's storm keyed to Q (Wilding Claw)",
    ("zonecontrol", "Milio", "E", "Cozy Campfire"):
        "W's campfire zone; his E is the Warm Hugs shield",
    ("threatrange", "Milio", "E", "Cozy Campfire"):
        "W's range-extending aura; his E is Warm Hugs",
    ("threatrange", "TahmKench", "W", "Devour"):
        "R's Devour keyed to W; the R row holds W's Abyssal Dive",
    ("threatrange", "TahmKench", "R", "Abyssal Dive"):
        "W's Abyssal Dive keyed to R; the W row holds R's Devour",
    ("objdamage", "Heimerdinger", "W", "H-28G Evolution Turret"):
        "Q's turrets; his W is Hextech Micro-Rockets",
}

_CONTEXT_LEADS: dict[tuple[str, str, str, str], str] = {
    ("cc_output", "Aphelios", "Q", "Gravitum"):
        "the Q active is chosen by the main-hand weapon (a passive form)",
    ("threatrange", "Aphelios", "Q", "Calibrum"):
        "the Q active is chosen by the main-hand weapon (a passive form)",
    ("threatrange", "Aphelios", "W", "Infernum"):
        "the weapon whose Q the W swap readies (a passive form)",
    ("waveclear", "Aphelios", "Q", "Infernum"):
        "the Q active is chosen by the main-hand weapon (a passive form)",
    ("zonecontrol", "Aphelios", "W", "Infernum"):
        "the weapon the W swap places off-hand (a passive form)",
    ("mobility", "Pantheon", "E", "Mortal Will"):
        "E's text quotes the Mortal Will empowered recast",
    ("cc_output", "TahmKench", "Q", "An Acquired Taste"):
        "Q's text quotes the 3-stack An Acquired Taste stun",
    ("antitank", "Renekton", "E", "Reign of Anger"):
        "E's text quotes the Fury-empowered Dice (Reign of Anger Bonus)",
    ("scaling", "Karma", "Q", "Mantra"):
        "the row is the Mantra-empowered Q (Soulflare)",
    ("waveclear", "Karma", "Q", "Mantra"):
        "the row is the Mantra-empowered Q (Soulflare)",
    ("zonecontrol", "Karma", "Q", "Mantra"):
        "the row is the Mantra-empowered Q (Soulflare)",
}


def _patch() -> str:
    return (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _ability_names(abilities: Mapping[str, Any]) -> dict[str, dict[str, set[str]]]:
    """champion -> ability name -> the slots that carry it (any form)."""
    out: dict[str, dict[str, set[str]]] = {}
    for champ, kit in abilities.items():
        names: dict[str, set[str]] = {}
        for slot in _SLOTS:
            for form in kit.get(slot) or []:
                name = (form.get("name") or "").strip()
                if name:
                    names.setdefault(name, set()).add(slot)
        out[champ] = names
    return out


def _strip_subject(quote: str, champ_names: Iterable[str]) -> str:
    """Drop a leading champion name and slot letter ("Ekko Q ...")."""
    text = quote.strip()
    for name in sorted(champ_names, key=len, reverse=True):
        if name and text.startswith(name + " "):
            text = text[len(name) + 1:]
            break
    if len(text) > 2 and text[0] in _SLOTS and text[1] == " ":
        text = text[2:]
    return text


def _leading_name(text: str, names: Iterable[str]) -> str | None:
    """The longest ability name the text opens on, word-bounded."""
    best = None
    for name in names:
        if len(name) < 4 or not text.lower().startswith(name.lower()):
            continue
        rest = text[len(name):]
        if rest and (rest[0].isalnum() or rest[0] == "_"):
            continue
        if best is None or len(name) > len(best):
            best = name
    return best


_PAREN_LEAD = re.compile(r"^([A-Z][A-Za-z' !,.-]{2,40}?) \(([PQWER]{1,2})\)")


def lead_departures(
    sidecars: Mapping[str, list[Mapping[str, Any]]],
    abilities: Mapping[str, Any],
    display: Mapping[str, str],
) -> tuple[set[tuple[str, str, str, str]], list[str]]:
    """Return (leading-name slot departures, quotes leading on a non-name).

    A departure is (axis, champion, row slot, leading name) where the quote
    opens on an ability name that the row's slot does not carry.
    """
    names = _ability_names(abilities)
    departures: set[tuple[str, str, str, str]] = set()
    unknown: list[str] = []
    for axis, entries in sidecars.items():
        for entry in entries:
            champ = entry["champion"]
            slot = entry.get("source") or entry.get("spell")
            if slot not in _SLOTS:
                continue
            kit = names.get(champ, {})
            text = _strip_subject(
                entry["source_quote"], {champ, display.get(champ, champ)},
            )
            lead = _leading_name(text, kit)
            if lead is not None:
                if slot not in kit[lead]:
                    departures.add((axis, champ, slot, lead))
                continue
            match = _PAREN_LEAD.match(text)
            if match and match.group(1) not in kit:
                unknown.append(f"{axis} {champ} {slot}: {match.group(0)!r}")
    return departures, unknown


def _live() -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, str]]:
    patch = _patch()
    abilities = _load(_DS_DATA / patch / "champion_abilities.json")["data"]
    champs = _load(_DS_DATA / patch / "champions.json")["data"]
    display = {cid: row.get("name", cid) for cid, row in champs.items()}
    sidecars = {
        axis: _load(_DS_DIR / f"{axis}_registry_notes.json")["entries"]
        for axis in _AXES
    }
    return sidecars, abilities, display


class TestQuoteAbilityNames(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sidecars, cls.abilities, cls.display = _live()
        cls.departures, cls.unknown = lead_departures(
            cls.sidecars, cls.abilities, cls.display,
        )

    def test_every_leading_name_is_the_rows_own_slot(self) -> None:
        allowed = set(_MIS_KEYED) | set(_CONTEXT_LEADS)
        self.assertEqual(sorted(self.departures - allowed), [])

    def test_every_pinned_departure_is_still_present(self) -> None:
        # A fixed registry row (or a reworded quote) must drop its pin.
        stale = (set(_MIS_KEYED) | set(_CONTEXT_LEADS)) - self.departures
        self.assertEqual(sorted(stale), [])

    def test_no_quote_leads_on_an_ability_the_kit_lacks(self) -> None:
        self.assertEqual(self.unknown, [])

    def test_pins_name_real_abilities_of_another_slot(self) -> None:
        names = _ability_names(self.abilities)
        for axis, champ, slot, lead in set(_MIS_KEYED) | set(_CONTEXT_LEADS):
            with self.subTest(axis=axis, champion=champ, slot=slot):
                self.assertIn(lead, names[champ])
                self.assertNotIn(slot, names[champ][lead])

    def test_fixed_quotes_name_the_owning_ability(self) -> None:
        # S144-D-428: (axis, champion, slot) -> the ability the quote names.
        fixed = {
            ("threatrange", "Ekko", "Q"): "Timewinder",
            ("threatrange", "Ambessa", "W"): "Repudiation",
            ("threatrange", "Zyra", "W"): "Rampant Growth",
            ("objdamage", "Zyra", "W"): "Rampant Growth",
            ("scaling", "Belveth", "P"): "Death in Lavender",
            ("scaling", "Volibear", "R"): "Stormbringer",
            ("scaling", "AurelionSol", "P"): "Cosmic Creator",
            ("scaling", "Bard", "P"): "Traveler's Call",
            ("zonecontrol", "Hwei", "Q"): "Molten Fissure",
        }
        names = _ability_names(self.abilities)
        for (axis, champ, slot), want in fixed.items():
            with self.subTest(axis=axis, champion=champ, slot=slot):
                rows = [
                    e for e in self.sidecars[axis]
                    if e["champion"] == champ
                    and (e.get("source") or e.get("spell")) == slot
                ]
                self.assertEqual(len(rows), 1)
                text = _strip_subject(
                    rows[0]["source_quote"],
                    {champ, self.display.get(champ, champ)},
                )
                self.assertEqual(_leading_name(text, names[champ]), want)
                self.assertIn(slot, names[champ][want])

    def test_no_quote_cites_aurelion_sols_pre_rework_q(self) -> None:
        # Star Surge was Aurelion Sol's Q before his rework; the live Q is
        # Breath of Light, so a quote naming Star Surge describes a dead kit.
        names = _ability_names(self.abilities)
        self.assertNotIn("Star Surge", names["AurelionSol"])
        hits = [
            f"{axis} {e.get('source') or e.get('spell')}"
            for axis, entries in self.sidecars.items()
            for e in entries
            if e["champion"] == "AurelionSol" and "Star Surge" in e["source_quote"]
        ]
        self.assertEqual(hits, [])


class TestDetectorOnPlantedRows(unittest.TestCase):
    """The detector must see each defect shape, so an empty result is real."""

    _ABILITIES = {
        "Ekko": {
            "P": [{"name": "Z-Drive Resonance"}],
            "Q": [{"name": "Timewinder"}],
            "W": [{"name": "Parallel Convergence"}],
            "E": [{"name": "Phase Dive"}],
            "R": [{"name": "Chronobreak"}],
        },
    }
    _DISPLAY = {"Ekko": "Ekko"}

    def _run(self, quote: str, slot: str = "Q"):
        rows = {"threatrange": [
            {"champion": "Ekko", "source": slot, "source_quote": quote},
        ]}
        return lead_departures(rows, self._ABILITIES, self._DISPLAY)

    def test_wrong_slot_lead_after_champion_and_slot(self) -> None:
        dep, unk = self._run("Ekko Q Z-Drive Resonance boomerang ~1050")
        self.assertEqual(dep, {("threatrange", "Ekko", "Q", "Z-Drive Resonance")})
        self.assertEqual(unk, [])

    def test_own_slot_lead_passes(self) -> None:
        self.assertEqual(self._run("Ekko Q Timewinder boomerang"), (set(), []))

    def test_invented_name_with_slot_paren(self) -> None:
        dep, unk = self._run("Temporal Grenade (Q) - slows")
        self.assertEqual(dep, set())
        self.assertEqual(len(unk), 1)

    def test_mid_sentence_mention_is_not_a_lead(self) -> None:
        self.assertEqual(
            self._run("throws a grenade; Z-Drive Resonance procs on hit"),
            (set(), []),
        )

    def test_word_boundary(self) -> None:
        dep, _ = self._run("Phase Diver lands", slot="Q")
        self.assertEqual(dep, set())

    def test_non_ability_slot_rows_are_skipped(self) -> None:
        self.assertEqual(self._run("Z-Drive Resonance", slot="BASE"), (set(), []))


if __name__ == "__main__":
    unittest.main()
