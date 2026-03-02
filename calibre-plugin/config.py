"""
config.py - Calibre plugin configuration panel.

Settings are persisted via Calibre's JSONConfig mechanism.
"""

import os
import subprocess
import sys
from pathlib import Path

from calibre.utils.config import JSONConfig
from qt.core import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Stored at ~/.config/calibre/plugins/epub_translate.json
plugin_prefs = JSONConfig("plugins/epub_translate")

LANGUAGE_OPTIONS = [
    ("Simplified Chinese", "SIMPLIFIED_CHINESE"),
    ("Traditional Chinese", "TRADITIONAL_CHINESE"),
    ("English", "ENGLISH"),
    ("Japanese", "JAPANESE"),
    ("Korean", "KOREAN"),
    ("French", "FRENCH"),
    ("German", "GERMAN"),
    ("Spanish", "SPANISH"),
    ("Russian", "RUSSIAN"),
    ("Portuguese", "PORTUGUESE"),
]

# Defaults
plugin_prefs.defaults["python_path"] = ""          # manual override; empty = use auto-detected venv
plugin_prefs.defaults["target_language"] = "SIMPLIFIED_CHINESE"
plugin_prefs.defaults["concurrency"] = 3
plugin_prefs.defaults["user_prompt"] = ""
plugin_prefs.defaults["llm_key"] = ""
plugin_prefs.defaults["llm_url"] = "https://api.deepseek.com"
plugin_prefs.defaults["llm_model"] = "deepseek-chat"
plugin_prefs.defaults["llm_token_encoding"] = "o200k_base"
plugin_prefs.defaults["llm_timeout"] = 120.0
plugin_prefs.defaults["llm_top_p"] = 0.6
plugin_prefs.defaults["llm_temperature"] = 0.85
plugin_prefs.defaults["llm_retry_times"] = 5
plugin_prefs.defaults["llm_retry_interval"] = 6.0


# ── venv auto-setup helpers ───────────────────────────────────────────────────


def _get_plugin_data_dir() -> Path:
    """Return the plugin's private data directory (created if absent)."""
    from calibre.utils.config import config_dir
    d = Path(config_dir) / "plugins" / "epub_translate"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_venv_python() -> "str | None":
    """Return the venv python path if the venv exists and epub_translator is importable."""
    venv_dir = _get_plugin_data_dir() / "venv"
    if sys.platform == "win32":
        python = venv_dir / "Scripts" / "python.exe"
    else:
        python = venv_dir / "bin" / "python"
    if not python.exists():
        return None
    try:
        r = subprocess.run(
            [str(python), "-c", "import epub_translator"],
            capture_output=True, timeout=10,
        )
        if r.returncode == 0:
            return str(python)
    except Exception:
        pass
    return None


def _find_system_python() -> "str | None":
    """Search for a system Python >=3.10 to use as the venv base.

    We prefer version-specific binaries (3.13, 3.12, 3.11) over the generic
    'python3', because the generic name may resolve to a very new release that
    epub-translator does not yet support.  The actual compatibility check is
    left to pip at install time, so this function never needs updating when
    epub-translator raises or lowers its Python requirements.
    """
    import shutil

    if sys.platform == "win32":
        candidates = [
            "python3.13", "python3.12", "python3.11", "python3.10",
            "python", "python3", "py",
        ]
    else:
        candidates = [
            # Prefer stable, well-supported releases first
            "python3.13",
            "python3.12",
            "python3.11",
            "python3.10",
            "/opt/homebrew/bin/python3.13",
            "/opt/homebrew/bin/python3.12",
            "/opt/homebrew/bin/python3.11",
            "/opt/homebrew/bin/python3.10",
            "/usr/local/bin/python3.13",
            "/usr/local/bin/python3.12",
            "/usr/local/bin/python3.11",
            "/usr/local/bin/python3.10",
            # Generic fallback — version unknown until checked
            "python3",
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
            "python",
        ]

    check_script = (
        "import sys; assert sys.version_info >= (3, 10), "
        "f'too old: {sys.version}'; print('ok')"
    )

    for name in candidates:
        if not os.path.isabs(name):
            full = shutil.which(name)
            if not full:
                continue
        else:
            full = name
            if not os.path.exists(full):
                continue

        # On Windows, "py" is the launcher — pass "-3" to select Python 3
        cmd = [full, "-3", "-c", check_script] if name == "py" else [full, "-c", check_script]

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                if name == "py":
                    path_r = subprocess.run(
                        [full, "-3", "-c", "import sys; print(sys.executable)"],
                        capture_output=True, text=True, timeout=10,
                    )
                    if path_r.returncode == 0:
                        return path_r.stdout.strip()
                return full
        except Exception:
            continue

    return None


