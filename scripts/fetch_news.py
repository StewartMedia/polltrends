"""Fetch real news headlines for Australian political parties via Google News RSS.

Google News RSS is free, no API key required, and returns actual published articles.
"""
import json
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import ENTITIES, RAW_DIR

# Google News RSS base URL
GNEWS_RSS_URL = "https://news.google.com/rss/search?q={query}&hl=en-AU&gl=AU&ceid=AU:en"

# Search queries per party - use specific terms that return relevant political news
PARTY_QUERIES = {
    "ALP": '"Australian Labor Party" OR "ALP" OR "Labor government"',
    "LIB": '"Liberal Party" OR "coalition" OR "opposition leader"',
    "GRN": '"Australian Greens" OR "Greens party"',
    "PHON": '"One Nation" OR "Pauline Hanson"',
}


def fetch_party_news(party_code: str, query: str, max_items: int = 10) -> list[dict]:
    """Fetch news headlines for a party from Google News RSS."""
    url = GNEWS_RSS_URL.format(query=quote(query))

    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; PolTrends/1.0)"
        })
        resp.raise_for_status()
    except Exception as e:
        print(f"  WARNING: Failed to fetch news for {party_code}: {e}")
        return []

    articles = []
    try:
        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            return []

        for item in channel.findall("item")[:max_items]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date_str = item.findtext("pubDate", "")
            source = item.findtext("source", "")

            # Parse pub date: "Fri, 21 Feb 2026 03:00:00 GMT"
            pub_date = None
            if pub_date_str:
                try:
                    dt = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %Z")
                    pub_date = dt.strftime("%Y-%m-%d")
                except ValueError:
                    pub_date = pub_date_str

            # Clean title - Google News appends " - Source Name"
            clean_title = title
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                clean_title = parts[0]
                if not source:
                    source = parts[1]

            articles.append({
                "title": clean_title,
                "source": source,
                "url": link,
                "date": pub_date,
                "party_code": party_code,
            })
    except ET.ParseError as e:
        print(f"  WARNING: XML parse error for {party_code}: {e}")

    return articles


def main():
    today = date.today().isoformat()
    print(f"Fetching news headlines for {today}")

    all_news = {}
    for code, query in PARTY_QUERIES.items():
        print(f"  Fetching news for {ENTITIES[code]['short_name']}...")
        articles = fetch_party_news(code, query)
        all_news[code] = articles
        print(f"    Found {len(articles)} articles")

    # Save
    out_dir = RAW_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "news.json", "w") as f:
        json.dump(all_news, f, indent=2)

    print(f"News saved to {out_dir}")
    return all_news


if __name__ == "__main__":
    main()
