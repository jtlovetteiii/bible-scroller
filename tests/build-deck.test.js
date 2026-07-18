'use strict';
/**
 * Golden + cardinal-rule tests for scripts/build-deck.js.
 *
 * build-deck.js is the deterministic half of gen_service: the model emits deck
 * JSON, this script renders every slide. That makes it the thing an eval of the
 * skill stands on — if the renderer drifts, a skill eval fails for the wrong
 * reason. So: pin the reference deck's HTML and report byte-for-byte, and pin
 * the build errors that enforce the cardinal rule (never emit a slide that
 * could not be shown to the congregation as-is).
 *
 *   npm test                  # run
 *   npm run test:update       # re-record the goldens after an intended change
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const { build, DeckError, textWidth, CONTENT_W } = require('../scripts/build-deck.js');

const ROOT = path.resolve(__dirname, '..');
const SCRIPT = path.join(ROOT, 'scripts', 'build-deck.js');
const GOLDEN_DIR = path.join(__dirname, 'golden');
const REFERENCE_DECK = path.join(ROOT, 'examples', '2026-06-28.deck.json');

const readDeck = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));

/** Compare `actual` to the recorded golden, or re-record it when UPDATE_GOLDEN=1. */
function matchesGolden(name, actual) {
  const file = path.join(GOLDEN_DIR, name);
  if (process.env.UPDATE_GOLDEN) {
    fs.mkdirSync(GOLDEN_DIR, { recursive: true });
    fs.writeFileSync(file, actual);
    return;
  }
  assert.ok(
    fs.existsSync(file),
    `missing golden ${name} — re-record with UPDATE_GOLDEN=1 node --test tests/`
  );
  assert.equal(actual, fs.readFileSync(file, 'utf8'), `${name} drifted from its golden`);
}

// ── The reference deck ──────────────────────────────────────────────────────
//
// The golden is the script's output for examples/2026-06-28.deck.json. It
// tracks the hand-built passages/2026-06-28/service-preview.html, and now
// deliberately improves on it in two places:
//
//   - slide 22 ("His Name Is Jesus") is congregational praise, not special
//     music (bs-fdn). The hand-built deck had it on the praise background but
//     wearing special music's scrim and label; the script is self-consistent.
//   - slide 23 is the sermon_transition black slide, which every deck gets and
//     the hand-built one was missing.

test('reference deck renders identically to its golden', () => {
  const { html, report } = build(readDeck(REFERENCE_DECK), REFERENCE_DECK);
  matchesGolden('2026-06-28.preview.html', html);
  matchesGolden('2026-06-28.report.json', JSON.stringify(report, null, 2) + '\n');
});

test('reference deck report carries the facts the skill reports back', () => {
  const { report } = build(readDeck(REFERENCE_DECK), REFERENCE_DECK);

  assert.equal(report.slides, 37, '36 hand-built slides + the sermon_transition');
  assert.equal(report.season, 'summer', 'June -> summer, derived from the date');

  // Every deck ends its music with a black slide the congregation looks at
  // while the pastor comes up — video or no video.
  const types = report.segments.map((s) => s.type);
  assert.ok(types.includes('sermon_transition'), 'the deck has a sermon transition');
  assert.equal(
    types.at(-1),
    'closing_prayer',
    'and it comes before the invitation + closing prayer, not at the very end'
  );

  // Every song in the library that is unverified must be named, so the skill
  // can hand the operator a list of what to check before Sunday.
  assert.deepEqual(
    report.unverified.map((u) => u.song).sort(),
    ['his-name-is-jesus', 'o-what-a-savior', 'waymaker', 'worthy-of-worship'],
    'unverified songs are surfaced by slug'
  );

  // The report surfaces both kinds of gap batch mode has to act on, and they
  // get different treatment (see gen_service's non-interactive contract):
  //   - a missing performer BLOCKS: the deck is held and the agent asks first
  //   - missing lyrics DON'T: the title slide ships and the agent asks alongside
  const [performer, lyrics] = report.missing;

  assert.equal(performer.type, 'special_music');
  assert.match(performer.need, /performer/i);

  assert.equal(lyrics.song, 'his-name-is-jesus');
  assert.match(lyrics.need, /lyrics/i);
});

// ── Asset base (bs-tiz.9) ────────────────────────────────────────────────────
//
// Backgrounds load from a configurable root so a hosted deck can point at S3
// (specs/deck-publishing.md). The default must reproduce the historical
// /templates/service/<file> exactly — that byte-identity is what keeps the
// golden above valid — and a full origin must yield absolute URLs.

