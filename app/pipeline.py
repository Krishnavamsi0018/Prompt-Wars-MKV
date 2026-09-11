"""Orchestration: rules -> Gemini -> schema validation (1 retry) -> deterministic verification -> ActionCard.

Kept separate from main.py so it can be tested without HTTP and with a fake model.
"""

import asyncio
import logging
import re

from pydantic import ValidationError

from app.actions import DISCLAIMER, build_links, build_sos_message, card_contacts
from app.config import settings
from app.fallback import build_fallback_card
from app.gemini_client import LLM, MIN_ATTEMPT_BUDGET_S, VALIDATION_RESERVE_S, LLMError
from app.protocols import PROTOCOLS, contacts_for
from app.schemas import ActionCard, CardFact, CardProtocol, GeminiAssessment, RedFlag
from app.verify import (
    Rule,
    fact_status,
    faithful_value,
    raise_severity,
    sanitize_free_text,
    scan_red_flags,
    severity_floor,
    unsupported_claims,
)

log = logging.getLogger("lifebridge")

MAX_PROTOCOLS = 4
# A repair call is only worth starting if a model attempt can still finish and be validated in time.
MIN_REPAIR_BUDGET_S = MIN_ATTEMPT_BUDGET_S + VALIDATION_RESERVE_S
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_assessment(raw: str) -> GeminiAssessment:
    return GeminiAssessment.model_validate_json(_FENCE.sub("", raw))


def _correction_message(err: ValidationError) -> str:
    problems = "; ".join(
        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in err.errors(include_input=False)[:6]
    )
    return (
        f"Your previous reply did not match the required schema ({problems}). "
        "Return only corrected JSON that matches the schema exactly."
    )


async def analyze(
    llm: LLM | None,
    text: str,
    images: list[tuple[bytes, str]],
    lat: float | None = None,
    lng: float | None = None,
    budget_s: float | None = None,
) -> ActionCard:
    rules = scan_red_flags(text)

    if llm is None:
        log.warning("analyze outcome=fallback reason=not_configured")
        return build_fallback_card(text, rules, lat, lng, "AI analysis is not configured on this server.")

    # ONE deadline for the whole Gemini step: first call, model failover AND the schema-repair call.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + (settings.gemini_timeout_s if budget_s is None else budget_s)

    correction: str | None = None
    for attempt in (1, 2):
        if attempt == 2 and deadline - loop.time() < MIN_REPAIR_BUDGET_S:
            log.warning("analyze outcome=fallback reason=no_time_for_repair")
            return build_fallback_card(text, rules, lat, lng, "AI returned an unreadable answer.")
        try:
            raw = await llm.generate(text, images, correction, deadline=deadline)
        except LLMError as exc:
            log.warning("analyze outcome=fallback reason=llm_error:%s attempt=%d", exc, attempt)
            return build_fallback_card(text, rules, lat, lng, "AI analysis is unavailable right now.")
        try:
            assessment = parse_assessment(raw)
        except ValidationError as exc:
            log.warning("analyze invalid_output attempt=%d errors=%d", attempt, exc.error_count())
            correction = _correction_message(exc)
            continue
        card = build_card(assessment, text, bool(images), rules, lat, lng)
        log.info(
            "analyze outcome=gemini attempt=%d severity=%s escalated=%s facts=%d verified=%d",
            attempt, card.severity, card.severity_escalated, len(card.facts),
            sum(f.status == "verified" for f in card.facts),
        )
        return card

    return build_fallback_card(text, rules, lat, lng, "AI returned an unreadable answer twice.")


def _merge_protocols(model_ids: list[str], rules: list[Rule], scope: str) -> list[str]:
    critical_rule_ids = [r.protocol_id for r in rules if r.protocol_id and r.severity == "critical"]
    other_rule_ids = [r.protocol_id for r in rules if r.protocol_id and r.severity != "critical"]
    ids = list(dict.fromkeys([*critical_rule_ids, *model_ids, *other_rule_ids]))
    if len(ids) > 1 and "general_safety" in ids:
        ids.remove("general_safety")
    # Generic "Stay safe" steps only make sense for real emergencies; they were noise on a small cut (eval v1).
    if not ids and scope in ("emergency", "urgent"):
        ids = ["general_safety"]
    if scope not in ("emergency", "urgent") and ids == ["general_safety"]:
        ids = []
    return ids[:MAX_PROTOCOLS]


def build_card(
    a: GeminiAssessment,
    text: str,
    has_images: bool,
    rules: list[Rule],
    lat: float | None,
    lng: float | None,
) -> ActionCard:
    facts: list[CardFact] = []
    for f in a.facts:
        status = fact_status(f, text, has_images)
        if status == "verified":
            value = faithful_value(f.value, f.quote, text)
        elif status == "visual":
            value = f.value
        else:
            value = sanitize_free_text(f.value)
        facts.append(CardFact(**f.model_dump(exclude={"value"}), value=value, status=status))

    floor = severity_floor(rules)
    severity = raise_severity(a.severity, floor)
    escalated = severity != a.severity

    scope = a.scope
    if floor == "critical":
        scope = "emergency"
    elif rules and scope in ("non_urgent", "out_of_scope"):
        scope = "urgent"

    incident_type = a.incident_type
    if incident_type in ("unknown", "other"):
        incident_type = next((r.incident_type for r in rules if r.incident_type), incident_type)

    protocol_ids = _merge_protocols(list(a.protocol_ids), rules, scope)
    red_flags = [RedFlag(id=r.id, label=r.label) for r in rules]

    notices: list[str] = []
    if escalated:
        notices.append(
            "Safety rules raised the severity because your message mentions: "
            + ", ".join(r.label.lower() for r in rules) + "."
        )
    if any(f.status == "unverified" for f in facts):
        notices.append("Some details could not be matched to your words. They are marked 'Not verified'.")
    if any(f.status == "visual" for f in facts):
        notices.append("Details seen in photos are marked 'From photo' - please confirm them.")

    verified = [f for f in facts if f.status == "verified"]

    # The summary is model prose: if it overstates the user's words (eval v1: "not answering" -> "unresponsive"),
    # replace it with one built from the verified facts.
    summary = sanitize_free_text(a.summary)
    if unsupported_claims(summary, text):
        log.info("summary replaced: unsupported claims=%s", unsupported_claims(summary, text))
        summary = ("Reported: " + "; ".join(f.value.rstrip(". ") for f in verified[:4]) + ".") if verified else (
            "Please check the details below.")

    return ActionCard(
        source="gemini",
        scope=scope,
        incident_type=incident_type,
        severity=severity,
        severity_escalated=escalated,
        summary=summary,
        language=a.language,
        red_flags=red_flags,
        facts=facts,
        protocols=[CardProtocol(id=p, title=PROTOCOLS[p].title, steps=list(PROTOCOLS[p].steps)) for p in protocol_ids],
        contacts=card_contacts(contacts_for(incident_type, *(r.incident_type for r in rules if r.incident_type))),
        follow_up_questions=[sanitize_free_text(q) for q in a.follow_up_questions],
        unknowns=[sanitize_free_text(u) for u in a.unknowns],
        sos_message=build_sos_message(incident_type, severity, red_flags, verified, lat, lng),
        links=build_links(lat, lng),
        notices=notices,
        disclaimer=DISCLAIMER,
    )
