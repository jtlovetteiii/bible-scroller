"""Keeping copyrighted lyric text out of a cloud model's context.

The deterministic half of the design in `specs/lyric-ingestion.md` (`bs-8qs`): a local
model contributes only LINE NUMBERS and titles, and everything that touches a lyric
byte happens here, in pure functions with no network.

`offsets` numbers the email, builds the prompt, parses/validates/repairs the model's
spec, slices `songs/*.md` out of it and redacts the same ranges from the email.
`consensus` merges N independently-produced specs into one.

Promoted out of `agent/tests/probes/` on 2026-08-02 (`bs-2pn`) once they had been made
to work against the real 2026-07-26 email rather than the synthetic fixture. Pinned by
`tests/test_lyric_repair.py` and `tests/test_lyric_pipeline.py`.
"""

from .consensus import ConsensusReport, consensus, slugify, title_key
from .offsets import (
    REFERENCE_TMPL,
    Repair,
    Section,
    Song,
    SpecError,
    build_prompt,
    number_lines,
    parse_spec,
    redact,
    render_song,
    repair_spec,
    uniquify_section_names,
    validate_spec,
)

__all__ = [
    "ConsensusReport", "REFERENCE_TMPL", "Repair", "Section", "Song", "SpecError",
    "build_prompt", "consensus", "number_lines", "parse_spec", "redact", "render_song",
    "repair_spec", "slugify", "title_key", "uniquify_section_names", "validate_spec",
]
