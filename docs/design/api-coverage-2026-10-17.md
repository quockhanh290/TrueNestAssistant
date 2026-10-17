# Bảng phủ API cho mini app TrueNest (17/10/2026)

Người viết: phiên P. Chỉ đọc code và chạy thử một bản webapp riêng ở cổng 8096 trên **bản sao** cơ sở dữ liệu (đã tắt); không sửa code, không commit.
Mốc code: commit `7460af4`. Giờ máy lúc viết: 04:29 sáng 17/10 giờ Calgary (MDT), tức 17:29 chiều 17/10 giờ Việt Nam.

Nhãn dùng trong tài liệu:
- **[đo]**: tôi đã chạy thật trên bản sao và thấy kết quả;
- **[đọc]**: tôi đã đọc đúng dòng code;
- **[báo cáo phụ]**: một trợ lý con đọc giúp, tôi đã kiểm lại vài chỗ (ghi rõ chỗ nào đã kiểm);
- **[chưa kiểm]**: chưa ai đọc hoặc chưa ai chạy.

Mục tiêu của chủ dự án: **nối toàn bộ back end**. Nghĩa là không màn nào còn là trang "làm qua bot", không nút nào chết, không con số nào bịa. Tài liệu này là đặc tả để phiên dựng làm theo, chưa phải code.

---

## 0. Tóm tắt bằng số

| Đo cái gì | Kết quả |
|---|---|
| Đường API cần đăng nhập đang có trong máy chủ | **31** (16 đọc, 6 sửa, 9 ghi mới). Ngoài ra có 1 đường kiểm sống và 3 đường công khai cho trang chia sẻ của khách [đọc server.py:256–402] |
| Số đường bản giao diện v2 hiện tại thực sự gọi | **15/31** (13 đọc, 2 ghi: đặt lịch xem và tạo trang chia sẻ) [đọc api2.js:71–112] |
| Số đường đã có nhưng v2 không dùng | **16**: sửa căn, đổi trạng thái căn, làm mới căn, xem/sửa bài đăng ở mọi ngôn ngữ, thêm khách, sửa khách, thêm ghi chú, ghi hoa hồng, sửa hồ sơ, bật/tắt thông báo, xin nâng cấp, đề xuất căn liên broker (xem và gửi), lượt thử (xem và trừ), báo cáo cho quản trị |
| Đường mới cần thêm (đề xuất ở mục 2) | **19**, cộng 1 đường thay thế tuỳ quyết định về ảnh |
| Đường có sẵn cần mở rộng trường hoặc tham số | **11** |
| Lỗi chung của máy chủ phải sửa trước khi nối thêm | **9** (mục 3, nhóm A) |
| Lỗi dữ liệu đã đo trên bản sao | 3/3 căn có **0 ảnh dùng được trên web**, dù mỗi căn có 7 ảnh trong Telegram; 3/3 căn có **cùng một mốc "cập nhật"** đến từng giây |
| Màn trong v2 hiện vẫn là trang "làm qua bot" | **5**: Thêm căn, Thêm khách, Đặt lịch xem (trang riêng), Công cụ, Hướng dẫn. Ngoài ra còn 8 màn trong bản đồ trang chưa có trang nào (mục 1) |

Dữ liệu trong bản sao rất nhỏ: 2 broker, 3 căn, 0 khách, 0 lịch xem, 0 hoa hồng, 0 trang chia sẻ. Vì vậy mọi phép đo về luồng khách, lịch, hoa hồng đều là tôi **tự tạo dữ liệu trên bản sao** rồi gọi đường API, không phải quan sát dữ liệu thật.

Ba phát hiện đổi cách làm (chi tiết ở mục 3):
1. **Broker này ghi được vào khách của broker khác** [đo]. Một broker đặt được lịch xem và ghi được khoản hoa hồng gắn vào mã khách của broker khác, và máy chủ trả "thành công". Lý do: tầng cơ sở dữ liệu không lọc theo chủ ở bất kỳ hàm đọc/sửa theo mã nào [báo cáo phụ, đã kiểm `update_viewing`, `set_listing_status`, `mark_deal_paid`]. Hai đường ghi lịch và ghi hoa hồng cũng không tự kiểm.
2. **Cờ "đã thanh toán" của hoa hồng không có nghĩa là broker đã nhận tiền.** Nó nghĩa là **broker đã trả phí sàn 20% cho TrueNest** và quản trị đã xác nhận biên lai [đọc feat_payment.py:36–52, db/deals.py:100–121]. Màn Hoa hồng hiện cộng các khoản đó vào ô "Đã nhận tháng này", tức là đang hiện sai nghĩa. Thêm nữa: một khoản ghi từ web mà chưa trả phí sẽ thành **công nợ**, và công nợ **chặn broker giữ chỗ liên broker** [đọc feat_match.py:991]. Web hiện không gửi hướng dẫn chuyển khoản nào kèm theo.
3. **Ảnh không lên web vì đường dẫn công cụ tải ảnh trỏ vào một tệp không tồn tại trên máy này** [đo: tệp `~/workspace/custom-connectors/custom.legacy-cloudflare/bin/cf.py` mà photos.py:25 trỏ tới không có]. Lỗi này không do API: bot tải ảnh lên kho ảnh thất bại một cách im lặng, nên cột link ảnh của căn trống.

---

## 1. Bảng theo màn

Danh sách màn lấy theo `claude-design-prompts-2026-10-17.md` mục 2 (22 màn). Cột "Stitch" ghi màn mẫu tương ứng trong `stitch_ui/screens/` (bỏ 07 và 22 vì là đồ marketing). Nội dung của các màn Stitch có rất nhiều tính năng **không có back end và không có kế hoạch** (thanh toán VietQR tự duyệt, chia hoa hồng 50/50, xác minh căn cước, đánh giá sao, ảnh 360°, đăng tự động lên Facebook...). Những thứ đó gom ở **mục 1.23**, không rải trong bảng, để phiên dựng không nối nhầm vào số bịa.

Cách đọc cột "Route":
- `GET /api/x` (dòng N) là đường đã có trong `webapp/server.py`;
- **THIẾU → Rk** là đường mới đề xuất ở mục 2;
- **MỞ RỘNG → Mk** là thêm trường hoặc tham số vào đường đã có (cũng ở mục 2).

### 1.1 Trang chính (Stitch: 14 một phần)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Ngày hôm nay (giờ Việt Nam) | `GET /api/today` (306) | `db.vntime` | có sẵn |
| Lịch xem hôm nay, kể cả buổi đã qua giờ, kèm tên căn | `GET /api/today` | `db.list_viewings_between` | có sẵn, đã chặn lộ tên căn/khách của người khác [đọc api.py:712–740] |
| Khách cần theo dõi (gấp, hoặc im quá 5 ngày) | `GET /api/today` | `db.followup_clients` | có sẵn |
| Số căn quá hạn làm mới | `GET /api/today` | `utils.FRESHNESS_WINDOW_DAYS` | có sẵn. Nhưng số này **đang sai trên dữ liệu thật**: cả 3 căn có cùng mốc cập nhật do một lần chạy script, không do broker xác nhận (mục 3, B4) |
| Số trên dòng mục (căn, khách, buổi sắp tới, yêu cầu liên broker) | `GET /api/today` → `counts` | | **MỞ RỘNG → M1**: số hiện bị chặn trần ở 200 căn, 100 khách, 50 buổi [đọc api.py:765–772]. Broker có 250 căn sẽ thấy "200" |
| Số trên dòng Hoa hồng ("tháng này") | THIẾU (chỉ là chữ) | `db.list_deals` | **MỞ RỘNG → M1**: thêm `deals_month_total`, nhưng chỉ sau khi chốt nghĩa "đã nhận" (Q2) |
| Ba lối tắt: Thêm căn, Thêm khách, Đặt lịch xem | dẫn tới 1.18, 1.17, 1.8 | | v2 hiện mở **trang chỉ dẫn qua bot** [đọc pages-static.js:18–30] |

### 1.2 Căn hộ: danh sách, bộ lọc, chọn nhiều (Stitch: 15, 20)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Danh sách căn và các trường của thẻ | `GET /api/listings` (258) | `db.list_broker_listings`, `db.search_listings`, `schema.quality_score` | có. Thẻ đã có `updated_at` [đọc api.py:75]; tài liệu prompt ghi "chưa có" là đã cũ |
| Ảnh nhỏ trên thẻ | `photo_urls` | `db.add_photo_url` | đường có, **dữ liệu rỗng** (mục 3, B2). Phải sửa ở bot, hoặc làm **R11/R12** |
| Tìm theo chữ | `?q=` | | chỉ tìm trong **tiêu đề** ghép (số phòng + toà/quận) [đọc api.py:185–187], không tìm địa chỉ hay giá. **MỞ RỘNG → M2** |
| Lọc: trạng thái, phòng ngủ, khu, giá, diện tích, nội thất, thú cưng, điểm tin | có đủ tham số | | Màn 15/20 có thêm lọc "ban công", "≥50 m²" (đã có `min_area`), "điểm ≥50/70/80" (đã có `min_score`). "Ban công" không có trường → bỏ |
| Đếm theo trạng thái (tất cả / trống / đã thuê) — màn 15 | THIẾU | | **MỞ RỘNG → M2**: trả `status_counts` |
| Tổng số căn | `total` | | bị chặn ở 200 vì máy chủ chỉ lấy 200 dòng trước khi lọc [đọc api.py:157–159] |
| Gọi chủ nhà | `GET /api/listing/<id>` → `phone` | | có (gọi thêm một lần mỗi khi bấm) |
| Chia sẻ một căn hoặc nhiều căn | `POST /api/share` (369) | `db.create_share_page` | có, nhưng sai luật B14 (mục 3, C1). Làm **R5** |
| Đặt lịch từ thẻ | `POST /api/viewings` (392) | `db.create_viewing` | có, nhưng không kiểm chủ (mục 3, A2) |
| Chạm nhãn trạng thái để đổi | `PUT /api/listing/<id>/status` (341) | `db.set_listing_status` | có, nhưng **nhận mọi chữ** (mục 3, A4) |
| Sửa / Bài đăng / Bổ sung trên thẻ (màn 15) | dẫn tới 1.19, 1.20 | | |

