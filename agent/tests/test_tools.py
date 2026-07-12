"""Unit tests for the deterministic Gmail tools (bs-tiz.3).

Everything runs against a fake Gmail service shaped like the real
googleapiclient one (`users().messages().get(...).execute()`), so no network,
no credentials, and no live mail is ever touched.
"""

from __future__ import annotations

import base64
import email
from pathlib import Path

import pytest

from email_agent.tools import (
    build_reply_message,
    extract_body,
    get_attachment_binary,
    get_message,
    list_attachments,
    reply_subject,
    send_reply,
)

# ---------------------------------------------------------------------------
# fake Gmail API
# ---------------------------------------------------------------------------


def b64url(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def hdrs(**kw: str) -> list[dict[str, str]]:
    return [{"name": k.replace("_", "-"), "value": v} for k, v in kw.items()]


class _Req:
    def __init__(self, result, recorder=None, kwargs=None):
        self._result = result
        self._recorder = recorder
        self._kwargs = kwargs

    def execute(self):
        if self._recorder is not None:
            self._recorder.append(self._kwargs)
        return self._result


class FakeAttachments:
    def __init__(self, blobs: dict[str, bytes]):
        self._blobs = blobs

    def get(self, *, userId, messageId, id):  # noqa: N803 - mirrors the real API
        return _Req({"size": len(self._blobs[id]), "data": b64url(self._blobs[id])})


class FakeMessages:
    def __init__(self, messages, blobs, sent):
        self._messages = messages
        self._blobs = blobs
        self._sent = sent

    def get(self, *, userId, id, format=None, metadataHeaders=None):  # noqa: N803, A002
        return _Req(self._messages[id])

    def attachments(self):
        return FakeAttachments(self._blobs)

    def send(self, *, userId, body):  # noqa: N803
        return _Req(
            {"id": "sent-1", "threadId": body.get("threadId")},
            recorder=self._sent,
            kwargs=body,
        )


class FakeThreads:
    def __init__(self, threads):
        self._threads = threads

    def get(self, *, userId, id, format=None, metadataHeaders=None):  # noqa: N803, A002
        return _Req(self._threads[id])


class FakeUsers:
    def __init__(self, svc):
        self._svc = svc

    def messages(self):
        return FakeMessages(self._svc.messages, self._svc.blobs, self._svc.sent)

    def threads(self):
        return FakeThreads(self._svc.threads)


class FakeService:
    def __init__(self, messages=None, threads=None, blobs=None):
        self.messages = messages or {}
        self.threads = threads or {}
        self.blobs = blobs or {}
        self.sent: list[dict] = []

    def users(self):
        return FakeUsers(self)


# ---------------------------------------------------------------------------
# fixtures: real-shaped Gmail payloads
# ---------------------------------------------------------------------------

PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nfake order of service\n%%EOF"


@pytest.fixture
def plain_message() -> dict:
    """text/plain only, no parts."""
    return {
        "id": "msg-plain",
        "threadId": "thread-plain",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Here is Sunday",
        "payload": {
            "partId": "",
            "mimeType": "text/plain",
            "filename": "",
            "headers": hdrs(
                Subject="AI: order of service",
                From="Minister of Music <music@example.org>",
                To="agent@example.org",
                Date="Sat, 11 Jul 2026 09:00:00 -0500",
                Message_ID="<abc123@mail.example.org>",
                Content_Type='text/plain; charset="UTF-8"',
            ),
            "body": {"size": 22, "data": b64url("Here is Sunday's plan.")},
        },
    }


@pytest.fixture
def multipart_message() -> dict:
    """multipart/mixed -> [multipart/alternative(plain, html), pdf attachment]."""
    return {
        "id": "msg-mixed",
        "threadId": "thread-mixed",
        "labelIds": ["INBOX"],
        "snippet": "Order of service attached",
        "payload": {
            "partId": "",
            "mimeType": "multipart/mixed",
            "filename": "",
            "headers": hdrs(
                Subject="AI: Sunday 2026-07-12",
                From="Minister of Music <music@example.org>",
                To="agent@example.org",
                Cc="pastor@example.org",
                Date="Sat, 11 Jul 2026 09:00:00 -0500",
                Message_ID="<mixed-1@mail.example.org>",
                References="<root@mail.example.org>",
                In_Reply_To="<root@mail.example.org>",
            ),
            "parts": [
                {
                    "partId": "0",
                    "mimeType": "multipart/alternative",
                    "filename": "",
                    "headers": hdrs(Content_Type="multipart/alternative"),
                    "body": {"size": 0},
                    "parts": [
                        {
                            "partId": "0.0",
                            "mimeType": "text/plain",
                            "filename": "",
                            "headers": hdrs(
                                Content_Type='text/plain; charset="UTF-8"',
                                Content_Transfer_Encoding="quoted-printable",
                            ),
                            "body": {
                                "size": 40,
                                "data": b64url("Order of service attached. Caf=C3=A9 hymn."),
                            },
                        },
                        {
                            "partId": "0.1",
                            "mimeType": "text/html",
                            "filename": "",
                            "headers": hdrs(Content_Type='text/html; charset="UTF-8"'),
                            "body": {
                                "size": 60,
                                "data": b64url("<div>Order of service <b>attached</b>.</div>"),
                            },
                        },
                    ],
                },
                {
                    "partId": "1",
                    "mimeType": "application/pdf",
                    "filename": "Order-of-Service.PDF",
                    "headers": hdrs(
                        Content_Type="application/pdf",
                        Content_Disposition='attachment; filename="Order-of-Service.PDF"',
                    ),
                    "body": {"attachmentId": "att-pdf-1", "size": len(PDF_BYTES)},
                },
            ],
        },
    }


@pytest.fixture
def html_only_message() -> dict:
    """Nested multipart/related with only HTML text + an inline image."""
    return {
        "id": "msg-html",
        "threadId": "thread-html",
        "payload": {
            "mimeType": "multipart/mixed",
            "filename": "",
            "headers": hdrs(Subject="AI: html only", Message_ID="<h1@mail.example.org>"),
            "parts": [
                {
                    "mimeType": "multipart/related",
                    "filename": "",
                    "headers": hdrs(Content_Type="multipart/related"),
                    "body": {"size": 0},
                    "parts": [
                        {
                            "partId": "0.0",
                            "mimeType": "text/html",
                            "filename": "",
                            "headers": hdrs(Content_Type="text/html; charset=UTF-8"),
                            "body": {
                                "size": 90,
                                "data": b64url(
                                    "<style>p{color:red}</style>"
                                    "<p>Hymn&nbsp;123</p><br><p>Sermon &amp; prayer</p>"
                                ),
                            },
                        },
                        {
                            "partId": "0.1",
                            "mimeType": "image/png",
                            "filename": "logo.png",
                            "headers": hdrs(Content_Disposition='inline; filename="logo.png"'),
                            "body": {"attachmentId": "att-png-1", "size": 12},
                        },
                    ],
                },
            ],
        },
    }


@pytest.fixture
def service(multipart_message, plain_message, html_only_message) -> FakeService:
    return FakeService(
        messages={
            "msg-plain": plain_message,
            "msg-mixed": multipart_message,
            "msg-html": html_only_message,
        },
        threads={
            "thread-mixed": {"id": "thread-mixed", "messages": [multipart_message]},
        },
        blobs={"att-pdf-1": PDF_BYTES, "att-png-1": b"\x89PNG\r\n\x1a\n"},
    )


# ---------------------------------------------------------------------------
# get_message
# ---------------------------------------------------------------------------


def test_get_message_plain(service):
    msg = get_message("msg-plain", service=service)
    assert msg["threadId"] == "thread-plain"
    assert msg["body"] == "Here is Sunday's plan."
    assert msg["bodyMimeType"] == "text/plain"
    assert msg["headers"]["Subject"] == "AI: order of service"
    assert msg["headers"]["Message-ID"] == "<abc123@mail.example.org>"
    assert msg["attachmentCount"] == 0


def test_get_message_prefers_plain_over_html_and_decodes_qp(service):
    msg = get_message("msg-mixed", service=service)
    # text/plain wins over the text/html sibling in multipart/alternative...
    assert msg["bodyMimeType"] == "text/plain"
    # ...and the quoted-printable escape is decoded.
    assert msg["body"] == "Order of service attached. Café hymn."
    assert msg["attachmentCount"] == 1
    assert msg["headers"]["References"] == "<root@mail.example.org>"
    assert msg["headers"]["Cc"] == "pastor@example.org"


def test_get_message_falls_back_to_stripped_html(service):
    msg = get_message("msg-html", service=service)
    assert msg["bodyMimeType"] == "text/html"
    assert "<p>" not in msg["body"]
    assert "color:red" not in msg["body"]  # <style> block dropped
    assert "Hymn 123" in msg["body"]  # &nbsp; unescaped
    assert "Sermon & prayer" in msg["body"]  # &amp; unescaped
    # the inline image is an attachment, not body text
    assert msg["attachmentCount"] == 1


def test_extract_body_on_bodiless_payload():
    assert extract_body({"mimeType": "multipart/mixed", "parts": []}) == ("", "")


# ---------------------------------------------------------------------------
# list_attachments
# ---------------------------------------------------------------------------


def test_list_attachments_metadata(service):
    atts = list_attachments("msg-mixed", service=service)
    assert len(atts) == 1
    att = atts[0]
    assert att == {
        "filename": "Order-of-Service.PDF",
        "extension": "pdf",  # lowercased, no leading dot
        "mimeType": "application/pdf",
        "size": len(PDF_BYTES),
        "attachmentId": "att-pdf-1",
        "partId": "1",
    }


def test_list_attachments_finds_nested_parts(service):
    atts = list_attachments("msg-html", service=service)
    assert [a["filename"] for a in atts] == ["logo.png"]
    assert atts[0]["attachmentId"] == "att-png-1"


def test_list_attachments_empty_for_plain_message(service):
    assert list_attachments("msg-plain", service=service) == []


# ---------------------------------------------------------------------------
# get_attachment_binary / save_attachment
# ---------------------------------------------------------------------------


def test_get_attachment_binary_round_trips(service):
    assert get_attachment_binary("msg-mixed", "att-pdf-1", service=service) == PDF_BYTES


def test_get_attachment_binary_requires_id(service):
    with pytest.raises(ValueError):
        get_attachment_binary("msg-mixed", "", service=service)


def test_save_attachment_writes_bytes_and_returns_path(service, tmp_path):
    from email_agent.tools import save_attachment

    dest = tmp_path / "nested" / "oos.pdf"
    path = save_attachment("msg-mixed", "att-pdf-1", dest, service=service)
    assert path == dest
    assert dest.read_bytes() == PDF_BYTES  # no conversion, byte-identical


# ---------------------------------------------------------------------------
# send_reply — RFC 2822 threading
# ---------------------------------------------------------------------------


def test_reply_subject_prefixes_once():
    assert reply_subject("AI: Sunday") == "Re: AI: Sunday"
    assert reply_subject("Re: AI: Sunday") == "Re: AI: Sunday"
    assert reply_subject("RE: AI: Sunday") == "RE: AI: Sunday"


def test_build_reply_message_threading_headers():
    parent = {
        "Subject": "AI: Sunday 2026-07-12",
        "From": "Minister of Music <music@example.org>",
        "Message-ID": "<mixed-1@mail.example.org>",
        "References": "<root@mail.example.org>",
    }
    msg = build_reply_message(parent, "Deck is ready: http://x/y")
    assert msg["Subject"] == "Re: AI: Sunday 2026-07-12"
    assert msg["To"] == "Minister of Music <music@example.org>"
    assert msg["In-Reply-To"] == "<mixed-1@mail.example.org>"
    # References chain grows: parent's chain + parent's own Message-ID
    assert msg["References"] == "<root@mail.example.org> <mixed-1@mail.example.org>"
    assert msg.get_content().strip() == "Deck is ready: http://x/y"


def test_build_reply_message_honours_reply_to():
    parent = {
        "From": "noreply@example.org",
        "Reply-To": "music@example.org",
        "Subject": "AI: x",
        "Message-ID": "<m@x>",
    }
    assert build_reply_message(parent, "hi")["To"] == "music@example.org"
    # first reply in a thread: References is just the parent Message-ID
    assert build_reply_message(parent, "hi")["References"] == "<m@x>"


def test_build_reply_message_with_attachment(tmp_path: Path):
    f = tmp_path / "deck.pdf"
    f.write_bytes(PDF_BYTES)
    msg = build_reply_message({"Subject": "AI: x", "Message-ID": "<m@x>", "From": "a@b"}, "body", [f])
    parts = list(msg.iter_attachments())
    assert len(parts) == 1
    assert parts[0].get_filename() == "deck.pdf"
    assert parts[0].get_content_type() == "application/pdf"
    assert parts[0].get_payload(decode=True) == PDF_BYTES


def test_send_reply_posts_threadid_and_correct_mime(service):
    result = send_reply("thread-mixed", "Your deck is ready.", service=service)

    assert result == {"id": "sent-1", "threadId": "thread-mixed"}
    assert len(service.sent) == 1
    body = service.sent[0]

    # Gmail-side threading: threadId must be on the insert itself.
    assert body["threadId"] == "thread-mixed"

    # RFC 2822-side threading: decode the raw MIME we actually posted.
    raw = base64.urlsafe_b64decode(body["raw"] + "=" * (-len(body["raw"]) % 4))
    sent = email.message_from_bytes(raw)
    assert sent["Subject"] == "Re: AI: Sunday 2026-07-12"
    assert sent["To"] == "Minister of Music <music@example.org>"
    assert sent["In-Reply-To"] == "<mixed-1@mail.example.org>"
    assert sent["References"] == "<root@mail.example.org> <mixed-1@mail.example.org>"
    assert "Your deck is ready." in sent.get_payload(decode=True).decode()


def test_send_reply_rejects_empty_thread():
    svc = FakeService(threads={"empty": {"id": "empty", "messages": []}})
    with pytest.raises(ValueError):
        send_reply("empty", "hi", service=svc)


# ---------------------------------------------------------------------------
# SDK tool layer
# ---------------------------------------------------------------------------


def test_sdk_tools_registered():
    from email_agent.tools import GMAIL_TOOL_NAMES, GMAIL_TOOLS, gmail_tools_server

    assert [t.name for t in GMAIL_TOOLS] == [
        "get_thread",
        "get_message",
        "list_attachments",
        "save_attachment",
        "send_reply",
        # Declining to reply is a first-class outcome, not the absence of one.
        "skip_reply",
    ]
    assert GMAIL_TOOL_NAMES == [
        "mcp__gmail__get_thread",
        "mcp__gmail__get_message",
        "mcp__gmail__list_attachments",
        "mcp__gmail__save_attachment",
        "mcp__gmail__send_reply",
        "mcp__gmail__skip_reply",
    ]
    server = gmail_tools_server()
    assert server["type"] == "sdk"
    assert server["name"] == "gmail"


@pytest.mark.asyncio
async def test_get_message_tool_returns_error_content_on_failure(monkeypatch):
    import email_agent.tools as t

    monkeypatch.setattr(t, "get_message", lambda *_a, **_k: 1 / 0)
    result = await t.get_message_tool.handler({"msg_id": "x"})
    assert result["is_error"] is True
    assert "get_message failed" in result["content"][0]["text"]
