/* TrueNest v2 - khung điều hướng + các tab Khách / Lịch xem / Hoa hồng.
 * Dữ liệu lấy qua api.js (TrueNestAPI); tệp này chỉ dựng giao diện. Màn "Căn hộ" nằm ở listings.js.
 * Trường dùng (webapp/api_clients_deals.py):
 *   clients  -> id, name, phone, status, status_vi, urgency, req_summary, notes
 *   viewings -> id, client_name, listing_ids, scheduled_at (epoch giây), status, notes
 *   deals    -> month, month_total, closed[], negotiating[] (client_name, listing_id, commission_vnd, paid, closed_at, notes)
 */
(function () {
  'use strict';
  var UI = window.TrueNestUI, API = window.TrueNestAPI, I = UI.ICON, esc = UI.esc;
  var doc = document;

  var META = {
    listings: { title: 'Quản lý căn', icon: I.building(18) },
    clients: { title: 'Khách hàng', icon: I.users(18) },
    viewings: { title: 'Lịch xem', icon: I.calendar(18) },
    deals: { title: 'Hoa hồng', icon: I.wallet(18) }
  };
  var reg = {}, counts = {}, current = '';

  var titleEl = doc.getElementById('topbar-title'), iconEl = doc.getElementById('topbar-icon'), pillEl = doc.getElementById('topbar-count');
  var fab = doc.getElementById('fab-add');

  function paintCount() {
    var t = counts[current] || '';
    pillEl.textContent = t; pillEl.hidden = !t;
  }

  var App = window.TrueNestApp = {
    register: function (name, v) { reg[name] = { load: v.load, loaded: false }; },
    setCount: function (name, text) { counts[name] = text; if (name === current) paintCount(); },
    invalidate: function (name) {
      var v = reg[name]; if (!v) return;
      v.loaded = false;
      if (name === current && v.load) { v.loaded = true; v.load(); }
    },
    show: function (name) {
      if (!reg[name]) return;
      current = name;
      doc.querySelectorAll('[data-view]').forEach(function (el) { el.hidden = el.getAttribute('data-view') !== name; });
      doc.querySelectorAll('.nav button').forEach(function (b) {
        if (b.getAttribute('data-nav') === name) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
      });
      titleEl.textContent = META[name].title; iconEl.innerHTML = META[name].icon;
      fab.hidden = name !== 'listings';
      paintCount();
      var v = reg[name];
      if (!v.loaded) { v.loaded = true; v.load(); }
      window.scrollTo(0, 0);
    },
    start: function (name) { App.show(name); }
  };

  doc.querySelector('.nav').addEventListener('click', function (e) {
    var b = e.target.closest('button[data-nav]'); if (!b) return;
    UI.haptic(); App.show(b.getAttribute('data-nav'));
  });

  /* ---------- tiện ích dùng chung cho 3 tab ---------- */
  function box(name) { return doc.getElementById(name + '-list'); }
  function loadingState(el) { el.innerHTML = '<div class="state" role="status">Đang tải…</div>'; }
  function failState(el, e, retry) {
    var msg = e && e.status === 401
      ? (API.authMode() === 'none' ? 'Mở ứng dụng từ Telegram, hoặc thêm ?demo=1&broker_id=… vào địa chỉ khi thử trên máy.' : 'Phiên đăng nhập không hợp lệ. Hãy mở lại từ Telegram.')
      : 'Không tải được' + (e && e.message ? ' (' + esc(e.message) + ')' : '') + '.';
    el.innerHTML = '<div class="state state--error" role="alert">' + msg + '<br><button type="button">Thử lại</button></div>';
    el.querySelector('button').addEventListener('click', retry);
  }
  function empty(el, text) { el.innerHTML = '<div class="state">' + esc(text) + '</div>'; }

  /* ---------- Khách ---------- */
  var URGENCY = { urgent: ['Gấp', 'pill--bad'], low: ['Thấp', ''] };
  function loadClients() {
    var el = box('clients'); loadingState(el);
    API.clients().then(function (data) {
      var list = data.clients || [];
      App.setCount('clients', list.length + ' khách');
      if (!list.length) return empty(el, 'Chưa có khách hàng nào.');
      el.innerHTML = list.map(function (c) {
        var u = URGENCY[c.urgency];
        var h = '<article class="card row-card"><div class="row-card__top"><h2 class="row-card__name">' + esc(c.name) + '</h2><span class="pill">' + esc(c.status_vi || c.status) + '</span></div>';
        if (c.req_summary && c.req_summary !== '—') h += '<p class="row-card__sub">' + esc(c.req_summary) + '</p>';
        if (c.notes) h += '<p class="row-card__sub">' + esc(c.notes) + '</p>';
        h += '<div class="row-card__meta">';
        h += c.phone ? '<a class="row-card__call" href="tel:' + esc(String(c.phone).replace(/[^\d+]/g, '')) + '">' + I.phone(16) + esc(c.phone) + '</a>' : '<span></span>';
        if (u) h += '<span class="pill ' + u[1] + '">' + u[0] + '</span>';
        return h + '</div></article>';
      }).join('');
    }, function (e) { failState(el, e, loadClients); });
  }

  /* ---------- Lịch xem ---------- */
  var VIEW_ST = { scheduled: ['Đã hẹn', ''], done: ['Đã xem', 'pill--good'], cancelled: ['Đã huỷ', 'pill--bad'] };
  function loadViewings() {
    var el = box('viewings'); loadingState(el);
    API.viewings().then(function (data) {
      var list = data.viewings || [];
      App.setCount('viewings', list.length + ' lịch');
      if (!list.length) return empty(el, 'Chưa có lịch xem sắp tới.');
      el.innerHTML = list.map(function (v) {
        var st = VIEW_ST[v.status] || [v.status || '', ''];
        var n = (v.listing_ids || []).length;
        var h = '<article class="card row-card"><div class="row-card__top"><h2 class="row-card__name">' + esc(v.client_name || 'Khách') + '</h2><span class="pill ' + st[1] + '">' + esc(st[0]) + '</span></div>';
        h += '<p class="row-card__sub">' + I.calendar(13, ' style="vertical-align:-2px;margin-right:4px"') + esc(UI.fmtDateTime(v.scheduled_at)) + (n ? ' · ' + n + ' căn' : '') + '</p>';
        if (v.notes) h += '<p class="row-card__sub">' + esc(v.notes) + '</p>';
        return h + '</article>';
      }).join('');
    }, function (e) { failState(el, e, loadViewings); });
  }

  /* ---------- Hoa hồng ---------- */
  function dealCard(d) {
    var sub = [UI.fmtDate(d.closed_at), d.notes].filter(Boolean).join(' · ');
    return '<article class="card row-card"><div class="row-card__top"><h2 class="row-card__name">' + esc(d.client_name || 'Giao dịch') + '</h2>' +
      '<span class="pill ' + (d.paid ? 'pill--good' : 'pill--warn') + '">' + UI.fmtMoney(d.commission_vnd) + '</span></div>' +
      (sub ? '<p class="row-card__sub">' + esc(sub) + '</p>' : '') + '</article>';
  }
  function loadDeals() {
    var el = box('deals'); loadingState(el);
    API.deals().then(function (data) {
      var closed = data.closed || [], pending = data.negotiating || [];
      var m = String(data.month || '').split('-');
      var label = m.length === 2 ? 'Hoa hồng đã nhận tháng ' + m[1] + '/' + m[0] : 'Hoa hồng đã nhận tháng này';
      App.setCount('deals', UI.fmtMoney(data.month_total));
      var h = '<div class="card sum-card"><p class="sum-card__label">' + esc(label) + '</p><p class="sum-card__value">' + UI.fmtMoney(data.month_total) + '</p></div>';
      if (!closed.length && !pending.length) h += '<div class="state">Chưa có giao dịch nào trong tháng.</div>';
      if (closed.length) h += '<h3 class="section-label">Đã thanh toán (' + closed.length + ')</h3>' + closed.map(dealCard).join('');
      if (pending.length) h += '<h3 class="section-label">Chưa thanh toán (' + pending.length + ')</h3>' + pending.map(dealCard).join('');
      el.innerHTML = h;
    }, function (e) { failState(el, e, loadDeals); });
  }

  App.register('clients', { load: loadClients });
  App.register('viewings', { load: loadViewings });
  App.register('deals', { load: loadDeals });
})();
