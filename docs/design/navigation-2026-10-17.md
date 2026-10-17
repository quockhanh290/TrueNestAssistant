# Thiết kế lại điều hướng Mini App TrueNest: trang chính dẫn vào trang con (17/10/2026)

Người viết: phiên E (thiết kế). Chỉ đọc code và dựng mockup trong `docs/design/`; không sửa code, không commit.
Nhãn: **[đã xác minh]** = tôi đã đọc code/chạy/đo; **[nguồn]** = trang core.telegram.org đã fetch hoặc ảnh chủ dự án cung cấp; **[ý kiến]** = phán đoán thiết kế; **[giả định]** = con số tôi đặt tạm, chưa đo; **[chưa đo]** = cần dữ liệu thật.
Tài liệu nền: `docs/research/tma-design-2026-10-17.md` (viết tắt "tài liệu nghiên cứu").

---

## 0. Tóm tắt

1. Bỏ thanh tab dưới. Một **trang chính** gồm ba phần: "Hôm nay", ba lối tắt, rồi danh sách các mục dạng dòng có mũi tên `›`. Mỗi mục dẫn vào một trang con; trang con dẫn vào trang chi tiết. Quay lại hoàn toàn nhờ nút Quay lại của Telegram.
2. Kiểm kê được **28 điểm đến** gom thành **9 nhóm** (mục 2). Thanh tab chỉ chứa 4–5 mục nên 20 điểm đến không có chỗ; trang chính chứa được cả 28 (qua 9 dòng: 7 mục và 2 dòng phụ).
3. Mọi hành động thường dùng (13 hành động, mục 3.3) cách trang chính **tối đa 2 chạm**. Ba hành động ít dùng (sửa căn, sửa bài đăng, ghi chú khách) là 3 chạm.
4. Cái giá phải trả: chuyển giữa hai mục cùng cấp (Căn hộ sang Khách) mất 2 chạm thay vì 1. Tôi bù bằng lối tắt chéo (mục 6). **Tần suất chuyển mục chưa có dữ liệu** (mục 8.3), nên đây là đánh đổi có chủ đích, chưa phải đã chứng minh.
5. Phần "Hôm nay" dựng được một phần bằng API đã có; **hai trong ba khối thiếu API đúng nghĩa** (mục 4).
6. Phải sửa luật A3 trong `CLAUDE.md` (mục 9): luật hiện tại giả định có tab dưới.

---

## 1. Nguồn về mini app của BotFather

- **Ảnh chụp thật do chủ dự án cung cấp (17/10/2026, theme tối).** Tôi không tự tìm được ảnh hay bài mô tả; điều dưới đây là mô tả của điều phối viên về ảnh đó, tôi chưa nhìn ảnh trực tiếp.
  - Thanh đầu do Telegram vẽ: mũi tên Quay lại bên trái, tên "BotFather", nút ba chấm và nút X bên phải. Mini app không tự vẽ header.
  - Đây là trang con cấp 2 (danh sách bot, rồi trang của một bot): tên bot "TrueNest Assistant" cỡ lớn căn giữa, `@truenest_bot` chữ xám nhỏ.
  - Một thẻ bo góc chứa ô token (làm mờ) và hai nút ngang nhau Copy (xanh), Revoke (đỏ), dưới thẻ có đoạn chú thích xám kèm "Read more ›".
  - Mục "Settings": danh sách gom nhóm kiểu iOS, các dòng nối liền, bo góc ở cả cụm, mỗi dòng gồm icon nét mảnh, nhãn, mũi tên `›`. Các dòng: Edit Info, Commands, Mini Apps, Bot Settings, Login Widget, Serverless (có huy hiệu NEW). Mỗi dòng dẫn sang một trang con.
  - Không có thanh tab dưới, không có MainButton, không có nút nổi. Chân trang chỉ có chữ "@BotFather".
- **Suy ra từ ảnh, chưa đo hành vi:** (a) mẫu điều hướng là danh sách dòng `›` dẫn vào trang con; (b) hành động chính của trang (Copy/Revoke) nằm trong nội dung chứ không phải MainButton; (c) quay lại hoàn toàn nhờ BackButton của Telegram.
- **Tìm nguồn chữ:** WebSearch không ra ảnh hay mô tả giao diện BotFather; chỉ có hướng dẫn bên thứ ba về cách bật mini app trong BotFather, mô tả lệch nhau giữa các bài (giao diện đã đổi theo thời gian). Tôi không dùng chúng.
- **core.telegram.org/bots/webapps** (fetch 17/10/2026, đọc hết 113.140 ký tự qua công cụ trích): chỉ nói BotFather ở ba chỗ: đặt Main Mini App, thêm mục "Settings" vào menu ngữ cảnh của Mini App ("You can add a 'Settings' item to the context menu of your Mini App using @BotFather"), và cấu hình mode compact/biểu tượng tải. **Không nói gì** về cách BotFather tự dựng giao diện. Giới hạn độ dài/ký tự của `startapp`: **không có trong trang** (xác nhận lại lần này).
- Giới hạn của BotFather làm gương: nó là công cụ có ~7 mục ngang hàng, dùng thưa (người dùng mở vài lần để cấu hình). TrueNest là công cụ dùng nhiều lần mỗi ngày. Mẫu hub phù hợp về hình dạng, nhưng **không có bằng chứng rằng nó chịu được tần suất dùng của môi giới** [ý kiến].

