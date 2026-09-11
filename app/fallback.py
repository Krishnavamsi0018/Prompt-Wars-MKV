"""Deterministic card used whenever Gemini cannot be used. It never needs the network."""

from app.actions import DISCLAIMER, build_links, build_sos_message, card_contacts
from app.protocols import PROTOCOLS, contacts_for
from app.schemas import ActionCard, CardProtocol, RedFlag
from app.verify import Rule, severity_floor

FALLBACK_QUESTIONS = [
    "Where exactly are you? (address or landmark)",
    "Is the person awake and breathing normally?",
    "How many people are hurt?",
]


def build_fallback_card(
    text: str, rules: list[Rule], lat: float | None, lng: float | None, reason: str
) -> ActionCard:
    floor = severity_floor(rules)
    incident_type = next((r.incident_type for r in rules if r.incident_type), "unknown")
    protocol_ids = list(dict.fromkeys(r.protocol_id for r in rules if r.protocol_id)) or ["general_safety"]
    red_flags = [RedFlag(id=r.id, label=r.label) for r in rules]

    if floor == "critical":
        scope = "emergency"
    elif rules:
        scope = "urgent"
    else:
        scope = "unknown"

    return ActionCard(
        source="fallback",
        scope=scope,
        incident_type=incident_type,
        severity=floor,
        severity_escalated=False,
        summary="Automatic analysis is unavailable. If anyone is in danger, call 112 now.",
        language="unknown",
        red_flags=red_flags,
        facts=[],
        protocols=[CardProtocol(id=p, title=PROTOCOLS[p].title, steps=list(PROTOCOLS[p].steps))
                   for p in protocol_ids[:4]],
        contacts=card_contacts(contacts_for(incident_type, *(r.incident_type for r in rules if r.incident_type))),
        follow_up_questions=FALLBACK_QUESTIONS,
        unknowns=[],
        sos_message=build_sos_message(incident_type, floor, red_flags, [], lat, lng, user_text=text),
        links=build_links(lat, lng),
        notices=[reason + " Showing safety guidance based on keywords in your message."],
        disclaimer=DISCLAIMER,
    )
