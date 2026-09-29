"""Shared configuration, search, and HTTP helpers."""

from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit
from .providers import PROVIDERS


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_ROOT = PROJECT_ROOT / ".config"
SUPPORTED_PROVIDERS = set(PROVIDERS)


class AppError(Exception):
    """An expected, user-facing application error."""


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def remove_whitespace(value: str) -> str:
    """Remove whitespace introduced when secrets are copied from other apps."""
    return re.sub(r"\s+", "", str(value))


def fuzzy_search(query: str, candidates: Iterable[str]) -> list[str]:
    """Return stable fuzzy matches, ranked from strongest to weakest."""
    query_key = normalize_text(query)
    values = sorted(set(str(item) for item in candidates), key=normalize_text)
    if not query_key:
        return values

    ranked: list[tuple[int, float, str]] = []
    for value in values:
        candidate = normalize_text(value)
        if candidate == query_key:
            ranked.append((0, 1.0, value))
        elif candidate.startswith(query_key):
            ranked.append((1, 1.0, value))
        elif query_key in candidate:
            # All direct substring matches have equal priority; keep their order deterministic.
            ranked.append((2, 1.0, value))
        else:
            score = SequenceMatcher(None, query_key, candidate).ratio()
            if score >= 0.35:
                ranked.append((3, score, value))
    ranked.sort(key=lambda item: (item[0], -item[1], normalize_text(item[2])))
    return [item[2] for item in ranked]


def api_key(provider: str, api_name: str) -> str:
    return f"{provider}/{api_name}"


def mask_secret(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _validate_name(value: str, label: str) -> str:
    value = str(value).strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise AppError(f"Invalid {label}: {value!r}")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise AppError(f"Configuration file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AppError(f"Invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise AppError(f"Configuration must be a JSON object: {path}")
    return data


def list_apis() -> list[dict[str, Any]]:
    """Scan .config and return valid API records sorted by unique key."""
    records: list[dict[str, Any]] = []
    if not CONFIG_ROOT.exists():
        return records
    for provider_dir in CONFIG_ROOT.iterdir():
        if not provider_dir.is_dir():
            continue
        provider = provider_dir.name
        for api_dir in provider_dir.iterdir():
            if not api_dir.is_dir():
                continue
            api_name = api_dir.name
            config_path = api_dir / f"{api_name}.json"
            if not config_path.is_file():
                continue
            data = _read_json(config_path)
            apikey = data.get("apikey")
            if not isinstance(apikey, str):
                raise AppError(f"Missing string 'apikey' in {config_path}")
            records.append(
                {
                    "provider": provider,
                    "api_name": api_name,
                    "key": api_key(provider, api_name),
                    "apikey": apikey,
                    "path": config_path,
                    "extra": {key: value for key, value in data.items() if key != "apikey"},
                }
            )
    return sorted(records, key=lambda item: normalize_text(item["key"]))


def find_api(identifier: str) -> dict[str, Any]:
    matches = [item for item in list_apis() if item["key"] == identifier]
    if not matches:
        raise AppError(f"API not found: {identifier}")
    return matches[0]


def write_api(provider: str, api_name: str, apikey: str, **extra: Any) -> str:
    provider = _validate_name(provider, "provider")
    api_name = _validate_name(api_name, "api name")
    apikey = remove_whitespace(apikey) if isinstance(apikey, str) else apikey
    if provider not in SUPPORTED_PROVIDERS:
        raise AppError(f"Unsupported provider: {provider}")
    if not isinstance(apikey, str) or not apikey.strip():
        raise AppError(f"API key is empty: {provider}/{api_name}")
    if provider == 'custom':
        extra['base_url'] = validate_base_url(extra.get('base_url', ''))
    elif extra.get('base_url'):
        extra['base_url'] = validate_base_url(extra['base_url'])
    target_dir = CONFIG_ROOT / provider / api_name
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{api_name}.json"
    if target_path.exists():
        raise AppError(f"API already exists: {provider}/{api_name}")
    payload = {"apikey": apikey.strip(), **extra}
    temporary_path = target_path.with_suffix(".json.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary_path, target_path)
    return api_key(provider, api_name)


def delete_api(identifier: str) -> None:
    import shutil

    record = find_api(identifier)
    shutil.rmtree(record["path"].parent)
    provider_dir = record["path"].parent.parent
    if provider_dir.exists() and not any(provider_dir.iterdir()):
        provider_dir.rmdir()


def parse_batch_payload(payload: str) -> list[dict[str, str]]:
    """Parse {provider: {api_name: ..., apikey: ...}} or a list of records."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AppError(f"Invalid batch JSON: {exc.msg}") from exc
    records: list[dict[str, str]] = []
    if isinstance(data, list):
        source = data
    elif isinstance(data, dict):
        source = []
        for provider, value in data.items():
            if isinstance(value, dict):
                source.append({"provider": provider, **value})
            elif isinstance(value, list):
                source.extend({"provider": provider, **item} for item in value if isinstance(item, dict))
    else:
        raise AppError("Batch JSON must be an object or array")
    for item in source:
        provider = item.get("provider")
        api_name = item.get("api_name")
        apikey = item.get("apikey")
        if not all(isinstance(value, str) for value in (provider, api_name, apikey)):
            raise AppError("Each API record needs provider, api_name, and apikey strings")
        records.append({"provider": provider, "api_name": api_name, "apikey": apikey, **{key: item[key] for key in ('base_url', 'note', 'query_mode') if key in item}})
    if not records:
        raise AppError("No API records found")
    return records


def validate_base_url(value: str) -> str:
    value = str(value).strip().rstrip('/')
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AppError('Base URL 必须是 HTTPS 地址，不能包含凭据、查询参数或片段。')
    return value
