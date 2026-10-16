"""Explicit, cached API-Football import. Page views never call the provider."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import joblib
from football_config import ROOT, CACHE, BUNDLE, LEAGUES
from ml.matches import fit_bundle


class ProviderError(RuntimeError):
    pass


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def get_key():
    key = os.environ.get('API_FOOTBALL_KEY', '').strip()
    if not key and (ROOT / '.env').exists():
        for line in (ROOT / '.env').read_text().splitlines():
            if line.strip().startswith('API_FOOTBALL_KEY='):
                key = line.split('=', 1)[1].strip().strip('\"\'')
                break
    if not key:
        raise ProviderError('Missing API_FOOTBALL_KEY. Add it to Footballanalyzer-master/.env.')
    return key


class Client:
    def __init__(self, key, max_requests=35):
        self.key, self.max_requests, self.calls = key, max_requests, 0
        self.last_call = 0
        CACHE.mkdir(parents=True, exist_ok=True)

    def get(self, endpoint, params):
        query = endpoint + '?' + urlencode(sorted(params.items()))
        path = CACHE / (hashlib.sha256(query.encode()).hexdigest() + '.json')
        if path.exists():
            cached = json.loads(path.read_text())
            if time.time() - cached['fetched_at'] < 86400:
                if cached.get('error'):
                    raise ProviderError(cached['error'])
                print(f'Cache: {query}')
                return cached
        quota_path = CACHE / 'quota.json'
        today = datetime.now(timezone.utc).date().isoformat()
        quota = json.loads(quota_path.read_text()) if quota_path.exists() else {}
        if quota.get('day') != today:
            quota = dict(day=today, calls=0, remaining=100)
        if self.calls >= self.max_requests or quota['calls'] >= 80 or quota['remaining'] <= 20:
            raise RuntimeError('Request budget reached. Stopping with 20 requests reserved; try another day.')
        time.sleep(max(0, 6.1 - (time.monotonic() - self.last_call)))
        # Reserve before sending; failures and interrupted requests still consume our local budget.
        quota['calls'] += 1
        quota['remaining'] -= 1
        atomic_json(quota_path, quota)
        self.calls += 1
        self.last_call = time.monotonic()
        request = Request('https://v3.football.api-sports.io/' + query,
                          headers={'x-apisports-key': self.key})
        try:
            with urlopen(request, timeout=45) as response:
                remaining = response.headers.get('x-ratelimit-requests-remaining')
                if remaining is not None:
                    quota['remaining'] = min(quota['remaining'], int(remaining))
                    atomic_json(quota_path, quota)
                payload = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f'API-Football HTTP {exc.code}; stopped without automatic retry.') from None
        except URLError:
            raise RuntimeError('Could not connect to API-Football; stopped without automatic retry.') from None
        print(f'Fetched {query}; remaining daily budget reported/estimated: {quota["remaining"]}')
        if payload.get('errors'):
            error = json.dumps(payload['errors'], ensure_ascii=False).replace(self.key, '[redacted]')
            atomic_json(path, dict(fetched_at=time.time(), error=error))
            # Subscription/auth/rate failures stop the run; season access failures can be skipped.
            if not any(word in error.lower() for word in ('season', 'plan')):
                raise RuntimeError(error)
            raise ProviderError(error)
        if payload.get('paging', {}).get('total', 1) > 1:
            raise RuntimeError('Unexpected paginated response. Refusing to use incomplete data.')
        cached = dict(fetched_at=time.time(), query=query, response=payload['response'])
        atomic_json(path, cached)
        return cached


def update(args):
    client = Client(get_key(), args.max_requests)
    all_fixtures, sources = [], []
    for league in args.leagues:
        info = client.get('leagues', {'id': league})['response']
        if len(info) != 1 or info[0]['league']['id'] != league:
            raise RuntimeError(f'Invalid league metadata for {league}')
        seasons = {s['year']: s for s in info[0]['seasons']}
        for year in args.seasons:
            if year not in seasons:
                print(f'{LEAGUES[league]} {year}: unavailable in league metadata')
                continue
            try:
                cached = client.get('fixtures', {'league': league, 'season': year})
            except ProviderError as exc:
                print(f'{LEAGUES[league]} {year}: {exc}')
                continue
            fixtures = cached['response']
            if not fixtures:
                print(f'{LEAGUES[league]} {year}: no fixtures')
                continue
            if any(f['league']['id'] != league or f['league']['season'] != year for f in fixtures):
                raise RuntimeError('Provider returned fixtures for the wrong league/season')
            all_fixtures.extend(fixtures)
            sources.append(dict(league=league, season=year, fetched_at=cached['fetched_at'], fixtures=len(fixtures)))
    bundle = fit_bundle(all_fixtures, sources)
    # Don't silently remove an existing league or replace its latest season with an older one.
    if BUNDLE.exists():
        previous = joblib.load(BUNDLE)
        if any(bundle['seasons'].get(lid, 0) < year for lid, year in previous['seasons'].items()):
            raise RuntimeError('Import would remove a league or downgrade a season; existing model retained.')
    temporary = BUNDLE.with_suffix('.tmp')
    joblib.dump(bundle, temporary)
    joblib.load(temporary)  # Confirm readability before publishing a single model+data snapshot.
    temporary.replace(BUNDLE)
    print(json.dumps(bundle['metrics'], indent=2))
    print(f'Updated {len(bundle["teams"])} leagues using {client.calls} API requests. Website reloads data automatically.')
    if bundle['metrics']['log_loss'] >= bundle['metrics']['baseline_log_loss']:
        print('Validation warning: model does not beat the simple outcome-frequency baseline on log loss.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--leagues', nargs='+', type=int, choices=list(LEAGUES), default=list(LEAGUES))
    parser.add_argument('--seasons', nargs='+', type=int, default=[2022, 2023, 2024, 2025, 2026])
    parser.add_argument('--max-requests', type=int, default=35)
    args = parser.parse_args()
    if not 1 <= args.max_requests <= 80:
        parser.error('--max-requests must be between 1 and 80')
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE / '.update.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('An update is already running.')
        try:
            update(args)
        except (RuntimeError, ValueError, KeyError) as exc:
            raise SystemExit(f'Update stopped; active data/model unchanged: {exc}') from None


if __name__ == '__main__':
    main()
