"""Pins the safety invariant of the lyric-spec repair pass (bs-2pn / bs-8qs).

Pure and network-free, so it runs in the default suite. These modules still live in
tests/probes/ — the spec (§5) wants them promoted into src/email_agent/, and when
that happens this file should move with them unchanged.

WHAT IS BEING PROTECTED. `repair_spec` exists because the local model's line ranges
are mechanically sloppy: on the real 2026-07-26 email every one of seven runs was
rejected by `validate_spec`, always because a song's last section ran long — into
the next song's first line, or past the end of the email. Binning those specs made
the pipeline fail closed on the one email it was built for, so they are repaired
instead.

Repairing a spec is only safe because of one property:

    NO NON-BLANK CLAIMED LINE IS EVER GIVEN UP.

A claimed line is both written to songs/*.md and deleted from the email the cloud
model sees — one range set, one walk (spec §4.1). So a repair that quietly dropped a
line would not merely misfile a lyric, it would leave that lyric in the thread and
put the run back in front of the content filter. Mis-attribution is recoverable;
under-claiming is the failure the whole design exists to prevent.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

from email_agent.lyrics import (  # noqa: E402
    Section,
    Song,
    SpecError,
    repair_spec,
    uniquify_section_names,
    validate_spec,
)

# Every 4th line blank, so stanza separators are exercised the way a real email has
# them. Note the trailing blank is not a line as far as splitlines() is concerned, so
# N_LINES is derived from the text rather than assumed — the same count validate_spec
# bounds against.
EMAIL = "\n".join("" if i % 4 == 0 else f"line {i}" for i in range(1, 61))
N_LINES = len(EMAIL.splitlines())
NONBLANK = {i for i, ln in enumerate(EMAIL.splitlines(), 1) if ln.strip()}


def claimed(songs: list[Song]) -> set[int]:
    return {i for s in songs for sec in s.sections for i in range(sec.start, sec.end + 1)}


def _spec(rng: random.Random) -> list[Song]:
    """A deliberately broken spec: ranges that overlap, invert and run off both ends."""
    songs = []
    for si in range(rng.randint(1, 4)):
        sections = [
            Section(name=f"S{j}", start=(st := rng.randint(-3, N_LINES + 5)),
                    end=st + rng.randint(-2, 12))
            for j in range(rng.randint(1, 4))
        ]
        songs.append(Song(slug=f"song-{si}", title=f"Song {si}", sections=sections))
    return songs


def test_repair_never_gives_up_a_claimed_line():
    """The invariant, over 20k adversarial specs."""
    rng = random.Random(1234)
    for trial in range(20_000):
        spec = _spec(rng)
        before = claimed(spec) & NONBLANK
        after = claimed(repair_spec(spec, EMAIL)[0])
        assert before <= after, (
            f"trial {trial}: repair gave up non-blank lines {sorted(before - after)}. "
            "Those lyrics would stay in the thread and reach the content filter."
        )


def test_repair_output_always_validates():
    """Whatever goes in, what comes out is a spec we are willing to apply."""
    rng = random.Random(99)
    for trial in range(20_000):
        fixed, _ = repair_spec(_spec(rng), EMAIL)
        try:
            validate_spec(fixed, EMAIL)
        except SpecError as exc:  # pragma: no cover - only on regression
            pytest.fail(f"trial {trial}: repaired spec still invalid: {exc}")


def test_overlap_goes_to_the_later_starting_song():
    """The 7/26 failure, reduced: one song's range runs into the next song's first line.

    Line 20 is where `two` starts, so `two` keeps it and `one` is truncated to 19 —
    and line 20 is still claimed by somebody, which is what stops it leaking.
    """
    spec = [
        Song("one", "One", [Section("Verse 1", 5, 20)]),
        Song("two", "Two", [Section("Verse 1", 20, 30)]),
    ]
    fixed, repairs = repair_spec(spec, EMAIL)
    by_slug = {s.slug: s for s in fixed}
    assert by_slug["one"].sections[0].end == 19
    assert by_slug["two"].sections[0].start == 20
    assert 20 in claimed(fixed)
    assert any(r.kind == "truncate" for r in repairs)


def test_range_past_the_end_is_clamped_not_dropped():
    spec = [Song("one", "One", [Section("Verse 1", 50, N_LINES + 6)])]
    fixed, repairs = repair_spec(spec, EMAIL)
    assert fixed[0].sections[0].end == N_LINES
    assert any(r.kind == "clamp" for r in repairs)


def test_duplicate_section_names_are_renamed_never_dropped():
    """songs/*.md needs unique `## Section` headings, but dropping one would un-redact it.

    schemas/deck.schema.json: a deck's `sections` is an ordered list of headings
    "repeats and all", and every name must exist in the song file — so two `## Chorus`
    headings are ambiguous. They still have to stay, because `redact()` walks these
    same sections to decide what to delete from the email.
    """
    song = Song("s", "S", [
        Section("Chorus", 5, 7),
        Section("Verse 1", 9, 11),
        Section("Chorus", 13, 15),
        Section("Chorus", 17, 19),
    ])
    uniquify_section_names([song])
    names = [s.name for s in sorted(song.sections, key=lambda x: x.start)]
    assert names == ["Chorus", "Verse 1", "Chorus (2)", "Chorus (3)"]
    assert len(names) == len(set(names))
    assert claimed([song]) == set(range(5, 8)) | set(range(9, 12)) | set(range(13, 16)) | set(range(17, 20))
