"""Build the static site (docs/) from the latest snapshots."""
import hashlib
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (  # noqa: E402
    ENTITIES, OUTPUT_DIR, PROCESSED_DIR, RAW_DIR, SITE_DIR, SITE_URL, TEMPLATES_DIR, VIC_ENTITIES,
    VIC_LEADERS, load_latest_file, now_local, today_local,
)
from scripts import generate_charts as charts  # noqa: E402
from scripts.generate_narrative import article  # noqa: E402
from scripts.generate_og_image import generate_og_image  # noqa: E402
from scripts.vic_model import TIPPING_BAND  # noqa: E402

PARTY_COLORS = {"ALP": "#F0524A", "LIB": "#3D8BFD", "NAT": "#F2C230", "LNP": "#3D8BFD",
                "GRN": "#3FCB6E", "IND": "#9AA4B2", "PHON": "#FF8A1F", "ONP": "#FF8A1F"}
SENTENCE = {"ALP": "Labor", "LIB": "The Liberals", "GRN": "The Greens", "PHON": "One Nation", "NAT": "The Nationals"}
MID = {"ALP": "Labor", "LIB": "the Liberals", "GRN": "the Greens", "PHON": "One Nation", "NAT": "the Nationals"}


# ---------- helpers ----------
def safe_url(url: str) -> str:
    p = urlparse(url or "")
    return url if p.scheme in ("http", "https") and p.netloc else ""


def clean_articles(items):
    if isinstance(items, dict):
        return {k: clean_articles(v) for k, v in items.items()}
    if isinstance(items, list):
        return [{**a, "url": safe_url(a.get("url", ""))} if isinstance(a, dict) else a for a in items]
    return items


def fmt_day(iso) -> str:
    return date.fromisoformat(str(iso)[:10]).strftime("%-d %b") if iso else ""


def fmt_day_long(iso) -> str:
    return date.fromisoformat(str(iso)[:10]).strftime("%-d %B %Y") if iso else ""


def month(iso) -> str:
    return date.fromisoformat(str(iso)[:10]).strftime("%b")


def day(iso) -> str:
    return date.fromisoformat(str(iso)[:10]).strftime("%-d")


def asset_hash(*paths: Path) -> str:
    h = hashlib.md5()
    for p in paths:
        h.update(p.read_bytes())
    return h.hexdigest()[:8]


def copy_assets() -> str:
    assets = OUTPUT_DIR / "assets"
    (assets / "fonts").mkdir(parents=True, exist_ok=True)
    for f in (SITE_DIR / "static").iterdir():
        shutil.copy2(f, assets / f.name)
    for f in (assets / "fonts").glob("*.ttf"):
        f.unlink()  # web pages use the subset woff2 files; TTFs are only for share images
    for f in (SITE_DIR / "webfonts").glob("*.woff2"):
        shutil.copy2(f, assets / "fonts" / f.name)
    shutil.copy2(SITE_DIR / "static" / "favicon.svg", OUTPUT_DIR / "favicon.svg")
    return asset_hash(SITE_DIR / "static" / "site.css", SITE_DIR / "static" / "site.js")


# ---------- headlines ----------
def national_headline(summary: dict) -> tuple[Markup, str, str]:
    if not summary:
        return Markup("Who is Australia searching for?"), "", ""
    s, leader, runner = summary["stats"], summary["leader"], summary["runner_up"]
    lead_name = ENTITIES[leader]["short_name"]
    ratio = summary.get("lead_ratio") or 0
    share = s[leader]["share"]
    if ratio and ratio < 1.15:
        h = Markup("<em>Neck and neck</em> in the search race.")
    elif share >= 50:
        h = Markup(f"{escape(lead_name)} <em>owns</em> the conversation.")
    else:
        h = Markup(f"{escape(lead_name)} <em>leads</em> the search race.")
    lede = (f"{SENTENCE.get(leader, lead_name)} drew {share:.0f}% of all search interest in Australia's "
            f"main parties in the week to {fmt_day_long(summary['period']['end'])}, "
            f"{ratio:.1f} times {MID.get(runner, runner)}. "
            f"That is attention, not support: the headlines below show what drove it.")
    plain = f"{lead_name} leads Australian political searches"
    return h, lede, plain


