import copy
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.error import HTTPError
import norsk_tipping as nt

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
FIXTURE = {'id': '2026:1', 'home': 'Leeds', 'away': 'Tottenham', 'kickoff': '2026-11-07T12:30:00+00:00'}
EVENT = {'sportId': 'FBL', 'eventId': 'e1', 'homeParticipant': 'Leeds United', 'awayParticipant': 'Tottenham Hotspur',
         'startTime': '2026-11-07T13:30:00+01:00', 'tournament': {'id': '35887', 'name': 'England - Premier League'},
         'mainMarket': {'marketId': 'm1', 'marketName': 'HUB', 'live': False, 'betStop': '2026-11-07T13:30:00+01:00',
                        'selections': [{'selectionValue': 'H', 'selectionOdds': '2.55'},
                                       {'selectionValue': 'D', 'selectionOdds': '3.30'},
                                       {'selectionValue': 'A', 'selectionOdds': '2.65'}]}}

class NorskTippingTest(unittest.TestCase):
    def test_matching_names_timezone_and_prices(self):
        quote, = nt.match_quotes([EVENT], [FIXTURE], NOW)
        self.assertEqual(quote['fixture_id'], FIXTURE['id'])
        self.assertEqual(quote['home'], 'Leeds United')
        self.assertEqual(quote['odds'], {'home': 2.55, 'draw': 3.30, 'away': 2.65})

    def test_ambiguous_or_wrong_fixture_and_bad_markets_rejected(self):
        self.assertEqual(nt.match_quotes([EVENT, EVENT], [FIXTURE], NOW), [])
        self.assertEqual(nt.match_quotes([EVENT], [FIXTURE, FIXTURE], NOW), [])
        for change in ('league', 'kickoff', 'live', 'stop', 'price', 'outcome', 'market'):
            e = copy.deepcopy(EVENT)
            if change == 'league': e['tournament']['name'] = 'England - Championship'
            if change == 'kickoff': e['startTime'] = '2026-11-07T13:31:00+01:00'
            if change == 'live': e['mainMarket']['live'] = True
            if change == 'stop': e['mainMarket']['betStop'] = '2026-11-05T11:30:00+00:00'
            if change == 'price': e['mainMarket']['selections'][0]['selectionOdds'] = 'nan'
            if change == 'outcome': e['mainMarket']['selections'][0]['selectionValue'] = 'D'
            if change == 'market': e['mainMarket']['marketName'] = 'HUB 1st half'
            self.assertEqual(nt.match_quotes([e], [FIXTURE], NOW), [], change)
        self.assertEqual(nt.match_quotes([EVENT], [FIXTURE], NOW+timedelta(days=3)), [])

    def test_one_network_request_is_cached_and_rate_limit_respected(self):
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        with patch.object(nt, '_cached', {}), patch.object(nt, '_next_allowed', 0), \
             patch.object(nt.clock, 'time', return_value=1000), patch.object(nt, 'datetime') as date_class, \
             patch.object(nt, 'urlopen', return_value=Response(json.dumps({'eventList': [EVENT]}).encode())) as network:
            date_class.now.return_value = NOW
            a = nt.fetch_events(NOW.date(), NOW.date()+timedelta(days=3))
            b = nt.fetch_events(NOW.date(), NOW.date()+timedelta(days=3))
            self.assertEqual(a,b)
            network.assert_called_once()
        with patch.object(nt, '_cached', {}), patch.object(nt, '_next_allowed', 0), \
             patch.object(nt.clock, 'time', return_value=1000), patch.object(nt, 'datetime') as date_class, \
             patch.object(nt, 'urlopen', side_effect=HTTPError('url',429,'limited',{'Retry-After':'120'},None)) as network:
            date_class.now.return_value = NOW
            for _ in range(2):
                with self.assertRaises(nt.SourceError):
                    nt.fetch_events(NOW.date(), NOW.date()+timedelta(days=3))
            network.assert_called_once()
