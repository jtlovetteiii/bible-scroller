"""Consensus over N one-shot specs (bs-8qs).

NO NETWORK. Pure functions, like lyric_offsets.py.

WHY THIS EXISTS: a single call to the local model is not reliable. Three identical
think-off calls on the same email leaked 6, 4 and 0 lyric lines, and one run missed
a whole song. But with reasoning disabled a call costs ~6s, so N calls are
affordable, and the runs miss DIFFERENT lines — so unioning their claimed ranges
covers all of them.

Measured on the hostile fixture, 7 calls / 44s / 6 valid specs:

    threshold      claimed   prose destroyed   LYRICS LEAKED
    K>=1 .. K>=4      45            3                0
    K>=5              42            2                2
    K>=6              38            0                4

THE BIAS IS DELIBERATE. The two error directions are not symmetric:
  - over-claiming destroys a prose line -> visible to the minister in the reply,
    correctable, costs one email;
  - under-claiming leaks a lyric -> content-filter 400, the run dies, and it is the
    exact failure this whole design exists to prevent.
So default low (union-ish) and surface the over-claim rather than hiding it.

N and K are CONFIGURABLE ON PURPOSE. They are tuned to the model currently served
at home (a 1-bit quant). A stronger model should need fewer runs; do not bake these
numbers into code.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass

from lyric_offsets import Section, Song


@dataclass
class ConsensusReport:
    """What the vote decided, and how confident it was. Meant to be logged."""

    songs: list[Song]
    valid_specs: int
    total_specs: int
    #: line -> how many specs claimed it. The audit trail for a disputed line.
    votes: dict[int, int]
    #: Lines claimed by some specs but below the threshold — i.e. deliberately
    #: dropped. Worth logging: these are the near-misses.
    below_threshold: list[int]
    #: title -> vote count, per slug. Surfaces disagreement about what a song IS.
    title_votes: dict[str, dict[str, int]]


def _runs(sorted_lines: list[int]) -> list[tuple[int, int]]:
    """Collapse a sorted line list into contiguous (start, end) runs."""
    if not sorted_lines:
        return []
    out: list[tuple[int, int]] = []
    start = prev = sorted_lines[0]
    for n in sorted_lines[1:]:
        if n != prev + 1:
            out.append((start, prev))
            start = n
        prev = n
    out.append((start, prev))
    return out


def consensus(
    specs: list[list[Song]],
    *,
    line_threshold: int = 1,
    song_threshold: int = 1,
) -> ConsensusReport:
    """Merge N independently-produced specs into one.

    `line_threshold` — a line is treated as lyric if at least this many specs
    claimed it. 1 is the union: maximally safe against leakage, maximally likely to
    swallow a prose line.

    `song_threshold` — a song must be proposed by at least this many specs to
    survive. Guards against one run inventing a song the others did not see.
    """
    total = len(specs)

    # --- vote on lines, and remember which slug claimed each ------------------
    line_votes: collections.Counter[int] = collections.Counter()
    slug_votes: collections.Counter[str] = collections.Counter()
    lines_by_slug: dict[str, collections.Counter[int]] = collections.defaultdict(
        collections.Counter
    )
    titles_by_slug: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    # Section names keyed by the line they start on, so a merged run can be named
    # from whatever the specs actually called it rather than "Section 1".
    names_at: dict[str, dict[int, collections.Counter[str]]] = collections.defaultdict(
        lambda: collections.defaultdict(collections.Counter)
    )

    for spec in specs:
        seen_slugs = {s.slug for s in spec}
        for slug in seen_slugs:
            slug_votes[slug] += 1
        for song in spec:
            titles_by_slug[song.slug][song.title] += 1
            for sec in song.sections:
                names_at[song.slug][sec.start][sec.name] += 1
                for ln in range(sec.start, sec.end + 1):
                    line_votes[ln] += 1
                    lines_by_slug[song.slug][ln] += 1

    # --- build the surviving songs ------------------------------------------
    songs: list[Song] = []
    for slug, votes in slug_votes.items():
        if votes < song_threshold:
            continue
        claimed = sorted(
            ln for ln, c in lines_by_slug[slug].items() if c >= line_threshold
        )
        if not claimed:
            continue
        sections: list[Section] = []
        for i, (start, end) in enumerate(_runs(claimed), 1):
            named = names_at[slug].get(start)
            name = named.most_common(1)[0][0] if named else f"Section {i}"
            sections.append(Section(name=name, start=start, end=end))
        title = titles_by_slug[slug].most_common(1)[0][0]
        songs.append(Song(slug=slug, title=title, sections=sections))

    songs.sort(key=lambda s: s.first_line)

    below = sorted(ln for ln, c in line_votes.items() if 0 < c < line_threshold)
    return ConsensusReport(
        songs=songs,
        valid_specs=total,
        total_specs=total,
        votes=dict(line_votes),
        below_threshold=below,
        title_votes={k: dict(v) for k, v in titles_by_slug.items()},
    )
