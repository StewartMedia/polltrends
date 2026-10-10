"""Victorian seat outlook: poll average plus a uniform-swing pendulum model.

This is deliberately transparent, not a forecast:
  1. Average the latest poll from each pollster in the last 30 days
     (widening to 60 days if needed).
  2. Swing = 2022 Labor two-party-preferred (55.0%) minus the average.
  3. Apply that swing uniformly to every classic Labor-v-Coalition seat on
     the 2022 pendulum. Seats contested against Greens or independents keep
     their current holder and are flagged, because a 2PP swing says nothing
     about them.
One Nation polling above 20% breaks the two-party assumptions, so the site
shows the published YouGov MRP seat projection alongside this model.

Output: data/processed/<date>/victoria/seat_model.json
"""
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (  # noqa: E402
    PROCESSED_DIR, RAW_DIR, TIMEZONE, VIC_ELECTION, VIC_SEATS_PATH, load_latest_file, now_local, today_local,
    write_json,
)

PRIMARY_KEYS = ["ALP", "LNP", "ONP", "GRN", "OTH_ALL"]
TIPPING_BAND = 3.0  # seats within this many points of the modelled swing


def norm_firm(firm: str) -> str:
    firm = re.sub(r"\(.*?\)", "", firm).strip()
    return firm.split("/")[0].strip()


