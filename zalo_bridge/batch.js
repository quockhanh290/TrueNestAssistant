"use strict";
/* Channel-agnostic message batching engine — 1:1 JS port of
 * whatsapp_bridge/batch.py. Keep the two in sync: the Python
 * simulate.py case suite (49 checks) is the behavioral contract and
 * zalo_bridge/simulate.js runs the same cases against this port.
 *
 * Brokers forward listings as SEQUENCES of messages; this engine groups
 * one sender's events into ONE batch. Close rules (content first):
 *   1. a second DIFFERENT full-listing text -> flush ("split")
 *   2. LUU keyword -> flush with save intent; BO -> cancel
 *   3. silence `silence`s -> flush; age > `hardCap` -> flush regardless
 * A textless batch flushed within `suppWindow` of the previous flush is
 * flagged ask_supplement; batches WITH listing text never merge.
 * Webhook retries are deduped by message id; identical texts and photo
 * ids inside a batch are deduped; media of every kind is collected;
 * retract events remove recalled items; HUY LINK cancels the open batch.
 */

const PRICE_RE = /(\d[\d.,\s]*)\s*(tỷ|ty|tr|triệu|trieu|million|k)(?![\p{L}\p{N}])/iu;
const PRICE_RE_G = /(\d[\d.,\s]*)\s*(tỷ|ty|tr|triệu|trieu|million|k)(?![\p{L}\p{N}])/giu;
const BED_RE = /(\d+)\s*(pn|phòng ngủ|phong ngu|bedrooms?|br)(?![\p{L}\p{N}])/iu;
const PHONE_RE = /(?<!\d)(0\d{9})(?!\d)/;
const PHONE_RE_G = /(?<!\d)(0\d{9})(?!\d)/g;
const DISTRICTS = [
  "Sơn Trà", "Hải Châu", "Ngũ Hành Sơn", "Cẩm Lệ", "Thanh Khê",
  "Liên Chiểu", "An Thượng", "Mỹ Khê", "Non Nước", "Hội An",
];
const PAIRING_RE = /^(WA|ZN)-[A-Z2-9]{6}$/;

const SHORT_MAX = 40;
const MEDIA_KINDS = ["image", "video", "audio", "document", "location", "contact"];
const SEEN_KEEP = 300;

function parseListing(text) {
  const out = {};
  const t = text || "";
  const m = t.match(PRICE_RE);
  if (m) {
    const num = parseFloat(m[1].replace(/,/g, ".").replace(/ /g, ""));
    if (!Number.isNaN(num)) {
      const unit = m[2].toLowerCase();
      const mult = { "tỷ": 1e9, "ty": 1e9, "tr": 1e6, "triệu": 1e6,
                     "trieu": 1e6, "million": 1e6, "k": 1e3 }[unit] || 1;
      out.price_vnd = Math.trunc(num * mult);
    }
  }
  const b = t.match(BED_RE);
  if (b) out.bedrooms = parseInt(b[1], 10);
  const p = t.match(PHONE_RE);
  if (p) out.phone_in_text = p[1];
  const low = t.toLowerCase();
  for (const d of DISTRICTS) {
    if (low.includes(d.toLowerCase())) { out.district = d; break; }
  }
  return out;
}

function hasListingMarkers(text) {
  return Object.keys(parseListing(text)).length > 0;
}

function isPairingCode(text) {
  return PAIRING_RE.test((text || "").trim().toUpperCase());
}

class Batch {
  constructor(batchId, sender) {
    this.batch_id = batchId;
    this.sender = sender;
    this.texts = [];
    this.notes = [];
    this.photos = [];
    this.others = [];      // [kind, mediaId]
    this.locations = [];
    this.text_ids = {};    // msgId -> listing text
    this.anchor_msg_id = "";
    this.started_at = 0;
    this.last_at = 0;
    this.reason = "";
  }
  get combined_text() { return this.texts.join("\n"); }
  get parsed() { return parseListing(this.combined_text); }
  get is_multi() {
    const t = this.combined_text;
    const phones = new Set(t.match(PHONE_RE_G) || []);
    const prices = t.match(PRICE_RE_G) || [];
    return phones.size >= 2 || prices.length >= 2;
  }
}

function batchToDict(b) {
  return {
    batch_id: b.batch_id, sender: b.sender, texts: b.texts, notes: b.notes,
    photos: b.photos, others: b.others, locations: b.locations,
    text_ids: b.text_ids, anchor_msg_id: b.anchor_msg_id,
    started_at: b.started_at, last_at: b.last_at, reason: b.reason,
  };
}

