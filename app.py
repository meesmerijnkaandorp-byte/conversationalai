from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from src.agent import get_agent_decision
from src.catalog import filter_inventory, load_inventory, public_inventory_summary, select_publishers
from src.order import (
    FIELD_LABELS,
    create_order,
    empty_order,
    format_order_value,
    is_order_confirmation,
    merge_order_patch,
    missing_required,
)

BASE_DIR = Path(__file__).parent
INVENTORY_PATH = BASE_DIR / "data" / "publishers.csv"
ORDERS_PATH = BASE_DIR / "data" / "orders" / "orders.jsonl"

DISPLAY_COLUMNS = {
    "domain": "Domein",
    "dr": "DR",
    "monthly_traffic": "Traffic",
    "language": "Taal",
    "category": "Categorie",
    "price_eur": "Prijs EUR",
    "turnaround_days": "Doorlooptijd",
}

WELCOME_MESSAGE = """
Hoi! Ik help je een linkbuilding/mediabuying conceptorder samen te stellen.

Vertel bijvoorbeeld: **thema fintech, Nederlands, min DR 50, min traffic 50k, 3 plaatsingen, budget 2000 euro, target URL https://example.com, anchor 'boekhoudsoftware vergelijken'**.
""".strip()


@st.cache_data(show_spinner=False)
def get_inventory(path: str) -> pd.DataFrame:
    return load_inventory(Path(path))


def init_session() -> None:
    if "order" not in st.session_state:
        st.session_state.order = empty_order()
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": WELCOME_MESSAGE}]
    if "selected_domain_ids" not in st.session_state:
        st.session_state.selected_domain_ids = []
    if "last_order" not in st.session_state:
        st.session_state.last_order = None


def reset_session() -> None:
    st.session_state.order = empty_order()
    st.session_state.messages = [{"role": "assistant", "content": WELCOME_MESSAGE}]
    st.session_state.selected_domain_ids = []
    st.session_state.last_order = None


def order_table(order: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for key, label in FIELD_LABELS.items():
        rows.append({"Veld": label, "Waarde": format_order_value(order, key)})
    return pd.DataFrame(rows)


def compute_suggestion(matches: pd.DataFrame, order: dict[str, Any]) -> list[str]:
    selected_df = select_publishers(matches, order.get("quantity"), order.get("budget_eur"))
    return selected_df["domain"].tolist() if not selected_df.empty else []


def enrich_reply(reply: str, order: dict[str, Any], matches: pd.DataFrame, selected_domains: list[str]) -> str:
    missing = missing_required(order)
    if missing:
        labels = ", ".join(FIELD_LABELS[field] for field in missing)
        return f"{reply}\n\nNog nodig voor een conceptorder: **{labels}**."

    if matches.empty:
        return (
            f"{reply}\n\nMet deze harde filters vind ik nog geen publisher in de sample-inventory. "
            "Verlaag bijvoorbeeld min. DR/min. traffic of kies een andere taal."
        )

    if not selected_domains:
        return (
            f"{reply}\n\nIk vind **{len(matches)}** passende publisher(s), maar binnen het budget is nog niets geselecteerd. "
            "Verhoog het budget of selecteer rechts handmatig een publisher."
        )

    selected_rows = matches[matches["domain"].isin(selected_domains)]
    total = int(selected_rows["price_eur"].sum())
    formatted_total = f"{total:,}".replace(",", ".")
    domain_list = ", ".join(selected_domains[:5])
    return (
        f"{reply}\n\n**Voorstel:** {len(matches)} match(es), geselecteerd: **{domain_list}**. "
        f"Geschatte totaalprijs: **€{formatted_total}**. Typ **bevestig order** of klik rechts op **Conceptorder aanmaken**."
    )


def store_concept_order(inventory: pd.DataFrame) -> dict[str, Any]:
    selected_domains = st.session_state.selected_domain_ids
    record = create_order(st.session_state.order, selected_domains, inventory, ORDERS_PATH)
    st.session_state.last_order = record
    return record


def render_sidebar(inventory: pd.DataFrame) -> None:
    order = st.session_state.order
    matches = filter_inventory(inventory, order)
    missing = missing_required(order)

    with st.sidebar:
        st.header("Conceptorder")
        if st.button("Nieuw gesprek / reset"):
            reset_session()
            st.rerun()

        st.dataframe(order_table(order), hide_index=True, use_container_width=True)

        if missing:
            st.warning("Nog nodig: " + ", ".join(FIELD_LABELS[field] for field in missing))
        else:
            st.success("Alle verplichte ordervelden zijn ingevuld.")

        st.divider()
        st.subheader("Publisher matches")
        active_filters = any(order.get(key) is not None for key in ["theme", "language", "min_dr", "min_traffic"])
        if not active_filters:
            st.caption("Nog geen filters. Start links de chat om matches te zien.")
            return

        visible_matches = matches[list(DISPLAY_COLUMNS.keys())].rename(columns=DISPLAY_COLUMNS)
        st.dataframe(visible_matches, hide_index=True, use_container_width=True)

        domain_options = matches["domain"].tolist()
        default_selection = [domain for domain in st.session_state.selected_domain_ids if domain in domain_options]
        if not missing and not default_selection:
            default_selection = compute_suggestion(matches, order)
            st.session_state.selected_domain_ids = default_selection

        selected = st.multiselect(
            "Geselecteerde publishers",
            options=domain_options,
            default=default_selection,
            help="Voor deze POC zijn dit sample publishers uit data/publishers.csv.",
        )
        st.session_state.selected_domain_ids = selected

        can_create = not missing and len(selected) > 0
        if st.button("Conceptorder aanmaken", disabled=not can_create, type="primary"):
            record = store_concept_order(inventory)
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": (
                        f"Conceptorder **{record['order_id']}** is aangemaakt met "
                        f"{len(record['selected_publishers'])} publisher(s). "
                        f"Geschatte totaalprijs: **€{record['estimated_total_eur']}**."
                    ),
                }
            )
            st.rerun()

        if st.session_state.last_order:
            st.info(f"Laatste order: {st.session_state.last_order['order_id']}")


