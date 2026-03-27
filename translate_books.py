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

import openai
from tqdm import tqdm
from epub_translator import LLM, translate, SubmitKind, FillFailedEvent
from epub_translator.translation import language as Lang


# ---------------------------------------------------------------------------
# Azure content-filter error handling
# ---------------------------------------------------------------------------

def _is_content_filter_error(err: Exception) -> bool:
    """Return True if err is an Azure OpenAI content-filter (policy) rejection."""
    if not isinstance(err, openai.BadRequestError):
        return False
    body = getattr(err, 'body', None)
    if isinstance(body, dict):
        error_info = body.get('error', body)
        if isinstance(error_info, dict):
            if error_info.get('code') == 'content_filter':
                return True
            inner = error_info.get('innererror', {})
            if isinstance(inner, dict) and inner.get('code') == 'ResponsibleAIPolicyViolation':
                return True
    return 'content_filter' in str(err) or 'content management policy' in str(err)


# Holds the per-book skip callback; swapped by translate_one() before each book.
_content_filter_skip_cb = None


def _install_content_filter_skip() -> None:
    """One-time monkey-patch of XMLTranslator to skip content-filtered segments."""
    from epub_translator.xml_translator.translator import XMLTranslator
    if getattr(XMLTranslator._translate_inline_segments, '_content_filter_patched', False):
        return
    original = XMLTranslator._translate_inline_segments

    def patched(self, inline_segments, callbacks):
        try:
            return original(self, inline_segments, callbacks)
        except Exception as e:
            if _is_content_filter_error(e):
                preview = ""
                for seg in inline_segments[:1]:
                    for ts in seg:
                        preview += ts.text
                        if len(preview) >= 80:
                            break
                if _content_filter_skip_cb is not None:
                    _content_filter_skip_cb(preview[:80])
                return [None] * len(inline_segments)
            raise

    patched._content_filter_patched = True
    XMLTranslator._translate_inline_segments = patched

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
    # Azure OpenAI: use plain OpenAI client with full deployment URL as base_url.
    # This allows the "model" field to be the actual model name (e.g. gpt-5.4)
    # rather than being forced to match the deployment name.
    if ".openai.azure.com" in c["url"]:
        from openai import OpenAI as _OpenAI
        parsed = urlparse(c["url"])
        base_path = parsed.path
        for suffix in ("/chat/completions", "/completions"):
            if base_path.endswith(suffix):
                base_path = base_path[: -len(suffix)]
                break
        base_url = f"{parsed.scheme}://{parsed.netloc}{base_path}"
        query_params = parse_qs(parsed.query)
        default_query = {}
        if "api-version" in query_params:
            default_query["api-version"] = query_params["api-version"][0]
        llm._executor._client = _OpenAI(
            api_key=c["key"],
            base_url=base_url,
            timeout=c.get("timeout", 120.0),
            default_query=default_query if default_query else None,
        )
        print(f"   Azure OpenAI: {base_url}")

    # Patch _invoke_model to use max_completion_tokens instead of max_tokens
    # for newer models (e.g. gpt-5.4) that reject the legacy parameter.
    def _patched_invoke(input_messages, top_p, temperature, max_tokens):
        from io import StringIO as _StringIO
        from epub_translator.llm.types import MessageRole as _MR
        msgs = []
        for item in input_messages:
            if item.role == _MR.SYSTEM:
                msgs.append({"role": "system", "content": item.message})
            elif item.role == _MR.USER:
                msgs.append({"role": "user", "content": item.message})
            elif item.role == _MR.ASSISTANT:
                msgs.append({"role": "assistant", "content": item.message})
        stream = llm._executor._client.chat.completions.create(
            model=llm._executor._model_name,
            messages=msgs,
            stream=True,
            stream_options={"include_usage": True},
            top_p=top_p,
            temperature=temperature,
            max_completion_tokens=max_tokens,
        )
        buf = _StringIO()
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                buf.write(chunk.choices[0].delta.content)
            llm._executor._statistics.submit_usage(chunk.usage)
        return buf.getvalue()
    llm._executor._invoke_model = _patched_invoke
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

    fill_errors, critical_errors, skipped_segments = 0, 0, 0

    try:
        global _content_filter_skip_cb

        def on_content_skip(preview: str) -> None:
            nonlocal skipped_segments
            skipped_segments += 1
            tqdm.write(f"  Content filtered (skipped): {preview!r}")

        _content_filter_skip_cb = on_content_skip

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
        if skipped_segments:
            print(f"  Skipped: {skipped_segments} content-filtered segment(s) (kept in original language)")
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
    finally:
        _content_filter_skip_cb = None


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
    _install_content_filter_skip()

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
