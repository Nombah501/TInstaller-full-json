#!/usr/bin/env python3
"""
sync.py — incremental BG→RU fork sync for TInstaller JSON.

What it does:
  1. Fetch upstream https://topperbg.github.io/1.json
  2. Load local 1.json (translated) + data/translation_cache.json
  3. Diff by content hash — only new/changed Bulgarian descriptions/categories hit the translator API
  4. Merge: new apps get translated, removed apps disappear, updated apps get fresh translation, unchanged apps keep cached RU text
  5. Write updated 1.json (RU) + translation_cache.json + upstream snapshot

Incremental = fast + cheap + preserves manual fixes in cache.

Usage:
  python scripts/sync.py                  # fetch + translate diff + write
  python scripts/sync.py --force          # re-translate everything
  python scripts/sync.py --dry-run        # print stats, no write
  python scripts/sync.py --upstream PATH  # use local file instead of fetching
  python scripts/sync.py --check          # exit 1 if upstream changed and local is stale

Cache format (data/translation_cache.json):
  {
    "meta": {"updated": "2026-08-26T...", "upstream_count": 197},
    "texts": {
      "<sha16(bg_text)>": {"bg": "...", "ru": "...", "type": "description|category"}
    }
  }
  Secondary index by bg_text hash — stable across reorders. If BG text changes, hash misses and new translation is fetched.

Exit codes:
  0 — success (or dry-run, or no changes)
  1 — upstream unreachable / check shows stale
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_URL = "https://topperbg.github.io/1.json"
OUTPUT_JSON = ROOT / "1.json"
CACHE_JSON = ROOT / "data" / "translation_cache.json"
UPSTREAM_SNAPSHOT = ROOT / "data" / "upstream_snapshot.json"

# Allow running as module
sys.path.insert(0, str(Path(__file__).parent))
from translator import Translator, CATEGORY_MAP, text_hash

def fetch_upstream(url: str = UPSTREAM_URL, timeout: int = 30) -> dict:
    import urllib.request
    print(f"[sync] fetching {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "TInstaller-fork-sync/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    if "apps" not in data or not isinstance(data["apps"], list):
        raise ValueError(f"unexpected upstream shape: keys={list(data.keys())}")
    print(f"[sync] fetched {len(data['apps'])} apps from upstream")
    return data


def load_cache() -> dict:
    if CACHE_JSON.exists():
        try:
            c = json.loads(CACHE_JSON.read_text(encoding="utf-8"))
            # migrate old flat format if needed
            if "texts" in c:
                return c
            # legacy: flat {hash: ru} -> wrap
            return {"meta": {}, "texts": c}
        except Exception as e:
            print(f"[sync] WARN cache corrupt, starting fresh: {e}")
    return {"meta": {}, "texts": {}}


def save_cache(cache: dict, force: bool = False):
    CACHE_JSON.parent.mkdir(parents=True, exist_ok=True)
    # Only bump timestamp if there were actual changes or forced
    if force or cache.get("_dirty"):
        cache["meta"]["updated"] = datetime.datetime.utcnow().isoformat() + "Z"
        cache.pop("_dirty", None)
    CACHE_JSON.write_text(json.dumps({k: v for k, v in cache.items() if not k.startswith("_")}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[sync] cache saved: {len(cache['texts'])} entries -> {CACHE_JSON}")


def load_translated() -> dict | None:
    if OUTPUT_JSON.exists():
        try:
            return json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[sync] WARN existing 1.json corrupt: {e}")
    return None


def translate_incremental(upstream_apps: list[dict], cache: dict, force: bool = False) -> tuple[list[dict], dict]:
    """
    Returns (translated_apps, stats).
    Mutates cache in place (adds new entries).
    """
    translator = Translator(delay=0.6)
    texts: dict = cache.setdefault("texts", {})

    stats = {"total": len(upstream_apps), "hits": 0, "misses": 0, "categories_hit": 0, "categories_miss": 0}
    translated_apps: list[dict] = []

    # Collect unique BG texts to minimize API calls (descriptions deduplicated)
    # Build list of needed translations first, then batch with dedup
    needed_desc_hashes: dict[str, str] = {}  # hash -> bg_text
    needed_cat_hashes: dict[str, str] = {}

    for app in upstream_apps:
        for field in ("description", "category"):
            bg = app.get(field, "")
            if not bg or not bg.strip():
                continue
            h = text_hash(bg)
            if field == "description":
                if h not in texts and h not in needed_desc_hashes and not force:
                    needed_desc_hashes[h] = bg
                elif force and h not in needed_desc_hashes:
                    needed_desc_hashes[h] = bg
            else:  # category
                # categories go through static map — only unknown ones need API
                if bg.strip() in CATEGORY_MAP:
                    continue
                if h not in texts and h not in needed_cat_hashes and not force:
                    needed_cat_hashes[h] = bg
                elif force and h not in needed_cat_hashes:
                    needed_cat_hashes[h] = bg

    # Translate needed descriptions
    if needed_desc_hashes:
        print(f"[sync] translating {len(needed_desc_hashes)} new/changed descriptions...")
        for i, (h, bg) in enumerate(needed_desc_hashes.items(), 1):
            ru = translator.translate(bg)
            texts[h] = {"bg": bg, "ru": ru, "type": "description"}
            stats["misses"] += 1
            cache["_dirty"] = True
            if i % 10 == 0:
                print(f"  ... {i}/{len(needed_desc_hashes)}")
    # Hits = total unique descs that were already cached
    # Compute total unique descs
    all_desc_hashes = {text_hash(a.get("description","")) for a in upstream_apps if a.get("description","").strip()}
    stats["hits"] = len(all_desc_hashes) - len(needed_desc_hashes) if not force else 0
    if force:
        stats["hits"] = 0
        stats["misses"] = len(all_desc_hashes)

    # Translate needed categories (rare — usually 0 because of static map)
    if needed_cat_hashes:
        print(f"[sync] translating {len(needed_cat_hashes)} new categories...")
        for h, bg in needed_cat_hashes.items():
            ru = translator.translate_category(bg)
            texts[h] = {"bg": bg, "ru": ru, "type": "category"}
            stats["categories_miss"] += 1
            cache["_dirty"] = True
    all_cat_hashes = {text_hash(a.get("category","")) for a in upstream_apps if a.get("category","").strip()}
    cached_cat = sum(1 for h in all_cat_hashes if h in texts or text_hash.__doc__)
    # simpler: categories hits = total unique cats covered by static map + cache
    stats["categories_hit"] = len(all_cat_hashes) - len(needed_cat_hashes)

    # Now build translated apps using cache (+ static map for categories)
    for app in upstream_apps:
        out = dict(app)  # shallow copy

        # description
        bg_desc = app.get("description", "")
        if bg_desc and bg_desc.strip():
            h = text_hash(bg_desc)
            entry = texts.get(h)
            if entry and "ru" in entry:
                out["description"] = entry["ru"]
            elif bg_desc.strip() in CATEGORY_MAP:
                out["description"] = CATEGORY_MAP[bg_desc.strip()]
            else:
                # fallback: if not in cache (should not happen), keep original
                out["description"] = bg_desc

        # category
        bg_cat = app.get("category", "")
        if bg_cat and bg_cat.strip():
            # static map wins
            if bg_cat.strip() in CATEGORY_MAP:
                out["category"] = CATEGORY_MAP[bg_cat.strip()]
            else:
                h = text_hash(bg_cat)
                entry = texts.get(h)
                if entry:
                    out["category"] = entry["ru"]
                else:
                    # try live translate (should have been cached above)
                    out["category"] = translator.translate_category(bg_cat)

        # title: keep as-is (brand names). Only translate if purely Cyrillic Bulgarian title?
        # We intentionally do NOT translate titles to avoid breaking brand names.
        translated_apps.append(out)

    return translated_apps, stats


def main():
    ap = argparse.ArgumentParser(description="Incremental BG->RU sync for TInstaller fork")
    ap.add_argument("--force", action="store_true", help="re-translate everything")
    ap.add_argument("--dry-run", action="store_true", help="don't write files")
    ap.add_argument("--upstream", type=str, default=None, help="path to local upstream JSON instead of fetching")
    ap.add_argument("--check", action="store_true", help="exit 1 if local is stale vs upstream")
    ap.add_argument("--out", type=str, default=None, help="output path override")
    args = ap.parse_args()

    out_path = Path(args.out) if args.out else OUTPUT_JSON

    # Load upstream
    if args.upstream:
        upstream = json.loads(Path(args.upstream).read_text(encoding="utf-8"))
        print(f"[sync] loaded upstream from {args.upstream}: {len(upstream['apps'])} apps")
    else:
        try:
            upstream = fetch_upstream()
        except Exception as e:
            print(f"[sync] ERROR fetching upstream: {e}", file=sys.stderr)
            sys.exit(1)

    upstream_apps: list[dict] = upstream["apps"]

    # Check mode: compare upstream hash vs snapshot
    if args.check:
        if not UPSTREAM_SNAPSHOT.exists():
            print("[sync] --check: no snapshot, considered stale")
            sys.exit(1)
        snap = json.loads(UPSTREAM_SNAPSHOT.read_text(encoding="utf-8"))
        snap_hash = hashlib.sha256(json.dumps(snap, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        cur_hash = hashlib.sha256(json.dumps(upstream, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if snap_hash != cur_hash:
            print("[sync] --check: upstream changed, local is stale")
            sys.exit(1)
        print("[sync] --check: up to date")
        sys.exit(0)

    cache = load_cache()
    print(f"[sync] cache: {len(cache.get('texts', {}))} entries")

    translated_apps, stats = translate_incremental(upstream_apps, cache, force=args.force)

    print(f"[sync] stats: total={stats['total']} hits={stats['hits']} misses={stats['misses']} "
          f"cat_hits={stats['categories_hit']} cat_misses={stats['categories_miss']}")

    output = {"apps": translated_apps}

    if args.dry_run:
        print("[sync] dry-run, not writing")
        # preview first 2
        print(json.dumps(translated_apps[:2], ensure_ascii=False, indent=2)[:3000])
        return

    # Write output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[sync] wrote {len(translated_apps)} apps -> {out_path}")

    # Write snapshots
    UPSTREAM_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    # Save raw upstream snapshot for diff / debugging (not served, just for history)
    # Keep it compact but pretty for git diff readability
    UPSTREAM_SNAPSHOT.write_text(json.dumps(upstream, ensure_ascii=False, indent=2), encoding="utf-8")
    save_cache(cache, force=args.force)
    # Also write ru.json alias (same content) for convenience — TInstaller can use either
    ru_alias = ROOT / "ru.json"
    if ru_alias != out_path:
        ru_alias.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[sync] alias -> {ru_alias}")

    # Print summary for commit message
    print(f"[sync] done. Upstream {len(upstream_apps)} -> RU {len(translated_apps)}. "
          f"New translations: {stats['misses']} desc + {stats['categories_miss']} cat.")


if __name__ == "__main__":
    main()
