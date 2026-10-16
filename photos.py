"""R2 photo upload for broker listing photos.

When a broker sends photos via Telegram, we store the Telegram file_id
(for sending back through the bot) AND upload to Cloudflare R2 (so the
web app can display them via HTTP URLs).

R2 layout:  broker/<uuid>.jpg
Public URL: https://pub-fbff0cd4faa041bf9e05aeb9fa79fb7a.r2.dev/broker/<uuid>.jpg

Uploads run in the background (asyncio.create_task) so the bot responds
fast. Failures are logged but never break the intake flow.
"""
import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
import urllib.request
import uuid

log = logging.getLogger(__name__)

CF_SCRIPT = os.path.expanduser(
    "~/workspace/custom-connectors/custom.legacy-cloudflare/bin/cf.py")
R2_ACCOUNT = "cbd7471fd195b222bda1aaa1f60ddad5"
R2_BUCKET = "rental-images"
R2_PREFIX = "broker/"
R2_PUBLIC_BASE = "https://pub-fbff0cd4faa041bf9e05aeb9fa79fb7a.r2.dev"

# Allow override via env (tests, staging).
R2_ENABLED = os.environ.get("R2_PHOTOS_ENABLED", "1") == "1"

# Cached result of the PIL availability probe.
_PIL_OK = None


def _pil_ok():
    """True if PIL is importable. Cached."""
    global _PIL_OK
    if _PIL_OK is None:
        try:
            from PIL import Image  # noqa: F401
            _PIL_OK = True
        except ImportError:
            _PIL_OK = False
    return _PIL_OK


def compute_dhash(image_path):
    """Compute a 64-bit dHash (16-char hex) for an image file.

    Same algorithm as the rental pipeline (backfill_phashes.py):
    grayscale, resize to 9x8 LANCZOS, compare adjacent pixels.

    Returns None when PIL is unavailable — callers must treat None as
    "no hash", never as a failure. Uploads must still work without PIL.
    """
    if not _pil_ok():
        return None
    try:
        from PIL import Image
        im = Image.open(image_path).convert("L").resize((9, 8),
                                                        Image.LANCZOS)
        px = list(im.getdata())
        bits = 0
        for r in range(8):
            for c in range(8):
                bits = (bits << 1) | (
                    1 if px[r * 9 + c] > px[r * 9 + c + 1] else 0)
        return format(bits, "016x")
    except Exception:
        log.warning("dhash failed for %s", image_path, exc_info=True)
        return None


def hamming_distance(h1, h2):
    """Hamming distance between two 16-char hex dhashes."""
    try:
        return bin(int(h1, 16) ^ int(h2, 16)).count("1")
    except (TypeError, ValueError):
        return 64  # uncomparable → max distance


def _dct_1d(vec):
    """Orthonormal DCT-II of a length-N vector (pure Python).

    No numpy/scipy dependency — 32x32 images need only ~65k
    multiply-adds for the full 2D transform, fast enough in
    pure Python and works on any machine with PIL (e.g. Khanh's
    Windows box).
    """
    import math
    n = len(vec)
    out = [0.0] * n
    for k in range(n):
        s = 0.0
        for i in range(n):
            s += vec[i] * math.cos(math.pi / n * (i + 0.5) * k)
        out[k] = s * (math.sqrt(1.0 / n) if k == 0
                      else math.sqrt(2.0 / n))
    return out


def _dct_2d(matrix):
    """Separable 2D DCT-II: rows then columns."""
    rows = [_dct_1d(r) for r in matrix]
    tcols = [_dct_1d(list(c)) for c in zip(*rows)]
    return [list(r) for r in zip(*tcols)]


