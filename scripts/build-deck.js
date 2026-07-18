#!/usr/bin/env node
/**
 * build-deck.js — render service-preview.html from a deck JSON file.
 *
 *   node scripts/build-deck.js <deck.json> [--out path/to/service-preview.html]
 *                                          [--report path/to/report.json]
 *                                          [--quiet]
 *
 * The model's job is to emit well-formed deck JSON (schemas/deck.schema.json).
 * THIS script owns everything mechanical:
 *   - sequential slide numbering + zero-padded export names
 *   - background selection (segment type, song type, praise-1/praise-2 alternation)
 *   - seasonal background variants resolved from the deck's date
 *   - automatic <div class="scrim"></div> for the bright backgrounds
 *   - pulling lyrics out of songs/*.md (repeats supported), never inventing them
 *   - splitting an over-long stanza across slides (60px projection floor)
 *   - HTML-escaping every model-supplied string, lyric line breaks -> <br>
 *   - .slide-label preview chrome (outside .slide so html2canvas skips it),
 *     including the amber `unverified` variant
 *
 * Exits 0 on success, 1 on validation failure (with an actionable message
 * naming the offending segment), 2 on usage/IO error.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SONGS_DIR = path.join(ROOT, 'songs');
const SERVICE_BG_DIR = path.join(ROOT, 'templates', 'service');
const TEMPLATE = path.join(ROOT, 'templates', 'service-slides-template.html');
const SLIDES_MARKER = '<!-- SLIDES -->';

// ── Layout constants, grounded in templates/service-slides-template.html ─────
// .slide                 1456 x 816
// .lyric-slide .content  padding: 80px 130px  -> 1196 x 656 content box
// .lyric                 font-size 60px, line-height 1.4
const CONTENT_W = 1196;
const CONTENT_H = 656;
const LINE_HEIGHT_RATIO = 1.4;

// Sizes we may drop to so a long line stays whole. 60px is the design size; 48px
// is the floor the operator set for the back row of the sanctuary. Below that,
// shrinking is the wrong answer and the slide is reported instead.
const FONT_LADDER = [60, 58, 56, 54, 52, 50, 48];
const FONT_FLOOR = FONT_LADDER[FONT_LADDER.length - 1];

const SEASONS = ['winter', 'spring', 'summer', 'fall'];
const SEASON_BY_MONTH = {
  1: 'winter', 2: 'winter', 12: 'winter',
  3: 'spring', 4: 'spring', 5: 'spring',
  6: 'summer', 7: 'summer', 8: 'summer',
  9: 'fall', 10: 'fall', 11: 'fall',
};

// Backgrounds that are bright/busy enough to need a scrim under white text.
const SCRIM_BACKGROUNDS = new Set(['choir.png', 'baptism.png', 'graduation.png']);

const SEGMENT_TYPES = [
  'preshow', 'prelude', 'baptism', 'graduation',
  'welcome', 'song', 'special_music', 'video', 'sermon_transition', 'closing_prayer',
];

// Allowed keys per segment type (beyond the common ones), so a typo like
// "sections" on a special_music segment is caught instead of silently ignored.
const COMMON_KEYS = ['type', 'background', 'scrim'];
const SEGMENT_KEYS = {
  preshow: ['count'],
  prelude: ['song', 'title', 'performer'],
  baptism: ['names', 'text'],
  graduation: ['text'],
  welcome: [],
  song: ['song', 'role', 'sections', 'number', 'title_only', 'font_size'],
  special_music: ['song', 'title', 'performer', 'lyrics', 'font_size'],
  video: ['label'],
  sermon_transition: ['label'],
  closing_prayer: [],
};

// ── Small helpers ───────────────────────────────────────────────────────────

// Text-content escaping. Quotes are deliberately left alone: every string we
// emit lands in element *content*, never in an attribute (the only attribute we
// write is src, built from a filename validated against templates/service/), and
// hymn text is full of apostrophes ("'Tis", "heav'nly") that would otherwise
// turn the HTML source into unreadable &#39; soup.
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

class DeckError extends Error {}

// ── Song library ────────────────────────────────────────────────────────────

/**
 * Parse songs/<slug>.md: YAML-ish frontmatter (flat key: value) + `## Section`
 * headings. HTML comments and blank padding are ignored.
 */
