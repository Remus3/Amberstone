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

`my_champion` and every list entry must be a string of at most _MAX_NAME_CHARS
that still holds a letter or digit once sanitised. `queue_id` picks the prompt's mode label
(Arena, ARAM); `is_aram` counts only as a real boolean true. A list field reads
at most _MAX_NAMES entries; any other shape counts as empty.

Returns:
    {
        "ok":           bool,   # True only when the reply carried advice
        "advice":       str,    # 1-line headline ("Stay Ahri - clean wave clear vs Cait/Lux"),
                                # or a friendly "(...)" line when ok is False
        "swap":         str,    # ARAM bench swap recommendation, "" if none
        "summoners":    str,    # suggested D/F spells ("Flash + Heal" or similar)
        "watchout":     str,    # primary threat to track
        "raw":          str,    # the reply text for debugging, capped at 1500 chars
        "elapsed_ms":   int,
    }

Cost: one Haiku call per invocation (~$0.001), and no call at all for a state or
key that cannot produce advice. SDK retries are off so a timeout cannot bill
again unrecorded. Dashboard SHOULD debounce state changes so we don't burn one
call per pick during active draft; nothing on the server does.
"""
from __future__ import annotations

import logging
import re
import sys
import time
from itertools import islice
from typing import Any

from core.log_scrub import scrub_log

# RM-364: `state` here is an HTTP POST body forwarded verbatim from
# dashboard/routes_coach.py, so EVERY interpolated field is attacker-shaped
# by construction - not one named field. Sanitised at assembly.
from core.prompt_sanitize import _INJECTION_MARKER, _NEWLINE_TOKEN, DEFAULT_MAX_LEN
from core.prompt_sanitize import clean as _psan_clean
from core.queue_modes import mode_key_from_queue_id

logger = logging.getLogger("rc.coaches.champ_select")

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 350

# The friendly line for every path that spent or tried to spend and has nothing
# to show. Raw API errors stay in the log (CLAUDE.md error-handling rule). Any
# retry is the caller's next POST; the SDK does not retry here.
_PAUSED = "(coaching paused - retrying)"

# An over-long entry is DROPPED rather than cut: a cut mid-phrase could leave a
# fragment of an injection that the sanitizer's patterns no longer match. The
# longest champion name is well under this.
_MAX_NAME_CHARS = 64
# Arena 3x6 has 15 opponents, the largest list a real pick state can hold.
_MAX_NAMES = 16

_RIFT_LABEL = "Summoner's Rift draft/blind"
# Bullets, numbering, headings and bold around a label.
_LABEL_EDGE_RE = re.compile(r"^[^A-Za-z]+|[^A-Za-z]+$")
_WRAPPED_RE = re.compile(r"^([*_`]+)(.+?)\1$")
# "No" alone has to count, so a swap line opening with the word "No" or "Not" is
# dropped: an empty swap is the safe way to be wrong.
_NO_SWAP_RE = re.compile(r"(?i)^\W*(?:none|no|not|nope|nothing|nil|n/?a|n\.a|don.?t|keep|stay)\b")

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


def _drop_unpaired(s: str) -> str:
    """Remove decoration with nothing to pair with. A line's bold can straddle
    the colon ("**Advice:** x", "**Advice: x**"), which leaves one unpaired half
    in the value. A bold marker can go wherever it is; a single marker only at
    an edge, since inside a word it may be text ("snake_case")."""
    for mark in ("**", "__"):
        if s.count(mark) % 2:
            head, _, tail = s.partition(mark) if s.startswith(mark) else s.rpartition(mark)
            s = (head + tail).strip()
    for mark in ("*", "_", "`"):
        if s.count(mark) % 2:
            if s.startswith(mark):
                s = s[1:].strip()
            elif s.endswith(mark):
                s = s[:-1].strip()
    return s


def _field_value(text: str) -> str:
    """A label's value without decoration that belongs to the line rather than
    the text: an unpaired half of bold, or bold wrapping the whole value. Markup
    inside the value ("Stay **Ahri**") is the model's text and stays. A value
    with no letter or digit is no value."""
    s = _drop_unpaired(text.strip())
    wrapped = _WRAPPED_RE.match(s)
    if wrapped and wrapped.group(1) not in wrapped.group(2):
        s = wrapped.group(2).strip()
    return s if any(ch.isalnum() for ch in s) else ""


def _parse_response(raw: str) -> dict[str, str]:
    """Read the four labelled lines. Models decorate them with markdown despite
    the system prompt, so anything but letters is ignored around a label. The
    first non-empty value of a label wins."""
    fields: dict[str, str] = {"advice": "", "swap": "", "summoners": "", "watchout": ""}
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s or ":" not in s:
            continue
        label, _, val = s.partition(":")
        key = _LABEL_EDGE_RE.sub("", label).lower()
        if key in fields and not fields[key]:
            fields[key] = _field_value(val)[:200]
    return fields


def _name(value: object) -> str:
    """The sanitised champion name in `value`, or "" if it cannot be one. The
    letter-or-digit test reads the sanitised text, because cleaning can leave
    nothing of a name: U+3164 is alnum but cleans to a space, and a bare role
    marker cleans to the blocked marker. Cleaning runs uncapped and an oversized
    result is dropped, because clean()'s own cap could cut a marker into a
    fragment that this test would read as letters."""
    if not isinstance(value, str) or len(value) > _MAX_NAME_CHARS:
        return ""
    cleaned = _psan_clean(value, max_len=sys.maxsize).strip()
    if len(cleaned) > DEFAULT_MAX_LEN:
        return ""
    residue = cleaned.replace(_INJECTION_MARKER, "").replace(_NEWLINE_TOKEN, "")
    return cleaned if any(ch.isalnum() for ch in residue) else ""


def _names(value: object) -> list[str]:
    """Sanitised names from a list field. Only a list or tuple counts: a string
    would iterate by character and a dict by key. The cap applies to entries
    READ, so the work this function does for one request is bounded."""
    if not isinstance(value, (list, tuple)):
        return []
    return [n for n in map(_name, islice(value, _MAX_NAMES)) if n]


def _mode_key(state: dict) -> str | None:
    """Dashboard mode key from an integer queue_id. A JSON float is refused here
    because mode_key_from_queue_id's int() raises on Infinity."""
    qid = state.get("queue_id")
    return mode_key_from_queue_id(qid) if isinstance(qid, int) else None


