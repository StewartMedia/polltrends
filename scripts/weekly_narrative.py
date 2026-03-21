#!/usr/bin/env python3
"""Self-contained weekly PolTrends narrative update pipeline.

Steps:
1. Verify latest national raw snapshot via config.settings helpers
2. Warn if LM Studio is unavailable at localhost:1234 / configured endpoint
3. Regenerate spikes, sentiment, weekly analysis, and narrative for that snapshot
4. Rebuild the static site
5. Commit and push only the relevant generated changes
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import ENTITIES, LM_STUDIO_MODEL, LM_STUDIO_URL, PROCESSED_DIR, RAW_DIR, ROOT_DIR, find_latest_snapshot_date
from scripts.analyse_sentiment import run_sentiment_analysis
from scripts.build_site import build
from scripts.detect_spikes import run_spike_detection
from scripts.generate_narrative import generate_narrative
from scripts.weekly_analysis import run_weekly_analysis


def check_lm_studio() -> bool:
    """Return True when LM Studio responds on the configured host.

    We probe /v1/models on the same host as LM_STUDIO_URL because that is a cheap,
    reliable readiness check for the local server.
    """
    parsed = urlparse(LM_STUDIO_URL)
    models_url = f"{parsed.scheme}://{parsed.netloc}/v1/models"
    try:
        response = requests.get(models_url, timeout=3)
        response.raise_for_status()
        print(f"LM Studio ready at {models_url} using model setting: {LM_STUDIO_MODEL}")
        return True
    except Exception as exc:
        print(f"WARNING: LM Studio is not reachable at {models_url}: {exc}")
        print("Narrative generation requires the LM Studio API server to be running.")
        return False


def save_narrative(snapshot_date: str, narrative: str) -> None:
    out_dir = PROCESSED_DIR / snapshot_date
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "narrative.md").write_text(narrative)
    (out_dir / "narrative.json").write_text(
        json.dumps(
            {
                "date": snapshot_date,
                "model": LM_STUDIO_MODEL,
                "narrative": narrative,
            },
            indent=2,
        )
        + "\n"
    )


def run_git(command: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(command))
    return subprocess.run(command, cwd=ROOT_DIR, check=check, text=True)


def commit_and_push(snapshot_date: str) -> None:
    run_git(["git", "config", "--local", "user.name", "Hermes Agent"], check=False)
    run_git(["git", "config", "--local", "user.email", "hermes@example.com"], check=False)

    paths_to_add = [
        f"data/processed/{snapshot_date}",
        "docs/index.html",
        "docs/analysis.html",
        "docs/xreport.html",
        "docs/victoria.html",
        "docs/og-image.png",
        "scripts/weekly_narrative.py",
    ]
    run_git(["git", "add", *paths_to_add], check=False)

    status = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT_DIR,
        check=True,
        text=True,
        capture_output=True,
    )
    staged = [line.strip() for line in status.stdout.splitlines() if line.strip()]
    if not staged:
        print("No relevant changes staged; skipping commit.")
        return

    print("Staged files:")
    for path in staged:
        print(f"  - {path}")

    commit = subprocess.run(
        ["git", "commit", "-m", f"Update weekly narrative for {snapshot_date}"],
        cwd=ROOT_DIR,
        check=False,
        text=True,
        capture_output=True,
    )
    print(commit.stdout.strip())
    if commit.returncode != 0 and "nothing to commit" not in commit.stdout.lower() + commit.stderr.lower():
        print(commit.stderr.strip())
        raise subprocess.CalledProcessError(commit.returncode, commit.args)

    run_git(["git", "push", "origin", "main"])


def main() -> int:
    snapshot_date = find_latest_snapshot_date(
        raw_required=["interest_over_time.json", "related_queries.json", "news.json"]
    )
    if not snapshot_date:
        print("ERROR: No raw snapshot with interest_over_time.json, related_queries.json, and news.json was found.")
        print("Suggestion: fetch fresh data first, e.g. python scripts/daily_fetch.py")
        return 1

    raw_dir = RAW_DIR / snapshot_date
    proc_dir = PROCESSED_DIR / snapshot_date

    print(f"Using raw snapshot date: {snapshot_date}")
    proc_dir.mkdir(parents=True, exist_ok=True)

    run_spike_detection(ENTITIES, raw_dir, proc_dir, label="national")
    run_sentiment_analysis(ENTITIES, raw_dir, proc_dir, label="national")
    analysis = run_weekly_analysis(ENTITIES, raw_dir, proc_dir, proc_dir, label="national")
    if not analysis:
        print("ERROR: Weekly analysis could not be generated.")
        return 1

    lm_ok = check_lm_studio()
    if not lm_ok:
        print("Suggestion: start LM Studio at http://localhost:1234 and re-run this script.")
        return 1

    narrative = generate_narrative()
    if not narrative:
        print("ERROR: Narrative generation failed.")
        print("Suggestion: ensure LM Studio has the configured model loaded, or fetch fresh data first.")
        return 1

    save_narrative(snapshot_date, narrative)
    build()
    commit_and_push(snapshot_date)
    print(f"Weekly narrative generated and site rebuilt for {snapshot_date}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
