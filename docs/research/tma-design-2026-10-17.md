# Nghiên cứu thiết kế Telegram Mini App TrueNest (17/10/2026)

Người viết: phiên C (nghiên cứu). Chỉ đọc code và tra nguồn, không sửa code, không commit.
Cách đọc nhãn: **[đã xác minh]** = tôi đã đọc/chạy/đo tận nơi; **[nguồn: Sx]** = có trang đã fetch (mục Nguồn ở cuối); **[chưa có nguồn]** = kinh nghiệm hoặc suy luận, chưa kiểm; **[ý kiến]** = phán đoán thiết kế của tôi, không phải sự thật đo được.
Mốc thời gian: hôm nay 17/10/2026; Bot API mới nhất tôi thấy trong changelog là 10.3 (24/08/2026) [S2].

---

## 0. Tóm tắt khuyến nghị

1. **Việc khẩn nhất không phải giao diện mà là cửa vào.** Máy chủ hiện tin `?demo=1&broker_id=X` và `?tg_user_id=X` mà không cần chữ ký. Tôi đã chạy thử máy chủ trên cổng riêng với CSDL rỗng: cả hai kiểu vượt qua bước xác thực rồi mới chết ở bước đọc bảng (không phải 401) [đã xác minh, mục 4.1]. Bất kỳ ai biết địa chỉ đều đọc/sửa được dữ liệu của bất kỳ môi giới nào. Phải đóng trước khi làm bất cứ thứ gì khác.
2. **Hướng của phiên B (tokens.css + api.js + lớp giao diện) đứng được**, nhưng thiếu tầng thứ tư: **lớp bọc nền tảng** (Telegram / trình duyệt / native). Chỗ nào còn đọc `window.Telegram` hoặc `location.search` ngoài lớp này là chỗ sau này phải viết lại.
3. **Stack khuyến nghị:** giữ 3 tầng của B + lớp bọc nền tảng; giao diện chuyển sang **Preact + Vite** (4,7 KB gzip đo được, so với 47 KB của React 18) khi bắt đầu làm các màn có trạng thái (bộ lọc, form, bottom sheet); native sau này đi **Capacitor** bọc chính bản web; **không** dùng React Native/Expo ở giai đoạn này. Đây là **[ý kiến]**, chưa có phép đo thiết bị thật; cổng kiểm ở mục 5.
4. **Giao diện trong Telegram:** dùng nút Quay lại gốc (BackButton) thay cho header tự vẽ, nút chính gốc (MainButton) cho hành động chính của màn chi tiết/form, tab dưới tự vẽ chỉ cho 4 mục cấp một. Mẫu `UI/Main.dc.html` hợp về bố cục, xung đột ở: màu cứng không theo theme, header có nút Quay lại/Đóng trùng chức năng Telegram, nút nổi (FAB) cộng tab dưới cộng MainButton là ba thanh đáy chen nhau.
5. **Chia sẻ căn cho khách** nên dùng `savePreparedInlineMessage` (máy chủ gọi) + `WebApp.shareMessage` (mini app gọi): môi giới chọn chat gốc của Telegram và gửi một thẻ căn đi với tên mình [nguồn: S1, S3]. Trang công khai `/s/<token>` đã có sẵn trong repo làm đích bấm vào cho khách.
6. **Backend:** stdlib `http.server` đủ chạy giai đoạn Telegram-only; không cần đổi chỉ vì "nhanh hơn". Đổi sang FastAPI khi chạm một trong các điều kiện ở mục 4.3 (chủ yếu: cần phiên token cho web, và cần hợp đồng API sinh tự động). Hợp đồng API nên chốt dạng OpenAPI trước khi đổi framework.
7. **Hiệu năng mở lần đầu:** máy chủ hiện không nén, không đặt Cache-Control, trả HTTP/1.0, và không có kiểu MIME cho `.woff2` [đã xác minh, mục 1.9]. Sửa mấy chỗ này rẻ hơn nhiều so với đổi framework.

---

## 1. Thực hành tốt cho Telegram Mini App hiện nay

Mọi mục dưới đây là từ trang tài liệu chính thức [S1] trừ khi ghi khác. Lưu ý: S1 tôi chỉ đọc qua bản trích của công cụ fetch (trang dài 113.140 ký tự, đã đọc hết hai đoạn). Đoạn trích chưa phải nguyên văn, nên các con số giới hạn (khóa, byte) nên đối chiếu lại nguyên văn trước khi dựa vào chúng.

### 1.1 Theme sáng/tối (themeParams)
- Telegram cấp bộ màu theo người dùng: `bg_color`, `text_color`, `hint_color`, `link_color`, `button_color`, `button_text_color`, `secondary_bg_color` (6.1); `header_bg_color`, `accent_text_color`, `section_bg_color`, `section_header_text_color`, `subtitle_text_color`, `destructive_text_color` (7.0); `section_separator_color` (7.6); `bottom_bar_bg_color` (7.10). Mỗi màu có biến CSS `--tg-theme-*`. Sự kiện `themeChanged` bắn khi người dùng đổi theme hoặc bật chế độ đêm; `colorScheme` cho biết sáng/tối và cũng có biến `--tg-color-scheme` [S1].
- `setHeaderColor`, `setBackgroundColor` (6.1) chỉ nhận mã `#RRGGBB` hoặc từ khóa `bg_color`/`secondary_bg_color` trước bản 6.9; từ 6.9 nhận màu bất kỳ. `setBottomBarColor` từ 7.10 [S1]. Gọi các hàm này **khi** `themeChanged` bắn chứ không chỉ lúc khởi động, nếu không thanh đầu/đáy lệch màu khi người dùng đổi theme giữa chừng [ý kiến, suy từ mô tả sự kiện].
- Thực trạng repo: `listings.html` gọi `setHeaderColor('#071420')` và `setBackgroundColor('#071420')` cứng lúc khởi động (dòng 19–20, 26–27), không nghe `themeChanged` [đã xác minh].

### 1.2 Viewport, toàn màn hình, vùng an toàn
- `viewportHeight` đổi liên tục khi người dùng kéo, "không đủ chính xác để ghim phần tử xuống đáy"; dùng `viewportStableHeight` (biến `--tg-viewport-stable-height`) cho phần tử ghim đáy [S1]. Tài liệu SDK bên thứ ba nói cùng ý: `height` đổi khi kéo, `stableHeight` là chiều cao ở trạng thái ổn định gần nhất [S7].
- `requestFullscreen()` / `exitFullscreen()` từ Bot API 8.0; sự kiện `fullscreenChanged`, `fullscreenFailed` (lỗi `UNSUPPORTED` hoặc `ALREADY_FULLSCREEN`) [S1].
- Hai loại vùng an toàn, đều từ 8.0: `safeAreaInset` = chỗ tránh tai thỏ/thanh hệ thống, biến `--tg-safe-area-inset-*`; `contentSafeAreaInset` = chỗ tránh **giao diện Telegram** (ví dụ nút của Telegram phủ lên khi toàn màn hình), biến `--tg-content-safe-area-inset-*` [S1; ý nghĩa hai loại cũng khớp S7].
- Thực trạng: `listings.html` luôn gọi `requestFullscreen` (ngay lúc mở và lại ở cú chạm đầu tiên, dòng 22–31) nhưng chỉ cộng `env(safe-area-inset-top)` (dòng 47) [đã xác minh]. Khi toàn màn hình, nút Telegram phủ lên đầu trang; `env()` không biết chuyện đó, chỉ biến `--tg-content-safe-area-inset-top` biết. Nên chỗ này nhiều khả năng che mất đầu trang trên máy thật [ý kiến: chưa thử trên máy; cần thử, xem cổng P4].
- `tokens.css` của B đã khai `--safe-top/bottom` bằng `max(env, tg-safe) + tg-content-safe` (dòng 129–130). Hướng đúng. Điều **chưa kiểm**: công thức này cộng hai vùng, đúng nếu Telegram báo hai vùng tách biệt chứ không gộp; tài liệu tôi đọc không nói rõ [chưa có nguồn]. Phải thử trên iPhone có tai thỏ ở chế độ toàn màn hình.
- **Gợi ý [ý kiến]:** công cụ quản lý dữ liệu không cần toàn màn hình. Toàn màn hình mất header gốc của Telegram và buộc phải tự dựng lại mọi thứ; lợi ích chỉ là thêm khoảng 50–60 px chiều dọc (con số chưa đo). Để chế độ thường, dùng BackButton gốc.

