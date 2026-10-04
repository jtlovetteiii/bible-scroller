# bs-tiz.7 — Agent SDK spike findings

**Date:** 2026-07-11 · **SDK:** `claude-agent-sdk` 0.2.116 · **Model:** `claude-sonnet-5`
**Verdict: all three assumptions GREEN.** The harness design in `specs/email-agent.md` rests on proven ground.

Reproduce with `cd agent && uv run python spike/spike.py all`.

## 1. Subscription billing — GREEN

A headless `query()` with `CLAUDE_CODE_OAUTH_TOKEN` set and `ANTHROPIC_API_KEY` unset
is billed to the **subscription**.

**How we know — and the trap we nearly fell into.** The obvious signal, `total_cost_usd`
on the `ResultMessage`, is *worthless for this question*: Claude Code reports a cost
**estimate** on every run regardless of which account pays. The first version of this
spike treated a non-zero cost as evidence of pay-per-token billing and would have sent
someone chasing a problem that did not exist.

The real signal is `RateLimitEvent.rate_limit_type`. Observed value: **`five_hour`**.
Five-hour and seven-day windows are *subscription* rate-limit windows; a pay-per-token
API account is limited per-minute and never reports these. `spike.py` now asserts on
this and explicitly ignores `total_cost_usd`.

The foot-gun in the spec is real but is now guarded in code, not just documented:
`config.assert_subscription_auth()` hard-fails at startup if `ANTHROPIC_API_KEY` is
present, because it silently outranks the OAuth token.

## 2. Cross-process session resume — GREEN

`session_id` is carried on the init `SystemMessage` (`msg.data["session_id"]`). Passing
it to `ClaudeAgentOptions(resume=...)` in a **separate OS process** restores prior
context: process 1 was told the invitation hymn was "Just As I Am" #417; process 2,
resuming only from the persisted ID, answered correctly with no other context.

The resumed run keeps the **same** `session_id` (it does not mint a new one), so the
dispatcher's `threadId → session_id` mapping is stable across replies.

This check re-execs itself as a subprocess in `all` mode. That is deliberate: proving
resume *within* one process would prove nothing, since in-memory state would carry the
context for free and produce a false green.

## 3. Skill loading from `.claude/` — GREEN

With `setting_sources=["project"]`, the SDK sees the repo's `.claude/` directory and the
agent lists `gen_service, gen_slides, prep_sermon`.

**`setting_sources` is not optional and its failure mode is silent.** Omit it and the SDK
loads no project settings at all — the skills simply do not exist, the agent has nothing
to dispatch to, and nothing errors. `harness.py` sets it explicitly.

## Incidental findings

- `ClaudeAgentOptions` has a dedicated **`skills`** field alongside `setting_sources`.
  Worth a look during **bs-tiz.8** (migrating `gen_service` to `SKILL.md`) — it may allow
  loading skills without pulling in all project settings.
- `permission_mode="bypassPermissions"` is required for headless operation. There is no
  human to approve a tool prompt; without it a run can stall waiting for an approval that
  can never come.
- `AskUserQuestion` exists as a built-in SDK tool but must **not** be exposed to this
  agent — there is no interactive user, so a call to it would hang the run until the
  timeout. This reinforces the non-interactive/report design in `bs-ixn`.
