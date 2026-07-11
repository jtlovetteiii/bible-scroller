"""bs-tiz.4 — the agent harness.

Satisfies the ``RunAgent`` protocol in ``dispatcher.py``: IDs in, session ID out.

Deliberately **not** a ``gen_service`` wrapper. The agent is a general
"handle-an-email" harness that is handed the Gmail tools plus whatever skills the
project exposes, and is told to work out the intent itself. Today the only skill
it drives is ``gen_service``; adding a second one must not require touching this
file (spec §1, §4.4).
"""

from __future__ import annotations

import anyio
import logging

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    ToolUseBlock,
    query,
)

from .config import REPO_ROOT, config, assert_subscription_auth
from .tools import GMAIL_TOOL_NAMES, gmail_tools_server

logger = logging.getLogger(__name__)

SEND_REPLY_TOOL = "mcp__gmail__send_reply"

SYSTEM_PROMPT = f"""\
You are an assistant handling email on behalf of the operator who builds the slides \
for a church service. A message has arrived that is addressed to you. Your job is to \
work out what is being asked and do it, end to end, without a human in the loop.

You have Gmail tools to read the message, list and save its attachments, and send \
exactly one reply. You also have this project's skills available as slash commands; \
read the message first, then decide which (if any) applies. Right now the main one is \
`gen_service`, which builds a service slide deck from an order of service.

Non-negotiable rules:

1. THERE IS NO INTERACTIVE USER. Never ask a question and wait — nobody will answer, \
and the run will simply hang. Anything you would have asked becomes a line in your \
reply instead.
2. You MUST finish by sending exactly one reply, in-thread, with `{SEND_REPLY_TOOL}`. \
That reply is the entire product of this run. If you cannot do the work, reply \
explaining what you need. Never finish silently.
3. NEVER show the congregation something you are unsure of. If you lack lyrics for a \
song, do not invent them: build what you safely can, and ask for the missing lyrics in \
your reply.
4. The tools do not convert attachments. If a PDF or Word document arrives, save it and \
convert it yourself.

Write the reply as a person would: what you built, a link to it, what you want checked, \
and what you still need. Not a status dump.

The repo is at {REPO_ROOT}. Decks are served at {config.public_base_url}.
"""


class AgentError(RuntimeError):
    """Raised on any failure. The dispatcher turns this into `failed` + released claim."""


async def _run(thread_id: str, msg_id: str, session_id: str | None) -> str | None:
    assert_subscription_auth()

    options = ClaudeAgentOptions(
        model=config.agent_model,
        cwd=str(REPO_ROOT),
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"gmail": gmail_tools_server()},
        # setting_sources=["project"] is what makes the SDK read the repo's
        # .claude/ directory. Without it the skills are invisible and the agent
        # silently has nothing to dispatch to.
        setting_sources=["project"],
        allowed_tools=[
            *GMAIL_TOOL_NAMES,
            "Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebSearch", "WebFetch",
        ],
        permission_mode="bypassPermissions",  # headless: nobody can approve a prompt
        resume=session_id,
    )

    prompt = (
        f"A new message (id {msg_id}) has arrived in thread {thread_id}. "
        f"Read it and handle it, then reply in-thread."
        if session_id is None
        else f"A reply (message id {msg_id}) has arrived in thread {thread_id}, which "
        f"you have worked on before. Read it and respond appropriately, then reply "
        f"in-thread."
    )

    new_session_id: str | None = session_id
    replied = False
    result: ResultMessage | None = None

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, SystemMessage):
            sid = (message.data or {}).get("session_id")
            if sid:
                new_session_id = sid
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock) and block.name == SEND_REPLY_TOOL:
                    replied = True
        elif isinstance(message, ResultMessage):
            result = message
            new_session_id = new_session_id or getattr(message, "session_id", None)

    if result is not None and getattr(result, "is_error", False):
        raise AgentError(f"agent run errored: {getattr(result, 'result', result)!r}")

    # The dispatcher treats our return as the commit point — it marks the message
    # processed and will never look at it again. Returning without having sent the
    # reply would strand the request in silence, so this is a hard failure: the
    # thread goes to `failed`, the claim releases, and the message is retried.
    if not replied:
        raise AgentError(
            f"agent finished without calling {SEND_REPLY_TOOL} — no reply was sent for "
            f"message {msg_id}, so the request would be silently dropped."
        )

    if new_session_id is None:
        raise AgentError("agent run produced no session_id; cannot resume this thread")

    return new_session_id


def run_agent(thread_id: str, msg_id: str, session_id: str | None) -> str | None:
    """Sync entry point matching the dispatcher's ``RunAgent`` protocol."""

    async def _with_timeout() -> str | None:
        with anyio.fail_after(config.agent_timeout_seconds):
            return await _run(thread_id, msg_id, session_id)

    try:
        return anyio.run(_with_timeout)
    except TimeoutError as exc:
        raise AgentError(
            f"agent run exceeded {config.agent_timeout_seconds}s for message {msg_id}"
        ) from exc
