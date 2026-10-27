import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pl_rounds as tracker
from ml.matches import empty_stats

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


class Model:
    classes_ = np.array(['away', 'draw', 'home'])
    def predict_proba(self, inputs):
        return np.array([[.2, .3, .5]])


def fixture(key='2026:1', days=2, score=None):
    return {'id': key, 'season': 2026, 'round': 9, 'home': 'A', 'away': 'B',
            'kickoff': (NOW+timedelta(days=days)).isoformat(), 'started': score is not None, 'score': score}


def bundle():
    teams = {name: empty_stats(name) for name in ('A', 'B')}
    for team in teams.values():
        team['mp'] = 5
    return {'seasons': {39: 2026}, 'teams': {39: teams}, 'model': Model(), 'trained_at': NOW.isoformat(),
            'snapshots': [{'league': 39, 'season': 2026, 'fixtures': [], 'last_result': '2026-10-25', 'fetched_at': NOW.timestamp()}]}


class RoundTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path_patch = patch.object(tracker, 'DIRECTORY', Path(self.directory.name))
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.clock = patch.object(tracker, 'utcnow', return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_forecast_is_immutable_when_result_and_model_change(self):
        state = tracker.read_state()
        tracker.reconcile(state, [fixture()], NOW)
        tracker.forecast_upcoming(state, bundle(), NOW, 'original-model')
        original = copy.deepcopy(state['records']['2026:1']['forecast'])
        self.assertEqual(original['probabilities'], {'home': .5, 'draw': .3, 'away': .2})
        later = NOW + timedelta(days=3)
        tracker.reconcile(state, [fixture(score=[0, 1])], later)
        tracker.forecast_upcoming(state, bundle(), later, 'new-model')
        self.assertEqual(state['records']['2026:1']['forecast'], original)
        result = tracker.metrics(state['records'].values())
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['accuracy'], 0)
        self.assertAlmostEqual(result['log_loss'], -np.log(.2))
        self.assertAlmostEqual(result['brier'], .25+.09+.64)
        tracker.write_state(state)
        self.assertEqual(tracker.read_state()['records']['2026:1']['forecast'], original)

    def test_started_finished_and_missing_kickoff_never_get_forecast(self):
        missing = fixture('2026:3'); missing['kickoff'] = None
        started = fixture('2026:4'); started['started'] = True
        state = tracker.read_state()
        tracker.reconcile(state, [fixture(days=-1), fixture('2026:2', score=[1, 1]), missing, started], NOW)
        tracker.forecast_upcoming(state, bundle(), NOW, 'model')
        self.assertTrue(all(r['forecast'] is None for r in state['records'].values()))
        self.assertEqual(tracker.metrics(state['records'].values())['count'], 0)

    def test_clock_is_checked_after_training_and_insufficient_history(self):
        state = tracker.read_state()
        tracker.reconcile(state, [fixture()], NOW)
        with patch.object(tracker, 'utcnow', return_value=NOW+timedelta(days=3)):
            tracker.forecast_upcoming(state, bundle(), NOW, 'model')
        self.assertIsNone(state['records']['2026:1']['forecast'])
        data = bundle(); data['teams'][39]['A']['mp'] = 4
        tracker.forecast_upcoming(state, data, NOW, 'model')
        self.assertIsNone(state['records']['2026:1']['forecast'])

    def test_postponement_and_earlier_kickoff(self):
        state = tracker.read_state()
        tracker.reconcile(state, [fixture()], NOW)
        tracker.forecast_upcoming(state, bundle(), NOW, 'model')
        tracker.reconcile(state, [fixture(days=10)], NOW)
        self.assertTrue(state['records']['2026:1']['eligible'])
        tracker.reconcile(state, [fixture(days=-1, score=[1, 0])], NOW)
        self.assertFalse(state['records']['2026:1']['eligible'])
        self.assertEqual(tracker.metrics(state['records'].values())['count'], 0)

    def test_result_feedback_survives_training_source_failure(self):
        state = tracker.read_state()
        tracker.reconcile(state, [fixture()], NOW)
        tracker.forecast_upcoming(state, bundle(), NOW, 'model')
        tracker.write_state(state)
        with patch.object(tracker, 'fetch_schedule', return_value=[fixture(score=[1, 0])]), \
             patch.object(tracker, 'utcnow', return_value=NOW+timedelta(days=3)), \
             patch.object(tracker, 'refresh_current', side_effect=OSError('offline')):
            report = tracker.sync()
        self.assertEqual(report['metrics']['count'], 1)
        self.assertEqual(report['metrics']['accuracy'], 1)
        self.assertIsNotNone(report['error'])
        self.assertEqual(report['records'][0]['forecast']['model_id'], 'model')

    def test_full_round_window_and_corrected_results(self):
        state = tracker.read_state()
        tracker.reconcile(state, [fixture(), fixture('2026:2', days=12)], NOW)
        tracker.forecast_upcoming(state, bundle(), NOW, 'model')
        self.assertTrue(all(r['forecast'] for r in state['records'].values()))
        tracker.reconcile(state, [fixture(score=[1, 0])], NOW+timedelta(days=3))
        self.assertEqual(tracker.metrics(state['records'].values())['accuracy'], 1)
        tracker.reconcile(state, [fixture(score=[0, 1])], NOW+timedelta(days=3))
        self.assertEqual(tracker.metrics(state['records'].values())['accuracy'], 0)

    def test_feed_rejects_old_season(self):
        with patch.object(tracker, 'get_json', side_effect=[{'events': [{'deadline_time': '2025-08-01T12:00:00Z'}]}, []]):
            with self.assertRaises(ValueError):
                tracker.fetch_schedule(2026)

    def test_new_results_trigger_refresh_but_old_forecast_stays(self):
        with patch.object(tracker, 'fetch_schedule', return_value=[fixture()]), \
             patch.object(tracker, 'refresh_current', return_value=bundle()) as refresh, \
             patch.object(tracker, 'archive_model', return_value='model'):
            first = tracker.sync()
            second = tracker.sync()
        self.assertEqual(refresh.call_count, 2)
        self.assertIsNone(first['error'])
        self.assertEqual(first['records'][0]['forecast'], second['records'][0]['forecast'])
