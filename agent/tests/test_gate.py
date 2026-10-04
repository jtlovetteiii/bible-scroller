"""Gate tests — bs-tiz.1 acceptance criteria (spec §4.1)."""

from __future__ import annotations

import dataclasses
import re

from conftest import FakeGmail, make_message

from email_agent.gate import METADATA_HEADERS, build_query, poll


def test_matching_initial_and_reply_are_detected_and_classified(cfg):
    gmail = FakeGmail(
        [
            make_message("m1", "t1", "AI: Order of service 7/13", internal_date=1000),
            make_message(
                "m2",
                "t1",
                "Re: AI: Order of service 7/13",
                references="<abc@mail>",
                internal_date=2000,
            ),
        ]
    )

    got = poll(service=gmail, cfg=cfg)

    assert [(g.thread_id, g.msg_id, g.is_reply) for g in got] == [
        ("t1", "m1", False),
        ("t1", "m2", True),
    ]


def test_reply_classified_by_headers_not_by_re_prefix(cfg):
    """Users edit subject lines; References/In-Reply-To is the reliable signal."""
    gmail = FakeGmail(
        [
            # A reply whose sender stripped the "Re:" — still a reply.
            make_message("m1", "t1", "AI: one more thing", references="<abc@mail>"),
            # A fresh mail that merely *says* Re: — the configured regex tolerates
            # the prefix, but with no threading headers it is an initial message.
            make_message("m2", "t2", "Re: AI: new request"),
        ]
    )

    by_id = {g.msg_id: g for g in poll(service=gmail, cfg=cfg)}

    assert by_id["m1"].is_reply is True
    assert by_id["m2"].is_reply is False


def test_non_matching_mail_is_ignored(cfg):
    gmail = FakeGmail(
        [
            make_message("m1", "t1", "Lunch on Sunday?"),
            make_message("m2", "t2", "FWD: your Amazon order"),
            make_message("m3", "t3", "Calvary AI — slides please"),
        ]
    )

    got = poll(service=gmail, cfg=cfg)

    assert [g.msg_id for g in got] == ["m3"]


def test_subject_pattern_is_configurable(cfg):
    cfg = dataclasses.replace(cfg, subject_pattern=re.compile(r"media AI", re.IGNORECASE))
    gmail = FakeGmail(
        [
            make_message("m1", "t1", "AI: slides"),
            make_message("m2", "t2", "Sunday media AI request"),
        ]
    )

    assert [g.msg_id for g in poll(service=gmail, cfg=cfg)] == ["m2"]


def test_no_message_bodies_are_ever_fetched(cfg):
    """Explicit acceptance criterion, not an optimization."""
    gmail = FakeGmail([make_message("m1", "t1", "AI: slides")])

    poll(service=gmail, cfg=cfg)

    get_calls = gmail.messages_resource.get_calls
    assert get_calls, "expected the gate to fetch message metadata"
    for call in get_calls:
        assert call["format"] == "metadata"
        assert call["metadataHeaders"] == METADATA_HEADERS
    # ...and nothing came back that could contain a body.
    assert all("full" != c.get("format") for c in get_calls)


def test_query_is_bounded_by_lookback_days(cfg):
    cfg = dataclasses.replace(cfg, lookback_days=3)
    gmail = FakeGmail([make_message("m1", "t1", "AI: slides")])

    poll(service=gmail, cfg=cfg)

    assert build_query(cfg) == "in:inbox newer_than:3d"
    assert gmail.messages_resource.list_calls[0]["q"] == "in:inbox newer_than:3d"


def test_output_is_ids_only(cfg):
    gmail = FakeGmail([make_message("m1", "t1", "AI: slides")])

    (gated,) = poll(service=gmail, cfg=cfg)

    assert set(vars(gated)) == {"thread_id", "msg_id", "is_reply"}
