"""
ui.py - Calibre plugin main UI.

EpubTranslateAction (InterfaceAction):
  - Toolbar button + dropdown menu
  - "Translate selected books" -> do_translate()
  - "Settings" -> show_settings()
"""

import os
import tempfile
from pathlib import Path

from calibre.gui2 import error_dialog, info_dialog, question_dialog
from calibre.gui2.actions import InterfaceAction
from qt.core import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QThread,
    QTimer,
    QVBoxLayout,
    Qt,
    pyqtSignal,
)

from calibre_plugins.epub_translate.config import plugin_prefs
from calibre_plugins.epub_translate.worker import TranslationWorker

PLUGIN_ICONS = ["images/icon.png"]


class EpubTranslateAction(InterfaceAction):
    name = "Epub Translate"
    action_spec = ("Translate EPUB", None, "Translate selected books into bilingual editions", None)
    action_add_menu = True
    action_menu_clone_qaction = "Translate selected books"
    dont_add_to = frozenset(["context-menu-device"])
    dont_remove_from = frozenset()

    def genesis(self):
        # Connect signal first; icon loading failure must not break functionality
        self.qaction.triggered.connect(self.do_translate)

        try:
            icon = _get_plugin_icon(PLUGIN_ICONS[0])
            if icon and not icon.isNull():
                self.qaction.setIcon(icon)
        except Exception:
            pass

        # action_menu_clone_qaction already adds "Translate selected books" as the first item;
        # we only need to append the Settings entry.
        try:
            menu = self.qaction.menu()
            if menu is not None:
                menu.addSeparator()
                self.create_menu_action(menu, "settings", "Settings...",
                                        triggered=self.show_settings)
        except Exception:
            pass

    def initialization_complete(self):
        pass

    # ------------------------------------------------------------------ #

    def do_translate(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows:
            return error_dialog(self.gui, "No books selected",
                                "Please select at least one book with an EPUB format.", show=True)

        # Ensure Python environment is ready
        from calibre_plugins.epub_translate.config import _get_venv_python
        python_exe = _get_venv_python()
        if not python_exe:
            manual = plugin_prefs.get("python_path", "").strip()
            if manual and Path(manual).exists():
                python_exe = manual
            else:
                dlg = _SetupDialog(self.gui)
                if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.was_successful():
                    return
                python_exe = _get_venv_python()
                if not python_exe:
                    return error_dialog(
                        self.gui, "Setup failed",
                        "Could not find a working Python after setup.\n\n"
                        "Please open Settings > Advanced for details or set a manual override.",
                        show=True,
                    )

        db = self.gui.current_db

        # Collect translation tasks
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
                self.gui, "Some books skipped",
                "The following books have no EPUB format and were skipped:\n"
                + "\n".join(f"  - {t}" for t in skipped),
                show=True,
            )

        if not tasks:
            return

        # Confirmation dialog
        titles = [db.title(bid, index_is_id=True) for bid, _, _ in tasks]
        msg = f"About to translate {len(tasks)} book(s):\n" + "\n".join(f"  - {t}" for t in titles)
        if not question_dialog(self.gui, "Confirm translation", msg):
            for p in tmp_files:
                if os.path.exists(p):
                    os.remove(p)
            return

        dlg = _ProgressDialog(self.gui, tasks, db)
        dlg.exec()

    def show_settings(self):
        from calibre_plugins.epub_translate.config import ConfigWidget
        d = QDialog(self.gui)
        d.setWindowTitle("Epub Translate Settings")
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
    """Load the plugin icon from within its zip file.

    Calibre's ZipImporter injects a partially-applied get_icons() (bound to
    the plugin's zip path) into each plugin module's global namespace, so we
    call it directly rather than importing from calibre.gui2.
    """
    try:
        icon = get_icons(icon_name, "Epub Translate")  # noqa: F821
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


