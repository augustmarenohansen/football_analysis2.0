"""Prospective Premier League forecasts and result feedback, stored independently of models."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
from urllib.request import Request, urlopen

import joblib
from current_data import current_season, refresh_current
from football_config import ROOT
from ml.matches import features, history_games

DIRECTORY = ROOT / 'data' / 'pl_rounds'
INTERVAL = 3600
_lock = threading.Lock()
ALIASES = {'Coventry City': 'Coventry', 'Hull City': 'Hull', 'Ipswich Town': 'Ipswich',
           'Man Utd': 'Man United', 'Spurs': 'Tottenham', 'Nott\u2019m Forest': "Nott'm Forest"}
OUTCOMES = ('home', 'draw', 'away')


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Kickoff must include a time zone')
    return result


def read_state():
    path = DIRECTORY / 'history.json'
    return json.loads(path.read_text()) if path.exists() else {'records': {}, 'last_success': None, 'error': None}


def write_state(state):
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=DIRECTORY, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as file:
            json.dump(state, file, allow_nan=False)
        os.replace(name, DIRECTORY / 'history.json')
    finally:
        Path(name).unlink(missing_ok=True)


def get_json(endpoint):
    request = Request('https://fantasy.premierleague.com/api/' + endpoint + '/',
                      headers={'User-Agent': 'FootballAnalyzer/2.0'})
    with urlopen(request, timeout=25) as response:
        raw = response.read(10_000_001)
    if len(raw) > 10_000_000:
        raise ValueError('Fixture response too large')
    return json.loads(raw)


def fetch_schedule(season):
    bootstrap = get_json('bootstrap-static')
    fixtures = get_json('fixtures')
    # The endpoint always serves one season: reject an old season after rollover.
    deadlines = [timestamp(e['deadline_time']) for e in bootstrap['events']]
    if not deadlines or min(deadlines).year != season:
        raise ValueError('Premier League fixture feed does not yet cover the current season')
    teams = {t['id']: ALIASES.get(t['name'], t['name']) for t in bootstrap['teams']}
    if len(teams) != 20 or len(set(teams.values())) != 20:
        raise ValueError('Invalid Premier League team list')
    records, seen = [], set()
    for f in fixtures:
        key = f"{season}:{f['id']}"
        if key in seen:
            raise ValueError('Duplicate fixture ID')
        seen.add(key)
        kickoff = f['kickoff_time']
        if kickoff and not datetime(season, 7, 1, tzinfo=timezone.utc) <= timestamp(kickoff) < datetime(season+1, 7, 1, tzinfo=timezone.utc):
            raise ValueError('Fixture outside the current season')
        event = f['event']
        if event is not None and (type(event) is not int or not 1 <= event <= 38):
            raise ValueError('Invalid round')
        home, away = teams[f['team_h']], teams[f['team_a']]
        if home == away:
            raise ValueError('Invalid fixture teams')
        score = None
        if f['finished'] is True:
            score = [f['team_h_score'], f['team_a_score']]
            if any(type(v) is not int or v < 0 for v in score):
                raise ValueError('Invalid final score')
        records.append({'id': key, 'season': season, 'round': event, 'home': home, 'away': away,
                        'kickoff': kickoff, 'started': f['started'] is True, 'score': score})
    pairs = {(r['home'], r['away']) for r in records}
    if len(records) != 380 or len(pairs) != 380:
        raise ValueError('Incomplete or duplicated Premier League schedule')
    return records


def reconcile(state, schedule, now):
    for fixture in schedule:
        record = state['records'].setdefault(fixture['id'], {'forecast': None})
        # IDs may survive a reschedule, but must never change teams.
        if 'home' in record and (record['home'], record['away']) != (fixture['home'], fixture['away']):
            raise ValueError('Fixture identity changed')
        record.update(fixture)
        record['result'] = None
        if fixture['score'] is not None and fixture['kickoff'] and timestamp(fixture['kickoff']).timestamp() + 4*3600 <= now.timestamp():
            h, a = fixture['score']
            record['result'] = 'home' if h > a else 'away' if a > h else 'draw'
        forecast = record['forecast']
        record['eligible'] = bool(forecast and fixture['kickoff'] and
                                  timestamp(forecast['created_at']) < timestamp(fixture['kickoff']))
        if forecast and not record['eligible']:
            record['reason'] = 'Kickoff changed to before forecast creation; excluded from evaluation'
        elif not forecast:
            record['reason'] = ('No pre-match forecast recorded' if fixture['started'] or record['result'] else
                                'Waiting for the prediction window or a confirmed kickoff')


def archive_model(data):
    identity = {'trained_at': data['trained_at'], 'sources': [(s['league'], s['season'], s['sha256']) for s in data['sources']]}
    model_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    directory = DIRECTORY / 'models'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (model_id + '.joblib')
    if not path.exists():
        fd, temporary = tempfile.mkstemp(dir=directory)
        os.close(fd)
        try:
            joblib.dump(data, temporary)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return model_id


def forecast_upcoming(state, data, now, model_id):
    season = data['seasons'][39]
    teams = {t['name']: t for t in data['teams'][39].values()}
    snapshot = next(s for s in data['snapshots'] if s['league'] == 39 and s['season'] == season)
    completed = {(f['teams']['home']['name'], f['teams']['away']['name']): f for f in snapshot['fixtures']}
    # Predict all future matches of rounds that begin within seven days.
    rounds = {r['round'] for r in state['records'].values() if r['season'] == season and r['kickoff'] and
              0 < (timestamp(r['kickoff']) - now).total_seconds() <= 7*86400 and r['round'] is not None}
    labels = Counter()
    for s in data['snapshots']:
        if s['league'] == 39:
            for f in s['fixtures']:
                h, a = f['goals']['home'], f['goals']['away']
                labels['home' if h > a else 'away' if a > h else 'draw'] += 1
    baseline = {c: (labels[c]+1)/(sum(labels.values())+3) for c in OUTCOMES}
    for record in state['records'].values():
        if record['season'] != season:
            continue
        match = completed.get((record['home'], record['away']))
        record['included_in_training'] = bool(match and record['result'] and
                                               [match['goals']['home'], match['goals']['away']] == record['score'])
        if record['forecast'] or record['round'] not in rounds or not record['kickoff']:
            continue
        if record['started'] or record['score'] is not None or timestamp(record['kickoff']) <= now or match:
            continue
        home, away = teams.get(record['home']), teams.get(record['away'])
        if not home or not away or min(history_games(home), history_games(away)) < 5:
            record['reason'] = 'Insufficient team history or unmatched team name'
            continue
        inputs = features(home, away, 39)
        model = data['model']
        probabilities = {str(c): float(p) for c, p in zip(model.classes_, model.predict_proba([inputs])[0])}
        if set(probabilities) != set(OUTCOMES) or any(not math.isfinite(p) or p < 0 for p in probabilities.values()) or abs(sum(probabilities.values())-1) > 1e-8:
            raise ValueError('Invalid model probabilities')
        # Check the clock again after network access/training, never backdate a forecast.
        created = utcnow()
        if created >= timestamp(record['kickoff']):
            continue
        record['forecast'] = {'created_at': created.isoformat(), 'kickoff_at_creation': record['kickoff'],
                              'round_at_creation': record['round'], 'probabilities': probabilities,
                              'pick': max(probabilities, key=probabilities.get), 'baseline': baseline,
                              'features': inputs, 'model_id': model_id, 'trained_at': data['trained_at'],
                              'last_result': snapshot['last_result'], 'data_checked_at': snapshot['fetched_at']}
        record['eligible'] = True
        record['reason'] = None


def metrics(records):
    scored = [r for r in records if r.get('eligible') and r.get('result')]
    if not scored:
        return {'count': 0, 'accuracy': None, 'log_loss': None, 'brier': None, 'baseline_log_loss': None}
    return {'count': len(scored),
            'accuracy': sum(r['forecast']['pick'] == r['result'] for r in scored)/len(scored),
            'log_loss': sum(-math.log(max(r['forecast']['probabilities'][r['result']], 1e-15)) for r in scored)/len(scored),
            'brier': sum(sum((r['forecast']['probabilities'][c] - int(c == r['result']))**2 for c in OUTCOMES) for r in scored)/len(scored),
            'baseline_log_loss': sum(-math.log(r['forecast']['baseline'][r['result']]) for r in scored)/len(scored)}


def report():
    state = read_state()
    records = sorted(state['records'].values(), key=lambda r: (r['season'], r['round'] or 99, r['kickoff'] or '9999'))
    return {**{k: v for k, v in state.items() if k != 'records'}, 'records': records,
            'metrics': metrics(records), 'interval_minutes': INTERVAL//60,
            'rounds': [{'season': season, 'round': number, **metrics([r for r in records if r['season'] == season and r['round'] == number])}
                       for season, number in sorted({(r['season'], r['round']) for r in records if r['round']})]}


def sync():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    with _lock, (DIRECTORY / 'sync.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_state()
        state['last_attempt'] = utcnow().isoformat()
        try:
            schedule = fetch_schedule(current_season())
            reconcile(state, schedule, utcnow())
            # Persist evaluation even if the separate results/training source is unavailable.
            write_state(state)
            data = refresh_current(39)
            if data['seasons'][39] != current_season():
                raise ValueError('Model season does not match schedule')
            model_id = archive_model(data)
            forecast_upcoming(state, data, utcnow(), model_id)
            state.update(last_success=utcnow().isoformat(), error=None, model_id=model_id,
                         trained_at=data['trained_at'])
        except Exception as exc:
            # Never let a background error kill monitoring or overwrite forecasts.
            state['error'] = f'Update failed ({type(exc).__name__}). Existing forecasts are preserved; next check in one hour or use Check now.'
        write_state(state)
    return report()


async def monitor():
    while True:
        await asyncio.to_thread(sync)
        await asyncio.sleep(INTERVAL)
