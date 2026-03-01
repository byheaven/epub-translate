# epub-translate

将英文 EPUB 书籍翻译为**中英双语对照版本**的工具套件，基于 [oomol-lab/epub-translator](https://github.com/oomol-lab/epub-translator)。

包含两种使用方式：
- **CLI 脚本**：批量翻译 `input/` 目录下的 epub 文件
- **Calibre 插件**：在 Calibre 书库中选中书籍直接翻译，翻译结果自动加入书库

## 效果预览

翻译后为中英双语对照排版（英文段落下方紧跟中文翻译），封面与原书一致，书名自动更新为双语标题。

## 支持的模型

任何兼容 OpenAI API 格式的模型均可使用：

| 模型 | url | model | 大致成本/本 |
|------|-----|-------|------------|
| DeepSeek V3 | `https://api.deepseek.com` | `deepseek-chat` | ¥0.5–3 |
| OpenAI GPT-4o | `https://api.openai.com/v1` | `gpt-4o` | $1–5 |
| OpenAI GPT-4o-mini | `https://api.openai.com/v1` | `gpt-4o-mini` | $0.2–1 |
| Azure OpenAI | `https://<resource>.openai.azure.com/openai/deployments/<model>/chat/completions?api-version=2024-02-01` | deployment 名称 | 按用量 |
| 硅基流动 | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3` | ¥0.3–1 |
| 阿里通义 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | ¥0.5–2 |

---

## 方式一：CLI 脚本

### 安装

需要 Python 3.12+。

```bash
git clone https://github.com/byheaven/epub-translate.git
cd epub-translate
python3 -m venv .venv
source .venv/bin/activate
pip install epub-translator tqdm
```

### 配置

复制并编辑 `config.example.json`：

```bash
cp config.example.json config.json
```

```json
{
  "llm": {
    "key": "YOUR_API_KEY",
    "url": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "token_encoding": "o200k_base",
    "timeout": 120.0,
    "top_p": 0.6,
    "temperature": 0.85,
    "retry_times": 5,
    "retry_interval_seconds": 6.0
  },
  "target_language": "SIMPLIFIED_CHINESE",
  "concurrency": 3,
  "user_prompt": ""
}
```

**`target_language` 可选值：** `SIMPLIFIED_CHINESE` `TRADITIONAL_CHINESE` `JAPANESE` `KOREAN` `FRENCH` `GERMAN` `SPANISH` `RUSSIAN` `PORTUGUESE` `ENGLISH`

### 使用

```bash
# 将 epub 文件放入 input/
cp ~/Downloads/book.epub input/

# 运行翻译
source .venv/bin/activate
python translate_books.py

# 结果在 output/
```

翻译中断后重新运行会自动从缓存断点续翻，无需从头开始。

---

## 方式二：Calibre 插件

在 Calibre 书库中直接选中书籍翻译，支持批量操作，翻译结果自动加入书库。

### 安装

**前提：** 已完成 CLI 方式的安装步骤（需要 `.venv` 和 `config.json`）。

**下载插件：**

从 [Releases](https://github.com/byheaven/epub-translate/releases) 下载最新的 `EpubTranslate.zip`，或自行打包：

```bash
cd calibre-plugin
zip -r ../EpubTranslate.zip . --exclude '*.DS_Store'
cd ..
```

**安装到 Calibre：**

```bash
# macOS
/Applications/calibre.app/Contents/MacOS/calibre-customize -a EpubTranslate.zip

# Linux
calibre-customize -a EpubTranslate.zip
```

重启 Calibre，在 **Preferences → Toolbars & Menus** 中将 **Epub Translate** 添加到工具栏。

### 使用

1. 在 Calibre 书库中选中一本或多本含 EPUB 格式的书
2. 点击工具栏的 **Translate EPUB** 按钮
3. 确认后开始翻译，进度实时显示
4. 翻译完成后双语版自动加入书库（原书不受影响）

### 插件配置

点击 **Translate EPUB → Settings** 可配置：
- `epub-translate` 项目路径（插件据此找到 `.venv` 和 `config.json`）
- 目标语言、并发数、自定义提示词
- 也可直接编辑项目目录下的 `config.json`

---

## 文件结构

```
epub-translate/
├── translate_books.py       # CLI 批量翻译脚本
├── translate_worker.py      # Calibre 插件调用的翻译 worker（JSON 行协议）
├── config.example.json      # 配置示例
├── calibre-plugin/          # Calibre 插件源码
│   ├── __init__.py          # 插件注册
│   ├── ui.py                # 工具栏按钮、进度对话框
│   ├── worker.py            # QThread 封装子进程
│   ├── config.py            # 插件配置面板
│   └── images/icon.png      # 工具栏图标
├── input/                   # 待翻译的 epub（CLI 用）
├── output/                  # 翻译结果（CLI 用）
└── cache/                   # 翻译缓存（断点续翻）
```

## 工作原理

### CLI 脚本

直接调用 `epub-translator` 库，对 `input/` 中的每本书调用 `translate()` 函数，以 `APPEND_BLOCK` 模式输出双语 epub。

### Calibre 插件

插件运行于 Calibre 内置 Python 环境，无法直接 import `epub-translator`（依赖 openai/tiktoken 等）。因此采用**子进程方案**：

```
Calibre 插件 (Qt/Python 3.14)
  │  subprocess.Popen
  ▼
translate_worker.py (.venv/bin/python)
  │  stdout: JSON 行协议 {"type":"progress","value":0.45}
  ▼
epub_translator 库（实际翻译）
```

进度通过 JSON 行实时回传，插件解析后更新 Qt 进度条。

## License

MIT