### 1.3 Nút gốc: BackButton, MainButton, SecondaryButton, SettingsButton
- **BackButton** (6.1): `show()/hide()/onClick`, mặc định ẩn. **MainButton** (đổi tên chung thành BottomButton ở 7.10): `setText/show/hide/enable/disable/showProgress`, có `hasShineEffect` (7.10), `iconCustomEmojiId` (9.5). Khi mở từ menu đính kèm, nút ẩn tới khi người dùng chạm vào app. **SecondaryButton** (7.10): cùng dạng, `position` là `left/right/top/bottom`, chỉ có hiệu lực khi cả hai nút cùng hiện. **SettingsButton** (7.0): thêm mục "Settings" vào menu ngữ cảnh [S1].
- Quy ước đề xuất [ý kiến]: BackButton hiện ở mọi màn con, ẩn ở màn gốc của từng tab. MainButton chỉ có trên màn chi tiết/form (Lưu, Gửi cho khách, Đặt lịch xem), ẩn ở màn danh sách. SettingsButton cho "Cài đặt thông báo / hồ sơ" thay vì tab thứ năm.
- Phải có đường lùi khi chạy ngoài Telegram (web): lớp bọc nền tảng cung cấp nút Quay lại tự vẽ chỉ khi không phải Telegram (xem mục 3).

### 1.4 Haptics
`impactOccurred(light|medium|heavy|rigid|soft)`, `notificationOccurred(error|success|warning)`, `selectionChanged()` (chỉ khi lựa chọn đổi, không phải khi xác nhận) — từ 6.1 [S1]. `tabs.js` đang rung `light` mỗi lần đổi tab (dòng 23); theo mô tả của Telegram, đổi tab nên là `selectionChanged`, còn `impactOccurred` dành cho chạm nút [ý kiến, dựa trên mô tả hàm]. Gom mọi lời gọi vào một chỗ để ngoài Telegram thành hàm rỗng.

### 1.5 Lưu trữ
| Loại | Từ bản | Giới hạn | Dùng cho TrueNest |
|---|---|---|---|
| CloudStorage | 6.9 | 1024 khóa/người/bot; khóa 1–128 ký tự `A-Za-z0-9_-`; giá trị tối đa 4096 ký tự | Bộ lọc đã lưu, tab cuối cùng, nháp ghi chú nhỏ. Đồng bộ giữa các thiết bị của cùng môi giới |
| DeviceStorage | 9.0 | 5 MB/người/bot, cục bộ máy | Bộ nhớ đệm danh sách để mở nhanh lần sau |
| SecureStorage | 9.0 | 10 mục/người/bot, dùng Keychain (iOS)/Keystore (Android); có `restoreItem` hỏi quyền người dùng | Chỉ cần khi có token phiên (giai đoạn web/native) |
[S1]. Dữ liệu nghiệp vụ (căn, khách, deal) **không** để ở đây; nguồn thật là máy chủ. Mọi chỗ dùng phải kiểm `isVersionAtLeast`, và rơi về `localStorage` khi bản cũ — script chính thức mặc định `webAppVersion = '6.0'` khi không có tham số phiên bản [đã xác minh, S4], nghĩa là client cũ/không rõ sẽ tưởng là 6.0.

### 1.6 Xác thực initData phía máy chủ
- Cách chuẩn: máy chủ nhận nguyên chuỗi `Telegram.WebApp.initData`, tính `secret = HMAC_SHA256(key="WebAppData", msg=bot_token)`, dựng chuỗi kiểm từ mọi trường trừ `hash` (sắp theo khóa, `key=value`, nối bằng xuống dòng), so `HMAC_SHA256(secret, chuỗi)` dạng hex với `hash`, **và kiểm `auth_date` để loại dữ liệu cũ**. `initDataUnsafe` chỉ để hiển thị [S1].
- Chuẩn Ed25519 cho bên thứ ba: bên đó chỉ cần `bot_id`, không cần token; chuỗi kiểm bắt đầu bằng `bot_id:WebAppData\n`, loại cả `hash` lẫn `signature`; chữ ký base64url; có hai khóa công khai (test và production) [S1]. TrueNest tự giữ token bot nên **không cần** Ed25519 hôm nay; chỉ cần nếu sau này một dịch vụ khác (không được biết token) muốn xác minh người dùng. Thư viện chuẩn Python không có Ed25519 — cần gói ngoài [chưa có nguồn, kiến thức chung].
- Thực trạng `validate_init_data` (server.py dòng 45–67): đúng phần HMAC, so sánh bằng `compare_digest`; **không đọc `auth_date`** nên một chuỗi initData bị lộ có hiệu lực mãi mãi [đã xác minh].
- Cập nhật mới: Bot API 10.1 (11/06/2026) thêm trường `chat_join_request_query_id` vào `WebAppInitData` [S1]; không ảnh hưởng ta, nhưng chứng tỏ trường mới sẽ còn xuất hiện: **đừng viết phép kiểm theo danh sách trường cố định**, cứ lấy mọi trường trừ `hash` (code hiện tại đã làm đúng).
- Cập nhật bảo mật 10.2 (14/07/2026): lời gọi phương thức Mini App từ **origin khác** với origin gốc của app bị chặn, tự bật cho mọi Mini App từ 20/07/2026 (có thể tắt qua BotFather) [S2, chỉ qua bản tóm tắt của công cụ fetch; nên đọc nguyên văn]. Hệ quả cho ta: không nhúng Mini App trong iframe của trang khác, không chạy `Telegram.WebApp.*` từ tên miền khác với tên miền đã đăng ký với bot. Điều này cũng là một lý do để trang web/PWA sau này là một ứng dụng riêng, dùng lớp bọc nền tảng chứ không nhúng.

### 1.7 Deep link `startapp`
- `https://t.me/<bot>?startapp=<chuỗi>` mở Mini App chính; chuỗi đến app dưới dạng `start_param` (và tham số GET `tgWebAppStartParam`). `https://t.me/<bot>/<tên_app>?startapp=...` là link trực tiếp; mặc định mở full chiều cao từ 7.6; `mode=compact` mở nửa chiều cao [S1]. Nên dùng để mở thẳng một căn: `startapp=l_<id>` (định dạng do ta đặt). Giới hạn độ dài/ký tự của `startapp` **tôi chưa đọc** [chưa có nguồn]; giữ chuỗi ngắn, chỉ ký tự an toàn.
- Mọi `start_param` là dữ liệu do người ngoài gửi: kiểm quyền sở hữu căn ở máy chủ, không tin tham số.

