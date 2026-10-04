# Content-filter / copyright probes

> **⚠ SHELVED 2026-08-02 along with the design they produced.** The content filter
> was resolved by routing runs at a non-Anthropic endpoint (`AGENT_BASE_URL`) rather
> than by changing the pipeline — see `specs/lyric-ingestion.md` for the full note.
> These probes remain valid evidence and are worth re-reading before anyone
> re-opens the question; they are not part of any live code path.

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
| `probe_offsets.py` | one call → spec → deterministic apply |
| `probe_consensus.py` | N calls → consensus → deterministic apply. **The current design.** |
| `fixture_0726.py` | **pure.** Slices the real 7/26 thread out of `examples/flowcharts.md` |
| `probe_gate.py` | **the gate** (spec §7.1/§7.2) — a full cloud agent run over the redacted thread |
| `verify_0726.py` | **pure.** Checks a finished run against `bs-2pn`'s acceptance criteria |

The deterministic half no longer lives here. `lyric_offsets.py` and
`lyric_consensus.py` were promoted on 2026-08-02 to
**`src/email_agent/lyrics/{offsets,consensus}.py`** and are pinned by
`tests/test_lyric_repair.py` and `tests/test_lyric_pipeline.py`. Import them as
`from email_agent.lyrics import ...`; the probes here do.

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

## The real 7/26 email (2026-08-02, `bs-2pn`)

Everything above this line was measured on the **synthetic** fixture. Against the real
262-line email the numbers did not hold, and the gate has now been run. Both results
are written up in `specs/lyric-ingestion.md` §7.1 and §7.3 — read those, not this
summary — but the two headlines:

- **The consensus needed real work.** 0 of 7 runs produced an acceptable spec, always
  for the same reason (a song's last section running long). After a prompt fix,
  `repair_spec`, per-line ownership and not claiming blank lines: **K≥1…K≥3 leak 0**,
  212/212 verbatim, six songs. Calls cost **~40s each here, not 6.3s** — that figure
  was the small synthetic.
- **The gate is not a yes/no.** The same redacted thread 400'd once and built a
  complete deck the next time. Use `probe_gate.py --repeat` and read the *rate*; a
  single green run is not evidence.

Re-scoring the consensus does not need the model — cache the specs once and iterate
offline:

```bash
LOCAL_LLM_BASE_URL=http://100.66.185.49:8080 \
  uv run python -u tests/probes/probe_consensus.py --fixture 0726 -n 7 \
    --save-specs /tmp/specs.json --out-dir /tmp/gate
uv run python -u tests/probes/probe_consensus.py --fixture 0726 -n 7 --sweep \
    --load-specs /tmp/specs.json          # no model calls
uv run python -u tests/probes/probe_gate.py --in-dir /tmp/gate --arm redacted \
    --repeat 5 --keep-workspaces /tmp/ws  # costs real cloud runs
```

## Caveat on all of the above

**The trigger is still not isolated, and it is now clear it is not deterministic.**
The cloud arm of `probe_filter.py` *passes*, while the real incident blocked 6/6 — and
`bs-a1f` attempt 3 blocked on the first assistant turn after `get_thread` having
written nothing at all.

2026-08-02 added a third observation that does not fit either: a **redacted** thread —
independently verified to contain 0 of 128 lyric lines — was blocked once and then
cleared the filter on repeated runs of the same input. So "lyrics are present" is not
the trigger, and neither is any other pure function of the text.

The raw arm (§7.2) has **not** been run yet; the one 400 seen so far was on the
redacted thread, which is the more surprising direction. Treat any single run, in
either direction, as an anecdote — `probe_gate.py --repeat` exists for this.
