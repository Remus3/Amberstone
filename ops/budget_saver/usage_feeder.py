"""Feed usage_signal.json for the Budget-Saver watchdog from the Anthropic cost API.

Reads month-to-date organization API spend (the /v1/organizations/cost_report endpoint,
authed with ANTHROPIC_USAGE_KEY) and writes remaining_frac = max(0, 1 - spend/ceiling),
where ceiling = RC_BUDGET_CEILING_USD.

IMPORTANT: this tracks the API-KEY dollar budget (RC's runtime + any org API calls), NOT
the Claude Code SUBSCRIPTION plan (the thing that shows "N% remaining" in the CLI). There is
no standalone API for subscription-plan-remaining - for that, launch budget-saver manually
when the CLI warns you are low (see README). This feeder is the automatic path for capping
API dollar spend.

Opt-in: if RC_BUDGET_CEILING_USD is unset or <= 0, the feeder does nothing (auto-flip stays
dark) so it can never false-arm. Best-effort: any API/parse failure leaves the last signal
untouched and logs, rather than raising.
"""
import json
import os
import pathlib
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
SIGNAL_PATH = ROOT / "usage_signal.json"


def _ceiling() -> float:
    try:
        return float(os.environ.get("RC_BUDGET_CEILING_USD", "0") or 0)
    except ValueError:
        return 0.0


def _month_start_iso() -> str:
    t = time.gmtime()
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-01T00:00:00Z"


def fetch_month_spend_usd() -> float:
    """Sum month-to-date org API cost in USD. Raises on API/parse error."""
    key = os.environ["ANTHROPIC_USAGE_KEY"]
    url = ("https://api.anthropic.com/v1/organizations/cost_report"
           f"?starting_at={_month_start_iso()}")
    req = urllib.request.Request(url, headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    total = 0.0
    for bucket in data.get("data", []):
        for res in bucket.get("results", []):
            total += float(res.get("amount", 0) or 0)
    return total


def main() -> int:
    ceiling = _ceiling()
    if ceiling <= 0:
        print("[feeder] RC_BUDGET_CEILING_USD not set (>0) - auto-flip stays manual; nothing written.")
        return 0
    try:
        spend = fetch_month_spend_usd()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError, KeyError) as e:
        print(f"[feeder] cost API unavailable ({e!r}) - leaving last signal untouched.")
        return 0
    remaining = max(0.0, 1.0 - spend / ceiling)
    tmp = SIGNAL_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"remaining_frac": round(remaining, 4), "spend_usd": round(spend, 2),
                    "ceiling_usd": ceiling, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2),
        encoding="utf-8",
    )
    tmp.replace(SIGNAL_PATH)
    print(f"[feeder] spend=${spend:.2f} ceiling=${ceiling:.2f} remaining_frac={remaining:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
