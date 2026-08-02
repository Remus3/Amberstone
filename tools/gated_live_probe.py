# arch: one-shot live-game evidence probe for the gated-drain lane | section=tools | frozen=no
"""gated_live_probe.py - dump the evidence-contract facts for the CURRENT game.

Lane 9 (Headless-Gated) re-derives the same handful of live facts at the top of
every in-game drain pass of ``docs/LIVE_GAME_GATED_SYNC.md``: what mode is up,
which gate that maps to, the real comp, whether the vision frame is fresh,
whether the Haiku coach is credit-paused, and which serving surfaces actually
carry the value a row wants. Doing that by hand mid-game burns the scarce
in-game minutes the whole lane exists to spend well. This tool answers all of it
in ONE command so the in-game pass is copy-paste, not a re-derivation.

It is READ-ONLY: it GETs the local HTTPS dashboard and the vision relay and
prints. It never writes, never restarts, never touches the engine, and never
ticks a row - closing a row still needs recorded live evidence per the four-part
evidence contract in the doc. This only tells you what THIS game can prove.

WHAT IT REPORTS (the evidence-contract inputs, section 3 of the lane skill):
  - mode_key + the in-game verdict (mode_key in the live set AND liveclient
    non-empty), and the GATE that mode maps to.
  - champion / level / game_time / game_id, and the real ally + enemy comps.
  - coach_source and the deterministic coach fields (action / immediate /
    fight_rule / risk), plus a Haiku-credit-paused flag lifted from the
    friendly degraded-mode string (never the raw API error - Error Handling
    rule) so a blocked-by-credits session is called plainly.
  - vision health: /latest-frame byte count and /latest-liveclient presence. A
    zero-byte frame BLOCKS every pixel / OCR / augment-render row this session.
  - serving-surface probes: whether /api/state carries a cc-* panel (the G3-11
    close path) and any st-* / adaptation fields (the G7-04 census), so the
    SUBSTITUTION trap is visible - a value the engine computes but no live
    surface serves is NOT drainable by playing.
  - minimap dot count + zoi presence.

USAGE
    python tools/gated_live_probe.py            # human markdown to stdout
    python tools/gated_live_probe.py --json      # machine-readable JSON
    python tools/gated_live_probe.py --base URL  # non-default dashboard base

Fail-soft: any probe that cannot reach its endpoint yields a null section and a
noted reason, never an exception. Non-zero exit means "could not reach RC", which
is itself a useful answer (RC down, or no game host).
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.request
from pathlib import Path

_DASH_BASE = "https://127.0.0.1:8888"
# The vision server on :8889 is plain HTTP and token-gated - NOT https.
# This was `https://` and sent no token, so every vision probe failed at the
# TLS layer (or 401'd over http) and the tool reported `frame_dead=True`
# unconditionally. That false negative reached
# `docs/LIVE_GAME_GATED_SYNC.md` as a PRECONDITION and blocked G3-13.
# Measured 2026-08-02 mid-game: this method returned 0 bytes while an
# authenticated HTTP GET to the same endpoint returned 243396 bytes aged
# 0.9s. Ground truth for both facts is `modes/shared_vision.py:25` +
# `_capture_screen`. Pinned by tests/test_gated_live_probe_relay_auth.py.
_RELAY_BASE = "http://127.0.0.1:8889"


_SENTINEL = object()


def _relay_token() -> str:
    """Canonical vision-relay token (env -> config file -> legacy default).

    Fail-soft by contract (see module docstring: "never an exception"). Run as
    `python tools/gated_live_probe.py` the repo root is NOT on sys.path, so the
    `core.vision_token` import raises ModuleNotFoundError - which crashed the
    tool once already. Put the repo root on the path, and if the import still
    fails return "" so the caller simply sends no header and reports a reachable
    error instead of dying.
    """
    try:
        from core.vision_token import get_vision_token
    except ModuleNotFoundError:
        root = str(Path(__file__).resolve().parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            from core.vision_token import get_vision_token
        except Exception:  # noqa: BLE001 - fail-soft probe
            return ""
    except Exception:  # noqa: BLE001 - fail-soft probe
        return ""
    try:
        return get_vision_token() or ""
    except Exception:  # noqa: BLE001 - fail-soft probe
        return ""
_TIMEOUT = 3.0

# The dashboard cert is mkcert self-signed; skip verification like every other
# local RC probe (rc_facts.py, live_flip_watcher.py).
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

# game-monitor / lane-skill gate: these mode_keys are "in a game" when liveclient
# is also non-empty. Anything else (client, null) is lobby/idle.
_IN_GAME_MODES = {"sr", "arena", "aram", "tft", "brawl"}

# mode_key -> the gate section its live rows live under.
_MODE_TO_GATE = {
    "sr": "GATE 2 (practice) / GATE 4 (matchmade)",
    "aram": "GATE 3 (ARAM Mayhem q2400 KIWI)",
    "arena": "GATE 5 (Arena/Cherry q1750)",
    "tft": "(no dedicated gate)",
    "brawl": "(brawl retired from champ-select)",
    "client": "GATE 1 (lobby/champ-select)",
}


def _request(url: str, token: str | None) -> urllib.request.Request:
    """Build the GET. The :8889 relay endpoints are token-gated (401 without)."""
    headers = {"X-RC-Token": token} if token else {}
    return urllib.request.Request(url, headers=headers)


def _get_json(url: str, token: str | None = _SENTINEL) -> tuple[dict | None, str | None]:
    if token is _SENTINEL:
        token = _relay_token()
    try:
        with urllib.request.urlopen(_request(url, token), timeout=_TIMEOUT,
                                    context=_SSL) as r:
            return json.loads(r.read().decode("utf-8")), None
    except Exception as exc:  # noqa: BLE001 - fail-soft probe
        return None, f"{type(exc).__name__}: {exc}"


def _get_nbytes(url: str, token: str | None = _SENTINEL) -> tuple[int | None, str | None]:
    if token is _SENTINEL:
        token = _relay_token()
    try:
        with urllib.request.urlopen(_request(url, token), timeout=_TIMEOUT,
                                    context=_SSL) as r:
            return len(r.read()), None
    except Exception as exc:  # noqa: BLE001 - fail-soft probe
        return None, f"{type(exc).__name__}: {exc}"


def _is_cc_key(key: str) -> bool:
    """Match cc-panel keys (cc, cc_blended, cc_conditional, foo_cc) without the
    'auto_accept' / 'account' / 'access' false positives that a naive substring
    test hits."""
    k = str(key).lower()
    return k == "cc" or k.startswith("cc_") or k.endswith("_cc") or "_cc_" in k


def _scan_keys(obj: object, pred, path: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}/{k}"
            if pred(k):
                hits.append(p)
            hits.extend(_scan_keys(v, pred, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:3]):
            hits.extend(_scan_keys(v, pred, f"{path}[{i}]"))
    return hits


def _is_adapt_key(key: str) -> bool:
    k = str(key).lower()
    return k.startswith("st_") or k.startswith("st-") or "adapt" in k


def collect(dash_base: str, relay_base: str) -> dict:
    state, state_err = _get_json(f"{dash_base}/api/state")
    frame_bytes, frame_err = _get_nbytes(f"{relay_base}/latest-frame")
    relay, relay_err = _get_json(f"{relay_base}/latest-liveclient")

    out: dict = {
        "reachable": state is not None,
        "state_error": state_err,
        "vision": {
            "frame_bytes": frame_bytes,
            "frame_error": frame_err,
            "frame_dead": (frame_bytes == 0) or (frame_bytes is None),
            "relay_present": relay is not None,
            "relay_error": relay_err,
        },
    }
    if state is None:
        out["in_game"] = False
        return out

    lc = state.get("liveclient") or {}
    coach = state.get("coach") or {}
    mode_key = state.get("mode_key")
    lc_nonempty = isinstance(lc, dict) and len(lc) > 0
    in_game = mode_key in _IN_GAME_MODES and lc_nonempty

    immediate = str(coach.get("immediate") or "")
    # degraded-mode string is friendly by design (Error Handling rule); never a
    # raw API error. Detect the paused/credits phrasing, not a raw 4xx.
    credit_paused = ("paused" in immediate.lower()) or ("add api credits" in immediate.lower())

    out.update(
        {
            "in_game": in_game,
            "mode_key": mode_key,
            "gate": _MODE_TO_GATE.get(str(mode_key), "(unmapped mode_key)"),
            "champion": lc.get("champion"),
            "level": lc.get("level"),
            "game_time": lc.get("game_time"),
            "game_time_s": lc.get("game_time_s"),
            "game_id": lc.get("game_id"),
            "game_mode": lc.get("game_mode"),
            "ally_team": lc.get("ally_team"),
            "enemy_team": lc.get("enemy_team"),
            "coach_source": state.get("coach_source"),
            "coach": {
                "action": coach.get("action"),
                "immediate": coach.get("immediate"),
                "fight_rule": coach.get("fight_rule"),
                "risk": coach.get("risk"),
            },
            "haiku_credit_paused": credit_paused,
            "serving_surfaces": {
                "cc_panel_in_state": _scan_keys(state, _is_cc_key),
                "adapt_fields_in_state": _scan_keys(state, _is_adapt_key),
            },
            "minimap_dot_count": len(state.get("minimap_dots") or []),
            "zoi_present": bool(state.get("zoi")),
        }
    )
    return out


def _render(facts: dict) -> str:
    lines: list[str] = ["# gated_live_probe"]
    if not facts.get("reachable"):
        lines.append(f"RC UNREACHABLE: {facts.get('state_error')}")
        return "\n".join(lines)

    ig = facts.get("in_game")
    lines.append(f"IN-GAME: {ig}  mode_key={facts.get('mode_key')!r}  gate={facts.get('gate')}")
    if not ig:
        lines.append("Not in a game (PREP half - the drain half does not run).")
        return "\n".join(lines)

    lines.append(
        f"champ={facts.get('champion')} L{facts.get('level')} "
        f"t={facts.get('game_time')} game_mode={facts.get('game_mode')!r} game_id={facts.get('game_id')!r}"
    )
    lines.append(f"ally  = {facts.get('ally_team')}")
    lines.append(f"enemy = {facts.get('enemy_team')}")
    c = facts.get("coach") or {}
    lines.append(f"coach_source={facts.get('coach_source')!r}  haiku_credit_paused={facts.get('haiku_credit_paused')}")
    lines.append(f"  action    = {c.get('action')!r}")
    lines.append(f"  immediate = {c.get('immediate')!r}")
    lines.append(f"  fight_rule= {c.get('fight_rule')!r}")
    lines.append(f"  risk      = {c.get('risk')!r}")

    v = facts.get("vision") or {}
    dead = " (DEAD - blocks every pixel/OCR/augment row this session)" if v.get("frame_dead") else ""
    lines.append(f"vision frame_bytes={v.get('frame_bytes')}{dead}  relay_present={v.get('relay_present')}")

    ss = facts.get("serving_surfaces") or {}
    cc = ss.get("cc_panel_in_state") or []
    lines.append(f"cc_panel_in_state={cc or 'NONE (G3-11 game-path inert; close needs the panel wired)'}")
    lines.append(f"adapt_fields_in_state={ss.get('adapt_fields_in_state') or 'NONE (G7-04: post-game-only this mode)'}")
    lines.append(f"minimap_dots={facts.get('minimap_dot_count')}  zoi_present={facts.get('zoi_present')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="one-shot live-game evidence probe for the gated-drain lane")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON instead of markdown")
    ap.add_argument("--base", default=_DASH_BASE, help="dashboard base URL (default %(default)s)")
    ap.add_argument("--relay", default=_RELAY_BASE, help="vision relay base URL (default %(default)s)")
    args = ap.parse_args(argv)

    facts = collect(args.base, args.relay)
    if args.json:
        print(json.dumps(facts, indent=2))
    else:
        print(_render(facts))
    return 0 if facts.get("reachable") else 1


if __name__ == "__main__":
    sys.exit(main())
