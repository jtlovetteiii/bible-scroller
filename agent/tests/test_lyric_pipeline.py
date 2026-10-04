"""Golden test: the whole deterministic pipeline over the REAL 2026-07-26 email.

Network-free and deterministic, the way `tests/build-deck.test.js` pins `build-deck.js`
(spec §5). The nondeterministic part — the local model — is frozen into
`tests/fixtures/specs_0726.json`: five specs it actually produced, captured 2026-08-02
with `probe_consensus.py --save-specs`. Note the fixture is line numbers and titles
only and contains **zero lyric characters**, which is the design's central claim made
checkable (`test_the_frozen_specs_contain_no_lyric_text`).

So this file pins consensus → repair → slice → redact against a known-hard input. To
re-cut the fixture after a prompt or model change, re-run `--save-specs` and expect
these numbers to move; they are a record of behaviour, not a law.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "probes"))

import fixture_0726  # noqa: E402
from email_agent.lyrics import (  # noqa: E402
    Section,
    Song,
    consensus,
    redact,
    render_song,
    repair_spec,
    uniquify_section_names,
    validate_spec,
)

FIXTURE = Path(__file__).parent / "fixtures" / "specs_0726.json"


@pytest.fixture(scope="module")
def email() -> str:
    return fixture_0726.minister_lyrics()


@pytest.fixture(scope="module")
def specs() -> list[list[Song]]:
    return [
        [
            Song(slug=s["slug"], title=s["title"],
                 sections=[Section(**sec) for sec in s["sections"]])
            for s in spec
        ]
        for spec in json.loads(FIXTURE.read_text())
    ]


@pytest.fixture(scope="module")
def merged(specs, email):
    """Consensus + the de-confliction the real caller applies. K=1, the safe default."""
    rep = consensus(specs, email, line_threshold=1, song_threshold=1)
    rep.songs, _ = repair_spec(rep.songs, email)
    uniquify_section_names(rep.songs)
    validate_spec(rep.songs, email)
    return rep


def _lyric_lines(email: str) -> set[str]:
    """What the minister actually pasted: not his prose line, not the six labels."""
    lines = email.splitlines()
    labels = {ln for ln in lines if ln.strip().lower().endswith("lyrics:")}
    return {ln for ln in lines[1:] if ln.strip() and ln not in labels}


def test_the_frozen_specs_contain_no_lyric_text(email):
    """The design's whole claim, as a test: the model emits numbers, not words."""
    blob = FIXTURE.read_text()
    present = [ln for ln in _lyric_lines(email) if ln.strip() and ln.strip() in blob]
    assert not present, f"the spec fixture contains lyric text: {present[:3]}"


def test_finds_exactly_the_six_songs(merged):
    assert [s.title for s in merged.songs] == [
        "The Lord Will Provide",
        "One Day",
        "How Firm a Foundation",
        "All Hail King Jesus",
        "Goodness of God",
        "Jesus, Keep Me Near the Cross",
    ]


def test_no_lyric_survives_redaction(merged, email):
    """The failure this design exists to prevent. Exact-line AND substring."""
    redacted = redact(merged.songs, email)
    red_lines = set(redacted.splitlines())
    lyrics = _lyric_lines(email)
    assert not [ln for ln in lyrics if ln in red_lines], "a lyric line survived as a line"
    assert not [
        ln for ln in lyrics if len(ln.strip()) > 12 and ln.strip() in redacted
    ], "a lyric line survived inside another line"


def test_every_extracted_line_is_byte_exact(merged, email):
    """No text is regenerated, so nothing can be subtly wrong on a slide."""
    source = set(email.splitlines())
    checked = 0
    for song in merged.songs:
        body = render_song(song, email).split("---", 2)[-1]
        for ln in body.splitlines():
            if ln.strip() and not ln.startswith("##"):
                checked += 1
                assert ln in source, f"{song.slug}: {ln!r} is not a line of the email"
    assert checked == 212, f"expected 212 extracted lines, got {checked}"


def test_section_headings_are_unique_per_song(merged, email):
    """schemas/deck.schema.json requires it — a deck names a section to project it."""
    for song in merged.songs:
        headings = [ln for ln in render_song(song, email).splitlines() if ln.startswith("## ")]
        assert len(headings) == len(set(headings)), f"{song.slug}: duplicate {headings}"


def test_stanza_structure_survives(merged):
    """Blank lines are not claimed, so stanzas stay separate rather than fusing.

    How Firm a Foundation is the check worth having: four verses, no chorus. When
    blank lines were claimed it came out as one section covering the whole song.
    """
    by_slug = {s.slug: s for s in merged.songs}
    assert len(by_slug["how-firm-a-foundation"].sections) == 4
    # And no song collapsed to a single section.
    assert all(len(s.sections) > 1 for s in merged.songs if s.slug != "the-lord-will-provide")


def test_no_song_swallows_another(merged, email):
    """Per-line majority ownership. Under a plain union one spec's over-long range
    filed the whole of One Day under The Lord Will Provide."""
    lines = email.splitlines()
    for song in merged.songs:
        text = render_song(song, email)
        # A song file may still carry a swallowed label (a known, reported over-claim),
        # but it must not carry another song's actual stanzas.
        for other in merged.songs:
            if other.slug == song.slug:
                continue
            other_first = lines[min(sec.start for sec in other.sections) - 1]
            assert other_first not in text, (
                f"{song.slug} contains {other.slug}'s opening line {other_first!r}"
            )


def test_no_line_is_stranded_in_the_wrong_song(merged, email):
    """A claimed line between two lines of song X belongs to X.

    Line 180, 'Singing "Holy", singing "Holy"', was filed under One Day while 178, 179
    and 181 were all All Hail King Jesus — a real lyric in the wrong song file. The
    frontier model caught it and moved it by hand, which is exactly the kind of rescue
    this design must not depend on.
    """
    owner: dict[int, str] = {}
    for song in merged.songs:
        for sec in song.sections:
            for i in range(sec.start, sec.end + 1):
                owner[i] = song.slug
    islands = [
        i for i in owner
        if owner.get(i - 1) and owner.get(i - 1) == owner.get(i + 1) != owner[i]
    ]
    assert not islands, f"lines stranded in the wrong song: {islands}"
    assert owner[180] == "all-hail-king-jesus"


def test_overclaim_candidates_are_reported(merged):
    """They cannot be dropped (that is the leak direction) so they must be surfaced."""
    assert merged.low_confidence, "no over-claim candidates flagged at all"
    flagged = {ln for ln, _, _ in merged.low_confidence}
    # Line 75 is "ONE DAY lyrics:", one of the labels the consensus actually swallowed.
    assert 75 in flagged
