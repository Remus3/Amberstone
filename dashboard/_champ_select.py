"""Champ-select brief generator (Haiku-backed).

Tier 2 helper-shake (2026-05-01): extracted from web_dashboard.py.

`brief_via_coach()` asks Claude Haiku for a unified champ-select brief -
build path + runes + ally notes - in a single API call. Cached
aggressively (10 minute TTL, keyed by champion + enemies + allies +
role + mode) because dashboard polls hit the same context repeatedly
during a single champ-select phase.

The cache is a module-level dict trimmed to ~100 entries when it grows
past 200; LRU-by-timestamp eviction. Nothing outside this module reads
it.

API key sourced from `<APP_DIR>/API-Key-Claude.txt` - same path
convention as the rest of RC. Returns the empty `{build: [], runes: {},
ally_notes: ""}` shape on any error so callers don't need to guard.
"""
from __future__ import annotations

import json
import logging
import time

from dashboard._context import APP_DIR

log = logging.getLogger("rc.web_dashboard")

# Cached by (champion, frozenset(enemies), frozenset(allies), role, mode)
# for 10 minutes. Trimmed when size exceeds 200.
_CACHE: dict = {}
_TTL_S = 600


def brief_via_coach(champ: str, enemies: list, allies: list,
                    role: str, mode: str) -> dict:
    """Ask Haiku for a unified champ-select brief: build path + runes + ally
    notes. One API call per unique context. Returns dict with build, runes,
    ally_notes. Cached aggressively."""
    key = (champ, frozenset(enemies), frozenset(allies), role, mode)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and (now - cached["ts"]) < _TTL_S:
        return cached["brief"]
    empty = {"build": [], "runes": {}, "ally_notes": ""}
    try:
        key_path = APP_DIR / "API-Key-Claude.txt"
        api_key = key_path.read_text(encoding="utf-8").strip() if key_path.exists() else ""
        if not api_key.startswith("sk-ant-"):
            return empty
        import anthropic as _a
        client = _a.Anthropic(api_key=api_key)
        aram_note = ""
        if mode.upper() in ("ARAM", "KIWI"):
            aram_note = (
                "This is ARAM - no lane phase, single mid lane, can't recall to "
                "base. Prioritize items that complete fast, sustain (BT/Shieldbow "
                "for squishy carries, Spirit Visage for AP bruisers). Skip Teleport. "
                "Prefer one early tank/sustain item over pure damage for mid-game "
                "fights. Item path should reflect the constant-combat pacing."
            )
        prompt = (
            f"You are a League champ-select advisor. Return STRICT JSON only.\n\n"
            f"CHAMPION: {champ}\n"
            f"MODE: {mode}\n"
            f"ROLE: {role or 'default'}\n"
            f"ENEMIES: {', '.join(enemies) if enemies else '(unknown)'}\n"
            f"ALLIES: {', '.join(allies) if allies else '(unknown)'}\n"
            f"{aram_note}\n\n"
            f"Output JSON with this exact shape (no markdown, no commentary):\n"
            f'{{\n'
            f'  "build": ["item1", ..., "item7"],\n'
            f'  "runes": {{\n'
            f'    "keystone": "Keystone name",\n'
            f'    "primary_tree": "Precision|Domination|Sorcery|Resolve|Inspiration",\n'
            f'    "secondary_tree": "same set, different from primary",\n'
            f'    "shards": ["Adaptive|Attack Speed|Ability Haste",\n'
            f'               "Adaptive|Armor|Magic Resist|Move Speed|Health Scaling",\n'
            f'               "Armor|Magic Resist|Health|Tenacity and Slow Resist"]\n'
            f'  }},\n'
            f'  "ally_notes": "ONE sentence: who on my team is the main carry/engage and '
            f'what my priority is in teamfights."\n'
            f'}}\n\n'
            f"Rules:\n"
            f"- 'build' = 7 entries in purchase order (6 legendaries + boots slotted realistically).\n"
            f"- Item names must match League in-game spelling exactly.\n"
            f"- Avoid redundant items (e.g. no Lord Dominik's AND Mortal Reminder).\n"
            f"- Consider enemy threats for item choices (armor/MR/heal/burst).\n"
            f"- For runes, return the keystone + trees + 3 shards the champ actually runs.\n"
            f"- 'ally_notes' = empty string if ALLIES is unknown."
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # Strip any stray code fences
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            data = json.loads(text)
        except Exception:
            # Best-effort salvage: find first { ... last }
            a, b = text.find("{"), text.rfind("}")
            if a != -1 and b > a:
                try: data = json.loads(text[a:b+1])
                except Exception: data = {}
            else:
                data = {}
        brief = {
            "build":      data.get("build") or [],
            "runes":      data.get("runes") or {},
            "ally_notes": (data.get("ally_notes") or "")[:300],
        }
        _CACHE[key] = {"ts": now, "brief": brief}
        if len(_CACHE) > 200:
            oldest = sorted(_CACHE.items(), key=lambda x: x[1]["ts"])[:100]
            for k, _ in oldest:
                _CACHE.pop(k, None)
        return brief
    except Exception as exc:
        log.warning("brief_via_coach(%s): %s", champ, exc)
        return empty
