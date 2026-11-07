"""Display-time carry-efficiency shares from the post-game roster.

`gold_share_pct` = the operator's gold as a percent of their own team's
total gold. Pure + DISPLAY-only: it reads the enriched last-match roster
(`is_me` / `team_id` / `gold` per `dashboard.builders_lcu_enrich`) and never
touches the persisted `match_metrics` grade. Fills the gap flagged in the
R2 competitor-lift triage (`docs/_archive/COMPETITOR_LIFT_2026-06-18_R2.md`): gold
share had no producer repo-wide while kill-participation already existed.

Input contract (S144-T-597). The roster comes from stored LCU match JSON, and
the caller (`dashboard.builders_last_match`) computes the shares inside the
last-match builder's try block, so a raise here does not blank one stat - it
replaces the whole Post Game Review payload with an error. Every check below
is therefore a shape check that returns None (the "-" no-data sentinel), and
there is deliberately no try/except to hide a programming error:

  * the roster is a list or tuple of dict rows (a generator would be consumed
    by the operator lookup and lose rows; a dict or str is not a roster);
  * the operator is the ONE row whose `is_me` is the bool True (two such rows
    are ambiguous; a truthy "false" string is not a flag);
  * the team is every row whose `team_id` equals the operator's, which must be
    an int (not a bool, which would equal team 1) or a non-blank str - an
    unknown team would otherwise match every row lacking one, the whole lobby;
  * a team row's value is a non-bool int or a finite float, >= 0, or missing /
    None, which reads 0 (pinned by tests/test_carry_share.py). A present but
    unusable value (a string, NaN, inf, a negative, a bool) makes the total
    unknowable, so the share is None rather than a number outside 0..100.

Rows on other teams are never read, so junk there cannot change the result.
"""
from __future__ import annotations

import math

# A sentinel distinct from every valid value, for a team row whose field is
# present but unusable.
_INVALID = object()


def gold_share_pct(roster):
    """Operator gold as a 0-100 percent of their team's total gold.

    Returns None when the roster has no single `is_me` row, the team gold sums
    to zero, or the roster breaks the module's input contract - the caller
    renders that as the "-" no-data sentinel.
    """
    return _team_share_pct(roster, "gold")


def dmg_share_pct(roster):
    """Operator champion damage as a 0-100 percent of their team's total
    (roster field `damage_to_champs` per `dashboard.builders_lcu_enrich`).

    Mirrors `gold_share_pct` semantics exactly: None when the roster has no
    single `is_me` row, the team total is <= 0, or the input contract is
    broken; rounded to 1 decimal. OQ12 PGR normalized carry-metrics bundle,
    slice A.
    """
    return _team_share_pct(roster, "damage_to_champs")


def _team_key(value):
    """A usable team id (non-bool int or non-blank str), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return value
    return None


def _amount(row, field):
    """The row's `field` as a non-negative int; missing / None reads 0.

    Floats are truncated with int(), exactly as the pre-contract body did, so
    an integral float stays byte-identical. Returns _INVALID for anything
    else. The share math then runs on ints only, so a huge value can never
    overflow a float multiply.
    """
    value = row.get(field)
    if value is None:
        return 0
    if isinstance(value, bool):
        return _INVALID
    if isinstance(value, int):
        return value if value >= 0 else _INVALID
    if isinstance(value, float):
        if not math.isfinite(value) or value < 0:
            return _INVALID
        return int(value)
    return _INVALID


def _team_share_pct(roster, field):
    """Shared share math: operator's `field` over their team's sum."""
    if roster is None:
        return None
    if not isinstance(roster, (list, tuple)):
        return None
    if not all(isinstance(r, dict) for r in roster):
        return None
    mine = [r for r in roster if r.get("is_me") is True]
    if len(mine) != 1:
        return None
    me = mine[0]
    my_team = _team_key(me.get("team_id"))
    if my_team is None:
        return None
    team_total = 0
    for row in roster:
        if _team_key(row.get("team_id")) != my_team:
            continue
        amount = _amount(row, field)
        if amount is _INVALID:
            return None
        team_total += amount
    if team_total <= 0:
        return None
    my_amount = _amount(me, field)
    # Exact int true division (correctly rounded); my_amount <= team_total
    # because the operator row is itself a team row, so the result is 0..100.
    return round(my_amount * 100 / team_total, 1)
