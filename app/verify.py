"""Deterministic verification: evidence grounding, red-flag safety rules, output sanitising.

Nothing in here calls the model, so all of it still works when Gemini is down.
"""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.schemas import SEVERITY_ORDER, ExtractedFact, FactStatus

# ---------- Evidence grounding ----------

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
FUZZY_THRESHOLD = 0.85  # tolerate small typo corrections by the model, not paraphrases
MIN_QUOTE_CHARS = 3


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _NON_WORD.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def quote_in_text(quote: str, text: str) -> bool:
    q, t = normalize(quote), normalize(text)
    if len(q) < MIN_QUOTE_CHARS or not t:
        return False
    if q in t:
        return True
    # Fuzzy, word by word, so a model that silently fixed a typo ("hebal" -> "hebbal") still verifies,
    # but a changed meaning ("conscious" -> "unconscious", "not" dropped) never does.
    q_words, t_words = q.split(), t.split()
    n = len(q_words)
    return any(
        all(_word_close(a, b) for a, b in zip(q_words, t_words[i : i + n], strict=True))
        for i in range(len(t_words) - n + 1)
    )


_NEGATIONS = frozenset({"not", "no", "never", "nahi", "nahin", "mat", "नहीं", "न", "मत"})


def _word_close(a: str, b: str) -> bool:
    if a == b:
        return True
    if a in _NEGATIONS or b in _NEGATIONS or min(len(a), len(b)) < 4 or a[:2] != b[:2]:
        return False
    return SequenceMatcher(None, a, b, autojunk=False).ratio() >= FUZZY_THRESHOLD


def fact_status(fact: ExtractedFact, user_text: str, has_images: bool) -> FactStatus:
    if fact.source == "text":
        return "verified" if quote_in_text(fact.quote, user_text) else "unverified"
    # Image observations cannot be checked by code: they are labelled for human confirmation.
    return "visual" if has_images else "unverified"


# Clinical/escalating claims a model may "upgrade" a report into (e.g. "not answering" -> "unresponsive").
STRONG_CLAIMS: tuple[str, ...] = (
    "unresponsive", "unconscious", "not breathing", "stopped breathing", "cardiac arrest", "heart attack",
    "stroke", "seizure", "fracture", "broken", "concussion", "dead", "died", "deceased", "paralysed",
    "paralyzed", "internal bleeding", "severe", "heavy", "critical", "life threatening", "poisoned", "overdose",
)


def faithful_value(value: str, quote: str, user_text: str) -> str:
    """Keep a verified fact no stronger than the user's words.

    If the model's value contains a strong claim that the user never wrote, fall back to the user's own
    (already verified) quote, e.g. "Father is unresponsive" -> "He is not answering".
    """
    v, t = f" {normalize(value)} ", f" {normalize(user_text)} "
    if any(f" {c} " in v and f" {c} " not in t for c in STRONG_CLAIMS):
        words = quote.strip().strip(".,;:!?\"'“”").strip()
        return words[:1].upper() + words[1:]
    return value


# ---------- Red-flag safety rules ----------


@dataclass(frozen=True)
class Rule:
    id: str
    label: str
    severity: str
    pattern: re.Pattern[str]
    protocol_id: str | None = None
    incident_type: str | None = None


def _rx(*alternatives: str) -> re.Pattern[str]:
    return re.compile("|".join(alternatives), re.IGNORECASE | re.UNICODE)