def compute_phash(image_path):
    """Compute a 64-bit pHash (16-char hex) for an image file.

    Classic DCT perceptual hash: grayscale, resize to 32x32 LANCZOS,
    2D-DCT, keep top-left 8x8 low-frequency coefficients, median
    threshold -> 64 bits.

    Complements dHash: dHash catches small edits/crops (gradient
    based), pHash catches resizes/recompressions/recolors (frequency
    based). Either one firing suggests a duplicate.

    Returns None when PIL is unavailable — callers must treat None as
    "no hash", never as a failure. Uploads must still work without PIL.
    """
    if not _pil_ok():
        return None
    try:
        from PIL import Image
        im = Image.open(image_path).convert("L").resize((32, 32),
                                                        Image.LANCZOS)
        px = list(im.getdata())
        grid = [px[i * 32:(i + 1) * 32] for i in range(32)]
        dct = _dct_2d(grid)
        coeffs = [dct[r][c] for r in range(8) for c in range(8)]
        median = sorted(coeffs)[len(coeffs) // 2]
        bits = 0
        for v in coeffs:
            bits = (bits << 1) | (1 if v > median else 0)
        return format(bits, "016x")
    except Exception:
        log.warning("phash failed for %s", image_path, exc_info=True)
        return None


def _get_file_path(file_id, bot_token, timeout=15):
    """Call Telegram getFile API, return file_path or None."""
    url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        if data.get("ok"):
            return data["result"].get("file_path")
    except Exception:
        log.warning("getFile failed for %s", file_id[:20], exc_info=True)
    return None


def _download_file(file_path, bot_token, timeout=30):
    """Download file bytes from Telegram servers."""
    url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        log.warning("download failed for %s", file_path, exc_info=True)
    return None


def _r2_put(key, filepath, timeout=120):
    """Upload a local file to R2 via cf.py. Returns True on success."""
    try:
        p = subprocess.run(
            [sys.executable, CF_SCRIPT, "r2-put",
             R2_ACCOUNT, R2_BUCKET, key, filepath],
            capture_output=True, text=True, timeout=timeout)
        if p.returncode == 0:
            return True
        log.warning("r2-put failed: %s %s", p.returncode,
                    (p.stderr or "")[:200])
    except Exception:
        log.warning("r2-put exception", exc_info=True)
    return False


def upload_photo_sync(file_id, bot_token):
    """Upload one Telegram photo to R2. Returns (public_url, dhash, phash).

    dhash/phash are 16-char hex strings, or None when PIL is unavailable /
    hashing failed. Upload is never blocked by a missing hash.

    Synchronous — call from a thread or background task, never from the
    bot's event loop directly.
    """
    if not R2_ENABLED:
        return None, None, None
    if not bot_token or not file_id:
        return None, None, None
    file_path = _get_file_path(file_id, bot_token)
    if not file_path:
        return None, None, None
    data = _download_file(file_path, bot_token)
    if not data:
        return None, None, None
    # Guess extension from Telegram file_path (usually .jpg).
    ext = os.path.splitext(file_path)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    key = f"{R2_PREFIX}{uuid.uuid4().hex}{ext}"
    fd, tmp = tempfile.mkstemp(suffix=ext)
    url, dhash, phash = None, None, None
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        # Compute perceptual hashes BEFORE upload so dedup can use them
        # even if the R2 upload later fails.
        dhash = compute_dhash(tmp)
        phash = compute_phash(tmp)
        if _r2_put(key, tmp):
            url = f"{R2_PUBLIC_BASE}/{key}"
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return url, dhash, phash


async def upload_photo(file_id, bot_token):
    """Async wrapper: runs the blocking upload in a thread.

    Returns (public_url, dhash, phash) — see upload_photo_sync.
    """
    return await asyncio.to_thread(upload_photo_sync, file_id, bot_token)


async def upload_listing_photos(listing_id, file_ids, bot_token, db_add_fn):
    """Upload all photos for a listing in the background.

    db_add_fn(listing_id, url, dhash, phash) is called for each successful
    upload (hashes may be None). Failures are logged and skipped — the
    listing still works via file_id.

    Returns the list of (url, dhash, phash) tuples for successful uploads,
    so callers can run post-upload dedup checks.
    """
    if not file_ids:
        return []
    done = []
    for fid in file_ids:
        try:
            url, dhash, phash = await upload_photo(fid, bot_token)
            if url:
                try:
                    db_add_fn(listing_id, url, dhash, phash)
                except Exception:
                    log.warning("db_add_fn failed for %s", listing_id,
                                exc_info=True)
                else:
                    done.append((url, dhash, phash))
            else:
                log.warning("R2 upload returned None for listing %s",
                            listing_id)
        except Exception:
            log.warning("upload_listing_photos failed for %s", listing_id,
                        exc_info=True)
    return done
