# Scripture Scroller

A lightweight, browser-based presentation tool for displaying Bible passages in a continuous, scrollable format — designed for use during live worship services and sermons.

Traditional sermon slide decks break Scripture into disjointed slides, forcing the audience to “reset” with each transition. **Scripture Scroller** offers a more natural and meditative alternative: a clean, full-screen interface that *scrolls smoothly through a passage* as the pastor reads or preaches, much like a modern Bible app experience.

---

## ✨ Core Concept

Instead of advancing slide-by-slide, the operator presses **Space** to jump between passages, **Right Arrow** to jump incrementally within a passage, or **Arrow Down** to *smoothly scroll* through text. The transitions are fluid, allowing the congregation to remain visually anchored to the passage. Older verses remain visible for a moment, and new verses enter gently into view — mirroring how people read Scripture digitally today.

---

## 🎯 Key Features

| Feature | Status | Description |
|----------|--------|-------------|
| **Smooth scroll navigation** | ✅ Implemented | Hardware-accelerated smooth scrolling using `requestAnimationFrame` for buttery-smooth transitions. |
| **Intelligent scrolling** | ✅ Implemented | Automatically detects when passages are too long for the viewport and scrolls progressively through them. |
| **Sticky reference header** | ✅ Implemented | Verse reference stays visible at the top when scrolling within a passage, providing context. |
| **Gradient fade effect** | ✅ Implemented | Text naturally fades as it scrolls toward the top, guiding eyes to new content. |
| **Media mode** | ✅ Implemented | Toggle to display slides/images alongside Scripture. Press **M** to switch between Scripture and media presentations with smooth crossfade transitions. |
| **Bookmark mode** | ✅ Implemented | Press **B** to gracefully fade content for sermon pauses (like placing a bookmark in a Bible). |
| **Large, legible typography** | ✅ Implemented | Projection-optimized 4rem serif text with justified alignment, mimicking modern Bible apps. |
| **Highlighting / dimming** | ✅ Implemented | Current verses at full opacity; past verses dimmed; upcoming verses subtle. |
| **Dark mode** | ✅ Implemented | High-contrast dark theme optimized for low-light sanctuaries. |
| **Light mode (Bible page aesthetic)** | ✅ Implemented | Warm cream paper texture with authentic Bible page details: subtle gutter shadow and red page edge. Toggled with **T** key. |
| **In-app editing** | ✅ Implemented | Edit mode (**E** key) for text editing; Style mode (**S** key) for marking words of Christ in red. |
| **Passage management** | ✅ Implemented | Add, remove, reorder passages directly in Edit mode with visual toolbar buttons. |
| **File browser** | ✅ Implemented | Press **F** to open file browser, load different passage files, auto-save on edit. |
| **JSON data source** | ✅ Implemented | Load verses dynamically from JSON files in `passages/` directory. |
| **Node.js server** | ✅ Implemented | Express server for file loading/saving, configurable passages directory. |
| **Remote control** | 🔄 Planned | Optional control via web socket for tablet/phone remote. |

---

## 🧩 Technical Overview

### 1. Project Structure

```
scripture-scroller/
│
├── server.js # Node.js/Express backend
├── package.json # Dependencies
├── config.json # Server configuration
├── index.html # Main presentation file
├── style.css # Typography and theme styles
├── app.js # Scrolling and interaction logic
└── passages/ # Sermon passage files (JSON)
    └── john-1-1-10.json # Example passage file
```


### 2. Example `passages.json`

**Basic format (Scripture only):**
```json
[
  {
    "ref": "John 1:1–3",
    "text": "In the beginning was the Word, and the Word was with God, and the Word was God..."
  },
  {
    "ref": "John 1:4–6",
    "text": "In Him was life, and the life was the light of men..."
  }
]
```

**Extended format (Scripture + Media):**
```json
{
  "passages": [
    {
      "ref": "John 1:1–3",
      "text": "In the beginning was the Word, and the Word was with God, and the Word was God..."
    },
    {
      "ref": "John 1:4–6",
      "text": "In Him was life, and the life was the light of men..."
    }
  ],
  "media": [
    {
      "src": "sermon-point-1.jpg",
      "alt": "Main Point 1"
    },
    {
      "src": "sermon-point-2.jpg",
      "alt": "Main Point 2"
    }
  ]
}
```

