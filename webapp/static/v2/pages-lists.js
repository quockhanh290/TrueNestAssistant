/* TrueNest v2 - các trang con dạng danh sách (đọc dữ liệu từ API đã có, chưa có form sửa):
 *   Khách (+ chi tiết khách), Lịch xem, Hoa hồng, Trang đã chia sẻ, Liên kết broker, Hồ sơ.
 * Mỗi danh sách có đủ bốn trạng thái qua UI.load: đang tải / rỗng / lỗi mạng (có Thử lại) / 401 (không có Thử lại).
 * Trường dùng (webapp/api.py, webapp/api_clients_deals.py):
 *   clients  -> id, name, phone, status, status_vi, urgency, req_summary, notes
 *   viewings -> id, client_id, client_name, listing_ids, scheduled_at (epoch giây), status, notes
 *   deals    -> month, month_total, closed[], negotiating[] (client_name, listing_id, commission_vnd, paid, closed_at, notes)
 *   shares   -> token, title, listing_count, view_count, booking_count, created_at, expires_at
 *   xbroker  -> requests[] (id, summary, urgency, response_count, max_responders, district, bedrooms, budget_max), trial
 *   profile  -> name, phone, tier, score, completeness, freshness, stats{total_listings, active_listings, rented_listings, share_views}
 */
