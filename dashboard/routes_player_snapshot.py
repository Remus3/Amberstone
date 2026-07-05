"""GET /api/player-snapshot - DB-pure Home player-snapshot model (read-only).

Feeds the Home player-snapshot card (spec docs/superpowers/specs/
2026-07-04-player-snapshot-card-design.md). Assembles the normalized model
from core.player_gpi (self-relative GPI over a time window) plus a net-new
tag heuristic. No Riot API, no Claude. Rank/level/name are NOT here (they are
LCU-live, merged client-side from /api/home/summary); this route stays
rewind_history.db-pure and deterministic.
"""
from __future__ import annotations

# axis key -> (high word / strong, low word / weak). Spec 4.6.
_TAG_WORDS: dict[str, tuple[str, str]] = {
    "aggression": ("Aggressive", "Passive"),
    "farming": ("Strong Farmer", "Weak Farm"),
    "vision": ("Vision Control", "Visionless"),
    "objectives": ("Objective Focused", "Objective Shy"),
    "survival": ("Survivor", "Gank Prone"),
    "tempo": ("Snowballer", "Slow Starter"),
    "versatility": ("Generalist", "One-Trick"),
    "consistency": ("Consistent", "Streaky"),
}


def _derive_snapshot_tags(gpi: dict) -> list[dict]:
    """Three tags in [strong, neutral, weak] order (spec 4.6)."""
    strong_key = gpi.get("strongest_axis") or "aggression"
    weak_key = gpi.get("weakest_axis") or "farming"
    axes = {a["key"]: a for a in gpi.get("axes", [])}
    versat = (axes.get("versatility") or {}).get("score") or 0.0
    consist = (axes.get("consistency") or {}).get("score") or 0.0
    shape_key = "versatility" if versat >= consist else "consistency"
    shape_score = versat if shape_key == "versatility" else consist
    # High word when the shape axis reads at/above its midpoint, else low word;
    # either way it is a descriptor, never a weakness.
    shape_label = _TAG_WORDS[shape_key][0 if shape_score >= 50.0 else 1]
    return [
        {"label": _TAG_WORDS[strong_key][0], "tone": "strong"},
        {"label": shape_label, "tone": "neutral"},
        {"label": _TAG_WORDS[weak_key][1], "tone": "weak"},
    ]
