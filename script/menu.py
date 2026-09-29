"""PySide6 desktop UI for API balance and usage monitoring."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QTextBrowser, QTextEdit,
    QToolButton, QVBoxLayout, QWidget, QWizard, QWizardPage,
)

from .function import add_api, del_api, search_api, select_api, show_all_api
from .util import AppError


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def provider_label(provider: str) -> str:
    return {"opencode_go": "OpenCode Go", "deepseek": "DeepSeek", "zhipu": "智谱 API"}.get(provider, provider)


def result_state(result: dict[str, Any]) -> str:
    if result.get("kind") == "usage":
        values = [result["data"][key].get("percent", 0) for key in ("rolling", "weekly", "monthly")]
        return "error" if max(values) >= 90 else "warning" if max(values) >= 70 else "success"
    if result.get("kind") in {"balance", "key_status"}:
        return "success"
    return "error"


class QueryWorker(QObject):
    finished = Signal(str, dict)
    failed = Signal(str, str)

    def __init__(self, identifier: str) -> None:
        super().__init__()
        self.identifier = identifier

    def run(self) -> None:
        try:
            self.finished.emit(self.identifier, select_api(self.identifier))
        except (AppError, OSError) as exc:
            self.failed.emit(self.identifier, str(exc))


class ApiNamePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("命名 API")
        self.setSubTitle("为这组 API Key 设置一个便于识别的名称。")
        layout = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText("例如 main、personal 或 backup")
        self.registerField("api_name*", self.name)
        layout.addRow("API 名称", self.name)


class ApiKeyPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("填写 API Key")
        self.setSubTitle("密钥只会保存在本地 .config 目录，保存时会自动移除空白字符。")
        layout = QFormLayout(self)
        self.key = QLineEdit()
        self.key.setProperty("role", "secret")
        self.key.setFont(QFont("JetBrains Mono", 11))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("粘贴 API Key")
        self.registerField("apikey*", self.key)
        layout.addRow("API Key", self.key)


class AddApiWizard(QWizard):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("添加 API")
        self.resize(560, 330)
        provider_page = QWizardPage()
        provider_page.setTitle("选择供应商")
        provider_page.setSubTitle("选择要查询的 API 平台。")
        provider_layout = QFormLayout(provider_page)
        self.provider = QComboBox()
        self.provider.addItem("OpenCode Go", "opencode_go")
        self.provider.addItem("DeepSeek", "deepseek")
        self.provider.addItem("智谱 API", "zhipu")
        provider_layout.addRow("供应商", self.provider)
        self.name_page = ApiNamePage()
        self.key_page = ApiKeyPage()
        self.addPage(provider_page)
        self.addPage(self.name_page)
        self.addPage(self.key_page)
        self.setButtonText(QWizard.WizardButton.FinishButton, "保存 API")

    def record(self) -> dict[str, dict[str, str]]:
        return {self.provider.currentData(): {
            "api_name": self.name_page.name.text().strip(),
            "apikey": self.key_page.key.text().strip(),
        }}


class ApiCard(QFrame):
    query_requested = Signal(str)

    def __init__(self, identifier: str, cached: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.identifier = identifier
        self.setObjectName("apiCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        header = QHBoxLayout()
        provider, name = identifier.split("/", 1)
        title = QLabel(f"{provider_label(provider)} / {name}")
        title.setObjectName("cardTitle")
        header.addWidget(title)
        header.addStretch()
        self.status = QLabel("未查询")
        self.status.setObjectName("statusBadge")
        self.status.setProperty("state", "unqueried")
        header.addWidget(self.status)
        layout.addLayout(header)
        self.details = QVBoxLayout()
        self.details.setSpacing(7)
        layout.addLayout(self.details)
        action = QPushButton("立即查询")
        action.setObjectName("smallButton")
        action.clicked.connect(lambda: self.query_requested.emit(self.identifier))
        layout.addWidget(action, alignment=Qt.AlignmentFlag.AlignRight)
        if cached:
            self.set_result(cached["result"], cached["queried_at"])

    def clear_details(self) -> None:
        while self.details.count():
            item = self.details.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def set_result(self, result: dict[str, Any], queried_at: str) -> None:
        self.clear_details()
        state = result_state(result)
        self.status.setText({"success": "正常", "warning": "注意", "error": "异常"}[state])
        self.status.setProperty("state", state)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.details.addWidget(QLabel(f"最后查询：{queried_at}"))
        data = result.get("data", {})
        if result.get("provider") == "deepseek":
            for info in data.get("balance_infos", []):
                currency = info.get("currency", "?")
                self.details.addWidget(QLabel(f"币种：{currency}"))
                self.details.addWidget(QLabel(f"总余额：{info.get('total_balance', '?')}"))
                self.details.addWidget(QLabel(f"充值余额：{info.get('topped_up_balance', '?')}"))
                self.details.addWidget(QLabel(f"赠金余额：{info.get('granted_balance', '?')}"))
        elif result.get("kind") == "usage":
            for key, label in (("rolling", "5 小时"), ("weekly", "本周"), ("monthly", "本月")):
                item = data[key]
                row = QHBoxLayout()
                row.addWidget(QLabel(label))
                progress = QProgressBar()
                progress.setRange(0, 100)
                progress.setValue(min(100, int(item.get("percent", 0))))
                progress.setTextVisible(True)
                progress.setFormat(f"{item.get('percent', '?')}%")
                progress.setProperty("state", "error" if progress.value() >= 90 else "warning" if progress.value() >= 70 else "success")
                progress.style().unpolish(progress)
                progress.style().polish(progress)
                row.addWidget(progress, 1)
                self.details.addLayout(row)
                self.details.addWidget(QLabel(f"重置：{item.get('resetsAt', '?')}"))
        else:
            self.details.addWidget(QLabel(result.get("message", "API Key 有效")))


class UsageResultWidget(QFrame):
    """Structured result view for provider usage and balance responses."""

    def __init__(self) -> None:
        super().__init__(objectName="resultWidget")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(12)

    def clear(self) -> None:
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def loading(self) -> None:
        self.clear()
        label = QLabel("正在请求远程接口，请稍候...", objectName="loadingState")
        self.layout.addWidget(label)
        self.layout.addStretch()

    def error(self, message: str) -> None:
        self.clear()
        label = QLabel(message, objectName="errorState")
        label.setWordWrap(True)
        self.layout.addWidget(label)
        self.layout.addStretch()

    def render(self, result: dict[str, Any]) -> None:
        self.clear()
        provider = result.get("provider")
        data = result.get("data", {})
        state = result_state(result)
        status = QLabel({"success": "正常", "warning": "注意", "error": "异常"}[state])
        status.setObjectName("statusBadge")
        status.setProperty("state", state)
        self.layout.addWidget(status, alignment=Qt.AlignmentFlag.AlignLeft)
        if result.get("kind") == "usage":
            for key, label in (("rolling", "5 小时"), ("weekly", "本周"), ("monthly", "本月")):
                item = data[key]
                row = QHBoxLayout()
                name = QLabel(label)
                name.setMinimumWidth(54)
                row.addWidget(name)
                progress = QProgressBar()
                percent = min(100, max(0, int(item.get("percent", 0))))
                progress.setRange(0, 100)
                progress.setValue(percent)
                progress.setTextVisible(True)
                progress.setFormat(f"{percent}%")
                progress.setProperty("state", "error" if percent >= 90 else "warning" if percent >= 70 else "success")
                progress.style().unpolish(progress)
                progress.style().polish(progress)
                row.addWidget(progress, 1)
                self.layout.addLayout(row)
                reset = QLabel(f"重置：{item.get('resetsAt', '?')}", objectName="hint")
                self.layout.addWidget(reset)
        elif provider == "deepseek":
            for info in data.get("balance_infos", []):
                self.layout.addWidget(QLabel(f"币种：{info.get('currency', '?')}"))
                self.layout.addWidget(QLabel(f"总余额：{info.get('total_balance', '?')}"))
                self.layout.addWidget(QLabel(f"充值余额：{info.get('topped_up_balance', '?')}"))
                self.layout.addWidget(QLabel(f"赠金余额：{info.get('granted_balance', '?')}"))
        else:
            message = result.get("message", "API Key 有效，具体余额请查看智谱控制台。")
            self.layout.addWidget(QLabel(message))
        self.layout.addStretch()


class OverviewPage(QWidget):
    query_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.cache: dict[str, dict[str, Any]] = {}
        self.cards_layout = QGridLayout()
        self.cards_layout.setSpacing(12)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 24)
        header = QHBoxLayout()
        title = QLabel("总览")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        self.summary = QLabel("等待查询")
        self.summary.setObjectName("muted")
        header.addWidget(self.summary)
        layout.addLayout(header)
        stats = QHBoxLayout()
        self.total = self.stat_card("已配置 API", "0", "本地配置")
        self.healthy = self.stat_card("正常状态", "0", "最近查询")
        self.recent = self.stat_card("最近查询", "暂无", "等待操作")
        stats.addWidget(self.total)
        stats.addWidget(self.healthy)
        stats.addWidget(self.recent)
        layout.addLayout(stats)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        cards_host = QWidget()
        cards_host.setLayout(self.cards_layout)
        scroll.setWidget(cards_host)
        layout.addWidget(scroll, 1)

    def stat_card(self, heading: str, value: str, hint: str) -> QFrame:
        card = QFrame(objectName="statCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 14, 16, 14)
        box.addWidget(QLabel(heading, objectName="muted"))
        value_label = QLabel(value, objectName="statValue")
        box.addWidget(value_label)
        box.addWidget(QLabel(hint, objectName="hint"))
        card.value_label = value_label  # type: ignore[attr-defined]
        return card

    def update_data(self, cache: dict[str, dict[str, Any]]) -> None:
        self.cache = cache
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        identifiers = show_all_api()
        for index, identifier in enumerate(identifiers):
            card = ApiCard(identifier, cache.get(identifier))
            card.query_requested.connect(self.query_requested)
            self.cards_layout.addWidget(card, index // 2, index % 2)
        self.total.value_label.setText(str(len(identifiers)))  # type: ignore[attr-defined]
        success = sum(1 for item in cache.values() if result_state(item["result"]) == "success")
        self.healthy.value_label.setText(str(success))  # type: ignore[attr-defined]
        latest = max(cache.values(), key=lambda item: item["queried_at"], default=None)
        self.recent.value_label.setText(latest["result"]["key"].split("/", 1)[-1] if latest else "暂无")  # type: ignore[attr-defined]
        self.summary.setText(f"{len(identifiers)} 个 API · {success} 个正常")


class ApiManagerPage(QWidget):
    query_requested = Signal(str)
    add_requested = Signal()
    delete_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.list = QListWidget()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索 provider/api_name")
        self.query_button = QPushButton("查询")
        self.query_button.setObjectName("primary")
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("danger")
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setVisible(False)
        self.result_view = UsageResultWidget()
        self.copy_button = QPushButton("复制结果")
        self.copy_button.setEnabled(False)
        self.search.textChanged.connect(self.refresh)
        self.list.itemDoubleClicked.connect(lambda _item: self.query())
        self.query_button.clicked.connect(self.query)
        self.delete_button.clicked.connect(self.delete)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 24)
        title = QLabel("API 管理", objectName="pageTitle")
        layout.addWidget(title)
        row = QHBoxLayout()
        row.addWidget(self.search)
        add = QPushButton("添加 API")
        add.setObjectName("primary")
        add.clicked.connect(self.add_requested)
        row.addWidget(add)
        layout.addLayout(row)
        body = QHBoxLayout()
        left = QFrame(objectName="panel")
        left_box = QVBoxLayout(left)
        left_box.addWidget(QLabel("API 列表"))
        left_box.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.query_button)
        buttons.addWidget(self.delete_button)
        left_box.addLayout(buttons)
        body.addWidget(left, 1)
        right = QFrame(objectName="panel")
        right_box = QVBoxLayout(right)
        result_header = QHBoxLayout()
        result_header.addWidget(QLabel("查询结果"))
        result_header.addStretch()
        result_header.addWidget(self.copy_button)
        right_box.addLayout(result_header)
        right_box.addWidget(self.result_view, 1)
        right_box.addWidget(self.output)
        body.addWidget(right, 1)
        layout.addLayout(body, 1)

    def refresh(self) -> None:
        values = search_api(self.search.text())
        self.list.clear()
        for value in values:
            self.list.addItem(QListWidgetItem(value))

    def selected(self) -> str | None:
        item = self.list.currentItem()
        return item.text() if item else None

    def query(self) -> None:
        identifier = self.selected()
        if identifier:
            self.query_requested.emit(identifier)

    def delete(self) -> None:
        identifier = self.selected()
        if identifier:
            self.delete_requested.emit(identifier)

    def set_busy(self, busy: bool) -> None:
        self.query_button.setEnabled(not busy)
        self.delete_button.setEnabled(not busy)
        self.query_button.setText("查询中..." if busy else "查询")

    def show_loading(self) -> None:
        self.result_view.loading()

    def show_result(self, result: dict[str, Any]) -> None:
        self.result_view.render(result)

    def show_error(self, message: str) -> None:
        self.result_view.error(message)


class HelpPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 24)
        layout.addWidget(QLabel("使用说明", objectName="pageTitle"))
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml("""
        <h2>API Balance Center</h2>
        <p>用于管理和查询 OpenCode Go、DeepSeek、智谱 API。</p>
        <h3>查询接口</h3>
        <p><b>OpenCode Go</b><br>GET https://opencode.ai/zen/go/v1/usage</p>
        <p><b>DeepSeek</b><br>GET https://api.deepseek.com/user/balance</p>
        <p><b>智谱</b><br>优先尝试控制台余额接口，失败后使用官方模型接口验证 API Key。</p>
        <h3>配置格式</h3>
        <p>通过“API 管理 &gt; 添加 API”按三步完成配置，无需手动编写 JSON。</p>
        <h3>错误码说明</h3>
        <p>OpenCode Go 的 401/403 分别表示认证失败和没有 Go 订阅。智谱 1113 表示余额不足，1308/1310 表示套餐用量达到限制。</p>
        """)
        layout.addWidget(browser, 1)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("API Balance Center")
        self.resize(1120, 720)
        self.setMinimumSize(860, 560)
        self.cache: dict[str, dict[str, Any]] = {}
        self.thread: QThread | None = None
        self.worker: QueryWorker | None = None
        self.collapsed = False
        self._build()
        self.refresh_all()

    def _build(self) -> None:
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.sidebar = QFrame(objectName="sidebar")
        self.sidebar.setMinimumWidth(68)
        self.sidebar.setMaximumWidth(220)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(12, 22, 12, 18)
        self.brand = QLabel("API Balance", objectName="brand")
        side.addWidget(self.brand)
        side.addWidget(QLabel("账户状态控制台", objectName="muted"))
        side.addSpacing(28)
        side.addWidget(QLabel("WORKSPACE", objectName="section"))
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list[QToolButton] = []
        for text, icon, index in (("总览", "◉", 0), ("API 管理", "▣", 1), ("使用说明", "?", 2)):
            button = QToolButton()
            button.setObjectName("navButton")
            button.setText(f"{icon}  {text}")
            button.setProperty("fullText", f"{icon}  {text}")
            button.setProperty("shortText", icon)
            button.setToolTip(text)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.clicked.connect(lambda _checked, page=index: self.pages.setCurrentIndex(page))
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            side.addWidget(button)
        self.nav_buttons[0].setChecked(True)
        side.addStretch()
        self.collapse_button = QToolButton()
        self.collapse_button.setObjectName("navButton")
        self.collapse_button.setText("‹  收起侧栏")
        self.collapse_button.clicked.connect(self.toggle_sidebar)
        side.addWidget(self.collapse_button)
        side.addWidget(QLabel("API Key 仅保存在本地", objectName="muted"))
        root.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        self.overview = OverviewPage()
        self.manager = ApiManagerPage()
        self.help_page = HelpPage()
        self.pages.addWidget(self.overview)
        self.pages.addWidget(self.manager)
        self.pages.addWidget(self.help_page)
        self.overview.query_requested.connect(self.query_api)
        self.manager.query_requested.connect(self.query_api)
        self.manager.add_requested.connect(self.add_api)
        self.manager.delete_requested.connect(self.remove_api)
        self.manager.copy_button.clicked.connect(self.copy_result)
        root.addWidget(self.pages, 1)

    def refresh_all(self) -> None:
        self.manager.refresh()
        self.overview.update_data(self.cache)

    def toggle_sidebar(self) -> None:
        self.collapsed = not self.collapsed
        self.sidebar.setMaximumWidth(68 if self.collapsed else 220)
        self.sidebar.setMinimumWidth(68 if self.collapsed else 220)
        self.brand.setVisible(not self.collapsed)
        self.collapse_button.setText("›" if self.collapsed else "‹  收起侧栏")
        for button in self.nav_buttons:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setText(button.property("shortText") if self.collapsed else button.property("fullText"))

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        if self.width() < 960 and not self.collapsed:
            self.toggle_sidebar()
        elif self.width() >= 1040 and self.collapsed:
            self.toggle_sidebar()

    def query_api(self, identifier: str) -> None:
        if self.thread and self.thread.isRunning():
            return
        self.manager.set_busy(True)
        self.manager.show_loading()
        self.manager.output.setPlainText("正在请求远程接口，请稍候...")
        self.manager.output.setProperty("loading", True)
        self.manager.output.style().unpolish(self.manager.output)
        self.manager.output.style().polish(self.manager.output)
        self.manager.copy_button.setEnabled(False)
        self.pages.setCurrentWidget(self.manager)
        self.thread = QThread(self)
        self.worker = QueryWorker(identifier)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.query_finished)
        self.worker.failed.connect(self.query_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker_finished)
        self.thread.start()

    def query_finished(self, identifier: str, result: dict[str, Any]) -> None:
        self.cache[identifier] = {"result": result, "queried_at": now_text()}
        self.manager.show_result(result)
        self.manager.output.setPlainText(format_result(result))
        self.manager.output.setProperty("loading", False)
        self.manager.output.style().unpolish(self.manager.output)
        self.manager.output.style().polish(self.manager.output)
        self.manager.copy_button.setEnabled(True)
        self.manager.set_busy(False)
        self.refresh_all()

    def query_failed(self, identifier: str, message: str) -> None:
        formatted = format_error(identifier, message)
        self.manager.show_error(formatted)
        self.manager.output.setPlainText(formatted)
        self.manager.output.setProperty("loading", False)
        self.manager.output.style().unpolish(self.manager.output)
        self.manager.output.style().polish(self.manager.output)
        self.manager.copy_button.setEnabled(True)
        self.manager.set_busy(False)

    def worker_finished(self) -> None:
        if self.thread:
            self.thread.deleteLater()
        self.thread = None
        self.worker = None

    def add_api(self) -> None:
        dialog = AddApiWizard(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                add_api(dialog.record())
                self.refresh_all()
            except (AppError, OSError) as exc:
                QMessageBox.critical(self, "增加失败", str(exc))

    def remove_api(self, identifier: str) -> None:
        if QMessageBox.question(self, "确认删除", f"确定删除 {identifier} 吗？") != QMessageBox.StandardButton.Yes:
            return
        try:
            del_api(identifier)
            self.cache.pop(identifier, None)
            self.refresh_all()
        except AppError as exc:
            QMessageBox.critical(self, "删除失败", str(exc))

    def copy_result(self) -> None:
        QApplication.clipboard().setText(self.manager.output.toPlainText())
        self.manager.copy_button.setText("已复制")

    def closeEvent(self, event: Any) -> None:
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait(1000)
        event.accept()


def format_result(result: dict[str, Any]) -> str:
    provider = result["provider"]
    data = result.get("data", {})
    lines = [f"API: {result['key']}", "状态：正常", f"查询时间：{now_text()}", ""]
    if provider == "deepseek":
        lines.append(f"账户可用：{data.get('is_available', 'unknown')}")
        for info in data.get("balance_infos", []):
            lines.extend([
                f"币种：{info.get('currency', '?')}",
                f"总余额：{info.get('total_balance', '?')}",
                f"充值余额：{info.get('topped_up_balance', '?')}",
                f"赠金余额：{info.get('granted_balance', '?')}",
            ])
    elif result.get("kind") == "usage":
        for key, label in (("rolling", "5 小时"), ("weekly", "本周"), ("monthly", "本月")):
            item = data[key]
            lines.append(f"{label}：{item.get('percent', '?')}%")
            lines.append(f"重置时间：{item.get('resetsAt', '?')}")
    elif result.get("kind") == "balance":
        lines.append(json.dumps(data.get("data", {}), ensure_ascii=False, indent=2))
    else:
        lines.append(result.get("message", "API Key 有效，具体余额请查看智谱控制台。"))
    return "\n".join(lines)


def format_error(identifier: str, message: str) -> str:
    return f"API：{identifier}\n状态：查询失败\n查询时间：{now_text()}\n\n错误信息：\n{message}\n\n建议：检查 API Key、网络连接和供应商服务状态。"


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    load_fonts(app)
    stylesheet = Path(__file__).with_name("ui") / "styles.qss"
    app.setStyleSheet(stylesheet.read_text(encoding="utf-8"))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def load_fonts(app: QApplication) -> None:
    """Load bundled fonts and fall back to the platform font if unavailable."""
    fonts_dir = Path(__file__).with_name("ui") / "fonts"
    regular_id = QFontDatabase.addApplicationFont(str(fonts_dir / "SourceHanSansSC-Regular.otf"))
    QFontDatabase.addApplicationFont(str(fonts_dir / "SourceHanSansSC-Medium.otf"))
    QFontDatabase.addApplicationFont(str(fonts_dir / "SourceHanSansSC-Bold.otf"))
    QFontDatabase.addApplicationFont(str(fonts_dir / "JetBrainsMono-Regular.ttf"))
    if regular_id >= 0:
        families = QFontDatabase.applicationFontFamilies(regular_id)
        if families:
            app.setFont(QFont(families[0], 10))


if __name__ == "__main__":
    main()
