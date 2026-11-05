import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from api.main import app
import norsk_tipping as nt
import pl_rounds as tracker
from test_pl_rounds import NOW, fixture, bundle


async def request(data):
    messages = []
    sent = False
    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {'type': 'http.request', 'body': json.dumps(data).encode(), 'more_body': False}
        return {'type': 'http.disconnect'}
    async def send(message):
        messages.append(message)
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST',
             'scheme': 'http', 'path': '/api/pl-rounds/predict-round', 'raw_path': b'/api/pl-rounds/predict-round',
             'query_string': b'', 'root_path': '', 'headers': [(b'content-type', b'application/json')],
             'client': ('test', 1), 'server': ('test', 80)}
    await app(scope, receive, send)
    return messages[0]['status'], json.loads(messages[-1]['body'])


class RoundEndpointTest(unittest.TestCase):
    def test_success_and_validation_with_isolated_history(self):
        quote = {'fixture_id': '2026:1', 'home': 'A', 'away': 'B', 'event_id': 'ev', 'market_id': 'market',
                 'bet_stop': fixture()['kickoff'], 'odds': {'home': 1.5, 'draw': 2, 'away': 5}}
        with tempfile.TemporaryDirectory() as d, patch.object(tracker, 'DIRECTORY', Path(d)), \
             patch.object(tracker, 'utcnow', return_value=NOW), \
             patch.object(tracker, 'current_season', return_value=2026), \
             patch.object(tracker, 'fetch_schedule', return_value=[fixture()]), \
             patch.object(tracker, 'refresh_current', return_value=bundle()), \
             patch.object(tracker, 'archive_model', return_value='model'), \
             patch.object(nt, 'fetch_events', return_value=([], NOW.timestamp())), \
             patch.object(nt, 'match_quotes', return_value=[quote]):
            status, data = asyncio.run(request({'season': 2026, 'round': 9}))
            self.assertEqual(status, 200)
            self.assertEqual(data['created'], 1)
            self.assertEqual(data['report']['records'][0]['simulation']['pick'], 'away')
            status, _ = asyncio.run(request({'season': 2026, 'round': 39}))
            self.assertEqual(status, 422)
