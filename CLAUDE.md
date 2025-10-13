# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Scripture Scroller** is a lightweight, browser-based presentation tool for displaying Bible passages in a continuous, scrollable format during live worship services. The key innovation is smooth scrolling between verses rather than abrupt slide transitions, creating a more natural reading experience.

## Architecture

This is a static web application with no build process or dependencies:

- **index.html**: Main presentation interface and entry point
- **app.js**: Core scrolling logic, keyboard navigation, and passage rendering
- **style.css**: Typography, themes (light/dark modes), and scroll transitions
- **passages.json**: Editable data file containing sermon passages for each service

### Key Technical Decisions

- **No framework**: Vanilla JavaScript for simplicity and offline reliability
- **Static deployment**: Can run from filesystem, USB drive, or any web server
- **Smooth scrolling**: Uses native `scrollIntoView({ behavior: "smooth" })` or CSS transitions
- **JSON data source**: Simple format for non-technical operators to edit passages

## Development Commands

This project has no build system. Development workflow:

1. **Run locally**: Open `index.html` directly in a browser (Chrome, Edge, Firefox)
2. **Edit passages**: Modify `passages.json` and refresh the browser
3. **Test navigation**: Use Space/Arrow keys to verify smooth scrolling behavior

## Core Functionality

### Navigation Controls
- **Space** or **↓**: Scroll to next verse section
- **↑**: Scroll to previous verse section

### Passage Management
The `passages.json` format:
```json
[
  {
    "ref": "John 1:1–3",
    "text": "In the beginning was the Word..."
  }
]
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

Current status: Early development (pre-v0.1)

Planned milestones:
- v0.1: Static HTML prototype with smooth scroll
- v0.2: Dynamic JSON loading
- v0.3: Highlighting and dimming effects
- v0.4: Configurable themes (light/dark)
- v0.5: Optional remote control features
- v1.0: Production-ready for live services

## Future Considerations

- Optional Bible API integration for dynamic text fetching
- WebSocket server for remote control from tablet/phone
- Alternative input formats (YAML, Markdown)
- Presentation metadata (service date, sermon title, etc.)
