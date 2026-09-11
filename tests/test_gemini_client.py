"""Model failover in the Gemini client. The SDK call is faked: no network, no quota."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from google.genai import errors

from app.config import Settings, _csv
from app.gemini_client import GeminiClient, LLMError
from app.main import app
from tests.conftest import NORMAL_TEXT, assessment

PRIMARY, SECOND, THIRD = "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash"


def api_error(code: int) -> errors.APIError:
    cls = errors.ServerError if code >= 500 else errors.ClientError
    return cls(code, {"error": {"code": code, "message": "test", "status": "TEST"}})


class FakeModels:
    """Each call pops the next outcome (text, or an exception to raise) and records which model was asked."""

    def __init__(self, *outcomes, delay_s: float = 0.0):
        self.outcomes = list(outcomes)
        self.models_called: list[str] = []
        self.delay_s = delay_s

    async def generate_content(self, model, contents, config):
        self.models_called.append(model)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)


@pytest.fixture
def make_client():
    def _make(*outcomes, timeout_s: int = 25, delay_s: float = 0.0,
              fallbacks: tuple[str, ...] = (SECOND, THIRD)) -> tuple[GeminiClient, FakeModels]:
        settings = Settings(gemini_api_key="test-key-not-real", gemini_model=PRIMARY,
                            gemini_fallback_models=fallbacks, gemini_timeout_s=timeout_s)
        client = GeminiClient(settings)
        fake = FakeModels(*outcomes, delay_s=delay_s)
        client._client = SimpleNamespace(aio=SimpleNamespace(models=fake))
        return client, fake

    return _make


def generate(client: GeminiClient) -> str:
    return asyncio.run(client.generate("help", []))


# 1. primary success -> no failover
def test_primary_success_uses_no_fallback(make_client):
    client, fake = make_client('{"ok": 1}')
    assert generate(client) == '{"ok": 1}'
    assert fake.models_called == [PRIMARY]


# 2. primary 503 -> second model succeeds
def test_primary_503_fails_over_to_second_model(make_client):
    client, fake = make_client(api_error(503), '{"ok": 2}')
    assert generate(client) == '{"ok": 2}'
    assert fake.models_called == [PRIMARY, SECOND]


# 3. 503 -> 503 -> third model succeeds
def test_two_503s_fail_over_to_third_model(make_client):
    client, fake = make_client(api_error(503), api_error(503), '{"ok": 3}')
    assert generate(client) == '{"ok": 3}'
    assert fake.models_called == [PRIMARY, SECOND, THIRD]


@pytest.mark.parametrize("code", [429, 504])
def test_429_and_504_also_fail_over(make_client, code):
    client, fake = make_client(api_error(code), '{"ok": 2}')
    assert generate(client) == '{"ok": 2}'
    assert fake.models_called == [PRIMARY, SECOND]


# 4. every model transiently unavailable -> deterministic fallback
def test_all_models_transient_raises_after_one_attempt_each(make_client):
    client, fake = make_client(api_error(503), api_error(429), api_error(504))
    with pytest.raises(LLMError):
        generate(client)
    assert fake.models_called == [PRIMARY, SECOND, THIRD], "each model tried exactly once"


def test_all_models_transient_serves_fallback_card(client, make_client):
    gemini, fake = make_client(api_error(503), api_error(503), api_error(503))
    app.state.llm = gemini
    r = client.post("/api/analyze", data={"text": "my uncle collapsed and is not breathing"})
    assert r.status_code == 200
    card = r.json()
    assert card["source"] == "fallback"
    assert card["severity"] == "critical"
    assert len(fake.models_called) == 3


# 5. non-transient error on the primary -> no failover
@pytest.mark.parametrize("code", [400, 401, 403, 404, 500])
def test_non_transient_error_does_not_fail_over(make_client, code):
    client, fake = make_client(api_error(code), '{"never": "used"}')
    with pytest.raises(LLMError):
        generate(client)
    assert fake.models_called == [PRIMARY]


def test_unexpected_exception_does_not_fail_over(make_client):
    client, fake = make_client(ValueError("boom"), '{"never": "used"}')
    with pytest.raises(LLMError):
        generate(client)
    assert fake.models_called == [PRIMARY]


def test_non_transient_error_on_fallback_model_stops_the_chain(make_client):
    client, fake = make_client(api_error(503), api_error(404), '{"never": "used"}')
    with pytest.raises(LLMError):
        generate(client)
    assert fake.models_called == [PRIMARY, SECOND]


# 6. invalid structured output -> existing behaviour, no model failover
def test_invalid_output_is_returned_without_failover(make_client):
    client, fake = make_client("this is not json", '{"never": "used"}')
    assert generate(client) == "this is not json"
    assert fake.models_called == [PRIMARY]


def test_invalid_output_gets_only_the_existing_schema_repair_attempt(client, make_client):
    """Invalid output is handled by the pipeline's single schema-repair call (with the validation error),
    on the primary model again - never by model failover. Then the deterministic fallback card."""
    gemini, fake = make_client("not json", "still not json")
    app.state.llm = gemini
    card = client.post("/api/analyze", data={"text": NORMAL_TEXT}).json()
    assert card["source"] == "fallback"
    assert fake.models_called == [PRIMARY, PRIMARY]


# 7. the overall budget prevents excessive waiting
def test_no_failover_when_too_little_time_remains(make_client):
    # 3 s budget - 1 s validation reserve leaves ~2 s after the 503: below the 3 s minimum for another model.
    client, fake = make_client(api_error(503), '{"ok": 2}', timeout_s=3)
    with pytest.raises(LLMError):
        generate(client)
    assert fake.models_called == [PRIMARY]


def test_hanging_model_is_cut_off_inside_the_budget_and_not_failed_over(make_client):
    # budget 2 s - 1 s reserve = 1 s for the call; the fake would take 5 s.
    client, fake = make_client('{"late": 1}', '{"never": "used"}', timeout_s=2, delay_s=5)
    loop_time = asyncio.new_event_loop()
    try:
        start = loop_time.time()
        with pytest.raises(LLMError, match="timeout"):
            loop_time.run_until_complete(client.generate("help", []))
        elapsed = loop_time.time() - start
    finally:
        loop_time.close()
    assert fake.models_called == [PRIMARY]
    assert elapsed < 2, "a reply is never awaited past the budget minus the validation reserve"


def test_no_fallbacks_configured_means_single_attempt(make_client):
    client, fake = make_client(api_error(503), '{"never": "used"}', fallbacks=())
    with pytest.raises(LLMError):
        generate(client)
    assert fake.models_called == [PRIMARY]


def test_duplicate_models_are_not_tried_twice(make_client):
    client, fake = make_client(api_error(503), api_error(503), fallbacks=(PRIMARY, SECOND))
    with pytest.raises(LLMError):
        generate(client)
    assert fake.models_called == [PRIMARY, SECOND]


def test_fallback_models_env_parsing(monkeypatch):
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", " gemini-3.7-flash , ,gemini-3.8-flash ")
    assert _csv("GEMINI_FALLBACK_MODELS") == ("gemini-3.7-flash", "gemini-3.8-flash")
    monkeypatch.delenv("GEMINI_FALLBACK_MODELS")
    assert _csv("GEMINI_FALLBACK_MODELS") == ()


# 8. a fallback model's answer goes through exactly the same verification as the primary's
def test_fallback_model_output_gets_identical_verification(client, make_client):
    """Model under-rates severity and invents a quote. Whether the primary or the third model answers,
    the rules escalate, the invented quote is flagged, and the cards are the same."""
    text = "my uncle collapsed and is not breathing"
    raw = json.dumps(assessment(severity="low", scope="non_urgent", protocol_ids=[], facts=[
        {"category": "condition", "label": "Pulse", "value": "No pulse",
         "source": "text", "quote": "he has no pulse", "confidence": "high"},
    ]))

    primary_llm, _ = make_client(raw)
    app.state.llm = primary_llm
    primary_card = client.post("/api/analyze", data={"text": text}).json()

    fallback_llm, fake = make_client(api_error(503), api_error(503), raw)
    app.state.llm = fallback_llm
    fallback_card = client.post("/api/analyze", data={"text": text}).json()

    assert fake.models_called == [PRIMARY, SECOND, THIRD]
    assert fallback_card == primary_card
    assert fallback_card["source"] == "gemini"
    assert fallback_card["severity"] == "critical" and fallback_card["severity_escalated"] is True
    assert fallback_card["facts"][0]["status"] == "unverified"
    assert fallback_card["protocols"][0]["id"] == "unresponsive_person"
    assert "gemini-3" not in json.dumps(fallback_card), "the model used is not exposed to the user"
