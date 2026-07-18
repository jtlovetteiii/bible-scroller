"""The agent must be *allowed* to decide a reply isn't warranted.

The first version of the harness demanded a reply ("never finish silently") and
gave the agent only a single message ID. So it had neither the picture nor the
authority to decline — which is precisely why it replied to its own reply. The
deterministic authorship guard was then the only thing preventing a loop, which
is too much weight for bookkeeping to carry.

A run must now end in exactly one of two deliberate outcomes — reply, or decline
to reply. Both are success. What is still a failure is deciding *nothing*: the
dispatcher treats a return as the commit point, so a silent finish drops the
request forever.
"""

from __future__ import annotations

import collections
import logging

import pytest

from email_agent import harness


class FakeBlock:
    def __init__(self, name: str):
        self.name = name


class FakeAssistant:
    def __init__(self, *tool_names: str):
        self.content = [FakeBlock(n) for n in tool_names]


class FakeSystem:
    def __init__(self, session_id: str):
        self.data = {"session_id": session_id}


class FakeResult:
    is_error = False
    session_id = "s-1"
    result = "done"


def _fake_query(*messages):
    async def _q(*, prompt, options):  # noqa: ARG001
        for m in messages:
            yield m

    return _q


def _patch(monkeypatch, *messages):
    monkeypatch.setattr(harness, "query", _fake_query(*messages))
    monkeypatch.setattr(harness, "assert_subscription_auth", lambda: None)
    monkeypatch.setattr(harness, "gmail_tools_server", lambda: {"type": "sdk", "name": "gmail"})
    # isinstance() checks in the harness must recognise our doubles
    monkeypatch.setattr(harness, "SystemMessage", FakeSystem)
    monkeypatch.setattr(harness, "AssistantMessage", FakeAssistant)
    monkeypatch.setattr(harness, "ResultMessage", FakeResult)
    monkeypatch.setattr(harness, "ToolUseBlock", FakeBlock)


def test_reply_is_a_valid_ending(monkeypatch):
    _patch(
        monkeypatch,
        FakeSystem("s-1"),
        FakeAssistant(harness.SEND_REPLY_TOOL),
        FakeResult(),
    )
    assert harness.run_agent("t-1", "m-1", None) == "s-1"


def test_declining_to_reply_is_a_valid_ending(monkeypatch):
    """The whole point: skip_reply must NOT be treated as a failed run."""
    _patch(
        monkeypatch,
        FakeSystem("s-1"),
        FakeAssistant(harness.SKIP_REPLY_TOOL),
        FakeResult(),
    )
    assert harness.run_agent("t-1", "m-1", None) == "s-1"


def test_deciding_nothing_is_still_a_failure(monkeypatch):
    """A run that neither replies nor declines has silently dropped the request."""
    _patch(
        monkeypatch,
        FakeSystem("s-1"),
        FakeAssistant("mcp__gmail__get_thread"),  # read it, then just... stopped
        FakeResult(),
    )
    with pytest.raises(harness.AgentError, match="silently dropped"):
        harness.run_agent("t-1", "m-1", None)


# ---------------------------------------------------------------------------
# bs-zwj: the bundled CLI's stderr must reach our logs, not vanish. The failure
# that prompted this ("error result: success") was opaque only because we never
# asked the SDK to pipe stderr.
# ---------------------------------------------------------------------------


def test_stderr_capture_records_lines_and_skips_blanks(caplog):
    sink: collections.deque[str] = collections.deque(maxlen=10)
    capture = harness._stderr_capture("t-9", "m-9", sink)
    with caplog.at_level(logging.DEBUG, logger="email_agent.harness"):
        capture("node: real error\n")
        capture("\n")   # a bare newline is not signal — dropped
        capture("")     # nor an empty chunk
        capture("  stack frame")

    assert list(sink) == ["node: real error", "  stack frame"]  # leading indent kept
    assert any("node: real error" in r.message for r in caplog.records)


def _query_that_stderrs_then_fails(*lines, exc):
    """A fake query that delivers CLI stderr the way the real transport does —
    via options.stderr — and then dies, so the tail-on-failure path is exercised."""

    async def _q(*, prompt, options):  # noqa: ARG001
        for line in lines:
            options.stderr(line)
        raise exc
        yield  # unreachable; makes this an async generator

    return _q


def test_cli_stderr_tail_is_logged_when_a_run_fails(monkeypatch, caplog):
    _patch(monkeypatch)  # benign query + auth/isinstance doubles
    boom = Exception("Claude Code returned an error result: success")
    monkeypatch.setattr(
        harness,
        "query",
        _query_that_stderrs_then_fails(
            "node:internal/errors real cause here", "  at frame 1", exc=boom
        ),
    )

    with caplog.at_level(logging.ERROR, logger="email_agent.harness"):
        with pytest.raises(Exception, match="error result: success"):
            harness.run_agent("t-1", "m-1", None)

    errors = "\n".join(r.message for r in caplog.records if r.levelno >= logging.ERROR)
    assert "node:internal/errors real cause here" in errors
    assert "at frame 1" in errors


def test_no_stderr_tail_logged_on_a_clean_run(monkeypatch, caplog):
    """A healthy run must not emit the ERROR tail — no crying wolf."""
    _patch(
        monkeypatch,
        FakeSystem("s-1"),
        FakeAssistant(harness.SEND_REPLY_TOOL),
        FakeResult(),
    )
    with caplog.at_level(logging.ERROR, logger="email_agent.harness"):
        assert harness.run_agent("t-1", "m-1", None) == "s-1"
    assert not [r for r in caplog.records if "stderr tail" in r.message]
