import unittest
from unittest.mock import patch
import numpy as np
from pydantic import ValidationError
from api.odds import OddsInput, assess_odds
from api.matches import Match, compare
from ml.matches import empty_stats


class OddsTests(unittest.TestCase):
    def test_arithmetic_and_zero_probability(self):
        for price, expected, sign in [(2.2, .1, 'positive'), (2, 0, 'break_even'), (1.5, -.25, 'negative')]:
            result = assess_odds(OddsInput(outcome='home', decimal=price), {'home': .5}, 2024)
            self.assertAlmostEqual(result['expected_net_return_per_unit'], expected)
            self.assertAlmostEqual(result['break_even_probability'], 1 / price)
            self.assertAlmostEqual(result['edge_percentage_points'], (.5 - 1 / price) * 100)
            self.assertEqual(result['fair_odds'], 2)
            self.assertEqual(result['simulation_result'], sign)
            self.assertEqual(result['assessment'], 'insufficient_evidence')
        result = assess_odds(OddsInput(outcome='away', decimal=2), {'away': 0}, 2024)
        self.assertIsNone(result['fair_odds'])
        self.assertEqual(result['expected_net_return_per_unit'], -1)

    def test_invalid_prices_and_unsupported_context(self):
        for price in [0, -1, 1, float('nan'), float('inf'), 'abc']:
            with self.assertRaises(ValidationError):
                OddsInput(outcome='home', decimal=price)
        for override in [{'outcome': 'qualify'}, {'market': 'extra_time'}, {'mode': 'current_bet'}]:
            with self.assertRaises(ValidationError):
                OddsInput(**dict({'outcome': 'home', 'decimal': 2}, **override))

    def test_quotes_do_not_affect_model_and_map_all_outcomes(self):
        class Model:
            classes_ = np.array(['away', 'draw', 'home'])
            def predict_proba(self, values):
                return np.array([[.2, .3, .5]])
        teams = {'1': empty_stats('A'), '2': empty_stats('B')}
        for team in teams.values():
            team['mp'] = 10
        data = {'teams': {135: teams}, 'model': Model(), 'seasons': {135: 2024}, 'metrics': {}}
        with patch('api.matches.refresh', return_value=data):
            plain = compare(Match(home_team='A', away_team='B', league=135))
            self.assertNotIn('odds_assessment', plain)
            for outcome, probability in [('home', .5), ('draw', .3), ('away', .2)]:
                for price in [1.1, 2.2, 100]:
                    result = compare(Match(home_team='A', away_team='B', league=135,
                                           odds=OddsInput(outcome=outcome, decimal=price)))
                    for key in ('home_win', 'draw', 'away_win', 'prediction'):
                        self.assertEqual(result[key], plain[key])
                    assessment = result['odds_assessment']
                    self.assertEqual(assessment['model_probability'], probability)
                    self.assertEqual(assessment['assessment'], 'insufficient_evidence')
                    self.assertEqual(assessment['season'], 2024)


if __name__ == '__main__':
    unittest.main()
