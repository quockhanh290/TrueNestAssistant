"""Free translation for broker posts: MyMemory (primary) + Lingva (fallback).

Used when a broker edits the Vietnamese version of a saved FB post —
other existing language versions are auto-translated from the edited text.
"""
import json
import logging
import urllib.parse
import urllib.request

import config

log = logging.getLogger("linh")

# MyMemory language pair codes
MYMEMORY_PAIRS = {
    "en": "vi|en",
    "ko": "vi|ko",
    "zh": "vi|zh-CN",
    "ru": "vi|ru",
}

# Lingva Translate language codes (ISO 639-1)
LINGVA_LANGS = {"en": "en", "ko": "ko", "zh": "zh", "ru": "ru"}

TIMEOUT = 10  # seconds per request

# In-memory cache: (text, target_lang) -> translated text
_cache = {}


def _mymemory(text, target_lang):
    """Translate via MyMemory API. Returns text or None."""
    pair = MYMEMORY_PAIRS.get(target_lang)
    if not pair:
        return None
    params = {"q": text, "langpair": pair}
    if config.TRANSLATION_EMAIL:
        params["de"] = config.TRANSLATION_EMAIL
    url = ("https://api.mymemory.translated.net/get?"
           + urllib.parse.urlencode(params))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TrueNestBot/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status == 429:
                log.warning("MyMemory rate limited (429)")
                return None
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        log.warning("MyMemory request failed", exc_info=True)
        return None
    # MyMemory returns responseStatus 200 on success, 429 on quota exceeded
    status = str(data.get("responseStatus", ""))
    if status == "429":
        log.warning("MyMemory quota exceeded (responseStatus 429)")
        return None
    if status != "200":
        log.warning("MyMemory bad status: %s", status)
        return None
    translated = (data.get("responseData") or {}).get("translatedText")
    if not translated or not translated.strip():
        return None
    # MyMemory sometimes returns the query back with a warning prefix
    if "QUERY LENGTH LIMIT" in translated.upper():
        return None
    return translated.strip()


def _lingva(text, target_lang):
    """Translate via Lingva Translate (free, no key). Returns text or None."""
    lang = LINGVA_LANGS.get(target_lang)
    if not lang:
        return None
    encoded = urllib.parse.quote(text, safe="")
    url = f"https://lingva.ml/api/v1/vi/{lang}/{encoded}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TrueNestBot/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status == 429:
                log.warning("Lingva rate limited (429)")
                return None
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        log.warning("Lingva request failed", exc_info=True)
        return None
    translated = data.get("translation")
    if not translated or not translated.strip():
        return None
    return translated.strip()


def translate(text, target_lang, source_lang="vi"):
    """Translate text to target_lang. Returns translated text or None.

    Chain: cache → MyMemory → Lingva → None.
    Only vi→{en,ko,zh,ru} is supported.
    """
    if not config.TRANSLATION_ENABLED:
        return None
    if source_lang != "vi":
        log.warning("translate: unsupported source lang %s", source_lang)
        return None
    if target_lang not in MYMEMORY_PAIRS:
        log.warning("translate: unsupported target lang %s", target_lang)
        return None
    if not text or not text.strip():
        return None
    text = text.strip()

    key = (text, target_lang)
    if key in _cache:
        return _cache[key]

    result = _mymemory(text, target_lang)
    if result is None:
        log.info("MyMemory failed for %s, trying Lingva", target_lang)
        result = _lingva(text, target_lang)

    if result:
        _cache[key] = result
    return result


def clear_cache():
    """Clear the in-memory translation cache (for tests)."""
    _cache.clear()
