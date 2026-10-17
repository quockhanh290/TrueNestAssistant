# Rà soát luồng — bot Linh + Mini App (17/10/2026)

Phiên A, chỉ đọc. Không sửa code, không chạy test, không chạy bot. Đối chiếu với HEAD `eb969d1`
(máy Calgary 02:47 MDT 17/10, tức 15:47 giờ Việt Nam 17/10).

**Trong lúc phiên này đang đọc, mã đã thay đổi:** commit `93b22a3` (sửa xác thực webapp) và
`77f480d` (chỉ chạy một bot + một webapp) được đưa vào giữa chừng. Lỗi xác thực ở mục 3.2 là
lỗi tôi đọc thấy ở bản trước đó; nó được đánh dấu là "đã sửa ở 93b22a3". Mọi mục khác đã được
kiểm lại trên HEAD.

**Phạm vi thật sự đã làm:** ba phiên con được giao rà luồng 1, 2, 4 chưa trả kết quả lúc viết
báo cáo. Vì vậy luồng 3 được rà kỹ, còn luồng 1, 2, 4 chỉ có những mục tôi tự lần tới. Phần lớn
luồng 1, 2, 4 là **chưa kiểm**, xem mục "Đã đọc / chưa đọc". Đây không phải một lượt quét hết.

**Số đo của điều phối (đã xác minh, phiên này không chạy lại):** `tests/test_flows.py` cho
**35 bài đạt / 1 bài trượt**. Bài trượt là `TestGuidedIntake::test_full_walkthrough`, do thiếu
tệp danh mục địa điểm. Xem mục 1.1.

---

## Tóm tắt

| Luồng | Nghiêm trọng | Cao | Trung bình | Thấp |
|---|---|---|---|---|
| 1. Nhập căn → đăng tin | 0 | 1 | 1 | 0 |
| 2. Khách → ghép → xem nhà → deal | 0 | 1 | 2 | 0 |
| 3. Webapp | 2 (1 đã sửa ở 93b22a3) | 2 | 3 | 6 |
| 4. Thanh toán / premium / nhắc việc | 0 | 1 | 1 | 1 |
| **Tổng** | **2** | **5** | **7** | **7** |

Năm lỗi nặng nhất:
1. **Ai vào được máy chủ webapp cũng tải được token bot và toàn bộ cơ sở dữ liệu**, bằng một đường dẫn có `../` (mục 3.1). Lỗi này còn trên `eb969d1`; **điều phối đã sửa ở `417a5e6`** (đo: bản cũ lộ 6/7 phép thử, bản mới 0/7; máy chủ chỉ nghe 127.0.0.1). Qua tunnel Cloudflare, `..` bị trả 400.
2. **(Đã sửa ở 93b22a3)** Webapp không bao giờ kiểm được chữ ký Telegram, và tin luôn tham số `tg_user_id`. Ai biết mã Telegram của một môi giới thì đọc và sửa được căn, khách, deal của người đó (mục 3.2).
3. **Nhập căn theo bước bị chết ở bước chọn phường** cho mọi môi giới. Bot im lặng, không báo gì, và môi giới kẹt ở bước đó (mục 1.1).
4. **Khách cầm link chia sẻ có thể tự động phạt môi giới** mà không cần ai xác minh. Gửi ba báo cáo là môi giới bị cấm đề xuất 7 ngày (mục 3.3).
5. **Sáu tính năng nhắc việc và tóm tắt (sáng, trưa, tối, nhắc xem nhà, follow-up, nudge) không chạy.** Không có gì lên lịch cho chúng, và cả sáu chỉ `print` ra màn hình chứ không gửi tin (mục 4.1). Lịch hẹn xem nhà còn bị lưu lệch 13 giờ (mục 2.1).

---

## Luồng 1 — Nhập căn → đăng tin

