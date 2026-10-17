# TrueNest Assistant — quy tắc cho mọi phiên làm việc

## Thiết kế giao diện: BẮT BUỘC tuân thủ nghiên cứu Telegram Mini App

Từ 17/10/2026, mọi việc thiết kế hoặc dựng giao diện (mini app trong `webapp/static/`,
trang chia sẻ cho khách, mẫu mới trong `UI/`) phải tuân thủ
`docs/research/tma-design-2026-10-17.md`. Trước khi làm, đọc mục 0, 1, 2, 3 của tài liệu đó.

Chuẩn thiết kế duy nhất: `UI/Main.dc.html` + `webapp/static/v2/tokens.css`.
`stitch_ui/DESIGN.md` đã lỗi thời (mâu thuẫn phông chữ với mẫu mới), không dùng làm chuẩn.

### A. Bắt buộc (có nguồn tài liệu chính thức của Telegram)
1. **Màu chỉ đi qua token** trong `tokens.css`, không viết mã hex trong giao diện. Theo
   `themeChanged` của Telegram; `setHeaderColor` / `setBackgroundColor` gọi lại mỗi khi theme đổi.
2. **Vùng an toàn và ghim đáy:** dùng `--tg-safe-area-inset-*` và `--tg-content-safe-area-inset-*`;
   phần tử ghim đáy dựa trên `viewportStableHeight`, không dựa trên `viewportHeight`.
3. **Nút gốc của Telegram:** màn con dùng BackButton; không tự vẽ nút Quay lại/Đóng khi chạy
   trong Telegram (bỏ khỏi mã, không chỉ ẩn). MainButton cho đúng **một** hành động chính của
   màn chi tiết/form; khi MainButton hiện thì ẩn tab dưới. Không bao giờ để ba thanh đáy
   (FAB + tab dưới + MainButton) cùng lúc.
4. **Mọi tính năng Telegram mới** phải kiểm `isVersionAtLeast` và có đường lùi.
5. **Xác thực:** gửi `initData` qua header `X-Telegram-Init-Data`; máy chủ kiểm chữ ký và
   `auth_date`. Không dùng `tg_user_id`, không tin `initDataUnsafe` hay `start_param` để phân
   quyền — quyền sở hữu luôn kiểm ở máy chủ. `?demo=1` chỉ chạy khi máy chủ bật `WEBAPP_DEV=1`.
6. **Dữ liệu nghiệp vụ** (căn, khách, deal) không lưu ở CloudStorage/DeviceStorage; chỉ lưu
   tuỳ chọn giao diện (bộ lọc, tab cuối).
7. **Không nhúng mini app trong iframe** của tên miền khác (Bot API 10.2 chặn gọi khác origin).

### B. Mặc định (ý kiến có căn cứ trong tài liệu — muốn làm khác phải ghi lý do vào commit)
8. **Kiến trúc bốn tầng:**
   - `tokens.css` giữ màu, chữ, khoảng cách.
   - `api.js` là lớp gọi API duy nhất, không đụng DOM.
   - Lớp bọc nền tảng (Telegram / trình duyệt / native) là nơi duy nhất được đọc
     `window.Telegram` và `location`.
   - Lớp giao diện không gọi `fetch` trực tiếp.

   Trang mới không được tự viết hàm `apiUrl`/`fetch` riêng.
9. **Không bật toàn màn hình** (`requestFullscreen`) cho các màn quản lý.
10. **Rung (haptics):**
    - `selectionChanged` khi đổi tab hoặc đổi lựa chọn;
    - `impactOccurred` khi chạm nút;
    - `notificationOccurred` báo kết quả thành công/lỗi.

    Gom mọi lời gọi rung vào một chỗ; ngoài Telegram thì không làm gì.
11. **Không chặn chọn chữ toàn trang.** `user-select:none` chỉ đặt cho nút, tab, icon, để môi
    giới vẫn sao chép được số điện thoại và giá.
12. **Chống thao tác nhầm:**
    - Chỉ tắt vuốt-dọc-đóng-app trong lúc bottom sheet đang mở.
    - Bật xác nhận khi đóng app nếu form có thay đổi chưa lưu.
    - Thao tác không hoàn tác được thì hỏi lại bằng `showConfirm`.
13. **Mỗi màn mới phải có đủ bốn trạng thái:** đang tải, rỗng, lỗi mạng, hết phiên (401).
14. **Chia sẻ căn cho khách:** `savePreparedInlineMessage` (máy chủ) + `shareMessage` (app),
    đích là trang công khai `/s/<token>`.
15. **Phông và ảnh tự lưu**, không nạp Google Fonts hay CDN nào ngoài `telegram-web-app.js`.

### C. Chưa có nguồn — phải thử trên máy thật trước khi dựa vào
- Công thức cộng safe-area với content-safe-area (iPhone có tai thỏ).
- Hành vi bàn phím che ô nhập trên iOS / Android / Desktop.
- `tel:` trong WebView của Telegram.
- Giới hạn độ dài của `startapp`.
- Thời hạn của PreparedInlineMessage.

### Cổng kiểm khi nộp một màn giao diện
- Đổi Telegram sang theme sáng rồi tối: không còn chữ nhạt trên nền sáng, thanh đầu/đáy đổi màu theo.
- Tìm `#[0-9a-fA-F]{3,6}` trong tệp giao diện: không có kết quả nào ngoài `tokens.css`.
- Tìm `window.Telegram`, `location.search`, `fetch(`: chỉ có trong lớp bọc nền tảng và `api.js`.
- Chụp ảnh khổ 390px cả bốn trạng thái, đặt cạnh `UI/Main.dc.html`.
- Mở trong Telegram thật (ít nhất một máy iOS hoặc Android) trước khi báo xong.

## Vận hành
- Khởi động/restart: `.\start-all.ps1`. Script tự tắt bản cũ; luôn chỉ có 1 bot + 1 webapp.
- Không chạy thẳng `python bot.py` song song với bản đang chạy (bot có khoá, bản thứ hai sẽ tự thoát).
