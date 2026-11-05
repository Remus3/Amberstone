"""gated_g103_cc_pressure.py - capture and grade the G1-03 champ-select CC chip check.

G1-03 is a RENDER question on the real dashboard: in a DRAFT champ select
(q400 / q420) once at least one ally and one enemy champion are committed, the
TEAM ANALYSIS cluster shows the CC-conditional pressure chip
``#csv-sugg-cc-conditional-pressure`` with a tier and two chain values
(``web/js/panels/cc_conditional_pressure.js`` ``renderCcConditionalPressure``,
gated by ``web/js/panels/champ_select.js`` ``_csvRenderCcConditionalPressure``).

Two subcommands, both READ-ONLY (no network call, no write, no tick):

``snippet``
    Prints an async browser expression to run in the dashboard tab. It reads
    ``/api/state`` from the same origin (keeping only the LCU phase, queue id
    and the committed champion ids - never a puuid or a player name), the
    champion slugs those ids map to through ``/data/champions_index.json`` (the
    file the page's own ``resolveChampNames`` reads), the champ-select view, the TEAM ANALYSIS drawer, the chip (hidden flag, tier attribute,
    tier label, both rows, verdict line, on-screen box), the page age, and the
    ``/api/cc-conditional-pressure`` URL the page itself last fetched (from
    resource timing), re-fetched once so the rendered numbers can be tied to
    the route body.

``grade --evidence E``
    Grades that bundle. PASS needs ALL of: the :8888 origin with ui_mock off;
    LCU phase ChampSelect; one ally and one enemy champion id above 0; the
    champ-select view shown; the chip not hidden, its tier in good / warn /
    bad with the matching label, both rows reading ``<n>.<n>s``, a verdict
    line; the chip ON SCREEN (a rendered, non-empty box); and the page's own
    last route URL tied to THIS roster by names and mode, with the rendered
    tier and seconds matching its body (any tie missing or off: INCONCLUSIVE).

TRAPS the grader encodes:
- ``web/index.html`` ships the chip with ``data-cc-cond-tier="warn"``, so a
  non-empty tier attribute alone proves nothing; the label and rows must be
  there too.
- The TEAM ANALYSIS drawer ``#csv-ta-body`` is collapsed by default
  (sessionStorage ``csv-ta-open``). A populated chip inside a collapsed drawer
  is not on screen: COLLAPSED, INCONCLUSIVE - open it and capture again.
- A ``hidden`` attribute is not the visibility truth: measured 2026-10-30 in
  headless Chromium, the SHOWN champ-select view keeps ``[hidden]`` while its
  computed display is block. View and chip are graded on rendered boxes
  (``getClientRects``), never on the attribute.
- The renderer skips a repaint when the payload signature is unchanged, but
  the gate hides the chip directly (their_team empty, champion index not
  loaded) without clearing that signature, so a chip hidden once can stay
  hidden for a later identical payload. A hidden chip is graded only on a
  page reloaded in this lobby and captured 10 to 90 s after the reload
  (``page_age_s``); outside that window it is INCONCLUSIVE.
- Blind select (ARAM / Mayhem) shows no enemy picks, so the chip stays hidden
  by design: INCONCLUSIVE (BLIND), never FAIL.

SUBSTITUTION. A GET of ``/api/cc-conditional-pressure`` is the COMPUTE half
only; ``tests/test_gated_g103_cc_pressure.py`` reaches PASS from hand-built
bundles. A PASS counts only for a bundle read in the real dashboard tab.

Exit codes: 0 = PASS; 1 = FAIL (a definite contradiction on proven
evidence); 3 = INCONCLUSIVE (not evidence, not applicable, or a needed check
could not be made); 2 = unreadable input or a usage error.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TIER_LABELS = {"good": "FAVORABLE", "warn": "EVEN", "bad": "AT RISK"}
ENEMY_ROW_LABEL = "Enemy can chain on one target"
ALLY_ROW_LABEL = "You can chain on one target"
SECONDS_RE = re.compile(r"^[0-9]+\.[0-9]s$")
SETTLE_S = 10.0           # a hidden chip is not graded sooner after a reload
FRESH_PAGE_S = 90.0       # nor later (stale signature, resource-timing buffer)
VALUE_TOL = 0.05 + 1e-9   # toFixed(1) vs a Python float: half-way ties differ

SNIPPET = r"""async () => {
  const $ = (id) => document.getElementById(id);
  const txt = (el) => (el ? el.textContent : null);
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { w: r.width, h: r.height,
             visible: el.getClientRects().length > 0
               && getComputedStyle(el).visibility !== "hidden" };
  };
  const ids = (team) => (Array.isArray(team) ? team : [])
    .map((p) => (p && (p.championId | 0)) || 0).filter((x) => x > 0);
  let lcu = null, state_error = null;
  try {
    const r = await fetch("/api/state", { cache: "no-store" });
    if (r.ok) {
      const s = await r.json();
      const l = (s && s.lcu) || {};
      const cs = l.champ_select || {};
      lcu = { phase: l.phase === undefined ? null : l.phase,
              queue_id: cs.queue_id === undefined ? null : cs.queue_id,
              ally_ids: ids(cs.my_team), enemy_ids: ids(cs.their_team),
              has_champ_select: !!l.champ_select };
    } else { state_error = "HTTP " + r.status; }
  } catch (e) { state_error = String((e && e.name) || e); }
  // the slugs the page's resolveChampNames builds (CHAMPS.byId from this file),
  // so the grader can tie the page's last route fetch to THIS roster
  let names = null;
  if (lcu) {
    try {
      const r = await fetch("/data/champions_index.json", { cache: "no-store" });
      if (r.ok) {
        const byId = ((await r.json()) || {}).byId || {};
        const res = (arr) => arr.map((id) => byId[String(id)]).filter(Boolean).map(String);
        names = { ally: res(lcu.ally_ids), enemy: res(lcu.enemy_ids) };
      }
    } catch (_) {}
  }
  const chip = $("csv-sugg-cc-conditional-pressure");
  const pick = (el, sel) => (el ? el.querySelector(sel) : null);
  const rows = chip ? Array.from(chip.querySelectorAll(".cc-conditional-pressure-row"))
    .map((r) => ({ label: txt(pick(r, ".cc-conditional-pressure-row-label")),
                   value: txt(pick(r, ".cc-conditional-pressure-row-value")) })) : [];
  let route_url = null, route = null, route_status = null;
  try {
    const ents = performance.getEntriesByType("resource")
      .filter((e) => e.name.indexOf("/api/cc-conditional-pressure?") >= 0);
    if (ents.length) {
      const last = ents[ents.length - 1];
      route_url = last.name;
      if (typeof last.responseStatus === "number") route_status = last.responseStatus;
    }
  } catch (_) {}
  if (route_url) {
    try {
      const r = await fetch(route_url, { cache: "no-store" });
      route = r.ok ? await r.json() : null;
    } catch (_) {}
  }
  const view = $("view-champ-select"), ta = $("csv-team-analysis"), body = $("csv-ta-body");
  return {
    tool: "gated_g103_cc_pressure",
    captured_at: new Date().toISOString(),
    href: location.href,
    ui_mock: (document.body && document.body.dataset.uiMock) || "",
    page_age_s: performance.now() / 1000,
    visibility: document.visibilityState,
    state_error, lcu, names,
    view_hidden: view ? view.hidden : null,
    view_box: box(view),
    ta_hidden: ta ? ta.hidden : null,
    ta_body_hidden: body ? body.hidden : null,
    chip_present: !!chip,
    chip_hidden: chip ? chip.hidden : null,
    chip_tier_attr: chip ? (chip.dataset.ccCondTier || "") : null,
    chip_tier_label: txt(pick(chip, ".cc-conditional-pressure-tier")),
    chip_rows: rows,
    chip_verdict: txt(pick(chip, ".cc-conditional-pressure-verdict")),
    chip_box: box(chip),
    route_url, route_status, route,
  };
}"""


class InputError(Exception):
    """Unreadable or unusable input (exit 2)."""


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _id_list(v) -> list[int] | None:
    if not isinstance(v, list):
        return None
    out = []
    for x in v:
        if not isinstance(x, int) or isinstance(x, bool):
            return None
        if x > 0:
            out.append(x)
    return out


def route_names(url) -> dict | None:
    """ally / enemy name counts and mode from the page's own route URL, or None."""
    if not isinstance(url, str) or "/api/cc-conditional-pressure?" not in url:
        return None
    try:
        qs = parse_qs(urlparse(url).query)
    except ValueError:
        return None

    def names(key):
        raw = (qs.get(key) or [""])[0]
        return [n for n in raw.split(",") if n.strip()]
    return {"ally": sorted(names("ally")), "enemy": sorted(names("enemy")),
            "mode": (qs.get("mode") or [""])[0].upper()}