## 🖥️ Usage

### Getting Started

**New in v0.3:** Scripture Scroller now requires Node.js for file management and persistence.

1. Clone or download the repository
2. Install dependencies:
   ```bash
   npm install
   ```
3. Start the server:
   ```bash
   npm start
   ```
4. Open your browser to `http://localhost:3000`
5. The app loads with default hardcoded passages (or press **F** to load from files)

### Keyboard Controls

#### Presentation Mode (default)
| Key | Action |
|-----|--------|
| **Space** | Advance forward (scroll to next verse in Scripture mode, or next media slide in Media mode) |
| **→** | Jump down incrementally within current passage (instant, no smooth scroll - ideal for low-performance PCs) |
| **↓** | Smooth scroll down within passage (Scripture mode) OR advance to next media slide (Media mode) |
| **↑** | Smooth scroll up within passage (Scripture mode) OR go back to previous media slide (Media mode) |
| **M** | Toggle between Scripture mode and Media mode (smooth crossfade transition) |
| **B** | Toggle bookmark mode (fade content for sermon pauses) |
| **T** | Toggle light/dark theme |
| **F** | Open file browser to load/manage passage files |
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

### Managing Passage Files

**New in v0.3:** Full file management with persistence!

#### Loading Passage Files
1. Press **F** to open the file browser sidebar
2. Click on any `.json` file to load it
3. The passages will replace current content and scroll to the beginning

#### Creating New Passage Files
1. Create a new `.json` file in the `passages/` directory
2. Use the format shown in "Example passages.json" above
3. Press **F** to refresh the file browser and load it

#### Editing Passages
1. Press **F** to load a passage file (if needed)
2. Press **E** to enter Edit mode
3. Click into any verse reference or text to edit
4. Use toolbar buttons to add, remove, or reorder passages:
   - **↑↓** - Move passages up/down
   - **⊕↑⊕↓** - Insert new passages above/below
   - **×** - Delete passages
5. Press **Esc** to save and return to presentation mode
6. **Changes are automatically saved** to the loaded file!

#### Styling Words of Christ
1. Press **S** to enter Style mode
2. Select the text you want to mark as Jesus' words
3. Press **Enter** to apply red styling
4. Press **Esc** to exit Style mode
5. Changes are automatically saved if a file is loaded

#### Using Media Mode
**New in v0.5:** Display sermon slides/images alongside Scripture!

1. Add a `media` array to your passage JSON file (see "Extended format" above)
2. Place your image files (JPG, PNG) in the `passages/` directory
3. During presentation, press **M** to toggle to Media mode
4. Navigate through slides with **Space**, **↓** (forward), or **↑** (backward)
5. Press **M** again to return to Scripture mode
6. The app remembers your position in both Scripture and Media

**Use case:** Perfect for displaying sermon outlines, main points, or illustrations without switching to a separate presentation tool like PowerPoint. Eliminates conflicts between OBS projector mode and other presentation software.

#### Configuration
Edit `config.json` to customize:
```json
{
  "passagesDir": "./passages",  // Path to passage files
  "port": 3000                  // Server port
}
```

The simplicity of this approach makes it easy to use with file sync tools like OneDrive sync. For example, you could point `passagesDir` to your OneDrive folder to sync your setup between the computer where you prepare sermon outlines and the computer where you present them to an audience:
```json
{
  "passagesDir": "/Users/yourname/OneDrive/scripture-passages",
  "port": 3000
}
```

## 🧪 Testing

The repo has **three test surfaces with very different costs.** Know which you're
running before you run it — one of them spends real money.

