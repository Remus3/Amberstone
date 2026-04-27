"""
overlay.py — Thin entry point for Riot Commander overlay.

Imports OverlayApp from app.py (modular) and re-exports it.
main.py references `overlay.OverlayApp`, so this file must exist
and export that class.

All panel classes live in ui/, all constants in core/theme.py,
all app logic in app.py.
"""

# Re-export OverlayApp for backwards compatibility with main.py
from app import OverlayApp

if __name__ == "__main__":
    app = OverlayApp()
    app.run()
