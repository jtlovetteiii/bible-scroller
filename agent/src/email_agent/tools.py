"""Deterministic Gmail tool surface for the agent (spec §4.3, bs-tiz.3).

Two layers, deliberately separated:

1. **Pure functions** (`get_message`, `list_attachments`, `get_attachment_binary`,
   `save_attachment`, `send_reply`) — plain Python, take an optional `service`
   argument so they are unit-testable against a fake Gmail service.
2. **A thin Claude Agent SDK wrapper layer** (`gmail_tools_server()`) — registers
   the same four operations as in-process MCP tools the agent can call.

Scope boundary: these tools stop at **bytes + metadata**. They never convert a
format (no PDF→text, no docx parsing). The agent is a filesystem agent and does
its own conversion after `save_attachment` puts the raw file on disk.
"""

from __future__ import annotations

import base64
import binascii
import html
import json
import logging
import mimetypes
import quopri
import re
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

logger = logging.getLogger(__name__)

from .config import config
from .gmail_client import gmail_service

USER_ID = "me"

#: Headers the agent and the in-thread reply logic need. Anything else is noise.
WANTED_HEADERS = (
    "Subject",
    "From",
    "To",
    "Cc",
    "Reply-To",
    "Date",
    "Message-ID",
    "References",
    "In-Reply-To",
)

_QP_HINT = re.compile(rb"=[0-9A-Fa-f]{2}|=\r?\n")


# ---------------------------------------------------------------------------
# low-level MIME helpers
# ---------------------------------------------------------------------------


def _svc(service: Any | None):
    return service if service is not None else gmail_service()


#: Sentinel: distinguishes "caller passed no store, use the real one" from
#: "caller explicitly passed None to disable the guard" (only tests should do that).
_DEFAULT = object()


def _store(store: Any):
    if store is _DEFAULT:
        from .store import StateStore  # local import: avoids a cycle at module load

        return StateStore(config.state_db_path)
    return store


def b64url_decode(data: str) -> bytes:
    """Decode Gmail's base64url payload strings (padding is often stripped)."""
    if not data:
        return b""
    s = data.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    try:
        return base64.b64decode(s)
    except (binascii.Error, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"Not valid base64url data: {exc}") from exc


def _header_map(part_or_message: dict[str, Any]) -> dict[str, str]:
    """Case-insensitive-ish header lookup keyed by lowercase name."""
    headers = part_or_message.get("headers") or []
    return {h.get("name", "").lower(): h.get("value", "") for h in headers}


def _charset(part: dict[str, Any]) -> str:
    """Charset from the part's Content-Type, defaulting to utf-8."""
    ctype = _header_map(part).get("content-type", "")
    m = re.search(r'charset="?([\w\-]+)"?', ctype, re.IGNORECASE)
    return m.group(1) if m else "utf-8"


def _part_text(part: dict[str, Any]) -> str:
    """Decode one text part's body to str.

    Gmail normally *already* undoes the Content-Transfer-Encoding, so `body.data`
    is base64url of the real bytes. But some parts (notably ones round-tripped
    through `format=raw`, or produced by odd senders) still carry live
    quoted-printable. So: decode base64url, and only then quopri-decode if the
    part *claims* quoted-printable AND the bytes still look encoded. That guard
    is what stops a normal message with a literal "=" in it being mangled.
    """
    raw = b64url_decode((part.get("body") or {}).get("data", ""))
    cte = _header_map(part).get("content-transfer-encoding", "").lower()
    if cte == "quoted-printable" and _QP_HINT.search(raw):
        raw = quopri.decodestring(raw)
    return raw.decode(_charset(part), errors="replace")


