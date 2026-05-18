# Riot Commander

## TL;DR
A personal live coaching system for League of Legends that reads the Riot game API in real time and surfaces AI-generated build and strategy advice on a second monitor while you're playing.

## The problem
League coaching advice online is static - tier lists and guides don't know what items you own mid-fight, what the enemy team is, or what patch you're on. The Riot client exposes a live game API that almost nobody builds personal tooling against. Getting fast, contextual advice during a match means either pausing to look things up (too slow) or memorizing everything (unrealistic for casual play).

## What it does
- Reads the Riot Live Client API every few seconds and feeds current gold, items, and champion data to Claude Haiku for fast mid-game advice
- Displays coaching cards on a secondary monitor (iPad-as-display via Duet) in a fullscreen Edge dashboard - visible during play without alt-tabbing
- Computes actual DPS math for every purchasable item against the current target before asking the LLM, so item recommendations are grounded in real numbers
- Screens game screenshots through Claude Sonnet vision for anything the API doesn't expose (scoreboard, draft state)
- Covers ARAM, Arena, Brawl, Summoner's Rift, and TFT with mode-aware coaches

## How it works (technical)
- **Stack:** Python 3.14, Flask (dashboard + DPS engine), asyncio scheduler, Claude Haiku (fast coaching), Claude Sonnet (vision), Tesseract OCR, Tailscale (cross-machine networking), mkcert TLS
- **Architecture:** Legion PC runs the RC process, a local DPS math service (`:8893`), a vision relay server (`:8889`), and the HTTPS dashboard (`:8888`). Game-PC runs five lightweight agents that capture the screen, poll the Riot API, and forward everything to Legion over Tailscale. The LLM sees pre-computed DPS rankings in the prompt before generating any text.
- **Non-obvious bits:**
  1. The DPS engine (`agents/daemon_slayer/`) hand-models all 547 purchasable League items - on-hit procs, armor pen, periodic damage, HP scaling - so Haiku sees "Kraken Slayer +340 DPS, 2700g" instead of guessing from patch notes. Getting this to cover the full item catalogue took 63 batch commits and reverse-engineering Meraki's item passive JSON for cooldown fields.
  2. The dashboard runs headless on Legion (no GUI process) and is served over mkcert-signed HTTPS. Game-PC's browser trusts the cert without warnings. Atomic JSON writes with retry-on-WinError-5 prevent the browser from reading a half-written file mid-poll.

## Status & impact
- **State:** In active personal use, running every session
- **What it replaced:** Looking up item builds manually on aggregator A mid-game, pausing to check tier lists; also replaced a tkinter overlay window approach that required the game and coaching UI to share a single screen
- **Numbers:** 2,262 passing tests on the DPS engine; 547/547 DDragon purchasable items covered; coaching response latency ~1-2s (Haiku); DPS engine answers in <10ms locally; 8+ months of daily iteration across ~100 tracked sessions


## Planned direction: RC Tutor

RC Tutor would be the productized variant of this codebase - single-machine install, subscription tiers, PyInstaller bundle, public distribution. Whether to build it is an open strategic question; the sections below lay out what's available, what's missing, and what the actual competitive picture looks like.