# English + common Hindi (romanised and Devanagari) phrasings. Rules can only RAISE severity.
RULES: tuple[Rule, ...] = (
    Rule("not_breathing", "Not breathing", "critical",
         _rx(r"\bnot breathing\b", r"\bstopped breathing\b", r"\bno breath", r"\bisn'?t breathing\b",
             r"saa?ns? nahi", r"साँस नहीं", r"सांस नहीं"),
         "unresponsive_person", "medical"),
    Rule("unresponsive", "Not responding", "critical",
         _rx(r"\bunconscious\b", r"\bunresponsive\b", r"\bpassed out\b", r"\bcollapsed\b", r"\bfainted\b",
             # "not answering / doesn't respond" - but not "not answering my calls / the door"
             r"\b(not|isn'?t|is not|doesn'?t|does not|won'?t|will not|can'?t|cannot)\s+"
             r"(answer(ing)?|respond(ing)?|wak(e|ing)(\s+up)?)\b"
             r"(?!\s+(to\s+)?(my|his|her|their|our|the|a)?\s*(phone|calls?|texts?|messages?|door|emails?))",
             r"\bno response\b", r"\bbehosh\b", r"बेहोश", r"\bjawab nahi", r"जवाब नहीं"),
         "unresponsive_person", "medical"),
    Rule("breathing_difficulty", "Difficulty breathing", "critical",
         _rx(r"\bcan'?t breathe\b", r"\bcannot breathe\b", r"\bstruggling to breathe\b",
             r"\bgasping\b", r"\bshortness of breath\b"),
         None, "medical"),
    Rule("heavy_bleeding", "Heavy bleeding", "critical",
         _rx(r"\b(heavy|heavily|severe|profuse|uncontrolled|spurting|lots? of|a lot of|so much)\s+(bleeding|blood)\b",
             r"\bbleeding (heavily|badly|a lot|profusely)\b", r"\bwon'?t stop bleeding\b",
             r"\bblood everywhere\b", r"\bbahut khoon\b", r"बहुत खून"),
         "severe_bleeding", "injury_trauma"),
    Rule("chest_pain", "Chest pain", "critical",
         _rx(r"\bchest pain\b", r"\bpain in (his|her|their|my) chest\b", r"\bchest (tightness|pressure)\b",
             r"\bheart attack\b", r"seene m(ei|e)n dard", r"सीने में दर्द"),
         "chest_pain", "medical"),
    Rule("stroke_signs", "Possible stroke signs", "critical",
         _rx(r"(?<!heat )\bstroke\b", r"\bface (is )?drooping\b", r"\bslurred speech\b", r"\bslurring\b",
             r"\bone side (of (his|her|their) body )?(is )?(weak|numb|paralys)"),
         "stroke_fast", "medical"),
    Rule("choking", "Choking", "critical",
         _rx(r"\bchoking\b", r"\bchoked\b", r"\bstuck in (his|her|their|my) throat\b"),
         "choking", "medical"),
    Rule("drowning", "Drowning", "critical",
         _rx(r"\bdrown", r"\bdoob", r"डूब"),
         "drowning", "drowning"),
    Rule("fire", "Fire", "critical",
         _rx(r"\bfire\b", r"\bon fire\b", r"\bflames?\b", r"\bburning (building|house|car|vehicle)\b",
             r"\baag\b", r"आग"),
         "fire_evacuation", "fire"),
    Rule("electrocution", "Electric shock", "critical",
         _rx(r"\belectrocut", r"\belectric shock\b", r"\blive wire\b", r"\bcurrent (laga|lag gaya)\b", r"करंट"),
         "electrocution", "electrocution"),
    Rule("self_harm", "Risk of suicide or self-harm", "critical",
         _rx(r"\bsuicid", r"\bkill (myself|himself|herself|themselves)\b", r"\bend (my|his|her|their) life\b",
             r"\bself[- ]harm", r"\bwant to die\b", r"\bkhudkushi\b", r"आत्महत्या"),
         "mental_health_crisis", "mental_health_crisis"),
    Rule("weapon_violence", "Weapon / serious violence", "critical",
         _rx(r"\bstabbed\b", r"\bgunshot\b", r"\bshot (at|by)\b", r"\bhas a (knife|gun)\b"),
         "personal_safety", "violence_assault"),
    Rule("poisoning", "Possible poisoning / overdose", "critical",
         _rx(r"\bpoison", r"\boverdose\b", r"\bswallowed (bleach|pesticide|acid|pills)\b", r"\bzeh?er\b", r"ज़हर|जहर"),
         None, "medical"),
    Rule("seizure", "Seizure", "high",
         _rx(r"\bseizure", r"\bconvuls", r"\bhaving (a )?fits?\b", r"\bmirgi\b", r"मिर्गी"),
         "seizure", "medical"),
    Rule("heatstroke", "Possible heat stroke", "high",
         _rx(r"\bheat ?stroke\b", r"\bsunstroke\b", r"\bloo lag"),
         "heatstroke", "medical"),
    Rule("burn", "Burn", "high",
         _rx(r"\bburn(s|ed|t)?\b", r"\bscald", r"\bjal gaya\b", r"जल गया"),
         "burns", "injury_trauma"),
    Rule("road_accident", "Road accident", "high",
         _rx(r"\baccident\b", r"\bhit by (a |an )?(car|bus|truck|lorry|bike|auto|vehicle)\b",
             r"\bcrash(ed)?\b", r"\bcollision\b", r"दुर्घटना"),
         "road_accident", "road_accident"),
    Rule("violence", "Threat or assault", "high",
         _rx(r"\battack(ed|ing)?\b", r"\bassault", r"\bbeing followed\b", r"\bharass", r"\bthreaten"),
         "personal_safety", "violence_assault"),
)


def scan_red_flags(text: str) -> list[Rule]:
    return [rule for rule in RULES if rule.pattern.search(text)]


def severity_floor(rules: list[Rule]) -> str:
    return max((r.severity for r in rules), key=SEVERITY_ORDER.index, default="unknown")


def raise_severity(model_severity: str, floor: str) -> str:
    """Never lowers: the result is the higher of the model's and the rules' severity."""
    return max(model_severity, floor, key=SEVERITY_ORDER.index)


# ---------- Free-text sanitising (defence in depth; the prompt already forbids these) ----------

_DOSAGE = re.compile(r"\b\d+(\.\d+)?\s?(mg|mcg|µg|g|ml|iu|units?|tablets?|tabs?|pills?|drops?)\b", re.IGNORECASE)
_PHONE_LIKE = re.compile(r"(?<!\w)\+?\d[\d\s-]{4,}\d(?!\w)")  # 6+ chars: leaves ages, years, 112


def sanitize_free_text(text: str) -> str:
    """Strip anything that looks like a dose or a phone number from model-written prose.

    Phone numbers shown to users only ever come from the fixed CONTACTS table.
    """
    text = _DOSAGE.sub("[dose removed]", text)
    return _PHONE_LIKE.sub("[number removed]", text)
