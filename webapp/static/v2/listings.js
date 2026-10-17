/* TrueNest v2 - màn "Căn hộ": tìm kiếm, lọc, danh sách thẻ, gọi / chia sẻ / đặt lịch xem.
 * Chỉ dùng các trường mà GET /api/listings trả về (webapp/api.py, listing_summary):
 *   id, title, price_vnd, bedrooms, bedroom_label, area_m2, bathrooms, district, status, photo_count,
 *   photo_urls, has_post, created_at, quality_score, amenities, highlights.
 * Số điện thoại chủ nhà không có trong bản tóm tắt nên lấy từ GET /api/listing/<id> khi bấm Gọi.
 */
(function () {
  'use strict';
  var UI = window.TrueNestUI, API = window.TrueNestAPI, App = window.TrueNestApp, I = UI.ICON, esc = UI.esc;

  var PAGE = 100;               // server giới hạn tối đa 100 căn / lượt
  var MIN_PHOTOS = 3;           // config.MIN_PHOTOS (bot yêu cầu tối thiểu 3 ảnh)
  var STATUS_LABEL = { submitted: 'Còn trống', rented: 'Đã thuê' };
  var BED_LABEL = { studio: 'Studio', '1': '1PN', '2': '2PN', '3+': '3PN trở lên' };

  var state = { q: '', status: '', bedrooms: '', district: '', minPrice: '', maxPrice: '', pet: false };
  var items = [], total = 0, loading = false, seq = 0;
  var districts = {};           // khu vực đã gặp trong dữ liệu (giữ lại để bộ lọc không bị co lại khi đang lọc)

  var $ = function (id) { return document.getElementById(id); };
  var listEl = $('listings-list'), chipsRow = $('chips-row'), chipsEl = $('chips'), badgeEl = $('filter-badge'), filterBtn = $('filter-btn'), searchEl = $('search');

  /* ---------- trạng thái → hiển thị ---------- */
  function statusInfo(code) {
    switch (code) {
      case 'submitted': return { cls: 'open', label: 'Còn trống', quiet: false };
      case 'rented': return { cls: 'rented', label: 'Đã thuê', quiet: true };
      case 'contracted': return { cls: 'rented', label: 'Đã ký HĐ', quiet: true };
      case 'draft': case 'pending_info': return { cls: 'attn', label: 'Bổ sung', quiet: false };
      default: return { cls: 'soon', label: code || 'Chưa rõ', quiet: false };
    }
  }
  function scoreClass(s) { return s >= 80 ? 'good' : s >= 50 ? 'mid' : 'low'; }
  function amenityIcon(a) {
    var k = String(a).toLowerCase();
    if (k.indexOf('wifi') >= 0) return I.wifi(12);
    if (k.indexOf('pool') >= 0 || k.indexOf('hồ bơi') >= 0 || k.indexOf('bể bơi') >= 0) return I.waves(12);
    if (k.indexOf('gym') >= 0) return I.dumbbell(12);
    return '';
  }
  function cleanLabel(s) { return (!s || s === '—' || s === '-') ? '' : String(s); }

  function cardHtml(l) {
    var score = Math.round(Number(l.quality_score) || 0);
    var st = statusInfo(l.status);
    var photos = Number(l.photo_count) || 0;
    var firstPhoto = (l.photo_urls || [])[0] || '';

    var br = cleanLabel(l.bedroom_label);
    var title = cleanLabel(l.title) || [br, l.district].filter(Boolean).join(' ') || 'Chưa có tiêu đề';
    var price = UI.fmtPrice(l.price_vnd);
    var district = l.district && title.indexOf(l.district) < 0 ? l.district : '';
    var wc = l.bathrooms ? l.bathrooms + 'WC' : '';
    var area = l.area_m2 ? l.area_m2 + ' m²' : '';

    var amen = l.amenities || [], hl = l.highlights || [];
    var amenExtra = amen.length - 3, hlExtra = hl.length - 2;

    var warns = [];
    if (photos < MIN_PHOTOS) warns.push('Cần cập nhật ảnh');
    if (score < 50) warns.push('Tin còn thiếu thông tin');
    var attn = warns.length > 0 && !st.quiet;

    var h = '<article class="card' + (st.quiet ? ' is-quiet' : '') + (attn ? ' is-attn' : '') + '" data-id="' + esc(l.id) + '" data-title="' + esc(title) + '">';
    h += '<div class="card__main"><div class="thumb">';
    h += firstPhoto ? '<img src="' + esc(firstPhoto) + '" alt="" loading="lazy">' : I.imageThin() + '<span>Ảnh căn</span>';
    h += '<span class="score score--' + scoreClass(score) + '" aria-label="Điểm chất lượng tin ' + score + '">' + score + '</span>';
    h += '<span class="badge badge--' + st.cls + '">' + esc(st.label) + '</span></div>';

    h += '<div class="card__body"><div class="card__head"><h2 class="card__title">' + esc(title) + '</h2>';
    if (price) h += '<span class="card__price">' + esc(price) + '</span>';
    h += '</div>';
    if (district) h += '<div class="card__where">' + I.pin(12) + '<span>' + esc(district) + '</span></div>';
    if (br || wc || area) {
      h += '<div class="facts">';
      if (br) h += '<span>' + I.bed(13) + esc(br) + '</span>';
      if (wc) h += '<span>' + I.bath(13) + esc(wc) + '</span>';
      if (area) h += '<span>' + I.ruler(13) + esc(area) + '</span>';
      h += '</div>';
    }
    if (amen.length) {
      h += '<div class="amen">';
      amen.slice(0, 3).forEach(function (a) { h += '<span>' + amenityIcon(a) + esc(a) + '</span>'; });
      if (amenExtra > 0) h += '<span class="more" aria-label="Còn ' + amenExtra + ' tiện ích: ' + esc(amen.slice(3).join(', ')) + '">+' + amenExtra + '</span>';
      h += '</div>';
    }
    h += '</div></div>';

    if (warns.length) {
      h += '<div class="notes">' + warns.map(function (w) { return '<span class="warn-tag">' + I.alert(12) + esc(w) + '</span>'; }).join('') + '</div>';
    } else if (hl.length) {
      h += '<div class="notes">' + I.tag(13, ' style="color:var(--c-placeholder)"');
      h += hl.slice(0, 2).map(function (x) { return '<span class="notes__item">' + esc(x) + '</span>'; }).join('<span class="notes__sep" aria-hidden="true">·</span>');
      if (hlExtra > 0) h += '<span class="more more--lg" aria-label="Còn ' + hlExtra + ' điểm nổi bật: ' + esc(hl.slice(2).join(', ')) + '">+' + hlExtra + '</span>';
      h += '</div>';
    }

    var foot = [];
    var posted = UI.ago(l.created_at);
    if (posted) foot.push('<b>Đăng ' + esc(posted) + '</b>');
    foot.push(photos + ' ảnh');
    h += '<div class="card__foot"><div class="card__foot-text">' + I.calendar(14) + foot.join('<span class="dot">·</span>') + '</div><div class="card__actions">';
    h += '<button type="button" class="icon-btn" data-act="call" aria-label="Gọi chủ nhà ' + esc(title) + '">' + I.phone(20) + '</button>';
    h += '<button type="button" class="icon-btn" data-act="share" aria-label="Chia sẻ ' + esc(title) + '">' + I.share(20) + '</button>';
    h += '<button type="button" class="icon-btn" data-act="book" aria-label="Đặt lịch xem ' + esc(title) + '">' + I.calendarPlus(20) + '</button>';
    h += '</div></div></article>';
    return h;
  }

  /* ---------- bộ lọc ---------- */
  function activeChips() {
    var c = [];
    if (state.status) c.push({ key: 'status', label: STATUS_LABEL[state.status] || state.status });
    if (state.bedrooms) c.push({ key: 'bedrooms', label: BED_LABEL[state.bedrooms] || state.bedrooms });
    if (state.district) c.push({ key: 'district', label: state.district });
    if (state.minPrice || state.maxPrice) {
      var lo = state.minPrice, hi = state.maxPrice;
      c.push({ key: 'price', label: lo && hi ? lo + ' – ' + hi + ' tr/tháng' : lo ? 'Từ ' + lo + ' tr/tháng' : 'Đến ' + hi + ' tr/tháng' });
    }
    if (state.pet) c.push({ key: 'pet', label: 'Pet friendly' });
    return c;
  }
  function renderChips() {
    var chips = activeChips();
    chipsRow.hidden = chips.length === 0;
    chipsEl.innerHTML = chips.map(function (c) {
      return '<button type="button" class="chip" data-k="' + c.key + '" aria-label="Bỏ lọc ' + esc(c.label) + '">' + esc(c.label) + ' ' + I.close(14) + '</button>';
    }).join('');
    badgeEl.hidden = chips.length === 0;
    badgeEl.textContent = chips.length;
    filterBtn.classList.toggle('is-on', chips.length > 0);
    filterBtn.setAttribute('aria-label', chips.length ? 'Bộ lọc, ' + chips.length + ' đang chọn' : 'Bộ lọc');
  }
  function clearKey(k) {
    if (k === 'price') { state.minPrice = ''; state.maxPrice = ''; }
    else if (k === 'pet') state.pet = false;
    else state[k] = '';
  }
  chipsEl.addEventListener('click', function (e) {
    var b = e.target.closest('.chip'); if (!b) return;
    clearKey(b.getAttribute('data-k')); UI.haptic(); reload();
  });
  $('chips-clear').addEventListener('click', function () {
    state.status = state.bedrooms = state.district = state.minPrice = state.maxPrice = ''; state.pet = false; UI.haptic(); reload();
  });

  function openFilters() {
    UI.haptic();
    UI.sheet('Bộ lọc', function (body, sh) {
      var draft = { status: state.status, bedrooms: state.bedrooms, district: state.district, pet: state.pet };
      function seg(label, field, options) {
        var h = '<div class="field"><span class="field__label">' + label + '</span><div class="seg" data-f="' + field + '">';
        h += '<button type="button" data-v="" aria-pressed="false">Tất cả</button>';
        options.forEach(function (o) { h += '<button type="button" data-v="' + esc(o[0]) + '" aria-pressed="false">' + esc(o[1]) + '</button>'; });
        return h + '</div></div>';
      }
      var dOpts = Object.keys(districts).sort().map(function (d) { return [d, d]; });
      if (state.district && !districts[state.district]) dOpts.push([state.district, state.district]);
      body.innerHTML =
        seg('Tình trạng', 'status', [['submitted', 'Còn trống'], ['rented', 'Đã thuê']]) +
        seg('Phòng ngủ', 'bedrooms', [['studio', 'Studio'], ['1', '1PN'], ['2', '2PN'], ['3+', '3PN+']]) +
        (dOpts.length ? seg('Khu vực', 'district', dOpts) : '') +
        '<div class="field"><span class="field__label">Giá thuê (triệu/tháng)</span><div class="range">' +
        '<input type="number" id="f-min" inputmode="decimal" min="0" step="0.5" placeholder="Từ" aria-label="Giá từ, triệu mỗi tháng" value="' + esc(state.minPrice) + '"> – ' +
        '<input type="number" id="f-max" inputmode="decimal" min="0" step="0.5" placeholder="Đến" aria-label="Giá đến, triệu mỗi tháng" value="' + esc(state.maxPrice) + '"></div></div>' +
        '<div class="field"><span class="field__label">Khác</span><div class="seg"><button type="button" id="f-pet" aria-pressed="' + state.pet + '">Pet friendly</button></div></div>' +
        '<div class="sheet__actions"><button type="button" class="btn" id="f-reset">Xoá bộ lọc</button><button type="button" class="btn btn--primary" id="f-apply">Áp dụng</button></div>';
      function paint() {
        body.querySelectorAll('.seg[data-f]').forEach(function (g) {
          var cur = draft[g.getAttribute('data-f')];
          g.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-v') === cur)); });
        });
        body.querySelector('#f-pet').setAttribute('aria-pressed', String(draft.pet));
      }
      paint();
      body.addEventListener('click', function (e) {
        var b = e.target.closest('button'); if (!b) return;
        var g = b.closest('.seg[data-f]');
        if (g) { draft[g.getAttribute('data-f')] = b.getAttribute('data-v'); paint(); }
        else if (b.id === 'f-pet') { draft.pet = !draft.pet; paint(); }
        else if (b.id === 'f-reset') { draft = { status: '', bedrooms: '', district: '', pet: false }; body.querySelector('#f-min').value = ''; body.querySelector('#f-max').value = ''; paint(); }
        else if (b.id === 'f-apply') {
          state.status = draft.status; state.bedrooms = draft.bedrooms; state.district = draft.district; state.pet = draft.pet;
          state.minPrice = body.querySelector('#f-min').value.trim(); state.maxPrice = body.querySelector('#f-max').value.trim();
          sh.close(); reload();
        }
      });
    });
  }
  filterBtn.addEventListener('click', openFilters);

  /* ---------- tải dữ liệu ---------- */
  function params(offset) {
    return {
      q: state.q.trim(), status: state.status, bedrooms: state.bedrooms, district: state.district,
      min_price: state.minPrice ? Number(state.minPrice) * 1e6 : '', max_price: state.maxPrice ? Number(state.maxPrice) * 1e6 : '',
      pet_friendly: state.pet ? 'true' : '', limit: PAGE, offset: offset || 0
    };
  }
  function setCount() { App.setCount('listings', total + ' căn'); }

  function errorHtml(e) {
    var msg = e && e.status === 401
      ? (API.authMode() === 'none' ? 'Mở ứng dụng từ Telegram, hoặc thêm ?demo=1&broker_id=… vào địa chỉ khi thử trên máy.' : 'Phiên đăng nhập không hợp lệ. Hãy mở lại từ Telegram.')
      : 'Không tải được danh sách căn' + (e && e.message ? ' (' + esc(e.message) + ')' : '') + '.';
    return '<div class="state state--error" role="alert">' + msg + '<br><button type="button" data-retry>Thử lại</button></div>';
  }

  function render() {
    renderChips();
    if (!items.length) {
      var filtered = activeChips().length > 0 || state.q.trim();
      listEl.innerHTML = '<div class="state">' + (filtered ? 'Không có căn nào khớp. Thử bỏ bớt bộ lọc.' : 'Chưa có căn nào. Gửi tin đăng cho bot để thêm căn đầu tiên.') + '</div>';
    } else {
      listEl.innerHTML = items.map(cardHtml).join('') +
        (items.length < total ? '<button type="button" class="more-btn" data-more>Xem thêm (' + (total - items.length) + ' căn)</button>' : '');
    }
    setCount();
  }

  function absorb(data) {
    (data.items || []).forEach(function (l) { if (l.district) districts[l.district] = 1; });
  }

  function reload() {
    var my = ++seq;
    renderChips();
    listEl.innerHTML = '<div class="state" role="status">Đang tải…</div>';
    loading = true;
    return API.listings(params(0)).then(function (data) {
      if (my !== seq) return;
      items = data.items || []; total = Number(data.total); if (!isFinite(total)) total = items.length;
      absorb(data); loading = false; render();
    }, function (e) {
      if (my !== seq) return;
      loading = false; items = []; total = 0; listEl.innerHTML = errorHtml(e); App.setCount('listings', '');
    });
  }
  function loadMore() {
    if (loading) return; loading = true;
    var my = seq;
    API.listings(params(items.length)).then(function (data) {
      if (my !== seq) return;
      items = items.concat(data.items || []); absorb(data); loading = false; render();
    }, function (e) { loading = false; UI.toast(e.message || 'Không tải thêm được'); });
  }

  /* ---------- hành động trên thẻ ---------- */
  function shareLink(url, text) {
    var t = UI.tg();
    if (UI.inTelegram() && t && t.openTelegramLink) {
      t.openTelegramLink('https://t.me/share/url?url=' + encodeURIComponent(url) + '&text=' + encodeURIComponent(text));
    } else if (navigator.share) {
      navigator.share({ title: text, url: url }).catch(function () {});
    } else if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(function () { UI.toast('Đã sao chép liên kết'); }, function () { UI.toast(url); });
    } else { UI.toast(url); }
  }

  function bookSheet(id, title) {
    UI.sheet('Đặt lịch xem', function (body, sh) {
      body.innerHTML = '<p class="row-card__sub" style="margin-bottom:var(--s-3)">' + esc(title) + '</p><div class="state" role="status">Đang tải danh sách khách…</div>';
      API.clients().then(function (data) {
        var clients = data.clients || [];
        if (!clients.length) { body.innerHTML = '<p class="row-card__sub" style="margin-bottom:var(--s-3)">' + esc(title) + '</p><div class="state">Chưa có khách nào để đặt lịch.</div>'; return; }
        body.innerHTML =
          '<p class="row-card__sub" style="margin-bottom:var(--s-3)">' + esc(title) + '</p>' +
          '<div class="field"><label for="b-client">Khách</label><select id="b-client">' +
          clients.map(function (c) { return '<option value="' + esc(c.id) + '">' + esc(c.name) + '</option>'; }).join('') + '</select></div>' +
          '<div class="field"><label for="b-when">Thời gian</label><input type="datetime-local" id="b-when"></div>' +
          '<div class="field"><label for="b-note">Ghi chú</label><textarea id="b-note" rows="2"></textarea></div>' +
          '<p class="form-error" id="b-err" role="alert" hidden></p>' +
          '<div class="sheet__actions"><button type="button" class="btn" id="b-cancel">Huỷ</button><button type="button" class="btn btn--primary" id="b-ok">Đặt lịch</button></div>';
        body.querySelector('#b-cancel').addEventListener('click', sh.close);
        body.querySelector('#b-ok').addEventListener('click', function () {
          var sel = body.querySelector('#b-client'), when = body.querySelector('#b-when').value, err = body.querySelector('#b-err'), btn = this;
          var ts = when ? Math.floor(new Date(when).getTime() / 1000) : NaN;
          if (!isFinite(ts)) { err.textContent = 'Chọn thời gian xem.'; err.hidden = false; return; }
          btn.disabled = true; err.hidden = true;
          API.createViewing({
            client_id: sel.value, client_name: sel.options[sel.selectedIndex].text, listing_ids: [id],
            scheduled_at: ts, notes: body.querySelector('#b-note').value.trim()
          }).then(function () { UI.haptic('ok'); sh.close(); UI.toast('Đã đặt lịch xem'); App.invalidate('viewings'); },
            function (e) { btn.disabled = false; err.textContent = e.message || 'Không đặt được lịch.'; err.hidden = false; });
        });
      }, function (e) { body.innerHTML = '<div class="state state--error" role="alert">' + esc(e.message || 'Không tải được danh sách khách') + '</div>'; });
    });
  }

  listEl.addEventListener('click', function (e) {
    if (e.target.closest('[data-retry]')) return reload();
    if (e.target.closest('[data-more]')) return loadMore();
    var btn = e.target.closest('[data-act]'); if (!btn) return;
    var card = btn.closest('.card'), id = card.getAttribute('data-id'), title = card.getAttribute('data-title');
    UI.haptic();
    var act = btn.getAttribute('data-act');
    if (act === 'call') {
      btn.disabled = true;
      API.listing(id).then(function (d) {
        btn.disabled = false;
        if (!UI.callPhone(d.phone)) UI.toast('Căn này chưa có số chủ nhà');
      }, function (er) { btn.disabled = false; UI.toast(er.message || 'Không lấy được số chủ nhà'); });
    } else if (act === 'share') {
      btn.disabled = true;
      API.createShare({ listing_ids: [id], title: title }).then(function (r) {
        btn.disabled = false; shareLink(r.url, title);
      }, function (er) { btn.disabled = false; UI.toast(er.message || 'Không tạo được liên kết chia sẻ'); });
    } else if (act === 'book') {
      bookSheet(id, title);
    }
  });

  var timer = null;
  searchEl.addEventListener('input', function () {
    clearTimeout(timer);
    timer = setTimeout(function () { state.q = searchEl.value; reload(); }, 300);
  });
  searchEl.addEventListener('keydown', function (e) { if (e.key === 'Enter') { clearTimeout(timer); state.q = searchEl.value; reload(); searchEl.blur(); } });

  $('fab-add').addEventListener('click', function () {
    UI.haptic();
    UI.toast('Gửi tin đăng cho bot để thêm căn mới');
    var t = UI.tg();
    if (UI.inTelegram() && t && t.close) setTimeout(function () { try { t.close(); } catch (e) { /* bỏ qua */ } }, 900);
  });

  App.register('listings', { load: reload });
  App.start('listings');
})();
