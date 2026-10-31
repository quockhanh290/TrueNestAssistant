/* TrueNest Zalo intake bridge v2.
 *
 * A dedicated Zalo personal account (NEVER Khanh's main account)
 * receives listing forwards via 1:1 DM. v2 (spec: BRIDGE_V2.md):
 * messages are grouped by the batching engine (batch.js, port of the
 * Python engine), closed batches AUTO-SAVE as draft listings through
 * save_cli.py -> bridge_save.py, photo-only follow-ups ask GỘP/MỚI,
 * HUY undoes the latest save within 10 minutes. State persists in
 * <data>/bridge-state.json so open batches survive restarts.
 *
 * Run: node bridge.js            (uses saved credentials)
 *      node bridge.js --pair     (QR login, first time only)
 *
 * Env:
 *   BOT_DB_PATH        (optional, sqlite db path)
 *   ZALO_BRIDGE_DATA   (optional, dir for credentials+state; default ./data)
 */

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const https = require("node:https");
const { execFile, execFileSync } = require("node:child_process");
const { Zalo, ThreadType, LoginQRCallbackEventType } = require("zca-js");
const { createCore } = require("./core.js");

// ---- config ----
const ROOT = path.resolve(__dirname, "..");
const DATA = process.env.ZALO_BRIDGE_DATA || path.join(__dirname, "data");
const CRED_PATH = path.join(DATA, "zalo-credentials.json");
const QR_PATH = path.join(DATA, "zalo-qr.png");
const STATE_PATH = path.join(DATA, "bridge-state.json");
const DB_CLI = path.join(__dirname, "db_cli.py");
const SAVE_CLI = path.join(__dirname, "save_cli.py");
const TOKEN_TXT = path.join(ROOT, "token.txt");

fs.mkdirSync(DATA, { recursive: true, mode: 0o700 });

function readBotToken() {
  try {
    return fs.readFileSync(TOKEN_TXT, "utf8").trim().split(/\s+/)[0];
  } catch {
    return "";
  }
}
const BOT_TOKEN = readBotToken();
if (!BOT_TOKEN) {
  console.error("token.txt missing - cannot notify Telegram. Exiting.");
  process.exit(1);
}

// ---- db access via python (pairing links) ----
function dbCall(...args) {
  try {
    const out = execFileSync("python3", [DB_CLI, ...args], {
      encoding: "utf8", timeout: 15000,
    });
    return JSON.parse(out.trim().split("\n").pop());
  } catch (e) {
    console.error("dbCall failed:", e.message);
    return { ok: false, error: "db_unreachable" };
  }
}

// ---- save via python one-shot (bridge_save.py) ----
function saveCli(args) {
  return new Promise((resolve) => {
    execFile("python3", [SAVE_CLI, ...args], { timeout: 120000 },
      (err, stdout) => {
        if (err) { console.error("saveCli failed:", err.message); return resolve(null); }
        try { resolve(JSON.parse(stdout.trim().split("\n").pop())); }
        catch { resolve(null); }
      });
  });
}

async function withTempPhotos(photoBuffers, fn) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "zalo-bridge-"));
  try {
    photoBuffers.forEach((buf, i) =>
      fs.writeFileSync(path.join(dir, String(i).padStart(3, "0") + ".jpg"), buf));
    return await fn(dir);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

const saveDeps = {
  async saveListing({ tgId, text, photoBuffers }) {
    const txtFile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "zb-t-")), "t.txt");
    fs.writeFileSync(txtFile, text || "", "utf8");
    try {
      return await withTempPhotos(photoBuffers, (dir) =>
        saveCli(["save", "--tg", String(tgId), "--text-file", txtFile, "--photos", dir]));
    } finally {
      fs.rmSync(path.dirname(txtFile), { recursive: true, force: true });
    }
  },
  async appendPhotos({ listingId, photoBuffers }) {
    return withTempPhotos(photoBuffers, (dir) =>
      saveCli(["append", "--listing", listingId, "--photos", dir]));
  },
  async undoListing(listingId) {
    return saveCli(["undo", "--listing", listingId]);
  },
};

// ---- telegram notify ----
function tgSend(chatId, text) {
  const body = JSON.stringify({ chat_id: chatId, text });
  const req = https.request(
    { hostname: "api.telegram.org", path: `/bot${BOT_TOKEN}/sendMessage`,
      method: "POST",
      headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) } },
    (res) => res.resume());
  req.on("error", () => {});
  req.write(body);
  req.end();
}

