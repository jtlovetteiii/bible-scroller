# Spec: Deck Publishing — Deliver Generated Decks via S3, Not by Serving Them

- **Status:** Planned. Supersedes the delivery half of `specs/email-agent.md` §4.6/§6/§10.
- **Date:** 2026-07-15
- **Epic:** `bs-tiz` (Email Agent)
- **Owner:** thomas
- **Issues:** `bs-tiz.9` (renderer asset base), `bs-tiz.10` (publish tool),
  `bs-tiz.11` (template sync), `bs-tiz.12` (vendor html2canvas, backlog);
  revises `bs-tiz.6` (host), feeds `bs-tiz.5` (reply link).

---

## 1. What changed and why

The email-agent design assumed the generated deck would be **served** off the
same always-on box that runs the agent: Express hosting the `passages/` tree, the
reply link a `https://<host>/passages/<date>/service-preview.html`, reached by the
minister over a tailnet. That baked two couplings we no longer want:

1. **Delivery was tied to the agent's host.** The minister could only reach a deck
   if he was on the tailnet on whatever device opened the email. A link opened on
   his phone at 6am — the actual usage — would fail unless Tailscale was installed
   and running there.
2. **The URL was tied to a machine we may re-home.** An emailed link lives in a
   mailbox forever; pointing it at a specific host makes every old email a future
   dead link.

**New model: separate *where the agent runs* from *where the deck lives*.**

- The agent stays **self-hosted** on the user's home server / Raspberry Pi. It
  still needs an always-on box for the CRON gate, dispatcher, and agent
  (`bs-tiz.6`, unchanged in that respect).
- Each finished deck is **published to a public S3 bucket** the user already owns.
- The minister opens the deck **on his phone over the public internet** — no
  tailnet, no VPN, no client software, nothing for the operator to provision on
  the minister's devices.

Nothing in the deck is sensitive (service order, hymn titles, public-domain
lyrics on stock backgrounds), so a public bucket is acceptable. It is not,
however, meant to be a *browsable* archive — see §4.

## 2. Why S3 works here (and the standalone-bundle idea is dead)

An earlier worry was that the deck HTML isn't self-contained — it references
background images — so hosting would force inlining them as `data:` URIs. That
premise is false for object storage, and the numbers make the opposite case:

- A deck references a **small shared set of ~13 template PNGs**, not one image per
  slide. `hymn-1.png` appears ~20 times in a service but downloads **once** and is
  served from cache for the rest.
- Inlining would take those 13 shared files and re-encode them into the HTML on
  every reuse (~75 stamps in a long service), with base64's ~33% inflation, no
  lazy loading, and no caching. Separate objects are **strictly better** for the
  phone case *because* of the reuse.

So the deck is a static **site** (HTML + a handful of shared image objects), not a
static **file**. `data:` URIs are only forced when the channel is genuinely
single-file (an email attachment, a strict CSP) — a bucket is neither.

## 3. Mechanism

Three pieces, each a separate issue. The load-bearing rule: **the renderer emits
correct paths at build time — nothing rewrites the finished HTML.**

### 3.1 Renderer asset base — `bs-tiz.9`

`scripts/build-deck.js` currently hardcodes image paths in one helper:

```js
const bg = (file) => `/templates/service/${file}`;   // build-deck.js:463
```

That single seam becomes configurable via a `--asset-base <url>` flag (and a
matching env var, e.g. `DECK_ASSET_BASE`):

- **Unset (default):** emits `/templates/service/<file>` exactly as today. This is
  a hard requirement — local Express serving and the golden tests
  (`tests/build-deck.test.js`, `tests/golden/*`) must stay **byte-for-byte
  identical** when the flag is absent.
- **Set to a full origin** (e.g. `https://<bucket-or-cdn>/templates/service`):
  emits **absolute** `<img src>` URLs.

Absolute URLs are deliberate: the image resolves against the bucket origin no
matter where the HTML is opened — bucket root, a sub-path, an email preview, even
saved to disk. Relative paths would force the HTML and images into a fixed
relative layout; absolute URLs decouple them, which is exactly what an emailed
link needs.

This preserves the project's cardinal rule (`email-agent.md` §5.1): the model
emits data, the script owns markup, and **the generated HTML is never
post-processed**. A publish step that rewrote paths in the finished file would be
a second writer of that artifact and would re-introduce the drift that rule
exists to prevent.

