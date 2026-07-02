"""Display-time carry-efficiency shares from the post-game roster.

`gold_share_pct` = the operator's gold as a percent of their own team's
total gold. Pure + DISPLAY-only: it reads the enriched last-match roster
(`is_me` / `team_id` / `gold` per `dashboard.builders_lcu_enrich`) and never
touches the persisted `match_metrics` grade. Fills the gap flagged in the
R2 competitor-lift triage (`docs/COMPETITOR_LIFT_2026-06-18_R2.md`): gold
share had no producer repo-wide while kill-participation already existed.
"""
from __future__ import annotations


def gold_share_pct(roster):
    """Operator gold as a 0-100 percent of their team's total gold.

    Returns None when the roster has no `is_me` row or the team gold sums to
    zero - the caller renders that as the "-" no-data sentinel.
    """
    return _team_share_pct(roster, "gold")


def dmg_share_pct(roster):
    """Operator champion damage as a 0-100 percent of their team's total
    (roster field `damage_to_champs` per `dashboard.builders_lcu_enrich`).

    Mirrors `gold_share_pct` semantics exactly: None when the roster has no
    `is_me` row or the team total is <= 0; rounded to 1 decimal. OQ12 PGR
    normalized carry-metrics bundle, slice A.
    """
    return _team_share_pct(roster, "damage_to_champs")


def _team_share_pct(roster, field):
    """Shared share math: operator's `field` over their team's sum."""
    rows = roster or []
    me = next((r for r in rows if r.get("is_me")), None)
    if me is None:
        return None
    my_team = me.get("team_id")
    team_total = sum(int(r.get(field) or 0)
                     for r in rows if r.get("team_id") == my_team)
    if team_total <= 0:
        return None
    return round(100.0 * int(me.get(field) or 0) / team_total, 1)