### 1.3 Chi tiết căn (Stitch: 04, 12)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Mọi trường thông tin, điểm tin và phần còn thiếu | `GET /api/listing/<id>` (284) | `schema.quality_score` | có. API gắn cứng `ai_scored: True` [đọc api.py:77, 106], trong khi điểm thật ra **tính theo bảng trọng số cố định**, không phải AI [đọc schema.py:173–185]. Giao diện không được ghi "điểm AI" |
| Bảng 11 tiêu chí điểm (màn 04) | `quality_missing` chỉ có phần thiếu | `schema.quality_breakdown` | **MỞ RỘNG → M3**: trả cả phần đã đạt (hàm `quality_breakdown` đã dùng ở đường đề xuất liên broker) |
| Nhiều ảnh, phóng to | `photo_urls` | | rỗng (mục 3, B2) |
| "Cập nhật X ngày trước" | `updated_at` | | có, nhưng dữ liệu đang giống nhau cho mọi căn (B4) |
| Gọi, Sửa, Bài đăng | `phone`; 1.19; 1.20 | | v2 có Gọi và Bài đăng (chỉ tiếng Việt). Chưa có Sửa |
| Làm mới (xác nhận còn trống / đã thuê) | `POST /api/listing/<id>/refresh` (381) | `db.refresh_listing`, `db.check_refresh_velocity` | có, v2 **chưa gọi** |
| Khách hợp với căn này (số và danh sách) | **THIẾU → R2** | `feat_match.score_match`, `db.list_clients` | |
| Gửi cho khách (MainButton) | `POST /api/share` | | chỉnh theo B14 → **R5** |
| Đặt lịch xem (SecondaryButton) | `POST /api/viewings` | | |
| Đổi trạng thái: còn trống / giữ chỗ / đã thuê | `PUT .../status` | | cần danh sách trạng thái hợp lệ (A4) |
| Xoá căn (màn 04, 12) | **THIẾU**, hiện lách được qua `PUT .../status` với "deleted" | `set_listing_status(id,"deleted")`, bot dùng ở feat_listings.py:473 | **MỞ RỘNG → M4**: cho phép "deleted" có chủ đích, hỏi lại bằng `showConfirm` (B12) |
| Phí điện/nước/wifi, toạ độ, cách biển 300 m, 360°, "Độc quyền", "Verified" | không có trường | | mục 1.23 |

### 1.4 Khách: danh sách (Stitch: 24)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Danh sách, khách gấp lên đầu | `GET /api/clients` (310) | `db.list_clients` | có, chặn trần 100 |
| Nhãn trạng thái | `status_vi` | | **sai từ vựng** (mục 3, B5): nhãn có "Đang tìm", "Đã liên hệ"... còn bot ghi "scheduled", "rented"... nên nhiều khách sẽ hiện chữ tiếng Anh thô |
| Chip lọc theo phễu, kèm số đếm mỗi bậc | `?status=` có; số đếm THIẾU | `db.count_clients` | **MỞ RỘNG → M5** |
| Tìm theo tên / số điện thoại | THIẾU | | **MỞ RỘNG → M5** (`?q=`) |
| Lịch hẹn gần nhất trên thẻ (màn 24) | THIẾU | `db.client_viewings` | **MỞ RỘNG → M5** (`next_viewing`) |
| Gọi | `phone` | | có |
| "Gợi ý tin (3)" / "Căn hợp" | **THIẾU → R1** | | |
| Thêm khách | `POST /api/clients` (385) | `db.create_client` | có, v2 chưa gọi |
| Nguồn khách (Facebook Ads, Zalo), VIP, hợp đồng số, nhắc tái ký, chat | không có | | mục 1.23 |

### 1.5 Chi tiết khách (Stitch: 25)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Nhu cầu, liên hệ, trạng thái | `GET /api/client/<id>` (314) | `db.get_client` | có |
| Lịch xem của khách | có (`viewings`, tối đa 20) | `db.client_viewings` | thiếu tên căn → **MỞ RỘNG → M6** |
| Căn đã gửi / đã xem | chỉ có mã căn | `db.get_listing` | **MỞ RỘNG → M6**: ghép tiêu đề, giá, trạng thái (chỉ căn của chính broker) |
| Trang đã chia sẻ cho khách này | THIẾU bộ lọc | `db.list_share_pages` | **MỞ RỘNG → M7** (`GET /api/shares?client_id=`) |
| Ghi chú dạng dòng thời gian | `notes` là **một chuỗi** | `db.add_note` nối "[dd/mm HH:MM] nội dung" bằng xuống dòng [báo cáo phụ] | **MỞ RỘNG → M6**: máy chủ tách thành `notes_list`, giao diện không tự tách |
| Thêm ghi chú | `POST /api/client/<id>/notes` (388) | `db.add_note` | có, v2 chưa gọi |
| Đổi trạng thái | `PUT /api/client/<id>` (350) | `db.update_client` | có, nhưng không kiểm giá trị (B5) |
| Sửa khách | `PUT /api/client/<id>` | | có |
| Căn hợp (MainButton) | **R1** | | |
| Đặt lịch (SecondaryButton) | `POST /api/viewings` | | |
| Nhắn Telegram cho khách | không có username của khách | | bỏ, hoặc chỉ hiện khi có số điện thoại (mở theo dạng `tel:`) |
| Xoá khách | **THIẾU → R18** | `db.delete_client` (xoá cứng) | Q6 |
| Lịch sử hội thoại bot đưa vào dòng thời gian (màn 25) | không có | | mục 1.23 |

### 1.6 Căn hợp với khách (Stitch: 09)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Danh sách căn khớp kèm điểm khớp % | **THIẾU → R1** | `feat_match.filter_hard_criteria` (feat_match.py:130), `feat_match.score_match` (70) | Lưu ý: ở bot, tính năng "tìm căn cho khách" **không** dùng `score_match` mà dùng `_client_to_search_filters` rồi xếp theo từ khoá (feat_clients.py:1190, 1261) [báo cáo phụ]. Hai cách ra hai thứ tự khác nhau → Q4 |
| "Tiết kiệm 2,5 tr" (màn 09) | suy được = ngân sách tối đa − giá | | tính trong R1, không bịa |
| Chọn nhiều → tạo trang chia sẻ gửi khách | `POST /api/share` + **R5** | | cần thêm bước ghi "đã gửi" cho khách (**MỞ RỘNG → M8**) |
| "Match broker khác" (màn 09) | **R19** | | |
| "Kho 120+ căn đối tác" | không có | | mục 1.23 |

### 1.7 Lịch xem (Stitch: không có)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Buổi sắp tới, nhóm theo ngày | `GET /api/viewings` (317) | `db.list_viewings` | có, chỉ buổi chưa tới giờ và đang hẹn, tối đa 50 |
| Lịch sử (buổi đã qua, đã huỷ) | THIẾU | `db.list_viewings(upcoming_only=False)` có sẵn | **MỞ RỘNG → M9** (`?scope=past`) |
| Tên căn và địa chỉ trong buổi | THIẾU | `db.get_listing` | **MỞ RỘNG → M9** |
| Đánh dấu đã xem / huỷ buổi / dời giờ | **THIẾU → R6** | `db.update_viewing` | bot "huỷ" bằng cách **xoá hẳn** dòng (feat_viewings.py:410) [báo cáo phụ] → Q5 |
| Nhắc trước buổi xem | **không có** | | bot hứa "Em sẽ nhắc trước 1 tiếng" (feat_viewings.py:346) nhưng không có tác vụ nào gửi nhắc: hàng đợi việc của bot chỉ có một việc là đọc hộp thư đi mỗi 30 giây (bot.py:1380) [đọc] |

### 1.8 Đặt lịch xem: form (Stitch: không có; tiêu đề màn 13 ghi nhầm "Tạo lịch hẹn")

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Chọn khách | `GET /api/clients` | | có |
| Chọn nhiều căn | `GET /api/listings` | | có |
| Lưu | `POST /api/viewings` | `db.create_viewing` | có. Máy chủ **nhận cả lời gọi rỗng** (không khách, không giờ) và trả thành công [đo]. Phải kiểm như mục 3, A3 |
| Ghi "đã hẹn xem" vào khách | THIẾU | bot gọi `touch_contact` và đặt trạng thái khách (feat_viewings.py `vw_confirm` 324) | **MỞ RỘNG → M10**: làm giống bot |
| Báo trùng giờ | THIẾU | `db.viewings_between` | **MỞ RỘNG → M10**: trả cảnh báo, không chặn |
| Trang riêng `/viewings/new` | | | v2 hiện là trang chỉ dẫn [đọc pages-static.js:26] |

### 1.9 Hoa hồng (Stitch: 17)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Chọn tháng | `GET /api/deals?month=` (320) | `db.list_deals` | có |
| Tổng "đã nhận" | `month_total` | | **sai nghĩa** (mục 0, ý 2). Chờ Q2 |
| "Chờ nhận" và số khoản | THIẾU (giao diện phải tự cộng) | | **MỞ RỘNG → M11** |
| Tên căn trong khoản | THIẾU | | **MỞ RỘNG → M11** |
| Phí sàn phải trả và trạng thái đã trả | THIẾU | `feat_payment.platform_fee_for` (hàm thuần) | **MỞ RỘNG → M11**: thêm `platform_fee_vnd`, `fee_paid` |
| Đánh dấu broker đã nhận tiền | **THIẾU → R7** | không có cột nào | Q2 |
| Sửa / xoá khoản | **THIẾU → R7** | `db.delete_deal` có nhưng không ai gọi | Q2 |
| KPI 82%, "chờ giải ngân", "100% tháng đầu / 50%", ẩn số tiền | không có | | mục 1.23 (ẩn số tiền làm được ở giao diện, không cần máy chủ) |

