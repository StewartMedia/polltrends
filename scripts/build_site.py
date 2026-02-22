"""Build the static site from templates and data."""
import json
import sys
from datetime import date, datetime
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (
    ENTITIES, PARTY_COLORS, RAW_DIR, PROCESSED_DIR, TEMPLATES_DIR, OUTPUT_DIR,
    VIC_ENTITIES, VIC_PARTY_COLORS,
)
from scripts.generate_charts import (
    build_interest_chart, build_weekly_bars, build_related_queries_table, load_spikes,
)


def load_latest_file(directory: Path, filename: str, subdir: str | None = None) -> dict | str | None:
    """Load a file from the most recent dated subdirectory."""
    dirs = sorted(d for d in directory.iterdir() if d.is_dir())
    for d in reversed(dirs):
        target = d / subdir if subdir else d
        path = target / filename
        if path.exists():
            if filename.endswith(".json"):
                with open(path) as f:
                    return json.load(f)
            else:
                with open(path) as f:
                    return f.read()
    return None


def build():
    """Build all site pages."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()

    # --- National data ---
    iot_data = load_latest_file(RAW_DIR, "interest_over_time.json") or {}
    rq_data = load_latest_file(RAW_DIR, "related_queries.json") or {}
    news_data = load_latest_file(RAW_DIR, "news.json") or {}
    analysis = load_latest_file(PROCESSED_DIR, "weekly_analysis.json")
    sentiment = load_latest_file(PROCESSED_DIR, "sentiment_analysis.json")

    # Add enriched fields to analysis
    if analysis:
        winner_code = analysis.get("search_winner", "")
        analysis["search_winner_name"] = ENTITIES.get(winner_code, {}).get("short_name", winner_code)

    # Load narrative and spike annotations
    narrative_md = load_latest_file(PROCESSED_DIR, "narrative.md")
    narrative_html = markdown.markdown(narrative_md) if narrative_md else None
    spikes = load_spikes()

    # Generate national charts
    charts = {
        "interest_over_time": build_interest_chart(iot_data, spikes) if iot_data else "<p>No data yet.</p>",
        "weekly_bars": build_weekly_bars(iot_data) if iot_data else "<p>No data yet.</p>",
        "related_queries": build_related_queries_table(rq_data) if rq_data else "<p>No data yet.</p>",
    }

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
    html = tpl.render(**common_ctx, page="analysis", narrative=narrative_html)
    with open(OUTPUT_DIR / "analysis.html", "w") as f:
        f.write(html)

    # Build news page
    tpl = env.get_template("xreport.html")
    html = tpl.render(
        **common_ctx,
        page="xreport",
        news=news_data,
        spikes=spikes,
    )
    with open(OUTPUT_DIR / "xreport.html", "w") as f:
        f.write(html)

    # --- Victoria data ---
    vic_iot = load_latest_file(RAW_DIR, "interest_over_time.json", subdir="victoria") or {}
    vic_rq = load_latest_file(RAW_DIR, "related_queries.json", subdir="victoria") or {}
    vic_news = load_latest_file(RAW_DIR, "news.json", subdir="victoria") or {}
    vic_analysis = load_latest_file(PROCESSED_DIR, "weekly_analysis.json", subdir="victoria")
    vic_sentiment = load_latest_file(PROCESSED_DIR, "sentiment_analysis.json", subdir="victoria")
    vic_spikes = load_spikes(subdir="victoria")

    if vic_analysis:
        winner_code = vic_analysis.get("search_winner", "")
        vic_analysis["search_winner_name"] = VIC_ENTITIES.get(winner_code, {}).get("short_name", winner_code)

    # Enrich VIC entities with colors
    vic_entities_with_colors = {}
    for code, ent in VIC_ENTITIES.items():
        vic_entities_with_colors[code] = {**ent, "color": VIC_PARTY_COLORS[code]}

    # Generate Victoria charts
    vic_charts = None
    if vic_iot:
        vic_charts = {
            "interest_over_time": build_interest_chart(
                vic_iot, vic_spikes,
                entities=VIC_ENTITIES, party_colors=VIC_PARTY_COLORS,
                title="Victoria — Political Party Search Interest",
            ),
            "weekly_bars": build_weekly_bars(
                vic_iot,
                entities=VIC_ENTITIES, party_colors=VIC_PARTY_COLORS,
                title_prefix="Victoria — Average Search Interest",
            ),
            "related_queries": build_related_queries_table(
                vic_rq,
                entities=VIC_ENTITIES, party_colors=VIC_PARTY_COLORS,
            ),
        }

    # Build Victoria page
    tpl = env.get_template("victoria.html")
    html = tpl.render(
        updated=today,
        entities=entities_with_colors,
        page="victoria",
        vic_entities=vic_entities_with_colors,
        vic_analysis=vic_analysis,
        vic_charts=vic_charts,
        vic_news=vic_news,
        vic_spikes=vic_spikes,
        vic_sentiment=vic_sentiment,
    )
    with open(OUTPUT_DIR / "victoria.html", "w") as f:
        f.write(html)

    print(f"Site built to {OUTPUT_DIR}")


def main():
    build()


if __name__ == "__main__":
    main()
