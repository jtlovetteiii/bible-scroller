"""Dispatcher + state store tests — bs-tiz.2 acceptance criteria (spec §4.2, §7)."""

from __future__ import annotations

import dataclasses
import threading
import time

import pytest

from email_agent.dispatcher import APOLOGY_BODY, Dispatcher
from email_agent.gate import GatedMessage
from email_agent.store import DONE, FAILED, IN_FLIGHT, StateStore


class RecordingAgent:
    """Fake harness (the bs-tiz.4 seam). Records calls; optionally slow/failing."""

    def __init__(self, *, delay: float = 0.0, fail: bool = False):
        self.calls: list[tuple[str, str, str | None]] = []
        self.delay = delay
        self.fail = fail
        self.lock = threading.Lock()
        self._counter = 0

    def __call__(self, thread_id: str, msg_id: str, session_id: str | None) -> str | None:
        with self.lock:
            self.calls.append((thread_id, msg_id, session_id))
            self._counter += 1
            n = self._counter
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("agent exploded")
        # New session for a cold thread; a resume hands the same one back.
        return session_id or f"sess-{n}"


def initial(msg_id: str, thread_id: str = "t1") -> GatedMessage:
    return GatedMessage(thread_id=thread_id, msg_id=msg_id, is_reply=False)


def reply(msg_id: str, thread_id: str = "t1") -> GatedMessage:
    return GatedMessage(thread_id=thread_id, msg_id=msg_id, is_reply=True)


# --- concurrency ------------------------------------------------------------


def test_overlapping_passes_launch_the_agent_exactly_once(cfg, store):
    """The whole reason SQLite was chosen over a JSON file.

    Two heartbeat passes genuinely overlap (real threads, real temp SQLite file,
    a slow agent) on the same thread. Exactly one may run the agent — otherwise
    the minister gets two decks and two replies.
    """
    agent = RecordingAgent(delay=0.4)
    msgs = [initial("m1")]

    # Two dispatchers => two connections => a real cross-connection race.
    results: dict[str, object] = {}
    barrier = threading.Barrier(2)

    def pass_(name: str) -> None:
        dispatcher = Dispatcher(StateStore(cfg.state_db_path), agent, cfg)
        barrier.wait()  # maximize the overlap
        results[name] = dispatcher.dispatch(msgs)

    a = threading.Thread(target=pass_, args=("a",))
    b = threading.Thread(target=pass_, args=("b",))
    a.start()
    b.start()
    a.join()
    b.join()

    assert len(agent.calls) == 1, f"agent ran {len(agent.calls)} times: {agent.calls}"

    winner = [r for r in results.values() if r.processed]  # type: ignore[attr-defined]
    loser = [r for r in results.values() if r.skipped_in_flight]  # type: ignore[attr-defined]
    assert len(winner) == 1 and len(loser) == 1

    state = store.get("t1")
    assert state.status == DONE
    assert state.last_processed_msg_id == "m1"


def test_many_concurrent_claims_yield_a_single_winner(cfg):
    stores = [StateStore(cfg.state_db_path) for _ in range(8)]
    wins: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def claim(s: StateStore) -> None:
        barrier.wait()
        won = s.claim("t1", stale_after_seconds=cfg.agent_timeout_seconds)
        with lock:
            wins.append(won)

    threads = [threading.Thread(target=claim, args=(s,)) for s in stores]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(wins) == 1, f"expected exactly one claim winner, got {sum(wins)}"


# --- session mapping --------------------------------------------------------


def test_reply_resolves_to_the_same_session_as_its_initiating_message(cfg, store):
    agent = RecordingAgent()
    dispatcher = Dispatcher(store, agent, cfg)

    dispatcher.dispatch([initial("m1")])
    session_id = store.get("t1").session_id
    assert session_id is not None

    dispatcher.dispatch([reply("m2")])

    assert agent.calls == [
        ("t1", "m1", None),  # initial => new session
        ("t1", "m2", session_id),  # reply => resume the SAME session
    ]
    assert store.get("t1").session_id == session_id


