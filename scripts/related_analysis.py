"""Who are Victorians comparing? Cross-party links in related search queries.

Reads the daily Victorian related-query snapshots and writes
  data/processed/<date>/victoria/related_analysis.json

Two windows feed it:
  related_queries_7d.json   last 7 days, the "this week" view (from 18 Nov 2026)
  related_queries.json      rolling 90 days, the baseline and the daily history

Google scales each party's top related queries 0-100 against that party's own
busiest query, so values are never compared across parties. Every figure here
is a *share within one party's searches*: of the search weight behind a
party's top related queries, how much names another party, or falls into an
intent such as how-to-vote. Rule-based, no language model.
"""
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (  # noqa: E402
    PROCESSED_DIR, RAW_DIR, VIC_ENTITIES, has_related_rows, list_dated_directories, load_latest_file,
    load_snapshot_file, today_local, write_json,
)

MINOR = "MINOR"

# Minor parties are matched first and removed from the query, so "democratic
# labour" counts as a minor party, not Labor.
MINOR_PARTIES = [
    ("Victorian Socialists", r"victorian socialists?|\bsocialists?\b"),
    ("Libertarian", r"libertarians?(?: party)?"),
    ("Animal Justice", r"animal justice"),
    ("DLP", r"labou?r dlp|\bdlp\b|democratic labou?r"),
    ("Citizens Party", r"citizens party"),
    ("Australian Democrats", r"\bdemocrats\b"),
    ("Legalise Cannabis", r"legali[sz]e cannabis|cannabis party"),
    ("Family First", r"family first"),
    ("Sustainable Australia", r"sustainable australia"),
    ("Shooters, Fishers and Farmers", r"shooters"),
    ("Freedom Party", r"freedom party"),
    ("Trumpet of Patriots", r"trumpet of patriots"),
    ("Independents", r"\bindependents?\b|\bteals?\b"),
]

# Party names, nicknames and current or recent leaders (state and federal).
PARTY_TERMS = {
    "ALP": r"\blabou?r\b|\balp\b|albanese|ben carroll|jacinta allan|daniel andrews",
    "LIB": r"\bliberals?\b|\blib\b|\bcoalition\b|jess wilson|dutton|sussan ley|angus taylor|john pesutto",
    "NAT": r"\bnationals\b|national party|\bnats\b|danny o.?brien|littleproud",
    "GRN": r"\bgreens?\b|ellen sandell|shoebridge|bandt",
    "PHON": r"one nation|hanson|pickering",
}

# Queries about another state or country are leakage into the Victorian
# figures (for example a WA by-election) and are dropped.
NON_VIC = re.compile(
    r"\b(nsw|new south wales|queensland|qld|wa|western australia|south australia|tasmania|tas|"
    r"northern territory|nt|act|secret harbour|perth|sydney|brisbane|adelaide|hobart|darwin|canberra|"
    r"uk|britain|british|england|nz|new zealand|canada|usa|america|american)\b"
)

# First match wins. "Name lookup" is everything else.
INTENTS = [
    ("vote", "How to vote", r"how to vote|\bhtv\b|vote (?:\w+ )?card|preferenc|ballot|early vot|pre.?poll|"
                            r"polling (?:booth|place)|where (?:do i |to )vote|enrol|^vote |vote for"),
    ("candidates", "Candidates & seats", r"candidate|\bmps?\b|member for|\bseats?\b|electorate|district"),
    ("compare", "Comparisons", r"\bvs\.?\b|versus|\bor\b|difference|compare|better"),
    ("policy", "Policies", r"polic|platform|stance|stand for|promise|\bplans?\b|believe|values|manifesto"),
    ("leader", "Leaders", r"leader|premier|prime minister|\bwho is\b"),
    ("outcome", "Polls & outcome", r"\bwin\b|winning|\bpolls?\b|polling|odds|chance|results?|predict|lose"),
]
INTENT_LABELS = {k: label for k, label, _ in INTENTS} | {"name": "Name lookup"}

HISTORY_LOOKBACK_DAYS = 14
HISTORY_WINDOW_DAYS = 90
STALE_7D_DAYS = 3


def classify(query: str) -> tuple[set[str], list[str], str]:
    """Return (party codes named, minor party names, intent key)."""
    q = query.lower()
    minors, rest = [], q
    for label, rx in MINOR_PARTIES:
        if re.search(rx, rest):
            minors.append(label)
            rest = re.sub(rx, " ", rest)
    parties = {code for code, rx in PARTY_TERMS.items() if re.search(rx, rest)}
    intent = next((key for key, _, rx in INTENTS if re.search(rx, q)), "name")
    return parties, minors, intent


def _rows(party: dict | None, kind: str) -> list[dict]:
    out = []
    for r in (party or {}).get(kind, []) or []:
        q = str(r.get("query", "")).strip()
        if q and not NON_VIC.search(q.lower()):
            out.append({"query": q, "value": r.get("value") or 0})
    return out