### 1.1 Nhập căn theo bước chết ở bước "Phường/xã" vì thiếu tệp danh mục, bot im lặng và môi giới bị kẹt
- **Cơ chế:** module địa điểm đọc `data/danang_locations.json` trong hàm `_load`, và không có đường lùi nào. Trong `data/` chỉ có `buildings.json`, `building_catalog.json`, `locations.json`. `TODO_KHANH.md` vẫn để mục "Copy file location catalog (2.8MB)" chưa làm. Nếu mở tệp lỗi, `_DATA` vẫn là `None`, nên mỗi lần gọi lại mở tệp và lại ném lỗi. Bot **không đăng ký error handler nào**, cũng không có `ConversationHandler`: mọi nút bấm đi qua một `on_callback` duy nhất, và trạng thái nằm trong `ctx.user_data["guided"]`.
- **Kịch bản:** môi giới chọn "nhập theo bước", trả lời số phòng ngủ, phòng tắm, loại hình, giá, rồi gõ diện tích "65". Bot tăng bước lên "ward" **trước** khi vẽ màn tiếp theo. Lúc vẽ, nó gọi `get_wards()` và ném `FileNotFoundError`. PTB chỉ ghi log "No error handlers are registered". Môi giới **không nhận được tin nhắn nào**.
  - Môi giới gõ tên phường, hoặc gõ "bỏ qua", thì nhánh `step == "ward"` gọi `search_wards` và lại ném lỗi. Bot vẫn im lặng. Chữ "bỏ qua" gõ tay ở bước này không được xử lý như lệnh bỏ qua.
  - Đường thoát chỉ có hai, và môi giới không thấy được: gõ "hủy" (mất hết câu trả lời), hoặc bấm nút "Bỏ qua" / "⬅️" còn sót trên tin nhắn **bước diện tích** cũ. Nút đó gửi `guided:skip` và áp vào bước hiện tại là "ward", nên bot nhảy qua được.
  - Nếu môi giới bấm "Bỏ qua" ngay trên màn diện tích, bot đi tới cùng chỗ hỏng. Callback đã được `q.answer()` nên không bị quay vòng chờ, nhưng tin nhắn không được sửa.
- **Hậu quả:** với người mới, kênh nhập căn chính bị chết ở bước 6/19, không có lời báo nào. Họ sẽ nghĩ bot treo.
- **Còn ai gọi danh mục này nữa:**
  - `parser.parse_district` và `parse_street`: dùng khi môi giới dán bài đăng tự do. Hai hàm này bọc lời gọi trong `try/except: pass`, nên không crash nhưng âm thầm mất phần khớp phường/đường. Xem 1.2.
  - `buildings.load_catalog`: cũng `except: pass`, nên không gộp được ~925 toà nhà OSM.
  - Trong `feat_intake`: thêm `get_wards()` khi bấm nút phường (dòng 1718) và `search_streets` (dòng 2086). Bước đường dùng `search_streets`, nên nếu môi giới thoát được bước phường thì gõ tên đường cũng sẽ crash tương tự.
- **Mức độ:** Cao. Nghiêm trọng nếu máy đang chạy bot chính là máy này: `start-all.ps1`, `token.txt`, `broker_bot.db` đều nằm ở đây, nên khả năng cao là đúng vậy.
- **Nhãn:** [Đã xác minh bằng đọc code] cho đường chạy và cách thoát. Bài test của điều phối tái hiện được phần crash. Phần "bot thật đang thiếu tệp" là [Nghi ngờ có căn cứ]: tệp không có ở thư mục này, nhưng tôi chưa kiểm tiến trình bot đang chạy từ thư mục nào.
- **Vị trí:** `locations.py:15-16, 40-46`; `feat_intake.py:1474, 1636-1650 (_guided_advance rồi _guided_show), 1718, 2086, 2113, 2144-2147`; `bot.py:1224` (chỉ có `CallbackQueryHandler(on_callback)`); không có `add_error_handler` ở đâu cả; `parser.py:140-147, 168-175`; `buildings.py:52-64`.
- **Hướng sửa:**
  - Chép tệp danh mục vào `data/`.
  - `_load` khi thiếu tệp trả danh mục rỗng và ghi log một lần.
  - Bước phường, nếu danh mục rỗng, rơi về nhập tự do.
  - Đăng ký `app.add_error_handler` để luôn báo môi giới "có lỗi, gõ hủy để làm lại".
  - Cổng kiểm: chạy `test_full_walkthrough` khi không có tệp danh mục, kết quả phải là đi hết các bước.

### 1.2 Bóc bài đăng tự do âm thầm mất khớp phường/đường khi danh mục lỗi
- **Cơ chế:** `parse_district` và `parse_street` nuốt mọi ngoại lệ (`except Exception: pass`) rồi rơi về danh sách quận cũ và regex. Không có dòng log nào.
- **Kịch bản:** môi giới dán bài "Căn 2PN đường Võ Nguyên Giáp, phường An Hải". Danh mục không mở được, nên phường mới sau sáp nhập không nhận ra. Phần đường chỉ còn regex bắt được khi bài có chữ "Địa chỉ:".
- **Hậu quả:** tin lưu thiếu vị trí, và ghép khách theo khu vực sai. Không ai biết vì không có log.
- **Mức độ:** Trung bình. **Nhãn:** [Đã xác minh bằng đọc code] (phần nuốt lỗi); mức suy giảm chất lượng là [Chưa kiểm].
- **Vị trí:** `parser.py:140-147, 168-175`; `buildings.py:53-63`.
- **Hướng sửa:** ghi log cảnh báo một lần khi danh mục không mở được, và tách lỗi "thiếu tệp" khỏi lỗi khác.