def poll_average(polls: list[dict], as_of: str) -> dict:
    as_of_d = date.fromisoformat(as_of)
    for window in (30, 60, 120):
        cutoff = (as_of_d - timedelta(days=window)).isoformat()
        latest_by_firm: dict[str, dict] = {}
        for p in sorted(polls, key=lambda p: p["date"], reverse=True):
            if p["date"] < cutoff or p["date"] > as_of:
                continue
            latest_by_firm.setdefault(norm_firm(p["firm"]), p)
        used = list(latest_by_firm.values())
        if len(used) >= 3 or window == 120:
            break

    def mean(key):
        vals = [p[key] for p in used if p.get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    return {
        "window_days": window,
        "n_polls": len(used),
        "primary": {k: mean(f"p_{k}") for k in PRIMARY_KEYS},
        "tpp": {"ALP": mean("tpp_ALP"), "LNP": mean("tpp_LNP")},
        "n_tpp": sum(1 for p in used if p.get("tpp_ALP") is not None),
        "polls": [
            {k: p.get(k) for k in ("date", "fieldwork", "firm", "client", "sample",
                                    "p_ALP", "p_LNP", "p_ONP", "p_GRN", "p_OTH_ALL", "tpp_ALP", "tpp_LNP")}
            for p in sorted(used, key=lambda p: p["date"], reverse=True)
        ],
    }


def trend_series(polls: list[dict], since: str = "2025-11-01", window: int = 30) -> list[dict]:
    """Trailing 30-day average at each poll date (latest poll per firm in window)."""
    dates = sorted({p["date"] for p in polls if p["date"] >= since})
    out = []
    for d in dates:
        avg = poll_average([p for p in polls if p["date"] <= d], d)
        out.append({"date": d, **{k: avg["primary"][k] for k in PRIMARY_KEYS}, "tpp_ALP": avg["tpp"]["ALP"]})
    return out


def seat_outcomes(seats: list[dict], swing_to_lnp: float) -> tuple[list[dict], dict]:
    results, tally = [], {}
    for s in seats:
        s = dict(s)
        holder = s["holder"]
        if s["classic"]:
            if holder == "ALP":
                s["flips_at"] = s["margin"]          # swing to Coalition needed
                s["projected"] = "LNP" if swing_to_lnp > s["margin"] else "ALP"
            else:
                s["flips_at"] = -s["margin"]         # swing to Labor needed
                s["projected"] = "ALP" if swing_to_lnp < -s["margin"] else holder
        else:
            s["flips_at"] = None
            s["projected"] = holder
        s["changes"] = s["projected"] not in (holder, "LNP" if holder in ("LIB", "NAT") else None)
        group = "LNP" if s["projected"] in ("LIB", "NAT", "LNP") else s["projected"]
        tally[group] = tally.get(group, 0) + 1
        results.append(s)
    return results, tally


def key_seats(seats: list[dict], swing: float, limit: int = 18) -> list[dict]:
    picks = []
    for s in seats:
        reason = None
        if s["classic"] and s["holder"] == "ALP" and abs(s["margin"] - swing) <= TIPPING_BAND:
            reason = "On the tipping point"
        elif not s["classic"] and s["margin"] < 5:
            reason = f"Close {s['holder']} v {s['vs']} contest"
        if reason:
            picks.append({**s, "reason": reason, "distance": abs((s["margin"] - swing) if s["classic"] else s["margin"])})
    picks.sort(key=lambda s: s["distance"])
    return picks[:limit]


def threshold_swings(seats: list[dict], majority: int) -> dict:
    """Uniform swings at which Labor loses its majority and the Coalition wins one."""
    alp_margins = sorted(s["margin"] for s in seats if s["classic"] and s["holder"] == "ALP")
    alp_now = sum(1 for s in seats if s["holder"] == "ALP")
    lnp_now = sum(1 for s in seats if s["holder"] in ("LIB", "NAT"))
    lose_k = alp_now - majority + 1       # flips needed to push Labor below a majority
    win_k = majority - lnp_now            # flips needed for a Coalition majority
    return {
        "alp_loses_majority": alp_margins[lose_k - 1] if 0 < lose_k <= len(alp_margins) else None,
        "lnp_wins_majority": alp_margins[win_k - 1] if 0 < win_k <= len(alp_margins) else None,
    }


def build(snapshot_date: str | None = None) -> dict | None:
    snapshot_date = snapshot_date or today_local()
    polls_date, polls = load_latest_file(RAW_DIR, "polls.json", subdir="victoria", on_or_before=snapshot_date)
    if not polls:
        print("  No Victorian polls snapshot available")
        return None
    seats_doc = json.loads(VIC_SEATS_PATH.read_text())
    seats = seats_doc["seats"]
    base = VIC_ELECTION["baseline_2022"]

    avg = poll_average(polls["assembly"], snapshot_date)
    tpp_alp = avg["tpp"]["ALP"]
    swing = round(base["tpp"]["ALP"] - tpp_alp, 1) if tpp_alp is not None else 0.0
    outcomes, tally = seat_outcomes(seats, swing)

    # Whole days until polls open (8am Melbourne time), matching the site's live countdown.
    polls_open = datetime.fromisoformat(VIC_ELECTION["date"] + "T08:00:00").replace(tzinfo=TIMEZONE)
    if snapshot_date == today_local():
        days_to_go = max(0, int((polls_open - now_local()).total_seconds() // 86400))
    else:
        days_to_go = (polls_open.date() - date.fromisoformat(snapshot_date)).days
    mrp = polls.get("mrp", [])[:1]
    premier = polls.get("preferred_premier", [])[:1]
    fresh_cutoff = (date.fromisoformat(snapshot_date) - timedelta(days=120)).isoformat()
    substate = {k: v[0] for k, v in polls.get("substate", {}).items() if v and v[0]["date"] >= fresh_cutoff}

    model = {
        "snapshot_date": snapshot_date,
        "polls_date": polls_date,
        "polls_source": polls.get("source"),
        "election_date": VIC_ELECTION["date"],
        "days_to_go": days_to_go,
        "majority": VIC_ELECTION["majority"],
        "baseline_2022": base,
        "average": avg,
        "swing_to_lnp": swing,
        "uniform_swing_tally": tally,
        "thresholds": threshold_swings(seats, VIC_ELECTION["majority"]),
        "mrp": mrp[0] if mrp else None,
        "preferred_premier": premier[0] if premier else None,
        "events": polls.get("events", []),
        "trend": trend_series(polls["assembly"]),
        "substate": substate,
        "seats": outcomes,
        "key_seats": key_seats(outcomes, swing),
        "seats_source": seats_doc.get("source"),
    }
    write_json(PROCESSED_DIR / snapshot_date / "victoria" / "seat_model.json", model)
    print(f"  Victorian model: avg 2PP ALP {tpp_alp} ({avg['n_tpp']} polls), swing {swing} to Coalition, "
          f"uniform-swing tally {tally}, {len(model['key_seats'])} key seats, {days_to_go} days to go")
    return model


if __name__ == "__main__":
    build()
