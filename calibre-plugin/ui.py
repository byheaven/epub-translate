"""
ui.py — Calibre 插件主界面

InterfaceAction 子类：
  - 工具栏按钮 + 下拉菜单
  - "翻译选中的书" → do_translate()
  - "设置" → show_settings()
"""

import os
import tempfile
from pathlib import Path

from calibre.gui2 import error_dialog, info_dialog, question_dialog
from calibre.gui2.actions import InterfaceAction
from qt.core import (
    QDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    Qt,
)

from calibre_plugins.epub_translate.config import plugin_prefs
from calibre_plugins.epub_translate.worker import TranslationWorker

PLUGIN_ICONS = ["images/icon.png"]


class EpubTranslateAction(InterfaceAction):
    name = "Epub Translate"
    action_spec = ("翻译 EPUB", None, "将选中的书翻译为双语版本", None)
    action_add_menu = True
    action_menu_clone_qaction = "翻译选中的书"
    dont_add_to = frozenset(["context-menu-device"])
    dont_remove_from = frozenset()

    def genesis(self):
        # connect 必须在最前面，icon 加载失败不应影响功能
        self.qaction.triggered.connect(self.do_translate)

        try:
            icon = _get_plugin_icon(PLUGIN_ICONS[0])
            if icon and not icon.isNull():
                self.qaction.setIcon(icon)
        except Exception:
            pass

        # action_menu_clone_qaction 已自动把"翻译选中的书"加为第一项
        # 只需补充设置项
        try:
            menu = self.qaction.menu()
            if menu is not None:
                menu.addSeparator()
                self.create_menu_action(menu, "settings", "设置…",
                                        triggered=self.show_settings)
        except Exception:
            pass

    def initialization_complete(self):
        pass

    # ------------------------------------------------------------------ #

    def do_translate(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows:
            return error_dialog(self.gui, "未选中书籍",
                                "请先在书库中选中至少一本 EPUB 格式的书。", show=True)

        db = self.gui.current_db
        project_path = plugin_prefs["project_path"]

        # 检查项目路径
        python_exe = Path(project_path) / ".venv" / "bin" / "python"
        worker_script = Path(project_path) / "translate_worker.py"
        if not python_exe.exists():
            return error_dialog(
                self.gui, "配置错误",
                f"找不到 Python 虚拟环境：{python_exe}\n\n"
                "请在插件设置中填写正确的 epub-translate 项目路径。",
                show=True,
            )
        if not worker_script.exists():
            return error_dialog(
                self.gui, "配置错误",
                f"找不到 translate_worker.py：{worker_script}",
                show=True,
            )

        # 收集任务
        tasks = []
        skipped = []
        tmp_files = []

        model = self.gui.library_view.model()
        for row in rows:
            book_id = model.id(row)
            if not db.has_format(book_id, "EPUB", index_is_id=True):
                skipped.append(db.title(book_id, index_is_id=True))
                continue
            source_path = db.format_abspath(book_id, "EPUB", index_is_id=True)
            fd, target_path = tempfile.mkstemp(suffix=".epub", prefix="calibre_translate_")
            os.close(fd)
            tmp_files.append(target_path)
            tasks.append((book_id, source_path, target_path))

        if skipped:
            info_dialog(
                self.gui, "跳过部分书籍",
                "以下书籍没有 EPUB 格式，已跳过：\n" + "\n".join(f"  · {t}" for t in skipped),
                show=True,
            )

        if not tasks:
            return

        # 确认对话框
        titles = [db.title(bid, index_is_id=True) for bid, _, _ in tasks]
        msg = f"即将翻译以下 {len(tasks)} 本书：\n" + "\n".join(f"  · {t}" for t in titles)
        if not question_dialog(self.gui, "确认翻译", msg):
            for p in tmp_files:
                if os.path.exists(p):
                    os.remove(p)
            return

        # 启动进度对话框
        dlg = _ProgressDialog(self.gui, tasks, project_path, db)
        dlg.exec()

    def show_settings(self):
        from calibre_plugins.epub_translate.config import ConfigWidget
        from qt.core import QDialog, QDialogButtonBox, QVBoxLayout
        d = QDialog(self.gui)
        d.setWindowTitle("Epub Translate 设置")
        vl = QVBoxLayout(d)
        w = ConfigWidget()
        vl.addWidget(w)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        vl.addWidget(bb)
        if d.exec() == QDialog.DialogCode.Accepted:
            w.save_settings()


# ------------------------------------------------------------------ #

def _get_plugin_icon(icon_name: str):
    """加载插件图标。
    Calibre 的 ZipImporter 会自动将 get_icons (partial 绑定了 zip 路径) 注入
    到插件模块的全局命名空间，直接调用即可从 zip 内读取图片。
    """
    try:
        # get_icons 由 Calibre 插件加载器注入，已绑定到本插件的 zip 文件
        icon = get_icons(icon_name, 'Epub Translate')  # noqa: F821
        if icon and not icon.isNull():
            return icon
    except Exception:
        pass
    try:
        return get_icons(icon_name)  # noqa: F821
    except Exception:
        pass
    from calibre.gui2 import get_icons as _gi
    return _gi("edit_input.png")


# ------------------------------------------------------------------ #

class _ProgressDialog(QDialog):
    """翻译进度对话框（模态）。"""

    def __init__(self, parent, tasks, project_path, db):
        super().__init__(parent)
        self.setWindowTitle("正在翻译 EPUB")
        self.setMinimumWidth(480)
        self.tasks = tasks
        self.project_path = project_path
        self.db = db
        self._results = []  # [(book_id, success, msg)]
        self._build_ui()
        self._start_worker()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.status_label = QLabel("准备中…")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(120)
        layout.addWidget(self.log_view)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self.cancel_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _start_worker(self):
        self.worker = TranslationWorker(self.tasks, self.project_path, parent=self)
        self.worker.progress_changed.connect(self._on_progress)
        self.worker.status_changed.connect(self._on_status)
        self.worker.book_finished.connect(self._on_book_finished)
        self.worker.all_finished.connect(self._on_all_finished)
        self.worker.start()

    def _on_progress(self, value: float):
        self.progress_bar.setValue(int(value * 1000))

    def _on_status(self, text: str):
        self.status_label.setText(text)
        self.log_view.append(text)

    def _on_book_finished(self, book_id: int, success: bool, msg: str):
        self._results.append((book_id, success, msg))
        if success:
            self._add_to_library(book_id)
            title = self.db.title(book_id, index_is_id=True)
            self.log_view.append(f"✅ 完成：{title}")
        else:
            title = self.db.title(book_id, index_is_id=True)
            self.log_view.append(f"❌ 失败：{title}  {msg}")

    def _add_to_library(self, book_id: int):
        """将翻译后的 epub 作为新书加入书库。"""
        # 找到对应的 target_path
        target_path = None
        for (tid, _, tp) in self.tasks:
            if tid == book_id:
                target_path = tp
                break
        if not target_path or not os.path.exists(target_path):
            return

        try:
            # 从翻译后 EPUB 读取标题（epub-translator 已将中文翻译 APPEND_TEXT 到 OPF title）
            from calibre.ebooks.metadata.meta import get_metadata as get_epub_metadata
            from calibre.ebooks.metadata.book.base import Metadata
            with open(target_path, 'rb') as f:
                epub_mi = get_epub_metadata(f, stream_type='epub')

            orig_mi = self.db.get_metadata(book_id, index_is_id=True, get_cover=False)
            # 优先用翻译后 EPUB 里的标题，回退到原标题 + [双语]
            new_title = (epub_mi.title or "").strip() or f"{orig_mi.title} [双语]"
            new_mi = Metadata(new_title, orig_mi.authors)
            new_mi.tags = list(orig_mi.tags or []) + ["双语"]
            new_id = self.db.create_book_entry(new_mi)
            self.db.add_format_with_hooks(new_id, "EPUB", target_path, index_is_id=True)

            # 复制原书封面
            cover_data = self.db.cover(book_id, index_is_id=True)
            if cover_data:
                self.db.set_cover(new_id, cover_data)

            self.db.refresh_ids([new_id])
            # 刷新 GUI 书库视图
            self.parent().library_view.model().books_added(1)
        except Exception as e:
            self.log_view.append(f"  ⚠️  加入书库失败：{e}")
        finally:
            try:
                os.remove(target_path)
            except OSError:
                pass

    def _on_all_finished(self):
        self.progress_bar.setValue(1000)
        self.status_label.setText("全部翻译完成！")
        self.cancel_btn.setText("关闭")
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.accept)

        # 汇总报告
        success = sum(1 for _, ok, _ in self._results if ok)
        failed = len(self._results) - success
        self.log_view.append(f"\n── 完成 {success} 本，失败 {failed} 本 ──")

    def _on_cancel(self):
        if hasattr(self, "worker") and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        self.reject()

    def closeEvent(self, event):
        if hasattr(self, "worker") and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(event)
