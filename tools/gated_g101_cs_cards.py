"""gated_g101_cs_cards.py - capture and grade the G1-01 locked-own-champ card check.

G1-01 (LIVE RESIDUAL) is a RENDER question on the real dashboard: in ONE champ
select with the operator's own champion LOCKED, the three surviving
own-champion cards are on screen and drawn from THIS champion's data:

- DS skill order  ``#csv-sugg-ds-skill-order`` (``web/js/panels/ds_skill_order.js``
  ``renderDsSkillOrder``; GET ``/api/ds-skill-order``, mode always SR);
- personal best build  ``#csv-personal-build`` (``web/js/panels/personal_build.js``
  ``renderPersonalBuild``; GET ``/api/personal-build``, mode from the queue);
- the build-order B-card, which is NO LONGER a card: B6 + B7 (QA 2026-07-03
  slice A) merged it into the build chooser as the ORDERED SEQUENCE strip
  ``#csv-builds-seq`` inside ``.csv-builds`` (``web/js/panels/champ_select.js``
  ``_csvBuildSeqStripHtml``; POST ``/api/build-order``).

Two subcommands, both READ-ONLY (no network call, no write, no tick):

``snippet``
    Prints an async browser expression to run in the dashboard tab. It reads
    ``/api/state`` from the same origin (keeping only the LCU phase, queue id,
    is_aram and the operator's own champion id / lock flags - never a puuid,
    a player name or another player's pick), the slug for that id through
    ``/data/champions_index.json`` (the file the page's ``CHAMPS`` index is
    built from), the three mounts (hidden flag, rendered box, text), the host
    card box, the page age and tab visibility, and THE PAGE'S OWN cached
    payloads: it imports ``/js/panels/ds_skill_order.js`` and
    ``/js/panels/personal_build.js`` (the same module instances the page
    loaded, so only their getters run) and reads the cache entry for this
    champion. Resource timing gives how long ago each route answered.

``grade --evidence E``
    Grades the bundle per card, then overall: PASS iff all three cards PASS,
    FAIL iff any card FAILs, else INCONCLUSIVE.

TRAPS the grader encodes (measured in source 2026-10-30, before any game):
- ``my_champion`` is the LOCKED id OR the hover (``lcu/champ_select_shape.py``),
  and every card renders for a hover too. The row is about a LOCKED pick, so
  the capture needs ``my_completed`` true (and ``my_champion_locked`` equal to
  ``my_champion`` when the agent sends it): else NOT_LOCKED, INCONCLUSIVE.
- A ``hidden`` attribute is not the visibility truth (the shown champ-select
  view keeps ``[hidden]``, measured s144 c36): every card is graded on its
  rendered box.
- Both card renderers skip a repaint on an unchanged payload signature, while
  ``_csvRenderPersonalBuild`` / ``renderDsSkillOrderForChampSelect`` hide the
  card DIRECTLY when no champion is picked, without clearing that signature.
  REPRODUCED 2026-10-30 in headless Chromium through the page's own
  ``renderChampSelectView``: lock champion A, then a new select with no pick,
  then lock A again - both cards stay hidden with A's payload cached
  (RM-1162). So a card hidden while the PAGE'S OWN cache holds a non-empty
  payload for this champion is a real render failure: FAIL, provided the
  cache was read before the DOM and two animation frames plus 0.5 s passed in
  between (``dom_after_cache``; any scheduled re-render has run), or the
  page's own fetch answered 5 s or more before the capture - AND the build
  chooser already carries this champion's slug. The page renders from its
  pushed state (about every 2 s), not from the snippet's ``/api/state`` read,
  so right after a lock it can still be drawing the previous hover; a chooser
  for another pick is state lag: INCONCLUSIVE.
  (The ``_csvComputeSig`` render gate does NOT cause this: ``_csvScheduleRender``
  clears the section signature before every post-fetch re-render.)
- The strip's ``empty`` state ("no ordered build") is unreachable from the
  fetch path (``build_order.js`` caches only an ok, non-empty order), so a
  route that answers no order leaves ``computing...`` up for good. A strip
  still ``loading`` is INCONCLUSIVE, never FAIL: the page's build-order cache
  key needs the archetype, which the snippet cannot read.
- SR ONLY: ``renderChampSelectView`` calls ``_csvRenderSuggestions`` (which
  draws both cards) only when the mode is ``sr``; ARAM / Arena take
  ``_csvRenderSuggestionsNonSr``, which never touches them. A non-SR capture
  is NOT_SR, INCONCLUSIVE.
- Personal build hides BY DESIGN below its sample threshold (payload with no
  items): INCONCLUSIVE, not FAIL.

SUBSTITUTION. A GET of either route, or the POST, is the COMPUTE half only;
``tests/test_gated_g101_cs_cards.py`` reaches PASS from hand-built bundles
and from the real renderers' markup drawn under node. A PASS counts only for
a bundle read in the real dashboard tab.

Exit codes: 0 = PASS; 1 = FAIL (a definite contradiction on proven
evidence); 3 = INCONCLUSIVE; 2 = unreadable input or a usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SETTLE_S = 10.0         # no verdict on a page younger than this
LANDED_S = 5.0          # a hidden card is graded only this long after its fetch answered
SEQ_MAX_CHIPS = 7       # build_order.js BO_SLOTS
DSSO_TITLE = "Skill order"
PBW_TITLE = "Your best build"
SEQ_TAG = "ORDERED SEQUENCE"
MAX_RE = re.compile(r"^Max: [QWER]( > [QWER])*$")
ULT_RE = re.compile(r"^Ult: [0-9]+(/[0-9]+)*$")
CARDS = ("ds_skill_order", "personal_build", "build_seq")

# web/js/panels/personal_build.js _PBW_MODE_MAP (pinned by the tests); any other
# queue falls back to "sr", as pbwModeForQueue does.
PBW_MODE_MAP = {
    450: "aram", 920: "aram", 2400: "aram",
    1750: "arena", 1700: "arena", 1710: "arena",
    400: "sr", 420: "sr", 430: "sr", 440: "sr",
    830: "sr", 840: "sr", 850: "sr",
}

SNIPPET = r"""async () => {
  const $ = (id) => document.getElementById(id);
  const txt = (el) => (el ? el.textContent : null);
  const pick = (el, sel) => (el ? el.querySelector(sel) : null);
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { w: r.width, h: r.height,
             visible: el.getClientRects().length > 0
               && getComputedStyle(el).visibility !== "hidden",
             in_viewport: r.bottom > 0 && r.right > 0
               && r.top < innerHeight && r.left < innerWidth };
  };
  const now = performance.now();
  let lcu = null, state_error = null;
  try {
    const r = await fetch("/api/state", { cache: "no-store" });
    if (r.ok) {
      const s = await r.json();
      const l = (s && s.lcu) || {};
      const cs = l.champ_select || {};
      const num = (v) => (v === undefined || v === null ? null : (v | 0));
      lcu = { phase: l.phase === undefined ? null : l.phase,
              queue_id: num(cs.queue_id), is_aram: !!cs.is_aram,
              my_champion: num(cs.my_champion),
              my_champion_locked: num(cs.my_champion_locked),
              my_completed: cs.my_completed === undefined ? null : !!cs.my_completed,
              has_champ_select: !!l.champ_select };
    } else { state_error = "HTTP " + r.status; }
  } catch (e) { state_error = String((e && e.name) || e); }
  let slug = null;
  if (lcu && lcu.my_champion > 0) {
    try {
      const r = await fetch("/data/champions_index.json", { cache: "no-store" });
      if (r.ok) {
        const byId = ((await r.json()) || {}).byId || {};
        slug = byId[String(lcu.my_champion)] ? String(byId[String(lcu.my_champion)]) : null;
      }
    } catch (_) {}
  }
  const PBW_MODES = { 450: "aram", 920: "aram", 2400: "aram", 1750: "arena",
    1700: "arena", 1710: "arena" };
  const pbwMode = lcu ? (PBW_MODES[lcu.queue_id] || "sr") : null;
  // the PAGE'S OWN cache: same URL as the page's import, so the same module instance
  let dsso_payload = null, pbw_payload = null, cache_error = null;
  if (slug) {
    try {
      const m = await import("/js/panels/ds_skill_order.js");
      const p = m.getCachedDsSkillOrder(slug, "SR");
      dsso_payload = p ? { ok: p.ok === true, reason: p.reason || null,
        champion: p.champion == null ? null : String(p.champion),
        max_order: Array.isArray(p.max_order) ? p.max_order.map(String) : null,
        max_order_str: p.max_order_str == null ? null : String(p.max_order_str),
        ult_levels: Array.isArray(p.ult_levels) ? p.ult_levels.map((x) => x | 0) : null }
        : null;
      const b = await import("/js/panels/personal_build.js");
      const q = b.getCachedPersonalBuild(slug, pbwMode);
      pbw_payload = q ? { champion: q.champion == null ? null : String(q.champion),
        confidence: q.confidence || null,
        n_items: Array.isArray(q.items) ? q.items.length : 0 } : null;
    } catch (e) { cache_error = String((e && e.name) || e); }
  }
  const landed = (frag, test) => {
    try {
      const ents = performance.getEntriesByType("resource")
        .filter((e) => e.name.indexOf(frag) >= 0 && test(e.name));
      if (!ents.length) return null;
      const last = ents[ents.length - 1];
      return { since_s: last.responseEnd > 0 ? (now - last.responseEnd) / 1000 : null,
               status: typeof last.responseStatus === "number" ? last.responseStatus : null,
               count: ents.length };
    } catch (_) { return null; }
  };
  // let any re-render scheduled by a cache landing run before the DOM is read
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  await new Promise((r) => setTimeout(r, 500));
  const dom_after_cache = document.visibilityState === "visible";
  const qp = (u, k) => { try { return new URL(u).searchParams.get(k); } catch (_) { return null; } };
  const dsso = $("csv-sugg-ds-skill-order"), pbw = $("csv-personal-build");
  const builds = document.querySelector("#view-champ-select .csv-builds");
  const seq = $("csv-builds-seq");
  const view = $("view-champ-select");
  const host = dsso ? dsso.closest(".csv-card") : null;
  return {
    tool: "gated_g101_cs_cards",
    captured_at: new Date().toISOString(),
    href: location.href,
    ui_mock: (document.body && document.body.dataset.uiMock) || "",
    page_age_s: now / 1000,
    visibility: document.visibilityState,
    state_error, lcu, slug, pbw_mode: pbwMode, cache_error, dom_after_cache,
    view_box: box(view), host_box: box(host),
    dsso: { present: !!dsso, hidden: dsso ? dsso.hidden : null, box: box(dsso),
            title: txt(pick(dsso, ".dsso-head-title")), sub: txt(pick(dsso, ".dsso-head-sub")),
            max: txt(pick(dsso, ".dsso-max")), ult: txt(pick(dsso, ".dsso-ult")),
            payload: dsso_payload,
            fetch: slug ? landed("/api/ds-skill-order?", (u) => qp(u, "champion") === slug
                                 && qp(u, "mode") === "SR") : null },
    pbw: { present: !!pbw, hidden: pbw ? pbw.hidden : null, box: box(pbw),
           title: txt(pick(pbw, ".pbw-head-title")), sub: txt(pick(pbw, ".pbw-head-sub")),
           rows: pbw ? pbw.querySelectorAll(".pbw-row").length : null,
           payload: pbw_payload,
           fetch: slug ? landed("/api/personal-build?", (u) => qp(u, "champion") === slug
                                && qp(u, "mode") === pbwMode) : null },
    seq: { builds_present: !!builds,
           builds_champion: builds ? (builds.dataset.champion || "") : null,
           builds_mode: builds ? (builds.dataset.mode || "") : null,
           present: !!seq, state: seq ? (seq.dataset.boState || "") : null, box: box(seq),
           tag: txt(pick(seq, ".csv-boseq-tag")),
           chips: seq ? seq.querySelectorAll(".csv-boseq-chip").length : null,
           fetch: landed("/api/build-order", () => true) },
  };
}"""


class InputError(Exception):
    """Unreadable or unusable input (exit 2)."""


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _shown(b) -> bool | None:
    """True / False on a captured box, None when no box was captured."""
    if b is None:
        return None
    if not isinstance(b, dict):
        raise InputError("a box must be an object")
    w, h = b.get("w"), b.get("h")
    if not (_is_num(w) and _is_num(h)):
        return None
    return bool(b.get("visible")) and w > 0 and h > 0


def detect_mode(queue_id, is_aram) -> str:
    """champ_select.js _csvDetectMode: the strip's data-mode."""
    q = int(queue_id) if _is_num(queue_id) else 0
    if q in (1700, 1710, 1750):
        return "arena"
    if is_aram is True or q in (450, 920, 2400):
        return "aram"
    return "sr"


