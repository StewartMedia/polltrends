"""Fetch published Victorian state voting-intention polls.

Source: Wikipedia "Opinion polling for the 2026 Victorian state election",
which collates every public poll with links to the original reports. One
request per run. If the page layout changes and parsing fails, the previous
snapshot is kept and the site labels it with its real date.

Output: data/raw/<date>/victoria/polls.json
"""
import io
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from lxml import html as lxml_html

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import RAW_DIR, USER_AGENT, now_local, today_local, write_json  # noqa: E402

PAGE = "Opinion_polling_for_the_2026_Victorian_state_election"
PAGE_URL = "https://en.wikipedia.org/wiki/" + PAGE
API = "https://en.wikipedia.org/w/api.php"
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
PARTY_ALIASES = {"L/NP": "LNP", "LNP": "LNP", "ALP": "ALP", "GRN": "GRN", "ONP": "ONP",
                 "IND": "IND", "Others": "OTH", "LIB": "LIB", "NAT": "NAT"}


def clean(text) -> str:
    return re.sub(r"\[[^\]]*\]", "", str(text)).replace("\xa0", " ").strip()


def pct(value) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%?", clean(value))
    if not m or "N/a" in str(value) or "n/a" in str(value):
        return None
    return float(m.group(1))


def parse_end_date(text: str, default_year: int) -> str | None:
    """'24–28 Sep' -> 2026-09-28; 'Mar–Apr 2026' -> 2026-04-15."""
    text = clean(text)
    year_m = re.search(r"(20\d{2})", text)
    year = int(year_m.group(1)) if year_m else default_year
    day_months = re.findall(r"(\d{1,2})\s+([A-Za-z]{3,})", text)
    if day_months:
        day, mon = day_months[-1]
        month = MONTHS.get(mon[:3].lower())
        if month:
            return date(year, month, int(day)).isoformat()
    months = re.findall(r"([A-Za-z]{3,})", text)
    for mon in reversed(months):
        if mon[:3].lower() in MONTHS:
            return date(year, MONTHS[mon[:3].lower()], 15).isoformat()
    return None


def sectioned_tables(page_html: str) -> list[dict]:
    """Return wikitables tagged with their h2/h3/h4 headings."""
    root = lxml_html.fromstring(page_html)
    heads = {"h2": "", "h3": "", "h4": ""}
    found = []
    for el in root.iter():
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag in heads:
            heads[tag] = clean(el.text_content())
            if tag == "h2":
                heads["h3"] = heads["h4"] = ""
            elif tag == "h3":
                heads["h4"] = ""
        elif tag == "table" and "wikitable" in (el.get("class") or ""):
            try:
                df = pd.read_html(io.StringIO(lxml_html.tostring(el, encoding="unicode")))[0]
            except ValueError:
                continue
            found.append({**heads, "df": df})
    return found


def flat_columns(df: pd.DataFrame) -> list[str]:
    names = []
    for col in df.columns:
        parts = [clean(p) for p in (col if isinstance(col, tuple) else (col,))]
        parts = [p for p in parts if p and not p.startswith("Unnamed")]
        group = parts[0] if parts else ""
        leaf = parts[-1] if parts else ""
        if group.startswith("Primary"):
            names.append("p_" + PARTY_ALIASES.get(leaf, leaf))
        elif group.startswith("2PP"):
            names.append("tpp_" + PARTY_ALIASES.get(leaf, leaf))
        elif group.startswith("Seat tally"):
            names.append("seats_" + PARTY_ALIASES.get(leaf, leaf))
        elif group.startswith("Party leaders"):
            names.append("lead_" + leaf)
        else:
            names.append(leaf or group)
    return names


def parse_poll_rows(df: pd.DataFrame, default_year: int) -> tuple[list[dict], list[dict]]:
    df = df.copy()
    df.columns = flat_columns(df)
    polls, events = [], []
    for _, row in df.iterrows():
        values = [clean(v) for v in row.tolist()]
        when = parse_end_date(values[0], default_year)
        if len(set(values[1:])) == 1 and values[1]:
            if when:
                events.append({"date": when, "label": values[1]})
            continue
        firm = clean(row.get("Polling firm", ""))
        if not firm or "election" in firm.lower() or not when:
            continue
        rec = {"date": when, "fieldwork": values[0], "firm": firm,
               "client": clean(row.get("Client", "")), "sample": clean(row.get("Sample size", ""))}
        for col in df.columns:
            if col.startswith(("p_", "tpp_", "seats_", "lead_")):
                rec[col] = pct(row[col])
        polls.append(rec)
    return polls, events