def _safe_error_text(exc: BaseException, api_key: str) -> str:
    """Exception text fit for the log: an HTTP layer can quote a bad header
    value, so the key is removed, and the text cannot start a new log line."""
    try:
        text = str(exc)
    except Exception:  # noqa: BLE001 - a broken __str__; never raises is the contract
        text = "<exception text unavailable>"
    return scrub_log(text.replace(api_key, "[redacted]"))


def _usable_key(api_key: object) -> str:
    """The key to send, or "" if it cannot be one. A header value with anything
    else in it could not authenticate, and an HTTP layer might quote it back."""
    key = api_key.strip() if isinstance(api_key, str) else ""
    return key if key.isascii() and key.isprintable() and " " not in key else ""


def _close_quietly(client: Any) -> None:
    """Release the client's connection pool. By now the call is over and may
    have been paid for, so a failed close must not cost the caller its answer."""
    if client is None:
        return
    try:
        client.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("champ-select coach: client close: %s", type(exc).__name__)


def _reply_text(resp: Any) -> str:
    """All text in the reply. A block with no text (any non-text type) is
    skipped rather than assumed away by reading content[0]."""
    parts = [getattr(block, "text", None) for block in (resp.content or [])]
    return "\n".join(p for p in parts if isinstance(p, str))


def _swap_value(value: str, *, is_aram: bool, bench: list[str]) -> str:
    """The swap line only means something in ARAM with a bench to swap from."""
    if not is_aram or not bench or _NO_SWAP_RE.match(value):
        return ""
    return value


