# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Scripture Scroller** is a lightweight, browser-based presentation tool for displaying Bible passages in a continuous, scrollable format during live worship services. The key innovation is smooth scrolling between verses rather than abrupt slide transitions, creating a more natural reading experience.

## Architecture

This is a web application with a Node.js backend and vanilla JavaScript frontend:

- **server.js**: Node.js/Express server for file management and REST API
- **index.html**: Main presentation interface and entry point
- **app.js**: Core scrolling logic, keyboard navigation, and passage rendering
- **style.css**: Typography, themes (light/dark modes), and scroll transitions
- **passages/**: Directory containing JSON passage files for different services
- **config.json**: Server configuration (passages directory path, port)

### Service Slide Builder & Email Agent

A second subsystem, layered on top of the scroller, generates ProPresenter slide
decks for the *musical* portion of a service and (as the `bs-tiz` epic) can run
unattended, driven by an emailed order of service. Full design:
**`specs/email-agent.md`**. Key pieces:

- **`.claude/commands/gen_service.md`**: the skill that turns an order of service
  into a deck. Emits **deck JSON, never HTML**. Has an interactive mode (human in
  the chat) and a non-interactive **batch mode** (whole order of service at once,
  used by the agent).
- **`scripts/build-deck.js`**: deterministic renderer — deck JSON → slide HTML +
  a machine-readable `service-report.json`. Owns everything mechanical: slide
  numbering, backgrounds, seasons, stanza splitting, and **typography**. Pinned by
  `tests/build-deck.test.js` (`npm test`).
- **`schemas/deck.schema.json`**: the deck JSON contract.
- **`songs/`**: one Markdown file per song (frontmatter + `## Section` headings).
  A `|` in a lyric line is a **caesura** — where the renderer may break that line
  if it is too wide, rather than shrinking the whole song. Never shown on a slide.
- **`agent/`**: the Python Claude Agent SDK harness, Gmail gate/tools, and SQLite
  dispatcher. Tests: `cd agent && uv run pytest`; evals: `uv run pytest -m eval`.

**Copyrighted lyrics were the agent's one unsolved failure mode — solved by changing
the endpoint, not the pipeline.** Anthropic's API content-filters the licensed lyrics
the church is entitled to display, which killed a real Sunday (2026-07-26). The filter
is a property of the *endpoint*, not the model: lyrics merely being in context trips
it, so no prompt or output shaping avoids it. The fix is `AGENT_BASE_URL` — point the
agent's CLI subprocess at any Anthropic-compatible endpoint (currently Moonshot,
`kimi-k3[1m]`). See `.env.example` and `Config.agent_env()`. Verified end to end on
2026-08-02 and on a re-run of the 7/26 thread.

*Shelved by that decision:* `specs/lyric-ingestion.md`, `agent/src/email_agent/lyrics/`,
and `agent/tests/probes/` — the local-model/line-offset design (`bs-8qs`, `bs-2pn`)
that avoided sending lyrics to a cloud model. It is **not wired into the runtime**;
nothing imports `lyrics/`. Kept because the measurement work is real and the design is
the fallback if the backend ever becomes unavailable. Do not build on it without
deciding to revive it first.

Two rules that are easy to violate: **the model emits data, not slide markup** —
if a slide is wrong, fix `build-deck.js`, not the HTML; and **never hand-edit a
generated `service-preview.html`** — it is rebuilt from the deck JSON on every
change, so ad-hoc fixes must go into a durable input (the deck JSON or a
`songs/*.md` file). See `specs/email-agent.md` §5.1.

### Key Technical Decisions

- **No frontend framework**: Vanilla JavaScript for simplicity and offline reliability
- **Node.js backend**: Express server provides file loading/saving via REST API
- **Smooth scrolling**: Uses `requestAnimationFrame` for hardware-accelerated scrolling, plus native `scrollIntoView()` for passage transitions
- **JSON data source**: Simple format for non-technical operators to edit passages
- **File-based persistence**: All passage data stored in JSON files, supports cloud sync (OneDrive, etc.)

## Development Commands

This project has no frontend build system. Development workflow:

1. **Install dependencies**: `npm install`
2. **Run locally**: `npm start` (starts Express server on port 3000)
3. **Open app**: Navigate to `http://localhost:3000` in browser
4. **Edit passages**: Use in-app edit mode (press **E**) or modify JSON files in `passages/` directory
5. **Test navigation**: Use Space/Arrow keys to verify scrolling behavior

## Core Functionality

### Navigation Controls
- **Space**: Jump to next passage section
- **→ (Right Arrow)**: Jump incrementally within current passage (instant, no smooth scroll)
- **↓ (Down Arrow)**: Smooth continuous scroll within current passage (hold to scroll)
- **↑ (Up Arrow)**: Smooth continuous scroll up within current passage
- **M**: Toggle between Scripture and Media modes
- **B**: Toggle bookmark mode (blank screen)
- **T**: Toggle light/dark theme
- **F**: Open file browser
- **E**: Enter edit mode
- **S**: Enter style mode (for marking words of Christ)

### Passage Management
JSON files support two formats:

**Basic format (Scripture only):**
```json
[
  {
    "ref": "John 1:1–3",
    "text": "In the beginning was the Word..."
  }
]
```

**Extended format (Scripture + Media):**
```json
{
  "passages": [
    {
      "ref": "John 1:1–3",
      "text": "In the beginning was the Word..."
    }
  ],
  "media": [
    {
      "src": "sermon-slide.jpg",
      "alt": "Sermon Point 1"
    }
  ]
}
```

### Visual Behaviors
- Current verse section is subtly highlighted
- Previous verses remain visible but dimmed
- Smooth scroll transitions (not instant jumps)
- Typography optimized for sanctuary projection (large, high-contrast)

## Design Principles

- **Clarity over flashiness**: Typography serves Scripture, not distracts from it
- **Continuity**: Encourage reading journey, not slideshow fragments
- **Simplicity**: Should run from a single HTML file if needed
- **Offline-ready**: No network dependencies for core functionality

## Development Roadmap Context

Current status: v0.5 (Media Integration complete)

Completed milestones:
- v0.1: Static HTML prototype with smooth scroll ✅
- v0.2: In-app editing ✅
- v0.3: Node.js server with persistence and file browser ✅
- v0.4: Enhanced visual polish (authentic Bible page aesthetic) ✅
- v0.5: Media integration with smooth crossfade transitions ✅

Next milestones:
- v0.6: Enhanced navigation (jump to passages, search)
- v0.7: Presentation controls (optional remote control)
- v1.0: Production-ready for live services

## Future Considerations

- Optional Bible API integration for dynamic text fetching
- WebSocket server for remote control from tablet/phone
- Alternative input formats (YAML, Markdown)
- Presentation metadata (service date, sermon title, etc.)


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"

   bd dolt push  # issue data — NOT automatic, and NOT covered by git push
   ```
   `bd dolt push` sends the issue database to `refs/dolt/data` on the same
   GitHub remote (configured as `sync.git-remote` in `.beads/config.yaml`).
   Skipping it is how clones drift apart: `.beads/issues.jsonl` alone is a
   passive export, and a machine that never pulled your Dolt data can export
   its own staler database straight over the file. On a fresh clone, run
   `bd bootstrap` (reads `sync.git-remote`, clones the DB) before `bd init`.
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
