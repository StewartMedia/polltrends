"""Central configuration for poltrends."""
import json
import os
from datetime import datetime
from typing import Any
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SITE_DIR = ROOT_DIR / "site"
TEMPLATES_DIR = SITE_DIR / "templates"
OUTPUT_DIR = ROOT_DIR / "docs"  # GitHub Pages serves from /docs
SITE_URL = "https://poltrends.stewartmedia.com.au"

# All snapshot folders are named by the Melbourne calendar date, so local runs
# and GitHub Actions (UTC) runs write to the same folder for the same day.
TIMEZONE = ZoneInfo(os.getenv("POLTRENDS_TZ", "Australia/Melbourne"))
USER_AGENT = "PolTrends/2.0 (+https://poltrends.stewartmedia.com.au)"

with open(CONFIG_DIR / "entities.json") as f:
    _config = json.load(f)

# Federal (national)
ENTITIES = _config["entities"]
GEO = _config["geo"]
TIMEFRAME = _config["timeframe"]
PARTY_COLORS = {code: ent["color"] for code, ent in ENTITIES.items()}

# Victoria
_vic = _config.get("victoria", {})
VIC_ENTITIES = _vic.get("entities", {})
VIC_GEO = _vic.get("geo", "AU-VIC")
VIC_PARTY_COLORS = {code: ent["color"] for code, ent in VIC_ENTITIES.items()}
VIC_LEADERS = _vic.get("leaders", {})
VIC_LEADER_COLORS = {code: ent["color"] for code, ent in VIC_LEADERS.items()}
VIC_ELECTION = _vic.get("election", {})
VIC_SEATS_PATH = CONFIG_DIR / "vic_seats.json"


def now_local() -> datetime:
    return datetime.now(TIMEZONE)


def today_local() -> str:
    """Snapshot date (YYYY-MM-DD) in Melbourne time."""
    return now_local().date().isoformat()


def list_dated_directories(directory: Path) -> list[Path]:
    """Return dated child directories sorted ascending by name."""
    if not directory.exists():
        return []
    return sorted(d for d in directory.iterdir() if d.is_dir() and d.name[:2] == "20")


def has_snapshot_files(base_dir: Path, filenames: list[str], subdir: str | None = None) -> bool:
    """Check whether all expected files exist for a dated snapshot."""
    target_dir = base_dir / subdir if subdir else base_dir
    return all((target_dir / filename).exists() for filename in filenames)


def find_latest_snapshot_date(
    raw_required: list[str] | None = None,
    processed_required: list[str] | None = None,
    raw_subdir: str | None = None,
    processed_subdir: str | None = None,
) -> str | None:
    """Find the latest snapshot date satisfying the requested raw/processed files."""
    raw_required = raw_required or []
    processed_required = processed_required or []

    raw_dates = {d.name for d in list_dated_directories(RAW_DIR)} if raw_required else set()
    processed_dates = {d.name for d in list_dated_directories(PROCESSED_DIR)} if processed_required else set()

    if raw_required and processed_required:
        candidate_dates = sorted(raw_dates & processed_dates, reverse=True)
    elif raw_required:
        candidate_dates = sorted(raw_dates, reverse=True)
    else:
        candidate_dates = sorted(processed_dates, reverse=True)

    for snapshot_date in candidate_dates:
        raw_ok = True
        proc_ok = True

        if raw_required:
            raw_ok = has_snapshot_files(RAW_DIR / snapshot_date, raw_required, raw_subdir)
        if processed_required:
            proc_ok = has_snapshot_files(PROCESSED_DIR / snapshot_date, processed_required, processed_subdir)

        if raw_ok and proc_ok:
            return snapshot_date

    return None


def load_snapshot_file(
    directory: Path,
    snapshot_date: str,
    filename: str,
    subdir: str | None = None,
) -> Any:
    """Load a file from a specific dated snapshot."""
    target_dir = directory / snapshot_date
    if subdir:
        target_dir = target_dir / subdir

    path = target_dir / filename
    if not path.exists():
        return None

    if filename.endswith(".json"):
        with open(path) as f:
            return json.load(f)

    with open(path) as f:
        return f.read()


def load_latest_file(
    directory: Path,
    filename: str,
    subdir: str | None = None,
    on_or_before: str | None = None,
) -> tuple[str | None, Any]:
    """Return (date, data) for the newest snapshot that has `filename`.

    Used for carry-forward: if today's fetch for one source failed, the site
    still renders the last good copy and labels it with its real date.
    """
    for d in reversed(list_dated_directories(directory)):
        if on_or_before and d.name > on_or_before:
            continue
        data = load_snapshot_file(directory, d.name, filename, subdir)
        if data:
            return d.name, data
    return None, None


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        f.write("\n")
