"use strict";
/* Behavior-case simulator for the JS batch engine — the same suite as
 * whatsapp_bridge/simulate.py (49 checks there incl. 3 platform-contract
 * checks R5/R6 that don't apply to the port; 46 checks here).
 * Run: node simulate.js
 */
const { Batcher } = require("./batch.js");

const LIST_A = "Cho thuê 2PN Sơn Trà 15tr/tháng, liên hệ 0912345678";
const LIST_B = "Cho thuê 1PN An Thượng 9tr, full nội thất, gọi 0987654321";
const LIST_C = "Villa 4PN Hội An 35tr/tháng, hồ bơi riêng, 0933111222";
const S = "zalo-user-1";
const S2 = "zalo-user-2";

class Sim {
  constructor() {
    this.t = 0;
    this.b = new Batcher({ now: () => this.t });
    this.actions = [];
  }
  feed(dt, ev) {
    this.t += dt;
    this.actions.push(...this.b.tick());
    this.actions.push(...this.b.onEvent(ev));
  }
  advance(seconds, step = 2) {
    const end = this.t + seconds;
    while (this.t < end) {
      this.t = Math.min(this.t + step, end);
      this.actions.push(...this.b.tick());
    }
  }
  flushes() { return this.actions.filter((a) => a[0] === "flush"); }
  supplements() { return this.actions.filter((a) => a[0] === "ask_supplement"); }
  cancels() { return this.actions.filter((a) => a[0] === "cancel"); }
}

const txt = (sender, body, msg_id = "") => ({ sender, kind: "text", body, msg_id });
const img = (sender, pid, caption = "", msg_id = "") =>
  ({ sender, kind: "image", photo_id: pid, caption, msg_id });
const kw = (sender, word) => ({ sender, kind: "keyword", body: word });
const media = (sender, kind, mid, caption = "", msg_id = "") =>
  ({ sender, kind, photo_id: mid, caption, msg_id });
const retract = (sender, target, msg_id) =>
  ({ sender, kind: "retract", target_id: target, msg_id });

const results = [];
function check(name, cond, detail = "") {
  results.push([name, !!cond]);
  console.log((cond ? "PASS " : "FAIL ") + name + (detail ? `  [${detail}]` : ""));
}

let s, f;

// 1 forward block
s = new Sim();
s.feed(0, img(S, "p0", LIST_A));
for (let i = 1; i < 13; i++) s.feed(0.15, img(S, `p${i}`));
s.advance(20); f = s.flushes();
check("1.forward block -> 1 batch", f.length === 1 && f[0][1].photos.length === 13);
check("1.caption parsed", f[0][1].parsed.price_vnd === 15000000
  && f[0][1].parsed.district === "Sơn Trà", JSON.stringify(f[0][1].parsed));

// 2 text-first
s = new Sim(); s.feed(0, txt(S, LIST_A));
for (let i = 0; i < 5; i++) s.feed(2, img(S, `p${i}`));
s.advance(20); f = s.flushes();
check("2.text-first -> 1 batch, 5 photos", f.length === 1
  && f[0][1].photos.length === 5 && f[0][1].texts.length === 1);

// 3 photos-first
s = new Sim();
for (let i = 0; i < 5; i++) s.feed(0.2, img(S, `p${i}`));
s.feed(8, txt(S, LIST_A)); s.advance(20); f = s.flushes();
check("3.photos-first -> 1 batch", f.length === 1
  && f[0][1].photos.length === 5 && f[0][1].texts.length === 1);

// 4 text only
s = new Sim(); s.feed(0, txt(S, LIST_B)); s.advance(20); f = s.flushes();
check("4.text-only flush", f.length === 1 && !f[0][1].photos.length
  && f[0][1].parsed.bedrooms === 1);

// 5 photos only
s = new Sim();
for (let i = 0; i < 13; i++) s.feed(0.15, img(S, `p${i}`));
s.advance(20); f = s.flushes();
check("5.photos-only -> 1 flush, no text", f.length === 1
  && f[0][1].photos.length === 13 && !f[0][1].texts.length);