---

## 2. Kiểm kê điểm đến

Nguồn: **B** = menu bot (`utils.py` `MENU_KB`); **A** = nhóm route API trong `webapp/server.py`; **T** = trang trên nhánh `origin/ui-broker-flow` của Tana (xem bằng `git ls-tree`/`git show`); **S** = màn trong `stitch_ui/screens/`.

Số đo [đã xác minh]: menu bot có **11 nút** (điều phối nói 10; tôi đếm 1 + 2 + 2 + 2 + 2 + 2). API có **17 họ đường dẫn** (GET: listings, listing, post, trial, shares, admin, propose, xbroker, clients, client, viewings, deals, profile, notify, referral; POST thêm: share, premium). Nhánh Tana có **9 trang** (clients, deals, profile, propose, settings, shares, upgrade, viewings, xbroker). `stitch_ui/screens/` có **21 tệp** (20 html, 1 md); 4 ảnh chụp (08, 11, 19, 23) là đồ marketing (thẻ mạng xã hội, email, banner), không phải màn app nên không tính.

| # | Điểm đến | Nguồn | Ghi chú |
|---|---|---|---|
| **Nhóm 1. Căn hộ** | | | |
| 1 | Danh sách căn | B, A `listings`, S15 | Đã có trang `listings.html` |
| 2 | Chi tiết căn | A `listing/<id>`, S04, S12 | |
| 3 | Sửa thông tin căn | A PUT `listing/<id>`, S03 | |
| 4 | Thêm căn mới | B `menu:new`, S13 | **Chưa có API tạo căn**: hiện chỉ bot nhận tin. Trên web cần API mới |
| 5 | Bộ lọc căn (tờ kéo lên) | A (tham số lọc của `listings`), S20 | Không phải trang riêng: là sheet trong trang 1 |
| 6 | Bài đăng của căn (xem/sửa theo ngôn ngữ) | B `menu:write`, A `post/<id>`, S10 | |
| **Nhóm 2. Khách** | | | |
| 7 | Danh sách khách | B, A `clients`, T, S24 | |
| 8 | Chi tiết khách | A `client/<id>`, S25 | |
| 9 | Thêm/sửa khách, ghi chú | A POST `clients`, PUT `client/<id>`, POST `client/<id>/notes` | |
| 10 | Căn hợp với khách | S09 | Chưa thấy API riêng; dựng được từ `listings` kèm tham số lọc theo yêu cầu khách [ý kiến, chưa thử] |
| **Nhóm 3. Lịch xem** | | | |
| 11 | Lịch xem | B, A `viewings`, T | |
| 12 | Đặt lịch xem | A POST `viewings` | |
| **Nhóm 4. Hoa hồng** | | | |
| 13 | Hoa hồng theo tháng | B, A `deals`, T, S17 | |
| 14 | Ghi nhận hoa hồng | A POST `deals` | |
| **Nhóm 5. Chia sẻ** | | | |
| 15 | Tạo trang chia sẻ (chọn nhiều căn) | A POST `share`, S05 | |
| 16 | Các trang đã chia sẻ (lượt xem, lượt đặt lịch) | A `shares`, T | |
| 17 | Trang công khai `/s/<token>` | `server.py` (không đăng nhập) | Khách xem, không thuộc mini app; chỉ là đích |
| **Nhóm 6. Liên kết broker** | | | |
| 18 | Yêu cầu từ broker khác | B `menu:match`, A `xbroker`, T | Tôi **chưa đọc `feat_match.py`** nên chưa chắc nút bot và trang `xbroker` là một chức năng |
| 19 | Đề xuất căn cho một yêu cầu | A `propose/<id>` (GET, POST), T | |
| 20 | Xuất tin liên broker | S06 | Chưa thấy API |
| **Nhóm 7. Tài khoản** | | | |
| 21 | Hồ sơ broker, điểm uy tín | B, A `profile`, T, S18 | |
| 22 | Cài đặt thông báo | A `notify/prefs`, T, S02 | |
| 23 | Nâng cấp gói | B `menu:premium`, A POST `premium/request`, T, S21 | |
| 24 | Giới thiệu bạn | A `referral` | Không có màn vẽ |
| **Nhóm 8. Công cụ và trợ giúp** | | | |
| 25 | Mẫu tin nhắn | B `menu:templates` | Chưa có API |
| 26 | Bộ marketing | S07, S22 | Chưa có API |
| 27 | Hướng dẫn | B `menu:help` | Nội dung tĩnh |
| **Nhóm 9. Quản trị** | | | |
| 28 | Báo cáo quản trị | A `admin/reports` | Chỉ tài khoản quản trị thấy; không hiện trên trang chính cho người khác |

**28 điểm đến, 9 nhóm.** Không tính là điểm đến: cổng dùng thử (`trial/<feature>`), đổi trạng thái căn (`PUT listing/<id>/status`) và làm mới căn (`POST listing/<id>/refresh`): đây là hành động, không phải màn.

