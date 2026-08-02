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
import collections
import logging
from collections.abc import Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from .config import REPO_ROOT, config, assert_agent_auth
from .publish import PUBLISH_TOOL_NAMES, publish_tools_server
from .tools import GMAIL_TOOL_NAMES, gmail_tools_server

logger = logging.getLogger(__name__)

SEND_REPLY_TOOL = "mcp__gmail__send_reply"
SKIP_REPLY_TOOL = "mcp__gmail__skip_reply"
GET_THREAD_TOOL = "mcp__gmail__get_thread"
PUBLISH_DECK_TOOL = "mcp__deck__publish_deck"

#: A run must end in exactly one of these. Both are success; neither is.
TERMINAL_TOOLS = {SEND_REPLY_TOOL, SKIP_REPLY_TOOL}

SYSTEM_PROMPT = f"""\
You are an assistant handling email on behalf of the operator who builds the slides \
for a church service. Something has arrived on an email thread. Your job is to work out \
what — if anything — is being asked, and to do it, end to end, without a human in the loop.

You have Gmail tools to read the thread, save its attachments, and either reply or \
deliberately not reply. You also have this project's skills as slash commands; the main \
one is `gen_service`, which builds a service slide deck from an order of service.

How to work:

1. FIRST, read the whole conversation with `{GET_THREAD_TOOL}`. Not just the newest \
message — the thread. You cannot judge what is needed from one message in isolation: you \
may have already answered it, it may be a message you wrote yourself, or it may be a \
"thanks!" that closes the conversation out.

2. THEN decide whether the thread actually needs anything from you. This is a real \
decision and you are expected to make it, not a formality:
   - It needs a reply -> do the work, then `{SEND_REPLY_TOOL}`.
   - It needs nothing -> `{SKIP_REPLY_TOOL}` with your reason.
   Every run must end with exactly one of those two. Never just stop.

   Do NOT reply out of politeness. A reply that adds nothing still lands in a real \
person's inbox — and if the message you are "replying" to is one of your own, you are \
talking to yourself and can start an endless loop of replies to replies. When in doubt \
about whether a reply adds value, skip.

   The thread marks messages you wrote with `authored_by_agent`. That flag is a hint \
drawn from our local records, and those records can be incomplete — a message can be \
yours even when the flag says false. So read the text and judge for yourself: if the \
newest message is plainly your own work (your deck link, your report, your questions), \
that is the fact that matters, whatever the flag says.

3. THERE IS NO INTERACTIVE USER. Never ask a question and wait — nobody will answer and \
the run will hang. Anything you would have asked becomes a line in your reply.

4. NEVER show the congregation something you are unsure of. If you lack lyrics for a \
song, do not invent them: build what you safely can, and ask for the missing lyrics in \
your reply.

5. The tools do not convert attachments. If a PDF or Word document arrives, save it and \
convert it yourself.

6. A deck the minister cannot open is not a delivered deck. When you have built one and \
are about to reply about it, publish it with `{PUBLISH_DECK_TOOL}` and put the URL it \
returns in your email. Pass it the deck JSON, not the preview HTML — the local preview's \
images only resolve against a local server, so a link to it would open as a deck with \
every background missing. Re-publishing a corrected deck for the same date replaces it \
at the same URL, so a link you already sent keeps working and shows the fix.

When you do reply, write as a person would: what you built, a link to it, what you want \
checked, what you still need. Not a status dump.

The repo is at {REPO_ROOT}. Published decks are served at {config.deck_base_url}.
"""


class AgentError(RuntimeError):
    """Raised on any failure. The dispatcher turns this into `failed` + released claim."""


#: How many trailing lines of the bundled CLI's stderr to keep. The CLI's own
#: error text lands there, not in our exceptions: when it exits non-zero with an
#: empty error body the SDK can only report the result subtype — on the
#: deployment host that surfaced as the literal, useless word "success". A tail
#: is enough (the real message is at the end) and bounds memory on a chatty run.
STDERR_TAIL_LINES = 50


def _stderr_capture(
    thread_id: str, msg_id: str, sink: collections.deque[str]
) -> Callable[[str], None]:
    """Build the ``ClaudeAgentOptions.stderr`` callback for one run.

    The SDK pipes the CLI's stderr only when this callback is set
    (``subprocess_cli.py``); otherwise the child inherits our stderr and — as
    seen on the homelab box, where the journal caught nothing — the real error
    can vanish. Capture each line into ``sink`` for a tail dumped iff the run
    fails, and mirror it to DEBUG so a healthy run stays quiet.
    """

    def capture(line: str) -> None:
        line = line.rstrip("\n")
        if not line:
            return
        sink.append(line)
        logger.debug("claude-cli stderr [thread %s msg %s]: %s", thread_id, msg_id, line)

    return capture