### 1.8 Chia sẻ căn cho khách (quan trọng nhất với môi giới)
Ba đường, từ phù hợp nhất:
1. **`savePreparedInlineMessage` (máy chủ) + `WebApp.shareMessage(msg_id)` (app)** [S1, S3]. Máy chủ gọi Bot API `savePreparedInlineMessage(user_id, result, allow_user_chats, allow_bot_chats, allow_group_chats, allow_channel_chats)` với `result` là một InlineQueryResult (thẻ ảnh/tiêu đề/nút mở link); nhận về `PreparedInlineMessage`. App gọi `shareMessage(msg_id, callback)`, Telegram mở hộp chọn chat gốc; có sự kiện `shareMessageSent` / `shareMessageFailed` (lý do gồm tin hết hạn, gửi lỗi, người dùng từ chối). Yêu cầu client từ 8.0 [S1]. **Thời hạn:** kết quả có trường ngày hết hạn [S13 — chỉ thấy qua kết quả tìm kiếm, chưa fetch trang]; con số bao lâu thì **chưa có nguồn**. Cách xử lý: tạo tin ngay trước khi bấm chia sẻ, không lưu sẵn.
2. **`switchInlineQuery(query, [loại chat])`** (6.7): chèn `@bot <query>` vào ô nhập của chat [S1]. Cần bật chế độ inline cho bot và viết trình xử lý inline. Điều kiện app nào được gọi hàm này tôi **chưa xác minh** (bản trích có câu "Inline Mini Apps cannot read or send messages directly" mà tôi chưa hiểu hết phạm vi) [chưa chắc, cần thử].
3. **Chia sẻ link công khai** `/s/<token>` đã có (`api.create_share` trả `{token, url}`; trang `share.render_share_page` không cần đăng nhập) [đã xác minh, server.py dòng 155–162, 329–336]. Link này vẫn là đích mà thẻ ở đường 1 trỏ tới, và là cách duy nhất cho khách chưa dùng Telegram. Mở hộp chia sẻ bằng `t.me/share/url` hay không: **chưa có nguồn** tôi đã đọc.
- Cũng có `shareToStory` (7.8) và `requestChat` (9.6) [S1], chưa cần.

### 1.9 Hiệu năng mở lần đầu
Số đo tôi có (đo hôm nay, trên máy tôi):
| Thành phần | Kích thước thô | Gzip |
|---|---|---|
| `telegram-web-app.js` (tải từ telegram.org) | 119.731 B | 19.087 B |
| `listings.html` (bản chạy) | 22.632 B | 5.841 B |
| Phông tự lưu của B (`v2/fonts/`) | 189.956 B (không nén thêm: woff2) | — |
[đã xác minh, S4 và đo trên repo].
- Tài liệu bảo đặt script trong `<head>` trước các script khác [S1]; đây là script chặn hiển thị, ta không thay được. `ready()` "nên gọi sớm nhất khi các thành phần giao diện thiết yếu đã tải" [S1] — gọi sau khi vẽ khung xương (skeleton), không phải ở đầu `<head>` như code hiện tại (dòng 18).
- `listings.html` dòng 63 còn nạp phông từ Google Fonts lúc chạy, thêm một lượt tìm DNS/kết nối sang tên miền thứ ba trước khi vẽ chữ; `fonts.css` tự lưu của B giải quyết việc này — **hướng B đúng**, nhớ gỡ dòng Google Fonts khi chuyển [đã xác minh].
- Phía máy chủ [đã xác minh bằng cách chạy server và `curl -D -`]: phản hồi là `HTTP/1.0` (không giữ kết nối), `Content-Length: 22632` (tức không nén), **không có `Cache-Control`/`ETag`**; `MIME` trong `server.py` (dòng 34–42) không có `.woff2`, `.webp`, `.map`, `.ico` nên phông và ảnh bị trả `application/octet-stream`. Mỗi lần mở, trang và phông tải lại từ đầu.
- Đề xuất [ý kiến]: (a) đặt một reverse proxy (Caddy/nginx/Cloudflare) phía trước lo TLS, nén, HTTP/2, cache tĩnh; hiện chưa biết bản chạy thật được phơi ra thế nào [chưa biết]. (b) Tệp tĩnh có băm tên (`app.3f2a.js`) + `Cache-Control: immutable`. (c) Lưu danh sách lần trước vào DeviceStorage/localStorage, vẽ ngay rồi cập nhật ("stale-while-revalidate"). (d) Gọi API ngay khi tải script, song song với việc chờ DOM.
- Con số mục tiêu (ví dụ "danh sách đầu tiên hiện ≤ 1,5 s trên Android tầm trung, 4G") là **đề xuất của tôi**, không phải chuẩn của Telegram.

### 1.10 Những bẫy hay gặp
- **Vuốt dọc đóng app:** `disableVerticalSwipes()` từ 7.7; tài liệu khuyên **bật** trừ khi trùng cử chỉ của app, và nói ngay cả khi tắt, người dùng vẫn có thể thu nhỏ/đóng bằng cách vuốt ở header [S1]. `listings.html` tắt toàn cục (dòng 33). Gợi ý [ý kiến]: chỉ tắt trong lúc bottom sheet đang mở/đang kéo; thêm `enableClosingConfirmation()` (6.2) khi form có thay đổi chưa lưu.
- **Bàn phím che ô nhập / thanh ghim đáy nhảy:** tài liệu chỉ nói `viewportHeight` không dùng để ghim đáy, dùng `viewportStableHeight` [S1]. Hành vi cụ thể khác nhau giữa iOS, Android, Desktop **chưa có nguồn xác nhận**: một bài blog bên thứ ba nói ba nền tảng khác nhau về lưu trữ, bàn phím, cử chỉ nhưng không mô tả chi tiết [S13, chưa fetch]. Cần thử trên máy thật (cổng P4).
- **Phiên bản:** không có API nào từ 8.0/9.0 đảm bảo có trên client của môi giới (tôi không biết họ dùng bản Telegram nào) [chưa biết]. Mọi tính năng mới đều `isVersionAtLeast` rồi mới dùng, có đường lùi.
- **Chặn chọn văn bản:** `listings.html` đặt `user-select:none` cho cả `body` (dòng 37) — môi giới không sao chép được số điện thoại, địa chỉ [đã xác minh]. Chỉ nên tắt trên nút/tab, không phải toàn trang.
- **`maximum-scale=1, user-scalable=no`** (dòng 5): chặn phóng to, bất lợi cho người đọc chữ nhỏ ngoài nắng; nhiều trình duyệt iOS tự bỏ qua [chưa có nguồn]. Ghi nhận, chưa nhất thiết đổi.
- **Telegram Desktop / Web:** chạy thử cả ba (iOS, Android, Desktop). Tài liệu có mục gỡ lỗi riêng cho từng nền tảng và môi trường test với đường dẫn `/test/` [S1].

---

## 2. Mẫu UX cho công cụ quản lý nhỏ trong Telegram và đối chiếu với `UI/Main.dc.html`

Lưu ý trung thực: phần mẫu UX dưới đây là **[ý kiến]**, tôi không đọc được tài liệu thiết kế chính thức nào của Telegram về điều hướng (chỉ có mô tả API). Mẫu chỉ dùng để chọn, chưa phải chuẩn.

### 2.1 Tab dưới hay nút gốc?
- BackButton/MainButton/SecondaryButton/SettingsButton là **nút theo ngữ cảnh**, mỗi loại một chỗ [S1]. Chúng không thay được thanh tab 4 mục ngang hàng (Căn hộ / Khách / Lịch xem / Hoa hồng).
- Cách chia: tab dưới tự vẽ cho **4 đích cấp một**; BackButton cho ngăn xếp màn con; MainButton cho **một** hành động chính của màn đang mở và khi MainButton hiện thì **ẩn tab dưới** (không để hai thanh đáy chồng nhau); SecondaryButton cho hành động phụ ("Lưu nháp", "Hủy").
- FAB "Thêm căn" (mẫu: 56 px, `bottom: 80px`) trùng ý với MainButton "Thêm căn". Ở màn danh sách hãy chọn FAB (vì tab dưới đang hiện, MainButton không dùng); ở màn form dùng MainButton "Lưu". Đừng dùng cả hai cùng lúc.

