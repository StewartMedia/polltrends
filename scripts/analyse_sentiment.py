"""Analyse sentiment of related queries using Grok API.

Classifies each related query as positive/negative/neutral for the associated party.
Runs weekly as part of the analysis pipeline.
"""
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import ENTITIES, GROK_API_URL, GROK_MODEL, RAW_DIR, PROCESSED_DIR

GROK_API_KEY = os.environ.get("GROK_API_KEY", "")

SENTIMENT_PROMPT_TEMPLATE = """You are an Australian political analyst. Classify the sentiment
of each search query below as it relates to the party "{party_name}".

For each query, respond with exactly one of: positive, negative, neutral
Consider whether the query suggests favourable or unfavourable attention for the party.

Queries:
{queries}

Respond as a JSON array of objects with "query" and "sentiment" keys. Nothing else."""


def classify_queries(party_name: str, queries: list[str]) -> list[dict]:
    """Classify a batch of queries by sentiment using Grok."""
    if not queries:
        return []

    if not GROK_API_KEY:
        # Fallback: all neutral
        return [{"query": q, "sentiment": "neutral"} for q in queries]

    query_text = "\n".join(f"- {q}" for q in queries)
    prompt = SENTIMENT_PROMPT_TEMPLATE.format(party_name=party_name, queries=query_text)

    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": GROK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
    }

    try:
        resp = requests.post(GROK_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

        # Parse JSON from response (handle markdown code blocks)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]

        return json.loads(content)
    except Exception as e:
        print(f"  Sentiment API error: {e}")
        return [{"query": q, "sentiment": "neutral"} for q in queries]


def analyse_week():
    """Analyse related queries from the most recent data."""
    raw_dirs = sorted(d for d in RAW_DIR.iterdir() if d.is_dir())
    if not raw_dirs:
        print("No data found.")
        return

    latest = raw_dirs[-1]
    rq_path = latest / "related_queries.json"
    if not rq_path.exists():
        print(f"No related queries in {latest}")
        return

    with open(rq_path) as f:
        rq_data = json.load(f)

    results = {}

    for code, ent in ENTITIES.items():
        print(f"Analysing sentiment for {ent['short_name']}...")
        party_queries = rq_data.get(code, {})

        all_queries = []
        for q in party_queries.get("top", []):
            all_queries.append(q.get("query", ""))
        for q in party_queries.get("rising", []):
            all_queries.append(q.get("query", ""))

        # Deduplicate
        all_queries = list(dict.fromkeys(q for q in all_queries if q))

        classified = classify_queries(ent["name"], all_queries)

        # Tally
        sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
        for item in classified:
            s = item.get("sentiment", "neutral").lower()
            if s in sentiment_counts:
                sentiment_counts[s] += 1

        total = len(classified) or 1
        results[code] = {
            "party": ent["short_name"],
            "queries_analysed": len(classified),
            "sentiment_counts": sentiment_counts,
            "sentiment_score": round(
                (sentiment_counts["positive"] - sentiment_counts["negative"]) / total, 2
            ),
            "classified_queries": classified,
        }

    # Save
    today = date.today().isoformat()
    out_dir = PROCESSED_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "sentiment_analysis.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Sentiment analysis saved to {out_dir}")
    return results


def main():
    analyse_week()


if __name__ == "__main__":
    main()