Ghi chú trung thực: các trang T (nhánh Tana) hiện dùng Tailwind từ CDN và `tabs.js` đưa `init_data` lẫn `tg_user_id` lên URL [đã xác minh bằng `git show origin/ui-broker-flow:webapp/static/v2/tabs.js`]; vì vậy chúng chỉ dùng làm danh mục chức năng, phải viết lại theo `tokens.css` + `api.js` chứ không nhập nguyên.

---

## 3. Bản đồ màn hình

### 3.1 Cây

```
Trang chính (hub)                     /v2/                     startapp=h
│  [Hôm nay] [3 lối tắt] [các dòng mục]
│
├─ Căn hộ                             /v2/listings             l
│   ├─ Chi tiết căn                   /v2/listings/<id>        l_<id>
│   │   ├─ Sửa căn                    /v2/listings/<id>/edit
│   │   └─ Bài đăng                   /v2/listings/<id>/post
│   ├─ Thêm căn                       /v2/listings/new         new_l
│   └─ (Bộ lọc = sheet trong trang)
├─ Khách                              /v2/clients              c
│   ├─ Chi tiết khách                 /v2/clients/<id>         c_<id>
│   │   ├─ Căn hợp với khách          /v2/clients/<id>/matches
│   │   └─ Sửa khách / ghi chú
│   └─ Thêm khách                     /v2/clients/new          new_c
├─ Lịch xem                           /v2/viewings             v
│   └─ Đặt lịch xem                   /v2/viewings/new         new_v
├─ Hoa hồng                           /v2/deals                d
│   └─ Ghi nhận hoa hồng              /v2/deals/new
├─ Trang đã chia sẻ                   /v2/shares               s
│   └─ (Tạo trang chia sẻ)            /v2/shares/new           (từ chọn nhiều căn)
├─ Liên kết broker                    /v2/xbroker              x
│   └─ Đề xuất căn                    /v2/xbroker/<req>        x_<req>
├─ Công cụ                            /v2/tools
│   ├─ Mẫu tin nhắn                   /v2/tools/templates
│   └─ Bộ marketing                   /v2/tools/marketing
├─ Hồ sơ và gói dịch vụ               /v2/profile              p
│   ├─ Cài đặt thông báo              /v2/profile/notifications
│   ├─ Nâng cấp gói                   /v2/profile/upgrade
│   └─ Giới thiệu bạn                 /v2/profile/referral
├─ Hướng dẫn                          /v2/help
└─ (quản trị, ẩn với người thường)    /v2/admin
```

Đích ngoài mini app: `/s/<token>` (trang công khai cho khách, đã có).

**Quy tắc chạm:** trang chính, trang con, trang chi tiết = 3 tầng. "Chạm" = số lần bấm để màn của hành động hiện ra (form, bộ chọn chat, hộp xác nhận); chạm chọn trong hộp của Telegram không tính.

### 3.2 Tại sao 9 dòng chứ không 28

Trang chính chỉ liệt kê 7 mục + 2 dòng phụ (Hồ sơ, Hướng dẫn) = 9 dòng. Các màn như Bộ lọc, Sửa, Đặt lịch xem không thành dòng riêng vì chúng là hành động của một mục. Con số này cùng cỡ số dòng của danh sách "Settings" trong ảnh BotFather (6 dòng) [nguồn: ảnh chủ dự án].

### 3.3 Độ sâu tới hành động thường dùng

Danh sách "thường dùng" là **[ý kiến]** của tôi từ cấu trúc menu bot, chưa có số liệu tần suất (DB thật mới có 1 môi giới).

| # | Hành động | Đường đi | Chạm |
|---|---|---|---|
| 1 | Xem lịch hôm nay | Nằm sẵn trên trang chính | 0 |
| 2 | Mở một buổi xem hôm nay | Bấm dòng ở "Hôm nay" | 1 |
| 3 | Mở khách cần theo dõi | Bấm dòng ở "Hôm nay" | 1 |
| 4 | Thêm căn | Lối tắt "Thêm căn" | 1 |
| 5 | Thêm khách | Lối tắt "Thêm khách" | 1 |
| 6 | Đặt lịch xem (không gắn căn) | Lối tắt "Đặt lịch xem" | 1 |
| 7 | Gọi chủ nhà một căn | Căn hộ, rồi nút Gọi trên thẻ | 2 |
| 8 | Chia sẻ một căn cho khách | Căn hộ, rồi nút Chia sẻ trên thẻ | 2 |
| 9 | Đặt lịch xem cho một căn | Căn hộ, rồi nút Đặt lịch trên thẻ | 2 |
| 10 | Đổi trạng thái căn (đã thuê / còn trống) | Căn hộ, rồi chạm nhãn trạng thái trên thẻ để mở hộp chọn | 2 |
| 11 | Xem hoa hồng tháng này | Hoa hồng | 1 |
| 12 | Trả lời yêu cầu liên broker | Liên kết broker (huy hiệu số đang chờ), rồi bấm yêu cầu | 2 |
| 13 | Căn hợp với một khách | Khách, rồi nút trên thẻ khách | 2 |