def _hidden_card(card: dict, name: str, has_data, settled: bool, drawn: bool,
                 notes: list) -> tuple[str, str]:
    """Grade a card with no rendered box. has_data: True / False / None. drawn: the
    page's last render was for THIS champion (the chooser carries its slug)."""
    if has_data is None:
        return "INCONCLUSIVE", f"{name}: hidden and the page holds no payload for this champion yet"
    if has_data is False:
        return "INCONCLUSIVE", f"{name}: hidden BY DESIGN (the page's payload has no content)"
    f = card.get("fetch")
    since = f.get("since_s") if isinstance(f, dict) else None
    status = f.get("status") if isinstance(f, dict) else None
    landed = _is_num(since) and since >= LANDED_S
    if not (landed or settled):
        return "INCONCLUSIVE", (f"{name}: hidden, but neither the page's fetch is seen "
                                f"{LANDED_S:.0f} s landed nor the DOM read after the cache read")
    if status is not None and (not _is_num(status) or not 200 <= status < 300):
        return "INCONCLUSIVE", f"{name}: hidden after a non-2xx page fetch"
    if not drawn:
        return "INCONCLUSIVE", (f"{name}: hidden, but the page has not yet drawn this champion "
                                "(the chooser is for another pick: state lag); capture again")
    notes.append(f"{name}: hidden while the page's own cache holds its payload - the "
                 "stale-signature hide (RM-1162) is the measured cause; F5 and capture "
                 "again, keep both bundles")
    return "FAIL", f"{name}: HIDDEN_WITH_DATA"


