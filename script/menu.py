"""PySide6 desktop UI for API balance and usage monitoring."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot, QSize
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QInputDialog,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QTextBrowser,
    QToolButton, QVBoxLayout, QWidget, QTreeWidget, QTreeWidgetItem,
)

from .function import add_api, del_api, select_api, show_all_api
from .util import AppError, validate_base_url
from .providers import PROVIDERS, provider_label
from . import metadata


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def serif_label(text: str, role: str) -> QLabel:
    label = QLabel(text, objectName=role)
    families = set(QFontDatabase.families())
    family = next((name for name in ("Georgia", "Times New Roman", "Noto Serif") if name in families), "serif")
    font = QFont(family)
    font.setStyleHint(QFont.StyleHint.Serif)
    label.setFont(font)
    return label


def nav_icon(kind: int) -> QIcon:
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#c8bdab"), 1.5))
    if kind == 0:
        for x, y in ((4, 4), (14, 4), (4, 14), (14, 14)):
            painter.drawRect(x, y, 6, 6)
    elif kind == 1:
        for y in (5, 11, 17):
            painter.drawRect(4, y, 16, 3)
    elif kind == 2:
        for x, height in ((5, 6), (11, 12), (17, 17)):
            painter.drawRect(x, 21-height, 3, height)
    else:
        painter.drawRect(5, 3, 14, 18)
        painter.drawLine(8, 8, 16, 8)
        painter.drawLine(8, 12, 16, 12)
        painter.drawLine(8, 16, 13, 16)
    painter.end()
    return QIcon(pixmap)


def result_state(result: dict[str, Any]) -> str:
    if result.get('kind') == 'plan_quota':
        used = max(100 - value for item in result['quotas'] for value in (item['rolling'], item['weekly']))
        return 'error' if used >= 90 else 'warning' if used >= 70 else 'success'
    if result.get("kind") == "usage":
        values = [result["data"][key].get("percent", 0) for key in ("rolling", "weekly", "monthly")]
        return "error" if max(values) >= 90 else "warning" if max(values) >= 70 else "success"
    if result.get("kind") == "balance" and result.get("data", {}).get("is_available") is False:
        return "error"
    if result.get("kind") in {"balance", "key_status", "connection", "key_usage"}:
        return "success"
    return "error"


class QueryWorker(QObject):
    finished = Signal(str, dict)
    failed = Signal(str, str)

    def __init__(self, identifier: str) -> None:
        super().__init__()
        self.identifier = identifier

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.identifier, select_api(self.identifier))
        except (AppError, OSError) as exc:
            self.failed.emit(self.identifier, str(exc))
        except Exception:
            self.failed.emit(self.identifier, '接口响应格式异常，请检查供应商接口。')


class AddApiDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connect Provider / 添加账户")
        self.resize(560, 450)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(serif_label("Connect Provider", "dialogTitle"))
        self.provider = QComboBox()
        for key, spec in PROVIDERS.items():
            self.provider.addItem(f"{spec['group']} / {spec['label']}", key)
        self.capability = QLabel(objectName="hint")
        self.capability.setWordWrap(True)
        self.query_mode = QComboBox()
        self.query_mode.addItem('普通密钥 / 额度与用量', 'key')
        self.query_mode.addItem('管理密钥 / 账户余额', 'account')
        self.name = QLineEdit()
        self.name.setPlaceholderText("main / personal / backup")
        self.note = QLineEdit()
        self.note.setPlaceholderText("可选，例如：主力开发、备用账户")
        self.note.setMaxLength(120)
        self.base = QLineEdit()
        self.key = QLineEdit()
        self.key.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("粘贴 API Key")
        form = QFormLayout()
        self.form = form
        form.addRow("供应商", self.provider)
        form.addRow("能力", self.capability)
        form.addRow("OpenRouter 模式", self.query_mode)
        form.addRow("账户标识", self.name)
        form.addRow("备注", self.note)
        form.addRow("Base URL", self.base)
        form.addRow("API Key", self.key)
        layout.addLayout(form)
        self.error_label = QLabel(objectName="errorText")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存账户")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.provider.currentIndexChanged.connect(self.provider_changed)
        self.provider_changed()

    def provider_changed(self):
        spec = PROVIDERS[self.provider.currentData()]
        self.base.setText(spec['base'])
        self.base.setReadOnly(self.provider.currentData() != 'custom')
        self.form.setRowVisible(self.query_mode, self.provider.currentData() == 'openrouter')
        self.capability.setText(spec['capability'] + " · 不产生推理调用费用")

    def accept(self):
        if not self.name.text().strip() or not self.key.text().strip():
            self.error_label.setText("请填写账户标识与密钥。")
            return
        if self.provider.currentData() == 'custom':
            try:
                validate_base_url(self.base.text())
            except AppError as exc:
                self.error_label.setText(str(exc))
                return
        super().accept()

    def record(self):
        record = {'api_name': self.name.text().strip(), 'apikey': self.key.text().strip(), 'note': self.note.text().strip()}
        if self.provider.currentData() == 'custom':
            record['base_url'] = self.base.text().strip()
        if self.provider.currentData() == 'openrouter':
            record['query_mode'] = self.query_mode.currentData()
        return {self.provider.currentData(): record}


class UsageResultWidget(QFrame):
    """One result renderer shared by account cards and the detail panel."""

    def __init__(self) -> None:
        super().__init__(objectName="resultWidget")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(12)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.error("选择账户后查询余额或用量。")

    def clear(self) -> None:
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def loading(self) -> None:
        self.error("正在查询…")

    def error(self, message: str) -> None:
        self.clear()
        label = QLabel(message, objectName="hint")
        label.setWordWrap(True)
        self.layout.addWidget(label)

    def render(self, result: dict[str, Any]) -> None:
        self.clear()
        data = result.get("data", {})
        if result.get("kind") == "error":
            self.error(result.get("message", "查询失败"))
        elif result.get("kind") == "usage":
            for key, title in (("rolling", "5 小时"), ("weekly", "本周"), ("monthly", "本月")):
                item = data[key]
                percent = float(item.get("percent", 0))
                block = QWidget()
                box = QVBoxLayout(block)
                box.setContentsMargins(0, 0, 0, 0)
                row = QHBoxLayout()
                row.addWidget(QLabel(title))
                row.addStretch()
                row.addWidget(QLabel(f"{percent:g}%", objectName="usageValue"))
                box.addLayout(row)
                progress = QProgressBar()
                progress.setRange(0, 100)
                progress.setValue(min(100, max(0, int(percent))))
                progress.setTextVisible(False)
                progress.setProperty("state", "error" if percent >= 90 else "warning" if percent >= 70 else "success")
                box.addWidget(progress)
                reset = QLabel(f"重置 {item.get('resetsAt', '未知')}", objectName="hint")
                reset.setWordWrap(True)
                box.addWidget(reset)
                self.layout.addWidget(block)
        elif result.get('kind') == 'plan_quota':
            for quota in result['quotas']:
                self.layout.addWidget(QLabel(quota['model'], objectName='cardTitle'))
                for field, title in (('rolling', '5 小时'), ('weekly', '本周')):
                    remaining = quota[field]
                    self.layout.addWidget(QLabel(f'{title}剩余 {remaining:g}%', objectName='usageValue'))
                    progress = QProgressBar()
                    progress.setRange(0, 100)
                    progress.setValue(round(remaining))
                    progress.setTextVisible(False)
                    self.layout.addWidget(progress)
        elif result.get("provider") == "deepseek":
            for info in data.get("balance_infos", []):
                block = QWidget()
                box = QVBoxLayout(block)
                box.setContentsMargins(0, 0, 0, 0)
                box.addWidget(QLabel(f"账户余额 · {info.get('currency', '?')}", objectName="hint"))
                box.addWidget(QLabel(str(info.get('total_balance', '?')), objectName="balanceValue"))
                box.addWidget(QLabel(f"充值 {info.get('topped_up_balance', '?')}    赠金 {info.get('granted_balance', '?')}", objectName="muted"))
                self.layout.addWidget(block)
        elif result.get("kind") == "balance" and "balance" in result:
            self.layout.addWidget(QLabel(f"账户余额 · {result.get('currency', '?')}", objectName="hint"))
            self.layout.addWidget(QLabel(result['balance'], objectName="balanceValue"))
        elif result.get("kind") == "key_usage":
            account = data['data']
            self.layout.addWidget(QLabel("密钥剩余额度 · USD", objectName="hint"))
            remaining = account.get('limit_remaining')
            self.layout.addWidget(QLabel(str(remaining) if remaining is not None else "未设限", objectName="balanceValue"))
            for key, title in (("usage_daily", "今日消耗"), ("usage_weekly", "近周消耗"), ("usage_monthly", "近月消耗")):
                self.layout.addWidget(QLabel(f"{title}  ${account.get(key, '—')}", objectName="muted"))
            note = QLabel(result['message'], objectName="hint")
            note.setWordWrap(True)
            self.layout.addWidget(note)
        elif result.get("kind") == "connection":
            self.layout.addWidget(QLabel("CONNECTED", objectName="usageValue"))
            self.layout.addWidget(QLabel(f"返回 {result.get('model_count', 0)} 个模型", objectName="cardTitle"))
            note = QLabel("此供应商仅做连接检查；余额请查看其控制台。", objectName="hint")
            note.setWordWrap(True)
            self.layout.addWidget(note)
        elif result.get("kind") == "balance":
            account = data.get("data", {})
            value = account.get("availableBalance", account.get("balance", "未知"))
            self.layout.addWidget(QLabel("账户余额", objectName="hint"))
            self.layout.addWidget(QLabel(str(value), objectName="balanceValue"))
        else:
            label = QLabel("密钥验证通过\n余额请前往智谱控制台查看。", objectName="hint")
            label.setWordWrap(True)
            self.layout.addWidget(label)


class ApiCard(QFrame):
    query_requested = Signal(str)

    def __init__(self, identifier: str, cached: dict[str, Any] | None = None) -> None:
        super().__init__(objectName="apiCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)
        provider, name = identifier.split("/", 1)
        header = QHBoxLayout()
        title = QLabel(metadata.notes().get(identifier) or name, objectName="cardTitle")
        title.setWordWrap(True)
        header.addWidget(title, 1)
        state = result_state(cached["result"]) if cached else "unqueried"
        status = QLabel({"success": "已同步", "warning": "注意", "error": "异常", "unqueried": "未同步"}[state], objectName="statusBadge")
        status.setProperty("state", state)
        header.addWidget(status)
        layout.addLayout(header)
        name_label = QLabel(identifier, objectName="hint")
        name_label.setWordWrap(True)
        layout.addWidget(name_label)
        view = UsageResultWidget()
        if cached:
            view.render(cached["result"])
        else:
            view.error("尚无查询结果")
        layout.addWidget(view)
        layout.addStretch()
        footer = QHBoxLayout()
        stamp = cached["queried_at"][11:19] if cached else "—"
        footer.addWidget(QLabel(f"最近查询 {stamp}", objectName="hint"))
        footer.addStretch()
        action = QPushButton("查询 →")
        action.clicked.connect(lambda: self.query_requested.emit(identifier))
        footer.addWidget(action)
        layout.addLayout(footer)


class OverviewPage(QWidget):
    query_requested = Signal(str)
    add_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.cache: dict[str, dict[str, Any]] = {}
        self.cards_layout = QGridLayout()
        self.cards_layout.setSpacing(16)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cards_layout.setColumnStretch(0, 1)
        self.cards_layout.setColumnStretch(1, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 24)
        header = QHBoxLayout()
        title = serif_label("Field Console", "pageTitle")
        header.addWidget(title)
        header.addStretch()
        self.summary = QLabel("等待查询")
        self.summary.setObjectName("muted")
        header.addWidget(self.summary)
        add = QPushButton("+ 添加账户", objectName="primary")
        add.clicked.connect(self.add_requested)
        header.addWidget(add)
        layout.addLayout(header)
        layout.addWidget(QLabel("01 / ACCOUNTS     余额、额度与供应商状态", objectName="pageSubtitle"))
        stats = QHBoxLayout()
        self.total = self.stat_card("账户", "0", "本地配置")
        self.healthy = self.stat_card("状态正常", "0", "最近查询")
        self.recent = self.stat_card("供应商", str(len(PROVIDERS)), "官方接口与兼容服务")
        stats.addWidget(self.total)
        stats.addWidget(self.healthy)
        stats.addWidget(self.recent)
        layout.addLayout(stats)
        self.provider_filter = QComboBox()
        self.provider_filter.addItem("全部供应商", "")
        self.provider_filter.currentIndexChanged.connect(lambda: self.update_data(self.cache))
        layout.addWidget(self.provider_filter, alignment=Qt.AlignmentFlag.AlignLeft)
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
                item.widget().hide()
                item.widget().deleteLater()
        identifiers = show_all_api()
        if not identifiers:
            empty = QLabel("还没有账户\n点击右上角“添加账户”开始使用。", objectName="emptyState")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cards_layout.addWidget(empty, 0, 0, 1, 2)
        available = sorted({key.split('/')[0] for key in identifiers})
        selected = self.provider_filter.currentData()
        self.provider_filter.blockSignals(True)
        self.provider_filter.clear()
        self.provider_filter.addItem("全部供应商", "")
        for provider in available:
            self.provider_filter.addItem(provider_label(provider), provider)
        self.provider_filter.setCurrentIndex(max(0, self.provider_filter.findData(selected)))
        self.provider_filter.blockSignals(False)
        row = 0
        for provider in available:
            if selected and provider != selected:
                continue
            header = QFrame(objectName="providerHeader")
            box = QHBoxLayout(header)
            box.setContentsMargins(0, 12, 0, 8)
            box.addWidget(serif_label(provider_label(provider), "providerTitle"))
            box.addWidget(QLabel(PROVIDERS.get(provider, {}).get('capability', '未支持'), objectName="hint"))
            box.addStretch()
            self.cards_layout.addWidget(header, row, 0, 1, 2)
            row += 1
            keys = [key for key in identifiers if key.split('/')[0] == provider]
            cards = []
            for index, identifier in enumerate(keys):
                card = ApiCard(identifier, cache.get(identifier))
                cards.append(card)
                card.query_requested.connect(self.query_requested)
                self.cards_layout.addWidget(card, row + index // 2, index % 2, alignment=Qt.AlignmentFlag.AlignTop)
            for index in range(0, len(cards), 2):
                pair = cards[index:index+2]
                height = max(card.sizeHint().height() for card in pair)
                for card in pair:
                    card.setFixedHeight(height)
            row += (len(keys)+1)//2
        self.total.value_label.setText(str(len(identifiers)))  # type: ignore[attr-defined]
        success = sum(1 for item in cache.values() if result_state(item["result"]) == "success")
        self.healthy.value_label.setText(str(success))  # type: ignore[attr-defined]
        self.recent.value_label.setText(str(len(PROVIDERS)))
        self.summary.setText(f"{len(identifiers)} 个 API · {success} 个正常")


class ApiManagerPage(QWidget):
    query_requested = Signal(str)
    add_requested = Signal()
    delete_requested = Signal(str)
    note_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.list = QTreeWidget()
        self.list.setHeaderHidden(True)
        self.list.setIndentation(18)
        self.list.setColumnCount(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索供应商、账户或备注")
        self.query_button = QPushButton("查询")
        self.query_button.setObjectName("primary")
        self.note_button = QPushButton("备注")
        self.note_button.clicked.connect(lambda: self.note_requested.emit(self.selected()) if self.selected() else None)
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("danger")
        self.result_text = ""
        self.result_view = UsageResultWidget()
        self.copy_button = QPushButton("复制结果")
        self.copy_button.setEnabled(False)
        self.search.textChanged.connect(self.refresh)
        self.list.itemDoubleClicked.connect(lambda _item: self.query())
        self.query_button.clicked.connect(self.query)
        self.delete_button.clicked.connect(self.delete)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 24)
        title = serif_label("Providers", "pageTitle")
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
        buttons.addWidget(self.note_button)
        buttons.addWidget(self.delete_button)
        left_box.addLayout(buttons)
        body.addWidget(left, 2)
        right = QFrame(objectName="panel")
        right_box = QVBoxLayout(right)
        result_header = QHBoxLayout()
        result_header.addWidget(QLabel("查询结果"))
        result_header.addStretch()
        result_header.addWidget(self.copy_button)
        right_box.addLayout(result_header)
        result_scroll = QScrollArea()
        result_scroll.setWidgetResizable(True)
        result_scroll.setFrameShape(QFrame.Shape.NoFrame)
        result_scroll.setWidget(self.result_view)
        right_box.addWidget(result_scroll, 1)

        body.addWidget(right, 3)
        layout.addLayout(body, 1)

    def refresh(self) -> None:
        previous = self.selected()
        self.list.clear()
        groups = {}
        notes = metadata.notes()
        query = self.search.text().strip().casefold()
        for identifier in show_all_api():
            provider, name = identifier.split('/', 1)
            note = notes.get(identifier, '')
            haystack = f"{identifier} {provider_label(provider)} {note}".casefold()
            if query and query not in haystack:
                continue
            if provider not in groups:
                groups[provider] = QTreeWidgetItem(self.list, [provider_label(provider)])
                groups[provider].setFlags(Qt.ItemFlag.ItemIsEnabled)
                groups[provider].setExpanded(True)
            item = QTreeWidgetItem(groups[provider], [note or name])
            item.setData(0, Qt.ItemDataRole.UserRole, identifier)
            item.setToolTip(0, identifier)
            if identifier == previous:
                self.list.setCurrentItem(item)

    def select_identifier(self, identifier):
        for index in range(self.list.topLevelItemCount()):
            group = self.list.topLevelItem(index)
            for child_index in range(group.childCount()):
                item = group.child(child_index)
                if item.data(0, Qt.ItemDataRole.UserRole) == identifier:
                    self.list.setCurrentItem(item)
                    return

    def selected(self) -> str | None:
        item = self.list.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

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
        self.note_button.setEnabled(not busy)
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
        layout.addWidget(serif_label("Operator Guide", "pageTitle"))
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml("""
        <h2>Field Console</h2>
        <p>用于管理和查询 OpenCode Go、DeepSeek、智谱 API。</p>
        <h3>查询接口</h3>
        <p><b>OpenCode Go</b><br>GET https://opencode.ai/zen/go/v1/usage</p>
        <p><b>DeepSeek</b><br>GET https://api.deepseek.com/user/balance</p>
        <p><b>智谱</b><br>优先尝试控制台余额接口，失败后使用官方模型接口验证 API Key。</p>
        <h3>配置格式</h3>
        <p>通过“API 管理 &gt; 添加 API”选择供应商并填写标识、备注与密钥，无需手动编写 JSON。</p>
        <h3>错误码说明</h3>
        <p>OpenCode Go 的 401/403 分别表示认证失败和没有 Go 订阅。智谱 1113 表示余额不足，1308/1310 表示套餐用量达到限制。</p>
        """)
        layout.addWidget(browser, 1)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("API 余额查询")
        self.resize(1120, 720)
        self.setMinimumSize(860, 600)
        self.cache: dict[str, dict[str, Any]] = {}
        self.thread: QThread | None = None
        self.worker: QueryWorker | None = None
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
        self.sidebar.setFixedWidth(208)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(12, 22, 12, 18)
        self.brand = serif_label("Field Console", "brand")
        side.addWidget(self.brand)
        side.addWidget(QLabel("API / RESOURCE MONITOR", objectName="section"))
        side.addSpacing(28)
        side.addWidget(QLabel("工作台", objectName="section"))
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list[QToolButton] = []
        for text, icon_index, page_index in (("总览 / Console", 0, 0), ("供应商 / Providers", 1, 1), ("使用说明 / Guide", 3, 2)):
            button = QToolButton()
            button.setObjectName("navButton")
            button.setText(text)
            button.setIcon(nav_icon(icon_index))
            button.setIconSize(QSize(22, 22))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setToolTip(text)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked, page=page_index: self.pages.setCurrentIndex(page))
            self.nav_group.addButton(button, page_index)
            self.nav_buttons.append(button)
            side.addWidget(button)
        self.nav_buttons[0].setChecked(True)
        side.addStretch()
        side.addWidget(QLabel("本地存储 · 手动查询", objectName="hint"))
        root.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        self.overview = OverviewPage()
        self.manager = ApiManagerPage()
        self.help_page = HelpPage()
        self.pages.addWidget(self.overview)
        self.pages.addWidget(self.manager)
        self.pages.addWidget(self.help_page)
        self.overview.add_requested.connect(self.add_api)
        self.overview.query_requested.connect(self.query_api)
        self.manager.query_requested.connect(self.query_api)
        self.manager.add_requested.connect(self.add_api)
        self.manager.delete_requested.connect(self.remove_api)
        self.manager.note_requested.connect(self.edit_note)
        self.manager.copy_button.clicked.connect(self.copy_result)
        root.addWidget(self.pages, 1)

    def refresh_all(self) -> None:
        self.manager.refresh()
        self.overview.update_data(self.cache)

    def query_api(self, identifier: str) -> None:
        if self.thread is not None:
            return
        self.manager.set_busy(True)
        self.manager.show_loading()
        self.manager.result_text = ""
        self.manager.copy_button.setText("复制结果")
        self.manager.copy_button.setEnabled(False)
        self.manager.search.clear()
        self.manager.select_identifier(identifier)
        self.pages.setCurrentWidget(self.manager)
        self.nav_buttons[1].setChecked(True)
        self.thread = QThread(self)
        self.worker = QueryWorker(identifier)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.query_finished)
        self.worker.failed.connect(self.query_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.worker_finished)
        self.thread.start()

    def query_finished(self, identifier: str, result: dict[str, Any]) -> None:
        self.cache[identifier] = {"result": result, "queried_at": now_text()}
        self.manager.show_result(result)
        self.manager.result_text = format_result(result)
        self.manager.copy_button.setEnabled(True)
        self.refresh_all()

    def query_failed(self, identifier: str, message: str) -> None:
        formatted = format_error(identifier, message)
        self.manager.show_error(formatted)
        self.manager.result_text = formatted
        self.manager.copy_button.setEnabled(True)
        self.cache[identifier] = {"result": {"key": identifier, "kind": "error", "message": message}, "queried_at": now_text()}
        self.refresh_all()

    def worker_finished(self) -> None:
        if self.thread:
            self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self.manager.set_busy(False)

    def add_api(self) -> None:
        dialog = AddApiDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                keys = add_api(dialog.record())
                if dialog.note.text().strip():
                    metadata.set_note(keys[0], dialog.note.text())
                self.refresh_all()
            except (AppError, OSError) as exc:
                QMessageBox.critical(self, "增加失败", str(exc))

    def remove_api(self, identifier: str) -> None:
        if self.thread is not None:
            return
        if QMessageBox.question(self, "确认删除", f"确定删除 {identifier} 吗？") != QMessageBox.StandardButton.Yes:
            return
        try:
            del_api(identifier)
            metadata.delete_note(identifier)
            self.cache.pop(identifier, None)
            self.refresh_all()
            self.manager.result_text = ""
            self.manager.copy_button.setEnabled(False)
            self.manager.show_error("账户已删除。选择其他账户继续查询。")
        except AppError as exc:
            QMessageBox.critical(self, "删除失败", str(exc))

    def edit_note(self, identifier):
        current = metadata.notes().get(identifier, '')
        text, accepted = QInputDialog.getText(self, "账户备注", "显示备注（留空恢复账户标识）", text=current)
        if accepted:
            try:
                metadata.set_note(identifier, text)
                self.refresh_all()
            except (AppError, OSError) as exc:
                QMessageBox.warning(self, "备注保存失败", str(exc))

    def copy_result(self) -> None:
        QApplication.clipboard().setText(self.manager.result_text)
        self.manager.copy_button.setText("已复制")

    def closeEvent(self, event: Any) -> None:
        if self.thread is not None:
            event.ignore()
            return
        event.accept()


def format_result(result: dict[str, Any]) -> str:
    provider = result["provider"]
    data = result.get("data", {})
    lines = [f"API: {result['key']}", f"状态：{dict(success='正常', warning='注意', error='异常')[result_state(result)]}", f"查询时间：{now_text()}", ""]
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
    elif result.get('kind') == 'plan_quota':
        for quota in result['quotas']:
            lines.append(f"{quota['model']}：5 小时剩余 {quota['rolling']:g}%，本周剩余 {quota['weekly']:g}%")
    elif result.get("kind") == "balance" and "balance" in result:
        lines.append(f"余额：{result['balance']} {result['currency']}")
    elif result.get("kind") == "key_usage":
        lines.append(json.dumps(data.get("data", {}), ensure_ascii=False, indent=2))
        lines.append(result["message"])
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
    """Use installed UI fonts and a palette for native dialog surfaces."""
    available = set(QFontDatabase.families())
    family = next((name for name in ("Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC") if name in available), app.font().family())
    app.setFont(QFont(family, 10))
    palette = app.palette()
    for role, color in ((QPalette.ColorRole.Window, "#1c1c1c"), (QPalette.ColorRole.Base, "#252525"), (QPalette.ColorRole.Button, "#383838"), (QPalette.ColorRole.WindowText, "#e3ddcf"), (QPalette.ColorRole.Text, "#e3ddcf"), (QPalette.ColorRole.ButtonText, "#e3ddcf")):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)


if __name__ == "__main__":
    main()