def test_new_thread_gets_a_distinct_session(cfg, store):
    agent = RecordingAgent()
    dispatcher = Dispatcher(store, agent, cfg)

    dispatcher.dispatch([initial("m1", "t1"), initial("m2", "t2")])

    assert store.get("t1").session_id != store.get("t2").session_id


# --- idempotency ------------------------------------------------------------


def test_already_processed_message_is_not_reprocessed(cfg, store):
    agent = RecordingAgent()
    dispatcher = Dispatcher(store, agent, cfg)

    dispatcher.dispatch([initial("m1")])
    # The gate re-emits it next tick — it is still inside the lookback window.
    result = dispatcher.dispatch([initial("m1")])

    assert len(agent.calls) == 1
    assert result.skipped_already_processed == ["m1"]


def test_older_message_is_not_reprocessed_after_a_newer_one(cfg, store):
    """last_processed_msg_id alone can't answer this; the ledger can."""
    agent = RecordingAgent()
    dispatcher = Dispatcher(store, agent, cfg)

    dispatcher.dispatch([initial("m1"), reply("m2")])
    assert len(agent.calls) == 2

    # Gate re-emits the whole lookback window, oldest first.
    result = dispatcher.dispatch([initial("m1"), reply("m2")])

    assert len(agent.calls) == 2
    assert sorted(result.skipped_already_processed) == ["m1", "m2"]


# --- failure semantics (spec §7) -------------------------------------------


def test_agent_error_marks_failed_releases_the_claim_and_retries(cfg, store):
    failing = RecordingAgent(fail=True)
    dispatcher = Dispatcher(store, failing, cfg)

    result = dispatcher.dispatch([initial("m1")])

    assert result.failed == ["m1"]
    state = store.get("t1")
    assert state.status == FAILED  # out of in-flight
    assert state.status != IN_FLIGHT  # claim released — never locked forever
    assert state.last_processed_msg_id is None  # NOT committed

    # ...and the next pass retries it rather than dropping it.
    ok = RecordingAgent()
    Dispatcher(store, ok, cfg).dispatch([initial("m1")])

    assert ok.calls == [("t1", "m1", None)]
    assert store.get("t1").status == DONE


# --- the retry bound (bs-9ed) ----------------------------------------------


class RecordingSend:
    """Fake `tools.send_reply`. Records every apology; optionally refuses to send."""

    def __init__(self, *, fail: bool = False):
        self.calls: list[dict] = []
        self.fail = fail

    def __call__(self, thread_id: str, body: str, *, store=None):
        self.calls.append({"thread_id": thread_id, "body": body, "store": store})
        if self.fail:
            raise RuntimeError("gmail is down")
        return {"id": f"apology-{len(self.calls)}", "threadId": thread_id}


def test_persistently_failing_message_is_bounded_apologised_once_and_retired(cfg, store):
    """bs-9ed. Before the bound existed this ran the agent on EVERY tick for the
    whole 7-day lookback window — thousands of Sonnet runs on the subscription —
    and never told the minister anything.
    """
    agent = RecordingAgent(fail=True)
    send = RecordingSend()
    dispatcher = Dispatcher(store, agent, cfg, send_reply=send)

    results = [dispatcher.dispatch([initial("m1")]) for _ in range(10)]

    # Bounded: the agent ran max_attempts times, not once per pass.
    assert len(agent.calls) == cfg.max_attempts_per_message

    # Exactly one apology, to the right thread, with the fixed body (no LLM).
    assert len(send.calls) == 1
    assert send.calls[0]["thread_id"] == "t1"
    assert send.calls[0]["body"] == APOLOGY_BODY

    # ...and it went out through the store, so `mark_agent_sent` records our
    # authorship and the gate can never hand the apology back as a new request.
    assert send.calls[0]["store"] is store

    # Retired on the pass that crossed the bound, and never touched again.
    n = cfg.max_attempts_per_message
    assert [i for i, r in enumerate(results) if r.gave_up == ["m1"]] == [n - 1]
    # Every pass after that is a no-op: no agent, no mail, just the ledger.
    assert all(r.skipped_already_processed == ["m1"] for r in results[n:])
    assert all(r.failed == [] and r.gave_up == [] for r in results[n:])
    assert store.is_processed("m1") is True
    assert store.get("t1").status == DONE  # claim released, thread not wedged


