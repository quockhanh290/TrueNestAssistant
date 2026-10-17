/* TrueNest Zalo -> Telegram bridge.
 *
 * A dedicated Zalo personal account (nick phu, NEVER the main account)
 * receives listing forwards via 1:1 DM. This bridge:
 *   1. Redeems pairing codes (ZN-XXXXXX) -> links zalo_id to telegram_id.
 *   2. For linked senders: parses listing-like messages, forwards to the
 *      broker's Telegram via bot Linh (Bot API), entering normal intake flow.
 *   3. For unknown senders: replies once with pairing instructions.
 *
 * Run: node bridge.js            (uses saved credentials)
 *      node bridge.js --pair     (QR login, first time only)
 *
 * Env:
 *   BOT_DB_PATH        (optional, sqlite db path)
 *   ZALO_BRIDGE_DATA   (optional, dir for credentials; default ./data)
 */

const fs = require("node:fs");
const path = require("node:path");
const https = require("node:https");
const { execFileSync } = require("node:child_process");
const { Zalo, ThreadType, LoginQRCallbackEventType } = require("zca-js");

// ---- config ----
const ROOT = path.resolve(__dirname, "..");
const DATA = process.env.ZALO_BRIDGE_DATA || path.join(__dirname, "data");
const CRED_PATH = path.join(DATA, "zalo-credentials.json");
const QR_PATH = path.join(DATA, "zalo-qr.png");
const DB_CLI = path.join(__dirname, "db_cli.py");
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
  console.error("token.txt missing - cannot send to Telegram. Exiting.");
  process.exit(1);
}

// ---- db access via python (respects api.py/db-package law) ----
function dbCall(...args) {
  try {
    const out = execFileSync("python3", [DB_CLI, ...args], {
      encoding: "utf8",
      timeout: 15000,
    });
    return JSON.parse(out.trim().split("\n").pop());
  } catch (e) {
    console.error("dbCall failed:", e.message);
    return { ok: false, error: "db_unreachable" };
  }
}

// ---- telegram send ----
function tgApi(method, payload) {
  return new Promise((resolve) => {
    const body = JSON.stringify(payload);
    const req = https.request(
      {
        hostname: "api.telegram.org",
        path: `/bot${BOT_TOKEN}/${method}`,
        method: "POST",
        headers: { "Content-Type": "application/json", "Content-Length": body.length },
      },
      (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => {
          try {
            resolve(JSON.parse(data));
          } catch {
            resolve({ ok: false });
          }
        });
      }
    );
    req.on("error", () => resolve({ ok: false }));
    req.setTimeout(20000, () => {
      req.destroy();
      resolve({ ok: false });
    });
    req.write(body);
    req.end();
  });
}

// ---- listing parse (mirrors inbox/adapters/zalo/broker-bot.js) ----
function parseListing(text) {
  const out = { price_vnd: null, bedrooms: null, phone: null, district: null };
  const t = (text || "").toLowerCase();
  let m = t.match(/(\d+(?:[.,]\d+)?)\s*(tr|triệu|million)/);
  if (m) out.price_vnd = Math.round(parseFloat(m[1].replace(",", ".")) * 1e6);
  if (!out.price_vnd) {
    m = t.match(/(\d{7,9})(?:\s*(vnd|đ|d))?/);
    if (m) out.price_vnd = parseInt(m[1], 10);
  }
  m = t.match(/(\d+)\s*(pn|phòng ngủ|bed)/);
  if (m) out.bedrooms = parseInt(m[1], 10);
  else if (/studio/.test(t)) out.bedrooms = 0;
  m = (text || "").replace(/[\s.]/g, "").match(/(0\d{9}|84\d{9})/);
  if (m) out.phone = m[1];
  const districts = ["hải châu", "sơn trà", "ngũ hành sơn", "liên chiểu", "cẩm lệ", "thanh khê", "hòa vang"];
  for (const d of districts) {
    if (t.includes(d)) {
      out.district = d;
      break;
    }
  }
  return out;
}

function looksLikeListing(text, photoCount) {
  if (!text || text.length < 20) return false;
  const p = parseListing(text);
  return !!(p.price_vnd || (p.bedrooms !== null && photoCount > 0) || (p.phone && p.price_vnd));
}

// ---- rate limiting (per zalo sender) ----
const lastReply = new Map(); // zaloId -> ts (for unlinked guidance)
const msgCount = new Map(); // zaloId -> {n, windowStart}
function tooFast(zaloId, limit = 20, windowMs = 60_000) {
  const now = Date.now();
  let e = msgCount.get(zaloId);
  if (!e || now - e.windowStart > windowMs) {
    e = { n: 0, windowStart: now };
    msgCount.set(zaloId, e);
  }
  e.n += 1;
  return e.n > limit;
}

const PAIRING_RE = /^\s*ZN-[A-Z0-9]{6}\s*$/i;
const UNLINK_RE = /^\s*HUY LINK\s*$/i;

const GUIDE_TEXT =
  "Chào bạn, đây là tài khoản nhận tin của TrueNest.\n\n" +
  "Để liên kết: mở bot TrueNest trên Telegram, gửi /linkzalo để lấy mã, " +
  "rồi gửi mã đó vào đây.\n\n" +
  "Sau khi liên kết, bạn forward tin listing vào đây là tin tự về Telegram của bạn.";