def victoria_headline(model: dict | None) -> tuple[Markup, str]:
    if not model or model["average"]["tpp"]["ALP"] is None:
        return Markup("Victoria votes on <em>28 November</em>."), "Polls and seats will appear after the next run."
    avg = model["average"]
    tpp, onp = avg["tpp"], avg["primary"].get("ONP") or 0
    leader = "The Coalition" if tpp["LNP"] > tpp["ALP"] else "Labor"
    h = Markup(f"{leader} in front. <em>One Nation</em> in the mix.") if onp >= 15 else Markup(f"{leader} <em>in front</em>.")
    swing = model["swing_to_lnp"]
    lede = (f"Polls average {tpp['LNP']}–{tpp['ALP']} two-party preferred, "
            f"{article(swing)} {abs(swing):.1f}-point swing {'to the Coalition' if swing > 0 else 'to Labor'} since 2022. "
            f"With One Nation on {onp:.0f}% of the primary vote, the classic pendulum and seat-by-seat "
            f"modelling tell very different stories. Explore both below.")
    return h, lede


def seat_payload(model: dict) -> Markup:
    keep = ("seat", "member", "holder", "margin", "vs", "classic", "region", "note", "tier")
    data = {"majority": model["majority"], "swing": model["swing_to_lnp"],
            "seats": [{k: s.get(k) for k in keep} for s in model["seats"]]}
    return Markup(json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))


def updated_labels(run_status: dict | None) -> tuple[str, str, bool]:
    if run_status and run_status.get("finished_at"):
        ts = datetime.fromisoformat(run_status["finished_at"])
    else:
        ts = now_local()
    short = ts.strftime("%-d %b, %-I:%M%p").replace("AM", "am").replace("PM", "pm")
    long = ts.strftime("%-d %B %Y at %-I:%M%p %Z").replace("AM", "am").replace("PM", "pm")
    return short, long, False


