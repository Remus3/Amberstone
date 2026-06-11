# ADR-003: Vision server runs in-process on Legion at 127.0.0.1:8889

**Date:** 2026-04  
**Status:** Accepted

## Context

The vision pipeline needs to receive JPEG frames from Game-PC, cache the latest frame, run OCR (Tesseract), and optionally escalate to Sonnet vision API. Options considered:

1. **Separate process on Legion** - isolated but adds IPC overhead and a second process to supervise.
2. **In-process HTTP server** (`moon_vision_server.py`) started as a thread inside RC - same process, shared memory, simpler restart story.
3. **Separate process on Game-PC** - would require a full Anthropic API key on Game-PC for every vision call; adds latency for the coach prompt on Legion.

## Decision

`moon_vision_server.py` starts as a background thread inside the RC process, listening on `127.0.0.1:8889`. All Game-PC agents POST to this endpoint. `RC-VisionServer` scheduled task starts it independently as a fallback for when RC itself isn't running.

## Consequences

**Good:** Single process to supervise. Frame cache is in-memory (fast). Vision API key stays on Legion only.  
**Trade-off:** `moon_vision_server.py` has grown to 701 LOC (god module). A crash in the vision thread can destabilize RC (mitigated by thread isolation + health monitor).  
**Watch for:** Content-type mismatch - vision server hardcodes `image/png` but Game-PC sends JPEG. Magic-byte detection workaround is in place. Phase 2.4 will split this into `vision/`.

## Update 2026-06-11 (deep-audit P2)

Live reality refined: the server runs as a SEPARATE pythonw child process, not a thread - `dashboard/server.py` probes :8889 at RC startup and `subprocess.Popen`-spawns `moon_vision_server.py` if nothing is listening (self-heal). The `RC-VisionServer` scheduled task was a redundant boot-time launcher that lost the port race and exited 1 on every boot; it was REMOVED (XML archived in `docs/_archive/2026-06-11_RC-VisionServer_schtask_removed.xml`). The dashboard self-heal is now the sole launcher. Fallback when RC itself is down: vision is not needed without RC (its only consumers are RC coaches).