Các phần khác của luồng 1 (đăng tin, `feat_write`, `photos`, `normalize`, `feat_listings`, buffer ảnh, khả năng chạm đôi nút đăng): **chưa kiểm** trong phiên này.

---

## Luồng 2 — Khách → ghép → gửi khách → xem nhà → deal

### 2.1 Lịch hẹn xem nhà được lưu theo giờ Calgary, lệch 13 giờ so với giờ môi giới chọn
- **Cơ chế:** môi giới chọn ngày và giờ bằng nút, ví dụ "15:00". Bot ghép thành `strptime(date+time, "%Y%m%d%H%M")`, ra một `datetime` **không có múi giờ**, rồi `.timestamp()`. Python hiểu giờ không múi là giờ địa phương của máy, tức Calgary (hiện là MDT, UTC−6). Mốc lưu vào DB vì vậy là "15:00 Calgary" = **04:00 sáng hôm sau giờ Việt Nam**. Từ 01/11, khi Calgary về MST, độ lệch thành 14 giờ.
- **Kịch bản:** môi giới hẹn khách thứ Bảy 15:00.
  - Màn xác nhận vẫn ghi "15:00" vì hiển thị lại bằng `fromtimestamp` không múi, nên lệch hai lần thành ra khớp nhau.
  - Bản tin buổi sáng (`morning_brief`) đổi bằng `VN_TZ` sẽ ghi "04h", và xếp lịch sang **ngày hôm sau**.
  - `due_viewings` (nhắc trước 1 giờ) so với `time.time()`, nên nếu có chạy thì sẽ nhắc lúc 03:00 sáng Chủ nhật giờ Việt Nam.
- **Hậu quả:** mọi thứ so sánh lịch với "bây giờ" đều sai 13–14 giờ: nhắc hẹn, "lịch hôm nay", xin phản hồi sau buổi xem. Hiện các script nhắc này chưa chạy (mục 4.1), nên lỗi đang ngủ. Bật chúng lên là lộ ngay.
- **Mức độ:** Cao. **Nhãn:** [Đã xác minh bằng đọc code].
- **Vị trí:** `feat_viewings.py:290-291, 334-339, 59-62 (_fmt_sched)`; `morning_brief.py:54`; `midday_summary.py:78`; `viewing_reminder.py:31`; `followup_reminder.py:68`.
- **Hướng sửa:** dựng `datetime(..., tzinfo=VN_TZ)` khi tạo lịch, và hiển thị bằng `fromtimestamp(ts, VN_TZ)` ở mọi nơi. Lịch cũ trong DB cần di chuyển một lần (+13h hoặc +14h tuỳ ngày tạo); xem mục dữ liệu thật.

### 2.2 Bộ chọn ngày "Hôm nay / Ngày mai" dùng ngày Calgary
- **Cơ chế:** `_next_days` dùng `datetime.date.today()`, tức ngày của máy Calgary.
- **Kịch bản:** từ 00:00 đến khoảng 13:00 giờ Việt Nam (14:00 khi Calgary về MST), Calgary vẫn đang ở hôm qua. Môi giới mở bot lúc 9h sáng thứ Bảy thì nút "Hôm nay" ghi **thứ Sáu**, còn "Ngày mai" mới là thứ Bảy.
- **Hậu quả:** hẹn nhầm ngày. Lỗi xảy ra hơn nửa ngày làm việc ở Việt Nam.
- **Mức độ:** Trung bình. **Nhãn:** [Đã xác minh bằng đọc code].
- **Vị trí:** `feat_viewings.py:42-56, 180`.
- **Hướng sửa:** `datetime.datetime.now(VN_TZ).date()`.

### 2.3 Hoa hồng "tháng này" tính theo tháng Calgary
- **Cơ chế:** bot dùng `datetime.now().strftime("%Y%m")` cho khoá tháng. Webapp dùng `time.localtime()` / `time.mktime` cho đầu tháng. Cả hai đều theo giờ Calgary.
- **Kịch bản:** deal chốt lúc 10h sáng 01/11 giờ Việt Nam, khi Calgary vẫn là 31/10. Deal đó bị tính vào tháng 10. Ngày chốt hiển thị (`fromtimestamp` không múi) cũng có thể lệch một ngày.
- **Mức độ:** Trung bình. **Nhãn:** [Đã xác minh bằng đọc code].
- **Vị trí:** `feat_deals.py:42, 54`; `webapp/api_clients_deals.py:205-228`.
- **Hướng sửa:** tính biên tháng theo `VN_TZ`.

