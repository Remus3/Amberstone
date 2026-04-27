# Riot Commander — System Architecture (2026-04-20)

Three machines, five data flows, one dashboard.

## High-level flow

```mermaid
flowchart LR
    subgraph GamePC ["🎮 Game-PC (192.168.8.237)"]
        direction TB
        LoL["League of Legends"]
        LCU["LCU API<br/>(localhost)"]
        LC["Live Client API<br/>(127.0.0.1:2999)"]
        ScreenA["gamepc_screen_agent.py<br/>📸 JPEG 1920×1080 every 2s"]
        LCRelay["gamepc_liveclient_relay.py<br/>📡 JSON every 1s"]
        LCUAgent["gamepc_lcu_agent.py<br/>🎫 LCU state + cmd queue"]
        LoL --> LCU
        LoL --> LC
        LoL -.screenshot.-> ScreenA
        LC -.poll.-> LCRelay
        LCU -.poll.-> LCUAgent
    end

    subgraph Legion ["🧠 Legion (192.168.8.230)"]
        direction TB
        Vision["Vision Server :8889<br/>(cache + Sonnet vision)"]
        RC["RC main.py<br/>game_reader + coaches + OCR"]
        Dashboard["Web Dashboard :8888<br/>(PWA, lobby, build preview)"]
        RC -->|reads cached frame + liveclient| Vision
        Dashboard -->|reads| Vision
        RC -->|writes coaching_data.json| Dashboard
    end

    subgraph iPad ["📱 iPad"]
        direction TB
        PWA["Edge PWA<br/>1180×820 layout"]
    end

    ScreenA -->|POST /upload-frame| Vision
    LCRelay -->|POST /upload-liveclient| Vision
    LCUAgent -->|POST /upload-lcu<br/>GET /lcu-cmd-pending| Vision
    Dashboard -->|HTTP :8888| PWA

    classDef pc fill:#0a1320,stroke:#4a9eff,color:#d0d0e0
    classDef legion fill:#1a0a14,stroke:#ff2244,color:#d0d0e0
    classDef ipad fill:#0a1a0f,stroke:#44ff88,color:#d0d0e0
    class LoL,LCU,LC,ScreenA,LCRelay,LCUAgent pc
    class Vision,RC,Dashboard legion
    class PWA ipad
```

## What each machine owns

```mermaid
flowchart TB
    subgraph G ["Game-PC — the source"]
        G1["🎮 League client lifecycle"]
        G2["🎥 Screenshot capture<br/>(1 every 2s)"]
        G3["🎫 LCU auth + commands<br/>(auto-accept, bench swap,<br/> summoner spells, rune write)"]
        G4["📡 Live Client API polling<br/>(in-game state every 1s)"]
    end

    subgraph L ["Legion — the brain"]
        L1["🧠 Coaching engine<br/>(Haiku 4.5 text, Sonnet vision)"]
        L2["📦 Relay caches<br/>(frame + liveclient + LCU)"]
        L3["🎨 Web dashboard<br/>(lobby, game mode, LCU panel)"]
        L4["📊 OCR pipeline<br/>(Tesseract, 125ms/tick)"]
        L5["🪝 Bridge to other Claude Code"]
    end

    subgraph P ["iPad — the viewport"]
        P1["📺 Mirrors Game-PC via Duet<br/>(native 1920×1080)"]
        P2["🖥️ Edge PWA<br/>(coach cards, build grid,<br/> lobby inputs, LCU controls)"]
    end

    G -->|HTTP push| L
    L -->|HTTP serve| P

    classDef pc fill:#0a1320,stroke:#4a9eff,color:#e8ecf0
    classDef legion fill:#1a0a14,stroke:#ff2244,color:#e8ecf0
    classDef ipad fill:#0a1a0f,stroke:#44ff88,color:#e8ecf0
    class G,G1,G2,G3,G4 pc
    class L,L1,L2,L3,L4,L5 legion
    class P,P1,P2 ipad
```

## Data flows — who talks to who

