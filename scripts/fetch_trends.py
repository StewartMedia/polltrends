"""Fetch Google Trends entity data for Australian political parties.

Pulls interest-over-time and related queries daily, stores as dated JSON files.
"""
import json
import time
import sys
from datetime import datetime, date
from pathlib import Path

from pytrends.request import TrendReq

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import ENTITIES, GEO, RAW_DIR


def fetch_interest_over_time(pytrends: TrendReq, timeframe: str = "today 3-m") -> dict:
    """Fetch interest over time for all entities."""
    mids = [ent["mid"] for ent in ENTITIES.values()]
    codes = list(ENTITIES.keys())

    pytrends.build_payload(mids, geo=GEO, timeframe=timeframe)
    df = pytrends.interest_over_time()

    if df.empty:
        print("WARNING: Empty interest_over_time response")
        return {}

    # Rename columns from mids to party codes
    mid_to_code = {ent["mid"]: code for code, ent in ENTITIES.items()}
    df = df.rename(columns=mid_to_code)
    df = df.drop(columns=["isPartial"], errors="ignore")

    # Convert to serialisable format
    records = []
    for dt, row in df.iterrows():
        record = {"date": dt.strftime("%Y-%m-%d")}
        for code in codes:
            record[code] = int(row.get(code, 0))
        records.append(record)

    return {"timeframe": timeframe, "geo": GEO, "data": records}


def fetch_related_queries(pytrends: TrendReq) -> dict:
    """Fetch related queries for each entity individually."""
    results = {}

    for code, ent in ENTITIES.items():
        print(f"  Fetching related queries for {code}...")
        try:
            pytrends.build_payload([ent["mid"]], geo=GEO, timeframe="today 3-m")
            related = pytrends.related_queries()
            mid = ent["mid"]

            entity_queries = {"top": [], "rising": []}

            if mid in related and related[mid]["top"] is not None:
                top_df = related[mid]["top"]
                entity_queries["top"] = top_df.to_dict("records")

            if mid in related and related[mid]["rising"] is not None:
                rising_df = related[mid]["rising"]
                entity_queries["rising"] = rising_df.to_dict("records")

            results[code] = entity_queries
        except Exception as e:
            print(f"  WARNING: Failed for {code}: {e}")
            results[code] = {"top": [], "rising": []}

        time.sleep(2)  # Be gentle with Google

    return results


def main():
    today = date.today().isoformat()
    print(f"Fetching trends data for {today}")

    pytrends = TrendReq(hl="en-AU", tz=600)  # AEST

    # Interest over time
    print("Fetching interest over time...")
    iot_data = fetch_interest_over_time(pytrends)

    # Related queries
    print("Fetching related queries...")
    time.sleep(3)
    rq_data = fetch_related_queries(pytrends)

    # Save raw data
    out_dir = RAW_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "interest_over_time.json", "w") as f:
        json.dump(iot_data, f, indent=2)

    with open(out_dir / "related_queries.json", "w") as f:
        json.dump(rq_data, f, indent=2)

    print(f"Data saved to {out_dir}")
    return iot_data, rq_data


if __name__ == "__main__":
    main()
