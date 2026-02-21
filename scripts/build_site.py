"""Build the static site from templates and data."""
import json
import sys
from datetime import date, datetime
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import ENTITIES, PARTY_COLORS, RAW_DIR, PROCESSED_DIR, TEMPLATES_DIR, OUTPUT_DIR
from scripts.generate_charts import build_interest_chart, build_weekly_bars, build_related_queries_table, load_spikes


def load_latest_file(directory: Path, filename: str) -> dict | str | None:
    """Load a file from the most recent dated subdirectory."""
    dirs = sorted(d for d in directory.iterdir() if d.is_dir())
    for d in reversed(dirs):
        path = d / filename
        if path.exists():
            if filename.endswith(".json"):
                with open(path) as f:
                    return json.load(f)
            else:
                with open(path) as f:
                    return f.read()
    return None


def load_grok_archive() -> list[dict]:
    """Load all grok reports for the archive section."""
    archive = []
    dirs = sorted(d for d in RAW_DIR.iterdir() if d.is_dir())
    for d in reversed(dirs):
        report_path = d / "grok_report.json"
        if report_path.exists():
            with open(report_path) as f:
                data = json.load(f)
                data["report"] = markdown.markdown(data.get("report", ""))
                archive.append(data)
    return archive[:14]  # Last 2 weeks


def build():
    """Build all site pages."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()

    # Load data
    iot_data = load_latest_file(RAW_DIR, "interest_over_time.json") or {}
    rq_data = load_latest_file(RAW_DIR, "related_queries.json") or {}
    analysis = load_latest_file(PROCESSED_DIR, "weekly_analysis.json")
    sentiment = load_latest_file(PROCESSED_DIR, "sentiment_analysis.json")
    grok_report_raw = load_latest_file(RAW_DIR, "grok_report.md")
    grok_archive = load_grok_archive()

    # Add enriched fields to analysis
    if analysis:
        winner_code = analysis.get("search_winner", "")
        analysis["search_winner_name"] = ENTITIES.get(winner_code, {}).get("short_name", winner_code)

    # Load spike annotations
    spikes = load_spikes()

    # Generate charts
    charts = {
        "interest_over_time": build_interest_chart(iot_data, spikes) if iot_data else "<p>No data yet.</p>",
        "weekly_bars": build_weekly_bars(iot_data) if iot_data else "<p>No data yet.</p>",
        "related_queries": build_related_queries_table(rq_data) if rq_data else "<p>No data yet.</p>",
    }

    # Convert grok report markdown to HTML
    grok_report_html = markdown.markdown(grok_report_raw) if grok_report_raw else None

    # Enrich entities with colors for templates
    entities_with_colors = {}
    for code, ent in ENTITIES.items():
        entities_with_colors[code] = {**ent, "color": PARTY_COLORS[code]}

    common_ctx = {
        "updated": today,
        "entities": entities_with_colors,
        "analysis": analysis,
        "sentiment": sentiment,
        "charts": charts,
    }

    # Build index
    tpl = env.get_template("index.html")
    html = tpl.render(**common_ctx, page="index")
    with open(OUTPUT_DIR / "index.html", "w") as f:
        f.write(html)

    # Build analysis page
    tpl = env.get_template("analysis.html")
    html = tpl.render(**common_ctx, page="analysis")
    with open(OUTPUT_DIR / "analysis.html", "w") as f:
        f.write(html)

    # Build X report page
    tpl = env.get_template("xreport.html")
    html = tpl.render(
        **common_ctx,
        page="xreport",
        grok_report=grok_report_html,
        grok_archive=grok_archive,
    )
    with open(OUTPUT_DIR / "xreport.html", "w") as f:
        f.write(html)

    print(f"Site built to {OUTPUT_DIR}")


def main():
    build()


if __name__ == "__main__":
    main()
