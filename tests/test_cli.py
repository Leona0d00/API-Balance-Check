import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from script import cli, util


PROJECT = Path(__file__).resolve().parent.parent


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / ".config"
        self.root_patch = patch.object(util, "CONFIG_ROOT", self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(list(args))
        self.assertEqual(stderr.getvalue(), "")
        return code, stdout.getvalue()

    def query(self, provider, payload, **extra):
        identifier = util.write_api(provider, "main", "sk-test-credential", **extra)
        response = Mock(ok=True, status_code=200, json=Mock(return_value=payload))
        with patch("script.function.requests.request", return_value=response) as request:
            code, output = self.invoke("--account", identifier)
        self.assertEqual(code, 0, output)
        report = json.loads(output)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["summary"], {"total": 1, "succeeded": 1, "failed": 0})
        self.assertTrue(report["queried_at"].endswith("Z"))
        self.assertNotIn("sk-test-credential", output)
        return report["accounts"][0], request

    def test_balance_currency_precision_and_no_raw_response(self):
        row, request = self.query("deepseek", {
            "is_available": False,
            "balance_infos": [
                {"currency": "CNY", "total_balance": "12.500", "topped_up_balance": "10.00", "granted_balance": "2.500"},
                {"currency": "USD", "total_balance": "0.010"},
            ],
            "unexpected_secret": "sk-test-credential",
        })
        self.assertEqual(row["balances"], [
            {"currency": "CNY", "total": "12.500", "topped_up_balance": "10.00", "granted_balance": "2.500"},
            {"currency": "USD", "total": "0.010"},
        ])
        self.assertFalse(row["is_available"])
        self.assertTrue(row["balance_supported"])
        self.assertNotIn("data", row)
        self.assertNotIn("unexpected_secret", row)
        self.assertEqual(request.call_args.kwargs["timeout"], (5, 15))
        for provider, payload, expected, currency in [
            ("moonshot", {"data": {"available_balance": "6.250"}}, "6.250", "CNY"),
            ("moonshot_global", {"data": {"available_balance": "8.123456789"}}, "8.123456789", "USD"),
            ("siliconflow", {"data": {"totalBalance": "9.00"}}, "9.00", "CNY"),
            ("openrouter", {"data": {"total_credits": "1.10", "total_usage": "0.90"}}, "0.20", "USD"),
            ("zhipu", {"data": {"availableBalance": "4.00"}}, "4.00", None),
        ]:
            with self.subTest(provider=provider):
                row, _ = self.query(provider, payload, query_mode="account")
                self.assertEqual(row["balances"], [{"currency": currency, "total": expected}])

    def test_go_usage_and_minimax_remaining_have_explicit_semantics(self):
        row, _ = self.query("opencode_go", {"usage": {
            "rolling": {"percent": 25.1, "resetsAt": "2026-10-03T12:00:00Z"},
            "weekly": {"percent": 0}, "monthly": {"percent": 100},
        }})
        self.assertEqual(row["windows"]["rolling"], {
            "used_percent": 25.1, "remaining_percent": 74.9, "resets_at": "2026-10-03T12:00:00Z",
        })
        self.assertEqual(row["windows"]["monthly"]["remaining_percent"], 0)
        self.assertFalse(row["balance_supported"])
        for provider in ("minimax_plan_cn", "minimax_plan_global"):
            row, _ = self.query(provider, {"base_resp": {"status_code": 0}, "model_remains": [
                {"model_name": "general", "current_interval_remaining_percent": 64,
                 "current_weekly_remaining_percent": 91},
            ]})
            self.assertEqual(row["quotas"], [{"model": "general", "rolling_remaining_percent": 64.0, "weekly_remaining_percent": 91.0}])
            self.assertNotIn("balances", row)

    def test_openrouter_key_usage_and_connection_are_not_balances(self):
        row, _ = self.query("openrouter", {"data": {
            "limit": None, "limit_remaining": None, "usage": "4.20", "usage_weekly": "1.30",
            "label": "sk-test-credential",
        }})
        self.assertEqual(row["key_usage"], {
            "currency": "USD", "limit": None, "limit_remaining": None, "usage": "4.20", "usage_weekly": "1.30",
        })
        self.assertFalse(row["balance_supported"])
        self.assertNotIn("balances", row)
        row, _ = self.query("openai", {"data": [{"id": "model-a"}, {"id": "model-b"}]})
        self.assertEqual(row["model_count"], 2)
        self.assertEqual(row["kind"], "connection")
        self.assertFalse(row["balance_supported"])
        identifier = util.write_api("zhipu", "fallback", "sk-test-credential")
        responses = [Mock(ok=False, status_code=403, json=Mock(return_value={"message": "Forbidden"})),
                     Mock(ok=True, status_code=200, json=Mock(return_value={"data": []}))]
        with patch("script.function.requests.request", side_effect=responses):
            code, output = self.invoke("--account", identifier)
        row = json.loads(output)["accounts"][0]
        self.assertEqual(code, 0)
        self.assertEqual(row["kind"], "key_status")
        self.assertFalse(row["balance_supported"])
        self.assertNotIn("internal_error", row)

    def test_partial_failure_redaction_stable_order_and_one_config_scan(self):
        util.write_api("deepseek", "a", "sk-first-credential")
        util.write_api("moonshot", "b", "sk-second-credential")

        def query(record):
            if record["provider"] == "moonshot":
                raise util.AppError("HTTP 401: sk-first-credential sk-second-credential")
            return {"provider": "deepseek", "kind": "balance", "data": {
                "balance_infos": [{"currency": "CNY", "total_balance": "1.25"}],
            }}

        with patch("script.function.query_api_record", side_effect=query), patch("script.util.list_apis", wraps=util.list_apis) as scan:
            code, output = self.invoke()
        self.assertEqual(code, 1)
        scan.assert_called_once()
        report = json.loads(output)
        self.assertEqual(report["summary"], {"total": 2, "succeeded": 1, "failed": 1})
        self.assertEqual([item["account"] for item in report["accounts"]], ["deepseek/a", "moonshot/b"])
        self.assertEqual(report["accounts"][1]["error"]["message"], "HTTP 401: [redacted] [redacted]")
        self.assertNotIn("sk-first-credential", output)
        self.assertNotIn("sk-second-credential", output)

    def test_filters_are_exact_and_combine_as_intersection(self):
        util.write_api("deepseek", "main", "sk-test-credential")
        util.write_api("moonshot", "main", "sk-test-credential")
        result = {"provider": "deepseek", "kind": "balance", "data": {"balance_infos": [{"currency": "CNY", "total_balance": "2"}]}}
        with patch("script.function.query_api_record", return_value=result) as query:
            code, output = self.invoke("--provider", "deepseek", "--account", "deepseek/main", "--account", "moonshot/main")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["summary"]["total"], 1)
            query.assert_called_once()
        with patch("script.function.query_api_record") as query:
            for args, expected in [
                (("--account", "deepseek/missing"), "account_not_found"),
                (("--provider", "moonshot", "--account", "deepseek/main"), "no_accounts"),
                (("--provider", "unknown"), "invalid_arguments"),
                (("--workers", "0"), "invalid_arguments"),
                (("--workers", "33"), "invalid_arguments"),
                (("--workers", "abc"), "invalid_arguments"),
            ]:
                with self.subTest(args=args):
                    code, output = self.invoke(*args)
                    self.assertEqual(code, 2)
                    self.assertEqual(json.loads(output)["error"]["code"], expected)
            query.assert_not_called()

    def test_short_misconfigured_keys_do_not_corrupt_schema_or_amounts(self):
        util.write_api("deepseek", "main", "1")
        util.write_api("openai", "main", "ok")

        def query(record):
            if record["provider"] == "deepseek":
                return {"provider": "deepseek", "kind": "balance", "data": {
                    "balance_infos": [{"currency": "CNY", "total_balance": "12.10"}],
                }}
            return {"provider": "openai", "kind": "connection", "model_count": 1}

        with patch("script.function.query_api_record", side_effect=query):
            code, output = self.invoke()
        report = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual([row["status"] for row in report["accounts"]], ["ok", "ok"])
        self.assertEqual(report["accounts"][0]["balances"][0]["total"], "12.10")
        self.assertTrue(report["queried_at"].endswith("Z"))

    def test_empty_and_invalid_configuration_have_structured_errors(self):
        code, output = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["error"]["code"], "no_accounts")
        util.write_api("deepseek", "main", "sk-test-credential")
        path = self.root / "deepseek" / "main" / "main.json"
        path.write_text('{"apikey": "sk-test-credential", broken}', encoding="utf-8")
        with patch("script.function.requests.request") as request:
            code, output = self.invoke()
            request.assert_not_called()
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["error"]["code"], "configuration_error")
        self.assertNotIn("sk-test-credential", output)
        path.write_bytes(b"\xff\xfe")
        code, output = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["error"]["code"], "configuration_error")

    def test_parallel_queries_are_actually_concurrent(self):
        for name in ("a", "b"):
            util.write_api("openai", name, "sk-test-credential")
        barrier = threading.Barrier(2)

        def query(record):
            barrier.wait(timeout=5)
            return {"provider": "openai", "kind": "connection", "model_count": 1}

        with patch("script.function.query_api_record", side_effect=query):
            code, output = self.invoke("--workers", "2")
        self.assertEqual(code, 0, output)
        self.assertEqual(json.loads(output)["summary"]["succeeded"], 2)

    def test_malformed_numeric_and_missing_fields_are_per_account_errors(self):
        identifier = util.write_api("deepseek", "main", "sk-test-credential")
        for payload in (
            {"balance_infos": [{"currency": "CNY", "total_balance": "NaN"}]},
            {"balance_infos": [{"currency": "CNY", "total_balance": "Infinity"}]},
            {"balance_infos": [{"currency": "CNY"}]},
            {"balance_infos": []},
        ):
            with self.subTest(payload=payload):
                with patch("script.function.requests.request", return_value=Mock(ok=True, status_code=200, json=Mock(return_value=payload))):
                    code, output = self.invoke("--account", identifier)
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(output)["accounts"][0]["status"], "error")
                self.assertNotIn('"total": "NaN"', output)

    def test_table_has_quota_semantics_and_sanitizes_terminal_controls(self):
        util.write_api("openai", "main", "sk-test-credential")
        with patch("script.function.query_api_record", side_effect=util.AppError("failed\n\x1b[31m sk-test-credential")):
            code, output = self.invoke("--format", "table")
        self.assertEqual(code, 1)
        self.assertIn("openai/main", output)
        self.assertIn("失败 1", output)
        self.assertIn("[redacted]", output)
        self.assertNotIn("\x1b", output)
        self.assertNotIn("sk-test-credential", output)
        with patch("script.function.query_api_record", return_value={"provider": "openai", "kind": "connection", "model_count": 2}):
            code, output = self.invoke("--format", "table")
        self.assertEqual(code, 0)
        self.assertIn("余额不可查询", output)

    def test_entrypoint_queries_fixture_from_unrelated_directory(self):
        util.write_api("deepseek", "main", "sk-test-credential")
        # Patch only the request in a separate process; exercise actual path resolution and JSON output.
        program = (
            "import runpy, sys; from pathlib import Path; from unittest.mock import Mock, patch; "
            f"sys.path.insert(0, {str(PROJECT)!r}); from script import util; util.CONFIG_ROOT = Path({str(self.root)!r}); "
            f"sys.argv = [{str(PROJECT / 'balance.py')!r}]; "
            "response = Mock(ok=True, status_code=200, json=Mock(return_value={'balance_infos': [{'currency': 'CNY', 'total_balance': '3.50'}]})); "
            "request = patch('script.function.requests.request', return_value=response); request.start(); "
            f"runpy.run_path({str(PROJECT / 'balance.py')!r}, run_name='__main__')"
        )
        process = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", program], cwd=self.temp.name,
                                 capture_output=True, encoding="utf-8", timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        row = json.loads(process.stdout)["accounts"][0]
        self.assertEqual(row["balances"], [{"currency": "CNY", "total": "3.50"}])
        self.assertNotIn("PySide6", process.stdout)

    @unittest.skipUnless(os.name == "nt", "Windows launcher")
    def test_windows_launcher_forwards_arguments_and_exit_code_from_any_directory(self):
        env = dict(os.environ, BALANCE_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1")
        process = subprocess.run(["cmd.exe", "/d", "/c", str(PROJECT / "balance.cmd"), "--workers", "0"],
                                 cwd=self.temp.name, env=env, capture_output=True, encoding="utf-8", timeout=20)
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(json.loads(process.stdout)["error"]["code"], "invalid_arguments")


if __name__ == "__main__":
    unittest.main()
