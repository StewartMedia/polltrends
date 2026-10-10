"""Build config/vic_seats.json: the 88 Victorian Legislative Assembly districts.

Sources (Wikipedia, which mirrors VEC results and Antony Green's pendulum):
  - "2026 Victorian state election" pre-election pendulum (2022 margins,
    adjusted for by-elections where the seat changed hands)
  - "Electoral districts of Victoria" for each district's Legislative Council region

The pendulum only changes with by-elections or retirements, so this runs on
demand (`python scripts/build_vic_seats.py`) and the JSON output is committed.
"""
import io
import re
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import USER_AGENT, VIC_SEATS_PATH, now_local, write_json  # noqa: E402

API = "https://en.wikipedia.org/w/api.php"
METRO_REGIONS = {
    "Northern Metropolitan", "North-Eastern Metropolitan", "South-Eastern Metropolitan",
    "Southern Metropolitan", "Western Metropolitan",
}

# Seats whose holder changed after 2022, or whose status needs a note.
OVERRIDES = {
    "Prahran": {
        "holder": "LIB", "margin": 1.4, "vs": "GRN",
        "note": "Liberal gain at the Feb 2025 by-election (LIB 1.4% v GRN). The Greens won it by 12.0% in 2022.",
    },
    "Ringwood": {"note": "Sitting MP Will Fowles left Labor and sits as an independent."},
    "South Barwon": {"note": "Sitting MP Darren Cheeseman left Labor and sits as an independent."},
    "Werribee": {"note": "Labor held it by 0.8% at the Feb 2025 by-election; the 2022 margin is used."},
    "Mulgrave": {"note": "Labor held it by 6.5% v IND at the Nov 2023 by-election."},
    "Brunswick": {"note": "Sitting Greens MP Tim Read died on 19 September 2026."},
    "Bendigo East": {"note": "Former premier Jacinta Allan is leaving politics."},
}

MARGIN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:\[[^\]]*\])?\s*(?:v\s*([A-Z]{2,4}))?")


def wiki_tables(page: str) -> list[pd.DataFrame]:
    resp = requests.get(
        API,
        params={"action": "parse", "page": page, "prop": "text", "format": "json", "formatversion": 2},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.json()["parse"]["text"]))


def clean(text) -> str:
    return re.sub(r"\[[^\]]*\]", "", str(text)).strip()


def parse_pendulum(tables: list[pd.DataFrame]) -> list[dict]:
    seats = []
    for t in tables:
        if t.shape[1] != 4:
            continue
        first = clean(t.iloc[0, 0])
        if not re.search(r"seats \(\d+\)", first):
            continue
        tier = None
        for _, row in t.iterrows():
            cells = [clean(c) for c in row.tolist()]
            if len(set(cells)) == 1:
                if cells[0] in {"Marginal", "Fairly safe", "Safe", "Very safe"}:
                    tier = cells[0]
                continue
            if cells[0] == "Seat":
                continue
            seat, member, party, margin_text = cells
            m = MARGIN_RE.search(margin_text)
            if not m:
                print(f"  WARNING: could not parse margin for {seat}: {margin_text}")
                continue
            sitting_ind = "(IND)" in member
            seats.append({
                "seat": seat,
                "member": member.replace("(IND)", "").strip(),
                "holder": party,
                "margin": float(m.group(1)),
                "vs": m.group(2),
                "tier": tier,
                "sitting_independent": sitting_ind,
            })
    return seats


def parse_regions(tables: list[pd.DataFrame]) -> dict[str, str]:
    for t in tables:
        cols = [str(c) for c in t.columns]
        if "Name" in cols and "Electoral region" in cols and len(t) == 88:
            return {clean(r["Name"]): clean(r["Electoral region"]) for _, r in t.iterrows()}
    raise RuntimeError("Electoral districts table not found")


def main():
    pendulum = parse_pendulum(wiki_tables("2026_Victorian_state_election"))
    regions = parse_regions(wiki_tables("Electoral_districts_of_Victoria"))

    seats = []
    for s in pendulum:
        s.update(OVERRIDES.get(s["seat"], {}))
        if s["vs"] is None:
            s["vs"] = "ALP" if s["holder"] in {"LIB", "NAT"} else "LNP"
        s["classic"] = {s["holder"], s["vs"]} <= {"ALP", "LNP", "LIB", "NAT"} and (
            "ALP" in {s["holder"], s["vs"]}
        )
        region = regions.get(s["seat"])
        if not region:
            print(f"  WARNING: no region for {s['seat']}")
        s["region"] = region
        # Upper-house region type. Not a strict city/country split: the
        # Eastern Victoria region includes the outer Mornington Peninsula.
        s["region_type"] = "Metropolitan" if region in METRO_REGIONS else "Country"
        seats.append(s)

    names = {s["seat"] for s in seats}
    missing = sorted(set(regions) - names)
    if len(seats) != 88 or missing:
        raise SystemExit(f"Expected 88 seats, parsed {len(seats)}. Missing: {missing}")

    counts = {}
    for s in seats:
        counts[s["holder"]] = counts.get(s["holder"], 0) + 1

    write_json(VIC_SEATS_PATH, {
        "generated": now_local().isoformat(timespec="seconds"),
        "source": "Wikipedia: 2026 Victorian state election (pre-election pendulum) and Electoral districts of Victoria",
        "notes": "Margins are 2022 two-candidate-preferred margins, as used in the published pendulum.",
        "holder_counts": counts,
        "seats": sorted(seats, key=lambda s: s["seat"]),
    })
    print(f"Wrote {len(seats)} seats to {VIC_SEATS_PATH}: {counts}")


if __name__ == "__main__":
    main()
