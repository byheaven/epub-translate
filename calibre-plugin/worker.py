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


def _extract_bundled_worker() -> str | None:
    """
    Extract translate_worker.py from inside the plugin ZIP to a writable
    directory so it can be launched as a subprocess.

    Calibre injects get_resources() into every plugin module's namespace;
    it reads raw bytes from the zip without requiring the file to exist on disk.
    Returns the path to the extracted file, or None if extraction fails.
    """
    try:
        from calibre.utils.config import config_dir
        dest_dir = os.path.join(config_dir, "plugins", "epub_translate")
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, "translate_worker.py")
        data = get_resources("translate_worker.py")  # noqa: F821  (injected by Calibre)
        if data:
            with open(dest, "wb") as f:
                f.write(data)
            return dest
    except Exception:
        pass
    return None


class TranslationWorker(QThread):
    progress_changed = pyqtSignal(float)          # overall progress 0.0~1.0
    status_changed = pyqtSignal(str)              # status text
    book_finished = pyqtSignal(int, bool, str)    # book_id, success, message
    all_finished = pyqtSignal()

    def __init__(self, tasks: list[tuple[int, str, str]], parent=None):
        """
        tasks: [(book_id, source_epub_path, target_epub_path), ...]
        """
        super().__init__(parent)
        self.tasks = tasks
        self._proc = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.kill()

    def run(self):
        import json as _json
        import tempfile
        from calibre_plugins.epub_translate.config import (
            _get_venv_python, plugin_prefs, get_effective_config
        )

        total = len(self.tasks)
        python_exe = _get_venv_python() or plugin_prefs.get("python_path", "").strip()

        # Write the effective config to a temp file so the worker subprocess can read it.
        # This works whether the user filled in the API fields directly or pointed to a config.json.
        try:
            effective_config = get_effective_config()
            tmp_cfg = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            )
            _json.dump(effective_config, tmp_cfg, ensure_ascii=False)
            tmp_cfg.close()
            config_path = tmp_cfg.name
        except Exception as e:
            self.status_changed.emit(f"Failed to write config: {e}")
            self.all_finished.emit()
            return

        try:
            for idx, (book_id, source_path, target_path) in enumerate(self.tasks):
                if self._cancelled:
                    break

                book_name = Path(source_path).stem
                self.status_changed.emit(f"Translating book {idx + 1}/{total}: {book_name}")

                # Prefer the copy bundled inside the plugin ZIP (auto-extracted);
                # fall back to a copy alongside this file for development use.
                worker_script = _extract_bundled_worker() or str(
                    Path(__file__).parent / "translate_worker.py"
                )

                cmd = [
                    python_exe,
                    worker_script,
                    "--source", source_path,
                    "--target", target_path,
                    "--config", config_path,
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
                        overall = (idx + book_progress) / total
                        self.progress_changed.emit(overall)

                    elif msg_type == "error":
                        if msg.get("critical"):
                            error_msg = msg.get("message", "Unknown error")
                        else:
                            self.status_changed.emit(f"  {msg.get('message', '')}")

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
                self.progress_changed.emit((idx + 1) / total)

        finally:
            try:
                os.unlink(config_path)
            except OSError:
                pass

        self.all_finished.emit()
