"""Daily pipeline: fetch trends data, detect spikes, generate Grok X report."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.fetch_trends import main as fetch_trends
from scripts.detect_spikes import main as detect_spikes
from scripts.grok_report import main as grok_report
from scripts.build_site import main as build_site


def main():
    print("=" * 50)
    print("DAILY PIPELINE")
    print("=" * 50)

    print("\n--- Step 1: Fetch Google Trends data ---")
    fetch_trends()

    print("\n--- Step 2: Detect spikes ---")
    detect_spikes()

    print("\n--- Step 3: Generate Grok X report ---")
    grok_report()

    print("\n--- Step 4: Rebuild site ---")
    build_site()

    print("\n--- Daily pipeline complete ---")


if __name__ == "__main__":
    main()
