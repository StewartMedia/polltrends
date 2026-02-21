"""Daily pipeline: fetch trends data, news headlines, detect spikes, rebuild site."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.fetch_trends import main as fetch_trends
from scripts.fetch_news import main as fetch_news
from scripts.detect_spikes import main as detect_spikes
from scripts.build_site import main as build_site


def main():
    print("=" * 50)
    print("DAILY PIPELINE")
    print("=" * 50)

    print("\n--- Step 1: Fetch Google Trends data ---")
    fetch_trends()

    print("\n--- Step 2: Fetch news headlines ---")
    fetch_news()

    print("\n--- Step 3: Detect spikes & match news ---")
    detect_spikes()

    print("\n--- Step 4: Rebuild site ---")
    build_site()

    print("\n--- Daily pipeline complete ---")


if __name__ == "__main__":
    main()
