"""Business logic for API management and provider queries."""

from __future__ import annotations

from typing import Any

import requests

from .util import AppError, fuzzy_search, find_api, list_apis, parse_batch_payload, write_api, delete_api


TIMEOUT = (5, 15)


def show_all_api() -> list[str]:
    return [item["key"] for item in list_apis()]


def search_api(query: str) -> list[str]:
    return fuzzy_search(query, show_all_api())


def add_api(payload: str | dict[str, Any]) -> list[str]:
    records = parse_batch_payload(payload) if isinstance(payload, str) else _records_from_mapping(payload)
    added: list[str] = []
    try:
        for record in records:
            added.append(write_api(record["provider"], record["api_name"], record["apikey"]))
    except Exception:
        # Batch additions are intentionally not rolled back: successful records remain usable.
        raise
    return added


def _records_from_mapping(payload: dict[str, Any]) -> list[dict[str, str]]:
    import json

    return parse_batch_payload(json.dumps(payload))


def del_api(identifier: str) -> None:
    delete_api(identifier)


def select_api(identifier: str) -> dict[str, Any]:
    record = find_api(identifier)
    if not record["apikey"].strip():
        raise AppError(f"API key is empty: {identifier}")
    provider = record["provider"]
    if provider == "opencode_go":
        return _query_opencode_go(record)
    if provider == "deepseek":
        return _query_deepseek(record)
    if provider == "zhipu":
        return _query_zhipu(record)
    raise AppError(f"Unsupported provider: {provider}")


def _request(method: str, url: str, apikey: str, **kwargs: Any) -> requests.Response:
    headers = {"Authorization": f"Bearer {apikey}", "Accept": "application/json"}
    headers.update(kwargs.pop("headers", {}))
    try:
        response = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise AppError(f"Network request failed: {exc}") from exc
    if not response.ok:
        detail = _error_detail(response)
        raise AppError(f"HTTP {response.status_code}: {detail}")
    return response


def _json_response(response: requests.Response) -> dict[str, Any] | list[Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise AppError("Provider returned invalid JSON") from exc
    if not isinstance(data, (dict, list)):
        raise AppError("Provider returned an unexpected JSON value")
    return data


def _error_detail(response: requests.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            error = data.get("error", data.get("message", data))
            return str(error)
    except ValueError:
        pass
    return response.text[:300] or response.reason


def _query_opencode_go(record: dict[str, Any]) -> dict[str, Any]:
    response = _request("GET", "https://opencode.ai/zen/go/v1/usage", record["apikey"])
    data = _json_response(response)
    if not isinstance(data, dict) or not isinstance(data.get("usage"), dict):
        raise AppError("OpenCode Go response does not contain usage data")
    usage = data["usage"]
    for window in ("rolling", "weekly", "monthly"):
        if not isinstance(usage.get(window), dict):
            raise AppError(f"OpenCode Go response is missing {window} usage")
    return {"key": record["key"], "provider": "opencode_go", "kind": "usage", "data": usage}


def _query_deepseek(record: dict[str, Any]) -> dict[str, Any]:
    response = _request("GET", "https://api.deepseek.com/user/balance", record["apikey"])
    data = _json_response(response)
    if not isinstance(data, dict) or not isinstance(data.get("balance_infos"), list):
        raise AppError("DeepSeek response does not contain balance_infos")
    return {"key": record["key"], "provider": "deepseek", "kind": "balance", "data": data}


def _query_zhipu(record: dict[str, Any]) -> dict[str, Any]:
    """Try the console balance endpoint, then fall back to official key validation."""
    internal_error = None
    try:
        response = _request(
            "GET",
            "https://www.bigmodel.cn/api/biz/account/query-customer-account-report",
            record["apikey"],
        )
        data = _json_response(response)
        account = data.get("data") if isinstance(data, dict) else None
        if isinstance(account, dict) and any(key in account for key in ("balance", "availableBalance")):
            return {"key": record["key"], "provider": "zhipu", "kind": "balance", "data": data}
        internal_error = "unrecognized internal response"
    except AppError as exc:
        internal_error = str(exc)

    try:
        response = _request("GET", "https://open.bigmodel.cn/api/paas/v4/models", record["apikey"])
        data = _json_response(response)
        return {
            "key": record["key"],
            "provider": "zhipu",
            "kind": "key_status",
            "data": data,
            "message": "API key is valid. Zhipu does not document a public balance endpoint.",
            "internal_error": internal_error,
        }
    except AppError as exc:
        raise AppError(f"Zhipu key validation failed: {exc}") from exc
