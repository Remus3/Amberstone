import json

def send_error(h, exc: Exception, status: int = 500) -> None:
    """Send a standardized JSON error envelope with a truncated exception string."""
    payload = json.dumps({"error": str(exc)[:200]}).encode("utf-8")
    h._send(status, payload, "application/json")
