"""Transient-error retry in the Gemini client. The SDK call is faked: no network, no quota."""

import asyncio
from types import SimpleNamespace

import pytest
from google.genai import errors

from app import gemini_client
from app.config import Settings
from app.gemini_client import GeminiClient, LLMError
from app.main import app
from tests.conftest import NORMAL_TEXT, assessment


def api_error(code: int) -> errors.APIError:
    cls = errors.ServerError if code >= 500 else errors.ClientError
    return cls(code, {"error": {"code": code, "message": "test", "status": "TEST"}})


class FakeModels:
    def __init__(self, *outcomes, delay_s: float = 0.0):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.delay_s = delay_s

    async def generate_content(self, model, contents, config):
        self.calls += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)


@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setattr(gemini_client, "RETRY_DELAY_S", 0)

    def _make(*outcomes, timeout_s: int = 25, delay_s: float = 0.0) -> tuple[GeminiClient, FakeModels]:
        client = GeminiClient(Settings(gemini_api_key="test-key-not-real", gemini_timeout_s=timeout_s))
        fake = FakeModels(*outcomes, delay_s=delay_s)
        client._client = SimpleNamespace(aio=SimpleNamespace(models=fake))
        return client, fake

    return _make


def generate(client: GeminiClient) -> str:
    return asyncio.run(client.generate("help", []))


# 1. 503 -> one retry -> success
def test_503_then_success_retries_once(make_client):
    client, fake = make_client(api_error(503), '{"ok": true}')
    assert generate(client) == '{"ok": true}'
    assert fake.calls == 2


@pytest.mark.parametrize("code", [429, 504])
def test_other_transient_codes_are_retried(make_client, code):
    client, fake = make_client(api_error(code), '{"ok": true}')
    assert generate(client) == '{"ok": true}'
    assert fake.calls == 2


# 2. 503 -> retry -> failure -> deterministic fallback
def test_503_twice_raises_after_exactly_one_retry(make_client):
    client, fake = make_client(api_error(503), api_error(503))
    with pytest.raises(LLMError):
        generate(client)
    assert fake.calls == 2, "at most one retry"


def test_503_twice_serves_fallback_card_through_api(client, make_client):
    gemini, fake = make_client(api_error(503), api_error(503))
    app.state.llm = gemini
    r = client.post("/api/analyze", data={"text": "my uncle collapsed and is not breathing"})
    assert r.status_code == 200
    card = r.json()
    assert card["source"] == "fallback"
    assert card["severity"] == "critical"
    assert fake.calls == 2


def test_503_then_success_serves_ai_card_through_api(client, make_client):
    import json
    gemini, fake = make_client(api_error(503), json.dumps(assessment()))
    app.state.llm = gemini
    card = client.post("/api/analyze", data={"text": NORMAL_TEXT}).json()
    assert card["source"] == "gemini"
    assert fake.calls == 2


# 3. invalid output -> NO transient retry
def test_invalid_output_is_returned_without_transient_retry(make_client):
    client, fake = make_client("this is not json", '{"never": "used"}')
    assert generate(client) == "this is not json"
    assert fake.calls == 1


def test_invalid_output_only_gets_the_schema_repair_attempt(client, make_client):
    """Invalid output is handled by the pipeline's single schema-repair call (with the validation error),
    never by the transient retry: exactly 2 SDK calls, then the fallback card."""
    gemini, fake = make_client("not json", "still not json")
    app.state.llm = gemini
    card = client.post("/api/analyze", data={"text": NORMAL_TEXT}).json()
    assert card["source"] == "fallback"
    assert fake.calls == 2


# 4. non-transient errors -> NO retry
@pytest.mark.parametrize("code", [400, 401, 403, 404, 500])
def test_non_transient_api_errors_are_not_retried(make_client, code):
    client, fake = make_client(api_error(code), '{"never": "used"}')
    with pytest.raises(LLMError):
        generate(client)
    assert fake.calls == 1


def test_unexpected_exception_is_not_retried(make_client):
    client, fake = make_client(ValueError("boom"), '{"never": "used"}')
    with pytest.raises(LLMError):
        generate(client)
    assert fake.calls == 1


# Overall timeout budget is preserved
def test_no_retry_when_the_overall_budget_is_too_small(make_client):
    # 2 s left < MIN_RETRY_BUDGET_S (3 s): a retry could not finish inside the overall timeout
    client, fake = make_client(api_error(503), '{"ok": true}', timeout_s=2)
    with pytest.raises(LLMError):
        generate(client)
    assert fake.calls == 1


def test_own_timeout_is_not_retried(make_client):
    client, fake = make_client('{"ok": true}', '{"ok": true}', timeout_s=1, delay_s=2)
    with pytest.raises(LLMError, match="timeout"):
        generate(client)
    assert fake.calls == 1
