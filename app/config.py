"""Settings from environment variables. Locally they come from .env; in production from the host's secret config."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    gemini_timeout_s: int = _int("GEMINI_TIMEOUT_S", 25)
    max_text_chars: int = _int("MAX_TEXT_CHARS", 4000)
    max_images: int = _int("MAX_IMAGES", 3)
    max_image_bytes: int = _int("MAX_IMAGE_BYTES", 5 * 1024 * 1024)
    max_request_bytes: int = _int("MAX_REQUEST_BYTES", 18 * 1024 * 1024)
    rate_limit_per_minute: int = _int("RATE_LIMIT_PER_MINUTE", 8)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)


settings = Settings()