class _SetupThread(QThread):
    """Background thread that runs setup_venv()."""
    status_changed = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)   # success, error_message

    def run(self):
        from calibre_plugins.epub_translate.config import setup_venv
        try:
            setup_venv(on_status=lambda msg: self.status_changed.emit(msg))
            self.finished_signal.emit(True, "")
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class _SetupDialog(QDialog):
    """Modal progress dialog for first-time venv setup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Setting Up epub-translator")
        self.setMinimumWidth(440)
        self._success = False
        self._build_ui()
        self._start_setup()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        intro = QLabel(
            "epub-translator is not installed yet.\n"
            "Setting up a Python environment automatically — this only happens once."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.status_label = QLabel("Initializing...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)   # indeterminate
        layout.addWidget(self.progress_bar)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self.cancel_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _start_setup(self):
        self._thread = _SetupThread(self)
        self._thread.status_changed.connect(self.status_label.setText)
        self._thread.finished_signal.connect(self._on_finished)
        self._thread.start()

    def _on_finished(self, success: bool, error: str):
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        if success:
            self._success = True
            self.status_label.setText("Setup complete!")
            self.cancel_btn.setText("Close")
            self.cancel_btn.clicked.disconnect()
            self.cancel_btn.clicked.connect(self.accept)
            QTimer.singleShot(800, self.accept)
        else:
            self.status_label.setText(f"Setup failed:\n{error}")
            self.cancel_btn.setText("Close")
            self.cancel_btn.clicked.disconnect()
            self.cancel_btn.clicked.connect(self.reject)

    def _on_cancel(self):
        if hasattr(self, "_thread") and self._thread.isRunning():
            self._thread.terminate()
            self._thread.wait(2000)
        self.reject()

    def was_successful(self) -> bool:
        return self._success


# ------------------------------------------------------------------ #


class _ProgressDialog(QDialog):
    """Modal progress dialog shown while books are being translated."""

    def __init__(self, parent, tasks, db):
        super().__init__(parent)
        self.setWindowTitle("Translating EPUB")
        self.setMinimumWidth(480)
        self.tasks = tasks
        self.db = db
        self._results = []  # [(book_id, success, msg)]
        self._build_ui()
        self._start_worker()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.status_label = QLabel("Preparing...")
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

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self.cancel_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _start_worker(self):
        self.worker = TranslationWorker(self.tasks, parent=self)
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
        title = self.db.title(book_id, index_is_id=True)
        if success:
            self._add_to_library(book_id)
            self.log_view.append(f"Done: {title}")
        else:
            self.log_view.append(f"Failed: {title}  {msg}")

    def _add_to_library(self, book_id: int):
        """Add the translated EPUB as a new library entry (original book is untouched)."""
        target_path = None
        for (tid, _, tp) in self.tasks:
            if tid == book_id:
                target_path = tp
                break
        if not target_path or not os.path.exists(target_path):
            return

        try:
            # Read title from translated EPUB — epub-translator appends the
            # translated title via APPEND_TEXT mode in the OPF <dc:title> field.
            from calibre.ebooks.metadata.meta import get_metadata as get_epub_metadata
            from calibre.ebooks.metadata.book.base import Metadata
            with open(target_path, "rb") as f:
                epub_mi = get_epub_metadata(f, stream_type="epub")

            orig_mi = self.db.get_metadata(book_id, index_is_id=True, get_cover=False)
            new_title = (epub_mi.title or "").strip() or f"{orig_mi.title} [Bilingual]"
            new_mi = Metadata(new_title, orig_mi.authors)
            new_mi.tags = list(orig_mi.tags or []) + ["bilingual"]
            new_id = self.db.create_book_entry(new_mi)
            self.db.add_format_with_hooks(new_id, "EPUB", target_path, index_is_id=True)

            # Copy cover from the original book
            cover_data = self.db.cover(book_id, index_is_id=True)
            if cover_data:
                self.db.set_cover(new_id, cover_data)

            self.db.refresh_ids([new_id])
            self.parent().library_view.model().books_added(1)
        except Exception as e:
            self.log_view.append(f"  Warning: failed to add to library: {e}")
        finally:
            try:
                os.remove(target_path)
            except OSError:
                pass

    def _on_all_finished(self):
        self.progress_bar.setValue(1000)
        self.status_label.setText("All translations complete!")
        self.cancel_btn.setText("Close")
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.accept)

        success = sum(1 for _, ok, _ in self._results if ok)
        failed = len(self._results) - success
        self.log_view.append(f"\n-- {success} succeeded, {failed} failed --")

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
