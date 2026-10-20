#!/usr/bin/env python3
"""Behavior-case simulator for the batching engine.

Replays realistic broker behavior as normalized channel events against
whatsapp_bridge.batch.Batcher on a VIRTUAL clock, then asserts the
grouping decisions. This validates the DECISION LAYER, not the platform:
it proves our batching logic is correct for every designed behavior case.
Live platform behavior (real webhook timing/caption placement) still
needs the live test with Meta's test number.

Usage: python3 simulate.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from batch import Batcher, Event  # noqa: E402

LIST_A = "Cho thuê 2PN Sơn Trà 15tr/tháng, liên hệ 0912345678"
LIST_B = "Cho thuê 1PN An Thượng 9tr, full nội thất, gọi 0987654321"
LIST_C = "Villa 4PN Hội An 35tr/tháng, hồ bơi riêng, 0933111222"


class Sim:
    def __init__(self):
        self.t = 0.0
        self.b = Batcher(now=lambda: self.t)
        self.actions = []

    def feed(self, dt, ev: Event):
        self.t += dt
        self.actions += self.b.on_event(ev)

    def advance(self, seconds, step=2.0):
        end = self.t + seconds
        while self.t < end:
            self.t = min(self.t + step, end)
            self.actions += self.b.tick()

    def flushes(self):
        return [a for a in self.actions if a[0] == "flush"]

    def supplements(self):
        return [a for a in self.actions if a[0] == "ask_supplement"]

    def cancels(self):
        return [a for a in self.actions if a[0] == "cancel"]


def txt(sender, body):
    return Event(sender=sender, kind="text", body=body)


def img(sender, pid, caption=""):
    return Event(sender=sender, kind="image", photo_id=pid, caption=caption)


def kw(sender, word):
    return Event(sender=sender, kind="keyword", body=word)


def react(sender):
    return Event(sender=sender, kind="reaction")


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


S = "84912345678"

# Case 1: WhatsApp forward block (caption on first image, 13 images total)
s = Sim()
s.feed(0, img(S, "p0", caption=LIST_A))
for i in range(1, 13):
    s.feed(0.15, img(S, f"p{i}"))
s.advance(20)
f = s.flushes()
check("1.forward block -> 1 batch", len(f) == 1 and len(f[0][1].photos) == 13,
      f"batches={len(f)}")
check("1.caption parsed", f[0][1].parsed.get("price_vnd") == 15_000_000
      and f[0][1].parsed.get("district") == "Sơn Trà",
      f"parsed={f[0][1].parsed}" if f else "")

# Case 2: Zalo style text-first then photos
s = Sim()
s.feed(0, txt(S, LIST_A))
for i in range(5):
    s.feed(2, img(S, f"p{i}"))
s.advance(20)
f = s.flushes()
check("2.text-first -> 1 batch, 5 photos",
      len(f) == 1 and len(f[0][1].photos) == 5 and len(f[0][1].texts) == 1)

# Case 3: photos first, text after
s = Sim()
for i in range(5):
    s.feed(0.2, img(S, f"p{i}"))
s.feed(8, txt(S, LIST_A))
s.advance(20)
f = s.flushes()
check("3.photos-first -> 1 batch", len(f) == 1
      and len(f[0][1].photos) == 5 and len(f[0][1].texts) == 1)

# Case 4: text only
s = Sim()
s.feed(0, txt(S, LIST_B))
s.advance(20)
f = s.flushes()
check("4.text-only flush", len(f) == 1 and not f[0][1].photos
      and f[0][1].parsed.get("bedrooms") == 1)

# Case 5: photos only, no text
s = Sim()
for i in range(13):
    s.feed(0.15, img(S, f"p{i}"))
s.advance(20)
f = s.flushes()
check("5.photos-only -> 1 flush, no text",
      len(f) == 1 and len(f[0][1].photos) == 13 and not f[0][1].texts)

# Case 6: supplement within 5 min -> ask, not auto-merge
s = Sim()
s.feed(0, txt(S, LIST_A))
s.advance(20)
first = s.flushes()[0][1].batch_id
s.advance(120)
s.feed(0, img(S, "extra1"))
s.feed(0.5, img(S, "extra2"))
s.advance(20)
sup = s.supplements()
check("6.supp photos -> ask_supplement", len(sup) == 1
      and len(sup[0][1].photos) == 2 and sup[0][2] == first,
      f"prev_id={sup[0][2] if sup else '?'}")

# Case 7: bulk-forward 3 listings -> each own batch, NO supplement pestering
s = Sim()
s.feed(0, txt(S, LIST_A))
s.feed(3, txt(S, LIST_B))
s.feed(3, txt(S, LIST_C))
s.advance(30)
f = s.flushes()
texts = sorted([b.combined_text for _, b in f])
check("7.three listings -> 3 batches",
      len(f) == 3 and texts == sorted([LIST_A, LIST_B, LIST_C]),
      f"n={len(f)}")
check("7.no supplement spam", len(s.supplements()) == 0)

# Case 8: chat note interleaved
s = Sim()
s.feed(0, txt(S, LIST_A))
s.feed(1, txt(S, "căn của chị Hằng nè"))   # no markers -> note
for i in range(3):
    s.feed(1, img(S, f"p{i}"))
s.advance(20)
f = s.flushes()
check("8.note kept, not split", len(f) == 1
      and f[0][1].notes == ["căn của chị Hằng nè"]
      and len(f[0][1].photos) == 3)

# Case 9a: BO keyword cancels
s = Sim()
s.feed(0, txt(S, LIST_A))
s.feed(1, img(S, "p0"))
s.feed(1, kw(S, "BO"))
s.advance(20)
check("9a.BO cancels batch", len(s.cancels()) == 1 and len(s.flushes()) == 0)

# Case 9b: LUU flushes immediately
s = Sim()
s.feed(0, img(S, "p0", caption=LIST_A))
s.feed(0.5, kw(S, "luu"))
f = s.flushes()
check("9b.LUU flushes now", len(f) == 1 and f[0][1].reason == "save_kw")

# Case 10: re-forward of same listing 10 min later -> 2 independent flushes
# (dedup itself is the backend's job at save time, using photo hashes)
s = Sim()
s.feed(0, txt(S, LIST_A))
s.advance(20)
s.advance(600)
s.feed(0, txt(S, LIST_A))
s.advance(20)
f = s.flushes()
check("10.repeat 10min later -> separate flush",
      len(f) == 2, "(dedup happens in backend at save time)")

# Case 11: reactions ignored
s = Sim()
s.feed(0, txt(S, LIST_A))
s.feed(1, react(S))
for i in range(2):
    s.feed(1, img(S, f"p{i}"))
s.feed(1, react(S))
s.advance(20)
f = s.flushes()
check("11.reactions ignored", len(f) == 1 and len(f[0][1].photos) == 2)

# Case 12: pairing code during open batch -> immediate, batch untouched
s = Sim()
s.feed(0, img(S, "p0"))
s.feed(1, txt(S, "WA-6BF48B"))
s.feed(1, txt(S, LIST_A))
s.advance(20)
imm = [a for a in s.actions if a[0] == "immediate"]
f = s.flushes()
check("12.pairing bypasses batch", len(imm) == 1
      and len(f) == 1 and len(f[0][1].photos) == 1
      and len(f[0][1].texts) == 1)

# Case 13: slow trickle of photos -> hard cap 60s closes first batch
s = Sim()
for i in range(8):
    s.feed(10, img(S, f"p{i}"))   # one photo every 10s for 70s
s.advance(30)
reasons = [b.reason for _, b in s.flushes()]
check("13.hard cap 60s splits trickle",
      reasons[0] == "hardcap", f"reasons={reasons}")

# Case 14: two senders interleaved -> isolated batches
s = Sim()
S2 = "84999999999"
s.feed(0, txt(S, LIST_A))
s.feed(0.5, txt(S2, LIST_B))
s.feed(1, img(S, "p0"))
s.feed(1, img(S2, "q0"))
s.advance(20)
f = s.flushes()
by = {b.sender: b for _, b in f}
check("14.sender isolation",
      len(f) == 2 and by[S].combined_text == LIST_A
      and by[S2].combined_text == LIST_B)

# Case 15: lone chatty text, no markers, no batch -> no listing
s = Sim()
s.feed(0, txt(S, "ok bạn"))
s.advance(20)
check("15.lone chat ignored", len(s.flushes()) == 0
      and any(a[0] == "ignore_chat" for a in s.actions))

# ------------------------------------------------------------- report
fails = [r for r in results if not r[1]]
for name, ok, detail in results:
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
print(f"\n{len(results) - len(fails)}/{len(results)} pass")
sys.exit(1 if fails else 0)