### 1.10 Ghi nhận hoa hồng: form (Stitch: 17, nút "Thêm giao dịch mới")

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Chọn khách, chọn căn | `GET /api/clients`, `GET /api/listings` | | có |
| Lưu | `POST /api/deals` (395) | `db.create_deal`, `db.money.parse_money` | có. **Không kiểm khách/căn có phải của mình** [đo] |
| Hướng dẫn trả phí sàn sau khi lưu | **THIẾU** | `feat_payment.payment_instructions_text` (80) | bot gửi hướng dẫn ngay sau khi ghi (feat_deals.py:325). Web thì **im lặng** → **MỞ RỘNG → M12** |
| Đổi trạng thái khách thành "đã thuê" | THIẾU | bot làm trong `_handle_add_deal` (feat_deals.py:278) [báo cáo phụ] | **M12** |
| Ngày chốt | THIẾU tham số | `db.create_deal(closed_at=...)` đã nhận | **M12** |

### 1.11 Trang đã chia sẻ (Stitch: 05)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Danh sách trang, lượt xem, lượt đặt lịch, hạn | `GET /api/shares` (294) | `db.list_share_pages`, `db.list_share_bookings` | có. Mảng `bookings` chứa **tên và số điện thoại của khách vãng lai**, lại được trả ngay trong danh sách → nên chuyển sang R3 |
| Tên khách nhận | THIẾU | `db.get_client` | **MỞ RỘNG → M7** |
| Chi tiết một trang: các căn, lượt đặt | **THIẾU → R3** | `db.get_share_page(bump_view=False)` | |
| Gia hạn / tắt trang | **THIẾU → R4** | không có hàm db | phải thêm hàm vào db/share.py |
| Đổi tiêu đề, xếp lại thứ tự, bỏ bớt căn (màn 05) | **R4** | | |
| Sao chép link | `url` (khi tạo), hoặc dựng từ `token` | | có |
| Chia sẻ lại qua Telegram | **R5** | | |
| Ẩn số chủ nhà (khách gọi sẽ về broker), hiện thông tin broker ở chân trang (màn 05) | | | trang công khai **hiện có hiện số của ai**: [chưa kiểm] share.py `_listing_card`. Nếu đang hiện số chủ nhà thì đây là việc cần quyết (Q7) |

### 1.12 Liên kết broker: danh sách yêu cầu (Stitch: 16)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Yêu cầu đang mở của broker khác | `GET /api/xbroker` (303) | `db.list_open_xbroker_requests` | có |
| Lượt thử còn lại | `trial` | `db.check_trial` | có. Nhưng **không đường nào trừ lượt này**: gửi đề xuất từ web không kiểm, không trừ [đọc api.py:595–668] |
| Số chỗ: x/3 | `response_count / max_responders` | `MAX_RESPONDERS = 3` (db/match.py:235) | màn Stitch ghi **5** chỗ, code là **3**. Tối đa 5 là số **căn** mỗi đề xuất (`PROPOSE_MAX_LISTINGS`, match.py:453), không phải số broker |
| "Đã đề xuất của tôi", tab "Đã đề xuất / Lịch sử" | **THIẾU → R21** | `db.get_propose_response` | |
| Giữ chỗ | **THIẾU → R20** | hiện chỉ giữ được bằng cách **trả lời tin trong nhóm Telegram** (`on_group_reply`, feat_match.py:974), có danh sách tạm nằm trong RAM của bot (`_pending_picks`) [báo cáo phụ] | khó nhất (mục 4) |
| Đăng yêu cầu tìm căn mới (nút chính màn 16) | **THIẾU → R19** | logic nằm trong handler `match_broadcast_send` (feat_match.py:409): đăng vào nhóm, nhắn riêng các broker có căn hợp | khó |
| Điểm uy tín người đăng, tỉ lệ chốt, chia 50/50, hợp đồng điện tử, bảo lãnh cọc, "1.420 môi giới trực tuyến", dòng tin chạy | không có | | mục 1.23 |

### 1.13 Đề xuất căn cho một yêu cầu (Stitch: 06)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Yêu cầu, hạn, chỗ, căn khớp kèm điểm, độ mới, gợi ý tăng điểm | `GET /api/propose/<id>` (300) | `feat_match.filter_hard_criteria`, `score_match`, `schema.quality_breakdown` | có, v2 **chưa có trang** (mã mở `x_<id>` dẫn tới trang "Không tìm thấy" vì router không có `/xbroker/:id`) [đọc router.js:166–173]. Đường đọc này **có tác dụng phụ**: nó tự nhả chỗ và gửi tin vào hộp thư đi (mục 3, A8) |
| Gửi đề xuất | `POST /api/propose/<id>` (377) | `db.save_propose_response` | có. **Broker đăng yêu cầu không được báo** (luồng bot cũ báo qua `_notify_new_response`, feat_match.py:674) → **MỞ RỘNG → M13** |
| Đồng hồ giữ chỗ 58:29 | `expires_at` | | có. Không có tác vụ nào thu hồi chỗ hết hạn; chỉ dọn khi có ai đọc (match.py:238) [báo cáo phụ] |
| AI phát hiện ảnh mờ, quay video | không có | | mục 1.23 |

### 1.14 Hồ sơ và gói (Stitch: 18, 14)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Tên, số, xưng hô, gói, điểm uy tín và hai thành phần, thống kê | `GET /api/profile` (324) | `utils.broker_profile_score` | có. Số "đang còn trống" chỉ đếm trạng thái `submitted` |
| Sửa tên, số, xưng hô | `PUT /api/profile` (354) | `db.update_broker` | có, v2 chưa gọi. Không kiểm độ dài, định dạng số |
| Hạn gói | THIẾU | cột `tier_expires_at` có trong bảng broker | **MỞ RỘNG → M14** |
| Giới thiệu bạn | `GET /api/referral` (330) | `db.get_referral_progress` | có |
| Thông báo (dòng dẫn) | 1.16 | | |
| Nhật ký điểm (+40 căn cước, +15 phản hồi nhanh), hạng Bạc/Vàng, Top 15%, 18 đánh giá 4,9 sao, tỉ lệ chốt 16,6%, 14 broker thân thiết, xuất PDF, QR hồ sơ | không có | | mục 1.23 |
| "Cách tính điểm" | | | viết tĩnh theo `utils.broker_profile_score` [chưa kiểm công thức] |

### 1.15 Nâng cấp gói (Stitch: 21)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Gói hiện tại | `GET /api/profile` → `tier` | | có |
| Lượt thử từng tính năng | `GET /api/trial/<feature>` (291) | `db.check_trial` | có (2 tính năng, mỗi cái 3 lượt) |
| Yêu cầu đang chờ duyệt | THIẾU (hiện chỉ biết qua lỗi 409) | `db.get_pending_premium_request` | **R14** |
| Gửi yêu cầu nâng cấp | `POST /api/premium/request` (398) | `db.create_premium_request` + hộp thư đi `premium_request` | có, có báo quản trị |
| Giá và thông tin chuyển khoản | THIẾU | `config.PAYMENT_BANK`, `PAYMENT_MOMO`; giá 99k/199k chỉ nằm trong docstring feat_premium.py:5–6 | **R14** trả giá và thông tin chuyển khoản từ cấu hình. Giá phải đưa vào `config`, không viết cứng ở giao diện |
| QR VietQR, "duyệt tự động 15–30 giây", hoàn tiền 3 ngày, "1.200+ broker" | không có | | mục 1.23. Hiện duyệt **bằng tay** qua lệnh `/approve` |

### 1.16 Cài đặt thông báo (Stitch: 02)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| 4 công tắc | `GET /api/notify/prefs` (327) | `db.get_notify_prefs` | có. v2 chỉ hiện chữ "Bật/Tắt", không cho gạt [đọc pages-lists.js:223–227] |
| Gạt là lưu | `PUT /api/notify/prefs` (358) | `db.set_notify_pref` | có, nhưng gửi chữ `"false"` thì lưu thành **bật** [đo] |
| 7 công tắc, im lặng ban đêm, "gửi tin thử", "độ trễ webhook 42 ms" (màn 02) | không có | | mục 1.23. Có 3 công tắc trong màn 02 không có loại thông báo nào đứng sau: khách mở link, nhắc đếm ngược giữ chỗ, nhắc lịch hẹn |

### 1.17 Thêm khách / Sửa khách: form (Stitch: không có)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Tạo | `POST /api/clients` (385) | `db.create_client` | có. Số phòng ngủ sai kiểu bị **bỏ qua im lặng** [đọc api_clients_deals.py:122–127; đo: gửi "x" vẫn 200] |
| Dán yêu cầu tự do để tự điền | THIẾU | `feat_clients.parse_client_freetext` (276), `_detect_client_urgency` (235) — hàm thuần [báo cáo phụ] | **MỞ RỘNG → M15** (`POST /api/clients/parse`, chỉ đọc). Tính chung vào R10 |
| Sửa, đổi trạng thái | `PUT /api/client/<id>` | `db.update_client` | có. Thiếu kiểm giá trị trạng thái (B5) |

### 1.18 Thêm căn: form (Stitch: 13)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Dán tin có sẵn → tách trường | **THIẾU → R10** | `parser.parse_listing(text)` (parser.py:400). Bộ tách là **quy tắc, không phải AI** [báo cáo phụ; đã kiểm parser.py chỉ import `re`] | Màn 13 ghi "AI đã trích xuất 8/8" thì phải đổi chữ |
| Lưu căn | **THIẾU → R9** | `db.create_listing` (listings.py:31), kiểm trùng (`find_exact_duplicate_by_hash`, `find_potential_duplicates`), `set_listing_status(...,"submitted")`, `feat_referral.on_listing_submitted`, `feat_write.generate_post` + `db.save_post` | mọi bước nằm trong `_try_final_submit` (feat_intake.py:398) là **handler của bot** → phải tách (mục 2, R9) |
| Ảnh | **THIẾU → R11** | `photos.upload_photo_sync` (cần sửa đường dẫn công cụ, mục 3, B2) | Q1 |
| Điểm tin dự kiến | R10 trả `quality_score` | `schema.quality_score` | |
| Giới hạn 20 căn của gói miễn phí | | `db.check_listing_limit` (listings.py:19) | bot **không** gọi hàm này khi nhập căn [báo cáo phụ]. R9 phải quyết có gọi hay không (Q8) |

