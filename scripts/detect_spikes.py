"""Detect significant spikes in entity search interest data.

Identifies days where a party's interest is significantly above its rolling average,
then asks Grok to explain the likely cause.
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import ENTITIES, GROK_API_URL, GROK_MODEL, RAW_DIR, PROCESSED_DIR

GROK_API_KEY = os.environ.get("GROK_API_KEY", "")

SPIKE_THRESHOLD = 2.0  # Must be this many times above the rolling average
ROLLING_WINDOW = 7     # Days for rolling average
MIN_ABSOLUTE = 10      # Minimum absolute value to count as a spike (filters noise)


def detect_spikes(iot_data: dict) -> list[dict]:
    """Find significant spikes in interest data."""
    records = iot_data.get("data", [])
    if len(records) < ROLLING_WINDOW + 1:
        return []

    codes = list(ENTITIES.keys())
    spikes = []

    for code in codes:
        values = [r.get(code, 0) for r in records]

        for i in range(ROLLING_WINDOW, len(values)):
            current = values[i]
            window = values[i - ROLLING_WINDOW:i]
            rolling_avg = sum(window) / len(window) if window else 0

            if rolling_avg > 0 and current >= MIN_ABSOLUTE:
                ratio = current / rolling_avg
                if ratio >= SPIKE_THRESHOLD:
                    spikes.append({
                        "date": records[i]["date"],
                        "party_code": code,
                        "party_name": ENTITIES[code]["short_name"],
                        "value": current,
                        "rolling_avg": round(rolling_avg, 1),
                        "ratio": round(ratio, 1),
                        "explanation": None,
                    })

    # Sort by ratio descending, keep top 10 most significant
    spikes.sort(key=lambda s: s["ratio"], reverse=True)
    return spikes[:10]


EXPLAIN_PROMPT_TEMPLATE = """You are an Australian political analyst with access to X/Twitter data.

For each spike in Google search interest below, provide a brief (1-2 sentence) explanation
of what likely caused it. Focus on specific news events, announcements, scandals, or media coverage.

Spikes to explain:
{spikes_text}

Respond as a JSON array of objects with "date", "party_code", and "explanation" keys. Nothing else."""


def explain_spikes(spikes: list[dict]) -> list[dict]:
    """Ask Grok to explain detected spikes."""
    if not spikes:
        return []

    if not GROK_API_KEY:
        for s in spikes:
            s["explanation"] = "Significant spike in search interest"
        return spikes

    spikes_text = "\n".join(
        f"- {s['date']}: {s['party_name']} surged to {s['value']} "
        f"({s['ratio']}x above 7-day average of {s['rolling_avg']})"
        for s in spikes
    )

    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": GROK_MODEL,
        "messages": [{"role": "user", "content": EXPLAIN_PROMPT_TEMPLATE.format(spikes_text=spikes_text)}],
        "temperature": 0.2,
    }

    try:
        resp = requests.post(GROK_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()

        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]

        explanations = json.loads(content)
        exp_map = {(e["date"], e["party_code"]): e["explanation"] for e in explanations}

        for s in spikes:
            key = (s["date"], s["party_code"])
            if key in exp_map:
                s["explanation"] = exp_map[key]
            elif not s["explanation"]:
                s["explanation"] = "Significant spike in search interest"

    except Exception as e:
        print(f"  Grok explanation error: {e}")
        for s in spikes:
            if not s["explanation"]:
                s["explanation"] = "Significant spike in search interest"

    return spikes


def main():
    print("Detecting spikes in trends data...")

    raw_dirs = sorted(d for d in RAW_DIR.iterdir() if d.is_dir())
    if not raw_dirs:
        print("No data found.")
        return []

    latest = raw_dirs[-1]
    with open(latest / "interest_over_time.json") as f:
        iot_data = json.load(f)

    spikes = detect_spikes(iot_data)
    print(f"Found {len(spikes)} significant spikes")

    if spikes:
        for s in spikes:
            print(f"  {s['date']} - {s['party_name']}: {s['value']} ({s['ratio']}x avg)")

    spikes = explain_spikes(spikes)

    # Save
    today = date.today().isoformat()
    out_dir = PROCESSED_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "spikes.json", "w") as f:
        json.dump(spikes, f, indent=2)

    print(f"Spikes saved to {out_dir}")
    return spikes


if __name__ == "__main__":
    main()
