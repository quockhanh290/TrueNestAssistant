/* TrueNest v2 - trang tĩnh và trang "chưa có trên mini app": Công cụ, Hướng dẫn, Thêm căn/khách, Đặt lịch xem, không tìm thấy.
 * Các trang này chưa có API (xem docs/design/navigation-2026-10-17.md mục 2 và 10, W11); nói thẳng điều đó thay vì giả vờ có form.
 */
(function () {
  'use strict';
  var UI = window.TrueNestUI, App = window.TrueNestApp, PF = window.TrueNestPlatform, I = UI.ICON, esc = UI.esc;

  function head(title) { return '<header class="page-head"><h1>' + esc(title) + '</h1></header>'; }
  function info(ctx, title, icon, heading, text, actions) {
    ctx.el.innerHTML = '<div class="content">' + head(title) + '<div class="msg msg--page">' + I[icon](40) + '<h2>' + esc(heading) + '</h2><p>' + esc(text) + '</p>' + (actions || '') + '</div></div>';
    ctx.el.addEventListener('click', function (e) {
      if (e.target.closest('[data-close]')) { PF.haptic.tap(); PF.close(); }
    });
    return { buttons: function () { return {}; } };
  }
  var closeBtn = function () { return PF.inTelegram() ? '<button type="button" class="add" data-close>Đóng và mở chat với bot</button>' : ''; };

  App.route('/listings/new', function (ctx) {
    return info(ctx, 'Thêm căn', 'plus', 'Thêm căn bằng cách gửi tin cho bot',
      'Gửi nội dung tin đăng và ảnh cho bot, bot sẽ tạo căn và báo phần còn thiếu. Nhập trực tiếp trong ứng dụng này đang được dựng.', closeBtn());
  });
  App.route('/clients/new', function (ctx) {
    return info(ctx, 'Thêm khách', 'userPlus', 'Thêm khách bằng cách gửi yêu cầu cho bot',
      'Gửi yêu cầu của khách (số phòng, ngân sách, khu vực) cho bot. Form thêm khách trong ứng dụng này đang được dựng.', closeBtn());
  });
  App.route('/viewings/new', function (ctx) {
    return info(ctx, 'Đặt lịch xem', 'calendarPlus', 'Đặt lịch từ căn cần xem',
      'Mở danh sách căn, bấm Đặt lịch trên thẻ căn rồi chọn khách và giờ xem.',
      '<a class="add" href="/v2/listings" data-go="/listings">Mở danh sách căn</a>');
  });

  App.route('/tools', function (ctx) {
    ctx.el.innerHTML = '<div class="content">' + head('Công cụ') +
      '<div class="group"><div class="row row--info"><span class="ic">' + I.doc(22) + '</span><span class="lb">Mẫu tin nhắn<small>Dùng trong bot: mở menu bot, chọn Mẫu tin nhắn.</small></span></div>' +
      '<div class="row row--info"><span class="ic">' + I.image(22) + '</span><span class="lb">Bộ marketing<small>Đang được dựng cho ứng dụng này.</small></span></div></div></div>';
    return { buttons: function () { return {}; } };
  });

  App.route('/help', function (ctx) {
    ctx.el.innerHTML = '<div class="content">' + head('Hướng dẫn') +
      '<div class="group group--pad"><ol class="steps">' +
      '<li><b>Thêm căn.</b> Gửi tin đăng và ảnh cho bot; bot tách thông tin và báo phần còn thiếu.</li>' +
      '<li><b>Gửi cho khách.</b> Mở căn, bấm Gửi cho khách để tạo trang xem riêng rồi chọn người nhận trong Telegram.</li>' +
      '<li><b>Đặt lịch xem.</b> Bấm Đặt lịch trên thẻ căn, chọn khách và giờ. Lịch hôm nay hiện ngay ở trang chính.</li>' +
      '<li><b>Giữ tin mới.</b> Căn quá 7 ngày chưa xác nhận còn trống sẽ được nhắc ở trang chính.</li></ol></div></div>';
    return { buttons: function () { return {}; } };
  });

  App.notFound(function (ctx) {
    return info(ctx, 'Không tìm thấy', 'alert', 'Không tìm thấy trang này', 'Đường dẫn không đúng hoặc trang đã đổi chỗ.',
      '<a class="add" href="/v2/" data-go="/">Về trang chính</a>');
  });
})();
