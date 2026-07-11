# Generate Service Slides

---
argument-hint: 2026-06-28
description: Interactively prompts for the week's order of service — assembled from a fixed set of segments — and generates an HTML slide preview to export as JPEGs for ProPresenter. The sermon is handled separately by gen_slides.
---

Each Sunday is assembled from a fixed menu of **segments** whose *theme* is constant but whose *text* changes weekly. This skill asks for this week's specifics segment by segment, pulls lyrics from the song library (`songs/`), and generates the non-sermon slides. The sermon is produced separately by `gen_slides`; this skill's output is exported to its own image folder that ProPresenter imports alongside the sermon images.

## Your job

Generate only the `<div class="slide">…</div>` elements (with their `.slide-label` companions) and splice them into the template shell. Do not regenerate the CSS, export button, or JavaScript.

## The cardinal rule

**Never generate a slide that could not be shown to the congregation, as-is, right now.** No placeholder text, no "lyrics unconfirmed", no "TODO" on a slide. If you're missing something you need (lyrics for a song, a performer name), either omit that slide entirely or generate only the part you *can* safely show (e.g. a title slide), and **tell the user in chat** exactly what you still need. A status note the operator forgets to remove is a disaster on the sanctuary screen; a clear message in chat is not.

## Input

The argument is the **service date** (e.g. `2026-06-28`), used to write `passages/YYYY-MM-DD/service-preview.html`.

### Season

Several backgrounds come in seasonal variants (`…-{season}.png`, season ∈ `spring|summer|fall|winter`). Infer the season from the date's month (Dec–Feb winter, Mar–May spring, Jun–Aug summer, Sep–Nov fall), state your assumption, and let the user override. Use the chosen season for every `{season}` background in the run.

### Everything else — interactive

There is no plan file. Walk the segments below in order, asking one at a time and waiting for the answer. Skip the "occasional" segments unless the user brings them up — but **do** ask once whether the week has a baptism, graduate recognition, or video. When you've gathered everything, **echo the assembled running order back to the user and let them correct it** before you generate. If a detail is ambiguous (which verses, which arrangement, an unfamiliar title), ask rather than guess.

## Segments

Backgrounds are in `templates/service/`. Use **server-relative** paths (`/templates/service/…`) so the file works when served by Express.

| Segment | Background(s) | Slides |
|---|---|---|
| **Preshow** | `welcome-text-{season}` | 1 plain (default; more only if asked) |
| **Prelude** | `prelude.png` | 1 song-title (title only). Usually a musical number — only add lyric slides if the user explicitly asks. |
| **Baptism** *(occasional)* | `baptism.png` | 1 hero — the name(s) given, else the word `Baptism`, bottom-right |
| **Graduation** *(occasional)* | `graduation.png` | 1 hero — `Recognition of Graduates`, centered |
| **Welcome** | `welcome-text-{season}`, `welcome-card-{season}`, `welcome-text-{season}`, `scripture-emphasis.png` | 4 plain, in that exact order |
| **Hymn / Congregational / Invitation** | hymns & invitation → `hymn-1.png`; praise/congregational → `praise-1.png` (use `praise-2.png` to alternate if there are several) | title slide + one lyric slide per section. The meat of the skill — see Songs below. |
| **Special music** | `choir.png` + scrim | 1 song-title with **title + performer** (e.g. "The Lovette Quartet", "Calvary Choir"). Lyrics only if the user provides them — never from the library. |
| **Video** *(occasional)* | `black.png` | 1 plain per video (usually 1–2) |
| **Sermon** | — | **Skip.** Handled by `gen_slides`. |
| **Closing prayer** | `closing-prayer-text.png`, `closing-prayer-blank.png`, `welcome-blank-{season}` | 3 plain, in that exact order. Always follows the invitation hymn. |

## Slide types

### Plain — baked-in / no-text backgrounds

Emit the background as a bare full-bleed image. Used for every preshow, welcome, scripture-emphasis, video, and closing-prayer slide (their text, if any, is already in the image).

```html
<div class="slide-label">Slide N — Preshow</div>
<div class="slide plain-slide">
  <img class="bg" src="/templates/service/welcome-text-summer.png" alt="">
</div>
```

### Song-title — prelude, special music, and the announce slide of each hymn/praise song

Center holds **only the title**. No author, no kicker.

```html
<div class="slide-label">Slide N — Holy, Holy, Holy · Title</div>
<div class="slide song-title-slide">
  <img class="bg" src="/templates/service/hymn-1.png" alt="">
  <div class="content">
    <div class="title">Holy, Holy, Holy</div>
  </div>
  <div class="hymn-number"># 2</div>
</div>
```

- `.hymn-number` (bottom-left, styled `# NNN`): **hymns and the invitation only.** Omit for prelude and praise songs.
- `.performer` (under the title): **special music only.**

```html
<!-- Special music -->
<div class="slide song-title-slide">
  <img class="bg" src="/templates/service/choir.png" alt="">
  <div class="scrim"></div>
  <div class="content">
    <div class="title">O What a Savior</div>
    <div class="performer">The Lovette Quartet</div>
  </div>
</div>
```