### 2.2 Danh sách dày dữ liệu
Mẫu thẻ (ảnh 128 px, giá, quận, 2PN/2WC/78 m², tiện ích, nhãn, chân thẻ có Gọi / Chia sẻ / Đặt lịch xem) là mật độ tốt cho môi giới: mỗi thẻ có hành động nhanh ngay tại chỗ. Gợi ý:
- Thẻ cao khoảng 190–200 px (đọc từ mẫu) cho 3 thẻ/màn; kiểm lại sau khi đo trên máy 360×640 [chưa đo].
- Dùng danh sách ảo/phân trang khi >100 căn (API đã có `limit ≤ 100`, `offset`) [đã xác minh, server.py dòng 223].
- Vùng chạm 44 px đã đúng trong mẫu (nút 44×44) — giữ nguyên.
- Chữ cực nhỏ (10–11 px) cho nhãn trạng thái/tiện ích: đọc ngoài nắng khó [ý kiến]; mẫu `DESIGN.md` cũng nhắc "điều kiện ánh sáng ngoài trời" [đã xác minh, stitch_ui/DESIGN.md dòng 15].

### 2.3 Bộ lọc dạng bottom sheet
- Mẫu có ô tìm, nút lọc kèm huy hiệu "3 đang chọn", hàng chip có "Xoá tất cả" — mẫu hay. **Nhưng tệp mẫu không vẽ chính cái sheet** (tôi không thấy phần tử `dialog` nào trong mẫu) [đã xác minh bằng tìm kiếm trong tệp]; phải thiết kế thêm.
- Sheet cần: kéo xuống để đóng **nhưng** phải tắt vuốt-dọc-đóng-app trong lúc mở (mục 1.10); nút "Áp dụng (N căn)" dạng MainButton gốc là lựa chọn, nhưng với sheet tự vẽ thì nút trong sheet đỡ rối hơn [ý kiến]; trường nhập số (giá) dùng `inputmode="numeric"`; bàn phím mở thì sheet phải co theo `viewportStableHeight`/vùng nhìn thấy (cần thử máy thật).
- Lưu bộ lọc đã chọn vào CloudStorage để mở lại giữ nguyên (nhớ giới hạn 4096 ký tự/giá trị).

### 2.4 Thao tác nhanh (broker thường làm)
Gọi chủ nhà (`tel:` qua `openLink` hay thẻ `<a>`: **chưa thử trong WebView Telegram**), chia sẻ (mục 1.8), đặt lịch xem (POST `/api/viewings` đã có), đổi trạng thái (PUT `/api/listing/<id>/status`), nhớ rung nhẹ khi thành công và `showPopup`/`showConfirm` (6.2) cho thao tác không hoàn tác được [S1].

### 2.5 Đối chiếu `UI/Main.dc.html`
| Mục trong mẫu | Hợp với Telegram? | Ghi chú |
|---|---|---|
| Khung 390 px, một cột | Hợp | Nhưng `tokens.css` đặt `--app-max: 420px`; trên iPad/Desktop căn giữa |
| Thẻ, ô tìm, chip, vùng chạm 44 px | Hợp | Giữ |
| Màu tô cứng bằng hex (nền `#071420`, chữ `#d7e4f4`, nút `#2aabee`…) trong thuộc tính `style` | **Xung đột** | Người dùng theme sáng vẫn thấy tối; không đổi theo `themeChanged`. Mẫu cố ý là bản vẽ ("REFERENCE MOCKUP" theo `UI/README.md`) nên phải chuyển sang token |
| Header tự vẽ: Quay lại + tiêu đề "Quản lý căn" + "12 căn" + nút Đóng | **Xung đột** | Telegram đã có header gốc với nút Đóng/Quay lại; `listings.html` ẩn hai nút bằng class `design-nav-btn` khi trong Telegram [đã xác minh] — đúng hướng, nhưng hãy bỏ hẳn khỏi mã chứ đừng ẩn. Số "N căn" nên đưa xuống làm dòng đếm dưới ô tìm |
| Nút nổi (FAB) + tab dưới 64 px | Hợp có điều kiện | Ba thanh đáy khi có MainButton (xem 2.1). Tab dưới phải cộng `--safe-bottom` |
| Tab dưới 4 mục có nhãn | Hợp | Đủ rộng cho 4 mục; thêm mục thứ 5 là hết chỗ |
| Phông Be Vietnam Pro + JetBrains Mono + Space Grotesk | Hợp, nhưng nặng | 190 KB phông tự lưu; kiểm số phông thật dùng (có 3 họ × nhiều độ đậm). `DESIGN.md` cũ ghi Geist/Space Grotesk, mẫu mới đổi sang Be Vietnam Pro (dấu tiếng Việt) — hai hệ thiết kế đang **mâu thuẫn**, chọn mẫu mới làm chuẩn và đánh dấu `stitch_ui/DESIGN.md` là lỗi thời [đã xác minh: DESIGN.md dòng 14–16 vs Main.dc.html dòng 13] |
| Không có trạng thái rỗng/lỗi/đang tải | Thiếu | Mẫu chỉ có một cảnh đẹp. Cần vẽ: đang tải, rỗng, lỗi mạng, hết phiên (401) |
| Không có chế độ sáng | Thiếu | Xem mục 3.1 |

---

## 3. Kiến trúc để lên web/PWA và native không phải viết lại

### 3.1 Bốn tầng (B đã có ba)
```
(1) tokens        tokens.css / tokens.json  - màu, chữ, khoảng cách; không biết gì về màn hình
(2) service/API   api.js                    - gọi máy chủ, trả dữ liệu thuần, không DOM
(3) platform      platform.js (MỚI)         - Telegram | trình duyệt | native: theme, nút, haptic, storage, chia sẻ, vùng an toàn, thông tin phiên
(4) giao diện     màn hình/component        - chỉ gọi (1)(2)(3), không đụng window.Telegram, location, localStorage
```
Quy tắc cần kiểm bằng lệnh (gate): ngoài `platform.js`, không có `window.Telegram` / `Telegram.WebApp` / `location.search` / `localStorage`; ngoài `tokens.css`, không có mã hex trong tầng giao diện.

Giao diện lớp bọc nền tảng (đề xuất, ví dụ):
```
platform.id            'telegram' | 'web' | 'native'
platform.ready()
platform.theme.get() / onChange(cb)         -> {scheme:'dark'|'light', params:{...}}
platform.safeArea.get() / onChange(cb)
platform.back.set(handlerOrNull)            // Telegram: BackButton; web: nút tự vẽ; native: nút hệ thống
platform.primary.set({text, onClick, loading}) / clear()
platform.haptic.tap() / select() / success() / error()
platform.storage.get/set(key)               // Cloud/Device/Secure -> localStorage -> bộ nhớ native
platform.share.listing(listingId)           // Telegram: shareMessage; web: navigator.share hoặc sao chép link; native: share sheet
platform.credentials()                       // xem 3.3
platform.openLink(url) / call(phone)
```
Mỗi hàm có đường lùi nên mini app chạy được cả trong Chrome thường (đây cũng là cách test không cần điện thoại).

### 3.2 Nhận xét hướng tokens.css + api.js của phiên B
Tôi đọc cả hai tệp (chưa commit, đang ở dạng `??`) [đã xác minh].

