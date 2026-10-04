"""Email gate — bs-tiz.1 (spec §4.1).

Deterministic, no LLM, **metadata only**.

The gate is the agent's only entry point. It never "wakes up and reads the
inbox" — it polls on a timer, applies a configurable subject regex, and emits
nothing but IDs. Every interpretive act (reading the body, the attachments,
working out what is being asked) belongs to the agent.

Two hard rules, both acceptance criteria rather than optimizations:

1. **No bodies are ever fetched.** Messages are read with
   ``format="metadata"`` and an explicit ``metadataHeaders`` allow-list, so the
   Gmail API returns headers only — the payload never crosses the wire.
2. **The query is bounded by ``config.lookback_days``** so a restart (or an
   empty state DB) can never replay the whole archive.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .config import Config, config as default_config

log = logging.getLogger(__name__)

#: The only headers we ask Gmail for. Subject drives the regex gate;
#: References/In-Reply-To drive initial-vs-reply classification.
METADATA_HEADERS = ["Subject", "References", "In-Reply-To", "Message-ID"]


@dataclass(frozen=True)
class GatedMessage:
    """The gate's entire output surface: IDs plus one boolean."""

    thread_id: str
    msg_id: str
    is_reply: bool


def _headers(message: dict[str, Any]) -> dict[str, str]:
    """Lower-cased header map from a metadata-format message resource."""
    return {
        h.get("name", "").lower(): h.get("value", "")
        for h in message.get("payload", {}).get("headers", [])
    }


def _is_reply(headers: dict[str, str]) -> bool:
    """Classify initial message vs reply.

    Uses the ``References`` / ``In-Reply-To`` headers rather than a ``Re:``
    subject prefix: the prefix is user-editable (and localized), the threading
    headers are set by the sending client and are what Gmail itself threads on.
    """
    return bool(headers.get("references", "").strip() or headers.get("in-reply-to", "").strip())


def build_query(cfg: Config) -> str:
    """Gmail search query. Bounded so we can't replay the archive."""
    return f"in:inbox newer_than:{cfg.lookback_days}d"


def poll(service: Any | None = None, cfg: Config | None = None) -> list[GatedMessage]:
    """Poll Gmail and return the messages the agent should act on.

    Non-matching mail is ignored entirely — it is never even counted.
    Results are ordered oldest-first so a thread's messages are dispatched in
    the order they arrived.
    """
    cfg = cfg or default_config
    if service is None:  # pragma: no cover - requires live credentials
        from .gmail_client import gmail_service

        service = gmail_service()

    messages = service.users().messages()

    ids: list[str] = []
    page_token: str | None = None
    while True:
        resp = messages.list(
            userId="me",
            q=build_query(cfg),
            pageToken=page_token,
        ).execute()
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    gated: list[tuple[int, GatedMessage]] = []
    for msg_id in ids:
        # format="metadata" => Gmail returns headers only. No body, ever.
        msg = messages.get(
            userId="me",
            id=msg_id,
            format="metadata",
            metadataHeaders=METADATA_HEADERS,
        ).execute()

        headers = _headers(msg)
        subject = headers.get("subject", "")
        if not cfg.subject_pattern.search(subject):
            continue

        gated.append(
            (
                int(msg.get("internalDate", 0)),
                GatedMessage(
                    thread_id=msg["threadId"],
                    msg_id=msg["id"],
                    is_reply=_is_reply(headers),
                ),
            )
        )

    gated.sort(key=lambda pair: pair[0])
    result = [g for _, g in gated]
    log.info("gate: %d message(s) scanned, %d actionable", len(ids), len(result))
    return result