test('--asset-base re-roots background URLs; default is unchanged', () => {
  const deck = readDeck(REFERENCE_DECK);
  // Tolerant of any extra attributes (crossorigin) between class and src.
  const srcs = (html) => [...html.matchAll(/<img class="bg"[^>]* src="([^"]*)"/g)].map((m) => m[1]);

  // Default: bare absolute paths served by Express, as before.
  const def = srcs(build(deck, REFERENCE_DECK).html);
  assert.ok(def.length > 0, 'the reference deck has background images');
  assert.ok(
    def.every((s) => s.startsWith('/templates/service/')),
    'default emits /templates/service/<file>'
  );

  // A full origin makes every background an absolute URL, filenames intact.
  const base = 'https://cdn.example.com/templates/service';
  const hosted = srcs(build(deck, REFERENCE_DECK, { assetBase: base }).html);
  assert.deepEqual(
    hosted,
    def.map((s) => s.replace(/^\/templates\/service/, base)),
    'each background is re-rooted at the asset base'
  );

  // A trailing slash on the base must not produce a doubled slash.
  const slashed = srcs(build(deck, REFERENCE_DECK, { assetBase: base + '/' }).html);
  assert.deepEqual(slashed, hosted, 'a trailing slash on the base is normalized away');
});

// ── Cross-origin export (bs-517) ─────────────────────────────────────────────
//
// html2canvas rasterizes the background <img> into each exported JPEG. When the
// image is cross-origin (a hosted deck), the element must carry
// crossorigin="anonymous" or the browser never sends Origin, S3's CORS headers
// go unused, the canvas is tainted, and canvas.toBlob() throws. Same-origin (the
// default relative base) must NOT get the attribute — that keeps the golden
// byte-identical and adds nothing the same-origin path needs.

test('crossorigin is emitted only when the asset base is cross-origin', () => {
  const deck = readDeck(REFERENCE_DECK);
  const bgImgs = (html) => [...html.matchAll(/<img class="bg"[^>]*>/g)].map((m) => m[0]);

  // Default (relative) and an explicitly relative base: no crossorigin.
  for (const opts of [undefined, { assetBase: '/some/other/path' }]) {
    const imgs = bgImgs(build(deck, REFERENCE_DECK, opts).html);
    assert.ok(imgs.length > 0);
    assert.ok(
      imgs.every((t) => !t.includes('crossorigin')),
      `same-origin base must not emit crossorigin (opts=${JSON.stringify(opts)})`
    );
  }

  // Absolute bases (https, http, protocol-relative): every bg img opts into CORS.
  for (const base of [
    'https://cbc-wilm-agent-public.s3.us-east-1.amazonaws.com/templates/service',
    'http://cbc-wilm-agent-public.s3-website-us-east-1.amazonaws.com/templates/service',
    '//cdn.example.com/templates/service',
  ]) {
    const imgs = bgImgs(build(deck, REFERENCE_DECK, { assetBase: base }).html);
    assert.ok(
      imgs.every((t) => t.includes('<img class="bg" crossorigin="anonymous" src="')),
      `cross-origin base ${base} must emit crossorigin="anonymous"`
    );
  }
});

// ── Typography ──────────────────────────────────────────────────────────────
//
// The script used to estimate wrapping as ceil(chars / 55) — a monospace
// assumption applied to Optima, a proportional face. It was wrong by up to 24% of
// the box, so hymn lines wrapped mid-phrase and stranded words like "glassy sea;"
// alone on a centered line. Widths now come from a real glyph table.

test('no lyric line ever wraps — every painted line fits its slide', () => {
  const { html } = build(readDeck(REFERENCE_DECK), REFERENCE_DECK);

  for (const [, style, body] of html.matchAll(
    /<div class="lyric"(?:\s+style="font-size:\s*(\d+)px")?>\s*([\s\S]*?)\s*<\/div>/g
  )) {
    const size = Number(style ?? 60);
    for (const line of body.split('<br>').map((l) => l.trim())) {
      assert.ok(
        textWidth(line, size) <= CONTENT_W,
        `"${line}" is ${Math.round(textWidth(line, size))}px at ${size}px — it will wrap in a ${CONTENT_W}px box`
      );
      assert.doesNotMatch(line, /\|/, 'the caesura marker never reaches a slide');
    }
  }
});

