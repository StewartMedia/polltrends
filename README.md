# PolTrends Australia

Static site at <https://poltrends.stewartmedia.com.au>, served by GitHub Pages from `docs/`.

It tracks Google Trends search interest for Australian political parties, the headlines that line up with each search spike, and the 2026 Victorian election: published polls, a uniform-swing seat model on the 2022 pendulum, and the published MRP.

## How it runs

A single workflow, `.github/workflows/poltrends.yml`, runs `scripts/run_daily.py` and commits `data/` and `docs/`.

- 19:30 UTC (06:30 AEDT / 05:30 AEST): full run with Google Trends, news, polls and site.
- 07:30 UTC (18:30 AEDT): refresh of news, polls and site. Trends is skipped because today's snapshot already exists.
- Manual: Actions → *PolTrends daily update* → *Run workflow* (needs repo admin). Tick *force_trends* to refetch Trends.
- Push: any push to `main` that changes `scripts/`, `config/`, `site/`, `requirements.txt` or the workflow runs the pipeline and redeploys.

No local machine, cron job or language model is involved. Each step is isolated. If one source fails, the site keeps its last good snapshot and labels it with its date. The footer's *Data health* panel shows the result of every step in the last run.

## Pipeline (`scripts/`)

| Step | Script | Output |
| --- | --- | --- |
| Search interest (AU, VIC parties, VIC leaders) | `fetch_trends.py` | `data/raw/<date>/[victoria/]interest_over_time.json`, `related_queries.json`, `victoria/leaders_interest.json` |
| Headlines (Google News RSS) | `fetch_news.py` | `news.json`, `victoria/seat_news.json` |
| Victorian polls (Wikipedia poll table) | `fetch_vic_polls.py` | `victoria/polls.json` |
| Seat model | `vic_model.py` | `data/processed/<date>/victoria/seat_model.json` |
| Spikes and headline matching | `detect_spikes.py` | `spikes.json` |
| Rolling 7-day summary | `weekly_analysis.py` | `weekly_analysis.json`, `victoria/leaders_analysis.json` |
| Briefing (rule-based, no LLM) | `generate_narrative.py` | `briefing.json` |
| Site and share images | `build_site.py`, `generate_charts.py`, `generate_og_image.py` | `docs/` |
| X posts (separate workflow step) | `post_x.py` | `data/x/ledger.json`, `drafts.json` |

Snapshot folders use the Melbourne calendar date.

## Posting to X (@poltrendsau)

`scripts/post_x.py` runs after the pipeline. It builds posts from fixed templates (no language model) for three events: a newly published Victorian poll, Monday's share-of-search summary, and a strong search spike from the last three days (at least 3x the 7-day average and an index of 8 or more). Each post attaches that day's share image and contains no link, because X charges $0.015 per post but $0.20 per post with a URL.

- **Mode:** repository variable `X_POST_MODE` = `off`, `dry-run` (default) or `live`. Dry-run writes drafts to `data/x/drafts.json` and the Actions run summary and never calls X.
- **Guardrails:** at most 1 post per run and 2 per Melbourne day; `data/x/ledger.json` records every event so nothing posts twice; the first run baselines existing events; a poll that looks like a Wikipedia edit of a known poll (same firm within 7 days, or same date and figures) is not announced as new; failed posts retry once.
- **Credentials:** GitHub Actions secrets `X_API_KEY`, `X_API_SECRET` (Jim's X app) and `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET` (the @poltrendsau account). Create the account tokens by running `.venv/bin/python scripts/x_authorise.py` locally while logged in to X as @poltrendsau. It never prints the tokens.
- **Preview:** `.venv/bin/python scripts/post_x.py --preview` prints a sample of each post type from the latest data.

## Victorian seats

`config/vic_seats.json` holds the 88 districts with their 2022 margins and upper-house regions. It is built from the published pre-election pendulum by `scripts/build_vic_seats.py`. Re-run it after a by-election or a change of seat holder, review the diff, and commit. Seat-specific corrections (for example, Prahran after the 2025 by-election) live in `OVERRIDES` in that script.

## Local use

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/run_daily.py          # full pipeline
python scripts/build_site.py         # rebuild docs/ from existing data
python -m http.server 8080 --directory docs
```

## Config

- `config/entities.json`: parties, leaders (Google Trends topic IDs), colours, election date and the 2022 baseline.
- `config/settings.py`: paths, timezone and snapshot helpers.

Fonts (Inter, Instrument Serif, SIL Open Font License): full TTFs in `site/fonts/` for share images, Latin-subset WOFF2 in `site/webfonts/` for the site (made with `pyftsubset`).