def test_give_up_is_terminal_even_when_the_apology_cannot_be_sent(cfg, store):
    """The subtle half of bs-9ed.

    If a failed apology kept the message in the retry pool, the unbounded loop
    would simply move up a level — the same message re-entering the give-up path
    on every pass forever, now hammering Gmail instead of the model.
    """
    cfg = dataclasses.replace(cfg, max_attempts_per_message=2)
    agent = RecordingAgent(fail=True)
    send = RecordingSend(fail=True)
    dispatcher = Dispatcher(store, agent, cfg, send_reply=send)

    for _ in range(6):
        dispatcher.dispatch([initial("m1")])

    assert len(agent.calls) == 2  # still bounded
    assert len(send.calls) == 1  # tried once, failed, never retried
    assert store.is_processed("m1") is True  # left the pool ANYWAY
    assert store.get("t1").status == DONE


def test_attempts_are_counted_before_the_run_so_a_lost_process_still_pays(cfg, store):
    """A run that never returns — killed process, reboot, reaped timeout — never
    reaches the failure handler. Counting on the way *in* is what bounds it.
    """
    seen: list[int] = []

    def agent(thread_id: str, msg_id: str, session_id: str | None) -> str:
        seen.append(store.attempt_count(msg_id))  # mid-run: already counted
        return "sess-x"

    Dispatcher(store, agent, cfg).dispatch([initial("m1")])

    assert seen == [1]


def test_the_attempt_counter_survives_a_restart(cfg):
    """The heartbeat is a fresh process every tick, so an in-memory counter would
    reset to zero before it ever bounded anything. Separate StateStore instances
    on the same file stand in for separate processes.
    """
    agent = RecordingAgent(fail=True)
    send = RecordingSend()

    for _ in range(5):
        # A brand-new store + dispatcher per pass, as CRON gives us.
        Dispatcher(StateStore(cfg.state_db_path), agent, cfg, send_reply=send).dispatch(
            [initial("m1")]
        )

    assert len(agent.calls) == cfg.max_attempts_per_message
    assert len(send.calls) == 1


def test_the_bound_is_per_message_not_per_thread(cfg, store):
    """One poison message must not retire its thread's other traffic."""
    cfg = dataclasses.replace(cfg, max_attempts_per_message=1)
    send = RecordingSend()
    poison = RecordingAgent(fail=True)

    Dispatcher(store, poison, cfg, send_reply=send).dispatch([initial("m1")])
    assert store.is_processed("m1") is True  # retired

    # A reply on the SAME thread is unaffected and still runs.
    ok = RecordingAgent()
    result = Dispatcher(store, ok, cfg, send_reply=send).dispatch([reply("m2")])

    assert result.processed == ["m2"]
    assert len(ok.calls) == 1


def test_an_exhausted_message_is_retired_without_running_the_agent_again(cfg, store):
    """The pre-run guard, independently of the eager give-up.

    Reachable when a pass is killed between recording its attempt and reaching
    the failure handler — exactly the unattended-box case, where the runs that
    kill the process are the ones nobody is there to see.
    """
    for _ in range(cfg.max_attempts_per_message):
        store.record_attempt("t1", "m1")  # a previous process's attempts

    agent = RecordingAgent(fail=True)
    send = RecordingSend()
    result = Dispatcher(store, agent, cfg, send_reply=send).dispatch([initial("m1")])

    assert agent.calls == []  # not one more Sonnet run
    assert result.gave_up == ["m1"]
    assert len(send.calls) == 1
    assert store.is_processed("m1") is True


