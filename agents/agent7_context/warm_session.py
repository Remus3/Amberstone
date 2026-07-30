"""Agent 7 warm-session manager - persistent Haiku conversation handle.

Replaces the per-request ephemeral ``claude`` subprocess invocation for
``/api/input`` traffic when the user is actively at the UI. Typical
round-trip drops from ~6s (subprocess + cold Claude) to ~1s (direct
SDK + warm context cache), and cost drops ~6x for short prompts.

Lifecycle (per Agent 7 charter):
  * **Warm starts** on first ``send()`` call (lazy).
  * **Warm ends** when idle for ``IDLE_TIMEOUT_SEC`` (30 min) *or* when
    the supervisor calls ``close()`` during shutdown.
  * After warm ends, the next ``send()`` re-warms automatically.

Thread-safety: the SDK client is threadsafe for independent calls, but
we serialise ``send()`` under an internal lock because we're editing a
shared ``messages`` list. Concurrent /api/input POSTs block briefly -
acceptable for an interactive NL parser.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("agent7.warm_session")

# Charter defaults - overridable per-instance if we ever need them.
IDLE_TIMEOUT_SEC = 30 * 60     # 30 min
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_HISTORY_TURNS = 20         # trim past this to keep token cost bounded
DEFAULT_MAX_OUTPUT_TOKENS = 600


def _load_api_key() -> str:
    """Mirror coaches/_base_coach.py read_api_key so warm session finds
    the same key the coaches use."""
    p = Path(__file__).resolve().parent.parent.parent / "API-Key-Claude.txt"
    if p.exists():
        try:
            k = p.read_text(encoding="utf-8").strip()
            if k.startswith("sk-ant-"):
                return k
        except OSError:
            pass
    return os.environ.get("ANTHROPIC_API_KEY", "")


def _load_charter() -> str:
    p = Path(__file__).resolve().parent / "charter.md"
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            pass
    return ""


class WarmSessionError(RuntimeError):
    """Raised when the warm session cannot make progress (missing key,
    SDK unavailable, etc.) - callers should fall back to ephemeral CLI."""


class WarmAgent7Session:
    """Persistent Haiku-backed NL conversation for Agent 7 dispatch.

    Not a singleton per se - the supervisor owns one instance. Imports
    the Anthropic SDK lazily so importing this module from tests or
    from environments without the SDK doesn't crash.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        idle_timeout_sec: float = IDLE_TIMEOUT_SEC,
        charter: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._idle_timeout = idle_timeout_sec
        self._charter = charter if charter is not None else _load_charter()
        self._api_key = api_key if api_key is not None else _load_api_key()
        self._client: Any = None
        self._messages: list[dict[str, str]] = []
        self._last_activity: float = 0.0
        self._total_sent: int = 0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._lock = threading.Lock()

    # ---- lifecycle ----------------------------------------------------
    def _ensure_client(self) -> None:
        if self._client is not None:
            return
        if not self._api_key:
            raise WarmSessionError("no ANTHROPIC_API_KEY available")
        try:
            import anthropic
        except ImportError as e:
            raise WarmSessionError(f"anthropic SDK not importable: {e}") from e
        self._client = anthropic.Anthropic(api_key=self._api_key, base_url="https://api.anthropic.com")
        logger.info("warm session opened (model=%s)", self._model)

    def _trim_history(self) -> None:
        """Keep the last ``MAX_HISTORY_TURNS * 2`` messages (one user +
        one assistant per turn). Drops from the front."""
        cap = MAX_HISTORY_TURNS * 2
        if len(self._messages) > cap:
            self._messages = self._messages[-cap:]

    def _check_idle(self) -> bool:
        """If we've been idle past the timeout, reset to cold. Returns
        True if a reset happened (caller doesn't need to act on it)."""
        if self._last_activity == 0.0:
            return False
        if time.monotonic() - self._last_activity < self._idle_timeout:
            return False
        logger.info("warm session idle %.0fs - resetting history",
                    time.monotonic() - self._last_activity)
        self._messages.clear()
        self._last_activity = 0.0
        return True

    def close(self) -> None:
        with self._lock:
            self._messages.clear()
            # SDK has no explicit close; GC handles the HTTP pool.
            self._client = None
            self._last_activity = 0.0
        logger.info("warm session closed")

    # ---- public send --------------------------------------------------
    def send(
        self,
        user_text: str,
        max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> dict[str, Any]:
        """Send one user turn; return the assistant reply + metadata.

        Raises :class:`WarmSessionError` on any failure so the supervisor
        can fall back to the ephemeral CLI.
        """
        if not user_text or not user_text.strip():
            raise WarmSessionError("empty user_text")

        with self._lock:
            self._check_idle()
            self._ensure_client()
            self._messages.append({"role": "user", "content": user_text})
            self._trim_history()
            try:
                resp = self._client.messages.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    system=(
                        [{"type": "text", "text": self._charter,
                          "cache_control": {"type": "ephemeral"}}]
                        if self._charter else None
                    ),
                    messages=self._messages,
                    timeout=30,
                )
            except Exception as e:               # noqa: BLE001
                # Roll back the user message so a retry doesn't
                # duplicate it into the conversation.
                if self._messages and self._messages[-1]["role"] == "user":
                    self._messages.pop()
                logger.warning("warm send failed: %s", e)
                raise WarmSessionError(str(e)) from e

            try:
                text = resp.content[0].text
            except (AttributeError, IndexError) as e:
                raise WarmSessionError(f"malformed response: {e}") from e

            self._messages.append({"role": "assistant", "content": text})
            self._trim_history()
            self._last_activity = time.monotonic()
            self._total_sent += 1

            usage = getattr(resp, "usage", None)
            inp = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
            out = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
            self._total_input_tokens += inp
            self._total_output_tokens += out

            # AUDIT 2026-05-23 (cost-trace gap C): feed cost_tracker. Warm
            # session reuses one client across turns; recording happens per
            # turn so by_purpose["agent7_warm"] reflects real cadence.
            try:
                from core.cost_tracker import record_anthropic_response
                record_anthropic_response(resp, model=self._model, purpose="agent7_warm")
            except Exception as exc:  # noqa: BLE001
                logger.debug("cost_tracker record: %s", exc)

        return {
            "text": text,
            "model": self._model,
            "input_tokens": inp,
            "output_tokens": out,
            "turns": self._total_sent,
        }

    # ---- introspection ------------------------------------------------
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "warm": self._client is not None and self._last_activity > 0.0,
                "model": self._model,
                "history_len": len(self._messages),
                "turns": self._total_sent,
                "total_input_tokens": self._total_input_tokens,
                "total_output_tokens": self._total_output_tokens,
                "idle_sec": (
                    round(time.monotonic() - self._last_activity, 1)
                    if self._last_activity > 0 else None
                ),
                "idle_timeout_sec": self._idle_timeout,
            }