**tokens.css — đứng được, cần sửa 5 chỗ:**
1. Chế độ `[data-theme="telegram"]` chỉ ánh xạ 10 biến (`--c-bg`, `--c-surface`, `--c-surface-quiet`, `--c-text`, `--c-muted`, `--c-dim`, `--c-accent`, `--c-primary`, `--c-on-primary`, `--c-bad`, `--c-border`). Các biến còn lại — `--c-text-2`, `--c-text-3`, `--c-text-quiet`, `--c-placeholder`, `--c-icon-btn-bg`, `--c-scrim`, toàn bộ nhóm `--st-*` (nền huy hiệu trạng thái tối) và `--c-surface-thumb/badge` — **vẫn là màu tối cứng**. Trên theme sáng sẽ ra chữ sáng nhạt trên nền sáng. Cần ánh xạ đủ, hoặc tính ra từ biến gốc bằng `color-mix()` [ý kiến; đã xác minh việc thiếu bằng đọc tệp].
2. `color-scheme: dark` cố định ở `:root` — phải đổi theo scheme, nếu không thanh cuộn và ô nhập mặc định của trình duyệt vẫn tối.
3. Phép đặt `data-theme="telegram"` hiện **không bật mặc định** ("Mặc định giữ nền tối của thương hiệu") — ai bật, bật lúc nào, chưa thấy mã. Đề xuất: bộ token **hai bậc**: (a) thương hiệu tối và (b) thương hiệu sáng, chọn theo `colorScheme`/`prefers-color-scheme`; chỉ lấy từ `--tg-theme-*` các màu **chức năng** (nền, chữ, link, nút, nguy hiểm, đường kẻ). Lý do: màu trạng thái (còn trống/đã thuê/cần chú ý) là ngữ nghĩa nghiệp vụ, không nên đổi theo theme của người dùng [ý kiến].
4. Ánh xạ `--c-surface` ← `secondary_bg_color` và `--c-bg` ← `bg_color`. Cách Telegram dùng cặp này (nền trang với nền thẻ nào sáng hơn) **tôi chưa xác nhận bằng nguồn** [chưa có nguồn]. Phải xem trên 3 theme thật (mặc định sáng, mặc định tối, một theme tùy biến) trước khi chốt. Tài liệu có `section_bg_color`/`section_separator_color` cho đúng việc thẻ/phân cách — nên dùng chúng cho thẻ.
5. `--safe-*` xem mục 1.2. Tốt, nhưng cần kiểm.
Điểm cộng: tên ngữ nghĩa (`--c-*`), tách primitive/semantic, có hạng mục `prefers-reduced-motion`, phông tự lưu. Nên có thêm bản `tokens.json` (nguồn thật) rồi sinh CSS, để native dùng chung (xem 3.4) — **chưa cần làm ngay**.

**api.js — đứng được, cần 6 chỗ chỉnh:**
1. Không đụng DOM, đúng ý. Nhưng nó tự đọc `window.Telegram` (`tgApp()`) và `location.search` (`pageParams()`), tức là đang giữ luôn vai trò của lớp bọc nền tảng. Chuyển thành một **nhà cung cấp thông tin xác thực được tiêm vào** (`TrueNestAPI.configure({baseUrl, getAuth})`), `getAuth()` do `platform.js` cấp.
2. `authMode()=='demo'` và việc chuyển tiếp `demo`/`broker_id` từ URL: trong sản phẩm thật, bất kỳ ai thêm `?demo=1` vào link là chạy. Đưa vào cờ build/dev; máy chủ cũng phải từ chối (mục 4.1).
3. Gửi `tg_user_id` "để không làm hỏng hành vi đang chạy" (chú thích đầu tệp): đó chính là cái cửa hổng ở máy chủ. Khi máy chủ sửa xong, mã này vô dụng; đặt hạn gỡ.
4. Thiếu: `baseUrl` (web/native không dùng đường dẫn tương đối), thời gian chờ + hủy yêu cầu (`AbortController`), cơ chế xử lý 401 chung (gọi lại `getAuth` hoặc báo lớp trên), không tự thử lại với PUT/POST.
5. Hình dạng phản hồi từ máy chủ không đồng nhất: `listings` → `{items,...}`, `clients` → `{clients}`, `viewings` → `{viewings}`, `deals` → `{closed, negotiating,...}` (ghi ngay trong chú thích của `api.js`, `tabs.js` còn phải đoán `data.deals || data.closed`) [đã xác minh]. `api.js` nên **chuẩn hóa** về `{items,total}` ở một chỗ để giao diện không biết chuyện đó, và máy chủ sau này sửa theo hợp đồng ở mục 4.4.
6. Dạng xuất: hiện là IIFE gắn `window.TrueNestAPI`. Nếu dùng Vite/Capacitor, chuyển sang `export` (ES module). Giữ cả hai trong thời gian chuyển tiếp là được [ý kiến].
Điểm cộng: có lớp lỗi `ApiError(status, code, message)`, không rò thông tin vào DOM, gọi mạng ở đúng một chỗ.

### 3.3 Xác thực đa nền tảng
```
Hôm nay      : initData -> header "X-Telegram-Init-Data" -> máy chủ kiểm HMAC + auth_date -> broker_id
Giữ nguyên   : initData chỉ để ĐỔI LẤY phiên:  POST /api/v1/auth/telegram  -> {token, expires_at}
Web/PWA      : Telegram Login Widget (hoặc OTP qua bot) -> cùng endpoint đổi phiên -> {token}
Native       : cùng token, cất trong Keychain/Keystore (Capacitor plugin hoặc SecureStorage của Telegram nếu chạy trong TMA)
Mọi nền tảng : header  Authorization: Bearer <token>  -> API chỉ thấy MỘT kiểu xác thực
```
- Lợi: mọi nền tảng cùng một đường vào API; không phải gửi nguyên chuỗi initData (dài, chứa dữ liệu người dùng) vào mọi lời gọi.
- Telegram Login Widget và OTP-qua-bot: **tôi chưa đọc tài liệu** [chưa có nguồn]; chọn cách nào là quyết định sau, nhưng đường "đổi lấy token" thiết kế sẵn thì chọn cách nào cũng cắm vào được. SecureStorage trong TMA (9.0) lưu ở Keychain/Keystore [S1].
- Cả ba giai đoạn dùng chung một bảng người dùng (`broker_id` = id Telegram như hiện tại). Web không có Telegram sẽ cần cách **liên kết** tài khoản web với id Telegram [ý kiến; chưa thiết kế].
- Không đưa chuỗi initData vào URL (mục 4.1): `tabs.js` và `listings.html` hiện còn làm vậy.

### 3.4 Bảng so sánh stack
Số liệu đo hôm nay (tải từ jsDelivr rồi `gzip -9`): React 18.3.1 + ReactDOM = 4.268 + 42.798 = **47.066 B** gzip; Preact 10.24.3 = **4.686 B** gzip (bản `latest` trên npm hiện là 11.0.1, tôi đo bản 10.24.3; chưa đo bản 11) [đã xác minh]. Chi phí cố định cho mọi lựa chọn: `telegram-web-app.js` 19.087 B gzip.

