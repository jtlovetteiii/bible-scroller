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

  // Every song whose LYRICS are unverified must be named, so the skill can hand
  // the operator a list of what to check before Sunday. Title-only songs are
  // deliberately absent: they projected no text, so there is nothing to check,
  // and `missing` already asks for their words. Listing them in both would
  // double-count every unresolved song and bury the ones that can be acted on.
  assert.deepEqual(
    report.unverified.map((u) => u.song).sort(),
    ['waymaker', 'worthy-of-worship'],
    'unverified names songs with projected lyrics, not title-only ones'
  );
  const titleOnly = report.songs.filter((s) => !s.sections.length).map((s) => s.slug);
  assert.ok(titleOnly.length, 'the reference deck still exercises the title-only path');
  for (const slug of titleOnly) {
    assert.ok(
      !report.unverified.some((u) => u.song === slug),
      `${slug} projected no lyrics, so it must not be reported as unverified`
    );
  }

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
  // Backgrounds are painted as a div's background-image, so the URL lives inside
  // url('…') in the style attribute rather than an <img src>.
  const srcs = (html) =>
    [...html.matchAll(/<div class="bg" style="background-image: url\('([^']*)'\)"/g)].map((m) => m[1]);

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

// ── Backgrounds fill the frame on export (bs-kyp, supersedes bs-517) ──────────
//
// The background is a div with a background-image, NEVER an <img>. html2canvas
// (the exporter) ignores object-fit, so an <img class="bg"> letterboxed every
// non-16:9 background with white margins in the exported JPEG. A div's
// background-size: cover it honors, so the art fills the frame. CORS for the
// hosted case now rides on html2canvas's useCORS:true (set in the template),
// which re-fetches each background with crossOrigin="anonymous" — so no deck
// carries a per-element crossorigin attribute anymore.

test('every background is a cover-filled div, never an <img> that would letterbox', () => {
  const deck = readDeck(REFERENCE_DECK);

  for (const base of [
    undefined,
    { assetBase: '/some/other/path' },
    { assetBase: 'https://cbc-wilm-agent-public.s3.us-east-1.amazonaws.com/templates/service' },
  ]) {
    const { html } = build(deck, REFERENCE_DECK, base);
    const divs = [...html.matchAll(/<div class="bg"[^>]*>/g)].map((m) => m[0]);
    assert.ok(divs.length > 0, `the reference deck has backgrounds (base=${JSON.stringify(base)})`);
    assert.ok(
      !/<img class="bg"/.test(html),
      'no background is an <img> — html2canvas would ignore object-fit and letterbox it'
    );
    assert.ok(
      divs.every((d) => d.includes("style=\"background-image: url('")),
      'every background div paints its image via background-image (CSS supplies background-size: cover)'
    );
    assert.ok(
      divs.every((d) => !d.includes('crossorigin')),
      'no per-element crossorigin — the hosted export relies on html2canvas useCORS instead'
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
    const size = Number(style ?? 75);
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
  // The preferred fix. In caesura-full.md every line fits at 75px except
  // "Casting down their golden crowns | around the glassy sea;" — too wide whole,
  // but each half fits. Shrinking to fit it would drag the WHOLE song down;
  // breaking it at its marked caesura costs one line and keeps full size.
  const { report, html } = build(
    { date: '2026-06-28', segments: [{ type: 'song', song: 'caesura-full', sections: ['Verse 1'] }] },
    '<test>',
    { songsDir: FIXTURE_SONGS }
  );

  const [caes] = report.typography;
  assert.equal(caes.kind, 'caesura');
  assert.equal(caes.size, 75, 'the song stays at full size');

  const lyric = html.match(/<div class="lyric"[^>]*>([\s\S]*?)<\/div>/)[1];
  const painted = lyric.split('<br>').map((l) => l.trim());
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
      '## Verse 1\nHere I raise my Ebenezer; hither by Thy help\nShort line.\n'
  );

  try {
    const { report } = build(
      { date: '2026-06-28', segments: [{ type: 'song', song: 'zz-test-unmarked' }] },
      '<test>'
    );
    const [t] = report.typography;
    assert.equal(t.kind, 'shrunk');
    assert.equal(t.size, 60, 'shrunk to the floor to fit the unmarked line');
    assert.deepEqual(t.unmarked, ['Here I raise my Ebenezer; hither by Thy help']);
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
  // At 75px its unmarked lines are too wide, so the hymn shrinks to the 60px
  // floor — the old proven size — where every line either fits or breaks at its
  // marked caesura. The point: the complete hymn projects with no wrap, and the
  // congregation never sees a stranded word.
  const { report } = build(
    { date: '2026-06-28', segments: [{ type: 'song', song: 'holy-holy-holy' }] },
    '<test>'
  );
  assert.equal(report.warnings.length, 0, 'no line wraps');
  assert.equal(report.typography[0].size, 60, 'it settles at the 60px floor');
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
