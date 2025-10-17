# Scripture Scroller

A lightweight, browser-based presentation tool for displaying Bible passages in a continuous, scrollable format — designed for use during live worship services and sermons.

Traditional sermon slide decks break Scripture into disjointed slides, forcing the audience to “reset” with each transition. **Scripture Scroller** offers a more natural and meditative alternative: a clean, full-screen interface that *scrolls smoothly through a passage* as the pastor reads or preaches, much like a modern Bible app experience.

---

## ✨ Core Concept

Instead of advancing slide-by-slide, the operator presses **Space** or **Arrow Down** to *scroll* to the next portion of text. The transition is smooth, allowing the congregation to remain visually anchored to the passage. Older verses remain visible for a moment, and new verses enter gently into view — mirroring how people read Scripture digitally today.

---

## 🎯 Key Features

| Feature | Status | Description |
|----------|--------|-------------|
| **Smooth scroll navigation** | ✅ Implemented | Each key press scrolls smoothly to the next portion of text — either within a passage or to the next verse section. |
| **Intelligent scrolling** | ✅ Implemented | Automatically detects when passages are too long for the viewport and scrolls progressively through them. |
| **Sticky reference header** | ✅ Implemented | Verse reference stays visible at the top when scrolling within a passage, providing context. |
| **Gradient fade effect** | ✅ Implemented | Text naturally fades as it scrolls toward the top, guiding eyes to new content. |
| **Bookmark mode** | ✅ Implemented | Press **B** to gracefully fade content for sermon pauses (like placing a bookmark in a Bible). |
| **Large, legible typography** | ✅ Implemented | Projection-optimized 4rem serif text with justified alignment, mimicking modern Bible apps. |
| **Highlighting / dimming** | ✅ Implemented | Current verses at full opacity; past verses dimmed; upcoming verses subtle. |
| **Dark mode** | ✅ Implemented | High-contrast dark theme optimized for low-light sanctuaries. |
| **Light mode** | ✅ Implemented | Clean paper-white theme for daytime services, toggled with **T** key. |
| **In-app editing** | ✅ Implemented | Edit mode (**E** key) for text editing; Style mode (**S** key) for marking words of Christ in red. |
| **Passage management** | ✅ Implemented | Add, remove, reorder passages directly in Edit mode with visual toolbar buttons. |
| **Offline-ready** | ✅ Implemented | Fully static — runs from filesystem, USB drive, or any web server without internet. |
| **JSON data source** | 🔄 Planned | Load verses dynamically from a `passages.json` file (currently hardcoded samples). |
| **Remote control** | 🔄 Planned | Optional control via local server or web socket. |

---

## 🧩 Technical Overview

### 1. Project Structure

scripture-scroller/
│
├── index.html # Main presentation file
├── style.css # Typography and theme styles
├── app.js # Scrolling and interaction logic
├── passages.json # Sermon passages (editable)
└── assets/ # Backgrounds, logos, etc. (optional)


### 2. Example `passages.json`

```json
[
  {
    "ref": "John 1:1–3",
    "text": "In the beginning was the Word, and the Word was with God, and the Word was God..."
  },
  {
    "ref": "John 1:4–6",
    "text": "In Him was life, and the life was the light of men..."
  },
  {
    "ref": "John 1:7–10",
    "text": "He came as a witness, to bear witness about the light..."
  }
]
```

## 🖥️ Usage

### Getting Started

1. Clone or download the repository.
2. Open `index.html` in a modern web browser (Chrome, Edge, or Firefox recommended).
3. The demo loads with sample passages from John 1:1–10.

### Keyboard Controls

#### Presentation Mode (default)
| Key | Action |
|-----|--------|
| **Space** or **↓** | Scroll forward (within passage or to next verse) |
| **↑** | Scroll backward (within passage or to previous verse) |
| **B** | Toggle bookmark mode (fade content for sermon pauses) |
| **T** | Toggle light/dark theme |
| **E** | Enter Edit mode |
| **S** | Enter Style mode |

#### Edit Mode (press **E** to enter, **Esc** to exit)
| Action | Control |
|--------|---------|
| **Edit verse text** | Click into any verse text and edit directly |
| **Edit verse reference** | Click into verse reference and edit directly |
| **Move passage up** | Click **↑** button on verse reference |
| **Move passage down** | Click **↓** button on verse reference |
| **Insert passage above** | Click **⊕↑** button on verse reference |
| **Insert passage below** | Click **⊕↓** button on verse reference |
| **Delete passage** | Click **×** button on verse reference (with confirmation) |