(function () {
  'use strict';
  var UI = window.TrueNestUI, API = window.TrueNestAPI, App = window.TrueNestApp, PF = window.TrueNestPlatform, I = UI.ICON, esc = UI.esc;

  function head(title) {
    return '<header class="page-head"><h1>' + esc(title) + '</h1><span class="count-pill" data-count aria-live="polite" hidden></span></header>';
  }
  function setCount(el, text) { var p = el.querySelector('[data-count]'); if (p) { p.textContent = text || ''; p.hidden = !text; } }

  /** Dựng trang danh sách: cfg = { title, what, load, render(data)->html, count(data)->text, empty (html) }. */
  function listPage(pattern, cfg) {
    App.route(pattern, function (ctx) {
      ctx.el.innerHTML = '<div class="content">' + head(cfg.title) + '<div class="list" data-list></div></div>';
      UI.load(ctx.el.querySelector('[data-list]'), cfg.load, cfg.render, {
        what: cfg.what, empty: cfg.empty, skeletonH: cfg.skeletonH,
        onData: function (d) { setCount(ctx.el, cfg.count ? cfg.count(d) : ''); },
        onError: function () { setCount(ctx.el, ''); }
      });
      return { buttons: function () { return {}; } };
    });
  }
  function callBtn(phone) {
    return phone ? '<button type="button" class="row-card__call" data-call="' + esc(phone) + '">' + I.phone(16) + esc(phone) + '</button>' : '<span></span>';
  }
  function bindCalls(el) {
    el.addEventListener('click', function (e) {
      var b = e.target.closest('[data-call]'); if (!b) return;
      PF.haptic.tap();
      if (!UI.callPhone(b.getAttribute('data-call'))) UI.toast('Không có số điện thoại');
    });
  }

  /* ---------- Khách ---------- */
  var URGENCY = { urgent: ['Gấp', 'pill--bad'], low: ['Thấp', ''] };
  App.route('/clients', function (ctx) {
    ctx.el.innerHTML = '<div class="content">' + head('Khách') + '<div class="list" data-list></div></div>';
    var list = ctx.el.querySelector('[data-list]');
    bindCalls(list);
    UI.load(list, function () { return API.clients(); }, function (data) {
      var cs = data.clients || [];
      if (!cs.length) return '';
      return cs.map(function (c) {
        var u = URGENCY[c.urgency];
        var h = '<article class="card row-card"><a class="row-card__link" href="/v2/clients/' + esc(encodeURIComponent(c.id)) + '" data-go="/clients/' + esc(encodeURIComponent(c.id)) + '">' +
          '<div class="row-card__top"><h2 class="row-card__name">' + esc(c.name) + '</h2><span class="pill">' + esc(c.status_vi || c.status) + '</span></div>';
        if (c.req_summary && c.req_summary !== '—') h += '<p class="row-card__sub">' + esc(c.req_summary) + '</p>';
        if (c.notes) h += '<p class="row-card__sub">' + esc(c.notes) + '</p>';
        h += '</a><div class="row-card__meta">' + callBtn(c.phone) + (u ? '<span class="pill ' + u[1] + '">' + u[0] + '</span>' : '') + '</div></article>';
        return h;
      }).join('');
    }, {
      what: 'danh sách khách', skeletonH: 96,
      empty: UI.emptyState('users', 'Chưa có khách nào', 'Thêm khách đầu tiên bằng cách gửi yêu cầu của khách cho bot.',
        '<a class="add" href="/v2/clients/new" data-go="/clients/new">' + I.plus(16) + 'Thêm khách</a>'),
      onData: function (d) { setCount(ctx.el, (d.clients || []).length ? d.clients.length + ' khách' : ''); },
      onError: function () { setCount(ctx.el, ''); }
    });
    return { buttons: function () { return {}; } };
  });

  /* ---------- Chi tiết khách (chỉ đọc) ---------- */
  App.route('/clients/:id', function (ctx) {
    var id = ctx.params.id;
    ctx.el.innerHTML = '<div class="content"><div data-body class="stack"></div></div>';
    var body = ctx.el.querySelector('[data-body]');
    bindCalls(body);
    UI.load(body, function () { return API.client(id); }, function (c) {
      var u = URGENCY[c.urgency];
      var h = '<header class="page-head"><h1>' + esc(c.name) + '</h1><span class="pill">' + esc(c.status_vi || c.status || '') + '</span>' + (u ? '<span class="pill ' + u[1] + '">' + u[0] + '</span>' : '') + '</header>';
      h += '<div class="card row-card">';
      if (c.req_summary && c.req_summary !== '—') h += '<p class="row-card__sub">Yêu cầu: ' + esc(c.req_summary) + '</p>';
      else if (c.requirements_raw) h += '<p class="row-card__sub">' + esc(c.requirements_raw) + '</p>';
      if (c.notes) h += '<p class="row-card__sub">' + esc(c.notes) + '</p>';
      h += '<div class="row-card__meta">' + callBtn(c.phone) + '</div></div>';
      var vs = c.viewings || [];
      h += '<h2 class="section-label">Lịch xem (' + vs.length + ')</h2>';
      if (!vs.length) h += '<p class="row-card__sub">Chưa có lịch xem nào với khách này.</p>';
      h += vs.map(function (v) {
        var st = VIEW_ST[v.status] || [v.status || '', ''];
        return '<div class="card row-card"><div class="row-card__top"><h3 class="row-card__name">' + esc(UI.fmtDateTime(v.scheduled_at)) + '</h3><span class="pill ' + st[1] + '">' + esc(st[0]) + '</span></div>' +
          ((v.listing_ids || []).length ? '<p class="row-card__sub">' + v.listing_ids.length + ' căn</p>' : '') + (v.notes ? '<p class="row-card__sub">' + esc(v.notes) + '</p>' : '') + '</div>';
      }).join('');
      return h;
    }, { what: 'thông tin khách', skeletonN: 2, skeletonH: 110 });
    return { buttons: function () { return {}; } };
  });

  /* ---------- Lịch xem ---------- */
  var VIEW_ST = { scheduled: ['Đã hẹn', ''], done: ['Đã xem', 'pill--good'], cancelled: ['Đã huỷ', 'pill--bad'] };
  listPage('/viewings', {
    title: 'Lịch xem', what: 'lịch xem', skeletonH: 84,
    load: function () { return API.viewings(); },
    count: function (d) { var n = (d.viewings || []).length; return n ? n + ' lịch' : ''; },
    empty: UI.emptyState('calendar', 'Chưa có lịch xem sắp tới', 'Đặt lịch từ thẻ căn hoặc từ trang chi tiết căn.',
      '<a class="add add--quiet" href="/v2/listings" data-go="/listings">Mở danh sách căn</a>'),
    render: function (data) {
      return (data.viewings || []).map(function (v) {
        var st = VIEW_ST[v.status] || [v.status || '', ''];
        var n = (v.listing_ids || []).length;
        var inner = '<div class="row-card__top"><h2 class="row-card__name">' + esc(v.client_name || 'Khách') + '</h2><span class="pill ' + st[1] + '">' + esc(st[0]) + '</span></div>' +
          '<p class="row-card__sub">' + I.calendar(13, ' style="vertical-align:-2px;margin-right:4px"') + esc(UI.fmtDateTime(v.scheduled_at)) + (n ? ' · ' + n + ' căn' : '') + '</p>' +
          (v.notes ? '<p class="row-card__sub">' + esc(v.notes) + '</p>' : '');
        return v.client_id
          ? '<a class="card row-card" href="/v2/clients/' + esc(encodeURIComponent(v.client_id)) + '" data-go="/clients/' + esc(encodeURIComponent(v.client_id)) + '">' + inner + '</a>'
          : '<article class="card row-card">' + inner + '</article>';
      }).join('');
    }
  });

  /* ---------- Hoa hồng ---------- */
  function dealCard(d) {
    var sub = [UI.fmtDate(d.closed_at), d.notes].filter(Boolean).join(' · ');
    return '<article class="card row-card"><div class="row-card__top"><h3 class="row-card__name">' + esc(d.client_name || 'Giao dịch') + '</h3>' +
      '<span class="pill ' + (d.paid ? 'pill--good' : 'pill--warn') + '">' + UI.fmtMoney(d.commission_vnd) + '</span></div>' +
      (sub ? '<p class="row-card__sub">' + esc(sub) + '</p>' : '') + '</article>';
  }
  listPage('/deals', {
    title: 'Hoa hồng', what: 'hoa hồng', skeletonH: 84,
    load: function () { return API.deals(); },
    count: function (d) { return UI.fmtMoney(d.month_total); },
    render: function (data) {
      var closed = data.closed || [], pending = data.negotiating || [];
      var m = String(data.month || '').split('-');
      var label = m.length === 2 ? 'Hoa hồng đã nhận tháng ' + m[1] + '/' + m[0] : 'Hoa hồng đã nhận tháng này';
      var h = '<div class="card sum-card"><p class="sum-card__label">' + esc(label) + '</p><p class="sum-card__value">' + UI.fmtMoney(data.month_total) + '</p></div>';
      if (!closed.length && !pending.length) return h + UI.emptyState('wallet', 'Chưa có giao dịch trong tháng', 'Giao dịch được ghi nhận qua bot sẽ hiện ở đây.');
      if (closed.length) h += '<h2 class="section-label">Đã thanh toán (' + closed.length + ')</h2>' + closed.map(dealCard).join('');
      if (pending.length) h += '<h2 class="section-label">Chưa thanh toán (' + pending.length + ')</h2>' + pending.map(dealCard).join('');
      return h;
    },
    empty: UI.emptyState('wallet', 'Chưa có giao dịch', 'Giao dịch được ghi nhận qua bot sẽ hiện ở đây.')
  });

  /* ---------- Trang đã chia sẻ ---------- */
  App.route('/shares', function (ctx) {
    ctx.el.innerHTML = '<div class="content">' + head('Trang đã chia sẻ') + '<div class="list" data-list></div></div>';
    var list = ctx.el.querySelector('[data-list]');
    list.addEventListener('click', function (e) {
      var b = e.target.closest('[data-share]'); if (!b) return;
      PF.haptic.tap();
      var url = PF.absUrl('/s/' + b.getAttribute('data-token'));
      if (b.getAttribute('data-share') === 'open') PF.openLink('/s/' + b.getAttribute('data-token'));
      else if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(function () { PF.haptic.success(); UI.toast('Đã sao chép liên kết'); }, function () { UI.toast(url); });
      else UI.toast(url);
    });
    UI.load(list, function () { return API.shares(); }, function (data) {
      return (data.shares || []).map(function (s) {
        var h = '<article class="card row-card"><div class="row-card__top"><h2 class="row-card__name">' + esc(s.title || 'Trang chia sẻ') + '</h2><span class="pill">' + (Number(s.listing_count) || 0) + ' căn</span></div>';
        h += '<p class="row-card__sub">' + (Number(s.view_count) || 0) + ' lượt xem · ' + (Number(s.booking_count) || 0) + ' lượt đặt lịch' + (s.created_at ? ' · ' + esc(UI.fmtDate(s.created_at)) : '') + '</p>';
        h += '<div class="acts acts--flat"><button type="button" class="act act--call" data-share="open" data-token="' + esc(s.token) + '">' + I.share(18) + 'Mở trang</button>' +
          '<button type="button" class="act" data-share="copy" data-token="' + esc(s.token) + '">' + I.link(18) + 'Sao chép liên kết</button></div></article>';
        return h;
      }).join('');
    }, {
      what: 'các trang đã chia sẻ', skeletonH: 110,
      empty: UI.emptyState('share', 'Chưa chia sẻ trang nào', 'Bấm Chia sẻ trên thẻ căn để tạo trang gửi cho khách.',
        '<a class="add add--quiet" href="/v2/listings" data-go="/listings">Mở danh sách căn</a>'),
      onData: function (d) { var n = (d.shares || []).length; setCount(ctx.el, n ? n + ' trang' : ''); },
      onError: function () { setCount(ctx.el, ''); }
    });
    return { buttons: function () { return {}; } };
  });

  /* ---------- Liên kết broker ---------- */
  App.route('/xbroker', function (ctx) {
    ctx.el.innerHTML = '<div class="content">' + head('Liên kết broker') + '<div class="list" data-list></div></div>';
    var list = ctx.el.querySelector('[data-list]');
    UI.load(list, function () { return API.xbroker(); }, function (data) {
      var rs = data.requests || [];
      if (!rs.length) return '';
      var h = '';
      if (data.trial && data.trial.allowed === false) h += '<p class="notice">Đã hết lượt thử tính năng này. Cần gói Max để trả lời yêu cầu.</p>';
      return h + rs.map(function (r) {
        var urgent = r.urgency === 'urgent';
        var bits = [];
        if (r.bedrooms !== null && r.bedrooms !== undefined && r.bedrooms !== '') bits.push(Number(r.bedrooms) === 0 ? 'Studio' : r.bedrooms + 'PN');
        if (r.budget_max) bits.push('đến ' + UI.fmtPrice(r.budget_max));
        if (r.district) bits.push(r.district);
        return '<article class="card row-card"><div class="row-card__top"><h2 class="row-card__name">' + esc(r.summary || bits.join(' · ') || 'Yêu cầu') + '</h2>' +
          (urgent ? '<span class="pill pill--bad">Gấp</span>' : '') + '</div>' +
          (r.summary && bits.length ? '<p class="row-card__sub">' + esc(bits.join(' · ')) + '</p>' : '') +
          '<p class="row-card__sub">' + (Number(r.response_count) || 0) + '/' + (Number(r.max_responders) || 0) + ' broker đã trả lời</p></article>';
      }).join('');
    }, {
      what: 'yêu cầu từ broker khác', skeletonH: 96,
      empty: UI.emptyState('link', 'Chưa có yêu cầu nào', 'Khi broker khác cần tìm căn, yêu cầu sẽ hiện ở đây.'),
      onData: function (d) { var n = (d.requests || []).length; setCount(ctx.el, n ? n + ' yêu cầu' : ''); },
      onError: function () { setCount(ctx.el, ''); }
    });
    return { buttons: function () { return {}; } };
  });

  /* ---------- Hồ sơ và gói dịch vụ: ba khối, mỗi khối tự có bốn trạng thái ---------- */
  var TIER = { free: 'Miễn phí', pro: 'Pro', max: 'Max' };
  App.route('/profile', function (ctx) {
    ctx.el.innerHTML = '<div class="content">' + head('Hồ sơ') +
      '<div data-b="me"></div><h2 class="section-label">Giới thiệu bạn bè</h2><div data-b="ref"></div>' +
      '<h2 class="section-label">Thông báo</h2><div data-b="prefs"></div></div>';
    var q = function (k) { return ctx.el.querySelector('[data-b=' + k + ']'); };
    UI.load(q('me'), function () { return API.profile(); }, function (p) {
      var s = p.stats || {};
      function stat(n, label) { return '<div>' + esc(n == null ? 0 : n) + '<small>' + esc(label) + '</small></div>'; }
      return '<div class="card row-card"><div class="row-card__top"><h2 class="row-card__name">' + esc(p.name || 'Môi giới') + '</h2><span class="pill">' + esc(TIER[p.tier] || p.tier || '') + '</span></div>' +
        (p.phone ? '<p class="row-card__sub">' + esc(p.phone) + '</p>' : '') +
        '<p class="row-card__sub">Điểm uy tín <b class="num">' + (p.score == null ? '—' : esc(p.score)) + '</b></p></div>' +
        '<div class="stats">' + stat(s.active_listings, 'Căn còn trống') + stat(s.rented_listings, 'Căn đã thuê') + stat(s.share_views, 'Lượt xem trang chia sẻ') + '</div>';
    }, { what: 'hồ sơ', skeletonN: 2, skeletonH: 96 });
    UI.load(q('ref'), function () { return API.referral(); }, function (r) {
      return '<div class="card row-card"><p class="row-card__sub">Đã mời ' + (Number(r.invited) || 0) + ' · đủ điều kiện ' + (Number(r.qualified) || 0) + '/' + (Number(r.needed) || 0) + '</p>' +
        (r.link ? '<div class="row-card__meta"><button type="button" class="row-card__call" data-copy="' + esc(r.link) + '">' + I.link(16) + 'Sao chép liên kết mời</button></div>' : '') + '</div>';
    }, { what: 'thông tin giới thiệu', skeletonN: 1, skeletonH: 72 });
    UI.load(q('prefs'), function () { return API.notifyPrefs(); }, function (d) {
      return '<div class="group">' + (d.prefs || []).map(function (p) {
        return '<div class="row"><span class="lb">' + esc(p.label) + '</span><span class="val">' + (p.enabled ? 'Bật' : 'Tắt') + '</span></div>';
      }).join('') + '</div>';
    }, { what: 'cài đặt thông báo', skeletonN: 1, skeletonH: 120 });
    ctx.el.addEventListener('click', function (e) {
      var b = e.target.closest('[data-copy]'); if (!b) return;
      PF.haptic.tap();
      var v = b.getAttribute('data-copy');
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(v).then(function () { PF.haptic.success(); UI.toast('Đã sao chép liên kết'); }, function () { UI.toast(v); });
      else UI.toast(v);
    });
    return { buttons: function () { return {}; } };
  });
})();
