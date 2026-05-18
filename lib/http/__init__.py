"""Shared HTTP client - every outbound call from Phase 3 code goes through here.

Enforces: polite UA, <=1 req/sec per hostname, blocklist, circuit breaker.
"""
from lib.http.client import HttpClient, HttpError, Blocked, CircuitOpen, get_client

__all__ = ["HttpClient", "HttpError", "Blocked", "CircuitOpen", "get_client"]