Ít dùng, 3 chạm: sửa căn (Căn hộ, thẻ, Sửa), mở/sửa bài đăng, thêm ghi chú cho khách (Khách, thẻ, ô ghi chú). Chọn nhiều căn rồi gửi: 1 chạm vào Căn hộ + chạm chọn từng căn + 1 chạm MainButton.

**Độ sâu tối đa tới hành động thường dùng: 2 chạm.** Điều kiện: nút Gọi/Chia sẻ/Đặt lịch/trạng thái có ngay trên thẻ (như `UI/Main.dc.html`); nếu bị chuyển vào trong màn chi tiết thì thành 3.

---

## 4. Nội dung trang chính

Mockup: `nav-mockups/01-hub.html`, ảnh `01-hub.png`.

Thứ tự từ trên xuống: (1) "Hôm nay"; (2) ba lối tắt; (3) ba cụm dòng mục; (4) chân trang `@truenest_bot`. Cụm dòng theo mẫu BotFather: dòng nối liền, bo góc ở cụm, icon nét mảnh + nhãn + `›` [nguồn: ảnh chủ dự án]. Không có thanh dưới, không có nút nổi, không có MainButton.

Cụm 1: Căn hộ, Khách, Lịch xem, Hoa hồng (bốn mục dùng hằng ngày). Cụm 2: Trang đã chia sẻ, Liên kết broker, Công cụ. Cụm 3: Hồ sơ và gói dịch vụ, Hướng dẫn. Thứ tự này là [ý kiến], dựa trên thứ tự menu bot hiện tại.

### Phần "Hôm nay": đo được gì từ API có sẵn

| Khối | API có sẵn | Làm được ngay? | Còn thiếu |
|---|---|---|---|
| Lịch xem hôm nay | `GET /api/viewings` | **Một phần.** [đã xác minh `db.list_viewings`] chỉ trả buổi có trạng thái `scheduled` và `scheduled_at >=` bây giờ, tối đa 50. Hệ quả: buổi 10:00 **biến khỏi khối "hôm nay" lúc 10:01**, kể cả khi đang diễn ra. Hàm DB đã có tham số `upcoming_only=False` nhưng route không lộ ra | Tham số ngày (`?date=YYYY-MM-DD`) hoặc `?upcoming=0`. Ngày phải tính theo giờ Việt Nam; máy chủ chạy ở Calgary, `scheduled_at` là epoch nên so ở giờ Asia/Ho_Chi_Minh |
| Khách cần theo dõi | `GET /api/clients` | **Dựng tạm được.** Trả `urgency` (urgent/normal/low), `status`, `updated_at`, đã xếp "khẩn trước" [đã xác minh `db.list_clients`]. Luật tạm: `urgency = urgent`, hoặc trạng thái đang mở mà `updated_at` quá N ngày. **N chưa đo; tôi đặt 5 [giả định]** | Trường "hẹn liên hệ lại" (`follow_up_at`): không có. Không có nó thì "cần theo dõi" chỉ là xấp xỉ. Danh sách giới hạn cứng 100 khách |
| Căn cần làm mới | `GET /api/listings`, `GET /api/profile` | **Không.** `listing_summary` không trả `updated_at`; hàm tính độ cũ `freshness_info` chỉ nằm trong luồng `propose`. `profile` trả `fresh_listings` nhưng **không trả tổng**, và `stats.active_listings` đếm `submitted` còn điểm uy tín đếm 4 trạng thái (`draft`, `pending_info`, `submitted`, `uncertain`) nên không trừ ra được số "quá hạn" [đã xác minh] | Thêm `updated_at`/`age_days` vào `listing_summary`, hoặc số đếm "quá 7 ngày" (`FRESHNESS_WINDOW_DAYS = 7` trong `utils.py`) |

**Đề xuất [ý kiến]:** thêm một route `GET /api/today` gom ba khối trong một lượt gọi (ba lượt gọi riêng làm trang chính chậm hơn; **chưa đo**). Gate ở mục 10. Cho tới khi có route này, trang chính vẫn mở được: khối thiếu API hiện "chưa có dữ liệu" chứ không bịa số.

Số đếm trên dòng mục (12 căn, 7 khách) trong mockup chỉ là mẫu. Muốn có thật cần thêm số đếm vào `/api/today` hoặc gọi thêm 4 API; bản đầu có thể bỏ số, chỉ giữ huy hiệu "Liên kết broker" (yêu cầu đang chờ) khi API có.

---

## 5. Từng trang: nút gốc, MainButton, URL, deep link

Quy ước [ý kiến, theo mẫu BotFather và `tài liệu nghiên cứu` 1.3]: **BackButton hiện ở mọi trang trừ trang chính. Trang danh sách không có MainButton**: hành động thêm nằm trong nội dung (nút "Thêm căn" cạnh số đếm), đúng kiểu Copy/Revoke của BotFather. **MainButton chỉ ở trang chi tiết và form**, đúng một hành động chính. SecondaryButton chỉ khi có hành động phụ thật sự đi đôi. SettingsButton: một nút duy nhất, dẫn tới "Hồ sơ và gói dịch vụ".

