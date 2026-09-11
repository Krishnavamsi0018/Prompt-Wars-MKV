"""Final action generation, all deterministic: contacts, SOS message, map links."""

from urllib.parse import quote_plus

from app.protocols import Contact
from app.schemas import CardContact, CardFact, CardLink, RedFlag

DISCLAIMER = (
    "LifeBridge gives general safety guidance, not medical advice or a diagnosis. "
    "It does not contact emergency services for you. If anyone may be in danger, call 112."
)

INCIDENT_LABELS: dict[str, str] = {
    "medical": "Medical emergency",
    "injury_trauma": "Injury",
    "road_accident": "Road accident",
    "fire": "Fire",
    "drowning": "Drowning",
    "electrocution": "Electric shock",
    "violence_assault": "Violence / assault",
    "natural_disaster": "Natural disaster",
    "hazardous_material": "Hazardous material",
    "mental_health_crisis": "Mental health crisis",
    "other": "Emergency",
    "unknown": "Possible emergency",
}

MAX_SOS_FACTS = 6
MAX_SOS_USER_TEXT = 280


def card_contacts(contacts: list[Contact]) -> list[CardContact]:
    return [CardContact(name=c.name, number=c.number, tel=f"tel:{c.number}") for c in contacts]


def maps_point_url(lat: float, lng: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lng:.6f}"


def build_links(lat: float | None, lng: float | None) -> list[CardLink]:
    if lat is None or lng is None:
        return [CardLink(label="Find hospitals near me (Google Maps)",
                         url="https://www.google.com/maps/search/?api=1&query=" + quote_plus("hospitals near me"))]
    return [
        CardLink(label="My location (Google Maps)", url=maps_point_url(lat, lng)),
        CardLink(label="Hospitals near my location (Google Maps)",
                 url="https://www.google.com/maps/search/?api=1&query="
                 + quote_plus(f"hospitals near {lat:.6f},{lng:.6f}")),
    ]


def build_sos_message(
    incident_type: str,
    severity: str,
    red_flags: list[RedFlag],
    verified_facts: list[CardFact],
    lat: float | None,
    lng: float | None,
    user_text: str | None = None,
) -> str:
    """Built only from rule hits, code-verified facts, the user's own words and device location."""
    lines = [f"EMERGENCY - {INCIDENT_LABELS.get(incident_type, 'Emergency')} (severity: {severity.upper()})"]
    if red_flags:
        lines.append("Red flags: " + ", ".join(f.label for f in red_flags))
    lines += [f"- {f.label}: {f.value}" for f in verified_facts[:MAX_SOS_FACTS]]
    if user_text:
        clipped = user_text.strip()
        if len(clipped) > MAX_SOS_USER_TEXT:
            clipped = clipped[:MAX_SOS_USER_TEXT].rstrip() + "..."
        lines.append(f'Message: "{clipped}"')
    if lat is not None and lng is not None:
        lines.append(f"Location: {maps_point_url(lat, lng)}")
    lines.append("Sent via LifeBridge. Please send help.")
    return "\n".join(lines)
