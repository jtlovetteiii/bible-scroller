"""SQLite state store — bs-tiz.2 (spec §4.2, §7).

Owns **all** cross-run state:

    threadId -> { session_id, last_processed_msgId, status, updated_at }

and nothing else. The Claude Agent SDK persists the conversation transcript
itself (JSONL on disk), so this store holds only mapping/bookkeeping — never
conversation history.

Why SQLite and not a JSON file: the ~60s heartbeat **overlaps itself** (slide
generation takes minutes), so a read-then-write claim would race and
double-process a thread — two agents, two replies. Every claim here is a single
atomic conditional UPDATE inside an IMMEDIATE transaction; the winner is decided
by ``rowcount``, not by anything the process read beforehand.

Second table, ``processed_messages``: ``threads.last_processed_msg_id`` records
the most recent message per spec, but a *single* column cannot answer "have we
handled msg A?" once msg B has landed on top of it — and the gate legitimately
re-emits older messages for the whole lookback window. The ledger is the
authoritative idempotency check; the spec column is kept as the summary view.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

# --- Thread status values ---------------------------------------------------
NEW = "new"  # seen, never run
IN_FLIGHT = "in_flight"  # claimed; an agent is running (or the process died)
DONE = "done"  # last run completed and its reply was sent
FAILED = "failed"  # last run errored / timed out / was reaped; claim released

#: Statuses that do NOT hold the claim.
RELEASED = (NEW, DONE, FAILED)

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    thread_id             TEXT PRIMARY KEY,
    session_id            TEXT,
    last_processed_msg_id TEXT,
    status                TEXT NOT NULL DEFAULT 'new',
    updated_at            REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_messages (
    thread_id    TEXT NOT NULL,
    msg_id       TEXT NOT NULL PRIMARY KEY,
    processed_at REAL NOT NULL
);

-- Messages the agent itself wrote. Surfaced to the agent as an authorship HINT
-- (see get_thread), and used by the dispatcher as a cheap runaway-loop guard.
-- Kept separate from processed_messages because "we wrote it" and "we handled it"
-- are different facts, even though they currently coincide.
CREATE TABLE IF NOT EXISTS agent_sent_messages (
    thread_id TEXT NOT NULL,
    msg_id    TEXT NOT NULL PRIMARY KEY,
    sent_at   REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_processed_thread ON processed_messages (thread_id);
CREATE INDEX IF NOT EXISTS idx_agent_sent_thread ON agent_sent_messages (thread_id);
"""


@dataclass(frozen=True)
class ThreadState:
    thread_id: str
    session_id: str | None
    last_processed_msg_id: str | None
    status: str
    updated_at: float


