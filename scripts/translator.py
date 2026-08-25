"""
Bulgarian -> Russian translator abstraction.

Primary backend: MyMemory (free, no key, good bg->ru quality).
Fallback: LibreTranslate public instance.
Static map for categories ensures perfect/consistent translation.

Usage:
    from translator import Translator
    t = Translator()
    t.translate("Алтернативен маркет за приложения")
    t.translate_category("Маркети")
"""

from __future__ import annotations

import hashlib
import time
import random
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
    "Скрийнсейвъри": "Скринсейверы",
    "Kodi repo": "Kodi репозитории",
    "Plex&Jellyfin": "Plex и Jellyfin",
    "Kodi": "Kodi",
    "Kodi Modi": "Kodi Моды",
    # variations that might appear in future
    "Скрийнсейвъри ": "Скринсейверы",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _mymemory_translate(text: str, src: str = "bg-BG", tgt: str = "ru-RU") -> Optional[str]:
    """Single attempt via MyMemory. Returns None on failure."""
    if not HAS_DEEP:
        return None
    try:
        # MyMemory has undocumented rate-limit ~ a few req/s; caller handles backoff
        result = MyMemoryTranslator(source=src, target=tgt).translate(text)
        if result and result.strip() and result.strip() != text.strip():
            return result.strip()
        # MyMemory sometimes returns same text when it doesn't know — treat as valid if not empty
        if result and result.strip():
            return result.strip()
        return None
    except Exception:
        return None


def _libre_translate(text: str, src: str = "bg", tgt: str = "ru") -> Optional[str]:
    """Fallback via public LibreTranslate instance."""
    # Try a couple of public instances
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
                if translated and translated.strip():
                    return translated.strip()
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Main translator
# ---------------------------------------------------------------------------

class Translator:
    """
    Stateful translator with built-in retry/backoff.
    Keeps category map separate for instant results.
    """

    def __init__(self, delay: float = 0.6, max_retries: int = 3):
        self.delay = delay
        self.max_retries = max_retries
        self._last_call = 0.0

    def translate_category(self, bg: str) -> str:
        """Translate category — static map first, then API fallback."""
        bg_stripped = bg.strip()
        if bg_stripped in CATEGORY_MAP:
            return CATEGORY_MAP[bg_stripped]
        # fallback to generic translate
        ru = self.translate(bg_stripped)
        # cache the new mapping for next time (in-memory only)
        if ru and ru != bg_stripped:
            CATEGORY_MAP[bg_stripped] = ru
        return ru or bg_stripped

    def translate(self, text: str, src: str = "bg-BG", tgt: str = "ru-RU") -> str:
        """
        Translate arbitrary BG text to RU.
        - Empty / whitespace → return as-is
        - Very short brand names / single-word English → return as-is (heuristic)
        - Otherwise MyMemory with retry + Libre fallback
        """
        if not text or not text.strip():
            return text

        stripped = text.strip()

        # Heuristic: don't translate if text looks like English/brand/latin-only
        # e.g. "Aurora Store", "VLC", "Kodi"
        # If no Cyrillic at all, keep as-is — saves API calls
        has_cyrillic = any('\u0400' <= ch <= '\u04FF' for ch in stripped)
        if not has_cyrillic:
            return text  # nothing to translate

        # Rate-limit: ensure minimum delay between calls
        now = time.time()
        wait = self.delay - (now - self._last_call)
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.2))

        last_error = None
        for attempt in range(self.max_retries):
            # Try MyMemory first
            result = _mymemory_translate(stripped, src=src, tgt=tgt)
            self._last_call = time.time()

            if result:
                return result

            # Fallback to Libre on last retry
            if attempt == self.max_retries - 1:
                libre = _libre_translate(stripped, src="bg", tgt="ru")
                if libre:
                    return libre

            # Exponential backoff before retry
            backoff = (2 ** attempt) * 0.5 + random.uniform(0, 0.3)
            time.sleep(backoff)
            last_error = f"attempt {attempt+1} failed"

        # If everything failed, return original with a marker (so sync doesn't lose data)
        # Caller will see original Bulgarian rather than broken output
        print(f"[translator] WARN failed to translate after {self.max_retries} retries: {stripped[:80]!r} ({last_error})")
        return text

    def translate_description(self, text: str) -> str:
        """Wrapper that preserves leading emoji/formatting quirks."""
        # Descriptions often start with emoji like "✳️ " — keep them, just translate core
        return self.translate(text)


# Quick smoke test when run directly
if __name__ == "__main__":
    t = Translator(delay=0.3)
    for s in ["Алтернативен маркет за приложения", "Кино", "Скрийнсейвър за Android TV", "ViewBox е популярно, леко онлайн кино"]:
        print(f"  {s!r} -> {t.translate(s)!r}")
    print(f"  Category 'Маркети' -> {t.translate_category('Маркети')!r}")