#### Style Mode (press **S** to enter, **Esc** to exit)
| Key | Action |
|-----|--------|
| **Select text + Enter** | Mark selected text as "words of Christ" (displays in red) |

### Editing Passages

**New in v0.2:** Passages can now be edited directly in the app!

**Using In-App Editing (Recommended):**
1. Press **E** to enter Edit mode
2. Click into any verse reference or text to edit
3. Use toolbar buttons to add, remove, or reorder passages:
   - **↑↓** - Move passages up/down
   - **⊕↑⊕↓** - Insert new passages above/below
   - **×** - Delete passages
4. Press **Esc** to save and return to presentation mode

**Styling Words of Christ:**
1. Press **S** to enter Style mode
2. Select the text you want to mark as Jesus' words
3. Press **Enter** to apply red styling
4. Press **Esc** to exit Style mode

**Manual Editing (Advanced):**
Passages are stored in the `passages` array in `app.js` (lines 2-19). You can also edit this directly:
```javascript
const passages = [
    {
        ref: "Your Reference",
        text: "Your Scripture text here..."
    }
];
```

**Note:** Changes made in Edit mode are stored in memory only. Persistence features are planned for v0.3.

## 🔧 Development Roadmap

| Milestone | Status | Description |
|-----------|--------|-------------|
| **v0.1 – Prototype** | ✅ **Complete** | Working demo with intelligent smooth scrolling, sticky headers, gradient fade, and bookmark mode. |
| **v0.2 – In-App Editing** | ✅ **Complete** | Edit mode for text/passage management, Style mode for red-letter text, light/dark theme toggle. |
| **v0.3 – Persistence** | 🔄 Next | Save edited passages to localStorage or export/import JSON. |
| **v0.4 – Enhanced Navigation** | 🔄 Planned | Jump to specific passages, search, and keyboard shortcuts reference. |
| **v0.5 – Presentation Controls** | 🔄 Planned | Optional remote control via local server or web socket. |
| **v1.0 – Release** | 🔄 Planned | Polished and production-ready for live service projection. |

## 🧰 Technical Stack

**Current Implementation:**
- **Frontend:** HTML5 + CSS3 + Vanilla JavaScript (no build tools or dependencies)
- **Animations:** Native `scrollIntoView()` and `scrollBy()` with CSS transitions
- **Data Source:** In-memory JavaScript array (editable via Edit mode)
- **Typography:** Georgia serif, 4rem size, justified text
- **Themes:** Dark mode (default) and light mode (toggled with **T** key)
- **Editing:** Full WYSIWYG editing with contentEditable, passage management with dynamic re-rendering

**Planned Enhancements:**
- Persistent storage (localStorage or JSON export/import)
- WebSocket server for remote control
- Optional Bible API integration
- Enhanced navigation and search

## 🕊️ Design Principles

- Clarity over flashiness – Typography and pacing should always serve Scripture, not distract from it.
- Continuity – Encourage a “reading journey” through the Word, not a slideshow of disconnected fragments.
- Accessibility – Maintain large text, high contrast, and simple controls suitable for volunteers and projection operators.
- Simplicity – The entire app should run from a single HTML file if needed.

## 💡 Example Use Case

**Scenario:** The pastor plans to teach through Romans 8:1–17 during Sunday morning worship.

**Setup:**
1. Split the passage into 5–6 natural sections (roughly 3–4 verses each)
2. Add each section to the `passages` array in `app.js`
3. Open `index.html` on the projection computer
4. Press **F11** for fullscreen mode

**Preparation (New in v0.2!):**
1. Press **E** to enter Edit mode
2. Copy the pastor's passage outline and paste directly into the app
3. Add paragraph breaks, fix formatting as needed
4. Press **S** to mark any words of Jesus in red
5. Press **Esc** to return to presentation mode

**During the Sermon:**
- As the pastor reads, the operator presses **Space** to advance
- If a section is long, the app automatically scrolls through it progressively
- The verse reference stays visible at the top for context
- Previous text remains visible but dimmed, maintaining reading continuity
- When the pastor pauses to explain, press **B** to fade the text reverently
- Press **B** again to restore the text and continue reading
- Press **T** to switch between light and dark mode based on lighting conditions

**Result:** The congregation experiences Scripture as a flowing, meditative journey rather than disconnected slide fragments.