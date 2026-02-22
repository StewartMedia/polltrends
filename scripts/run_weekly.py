"""Weekly pipeline: full analysis including sentiment + spikes + rebuild site.

Runs for both national (AU) and Victoria (AU-VIC) data.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.fetch_trends import main as fetch_trends, fetch_victoria as fetch_trends_vic
from scripts.fetch_news import main as fetch_news, fetch_victoria as fetch_news_vic
from scripts.detect_spikes import main as detect_spikes, detect_victoria as detect_spikes_vic
from scripts.analyse_sentiment import main as analyse_sentiment, analyse_victoria as analyse_sentiment_vic
from scripts.weekly_analysis import main as weekly_analysis, analyse_victoria as weekly_analysis_vic
from scripts.build_site import main as build_site


def main():
    print("=" * 50)
    print("WEEKLY PIPELINE")
    print("=" * 50)

    # --- National ---
    print("\n--- Step 1: Fetch Google Trends data (National) ---")
    fetch_trends()

    print("\n--- Step 2: Fetch news headlines (National) ---")
    fetch_news()

    print("\n--- Step 3: Detect spikes & match news (National) ---")
    detect_spikes()

    print("\n--- Step 4: Sentiment analysis (National) ---")
    analyse_sentiment()

    print("\n--- Step 5: Weekly analysis (National) ---")
    weekly_analysis()

    # --- Victoria ---
    print("\n--- Step 6: Fetch Google Trends data (Victoria) ---")
    fetch_trends_vic()

    print("\n--- Step 7: Fetch news headlines (Victoria) ---")
    fetch_news_vic()

    print("\n--- Step 8: Detect spikes & match news (Victoria) ---")
    detect_spikes_vic()

    print("\n--- Step 9: Sentiment analysis (Victoria) ---")
    analyse_sentiment_vic()

    print("\n--- Step 10: Weekly analysis (Victoria) ---")
    weekly_analysis_vic()

    # --- Build site ---
    print("\n--- Step 11: Rebuild site ---")
    build_site()

    print("\n--- Weekly pipeline complete ---")


if __name__ == "__main__":
    main()
