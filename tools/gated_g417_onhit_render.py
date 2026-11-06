"""gated_g417_onhit_render.py - read-only grader for G4-17 (on-hit AP build render).

G4-17 asks for the in-game eyeball that the DS Slice B ``onhit`` build (Nashor's
Tooth, item 3115, present) RENDERS on the overlay BUILD panel in a real Gwen /
Kayle / Kog'Maw game. LEDGER 911 proved the backend on ``POST /api/build-plan``
(scorer onhit, Nashor's in the build order).

Facts measured at source (s144 lane gated c74) that shape the check:

- ``/api/build-plan`` does NOT feed the item rows. It feeds only the per-icon
  state badges (``planStates``) and the COUNTER chips. The three painted rows of
  ``#am-build-body`` (``web/js/panels/active_match.js`` ``_renderAmBuildBody``)
  come from: "Daemon Slayer" (``.bm-live``) = ``POST /api/ds-preview``
  ``ranked`` (``_maybeRefreshDsPicks``; falls back to the coach payload's
  ``daemon_slayer_picks`` while the preview cache is empty); "Meta Build"
  (``.bm-meta``) = ``POST /api/build-order`` ``order`` with my owned items and
  level (``_maybeRefreshBuildOrder``); "Ultimate Build" (``.bm-ult``) = the same
  route at level 18 with no items (``_maybeRefreshUltimateOrder``). So the
  LEDGER 911 proof is the wrong route for this row's render question; the
  served ``/api/ds-preview`` reply is the one the Daemon Slayer row paints.
- All three routes resolve the scorer the same way when the client sends no
  archetype (it never does): ``get_archetype_for(champion)["primary"]``, which
  is ``onhit`` for Gwen / Kayle / KogMaw by default, but a persisted operator
  pick in gitignored ``data/cs_archetype_picks.json`` wins over the default, so
  only the served reply's ``scorer`` proves the onhit route ran. ``--preview``
  is therefore required.
- The Daemon Slayer row: the preview's ranked rows (``top`` 8) are
  family-deduped (``_bmFamilyDedupe``; family from the Meta / Ultimate rows'
  ``locked_family`` / ``family`` and the preview rows' ``family``), capped at 7
  (``_BM_SLOT_CAP``), re-ordered by the in-memory operator overrides and MUTE
  (``filterSilenced`` DROPS a silenced item from this row only), then owned
  items sorted left. A headless page has no overrides, so a Nashor's dark only
  on the operator's overlay after a MUTE is not a defect.
- The Meta / Ultimate requests echo an ``incumbent`` (the order already shown)
  for hysteresis, which a curl from outside cannot reproduce, so their
  comparison is ADVISORY; only the Daemon Slayer row is graded strictly.
- A full build (6 slots) answers ``build_complete`` with an empty ranked list
  and scorer ``dps``: graded FULL_BUILD, not a scorer drift.
- An owned Nashor's is not in the preview's ranked rows (it ranks open slots),
  so the eyeball is taken BEFORE buying it.

Sub-commands (READ-ONLY: reads the files named; no network, no write, no tick):

  snippet
      Print the JS expression a HEADLESS Chromium page on the dashboard evaluates
      to capture the three build rows as JSON (save it as the --dom file).
  bodies --state FILE
      Print the three request bodies the client posts for that state:
      ``ds_preview`` (to /api/ds-preview), ``build_order`` and ``ultimate`` (to
      /api/build-order; no incumbent).
  grade --state FILE --dom FILE --preview FILE [--order FILE] [--ultimate FILE]
        [--state-ts EPOCH] [--json]
      Verdicts and exit codes:
        RENDER_MATCH (0)      onhit scorer served, Nashor's painted and visible
                              in the Daemon Slayer row exactly when the preview
                              ranks it in the shown 7, and painted in at least
                              one row; the operator eyeball is STILL owed
        ROSTER_BAD (3)        no coach champion, or not my roster row's
        PANE_ABSENT (3)       ``#am-build-body`` is not in the captured DOM
        PLAN_ERROR (3)        a supplied reply is ok:false
        SCORER_DRIFT (3)      a supplied reply's scorer is not ``onhit``
        RENDER_MISMATCH (3)   the Daemon Slayer row's Nashor's state differs
                              from the preview, or a painted Nashor's is hidden
                              or clipped
        PLAN_NO_NASHOR (3)    no reply ranks Nashor's in its shown 7 and no row
                              paints it (a DS question at this state, not a
                              render defect)
        NASHOR_DARK (3)       no row paints Nashor's though a reply ranks it
        NO_GAME (4)           LCU phase not exactly InProgress, empty
                              liveclient, or mode_key not sr / aram
        STALE_DOM (4)         DOM and state captures more than MAX_SKEW_S apart
        NOT_ONHIT_CHAMP (4)   the coach champion is not on the onhit roster
        FULL_BUILD (4)        the preview answered build_complete
        NASHOR_OWNED (4)      I already own Nashor's (re-sample before the buy)
        EMPTY_ROWS (4)        all three rows empty (DS down or not landed)

RENDER_MATCH never ticks G4-17: render == compute is the SUBSTITUTION half, and a
headless dashboard page is not the Electron overlay widget (``w-build``, its own
width). Only the operator's overlay read of the Nashor's icon answers the row.
Prints champion names and item ids only, never a player name, game id or player id.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

TOOL = "gated_g417_onhit_render"
PANE_ID = "am-build-body"
NASHOR_ID = "3115"
NASHOR_KEY = "nashorstooth"
SLOT_CAP = 7
MAX_SKEW_S = 5.0
LIVE_MODES = ("sr", "aram")
ROWS = ("bm-live", "bm-meta", "bm-ult")
EXIT = {"RENDER_MATCH": 0, "ROSTER_BAD": 3, "PANE_ABSENT": 3, "PLAN_ERROR": 3,
        "SCORER_DRIFT": 3, "RENDER_MISMATCH": 3, "PLAN_NO_NASHOR": 3,
        "NASHOR_DARK": 3}

DOM_SNIPPET = (
    "(() => { const b = document.getElementById('" + PANE_ID + "');"
    " const ts = Date.now() / 1000;"
    " if (!b) return {ts: ts, present: false};"
    " const vis = (e) => { if (!e) return false;"
    " const r = e.getBoundingClientRect();"
    " return getComputedStyle(e).display !== 'none' && r.width > 0"
    " && r.height > 0 && e.offsetParent !== null; };"
    " const out = (a, c) => !!c && (a.right > c.right + 1 || a.left < c.left - 1);"
    " const pr = b.getBoundingClientRect();"
    " const rows = Array.from(b.querySelectorAll('.bm-module > .bm-row'))"
    ".filter((r) => !r.classList.contains('bm-shaper')).map((r) => {"
    " const s = r.querySelector('.bm-strip');"
    " const sr = s ? s.getBoundingClientRect() : null;"
    " const items = s ? Array.from(s.children).map((w) => {"
    " const img = w.querySelector('img');"
    " const src = img ? (img.getAttribute('src') || '') : '';"
    " const m = src.match(/\\/item\\/(\\d+)\\.png/);"
    " const tile = w.firstElementChild;"
    " const t = img ? (img.alt || '') : ((tile && tile.title) || w.title || '');"
    " const wr = w.getBoundingClientRect();"
    " return {id: m ? m[1] : '', name: t.split(' (+')[0],"
    " owned: w.classList.contains('bm-owned'), visible: vis(w),"
    " clipped: out(wr, sr) || out(wr, pr)}; }) : [];"
    " const v = ['bm-live', 'bm-meta', 'bm-ult'].find((c) => r.classList.contains(c));"
    " const lab = r.querySelector('.bm-row-label');"
    " return {variant: v || '', label: lab ? lab.textContent.trim() : '',"
    " visible: vis(r), items: items}; });"
    " return {ts: ts, present: true, rows: rows}; })()"
)


def _key(name: Any) -> str:
    """Name-form-blind compare key ("Kog'Maw" == "KogMaw" == "kogmaw")."""
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _coach(state: dict) -> dict:
    """``(st.coach || st)`` (main.js coachPayload)."""
    coach = state.get("coach")
    return coach if isinstance(coach, dict) else state


def _me_row(lc: dict) -> Optional[dict]:
    ap = lc.get("activePlayer") if isinstance(lc.get("activePlayer"), dict) else {}
    me = str(ap.get("summonerName") or ap.get("riotIdGameName") or "")
    if not me:
        return None
    for pl in lc.get("allPlayers") or []:
        if not isinstance(pl, dict):
            continue
        rid = str(pl.get("riotIdGameName") or pl.get("summonerName") or "")
        if rid == me or me.startswith(rid + "#") or rid == me.split("#", 1)[0]:
            return pl
    return None


def owned_ids(lc: dict) -> list:
    """Port of active_match.js _amOwnedItemIds (live branch)."""
    raw = lc.get("owned_item_ids")
    ids = [s for s in (str("" if i is None else i).strip()
                       for i in (raw if isinstance(raw, list) else [])) if s]
    if ids:
        return ids
    row = _me_row(lc) or {}
    for it in row.get("items") if isinstance(row.get("items"), list) else []:
        if not isinstance(it, dict):
            continue
        if isinstance(it.get("slot"), int) and it["slot"] >= 6:
            continue
        iid = it.get("itemID") or it.get("itemId") or 0
        if iid:
            ids.append(str(iid))
    return ids


def client_bodies(state: dict) -> dict:
    """The three bodies _renderAmBuildBody's fetchers post for this state."""
    lc = state.get("liveclient") if isinstance(state.get("liveclient"), dict) else {}
    p = _coach(state)
    champion = str(p.get("champion") or "")
    mode = str(state.get("mode") or state.get("mode_key") or "").upper() or "SR"
    try:
        level = int(float(p.get("level") or 0)) or 1
    except (TypeError, ValueError, OverflowError):
        level = 1
    items = owned_ids(lc)
    return {
        "ds_preview": {"champion": champion, "mode": mode, "level": level,
                       "items": items},
        "build_order": {"champion": champion, "mode": mode, "level": level,
                        "items": items, "archetype": ""},
        "ultimate": {"champion": champion, "mode": mode, "level": 18,
                     "items": [], "archetype": ""},
    }


