# Spec: Email Agent — Slide-Deck Agent Driven by Order-of-Service Email

- **Status:** Draft for review (planning complete; implementation not started)
- **Date:** 2026-07-11
- **Epic:** `bs-tiz`
- **Owner:** thomas

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
  the Baptist Hymnal"; "check line wrapping / tell me if you want font tweaks");
- critically, a **prompt-for-more-info loop** when a requested song has no
  lyrics ("you listed At the Cross as congregational but I don't have lyrics —
  reply with them, and note any repeats/bridge/extra chorus you sing").

**Library-divergence rule:** if the minister supplies lyrics that differ from
the library, use his version for *this* deck, call out the difference, and do
**not** modify the library unless explicitly told to.

Optional (not on the critical path): a PDF attachment fallback for recipients
off the tailnet.

### 4.6 Deployment host — `bs-tiz.6`

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

The interface between the agent and `gen_service`. Defining it is a deliverable
of `bs-ixn` and unblocks the agent-behavior work.

- **In:** the order of service (emailed text) + fetched attachment paths + prior
  report/context for a reply.
- **Out:** artifact path (the written `service-preview.html`) + a structured
  report (verify-these / missing-these), with **zero blocking questions**.

Anything the interactive skill would have *asked* becomes a line in the report.
`gen_service` today is human-in-the-loop; `bs-ixn` adds the non-interactive
mode, `bs-c16` moves HTML generation into a deterministic JSON→HTML build, and
`bs-8yd` forbids drafting lyrics from memory in batch mode.

## 6. Key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Artifact delivery | **Host the HTML** | Aligns with hosting the whole app; co-located agent → no upload step. Killed the self-contained-bundle idea. |
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

## 8. Verification (spike) — `bs-tiz.7`

Before building the harness, a short hands-on confirmation of the three
assumptions the design rests on:

1. Headless `claude-agent-sdk` query bills the **subscription** via
   `CLAUDE_CODE_OAUTH_TOKEN` (with `ANTHROPIC_API_KEY` unset).
2. A resumed session restores prior context across two **separate** process
   runs (`resume=session_id`, `session_id` from the init `SystemMessage`).
3. `gen_service` **loads and runs** from `.claude/` inside an SDK query.

Note: `AskUserQuestion` is a built-in SDK tool but does **not** apply here (no
interactive user) — this reinforces the non-interactive/report design.

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

**Parallel-startable now:** `bs-tiz.7` (spike), `bs-tiz.1` (gate), `bs-tiz.3`
(Gmail tools), `bs-c16`, `bs-8yd`, `bs-tiz.8`.

**Suggested first move:** `bs-tiz.7` — half a day, validates the three harness
assumptions, unblocks `bs-tiz.4`; `bs-c16` and `bs-tiz.3` run fully in parallel.

## 10. Deferred / open

- Minister-side link reachability (whether he's on the tailnet when he clicks).
  Deferred; PDF-attachment fallback captured as optional AC on `bs-tiz.5`.
- Every reply re-waking the agent (even "thanks!") costs tokens — POC-acceptable;
  the agent decides whether a reply needs action.
- Future skills beyond `gen_service` — the harness is architected broad to
  accommodate them without a rewrite.