// ---- state persistence (atomic) ----
function loadState() {
  try { return JSON.parse(fs.readFileSync(STATE_PATH, "utf8")); }
  catch { return null; }
}
function storeState(obj) {
  const tmp = STATE_PATH + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(obj), { mode: 0o600 });
  fs.renameSync(tmp, STATE_PATH);
}

// ---- zca message -> normalized engine event ----
function quoteDataOf(data) {
  if (!data || data.msgId === undefined) return null;
  return {
    content: typeof data.content === "string" ? data.content : "",
    msgType: data.msgType, propertyExt: data.propertyExt,
    uidFrom: data.uidFrom, msgId: data.msgId, cliMsgId: data.cliMsgId,
    ts: data.ts, ttl: data.ttl,
  };
}

function normalize(api, core, msg) {
  if (msg.isSelf) return;
  if (msg.type !== ThreadType.User) return;      // 1:1 DM only
  const data = msg.data || {};
  const sender = String(data.uidFrom || msg.threadId || "");
  if (!sender) return;
  const raw = { quoteData: quoteDataOf(data), name: data.senderName || "" };
  const msgId = String(data.msgId || "");

  const content = data.content;
  if (typeof content === "string") {
    core.handleMessage(sender, { sender, kind: "text", body: content, msg_id: msgId }, raw)
      .catch((e) => console.error("handleMessage:", e.message));
    return;
  }
  // photo/video/file messages: content is an object with an href
  const atts = Array.isArray(data.attachments) && data.attachments.length
    ? data.attachments : null;
  const items = atts || (content && typeof content === "object" ? [content] : []);
  if (!items.length) {
    core.handleMessage(sender, { sender, kind: "sticker", msg_id: msgId }, raw)
      .catch(() => {});
    return;
  }
  items.forEach((att, i) => {
    const url = att.href || att.hdUrl || att.hd_url || "";
    const typeStr = String(att.type || data.msgType || "");
    let kind = "document";
    if (/photo|image/i.test(typeStr) || (!atts && /photo|image/i.test(String(data.msgType || "")))) kind = "image";
    else if (/video/i.test(typeStr)) kind = "video";
    const pid = String(att.msgId || att.id || (items.length > 1 ? `${msgId}:${i}` : msgId));
    if (kind === "image" && url) core.notePhotoUrl(pid, url);
    core.handleMessage(sender,
      { sender, kind, photo_id: pid, msg_id: items.length > 1 ? `${msgId}:${i}` : msgId },
      raw).catch((e) => console.error("handleMessage:", e.message));
  });
}

async function main() {
  const zalo = new Zalo();
  const wantPair = process.argv.includes("--pair");

  let api;
  if (wantPair || !fs.existsSync(CRED_PATH)) {
    console.log("QR login: scan", QR_PATH);
    api = await zalo.loginQR({}, (event, data) => {
      if (event === LoginQRCallbackEventType.QR_GENERATED && data?.qrCode) {
        fs.writeFileSync(QR_PATH, Buffer.from(data.qrCode.split(",")[1] || data.qrCode, "base64"));
        console.log("QR saved to", QR_PATH);
      }
    });
    fs.writeFileSync(CRED_PATH, JSON.stringify(api.getContext?.() || {}), { mode: 0o600 });
    console.log("Credentials saved.");
  } else {
    const creds = JSON.parse(fs.readFileSync(CRED_PATH, "utf8"));
    api = await zalo.login(creds);
  }

  const core = createCore({
    send: async (zaloId, text, quote) => {
      const payload = quote ? { msg: text, quote } : { msg: text };
      await api.sendMessage(payload, zaloId, ThreadType.User);
    },
    download: async (url) => {
      try {
        const res = await fetch(url);
        if (!res.ok) return null;
        return Buffer.from(await res.arrayBuffer());
      } catch { return null; }
    },
    dbCall,
    tgSend,
    loadState,
    storeState,
    ...saveDeps,
  });

  api.listener.on("message", (msg) => normalize(api, core, msg));
  // message recall (undo) — supported by zca-js listener; harmless if absent
  if (typeof api.listener.on === "function") {
    api.listener.on("undo", (msg) => {
      const data = msg?.data || {};
      const sender = String(data.uidFrom || msg?.threadId || "");
      const target = String(data.msgId || "");
      if (sender && target) {
        core.handleUndo(sender, target).catch((e) => console.error("undo:", e.message));
      }
    });
  }
  setInterval(() => core.tick().catch((e) => console.error("tick:", e.message)), 1000);
  api.listener.start();
  console.log("Zalo bridge v2 listening (1:1 DMs only, auto-save).");
}

main().catch((e) => {
  console.error("fatal:", e);
  process.exit(1);
});
