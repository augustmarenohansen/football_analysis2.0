"""Price arithmetic for historical simulations, not current-fixture advice."""
from typing import Literal
from pydantic import BaseModel, Field


class OddsInput(BaseModel):
    outcome: Literal['home', 'draw', 'away']
    decimal: float = Field(gt=1, allow_inf_nan=False)
    market: Literal['90_minute_1x2'] = '90_minute_1x2'
    mode: Literal['historical_simulation'] = 'historical_simulation'


def assess_odds(quote: OddsInput, probabilities: dict, season: int):
    probability = float(probabilities[quote.outcome])
    break_even = 1 / quote.decimal
    expected_return = probability * quote.decimal - 1
    return {
        'outcome': quote.outcome, 'decimal_odds': quote.decimal,
        'model_probability': probability, 'break_even_probability': break_even,
        'fair_odds': 1 / probability if probability > 0 else None,
        'edge_percentage_points': (probability - break_even) * 100,
        'expected_net_return_per_unit': expected_return,
        'simulation_result': ('positive' if expected_return > 1e-12 else
                              'negative' if expected_return < -1e-12 else 'break_even'),
        # Never infer readiness for a current bet from a positive point estimate.
        'assessment': 'insufficient_evidence',
        'mode': quote.mode, 'market': quote.market, 'season': season,
        'reason': 'Historical team snapshot only. No verified fixture, quote timing, or calibrated uncertainty buffer is available for a current bet.',
        'assumptions': '90 minutes plus stoppage time; excludes extra time and penalties. Standard win/lose bet, no fees or taxes. Single-price comparison; bookmaker margin is not estimated.',
    }
