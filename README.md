# LifeBridge

[![CI](https://github.com/Krishnavamsi0018/Prompt-Wars-MKV/actions/workflows/ci.yml/badge.svg)](https://github.com/Krishnavamsi0018/Prompt-Wars-MKV/actions/workflows/ci.yml)

**Live app: https://lifebridge-xtwa.onrender.com**

**Messy emergency input in → verified action card out.** A Gemini-powered bridge between a frightened person and the systems that can help them.

Built for PromptWars × TechVerse: *"a universal bridge between human intent and complex systems… converts unstructured, messy, real-world inputs into structured, verified, and life-saving actions."*

## How LifeBridge meets the evaluation criteria
| Criterion | What we did | Where to look |
|---|---|---|
| Problem statement alignment | Messy free text (any language) and photos → Gemini structured output → deterministic verification → concrete actions (call buttons, vetted steps, SOS message, map links) | [Solution](#solution), [`app/pipeline.py`](app/pipeline.py) |
| Code quality | Small single-purpose modules, one module that talks to Gemini, typed Pydantic contracts, ruff lint in CI | [`app/`](app), [`app/schemas.py`](app/schemas.py), [`pyproject.toml`](pyproject.toml) |
| Security | API key only in server env vars; strict CSP and security headers; uploads checked by magic bytes and size; per-IP rate limit; model/user text rendered with `textContent`; user text wrapped as data against prompt injection | [Security](#security), [`app/main.py`](app/main.py), [`app/gemini_client.py`](app/gemini_client.py) |
| Efficiency | One Gemini call per request; photos downscaled in the browser; one shared 25 s budget for the whole Gemini step; failover only on transient errors; no database | [`app/gemini_client.py`](app/gemini_client.py), [`app/pipeline.py`](app/pipeline.py), [`static/app.js`](static/app.js) |
| Testing | 108 pytest tests with Gemini mocked (no quota used), run in CI on every push; a separate 5-case live evaluation harness | [`tests/`](tests), [`.github/workflows/ci.yml`](.github/workflows/ci.yml), [`evals/`](evals) |
| Accessibility | Semantic HTML, labelled inputs, skip link, keyboard focus, live regions, severity in text not colour alone, reduced-motion support, mobile layout | [Accessibility](#accessibility), [`static/index.html`](static/index.html) |
| Google services | Gemini API via the official `google-genai` SDK (structured output + multimodal), Google AI Studio, Google Maps URLs | [Google services used](#google-services-used) |

## Problem
In the first minutes of an emergency, bystanders panic, type badly, mix languages, and don't know what to do or what responders need to hear. Emergency systems need structured facts: what happened, how serious, where, who is hurt.

## Solution
LifeBridge takes a free-text description (any language) and optional photos, and returns an **action card**:

- **Severity** and incident type
- **Do this now** — vetted first-aid / safety steps
- **Call for help** — the right numbers (112 always first)
- **Responders will ask** — the critical missing information
- **SOS message** — ready to copy/share, built only from verified facts, with a Google Maps link if location is shared
- **What LifeBridge understood** — every extracted fact labelled *Verified from your words*, *From photo – please confirm*, or *Not verified*

The **Call 112** bar is always visible and never depends on the AI.

The app also has three in-app sections, switched from the sidebar (or the tab strip on mobile):
- **Emergency** — one-tap cards for 112, 108 and 100, plus safety steps rendered from the same vetted protocol cards the action card uses (served by `GET /api/protocols`, so there is one source of first-aid wording).
- **About** — how LifeBridge works: Describe → Understand → Verify → Act.
- **FAQ** — what you can describe, photos, location, diagnosis, automatic calling, what happens if Gemini is unavailable, and what is stored.

## Core principle: the model interprets, code verifies and instructs

```text
Browser (text + photos, optional location)
   │
   ▼
POST /api/analyze  (FastAPI)
 1. Input validation   size/type limits (magic bytes), rate limit
 2. Red-flag rules     deterministic keyword rules (English + Hindi) on the text
 3. Gemini             one multimodal call, structured output (response_schema)
 4. Schema validation  Pydantic; 1 retry with the validation error; else fallback card
 5. Verification       evidence quotes checked against the user's text;
                       severity = max(model, rules) - rules never lower it;
                       protocol IDs -> pre-written steps; numbers from a fixed table;
                       doses / phone numbers scrubbed from model prose
 6. Actions            SOS message + map links assembled by code
   │
   ▼
Action card (JSON) -> rendered with textContent (no HTML injection)
```

**Model failover (availability only):** on a transient 429 / 503 / 504 (seen repeatedly during live testing), the same request moves to the next model in `GEMINI_FALLBACK_MODELS`; each model gets at most one attempt. The whole Gemini step — first call, failover and the one schema-repair call — shares a single 25 s budget that keeps 1 s in reserve for validation; the repair call is skipped if under 4 s remain. Whichever model answers, the output goes through the identical prompt, schema validation, evidence checks and safety rules, and the user is not shown which model answered. If every model is unavailable, a call times out, fails with any other error, or returns invalid output twice, the user gets a **fallback card** driven by the red-flag rules, with contacts and safety steps.

## What Gemini does — and does not do
| Gemini does | Gemini never does |
|---|---|
| Understand messy, multilingual text and photos | Diagnose |
| Classify scope, incident type, severity | Write first-aid instructions (it selects IDs from a vetted list) |
| Extract facts with verbatim evidence quotes | Produce phone numbers or drug doses |
| List unknowns and follow-up questions | Lower a severity the safety rules have raised |

The product prompt is in [`app/prompts/system_prompt.md`](app/prompts/system_prompt.md) (current: v2; v1 kept in [`app/prompts/archive/`](app/prompts/archive)). Its design and iteration history are in [`PROMPT_STRATEGY_TEMPLATE.md`](PROMPT_STRATEGY_TEMPLATE.md).

## Google services used
Only what the code actually uses:

| Service | How LifeBridge uses it | Where |
|---|---|---|
| **Gemini API** (key from Google AI Studio) | The single AI step: one call per request through the official `google-genai` Python SDK | [`app/gemini_client.py`](app/gemini_client.py) |
| **Gemini structured output** | `response_mime_type="application/json"` + `response_schema` set to the Pydantic model `GeminiAssessment`, so replies follow a fixed contract with enum-constrained fields (incident type, severity, protocol IDs) | [`app/gemini_client.py`](app/gemini_client.py), [`app/schemas.py`](app/schemas.py) |
| **Gemini multimodal input** | Scene or document photos are sent as image parts in the same call as the text | [`app/gemini_client.py`](app/gemini_client.py) |
| **Gemini model failover** (optional) | `GEMINI_FALLBACK_MODELS` can list further Gemini models to try on 429/503/504; the same prompt, schema and verification apply to every model | [`app/gemini_client.py`](app/gemini_client.py) |
| **Google AI Studio** | API key provisioning and checking per-model rate limits | – |
| **Google Maps URLs** | "My location" and "hospitals near me" links in the action card and SOS message (no Maps API key needed) | [`app/actions.py`](app/actions.py) |

Not used: **Cloud Run**. The live app runs on Render because Google Cloud billing was not available to us; the Dockerfile listens on `$PORT` and is Cloud Run-compatible (see [Deployment](#deployment)).

## Tech stack
| Part | Choice | Why |
|---|---|---|
| AI | Gemini API (Google AI Studio key) via `google-genai` | Multimodal, fast, native structured output |
| Backend | Python, FastAPI, Pydantic v2 | Pydantic is both the schema sent to Gemini and the validator of its reply |
| Frontend | Plain HTML/CSS/JS | No build step; full control over accessibility |
| Maps | Google Maps URLs | Location / nearby-hospital links without an API key |
| Tests | pytest + FastAPI TestClient, Gemini mocked; ruff | No API quota used by tests |
| Deploy | Docker (listens on `$PORT`) | Runs unchanged on Render, Hugging Face Spaces or Cloud Run |

## Project structure
```text
app/
  main.py            HTTP layer: validation, security headers, rate limit, static files, /api/protocols
  pipeline.py        rules -> Gemini -> validation/retry -> verification -> ActionCard
  gemini_client.py   the only module that calls Gemini (model failover, shared time budget)
  prompts/system_prompt.md          the product prompt (v2)
  prompts/archive/system_prompt_v1.md   the first version, kept for comparison
  schemas.py         Gemini output contract + API response contract
  verify.py          evidence grounding, red-flag rules, severity floor, sanitising
  protocols.py       vetted protocol cards + fixed emergency numbers (single source of first-aid wording)
  actions.py         SOS message, map links, contacts
  fallback.py        deterministic card when Gemini can't be used
  ratelimit.py       per-IP sliding-window limiter
static/              index.html, styles.css, app.js, landscape.svg (Home, Emergency, About, FAQ)
tests/               API, verification, Gemini-client failover and time-budget tests (Gemini mocked)
evals/               live 5-case evaluation harness (cases.json, run_evals.py) + raw results per prompt version
```

## Run locally
```bash
python -m venv .venv
.venv/Scripts/activate        # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
cp .env.example .env          # then put your Gemini API key in .env
uvicorn app.main:app --reload --port 8000
```
Open http://localhost:8000. Without a key the app still runs and serves fallback cards.

## Environment variables
| Name | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | yes (for AI) | – | Server-side only. Never sent to the browser, never committed. |
| `GEMINI_MODEL` | no | `gemini-3.6-flash` | Model id (`gemini-2.5-flash` is no longer available to new API keys) |
| `GEMINI_FALLBACK_MODELS` | no | *(empty)* | Comma-separated models tried in order after a 429/503/504, e.g. `gemini-3.7-flash,gemini-3.8-flash`. Empty = primary only |
| `GEMINI_TIMEOUT_S` | no | `25` | Overall budget for the Gemini step, shared by all models in the chain |
| `RATE_LIMIT_PER_MINUTE` | no | `8` | Per-IP limit on `/api/analyze` |
| `MAX_TEXT_CHARS`, `MAX_IMAGES`, `MAX_IMAGE_BYTES` | no | `4000`, `3`, `5 MB` | Input limits |

## API
- `GET /healthz` → `{"status": "ok", "gemini_configured": true|false}`
- `GET /api/protocols?ids=a,b` → read-only list of vetted protocol cards (`id`, `title`, `steps`) straight from `app/protocols.py`; unknown IDs are ignored, no `ids` returns all. Used by the Emergency section.
- `POST /api/analyze` (multipart form): `text`, `images` (0–3 JPEG/PNG/WebP/HEIC), optional `lat` + `lng` → `ActionCard` JSON (see `app/schemas.py`). Errors: `400` empty/invalid, `413` too large, `415` unsupported file, `429` rate limited — all as `{"error", "message"}`.

## Testing
```bash
pytest -q        # Gemini is mocked - no key or quota needed
ruff check .
```
108 tests. Covers: normal flow, photos, location links, evidence verification (incl. meaning-flipping near-matches), fact/summary wording kept faithful to the user's words, safety-rule escalation, prompt injection, dose/phone scrubbing, out-of-scope input, malformed output + repair attempt, invented protocol IDs, model failure, Gemini model failover (429/503/504 only), the shared 25 s time budget, missing key, all input-validation errors, rate limiting, security headers, the `/api/protocols` endpoint, and a guard that fails if protocol steps are ever duplicated in the frontend. CI runs lint and tests on every push (`.github/workflows/ci.yml`).

### Live prompt evaluation
`python -m evals.run_evals` runs the 5 cases in [`evals/cases.json`](evals/cases.json) (clear emergency, ambiguous wording, minor injury, out-of-scope, prompt injection) against the real model through the full pipeline and saves raw replies + final cards to `evals/results/<prompt-version>.json`. It uses API quota, so it is run deliberately, not in CI. Findings feed the iteration log in [`PROMPT_STRATEGY_TEMPLATE.md`](PROMPT_STRATEGY_TEMPLATE.md).

## Deployment
The image is platform-neutral. Current target: **Render** (free web service, Docker runtime) — live at https://lifebridge-xtwa.onrender.com.
1. Push this repo to GitHub.
2. Render → New → Web Service → connect the repo → Runtime: Docker → Instance: Free.
3. Environment → add `GEMINI_API_KEY` (and optionally `GEMINI_MODEL`).
4. Health check path: `/healthz`.

Cloud Run (if billing is available): `gcloud run deploy lifebridge --source . --set-env-vars GEMINI_MODEL=... --set-secrets GEMINI_API_KEY=...`

## Security
- API key only in server environment variables; `.env` is git-ignored; `.env.example` has placeholders.
- Same-origin API; strict Content-Security-Policy, `nosniff`, `DENY` framing, no referrer.
- Uploads validated by size and magic bytes; request size capped.
- Per-IP rate limiting protects the Gemini quota.
- No accounts and no database. Information submitted for analysis is sent to the Gemini API. Application logs record outcomes (severity, counts, errors), never message content; server access logs may contain technical request information such as IP addresses.
- User text is wrapped as data inside delimiters; attempts to close the delimiter are stripped.

## Accessibility
Semantic landmarks and headings, labelled inputs, skip link, keyboard-operable controls with visible focus (the photo and location cards show a focus ring around the whole card), `role="status"`/`role="alert"` live regions, focus moved to the result card and to the heading when switching sections, `aria-current` on the active section, native `<details>` accordion for the FAQ, severity conveyed by text + icon (not colour alone), large targets for the main actions (42–56 px), `prefers-reduced-motion` respected, responsive layout checked at 375 px with no horizontal scrolling.

## Known limitations
- Protocol content is adapted from general public first-aid guidance and has **not** been reviewed by a medical professional.
- Emergency numbers are India-specific.
- Red-flag rules cover English and common Hindi phrasings only; other languages rely on Gemini.
- Image-derived facts can't be verified by code — they are labelled for human confirmation.
- The Gemini free tier may use inputs to improve Google products — demo with synthetic data only; production would use a paid tier / Vertex AI.
- The rate limiter is in-memory (single instance).
- Voice input and medical-document context are not yet implemented.

## Future improvements
Voice notes, medical-record photos → patient context (allergies, medications), region-aware emergency numbers, clinician-reviewed protocol content, more languages in the safety rules.

## Disclaimer
LifeBridge gives general safety guidance, not medical advice or a diagnosis. It does not contact emergency services. If anyone may be in danger, call 112.
