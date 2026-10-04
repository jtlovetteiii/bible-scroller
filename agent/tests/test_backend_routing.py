"""The alternate-backend seam (bs-dox): AGENT_BASE_URL -> the CLI subprocess.

What actually matters here is not that the right keys are present, but that a
SUBSCRIPTION CREDENTIAL CANNOT REACH A THIRD-PARTY ENDPOINT. `ClaudeAgentOptions.env`
is merged over the inherited environment rather than replacing it, so a key we
merely omit keeps whatever the service already has — which for
CLAUDE_CODE_OAUTH_TOKEN would mean posting the user's subscription token to
someone else's box. Blanking is the only thing a merged dict can do about that,
so most of these tests are about the blanks rather than the values.
"""

from __future__ import annotations

import dataclasses

import pytest

from email_agent.config import Config, assert_agent_auth


def _config(**overrides) -> Config:
    return dataclasses.replace(Config(), **overrides)


PROXY = "http://192.168.0.48:9223"


# --- Default path: nothing changes ------------------------------------------


def test_no_base_url_means_no_env_overlay(monkeypatch):
    """The default path must stay byte-identical to what shipped.

    An empty overlay leaves the inherited environment alone, which is how the
    subscription auth keeps working without this feature knowing about it.
    """
    monkeypatch.delenv("AGENT_BASE_URL", raising=False)
    config = _config(agent_base_url=None)

    assert config.uses_alternate_backend is False
    assert config.agent_env() == {}


def test_base_url_read_from_environment(monkeypatch):
    monkeypatch.setenv("AGENT_BASE_URL", PROXY)
    monkeypatch.setenv("AGENT_AUTH_TOKEN", "sk-local-abc")

    config = Config()

    assert config.agent_base_url == PROXY
    assert config.agent_auth_token == "sk-local-abc"


def test_empty_env_vars_are_none_not_empty_string(monkeypatch):
    """`AGENT_BASE_URL=` in a .env must read as "unset", not as a base URL of "".

    An empty string is truthy enough to route on and would send the agent at a
    nonsense endpoint while looking configured.
    """
    monkeypatch.setenv("AGENT_BASE_URL", "")
    monkeypatch.setenv("AGENT_AUTH_TOKEN", "")

    config = Config()

    assert config.agent_base_url is None
    assert config.agent_auth_token is None
    assert config.uses_alternate_backend is False


# --- Alternate path: credentials must not leak ------------------------------


def test_subscription_token_is_blanked_for_alternate_backend():
    """The one that matters. Omitting this key would INHERIT the real token."""
    env = _config(agent_base_url=PROXY, agent_auth_token="sk-local-abc").agent_env()

    assert "CLAUDE_CODE_OAUTH_TOKEN" in env, "key must be present to override the inherited one"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == ""


def test_api_key_is_blanked_for_alternate_backend():
    """ANTHROPIC_API_KEY outranks ANTHROPIC_AUTH_TOKEN, so a stray one shadows us."""
    env = _config(agent_base_url=PROXY, agent_auth_token="sk-local-abc").agent_env()

    assert env["ANTHROPIC_API_KEY"] == ""


def test_auth_token_uses_auth_token_not_api_key():
    """Exactly one credential header. Setting both makes the client send both,
    which Anthropic-compatible servers reject."""
    env = _config(agent_base_url=PROXY, agent_auth_token="sk-local-abc").agent_env()

    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-local-abc"
    assert env["ANTHROPIC_API_KEY"] == ""


def test_base_url_is_passed_through():
    env = _config(agent_base_url=PROXY, agent_auth_token=None).agent_env()

    assert env["ANTHROPIC_BASE_URL"] == PROXY


def test_no_auth_token_still_blanks_inherited_credentials():
    """A tokenless LAN proxy is a legitimate config — and the case where a leaked
    subscription token would be easiest to miss, since nothing else is set."""
    env = _config(agent_base_url=PROXY, agent_auth_token=None).agent_env()

    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == ""
    assert env["ANTHROPIC_API_KEY"] == ""


# --- The auth guard ---------------------------------------------------------


def test_guard_still_fires_on_the_default_path(monkeypatch):
    """The spec §4.6 billing foot-gun must survive this change untouched."""
    monkeypatch.delenv("AGENT_BASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-oops")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    import email_agent.config as cfg

    monkeypatch.setattr(cfg, "config", _config(agent_base_url=None))

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        assert_agent_auth()


def test_guard_requires_oauth_token_on_the_default_path(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    import email_agent.config as cfg

    monkeypatch.setattr(cfg, "config", _config(agent_base_url=None))

    with pytest.raises(RuntimeError, match="CLAUDE_CODE_OAUTH_TOKEN"):
        assert_agent_auth()


def test_guard_does_not_fire_for_alternate_backend(monkeypatch):
    """The billing foot-gun is a statement about Anthropic's billing. Nothing is
    billed to the subscription when the run never reaches Anthropic, and
    agent_env() blanks the key in the child regardless."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-irrelevant")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    import email_agent.config as cfg

    monkeypatch.setattr(cfg, "config", _config(agent_base_url=PROXY))

    assert_agent_auth()  # must not raise
