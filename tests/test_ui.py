import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import QEventLoop, QTimer
from script import menu, util


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        menu.load_fonts(cls.app)
        cls.app.setStyleSheet((Path(menu.__file__).parent / 'ui/styles.qss').read_text(encoding='utf-8'))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root_patch = patch.object(util, 'CONFIG_ROOT', Path(self.temp.name))
        self.root_patch.start()
        util.write_api('deepseek', 'main', 'test-only')
        self.window = menu.MainWindow(auto_query_codex=False)
        self.window.show()
        self.result = {'key': 'deepseek/main', 'provider': 'deepseek', 'kind': 'balance', 'data': {'is_available': True, 'balance_infos': [{'currency': 'CNY', 'total_balance': '12.50'}]}}

    def tearDown(self):
        self.wait_worker()
        self.window.close()
        self.root_patch.stop()
        self.temp.cleanup()

    def wait_worker(self):
        deadline = time.monotonic() + 3
        while self.window.thread is not None and time.monotonic() < deadline:
            loop = QEventLoop()
            QTimer.singleShot(10, loop.quit)
            loop.exec()
        self.assertIsNone(self.window.thread)

    @patch('script.menu.select_api')
    def test_async_query_navigation_copy_and_selection(self, query):
        query.return_value = self.result
        self.window.manager.select_identifier('deepseek/main')
        self.window.manager.query_button.click()
        self.wait_worker()
        self.assertEqual(self.window.pages.currentWidget(), self.window.manager)
        self.assertTrue(self.window.nav_buttons[1].isChecked())
        self.assertEqual(self.window.manager.selected(), 'deepseek/main')
        self.window.copy_result()
        self.assertIn('12.50', self.app.clipboard().text())
        self.assertTrue(self.window.manager.query_button.isEnabled())
        self.assertEqual(self.window.overview.healthy.value_label.text(), '1')

    @patch('script.menu.select_api')
    def test_failure_replaces_cached_success(self, query):
        self.window.query_finished('deepseek/main', self.result)
        query.side_effect = util.AppError('模拟网络超时')
        self.window.query_api('deepseek/main')
        self.wait_worker()
        self.assertEqual(self.window.overview.healthy.value_label.text(), '0')
        self.assertIn('模拟网络超时', self.window.manager.result_text)
        self.assertTrue(self.window.manager.query_button.isEnabled())

    @patch('script.menu.select_api')
    def test_overview_query_updates_in_place(self, query):
        query.return_value = self.result
        self.window.pages.setCurrentWidget(self.window.overview)
        self.window.query_api('deepseek/main', stay_on_overview=True)
        self.wait_worker()
        self.assertEqual(self.window.pages.currentWidget(), self.window.overview)
        self.assertEqual(self.window.cache['deepseek/main']['result']['kind'], 'balance')

    def test_overview_reflows_and_collapses_header(self):
        util.write_api('xiaomi_mimo', 'win10', 'test-only')
        util.write_api('zhipu', 'win10', 'test-only')
        self.window.refresh_all()
        self.window.resize(1050, 800)
        self.app.processEvents()
        overview = self.window.overview
        self.assertEqual(overview._column_count(), 2)
        column_hosts = [overview.cards_layout.itemAt(index).widget() for index in range(overview.cards_layout.count())]
        self.assertEqual(sorted(host.layout().count() for host in column_hosts), [2, 2])
        self.assertTrue(all(overview.cards_layout.getItemPosition(index)[2:] == (1, 1)
                            for index in range(overview.cards_layout.count())))
        self.window.resize(1500, 800)
        self.app.processEvents()
        self.assertEqual(overview._column_count(), 3)
        self.assertEqual(sum(overview.cards_layout.itemAt(index).widget().layout().count()
                             for index in range(overview.cards_layout.count())), 4)
        overview._scroll_changed(30)
        self.assertFalse(overview.hero.isVisible())
        overview._scroll_changed(0)
        self.assertTrue(overview.hero.isVisible())

    def test_result_replacement_hides_previous_content(self):
        view = self.window.manager.result_view
        view.render(self.result)
        view.error('查询失败')
        texts = [w.text() for w in view.findChildren(QLabel) if w.isVisibleTo(view)]
        self.assertEqual(texts, ['查询失败'])

    def test_usage_thresholds_and_unavailable_account(self):
        self.result['data']['is_available'] = False
        self.assertEqual(menu.result_state(self.result), 'error')
        result = {'kind': 'usage', 'data': {key: {'percent': 95} for key in ['rolling', 'weekly', 'monthly']}}
        self.assertEqual(menu.result_state(result), 'error')
        self.assertIn('状态：异常', menu.format_result(self.result))

    def test_provider_tree_note_edit_and_search(self):
        self.window.manager.select_identifier('deepseek/main')
        with patch('script.menu.QInputDialog.getText', return_value=('主力开发', True)):
            self.window.manager.note_button.click()
        self.window.manager.search.setText('主力')
        group = self.window.manager.list.topLevelItem(0)
        self.assertEqual(group.text(0), 'DeepSeek')
        self.assertEqual(group.child(0).text(0), '主力开发')
        self.assertEqual(self.window.manager.selected(), 'deepseek/main')

    def test_add_dialog_custom_endpoint_validation(self):
        dialog = menu.AddApiDialog(self.window)
        dialog.provider.setCurrentIndex(dialog.provider.findData('custom'))
        dialog.name.setText('proxy')
        dialog.key.setText('test-only')
        dialog.base.setText('http://example.org/v1')
        dialog.accept()
        self.assertEqual(dialog.result(), 0)
        dialog.base.setText('https://example.org/v1')
        dialog.accept()
        self.assertEqual(dialog.result(), 1)
        self.assertEqual(dialog.record()['custom']['base_url'], 'https://example.org/v1')


if __name__ == '__main__':
    unittest.main()
