"""The ONLY module that talks to Gemini. Everything else sees a plain `generate(...) -> str`."""

import asyncio
import logging
import re
from pathlib import Path
from typing import Protocol

from google import genai
from google.genai import errors, types

from app.config import Settings
from app.protocols import protocol_catalog
from app.schemas import GeminiAssessment

log = logging.getLogger("lifebridge")

PROMPT_PATH = Path(__file__).parent / "prompts" / "system_prompt.md"
_HTML_COMMENT = re.compile(r"<!--.*?-->\s*", re.DOTALL)


class LLMError(Exception):
    """Any failure to get a response from the model (timeout, quota, network, safety block, empty reply)."""


# Model failover (availability only). Live tests saw repeated 503 "high demand" (returned in ~4-6 s) and
# 504 errors on more than one model. On 429/503/504 the SAME request moves to the next configured model;
# each model gets at most one attempt. Everything else (400 bad request, 401/403 auth, 404 model, 500,
# our own timeout, empty reply, unexpected exceptions) fails straight to the deterministic fallback.
TRANSIENT_STATUS_CODES = frozenset({429, 503, 504})
VALIDATION_RESERVE_S = 1.0  # time kept back inside the overall budget for schema validation + verification
MIN_ATTEMPT_BUDGET_S = 3.0  # don't start a failover attempt that can't realistically finish in time


def is_transient(exc: Exception) -> bool:
    return isinstance(exc, errors.APIError) and exc.code in TRANSIENT_STATUS_CODES


def load_system_prompt() -> str:
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    return _HTML_COMMENT.sub("", raw).replace("{{PROTOCOL_CATALOG}}", protocol_catalog()).strip()


def wrap_user_text(text: str) -> str:
    # Neutralise attempts to close the data block and smuggle instructions outside it.
    safe = re.sub(r"</?\s*user_report\s*>", "", text, flags=re.IGNORECASE)
    return f"<user_report>\n{safe}\n</user_report>"


class LLM(Protocol):
    async def generate(
        self,
        user_text: str,
        images: list[tuple[bytes, str]],
        correction: str | None = None,
        deadline: float | None = None,
    ) -> str: ...


class GeminiClient:
    def __init__(self, settings: Settings) -> None:
        # Primary first, then configured fallbacks; duplicates removed so no model is tried twice.
        self._models = tuple(dict.fromkeys([settings.gemini_model, *settings.gemini_fallback_models]))
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
        self,
        user_text: str,
        images: list[tuple[bytes, str]],
        correction: str | None = None,
        deadline: float | None = None,
    ) -> str:
        """`deadline` (event-loop clock) lets the caller share ONE budget across several generate() calls."""
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
        contents = [types.Content(role="user", parts=parts)]
        loop = asyncio.get_running_loop()
        if deadline is None:  # ONE overall budget shared by every model in the chain
            deadline = loop.time() + self._timeout_s

        for index, model in enumerate(self._models):
            # A reply must arrive with VALIDATION_RESERVE_S to spare, so a late answer is never returned.
            budget = deadline - loop.time() - VALIDATION_RESERVE_S
            try:
                response = await asyncio.wait_for(
                    self._client.aio.models.generate_content(model=model, contents=contents, config=config),
                    timeout=max(0.0, budget),
                )
            except TimeoutError as exc:
                raise LLMError("timeout") from exc
            except Exception as exc:  # SDK raises several error types; the pipeline only needs "it failed"
                reason = f"{type(exc).__name__}:{getattr(exc, 'code', '')}"
                has_next = index + 1 < len(self._models)
                time_left = deadline - loop.time() - VALIDATION_RESERVE_S
                if is_transient(exc) and has_next and time_left >= MIN_ATTEMPT_BUDGET_S:
                    log.warning("gemini %s on %s; failing over to %s", reason, model, self._models[index + 1])
                    continue
                raise LLMError(reason) from exc

            text = response.text
            if not text:
                raise LLMError("empty_response")
            if index:
                log.info("gemini answered by fallback model %s", model)
            return text

        raise LLMError("no_models_configured")  # unreachable with a non-empty chain; kept for type safety
