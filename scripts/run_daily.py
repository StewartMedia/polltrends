"""Daily pipeline. Runs in GitHub Actions; no local services or models needed.

Every step is isolated: a failed fetch is recorded and the site falls back to
the last good snapshot for that source, labelled with its real date.
"""
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import PROCESSED_DIR, now_local, today_local, write_json  # noqa: E402
from scripts import (  # noqa: E402
    build_site, detect_spikes, fetch_news, fetch_trends, fetch_vic_polls, generate_narrative,
    vic_model, weekly_analysis,
)

status: dict[str, dict] = {}


def step(name: str, fn, *args):
    print(f"\n=== {name} ===")
    started = time.time()
    try:
        result = fn(*args)
        ok = result is not False and result is not None
    except Exception as exc:  # keep going; record the failure
        traceback.print_exc()
        result, ok = None, False
        status[name] = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"[:300]}
    else:
        status[name] = {"ok": ok}
    status[name]["seconds"] = round(time.time() - started, 1)
    return result


def main() -> int:
    print(f"PolTrends daily pipeline - {now_local():%Y-%m-%d %H:%M %Z}")

    step("trends_national", fetch_trends.main)
    step("trends_victoria", fetch_trends.fetch_victoria)
    step("trends_victoria_leaders", fetch_trends.fetch_victoria_leaders)
    step("news_national", fetch_news.main)
    step("news_victoria", fetch_news.fetch_victoria)
    step("polls_victoria", fetch_vic_polls.main)

    model = step("seat_model", vic_model.build)
    if model:
        seats = [s["seat"] for s in model.get("key_seats", [])]
        step("seat_news", fetch_news.fetch_seat_news, seats)

    step("spikes_national", detect_spikes.main)
    step("spikes_victoria", detect_spikes.detect_victoria)
    step("summary_national", weekly_analysis.main)
    step("summary_victoria", weekly_analysis.analyse_victoria)
    step("summary_victoria_leaders", weekly_analysis.analyse_victoria_leaders)
    step("briefing", generate_narrative.main)

    write_json(PROCESSED_DIR / today_local() / "run_status.json", {
        "date": today_local(),
        "finished_at": now_local().isoformat(timespec="seconds"),
        "steps": status,
    })

    step("build_site", build_site.build)
    failed = [k for k, v in status.items() if not v["ok"]]
    print(f"\nDone. {len(status) - len(failed)}/{len(status)} steps ok." + (f" Failed: {failed}" if failed else ""))
    return 1 if not status.get("build_site", {}).get("ok") else 0


if __name__ == "__main__":
    sys.exit(main())
