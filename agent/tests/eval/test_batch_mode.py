"""Evals for gen_service's non-interactive batch mode (bs-ixn).

Run: uv run pytest -m eval -s

The two flowcharts in examples/flowcharts.md pin the two halves of the batch
contract, and they are deliberately different shapes:

  7/12 — nothing blocks. The agent must BUILD, and ask for what it is missing
         alongside the deck link.
  7/5  — the "Quartet" line names no song. A slide cannot sensibly exist, so the
         agent must NOT build. It holds and asks first.

Getting these two backwards is the failure that matters: an agent that always
builds ships a deck with an invented quartet number, and an agent that always
asks makes the operator wait a day for a deck he could have had immediately.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from eval_harness import (  # noqa: F401 — `stage` is imported to register the fixture
    read_flowchart,
    rebuild,
    run_gen_service,
    seed_library,
    stage,
    validate_deck,
)

# The agent runs once per flowchart (module-scoped fixture), so the tests reading
# that run must share the module's event loop.
pytestmark = [pytest.mark.eval, pytest.mark.asyncio(loop_scope="module")]


# ── 7/12: nothing blocks — build, and ask alongside ─────────────────────────

SERVICE_DATE_0712 = "2026-07-12"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def run_0712(stage):
    # What the agent already knows. "O For A Thousand Tongues" is in the library
    # and must be reused; everything else in this flowchart is new to it.
    #   Tell Me the Story of Jesus     — public-domain hymn -> look it up, save it
    #   Before the Throne of God Above — the invitation hymn, likewise
    #   Forever Yahweh                 — modern praise, no lookup path -> ASK
    #   Amazing Love Medley            — a choir number, never from the library
    ws = stage("s0712")
    seed_library(ws, keep={"o-for-a-thousand-tongues-to-sing", "waymaker"})

    return await run_gen_service(
        ws,
        read_flowchart("7/12/2026"),
        subject="Order of service 7/12",
        today="2026-07-07",
    )


async def test_0712_builds_a_deck_despite_the_missing_lyrics(run_0712):
    """The non-blocking tier: one unresolvable song must not cost the whole deck."""
    assert run_0712.built_a_deck(SERVICE_DATE_0712), (
        "nothing in this flowchart blocks a slide, so the agent should have built "
        f"the deck rather than holding it. It replied:\n\n{run_0712.reply}"
    )
    validate_deck(run_0712.workspace, run_0712.deck(SERVICE_DATE_0712))

    built = rebuild(run_0712.workspace, SERVICE_DATE_0712)
    assert built.returncode == 0, f"the agent's own deck does not rebuild:\n{built.stderr}"


async def test_0712_supplies_the_skeleton_the_flowchart_leaves_out(run_0712):
    """The flowchart lists only music. Everything around it has to be inferred."""
    types = run_0712.segment_types(SERVICE_DATE_0712)

    for implied in ("preshow", "prelude", "welcome", "sermon_transition", "closing_prayer"):
        assert implied in types, f"the deck is missing the implied {implied!r} segment: {types}"

    # Order is the part that actually matters — a welcome after the sermon is not
    # a service. Check the fixed spine holds, ignoring the music in between.
    spine = [t for t in types if t in ("preshow", "welcome", "sermon_transition", "closing_prayer")]
    assert spine == ["preshow", "welcome", "sermon_transition", "closing_prayer"]


async def test_0712_tehillah_means_the_room_sings(run_0712):
    """bs-fdn, the distinction that decides whether the congregation sings or watches.

    'Choir: Amazing Love Medley' is a performed number. 'Tehillah: Forever Yahweh'
    is NOT — Tehillah is the praise team, so that song is congregational. Reading
    it as a performer name puts the wrong background on the slide and stops the
    room from singing.
    """
    choir = run_0712.find_music(SERVICE_DATE_0712, "amazing love")
    assert choir["type"] == "special_music", "the choir medley is a performed number"

    yahweh = run_0712.find_music(SERVICE_DATE_0712, "yahweh")
    assert yahweh["type"] == "song", (
        "'Tehillah: Forever Yahweh' is congregational singing — Tehillah is the "
        "praise team, not a performer"
    )


async def test_0712_asks_for_the_lyrics_it_could_not_find(run_0712):
    """The question it would have asked interactively becomes a line in the reply."""
    report = run_0712.report(SERVICE_DATE_0712)

    missing_lyrics = [m for m in report["missing"] if "lyric" in m.get("need", "").lower()]
    assert missing_lyrics, (
        "Forever Yahweh is a modern praise song with no lookup path, so the agent "
        f"should have reported it as missing lyrics rather than inventing them. "
        f"Report: {report['missing']}"
    )
    assert any("yahweh" in m.get("song", "").lower() for m in missing_lyrics)

    assert "yahweh" in run_0712.reply.lower(), (
        f"the reply never mentions the song it needs lyrics for:\n\n{run_0712.reply}"
    )


async def test_0712_reuses_the_library_and_flags_what_it_looked_up(run_0712):
    """Library first (bs-8yd); anything looked up is flagged for a human to check."""
    report = run_0712.report(SERVICE_DATE_0712)
    songs = {s["slug"] for s in report["songs"]}

    assert "o-for-a-thousand-tongues-to-sing" in songs, "the library copy should be reused"

    # "Tell Me the Story of Jesus" is a public-domain hymn the agent had never seen.
    # It should have looked it up and saved it rather than asking for it...
    story = run_0712.find_music(SERVICE_DATE_0712, "story of jesus")
    assert not story.get("title_only"), "a public-domain hymn is lookupable — don't ask for it"

    # ...and flagged it, because nobody has read those lyrics. The amber flag and
    # the `unverified` line ARE the "please check these slides" message. Saving it
    # as verified:true would ship unchecked lyrics with nothing to mark them.
    looked_up = {u["song"] for u in report["unverified"]}
    assert story["song"] in looked_up, (
        f"the agent looked up {story['song']!r} but marked it verified — nobody has "
        f"read those lyrics. unverified was: {sorted(looked_up)}"
    )


# ── 7/5: a slide cannot exist — hold, and ask first ─────────────────────────

SERVICE_DATE_0705 = "2026-07-05"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def run_0705(stage):
    ws = stage("s0705")
    seed_library(ws, keep={"i-am-resolved", "his-name-is-jesus"})

    return await run_gen_service(
        ws,
        read_flowchart("7/5/2026"),
        subject="Order of service 7/5",
        today="2026-06-30",
    )


async def test_0705_holds_the_deck_when_a_slide_cannot_exist(run_0705):
    """The blocking tier.

    'Quartet' names no song. Special music needs a title AND a performer, and the
    flowchart gives neither — so there is no honest slide to make. The agent must
    not guess a song, and must not ship a deck with a hole in it. It asks first.
    """
    # Order matters: assert it REPLIED before asserting it didn't build. Otherwise a
    # run that silently did nothing at all would pass this test — holding the deck
    # and dying are not the same outcome, and only one of them is correct.
    assert run_0705.replies, "the run ended without a reply — it must always send one"

    assert not run_0705.built_a_deck(SERVICE_DATE_0705), (
        "the Quartet line names no song, so no deck should have been built yet — "
        f"the agent should have asked first. It replied:\n\n{run_0705.reply}"
    )


async def test_0705_asks_for_the_quartet_song(run_0705):
    reply = run_0705.reply.lower()
    assert "quartet" in reply, f"the reply never raises the quartet:\n\n{run_0705.reply}"
    assert any(w in reply for w in ("song", "title", "piece")), (
        f"the reply must ask WHAT the quartet is singing:\n\n{run_0705.reply}"
    )


async def test_0705_may_suggest_the_performer_but_must_not_assume_it(run_0705):
    """A bare 'Quartet' is usually the Lovette Quartet — usually is not always.

    Suggesting it is helpful. Silently building on it is exactly the kind of quiet
    guess that puts a wrong name on the wall, so if the agent raises the name at
    all it must be asking, not asserting.
    """
    reply = run_0705.reply.lower()
    if "lovette" not in reply:
        return  # not suggesting it at all is fine — the ask for the song still stands

    # It offered the name. That is only safe if it is offering, not asserting. Cast a
    # wide net for the hedge: this is prose, and there are many ways to ask. The
    # load-bearing guarantee is structural and lives in the test above — it built no
    # deck, so it cannot have quietly acted on the guess.
    hedges = ("let me know", "confirm", "if that", "if this", "correct", "assume", "?")
    assert any(h in reply for h in hedges), (
        "the agent stated the Lovette Quartet as fact — it may suggest, but it must "
        f"leave him room to correct it:\n\n{run_0705.reply}"
    )
