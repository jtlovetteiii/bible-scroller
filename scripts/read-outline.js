#!/usr/bin/env node
'use strict';
/**
 * Read a sermon outline (.docx) for gen_slides: its text, in order, with a
 * marker wherever the pastor placed an image. No pandoc needed.
 *
 *   node scripts/read-outline.js outlines/2026-11-15_outline.docx
 *   node scripts/read-outline.js outlines/2026-11-15_outline.docx --media passages/2026-11-15/illustrations
 *
 * Output: one line per paragraph. List items (Word numbering, e.g. the
 * pastor's "What if…" questions) are prefixed "• ". Each embedded image
 * becomes a line like
 *
 *   [IMAGE 1] illustrations/illustration1.jpeg  1191x670  "alt text from Word"
 *
 * at the point it appears. With --media DIR the images are written there as
 * illustration1.jpeg, illustration2.png… in document order. Keep DIR in a
 * subfolder (illustrations/), not the passage folder itself: prep_sermon
 * treats every image directly in passages/<date>/ as a deck slide.
 */

const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const decode = s => s
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
  .replace(/&apos;/g, "'").replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(+n))
  .replace(/&amp;/g, '&');

/** rels XML → { rId: 'media/image1.jpeg' } for image relationships. */
function parseRels(xml) {
  const map = {};
  for (const m of xml.matchAll(/<Relationship\b[^>]*>/g)) {
    const id = (m[0].match(/\bId="([^"]+)"/) || [])[1];
    const target = (m[0].match(/\bTarget="([^"]+)"/) || [])[1];
    if (id && target && /relationships\/image"/.test(m[0])) map[id] = target;
  }
  return map;
}

/**
 * document.xml + rels → ordered blocks:
 *   { type: 'text', text, list }  |  { type: 'image', target, alt }
 */
function parseDocument(xml, rels) {
  const blocks = [];
  for (const p of xml.matchAll(/<w:p[ >][\s\S]*?<\/w:p>/g)) {
    const body = p[0];
    // Walk runs in order so text and images keep their relative position.
    let text = '';
    const flush = () => {
      const t = text.replace(/[ \t]+/g, ' ').trim();
      if (t) blocks.push({ type: 'text', text: t, list: /<w:numPr>/.test(body) });
      text = '';
    };
    for (const tok of body.matchAll(/<w:t(?:\s[^>]*)?>([^<]*)<\/w:t>|<w:tab\/>|<w:br\/>|<w:drawing>[\s\S]*?<\/w:drawing>|<w:pict>[\s\S]*?<\/w:pict>/g)) {
      const s = tok[0];
      if (s.startsWith('<w:t')) text += decode(tok[1] || '');
      else if (s === '<w:tab/>' || s === '<w:br/>') text += ' ';
      else {
        const rid = (s.match(/r:(?:embed|id)="([^"]+)"/) || [])[1];
        if (!rid || !rels[rid]) continue;
        flush();
        const alt = decode((s.match(/\bdescr="([^"]*)"/) || s.match(/<wp:docPr\b[^>]*\bname="([^"]*)"/) || [])[1] || '');
        blocks.push({ type: 'image', target: rels[rid], alt });
      }
    }
    flush();
  }
  return blocks;
}

/** Pixel size from a PNG/JPEG/GIF header, or null. */
function imageSize(buf) {
  if (buf.length > 24 && buf.readUInt32BE(0) === 0x89504e47) return [buf.readUInt32BE(16), buf.readUInt32BE(20)];
  if (buf.length > 10 && buf.toString('ascii', 0, 3) === 'GIF') return [buf.readUInt16LE(6), buf.readUInt16LE(8)];
  if (buf[0] === 0xff && buf[1] === 0xd8) {
    let i = 2;
    while (i + 9 < buf.length) {
      if (buf[i] !== 0xff) { i++; continue; }
      const marker = buf[i + 1];
      if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) {
        return [buf.readUInt16BE(i + 7), buf.readUInt16BE(i + 5)];
      }
      i += 2 + buf.readUInt16BE(i + 2);
    }
  }
  return null;
}

function main() {
  const args = process.argv.slice(2);
  const docx = args.find(a => !a.startsWith('--'));
  const mi = args.indexOf('--media');
  const mediaDir = mi >= 0 ? args[mi + 1] : null;
  if (!docx || (mi >= 0 && !mediaDir)) {
    console.error('usage: node scripts/read-outline.js outlines/<file>.docx [--media passages/<date>/illustrations]');
    process.exit(2);
  }
  const unzip = (entry, encoding) => execFileSync('unzip', ['-p', docx, entry], { encoding, maxBuffer: 1 << 28 });
  let relsXml = '';
  try { relsXml = unzip('word/_rels/document.xml.rels', 'utf8'); } catch { /* no images */ }
  const blocks = parseDocument(unzip('word/document.xml', 'utf8'), parseRels(relsXml));

  if (mediaDir) fs.mkdirSync(mediaDir, { recursive: true });
  let n = 0;
  for (const b of blocks) {
    if (b.type === 'text') { console.log((b.list ? '• ' : '') + b.text); continue; }
    n++;
    const name = `illustration${n}${path.extname(b.target).toLowerCase() || '.jpeg'}`;
    const buf = unzip('word/' + b.target.replace(/^\/?word\//, ''), 'buffer');
    const size = imageSize(buf);
    if (mediaDir) fs.writeFileSync(path.join(mediaDir, name), buf);
    const where = mediaDir ? path.join(path.basename(mediaDir), name) : b.target;
    console.log(`[IMAGE ${n}] ${where}  ${size ? size.join('x') : '?x?'}  "${b.alt}"`);
  }
  if (n && !mediaDir) console.error(`\n${n} image(s) in the outline; re-run with --media <dir> to extract them.`);
}

if (require.main === module) main();
module.exports = { parseDocument, parseRels, imageSize };