def _strip_html(markup: str) -> str:
    """Crude but dependency-free HTML → text. Only used when there is no text/plain."""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", markup)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", text)
    text = re.sub(r"(?i)<li\b[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def iter_parts(payload: dict[str, Any]):
    """Depth-first walk over a payload and every nested `parts` entry."""
    yield payload
    for child in payload.get("parts") or []:
        yield from iter_parts(child)


def _is_attachment(part: dict[str, Any]) -> bool:
    disposition = _header_map(part).get("content-disposition", "").lower()
    if disposition.startswith("attachment"):
        return True
    # Inline images referenced by a text/html part still count as attachments to us.
    body = part.get("body") or {}
    return bool(part.get("filename")) and bool(body.get("attachmentId"))


def extract_body(payload: dict[str, Any]) -> tuple[str, str]:
    """Return `(text, source_mime)` for a message payload.

    Prefers the first non-attachment `text/plain` part anywhere in the tree
    (handles multipart/alternative, multipart/mixed, and nesting of both). Falls
    back to the first `text/html` part with its tags stripped. Returns `("", "")`
    when the message is bodiless (e.g. attachment-only).
    """
    plain: dict[str, Any] | None = None
    html_part: dict[str, Any] | None = None

    for part in iter_parts(payload):
        mime = part.get("mimeType", "")
        if _is_attachment(part) or not (part.get("body") or {}).get("data"):
            continue
        if mime == "text/plain" and plain is None:
            plain = part
        elif mime == "text/html" and html_part is None:
            html_part = part

    if plain is not None:
        return _part_text(plain), "text/plain"
    if html_part is not None:
        return _strip_html(_part_text(html_part)), "text/html"
    return "", ""


# ---------------------------------------------------------------------------
# 1. get_message
# ---------------------------------------------------------------------------


def get_message(msg_id: str, *, service: Any | None = None) -> dict[str, Any]:
    """Fetch one message: the headers that matter, plus its plain-text body."""
    msg = (
        _svc(service)
        .users()
        .messages()
        .get(userId=USER_ID, id=msg_id, format="full")
        .execute()
    )
    payload = msg.get("payload") or {}
    headers = _header_map(payload)
    body, body_mime = extract_body(payload)

    return {
        "id": msg.get("id", msg_id),
        "threadId": msg.get("threadId"),
        "labelIds": msg.get("labelIds", []),
        "snippet": msg.get("snippet", ""),
        "headers": {name: headers.get(name.lower(), "") for name in WANTED_HEADERS},
        "body": body,
        "bodyMimeType": body_mime,
        "attachmentCount": sum(1 for p in iter_parts(payload) if _is_attachment(p)),
    }


# ---------------------------------------------------------------------------
# 2. list_attachments
# ---------------------------------------------------------------------------


def list_attachments(msg_id: str, *, service: Any | None = None) -> list[dict[str, Any]]:
    """Metadata for every attachment on a message. No bytes are fetched."""
    msg = (
        _svc(service)
        .users()
        .messages()
        .get(userId=USER_ID, id=msg_id, format="full")
        .execute()
    )
    out: list[dict[str, Any]] = []
    for part in iter_parts(msg.get("payload") or {}):
        if not _is_attachment(part):
            continue
        body = part.get("body") or {}
        filename = part.get("filename") or ""
        out.append(
            {
                "filename": filename,
                "extension": Path(filename).suffix.lower().lstrip("."),
                "mimeType": part.get("mimeType", ""),
                "size": body.get("size", 0),
                "attachmentId": body.get("attachmentId"),
                "partId": part.get("partId"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# 3. get_attachment_binary / save_attachment
# ---------------------------------------------------------------------------


def get_attachment_binary(
    msg_id: str, attachment_id: str, *, service: Any | None = None
) -> bytes:
    """Raw bytes of one attachment. No conversion — bytes exactly as sent."""
    if not attachment_id:
        raise ValueError(
            "attachment_id is required; get it from list_attachments()."
        )
    att = (
        _svc(service)
        .users()
        .messages()
        .attachments()
        .get(userId=USER_ID, messageId=msg_id, id=attachment_id)
        .execute()
    )
    return b64url_decode(att.get("data", ""))


def save_attachment(
    msg_id: str,
    attachment_id: str,
    dest_path: str | Path,
    *,
    service: Any | None = None,
) -> Path:
    """Write an attachment's raw bytes to `dest_path` and return the path."""
    data = get_attachment_binary(msg_id, attachment_id, service=service)
    path = Path(dest_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ---------------------------------------------------------------------------
# 4. send_reply  (RFC 2822 threading — the easy thing to get wrong)
# ---------------------------------------------------------------------------


def _thread_parent_headers(thread_id: str, *, service: Any | None = None) -> dict[str, str]:
    """Headers of the LAST message in a thread — the message we are replying to."""
    thread = (
        _svc(service)
        .users()
        .threads()
        .get(
            userId=USER_ID,
            id=thread_id,
            format="metadata",
            metadataHeaders=list(WANTED_HEADERS),
        )
        .execute()
    )
    messages = thread.get("messages") or []
    if not messages:
        raise ValueError(f"Thread {thread_id} has no messages to reply to.")
    return _header_map(messages[-1].get("payload") or {})


def reply_subject(parent_subject: str) -> str:
    """`Re: ` the subject once — never `Re: Re:`."""
    subject = (parent_subject or "").strip()
    if re.match(r"^re\s*:", subject, re.IGNORECASE):
        return subject
    return f"Re: {subject}" if subject else "Re:"


def build_reply_message(
    parent_headers: dict[str, str],
    body: str,
    attachments: list[str | Path] | None = None,
) -> EmailMessage:
    """Construct the RFC 2822 reply from the parent message's headers.

    Threading rules (all three are required for mail clients *and* Gmail to keep
    the conversation as one thread):
      * `In-Reply-To` = the parent's `Message-ID`, verbatim, angle brackets kept.
      * `References`  = the parent's `References` (if any) + the parent's
        `Message-ID` appended — the chain grows, it is never replaced.
      * `Subject`     = the parent subject with a single `Re: ` prefix.
    Gmail additionally needs `threadId` on the API call; that is done in
    `send_reply`, not here.
    """
    parent = {k.lower(): v for k, v in parent_headers.items()}
    message_id = (parent.get("message-id") or "").strip()

    msg = EmailMessage()
    msg["To"] = (parent.get("reply-to") or parent.get("from") or "").strip()
    msg["Subject"] = reply_subject(parent.get("subject", ""))
    if message_id:
        msg["In-Reply-To"] = message_id
        prior = (parent.get("references") or "").split()
        if message_id not in prior:
            prior.append(message_id)
        msg["References"] = " ".join(prior)

    msg.set_content(body)

    for raw_path in attachments or []:
        path = Path(raw_path).expanduser()
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
        msg.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype or "octet-stream",
            filename=path.name,
        )
    return msg


def get_thread(
    thread_id: str,
    *,
    service: Any | None = None,
    store: Any = _DEFAULT,
) -> dict[str, Any]:
    """The whole conversation, oldest first, with each message's body.

    The agent should read this before deciding anything. A single message in
    isolation cannot tell it whether the conversation is finished, whether it has
    already answered, or whether the newest message even asks for anything.

    `authored_by_agent` is a **hint, not a verdict**. It comes from the local
    store (messages we recorded at send time), so it is only as good as that
    store: wipe the DB and every flag reads False. Treat it as corroboration for
    a judgment the agent should be able to reach from the text anyway — if the
    last message is plainly our own reply, that should be evident from reading it.
    """
    svc = _svc(service)
    st = _store(store)

    thread = svc.users().threads().get(userId=USER_ID, id=thread_id, format="full").execute()
    messages = []
    for raw in thread.get("messages", []):
        payload = raw.get("payload") or {}
        headers = _header_map(payload)
        body, body_mime = extract_body(payload)

        authored = False
        if st is not None:
            try:
                authored = st.is_agent_sent(raw["id"])
            except Exception:  # noqa: BLE001
                logger.warning("authorship lookup failed for %s", raw["id"])

        messages.append(
            {
                "id": raw["id"],
                "authored_by_agent": authored,
                "headers": {n: headers.get(n.lower(), "") for n in WANTED_HEADERS},
                "body": body,
                "bodyMimeType": body_mime,
                "attachmentCount": sum(1 for p in iter_parts(payload) if _is_attachment(p)),
            }
        )

    return {"threadId": thread_id, "messageCount": len(messages), "messages": messages}


def send_reply(
    thread_id: str,
    body: str,
    attachments: list[str | Path] | None = None,
    *,
    service: Any | None = None,
    store: Any = _DEFAULT,
) -> dict[str, Any]:
    """Reply in-thread to the latest message of `thread_id`. Returns the sent message."""
    svc = _svc(service)
    store = _store(store)
    parent = _thread_parent_headers(thread_id, service=svc)
    msg = build_reply_message(parent, body, attachments)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = (
        svc.users()
        .messages()
        .send(userId=USER_ID, body={"raw": raw, "threadId": thread_id})
        .execute()
    )

    # Record that WE authored this, so the gate can never feed it back to us as a
    # new request. Our reply carries the thread's subject (`Re: AI: …`) and so
    # matches the subject regex exactly as well as the original — without this the
    # agent replies to itself forever. Sending is what matters; if the bookkeeping
    # fails we log loudly rather than fail the send (the reply is already gone),
    # but a failure here means the loop guard is off and must be treated as urgent.
    if store is not None and sent.get("id"):
        try:
            store.mark_agent_sent(thread_id, sent["id"])
        except Exception:  # noqa: BLE001
            logger.exception(
                "REPLY LOOP GUARD FAILED: could not record agent-sent message %s on "
                "thread %s. The gate may feed this reply back and cause a self-reply "
                "loop.",
                sent["id"],
                thread_id,
            )

    return sent


# ---------------------------------------------------------------------------
# Claude Agent SDK tool layer
# ---------------------------------------------------------------------------


def _ok(payload: Any) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    return {"content": [{"type": "text", "text": text}]}


def _err(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"ERROR: {message}"}], "is_error": True}


@tool(
    "get_message",
    (
        "Read one Gmail message: its headers and its body text.\n"
        "Input: msg_id (the Gmail message id, e.g. '18f2a...'). NOT the thread id.\n"
        "Returns JSON: id, threadId, headers (Subject, From, To, Cc, Reply-To, Date, "
        "Message-ID, References, In-Reply-To), body (plain text; HTML mail is "
        "tag-stripped), bodyMimeType, attachmentCount.\n"
        "The body does NOT include attachments. If attachmentCount > 0, call "
        "list_attachments next. Use the returned threadId when you later send_reply."
    ),
    {
        "type": "object",
        "properties": {
            "msg_id": {"type": "string", "description": "Gmail message id."}
        },
        "required": ["msg_id"],
    },
)
async def get_message_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return _ok(get_message(args["msg_id"]))
    except Exception as exc:  # noqa: BLE001 - surface the failure to the model
        return _err(f"get_message failed: {exc}")


@tool(
    "list_attachments",
    (
        "List the attachments on a Gmail message. METADATA ONLY — no file contents "
        "are downloaded and nothing is written to disk.\n"
        "Input: msg_id.\n"
        "Returns a JSON array of {filename, extension, mimeType, size (bytes), "
        "attachmentId}. An empty array means the message has no attachments.\n"
        "You need the attachmentId from here to call save_attachment."
    ),
    {
        "type": "object",
        "properties": {
            "msg_id": {"type": "string", "description": "Gmail message id."}
        },
        "required": ["msg_id"],
    },
)
async def list_attachments_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return _ok(list_attachments(args["msg_id"]))
    except Exception as exc:  # noqa: BLE001
        return _err(f"list_attachments failed: {exc}")


@tool(
    "save_attachment",
    (
        "Download one attachment's RAW BYTES and write them to a file on disk. "
        "Returns the absolute path it wrote.\n"
        "Inputs: msg_id, attachment_id (from list_attachments), dest_path (where to "
        "write; parent directories are created for you).\n"
        "IMPORTANT: this does NO conversion. A PDF lands as a .pdf, a .docx lands as "
        "a .docx — the bytes are exactly what the sender sent. Converting the file to "
        "text/markdown is YOUR job after this returns: read it, or install and run a "
        "converter with Bash. Give dest_path an extension matching the attachment's "
        "real filename so your converter recognises it."
    ),
    {
        "type": "object",
        "properties": {
            "msg_id": {"type": "string", "description": "Gmail message id."},
            "attachment_id": {
                "type": "string",
                "description": "attachmentId from list_attachments.",
            },
            "dest_path": {
                "type": "string",
                "description": "File path to write the raw bytes to.",
            },
        },
        "required": ["msg_id", "attachment_id", "dest_path"],
    },
)
async def save_attachment_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        path = save_attachment(args["msg_id"], args["attachment_id"], args["dest_path"])
        return _ok({"path": str(path.resolve()), "bytes": path.stat().st_size})
    except Exception as exc:  # noqa: BLE001
        return _err(f"save_attachment failed: {exc}")


@tool(
    "get_thread",
    (
        "Read the ENTIRE conversation, oldest message first, with each message's body. "
        "Call this FIRST, before deciding anything.\n"
        "A single message read in isolation cannot tell you whether the conversation is "
        "already finished, whether you have already answered it, or whether the newest "
        "message is even asking for anything. The thread can.\n"
        "Each message carries `authored_by_agent`: true means our records say WE wrote "
        "it. Treat that as a hint that corroborates your own reading, not as the whole "
        "answer — those records can be incomplete, so a message may be ours even when "
        "the flag is false. Read the text and judge for yourself."
    ),
    {
        "type": "object",
        "properties": {
            "thread_id": {"type": "string", "description": "Gmail threadId to read."},
        },
        "required": ["thread_id"],
    },
)
async def get_thread_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return _ok(get_thread(args["thread_id"]))
    except Exception as exc:  # noqa: BLE001
        return _err(f"get_thread failed: {exc}")


@tool(
    "skip_reply",
    (
        "Conclude the task WITHOUT sending any email, because no reply is warranted.\n"
        "This is a legitimate, expected outcome — not a failure. Use it when the newest "
        "message needs nothing from you: it is a message you yourself wrote; it is a "
        "bare acknowledgement ('thanks!', 'got it'); or the conversation is simply "
        "finished.\n"
        "Every task must end with EITHER send_reply OR skip_reply. Never just stop.\n"
        "Prefer skip_reply over sending a courtesy reply that adds nothing — a needless "
        "reply lands in a real person's inbox, and if the reply is to yourself it can "
        "start a loop of replies to replies."
    ),
    {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Briefly, why no reply is needed. Recorded in the logs.",
            },
        },
        "required": ["reason"],
    },
)
async def skip_reply_tool(args: dict[str, Any]) -> dict[str, Any]:
    reason = args.get("reason", "(none given)")
    logger.info("agent chose NOT to reply: %s", reason)
    return _ok({"skipped": True, "reason": reason})


