'use strict';
/** Unit tests for scripts/read-outline.js (outline text + image positions). */

const test = require('node:test');
const assert = require('node:assert/strict');
const { parseDocument, parseRels, imageSize } = require('../scripts/read-outline');

const rels = parseRels(`<Relationships>
  <Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.jpeg"/>
  <Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com"/>
</Relationships>`);

const p = inner => `<w:p>${inner}</w:p>`;
const run = t => `<w:r><w:t xml:space="preserve">${t}</w:t></w:r>`;
const drawing = (rid, descr) =>
  `<w:r><w:drawing><wp:inline><wp:docPr id="1" name="Picture 1" descr="${descr}"/>` +
  `<a:graphic><pic:blipFill><a:blip r:embed="${rid}"/></pic:blipFill></a:graphic></wp:inline></w:drawing></w:r>`;

test('parseRels keeps only image relationships', () => {
  assert.deepEqual(rels, { rId5: 'media/image1.jpeg' });
});

test('text, list items and images come out in document order', () => {
  const xml = p(drawing('rId5', 'Built &amp; “Tough”')) +
    p(run('Built for ') + run('Praise')) +
    p('<w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr>' + run('What if,  instead?')) +
    p(run('   '));
  assert.deepEqual(parseDocument(xml, rels), [
    { type: 'image', target: 'media/image1.jpeg', alt: 'Built & “Tough”' },
    { type: 'text', text: 'Built for Praise', list: false },
    { type: 'text', text: 'What if, instead?', list: true },
  ]);
});

test('an image mid-paragraph splits the text around it', () => {
  const blocks = parseDocument(p(run('Before') + drawing('rId5', 'x') + run('After')), rels);
  assert.deepEqual(blocks.map(b => b.type === 'text' ? b.text : '[img]'), ['Before', '[img]', 'After']);
});

test('images with unknown relationship ids are skipped', () => {
  assert.deepEqual(parseDocument(p(drawing('rId404', 'gone')), rels), []);
});

test('imageSize reads PNG and JPEG headers', () => {
  const png = Buffer.alloc(32);
  png.writeUInt32BE(0x89504e47, 0); png.writeUInt32BE(640, 16); png.writeUInt32BE(480, 20);
  assert.deepEqual(imageSize(png), [640, 480]);

  // SOI, APP0 (length 4), SOF0 with height 360, width 480.
  const jpeg = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x04, 0x00, 0x00,
    0xff, 0xc0, 0x00, 0x11, 0x08, 0x01, 0x68, 0x01, 0xe0, 0x03]);
  assert.deepEqual(imageSize(jpeg), [480, 360]);
  assert.equal(imageSize(Buffer.from('not an image')), null);
});