def mode_for_queue(queue_id) -> str:
    """The page's queue -> route mode map (champ_select.js gate)."""
    q = queue_id if _is_num(queue_id) else 0
    if q == 2400:
        return "KIWI"
    if q in (1700, 1710, 1750):
        return "ARENA"
    if q in (420, 400, 430, 700):
        return "SR"
    return "ARAM"


def roster_tie(rn, names, queue_id) -> bool | None:
    """True when the page's last route URL is for THIS roster and mode; None
    when it cannot be decided (no URL or no resolved names)."""
    if rn is None or not isinstance(names, dict):
        return None
    ally, enemy = names.get("ally"), names.get("enemy")
    if not (isinstance(ally, list) and isinstance(enemy, list) and ally and enemy
            and all(isinstance(n, str) for n in ally + enemy)):
        return None
    return (rn["ally"] == sorted(ally) and rn["enemy"] == sorted(enemy)
            and rn["mode"] == mode_for_queue(queue_id))


def expected_from_route(route) -> dict | None:
    """Tier and chain seconds the renderer would draw from a route body."""
    if not isinstance(route, dict) or route.get("ok") is not True:
        return None

    def side(total_key, avg_key):
        v = route.get(total_key)
        if v is not None:
            return float(v) if _is_num(v) else None
        v = route.get(avg_key)
        return float(v) if _is_num(v) else 0.0
    enemy = side("enemy_total_cc_seconds", "enemy_conditional_cc_s")
    ally = side("ally_total_cc_seconds", "ally_conditional_cc_s")
    if enemy is None or ally is None:
        return None
    tier = route.get("tier") or "warn"
    return {"tier": tier, "enemy_s": enemy, "ally_s": ally}


