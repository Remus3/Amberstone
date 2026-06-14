"""coaches/aram_team_analyzer.py - pre-game ARAM team-comp swap/variant advisor.

Single job: given the current ally team + bench + the user's pick + the
variants available for the user's current champion, decide whether to:
  (a) SWAP to a bench champion,
  (b) change VARIANT (runes/items) on the current champion, or
  (c) STAY with current pick + variant.

Explicitly assumes teammates won't change - only the user's swap is on
the table. Variant change is preferred when the gap can be fixed without
giving up the current champ (e.g. team needs more damage and current
champ has both an enchanter and an AP-burst variant available).

Public API:
    analyze(state: dict, api_key: str) -> dict

`state` shape:
    {
        "my_champion":  "Lulu",
        "my_team":      ["Lulu", "Yuumi", "Sona", "Janna", "Soraka"],
        "their_team":   ["Vayne", "Lux", "Thresh", "Riven", "Yasuo"],
        "bench":        ["Caitlyn", "Vi", "Wukong"],
        "current_variant": "support-enchanter",  # currently-applied variant key
        "variants": [                            # all variants available for this mode
            {"key": "support-enchanter", "label": "Enchanter Support",
             "summary": "Summon Aery/Sorcery -> Imperial Mandate, Ardent, Mikael's"},
            {"key": "ap-burst",          "label": "AP Burst",
             "summary": "Arcane Comet/Sorcery -> Luden's, Shadowflame, Rabadon's"},
            {"key": "on-hit",            "label": "On-Hit Bruiser",
             "summary": "Lethal Tempo/Precision -> Wit's End, Nashor's, Guinsoo's"},
        ]
    }

Returns:
    {
        "ok":             bool,
        "recommendation": "swap" | "variant" | "stay",
        "swap_to":        str,  # bench champion name, "" if not swap
        "variant_to":     str,  # variant key, "" if not variant
        "reason":         str,
        "confidence":     "high" | "medium" | "low",
        "raw":            str,
        "elapsed_ms":     int,
    }

Cost: ZERO for the meaningful case. The swap/variant/stay decision is now
answered deterministically by core.aram_comp_verdict (correct-by-construction
from champions.json range/damage/frontline/engage/sustain facts) with no LLM
call (Haiku-elimination PRIMARY north star). The Haiku call survives only as a
fail-soft fallback for a team too thin to judge (< 3 resolvable champs); it
adds the "source" key ("deterministic" when the engine answered).
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("rc.coaches.aram_team")

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 280

_SYSTEM_PROMPT = """You are an ARAM team-comp analyzer. The user can:
  (a) SWAP their pick to a bench champion (only the user's pick changes -
      teammates will NOT change), OR
  (b) change the VARIANT (different runes + items) on their current pick
      without swapping champions, OR
  (c) STAY with current pick and current variant.

Prefer VARIANT changes over SWAPS when a variant would adequately fix
the gap - variant changes have zero risk (same champ, just different
build). Prefer SWAPS only when no available variant of the current pick
addresses the gap.

Evaluate these factors in order of importance for ARAM:
  1. Range mix - all-melee comps lose; need at least 2 ranged champs.
  2. Damage type - avoid mono-AP or mono-AD (enemy itemization punishes).
  3. Frontline - need at least one tank or beefy bruiser to soak/engage.
  4. Engage tool - someone has to start fights; pure poke comps stall.
  5. Sustain - healing/shielding extends fights significantly.
  6. Wave clear - weak clear loses ARAM into poke comps.

If the current comp is already balanced AND current variant fits, STAY.

Output EXACTLY five lines, label + colon + value, no markdown, no extras:
Recommendation: swap | variant | stay
SwapTo: <bench champion name, or 'none'>
VariantTo: <variant key from the list provided, or 'none'>
Reason: <one short sentence - concrete gap + why this fixes it, or why current is fine>
Confidence: high | medium | low"""


_USER_TEMPLATE = """Ally team (5 picks, including me): {my_team}
Enemy team:                      {their_team}
My current pick:                 {my_champion}
My current variant:              {current_variant}

