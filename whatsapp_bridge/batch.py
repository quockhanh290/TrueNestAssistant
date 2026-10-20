"""Channel-agnostic message batching engine for the intake bridges.

Brokers forward listings as SEQUENCES of messages (text and photos are
always separate events on WhatsApp Cloud API and always separate messages
on Zalo). This engine groups one sender's events into ONE batch so the
backend intake can process a whole listing at once.

Close-of-batch rules (content first, time as fallback):
  1. A second full-listing text arrives -> current batch flushes ("split").
  2. Broker sends LUU keyword -> flush with save intent. BO -> cancel.
  3. Silence for `silence` seconds since the last event -> flush.
  4. Batch older than `hard_cap` seconds -> flush regardless. The cap is
     generous (180s) so a slow photo selection is never split; it only
     guards against a pathological endless stream.
A photo/media-only batch flushed within `supp_window` of the previous
flush for the same sender is flagged as a possible supplement
("ask_supplement") so the bridge can ask [Bổ sung vào căn vừa rồi]
[Căn mới] instead of guessing. Batches WITH their own listing text are
always new listings and never merge.

Robustness rules:
  - Duplicate platform events (Meta webhook retries share the same
    message id) are dropped via a bounded per-sender seen-set.
  - Identical texts and repeated photo ids inside a batch are deduped.
  - Videos, voice notes, documents, location pins and contact cards are
    collected as media (never silently dropped); captions on any media
    count as batch text.
  - A retract event (Zalo message recall) removes the targeted photo /
    media / text from the still-open batch.
  - HUY LINK cancels any open batch (nothing may flush under a dead link).
  - LUU with no open batch is a safe no-op.

The caller feeds normalized events (see Event) and periodically calls
tick() with the current virtual time; the engine returns action lists.
Photo bytes/download live outside the engine (media ids only here).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

# ------------------------------------------------------------------ parse

PRICE_RE = re.compile(
    r"(\d[\d.,\s]*)\s*(tỷ|ty|tr|triệu|trieu|million|k)\b", re.IGNORECASE
)
BED_RE = re.compile(r"(\d+)\s*(pn|phòng ngủ|phong ngu|bedrooms?|br)\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(0\d{9})(?!\d)")
DISTRICTS = [
    "Sơn Trà", "Hải Châu", "Ngũ Hành Sơn", "Cẩm Lệ", "Thanh Khê",
    "Liên Chiểu", "An Thượng", "Mỹ Khê", "Non Nước", "Hội An",
]
PAIRING_RE = re.compile(r"WA-[A-Z2-9]{6}|ZN-[A-Z2-9]{6}")

SHORT_MAX = 40        # chars; a text this short with no markers = chat/note
MEDIA_KINDS = ("image", "video", "audio", "document", "location", "contact")
SEEN_KEEP = 300       # message ids remembered per sender for dedup


def parse_listing(text: str) -> dict:
    out = {}
    m = PRICE_RE.search(text or "")
    if m:
        num = float(m.group(1).replace(",", ".").replace(" ", ""))
        unit = m.group(2).lower()
        mult = {"tỷ": 1e9, "ty": 1e9, "tr": 1e6, "triệu": 1e6,
                "trieu": 1e6, "million": 1e6, "k": 1e3}.get(unit, 1)
        out["price_vnd"] = int(num * mult)
    m = BED_RE.search(text or "")
    if m:
        out["bedrooms"] = int(m.group(1))
    m = PHONE_RE.search(text or "")
    if m:
        out["phone_in_text"] = m.group(1)
    for d in DISTRICTS:
        if re.search(re.escape(d), text or "", re.IGNORECASE):
            out["district"] = d
            break
    return out


def has_listing_markers(text: str) -> bool:
    return bool(parse_listing(text))


def is_pairing_code(text: str) -> bool:
    return bool(PAIRING_RE.fullmatch((text or "").strip().upper()))


# ------------------------------------------------------------------ model

@dataclass
class Event:
    sender: str            # channel sender key (phone / zalo_id)
    kind: str              # text | image | video | audio | document |
                           # location | contact | reaction | button |
                           # keyword | retract
    body: str = ""         # text body (kind=text/keyword) or button id
    caption: str = ""      # caption carried by a media event
    photo_id: str = ""     # media id of a media event
    msg_id: str = ""       # platform message id (dedup + retract lookup)
    target_id: str = ""    # kind=retract: msg_id/photo_id being recalled
    meta: dict = field(default_factory=dict)  # e.g. {"lat": .., "lng": ..}


@dataclass
class Batch:
    batch_id: int
    sender: str
    texts: list = field(default_factory=list)      # listing texts
    notes: list = field(default_factory=list)      # broker chat notes
    photos: list = field(default_factory=list)     # image media ids
    others: list = field(default_factory=list)     # (kind, media_id)
    locations: list = field(default_factory=list)  # location meta dicts
    text_ids: dict = field(default_factory=dict)   # msg_id -> listing text
    started_at: float = 0.0
    last_at: float = 0.0
    reason: str = ""         # silence|hardcap|split|save_kw

    @property
    def combined_text(self) -> str:
        return "\n".join(self.texts)

    @property
    def parsed(self) -> dict:
        return parse_listing(self.combined_text)

    @property
    def is_multi(self) -> bool:
        """One pasted message holding 2+ listings (2 phones or 2 prices)."""
        t = self.combined_text
        return len(set(PHONE_RE.findall(t))) >= 2 or len(PRICE_RE.findall(t)) >= 2


# ------------------------------------------------------------------ engine

class Batcher:
    def __init__(self, now=None, silence: float = 15.0, hard_cap: float = 180.0,
                 supp_window: float = 300.0):
        self._now = now or time.time
        self.silence = silence
        self.hard_cap = hard_cap
        self.supp_window = supp_window
        self.batches: dict[str, Batch] = {}
        self.recent: dict[str, tuple[int, float]] = {}  # sender -> (batch_id, flushed_at)
        self.pending_supp: dict[str, tuple[int, int]] = {}  # sender -> (batch_id, prev_batch_id)
        self.supp_mode: dict[str, dict] = {}  # sender -> {mode, target, until}
        self._seen: dict[str, dict[str, float]] = {}  # sender -> msg_id -> ts
        self._seq = 0

    # ---------------------------------------------------------- internals

    def _open(self, sender: str, now: float) -> Batch:
        self._seq += 1
        b = Batch(batch_id=self._seq, sender=sender, started_at=now, last_at=now)
        self.batches[sender] = b
        return b

    def _is_duplicate(self, sender: str, msg_id: str, now: float) -> bool:
        if not msg_id:
            return False
        seen = self._seen.setdefault(sender, {})
        if msg_id in seen:
            return True
        seen[msg_id] = now
        if len(seen) > SEEN_KEEP:  # prune the oldest half
            for k in sorted(seen, key=seen.get)[: SEEN_KEEP // 2]:
                del seen[k]
        return False

    def _flush(self, sender: str, reason: str, now: float) -> list:
        b = self.batches.pop(sender, None)
        if b is None or (not b.texts and not b.photos and not b.notes
                         and not b.others):
            return []
        b.reason = reason
        prev = self.recent.get(sender)
        self.recent[sender] = (b.batch_id, now)
        # The broker already answered the supplement question for this burst.
        # Merge mode applies ONLY to batches without their own listing text:
        # a full listing text is always a new listing, never a supplement.
        mode = self.supp_mode.get(sender)
        if mode and now <= mode["until"] and not b.texts:
            if mode["mode"] == "merge":
                return [("merge_into", b, mode["target"])]
            return [("flush", b)]  # mode == "new": always a fresh listing
        # A follow-up batch WITHOUT its own listing text, flushed soon
        # after another batch, is likely extra photos for the previous
        # listing -> ask, don't guess. A batch WITH full listing text is
        # always a new listing (bulk-forwarding brokers must not be
        # pestered with the supplement question).
        if (prev and not b.texts
                and now - prev[1] <= self.supp_window
                and prev[0] != b.batch_id):
            self.pending_supp[sender] = (b.batch_id, prev[0])
            return [("ask_supplement", b, prev[0])]
        return [("flush", b)]

    def resolve_supplement(self, sender: str, merge: bool):
        """Record the broker's answer to a supplement question.

        merge=True  -> broker confirmed the extra photos belong to the
                       previous listing; later batches in this burst
                       auto-merge into it without re-asking.
        merge=False -> they're a separate listing; stop asking for the
                       rest of the burst.
        """
        pend = self.pending_supp.pop(sender, None)
        if pend is None:
            return  # double-tap / late click: keep the existing supp_mode
        target = pend[1]
        self.supp_mode[sender] = {
            "mode": "merge" if merge else "new",
            "target": target,
            "until": self._now() + self.supp_window,
        }

    def _add_text(self, b: Batch, text: str, now: float, msg_id: str = ""):
        text = (text or "").strip()
        if not text:
            return
        if has_listing_markers(text):
            if text not in b.texts:  # broker pasted the same text twice
                b.texts.append(text)
                if msg_id:
                    b.text_ids[msg_id] = text
        else:
            if text not in b.notes:
                b.notes.append(text)
        b.last_at = now

    def _retract(self, sender: str, target_id: str) -> list:
        b = self.batches.get(sender)
        if b is None or not target_id:
            return [("ignore", sender)]
        removed = False
        if target_id in b.photos:
            b.photos.remove(target_id)
            removed = True
        before = len(b.others)
        b.others = [o for o in b.others if o[1] != target_id]
        removed = removed or len(b.others) != before
        t = b.text_ids.pop(target_id, None)
        if t is not None and t in b.texts:
            b.texts.remove(t)
            removed = True
        if not removed:
            return [("ignore", sender)]
        if not b.texts and not b.photos and not b.notes and not b.others:
            self.batches.pop(sender, None)  # everything recalled: batch gone
            return [("cancel", sender)]
        return [("retracted", sender, target_id)]

    # ---------------------------------------------------------- public

    def on_event(self, ev: Event) -> list:
        now = self._now()
        sender = ev.sender

        if self._is_duplicate(sender, ev.msg_id, now):
            return [("duplicate", ev)]

        if ev.kind == "reaction":
            return [("ignore", ev)]
        if ev.kind == "button":
            return [("immediate", ev)]
        if ev.kind == "retract":
            return self._retract(sender, ev.target_id)

        if ev.kind == "keyword":
            kw = (ev.body or "").strip().upper()
            if kw == "HUY LINK":
                acts = []
                if self.batches.pop(sender, None) is not None:
                    acts.append(("cancel", sender))
                acts.append(("immediate", ev))
                return acts
            if kw == "LUU":
                return self._flush(sender, "save_kw", now)
            if kw == "BO":
                if self.batches.pop(sender, None) is not None:
                    return [("cancel", sender)]
                return [("ignore_chat", ev)]
            return [("immediate", ev)]

        if ev.kind == "text" and is_pairing_code(ev.body):
            return [("immediate", ev)]

        if ev.kind in MEDIA_KINDS:
            b = self.batches.get(sender)
            if b is None:
                b = self._open(sender, now)
            if ev.kind == "image":
                pid = ev.photo_id or f"photo-{len(b.photos)}"
                if pid not in b.photos:  # same photo forwarded twice
                    b.photos.append(pid)
            else:
                entry = (ev.kind, ev.photo_id or ev.msg_id)
                if entry not in b.others:
                    b.others.append(entry)
                if ev.kind == "location" and ev.meta:
                    b.locations.append(dict(ev.meta))
            b.last_at = now
            if ev.caption:
                self._add_text(b, ev.caption, now, ev.msg_id)
            return []

        if ev.kind == "text":
            text = (ev.body or "").strip()
            b = self.batches.get(sender)
            if b is not None and b.texts and has_listing_markers(text):
                if text in b.texts:
                    # accidental double-paste of the same listing: dedupe,
                    # don't split. (A genuinely re-forwarded listing arrives
                    # after the previous batch has flushed.)
                    self._add_text(b, text, now, ev.msg_id)
                    return []
                # second, DIFFERENT full listing -> close current, start new
                acts = self._flush(sender, "split", now)
                b = self._open(sender, now)
                self._add_text(b, text, now, ev.msg_id)
                return acts
            if b is None:
                if not has_listing_markers(text) and len(text) <= SHORT_MAX:
                    return [("ignore_chat", ev)]
                b = self._open(sender, now)
            self._add_text(b, text, now, ev.msg_id)
            return []

        return [("ignore", ev)]  # stickers and other unknown kinds

    def tick(self) -> list:
        now = self._now()
        acts = []
        for sender, b in list(self.batches.items()):
            if now - b.started_at >= self.hard_cap:
                acts += self._flush(sender, "hardcap", now)
            elif now - b.last_at >= self.silence:
                acts += self._flush(sender, "silence", now)
        return acts