def setup_venv(on_status=None) -> None:
    """Create the plugin venv and pip-install epub-translator.

    Calls on_status(str) for progress messages.
    Raises RuntimeError on failure.
    """
    def _status(msg: str):
        if on_status:
            on_status(msg)

    _status("Finding system Python 3.10+...")
    system_python = _find_system_python()
    if not system_python:
        raise RuntimeError(
            "No Python 3.10+ found on this system.\n"
            "Please install Python 3.13 or 3.12 from https://www.python.org/downloads/"
        )
    _status(f"Found Python: {system_python}")

    venv_dir = _get_plugin_data_dir() / "venv"
    _status(f"Creating virtual environment at {venv_dir} ...")
    try:
        r = subprocess.run(
            [system_python, "-m", "venv", str(venv_dir)],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            raise RuntimeError(f"venv creation failed:\n{r.stderr or r.stdout}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("venv creation timed out (60 s).")

    if sys.platform == "win32":
        pip = venv_dir / "Scripts" / "pip"
        python = venv_dir / "Scripts" / "python.exe"
    else:
        pip = venv_dir / "bin" / "pip"
        python = venv_dir / "bin" / "python"

    _status("Installing epub-translator (this may take a minute)...")
    try:
        r = subprocess.run(
            [str(pip), "install", "--upgrade", "epub-translator"],
            capture_output=True, text=True, timeout=300,
        )
        if r.returncode != 0:
            pip_output = (r.stderr or r.stdout)
            # Detect Python version incompatibility and give an actionable message
            if "Requires-Python" in pip_output or "No matching distribution" in pip_output:
                import re
                # Extract the constraint from lines like "0.1.9 Requires-Python >=3.11, <3.14"
                match = re.search(r"Requires-Python\s+([^\n;]+)", pip_output)
                constraint = match.group(1).strip() if match else "unknown"
                py_ver = subprocess.run(
                    [str(python), "-c", "import sys; print(sys.version.split()[0])"],
                    capture_output=True, text=True,
                ).stdout.strip()
                import shutil as _shutil
                _shutil.rmtree(str(venv_dir), ignore_errors=True)
                raise RuntimeError(
                    f"Python {py_ver} is not compatible with epub-translator "
                    f"(requires {constraint}).\n\n"
                    "Please install a compatible Python version "
                    "(e.g. 3.13 or 3.12) from https://www.python.org/downloads/\n"
                    "Then click Translate again."
                )
            raise RuntimeError(f"pip install failed:\n{pip_output[-800:]}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("pip install timed out (5 min).")

    _status("Verifying installation...")
    r = subprocess.run(
        [str(python), "-c",
         "import importlib.metadata, epub_translator; "
         "print(importlib.metadata.version('epub-translator'))"],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0:
        detail = (r.stderr or r.stdout).strip()[-600:]
        raise RuntimeError(f"epub-translator installed but import failed:\n{detail}")
    _status(f"epub-translator {r.stdout.strip()} installed successfully.")


# ── Config helpers ────────────────────────────────────────────────────────────


def get_effective_config() -> dict:
    """Build the config dict from plugin pref fields."""
    return {
        "llm": {
            "key": plugin_prefs["llm_key"],
            "url": plugin_prefs["llm_url"],
            "model": plugin_prefs["llm_model"],
            "token_encoding": plugin_prefs["llm_token_encoding"],
            "timeout": plugin_prefs["llm_timeout"],
            "top_p": plugin_prefs["llm_top_p"],
            "temperature": plugin_prefs["llm_temperature"],
            "retry_times": plugin_prefs["llm_retry_times"],
            "retry_interval_seconds": plugin_prefs["llm_retry_interval"],
        },
        "target_language": plugin_prefs["target_language"],
        "concurrency": plugin_prefs["concurrency"],
        "user_prompt": plugin_prefs["user_prompt"] or None,
    }


# ── Settings UI ───────────────────────────────────────────────────────────────


class ConfigWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- API Settings ---
        api_group = QGroupBox("API Settings")
        api_form = QFormLayout(api_group)

        self.llm_key = QLineEdit()
        self.llm_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.llm_key.setPlaceholderText("sk-...")
        api_form.addRow("API Key:", self.llm_key)

        self.llm_url = QLineEdit()
        self.llm_url.setPlaceholderText("https://api.deepseek.com")
        api_form.addRow("API URL:", self.llm_url)

        self.llm_model = QLineEdit()
        self.llm_model.setPlaceholderText("deepseek-chat")
        api_form.addRow("Model:", self.llm_model)

        layout.addWidget(api_group)

        # --- Translation Settings ---
        trans_group = QGroupBox("Translation Settings")
        trans_form = QFormLayout(trans_group)

        self.target_language = QComboBox()
        for label, value in LANGUAGE_OPTIONS:
            self.target_language.addItem(label, value)
        trans_form.addRow("Target language:", self.target_language)

        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 20)
        self.concurrency.setSuffix(" concurrent requests")
        trans_form.addRow("Concurrency:", self.concurrency)

        self.user_prompt = QTextEdit()
        self.user_prompt.setMaximumHeight(80)
        self.user_prompt.setPlaceholderText("(Optional) Custom instructions appended to the system prompt")
        trans_form.addRow("User prompt:", self.user_prompt)

        layout.addWidget(trans_group)

        # --- Advanced ---
        adv_group = QGroupBox("Advanced")
        adv_form = QFormLayout(adv_group)

        python_row = QHBoxLayout()
        self.python_display = QLineEdit()
        self.python_display.setReadOnly(True)
        python_row.addWidget(self.python_display, 1)
        self.reinstall_btn = QPushButton("Reinstall")
        self.reinstall_btn.setFixedWidth(80)
        self.reinstall_btn.clicked.connect(self._on_reinstall)
        python_row.addWidget(self.reinstall_btn)
        adv_form.addRow("Python:", python_row)

        self.python_path = QLineEdit()
        self.python_path.setPlaceholderText("(optional) /path/to/python — overrides auto-detected venv")
        adv_form.addRow("Override:", self.python_path)

        self.adv_status = QLineEdit()
        self.adv_status.setReadOnly(True)
        adv_form.addRow("Status:", self.adv_status)

        layout.addWidget(adv_group)
        layout.addStretch()

        self._refresh_venv_status()

    def _refresh_venv_status(self):
        """Update the Python path display and status label in the Advanced section."""
        venv_python = _get_venv_python()
        if venv_python:
            self.python_display.setText(f"auto: {venv_python}")
            try:
                r = subprocess.run(
                    [venv_python, "-c",
                     "import sys, importlib.metadata; "
                     "print(sys.version.split()[0], "
                     "importlib.metadata.version('epub-translator'))"],
                    capture_output=True, text=True, timeout=10,
                )
                if r.returncode == 0:
                    parts = r.stdout.strip().split()
                    py_ver = parts[0] if parts else "?"
                    pkg_ver = parts[1] if len(parts) > 1 else "?"
                    self.adv_status.setText(f"OK — Python {py_ver}, epub-translator {pkg_ver}")
                    self.adv_status.setStyleSheet("QLineEdit { color: green; }")
                else:
                    self.adv_status.setText("Warning: import check failed")
                    self.adv_status.setStyleSheet("QLineEdit { color: orange; }")
            except Exception:
                self.adv_status.setText("Warning: could not check version")
                self.adv_status.setStyleSheet("QLineEdit { color: orange; }")
        else:
            manual = plugin_prefs.get("python_path", "").strip()
            if manual:
                self.python_display.setText(f"manual: {manual}")
            else:
                self.python_display.setText("Not configured — click Translate to auto-install")
            self.adv_status.setText("Venv not set up yet")
            self.adv_status.setStyleSheet("QLineEdit { color: gray; }")

    def _on_reinstall(self):
        """Remove the managed venv so it will be recreated on next Translate."""
        import shutil as _shutil
        venv_dir = _get_plugin_data_dir() / "venv"
        if venv_dir.exists():
            try:
                _shutil.rmtree(str(venv_dir))
            except Exception as e:
                self.adv_status.setText(f"Failed to remove venv: {e}")
                self.adv_status.setStyleSheet("QLineEdit { color: red; }")
                return
        self.python_display.setText("Not configured — venv removed")
        self.adv_status.setText("Venv removed. Click Translate to reinstall.")
        self.adv_status.setStyleSheet("QLineEdit { color: orange; }")

    def _load_values(self):
        self.python_path.setText(plugin_prefs["python_path"])
        self.llm_key.setText(plugin_prefs["llm_key"])
        self.llm_url.setText(plugin_prefs["llm_url"])
        self.llm_model.setText(plugin_prefs["llm_model"])

        lang_value = plugin_prefs["target_language"]
        for i, (_, value) in enumerate(LANGUAGE_OPTIONS):
            if value == lang_value:
                self.target_language.setCurrentIndex(i)
                break

        self.concurrency.setValue(plugin_prefs["concurrency"])
        self.user_prompt.setPlainText(plugin_prefs["user_prompt"])

    def save_settings(self):
        plugin_prefs["python_path"] = self.python_path.text().strip()
        plugin_prefs["llm_key"] = self.llm_key.text().strip()
        plugin_prefs["llm_url"] = self.llm_url.text().strip()
        plugin_prefs["llm_model"] = self.llm_model.text().strip()
        plugin_prefs["target_language"] = self.target_language.currentData()
        plugin_prefs["concurrency"] = self.concurrency.value()
        plugin_prefs["user_prompt"] = self.user_prompt.toPlainText().strip()
