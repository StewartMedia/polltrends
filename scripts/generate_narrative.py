"""Deterministic weekly briefing.

Writes plain-English paragraphs straight from the computed numbers: no
language model, local or hosted, so every sentence is traceable to the data
and the run cannot fail on model availability.

Output: data/processed/<date>/briefing.json
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (  # noqa: E402
    ENTITIES, PROCESSED_DIR, RAW_DIR, VIC_ENTITIES, VIC_LEADERS, load_latest_file, now_local,
    today_local, write_json,
)


def fmt_date(iso: str, with_year: bool = False) -> str:
    d = date.fromisoformat(iso[:10])
    return d.strftime("%-d %B %Y" if with_year else "%-d %B")


# Names as they read mid-sentence ("the Greens", "Labor").
SENTENCE_NAMES = {"ALP": "Labor", "LIB": "the Liberals", "NAT": "the Nationals", "GRN": "the Greens",
                  "PHON": "One Nation", "ONP": "One Nation"}


def name(entities: dict, code: str, start: bool = False) -> str:
    text = SENTENCE_NAMES.get(code) or entities.get(code, {}).get("short_name", code)
    return text[0].upper() + text[1:] if start else text


def article(number: float) -> str:
    """'a' or 'an' before a spoken number (an 8.7, an 11, an 18)."""
    whole = str(int(abs(number)))
    return "an" if whole.startswith("8") or whole in ("11", "18") else "a"


def share_text(share: float) -> str:
    return "under 1%" if share < 1 else f"{share:.0f}%"


def lead_sentence(summary: dict, entities: dict, scope: str) -> str:
    s = summary["stats"]
    leader, runner = summary["leader"], summary["runner_up"]
    ratio = summary.get("lead_ratio") or 0
    lead = s[leader]
    week = f"the week to {fmt_date(summary['period']['end'])}"
    if ratio and ratio < 1.15:
        return (f"{name(entities, leader, True)} and {name(entities, runner)} were almost level in {scope} "
                f"search interest in {week} ({lead['avg']} v {s[runner]['avg']} on Google's 0-100 scale).")
    times = f"{ratio:.1f} times" if ratio < 10 else f"more than {int(ratio)} times"
    return (f"{name(entities, leader, True)} led {scope} search interest in {week}, averaging {lead['avg']} "
            f"on Google's 0-100 scale, {times} the next party ({name(entities, runner)}). "
            f"That is {share_text(lead['share'])} of all search interest across the parties tracked.")


def movement_sentence(summary: dict, entities: dict) -> str | None:
    s = summary["stats"]
    movers = sorted(s, key=lambda c: s[c]["change_pts"])
    up, down = movers[-1], movers[0]
    parts = []
    if s[up]["change_pts"] >= 1:
        pct = f" ({s[up]['momentum_pct']:+d}%)" if s[up]["momentum_pct"] is not None else ""
        parts.append(f"{name(entities, up, True)} rose the most on the previous week, up {s[up]['change_pts']:.1f} points{pct}")
    if s[down]["change_pts"] <= -1:
        pct = f" ({s[down]['momentum_pct']:+d}%)" if s[down]["momentum_pct"] is not None else ""
        lead_in = name(entities, down, not parts)
        parts.append(f"{lead_in} fell furthest, down {abs(s[down]['change_pts']):.1f} points{pct}")
    if not parts:
        return "Movement on the previous week was small for every party."
    return "; ".join(parts) + "."


def spike_sentences(spikes: list[dict], as_of: str, entities: dict, days: int = 14, limit: int = 3) -> list[str]:
    cutoff = date.fromordinal(date.fromisoformat(as_of).toordinal() - days).isoformat()
    out = []
    for s in [s for s in spikes if s["date"] >= cutoff][:limit]:
        line = (f"Searches for {name(entities, s['party_code'])} jumped to {s['value']} on {fmt_date(s['date'])}, "
                f"{s['ratio']:.1f} times the previous week's average.")
        if s.get("news"):
            n = s["news"][0]
            src = f" ({n['source']})" if n.get("source") else ""
            line += f" Coverage around that day: \u201c{n['title']}\u201d{src}."
        else:
            line += " No matching headline was found in the news collected."
        out.append(line)
    return out


def rising_sentence(related: dict, code: str, entities: dict) -> str | None:
    rising = [q for q in (related.get(code) or {}).get("rising", []) if q.get("query")][:3]
    if not rising:
        return None
    terms = ", ".join(f"\u201c{q['query']}\u201d" for q in rising)
    return f"Fastest-rising searches alongside {name(entities, code)}: {terms}."


def national(as_of: str) -> list[str]:
    _, summary = load_latest_file(PROCESSED_DIR, "weekly_analysis.json")
    if not summary:
        return []
    _, spikes = load_latest_file(PROCESSED_DIR, "spikes.json")
    _, related = load_latest_file(RAW_DIR, "related_queries.json")
    paras = [lead_sentence(summary, ENTITIES, "national")]
    move = movement_sentence(summary, ENTITIES)
    if move:
        paras.append(move)
    paras += spike_sentences(spikes or [], as_of, ENTITIES)
    rising = rising_sentence(related or {}, summary["leader"], ENTITIES)
    if rising:
        paras.append(rising)
    return paras


def victoria(as_of: str) -> list[str]:
    paras = []
    _, model = load_latest_file(PROCESSED_DIR, "seat_model.json", subdir="victoria")
    if model:
        avg = model["average"]
        p, t = avg["primary"], avg["tpp"]
        days = model["days_to_go"]
        when = f"{days} days until Victorians vote" if days > 1 else "Victorians vote"
        paras.append(f"{when} on Saturday {fmt_date(model['election_date'], True)}.")
        if p.get("LNP") is not None:
            line = (f"Across the latest poll from each of {avg['n_polls']} pollsters, the Coalition averages "
                    f"{p['LNP']}% of the primary vote, Labor {p['ALP']}%, One Nation {p['ONP']}% and the Greens {p['GRN']}%.")
            if t.get("ALP") is not None:
                line += (f" On two-party-preferred the Coalition leads {t['LNP']} to {t['ALP']} "
                         f"({avg['n_tpp']} polls), {article(model['swing_to_lnp'])} {abs(model['swing_to_lnp']):.1f}-point swing "
                         f"{'to the Coalition' if model['swing_to_lnp'] > 0 else 'to Labor'} since 2022.")
            paras.append(line)
        tally = model["uniform_swing_tally"]
        lnp, alp = tally.get("LNP", 0), tally.get("ALP", 0)
        majority = model["majority"]
        if lnp >= majority:
            outcome = f"a Coalition majority ({lnp} seats, {majority} needed)"
        elif alp >= majority:
            outcome = f"a Labor majority ({alp} seats, {majority} needed)"
        else:
            outcome = f"a hung parliament (Labor {alp}, Coalition {lnp}, {majority} needed)"
        paras.append(f"Applied uniformly to the 2022 pendulum, that swing points to {outcome}. "
                     f"Treat this as the classic two-party read only: it cannot see One Nation winning seats.")
        mrp = model.get("mrp")
        if mrp:
            coal = int((mrp.get("seats_LIB") or 0) + (mrp.get("seats_NAT") or 0))
            paras.append(f"The {mrp['firm']} MRP ({mrp['fieldwork']}), which models seats one by one, projects "
                         f"Coalition {coal}, Labor {int(mrp.get('seats_ALP') or 0)}, One Nation "
                         f"{int(mrp.get('seats_ONP') or 0)} and Greens {int(mrp.get('seats_GRN') or 0)}: "
                         f"{'a hung parliament' if max(coal, mrp.get('seats_ALP') or 0) < majority else 'a majority'}.")
        pp = model.get("preferred_premier")
        if pp and pp.get("lead_Wilson") is not None:
            paras.append(f"Preferred premier ({pp['firm']}, {pp['fieldwork']}): Wilson {pp['lead_Wilson']:.0f}%, "
                         f"Carroll {pp['lead_Carroll']:.0f}%, Pickering {pp['lead_Pickering']:.0f}%.")

    _, summary = load_latest_file(PROCESSED_DIR, "weekly_analysis.json", subdir="victoria")
    if summary:
        paras.append(lead_sentence(summary, VIC_ENTITIES, "Victorian"))
    _, leaders = load_latest_file(PROCESSED_DIR, "leaders_analysis.json", subdir="victoria")
    if leaders:
        st = leaders["stats"]
        order = leaders["ranking"]
        paras.append("Among the leaders, search interest ran "
                     + ", ".join(f"{VIC_LEADERS[c]['short_name']} {share_text(st[c]['share'])}" for c in order)
                     + " of the combined total this week.")
    _, spikes = load_latest_file(PROCESSED_DIR, "spikes.json", subdir="victoria")
    paras += spike_sentences(spikes or [], as_of, VIC_ENTITIES, limit=2)
    return paras


def main() -> dict:
    as_of = today_local()
    briefing = {
        "date": as_of,
        "generated_at": now_local().isoformat(timespec="seconds"),
        "method": "Deterministic summary of computed figures. No language model is used.",
        "national": national(as_of),
        "victoria": victoria(as_of),
    }
    write_json(PROCESSED_DIR / as_of / "briefing.json", briefing)
    print(f"  briefing: {len(briefing['national'])} national + {len(briefing['victoria'])} Victorian paragraphs")
    return briefing


if __name__ == "__main__":
    for section in ("national", "victoria"):
        print(f"\n## {section}")
        for p in main()[section]:
            print("-", p)
