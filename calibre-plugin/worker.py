"""
worker.py - QThread wrapper around the translate_worker.py subprocess.

Signals:
  progress_changed(float)        - overall translation progress 0.0~1.0
  status_changed(str)            - status text update
  book_finished(int, bool, str)  - (book_id, success, message)
  all_finished()                 - all books have been processed
"""

import json
import os
import subprocess
from pathlib import Path

from qt.core import QThread, pyqtSignal


class TranslationWorker(QThread):
    progress_changed = pyqtSignal(float)          # overall progress 0.0~1.0
    status_changed = pyqtSignal(str)              # status text
    book_finished = pyqtSignal(int, bool, str)    # book_id, success, message
    all_finished = pyqtSignal()

    def __init__(self, tasks: list[tuple[int, str, str]], project_path: str, parent=None):
        """
        tasks: [(book_id, source_epub_path, target_epub_path), ...]
        project_path: root directory of the epub-translate project (contains .venv and config.json)
        """
        super().__init__(parent)
        self.tasks = tasks
        self.project_path = Path(project_path)
        self._proc = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.kill()

    def run(self):
        total = len(self.tasks)
        python_exe = self.project_path / ".venv" / "bin" / "python"
        worker_script = self.project_path / "translate_worker.py"
        config_path = self.project_path / "config.json"

        for idx, (book_id, source_path, target_path) in enumerate(self.tasks):
            if self._cancelled:
                break

            book_name = Path(source_path).stem
            self.status_changed.emit(f"Translating book {idx + 1}/{total}: {book_name}")

            cmd = [
                str(python_exe),
                str(worker_script),
                "--source", source_path,
                "--target", target_path,
                "--config", str(config_path),
            ]

            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )
            except FileNotFoundError as e:
                self.book_finished.emit(book_id, False, f"Failed to start worker: {e}")
                continue

            book_progress = 0.0
            success = False
            error_msg = ""

            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")

                if msg_type == "progress":
                    book_progress = float(msg.get("value", 0.0))
                    # overall = (completed books + current book progress) / total books
                    overall = (idx + book_progress) / total
                    self.progress_changed.emit(overall)

                elif msg_type == "error":
                    if msg.get("critical"):
                        error_msg = msg.get("message", "Unknown error")

                elif msg_type == "done":
                    success = bool(msg.get("success"))

                elif msg_type == "stats":
                    in_tok = msg.get("input_tokens", 0)
                    out_tok = msg.get("output_tokens", 0)
                    cached = msg.get("cached_tokens", 0)
                    self.status_changed.emit(
                        f"Done: {book_name}  "
                        f"Tokens in {in_tok:,} (cached {cached:,}) / out {out_tok:,}"
                    )

            self._proc.wait()

            if not success and not error_msg:
                stderr = self._proc.stderr.read()
                error_msg = stderr.strip()[:200] if stderr.strip() else "Subprocess exited unexpectedly"

            self.book_finished.emit(book_id, success, error_msg)

            # mark this book as fully complete in the overall progress bar
            self.progress_changed.emit((idx + 1) / total)

        self.all_finished.emit()