| Command | Covers | Cost | When |
|---|---|---|---|
| `npm test` | The deterministic slide builder (`scripts/build-deck.js`): reference deck HTML + report goldens, the cardinal-rule build errors, the CLI contract. | Fast, free, offline | Anytime; before committing any change to the builder, schema, songs, or templates. |
| `cd agent && uv run pytest` | Python agent unit tests — gate, dispatcher, SQLite store, Gmail tools, harness. | Fast, free, offline | Anytime; before committing agent changes. |
| `cd agent && uv run pytest -m eval` | End-to-end **evals**: the real model runs `gen_service` against the actual example flowcharts. | **Slow (~8 min) and burns API tokens; needs subscription auth.** | Deliberately, after changing the `gen_service` skill or the batch contract. Not part of a routine test run. |

A few things worth keeping straight:

- **The evals are opt-in and do not run by default.** `uv run pytest` excludes
  them (`-m "not eval"` in `agent/pyproject.toml`), so the normal suite stays fast
  and offline. You only pay for the evals when you explicitly pass `-m eval`.
- **`npm run test:update`** re-records the `build-deck.js` golden files *and*
  rebuilds the reference preview (`passages/2026-06-28/`). Run it after an
  intentional change to the renderer or templates, then eyeball the diff — the
  goldens are the thing standing between a code change and a broken slide.
- **Why the tests are shaped this way:** the model's only output is deck JSON and
  everything downstream is deterministic, so the deterministic half is pinned by
  cheap golden tests and the model's *judgment* is what the (expensive) evals
  check. Full rationale in `specs/email-agent.md` §5.1–5.2.

> Note: `npm test` and the evals cover the **service-slide builder and email agent**
> subsystem (see `specs/email-agent.md`). The core Scripture-scrolling app has no
> automated tests; it is verified by hand in the browser.

## ☁️ Infrastructure

Generated decks are published to a public S3 bucket rather than served off the
agent host (see `specs/deck-publishing.md`). That bucket and its IAM are
**managed by Terraform in `infra/`** — don't click it together in the console, or
the next `terraform apply` will fight you.

```bash
cd infra
export AWS_PROFILE=<your-profile>   # the S3 backend needs this too, not just the provider
terraform plan
```

What it creates:

- **`cbc-wilm-agent-public`** — the deck bucket, configured as a static website.
  ACLs are disabled (`BucketOwnerEnforced`); public read comes from a **bucket
  policy** granting anonymous `s3:GetObject`. Consequence worth knowing: uploads
  must **not** pass `--acl public-read`, which now hard-fails. Objects are public
  by virtue of the policy alone.
- **`cbc-wilm-agent-publisher`** — an IAM policy scoped to this one bucket:
  `ListBucket`, `GetObject`, `PutObject`. No `DeleteObject`, so an unattended run
  that goes wrong can't unmake past services. Add it if pruning is ever needed.
- **`cbc-wilm-agent`** — a dedicated IAM user with that policy attached
  directly, so the agent can be revoked and audited apart from any human.
- **CORS** (`GET`/`HEAD`, any origin) so a deck rendered *outside* the bucket —
  a local preview built with `--asset-base` pointing at S3 — can load template
  images without tainting the html2canvas canvas and breaking Export. Decks
  served from the bucket are same-origin and don't need it.

The deck URL is currently **`http://`**: S3 static website endpoints don't
support HTTPS. Fine for slide media; see `bs-a4a` if that ever needs to change.

`terraform output` gives you the website endpoint (feed it to `build-deck.js` as
the media asset base) and the user name.

### Access keys are created by hand — on purpose

**Terraform does not manage the agent's access key**, and shouldn't: an
`aws_iam_access_key` resource writes the secret into the state file, where it
would live forever. So after `terraform apply`:

1. Create an access key for the `cbc-wilm-agent` user in the IAM console.
2. Put it **only** in the agent host's environment (systemd `EnvironmentFile`,
   `0600`, root-owned — not a `.env` in this repo).
3. Verify with `aws sts get-caller-identity` that you get `cbc-wilm-agent` back
   and not some other identity.

The plan showing a user with no key is correct, not half-finished — Terraform
doesn't track keys and won't report drift on one.

Why a user with a key instead of a role: the agent runs on a self-hosted always-on
box (`specs/email-agent.md` §4.6), so there's no EC2 instance profile to source
temporary credentials from, and a user-assumes-role hop would add a trust policy
without shrinking the blast radius. The scoping of `cbc-wilm-agent-publisher` is
what limits the damage — worst case on a leak is read/write of slide media.

