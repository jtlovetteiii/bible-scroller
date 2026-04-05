# Generate Sermon Slides

---
argument-hint: 2026-03-01 templates/sermon-sunrise-mountains
description: Reads a full sermon outline and generates an HTML slide preview using the specified template. Run this before prep_sermon to create the media slides.
---

Each Sunday, the Pastor prepares a sermon outline. Before running `prep_sermon`, this skill generates an HTML slide preview that can be reviewed, tweaked, and exported to JPEG images. Those images are then picked up automatically by `prep_sermon`.

## Your job

Your job is narrow: **generate only the `<div class="slide">...</div>` elements** (with their `.slide-label` companions). You will splice them into an existing HTML template — you must not regenerate the CSS, the export button, or the JavaScript.

## Input

The argument provides two things:
1. **Date** — e.g. `2026-03-01`. Used to write the output at `passages/YYYY-MM-DD/slides-preview.html`.
2. **Template folder** — e.g. `templates/sermon-sunrise-mountains`. Contains three background images: `title.jpeg`, `main-point.jpeg`, and `sub-point.jpeg`.

**Before reading the outline**, list all files in `outlines/` that match the date (e.g. `outlines/2026-03-01_*.docx`) and ask the user which one to use. The pastor may have multiple variants (full outline, points only, verses only) and the right file changes week to week.

Read the chosen outline using: `pandoc "outlines/FILENAME.docx" -t plain`

## Output

1. Create the folder `passages/YYYY-MM-DD/` if it does not exist.
2. Read `templates/slides-template.html`.
3. Replace the line `<!-- SLIDES -->` with your generated slide HTML.
4. Write the result to `passages/YYYY-MM-DD/slides-preview.html`.
5. Tell the user to open `http://localhost:3000/passages/YYYY-MM-DD/slides-preview.html` to review and export.

Use **server-relative paths** for all background images (e.g. `/templates/sermon-sunrise-mountains/title.jpeg`), so the file works correctly when served by the Express server regardless of folder depth.

---

## Slide types

### 1. Title slide

One per sermon. Use `title.jpeg`.

```html
<div class="slide-label">Slide N — Title</div>
<div class="slide title-slide">
  <img class="bg" src="/TEMPLATE_FOLDER/title.jpeg" alt="">
  <div class="content">
    <div class="series">SERIES TITLE</div>
    <div class="divider"></div>
    <div class="title">SERMON TITLE</div>
    <div class="scripture-ref">PRIMARY SCRIPTURE REF</div>
  </div>
</div>
```

- **Series title**: the overarching series name (e.g. "The New of a New Creation")
- **Sermon title**: the subtitle for this week (e.g. "A New Destination")
- **Scripture ref**: the primary passage for the sermon (e.g. "2 Corinthians 5:1–9")

### 2. Scripture slide (special)

Used for special verses displayed in media mode rather than the scroller — typically an attention-getter at the opening, or a key series verse. Use `main-point.jpeg`.

```html
<div class="slide-label">Slide N — REFERENCE (special)</div>
<div class="slide scripture-slide">
  <img class="bg" src="/TEMPLATE_FOLDER/main-point.jpeg" alt="">
  <div class="content">
    <div class="verse-text">
      LINE ONE<br>
      LINE TWO<br>
      ...
    </div>
  </div>
  <div class="verse-ref">REFERENCE TRANSLATION</div>
</div>
```

Break verse text into natural phrases using `<br>`. Aim for 3–5 lines. The reference (e.g. "Hebrews 9:27–28 NKJV") goes in `.verse-ref`.

When to include a special scripture slide:
- If a verse appears before the series title in the outline, it is almost certainly an opening attention-getter — include it.
- If the outline has a recurring key verse for the series, include it after the title slide. **Ask** if you are unsure whether a verse should be in the scroller or on a special slide.

### 3. Main point slide

One per Roman-numeral main point. Use `main-point.jpeg`.

```html
<div class="slide-label">Slide N — Main Point NUMERAL</div>
<div class="slide main-point-slide">
  <img class="bg" src="/TEMPLATE_FOLDER/main-point.jpeg" alt="">
  <div class="content">
    <div class="qualifier">QUALIFIER PHRASE,</div>
    <div class="statement">CORE STATEMENT.</div>
  </div>
</div>
```

Split the main point into two lines:
- **Qualifier** (lighter weight): a short introductory phrase, e.g. "For the Believer,"
- **Statement** (bold): the core claim, e.g. "Our New Destination is Our Final Destination."

If the statement is long, use `<br>` to break it at a natural phrase boundary.

### 4. Sub-point slide

One or more per lettered sub-point (A, B, C…) and numbered sub-sub-point (1, 2, 3…). Use `sub-point.jpeg`.

