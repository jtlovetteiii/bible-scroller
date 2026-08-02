# Spec: Mitigating Cloud Model Failures Due To Copyrighted Lyrics

- **Status:** The gate (§7.1) has been run — **read it before planning work, it
  changed what the question is** — and it surfaced a second lyric channel this design
  does not close (§4.5, `bs-vhp`). The deterministic half now lives in
  `agent/src/email_agent/lyrics/` with golden tests (§5); everything that talks to a
  model or to Gmail is still unbuilt.
- **Date:** 2026-08-01 (gate results, §4.5 and the §5 promotion added 2026-08-02)
- **Issue:** `bs-8qs` (carries the full experimental record)
- **Related:** `bs-a1f` (the incident), `bs-e4m` (spike, closed), `bs-dox` (superseded
  approach), `bs-zzq`, `bs-7sb`, `bs-fsx`, `bs-752`
- **Owner:** thomas

> **Read this first.** Everything below §3 is measured, not assumed. Where a number
> appears it came from a probe in `agent/tests/probes/`, and those probes are
> committed so any claim here can be re-run. Where something is *unknown* it says so
> — in particular §7.1, which is the one test that should gate implementation.

---

## 1. The problem

The agent's core job is putting song lyrics on a screen. The church holds a CCLI
licence covering the songs it displays. Cloud frontier models nonetheless refuse or
are blocked when asked to reproduce those lyrics, and this has already destroyed a
real Sunday.

**2026-07-26, production.** The minister emailed six songs and pasted the lyrics for
all of them. Every attempt died with:

```
API Error: 400 Output blocked by content filtering policy
```

Six failures across two threads (`19f95387567d275e`, `19f9e5592103ca17`). The
`bs-9ed` retry bound did its job — three bounded attempts, then a fixed apology went
out rather than silence — but the minister got no deck. The full thread, including
the pasted lyrics for all six songs and the apology, is preserved in
`examples/flowcharts.md` under "Example: 7/26/2026", and is the fixture for §7.

What makes this hard is the shape of the failure, established in `bs-a1f`:

- It is **not** verbatim reproduction from memory. The minister *pasted* the licensed
  lyrics into the email and it still blocked.
- It is **not** fixed by writing lyrics via a tool instead of prose. Attempt 2 blocked
  *on* a `Write` call.
- Attempt 3 blocked on the **first assistant turn after `mcp__gmail__get_thread`**,
  having written nothing at all. Lyrics merely being *in context* was enough that time.
- It correlates with **copyright status**, not luck: the two writes that succeeded
  that day were public-domain hymns; the block landed on the copyrighted set.

That last point kills the whole "keep lyrics out of the model's *output*" family of
fixes, because the agent still has to read the thread.

### 1.1 Goal

A service whose songs are copyrighted is processed end to end — lyrics into
`songs/*.md`, deck built, link emailed — on the existing subscription-billed cloud
model, without a content-filter block and without any lyric text being invented.

### 1.2 Non-goals

- Agentic execution on a local model. Tried, and it failed badly (§3.3). The local
  model is a **tool**, never an orchestrator.
- Replacing the Claude Agent SDK. See `bs-752`; a framework swap does not clear the
  filter, which is a provider policy, not an SDK property.
- Any change to how decks are rendered. `build-deck.js` is untouched by this work.

---

## 2. What we tried, and why each was abandoned

### 2.1 Fall back to another *provider* — `bs-dox`, **falsified**

The premise was that the filter is Anthropic-side policy, so any non-Anthropic model
would clear it. Measured (`probe_filter.py`):

| backend | model | result |
|---|---|---|
| cloud | `claude-sonnet-5` | **PASS** — 15.6s, 53 lines verbatim, no 400 |
| proxy | `gpt-5.6-terra` | **REFUSED**, deterministically 2/2 |
| proxy | `bonsai` | **PASS** — no refusal, no filter |

> *"Sorry, I can't reproduce or compile the complete lyrics of these copyrighted
> songs."* — `gpt-5.6-terra`

