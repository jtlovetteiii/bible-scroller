# Content-filter / copyright probes

> **The design these produced is written up in
> [`specs/lyric-ingestion.md`](../../../specs/lyric-ingestion.md).** Read that first;
> this file is the raw evidence behind it. Tracked as `bs-8qs`.

Diagnostic scripts, not tests. `pytest` does not collect them (`testpaths = ["tests"]`
with the default `test_*.py` pattern), and they cost real model calls — run them
deliberately.

## The files

| file | what it is |
|---|---|
| `probe_filter.py` | does a model reproduce copyrighted lyrics, refuse, or get filtered? |
| `probe_copy.py` | does deterministic copying sidestep the refusal? |
| `probe_intermediary.py` | the local model as an *agentic* intermediary — **failed**, see below |
| `lyric_offsets.py` | **pure, no network.** Numbering, prompt, spec parse/validate, slicing, redaction |
| `lyric_consensus.py` | **pure, no network.** Merges N specs by vote |
| `probe_offsets.py` | one call → spec → deterministic apply |
| `probe_consensus.py` | N calls → consensus → deterministic apply. **The current design.** |

`lyric_offsets.py` and `lyric_consensus.py` are real implementations, not throwaways —
they are the deterministic half, ready to promote into `src/email_agent/`.

## Calling the local model

Go **direct to llama.cpp**, not through UniClaudeProxy — the proxy drops
`chat_template_kwargs` (so reasoning cannot be disabled) and drops llama.cpp's separate
`reasoning_content` field (so a truncated call looks like an empty answer). See
`specs/lyric-ingestion.md` §3.2.

```bash
LOCAL_LLM_BASE_URL=http://100.66.185.49:8080 \
  uv run python -u tests/probes/probe_consensus.py -n 7 --sweep
```

The address is volatile — the `192.168.x` one does not route from outside the house.

They exist because the email agent's one unsolved failure mode is that the licensed
song lyrics the church is entitled to display cannot reliably be put through a
model. See `bs-a1f` (the incident), `bs-e4m` (the spike these came from) and
`bs-8qs` (the design they justify).

Nothing here writes into the repo and nothing sends email. Output goes to a temp
directory unless you pass `--out-dir`.

## Running

From `agent/`:

```bash
uv run python tests/probes/probe_filter.py --backend cloud
uv run python tests/probes/probe_filter.py --backend proxy --model gpt-5.6-terra
uv run python tests/probes/probe_copy.py   --backend cloud
uv run python tests/probes/probe_copy.py   --backend proxy --model gpt-5.6-terra
```

The proxy address is read from `FALLBACK_API_BASE_URL` and defaults to the homelab
UniClaudeProxy. That address is volatile — override it rather than editing the file.

## What they measured (2026-07-30)

`probe_filter.py` — reproduce two copyrighted songs' lyrics verbatim into a file.
Lyrics in context AND in output.

| backend | model | result |
|---|---|---|
| cloud | claude-sonnet-5 | **PASS** — 15.6s, Read/Read/Write, 53 lines verbatim, no filter |
| proxy | gpt-5.6-terra | **REFUSED**, deterministically 2/2 — *"Sorry, I can't reproduce or compile the complete lyrics of these copyrighted songs."* |

The refusal arrives with `is_error=False`, so the run looks successful and simply
produces nothing.

This falsified the premise behind `bs-dox`: reaching a non-Anthropic provider does
not clear the problem, because copyright-reproduction guardrails are an industry
norm rather than an Anthropic policy quirk. On this task Anthropic was the *more*
permissive provider.

`probe_copy.py` — the same job, but the model is forbidden from emitting lyric text
and told to move the bytes with shell instead.

| backend | model | result |
|---|---|---|
| proxy | gpt-5.6-terra | **PASS** — 1 Bash call, 6.4s, no refusal, no lyrics in model output |
| cloud | claude-sonnet-5 | **PASS** — 2 Bash calls, 12.9s, no refusal, no lyrics in model output |

**But note the caveat that shaped `bs-8qs`:** gpt-5.6-terra's shell one-liner produced
byte-exact lyrics while DUPLICATING stanza headings — 16 where 10 were correct
(`## Chorus`, `## Verse 2`, `## Bridge` each twice). Sonnet got it right only because
it ran a `grep -n` inspection pass first. Model-authored shell is not deterministic;
the probe therefore asserts on the heading count, and the real implementation must
use a fixed, golden-tested tool.

## Caveat on all of the above

None of this reproduces the actual 7/26 production failure. The cloud arm of
`probe_filter.py` *passes*, while the real incident blocked 6/6 — and `bs-a1f`
attempt 3 blocked on the first assistant turn after `get_thread` having written
nothing at all. Those two observations conflict, so the real trigger is narrower
than "lyrics are present" and has not been isolated. Build a fixture from the real
thread before trusting that any fix works.
