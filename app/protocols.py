"""Vetted, fixed action content. Gemini may only SELECT from these IDs; it never writes the steps.

Content is adapted from widely published public first-aid guidance (hands-only CPR, direct pressure
for bleeding, cool running water for burns, FAST for stroke, etc.). It is deliberately conservative and
contains no drug names or doses. It has NOT been reviewed by a medical professional - see README.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Protocol:
    id: str
    title: str
    when: str  # shown to Gemini in the prompt catalogue so it can choose correctly
    steps: tuple[str, ...]


PROTOCOLS: dict[str, Protocol] = {
    p.id: p
    for p in (
        Protocol(
            "unresponsive_person",
            "Person not responding",
            "someone is unconscious, unresponsive, collapsed, or not breathing normally",
            (
                "Shout and tap their shoulders. If there is no response, call 112 or ask someone to call.",
                "Check breathing for up to 10 seconds: look at the chest, listen, feel for breath.",
                "If NOT breathing normally: push hard and fast in the centre of the chest "
                "(about 2 pushes per second) and do not stop until help arrives.",
                "If a defibrillator (AED) is available, switch it on and follow its voice instructions.",
                "If they ARE breathing: roll them onto their side (recovery position) and keep checking breathing.",
            ),
        ),
        Protocol(
            "severe_bleeding",
            "Heavy bleeding",
            "heavy, spurting or uncontrolled bleeding, or a deep wound",
            (
                "Press firmly on the wound with a clean cloth or your hand. Keep pressing.",
                "If blood soaks through, add more cloth on top. Do not lift the first cloth.",
                "Keep the person lying down and warm.",
                "Do not pull out any object stuck in the wound; press around it instead.",
            ),
        ),
        Protocol(
            "burns",
            "Burns",
            "burns from fire, hot liquid, chemicals or electricity",
            (
                "Cool the burn under cool running water for 20 minutes.",
                "Remove rings, watches or tight clothing near the burn, unless stuck to the skin.",
                "Cover loosely with cling film or a clean, non-fluffy cloth.",
                "Do not put ice, butter, toothpaste or oil on the burn.",
            ),
        ),
        Protocol(
            "choking",
            "Choking",
            "someone is choking or has something stuck in their throat",
            (
                "If they can cough, encourage them to keep coughing.",
                "If they cannot cough, speak or breathe: give up to 5 firm back blows between the shoulder blades.",
                "Then give up to 5 abdominal thrusts (quick inward and upward pulls above the navel).",
                "Repeat back blows and thrusts. If they become unresponsive, call 112 and start chest pushes.",
            ),
        ),
        Protocol(
            "stroke_fast",
            "Possible stroke (FAST)",
            "face drooping, arm weakness, slurred or confused speech, sudden one-sided weakness",
            (
                "Face: is one side drooping? Arms: can they raise both? Speech: is it slurred or strange?",
                "Time: if any sign is present, call 112 now. Note the time symptoms started.",
                "Do not give them anything to eat or drink.",
                "Keep them comfortable and stay with them until help arrives.",
            ),
        ),
        Protocol(
            "chest_pain",
            "Chest pain",
            "chest pain, pressure or tightness, or a suspected heart attack",
            (
                "Call 112 or 108 for an ambulance now.",
                "Help them sit down and rest in a comfortable position. Loosen tight clothing.",
                "Do not let them walk around or exert themselves.",
                "If they become unresponsive and stop breathing normally, start chest pushes.",
            ),
        ),
        Protocol(
            "seizure",
            "Seizure / fits",
            "a seizure, convulsions or fits",
            (
                "Move hard or sharp objects away. Cushion their head.",
                "Do not hold them down and do not put anything in their mouth.",
                "Time the seizure. Call 112 if it lasts more than 5 minutes or they are injured.",
                "When the shaking stops, roll them onto their side and stay with them.",
            ),
        ),
        Protocol(
            "road_accident",
            "Road accident scene",
            "a road traffic accident or someone hit by a vehicle",
            (
                "Keep yourself safe: stay off the traffic lane and warn other vehicles.",
                "Do not move injured people unless they are in immediate danger (fire, traffic).",
                "Do not remove a rider's helmet.",
                "Switch off vehicle engines if it is safe to do so.",
            ),
        ),
        Protocol(
            "fire_evacuation",
            "Fire",
            "fire, smoke or a burning building or vehicle",
            (
                "Get everyone out now. Do not stop to collect belongings.",
                "Stay low under smoke. Do not use lifts.",
                "Close doors behind you to slow the fire.",
                "Do not go back inside. Call 101 (fire) or 112 once you are safe.",
            ),
        ),
        Protocol(
            "drowning",
            "Drowning",
            "someone drowning or pulled from water",
            (
                "Do not jump in unless trained. Reach with a stick or throw something that floats.",
                "Once out of the water, check breathing.",
                "If NOT breathing normally, call 112 and start chest pushes.",
                "Keep them warm, even if they seem to recover.",
            ),
        ),
        Protocol(
            "electrocution",
            "Electric shock",
            "an electric shock or contact with a live wire",
            (
                "Do NOT touch the person while they are still in contact with the power source.",
                "Switch off the power at the mains if you can, or push the source away with dry wood or plastic.",
                "Once safe, check breathing. If NOT breathing normally, start chest pushes.",
                "Treat any burns with cool running water.",
            ),
        ),
        Protocol(
            "heatstroke",
            "Heat stroke",
            "heat stroke or heat exhaustion: very hot skin, confusion or collapse in heat",
            (
                "Move them to a cool, shaded place.",
                "Remove extra clothing. Cool them with water on the skin and fanning.",
                "If they are fully awake, give small sips of water.",
                "If they become confused or unresponsive, call 112.",
            ),
        ),
        Protocol(
            "personal_safety",
            "Personal safety",
            "violence, assault, threats, being followed, or any danger from another person",
            (
                "Get to a safe, public or locked place if you can.",
                "Call 112 (police). Women can also call 1091.",
                "Do not confront the attacker.",
                "Share your live location with someone you trust.",
            ),
        ),
        Protocol(
            "mental_health_crisis",
            "Mental health crisis",
            "thoughts of suicide, self-harm, or a severe emotional crisis",
            (
                "If life is in immediate danger, call 112 now.",
                "Stay with the person. Listen without judging.",
                "Remove anything they could use to hurt themselves, if it is safe to do so.",
                "Call Tele-MANAS (14416) for free, confidential mental health support.",
            ),
        ),
        Protocol(
            "general_safety",
            "Stay safe",
            "any emergency where no more specific card applies",
            (
                "Make sure you are safe before helping anyone.",
                "If anyone may be in danger, call 112.",
                "Do not move an injured person unless they are in immediate danger.",
                "Keep the person warm and stay with them until help arrives.",
            ),
        ),
    )
}

PROTOCOL_IDS: tuple[str, ...] = tuple(PROTOCOLS)


@dataclass(frozen=True)
class Contact:
    id: str
    name: str
    number: str


# Fixed India emergency numbers. Gemini never produces phone numbers.
CONTACTS: dict[str, Contact] = {
    c.id: c
    for c in (
        Contact("emergency", "National emergency", "112"),
        Contact("ambulance", "Ambulance", "108"),
        Contact("fire", "Fire", "101"),
        Contact("police", "Police", "100"),
        Contact("women", "Women helpline", "1091"),
        Contact("mental_health", "Tele-MANAS mental health", "14416"),
    )
}

_INCIDENT_CONTACTS: dict[str, tuple[str, ...]] = {
    "medical": ("ambulance",),
    "injury_trauma": ("ambulance",),
    "road_accident": ("ambulance", "police"),
    "fire": ("fire", "ambulance"),
    "drowning": ("ambulance",),
    "electrocution": ("ambulance",),
    "violence_assault": ("police", "women"),
    "natural_disaster": ("fire", "ambulance"),
    "hazardous_material": ("fire", "ambulance"),
    "mental_health_crisis": ("mental_health",),
}


def contacts_for(*incident_types: str) -> list[Contact]:
    """112 always comes first; numbers for every detected incident type follow (e.g. fire + medical)."""
    ids = ["emergency"]
    for incident in incident_types or ("unknown",):
        ids += _INCIDENT_CONTACTS.get(incident, ("ambulance",))
    return [CONTACTS[i] for i in dict.fromkeys(ids)]


def protocol_catalog() -> str:
    """Rendered into the system prompt so the model knows when each ID applies."""
    return "\n".join(f"- {p.id}: {p.when}" for p in PROTOCOLS.values())
