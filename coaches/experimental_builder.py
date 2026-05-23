"""coaches/experimental_builder.py - auto-adapting experimental ARAM builds.

Generates and persistently iterates on off-meta "funky" builds for each
champion in ARAM Mayhem (and ARAM). The user opts in via the variant
dropdown - picking "⚗ Experimental" applies whatever this module's
current iteration says. After the game ends, the user's grade feeds
back here and the module either keeps the build (good result) or
generates the next iteration (poor result), exploring different
keystones / item combinations toward a clear win pattern.

State lives on disk at `data/experimental_builds.json` so iterations
persist across RC restarts. Schema:

    {
      "<Champion>": {
        "current": {
          "iteration": int,         # 1, 2, 3, ...
          "label": str,
          "rationale": str,
          "runes": {keystone, primary, secondary},
          "summoners": [int, int],
          "items": [str, ...],
          "created_at": float,
          "validated": bool         # true if a prior result was S/A
        },
        "history": [
          {
            ...same shape as current...,
            "result": {grade, kda_str, kp_pct, gold_per_min, notes[]},
            "verdict": "validated|tweak_items|regen|scrap",
            "ended_at": float
          }
        ]
      }
    }

Public API:
    get_current(champion)              -> dict | None
    generate(champion, api_key)        -> dict (current build)
    adapt(champion, api_key)           -> dict (new current build)
    record_result(champion, grade, gs) -> dict (verdict + optional next iter)
    mark_active(champion, mode)        -> writes data/experimental_active.json
    consume_active()                   -> reads + deletes the marker
    clear(champion)                    -> wipe one champ's experimental data
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("rc.coaches.experimental")

_ROOT = Path(__file__).resolve().parent.parent
_BUILDS_PATH = _ROOT / "data" / "experimental_builds.json"
_ACTIVE_PATH = _ROOT / "data" / "experimental_active.json"

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 480

_KEYSTONES = (
    "Press the Attack", "Lethal Tempo", "Fleet Footwork", "Conqueror",
    "Electrocute", "Dark Harvest", "Hail of Blades",
    "Summon Aery", "Arcane Comet", "Phase Rush",
    "Grasp of the Undying", "Aftershock", "Guardian",
    "Glacial Augment", "Unsealed Spellbook", "First Strike",
)
_TREES = ("Precision", "Domination", "Sorcery", "Inspiration", "Resolve")
_SUMMONERS = {
    "flash": 4, "snowball": 32, "mark": 32, "heal": 7, "ignite": 14,
    "exhaust": 3, "cleanse": 1, "ghost": 6, "barrier": 21, "teleport": 12,
    "smite": 11, "clarity": 13,
}

_SYSTEM_PROMPT = """You design EXPERIMENTAL ARAM Mayhem builds - off-meta
but coherent. Goal: leverage the champion's underused stats / ability
quirks / item synergies in a way that explores territory the standard
build doesn't. Break the meta idea but stay grounded - the build must
be playable, not parody.

ARAM Mayhem context: faster respawns, ult haste buff, Mark/Snowball
required as one summoner, no recall. Favor snowballing/early-power
items; slightly less defensive than standard ARAM.

If prior attempts are listed with their results:
- A grade-S or grade-A result MEANS that direction worked - propose
  refinements (swap one item, try a different secondary tree).
- A grade-B result MEANS keep most of it, change 1-2 items.
- A grade-C/D MEANS the premise was off - try a substantially different
  approach (different damage profile or playstyle).
- A grade-F MEANS the build was broken - pick a completely different
  premise from the failed one.
- Do NOT repeat a build that already failed at C-or-worse.