Phụ thuộc phiên bản [nguồn: tài liệu nghiên cứu 1.3]: SecondaryButton cần Bot API 7.10, SettingsButton 7.0 (và mục "Settings" phải bật trong BotFather). Mọi nút phải qua `isVersionAtLeast`; nếu thiếu thì chuyển thành nút trong nội dung. Vì vậy trang chính luôn có dòng "Hồ sơ và gói dịch vụ", không chỉ dựa vào SettingsButton.

| Trang | URL web | startapp | Back | MainButton | SecondaryButton |
|---|---|---|---|---|---|
| Trang chính | `/v2/` | `h` | ẩn | ẩn | ẩn |
| Căn hộ (danh sách) | `/v2/listings` | `l` | hiện | ẩn. Khi đang chọn nhiều căn: "Gửi N căn cho khách" | ẩn |
| Chi tiết căn | `/v2/listings/<id>` | `l_<id>` | hiện | "Gửi cho khách" | "Đặt lịch xem" |
| Sửa căn | `.../<id>/edit` | không | hiện | "Lưu thay đổi" (tắt khi chưa đổi gì) | ẩn |
| Thêm căn | `/v2/listings/new` | `new_l` | hiện | "Lưu căn" | ẩn |
| Bài đăng | `.../<id>/post` | không | hiện | "Lưu bài đăng" | "Sao chép" |
| Khách (danh sách) | `/v2/clients` | `c` | hiện | ẩn | ẩn |
| Chi tiết khách | `/v2/clients/<id>` | `c_<id>` | hiện | "Căn hợp với khách" | "Đặt lịch xem" |
| Căn hợp với khách | `.../<id>/matches` | không | hiện | "Gửi N căn đã chọn" | ẩn |
| Thêm/sửa khách | `/v2/clients/new` | `new_c` | hiện | "Lưu khách" | ẩn |
| Lịch xem | `/v2/viewings` | `v` | hiện | ẩn | ẩn |
| Đặt lịch xem | `/v2/viewings/new` | `new_v` | hiện | "Đặt lịch" | ẩn |
| Hoa hồng | `/v2/deals` | `d` | hiện | ẩn | ẩn |
| Ghi nhận hoa hồng | `/v2/deals/new` | không | hiện | "Lưu hoa hồng" | ẩn |
| Trang đã chia sẻ | `/v2/shares` | `s` | hiện | ẩn | ẩn |
| Liên kết broker | `/v2/xbroker` | `x` | hiện | ẩn | ẩn |
| Đề xuất căn | `/v2/xbroker/<req>` | `x_<req>` | hiện | "Gửi đề xuất (N căn)" | ẩn |
| Công cụ | `/v2/tools` | không | hiện | ẩn | ẩn |
| Hồ sơ | `/v2/profile` | `p` | hiện | "Lưu" chỉ khi có thay đổi | ẩn |
| Cài đặt thông báo | `.../notifications` | không | hiện | ẩn (công tắc lưu ngay) | ẩn |
| Nâng cấp gói | `.../upgrade` | không | hiện | "Gửi yêu cầu nâng cấp" | ẩn |
| Hướng dẫn | `/v2/help` | không | hiện | ẩn | ẩn |

Ghi chú:
- **startapp:** chuỗi ngắn, chỉ chữ thường, số, gạch dưới (an toàn nhất) [ý kiến]; giới hạn thật của Telegram **chưa có nguồn** (trang tài liệu không nêu, xác nhận ở mục 1). `<id>` là id căn/khách hiện có trong DB; tôi chưa kiểm định dạng id nên chưa biết nó có ký tự lạ không [chưa kiểm]. Theo `CLAUDE.md` A5, `start_param` chỉ để mở màn; quyền sở hữu căn/khách vẫn kiểm ở máy chủ.
- **URL web:** hôm nay máy chủ chỉ trả trang cho `/v2/` và tệp tĩnh [đã xác minh `server.py` dòng 159]; đường dẫn sâu như `/v2/listings/<id>` cần máy chủ trả lại cùng trang vào (fallback), xem việc W1 ở mục 10. Trong Telegram dùng cùng bộ đường dẫn qua router phía trình duyệt nên cùng mã chạy được trên web sau này.
- **Mockup chi tiết căn:** `nav-mockups/03-listing-detail.html`. Khung sọc xám "Telegram vẽ" là thanh nút đáy do Telegram vẽ (Secondary trái, Main phải). Vì không có thanh tab dưới nên không còn cảnh hai thanh đáy chồng nhau, và không bao giờ có ba thanh (đúng luật A3 cũ ở phần "ba thanh đáy").
- **MainButton cho từng việc** nhất quán một quy tắc: động từ + đối tượng, cùng chữ với kết quả sau đó ("Lưu khách" rồi thông báo "Đã lưu khách").

---

## 6. Lối tắt chéo

Mục đích: bù cái giá 2 chạm khi chuyển giữa các mục.

