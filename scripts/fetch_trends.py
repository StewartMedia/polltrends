"""Fetch Google Trends entity data for Australian political parties and leaders.

Writes dated JSON snapshots (Melbourne date):
  data/raw/<date>/interest_over_time.json            national parties
  data/raw/<date>/related_queries.json
  data/raw/<date>/victoria/interest_over_time.json   Victorian parties
  data/raw/<date>/victoria/related_queries.json
  data/raw/<date>/victoria/related_queries_7d.json   Victorian parties, last 7 days
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
    has_complete_related, has_related_rows, now_local, today_local, write_json,
)

MAX_ENTITIES_PER_REQUEST = 5
REQUEST_TIMEOUT = (10, 25)
BACKOFF = [20, 45, 90, 150]  # seconds between attempts
# Short window for the Victorian "who are voters comparing" panel. The 90-day
# related queries move too slowly to show campaign-week behaviour.
RELATED_7D_TIMEFRAME = "now 7-d"
# The Nationals topic has returned no Victorian related queries since tracking
# began (too little volume), so it is left out to save a rate-limited request.
RELATED_7D_EXCLUDE = {"NAT"}
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


def _parse_related(rq: dict, entities: dict, batch: list[str], related: dict) -> None:
    mid_to_code = {entities[c]["mid"]: c for c in batch}
    for mid, parts in (rq or {}).items():
        code = mid_to_code.get(mid, mid)
        if code in related:
            continue
        parts = parts or {}
        related[code] = {
            kind: (parts[kind].to_dict("records") if parts.get(kind) is not None else [])
            for kind in ("top", "rising")
        }


def fetch_related(entities: dict, geo: str, timeframe: str) -> dict:
    """Related queries only. Returns {} when Google gives nothing back."""
    related: dict[str, dict] = {}
    for i, batch in enumerate(_batch_codes(list(entities.keys()))):
        pt = _session()
        mids = [entities[c]["mid"] for c in batch]
        print(f"  related batch {i + 1}: {', '.join(batch)} (geo={geo}, {timeframe})")
        _retry("build_payload", lambda: pt.build_payload(mids, geo=geo, timeframe=timeframe))
        try:
            rq = _retry("related_queries", pt.related_queries) or {}
        except RETRYABLE as exc:
            print(f"  WARNING: related queries unavailable ({exc.__class__.__name__})")
            rq = {}
        _parse_related(rq, entities, batch, related)
        time.sleep(4)
    return related if has_related_rows(related) else {}


def save_related(path: Path, related: dict) -> bool:
    """Write related queries only when they hold data, so an empty
    rate-limited response never replaces the last good snapshot."""
    if has_related_rows(related):
        write_json(path, related)
        return True
    print(f"  WARNING: related queries empty; not writing {path.name} (last good copy is used)")
    return False


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
            _parse_related(rq, entities, batch, related)
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
            related_path = out_dir / "related_queries.json"
            if with_related and not _has_rows_on_disk(related_path):
                print("  related queries missing or empty for today; retrying them only")
                try:
                    save_related(related_path, fetch_related(entities, geo, TIMEFRAME))
                except RETRYABLE as exc:
                    print(f"  WARNING: related retry failed ({exc.__class__.__name__}); keeping last good copy")
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
        save_related(out_dir / "related_queries.json", related)
    print(f"  saved {label} -> {out_dir} ({len(payload['data'])} days, last {payload['data'][-1]['date']})")
    return True


def _has_rows_on_disk(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        return has_related_rows(json.loads(path.read_text()))
    except json.JSONDecodeError:
        return False


def _is_complete_on_disk(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        return has_complete_related(json.loads(path.read_text()))
    except json.JSONDecodeError:
        return False


def fetch_victoria_related_7d() -> bool:
    """Victorian related queries over the last 7 days (one snapshot per day).

    Feeds the "who are voters comparing" panel. Optional: a failure leaves the
    panel on its last good snapshot, labelled with its date.
    """
    out = RAW_DIR / today_local() / "victoria" / "related_queries_7d.json"
    print(f"\nFetching victoria related queries ({RELATED_7D_TIMEFRAME})")
    if _is_complete_on_disk(out) and not os.getenv("POLTRENDS_FORCE_TRENDS"):
        print("  already fetched today; skipping. Set POLTRENDS_FORCE_TRENDS=1 to refetch.")
        return True
    entities = {c: e for c, e in VIC_ENTITIES.items() if c not in RELATED_7D_EXCLUDE}
    time.sleep(8)
    try:
        related = fetch_related(entities, VIC_GEO, RELATED_7D_TIMEFRAME)
    except RETRYABLE as exc:
        print(f"  FAILED: {exc.__class__.__name__}: {exc}")
        return False
    if not related:
        print("  FAILED: no related queries returned")
        return False
    if not has_complete_related(related):
        # Usually rate limiting. Saving it would replace a full sample with a partial one.
        empty = sorted(c for c, v in related.items() if not v.get("top"))
        print(f"  FAILED: partial pull, no top queries for {', '.join(empty)}; last complete copy is used")
        return False
    write_json(out, {
        "timeframe": RELATED_7D_TIMEFRAME,
        "geo": VIC_GEO,
        "fetched_at": now_local().isoformat(timespec="seconds"),
        "excluded": sorted(RELATED_7D_EXCLUDE),
        "parties": related,
    })
    print(f"  saved -> {out}")
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
    results = [main(), fetch_victoria(), fetch_victoria_leaders(), fetch_victoria_related_7d()]
    sys.exit(0 if any(results) else 1)
