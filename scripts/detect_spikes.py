"""Detect significant spikes in entity search interest data.

Identifies days where a party's interest is significantly above its rolling average,
then matches with real news headlines from Google News RSS.
"""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import ENTITIES, RAW_DIR, PROCESSED_DIR

SPIKE_THRESHOLD = 2.0  # Must be this many times above the rolling average
ROLLING_WINDOW = 7     # Days for rolling average
MIN_ABSOLUTE = 10      # Minimum absolute value to count as a spike (filters noise)


def detect_spikes(iot_data: dict) -> list[dict]:
    """Find significant spikes in interest data."""
    records = iot_data.get("data", [])
    if len(records) < ROLLING_WINDOW + 1:
        return []

    codes = list(ENTITIES.keys())
    spikes = []

    for code in codes:
        values = [r.get(code, 0) for r in records]

        for i in range(ROLLING_WINDOW, len(values)):
            current = values[i]
            window = values[i - ROLLING_WINDOW:i]
            rolling_avg = sum(window) / len(window) if window else 0

            if rolling_avg > 0 and current >= MIN_ABSOLUTE:
                ratio = current / rolling_avg
                if ratio >= SPIKE_THRESHOLD:
                    spikes.append({
                        "date": records[i]["date"],
                        "party_code": code,
                        "party_name": ENTITIES[code]["short_name"],
                        "value": current,
                        "rolling_avg": round(rolling_avg, 1),
                        "ratio": round(ratio, 1),
                        "explanation": None,
                        "news": [],
                    })

    # Sort by ratio descending, keep top 10 most significant
    spikes.sort(key=lambda s: s["ratio"], reverse=True)
    return spikes[:10]


def match_news_to_spikes(spikes: list[dict], news_data: dict) -> list[dict]:
    """Match real news headlines to spike dates.

    For each spike, find news articles for that party published within
    a 2-day window around the spike date (day before, day of, day after).
    """
    for spike in spikes:
        party_code = spike["party_code"]
        spike_date = datetime.strptime(spike["date"], "%Y-%m-%d").date()
        articles = news_data.get(party_code, [])

        matching = []
        for article in articles:
            if not article.get("date"):
                continue
            try:
                article_date = datetime.strptime(article["date"], "%Y-%m-%d").date()
            except ValueError:
                continue

            # Match articles within 2 days of the spike
            delta = abs((article_date - spike_date).days)
            if delta <= 2:
                matching.append({
                    "title": article["title"],
                    "source": article.get("source", ""),
                    "url": article.get("url", ""),
                    "date": article["date"],
                })

        spike["news"] = matching[:3]  # Top 3 most relevant

        # Build explanation from actual headlines
        if matching:
            spike["explanation"] = matching[0]["title"]
        else:
            spike["explanation"] = "Significant spike in search interest"

    return spikes


def main():
    print("Detecting spikes in trends data...")

    raw_dirs = sorted(d for d in RAW_DIR.iterdir() if d.is_dir())
    if not raw_dirs:
        print("No data found.")
        return []

    latest = raw_dirs[-1]

    # Load interest over time
    iot_path = latest / "interest_over_time.json"
    if not iot_path.exists():
        print("No interest data found.")
        return []

    with open(iot_path) as f:
        iot_data = json.load(f)

    # Load news data
    news_data = {}
    news_path = latest / "news.json"
    if news_path.exists():
        with open(news_path) as f:
            news_data = json.load(f)
    else:
        print("  WARNING: No news data found. Run fetch_news.py first.")

    spikes = detect_spikes(iot_data)
    print(f"Found {len(spikes)} significant spikes")

    if spikes:
        for s in spikes:
            print(f"  {s['date']} - {s['party_name']}: {s['value']} ({s['ratio']}x avg)")

    spikes = match_news_to_spikes(spikes, news_data)

    # Save
    today = date.today().isoformat()
    out_dir = PROCESSED_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "spikes.json", "w") as f:
        json.dump(spikes, f, indent=2)

    print(f"Spikes saved to {out_dir}")
    return spikes


if __name__ == "__main__":
    main()