| Từ | Tới | Cách |
|---|---|---|
| Thẻ khách / chi tiết khách | Căn hợp với khách | Nút trên thẻ; MainButton ở chi tiết khách |
| Thẻ căn / chi tiết căn | Gửi cho khách | Nút Chia sẻ trên thẻ; MainButton ở chi tiết căn |
| Chi tiết căn | Khách hợp với căn này | Dòng `›` dưới các ô nút (có trong mockup) |
| Chi tiết căn | Đặt lịch xem | SecondaryButton; điền sẵn căn |
| Chi tiết khách | Đặt lịch xem | SecondaryButton; điền sẵn khách |
| Buổi xem (trang chính, danh sách lịch) | Chi tiết khách | Bấm dòng |
| Trang Hoa hồng, ghi nhận | Chọn khách và căn | Ô chọn có tìm kiếm, mở từ danh sách đã có |
| Chi tiết khách | Trang đã chia sẻ cho khách này | `shares` có `client_id` [đã xác minh `list_shares`]; lọc theo khách |
| Trang chia sẻ đã tạo | Chi tiết căn | Bấm căn trong trang |

Lối tắt ở trang chính (Thêm căn, Thêm khách, Đặt lịch xem) là ba hành động cho 1 chạm. Chọn ba thứ này là [ý kiến]; **chưa có tần suất để biết có phải ba hành động hay dùng nhất**.

Giữ BackButton đơn giản: bấm Quay lại luôn về đúng trang vừa đứng (ngăn xếp), kể cả khi tới từ lối tắt chéo. Telegram không tự quản ngăn xếp; app tự quản [chưa có nguồn, suy từ API chỉ có `show/hide/onClick`].

---

## 7. Bốn trạng thái mỗi trang danh sách

Mockup: `nav-mockups/04-list-states.html`, ảnh `04-list-states.png` và `04-state-1..4.png`. Áp cho 9 danh sách: Căn hộ, Khách, Lịch xem, Hoa hồng, Trang đã chia sẻ, Liên kết broker, Mẫu tin nhắn, Hôm nay (từng khối), Căn hợp với khách.

| Trạng thái | Hiển thị | Hành động | Lời |
|---|---|---|---|
| Đang tải | 3 thẻ xám nhấp nháy (skeleton) đúng hình thẻ; ô tìm vẫn hiện. Tắt nhấp nháy khi `prefers-reduced-motion` | không | không chữ |
| Rỗng | Icon + tiêu đề + một câu chỉ cách thêm | Nút thêm đúng mục ("Thêm căn", "Thêm khách"...) | "Chưa có căn nào" / "Thêm căn đầu tiên bằng cách gửi tin cho bot, hoặc nhập trực tiếp tại đây." |
| Lỗi mạng | Icon cảnh báo + câu nói rõ cái gì xảy ra | "Thử lại" (gọi lại cùng API) | "Không tải được danh sách" / "Kiểm tra kết nối mạng rồi thử lại. Dữ liệu của bạn không bị mất." |
| Hết phiên (401) | Icon khoá + hướng dẫn | **Không có nút Thử lại** (xem dưới) | "Phiên đã hết hạn" / "Đóng ứng dụng bằng nút X ở góc trên, rồi mở lại từ bot." |

Quyết định cho 401: `initData` là chuỗi cố định lúc mở app và máy chủ từ chối khi `auth_date` quá hạn (CLAUDE.md A5), nên gọi lại với cùng chuỗi sẽ vẫn 401; "Thử lại" ở đây vô ích. Cách chắc chắn là mở lại app từ bot. Tôi **không tự vẽ nút Đóng** (CLAUDE.md A3); chỉ chỉ vào nút X của Telegram. Điều **chưa kiểm**: Telegram có cấp `initData` mới khi người dùng chỉ vuốt xuống làm mới hay phải mở lại hẳn; nếu có thì có thể thêm tự phục hồi. Phải thử trên máy thật.

Lỗi mạng và 401 phải phân biệt được ở `api.js` (lớp `ApiError` có `status`) [đã xác minh trong tài liệu nghiên cứu 3.2]. Lỗi riêng từng khối ở "Hôm nay": mỗi khối tự hiện trạng thái của nó, lỗi một khối không làm hỏng cả trang.

---

## 8. So sánh ba phương án

### 8.1 Bảng

| Tiêu chí | Tab dưới (hiện tại) | Trang chính + trang con (hub) | Lai: hub + lối tắt (đề xuất) |
|---|---|---|---|
| Số điểm đến chứa được | 4–5 (tài liệu nghiên cứu 2.1: thêm mục thứ 5 là hết chỗ). 28 điểm đến: 20+ không có chỗ | 28 (qua 9 dòng) | 28 |
| Chuyển giữa hai mục chính | 1 chạm | 2 chạm (Quay lại rồi vào) | 1–2 chạm (lối tắt chéo; mục 6) |
| Vào hành động thường dùng từ lúc mở app | 1–2 chạm cho 4 mục trên tab; các mục còn lại phải đi vòng qua tab "Thêm" (S14 đã vẽ tab "Thêm") | ≤ 2 chạm (mục 3.3) | ≤ 2 chạm, nhiều hành động 1 chạm |
| Cho người mới biết app có gì | Chỉ 4 nhãn tab; phần còn lại giấu | Thấy hết danh sách ngay | Thấy hết, kèm "Hôm nay" |
| Hợp với luật nút gốc (A3) | Dễ vi phạm: tab dưới + MainButton + nút nổi (ba thanh đáy; nay phải ẩn tab mỗi khi MainButton hiện) | Hợp: không có thanh đáy tự vẽ, MainButton một mình | Hợp |
| Hợp mẫu BotFather | Không (BotFather không có tab dưới) [nguồn: ảnh chủ dự án] | Có | Có, thêm "Hôm nay" |
| Chỗ cho nội dung "Hôm nay" | Phải ép vào một tab | Là chính trang chính | Là chính trang chính |
| Rủi ro | Phải tắt/hiện tab theo MainButton; mất chiều cao đáy (64px + safe-area) | Mỗi lần đổi mục tốn thêm 1 chạm; người dùng thành thạo có thể thấy chậm | Như hub, nhẹ hơn nhờ lối tắt; thêm việc dựng lối tắt |
| Chi phí dựng | Đã có `tabs.js` (nhưng vi phạm A5: `init_data` trên URL) | Cần router + bản đồ trang | Hub + router + 6–9 lối tắt |
| Lên web/PWA | Tab dưới quen thuộc | Dựng bằng đường dẫn URL (mục 5), dễ sao ra web | Như hub |

