/* MOCK.JS - chỉ để xem mockup tĩnh (đổi theme, đổi trạng thái). Không phải code app, không gọi mạng.
 * ?theme=dark|light|tim|cam   ?state=data|loading|empty|error|401|...   ?bare=1 (ẩn thanh công cụ, dùng để chụp ảnh) */
(function () {
  var d = document.documentElement;
  var q = new URLSearchParams(location.search);
  var THEMES = [['dark', 'Tối'], ['light', 'Sáng'], ['tim', 'Tím'], ['cam', 'Cam']];
  var STATE_LABEL = { data: 'Có dữ liệu', loading: 'Đang tải', empty: 'Rỗng', error: 'Lỗi mạng', '401': 'Hết phiên 401',
    filter: 'Tờ bộ lọc', select: 'Chọn nhiều', many: 'Nhiều dòng', busy: 'Đang gửi', fielderr: 'Lỗi trường', neterr: 'Lỗi gửi',
    nf404: 'Không tìm thấy', upgrade: 'Cần nâng cấp', pending: 'Đã có yêu cầu chờ', nolang: 'Chưa có bài', saving: 'Đang lưu', saveerr: 'Lưu lỗi',
    dirty: 'Đã sửa', clean: 'Chưa sửa', tools: 'Màn con Mẫu tin', expired: 'Hết hạn', emptyf: 'Rỗng do lọc', copied: 'Đã sao chép', nopick: 'Chưa chọn gói', locked: 'Tạm khoá', noslot: 'Hết chỗ' };

  var theme = q.get('theme') || 'dark';
  if (!THEMES.some(function (t) { return t[0] === theme; })) theme = 'dark';
  var states = (document.body.getAttribute('data-states') || 'data').split(',');
  var state = q.get('state') || 'data';
  if (states.indexOf(state) < 0) state = 'data';

  function apply() {
    d.setAttribute('data-theme', theme);
    d.setAttribute('data-scheme', (theme === 'light' || theme === 'cam') ? 'light' : 'dark');
    d.setAttribute('data-state', state);
    var nodes = document.querySelectorAll('[data-v]');
    for (var i = 0; i < nodes.length; i++) {
      var on = nodes[i].getAttribute('data-v').split(' ').indexOf(state) >= 0;
      if (on) nodes[i].removeAttribute('hidden'); else nodes[i].setAttribute('hidden', '');
    }
    var bs = document.querySelectorAll('.mock-bar button');
    for (var j = 0; j < bs.length; j++) {
      var k = bs[j].getAttribute('data-k'), v = bs[j].getAttribute('data-v2');
      bs[j].setAttribute('aria-pressed', String((k === 'theme' && v === theme) || (k === 'state' && v === state)));
    }
    try {
      var u = new URL(location.href);
      u.searchParams.set('theme', theme); u.searchParams.set('state', state);
      history.replaceState(null, '', u.toString());
    } catch (e) { /* mở bằng file:// có thể không cho đổi URL: bỏ qua */ }
  }

  if (q.get('bare') === '1') d.classList.add('bare');

  var bar = document.getElementById('mockbar');
  if (bar) {
    var h = '<div class="mock-bar__row"><b>Theme</b>';
    THEMES.forEach(function (t) { h += '<button type="button" data-k="theme" data-v2="' + t[0] + '">' + t[1] + '</button>'; });
    h += '</div><div class="mock-bar__row"><b>Trạng thái</b>';
    states.forEach(function (s) { h += '<button type="button" data-k="state" data-v2="' + s + '">' + (STATE_LABEL[s] || s) + '</button>'; });
    h += '</div><div class="mock-bar__row"><a href="index.html">Danh sách 22 màn</a></div>';
    bar.innerHTML = h;
    bar.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) return;
      if (b.getAttribute('data-k') === 'theme') theme = b.getAttribute('data-v2'); else state = b.getAttribute('data-v2');
      apply();
    });
  }
  apply();
})();
