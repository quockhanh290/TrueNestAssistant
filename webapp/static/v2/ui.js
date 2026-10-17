/* TrueNest v2 - tiện ích giao diện dùng chung (định dạng, biểu tượng, hộp thoại, thông báo, cầu nối Telegram).
 * Không gọi API. Mọi hàm Telegram đều được bọc để chạy được cả khi mở ngoài Telegram.
 */
(function (root) {
  'use strict';
  var doc = root.document;

  function tg() { return (root.Telegram && root.Telegram.WebApp) || null; }
  function inTelegram() { var t = tg(); return !!(t && t.initData); }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (m) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
    });
  }

  /** 12500000 -> "12,5 tr"; 28000000 -> "28 tr"; rỗng -> "" */
  function fmtPrice(vnd) {
    var n = Number(vnd);
    if (!isFinite(n) || n <= 0) return '';
    var tr = n / 1e6;
    var s = (Math.round(tr * 10) / 10).toString().replace('.', ',');
    return s + ' tr';
  }
  function fmtMoney(vnd) {
    var n = Number(vnd);
    if (!isFinite(n)) return '0 tr';
    var s = (Math.round(n / 1e5) / 10).toString().replace('.', ',');
    return s + ' tr';
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  /** epoch giây -> "15/11 14:30" */
  function fmtDateTime(sec) {
    var n = Number(sec); if (!isFinite(n) || n <= 0) return '';
    var d = new Date(n * 1000);
    return pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function fmtDate(sec) {
    var n = Number(sec); if (!isFinite(n) || n <= 0) return '';
    var d = new Date(n * 1000);
    return pad(d.getDate()) + '/' + pad(d.getMonth() + 1);
  }
  /** epoch giây -> "hôm nay" / "3 ngày trước" */
  function ago(sec) {
    var n = Number(sec); if (!isFinite(n) || n <= 0) return '';
    var days = Math.floor((Date.now() / 1000 - n) / 86400);
    if (days <= 0) return 'hôm nay';
    if (days < 60) return days + ' ngày trước';
    return Math.floor(days / 30) + ' tháng trước';
  }

  function svg(inner, size, extra) {
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"' + (extra || '') + '>' + inner + '</svg>';
  }
  /* Đường nét lấy từ mẫu UI/Main.dc.html (bộ biểu tượng Lucide) */
  var P = {
    building: '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"></path><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"></path><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"></path><path d="M10 6h4"></path><path d="M10 10h4"></path><path d="M10 14h4"></path><path d="M10 18h4"></path>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M22 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path>',
    calendar: '<rect width="18" height="18" x="3" y="4" rx="2" ry="2"></rect><line x1="16" x2="16" y1="2" y2="6"></line><line x1="8" x2="8" y1="2" y2="6"></line><line x1="3" x2="21" y1="10" y2="10"></line>',
    calendarPlus: '<rect width="18" height="18" x="3" y="4" rx="2" ry="2"></rect><line x1="16" x2="16" y1="2" y2="6"></line><line x1="8" x2="8" y1="2" y2="6"></line><line x1="3" x2="21" y1="10" y2="10"></line><line x1="12" x2="12" y1="13" y2="19"></line><line x1="9" x2="15" y1="16" y2="16"></line>',
    wallet: '<rect width="20" height="12" x="2" y="6" rx="2"></rect><circle cx="12" cy="12" r="2"></circle><path d="M6 12h.01M18 12h.01"></path>',
    back: '<path d="m12 19-7-7 7-7"></path><path d="M19 12H5"></path>',
    close: '<path d="M18 6 6 18"></path><path d="m6 6 12 12"></path>',
    search: '<circle cx="11" cy="11" r="8"></circle><path d="m21 21-4.3-4.3"></path>',
    sliders: '<line x1="21" x2="14" y1="4" y2="4"></line><line x1="10" x2="3" y1="4" y2="4"></line><line x1="21" x2="12" y1="12" y2="12"></line><line x1="8" x2="3" y1="12" y2="12"></line><line x1="21" x2="16" y1="20" y2="20"></line><line x1="12" x2="3" y1="20" y2="20"></line><line x1="14" x2="14" y1="2" y2="6"></line><line x1="8" x2="8" y1="10" y2="14"></line><line x1="16" x2="16" y1="18" y2="22"></line>',
    plus: '<path d="M5 12h14"></path><path d="M12 5v14"></path>',
    image: '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"></rect><circle cx="9" cy="9" r="2"></circle><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"></path>',
    pin: '<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"></path><circle cx="12" cy="10" r="3"></circle>',
    bed: '<path d="M2 4v16"></path><path d="M2 8h18a2 2 0 0 1 2 2v10"></path><path d="M2 17h20"></path><path d="M6 8v9"></path>',
    bath: '<path d="M9 6 6.5 3.5a1.5 1.5 0 0 0-1-1C4.7 2.5 4 3.2 4 4v2"></path><path d="M2 12h20"></path><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"></path>',
    ruler: '<path d="M21.3 8.7 8.7 21.3c-1 1-2.5 1-3.4 0l-2.6-2.6c-1-1-1-2.5 0-3.4L15.3 2.7c1-1 2.5-1 3.4 0l2.6 2.6c1 1 1 2.5 0 3.4Z"></path><path d="m14.5 3.5 2 2"></path><path d="m11.5 6.5 2 2"></path><path d="m8.5 9.5 2 2"></path><path d="m5.5 12.5 2 2"></path>',
    wifi: '<path d="M5 12.55a11 11 0 0 1 14.08 0"></path><path d="M1.42 9a16 16 0 0 1 21.16 0"></path><path d="M8.53 16.11a6 6 0 0 1 6.95 0"></path><line x1="12" x2="12.01" y1="20" y2="20"></line>',
    waves: '<path d="M2 6c.6.5 1.2 1 2.5 1C7 7 7 5 9.5 5c2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"></path><path d="M2 12c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"></path><path d="M2 18c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"></path>',
    dumbbell: '<path d="m6.5 6.5 11 11"></path><path d="m21 21-1-1"></path><path d="m3 3 1 1"></path><path d="m18 22 4-4"></path><path d="m2 6 4-4"></path>',
    tag: '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"></path><circle cx="7.5" cy="7.5" r=".5"></circle>',
    phone: '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"></path>',
    share: '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"></path><polyline points="16 6 12 2 8 6"></polyline><line x1="12" x2="12" y1="2" y2="15"></line>',
    alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"></path><path d="M12 9v4"></path><path d="M12 17h.01"></path>'
  };
  var ICON = {};
  Object.keys(P).forEach(function (k) {
    ICON[k] = function (size, extra) { return svg(P[k], size || 16, extra); };
  });
  ICON.imageThin = function () { return svg(P.image, 30).replace('stroke-width="2"', 'stroke-width="1.75"'); };

  function haptic(kind) {
    var t = tg();
    if (!inTelegram()) return;   // ngoài Telegram thư viện chỉ in cảnh báo "không hỗ trợ"
    try {
      if (t && t.HapticFeedback) {
        if (kind === 'ok' && t.HapticFeedback.notificationOccurred) t.HapticFeedback.notificationOccurred('success');
        else if (t.HapticFeedback.impactOccurred) t.HapticFeedback.impactOccurred('light');
      }
    } catch (e) { /* ngoài Telegram */ }
  }

  var toastTimer = null;
  function toast(msg) {
    var el = doc.getElementById('toast');
    if (!el) { el = doc.createElement('div'); el.id = 'toast'; el.className = 'toast'; el.setAttribute('role', 'status'); doc.body.appendChild(el); }
    el.textContent = msg; el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 3200);
  }

  /** Mở hộp thoại dưới. build(contentEl, api) điền nội dung. Trả về { close }. */
  function sheet(title, build) {
    var scrim = doc.createElement('div');
    scrim.className = 'scrim';
    var box = doc.createElement('div');
    box.className = 'sheet'; box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true'); box.setAttribute('aria-label', title);
    box.innerHTML = '<div class="sheet__head"><h2>' + esc(title) + '</h2><button type="button" class="icon-btn" aria-label="Đóng">' + ICON.close(18) + '</button></div><div class="sheet__body"></div>';
    scrim.appendChild(box); doc.body.appendChild(scrim);
    var prevFocus = doc.activeElement;
    function close() {
      doc.removeEventListener('keydown', onKey);
      if (scrim.parentNode) scrim.parentNode.removeChild(scrim);
      if (prevFocus && prevFocus.focus) { try { prevFocus.focus(); } catch (e) { /* bỏ qua */ } }
    }
    function onKey(e) { if (e.key === 'Escape') close(); }
    doc.addEventListener('keydown', onKey);
    scrim.addEventListener('click', function (e) { if (e.target === scrim) close(); });
    box.querySelector('.icon-btn').addEventListener('click', close);
    var api = { close: close, box: box };
    build(box.querySelector('.sheet__body'), api);
    var first = box.querySelector('input,select,button.btn');
    if (first) { try { first.focus(); } catch (e) { /* bỏ qua */ } }
    return api;
  }

  function callPhone(phone) {
    var p = String(phone || '').replace(/[^\d+]/g, '');
    if (!p) return false;
    root.location.href = 'tel:' + p;
    return true;
  }

  root.TrueNestUI = {
    tg: tg, inTelegram: inTelegram, esc: esc,
    fmtPrice: fmtPrice, fmtMoney: fmtMoney, fmtDateTime: fmtDateTime, fmtDate: fmtDate, ago: ago,
    ICON: ICON, haptic: haptic, toast: toast, sheet: sheet, callPhone: callPhone
  };
})(window);
