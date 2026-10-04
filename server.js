const express = require('express');
const fs = require('fs').promises;
const path = require('path');

const app = express();

// Load configuration
let config;
try {
  config = require('./config.json');
} catch (err) {
  config = {
    passagesDir: './passages',
    port: 3000
  };
}

const PORT = process.env.PORT || config.port;
// Loopback only by default. Set HOST=0.0.0.0 (or "host" in config.json) to
// reach the app from another device, e.g. a tablet on the church network.
const HOST = process.env.HOST || config.host || '127.0.0.1';
const PASSAGES_DIR = process.env.PASSAGES_DIR || config.passagesDir;

// Middleware
app.use(express.json());

// Serve only what the browser needs. The repo root also holds the email
// agent's OAuth token and credentials, so it must never be served wholesale.
for (const file of ['index.html', 'app.js', 'style.css']) {
  app.get(`/${file}`, (req, res) => res.sendFile(path.join(__dirname, file)));
}
app.get('/', (req, res) => res.sendFile(path.join(__dirname, 'index.html')));
app.use('/fonts', express.static(path.join(__dirname, 'fonts')));
// Media images and generated slide previews (scripts/build-deck.js writes
// previews to ./passages/<date>/, and they load backgrounds from /templates/)
app.use('/passages', express.static(path.join(__dirname, 'passages')));
app.use('/templates', express.static(path.join(__dirname, 'templates')));

// API: List all passage files
app.get('/api/passages', async (req, res) => {
  try {
    const files = await fs.readdir(PASSAGES_DIR);
    const jsonFiles = files.filter(f => f.endsWith('.json'));
    res.json({ files: jsonFiles });
  } catch (err) {
    console.error('Error reading passages directory:', err);
    res.status(500).json({ error: 'Failed to read passages directory' });
  }
});

// API: Load specific passage file
app.get('/api/passages/:filename', async (req, res) => {
  try {
    const filename = req.params.filename;

    // Security: prevent directory traversal
    if (filename.includes('..') || filename.includes('/') || filename.includes('\\')) {
      return res.status(400).json({ error: 'Invalid filename' });
    }

    if (!filename.endsWith('.json')) {
      return res.status(400).json({ error: 'File must be a JSON file' });
    }

    const filePath = path.join(PASSAGES_DIR, filename);
    const content = await fs.readFile(filePath, 'utf-8');
    const passages = JSON.parse(content);

    res.json({ filename, passages });
  } catch (err) {
    console.error('Error reading passage file:', err);
    res.status(500).json({ error: 'Failed to read passage file' });
  }
});

// API: Save passage file
app.post('/api/passages/:filename', async (req, res) => {
  try {
    const filename = req.params.filename;

    // Security: prevent directory traversal
    if (filename.includes('..') || filename.includes('/') || filename.includes('\\')) {
      return res.status(400).json({ error: 'Invalid filename' });
    }

    if (!filename.endsWith('.json')) {
      return res.status(400).json({ error: 'File must be a JSON file' });
    }

    const passages = req.body.passages;
    if (!Array.isArray(passages)) {
      return res.status(400).json({ error: 'Passages must be an array' });
    }

    // Extract media array (default to empty array if not provided)
    const media = req.body.media || [];

    // Create file content with both passages and media
    const fileContent = {
      passages,
      media
    };

    const filePath = path.join(PASSAGES_DIR, filename);
    await fs.writeFile(filePath, JSON.stringify(fileContent, null, 2), 'utf-8');

    res.json({ success: true, filename });
  } catch (err) {
    console.error('Error saving passage file:', err);
    res.status(500).json({ error: 'Failed to save passage file' });
  }
});

// Start server
app.listen(PORT, HOST, () => {
  console.log(`Scripture Scroller server running on http://${HOST === '0.0.0.0' ? 'localhost' : HOST}:${PORT}`);
  if (HOST !== '127.0.0.1' && HOST !== 'localhost') {
    console.log(`Listening on ${HOST}: reachable from other devices on the network`);
  }
  console.log(`Passages directory: ${path.resolve(PASSAGES_DIR)}`);
});
