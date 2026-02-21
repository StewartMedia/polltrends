"""Weekly analysis: who won the week in search interest and sentiment."""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import ENTITIES, RAW_DIR, PROCESSED_DIR


def load_latest_data():
    """Load most recent interest-over-time and sentiment data."""
    raw_dirs = sorted(d for d in RAW_DIR.iterdir() if d.is_dir())
    proc_dirs = sorted(d for d in PROCESSED_DIR.iterdir() if d.is_dir())

    iot_data = {}
    if raw_dirs:
        iot_path = raw_dirs[-1] / "interest_over_time.json"
        if iot_path.exists():
            with open(iot_path) as f:
                iot_data = json.load(f)

    sentiment_data = {}
    if proc_dirs:
        sent_path = proc_dirs[-1] / "sentiment_analysis.json"
        if sent_path.exists():
            with open(sent_path) as f:
                sentiment_data = json.load(f)

    return iot_data, sentiment_data


def determine_winner(iot_data: dict, sentiment_data: dict) -> dict:
    """Determine who won the week based on search interest and sentiment."""
    records = iot_data.get("data", [])
    codes = list(ENTITIES.keys())

    # Last 7 days average search interest
    last_7 = records[-7:] if len(records) >= 7 else records
    avg_interest = {}
    for code in codes:
        avg_interest[code] = sum(r.get(code, 0) for r in last_7) / max(len(last_7), 1)

    # Previous 7 days for comparison
    prev_7 = records[-14:-7] if len(records) >= 14 else []
    prev_avg = {}
    for code in codes:
        if prev_7:
            prev_avg[code] = sum(r.get(code, 0) for r in prev_7) / len(prev_7)
        else:
            prev_avg[code] = 0

    # Calculate momentum (week-over-week change)
    momentum = {}
    for code in codes:
        if prev_avg[code] > 0:
            momentum[code] = round(
                ((avg_interest[code] - prev_avg[code]) / prev_avg[code]) * 100, 1
            )
        else:
            momentum[code] = 0

    # Search interest winner
    search_winner = max(codes, key=lambda c: avg_interest[c])

    # Sentiment scores
    sentiment_scores = {}
    for code in codes:
        if code in sentiment_data:
            sentiment_scores[code] = sentiment_data[code].get("sentiment_score", 0)
        else:
            sentiment_scores[code] = 0

    # Overall winner: highest search interest with positive or neutral sentiment
    # Weight: 70% search interest rank, 30% sentiment
    max_interest = max(avg_interest.values()) or 1
    combined_scores = {}
    for code in codes:
        norm_interest = avg_interest[code] / max_interest
        norm_sentiment = (sentiment_scores.get(code, 0) + 1) / 2  # map -1..1 to 0..1
        combined_scores[code] = round(0.7 * norm_interest + 0.3 * norm_sentiment, 3)

    overall_winner = max(codes, key=lambda c: combined_scores[c])

    period_start = last_7[0]["date"] if last_7 else "N/A"
    period_end = last_7[-1]["date"] if last_7 else "N/A"

    analysis = {
        "period": {"start": period_start, "end": period_end},
        "avg_interest": {c: round(avg_interest[c], 1) for c in codes},
        "momentum_pct": momentum,
        "sentiment_scores": sentiment_scores,
        "combined_scores": combined_scores,
        "search_winner": search_winner,
        "overall_winner": overall_winner,
        "summary": build_summary(
            overall_winner, avg_interest, momentum, sentiment_scores, period_start, period_end
        ),
    }

    return analysis


def build_summary(winner, avg_interest, momentum, sentiment_scores, start, end) -> str:
    """Build a human-readable weekly summary."""
    ent = ENTITIES[winner]
    lines = [
        f"## Week in Review: {start} to {end}",
        "",
        f"**{ent['short_name']}** dominated search interest this week "
        f"with an average score of {avg_interest[winner]:.1f}.",
        "",
        "### Party Breakdown",
        "",
    ]

    for code in ENTITIES:
        e = ENTITIES[code]
        m = momentum.get(code, 0)
        m_str = f"+{m}%" if m > 0 else f"{m}%"
        s = sentiment_scores.get(code, 0)
        s_label = "positive" if s > 0.1 else "negative" if s < -0.1 else "neutral"
        lines.append(
            f"- **{e['short_name']}**: Avg interest {avg_interest[code]:.1f} "
            f"({m_str} WoW), sentiment: {s_label} ({s:+.2f})"
        )

    return "\n".join(lines)


def main():
    print("Running weekly analysis...")
    iot_data, sentiment_data = load_latest_data()

    if not iot_data.get("data"):
        print("No interest data available. Run fetch_trends.py first.")
        return

    analysis = determine_winner(iot_data, sentiment_data)

    today = date.today().isoformat()
    out_dir = PROCESSED_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "weekly_analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)

    print(f"\nWeekly analysis saved to {out_dir}")
    print(f"\n{analysis['summary']}")
    return analysis


if __name__ == "__main__":
    main()
