# TrueNest Assistant — quy tắc cho mọi phiên làm việc

## Thiết kế giao diện: BẮT BUỘC tuân thủ nghiên cứu Telegram Mini App

Từ 17/10/2026, mọi việc thiết kế hoặc dựng giao diện (mini app trong `webapp/static/`,
trang chia sẻ cho khách, mẫu mới trong `UI/`) phải tuân thủ
`docs/research/tma-design-2026-10-17.md`. Trước khi làm, đọc mục 0, 1, 2, 3 của tài liệu đó.

Chuẩn thiết kế (chủ dự án quyết 17/10/2026): **khung như mini app BotFather, nội dung trang
làm đầy đủ.**
- **Khung** (theo BotFather): màu nền/chữ/nút lấy từ theme Telegram của người dùng
  (`--tg-theme-*`, có dự phòng sáng/tối xanh Telegram); phông hệ thống (SF Pro / Roboto /
  Segoe UI), không phông tuỳ biến, số dùng `tabular-nums`; thanh đầu và nút gốc do Telegram vẽ;
  trang chính và Cài đặt là danh sách gom nhóm bo góc, dòng có icon + `›`; nút đặc màu nút của
  theme, nút nguy hiểm màu destructive của theme.
- **Nội dung từng trang làm đầy đủ**, không rút gọn thành danh sách cài đặt: thẻ căn có ảnh (bố
  cục theo `UI/Main.dc.html`), ô số liệu lớn, ảnh đại diện chữ cái đầu, lưới thông số có icon,
  biểu đồ, nhãn trạng thái. Đầy đủ không có nghĩa là nhồi: câu hỏi chính của mỗi màn (ví dụ
  giá + liên hệ của căn) phải trả lời được trên khung nhìn đầu tiên, không cần cuộn, và mỗi màn
  vẫn chỉ một hành động chính.
- **Màu ngoài theme** chỉ có hai bộ cố định, mỗi màu có biến thể sáng-tối: bộ nhỏ màu trạng
  thái (còn trống, đã thuê, gấp...) và **bộ 6 màu nhấn** kiểu trang Cài đặt Telegram (xanh dương,
  cam, tím, đỏ, xanh lá, xanh ngọc) cho icon nền màu, biểu đồ, ảnh đại diện. Không màu nào khác.
- Tệp token của v2 là nơi duy nhất ánh xạ các màu này (hiện là `webapp/static/v2/tokens-tg.css`,
  gộp về `tokens.css` khi bỏ trang cũ). `UI/Main.dc.html` chỉ dùng để tham khảo bố cục thẻ căn,
  không còn là chuẩn màu/phông.
Điều hướng theo `docs/design/navigation-2026-10-17.md` (chủ dự án duyệt 17/10/2026). Tài liệu
này thay các chỗ về tab dưới/FAB trong tài liệu nghiên cứu (mục 0 ý 4, 1.3, 2.1, 2.5).
`stitch_ui/DESIGN.md` đã lỗi thời (mâu thuẫn phông chữ với mẫu mới), không dùng làm chuẩn.

### A. Bắt buộc (có nguồn tài liệu chính thức của Telegram)
1. **Màu chỉ đi qua token** trong `tokens.css`, không viết mã hex trong giao diện. Theo
   `themeChanged` của Telegram; `setHeaderColor` / `setBackgroundColor` gọi lại mỗi khi theme đổi.
2. **Vùng an toàn và ghim đáy:** dùng `--tg-safe-area-inset-*` và `--tg-content-safe-area-inset-*`;
   phần tử ghim đáy dựa trên `viewportStableHeight`, không dựa trên `viewportHeight`.
3. **Điều hướng và nút gốc của Telegram:**
   - Cấu trúc **trang chính (hub) → trang con → trang chi tiết**, không có thanh tab dưới.
     Trang chính gồm phần "Hôm nay", vài lối tắt, và các mục dạng dòng có mũi tên `›`.
   - Màn con dùng BackButton, luôn ẩn ở trang chính. Không tự vẽ nút Quay lại/Đóng khi chạy
     trong Telegram (bỏ khỏi mã, không chỉ ẩn).
   - MainButton cho đúng **một** hành động chính của trang chi tiết/form (động từ + đối tượng).
     Trang chính và trang danh sách không dùng MainButton; nút thêm đặt trong nội dung.
   - SecondaryButton và SettingsButton phải qua `isVersionAtLeast`, thiếu thì có nút thay trong
     nội dung.
   - Không có thanh đáy tự vẽ nào (kể cả nút nổi/FAB).
   - Mọi hành động thường dùng đạt được trong **≤ 2 chạm** từ trang chính; thêm màn mới thì
     cập nhật bản đồ trang trong `docs/design/`.
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
15. **Phông hệ thống, ảnh tự lưu**, không nạp Google Fonts hay CDN nào ngoài `telegram-web-app.js`.
16. **Mỗi trang có đường dẫn URL** (`/v2/...`) và, nếu mở trực tiếp được, một mã `startapp`
    ngắn chỉ gồm chữ thường, số, gạch dưới. Router không đọc `window.Telegram`/`location` ngoài
    lớp bọc nền tảng. `start_param` chỉ để chọn màn mở; quyền kiểm ở máy chủ.

### C. Chưa có nguồn — phải thử trên máy thật trước khi dựa vào
- Công thức cộng safe-area với content-safe-area (iPhone có tai thỏ).
- Hành vi bàn phím che ô nhập trên iOS / Android / Desktop.
- `tel:` trong WebView của Telegram.
- Giới hạn độ dài của `startapp`.
- Thời hạn của PreparedInlineMessage.
- Cử chỉ vuốt cạnh để quay lại và hành vi BackButton trên iOS / Android / Desktop.
- Telegram có cấp `initData` mới khi mở lại app hay không (ảnh hưởng màn hết phiên 401).

### Cổng kiểm khi nộp một màn giao diện
- Đổi Telegram sang theme sáng rồi tối: không còn chữ nhạt trên nền sáng, thanh đầu/đáy đổi màu theo.
  Thử thêm một theme có màu nút khác xanh: app đổi theo.
- Tìm `#[0-9a-fA-F]{3,6}` trong tệp giao diện: không có kết quả nào ngoài `tokens.css`.
- Tìm `window.Telegram`, `location.search`, `fetch(`: chỉ có trong lớp bọc nền tảng và `api.js`.
- Chụp ảnh khổ 390px cả bốn trạng thái, đặt cạnh `UI/Main.dc.html`.
- Mở trong Telegram thật (ít nhất một máy iOS hoặc Android) trước khi báo xong.
- Cập nhật bản đồ trang; đếm chạm từ trang chính tới mọi hành động thường dùng: không cái nào > 2.
- Không còn thanh tab dưới hay nút nổi tự vẽ trong tệp giao diện.
- Ảnh 390px khung đầu tiên của mỗi màn: thấy được câu trả lời cho câu hỏi chính của màn mà
  không cuộn; màu ngoài theme chỉ thuộc bộ trạng thái hoặc bộ 6 màu nhấn.

## Vận hành
- Khởi động/restart: `.\start-all.ps1`. Script tự tắt bản cũ; luôn chỉ có 1 bot + 1 webapp.
- Không chạy thẳng `python bot.py` song song với bản đang chạy (bot có khoá, bản thứ hai sẽ tự thoát).
