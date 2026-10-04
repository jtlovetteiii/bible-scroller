"""Regression: the agent must never reply to its own reply.

Observed live on 2026-07-11. The agent answered a real `AI:` email correctly, and
the next heartbeat tick handed it *its own reply* as a fresh request — the reply
keeps the thread subject (`Re: AI: …`), so it matches the gate's subject regex
just as well as the original. It replied to itself, and would have done so
forever, burning subscription tokens unattended.

Neither the sender nor the SENT label can distinguish the two: the operator tests
by emailing themselves, so every message in the thread is from the same address
and carries both SENT and INBOX. The only reliable fact is authorship — and we
know it, because we are the ones who sent it.
"""

from __future__ import annotations

from email_agent import tools
from email_agent.store import StateStore


class FakeSend:
    """Minimal Gmail double: records the send and hands back a new message id."""

    def __init__(self, sent_id: str = "agent-reply-1"):
        self.sent_id = sent_id
        self.sent_count = 0

    # -- chained googleapiclient shape --
    def users(self):
        return self

    def messages(self):
        return self

    def threads(self):
        return self

    def get(self, **kwargs):
        self._pending = {
            "messages": [
                {
                    "id": "original-msg",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "AI: First test message"},
                            {"name": "From", "value": "thomas@example.com"},
                            {"name": "Message-ID", "value": "<orig@mail>"},
                        ]
                    },
                }
            ]
        }
        return self

    def send(self, **kwargs):
        self.sent_count += 1
        self._pending = {"id": self.sent_id, "threadId": kwargs["body"]["threadId"]}
        return self

    def execute(self):
        return self._pending


def test_agent_sent_reply_is_never_treated_as_a_new_request(tmp_path):
    store = StateStore(tmp_path / "state.db")
    svc = FakeSend(sent_id="agent-reply-1")

    sent = tools.send_reply("thread-1", "Here is your deck.", service=svc, store=store)
    assert sent["id"] == "agent-reply-1"
    assert svc.sent_count == 1

    # The dispatcher gates on is_processed(). Our own reply must be rejected by it,
    # or the next tick feeds it straight back in and the loop begins.
    assert store.is_processed("agent-reply-1"), (
        "the agent's own reply was NOT recorded as authored-by-us — the gate will "
        "hand it back as a new request and the agent will reply to itself forever"
    )

    # The real inbound message must remain eligible.
    assert not store.is_processed("original-msg")


def test_guard_survives_a_second_send_on_the_same_thread(tmp_path):
    store = StateStore(tmp_path / "state.db")

    for i in (1, 2):
        svc = FakeSend(sent_id=f"agent-reply-{i}")
        tools.send_reply("thread-1", f"reply {i}", service=svc, store=store)

    assert store.is_processed("agent-reply-1")
    assert store.is_processed("agent-reply-2")