### 1.19 Sửa căn: form (Stitch: 03)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Lưu các trường | `PUT /api/listing/<id>` (337) | `db.update_listing_field` | có. Gửi giá sai kiểu ("abc") thì trả **200 kèm danh sách đã sửa rỗng** [đo] → giao diện tưởng đã lưu. **MỞ RỘNG → M16**: trả 400 kèm trường lỗi |
| Loại nhà, số chủ nhà, tầng, ngày vào ở, tiện ích | THIẾU trong danh sách được sửa | `update_listing_field` nhận mọi khoá | **M16**: thêm `property_type`, `primary_phone`, `floor_number`, `available_from`, `amenities` |
| Ghi chú kín (số chủ nhà, % hoa hồng — màn 03) | không có trường | | Q9 |
| "Lưu tạm", "AI viết lại" | không có | | mục 1.23 |
| Lưu ý tác dụng phụ | | | **mọi lần sửa đều đẩy mốc cập nhật lên "bây giờ"** [đọc listings.py:212–233], nên sửa giá cũng làm căn "mới" lại mà không qua bước xác nhận còn trống có phạt. Q3 |

### 1.20 Bài đăng (Stitch: 10)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Xem theo ngôn ngữ, biết ngôn ngữ nào đã có | `GET /api/post/<id>?lang=` (287) | `db.get_saved_post`, `get_saved_post_langs` | có (v2 chỉ gọi tiếng Việt) |
| Lưu | `PUT /api/post/<id>` (345) | `db.save_post` | có, v2 chưa gọi |
| Tạo bài ở ngôn ngữ chưa có / dịch | **THIẾU → R13** | `feat_write.generate_post(listing, lang)` (61, theo mẫu, không AI); `translate.translate` (92, gọi dịch vụ ngoài MyMemory rồi Lingva) | chuỗi "dịch, hỏng thì tạo theo mẫu" đang nằm trong handler `handle_edit_post` (feat_intake/feat_write 511–575) [báo cáo phụ] |
| Viết lại theo giọng, chấm "SEO 98%", gửi vào nhóm Facebook, gửi vào kênh Telegram, gửi album ảnh qua bot | không có | | mục 1.23 |

### 1.21 Công cụ, Mẫu tin nhắn (Stitch: không có)

| Thứ cần có | Route | Hàm dùng lại | Ghi chú |
|---|---|---|---|
| Mẫu có sẵn + mẫu riêng | **THIẾU → R15** | `feat_templates.TPL_BUILTINS` (khoảng dòng 27), `db.list_templates` | |
| Điền tên khách/căn vào mẫu | **R15** (`?client_id=&listing_id=`) | `feat_templates._fill_tpl` (48, thuần) | |
| Thêm / xoá mẫu riêng | **THIẾU → R16, R17** | `db.create_template`, `db.delete_template` (không lọc chủ) | |
| Bộ marketing | không có | | nhãn "Sắp có" |

### 1.22 Hướng dẫn

Nội dung tĩnh, không cần API. Câu "Lịch hôm nay hiện ngay ở trang chính" đúng. Câu "bot sẽ nhắc" (nếu có) là **sai** (1.7).

### 1.23 Thứ có trên màn Stitch mà không có back end — không được nối vào số giả

Trợ lý con đọc 19 màn Stitch và gắn cờ những thứ dưới đây [báo cáo phụ]. Tôi đã kiểm lại ba chỗ: giá 99k/199k có trong docstring, thanh toán là chuyển khoản duyệt tay, số chỗ liên broker là 3.

| Nhóm | Thứ | Nếu muốn giữ thì cần gì |
|---|---|---|
| Tiền | QR VietQR, đối soát số dư tự động, hoàn tiền | cổng thanh toán và webhook ngân hàng: dự án riêng |
| Tiền | Chia hoa hồng 50/50 giữa broker, bảo lãnh cọc, hợp đồng liên kết điện tử | pháp lý cộng giữ tiền hộ: không làm trong mini app |
| Tiền | KPI tháng, "chờ giải ngân", loại hoa hồng 100%/50% | thêm trường cho khoản hoa hồng (cùng với Q2) |
| Uy tín | Xác minh căn cước, đánh giá sao, hạng Bạc/Vàng, Top %, thời gian phản hồi, tỉ lệ chốt, broker thân thiết | không có dữ liệu. Tỉ lệ chốt **suy được** (số khoản hoa hồng / số khách) nếu chủ dự án muốn |
| Nội dung | "Điểm AI", "AI tách tin", "AI viết lại", "AI dịch", "SEO" | không có AI nào. Bộ tách và bộ tạo bài đều theo quy tắc; dịch là dịch vụ ngoài. **Đổi chữ trên giao diện** |
| Ảnh | 360°, video, phát hiện ảnh mờ, giới hạn 15 ảnh | không có |
| Vị trí | Toạ độ, khoảng cách tới biển, "gửi vị trí" | không có toạ độ trong dữ liệu căn [chưa kiểm hết `buildings.json`, có thể có toạ độ toà nhà] |
| Đăng tin | Đăng tự động vào nhóm Facebook/Zalo/Telegram | Facebook gần như không cho đăng vào nhóm qua API; Telegram làm được bằng bot nhưng chưa có luồng |
| Khách | Nguồn lead Facebook Ads, VIP, chat, nhắc tái ký, hợp đồng số | không có |
| Thông báo | Im lặng ban đêm, độ trễ webhook, gửi thử, 3 loại thông báo không tồn tại | không có |
| Trang trí | "1.420 broker trực tuyến", dòng tin chạy "14 giây trước...", "SSL 256-bit", "Cloud Synced", "TMA Live" | số bịa: **bỏ** |
| Điều hướng | Thanh tab dưới (14, 15, 20, 24), nút nổi "+" (15, 20) | trái luật A3: bỏ |

---

## 2. Hợp đồng cho từng chỗ thiếu

### 2.0 Quy ước chung cho mọi đường mới (bắt buộc)

- **Xác thực:** chỉ đọc `initData` từ header `X-Telegram-Init-Data` (luật A5). Máy chủ hiện còn nhận `init_data` và `init_data_b64` trên địa chỉ [đọc server.py:133–146]. Địa chỉ thì bị ghi vào nhật ký máy chủ (server.py:404–406), nên một chuỗi đăng nhập còn hạn 24 giờ sẽ nằm trong nhật ký. Bỏ hai đường vào đó (A6).
- **Quyền sở hữu:** mọi đường nhận một mã (căn, khách, lịch, khoản hoa hồng, trang chia sẻ, mẫu) phải đọc bản ghi rồi so `broker_id` với người gọi **trước** khi đọc hay ghi. Sai chủ hoặc không có thì trả **404** (không trả 403, để không lộ là mã đó có tồn tại). Đề xuất gom vào một lớp dịch vụ, ví dụ `webapp/owned.py`: `owned_listing(bid, id)`, `owned_client`, `owned_viewing`, `owned_deal`, `owned_share`, `owned_template`. Mỗi hàm trả bản ghi hoặc `None`. Không sửa hàm của `db/`, vì bot cũng gọi chúng.
- **Thân yêu cầu:** phải là đối tượng JSON; nếu không thì trả `400 {"error":"bad_body"}`.
- **Lỗi:** dạng `{"error": "<mã>", "error_vi": "<câu cho người dùng>", "field": "<tên trường>"?}`. Mã trạng thái: 400 (sai dữ liệu), 401 (hết phiên), 402 (hết lượt thử), 404, 409 (trùng hoặc đang chờ), 410 (hết hạn), 422 (không đạt điều kiện), 500 (lỗi trong máy chủ, luôn có thân JSON).
- **Tác dụng phụ ra Telegram:** webapp **không gọi Telegram trực tiếp**, trừ một ngoại lệ là R5 (cần kết quả ngay). Mọi tin nhắn đi qua `db.queue_notification` để bot gửi. Mỗi loại tin mới phải thêm nhánh xử lý trong `feat_match.process_outbox_notifications` (feat_match.py:783). Nếu thiếu nhánh, tin đó bị **đánh dấu đã gửi và vứt im lặng** [báo cáo phụ].
- **Bốn trạng thái (B13):** mọi đường đọc mới phải phân biệt được "rỗng" (200 với mảng rỗng) với "lỗi" (mã khác 2xx). Không bao giờ trả 200 kèm số 0 khi thật ra là đọc thất bại. Hiện `get_profile_api` đang làm đúng điều cấm này: nuốt ngoại lệ rồi trả số 0 [đọc api_clients_deals.py:300–308].

### 2.1 Đường mới

**R1. `GET /api/client/<id>/matches?include_stale=0&limit=30`: căn hợp với khách**
- Trả về `{client:{id,name,budget_min,budget_max,bedrooms,district,property_type}, items:[{...listing_summary, match_score, savings_vnd, age_days, freshness_label}], hidden:{hard:{<tiêu chí>:n}, stale:n}}`.
- Lỗi: 404 nếu khách không phải của mình.
- Dùng lại `feat_match.filter_hard_criteria` + `score_match`. Lọc độ mới bằng `api.freshness_info`, giống hệt đường đề xuất liên broker để hai màn ra cùng con số.
- Không có tác dụng phụ.
- Cổng kiểm (phải đỏ trước khi làm): broker B gọi R1 với mã khách của A thì trả 404; khách không có ngân sách thì vẫn trả danh sách và không lỗi chia cho 0; căn đã xoá không xuất hiện.

**R2. `GET /api/listing/<id>/clients?limit=20`: khách hợp với căn**
- Trả về `{count, items:[{id,name,status,urgency,match_score}]}`.
- Chạy `score_match(listing, client)` trên các khách đang mở của chính broker (`db.list_clients`, bỏ các trạng thái trong `CLOSED_CLIENT_STATUSES`).
- Không có tác dụng phụ.
- Cổng kiểm: chỉ đếm khách của chủ căn; căn của người khác thì 404.

**R3. `GET /api/share/<token>`: chi tiết trang chia sẻ của mình**
- Trả về `{token,title,client:{id,name}|null,listings:[summary],view_count,created_at,expires_at,active,bookings:[{id,name,phone,listing_id,preferred_date,note,created_at}]}`.
- Bắt buộc gọi `db.get_share_page(token, bump_view=False)`, nếu không chính broker mở trang cũng làm tăng lượt xem. Tôi chưa kiểm hàm mặc định có tăng lượt xem không; chữ ký `bump_view=True` ở db/share.py:49 gợi ý là có.
- Lỗi: 404 nếu không phải của mình.
- Đồng thời bỏ mảng `bookings` (có số điện thoại khách) khỏi `GET /api/shares`, chỉ để lại số đếm.
- Cổng kiểm: broker B đọc token của A thì 404; đọc R3 không làm đổi `view_count`.

