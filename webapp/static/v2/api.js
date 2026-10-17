/* TrueNest v2 - lớp gọi API duy nhất.
 * Tầng 2 trong 3 tầng. Không đụng DOM, không biết gì về giao diện; chỉ trả dữ liệu thuần.
 * Dùng được từ bất kỳ framework nào: window.TrueNestAPI.listings({...}) -> Promise<{items,total,limit,offset}>.
 *
 * Xác thực (theo đúng cách webapp/server.py đọc):
 *  - Chế độ dev: URL trang có ?demo=1&broker_id=X  -> chuyển tiếp hai tham số này cho mọi lời gọi.
 *    Server chỉ chấp nhận khi chạy với WEBAPP_DEV=1.
 *  - Trong Telegram: header X-Telegram-Init-Data = Telegram.WebApp.initData (server kiểm chữ ký).
 */
(function (root) {
  'use strict';

  function ApiError(status, code, message) {
    var e = new Error(message || code || ('HTTP ' + status));
    e.name = 'ApiError';
    e.status = status;
    e.code = code || '';
    return e;
  }

  function tgApp() {
    return (root.Telegram && root.Telegram.WebApp) || null;
  }

  function pageParams() {
    try { return new URLSearchParams(root.location.search); } catch (e) { return new URLSearchParams(); }
  }

  /** Mô tả chế độ xác thực hiện tại, để giao diện nói được vì sao bị 401. */
  function authMode() {
    var q = pageParams();
    if (q.get('demo') === '1') return 'demo';
    var tg = tgApp();
    if (tg && tg.initData) return 'telegram';
    return 'none';
  }

  function buildRequest(path, params) {
    var qs = new URLSearchParams();
    if (params) {
      Object.keys(params).forEach(function (k) {
        var v = params[k];
        if (v === undefined || v === null || v === '') return;
        qs.set(k, String(v));
      });
    }
    var headers = {};
    var q = pageParams();
    var tg = tgApp();
    if (q.get('demo') === '1') {
      qs.set('demo', '1');
      if (q.get('broker_id')) qs.set('broker_id', q.get('broker_id'));
    } else if (tg && tg.initData) {
      headers['X-Telegram-Init-Data'] = tg.initData;
    }
    var s = qs.toString();
    return { url: path + (s ? '?' + s : ''), headers: headers };
  }

  function request(method, path, params, body) {
    var r = buildRequest(path, params);
    var init = { method: method, headers: r.headers };
    if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    return fetch(r.url, init).then(function (res) {
      return res.text().then(function (txt) {
        var data = null;
        if (txt) { try { data = JSON.parse(txt); } catch (e) { data = null; } }
        if (!res.ok) {
          throw ApiError(res.status, data && data.error, data && (data.error_vi || data.error));
        }
        return data == null ? {} : data;
      });
    }, function () {
      throw ApiError(0, 'network', 'Không kết nối được máy chủ');
    });
  }

  var API = {
    ApiError: ApiError,
    authMode: authMode,

    /** GET /api/listings -> { items, total, limit, offset, filter_groups }.
     *  params: q, bedrooms ('studio'|'2'|'3+'), status, min_price, max_price, district,
     *          pet_friendly ('true'), furnishing, min_area, min_score, limit (<=100), offset */
    listings: function (params) { return request('GET', '/api/listings', params); },
    /** GET /api/listing/<id> -> bản chi tiết (có phone, available_from, address...). */
    listing: function (id) { return request('GET', '/api/listing/' + encodeURIComponent(id)); },

    /** GET /api/clients -> { clients: [...] } */
    clients: function (status) { return request('GET', '/api/clients', status ? { status: status } : null); },
    /** GET /api/viewings -> { viewings: [...] } (chỉ lịch sắp tới) */
    viewings: function () { return request('GET', '/api/viewings'); },
    /** GET /api/deals -> { month, month_total, closed: [...], negotiating: [...] } */
    deals: function (month) { return request('GET', '/api/deals', month ? { month: month } : null); },

    /** POST /api/viewings { client_id, client_name, listing_ids, scheduled_at (epoch giây), notes } */
    createViewing: function (body) { return request('POST', '/api/viewings', null, body); },
    /** POST /api/share { listing_ids, title, client_id } -> { token, url, listing_count } */
    createShare: function (body) { return request('POST', '/api/share', null, body); }
  };

  root.TrueNestAPI = API;
})(typeof window !== 'undefined' ? window : this);
