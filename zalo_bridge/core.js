"use strict";
/* Zalo bridge v2 core — testable brain, wired to zca-js by bridge.js.
 *
 * Spec (BRIDGE_V2.md): AUTO-SAVE. A closed batch saves immediately as a
 * draft listing; the broker decides keep/edit/delete when reviewing in
 * their inventory. Photo-only follow-up batches (<=5 min after a save)
 * are the one exception — they ask GỘP / MỚI by quoted keyword reply;
 * no answer in 10 min = saved separately. HUY within 10 min undoes the
 * latest save. Every bridge message quotes the broker's anchor message.
 *
 * deps = {
 *   send(zaloId, text, quote|null) -> Promise,
 *   download(url) -> Promise<Buffer|null>,
 *   dbCall(...args) -> object            (pairing link lookup/unlink),
 *   saveListing({tgId, text, photoBuffers}) -> Promise<result>,
 *   appendPhotos({listingId, photoBuffers}) -> Promise<result>,
 *   undoListing(listingId) -> Promise<{ok}>,
 *   tgSend(tgId, text),
 *   loadState() -> object|null, storeState(obj),
 *   now() -> seconds,
 * }
 */
const { Batcher, batchToDict, batchFromDict, isPairingCode } = require("./batch.js");

const SUPP_TIMEOUT_SEC = 600;
const UNDO_WINDOW_SEC = 600;
const OUTBOX_BACKOFF = [60, 300, 900];
const RATE_LIMIT = 20;
const GUIDE_INTERVAL = 3600;

const GUIDE_TEXT =
  "Chào anh/chị 👋 Em là Linh, trợ lý TrueNest.\n\n" +
  "Để liên kết: mở bot TrueNest trên Telegram, gửi /linkzalo để lấy mã, " +
  "rồi gửi mã đó vào đây.\n\n" +
  "Sau khi liên kết, anh/chị forward tin vào đây là tin tự vào kho.";

function summaryOf(b) {
  const p = b.parsed;
  const bits = [];
  if (p.bedrooms) bits.push(`${p.bedrooms}PN`);
  if (p.district) bits.push(p.district);
  if (p.price_vnd) {
    bits.push(p.price_vnd >= 1_000_000
      ? `${Math.round((p.price_vnd / 1e6) * 100) / 100}tr`
      : `${p.price_vnd}đ`);
  }
  let head = bits.length ? bits.join(" ") : "Tin mới";
  if (!b.texts.length && b.photos.length) head = `${b.photos.length} ảnh (chưa có nội dung)`;
  let tail = b.photos.length && b.texts.length ? ` + ${b.photos.length} ảnh` : "";
  if (b.others.length) tail += ` (bỏ qua ${b.others.length} file/video — em chỉ nhận ảnh)`;
  return head + tail;
}