test('a marked caesura breaks the line and keeps the song at full size', () => {
  // The preferred fix. "Casting down their golden crowns around the glassy sea;"
  // is 1480px at 60px in a 1196px box. Shrinking to fit it would drag ALL of
  // Holy, Holy, Holy down to 48px — 20% smaller, for one line. Breaking it at the
  // caesura marked in the song file costs one line and nothing else.
  const { report, html } = build(readDeck(REFERENCE_DECK), REFERENCE_DECK);

  const holy = report.typography.find((t) => t.song.startsWith('Holy'));
  assert.equal(holy.kind, 'caesura');
  assert.equal(holy.size, 60, 'the hymn stays at full size');

  const verse2 = html.match(/Slide 9 —[\s\S]*?<div class="lyric"[^>]*>([\s\S]*?)<\/div>/)[1];
  const painted = verse2.split('<br>').map((l) => l.trim());
  assert.ok(
    painted.includes('Casting down their golden crowns') &&
      painted.includes('around the glassy sea;'),
    `the line broke at its sense-break, not wherever the words ran out: ${painted}`
  );
});

test('an unmarked over-wide line shrinks the song AND names the line to mark', () => {
  // The fallback. The deck still builds — a long line must never block the
  // operator's whole deck — but the report says exactly which line to mark and how,
  // so the fix lands in the song file rather than being rediscovered every week.
  const stub = path.join(ROOT, 'songs', 'zz-test-unmarked.md');
  fs.writeFileSync(
    stub,
    '---\ntitle: Unmarked\ntype: hymn\nverified: true\n---\n\n' +
      '## Verse 1\nCasting down their golden crowns around the glassy sea;\nShort line.\n'
  );

  try {
    const { report } = build(
      { date: '2026-06-28', segments: [{ type: 'song', song: 'zz-test-unmarked' }] },
      '<test>'
    );
    const [t] = report.typography;
    assert.equal(t.kind, 'shrunk');
    assert.equal(t.size, 48, 'shrunk to fit the unmarked line');
    assert.deepEqual(t.unmarked, ['Casting down their golden crowns around the glassy sea;']);
    assert.match(t.fix, /caesura/, 'and it says how to get back to full size');
  } finally {
    fs.rmSync(stub, { force: true });
  }
});

test('a line that fits at no size and cannot be broken is a loud warning', () => {
  // The floor is the operator's readability limit for the back of the sanctuary,
  // so the script will not go below it. This line WILL wrap — say so.
  const stub = path.join(ROOT, 'songs', 'zz-test-toolong.md');
  const tooLong = 'Magnificent'.padEnd(11) + ' magnificent'.repeat(8);
  fs.writeFileSync(stub, `---\ntitle: Too Long\ntype: hymn\nverified: true\n---\n\n## Verse 1\n${tooLong}\n`);

  try {
    const { report } = build(
      { date: '2026-06-28', segments: [{ type: 'song', song: 'zz-test-toolong' }] },
      '<test>'
    );
    assert.equal(report.warnings.length, 1);
    assert.match(report.warnings[0], /WRAP MID-PHRASE/);
    assert.match(report.warnings[0], /caesura|font_size/, 'and it offers both ways out');
  } finally {
    fs.rmSync(stub, { force: true });
  }
});

test('the whole of Holy, Holy, Holy is projectable — verse 4 included', () => {
  // Verse 4's longest line needs 43px, BELOW the 48px floor. Before the caesura
  // mechanism, projecting the complete hymn was simply impossible without a wrap.
  const { report } = build(
    { date: '2026-06-28', segments: [{ type: 'song', song: 'holy-holy-holy' }] },
    '<test>'
  );
  assert.equal(report.warnings.length, 0, 'no line wraps');
  assert.equal(report.typography[0].size, 60, 'and it is still at full size');
});

test('font_size on a segment overrides the fitter', () => {
  const { report, html } = build(
    {
      date: '2026-06-28',
      segments: [{ type: 'song', song: 'holy-holy-holy', sections: ['Verse 1'], font_size: 40 }],
    },
    '<test>'
  );

  assert.match(html, /style="font-size: 40px"/, 'the operator gets the size they asked for');
  assert.equal(report.typography[0].size, 40);
  assert.match(report.typography[0].reason, /explicitly/, 'and the report says it was deliberate');
});

// ── The cardinal rule, enforced by the script rather than the model ──────────
//
// These are the failures batch mode leans on: with no human to catch a bad
// slide, "the build refuses" is the only thing standing between a placeholder
// and the sanctuary wall. Each must name the offending segment.

// Songs shaped for these tests specifically. They used to reuse real library
// files, which meant editing a hymn could break a renderer test for reasons that
// had nothing to do with the renderer — and did, when his-name-is-jesus.md lost
// its placeholder section (bs-b8d). The library is the church's data; fixtures
// are ours.
const FIXTURE_SONGS = path.join(__dirname, 'fixtures', 'songs');

