# Spec: Email Agent — Slide-Deck Agent Driven by Order-of-Service Email

- **Status:** Implemented and live-verified end-to-end; deployment (`bs-tiz.6`) is the main remaining piece.
- **Date:** 2026-07-11 (planning); updated 2026-07-15
- **Epic:** `bs-tiz`
- **Owner:** thomas

> **Implementation status (2026-07-15).** The email plumbing is built and proven
> live: a real `AI:` email was read from Gmail, handled on Sonnet, and answered
> with a correct in-thread reply; idempotent on re-run; the agent declines to
> reply when nothing is warranted. Done: the gate (`bs-tiz.1`), Gmail tools
> (`bs-tiz.3`), dispatcher + SQLite store (`bs-tiz.2`), harness (`bs-tiz.4`),
> spike (`bs-tiz.7`), deterministic build (`bs-c16`), batch mode (`bs-ixn`),
> library-first lyrics (`bs-8yd`), and the special-music/congregational
> distinction (`bs-fdn`). Remaining: reply/report composition (`bs-tiz.5`) and
> the deployment host (`bs-tiz.6`). Sections 5–8 below have been reconciled with
> what was actually built; §5 in particular corrects a framing the planning draft
> got wrong.

---

## 1. Goal

Let the minister of music email an order of service (the "flowchart") and get
back a link to a generated slide deck, produced by the existing `gen_service`
skill running unattended. The operator (the volunteer who builds the slides)
receives the email, and an agent does the work on their behalf.

This is a **proof of concept**. Observability, multi-tenant safety, abuse
prevention, and production hardening are explicitly out of scope. The design
must, however, be architected broadly enough to add future skills without a
rewrite — the agent is a general "handle-an-email" agent, not a `gen_service`
wrapper.

## 2. Non-goals (POC)

- No dedicated agent email address — reuse an existing personal Gmail + OAuth
  credentials during the POC.
- No allow-list / anti-abuse beyond the deterministic subject-line gate.
- No heavy observability or alerting.
- No attachment format-conversion tooling — the agent installs packages and
  converts (PDF/Word → text) itself as needed.

## 3. Architecture

One small always-on host runs everything, sharing a single filesystem:

```
┌─ CRON heartbeat (~60s) ─────────────────┐
│  Gmail poll → subject regex → is this    │   deterministic
│  for the agent? initial vs reply?        │   (no LLM, metadata only)
│  → emit list of {threadId, msgId}        │
└──────────────┬──────────────────────────┘
               │ hands off IDs only
┌──────────────▼─ Dispatcher + SQLite state ┐
│  for each actionable thread:               │   deterministic
│  - already acted on this msg? skip         │
│  - locked / in-flight? skip (txn claim)    │
│  - map threadId → Agent SDK session_id     │
└──────────────┬─────────────────────────────┘
               │ launches / resumes
┌──────────────▼─ Agent (Claude Agent SDK) ─┐
│  broad "handle-an-email" harness            │   LLM
│  tools: getMessage, listAttachments,        │   ← deterministic tools
│         getAttachmentBinary, sendReply      │
│  skills: gen_service (+ future), auto-loaded│
│  → generate deck → reply in-thread w/ link  │
│    + structured report + open questions     │
└─────────────────────────────────────────────┘
```

**First principles (from ideation):**

- **Configurability** — the subject-line pattern and poll interval are config,
  not code.
- **Determinism** — the entry point is timer-driven and never "wakes up and
  reads the inbox." The gate only ever emits IDs for messages explicitly
  addressed to the agent; everything interpretive is left to the agent.

## 4. Components

### 4.1 Email gate — `bs-tiz.1`

Deterministic, no LLM. A ~60s CRON (later a Lambda + EventBridge timer) polls
the shared Gmail inbox using existing OAuth credentials. Applies a configurable
subject-line regex (e.g. `AI:`, `Calvary AI`) and classifies initial-message vs
reply. Fetches **metadata only**. Emits a list of `{threadId, msgId}`.

### 4.2 Dispatcher + SQLite state store — `bs-tiz.2`

Owns all cross-run state in SQLite:

```
threads(threadId → { session_id, last_processed_msgId, status, updated_at })
processed_messages(msgId → { threadId, processed_at })
```

**Deviation from the original design (implemented 2026-07-11):** a second table
was added. `last_processed_msgId` alone cannot answer "have we handled message
A?" once message B lands on top of it — and the gate legitimately re-emits every
message in the lookback window on every tick. With only that column, an older
message reappearing would be reprocessed and would send a **duplicate reply**.
`processed_messages` is the authoritative idempotency ledger; the original column
is retained as a summary view.

For each actionable thread it (a) skips messages already acted on, (b) skips
in-flight threads via a **transactional claim**, and (c) resolves the thread to
a Claude Agent SDK `session_id` — a new session for an initial email, resume for
a reply.

SQLite (not a JSON file) specifically because the heartbeat overlaps itself and
slide generation takes minutes; a JSON read/write race would double-process a
thread. The SDK persists the conversation transcript itself (JSONL on disk), so
this store holds **only** the mapping/bookkeeping — not conversation history.

### 4.3 Deterministic Gmail tools — `bs-tiz.3`

The narrow tool surface the agent uses:

- `getMessage(msgId)` → headers + body
- `listAttachments(msgId)` → metadata (filename, extension, size, mimeType)
- `getAttachmentBinary(msgId, attachmentId)` → raw bytes
- `sendReply(threadId, body, attachments?)` → replies **in-thread** via
  `In-Reply-To` / `References`

No format conversion in the tools — the agent handles that itself.

### 4.4 Agent harness — `bs-tiz.4`

Python **Claude Agent SDK** (`claude-agent-sdk`) — Claude Code as a library.
Launched by the dispatcher with a `threadId` + `session_id`: a new session for
an initiating email, `ClaudeAgentOptions(resume=session_id)` for a reply so full
prior context is restored. Deliberately **not** narrowed to `gen_service` — it
is given the Gmail tools plus its skills (auto-loaded from `.claude/` via
`setting_sources`) and instructed to discover intent and dispatch. For this POC
the one skill it drives is `gen_service`.

