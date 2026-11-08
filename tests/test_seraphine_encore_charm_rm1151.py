"""RM-1151: Seraphine R (Encore) charms; it does not stun.

DDragon / Meraki prose for the 16.21.1 data set: "projects a captivating
force ... deals magic damage to enemies hit, charms them". The duration
(1.25 / 1.5 / 1.75 s) is unchanged; only the word was wrong, in the DS
registry comment and in the one-word hint the coach prompt renders.
"""

from __future__ import annotations

import json
from pathlib import Path

from core import enemy_cc_threat_context as ectc

_ROOT = Path(__file__).resolve().parents[1]
_DS = _ROOT / "agents" / "daemon_slayer"


def _encore_prose() -> str:
    cur = (_ROOT / "data" / "daemon_slayer" / "current.txt").read_text(encoding="utf-8").strip()
    doc = json.loads(
        (_ROOT / "data" / "daemon_slayer" / cur / "champion_abilities.json")
        .read_text(encoding="utf-8")
    )

    def find(o):
        if isinstance(o, dict):
            if "Seraphine" in o:
                return o["Seraphine"]
            for v in o.values():
                r = find(v)
                if r:
                    return r
        return None

    spell = find(doc)["R"][0]
    return " ".join(spell.get("effects_descriptions") or []).lower()


def test_data_prose_says_charm_not_stun() -> None:
    prose = _encore_prose()
    assert "charms" in prose
    assert "stun" not in prose


def test_hint_word_is_charm() -> None:
    assert ectc._CC_KIND_HINTS[("Seraphine", "R")] == "charm"


def test_registry_comment_says_charm() -> None:
    src = (_DS / "_per_spell_cc.py").read_text(encoding="utf-8")
    line = next(
        ln for ln in src.splitlines() if ln.strip().startswith("# Seraphine R - Encore")
    )
    assert "charm" in line and "stun" not in line
