"""Post Game Review renderer over T2 findings, for ONE match, ONE player.

Consumes `core.event_patterns` Findings and `core.cohort_baseline.rank_of`.
Runs entirely off a Match-V5 match blob plus its timeline: no client, no API
call, no Claude.

THE ONE RULE THIS MODULE ENCODES (docs/REPLAY_T2_PARSE_CRITERIA.md section 4):
win-side and loss-side are DIFFERENT QUESTIONS, not one question with a sign
flip.

  LOSS side -> COST ATTRIBUTION. Rank the negative step changes by measured
    magnitude and attribute each to the nearest preceding decision. The
    deliverable is an ordered list of what cost the most, not a list of
    everything that went wrong.

  WIN side -> DECISION PATTERN. Report what the player did, in order, with no
    claim that any of it was correct. A winner's action is not automatically
    right: winners make mistakes they get away with. Nothing here is a coaching
    rule, and every decision line says so in its own payload - promotion needs
    a MEASURED win-vs-loss rate difference across the corpus, which is
    tools/mine_event_patterns.py's job and cannot be answered from one match.

TWO CONSTRUCTION DETAILS THAT ARE NOT COSMETIC:

1. The cost view is spined on `death_cost` alone. `early_deaths`,
   `solo_deaths` and `shutdowns_given` are the SAME deaths relabelled, so
   listing each as its own line makes one death appear up to four times, each
   carrying the full gold, and the magnitude ranking becomes fiction. They
   attach to their death as TAGS instead.

2. A cohort band is omitted, never defaulted. `rank_of` returns None for a
   metric its cohort has no table for, and rendering that as an average
   invents a comparison the corpus never made. Those metrics land in
   `unavailable` by name.
"""
from __future__ import annotations

from core import cohort_baseline as cb
from core import event_patterns as ep

# Findings that are the same death seen through another filter. They tag the
# death they came from; they never become lines of their own.
DEATH_SUBSETS = ("early_deaths", "solo_deaths", "shutdowns_given")

# Criteria that describe a CHOICE rather than a cost. These are the win-side
# view. Deliberately disjoint from the death criteria above.
DECISION_CRITERIA = ("skill_order", "objective_participation",
                     "kill_participation", "plate_share")

PROMOTION_NOTE = ("observed, not validated - promotion to a coaching rule "
                  "requires a measured win-vs-loss rate difference across the "
                  "corpus (tools/mine_event_patterns.py)")


def _by_criterion(match, timeline, pid) -> dict:
    out: dict = {}
    for f in ep.analyse(match, timeline, pid):
        out.setdefault(f.criterion, []).append(f)
    return out


def _decision_history(by: dict) -> list:
    """Every timestamped decision the player made, ascending.

    Purchases come from `item_order`, which is undo-corrected, so a bought and
    immediately undone item is not offered as an explanation for anything.
    """
    hist = []
    for f in by.get("item_order", []):
        for t_ms, item_id in f.detail.get("purchases", []):
            hist.append({"decision": "item_purchased", "t_ms": int(t_ms),
                         "item_id": int(item_id)})
    for f in by.get("skill_order", []):
        for i, slot in enumerate(f.detail.get("order", [])):
            hist.append({"decision": "skill_level_up", "t_ms": None,
                         "skill_slot": int(slot), "point": i + 1})
    return sorted([h for h in hist if h["t_ms"] is not None],
                  key=lambda h: h["t_ms"])


def _attribute(history: list, t_ms: int):
    """Nearest decision strictly BEFORE t_ms, or None.

    None is a real answer. A death before the player's first decision has no
    preceding decision, and manufacturing one out of an empty history would be
    a fabricated cause.
    """
    prior = [h for h in history if h["t_ms"] < t_ms]
    if not prior:
        return None
    nearest = prior[-1]
    return dict(nearest, gap_ms=t_ms - nearest["t_ms"])


# ----------------------------------------------------------- loss side

def cost_attribution(match, timeline, pid) -> list:
    """Ordered list of what cost the most, each attributed to a decision."""
    by = _by_criterion(match, timeline, pid)
    history = _decision_history(by)
    tags: dict = {}
    for name in DEATH_SUBSETS:
        for f in by.get(name, []):
            tags.setdefault(f.t_ms, []).append(name)

    lines = []
    for f in by.get("death_cost", []):
        lines.append({
            "criterion": f.criterion,
            "t_ms": f.t_ms,
            "magnitude_gold": f.magnitude_gold,
            "tags": sorted(tags.get(f.t_ms, [])),
            "attributed_to": _attribute(history, f.t_ms),
            "tier": f.tier,
            "detail": dict(f.detail),
        })
    # Magnitude first; a tie breaks on time so the order is deterministic.
    lines.sort(key=lambda ln: (-ln["magnitude_gold"], ln["t_ms"]))
    return lines


# ------------------------------------------------------------ win side

