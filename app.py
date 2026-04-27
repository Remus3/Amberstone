# app.py — compatibility shim (ARCH-001)
# OverlayApp is now defined in the app/ package (app/__init__.py).
# Python package takes precedence over this module — this file is kept
# only so explicit `import app` references don't raise FileNotFoundError.
# overlay.py: `from app import OverlayApp` resolves from app/__init__.py.
