# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
4. Translation caches are stored in `cache/` for resumability (interrupted jobs can be restarted)

## Architecture

The entire application is `translate_books.py` (~164 lines). Key functions:

- `main()` — entry point: loads config, discovers EPUBs in `input/`, iterates and calls `translate_one()`
- `translate_one()` — handles one book: checks if output already exists (skip), calls `epub_translator.translate()` with a tqdm progress bar
- `build_llm()` — constructs an `LLM` object from config for the `epub-translator` library
- `load_config()` — reads `config.json`

The `epub_translator` library handles all actual translation logic, chunking, and caching. This codebase does not implement any translation logic directly.

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

The LLM `url` field must be an OpenAI-compatible API endpoint. Any provider with such an API works (DeepSeek, OpenAI, Anthropic via compatible proxy, SiliconFlow, Alibaba Qwen, etc.).

## Dependencies

- Python 3.12 at `/opt/homebrew/bin/python3.12`
- `epub-translator` (OOMOL Lab) — the core translation library
- `tqdm` — progress bar display
