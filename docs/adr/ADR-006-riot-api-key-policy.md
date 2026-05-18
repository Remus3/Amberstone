# ADR-006: Riot API key permitted for full-team context enrichment

**Date:** 2026-05-09
**Status:** Accepted (supersedes prior memory rule "no Riot API key - local-data first")
**Personal-tier key issued:** 2026-05-09 (same-day approval - well inside the documented 2-6 week window; FU03 daily-renewal helper is vestigial and skipped)

## Context

RC's original posture (memory entry `reference_no_riot_api_key.md`) was **no Riot Developer API key, ever** - get all data from LCU + LiveClient + DDragon, with public-site scraping as the fallback. This held while the feature plan was self-only: every data point about the operator is reachable via LCU.

The plan changed when full-team context enrichment was scoped: showing each of the 10 champ-select players' loss-streak, mains, current rank, and locked-champion mastery.

LCU + LiveClient cannot reach this data. They expose only the operator's own history and current-game live state. Match-V5 / League-V4 / Account-V1 / Champion-Mastery-V4 - the endpoints that surface other players' history - require a Riot API key.

Alternatives considered:

1. **Continue scraping aggregator A / aggregator B / league-of-graphs.** Cloudflare-fronted, increasingly 403'd. League-of-graphs already 403s automated fetches per memory. Brittle, ToS-grey, and the freshness needed at champ-select (~30s decision window) makes scraping unreliable.
2. **Skip the feature.** Possible, but full-team context is the highest-leverage live-coaching signal RC can add: mains, streak, and rank shape every champ-select decision and every early-game gameplan.
3. **Riot Personal-tier API key, single-user shape.** Riot offers three tiers: Development (auto-issued, 24h expiry, 20/s + 100/2min), Personal (non-expiring, same 20/s + 100/2min, no domain verification required, "for personal projects / small group of users"), Production (non-expiring, 500/10s + 30k/10min, requires verified domain + ToS + Privacy Policy + hosted site). RC is single-user / private / no public distribution - Personal tier is the correct target. Single key, single machine, single operator. No multi-tenant proxy, no JWT auth, no per-user quotas. Just a module + cache + rate limiter on Legion.

Option 3 is the only durable answer.

## Decision

**Riot Developer API key is permitted for full-team context enrichment** (champ-select panels, post-game review timeline data) and any future feature that needs Match-V5 / League-V4 / Account-V1 / Champion-Mastery-V4.

Constraints:

- **Single-user shape only.** Key is operator's personal-tier key, used by one operator on Legion. No proxy service, no JWT auth, no redistribution.
- **Key location:** `C:\Riot Commander\API-Key-Riot.txt` (gitignored, mirrors `API-Key-Claude.txt` pattern).
- **All API access flows through one module:** `core/riot_api.py`. Direct `urllib.request` calls to `*.api.riotgames.com` from elsewhere in RC are not permitted.
- **Caching is required, not optional.** Match-V5 responses are immutable - cache forever. League-V4 / mastery - 5-minute TTL. Account-V1 PUUIDs - cache forever (stable). Cache backend: SQLite at `data/riot_api_cache.db`.
- **Rate limiting is required.** Token bucket sized to the active key tier's headline limit; soft-fail (log + return None) on bucket exhaustion. Coaches must tolerate missing context, never crash on it.

If a future requirement ever needs to redistribute RC or expose API-derived data publicly, this ADR must be reopened - single-user shape is the load-bearing assumption.

## Consequences

**Good:** unlocks the highest-value live-coaching feature class (full-team champ-select intelligence). Eliminates dependence on scraper-fallback that's already failing under Cloudflare. Ends the "no Riot key, ever" rule that has caused multiple "what about scraping?" detours in past sessions.

**Trade-off:** introduces an external dependency on Riot's developer portal - key tier, key expiry, rate limits, and ToS are all things RC now has to track. Adds operator burden for the application + (until production-tier approval) periodic dev-tier renewal.

**Watch for:**
- **Key tier:** Personal tier was granted on 2026-05-09 (same-day approval, well inside the documented 2-6 week window). Headline limits remain 20/s + 100/2min, identical to Dev tier. Daily renewal scaffolding (FU03) is now vestigial - Personal keys do not expire.
- **Rate-limit headroom is tight, not generous.** Personal tier inherits Dev tier's 20/s + 100/2min ceilings. The all-10-player champ-select fan-out is ~80-150 calls per **cold** fire; close to the 100/2min wall. Mitigations are not optional:
  - Account-V1 PUUIDs cache forever (Riot IDs stable) - amortizes after first session with any given player.
  - Match-V5 detail caches forever (immutable) - repeat lobbies hit cache.
  - Spread fetch across the champ-select window (~90s on SR) - token bucket prevents burst.
  - Prioritize: locked-champ mastery + rank fire first; mains + streak fire as bandwidth allows.
  - If Personal-tier limits prove insufficient in practice, Production-tier is the next step (requires verified domain + ToS + Privacy Policy - non-trivial scope expansion).
- **ToS scope of approved use:** Riot's API policy explicitly **forbids real-time in-game advisory** ("go here now" / power-spike notifications / enemy cooldown trackers / ult timers / etc.). It explicitly **permits**: pre-game best practices, post-game analysis, static-at-lock-in champion-select recommendations. RC's planned Web-API uses (champ-select enrichment + post-game review) are inside the permitted envelope. RC's existing live in-game coaching loop runs on LCU + LiveClient + local vision - **NOT** on the Riot Web API key - and is therefore a separate compliance question not bound by this ADR. The Web API key MUST NOT be used to drive any real-time in-game advisory feature.
- **Ranked champ-select obfuscation rule:** Riot obfuscates summoner names in ranked champ-select until the loading screen. Any "show enemy mains/rank during champ-select" feature must check queue type and skip enrichment for ranked queues, or only display non-name-derived data (rank without identification). Non-ranked queues are unrestricted.
- **Memory entry:** `reference_no_riot_api_key.md` rewritten as superseded; index in `MEMORY.md` updated (already done 2026-05-09).