function createCore(deps) {
  const now = deps.now || (() => Date.now() / 1000);
  let state = deps.loadState() || {};
  const engines = new Map();
  for (const [s, snap] of Object.entries(state.engines || {})) {
    engines.set(s, Batcher.restore(snap, { now }));
  }
  const S = {
    photoUrls: state.photoUrls || {},          // photoId -> url
    anchors: state.anchors || {},              // "sender:batchId" -> quote
    batchListing: state.batchListing || {},    // sender -> {batchId: listingId}
    lastSave: state.lastSave || {},            // sender -> {listing_id, at}
    pendingSupp: state.pendingSupp || {},      // sender -> {batch, target_listing, target_summary, created}
    outbox: state.outbox || [],                // [{sender, type, batch, listing_id, attempts, nextAt}]
    guideSent: state.guideSent || {},          // sender -> ts
  };
  const linkCache = new Map();                 // zaloId -> telegramId
  const rate = new Map();                      // zaloId -> [ts]

  function persist() {
    const snaps = {};
    for (const [s, e] of engines.entries()) snaps[s] = e.snapshot();
    deps.storeState({ engines: snaps, ...S });
  }

  function engine(sender) {
    let e = engines.get(sender);
    if (!e) { e = new Batcher({ now }); engines.set(sender, e); }
    return e;
  }

  function lookup(sender) {
    if (linkCache.has(sender)) return linkCache.get(sender);
    const r = deps.dbCall("lookup", sender);
    const tg = r && r.ok ? r.telegram_id : null;
    if (tg) linkCache.set(sender, tg);
    return tg;
  }

  function quoteFor(sender, batch) {
    return S.anchors[`${sender}:${batch.batch_id}`] || null;
  }

  function noteAnchor(sender, batch, quoteData) {
    const key = `${sender}:${batch.batch_id}`;
    if (quoteData && !S.anchors[key]) S.anchors[key] = quoteData;
  }

  async function downloadPhotos(b) {
    const buffers = [];
    let failed = 0;
    for (const pid of b.photos) {
      const url = S.photoUrls[pid];
      const buf = url ? await deps.download(url) : null;
      if (buf) buffers.push(buf); else failed += 1;
    }
    return { buffers, failed };
  }

  async function receiptSaved(sender, b, result, dlFailed) {
    const lines = [`✅ Đã lưu vào kho: ${summaryOf(b)}`];
    if (result.photos_failed || dlFailed) {
      lines.push(`⚠️ ${result.photos_failed + dlFailed} ảnh lỗi, chưa lưu được.`);
    }
    if (result.dup_suspect) {
      lines.push(`ℹ️ Tin này có vẻ trùng với: ${result.dup_suspect} — anh/chị vào kho kiểm tra giúp em nhé.`);
    }
    if (b.is_multi) {
      lines.push("⚠️ Tin này có vẻ chứa 2 căn — vào kho tách giúp em nhé.");
    }
    lines.push("(Nhắn HUY trong 10 phút để huỷ nếu lưu nhầm)");
    await deps.send(sender, lines.join("\n"), quoteFor(sender, b));
  }

  async function doSave(sender, tgId, b, outboxRow = null) {
    const { buffers, failed } = await downloadPhotos(b);
    let result = null;
    try {
      result = await deps.saveListing({ tgId, text: b.combined_text, photoBuffers: buffers });
    } catch { result = null; }

    if (result && result.ok) {
      (S.batchListing[sender] ||= {})[b.batch_id] =
        { listing_id: result.listing_id, summary: summaryOf(b) };
      S.lastSave[sender] = { listing_id: result.listing_id, at: now() };
      if (outboxRow) S.outbox = S.outbox.filter((r) => r !== outboxRow);
      await receiptSaved(sender, b, result, failed);
      persist();
      return true;
    }
    if (result && result.error === "limit") {
      if (outboxRow) S.outbox = S.outbox.filter((r) => r !== outboxRow);
      await deps.send(sender,
        "⚠️ Kho của anh/chị đã đạt giới hạn số tin của gói hiện tại. Nâng gói trong bot để lưu thêm nhé.",
        quoteFor(sender, b));
      persist();
      return true;
    }
    if (!outboxRow) {
      S.outbox.push({ sender, type: "save", tgId, batch: batchToDict(b),
                      attempts: 0, nextAt: now() + OUTBOX_BACKOFF[0] });
      await deps.send(sender,
        "⏳ Lưu đang gặp trục trặc, em sẽ tự thử lại và báo anh/chị ngay khi xong.",
        quoteFor(sender, b));
    }
    persist();
    return false;
  }

  async function doAppend(sender, b, listingId, targetSummary, outboxRow = null) {
    const { buffers, failed } = await downloadPhotos(b);
    let result = null;
    try {
      result = await deps.appendPhotos({ listingId, photoBuffers: buffers });
    } catch { result = null; }
    if (result && result.ok) {
      if (outboxRow) S.outbox = S.outbox.filter((r) => r !== outboxRow);
      let msg = `✅ Đã gộp ${result.photos_ok} ảnh vào căn ${targetSummary}.`;
      if (result.photos_failed || failed) {
        msg += ` (${result.photos_failed + failed} ảnh lỗi, chưa gộp được)`;
      }
      await deps.send(sender, msg, quoteFor(sender, b));
      persist();
      return true;
    }
    if (!outboxRow) {
      S.outbox.push({ sender, type: "append", listingId, targetSummary,
                      batch: batchToDict(b), attempts: 0,
                      nextAt: now() + OUTBOX_BACKOFF[0] });
    }
    persist();
    return false;
  }

  async function handleActions(sender, tgId, actions) {
    for (const act of actions) {
      const [kind, x, y] = act;
      if (kind === "flush") {
        await doSave(sender, tgId, x);
        delete S.anchors[`${sender}:${x.batch_id}`];
      } else if (kind === "ask_supplement") {
        const b = x, prevId = y;
        const targetRec = (S.batchListing[sender] || {})[prevId];
        if (!targetRec) { await doSave(sender, tgId, b); continue; }
        S.pendingSupp[sender] = { batch: batchToDict(b),
                                  target_listing: targetRec.listing_id,
                                  target_summary: targetRec.summary || "căn vừa rồi",
                                  created: now() };
        await deps.send(sender,
          `Vừa nhận thêm ${b.photos.length} ảnh. Đây có phải ảnh của căn ${targetRec.summary || "vừa rồi"} không? Nhắn GỘP nếu đúng, MỚI nếu là căn riêng nhé.`,
          quoteFor(sender, b));
      } else if (kind === "merge_into") {
        const b = x, targetBatch = y;
        const targetRec = (S.batchListing[sender] || {})[targetBatch];
        if (targetRec) {
          await doAppend(sender, b, targetRec.listing_id,
                         targetRec.summary || "căn vừa rồi");
        } else {
          await doSave(sender, tgId, b);
        }
        delete S.anchors[`${sender}:${b.batch_id}`];
      } else if (kind === "immediate") {
        const ev = x;
        if (ev.kind === "keyword" && (ev.body || "").trim().toUpperCase() === "HUY LINK") {
          const r = deps.dbCall("unlink", sender);
          linkCache.delete(sender);
          await deps.send(sender, r && r.ok
            ? "✅ Đã huỷ liên kết. Tin forward vào đây sẽ không vào kho nữa."
            : "Anh/chị chưa liên kết tài khoản nào.", null);
          if (r && r.ok && tgId) {
            deps.tgSend(tgId, "Đã huỷ liên kết Zalo theo yêu cầu của anh/chị.");
          }
        }
        // pairing-code immediate is handled before the engine (see below)
      }
      // cancel / ignore / ignore_chat / duplicate / retracted: silent
    }
    persist();
  }

  function rateOk(sender) {
    const t = now();
    const hits = (rate.get(sender) || []).filter((x) => t - x < 60);
    if (hits.length >= RATE_LIMIT) { rate.set(sender, hits); return false; }
    hits.push(t); rate.set(sender, hits);
    return true;
  }

  /* ev: normalized batch event; raw: {quoteData} from the platform msg */
  async function handleMessage(sender, ev, raw = {}) {
    if (!rateOk(sender)) return;
    const text = ev.kind === "text" ? (ev.body || "").trim() : "";

    // pairing works for everyone, linked or not
    if (ev.kind === "text" && isPairingCode(text)) {
      const r = deps.dbCall("redeem", text.toUpperCase(), sender, raw.name || "");
      if (r && r.ok) {
        linkCache.set(sender, r.telegram_id);
        await deps.send(sender,
          "✅ Đã liên kết! Từ giờ anh/chị forward tin vào đây, tin sẽ tự vào kho (em lưu ngay, không cần xác nhận).", null);
        deps.tgSend(r.telegram_id,
          "🔗 Đã liên kết Zalo! Từ giờ forward tin vào tài khoản Zalo nhận tin là tin tự vào kho.");
      } else {
        const why = r && r.error === "expired" ? "mã đã hết hạn (15 phút)"
          : r && r.error === "used" ? "mã đã được dùng rồi" : "mã không đúng";
        await deps.send(sender, `❌ ${why}. Mở bot Telegram gửi /linkzalo để lấy mã mới nhé.`, null);
      }
      return;
    }

    const tgId = lookup(sender);
    if (!tgId) {
      const t = now();
      if (t - (S.guideSent[sender] || 0) > GUIDE_INTERVAL) {
        S.guideSent[sender] = t;
        await deps.send(sender, GUIDE_TEXT, null);
        persist();
      }
      return;
    }

    // HUY: undo the latest save (bridge-level, not an engine keyword)
    if (ev.kind === "text" && text.toUpperCase() === "HUY") {
      const last = S.lastSave[sender];
      if (last && now() - last.at <= UNDO_WINDOW_SEC) {
        const r = await deps.undoListing(last.listing_id);
        delete S.lastSave[sender];
        await deps.send(sender, r && r.ok
          ? "✅ Đã huỷ tin vừa lưu."
          : "Em huỷ không thành công, anh/chị vào kho xoá giúp em nhé.",
          raw.quoteData || null);
      } else {
        await deps.send(sender,
          "Đã quá 10 phút kể từ lần lưu gần nhất (hoặc chưa có tin nào được lưu). Anh/chị vào kho xoá giúp em nhé.",
          raw.quoteData || null);
      }
      persist();
      return;
    }

    // supplement answer pending?
    const pend = S.pendingSupp[sender];
    if (pend && ev.kind === "text" && ["GỘP", "GOP", "MỚI", "MOI"].includes(text.toUpperCase())) {
      delete S.pendingSupp[sender];
      const b = batchFromDict(pend.batch);
      const merge = ["GỘP", "GOP"].includes(text.toUpperCase());
      engine(sender).resolveSupplement(sender, merge);
      if (merge) await doAppend(sender, b, pend.target_listing, pend.target_summary);
      else await doSave(sender, tgId, b);
      delete S.anchors[`${sender}:${b.batch_id}`];
      persist();
      return;
    }

    // keywords -> engine keyword events
    if (ev.kind === "text" && ["HUY LINK", "LUU", "BO"].includes(text.toUpperCase())) {
      ev = { ...ev, kind: "keyword", body: text.toUpperCase() };
    }

    const eng = engine(sender);
    const actions = eng.onEvent(ev);
    // anchor capture: whatever batch is open now belongs to this message
    const open = eng.batches.get(sender);
    if (open) noteAnchor(sender, open, raw.quoteData);
    await handleActions(sender, tgId, actions);
  }

  async function handleUndo(sender, undoneMsgId) {
    const tgId = lookup(sender);
    if (!tgId) return;
    const eng = engine(sender);
    const actions = eng.onEvent({ sender, kind: "retract",
      target_id: undoneMsgId, msg_id: `undo:${undoneMsgId}:${now()}` });
    await handleActions(sender, tgId, actions);
  }

  async function tick() {
    const t = now();
    for (const [sender, eng] of [...engines.entries()]) {
      const tgId = lookup(sender);
      if (!tgId) continue;
      const acts = eng.tick();
      if (acts.length) await handleActions(sender, tgId, acts);
    }
    // supplement timeouts -> save separately
    for (const [sender, pend] of Object.entries(S.pendingSupp)) {
      if (t - pend.created > SUPP_TIMEOUT_SEC) {
        delete S.pendingSupp[sender];
        const tgId = lookup(sender);
        if (!tgId) continue;
        engine(sender).resolveSupplement(sender, false);
        const held = batchFromDict(pend.batch);
        await doSave(sender, tgId, held);
        delete S.anchors[`${sender}:${held.batch_id}`];
      }
    }
    // outbox retries
    for (const row of [...S.outbox]) {
      if (row.nextAt > t) continue;
      const b = batchFromDict(row.batch);
      const ok = row.type === "save"
        ? await doSave(row.sender, row.tgId, b, row)
        : await doAppend(row.sender, b, row.listingId, row.targetSummary, row);
      if (!ok) {
        row.attempts += 1;
        if (row.attempts > OUTBOX_BACKOFF.length) {
          S.outbox = S.outbox.filter((r) => r !== row);
          await deps.send(row.sender,
            "❌ Em không lưu được đợt này sau nhiều lần thử. Anh/chị gửi lại giúp em nhé.",
            quoteFor(row.sender, b));
        } else {
          row.nextAt = t + OUTBOX_BACKOFF[row.attempts - 1];
        }
      }
    }
    persist();
  }

  return { handleMessage, handleUndo, tick,
           notePhotoUrl: (id, url) => { S.photoUrls[id] = url; } };
}

module.exports = { createCore, summaryOf };
