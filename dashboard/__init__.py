"""Dashboard package - extracted from web_dashboard.py.

Slice 2B (2026-05-01): pure-builder helpers carved out of
web_dashboard.py. Slice 2C will move route handlers into
`dashboard/routes_*.py` and adopt this package's `_context`
for the shared sqlite conn cache + APP_DIR.
"""
