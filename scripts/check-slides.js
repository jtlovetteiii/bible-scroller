#!/usr/bin/env node
/**
 * check-slides.js — readability check for a sermon slides-preview.html.
 *
 *   node scripts/check-slides.js passages/<date>/slides-preview.html [--out dir]
 *
 * Renders the preview in headless Chrome, through the Express server (the
 * backgrounds use server-relative /templates/ paths), and writes to --out
 * (default: passages/<date>/.check/):
 *   - report.txt        unintended line wraps, overflow, text off the slide
 *   - contact-sheet.png every slide as html2canvas renders it, numbered
 *   - slideN.png        each slide at full size
 *
 * The images come from html2canvas, the same renderer the Export button uses,
 * so they show what the congregation will see, not what Chrome would paint.
 * html2canvas drops some CSS (e.g. filter, backdrop-filter, blend modes).
 *
 * Requires `npm start` to be running (PORT env var, default 3000), and
 * Chrome (CHROME env var, or the standard macOS / Linux locations).
 * Exits 0 if no problems were found, 1 if any were, 2 on usage/IO error.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const PORT = process.env.PORT || 3000;

function usage(msg) {
  if (msg) console.error(`check-slides: ${msg}`);
  console.error('usage: node scripts/check-slides.js passages/<date>/slides-preview.html [--out dir]');
  process.exit(2);
}

function findChrome() {
  const candidates = [
    process.env.CHROME,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
  ].filter(Boolean);
  return candidates.find(p => fs.existsSync(p));
}

// Runs inside the page. Waits for fonts and backgrounds, measures every text
// element, then renders each slide with html2canvas and assembles a contact
// sheet. Results land in <pre id="check-slides-result"> as JSON for --dump-dom.
function inPageCheck() {
  const TEXT = '.title, .series, .scripture-ref, .qualifier, .statement, .verse-text, .verse-ref, .point, .section-label';

  function lineHeight(el) {
    const cs = getComputedStyle(el);
    const lh = parseFloat(cs.lineHeight);
    return Number.isFinite(lh) ? lh : parseFloat(cs.fontSize) * 1.2;
  }

  function measure(slides) {
    const problems = [];
    slides.forEach((slide, i) => {
      const n = i + 1;
      const box = slide.getBoundingClientRect();
      slide.querySelectorAll(TEXT).forEach(el => {
        const text = el.textContent.replace(/\s+/g, ' ').trim();
        const short = text.length > 50 ? text.slice(0, 50) + '…' : text;
        const intended = el.querySelectorAll('br').length + 1;
        const lines = Math.round(el.getBoundingClientRect().height / lineHeight(el));
        if (lines > intended) {
          problems.push(`Slide ${n}: "${short}" wraps to ${lines} lines (expected ${intended}) — shorten, add a <br>, or shrink it`);
        }
        const r = el.getBoundingClientRect();
        if (r.left < box.left || r.right > box.right || r.top < box.top || r.bottom > box.bottom) {
          problems.push(`Slide ${n}: "${short}" extends past the edge of the slide`);
        }
      });
      const content = slide.querySelector('.content');
      if (content && content.scrollHeight > content.clientHeight + 1) {
        problems.push(`Slide ${n}: content is taller than the slide's text area (${content.scrollHeight}px > ${content.clientHeight}px)`);
      }
    });
    return problems;
  }

  async function run() {
    const out = { problems: [], slides: [], sheet: null };
    try {
      await document.fonts.ready;
      await Promise.all([...document.images].map(img => img.complete ? null : new Promise(r => { img.onload = img.onerror = r; })));
      const slides = [...document.querySelectorAll('.slide')];
      out.problems = measure(slides);

      const W = 728, H = 408, COLS = 4, GAP = 8, LABEL = 28;
      const rows = Math.ceil(slides.length / COLS);
      const sheet = document.createElement('canvas');
      sheet.width = COLS * W + (COLS + 1) * GAP;
      sheet.height = rows * (H + LABEL) + (rows + 1) * GAP;
      const ctx = sheet.getContext('2d');
      ctx.fillStyle = '#111';
      ctx.fillRect(0, 0, sheet.width, sheet.height);
      ctx.font = '20px -apple-system, Helvetica, sans-serif';

      for (let i = 0; i < slides.length; i++) {
        const canvas = await html2canvas(slides[i], {
          width: slides[i].offsetWidth,
          height: slides[i].offsetHeight,
          scale: 1,
          useCORS: true,
          logging: false,
        });
        out.slides.push(canvas.toDataURL('image/png'));
        const x = GAP + (i % COLS) * (W + GAP);
        const y = GAP + Math.floor(i / COLS) * (H + LABEL + GAP);
        ctx.fillStyle = '#ccc';
        ctx.fillText(`Slide ${i + 1}`, x, y + 20);
        ctx.drawImage(canvas, x, y + LABEL, W, H);
      }
      out.sheet = sheet.toDataURL('image/png');
    } catch (err) {
      out.error = String(err && err.stack || err);
    }
    const pre = document.createElement('pre');
    pre.id = 'check-slides-result';
    pre.textContent = JSON.stringify(out);
    document.body.appendChild(pre);
  }

  window.addEventListener('load', run);
}

function main() {
  const args = process.argv.slice(2);
  const preview = args.find(a => !a.startsWith('--'));
  if (!preview) usage();
  const absPreview = path.resolve(preview);
  if (!fs.existsSync(absPreview)) usage(`no such file: ${preview}`);
  const rel = path.relative(ROOT, absPreview);
  if (!rel.startsWith(`passages${path.sep}`)) usage('the preview must live under passages/ so the server can serve it');

  const outIdx = args.indexOf('--out');
  const outDir = outIdx >= 0 ? path.resolve(args[outIdx + 1] || usage('--out needs a directory'))
    : path.join(path.dirname(absPreview), '.check');

  const chrome = findChrome();
  if (!chrome) usage('Chrome not found; set CHROME to its executable');

  // A sibling copy with the check script injected, so relative paths resolve
  // (no leading dot: express.static refuses to serve dotfiles)
  // exactly as they do for the real preview.
  const html = fs.readFileSync(absPreview, 'utf8');
  if (!html.includes('</body>')) usage('preview has no </body>');
  const probe = path.join(path.dirname(absPreview), '_check-slides-probe.html');
  fs.writeFileSync(probe, html.replace('</body>', `<script>(${inPageCheck})();</script>\n</body>`));

  let dom;
  try {
    const url = `http://localhost:${PORT}/${path.relative(ROOT, probe).split(path.sep).join('/')}`;
    dom = execFileSync(chrome, [
      '--headless=new', '--disable-gpu', '--hide-scrollbars',
      '--window-size=1600,1000', '--virtual-time-budget=120000',
      '--dump-dom', url,
    ], { maxBuffer: 512 * 1024 * 1024, stdio: ['ignore', 'pipe', 'ignore'] }).toString();
  } finally {
    fs.unlinkSync(probe);
  }

  const m = dom.match(/<pre id="check-slides-result">([\s\S]*?)<\/pre>/);
  if (!m) {
    console.error(`check-slides: no result from the page — is the server running on port ${PORT} (npm start)?`);
    process.exit(2);
  }
  const unescape = s => s.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
  const result = JSON.parse(unescape(m[1]));
  if (result.error) {
    console.error(`check-slides: in-page error: ${result.error}`);
    process.exit(2);
  }

  fs.mkdirSync(outDir, { recursive: true });
  const png = dataUrl => Buffer.from(dataUrl.split(',')[1], 'base64');
  result.slides.forEach((d, i) => fs.writeFileSync(path.join(outDir, `slide${i + 1}.png`), png(d)));
  fs.writeFileSync(path.join(outDir, 'contact-sheet.png'), png(result.sheet));

  const report = result.problems.length
    ? result.problems.join('\n')
    : `No wrap or overflow problems in ${result.slides.length} slides.`;
  fs.writeFileSync(path.join(outDir, 'report.txt'), report + '\n');

  console.log(report);
  console.log(`\nContact sheet: ${path.relative(process.cwd(), path.join(outDir, 'contact-sheet.png'))}`);
  console.log(`Per-slide images: ${path.relative(process.cwd(), outDir)}/slideN.png`);
  process.exit(result.problems.length ? 1 : 0);
}

main();
