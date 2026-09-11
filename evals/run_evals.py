"""Run a SMALL set of real Gemini cases through the production pipeline and record the results.

Uses real API quota - run deliberately, not in CI.
    python -m evals.run_evals            # all cases
    python -m evals.run_evals minor_injury out_of_scope
    python -m evals.run_evals --single-call   # hard budget: one real call per case
Results: evals/results/<prompt-version>.json (committed as evidence for the prompt iteration log).
"""

import asyncio
import json
import re
import sys
import time
from pathlib import Path

from app.config import settings
from app.gemini_client import PROMPT_PATH, GeminiClient, LLMError
from app.pipeline import analyze

ROOT = Path(__file__).parent
TRANSIENT_RETRY_DELAY_S = 10


class RecordingLLM:
    """Wraps the real client and keeps every raw reply / error for the record."""

    def __init__(self, inner: GeminiClient, max_calls: int | None = None) -> None:
        self.inner = inner
        self.max_calls = max_calls
        self.log: list[dict] = []

    async def generate(self, user_text, images, correction=None):
        if self.max_calls is not None and len(self.log) >= self.max_calls:
            self.log.append({"ok": False, "seconds": 0, "error": "call budget exhausted (not sent)"})
            raise LLMError("call_budget_exhausted")
        t0 = time.perf_counter()
        try:
            raw = await self.inner.generate(user_text, images, correction)
            self.log.append({"ok": True, "seconds": round(time.perf_counter() - t0, 1),
                             "correction": bool(correction), "raw": raw})
            return raw
        except LLMError as exc:
            cause = exc.__cause__
            self.log.append({"ok": False, "seconds": round(time.perf_counter() - t0, 1),
                             "error": f"{exc} {type(cause).__name__ if cause else ''} {str(cause)[:300] if cause else ''}"})
            raise


def check(card: dict, expect: dict) -> list[str]:
    problems = []
    for key in ("severity", "scope", "incident_type"):
        if key in expect and card[key] not in expect[key]:
            problems.append(f"{key}={card[key]} (expected {expect[key]})")
    ids = [p["id"] for p in card["protocols"]]
    for pid in expect.get("protocols_required", []):
        if pid not in ids:
            problems.append(f"missing protocol {pid}")
    forbidden = expect.get("protocols_forbidden", [])
    if "*" in forbidden and ids:
        problems.append(f"expected no protocols, got {ids}")
    problems += [f"forbidden protocol {p}" for p in forbidden if p in ids]
    values = " ".join(f["value"] for f in card["facts"]).lower()
    problems += [f"fact value contains '{w}'" for w in expect.get("value_must_not_contain", []) if w in values]
    prose = " ".join([card["summary"], *card["follow_up_questions"], *card["unknowns"], values]).lower()
    problems += [f"model text contains '{w}'" for w in expect.get("text_must_not_contain", [])
                 if re.search(rf"\b{re.escape(w)}\b", prose)]
    unverified = [f["label"] for f in card["facts"] if f["status"] == "unverified"]
    if unverified:
        problems.append(f"unverified facts: {unverified}")
    return problems


async def run(selected: list[str], single_call: bool = False) -> None:
    if not settings.gemini_configured:
        sys.exit("GEMINI_API_KEY is not set")
    version = re.search(r"version:\s*(v\d+)", PROMPT_PATH.read_text(encoding="utf-8")).group(1)
    cases = [c for c in json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
             if not selected or c["id"] in selected]
    client = GeminiClient(settings)
    results = []
    for case in cases:
        llm = RecordingLLM(client, max_calls=1 if single_call else None)
        card = await analyze(llm, case["text"], [])
        if not single_call and card.source == "fallback" and llm.log and not llm.log[-1]["ok"]:
            await asyncio.sleep(TRANSIENT_RETRY_DELAY_S)  # one retry for transient 503/429
            card = await analyze(llm, case["text"], [])
        card_d = card.model_dump()
        problems = check(card_d, case["expect"]) if card.source == "gemini" else ["FALLBACK - model unavailable"]
        results.append({"id": case["id"], "purpose": case["purpose"], "text": case["text"],
                        "calls": llm.log, "card": card_d, "problems": problems})
        print(f"\n=== {case['id']} [{card.source}] {'PASS' if not problems else 'ISSUES'}")
        ok_raw = [c["raw"] for c in llm.log if c["ok"]]
        if ok_raw:
            try:
                m = json.loads(ok_raw[-1])
                print(f"  MODEL: scope={m.get('scope')} type={m.get('incident_type')} "
                      f"severity={m.get('severity')} protocols={m.get('protocol_ids')}")
            except json.JSONDecodeError:
                print("  MODEL: (unparseable raw reply)")
        print(f"  FINAL: scope={card.scope} type={card.incident_type} severity={card.severity} "
              f"escalated={card.severity_escalated} red_flags={[f.id for f in card.red_flags]}")
        print(f"  protocols={[p.id for p in card.protocols]}")
        for f in card.facts:
            print(f"  fact [{f.status}] {f.label}: {f.value}  <- \"{f.quote}\"")
        print(f"  summary: {card.summary}")
        print(f"  questions: {card.follow_up_questions}")
        for p in problems:
            print(f"  ! {p}")

    out = ROOT / "results" / f"{version}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"prompt_version": version, "model": settings.gemini_model, "results": results},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    args = sys.argv[1:]
    # --single-call: exactly one real API call per case (no transient retry, no schema-repair retry)
    asyncio.run(run([a for a in args if a != "--single-call"], single_call="--single-call" in args))