Output EXACTLY 7 labelled lines, no markdown, no extras:
Label: <short build name, e.g. "On-Hit Tank Hybrid">
Rationale: <one short sentence on the premise>
Keystone: <one from the allowed list>
Primary: <one tree from Precision|Domination|Sorcery|Inspiration|Resolve>
Secondary: <one tree, different from Primary>
Summoners: <D, F - two names from: Flash, Snowball, Heal, Ignite, Exhaust, Cleanse, Ghost, Barrier, Teleport>
Items: <6 item display names, comma-separated, in build order>"""


def _load() -> dict:
    if not _BUILDS_PATH.exists():
        return {}
    try:
        return json.loads(_BUILDS_PATH.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("experimental load failed: %s", exc)
        return {}


def _save(data: dict) -> None:
    """Atomic write - overlays may poll mid-write."""
    _BUILDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _BUILDS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_BUILDS_PATH)


def get_current(champion: str) -> dict | None:
    return (_load().get(champion) or {}).get("current") or None


def get_history(champion: str) -> list[dict]:
    return (_load().get(champion) or {}).get("history") or []


def _parse_haiku(raw: str) -> dict:
    """Parse the 7-line output into a structured build dict."""
    fields = {"label": "", "rationale": "", "keystone": "",
              "primary": "", "secondary": "", "summoners": "", "items": ""}
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s or ":" not in s:
            continue
        label, _, val = s.partition(":")
        key = label.strip().lower()
        if key in fields:
            fields[key] = val.strip()
    # Keystone validation
    keystone = next((k for k in _KEYSTONES if k.lower() == fields["keystone"].lower()), "")
    primary = next((t for t in _TREES if t.lower() == fields["primary"].lower()), "")
    secondary = next((t for t in _TREES if t.lower() == fields["secondary"].lower()), "")
    if primary and secondary == primary:
        secondary = next((t for t in _TREES if t != primary), "Resolve")
    # Summoners
    summ_ids: list[int] = []
    for tok in re.split(r"[,/+]", fields["summoners"]):
        nm = tok.strip().lower()
        if nm in _SUMMONERS:
            summ_ids.append(_SUMMONERS[nm])
        if len(summ_ids) >= 2:
            break
    while len(summ_ids) < 2:
        summ_ids.append(4 if 4 not in summ_ids else 32)
    # Items (split on comma)
    items = [s.strip() for s in fields["items"].split(",") if s.strip()][:6]
    return {
        "label":     fields["label"][:60] or "Experimental Build",
        "rationale": fields["rationale"][:240] or "(no rationale)",
        "runes":     {"keystone": keystone, "primary": primary, "secondary": secondary},
        "summoners": summ_ids[:2],
        "items":     items,
    }


def _build_history_block(history: list[dict]) -> str:
    """Format prior attempts compactly so Haiku can reason about them."""
    if not history:
        return "  (none - this is the first attempt)"
    lines = []
    for entry in history[-6:]:           # last 6 attempts is plenty of context
        it = entry.get("iteration", "?")
        label = entry.get("label", "?")
        runes = entry.get("runes") or {}
        items = entry.get("items") or []
        result = entry.get("result") or {}
        grade = result.get("grade", "?")
        kda = result.get("kda_str", "?")
        kp = result.get("kp_pct", "?")
        verdict = entry.get("verdict", "?")
        item_short = ", ".join(items[:4]) + (", ..." if len(items) > 4 else "")
        lines.append(
            f"  it.{it} ({label}): {runes.get('keystone','?')}/{runes.get('primary','?')} "
            f"→ {item_short} | grade={grade} kda={kda} kp={kp}% verdict={verdict}"
        )
    return "\n".join(lines)


def _call_haiku(champion: str, history: list[dict], api_key: str) -> dict | None:
    """Returns parsed build dict on success, None on failure."""
    try:
        import anthropic
        prompt = (
            f"Champion: {champion}\n"
            f"Mode: ARAM Mayhem (queue 920) / ARAM (queue 450)\n\n"
            f"Prior attempts:\n{_build_history_block(history)}\n\n"
            f"Design the next experimental build."
        )
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_MODEL, max_tokens=_MAX_TOKENS,
            system=[
                {"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}},
            ],
            messages=[{"role": "user", "content": prompt}],
            timeout=15,
        )
        # AUDIT 2026-05-23 (cost-trace gap C): feed cost_tracker.
        try:
            from core.cost_tracker import record_anthropic_response
            record_anthropic_response(resp, model=_MODEL, purpose="experimental_builder")
        except Exception as exc:
            logger.debug("cost_tracker record: %s", exc)
        raw = resp.content[0].text if resp.content else ""
        parsed = _parse_haiku(raw)
        if not parsed["runes"]["keystone"] or not parsed["items"]:
            logger.warning("experimental: parse incomplete for %s: %s", champion, parsed)
            return None
        parsed["raw"] = raw[:1500]
        return parsed
    except Exception as exc:
        logger.warning("experimental Haiku call failed for %s: %s", champion, exc)
        return None


def generate(champion: str, api_key: str | None) -> dict | None:
    """Generate the FIRST experimental build for a champion. No history."""
    if not api_key:
        logger.info("experimental: no API key - skipping generation for %s", champion)
        return None
    return _create_iteration(champion, history=[], api_key=api_key, premise="initial")


def adapt(champion: str, api_key: str | None) -> dict | None:
    """Generate the NEXT iteration - Haiku considers full history."""
    if not api_key:
        logger.info("experimental: no API key - skipping adapt for %s", champion)
        return None
    history = get_history(champion)
    return _create_iteration(champion, history=history, api_key=api_key, premise="adapt")


def _create_iteration(champion: str, history: list[dict],
                      api_key: str, premise: str) -> dict | None:
    parsed = _call_haiku(champion, history, api_key)
    if not parsed:
        return None
    data = _load()
    champ_entry = data.setdefault(champion, {"current": None, "history": []})
    next_iter = (champ_entry.get("current") or {}).get("iteration", 0) + 1
    if not champ_entry.get("current"):
        next_iter = max(1, len(champ_entry.get("history", [])) + 1)
    parsed.update({
        "iteration":  next_iter,
        "created_at": time.time(),
        "validated":  False,
    })
    champ_entry["current"] = parsed
    _save(data)
    logger.info("experimental: %s iteration %d created (%s)",
                champion, next_iter, parsed["label"])
    return parsed


def _grade_to_verdict(grade: str) -> str:
    g = (grade or "").upper()
    if g in ("S", "A"): return "validated"
    if g == "B":         return "tweak_items"
    if g in ("C", "D"):  return "regen"
    if g == "F":         return "scrap"
    return "regen"


def record_result(champion: str, grade: str, game_state: dict | None,
                  api_key: str | None = None) -> dict:
    """Archive the current build into history with the game's result, then
    decide whether to keep, tweak, or regenerate. If regen is warranted
    and api_key is provided, immediately produces the next iteration."""
    out = {"champion": champion, "verdict": "noop", "next_iteration": None}
    data = _load()
    champ_entry = data.get(champion)
    if not champ_entry or not champ_entry.get("current"):
        out["verdict"] = "no_current"
        return out
    cur = champ_entry["current"]
    gs = game_state or {}
    result = {
        "grade":        grade or "",
        "kda_str":      gs.get("kda", "?"),
        "kp_pct":       gs.get("kp_pct", 0),
        "gold_per_min": gs.get("gold_per_min", 0),
        "notes":        gs.get("notes", []),
    }
    verdict = _grade_to_verdict(grade)
    archived = dict(cur)
    archived.update({"result": result, "verdict": verdict, "ended_at": time.time()})
    champ_entry.setdefault("history", []).append(archived)

    if verdict == "validated":
        # Lock the current build - don't touch it on next pickup
        champ_entry["current"]["validated"] = True
        out["verdict"] = "validated"
        _save(data)
    else:
        # Save first so the regen sees up-to-date history
        _save(data)
        if api_key:
            new = adapt(champion, api_key)
            if new:
                out["next_iteration"] = new["iteration"]
                out["verdict"] = verdict + "+regenerated"
            else:
                out["verdict"] = verdict + "+regen_failed"
        else:
            out["verdict"] = verdict + "+queued"
    return out


def clear(champion: str) -> bool:
    data = _load()
    if champion in data:
        del data[champion]
        _save(data)
        return True
    return False


def mark_active(champion: str, mode: str) -> None:
    """Drop a marker that the user picked experimental for this game.
    Performance tracker reads + clears this on save_rating to attribute
    the result back to this iteration."""
    try:
        _ACTIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _ACTIVE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "champion": champion, "mode": mode, "marked_at": time.time(),
        }), encoding="utf-8")
        tmp.replace(_ACTIVE_PATH)
    except Exception as exc:
        logger.warning("mark_active failed: %s", exc)


def consume_active() -> dict | None:
    """Read the active marker and delete it. Used by performance_tracker
    after a rating is saved to figure out if the experimental was active."""
    if not _ACTIVE_PATH.exists():
        return None
    try:
        data = json.loads(_ACTIVE_PATH.read_text(encoding="utf-8"))
        _ACTIVE_PATH.unlink(missing_ok=True)
        return data
    except Exception as exc:
        logger.warning("consume_active failed: %s", exc)
        try: _ACTIVE_PATH.unlink(missing_ok=True)
        except Exception: pass
        return None