| Tiêu chí | JS thuần, không build (hướng hiện tại) | Preact + Vite | React Native / Expo | Capacitor (bọc bản web) |
|---|---|---|---|---|
| Tốc độ mở trong Telegram | Tốt nhất: không runtime khung; `listings.html` 5,8 KB gzip | Rất tốt: thêm ~4,7 KB gzip runtime + mã đã build; bundle chia nhỏ được | **Chưa đo.** Trong Telegram nó chạy dưới dạng web (react-native-web: Expo ánh xạ `<View>` sang phần tử react-dom [S9]); docs không nói về kích thước/khởi động [S9]. Kỳ vọng nặng hơn Preact vì kéo thêm react-dom + lớp react-native-web **[chưa có nguồn]** | Không áp dụng trong Telegram: Capacitor là vỏ native cho app riêng, không chạy bên trong Telegram. Mini App vẫn là bản web |
| Dùng lại code cho web/PWA | Dùng lại được mã nhưng tự quản trạng thái/DOM; mỗi màn thêm công | Tốt: cùng mã chạy Telegram + web; có hệ sinh thái component | Tốt cho web+iOS+Android từ một nguồn (Expo "maximizes code reuse" [S9]); nhưng **không** dùng lại được mã DOM/HTML hiện có | Rất tốt: "nếu chạy trên trình duyệt thì gần như chạy trong app" [S8]; dùng lại nguyên bản web |
| Dùng lại cho native | Qua Capacitor: được, mã DOM thuần chạy trong WebView | Qua Capacitor: được | Native thật (giao diện gốc), nhưng viết lại toàn bộ lớp giao diện | Được: thêm dự án iOS/Android, thêm cầu nối plugin viết Swift/Java/JS khi cần tính năng máy [S8] |
| Chi phí chuyển từ code hiện tại | 0 | Trung bình, **rẻ nhất ngay bây giờ** vì mới có ~2 màn (`listings.html` 268 dòng, `tabs.js` 114 dòng) [đã xác minh] và `tokens.css`/`api.js` giữ nguyên. Đắt dần theo mỗi màn thêm | Cao: viết lại toàn bộ giao diện sang thành phần RN; chỉ `api.js`-kiểu lớp dịch vụ dùng lại được | Thấp nếu đã có bản web đóng gói (Vite hoặc thuần); chủ yếu là việc cấu hình dự án native |
| Hợp với backend Python stdlib | Hợp: tệp tĩnh + JSON | Hợp: `vite build` ra thư mục tĩnh, server phục vụ như hiện nay (nhớ thêm MIME `.woff2`, `.map`, tệp có băm tên) | Hợp về API (JSON qua HTTP); khâu phát hành app qua cửa hàng là việc riêng | Hợp: gọi cùng API qua HTTPS; cần CORS đúng (hiện `*`, nên siết) và phiên token thay vì initData |
| Rủi ro chính | String-template + `innerHTML` rải rác (như `tabs.js`) dễ sót thoát ký tự → XSS; trạng thái bộ lọc/sheet/form tự quản dễ lỗi | Thêm chuỗi công cụ Node cho máy phát triển; phải học/giữ Vite, TypeScript tùy chọn | Hai hệ thống giao diện (Telegram web và app RN) phải bảo trì song song | Có chi phí cửa hàng ứng dụng (tài khoản, duyệt); hiệu năng WebView trên máy yếu **chưa đo** |

Về `@telegram-apps/sdk` (kiểm tình trạng thật, 17/10/2026): bản `latest` là **3.11.8, xuất bản 08/10/2025**; bản ghi cuối của gói trong registry là 05/12/2025; không có cờ `deprecated` [đã xác minh, S5]. Gói cùng nhóm `@tma.js/sdk` có `latest` 3.3.0 (14/07/2026) và `4.0.0-rc.0` (11/10/2026) [S5]; kho GitHub `Telegram-Mini-Apps/tma.js` không bị lưu trữ, cập nhật gần nhất 12/10/2026, phát hành `@tma.js/sdk@3.3.0` ngày 14/07/2026 [S6]. Trang tài liệu `@tma.js/sdk` có mục "Migrating from telegram-apps" nhưng **không nói** gói này là đổi tên hay kế nhiệm của `@telegram-apps/sdk` [S7]. Kết luận có nhãn: *không bị bỏ rơi chính thức nhưng gói `@telegram-apps/sdk` đã 12 tháng không có bản mới; gói đang được cập nhật là `@tma.js/sdk`* — nếu dùng SDK thì chọn `@tma.js/sdk`. Tôi **chưa kiểm** nó có hỗ trợ đủ API 9.x–10.x (Device/SecureStorage, v.v.) không. Với kế hoạch này không cần SDK: lớp `platform.js` bọc trực tiếp `telegram-web-app.js` chính thức là đủ, và SDK nào cũng đổi được ở một chỗ.

**Khuyến nghị một câu [ý kiến]:** giữ 3 tầng của B + thêm lớp bọc nền tảng; làm lớp giao diện bằng Preact + Vite; native bằng Capacitor khi đến Phase 3; bỏ RN/Expo.
Điều kiện đổi ý: nếu sau khi làm xong lớp bọc nền tảng + 3 màn thật mà JS thuần vẫn gọn (xem cổng P9) thì cứ ở lại JS thuần — đừng thêm build vì thời trang.

---

## 4. Backend

### 4.1 Đã xác minh khi đọc và chạy code: lỗ hổng xác thực
`_auth` (server.py dòng 105–134):
- dòng 107–111: `demo=1` → trả `broker_id` lấy từ chính URL, **không điều kiện môi trường nào**;
- dòng 131–133: nếu chữ ký sai/thiếu nhưng có `tg_user_id` là số → **tin luôn**; chú thích trong mã nói "WebView context is trusted" — không đúng: ai cũng gọi được, không cần WebView;
- `validate_init_data` không kiểm `auth_date`.
Thí nghiệm của tôi: chạy `python -I webapp/server.py` trên cổng 18080, `BOT_DB_PATH` trỏ vào thư mục tạm, `BOT_TOKEN=x`. Kết quả: `GET /api/listings` → **401**; còn `?tg_user_id=123`, `?demo=1&broker_id=123`, `/api/clients?tg_user_id=999` đều **qua được xác thực** — ngăn xếp lỗi nằm ở `api.get_listings → db.list_broker_listings`: `no such table: tg_listings` (CSDL tạm rỗng), tức là đã sau bước xác thực [đã xác minh]. Với CSDL thật, ba lời gọi đó trả dữ liệu của môi giới có id tương ứng. (Tôi không chạy trên CSDL thật.)
Hệ quả phụ: `log_message` (dòng 364–366) ghi cả dòng yêu cầu, **kèm query string** — mà `tabs.js`/`listings.html` đưa nguyên `init_data=` vào query. Chuỗi initData hợp lệ sẽ nằm trong log và vì không kiểm `auth_date`, dùng lại được mãi [đã xác minh bằng đọc mã; chưa kiểm tệp log thật].
Phụ khác: CORS `Access-Control-Allow-Origin: *` cho cả API có xác thực (dòng 83) — với token trong header thì rủi ro thấp hơn cookie, nhưng nên siết về đúng origin của app; `_static` kiểm `full.startswith(STATIC_DIR)` có thể khớp nhầm thư mục anh em tên bắt đầu giống nhau (ví dụ `static_x`) — chỉ là điểm nhỏ [ý kiến, chưa tái hiện].

### 4.2 stdlib `http.server` có đủ không?
Số liệu thật: server.py có **30 nhánh** `if parts[0] == ...` tự định tuyến; mỗi API trả `{"error": "<mã>"}` (không có thông điệp tiếng Việt, không có chi tiết trường lỗi) [đã xác minh]. `ThreadingHTTPServer` đủ để chạy với số môi giới nhỏ [ý kiến; **chưa đo tải**, tôi không chạy kiểm thử chịu tải]. Điểm nghẽn thật có lẽ ở SQLite khi nhiều ghi cùng lúc (chưa đo) chứ không ở `http.server`.
Kết luận: **đủ cho giai đoạn Telegram-only, nếu sửa mục 4.1 và 1.9**; đổi framework không sửa được các lỗi đó.

