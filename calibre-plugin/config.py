"""
config.py - Calibre plugin configuration panel.

Settings are persisted via Calibre's JSONConfig mechanism.
Keys mirror those in config.json so they stay consistent.
"""

from calibre.utils.config import JSONConfig
from qt.core import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    Qt,
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
plugin_prefs.defaults["project_path"] = "/Users/yubai/epub-translate"
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
plugin_prefs.defaults["use_config_json"] = True  # True = read project_path/config.json


def get_effective_config() -> dict:
    """Return the config dict passed to translate_worker.py.

    When use_config_json is True, reads project_path/config.json directly.
    Otherwise builds the dict from plugin prefs.
    """
    import json
    from pathlib import Path

    if plugin_prefs["use_config_json"]:
        config_path = Path(plugin_prefs["project_path"]) / "config.json"
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                return json.load(f)

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


class ConfigWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Project path
        path_group = QGroupBox("epub-translate Project")
        path_form = QFormLayout(path_group)

        self.project_path = QLineEdit()
        self.project_path.setPlaceholderText("/Users/yubai/epub-translate")
        path_form.addRow("Project path:", self.project_path)

        note = QLabel("The plugin uses .venv/bin/python and config.json from this directory.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        path_form.addRow("", note)

        layout.addWidget(path_group)

        # Translation settings
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

        # API overrides (only active when the group is checked)
        api_group = QGroupBox("API Settings (overrides config.json llm section)")
        api_group.setCheckable(True)
        api_group.setChecked(False)
        api_form = QFormLayout(api_group)
        self.api_group = api_group

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
        layout.addStretch()

    def _load_values(self):
        self.project_path.setText(plugin_prefs["project_path"])

        lang_value = plugin_prefs["target_language"]
        for i, (_, value) in enumerate(LANGUAGE_OPTIONS):
            if value == lang_value:
                self.target_language.setCurrentIndex(i)
                break

        self.concurrency.setValue(plugin_prefs["concurrency"])
        self.user_prompt.setPlainText(plugin_prefs["user_prompt"])
        self.llm_key.setText(plugin_prefs["llm_key"])
        self.llm_url.setText(plugin_prefs["llm_url"])
        self.llm_model.setText(plugin_prefs["llm_model"])

        if plugin_prefs["llm_key"]:
            self.api_group.setChecked(True)

    def save_settings(self):
        plugin_prefs["project_path"] = self.project_path.text().strip()
        plugin_prefs["target_language"] = self.target_language.currentData()
        plugin_prefs["concurrency"] = self.concurrency.value()
        plugin_prefs["user_prompt"] = self.user_prompt.toPlainText().strip()

        if self.api_group.isChecked():
            plugin_prefs["llm_key"] = self.llm_key.text().strip()
            plugin_prefs["llm_url"] = self.llm_url.text().strip()
            plugin_prefs["llm_model"] = self.llm_model.text().strip()
            plugin_prefs["use_config_json"] = False
        else:
            plugin_prefs["use_config_json"] = True
