#!/Users/yubai/epub-translate/.venv/bin/python
"""
translate_worker.py - Translation worker invoked by the Calibre plugin.

Usage:
  .venv/bin/python translate_worker.py \\
    --source /path/to/book.epub \\
    --target /tmp/book-bilingual.epub \\
    --config /path/to/config.json

stdout protocol (one JSON object per line):
  {"type": "progress", "value": 0.45}
  {"type": "error", "message": "retry 1: ...", "critical": false}
  {"type": "stats", "input_tokens": 58524, "output_tokens": 18913, "cached_tokens": 2816}
  {"type": "done", "success": true}
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import openai
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


def emit(obj: dict) -> None:
    """Write a single JSON line to stdout and flush immediately."""
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def build_llm(config: dict, base_dir: Path) -> LLM:
    c = config["llm"]
    cache_dir = base_dir / "cache"
    cache_dir.mkdir(exist_ok=True)
    log_dir = base_dir / "logs"
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
    return llm


def main():
    parser = argparse.ArgumentParser(description="EPUB translation worker (called by the Calibre plugin)")
    parser.add_argument("--source", required=True, help="Source EPUB path")
    parser.add_argument("--target", required=True, help="Output EPUB path")
    parser.add_argument("--config", required=True, help="Path to config.json")
    args = parser.parse_args()

    source_path = Path(args.source)
    target_path = Path(args.target)
    config_path = Path(args.config)
    base_dir = config_path.parent

    if not source_path.exists():
        emit({"type": "error", "message": f"Source file not found: {source_path}", "critical": True})
        emit({"type": "done", "success": False})
        sys.exit(1)

    if not config_path.exists():
        emit({"type": "error", "message": f"Config file not found: {config_path}", "critical": True})
        emit({"type": "done", "success": False})
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    lang_key = config.get("target_language", "SIMPLIFIED_CHINESE")
    target_lang = LANGUAGE_MAP.get(lang_key, Lang.CHINESE)
    user_prompt = config.get("user_prompt", None)
    concurrency = config.get("concurrency", 3)

    try:
        llm = build_llm(config, base_dir)
    except Exception as e:
        emit({"type": "error", "message": f"Failed to initialize LLM: {e}", "critical": True})
        emit({"type": "done", "success": False})
        sys.exit(1)

    _install_content_filter_skip()

    global _content_filter_skip_cb

    def on_content_skip(preview: str) -> None:
        emit({
            "type": "error",
            "message": f"Content filtered (segment skipped): {preview!r}",
            "critical": False,
        })

    _content_filter_skip_cb = on_content_skip

    last_progress = 0.0

    def on_progress(progress: float) -> None:
        nonlocal last_progress
        # Emit only when progress changes by at least 1% to reduce IPC overhead
        if progress - last_progress >= 0.01 or progress >= 1.0:
            emit({"type": "progress", "value": round(progress, 4)})
            last_progress = progress

    def on_fill_failed(event: FillFailedEvent) -> None:
        is_critical = bool(event.over_maximum_retries)
        emit({
            "type": "error",
            "message": event.error_message,
            "critical": is_critical,
        })

    try:
        translate(
            llm=llm,
            source_path=str(source_path),
            target_path=str(target_path),
            target_language=target_lang,
            submit=SubmitKind.APPEND_BLOCK,
            user_prompt=user_prompt,
            concurrency=concurrency,
            on_progress=on_progress,
            on_fill_failed=on_fill_failed,
        )
        emit({
            "type": "stats",
            "input_tokens": llm.input_tokens,
            "output_tokens": llm.output_tokens,
            "cached_tokens": llm.input_cache_tokens,
        })
        emit({"type": "done", "success": True})

    except KeyboardInterrupt:
        emit({"type": "error", "message": "Translation cancelled by user", "critical": True})
        emit({"type": "done", "success": False})
        sys.exit(0)

    except Exception as e:
        emit({"type": "error", "message": str(e), "critical": True})
        emit({"type": "done", "success": False})
        sys.exit(1)


if __name__ == "__main__":
    main()