// 6 supplement
s = new Sim(); s.feed(0, txt(S, LIST_A)); s.advance(20);
const firstId = s.flushes()[0][1].batch_id;
s.advance(120);
s.feed(0, img(S, "extra1")); s.feed(0.5, img(S, "extra2")); s.advance(20);
const sup = s.supplements();
check("6.supp photos -> ask_supplement", sup.length === 1
  && sup[0][1].photos.length === 2 && sup[0][2] === firstId);

// 7 three listings
s = new Sim();
s.feed(0, txt(S, LIST_A)); s.feed(3, txt(S, LIST_B)); s.feed(3, txt(S, LIST_C));
s.advance(30); f = s.flushes();
const texts = f.map((a) => a[1].combined_text).sort();
check("7.three listings -> 3 batches", f.length === 3
  && JSON.stringify(texts) === JSON.stringify([LIST_A, LIST_B, LIST_C].sort()));
check("7.no supplement spam", s.supplements().length === 0);

// 8 note
s = new Sim(); s.feed(0, txt(S, LIST_A));
s.feed(1, txt(S, "căn của chị Hằng nè"));
for (let i = 0; i < 3; i++) s.feed(1, img(S, `p${i}`));
s.advance(20); f = s.flushes();
check("8.note kept, not split", f.length === 1
  && JSON.stringify(f[0][1].notes) === JSON.stringify(["căn của chị Hằng nè"])
  && f[0][1].photos.length === 3);

// 9a BO / 9b LUU
s = new Sim(); s.feed(0, txt(S, LIST_A)); s.feed(1, img(S, "p0")); s.feed(1, kw(S, "BO"));
s.advance(20);
check("9a.BO cancels batch", s.cancels().length === 1 && s.flushes().length === 0);
s = new Sim(); s.feed(0, img(S, "p0", LIST_A)); s.feed(0.5, kw(S, "luu")); f = s.flushes();
check("9b.LUU flushes now", f.length === 1 && f[0][1].reason === "save_kw");

// 10 repeat later
s = new Sim(); s.feed(0, txt(S, LIST_A)); s.advance(20); s.advance(600);
s.feed(0, txt(S, LIST_A)); s.advance(20);
check("10.repeat 10min later -> separate flush", s.flushes().length === 2);

// 11 reactions
s = new Sim(); s.feed(0, txt(S, LIST_A));
s.feed(1, { sender: S, kind: "reaction" });
for (let i = 0; i < 2; i++) s.feed(1, img(S, `p${i}`));
s.feed(1, { sender: S, kind: "reaction" });
s.advance(20); f = s.flushes();
check("11.reactions ignored", f.length === 1 && f[0][1].photos.length === 2);

// 12 pairing during batch
s = new Sim(); s.feed(0, img(S, "p0")); s.feed(1, txt(S, "ZN-6BF48B"));
s.feed(1, txt(S, LIST_A)); s.advance(20);
const imm = s.actions.filter((a) => a[0] === "immediate"); f = s.flushes();
check("12.pairing bypasses batch", imm.length === 1 && f.length === 1
  && f[0][1].photos.length === 1 && f[0][1].texts.length === 1);

// 13 hard cap
s = new Sim();
for (let i = 0; i < 20; i++) s.feed(10, img(S, `p${i}`));
s.advance(30); f = s.flushes();
check("13.hard cap 180s splits endless trickle",
  f[0][1].reason === "hardcap" && f[0][1].photos.length === 18);

// 14 isolation
s = new Sim();
s.feed(0, txt(S, LIST_A)); s.feed(0.5, txt(S2, LIST_B));
s.feed(1, img(S, "p0")); s.feed(1, img(S2, "q0")); s.advance(20); f = s.flushes();
const by = Object.fromEntries(f.map((a) => [a[1].sender, a[1]]));
check("14.sender isolation", f.length === 2
  && by[S].combined_text === LIST_A && by[S2].combined_text === LIST_B);

// 15 lone chat
s = new Sim(); s.feed(0, txt(S, "ok bạn")); s.advance(20);
check("15.lone chat ignored", s.flushes().length === 0
  && s.actions.some((a) => a[0] === "ignore_chat"));

