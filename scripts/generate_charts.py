"""Generate interactive Plotly charts from trends data."""
import json
import sys
from datetime import date
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import ENTITIES, PARTY_COLORS, RAW_DIR, OUTPUT_DIR


def load_latest_iot() -> dict:
    """Load the most recent interest-over-time data."""
    raw_dirs = sorted(RAW_DIR.iterdir())
    if not raw_dirs:
        raise FileNotFoundError("No raw data found. Run fetch_trends.py first.")

    latest = raw_dirs[-1]
    with open(latest / "interest_over_time.json") as f:
        return json.load(f)


def load_latest_related_queries() -> dict:
    """Load the most recent related queries data."""
    raw_dirs = sorted(RAW_DIR.iterdir())
    latest = raw_dirs[-1]
    with open(latest / "related_queries.json") as f:
        return json.load(f)


def build_interest_chart(iot_data: dict) -> str:
    """Build the main interest-over-time comparison chart. Returns HTML string."""
    records = iot_data.get("data", [])
    if not records:
        return "<p>No data available.</p>"

    dates = [r["date"] for r in records]

    fig = go.Figure()

    for code, ent in ENTITIES.items():
        values = [r.get(code, 0) for r in records]
        fig.add_trace(go.Scatter(
            x=dates,
            y=values,
            mode="lines",
            name=ent["short_name"],
            line=dict(color=PARTY_COLORS[code], width=2.5),
            hovertemplate=f"{ent['short_name']}: %{{y}}<br>%{{x}}<extra></extra>",
        ))

    fig.update_layout(
        title=dict(
            text="Australian Political Party Search Interest",
            font=dict(size=20),
        ),
        xaxis_title="Date",
        yaxis_title="Search Interest (relative)",
        template="plotly_white",
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        margin=dict(l=60, r=30, t=80, b=60),
        height=500,
    )

    return fig.to_html(full_html=False, include_plotlyjs=False)


def build_weekly_bars(iot_data: dict) -> str:
    """Build a bar chart showing average search interest for the most recent 7 days."""
    records = iot_data.get("data", [])
    if len(records) < 7:
        return "<p>Not enough data for weekly summary.</p>"

    last_7 = records[-7:]
    codes = list(ENTITIES.keys())

    avgs = {}
    for code in codes:
        avgs[code] = sum(r.get(code, 0) for r in last_7) / 7

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[ENTITIES[c]["short_name"] for c in codes],
        y=[avgs[c] for c in codes],
        marker_color=[PARTY_COLORS[c] for c in codes],
        text=[f"{avgs[c]:.1f}" for c in codes],
        textposition="auto",
    ))

    period_start = last_7[0]["date"]
    period_end = last_7[-1]["date"]

    fig.update_layout(
        title=dict(
            text=f"Average Search Interest — Last 7 Days ({period_start} to {period_end})",
            font=dict(size=18),
        ),
        yaxis_title="Avg Search Interest",
        template="plotly_white",
        height=400,
        margin=dict(l=60, r=30, t=80, b=60),
    )

    return fig.to_html(full_html=False, include_plotlyjs=False)


def build_related_queries_table(rq_data: dict) -> str:
    """Build an HTML table of top/rising related queries per party."""
    html = ""
    for code, ent in ENTITIES.items():
        queries = rq_data.get(code, {})
        top = queries.get("top", [])[:10]
        rising = queries.get("rising", [])[:10]

        html += f'<div class="rq-card" style="border-left: 4px solid {PARTY_COLORS[code]}">\n'
        html += f'<h3>{ent["short_name"]} — Related Queries</h3>\n'
        html += '<div class="rq-columns">\n'

        # Top queries
        html += '<div class="rq-col"><h4>Top</h4><table><tr><th>Query</th><th>Score</th></tr>\n'
        for q in top:
            query_text = q.get("query", "")
            value = q.get("value", 0)
            html += f"<tr><td>{query_text}</td><td>{value}</td></tr>\n"
        html += "</table></div>\n"

        # Rising queries
        html += '<div class="rq-col"><h4>Rising</h4><table><tr><th>Query</th><th>Change</th></tr>\n'
        for q in rising:
            query_text = q.get("query", "")
            value = q.get("value", "")
            html += f"<tr><td>{query_text}</td><td>{value}</td></tr>\n"
        html += "</table></div>\n"

        html += "</div></div>\n"

    return html


def main():
    print("Generating charts...")
    iot_data = load_latest_iot()
    rq_data = load_latest_related_queries()

    charts = {
        "interest_over_time": build_interest_chart(iot_data),
        "weekly_bars": build_weekly_bars(iot_data),
        "related_queries": build_related_queries_table(rq_data),
    }

    # Save chart fragments for the site builder
    out = OUTPUT_DIR / "_charts"
    out.mkdir(parents=True, exist_ok=True)

    for name, html in charts.items():
        with open(out / f"{name}.html", "w") as f:
            f.write(html)

    print(f"Charts saved to {out}")
    return charts


if __name__ == "__main__":
    main()
