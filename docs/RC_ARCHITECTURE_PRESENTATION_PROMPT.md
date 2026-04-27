# Prompt for Claude Desktop — make a Riot Commander presentation

Paste this entire block into the Claude Desktop app. Attach the companion file
`RC_ARCHITECTURE_INFOGRAPH.md` from this same folder so the model has the full
source content.

---

I have an attached markdown file describing the architecture of a live-gaming
coaching tool called "Riot Commander". Please produce a clean, visually
engaging 6-slide presentation from it. Format: PowerPoint (.pptx).

**Audience:** A technical peer who has never seen this project and wants to
understand the topology, data flow, and what each machine is responsible for
in 90 seconds.

**Slide-by-slide plan:**

1. **Title slide** — "Riot Commander" as headline, subhead "Multi-machine
   League of Legends coaching overlay, 2026-04-20". Three tiny icons for the
   three machines (Game-PC = game-controller, Legion = brain, iPad = tablet).
   Background: subtle dark-blue gradient.

2. **The three machines** — split into 3 columns, color-coded:
   - Game-PC (blue #4A9EFF): source of truth, runs League + 3 relay agents.
   - Legion (red #FF4A6A): the brain, runs web dashboard + vision server + RC
     main + Haiku coaching.
   - iPad (green #44FF88): viewport, shows Duet mirror + Edge PWA dashboard.
   Each column: one icon + 3 bullet points.

3. **Data flow diagram** — a flow chart with arrows. Three boxes horizontally
   (Game-PC → Legion → iPad). Label each arrow with what travels across it
   and the cadence. Pull the flow table from the source markdown for accuracy.

4. **What Legion's brain does** — zoom in on Legion. Show the two HTTP
   services (:8888 dashboard, :8889 vision server) and their responsibilities.
   Note the tkinter overlays are disabled (HEADLESS=True).

5. **Gotchas learned** — a 2×3 grid of the 6 gotchas from the source doc
   (iphlpsvc portproxy, Python cp1252 stdout, localhost-only APIs, headless
   mode, media-type mismatch, Python-string regex escapes). Each cell: bold
   title + one-line explanation.

6. **End-to-end match life** — a vertical timeline showing one match:
   queue → champ select → in-game → match end → return to lobby. At each
   step, what data flows and what the dashboard shows.

**Style guidance:**
- Dark theme (background #0b0b12, text #e0e0e8) matching the RC dashboard.
- Use the color codes above for each machine consistently.
- Monospace font for process names and API paths. Sans-serif for body text.
- Minimal words per slide — visuals carry the story.
- No stock photos. All diagrams should be generated shapes/icons.

Please produce the .pptx. If PPTX is unavailable in this environment, fall
back to a standalone HTML deck using reveal.js or similar that can be opened
in a browser and exported to PDF.
