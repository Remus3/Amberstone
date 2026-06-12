"""s210: Suggestions panel - global ban suggestions endpoint.

GET /api/champ-select/ban-suggestions?exclude=119,236,86,99,51,150&top=4

Returns the top-N globally-banned champions from
``data/meta/global_top_bans.json``, filtered to exclude champions
already banned by either team. Stateless + file-backed; the operator
edits the JSON when the meta shifts.

Distinct from /api/champ-select/pickban-recs (which reads operator-
specific match history). The Suggestions panel surfaces what the
global player base bans; the Pick & Ban panel surfaces what the
operator personally struggles against.

Response:
  {
    "ok": true,
    "patch": "16.10.1",
    "suggestions": [
      {"champId": 777, "name": "Yone", "icon": "/icons/champions/Yone.png"},
      ...up to 4
    ],
    "excluded_count": int,
    "fell_back": bool   // true when fewer than N suggestions remained after filtering
  }
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("rc.web_dashboard")

_BANS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "global_top_bans.json"
_CHAMPS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_champions.json"

# Module-level resolver cache. ddragon_champions.json doesn't change
# across requests; the bans file is small enough to re-read each call
# (~1KB, sub-ms) so we always pick up operator edits without a restart.
_NAME_TO_ID: dict[str, int] | None = None


def _load_name_to_id() -> dict[str, int]:
    """Build display-name → numeric-id index. Stores apostrophe + space
    variants under the same id so 'Kai'Sa' and 'KaiSa' both resolve."""
    global _NAME_TO_ID
    if _NAME_TO_ID is not None:
        return _NAME_TO_ID
    out: dict[str, int] = {}
    try:
        raw = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        for entry in data.values():
            if not isinstance(entry, dict):
                continue
            key = entry.get("key")
            name = entry.get("name")
            slug = entry.get("id")
            if not (key and name):
                continue
            try:
                cid = int(key)
            except (TypeError, ValueError):
                continue
            out[name] = cid
            out[name.replace("'", "")] = cid           # Kai'Sa → KaiSa
            out[name.replace(" ", "")] = cid           # Miss Fortune → MissFortune
            out[name.replace("'", "").replace(" ", "")] = cid
            if slug:
                out[slug] = cid                        # DDragon slug ("KaiSa")
    except Exception as exc:
        log.warning("ban-suggestions: ddragon_champions load failed: %s", exc)
    _NAME_TO_ID = out
    return out


def _parse_int_csv(raw: str) -> set[int]:
    out: set[int] = set()
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.add(int(chunk))
        except ValueError:
            continue
    return out


def _load_bans_file() -> dict:
    try:
        return json.loads(_BANS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.warning("ban-suggestions: %s missing", _BANS_PATH)
        return {"top_bans": [], "patch": "unknown"}
    except Exception as exc:
        log.warning("ban-suggestions: load failed: %s", exc)
        return {"top_bans": [], "patch": "unknown"}


def _serve_ban_suggestions(h) -> None:
    try:
        qs = parse_qs(urlparse(h.path).query)
        exclude_raw = (qs.get("exclude") or [""])[0]
        excluded = _parse_int_csv(exclude_raw)
        top_raw = (qs.get("top") or ["4"])[0]
        try:
            top = max(1, min(10, int(top_raw)))
        except ValueError:
            top = 4

        bans_doc = _load_bans_file()
        idx = _load_name_to_id()

        suggestions: list[dict] = []
        for name in bans_doc.get("top_bans", []):
            if len(suggestions) >= top:
                break
            cid = idx.get(name)
            if cid is None:
                # Try a few slug variants before giving up.
                cid = (idx.get(name.replace("'", ""))
                       or idx.get(name.replace(" ", ""))
                       or idx.get(name.replace("'", "").replace(" ", "")))
            if cid is None:
                log.debug("ban-suggestions: unresolved name %r", name)
                continue
            if cid in excluded:
                continue
            # Use the DDragon slug for the icon URL - name_to_id includes
            # slug→cid mappings, so reverse-find via the icon path is
            # safest by always sanitizing the display name.
            slug = name.replace(" ", "").replace("'", "").replace(".", "")
            suggestions.append({
                "champId": cid,
                "name":    name,
                "icon":    f"/icons/champions/{slug}.png",
            })

        h._send(200, json.dumps({
            "ok": True,
            "patch": bans_doc.get("patch", "unknown"),
            "suggestions": suggestions,
            "excluded_count": len(excluded),
            "fell_back": len(suggestions) < top,
        }).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/champ-select/ban-suggestions: %s", exc)
        # Raw exception text stays in the log only.
        h._send(500, json.dumps(
            {"ok": False, "error": "internal error - see logs"}).encode(),
            "application/json")


def _equals(p: str):
    def m(path: str) -> bool: return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/champ-select/ban-suggestions"), _serve_ban_suggestions),
]
POST_ROUTES: list = []