def grade_dsso(card: dict, settled: bool, drawn: bool, notes: list) -> tuple[str, str]:
    name = "ds_skill_order"
    if card.get("present") is False:
        return "FAIL", f"{name}: CARD_MISSING (#csv-sugg-ds-skill-order not in the DOM)"
    p = card.get("payload")
    if p is not None and not isinstance(p, dict):
        raise InputError("dsso.payload must be an object")
    has = None if p is None else bool(p.get("ok") is True and p.get("max_order"))
    shown = _shown(card.get("box"))
    if shown is None:
        return "INCONCLUSIVE", f"{name}: box not captured"
    if not shown:
        return _hidden_card(card, name, has, settled, drawn, notes)
    title, mx, ult = card.get("title"), card.get("max"), card.get("ult")
    if title != DSSO_TITLE or not isinstance(mx, str) or not MAX_RE.match(mx) \
            or not isinstance(ult, str) or not ULT_RE.match(ult):
        return "FAIL", f"{name}: MALFORMED (title / Max / Ult text not the renderer's shape)"
    if not has:
        return "INCONCLUSIVE", f"{name}: shown, but no ok page payload to tie it to"
    want_max = "Max: " + str(p.get("max_order_str") or " > ".join(p.get("max_order") or []))
    ults = p.get("ult_levels") if isinstance(p.get("ult_levels"), list) else []
    want_ult = "Ult: " + "/".join(str(x) for x in ults)
    if card.get("sub") != p.get("champion") or mx != want_max or ult != want_ult:
        return "INCONCLUSIVE", f"{name}: rendered text differs from the page's payload (render lag)"
    return "PASS", f"{name}: RENDERED and tied to the page's payload"