### 4.3 Khi nào đổi (FastAPI hoặc tương tự)
FastAPI sinh OpenAPI/JSON Schema tự động, xác thực dữ liệu bằng Pydantic, có cơ chế phụ thuộc (dependency) cho bảo mật, hỗ trợ OAuth2/JWT và khóa API qua header/query/cookie [S10]. Bản `latest` trên PyPI hiện 0.143.3, yêu cầu Python ≥ 3.10, phụ thuộc starlette và pydantic ≥ 2.9 (xuất bản 16/10/2026) [S11]; máy này chạy Python 3.11.4 [đã xác minh; máy chủ thật chưa biết]. Chạm **một** trong các điều kiện sau thì đổi:
1. Web/PWA ra đời cần phiên token + đăng nhập (mục 3.3) — viết tay với stdlib được nhưng dễ sai.
2. Số route vượt khoảng 40–50 hoặc có hơn 1 người cùng sửa (hiện 30 route, tự định tuyến) [ngưỡng: ý kiến].
3. Cần tải ảnh lên (multipart), WebSocket/thông báo đẩy, hoặc nhiều yêu cầu đồng thời (`ThreadingHTTPServer` mỗi yêu cầu một luồng, không giới hạn).
4. Cần hợp đồng API sinh tự động cho client web/native.
Cái giá: phá luật "không phụ thuộc ngoài stdlib" của `webapp/README.md`, thêm quản lý gói/venv, cổng chạy (uvicorn) và có thể nâng Python. Lớp `api.py`/`api_clients_deals.py` (hàm thuần trả `(dict, code)`) **giữ nguyên được**: chỉ thay phần định tuyến — đúng ý quy tắc "UI không đọc db trực tiếp" của dự án [đã xác minh, webapp/README.md].

### 4.4 Hợp đồng API dùng chung (mini app, web, native)
Đề xuất [ý kiến], chốt bằng một tệp OpenAPI 3 mô tả 30 route hiện có trước khi đổi bất cứ thứ gì:
- **Phiên bản:** tiền tố `/api/v1`; giữ `/api/*` cũ chạy song song tới khi mini app chuyển xong.
- **Xác thực:** `Authorization: Bearer <token>`; endpoint đổi `POST /api/v1/auth/telegram` nhận initData trong **thân** yêu cầu (không trong URL), trả `{token, expires_at}` (mục 3.3). Kiểm `auth_date` tối đa N giờ (N do ta chọn).
- **Danh sách:** luôn `{items, total, limit, offset}`; hôm nay có endpoint trả `clients`/`viewings`/`closed` — đổi tên dần, giữ trường cũ một thời gian.
- **Lỗi:** `{error: "<mã_ổn_định>", message: "<tiếng Việt cho người dùng>", fields: {tên: "lý do"}}`; mã HTTP nhất quán (400/401/403/404/409/422).
- **Kiểu dữ liệu:** tiền là số nguyên VND (`price_vnd` đã vậy); thời điểm là epoch giây UTC (`scheduled_at` đã vậy) — múi giờ hiển thị Asia/Ho_Chi_Minh ở client; id luôn là chuỗi.
- **Ghi:** `PUT` chỉ nhận danh sách trường cho phép (đã có); thêm `If-Match`/phiên bản dòng khi cần chống ghi đè (hai thiết bị cùng sửa).
- **Chia sẻ:** `POST /api/v1/share` (đã có dạng này) và endpoint mới tạo `PreparedInlineMessage` (chỉ khi gọi từ Telegram) để `shareMessage` dùng.
- **Quy tắc bất biến:** trường mới chỉ **thêm**; không đổi nghĩa trường đã phát hành (native đã lên cửa hàng thì không ép cập nhật được).
- Sinh client TypeScript/JS từ OpenAPI là khả thi nhưng tôi chưa thử công cụ cụ thể [chưa có nguồn].

---

## 5. Danh sách việc theo thứ tự ưu tiên (kèm cổng kiểm)

Phân tuyến theo tệp (nhắc theo luật nhiều phiên): P0–P1 và P6, P7, P8 chạm `webapp/server.py`, `api*.py` — không thuộc phiên B (giao diện). Điều phối nên giao cho đúng một phiên.

| # | Việc | Cổng kiểm (đạt khi…) |
|---|---|---|
| **P0** | **Đóng cửa xác thực:** bỏ tin `tg_user_id`; `demo=1` chỉ chạy khi có `WEBAPP_DEV=1` và máy chủ chỉ nghe `127.0.0.1`; kiểm `auth_date` (hạn N giờ); initData qua header/thân yêu cầu, không qua URL; log không in query | Bốn lời gọi tôi đã thử (`/api/listings`, `?tg_user_id=123`, `?demo=1&broker_id=123`, `/api/clients?tg_user_id=999`) cùng trả **401** với CSDL thật có dữ liệu; initData hợp lệ nhưng `auth_date` quá hạn → 401; chuỗi initData hợp lệ → 200; `grep init_data` trong log sau một phiên dùng thử → 0 dòng |
| **P1** | Lớp bọc nền tảng `platform.js`; chuyển mọi `window.Telegram`/`location.search`/`localStorage` vào đó | `grep -rn "Telegram\.\|location\.search\|localStorage" webapp/static/v2` chỉ ra kết quả trong `platform.js`; mở trang trong Chrome thường: 0 lỗi console, danh sách vẫn vẽ (dùng nền tảng `web`) |
| **P2** | Hoàn thiện `tokens.css`: bộ sáng + tối; ánh xạ đủ biến; `color-scheme` theo scheme; nghe `themeChanged` | Chụp màn hình danh sách ở 3 theme Telegram (sáng, tối, một theme tùy biến) trên máy thật; tính tỉ lệ tương phản chữ/nền cho mọi cặp token chữ ≥ 4,5:1 (chữ thường); `grep -n "#[0-9a-fA-F]\{6\}"` trong tầng giao diện → 0 (ngoài tokens) |
| **P3** | Chỉnh `api.js`: `configure({baseUrl,getAuth})`, thời gian chờ + hủy, xử lý 401 chung, chuẩn hóa `{items,total}`, bỏ gửi `tg_user_id` sau khi P0 xong, xuất ES module | Bộ kiểm hợp đồng chạy cùng một tệp ví dụ phản hồi với hai `getAuth` giả (Telegram, Bearer) đều xanh; mutation: bỏ bước chuẩn hóa → ít nhất một test đỏ |
| **P4** | Điều hướng trong Telegram: BackButton thay header tự vẽ; MainButton cho màn form; tab dưới chỉ ở màn gốc; bỏ `requestFullscreen` (hoặc dùng đúng `--safe-top` nếu giữ); `disableVerticalSwipes` chỉ khi sheet mở | Trên 1 iPhone có tai thỏ + 1 Android: nút Quay lại hệ thống đi lùi đúng 1 màn ở cả 3 màn con; không có 2 thanh header; không có 2 thanh đáy chồng nhau; **đo bằng pixel** chiều cao vùng nội dung trước/sau; bàn phím mở: ô nhập đang gõ vẫn thấy được ở cả hai máy |
| **P5** | Chia sẻ căn: endpoint tạo `PreparedInlineMessage` + `shareMessage`; tạo ngay trước khi bấm | Môi giới gửi 1 căn vào chat thử trong ≤ 3 chạm; tin nhận được mở đúng `/s/<token>`; để tin quá hạn rồi gửi → app hiện thông báo lỗi tiếng Việt chứ không treo (kiểm bằng sự kiện `shareMessageFailed`) |
| **P6** | Hiệu năng máy chủ + tải đầu: nén, `Cache-Control`/ETag, tên tệp có băm, MIME `.woff2`/`.webp`, `ready()` sau khung xương, gỡ Google Fonts, đệm danh sách lần trước | Đo **trước/sau** trên máy thật: thời gian từ chạm mở app đến thẻ căn đầu tiên (mỗi bản ≥ 10 lần, báo trung vị và p90); số byte tải lần mở thứ hai (devtools từ xa) giảm so với lần đầu; `curl -I` thấy `Cache-Control` và `Content-Encoding` |
| **P7** | Viết OpenAPI 3 cho 30 route hiện có (chưa đổi framework) | Một tập lệnh gọi mọi GET với dữ liệu thử và xác nhận phản hồi khớp lược đồ → 0 sai; tài liệu duyệt bởi phiên làm giao diện (họ đọc xong gọi được không cần xem mã server) |
| **P8** | `POST /api/v1/auth/telegram` đổi initData lấy token; giao diện dùng token | Cùng tài khoản gọi API từ trang web thuần (ngoài Telegram) bằng token → 200; token hết hạn → 401 → app tự đổi lại, người dùng không thấy gì; không còn initData nào trong URL |
| **P9** | Điểm quyết định lớp giao diện (sau khi xong P1–P4 và 3 màn: Danh sách, Chi tiết, Form) | Đếm: số dòng mã thao tác DOM tay cho bộ lọc/sheet/form, số lỗi trạng thái phát sinh. Ngưỡng do chủ dự án đặt; nếu vượt thì chuyển Preact+Vite (port 2–3 màn, giữ nguyên `tokens.css`, `api.js`, `platform.js`) |
| **P10** | Khi cần đổi FastAPI: bám điều kiện 4.3 | Cả bộ kiểm hợp đồng P7 chạy xanh trên server mới không sửa client |
| **P11** | Native (Phase 3): thử một vỏ Capacitor chạy màn Danh sách | Cùng thư mục build chạy trên 1 máy Android thật; không sửa dòng nào trong `api.js`/`tokens.css`; đo thời gian mở lạnh so với Mini App |

