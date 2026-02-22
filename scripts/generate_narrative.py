"""Generate weekly narrative analysis using local LLM (LM Studio / Qwen 2.5 7B).

Feeds all real data (trends, spikes, news, sentiment) into the model and asks it
to write a narrative connecting news events to search interest movements.

Pre-computes rankings and key facts so the LLM cannot misinterpret the raw numbers.
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

SYSTEM_PROMPT = """You are an Australian political data analyst. You write factual weekly briefings
based STRICTLY on the pre-computed facts and data provided. You MUST NOT contradict the rankings
or numbers given in the VERIFIED FACTS section. If the facts say party X ranked #1, you must say
party X ranked #1. Do not guess, infer, or invent any information not in the data."""

NARRATIVE_PROMPT = """Write a weekly briefing on Australian political party search interest.

## VERIFIED FACTS (you MUST use these exactly — do not contradict)
{verified_facts}

## Daily Search Interest Data
{interest_table}

## Detected Spikes
{spikes_summary}

## News Headlines This Week
{news_summary}

## Query Sentiment
{sentiment_summary}

---

Write a 3-5 paragraph weekly analysis in markdown format. Rules:
1. Open with the #1 ranked party by search interest as stated in VERIFIED FACTS
2. State the exact average scores and rankings from VERIFIED FACTS
3. Connect specific news headlines to observed spikes or changes
4. Note any interesting patterns in sentiment
5. Close with a brief forward-looking observation

CRITICAL: The rankings in VERIFIED FACTS are computed directly from the data and are correct.
You must not reorder them or claim a different party was #1.
Australian English. No fluff. Be concise."""


def build_prompt_data() -> dict:
    """Gather all data for the narrative prompt, with pre-computed rankings."""
    raw_dirs = sorted(d for d in RAW_DIR.iterdir() if d.is_dir())
    proc_dirs = sorted(d for d in PROCESSED_DIR.iterdir() if d.is_dir())

    latest_raw = raw_dirs[-1] if raw_dirs else None
    latest_proc = proc_dirs[-1] if proc_dirs else None

    # Interest over time - last 7 days + pre-compute rankings
    interest_table = "No data available."
    verified_facts = "No data available."
    if latest_raw:
        iot_path = latest_raw / "interest_over_time.json"
        if iot_path.exists():
            with open(iot_path) as f:
                iot = json.load(f)
            records = iot.get("data", [])[-7:]

            # Build readable table
            lines = []
            header = "Date       | " + " | ".join(
                f"{ENTITIES[c]['short_name']:>12}" for c in ENTITIES
            )
            lines.append(header)
            lines.append("-" * len(header))
            for r in records:
                row = f"{r['date']} | " + " | ".join(
                    f"{r.get(code, 0):>12}" for code in ENTITIES
                )
                lines.append(row)
            interest_table = "\n".join(lines)

            # Pre-compute verified facts the LLM MUST use
            averages = {}
            for code in ENTITIES:
                vals = [r.get(code, 0) for r in records]
                averages[code] = round(sum(vals) / len(vals), 1)

            # Sort by average descending
            ranked = sorted(averages.items(), key=lambda x: x[1], reverse=True)

            # Build verified facts
            fact_lines = []
            period_start = records[0]["date"] if records else "N/A"
            period_end = records[-1]["date"] if records else "N/A"
            fact_lines.append(f"- Period: {period_start} to {period_end}")
            fact_lines.append(f"- RANKING BY AVERAGE SEARCH INTEREST (highest to lowest):")
            for rank, (code, avg) in enumerate(ranked, 1):
                name = ENTITIES[code]["short_name"]
                vals = [r.get(code, 0) for r in records]
                peak = max(vals)
                low = min(vals)
                peak_date = records[vals.index(peak)]["date"]
                fact_lines.append(
                    f"  #{rank}: {name} — average {avg}, peak {peak} on {peak_date}, low {low}"
                )

            winner_name = ENTITIES[ranked[0][0]]["short_name"]
            fact_lines.append(f"- THE #1 PARTY THIS WEEK IS: {winner_name} (avg: {ranked[0][1]})")
            fact_lines.append(f"- THE #2 PARTY THIS WEEK IS: {ENTITIES[ranked[1][0]]['short_name']} (avg: {ranked[1][1]})")
            if len(ranked) > 2:
                fact_lines.append(f"- THE #3 PARTY THIS WEEK IS: {ENTITIES[ranked[2][0]]['short_name']} (avg: {ranked[2][1]})")
            if len(ranked) > 3:
                fact_lines.append(f"- THE #4 PARTY THIS WEEK IS: {ENTITIES[ranked[3][0]]['short_name']} (avg: {ranked[3][1]})")

            verified_facts = "\n".join(fact_lines)

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
        "verified_facts": verified_facts,
        "interest_table": interest_table,
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
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
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

    # Print the verified facts so the user can see what the LLM was given
    data = build_prompt_data()
    print(f"\nVerified facts:\n{data['verified_facts']}\n")

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