def grade_pbw(card: dict, settled: bool, drawn: bool, notes: list) -> tuple[str, str]:
    name = "personal_build"
    if card.get("present") is False:
        return "FAIL", f"{name}: CARD_MISSING (#csv-personal-build not in the DOM)"
    p = card.get("payload")
    if p is not None and not isinstance(p, dict):
        raise InputError("pbw.payload must be an object")
    n_items = p.get("n_items") if isinstance(p, dict) else None
    has = None if p is None else bool(_is_num(n_items) and n_items > 0)
    shown = _shown(card.get("box"))
    if shown is None:
        return "INCONCLUSIVE", f"{name}: box not captured"
    if not shown:
        if has is False:
            notes.append(f"{name}: confidence {p.get('confidence')!r} - below the personal "
                         "sample threshold for this champion and mode")
        return _hidden_card(card, name, has, settled, drawn, notes)
    title, sub, rows = card.get("title"), card.get("sub"), card.get("rows")
    if title != PBW_TITLE or not isinstance(sub, str) or ": items you win with" not in sub \
            or not _is_num(rows) or rows < 1:
        return "FAIL", f"{name}: MALFORMED (title / sub line / rows not the renderer's shape)"
    if not has:
        return "INCONCLUSIVE", f"{name}: shown, but no page payload with items to tie it to"
    if not sub.startswith(f"{p.get('champion')}: items you win with") or rows != n_items:
        return "INCONCLUSIVE", f"{name}: rendered champion / row count differs from the page's payload"
    return "PASS", f"{name}: RENDERED and tied to the page's payload ({rows} rows)"


