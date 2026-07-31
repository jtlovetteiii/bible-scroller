"""Single-call offsets formulation of the lyric intermediary (bs-8qs).

ONE HTTP call to the proxy. No Agent SDK, no tools, no agentic loop. The model
returns a JSON spec of line ranges; lyric_offsets.py does everything else.

This is the LAST rescue attempt for the Bonsai-as-intermediary design. Per the
falsification condition recorded on bs-8qs: if this leaks lyrics, or mis-titles a
song whose title is present in the email, the design should be abandoned rather
than patched again.

Run from agent/:
  uv run python -u tests/probes/probe_offsets.py --model bonsai
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lyric_offsets import (  # noqa: E402
    SpecError,
    build_prompt,
    parse_spec,
    redact,
    render_song,
    validate_spec,
)
from probe_intermediary import DECOYS, PROSE, build_email  # noqa: E402

PROXY_URL = os.getenv("FALLBACK_API_BASE_URL", "http://192.168.0.48:9223")


#: Bonsai spends most of its budget on reasoning tokens the proxy does not surface.
#: At max_tokens=4000 it returned stop_reason=max_tokens with an EMPTY text block —
#: it never reached an answer. 16000 leaves room to think and still reply (measured:
#: 5969 output tokens for a 273-character answer, i.e. ~95% invisible reasoning).
DEFAULT_MAX_TOKENS = 16000


def call_model(model: str, prompt: str, timeout: float, max_tokens: int) -> tuple[str, dict]:
    r = httpx.post(
        f"{PROXY_URL.rstrip('/')}/v1/messages",
        headers={"content-type": "application/json", "anthropic-version": "2023-06-01"},
        json={
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return text, data.get("usage", {})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="bonsai")
    ap.add_argument("--timeout", type=float, default=1800.0)
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    args = ap.parse_args()

    email_text, all_lyrics = build_email()
    work = Path(tempfile.mkdtemp(prefix="offsets-"))
    (work / "songs").mkdir()
    (work / "email.txt").write_text(email_text)

    print("=" * 72)
    print(f"MODEL: {args.model}   WORK: {work}")
    print(f"email: {len(email_text.splitlines())} lines, {len(all_lyrics)} of them lyrics")
    print("=" * 72)

    prompt = build_prompt(email_text)
    t0 = time.monotonic()
    try:
        raw, usage = call_model(args.model, prompt, args.timeout, args.max_tokens)
    except Exception as exc:  # noqa: BLE001
        print(f"CALL FAILED: {type(exc).__name__}: {str(exc)[:300]}")
        return 1
    elapsed = time.monotonic() - t0

    out_tok = usage.get("output_tokens", 0)
    print(f"elapsed        : {elapsed:.1f}s")
    print(f"output tokens  : {out_tok}  (~{out_tok / elapsed:.0f} tok/s)")
    print(f"raw reply      : {raw.strip()[:400]}")
    print("-" * 72)

    fails: list[str] = []

    try:
        songs = parse_spec(raw)
        validate_spec(songs, email_text)
    except SpecError as exc:
        print(f"SPEC REJECTED  : {exc}")
        print("=" * 72)
        print("VERDICT: FAIL (spec unusable — but note it failed CLOSED)")
        return 0

    print(f"songs in spec  : {[(s.slug, [x.name for x in s.sections]) for s in songs]}")

    for song in songs:
        (work / "songs" / f"{song.slug}.md").write_text(render_song(song, email_text))
    redacted = redact(songs, email_text)
    (work / "redacted.txt").write_text(redacted)

    # --- CHECK 1: under-redaction ----------------------------------------
    leaked = [l for l in all_lyrics if l in redacted]
    print(f"CHECK 1 under-redaction : {len(leaked)} lyric line(s) leaked")
    for l in leaked[:5]:
        print(f"    LEAKED: {l!r}")
    if leaked:
        fails.append(f"{len(leaked)} lyric lines survived redaction")

    # --- CHECK 2: over-redaction -----------------------------------------
    lost = [p for p in PROSE + DECOYS if p not in redacted]
    print(f"CHECK 2 over-redaction  : {len(lost)} prose line(s) lost")
    for p in lost[:5]:
        print(f"    LOST: {p!r}")
    if lost:
        fails.append(f"{len(lost)} prose lines destroyed")

    # --- CHECK 3: hallucination ------------------------------------------
    # Structural, not statistical: every lyric byte came from a slice.
    src_lines = set(email_text.splitlines())
    total, bad = 0, []
    for f in sorted((work / "songs").glob("*.md")):
        body = f.read_text().split("---", 2)[-1]
        for ln in body.splitlines():
            if not ln.strip() or ln.startswith("##"):
                continue
            total += 1
            if ln not in src_lines:
                bad.append((f.name, ln))
    print(f"CHECK 3 library lines   : {total} written, {len(bad)} not verbatim from email")
    for n, s in bad[:5]:
        print(f"    NOT VERBATIM in {n}: {s!r}")
    if bad:
        fails.append(f"{len(bad)} library lines not verbatim")

    # --- CHECK 4: no fabrication for a title-only song --------------------
    fabricated = [s.slug for s in songs if "elijah" in s.slug.lower()]
    print(f"CHECK 4 title-only song : {'FABRICATED ' + str(fabricated) if fabricated else 'correctly skipped'}")
    if fabricated:
        fails.append("fabricated a song mentioned by name only")

    # --- CHECK 5: title fidelity -----------------------------------------
    # "Revelation Song" appears in the email on its own line, so there is no excuse
    # for missing it. Song 1 has NO title in the email; any sensible fallback is ok.
    titles = [s.title.strip().lower() for s in songs]
    got_rev = any("revelation" in t for t in titles)
    print(f"CHECK 5 title fidelity  : titles={[s.title for s in songs]}")
    print(f"        'Revelation Song' identified: {got_rev}")
    if not got_rev:
        fails.append("missed 'Revelation Song' despite the title being in the email")

    # --- CHECK 6: caesura survival ---------------------------------------
    src_caesura = sum(1 for l in all_lyrics if "|" in l)
    got_caesura = sum(
        1
        for f in (work / "songs").glob("*.md")
        for l in f.read_text().splitlines()
        if "|" in l and not l.startswith("#")
    )
    print(f"CHECK 6 caesuras        : {got_caesura}/{src_caesura} preserved")
    if got_caesura != src_caesura:
        fails.append(f"caesura loss: {got_caesura}/{src_caesura}")

    print("=" * 72)
    print("VERDICT: PASS" if not fails else "VERDICT: FAIL")
    for f in fails:
        print(f"  - {f}")
    print(f"artifacts: {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
