# arch: cs archetype pick rest endpoints | section=dashboard | frozen=no
"""Phase 3 (s176, 2026-05-12) - REST endpoints for the CS archetype picks.

Mirror of ``routes_lobby_aux`` shape: GET reads, POST writes, with atomic
file persistence under the hood via ``core.archetype_picks``.

Callers: the champ-select view in ``web/js/panels/champ_select.js`` only
GETs the resolved pick (``_csvFetchArchetype``) for its read-only chip.
LEDGER 824 removed the picker grid and both of its POSTs (save ``user_cs`` +
clear), so no dashboard surface sends a POST here any more; the routes stay
registered for scripted callers (curl). A saved pick is NOT cosmetic: every
``core.archetype_picks.get_archetype_for`` consumer reads it, including the
coach dispatcher and ``core/build_order_precompute.py`` (RM-164), so a POST
changes which scorer ranks that champion's builds.

Routes:

* ``GET  /api/cs-archetype-pick?champion=<id>``
    Returns the merged pick (explicit override OR DDragon-tag default).
    No champion param returns the full persisted map under "picks", the
    archetype enum under "archetypes" and the sources a POST may save under
    "sources".

* ``POST /api/cs-archetype-pick``
    Body: ``{ champion, primary, secondary?, source? }``.
    Returns the canonicalized entry.

* Clear via POST with ``{ champion, clear: true }`` - falls back to the
    default. No separate DELETE method, to keep the dispatch table simple.

* ``GET  /api/archetype-nudge`` / ``POST /api/archetype-nudge/dismiss``
    The s184 first-purchase nudge diagnostic and its dismiss.

Body contract (s144 true-audit cycle 77; ``dashboard._dispatch`` does NOT
validate these bodies - ``ArchetypeNudgeDismissRequest`` is not in its
``_REQUEST_MODELS`` - so this module is the only gate):

* ``champion`` is a string, stripped, 1..``_MAX_CHAMPION_LEN`` characters,
  every one printable. Anything else is ``400 {"error": "invalid champion"}``
  and nothing is written; a missing / null / blank one is
  ``400 {"error": "champion required"}``. The value is never echoed in an
  error.
* ``primary`` / ``secondary`` / ``source`` are strings when present; null or
  an empty string reads as absent (``primary`` is then required). Any other
  type is ``400 {"error": "invalid pick - see logs"}``, logged by field and
  type only.
* ``source`` may be ``user_cs`` (the default), ``user_ingame`` or ``nudge``.
  ``default`` is refused: a persisted override labelled "default" would be
  skipped by the nudge evaluator as not-operator-intent while still
  overriding the DDragon default. Use ``clear`` to go back to the default.
* Unknown keys are ``400 {"error": "unknown field - see logs"}``, so a typo
  never saves a pick the caller did not ask for.
* At most ``_MAX_PICKS`` distinct champions are saved; a NEW champion past
  that is ``409`` (re-saving or clearing an existing one always works).
"""
import json
import logging
from urllib.parse import urlparse, parse_qs

from core.archetype_mismatch import (
    dismiss_nudge,
    get_nudge_state_snapshot,
)
from core.archetype_picks import (
    ARCHETYPES,
    IMPLEMENTED_SCORERS,
    SOURCE_DEFAULT,
    SOURCE_USER_CS,
    VALID_SOURCES,
    PicksReadError,
    clear_archetype_pick,
    get_archetype_for,
    list_archetype_picks,
    save_archetype_pick,
)
from dashboard._dispatch import equals
from dashboard._errors import send_error
from dashboard._json_flags import bad_flag_body, coerce_json_flag

log = logging.getLogger("rc.web_dashboard")

# Longest real champion display name is 14 characters ("Nunu & Willump");
# 64 leaves room for any localized or future name and still bounds a key.
_MAX_CHAMPION_LEN = 64
# The roster is ~173 champions; a cap well above it only stops unbounded
# growth of the picks file, which every save rewrites whole.
_MAX_PICKS = 512
# Sources a POST may save. SOURCE_DEFAULT is resolver output, not intent.
_POST_SOURCES = frozenset(VALID_SOURCES) - {SOURCE_DEFAULT}
_PICK_KEYS = frozenset({"champion", "primary", "secondary", "source", "clear"})
_DISMISS_KEYS = frozenset({"champion"})
# Unknown-key log line: at most this many names, each clipped.
_LOG_MAX_KEYS = 10
_LOG_KEY_CHARS = 40

_REQUIRED = "required"
_INVALID = "invalid"


