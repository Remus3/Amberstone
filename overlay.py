"""
overlay.py - Thin entry point for Amberstone overlay.

Imports OverlayApp from the app/ package (app/__init__.py) and re-exports
it. main.py references `overlay.OverlayApp`, so this file must exist
and export that class.

All panel classes live in ui/, all constants in core/theme.py,
all app logic in the app/ package (the old app.py shim was removed
2026-10-09: the package always shadowed it, so nothing imported it).
"""

# Re-export OverlayApp for backwards compatibility with main.py
from app import OverlayApp

if __name__ == "__main__":
    app = OverlayApp()
    app.run()