Các phần khác của luồng 2 (ghép khách `feat_match`, gửi khách `feat_sendclient`, chạm đôi tạo deal, quyền sở hữu trong callback của bot, độ dài `callback_data`): **chưa kiểm**.

---

## Luồng 3 — Webapp

### 3.1 [NGHIÊM TRỌNG — VẪN CÒN] Đi ngược thư mục qua `/static/`: tải được `token.txt` và `broker_bot.db`
- **Cơ chế:** `_static(name)` làm `os.path.normpath(name)`. Trên Windows, `"../../token.txt"` thành `"..\..\token.txt"`. Hàm nối với `STATIC_DIR` rồi kiểm `full.startswith(STATIC_DIR)`. Chuỗi `D:\...\webapp\static\..\..\token.txt` **vẫn bắt đầu bằng** `STATIC_DIR` dưới dạng chữ, nên phép kiểm qua, và `isfile` trả đúng. `http.server` không tự chuẩn hoá đường dẫn.
  - Tôi đã chạy lại đúng phép kiểm này trong Python (không mở tệp): `'../../token.txt' → startswith=True, isfile=True` và `'../../broker_bot.db' → True, True`.
- **Kịch bản:** `curl --path-as-is http://<máy>:8080/static/../../token.txt` trả về token bot. `.../static/../../broker_bot.db` trả nguyên cơ sở dữ liệu: mọi môi giới, khách, số điện thoại, deal. Máy chủ nghe ở `0.0.0.0`, nên ai cùng mạng LAN/wifi cũng làm được.
- **Hậu quả:** lộ token thì người khác điều khiển được bot. Lộ DB là lộ dữ liệu khách của mọi môi giới.
- **Mức độ:** Nghiêm trọng. **Nhãn:**
  - [Đã xác minh bằng đọc code] cho đường kiểm, cộng phép mô phỏng ở trên.
  - Qua đường hầm Cloudflare (`*.trycloudflare.com`): [Chưa kiểm]. Cloudflare có thể chuẩn hoá `..` trước khi chuyển tiếp, và tôi không gửi thử yêu cầu nào.
- **Vị trí:** `webapp/server.py:218-221` (HEAD); `do_GET` ở nhánh `/static/`.
- **Hướng sửa:**
  - Dùng `full = os.path.realpath(os.path.join(STATIC_DIR, name))` và `os.path.commonpath([full, STATIC_DIR]) == STATIC_DIR`.
  - Từ chối mọi tên có `..` hoặc `\`.
  - Cân nhắc bind `127.0.0.1` khi đã có đường hầm.
  - Cổng kiểm: request `--path-as-is` tới `token.txt` phải trả 404.
  - **Nên đổi token bot** nếu máy từng mở cổng ra mạng ngoài.

### 3.2 [NGHIÊM TRỌNG — ĐÃ SỬA Ở 93b22a3] Webapp không kiểm được initData, tin `tg_user_id`, và `?demo=1` mở trong production
- **Cơ chế (bản trước 93b22a3):** `server.py` đọc `BOT_TOKEN`, trong khi `start-all.ps1` chỉ đặt `TELEGRAM_BOT_TOKEN`. Token rỗng thì `validate_init_data` luôn trả `None`. Sau đó `_auth` rơi về "tin `tg_user_id` từ WebView". Ngoài ra `?demo=1&broker_id=X` luôn mở, và `auth_date` không được kiểm.
- **Kịch bản cũ:** ai biết mã Telegram của một môi giới mở `https://<tunnel>/api/clients?tg_user_id=<id>` là đọc và sửa được khách, căn, deal của người đó. Với `tg_user_id=<ADMIN_TELEGRAM_ID>` thì vào được `/api/admin/reports`.
- **Hiện trạng:** commit `93b22a3` đọc `TELEGRAM_BOT_TOKEN`, bỏ nhánh `tg_user_id`, chỉ cho demo khi `WEBAPP_DEV=1`, và từ chối initData cũ hơn 24 giờ (`server.py:38-40, 74-75, 119-121, 386-388`). Phần so sánh chữ ký vẫn dùng `hmac.compare_digest`, đúng thời gian hằng.
- **Mức độ:** Nghiêm trọng. **Nhãn:** [Đã xác minh bằng đọc code] cho bản cũ; phần đã sửa tôi mới đọc lướt các dòng trên. Cổng kiểm do phiên sửa tự báo, tôi chưa chạy lại.
- **Còn sót:** frontend v2 vẫn gửi `tg_user_id` và `init_data` trên **query string** (`webapp/static/v2/listings.html:131-132`, `tabs.js:31-33`, theo bản tôi đọc trước khi v2 được viết lại). Server nay bỏ qua `tg_user_id`, nhưng initData trên URL bị `log_message` ghi vào log; xem 3.11.