```html
<div class="slide-label">Slide N — Sub-point LABEL</div>
<div class="slide sub-point-slide">
  <img class="bg" src="/TEMPLATE_FOLDER/sub-point.jpeg" alt="">
  <div class="content">
    <div class="points">
      <div class="point">POINT TEXT.</div>
    </div>
  </div>
  <div class="section-label">PARENT SECTION NAME</div>
</div>
```

**Section label**: a short (2–4 word) name derived from the parent main point, shown at the bottom-left of every sub-point slide. It stays consistent across all sub-points under the same main point.

**Lettered sub-point header slides** (A, B, C…): do not include the letter prefix. Center the text horizontally and vertically by adding `style="align-items: center; text-align: center;"` to the `.content` div.

```html
<div class="slide sub-point-slide">
  <img class="bg" src="/TEMPLATE_FOLDER/sub-point.jpeg" alt="">
  <div class="content" style="align-items: center; text-align: center;">
    <div class="points">
      <div class="point">The Road of <span class="emphasis">Betrayal</span></div>
    </div>
  </div>
  <div class="section-label">PARENT SECTION NAME</div>
</div>
```

**Text length**: prefer single-line text. Use `<br>` only if the line is genuinely too long to fit (roughly more than ~55 characters).

**Long-point font override**: if a specific point is too long to fit on one line at the default size, apply an inline `style="font-size: Npx"` to just that `.point` div. Apply the same override on every stacked slide that contains that point so the layout stays consistent.

**Emphasis**: wrap the concluding key noun phrase in `<span class="emphasis">`. This is usually:
- The phrase after "through a", "with an", "is a", "is an", etc.
- A mid-sentence capitalized phrase (the pastor's own signal for importance, e.g. "Spiritual Renewal", "Eternal Reward")

Example:
```html
<div class="point">Our Final Destination is reached through a <span class="emphasis">Spiritual Renewal</span>.</div>
```

---

## Stacking (ALWAYS ASK)

When two or more consecutive sub-points are closely related, they may be "stacked": shown one at a time, with each new slide adding the next point beneath the previous ones. Since there are no animations, this means generating multiple slides.

**Always ask the user** whether to stack sub-points before generating. This decision changes week to week depending on how the pastor intends to deliver the content.

**Position stability**: when stacking, each point must occupy the same position across every slide in the sequence. Use `visibility: hidden` (not `display: none`) on unrevealed points — they remain invisible but still take up space, so the layout never shifts as new points appear.

Example of a stacked group of three:
```html
<!-- Slide 1: point 1 visible; 2 & 3 hold space invisibly -->
<div class="slide sub-point-slide">
  <img class="bg" src="/TEMPLATE_FOLDER/sub-point.jpeg" alt="">
  <div class="content">
    <div class="points">
      <div class="point">1. Point one text.</div>
      <div class="point" style="visibility: hidden">2. Point two text with <span class="emphasis">key phrase</span>.</div>
      <div class="point" style="visibility: hidden">3. Point three text.</div>
    </div>
  </div>
  <div class="section-label">SECTION NAME</div>
</div>

<!-- Slide 2: points 1 & 2 visible; 3 holds space invisibly -->
<div class="slide sub-point-slide">
  <img class="bg" src="/TEMPLATE_FOLDER/sub-point.jpeg" alt="">
  <div class="content">
    <div class="points">
      <div class="point">1. Point one text.</div>
      <div class="point">2. Point two text with <span class="emphasis">key phrase</span>.</div>
      <div class="point" style="visibility: hidden">3. Point three text.</div>
    </div>
  </div>
  <div class="section-label">SECTION NAME</div>
</div>

<!-- Slide 3: all points visible -->
<div class="slide sub-point-slide">
  <img class="bg" src="/TEMPLATE_FOLDER/sub-point.jpeg" alt="">
  <div class="content">
    <div class="points">
      <div class="point">1. Point one text.</div>
      <div class="point">2. Point two text with <span class="emphasis">key phrase</span>.</div>
      <div class="point">3. Point three text.</div>
    </div>
  </div>
  <div class="section-label">SECTION NAME</div>
</div>
```

---

## Notes

- Use an en dash (–) not a hyphen (-) in scripture ranges (e.g. "5:1–9").
- Do not strip or alter the pastor's wording. You may trim redundant lead-ins (e.g. "As a New Creation,") when it makes a sub-point slide more readable, but note any changes.
- Special or complex slides (custom images, Greek vocabulary, quotes) are outside this skill's scope. Leave a placeholder comment `<!-- MANUAL SLIDE: description -->` where one would go and tell the user.
- Number slides sequentially from 1.
