import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from script import function, util


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_root = Path(self.temp_dir.name) / ".config"
        self.old_root = util.CONFIG_ROOT
        util.CONFIG_ROOT = self.config_root

    def tearDown(self):
        util.CONFIG_ROOT = self.old_root
        self.temp_dir.cleanup()

    def test_fuzzy_search_ranks_exact_prefix_and_substring(self):
        values = ["deepseek/backup", "deepseek/main", "zhipu/main"]
        self.assertEqual(util.fuzzy_search("main", values), ["deepseek/main", "zhipu/main"])
        self.assertEqual(util.fuzzy_search("deep", values)[0], "deepseek/backup")

    def test_batch_add_and_delete(self):
        payload = {"deepseek": {"api_name": "main", "apikey": "secret"}}
        self.assertEqual(function.add_api(payload), ["deepseek/main"])
        self.assertEqual(function.show_all_api(), ["deepseek/main"])
        with self.assertRaises(util.AppError):
            function.add_api(payload)
        function.del_api("deepseek/main")
        self.assertEqual(function.show_all_api(), [])

    def test_api_key_whitespace_is_removed_before_storage(self):
        util.write_api("deepseek", "main", " se\ncret\t ")
        self.assertEqual(util.find_api("deepseek/main")["apikey"], "secret")

    @patch("script.function.requests.request")
    def test_deepseek_query(self, request):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            "is_available": True,
            "balance_infos": [{"currency": "USD", "total_balance": "1.20"}],
        }
        request.return_value = response
        util.write_api("deepseek", "main", "secret")
        result = function.select_api("deepseek/main")
        self.assertEqual(result["kind"], "balance")
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer secret")

    def test_parse_batch_list(self):
        records = util.parse_batch_payload(json.dumps([
            {"provider": "zhipu", "api_name": "main", "apikey": "secret"}
        ]))
        self.assertEqual(records[0]["provider"], "zhipu")


if __name__ == "__main__":
    unittest.main()
