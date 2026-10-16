#!/usr/bin/env python3
"""Backfill pHash for existing listing photos that only have dHash.

For each listing with photo_urls missing entries in photo_phashes,
downloads the R2 URL to a temp file, computes pHash, and stores it via
db.add_photo_hash (preserving the existing dHash).

Usage:
    BOT_DB_PATH=broker_bot.db .venv/bin/python scripts/backfill_phash.py [--limit N] [--dry-run]

Notes:
- Downloads cost R2 egress bandwidth; run with --limit on big DBs.
- Idempotent: skips URLs that already have a pHash.
- Requires Pillow; skips gracefully when PIL is unavailable.
"""
import argparse
import os
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from photos import compute_phash  # noqa: E402


def _download(url, timeout=30):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TrueNest/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"  download failed: {url[:60]}... ({e})")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="max listings to process (0 = all)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be done, change nothing")
    args = ap.parse_args()

    db.init_db()
    try:
        from photos import _pil_ok
        pil = _pil_ok()
    except Exception:
        pil = False
    if not pil:
        print("Pillow not available — nothing to do. Install Pillow first.")
        return 1

    conn = db.connect()
    rows = conn.execute(
        "SELECT id, photo_urls, photo_hashes, photo_phashes FROM tg_listings"
        " WHERE photo_urls IS NOT NULL AND photo_urls != '[]'"
        " ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    if args.limit:
        rows = rows[:args.limit]

    import json
    listings_done = 0
    photos_done = 0
    photos_failed = 0
    for r in rows:
        lid = r["id"]
        try:
            urls = json.loads(r["photo_urls"] or "[]")
            dhashes = json.loads(r["photo_hashes"] or "{}")
            phashes = json.loads(r["photo_phashes"] or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        missing = [u for u in urls if u and u not in phashes]
        if not missing:
            continue
        if args.dry_run:
            print(f"{lid}: would backfill {len(missing)} photo(s)")
            listings_done += 1
            photos_done += len(missing)
            continue
        print(f"{lid}: backfilling {len(missing)} photo(s)...")
        for url in missing:
            data = _download(url)
            if not data:
                photos_failed += 1
                continue
            ext = os.path.splitext(url.split("?")[0])[1].lower() or ".jpg"
            fd, tmp = tempfile.mkstemp(suffix=ext)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                ph = compute_phash(tmp)
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            if not ph:
                photos_failed += 1
                continue
            if db.add_photo_hash(lid, url, dhashes.get(url), ph):
                photos_done += 1
            else:
                photos_failed += 1
        listings_done += 1

    print(f"done: {listings_done} listing(s), {photos_done} phash(es) stored,"
          f" {photos_failed} failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
