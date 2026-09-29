"""Read the active Codex subscription allowance through the local app-server."""

from __future__ import annotations

import json
import math
import os
import queue
import shutil
import subprocess
import threading
import time
from typing import Any

from .util import AppError


TIMEOUT_SECONDS = 10


def _window_label(minutes: int | float | None) -> str:
    if minutes == 300:
        return "5 小时"
    if minutes == 10080:
        return "本周"
    if isinstance(minutes, (int, float)) and minutes > 0:
        return f"{minutes / 60:g} 小时"
    return "额度窗口"


def normalize_rate_limits(payload: dict[str, Any]) -> dict[str, Any]:
    limits = payload.get("rateLimitsByLimitId") or {"codex": payload.get("rateLimits")}
    if not isinstance(limits, dict) or not isinstance(limits.get("codex"), dict):
        raise AppError("Codex 未返回订阅额度。")

    codex = limits["codex"]
    windows = []
    for field in ("primary", "secondary"):
        item = codex.get(field)
        if not isinstance(item, dict):
            continue
        used = item.get("usedPercent")
        if not isinstance(used, (int, float)) or not math.isfinite(used):
            continue
        used = min(100.0, max(0.0, float(used)))
        windows.append({
            "label": _window_label(item.get("windowDurationMins")),
            "used": used,
            "remaining": 100.0 - used,
            "resets_at": item.get("resetsAt"),
        })
    if not windows:
        raise AppError("Codex 未返回可用额度窗口。")

    reserve = limits.get("base_model_inference")
    reserve_windows = []
    if isinstance(reserve, dict):
        for field in ("primary", "secondary"):
            item = reserve.get(field)
            if not isinstance(item, dict) or not isinstance(item.get("usedPercent"), (int, float)):
                continue
            used = min(100.0, max(0.0, float(item["usedPercent"])))
            reserve_windows.append({
                "label": _window_label(item.get("windowDurationMins")),
                "used": used,
                "remaining": 100.0 - used,
                "resets_at": item.get("resetsAt"),
            })

    credits = codex.get("credits") if isinstance(codex.get("credits"), dict) else {}
    return {
        "kind": "subscription_quota",
        "provider": "codex_subscription",
        "key": "codex_subscription/current",
        "plan": str(codex.get("planType") or "ChatGPT").title(),
        "windows": windows,
        "reserve_model": reserve.get("normalModelSlug") if isinstance(reserve, dict) else None,
        "reserve_windows": reserve_windows,
        "credits": {
            "has_credits": bool(credits.get("hasCredits")),
            "unlimited": bool(credits.get("unlimited")),
            "balance": str(credits.get("balance", "0")),
        },
    }


def read_codex_usage() -> dict[str, Any]:
    executable = shutil.which("codex")
    if not executable:
        raise AppError("未找到 Codex CLI，无法读取当前订阅额度。")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            [executable, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise AppError("无法启动 Codex app-server。") from exc

    messages: queue.Queue[dict[str, Any]] = queue.Queue()

    def pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                messages.put(message)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.monotonic() + TIMEOUT_SECONDS

    def send(message: dict[str, Any]) -> None:
        if process.stdin is None:
            raise AppError("Codex app-server 输入不可用。")
        process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()

    def receive(request_id: int) -> dict[str, Any]:
        while time.monotonic() < deadline:
            try:
                message = messages.get(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty:
                break
            if message.get("id") == request_id:
                if message.get("error"):
                    raise AppError("Codex app-server 拒绝额度查询。")
                result = message.get("result")
                if not isinstance(result, dict):
                    raise AppError("Codex app-server 返回格式异常。")
                return result
        raise AppError("Codex 订阅额度查询超时。")

    try:
        send({
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "api-balance-check", "version": "1.0.0"},
                "capabilities": {"experimentalApi": True},
            },
        })
        receive(1)
        send({"method": "initialized"})
        send({
            "id": 2,
            "method": "account/rateLimits/read",
            "params": {"excludeResetCreditDetails": True, "supportsLunaReserve": True},
        })
        return normalize_rate_limits(receive(2))
    except (BrokenPipeError, OSError) as exc:
        raise AppError("Codex app-server 通信失败。") from exc
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
