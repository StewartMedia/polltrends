"""Rolling 7-day search-interest summary.

Runs daily. For each entity: last-7-day average, previous-7-day average,
change, share of search, rank and a 30-day sparkline. Values are Google
Trends relative interest (0-100, scaled to the busiest day in the 90-day
window), not search counts and not voting intention.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (  # noqa: E402
    ENTITIES, PROCESSED_DIR, RAW_DIR, VIC_ENTITIES, VIC_LEADERS, load_latest_file, today_local, write_json,
)

LOW_BASE = 2.0  # below this, % change is noise


def _avg(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def rolling(values: list[int], window: int = 7) -> list[float]:
    out = []
    for i in range(len(values)):
        chunk = values[max(0, i - window + 1):i + 1]
        out.append(round(_avg(chunk), 1))
    return out


def summarise(iot: dict, entities: dict) -> dict | None:
    records = iot.get("data", [])
    if len(records) < 14:
        return None
    codes = list(entities)
    last7, prev7 = records[-7:], records[-14:-7]

    stats = {}
    for code in codes:
        values = [r.get(code, 0) for r in records]
        cur = _avg([r.get(code, 0) for r in last7])
        prev = _avg([r.get(code, 0) for r in prev7])
        peak_idx = max(range(len(last7)), key=lambda i: last7[i].get(code, 0))
        stats[code] = {
            "avg": round(cur, 1),
            "prev_avg": round(prev, 1),
            "change_pts": round(cur - prev, 1),
            "momentum_pct": round((cur - prev) / prev * 100) if prev >= LOW_BASE else None,
            "avg_90d": round(_avg(values), 1),
            "peak_7d": last7[peak_idx].get(code, 0),
            "peak_7d_date": last7[peak_idx]["date"][:10],
            "peak_90d": max(values),
            "peak_90d_date": records[values.index(max(values))]["date"][:10],
            "spark": rolling(values)[-30:],
        }

    total = sum(s["avg"] for s in stats.values()) or 1
    prev_total = sum(s["prev_avg"] for s in stats.values()) or 1
    for code, s in stats.items():
        s["share"] = round(s["avg"] / total * 100, 1)
        s["prev_share"] = round(s["prev_avg"] / prev_total * 100, 1)

    ranked = sorted(codes, key=lambda c: stats[c]["avg"], reverse=True)
    prev_ranked = sorted(codes, key=lambda c: stats[c]["prev_avg"], reverse=True)
    for i, code in enumerate(ranked, 1):
        stats[code]["rank"] = i
        stats[code]["prev_rank"] = prev_ranked.index(code) + 1

    leader, runner_up = ranked[0], ranked[1]
    lead_ratio = stats[leader]["avg"] / stats[runner_up]["avg"] if stats[runner_up]["avg"] else None
    return {
        "period": {"start": last7[0]["date"][:10], "end": last7[-1]["date"][:10]},
        "prev_period": {"start": prev7[0]["date"][:10], "end": prev7[-1]["date"][:10]},
        "ranking": ranked,
        "leader": leader,
        "runner_up": runner_up,
        "lead_ratio": round(lead_ratio, 1) if lead_ratio else None,
        "stats": stats,
    }


def run(entities: dict, filename: str, subdir: str | None, label: str,
        out_name: str = "weekly_analysis.json") -> dict | None:
    src_date, iot = load_latest_file(RAW_DIR, filename, subdir=subdir)
    if not iot:
        print(f"  No {label} data")
        return None
    summary = summarise(iot, entities)
    if not summary:
        print(f"  Not enough {label} data")
        return None
    summary["source_date"] = src_date
    summary["fetched_at"] = iot.get("fetched_at")
    out_dir = PROCESSED_DIR / today_local()
    if subdir:
        out_dir = out_dir / subdir
    write_json(out_dir / out_name, summary)
    lead = summary["stats"][summary["leader"]]
    print(f"  {label}: {entities[summary['leader']]['short_name']} leads "
          f"(avg {lead['avg']}, {lead['share']}% share) for {summary['period']['start']}..{summary['period']['end']}")
    return summary


def main():
    return run(ENTITIES, "interest_over_time.json", None, "national")


def analyse_victoria():
    return run(VIC_ENTITIES, "interest_over_time.json", "victoria", "victoria")


def analyse_victoria_leaders():
    return run(VIC_LEADERS, "leaders_interest.json", "victoria", "victoria leaders",
               out_name="leaders_analysis.json")


if __name__ == "__main__":
    main()
    analyse_victoria()
    analyse_victoria_leaders()