### 3.2 Publish tool — `bs-tiz.10`

What the agent runs when a deck is ready to share:

1. Render the deck with `--asset-base` pointed at the S3 template root (§3.1).
2. Upload **one HTML object** to a date-keyed path, e.g.
   `s3://<bucket>/decks/<date>/index.html`.
3. Return the public `https://…` URL for the reply (`bs-tiz.5` puts it in the
   email).

Per-deck upload is a **single HTML file**. There are no per-deck images and no
`data:` URIs; the templates it references were uploaded separately (§3.3). Bucket,
path prefix, and asset base are **config (env), not code**, because the external
URL may change.

### 3.3 Template sync — `bs-tiz.11` (operator-run)

The ~13 template PNGs change only when the operator edits or adds a template, so
they are **not** part of per-deck publishing. A user-run script
(`scripts/sync-templates.js` / an npm script) uploads `templates/service/*.png` to
the same S3 asset root `--asset-base` points at. The operator runs it **manually
after changing a template** — that is the whole reason a deck publish stays down
to one HTML upload.

### 3.4 JPEG export and CORS — the non-obvious constraint

The hosted deck is not just *viewed*; the operator clicks **Export** on it to
generate the `SlideNN.jpeg` files for ProPresenter, often from a machine at church
with only the S3 link. That export is **fully client-side** — `html2canvas`
rasterizes each slide to a `<canvas>`, then `canvas.toBlob()` triggers a local
download (`templates/service-slides-template.html:213`). It never contacts the
agent host or any server. Good.

But it has **two** network dependencies that must both hold from the church:

1. **html2canvas loads from cdnjs.** The Export button is inert until that script
   downloads. Church internet covers it; a fully-offline box would not (this is
   the whole reason to eventually vendor it — `bs-tiz.12`).
2. **The template images must be CORS-readable — a real landmine.** html2canvas
   draws each background PNG *into* the canvas. Once those images are cross-origin
   (served from S3 instead of same-origin Express), the browser **taints** the
   canvas unless S3 returns `Access-Control-Allow-Origin`, and a tainted canvas
   makes `canvas.toBlob()` **throw a SecurityError** — export fails while the deck
   still looks perfect on screen. The template already sets `useCORS: true` (the
   client half); the bucket/CDN must send the header (the server half).

This never reproduces locally, where everything is same-origin, so it is an
explicit acceptance criterion on `bs-tiz.10`: **verify JPEG export from the hosted
S3 URL, not just from a local build.**

## 4. Bucket hygiene and URL permanence

- **Not a browsable archive.** Disable S3 directory listing and use date-keyed,
  hard-to-enumerate paths. Content isn't sensitive, but "not sensitive" shouldn't
  quietly become "public index of every service we've ever run."
- **Design paths as permanent.** An emailed `…s3….amazonaws.com/decks/2026-06-28/`
  link is forever. If the bucket is later fronted with CloudFront + a domain the
  user owns, a stable date-based scheme lets those old links keep working. Don't
  design as if the URL is disposable.

## 5. What this does *not* change

- **The agent host (`bs-tiz.6`) still exists** — CRON gate, dispatcher, and agent
  on one always-on box against a shared filesystem, subscription OAuth auth with
  `ANTHROPIC_API_KEY` unset. Only *deck delivery* moved off it; the box may still
  serve the scroller app to the operator, independently.
- **The determinism funnel (`email-agent.md` §5.1) is untouched** — in fact this
  reinforces it: publishing is render-with-a-flag + upload, never an edit of the
  rendered file.
- **The report's local `preview_url`** (the `http://localhost:3000/...` operator
  preview) stays as-is. The published URL is a separate, additional output of the
  publish tool.

## 6. Deferred / notes

- **html2canvas CDN dependency (`bs-tiz.12`, backlog).** The slide template's
  export button loads html2canvas from cdnjs. In this model the CDN just works
  (the minister's phone has internet; the export button is an operator tool run
  locally with internet), so it is **not** on the critical path. Vendoring it
  removes the last external dependency for full offline resilience; captured, not
  urgent.
- **A future custom domain** in front of the bucket is the clean answer to URL
  permanence (§4) but needs a small reverse proxy / CloudFront distribution;
  `.ts.net` names and raw S3 URLs don't take a custom domain cleanly on their own.
  Out of scope now; the date-keyed path scheme is chosen to make it painless later.
