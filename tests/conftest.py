import json
import os

# Tests must never reach the real Gemini API or depend on a developer's .env.
# Set before importing the app: load_dotenv() does not override existing variables.
os.environ["GEMINI_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient

from app.gemini_client import LLMError
from app.main import app
from app.ratelimit import RateLimiter


class FakeLLM:
    """Stands in for Gemini. Each queued item is returned (str/dict) or raised (Exception) in order."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def generate(self, user_text, images, correction=None, deadline=None):
        self.calls.append({"text": user_text, "images": images, "correction": correction, "deadline": deadline})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item)


def assessment(**overrides) -> dict:
    base = {
        "scope": "emergency",
        "incident_type": "injury_trauma",
        "severity": "high",
        "summary": "An elderly man fell on the stairs and is bleeding from the head.",
        "language": "en",
        "facts": [
            {"category": "injury", "label": "Injury", "value": "Bleeding from the head",
             "source": "text", "quote": "blood on his head", "confidence": "high"},
            {"category": "location", "label": "Location", "value": "Near Hebbal flyover",
             "source": "text", "quote": "near Hebbal flyover", "confidence": "high"},
        ],
        "protocol_ids": ["severe_bleeding"],
        "follow_up_questions": ["Is he breathing normally?"],
        "unknowns": ["Whether he is conscious"],
    }
    base.update(overrides)
    return base


NORMAL_TEXT = "my father fell on the stairs, there is blood on his head, we are near Hebbal flyover"


@pytest.fixture
def client():
    with TestClient(app) as c:
        app.state.limiter = RateLimiter(1000)
        yield c


@pytest.fixture
def use_llm(client):
    def _install(*responses) -> FakeLLM:
        fake = FakeLLM(*responses)
        app.state.llm = fake
        return fake
    return _install


__all__ = ["FakeLLM", "LLMError", "assessment", "NORMAL_TEXT"]
