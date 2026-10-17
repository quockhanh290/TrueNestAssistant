/* TrueNest v2 - router theo đường dẫn (/v2/...) với ngăn xếp trang.
 * - Mỗi trang là một <section> nằm trong ngăn xếp; đi tiếp thì ẩn trang dưới (giữ nguyên DOM, bộ lọc, vị trí cuộn),
 *   quay lại thì bỏ trang trên cùng và hiện lại trang dưới đúng như lúc rời đi.
 * - BackButton của Telegram (qua platform.js) luôn quay về trang vừa đứng; ẩn ở trang chính.
 * - Mở thẳng /v2/listings/<id>: ngăn xếp chỉ có 1 trang nhưng Back vẫn hiện và đưa về trang chính.
 * - Không đọc đối tượng nền tảng hay địa chỉ trang: mọi thứ đi qua TrueNestPlatform.
 *
 * Giao thức trang: App.route(mẫu, (ctx) => page). ctx = { el, path, params, App }.
 * Hàm tạo trang tự vẽ vào ctx.el và trả về { buttons?(): {main?, secondary?}, onShow?(), onHide? } (đều tuỳ chọn).
 */
(function (root) {
  'use strict';
  var doc = root.document, PF = root.TrueNestPlatform;
  var routes = [], stack = [], host = null;

  function compile(pattern) {
    var keys = [];
    var re = new RegExp('^' + pattern.replace(/:([a-z]+)/g, function (_, k) { keys.push(k); return '([^/]+)'; }) + '$');
    return { re: re, keys: keys };
  }
  function match(path) {
    for (var i = 0; i < routes.length; i++) {
      var m = routes[i].c.re.exec(path);
      if (m) {
        var params = {};
        routes[i].c.keys.forEach(function (k, j) { try { params[k] = decodeURIComponent(m[j + 1]); } catch (e) { params[k] = m[j + 1]; } });
        return { route: routes[i], params: params };
      }
    }
    return null;
  }

  function top() { return stack[stack.length - 1]; }

  function mount(path) {
    var m = match(path) || { route: routes.notFound, params: {} };
    var el = doc.createElement('section');
    el.className = 'view';
    el.setAttribute('data-path', path);
    host.appendChild(el);
    var entry = { path: path, el: el, page: null, scrollY: 0 };
    entry.page = m.route.factory({ el: el, path: path, params: m.params, App: App }) || {};
    return entry;
  }

  /* ---------- nút thay trong nội dung khi không có nút gốc của Telegram ---------- */
  function paintFallback(entry, native, spec) {
    Array.prototype.slice.call(entry.el.querySelectorAll('[data-chrome]')).forEach(function (n) { n.parentNode.removeChild(n); });
    var isHub = entry.path === '/';
    var needBack = !isHub || stack.length > 1;
    if (needBack && !PF.hasNativeBack()) {
      var crumb = doc.createElement('button');
      crumb.type = 'button'; crumb.className = 'crumb'; crumb.setAttribute('data-chrome', '');
      crumb.innerHTML = root.TrueNestUI.ICON.back(16) + '<span>Trang trước</span>';
      crumb.addEventListener('click', function () { App.back(); });
      entry.el.insertBefore(crumb, entry.el.firstChild);
    }
    var items = [];
    if (spec.secondary && !native.secondary) items.push(['secondary', spec.secondary]);
    if (spec.main && !native.main) items.push(['main', spec.main]);
    if (items.length) {
      var bar = doc.createElement('div');
      bar.className = 'actionbar'; bar.setAttribute('data-chrome', '');
      items.forEach(function (it) {
        var b = doc.createElement('button');
        b.type = 'button'; b.className = 'btn' + (it[0] === 'main' ? ' btn--primary' : '');
        b.textContent = it[1].text; b.disabled = !!it[1].disabled;
        b.addEventListener('click', function () { if (!b.disabled) it[1].onClick(); });
        bar.appendChild(b);
      });
      entry.el.appendChild(bar);
    }
  }

  function chrome() {
    var e = top(); if (!e) return;
    var hub = e.path === '/' && stack.length === 1;
    PF.setBack(hub ? null : function () { App.back(); });
    var spec = (e.page && e.page.buttons && e.page.buttons()) || {};
    var native = PF.setButtons(spec);
    paintFallback(e, native, spec);
  }

  function show() {
    var e = top();
    stack.forEach(function (s) { s.el.hidden = s !== e; });
    chrome();
    root.scrollTo(0, e.scrollY || 0);
    if (e.page && e.page.onShow) e.page.onShow();
  }

  function leave() {
    var e = top(); if (!e) return;
    e.scrollY = root.pageYOffset || 0;
    if (e.page && e.page.onHide) e.page.onHide();
  }

  function drop(entry) {
    if (entry.page && entry.page.destroy) entry.page.destroy();
    if (entry.el.parentNode) entry.el.parentNode.removeChild(entry.el);
  }

  var App = root.TrueNestApp = {
    route: function (pattern, factory) { routes.push({ c: compile(pattern), factory: factory }); },
    notFound: function (factory) { routes.notFound = { factory: factory }; },

    /** Đi tới trang con (thêm vào ngăn xếp). */
    go: function (path) {
      if (top() && top().path === path) return;
      leave();
      PF.push(path, { i: stack.length });
      stack.push(mount(path));
      show();
    },
    /** Quay lại trang vừa đứng; nếu đang ở trang mở thẳng (ngăn xếp 1 trang) thì về trang chính. */
    back: function () {
      if (stack.length > 1) { PF.historyBack(); return; }
      if (top().path === '/') return;
      leave();
      var old = stack.pop(); drop(old);
      PF.replace('/', { i: 0 });
      stack.push(mount('/'));
      show();
    },
    /** Vẽ lại các nút gốc / nút thay thế của trang đang hiện (gọi khi trạng thái trang đổi, ví dụ đã chọn căn). */
    refreshChrome: chrome,
    current: function () { return top() ? top().path : ''; },

    /** Mở app: đọc đường dẫn hiện tại (hoặc start_param ở trang chính) rồi dựng trang đầu. */
    start: function (hostEl) {
      host = hostEl;
      var path = PF.path();
      if (path === '/') {
        var mapped = fromStartParam(PF.startParam());
        if (mapped) { path = mapped; }
      }
      PF.replace(path, { i: 0 });
      stack.push(mount(path));
      show();
      PF.setSettings(function () { PF.haptic.tap(); App.go('/profile'); });
      PF.onPop(function (st) {
        var i = st && typeof st.i === 'number' ? st.i : 0;
        if (i < stack.length - 1) {
          leave();
          while (stack.length - 1 > i) drop(stack.pop());
          show();
        } else if (i > stack.length - 1) {
          leave();
          stack.push(mount(PF.path()));
          show();
        }
      });
      host.addEventListener('click', function (ev) {
        var a = ev.target.closest && ev.target.closest('[data-go]');
        if (!a || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button) return;
        ev.preventDefault();
        PF.haptic.select();
        App.go(a.getAttribute('data-go'));
      });
    }
  };

  /** start_param -> đường dẫn. Chỉ chọn màn; quyền sở hữu căn/khách vẫn do máy chủ kiểm. */
  function fromStartParam(p) {
    if (!p) return '';
    var map = { h: '/', l: '/listings', c: '/clients', v: '/viewings', d: '/deals', s: '/shares', x: '/xbroker', p: '/profile',
      new_l: '/listings/new', new_c: '/clients/new', new_v: '/viewings/new' };
    if (map.hasOwnProperty(p)) return map[p] === '/' ? '' : map[p];
    var m = /^(l|c|x)_([A-Za-z0-9_-]{1,64})$/.exec(p);
    if (m) {
      var id = m[2];
      if (m[1] === 'l' && /^[0-9a-f]{12}$/.test(id)) id = 'tg:' + id;   // mã căn là "tg:" + 12 ký tự hex; ':' không dùng được trong startapp
      return { l: '/listings/', c: '/clients/', x: '/xbroker/' }[m[1]] + id;
    }
    return '';
  }
})(window);