def process_prompt(prompt: str, inventory: pd.DataFrame) -> None:
    st.session_state.messages.append({"role": "user", "content": prompt})

    current_matches = filter_inventory(inventory, st.session_state.order)
    decision = get_agent_decision(
        messages=st.session_state.messages,
        order=st.session_state.order,
        inventory_matches=public_inventory_summary(current_matches),
    )

    st.session_state.order = merge_order_patch(st.session_state.order, decision.get("patch", {}))
    updated_matches = filter_inventory(inventory, st.session_state.order)

    if not missing_required(st.session_state.order):
        suggested = compute_suggestion(updated_matches, st.session_state.order)
        if suggested:
            st.session_state.selected_domain_ids = suggested

    if is_order_confirmation(prompt):
        missing = missing_required(st.session_state.order)
        if missing:
            labels = ", ".join(FIELD_LABELS[field] for field in missing)
            assistant_reply = f"Ik kan de order nog niet aanmaken. Ik mis nog: **{labels}**."
        elif not st.session_state.selected_domain_ids:
            assistant_reply = "Ik kan de order nog niet aanmaken, want er is nog geen publisher geselecteerd. Pas de filters of selectie rechts aan."
        else:
            record = store_concept_order(inventory)
            assistant_reply = (
                f"Conceptorder **{record['order_id']}** is aangemaakt met "
                f"{len(record['selected_publishers'])} publisher(s). "
                f"Geschatte totaalprijs: **€{record['estimated_total_eur']}**."
            )
    else:
        assistant_reply = enrich_reply(
            decision.get("assistant_reply", "Genoteerd."),
            st.session_state.order,
            updated_matches,
            st.session_state.selected_domain_ids,
        )

    st.session_state.messages.append({"role": "assistant", "content": assistant_reply})


def main() -> None:
    st.set_page_config(page_title="Linkbuilding Marketplace POC", page_icon="🔗", layout="wide")
    init_session()
    inventory = get_inventory(str(INVENTORY_PATH))

    st.title("🔗 Linkbuilding / Mediabuying Marketplace POC")
    st.caption("Chatgestuurde order intake met sample inventory, publisher filtering en conceptorder-export naar JSONL.")

    render_sidebar(inventory)

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Beschrijf de campagne of vul ontbrekende orderinformatie aan...")
    if prompt:
        process_prompt(prompt, inventory)
        st.rerun()


if __name__ == "__main__":
    main()
