"""
Bulgarian -> Russian translator abstraction.

Primary backend: MyMemory (free, no key, good bg->ru quality).
Fallback: LibreTranslate public instance.
Static map for categories ensures perfect/consistent translation.

MyMemory limit: 500 chars — longer texts are chunked.
"""

from __future__ import annotations

import hashlib
import time
import random
import re
from typing import Optional

try:
    from deep_translator import MyMemoryTranslator
    HAS_DEEP = True
except ImportError:
    HAS_DEEP = False

import urllib.request
import urllib.parse
import json


# ---------------------------------------------------------------------------
# Static category map — perfect translation, no API calls, consistent labels
# ---------------------------------------------------------------------------
CATEGORY_MAP: dict[str, str] = {
    "Маркети": "Маркеты",
    "Кино": "Кино",
    "Инструменти": "Инструменты",
    "IPTV": "IPTV",
    "Стрийминг": "Стриминг",
    "Ланчъри": "Лаунчеры",
    "Видеоплеъри": "Видеоплееры",
    "FireTV": "FireTV",
    "Браузъри": "Браузеры",
    "Скрийнсейвъри": "Скринсейверы",
    "Kodi repo": "Kodi репозитории",
    "Plex&Jellyfin": "Plex и Jellyfin",
    "Kodi": "Kodi",
    "Kodi Modi": "Kodi Моды",
}

