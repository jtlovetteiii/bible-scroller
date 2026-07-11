from __future__ import annotations

import dataclasses
import re
from typing import Any

import pytest

from email_agent.config import Config
from email_agent.store import StateStore


# --- Fake Gmail -------------------------------------------------------------


class _Request:
    def __init__(self, result: Any):
        self._result = result

    def execute(self) -> Any:
        return self._result


class FakeMessages:
    """Stands in for service.users().messages().

    Records every call so tests can assert the gate never asked for a body.
    """

    def __init__(self, messages: list[dict[str, Any]]):
        self._messages = {m["id"]: m for m in messages}
        self.list_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> _Request:
        self.list_calls.append(kwargs)
        return _Request({"messages": [{"id": mid} for mid in self._messages]})

    def get(self, **kwargs: Any) -> _Request:
        self.get_calls.append(kwargs)
        msg = self._messages[kwargs["id"]]
        if kwargs.get("format") != "metadata":
            raise AssertionError(
                f"gate must never fetch bodies; got format={kwargs.get('format')!r}"
            )
        # Mimic the API: metadata format returns headers only, no body/parts.
        payload_headers = msg["payload"]["headers"]
        wanted = {h.lower() for h in kwargs.get("metadataHeaders", [])}
        return _Request(
            {
                "id": msg["id"],
                "threadId": msg["threadId"],
                "internalDate": msg.get("internalDate", "0"),
                "payload": {
                    "headers": [
                        h for h in payload_headers if not wanted or h["name"].lower() in wanted
                    ]
                },
            }
        )


class FakeGmail:
    def __init__(self, messages: list[dict[str, Any]]):
        self.messages_resource = FakeMessages(messages)

    def users(self) -> "FakeGmail":
        return self

    def messages(self) -> FakeMessages:
        return self.messages_resource


def make_message(
    msg_id: str,
    thread_id: str,
    subject: str,
    *,
    references: str | None = None,
    internal_date: int = 0,
) -> dict[str, Any]:
    headers = [
        {"name": "Subject", "value": subject},
        {"name": "From", "value": "minister@example.org"},
    ]
    if references:
        headers.append({"name": "References", "value": references})
        headers.append({"name": "In-Reply-To", "value": references})
    return {
        "id": msg_id,
        "threadId": thread_id,
        "internalDate": str(internal_date),
        "payload": {
            "headers": headers,
            # If the gate ever asked for a full body it would find this. It must not.
            "body": {"data": "SEVMTE8="},
        },
    }


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def cfg(tmp_path) -> Config:
    """Config isolated to a temp dir, with a short agent timeout for reaper tests."""
    return dataclasses.replace(
        Config(),
        subject_pattern=re.compile(r"^\s*(re:\s*)*\s*(AI:|Calvary AI)", re.IGNORECASE),
        state_db_path=tmp_path / "state.db",
        agent_timeout_seconds=60,
        lookback_days=7,
    )


@pytest.fixture
def store(cfg: Config) -> StateStore:
    return StateStore(cfg.state_db_path)
