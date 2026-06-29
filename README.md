# Linkbuilding / Mediabuying Marketplace POC

Een minimale POC voor een marketplace waarin een klant via chat een conceptorder maakt. De app gebruikt Streamlit voor de UI, een sample publisher-inventory in CSV en optioneel de OpenAI API voor betere orderextractie.

## Wat zit erin?

- Chatgestuurde order intake
- Verplichte ordervelden:
  - thema / niche
  - taal
  - minimale DR
  - minimale traffic
  - target URL
  - anchor text
  - aantal plaatsingen
- Optioneel: budget en extra notities
- Publisher filtering op taal, DR, traffic en thema
- Automatische publisherselectie op basis van aantal en budget
- Conceptorder-export naar `data/orders/orders.jsonl`
- Mock mode zonder API-key
- OpenAI mode met `OPENAI_API_KEY`
- GitHub Codespaces/devcontainer setup

## GitHub Codespaces setup

1. Maak een nieuwe GitHub repository.
2. Zet alle bestanden uit deze map in de root van je repository.
3. Open de repository in GitHub Codespaces.
4. Voeg optioneel een Codespaces secret toe:
   - naam: `OPENAI_API_KEY`
   - waarde: je OpenAI API-key
5. Start de app:

```bash
streamlit run app.py
```

Codespaces opent poort `8501` automatisch door de `.devcontainer/devcontainer.json` configuratie.

## Zonder OpenAI API-key

De app werkt ook zonder API-key. Dan gebruikt `src/agent.py` simpele regex-extractie. Dat is genoeg voor een POC-demo, maar minder flexibel dan een echte LLM.

## Met OpenAI API-key

Zet in Codespaces of lokaal:

```bash
export OPENAI_API_KEY="jouw_key"
export OPENAI_MODEL="gpt-5.5"
streamlit run app.py
```

`OPENAI_MODEL` is optioneel. De default in deze POC is `gpt-5.5`.

## Voorbeeldprompt

```text
Thema fintech, Nederlands, min DR 50, min traffic 50k, 3 plaatsingen, budget 2000 euro, target URL https://example.com/boekhouden, anchor 'boekhoudsoftware vergelijken'
```

Daarna:

```text
bevestig order
```

## Data aanpassen

Pas `data/publishers.csv` aan met je eigen inventory. Vereiste kolommen:

```text
domain,dr,monthly_traffic,language,category,price_eur,turnaround_days,sponsored_allowed,contact_email,notes
```

## Productienotities

Dit is bewust een POC. Voor productie wil je onder andere toevoegen:

- echte user accounts en rechten
- database in plaats van JSONL
- publisher availability en voorraadregels
- compliance checks per niche
- pricing rules en marges
- order lifecycle: draft, pending approval, paid, in progress, delivered
- audit trail en logging
- betalingsprovider
- publisher outreach workflow
