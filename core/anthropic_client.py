"""core/anthropic_client.py - tracked Anthropic client construction shim.

Defense-in-depth vs the recurring "new coach forgot to wire telemetry" gap.
3rd cost-trace audit (2026-04-29 gap A, gap B, 2026-05-23) caught 11
untracked `messages.create` call sites. Even after wiring all 11, a future
caller may add a 12th. This shim lets any caller use a single import
(`from core.anthropic_client import tracked_anthropic`) and get
auto-recording for free.

Usage:

    from core.anthropic_client import tracked_anthropic
    client = tracked_anthropic(api_key, purpose="aram_coach")
    resp = client.messages.create(model="claude-haiku-4-5-20251001",
                                  max_tokens=400,
                                  messages=[...])
    # resp is byte-equivalent to the raw anthropic.Anthropic response;
    # the cost ledger has been updated as a side-effect.

The shim returns the real `anthropic.Anthropic` instance with
`messages.create` rebound to a wrapper that records the response. All
other client methods + attributes pass through unchanged.

Best-effort: a telemetry hiccup must not break the caller. Recording
failures are swallowed; the raw response is still returned. Exceptions
raised by the underlying `messages.create` propagate unchanged (we do
NOT eat real API errors).

Sites that need PER-CALL purpose labels (e.g. vision_server records
vision_relay vs coach_relay from the same client) should call
`core.cost_tracker.record_anthropic_response(resp, model=..., purpose=...)`
directly after `messages.create` instead of constructing through this
shim - or pass a different `purpose=` per construction.
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("rc.anthropic_client")


def tracked_anthropic(
    api_key: str,
    *,
    purpose: str,
    default_model: str = "",
) -> Any:
    """Return an `anthropic.Anthropic` client whose `messages.create`
    auto-records to `core.cost_tracker`.

    Parameters
    ----------
    api_key : str
        Anthropic API key. Passed through to `anthropic.Anthropic(api_key=...)`.
    purpose : str
        Cost-ledger purpose label (e.g. "aram_coach"). Recorded into
        `by_purpose[<purpose>]` in `data/spend/YYYY-MM-DD.json`.
    default_model : str
        Fallback model name if `messages.create(model=...)` is omitted at
        the call site AND the response object has no `.model` attribute.
        Empty string by default (relies on the response).

    Returns
    -------
    anthropic.Anthropic
        Real client with `messages.create` shimmed to record after a
        successful response.
    """
    import anthropic  # imported lazily so tests can monkeypatch
    client = anthropic.Anthropic(api_key=api_key)
    original_create = client.messages.create

    def wrapped_create(*args: Any, **kwargs: Any) -> Any:
        resp = original_create(*args, **kwargs)
        try:
            from core.cost_tracker import record_anthropic_response
            mdl = kwargs.get("model") or default_model
            record_anthropic_response(resp, model=mdl, purpose=purpose)
        except Exception as exc:
            _log.debug("tracked_anthropic record swallowed: %s", exc)
        return resp

    # Rebind the bound method. The Anthropic SDK exposes `client.messages`
    # as a Resource instance whose `.create` is a normal method on its
    # class; binding the attribute on the instance overrides the class
    # method for this client only.
    client.messages.create = wrapped_create  # type: ignore[assignment]
    return client