The **choir background is bright and busy** — always add `<div class="scrim"></div>` right after its `<img class="bg">`.

### Lyric — one stanza per slide

```html
<div class="slide-label">Slide N — Holy, Holy, Holy · Verse 1</div>
<div class="slide lyric-slide">
  <img class="bg" src="/templates/service/hymn-1.png" alt="">
  <div class="content">
    <div class="lyric">
      Holy, holy, holy! Lord God Almighty!<br>
      Early in the morning our song shall rise to Thee;<br>
      Holy, holy, holy! merciful and mighty!<br>
      God in three Persons, blessed Trinity!
    </div>
  </div>
</div>
```

- One `<br>` per lyric line.
- **60px is the congregation-projection floor** and the `.lyric` default (60px at 130px side padding) is the proven fit for the longest classic hymn lines (~55 chars). If a stanza would overflow or force text below 60px, **split it across two lyric slides** at a natural break — never shrink past the floor. Flag any stanza you split.

### Hero — baptism, graduation

One large phrase over a photo. Both backgrounds are bright, so the `.hero` style already carries a heavy shadow; also add a `<div class="scrim"></div>`.

```html
<!-- Baptism: name(s) if given, else "Baptism", bottom-right -->
<div class="slide hero-slide">
  <img class="bg" src="/templates/service/baptism.png" alt="">
  <div class="scrim"></div>
  <div class="hero br">Baptism</div>
</div>

<!-- Graduation: centered -->
<div class="slide hero-slide">
  <img class="bg" src="/templates/service/graduation.png" alt="">
  <div class="scrim"></div>
  <div class="hero">Recognition of Graduates</div>
</div>
```

## Songs (`songs/`)

One markdown file per song, slug-named (`amazing-grace.md`), with frontmatter + `## Section` headings. The section headings (`Verse 1`, `Chorus`, `Refrain`, `Bridge`…) are the selection handles a request points at.

```markdown
---
title: Amazing Grace
type: hymn            # hymn | praise | choral
source: https://hymnary.org/hymn/BH1991/330
hymnal: BH1991
number: 330
author: John Newton   # metadata only — never shown on a slide
public_domain: true
verified: true         # false = drafted from memory, must be human-checked
---

## Verse 1
Amazing grace! how sweet the sound
...
```

`type` drives the background (`hymn` → `hymn-1.png` + number; `praise` → `praise-1/2.png`, no number).

### Resolving a song

1. **In the library** → use it. If `verified: false`, keep the unverified flag (below).
2. **Not in the library, public-domain hymn** (clearly PD) → write the lyrics from its hymnary.org page, save the file with `public_domain: true`, `verified: true`.
3. **Not in the library, copyrighted** (modern hymn or praise song) → draft the best-known lyrics, save with `verified: false` and a `<!-- VERIFY … -->` comment. Slides are still generated (drafted lyrics are showable), but flagged.
4. **Not in the library and you don't actually know the lyrics** → do **not** invent them and do **not** emit lyric slides. Generate the title slide only and tell the user you need the lyrics.

> `WebFetch`'s summarizer refuses to reproduce lyric text on copyright grounds, so you cannot rely on it to *return* lyrics. Use it / `WebSearch` only to confirm a song's identity, author, hymnal number, and stanza structure — then supply the text yourself.

### Verse selection

- "verses 1–3" → include `## Verse 1/2/3`. Include a hymn's `## Refrain`/`## Chorus` after each verse if that's how it's sung (ask if unsure).
- "skip the last chorus repeat" and similar → don't encode the rule; author the **exact ordered section sequence** the operator wants, repeats and all.
- No selection given → all sections in file order (the default for the invitation hymn).

## Verification flagging (preview-only)

The `.slide-label` sits **outside** the `.slide`, so html2canvas never exports it — it's operator-only preview chrome. For any slide whose lyrics came from a `verified: false` song, add `unverified` to its label so it shows amber in the preview:

```html
<div class="slide-label unverified">Slide N — Way Maker · Chorus (VERIFY)</div>
```

Never put verification text inside the slide itself (see the cardinal rule).

## Output

1. Create `passages/YYYY-MM-DD/` if it does not exist.
2. Read `templates/service-slides-template.html`.
3. Replace the line `<!-- SLIDES -->` with your generated slide HTML.
4. Write the result to `passages/YYYY-MM-DD/service-preview.html`.
5. Tell the user to open `http://localhost:3000/passages/YYYY-MM-DD/service-preview.html` to review and export. Exported files are zero-padded (`Slide01.jpeg`…) so a full service sorts correctly, and import into ProPresenter ahead of the sermon images.
6. Summarize the running order, **call out every unverified song by name**, and **list anything you still need** (missing lyrics, a performer name, etc.).

## Notes

- Number slides sequentially from 1.
- Use an en dash (–) not a hyphen in ranges.
- Preserve archaic hymn spellings ("'Tis", "wert"); never alter wording.
- Save any new songs you resolve to `songs/` so the library grows.
