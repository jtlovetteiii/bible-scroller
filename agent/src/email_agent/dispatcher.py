"""Dispatcher — bs-tiz.2 (spec §4.2, §7).

Consumes the gate's ``[{threadId, msgId, isReply}]`` and, for each message:

1. skips it if the ledger says it was already handled;
2. skips the thread if another (overlapping) heartbeat holds the claim;
3. gives up on it — once, terminally — if it has already burned its attempts;
4. resolves ``threadId -> session_id`` — a new session for an initial email, a
   resume for a reply;
5. runs the agent, and only **after** it returns (i.e. after the reply is sent)
   marks the message processed.

Still deterministic — no LLM lives here. The LLM is behind ``RunAgent``, and the
give-up apology is a fixed string, not a model call: the one path that runs when
the agent is broken must not itself depend on the agent.
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
        into ``failed`` + released claim, and the message is retried next pass —
        up to ``cfg.max_attempts_per_message`` times.
    """

    def __call__(
        self, thread_id: str, msg_id: str, session_id: str | None
    ) -> str | None: ...


@runtime_checkable
class SendReply(Protocol):
    """The seam to Gmail for the give-up apology. Satisfied by ``tools.send_reply``.

    The dispatcher does not otherwise touch Gmail, and this is the only reason it
    now does: the failure path has to be able to speak to the minister without
    going through the agent that is, by hypothesis, failing.
    """

    def __call__(self, thread_id: str, body: str, *, store: object) -> object: ...


#: The give-up reply. Fixed text, not a model call — see the module docstring.
#: Deliberately says nothing about *what* broke: the dispatcher genuinely does not
#: know (it holds an exception from an opaque seam), and a guess would be worse
#: than an honest "I could not do this, a human should look".
#:
#: It must also not overclaim. An earlier draft reassured the minister that "no
#: slides were published", which the dispatcher cannot know and which is
#: sometimes FALSE: the agent publishes the deck to S3 *before* it replies (see
#: harness.SYSTEM_PROMPT step 6), so a run that dies between those two steps
#: leaves a real deck at a real URL. What IS true in every case is the thing that
#: actually matters to him — no link ever reached him, so nothing of ours is in
#: front of the congregation.
APOLOGY_BODY = (
    "I ran into an error trying to handle this request and could not complete it.\n"
    "\n"
    "I tried several times, so this is unlikely to fix itself — I have stopped "
    "retrying rather than keep failing quietly.\n"
    "\n"
    "I never sent you a link, so please assume nothing is ready to use. If you "
    "still need this, please forward this thread to Thomas, or start a new email "
    "so I can try again from scratch.\n"
    "\n"
    "— Calvary AI\n"
)


@dataclass
class DispatchResult:
    processed: list[str] = field(default_factory=list)
    skipped_already_processed: list[str] = field(default_factory=list)
    skipped_in_flight: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    reaped: list[str] = field(default_factory=list)
    #: Messages that exhausted their attempts and were retired (bs-9ed). They are
    #: in the ledger, so they will never be dispatched again.
    gave_up: list[str] = field(default_factory=list)


