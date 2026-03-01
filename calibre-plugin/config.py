"""
config.py — Calibre 插件配置面板

使用 calibre JSONConfig 持久化存储，key 与 config.json 保持一致。
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

# 插件配置存储（~/.config/calibre/plugins/epub_translate.json）
plugin_prefs = JSONConfig("plugins/epub_translate")

LANGUAGE_OPTIONS = [
    ("简体中文", "SIMPLIFIED_CHINESE"),
    ("繁體中文", "TRADITIONAL_CHINESE"),
    ("English", "ENGLISH"),
    ("日本語", "JAPANESE"),
    ("한국어", "KOREAN"),
    ("Français", "FRENCH"),
    ("Deutsch", "GERMAN"),
    ("Español", "SPANISH"),
    ("Русский", "RUSSIAN"),
    ("Português", "PORTUGUESE"),
]

# 默认值
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
plugin_prefs.defaults["use_config_json"] = True  # True = 读取 project_path/config.json


def get_effective_config() -> dict:
    """返回用于 translate_worker.py 的 config dict。
    如果 use_config_json=True，直接读取 project_path/config.json，
    否则从插件配置构建。
    """
    import json
    from pathlib import Path

    if plugin_prefs["use_config_json"]:
        config_path = Path(plugin_prefs["project_path"]) / "config.json"
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                return json.load(f)

    # 从插件配置构建
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

        # === 项目路径 ===
        path_group = QGroupBox("epub-translate 项目")
        path_form = QFormLayout(path_group)

        self.project_path = QLineEdit()
        self.project_path.setPlaceholderText("/Users/yubai/epub-translate")
        path_form.addRow("项目路径：", self.project_path)

        note = QLabel("插件将使用该路径下的 .venv/bin/python 和 config.json")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        path_form.addRow("", note)

        layout.addWidget(path_group)

        # === 翻译设置 ===
        trans_group = QGroupBox("翻译设置")
        trans_form = QFormLayout(trans_group)

        self.target_language = QComboBox()
        for label, value in LANGUAGE_OPTIONS:
            self.target_language.addItem(label, value)
        trans_form.addRow("目标语言：", self.target_language)

        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 20)
        self.concurrency.setSuffix(" 个并发请求")
        trans_form.addRow("并发数：", self.concurrency)

        self.user_prompt = QTextEdit()
        self.user_prompt.setMaximumHeight(80)
        self.user_prompt.setPlaceholderText("（可选）追加到系统提示词的自定义指令")
        trans_form.addRow("自定义提示词：", self.user_prompt)

        layout.addWidget(trans_group)

        # === API 配置（仅当不使用 config.json 时生效）===
        api_group = QGroupBox("API 配置（覆盖 config.json 中的 llm 配置）")
        api_group.setCheckable(True)
        api_group.setChecked(False)
        api_form = QFormLayout(api_group)
        self.api_group = api_group

        self.llm_key = QLineEdit()
        self.llm_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.llm_key.setPlaceholderText("sk-...")
        api_form.addRow("API Key：", self.llm_key)

        self.llm_url = QLineEdit()
        self.llm_url.setPlaceholderText("https://api.deepseek.com")
        api_form.addRow("API URL：", self.llm_url)

        self.llm_model = QLineEdit()
        self.llm_model.setPlaceholderText("deepseek-chat")
        api_form.addRow("模型：", self.llm_model)

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

        # 如果有独立 API key，展开 API 配置组
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
