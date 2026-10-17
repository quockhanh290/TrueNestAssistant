/* TrueNest v2 - lớp bọc nền tảng (tầng 3).
 * Đây là NƠI DUY NHẤT trong giao diện được đọc window.Telegram và location.
 * Mọi tính năng Telegram đi qua isVersionAtLeast và có đường lùi:
 *   - nút Quay lại / Chính / Phụ: nếu không có nút gốc, hàm trả false để lớp giao diện vẽ nút thay trong nội dung;
 *   - haptic, safe-area, đổi theme: ngoài Telegram thì không làm gì (hoặc dùng prefers-color-scheme).
 */
(function (root) {
  'use strict';
  var doc = root.document;
  var BASE = '/v2';

  function tg() { return (root.Telegram && root.Telegram.WebApp) || null; }
  /* "Trong Telegram" = có initData thật. Trình duyệt thường vẫn nạp telegram-web-app.js nên WebApp tồn tại nhưng rỗng. */
  function inTelegram() { var t = tg(); return !!(t && t.initData); }
  function since(v) {
    var t = tg();
    try { return !!(inTelegram() && t.isVersionAtLeast && t.isVersionAtLeast(v)); } catch (e) { return false; }
  }
  function safe(fn) { try { return fn(); } catch (e) { return undefined; } }

  /* ---------- URL ---------- */
  var DEV_KEYS = ['demo', 'broker_id'];   // chỉ dùng khi máy chủ bật WEBAPP_DEV=1
  function qs() { try { return new URLSearchParams(root.location.search); } catch (e) { return new URLSearchParams(); } }
  function devSearch() {
    var q = qs(), out = new URLSearchParams();
    DEV_KEYS.forEach(function (k) { if (q.get(k)) out.set(k, q.get(k)); });
    var s = out.toString();
    return s ? '?' + s : '';
  }
  /** Đường dẫn trong app, bỏ tiền tố /v2: "/v2/listings/5" -> "/listings/5"; "/v2/" -> "/". */
  function path() {
    var p = root.location.pathname || '/';
    if (p.indexOf(BASE) === 0) p = p.slice(BASE.length);
    if (!p || p.charAt(0) !== '/') p = '/' + p;
    if (p.length > 1 && p.charAt(p.length - 1) === '/') p = p.slice(0, -1);
    return p;
  }
  function href(p) { return BASE + (p === '/' ? '/' : p) + devSearch() + (root.location.hash || ''); }
  function histState() { var s = root.history.state; return s && typeof s.i === 'number' ? s : null; }
  function push(p, st) { root.history.pushState(st, '', href(p)); }
  function replace(p, st) { root.history.replaceState(st, '', href(p)); }
  function onPop(fn) { root.addEventListener('popstate', function (e) { fn(e.state); }); }
  function historyBack() { root.history.back(); }

  /** start_param chỉ dùng để CHỌN màn mở; quyền sở hữu luôn kiểm ở máy chủ. */
  function startParam() {
    var t = tg();
    var v = inTelegram() && t.initDataUnsafe && t.initDataUnsafe.start_param;
    return typeof v === 'string' ? v : '';
  }

  /* ---------- xác thực (api2.js dùng) ---------- */
  function authMode() {
    if (qs().get('demo') === '1') return 'demo';
    return inTelegram() ? 'telegram' : 'none';
  }
  function authParams() {
    var q = qs();
    if (q.get('demo') === '1') return { demo: '1', broker_id: q.get('broker_id') || '' };
    return null;
  }
  function initData() { var t = tg(); return inTelegram() ? t.initData : ''; }

  /* ---------- theme + vùng an toàn ---------- */
  /* Telegram nhận từ khoá theme cho màu thanh đầu/nền/thanh đáy, nên đổi theme là đổi theo, không cần đọc màu. */
  function applyTheme() {
    var t = tg(), el = doc.documentElement, scheme;
    if (inTelegram()) {
      scheme = t.colorScheme === 'light' ? 'light' : 'dark';
    } else {
      scheme = (root.matchMedia && root.matchMedia('(prefers-color-scheme: light)').matches) ? 'light' : 'dark';
    }
    el.setAttribute('data-scheme', scheme);
    if (!inTelegram()) return;
    if (since('6.1')) {
      safe(function () { t.setHeaderColor('secondary_bg_color'); });
      safe(function () { t.setBackgroundColor('secondary_bg_color'); });
    }
    if (since('7.10')) safe(function () { t.setBottomBarColor('secondary_bg_color'); });
  }
  function applyViewport() {
    var t = tg();
    if (!inTelegram()) return;
    var h = t.viewportStableHeight || t.viewportHeight;
    if (h) doc.documentElement.style.setProperty('--tg-viewport-stable-height', h + 'px');
  }

  /* ---------- nút gốc ---------- */
  var cur = { back: null, main: null, secondary: null, settings: null };
  var nativeBack = false;

  function setBack(handler) {
    var t = tg(), b = t && t.BackButton;
    if (b && cur.back) safe(function () { b.offClick(cur.back); });
    cur.back = handler || null;
    if (!since('6.1') || !b) { nativeBack = false; return false; }
    if (handler) { safe(function () { b.onClick(handler); b.show(); }); nativeBack = true; }
    else { safe(function () { b.hide(); }); nativeBack = true; }
    return true;
  }
  function hasNativeBack() { return since('6.1') && !!(tg() && tg().BackButton); }

  function applyButton(kind, spec) {
    var t = tg(); if (!t) return false;
    var need = kind === 'main' ? '6.0' : '7.10';
    var btn = kind === 'main' ? t.MainButton : t.SecondaryButton;
    if (!since(need) || !btn) return false;
    if (cur[kind]) safe(function () { btn.offClick(cur[kind]); });
    cur[kind] = null;
    if (!spec) { safe(function () { btn.hide(); }); return true; }
    var params = { text: spec.text, is_visible: true, is_active: !spec.disabled };
    if (kind === 'secondary') params.position = 'left';
    safe(function () { btn.setParams(params); });
    cur[kind] = spec.onClick;
    safe(function () { btn.onClick(spec.onClick); });
    if (spec.loading) safe(function () { btn.showProgress(false); }); else safe(function () { btn.hideProgress(); });
    return true;
  }
  /** spec = { main: {text,onClick,disabled,loading}, secondary: {...} } (mỗi khoá có thể thiếu = ẩn nút).
   *  Trả { main: bool, secondary: bool }: true = đã dùng nút gốc, false = giao diện phải vẽ nút thay trong nội dung. */
  function setButtons(spec) {
    spec = spec || {};
    return {
      main: spec.main ? applyButton('main', spec.main) : (applyButton('main', null), false),
      secondary: spec.secondary ? applyButton('secondary', spec.secondary) : (applyButton('secondary', null), false)
    };
  }
  /** SettingsButton (7.0): một nút, dẫn tới Hồ sơ. Luôn có dòng Hồ sơ trong nội dung nên không cần đường lùi. */
  function setSettings(handler) {
    var t = tg(), b = t && t.SettingsButton;
    if (!since('7.0') || !b) return false;
    if (cur.settings) safe(function () { b.offClick(cur.settings); });
    cur.settings = handler;
    safe(function () { b.onClick(handler); b.show(); });
    return true;
  }

  /* ---------- rung: gom về một chỗ, ngoài Telegram không làm gì ---------- */
  function hf() { var t = tg(); return since('6.1') && t.HapticFeedback ? t.HapticFeedback : null; }
  var haptic = {
    select: function () { var h = hf(); if (h) safe(function () { h.selectionChanged(); }); },
    tap: function () { var h = hf(); if (h) safe(function () { h.impactOccurred('light'); }); },
    success: function () { var h = hf(); if (h) safe(function () { h.notificationOccurred('success'); }); },
    error: function () { var h = hf(); if (h) safe(function () { h.notificationOccurred('error'); }); }
  };

  /* ---------- chống thao tác nhầm ---------- */
  function lockSwipe(on) {
    var t = tg();
    if (!since('7.7')) return;
    safe(function () { on ? t.disableVerticalSwipes() : t.enableVerticalSwipes(); });
  }
  function setClosingConfirm(on) {
    var t = tg();
    if (!since('6.2')) return;
    safe(function () { on ? t.enableClosingConfirmation() : t.disableClosingConfirmation(); });
  }
  function confirm(message, cb) {
    var t = tg();
    if (since('6.2') && t.showConfirm) safe(function () { t.showConfirm(message, function (ok) { cb(!!ok); }); });
    else cb(root.confirm(message));
  }

  /* ---------- liên kết / đóng ---------- */
  function close() { var t = tg(); if (inTelegram()) safe(function () { t.close(); }); }
  function openTelegramShare(url, text) {
    var t = tg();
    if (inTelegram() && t.openTelegramLink) {
      safe(function () { t.openTelegramLink('https://t.me/share/url?url=' + encodeURIComponent(url) + '&text=' + encodeURIComponent(text || '')); });
      return true;
    }
    return false;
  }
  function openTel(phone) {
    var p = String(phone || '').replace(/[^\d+]/g, '');
    if (!p) return false;
    root.location.href = 'tel:' + p;
    return true;
  }

  /** Đường dẫn tương đối (vd "/s/abc") -> địa chỉ đầy đủ, để sao chép / mở trong trình duyệt. */
  function absUrl(p) { try { return new URL(p, root.location.href).href; } catch (e) { return p; } }
  function openLink(p) {
    var u = absUrl(p), t = tg();
    if (inTelegram() && t.openLink) { safe(function () { t.openLink(u); }); return; }
    root.open(u, '_blank', 'noopener');
  }

  var started = false;
  function init() {
    if (started) return; started = true;
    var t = tg();
    if (inTelegram()) {
      safe(function () { t.ready(); });
      safe(function () { t.expand(); });
      if (t.onEvent) {
        safe(function () { t.onEvent('themeChanged', applyTheme); });
        safe(function () { t.onEvent('viewportChanged', applyViewport); });
      }
    } else if (root.matchMedia) {
      var mq = root.matchMedia('(prefers-color-scheme: light)');
      var fn = function () { applyTheme(); };
      if (mq.addEventListener) mq.addEventListener('change', fn); else if (mq.addListener) mq.addListener(fn);
    }
    doc.documentElement.classList.toggle('in-telegram', inTelegram());
    applyTheme(); applyViewport();
  }

  root.TrueNestPlatform = {
    init: init, inTelegram: inTelegram, since: since,
    path: path, href: href, push: push, replace: replace, histState: histState, onPop: onPop, historyBack: historyBack,
    startParam: startParam, authMode: authMode, authParams: authParams, initData: initData,
    applyTheme: applyTheme,
    setBack: setBack, hasNativeBack: hasNativeBack, setButtons: setButtons, setSettings: setSettings,
    haptic: haptic, lockSwipe: lockSwipe, setClosingConfirm: setClosingConfirm, confirm: confirm,
    close: close, absUrl: absUrl, openLink: openLink, openTelegramShare: openTelegramShare, openTel: openTel
  };
})(window);
