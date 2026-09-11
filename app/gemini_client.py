"""The ONLY module that talks to Gemini. Everything else sees a plain `generate(...) -> str`."""

import asyncio
import re
from pathlib import Path
from typing import Protocol

from google import genai
from google.genai import types

from app.config import Settings
from app.protocols import protocol_catalog
from app.schemas import GeminiAssessment

PROMPT_PATH = Path(__file__).parent / "prompts" / "system_prompt.md"
_HTML_COMMENT = re.compile(r"<!--.*?-->\s*", re.DOTALL)


class LLMError(Exception):
    """Any failure to get a response from the model (timeout, quota, network, safety block, empty reply)."""


def load_system_prompt() -> str:
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    return _HTML_COMMENT.sub("", raw).replace("{{PROTOCOL_CATALOG}}", protocol_catalog()).strip()


def wrap_user_text(text: str) -> str:
    # Neutralise attempts to close the data block and smuggle instructions outside it.
    safe = re.sub(r"</?\s*user_report\s*>", "", text, flags=re.IGNORECASE)
    return f"<user_report>\n{safe}\n</user_report>"


class LLM(Protocol):
    async def generate(
        self, user_text: str, images: list[tuple[bytes, str]], correction: str | None = None
    ) -> str: ...


class GeminiClient:
    def __init__(self, settings: Settings) -> None:
        self._model = settings.gemini_model
        self._timeout_s = settings.gemini_timeout_s
        self._system_prompt = load_system_prompt()
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                timeout=settings.gemini_timeout_s * 1000,
                # No hidden SDK retries: in an emergency a fast fallback beats a slow retry.
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    async def generate(
        self, user_text: str, images: list[tuple[bytes, str]], correction: str | None = None
    ) -> str:
        parts: list[types.Part] = [types.Part.from_text(text=wrap_user_text(user_text))]
        parts += [types.Part.from_bytes(data=data, mime_type=mime) for data, mime in images]
        if images:
            parts.append(types.Part.from_text(text=f"[{len(images)} photo(s) attached above]"))
        if correction:
            parts.append(types.Part.from_text(text=correction))

        config = types.GenerateContentConfig(
            system_instruction=self._system_prompt,
            response_mime_type="application/json",
            response_schema=GeminiAssessment,
            temperature=0.1,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),  # no tools used
        )
        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self._model, contents=[types.Content(role="user", parts=parts)], config=config
                ),
                timeout=self._timeout_s,
            )
        except TimeoutError as exc:
            raise LLMError("timeout") from exc
        except Exception as exc:  # SDK raises several error types; the pipeline only needs "it failed"
            raise LLMError(type(exc).__name__) from exc

        text = response.text
        if not text:
            raise LLMError("empty_response")
        return text
