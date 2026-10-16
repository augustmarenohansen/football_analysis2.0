"""Local-only serving of cached match models. No upstream calls in web requests."""
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import joblib
from football_config import BUNDLE, LEAGUES
from ml.matches import features

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
        if candidate.get('version') != 1:
            raise HTTPException(503, 'Unsupported model format')
        _cached, _stamp = candidate, stamp
    return _cached


@router.get('/api/catalog')
def catalog():
    data = bundle()
    return {
        'leagues': [dict(id=lid, name=name, ready=bool(data and lid in data['teams']),
                         season=data['seasons'].get(lid) if data else None) for lid, name in LEAGUES.items()],
        'trained_at': data['trained_at'] if data else None,
        'last_match': data['last_match'] if data else None,
        'metrics': data['metrics'] if data else None,
        'sources': data['sources'] if data else [],
    }


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
    _, values = league_data(league)
    return {'teams': sorted(t['name'] for t in values.values())}


@router.get('/api/football/team/{team}')
def stats(team: str, league: int):
    _, values = league_data(league)
    return public_stats(find_team(values, team))


class Match(BaseModel):
    home_team: str
    away_team: str
    league: int


@router.post('/api/football/compare')
def compare(match: Match):
    data, values = league_data(match.league)
    if match.home_team == match.away_team:
        raise HTTPException(422, 'Pick two different teams')
    home, away = find_team(values, match.home_team), find_team(values, match.away_team)
    if min(home['mp'], away['mp']) < 5:
        raise HTTPException(409, 'At least five completed games per team are needed in this season')
    model = data['model']
    probabilities = dict(zip(model.classes_, model.predict_proba([features(home, away, match.league)])[0]))
    def details(team):
        n = max(team['mp'], 1)
        return {'form': {'win_ratio': round(100 * team['w'] / n, 1),
                         'goals_per_game': round(team['gf'] / n, 2),
                         'defense_rating': round(1 / (team['ga'] / n + 1), 2)}}
    labels = {'home': 'Home Win', 'away': 'Away Win', 'draw': 'Draw'}
    return {'home_win': float(probabilities['home']), 'draw': float(probabilities['draw']),
            'away_win': float(probabilities['away']), 'prediction': labels[max(probabilities, key=probabilities.get)],
            'details': {'model': 'Match-result model (historical data)', 'home_team': details(home),
                        'away_team': details(away), 'season': data['seasons'][match.league],
                        'metrics': data['metrics']}}
