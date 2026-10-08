"""Headless, read-only account queries with a versioned JSON contract."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import sys
from typing import Any, Sequence
import unicodedata

from . import function, util
from .providers import PROVIDERS, provider_label


class CliError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliError("invalid_arguments", message)


def _workers(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("workers must be an integer from 1 to 32") from exc
    if not 1 <= count <= 32:
        raise argparse.ArgumentTypeError("workers must be an integer from 1 to 32")
    return count


def _parser() -> Parser:
    parser = Parser(prog="api-balance", description="Query configured API accounts without opening the desktop UI.")
    parser.add_argument("--format", choices=("json", "table"), default="json", help="output format (default: json)")
    parser.add_argument("--provider", action="append", choices=sorted(PROVIDERS), help="provider ID; repeat to select multiple providers")
    parser.add_argument("--account", action="append", help="exact provider/api_name; repeat to select multiple accounts")
    parser.add_argument("--workers", type=_workers, default=4, help="concurrent accounts, 1-32 (default: 4)")
    return parser


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _amount(value: Any) -> str:
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError()
    except (InvalidOperation, ValueError) as exc:
        raise util.AppError("Provider returned an invalid numeric value") from exc
    return format(number, "f")


def _percent(value: Any) -> float:
    number = float(_amount(value))
    if not 0 <= number <= 100:
        raise util.AppError("Provider returned a percentage outside 0-100")
    return number


def _normalize(result: dict[str, Any]) -> dict[str, Any]:
    """Expose selected, validated fields instead of full provider responses."""
    kind = result["kind"]
    output: dict[str, Any] = {"kind": kind, "balance_supported": kind == "balance"}
    data = result.get("data", {})
    if kind == "balance":
        if result["provider"] == "deepseek":
            balances = []
            for info in data["balance_infos"]:
                currency = info.get("currency")
                if not isinstance(currency, str) or not currency:
                    raise util.AppError("Provider returned a balance without a currency")
                balance = {"currency": currency, "total": _amount(info["total_balance"])}
                for field in ("topped_up_balance", "granted_balance"):
                    if info.get(field) is not None:
                        balance[field] = _amount(info[field])
                balances.append(balance)
            if not balances:
                raise util.AppError("Provider returned no balances")
            output["balances"] = balances
            if isinstance(data.get("is_available"), bool):
                output["is_available"] = data["is_available"]
        elif "balance" in result:
            output["balances"] = [{"currency": result.get("currency"), "total": _amount(result["balance"])}]
        else:  # Zhipu's console response does not specify a documented currency.
            account = data["data"]
            output["balances"] = [{"currency": None, "total": _amount(account.get("availableBalance", account.get("balance")))}]
    elif kind == "usage":
        windows = {}
        for name in ("rolling", "weekly", "monthly"):
            item = data[name]
            used = _percent(item["percent"])
            reset = item.get("resetsAt")
            windows[name] = {"used_percent": used, "remaining_percent": float(Decimal("100") - Decimal(str(used))),
                             "resets_at": str(reset) if reset is not None else None}
        output["windows"] = windows
    elif kind == "plan_quota":
        quotas = [{"model": str(item["model"]), "rolling_remaining_percent": _percent(item["rolling"]),
                   "weekly_remaining_percent": _percent(item["weekly"])} for item in result["quotas"]]
        if not quotas:
            raise util.AppError("Provider returned no plan quotas")
        output["quotas"] = quotas
    elif kind == "key_usage":
        account = data["data"]
        usage: dict[str, Any] = {"currency": "USD"}
        for field in ("limit", "limit_remaining", "usage", "usage_daily", "usage_weekly", "usage_monthly"):
            if field in account:
                usage[field] = _amount(account[field]) if account[field] is not None else None
        output["key_usage"] = usage
    elif kind == "connection":
        output["model_count"] = int(result["model_count"])
    elif kind != "key_status":
        raise util.AppError("Provider returned an unsupported result kind")
    if result.get("message"):
        output["message"] = str(result["message"])
    return output


def _query(record: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {"account": record["key"], "provider": record["provider"],
                              "provider_name": provider_label(record["provider"])}
    try:
        normalized = _normalize(function.query_api_record(record))
        output.update(normalized, status="ok")
    except util.AppError as exc:
        output.update(status="error", kind=None, balance_supported=None,
                      error={"code": "query_failed", "message": str(exc)})
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        output.update(status="error", kind=None, balance_supported=None,
                      error={"code": "invalid_response", "message": "Provider returned an unexpected response structure"})
    except Exception:
        output.update(status="error", kind=None, balance_supported=None,
                      error={"code": "internal_error", "message": "Unexpected error while querying this account"})
    output["queried_at"] = _now()
    return output


def _select(records: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.account:
        unknown = set(args.account) - {record["key"] for record in records}
        if unknown:
            raise CliError("account_not_found", "Unknown account(s): " + ", ".join(sorted(unknown)))
    selected = [record for record in records
                if (not args.provider or record["provider"] in args.provider)
                and (not args.account or record["key"] in args.account)]
    if not selected:
        raise CliError("no_accounts", "No configured accounts match the selection. Add accounts in the desktop app first.")
    return selected


def _redact(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        # Redact free text, not enum values, timestamps or numeric strings: a short
        # misconfigured key such as "1" must not corrupt balances or the schema.
        text_fields = {"account", "provider_name", "currency", "model", "message", "resets_at"}
        return {key: _redact(item, secrets) if isinstance(item, (dict, list)) or key in text_fields else item
                for key, item in value.items()}
    return value


def _report(started: str, accounts: list[dict[str, Any]], error: dict[str, str] | None = None) -> dict[str, Any]:
    failed = sum(item["status"] == "error" for item in accounts)
    report: dict[str, Any] = {"schema_version": 1, "queried_at": started, "finished_at": _now(),
                              "summary": {"total": len(accounts), "succeeded": len(accounts) - failed, "failed": failed},
                              "accounts": accounts}
    if error is not None:
        report["error"] = error
    return report


def _cell(value: Any) -> str:
    # Keep account names and upstream errors on a single line, without terminal controls.
    return "".join(" " if unicodedata.category(char).startswith("C") else char for char in str(value))


def _width(value: str) -> int:
    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in value)


def _detail(item: dict[str, Any]) -> str:
    if item["status"] == "error":
        return item["error"]["message"]
    kind = item["kind"]
    if kind == "balance":
        detail = "; ".join(f"{balance['currency'] or '币种未知'} {balance['total']}" for balance in item["balances"])
        return detail + ("（账户不可用）" if item.get("is_available") is False else "")
    if kind == "usage":
        return "; ".join(f"{name} 剩余 {window['remaining_percent']:g}%" for name, window in item["windows"].items())
    if kind == "plan_quota":
        return "; ".join(f"{quota['model']}: 5h 剩余 {quota['rolling_remaining_percent']:g}%, 周剩余 {quota['weekly_remaining_percent']:g}%" for quota in item["quotas"])
    if kind == "key_usage":
        usage = item["key_usage"]
        remaining = usage.get("limit_remaining")
        if remaining is not None:
            detail = f"密钥剩余额度 USD {remaining}"
        elif "limit" in usage and usage["limit"] is None:
            detail = "密钥未设限"
        else:
            detail = "密钥剩余额度未知"
        return f"{detail}; 累计用量 USD {usage.get('usage', '未知')}（非账户余额）"
    if kind == "connection":
        return f"模型列表可访问（{item['model_count']} 个）；余额不可查询"
    return "密钥验证通过；余额不可查询"


def _table(report: dict[str, Any]) -> str:
    rows = [["账户", "供应商", "状态", "类型", "结果"]]
    rows.extend([item["account"], item["provider_name"], item["status"], item["kind"] or "—", _detail(item)] for item in report["accounts"])
    rows = [[_cell(cell) for cell in row] for row in rows]
    widths = [max(_width(row[index]) for row in rows) for index in range(5)]
    lines = [" | ".join(cell + " " * (widths[index] - _width(cell)) for index, cell in enumerate(row)).rstrip() for row in rows]
    lines.insert(1, "-+-".join("-" * width for width in widths))
    summary = report["summary"]
    lines.append(f"\n查询时间 {report['queried_at']} | 共 {summary['total']} 个，成功 {summary['succeeded']}，失败 {summary['failed']}")
    if "error" in report:
        lines.append(_cell(f"{report['error']['code']}: {report['error']['message']}"))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    # JSON and Chinese tables must remain UTF-8 when piped to another process.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    started = _now()
    output_format = "json"
    secrets: list[str] = []
    try:
        args = _parser().parse_args(argv)
        output_format = args.format
        records = util.list_apis()
        secrets = sorted({record["apikey"] for record in records if record["apikey"]}, key=len, reverse=True)
        selected = _select(records, args)
        with ThreadPoolExecutor(max_workers=min(args.workers, len(selected))) as pool:
            accounts = list(pool.map(_query, selected))
        report = _report(started, accounts)
        exit_code = 1 if report["summary"]["failed"] else 0
    except CliError as exc:
        report = _report(started, [], {"code": exc.code, "message": str(exc)})
        exit_code = 2
    except (util.AppError, OSError, UnicodeError) as exc:
        report = _report(started, [], {"code": "configuration_error", "message": str(exc)})
        exit_code = 2
    except KeyboardInterrupt:
        report = _report(started, [], {"code": "interrupted", "message": "Query interrupted"})
        exit_code = 130
    report = _redact(report, secrets)
    print(_table(report) if output_format == "table" else json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
