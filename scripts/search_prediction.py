"""Experimental search-only prediction. No polling or seat-model inputs."""
import math
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import (PROCESSED_DIR, RAW_DIR, VIC_ENTITIES,
                             load_latest_file, today_local, write_json)

SUPPORTED_PARTIES = list(VIC_ENTITIES)
STALE_DAYS = 3
MIN_ROWS = 14
MAJOR_PARTIES = ['ALP', 'LIB', 'GRN', 'PHON']


def _is_valid_nonneg_finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def has_complete_vic_interest(data, assessment_date=None):
    if not isinstance(data, dict) or data.get('geo') != 'AU-VIC':
        return False
    if set(SUPPORTED_PARTIES) != {'ALP', 'LIB', 'NAT', 'GRN', 'PHON'}:
        return False  # These five topics fit one comparable request.
    rows = data.get('data')
    if not isinstance(rows, list) or len(rows) < MIN_ROWS:
        return False
    try:
        dates = [date.fromisoformat(r['date']) for r in rows[-MIN_ROWS:]]
        if any(b - a != timedelta(days=1) for a, b in zip(dates, dates[1:])):
            return False
        if assessment_date and dates[-1] > date.fromisoformat(assessment_date):
            return False
        if any(not _is_valid_nonneg_finite(r.get(p)) for r in rows[-MIN_ROWS:] for p in SUPPORTED_PARTIES):
            return False
        return all(any(r[p] > 0 for r in rows[-7:]) for p in MAJOR_PARTIES)
    except (ValueError, TypeError, KeyError):
        return False


def _compute_avgs_and_momentum(rows):
    averages, momentum = {}, {}
    for p in SUPPORTED_PARTIES:
        recent = sum(r[p] for r in rows[-7:]) / 7
        previous = sum(r[p] for r in rows[-14:-7]) / 7
        averages[p] = round(recent, 2)
        momentum[p] = round((recent / previous - 1) * 100, 1) if previous else None
    return averages, momentum


def build(assessment_date=None):
    assessment_date = assessment_date or today_local()
    snapshot, data = load_latest_file(
        RAW_DIR, 'interest_over_time.json', subdir='victoria',
        on_or_before=assessment_date,
        valid=lambda d: has_complete_vic_interest(d, assessment_date))
    if not data:
        return None
    rows = data['data']
    source_date = rows[-1]['date']
    age = (date.fromisoformat(assessment_date) - date.fromisoformat(source_date)).days
    stale = age > STALE_DAYS
    averages, momentum = _compute_avgs_and_momentum(rows)
    ranking = sorted(SUPPORTED_PARTIES, key=lambda p: averages[p], reverse=True)
    top, runner_up = ranking[:2]
    # Scale-independent gap: multiplying every index by a constant leaves the call unchanged.
    gap = (averages[top] - averages[runner_up]) / averages[top]
    leading_days = sum(r[top] > max(r[p] for p in SUPPORTED_PARTIES if p != top) for r in rows[-7:])
    clear = gap > 0.10 and leading_days >= 5
    leader = top if clear and not stale else None
    _, related = load_latest_file(PROCESSED_DIR, 'related_analysis.json', subdir='victoria', on_or_before=assessment_date)
    query_weight = {}
    rel_date, rel_window = None, None
    if isinstance(related, dict):
        rel_date, rel_window = related.get('source_date'), related.get('window')
        try:
            fresh = isinstance(rel_date, str) and 0 <= (date.fromisoformat(assessment_date) - date.fromisoformat(rel_date)).days <= STALE_DAYS
        except (TypeError, ValueError):
            fresh = False
        profiles = related.get('profiles', {})
        if fresh and rel_window == '7d' and all(isinstance(profiles.get(p), dict) for p in MAJOR_PARTIES):
            for p in MAJOR_PARTIES:
                value = profiles[p].get('intents', {}).get('vote')
                if _is_valid_nonneg_finite(value) and value <= 1:
                    query_weight[p] = round(value * 100, 1)
    if stale:
        text = 'Current prediction withheld: search observations are stale.'
    elif leader:
        text = (f'{VIC_ENTITIES[leader]["short_name"]} tipped to finish with the largest primary vote '
                'among the tracked parties under our experimental search-leadership hypothesis.')
    else:
        text = 'Too close or inconsistent to call a primary-vote leader from search.'
    result = {
        'assessment_date': assessment_date, 'source_date': source_date, 'source_snapshot': snapshot,
        'fetched_at': data.get('fetched_at'), 'age_days': age, 'stale': stale,
        'methodology_version': 'search-pred-v1.2', 'clear_leader': clear,
        'predicted_primary_vote_leader': leader, 'prediction_text': text,
        'last7_avg': averages, 'momentum_pct_change': momentum,
        'ranking_by_entity_interest': ranking, 'leading_days': leading_days,
        'query_weight_vote_intent_pct': query_weight,
        'related_source_date': rel_date, 'related_window': rel_window,
        'evidence': f'{VIC_ENTITIES[top]["short_name"]} leads on {leading_days} of the last seven days. Observations end {source_date}.',
        'hypothesis': 'The sustained party-entity search leader will finish with the largest primary vote among tracked parties. This is an unvalidated hypothesis, not a calibrated election model.',
        'counterarguments': [
            'News or controversy can drive attention without support.',
            'Search users are not a representative sample of voters.',
            'National party topics filtered to Victoria can include federal political interest.',
            'Leader and party indices use separate batches and cannot be compared as absolute volumes.'
        ],
        'limitations': ['No seat totals, winning probabilities or government-formation prediction. Liberal and Nationals are separate parties here.',
                        'Intent percentages are shares of sampled related-query weight within each party, not search counts or vote shares. They contextualise but do not change the call.'],
        'note_on_stale_or_missing': ('Refresh required before a current call can be issued.' if stale else
                                     'Fresh, complete seven-day practical-voting query context unavailable.' if not query_weight else None),
        'comparable_inputs': True,
    }
    write_json(PROCESSED_DIR / assessment_date / 'victoria' / 'search_prediction.json', result)
    return result


if __name__ == '__main__':
    import json
    print(json.dumps(build(sys.argv[1] if len(sys.argv) > 1 else None), indent=2))
