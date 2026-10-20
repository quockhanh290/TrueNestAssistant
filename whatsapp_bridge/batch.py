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
A batch flushed within `supp_window` of the previous flush for the same
sender is flagged as a possible supplement ("ask_supplement") so the
bridge can ask [Bổ sung vào căn vừa rồi] [Căn mới] instead of guessing.

Pairing codes, HUY LINK and button replies never enter a batch.
Reactions are ignored. Short non-listing texts inside an open batch are
treated as the broker's note on the listing.

The caller feeds normalized events (see Event) and periodically calls
tick() with the current virtual time; the engine returns action lists.
Photo bytes/download live outside the engine (photo_ids only here).
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

SHORT_MAX = 40  # chars; a text this short with no markers = chat/note


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
    kind: str              # text | image | reaction | button | keyword
    body: str = ""         # text body (kind=text/keyword) or button id
    caption: str = ""      # caption carried by an image (WhatsApp)
    photo_id: str = ""     # media id of an image event


@dataclass
class Batch:
    batch_id: int
    sender: str
    texts: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    photos: list = field(default_factory=list)   # photo_ids
    started_at: float = 0.0
    last_at: float = 0.0
    reason: str = ""         # how the batch closed: silence|hardcap|split|save_kw

    @property
    def combined_text(self) -> str:
        return "\n".join(self.texts)

    @property
    def parsed(self) -> dict:
        return parse_listing(self.combined_text)


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
        self._seq = 0

    # ---------------------------------------------------------- internals

    def _open(self, sender: str, now: float) -> Batch:
        self._seq += 1
        b = Batch(batch_id=self._seq, sender=sender, started_at=now, last_at=now)
        self.batches[sender] = b
        return b

    def _flush(self, sender: str, reason: str, now: float) -> list:
        b = self.batches.pop(sender, None)
        if b is None or (not b.texts and not b.photos and not b.notes):
            return []
        b.reason = reason
        prev = self.recent.get(sender)
        self.recent[sender] = (b.batch_id, now)
        # The broker already answered the supplement question for this burst:
        mode = self.supp_mode.get(sender)
        if mode and now <= mode["until"]:
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

    def _add_text(self, b: Batch, text: str, now: float):
        text = text.strip()
        if not text:
            return
        if has_listing_markers(text):
            b.texts.append(text)
        else:
            b.notes.append(text)
        b.last_at = now

    # ---------------------------------------------------------- public

    def on_event(self, ev: Event) -> list:
        now = self._now()
        sender = ev.sender

        if ev.kind == "reaction":
            return [("ignore", ev)]
        if ev.kind == "button":
            return [("immediate", ev)]

        if ev.kind == "keyword":
            kw = (ev.body or "").strip().upper()
            if kw == "LUU":
                return self._flush(sender, "save_kw", now)
            if kw == "BO":
                if self.batches.pop(sender, None) is not None:
                    return [("cancel", sender)]
                return [("ignore_chat", ev)]
            return [("immediate", ev)]  # HUY LINK etc.

        if ev.kind == "text" and is_pairing_code(ev.body):
            return [("immediate", ev)]

        if ev.kind == "image":
            b = self.batches.get(sender)
            if b is None:
                b = self._open(sender, now)
            b.photos.append(ev.photo_id or f"photo-{len(b.photos)}")
            b.last_at = now
            if ev.caption:
                self._add_text(b, ev.caption, now)
            return []

        if ev.kind == "text":
            text = (ev.body or "").strip()
            b = self.batches.get(sender)
            if b is not None and b.texts and has_listing_markers(text):
                # second full listing -> close current, start new one
                acts = self._flush(sender, "split", now)
                b = self._open(sender, now)
                self._add_text(b, text, now)
                return acts
            if b is None:
                if not has_listing_markers(text) and len(text) <= SHORT_MAX:
                    return [("ignore_chat", ev)]
                b = self._open(sender, now)
            self._add_text(b, text, now)
            return []

        return [("ignore", ev)]

    def tick(self) -> list:
        now = self._now()
        acts = []
        for sender, b in list(self.batches.items()):
            if now - b.started_at >= self.hard_cap:
                acts += self._flush(sender, "hardcap", now)
            elif now - b.last_at >= self.silence:
                acts += self._flush(sender, "silence", now)
        return acts
