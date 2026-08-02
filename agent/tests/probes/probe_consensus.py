"""N one-shot calls to the local model, merged by consensus (bs-8qs).

Goes DIRECT to llama.cpp, not through UniClaudeProxy — the proxy drops
chat_template_kwargs (so reasoning cannot be disabled) and drops llama.cpp's
separate reasoning_content field (so a truncated call looks like an empty answer).
See specs/lyric-ingestion.md §4.

Run from agent/:
  uv run python -u tests/probes/probe_consensus.py
  uv run python -u tests/probes/probe_consensus.py -n 5 -k 1 --sweep
  LOCAL_LLM_BASE_URL=http://host:8080 uv run python -u tests/probes/probe_consensus.py
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lyric_consensus import consensus  # noqa: E402
from lyric_offsets import (  # noqa: E402
    SpecError,
    build_prompt,
    parse_spec,
    redact,
    render_song,
    validate_spec,
)
from probe_intermediary import DECOYS, PROSE, build_email  # noqa: E402

#: Volatile. Tailnet address survives Thomas being away from the LAN; the
#: 192.168.x address does not. Never hardcode either into production.
BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://100.66.185.49:8080")
MODEL = os.getenv("LOCAL_LLM_MODEL", "Bonsai-27B-Q1_0.gguf")


def one_shot(prompt: str, *, timeout: float = 600.0) -> tuple[str, int]:
    """One call, reasoning DISABLED. Returns (text, completion_tokens).

    enable_thinking=False is the only knob that works: it takes the real task from
    159s/7111 tokens to ~6s/~250. reasoning_budget, reasoning_effort and an
    Anthropic-style thinking block all measured as no-ops.
    """
    r = httpx.post(
        f"{BASE_URL.rstrip('/')}/v1/chat/completions",
        json={
            "model": MODEL,
            "max_tokens": 16000,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout,
    )
    r.raise_for_status()
    d = r.json()
    choice = d["choices"][0]
    msg = choice["message"]
    # A truncated reply is an ERROR, never "no lyrics found" — failing open here
    # would silently disable the whole protection.
    if choice.get("finish_reason") == "length":
        raise RuntimeError("local model hit max_tokens; treat as failure, not as empty")
    return (msg.get("content") or ""), d.get("usage", {}).get("completion_tokens", 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=7)
    ap.add_argument("-k", "--line-threshold", type=int, default=1)
    ap.add_argument("--song-threshold", type=int, default=1)
    ap.add_argument("--sweep", action="store_true", help="report every K, not just -k")
    args = ap.parse_args()

    email_text, all_lyrics = build_email()
    prompt = build_prompt(email_text)
    lines = email_text.splitlines()

    print("=" * 72)
    print(f"{BASE_URL}  model={MODEL}")
    print(f"N={args.runs}  K={args.line_threshold}  email={len(lines)} lines")
    print("=" * 72)

    specs: list[list[Song]] = []  # noqa: F821 — Song imported transitively
    t0 = time.monotonic()
    for i in range(args.runs):
        try:
            raw, tok = one_shot(prompt)
            spec = parse_spec(raw)
            validate_spec(spec, email_text)
            specs.append(spec)
            print(f"  run {i + 1}: ok   tok={tok:5}  songs={[s.slug for s in spec]}")
        except (SpecError, RuntimeError, httpx.HTTPError) as exc:
            print(f"  run {i + 1}: REJECTED  {type(exc).__name__}: {str(exc)[:80]}")
    elapsed = time.monotonic() - t0
    print(f"\n{args.runs} calls in {elapsed:.1f}s ({elapsed / args.runs:.1f}s each), "
          f"{len(specs)} valid")

    if not specs:
        print("VERDICT: FAIL — no usable spec. Fail CLOSED; do not proceed unredacted.")
        return 0

    # Ground truth, for scoring only. Production has none of this.
    lyric_set = set(all_lyrics)
    truth = {i for i, l in enumerate(lines, 1) if l.strip() in lyric_set}
    mixed = {
        i for i, l in enumerate(lines, 1)
        if any(x in l for x in lyric_set) and i not in truth
    }

    ks = range(1, len(specs) + 1) if args.sweep else [args.line_threshold]
    for k in ks:
        rep = consensus(specs, line_threshold=k, song_threshold=args.song_threshold)
        claimed = {i for s in rep.songs for sec in s.sections
                   for i in range(sec.start, sec.end + 1)}
        red = redact(rep.songs, email_text)
        leaked = [l for l in all_lyrics if l in red]
        lost = [p for p in PROSE + DECOYS if p not in red]
        src = set(lines)
        tot = bad = 0
        for s in rep.songs:
            for ln in render_song(s, email_text).split("---", 2)[-1].splitlines():
                if ln.strip() and not ln.startswith("##"):
                    tot += 1
                    bad += ln not in src
        caes = sum(
            1 for s in rep.songs
            for ln in render_song(s, email_text).splitlines()
            if "|" in ln and not ln.startswith("#")
        )
        print(
            f"  K>={k}: claimed={len(claimed):3} "
            f"prose_destroyed={len(claimed - truth - mixed):2} "
            f"leaked={len(leaked):2} lost_prose={len(lost)} "
            f"verbatim={tot - bad}/{tot} caesura={caes}/3 "
            f"titles={[s.title for s in rep.songs]}"
        )

    rep = consensus(specs, line_threshold=args.line_threshold,
                    song_threshold=args.song_threshold)
    print(f"\ntitle votes: {rep.title_votes}")
    if rep.below_threshold:
        print(f"dropped below threshold (near-misses): {rep.below_threshold}")
    return 0


if __name__ == "__main__":
    from lyric_offsets import Song  # noqa: F401,E402  — for the annotation above

    sys.exit(main())
