"""Fetch Google Trends entity data for Australian political parties and leaders.

Writes dated JSON snapshots (Melbourne date):
  data/raw/<date>/interest_over_time.json            national parties
  data/raw/<date>/related_queries.json
  data/raw/<date>/victoria/interest_over_time.json   Victorian parties
  data/raw/<date>/victoria/related_queries.json
  data/raw/<date>/victoria/leaders_interest.json     Victorian leaders

Google Trends rate-limits aggressively, so every call retries with backoff and
a failure in one dataset never blocks the others. Downstream steps carry the
last good snapshot forward and label it with its real date.
"""
import json
import os
import sys
import time
from pathlib import Path

from pytrends import exceptions as pt_exceptions
from pytrends.request import TrendReq
from requests import exceptions as req_exceptions

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (  # noqa: E402
    ENTITIES, GEO, RAW_DIR, TIMEFRAME, VIC_ENTITIES, VIC_GEO, VIC_LEADERS,
    now_local, today_local, write_json,
)

MAX_ENTITIES_PER_REQUEST = 5
REQUEST_TIMEOUT = (10, 25)
BACKOFF = [20, 45, 90, 150]  # seconds between attempts
RETRYABLE = (
    pt_exceptions.TooManyRequestsError,
    pt_exceptions.ResponseError,
    req_exceptions.ReadTimeout,
    req_exceptions.ConnectTimeout,
    req_exceptions.ConnectionError,
)


def _session() -> TrendReq:
    # pytrends tz is minutes *behind* UTC, so AEST (UTC+10) is -600.
    return TrendReq(hl="en-AU", tz=-600, timeout=REQUEST_TIMEOUT)


def _retry(label: str, fn):
    for attempt, wait in enumerate(BACKOFF + [None]):
        try:
            return fn()
        except RETRYABLE as exc:
            if wait is None:
                raise
            status = getattr(getattr(exc, "response", None), "status_code", "")
            print(f"  {label}: {exc.__class__.__name__} {status} - retry {attempt + 1}/{len(BACKOFF)} in {wait}s")
            time.sleep(wait)


def _batch_codes(codes: list[str]) -> list[list[str]]:
    """Split codes into request batches. Extra batches repeat the first code
    as an anchor so their values can be rescaled onto the first batch."""
    if len(codes) <= MAX_ENTITIES_PER_REQUEST:
        return [codes]
    anchor = codes[0]
    batches = [codes[:MAX_ENTITIES_PER_REQUEST]]
    rest = codes[MAX_ENTITIES_PER_REQUEST:]
    step = MAX_ENTITIES_PER_REQUEST - 1
    while rest:
        batches.append([anchor] + rest[:step])
        rest = rest[step:]
    return batches


def _frame_to_series(df, entities: dict, batch: list[str]) -> dict[str, dict[str, int]]:
    """Convert a pytrends frame into {code: {date: value}}, dropping partial rows.

    Today's row is always partial and reads low, which would distort the
    7-day averages, so it is excluded.
    """
    if df is None or df.empty:
        return {}
    if "isPartial" in df.columns:
        df = df[~df["isPartial"].astype(bool)]
        df = df.drop(columns=["isPartial"])
    mid_to_code = {entities[c]["mid"]: c for c in batch}
    df = df.rename(columns=mid_to_code)
    out: dict[str, dict[str, int]] = {}
    for code in batch:
        if code not in df.columns:
            continue
        out[code] = {dt.strftime("%Y-%m-%d"): int(v) for dt, v in df[code].items()}
    return out


