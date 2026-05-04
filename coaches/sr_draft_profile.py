"""SR Draft Theatre — 3-build profile generator.

Phase 8 step 1 (thin slice, 2026-05-04): stub generator that proves
the LCU → dashboard route wiring without yet calling the Daemon Slayer
engine on :8893.

`build_profile(champion, role, my_team, their_team, queue_id)` is the
single entry point. It returns a stable shape so the dashboard route +
smoke test can lock in before P8-2 swaps the body for 3× engine `/beam`
calls (primary / alt-playstyle / experimental). User-curated builds
will later be appended in P8-3 with `kind: "user"`; engine outputs get
`kind: "engine"`.

Operator-additive invariant: this generator NEVER reads or writes the
user-curated store at `data/daemon_slayer/user_builds.json`. Merge
happens at the route layer in P8-3.
"""
from __future__ import annotations

from typing import Any, Optional


# SR queue IDs that should engage the 3-build profile generator.
# Inherited as the canonical set for Phase 8 — Clash (700) and other
# draft-style modes can be added later if the engine output proves
# applicable to those queues.
SR_DRAFT_QUEUE_IDS = frozenset({
    400,  # Normal Draft Pick
    420,  # Ranked Solo/Duo
    430,  # Normal Blind Pick (no draft phase, but champ-select is structurally identical)
    440,  # Ranked Flex
})


def is_sr_draft_queue(queue_id: Optional[int]) -> bool:
    """True when queue_id corresponds to a Summoner's Rift queue that
    Phase 8 should activate for. Centralised so the state builder + the
    route handler agree on the gate."""
    if queue_id is None:
        return False
    try:
        return int(queue_id) in SR_DRAFT_QUEUE_IDS
    except (TypeError, ValueError):
        return False


def build_profile(
    champion: str,
    role: Optional[str] = None,
    my_team: Optional[list[dict[str, Any]]] = None,
    their_team: Optional[list[dict[str, Any]]] = None,
    queue_id: Optional[int] = None,
) -> dict[str, Any]:
    """Return the 3-build profile envelope for an SR champ-select pick.

    Thin-slice contract (P8-1): returns the locked shape with an empty
    `profiles` list and `engine_version: None`. P8-2 will replace the
    body with 3× `/beam` calls; P8-3 will append user-curated builds.

    Args:
        champion: Display name (e.g. "Tristana"). Required.
        role: Lane assignment ("TOP", "JUNGLE", "MIDDLE", "BOTTOM",
            "UTILITY") or None if unassigned.
        my_team: Ally cellId/championId records from `champ_select.my_team`.
        their_team: Enemy cellId/championId records.
        queue_id: LCU queue id (400/420/430/440 for SR draft).

    Returns:
        {
          "champion": str,
          "role": str | None,
          "queue_id": int | None,
          "sr_draft": bool,         # echoed for client-side gating
          "engine_version": str | None,
          "profiles": list[dict],   # empty in P8-1
        }
    """
    return {
        "champion": champion,
        "role": role,
        "queue_id": queue_id,
        "sr_draft": is_sr_draft_queue(queue_id),
        "engine_version": None,
        "profiles": [],
    }