async def _run(thread_id: str, msg_id: str, session_id: str | None) -> str | None:
    assert_agent_auth()

    if config.uses_alternate_backend:
        # Log the endpoint, never the token. Which backend served a run is the
        # first thing you need when reading back a transcript that looks wrong,
        # and today the journal has no other way to tell.
        logger.info(
            "thread %s: routing to %s (model %s)",
            thread_id, config.agent_base_url, config.agent_model,
        )

    cli_stderr: collections.deque[str] = collections.deque(maxlen=STDERR_TAIL_LINES)

    options = ClaudeAgentOptions(
        model=config.agent_model,
        cwd=str(REPO_ROOT),
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"gmail": gmail_tools_server(), "deck": publish_tools_server()},
        # setting_sources=["project"] is what makes the SDK read the repo's
        # .claude/ directory. Without it the skills are invisible and the agent
        # silently has nothing to dispatch to.
        setting_sources=["project"],
        allowed_tools=[
            *GMAIL_TOOL_NAMES,
            *PUBLISH_TOOL_NAMES,
            "Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebSearch", "WebFetch",
        ],
        permission_mode="bypassPermissions",  # headless: nobody can approve a prompt
        resume=session_id,
        # Empty on the default path. When AGENT_BASE_URL is set this redirects the
        # CLI subprocess — and only it — at that endpoint; the SDK merges this over
        # the inherited environment, so these keys win. See config.agent_env().
        env=config.agent_env(),
        # Without this the CLI's stderr is not piped to us at all — the failure
        # that prompted this (bs-zwj) was opaque precisely because we never asked
        # for it.
        stderr=_stderr_capture(thread_id, msg_id, cli_stderr),
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
    terminal: set[str] = set()
    result: ResultMessage | None = None
    #: The model's last text block. When the CLI aborts a turn on an API-level
    #: error (e.g. a content-filter block), it delivers that as the assistant's
    #: final words — "API Error: 400 Output blocked by content filtering policy"
    #: — then exits non-zero with an *empty* error body. The SDK can only echo
    #: the result subtype, which on this host surfaced as the literal, useless
    #: word "success" (bs-zwj). Keep the real message so we can raise with it.
    last_text: str | None = None

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, SystemMessage):
                sid = (message.data or {}).get("session_id")
                if sid:
                    new_session_id = sid
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock) and block.name in TERMINAL_TOOLS:
                        terminal.add(block.name)
                    elif isinstance(block, TextBlock) and block.text.strip():
                        last_text = block.text.strip()
            elif isinstance(message, ResultMessage):
                result = message
                new_session_id = new_session_id or getattr(message, "session_id", None)

        if result is not None and getattr(result, "is_error", False):
            raise AgentError(f"agent run errored: {getattr(result, 'result', result)!r}")
    except BaseException as exc:
        # BaseException, not Exception: a timeout cancels this scope with
        # CancelledError, and the CLI's dying words are exactly what you want
        # when a run wedged. We only log and re-raise — the dispatcher still owns
        # the failure. Logged here, next to the cause, rather than left for the
        # operator to reconstruct from journal timestamps.
        if cli_stderr:
            logger.error(
                "claude-cli stderr tail for thread %s msg %s (%d line[s]):\n%s",
                thread_id, msg_id, len(cli_stderr), "\n".join(cli_stderr),
            )
        # An API-level abort (content filter, overload, etc.) leaves the CLI's
        # error body empty, so the SDK's exception degrades to a bare subtype
        # like "success" — useless in the journal. The real reason is the
        # model's last words; re-raise with those. Only for a genuine Exception:
        # a CancelledError (timeout) must propagate untouched, and its final
        # text would be misleading anyway.
        if (
            isinstance(exc, Exception)
            and not isinstance(exc, AgentError)
            and last_text
            and last_text.startswith("API Error")
        ):
            raise AgentError(
                f"agent run aborted by an API error: {last_text}"
            ) from exc
        raise

    # A run must end in a deliberate terminal action: it either replied, or it
    # decided a reply was not warranted. Deciding NOT to reply is a legitimate
    # outcome, not a failure — that judgment is the agent's to make, and forcing a
    # reply is what let it answer its own messages in the first place.
    #
    # What we still refuse to accept is a run that ends having decided *nothing*.
    # The dispatcher treats our return as the commit point and will never look at
    # this message again, so a silent finish means the request is dropped without
    # anyone noticing. That is a hard failure: the thread goes to `failed`, the
    # claim releases, and the message is retried.
    if not terminal:
        raise AgentError(
            f"agent finished without calling {SEND_REPLY_TOOL} or {SKIP_REPLY_TOOL} for "
            f"message {msg_id} — it neither replied nor decided not to, so the request "
            f"would be silently dropped."
        )

    if SKIP_REPLY_TOOL in terminal and SEND_REPLY_TOOL not in terminal:
        logger.info("thread %s: agent judged that no reply was needed", thread_id)

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
