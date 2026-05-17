import pytest

from ai_intel.llm import get_anthropic_client


def test_client_uses_env_token(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-oat-test")
    client = get_anthropic_client()
    assert client is not None


def test_client_raises_when_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        get_anthropic_client()