### 8.2 Tại sao đề xuất lai

Hub thuần đẹp về nhất quán nhưng tốn 1 chạm mỗi lần đổi mục; lối tắt chéo là phần rẻ nhất để giảm chi phí đó mà không phải dựng lại thanh tab. Tôi **không** đề xuất "hub + tab dưới" vì nó quay lại đúng vấn đề ba thanh đáy.

### 8.3 Chưa đo được (phải ghi rõ)

- **Tần suất chuyển mục.** Không có số liệu: DB thật mới có 1 môi giới. Nên đo sau 2 tuần có 5+ người dùng: số lần Quay lại về trang chính rồi vào mục khác, trong một phiên mở app. Ngưỡng cần đặt trước khi đo (ví dụ: nếu trung bình > 3 lần chuyển mục cùng cấp mỗi phiên thì thêm tab, hoặc đưa ra lối tắt) **[giả định, chưa có cơ sở]**.
- **Danh sách "hành động thường dùng"** (mục 3.3) là ý kiến của tôi, chưa đối chiếu với thói quen thật.
- **Mức chậm của trang chính** khi gọi 3 API (hoặc `/api/today`): chưa đo.
- **Mẫu BotFather có chịu được dùng nhiều lần mỗi ngày không**: chưa có bằng chứng.
- **Hành vi BackButton** trên iOS/Android/Desktop (kể cả cử chỉ vuốt cạnh để quay lại): chưa thử.
- **Độ cao thẻ và số thẻ thấy được trên màn nhỏ** (360×640): chưa đo.

---

## 9. Đề xuất sửa `CLAUDE.md` (điều phối áp)

**A3 hiện tại** có câu: "MainButton cho đúng một hành động chính của màn chi tiết/form; khi MainButton hiện thì ẩn tab dưới. Không bao giờ để ba thanh đáy (FAB + tab dưới + MainButton) cùng lúc."

**Đề xuất thay A3 bằng:**

> 3. **Điều hướng và nút gốc của Telegram.** Cấu trúc là **trang chính (hub) → trang con → trang chi tiết**, không có thanh tab dưới. Trang chính liệt kê các mục bằng danh sách dòng có mũi tên `›`, kèm phần "Hôm nay" và vài lối tắt. Màn con dùng BackButton; không tự vẽ nút Quay lại/Đóng khi chạy trong Telegram (bỏ khỏi mã, không chỉ ẩn). BackButton luôn ẩn ở trang chính. MainButton cho đúng **một** hành động chính của trang chi tiết/form (động từ + đối tượng); trang danh sách và trang chính không dùng MainButton, hành động thêm đặt trong nội dung. SecondaryButton và SettingsButton phải qua `isVersionAtLeast` và có nút thay trong nội dung khi thiếu. Không có thanh đáy tự vẽ nào (kể cả nút nổi), để không bao giờ chồng với MainButton. Mọi hành động thường dùng phải đạt được trong ≤ 2 chạm từ trang chính; hành động mới thêm vào phải ghi độ sâu vào bản đồ trang trong `docs/design/`.

**Thêm vào B (mặc định):**

> 16. **Mỗi trang có đường dẫn URL** (`/v2/...`) và, nếu mở trực tiếp được, một mã `startapp` ngắn chỉ gồm chữ thường, số, gạch dưới. Router không đọc `window.Telegram`/`location` ngoài lớp bọc nền tảng. `start_param` chỉ để chọn màn mở; quyền kiểm ở máy chủ.

**Thêm vào C (chưa có nguồn):** giới hạn độ dài của `startapp` đã có; thêm "cử chỉ vuốt cạnh quay lại và hành vi BackButton trên ba nền tảng"; "Telegram có cấp initData mới khi mở lại hay không".

**Thêm vào Cổng kiểm:** "Với mỗi màn mới, cập nhật bản đồ trang; đếm số chạm từ trang chính tới mọi hành động thường dùng, không có hành động nào > 2." và "Không còn phần tử `nav`/tab dưới tự vẽ trong tệp giao diện."

