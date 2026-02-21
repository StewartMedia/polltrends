"""Weekly pipeline: full analysis including sentiment + spikes + rebuild site."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.fetch_trends import main as fetch_trends
from scripts.detect_spikes import main as detect_spikes
from scripts.grok_report import main as grok_report
from scripts.analyse_sentiment import main as analyse_sentiment
from scripts.weekly_analysis import main as weekly_analysis
from scripts.build_site import main as build_site


def main():
    print("=" * 50)
    print("WEEKLY PIPELINE")
    print("=" * 50)

    print("\n--- Step 1: Fetch Google Trends data ---")
    fetch_trends()

    print("\n--- Step 2: Detect spikes ---")
    detect_spikes()

    print("\n--- Step 3: Generate Grok X report ---")
    grok_report()

    print("\n--- Step 4: Sentiment analysis ---")
    analyse_sentiment()

    print("\n--- Step 5: Weekly analysis ---")
    weekly_analysis()

    print("\n--- Step 6: Rebuild site ---")
    build_site()

    print("\n--- Weekly pipeline complete ---")


if __name__ == "__main__":
    main()
