"""Internal: the Phase 3 web UI / API HTTP handler (_QuietHandler), its
threading server (_WebServer), and start_web_server.

Behavior-preserving split (s243) of agents/supervisor.py - see that
module's split note. The public surface is re-exported by
agents.supervisor.
"""
from __future__ import annotations

import http.server
import json
import os
import socketserver
import threading
import time
from typing import TYPE_CHECKING, Any

from agents.agent7_context.warm_session import WarmSessionError, warm_spawn_factory

from agents._supervisor_common import WEB_PORT, WEB_ROOT, _iso_now, log
from agents._supervisor_ephemeral import spawn_ephemeral_llm

if TYPE_CHECKING:  # runtime-free fwd-ref: Supervisor lives in the facade
    from agents.supervisor import Supervisor


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Web handler for the Phase 3 UI.

    Audit L4: deny dotfiles and common secret filenames so a misplaced
    ``.env`` in ``web/`` never reaches the wire, even inside the LAN.

    Added 2026-04-22: ``POST /api/input`` -> Agent 7 NL parser. The parser
    files any resulting task via Agent 1's scheduler and returns the
    parse result as JSON.
    """
    _DENYLIST_NAMES = {".env", ".git", ".htpasswd", "secrets.json",
                       "api-key-claude.txt", "credentials.json"}

    def _is_forbidden(self, path: str) -> bool:
        # strip query string
        clean = path.split("?", 1)[0].split("#", 1)[0]
        basename = clean.rsplit("/", 1)[-1].lower()
        if basename.startswith("."):
            return True
        return basename in self._DENYLIST_NAMES

    def do_GET(self) -> None:
        if self._is_forbidden(self.path):
            self.send_error(403, "Forbidden")
            return
        if self.path == "/api/queue":
            return self._handle_queue_snapshot()
        if self.path.startswith("/api/adaptation"):
            return self._handle_adaptation()
        if self.path == "/api/env":
            return self._handle_env()
        if self.path.startswith("/api/minimap-crop"):
            return self._handle_minimap_crop()
        if self.path.startswith("/api/insight-card"):
            return self._handle_insight_card()
        if self.path.startswith("/api/activity"):
            return self._handle_activity()
        if self.path.startswith("/api/task/"):
            return self._handle_task_detail()
        if self.path.startswith("/api/trending"):
            return self._handle_trending()
        if self.path.startswith("/api/session-games"):
            return self._handle_session_games()
        if self.path.startswith("/api/session"):
            return self._handle_session()
        if self.path.startswith("/api/advisories"):
            return self._handle_advisories()
        if self.path.startswith("/api/time-of-day"):
            return self._handle_time_of_day()
        if self.path.startswith("/api/day-of-week"):
            return self._handle_day_of_week()
        if self.path.startswith("/api/duration"):
            return self._handle_duration()
        if self.path.startswith("/api/digest"):
            return self._handle_digest()
        if self.path.startswith("/api/locked-champion"):
            return self._handle_locked_champion()
        super().do_GET()

    def do_HEAD(self) -> None:
        if self._is_forbidden(self.path):
            self.send_error(403, "Forbidden")
            return
        # Route /api/* HEAD through do_GET. Handlers check
        # ``self.command == "HEAD"`` and skip body writes per RFC 7231.
        if self.path.startswith("/api/"):
            return self.do_GET()
        super().do_HEAD()

    def do_POST(self) -> None:
        if self.path == "/api/input":
            return self._handle_input()
        if self.path == "/api/analyze":
            return self._handle_analyze()
        if self.path == "/api/file-task":
            return self._handle_file_task()
        if self.path.startswith("/api/task/") and self.path.endswith("/dismiss"):
            return self._handle_task_dismiss()
        self.send_error(404, "Not Found")

    # ------ API handlers --------------------------------------------
    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        # 256 KiB cap on request body - prevent accidental huge uploads.
        if length <= 0 or length > 256 * 1024:
            return b""
        return self.rfile.read(length)

    def _send_json(self, status: int, obj: Any) -> None:
        # allow_nan=False rejects bare NaN/Infinity tokens (a strict
        # JSON.parse on the dashboard throws on those). If a handler
        # accidentally bubbles a non-finite float into the body, fall
        # back to a generic error envelope rather than emitting an
        # un-parseable token (cycle 5-11 non-finite-token class).
        try:
            body = json.dumps(obj, default=str, allow_nan=False).encode("utf-8")
        except ValueError:
            log.error("response body had a non-finite float; sending generic error")
            status = 500
            body = json.dumps(
                {"error": "internal error - see supervisor log"},
            ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_error(self, status: int, public_msg: str, exc: BaseException | None = None) -> None:
        """Send a generic, user-safe error body and log the raw cause.

        CLAUDE.md Error-Handling rule: never surface a raw exception string
        (str(exc) / f"...{exc}") in a wire-JSON error field reachable by the
        dashboard - it can leak internal paths, import details, or secret-
        shaped traceback fragments. The caller passes a friendly message; the
        raw ``exc`` (if any) goes to the supervisor log only.
        """
        if exc is not None:
            log.warning("%s: %s", public_msg, exc)
        self._send_json(status, {"error": public_msg})

    def _handle_input(self) -> None:
        t0 = time.monotonic()
        raw = self._read_body()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as e:
            self._send_error(400, "malformed JSON body", e)
            return
        text = (payload.get("text") or "").strip()
        if not text:
            self._send_json(400, {"error": "missing 'text' field"})
            return

        # Round 42: sim-mode UI-feedback routing. Body carries
        # ``sim_context: true`` + optional ``history`` (last ~5 turns
        # client-side) + ``sim_fixture`` name. When present, the
        # message is scoped strictly to dashboard UI.
        sim_context = bool(payload.get("sim_context"))
        history = payload.get("history") or []
        if not isinstance(history, list):
            history = []
        sim_fixture = (payload.get("sim_fixture") or "").strip() or None

        sup = self.server.supervisor
        warm = sup.warm_agent7
        spawn_fn = spawn_ephemeral_llm
        spawn_path = "ephemeral_cli"
        if warm is not None:
            warm_spawn = warm_spawn_factory(warm)
            def _spawn_with_fallback(agent, task_id, op, pl):
                try:
                    return warm_spawn(agent, task_id, op, pl)
                except WarmSessionError as exc:
                    log.warning("warm session failed, falling back to ephemeral: %s", exc)
                    return spawn_ephemeral_llm(agent, task_id, op, pl)
            spawn_fn = _spawn_with_fallback
            spawn_path = "warm_then_ephemeral"

        if sim_context:
            from agents.agent7_context.ui_feedback import UIFeedbackParser
            ui_parser = UIFeedbackParser(
                scheduler=sup.scheduler, llm_spawn=spawn_fn,
            )
            try:
                ui_result = ui_parser.parse(
                    text, history=history[-5:], sim_fixture=sim_fixture,
                )
            except Exception as e:          # noqa: BLE001
                log.exception("ui_feedback parse raised: %s", e)
                self._send_error(500, "coaching paused - retrying")
                return
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            sup.record_input_latency(elapsed_ms)
            self._send_json(200, {
                "reply": ui_result.reply,
                "intent": ui_result.intent,
                "filed": ui_result.filed,
                "used_llm": ui_result.used_llm,
                "spawn_path": spawn_path if ui_result.used_llm else None,
                "proposed_changes": ui_result.proposed_changes,
                "refused": ui_result.refused,
                "refused_reason": ui_result.refused_reason,
                "bypass_dev": ui_result.bypass_dev,
                "sim_mode": True,
                "elapsed_ms": round(elapsed_ms, 1),
            })
            return

        from agents.agent7_context import InputParser
        parser = InputParser(
            scheduler=sup.scheduler,
            llm_spawn=spawn_fn,
        )
        try:
            result = parser.parse(text)
        except Exception as e:         # noqa: BLE001
            log.exception("agent7 parse raised: %s", e)
            self._send_error(500, "coaching paused - retrying")
            return

        elapsed_ms = (time.monotonic() - t0) * 1000.0
        sup.record_input_latency(elapsed_ms)
        self._send_json(200, {
            "reply": result.reply,
            "intent": result.intent,
            "filed": result.filed,
            "used_llm": result.used_llm,
            "spawn_path": spawn_path if result.used_llm else None,
            "elapsed_ms": round(elapsed_ms, 1),
        })

    def _handle_queue_snapshot(self) -> None:
        sched = self.server.supervisor.scheduler
        self._send_json(200, sched.snapshot())

    def _handle_env(self) -> None:
        """GET /api/env - selective environment surface for the dashboard.

        Only exposes flags the UI needs; never full env (which could
        leak the API key path). Keep this whitelist short.
        Also reports warm-session status, input-latency rollup, and
        auto-analyze state so the dashboard shows health at a glance.
        """
        whitelist = ("RC_COACH_ADAPTATION",)
        out: dict[str, Any] = {k: os.environ.get(k, "") for k in whitelist}
        sup = self.server.supervisor
        warm = sup.warm_agent7
        out["warm_agent7"] = warm.stats() if warm else {"warm": False}
        out["input_latency"] = sup.input_latency_stats()
        out["auto_analyze"] = sup.auto_analyze_stats()
        self._send_json(200, out)

    def _handle_minimap_crop(self) -> None:
        """GET /api/minimap-crop?mode=sr - fetches the latest Game-PC frame
        from the vision server, crops the minimap region, returns PNG.

        Mode-specific bboxes are empirically calibrated for 1920x1080
        windowed-borderless. Override via query string
        ``?bbox=x1,y1,x2,y2`` for debugging.

        Never blocks the supervisor - fails closed with a clear status
        if the vision server is cold or PIL isn't available.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or ["sr"])[0].lower()
        bbox_raw = (qs.get("bbox") or [""])[0]

        # Bbox resolution order: ?bbox= override -> persisted calibration in
        # data/vision_regions.json (`_minimap_<mode>` key) -> hardcoded
        # 1920x1080 fallback. Arena has no minimap - falls through to 404.
        if bbox_raw:
            try:
                from agents._minimap_bbox import parse_http_override as _parse_bbox
                bbox = _parse_bbox(bbox_raw)
            except ValueError as ve:
                self._send_error(
                    400,
                    "bbox must be x1,y1,x2,y2 with r>l,b>t,coords in [0,10000]",
                    ve,
                )
                return
        else:
            from agents._minimap_bbox import resolve as _resolve_minimap_bbox
            bbox = _resolve_minimap_bbox(mode)
            if bbox is None:
                self._send_json(404, {"error": f"no minimap for mode {mode!r}"})
                return

        try:
            import io
            import base64
            import urllib.request
            from PIL import Image
            from core.vision_token import get_vision_token
        except ImportError as e:
            self._send_error(500, "minimap crop unavailable - missing dependency", e)
            return

        tok = get_vision_token()

        # Fast path: a dedicated Game-PC minimap stream uploads pre-cropped
        # frames to source=minimap at high cadence (5-10Hz). When fresh,
        # serve it directly - no decode/re-encode on the supervisor.
        # Falls through to the slow path on any failure.
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8889/latest-frame?source=minimap",
                headers={"X-RC-Token": tok},
            )
            with urllib.request.urlopen(req, timeout=1.5) as r:
                fast = json.loads(r.read())
            fast_b64 = fast.get("b64") if isinstance(fast, dict) else None
            fast_ts = float(fast.get("ts", 0) or 0)
            if fast_b64 and (time.time() - fast_ts) < 3.0:
                raw = base64.b64decode(fast_b64)
                # Source frame is JPEG from the agent; re-encode only if the
                # caller specifically wants PNG semantics. For overlay use,
                # JPEG is fine and ~5x smaller - pass through as-is.
                ctype = "image/jpeg" if fast_b64.startswith("/9j/") else "image/png"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(raw)
                return
        except Exception:  # noqa: BLE001
            pass

        # Slow path: crop on demand from the global full-frame cache.
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8889/latest-frame",
                headers={"X-RC-Token": tok},
            )
            with urllib.request.urlopen(req, timeout=2.0) as r:
                frame = json.loads(r.read())
        except Exception as e:              # noqa: BLE001
            self._send_error(502, "vision server unreachable", e)
            return

        b64 = frame.get("b64") if isinstance(frame, dict) else None
        if not b64:
            self._send_json(504, {"error": "vision server has no cached frame"})
            return

        try:
            img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
            crop = img.crop(bbox)
            buf = io.BytesIO()
            crop.save(buf, format="PNG", optimize=True)
            body = buf.getvalue()
        except Exception as e:              # noqa: BLE001
            self._send_error(500, "minimap crop failed", e)
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        # No cache - the minimap should refresh with each poll.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _handle_task_detail(self) -> None:
        """GET /api/task/<id> - current snapshot of a single task plus
        its event history from the jsonl. Powers the activity-ticker
        click-to-detail modal.
        """
        # Path: /api/task/<id>
        parts = self.path.split("?", 1)[0].split("/")
        if len(parts) < 4 or not parts[3]:
            self._send_json(400, {"error": "task id required"})
            return
        task_id = parts[3].strip()
        if len(task_id) > 64 or not all(c.isalnum() or c in "-_" for c in task_id):
            self._send_json(400, {"error": "invalid task id"})
            return
        sched = self.server.supervisor.scheduler
        task = sched.get(task_id)
        # Walk the jsonl for this task's event history - small scan,
        # queue log is KB-range.
        events: list[dict[str, Any]] = []
        try:
            with sched._queue_log.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    t = rec.get("task") or {}
                    if t.get("id") == task_id:
                        events.append({
                            "ts": rec.get("ts"),
                            "event": rec.get("event"),
                            "status": t.get("status"),
                        })
        except OSError:
            pass

        if task is None and not events:
            self._send_json(404, {"error": "task not found"})
            return

        payload_preview: dict[str, Any] = {}
        result_preview: Any = None
        if task is not None:
            # Clip large payload fields so modal doesn't blow up.
            for k, v in (task.payload or {}).items():
                sv = json.dumps(v, default=str) if not isinstance(v, str) else v
                if len(sv) > 400:
                    sv = sv[:400] + "..."
                payload_preview[k] = sv
            if task.result is not None:
                rs = json.dumps(task.result, default=str)
                result_preview = rs if len(rs) <= 800 else rs[:800] + "..."

        self._send_json(200, {
            "id": task_id,
            "op": task.op if task else None,
            "owner_agent": task.owner_agent if task else None,
            "status": task.status if task else None,
            "priority": task.priority if task else None,
            "created_at": task.created_at if task else None,
            "updated_at": task.updated_at if task else None,
            "categories": list(task.categories) if task else None,
            "payload_preview": payload_preview,
            "result_preview": result_preview,
            "last_error": task.last_error if task else None,
            "events": events,
        })

    # Advisory ops are filed by the cold-streak detector + insight
    # detector (and future similar producers) - READY tasks carrying
    # user-visible notices.
    ADVISORY_OPS = frozenset({"cold-streak-advisory", "coaching-insight-advisory"})

    def _handle_advisories(self) -> None:
        """GET /api/advisories[?mode=aram&limit=10&include_completed=0]

        Returns the list of advisory tasks (currently cold-streak
        notifications) the user should see on the dashboard. Default
        scope is READY only so dismissed advisories disappear cleanly.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode_filter = (qs.get("mode") or [""])[0].strip() or None
        include_completed = (qs.get("include_completed") or ["0"])[0] in ("1", "true")
        try:
            limit = max(1, min(50, int((qs.get("limit") or ["10"])[0])))
        except ValueError:
            limit = 10

        sched = self.server.supervisor.scheduler
        statuses = ["ready"] + (["completed"] if include_completed else [])
        entries: list[dict[str, Any]] = []
        for status in statuses:
            for t in sched.list_by_status(status):
                if t.op not in self.ADVISORY_OPS:
                    continue
                p = t.payload or {}
                if mode_filter and p.get("mode") != mode_filter:
                    continue
                entry = {
                    "id": t.id,
                    "op": t.op,
                    "status": t.status,
                    "created_at": t.created_at,
                    "priority": t.priority,
                    "mode": p.get("mode"),
                    "message": p.get("message"),
                    "detected_at": p.get("detected_at"),
                }
                if t.op == "cold-streak-advisory":
                    entry.update({
                        "champion": p.get("champion"),
                        "delta": p.get("delta"),
                        "sample": p.get("sample"),
                        "baseline_kda_ratio": p.get("baseline_kda_ratio"),
                        "recent_kda_ratio": p.get("recent_kda_ratio"),
                    })
                elif t.op == "coaching-insight-advisory":
                    entry.update({
                        "insight_type": p.get("insight_type"),
                        "severity": p.get("severity"),
                        "champion": p.get("champion"),
                    })
                entries.append(entry)
        # Sort newest-first then clip.
        entries.sort(key=lambda e: e.get("created_at") or "", reverse=True)
        self._send_json(200, {"advisories": entries[:limit]})

    def _handle_task_dismiss(self) -> None:
        """POST /api/task/<id>/dismiss - completes the task with a
        ``{dismissed_at, source: "user"}`` result marker. Useful for
        advisory tasks the user has read and wants out of the active list.
        """
        # Path: /api/task/<id>/dismiss
        parts = self.path.split("?", 1)[0].split("/")
        # ["", "api", "task", "<id>", "dismiss"]
        if len(parts) < 5 or parts[1] != "api" or parts[2] != "task" \
                or parts[4] != "dismiss" or not parts[3]:
            self._send_json(400, {"error": "malformed dismiss url"})
            return
        task_id = parts[3].strip()
        if len(task_id) > 64 or not all(c.isalnum() or c in "-_" for c in task_id):
            self._send_json(400, {"error": "invalid task id"})
            return

        sched = self.server.supervisor.scheduler
        existing = sched.get(task_id)
        if existing is None:
            self._send_json(404, {"error": "task not found"})
            return
        # Idempotent: dismissing an already-completed task is a 200 no-op.
        if existing.status == "completed":
            self._send_json(200, {
                "id": task_id, "status": "completed",
                "already_completed": True,
            })
            return

        result = {
            "dismissed_at": _iso_now(),
            "source": "user",
            "prior_status": existing.status,
        }
        t = sched.complete(task_id, result=result)
        if t is None:
            self._send_json(500, {"error": "complete() returned None"})
            return
        self._send_json(200, {
            "id": task_id,
            "status": t.status,
            "dismissed_at": result["dismissed_at"],
        })

    def _handle_activity(self) -> None:
        """GET /api/activity?limit=N - last N scheduler events for the
        dashboard activity ticker. Keeps the autonomous framework's
        work visible to the operator.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        try:
            limit = int((qs.get("limit") or ["10"])[0])
        except ValueError:
            limit = 10
        sched = self.server.supervisor.scheduler
        self._send_json(200, {
            "events": sched.recent_events(limit=limit),
            "snapshot": sched.snapshot(),
        })

    def _handle_insight_card(self) -> None:
        """GET /api/insight-card?champion=X&mode=Y[&enemies=A,B]

        Returns ``{"card": "<text>"}`` with a compact summary line for
        copying to Discord / clipboard / voice-to-text. Empty string if
        the champion has no bucket yet.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or ["aram"])[0]
        champion = (qs.get("champion") or [""])[0].strip()
        enemies_raw = (qs.get("enemies") or [""])[0].strip()
        enemies = [e.strip() for e in enemies_raw.split(",") if e.strip()] \
                  if enemies_raw else None
        if not champion:
            self._send_json(400, {"error": "champion required"})
            return
        try:
            from coaches.adaptation_hint import insight_card
        except Exception as e:              # noqa: BLE001
            log.exception("insight_card import failed: %s", e)
            self._send_error(500, "coaching data temporarily unavailable")
            return
        card = insight_card(champion, mode, enemies=enemies)
        self._send_json(200, {
            "champion": champion,
            "mode": mode,
            "enemies": enemies,
            "card": card,
            "chars": len(card),
        })

    def _handle_adaptation(self) -> None:
        """GET /api/adaptation?champion=X&mode=Y[&enemies=A,B,C]

        Returns Agent 4's aggregates for the requested champion in the
        requested mode, plus the top activated matchups. Without
        ``champion``: returns ``top_champions`` for the mode.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or ["aram"])[0]
        champion = (qs.get("champion") or [""])[0].strip()
        enemies_raw = (qs.get("enemies") or [""])[0].strip()
        enemies = [e.strip() for e in enemies_raw.split(",") if e.strip()] if enemies_raw else None
        top_n = int((qs.get("top") or ["10"])[0] or "10")

        try:
            from coaches.adaptation_hint import for_champion, format_hint_line, top_champions
        except Exception as e:               # noqa: BLE001
            log.exception("adaptation helper import failed: %s", e)
            self._send_error(500, "internal error - see supervisor log")
            return

        if champion:
            data = for_champion(champion, mode)
            data["hint"] = format_hint_line(champion, mode, enemies=enemies)
            self._send_json(200, data)
            return

        self._send_json(200, {
            "mode": mode,
            "top": top_champions(mode, n=top_n, min_games=1),
        })

    def _handle_trending(self) -> None:
        """GET /api/trending?mode=aram[&n=3]

        Returns the hot/cold KDA streaks for ``mode`` via
        ``coaches.adaptation_hint.kda_trends``. Without ``mode``, returns
        a map of mode -> trends so the dashboard can pick without a
        round-trip per mode.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or [""])[0].strip() or None
        try:
            n = max(1, min(10, int((qs.get("n") or ["3"])[0])))
        except ValueError:
            n = 3
        try:
            from coaches.adaptation_hint import kda_trends, SUPPORTED_MODES
        except Exception as e:                  # noqa: BLE001
            log.exception("trending helper import failed: %s", e)
            self._send_error(500, "internal error - see supervisor log")
            return
        if mode:
            self._send_json(200, kda_trends(mode, n=n))
            return
        self._send_json(200, {
            "by_mode": {m: kda_trends(m, n=n) for m in SUPPORTED_MODES}
        })

    def _handle_session(self) -> None:
        """GET /api/session[?since=today|24h|7d|<ISO>]

        Returns ``session_summary`` across all mode DBs. Default
        ``since`` is local midnight (today's games).
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        since_spec = (qs.get("since") or ["today"])[0].strip() or "today"
        try:
            from coaches.adaptation_hint import session_summary, _parse_since
        except Exception as e:                  # noqa: BLE001
            log.exception("session helper import failed: %s", e)
            self._send_error(500, "internal error - see supervisor log")
            return
        self._send_json(200, session_summary(_parse_since(since_spec)))

    def _handle_session_games(self) -> None:
        """GET /api/session-games[?since=today|24h|7d|<ISO>&limit=N]

        Chronological per-match timeline since ``since``. Supports
        an optional ``limit`` (tail clamp, most-recent N).
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        since_spec = (qs.get("since") or ["today"])[0].strip() or "today"
        limit_raw = (qs.get("limit") or [""])[0].strip()
        limit: int | None = None
        if limit_raw:
            try:
                limit = max(1, min(500, int(limit_raw)))
            except ValueError:
                limit = None
        try:
            from coaches.adaptation_hint import session_games, _parse_since
        except Exception as e:                  # noqa: BLE001
            log.exception("session_games import failed: %s", e)
            self._send_error(500, "internal error - see supervisor log")
            return
        games = session_games(_parse_since(since_spec), limit=limit)
        self._send_json(200, {"since": since_spec, "games": games})

    def _handle_time_of_day(self) -> None:
        """GET /api/time-of-day[?mode=aram&since=today|24h|7d|<ISO>&min=3]

        Returns per-hour win-rate + KDA buckets for the requested mode
        (or all modes). Used by the dashboard's "when am I best?" view.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or [""])[0].strip() or None
        since_spec = (qs.get("since") or [""])[0].strip() or ""
        try:
            min_games = max(1, min(50, int((qs.get("min") or ["3"])[0])))
        except ValueError:
            min_games = 3
        try:
            from coaches.adaptation_hint import time_of_day_analysis, _parse_since
        except Exception as e:                  # noqa: BLE001
            log.exception("time_of_day import failed: %s", e)
            self._send_error(500, "internal error - see supervisor log")
            return
        since = _parse_since(since_spec) if since_spec else None
        self._send_json(200, time_of_day_analysis(
            mode=mode, since_iso=since, min_games=min_games,
        ))

    def _handle_day_of_week(self) -> None:
        """GET /api/day-of-week[?mode=aram&since=today|30d|<ISO>&min=3]"""
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or [""])[0].strip() or None
        since_spec = (qs.get("since") or [""])[0].strip() or ""
        try:
            min_games = max(1, min(50, int((qs.get("min") or ["3"])[0])))
        except ValueError:
            min_games = 3
        try:
            from coaches.adaptation_hint import day_of_week_analysis, _parse_since
        except Exception as e:                  # noqa: BLE001
            log.exception("day_of_week import failed: %s", e)
            self._send_error(500, "internal error - see supervisor log")
            return
        since = _parse_since(since_spec) if since_spec else None
        self._send_json(200, day_of_week_analysis(
            mode=mode, since_iso=since, min_games=min_games,
        ))

    def _handle_duration(self) -> None:
        """GET /api/duration[?mode=X&champion=Y&since=Z&min=N]

        Buckets matches by game length into stomp / quick / standard /
        long tiers. Per-tier win-rate + KDA. Filterable by champion for
        "my Tristana is a late-game carry" style insights.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or [""])[0].strip() or None
        champion = (qs.get("champion") or [""])[0].strip() or None
        since_spec = (qs.get("since") or [""])[0].strip() or ""
        try:
            min_games = max(1, min(50, int((qs.get("min") or ["3"])[0])))
        except ValueError:
            min_games = 3
        try:
            from coaches.adaptation_hint import duration_analysis, _parse_since
        except Exception as e:                  # noqa: BLE001
            log.exception("duration_analysis import failed: %s", e)
            self._send_error(500, "internal error - see supervisor log")
            return
        since = _parse_since(since_spec) if since_spec else None
        self._send_json(200, duration_analysis(
            mode=mode, champion=champion, since_iso=since,
            min_games=min_games,
        ))

    def _handle_digest(self) -> None:
        """GET /api/digest[?mode=X&since=Y&top=N]

        Bundles the top actionable insights (cold streaks, time-of-day
        outliers, weak days, problem durations) into a single ranked
        list. One-shot endpoint for dashboards / voice assistants.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or [""])[0].strip() or None
        since_spec = (qs.get("since") or [""])[0].strip() or ""
        try:
            top_n = max(1, min(30, int((qs.get("top") or ["5"])[0])))
        except ValueError:
            top_n = 5
        try:
            from coaches.adaptation_hint import coaching_digest, _parse_since
        except Exception as e:                  # noqa: BLE001
            log.exception("coaching_digest import failed: %s", e)
            self._send_error(500, "internal error - see supervisor log")
            return
        since = _parse_since(since_spec) if since_spec else None
        self._send_json(200, coaching_digest(
            mode=mode, since_iso=since, top_n=top_n,
        ))

    def _handle_locked_champion(self) -> None:
        """GET /api/locked-champion[?fresh=1]

        Best-effort champion identification when the live-client
        pipeline isn't producing data. Tries LCU -> match_db -> recent
        user-notes. Cached 10s by default; ``?fresh=1`` forces re-probe.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        force = (qs.get("fresh") or ["0"])[0] in ("1", "true")
        try:
            from agents.agent5_ui.champion_fallback import current_champion
        except Exception as e:  # noqa: BLE001
            log.exception("champion_fallback import failed: %s", e)
            self._send_error(500, "internal error - see supervisor log")
            return
        self._send_json(200, current_champion(force_fresh=force))

    def _handle_file_task(self) -> None:
        """POST /api/file-task - file a task directly into the running
        supervisor's in-memory heap.

        Request body (JSON)::

            {
              "op": "some-op",          # required
              "owner_agent": "6",       # required - string "0".."7"
              "priority": 50,           # optional int (default 100)
              "categories": [1, 5],     # optional int list
              "payload": {...},         # optional dict
              "user_override": false,   # optional bool
              "blocks": [],             # optional task_id list
              "blocked_by": []          # optional task_id list
            }

        Returns the filed task's id + status so callers can track it.
        Goes through all existing gating (hard-gate, frozen-file guard,
        Agent 0 review). Fails with 400 on malformed input.

        LAN trust model: same as /api/input - whoever can reach 8890
        can dispatch tasks. Don't expose 8890 beyond LAN.
        """
        raw = self._read_body()
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError as e:
            self._send_error(400, "malformed JSON body", e)
            return

        op = (body.get("op") or "").strip()
        owner = str(body.get("owner_agent") or "").strip()
        if not op or not owner:
            self._send_json(400, {"error": "op and owner_agent are required"})
            return

        try:
            priority = int(body.get("priority", 100))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "priority must be int"})
            return

        cats_raw = body.get("categories") or []
        if not isinstance(cats_raw, list) or not all(isinstance(c, int) for c in cats_raw):
            self._send_json(400, {"error": "categories must be list[int]"})
            return

        payload = body.get("payload") or {}
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "payload must be object"})
            return

        sup = self.server.supervisor
        try:
            task = sup.scheduler.file_task(
                op=op,
                owner_agent=owner,
                priority=priority,
                categories=list(cats_raw),
                payload=payload,
                user_override=bool(body.get("user_override", False)),
                blocks=list(body.get("blocks") or []),
                blocked_by=list(body.get("blocked_by") or []),
            )
        except Exception as e:       # noqa: BLE001
            log.exception("file_task from HTTP raised: %s", e)
            self._send_error(500, "internal error - see supervisor log")
            return

        self._send_json(200, {
            "id": task.id,
            "status": task.status,
            "priority": task.priority,
            "owner_agent": task.owner_agent,
            "op": task.op,
            "categories": task.categories,
            "frozen_file_hits": task.payload.get("_frozen_file_hits"),
        })

    def _handle_analyze(self) -> None:
        """POST /api/analyze - optional JSON body ``{"mode": "aram"}`` to run
        one mode, otherwise runs all. Synchronous - returns the summary.
        Intended for on-demand refresh from the iPad after a match ends.
        """
        raw = self._read_body()
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {}

        mode = (body.get("mode") or "").strip() or None
        try:
            from agents.agent4_coach_mentor import analyze_mode, analyze_all
            result = analyze_mode(mode) if mode else analyze_all()
        except ValueError as e:
            self._send_error(400, "invalid analyze request (check 'mode')", e)
            return
        except FileNotFoundError as e:
            self._send_error(404, "analyze data not found", e)
            return
        except Exception as e:               # noqa: BLE001
            log.exception("analyze raised: %s", e)
            self._send_error(500, "internal error - see supervisor log")
            return

        self._send_json(200, result if mode else {"per_mode": result})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        log.info("web %s - %s", self.address_string(), format % args)


class _WebServer(socketserver.ThreadingTCPServer):
    """Wraps the supervisor handle so HTTP handlers can access the
    scheduler + ephemeral-spawn closure."""
    daemon_threads = True
    supervisor: "Supervisor"


def start_web_server(port: int = WEB_PORT, supervisor: "Supervisor" | None = None) -> socketserver.TCPServer:
    WEB_ROOT.mkdir(parents=True, exist_ok=True)
    handler = lambda *a, **kw: _QuietHandler(*a, directory=str(WEB_ROOT), **kw)  # noqa: E731
    srv = _WebServer(("0.0.0.0", port), handler)
    srv.supervisor = supervisor  # type: ignore[assignment]
    t = threading.Thread(target=srv.serve_forever, name="web-http", daemon=True)
    t.start()
    log.info("web HTTP server listening on 0.0.0.0:%d (root=%s)", port, WEB_ROOT)
    return srv
