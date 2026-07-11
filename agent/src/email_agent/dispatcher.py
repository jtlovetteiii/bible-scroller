"""Dispatcher — bs-tiz.2 (spec §4.2, §7).

Consumes the gate's ``[{threadId, msgId, isReply}]`` and, for each message:

1. skips it if the ledger says it was already handled;
2. skips the thread if another (overlapping) heartbeat holds the claim;
3. resolves ``threadId -> session_id`` — a new session for an initial email, a
   resume for a reply;
4. runs the agent, and only **after** it returns (i.e. after the reply is sent)
   marks the message processed.

Still deterministic — no LLM lives here. The LLM is behind ``RunAgent``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .config import Config, config as default_config
from .gate import GatedMessage
from .store import StateStore

log = logging.getLogger(__name__)


@runtime_checkable
class RunAgent(Protocol):
    """The seam to the agent harness (bs-tiz.4), which does not exist yet.

    Deliberately the narrowest possible interface: IDs in, session ID out. The
    dispatcher knows nothing about the Claude Agent SDK, Gmail bodies, or slide
    decks — it only knows that *something* handles a message and, in doing so,
    ends up owning a session.

    Contract:
      - ``session_id`` is ``None`` for a thread we have never run, and the
        thread's existing session for a reply (harness passes it to
        ``ClaudeAgentOptions(resume=...)``).
      - Returns the session_id to persist for the thread (a fresh one from the
        init ``SystemMessage``, or the same one back on a resume).
      - **Must not return until the reply has actually been sent** — the
        dispatcher treats return as the commit point.
      - Raises on any failure, including timeout. The dispatcher converts that
        into ``failed`` + released claim, and the message is retried next pass.
    """

    def __call__(
        self, thread_id: str, msg_id: str, session_id: str | None
    ) -> str | None: ...


@dataclass
class DispatchResult:
    processed: list[str] = field(default_factory=list)
    skipped_already_processed: list[str] = field(default_factory=list)
    skipped_in_flight: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    reaped: list[str] = field(default_factory=list)


class Dispatcher:
    def __init__(
        self,
        store: StateStore,
        run_agent: RunAgent,
        cfg: Config | None = None,
    ):
        self.store = store
        self.run_agent = run_agent
        self.cfg = cfg or default_config

    @property
    def _stale_after(self) -> float:
        return float(self.cfg.agent_timeout_seconds)

    def dispatch(self, messages: list[GatedMessage]) -> DispatchResult:
        """One pass. Safe to run concurrently with another pass."""
        result = DispatchResult()

        # A crashed process leaves its claim behind with nobody to release it.
        # Reap before claiming so an abandoned thread is retryable this pass.
        result.reaped = self.store.reap_stale(stale_after_seconds=self._stale_after)
        if result.reaped:
            log.warning("reaped %d stale claim(s): %s", len(result.reaped), result.reaped)

        for msg in messages:
            self._dispatch_one(msg, result)
        return result

    def _dispatch_one(self, msg: GatedMessage, result: DispatchResult) -> None:
        if self.store.is_processed(msg.msg_id):
            result.skipped_already_processed.append(msg.msg_id)
            return

        if not self.store.claim(msg.thread_id, stale_after_seconds=self._stale_after):
            # Another heartbeat is mid-run on this thread. Spec §7: a reply that
            # lands mid-run is skipped *this tick* and picked up on the next one
            # — it stays out of the ledger, so it is never dropped.
            log.info("thread %s in flight; deferring msg %s", msg.thread_id, msg.msg_id)
            result.skipped_in_flight.append(msg.msg_id)
            return

        # Re-check under the claim: between our is_processed() read above and
        # winning the claim, a concurrent pass could have finished this very
        # message and released. Cheap; closes the window.
        if self.store.is_processed(msg.msg_id):
            self.store.release(msg.thread_id)
            result.skipped_already_processed.append(msg.msg_id)
            return

        state = self.store.get(msg.thread_id)
        session_id = state.session_id if state else None
        if not msg.is_reply and session_id is None:
            log.info("thread %s: new session for initial message %s", msg.thread_id, msg.msg_id)
        elif session_id:
            log.info("thread %s: resuming session %s", msg.thread_id, session_id)

        try:
            new_session_id = self.run_agent(
                thread_id=msg.thread_id,
                msg_id=msg.msg_id,
                session_id=session_id,
            )
        except BaseException as exc:  # noqa: BLE001 - the claim MUST be released
            # Spec §7: an agent error/timeout transitions the thread OUT of
            # in-flight so the claim is released. The message is NOT marked
            # processed, so the next pass retries it.
            log.exception("agent failed on thread %s msg %s: %s", msg.thread_id, msg.msg_id, exc)
            self.store.mark_failed(msg.thread_id)
            result.failed.append(msg.msg_id)
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            return

        # Commit boundary (spec §7): the harness has sent the reply, so and only
        # so do we record the message. A crash in this gap re-runs the message
        # and sends a duplicate reply — a named, accepted POC trade-off.
        self.store.mark_processed(
            msg.thread_id, msg.msg_id, new_session_id or session_id
        )
        result.processed.append(msg.msg_id)


__all__ = ["Dispatcher", "DispatchResult", "RunAgent"]
