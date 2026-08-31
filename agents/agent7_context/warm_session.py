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
shared ``messages`` list. The lock is held across the upstream call, so
a waiter blocks for up to the 30s request timeout - not "briefly", as
this docstring claimed before the lane-8 audit of 2026-08-31. ``stats()``
and ``close()`` take the same lock, so a shutdown racing an in-flight
send waits on it too. Acceptable for an interactive NL parser at current
cadence; narrowing the lock to the history mutation is filed as RM-294.
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


def _usable_key(k: str) -> bool:
    """A key must survive being written into an HTTP header.

    The SDK encodes headers as ASCII, so an internal newline or a
    non-ASCII character (a mis-saved key file) fails EVERY request. The
    client is cached on first use, so nothing re-reads the file and the
    session never recovers. Reject it here and fall through to the
    environment instead of caching a permanently broken client.
    """
    return (
        k.startswith("sk-ant-")
        and k.isascii()
        and not any(c.isspace() for c in k)
    )


def _load_api_key() -> str:
    """Mirror coaches/_base_coach.py read_api_key so warm session finds
    the same key the coaches use."""
    p = Path(__file__).resolve().parent.parent.parent / "API-Key-Claude.txt"
    if p.exists():
        try:
            k = p.read_text(encoding="utf-8").strip()
            if _usable_key(k):
                return k
            logger.warning("API-Key-Claude.txt is present but unusable "
                           "(non-ASCII, whitespace, or wrong prefix)")
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
        one assistant per turn), aligned so the window starts on a user
        turn. Drops from the front.

        The alignment is not cosmetic. The Messages API requires the
        first message to use the "user" role, and a bare tail slice lands
        on an assistant turn: `send` appends the user message BEFORE
        trimming, so at turn 21 the list is cap+1 long and `[-cap:]`
        starts one past the oldest user turn. Every request from then on
        was a 400. `_last_activity` only advances on success, so
        `_check_idle` could not fire and the session stayed broken for
        the whole idle timeout - silently, because both callers catch
        WarmSessionError and fall back to the ephemeral CLI this module
        exists to avoid. Pinned by
        tests/test_warm_session_history_contract.py.
        """
        cap = MAX_HISTORY_TURNS * 2
        if len(self._messages) > cap:
            self._messages = self._messages[-cap:]
        while self._messages and self._messages[0]["role"] != "user":
            self._messages.pop(0)

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

    def _redact(self, text: str) -> str:
        """Defense in depth: never let the key ride out on an error
        string a caller might log or render. No live SDK path was found
        that echoes it (measured against anthropic 0.96.0), so this
        guards the contract, not a demonstrated leak."""
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "<redacted-api-key>")
        return text

    def close(self) -> None:
        with self._lock:
            self._messages.clear()
            # anthropic 0.96.0 DOES expose close() (and __enter__); the
            # previous comment here claimed it did not and left the httpx
            # connection pool to GC. Release it deterministically.
            client, self._client = self._client, None
            if client is not None:
                try:
                    client.close()
                except Exception as exc:      # noqa: BLE001
                    # A transport already torn down must not block the
                    # supervisor's shutdown path.
                    logger.debug("sdk client close: %s", exc)
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
        # Both callers catch ONLY WarmSessionError to fall back to the
        # ephemeral CLI (supervisor.py, _supervisor_http.py), so a
        # non-string payload field must not escape as a raw
        # AttributeError past that handler.
        if not isinstance(user_text, str):
            raise WarmSessionError(
                f"user_text must be str, got {type(user_text).__name__}"
            )
        if not user_text.strip():
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
                # duplicate it into the conversation. No re-align is
                # needed after this pop: _trim_history above guarantees
                # messages[0] is a user turn, and popping the TAIL cannot
                # change the head. A re-align loop here was written, then
                # removed when mutation testing showed it unreachable
                # (an equivalent mutant), rather than shipped as dead
                # code carrying a comment claiming work it never does.
                if self._messages and self._messages[-1]["role"] == "user":
                    self._messages.pop()
                # Raw error to logs/ per the CLAUDE.md Error Handling
                # rule; the propagated string is redacted.
                logger.warning("warm send failed: %s", e)
                raise WarmSessionError(self._redact(str(e))) from e

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

            # Built INSIDE the lock: `turns` read outside it could be
            # bumped by a concurrent send between release and return, so
            # two callers could report the same turn number.
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
