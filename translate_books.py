#!/Users/yubai/epub-translate/.venv/bin/python
"""
epub-translate: 批量将英文 EPUB 翻译为中英双语对照版本
使用 oomol-lab/epub-translator 库

用法:
  1. 编辑 config.json，填入你的 API key 和模型配置
  2. 运行: /opt/homebrew/bin/python3.12 translate_books.py
  3. 自动扫描 ~/Downloads 中文件名为英文的 epub 文件
  4. 翻译结果保存在 ~/Downloads/{书名}-cn.epub
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from tqdm import tqdm
from epub_translator import LLM, translate, SubmitKind, FillFailedEvent
from epub_translator.translation import language as Lang

# === 路径配置 ===
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
DOWNLOAD_DIR = Path.home() / "Downloads"

# === 语言映射 ===
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
        print(f"❌ 配置文件不存在: {CONFIG_PATH}")
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
    # Azure OpenAI 需要专用客户端；检测到 Azure URL 时自动替换内部客户端
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
        print(f"   ☁️  Azure OpenAI: {azure_endpoint} (api-version={api_version})")
    return llm


def is_english_filename(name: str) -> bool:
    """判断文件名是否为纯英文（只含英文字母、数字、常见标点和空格）"""
    return bool(re.match(r"^[a-zA-Z0-9\s\-_.,;:!?'\"()\[\]&#+@]+$", name))


def clean_book_title(stem: str) -> str:
    """从文件名中提取书名，去掉作者、出版社、括号内容等多余信息"""
    name = stem
    # 去掉括号及其内容：(Author) [Publisher] {Year}
    name = re.sub(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]", "", name)
    # 去掉 " by Author" 结尾
    name = re.sub(r"\s+by\s+.*$", "", name, flags=re.IGNORECASE)
    # 去掉 " - Author/Publisher" 结尾（保留书名中合理的破折号如 "Spider-Man"）
    name = re.sub(r"\s+[-–—]\s+[A-Z].*$", "", name)
    # 清理多余空格
    name = re.sub(r"\s+", " ", name).strip()
    return name


def translate_one(llm: LLM, epub_path: Path, title: str, config: dict) -> bool:
    """翻译单本书，输出到同目录下的 {title}-cn.epub"""
    output_path = epub_path.parent / f"{title}-cn.epub"

    if output_path.exists():
        print(f"⏭️  跳过 (已存在): {output_path.name}")
        return True

    lang_key = config.get("target_language", "SIMPLIFIED_CHINESE")
    target_lang = LANGUAGE_MAP.get(lang_key, Lang.CHINESE)
    user_prompt = config.get("user_prompt", None)
    concurrency = config.get("concurrency", 3)

    print(f"\n📖 开始翻译: {epub_path.name}")
    print(f"   → 输出: {output_path.name}")
    print(f"   → 模型: {config['llm']['model']}")
    print(f"   → 目标语言: {target_lang}")
    print(f"   → 并发数: {concurrency}")

    fill_errors, critical_errors = 0, 0

    try:
        with tqdm(
            total=100,
            desc="   翻译中",
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
                    tqdm.write(f"   ❌ 严重错误（将影响输出）: {event.error_message}")
                else:
                    tqdm.write(f"   ⚠️  重试 {event.retried_count}: {event.error_message[:80]}")

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
        print(f"✅ 完成: {output_path.name}")
        print(f"   📊 Token: 输入 {tokens_in:,}（缓存命中 {cached:,}）/ 输出 {tokens_out:,}")
        if critical_errors:
            print(f"   ⚠️  {critical_errors} 处严重错误，输出可能不完整")
        return True

    except KeyboardInterrupt:
        print(f"\n⚠️  用户中断: {epub_path.name}")
        raise
    except Exception as e:
        print(f"❌ 翻译失败: {epub_path.name}")
        print(f"   错误: {e}")
        return False


def main():
    print("=" * 50)
    print("📚 EPUB 批量双语翻译工具")
    print("=" * 50)

    config = load_config()

    if config["llm"]["key"] == "YOUR_API_KEY_HERE":
        print("\n❌ 请先编辑 config.json，填入你的 API key")
        print(f"   配置文件: {CONFIG_PATH}")
        sys.exit(1)

    # 扫描 Downloads，只保留英文文件名、且尚未生成 -cn 版本的 epub
    all_epub = sorted(DOWNLOAD_DIR.glob("*.epub"))
    epub_files = [
        f for f in all_epub
        if is_english_filename(f.stem) and not f.stem.endswith("-cn")
    ]

    skipped = len(all_epub) - len(epub_files)
    if skipped:
        print(f"\n🔤 跳过 {skipped} 个非英文文件名的 epub")

    if not epub_files:
        print(f"\n❌ 未找到待翻译的英文 epub 文件")
        print(f"   扫描目录: {DOWNLOAD_DIR}/")
        sys.exit(1)

    # 清理书名并在必要时重命名原文件
    tasks: list[tuple[Path, str]] = []
    for epub_path in epub_files:
        title = clean_book_title(epub_path.stem)
        if title != epub_path.stem:
            new_path = epub_path.parent / f"{title}.epub"
            if not new_path.exists():
                epub_path.rename(new_path)
                print(f"✏️  重命名: {epub_path.name} → {new_path.name}")
                epub_path = new_path
        tasks.append((epub_path, title))

    print(f"\n找到 {len(tasks)} 本书:")
    for i, (f, title) in enumerate(tasks, 1):
        size_mb = f.stat().st_size / 1024 / 1024
        print(f"   {i}. {f.name} ({size_mb:.1f} MB)")

    llm = build_llm(config)

    success, failed = 0, 0
    for epub_path, title in tasks:
        try:
            if translate_one(llm, epub_path, title, config):
                success += 1
            else:
                failed += 1
        except KeyboardInterrupt:
            print("\n\n🛑 已中断。已完成的翻译在 ~/Downloads/ 中。")
            sys.exit(0)

    print(f"\n{'=' * 50}")
    print(f"📊 完成: {success} 成功, {failed} 失败")
    print(f"   输出目录: {DOWNLOAD_DIR}/")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