def fetch_interest(entities: dict, geo: str, timeframe: str = TIMEFRAME, with_related: bool = True):
    """Return (interest_payload, related_queries) for a set of entities."""
    codes = list(entities.keys())
    series: dict[str, dict[str, int]] = {}
    related: dict[str, dict] = {}
    anchor = codes[0]

    for i, batch in enumerate(_batch_codes(codes)):
        pt = _session()
        mids = [entities[c]["mid"] for c in batch]
        print(f"  batch {i + 1}: {', '.join(batch)} (geo={geo}, {timeframe})")
        _retry("build_payload", lambda: pt.build_payload(mids, geo=geo, timeframe=timeframe))
        df = _retry("interest_over_time", pt.interest_over_time)
        batch_series = _frame_to_series(df, entities, batch)
        if not batch_series:
            print("  WARNING: empty interest response")
            continue

        if i == 0:
            series.update(batch_series)
        else:
            ref = series.get(anchor, {})
            this = batch_series.get(anchor, {})
            for code in batch:
                if code == anchor or code not in batch_series:
                    continue
                scaled = {}
                for d, v in batch_series[code].items():
                    a_ref, a_this = ref.get(d, 0), this.get(d, 0)
                    scaled[d] = int(round(v * a_ref / a_this)) if a_ref and a_this else v
                series[code] = scaled

        if with_related:
            try:
                rq = _retry("related_queries", pt.related_queries) or {}
            except RETRYABLE as exc:
                print(f"  WARNING: related queries unavailable ({exc.__class__.__name__}); continuing")
                rq = {}
            mid_to_code = {entities[c]["mid"]: c for c in batch}
            for mid, parts in rq.items():
                code = mid_to_code.get(mid, mid)
                if code in related:
                    continue
                parts = parts or {}
                related[code] = {
                    kind: (parts[kind].to_dict("records") if parts.get(kind) is not None else [])
                    for kind in ("top", "rising")
                }
        time.sleep(4)

    if not series:
        return None, related

    dates = sorted(series[next(iter(series))].keys())
    records = [{"date": d, **{c: series.get(c, {}).get(d, 0) for c in codes}} for d in dates]
    payload = {
        "timeframe": timeframe,
        "geo": geo,
        "fetched_at": now_local().isoformat(timespec="seconds"),
        "data": records,
    }
    return payload, related


def fetch_and_save(entities: dict, geo: str, out_dir: Path, label: str, with_related: bool = True,
                   interest_file: str = "interest_over_time.json") -> bool:
    print(f"\nFetching {label} trends ({len(entities)} entities, geo={geo})")
    existing = out_dir / interest_file
    if existing.exists() and not os.getenv("POLTRENDS_FORCE_TRENDS"):
        try:
            prior = json.loads(existing.read_text())
        except json.JSONDecodeError:
            prior = {}
        fetched = prior.get("fetched_at", "")
        rows = prior.get("data") or [{}]
        if fetched.startswith(today_local()) and set(rows[0]) >= set(entities):
            print(f"  already fetched today ({fetched}); skipping. Set POLTRENDS_FORCE_TRENDS=1 to refetch.")
            return True
    try:
        payload, related = fetch_interest(entities, geo, with_related=with_related)
    except RETRYABLE as exc:
        print(f"  FAILED {label}: {exc.__class__.__name__}: {exc}")
        return False
    if not payload:
        print(f"  FAILED {label}: no data")
        return False
    write_json(out_dir / interest_file, payload)
    if with_related:
        write_json(out_dir / "related_queries.json", related)
    print(f"  saved {label} -> {out_dir} ({len(payload['data'])} days, last {payload['data'][-1]['date']})")
    return True


def main() -> bool:
    return fetch_and_save(ENTITIES, GEO, RAW_DIR / today_local(), "national")


def fetch_victoria() -> bool:
    return fetch_and_save(VIC_ENTITIES, VIC_GEO, RAW_DIR / today_local() / "victoria", "victoria")


def fetch_victoria_leaders() -> bool:
    if not VIC_LEADERS:
        return False
    time.sleep(10)
    return fetch_and_save(
        VIC_LEADERS, VIC_GEO, RAW_DIR / today_local() / "victoria", "victoria leaders",
        with_related=False, interest_file="leaders_interest.json",
    )


if __name__ == "__main__":
    results = [main(), fetch_victoria(), fetch_victoria_leaders()]
    sys.exit(0 if any(results) else 1)
