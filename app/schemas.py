"""Two contracts:
- GeminiAssessment: what the model must return (also sent to Gemini as response_schema).
- ActionCard: what the API returns to the browser, built by deterministic code.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.protocols import PROTOCOL_IDS

Scope = Literal["emergency", "urgent", "non_urgent", "out_of_scope"]
IncidentType = Literal[
    "medical",
    "injury_trauma",
    "road_accident",
    "fire",
    "drowning",
    "electrocution",
    "violence_assault",
    "natural_disaster",
    "hazardous_material",
    "mental_health_crisis",
    "other",
    "unknown",
]
Severity = Literal["unknown", "low", "moderate", "high", "critical"]
FactCategory = Literal["condition", "injury", "location", "people", "hazard", "time", "medical_history", "other"]
FactSource = Literal["text", "image"]
Confidence = Literal["high", "medium", "low"]
# Literal built from the vetted catalogue: Gemini cannot return an ID we don't have content for.
ProtocolId = Literal[PROTOCOL_IDS]  # type: ignore[valid-type]

SEVERITY_ORDER: tuple[str, ...] = ("unknown", "low", "moderate", "high", "critical")


# ---------- Model output contract ----------


class ExtractedFact(BaseModel):
    category: FactCategory
    label: str = Field(max_length=60, description="Short name, e.g. 'Breathing', 'Location'")
    value: str = Field(max_length=200, description="What the input says, in plain words")
    source: FactSource
    quote: str = Field(
        max_length=300,
        description="source=text: exact words copied from the user's text. source=image: what is visible.",
    )
    confidence: Confidence


class GeminiAssessment(BaseModel):
    scope: Scope
    incident_type: IncidentType
    severity: Severity
    summary: str = Field(max_length=400)
    language: str = Field(max_length=20, description="Language of the user's input, e.g. 'en', 'hi', 'kn'")
    facts: list[ExtractedFact] = Field(max_length=12)
    protocol_ids: list[ProtocolId] = Field(max_length=4)
    follow_up_questions: list[str] = Field(max_length=3)
    unknowns: list[str] = Field(max_length=5)


# ---------- API response contract ----------

FactStatus = Literal["verified", "visual", "unverified"]


class CardFact(BaseModel):
    category: FactCategory
    label: str
    value: str
    source: FactSource
    quote: str
    confidence: Confidence
    status: FactStatus


class RedFlag(BaseModel):
    id: str
    label: str


class CardProtocol(BaseModel):
    id: str
    title: str
    steps: list[str]


class CardContact(BaseModel):
    name: str
    number: str
    tel: str


class CardLink(BaseModel):
    label: str
    url: str


class ActionCard(BaseModel):
    source: Literal["gemini", "fallback"]
    scope: Scope | Literal["unknown"]  # "unknown" only when the model could not be used
    incident_type: IncidentType
    severity: Severity
    severity_escalated: bool = Field(description="True when safety rules raised the model's severity")
    summary: str
    language: str
    red_flags: list[RedFlag]
    facts: list[CardFact]
    protocols: list[CardProtocol]
    contacts: list[CardContact]
    follow_up_questions: list[str]
    unknowns: list[str]
    sos_message: str
    links: list[CardLink]
    notices: list[str]
    disclaimer: str
