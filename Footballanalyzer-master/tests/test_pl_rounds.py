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

    def test_round_finished_requires_every_assigned_match_to_have_a_final_result(self):
        self.assertFalse(tracker.round_finished([]))
        self.assertFalse(tracker.round_finished([{'result': 'home'}, {'result': None}]))
        self.assertFalse(tracker.round_finished([{'result': 'home'}, {}]))
        self.assertTrue(tracker.round_finished([{'result': 'home'}, {'result': 'draw'}, {'result': 'away'}]))
        state = tracker.read_state()
        match1, match2 = fixture('2026:1', days=-3, score=[1, 0]), fixture('2026:2', days=-1)
        tracker.reconcile(state, [match1, match2], NOW)
        tracker.write_state(state)
        self.assertFalse(tracker.report()['rounds'][0]['finished'])
        match2['score'] = [0, 0]
        tracker.reconcile(state, [match2], NOW)
        tracker.write_state(state)
        self.assertTrue(tracker.report()['rounds'][0]['finished'])

    def test_simulation_uses_quotes_before_prediction_and_preserves_forecast(self):
        state = tracker.read_state()
        tracker.reconcile(state, [fixture()], NOW)
        tracker.forecast_upcoming(state, bundle(), NOW, 'old-model')
        original = copy.deepcopy(state['records']['2026:1']['forecast'])
        tracker.write_state(state)
        with patch.object(tracker, 'fetch_schedule', return_value=[fixture()]), \
             patch.object(tracker, 'refresh_current', return_value=bundle()), \
             patch.object(tracker, 'archive_model', return_value='new-model'):
            report = tracker.simulate_fixture('2026:1', {'home': 1.5, 'draw': 2, 'away': 5})
            with self.assertRaises(ValueError):
                tracker.simulate_fixture('2026:1', {'home': 1.5, 'draw': 2, 'away': 5})
        row = report['records'][0]
        self.assertEqual(row['forecast'], original)
        self.assertEqual(row['simulation']['pick'], 'away')  # .2*5 > .5*1.5
        self.assertLessEqual(row['simulation']['quoted_at'], row['simulation']['created_at'])
        self.assertEqual(report['simulation']['pending_stake'], 10)
        state = tracker.read_state()
        tracker.reconcile(state, [fixture(score=[0, 2])], NOW+timedelta(days=3))
        self.assertEqual(tracker.simulation_summary(state['records'].values())['net'], 40)
        tracker.reconcile(state, [fixture(score=[1, 0])], NOW+timedelta(days=3))
        self.assertEqual(tracker.simulation_summary(state['records'].values())['net'], -10)
        tracker.reconcile(state, [fixture(days=-1, score=[1, 0])], NOW+timedelta(days=3))
        self.assertEqual(tracker.simulation_summary(state['records'].values())['invalid'], 1)

    def test_simulation_rejects_invalid_quotes_and_started_games(self):
        for prices in ({'home': 1, 'draw': 2, 'away': 3}, {'home': float('nan'), 'draw': 2, 'away': 3},
                       {'home': 2, 'draw': 2}, {'home': 2, 'draw': 2, 'away': float('inf')}):
            with self.assertRaises(ValueError):
                tracker.simulate_fixture('2026:1', prices)
        with patch.object(tracker, 'fetch_schedule', return_value=[fixture(days=-1)]), \
             patch.object(tracker, 'refresh_current') as refresh:
            with self.assertRaises(ValueError):
                tracker.simulate_fixture('2026:1', {'home': 2, 'draw': 2, 'away': 2})
            refresh.assert_not_called()

    def test_predict_round_creates_once_and_reports_unmatched(self):
        import norsk_tipping as nt
        state = tracker.read_state()
        existing = fixture('2026:3')
        tracker.reconcile(state, [existing], NOW)
        state['records'][existing['id']]['simulation'] = {'marker': 'preserved'}
        tracker.write_state(state)
        schedule = [fixture(), fixture('2026:2'), existing]
        quote = {'fixture_id': '2026:1', 'home': 'A', 'away': 'B', 'event_id': 'ev', 'market_id': 'market',
                 'bet_stop': (NOW+timedelta(days=2)).isoformat(), 'odds': {'home': 1.5, 'draw': 2, 'away': 5}}
        # report() expects real simulation data; use the stored state to check preservation.
        with patch.object(tracker, 'current_season', return_value=2026), \
             patch.object(tracker, 'fetch_schedule', return_value=schedule) as schedule_fetch, \
             patch.object(tracker, 'refresh_current', return_value=bundle()) as refresh, \
             patch.object(tracker, 'archive_model', return_value='model'), \
             patch.object(nt, 'fetch_events', return_value=([], NOW.timestamp())) as fetch, \
             patch.object(nt, 'match_quotes', return_value=[quote]), \
             patch.object(tracker, 'report', return_value={}):
            result = tracker.predict_round(2026, 9)
            again = tracker.predict_round(2026, 9)
        saved = tracker.read_state()['records']
        self.assertEqual(result['created'], 1)
        self.assertEqual(len(result['skipped']), 2)
        self.assertEqual(again['created'], 0)
        self.assertEqual(saved['2026:3']['simulation'], {'marker': 'preserved'})
        self.assertEqual(saved['2026:1']['simulation']['pick'], 'away')
        self.assertEqual(saved['2026:1']['simulation']['quote_source'], 'Norsk Tipping')
        self.assertEqual(saved['2026:1']['simulation']['event_id'], 'ev')
        self.assertEqual(saved['2026:1']['simulation']['quoted_at'], NOW.isoformat())
        self.assertEqual(schedule_fetch.call_count, 2)
        self.assertEqual(refresh.call_count, 2)  # the unmatched match can be retried
        self.assertEqual(fetch.call_count, 2)

    def test_predict_round_rejects_expired_prices_and_failed_lookup(self):
        import norsk_tipping as nt
        quote = {'fixture_id': '2026:1', 'home': 'A', 'away': 'B', 'event_id': 'ev', 'market_id': 'market',
                 'bet_stop': (NOW+timedelta(days=2)).isoformat(), 'odds': {'home': 2, 'draw': 3, 'away': 4}}
        with patch.object(tracker, 'current_season', return_value=2026), \
             patch.object(tracker, 'fetch_schedule', return_value=[fixture()]), \
             patch.object(tracker, 'refresh_current', return_value=bundle()), \
             patch.object(tracker, 'archive_model', return_value='model'), \
             patch.object(nt, 'fetch_events', return_value=([], (NOW-timedelta(seconds=61)).timestamp())), \
             patch.object(nt, 'match_quotes', return_value=[quote]):
            result = tracker.predict_round(2026, 9)
            self.assertEqual(result['created'], 0)
            self.assertIn('expired', result['skipped'][0]['reason'])
            self.assertIsNone(tracker.read_state()['records']['2026:1']['forecast'])
        before = (tracker.DIRECTORY/'history.json').read_bytes()
        with patch.object(tracker, 'current_season', return_value=2026), \
             patch.object(tracker, 'fetch_schedule', return_value=[fixture()]), \
             patch.object(tracker, 'refresh_current', return_value=bundle()), \
             patch.object(nt, 'fetch_events', side_effect=nt.SourceError('offline')):
            with self.assertRaises(nt.SourceError):
                tracker.predict_round(2026, 9)
        self.assertEqual((tracker.DIRECTORY/'history.json').read_bytes(), before)