function batchFromDict(d) {
  const b = new Batch(d.batch_id, d.sender);
  b.texts = d.texts || []; b.notes = d.notes || [];
  b.photos = d.photos || []; b.others = d.others || [];
  b.locations = d.locations || []; b.text_ids = d.text_ids || {};
  b.anchor_msg_id = d.anchor_msg_id || "";
  b.started_at = d.started_at || 0; b.last_at = d.last_at || 0;
  b.reason = d.reason || "";
  return b;
}

class Batcher {
  constructor(opts = {}) {
    this._now = opts.now || (() => Date.now() / 1000);
    this.silence = opts.silence ?? 15.0;
    this.hardCap = opts.hardCap ?? 180.0;
    this.suppWindow = opts.suppWindow ?? 300.0;
    this.batches = new Map();
    this.recent = new Map();        // sender -> [batchId, flushedAt]
    this.pendingSupp = new Map();   // sender -> [batchId, prevBatchId]
    this.suppMode = new Map();      // sender -> {mode, target, until}
    this._seen = new Map();         // sender -> Map(msgId -> ts)
    this._seq = 0;
  }

  _open(sender, now) {
    this._seq += 1;
    const b = new Batch(this._seq, sender);
    b.started_at = now; b.last_at = now;
    this.batches.set(sender, b);
    return b;
  }

  _isDuplicate(sender, msgId, now) {
    if (!msgId) return false;
    let seen = this._seen.get(sender);
    if (!seen) { seen = new Map(); this._seen.set(sender, seen); }
    if (seen.has(msgId)) return true;
    seen.set(msgId, now);
    if (seen.size > SEEN_KEEP) {
      const sorted = [...seen.entries()].sort((a, b2) => a[1] - b2[1]);
      for (const [k] of sorted.slice(0, SEEN_KEEP / 2)) seen.delete(k);
    }
    return false;
  }

  _flush(sender, reason, now) {
    const b = this.batches.get(sender);
    this.batches.delete(sender);
    if (!b || (!b.texts.length && !b.photos.length && !b.notes.length
               && !b.others.length)) return [];
    b.reason = reason;
    const prev = this.recent.get(sender);
    this.recent.set(sender, [b.batch_id, now]);
    const mode = this.suppMode.get(sender);
    if (mode && now <= mode.until && !b.texts.length) {
      if (mode.mode === "merge") return [["merge_into", b, mode.target]];
      return [["flush", b]];
    }
    if (prev && !b.texts.length && now - prev[1] <= this.suppWindow
        && prev[0] !== b.batch_id) {
      this.pendingSupp.set(sender, [b.batch_id, prev[0]]);
      return [["ask_supplement", b, prev[0]]];
    }
    return [["flush", b]];
  }

  resolveSupplement(sender, merge) {
    const pend = this.pendingSupp.get(sender);
    if (!pend) return;               // double-tap safe
    this.pendingSupp.delete(sender);
    this.suppMode.set(sender, {
      mode: merge ? "merge" : "new",
      target: pend[1],
      until: this._now() + this.suppWindow,
    });
  }

  _touchAnchor(b, ev) {
    if (!b.anchor_msg_id && ev.msg_id) b.anchor_msg_id = ev.msg_id;
  }

  _addText(b, text, now, msgId = "") {
    text = (text || "").trim();
    if (!text) return;
    if (hasListingMarkers(text)) {
      if (!b.texts.includes(text)) {
        b.texts.push(text);
        if (msgId) b.text_ids[msgId] = text;
      }
    } else if (!b.notes.includes(text)) {
      b.notes.push(text);
    }
    b.last_at = now;
  }

  _retract(sender, targetId) {
    const b = this.batches.get(sender);
    if (!b || !targetId) return [["ignore", sender]];
    let removed = false;
    const pi = b.photos.indexOf(targetId);
    if (pi >= 0) { b.photos.splice(pi, 1); removed = true; }
    const before = b.others.length;
    b.others = b.others.filter((o) => o[1] !== targetId);
    removed = removed || b.others.length !== before;
    const t = b.text_ids[targetId];
    if (t !== undefined) {
      delete b.text_ids[targetId];
      const ti = b.texts.indexOf(t);
      if (ti >= 0) { b.texts.splice(ti, 1); removed = true; }
    }
    if (!removed) return [["ignore", sender]];
    if (!b.texts.length && !b.photos.length && !b.notes.length
        && !b.others.length) {
      this.batches.delete(sender);
      return [["cancel", sender]];
    }
    return [["retracted", sender, targetId]];
  }

