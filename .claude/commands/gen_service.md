# Generate Service Slides

---
argument-hint: 2026-06-28
description: Interactively prompts for the week's order of service — assembled from a fixed set of segments — writes a deck JSON file, and runs scripts/build-deck.js to render the HTML slide preview to export as JPEGs for ProPresenter. The sermon is handled separately by gen_slides.
---

Each Sunday is assembled from a fixed menu of **segments** whose *theme* is constant but whose *text* changes weekly. This skill asks for this week's specifics segment by segment and writes a **deck JSON** file describing the running order. A deterministic build script (`scripts/build-deck.js`) turns that JSON into the slide HTML. The sermon is produced separately by `gen_slides`; this skill's output is exported to its own image folder that ProPresenter imports alongside the sermon images.

## Your job

**Emit data, not HTML.** Your entire output is a deck JSON file conforming to `schemas/deck.schema.json`, plus the command that builds it. Never hand-write slide markup, never edit `templates/service-slides-template.html`, never touch the generated `service-preview.html`.

The script — not you — owns everything mechanical:

- slide numbering and zero-padded export names
- background selection (per segment, per song `type`, praise-1/praise-2 alternation)
- seasonal background variants
- the `<div class="scrim">` on bright backgrounds
- pulling lyric text out of `songs/*.md` (repeats included)
- **typography**: measuring each line against the slide with real glyph widths, shrinking a song's font (60px → 48px floor) so no line ever wraps mid-phrase, and splitting an over-long stanza across slides
- HTML escaping, `<br>` line breaks, `.slide-label` preview chrome, the amber `unverified` flag

If a slide comes out wrong in a way the deck JSON cannot express, that is a bug in `scripts/build-deck.js` — fix the script, not the output.

### Typography — you do not eyeball this

A hymn line is a unit of metre, so the script **never wraps one**. It measures every line against the 1196px slide with real Optima glyph widths and picks the largest size from 60px down to a 48px floor at which every line of that song stays whole — one size per song, so the type doesn't jump between verses. Slides that fit at 60px are left alone.

Two things reach you:

- **`report.typography`** — every song whose font was shrunk, and why. Worth passing on: *"Holy, Holy, Holy is set at 48px; its longest line is too wide for the slide at full size."*
- **`report.warnings`** — a line that doesn't fit even at the 48px floor. The script will not go below the floor, so that line **will** wrap. This is a judgment call and it is yours to raise: re-break the line in `songs/`, or set `font_size` on the segment if smaller text is acceptable. Say so in your reply; don't let it ship silently.

`font_size` on a `song` or `special_music` segment overrides the fitter. Use it when the automatic call is wrong — not routinely.

## The cardinal rule

**Never generate a slide that could not be shown to the congregation, as-is, right now.** No placeholder text, no "lyrics unconfirmed", no "TODO" on a slide. If you're missing something (lyrics for a song, a performer name), either omit that slide (`"title_only": true` on a song segment) or leave the field out, and **tell the user in chat** exactly what you still need. The build report lists these for you under `missing`.

## Input

The argument is the **service date** (e.g. `2026-06-28`). It sets the deck's `date`, which drives the output path and the season.

### Season

Several backgrounds come in seasonal variants (`…-{season}.png`). The script derives the season from the date (Dec–Feb winter, Mar–May spring, Jun–Aug summer, Sep–Nov fall). State your assumption; if the user overrides it, set `"season"` on the deck.

### Everything else — two modes

**Interactive** (a human is in the chat): there is no plan file. Walk the segments below in order, asking one at a time and waiting for the answer. Skip the "occasional" segments unless the user brings them up — but **do** ask once whether the week has a baptism, graduate recognition, or video. When you've gathered everything, **echo the assembled running order back to the user and let them correct it** before you generate. If a detail is ambiguous (which verses, which arrangement, an unfamiliar title), ask rather than guess.