# Glossary for consistent post-processing (fixes drift in LLM/API outputs)
GLOSSARY: dict[str, str] = {
    "скрийнсейвър": "скринсейвер",
    "Скрийнсейвър": "Скринсейвер",
    "плейър": "плеер",
    "Плейър": "Плеер",
    "Стриминг канали": "Стриминговые каналы",
    "Стриминг Канали": "Стриминговые каналы",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _apply_glossary(text: str) -> str:
    for bg, ru in GLOSSARY.items():
        text = text.replace(bg, ru)
    return text


def _chunk_text(text: str, max_len: int = 450) -> list[str]:
    """Split text on word/sentence boundaries into chunks <= max_len."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    # Prefer splitting on paragraph/sentence boundaries
    parts = re.split(r'(\n\n|\n|(?<=[.!?])\s+)', text)
    current = ""
    for part in parts:
        if not part:
            continue
        if len(current) + len(part) <= max_len:
            current += part
        else:
            if current:
                chunks.append(current)
                current = ""
            # If single part still too long, hard-split on words
            while len(part) > max_len:
                cut = part.rfind(" ", 0, max_len)
                if cut == -1:
                    cut = max_len
                chunks.append(part[:cut])
                part = part[cut:].lstrip()
            current = part
    if current:
        chunks.append(current)
    return [c for c in chunks if c.strip()]


def _mymemory_translate(text: str, src: str = "bg-BG", tgt: str = "ru-RU") -> Optional[str]:
    """Single attempt via MyMemory. Returns None on failure or if not translated."""
    if not HAS_DEEP:
        return None
    # MyMemory hard limit is 500 chars
    if len(text) > 500:
        return None
    try:
        result = MyMemoryTranslator(source=src, target=tgt).translate(text)
        if not result or not result.strip():
            return None
        result = result.strip()
        # MyMemory returns input unchanged when it doesn't know — treat as failure
        # so caller can retry/fallback and we don't poison the cache
        if result.strip() == text.strip():
            return None
        return result
    except Exception:
        return None


def _libre_translate(text: str, src: str = "bg", tgt: str = "ru") -> Optional[str]:
    """Fallback via public LibreTranslate instance."""
    endpoints = [
        "https://libretranslate.com/translate",
        "https://translate.argosopentech.com/translate",
    ]
    for url in endpoints:
        try:
            data = urllib.parse.urlencode({
                "q": text,
                "source": src,
                "target": tgt,
                "format": "text",
            }).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                translated = body.get("translatedText") or body.get("translation")
                if translated and translated.strip() and translated.strip() != text.strip():
                    return translated.strip()
                if translated and translated.strip():
                    # Libre also may echo input — treat as failure
                    return None
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Main translator
# ---------------------------------------------------------------------------

class Translator:
    """
    Stateful translator with built-in retry/backoff and chunking.
    Keeps category map separate for instant results.
    """

    def __init__(self, delay: float = 0.6, max_retries: int = 3):
        self.delay = delay
        self.max_retries = max_retries
        self._last_call = 0.0

    def translate_category(self, bg: str) -> str:
        """Translate category — static map first (normalized), then API fallback."""
        key = bg.strip()
        # Normalize: casefold and collapse spaces for lookup
        # But keep original case for map keys (they are Title Case)
        if key in CATEGORY_MAP:
            return CATEGORY_MAP[key]
        # Try case-insensitive
        for k, v in CATEGORY_MAP.items():
            if k.casefold() == key.casefold():
                return v
        # fallback to generic translate
        ru = self.translate(key)
        # Don't poison map with failed translation (ru == bg)
        if ru and ru != key:
            # Don't overwrite map permanently, just return
            return ru
        return key

    def _translate_single(self, text: str, src: str = "bg-BG", tgt: str = "ru-RU") -> Optional[str]:
        """Translate a single chunk (<=500 chars) with retry."""
        # Rate-limit
        now = time.time()
        wait = self.delay - (now - self._last_call)
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.2))

        for attempt in range(self.max_retries):
            result = _mymemory_translate(text, src=src, tgt=tgt)
            self._last_call = time.time()
            if result:
                return _apply_glossary(result)

            if attempt == self.max_retries - 1:
                libre = _libre_translate(text, src="bg", tgt="ru")
                if libre:
                    return _apply_glossary(libre)

            backoff = (2 ** attempt) * 0.5 + random.uniform(0, 0.3)
            time.sleep(backoff)

        return None

    def translate(self, text: str, src: str = "bg-BG", tgt: str = "ru-RU") -> str:
        """
        Translate arbitrary BG text to RU.
        - Empty / whitespace → return as-is
        - No Cyrillic → return as-is (saves API calls)
        - Long texts (>500) → chunked, translated piece-wise
        - Returns original text if all attempts fail (caller decides whether to cache)
        """
        if not text or not text.strip():
            return text

        stripped = text.strip()

        has_cyrillic = any('\u0400' <= ch <= '\u04FF' for ch in stripped)
        if not has_cyrillic:
            return text

        # Handle long texts via chunking (>500)
        if len(stripped) > 500:
            chunks = _chunk_text(stripped, max_len=450)
            translated_chunks: list[str] = []
            for chunk in chunks:
                # Skip chunks without cyrillic (URLs, version strings) — don't fail whole text
                if not any('\u0400' <= ch <= '\u04FF' for ch in chunk):
                    translated_chunks.append(chunk)
                    continue
                ru = self._translate_single(chunk, src=src, tgt=tgt)
                if ru is None:
                    # If any chunk fails, fail the whole text — don't return partial
                    print(f"[translator] WARN chunk failed, falling back to original for: {stripped[:60]!r}")
                    return text
                translated_chunks.append(ru)
            # chunks already contain separators, join directly
            if any("\n" in c for c in translated_chunks):
                result = "".join(translated_chunks)
            else:
                result = " ".join(translated_chunks)
            if len(result) < len(stripped) * 0.5:
                result = " ".join(translated_chunks)
            return _apply_glossary(result)
        result = self._translate_single(stripped, src=src, tgt=tgt)
        if result is None:
            print(f"[translator] WARN failed to translate after {self.max_retries} retries: {stripped[:80]!r}")
            return text
        return result

    def translate_description(self, text: str) -> str:
        return self.translate(text)


# Quick smoke test when run directly
if __name__ == "__main__":
    t = Translator(delay=0.3)
    for s in ["Алтернативен маркет за приложения", "Кино", "Скрийнсейвър за Android TV", "ViewBox е популярно, леко онлайн кино"]:
        print(f"  {s!r} -> {t.translate(s)!r}")
    print(f"  Category 'Маркети' -> {t.translate_category('Маркети')!r}")