def latest_election_row(df: pd.DataFrame) -> dict | None:
    df = df.copy()
    df.columns = flat_columns(df)
    for _, row in df.iterrows():
        if "election" in clean(row.get("Polling firm", row.iloc[1])).lower():
            return {c: pct(row[c]) for c in df.columns if c.startswith(("p_", "tpp_", "seats_"))}
    return None


def combine_assembly(polls: list[dict]) -> list[dict]:
    """Merge duplicate rows for one poll (rowspan rows carrying an extra 2PP read)."""
    merged: dict[tuple, dict] = {}
    for p in polls:
        key = (p["date"], p["firm"])
        cur = merged.setdefault(key, {k: v for k, v in p.items() if not k.startswith("tpp_")})
        alp, lnp, onp = p.get("tpp_ALP"), p.get("tpp_LNP"), p.get("tpp_ONP")
        if alp is not None and lnp is not None:
            cur["tpp_ALP"], cur["tpp_LNP"] = alp, lnp
        elif alp is not None and onp is not None:
            cur["tpp_ALP_vs_ONP"], cur["tpp_ONP_vs_ALP"] = alp, onp
    out = []
    for p in merged.values():
        majors = [p.get(f"p_{k}") for k in ("ALP", "LNP", "GRN", "ONP")]
        # Independents and others are often one merged cell; derive the residual instead.
        p["p_OTH_ALL"] = round(100 - sum(majors), 1) if all(m is not None for m in majors) else None
        out.append(p)
    return sorted(out, key=lambda p: p["date"], reverse=True)


def main() -> bool:
    print("\nFetching Victorian polls (Wikipedia)")
    try:
        resp = requests.get(API, params={"action": "parse", "page": PAGE, "prop": "text|revid",
                                         "format": "json", "formatversion": 2},
                            headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        parsed = resp.json()["parse"]
        tables = sectioned_tables(parsed["text"])
    except Exception as exc:  # network or layout failure: keep previous snapshot
        print(f"  FAILED: {exc}")
        return False

    assembly, events, substate, mrp, premier = [], [], {}, [], []
    for t in tables:
        h2, h3, h4, df = t["h2"], t["h3"], t["h4"], t["df"]
        if h2 == "Voting intention" and h3 == "Legislative Assembly" and h4[:4].isdigit():
            rows, evs = parse_poll_rows(df, int(h4[:4]))
            assembly += rows
            events += evs
        elif h2 == "Sub-state results" and h3:
            rows, _ = parse_poll_rows(df, now_local().year)
            if rows:
                substate[h3] = sorted(rows, key=lambda r: r["date"], reverse=True)[:3]
        elif h2.startswith("Electorate projections") and h3 == "Legislative Assembly":
            rows, _ = parse_poll_rows(df, now_local().year)
            mrp += rows
        elif h2 == "Leadership polling" and h3 == "Preferred premier" and "Carroll" in h4:
            rows, _ = parse_poll_rows(df, now_local().year)
            premier += rows

    assembly = combine_assembly(assembly)
    if len(assembly) < 3:
        print(f"  FAILED: only {len(assembly)} assembly polls parsed; layout may have changed")
        return False

    out = {
        "source": PAGE_URL,
        "revision": parsed.get("revid"),
        "fetched_at": now_local().isoformat(timespec="seconds"),
        "assembly": assembly,
        "events": sorted({(e["date"], e["label"]): e for e in events}.values(), key=lambda e: e["date"]),
        "substate": substate,
        "mrp": sorted(mrp, key=lambda r: r["date"], reverse=True),
        "preferred_premier": sorted(premier, key=lambda r: r["date"], reverse=True),
    }
    write_json(RAW_DIR / today_local() / "victoria" / "polls.json", out)
    latest = assembly[0]
    print(f"  {len(assembly)} assembly polls; latest {latest['firm']} {latest['date']} "
          f"ALP {latest.get('p_ALP')} LNP {latest.get('p_LNP')} ONP {latest.get('p_ONP')} "
          f"2PP ALP {latest.get('tpp_ALP')}; MRP rows {len(mrp)}; sub-state {list(substate)}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