### 3.3 Khách cầm link chia sẻ tự động phạt được môi giới, không ai xác minh, không chống lặp
- **Cơ chế:** `POST /s/<token>/report` là công khai, không cần đăng nhập.
  - Với lý do `amenity_wrong`, bot xếp ngay `false_amenity_suspect`. Bộ phát thông báo gọi `penalize_false_amenity`, và hàm này gọi thẳng `flag_false_refresh`. Hàm đó **cộng 1 vào bộ đếm báo sai của môi giới** không điều kiện. Đủ 3 lần thì đặt cấm đề xuất 7 ngày.
  - Không có kiểm tra đối chiếu, không giới hạn mỗi link/mỗi khách một lần, không có bước admin duyệt trước.
  - Với `rented` thì có đối chiếu "môi giới vừa xác nhận còn trống trong 7 ngày", nhưng cũng không chống lặp.
- **Kịch bản:** một khách khó chịu, hoặc đối thủ được chuyển link, bấm "Tiện ích không đúng thực tế" ba lần trên cùng một trang (hoặc gửi ba POST). Sau tối đa ~90 giây (ba vòng outbox 30 giây), môi giới bị −30 điểm uy tín và bị cấm đề xuất 7 ngày.
- **Hậu quả:** môi giới bị phạt oan, mất lead liên môi giới.
- **Mức độ:** Cao. **Nhãn:** [Đã xác minh bằng đọc code].
- **Vị trí:** `webapp/share.py:338-383`; `feat_match.py:804-833`; `feat_notify.py:317-330`; `db/refresh.py:58-98`; `db/share.py:148-163`.
- **Hướng sửa:**
  - Mỗi cặp (token, listing, lý do) chỉ tính một lần.
  - `amenity_wrong` đưa vào hàng chờ admin duyệt, không phạt tự động.
  - Giới hạn tần suất theo IP/token.
  - Cổng kiểm: ba POST giống nhau thì bộ đếm chỉ tăng 1, và lý do `amenity_wrong` thì bộ đếm không đổi khi admin chưa duyệt.

### 3.4 Hàng đợi thông báo (outbox) bị tắc đầu hàng: một dòng không gửi được chặn mọi dòng sau
- **Cơ chế:** `pop_unsent_notifications` lấy **20 dòng cũ nhất** chưa gửi. Vòng lặp chỉ đánh dấu đã gửi ở cuối mỗi lượt.
  - Với `slot_reopened`, nếu không tìm thấy yêu cầu hoặc `BROKER_GROUP_ID` trống, code `continue`, **bỏ qua bước đánh dấu**.
  - Nếu `send_message(... reply_to_message_id=...)` ném lỗi (tin gốc trong nhóm đã bị xoá, bot bị kick), lỗi rơi ra `except` ngoài và dòng đó cũng không được đánh dấu.
  - Các dòng đó quay lại mỗi 30 giây, mãi mãi. Khi đủ 20 dòng như vậy, mọi thông báo mới bị chặn hoàn toàn: khách đặt lịch, yêu cầu premium gửi tới admin, phạt, cảnh báo.
- **Kịch bản:** bot chạy khi chưa cấu hình `BROKER_GROUP_ID`, và môi giới mở trang đề xuất mà không có căn hợp. Mỗi lần như vậy để lại một dòng `slot_reopened` không bao giờ được đánh dấu. Sau 20 lần, môi giới không còn nhận được thông báo khách đặt lịch từ trang chia sẻ.
- **Mức độ:** Cao. **Nhãn:** [Đã xác minh bằng đọc code]. Số dòng đang tắc trong DB thật là [Chưa kiểm].
- **Vị trí:** `db/notify.py:78-96`; `feat_match.py:743-765, 855-858`; `webapp/api.py:530-542`; `bot.py:1232-1238`.
- **Hướng sửa:**
  - Mọi nhánh đều đánh dấu kết quả (đã gửi / bỏ qua / lỗi).
  - Thêm cột `attempts` và bỏ dòng sau N lần lỗi.
  - Cổng kiểm: tạo 25 dòng `slot_reopened` không có group, một dòng `booking_created`, chạy một vòng outbox; dòng booking phải được gửi.

