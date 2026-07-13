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
// .slide            1456 x 816
// .lyric-slide .content  padding: 80px 130px  -> 1196 x 656 content box
// .lyric            font-size 60px, line-height 1.4 -> 84px per rendered line
// 656 / 84 = 7.8  -> 7 rendered lines is the most that fits without shrinking.
// The CSS comment and gen_service both call 60px at 130px padding the proven
// fit for the longest classic hymn lines (~55 chars), so ~55 chars is one
// rendered line.
const MAX_RENDERED_LINES = 7;
const MAX_CHARS_PER_LINE = 55;

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
  song: ['song', 'role', 'sections', 'number', 'title_only'],
  special_music: ['song', 'title', 'performer', 'lyrics'],
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
function parseSong(slug) {
  const file = path.join(SONGS_DIR, `${slug}.md`);
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

// ── Stanza splitting ────────────────────────────────────────────────────────

const renderedLines = (lines) =>
  lines.reduce((n, l) => n + Math.max(1, Math.ceil(l.length / MAX_CHARS_PER_LINE)), 0);

// A line that ends a sentence/clause is a natural place to break a stanza.
const isNaturalBreak = (line) => /[.;:!?]["'’”]?$/.test(line.trim());

/**
 * Split a stanza into the fewest chunks that each fit MAX_RENDERED_LINES,
 * balancing chunk sizes and preferring breaks after end-of-clause punctuation.
 * Deterministic: same input -> same output, always.
 */
function splitStanza(lines) {
  if (renderedLines(lines) <= MAX_RENDERED_LINES) return [lines];

  const n = lines.length;
  for (let k = 2; k <= n; k++) {
    const best = partition(lines, k);
    if (best && best.maxCost <= MAX_RENDERED_LINES) return best.chunks;
  }
  // Every individual line is longer than a slide (pathological) — one per slide.
  return lines.map((l) => [l]);
}

/** Exhaustive best k-way contiguous partition (stanzas are tiny; this is fine). */
function partition(lines, k) {
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
    const costs = chunks.map(renderedLines);
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

function validate(deck, deckPath) {
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
    if (!songs.has(slug)) songs.set(slug, parseSong(slug));
    return songs.get(slug);
  };
  const availableSlugs = () =>
    fs.readdirSync(SONGS_DIR).filter((f) => f.endsWith('.md')).map((f) => f.slice(0, -3));

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

const bg = (file) => `/templates/service/${file}`;

function build(deck, deckPath) {
  const songs = validate(deck, deckPath);

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
    const body = [`  <img class="bg" src="${bg(background)}" alt="">`];
    if (useScrim) body.push('  <div class="scrim"></div>');
    if (inner) body.push(...inner);
    html.push(`<div class="${labelClass}">${escapeHtml(labelText)}</div>`);
    html.push(`<div class="slide ${classes}">`, ...body, '</div>', '');
    return n;
  };

  const lyricSlide = (label, unverified, background, lines) =>
    slide({
      label, unverified, background,
      classes: 'lyric-slide',
      inner: [
        '  <div class="content">',
        '    <div class="lyric">',
        '      ' + lines.map(escapeHtml).join('<br>\n      '),
        '    </div>',
        '  </div>',
      ],
    });

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
          stanzasFromLyrics(seg.lyrics).forEach((stanza, si) => {
            const chunks = splitStanza(stanza);
            chunks.forEach((chunk, ci) => {
              const suffix = chunks.length > 1 ? ` (${ci + 1}/${chunks.length})` : '';
              const slideNo = lyricSlide(`${title} · Stanza ${si + 1}${suffix}`, false, background, chunk);
              if (chunks.length > 1 && ci === 0) {
                report.splits.push({
                  segment: i + 1, song: title, section: `Stanza ${si + 1}`,
                  parts: chunks.length,
                  slides: Array.from({ length: chunks.length }, (_, x) => slideNo + x),
                  reason: `stanza renders as ${renderedLines(stanza)} projected lines; ${MAX_RENDERED_LINES} is the most that fits at the 60px floor`,
                });
              }
            });
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
          for (const name of names) {
            const section = song.byName.get(name);
            const chunks = splitStanza(section.lines);
            chunks.forEach((chunk, ci) => {
              const suffix = chunks.length > 1 ? ` (${ci + 1}/${chunks.length})` : '';
              const slideNo = lyricSlide(`${song.title} · ${name}${suffix}`, unverified, background, chunk);
              if (chunks.length > 1 && ci === 0) {
                report.splits.push({
                  segment: i + 1, song: song.title, section: name,
                  parts: chunks.length,
                  slides: Array.from({ length: chunks.length }, (_, x) => slideNo + x),
                  reason: `stanza renders as ${renderedLines(section.lines)} projected lines; ${MAX_RENDERED_LINES} is the most that fits at the 60px floor`,
                });
              }
            });
            projected.push(name);
          }
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
    else if (a === '--report') args.report = argv[++i];
    else if (a === '--quiet' || a === '-q') args.quiet = true;
    else if (a === '--help' || a === '-h') args.help = true;
    else if (a.startsWith('-')) throw new DeckError(`unknown flag "${a}"`);
    else if (!args.deck) args.deck = a;
    else throw new DeckError(`unexpected argument "${a}"`);
  }
  return args;
}

const USAGE = `Usage: node scripts/build-deck.js <deck.json> [--out <file.html>] [--report <file.json>] [--quiet]

Renders passages/<date>/service-preview.html from a deck JSON file
(see schemas/deck.schema.json). Prints a JSON report to stdout and writes
it next to the HTML as service-report.json.`;

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

  let result;
  try {
    result = build(deck, deckPath);
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

module.exports = { build, parseSong, splitStanza, renderedLines, escapeHtml, DeckError };