def _rid(r: Any) -> str:
    if not isinstance(r, dict):
        return ""
    # _bmFamilyDedupe's key order: item_id first, then id.
    v = r.get("item_id") if r.get("item_id") is not None else r.get("id")
    return str(v or "")


def expected_live(preview: dict, order: Optional[dict],
                  ultimate: Optional[dict]) -> list:
    """The Daemon Slayer row's ids before overrides / owned sort: family dedupe
    (_bmFamilyDedupe) then the 7 cap (_bmComposeRows)."""
    ranked = [r for r in preview.get("ranked") or [] if isinstance(r, dict)]
    fam: dict = {}
    for reply in (order, ultimate):
        for r in (reply or {}).get("order") or []:
            if isinstance(r, dict) and _rid(r) and (r.get("locked_family") or r.get("family")):
                fam[_rid(r)] = r.get("locked_family") or r.get("family")
    for r in ranked:
        if _rid(r) and r.get("family"):
            fam[_rid(r)] = r["family"]
    seen, out = set(), []
    for r in ranked:
        f = fam.get(_rid(r)) if fam else None
        if f:
            if f in seen:
                continue
            seen.add(f)
        out.append(_rid(r))
    return out[:SLOT_CAP]


def _expected_order(reply: Optional[dict]) -> Optional[list]:
    if reply is None:
        return None
    return [_rid(r) for r in reply.get("order") or [] if isinstance(r, dict)][:SLOT_CAP]


