"""Business logic for API management and provider queries."""

from __future__ import annotations

from typing import Any
from decimal import Decimal, InvalidOperation

import requests

from .util import AppError, fuzzy_search, find_api, list_apis, parse_batch_payload, write_api, delete_api
from .providers import PROVIDERS
from .codex_usage import read_codex_usage


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
            extra = {key: value for key, value in record.items() if key not in {'provider', 'api_name', 'apikey'}}
            added.append(write_api(record["provider"], record["api_name"], record["apikey"], **extra))
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
    if identifier == "codex_subscription/current":
        return read_codex_usage()
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
    if provider in {'minimax_plan_cn', 'minimax_plan_global'}:
        return _query_minimax_plan(record)
    if provider in PROVIDERS:
        return _query_provider(record)
    raise AppError(f"Unsupported provider: {provider}")


def _request(method: str, url: str, apikey: str, **kwargs: Any) -> requests.Response:
    headers = {"Authorization": f"Bearer {apikey}", "Accept": "application/json"}
    headers.update(kwargs.pop("headers", {}))
    headers = {key: value for key, value in headers.items() if value is not None}
    try:
        response = requests.request(method, url, headers=headers, timeout=TIMEOUT, allow_redirects=False, **kwargs)
    except requests.RequestException as exc:
        raise AppError(f"Network request failed: {str(exc).replace(apikey, '[redacted]')}") from exc
    if 300 <= response.status_code < 400:
        raise AppError('接口返回重定向，请检查 Base URL。')
    if not response.ok:
        detail = _error_detail(response).replace(apikey, '[redacted]')
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


def _query_minimax_plan(record: dict[str, Any]) -> dict[str, Any]:
    provider = record['provider']
    url = PROVIDERS[provider]['base'] + '/token_plan/remains'
    data = _json_response(_request('GET', url, record['apikey']))
    if not isinstance(data, dict):
        raise AppError('MiniMax 未返回套餐数据。')
    status = data.get('base_resp')
    if isinstance(status, dict) and status.get('status_code') != 0:
        raise AppError('MiniMax 套餐查询失败。')
    rows = data.get('model_remains')
    if not isinstance(rows, list):
        raise AppError('MiniMax 未返回套餐额度。')
    quotas = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if item.get('current_interval_total_count') == 0 and item.get('current_weekly_total_count') == 0 and item.get('current_interval_status') == 3:
            continue  # Not included in this plan; the API may misleadingly report 100% remaining.
        try:
            rolling = Decimal(str(item['current_interval_remaining_percent']))
            weekly = Decimal(str(item['current_weekly_remaining_percent']))
        except (KeyError, InvalidOperation, TypeError):
            continue
        if not all(value.is_finite() and 0 <= value <= 100 for value in (rolling, weekly)):
            continue
        quotas.append({'model': str(item.get('model_name') or '模型'), 'rolling': float(rolling), 'weekly': float(weekly)})
    if not quotas:
        raise AppError('MiniMax 未返回可用套餐额度。')
    return {'key': record['key'], 'provider': provider, 'kind': 'plan_quota', 'quotas': quotas}


def _query_provider(record: dict[str, Any]) -> dict[str, Any]:
    provider = record['provider']
    base = record.get('extra', {}).get('base_url') or PROVIDERS[provider]['base']
    if provider == 'custom':
        from .util import validate_base_url
        base = validate_base_url(base)
    path = '/models'
    headers = {}
    if provider in {'moonshot', 'moonshot_global'}:
        path = '/users/me/balance'
    elif provider == 'siliconflow':
        path = '/user/info'
    elif provider == 'openrouter':
        path = '/credits' if record.get('extra', {}).get('query_mode') == 'account' else '/key'
    elif provider == 'anthropic':
        headers = {'Authorization': None, 'x-api-key': record['apikey'], 'anthropic-version': '2023-06-01'}
    elif provider == 'gemini':
        headers = {'Authorization': None, 'x-goog-api-key': record['apikey']}
    from .util import validate_base_url
    base = validate_base_url(base)
    data = _json_response(_request('GET', base.rstrip('/') + path, record['apikey'], headers=headers))
    result = {'key': record['key'], 'provider': provider, 'data': data}
    if provider in {'moonshot', 'moonshot_global', 'siliconflow', 'openrouter'}:
        if not isinstance(data, dict) or not isinstance(data.get('data'), dict):
            raise AppError('接口未返回预期账户数据。')
        account = data['data']
        if provider == 'openrouter':
            if path == '/credits':
                try:
                    value = Decimal(str(account['total_credits'])) - Decimal(str(account['total_usage']))
                    if not value.is_finite():
                        raise ValueError()
                except (KeyError, InvalidOperation, ValueError):
                    raise AppError('OpenRouter 未返回有效账户余额。')
                result.update(kind='balance', balance=str(value), currency='USD')
                return result
            if 'usage' not in account:
                raise AppError('OpenRouter 未返回密钥用量。')
            result.update(kind='key_usage', message='密钥额度不是账户余额；账户余额需要管理密钥。')
        else:
            field = 'totalBalance' if provider == 'siliconflow' else 'available_balance'
            try:
                value = Decimal(str(account[field]))
                if not value.is_finite():
                    raise ValueError()
            except (KeyError, InvalidOperation, ValueError):
                raise AppError('接口未返回有效余额。')
            result.update(kind='balance', balance=str(value), currency='USD' if provider == 'moonshot_global' else 'CNY')
    else:
        models = data.get('models' if provider == 'gemini' else 'data') if isinstance(data, dict) else None
        if not isinstance(models, list):
            raise AppError('接口未返回模型列表。')
        result.update(kind='connection', model_count=len(models), message='模型列表可访问；此检查不提供余额或推理可用性保证。')
    return result