| From | To | Protocol | Purpose | Cadence |
|---|---|---|---|---|
| Game-PC `screen_agent` | Legion `:8889/upload-frame` | HTTP POST (JPEG b64) | Screenshots for vision + OCR | every 2s |
| Game-PC `liveclient_relay` | Legion `:8889/upload-liveclient` | HTTP POST (JSON) | Live game telemetry | every 1s |
| Game-PC `lcu_agent` | Legion `:8889/upload-lcu` | HTTP POST (JSON) | Champ-select, queue, lobby state | every 1s |
| Legion dashboard | Legion `:8889/lcu-cmd` | HTTP POST | Queue a command for LCU (accept, bench, runes) | on user action |
| Game-PC `lcu_agent` | Legion `:8889/lcu-cmd-pending` | HTTP GET | Drain queued commands | every 0.5s |
| iPad / browser | Legion `:8888/` | HTTP GET | Dashboard HTML + state polling | every 500ms |
| Both Claude Codes | Legion `:8888/api/bridge` | HTTP POST+GET | Cross-Claude activity log via hooks | per prompt |

## Process names (actual files on disk)

**Game-PC (`C:\RC-Agent\`):**
- `gamepc_screen_agent.py`
- `gamepc_liveclient_relay.py`
- `gamepc_lcu_agent.py`
- `bridge_fetch.py` / `bridge_post.py` (Claude Code hooks)

**Legion (`C:\Riot Commander\`):**
- `main.py` — RC orchestrator (poll loop, coaches)
- `web_dashboard.py` — `:8888` HTTP server
- `moon_vision_server.py` — `:8889` HTTP server (caches + Sonnet)
- `game_reader.py` — reads cached liveclient from vision server
- `coach_integration.py` — Haiku coaching (SR/Classic/Ranked)
- `core/sr_aram_worker.py` — background poll thread
- `coaches/aram_coach.py`, `brawl_coach.py`, `arena_coach.py`, `tft_coach.py`
- `core/vision_tesseract.py` — OCR pipeline
- `item_advisor.py` — curated builds + Haiku fallback + exclusions
- `data/item_exclusions.json` — Lord Dominik's vs Mortal Reminder mutex, etc.

## Key gotchas (learned the hard way)

1. **Riot's LCU and Live Client APIs are `127.0.0.1`-only.** They refuse LAN connections even when bound to `0.0.0.0`. Hence the relay pattern — agents on Game-PC POST to Legion.
2. **`iphlpsvc` portproxy self-loops** silently eat port 2999. Check `netsh interface portproxy show all` before anything else when Riot's API stops responding.
3. **Python 3.14+ on Windows defaults to cp1252 for stdout**, so agents with Unicode arrows crash on startup. Set `PYTHONUTF8=1`.
4. **HEADLESS mode disables tkinter overlays on Legion** (`_HEADLESS = True` in `app/_overlay_manager.py`) — web dashboard is the UI.
5. **Vision server hardcodes `image/png` media type**; screen agent sends JPEG. Use `"image/jpeg" if data.startswith("/9j/") else "image/png"` auto-detect.

## The full life of one match

```mermaid
sequenceDiagram
    participant U as User
    participant G as Game-PC
    participant L as Legion
    participant D as Dashboard (iPad)

    U->>G: Queue in League client
    G->>L: lcu_agent pushes phase=Matchmaking
    L->>D: phase shows "Queued"

    Note over G,L: Ready check pops
    G->>L: lcu_agent auto-accepts (config.auto_accept=true)

    U->>G: Enter champ select
    G->>L: lcu_agent pushes ChampSelect session
    L->>D: LCU panel shows champ + bench + summoners
    D->>L: /api/preview-build for picked champion
    L->>L: item_advisor.resolve_build OR Haiku fallback
    L->>D: Build path + runes + ally notes

    U->>G: In-game — load screen → moveable champion
    G->>L: screen_agent starts pushing JPEG frames
    G->>L: liveclient_relay starts pushing /liveclientdata JSON
    L->>L: game_reader detects game, starts SrAramWorker
    L->>L: Coach (Haiku) submits state every ~30s
    L->>D: coaching_data.json updates → dashboard renders

    U->>D: Click "Pick advice" / "Runes" / etc.
    D->>L: /api/input — writes to pregame field
    L->>L: coach picks up pregame as question
    L->>D: response in coach.action / .immediate / etc.

    Note over G,L: Match ends
    G->>L: lcu_agent phase=WaitingForStats
    L->>D: client mode resumes, lobby UI shown
```

## Adjacent tools

- **claude-usage-tray** — tray icon showing Claude API usage (installed on both Legion & Game-PC).
- **Duet Display** — iPad mirrors Game-PC screen over USB-C for the actual gameplay view.
- **Claude Code CLI** — running on BOTH Legion and Game-PC, coordinated via the bridge at `:8888/api/bridge` and `CLAUDE.md` files in each cwd.