On this task Anthropic was the **more permissive** provider. Copyright guardrails are
an industry norm, so there is no provider to escape to; a fallback only trades a 400
for a refusal — and the refusal is worse operationally, arriving with
`is_error=False` so the run *looks* successful and simply produces nothing.

`bs-dox` remains open only as a fallback-of-last-resort if §5 proves infeasible. Do
not build it as originally specified.

### 2.2 Heuristic redaction

Rejected before building. Lyrics can appear anywhere the minister puts them —
inline with a sentence, mid-paragraph, in an attachment. A regex cannot make that
judgement. This is what motivated §5.

### 2.3 The local model as an *agent* — measured, **failed**

`probe_intermediary.py` gave Bonsai the Agent SDK with tools and asked it to extract
lyrics and rewrite the email. On a deliberately hostile two-song fixture:

- **3209s (53.5 minutes), 66 tool calls**, thrashing through Write/Read/verify loops
  with *"I apologize for the repeated confusion"*.
- **Leaked 18 lyric lines** — it appended the reference line and never deleted the
  block, i.e. failed *open* at the one thing the design exists to prevent.
- Titled songs from their first lyric line even where the real title was present.

The judgement half survived — zero prose lost, including an instruction buried
mid-stanza, and it correctly declined to invent lyrics for a song mentioned by name
only. Every failure was **text regeneration and agentic self-correction**, not
lyric/prose discrimination. That distinction is what §5 is built on.

### 2.4 Model-authored shell

`probe_copy.py` showed both providers will happily *orchestrate* a copy they refuse to
*retype*. But `gpt-5.6-terra`'s one-liner produced byte-exact lyrics while duplicating
stanza headings — 16 where 10 were correct. A mangled stanza structure is a broken
deck. **Model-authored shell is not deterministic.** The copy must be a fixed, tested
tool, matching this repo's existing rule for `build-deck.js`.

---

## 3. What we learned about the homelab LLM

All of this was invisible until the proxy was bypassed.

### 3.1 What the host actually is

```
server : llama.cpp
model  : Bonsai-27B-Q1_0.gguf
size   : 3.79 GB for 26.9B params  =>  ~1.13 bits/param — a 1-bit quant
context: n_ctx 65536 (trained 262144)
/props : reasoning_format=none, reasoning_in_content=false,
         chat_template_caps.supports_preserve_reasoning=true
```

The quantisation matters: **much of the variance in §4 may be the quant rather than
the model.** See §6 — nothing in this design may assume a particular model quality.

### 3.2 Do NOT call it through UniClaudeProxy

The proxy silently drops two things that make it unusable for this:

1. **It drops `chat_template_kwargs`.** This is the only knob that disables
   reasoning. Through the proxy it has no effect, which is why an early ten-variant
   sweep came back as pure noise.
2. **It drops llama.cpp's `reasoning_content` field.** llama.cpp returns thinking in
   a field separate from `content`. The proxy discards it, so a call that spent its
   whole budget thinking arrives as an **empty `content`** with
   `stop_reason=max_tokens` — indistinguishable from "no lyrics found" unless you
   check the stop reason.

Call `http://<host>:8080/v1/chat/completions` directly.

### 3.3 Reasoning must be disabled, and only one knob does it

Measured on `"Reply with exactly: OK"`, completion tokens:

| setting | tokens | effect |
|---|---|---|
| baseline | 106–122 | — |
| `reasoning_budget: 0` | 119–150 | none |
| `reasoning_effort: none/low/minimal` | 140–175 | none (verified as noise over 4 runs each) |
| `thinking: {"type":"disabled"}` | 158–165 | none |
| **`chat_template_kwargs: {"enable_thinking": false}`** | **2** | **works** |

On the real extraction task: **159.0s / 7111 tokens → 6.3s / ~250 tokens.** ~25x on
both axes. Reasoning bought nothing in quality — the one think-*on* run titled a song
"Holy, Holy, Holy" after one of its own lyric lines.

### 3.4 A single call is not reliable

Three identical think-off calls on the same fixture leaked **6, 4 and 0** lyric lines,
and one missed an entire song. Roughly **a third of calls produce an invalid spec**
(malformed JSON, or overlapping ranges) — caught by validation, but it means N must
be large enough that enough specs survive.

