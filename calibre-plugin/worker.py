"""
worker.py — QThread 封装子进程调用 translate_worker.py

信号：
  progress_changed(float)           — 当前书的翻译进度 0.0~1.0
  status_changed(str)               — 状态文本更新
  book_finished(int, bool, str)     — (book_id, success, message)
  all_finished()                    — 所有书翻译完毕
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from qt.core import QThread, pyqtSignal


class TranslationWorker(QThread):
    progress_changed = pyqtSignal(float)   # 整体进度 0.0~1.0
    status_changed = pyqtSignal(str)       # 状态文本
    book_finished = pyqtSignal(int, bool, str)  # book_id, success, msg
    all_finished = pyqtSignal()

    def __init__(self, tasks: list[tuple[int, str, str]], project_path: str, parent=None):
        """
        tasks: [(book_id, source_epub_path, target_epub_path), ...]
        project_path: epub-translate 项目根目录（含 .venv 和 config.json）
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
            self.status_changed.emit(f"正在翻译第 {idx + 1}/{total} 本：{book_name}")

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
                self.book_finished.emit(book_id, False, f"无法启动 worker: {e}")
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
                    # 整体进度 = (已完成书数 + 当前书进度) / 总书数
                    overall = (idx + book_progress) / total
                    self.progress_changed.emit(overall)

                elif msg_type == "error":
                    if msg.get("critical"):
                        error_msg = msg.get("message", "未知错误")

                elif msg_type == "done":
                    success = bool(msg.get("success"))

                elif msg_type == "stats":
                    in_tok = msg.get("input_tokens", 0)
                    out_tok = msg.get("output_tokens", 0)
                    cached = msg.get("cached_tokens", 0)
                    self.status_changed.emit(
                        f"完成：{book_name}  "
                        f"Token 输入 {in_tok:,}（缓存 {cached:,}）/ 输出 {out_tok:,}"
                    )

            self._proc.wait()

            if not success and not error_msg:
                stderr = self._proc.stderr.read()
                error_msg = stderr.strip()[:200] if stderr.strip() else "子进程异常退出"

            self.book_finished.emit(book_id, success, error_msg)

            # 更新整体进度到该书完成
            self.progress_changed.emit((idx + 1) / total)

        self.all_finished.emit()
