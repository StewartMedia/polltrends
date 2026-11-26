"""Disposable tests: no repository data or live collectors are written."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts import search_prediction as sp
from config.settings import TEMPLATES_DIR, VIC_ENTITIES
from jinja2 import Environment, FileSystemLoader, select_autoescape


def fixture():
    return {'geo': 'AU-VIC', 'data': [
        {'date': f'2026-11-{i:02d}', 'ALP': 10, 'LIB': 20, 'NAT': 1, 'GRN': 25, 'PHON': 70}
        for i in range(1, 15)]}


class PredictionTests(unittest.TestCase):
    def build(self, data=None, assessment='2026-11-16', related=None):
        data = fixture() if data is None else data
        def load(root, filename, **kwargs):
            self.assertEqual(kwargs['on_or_before'], assessment)
            if filename == 'interest_over_time.json':
                return ('2026-11-16', data) if kwargs['valid'](data) else (None, None)
            self.assertEqual(filename, 'related_analysis.json')  # No polls/seat inputs allowed.
            return '2026-11-16', related
        with patch.object(sp, 'load_latest_file', side_effect=load), patch.object(sp, 'write_json') as write:
            result = sp.build(assessment)
            if result:
                self.assertEqual(write.call_args.args[0], sp.PROCESSED_DIR / assessment / 'victoria/search_prediction.json')
            return result

    def test_independent_call(self):
        result = self.build()
        self.assertEqual(result['predicted_primary_vote_leader'], 'PHON')
        self.assertIn('One Nation tipped', result['prediction_text'])
        self.assertEqual(result['leading_days'], 7)
        self.assertNotIn('vote_share', result)

    def test_stale_withholds_call(self):
        result = self.build(assessment='2026-11-18')
        self.assertTrue(result['stale'])
        self.assertIsNone(result['predicted_primary_vote_leader'])
        self.assertNotIn('tipped', result['prediction_text'])

    def test_historical_assessment_not_wall_clock(self):
        with patch.object(sp, 'today_local', return_value='2027-01-01'):
            self.assertFalse(self.build()['stale'])

    def test_invalid_inputs(self):
        for value in [None, -1, float('inf'), float('nan'), True, '4']:
            data = fixture()
            data['data'][-1]['LIB'] = value
            with self.subTest(value=value):
                self.assertIsNone(self.build(data))
        for change in ['gap', 'future', 'geo', 'missing', 'zero', 'short']:
            data = fixture()
            if change == 'gap': data['data'][-2]['date'] = '2026-11-10'
            if change == 'future': data['data'][-1]['date'] = '2026-11-25'
            if change == 'geo': data['geo'] = 'AU'
            if change == 'missing': del data['data'][-1]['GRN']
            if change == 'zero':
                for row in data['data']: row['LIB'] = 0
            if change == 'short': data['data'] = data['data'][-7:]
            with self.subTest(change=change): self.assertIsNone(self.build(data))

    def test_tie_and_spike_withhold(self):
        data = fixture()
        for row in data['data']: row['GRN'] = row['PHON']
        self.assertIsNone(self.build(data)['predicted_primary_vote_leader'])
        data = fixture()
        for row in data['data']: row['PHON'] = 5
        data['data'][-1]['PHON'] = 1000
        self.assertIsNone(self.build(data)['predicted_primary_vote_leader'])

    def test_scale_invariant(self):
        data = fixture()
        for row in data['data']:
            for p in sp.SUPPORTED_PARTIES: row[p] *= .01
        self.assertEqual(self.build(data)['predicted_primary_vote_leader'], 'PHON')

    def test_intent_freshness_and_labels(self):
        related = {'source_date': '2026-11-15', 'window': '7d',
                   'profiles': {p: {'intents': {'vote': .2}} for p in sp.MAJOR_PARTIES}}
        self.assertEqual(self.build(related=related)['query_weight_vote_intent_pct']['PHON'], 20)
        for key, value in [('source_date', '2026-11-01'), ('source_date', '2026-11-20'), ('window', '90d')]:
            bad = copy.deepcopy(related)
            bad[key] = value
            self.assertEqual(self.build(related=bad)['query_weight_vote_intent_pct'], {})
        del related['profiles']['ALP']
        self.assertEqual(self.build(related=related)['query_weight_vote_intent_pct'], {})

    def test_render_states(self):
        env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=select_autoescape())
        template = env.get_template('search_prediction.html')
        for result, expected in [(self.build(), 'One Nation tipped'),
                                 (self.build(assessment='2026-11-18'), 'prediction withheld'),
                                 (None, 'No current call')]:
            html = template.render(search_pred=result, vic_entities=VIC_ENTITIES)
            self.assertIn(expected, html)
            self.assertIn('PolTrends election call', html)
            self.assertNotIn("{'ALP'", html)


if __name__ == '__main__':
    unittest.main()