Bench (only I can swap to these - teammates won't change):
{bench_block}

Available variants for {my_champion} (alternatives to swapping):
{variants_block}

What should I do?"""


def _parse_response(raw: str) -> dict[str, str]:
    fields = {"recommendation": "", "swapto": "", "variantto": "",
              "reason": "", "confidence": ""}
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s or ":" not in s:
            continue
        label, _, val = s.partition(":")
        key = label.strip().lower().replace(" ", "")
        if key in fields:
            fields[key] = val.strip()[:240]
    return fields


def analyze(state: dict, api_key: str | None) -> dict[str, Any]:
    """Synchronous Haiku call. Never raises; returns ok=False on error."""
    out: dict[str, Any] = {
        "ok": False, "recommendation": "stay", "swap_to": "", "variant_to": "",
        "reason": "", "confidence": "low", "raw": "", "elapsed_ms": 0,
    }
    if not isinstance(state, dict) or not state.get("my_champion"):
        out["reason"] = "(no champion picked yet)"
        return out

    # Haiku-elimination (PRIMARY north star): the deterministic comp-verdict
    # engine answers the swap/variant/stay question correct-by-construction from
    # champions.json facts (range mix / damage type / frontline / engage /
    # sustain) with ZERO spend. It runs FIRST - before the spend-gate - because
    # a free verdict has no spend to gate, and serves even when the Anthropic
    # kill-switch is off. The Haiku call below is now only a fail-soft fallback
    # for the degenerate case (a team too thin to judge, ok=False).
    try:
        from core.aram_comp_verdict import comp_verdict
        det = comp_verdict(state)
        if det.get("ok"):
            out.update({
                "ok": True,
                "recommendation": det.get("recommendation") or "stay",
                "swap_to": det.get("swap_to") or "",
                "variant_to": det.get("variant_to") or "",
                "reason": det.get("reason") or "(comp balanced)",
                "confidence": det.get("confidence") or "medium",
                "raw": "deterministic",
                "source": "deterministic",
                "factors": det.get("factors") or {},
            })
            return out
    except Exception as exc:
        logger.debug("deterministic comp_verdict failed, falling back: %s", exc)

    # Spend-gate: champ-select Anthropic calls off via Settings kill-switch.
    try:
        from core.cost_tracker import get_tracker as _gt
        if _gt().gate_disabled("champ_select"):
            out["reason"] = "(champ-select coach disabled)"
            return out
    except Exception:
        pass
    bench = [c for c in (state.get("bench") or []) if c]
    variants = [v for v in (state.get("variants") or []) if v.get("key")]
    if not bench and len(variants) <= 1:
        out["reason"] = "Empty bench and no other variants - stuck with current"
        out["recommendation"] = "stay"
        out["ok"] = True
        return out
    if not api_key:
        out["reason"] = "(API key missing - analyzer disabled)"
        return out

    my_team = ", ".join(c for c in (state.get("my_team") or []) if c) or "?"
    their_team = ", ".join(c for c in (state.get("their_team") or []) if c) or "?"
    bench_block = ("- " + "\n- ".join(bench)) if bench else "  (empty)"
    if variants:
        variants_block = "\n".join(
            f"- {v['key']} ({v.get('label') or v['key']}): {v.get('summary') or '(no summary)'}"
            for v in variants
        )
    else:
        variants_block = "  (no other variants - only the current build)"

    prompt = _USER_TEMPLATE.format(
        my_team=my_team,
        their_team=their_team,
        my_champion=state["my_champion"],
        current_variant=state.get("current_variant") or "(unknown)",
        bench_block=bench_block,
        variants_block=variants_block,
    )

    t0 = time.time()
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
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
            record_anthropic_response(resp, model=_MODEL, purpose="aram_team_analyzer")
        except Exception as exc:
            logger.debug("cost_tracker record: %s", exc)
        raw = resp.content[0].text if resp.content else ""
    except Exception as exc:
        # Never surface raw exception details (type or message) in the
        # user-facing reason field - friendly degrade + log the raw error.
        out["reason"] = "(analyzer paused - retrying)"
        logger.warning("aram team analyzer: %s", exc)
        return out

    elapsed = int((time.time() - t0) * 1000)
    fields = _parse_response(raw)

    rec = (fields.get("recommendation") or "").lower().strip()
    if rec not in ("swap", "variant", "stay"):
        rec = "stay"
    swap_raw = (fields.get("swapto") or "").strip()
    var_raw = (fields.get("variantto") or "").strip()
    swap_to = "" if (not swap_raw or swap_raw.lower() == "none" or rec != "swap") else swap_raw
    variant_to = "" if (not var_raw or var_raw.lower() == "none" or rec != "variant") else var_raw

    # Sanity: swap target must be on the bench (LLMs hallucinate)
    if swap_to and swap_to not in bench:
        norm = lambda s: "".join(c.lower() for c in s if c.isalnum())
        bench_norm = {norm(b): b for b in bench}
        match = bench_norm.get(norm(swap_to))
        if match:
            swap_to = match
        else:
            logger.warning("analyzer hallucinated swap=%r; bench=%s", swap_to, bench)
            swap_to = ""
            rec = "stay"

    # Sanity: variant key must be in the provided variants list
    if variant_to and variant_to not in [v["key"] for v in variants]:
        # Try fuzzy match on label too
        for v in variants:
            if v["key"].lower() == variant_to.lower() or \
               (v.get("label") or "").lower() == variant_to.lower():
                variant_to = v["key"]
                break
        else:
            logger.warning("analyzer hallucinated variant=%r; available=%s",
                           variant_to, [v["key"] for v in variants])
            variant_to = ""
            rec = "stay"

    # Don't recommend the variant the user is already on
    if variant_to and variant_to == state.get("current_variant"):
        rec = "stay"
        variant_to = ""

    conf = (fields.get("confidence") or "").lower().strip()
    if conf not in ("high", "medium", "low"):
        conf = "medium"

    out.update({
        "ok": True,
        "recommendation": rec,
        "swap_to":    swap_to,
        "variant_to": variant_to,
        "reason":     fields.get("reason", "")[:240] or "(no reason given)",
        "confidence": conf,
        "raw":        raw[:1200],
        "elapsed_ms": elapsed,
    })
    return out
