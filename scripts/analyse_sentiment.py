"""Analyse sentiment of related queries using keyword-based classification.

Classifies each related query as positive/negative/neutral for the associated party.
Uses a simple keyword lexicon approach - no API dependencies.
Supports multi-geo: national (AU) and Victoria (AU-VIC).
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import ENTITIES, RAW_DIR, PROCESSED_DIR, VIC_ENTITIES

# Keyword lexicons for political sentiment
NEGATIVE_KEYWORDS = [
    "scandal", "corruption", "fail", "crisis", "resign", "sack", "fired",
    "controversy", "fraud", "lie", "lying", "racist", "racism", "sexist",
    "attack", "slam", "blast", "reject", "oppose", "block", "protest",
    "illegal", "crime", "criminal", "abuse", "hate", "worst", "disaster",
    "collapse", "loss", "lose", "losing", "defeat", "drop", "fall",
    "investigation", "probe", "inquiry", "charged", "arrested", "jail",
    "ban", "penalty", "fine", "waste", "debt", "deficit", "inflation",
    "cost of living", "housing crisis", "broken promise",
]

POSITIVE_KEYWORDS = [
    "win", "victory", "success", "boost", "surge", "lead", "ahead",
    "popular", "support", "approve", "reform", "invest", "growth",
    "plan", "policy", "announce", "launch", "pledge", "promise",
    "improve", "better", "best", "strong", "unite", "build",
    "fund", "funding", "deliver", "achieve", "progress", "new",
    "innovation", "opportunity", "benefit", "protect", "save",
]


def classify_query(query: str) -> str:
    """Classify a query as positive, negative, or neutral using keyword matching."""
    q = query.lower()

    neg_score = sum(1 for kw in NEGATIVE_KEYWORDS if kw in q)
    pos_score = sum(1 for kw in POSITIVE_KEYWORDS if kw in q)

    if neg_score > pos_score:
        return "negative"
    elif pos_score > neg_score:
        return "positive"
    return "neutral"


def run_sentiment_analysis(entities: dict, raw_dir: Path, out_dir: Path, label: str = "national"):
    """Analyse related queries sentiment for a given geo."""
    rq_path = raw_dir / "related_queries.json"
    if not rq_path.exists():
        print(f"  No related queries at {rq_path}")
        return None

    with open(rq_path) as f:
        rq_data = json.load(f)

    results = {}

    for code, ent in entities.items():
        print(f"  Analysing sentiment for {ent['short_name']}...")
        party_queries = rq_data.get(code, {})

        all_queries = []
        for q in party_queries.get("top", []):
            all_queries.append(q.get("query", ""))
        for q in party_queries.get("rising", []):
            all_queries.append(q.get("query", ""))

        # Deduplicate
        all_queries = list(dict.fromkeys(q for q in all_queries if q))

        classified = []
        for q in all_queries:
            sentiment = classify_query(q)
            classified.append({"query": q, "sentiment": sentiment})

        # Tally
        sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
        for item in classified:
            s = item.get("sentiment", "neutral")
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
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "sentiment_analysis.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"  {label.title()} sentiment analysis saved to {out_dir}")
    return results


def analyse_week():
    """Analyse related queries from the most recent national data."""
    raw_dirs = sorted(d for d in RAW_DIR.iterdir() if d.is_dir())
    if not raw_dirs:
        print("No data found.")
        return

    latest = raw_dirs[-1]
    today = date.today().isoformat()
    out_dir = PROCESSED_DIR / today

    return run_sentiment_analysis(ENTITIES, latest, out_dir, label="national")


def analyse_victoria():
    """Analyse related queries from the most recent Victoria data."""
    raw_dirs = sorted(d for d in RAW_DIR.iterdir() if d.is_dir())
    if not raw_dirs:
        print("No data found.")
        return

    latest = raw_dirs[-1]
    vic_raw = latest / "victoria"
    if not vic_raw.exists():
        print("No Victoria data found.")
        return

    today = date.today().isoformat()
    out_dir = PROCESSED_DIR / today / "victoria"

    return run_sentiment_analysis(VIC_ENTITIES, vic_raw, out_dir, label="victoria")


def main():
    analyse_week()


if __name__ == "__main__":
    main()
