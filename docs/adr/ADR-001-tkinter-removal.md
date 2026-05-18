# ADR-001: Remove tkinter overlays; keep tk.Tk() as scheduler

**Date:** 2026-04 (Tier 2 #6)  
**Status:** Accepted

## Context

RC originally used tkinter fullscreen overlays on Game-PC to display coaching. This required a visible console window, was brittle on multi-monitor setups, and forced RC to run with a visible window process. Tier 2 work redesigned RC around a web dashboard served over HTTPS.

The `app/__init__.py` `OverlayApp` class was the integration point. Removing tkinter entirely would have required a full async refactor of the game-poll loop (Tier 2 #8, not yet started) because `root.after()` drives the scheduler.

## Decision

Remove all tkinter UI overlays and the secondary-display window. Retain `tk.Tk()` root in `app/__init__.py` solely as a scheduler via `root.after()`. RC runs headless from the operator's perspective. Coaching is delivered through the web dashboard at `:8888`.

## Consequences

**Good:** RC no longer needs a display on Legion. Overlays were fragile; the web dashboard is CSS + JS, much easier to iterate on. Console windows eliminated.  
**Trade-off:** `tk.Tk()` root remains as a silent scheduler dependency - `import tkinter` still must succeed on Legion, and a full asyncio refactor is deferred.  
**Watch for:** The `_overlay_manager.py` name is now a misnomer (no overlays). Full asyncio migration (Tier 2 #8) will remove the last tkinter dependency.
