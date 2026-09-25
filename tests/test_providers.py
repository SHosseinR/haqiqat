import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from haqiqat.budget import cost_usd
from haqiqat.config import Price, ProviderConfig, load_config
from haqiqat.providers.base import ChatRequest, ProviderError, parse_json
from haqiqat.providers.openai_compat import OpenAICompatChat, OpenAICompatEmbeddings
from haqiqat.sources import RegistryError, load_registry
from haqiqat.synthesize import OUTPUT_SCHEMA

REPO = Path(__file__).resolve().parent.parent


def req(**kw):
    base = dict(system="sys", user="usr", schema=OUTPUT_SCHEMA, schema_name="story",
                model="m", max_tokens=100)
    return ChatRequest(**{**base, **kw})


def test_openai_compat_chat_request_and_usage(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "k")
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={
            "model": "m-2026",
            "choices": [{"message": {"content": '```json\n{"a": 1}\n```'},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                      "prompt_tokens_details": {"cached_tokens": 60}},
        })

    chat = OpenAICompatChat(ProviderConfig(kind="openai_compat", base_url="https://x.test/v1",
                                           api_key_env="TEST_KEY"))
    chat.http = httpx.Client(base_url="https://x.test/v1", headers=chat.http.headers,
                             transport=httpx.MockTransport(handler))
    res = chat.complete_json(req())
    assert res.data == {"a": 1}
    assert (res.input_tokens, res.cache_read_tokens, res.output_tokens) == (40, 60, 20)
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["response_format"]["json_schema"]["strict"] is True
    assert seen["body"]["max_tokens"] == 100


def test_openai_compat_embeddings_order():
    def handler(request):
        return httpx.Response(200, json={
            "data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}],
            "usage": {"prompt_tokens": 7},
        })

    emb = OpenAICompatEmbeddings(ProviderConfig(kind="openai_compat", base_url="https://x.test"))
    emb.http = httpx.Client(base_url="https://x.test", transport=httpx.MockTransport(handler))
    res = emb.embed(["a", "b"], "m")
    assert res.vectors.tolist() == [[1, 0], [0, 1]] and res.tokens == 7


def test_truncated_output_is_an_error():
    def handler(request):
        return httpx.Response(200, json={"choices": [
            {"message": {"content": "{"}, "finish_reason": "length"}]})

    chat = OpenAICompatChat(ProviderConfig(kind="openai_compat", base_url="https://x.test"))
    chat.http = httpx.Client(base_url="https://x.test", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        chat.complete_json(req())


def test_claude_request_shape(monkeypatch):
    pytest.importorskip("anthropic")
    from haqiqat.providers.claude import FALLBACK_BETA, ClaudeChat

    monkeypatch.setenv("ANTHROPIC_TEST_KEY", "k")
    chat = ClaudeChat(ProviderConfig(kind="anthropic", api_key_env="ANTHROPIC_TEST_KEY",
                                     fallbacks="default"))
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            model="claude-opus-5", stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text='{"ok": true}')],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=90,
                                  cache_creation_input_tokens=0),
        )

    chat.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    res = chat.complete_json(req(effort="medium"))
    assert res.data == {"ok": True} and res.cache_read_tokens == 90
    assert captured["betas"] == [FALLBACK_BETA] and captured["fallbacks"] == "default"
    assert captured["output_config"] == {
        "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}, "effort": "medium"}
    assert captured["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_claude_refusal_raises(monkeypatch):
    pytest.importorskip("anthropic")
    from haqiqat.providers.claude import ClaudeChat

    monkeypatch.setenv("ANTHROPIC_TEST_KEY", "k")
    chat = ClaudeChat(ProviderConfig(kind="anthropic", api_key_env="ANTHROPIC_TEST_KEY"))
    resp = SimpleNamespace(model="m", stop_reason="refusal", content=[],
                           stop_details=SimpleNamespace(category=None),
                           usage=SimpleNamespace(input_tokens=1, output_tokens=0))
    chat.client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: resp))
    with pytest.raises(ProviderError, match="refusal"):
        chat.complete_json(req())


def test_parse_json_tolerates_prose():
    assert parse_json('Here you go: {"x": 2} thanks') == {"x": 2}
    with pytest.raises(ProviderError):
        parse_json("no json here")


def test_cost_accounting_uses_cache_prices():
    cfg = load_config(REPO / "config" / "config.example.yaml")
    cfg.pricing["m"] = Price(input=10, output=20, cache_read=1)
    assert cost_usd(cfg, "m", input_tokens=1_000_000, output_tokens=1_000_000,
                    cache_read_tokens=1_000_000) == pytest.approx(31)
    # Unknown models are charged at the conservative default, never free.
    assert cost_usd(cfg, "unknown-model", input_tokens=1_000_000) == pytest.approx(5)


def test_repository_registry_is_valid():
    reg = load_registry(REPO / "sources", REPO / "config" / "lenses.yaml")
    assert len(reg.sources) >= 60
    groups = {s.independence_group for s in reg.sources.values()}
    assert "srmg" in groups  # Arab News and Independent Persian share an owner
    same_owner = {reg.get("arab-news").independence_group,
                  reg.get("independent-persian").independence_group}
    assert same_owner == {"srmg"}


def test_registry_rejects_unknown_lens(tmp_path):
    (tmp_path / "bad.yaml").write_text(
        "id: bad\nname: {en: Bad}\nhomepage: https://b.test\nlanguages: [en]\ncountry: US\n"
        "type: online\nownership: {kind: private}\nindependence_group: bad\n"
        "lenses: {origin: nowhere}\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="unknown position"):
        load_registry(tmp_path, REPO / "config" / "lenses.yaml")
