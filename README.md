# LifeBridge

**Messy emergency input in → verified action card out.** A Gemini-powered bridge between a frightened person and the systems that can help them.

Built for PromptWars × TechVerse: *"a universal bridge between human intent and complex systems… converts unstructured, messy, real-world inputs into structured, verified, and life-saving actions."*

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

The product prompt is in [`app/prompts/system_prompt.md`](app/prompts/system_prompt.md). Its design and iteration history are in [`PROMPT_STRATEGY_TEMPLATE.md`](PROMPT_STRATEGY_TEMPLATE.md).

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
  main.py            HTTP layer: validation, security headers, rate limit, static files
  pipeline.py        rules -> Gemini -> validation/retry -> verification -> ActionCard
  gemini_client.py   the only module that calls Gemini
  prompts/system_prompt.md   the product prompt
  schemas.py         Gemini output contract + API response contract
  verify.py          evidence grounding, red-flag rules, severity floor, sanitising
  protocols.py       vetted protocol cards + fixed emergency numbers
  actions.py         SOS message, map links, contacts
  fallback.py        deterministic card when Gemini can't be used
  ratelimit.py       per-IP sliding-window limiter
static/              index.html, styles.css, app.js
tests/               API + unit tests (Gemini mocked)
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
- `POST /api/analyze` (multipart form): `text`, `images` (0–3 JPEG/PNG/WebP/HEIC), optional `lat` + `lng` → `ActionCard` JSON (see `app/schemas.py`). Errors: `400` empty/invalid, `413` too large, `415` unsupported file, `429` rate limited — all as `{"error", "message"}`.

## Testing
```bash
pytest -q        # Gemini is mocked - no key or quota needed
ruff check .
```
Covers: normal flow, photos, location links, evidence verification (incl. meaning-flipping near-matches), safety-rule escalation, prompt injection, dose/phone scrubbing, out-of-scope input, malformed output + retry, invented protocol IDs, model failure, missing key, all input-validation errors, rate limiting, security headers. CI runs both on every push (`.github/workflows/ci.yml`).

### Live prompt evaluation
`python -m evals.run_evals` runs the 5 cases in [`evals/cases.json`](evals/cases.json) (clear emergency, ambiguous wording, minor injury, out-of-scope, prompt injection) against the real model through the full pipeline and saves raw replies + final cards to `evals/results/<prompt-version>.json`. It uses API quota, so it is run deliberately, not in CI. Findings feed the iteration log in [`PROMPT_STRATEGY_TEMPLATE.md`](PROMPT_STRATEGY_TEMPLATE.md).

## Deployment
The image is platform-neutral. Current target: **Render** (free web service, Docker runtime).
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
- No database, no storage of user input; logs contain outcomes/latency, never user content.
- User text is wrapped as data inside delimiters; attempts to close the delimiter are stripped.

## Accessibility
Semantic landmarks and headings, labelled inputs, skip link, keyboard-operable controls with visible focus, `role="status"`/`role="alert"` live regions, focus moved to the result card, severity conveyed by text + icon (not colour alone), 48px+ touch targets, `prefers-reduced-motion` respected, mobile-first layout.

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