def test_a_healthy_message_never_apologises(cfg, store):
    send = RecordingSend()
    dispatcher = Dispatcher(store, RecordingAgent(), cfg, send_reply=send)

    result = dispatcher.dispatch([initial("m1")])

    assert result.processed == ["m1"] and result.gave_up == []
    assert send.calls == []


def test_message_is_marked_processed_only_after_the_agent_returns(cfg, store):
    """Commit boundary: the harness sends the reply, then we commit."""
    observed: list[bool] = []

    def agent(thread_id: str, msg_id: str, session_id: str | None) -> str:
        # Mid-run, before any reply has been sent: must not be in the ledger.
        observed.append(store.is_processed(msg_id))
        return "sess-x"

    Dispatcher(store, agent, cfg).dispatch([initial("m1")])

    assert observed == [False]
    assert store.is_processed("m1") is True


def test_reply_arriving_mid_run_is_deferred_then_reprocessed(cfg, store):
    """Spec §7: skipped this tick (in-flight), NOT dropped."""
    agent = RecordingAgent()
    dispatcher = Dispatcher(store, agent, cfg)

    # Simulate the agent still working on m1 (thread claimed by another pass).
    assert store.claim("t1", stale_after_seconds=cfg.agent_timeout_seconds)

    mid_run = dispatcher.dispatch([reply("m2")])
    assert mid_run.skipped_in_flight == ["m2"]
    assert agent.calls == []

    # The in-flight run finishes and releases.
    store.mark_processed("t1", "m1", "sess-1")

    after = dispatcher.dispatch([reply("m2")])
    assert after.processed == ["m2"]
    assert agent.calls == [("t1", "m2", "sess-1")]  # resumed, not dropped


# --- stale-claim reaper -----------------------------------------------------


def test_stale_claim_is_reaped_after_the_timeout(cfg, store):
    """A crashed process leaves a claim behind with nobody to release it."""
    cfg = dataclasses.replace(cfg, agent_timeout_seconds=1)
    agent = RecordingAgent()
    dispatcher = Dispatcher(store, agent, cfg)

    # A process claimed t1 and died.
    assert store.claim("t1", stale_after_seconds=1)
    assert store.get("t1").status == IN_FLIGHT

    # Not yet stale: the message is still deferred.
    assert dispatcher.dispatch([initial("m1")]).skipped_in_flight == ["m1"]
    assert agent.calls == []

    time.sleep(1.1)

    result = dispatcher.dispatch([initial("m1")])

    assert result.reaped == ["t1"]
    assert result.processed == ["m1"]
    assert agent.calls == [("t1", "m1", None)]
    assert store.get("t1").status == DONE


def test_fresh_claim_is_not_reaped(cfg, store):
    store.claim("t1", stale_after_seconds=cfg.agent_timeout_seconds)

    assert store.reap_stale(stale_after_seconds=cfg.agent_timeout_seconds) == []
    assert store.get("t1").status == IN_FLIGHT


# --- store basics -----------------------------------------------------------


def test_store_persists_across_instances(cfg):
    StateStore(cfg.state_db_path).mark_processed("t1", "m1", "sess-1")

    state = StateStore(cfg.state_db_path).get("t1")

    assert (state.session_id, state.last_processed_msg_id, state.status) == (
        "sess-1",
        "m1",
        DONE,
    )


def test_unknown_thread_is_none(store):
    assert store.get("nope") is None


@pytest.mark.parametrize("status", [DONE, FAILED])
def test_released_thread_can_be_reclaimed(cfg, store, status):
    store.claim("t1", stale_after_seconds=cfg.agent_timeout_seconds)
    if status == DONE:
        store.mark_processed("t1", "m1", "s")
    else:
        store.mark_failed("t1")

    assert store.claim("t1", stale_after_seconds=cfg.agent_timeout_seconds) is True
