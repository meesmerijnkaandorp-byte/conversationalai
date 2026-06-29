from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pandas as pd

from .order import normalize_language


REQUIRED_COLUMNS = [
    "domain",
    "dr",
    "monthly_traffic",
    "language",
    "category",
    "price_eur",
    "turnaround_days",
    "sponsored_allowed",
    "contact_email",
    "notes",
]

STOPWORDS = {
    "the",
    "and",
    "for",
    "met",
    "een",
    "het",
    "van",
    "voor",
    "over",
    "naar",
    "bij",
    "die",
    "dat",
    "this",
    "that",
    "een",
    "campagne",
    "links",
    "plaatsingen",
}


def load_inventory(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"Inventory mist kolommen: {', '.join(missing)}")

    numeric_columns = ["dr", "monthly_traffic", "price_eur", "turnaround_days"]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0).astype(int)

    df["language"] = df["language"].map(normalize_language)
    df["sponsored_allowed"] = df["sponsored_allowed"].astype(str).str.lower().isin(["true", "1", "yes", "ja"])
    return df


def _theme_tokens(theme: Any) -> list[str]:
    if not theme:
        return []
    tokens = re.findall(r"[a-z0-9]+", str(theme).lower())
    return [token for token in tokens if len(token) > 2 and token not in STOPWORDS]


def filter_inventory(df: pd.DataFrame, criteria: dict[str, Any]) -> pd.DataFrame:
    result = df.copy()

    min_dr = criteria.get("min_dr")
    min_traffic = criteria.get("min_traffic")
    language = normalize_language(criteria.get("language"))

    if min_dr is not None:
        result = result[result["dr"] >= int(min_dr)]
    if min_traffic is not None:
        result = result[result["monthly_traffic"] >= int(min_traffic)]
    if language:
        result = result[result["language"].str.lower() == language.lower()]

    tokens = _theme_tokens(criteria.get("theme"))
    if tokens and not result.empty:
        haystack = (
            result["domain"].astype(str)
            + " "
            + result["category"].astype(str)
            + " "
            + result["notes"].astype(str)
        ).str.lower()
        result = result.assign(
            theme_score=haystack.apply(lambda value: sum(1 for token in tokens if token in value))
        )
        # The theme is used as a ranking signal, not as a hard filter.
        # This keeps the POC useful when inventory categories are still sparse.
    else:
        result = result.assign(theme_score=0)

    sort_columns = ["theme_score", "dr", "monthly_traffic", "price_eur"]
    result = result.sort_values(sort_columns, ascending=[False, False, False, True])
    return result.reset_index(drop=True)


def select_publishers(matches: pd.DataFrame, quantity: int | None, budget_eur: int | None) -> pd.DataFrame:
    if matches.empty:
        return matches.copy()

    requested = int(quantity or min(3, len(matches)))
    requested = max(1, requested)

    if budget_eur is None or budget_eur <= 0:
        return matches.head(requested).copy()

    remaining = int(budget_eur)
    selected_indices: list[int] = []
    for index, row in matches.iterrows():
        price = int(row["price_eur"])
        if price <= remaining:
            selected_indices.append(index)
            remaining -= price
        if len(selected_indices) >= requested:
            break

    return matches.loc[selected_indices].copy()


def public_inventory_summary(matches: pd.DataFrame, max_rows: int = 8) -> list[dict[str, Any]]:
    public_columns = [
        "domain",
        "dr",
        "monthly_traffic",
        "language",
        "category",
        "price_eur",
        "turnaround_days",
    ]
    if matches.empty:
        return []
    return matches[public_columns].head(max_rows).to_dict(orient="records")