def _seconds(text) -> float | None:
    if not isinstance(text, str) or not SECONDS_RE.match(text.strip()):
        return None
    return float(text.strip()[:-1])


def grade(ev: dict) -> dict:
    if not isinstance(ev, dict):
        raise InputError("evidence must be a JSON object")
    checks: dict = {}
    provenance: list[str] = []
    fails: list[str] = []
    gaps: list[str] = []
    notes: list[str] = []
    state = "UNGRADED"

    href = str(ev.get("href") or "")
    try:
        port = urlparse(href).port
    except ValueError:
        port = None
    checks["real_origin"] = href.startswith("https://") and port == 8888
    if not checks["real_origin"]:
        provenance.append("evidence href is not the https :8888 dashboard")
    mock = ev.get("ui_mock")
    checks["ui_mock"] = str(mock if mock is not None else "")
    if mock not in (None, "", "0", 0, False):
        provenance.append("ui_mock is on: a fixture champ select, not the live LCU")

    lcu = ev.get("lcu")
    if not isinstance(lcu, dict):
        provenance.append("no /api/state read in this capture"
                          + (f" ({ev.get('state_error')})" if ev.get("state_error") else ""))
        lcu = {}
    phase = lcu.get("phase")
    checks["phase"] = phase if isinstance(phase, str) else None
    ally = _id_list(lcu.get("ally_ids"))
    enemy = _id_list(lcu.get("enemy_ids"))
    checks["ally_committed"] = len(ally) if ally is not None else None
    checks["enemy_committed"] = len(enemy) if enemy is not None else None
    checks["queue_id"] = lcu.get("queue_id") if _is_num(lcu.get("queue_id")) else None

    def result(verdict):
        return {"verdict": verdict, "state": state, "checks": checks,
                "provenance": provenance, "fails": fails, "gaps": gaps,
                "notes": notes, "captured_at": ev.get("captured_at")}

    if provenance:
        return result("INCONCLUSIVE")
    if phase != "ChampSelect":
        state = "NOT_IN_CHAMP_SELECT"
        gaps.append(f"LCU phase is {phase!r}, not ChampSelect")
        return result("INCONCLUSIVE")
    if ally is None or enemy is None:
        gaps.append("committed champion ids not captured")
        return result("INCONCLUSIVE")
    if not enemy:
        state = "BLIND"
        gaps.append("no enemy champion committed: blind select (ARAM / Mayhem) or no "
                    "enemy pick yet; the chip hides by design")
        return result("INCONCLUSIVE")
    if not ally:
        state = "NO_ALLY"
        gaps.append("no ally champion committed yet")
        return result("INCONCLUSIVE")
    # the view's hidden ATTRIBUTE is not the truth: measured 2026-10-30, the shown
    # champ-select view keeps [hidden] while its computed display is block
    vb = ev.get("view_box")
    checks["view_shown"] = (vb.get("visible") is True and _is_num(vb.get("w"))
                            and _is_num(vb.get("h")) and vb["w"] > 0 and vb["h"] > 0
                            ) if isinstance(vb, dict) else None
    if checks["view_shown"] is not True:
        state = "VIEW_NOT_SHOWN"
        gaps.append("champ-select view not rendered (another view, or not captured)")
        return result("INCONCLUSIVE")
    present = ev.get("chip_present")
    if present is False:
        state = "CHIP_MISSING"
        fails.append("#csv-sugg-cc-conditional-pressure is not in the DOM")
        return result("FAIL")
    # the snippet always returns these keys (null when the element is absent); a
    # MISSING key is a capture that never ran, never proof of a defect
    missing = [k for k in ("chip_hidden", "chip_tier_attr", "chip_tier_label",
                           "chip_rows", "chip_verdict", "chip_box") if k not in ev]
    if present is not True or missing:
        gaps.append("chip fields not captured: "
                    + ", ".join((["chip_present"] if present is not True else []) + missing))
        return result("INCONCLUSIVE")

    # the rendered box is the truth (a hidden attribute can be overridden by CSS)
    b = ev.get("chip_box")
    box_ok = (isinstance(b, dict) and isinstance(b.get("visible"), bool)
              and _is_num(b.get("w")) and _is_num(b.get("h")))
    on_screen = box_ok and b["visible"] is True and b["w"] > 0 and b["h"] > 0
    checks["on_screen"] = on_screen if box_ok else None
    if not box_ok:
        gaps.append("chip box not captured")
        return result("INCONCLUSIVE")

    rn = route_names(ev.get("route_url"))
    checks["route_url_seen"] = rn is not None
    checks["roster_tie"] = roster_tie(rn, ev.get("names"), lcu.get("queue_id"))
    age = ev.get("page_age_s")
    checks["page_age_s"] = age if _is_num(age) else None

    hidden = ev.get("chip_hidden")
    if hidden is True and on_screen:
        # contradicts the attribute: the box wins, grade it as shown
        notes.append("chip carries [hidden] but has a rendered box: graded as shown")
        hidden = False
    if hidden is True:
        state = "HIDDEN"
        if not _is_num(age) or not (SETTLE_S <= age <= FRESH_PAGE_S):
            gaps.append(f"hidden chip on a page aged {checks['page_age_s']} s: reload the "
                        f"dashboard in this lobby and capture {SETTLE_S:.0f} to "
                        f"{FRESH_PAGE_S:.0f} s later (stale-signature trap)")
            return result("INCONCLUSIVE")
        if rn is None:
            # resource timing lists a fetch only once its response has ended, so no
            # URL cannot rule out a request still in flight: never a FAIL
            gaps.append("no route fetch seen on this page: capture again; if a second "
                        "capture 60 s later still shows none, inspect the page by hand")
            return result("INCONCLUSIVE")
        if checks["roster_tie"] is not True:
            # hovers count as committed ids (championPickIntent), so a changed
            # hover starts a fetch that resource timing does not list yet
            gaps.append("the page's last route fetch is not tied to this roster (other "
                        "picks / hovers, or names not resolved): wait for the picks to "
                        "settle and capture again")
            return result("INCONCLUSIVE")
        if ev.get("visibility") != "visible":
            # the post-fetch repaint runs on requestAnimationFrame, paused in a
            # hidden tab
            gaps.append("the dashboard tab was not visible at capture: bring it to the "
                        "front and capture again")
            return result("INCONCLUSIVE")
        status = ev.get("route_status")
        if status is not None and not (_is_num(status) and 200 <= status < 300):
            gaps.append(f"the page's own route fetch got HTTP {status}: a compute-side "
                        "outage, not a render verdict")
            return result("INCONCLUSIVE")
        route = ev.get("route")
        checks["route_ok"] = route.get("ok") is True if isinstance(route, dict) else None
        if checks["route_ok"] is not True:
            # the renderer hides on a non-ok payload BY DESIGN: that is a compute
            # question for the route, not a render failure of this row
            gaps.append("route body for this roster is not ok (or the re-fetch got no "
                        "body): the chip hides by design; file it against the route")
            return result("INCONCLUSIVE")
        fails.append("chip hidden on a freshly loaded, visible page with both rosters "
                     "committed and an ok route body for this roster")
        return result("FAIL")
    if hidden is not False:
        gaps.append("chip hidden flag not captured")
        return result("INCONCLUSIVE")

    # the chip claims to be shown: its content must be the renderer's, not the
    # static index.html default
    tier = ev.get("chip_tier_attr")
    checks["tier"] = tier if isinstance(tier, str) else None
    label = ev.get("chip_tier_label")
    label = label.strip() if isinstance(label, str) else None
    if tier not in TIER_LABELS:
        fails.append(f"tier attribute {tier!r} is not good / warn / bad")
    elif label != TIER_LABELS[tier]:
        fails.append(f"tier label {label!r} does not match tier {tier!r}")
    rows = ev.get("chip_rows")
    by_label: dict = {}
    if isinstance(rows, list):
        for r in rows:
            if isinstance(r, dict) and isinstance(r.get("label"), str):
                by_label[r["label"].strip()] = r.get("value")
    enemy_s = _seconds(by_label.get(ENEMY_ROW_LABEL))
    ally_s = _seconds(by_label.get(ALLY_ROW_LABEL))
    checks["enemy_s"], checks["ally_s"] = enemy_s, ally_s
    if enemy_s is None:
        fails.append("enemy chain row missing or not '<n>.<n>s'")
    if ally_s is None:
        fails.append("ally chain row missing or not '<n>.<n>s'")
    verdict_line = ev.get("chip_verdict")
    if not (isinstance(verdict_line, str) and verdict_line.strip()):
        fails.append("verdict line missing")
    if fails:
        state = "MALFORMED"
        return result("FAIL")

    # populated: is it on screen? The drawer attribute only names WHY it is not.
    state = "POPULATED"
    if not on_screen:
        if ev.get("ta_body_hidden") is True:
            state = "COLLAPSED"
            gaps.append("TEAM ANALYSIS drawer collapsed: click its head to open it and "
                        "capture again")
            return result("INCONCLUSIVE")
        if ev.get("ta_body_hidden") is not False:
            gaps.append("drawer state not captured")
            return result("INCONCLUSIVE")
        fails.append("chip populated but has no on-screen box"
                     + (" (TEAM ANALYSIS cluster hidden)" if ev.get("ta_hidden") is True
                        else ""))
        return result("FAIL")
    state = "RENDERED"

    # PASS needs the chip tied to THIS roster: the page's last route URL by name and
    # mode, and the rendered numbers to that URL's body (else a page still showing
    # an earlier roster or lobby could pass)
    exp = expected_from_route(ev.get("route"))
    if checks["roster_tie"] is not True:
        gaps.append("roster tie not made (no route URL, names not resolved, or the "
                    "page's last fetch is for other picks): capture again")
        return result("INCONCLUSIVE")
    if exp is None:
        checks["route_tie"] = None
        gaps.append("route tie not made (no ok route body): capture again")
        return result("INCONCLUSIVE")
    tie = (exp["tier"] == tier and abs(exp["enemy_s"] - enemy_s) <= VALUE_TOL
           and abs(exp["ally_s"] - ally_s) <= VALUE_TOL)
    checks["route_tie"] = tie
    if not tie:
        gaps.append("rendered tier / seconds differ from the route body: render lag "
                    "or a roster change; capture again")
        return result("INCONCLUSIVE")
    return result("PASS")