### 3.5 Lỗi gửi thông báo đặt lịch bị nuốt rồi vẫn đánh dấu "đã gửi"
- **Cơ chế:** nhánh `booking_created` bọc `notify_new_booking` trong `try/except` riêng, chỉ ghi log, rồi rơi xuống `mark_notification_sent`. Ngược với 3.4: ở đây lỗi tạm thời (mạng, 429) làm **mất vĩnh viễn** thông báo. Cùng mẫu đó áp cho `trial_expiring`, `velocity_warning`, `premium_request`, phạt.
- **Kịch bản:** Telegram trả 429 đúng lúc khách đặt lịch. Môi giới không bao giờ được báo. Lịch đặt vẫn nằm trong DB nhưng không ai nhìn.
- **Mức độ:** Trung bình. **Nhãn:** [Đã xác minh bằng đọc code].
- **Vị trí:** `feat_match.py:771-780, 834-858`.
- **Hướng sửa:** chỉ đánh dấu khi gửi thành công; lỗi tạm thời thì để thử lại có giới hạn.

### 3.6 Tạo lịch xem và deal qua webapp không kiểm quyền sở hữu khách/căn, nên chèn được vào hồ sơ khách của môi giới khác
- **Cơ chế:** `POST /api/viewings` và `POST /api/deals` đưa thẳng `client_id`, `listing_ids`/`listing_id` từ body vào `db.create_viewing` / `db.create_deal`, không kiểm khách/căn thuộc người gọi. `db.client_viewings(client_id)` lọc **chỉ theo client_id**, không theo broker. `GET /api/client/<id>` (đã kiểm chủ khách) liệt kê các lịch đó.
- **Kịch bản:** môi giới A biết mã khách `cli:...` của môi giới B (từ một màn chia sẻ hay đề xuất). A tạo lịch xem gắn `client_id` đó và căn của A. B mở hồ sơ khách của mình và thấy lịch xem lạ, với căn của A. Deal cũng có thể gắn `listing_id` của B.
- **Mức độ:** Trung bình. Cần đăng nhập thật (sau 93b22a3) và cần biết mã. Mã có dạng ngẫu nhiên hay không: [Chưa kiểm] cho khách.
- **Nhãn:** [Đã xác minh bằng đọc code].
- **Vị trí:** `webapp/api_clients_deals.py:172-183, 257-273`; `db/viewings.py:12-33, 154-166`; `db/deals.py:31-45`.
- **Hướng sửa:** kiểm `get_client(client_id).broker_id == broker_id` và quyền sở hữu từng `listing_id`; `client_viewings` thêm điều kiện `broker_id`.

### 3.7 Trang đề xuất lộ nguyên văn yêu cầu của khách cho mọi môi giới
- **Cơ chế:** `GET /api/propose/<request_id>` không kiểm người gọi có giữ slot hay không. Nó trả `requirements_raw` lấy từ bảng `clients` của môi giới chủ khách, qua phép JOIN.
- **Kịch bản:** bất kỳ môi giới đã đăng nhập nào, có mã yêu cầu (đăng trong nhóm), đều đọc được đoạn môi giới chủ gõ về khách. Đoạn này có thể có tên hoặc số điện thoại khách.
- **Mức độ:** Trung bình. **Nhãn:** [Nghi ngờ có căn cứ]. Phần code đã đọc; việc `requirements_raw` thật sự chứa thông tin nhận dạng thì cần dữ liệu thật.
- **Vị trí:** `webapp/api.py:453-564`; `db/match.py:481-495`.
- **Hướng sửa:** chỉ trả bản tóm tắt; `requirements_raw` chỉ cho chủ khách.

### 3.8 Danh sách căn trên webapp bị cắt ở 200 căn
- **Cơ chế:** `get_listings` luôn lấy `limit=200, offset=0` từ DB rồi mới phân trang trong Python. `total` vì vậy tối đa 200, và trang sau 200 trống.
- **Mức độ:** Thấp. Chỉ ảnh hưởng môi giới có trên 200 căn. **Nhãn:** [Đã xác minh bằng đọc code].
- **Vị trí:** `webapp/api.py:155-158, 188-189`.

### 3.9 Không có busy_timeout/WAL trong khi bot và webapp cùng ghi một SQLite
- **Cơ chế:** `connect()` dùng mặc định `sqlite3.connect` (chờ 5 giây, journal kiểu rollback). Webapp là `ThreadingHTTPServer`, và bot ghi song song.
- **Hậu quả có thể:** lỗi "database is locked" lúc tải cao, trả 500 hoặc mất ghi.
- **Mức độ:** Thấp. **Nhãn:** [Nghi ngờ có căn cứ]; chưa đo tần suất.
- **Vị trí:** `db/core.py:267-270`.

### 3.10 Quy tắc "UI không đọc db trực tiếp, đi qua api.py"
- **Hiện trạng:**
  - Phía webapp tuân thủ: `server.py` chỉ gọi `api`, `api_clients_deals`, `share`. `share.py` gọi `db` nhưng nó là tầng máy chủ.
  - Phía bot: **48 module** `import db` trực tiếp. Quy tắc ghi "code mới", nên đây là tồn đọng chứ không phải vi phạm mới.