def _is_nashor(item: dict) -> bool:
    return str(item.get("id") or "") == NASHOR_ID or _key(item.get("name")) == NASHOR_KEY


def onhit_roster() -> dict:
    from core.ds_onhit_ap_roster import load_onhit_ap_roster
    return dict(load_onhit_ap_roster())


def canonical(name: str) -> str:
    from core.archetype_picks import canonical_champion_id
    return canonical_champion_id(name) or name


def grade(state: dict, dom: dict, state_ts: float, preview: dict,
          order: Optional[dict] = None, ultimate: Optional[dict] = None,
          roster: Optional[dict] = None) -> dict:
    lc = state.get("liveclient") if isinstance(state.get("liveclient"), dict) else {}
    lcu = state.get("lcu") if isinstance(state.get("lcu"), dict) else {}
    ctx: dict = {"tool": TOOL, "mode_key": state.get("mode_key"),
                 "lcu_phase": lcu.get("phase"), "game_time_s": lc.get("game_time_s"),
                 "state_ts": state_ts, "dom_ts": dom.get("ts")}

    def out(verdict: str, **kw) -> dict:
        return {"verdict": verdict, **ctx, **kw}

    if lcu.get("phase") != "InProgress" or not lc \
            or str(state.get("mode_key") or "") not in LIVE_MODES:
        return out("NO_GAME")
    if not _finite(dom.get("ts")) or not _finite(state_ts) \
            or abs(float(dom["ts"]) - float(state_ts)) > MAX_SKEW_S:
        return out("STALE_DOM")
    bodies = client_bodies(state)
    champion = bodies["ds_preview"]["champion"]
    row = _me_row(lc)
    ctx.update(posted_champion=champion,
               my_champion=str((row or {}).get("championName") or ""))
    if not champion:
        return out("ROSTER_BAD", problems=["no coach champion"])
    if row is not None and _key(row.get("championName")) != _key(champion):
        return out("ROSTER_BAD", problems=["coach champion != my roster row champion"])
    roster = onhit_roster() if roster is None else roster
    canon = canonical(champion)
    ctx.update(canonical=canon, coherence=roster.get(canon))
    if canon not in roster:
        return out("NOT_ONHIT_CHAMP")
    if not dom.get("present"):
        return out("PANE_ABSENT")
    replies = {"ds_preview": preview, "build_order": order, "ultimate": ultimate}
    bad = [k for k, v in replies.items() if v is not None and not v.get("ok")]
    if bad:
        return out("PLAN_ERROR", problems=[f"{k} reply ok:false" for k in bad])
    if preview.get("reason") == "build_complete":
        return out("FULL_BUILD")
    drift = {k: v.get("scorer") for k, v in replies.items()
             if v is not None and v.get("scorer") != "onhit"}
    ctx["scorers"] = {k: v.get("scorer") for k, v in replies.items() if v is not None}
    if drift:
        return out("SCORER_DRIFT", problems=[f"{k} scorer {s!r} != 'onhit'"
                                             for k, s in drift.items()])
    painted = {v: [] for v in ROWS}
    for r in dom.get("rows") or []:
        if isinstance(r, dict) and r.get("variant") in painted:
            painted[r["variant"]] = [i for i in r.get("items") or [] if isinstance(i, dict)]
    ctx["painted"] = {v: [str(i.get("id") or i.get("name") or "") for i in items]
                      for v, items in painted.items()}
    if not any(painted.values()):
        return out("EMPTY_ROWS", problems=["all three build rows empty: no evidence"])
    expect = {"bm-live": expected_live(preview, order, ultimate),
              "bm-meta": _expected_order(order),
              "bm-ult": _expected_order(ultimate)}
    ctx["expected"] = {k: v for k, v in expect.items() if v is not None}
    want = {k: (v is not None and NASHOR_ID in v) for k, v in expect.items()}
    got = {k: [i for i in items if _is_nashor(i)] for k, items in painted.items()}
    rows_with = [k for k in ROWS if got[k]]
    ctx["rows_with_nashor"] = rows_with
    advisory = [f"{k}: reply {'ranks' if want[k] else 'omits'} Nashor's, row "
                f"{'paints' if got[k] else 'omits'} it (incumbent hysteresis)"
                for k in ("bm-meta", "bm-ult")
                if expect[k] is not None and want[k] != bool(got[k])]
    ctx["advisory"] = advisory
    if not rows_with:
        if NASHOR_ID in bodies["ds_preview"]["items"]:
            return out("NASHOR_OWNED")
        if not any(want.values()):
            return out("PLAN_NO_NASHOR")
        return out("NASHOR_DARK")
    probs = []
    if want["bm-live"] != bool(got["bm-live"]):
        probs.append("Daemon Slayer row: preview "
                     f"{'ranks' if want['bm-live'] else 'omits'} Nashor's in the shown "
                     f"{SLOT_CAP}, row {'paints' if got['bm-live'] else 'omits'} it")
    for k in rows_with:
        for i in got[k]:
            if not i.get("visible") or i.get("clipped"):
                probs.append(f"{k}: Nashor's painted but hidden or clipped")
    if probs:
        return out("RENDER_MISMATCH", problems=probs)
    return out("RENDER_MATCH", operator_eyeball_owed=True)


def _load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{Path(path).name}: not a JSON object")
    return data


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=TOOL, description=__doc__.split("\n", 1)[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snippet")
    b = sub.add_parser("bodies")
    b.add_argument("--state", required=True)
    g = sub.add_parser("grade")
    g.add_argument("--state", required=True)
    g.add_argument("--dom", required=True)
    g.add_argument("--preview", required=True)
    g.add_argument("--order")
    g.add_argument("--ultimate")
    g.add_argument("--state-ts", type=float)
    g.add_argument("--json", action="store_true")
    return p


def run(args: argparse.Namespace) -> int:
    if args.cmd == "snippet":
        print(DOM_SNIPPET)
        return 0
    if args.cmd == "bodies":
        print(json.dumps(client_bodies(_load(args.state))))
        return 0
    state, dom, preview = _load(args.state), _load(args.dom), _load(args.preview)
    order = _load(args.order) if args.order else None
    ult = _load(args.ultimate) if args.ultimate else None
    ts = args.state_ts if args.state_ts is not None else Path(args.state).stat().st_mtime
    result = grade(state, dom, ts, preview, order, ult)
    print(json.dumps(result, indent=2 if args.json else None))
    return EXIT.get(result["verdict"], 4)


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
