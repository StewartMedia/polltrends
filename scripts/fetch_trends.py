"""Fetch Google Trends entity data for Australian political parties.

Pulls interest-over-time and related queries daily, stores as dated JSON files.
Supports multi-geo: national (AU) and Victoria (AU-VIC).

Note: pytrends allows max 5 entities per request. Victoria has 7 entities,
so we batch into groups of 5 with an overlapping anchor entity to normalise
the relative values across batches.
"""
import json
import time
import sys
from datetime import datetime, date
from pathlib import Path

from pytrends.request import TrendReq

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (
    ENTITIES, GEO, RAW_DIR,
    VIC_ENTITIES, VIC_GEO,
)

MAX_ENTITIES_PER_REQUEST = 5


def _batch_entities(entities: dict) -> list[list[str]]:
    """Split entities into batches of MAX_ENTITIES_PER_REQUEST.

    If more than one batch is needed, the first entity (anchor) is included
    in every batch so values can be normalised across batches.
    """
    codes = list(entities.keys())
    if len(codes) <= MAX_ENTITIES_PER_REQUEST:
        return [codes]

    anchor = codes[0]
    batches = []

    # First batch: first MAX entities
    first_batch = codes[:MAX_ENTITIES_PER_REQUEST]
    batches.append(first_batch)

    # Subsequent batches: anchor + next (MAX-1) entities
    batch_size = MAX_ENTITIES_PER_REQUEST - 1  # leave room for anchor
    remaining = codes[MAX_ENTITIES_PER_REQUEST:]
    while remaining:
        batch = [anchor] + remaining[:batch_size]
        batches.append(batch)
        remaining = remaining[batch_size:]

    return batches


def fetch_interest_over_time(
    pytrends: TrendReq,
    entities: dict,
    geo: str,
    timeframe: str = "today 3-m",
) -> dict:
    """Fetch interest over time for all entities.

    If more than 5 entities, fetches in batches with an anchor entity
    and normalises relative values across batches.
    """
    batches = _batch_entities(entities)
    codes = list(entities.keys())

    if len(batches) == 1:
        # Simple case — all fit in one request
        mids = [entities[c]["mid"] for c in batches[0]]
        pytrends.build_payload(mids, geo=geo, timeframe=timeframe)
        df = pytrends.interest_over_time()

        if df.empty:
            print("WARNING: Empty interest_over_time response")
            return {}

        mid_to_code = {entities[c]["mid"]: c for c in batches[0]}
        df = df.rename(columns=mid_to_code)
        df = df.drop(columns=["isPartial"], errors="ignore")

        records = []
        for dt, row in df.iterrows():
            record = {"date": dt.strftime("%Y-%m-%d")}
            for code in codes:
                record[code] = int(row.get(code, 0))
            records.append(record)

        return {"timeframe": timeframe, "geo": geo, "data": records}

    # Multi-batch: fetch each batch and normalise using anchor
    anchor_code = codes[0]
    all_dfs = {}  # code -> {date: value}
    anchor_values_first = None  # anchor values from first batch

    for i, batch in enumerate(batches):
        mids = [entities[c]["mid"] for c in batch]
        print(f"  Fetching batch {i + 1}/{len(batches)}: {', '.join(batch)}")
        pytrends.build_payload(mids, geo=geo, timeframe=timeframe)
        df = pytrends.interest_over_time()

        if df.empty:
            print(f"  WARNING: Empty response for batch {i + 1}")
            continue

        mid_to_code = {entities[c]["mid"]: c for c in batch}
        df = df.rename(columns=mid_to_code)
        df = df.drop(columns=["isPartial"], errors="ignore")

        if i == 0:
            # First batch is the reference — store anchor values
            anchor_values_first = {
                dt.strftime("%Y-%m-%d"): int(row.get(anchor_code, 0))
                for dt, row in df.iterrows()
            }
            for code in batch:
                all_dfs[code] = {
                    dt.strftime("%Y-%m-%d"): int(row.get(code, 0))
                    for dt, row in df.iterrows()
                }
        else:
            # Normalise this batch using anchor ratio
            anchor_values_this = {
                dt.strftime("%Y-%m-%d"): int(row.get(anchor_code, 0))
                for dt, row in df.iterrows()
            }

            for code in batch:
                if code == anchor_code:
                    continue  # already have anchor from first batch
                values = {}
                for dt, row in df.iterrows():
                    d = dt.strftime("%Y-%m-%d")
                    raw_val = int(row.get(code, 0))
                    anchor_this = anchor_values_this.get(d, 0)
                    anchor_first = anchor_values_first.get(d, 0)

                    if anchor_this > 0 and anchor_first > 0:
                        # Scale value based on anchor ratio
                        scale = anchor_first / anchor_this
                        values[d] = int(round(raw_val * scale))
                    else:
                        values[d] = raw_val
                all_dfs[code] = values

        if i < len(batches) - 1:
            time.sleep(3)  # Be gentle between batches

    if not all_dfs:
        return {}

    # Merge all into records
    all_dates = sorted(anchor_values_first.keys()) if anchor_values_first else []
    records = []
    for d in all_dates:
        record = {"date": d}
        for code in codes:
            record[code] = all_dfs.get(code, {}).get(d, 0)
        records.append(record)

    return {"timeframe": timeframe, "geo": geo, "data": records}


def fetch_related_queries(
    pytrends: TrendReq,
    entities: dict,
    geo: str,
    timeframe: str = "today 3-m",
) -> dict:
    """Fetch related queries for each entity individually."""
    results = {}

    for code, ent in entities.items():
        print(f"  Fetching related queries for {code}...")
        try:
            pytrends.build_payload([ent["mid"]], geo=geo, timeframe=timeframe)
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


def fetch_and_save(entities: dict, geo: str, out_dir: Path, label: str = "national"):
    """Fetch trends data and save to a directory."""
    print(f"\nFetching {label} trends data (geo={geo}, {len(entities)} entities)...")

    pytrends = TrendReq(hl="en-AU", tz=600)  # AEST

    # Interest over time
    print("Fetching interest over time...")
    iot_data = fetch_interest_over_time(pytrends, entities, geo)

    # Related queries
    print("Fetching related queries...")
    time.sleep(3)
    rq_data = fetch_related_queries(pytrends, entities, geo)

    # Save raw data
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "interest_over_time.json", "w") as f:
        json.dump(iot_data, f, indent=2)

    with open(out_dir / "related_queries.json", "w") as f:
        json.dump(rq_data, f, indent=2)

    print(f"{label.title()} data saved to {out_dir}")
    return iot_data, rq_data


def main():
    """Fetch national (AU) trends data."""
    today = date.today().isoformat()
    print(f"Fetching trends data for {today}")

    out_dir = RAW_DIR / today
    fetch_and_save(ENTITIES, GEO, out_dir, label="national")


def fetch_victoria():
    """Fetch Victoria (AU-VIC) trends data."""
    today = date.today().isoformat()
    print(f"Fetching Victoria trends data for {today}")

    out_dir = RAW_DIR / today / "victoria"
    fetch_and_save(VIC_ENTITIES, VIC_GEO, out_dir, label="victoria")


if __name__ == "__main__":
    main()
