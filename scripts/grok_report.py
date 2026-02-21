"""Generate daily Australian political X/Twitter summary via Grok API."""
import json
import os
import sys
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import GROK_API_URL, GROK_MODEL, RAW_DIR

GROK_API_KEY = os.environ.get("GROK_API_KEY", "")

DAILY_PROMPT = """You are a concise Australian political analyst. Summarise the key political
discussion on X/Twitter in Australia over the last 24 hours.

Focus on these parties:
- Australian Labor Party (ALP)
- Liberal Party of Australia
- Australian Greens
- Pauline Hanson's One Nation (PHON)

For each party that had notable activity, provide:
1. Key topics/events being discussed
2. Sentiment (positive/negative/mixed) with brief reasoning
3. Any trending hashtags or viral posts

Format as markdown. Be factual and concise. If a party had no notable activity, say so briefly.
End with a one-line "Front of Mind" verdict: which party dominated X discussion today and why."""


def fetch_grok_report() -> str:
    """Call Grok API for daily political summary."""
    if not GROK_API_KEY:
        return "_Grok API key not configured. Set GROK_API_KEY environment variable._"

    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": GROK_MODEL,
        "messages": [
            {"role": "user", "content": DAILY_PROMPT}
        ],
        "temperature": 0.3,
    }

    resp = requests.post(GROK_API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()

    data = resp.json()
    return data["choices"][0]["message"]["content"]


def main():
    today = date.today().isoformat()
    print(f"Generating Grok X report for {today}...")

    report = fetch_grok_report()

    out_dir = RAW_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "grok_report.md", "w") as f:
        f.write(report)

    # Also save as JSON for the site builder
    with open(out_dir / "grok_report.json", "w") as f:
        json.dump({"date": today, "report": report}, f, indent=2)

    print(f"Grok report saved to {out_dir}")
    return report


if __name__ == "__main__":
    main()