# ---------- build ----------
def build():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters.update(fmt_day=fmt_day, fmt_day_long=fmt_day_long, month=month, day=day)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    version = copy_assets()

    # National
    _, summary = load_latest_file(PROCESSED_DIR, "weekly_analysis.json")
    iot_date, iot = load_latest_file(RAW_DIR, "interest_over_time.json")
    _, related = load_latest_file(RAW_DIR, "related_queries.json")
    _, news = load_latest_file(RAW_DIR, "news.json")
    _, spikes = load_latest_file(PROCESSED_DIR, "spikes.json")
    _, briefing = load_latest_file(PROCESSED_DIR, "briefing.json")
    _, run_status = load_latest_file(PROCESSED_DIR, "run_status.json")

    # Victoria
    _, model = load_latest_file(PROCESSED_DIR, "seat_model.json", subdir="victoria")
    _, vic_summary = load_latest_file(PROCESSED_DIR, "weekly_analysis.json", subdir="victoria")
    _, leaders_summary = load_latest_file(PROCESSED_DIR, "leaders_analysis.json", subdir="victoria")
    _, vic_iot = load_latest_file(RAW_DIR, "interest_over_time.json", subdir="victoria")
    _, leaders_iot = load_latest_file(RAW_DIR, "leaders_interest.json", subdir="victoria")
    _, vic_related = load_latest_file(RAW_DIR, "related_queries.json", subdir="victoria")
    _, vic_news = load_latest_file(RAW_DIR, "news.json", subdir="victoria")
    _, seat_news = load_latest_file(RAW_DIR, "seat_news.json", subdir="victoria")
    _, vic_spikes = load_latest_file(PROCESSED_DIR, "spikes.json", subdir="victoria")
    _, polls = load_latest_file(RAW_DIR, "polls.json", subdir="victoria")

    news, vic_news, seat_news = clean_articles(news or {}), clean_articles(vic_news or {}), clean_articles(seat_news or {})
    spikes = [{**s, "news": clean_articles(s.get("news", []))} for s in (spikes or [])]
    vic_spikes = [{**s, "news": clean_articles(s.get("news", []))} for s in (vic_spikes or [])]

    updated_short, updated_long, _ = updated_labels(run_status)
    stale = bool(iot_date and (date.fromisoformat(today_local()) - date.fromisoformat(iot_date)).days > 2)
    health = sorted((run_status or {}).get("steps", {}).items())
    health = [(k.replace("_", " "), v) for k, v in health]
    vic_days = model["days_to_go"] if model else (date(2026, 11, 28) - date.fromisoformat(today_local())).days

    sparks = {c: charts.sparkline_svg(summary["stats"][c]["spark"], ENTITIES[c]["color"]) for c in ENTITIES} if summary else {}
    vic_sparks = ({c: charts.sparkline_svg(vic_summary["stats"][c]["spark"], VIC_ENTITIES[c]["color"]) for c in VIC_ENTITIES}
                  if vic_summary else {})

    headline, lede, plain_headline = national_headline(summary)
    vic_h, vic_lede = victoria_headline(model)

    common = dict(
        site_url=SITE_URL, asset_version=version, plotly_js=charts.PLOTLY_JS_URL,
        updated_short=updated_short, updated_long=updated_long, stale=stale, health=health,
        vic_days=vic_days, entities=ENTITIES, vic_entities=VIC_ENTITIES, leaders=VIC_LEADERS,
        party_colors=PARTY_COLORS, summary=summary, model=model, og_image="og-image.png",
    )

    def render(template: str, out: str, **ctx):
        context = {**common, "page_path": "" if out == "index.html" else out, **ctx}
        html = env.get_template(template).render(**context)
        (OUTPUT_DIR / out).write_text(html)

    render("index.html", "index.html", page="index", uses_plotly=True,
           title="PolTrends Australia: who Australians are searching for",
           description=f"{plain_headline}. Daily Google Trends tracking of Australian political parties, with the headlines behind every spike.",
           share_text=f"{plain_headline} this week. Daily search data on PolTrends Australia",
           headline=headline, lede=lede, sparks=sparks, related=related or {}, news=news, spikes=spikes,
           charts={
               "interest": charts.interest_chart(iot, ENTITIES, "chart-national", spikes),
               "share": charts.share_chart(iot, ENTITIES, "chart-share"),
           })

    other = sorted([s for s in (model or {}).get("seats", []) if not s["classic"]], key=lambda s: (s["holder"], s["margin"]))
    vic_desc = (f"Victoria votes 28 November 2026. Poll average {model['average']['tpp']['LNP']}–{model['average']['tpp']['ALP']} "
                f"Coalition v Labor. Swing the pendulum across all 88 seats." if model else "Victorian election tracker.")
    render("victoria.html", "victoria.html", page="victoria", uses_plotly=True,
           title="Victoria 2026: polls, seats and search | PolTrends Australia",
           description=vic_desc, share_text=f"Victoria votes in {vic_days} days. Polls, seats and search on PolTrends",
           vic_headline=vic_h, vic_lede=vic_lede, vic_summary=vic_summary, leaders_summary=leaders_summary,
           vic_sparks=vic_sparks, vic_related=vic_related or {}, vic_news=vic_news, seat_news=seat_news,
           vic_spikes=vic_spikes, other_contests=other, tipping_band=int(TIPPING_BAND),
           seat_json=seat_payload(model) if model else Markup("{}"),
           og_image="og-victoria.png",
           charts={
               "polls": charts.poll_trend_chart(polls["assembly"], model["trend"], model["events"], "chart-polls")
               if polls and model else Markup(""),
               "leaders": charts.interest_chart(leaders_iot, VIC_LEADERS, "chart-leaders", height=340),
               "vic_interest": charts.interest_chart(vic_iot, VIC_ENTITIES, "chart-vic", vic_spikes),
           })

    render("analysis.html", "analysis.html", page="analysis", uses_plotly=False,
           title="The briefing | PolTrends Australia",
           description="A plain-English weekly briefing built from search data, headlines and published polls.",
           share_text="This week's political search briefing on PolTrends Australia", briefing=briefing)

    render("xreport.html", "xreport.html", page="xreport", uses_plotly=False,
           title="Political headlines and search spikes | PolTrends Australia",
           description="Latest Australian political headlines by party, and the search spikes they lined up with.",
           share_text="The stories behind Australia's political searches", news=news, spikes=spikes, vic_news=vic_news)

    generate_og_image(OUTPUT_DIR / "og-image.png", summary=summary, model=model, kind="national")
    generate_og_image(OUTPUT_DIR / "og-victoria.png", summary=vic_summary, model=model, kind="victoria")
    print(f"Site built to {OUTPUT_DIR} (search data {iot_date}, assets v{version})")
    return str(OUTPUT_DIR)


def main():
    build()


if __name__ == "__main__":
    main()