async function handleMessage(api, msg) {
  try {
    if (msg.isSelf) return;
    if (msg.type !== ThreadType.User) return; // 1:1 DM only, ignore groups

    const text = typeof msg.data?.content === "string" ? msg.data.content : "";
    const zaloId = String(msg.data?.uidFrom || msg.threadId || "");
    const zaloName = msg.data?.senderName || "";
    if (!zaloId) return;
    if (tooFast(zaloId)) return; // silent drop on flood

    // 1. pairing code?
    if (PAIRING_RE.test(text)) {
      const r = dbCall("redeem", text.trim().toUpperCase(), zaloId, zaloName);
      if (r.ok) {
        await api.sendMessage(
          { msg: "✅ Đã liên kết! Từ giờ bạn forward tin listing vào đây, tin sẽ tự về Telegram của bạn." },
          zaloId,
          ThreadType.User
        );
        await tgApi("sendMessage", {
          chat_id: r.telegram_id,
          text: "🔗 <b>Đã liên kết Zalo!</b>\n\nTừ giờ bạn forward tin listing vào tài khoản Zalo nhận tin, tin sẽ tự về đây để bạn xác nhận.",
          parse_mode: "HTML",
        });
      } else {
        const why =
          r.error === "expired"
            ? "mã đã hết hạn (15 phút)"
            : r.error === "used"
            ? "mã đã được dùng rồi"
            : "mã không đúng";
        await api.sendMessage(
          { msg: `❌ ${why}. Mở bot Telegram gửi /linkzalo để lấy mã mới nhé.` },
          zaloId,
          ThreadType.User
        );
      }
      return;
    }

    // 2. unlink?
    if (UNLINK_RE.test(text)) {
      const r = dbCall("unlink", zaloId);
      await api.sendMessage(
        { msg: r.ok ? "✅ Đã hủy liên kết." : "Bạn chưa liên kết tài khoản nào." },
        zaloId,
        ThreadType.User
      );
      return;
    }

    // 3. linked?
    const link = dbCall("lookup", zaloId);
    const telegramId = link.ok ? link.telegram_id : null;
    if (!telegramId) {
      const now = Date.now();
      if (now - (lastReply.get(zaloId) || 0) > 3600_000) {
        lastReply.set(zaloId, now);
        await api.sendMessage({ msg: GUIDE_TEXT }, zaloId, ThreadType.User);
      }
      return;
    }

    // 4. listing forward -> parse + push to Telegram
    const photoCount = Array.isArray(msg.data?.attachments)
      ? msg.data.attachments.filter((a) => a.type === "photo" || a.type === "image").length
      : 0;
    if (!looksLikeListing(text, photoCount)) {
      return; // not a listing, ignore quietly
    }
    const p = parseListing(text);
    const lines = ["📥 <b>Tin mới từ Zalo</b>", ""];
    if (p.price_vnd) lines.push(`💰 ${p.price_vnd.toLocaleString("vi-VN")}đ`);
    if (p.bedrooms !== null) lines.push(`🏠 ${p.bedrooms === 0 ? "Studio" : p.bedrooms + "PN"}`);
    if (p.district) lines.push(`📍 ${p.district}`);
    if (p.phone) lines.push(`📱 ${p.phone}`);
    if (photoCount) lines.push(`🖼️ ${photoCount} ảnh`);
    lines.push("", "Reply tin này để nhập vào kho (luồng intake bình thường).");
    // keep original text for the broker to review
    const preview = text.length > 600 ? text.slice(0, 600) + "…" : text;
    lines.push("", `<i>${escapeHtml(preview)}</i>`);

    await tgApi("sendMessage", {
      chat_id: telegramId,
      text: lines.join("\n"),
      parse_mode: "HTML",
    });
    await api.sendMessage(
      { msg: "✅ Đã chuyển tin qua Telegram của bạn. Mở bot để xác nhận nhé." },
      zaloId,
      ThreadType.User
    );
  } catch (e) {
    console.error("handleMessage error:", e.message);
  }
}

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function main() {
  const zalo = new Zalo();
  const wantPair = process.argv.includes("--pair");

  let api;
  if (wantPair || !fs.existsSync(CRED_PATH)) {
    console.log("QR login: scan", QR_PATH);
    api = await zalo.loginQR(
      {},
      (event, data) => {
        if (event === LoginQRCallbackEventType.QR_GENERATED && data?.qrCode) {
          fs.writeFileSync(QR_PATH, Buffer.from(data.qrCode.split(",")[1] || data.qrCode, "base64"));
          console.log("QR saved to", QR_PATH);
        }
      }
    );
    fs.writeFileSync(CRED_PATH, JSON.stringify(api.getContext?.() || {}), { mode: 0o600 });
    console.log("Credentials saved.");
  } else {
    const creds = JSON.parse(fs.readFileSync(CRED_PATH, "utf8"));
    api = await zalo.login(creds);
  }

  api.listener.on("message", (msg) => handleMessage(api, msg));
  api.listener.start();
  console.log("Zalo bridge listening (1:1 DMs only).");
}

main().catch((e) => {
  console.error("fatal:", e);
  process.exit(1);
});