**Cần sửa cho khớp trong `docs/research/tma-design-2026-10-17.md`** (tài liệu của phiên C, không thuộc tuyến của tôi): mục 0 ý 4 ("tab dưới tự vẽ chỉ cho 4 mục cấp một"), mục 1.3 (quy ước BackButton ẩn ở "màn gốc của từng tab"), mục 2.1 (toàn bộ), mục 2.5 hàng "FAB + tab dưới" và "Tab dưới 4 mục". Các chỗ này mâu thuẫn với điều hướng mới. Phần FAB ở mục 2.1 ("ở màn danh sách chọn FAB") cũng không còn: tôi thay bằng nút "Thêm căn" trong nội dung, vì không còn tab dưới để FAB nổi trên đó, và để tránh một thanh đáy nữa [ý kiến].

---

## 10. Việc dựng code tiếp theo, kèm cổng kiểm

Thứ tự theo phụ thuộc. Đã có gate chung của `CLAUDE.md` (không hex, không `window.Telegram`/`fetch` ngoài lớp bọc, ảnh 390px, thử máy thật) áp cho mọi việc.

| # | Việc | Cổng kiểm |
|---|---|---|
| W1 | Máy chủ: trả lại trang vào cho `/v2/*` (fallback), thêm MIME `.woff2`/`.webp` | `curl` `/v2/listings/abc` trả 200 HTML; phông trả `font/woff2`; `/api/...` không bị ảnh hưởng |
| W2 | Lớp bọc nền tảng `platform.js`: back/main/secondary/settings, haptic, đều qua `isVersionAtLeast` với đường lùi | `grep` `window.Telegram` chỉ còn trong `platform.js`; mở trong Chrome thường vẫn thấy nút thay thế |
| W3 | Router theo đường dẫn + đồng bộ BackButton (ngăn xếp) | Từ chi tiết bấm Back về đúng danh sách, giữ bộ lọc và vị trí cuộn; ở trang chính BackButton ẩn; mở `/v2/listings/<id>` trực tiếp thì Back về hub |
| W4 | `GET /api/today` (lịch hôm nay gồm cả buổi đã qua giờ; khách cần theo dõi; số căn quá 7 ngày) | Số khớp từng API riêng trên cùng dữ liệu; buổi 10:00 vẫn hiện lúc 10:30; ngày tính theo giờ Việt Nam (test với giờ máy khác múi) |
| W5 | Trang chính theo `01-hub.html` | Ảnh 390px khớp mockup; có đủ 4 trạng thái cho từng khối; không có thanh đáy; tab không còn trong mã |
| W6 | Chuyển `listings.html` hiện có sang vai "Căn hộ": bỏ header Quay lại/Đóng tự vẽ, bỏ tab, bỏ nút nổi, thêm nút "Thêm căn" trong nội dung | Gate hex; không còn `design-nav-btn`; thử máy thật (an toàn vùng) |
| W7 | Viết lại trang khách/lịch xem/hoa hồng/chia sẻ/xbroker/hồ sơ/cài đặt/nâng cấp theo `tokens.css` + `api.js` (lấy chức năng từ nhánh Tana, không chép mã) | Không còn `init_data`/`tg_user_id` trên URL; không Tailwind CDN; từng trang qua gate hex |
| W8 | Bốn trạng thái cho mọi danh sách | Giả lập: tắt mạng, trả 401, trả danh sách rỗng, trì hoãn phản hồi; ảnh 4 trạng thái cạnh `UI/Main.dc.html` |
| W9 | Lối tắt chéo (mục 6) | Mỗi lối tắt điền sẵn đúng đối tượng; đếm chạm khớp bảng 3.3 |
| W10 | Nhận `startapp`, mở màn tương ứng | Mở bằng link `t.me/<bot>?startapp=l_<id>` trên máy thật; id không thuộc môi giới thì máy chủ từ chối (404/403), không lộ dữ liệu |
| W11 | API còn thiếu: tạo căn, tham số ngày cho viewings, `updated_at` trong listing, `follow_up_at` cho khách | Mỗi API có test và kiểm quyền sở hữu |
| W12 | Đo sau 2 tuần (mục 8.3): sự kiện chuyển mục, thời gian mở trang chính | Có số trước khi quyết định thêm tab hay giữ hub |

Ưu tiên thấp (không chặn): bản `Thêm căn` qua form web (cần W11); `Công cụ`, `Hướng dẫn` (chưa có API, nội dung tĩnh).

---

## 11. Tệp kèm theo (`docs/design/nav-mockups/`)

- `01-hub.html`, `02-listings.html`, `03-listing-detail.html`, `04-list-states.html`, `nav.css` (không có mã hex; mọi giá trị qua biến của `webapp/static/v2/tokens.css`).
- Ảnh 390px (nhân đôi mật độ): `01-hub.png`, `02-listings.png`, `03-listing-detail.png`, `04-state-1..4.png`; `04-list-states.png` là ảnh ghép bốn trạng thái.
- Khung sọc xám có nhãn "Telegram vẽ" = phần Telegram vẽ (header, nút Main/Secondary). Mọi thứ còn lại là phần ta vẽ.
- Giới hạn của mockup: chỉ có chủ đề tối (tokens chưa có theme sáng, đã nêu ở tài liệu nghiên cứu 3.2); ảnh căn là khung giả; số liệu và tên là mẫu.