**Batch** (the whole order of service arrives at once, e.g. emailed by the minister of music): resolve it in a single pass and **never block on a question**. See [Batch mode](#batch-mode) below. Everything else in this document — the segments, the schema, the songs, the cardinal rule — applies unchanged.

## Segments

Each is one object in the deck's `segments` array. The **Background** column is what the script picks — it is here so you know what to expect, not something you set.

| Segment | `type` | Background(s) | Slides |
|---|---|---|---|
| **Preshow** | `preshow` | `welcome-text-{season}` | 1 plain (`"count": n` for more) |
| **Prelude** | `prelude` | `prelude.png` | 1 song-title (title only). Usually a musical number; no lyrics. |
| **Baptism** *(occasional)* | `baptism` | `baptism.png` + scrim | 1 hero, bottom-right — `"names": [...]`, else the word `Baptism` |
| **Graduation** *(occasional)* | `graduation` | `graduation.png` + scrim | 1 hero, centered — `Recognition of Graduates` |
| **Welcome** | `welcome` | `welcome-text/card/text-{season}`, `scripture-emphasis` | 4 plain, in that order |
| **Hymn / Congregational / Invitation** | `song` | from the song's `type`: hymn/invitation → `hymn-1.png` + number; praise → `praise-1/2.png` alternating, no number | title slide + one lyric slide per section. The meat of the skill — see Songs below. |
| **Special music** | `special_music` | `choir.png` + scrim | 1 song-title with **title + performer**. Lyrics only if the user hands them to you (`"lyrics"`), never from the library. |
| **Video** *(occasional)* | `video` | `black.png` | 1 plain per video. An *extra* video slot — the pre-sermon black slide is `sermon_transition`. |
| **Sermon transition** | `sermon_transition` | `black.png` | 1 plain. **Every deck has one**, between the last pre-sermon music and the sermon. |
| **Sermon** | — | — | **Skip.** Handled by `gen_slides`. |
| **Closing prayer** | `closing_prayer` | `closing-prayer-text`, `closing-prayer-blank`, `welcome-blank-{season}` | 3 plain, in that order. Always follows the invitation hymn. |

Read `schemas/deck.schema.json` for the exact fields each segment accepts. `background` and `scrim` exist as per-segment escape hatches — use them only when the user asks for something the defaults don't cover.

## Deck JSON

```json
{
  "date": "2026-06-28",
  "segments": [
    { "type": "preshow" },
    { "type": "prelude", "song": "o-for-a-thousand-tongues-to-sing" },
    { "type": "welcome" },
    { "type": "song", "song": "holy-holy-holy", "sections": ["Verse 1", "Verse 2", "Verse 3"] },
    { "type": "special_music", "song": "o-what-a-savior", "performer": "The Lovette Quartet" },
    { "type": "song", "song": "waymaker" },
    { "type": "song", "song": "i-am-resolved", "role": "invitation" },
    { "type": "closing_prayer" }
  ]
}
```

A song is referenced by **slug** (the `songs/` filename without `.md`) plus an ordered list of `## Section` headings. Repeats are just repeats: `["Verse 1", "Refrain", "Verse 2", "Refrain"]`. Omit `sections` for every section in file order.

`examples/2026-06-28.deck.json` is a complete worked example.

## Songs (`songs/`)

One markdown file per song, slug-named (`amazing-grace.md`), with frontmatter + `## Section` headings.

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

`type` drives the background; `number` the hymn number; `verified: false` makes the script flag every slide of that song amber in the preview and list it under `unverified` in the report.

### Resolving a song

1. **In the library** → reference it by slug.
2. **Not in the library, public-domain hymn** (clearly PD) → write the lyrics from its hymnary.org page, save the file with `public_domain: true`, then reference it. `verified: true` in interactive mode — the operator is right there and will see the slides. **In batch mode, `verified: false`**: nobody has laid eyes on those lyrics, and the amber flag plus the `unverified` report line *is* how you tell him which slides to check before Sunday.
3. **Not in the library, copyrighted** (modern hymn or praise song) → draft the best-known lyrics, save with `verified: false` and a `<!-- VERIFY … -->` comment. Slides are still generated (drafted lyrics are showable), but flagged. **Interactive mode only** — in batch mode there is no one to check them, so skip to 4.
4. **Not in the library and you don't actually know the lyrics** → do **not** invent them. Create the song file with frontmatter and no sections, use `"title_only": true`, and tell the user you need the lyrics. The script refuses to project placeholder text, so a stub section (`(paste lyrics here…)`) is a build error, not a slide.

> `WebFetch`'s summarizer refuses to reproduce lyric text on copyright grounds, so you cannot rely on it to *return* lyrics. Use it / `WebSearch` only to confirm a song's identity, author, hymnal number, and stanza structure — then supply the text yourself.

### Verse selection

- "verses 1–3" → `["Verse 1", "Verse 2", "Verse 3"]`. Include a hymn's `Refrain`/`Chorus` after each verse if that's how it's sung (ask if unsure).
- "skip the last chorus repeat" and similar → don't encode the rule; write out the **exact ordered section sequence** the operator wants, repeats and all.
- No selection given → omit `sections` (all of them, in file order — the default for the invitation hymn).

## Batch mode

The order of service arrives as one input — a "flowchart" emailed by the minister of music. There is no one to ask, so **never block on a question**. You still *have* questions; you just ask them in the reply instead of in a prompt, and his reply comes back to you as another turn. `examples/flowcharts.md` has two real flowcharts with commentary — read it.

### The flowchart is only the music

It lists what is sung, and nothing else. **The rest of the service is implied and you must supply it.** Slot the flowchart's music into this skeleton:

| | Segment | Present |
|---|---|---|
| 1 | `preshow` | always |
| 2 | `prelude` | if the flowchart names one |
| 3 | `welcome` | always |
| 4 | hymns / congregational songs, specials, in flowchart order | from the flowchart |
| 5 | `sermon_transition` | **always** |
| 6 | *sermon* | always — **no slides**, `gen_slides` handles it |
| 7 | invitation `song` | from the flowchart |
| 8 | `closing_prayer` | always |

Occasional segments (baptism, graduation) appear only if the flowchart mentions them. Never ask "is there a baptism this week?" — its absence is the answer.

A `Video` line in the flowchart does **not** add a segment. The video is dropped into ProPresenter later, outside this deck; the `sermon_transition` black slide is its slot. The black slide is in every deck whether or not there's a video.

### Reading the flowchart

It is terse and telegraphic. The vocabulary:

| In the flowchart | Means |
|---|---|
| `Prelude: Heaven on my mind (Penelope Moore)` | `prelude`, `"performer": "Penelope Moore"` |
| `Hymns` *(header)* | the bare titles beneath it are congregational — `song` |
| `Choir: Amazing Love Medley` | `special_music` — a performed number |
| `Quartet` | `special_music` — but see below, this one is **incomplete** |
| `Tehillah: Forever Yahweh` | **congregational** — `song`. Tehillah is the *praise team*, not a performer. The bare titles after it are congregational too. |
| `Invitation: I am resolved` | `song`, `"role": "invitation"` |
| `Video` | nothing — the `sermon_transition` slide already covers it |
| `My country tis of thee 3x` | **`3x` = sing three verses** → `["Verse 1", "Verse 2", "Verse 3"]` |

The `Choir:` / `Quartet` vs `Tehillah:` distinction decides whether the room sings or watches, and it drives the background. Get it right.

### Two kinds of gap, handled differently

You will not have everything you need. What you do about it depends on whether a slide can still be made.

**Blocking — a slide cannot sensibly exist. Do not generate. Reply and ask.**

A `Quartet` line with no song title is the canonical case: special music needs a title *and* a performer, and you have neither. Do not guess a song. You may *suggest* the likely answer — a bare `Quartet` is usually "The Lovette Quartet" — but suggesting is not assuming, and he must confirm. Write no deck; send the question; build when he answers.

**Non-blocking — the deck is still worth having. Generate, and ask alongside.**

Missing lyrics are the canonical case. Emit `"title_only": true`, build the deck, send the link *and* the request for lyrics in the same reply. One unresolved song must never cost him his whole deck.

If a run has both kinds, blocking wins: hold the deck.

### Lyrics you don't have

The [Resolving a song](#resolving-a-song) ladder applies, with one rung removed: **in batch mode, never draft lyrics from memory.** There is no one to catch you. Library first; then look up a public-domain hymn and save it — **always `verified: false`** in batch mode, because no human has read those lyrics yet, and the amber flag plus the `unverified` report line *is* the "I looked these up, please check them" message he needs. Anything you can neither find nor look up: `title_only`, and ask him for the text.

### The deck is a living artifact

`passages/YYYY-MM-DD/service.deck.json` is durable state, not a one-shot render. His replies amend it, sometimes days later — **read the existing deck and edit it; never rebuild from the original email.** Real requests, all of them observed:

- here are the lyrics you asked for → save the song, drop `title_only`, rebuild
- the Star-Spangled Banner should come *before* the Welcome → reorder the segments
- you missed verse 3 of "Tell Me the Story of Jesus" → extend `sections` *and* the song file
- put lyrics on the choir special → `"lyrics"` inline on the `special_music` segment (a performed number does not belong in `songs/`)

Rebuild and reply with the link every time. A deck that changes on Sunday morning is normal.

### The service date

The flowchart often won't state it. Take it from the email; failing that, assume the next Sunday after the email was sent. It sets the output path *and* the season, so **say which date you used** in the reply — a deck built for the wrong Sunday is a silent, total failure.

## Output

1. Write the deck to `passages/YYYY-MM-DD/service.deck.json`.
2. Build it:

   ```bash
   node scripts/build-deck.js passages/YYYY-MM-DD/service.deck.json
   ```

   It writes `passages/YYYY-MM-DD/service-preview.html` (creating the folder) plus `service-report.json`, and prints the report as JSON.
3. **If the build fails**, it names the offending segment. Fix the deck JSON and re-run — never work around it by editing the HTML.
4. Tell the user to open `http://localhost:3000/passages/YYYY-MM-DD/service-preview.html` to review and export. Exported files are zero-padded (`Slide01.jpeg`…) so a full service sorts correctly, and import into ProPresenter ahead of the sermon images.
5. Summarize from the report: the running order, every stanza the script **split**, every **unverified** song by name, and everything under **missing** (lyrics, a performer name, …).

The report is the summary — don't re-derive it. `report.missing` is what to ask for, `report.unverified` is what to flag for checking, `report.splits` is what to warn about. In batch mode that summary is the reply, so the report's contents *are* the questions you send back.

## Notes

- Use an en dash (–) not a hyphen in ranges.
- Preserve archaic hymn spellings ("'Tis", "wert"); never alter wording.
- Save any new songs you resolve to `songs/` so the library grows.
