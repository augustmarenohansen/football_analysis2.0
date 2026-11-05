"""Read-only, on-demand Norsk Tipping Premier League quote lookup."""
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException as HttpClientError
import json
import math
import threading
import time as clock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pl_rounds import timestamp

# Explicitly verified source-name differences; unmapped names must match exactly.
TEAM_NAMES = {
    'Leeds United': 'Leeds', 'Tottenham Hotspur': 'Tottenham',
    'Newcastle United': 'Newcastle', 'Hull City': 'Hull',
    'Nottingham Forest': "Nott'm Forest", 'Manchester City': 'Man City',
    'Ipswich Town': 'Ipswich', 'Brighton and Hove Albion': 'Brighton',
    'Manchester United': 'Man United', 'Coventry City': 'Coventry',
    'AFC Bournemouth': 'Bournemouth',
}
CACHE_SECONDS = 60
MAX_BYTES = 8_000_000
_lock = threading.Lock()
_cached = {}
_next_allowed = 0.0


class SourceError(Exception):
    pass


def source_name(name):
    return TEAM_NAMES.get(name, name)


def fetch_events(start, end):
    """One request for the full date interval; never retry automatically."""
    global _next_allowed
    if not isinstance(start, date) or not isinstance(end, date) or start > end or (end-start).days > 13:
        raise ValueError('Choose an interval of at most 14 days')
    today = datetime.now(timezone.utc).date()
    if start < today - timedelta(days=1) or end > today + timedelta(days=30):
        raise ValueError('Only upcoming fixtures within 30 days can be checked')
    key = (start.isoformat(), end.isoformat())
    with _lock:
        now = clock.time()
        if key in _cached and now - _cached[key][0] < CACHE_SECONDS:
            return _cached[key][1], _cached[key][0]
        if now < _next_allowed:
            raise SourceError('Norsk Tipping asked us to wait before trying again')
        # API expects midnight and 23:59 in its date parameters.
        url = ('https://api.norsk-tipping.no/OddsenGameInfo/v1/api/events/FBL/'
               f'{start:%Y%m%d}0000/{end:%Y%m%d}2359')
        try:
            request = Request(url, headers={'Accept': 'application/json', 'User-Agent': 'FootballAnalyzer/1.0'})
            with urlopen(request, timeout=20) as response:
                content = response.read(MAX_BYTES + 1)
                if len(content) > MAX_BYTES:
                    raise SourceError('Norsk Tipping response is too large')
            data = json.loads(content)
        except HTTPError as exc:
            if exc.code == 429:
                retry = exc.headers.get('Retry-After', '')
                try:
                    delay = max(60, int(retry))
                except ValueError:
                    try:
                        delay = max(60, int(parsedate_to_datetime(retry).timestamp() - clock.time()))
                    except (TypeError, ValueError, OverflowError):
                        delay = 3600
                _next_allowed = clock.time() + delay
                raise SourceError('Norsk Tipping rate limited the request; wait before trying again') from exc
            raise SourceError(f'Norsk Tipping returned HTTP {exc.code}') from exc
        except (URLError, TimeoutError, OSError, HttpClientError, ValueError) as exc:
            raise SourceError('Could not retrieve Norsk Tipping odds') from exc
        if not isinstance(data, dict) or not isinstance(data.get('eventList'), list):
            raise SourceError('Norsk Tipping returned an unexpected response')
        fetched_at = clock.time()
        _cached.clear()
        _cached[key] = (fetched_at, data['eventList'])
        return data['eventList'], fetched_at


def match_quotes(events, fixtures, now):
    """Use only exact, unambiguous teams, competition and UTC kickoff matches."""
    matched, duplicate = {}, set()
    by_key = {}
    for fixture in fixtures:
        if not fixture.get('kickoff'):
            continue
        key = (fixture['home'], fixture['away'], timestamp(fixture['kickoff']))
        by_key.setdefault(key, []).append(fixture)
    for event in events:
        try:
            if not isinstance(event, dict) or event.get('sportId') != 'FBL':
                continue
            tournament = event.get('tournament') or {}
            if tournament.get('id') != '35887' or tournament.get('name') != 'England - Premier League':
                continue
            home, away = event['homeParticipant'], event['awayParticipant']
            if not isinstance(home, str) or not isinstance(away, str):
                continue
            kickoff = timestamp(event['startTime'])
            options = by_key.get((source_name(home), source_name(away), kickoff), [])
            market = event.get('mainMarket') or {}
            if len(options) != 1 or kickoff <= now or market.get('marketName') != 'HUB' or market.get('live') is not False:
                continue
            if not market.get('betStop') or timestamp(market['betStop']) <= now:
                continue
            selections = market.get('selections')
            if not isinstance(selections, list) or len(selections) != 3:
                continue
            mapping = {'H': 'home', 'D': 'draw', 'A': 'away'}
            odds = {}
            for selection in selections:
                outcome = mapping.get(selection.get('selectionValue'))
                price = float(selection.get('selectionOdds'))
                if not outcome or outcome in odds or not math.isfinite(price) or not 1 < price <= 10000:
                    raise ValueError('Invalid outcome or price')
                odds[outcome] = price
            if set(odds) != set(mapping.values()) or not event.get('eventId') or not market.get('marketId'):
                continue
            fixture = options[0]
            quote = {'fixture_id': fixture['id'], 'home': home, 'away': away, 'kickoff': event['startTime'],
                     'event_id': event['eventId'], 'market_id': market['marketId'], 'bet_stop': market['betStop'],
                     'odds': odds}
            if fixture['id'] in matched:
                duplicate.add(fixture['id'])
            else:
                matched[fixture['id']] = quote
        except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
            continue
    return [value for key, value in matched.items() if key not in duplicate]
