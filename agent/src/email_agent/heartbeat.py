"""Heartbeat entry point — one poll -> dispatch pass, then exit.

CRON drives the cadence (``config.poll_interval_seconds``); this process does
exactly one pass per invocation so overlapping invocations are normal and safe —
the dispatcher's transactional claim is what makes them safe.

    * * * * * cd /path/to/agent && uv run python -m email_agent.heartbeat

The agent harness (bs-tiz.4) does not exist yet, so ``--dry-run`` is currently
the only usable mode: it runs the gate and reports what *would* be dispatched
without claiming or launching anything.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import config
from .dispatcher import Dispatcher
from .gate import poll
from .store import StateStore

log = logging.getLogger("email_agent.heartbeat")


def _load_run_agent():
    """Resolve the agent harness (bs-tiz.4) lazily.

    Kept as a late import so the gate/dispatcher/store are fully testable — and
    the heartbeat is fully importable — before the harness lands.
    """
    try:
        from .harness import run_agent  # type: ignore[attr-defined]
    except ImportError as exc:  # pragma: no cover - until bs-tiz.4 lands
        raise RuntimeError(
            "Agent harness (bs-tiz.4) is not implemented yet. "
            "Run with --dry-run to exercise the gate and dispatcher."
        ) from exc
    return run_agent


def run_once(*, dry_run: bool = False) -> int:
    messages = poll()
    if not messages:
        log.info("heartbeat: nothing actionable")
        return 0

    if dry_run:
        for m in messages:
            kind = "reply" if m.is_reply else "initial"
            print(f"{kind:<7} thread={m.thread_id} msg={m.msg_id}")
        return 0

    dispatcher = Dispatcher(StateStore(config.state_db_path), _load_run_agent(), config)
    result = dispatcher.dispatch(messages)
    log.info(
        "heartbeat: processed=%d in_flight=%d already_done=%d failed=%d reaped=%d "
        "gave_up=%d",
        len(result.processed),
        len(result.skipped_in_flight),
        len(result.skipped_already_processed),
        len(result.failed),
        len(result.reaped),
        len(result.gave_up),
    )
    if result.gave_up:
        # Retiring a message is the one outcome nobody will otherwise notice: it
        # looks like success (the thread goes quiet) but the minister got an
        # apology instead of slides.
        log.error("gave up on message(s) after exhausting retries: %s", result.gave_up)
    return 1 if result.failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="One poll->dispatch pass.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the gate only; print what would be dispatched. No claims, no agent.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    return run_once(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
