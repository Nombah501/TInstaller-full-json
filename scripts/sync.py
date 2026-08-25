#!/usr/bin/env python3
"""
sync.py — incremental BG→RU fork sync for TInstaller JSON.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
import time
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_URL = "https://topperbg.github.io/1.json"
OUTPUT_JSON = ROOT / "1.json"
CACHE_JSON = ROOT / "data" / "translation_cache.json"
UPSTREAM_SNAPSHOT = ROOT / "data" / "upstream_snapshot.json"

sys.path.insert(0, str(Path(__file__).parent))
from translator import Translator, CATEGORY_MAP, text_hash

def fetch_upstream(url: str = UPSTREAM_URL, timeout: int = 30, retries: int = 3) -> dict:
    import urllib.request
    import urllib.error
    last_err = None
    for attempt in range(retries):
        try:
            print(f"[sync] fetching {url} (attempt {attempt+1}/{retries}) ...")
            req = urllib.request.Request(url, headers={"User-Agent": "TInstaller-fork-sync/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            if "apps" not in data or not isinstance(data["apps"], list):
                raise ValueError(f"unexpected upstream shape: keys={list(data.keys())}")
            print(f"[sync] fetched {len(data['apps'])} apps from upstream")
            return data
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError) as e:
            last_err = e
            print(f"[sync] fetch attempt {attempt+1} failed: {e}")
            if attempt < retries - 1:
                backoff = (2 ** attempt) * 2
                print(f"[sync] retrying in {backoff}s...")
                time.sleep(backoff)
    raise RuntimeError(f"failed to fetch upstream after {retries} attempts: {last_err}")

def load_cache() -> dict:
    if CACHE_JSON.exists():
        try:
            c = json.loads(CACHE_JSON.read_text(encoding="utf-8"))
            if "texts" in c:
                return c
            return {"meta": {}, "texts": c}
        except Exception as e:
            print(f"[sync] WARN cache corrupt, starting fresh: {e}")
    return {"meta": {}, "texts": {}}

def save_cache(cache: dict, force: bool = False):
    CACHE_JSON.parent.mkdir(parents=True, exist_ok=True)
    if force or cache.get("_dirty"):
        cache["meta"]["updated"] = datetime.datetime.utcnow().isoformat() + "Z"
        cache.pop("_dirty", None)
    # atomic write
    data = json.dumps({k: v for k, v in cache.items() if not k.startswith("_")}, ensure_ascii=False, indent=2)
    _atomic_write(CACHE_JSON, data)
    print(f"[sync] cache saved: {len(cache['texts'])} entries -> {CACHE_JSON}")

def load_translated() -> dict | None:
    if OUTPUT_JSON.exists():
        try:
            return json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[sync] WARN existing 1.json corrupt: {e}")
    return None

def _atomic_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".tmp.")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except:
            pass
        raise

def translate_incremental(upstream_apps: list[dict], cache: dict, force: bool = False) -> tuple[list[dict], dict]:
    translator = Translator(delay=0.6)
    texts: dict = cache.setdefault("texts", {})
    stats = {"total": len(upstream_apps), "hits": 0, "misses": 0, "categories_hit": 0, "categories_miss": 0}
    translated_apps: list[dict] = []

    # Deduplicate across descriptions and categories via single needed dict
    needed: dict[str, str] = {}  # hash -> bg_text (for descriptions)
    needed_cat: dict[str, str] = {}

    for app in upstream_apps:
        for field in ("description", "category"):
            bg = app.get(field, "")
            if not bg or not bg.strip():
                continue
            h = text_hash(bg)
            if h in texts and not force:
                continue
            # Categories covered by static map never need API
            if field == "category" and bg.strip() in CATEGORY_MAP:
                continue
            # Also check case-insensitive for categories
            if field == "category":
                found = False
                for k in CATEGORY_MAP:
                    if k.casefold() == bg.strip().casefold():
                        found = True
                        break
                if found:
                    continue
            if field == "description":
                if h not in needed:
                    needed[h] = bg
            else:
                if h not in needed and h not in needed_cat:
                    needed_cat[h] = bg

    # Translate needed descriptions (chunking handled inside Translator)
    if needed:
        print(f"[sync] translating {len(needed)} new/changed descriptions...")
        for i, (h, bg) in enumerate(needed.items(), 1):
            ru = translator.translate(bg)
            # Don't poison cache if translation failed (returned original)
            if ru.strip() == bg.strip():
                print(f"[sync] WARN skip caching untranslated: {bg[:60]!r}")
                stats["misses"] += 1
                continue
            texts[h] = {"bg": bg, "ru": ru, "type": "description"}
            cache["_dirty"] = True
            stats["misses"] += 1
            if i % 10 == 0:
                print(f"  ... {i}/{len(needed)}")

    all_desc_hashes = {text_hash(a.get("description","")) for a in upstream_apps if a.get("description","").strip()}
    stats["hits"] = len(all_desc_hashes) - len(needed) if not force else 0

    if needed_cat:
        print(f"[sync] translating {len(needed_cat)} new categories...")
        for h, bg in needed_cat.items():
            ru = translator.translate_category(bg)
            if ru.strip() == bg.strip():
                print(f"[sync] WARN skip caching untranslated category: {bg!r}")
                stats["categories_miss"] += 1
                continue
            texts[h] = {"bg": bg, "ru": ru, "type": "category"}
            cache["_dirty"] = True
            stats["categories_miss"] += 1

    all_cat_hashes = {text_hash(a.get("category","")) for a in upstream_apps if a.get("category","").strip()}
    stats["categories_hit"] = len(all_cat_hashes) - len(needed_cat)

    # Build translated apps
    for app in upstream_apps:
        out = dict(app)
        bg_desc = app.get("description", "")
        if bg_desc and bg_desc.strip():
            h = text_hash(bg_desc)
            entry = texts.get(h)
            if entry and "ru" in entry:
                out["description"] = entry["ru"]
            elif bg_desc.strip() in CATEGORY_MAP:
                out["description"] = CATEGORY_MAP[bg_desc.strip()]
            else:
                # check case-insensitive
                mapped = None
                for k, v in CATEGORY_MAP.items():
                    if k.casefold() == bg_desc.strip().casefold():
                        mapped = v
                        break
                out["description"] = mapped if mapped else bg_desc
        bg_cat = app.get("category", "")
        if bg_cat and bg_cat.strip():
            if bg_cat.strip() in CATEGORY_MAP:
                out["category"] = CATEGORY_MAP[bg_cat.strip()]
            else:
                # case-insensitive check
                mapped = None
                for k, v in CATEGORY_MAP.items():
                    if k.casefold() == bg_cat.strip().casefold():
                        mapped = v
                        break
                if mapped:
                    out["category"] = mapped
                else:
                    h = text_hash(bg_cat)
                    entry = texts.get(h)
                    if entry:
                        out["category"] = entry["ru"]
                    else:
                        # Don't hammer API per app if category translation previously failed
                        out["category"] = bg_cat
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

    if args.upstream:
        upstream = json.loads(Path(args.upstream).read_text(encoding="utf-8"))
        print(f"[sync] loaded upstream from {args.upstream}: {len(upstream['apps'])} apps")
    else:
        try:
            upstream = fetch_upstream()
        except Exception as e:
            # Try fallback to snapshot if available
            if UPSTREAM_SNAPSHOT.exists():
                print(f"[sync] fetch failed, falling back to snapshot: {e}", file=sys.stderr)
                upstream = json.loads(UPSTREAM_SNAPSHOT.read_text(encoding="utf-8"))
                print(f"[sync] fallback: {len(upstream['apps'])} apps from snapshot")
            else:
                print(f"[sync] ERROR fetching upstream: {e}", file=sys.stderr)
                sys.exit(1)

    upstream_apps: list[dict] = upstream["apps"]

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
        print(json.dumps(translated_apps[:2], ensure_ascii=False, indent=2)[:3000])
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(out_path, json.dumps(output, ensure_ascii=False, indent=2))
    print(f"[sync] wrote {len(translated_apps)} apps -> {out_path}")

    UPSTREAM_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(UPSTREAM_SNAPSHOT, json.dumps(upstream, ensure_ascii=False, indent=2))
    save_cache(cache, force=args.force)

    ru_alias = ROOT / "ru.json"
    if ru_alias != out_path:
        _atomic_write(ru_alias, json.dumps(output, ensure_ascii=False, indent=2))
        print(f"[sync] alias -> {ru_alias}")

    print(f"[sync] done. Upstream {len(upstream_apps)} -> RU {len(translated_apps)}. "
          f"New translations: {stats['misses']} desc + {stats['categories_miss']} cat.")

if __name__ == "__main__":
    main()