- **What's already built:** The components that transfer to RC Tutor with no productization work: Daemon Slayer DPS engine (`agents/daemon_slayer/`) with 547/547 DDragon purchasable items, ENGINE_VERSION 1.3.0, 2,262 passing tests, all four live-game coaches running `rank_for()` pre-Haiku; Tank EHP scorer (s174) + Bruiser hybrid scorer (s175) + CS archetype-picker UI (s176) + Phase 4a champion ability ingest (s177) + Phase 4b mage ability DPS evaluator (s178) + Phase 4c mage ability DPS ranker (s179, `/rank-mage` + dispatcher wire-in) + Phase 5 assassin burst-window scorer (s180, `/rank-assassin` + dispatcher wire-in) + Phase 6 enchanter HPS scorer (s181, `/rank-enchanter` + dispatcher wire-in) - **all 6 archetype scorers (carry/bruiser/tank/mage/assassin/enchanter)** fully wired through `rank_for_primary_archetype()`; archetype-expansion plan complete. Multi-mode coaching (ARAM, Arena, Brawl, SR, TFT) in `coaches/`. Vision relay (screen agent → Legion `:8889` → Tesseract OCR + Sonnet) live. HTTPS dashboard at `:8888`, headless/asyncio, SSE state stream. Personal match history (`rewind_history.db`, 2,851 matches) driving champ-select coaching and replay analysis. PyInstaller spec (`riot-commander.spec`, T3 #13) exists and bundles the main process, dashboard, and data assets - working starting point, not a tested clean-machine build. Known gap: the frozen `.ps1` ops supervisor calls Python by bare PATH name; that layer ships separately or is replaced.

- **What's needed to ship:** Five phases, with current scaffolding state. (1) *Single-machine compression* (~1-2 weeks, plan estimate) - the AI and coaching layers don't change, only relay endpoints and network assumptions. (2) *PyInstaller polish* (~1-2 weeks) - spec exists; Tesseract ships separately; frozen ops stack requires a separate launcher; not tested on a clean machine. (3) *Tiered vision routing* - Tesseract and Sonnet both exist; OCR-first escalation gate is not yet implemented. (4) *First-run wizard and API key flow* - greenfield; no scaffolding exists. (5) *Distribution and payment* - standalone installer, landing page, payment processor - all greenfield. These phases are a prerequisite estimate, not a commitment; which strategic option is pursued changes the scope materially.

- **Competitive picture:** The 2026 landscape has more direct AI coaching competition than the original plan assumed. **STATUP.GG** (Overlay Platform M, 100,000+ AI coaching sessions, free + premium) does real-time vision-based AI coaching with TTS - no formula-level damage math, but the "AI coaching" vertical is not empty. **build tool Z18** (standalone, free) markets LLM-over-live-game-state item recommendations. **Coaching App Z7.gg** (Overlay Platform M + standalone, free + premium) is currently the top-ranked LoL companion app, with AI champion-select coaching as its differentiator. **Overlay App Z5** (Overlay Platform M, free) does AI matchup tips. The Big Three (Aggregator C, Overlay App F, Overlay App E) are losing ground in 2026 reviews to ad load and bugs - none do formula-level math. On the damage-math side: **lolmath.net** (free web tool) markets "thousands of item combinations ranked by effectiveness" with "actual game data and formulas," covers SR/ARAM/Arena/URF, auto-updates per patch. **statcheck.lol** and an open-source GitHub calculator also exist. The dominant data point is **Backseat AI**: Tyler1-branded, Riot ToS-approved, multiple AI personalities, both subscription and ad tiers - shut down December 31, 2024 citing "unsustainable server costs combined with the current state of our tech." Unit economics was the killer, not features or distribution.

- **What's actually defensible:** The math layer itself is commodity - lolmath does what Daemon Slayer does, for free, on the web. The narrower advantages: (1) *Live-game integration with math grounding* - lolmath/statcheck are web tools you configure manually; RC reads live state and updates continuously without alt-tabbing. (2) *LLM synthesis on top of formula-level math* - AI coaching competitors don't do formula-level damage math; math tools don't do live LLM synthesis. RC sits at that intersection. (3) *Multi-mode coverage* - RC covers ARAM, Arena, Brawl, SR, and TFT; most AI coaching competitors are SR-focused. (4) *Vision pipeline* - Tesseract + Sonnet read scoreboard, draft state, and other data the API doesn't expose; most competitors are API-only. The honest pitch is "we integrate four things well," not "we built the only damage math engine."

- **Strategic options under consideration:** (A) *Niche down hard* - target high-elo climbers and content creators who care about formula transparency; smaller TAM (tens of thousands), higher willingness to pay ($20+/mo possible), lower acquisition cost. (B) *Keep RC personal* - don't productize; optionally open-source Daemon Slayer; 8 months of personal-use value is already realized. (C) *B2B pivot* - license the math engine as a component to existing coaching tools (Aggregator C, Overlay App E, Coaching App Z7) that recommend builds without damage-math grounding. No strategic option has been chosen.

