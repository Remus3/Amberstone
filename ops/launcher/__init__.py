"""The Amberstone launcher's Python side (docs/PACKAGING_PLAN.md section 3).

`service_host` (PKG-1) owns, starts and stops RC's local services when the app
launches and exits - never at boot. Every module here runs under the
launcher's own interpreter with `-I`, so each is stdlib-only and imports
nothing from the RC tree.
"""
