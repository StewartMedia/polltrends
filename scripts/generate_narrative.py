"""Generate weekly narrative analysis using local LLM (LM Studio / Qwen 3.5 27B).

Feeds all real data (trends, spikes, news, sentiment) into the model and asks it
to write a narrative connecting news events to search interest movements.

Pre-computes rankings and key facts so the LLM cannot misinterpret the raw numbers.
"""
import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (
    ENTITIES, RAW_DIR, PROCESSED_DIR, LM_STUDIO_MODEL, LM_STUDIO_URL,
    find_latest_snapshot_date, load_snapshot_file,
)

LM_STUDIO_TIMEOUT = int(os.getenv("LM_STUDIO_TIMEOUT", "90"))
LM_STUDIO_MAX_TOKENS = int(os.getenv("LM_STUDIO_MAX_TOKENS", "700"))
LM_STUDIO_TEMPERATURE = float(os.getenv("LM_STUDIO_TEMPERATURE", "0.2"))
MAX_NEWS_ARTICLES_PER_PARTY = int(os.getenv("NARRATIVE_MAX_NEWS_PER_PARTY", "2"))
MAX_SPIKES = int(os.getenv("NARRATIVE_MAX_SPIKES", "6"))
MAX_SPIKE_NEWS_TITLES = int(os.getenv("NARRATIVE_MAX_SPIKE_NEWS_TITLES", "1"))

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


def _truncate(text: str, limit: int) -> str:
    """Trim text without cutting through the middle of a word where possible."""
    if len(text) <= limit:
        return text

    clipped = text[: limit - 3].rsplit(" ", 1)[0].rstrip()
    return (clipped or text[: limit - 3]).rstrip() + "..."


def build_prompt_data(snapshot_date: str) -> dict:
    """Gather all data for the narrative prompt, with pre-computed rankings."""
    # Interest over time - last 7 days + pre-compute rankings
    interest_table = "No data available."
    verified_facts = "No data available."
    iot = load_snapshot_file(RAW_DIR, snapshot_date, "interest_over_time.json") or {}
    records = iot.get("data", [])[-7:]
    if records:

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
    spikes = load_snapshot_file(PROCESSED_DIR, snapshot_date, "spikes.json") or []
    if spikes:
        lines = []
        for s in spikes[:MAX_SPIKES]:
            news_str = ""
            if s.get("news"):
                titles = [_truncate(n["title"], 110) for n in s["news"][:MAX_SPIKE_NEWS_TITLES]]
                news_str = f" | Related news: {'; '.join(titles)}"
            lines.append(
                f"- {s['date']}: {s['party_name']} scored {s['value']} "
                f"({s['ratio']}x above average){news_str}"
            )
        spikes_summary = "\n".join(lines)

    # News headlines
    news_summary = "No news data available."
    news = load_snapshot_file(RAW_DIR, snapshot_date, "news.json") or {}
    lines = []
    for code, ent in ENTITIES.items():
        articles = news.get(code, [])[:MAX_NEWS_ARTICLES_PER_PARTY]
        if articles:
            lines.append(f"\n### {ent['short_name']}")
            for a in articles:
                lines.append(
                    f"- [{a['date']}] {_truncate(a['title'], 120)} ({a.get('source', '')})"
                )
    if lines:
        news_summary = "\n".join(lines)

    # Sentiment
    sentiment_summary = "No sentiment data available."
    sentiment = load_snapshot_file(PROCESSED_DIR, snapshot_date, "sentiment_analysis.json") or {}
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
    snapshot_date = find_latest_snapshot_date(
        raw_required=["interest_over_time.json", "news.json"],
        processed_required=["spikes.json", "sentiment_analysis.json", "weekly_analysis.json"],
    )
    if not snapshot_date:
        print("ERROR: No complete snapshot found for narrative generation.")
        return ""

    data = build_prompt_data(snapshot_date)
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
                "temperature": LM_STUDIO_TEMPERATURE,
                "max_tokens": LM_STUDIO_MAX_TOKENS,
            },
            timeout=LM_STUDIO_TIMEOUT,
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
    print(f"Using LM Studio model: {LM_STUDIO_MODEL}")
    print(
        f"Request settings: max_tokens={LM_STUDIO_MAX_TOKENS}, "
        f"temperature={LM_STUDIO_TEMPERATURE}, timeout={LM_STUDIO_TIMEOUT}s"
    )

    # Print the verified facts so the user can see what the LLM was given
    snapshot_date = find_latest_snapshot_date(
        raw_required=["interest_over_time.json", "news.json"],
        processed_required=["spikes.json", "sentiment_analysis.json", "weekly_analysis.json"],
    )
    if not snapshot_date:
        print("No complete snapshot found.")
        return ""

    data = build_prompt_data(snapshot_date)
    print(f"\nVerified facts:\n{data['verified_facts']}\n")
    prompt = NARRATIVE_PROMPT.format(**data)
    print(f"Prompt size: {len(prompt)} chars / {len(prompt.split())} words\n")

    narrative = generate_narrative()

    if not narrative:
        print("No narrative generated.")
        return ""

    # Save
    out_dir = PROCESSED_DIR / snapshot_date
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "narrative.md", "w") as f:
        f.write(narrative)

    with open(out_dir / "narrative.json", "w") as f:
        json.dump({"date": snapshot_date, "narrative": narrative, "model": LM_STUDIO_MODEL}, f, indent=2)

    print(f"Narrative saved to {out_dir}")
    print(f"\n{narrative}")
    return narrative


if __name__ == "__main__":
    main()
