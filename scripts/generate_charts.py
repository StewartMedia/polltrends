"""Generate interactive Plotly charts from trends data.

All chart builders accept entities and party_colors as parameters
so they can be reused for both national and Victoria data.
"""
import json
import sys
from datetime import date
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (
    ENTITIES, PARTY_COLORS, RAW_DIR, PROCESSED_DIR, OUTPUT_DIR,
    VIC_ENTITIES, VIC_PARTY_COLORS,
)


def load_latest_iot(subdir: str | None = None) -> dict:
    """Load the most recent interest-over-time data."""
    raw_dirs = sorted(d for d in RAW_DIR.iterdir() if d.is_dir())
    if not raw_dirs:
        raise FileNotFoundError("No raw data found. Run fetch_trends.py first.")

    latest = raw_dirs[-1]
    target = latest / subdir if subdir else latest
    with open(target / "interest_over_time.json") as f:
        return json.load(f)


def load_latest_related_queries(subdir: str | None = None) -> dict:
    """Load the most recent related queries data."""
    raw_dirs = sorted(d for d in RAW_DIR.iterdir() if d.is_dir())
    latest = raw_dirs[-1]
    target = latest / subdir if subdir else latest
    with open(target / "related_queries.json") as f:
        return json.load(f)


def load_spikes(subdir: str | None = None) -> list[dict]:
    """Load spike annotations from processed data."""
    proc_dirs = sorted(d for d in PROCESSED_DIR.iterdir() if d.is_dir())
    for d in reversed(proc_dirs):
        target = d / subdir if subdir else d
        path = target / "spikes.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
    return []


def build_interest_chart(
    iot_data: dict,
    spikes: list[dict] | None = None,
    entities: dict | None = None,
    party_colors: dict | None = None,
    title: str = "Australian Political Party Search Interest",
) -> str:
    """Build the main interest-over-time comparison chart with news annotations."""
    entities = entities or ENTITIES
    party_colors = party_colors or PARTY_COLORS

    records = iot_data.get("data", [])
    if not records:
        return "<p>No data available.</p>"

    dates = [r["date"] for r in records]

    fig = go.Figure()

    for code, ent in entities.items():
        values = [r.get(code, 0) for r in records]
        fig.add_trace(go.Scatter(
            x=dates,
            y=values,
            mode="lines",
            name=ent["short_name"],
            line=dict(color=party_colors[code], width=2.5),
            hovertemplate=f"{ent['short_name']}: %{{y}}<br>%{{x}}<extra></extra>",
        ))

    # Add spike annotations
    annotations = []
    if spikes:
        for spike in spikes:
            spike_date = spike["date"]
            party_code = spike["party_code"]
            explanation = spike.get("explanation", "Spike detected")
            value = spike.get("value", 0)
            color = party_colors.get(party_code, "#333")

            # Skip if party not in this entity set
            if party_code not in entities:
                continue

            # Truncate explanation for annotation label
            short_label = explanation[:60] + "..." if len(explanation) > 60 else explanation

            annotations.append(dict(
                x=spike_date,
                y=value,
                xref="x",
                yref="y",
                text=f"<b>{entities[party_code]['short_name']}</b><br>{short_label}",
                showarrow=True,
                arrowhead=2,
                arrowsize=1,
                arrowwidth=1.5,
                arrowcolor=color,
                ax=0,
                ay=-60,
                bordercolor=color,
                borderwidth=1.5,
                borderpad=4,
                bgcolor="rgba(255,255,255,0.9)",
                font=dict(size=10, color="#333"),
                align="left",
            ))

    fig.update_layout(
        title=dict(
            text=title,
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
        height=550,
        annotations=annotations,
    )

    return fig.to_html(full_html=False, include_plotlyjs=False)


def build_weekly_bars(
    iot_data: dict,
    entities: dict | None = None,
    party_colors: dict | None = None,
    title_prefix: str = "Average Search Interest",
) -> str:
    """Build a bar chart showing average search interest for the most recent 7 days."""
    entities = entities or ENTITIES
    party_colors = party_colors or PARTY_COLORS

    records = iot_data.get("data", [])
    if len(records) < 7:
        return "<p>Not enough data for weekly summary.</p>"

    last_7 = records[-7:]
    codes = list(entities.keys())

    avgs = {}
    for code in codes:
        avgs[code] = sum(r.get(code, 0) for r in last_7) / 7

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[entities[c]["short_name"] for c in codes],
        y=[avgs[c] for c in codes],
        marker_color=[party_colors[c] for c in codes],
        text=[f"{avgs[c]:.1f}" for c in codes],
        textposition="auto",
    ))

    period_start = last_7[0]["date"]
    period_end = last_7[-1]["date"]

    fig.update_layout(
        title=dict(
            text=f"{title_prefix} — Last 7 Days ({period_start} to {period_end})",
            font=dict(size=18),
        ),
        yaxis_title="Avg Search Interest",
        template="plotly_white",
        height=400,
        margin=dict(l=60, r=30, t=80, b=60),
    )

    return fig.to_html(full_html=False, include_plotlyjs=False)


def build_related_queries_table(
    rq_data: dict,
    entities: dict | None = None,
    party_colors: dict | None = None,
) -> str:
    """Build an HTML table of top/rising related queries per party."""
    entities = entities or ENTITIES
    party_colors = party_colors or PARTY_COLORS

    html = ""
    for code, ent in entities.items():
        queries = rq_data.get(code, {})
        top = queries.get("top", [])[:10]
        rising = queries.get("rising", [])[:10]

        html += f'<div class="rq-card" style="border-left: 4px solid {party_colors[code]}">\n'
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