- **Mức độ:** Thấp. **Nhãn:** [Đã xác minh bằng đọc code] (đếm bằng grep).

### 3.11 initData nằm trên URL nên bị ghi vào log máy chủ
- **Cơ chế:** frontend gửi `init_data=` trên query string; `log_message` in nguyên `self.path`. Với hạn 24 giờ, ai đọc được log sẽ dùng lại được phiên đó.
- **Mức độ:** Thấp. **Nhãn:** [Nghi ngờ có căn cứ]. Phần v2 đang được viết lại; CLAUDE.md của repo đã yêu cầu dùng header.
- **Vị trí:** `webapp/server.py` (`log_message`); frontend v2 như đã nêu ở 3.2.

### 3.12 `create_share` nhận `client_id` không kiểm chủ
- **Mức độ:** Thấp. Chỉ gắn nhãn khách lên trang chia sẻ của chính mình. **Nhãn:** [Đã xác minh bằng đọc code].
- **Vị trí:** `webapp/api.py:381-400`.

### 3.13 Đặt lịch trên trang chia sẻ không giới hạn tần suất
- **Cơ chế:** `POST /s/<token>/book` là công khai. Mỗi lần gửi tạo một dòng đặt lịch và một tin đẩy tới môi giới.
- **Hậu quả:** spam được môi giới.
- **Mức độ:** Thấp. **Nhãn:** [Đã xác minh bằng đọc code].
- **Vị trí:** `webapp/share.py:306-335`.

---

## Luồng 4 — Thanh toán / premium / nhắc việc

### 4.1 Sáu tính năng nhắc việc/tóm tắt là tính năng chết: không ai lên lịch, và chúng chỉ in ra màn hình
- **Cơ chế:**
  - `bot.py` chỉ có **một** job JobQueue: `run_repeating(_outbox_poller, interval=30)`. Không có `run_daily` nào. Không có `Defaults(tzinfo=...)`.
  - `start-all.ps1` chỉ khởi động bot và webapp. `scripts/` chỉ có bốn script dữ liệu (`backfill_phash`, `diag_db`, `fill_mock`, `fix_listings_full`).
  - Grep tên các module `morning_brief`, `midday_summary`, `evening_summary`, `viewing_reminder`, `followup_reminder`, `pending_nudges` trong `*.py`, `*.ps1`, `*.bat`, `*.cmd` chỉ ra chính các tệp đó.
  - Mỗi tệp là script độc lập có `main()`, và đếm `send_message` trong cả bảy tệp (gồm `nudge.py`) **đều bằng 0**. Chúng `print` ra stdout. Docstring của `viewing_reminder` ghi rõ: "Sending via the bot is wired up separately."
- **Kịch bản:** môi giới có lịch dẫn khách 15:00. Không có tin nhắc trước 1 giờ, không có bản tin sáng, không có tóm tắt tối.
- **Hậu quả:** cả lớp "trợ lý nhắc việc" không tồn tại với người dùng.
- **Mức độ:** Cao. **Nhãn:**
  - [Đã xác minh bằng đọc code] cho phần trong repo.
  - Có một tác vụ Windows Task Scheduler ngoài repo hay không: [Chưa kiểm]. Nhưng kể cả có, các script cũng chỉ in ra chứ không gửi.
- **Vị trí:** `bot.py:1232-1238`; `viewing_reminder.py:1-6, 15-50`; `morning_brief.py:49-95`; tương tự `midday_summary.py`, `evening_summary.py`, `followup_reminder.py`, `pending_nudges.py`, `nudge.py`.
- **Ghi chú:** `feat_evening` có handler nút (`bot.py:1090-1096`) nhưng tôi chưa lần xem cái gì gửi ra tin nhắn có những nút đó. `feat_stale` có `stale_action_cb`, và nguồn kích hoạt cũng chưa kiểm.
- **Hướng sửa:**
  - Nối từng script thành job `run_daily(time=datetime.time(h, m, tzinfo=VN_TZ))`, gửi bằng `ctx.bot.send_message`, với cờ "đã gửi" ghi trong cùng giao dịch.
  - Sửa 2.1 **trước** khi bật nhắc xem nhà.

### 4.2 Lượt dùng thử "ghép liên môi giới" chỉ tính ra chứ không chặn ở máy chủ
- **Cơ chế:** `GET /api/xbroker` tính `trial_ok` nhưng vẫn trả đủ danh sách yêu cầu dù đã hết lượt. Việc chặn dựa hoàn toàn vào frontend.
- **Kịch bản:** môi giới gói thường gọi thẳng API sau khi hết 3 lượt và vẫn xem được mọi yêu cầu mở.
- **Mức độ:** Trung bình. **Nhãn:** [Đã xác minh bằng đọc code].
- **Vị trí:** `webapp/api.py:567-591`.
- **Hướng sửa:** trả 402 khi `not trial_ok`.

