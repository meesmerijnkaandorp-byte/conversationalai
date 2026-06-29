from __future__ import annotations

import json
import os
import re
from typing import Any

from pydantic import BaseModel, Field

from .order import missing_required, normalize_language


class OrderPatch(BaseModel):
    theme: str | None = Field(default=None, description="Klantthema, niche of branche")
    language: str | None = Field(default=None, description="Gewenste publicatietaal")
    min_dr: int | None = Field(default=None, ge=0, le=100, description="Minimale Domain Rating")
    min_traffic: int | None = Field(default=None, ge=0, description="Minimaal maandelijks organisch verkeer")
    target_url: str | None = Field(default=None, description="URL waarnaar gelinkt moet worden")
    anchor_text: str | None = Field(default=None, description="Gewenste anchor text")
    quantity: int | None = Field(default=None, ge=1, description="Aantal plaatsingen")
    budget_eur: int | None = Field(default=None, ge=0, description="Maximaal budget in euro")
    notes: str | None = Field(default=None, description="Extra wensen, restricties of opmerkingen")


class AgentDecision(BaseModel):
    patch: OrderPatch = Field(default_factory=OrderPatch)
    assistant_reply: str = Field(description="Kort Nederlandstalig antwoord met maximaal een vervolgvraag")


SYSTEM_PROMPT = """
Je bent een Nederlandstalige intake-agent voor een linkbuilding/mediabuying marketplace.
Je doel is om via chat een conceptorder op te bouwen.

Verzamel minimaal deze velden:
- theme: thema/niche van de klant
- language: gewenste taal
- min_dr: minimale Domain Rating, 0-100
- min_traffic: minimale maandelijkse traffic
- target_url: landingspagina
- anchor_text: gewenste anchor text
- quantity: aantal plaatsingen

budget_eur en notes zijn optioneel.
Update alleen velden die de gebruiker expliciet noemt of corrigeert.
Stel maximaal een concrete vervolgvraag tegelijk.
Noem geen garanties over rankings, traffic of indexatie.
Gebruik inventory_matches alleen om haalbaarheid kort te duiden.
Antwoord in het Nederlands.
""".strip()

LANGUAGE_PATTERNS = {
    "Dutch": [r"\bnederlands\b", r"\bdutch\b", r"\bnl\b"],
    "English": [r"\bengels\b", r"\benglish\b", r"\ben\b"],
    "German": [r"\bduits\b", r"\bgerman\b", r"\bde\b"],
    "French": [r"\bfrans\b", r"\bfrench\b", r"\bfr\b"],
    "Spanish": [r"\bspaans\b", r"\bspanish\b", r"\bes\b"],
}

QUESTION_BY_FIELD = {
    "theme": "Wat is het thema of de niche van de klant?",
    "language": "In welke taal moeten de plaatsingen zijn?",
    "min_dr": "Wat is de minimale DR die je wilt hanteren?",
    "min_traffic": "Wat is de minimale maandelijkse traffic per domein?",
    "target_url": "Wat is de target URL waar de links naartoe moeten?",
    "anchor_text": "Welke anchor text wil je gebruiken?",
    "quantity": "Hoeveel plaatsingen wil je inkopen?",
}