def warm_spawn_factory(session: WarmAgent7Session) -> Callable[[str, str, str, dict], dict]:
    """Build a callable compatible with ``InputParser(llm_spawn=...)``.

    The resulting callable matches the signature
    ``(agent, task_id, op, payload) -> dict`` expected by
    ``InputParser._consume_llm_result``. Returns the same envelope shape
    that ``supervisor.spawn_ephemeral_llm`` produces so downstream
    parsing doesn't need a branch.
    """
    def _spawn(agent: str, task_id: str, op: str, payload: dict) -> dict:
        message = payload.get("message") or payload.get("user_text") or ""
        instruction = payload.get("instruction") or ""
        # The parser's fallback flow expects a JSON reply under result.result;
        # we give it that by packing the assistant text into the standard
        # claude --output-format json envelope shape.
        text_prompt = f"{instruction}\n\n{message}" if instruction else message
        reply = session.send(text_prompt)
        return {
            "ok": True,
            "substrate": "warm_agent7_session",
            "model": reply["model"],
            "exit_code": 0,
            "elapsed_sec": 0.0,
            "result": {
                "type": "result",
                "subtype": "success",
                "result": reply["text"],
                "usage": {
                    "input_tokens": reply["input_tokens"],
                    "output_tokens": reply["output_tokens"],
                },
            },
        }
    return _spawn
