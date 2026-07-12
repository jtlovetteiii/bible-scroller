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

const { build, DeckError } = require('../scripts/build-deck.js');

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
// The golden is the SCRIPT's output, which matches the segment table in
// .claude/commands/gen_service.md. It is byte-identical to the hand-built
// passages/2026-06-28/service-preview.html except for one line: slide 22's
// background. The deck calls "His Name Is Jesus" special_music (-> choir.png);
// the hand-built deck put it on praise-2.png, the congregational-praise
// background. That disagreement is bs-fdn, and it is a question for the
// minister of music, not a bug here. Resolve it there, then re-record.

test('reference deck renders identically to its golden', () => {
  const { html, report } = build(readDeck(REFERENCE_DECK), REFERENCE_DECK);
  matchesGolden('2026-06-28.preview.html', html);
  matchesGolden('2026-06-28.report.json', JSON.stringify(report, null, 2) + '\n');
});

test('reference deck report carries the facts the skill reports back', () => {
  const { report } = build(readDeck(REFERENCE_DECK), REFERENCE_DECK);

  assert.equal(report.slides, 36, 'the hand-built deck is 36 slides');
  assert.equal(report.season, 'summer', 'June -> summer, derived from the date');

  // Every song in the library that is unverified must be named, so the skill
  // can hand the operator a list of what to check before Sunday.
  assert.deepEqual(
    report.unverified.map((u) => u.song).sort(),
    ['his-name-is-jesus', 'o-what-a-savior', 'waymaker', 'worthy-of-worship'],
    'unverified songs are surfaced by slug'
  );

  // Both special-music segments lack a performer: exactly the kind of thing the
  // interactive skill would have ASKED about, and that batch mode must report.
  const performerGaps = report.missing.filter((m) => m.type === 'special_music');
  assert.equal(performerGaps.length, 2);
  for (const gap of performerGaps) assert.match(gap.need, /performer/i);
});

// ── The cardinal rule, enforced by the script rather than the model ──────────
//
// These are the failures batch mode leans on: with no human to catch a bad
// slide, "the build refuses" is the only thing standing between a placeholder
// and the sanctuary wall. Each must name the offending segment.

/** Build a one-segment deck, asserting it fails, and hand back the error. */
function buildErrorFor(segments) {
  const deck = { date: '2026-06-28', segments };
  try {
    build(deck, '<test>');
  } catch (e) {
    assert.ok(e instanceof DeckError, `expected a DeckError, got ${e}`);
    return e;
  }
  assert.fail('expected the build to fail, but it succeeded');
}

test('projecting placeholder text is a build error', () => {
  // his-name-is-jesus.md carries a stub section: "(paste lyrics here — song
  // identity unconfirmed)". Putting that on the sanctuary wall is the worst
  // outcome this project has, so asking for it by name must fail the build.
  const err = buildErrorFor([{ type: 'song', song: 'his-name-is-jesus', sections: ['Verse 1'] }]);
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
    { date: '2026-06-28', segments: [{ type: 'song', song: 'his-name-is-jesus' }] },
    '<test>'
  );

  assert.equal(report.slides, 1, 'the title slide, and no lyric slides');
  const [gap] = report.missing;
  assert.equal(gap.song, 'his-name-is-jesus');
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
  assert.equal(report.slides, 36, 'stdout is the machine-readable report');
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
