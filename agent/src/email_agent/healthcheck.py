"""Preflight: is the agent actually able to run right now?

    cd agent && uv run python -m email_agent.healthcheck

Exists because every credential this agent holds fails **silently and on a
delay** — nothing surfaces until the agent is mid-run, which in practice means
fifteen minutes before a service:

  * A Gmail refresh token dies with `invalid_grant`. Nothing announces it; the
    next poll simply stops working. Only a live API call can tell you.
  * `ANTHROPIC_API_KEY` appearing in the environment silently outranks
    `CLAUDE_CODE_OAUTH_TOKEN` and bills a pay-per-token account instead of the
    subscription.
  * The AWS SDK's credential chain puts environment variables ABOVE
    `~/.aws/credentials`, so a stray `AWS_PROFILE` or `AWS_ACCESS_KEY_ID` in the
    host environment publishes decks to the wrong account — or, worse, succeeds
    as an over-privileged identity like root, which works and therefore hides
    the misconfiguration until the day it doesn't.

Run this on a schedule so it fails on a Tuesday, not on a Saturday night with
the deck already built.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from typing import Any

from .config import config, assert_agent_auth
from .gmail_client import gmail_service

#: The ONLY identity allowed to publish. Root or a personal profile is a FAIL,
#: not a pass: both can write to the bucket, which is exactly why they mask a
#: broken credential chain instead of exposing it.
AGENT_ARN_SUFFIX = ":user/cbc-wilm-agent"

#: One fixed key, overwritten on every run. The agent user has ListBucket /
#: GetObject / PutObject and deliberately NOT DeleteObject (bs-crp), so the
#: probe object cannot clean itself up — overwrite is allowed and proven, and
#: adding Delete to the policy just to tidy up would widen it for no reason.
PROBE_KEY = "_policy-probe/healthcheck.txt"


def _check_alternate_backend() -> list[str]:
    """Print OK/FAIL for AGENT_BASE_URL; return failure strings (empty == healthy).

    Deliberately probes `/v1/models` rather than sending a completion: it is cheap,
    needs no token budget, and still proves the three things that actually break —
    the host is up, it is reachable from *this* box, and it is speaking Anthropic's
    API shape rather than an OpenAI one (bs-dox's blocking question).

    A 401/403 counts as reachable: the endpoint answered, the credential is the
    problem, and saying so is more useful than a bare "unreachable".
    """
    import urllib.error
    import urllib.request

    base = (config.agent_base_url or "").rstrip("/")
    url = f"{base}/v1/models"
    req = urllib.request.Request(url, method="GET")
    req.add_header("anthropic-version", "2023-06-01")
    if config.agent_auth_token:
        req.add_header("Authorization", f"Bearer {config.agent_auth_token}")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"OK    claude: {base} reachable (HTTP {resp.status}), model {config.agent_model}")
            return []
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            msg = f"{base} answered HTTP {exc.code} — reachable, but rejected the credential"
            print(f"FAIL  claude: {msg}")
            return [f"claude: {msg}"]
        # Anything else that produced a response still proves reachability, which
        # is what this check is for. /v1/models is optional in a proxy.
        print(f"OK    claude: {base} reachable (HTTP {exc.code}), model {config.agent_model}")
        return []
    except (urllib.error.URLError, OSError, ValueError) as exc:
        msg = f"{base} unreachable: {type(exc).__name__}: {exc}"
        print(f"FAIL  claude: {msg}")
        return [f"claude: {msg}"]


def _aws_clients(sts: Any | None = None, s3: Any | None = None) -> tuple[Any, Any]:
    """boto3 is imported locally, as in publish.py: keeps it off the test import path."""
    if sts is not None and s3 is not None:
        return sts, s3
    import boto3

    return sts or boto3.client("sts"), s3 or boto3.client("s3")


def check_aws(*, sts: Any | None = None, s3: Any | None = None) -> list[str]:
    """Print OK/FAIL lines for AWS; return a list of failure strings (empty == healthy)."""
    failures: list[str] = []

    try:
        sts_client, s3_client = _aws_clients(sts, s3)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"aws: cannot build clients: {type(exc).__name__}: {exc}")
        print(f"FAIL  aws: cannot build clients: {type(exc).__name__}: {exc}")
        return failures

    # --- Identity: WHO are we, really? ---
    try:
        arn = sts_client.get_caller_identity()["Arn"]
    except Exception as exc:  # noqa: BLE001
        failures.append(f"aws: sts:GetCallerIdentity failed: {type(exc).__name__}: {exc}")
        print(f"FAIL  aws: sts:GetCallerIdentity failed: {type(exc).__name__}: {exc}")
        print("      -> no usable AWS credentials; publishing will fail mid-run")
        return failures

    if not arn.endswith(AGENT_ARN_SUFFIX):
        failures.append(f"aws: wrong identity — expected *{AGENT_ARN_SUFFIX}, got {arn}")
        print("FAIL  aws: wrong identity")
        print(f"      -> expected an Arn ending in {AGENT_ARN_SUFFIX}")
        print(f"      -> actual   {arn}")
        print("      -> env vars outrank ~/.aws/credentials: check AWS_PROFILE /")
        print("         AWS_ACCESS_KEY_ID. Publishing as this identity may WORK and")
        print("         still be wrong.")
        return failures

    print(f"OK    aws: authenticated as {arn}")

    # --- Publisher policy: prove Put and Get against the real bucket ---
    body = f"healthcheck {dt.datetime.now().isoformat()}\n".encode()
    try:
        s3_client.put_object(
            Bucket=config.deck_bucket,
            Key=PROBE_KEY,
            Body=body,
            ContentType="text/plain; charset=utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        failures.append(
            f"aws: PutObject s3://{config.deck_bucket}/{PROBE_KEY} failed: "
            f"{type(exc).__name__}: {exc}"
        )
        print(f"FAIL  aws: cannot write to s3://{config.deck_bucket}/{PROBE_KEY}")
        print(f"      -> {type(exc).__name__}: {exc}")
        print("      -> the key authenticates but lacks the publisher policy")
        return failures

    try:
        got = s3_client.get_object(Bucket=config.deck_bucket, Key=PROBE_KEY)["Body"].read()
    except Exception as exc:  # noqa: BLE001
        failures.append(
            f"aws: GetObject s3://{config.deck_bucket}/{PROBE_KEY} failed: "
            f"{type(exc).__name__}: {exc}"
        )
        print(f"FAIL  aws: cannot read back s3://{config.deck_bucket}/{PROBE_KEY}")
        print(f"      -> {type(exc).__name__}: {exc}")
        return failures

    if got != body:
        failures.append(
            f"aws: probe read-back mismatch at s3://{config.deck_bucket}/{PROBE_KEY}"
        )
        print("FAIL  aws: probe read-back does not match what was written")
        return failures

    print(f"OK    aws: Put+Get verified on s3://{config.deck_bucket}/{PROBE_KEY}")
    # The probe object stays: the agent cannot DeleteObject by design (bs-crp).
    # The next run overwrites this same key.
    return failures


def main() -> int:
    failures: list[str] = []

    # --- Claude auth ---
    try:
        assert_agent_auth()
        if config.uses_alternate_backend:
            # Credentials are not the interesting failure for a self-hosted
            # endpoint — reachability is, and it fails exactly the way this whole
            # module exists to catch: silently, mid-run, on a Saturday.
            failures.extend(_check_alternate_backend())
        else:
            print("OK    claude: CLAUDE_CODE_OAUTH_TOKEN set, ANTHROPIC_API_KEY unset")
    except RuntimeError as exc:
        failures.append(f"claude: {exc}")
        print(f"FAIL  claude: {exc}")

    # --- Gmail auth: a live call, not just a file read ---
    try:
        profile = gmail_service().users().getProfile(userId="me").execute()
        print(f"OK    gmail: authenticated as {profile['emailAddress']}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"gmail: {type(exc).__name__}: {exc}")
        print(f"FAIL  gmail: {type(exc).__name__}: {exc}")
        print("      -> re-run: uv run python -m email_agent.authorize")

    # --- Send scope: without it the whole reply loop is dead ---
    try:
        scopes = json.loads(config.gmail_token_path.read_text()).get("scopes", [])
        can_send = any(
            s.endswith(("gmail.send", "gmail.modify")) or s == "https://mail.google.com/"
            for s in scopes
        )
        print(f"{'OK   ' if can_send else 'FAIL '} gmail: send scope {'present' if can_send else 'MISSING'}")
        if not can_send:
            failures.append("gmail: token lacks send scope; send_reply cannot work")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"gmail scopes unreadable: {exc}")

    # --- AWS: right identity, and a key that can actually publish ---
    failures.extend(check_aws())

    print()
    if failures:
        print(f"UNHEALTHY — {len(failures)} problem(s). The agent will NOT work.")
        return 1
    print("HEALTHY — the agent can read mail, send mail, reach Claude, and publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