def get_agent_decision(
    messages: list[dict[str, str]],
    order: dict[str, Any],
    inventory_matches: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_user_message = _latest_user_message(messages)
    if os.getenv("OPENAI_API_KEY"):
        try:
            return _openai_decision(messages, order, inventory_matches, latest_user_message)
        except Exception as exc:  # POC: keep the order flow usable when the API is unavailable.
            decision = _fallback_decision(latest_user_message, order)
            decision["assistant_reply"] += f"\n\n_Let op: ik val tijdelijk terug op mock mode omdat de AI-call faalde ({type(exc).__name__})._"
            return decision
    return _fallback_decision(latest_user_message, order)


def _openai_decision(
    messages: list[dict[str, str]],
    order: dict[str, Any],
    inventory_matches: list[dict[str, Any]],
    latest_user_message: str,
) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI()
    context = {
        "current_order": order,
        "missing_required_fields": missing_required(order),
        "latest_user_message": latest_user_message,
        "conversation_tail": messages[-10:],
        "inventory_matches": inventory_matches,
    }
    response = client.responses.parse(
        model=os.getenv("OPENAI_MODEL", "gpt-5.5"),
        instructions=SYSTEM_PROMPT,
        input=json.dumps(context, ensure_ascii=False),
        text_format=AgentDecision,
    )
    parsed: AgentDecision = response.output_parsed
    return parsed.model_dump()


def _fallback_decision(user_text: str, order: dict[str, Any]) -> dict[str, Any]:
    patch = _extract_patch(user_text)
    simulated_order = {**order}
    for key, value in patch.items():
        if value not in (None, ""):
            simulated_order[key] = value
    still_missing = missing_required(simulated_order)

    if still_missing:
        next_field = still_missing[0]
        reply = f"Genoteerd. {QUESTION_BY_FIELD[next_field]}"
    else:
        reply = (
            "Mooi, ik heb genoeg informatie voor een conceptorder. "
            "Controleer rechts de geselecteerde publishers en maak de conceptorder aan, "
            "of typ 'bevestig order' in de chat."
        )

    return {"patch": patch, "assistant_reply": reply}


def _latest_user_message(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content", "")
    return ""


def _extract_patch(text: str) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    lower = text.lower()

    url_match = re.search(r"https?://[^\s,;]+", text)
    if url_match:
        patch["target_url"] = url_match.group(0).rstrip(").]")

    for language, patterns in LANGUAGE_PATTERNS.items():
        if any(re.search(pattern, lower) for pattern in patterns):
            patch["language"] = normalize_language(language)
            break

    min_dr = _extract_number_after_keywords(
        lower,
        [r"dr", r"domain rating", r"domein rating", r"domeinwaarde"],
        max_value=100,
    )
    if min_dr is not None:
        patch["min_dr"] = min_dr

    min_traffic = _extract_number_after_keywords(
        lower,
        [r"traffic", r"verkeer", r"bezoekers", r"visits", r"maandelijkse traffic"],
    )
    if min_traffic is not None:
        patch["min_traffic"] = min_traffic

    budget = _extract_budget(lower)
    if budget is not None:
        patch["budget_eur"] = budget

    quantity = _extract_quantity(lower)
    if quantity is not None:
        patch["quantity"] = quantity

    theme = _extract_text_after_label(text, ["thema", "niche", "onderwerp", "branche"])
    if theme:
        patch["theme"] = theme

    anchor = _extract_text_after_label(text, ["anchor", "anker", "anchortekst", "anchor text"])
    if anchor:
        patch["anchor_text"] = anchor

    notes = _extract_notes(text)
    if notes:
        patch["notes"] = notes

    return patch


def _extract_number_after_keywords(text: str, keywords: list[str], max_value: int | None = None) -> int | None:
    number_pattern = r"(\d{1,3}(?:[\.,]\d{3})+|\d+(?:[\.,]\d+)?\s*k?)"
    for keyword in keywords:
        patterns = [
            rf"(?:min(?:imaal)?\s*)?{keyword}\s*(?:van|is|=|>=|>|min(?:imaal)?)?\s*{number_pattern}",
            rf"{number_pattern}\s*(?:\+|plus)?\s*{keyword}",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                number = _parse_number(match.group(1))
                if number is None:
                    continue
                if max_value is not None:
                    number = min(number, max_value)
                return number
    return None


def _extract_budget(text: str) -> int | None:
    number_pattern = r"(\d{1,3}(?:[\.,]\d{3})+|\d+(?:[\.,]\d+)?\s*k?)"
    patterns = [
        rf"(?:budget|maximaal|max|tot|ongeveer|rond)\s*(?:€|eur)?\s*{number_pattern}",
        rf"(?:€|eur)\s*{number_pattern}",
        rf"{number_pattern}\s*(?:euro|eur)\s*(?:budget|max)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _parse_number(match.group(1))
    return None


def _extract_quantity(text: str) -> int | None:
    match = re.search(r"\b(\d{1,2})\s*(?:links?|plaatsingen?|publicaties?|artikelen?)\b", text)
    if match:
        return max(1, int(match.group(1)))
    return None


def _parse_number(raw: str) -> int | None:
    value = raw.strip().lower().replace(" ", "")
    multiplier = 1000 if value.endswith("k") else 1
    value = value.rstrip("k")
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".")
    elif "." in value and len(value.split(".")[-1]) == 3:
        value = value.replace(".", "")
    else:
        value = value.replace(",", ".")
    try:
        return int(float(value) * multiplier)
    except ValueError:
        return None


def _extract_text_after_label(text: str, labels: list[str]) -> str | None:
    for label in labels:
        pattern = rf"(?:{re.escape(label)})\s*(?:is|:|=)?\s*[\"'“”]?([^\n.;]+)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" \"'“”")
            # Stop before another likely field label in the same sentence.
            value = re.split(
                r"\s+(?:dr|traffic|verkeer|taal|language|url|anchor|budget|aantal)\b",
                value,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            value = re.split(
                r",\s*(?:nederlands|dutch|engels|english|duits|german|frans|french|spaans|spanish|min|dr|traffic|verkeer|target|url|anchor|budget|aantal|\d)",
                value,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" ,")
            if value:
                return value
    return None


def _extract_notes(text: str) -> str | None:
    match = re.search(r"(?:notitie|notes?|opmerking|extra wens(?:en)?)\s*(?:is|:|=)?\s*([^\n]+)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    if any(word in text.lower() for word in ["geen casino", "geen adult", "geen gambling", "exclude", "uitsluiten"]):
        return text.strip()
    return None