// R1 caption positions
for (const pos of [0, 6, 12]) {
  s = new Sim();
  for (let i = 0; i < 13; i++) s.feed(0.15, img(S, `p${i}`, i === pos ? LIST_A : ""));
  s.advance(20); f = s.flushes();
  check(`R1.caption at photo ${pos} -> same batch`, f.length === 1
    && f[0][1].photos.length === 13
    && JSON.stringify(f[0][1].texts) === JSON.stringify([LIST_A]));
}
// R2 gaps
for (const gap of [0.05, 0.5, 2, 8, 14]) {
  s = new Sim();
  for (let i = 0; i < 6; i++) s.feed(gap, img(S, `p${i}`, i === 0 ? LIST_A : ""));
  s.advance(20); f = s.flushes();
  check(`R2.arrival gap ${gap}s -> 1 batch`, f.length === 1 && f[0][1].photos.length === 6);
}
// R3 text mid-stream
s = new Sim();
for (let i = 0; i < 3; i++) s.feed(0.3, img(S, `p${i}`));
s.feed(0.3, txt(S, LIST_A));
for (let i = 3; i < 6; i++) s.feed(0.3, img(S, `p${i}`));
s.advance(20); f = s.flushes();
check("R3.text mid-stream -> 1 batch, 6 photos", f.length === 1 && f[0][1].photos.length === 6);
// R4 slow selection + resolve merge
s = new Sim();
let resolved = false;
for (let i = 0; i < 5; i++) {
  s.feed(16, img(S, `p${i}`));
  if (!resolved && s.actions.some((a) => a[0] === "ask_supplement")) {
    s.b.resolveSupplement(S, true); resolved = true;
  }
}
s.advance(30);
const sups = s.actions.filter((a) => a[0] === "ask_supplement");
const merges = s.actions.filter((a) => a[0] === "merge_into");
const target = s.flushes().length ? s.flushes()[0][1].batch_id : null;
check("R4.asked supplement exactly once", sups.length === 1);
check("R4.rest auto-merges to first batch", merges.length >= 2
  && merges.every((m) => m[2] === target), `merges=${merges.length} target=${target}`);

// 16 webhook retry dedup
s = new Sim();
const evs = [0, 1, 2].map((i) => ({ sender: S, kind: "image", photo_id: `p${i}`,
  msg_id: `m${i}`, caption: i === 0 ? LIST_A : "" }));
for (const e of evs) s.feed(0.2, e);
for (const e of evs) s.feed(0.2, e);
s.advance(20); f = s.flushes();
const dups = s.actions.filter((a) => a[0] === "duplicate");
check("16.webhook retry deduped", f.length === 1 && f[0][1].photos.length === 3
  && dups.length === 3);

// 17 video / 18 audio / 19 location / 20 document
s = new Sim(); s.feed(0, txt(S, LIST_A)); s.feed(1, media(S, "video", "v1"));
s.feed(1, img(S, "p0")); s.feed(1, img(S, "p1")); s.advance(20); f = s.flushes();
check("17.video kept in batch", f.length === 1
  && f[0][1].others.some((o) => o[0] === "video" && o[1] === "v1")
  && f[0][1].photos.length === 2);
s = new Sim(); s.feed(0, img(S, "p0", LIST_A)); s.feed(1, media(S, "audio", "a1"));
s.advance(20); f = s.flushes();
check("18.voice note kept", f.length === 1
  && f[0][1].others.some((o) => o[0] === "audio" && o[1] === "a1"));
s = new Sim(); s.feed(0, txt(S, LIST_A));
s.feed(1, { sender: S, kind: "location", msg_id: "loc1", meta: { lat: 16.0544, lng: 108.2022 } });
s.advance(20); f = s.flushes();
check("19.location pin kept", f.length === 1
  && JSON.stringify(f[0][1].locations) === JSON.stringify([{ lat: 16.0544, lng: 108.2022 }]));
s = new Sim(); s.feed(0, txt(S, LIST_A));
s.feed(1, media(S, "document", "d1", "bảng giá kèm theo")); s.advance(20); f = s.flushes();
check("20.document kept", f.length === 1
  && f[0][1].others.some((o) => o[0] === "document" && o[1] === "d1"));

