"""
coaches/champ_select_coach.py - live coaching during ChampSelect.

Calls Claude Haiku with the current pick state and returns a compact
JSON advice payload the dashboard can render before the game starts.
Complements the cold-start adaptation panel (which surfaces historical
matchup data) by providing fresh per-pick situational advice.

Public API:
    coach_pick(state: dict, api_key: str) -> dict

`state` shape (whatever the dashboard has captured from LCU):
    {
        "is_aram": bool,
        "queue_id": int,
        "my_champion": "Ahri",          # resolved name (not ID)
        "my_team":    ["Yuumi", ...],   # ally champions, may include unknowns
        "their_team": ["Caitlyn", ...], # enemy champions
        "bench":      ["Tristana", ...] # ARAM only - swappable picks
    }

Returns:
    {
        "ok":           bool,
        "advice":       str,    # 1-line headline ("Stay Ahri - clean wave clear vs Cait/Lux")
        "swap":         str,    # ARAM bench swap recommendation, "" if none
        "summoners":    str,    # suggested D/F spells ("Flash + Heal" or similar)
        "watchout":     str,    # primary threat to track
        "raw":          str,    # full Haiku response for debugging
        "elapsed_ms":   int,
    }

Cost: one Haiku call per invocation (~$0.001). Dashboard SHOULD debounce
state changes so we don't burn one call per pick during active draft.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

# RM-364: `state` here is an HTTP POST body forwarded verbatim from
# dashboard/routes_coach.py, so EVERY interpolated field is attacker-shaped
# by construction - not one named field. Sanitised at assembly.
from core.prompt_sanitize import clean as _psan_clean
from core.prompt_sanitize import clean_iter as _psan_clean_iter

logger = logging.getLogger("rc.coaches.champ_select")

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 350

_SYSTEM_PROMPT = """You are a champ-select coach for League of Legends.

Output exactly four labelled lines, each prefixed by the label and a
colon. No markdown, no preamble, no extra lines. Be concrete and
specific to the comp/matchup. Keep each line under 100 characters.

Format:
Advice: <one-line headline - keep your champ, swap, or play-style>
Swap: <ARAM ONLY - bench swap recommendation if any, else 'none'>
Summoners: <D + F suggestion - "Flash + Heal", "Flash + Cleanse", etc.>
Watchout: <primary enemy threat to track during the game>"""


_USER_TEMPLATE = """Mode: {mode_label}
My champion: {my_champion}
My team: {my_team}
Enemy team: {their_team}
{bench_line}
Coach this pick. What is the headline judgment, summoner spells,
the most important enemy to watch, and (ARAM only) any swap?"""


def _parse_response(raw: str) -> dict[str, str]:
    fields: dict[str, str] = {"advice": "", "swap": "", "summoners": "", "watchout": ""}
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s or ":" not in s:
            continue
        label, _, val = s.partition(":")
        key = label.strip().lower()
        if key in fields:
            fields[key] = val.strip()[:200]
    return fields


def coach_pick(state: dict, api_key: str | None) -> dict[str, Any]:
    """Synchronous Haiku call. Returns advice dict; never raises."""
    out: dict[str, Any] = {
        "ok": False, "advice": "", "swap": "", "summoners": "",
        "watchout": "", "raw": "", "elapsed_ms": 0,
    }
    if not isinstance(state, dict) or not state.get("my_champion"):
        out["advice"] = "(no champion locked yet)"
        return out
    # Spend-gate: champ-select Anthropic calls off via Settings kill-switch.
    try:
        from core.cost_tracker import get_tracker as _gt
        if _gt().gate_disabled("champ_select"):
            out["advice"] = "(champ-select coach disabled)"
            return out
    except Exception:  # noqa: BLE001
        pass
    if not api_key:
        out["advice"] = "(API key missing - coach disabled)"
        return out

    is_aram = bool(state.get("is_aram"))
    mode_label = "ARAM" if is_aram else "Summoner's Rift draft/blind"
    # RM-364: clean_iter already drops None and empties, so it subsumes the
    # `if c` filter these joins used to carry.
    my_team = ", ".join(_psan_clean_iter(state.get("my_team") or [])) or "?"
    their_team = ", ".join(_psan_clean_iter(state.get("their_team") or [])) or "?"
    bench = _psan_clean_iter(state.get("bench") or [])
    bench_line = (f"Bench: {', '.join(bench)}" if (is_aram and bench)
                  else "")

    prompt = _USER_TEMPLATE.format(
        mode_label=mode_label,
        my_champion=_psan_clean(state["my_champion"]),
        my_team=my_team,
        their_team=their_team,
        bench_line=bench_line,
    )

    t0 = time.time()
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, base_url="https://api.anthropic.com")
        # Mark the static system prompt with cache_control=ephemeral so
        # subsequent champ-select ticks reuse the cached prefix at ~10% of
        # input-token cost. Per-tick coaches (aram/arena/brawl/sr) have
        # this since batch 5; champ-select was missed at first ship.
        # The user message (champion picks, hovered champ, etc.) varies
        # per tick and goes uncached.
        resp = client.messages.create(
            model=_MODEL, max_tokens=_MAX_TOKENS,
            system=[
                {"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}},
            ],
            messages=[{"role": "user", "content": prompt}],
            timeout=12,
        )
        # AUDIT 2026-05-23 (cost-trace gap C): feed cost_tracker.
        try:
            from core.cost_tracker import record_anthropic_response
            record_anthropic_response(resp, model=_MODEL, purpose="champ_select_coach")
        except Exception as exc:  # noqa: BLE001
            logger.debug("cost_tracker record: %s", exc)
        raw = resp.content[0].text if resp.content else ""
    except Exception as exc:  # noqa: BLE001
        # Never surface the raw exception (type or message) to the UI - the
        # advice field is user-facing. Friendly degrade + log the raw error.
        out["advice"] = "(coaching paused - retrying)"
        logger.warning("champ-select coach: %s", exc)
        return out

    elapsed = int((time.time() - t0) * 1000)
    fields = _parse_response(raw)
    out.update({
        "ok": bool(fields.get("advice")),
        "advice":    fields["advice"],
        "swap":      fields["swap"] if fields["swap"].lower() != "none" else "",
        "summoners": fields["summoners"],
        "watchout":  fields["watchout"],
        "raw":       raw[:1500],
        "elapsed_ms": elapsed,
    })
    return out
