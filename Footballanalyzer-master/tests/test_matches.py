import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import joblib
import numpy as np
from ml.matches import build_examples, fit_bundle
import update_football as updater


def fixtures(n=320):
    # Synthetic games only for code tests; never installed as real training data.
    values = []
    for i in range(n):
        hg, ag = [(2, 0), (1, 1), (0, 1)][i % 3]
        values.append({'fixture': {'id': i, 'timestamp': 1600000000 + i * 86400, 'status': {'short': 'FT'}},
                       'league': {'id': 135, 'season': 2020, 'round': 'Regular Season - 1'},
                       'teams': {'home': {'id': 1, 'name': 'A'}, 'away': {'id': 2, 'name': 'B'}},
                       'goals': {'home': hg, 'away': ag}})
    return values


class FeaturesTest(unittest.TestCase):
    def test_no_target_or_future_result_leakage(self):
        original = fixtures()
        before, _ = build_examples(original)
        altered = copy.deepcopy(original)
        altered[30]['goals']['home'] = 10
        after, _ = build_examples(altered)
        for a, b in zip(before, after):
            if a[0] <= altered[30]['fixture']['timestamp']:
                self.assertEqual(a[1], b[1])
        self.assertNotEqual(before[26][1], after[26][1])

    def test_simultaneous_games_are_not_used(self):
        values = fixtures(12)
        values[6]['fixture']['timestamp'] = values[5]['fixture']['timestamp'] + 3600
        examples, _ = build_examples(values)
        self.assertEqual(examples[0][1], examples[1][1])

    def test_unplayed_and_duplicate_matches(self):
        values = fixtures(12)
        values[-1]['fixture']['status']['short'] = 'NS'
        _, states = build_examples(values)
        self.assertEqual(states[(135, 2020, 1)]['mp'], 11)
        with self.assertRaises(ValueError):
            build_examples(values + values[:1])

    def test_relegation_playoffs_do_not_add_teams_or_statistics(self):
        values = fixtures(12)
        playoff = copy.deepcopy(values[-1])
        playoff['fixture']['id'] = 1000
        playoff['league']['round'] = 'Relegation Round'
        playoff['teams']['away'] = {'id': 3, 'name': 'Second division'}
        examples, states = build_examples(values + [playoff])
        self.assertNotIn((135, 2020, 3), states)
        self.assertEqual(states[(135, 2020, 1)]['mp'], 12)

    def test_model_roundtrip_and_probabilities(self):
        bundle = fit_bundle(fixtures(), [])
        examples, _ = build_examples(fixtures())
        self.assertEqual(set(bundle['model'].classes_), {'home', 'draw', 'away'})
        self.assertGreater(bundle['metrics']['validation_matches'], 30)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bundle.joblib'
            joblib.dump(bundle, path)
            model = joblib.load(path)['model']
            probabilities = model.predict_proba([examples[-1][1]])[0]
            self.assertAlmostEqual(sum(probabilities), 1)
            self.assertTrue(np.all(probabilities >= 0))


class ClientTest(unittest.TestCase):
    def test_cache_prevents_network_request(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(updater, 'CACHE', Path(directory)):
            query = 'fixtures?league=135&season=2024'
            path = Path(directory) / (updater.hashlib.sha256(query.encode()).hexdigest() + '.json')
            updater.atomic_json(path, dict(fetched_at=updater.time.time(), response=[]))
            with patch.object(updater, 'urlopen') as network:
                result = updater.Client('test-key').get('fixtures', dict(league=135, season=2024))
                self.assertEqual(result['response'], [])
                network.assert_not_called()

    def test_daily_reserve_stops_before_network(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(updater, 'CACHE', Path(directory)):
            today = updater.datetime.now(updater.timezone.utc).date().isoformat()
            updater.atomic_json(Path(directory) / 'quota.json', dict(day=today, calls=80, remaining=20))
            with patch.object(updater, 'urlopen') as network, self.assertRaises(RuntimeError):
                updater.Client('test-key').get('fixtures', dict(league=135, season=2024))
            network.assert_not_called()

    def test_api_error_is_cached_and_not_treated_as_data(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(updater, 'CACHE', Path(directory)):
            import io
            response = io.StringIO(json.dumps({'errors': {'plan': 'Season unavailable'}}))
            response.headers = {}
            with patch.object(updater, 'urlopen', return_value=response) as network:
                client = updater.Client('test-key')
                with self.assertRaises(updater.ProviderError):
                    client.get('fixtures', dict(league=135, season=2026))
                with self.assertRaises(updater.ProviderError):
                    client.get('fixtures', dict(league=135, season=2026))
                self.assertEqual(network.call_count, 1)


if __name__ == '__main__':
    unittest.main()

class ServingTest(unittest.TestCase):
    def test_catalog_and_predictions_are_league_scoped(self):
        from api import matches as service
        from fastapi import HTTPException
        model = fit_bundle(fixtures(), [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bundle.joblib'
            joblib.dump(model, path)
            with patch.object(service, 'BUNDLE', path), patch.object(service, '_stamp', None):
                catalog = service.catalog()
                self.assertTrue(next(x for x in catalog['leagues'] if x['id'] == 135)['ready'])
                self.assertFalse(next(x for x in catalog['leagues'] if x['id'] == 39)['ready'])
                self.assertEqual(service.teams(135)['teams'], ['A', 'B'])
                result = service.compare(service.Match(home_team='A', away_team='B', league=135))
                self.assertAlmostEqual(result['home_win'] + result['draw'] + result['away_win'], 1)
                with self.assertRaises(HTTPException):
                    service.compare(service.Match(home_team='A', away_team='A', league=135))
                with self.assertRaises(HTTPException):
                    service.teams(39)