def party_profile(code: str, party: dict | None) -> dict | None:
    """Shares of one party's top related-query weight, by linked party and intent."""
    top = _rows(party, "top")
    total = sum(r["value"] for r in top)
    if not top or not total:
        return None
    links = {o: 0.0 for o in list(VIC_ENTITIES) + [MINOR] if o != code}
    intents = {k: 0.0 for k in INTENT_LABELS}
    minor_names: dict[str, float] = {}
    for r in top:
        parties, minors, intent = classify(r["query"])
        w = r["value"] / total
        for o in parties - {code}:
            links[o] += w
        if minors:
            links[MINOR] += w
            for m in minors:
                minor_names[m] = minor_names.get(m, 0) + w
        intents[intent] += w
    return {
        "n_top": len(top),
        "links": {k: round(v, 3) for k, v in links.items()},
        "intents": {k: round(v, 3) for k, v in intents.items()},
        "minor_names": {k: round(v, 3) for k, v in sorted(minor_names.items(), key=lambda x: -x[1])},
    }


def history_90d(as_of: str) -> list[dict]:
    """Daily cross-party link shares from every valid 90-day snapshot."""
    series = []
    start = date.fromordinal(date.fromisoformat(as_of).toordinal() - HISTORY_WINDOW_DAYS).isoformat()
    for d in list_dated_directories(RAW_DIR):
        if d.name > as_of or d.name < start:
            continue
        data = load_snapshot_file(RAW_DIR, d.name, "related_queries.json", "victoria")
        if not has_related_rows(data):
            continue
        profiles = {c: party_profile(c, data.get(c)) for c in VIC_ENTITIES}
        series.append({"date": d.name, "links": {c: p["links"] for c, p in profiles.items() if p}})
    return series


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def link_shift(series: list[dict], p: str, o: str) -> dict | None:
    """Average of the last 3 valid days vs 3 valid days about 14 days earlier."""
    pts = [(s["date"], s["links"][p][o]) for s in series if p in s["links"]]
    if len(pts) < 6:
        return None
    end = date.fromisoformat(pts[-1][0])
    recent = [v for _, v in pts[-3:]]
    earlier = [v for d, v in pts if (end - date.fromisoformat(d)).days >= HISTORY_LOOKBACK_DAYS][-3:]
    if len(earlier) < 2:
        return None
    return {"now": _avg(recent), "before": _avg(earlier), "spark": [v for _, v in pts]}


def pct(x: float) -> str:
    return f"{round(x * 100)}%"


def build_hypotheses(view: dict, shifts: list[dict], names: dict) -> list[dict]:
    """Plain-English leads, each with the evidence that triggered it."""
    out = []
    grid = view["profiles"]
    pairs = [(p, o, prof["links"][o]) for p, prof in grid.items() if prof
             for o in prof["links"] if o != MINOR]
    week = "this week" if view["window"] == "7d" else "over 90 days"

    # 1. One-way links: P's searchers look up O far more than O's look up P.
    for p, o, share in sorted(pairs, key=lambda x: -x[2]):
        back = (grid.get(o) or {}).get("links", {}).get(p)
        if share >= 0.15 and back is not None and share >= 2 * max(back, 0.02):
            out.append({
                "kind": "one-way",
                "text": f"{names[p]} searches lead to {names[o]} far more than the reverse. "
                        f"One reading: people starting from {names[p]} are checking {names[o]} as the alternative.",
                "evidence": f"{pct(share)} of {names[p]}'s top related searches name {names[o]}; "
                            f"{pct(back)} of {names[o]}'s name {names[p]} ({week}).",
            })
            if len([h for h in out if h["kind"] == "one-way"]) >= 2:
                break

    # 2. Links that strengthened over the last two weeks (90-day history).
    # When the 7-day view exists it must agree, or the page would show two
    # contradictory figures for the same link.
    shown = 0
    for s in sorted(shifts, key=lambda s: -(s["now"] - s["before"])):
        this_week = ((grid.get(s["party"]) or {}).get("links") or {}).get(s["other"])
        agrees = view["window"] != "7d" or (this_week is not None and this_week >= 0.12)
        if shown < 2 and agrees and s["now"] >= 0.12 and s["now"] - s["before"] >= 0.08:
            shown += 1
            out.append({
                "kind": "rising-link",
                "text": f"{names[s['party']]} searchers are comparing with {names[s['other']]} "
                        f"more than they were two weeks ago.",
                "evidence": f"Share of {names[s['party']]}'s top related searches naming {names[s['other']]}: "
                            f"{pct(s['before'])} → {pct(s['now'])} (90-day window, 3-day averages).",
            })

    # 3. Prepoll research: how-to-vote and candidate searches.
    voting = sorted(((p, prof["intents"]["vote"] + prof["intents"]["candidates"])
                     for p, prof in grid.items() if prof), key=lambda x: -x[1])
    active = [(p, v) for p, v in voting if v >= 0.10]
    if active:
        listed = ", ".join(f"{names[p]} {pct(v)}" for p, v in active)
        lead = names[active[0][0]]
        out.append({
            "kind": "prepoll",
            "text": f"Prepoll research is showing up. {lead} draws the most practical searches "
                    f"(how-to-vote cards, candidates and seats). That looks more like people planning a vote "
                    f"than general curiosity.",
            "evidence": f"How-to-vote and candidate searches as a share of each party's top related searches "
                        f"{week}: {listed}.",
        })

    # 4. Minor parties appearing alongside the majors.
    minors: dict[str, list[str]] = {}
    for p, prof in grid.items():
        for m in (prof or {}).get("minor_names", {}):
            minors.setdefault(m, []).append(names[p])
    for p, rising in view["rising"].items():
        for r in rising:
            for m in classify(r["query"])[1]:
                if names[p] not in minors.setdefault(m, []):
                    minors[m].append(names[p])
    if minors:
        listed = "; ".join(f"{m} ({', '.join(ps)})" for m, ps in list(minors.items())[:4])
        out.append({
            "kind": "minors",
            "text": "Minor parties are turning up in major-party searches. That points to preference "
                    "and upper-house shopping, where minor parties matter most.",
            "evidence": f"Minor parties named in related searches {week}: {listed}.",
        })
    return out