---

## 6. Chưa có nguồn / chưa chắc

Đã xác minh nhưng **qua bản trích của công cụ fetch** (không phải nguyên văn): toàn bộ mục 1 từ S1; mục 10.2 bảo mật từ S2. Nên đọc lại nguyên văn các con số giới hạn trước khi dùng làm hợp đồng.

**Chưa có nguồn (tôi không đọc được trang nào xác nhận):**
- Thời hạn của `PreparedInlineMessage` (chỉ thấy kết quả tìm kiếm nói có ngày hết hạn tuyệt đối [S13]).
- Giới hạn độ dài/ký tự của `startapp`.
- Điều kiện nào thì `switchInlineQuery` dùng được (loại Mini App); và `t.me/share/url` qua `openTelegramLink` có phù hợp để chia sẻ link công khai không.
- Hành vi bàn phím che ô nhập / thanh ghim đáy khác nhau ra sao giữa iOS, Android, Desktop (chỉ có lời khuyên chung dùng `viewportStableHeight` từ S1/S7).
- Cặp `bg_color` / `secondary_bg_color` / `section_bg_color` nên gán cho nền trang / nền thẻ như thế nào trong thực tế người dùng Telegram.
- `--tg-safe-area-inset-*` và `--tg-content-safe-area-inset-*` cộng với nhau hay chồng lên nhau (công thức của B đang cộng).
- Gọi điện `tel:` và sao chép văn bản trong WebView Telegram trên iOS/Android.
- `@tma.js/sdk` có phủ API 9.x–10.x không; quan hệ chính thức với `@telegram-apps/sdk`.
- Kích thước bundle và thời gian khởi động của Expo web / react-native-web; hiệu năng WebView của Capacitor trên máy yếu.
- Telegram Login Widget và cách đăng nhập web: chưa đọc.
- Ed25519 trong Python: cần gói ngoài (kiến thức chung).
- Cách bản chạy thật được phơi ra Internet (reverse proxy, TLS) và Python/hệ điều hành máy chủ thật: tôi không biết.
- Chịu tải của `ThreadingHTTPServer` + SQLite: chưa đo.
- Phiên bản Telegram mà các môi giới thật đang dùng: không biết.
- Tệp log thật có chứa initData hay chưa: tôi chỉ đọc mã, không mở log.

**Mâu thuẫn nhỏ trong nguồn:** trang `bots/webapps` (qua bản trích) nói Bot API mới nhất là 10.1 (11/06/2026), còn changelog liệt kê tới 10.3 (24/08/2026) [S1, S2]. Tôi lấy changelog làm mốc; không ảnh hưởng kết luận (10.2/10.3 không có thay đổi Mini App ngoài phần bảo mật origin).

---

## 7. Nguồn đã fetch

| Mã | Địa chỉ | Dùng cho / mức đọc |
|---|---|---|
| S1 | https://core.telegram.org/bots/webapps | Mục 1 (theme, viewport, nút, haptic, storage, initData, startapp, chia sẻ, phiên bản API). Fetch 2 đoạn (0–100.000 và 100.000–113.140 ký tự), qua bản trích của công cụ |
| S2 | https://core.telegram.org/bots/api-changelog | Mốc phiên bản 9.5 → 10.3; thay đổi Mini App ở 9.5, 9.6, 10.1, 10.2. Đọc 100.000/169.944 ký tự đầu, qua bản trích |
| S3 | https://core.telegram.org/bots/api (đoạn 300.000–400.000 ký tự) | Tham số `savePreparedInlineMessage`, `answerWebAppQuery`. Các đoạn 400.000–500.000 và 500.000+ không chứa kiểu `PreparedInlineMessage` (đã thử). Đoạn 0–100.000 không chứa các mục này |
| S4 | https://telegram.org/js/telegram-web-app.js | Tải bằng `curl`, đo 119.731 B / 19.087 B gzip; `webAppVersion = '6.0'` mặc định |
| S5 | https://registry.npmjs.org/ (gói `@telegram-apps/sdk`, `@tma.js/sdk`, `@telegram-apps/sdk-react`, `@tma.js/sdk-react`, `vite`, `preact`, `react`, `expo`, `@capacitor/core`) | Phiên bản và ngày xuất bản; qua `curl` + phân tích JSON |
| S6 | https://api.github.com/repos/Telegram-Mini-Apps/tma.js (+ `/releases`) | Không lưu trữ; push 12/10/2026; phát hành 14/07/2026 |
| S7 | https://docs.telegram-mini-apps.com/packages/tma-js-sdk và `/features/viewport` | `@tma.js/sdk`; stable height; safe area vs content safe area |
| S8 | https://capacitorjs.com/docs | Capacitor: web-first, plugin native |
| S9 | https://docs.expo.dev/workflow/web/ | Expo web = react-native-web; tái sử dụng mã; không nói về kích thước bundle |
| S10 | https://fastapi.tiangolo.com/features/ | OpenAPI tự sinh, Pydantic, bảo mật |
| S11 | https://pypi.org/pypi/fastapi/json | FastAPI 0.143.3, Python ≥ 3.10, xuất bản 16/10/2026 |
| S12 | https://cdn.jsdelivr.net/npm/{preact@10.24.3, react@18.3.1, react-dom@18.3.1} | Kích thước gzip đo tại chỗ |
| S13 | Kết quả **WebSearch** (chưa fetch trang): `docs.aiogram.dev/.../prepared_inline_message.html`, `core.telegram.org/constructor/messages.botPreparedInlineMessage`, `adsgram.ai/blog/adsgram/telegram-mini-app-tma-development-mistakes-and-how-to-avoid-them`, `docs.telegram-mini-apps.com/...viewport` | Chỉ dùng làm gợi ý, mọi điều rút từ đây đã gắn nhãn "chưa có nguồn" |

Đo nội bộ repo (không phải nguồn web): chạy `webapp/server.py` cổng 18080 với CSDL tạm trong thư mục scratchpad (đã tự tắt); đọc `webapp/server.py`, `webapp/README.md`, `webapp/static/v2/{listings.html,tabs.js,tokens.css,api.js,fonts.css}`, `UI/Main.dc.html`, `UI/README.md`, `stitch_ui/DESIGN.md`. Lúc đọc, `tokens.css`, `api.js`, `fonts.css`, `fonts/` ở trạng thái chưa commit (phiên B đang làm); nhận xét ở mục 3.2 là trên bản tại thời điểm đó.