class StateStore:
    """Thread-safe, process-safe state for the dispatcher."""

    def __init__(self, db_path: str | Path, *, busy_timeout_seconds: float = 30.0):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._busy_timeout_seconds = busy_timeout_seconds
        with self._connect() as conn:
            # WAL: readers never block the writer, and the write lock is short.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A closed-on-exit connection.

        Note: `with sqlite3.connect(...)` commits but does *not* close, so the
        connection is wrapped rather than used directly.
        """
        conn = sqlite3.connect(
            self.db_path,
            timeout=self._busy_timeout_seconds,
            # isolation_level=None => no implicit BEGIN; we control transactions
            # ourselves so a claim can use BEGIN IMMEDIATE.
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={int(self._busy_timeout_seconds * 1000)}")
        try:
            yield conn
        finally:
            conn.close()

    # --- reads --------------------------------------------------------------

    def get(self, thread_id: str) -> ThreadState | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM threads WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        return _to_state(row) if row else None

    def is_processed(self, msg_id: str) -> bool:
        """Has this exact message already been fully handled (reply sent)?

        Also true for messages the agent itself authored — see `mark_agent_sent`.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_messages WHERE msg_id = ?", (msg_id,)
            ).fetchone()
        return row is not None

    def mark_agent_sent(self, thread_id: str, msg_id: str) -> None:
        """Record a message the agent itself sent, so it can never become input.

        THE REPLY LOOP GUARD. Our reply keeps the thread's subject (`Re: AI: …`),
        so it matches the gate's subject regex just as well as the original did.
        Left alone, the gate hands the agent its own outgoing mail on the next
        tick and it replies to itself, forever, burning tokens. (Observed live on
        2026-07-11 before this existed.)

        Filtering on sender or on the SENT label does NOT work: when the operator
        emails themselves — exactly how you test this — every message in the
        thread carries both SENT and INBOX and is from the same address, so our
        replies are indistinguishable from a real request by any header. The only
        reliable fact is authorship, which we know because we sent it.

        Recording it as "processed" makes the existing dispatcher check reject it
        with no new code path.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO processed_messages (thread_id, msg_id, processed_at) "
                "VALUES (?, ?, ?)",
                (thread_id, msg_id, time.time()),
            )
            conn.execute(
                "INSERT OR IGNORE INTO agent_sent_messages (thread_id, msg_id, sent_at) "
                "VALUES (?, ?, ?)",
                (thread_id, msg_id, time.time()),
            )

    def is_agent_sent(self, msg_id: str) -> bool:
        """Did WE write this message? Surfaced to the agent as a hint by `get_thread`.

        Deliberately separate from `is_processed`: "we authored it" and "we have
        handled it" are different facts that happen to coincide today. Keeping them
        distinct means the agent's view of authorship does not silently change if
        the bookkeeping semantics of `processed_messages` ever do.

        This is a HINT, not a safety mechanism. It is only as good as the local DB —
        wipe it and every message reads as not-ours. The agent must be able to reach
        the same conclusion by reading the thread.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM agent_sent_messages WHERE msg_id = ?", (msg_id,)
            ).fetchone()
        return row is not None

    # --- the claim ----------------------------------------------------------

    def claim(self, thread_id: str, *, stale_after_seconds: float, now: float | None = None) -> bool:
        """Atomically take the in-flight claim on a thread. True == we own it.

        This is the whole reason for SQLite. It is deliberately a single
        conditional UPDATE — never read-then-write — so two overlapping
        heartbeats racing on the same thread cannot both win: SQLite serializes
        the writes and exactly one sees ``rowcount == 1``.

        A claim older than ``stale_after_seconds`` is considered abandoned (the
        holding process crashed) and may be taken over, so a thread can never be
        locked forever.
        """
        now = time.time() if now is None else now
        cutoff = now - stale_after_seconds
        with self._connect() as conn:
            try:
                # IMMEDIATE: grab the write lock up-front rather than upgrading
                # mid-transaction, which is where SQLITE_BUSY deadlocks come from.
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT OR IGNORE INTO threads (thread_id, status, updated_at) "
                    "VALUES (?, ?, ?)",
                    (thread_id, NEW, now),
                )
                cur = conn.execute(
                    "UPDATE threads SET status = ?, updated_at = ? "
                    "WHERE thread_id = ? AND (status != ? OR updated_at < ?)",
                    (IN_FLIGHT, now, thread_id, IN_FLIGHT, cutoff),
                )
                won = cur.rowcount == 1
                conn.execute("COMMIT")
                return won
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def reap_stale(self, *, stale_after_seconds: float, now: float | None = None) -> list[str]:
        """Release claims held longer than the timeout; return the thread IDs.

        Required, not optional: a process killed mid-run leaves ``in_flight``
        behind with no one to release it. Reaping moves it to ``failed`` so the
        next pass can retry the message (it was never marked processed).
        """
        now = time.time() if now is None else now
        cutoff = now - stale_after_seconds
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute(
                    "SELECT thread_id FROM threads WHERE status = ? AND updated_at < ?",
                    (IN_FLIGHT, cutoff),
                ).fetchall()
                conn.execute(
                    "UPDATE threads SET status = ?, updated_at = ? "
                    "WHERE status = ? AND updated_at < ?",
                    (FAILED, now, IN_FLIGHT, cutoff),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return [r["thread_id"] for r in rows]

    # --- releases -----------------------------------------------------------

    def mark_processed(self, thread_id: str, msg_id: str, session_id: str | None) -> None:
        """Commit boundary (spec §7): called only AFTER the reply has been sent.

        Records the message in the ledger, stores the thread's session_id, and
        releases the claim — in one transaction.
        """
        now = time.time()
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT OR IGNORE INTO processed_messages (thread_id, msg_id, processed_at) "
                    "VALUES (?, ?, ?)",
                    (thread_id, msg_id, now),
                )
                # Upsert: the dispatcher always claims first so the row exists,
                # but a bare UPDATE would silently no-op if it didn't — leaving
                # a ledger entry with no thread row.
                conn.execute(
                    "INSERT OR IGNORE INTO threads (thread_id, status, updated_at) "
                    "VALUES (?, ?, ?)",
                    (thread_id, NEW, now),
                )
                conn.execute(
                    "UPDATE threads SET status = ?, session_id = COALESCE(?, session_id), "
                    "last_processed_msg_id = ?, updated_at = ? WHERE thread_id = ?",
                    (DONE, session_id, msg_id, now, thread_id),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def mark_failed(self, thread_id: str, session_id: str | None = None) -> None:
        """Release the claim after an agent error/timeout. Message stays unprocessed.

        The message is deliberately NOT added to the ledger, so the next pass
        retries it. A session_id captured before the failure is still worth
        keeping — a retry can resume that session rather than start cold.
        """
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE threads SET status = ?, session_id = COALESCE(?, session_id), "
                "updated_at = ? WHERE thread_id = ?",
                (FAILED, session_id, now, thread_id),
            )

    def release(self, thread_id: str) -> None:
        """Drop the claim without recording success or failure."""
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE threads SET status = ?, updated_at = ? "
                "WHERE thread_id = ? AND status = ?",
                (DONE, now, thread_id, IN_FLIGHT),
            )

    # --- diagnostics --------------------------------------------------------

    def all_threads(self) -> list[ThreadState]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM threads ORDER BY updated_at").fetchall()
        return [_to_state(r) for r in rows]


def _to_state(row: sqlite3.Row) -> ThreadState:
    return ThreadState(
        thread_id=row["thread_id"],
        session_id=row["session_id"],
        last_processed_msg_id=row["last_processed_msg_id"],
        status=row["status"],
        updated_at=row["updated_at"],
    )
