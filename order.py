from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
from typing import Any


REQUIRED_FIELDS = [
    "theme",
    "language",
    "min_dr",
    "min_traffic",
    "target_url",
    "anchor_text",
    "quantity",
]

FIELD_LABELS = {
    "theme": "Thema / niche",
    "language": "Taal",
    "min_dr": "Min. DR",
    "min_traffic": "Min. traffic",
    "target_url": "Target URL",
    "anchor_text": "Anchor text",
    "quantity": "Aantal plaatsingen",
    "budget_eur": "Budget EUR",
    "notes": "Notities",
}

INT_FIELDS = {"min_dr", "min_traffic", "quantity", "budget_eur"}
ALL_FIELDS = list(FIELD_LABELS.keys())

LANGUAGE_ALIASES = {
    "nl": "Dutch",
    "nederlands": "Dutch",
    "dutch": "Dutch",
    "en": "English",
    "engels": "English",
    "english": "English",
    "de": "German",
    "duits": "German",
    "german": "German",
    "fr": "French",
    "frans": "French",
    "french": "French",
    "es": "Spanish",
    "spaans": "Spanish",
    "spanish": "Spanish",
}


def normalize_language(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return LANGUAGE_ALIASES.get(text.lower(), text[:1].upper() + text[1:].lower())


def empty_order() -> dict[str, Any]:
    return {
        "theme": None,
        "language": None,
        "min_dr": None,
        "min_traffic": None,
        "target_url": None,
        "anchor_text": None,
        "quantity": None,
        "budget_eur": None,
        "notes": None,
    }


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower().replace("eur", "").replace("euro", "")
    text = text.replace("€", "").replace(" ", "")
    multiplier = 1000 if text.endswith("k") else 1
    text = text.rstrip("k")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "." in text and len(text.split(".")[-1]) == 3:
        text = text.replace(".", "")
    else:
        text = text.replace(",", ".")
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def merge_order_patch(order: dict[str, Any], patch: Any) -> dict[str, Any]:
    merged = {**empty_order(), **(order or {})}
    if patch is None:
        return merged
    if hasattr(patch, "model_dump"):
        patch = patch.model_dump()
    for key, value in dict(patch).items():
        if key not in ALL_FIELDS or value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if key in INT_FIELDS:
            coerced = _coerce_int(value)
            if coerced is None:
                continue
            if key == "min_dr":
                coerced = max(0, min(100, coerced))
            elif key in {"min_traffic", "quantity", "budget_eur"}:
                coerced = max(0, coerced)
            merged[key] = coerced
        elif key == "language":
            merged[key] = normalize_language(value)
        else:
            merged[key] = str(value).strip()
    return merged


def missing_required(order: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in REQUIRED_FIELDS:
        value = order.get(key)
        if key in INT_FIELDS:
            if value is None:
                missing.append(key)
        elif not value:
            missing.append(key)
    return missing


def format_order_value(order: dict[str, Any], key: str) -> str:
    value = order.get(key)
    if value is None or value == "":
        return "-"
    if key in {"min_traffic", "budget_eur"}:
        suffix = "" if key == "min_traffic" else " EUR"
        return f"{int(value):,}".replace(",", ".") + suffix
    return str(value)


def is_order_confirmation(text: str) -> bool:
    normalized = text.lower().strip()
    triggers = [
        "bevestig",
        "maak order",
        "order aanmaken",
        "conceptorder aanmaken",
        "goedgekeurd",
        "akkoord",
        "plaats order",
        "create order",
        "confirm order",
    ]
    return any(trigger in normalized for trigger in triggers)


def create_order(
    order: dict[str, Any],
    selected_domains: list[str],
    inventory_df: Any,
    output_path: Path,
) -> dict[str, Any]:
    order_id = "ORD-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3).upper()
    selected_rows = inventory_df[inventory_df["domain"].isin(selected_domains)].copy()
    selected_items = selected_rows.to_dict(orient="records")
    estimated_total = int(selected_rows["price_eur"].sum()) if not selected_rows.empty else 0

    record = {
        "order_id": order_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "concept",
        "criteria": {key: order.get(key) for key in ALL_FIELDS},
        "selected_publishers": selected_items,
        "estimated_total_eur": estimated_total,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    return record
