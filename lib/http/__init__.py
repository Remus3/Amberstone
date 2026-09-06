"""Shared HTTP client - every outbound call from Phase 3 code goes through here.

Enforces: polite UA, <=1 req/sec per hostname, blocklist, circuit breaker,
response size ceiling.
"""
from lib.http.client import (
    Blocked,
    CircuitOpen,
    HttpClient,
    HttpError,
    ResponseTooLarge,
    get_client,
)

__all__ = [
    "HttpClient",
    "HttpError",
    "Blocked",
    "CircuitOpen",
    "ResponseTooLarge",
    "get_client",
]
