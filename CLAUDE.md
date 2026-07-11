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
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