**R4. `PUT /api/share/<token>`: sửa trang chia sẻ**
- Thân: `{title?, listing_ids? (sắp theo thứ tự), extend_days? (1–30), active? (false = tắt ngay)}`.
- Trả về bản ghi như R3.
- Cần **hàm db mới** `update_share_page(token, **fields)` trong db/share.py (hiện chưa có hàm sửa).
- `listing_ids` phải là căn của mình; lọc giống `create_share`.
- Trang công khai (share.py `render_share_page`) phải tôn trọng `expires_at` và cờ tắt [chưa kiểm hiện nó xử lý trang hết hạn thế nào].
- Cổng kiểm: B sửa của A thì 404; gắn căn của người khác thì 400; trang đã tắt mở ra thì thấy trang lỗi, không thấy căn.

**R5. `POST /api/share/prepare`: tin nhắn chuẩn bị sẵn để chia sẻ (luật B14)**
- Thân: `{token}`.
- Máy chủ gọi Bot API `savePreparedInlineMessage(user_id=<người gọi>, result=<kết quả inline dạng bài viết, kèm nút mở /s/<token>>, allow_user_chats, allow_group_chats)`. Trả về `{prepared_message_id, expires_at?}`. Sau đó giao diện gọi `Telegram.WebApp.shareMessage(id)` qua lớp nền tảng, có kiểm `isVersionAtLeast('8.0')`. Nếu máy cũ thì lùi về `t.me/share/url` như hiện nay.
- Đây là chỗ duy nhất webapp gọi Telegram trực tiếp, vì cần mã trả về ngay. Webapp đã có token trong biến môi trường (server.py:41). Cần thêm hàm gọi Bot API (thư viện chuẩn `urllib`) vào tầng mới, ví dụ `webapp/tg_api.py`.
- Lỗi: 404 nếu token không phải của mình; `502 {"error":"telegram_failed"}` nếu Telegram từ chối, kèm `url` để giao diện lùi về cách cũ.
- Tác dụng phụ: một lời gọi ra Telegram, chưa có tin nào được gửi cho tới khi người dùng chọn chat.
- Chưa có nguồn (mục C trong CLAUDE.md): tin chuẩn bị sẵn sống bao lâu. Phải thử trên máy thật.
- Cổng kiểm: token của B thì 404; giả lập Telegram trả lỗi thì có 502 kèm `url`; không có token bot (chế độ dev) thì trả 503 rõ ràng, không treo.

**R6. `PUT /api/viewing/<id>`: đổi trạng thái, dời giờ, sửa ghi chú**
- Thân: `{status? ∈ ("scheduled","done","cancelled"), scheduled_at?, notes?, feedback?, listing_ids?}`.
- Trả về bản ghi buổi xem.
- Dùng lại `db.update_viewing` (viewings.py:75). Danh sách trạng thái hợp lệ lấy từ `VIEWING_STATUSES` (viewings.py:9).
- Khi `done`: đặt trạng thái khách thành "viewed" và ghi `viewed_listings`, giống bot (`_handle_viewing_feedback`, feat_viewings.py:474). Đoạn này nằm trong handler, phải tách thành hàm thuần `mark_viewing_done(viewing, feedback)` đặt ở lớp dịch vụ, để bot và web cùng gọi.
- Khi `cancelled`: **giữ dòng**, không xoá (khác bot, Q5).
- `listing_ids` phải là căn của mình.
- Lỗi: 400 nếu trạng thái lạ hoặc giờ không phải số; 404 nếu không phải của mình.
- Cổng kiểm: B đổi buổi của A thì 404; trạng thái "bogus" thì 400; `done` làm khách đổi sang "viewed".

**R7. `PUT /api/deal/<id>`: sửa khoản hoa hồng**
- Thân: `{commission_amount?, notes?, closed_at?, received? (bool, chỉ khi Q2 chọn thêm cột)}`.
- **Không bao giờ** cho broker sửa `paid` (phí sàn, chỉ quản trị xác nhận).
- Sửa số tiền của khoản **đã trả phí** thì trả 409 (đã đối soát xong).
- Cần **hàm db mới** `update_deal` (hiện không có, báo cáo phụ) và một cột mới nếu Q2 chọn A.
- Xoá khoản: chỉ cho khi chưa trả phí. Có thể làm bằng `DELETE /api/deal/<id>` → `db.delete_deal`; tôi không đếm vào 19 đường, chờ Q2.
- Cổng kiểm: B sửa của A thì 404; đặt `paid` thì bị bỏ qua hoặc 400; sửa khoản đã trả phí thì 409.

**R9. `POST /api/listings`: tạo căn từ form hoặc từ tin đã dán**
- Thân: `{raw_text?, fields:{price_vnd, property_type, bedrooms, bathrooms, area_m2, district, building_name, street, furnishing, deposit_months, pet_friendly, available_from, primary_phone, description}, confirm_duplicate?: bool}`.
- Trả về `{id, status, quality_score, missing_fields, duplicate_of?}`.
- Lỗi:
  - `409 {"error":"possible_duplicate","candidates":[...]}` khi nghi trùng và chưa xác nhận;
  - `402` khi vượt giới hạn gói (nếu Q8 chọn kiểm);
  - `400` theo trường;
  - `429` khi vượt `RATE_LIMITS_PER_HOUR` (config.py:16) [chưa kiểm bot có áp giới hạn này khi nhập căn không].
- Dùng lại: `db.create_listing`, `utils.content_hash_for_listing` (utils.py:519), `db.find_exact_duplicate_by_hash`, `db.find_potential_duplicates`, `db.set_listing_status(...,"submitted")`, `feat_write.generate_post`, `db.save_post`.
- **Phải tách ra khỏi bot:** chuỗi bước trong `_try_final_submit` (feat_intake.py:398) và `_process_buffer` (225) đặt thành hàm thuần, ví dụ `services/intake.py: submit_listing(broker_id, raw_text, parsed, photo_file_ids=[], changed_by)`. Hàm này trả kết quả và danh sách việc phụ cần làm. Bot gọi hàm đó rồi tự nhắn tin; web gọi rồi trả JSON. **Không viết lại logic kiểm trùng trong webapp.**
- Tác dụng phụ:
  - `feat_referral.on_listing_submitted` có thể cấp thưởng cho người mời và nhắn tin. Hàm này là `async` và cần `ctx` của bot, nên từ web phải đi qua hộp thư đi (loại mới `referral_progress`);
  - tạo bài đăng tiếng Việt;
  - tăng `listings_count`.
- Cổng kiểm:
  - tạo bằng broker A thì `broker_id` là A dù thân yêu cầu có ghi gì;
  - gửi lại đúng nội dung thì nhận 409;
  - `confirm_duplicate=true` thì lưu, ghi `duplicate_of` và không xoá căn cũ;
  - **test đối chiếu**: cùng một tin, đi qua đường bot và đường web ra cùng `parsed`, cùng `status`;
  - đếm dòng ở hộp thư đi trước và sau.

**R10. `POST /api/listings/parse` và `POST /api/clients/parse` (gộp làm một đường `/api/parse?kind=listing|client`, đếm là 1)**
- Thân: `{text}`.
- Trả về `{fields, missing, quality_score}` (với căn) hoặc `{fields, urgency}` (với khách).
- Chỉ đọc, không ghi.
- Dùng lại `parser.parse_listing`, `feat_clients.parse_client_freetext`, `_detect_client_urgency`.
- Cổng kiểm: không có dòng nào mới trong cơ sở dữ liệu sau khi gọi; text dài hơn 5.000 ký tự thì 400.

**R11. `POST /api/listing/<id>/photos` (gửi dạng nhiều phần): tải ảnh lên**
- Trả về `{photo_urls}`.
- Cần: (1) sửa đường dẫn công cụ tải ảnh trong photos.py:25 (B2); (2) một hàm tải lên từ dữ liệu ảnh (hiện `upload_photo_sync` chỉ nhận mã ảnh Telegram); (3) giới hạn kích thước. Máy chủ thư viện chuẩn hiện không đọc dữ liệu dạng nhiều phần; phải tự viết hoặc nhận ảnh dạng base64 trong JSON.
- Tác dụng phụ: ghi vào kho ảnh, kiểm trùng ảnh (`find_photos_by_hash`).
- **Thay thế R12:** `GET /api/photo/<listing_id>/<n>`. Máy chủ lấy ảnh từ Telegram bằng mã ảnh rồi chuyển tiếp cho trình duyệt, kèm bộ nhớ đệm. Ảnh hiện có (7 ảnh mỗi căn) hiện được ngay mà không cần kho ảnh, và không lộ token bot. Nhưng trang công khai cho khách cũng cần ảnh, nên R12 phải có biến thể công khai theo token chia sẻ. Q1.
- Cổng kiểm: ảnh căn của B thì 404; tệp quá 10 MB thì 413.

**R13. `POST /api/post/<id>/generate`: tạo hoặc dịch bài**
- Thân: `{lang, mode: "template"|"translate"}`.
- Trả về `{lang, text, source:"template"|"translated", saved:false}`.
- **Không tự lưu.** Broker sửa xong rồi lưu bằng `PUT /api/post` có sẵn.
- Dùng lại `feat_write.generate_post`, `translate.translate`.
- Tách chuỗi "dịch, hỏng thì tạo theo mẫu" ra khỏi `handle_edit_post`.
- Tác dụng phụ: gọi dịch vụ dịch ngoài, có thể chậm hoặc hỏng; đặt hạn chờ 10 giây và trả `504` kèm bản theo mẫu.
- Cổng kiểm: căn của B thì 404; ngôn ngữ lạ thì 400; dịch vụ ngoài hỏng thì vẫn có bài theo mẫu.

