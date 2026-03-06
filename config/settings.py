"""Central configuration for poltrends."""
import json
import os
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SITE_DIR = ROOT_DIR / "site"
TEMPLATES_DIR = SITE_DIR / "templates"
OUTPUT_DIR = ROOT_DIR / "docs"  # GitHub Pages serves from /docs
LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1/chat/completions")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "qwen3.5-27b-instruct")

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


def list_dated_directories(directory: Path) -> list[Path]:
    """Return dated child directories sorted ascending by name."""
    if not directory.exists():
        return []
    return sorted(d for d in directory.iterdir() if d.is_dir())


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
) -> dict | str | None:
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