### 4.3 Ngày hết lệnh cấm đề xuất hiển thị theo ngày Calgary
- **Cơ chế:** `datetime.fromtimestamp(cooldown_until).strftime("%d/%m/%Y")` không có múi giờ, nên có thể sớm hơn một ngày.
- **Mức độ:** Thấp. **Nhãn:** [Đã xác minh bằng đọc code].
- **Vị trí:** `webapp/api.py:600-608`.

**Đã đọc và thấy đúng:** `/approve` có kiểm `uid == ADMIN_TELEGRAM_ID`, và từ chối khi biến này trống (`feat_premium.py:255-260`). Phần còn lại của `cmd_approve`, `premium_paid_cb`, `feat_payment`: **chưa kiểm**.

---

## Đã đọc / chưa đọc

**Đã lần hết:**
- `webapp/server.py` (bản trước 93b22a3 đọc trọn; bản HEAD đọc các dòng xác thực và `_static`).
- `webapp/api.py`: listings, listing, status, refresh, post, trial, share, propose, xbroker, admin.
- `webapp/api_clients_deals.py`: create/update client, viewing, deal, deals theo tháng, profile, notify, premium request.
- `webapp/share.py`: `handle_booking`, `handle_report`.
- `db/trial.py`, `db/notify.py` (pop/mark), `db/refresh.py` (`flag_false_refresh`, `get_refresh_cooldown`), `db/viewings.py` (`create_viewing`, `client_viewings`), `db/deals.py` (`create_deal`), `db/share.py` (`create_listing_report`, token).
- `feat_match.process_outbox_notifications`, `feat_notify.penalize_*`.
- Đường crash ở bước phường của `feat_intake`, và `locations._load`.
- Danh sách job trong `bot.py`, đăng ký handler trong `bot.py`.

**Chỉ lướt:**
- `feat_viewings.py`: phần ngày/giờ.
- `feat_deals.py`: khoá tháng.
- `morning_brief.py`, `viewing_reminder.py`: đọc phần đầu.
- `feat_premium.cmd_approve`: 25 dòng đầu.
- `parser.py`, `buildings.py`: chỉ các khối gọi danh mục.

**Chưa đụng (chưa kiểm):**
- Luồng 1: `feat_write.py`, `photos.py`, `normalize.py`, `feat_listings.py`, phần lớn `feat_intake.py` (buffer ảnh, đăng tin, chạm đôi).
- Luồng 2: `feat_clients.py`, phần lớn `feat_match.py` (chấm điểm, nhóm, chọn tin), `feat_sendclient.py`, kiểm chủ trong callback của bot, độ dài `callback_data`.
- Luồng 4: `feat_payment.py`, phần lớn `feat_premium.py`, `feat_stale.py`, `followup.py`, `feat_refresh.py`, `feat_evening.py`.
- SQL ghép chuỗi: chưa quét có hệ thống. Các hàm DB đã đọc đều dùng tham số `?`.
- Các lỗi Cao mà phiên sửa khác đang làm (approve gói, kẹt trạng thái Hủy, crash menu, nút xác nhận cũ, buffer ảnh 5 giây): **phiên này không xác minh**; chỉ trùng ở múi giờ hẹn xem (2.1), phạt báo cáo trang chia sẻ (3.3) và outbox (3.4, 3.5).

## Các việc cần dữ liệu thật mới kiểm được
1. Tiến trình bot đang chạy có thiếu `data/danang_locations.json` không (mục 1.1). Kiểm thư mục làm việc của tiến trình và log "No error handlers are registered".
2. Đường hầm Cloudflare có chuyển nguyên `..` tới máy chủ không (mục 3.1). Thử bằng `curl --path-as-is` tới một tệp vô hại trước, đừng thử bằng `token.txt`.
3. Số dòng `outbox_notifications` có `sent_at IS NULL` và loại của chúng (mục 3.4). Câu `SELECT ntype, COUNT(*) ... GROUP BY ntype` chỉ đọc.
4. Bao nhiêu lịch xem đã lưu lệch múi giờ, và lịch nào tạo trước/sau 01/11, để biết dịch +13h hay +14h (mục 2.1).
5. `brokers.false_refresh_reports` và `refresh_cooldown_until` hiện có ai bị phạt từ báo cáo trang chia sẻ chưa (mục 3.3).
6. `clients.requirements_raw` có chứa tên/số điện thoại khách không (mục 3.7).
7. Có tác vụ Windows Task Scheduler nào chạy các script nhắc việc không (mục 4.1): `schtasks /query`.