**R14. `GET /api/premium/status`: tình trạng gói**
- Trả về `{tier, tier_expires_at, pending:{id,tier,created_at}|null, trials:{send2client:{remaining,limit}, xbroker_match:{...}}, plans:[{tier,price_vnd,benefits[]}], payment:{bank, momo}}`.
- Dùng lại `db.get_tier`, `db.get_pending_premium_request`, `db.check_trial`.
- Giá và quyền lợi đưa vào `config.py` (hiện chỉ có trong docstring).
- Cổng kiểm: có yêu cầu đang chờ thì `pending` khác null; số lượt khớp với `GET /api/trial`.

**R15. `GET /api/templates?client_id=&listing_id=`: mẫu tin nhắn**
- Trả về `{items:[{id|null, name, content, filled?, builtin:bool}]}`.
- Dùng lại `TPL_BUILTINS`, `db.list_templates`, `_fill_tpl`.
- `client_id` và `listing_id` phải là của mình, nếu không thì bỏ qua phần điền.

**R16. `POST /api/templates`** với thân `{name, content}`, gọi `db.create_template`.

**R17. `DELETE /api/template/<id>`**, gọi `db.delete_template`. Hàm này không lọc chủ, nên lớp dịch vụ phải kiểm. Mẫu có sẵn thì không xoá được.
- Cổng kiểm R15–R17: B xoá mẫu của A thì 404; xoá mẫu có sẵn thì 400.
- Lưu ý: máy chủ hiện **không có phương thức xoá**; gọi thử ra 501 [đo]. Phải thêm `do_DELETE` và thêm DELETE vào danh sách phương thức cho phép (server.py:104–105).

**R18. `DELETE /api/client/<id>`: xoá khách** (hoặc chỉ đổi trạng thái "cancelled", chờ Q6)
- `db.delete_client` xoá cứng; lịch xem và khoản hoa hồng trỏ tới khách sẽ còn mã mồ côi [chưa kiểm có ràng buộc khoá ngoại không].
- Phải hỏi lại bằng `showConfirm` (B12).
- Cổng kiểm: B xoá của A thì 404; sau khi xoá, trang chính không còn khách đó và không lỗi.

**R19. `POST /api/xbroker`: đăng yêu cầu tìm căn liên broker**
- Thân: `{client_id, summary?, urgency?}`.
- Trả về `{id, expires_at, notified_brokers:n}`.
- Lỗi:
  - 402 khi hết lượt thử hoặc gói không đủ (gói Max);
  - 429 khi vượt hạn mức đăng mỗi ngày/tuần (`config.BROADCAST_DAILY_LIMIT`, `BROADCAST_WEEKLY_LIMIT`; `db.can_broadcast`, match.py:289);
  - 404 nếu khách không phải của mình.
- Logic đang nằm trong handler `match_broadcast_send` (feat_match.py:409): kiểm hạn mức, **đăng tin vào nhóm broker**, ghi `create_match_request`, lưu mã tin nhóm, `record_broadcast`, rồi `notify_matching_brokers` (696) nhắn riêng broker có căn hợp.
- Tách: phần ghi cơ sở dữ liệu thành hàm thuần; phần đăng nhóm và nhắn riêng thành **một loại tin mới** trong hộp thư đi (`broadcast_request`) để bot làm.
- Tác dụng phụ: **tin công khai trong nhóm** và nhiều tin nhắn riêng. Làm cuối cùng.
- Cổng kiểm:
  - khách của B thì 404;
  - vượt hạn mức ngày thì 429 và không có dòng mới trong hộp thư đi;
  - **đối chiếu với bot**: cùng một khách, hai đường tạo cùng `requirements_summary`.

**R20. `POST /api/xbroker/<id>/slot`: giữ chỗ để đề xuất**
- Trả về `{has_slot:true, expires_at}`.
- Lỗi:
  - 409 hết chỗ (đã đủ `MAX_RESPONDERS`);
  - 402 hết lượt thử;
  - 403 đang có công nợ (`has_unpaid_debt`) hoặc đang bị cấm đề xuất;
  - 410 yêu cầu đã hết hạn;
  - 422 không có căn nào đạt tiêu chí cứng.
- Logic hiện nằm trong `on_group_reply` (feat_match.py:974). Đoạn đó dùng **danh sách tạm trong RAM của bot** (`_pending_picks`) để giữ chỗ trong lúc broker chọn căn, rồi ghi một dòng trống bằng `save_propose_response(rid, uid, [], {})`.
- Web và bot chạy **hai tiến trình khác nhau**, nên danh sách trong RAM không dùng chung được. Phải có **hàm giữ chỗ nguyên tử trong cơ sở dữ liệu**: một giao dịch đếm số chỗ rồi chèn trong cùng một lần khoá (`BEGIN IMMEDIATE`). Bot cũng phải chuyển sang dùng hàm này, nếu không hai đường có thể cùng cấp chỗ thứ 4.
- Tác dụng phụ: trừ lượt thử `xbroker_match` (Q10); báo broker đăng yêu cầu (tuỳ chọn).
- Cổng kiểm:
  - **hai tiến trình cùng giữ chỗ cuối cùng** thì đúng một bên thắng (chạy hai tiến trình thật, không chạy hai luồng trong cùng tiến trình);
  - broker có công nợ thì 403;
  - broker tự giữ chỗ cho yêu cầu của chính mình thì 400.

**R21. `GET /api/xbroker/mine`: yêu cầu của tôi và đề xuất tôi đã gửi**
- Trả về `{my_requests:[{id,summary,status,expires_at,responses:[{broker_alias, listings:[summary], match_scores}]}], my_proposals:[{request_id, summary, listing_ids, submitted_at, status}]}`.
- Chưa quyết có lộ tên broker đề xuất không. Bot hiện có mở khoá liên hệ (`match_contacts_unlocked` trong bảng broker) [chưa kiểm luồng].
- Cổng kiểm: không bao giờ trả đề xuất của yêu cầu không phải của mình.

Tổng đường mới: R1, R2, R3, R4, R5, R6, R7, R9, R10, R11, R13, R14, R15, R16, R17, R18, R19, R20, R21 = **19 đường**. R12 thay thế cho R11 tuỳ Q1. Không có R8: tôi đã gộp đường xoá khoản hoa hồng vào R7, chờ Q2.

### 2.2 Mở rộng đường có sẵn

| Mã | Đường | Thêm gì |
|---|---|---|
| M1 | `GET /api/today` | số đếm không bị trần (dùng `COUNT(*)`: `db.count_clients` đã có; với căn và lịch cần hàm đếm mới); `deals_month_total` sau Q2 |
| M2 | `GET /api/listings` | `status_counts`; tìm cả trong toà nhà, đường, quận; `total` đếm thật thay vì trần 200 |
| M3 | `GET /api/listing/<id>` | `quality_breakdown` đầy đủ; bỏ cờ `ai_scored` |
| M4 | `PUT /api/listing/<id>/status` | kiểm danh sách trạng thái hợp lệ; "deleted" là thao tác có chủ đích |
| M5 | `GET /api/clients` | `?q=`, `status_counts`, `next_viewing` |
| M6 | `GET /api/client/<id>` | tiêu đề căn trong căn đã gửi, căn đã xem và lịch xem; `notes_list` |
| M7 | `GET /api/shares` | `?client_id=`, `client_name`, bỏ `bookings` chi tiết |
| M8 | `POST /api/share` | kiểm `client_id` là của mình [đo: hiện nhận mã khách bịa]; khi có khách thì ghi `record_sent_listings`, `update_client(status="sent")`, `touch_contact` giống bot `s2c_sent` (feat_sendclient.py:490) |
| M9 | `GET /api/viewings` | `?scope=upcoming\|past\|all`, `listing_titles`, `address` |
| M10 | `POST /api/viewings` | kiểm chủ của khách và của căn, bắt buộc có giờ, có khách hoặc tên khách; cảnh báo trùng giờ; cập nhật khách giống bot |
| M11 | `GET /api/deals` | tổng chờ nhận, tên căn, `platform_fee_vnd`, `fee_paid` (đổi tên rõ nghĩa) |
| M12 | `POST /api/deals` | kiểm chủ; `closed_at`; gửi hướng dẫn trả phí sàn qua hộp thư đi (loại mới `deal_fee_instructions`, nội dung lấy từ `payment_instructions_text`); đổi trạng thái khách |
| M13 | `POST /api/propose/<id>` | báo broker đăng yêu cầu (hộp thư đi, loại mới `propose_submitted`, làm giống `_notify_new_response`); trừ lượt thử (Q10) |
| M14 | `GET /api/profile` | `tier_expires_at` |
| M15 | (gộp vào R10) | |
| M16 | `PUT /api/listing/<id>` | trả 400 theo trường khi sai kiểu; thêm các trường còn thiếu |

Đếm: M1–M14 và M16 là **15 dòng sửa trên 11 đường khác nhau** (M15 gộp vào R10).

---

## 3. Lệch giữa bản v2 hiện tại, máy chủ và dữ liệu thật

### A. Lỗi chung của máy chủ (sửa trước khi nối thêm bất cứ thứ gì)

