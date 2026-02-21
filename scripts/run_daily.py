"""Daily pipeline: fetch trends data and generate Grok X report."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.fetch_trends import main as fetch_trends
from scripts.grok_report import main as grok_report
from scripts.build_site import main as build_site


def main():
    print("=" * 50)
    print("DAILY PIPELINE")
    print("=" * 50)

    print("\n--- Step 1: Fetch Google Trends data ---")
    fetch_trends()

    print("\n--- Step 2: Generate Grok X report ---")
    grok_report()

    print("\n--- Step 3: Rebuild site ---")
    build_site()

    print("\n--- Daily pipeline complete ---")


if __name__ == "__main__":
    main()
