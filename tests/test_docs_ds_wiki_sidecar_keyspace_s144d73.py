"""Characterization guard: the wiki_ability_stats keyspace vs the accessors (RM-1340).

``wiki_ability_stats.json`` keys each record by the wiki Template:Data title
(``"Vel'Koz/Void Rift"``) while ``DataSnapshot.ability_static_cd`` and
``ability_recharge`` look it up as ``"<DDragon id>/<ability>"`` (``Velkoz``). The
two spellings agree for most champions and differ for 22 of 171 (measured at
patch 16.21.1), so those champions' wiki records are unreachable through the
accessors. ``docs/DAEMON_SLAYER.md`` records this ("wiki_ability_stats keyspace").

This is a CHARACTERIZATION of a known, Tier-2 defect, not a license for it. It
pins, derived from the committed sidecar (no hand-kept champion list):

  * the doc states the measured prefix counts, so a patch refresh that moves them
    forces a doc edit;
  * a mismatched-prefix record IS reachable under its wiki title and NOT under
    its DDragon id (the defect itself);
  * a matching-prefix record is reachable under its id (the control).

When the alias index lands (ENGINE bump), the "not reachable under id" half
flips: update the doc row and this test in the same commit. ASCII only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot

_ROOT = Path(__file__).resolve().parent.parent
_DOC = _ROOT / "docs" / "DAEMON_SLAYER.md"
_DATA = _ROOT / "data" / "daemon_slayer"


def _records() -> dict:
    patch = (_DATA / "current.txt").read_text(encoding="utf-8").strip()
    doc = json.loads((_DATA / patch / "wiki_ability_stats.json").read_text(encoding="utf-8"))
    return doc["abilities"]


def _mismatched() -> dict[str, dict[str, dict]]:
    """{wiki title prefix: {ability: record}} where the prefix is not the apiname."""
    out: dict[str, dict[str, dict]] = {}
    for key, rec in _records().items():
        prefix, ability = key.split("/", 1)
        if rec.get("apiname") != prefix:
            out.setdefault(prefix, {})[ability] = rec
    return out


def _prefixes() -> set[str]:
    return {k.split("/", 1)[0] for k in _records()}


def _doc_row() -> str:
    for line in _DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("- **`wiki_ability_stats` keyspace**"):
            return line
    raise AssertionError("docs/DAEMON_SLAYER.md lost the wiki_ability_stats keyspace row")


def test_doc_row_states_the_measured_counts() -> None:
    row = _doc_row()
    mism = _mismatched()
    carrying = sum(
        1
        for abilities in mism.values()
        for rec in abilities.values()
        if rec.get("static") is not None or rec.get("recharge_ranks")
    )
    m = re.search(r"For the (\d+) champions .*?\((\d+) of (\d+) title prefixes", row)
    assert m, "the row no longer states 'For the N champions ... (N of M title prefixes'"
    assert (int(m.group(1)), int(m.group(2)), int(m.group(3))) == (
        len(mism),
        len(mism),
        len(_prefixes()),
    )
    m5 = re.search(r"(\d+) of those records carry", row)
    assert m5 and int(m5.group(1)) == carrying


def test_mismatched_record_is_reachable_by_title_not_by_id() -> None:
    snap = DataSnapshot.load()
    mism = _mismatched()
    assert mism, "no mismatched prefix left: the alias fix landed, retire this guard"
    checked = 0
    for prefix, abilities in mism.items():
        for ability, rec in abilities.items():
            api = rec["apiname"]
            if rec.get("static") is not None:
                assert snap.ability_static_cd(prefix, ability) is not None
                assert snap.ability_static_cd(api, ability) is None, (api, ability)
                checked += 1
            if rec.get("recharge_ranks"):
                assert snap.ability_recharge(prefix, ability)
                assert snap.ability_recharge(api, ability) is None, (api, ability)
                checked += 1
    assert checked >= 1


def test_matching_prefix_record_is_reachable_by_id() -> None:
    snap = DataSnapshot.load()
    for key, rec in _records().items():
        prefix, ability = key.split("/", 1)
        if prefix == rec.get("apiname") and rec.get("recharge_ranks"):
            assert snap.ability_recharge(prefix, ability), key
            return
    raise AssertionError("no matching-prefix record with recharge_ranks to use as a control")


def test_kled_has_no_param_bearing_record() -> None:
    kled = {k: v for k, v in _records().items() if v.get("apiname") == "Kled"}
    assert kled, "Kled records vanished"
    assert all(k.startswith("Kled & Skaarl/") for k in kled)
    assert all(set(v) <= {"apiname", "slot"} for v in kled.values())
