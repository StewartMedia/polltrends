"""Detect search-interest spikes and match them to dated headlines.

A spike is a day where a party's interest is at least twice its trailing
7-day average and at least 3 points above it. Consecutive spike days for the
same party collapse to the peak day. Headlines come from every news snapshot
collected so far, so older spikes can still be matched to coverage from
their own week.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (  # noqa: E402
    ENTITIES, PROCESSED_DIR, RAW_DIR, VIC_ENTITIES, list_dated_directories, load_latest_file,
    today_local, write_json,
)

SPIKE_RATIO = 2.0
MIN_LIFT = 3        # points above the trailing average
MIN_VALUE = 5       # ignore quantisation noise at very low volumes
ROLLING_WINDOW = 7
MERGE_DAYS = 3
MAX_SPIKES = 12


def detect_spikes(iot_data: dict, entities: dict) -> list[dict]:
    records = iot_data.get("data", [])
    spikes = []
    for code, ent in entities.items():
        values = [r.get(code, 0) for r in records]
        found = []
        for i in range(ROLLING_WINDOW, len(values)):
            window = values[i - ROLLING_WINDOW:i]
            avg = sum(window) / ROLLING_WINDOW
            cur = values[i]
            if avg > 0 and cur >= MIN_VALUE and cur - avg >= MIN_LIFT and cur / avg >= SPIKE_RATIO:
                found.append({
                    "date": records[i]["date"][:10],
                    "party_code": code,
                    "party_name": ent["short_name"],
                    "value": cur,
                    "rolling_avg": round(avg, 1),
                    "ratio": round(cur / avg, 1),
                })
        merged: list[dict] = []
        for s in found:
            if merged and (date.fromisoformat(s["date"]) - date.fromisoformat(merged[-1]["date"])).days <= MERGE_DAYS:
                if s["value"] > merged[-1]["value"]:
                    merged[-1] = s
            else:
                merged.append(s)
        spikes.extend(merged)
    spikes.sort(key=lambda s: s["ratio"], reverse=True)
    return sorted(spikes[:MAX_SPIKES], key=lambda s: s["date"], reverse=True)


def news_archive(subdir: str | None = None) -> dict[str, list[dict]]:
    """All headlines ever collected for this geo, de-duplicated by title."""
    archive: dict[str, dict[str, dict]] = {}
    for d in list_dated_directories(RAW_DIR):
        path = (d / subdir if subdir else d) / "news.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        for code, articles in (data or {}).items():
            if not isinstance(articles, list):
                continue
            bucket = archive.setdefault(code, {})
            for a in articles:
                if a.get("title") and a.get("date"):
                    bucket.setdefault(a["title"].lower(), a)
    return {code: list(v.values()) for code, v in archive.items()}


PARTY_WORDS = {
    "ALP": re.compile(r"\b(Labor|ALP|Albanese|Carroll|Allan|Chalmers)\b", re.I),
    "LIB": re.compile(r"\b(Liberals?|Coalition|Taylor|Wilson|Battin|Pesutto|Ley|opposition)\b", re.I),
    "NAT": re.compile(r"\b(Nationals?|O'Brien|Littleproud)\b", re.I),
    "GRN": re.compile(r"\b(Greens?|Shoebridge|Sandell|Waters)\b", re.I),
    "PHON": re.compile(r"\b(One Nation|Hanson|Pickering)\b", re.I),
}


def match_news(spikes: list[dict], archive: dict[str, list[dict]]) -> list[dict]:
    """Attach headlines published from a day before to two days after each spike.

    A headline must name the party or its leader, so a story that merely
    appeared in the party's search results is not presented as the cause.
    """
    for spike in spikes:
        sd = date.fromisoformat(spike["date"])
        words = PARTY_WORDS.get(spike["party_code"])
        matches = []
        for a in archive.get(spike["party_code"], []):
            if words and not words.search(a.get("title", "")):
                continue
            try:
                delta = (date.fromisoformat(a["date"][:10]) - sd).days
            except ValueError:
                continue
            if -1 <= delta <= 2:
                matches.append({**{k: a.get(k, "") for k in ("title", "source", "url", "date")}, "_d": abs(delta)})
        matches.sort(key=lambda a: a["_d"])
        spike["news"] = [{k: v for k, v in a.items() if k != "_d"} for a in matches[:3]]
        spike["explanation"] = spike["news"][0]["title"] if spike["news"] else None
    return spikes


def run(entities: dict, subdir: str | None, label: str) -> list[dict]:
    src_date, iot = load_latest_file(RAW_DIR, "interest_over_time.json", subdir=subdir)
    if not iot:
        print(f"  No {label} interest data")
        return []
    archive = news_archive(subdir)
    if subdir:
        # State spikes are often driven by federal stories (and vice versa),
        # so fall back to national headlines for the same party.
        for code, articles in news_archive(None).items():
            archive.setdefault(code, [])
            archive[code] = archive[code] + articles
    spikes = match_news(detect_spikes(iot, entities), archive)
    out_dir = PROCESSED_DIR / today_local()
    if subdir:
        out_dir = out_dir / subdir
    write_json(out_dir / "spikes.json", spikes)
    matched = sum(1 for s in spikes if s["news"])
    print(f"  {label}: {len(spikes)} spikes from {src_date} data ({matched} with headlines)")
    return spikes


def main():
    return run(ENTITIES, None, "national")


def detect_victoria():
    return run(VIC_ENTITIES, "victoria", "victoria")


if __name__ == "__main__":
    main()
    detect_victoria()