/** Build a one-segment deck, asserting it fails, and hand back the error. */
function buildErrorFor(segments, options = {}) {
  const deck = { date: '2026-06-28', segments };
  try {
    build(deck, '<test>', options);
  } catch (e) {
    assert.ok(e instanceof DeckError, `expected a DeckError, got ${e}`);
    return e;
  }
  assert.fail('expected the build to fail, but it succeeded');
}

test('projecting placeholder text is a build error', () => {
  // stub-song.md carries a section whose only content is a placeholder. Putting
  // that on the sanctuary wall is the worst outcome this project has, so asking
  // for it by name must fail the build rather than render it.
  const err = buildErrorFor(
    [{ type: 'song', song: 'stub-song', sections: ['Verse 1'] }],
    { songsDir: FIXTURE_SONGS }
  );
  assert.match(err.message, /segment 1/, 'names the offending segment');
  assert.match(err.message, /placeholder/i, 'says why');
});

test('a song with no lyrics at all degrades to a title slide + a missing line', () => {
  // The distinction that makes batch mode possible. Asking to project a
  // placeholder is an ERROR (above); a song the library simply has no lyrics
  // for is a title slide plus a report line requesting them. The deck still
  // builds, so one unresolved song cannot cost the operator his whole service —
  // it just comes back as a question in the report instead of a blocking prompt.
  const { report } = build(
    { date: '2026-06-28', segments: [{ type: 'song', song: 'empty-song' }] },
    '<test>',
    { songsDir: FIXTURE_SONGS }
  );

  assert.equal(report.slides, 1, 'the title slide, and no lyric slides');
  const [gap] = report.missing;
  assert.equal(gap.song, 'empty-song');
  assert.match(gap.need, /lyrics/i, 'the report asks for what it needs');
});

test('an unknown song is a build error', () => {
  const err = buildErrorFor([{ type: 'song', song: 'not-a-real-song' }]);
  assert.match(err.message, /segment 1/);
  assert.match(err.message, /not-a-real-song/, 'names the song it could not find');
});

test('an unknown section is a build error that lists the real ones', () => {
  const err = buildErrorFor([
    { type: 'song', song: 'holy-holy-holy', sections: ['Verse 1', 'Verse 9'] },
  ]);
  assert.match(err.message, /segment 1/);
  assert.match(err.message, /Verse 9/, 'names the section it could not find');
  assert.match(err.message, /Verse 1/, 'lists the sections the song actually has');
});

// ── CLI contract ────────────────────────────────────────────────────────────
//
// The skill shells out to this script and branches on its exit code, so the
// codes are part of the contract: 0 ok, 1 validation failure, 2 usage/IO.

function runCli(args, opts = {}) {
  try {
    const stdout = execFileSync('node', [SCRIPT, ...args], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
      ...opts,
    });
    return { code: 0, stdout, stderr: '' };
  } catch (e) {
    return { code: e.status, stdout: e.stdout || '', stderr: e.stderr || '' };
  }
}

test('CLI exits 0 and prints the report as JSON on stdout', (t) => {
  const tmp = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'deck-'));
  t.after(() => fs.rmSync(tmp, { recursive: true, force: true }));

  const out = path.join(tmp, 'service-preview.html');
  const { code, stdout } = runCli([REFERENCE_DECK, '--out', out]);

  assert.equal(code, 0);
  const report = JSON.parse(stdout);
  assert.equal(report.slides, 37, 'stdout is the machine-readable report');
  assert.ok(fs.existsSync(out), 'writes the preview HTML');
  assert.ok(
    fs.existsSync(path.join(tmp, 'service-report.json')),
    'writes service-report.json next to the HTML'
  );
});

test('CLI exits 1 on a deck the model got wrong', (t) => {
  const tmp = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'deck-'));
  t.after(() => fs.rmSync(tmp, { recursive: true, force: true }));

  const bad = path.join(tmp, 'bad.deck.json');
  fs.writeFileSync(
    bad,
    JSON.stringify({ date: '2026-06-28', segments: [{ type: 'song', song: 'not-a-real-song' }] })
  );

  const { code, stderr } = runCli([bad, '--out', path.join(tmp, 'out.html')]);
  assert.equal(code, 1, 'validation failure is exit 1');
  assert.match(stderr, /not-a-real-song/, 'the error reaches stderr for the agent to read');
});

test('CLI exits 2 when called wrong', () => {
  assert.equal(runCli([]).code, 2, 'no deck argument');
  assert.equal(runCli([REFERENCE_DECK, '--nope']).code, 2, 'unknown flag');
});
