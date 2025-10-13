# Scripture Scroller

A lightweight, browser-based presentation tool for displaying Bible passages in a continuous, scrollable format — designed for use during live worship services and sermons.

Traditional sermon slide decks break Scripture into disjointed slides, forcing the audience to “reset” with each transition. **Scripture Scroller** offers a more natural and meditative alternative: a clean, full-screen interface that *scrolls smoothly through a passage* as the pastor reads or preaches, much like a modern Bible app experience.

---

## ✨ Core Concept

Instead of advancing slide-by-slide, the operator presses **Space** or **Arrow Down** to *scroll* to the next portion of text. The transition is smooth, allowing the congregation to remain visually anchored to the passage. Older verses remain visible for a moment, and new verses enter gently into view — mirroring how people read Scripture digitally today.

---

## 🎯 Key Features (Planned)

| Feature | Description |
|----------|-------------|
| **Predefined verse list** | Passages are defined in a simple JSON or YAML file for each sermon. |
| **Smooth scroll navigation** | Each key press scrolls smoothly to the next passage segment. |
| **Large, legible typography** | Optimized for readability from the back of a sanctuary. |
| **Highlighting / dimming** | Current verses subtly highlighted; previous verses fade slightly. |
| **Dark & light modes** | Toggleable presentation styles for morning/evening services. |
| **Offline-ready** | Fully static — can run from a USB drive or local machine without an internet connection. |
| **Optional API integration** | Future versions may fetch Scripture text dynamically (e.g., via a Bible API) if licensing allows. |

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

## 🖥️ Basic Usage

1. Clone or download the repository.
2. Open index.html in a modern web browser (Chrome, Edge, or Firefox recommended).
3. Press Space or ↓ Arrow to scroll to the next verse section.
4. Press ↑ Arrow to scroll back up.
5. Customize passages by editing passages.json.

## 🔧 Development Roadmap

| Milestone                         | Description                                                     |
| --------------------------------- | --------------------------------------------------------------- |
| **v0.1 – Prototype**              | Static HTML demo with sample verses and smooth scroll behavior. |
| **v0.2 – JSON Loader**            | Load verses dynamically from a `passages.json` file.            |
| **v0.3 – Highlighting & Dimming** | Add fade/highlight effects on scroll.                           |
| **v0.4 – Configurable Themes**    | Light/dark mode and typography controls.                        |
| **v0.5 – Presentation Controls**  | Optional remote control via local server or web socket.         |
| **v1.0 – Release**                | Polished and production-ready for live service projection.      |

## 🧰 Suggested Stack

- Frontend: HTML5 + CSS3 + Vanilla JavaScript
- Animations: scrollIntoView({ behavior: "smooth" }) or CSS transitions
- Data Source: Local passages.json file
- Optional Enhancements:
  - WebSocket server for remote control
  - Bible API integration
  - Markdown or YAML input parser

## 🕊️ Design Principles

- Clarity over flashiness – Typography and pacing should always serve Scripture, not distract from it.
- Continuity – Encourage a “reading journey” through the Word, not a slideshow of disconnected fragments.
- Accessibility – Maintain large text, high contrast, and simple controls suitable for volunteers and projection operators.
- Simplicity – The entire app should run from a single HTML file if needed.

## 💡 Example Use Case

- The pastor plans to teach through Romans 8:1–17.
- You split the passage into 5–6 natural sections (roughly 3–4 verses each).
- During the sermon, the operator taps Space as the pastor moves through the text.
- The display scrolls gently, showing the next section without abrupt transitions.