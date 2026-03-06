"""Build the static site from templates and data."""
import html as html_lib
import sys
from pathlib import Path
from urllib.parse import urlparse

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (
    ENTITIES, PARTY_COLORS, RAW_DIR, PROCESSED_DIR, TEMPLATES_DIR, OUTPUT_DIR,
    VIC_ENTITIES, VIC_PARTY_COLORS, find_latest_snapshot_date, load_snapshot_file,
)
from scripts.generate_charts import (
    build_interest_chart, build_weekly_bars, build_related_queries_table, load_spikes,
)
from scripts.generate_og_image import generate_og_image


def sanitize_url(url: str) -> str:
    """Allow only absolute HTTP(S) URLs in rendered content."""
    parsed = urlparse(url or "")
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url
    return ""


def sanitize_news_items(news_data: dict | None) -> dict:
    """Strip unsafe links from fetched news items."""
    if not news_data:
        return {}

    sanitized = {}
    for code, articles in news_data.items():
        sanitized[code] = []
        for article in articles:
            sanitized[code].append({
                **article,
                "url": sanitize_url(article.get("url", "")),
            })
    return sanitized


def sanitize_spikes(spikes: list[dict] | None) -> list[dict]:
    """Strip unsafe links from spike-associated articles."""
    if not spikes:
        return []

    sanitized = []
    for spike in spikes:
        spike_copy = {**spike}
        spike_copy["news"] = [
            {**article, "url": sanitize_url(article.get("url", ""))}
            for article in spike.get("news", [])
        ]
        sanitized.append(spike_copy)
    return sanitized


def build():
    """Build all site pages."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    national_snapshot = find_latest_snapshot_date(
        raw_required=["interest_over_time.json", "related_queries.json", "news.json"],
        processed_required=["weekly_analysis.json", "sentiment_analysis.json", "spikes.json"],
    )
    if not national_snapshot:
        raise FileNotFoundError("No complete national snapshot found to build the site.")

    # --- National data ---
    iot_data = load_snapshot_file(RAW_DIR, national_snapshot, "interest_over_time.json") or {}
    rq_data = load_snapshot_file(RAW_DIR, national_snapshot, "related_queries.json") or {}
    news_data = sanitize_news_items(
        load_snapshot_file(RAW_DIR, national_snapshot, "news.json") or {}
    )
    analysis = load_snapshot_file(PROCESSED_DIR, national_snapshot, "weekly_analysis.json")
    sentiment = load_snapshot_file(PROCESSED_DIR, national_snapshot, "sentiment_analysis.json")

    # Add enriched fields to analysis
    if analysis:
        winner_code = analysis.get("search_winner", "")
        analysis["search_winner_name"] = ENTITIES.get(winner_code, {}).get("short_name", winner_code)

    # Load narrative and spike annotations
    narrative_md = load_snapshot_file(PROCESSED_DIR, national_snapshot, "narrative.md")
    narrative_html = markdown.markdown(html_lib.escape(narrative_md)) if narrative_md else None
    spikes = sanitize_spikes(load_spikes(snapshot_date=national_snapshot))

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
        "updated": national_snapshot,
        "entities": entities_with_colors,
        "analysis": analysis,
        "sentiment": sentiment,
        "charts": charts,
    }

    # Build share message from latest winner
    winner_name = analysis.get("search_winner_name", "") if analysis else ""
    if winner_name:
        share_msg = f"{winner_name} is the most-searched party this week. See the full data on PolTrends Australia"
    else:
        share_msg = "Which Australian political party are voters searching for most? Check the data"

    # Build index
    tpl = env.get_template("index.html")
    html = tpl.render(
        **common_ctx, page="index",
        og_title="PolTrends Australia — Political Search Trends",
        og_description=f"Daily Google Trends data tracking Australian political parties. {winner_name + ' leads this week.' if winner_name else ''}",
        og_page="",
        share_message=share_msg,
    )
    with open(OUTPUT_DIR / "index.html", "w") as f:
        f.write(html)

    # Build analysis page
    tpl = env.get_template("analysis.html")
    html = tpl.render(
        **common_ctx, page="analysis", narrative=narrative_html,
        og_title="PolTrends Australia — Weekly Analysis",
        og_description="Weekly analysis of Australian political party search interest, sentiment, and news correlation.",
        og_page="analysis.html",
        share_message=share_msg,
    )
    with open(OUTPUT_DIR / "analysis.html", "w") as f:
        f.write(html)

    # Build news page
    tpl = env.get_template("xreport.html")
    html = tpl.render(
        **common_ctx,
        page="xreport",
        news=news_data,
        spikes=spikes,
        og_title="PolTrends Australia — News & Spikes",
        og_description="Latest news headlines and search interest spikes for Australian political parties.",
        og_page="xreport.html",
        share_message=share_msg,
    )
    with open(OUTPUT_DIR / "xreport.html", "w") as f:
        f.write(html)

    # --- Victoria data ---
    victoria_snapshot = find_latest_snapshot_date(
        raw_required=["interest_over_time.json", "related_queries.json", "news.json"],
        processed_required=["weekly_analysis.json", "sentiment_analysis.json", "spikes.json"],
        raw_subdir="victoria",
        processed_subdir="victoria",
    )
    if victoria_snapshot:
        vic_iot = load_snapshot_file(RAW_DIR, victoria_snapshot, "interest_over_time.json", subdir="victoria") or {}
        vic_rq = load_snapshot_file(RAW_DIR, victoria_snapshot, "related_queries.json", subdir="victoria") or {}
        vic_news = sanitize_news_items(
            load_snapshot_file(RAW_DIR, victoria_snapshot, "news.json", subdir="victoria") or {}
        )
        vic_analysis = load_snapshot_file(PROCESSED_DIR, victoria_snapshot, "weekly_analysis.json", subdir="victoria")
        vic_sentiment = load_snapshot_file(PROCESSED_DIR, victoria_snapshot, "sentiment_analysis.json", subdir="victoria")
        vic_spikes = sanitize_spikes(load_spikes(snapshot_date=victoria_snapshot, subdir="victoria"))
    else:
        vic_iot = {}
        vic_rq = {}
        vic_news = {}
        vic_analysis = None
        vic_sentiment = None
        vic_spikes = []

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

    # Victoria share message
    vic_winner = vic_analysis.get("search_winner_name", "") if vic_analysis else ""
    if vic_winner:
        vic_share = f"{vic_winner} leads Victorian political searches this week. See the data"
    else:
        vic_share = "Track Victorian state election search trends — which party are voters looking up?"

    # Build Victoria page
    tpl = env.get_template("victoria.html")
    html = tpl.render(
        updated=victoria_snapshot or national_snapshot,
        entities=entities_with_colors,
        page="victoria",
        vic_entities=vic_entities_with_colors,
        vic_analysis=vic_analysis,
        vic_charts=vic_charts,
        vic_news=vic_news,
        vic_spikes=vic_spikes,
        vic_sentiment=vic_sentiment,
        og_title="PolTrends Australia — Victoria State Election",
        og_description="Track search interest for Victorian political parties ahead of the state election.",
        og_page="victoria.html",
        share_message=vic_share,
    )
    with open(OUTPUT_DIR / "victoria.html", "w") as f:
        f.write(html)

    # Generate OG image for social sharing
    generate_og_image(OUTPUT_DIR / "og-image.png")

    print(
        f"Site built to {OUTPUT_DIR} "
        f"(national snapshot: {national_snapshot}, victoria snapshot: {victoria_snapshot or 'none'})"
    )


def main():
    build()


if __name__ == "__main__":
    main()