@tool(
    "send_reply",
    (
        "Send an email reply that lands INSIDE the original conversation thread.\n"
        "Only call this if the conversation actually needs a reply — read the whole "
        "thread with get_thread first. If it does not, call skip_reply instead.\n"
        "Inputs: thread_id (the threadId from get_message — NOT a message id), body "
        "(plain text you have written), attachments (optional list of file paths to "
        "attach).\n"
        "Threading, recipients and the 'Re: ' subject are all derived automatically "
        "from the last message in the thread — do NOT try to set them yourself and do "
        "NOT paste the previous email into the body.\n"
        "This actually sends mail to a real person. Send at most ONE reply per task, "
        "as the final step, once the work is done or has definitively failed."
    ),
    {
        "type": "object",
        "properties": {
            "thread_id": {"type": "string", "description": "Gmail threadId to reply in."},
            "body": {"type": "string", "description": "Plain-text body of the reply."},
            "attachments": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional file paths to attach.",
            },
        },
        "required": ["thread_id", "body"],
    },
)
async def send_reply_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        sent = send_reply(
            args["thread_id"], args["body"], args.get("attachments") or None
        )
        return _ok({"sent": True, "id": sent.get("id"), "threadId": sent.get("threadId")})
    except Exception as exc:  # noqa: BLE001
        return _err(f"send_reply failed: {exc}")


GMAIL_TOOLS = [
    get_thread_tool,
    get_message_tool,
    list_attachments_tool,
    save_attachment_tool,
    send_reply_tool,
    skip_reply_tool,
]

#: MCP-qualified names, for `ClaudeAgentOptions(allowed_tools=...)` in the harness.
GMAIL_TOOL_NAMES = [f"mcp__gmail__{t.name}" for t in GMAIL_TOOLS]


def gmail_tools_server():
    """In-process SDK MCP server exposing the four Gmail tools.

    Wire into the harness (bs-tiz.4) as:
        ClaudeAgentOptions(
            mcp_servers={"gmail": gmail_tools_server()},
            allowed_tools=[*GMAIL_TOOL_NAMES, "Read", "Write", "Bash", ...],
        )
    """
    return create_sdk_mcp_server(name="gmail", version="0.1.0", tools=GMAIL_TOOLS)
