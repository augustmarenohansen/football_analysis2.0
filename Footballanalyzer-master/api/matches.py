"""Current-season predictions after refreshing published results."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import joblib
from football_config import LEAGUES
from current_data import BUNDLE, refresh_current
from ml.matches import features, history_games
from api.odds import OddsInput, assess_odds

router = APIRouter()
_cached = None
_stamp = None


def bundle():
    global _cached, _stamp
    if not BUNDLE.exists():
        return None
    stamp = BUNDLE.stat().st_mtime_ns
    if stamp != _stamp:
        candidate = joblib.load(BUNDLE)
        if candidate.get('version') not in (1, 2):
            raise HTTPException(503, 'Unsupported model format')
        _cached, _stamp = candidate, stamp
    return _cached


@router.get('/api/catalog')
def catalog():
    data = bundle()
    return {
        'leagues': [dict(id=lid, name=name, ready=bool(data and lid in data['teams']), available=True,
                         season=data['seasons'].get(lid) if data else None) for lid, name in LEAGUES.items()],
        'trained_at': data['trained_at'] if data else None,
        'last_match': data['last_match'] if data else None,
        'metrics': data['metrics'] if data else None,
        'sources': data['sources'] if data else [],
    }


def refresh(league):
    if league not in LEAGUES:
        raise HTTPException(422, 'Unsupported league')
    try:
        return refresh_current(league)
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(503, 'Could not verify current results. No prediction was made. '
                            'The previous snapshot is preserved. Please try again later.') from exc


def freshness(data, league):
    season = data['seasons'][league]
    source = next((s for s in data.get('sources', [])
                   if s['league'] == league and s['season'] == season), {})
    return {'season': season, 'previous_season': season - 1,
            'checked_at': source.get('fetched_at'), 'last_result': source.get('last_result'),
            'provider': source.get('provider'), 'weights': data.get('season_weights'),
            'metrics': data['metrics']}


def league_data(league):
    data = bundle()
    if not data or league not in data['teams']:
        raise HTTPException(409, 'No imported match data for this league yet')
    return data, data['teams'][league]


def find_team(teams, name):
    for team in teams.values():
        if team['name'] == name:
            return team
    raise HTTPException(404, 'Team not found in selected league')


def public_stats(team):
    return {**{k: team[k] for k in ('mp', 'w', 'd', 'l', 'gf', 'ga', 'gd', 'pts')},
            'last_5': ' '.join(team['form'][-5:]) or '-', 'top_scorer': '-', 'goalkeeper': '-'}


@router.get('/api/football/teams')
def teams(league: int):
    data = refresh(league)
    values = data['teams'][league]
    return {'teams': sorted(t['name'] for t in values.values()), 'data': freshness(data, league)}


@router.get('/api/football/team/{team}')
def stats(team: str, league: int):
    _, values = league_data(league)
    return public_stats(find_team(values, team))


class Match(BaseModel):
    home_team: str
    away_team: str
    league: int
    odds: OddsInput | None = None


@router.post('/api/football/compare')
def compare(match: Match):
    if match.home_team == match.away_team:
        raise HTTPException(422, 'Pick two different teams')
    data = refresh(match.league)
    values = data['teams'][match.league]
    home, away = find_team(values, match.home_team), find_team(values, match.away_team)
    if min(history_games(home), history_games(away)) < 5:
        raise HTTPException(409, 'At least five completed games per team across these two seasons are required; '
                            'promoted teams without previous top-division history need five current-season games')
    model = data['model']
    probabilities = dict(zip(model.classes_, model.predict_proba([features(home, away, match.league)])[0]))
    def details(team):
        n = max(team['mp'], 1)
        return {'form': {'win_ratio': round(100 * team['w'] / n, 1),
                         'goals_per_game': round(team['gf'] / n, 2),
                         'defense_rating': round(1 / (team['ga'] / n + 1), 2)}}
    labels = {'home': 'Home Win', 'away': 'Away Win', 'draw': 'Draw'}
    result = {'home_win': float(probabilities['home']), 'draw': float(probabilities['draw']),
            'away_win': float(probabilities['away']), 'prediction': labels[max(probabilities, key=probabilities.get)],
            'data': freshness(data, match.league),
            'team_stats': {'home': public_stats(home), 'away': public_stats(away)},
            'details': {'model': 'Two-season model · 70% current / 30% previous when both are available', 'home_team': details(home),
                        'away_team': details(away), 'season': data['seasons'][match.league],
                        'metrics': data['metrics']}}

    if match.odds is not None:
        result['odds_assessment'] = assess_odds(match.odds, probabilities, data['seasons'][match.league])
    return result