class Dispatcher:
    def __init__(
        self,
        store: StateStore,
        run_agent: RunAgent,
        cfg: Config | None = None,
        send_reply: SendReply | None = None,
    ):
        self.store = store
        self.run_agent = run_agent
        self.cfg = cfg or default_config
        self._send_reply = send_reply

    def _apologise(self, thread_id: str) -> None:
        """Send the give-up reply, resolving the Gmail seam lazily.

        Late import, matching ``heartbeat._load_run_agent``: importing ``tools``
        pulls in the Claude Agent SDK and a Gmail client, and the dispatcher's
        tests must keep being able to run with neither.
        """
        send = self._send_reply
        if send is None:
            from .tools import send_reply as send  # noqa: PLC0415

        # store=self.store is load-bearing, not tidiness: send_reply records the
        # sent id via mark_agent_sent, which is what stops the gate handing our
        # own apology back to us next tick as a fresh `Re: AI: …` request. An
        # apology that re-triggered the agent would be a perfect reply loop —
        # exactly the failure of 2026-07-11 (see store.mark_agent_sent, bs-c8y).
        send(thread_id=thread_id, body=APOLOGY_BODY, store=self.store)

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

        # bs-9ed: the retry bound. Reachable here only if a previous pass was
        # killed between recording its attempt and giving up (the normal crossing
        # is handled eagerly in the except: block below, while still holding this
        # claim). Checked anyway — the whole point is that nothing is watching.
        if self.store.attempt_count(msg.msg_id) >= self.cfg.max_attempts_per_message:
            self._give_up(msg, session_id, result)
            return

        if not msg.is_reply and session_id is None:
            log.info("thread %s: new session for initial message %s", msg.thread_id, msg.msg_id)
        elif session_id:
            log.info("thread %s: resuming session %s", msg.thread_id, session_id)

        # Count the attempt BEFORE the run, not on the way out of a failure. The
        # failure that most needs bounding is the one that never comes back at
        # all — a run that wedges past the timeout and is reaped, or a poison
        # message that takes the process down with it. Neither reaches the
        # except: block, so a counter incremented there would sit at zero
        # forever and bound nothing, which is the bug in its own image.
        # Consequence, accepted: an operator Ctrl-C mid-run also spends an
        # attempt. The alternative — refunding on the way out — is a path a
        # poison message could ride to keep the counter at zero.
        attempts = self.store.record_attempt(msg.thread_id, msg.msg_id)

        try:
            new_session_id = self.run_agent(
                thread_id=msg.thread_id,
                msg_id=msg.msg_id,
                session_id=session_id,
            )
        except BaseException as exc:  # noqa: BLE001 - the claim MUST be released
            # Spec §7: an agent error/timeout transitions the thread OUT of
            # in-flight so the claim is released. The message is NOT marked
            # processed, so the next pass retries it — until it runs out of
            # attempts, at which point it is retired here rather than retried.
            log.exception("agent failed on thread %s msg %s: %s", msg.thread_id, msg.msg_id, exc)
            result.failed.append(msg.msg_id)
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                self.store.mark_failed(msg.thread_id)
                raise
            if attempts >= self.cfg.max_attempts_per_message:
                # Give up while STILL HOLDING THE CLAIM. mark_failed would release
                # it, and an overlapping heartbeat could then claim the thread,
                # find the same exhausted counter and apologise a second time.
                # The claim that guarantees one agent run per thread is reused to
                # guarantee one apology.
                self._give_up(msg, session_id, result)
            else:
                self.store.mark_failed(msg.thread_id)
            return

        # Commit boundary (spec §7): the harness has sent the reply, so and only
        # so do we record the message. A crash in this gap re-runs the message
        # and sends a duplicate reply — a named, accepted POC trade-off.
        self.store.mark_processed(
            msg.thread_id, msg.msg_id, new_session_id or session_id
        )
        result.processed.append(msg.msg_id)

    def _give_up(
        self, msg: GatedMessage, session_id: str | None, result: DispatchResult
    ) -> None:
        """Retire a message that has exhausted its attempts. TERMINAL. Holds the claim.

        Note this inverts the SUCCESS path's commit boundary, on purpose. There,
        marking processed *only after* the reply is sent is what stops a message
        being silently swallowed; the cost is a rare duplicate reply, which is
        the trade named in spec §7. Here the ordering has to go the other way,
        because the failure being handled is precisely "this message cannot be
        handled":

        - if the apology sends, the message is finished and must leave the pool;
        - if the apology does NOT send, the message is *still* finished, because
          the only thing left to retry is the run that has already failed
          `max_attempts_per_message` times.

        So mark_processed happens in a `finally`. If it were conditional on the
        send, a Gmail outage — or a permanently unreplyable thread — would put
        the message straight back in the retry pool with its counter already
        past the bound, and every subsequent pass would re-enter this method and
        fail to send again: the identical unbounded loop, rebuilt one level up,
        and now hitting the Gmail API instead of the model. Losing an apology is
        bad and is logged at ERROR. Retrying forever is the deployment blocker.

        `except Exception`, not BaseException: a Ctrl-C mid-apology must still
        propagate, and the `finally` retires the message on its way out anyway.
        """
        log.error(
            "GIVING UP on thread %s msg %s after %d attempts (max_attempts_per_message=%d). "
            "Sending the apology and retiring the message.",
            msg.thread_id,
            msg.msg_id,
            self.store.attempt_count(msg.msg_id),
            self.cfg.max_attempts_per_message,
        )
        try:
            self._apologise(msg.thread_id)
        except Exception:  # noqa: BLE001 - see docstring: MUST NOT block the retire
            log.exception(
                "could not send the give-up apology on thread %s; retiring msg %s "
                "anyway. THE MINISTER HAS NOT BEEN TOLD — this thread needs a human.",
                msg.thread_id,
                msg.msg_id,
            )
        finally:
            # The only line that makes give-up terminal. Records the message in
            # the ledger (so is_processed() rejects it on every future pass) and
            # releases the claim, in one transaction.
            self.store.mark_processed(msg.thread_id, msg.msg_id, session_id)
            result.gave_up.append(msg.msg_id)


__all__ = ["APOLOGY_BODY", "Dispatcher", "DispatchResult", "RunAgent", "SendReply"]
