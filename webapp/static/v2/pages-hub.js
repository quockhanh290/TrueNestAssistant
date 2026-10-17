/* TrueNest v2 - trang chính (hub): "Hôm nay", ba lối tắt, các dòng mục dẫn vào trang con.
 * Dữ liệu "Hôm nay" lấy từ GET /api/today qua api2.js. Mỗi khối tự có trạng thái riêng
 * (đang tải / chưa có dữ liệu / lỗi mạng / hết phiên); khi route chưa có (404) KHÔNG bịa số.
 * Không có thanh đáy, không có nút nổi, không dùng MainButton (xem docs/design/navigation-2026-10-17.md mục 4, 5).
 */
(function () {
  'use strict';
  var UI = window.TrueNestUI, API = window.TrueNestAPI, App = window.TrueNestApp, I = UI.ICON, esc = UI.esc;

  function chev() { return '<span class="chev">' + I.chevron(18) + '</span>'; }
  function link(path, inner, cls) {
    return '<a class="row' + (cls ? ' ' + cls : '') + '" href="/v2' + path + '" data-go="' + path + '">' + inner + '</a>';
  }
  function menuRow(path, icon, label, opts) {
    opts = opts || {};
    return link(path,
      '<span class="ic">' + I[icon](22) + '</span><span class="lb">' + esc(label) + (opts.sub ? '<small>' + esc(opts.sub) + '</small>' : '') + '</span>' +
      (opts.badge ? '<span class="badge-n" aria-label="' + esc(opts.badge) + ' đang chờ">' + esc(opts.badge) + '</span>' : '') +
      (opts.val ? '<span class="val">' + esc(opts.val) + '</span>' : '') + chev());
  }

  /* ---------- "Hôm nay": từng khối ---------- */
  function sub(title, right, first) {
    return '<div class="sub' + (first ? ' sub--first' : '') + '"><span>' + esc(title) + '</span><span>' + esc(right || '') + '</span></div>';
  }
  function note(iconName, text, retry) {
    return '<div class="blk-note">' + I[iconName](18) + '<span>' + text + '</span>' + (retry ? '<button type="button" class="linkbtn" data-retry>Thử lại</button>' : '') + '</div>';
  }
  function blockState(kind, title, e) {
    var inner;
    if (kind === 'loading') inner = '<div class="skels skels--tight" role="status" aria-label="Đang tải"><div class="skel skel--row"></div><div class="skel skel--row"></div></div>';
    else if (e && e.status === 401) inner = note('lock', 'Phiên đã hết hạn. Đóng ứng dụng bằng nút X rồi mở lại từ bot.');
    else if (e && (e.status === 404)) inner = note('alert', 'Chưa có dữ liệu');
    else inner = note('alert', 'Không tải được. Kiểm tra mạng rồi thử lại.', true);
    return sub(title, '', title === 'Lịch xem') + inner;
  }

  function viewingsBlock(d) {
    var list = d.viewings || [];
    var h = sub('Lịch xem', list.length ? list.length + ' buổi' : '', true);
    if (!list.length) return h + note('calendar', 'Hôm nay chưa có buổi xem nào.');
    return h + list.map(function (v) {
      var to = v.client_id ? '/clients/' + encodeURIComponent(v.client_id) : '/viewings';
      return link(to, '<span class="t">' + esc(v.time || '') + '</span><span class="lb">' + esc(v.client_name || 'Khách') +
        (v.listing_title ? '<small>' + esc(v.listing_title) + '</small>' : '') + '</span>' + chev());
    }).join('');
  }
  function followupsBlock(d) {
    var list = d.followups || [];
    var h = sub('Khách cần theo dõi', list.length ? list.length + ' người' : '');
    if (!list.length) return h + note('users', 'Chưa có khách nào cần theo dõi.');
    return h + list.map(function (f) {
      var urgent = f.urgency === 'urgent';
      var days = Number(f.days_since_update);
      var line = urgent ? f.summary : (isFinite(days) && f.days_since_update !== null ? days + ' ngày chưa cập nhật' : f.summary);
      return link('/clients/' + encodeURIComponent(f.id), '<span class="lb">' + esc(f.name || 'Khách') + (line ? '<small>' + esc(line) + '</small>' : '') + '</span>' +
        (urgent ? '<span class="chip-urgent">Gấp</span>' : '') + chev());
    }).join('');
  }
  function staleBlock(d) {
    var s = d.stale_listings || {};
    var n = Number(s.count) || 0;
    var h = sub('Căn cần làm mới', n ? n + ' căn' : '');
    if (!n) return h + note('building', 'Không có căn nào quá hạn xác nhận.');
    return h + link('/listings', '<span class="ic ic--warn">' + I.alert(22) + '</span><span class="lb">Quá ' + esc(s.window_days || 7) + ' ngày chưa xác nhận còn trống</span>' + chev());
  }

  /* ---------- dựng trang ---------- */
  App.route('/', function (ctx) {
    var el = ctx.el;
    el.innerHTML =
      '<div class="content hub">' +
      '<h1 class="sr-only">TrueNest</h1>' +
      '<section aria-label="Hôm nay"><div class="h2">Hôm nay <small id="today-date"></small></div>' +
      '<div class="group" id="today"><div data-b="viewings"></div><div data-b="followups"></div><div data-b="stale"></div></div></section>' +
      '<div class="shortcuts">' +
      '<a class="sc" href="/v2/listings/new" data-go="/listings/new">' + I.plus(22) + 'Thêm căn</a>' +
      '<a class="sc" href="/v2/clients/new" data-go="/clients/new">' + I.userPlus(22) + 'Thêm khách</a>' +
      '<a class="sc" href="/v2/viewings/new" data-go="/viewings/new">' + I.calendarPlus(22) + 'Đặt lịch xem</a></div>' +
      '<div class="group" id="menu-main"></div>' +
      '<div class="group" id="menu-more"></div>' +
      '<div class="group" id="menu-acct"></div>' +
      '<div class="foot">@truenest_bot</div></div>';

    var blocks = { viewings: el.querySelector('[data-b=viewings]'), followups: el.querySelector('[data-b=followups]'), stale: el.querySelector('[data-b=stale]') };
    var titles = { viewings: 'Lịch xem', followups: 'Khách cần theo dõi', stale: 'Căn cần làm mới' };

    function menus(counts) {
      counts = counts || {};
      function n(v) { return (typeof v === 'number') ? String(v) : ''; }
      el.querySelector('#menu-main').innerHTML =
        menuRow('/listings', 'building', 'Căn hộ', { val: n(counts.listings) }) +
        menuRow('/clients', 'users', 'Khách', { val: n(counts.clients) }) +
        menuRow('/viewings', 'calendar', 'Lịch xem', { val: typeof counts.viewings_upcoming === 'number' ? counts.viewings_upcoming + ' sắp tới' : '' }) +
        menuRow('/deals', 'wallet', 'Hoa hồng', { val: 'tháng này' });
      el.querySelector('#menu-more').innerHTML =
        menuRow('/shares', 'share', 'Trang đã chia sẻ') +
        menuRow('/xbroker', 'link', 'Liên kết broker', { badge: counts.xbroker_pending > 0 ? String(counts.xbroker_pending) : '' }) +
        menuRow('/tools', 'wrench', 'Công cụ', { sub: 'Mẫu tin nhắn, bộ marketing' });
      el.querySelector('#menu-acct').innerHTML =
        menuRow('/profile', 'user', 'Hồ sơ và gói dịch vụ') + menuRow('/help', 'help', 'Hướng dẫn');
    }
    menus(null);   // các dòng mục luôn hiện, kể cả khi "Hôm nay" chưa tải được

    function run() {
      Object.keys(blocks).forEach(function (k) { blocks[k].innerHTML = blockState('loading', titles[k]); });
      API.today().then(function (d) {
        el.querySelector('#today-date').textContent = UI.fmtDay(d.date);
        blocks.viewings.innerHTML = viewingsBlock(d);
        blocks.followups.innerHTML = followupsBlock(d);
        blocks.stale.innerHTML = staleBlock(d);
        menus(d.counts);
      }, function (e) {
        Object.keys(blocks).forEach(function (k) { blocks[k].innerHTML = blockState('error', titles[k], e); });
      });
    }
    el.addEventListener('click', function (ev) { if (ev.target.closest('[data-retry]')) { UI.haptic(); run(); } });
    run();
    return { buttons: function () { return {}; }, onShow: function () { /* làm mới khi quay lại trang chính sau khi đổi dữ liệu */ } };
  });
})();