def decision_pattern(match, timeline, pid) -> list:
    """What the player did, in order, with no correctness claim attached."""
    by = _by_criterion(match, timeline, pid)
    lines = []
    for f in by.get("item_order", []):
        for t_ms, item_id in f.detail.get("purchases", []):
            lines.append({"criterion": "item_purchased", "t_ms": int(t_ms),
                          "value": 0.0, "detail": {"item_id": int(item_id)},
                          "tier": f.tier})
    for name in DECISION_CRITERIA:
        for f in by.get(name, []):
            lines.append({"criterion": name, "t_ms": f.t_ms, "value": f.value,
                          "detail": dict(f.detail), "tier": f.tier})
    lines.sort(key=lambda ln: (ln["t_ms"], ln["criterion"]))
    for ln in lines:
        ln["validated"] = False
        ln["promotion"] = PROMOTION_NOTE
    return lines


# ------------------------------------------------------- cohort context

def _participant(match, pid):
    for p in (match.get("info") or {}).get("participants") or []:
        if p.get("participantId") == pid:
            return p
    return None


def cohort_context(match, pid, baselines) -> dict:
    """Percentile bands for this player's outcome metrics vs their role cohort.

    `unavailable` names every metric the cohort had no table for, so a missing
    comparison is visible instead of silently reading as average.
    """
    participant = _participant(match, pid)
    if not participant:
        return {"ranked": [], "unavailable": [], "role": ""}
    role = ep.POSITION_TO_ROLE.get(participant.get("teamPosition") or "", "")
    metrics = cb.participant_metrics(participant)
    ranked, unavailable = [], []
    for name in sorted(metrics):
        band = cb.rank_of(baselines or {}, role, name, metrics[name])
        (ranked if band else unavailable).append(band or name)
    return {"ranked": ranked, "unavailable": unavailable, "role": role}


# ---------------------------------------------------------- the report

def render(match, timeline, pid, baselines=None) -> dict:
    """One player's PGR. The outcome selects the VIEW, never a sign."""
    win = ep.won(match, pid)
    by = _by_criterion(match, timeline, pid)
    lines = (decision_pattern(match, timeline, pid) if win
             else cost_attribution(match, timeline, pid))
    gold = by.get("gold_deficit_profile") or []
    return {
        "participant_id": pid,
        "role": ep.role_of(match, pid),
        "win": win,
        "view": "decisions" if win else "cost",
        "lines": lines,
        "cohort": cohort_context(match, pid, baselines),
        "gold_profile": dict(gold[0].detail) if gold else None,
        "notes": [PROMOTION_NOTE] if win else [
            "costs are measured gold (bounty plus shutdown), not a severity "
            "score"],
    }


def _fmt_attr(attr) -> str:
    if not attr:
        return "no preceding decision"
    if attr["decision"] == "item_purchased":
        what = f"bought {attr['item_id']}"
    else:
        what = f"skill {attr.get('skill_slot')}"
    return f"{what} {attr['gap_ms'] // 1000}s earlier"


def render_text(report: dict) -> str:
    """Plain 7-bit ASCII. The dashboard renders the dict; this is for logs."""
    head = (f"PGR participant {report['participant_id']} "
            f"{report['role'] or '-'} "
            f"{'WIN' if report['win'] else 'LOSS'} -> "
            f"{report['view'].upper()} VIEW")
    out = [head, "=" * len(head)]
    if report["view"] == "cost":
        out.append("what it cost, most expensive first:")
        for ln in report["lines"]:
            tags = (" [" + ",".join(ln["tags"]) + "]") if ln["tags"] else ""
            out.append(f"  {ln['magnitude_gold']:>6}g  "
                       f"{ln['t_ms'] // 60000:>2}m{ln['t_ms'] // 1000 % 60:02d}s"
                       f"  {ln['criterion']}{tags}  "
                       f"after {_fmt_attr(ln['attributed_to'])}")
        if not report["lines"]:
            out.append("  none")
    else:
        out.append("decisions in order (NOT validated as correct):")
        for ln in report["lines"]:
            out.append(f"  {ln['t_ms'] // 60000:>2}m"
                       f"{ln['t_ms'] // 1000 % 60:02d}s  {ln['criterion']}  "
                       f"{ln['detail']}")
    cohort = report["cohort"]
    if cohort["ranked"]:
        out.append("cohort:")
        for r in cohort["ranked"]:
            # A tied band means most of the cohort scored the same value, so
            # the percentile separates nothing - say so rather than implying
            # a real standing.
            tied = "  [tied - cohort mostly level here]" if r.get("tied") else ""
            out.append(f"  {r['metric']:<26} {r['value']:>9.2f}  "
                       f"at or above p{r['at_or_above_p']}  "
                       f"(median {r['median']}, n={r['n']}){tied}")
    if cohort["unavailable"]:
        out.append("no cohort table: " + ", ".join(cohort["unavailable"]))
    for note in report["notes"]:
        out.append("NOTE: " + note)
    return "\n".join(out)
