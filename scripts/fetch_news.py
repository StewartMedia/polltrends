"""Fetch news headlines via Google News RSS (free, no API key).

Party news (national + Victoria) and seat news for the Victorian seats the
model flags as in play. Headlines are evidence for search spikes; they are
never summarised or rewritten.
"""
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (  # noqa: E402
    ENTITIES, RAW_DIR, TIMEZONE, USER_AGENT, VIC_ENTITIES, today_local, write_json,
)

GNEWS_RSS_URL = "https://news.google.com/rss/search?q={query}&hl=en-AU&gl=AU&ceid=AU:en"

# A seat headline must mention the seat and look political; this drops
# weather reports, crime briefs and sport that share a district's name.
POLITICAL_WORDS = re.compile(
    r"\b(candidate|candidates|election|electorate|seat|MP|member for|preselect\w*|campaign\w*|pledge\w*|"
    r"promis\w*|vote\w*|voter\w*|poll\w*|Labor|Liberal\w*|Greens|Nationals|One Nation|independent|"
    r"Coalition|Carroll|Wilson|Pickering|Sandell|minister|government|opposition|funding|commit\w*)\b",
    re.IGNORECASE,
)

PARTY_QUERIES = {
    "ALP": '"Albanese government" OR "federal Labor" OR "Anthony Albanese"',
    "LIB": '"Angus Taylor" OR "federal Liberals" OR "federal Coalition"',
    "GRN": '"Australian Greens" OR "David Shoebridge"',
    "PHON": '"One Nation" OR "Pauline Hanson"',
}

VIC_PARTY_QUERIES = {
    "ALP": '"Victorian Labor" OR "Ben Carroll" OR "Carroll government"',
    "LIB": '"Victorian Liberals" OR "Jess Wilson"',
    "NAT": '"Victorian Nationals" OR "Danny O\'Brien"',
    "GRN": '"Victorian Greens" OR "Ellen Sandell"',
    "PHON": '"Warren Pickering" OR "One Nation Victoria" OR "Victorian One Nation"',
}


def _parse_date(text: str) -> str | None:
    if not text:
        return None
    try:
        return parsedate_to_datetime(text).astimezone(TIMEZONE).date().isoformat()
    except (TypeError, ValueError):
        return None


def fetch_rss(query: str, tag: str, max_items: int = 12) -> list[dict]:
    url = GNEWS_RSS_URL.format(query=quote(query))
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except (requests.RequestException, ET.ParseError) as exc:
        print(f"  WARNING: news fetch failed for {tag}: {exc}")
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    articles, seen = [], set()
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        if " - " in title:
            head, tail = title.rsplit(" - ", 1)
            title = head.strip()
            source = source or tail.strip()
        key = title.lower()
        if not title or key in seen:
            continue
        seen.add(key)
        articles.append({
            "title": title,
            "source": source,
            "url": item.findtext("link") or "",
            "date": _parse_date(item.findtext("pubDate") or ""),
            "party_code": tag,
        })
    articles.sort(key=lambda a: a["date"] or "", reverse=True)
    return articles[:max_items]


def fetch_and_save(queries: dict, entities: dict, out_dir: Path, label: str) -> dict:
    print(f"\nFetching {label} news")
    all_news = {}
    for code, query in queries.items():
        articles = fetch_rss(query, code)
        all_news[code] = articles
        print(f"  {entities.get(code, {}).get('short_name', code)}: {len(articles)} articles")
        time.sleep(1)
    if sum(len(v) for v in all_news.values()) == 0:
        print(f"  WARNING: no {label} news fetched; keeping previous snapshot")
        return {}
    write_json(out_dir / "news.json", all_news)
    return all_news


def fetch_seat_news(seats: list[str], max_items: int = 4) -> dict:
    """Recent headlines for specific Victorian districts."""
    if not seats:
        return {}
    print(f"\nFetching seat news for {len(seats)} seats")
    out = {}
    for seat in seats:
        query = f'"{seat}" ("Victorian election" OR "state election" OR candidate OR electorate) when:45d'
        articles = [a for a in fetch_rss(query, seat, max_items=20)
                    if seat.lower() in a["title"].lower() and POLITICAL_WORDS.search(a["title"])]
        out[seat] = articles[:max_items]
        time.sleep(1)
    found = sum(1 for v in out.values() if v)
    print(f"  headlines found for {found}/{len(seats)} seats")
    write_json(RAW_DIR / today_local() / "victoria" / "seat_news.json", out)
    return out


def main():
    return fetch_and_save(PARTY_QUERIES, ENTITIES, RAW_DIR / today_local(), "national")


def fetch_victoria():
    return fetch_and_save(VIC_PARTY_QUERIES, VIC_ENTITIES, RAW_DIR / today_local() / "victoria", "victoria")


if __name__ == "__main__":
    main()
    fetch_victoria()
    print(json.dumps({"date": today_local(), "generated": datetime.now(TIMEZONE).isoformat()}))
