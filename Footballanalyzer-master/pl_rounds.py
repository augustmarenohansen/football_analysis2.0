"""Prospective Premier League forecasts and result feedback, stored independently of models."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
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


def simulation_result(record):
    simulation = record.get('simulation')
    if not simulation:
        return None
    # A postponed match can remain pending; an earlier kickoff invalidates the record.
    if not record.get('kickoff') or timestamp(simulation['created_at']) >= timestamp(record['kickoff']):
        return {'status': 'invalid', 'stake': 0, 'payout': 0, 'net': 0}
    if not record.get('result'):
        return {'status': 'pending', 'stake': 10, 'payout': None, 'net': None}
    odds = Decimal(str(simulation['odds'][simulation['pick']]))
    payout = (Decimal('10') * odds if simulation['pick'] == record['result'] else Decimal('0'))
    payout = payout.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    return {'status': 'settled', 'stake': 10, 'payout': float(payout), 'net': float(payout - 10)}


def simulation_summary(records):
    results = [x for x in (simulation_result(r) for r in records) if x]
    settled = [x for x in results if x['status'] == 'settled']
    pending = [x for x in results if x['status'] == 'pending']
    return {'settled': len(settled), 'pending': len(pending),
            'invalid': sum(x['status'] == 'invalid' for x in results),
            'stake': len(settled) * 10, 'pending_stake': len(pending) * 10,
            'payout': round(sum(x['payout'] for x in settled), 2),
            'net': round(sum(x['net'] for x in settled), 2)}


def round_finished(records):
    """Completion is based on every fixture currently assigned to the round."""
    return bool(records) and all(r.get('result') in OUTCOMES for r in records)


def simulate_fixture(fixture_id, prices):
    """Capture manual prices before creating an independent simulated pick."""
    if set(prices) != set(OUTCOMES) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                                             not math.isfinite(v) or v <= 1 or v > 10000
                                             for v in prices.values()):
        raise ValueError('Enter three finite decimal odds greater than 1 and no more than 10000')
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    with _lock, (DIRECTORY / 'sync.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_state()
        quoted_at = utcnow()
        schedule = fetch_schedule(current_season())
        reconcile(state, schedule, utcnow())
        record = state['records'].get(fixture_id)
        if not record:
            raise ValueError('Fixture not found in current Premier League schedule')
        if record.get('simulation'):
            raise ValueError('A simulation has already been saved for this fixture')
        if not record['kickoff'] or record['started'] or record['score'] is not None or timestamp(record['kickoff']) <= utcnow():
            raise ValueError('The fixture must have a confirmed future kickoff and must not have started')
        data = refresh_current(39)
        if data['seasons'][39] != record['season']:
            raise ValueError('Model and fixture seasons differ')
        source = next(s for s in data['snapshots'] if s['league'] == 39 and s['season'] == record['season'])
        if any(f['teams']['home']['name'] == record['home'] and f['teams']['away']['name'] == record['away']
               for f in source['fixtures']):
            raise ValueError('This fixture is already present in the completed-results data')
        teams = {t['name']: t for t in data['teams'][39].values()}
        home, away = teams.get(record['home']), teams.get(record['away'])
        if not home or not away or min(history_games(home), history_games(away)) < 5:
            raise ValueError('Team names or match history are insufficient for this fixture')
        inputs = features(home, away, 39)
        model = data['model']
        probabilities = {str(c): float(p) for c, p in zip(model.classes_, model.predict_proba([inputs])[0])}
        if set(probabilities) != set(OUTCOMES) or any(not math.isfinite(p) or p < 0 for p in probabilities.values()) or abs(sum(probabilities.values()) - 1) > 1e-8:
            raise ValueError('Invalid model probabilities')
        model_id = archive_model(data)
        created = utcnow()
        if created >= timestamp(record['kickoff']):
            raise ValueError('Kickoff passed while creating the prediction')
        pick = max(OUTCOMES, key=lambda outcome: probabilities[outcome] * prices[outcome] - 1)
        record['simulation'] = {'odds': prices, 'quote_source': 'manual', 'quoted_at': quoted_at.isoformat(),
                                'created_at': created.isoformat(), 'kickoff_at_creation': record['kickoff'],
                                'round_at_creation': record['round'], 'probabilities': probabilities,
                                'pick': pick, 'stake': 10, 'model_id': model_id, 'features': inputs,
                                'last_result': source['last_result'], 'data_checked_at': source['fetched_at']}
        write_state(state)
    return report()


def predict_round(season, round_number):
    """Create immutable simulations from one fresh model and one odds snapshot."""
    # Import here because the odds adapter uses this module's timestamp parser.
    import norsk_tipping
    if season != current_season() or not 1 <= round_number <= 38:
        raise ValueError('Choose a round in the current Premier League season')
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    with _lock, (DIRECTORY / 'sync.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_state()
        reconcile(state, fetch_schedule(season), utcnow())
        fixtures = [r for r in state['records'].values() if r['season'] == season and r['round'] == round_number]
        if not fixtures:
            raise ValueError('No fixtures found for this round')
        skips = []
        candidates = []
        for record in fixtures:
            if record.get('simulation'):
                skips.append({'fixture_id': record['id'], 'reason': 'Already has a saved simulation'})
            elif not record.get('kickoff') or record['started'] or record.get('score') is not None or timestamp(record['kickoff']) <= utcnow():
                skips.append({'fixture_id': record['id'], 'reason': 'Kickoff has passed or is unconfirmed'})
            else:
                candidates.append(record)
        if not candidates:
            return {'created': 0, 'skipped': skips, 'quotes': [], 'report': report()}

        # Refresh training data first, then get prices before producing predictions.
        data = refresh_current(39)
        if data['seasons'].get(39) != season:
            raise ValueError('Model and fixture seasons differ')
        source = next(s for s in data['snapshots'] if s['league'] == 39 and s['season'] == season)
        teams = {t['name']: t for t in data['teams'][39].values()}
        completed = {(f['teams']['home']['name'], f['teams']['away']['name']) for f in source['fixtures']}
        starts = [timestamp(r['kickoff']).astimezone(timezone.utc).date() for r in candidates]
        from datetime import timedelta
        events, fetched_at = norsk_tipping.fetch_events(min(starts)-timedelta(days=1), max(starts)+timedelta(days=1))
        quotes = norsk_tipping.match_quotes(events, candidates, utcnow())
        by_id = {quote['fixture_id']: quote for quote in quotes}
        model_id = archive_model(data)
        created_count = 0
        for record in candidates:
            quote = by_id.get(record['id'])
            if not quote:
                skips.append({'fixture_id': record['id'], 'reason': 'No unambiguous open Norsk Tipping odds'})
                continue
            home, away = teams.get(record['home']), teams.get(record['away'])
            if (record['home'], record['away']) in completed:
                skips.append({'fixture_id': record['id'], 'reason': 'Already in completed-results data'})
                continue
            if not home or not away or min(history_games(home), history_games(away)) < 5:
                skips.append({'fixture_id': record['id'], 'reason': 'Insufficient or unmatched team history'})
                continue
            inputs = features(home, away, 39)
            model = data['model']
            probabilities = {str(c): float(p) for c, p in zip(model.classes_, model.predict_proba([inputs])[0])}
            if set(probabilities) != set(OUTCOMES) or any(not math.isfinite(p) or p < 0 for p in probabilities.values()) or abs(sum(probabilities.values()) - 1) > 1e-8:
                raise ValueError('Invalid model probabilities; no round simulations were saved')
            created = utcnow()
            quoted = datetime.fromtimestamp(fetched_at, timezone.utc)
            if (created < quoted or (created - quoted).total_seconds() > norsk_tipping.CACHE_SECONDS or
                    created >= timestamp(record['kickoff']) or created >= timestamp(quote['bet_stop'])):
                skips.append({'fixture_id': record['id'], 'reason': 'Odds expired or kickoff passed before prediction'})
                continue
            prices = quote['odds']
            pick = max(OUTCOMES, key=lambda outcome: probabilities[outcome] * prices[outcome] - 1)
            record['simulation'] = {'odds': prices, 'quote_source': 'Norsk Tipping',
                                    'quoted_at': quoted.isoformat(), 'created_at': created.isoformat(),
                                    'kickoff_at_creation': record['kickoff'], 'round_at_creation': record['round'],
                                    'probabilities': probabilities, 'pick': pick, 'stake': 10, 'model_id': model_id,
                                    'features': inputs, 'last_result': source['last_result'],
                                    'data_checked_at': source['fetched_at'],
                                    'event_id': quote['event_id'], 'market_id': quote['market_id'],
                                    'bet_stop': quote['bet_stop'], 'source_home': quote['home'], 'source_away': quote['away']}
            created_count += 1
        write_state(state)
    return {'created': created_count, 'skipped': skips, 'quotes': quotes, 'report': report()}


def report():
    state = read_state()
    records = sorted(state['records'].values(), key=lambda r: (r['season'], r['round'] or 99, r['kickoff'] or '9999'))
    for record in records:
        record['simulation_result'] = simulation_result(record)
    return {**{k: v for k, v in state.items() if k != 'records'}, 'records': records,
            'metrics': metrics(records), 'simulation': simulation_summary(records), 'interval_minutes': INTERVAL//60,
            'rounds': [{'season': season, 'round': number,
                        'finished': round_finished([r for r in records if r['season'] == season and r['round'] == number]),
                        **metrics([r for r in records if r['season'] == season and r['round'] == number]),
                        'simulation': simulation_summary([r for r in records if r['season'] == season and r['round'] == number])}
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