def _load_json(path: str):
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise InputError(f"{p.name}: {type(exc).__name__}") from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="read-only G1-03 CC chip capture / grade")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snippet", help="print the browser expression that captures the evidence")
    gp = sub.add_parser("grade", help="grade an evidence bundle")
    gp.add_argument("--evidence", required=True)
    gp.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "snippet":
        print(SNIPPET)
        return 0
    try:
        ev = _load_json(args.evidence)
        try:
            res = grade(ev)
        except (KeyError, TypeError, ValueError, IndexError, AttributeError,
                ArithmeticError, RecursionError) as exc:
            raise InputError(f"evidence has the wrong shape: {type(exc).__name__}") from exc
    except InputError as exc:
        print(f"G1-03: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        c = res["checks"]
        print(f"G1-03 verdict {res['verdict']} ({res['state']}) phase {c.get('phase')} "
              f"queue {c.get('queue_id')} ally {c.get('ally_committed')} "
              f"enemy {c.get('enemy_committed')}")
        for line in res["provenance"]:
            print("  NOT EVIDENCE " + line)
        for line in res["fails"]:
            print("  FAIL " + line)
        for line in res["gaps"]:
            print("  GAP  " + line)
        for line in res["notes"]:
            print("  NOTE " + line)
    return {"PASS": 0, "FAIL": 1}.get(res["verdict"], 3)


if __name__ == "__main__":
    sys.exit(main())
