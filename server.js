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
const PASSAGES_DIR = process.env.PASSAGES_DIR || config.passagesDir;

// Middleware
app.use(express.json());
app.use(express.static('.'));

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

    const filePath = path.join(PASSAGES_DIR, filename);
    await fs.writeFile(filePath, JSON.stringify(passages, null, 2), 'utf-8');

    res.json({ success: true, filename });
  } catch (err) {
    console.error('Error saving passage file:', err);
    res.status(500).json({ error: 'Failed to save passage file' });
  }
});

// Start server
app.listen(PORT, () => {
  console.log(`Scripture Scroller server running on http://localhost:${PORT}`);
  console.log(`Passages directory: ${path.resolve(PASSAGES_DIR)}`);
});
