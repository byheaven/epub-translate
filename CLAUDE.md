# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## What This Project Does

A batch EPUB translation tool that converts English EPUB books into bilingual (English + target language) versions using LLM APIs. Built as a thin wrapper around the `epub-translator` library from OOMOL Lab.

## Running the Tool

```bash
./translate_books.py
```

There is no build step, no test suite. The script uses a shebang pointing to `.venv/bin/python` (Python 3.13). The virtual environment lives at `.venv/` inside the project directory.

**Workflow:**
1. Edit `config.json` with your API key and model settings
2. Place `.epub` files in `input/`
3. Run the script — output goes to `output/` as `{stem}_bilingual.epub`
4. Translation caches are stored in `cache/` for resumability

## Architecture

CLI application is `translate_books.py`. Key functions:
- `main()` — loads config, discovers EPUBs in `input/`, calls `translate_one()`
- `translate_one()` — skips if output exists, calls `epub_translator.translate()`
- `build_llm()` — constructs `LLM` object from config
- `load_config()` — reads `config.json`

## Calibre Plugin

The `calibre-plugin/` directory contains a Calibre InterfaceAction plugin.

**Architecture:** The plugin runs inside Calibre's embedded Python and cannot import `epub-translator` directly. It spawns `translate_worker.py` as a subprocess and communicates via JSON lines on stdout.

Key files:
- `calibre-plugin/ui.py` — toolbar button, progress dialog, library integration
- `calibre-plugin/worker.py` — `QThread` wrapping `subprocess.Popen`
- `calibre-plugin/config.py` — plugin settings panel (JSONConfig)
- `translate_worker.py` — standalone worker script invoked by the plugin

**Packaging:**
```bash
cd calibre-plugin && zip -r ../EpubTranslate.zip . --exclude '*.DS_Store'
/Applications/calibre.app/Contents/MacOS/calibre-customize -a ../EpubTranslate.zip
```

## Configuration (`config.json`)

```json
{
  "llm": {
    "key": "YOUR_API_KEY_HERE",
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
  "user_prompt": "..."
}
```

**Supported `target_language` values:** `SIMPLIFIED_CHINESE`, `TRADITIONAL_CHINESE`, `ENGLISH`, `JAPANESE`, `KOREAN`, `FRENCH`, `GERMAN`, `SPANISH`, `RUSSIAN`, `PORTUGUESE`

Azure OpenAI is auto-detected by `.openai.azure.com` in the URL and uses the `AzureOpenAI` client.

## Dependencies

- Python 3.12+ in `.venv/`
- `epub-translator` (OOMOL Lab) — core translation library
- `tqdm` — progress bar display
