"""Shared save path for the intake bridges (WhatsApp + Zalo).

Both bridges end here: a flushed batch becomes a DRAFT listing through
the exact same backend calls the Telegram bot's own forward flow uses
(parser.parse_listing -> db.create_listing lenient), photos go through
the same perceptual-hash + R2 pipeline (photos.py), duplicates are only
ever SUGGESTED in the receipt, never auto-merged (Khanh's rule: the
broker decides when reviewing in their inventory).

Bridge listings are created as status="draft" — identical semantics to
a Telegram forward the broker has not confirmed yet.

Functions here are synchronous and UI-free so both the Python WhatsApp
bridge and the Zalo bridge's one-shot CLI (zalo_bridge/save_cli.py) can
share them.
"""
from __future__ import annotations

import logging
import os
import tempfile

import db
import parser as listing_parser
import photos as photos_mod

log = logging.getLogger(__name__)


def _content_hash(texts, photo_keys) -> str:
    """Mirror of utils.content_hash_for_listing (kept local so this module
    never imports utils -> telegram; the bridges must run anywhere)."""
    import hashlib
    norm_texts = sorted(t.strip().lower() for t in (texts or []) if t and t.strip())
    norm_photos = sorted(photo_keys or [])
    blob = "\n".join(norm_texts) + "||" + ",".join(norm_photos)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def upload_photo_bytes(data: bytes, ext: str = ".jpg") -> tuple:
    """Upload one photo (raw bytes) to R2. Returns (url, dhash, phash).

    Mirrors photos.upload_photo_sync's tail, but starts from bytes
    instead of a Telegram file_id. Hashes are computed BEFORE upload so
    dedup can use them even when the upload itself fails.
    """
    if not photos_mod.R2_ENABLED or not data:
        return None, None, None
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    import uuid
    key = f"{photos_mod.R2_PREFIX}{uuid.uuid4().hex}{ext}"
    fd, tmp = tempfile.mkstemp(suffix=ext)
    url, dhash, phash = None, None, None
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        dhash = photos_mod.compute_dhash(tmp)
        phash = photos_mod.compute_phash(tmp)
        if photos_mod._r2_put(key, tmp):
            url = f"{photos_mod.R2_PUBLIC_BASE}/{key}"
    except Exception:
        log.warning("bridge photo upload failed", exc_info=True)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return url, dhash, phash


def _summary_of(listing: dict) -> str:
    """Short human summary of a stored listing, for receipts."""
    p = (listing or {}).get("parsed") or {}
    bits = []
    if p.get("bedrooms"):
        bits.append(f"{p['bedrooms']}PN")
    if p.get("district"):
        bits.append(p["district"])
    if p.get("price_vnd"):
        v = p["price_vnd"]
        bits.append(f"{v / 1e6:g}tr" if v >= 1_000_000 else f"{v:,}đ")
    n = len((listing or {}).get("photo_urls") or [])
    if n:
        bits.append(f"+ {n} ảnh")
    return " ".join(bits) or "1 tin"


def _find_dup_suspect(broker_id: int, new_listing_id: str,
                      stored_hashes: list) -> str | None:
    """First same-broker listing sharing a near-identical photo, if any."""
    for dhash, phash in stored_hashes:
        try:
            matches = db.find_photos_by_hash(dhash, max_distance=5,
                                             exclude_id=new_listing_id,
                                             phash=phash)
        except Exception:
            log.warning("dup check failed", exc_info=True)
            return None
        for lid, _url, _dist in matches:
            other = db.get_listing(lid)
            if other and other.get("broker_id") == broker_id \
                    and other.get("status") != "deleted":
                return _summary_of(other)
    return None


def save_bridge_listing(telegram_id: int, text: str,
                        photo_datas: list, photo_keys: list = None,
                        source: str = "bridge") -> dict:
    """Create a draft listing from a flushed bridge batch.

    Returns {ok, listing_id, photos_ok, photos_failed, dup_suspect,
    missing, error}. photo_datas = raw image bytes (images only — the
    bridges drop other media before this point, per spec).
    """
    ok_limit, count, limit = db.check_listing_limit(telegram_id)
    if not ok_limit:
        return {"ok": False, "error": "limit", "count": count,
                "limit": limit, "listing_id": None}

    result = listing_parser.parse_listing(text or "", photo_count=len(photo_datas))
    fields = dict(result["fields"])
    missing = list(result["missing"])
    broker_phone = db.get_broker_phone(telegram_id)
    if broker_phone and not fields.get("primary_phone"):
        fields["primary_phone"] = broker_phone
        missing = [m for m in missing if m != "primary_phone"]

    chash = _content_hash([text or ""], photo_keys or [])
    listing_id, _dropped = db.create_listing(
        telegram_id, raw_text=text or "", photo_file_ids=[],
        parsed=fields, missing_fields=missing,
        status="draft", content_hash=chash, lenient=True,
    )

    photos_ok = 0
    photos_failed = 0
    stored_hashes = []
    for data in photo_datas:
        url, dhash, phash = upload_photo_bytes(data)
        if url:
            db.add_photo_url(listing_id, url)
            db.add_photo_hash(listing_id, url, dhash, phash)
            photos_ok += 1
            if dhash or phash:
                stored_hashes.append((dhash, phash))
        else:
            photos_failed += 1

    dup = _find_dup_suspect(telegram_id, listing_id, stored_hashes) \
        if stored_hashes else None
    log.info("bridge save (%s): broker=%s listing=%s photos %d ok/%d fail",
             source, telegram_id, listing_id, photos_ok, photos_failed)
    return {"ok": True, "listing_id": listing_id, "photos_ok": photos_ok,
            "photos_failed": photos_failed, "dup_suspect": dup,
            "missing": missing, "error": None}


def append_photos_to_listing(listing_id: str, photo_datas: list) -> dict:
    """Attach extra photos to an existing listing (supplement merge)."""
    ok = fail = 0
    for data in photo_datas:
        url, dhash, phash = upload_photo_bytes(data)
        if url:
            db.add_photo_url(listing_id, url)
            db.add_photo_hash(listing_id, url, dhash, phash)
            ok += 1
        else:
            fail += 1
    return {"ok": fail == 0, "photos_ok": ok, "photos_failed": fail}


def undo_bridge_listing(listing_id: str) -> bool:
    """Soft-delete a bridge-saved listing (the HUY undo path)."""
    try:
        db.set_listing_status(listing_id, "deleted", changed_by="broker")
        return True
    except Exception:
        log.warning("undo failed for %s", listing_id, exc_info=True)
        return False