**Do not read any single run as evidence.** Variance dominates.

### 3.5 Addresses are volatile

`192.168.0.48` does not route when Thomas is away from the house; a round of tests
silently reached nothing before this was noticed. The tailnet address at time of
writing is `100.66.185.49`. An older recorded address (`100.69.94.72`) is stale.
**Both must be configuration, never hardcoded.**

---

## 4. The design

**Never route verbatim lyric text through a cloud model — in either direction.** The
local model contributes only *line numbers and titles*; deterministic code moves every
lyric byte.

```
Gmail thread
   │
   ▼
ingest_thread(thread_id)                  ← the frontier model calls THIS,
   │                                        never get_thread, for a lyric thread
   ├─ fetch thread text
   ├─ number the lines
   ├─ N × one-shot → local model (reasoning off)   ~6s each, parallel-safe
   │     each returns: {"songs":[{slug,title,sections:[{name,start,end}]}]}
   ├─ validate each spec        → reject malformed / out-of-bounds / overlapping
   ├─ consensus over survivors  → union line claims, majority-vote titles
   ├─ SLICE ranges → songs/*.md          (deterministic; no text regenerated)
   └─ DELETE the same ranges → redacted body with [LYRICS: …] reference lines
   │
   ▼
returns {songs:[{slug,title,sections}], thread:"<redacted>"}
   │
   ▼
frontier model — sees titles, section names and prose. Never lyric lines.
```

### 4.1 Why extraction and deletion share one range set

They are the same walk over the same ranges, so *"extracted but not removed"* — the
exact bug that leaked 18 lines in §2.3 — is **not a reachable state**. Hallucination
likewise becomes structurally impossible rather than merely checkable: the model emits
no lyric characters, so there is nothing to hallucinate. Slicing also preserves
caesura `|` markers and exact whitespace for free (measured 3/3 preserved, every run).

### 4.2 Consensus, and why the bias runs one way

Runs miss *different* lines, so the union covers them. Measured, 7 calls / 44s:

| threshold | claimed | prose destroyed | **lyrics leaked** |
|---|---|---|---|
| K≥1 … K≥4 | 45 | 3 | **0** |
| K≥5 | 42 | 2 | 2 |
| K≥6 | 38 | 0 | 4 |

Reproduced independently at N=6 (4 valid specs): K≥1 and K≥2 both leak **0**.
Title votes were unanimous among valid specs.

The two error directions are **not symmetric**, and the design leans on that:

- **Over-claiming** destroys a prose line → visible to the minister in the reply,
  correctable, costs one email.
- **Under-claiming** leaks a lyric → content-filter 400, the run dies, and it is the
  failure this entire document exists to prevent.

So default to a low threshold and **surface the over-claim** rather than hiding it:
the reply should say which lines were moved into the library so the minister can
correct a swallowed instruction.

### 4.3 The ordering constraint — this is what makes it real

**The tool takes a `thread_id`, never text, and is called *instead of*
`get_thread`.** If the frontier model must first read the email to decide whether to
call the tool, it has already taken the exposure — `bs-a1f` attempt 3 blocked on the
first turn after `get_thread` having written nothing. Get this ordering wrong and the
design is decorative.

Redaction belongs at **`extract_body` (`tools.py:148`)**, the single function both
`get_thread` (`tools.py:354`) and `get_message` (`tools.py:181`) use. Redacting only
`get_thread` is bypassable by calling `get_message` on the same id — a hole found
while writing this spec, and one that would look fine in testing.

Note the frontier model loses nothing it needs: deck JSON carries only slugs and
section names — verified, `passages/2026-07-19/service.deck.json` contains no lyric
text at all — so the reference line gives it exactly the schema it must emit.

### 4.4 Known limitation: mixed lines

Line granularity cannot express *"the second half of line 7 is a lyric"*. Two runs
failed in **opposite directions** on the same mixed prose+lyric line — one leaked the
lyric, one destroyed the prose. This is a limitation of the representation, not of the
model's judgement.

Minimal fix, preserving the no-hallucination guarantee: optional character trims on
**boundary lines only** —

