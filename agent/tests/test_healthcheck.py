"""Unit tests for healthcheck's AWS check (bs-sjz).

Both AWS clients are injected, so nothing here touches real AWS. The check's
whole reason to exist is that the WRONG identity still WORKS — root can write to
the bucket happily — so most of these tests are about refusing to pass on a
credential that functions.
"""

from __future__ import annotations

import pytest

from email_agent.config import config
from email_agent.healthcheck import AGENT_ARN_SUFFIX, PROBE_KEY, check_aws

AGENT_ARN = "arn:aws:iam::123456789012:user/cbc-wilm-agent"
ROOT_ARN = "arn:aws:iam::123456789012:root"


class FakeSTS:
    def __init__(self, arn: str | None = AGENT_ARN, error: Exception | None = None):
        self._arn = arn
        self._error = error
        self.calls = 0

    def get_caller_identity(self):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return {"Arn": self._arn, "Account": "123456789012", "UserId": "AIDAFAKE"}


class _Body:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeS3:
    """Stands in for boto3's S3 client; stores objects in a dict."""

    def __init__(
        self,
        put_error: Exception | None = None,
        get_error: Exception | None = None,
        corrupt: bool = False,
    ):
        self.objects: dict[str, bytes] = {}
        self.puts: list[dict] = []
        self._put_error = put_error
        self._get_error = get_error
        self._corrupt = corrupt

    def put_object(self, **kwargs):
        if self._put_error is not None:
            raise self._put_error
        self.puts.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {"ETag": '"fake"'}

    def get_object(self, **kwargs):
        if self._get_error is not None:
            raise self._get_error
        data = self.objects[kwargs["Key"]]
        return {"Body": _Body(b"something else" if self._corrupt else data)}

    def delete_object(self, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError(
            "the agent user cannot DeleteObject by design (bs-crp); the probe "
            "must overwrite a fixed key, not clean up after itself"
        )


# --- identity --------------------------------------------------------------


def test_correct_identity_passes(capsys):
    failures = check_aws(sts=FakeSTS(), s3=FakeS3())

    assert failures == []
    out = capsys.readouterr().out
    assert "OK    aws: authenticated as" in out
    assert AGENT_ARN in out


def test_root_identity_fails(capsys):
    """Root CAN write to the bucket. That is exactly why it must not pass."""
    s3 = FakeS3()
    failures = check_aws(sts=FakeSTS(arn=ROOT_ARN), s3=s3)

    assert len(failures) == 1
    assert AGENT_ARN_SUFFIX in failures[0], "the message must name what was expected"
    assert ROOT_ARN in failures[0], "the message must name what was actually found"
    assert s3.puts == [], "a wrong identity must never be probed against the bucket"
    assert "FAIL" in capsys.readouterr().out


def test_wrong_user_fails_naming_expected_and_actual(capsys):
    other = "arn:aws:iam::999999999999:user/thomas-personal"
    failures = check_aws(sts=FakeSTS(arn=other), s3=FakeS3())

    assert len(failures) == 1
    out = capsys.readouterr().out
    assert AGENT_ARN_SUFFIX in out
    assert other in out
    # The foot-gun is the credential chain, so the remedy must be on screen.
    assert "AWS_PROFILE" in out


def test_assumed_role_that_merely_contains_the_name_fails():
    """Suffix match, not substring: a role whose path mentions the agent is not the agent."""
    sneaky = "arn:aws:sts::123456789012:assumed-role/cbc-wilm-agent/session"
    failures = check_aws(sts=FakeSTS(arn=sneaky), s3=FakeS3())
    assert len(failures) == 1


def test_missing_credentials_fail(capsys):
    failures = check_aws(sts=FakeSTS(error=RuntimeError("Unable to locate credentials")), s3=FakeS3())

    assert len(failures) == 1
    assert "GetCallerIdentity" in failures[0]
    assert "Unable to locate credentials" in failures[0]
    assert "FAIL" in capsys.readouterr().out


# --- Put / Get probe -------------------------------------------------------


def test_probe_puts_and_gets_the_fixed_key():
    s3 = FakeS3()
    assert check_aws(sts=FakeSTS(), s3=s3) == []

    assert len(s3.puts) == 1
    put = s3.puts[0]
    assert put["Bucket"] == config.deck_bucket
    assert put["Key"] == PROBE_KEY


def test_probe_overwrites_one_fixed_key_across_runs():
    """The agent cannot DeleteObject (bs-crp), so the probe must not accumulate objects."""
    s3 = FakeS3()
    for _ in range(3):
        assert check_aws(sts=FakeSTS(), s3=s3) == []

    assert list(s3.objects) == [PROBE_KEY], "repeated runs must leave exactly one object"


def test_put_failure_fails(capsys):
    s3 = FakeS3(put_error=RuntimeError("AccessDenied"))
    failures = check_aws(sts=FakeSTS(), s3=s3)

    assert len(failures) == 1
    assert "PutObject" in failures[0]
    assert "AccessDenied" in failures[0]
    out = capsys.readouterr().out
    assert "FAIL  aws: cannot write" in out
    # An authenticated key without the publisher policy is the exact scenario.
    assert "publisher policy" in out


def test_get_failure_fails(capsys):
    s3 = FakeS3(get_error=RuntimeError("AccessDenied"))
    failures = check_aws(sts=FakeSTS(), s3=s3)

    assert len(failures) == 1
    assert "GetObject" in failures[0]
    assert "FAIL  aws: cannot read back" in capsys.readouterr().out


def test_read_back_mismatch_fails():
    failures = check_aws(sts=FakeSTS(), s3=FakeS3(corrupt=True))

    assert len(failures) == 1
    assert "mismatch" in failures[0]


# --- the dead token-age check is gone (bs-qka) ------------------------------


def test_no_token_age_check_remains():
    """The 7-day tell measured token.json's mtime, which gmail_client rewrites
    hourly, so the >=7 branch was unreachable. It was a proxy for "is the OAuth
    app published", which bs-xy9 answered directly; token death is caught by the
    live getProfile call instead."""
    import email_agent.healthcheck as hc

    assert not hasattr(hc, "_token_age_days")