def _json_send(h, status: int, payload: dict) -> None:
    h._send(status, json.dumps(payload).encode(), "application/json")


def _champion(value):
    """Return ``(champion, problem)`` for a caller-supplied champion.

    ``problem`` is None, ``_REQUIRED`` (absent / null / blank) or
    ``_INVALID`` (wrong type, too long, or a non-printable character).
    """
    if value is None:
        return "", _REQUIRED
    if not isinstance(value, str):
        return "", _INVALID
    champion = value.strip()
    if not champion:
        return "", _REQUIRED
    if len(champion) > _MAX_CHAMPION_LEN or not champion.isprintable():
        return "", _INVALID
    return champion, None


def _send_champion_problem(h, problem: str) -> None:
    error = "champion required" if problem == _REQUIRED else "invalid champion"
    _json_send(h, 400, {"error": error})


def _unknown_keys(h, payload: dict, allowed: frozenset, route: str) -> bool:
    """400 and True when ``payload`` carries a key outside ``allowed``."""
    unknown = [k for k in payload if k not in allowed]
    if not unknown:
        return False
    shown = [repr(str(k)[:_LOG_KEY_CHARS]) for k in unknown[:_LOG_MAX_KEYS]]
    log.warning("%s: %d unknown body field(s) refused: %s", route,
                len(unknown), ", ".join(shown))
    _json_send(h, 400, {"error": "unknown field - see logs"})
    return True


def _optional_str(payload: dict, field: str):
    """Return ``(value, ok)``: a stripped str, or None when absent / null /
    empty. ``ok`` is False when the field holds a non-string."""
    raw = payload.get(field)
    if raw is None:
        return None, True
    if not isinstance(raw, str):
        return None, False
    raw = raw.strip()
    return (raw or None), True


def _send_invalid_field(h, field: str, value) -> None:
    # The type only - the value is caller-chosen and unbounded.
    log.warning("cs-archetype-pick: field %s refused (type %s)",
                field, type(value).__name__)
    _json_send(h, 400, {"error": "invalid pick - see logs"})


def _store_call(h, arm: str, fn, **kwargs):
    """Run a picks-store write. Returns ``(result, True)``, or sends the
    500 and returns ``(None, False)``.

    An unreadable picks file (RM-444 ``PicksReadError``) or a disk error is
    an expected degradation: one WARNING line. Anything else is a bug and is
    logged with its traceback. The raw text (may carry a path) stays in the
    log either way; the client gets a generic line.
    """
    try:
        return fn(**kwargs), True
    except (PicksReadError, OSError) as exc:
        log.warning("cs-archetype-pick %s: %s", arm, exc)
    except Exception:  # noqa: BLE001 - a route must answer; traceback logged
        log.exception("cs-archetype-pick %s: unexpected failure", arm)
    _json_send(h, 500, {"error": f"{arm} failed - see logs"})
    return None, False


def _serve_archetype_get(h) -> None:
    qs = parse_qs(urlparse(h.path).query or "")
    champion_list = qs.get("champion") or []
    raw = champion_list[0] if champion_list else ""
    champion, problem = _champion(raw)
    if problem == _INVALID:
        _send_champion_problem(h, problem)
        return
    if champion:
        entry = get_archetype_for(champion)
        payload = {
            "ok":         True,
            "champion":   champion,
            "pick":       entry,
            "archetypes": list(ARCHETYPES),
            "implemented": sorted(IMPLEMENTED_SCORERS),
        }
    else:
        payload = {
            "ok":          True,
            "picks":       list_archetype_picks(),
            "archetypes":  list(ARCHETYPES),
            "implemented": sorted(IMPLEMENTED_SCORERS),
            "sources":     sorted(_POST_SOURCES),
        }
    _json_send(h, 200, payload)


