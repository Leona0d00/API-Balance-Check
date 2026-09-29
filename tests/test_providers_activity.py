import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from script import activity, function, metadata, util


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(util, 'CONFIG_ROOT', self.root / '.config')
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def query(self, provider, payload, **extra):
        identifier = util.write_api(provider, 'main', 'test-key', **extra)
        with patch('script.function.requests.request', return_value=Mock(ok=True, status_code=200, json=Mock(return_value=payload))) as request:
            result = function.select_api(identifier)
            return result, request.call_args

    def test_balance_adapters_and_decimal_precision(self):
        for provider, payload, expected in [
            ('moonshot', {'data': {'available_balance': 12.5}}, '12.5'),
            ('siliconflow', {'data': {'totalBalance': '8.20'}}, '8.20'),
            ('openrouter', {'data': {'total_credits': 1.1, 'total_usage': 0.9}}, '0.2'),
        ]:
            with self.subTest(provider=provider):
                result, args = self.query(provider, payload, query_mode='account')
                self.assertEqual(result['balance'], expected)

    def test_openrouter_key_usage_is_not_account_balance(self):
        result, args = self.query('openrouter', {'data': {'usage': 5, 'limit_remaining': None, 'usage_weekly': 2}})
        self.assertEqual(result['kind'], 'key_usage')
        self.assertNotIn('balance', result)
        self.assertTrue(args.args[1].endswith('/key'))

    def test_provider_auth_headers(self):
        for provider, payload, header in [('anthropic', {'data': []}, 'x-api-key'), ('gemini', {'models': []}, 'x-goog-api-key')]:
            result, args = self.query(provider, payload)
            self.assertEqual(args.kwargs['headers'][header], 'test-key')
            self.assertNotIn('Authorization', args.kwargs['headers'])
            self.assertEqual(result['kind'], 'connection')

    def test_xiaomi_mimo_official_models_endpoint(self):
        result, args = self.query('xiaomi_mimo', {'object': 'list', 'data': [{'id': 'mimo-v2.6-pro'}]})
        self.assertEqual(args.args[1], 'https://api.xiaomimimo.com/v1/models')
        self.assertEqual(args.kwargs['headers']['Authorization'], 'Bearer test-key')
        self.assertEqual(result['kind'], 'connection')
        self.assertEqual(result['model_count'], 1)
        self.assertNotIn('balance', result)
        self.assertEqual(activity.ALIASES['mimo'], 'xiaomi_mimo')

    def test_custom_url_and_extra_round_trip(self):
        payload = {'custom': {'api_name': 'proxy', 'apikey': 'test-key', 'base_url': 'https://example.org/v1', 'note': '代理'}}
        identifier = function.add_api(payload)[0]
        self.assertEqual(util.find_api(identifier)['extra']['base_url'], 'https://example.org/v1')
        for url in ('http://example.org/v1', 'https://name:password@example.org', 'https://example.org?key=secret'):
            with self.assertRaises(util.AppError):
                util.validate_base_url(url)

    def test_note_persistence_does_not_rewrite_credentials(self):
        identifier = util.write_api('deepseek', 'main', 'test-key', other_field={'preserve': True})
        path = util.find_api(identifier)['path']
        before = path.read_bytes()
        metadata.set_note(identifier, '  主力开发  ')
        self.assertEqual(metadata.notes()[identifier], '主力开发')
        self.assertEqual(path.read_bytes(), before)

    def test_malformed_balance_and_redirect_rejected(self):
        identifier = util.write_api('moonshot', 'main', 'test-key')
        with patch('script.function.requests.request', return_value=Mock(ok=True, status_code=200, json=Mock(return_value={'data': {'available_balance': 'NaN'}}))):
            with self.assertRaises(util.AppError):
                function.select_api(identifier)
        with patch('script.function.requests.request', return_value=Mock(ok=True, status_code=302)):
            with self.assertRaises(util.AppError):
                function.select_api(identifier)

    def test_api_activity_uses_completed_responses_not_queries(self):
        db_path = self.root / 'opencode.db'
        now = datetime(2026, 9, 29, 12)
        timestamp = int((now-timedelta(hours=1)).timestamp()*1000)
        with sqlite3.connect(db_path) as db:
            db.execute('CREATE TABLE message (data TEXT)')
            data = {'role': 'assistant', 'providerID': 'opencode-go', 'modelID': 'model', 'time': {'completed': timestamp}, 'tokens': {'input': 10, 'output': 5, 'cache': {'read': 20}}, 'cost': 0.1}
            db.execute('INSERT INTO message VALUES (?)', (json.dumps(data),))
            data['error'] = {'message': 'failed'}
            db.execute('INSERT INTO message VALUES (?)', (json.dumps(data),))
            data['role'] = 'user'
            db.execute('INSERT INTO message VALUES (?)', (json.dumps(data),))
        before = db_path.read_bytes()
        result = activity.load_activity(db_path, now)
        self.assertEqual(result['status'], 'ready')
        item = result['providers']['opencode_go']
        self.assertEqual(item['calls'], 1)
        self.assertEqual(item['tokens'], 35)
        self.assertEqual(item['daily'][-1], 1)
        self.assertEqual(db_path.read_bytes(), before)
        self.assertEqual(activity.load_activity(self.root/'missing.db')['status'], 'missing')


if __name__ == '__main__':
    unittest.main()