| # | Lỗi, mô tả bằng hành vi | Bằng chứng |
|---|---|---|
| A1 | **Gửi thân không phải đối tượng JSON thì máy chủ đóng kết nối, không trả gì.** Giao diện nhận "không kết nối được máy chủ", tức là trạng thái lỗi mạng, dù mạng không sao. Bất kỳ ngoại lệ nào trong xử lý cũng gây ra hiện tượng này, vì không có chỗ nào bắt lỗi chung | [đo] gửi `[1,2]` vào ghi lịch và `[]` vào sửa khách: cả hai đều "đầu kia đóng kết nối không trả lời"; nhật ký: `AttributeError: 'list' object has no attribute 'get'` ở server.py:352 |
| A2 | **Broker này ghi được vào khách của broker khác.** Ghi lịch xem và ghi hoa hồng không kiểm mã khách, mã căn có phải của mình không | [đo] trên bản sao: broker B đặt lịch cho khách của A → 200; B ghi hoa hồng cho khách của A → 200. A **không thấy** lịch đó trong chi tiết khách (0 buổi), vì lịch được ghi dưới tên B. Tức là dữ liệu bị gắn sai chủ và không ai thấy |
| A3 | **Ghi lịch xem nhận cả lời gọi rỗng** (không khách, không giờ, không căn) | [đo] `POST /api/viewings {}` → 200, tạo một dòng "đã hẹn" có mốc giờ là lúc tạo |
| A4 | **Đổi trạng thái căn nhận mọi chữ** | [đo] gửi "bogus" → 200, cơ sở dữ liệu lưu "bogus". Căn đó biến khỏi mọi bộ lọc trạng thái. Hàm `set_listing_status` không có danh sách hợp lệ [đọc listings.py:116–137] |
| A5 | **Công tắc thông báo hiểu ngược** khi giao diện gửi chữ thay vì giá trị đúng/sai | [đo] `enabled:"false"` → lưu thành bật |
| A6 | **Chuỗi đăng nhập Telegram nhận được cả trên địa chỉ**, và địa chỉ bị ghi vào nhật ký máy chủ | [đọc] server.py:133–146 và 404–406. Trái luật A5 |
| A7 | **Không có phương thức xoá** (501), và danh sách phương thức cho phép không có DELETE | [đo] |
| A8 | **Một đường đọc có tác dụng phụ:** mở màn Đề xuất căn khi không còn căn đạt có thể nhả chỗ của broker và gửi tin vào nhóm | [đọc] api.py:531–543. Telegram có thể tải lại trang, nên một lần mở là đủ mất chỗ. Nên chuyển việc nhả chỗ sang một đường ghi riêng hoặc sang R20 |
| A9 | **Sửa căn sai kiểu số thì vẫn trả "thành công"** với danh sách đã sửa rỗng | [đo] `price_vnd:"abc"` → 200, `updated: []` |

### B. Dữ liệu thật lệch với giả định của giao diện

| # | Lệch | Bằng chứng và cơ chế |
|---|---|---|
| B1 | **Mã có dấu hai chấm.** Mã căn dạng "tg:" + 12 ký tự, mã khách "cli:...", mã lịch "vw:...", mã hoa hồng "deal:...". Máy chủ **không giải mã** đường dẫn, nên "tg%3A..." không khớp | [đo] `GET /api/listing/tg%3A…` → 404; `tg:…` → 200. Bản v2 đã tránh được lỗi này: `seg()` giữ nguyên dấu hai chấm (api2.js:24), router giải mã tham số (router.js:26). **Nhưng bản cũ `api.js` vẫn mã hoá** (api.js:90) và vẫn được trang `listings.html` nạp (listings.html:109). Cách sửa gốc: máy chủ giải mã từng đoạn đường dẫn (`urllib.parse.unquote`) trước khi so, để không phụ thuộc giao diện |
| B2 | **Ảnh luôn rỗng trên web.** Bot nhận ảnh rồi chạy nền một việc tải lên kho ảnh; việc đó gọi một công cụ dòng lệnh ở đường dẫn **không tồn tại trên máy này**. Lỗi bị ghi nhật ký rồi bỏ qua, nên căn vẫn tạo được nhưng không có link ảnh | [đo] 3/3 căn có 7 mã ảnh Telegram, 0 link ảnh; tệp `~/workspace/custom-connectors/custom.legacy-cloudflare/bin/cf.py` (photos.py:25–26) không có. [chưa kiểm] nhật ký bot để thấy dòng "r2-put failed". Sửa đường dẫn thì chỉ có ảnh **mới**; ảnh cũ cần chạy lại việc tải (có sẵn mã ảnh) hoặc dùng R12 |
| B3 | **Cờ "đã thanh toán" = đã trả phí sàn**, không phải broker đã nhận hoa hồng | [đọc] feat_payment.py:36–52 (quản trị bấm "Đã nhận tiền" thì `mark_deal_paid`); db/deals.py:100 (chưa trả = công nợ); feat_match.py:991 (công nợ chặn giữ chỗ). Màn v2 ghi "Đã thanh toán" / "Chưa thanh toán" (pages-lists.js:138–139), còn prompt thiết kế ghi "Đã nhận / Chờ nhận". **Cả hai đều chưa đúng nghĩa** |
| B4 | **Mọi căn có cùng mốc cập nhật**, tới từng giây | [đo] 3/3 căn `updated_at = 1792223829`, dù tạo ở ba thời điểm khác nhau. Khớp với commit `262c142` (script ghi lại mốc dạng số giây). Hệ quả: khối "Căn cần làm mới", nhãn độ mới và điểm độ mới trong hồ sơ đều tính từ một mốc do script ghi, không do broker xác nhận. [chưa kiểm] script đó ghi mốc nào |
| B5 | **Hai bộ từ vựng trạng thái khách.** Webapp dịch 8 trạng thái: new, contacted, searching, sent, viewed, negotiating, closed, cancelled (api_clients_deals.py:32–41). Cơ sở dữ liệu và bot dùng: new, sent, pending_viewing, scheduled, viewed, negotiating, deposited, contracted, rented, cancelled (db/clients.py:9–12). Khách bot đặt "scheduled" hay "rented" sẽ hiện **chữ tiếng Anh thô**; giao diện gửi "searching" thì máy chủ vẫn lưu, vì `update_client` không kiểm | [đọc]. Chip lọc thiết kế "Đang tìm" và "Đã chốt" không khớp trạng thái nào bot ghi |
| B6 | **Bot hứa nhắc trước buổi xem nhưng không ai nhắc** | [đọc] feat_viewings.py:346; bot.py:1380 chỉ có một việc định kỳ. `viewing_reminder.py` là script riêng, chỉ in ra màn hình [báo cáo phụ] |
| B7 | **Lượt thử "gửi cho khách" chỉ bị trừ khi gửi từ web**; bot không trừ. **Lượt thử "liên broker" không đường nào trừ** | [đọc] `increment_trial_usage` chỉ được gọi ở api.py:349 |
| B8 | **Số đếm trên trang chính bị trần** 200/100/50 | [đọc] api.py:765–772 |
| B9 | Trang công khai cho khách đặt lịch **không có giới hạn tần suất** | [chưa kiểm kỹ] tôi chỉ tìm chữ "limit" và "rate" trong `handle_booking` (share.py:306–336) và không thấy. Mỗi lần đặt là một tin nhắn tới broker |

### C. Bản v2 lệch với luật và với API

| # | Lệch |
|---|---|
| C1 | Chia sẻ dùng `t.me/share/url` (platform.js:166–172), không dùng `savePreparedInlineMessage` + `shareMessage` như luật B14. Hiện chưa có dòng code nào gọi hai hàm đó [đọc: tìm trong toàn repo, 0 kết quả] |
| C2 | Trang Thông báo chỉ hiện chữ Bật/Tắt, không gạt được, dù đường lưu đã có |
| C3 | Mã mở thẳng `x_<id>` dẫn tới `/xbroker/<id>`, nhưng router không có trang đó, nên ra trang "Không tìm thấy" |
| C4 | Năm màn là trang "làm qua bot": Thêm căn, Thêm khách, Đặt lịch xem, Công cụ, Hướng dẫn. Tám màn trong bản đồ chưa có trang nào: Sửa căn, Bài đăng (chỉ có tờ xem tiếng Việt), Sửa khách, Căn hợp với khách, Đề xuất căn, Nâng cấp gói, Ghi nhận hoa hồng, Cài đặt thông báo (trang riêng) |
| C5 | Chọn giờ xem bằng ô ngày giờ của trình duyệt (pages-listings.js:77–78), tức là theo **múi giờ của điện thoại**. Broker ở Việt Nam thì đúng; điện thoại đặt múi khác thì lệch. Nên để máy chủ nhận "ngày + giờ" theo giờ Việt Nam và tự đổi (`db.vntime`) |
| C6 | Chữ hiển thị đang gán sai nguồn: "Giao dịch được ghi nhận qua bot sẽ hiện ở đây" (pages-lists.js:137), trong khi web có đường ghi |
| C7 | Hồ sơ nuốt lỗi thành số 0 (api_clients_deals.py:300–308). Đọc thất bại thì hiện "0 căn còn trống" thay vì trạng thái lỗi (trái B13) |

---

## 4. Thứ tự dựng đề xuất

Luật xếp: sửa nền trước; đọc trước, ghi sau; việc có tác dụng phụ ra Telegram để cuối. Mỗi nhóm có cổng kiểm riêng, và phải xanh mới sang nhóm sau.

| Nhóm | Việc | Đường | Cổng kiểm của nhóm |
|---|---|---|---|
| **0. Nền máy chủ** | bắt lỗi chung, trả 500 có thân JSON; kiểm thân là đối tượng; giải mã đường dẫn; bỏ nhận đăng nhập qua địa chỉ; thêm phương thức xoá; lớp kiểm chủ `owned_*`; danh sách trạng thái hợp lệ cho căn, khách, lịch; ép kiểu đúng/sai | A1–A7, A9, M4 | test: thân `[1]` → 400, không đóng kết nối; ép một ngoại lệ trong xử lý → 500 có JSON; `tg%3A` → 200; trạng thái "bogus" → 400; `"false"` → tắt; đăng nhập trên địa chỉ → 401 |
| **1. Chặn ghi sai chủ** | kiểm chủ ở ghi lịch, ghi hoa hồng, tạo trang chia sẻ có mã khách | M8 (phần kiểm), M10, M12 (phần kiểm) | **ma trận A/B**: mỗi đường ghi gọi bằng B với mã của A → 404 và số dòng không đổi. Ma trận phải sinh từ danh sách đường của máy chủ, không viết tay, để đường thêm sau tự rơi vào ma trận |
| **2. Đọc làm giàu** | tiêu đề căn ở mọi nơi; số không trần; lịch sử lịch; ghi chú tách dòng; tình trạng gói | M1–M3, M5–M7, M9, M11 (phần đọc), M14, R3, R14 | mỗi màn chụp đủ bốn trạng thái; số trên trang chính khớp với số ở trang con (đếm cùng một hàm) |
| **3. Đọc mới không tác dụng phụ** | căn hợp với khách, khách hợp với căn, tách tin, mẫu tin nhắn | R1, R2, R10, R15 | đếm dòng cơ sở dữ liệu trước và sau = 0 thay đổi; R1 và đường đề xuất liên broker cho cùng điểm với cùng cặp căn–khách |
| **4. Ghi trong nhà, không ra Telegram** | sửa căn đủ trường, đổi lịch, sửa hoa hồng (sau Q2), sửa/tắt trang chia sẻ, mẫu riêng, xoá khách, tạo/dịch bài | M16, R6, R7, R4, R16, R17, R18, R13 | ma trận A/B mở rộng; hỏi lại trước thao tác không hoàn tác được; dịch vụ dịch hỏng vẫn có bài |
| **5. Tạo căn** | tách `submit_listing` khỏi bot, rồi làm R9; ảnh (sau Q1) | R9, R11 hoặc R12 | test đối chiếu bot với web cho cùng một tin; ảnh mới có link; tạo trùng → 409 |
| **6. Ra Telegram qua hộp thư đi** | hướng dẫn trả phí sàn, báo đề xuất mới, tiến độ giới thiệu, ghi "đã gửi" cho khách | M12 (tin), M13, M8 (phần ghi), loại tin `referral_progress` | mỗi loại tin mới có nhánh xử lý ở bot (test: không loại nào rơi vào "không biết thì bỏ"); chạy bot thử trên bản sao và đếm tin đi |
| **7. Gọi Telegram trực tiếp** | chia sẻ bằng tin chuẩn bị sẵn | R5 | thử trên máy thật iOS hoặc Android (luật mục C) |
| **8. Liên broker đầy đủ** | giữ chỗ nguyên tử dùng chung cho bot và web, đăng yêu cầu, yêu cầu của tôi | R20, R19, R21 | hai tiến trình tranh chỗ cuối → đúng một thắng; vượt hạn mức → 429 và không có tin vào nhóm |