  onEvent(ev) {
    const now = this._now();
    const sender = ev.sender;

    if (this._isDuplicate(sender, ev.msg_id, now)) return [["duplicate", ev]];
    if (ev.kind === "reaction") return [["ignore", ev]];
    if (ev.kind === "button") return [["immediate", ev]];
    if (ev.kind === "retract") return this._retract(sender, ev.target_id);

    if (ev.kind === "keyword") {
      const kw = (ev.body || "").trim().toUpperCase();
      if (kw === "HUY LINK") {
        const acts = [];
        if (this.batches.delete(sender)) acts.push(["cancel", sender]);
        acts.push(["immediate", ev]);
        return acts;
      }
      if (kw === "LUU") return this._flush(sender, "save_kw", now);
      if (kw === "BO") {
        if (this.batches.delete(sender)) return [["cancel", sender]];
        return [["ignore_chat", ev]];
      }
      return [["immediate", ev]];
    }

    if (ev.kind === "text" && isPairingCode(ev.body)) return [["immediate", ev]];

    if (MEDIA_KINDS.includes(ev.kind)) {
      let b = this.batches.get(sender);
      if (!b) b = this._open(sender, now);
      this._touchAnchor(b, ev);
      if (ev.kind === "image") {
        const pid = ev.photo_id || `photo-${b.photos.length}`;
        if (!b.photos.includes(pid)) b.photos.push(pid);
      } else {
        const entry = [ev.kind, ev.photo_id || ev.msg_id || ""];
        if (!b.others.some((o) => o[0] === entry[0] && o[1] === entry[1])) {
          b.others.push(entry);
        }
        if (ev.kind === "location" && ev.meta) b.locations.push({ ...ev.meta });
      }
      b.last_at = now;
      if (ev.caption) this._addText(b, ev.caption, now, ev.msg_id);
      return [];
    }

    if (ev.kind === "text") {
      const text = (ev.body || "").trim();
      let b = this.batches.get(sender);
      if (b) this._touchAnchor(b, ev);
      if (b && b.texts.length && hasListingMarkers(text)) {
        if (b.texts.includes(text)) {
          this._addText(b, text, now, ev.msg_id);
          return [];
        }
        const acts = this._flush(sender, "split", now);
        b = this._open(sender, now);
        this._touchAnchor(b, ev);
        this._addText(b, text, now, ev.msg_id);
        return acts;
      }
      if (!b) {
        if (!hasListingMarkers(text) && text.length <= SHORT_MAX) {
          return [["ignore_chat", ev]];
        }
        b = this._open(sender, now);
        this._touchAnchor(b, ev);
      }
      this._addText(b, text, now, ev.msg_id);
      return [];
    }

    return [["ignore", ev]];
  }

  tick() {
    const now = this._now();
    const acts = [];
    for (const [sender, b] of [...this.batches.entries()]) {
      if (now - b.started_at >= this.hardCap) {
        acts.push(...this._flush(sender, "hardcap", now));
      } else if (now - b.last_at >= this.silence) {
        acts.push(...this._flush(sender, "silence", now));
      }
    }
    return acts;
  }

  snapshot() {
    const obj = (map) => Object.fromEntries(
      [...map.entries()].map(([k, v]) => [k, v]));
    return {
      seq: this._seq,
      batches: obj(new Map([...this.batches.entries()]
        .map(([s, b]) => [s, batchToDict(b)]))),
      recent: obj(new Map([...this.recent.entries()]
        .map(([s, v]) => [s, [...v]]))),
      pending_supp: obj(new Map([...this.pendingSupp.entries()]
        .map(([s, v]) => [s, [...v]]))),
      supp_mode: obj(this.suppMode),
      seen: obj(new Map([...this._seen.entries()]
        .map(([s, m]) => [s, Object.fromEntries(m)]))),
    };
  }

  static restore(snap, opts = {}) {
    const eng = new Batcher(opts);
    if (!snap) return eng;
    eng._seq = snap.seq || 0;
    for (const [s, d] of Object.entries(snap.batches || {})) {
      eng.batches.set(s, batchFromDict(d));
    }
    for (const [s, v] of Object.entries(snap.recent || {})) {
      eng.recent.set(s, [...v]);
    }
    for (const [s, v] of Object.entries(snap.pending_supp || {})) {
      eng.pendingSupp.set(s, [...v]);
    }
    for (const [s, v] of Object.entries(snap.supp_mode || {})) {
      eng.suppMode.set(s, v);
    }
    for (const [s, m] of Object.entries(snap.seen || {})) {
      eng._seen.set(s, new Map(Object.entries(m)));
    }
    return eng;
  }
}

module.exports = { Batcher, Batch, batchToDict, batchFromDict,
                   parseListing, hasListingMarkers, isPairingCode };