## 🔧 Development Roadmap

| Milestone | Status | Description |
|-----------|--------|-------------|
| **v0.1 – Prototype** | ✅ **Complete** | Working demo with intelligent smooth scrolling, sticky headers, gradient fade, and bookmark mode. |
| **v0.2 – In-App Editing** | ✅ **Complete** | Edit mode for text/passage management, Style mode for red-letter text, light/dark theme toggle. |
| **v0.3 – Persistence** | ✅ **Complete** | Node.js server with file browser, load/save JSON files, auto-save on edit, OneDrive sync support. |
| **v0.4 – Visual Polish** | ✅ **Complete** | Enhanced light mode with authentic Bible page aesthetic: warm cream paper texture, subtle gutter shadow, and red page edge detail. |
| **v0.5 – Media Integration** | ✅ **Complete** | Media mode for displaying sermon slides/images, smooth crossfade transitions, hardware-accelerated scrolling with `requestAnimationFrame`. |
| **v0.6 – Enhanced Navigation** | 🔄 Next | Jump to specific passages, search, and keyboard shortcuts reference. |
| **v0.7 – Presentation Controls** | 🔄 Planned | Optional remote control via web socket for tablet/phone. |
| **v1.0 – Release** | 🔄 Planned | Production-ready for live service projection. |

## 🧰 Technical Stack

**Current Implementation:**
- **Backend:** Node.js + Express server for file management
- **Frontend:** HTML5 + CSS3 + Vanilla JavaScript (no build tools)
- **Animations:**
  - Hardware-accelerated smooth scrolling using `requestAnimationFrame` for 60fps+ performance
  - Native `scrollIntoView()` for passage-to-passage transitions
  - CSS transitions for crossfade effects (1.2s duration)
- **Media Support:** Full-screen image display with crossfade transitions between Scripture and Media modes
- **Data Source:** JSON files loaded via REST API, auto-saved on edit, supports both Scripture-only and Scripture+Media formats
- **Persistence:** File-based storage with configurable directory (OneDrive sync supported)
- **Typography:** Georgia serif, 4rem size, justified text
- **Themes:** Dark mode (default) and light mode with authentic Bible page aesthetic (warm cream texture, gutter shadow, red page edge)
- **Editing:** Full WYSIWYG editing with contentEditable, passage management with dynamic re-rendering
- **File Browser:** Sidebar UI for loading/managing passage files

**Planned Enhancements:**
- WebSocket server for remote control via tablet/phone
- Optional Bible API integration for dynamic text fetching
- Enhanced navigation (jump to passage, search)
- Keyboard shortcuts reference overlay

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

**Preparation (New in v0.3!):**
1. Create a file `passages/romans-8-1-17.json` with the passage breakdown
2. Or load an existing file and press **E** to enter Edit mode
3. Copy the pastor's passage outline and paste directly into the app
4. Add paragraph breaks, fix formatting as needed
5. Press **S** to mark any words of Jesus in red
6. Press **Esc** to save and return to presentation mode
7. Changes are automatically saved to the file!

**During the Sermon:**
- As the pastor reads, the operator presses **Space** to advance between passages, **Right Arrow** to jump incrementally within a passage, or holds **Down Arrow** to smoothly scroll within the passage (if it's long)
- **Tip:** Use **Right Arrow** on lower-performance computers to avoid jerky smooth scrolling
- The verse reference stays visible at the top for context
- Previous text remains visible but dimmed, maintaining reading continuity
- When transitioning to sermon points, press **M** to switch to Media mode
- Navigate through sermon slides with **Space** or arrow keys
- Press **M** again to return smoothly to Scripture (remembers your place!)
- When the pastor pauses to explain, press **B** to fade the text reverently
- Press **B** again to restore the text and continue reading
- Press **T** to switch between light and dark mode based on lighting conditions

**Result:** The congregation experiences Scripture as a flowing, meditative journey rather than disconnected slide fragments, with seamless integration of sermon visuals—all in one tool.