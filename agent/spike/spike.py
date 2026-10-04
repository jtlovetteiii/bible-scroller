"""bs-tiz.7 — prove the three Agent SDK primitives the design rests on.

Each check is a separate subcommand so that the session-resume check is proven
across two genuinely separate OS processes (proving it inside one process would
prove nothing — in-memory state would carry the context for free).

    cd agent
    uv run python spike/spike.py auth
    uv run python spike/spike.py session-start     # writes .session_id
    uv run python spike/spike.py session-resume    # separate process, must recall
    uv run python spike/spike.py skill
    uv run python spike/spike.py all

Findings are appended to spike/FINDINGS.md.
"""

from __future__ import annotations

import anyio
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    RateLimitEvent,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    query,
)

from email_agent.config import REPO_ROOT, assert_agent_auth  # noqa: E402

SESSION_FILE = Path(__file__).parent / ".session_id"
MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-5")

# A fact the model cannot know unless prior context was genuinely restored.
SECRET = "the invitation hymn is Just As I Am, hymn number 417"


async def _run(prompt: str, **opts) -> tuple[str, str | None, ResultMessage | None, str | None]:
    """Run one query. Returns (assistant text, session_id, result, rate_limit_type)."""
    text: list[str] = []
    session_id: str | None = None
    result: ResultMessage | None = None
    rate_limit_type: str | None = None

    async for msg in query(
        prompt=prompt,
        options=ClaudeAgentOptions(model=MODEL, cwd=str(REPO_ROOT), **opts),
    ):
        # The init SystemMessage carries the session_id we must persist.
        if isinstance(msg, SystemMessage):
            sid = (msg.data or {}).get("session_id")
            if sid:
                session_id = sid
        elif isinstance(msg, RateLimitEvent):
            info = getattr(msg, "rate_limit_info", msg)
            rate_limit_type = getattr(info, "rate_limit_type", None)
        elif isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    text.append(block.text)
        elif isinstance(msg, ResultMessage):
            result = msg
            session_id = session_id or getattr(msg, "session_id", None)

    return "\n".join(text).strip(), session_id, result, rate_limit_type


#: Rate-limit windows that only a Claude subscription has. A pay-per-token API
#: account is limited per-minute (tokens/requests), never on a five-hour or
#: seven-day window — so seeing one of these is positive proof the run was billed
#: to the subscription.
SUBSCRIPTION_WINDOWS = {"five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet"}


def _billing_verdict(rate_limit_type: str | None, result: ResultMessage | None) -> tuple[bool, str]:
    """Decide whether the run was billed to the subscription.

    NOTE: do NOT use `total_cost_usd` for this. Claude Code reports a cost
    *estimate* on every run regardless of billing mode, so a non-zero cost says
    nothing about which account paid. The rate-limit window is the real signal.
    """
    usd = getattr(result, "total_cost_usd", None)
    note = f"(total_cost_usd={usd} is an estimate, reported either way — ignore it)"
    if rate_limit_type in SUBSCRIPTION_WINDOWS:
        return True, f"rate_limit_type={rate_limit_type!r} -> SUBSCRIPTION billing {note}"
    if rate_limit_type is None:
        return False, f"no RateLimitEvent seen — cannot confirm subscription billing {note}"
    return False, f"rate_limit_type={rate_limit_type!r} is not a subscription window {note}"


async def check_auth() -> bool:
    print("\n=== 1. AUTH: headless query bills the subscription ===")
    assert_agent_auth()  # raises if ANTHROPIC_API_KEY set / token missing
    print("  env guard passed: ANTHROPIC_API_KEY unset, CLAUDE_CODE_OAUTH_TOKEN set")

    text, sid, result, rlt = await _run("Reply with exactly the word: PONG")
    billed_to_subscription, why = _billing_verdict(rlt, result)
    print(f"  model     : {MODEL}")
    print(f"  response  : {text[:80]!r}")
    print(f"  session_id: {sid}")
    print(f"  billing   : {why}")
    # Both must hold: the query worked AND it was billed to the subscription.
    # Cost control is the entire reason this epic runs on Sonnet.
    ok = "PONG" in text.upper() and billed_to_subscription
    print(f"  -> {'GREEN' if ok else 'RED'}")
    return ok


async def check_session_start() -> bool:
    print("\n=== 2a. SESSION: start (process 1) ===")
    text, sid, _, _ = await _run(
        f"Remember this for later, it matters: {SECRET}. Just acknowledge briefly."
    )
    if not sid:
        print("  -> RED: no session_id returned")
        return False
    SESSION_FILE.write_text(sid)
    print(f"  told the model: {SECRET!r}")
    print(f"  response      : {text[:80]!r}")
    print(f"  session_id    : {sid}  (saved to {SESSION_FILE.name})")
    print("  -> GREEN (now run `session-resume` in a SEPARATE process)")
    return True


async def check_session_resume() -> bool:
    print("\n=== 2b. SESSION: resume in a separate process ===")
    if not SESSION_FILE.exists():
        print("  -> RED: no saved session_id. Run `session-start` first.")
        return False
    sid = SESSION_FILE.read_text().strip()
    print(f"  resuming  : {sid}")

    text, new_sid, _, _ = await _run(
        "Without any preamble: which hymn did I say was the invitation, "
        "and what is its number?",
        resume=sid,
    )
    print(f"  response  : {text[:120]!r}")
    lowered = text.lower()
    ok = "just as i am" in lowered and "417" in lowered
    print(f"  session_id after resume: {new_sid}")
    print(f"  -> {'GREEN: prior context restored across processes' if ok else 'RED: context NOT restored'}")
    return ok


async def check_skill() -> bool:
    """gen_service must load from .claude/ inside an SDK query.

    setting_sources=['project'] is what makes the SDK read the repo's .claude/
    directory. Without it the SDK loads NO project settings and the skill is
    invisible — this is the single most likely silent failure in the design.
    """
    print("\n=== 3. SKILL: gen_service loads from .claude/ ===")
    text, _, _, _ = await _run(
        "List the names of the custom slash commands/skills you can see from this "
        "project's .claude directory. Just the names, comma separated. Do not run them.",
        setting_sources=["project"],
        max_turns=3,
    )
    print(f"  response: {text[:200]!r}")
    ok = "gen_service" in text
    print(f"  -> {'GREEN: gen_service visible' if ok else 'RED: gen_service NOT visible'}")
    return ok


async def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    checks = {
        "auth": check_auth,
        "session-start": check_session_start,
        "session-resume": check_session_resume,
        "skill": check_skill,
    }

    if cmd == "all":
        results = {}
        for name in ("auth", "session-start", "session-resume", "skill"):
            try:
                if name == "session-resume":
                    # Must be a genuinely separate OS process, or this check is
                    # worthless: in-process state would restore the context for
                    # free and we'd get a false green.
                    proc = subprocess.run(
                        [sys.executable, __file__, "session-resume"],
                        cwd=Path(__file__).parent.parent,
                    )
                    results[name] = proc.returncode == 0
                    continue
                results[name] = await checks[name]()
            except Exception as exc:  # noqa: BLE001
                print(f"  -> RED (exception): {type(exc).__name__}: {exc}")
                results[name] = False
        print("\n=== SUMMARY ===")
        for name, ok in results.items():
            print(f"  {'GREEN' if ok else 'RED  '}  {name}")
        sys.exit(0 if all(results.values()) else 1)

    if cmd not in checks:
        print(f"unknown check {cmd!r}; expected one of {list(checks)} or 'all'")
        sys.exit(2)
    sys.exit(0 if await checks[cmd]() else 1)


if __name__ == "__main__":
    anyio.run(main)
