# epub-translate

[中文文档](README.zh-CN.md)

Translate English EPUB books into **bilingual side-by-side editions** (original + translated paragraphs interleaved), powered by [oomol-lab/epub-translator](https://github.com/oomol-lab/epub-translator).

Two usage modes:
- **CLI script** — batch-translate all EPUBs in `input/`, write results to `output/`
- **Calibre plugin** — select books in your Calibre library and translate them in-place; the bilingual edition is added automatically

## Output format

Each translated paragraph appears immediately below the original. The cover is preserved, and the book title is updated to include the translated title.

## Supported models

Any OpenAI-compatible API endpoint works:

| Model | url | model | Approx. cost/book |
|-------|-----|-------|-------------------|
| DeepSeek V3 | `https://api.deepseek.com` | `deepseek-chat` | ¥0.5–3 |
| OpenAI GPT-4o | `https://api.openai.com/v1` | `gpt-4o` | $1–5 |
| OpenAI GPT-4o-mini | `https://api.openai.com/v1` | `gpt-4o-mini` | $0.2–1 |
| Azure OpenAI | `https://<resource>.openai.azure.com/openai/deployments/<model>/chat/completions?api-version=2024-02-01` | deployment name | metered |
| SiliconFlow | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3` | ¥0.3–1 |
| Alibaba Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | ¥0.5–2 |

---

## Option 1: CLI script

### Install

Requires Python 3.12+.

```bash
git clone https://github.com/byheaven/epub-translate.git
cd epub-translate
python3 -m venv .venv
source .venv/bin/activate
pip install epub-translator tqdm
```

### Configure

```bash
cp config.example.json config.json
# edit config.json and set your API key
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

**`target_language` values:** `SIMPLIFIED_CHINESE` `TRADITIONAL_CHINESE` `JAPANESE` `KOREAN` `FRENCH` `GERMAN` `SPANISH` `RUSSIAN` `PORTUGUESE` `ENGLISH`

### Run

```bash
cp ~/Downloads/book.epub input/

source .venv/bin/activate
python translate_books.py

# results in output/
```

If interrupted, re-running resumes from the cache automatically — no work is lost.

---

## Option 2: Calibre plugin

Translate books directly from your Calibre library. The bilingual edition is added as a new entry (original is untouched).

### Install

**Prerequisite:** complete the CLI install steps above (`.venv` and `config.json` must exist).

**Download the plugin:**

Download `EpubTranslate.zip` from [Releases](https://github.com/byheaven/epub-translate/releases), or build it yourself:

```bash
cd calibre-plugin
zip -r ../EpubTranslate.zip . --exclude '*.DS_Store'
cd ..
```

**Install into Calibre:**

```bash
# macOS
/Applications/calibre.app/Contents/MacOS/calibre-customize -a EpubTranslate.zip

# Linux
calibre-customize -a EpubTranslate.zip
```

Restart Calibre, then go to **Preferences → Toolbars & Menus** and add **Epub Translate** to the toolbar.

### Use

1. Select one or more books with EPUB format in your library
2. Click the **Translate EPUB** toolbar button
3. Confirm and watch the progress dialog
4. The bilingual edition appears in the library when done

### Plugin settings

Click **Translate EPUB → Settings** to configure:
- Path to the `epub-translate` project directory (used to locate `.venv` and `config.json`)
- Target language, concurrency, custom prompt
- Or edit `config.json` in the project directory directly

---

## Repository layout

```
epub-translate/
├── translate_books.py       # CLI batch translation script
├── translate_worker.py      # Worker invoked by the Calibre plugin (JSON-line protocol)
├── config.example.json      # Configuration template
├── calibre-plugin/          # Calibre plugin source
│   ├── __init__.py          # Plugin registration
│   ├── ui.py                # Toolbar button and progress dialog
│   ├── worker.py            # QThread wrapping subprocess
│   ├── config.py            # Plugin settings panel
│   └── images/icon.png      # Toolbar icon
├── input/                   # Drop EPUBs here (CLI)
├── output/                  # Translated output (CLI)
└── cache/                   # Translation cache (enables resume)
```

## How it works

### CLI

Calls `epub_translator.translate()` on each file in `input/` using `SubmitKind.APPEND_BLOCK`, which interleaves original and translated paragraphs in the output EPUB.

### Calibre plugin

The plugin runs inside Calibre's embedded Python and cannot import `epub-translator` (which depends on `openai`, `tiktoken`, etc.). Instead it spawns a subprocess:

```
Calibre plugin (Qt / Python 3.14)
  │  subprocess.Popen
  ▼
translate_worker.py  (.venv/bin/python)
  │  stdout: JSON-line protocol  {"type":"progress","value":0.45}
  ▼
epub_translator library
```

Progress is streamed back as JSON lines and displayed in a Qt progress bar.

## License

MIT
