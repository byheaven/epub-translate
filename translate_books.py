#!/Users/yubai/epub-translate/.venv/bin/python
"""
translate_books.py - Batch EPUB bilingual translation tool.

Usage:
  1. Edit config.json with your API key and model settings.
  2. Place .epub files in input/.
  3. Run: python translate_books.py
  4. Translated bilingual EPUBs are written to output/.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from tqdm import tqdm
from epub_translator import LLM, translate, SubmitKind, FillFailedEvent
from epub_translator.translation import language as Lang

# === Paths ===
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

# === Language mapping ===
LANGUAGE_MAP = {
    "SIMPLIFIED_CHINESE": Lang.CHINESE,
    "TRADITIONAL_CHINESE": Lang.TRADITIONAL_CHINESE,
    "ENGLISH": Lang.ENGLISH,
    "JAPANESE": Lang.JAPANESE,
    "KOREAN": Lang.KOREAN,
    "FRENCH": Lang.FRENCH,
    "GERMAN": Lang.GERMAN,
    "SPANISH": Lang.SPANISH,
    "RUSSIAN": Lang.RUSSIAN,
    "PORTUGUESE": Lang.PORTUGUESE,
}


def load_config():
    if not CONFIG_PATH.exists():
        print(f"Config file not found: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_llm(config: dict) -> LLM:
    c = config["llm"]
    cache_dir = BASE_DIR / "cache"
    cache_dir.mkdir(exist_ok=True)
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    llm = LLM(
        key=c["key"],
        url=c["url"],
        model=c["model"],
        token_encoding=c.get("token_encoding", "o200k_base"),
        timeout=c.get("timeout", 120.0),
        top_p=c.get("top_p", 0.6),
        temperature=c.get("temperature", 0.85),
        retry_times=c.get("retry_times", 5),
        retry_interval_seconds=c.get("retry_interval_seconds", 6.0),
        cache_path=cache_dir,
        log_dir_path=log_dir,
    )
    # Azure OpenAI requires a dedicated client; detect by URL
    if ".openai.azure.com" in c["url"]:
        from openai import AzureOpenAI
        parsed = urlparse(c["url"])
        azure_endpoint = f"{parsed.scheme}://{parsed.netloc}"
        api_version = parse_qs(parsed.query).get("api-version", ["2024-02-01"])[0]
        llm._executor._client = AzureOpenAI(
            api_key=c["key"],
            azure_endpoint=azure_endpoint,
            api_version=api_version,
            timeout=c.get("timeout", 120.0),
        )
        print(f"   Azure OpenAI: {azure_endpoint} (api-version={api_version})")
    return llm


def translate_one(llm: LLM, epub_path: Path, config: dict) -> bool:
    """Translate a single EPUB and write the bilingual output to output/."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / f"{epub_path.stem}_bilingual.epub"

    if output_path.exists():
        print(f"Skipping (already exists): {output_path.name}")
        return True

    lang_key = config.get("target_language", "SIMPLIFIED_CHINESE")
    target_lang = LANGUAGE_MAP.get(lang_key, Lang.CHINESE)
    user_prompt = config.get("user_prompt", None)
    concurrency = config.get("concurrency", 3)

    print(f"\nTranslating: {epub_path.name}")
    print(f"  Output:      {output_path.name}")
    print(f"  Model:       {config['llm']['model']}")
    print(f"  Language:    {target_lang}")
    print(f"  Concurrency: {concurrency}")

    fill_errors, critical_errors = 0, 0

    try:
        with tqdm(
            total=100,
            desc="  Progress",
            unit="%",
            bar_format="{desc}: {percentage:3.0f}%|{bar}| [{elapsed}<{remaining}]",
        ) as pbar:
            last_progress = 0.0

            def on_progress(progress: float) -> None:
                nonlocal last_progress
                pbar.update((progress - last_progress) * 100)
                last_progress = progress

            def on_fill_failed(event: FillFailedEvent) -> None:
                nonlocal fill_errors, critical_errors
                fill_errors += 1
                if event.over_maximum_retries:
                    critical_errors += 1
                    tqdm.write(f"  Critical error (output may be incomplete): {event.error_message}")
                else:
                    tqdm.write(f"  Retry {event.retried_count}: {event.error_message[:80]}")

            translate(
                llm=llm,
                source_path=str(epub_path),
                target_path=str(output_path),
                target_language=target_lang,
                submit=SubmitKind.APPEND_BLOCK,
                user_prompt=user_prompt,
                concurrency=concurrency,
                on_progress=on_progress,
                on_fill_failed=on_fill_failed,
            )

        tokens_in = llm.input_tokens
        tokens_out = llm.output_tokens
        cached = llm.input_cache_tokens
        print(f"Done: {output_path.name}")
        print(f"  Tokens: in {tokens_in:,} (cache hit {cached:,}) / out {tokens_out:,}")
        if critical_errors:
            print(f"  Warning: {critical_errors} critical error(s), output may be incomplete")
        return True

    except KeyboardInterrupt:
        print(f"\nInterrupted: {epub_path.name}")
        raise
    except Exception as e:
        print(f"Failed: {epub_path.name}")
        print(f"  Error: {e}")
        return False


def main():
    print("=" * 50)
    print("EPUB Batch Bilingual Translation")
    print("=" * 50)

    config = load_config()

    if config["llm"]["key"] == "YOUR_API_KEY_HERE":
        print("\nPlease edit config.json and set your API key.")
        print(f"  Config file: {CONFIG_PATH}")
        sys.exit(1)

    INPUT_DIR.mkdir(exist_ok=True)
    epub_files = sorted(INPUT_DIR.glob("*.epub"))

    if not epub_files:
        print(f"\nNo .epub files found in {INPUT_DIR}/")
        sys.exit(1)

    print(f"\nFound {len(epub_files)} file(s):")
    for i, f in enumerate(epub_files, 1):
        size_mb = f.stat().st_size / 1024 / 1024
        print(f"  {i}. {f.name} ({size_mb:.1f} MB)")

    llm = build_llm(config)

    success, failed = 0, 0
    for epub_path in epub_files:
        try:
            if translate_one(llm, epub_path, config):
                success += 1
            else:
                failed += 1
        except KeyboardInterrupt:
            print("\n\nInterrupted. Completed translations are in output/.")
            sys.exit(0)

    print(f"\n{'=' * 50}")
    print(f"Done: {success} succeeded, {failed} failed")
    print(f"  Output directory: {OUTPUT_DIR}/")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
