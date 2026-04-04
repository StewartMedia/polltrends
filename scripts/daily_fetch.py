#!/usr/bin/env python3
"""Daily fetch PolTrends raw data from pytrends."""
import sys
import json
import time
import subprocess
from datetime import datetime

import pandas as pd
import pytrends.request
from pytrends import exceptions

sys.path.insert(0, ".")

from config.settings import ROOT_DIR, RAW_DIR, ENTITIES, GEO, TIMEFRAME, VIC_ENTITIES, VIC_GEO


today = datetime.now().strftime('%Y-%m-%d')
today_dir = RAW_DIR / today
today_dir.mkdir(parents=True, exist_ok=True)


MAX_KEYWORDS_PER_REQUEST = 5


def _build_payload(pytrends_instance, kw_list, geo, timeframe):
    """build_payload wrapper with retry."""
    for attempt in range(5):
        try:
            return pytrends_instance.build_payload(kw_list, geo=geo, timeframe=timeframe)
        except exceptions.TooManyRequestsError:
            if attempt < 4:
                wait = (2 ** attempt) * 15
                print(f"  ⚠️  429 rate limited, retrying in {wait}s (attempt {attempt+1}/5)...")
                time.sleep(wait)
            else:
                raise
        except exceptions.ResponseError as e:
            if attempt < 4:
                wait = (2 ** attempt) * 15
                print(f"  ⚠️  Google error {e.response.status_code}, retrying in {wait}s (attempt {attempt+1}/5)...")
                time.sleep(wait)
            else:
                raise


def fetch_for_geo(entities, geo, prefix):
    kw_list = [ent["mid"] for ent in entities.values()]
    # Split into batches if needed (Victoria geo caps at 5)
    batches = [kw_list[i:i + MAX_KEYWORDS_PER_REQUEST] for i in range(0, len(kw_list), MAX_KEYWORDS_PER_REQUEST)]

    all_interest_frames = []
    all_rq = {}
    all_topics = {}

    for batch_idx, batch in enumerate(batches):
        if len(batches) > 1:
            print(f"  [{prefix or 'national'}] batch {batch_idx + 1}/{len(batches)} ({len(batch)} keywords)")

        # Fresh session per batch to avoid session-level exhaustion
        pt = pytrends.request.TrendReq(hl='en-AU', tz=360)
        _build_payload(pt, batch, geo=geo, timeframe=TIMEFRAME)

        for attempt in range(5):
            try:
                interest = pt.interest_over_time()
                break
            except exceptions.TooManyRequestsError:
                if attempt < 4:
                    wait = (2 ** attempt) * 15
                    print(f"  ⚠️  429 rate limited, retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise
        all_interest_frames.append(interest)

        for attempt in range(5):
            try:
                rq = pt.related_queries()
                break
            except exceptions.TooManyRequestsError:
                if attempt < 4:
                    wait = (2 ** attempt) * 15
                    print(f"  ⚠️  429 rate limited, retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise
        all_rq.update(rq)

        for attempt in range(5):
            try:
                topics = pt.related_topics()
                break
            except exceptions.TooManyRequestsError:
                if attempt < 4:
                    wait = (2 ** attempt) * 15
                    print(f"  ⚠️  429 rate limited, retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise
        all_topics.update(topics)

    # Combine interest frames and transform to chart-compatible format
    interest_combined = pd.concat(all_interest_frames, axis=1) if len(all_interest_frames) > 1 else all_interest_frames[0]
    # Drop 'isPartial' column if present (metadata, not party data)
    if 'isPartial' in interest_combined.columns:
        interest_combined = interest_combined.drop(columns=['isPartial'])
    # Build {"data": [{"date": "...", "CODE": value, ...}, ...]} for chart compatibility
    records = []
    for date_idx, row in interest_combined.iterrows():
        record = {"date": date_idx.isoformat()}
        for col in interest_combined.columns:
            record[col] = int(row[col]) if pd.notna(row[col]) else 0
        records.append(record)
    interest_data = {"data": records}

    # Determine output paths: national → top-level, victoria → victoria/ subdir
    if prefix:
        geo_dir = today_dir / prefix
        geo_dir.mkdir(parents=True, exist_ok=True)
    else:
        geo_dir = today_dir

    with open(geo_dir / "interest_over_time.json", 'w') as f:
        json.dump(interest_data, f)

    with open(geo_dir / "related_queries.json", 'w') as f:
        json.dump(all_rq, f, default=str)

    with open(geo_dir / "news.json", 'w') as f:
        json.dump(all_topics, f, default=str)


# National
fetch_for_geo(ENTITIES, GEO, "")

# Victoria
fetch_for_geo(VIC_ENTITIES, VIC_GEO, "victoria")

# Git
subprocess.run(["git", "add", str(RAW_DIR / today)], cwd=ROOT_DIR, check=False)
subprocess.run(["git", "commit", "-m", f"Fetch raw trends {today}"], cwd=ROOT_DIR, check=False)
subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=ROOT_DIR, check=False)
subprocess.run(["git", "push", "origin", "main"], cwd=ROOT_DIR, check=False)

print("✅ PolTrends daily fetch complete")