def coach_pick(state: dict, api_key: str | None) -> dict[str, Any]:
    """Synchronous Haiku call. Returns advice dict; never raises."""
    out: dict[str, Any] = {
        "ok": False, "advice": "", "swap": "", "summoners": "",
        "watchout": "", "raw": "", "elapsed_ms": 0,
    }
    my_champion = _name(state.get("my_champion")) if isinstance(state, dict) else ""
    if not my_champion:
        out["advice"] = "(no champion locked yet)"
        return out
    # Spend-gate: champ-select Anthropic calls off via Settings kill-switch.
    # A gate that cannot be read stays open, as at every other gate_disabled
    # site, but it is logged: the operator may believe this switch is off.
    try:
        from core.cost_tracker import get_tracker as _gt
        if _gt().gate_disabled("champ_select"):
            out["advice"] = "(champ-select coach disabled)"
            return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("champ-select coach: spend gate unreadable: %s", type(exc).__name__)
    key = _usable_key(api_key)
    if not key:
        out["advice"] = "(API key missing - coach disabled)"
        return out

    mode_key = _mode_key(state)
    is_aram = state.get("is_aram") is True or mode_key == "aram"
    mode_label = "ARAM" if is_aram else "Arena" if mode_key == "arena" else _RIFT_LABEL
    my_team = ", ".join(_names(state.get("my_team"))) or "?"
    their_team = ", ".join(_names(state.get("their_team"))) or "?"
    bench = _names(state.get("bench"))
    bench_line = (f"Bench: {', '.join(bench)}" if (is_aram and bench)
                  else "")

    prompt = _USER_TEMPLATE.format(
        mode_label=mode_label,
        my_champion=my_champion,
        my_team=my_team,
        their_team=their_team,
        bench_line=bench_line,
    )

    t0 = time.perf_counter()
    client = None
    try:
        import anthropic
        # max_retries=0: the SDK's default of 2 retries a timeout, so one call
        # could block a handler thread for three 12 s timeouts plus backoff and
        # bill attempts cost_tracker never sees.
        client = anthropic.Anthropic(api_key=key, base_url="https://api.anthropic.com", max_retries=0)
        # cache_control matches the per-tick coaches, but this system prompt is
        # far below Haiku 4.5's minimum cacheable prefix, and a shorter prefix
        # silently does not cache - so today the marker saves nothing.
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
            logger.warning("champ-select coach: cost_tracker record: %s", type(exc).__name__)
        stop_reason = getattr(resp, "stop_reason", None)
        raw = "" if stop_reason == "refusal" else _reply_text(resp)
    except Exception as exc:  # noqa: BLE001
        # Never surface the raw exception (type or message) to the UI - the
        # advice field is user-facing. Friendly degrade + log the raw error.
        out["advice"] = _PAUSED
        out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        logger.warning("champ-select coach: %s: %s", type(exc).__name__, _safe_error_text(exc, key))
        return out
    finally:
        _close_quietly(client)

    elapsed = int((time.perf_counter() - t0) * 1000)
    fields = _parse_response(raw)
    out.update({
        "ok": bool(fields["advice"]),
        "advice":    fields["advice"],
        "swap":      _swap_value(fields["swap"], is_aram=is_aram, bench=bench),
        "summoners": fields["summoners"],
        "watchout":  fields["watchout"],
        "raw":       raw[:1500],
        "elapsed_ms": elapsed,
    })
    if not out["ok"]:
        # A reply that was paid for and holds no advice would otherwise answer
        # a blank panel with nothing in the log to say why.
        out["advice"] = _PAUSED
        stop = stop_reason if isinstance(stop_reason, str) else type(stop_reason).__name__
        logger.warning("champ-select coach: no advice in reply (stop_reason=%s, %d chars)",
                       scrub_log(stop), len(raw))
    return out
