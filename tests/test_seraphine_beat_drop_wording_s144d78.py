"""RM-1342: Seraphine E (Beat Drop) CC-tier wording matches the prose.

Sibling of RM-1151 (Seraphine R charms). The 16.21.1 data set says Beat
Drop slows, roots an ALREADY-SLOWED target, and stuns an IMMOBILIZED or
GROUNDED target, for the same duration. Three DS comments said the
inverse ("still target gets root, moving/slowed target gets stun").
Comment text only: no duration, registry row or engine output moves.
"""

from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DS = _ROOT / "agents" / "daemon_slayer"
_STALE = "still target gets root"
_FILES = (
    _DS / "_per_spell_cc.py",
    _DS / "tests" / "test_per_spell_cc_registry_wave9.py",
)


def _beat_drop_prose() -> str:
    cur = (_ROOT / "data" / "daemon_slayer" / "current.txt").read_text(encoding="utf-8").strip()
    doc = json.loads(
        (_ROOT / "data" / "daemon_slayer" / cur / "champion_abilities.json")
        .read_text(encoding="utf-8")
    )
    spell = doc["data"]["Seraphine"]["E"][0]
    return " ".join(spell.get("effects_descriptions") or []).lower()


def _beat_drop_comment_blocks(src: str) -> list[str]:
    """Each comment / docstring block that opens at a Seraphine E Beat Drop bullet."""
    lines = src.splitlines()
    blocks = []
    for i, ln in enumerate(lines):
        if "Seraphine E Beat Drop:" in ln:
            blocks.append("\n".join(lines[i : i + 4]))
    return blocks


def test_prose_roots_slowed_and_stuns_immobilized() -> None:
    prose = _beat_drop_prose()
    assert "already slowed are also rooted" in prose
    assert "immobilized or grounded are also stunned" in prose


def test_no_file_carries_the_inverted_wording() -> None:
    for path in _FILES:
        text = path.read_text(encoding="utf-8")
        assert _STALE not in text, path.name
        assert "slowed target gets stun" not in text, path.name
        assert "target gets stun)" not in text, path.name


def test_beat_drop_blocks_state_root_for_slowed_stun_for_immobilized() -> None:
    seen = 0
    for path in _FILES:
        for block in _beat_drop_comment_blocks(path.read_text(encoding="utf-8")):
            low = block.lower()
            if "stun or root" not in low:
                continue
            seen += 1
            assert "slowed" in low and "root" in low, (path.name, block)
            assert "immobiliz" in low and "stun" in low, (path.name, block)
    # Anchor: the _per_spell_cc.py comment appears twice (wave 4 + wave 9) and the
    # wave-9 test docstring once; an empty enumeration would otherwise pass.
    assert seen >= 3
