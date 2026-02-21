"""Central configuration for poltrends."""
import json
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SITE_DIR = ROOT_DIR / "site"
TEMPLATES_DIR = SITE_DIR / "templates"
OUTPUT_DIR = ROOT_DIR / "docs"  # GitHub Pages serves from /docs

with open(CONFIG_DIR / "entities.json") as f:
    _config = json.load(f)

ENTITIES = _config["entities"]
GEO = _config["geo"]
TIMEFRAME = _config["timeframe"]

# Party colors for charts
PARTY_COLORS = {code: ent["color"] for code, ent in ENTITIES.items()}

# Grok API (xAI)
GROK_API_URL = "https://api.x.ai/v1/chat/completions"
GROK_MODEL = "grok-3-mini"
