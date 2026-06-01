"""
core/cost_tracker.py - central cost tracking + cost-control gates.

AUDIT 2026-04-28 (proposals 5.1, 5.4, 5.5, 5.7, 5.8 + 2.1, 2.2):

  - record_call(model, input_tokens, output_tokens, cache_read, cache_write):
    daily spend ledger at data/spend/YYYY-MM-DD.json (atomic-written).
  - allow_call(): hard daily cap from rc_config.json / coach_settings.json.
  - banner_state(): ok / warn (>= 75%) / over (>= 100%) for dashboard.
  - acquire_vision_token(): token-bucket rate limit (default 6/min, burst 3).
  - vision_dedupe_get/put(): 2-second TTL cache keyed by frame_ts + prompt
    hash so the same frame doesn't re-pay across two coach loops.
  - coach_disabled(mode): reads `disabled_coaches` from config; the
    dashboard ops tab writes this list via /api/coach/toggle.

The tracker is a process-wide singleton (`get_tracker()`); concurrency is
serialized by an internal lock. Spend file writes use the shared atomic
JSON helper from `core.polled_json`.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

from core.polled_json import atomic_write_json, read_json_dict
from core.prom_metrics import Counter, Histogram

_log = logging.getLogger("rc.cost_tracker")

# Prometheus instrumentation (T3 #12, 2026-05-01). Counters bumped from
# the singleton's chokepoints - every Anthropic API call lands at
# `record_call`, every vision-rate-limit decision lands at
# `acquire_vision_token`, every dedup lookup at `vision_dedupe_get`.
_M_COACH_CALLS = Counter(
    "rc_coach_calls_total",
    "Anthropic API calls recorded by the cost tracker.",
    labelnames=("model", "purpose"),
)
_M_COACH_TOKENS = Counter(
    "rc_coach_tokens_total",
    "Tokens consumed by Anthropic API calls.",
    labelnames=("model", "kind"),
)
_M_COACH_COST_USD = Counter(
    "rc_coach_cost_usd_total",
    "Estimated USD spend on Anthropic API calls (per local pricing table).",
    labelnames=("model",),
)
# Per-call USD cost distribution (BACKLOG: per-call cost histogram). Observed
# once per record_call at the same chokepoint as the counters above so every
# Anthropic call lands in exactly one of these buckets, keyed by the cost
# "lane" (model x purpose). Lets a scrape compute median/p95 cost per lane and
# alert when p95 doubles week-over-week. USD buckets span a sub-tenth-cent
# Haiku tick up to a $1 Sonnet/vision call.
COST_PER_CALL_BUCKETS = (
    0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0,
)
_M_COACH_COST_PER_CALL = Histogram(
    "rc_coach_cost_usd_per_call",
    "Per-call estimated USD cost distribution, by model and purpose lane.",
    buckets=COST_PER_CALL_BUCKETS,
    labelnames=("model", "purpose"),
)
_M_VISION_TOKEN_GRANTED = Counter(
    "rc_vision_token_granted_total",
    "Vision rate-limit tokens granted (acquire_vision_token returned True).",
)
_M_VISION_TOKEN_DENIED = Counter(
    "rc_vision_token_denied_total",
    "Vision rate-limit tokens denied (acquire_vision_token returned False).",
)
_M_VISION_DEDUPE_HITS = Counter(
    "rc_vision_dedupe_hits_total",
    "Frame-dedup cache hits (duplicate frame skipped).",
)
_M_VISION_DEDUPE_MISSES = Counter(
    "rc_vision_dedupe_misses_total",
    "Frame-dedup cache misses (frame submitted to vision).",
)

# Approximate per-model pricing (USD per 1M tokens). Conservative; used
# only for the dashboard ledger - real billing is whatever Anthropic
# charges. Update alongside model rollouts.
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    "claude-haiku-4-5-20251001": {
        "input": 0.80, "output": 4.00,
        "cache_write_mult": 1.25, "cache_read_mult": 0.10,
    },
    "claude-sonnet-4-6": {
        "input": 3.00, "output": 15.0,
        "cache_write_mult": 1.25, "cache_read_mult": 0.10,
    },
    "claude-opus-4-7": {
        "input": 15.0, "output": 75.0,
        "cache_write_mult": 1.25, "cache_read_mult": 0.10,
    },
}
DEFAULT_PRICING = {
    "input": 3.00, "output": 15.0,
    "cache_write_mult": 1.25, "cache_read_mult": 0.10,
}

# Config keys (looked up first in rc_config.json, then coach_settings.json).
CFG_DAILY_BUDGET_USD     = "daily_budget_usd"        # None / 0 = unlimited
CFG_WARN_FRAC            = "warn_at_fraction"        # default 0.75
CFG_VISION_RATE_PER_MIN  = "vision_calls_per_min"    # default 6
CFG_VISION_BURST         = "vision_burst"            # default 3
CFG_COACH_DISABLED_MODES = "disabled_coaches"        # list[str], lowercase

DEFAULT_WARN_FRAC    = 0.75
DEFAULT_VISION_RATE  = 6.0
DEFAULT_VISION_BURST = 3.0
DEFAULT_DEDUPE_TTL_S = 2.0

_APP_DIR    = Path(__file__).parent.parent
_SPEND_DIR  = _APP_DIR / "data" / "spend"
_COACH_CFG  = _APP_DIR / "config" / "coach_settings.json"
_RC_CFG     = _APP_DIR / "rc_config.json"

# --- API spend gates (settings-menu kill-switches + per-match cost) --------
# Each gate is an individually toggleable kill-switch surfaced in the dev
# Settings card. The disabled set is persisted in coach_settings.json under
# CFG_COACH_DISABLED_MODES (shared with the legacy per-mode switch). A gate
# maps to the cost_tracker `purpose` labels its calls record under, so the
# per-match cost panel can attribute spend back to the gate that produced it.
GATE_META = {
    "sr":           {"label": "SR coach",
                     "purposes": ["sr_coach"],
                     "explain": "Live Summoner's Rift text coaching (Haiku)."},
    "aram":         {"label": "ARAM coach",
                     "purposes": ["aram_coach", "aram_aug_select"],
                     "explain": "Live ARAM text coaching (Haiku)."},
    "arena":        {"label": "Arena coach",
                     "purposes": ["arena_coach", "arena_aug_select"],
                     "explain": "Live Arena text coaching (Haiku)."},
    "brawl":        {"label": "Brawl coach",
                     "purposes": ["brawl_coach"],
                     "explain": "Live Brawl text coaching (Haiku)."},
    "vision":       {"label": "Vision scans",
                     "purposes": ["vision_relay", "vision_direct"],
                     "explain": "Sonnet screen-vision escalation (all modes; the priciest call)."},
    "champ_select": {"label": "Champ select",
                     "purposes": ["champ_select_coach", "champ_select_brief",
                                  "aram_team_analyzer", "experimental_builder"],
                     "explain": "Champ-select brief, team analyzer, experimental builder."},
    "tft":          {"label": "TFT coach",
                     "purposes": ["tft_coach", "tft_pbe", "tft_live_analysis",
                                  "tft_live_aug_select", "tft_vision"],
                     "explain": "TFT live + PBE coaching and TFT board vision."},
}
GATES = list(GATE_META)
_MATCH_OPEN_PATH     = _SPEND_DIR / "_match_open.json"      # by_purpose snapshot @ last boundary
_RECENT_MATCHES_PATH = _SPEND_DIR / "recent_matches.json"   # rolling per-match cost (pruned)
_RECENT_MATCHES_KEEP = 2                                    # average over last N full matches


def _purpose_to_gate(purpose: str):
    """Map a cost_tracker `purpose` label to its owning gate, or None when
    the purpose is not gated (e.g. coach_relay / agent7_warm / replay)."""
    p = str(purpose or "").lower()
    if not p:
        return None
    if p.startswith("tft"):          # tft_vision stays under the TFT gate
        return "tft"
    if "vision" in p:                # vision_relay / vision_direct
        return "vision"
    for g, meta in GATE_META.items():
        if g in ("vision", "tft"):
            continue
        if p in meta["purposes"]:
            return g
    return None


def _today_str() -> str:
    return date.today().isoformat()


def _empty_ledger() -> dict:
    return {
        "date":        _today_str(),
        "total_usd":   0.0,
        "calls":       0,
        "tokens_in":   0,
        "tokens_out":  0,
        "cache_in":    0,
        "cache_write": 0,
        "by_model":    {},
        "by_purpose":  {},
    }


def _read_config() -> dict:
    """Merge rc_config.json (operational) + coach_settings.json (per-mode)."""
    merged: dict = {}
    for p in (_RC_CFG, _COACH_CFG):
        merged.update(read_json_dict(p, default={}))
    return merged


class CostTracker:
    def __init__(
        self,
        *,
        config_provider=_read_config,
        spend_dir: Optional[Path] = None,
    ) -> None:
        self._cfg_provider = config_provider
        self._spend_dir = Path(spend_dir) if spend_dir else _SPEND_DIR
        self._spend_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Vision token-bucket
        self._vb_lock = threading.Lock()
        self._vb_tokens = float(self._cfg().get(CFG_VISION_BURST, DEFAULT_VISION_BURST))
        self._vb_last = time.monotonic()
        # Frame-dedup cache: key -> (result, expires_monotonic_s)
        self._dedupe: Dict[str, tuple] = {}

    # --- Config -----------------------------------------------------------

    def _cfg(self) -> dict:
        try:
            return self._cfg_provider() or {}
        except Exception as exc:
            _log.debug("cost_tracker config load: %s", exc)
            return {}

    def _spend_path(self) -> Path:
        return self._spend_dir / f"{_today_str()}.json"

    # --- Recording (5.8) --------------------------------------------------

    def record_call(
        self,
        *,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read: int = 0,
        cache_write: int = 0,
        purpose: str = "",
    ) -> dict:
        """Append an API call to today's ledger. Returns the call's USD
        cost + running total. Safe to call from any thread."""
        price = MODEL_PRICING.get(model, DEFAULT_PRICING)
        usd_input  = (input_tokens  / 1_000_000) * price["input"]
        usd_output = (output_tokens / 1_000_000) * price["output"]
        usd_cw     = (cache_write   / 1_000_000) * price["input"] * price["cache_write_mult"]
        usd_cr     = (cache_read    / 1_000_000) * price["input"] * price["cache_read_mult"]
        total_usd  = usd_input + usd_output + usd_cw + usd_cr
        try:
            purpose_lbl = purpose or "_unspecified"
            _M_COACH_CALLS.inc(model=model, purpose=purpose_lbl)
            if input_tokens:
                _M_COACH_TOKENS.inc(input_tokens, model=model, kind="input")
            if output_tokens:
                _M_COACH_TOKENS.inc(output_tokens, model=model, kind="output")
            if cache_read:
                _M_COACH_TOKENS.inc(cache_read, model=model, kind="cache_read")
            if cache_write:
                _M_COACH_TOKENS.inc(cache_write, model=model, kind="cache_write")
            if total_usd > 0:
                _M_COACH_COST_USD.inc(total_usd, model=model)
            # Every call (including $0 ones) lands in the per-call cost
            # histogram so p50/p95-per-lane are computed over the full call
            # population, not just the billed subset.
            _M_COACH_COST_PER_CALL.observe(
                total_usd, model=model, purpose=purpose_lbl)
        except Exception as exc:
            _log.debug("prom_metrics record_call: %s", exc)
        with self._lock:
            cur = read_json_dict(self._spend_path(), default=_empty_ledger())
            if cur.get("date") != _today_str():
                cur = _empty_ledger()
            cur["total_usd"]   = round(cur.get("total_usd", 0.0) + total_usd, 6)
            cur["calls"]       = cur.get("calls", 0) + 1
            cur["tokens_in"]   = cur.get("tokens_in", 0) + input_tokens
            cur["tokens_out"]  = cur.get("tokens_out", 0) + output_tokens
            cur["cache_in"]    = cur.get("cache_in", 0) + cache_read
            cur["cache_write"] = cur.get("cache_write", 0) + cache_write
            mb = cur.setdefault("by_model", {}).setdefault(model, {
                "calls": 0, "usd": 0.0,
                "tokens_in": 0, "tokens_out": 0,
                "cache_in": 0, "cache_write": 0,
            })
            mb["calls"]       += 1
            mb["usd"]         = round(mb.get("usd", 0.0) + total_usd, 6)
            mb["tokens_in"]   += input_tokens
            mb["tokens_out"]  += output_tokens
            mb["cache_in"]    += cache_read
            mb["cache_write"] += cache_write
            if purpose:
                pb = cur.setdefault("by_purpose", {}).setdefault(purpose, {
                    "calls": 0, "usd": 0.0,
                })
                pb["calls"] += 1
                pb["usd"]    = round(pb.get("usd", 0.0) + total_usd, 6)
                pb["tokens"] = (pb.get("tokens", 0) + input_tokens
                                + output_tokens + cache_read + cache_write)
            atomic_write_json(self._spend_path(), cur)
        return {"usd": round(total_usd, 6), "total_usd": cur["total_usd"]}

    def daily_spend(self) -> dict:
        return read_json_dict(self._spend_path(), default=_empty_ledger())

    # --- Spend cap (5.4) --------------------------------------------------

    def allow_call(self) -> bool:
        budget = self._cfg().get(CFG_DAILY_BUDGET_USD)
        if not budget or float(budget) <= 0:
            return True
        return self.daily_spend().get("total_usd", 0.0) < float(budget)

    def banner_state(self) -> str:
        cfg = self._cfg()
        budget = cfg.get(CFG_DAILY_BUDGET_USD)
        if not budget or float(budget) <= 0:
            return "ok"
        cur = self.daily_spend().get("total_usd", 0.0)
        warn_frac = float(cfg.get(CFG_WARN_FRAC, DEFAULT_WARN_FRAC))
        if cur >= float(budget):
            return "over"
        if cur >= float(budget) * warn_frac:
            return "warn"
        return "ok"

    # --- Vision rate limit (5.1) ------------------------------------------

    def acquire_vision_token(self) -> bool:
        """Token bucket: refills at `vision_calls_per_min`/60 per second up
        to `vision_burst`. Returns True if the call is permitted."""
        cfg = self._cfg()
        rate_per_min = float(cfg.get(CFG_VISION_RATE_PER_MIN, DEFAULT_VISION_RATE))
        burst        = float(cfg.get(CFG_VISION_BURST, DEFAULT_VISION_BURST))
        per_sec      = max(0.0, rate_per_min / 60.0)
        with self._vb_lock:
            now = time.monotonic()
            elapsed = now - self._vb_last
            self._vb_last = now
            self._vb_tokens = min(burst, self._vb_tokens + elapsed * per_sec)
            if self._vb_tokens >= 1.0:
                self._vb_tokens -= 1.0
                granted = True
            else:
                granted = False
        try:
            (_M_VISION_TOKEN_GRANTED if granted
             else _M_VISION_TOKEN_DENIED).inc()
        except Exception as exc:
            _log.debug("prom_metrics vision_token: %s", exc)
        return granted

    # --- Frame dedupe (5.5) -----------------------------------------------

    def vision_dedupe_get(self, key: str) -> Any:
        if not key:
            return None
        result: Any = None
        hit = False
        with self._lock:
            entry = self._dedupe.get(key)
            if entry:
                cached, expires = entry
                if time.monotonic() < expires:
                    result = cached
                    hit = True
                else:
                    self._dedupe.pop(key, None)
        try:
            (_M_VISION_DEDUPE_HITS if hit
             else _M_VISION_DEDUPE_MISSES).inc()
        except Exception as exc:
            _log.debug("prom_metrics vision_dedupe_get: %s", exc)
        return result

    def vision_dedupe_put(self, key: str, result: Any,
                          ttl_s: float = DEFAULT_DEDUPE_TTL_S) -> None:
        if not key or result is None:
            return
        expires = time.monotonic() + ttl_s
        with self._lock:
            self._dedupe[key] = (result, expires)
            if len(self._dedupe) > 100:
                now = time.monotonic()
                self._dedupe = {k: v for k, v in self._dedupe.items() if v[1] > now}

    # --- Coach kill-switches (2.2) ----------------------------------------

    def coach_disabled(self, mode: str) -> bool:
        modes = self._cfg().get(CFG_COACH_DISABLED_MODES, []) or []
        return str(mode).lower() in {str(m).lower() for m in modes}

    def set_coach_disabled(self, mode: str, disabled: bool) -> list:
        """Persist a mode-toggle into coach_settings.json. Returns the new
        full list. Caller must read coach_disabled() afterwards (the
        config-provider re-reads from disk on each call)."""
        cfg = read_json_dict(_COACH_CFG, default={})
        cur = list(cfg.get(CFG_COACH_DISABLED_MODES, []) or [])
        cur_lower = [str(m).lower() for m in cur]
        m = str(mode).lower()
        if disabled and m not in cur_lower:
            cur.append(m)
        elif not disabled and m in cur_lower:
            cur = [x for x in cur if str(x).lower() != m]
        cfg[CFG_COACH_DISABLED_MODES] = cur
        atomic_write_json(_COACH_CFG, cfg)
        return cur

    # --- API spend gates + per-match cost ---------------------------------

    def gate_disabled(self, gate: str) -> bool:
        """True when `gate` is in the persisted disabled set. Generalizes
        coach_disabled() across the full gate registry (text coaches +
        vision + champ_select + tft). Re-reads disk each call so a toggle
        applies live across processes (RC main + the vision server)."""
        return self.coach_disabled(gate)

    def note_match_boundary(self) -> None:
        """Close the current per-match cost segment - call once per full
        match (core.match_db.save_match). Diffs the SHARED daily ledger's
        by_purpose since the last boundary, attributes the delta per gate,
        appends a record to recent_matches.json (kept to the last N), then
        re-snapshots. Cross-process safe: the vision server writes the same
        daily ledger, so its vision spend is captured here. Best-effort -
        a telemetry hiccup never breaks the match-save path."""
        try:
            _open_path   = self._spend_dir / "_match_open.json"
            _recent_path = self._spend_dir / "recent_matches.json"
            with self._lock:
                now_bp = self.daily_spend().get("by_purpose", {}) or {}
                open_bp = (read_json_dict(_open_path, default={})
                           .get("by_purpose", {}) or {})
                by_gate: dict = {}
                for purpose, cur in now_bp.items():
                    gate = _purpose_to_gate(purpose)
                    if gate is None or not isinstance(cur, dict):
                        continue
                    prev = open_bp.get(purpose) or {}
                    prev = prev if isinstance(prev, dict) else {}
                    d_usd = float(cur.get("usd", 0.0)) - float(prev.get("usd", 0.0))
                    d_tok = int(cur.get("tokens", 0)) - int(prev.get("tokens", 0))
                    if d_usd < 0 or d_tok < 0:   # daily ledger rolled (midnight)
                        d_usd = float(cur.get("usd", 0.0))
                        d_tok = int(cur.get("tokens", 0))
                    g = by_gate.setdefault(gate, {"usd": 0.0, "tokens": 0})
                    g["usd"] = round(g["usd"] + d_usd, 6)
                    g["tokens"] += d_tok
                rec = read_json_dict(_recent_path, default={})
                matches = rec.get("matches") or []
                matches.append({"ts": time.time(), "by_gate": by_gate})
                matches = matches[-_RECENT_MATCHES_KEEP:]          # prune
                atomic_write_json(_recent_path, {"matches": matches})
                atomic_write_json(_open_path,
                                  {"by_purpose": now_bp, "ts": time.time()})
        except Exception as exc:
            _log.debug("note_match_boundary: %s", exc)

    def recent_match_avg(self) -> dict:
        """Per-gate cost averaged over the last N full matches. Returns
        {gate: {usd, tokens, n}} for EVERY gate (zeros when no data)."""
        rec = read_json_dict(self._spend_dir / "recent_matches.json", default={})
        matches = rec.get("matches") or []
        out = {g: {"usd": 0.0, "tokens": 0, "n": 0} for g in GATES}
        if not matches:
            return out
        n = len(matches)
        for g in GATES:
            usd = sum(float((m.get("by_gate", {}).get(g) or {}).get("usd", 0.0))
                      for m in matches)
            tok = sum(int((m.get("by_gate", {}).get(g) or {}).get("tokens", 0))
                      for m in matches)
            out[g] = {"usd": round(usd / n, 6), "tokens": int(tok / n), "n": n}
        return out

    def gates_state(self) -> dict:
        """Full gate registry for the Settings UI: per gate label, explain,
        and disabled flag (enabled = not disabled)."""
        return {g: {"label": GATE_META[g]["label"],
                    "explain": GATE_META[g]["explain"],
                    "disabled": self.coach_disabled(g)}
                for g in GATES}


# --- Singleton ------------------------------------------------------------

_singleton: Optional[CostTracker] = None
_singleton_lock = threading.Lock()


def get_tracker() -> CostTracker:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = CostTracker()
    return _singleton


# --- Shared response-recording helper -------------------------------------
# Mirror of vision_server/_inference.py:_record_to_cost_tracker and
# coaches/_base_coach.py:_record_coach_call. Lifted to a public module-level
# helper so the 11 untracked call sites (tft/*, agent7, dashboard/_champ_select,
# coaches/{aram_team_analyzer, experimental_builder, champ_select_coach,
# replay_coach}) all funnel through ONE pricing-table + Prometheus path. Audit
# 2026-05-23 (3rd cost-trace gap audit: 2026-04-29 gap A, gap B, 2026-05-23).
#
# Best-effort: a telemetry hiccup never breaks the caller. Returns the per-call
# spend dict on success, None on any failure.

def record_anthropic_response(
    resp: Any,
    *,
    model: str,
    purpose: str,
) -> Optional[dict]:
    """Extract usage from an anthropic.types.Message and feed cost_tracker.

    Single chokepoint for any call site that does NOT already use
    `coaches/_base_coach._BaseCoach._record_coach_call`. Pulls
    `input_tokens / output_tokens / cache_read_input_tokens /
    cache_creation_input_tokens` defensively (each defaults to 0 if missing
    or None). Falls back to `getattr(resp, "model", "")` only if `model` is
    blank.
    """
    try:
        u = getattr(resp, "usage", None)
        tin  = int(getattr(u, "input_tokens", 0) or 0) if u else 0
        tout = int(getattr(u, "output_tokens", 0) or 0) if u else 0
        cr   = int(getattr(u, "cache_read_input_tokens", 0) or 0) if u else 0
        cw   = int(getattr(u, "cache_creation_input_tokens", 0) or 0) if u else 0
        mdl  = model or getattr(resp, "model", "") or ""
        return get_tracker().record_call(
            model=mdl,
            input_tokens=tin, output_tokens=tout,
            cache_read=cr, cache_write=cw,
            purpose=purpose or "_unspecified",
        )
    except Exception as exc:
        _log.debug("record_anthropic_response swallowed: %s", exc)
        return None