def _serve_archetype_post(h, payload) -> None:
    """Save or clear a per-champion pick (body contract: module docstring).

    On ``{champion, clear: true}`` clears the override. Otherwise
    requires ``primary``; ``secondary`` and ``source`` are optional.
    """
    if not isinstance(payload, dict):
        _json_send(h, 400, {"error": "JSON object required"})
        return
    if _unknown_keys(h, payload, _PICK_KEYS, "cs-archetype-pick"):
        return
    champion, problem = _champion(payload.get("champion"))
    if problem:
        _send_champion_problem(h, problem)
        return

    # Clear path. RM-414: parsed, never bare-truthy - {"clear": "false"} used
    # to DELETE the saved pick. Absent keeps the old default (no clear); an
    # ambiguous value is a 400 before anything is written.
    # Rule: dashboard/_json_flags.py.
    clear = coerce_json_flag(payload, "clear", False)
    if clear is None:
        h._send(400, bad_flag_body("clear"), "application/json")
        return
    if clear:
        # RM-444: an unreadable picks file raises instead of being overwritten.
        cleared, ok = _store_call(h, "clear", clear_archetype_pick,
                                  champion=champion)
        if not ok:
            return
        _json_send(h, 200, {
            "ok":      True,
            "cleared": cleared,
            "pick":    get_archetype_for(champion),
        })
        return

    primary, ok = _optional_str(payload, "primary")
    if not ok:
        _send_invalid_field(h, "primary", payload.get("primary"))
        return
    if not primary:
        _json_send(h, 400, {"error": "primary required"})
        return
    secondary, ok = _optional_str(payload, "secondary")
    if not ok:
        _send_invalid_field(h, "secondary", payload.get("secondary"))
        return
    source, ok = _optional_str(payload, "source")
    if not ok:
        _send_invalid_field(h, "source", payload.get("source"))
        return
    source = source or SOURCE_USER_CS
    if source == SOURCE_DEFAULT:
        log.warning("cs-archetype-pick: source %r refused - use clear",
                    SOURCE_DEFAULT)
        _json_send(h, 400, {"error": "invalid pick - see logs"})
        return

    existing = list_archetype_picks()
    if champion not in existing and len(existing) >= _MAX_PICKS:
        log.warning("cs-archetype-pick: %d picks saved (cap %d), new "
                    "champion refused", len(existing), _MAX_PICKS)
        _json_send(h, 409, {"error": "too many saved picks - clear one first"})
        return

    try:
        entry = save_archetype_pick(
            champion=champion,
            primary=primary,
            secondary=secondary,
            source=source,
        )
    except ValueError as exc:
        # RM-239 / RM-242: the raiser's text used to be serialized verbatim,
        # so the validator's message (and the operator's raw input) reached
        # the wire. Raw cause to the log, curated literal to the client.
        # 400, not send_error's default 500: this is a client error, and the
        # generic "internal error" line would mis-describe it.
        send_error(h, exc, status=400, public_msg="invalid pick - see logs")
        return
    except (PicksReadError, OSError) as exc:
        log.warning("cs-archetype-pick save: %s", exc)
        _json_send(h, 500, {"error": "save failed - see logs"})
        return
    except Exception:  # noqa: BLE001 - a route must answer; traceback logged
        log.exception("cs-archetype-pick save: unexpected failure")
        _json_send(h, 500, {"error": "save failed - see logs"})
        return

    _json_send(h, 200, {
        "ok":   True,
        "pick": entry,
    })


def _serve_archetype_nudge_get(h) -> None:
    """Diagnostic GET - returns the current in-memory nudge state.

    Not security-sensitive (already exposed via /api/state); the dedicated
    endpoint just makes manual probing easier. Operator can curl it to
    see why a nudge isn't firing.
    """
    snapshot = get_nudge_state_snapshot()
    _json_send(h, 200, {
        "ok": True,
        "state": snapshot,
    })


def _serve_archetype_nudge_dismiss(h, payload) -> None:
    """POST /api/archetype-nudge/dismiss - operator clicked the chip's X.

    Body: ``{ champion: "<name>" }`` and nothing else (the shape of
    ``api_schema.ArchetypeNudgeDismissRequest``). Idempotent - re-dismissing
    an already-dismissed nudge is fine. Returns ``{ok, dismissed, champion}``.
    """
    if not isinstance(payload, dict):
        _json_send(h, 400, {"error": "JSON object required"})
        return
    if _unknown_keys(h, payload, _DISMISS_KEYS, "archetype-nudge dismiss"):
        return
    champion, problem = _champion(payload.get("champion"))
    if problem:
        _send_champion_problem(h, problem)
        return
    dismissed = dismiss_nudge(champion)
    _json_send(h, 200, {
        "ok":        True,
        "dismissed": dismissed,
        "champion":  champion,
    })


GET_ROUTES = [
    (equals("/api/cs-archetype-pick"), _serve_archetype_get),
    (equals("/api/archetype-nudge"),   _serve_archetype_nudge_get),
]

POST_ROUTES = [
    (equals("/api/cs-archetype-pick"),         _serve_archetype_post),
    (equals("/api/archetype-nudge/dismiss"),   _serve_archetype_nudge_dismiss),
]
