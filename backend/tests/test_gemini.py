import json

import httpx
import pytest

from app.config import Settings
from app.provider import Provider, ProviderError

BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_gemini_trailing_slash_bearer_and_unindexed_vectors():
    settings = Settings(embedding_url=BASE, embedding_model="gemini-embedding-001", embedding_key="isolated-test-key")
    requests = []
    def handler(request):
        requests.append(request)
        assert str(request.url) == BASE + "embeddings"
        assert request.headers["authorization"] == "Bearer isolated-test-key"
        body = json.loads(request.content)
        assert body["encoding_format"] == "float" and len(body["input"]) == 1
        return httpx.Response(200, json={"data": [{"object": "embedding", "embedding": [1.0] + [0.0] * 3071}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        vectors = Provider(settings, client).embed(["first source chunk", "second source chunk"])
    assert len(requests) == 2 and len(vectors) == 2 and len(vectors[0]) == 3072
    assert json.loads(requests[0].content)["input"] == ["first source chunk"]
    assert json.loads(requests[1].content)["input"] == ["second source chunk"]


@pytest.mark.parametrize("dimension", [3, 768, 1536])
def test_gemini_rejects_unexpected_dimensions(dimension):
    settings = Settings(embedding_url=BASE.rstrip("/"), embedding_model="gemini-embedding-001", embedding_key="test-only")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [{"embedding": [1.0] * dimension}]}))) as client:
        with pytest.raises(ProviderError, match="dimensions"):
            Provider(settings, client).embed(["document"])


def test_non_google_unindexed_response_remains_invalid(settings):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [{"embedding": [1.0, 0.0]}]}))) as client:
        with pytest.raises(ProviderError):
            Provider(settings, client).embed(["document"])


def test_google_url_normalization_from_environment(monkeypatch):
    monkeypatch.setenv("EMBEDDING_API_BASE_URL", BASE)
    monkeypatch.setenv("EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("LLM_API_BASE_URL", BASE)
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash")
    first = Settings()
    assert first.embedding_url == BASE.rstrip("/") and first.llm_url == BASE.rstrip("/")
    monkeypatch.setenv("EMBEDDING_API_BASE_URL", BASE.rstrip("/"))
    assert first.pipeline == Settings().pipeline
    monkeypatch.setenv("EMBEDDING_MODEL", "different-model")
    assert first.pipeline != Settings().pipeline


@pytest.mark.parametrize("model", ["gemini-2.5-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"])
def test_gemini_generation_schema_and_validation(model):
    settings = Settings(llm_url=BASE.rstrip("/"), llm_key="isolated-test-key", llm_model=model)
    def handler(request):
        assert str(request.url) == BASE + "chat/completions"
        assert request.headers["authorization"] == "Bearer isolated-test-key"
        body = json.loads(request.content)
        assert body["model"] == model
        if model == "gemini-2.5-flash":
            assert body["reasoning_effort"] == "none"
        else:
            assert body["reasoning_effort"] == "low"
            assert body["max_tokens"] == 512
        assert body["response_format"]["type"] == "json_schema"
        schema = body["response_format"]["json_schema"]["schema"]
        assert set(schema["required"]) == {"answer", "sources", "insufficient_evidence"}
        assert schema["additionalProperties"] is False
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"answer": "Documented finding [1]", "sources": [1], "insufficient_evidence": False})}}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = Provider(settings, client).generate("question", [{"label": 1, "text": "documented finding"}])
    assert result["sources"] == [1]


@pytest.mark.parametrize("status", [401, 403, 404, 429])
def test_google_failures_are_safe_and_never_fallback(settings, status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "private key or source text must not leak"}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError) as error:
            Provider(settings, client).embed(["document"])
    assert str(status) in str(error.value) and "private key" not in str(error.value)
    assert len(calls) == 1


def test_transient_503_retries_identical_request_once(settings, monkeypatch):
    monkeypatch.setattr("app.provider.time.sleep", lambda seconds: None)
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": {"message": "Temporarily overloaded"}})
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert Provider(settings, client).embed(["source"]) == [[1.0, 0.0]]
    assert len(calls) == 2
    assert calls[0].url == calls[1].url and calls[0].content == calls[1].content
    assert calls[0].headers["authorization"] == calls[1].headers["authorization"]


def test_persistent_503_stops_after_one_retry(settings, monkeypatch):
    monkeypatch.setattr("app.provider.time.sleep", lambda seconds: None)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError, match="503"):
            Provider(settings, client).embed(["source"])
    assert len(calls) == 2


def test_retry_uses_remaining_provider_budget(settings, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("app.provider.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("app.provider.time.sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            clock[0] += settings.provider_timeout / 2
            return httpx.Response(503)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        Provider(settings, client).embed(["source"])
    assert len(calls) == 2
    assert calls[1].extensions["timeout"]["read"] == settings.provider_timeout / 2 - 2


def test_late_overload_does_not_start_another_full_timeout(settings, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("app.provider.time.monotonic", lambda: clock[0])
    calls = []
    def handler(request):
        calls.append(request)
        clock[0] += settings.provider_timeout - 1
        return httpx.Response(503)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError, match="503"):
            Provider(settings, client).embed(["source"])
    assert len(calls) == 1