- **Risks watched:** Unit economics first - Backseat AI's shutdown is the clearest signal in the category; the ~70% Daemon Slayer absorption rate (plan estimate, not measured) means real traffic data is needed before assuming it holds. Auto-accept enforcement - Riot pushed Overlay Platform M to remove auto-accept; standalone auto-accept is explicitly gray area; RC Tutor should drop it or make it an off-by-default opt-in with a visible use-at-own-risk warning. Vanguard on a single machine - RC's two-machine architecture sidesteps Vanguard on the AI machine; RC Tutor's single-machine target means Vanguard runs alongside the tool, which is untested on a clean machine. Competitive movement - STATUP/Coaching App Z7/build tool Z18 are active and free; the differentiation window narrows if any of them wire in formula-level math.
## Ready-to-use snippets

### Casual ("what have you been up to?")
I built a coaching tool for League of Legends that puts live item and strategy advice on my second monitor while I'm playing. It reads the actual game API, runs some damage math locally, and calls an AI to tell me what to buy next - all before I have time to alt-tab. It started as a weekend thing and turned into a pretty serious engineering project.

### LinkedIn post (~100 words)
I've been building a real-time League of Legends coaching system as a side project - and it's become one of the more technically interesting things I've worked on.

The core challenge: fast, contextually accurate advice during a live game. Static tier lists don't know your gold count, your enemy team, or your current items. So I built a local DPS math engine that models all 547 purchasable items - armor pen, on-hit procs, HP scaling - and feeds the results to Claude Haiku before it generates any text.

The takeaway: when you give a small LLM pre-computed ground truth instead of asking it to reason from memory, the quality of advice jumps dramatically.

### Resume bullet
Built a real-time League of Legends AI coaching system - local DPS engine covering 547 items + Claude Haiku integration - reducing item-decision latency from "pause and look it up" to <2s with 2,262 passing tests.

### Interview answer (~90 seconds spoken)
I play League of Legends and I kept getting outbuilt in item choices mid-game - the decisions happen in 20-30 seconds and looking things up isn't an option. So I built a personal coaching system that runs on a second monitor.

The interesting part was the item advice layer. I tried just asking an LLM "what should I buy?" and the answers were generic and often wrong for the current patch. So I built a local math engine that hand-models every purchasable item in the game - how on-hit procs interact with attack speed, how lethality vs. armor pen applies at different target health thresholds - and injected the ranked output into the LLM's context before generating advice. That got me from "probably Infinity Edge" to "Trinity Force gives you +480 DPS on this target for 2700 gold, which is best in slot right now."

The outcome: advice I actually trust in-game, a system I use every session, and a much sharper intuition for where LLM + deterministic compute beats LLM alone.

## Things to mention if asked

- **Why this stack over alternatives:** Haiku for speed (sub-2s with the DPS pre-computation in the prompt), Sonnet only for vision where the API is blind. Could have used a local model but API latency was already fine and the quality gap was significant.
- **Tradeoffs:** The DPS engine is a hand-maintained registry - every new item needs an explicit entry. Automating extraction from patch notes was explored but the formulas are too inconsistently documented. The 63-batch commit history reflects that cost.
- **What I'd do differently:** Start with the web dashboard earlier. The tkinter overlay approach worked but was architecturally messy (shared process with the game poller). The headless + HTTPS dashboard model is cleaner and easier to iterate.
- **What's next (RC personal):** Tiered vision (cheap Tesseract OCR → escalate to Sonnet only when needed), and accumulating enough real-traffic data to validate the Bridge Watcher auto-action thresholds.
- **RC Tutor relationship:** See *Planned direction: RC Tutor* above - what's built, what's missing, the real competitive picture, and the three strategic options under consideration.