function parseSong(slug, songsDir = SONGS_DIR) {
  const file = path.join(songsDir, `${slug}.md`);
  if (!fs.existsSync(file)) return null;
  const raw = fs.readFileSync(file, 'utf8');

  const meta = {};
  let body = raw;
  const fm = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (fm) {
    for (const line of fm[1].split(/\r?\n/)) {
      const m = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
      if (!m) continue;
      let v = m[2].trim();
      if (v === 'true') v = true;
      else if (v === 'false') v = false;
      else if (v !== '' && /^-?\d+$/.test(v)) v = parseInt(v, 10);
      else if (v === '') v = null;
      meta[m[1]] = v;
    }
    body = fm[2];
  }

  // Strip HTML comments (the VERIFY notes) before section parsing.
  body = body.replace(/<!--[\s\S]*?-->/g, '');

  const sections = [];       // [{ name, lines, placeholder }] — order preserved
  const byName = new Map();  // last-wins lookup by exact heading text
  let current = null;
  for (const line of body.split(/\r?\n/)) {
    const h = line.match(/^##\s+(.*?)\s*$/);
    if (h) {
      current = { name: h[1], lines: [] };
      sections.push(current);
      byName.set(current.name, current);
      continue;
    }
    if (current && line.trim() !== '') current.lines.push(line.trim());
  }

  // The cardinal rule: never emit a slide that could not be shown to the
  // congregation as-is. A song file may carry a stub section
  // ("(paste lyrics here — song identity unconfirmed)"); such a section is
  // NOT lyrics and must never reach a slide.
  for (const s of sections) {
    s.placeholder = s.lines.length > 0 && s.lines.every((l) => PLACEHOLDER_RE.test(l));
    if (!s.lines.length) s.placeholder = true;
  }
  const usable = sections.filter((s) => !s.placeholder);

  return {
    slug,
    file,
    title: meta.title || slug,
    type: meta.type || null,
    number: meta.number != null ? meta.number : null,
    verified: meta.verified === true,
    public_domain: meta.public_domain === true,
    sections,   // every ## section, including placeholders
    usable,     // sections that carry real, projectable lyrics
    byName,
  };
}

// Stub text a song file may carry in place of lyrics.
const PLACEHOLDER_RE = /paste lyrics|lyrics here|unconfirmed|\bTODO\b|placeholder|\bTBD\b/i;

// ── Typography ──────────────────────────────────────────────────────────────
//
// A lyric slide is bound by two INDEPENDENT constraints, and conflating them is
// what produced orphaned words on the wall:
//
//   WIDTH  — one written line too wide for the box. It is NEVER greedily wrapped:
//            that is what strands "glassy sea;" alone on a centered line and makes
//            a congregation stumble. See the ladder below.
//   HEIGHT — too many lines for the box. THAT is what splitting a stanza is for.
//
// THE WIDTH LADDER, in order:
//   1. It fits at 60px          -> render it.
//   2. It carries a caesura (|) -> break there, and STAY at full size. Preferred:
//      a hymn line has a natural mid-point, and breaking at it costs nothing but a
//      line, where shrinking costs 20% of the type across the WHOLE song.
//   3. No caesura               -> shrink the song toward the 48px floor, and tell
//      the operator which line to mark. The deck still builds; it just asks.
//   4. Not even at the floor    -> a hard warning. Never silently wrap.
//
// The division of labour is deliberate: the SCRIPT measures (it can, exactly), the
// MODEL judges where the caesura falls (it can; a mechanical "break at the widest
// gap" rule breaks lines somewhere musically wrong). Marking the caesura in the
// song file makes that judgment durable and reviewable, and keeps the canonical
// metrical line intact — the break is a PROJECTION decision, not a lyric edit.
//
// Widths come from a real glyph table (scripts/optima-metrics.json), not a
// character count. The old `ceil(len / 55)` estimate was a monospace assumption
// applied to a proportional face and was wrong by up to 24% of the box.

const METRICS = JSON.parse(fs.readFileSync(path.join(__dirname, 'optima-metrics.json'), 'utf8'));

/** The caesura marker: a `|` in a song's lyric line marks where it may be broken. */
const CAESURA = '|';

/** The line as sung — one metrical unit, marker removed. */
const lineText = (line) => line.split(CAESURA).map((s) => s.trim()).filter(Boolean).join(' ');

/** The pieces the line may be broken into. One element if it carries no caesura. */
const lineParts = (line) => line.split(CAESURA).map((s) => s.trim()).filter(Boolean);

/** Width of `text` in px at `size`, exactly as the browser will lay it out. */
function textWidth(text, size) {
  let w = 0;
  for (const ch of text) w += METRICS.advances[ch] ?? METRICS.fallback;
  return (w * size) / METRICS.size;
}

const lineHeight = (size) => size * LINE_HEIGHT_RATIO;
const linesPerSlide = (size) => Math.floor(CONTENT_H / lineHeight(size));

const fits = (text, size) => textWidth(text, size) <= CONTENT_W;

/**
 * The lines actually rendered for one written line at `size`, and whether we had
 * to fall back to a greedy wrap (which we never want, and always report).
 */
function renderLine(line, size) {
  const whole = lineText(line);
  if (fits(whole, size)) return { lines: [whole], wrapped: false };

  const parts = lineParts(line);
  if (parts.length > 1 && parts.every((p) => fits(p, size))) {
    return { lines: parts, wrapped: false, broken: true };
  }

  // Nothing else worked: reproduce the browser's greedy wrap so the slide count is
  // still honest, and let the caller raise it.
  const out = [];
  let cur = '';
  for (const word of whole.split(/\s+/)) {
    const trial = cur ? `${cur} ${word}` : word;
    if (fits(trial, size)) cur = trial;
    else { if (cur) out.push(cur); cur = word; }
  }
  if (cur) out.push(cur);
  return { lines: out, wrapped: true };
}

const renderedLines = (lines, size) =>
  lines.reduce((n, l) => n + renderLine(l, size).lines.length, 0);

/**
 * The largest size at which every written line either fits whole or breaks cleanly
 * at its caesura. Null if even the floor cannot manage that.
 *
 * Takes ALL the stanzas of a song at once, deliberately. Fitting each stanza on its
 * own gives the same hymn a different size on every slide (verse 1 at 56px, verse 2
 * at 48px) and the type visibly jumps as the operator advances. One size per song.
 */
function fitSize(stanzas, ladder = FONT_LADDER) {
  const lines = stanzas.flat();
  return ladder.find((size) => lines.every((l) => !renderLine(l, size).wrapped)) ?? null;
}

/** Lines too wide at `size` that carry no caesura — the model should mark these. */
const unmarked = (stanzas, size) =>
  stanzas.flat().filter((l) => !fits(lineText(l), size) && lineParts(l).length === 1);

// A line that ends a sentence/clause is a natural place to break a stanza.
const isNaturalBreak = (line) => /[.;:!?]["'’”]?$/.test(lineText(line));

/**
 * Split one stanza across as many slides as it needs AT A GIVEN SIZE. The size is
 * chosen once per song by fitSize(), so every slide of a hymn matches.
 * Deterministic: same input -> same output, always.
 */
function layoutStanza(lines, size) {
  const max = linesPerSlide(size);
  if (renderedLines(lines, size) <= max) return [lines];

  for (let k = 2; k <= lines.length; k++) {
    const best = partition(lines, k, size);
    if (best && best.maxCost <= max) return best.chunks;
  }
  // A single line taller than the whole box (pathological) — one per slide.
  return lines.map((l) => [l]);
}

/** Exhaustive best k-way contiguous partition (stanzas are tiny; this is fine). */
function partition(lines, k, size) {
  const n = lines.length;
  if (k > n) return null;
  let best = null;

  const walk = (start, remaining, chunks) => {
    if (remaining === 1) {
      const chunk = lines.slice(start);
      consider([...chunks, chunk]);
      return;
    }
    for (let end = start + 1; end <= n - (remaining - 1); end++) {
      walk(end, remaining - 1, [...chunks, lines.slice(start, end)]);
    }
  };

  const consider = (chunks) => {
    const costs = chunks.map((c) => renderedLines(c, size));
    const maxCost = Math.max(...costs);
    const spread = maxCost - Math.min(...costs);
    // penalty: a break that does not follow end-of-clause punctuation
    let penalty = 0;
    let idx = 0;
    for (let i = 0; i < chunks.length - 1; i++) {
      idx += chunks[i].length;
      if (!isNaturalBreak(lines[idx - 1])) penalty++;
    }
    const key = [maxCost, penalty, spread];
    if (!best || cmp(key, best.key) < 0) best = { key, chunks, maxCost };
  };

  const cmp = (a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2];

  walk(0, k, []);
  return best;
}

// ── Validation ──────────────────────────────────────────────────────────────

function validate(deck, deckPath, songsDir = SONGS_DIR) {
  const errors = [];
  const err = (msg) => errors.push(msg);
  const where = (i, seg) => `segment ${i + 1} (${(seg && seg.type) || 'no type'})`;

  if (deck === null || typeof deck !== 'object' || Array.isArray(deck)) {
    throw new DeckError(`${deckPath}: deck must be a JSON object with "date" and "segments".`);
  }
  for (const key of Object.keys(deck)) {
    if (!['date', 'season', 'notes', 'segments'].includes(key)) {
      err(`unknown top-level key "${key}" (expected: date, season, notes, segments)`);
    }
  }
  if (typeof deck.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(deck.date)) {
    err(`"date" is required and must look like "YYYY-MM-DD" (got ${JSON.stringify(deck.date)})`);
  }
  if (deck.season != null && !SEASONS.includes(deck.season)) {
    err(`"season" must be one of ${SEASONS.join('|')} (got ${JSON.stringify(deck.season)})`);
  }
  if (!Array.isArray(deck.segments) || deck.segments.length === 0) {
    err('"segments" is required and must be a non-empty array');
    throw new DeckError(format(errors, deckPath));
  }

  const songs = new Map(); // slug -> parsed song (or null if missing)
  const loadSong = (slug) => {
    if (!songs.has(slug)) songs.set(slug, parseSong(slug, songsDir));
    return songs.get(slug);
  };
  const availableSlugs = () =>
    fs.readdirSync(songsDir).filter((f) => f.endsWith('.md')).map((f) => f.slice(0, -3));

  deck.segments.forEach((seg, i) => {
    if (seg === null || typeof seg !== 'object' || Array.isArray(seg)) {
      err(`segment ${i + 1}: must be an object, got ${JSON.stringify(seg)}`);
      return;
    }
    if (!SEGMENT_TYPES.includes(seg.type)) {
      err(`${where(i, seg)}: unknown segment type ${JSON.stringify(seg.type)} — expected one of ${SEGMENT_TYPES.join(', ')}`);
      return;
    }
    const allowed = new Set([...COMMON_KEYS, ...SEGMENT_KEYS[seg.type]]);
    for (const key of Object.keys(seg)) {
      if (!allowed.has(key)) {
        err(`${where(i, seg)}: unknown field "${key}" — allowed here: ${[...allowed].join(', ')}`);
      }
    }
    if (seg.background != null) {
      if (typeof seg.background !== 'string' || seg.background.includes('/')) {
        err(`${where(i, seg)}: "background" must be a bare filename in templates/service/ (e.g. "praise-2.png")`);
      } else if (!fs.existsSync(path.join(SERVICE_BG_DIR, seg.background))) {
        err(`${where(i, seg)}: background "${seg.background}" does not exist in templates/service/`);
      }
    }
    if (seg.scrim != null && typeof seg.scrim !== 'boolean') {
      err(`${where(i, seg)}: "scrim" must be true or false`);
    }

    switch (seg.type) {
      case 'preshow':
        if (seg.count != null && (!Number.isInteger(seg.count) || seg.count < 1)) {
          err(`${where(i, seg)}: "count" must be a positive integer`);
        }
        break;

      case 'prelude':
      case 'special_music': {
        if (seg.song == null && !seg.title) {
          err(`${where(i, seg)}: needs "song" (a slug in songs/) or "title"`);
        }
        if (seg.song != null) {
          const song = loadSong(seg.song);
          if (!song) {
            err(`${where(i, seg)}: song "${seg.song}" not found — songs/${seg.song}.md does not exist. Available: ${availableSlugs().join(', ')}`);
          }
        }
        if (seg.type === 'special_music' && seg.lyrics != null && !Array.isArray(seg.lyrics)) {
          err(`${where(i, seg)}: "lyrics" must be an array of stanzas (each a string or an array of lines)`);
        }
        break;
      }

      case 'song': {
        if (typeof seg.song !== 'string' || !seg.song) {
          err(`${where(i, seg)}: "song" (a slug in songs/) is required`);
          break;
        }
        const song = loadSong(seg.song);
        if (!song) {
          err(`${where(i, seg)}: song "${seg.song}" not found — songs/${seg.song}.md does not exist. Available: ${availableSlugs().join(', ')}`);
          break;
        }
        if (seg.role != null && !['hymn', 'praise', 'invitation'].includes(seg.role)) {
          err(`${where(i, seg)}: "role" must be hymn|praise|invitation (got ${JSON.stringify(seg.role)})`);
        }
        if (seg.sections != null) {
          if (!Array.isArray(seg.sections) || seg.sections.some((s) => typeof s !== 'string')) {
            err(`${where(i, seg)}: "sections" must be an array of section-heading strings`);
          } else {
            for (const name of seg.sections) {
              const section = song.byName.get(name);
              if (!section) {
                err(`${where(i, seg)}: song "${seg.song}" has no section "${name}" — songs/${seg.song}.md has: ${song.sections.map((s) => s.name).join(', ') || '(no sections — lyrics missing)'}. Never invent lyrics; fix the section name or add them to the song file.`);
              } else if (section.placeholder) {
                err(`${where(i, seg)}: song "${seg.song}" section "${name}" is a placeholder, not lyrics (songs/${seg.song}.md). It must never be projected. Paste the real lyrics into the song file, or use "title_only": true.`);
              }
            }
          }
        }
        if (seg.title_only != null && typeof seg.title_only !== 'boolean') {
          err(`${where(i, seg)}: "title_only" must be true or false`);
        }
        break;
      }

      case 'baptism':
        if (seg.names != null && (!Array.isArray(seg.names) || seg.names.some((s) => typeof s !== 'string'))) {
          err(`${where(i, seg)}: "names" must be an array of strings`);
        }
        break;
    }
  });

  if (errors.length) throw new DeckError(format(errors, deckPath));
  return songs;
}

function format(errors, deckPath) {
  return `Invalid deck: ${deckPath}\n` +
    errors.map((e) => `  ✗ ${e}`).join('\n') +
    `\n\nSee schemas/deck.schema.json. Nothing was written.`;
}

// ── Rendering ───────────────────────────────────────────────────────────────

// Default media root: an absolute path served by Express in local/dev use. The
// publish path (specs/deck-publishing.md) overrides this with a full origin
// (e.g. https://<bucket>/templates/service) via --asset-base / DECK_ASSET_BASE,
// so the emitted <img src> are absolute and resolve wherever the deck is opened
// — a bucket root, an email preview, or saved to disk.
const DEFAULT_ASSET_BASE = '/templates/service';

function build(deck, deckPath, options = {}) {
  // `songsDir` exists for tests: a cardinal-rule test needs a song file shaped a
  // particular way (a placeholder section, say), and reaching into the real
  // songs/ for that couples the renderer's tests to the church's actual library
  // — editing a hymn then breaks an unrelated build test. Production never sets it.
  const songs = validate(deck, deckPath, options.songsDir ?? SONGS_DIR);

  // Trailing slashes are stripped so `${assetBase}/${file}` is always clean. The
  // default reproduces the historical `/templates/service/<file>` byte-for-byte.
  const assetBase = String(options.assetBase ?? DEFAULT_ASSET_BASE).replace(/\/+$/, '');
  const bg = (file) => `${assetBase}/${file}`;

  // When the backgrounds load cross-origin — an absolute asset base, i.e. the
  // hosted case — the <img> must opt into CORS with crossorigin="anonymous", or
  // html2canvas taints the export canvas and canvas.toBlob() throws a
  // SecurityError while the slides still look correct. The bucket's CORS headers
  // (infra/s3.tf) are the other, necessary-but-not-sufficient half. A same-origin
  // base (the default relative path) needs nothing, so the attribute — and the
  // default golden — stay untouched.
  const crossOrigin = /^[a-z][a-z0-9+.-]*:\/\//i.test(assetBase) || assetBase.startsWith('//');
  const bgAttrs = crossOrigin ? ' crossorigin="anonymous"' : '';

  const month = parseInt(deck.date.slice(5, 7), 10);
  const season = deck.season || SEASON_BY_MONTH[month];
  if (!season) throw new DeckError(`${deckPath}: cannot derive a season from date "${deck.date}"`);

  const report = {
    date: deck.date,
    season,
    season_source: deck.season ? 'explicit' : 'derived-from-date',
    slides: 0,
    segments: [],
    songs: [],
    unverified: [],
    splits: [],
    typography: [],
    missing: [],
    warnings: [],
  };
  if (deck.notes) report.notes = deck.notes;

  const html = [];
  let n = 0;               // slide counter, 1-based
  let praiseIndex = 0;     // praise-1 / praise-2 alternation across the deck
  const songsSeen = new Map();

  const slide = ({ label, unverified, classes, background, scrim, inner }) => {
    n += 1;
    const labelClass = unverified ? 'slide-label unverified' : 'slide-label';
    const labelText = `Slide ${n} — ${label}${unverified ? ' (VERIFY)' : ''}`;
    const useScrim = scrim != null ? scrim : SCRIM_BACKGROUNDS.has(background);
    const body = [`  <img class="bg"${bgAttrs} src="${bg(background)}" alt="">`];
    if (useScrim) body.push('  <div class="scrim"></div>');
    if (inner) body.push(...inner);
    html.push(`<div class="${labelClass}">${escapeHtml(labelText)}</div>`);
    html.push(`<div class="slide ${classes}">`, ...body, '</div>', '');
    return n;
  };

  // `size` is the fitted font size. Only emitted when it differs from the
  // template's 60px, so an untouched slide stays byte-identical to the CSS default.
  const lyricSlide = (label, unverified, background, lines, size) => {
    const style = size && size !== FONT_LADDER[0] ? ` style="font-size: ${size}px"` : '';
    return slide({
      label, unverified, background,
      classes: 'lyric-slide',
      inner: [
        '  <div class="content">',
        `    <div class="lyric"${style}>`,
        '      ' + lines.map(escapeHtml).join('<br>\n      '),
        '    </div>',
        '  </div>',
      ],
    });
  };

  /**
   * Emit every lyric slide for one song, at ONE font size shared across all of
   * them. Records what it had to do to make them fit — a shrink or a forced wrap
   * is exactly the kind of thing the operator used to catch by eye, so it goes in
   * the report rather than happening silently.
   *
   * `stanzas` is [{ name, lines }] in projection order.
   */
  const emitSong = ({ segment, song, slug, stanzas, unverified, background, override }) => {
    const all = stanzas.map((s) => s.lines);
    const size = override ?? fitSize(all) ?? FONT_FLOOR;
    const slides = [];

    for (const { name, lines } of stanzas) {
      const chunks = layoutStanza(lines, size);
      chunks.forEach((chunk, ci) => {
        const suffix = chunks.length > 1 ? ` (${ci + 1}/${chunks.length})` : '';
        // Written lines -> the lines actually painted: a line with a caesura
        // becomes two, and the marker itself never reaches a slide.
        const rendered = chunk.flatMap((l) => renderLine(l, size).lines);
        slides.push(lyricSlide(`${song} · ${name}${suffix}`, unverified, background, rendered, size));
      });
      if (chunks.length > 1) {
        const first = slides[slides.length - chunks.length];
        report.splits.push({
          segment, song, section: name, parts: chunks.length,
          slides: Array.from({ length: chunks.length }, (_, x) => first + x),
          reason: `stanza renders as ${renderedLines(lines, size)} projected lines at ${size}px; ${linesPerSlide(size)} is the most that fits`,
        });
      }
    }

    // Lines we had to break at their caesura. Not a problem — this is the preferred
    // outcome — but the operator should know a line was split, and where.
    const broken = all.flat().filter((l) => renderLine(l, size).broken);
    if (broken.length) {
      report.typography.push({
        segment, song, slides, size, kind: 'caesura',
        lines: broken.map((l) => ({ line: lineText(l), as: lineParts(l) })),
        reason: `${broken.length} line(s) too wide for the slide at ${size}px were broken at the caesura marked in songs/${slug || song}.md, keeping the song at full size.`,
      });
    }

    if (size !== FONT_LADDER[0]) {
      // The lines that FORCED the shrink — measured at full size, which is where
      // they didn't fit. (At the shrunk size they fit by construction.)
      const needMarking = unmarked(all, FONT_LADDER[0]);
      report.typography.push({
        segment, song, slides, size, kind: override ? 'override' : 'shrunk',
        reason: override
          ? `font size ${size}px set explicitly on this segment.`
          : `shrunk from ${FONT_LADDER[0]}px because ${needMarking.length} line(s) are too wide for the slide and carry no caesura marker. One long line costs EVERY verse ${FONT_LADDER[0] - size}px, so marking it is usually the better fix.`,
        ...(override ? {} : {
          fix: `Add a "|" at the caesura of the line(s) below in songs/${slug || song}.md to keep the song at ${FONT_LADDER[0]}px.`,
          unmarked: needMarking.map(lineText),
        }),
      });
    }

    // The floor is the operator's readability limit for the back of the sanctuary,
    // so we do not go below it — which means these lines WILL wrap mid-phrase.
    // That is a judgment call and it belongs to a human, so say so loudly rather
    // than quietly projecting an orphaned word.
    const stillWrapping = all.flat().filter((l) => renderLine(l, size).wrapped);
    if (stillWrapping.length) {
      report.warnings.push(
        `${song}: ${stillWrapping.length} line(s) will WRAP MID-PHRASE — they do not fit at ${size}px and cannot be broken. ` +
        `Mark a caesura with "|" in songs/${slug || song}.md, or set "font_size" on this segment if smaller text is acceptable. ` +
        `Worst: ${JSON.stringify(lineText(stillWrapping[0]))}`
      );
    }
    return slides;
  };

  const titleSlide = (label, unverified, background, title, opts = {}) => {
    const inner = ['  <div class="content">', `    <div class="title">${escapeHtml(title)}</div>`];
    if (opts.performer) inner.push(`    <div class="performer">${escapeHtml(opts.performer)}</div>`);
    inner.push('  </div>');
    if (opts.number != null && opts.number !== '') {
      inner.push(`  <div class="hymn-number"># ${escapeHtml(opts.number)}</div>`);
    }
    return slide({
      label, unverified, background,
      classes: 'song-title-slide',
      scrim: opts.scrim,
      inner,
    });
  };

  const stanzasFromLyrics = (lyrics) =>
    lyrics.map((st) => (Array.isArray(st) ? st : String(st).split(/\r?\n/)).map((l) => l.trim()).filter(Boolean));

  deck.segments.forEach((seg, i) => {
    const first = n + 1;
    const comment = (text) => html.push(`<!-- ── ${text} ── -->`);
    const segScrim = seg.scrim;

    switch (seg.type) {
      case 'preshow': {
        comment('Preshow');
        const background = seg.background || `welcome-text-${season}.png`;
        for (let c = 0; c < (seg.count || 1); c++) {
          slide({ label: 'Preshow', classes: 'plain-slide', background, scrim: segScrim });
        }
        break;
      }

      case 'welcome': {
        comment('Welcome (text · card · text · scripture)');
        const seq = [
          [`welcome-text-${season}.png`, 'Welcome'],
          [`welcome-card-${season}.png`, 'Connection Card'],
          [`welcome-text-${season}.png`, 'Welcome'],
          ['scripture-emphasis.png', 'Scripture Emphasis'],
        ];
        for (const [background, label] of seq) {
          slide({ label, classes: 'plain-slide', background, scrim: segScrim });
        }
        break;
      }

      case 'video': {
        const label = seg.label || 'Video';
        comment(`Video — ${label}`);
        slide({ label, classes: 'plain-slide', background: seg.background || 'black.png', scrim: segScrim });
        break;
      }

      // The screen the congregation looks at while the pastor comes up. Every
      // deck has one. If there's a video it goes here, added outside this deck.
      case 'sermon_transition': {
        const label = seg.label || 'Sermon';
        comment(`Sermon transition — ${label}`);
        slide({ label, classes: 'plain-slide', background: seg.background || 'black.png', scrim: segScrim });
        break;
      }

      case 'closing_prayer': {
        comment('Closing Prayer');
        const seq = [
          ['closing-prayer-text.png', 'Closing Prayer'],
          ['closing-prayer-blank.png', 'Closing Prayer (blank)'],
          [`welcome-blank-${season}.png`, 'Dismissal'],
        ];
        for (const [background, label] of seq) {
          slide({ label, classes: 'plain-slide', background, scrim: segScrim });
        }
        break;
      }

      case 'baptism': {
        comment('Baptism');
        const text = seg.text || (seg.names && seg.names.length ? seg.names.join(' & ') : 'Baptism');
        if (!seg.text && !(seg.names && seg.names.length)) {
          report.missing.push({ segment: i + 1, type: 'baptism', need: 'name(s) of the baptism candidate(s) — slide reads "Baptism"' });
        }
        slide({
          label: `Baptism${seg.text || (seg.names && seg.names.length) ? ` · ${text}` : ''}`,
          classes: 'hero-slide',
          background: seg.background || 'baptism.png',
          scrim: segScrim,
          inner: [`  <div class="hero br">${escapeHtml(text)}</div>`],
        });
        break;
      }

      case 'graduation': {
        comment('Recognition of Graduates');
        const text = seg.text || 'Recognition of Graduates';
        slide({
          label: 'Recognition of Graduates',
          classes: 'hero-slide',
          background: seg.background || 'graduation.png',
          scrim: segScrim,
          inner: [`  <div class="hero">${escapeHtml(text)}</div>`],
        });
        break;
      }

      case 'prelude': {
        const song = seg.song ? songs.get(seg.song) : null;
        const title = seg.title || song.title;
        comment(`Prelude — ${title}`);
        titleSlide(`Prelude · ${title}`, false, seg.background || 'prelude.png', title, {
          performer: seg.performer,
          scrim: segScrim,
        });
        if (song) noteSong(report, songsSeen, song, seg, [], first);
        break;
      }

      case 'special_music': {
        const song = seg.song ? songs.get(seg.song) : null;
        const title = seg.title || song.title;
        comment(`Special Music — ${title}${seg.performer ? ` (${seg.performer})` : ' (performer TBD)'}`);
        const background = seg.background || 'choir.png';
        titleSlide(`Special Music · ${title}`, false, background, title, {
          performer: seg.performer,
          scrim: segScrim,
        });
        if (!seg.performer) {
          report.missing.push({ segment: i + 1, type: 'special_music', title, need: 'performer name (e.g. "Calvary Choir")' });
        }
        if (seg.lyrics) {
          // Operator-supplied only — never from the library.
          emitSong({
            segment: i + 1, song: title, unverified: false, background,
            override: seg.font_size,
            stanzas: stanzasFromLyrics(seg.lyrics).map((lines, si) => ({
              name: `Stanza ${si + 1}`,
              lines,
            })),
          });
        }
        if (song) noteSong(report, songsSeen, song, seg, [], first);
        break;
      }

      case 'song': {
        const song = songs.get(seg.song);
        const role = seg.role || (song.type === 'praise' ? 'praise' : 'hymn');
        const isPraise = role === 'praise';
        let background = seg.background;
        if (!background) {
          if (isPraise) {
            background = `praise-${(praiseIndex % 2) + 1}.png`;
            praiseIndex += 1;
          } else {
            background = 'hymn-1.png';
          }
        } else if (isPraise) {
          praiseIndex += 1;
        }
        const number = seg.number != null ? seg.number : (isPraise ? null : song.number);
        const unverified = !song.verified;

        // Default = every section that carries real lyrics, in file order.
        const names = seg.sections || song.usable.map((s) => s.name);
        const roleLabel = role === 'invitation' ? 'Invitation Hymn' : (isPraise ? 'Praise' : 'Hymn');
        comment(`${roleLabel}${number != null ? ` # ${number}` : ''} — ${song.title}${unverified ? ' — VERIFY' : ''}`);

        titleSlide(`${song.title} · Title`, unverified, background, song.title, {
          number,
          scrim: segScrim,
        });

        const projected = [];
        if (seg.title_only) {
          report.missing.push({
            segment: i + 1, type: 'song', song: song.slug, title: song.title,
            need: 'lyrics — title_only was set, so no lyric slides were generated',
          });
        } else if (!names.length) {
          report.missing.push({
            segment: i + 1, type: 'song', song: song.slug, title: song.title,
            need: `lyrics — songs/${song.slug}.md has no projectable sections (empty or placeholder text), so only the title slide was generated`,
          });
        } else {
          emitSong({
            segment: i + 1, song: song.title, slug: song.slug, unverified, background,
            override: seg.font_size,
            stanzas: names.map((name) => ({ name, lines: song.byName.get(name).lines })),
          });
          projected.push(...names);
        }
        noteSong(report, songsSeen, song, seg, projected, first, { role, background, number });
        break;
      }
    }

    report.segments.push({
      index: i + 1,
      type: seg.type,
      slides: n >= first ? [first, n] : [],
    });
  });

  report.slides = n;
  report.exports = n
    ? `Slide${String(1).padStart(2, '0')}.jpeg … Slide${String(n).padStart(2, '0')}.jpeg`
    : null;
  if (n > 99) {
    report.warnings.push('More than 99 slides: the template zero-pads export names to 2 digits, so they will not sort correctly.');
  }
  for (const s of report.songs) {
    if (!s.verified) report.unverified.push({ song: s.slug, title: s.title, slides: s.slides });
  }

  const template = fs.readFileSync(TEMPLATE, 'utf8');
  if (!template.includes(SLIDES_MARKER)) {
    throw new DeckError(`${TEMPLATE} no longer contains the ${SLIDES_MARKER} marker.`);
  }
  const out = template.replace(SLIDES_MARKER, html.join('\n').trimEnd() + '\n');

  return { html: out, report };
}

function noteSong(report, seen, song, seg, projected, firstSlide, extra = {}) {
  let entry = seen.get(song.slug);
  if (!entry) {
    entry = {
      slug: song.slug,
      title: song.title,
      type: song.type,
      verified: song.verified,
      public_domain: song.public_domain,
      number: extra.number != null ? extra.number : song.number,
      role: extra.role || seg.type,
      background: extra.background || seg.background || null,
      sections: [],
      slides: [],
    };
    seen.set(song.slug, entry);
    report.songs.push(entry);
  }
  entry.sections.push(...projected);
  entry.slides.push(firstSlide);
}

// ── CLI ─────────────────────────────────────────────────────────────────────

function parseArgs(argv) {
  const args = { quiet: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--out' || a === '-o') args.out = argv[++i];
    else if (a === '--asset-base') args.assetBase = argv[++i];
    else if (a === '--report') args.report = argv[++i];
    else if (a === '--quiet' || a === '-q') args.quiet = true;
    else if (a === '--help' || a === '-h') args.help = true;
    else if (a.startsWith('-')) throw new DeckError(`unknown flag "${a}"`);
    else if (!args.deck) args.deck = a;
    else throw new DeckError(`unexpected argument "${a}"`);
  }
  return args;
}

const USAGE = `Usage: node scripts/build-deck.js <deck.json> [--out <file.html>] [--report <file.json>]
                                    [--asset-base <url>] [--quiet]

Renders passages/<date>/service-preview.html from a deck JSON file
(see schemas/deck.schema.json). Prints a JSON report to stdout and writes
it next to the HTML as service-report.json.

--asset-base sets the root the slide backgrounds are loaded from (default
"/templates/service", served by Express). Pass a full origin — e.g.
https://<bucket>/templates/service — to emit absolute image URLs for a hosted
deck. Also settable via the DECK_ASSET_BASE env var; the flag wins.`;

function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (e) {
    console.error(e.message + '\n\n' + USAGE);
    process.exit(2);
  }
  if (args.help || !args.deck) {
    console.log(USAGE);
    process.exit(args.deck ? 0 : 2);
  }

  const deckPath = path.resolve(args.deck);
  let deck;
  try {
    deck = JSON.parse(fs.readFileSync(deckPath, 'utf8'));
  } catch (e) {
    console.error(`Cannot read deck ${deckPath}: ${e.message}`);
    process.exit(e instanceof SyntaxError ? 1 : 2);
  }

  // Flag wins over env; if neither is set, build() falls back to DEFAULT_ASSET_BASE.
  const assetBase = args.assetBase ?? process.env.DECK_ASSET_BASE;

  let result;
  try {
    result = build(deck, deckPath, { assetBase });
  } catch (e) {
    if (e instanceof DeckError) {
      console.error(e.message);
      process.exit(1);
    }
    throw e;
  }

  const outPath = path.resolve(
    args.out || path.join(ROOT, 'passages', deck.date, 'service-preview.html')
  );
  const reportPath = path.resolve(
    args.report || path.join(path.dirname(outPath), 'service-report.json')
  );
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, result.html);

  result.report.deck = path.relative(ROOT, deckPath);
  result.report.output = path.relative(ROOT, outPath);
  result.report.preview_url = `http://localhost:3000/${path.relative(ROOT, outPath).split(path.sep).join('/')}`;

  fs.mkdirSync(path.dirname(reportPath), { recursive: true });
  fs.writeFileSync(reportPath, JSON.stringify(result.report, null, 2) + '\n');
  result.report.report = path.relative(ROOT, reportPath);

  if (!args.quiet) console.log(JSON.stringify(result.report, null, 2));
}

if (require.main === module) main();

module.exports = { build, parseSong, layoutStanza, renderedLines, textWidth, fitSize, escapeHtml, DeckError, FONT_LADDER, FONT_FLOOR, CONTENT_W };