// 21 retract
s = new Sim(); s.feed(0, txt(S, LIST_A));
["m0", "m1", "m2"].forEach((mid, i) =>
  s.feed(1, { sender: S, kind: "image", photo_id: `p${i}`, msg_id: mid }));
s.feed(1, retract(S, "p1", "u1")); s.advance(20); f = s.flushes();
check("21.retract removes photo", f.length === 1
  && JSON.stringify(f[0][1].photos) === JSON.stringify(["p0", "p2"]));
s = new Sim();
s.feed(0, { sender: S, kind: "image", photo_id: "p0", msg_id: "m0" });
s.feed(1, retract(S, "p0", "u0")); s.advance(20);
check("21b.retract all cancels", s.cancels().length === 1 && s.flushes().length === 0);

// 22 photo dedup / 23 text dedup
s = new Sim(); s.feed(0, img(S, "p0", LIST_A)); s.feed(1, img(S, "p0")); s.feed(1, img(S, "p1"));
s.advance(20); f = s.flushes();
check("22.photo dedup in batch", f.length === 1
  && JSON.stringify(f[0][1].photos) === JSON.stringify(["p0", "p1"]));
s = new Sim(); s.feed(0, txt(S, LIST_A)); s.feed(2, txt(S, LIST_A)); s.advance(20); f = s.flushes();
check("23.text dedup in batch", f.length === 1
  && JSON.stringify(f[0][1].texts) === JSON.stringify([LIST_A]));

// 24 HUY LINK / 25 LUU empty
s = new Sim(); s.feed(0, txt(S, LIST_A)); s.feed(1, img(S, "p0")); s.feed(1, kw(S, "HUY LINK"));
s.advance(20);
check("24.HUY LINK cancels batch", s.cancels().length === 1 && s.flushes().length === 0
  && s.actions.some((a) => a[0] === "immediate"));
s = new Sim();
check("25.LUU empty batch no-op", s.b.onEvent(kw(S, "LUU")).length === 0);

// 26 multi
s = new Sim(); s.feed(0, txt(S, LIST_A + "\n---\n" + LIST_B)); s.advance(20); f = s.flushes();
check("26.multi-listing paste flagged", f.length === 1 && f[0][1].is_multi);
s = new Sim(); s.feed(0, txt(S, LIST_A)); s.advance(20);
check("26b.single listing not flagged", !s.flushes()[0][1].is_multi);

// 27 unanswered -> asked again
s = new Sim(); s.feed(0, txt(S, LIST_A)); s.advance(20);
s.feed(1, img(S, "x0")); s.feed(1, img(S, "x1")); s.advance(20);
s.feed(1, img(S, "x2")); s.feed(1, img(S, "x3")); s.advance(20);
check("27.unanswered -> asked again", s.supplements().length === 2);

// 28 full text after merge stays new
s = new Sim(); s.feed(0, txt(S, LIST_A)); s.advance(20);
s.feed(1, img(S, "x0")); s.advance(20);
s.b.resolveSupplement(S, true);
s.feed(1, txt(S, LIST_B)); s.advance(20);
const ftexts = s.flushes().map((a) => a[1].combined_text);
check("28.full text after merge-OK stays new",
  ftexts.includes(LIST_B) && s.actions.filter((a) => a[0] === "merge_into").length === 0);

// 29 album 30
s = new Sim();
for (let i = 0; i < 30; i++) s.feed(0.1, img(S, `p${i}`, i === 0 ? LIST_A : ""));
s.advance(20); f = s.flushes();
check("29.album 30 photos", f.length === 1 && f[0][1].photos.length === 30);

// 30 unknown kind ignored
s = new Sim(); s.feed(0, txt(S, LIST_A)); s.feed(1, { sender: S, kind: "sticker" });
s.feed(1, img(S, "p0")); s.advance(20); f = s.flushes();
check("30.sticker ignored", f.length === 1 && f[0][1].photos.length === 1);

const fails = results.filter((r) => !r[1]);
console.log(`\n${results.length - fails.length}/${results.length} pass`);
process.exit(fails.length ? 1 : 0);
