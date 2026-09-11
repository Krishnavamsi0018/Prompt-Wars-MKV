"""HTTP layer: input validation, security headers, rate limiting, static frontend."""

import logging
import math
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.gemini_client import GeminiClient
from app.pipeline import analyze
from app.ratelimit import RateLimiter
from app.schemas import ActionCard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("lifebridge")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "geolocation=(self), camera=(self), microphone=(self)",
}


def sniff_image_mime(data: bytes) -> str | None:
    """Trust file content, not the client-supplied Content-Type."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftyphevc", b"ftypmif1"):
        return "image/heic"
    return None


def error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status, headers=headers)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.llm = GeminiClient(settings) if settings.gemini_configured else None
    app.state.limiter = RateLimiter(settings.rate_limit_per_minute)
    if app.state.llm is None:
        log.warning("GEMINI_API_KEY not set: /api/analyze will serve deterministic fallback cards")
    yield


app = FastAPI(title="LifeBridge", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def guard(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.max_request_bytes:
        response = error(413, "payload_too_large", "The upload is too large. Send fewer or smaller photos.")
    else:
        response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


@app.get("/healthz")
async def healthz(request: Request) -> dict:
    return {"status": "ok", "gemini_configured": request.app.state.llm is not None}


@app.post("/api/analyze", response_model=ActionCard)
async def analyze_endpoint(
    request: Request,
    text: str = Form(""),
    lat: float | None = Form(None),
    lng: float | None = Form(None),
    images: list[UploadFile] = File(default=[]),  # noqa: B008 - FastAPI's dependency-declaration idiom
):
    retry_after = request.app.state.limiter.check(client_ip(request))
    if retry_after:
        return error(429, "rate_limited", "Too many requests. Please wait a moment. If in danger, call 112.",
                     {"Retry-After": str(math.ceil(retry_after))})

    text = text.strip()
    images = [f for f in images if f.filename]  # browsers send an empty part when no file is chosen
    if not text and not images:
        return error(400, "empty_input", "Describe what is happening or add a photo.")
    if len(text) > settings.max_text_chars:
        return error(413, "text_too_long", f"Please keep the description under {settings.max_text_chars} characters.")
    if len(images) > settings.max_images:
        return error(400, "too_many_images", f"Please send at most {settings.max_images} photos.")
    if (lat is None) != (lng is None) or (
        lat is not None and not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180)
    ):
        return error(400, "invalid_location", "Location is invalid.")

    image_parts: list[tuple[bytes, str]] = []
    for upload in images:
        data = await upload.read(settings.max_image_bytes + 1)
        if len(data) > settings.max_image_bytes:
            return error(413, "image_too_large",
                         f"Each photo must be under {settings.max_image_bytes // (1024 * 1024)} MB.")
        mime = sniff_image_mime(data)
        if mime is None:
            return error(415, "unsupported_file_type", "Only JPEG, PNG, WebP or HEIC photos are supported.")
        image_parts.append((data, mime))

    return await analyze(request.app.state.llm, text, image_parts, lat, lng)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
