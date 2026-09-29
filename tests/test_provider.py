"""Provider unit tests: mock is the default; Gemini is opt-in via env."""
import os

import pytest

from src.agents.graph import build_default_graph
from src.llm import provider


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


def test_unconfigured_by_default():
    assert not provider.is_configured()
    assert provider.model_name() == "mock"
    assert provider.get_api_key() == ""


def test_generate_falls_back_to_mock_without_key():
    ans, model = provider.generate_answer("explain", "q?", ["ctx"], lambda: "MOCK!")
    assert (ans, model) == ("MOCK!", "mock")


def test_embed_returns_none_without_key():
    assert provider.embed_texts(["hello"]) is None


def test_default_graph_is_mock_without_key():
    g = build_default_graph()
    st = g.run("What is OSPF?")
    assert st.model == "mock"
    assert st.answer  # mock template still responds


def test_env_alias_google_api_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    assert provider.is_configured()
    assert provider.model_name() == provider.GEN_MODEL
