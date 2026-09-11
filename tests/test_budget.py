"""One overall time budget for the whole Gemini step: first call + model failover + schema-repair call.

Real pipeline + real GeminiClient, with only the SDK's network call faked (per-call delays / outcomes).
"""

import asyncio
import json
import time
from types import SimpleNamespace

from app.config import Settings
from app.gemini_client import GeminiClient
from app.pipeline import MIN_REPAIR_BUDGET_S, analyze
from tests.conftest import NORMAL_TEXT, FakeLLM, assessment
from tests.test_gemini_client import PRIMARY, SECOND, THIRD, api_error

VALID = json.dumps(assessment())


class TimedFakeModels:
    """outcomes[i] is returned/raised on call i after delays[i] seconds (missing delay = instant)."""

    def __init__(self, outcomes, delays=()):
        self.outcomes = list(outcomes)
        self.delays = list(delays)
        self.models_called: list[str] = []

    async def generate_content(self, model, contents, config):
        i = len(self.models_called)
        self.models_called.append(model)
        if i < len(self.delays) and self.delays[i]:
            await asyncio.sleep(self.delays[i])
        outcome = self.outcomes[i]
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)


def run(outcomes, delays=(), budget_s=25.0, text=NORMAL_TEXT):
    client = GeminiClient(Settings(gemini_api_key="test-key-not-real", gemini_model=PRIMARY,
                                   gemini_fallback_models=(SECOND, THIRD), gemini_timeout_s=25))
    fake = TimedFakeModels(outcomes, delays)
    client._client = SimpleNamespace(aio=SimpleNamespace(models=fake))
    start = time.perf_counter()
    card = asyncio.run(analyze(client, text, [], budget_s=budget_s))
    return card, fake, time.perf_counter() - start


# 1. normal successful response is unchanged
def test_normal_success_unchanged():
    card, fake, _ = run([VALID])
    assert card.source == "gemini"
    assert fake.models_called == [PRIMARY]


# 2. invalid output gets its repair attempt when enough time remains
def test_repair_attempt_when_time_remains():
    card, fake, _ = run(["not json", VALID], budget_s=MIN_REPAIR_BUDGET_S + 0.5)
    assert card.source == "gemini"
    assert fake.models_called == [PRIMARY, PRIMARY]


# 3. invalid output skips repair when too little time remains
def test_repair_skipped_when_time_is_short():
    card, fake, _ = run(["not json", VALID], budget_s=MIN_REPAIR_BUDGET_S - 0.5)
    assert card.source == "fallback"
    assert fake.models_called == [PRIMARY], "no repair call is started without enough time"


def test_repair_skipped_after_a_slow_first_reply():
    # 5 s budget; the first (invalid) reply takes 1.5 s -> 3.5 s left < MIN_REPAIR_BUDGET_S (4 s)
    card, fake, elapsed = run(["not json", VALID], delays=[1.5], budget_s=5)
    assert card.source == "fallback"
    assert fake.models_called == [PRIMARY]
    assert elapsed < 2.5


# 4. the whole operation cannot exceed the overall budget
def test_repair_call_shares_the_original_deadline():
    llm = FakeLLM("not json", assessment())
    card = asyncio.run(analyze(llm, NORMAL_TEXT, []))
    assert card.source == "gemini"
    assert llm.calls[0]["deadline"] is not None
    assert llm.calls[1]["deadline"] == llm.calls[0]["deadline"], "no fresh budget for the repair call"


def test_hanging_repair_call_is_cut_at_the_original_deadline():
    # 5 s budget: invalid reply at 0.5 s, repair starts (4.5 s left), repair call hangs for 30 s.
    # It must be cut off at deadline - 1 s validation reserve = ~4 s total, never a fresh 25 s.
    card, fake, elapsed = run(["not json", VALID], delays=[0.5, 30], budget_s=5)
    assert card.source == "fallback"
    assert fake.models_called == [PRIMARY, PRIMARY]
    assert elapsed < 5, f"took {elapsed:.1f}s - exceeded the overall budget"


# 5. model failover still works, inside the same budget
def test_failover_during_repair_call():
    card, fake, _ = run(["not json", api_error(503), VALID])
    assert card.source == "gemini"
    assert fake.models_called == [PRIMARY, PRIMARY, SECOND]


def test_failover_is_limited_by_the_shared_budget():
    # 5 s budget: invalid reply at 0.8 s -> repair starts (4.2 s left); the primary's 503 arrives at 1.3 s,
    # leaving 5 - 1.3 - 1 s reserve = 2.7 s < 3 s minimum, so no failover. A fresh per-call budget
    # would have failed over here.
    card, fake, elapsed = run(["not json", api_error(503), VALID], delays=[0.8, 0.5], budget_s=5)
    assert card.source == "fallback"
    assert fake.models_called == [PRIMARY, PRIMARY]
    assert elapsed < 5


# 6. final failure still produces the deterministic emergency fallback
def test_final_failure_gives_emergency_fallback():
    card, fake, _ = run([api_error(503), api_error(503), api_error(503)],
                        text="my uncle collapsed and is not breathing")
    assert card.source == "fallback"
    assert card.severity == "critical"
    assert card.protocols[0].id == "unresponsive_person"
    assert card.contacts[0].number == "112"
    assert fake.models_called == [PRIMARY, SECOND, THIRD]


def test_invalid_twice_gives_emergency_fallback():
    card, fake, _ = run(["not json", "still not json"], text="my uncle collapsed and is not breathing")
    assert card.source == "fallback"
    assert card.severity == "critical"
    assert fake.models_called == [PRIMARY, PRIMARY]