def analyse(as_of: str | None = None) -> dict | None:
    as_of = as_of or today_local()
    names = {c: e["short_name"] for c, e in VIC_ENTITIES.items()} | {MINOR: "minor parties"}

    d7, raw7 = load_latest_file(RAW_DIR, "related_queries_7d.json", subdir="victoria",
                                on_or_before=as_of, valid=has_related_rows)
    d90, raw90 = load_latest_file(RAW_DIR, "related_queries.json", subdir="victoria",
                                  on_or_before=as_of, valid=has_related_rows)
    if not raw7 and not raw90:
        print("  no Victorian related-query snapshots")
        return None

    use_7d = bool(raw7 and d7) and (date.fromisoformat(as_of) - date.fromisoformat(str(d7))).days <= STALE_7D_DAYS
    if use_7d:
        window, src_date, parties = "7d", str(d7), raw7["parties"]
        excluded = set(raw7.get("excluded", []))
    else:
        window, src_date, parties, excluded = "90d", str(d90), raw90, set()

    profiles = {c: party_profile(c, parties.get(c)) for c in VIC_ENTITIES}
    baseline = {c: party_profile(c, (raw90 or {}).get(c)) for c in VIC_ENTITIES} if raw90 else {}

    # Rising queries new since the previous snapshot of the same window.
    prev_file = "related_queries_7d.json" if use_7d else "related_queries.json"
    prev_day = (date.fromisoformat(src_date).toordinal() - 1)
    _, prev = load_latest_file(RAW_DIR, prev_file, subdir="victoria",
                               on_or_before=date.fromordinal(prev_day).isoformat(), valid=has_related_rows)
    prev_parties = (prev or {}).get("parties", prev or {})
    rising, new_rising = {}, {}
    for c in VIC_ENTITIES:
        rows = _rows(parties.get(c), "rising")
        rising[c] = rows[:8]
        seen = {r["query"].lower() for r in _rows(prev_parties.get(c), "rising")} if prev else set()
        new_rising[c] = [r for r in rows if r["query"].lower() not in seen][:6] if prev else []

    series = history_90d(as_of)
    shifts = []
    for p in VIC_ENTITIES:
        for o in VIC_ENTITIES:
            if p != o:
                s = link_shift(series, p, o)
                if s:
                    shifts.append({"party": p, "other": o, **s})

    view = {"window": window, "profiles": profiles, "rising": rising}
    no_data = [c for c in VIC_ENTITIES if not profiles.get(c)]
    result = {
        "as_of": as_of,
        "window": window,
        "window_label": "last 7 days" if window == "7d" else "last 90 days",
        "source_date": src_date,
        "baseline_date": d90,
        "history_days": len(series),
        "history_start": series[0]["date"] if series else None,
        "intent_labels": INTENT_LABELS,
        "profiles": profiles,
        "baseline": baseline,
        "rising": rising,
        "new_rising": new_rising,
        "has_previous": bool(prev),
        "shifts": sorted(shifts, key=lambda s: -(s["now"] - s["before"]))[:6],
        "no_data": no_data,
        "excluded": sorted(excluded),
        "hypotheses": build_hypotheses(view, shifts, names),
    }
    return result


def main() -> bool:
    result = analyse()
    if not result:
        return False
    write_json(PROCESSED_DIR / today_local() / "victoria" / "related_analysis.json", result)
    print(f"  {result['window']} view from {result['source_date']}, {result['history_days']} days of history, "
          f"{len(result['hypotheses'])} hypotheses")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
