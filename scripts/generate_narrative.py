"""Generate weekly narrative analysis using local LLM (LM Studio / Qwen 2.5 7B).

Feeds all real data (trends, spikes, news, sentiment) into the model and asks it
to write a narrative connecting news events to search interest movements.
"""
import json
import sys
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import ENTITIES, RAW_DIR, PROCESSED_DIR

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
LM_STUDIO_MODEL = "qwen2.5-7b-instruct"

NARRATIVE_PROMPT = """You are an Australian political analyst writing a weekly briefing on how news events
drove public search interest for political parties this week.

You MUST only reference facts from the data provided below. Do not invent any events, names,
or details. If the data doesn't explain a spike, say the cause is unclear from available data.

## Search Interest Data (last 7 days)
{interest_summary}

## Detected Spikes
{spikes_summary}

## News Headlines This Week
{news_summary}

## Query Sentiment
{sentiment_summary}

---

Write a 3-5 paragraph weekly analysis in markdown format. Structure:
1. Open with which party dominated search interest this week and the overall trend
2. Connect specific news stories to observed spikes or changes in search interest
3. Note any interesting patterns in related search queries and sentiment
4. Close with a brief forward-looking observation

Keep it factual, concise, and analytical. Australian English. No fluff."""


def build_prompt_data() -> dict:
    """Gather all data for the narrative prompt."""
    raw_dirs = sorted(d for d in RAW_DIR.iterdir() if d.is_dir())
    proc_dirs = sorted(d for d in PROCESSED_DIR.iterdir() if d.is_dir())

    latest_raw = raw_dirs[-1] if raw_dirs else None
    latest_proc = proc_dirs[-1] if proc_dirs else None

    # Interest over time - last 7 days
    interest_summary = "No data available."
    if latest_raw:
        iot_path = latest_raw / "interest_over_time.json"
        if iot_path.exists():
            with open(iot_path) as f:
                iot = json.load(f)
            records = iot.get("data", [])[-7:]
            lines = []
            for r in records:
                parts = [f"{code}: {r.get(code, 0)}" for code in ENTITIES]
                lines.append(f"{r['date']} — {', '.join(parts)}")
            if lines:
                interest_summary = "\n".join(lines)

    # Spikes
    spikes_summary = "No significant spikes detected."
    if latest_proc:
        spikes_path = latest_proc / "spikes.json"
        if spikes_path.exists():
            with open(spikes_path) as f:
                spikes = json.load(f)
            if spikes:
                lines = []
                for s in spikes:
                    news_str = ""
                    if s.get("news"):
                        titles = [n["title"] for n in s["news"][:2]]
                        news_str = f" | Related news: {'; '.join(titles)}"
                    lines.append(
                        f"- {s['date']}: {s['party_name']} scored {s['value']} "
                        f"({s['ratio']}x above average){news_str}"
                    )
                spikes_summary = "\n".join(lines)

    # News headlines
    news_summary = "No news data available."
    if latest_raw:
        news_path = latest_raw / "news.json"
        if news_path.exists():
            with open(news_path) as f:
                news = json.load(f)
            lines = []
            for code, ent in ENTITIES.items():
                articles = news.get(code, [])[:5]
                if articles:
                    lines.append(f"\n### {ent['short_name']}")
                    for a in articles:
                        lines.append(f"- [{a['date']}] {a['title']} ({a.get('source', '')})")
            if lines:
                news_summary = "\n".join(lines)

    # Sentiment
    sentiment_summary = "No sentiment data available."
    if latest_proc:
        sent_path = latest_proc / "sentiment_analysis.json"
        if sent_path.exists():
            with open(sent_path) as f:
                sentiment = json.load(f)
            lines = []
            for code, data in sentiment.items():
                counts = data.get("sentiment_counts", {})
                score = data.get("sentiment_score", 0)
                lines.append(
                    f"- {data['party']}: {counts.get('positive', 0)} positive, "
                    f"{counts.get('neutral', 0)} neutral, {counts.get('negative', 0)} negative "
                    f"(score: {score:+.2f})"
                )
            if lines:
                sentiment_summary = "\n".join(lines)

    return {
        "interest_summary": interest_summary,
        "spikes_summary": spikes_summary,
        "news_summary": news_summary,
        "sentiment_summary": sentiment_summary,
    }


def generate_narrative() -> str:
    """Generate the weekly narrative via local LLM."""
    data = build_prompt_data()
    prompt = NARRATIVE_PROMPT.format(**data)

    try:
        resp = requests.post(
            LM_STUDIO_URL,
            json={
                "model": LM_STUDIO_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
                "max_tokens": 1500,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except requests.ConnectionError:
        print("ERROR: Cannot connect to LM Studio at localhost:1234")
        print("Make sure LM Studio is running with the API server enabled.")
        return ""
    except Exception as e:
        print(f"ERROR: Narrative generation failed: {e}")
        return ""


def main():
    print("Generating weekly narrative via local LLM...")
    narrative = generate_narrative()

    if not narrative:
        print("No narrative generated.")
        return ""

    # Save
    today = date.today().isoformat()
    out_dir = PROCESSED_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "narrative.md", "w") as f:
        f.write(narrative)

    with open(out_dir / "narrative.json", "w") as f:
        json.dump({"date": today, "narrative": narrative}, f, indent=2)

    print(f"Narrative saved to {out_dir}")
    print(f"\n{narrative}")
    return narrative


if __name__ == "__main__":
    main()
