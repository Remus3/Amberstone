"""RC Budget-Saver auto-flip watchdog (C7).

Polls the remaining Claude-plan budget fraction and, once it drops below a
threshold, arms budget-saver mode for the NEXT launch / loop cycle. This
does NOT hot-swap a live Claude Code process - it only flips the switch
that budget-saver.ps1 / the loop controller reads on their next start.

Run on a schedule (RC-BudgetSaverWatchdog, 15-min poll, registered by
setup.ps1). Each invocation is a single-shot: check, maybe arm, exit.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
FLAG_PATH = ROOT / "budget_saver_armed.flag"
COST_SIGNAL_PATH = ROOT / "usage_signal.json"  # best-effort local cache, optional
LOG_PATH = ROOT / "watchdog.log"

DEFAULT_THRESHOLD = 0.05  # arm when <5% of the plan window remains


def _log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}"
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line)


def should_arm(remaining_frac: float, threshold: float) -> bool:
    """Pure decision: arm budget-saver once remaining_frac drops below
    threshold. No I/O, no side effects - fully unit-testable."""
    return remaining_frac < threshold


def get_remaining_frac() -> float:
    """Best-effort read of the remaining-budget fraction.

    There is no guaranteed local API for "fraction of Claude plan
    remaining" - this reads an optional local usage-signal cache
    (usage_signal.json, written by any external prober that has one)
    if present and fresh-shaped. If it is missing, malformed, or any
    error occurs, this returns 1.0 (assume healthy / do not false-arm)
    and logs the miss rather than raising.
    """
    try:
        data = json.loads(COST_SIGNAL_PATH.read_text(encoding="utf-8"))
        frac = float(data["remaining_frac"])
        if 0.0 <= frac <= 1.0:
            return frac
        _log(f"[watchdog] usage_signal.json out-of-range remaining_frac={frac!r}, assuming 1.0")
        return 1.0
    except FileNotFoundError:
        _log("[watchdog] no usage_signal.json present - assuming remaining_frac=1.0 (healthy)")
        return 1.0
    except (OSError, ValueError, KeyError, TypeError) as e:
        _log(f"[watchdog] could not read remaining fraction ({e!r}) - assuming 1.0")
        return 1.0


def _set_machine_env(name: str, value: str) -> None:
    """Set a persistent Machine-scope env var so a scheduled-task-launched
    process (e.g. RC-Supervisor relaunch, or the next budget-saver shim)
    inherits it. Uses setx /M (same effect as
    [Environment]::SetEnvironmentVariable(...,'Machine') - see
    reference_scheduled_task_env_injection). Best-effort: logs and does
    not raise on failure (e.g. non-Windows dev box running the unit tests)."""
    try:
        subprocess.run(
            ["setx", name, value, "/M"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as e:
        _log(f"[watchdog] could not set Machine env {name}={value}: {e!r}")


def _toast(message: str) -> None:
    """Best-effort Windows toast via msg.exe to the current session; falls
    back to a log line if msg.exe is unavailable (non-interactive/headless)."""
    try:
        subprocess.run(
            ["msg", "*", message],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    _log(f"[watchdog] TOAST: {message}")


def arm() -> None:
    """Arm budget-saver mode: write the persistent flag file (atomic),
    set the Machine env RC_BUDGET_SAVER=1, and toast once. Idempotent -
    if the flag already exists, this only re-warms/logs, it does not
    re-toast (avoid alert spam on every 15-min poll while still armed)."""
    already_armed = FLAG_PATH.exists()

    tmp = FLAG_PATH.with_suffix(".flag.tmp")
    tmp.write_text(
        json.dumps({"armed_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "pid": os.getpid()}, indent=2),
        encoding="utf-8",
    )
    tmp.replace(FLAG_PATH)

    if not already_armed:
        _set_machine_env("RC_BUDGET_SAVER", "1")
        _toast("RC Budget-Saver ARMED - Claude plan nearly exhausted. Next launch routes local-first.")
    else:
        _log("[watchdog] already armed - flag refreshed, no repeat toast.")


def disarm() -> None:
    """Clear budget-saver mode: remove the flag and set RC_BUDGET_SAVER=0, so the
    next launch goes back to normal Claude routing. Only acts (and writes env) when
    currently armed, so it is a cheap no-op on the common healthy poll."""
    if not FLAG_PATH.exists():
        return
    try:
        FLAG_PATH.unlink()
    except OSError as e:
        _log(f"[watchdog] could not remove flag: {e!r}")
    _set_machine_env("RC_BUDGET_SAVER", "0")
    _log("[watchdog] DISARMED - budget recovered, next launch routes normal.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="RC Budget-Saver watchdog single-shot poll.")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                         help=f"remaining-fraction threshold to arm below (default {DEFAULT_THRESHOLD})")
    parser.add_argument("--dry-run", action="store_true",
                         help="report remaining fraction and the arm decision without arming")
    args = parser.parse_args(argv)

    # Refresh the usage signal from the Anthropic cost API (best-effort; a no-op
    # unless RC_BUDGET_CEILING_USD is set). Must never break the watchdog itself.
    try:
        import usage_feeder
        usage_feeder.main()
    except Exception as exc:  # noqa: BLE001 - a feeder failure must not stop the poll
        _log(f"[watchdog] usage-feed refresh skipped: {exc!r}")

    remaining = get_remaining_frac()
    would_arm = should_arm(remaining, args.threshold)

    if args.dry_run:
        print(f"[watchdog] dry-run: remaining_frac={remaining:.4f} threshold={args.threshold:.4f} "
              f"would_arm={would_arm}")
        return 0

    if would_arm:
        arm()
        _log(f"[watchdog] armed: remaining_frac={remaining:.4f} < threshold={args.threshold:.4f}")
    else:
        disarm()
        _log(f"[watchdog] holding: remaining_frac={remaining:.4f} >= threshold={args.threshold:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
