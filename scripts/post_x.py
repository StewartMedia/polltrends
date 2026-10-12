"""Post PolTrends updates to X (@poltrendsau).

Posts are built from fixed templates using the same data as the site. No language
model is involved. Three kinds of event can produce a post:

  poll    a Victorian poll that was not in any earlier snapshot
  weekly  Monday's share-of-search summary (first run on Monday, Melbourne time)
  spike   a search spike from the last few days, with the coverage that day

Modes (env X_POST_MODE, set as a GitHub repository variable):
  off      do nothing
  dry-run  (default) write drafts to data/x/ and the run summary; never call X
  live     upload the share image and post; needs X_API_KEY, X_API_SECRET,
           X_ACCESS_TOKEN and X_ACCESS_TOKEN_SECRET

Guardrails: at most MAX_PER_RUN posts per run and MAX_PER_DAY per Melbourne day,
a ledger (data/x/ledger.json) so nothing posts twice, and a first-run baseline so
the existing backlog is never posted. Dry-run drafts count towards the ledger,
so switching to live never dumps a backlog either.

Usage:
  python scripts/post_x.py            run in the mode set by X_POST_MODE
  python scripts/post_x.py --preview  print sample posts from the latest data
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (  # noqa: E402
    DATA_DIR, ENTITIES, OUTPUT_DIR, PROCESSED_DIR, RAW_DIR, VIC_ENTITIES, load_latest_file, now_local,
    today_local, write_json,
)

X_DIR = DATA_DIR / "x"
LEDGER_PATH = X_DIR / "ledger.json"
DRAFTS_PATH = X_DIR / "drafts.json"

MAX_PER_RUN = 1
MAX_PER_DAY = 2
POLL_MAX_AGE_DAYS = 21      # a "new" poll older than this was added late; do not post it
SPIKE_MAX_AGE_DAYS = 3
SPIKE_MIN_RATIO = 3.0
SPIKE_MIN_VALUE = 8
MAX_ATTEMPTS = 2
HASHTAG_VIC = "#springst"
ATTENTION_NOTE = "Search interest shows attention, not support."

PRIORITY = {"poll": 0, "weekly": 1, "spike": 2}


# --------------------------------------------------------------------------- text

def x_length(text: str) -> int:
    """Weighted length as X counts it (twitter-text v3; no URLs in our posts)."""
    total = 0
    for ch in text:
        cp = ord(ch)
        light = cp <= 4351 or 8192 <= cp <= 8205 or 8208 <= cp <= 8223 or 8242 <= cp <= 8247
        total += 1 if light else 2
    return total


def fits(text: str) -> bool:
    return x_length(text) <= 280


def _n(v) -> str:
    """53.0 -> '53', 46.3 -> '46.3'."""
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def _short_source(source: str) -> str:
    s = re.split(r" [–|-] | \| ", source or "")[0]
    return s.replace(" & Headlines", "").strip()


def _day(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%a %-d %b")


def _first_fitting(*options: str) -> str | None:
    for text in options:
        if text and fits(text):
            return text
    return None


# --------------------------------------------------------------------------- data

def _load(name: str, subdir: str | None = None, raw: bool = False):
    try:
        _, data = load_latest_file(RAW_DIR if raw else PROCESSED_DIR, name, subdir=subdir)
        return data
    except Exception:  # missing snapshot: that event type simply has nothing to say
        return None


def _norm_firm(firm: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (firm or "").lower())


def poll_meta(p: dict) -> dict:
    sig = "/".join(_n(p.get(k)) for k in ("p_ALP", "p_LNP", "p_ONP", "p_GRN", "tpp_LNP"))
    return {"firm": _norm_firm(p.get("firm")), "date": p.get("date"), "sig": sig}


def edited_from(p: dict, seen: dict) -> str | None:
    """Key of a known poll that this one is probably a Wikipedia edit of (same firm within a
    week, or same date and identical figures), so an edit is never announced as a new poll."""
    m = poll_meta(p)
    try:
        d = date.fromisoformat(m["date"])
    except (TypeError, ValueError):
        return None
    for key, v in seen.items():
        old = v.get("poll")
        if not old or key == poll_key(p):
            continue
        try:
            close = abs((date.fromisoformat(old["date"]) - d).days) <= 7
        except (TypeError, ValueError):
            close = False
        if (old["firm"] == m["firm"] and close) or (old["date"] == m["date"] and old["sig"] == m["sig"]):
            return key
    return None


def poll_key(p: dict) -> str:
    return f"poll:{p.get('date')}:{p.get('firm')}"


# --------------------------------------------------------------------------- templates

def poll_post(p: dict, model: dict | None) -> str | None:
    firm = p.get("firm", "")
    client = p.get("client") or ""
    who = f"{firm} ({client})" if client and "N/a" not in client and client != "—" else firm
    head = f"New Victorian poll: {who}, fieldwork {p.get('fieldwork') or _day(p['date'])}."
    tpp = (f"Two-party: Coalition {_n(p['tpp_LNP'])}, Labor {_n(p['tpp_ALP'])}"
           if p.get("tpp_LNP") is not None and p.get("tpp_ALP") is not None else "")
    prim_parts = [f"{lbl} {_n(p[k])}" for k, lbl in
                  (("p_LNP", "Coalition"), ("p_ALP", "Labor"), ("p_ONP", "One Nation"), ("p_GRN", "Greens"))
                  if p.get(k) is not None]
    prim = "Primaries: " + ", ".join(prim_parts) if prim_parts else ""
    body = "\n".join(x for x in (tpp, prim) if x)

    tail_long = tail_short = ""
    if model and model.get("average", {}).get("tpp", {}).get("ALP") is not None:
        avg = model["average"]["tpp"]
        t = model.get("uniform_swing_tally", {})
        tail_short = f"30-day average: Coalition {_n(avg['LNP'])}, Labor {_n(avg['ALP'])}."
        tail_long = (f"{tail_short} Uniform swing: Coalition {t.get('LNP')}, Labor {t.get('ALP')}, "
                     f"Greens {t.get('GRN')} seats ({model.get('majority', 45)} for majority).")
    options = [
        f"{head}\n\n{body}\n\n{tail_long}\n\n{HASHTAG_VIC}",
        f"{head}\n\n{body}\n\n{tail_long}",
        f"{head}\n\n{body}\n\n{tail_short}\n\n{HASHTAG_VIC}",
        f"{head}\n\n{body}",
    ]
    return _first_fitting(*[o for o in options if "\n\n\n" not in o])


def weekly_post(nat: dict, vic: dict | None) -> str | None:
    end = _day(nat["period"]["end"])
    lines = [f"{ENTITIES[c]['short_name']} {nat['stats'][c]['share']:.0f}%" for c in nat["ranking"]]
    vic_line = ""
    if vic:
        top = [c for c in vic["ranking"] if vic["stats"][c].get("share", 0) >= 1][:4]
        vic_line = "Victoria: " + ", ".join(
            f"{VIC_ENTITIES[c]['short_name']} {vic['stats'][c]['share']:.0f}%" for c in top)
    head = f"Share of party search interest in Australia, week to {end}:"
    options = [
        f"{head}\n\n" + "\n".join(lines) + (f"\n\n{vic_line}" if vic_line else "") + f"\n\n{ATTENTION_NOTE}",
        f"{head}\n\n" + "\n".join(lines) + f"\n\n{ATTENTION_NOTE}",
    ]
    return _first_fitting(*options)


def spike_post(s: dict, scope: str) -> str | None:
    names = VIC_ENTITIES if scope == "victoria" else ENTITIES
    party = names.get(s["party_code"], {}).get("short_name", s.get("party_name", s["party_code"]))
    where = "in Victoria" if scope == "victoria" else "across Australia"
    head = f"{party} searches {where} hit {_n(s['ratio'])}x their 7-day average on {_day(s['date'])}."
    news = next((n for n in s.get("news", []) if "facebook" not in (n.get("source") or "").lower()), None)
    tag = f"\n\n{HASHTAG_VIC}" if scope == "victoria" else ""
    if news:
        title = news["title"].strip()
        src = _short_source(news.get("source", ""))
        for cut in (None, 140, 110, 80):
            t = title if cut is None or len(title) <= cut else title[:cut].rsplit(" ", 1)[0] + "…"
            cov = f'Coverage that day: "{t}"' + (f" ({src})" if src else "")
            text = _first_fitting(f"{head}\n\n{cov}\n\n{ATTENTION_NOTE}{tag}", f"{head}\n\n{cov}\n\n{ATTENTION_NOTE}")
            if text:
                return text
    return _first_fitting(f"{head}\n\n{ATTENTION_NOTE}{tag}", f"{head}\n\n{ATTENTION_NOTE}")


# --------------------------------------------------------------------------- candidates

def collect_candidates(today: str, now: datetime) -> list[dict]:
    """Every event that could be posted now, newest data first. Ledger filtering happens later."""
    out: list[dict] = []
    model = _load("seat_model.json", "victoria")
    polls = _load("polls.json", "victoria", raw=True)

    if polls:
        cutoff = (date.fromisoformat(today) - timedelta(days=POLL_MAX_AGE_DAYS)).isoformat()
        for p in polls.get("assembly", []):
            if (p.get("date") or "") < cutoff:
                continue
            text = poll_post(p, model)
            if text:
                out.append({"key": poll_key(p), "kind": "poll", "text": text, "image": "og-victoria.png",
                            "sort": p.get("date", ""), "poll": p})

    nat = _load("weekly_analysis.json")
    if nat and now.weekday() == 0:
        week = date.fromisoformat(nat["period"]["end"]).isocalendar()
        text = weekly_post(nat, _load("weekly_analysis.json", "victoria"))
        if text:
            out.append({"key": f"weekly:{week.year}-W{week.week:02d}", "kind": "weekly", "text": text,
                        "image": "og-image.png", "sort": nat["period"]["end"]})

    cutoff = (date.fromisoformat(today) - timedelta(days=SPIKE_MAX_AGE_DAYS)).isoformat()
    seen_spikes: set[str] = set()
    for scope, sub, image in (("national", None, "og-image.png"), ("victoria", "victoria", "og-victoria.png")):
        for s in _load("spikes.json", sub) or []:
            k = f"spike:{s['party_code']}:{s['date']}"
            if (k in seen_spikes or s["date"] < cutoff or s["ratio"] < SPIKE_MIN_RATIO
                    or s["value"] < SPIKE_MIN_VALUE):
                continue
            seen_spikes.add(k)  # national wins when both scopes spike on the same day
            text = spike_post(s, scope)
            if text:
                out.append({"key": k, "kind": "spike", "text": text, "image": image, "sort": s["date"],
                            "ratio": s["ratio"]})

    out.sort(key=lambda c: (PRIORITY[c["kind"]], -c.get("ratio", 0), c["sort"]))
    return out


def baseline_entries(today: str, now: datetime, stamp: str) -> dict:
    """Ledger entries for everything currently visible, used on the very first run."""
    seen = {c["key"]: {"status": "baseline", "at": stamp} for c in collect_candidates(today, now)}
    for p in (_load("polls.json", "victoria", raw=True) or {}).get("assembly", []):
        seen[poll_key(p)] = {"status": "baseline", "at": stamp, "poll": poll_meta(p)}
    return seen


# --------------------------------------------------------------------------- X API

def _oauth():
    from requests_oauthlib import OAuth1
    return OAuth1(os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
                  os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_TOKEN_SECRET"])


def have_credentials() -> bool:
    return all(os.getenv(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"))


def publish(text: str, image: Path | None) -> str:
    """Upload the image (if present) and create the post. Returns the post ID."""
    import requests
    auth = _oauth()
    payload: dict = {"text": text}
    if image and image.exists():
        with image.open("rb") as fh:
            r = requests.post("https://api.x.com/2/media/upload", auth=auth, timeout=60,
                              files={"media": (image.name, fh, "image/png")},
                              data={"media_category": "tweet_image"})
        r.raise_for_status()
        payload["media"] = {"media_ids": [r.json()["data"]["id"]]}
    r = requests.post("https://api.x.com/2/tweets", auth=auth, json=payload, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"X API {r.status_code}: {r.text[:300]}")
    return r.json()["data"]["id"]


# --------------------------------------------------------------------------- run

def _summary(lines: list[str]) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as fh:
            fh.write("\n".join(lines) + "\n")


def main() -> int:
    mode = (os.getenv("X_POST_MODE") or "dry-run").strip().lower()
    if mode == "off":
        print("X posting is off (X_POST_MODE=off).")
        return 0
    if mode == "live" and not have_credentials():
        print("X_POST_MODE=live but X credentials are missing; running as dry-run.")
        mode = "dry-run"

    today, now = today_local(), now_local()
    stamp = now.isoformat(timespec="seconds")
    ledger = json.loads(LEDGER_PATH.read_text()) if LEDGER_PATH.exists() else None

    if ledger is None:
        seen = baseline_entries(today, now, stamp)
        write_json(LEDGER_PATH, {"created": stamp, "seen": seen})
        print(f"First run: baselined {len(seen)} existing events. Nothing posted.")
        _summary(["## X posts", f"First run: baselined {len(seen)} existing events. Nothing posted."])
        return 0

    seen = ledger.setdefault("seen", {})
    done = ("baseline", "posted", "drafted", "skipped", "edit")
    used_today = sum(1 for v in seen.values()
                     if v.get("status") in ("posted", "drafted") and v.get("at", "")[:10] == today)
    room = max(0, min(MAX_PER_RUN, MAX_PER_DAY - used_today))

    candidates = []
    for c in collect_candidates(today, now):
        prior = seen.get(c["key"], {})
        if prior.get("status") in done or prior.get("attempts", 0) >= MAX_ATTEMPTS:
            continue
        if c["kind"] == "poll" and c["key"] not in seen:
            original = edited_from(c["poll"], seen)
            if original:
                seen[c["key"]] = {"status": "edit", "at": stamp, "of": original, "poll": poll_meta(c["poll"])}
                print(f"{c['key']} looks like an edit of {original}; not posting.")
                continue
        candidates.append(c)
    chosen, rest = candidates[:room], candidates[room:]

    drafts = json.loads(DRAFTS_PATH.read_text()) if DRAFTS_PATH.exists() else []
    report = ["## X posts", f"Mode: **{mode}**. Posted or drafted today before this run: {used_today}/{MAX_PER_DAY}.", ""]
    for c in chosen:
        image = OUTPUT_DIR / c["image"]
        entry = {"key": c["key"], "kind": c["kind"], "text": c["text"], "image": c["image"],
                 "length": x_length(c["text"]), "at": stamp, "mode": mode}
        extra = {"poll": poll_meta(c["poll"])} if c["kind"] == "poll" else {}
        if mode == "live":
            try:
                entry["post_id"] = publish(c["text"], image)
                seen[c["key"]] = {"status": "posted", "at": stamp, "post_id": entry["post_id"], **extra}
                report.append(f"Posted `{c['key']}`: https://x.com/poltrendsau/status/{entry['post_id']}")
            except Exception as exc:
                attempts = seen.get(c["key"], {}).get("attempts", 0) + 1
                seen[c["key"]] = {"status": "error", "at": stamp, "attempts": attempts, "error": str(exc)[:300],
                                  **extra}
                entry["error"] = str(exc)[:300]
                report.append(f"FAILED `{c['key']}` (attempt {attempts}/{MAX_ATTEMPTS}): {str(exc)[:200]}")
                print(f"X post failed for {c['key']}: {exc}")
        else:
            seen[c["key"]] = {"status": "drafted", "at": stamp, **extra}
            report.append(f"Draft `{c['key']}` ({entry['length']}/280, image {c['image']}):")
        report += ["", "```", c["text"], "```", ""]
        drafts.append(entry)
        print(f"[{mode}] {c['key']} ({entry['length']} chars)\n{c['text']}\n")

    # Spikes go stale, so a spike that misses the cap is dropped. Polls and Monday's
    # summary wait for the next run (the summary only qualifies on Mondays anyway).
    for c in rest:
        if c["kind"] == "spike":
            seen[c["key"]] = {"status": "skipped", "at": stamp, "reason": "daily cap"}
    if rest:
        report.append(f"Held or skipped by the cap: {', '.join(c['key'] for c in rest)}")
    if not chosen:
        report.append("Nothing new to post.")
        print("Nothing new to post.")

    ledger["updated"] = stamp
    write_json(LEDGER_PATH, ledger)
    write_json(DRAFTS_PATH, drafts[-200:])
    _summary(report)
    return 0


def preview() -> None:
    """Sample of each post type from the latest data, ignoring the ledger and caps."""
    model = _load("seat_model.json", "victoria")
    polls = (_load("polls.json", "victoria", raw=True) or {}).get("assembly", [])
    samples = []
    if polls:
        samples.append(("poll (latest poll)", poll_post(polls[0], model)))
    nat = _load("weekly_analysis.json")
    if nat:
        samples.append(("weekly (Mondays)", weekly_post(nat, _load("weekly_analysis.json", "victoria"))))
    for scope, sub in (("national", None), ("victoria", "victoria")):
        sp = [s for s in (_load("spikes.json", sub) or []) if s["ratio"] >= SPIKE_MIN_RATIO and s["value"] >= SPIKE_MIN_VALUE]
        if sp:
            samples.append((f"spike ({scope}, most recent qualifying)", spike_post(sp[0], scope)))
    for label, text in samples:
        print(f"--- {label}: {x_length(text or '')}/280\n{text}\n")


if __name__ == "__main__":
    if "--preview" in sys.argv:
        preview()
    else:
        sys.exit(main())