Reference: Anthropic's official email-assistant example in
[`claude-agent-sdk-demos`](https://github.com/anthropics/claude-agent-sdk-demos).

### 4.5 Reply + report composition — `bs-tiz.5`

Most of the nuance lives here — steering/prompt design as much as plumbing.
After `gen_service` runs, the agent replies in-thread with:

- the **link to the hosted deck**;
- a **structured report** ("I already had verses 1–3 of Amazing Grace — check
  my work"; "you asked for a hymn we hadn't done, I added it to the library from
  the Baptist Hymnal"). Note: line wrapping and font sizing are **not** things the
  agent asks about — they are handled deterministically (§5.1); the agent only
  relays a `typography`/`warnings` entry when the script flags one;
- critically, a **prompt-for-more-info loop** when a requested song has no
  lyrics ("you listed At the Cross as congregational but I don't have lyrics —
  reply with them, and note any repeats/bridge/extra chorus you sing").

**Library-divergence rule:** if the minister supplies lyrics that differ from
the library, use his version for *this* deck, call out the difference, and do
**not** modify the library unless explicitly told to.

Optional (not on the critical path): a PDF attachment fallback for recipients
off the tailnet.

### 4.6 Deployment host — `bs-tiz.6`

> **Revised 2026-07-15 — deck delivery moved to S3.** The paragraphs below
> describe the original *serve-off-the-host* delivery, which is superseded by
> **`specs/deck-publishing.md`**. The agent still runs on one always-on
> self-hosted box (CRON gate + dispatcher + agent on a shared filesystem), but the
> reply link is now a **public S3 URL** the minister opens on his phone over the
> internet — no tailnet for the minister, and a deliberate upload step
> (`bs-tiz.10`/`bs-tiz.11`) replaces "no upload step." Read this section as the
> agent-host requirements only; take deck delivery from `deck-publishing.md`.

One always-on box — church server behind VPN or a Tailscale node — runs Express
(serving the app and the generated `passages/` tree), the CRON gate, the
dispatcher, and the agent, all on one filesystem. Serves both this feature and
the broader goal of hosting Bible Scroller itself (so the presenter computer no
longer needs local file copies + a local Node launch).

Because the agent is co-located, `gen_service` writes `service-preview.html`
straight into the served tree and the reply link is simply
`https://<host>/passages/<date>/service-preview.html` — no upload step.

**Auth:** authenticate the Agent SDK with a subscription OAuth token from
`claude setup-token`, set as `CLAUDE_CODE_OAUTH_TOKEN`.
**Foot-gun:** ensure `ANTHROPIC_API_KEY` is **unset** on the host — if present
it silently wins over the OAuth token and bills a pay-per-token API account
instead of the subscription. Bake an env-scrub / assertion into the service.

## 5. The batch contract (the seam) — inside `bs-ixn`

The interface between the agent and `gen_service`.

- **In:** the order of service (emailed text) + fetched attachment paths + prior
  report/context for a reply.
- **Out:** artifact path (the written `service-preview.html`) + a structured
  machine-readable report (`passages/<date>/service-report.json`).

**Correction to the planning draft.** The draft said the contract has "zero
blocking questions." That is misleading, and the implementation deliberately does
not honour it literally. The agent asks questions *constantly* — it asks them **by
email**. The real invariant is that the **process** never blocks waiting for an
answer; the thread is the loop, and session resume (`bs-tiz.4`) is the mechanism.
The two real flowchart examples (`examples/flowcharts.md`) each run three or four
rounds of refinement.

What a gap does depends on whether a slide can still honestly exist — **two tiers,
handled differently:**

- **Blocking** — a slide cannot sensibly be made (e.g. a "Quartet" line naming no
  song: special music needs a title *and* a performer). The agent does **not**
  generate; it replies asking, and builds once the answer arrives. It may *suggest*
  the likely answer but must not assume it.
- **Non-blocking** — the deck is still worth having (e.g. missing lyrics). The
  agent emits a `title_only` slide, builds, and asks in the same reply. One
  unresolved song must never cost the operator his whole deck.

Report fields the agent acts on: `missing` (ask for these), `unverified` (flag
for checking), `splits`, `typography` (§5.1), `warnings`. Supporting pieces:
`bs-c16` moved rendering into a deterministic JSON→HTML build; `bs-8yd` then
`bs-1mf` removed lyric drafting entirely — **lyric text reaches a slide only by
way of `songs/*.md`, never from the model.** A song not in the library is
`title_only` plus a request for the text, in both modes.

That last rule is narrower than it sounds and worth understanding rather than
merely obeying. It is not a copyright judgment — the church's CCLI licence, not
this pipeline, settles what may be projected. It is that the model is the wrong
*source*: text it recalls is unverified regardless of the work's age, nobody
reads it before Sunday in batch mode, and a long verbatim lyric block is the
output most likely to be refused outright, which costs the operator the entire
deck over one song. Asking costs him one reply, and the answer is durable.

It is also self-limiting rather than a scaling risk: the deck JSON carries no
lyric text at all, so once a song is in the library the model never handles its
words. The exposure is the cold-start path, and it shrinks every week.

### 5.1 The determinism funnel

The load-bearing architectural idea, worth stating plainly because it shapes both
the skill and how it is tested: **the model's only output is a small deck JSON;
everything downstream of it is deterministic.** `scripts/build-deck.js` owns
slide numbering, backgrounds, scrims, seasons, stanza splitting, HTML escaping,
and typography — the model emits data, never markup. This is what lets the agent
run unattended on a cheaper model: the model does only what requires judgment
(read the flowchart, resolve songs, decide intent), and plain code does the rest
reproducibly.

**Typography is the clearest case, and the one to get right — sanctuary
projection is the whole point.** A lyric line is a unit of metre and is **never
greedily wrapped** (a wrap strands words like "glassy sea;" alone on a centered
line and makes a congregation stumble). The script measures every line against the
1196px slide with real Optima glyph widths (`scripts/optima-metrics.json`, exact
to 0.00% error) and applies a ladder: fits at 60px → render; carries a **caesura**
(`|` in the song file) → break there and stay at full size; too wide with no
caesura → shrink the whole song toward a 48px readability floor and report which
line to mark; unfittable even at the floor → a loud `warnings` line, never a
silent wrap. Size is chosen **once per song** so type doesn't jump between verses.

The division of labour mirrors §5's philosophy: the **script measures** (exactly),
the **model judges** where a caesura falls (a mechanical "break at the widest gap"
rule breaks hymns in musically wrong places). The `|` lives in `songs/*.md`, never
on a slide; it declares where a line *may* break for projection without editing the
canonical lyric, which keeps the fix durable and reviewable.

**Corollary — never hand-edit the generated HTML.** The deck is rebuilt from the
deck JSON on every reply, and the minister replies several times a week. An edit
to `service-preview.html` survives until the next rebuild and then vanishes
silently. Every ad-hoc fix goes into a **durable input** — the deck JSON or a
`songs/*.md` file (including a caesura) — so it survives regeneration.

### 5.2 Test strategy

Because the model's output funnels to deck JSON, the deterministic half is pinned
by golden tests (`tests/build-deck.test.js`: reference deck HTML + report,
byte-for-byte; the cardinal-rule build errors; the CLI contract), and the model's
judgment is checked by evals against the real flowcharts
(`agent/tests/eval/`, `uv run pytest -m eval`). The evals stage an isolated repo
with a **seeded** song library (so "already in the library" vs "must look it up"
vs "must ask" is controlled) and assert on the deck's structure and the report —
never on prose. This is what makes a nondeterministic agent testably repeatable.

## 6. Key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Artifact delivery | **Publish to S3** (revised 2026-07-15) | Decouples deck delivery from the agent host; minister opens it on his phone with no tailnet. Still not a self-contained bundle — a shared ~13-image template set beats inlining. See `specs/deck-publishing.md`. |
| Harness | **Claude Agent SDK** (Python) | Claude Code as a library: native session resume, native skill loading, runs in our process on our filesystem. Not the API Tool Runner, not Managed Agents. |
| Auth / billing | **Subscription OAuth token** | Personal-assistant use (task emailed *to* the operator), a defensible use of subscription credit. |
| State store | **SQLite** | Transactional in-flight claim; avoids the JSON read/write race under overlapping heartbeats. |
| Skill format | **Migrate to `SKILL.md`** (`bs-tiz.8`) | `.claude/commands/*.md` is the legacy format; skills are the supported path for SDK + CLI. |

### ToS watch-line

Anthropic's Agent SDK terms restrict using claude.ai login to power products
offered to others. This POC is a personal assistant doing a task emailed to the
operator — not a service for end users. **Revisit** and move to
`ANTHROPIC_API_KEY` (pay-per-token) if this is ever rolled out to serve others
directly.

## 7. Failure & idempotency semantics — `bs-tiz.2`

- **In-flight lock:** a transactional claim prevents overlapping heartbeats from
  launching a second agent for the same thread.
- **Failure state:** an agent error must transition the thread out of
  `in-flight` (to a `failed`/timeout state that releases the claim) and send an
  "I hit an error" reply — never leave a thread locked forever.
- **Reply arriving mid-run:** a correction that lands while the agent is still
  working is skipped that tick (in-flight) and **reprocessed** after release —
  it must not be silently dropped.
- **Commit boundary:** mark a message processed only *after* the reply is sent.
  A crash between send-and-mark yields a rare duplicate reply — acceptable for
  POC, named here so it's a decision not a surprise.

## 8. Verification (spike) — `bs-tiz.7` (done)

Before building the harness, a short hands-on confirmation of the three
assumptions the design rests on — **all three confirmed** (`agent/spike/FINDINGS.md`):

1. Headless `claude-agent-sdk` query bills the **subscription** via
   `CLAUDE_CODE_OAUTH_TOKEN` (with `ANTHROPIC_API_KEY` unset). Caveat learned:
   `total_cost_usd` is *not* a billing signal; the subscription proof is
   `RateLimitEvent.rate_limit_type == 'five_hour'`. `ANTHROPIC_API_KEY` silently
   outranks the OAuth token, so `config.assert_agent_auth()` hard-fails on it
   (skipped when `AGENT_BASE_URL` routes the run away from Anthropic — see §8).
2. A resumed session restores prior context across two **separate** process
   runs (`resume=session_id`, `session_id` from the init `SystemMessage`).
3. `gen_service` **loads and runs** from `.claude/` inside an SDK query — but only
   with `setting_sources=["project"]`, which fails **silently** if omitted.

Note: `AskUserQuestion` is a built-in SDK tool but does **not** apply here (no
interactive user) — it would hang the run; reinforces the non-interactive design.

**Failure mode found during eval runs (`bs-a1f`) — RESOLVED 2026-08-02.** An agent
whose job is reproducing hymn lyrics verbatim will have its output refused with
`400 Output blocked by content filtering policy` (first seen on an
all-patriotic-hymns flowchart, ~1 in 8 runs; by 7/26 it was killing whole
services, six failures across two threads). This is *not* silence: the run ends
without a terminal tool call, which trips the harness's "decided nothing" guard →
`AgentError` → the dispatcher's failure path (§7) marks the thread failed,
releases the claim, and retries — uselessly, since every attempt fails the same way.

The filter is a property of the **endpoint, not the model**: lyrics merely being
in context is enough to trip it, so no prompt or output shaping avoids it, and
`fallback_model` cannot help (it swaps models *within* Anthropic's API). The fix
is therefore configuration, not code — `AGENT_BASE_URL` points the agent's CLI
subprocess at any Anthropic-compatible endpoint (currently Moonshot,
`kimi-k3[1m]`). Unset, everything behaves exactly as before.

Two consequences worth stating plainly. **Thread contents leave for a third party
on every run** when this is set, which is a data-handling decision, not just a
model choice — hence `agent_env()` blanking the subscription credentials rather
than merely not setting them. And it costs pay-per-token, where the subscription
did not.

*Superseded by this:* `specs/lyric-ingestion.md` and the local-model/line-offset
design (`bs-8qs`, `bs-2pn`) — extracting lyrics with a local model that emits only
offsets, sliced by deterministic code so no lyric text reaches a cloud model.
Shelved, not deleted, and **not wired into the runtime**; it is the fallback if
the alternate backend ever becomes unavailable.

## 9. Sequencing

```
bs-c16 (deterministic JSON→HTML build)
   └─► bs-ixn (batch mode — defines the CONTRACT)
          ├─► bs-tiz.4 (harness; also needs bs-tiz.7 + bs-tiz.3)
          │       └─► bs-tiz.5 (reply / report / missing-lyrics loop)
          └─► bs-tiz.5

bs-tiz.1 (gate) ──► bs-tiz.2 (dispatcher; also needs bs-tiz.4)
bs-tiz.7 (spike) ─► bs-tiz.4
bs-8yd  (library-first lyrics)   ─ parallel, on the skill critical path
bs-tiz.8 (gen_service → SKILL.md) ─ pair with the bs-c16/bs-ixn rework
bs-tiz.6 (deployment host)        ─ parallel infra
```

The DAG above is the original plan and still describes the dependencies
faithfully; nearly all of it is now built (see the status note at the top).
**Remaining:** `bs-tiz.5` (reply/report composition — the eval's `send_reply`
stub is deliberately the seam it builds on) and `bs-tiz.6` (deployment host, the
next session's focus). `bs-tiz.8` (migrate `gen_service` to `SKILL.md`) is
optional cleanup.

## 10. Deferred / open

- ~~Minister-side link reachability (whether he's on the tailnet when he clicks).~~
  **Resolved 2026-07-15 (`specs/deck-publishing.md`):** decks publish to a public
  S3 bucket and the minister opens them on his phone over the public internet, so
  tailnet membership is no longer required on his side. The PDF-attachment fallback
  is therefore no longer needed for reachability.
- Every reply re-waking the agent (even "thanks!") costs tokens — POC-acceptable;
  the agent decides whether a reply needs action.
- Future skills beyond `gen_service` — the harness is architected broad to
  accommodate them without a rewrite.