Ước lượng: **19 đường mới**, **15 dòng sửa trên 11 đường có sẵn**, **9 sửa nền** (nhóm 0), khoảng **6 hàm cần tách** khỏi handler của bot:
1. `submit_listing`
2. `mark_viewing_done`
3. "dịch, hỏng thì tạo theo mẫu"
4. ghi yêu cầu liên broker
5. giữ chỗ nguyên tử
6. ghi "đã gửi" cho khách (`s2c_sent`)

Cộng **3 hàm db mới**: `update_share_page`, `update_deal`, giữ chỗ nguyên tử. Và **4 loại tin mới** trong hộp thư đi: `deal_fee_instructions`, `propose_submitted`, `referral_progress`, `broadcast_request`.
Số giờ công: tôi chưa ước lượng (không có số đo năng suất trước để dựa vào).

---

## 5. Những gì tôi chưa đọc hoặc chưa kiểm

- Nội dung 19 màn Stitch do trợ lý con đọc. Tôi chỉ kiểm lại ba con số (giá, số chỗ, cách thanh toán).
- Toàn bộ `feat_intake.py` (2.429 dòng), `feat_clients.py` (1.729), `feat_match.py` (1.365): tôi đọc đoạn ảnh (feat_intake.py:455–800); phần còn lại theo báo cáo phụ.
- `webapp/share.py`: chưa đọc cách trang công khai hiện số điện thoại (của chủ nhà hay của broker), cách xử lý trang hết hạn, giới hạn tần suất đặt lịch.
- `utils.broker_profile_score`: chưa đọc công thức.
- Script đã ghi `updated_at` giống nhau cho mọi căn (commit 262c142): chưa đọc nó lấy mốc nào.
- Nhật ký bot thật: chưa xem để xác nhận dòng lỗi tải ảnh.
- Tài liệu `docs/reviews/backend-architecture-2026-10-17.md` của phiên khác: **cố ý không đọc** để không đụng tuyến của họ. Có thể trùng các đề xuất về lớp dịch vụ và kiểm chủ; cần điều phối đối chiếu.
- Mọi phép đo dựa trên bản sao có 3 căn và 0 khách. Hiệu năng (ví dụ R1 chấm điểm 200 căn × mỗi lần mở) **chưa đo**.
- Bot API `savePreparedInlineMessage`: chưa thử trên máy thật; thời hạn của tin chuẩn bị sẵn chưa có nguồn.

---

## 6. Câu hỏi cần chủ dự án quyết

| # | Câu hỏi | Lựa chọn | Khuyến nghị và lý do |
|---|---|---|---|
| Q1 | Ảnh trên web lấy từ đâu? | **A.** sửa đường dẫn công cụ tải lên kho ảnh, rồi chạy lại cho căn cũ. **B.** máy chủ lấy ảnh từ Telegram theo mã ảnh rồi chuyển tiếp (R12). **C.** cả hai: B ngay, A về sau | **C.** B hiện được ngay 21 ảnh đang có mà không chờ ai cài lại công cụ; A cần cho trang khách xem lâu dài và cho tải ảnh từ web (R11) |
| Q2 | Màn Hoa hồng hiện cái gì? | **A.** thêm cột "broker đã nhận tiền" (broker tự đánh dấu), tách khỏi "đã trả phí sàn". **B.** chỉ hiện "phí sàn đã trả / còn nợ", bỏ ý "đã nhận". **C.** giữ như cũ | **A**, và **hiện cả hai**. Broker cần biết tiền về, sàn cần biết phí. Hiện tại số "đã nhận tháng này" đang sai nghĩa |
| Q3 | Sửa thông tin căn có được tính là "làm mới" không? | **A.** không: tách mốc "xác nhận còn trống" khỏi mốc "sửa lần cuối". **B.** giữ như cũ | **A.** Hiện sửa một chữ là căn thành "mới", lách được bước xác nhận có phạt. Cần thêm một cột, và các phép tính độ mới chuyển sang cột đó |
| Q4 | "Căn hợp với khách" xếp theo cách nào? | **A.** dùng điểm khớp của luồng liên broker (`score_match`), cho cả bot. **B.** dùng cách bot đang làm (lọc rồi xếp theo từ khoá), không có %. **C.** web dùng A, bot giữ B | **A.** Màn thiết kế cần "Khớp %"; hai cách khác nhau sẽ làm bot và app gợi ý khác thứ tự cho cùng một khách |
| Q5 | Huỷ buổi xem thì xoá hay giữ? | **A.** giữ dòng, trạng thái "đã huỷ" (sửa cả bot). **B.** xoá như bot | **A.** Có lịch sử, và màn Lịch xem có nhãn "Huỷ" |
| Q6 | Xoá khách thì xoá cứng hay chỉ ẩn? | **A.** chỉ đổi trạng thái "cancelled". **B.** xoá cứng như bot | **A**, vì lịch và hoa hồng còn trỏ tới khách |
| Q7 | Trang công khai cho khách hiện số của ai? | **A.** luôn số broker. **B.** cho broker chọn (màn 05) | Chưa khuyến nghị: tôi chưa đọc trang hiện đang hiện số nào |
| Q8 | Tạo căn từ web có áp giới hạn 20 căn của gói miễn phí không? | **A.** có, cả bot và web. **B.** không, như bot hiện nay | **A**, nếu giới hạn đó là chủ đích. Hiện hàm kiểm có sẵn mà không ai gọi: có thể là tàn dư, có thể là đã cố ý tắt. Cần chủ dự án nói |
| Q9 | Có thêm "ghi chú kín" cho căn (số chủ nhà, % hoa hồng — màn 03) không? | **A.** thêm trường riêng, không bao giờ lên trang khách. **B.** không | **A**, rẻ (một khoá trong dữ liệu căn), nhưng phải có test "trang công khai không chứa ghi chú kín" |
| Q10 | Lượt thử trừ ở đâu? | **A.** "gửi cho khách" trừ ở cả bot và web; "liên broker" trừ khi giữ chỗ. **B.** giữ như cũ (web trừ, bot không; liên broker không ai trừ) | **A.** Hiện tại cùng một hành động có giá khác nhau tuỳ làm ở đâu |
| Q11 | Các tính năng chỉ có trên màn Stitch (mục 1.23) | **A.** bỏ khỏi màn. **B.** giữ dạng "Sắp có" cho vài cái. **C.** đưa vào kế hoạch | **A** cho số bịa và tính năng tiền/pháp lý; **B** cho đăng nhóm Telegram và tỉ lệ chốt (làm được bằng dữ liệu đang có) |
| Q12 | Liên broker (nhóm 8) có làm ngay không? | **A.** làm, kèm sửa bot dùng chung hàm giữ chỗ. **B.** trên web chỉ xem và đề xuất khi đã giữ chỗ qua nhóm Telegram | **B** cho đợt này. Giữ chỗ trên web buộc phải sửa luồng bot đang chạy (danh sách tạm trong RAM), rủi ro hai đường cùng cấp chỗ. Làm A khi có test hai tiến trình |

## 7. Quyết định của chủ dự án (17/10/2026)

| Câu | Quyết định |
|---|---|
| Q1 Ảnh căn | Máy chủ chuyển tiếp ảnh từ Telegram trước (kiểm chủ trước khi trả ảnh); sửa công cụ tải lên kho ảnh để sau. |
| Q2 Hoa hồng | Thêm cột "broker đã nhận tiền", tách khỏi "đã trả phí sàn"; màn hiện cả hai, phí sàn kèm hướng dẫn chuyển khoản. |
| Q3 Độ mới | Tách mốc "xác nhận còn trống" (confirmed_at) khỏi updated_at; sửa giá/tải ảnh không làm căn mới. |
| Q4 Xếp khớp | Căn hợp với khách và khách hợp với căn dùng chung điểm khớp của luồng liên broker, cho cả bot và web. |
| Q5/Q6 Huỷ, xoá | Không xoá cứng: buổi xem đánh dấu "đã huỷ", khách bị ẩn; hỏi lại bằng showConfirm. |
| Q8 Giới hạn 20 căn | Chưa áp giới hạn cho gói miễn phí; bỏ hàm kiểm thừa. |
| Q9 Ghi chú kín | Có trường ghi chú kín cho căn, kèm test trang khách không lộ. |
| Q11 Ngoài Stitch | Bỏ số bịa và các việc tiền/pháp lý (hoá đơn, hợp đồng); "Sắp có" cho đăng nhóm. |
| Q12 Liên broker | Đợt này web chỉ xem và đề xuất; giữ chỗ nguyên tử trong DB làm đợt sau. |

Q7 (trang khách hiện số của ai) và Q10 (trừ lượt thử ở đâu) chưa hỏi: Q10 theo khuyến nghị trừ giống nhau ở bot và web; Q7 chờ đọc share.py.
