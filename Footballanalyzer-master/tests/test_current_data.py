import copy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import joblib
import current_data as current
from ml.matches import apply_result, build_examples, empty_stats, features, history_games
from test_matches import fixtures


class SeasonalFeaturesTests(unittest.TestCase):
    def test_season_rates_are_weighted_not_season_lengths(self):
        old, new = empty_stats('A'), empty_stats('A')
        for _ in range(38):
            apply_result(old, 0, 2)
        for _ in range(5):
            apply_result(new, 3, 0)
        new['_previous'] = old
        result = features(new, new, 135)
        self.assertAlmostEqual(result['home_gf'], .7 * 3)
        self.assertAlmostEqual(result['home_ga'], .3 * 2)
        self.assertAlmostEqual(result['home_form'], .7 * 3)
        self.assertEqual(history_games(new), 43)
        promoted = empty_stats('Promoted')
        for _ in range(5):
            apply_result(promoted, 2, 0)
        self.assertEqual(features(promoted, promoted, 135)['home_gf'], 2)
        self.assertEqual(history_games(promoted), 5)
        empty = empty_stats('A')
        empty['_previous'] = old
        self.assertEqual(features(empty, empty, 135)['home_ga'], 2)

    def test_current_season_uses_previous_without_future_leakage(self):
        values = fixtures(30)
        for row in values[15:]:
            row['league']['season'] = 2021
        before, states = build_examples(values, weighted=True)
        self.assertEqual(states[(135, 2021, 1)]['_previous']['mp'], 15)
        self.assertTrue(any(x[0] == values[15]['fixture']['timestamp'] for x in before))
        changed = copy.deepcopy(values)
        changed[20]['goals']['home'] = 99
        after, _ = build_examples(changed, weighted=True)
        for a, b in zip(before, after):
            if a[0] <= values[20]['fixture']['timestamp']:
                self.assertEqual(a[1], b[1])
        promoted = copy.deepcopy(values)
        for row in promoted[15:]:
            row['teams']['home'] = {'id': 3, 'name': 'Promoted'}
        examples, _ = build_examples(promoted, weighted=True)
        self.assertFalse(any(x[0] == values[15]['fixture']['timestamp'] for x in examples))
        self.assertTrue(any(x[0] == values[20]['fixture']['timestamp'] for x in examples))


class SourceTests(unittest.TestCase):
    def csv(self):
        return 'Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n' + '\n'.join(
            f'I1,01/08/2026,Team{i},Team{i+1},2,1,H' for i in range(0, 20, 2))

    def test_dates_scores_roster_and_duplicate_validation(self):
        now = datetime(2026, 8, 3, tzinfo=timezone.utc)
        rows = current.parse_results(self.csv(), 135, 2026, now)
        self.assertEqual(len(rows), 10)
        for text in [self.csv().replace('I1', 'E0'), self.csv().replace(',2,1,H', ',2,1,D'),
                     self.csv() + '\nI1,01/08/2026,Team0,Team1,2,1,H',
                     self.csv().replace('Team19', 'Team18'), self.csv().replace('2026', '2025')]:
            with self.assertRaises(ValueError):
                current.parse_results(text, 135, 2026, now)
        # Today's results cannot become features before the date-based availability margin.
        with self.assertRaises(ValueError):
            current.parse_results(self.csv(), 135, 2026, datetime(2026, 8, 2, 3, tzinfo=timezone.utc))

    def test_season_rollover(self):
        self.assertEqual(current.current_season(datetime(2026, 6, 30)), 2025)
        self.assertEqual(current.current_season(datetime(2026, 7, 1)), 2026)

    def test_refresh_checks_network_each_time_and_preserves_bundle_on_failure(self):
        # Isolated synthetic snapshots; never publish into the application directory.
        def source(league, season):
            rows = fixtures()
            for f in rows:
                f['league']['season'] = season
                f['fixture']['id'] = str(season) + ':' + str(f['fixture']['id'])
                f['fixture']['timestamp'] += (season - 2020) * 366 * 86400
            return {'league': league, 'season': season, 'fixtures': rows,
                    'fetched_at': 1, 'sha256': str(season)}
        with tempfile.TemporaryDirectory() as directory, patch.object(current, 'BUNDLE', Path(directory)/'current.joblib'), \
                patch.object(current, 'current_season', return_value=2021), \
                patch.object(current, 'fetch_source', side_effect=source) as fetch:
            first = current.refresh_current(135)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(first['seasons'][135], 2021)
            with patch.object(current, 'fit_bundle') as fit:
                current.refresh_current(135)
                fit.assert_not_called()
            self.assertEqual(fetch.call_count, 3)
            saved = current.BUNDLE.read_bytes()
            with patch.object(current, 'fetch_source', side_effect=OSError('offline')):
                with self.assertRaises(OSError):
                    current.refresh_current(135)
            self.assertEqual(current.BUNDLE.read_bytes(), saved)
            self.assertEqual(joblib.load(current.BUNDLE)['version'], 2)

    def test_prediction_does_not_fall_back_after_refresh_failure(self):
        from api import matches
        from fastapi import HTTPException
        with patch.object(matches, 'refresh_current', side_effect=OSError('offline')):
            with self.assertRaises(HTTPException) as error:
                matches.compare(matches.Match(home_team='A', away_team='B', league=135))
            self.assertEqual(error.exception.status_code, 503)
