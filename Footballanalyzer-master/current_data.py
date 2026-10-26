"""Refresh published league results before prediction; never spend API-Football quota."""
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import os
import tempfile
import threading
from urllib.request import Request, urlopen

import joblib
from football_config import ROOT, LEAGUES
from ml.matches import fit_bundle

BUNDLE = ROOT / 'models' / 'current_bundle.joblib'
DIVISIONS = {39: ('E0', 20), 140: ('SP1', 20), 135: ('I1', 20),
             78: ('D1', 18), 61: ('F1', 18)}
_lock = threading.Lock()


def current_season(now=None):
    now = now or datetime.now(timezone.utc)
    return now.year if now.month >= 7 else now.year - 1


def parse_results(text, league, season, now=None):
    """Dates have no guaranteed timezone: release each day's results next day +4h UTC."""
    now = now or datetime.now(timezone.utc)
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    required = {'Div', 'Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG', 'FTR'}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError('Results source is missing required columns')
    fixtures, names, seen = [], set(), set()
    for row in reader:
        if not any(row.values()):
            continue
        if any(row.get(field) is None for field in required):
            raise ValueError('Incomplete row in results source')
        if row['Div'] != DIVISIONS[league][0]:
            raise ValueError('Unexpected division in results')
        date = datetime.strptime(row['Date'], '%d/%m/%Y').replace(tzinfo=timezone.utc)
        if not datetime(season, 7, 1, tzinfo=timezone.utc) <= date < datetime(season+1, 7, 1, tzinfo=timezone.utc):
            raise ValueError('Result is outside the requested season')
        home, away = row['HomeTeam'].strip(), row['AwayTeam'].strip()
        if not home or not away or home == away:
            raise ValueError('Invalid team names')
        key = f'{league}:{season}:{home}:{away}'
        if key in seen:
            raise ValueError('Duplicate fixture in results')
        seen.add(key)
        names.update((home, away))
        if not row['FTHG'] and not row['FTAG'] and not row['FTR']:
            continue
        hg, ag = int(row['FTHG']), int(row['FTAG'])
        if min(hg, ag) < 0 or row['FTR'] != ('H' if hg > ag else 'A' if ag > hg else 'D'):
            raise ValueError('Invalid final result')
        # Timestamp is deliberately end-of-day, not a fabricated kickoff time.
        timestamp = date.timestamp() + 86400
        if timestamp + 4 * 3600 > now.timestamp():
            continue
        fixtures.append({'fixture': {'id': key, 'timestamp': timestamp, 'status': {'short': 'FT'}},
                         'league': {'id': league, 'season': season, 'round': 'Regular Season - CSV'},
                         'teams': {'home': {'id': home, 'name': home}, 'away': {'id': away, 'name': away}},
                         'goals': {'home': hg, 'away': ag}, 'result_date': date.date().isoformat()})
    if len(names) != DIVISIONS[league][1] or not fixtures:
        raise ValueError('Current division membership is incomplete; try again after results are published')
    # Do not expose names from an incomplete or future-only result set.
    played_names = {f['teams'][side]['name'] for f in fixtures for side in ('home', 'away')}
    if names != played_names:
        raise ValueError('Not all division teams have published completed results yet')
    return fixtures


def fetch_source(league, season):
    code = DIVISIONS[league][0]
    url = f'https://www.football-data.co.uk/mmz4281/{season % 100:02d}{(season+1) % 100:02d}/{code}.csv'
    request = Request(url, headers={'User-Agent': 'FootballAnalyzer/2.0', 'Cache-Control': 'no-cache'})
    with urlopen(request, timeout=25) as response:
        raw = response.read(5_000_001)
    if len(raw) > 5_000_000:
        raise ValueError('Results download exceeds size limit')
    fixtures = parse_results(raw.decode('utf-8-sig'), league, season)
    return {'league': league, 'season': season, 'url': url, 'provider': 'Football-Data.co.uk',
            'fetched_at': datetime.now(timezone.utc).timestamp(),
            'sha256': hashlib.sha256(raw).hexdigest(), 'fixtures': fixtures,
            'last_result': max(f['result_date'] for f in fixtures)}


def publish(data):
    fd, filename = tempfile.mkstemp(dir=BUNDLE.parent, suffix='.joblib')
    os.close(fd)
    try:
        joblib.dump(data, filename)
        os.replace(filename, BUNDLE)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def refresh_current(league):
    if league not in LEAGUES:
        raise ValueError('Unsupported league')
    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    # Serialize both threads and processes; publish model and source snapshot together.
    with _lock, BUNDLE.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        season = current_season()
        old = joblib.load(BUNDLE) if BUNDLE.exists() else None
        snapshots = {(s['league'], s['season']): s for s in (old or {}).get('snapshots', [])
                     if s['season'] in (season - 1, season)}
        # A real request before every prediction, even if the contents are unchanged.
        fresh = fetch_source(league, season)
        previous = snapshots.get((league, season - 1))
        if previous is None:
            previous = fetch_source(league, season - 1)
        prior_current = snapshots.get((league, season))
        if prior_current and len(fresh['fixtures']) < len(prior_current['fixtures']):
            raise ValueError('Results source lost matches; retaining the previous snapshot')
        snapshots[(league, season)] = fresh
        snapshots[(league, season - 1)] = previous
        # Only publish leagues whose current and previous seasons are both present.
        snapshots = {key: value for key, value in snapshots.items()
                     if (key[0], season) in snapshots and (key[0], season-1) in snapshots}
        sources = [{k: v for k, v in s.items() if k != 'fixtures'} for s in snapshots.values()]
        unchanged = (old and prior_current and old.get('version') == 2
                     and old['seasons'].get(league) == season
                     and prior_current['fixtures'] == fresh['fixtures']
                     and len(snapshots) == len(old.get('snapshots', [])))
        if unchanged:
            candidate = old
            candidate['sources'] = sources
        else:
            fixtures = [f for s in snapshots.values() for f in s['fixtures']]
            candidate = fit_bundle(fixtures, sources, weighted=True)
        candidate['snapshots'] = list(snapshots.values())
        candidate['season_weights'] = {'current': .7, 'previous': .3}
        publish(candidate)
        return candidate


if __name__ == '__main__':
    for league in LEAGUES:
        result = refresh_current(league)
        print(LEAGUES[league], result['seasons'][league], len(result['teams'][league]), 'teams')
    print(result['metrics'])
