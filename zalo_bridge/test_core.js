"use strict";
/* Unit test for zalo_bridge/core.js with fake platform deps. */
const path = require("node:path");
const { createCore } = require(path.join(process.env.HOME,
  "workspace/broker-bot/zalo_bridge/core.js"));

const LIST_A = "Cho thuê 2PN Sơn Trà 15tr/tháng, liên hệ 0912345678";
const Z = "zalo-user-9";
const results = [];
function check(name, cond, detail = "") {
  results.push([name, !!cond]);
  console.log((cond ? "PASS " : "FAIL ") + name + (detail ? `  [${detail}]` : ""));
}

let clock = 1_000_000;
let sent = [], tgSent = [], saves = [], appends = [], undos = [];
let storedState = null;
let linked = false;
let saveShouldFail = 0;   // next N saveListing calls throw

function makeDeps() {
  return {
    now: () => clock,
    send: async (z, text, quote) => { sent.push({ z, text, quote }); },
    download: async (url) => Buffer.from("img:" + url),
    dbCall: (...args) => {
      if (args[0] === "lookup") return { ok: true, telegram_id: linked ? 111 : null };
      if (args[0] === "redeem") { linked = true; return { ok: true, telegram_id: 111 }; }
      if (args[0] === "unlink") { linked = false; return { ok: true }; }
      return { ok: false };
    },
    saveListing: async ({ tgId, text, photoBuffers }) => {
      if (saveShouldFail > 0) { saveShouldFail -= 1; throw new Error("boom"); }
      saves.push({ tgId, text, n: photoBuffers.length });
      return { ok: true, listing_id: "tg:test1", photos_ok: photoBuffers.length,
               photos_failed: 0, dup_suspect: null, missing: [] };
    },
    appendPhotos: async ({ listingId, photoBuffers }) => {
      appends.push({ listingId, n: photoBuffers.length });
      return { ok: true, photos_ok: photoBuffers.length, photos_failed: 0 };
    },
    undoListing: async (id) => { undos.push(id); return { ok: true }; },
    tgSend: (tg, text) => tgSent.push({ tg, text }),
    loadState: () => storedState,
    storeState: (obj) => { storedState = obj; },
  };
}

const ev = (kind, extra = {}) => ({ sender: Z, kind, ...extra });
const quote = { content: "x", msgType: "chat.text", msgId: "q1", cliMsgId: "c1",
                uidFrom: Z, ts: 1, ttl: 0, propertyExt: {} };

(async () => {
  const core = createCore(makeDeps());

  // 1) unlinked -> guide once
  await core.handleMessage(Z, ev("text", { body: "hello", msg_id: "a0" }), {});
  check("unlinked gets guide", sent.length === 1 && sent[0].text.includes("/linkzalo"));

  // 2) pairing
  sent = [];
  await core.handleMessage(Z, ev("text", { body: "ZN-ABC234", msg_id: "a1" }), {});
  check("pairing links + confirms", linked && sent.some((s) => s.text.includes("Đã liên kết")));
  check("pairing notifies telegram", tgSent.length === 1);

  // 3) forward text + 2 photos -> silence -> AUTO-SAVE (no confirm!)
  sent = [];
  core.notePhotoUrl("p1", "http://x/1.jpg");
  core.notePhotoUrl("p2", "http://x/2.jpg");
  await core.handleMessage(Z, ev("text", { body: LIST_A, msg_id: "a2" }), { quoteData: quote });
  await core.handleMessage(Z, ev("image", { photo_id: "p1", msg_id: "a3" }), {});
  await core.handleMessage(Z, ev("image", { photo_id: "p2", msg_id: "a4" }), {});
  check("no save before batch closes", saves.length === 0);
  clock += 16;
  await core.tick();
  check("auto-saved on flush", saves.length === 1 && saves[0].n === 2
    && saves[0].text === LIST_A, JSON.stringify(saves));
  check("receipt quoted", sent.some((s) => s.text.includes("Đã lưu vào kho") && s.quote === quote));

  // 4) supplement photos -> question -> GỘP -> append
  sent = [];
  core.notePhotoUrl("p3", "http://x/3.jpg");
  clock += 60;
  await core.handleMessage(Z, ev("image", { photo_id: "p3", msg_id: "a5" }), { quoteData: quote });
  clock += 16;
  await core.tick();
  check("supplement asks GOP/MOI", sent.some((s) => s.text.includes("GỘP")));
  check("not saved yet", saves.length === 1 && appends.length === 0);
  await core.handleMessage(Z, ev("text", { body: "GỘP", msg_id: "a6" }), {});
  check("GOP appends to previous listing", appends.length === 1
    && appends[0].listingId === "tg:test1" && appends[0].n === 1);

  // 5) HUY within 10 min undoes last save
  await core.handleMessage(Z, ev("text", { body: "HUY", msg_id: "a7" }), {});
  check("HUY undoes last save", undos.length === 1 && undos[0] === "tg:test1");

  // 6) save failure -> outbox -> retry succeeds
  saves = []; sent = [];
  saveShouldFail = 1;
  await core.handleMessage(Z, ev("text", { body: LIST_A, msg_id: "a8" }), { quoteData: quote });
  clock += 16;
  await core.tick();
  check("failure not claimed saved", !sent.some((s) => s.text.includes("Đã lưu vào kho")));
  check("failure notice sent", sent.some((s) => s.text.includes("trục trặc")));
  clock += 61;    // first backoff = 60s
  await core.tick();
  check("retry saved", saves.length === 1);

  // 7) restart: open batch restored from stored state
  await core.handleMessage(Z, ev("text", { body: LIST_A, msg_id: "a9" }), {});
  const core2 = createCore(makeDeps());
  saves = [];
  clock += 16;
  await core2.tick();
  check("open batch survives restart + saves", saves.length === 1);

  const fails = results.filter((r) => !r[1]);
  console.log(`\n${results.length - fails.length}/${results.length} pass`);
  process.exit(fails.length ? 1 : 0);
})().catch((e) => { console.error("ERR", e); process.exit(1); });