def grade_seq(card: dict, slug, mode, page_age) -> tuple[str, str]:
    name = "build_seq"
    if card.get("builds_present") is False:
        return "FAIL", f"{name}: BUILDS_MISSING (.csv-builds not rendered for a locked champion)"
    if card.get("builds_champion") != slug or card.get("builds_mode") != mode:
        return "INCONCLUSIVE", f"{name}: the build chooser is for another champion or mode (render lag)"
    if card.get("present") is False:
        return "FAIL", f"{name}: STRIP_MISSING (#csv-builds-seq absent inside .csv-builds)"
    state = card.get("state")
    if state == "loading":
        return "INCONCLUSIVE", (f"{name}: still 'computing...' at page age {page_age:.0f} s "
                                "(the route may have answered no order; see RM-1163)")
    if state == "empty":
        return "INCONCLUSIVE", f"{name}: 'no ordered build' (data state, not a render fault)"
    shown = _shown(card.get("box"))
    if shown is None:
        return "INCONCLUSIVE", f"{name}: box not captured"
    chips = card.get("chips")
    if state != "ready" or card.get("tag") != SEQ_TAG or not _is_num(chips) \
            or not 1 <= chips <= SEQ_MAX_CHIPS:
        return "FAIL", f"{name}: MALFORMED (state / tag / chip count not the renderer's shape)"
    if not shown:
        return "FAIL", f"{name}: a ready strip with no rendered box"
    return "PASS", f"{name}: RENDERED ({chips} chips) inside the chooser for this champion"