```json
{"name": "Verse 1", "start": 7, "end": 12, "start_col": 71}
```

Everything stays sliceable and the model still emits only integers. Not built.

---

### 4.5 The channel this design misses: the build report — `bs-vhp`

§4.3 checked that the deck JSON carries no lyric text. That is true, and it is not
the whole picture: **`scripts/build-deck.js` writes `service-report.json`, and the
report quotes lyric lines back at the model.** Measured on the real six 7/26 songs,
**53 of 127 distinct copyrighted lines appear in it verbatim** (and 112/127 in
`service-preview.html`). They arrive two ways:

- `report.typography` lists, per song, the exact lines that will not fit;
- `report.warnings` quotes the worst offender in prose — *`One Day: 5 line(s) will
  WRAP MID-PHRASE … Worst: "One day when heaven was filled with His praises,"`*.

This is not incidental: the model is *told* to read it. `gen_service.md` step 5 says
"Summarize from the report", and its typography rule says to act on those warnings by
adding a caesura to `songs/<slug>.md` — i.e. to open a file of copyrighted lyrics and
rewrite a lyric line. The 2026-08-01 passing run did exactly that ("added caesura
markers throughout").

So the redaction chokepoint at `extract_body` closes **email → model**. This channel
runs **tool → model** and is wide open. Until it is closed, *"never route verbatim
lyric text through a cloud model, in either direction"* is not a true description of
the pipeline, even with `ingest_thread` built exactly as §5 specifies.

The fix has an easy half and a hard half. Easy: report typography by section name and
line index, never by text — the deterministic renderer already owns the text and the
model never needs it. Hard: the caesura loop genuinely asks the model to edit lyric
lines. Either move caesura insertion into `build-deck.js` (it has the metrics, and
sense-breaks are largely inferable from punctuation), or express it as an offset edit,
the way ingestion already expresses extraction.

---

## 5. Components to build

Nothing below exists in `agent/src/` yet.

| # | Component | Notes |
|---|---|---|
| 1 | Config keys | endpoint, model, N, K, timeouts — all env-driven (§6) |
| 2 | llama.cpp client | sets `enable_thinking: false`; treats `finish_reason == "length"` as an **error**, never as "no lyrics" |
| 3 | Consensus runner | N calls, validate each, union ranges, majority-vote titles |
| 4 | `mcp__songs__ingest_thread(thread_id)` | returns metadata + redacted body |
| 5 | Redaction at `extract_body` | closes the `get_message` bypass (§4.3) |
| 6 | Sanitized-thread cache in `state.db` | so it does not re-run every heartbeat tick or on resume |
| 7 | Fail-closed path | local model unreachable ⇒ `bs-9ed` apology, **never** pass through raw |
| 8 | Healthcheck probe | `bs-7sb`, now more important: this is on the critical path |

**Done 2026-08-02 (`bs-2pn`).** The deterministic half is now
`agent/src/email_agent/lyrics/` (`offsets.py`, `consensus.py`), pinned by
`tests/test_lyric_repair.py` (the repair invariant, 20k adversarial specs) and
`tests/test_lyric_pipeline.py` (a golden run over the real 7/26 email). The golden
test freezes five real model specs into `tests/fixtures/specs_0726.json` so it is
deterministic and network-free — and that fixture contains **zero lyric characters**,
which is the design's central claim turned into an assertion.

Items 1, 2, 4, 5, 6, 7 and 8 remain unbuilt.

<details><summary>The original note, for context</summary>

`agent/tests/probes/lyric_offsets.py` and `lyric_consensus.py`
are pure, self-tested implementations of the deterministic half — numbering, prompt,
parsing, validation, slicing, redaction, consensus. Move them to `src/email_agent/`
and pin them with golden tests, exactly as `build-deck.js` is pinned by
`tests/build-deck.test.js`. The self-test already covers 41/41 verbatim lines, 3/3
caesuras, zero prose lost, and rejection of all five malformed-spec classes.

</details>

---

## 6. Configuration — assume nothing about the model

Every number in §4.2 was tuned against a **1-bit quant**. A stronger model at home
should need fewer runs, and the design must not have to change when that happens.

| key | default | why it must be tunable |
|---|---|---|
| `LOCAL_LLM_BASE_URL` | — | address is volatile (§3.5); empty disables the feature |
| `LOCAL_LLM_MODEL` | — | model file name changes with every quant swap |
| `LYRIC_CONSENSUS_RUNS` (N) | 7 | **the key dial.** A better quant should need fewer; ~⅓ of calls currently produce an invalid spec, so N must leave enough survivors |
| `LYRIC_CONSENSUS_THRESHOLD` (K) | 1 | union. Raise only with evidence from a real email |
| `LYRIC_SONG_THRESHOLD` | 1 | guards against one run inventing a song |
| `LOCAL_LLM_TIMEOUT_SECONDS` | — | separate from `agent_timeout_seconds`; preprocessing must not eat the agent's 1800s budget |

Log the vote counts per line. When N is reduced, the near-miss lines
(`ConsensusReport.below_threshold`) are the evidence for whether it was reduced too far.

---

## 7. Tests to run before implementing

### 7.1 The gate — does the *redacted* thread clear the filter?

> **RUN 2026-08-01/02 (`bs-2pn`). Result: the question is malformed as posed, and the
> answer is a rate.** Seven full cloud agent runs over the redacted thread:
> **6 cleared the filter and built a deck; 1 was blocked.** The single 400 was the
> first run, and it used the earlier redaction — fused sections, one song's lyrics
> sitting inside another song's file, duplicate headings. Every run on the corrected
> redaction cleared: **6/6**.
>
> Read that carefully. It is n=1 on the old redaction, so two explanations are still
> open — a base failure rate around 15%, or the redaction quality mattering — and this
> does not separate them. 6/6 is also consistent with a true failure rate up to ~20%;
> it does **not** establish zero. **The filter is not a deterministic function of the
> input**, so no single run settles anything in either direction. Use
> `probe_gate.py --repeat` and read the rate.
>
> Two things the passing run exposed, both worth more than the pass itself:
>
> 1. **The redaction is verifiably clean and it is still not enough.** 0 of 128
>    distinct lyric lines survive in the redacted thread (exact-line *and* substring),
>    and 212/212 lines in `songs/*.md` are byte-exact slices — yet ~50 lyric lines
>    reach the model anyway, through `service-report.json`. See §4.5 and `bs-vhp`.
> 2. **The model narrates the redaction to the minister as a fault.** It wrote that
>    the email "didn't actually contain any lyrics … which is an unusual way for that
>    to happen". The `[LYRICS: …]` line has to explain itself, or the system prompt
>    has to say this is normal, or every reply carries a spurious apology.

**This is the one that should gate implementation**, and it does not depend on
reproducing the original failure.

Take the 7/26 thread from `examples/flowcharts.md`, run it through the §4 pipeline,
and put the **redacted** result in front of cloud Sonnet as a full agent run. Confirm
it builds the deck and writes the reply with no 400.

Why this and not a reproduction attempt: the redacted output still contains song
*titles* ("Goodness of God", "All Hail King Jesus") and `[LYRICS: …]` reference lines,
and the model still has to reason about a service full of copyrighted songs. **If the
trigger is broader than verbatim lyric lines, zero leaked lines does not buy safety.**
That is the assumption this design rests on and it is currently untested.

- Redacted arm **passes** ⇒ direct evidence the design works. Proceed.
- Redacted arm **fails** ⇒ the design is wrong regardless, and we learned it before
  touching `tools.py`.

### 7.2 The raw arm — nearly free, run it alongside

Same thread, unredacted. If it 400s, that is a **regression test** — the first
reproduction we have ever had. Note the synthetic cloud arm in §2.1 *passed*, so this
may not reproduce; the incident was days earlier and filter behaviour may have moved.
A negative result is informative, not a blocker.

### 7.3 Consensus against a real email

> **RUN 2026-08-01 (`bs-2pn`). The §4.2 numbers did not survive contact.** Pointed at
> the real 262-line reply, **0 of 7 runs produced a spec `validate_spec` would accept**
> — against 6/7 on the synthetic. The pipeline failed closed on the one email it was
> built for.
>
> Every rejection was the same mechanical error: the `end` of a song's last section
> ran long, into the next song's first line (5/7, always line 77) or past EOF (2/7).
> The songs, titles and bulk of the ranges were right in every run. Four fixes, each
> measured, now in `tests/probes/`:
>
> | change | effect |
> |---|---|
> | prompt states the end-boundary rule explicitly | 0/7 → 2/5 valid |
> | `repair_spec` repairs rather than bins a spec | 2/5 → **7/7 usable** |
> | consensus splits *"is it a lyric?"* (union) from *"whose is it?"* (per-line majority) | stops one over-long range swallowing a whole song |
> | blank lines are never claimed | restores stanza structure |
>
> Final on the real email: **K≥1 … K≥3 all leak 0**, 212/212 verbatim, six songs,
> correct titles, correct stanza structure. Two numbers to carry forward:
>
> - **~40s per call, not 6.3s.** That figure was measured on the small synthetic; the
>   real email is 262 lines. N=7 is ~4 minutes of preprocessing, which is why
>   `LOCAL_LLM_TIMEOUT_SECONDS` must be separate from the agent budget (§6).
> - **Over-claimed prose lands *inside* a song file**, not merely "destroyed". The
>   swallowed `ONE DAY lyrics:` label became a section of `the-lord-will-provide.md`,
>   i.e. a line that would have gone on the wall. §4.2 undersells this cost. The
>   frontier model did notice and strip it, but relying on that is relying on the
>   thing this design exists to avoid depending on.

§4.2's numbers come from a synthetic hostile fixture. Re-run `probe_consensus.py`
against the real 7/26 text, which has exactly the awkward shape this is meant to
survive: `"ONe change: I will do 'All Hail King Jesus' instead of 'No body.'"` sitting
directly against `"The Lord Will Provide lyrics:"`. Tune N and K there, not on the
synthetic.

### 7.4 The bypass test

Assert that `get_message` on a message in a redacted thread cannot return lyric text
(§4.3).

---

## 8. Failure semantics

Follows the existing pattern: deciding *nothing* is an error (`harness.py:237`,
`bs-tiz.4`).

- **No valid spec after N runs** ⇒ fail closed. Do not hand the frontier model the
  unredacted thread. Route to the `bs-9ed` apology.
- **Local model unreachable** ⇒ same. This design puts the homelab box on the critical
  path for every lyric-bearing email, which is a real availability downgrade and the
  reason `bs-7sb` matters more now, not less.
- **Truncated response** (`finish_reason == "length"`) ⇒ an error, never "no lyrics
  found". Failing open here silently disables the entire protection.
- **Over-claimed prose** ⇒ not a failure. Report it in the reply so the minister can
  correct it.

---

## 9. Open questions

1. ~~**Does the redacted thread clear the filter?**~~ **Answered as a rate, 2026-08-02:
   6 of 7 runs cleared it; 6/6 on the corrected redaction.** Good enough to keep
   building, not good enough to call solved — see §7.1 for why the one failure does
   not separate "base rate ~15%" from "the redaction quality mattered".
1a. **Can the tool → model channel be closed?** `bs-vhp`, §4.5. Newly found and
   arguably now the binding constraint: the build report hands the model ~50
   copyrighted lyric lines regardless of how clean the email is.
2. **Would a better quant collapse N to 1–2?** §3.1. Cheapest available win; the
   config in §6 exists so this can be answered by measurement rather than redesign.
3. **Mixed lines** — build the `start_col` trims (§4.4), or accept the prose cost and
   report it?
4. **Attachments.** `SYSTEM_PROMPT` step 5 currently tells the *frontier* model to
   convert PDFs and Word docs itself. If lyrics arrive as an attachment that pulls
   them straight into frontier context and bypasses all of the above. Attachment→text
   must move to the local side of the boundary. **Not yet designed.**
5. **Trigger heuristic.** Should `ingest_thread` run on every thread, or only when the
   body looks lyric-bearing? Over-triggering costs ~45s; under-triggering leaks. If
   used at all, tune it conservatively — and note it cannot be "only when a cloud
   model would refuse", since you cannot know that without looking.