def grade(ev: dict) -> dict:
    if not isinstance(ev, dict):
        raise InputError("evidence must be a JSON object")
    checks: dict = {}
    provenance: list[str] = []
    gaps: list[str] = []
    notes: list[str] = []
    cards: dict = {}
    state = "UNGRADED"

    def result(verdict):
        return {"verdict": verdict, "state": state, "checks": checks, "cards": cards,
                "provenance": provenance, "gaps": gaps, "notes": notes,
                "captured_at": ev.get("captured_at")}

    href = str(ev.get("href") or "")
    checks["real_origin"] = bool(re.match(r"^https://[^/]+:8888(/|$)", href))
    if not checks["real_origin"]:
        provenance.append("evidence href is not the https :8888 dashboard")
    mock = ev.get("ui_mock")
    if mock not in (None, "", "0", 0, False) or "ui_mock=1" in href:
        provenance.append("ui_mock is on: a fixture champ select, not the live LCU")
    lcu = ev.get("lcu")
    if not isinstance(lcu, dict):
        provenance.append("no /api/state read in this capture")
        lcu = {}
    if provenance:
        return result("INCONCLUSIVE")

    phase = lcu.get("phase")
    checks["phase"] = phase if isinstance(phase, str) else None
    checks["queue_id"] = lcu.get("queue_id") if _is_num(lcu.get("queue_id")) else None
    if phase != "ChampSelect":
        state = "NOT_IN_CHAMP_SELECT"
        gaps.append(f"LCU phase is {phase!r}, not ChampSelect")
        return result("INCONCLUSIVE")
    mine, locked_id = lcu.get("my_champion"), lcu.get("my_champion_locked")
    locked = (lcu.get("my_completed") is True and _is_num(mine) and mine > 0
              and (locked_id is None or locked_id == mine))
    checks["locked"] = locked
    if not locked:
        state = "NOT_LOCKED"
        gaps.append("own champion not LOCKED (hover only, or no pick yet): lock in and capture again")
        return result("INCONCLUSIVE")
    slug = ev.get("slug")
    if not isinstance(slug, str) or not slug:
        gaps.append("own champion id did not resolve to a slug")
        return result("INCONCLUSIVE")
    page_age = ev.get("page_age_s")
    if not _is_num(page_age) or page_age < SETTLE_S:
        gaps.append(f"page younger than {SETTLE_S:.0f} s (or age not captured): capture again")
        return result("INCONCLUSIVE")
    if _shown(ev.get("view_box")) is not True:
        state = "VIEW_NOT_SHOWN"
        gaps.append("#view-champ-select has no rendered box (another view is up)")
        return result("INCONCLUSIVE")
    if ev.get("visibility") != "visible":
        gaps.append("tab not visible: rAF renders do not run in a background tab")
        return result("INCONCLUSIVE")
    if _shown(ev.get("host_box")) is not True:
        gaps.append("the cards' host .csv-card has no rendered box")
        return result("INCONCLUSIVE")
    if ev.get("cache_error"):
        notes.append(f"page cache read failed ({ev.get('cache_error')}): hidden cards cannot FAIL")

    mode = detect_mode(lcu.get("queue_id"), lcu.get("is_aram"))
    checks["mode"] = mode
    if mode != "sr":
        state = "NOT_SR"
        gaps.append("not an SR queue: champ_select.js renders these cards only in SR "
                    "(_csvRenderSuggestions), so an ARAM / Arena select proves nothing")
        return result("INCONCLUSIVE")
    settled = ev.get("dom_after_cache") is True and not ev.get("cache_error")
    seq = ev.get("seq")
    # the central pane and both cards are drawn in ONE renderChampSelectView pass, so a
    # chooser carrying this slug proves the page's last render was for this champion
    drawn = isinstance(seq, dict) and seq.get("builds_champion") == slug
    state = "LOCKED"
    for key, name, fn in (
            ("dsso", CARDS[0], lambda c: grade_dsso(c, settled, drawn, notes)),
            ("pbw", CARDS[1], lambda c: grade_pbw(c, settled, drawn, notes)),
            ("seq", CARDS[2], lambda c: grade_seq(c, slug, mode, page_age))):
        c = ev.get(key)
        if not isinstance(c, dict):
            raise InputError(f"{key} must be an object")
        verdict, why = fn(c)
        cards[name] = {"verdict": verdict, "why": why}
        b = c.get("box")
        if verdict == "PASS" and isinstance(b, dict) and b.get("in_viewport") is False:
            notes.append(f"{name}: rendered below the fold (scroll the card into view for the "
                         "screenshot; not graded)")
    vs = [c["verdict"] for c in cards.values()]
    if "FAIL" in vs:
        return result("FAIL")
    if all(v == "PASS" for v in vs):
        return result("PASS")
    return result("INCONCLUSIVE")


def _load_json(path: str):
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise InputError(f"{p.name}: {type(exc).__name__}") from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="read-only G1-01 champ-select card capture / grade")
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
        print(f"G1-01: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        c = res["checks"]
        print(f"G1-01 verdict {res['verdict']} ({res['state']}) phase {c.get('phase')} "
              f"queue {c.get('queue_id')} mode {c.get('mode')}")
        for name in CARDS:
            if name in res["cards"]:
                print(f"  CARD {res['cards'][name]['verdict']:<12} {res['cards'][name]['why']}")
        for line in res["provenance"]:
            print("  NOT EVIDENCE " + line)
        for line in res["gaps"]:
            print("  GAP  " + line)
        for line in res["notes"]:
            print("  NOTE " + line)
    return {"PASS": 0, "FAIL": 1}.get(res["verdict"], 3)


if __name__ == "__main__":
    sys.exit(main())
