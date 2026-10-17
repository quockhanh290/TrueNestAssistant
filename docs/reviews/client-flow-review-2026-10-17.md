# Rà soát mọi thứ liên quan tới khách thuê — TrueNest (17/10/2026)

Phiên C. Đọc trên bản sao đứng yên ở commit `1f9348a` (không đọc thư mục làm việc, nơi phiên khác đang
sửa back end). Hai nhánh giao diện đọc bằng `git show`. Máy chủ webapp chạy thử ở cổng 8097 với
`WEBAPP_DEV=1` trên **DB thử do tôi tự dựng** (sao chép cấu trúc từ DB thật ở chế độ chỉ đọc, xoá hết
dòng, rồi thêm hai môi giới giả, hai căn giả). DB thật lúc đo có 2 môi giới, 3 căn, 0 khách, 0 lịch
xem, 0 trang chia sẻ, 0 lượt đặt lịch, nên mọi phát hiện dưới đây là về **cơ chế**, chưa có khách thật
nào bị ảnh hưởng.

Nhãn: **đã xác minh** (đọc code và chạy thử ra kết quả) · **đã xác minh bằng đọc code** · **nghi ngờ có
căn cứ** · **chưa kiểm**. Phát hiện trùng với hai báo cáo cùng ngày ghi rõ "đã có ở báo cáo luồng mục X"
hoặc "đã có ở báo cáo kiến trúc mục X"; phần chính dành cho cái mới.

## Tóm tắt

**Một câu:** đường duy nhất để khách thật liên hệ môi giới qua TrueNest (form đặt lịch trên trang chia
sẻ) **chưa bao giờ chạy được**, trong khi các đường mà kẻ xấu dùng (gửi thẳng tới máy chủ để spam, chèn
liên kết, phạt môi giới) thì vẫn chạy. Phía bot, hồ sơ khách của một môi giới sửa được bởi môi giới khác
có mã khách, và một dấu `<` trong nhu cầu là đủ làm thẻ khách không mở được.

**Số phát hiện mới** (không tính phần trùng hai báo cáo cùng ngày):

| Mức | Số | Đã xác minh (chạy thử) | Đã xác minh bằng đọc code | Nghi ngờ có căn cứ |
|---|---|---|---|---|
| Nghiêm trọng | 1 | 1 (B1) | | |
| Cao | 6 | 3 (A1, A2, A4) | 3 (B2, B3, A3) | |
| Vừa | 7 | 2 (A5, B6 đo số) | 5 (B8, A6, A8 phần mới, A9, ghi log mã bot ở C3) | |
| Thấp | 9 | 1 (B7) | 6 (B9, A10 phần lớn) | 2 (trong A10) |

Trùng và đã xác nhận lại ở `1f9348a`: B5 (phạt từ báo cáo khách, nay đã giới hạn một lần mỗi link),
C1 (ghi lịch xem/deal vào khách người khác qua web: vẫn còn), C2 / A7 (ngân sách chữ: vẫn còn, và làm
gãy cả danh sách khách trong bot), A8 (nhắc việc chết: vẫn còn; lệch giờ khi đặt lịch trong bot: đã sửa).

**Câu Q7 (trang khách hiện số của ai):** đã trả lời ở B4: **chỉ số của môi giới tạo trang**; không lộ số
chủ nhà, địa chỉ chi tiết, ghi chú nội bộ hay hoa hồng (đã thử).

**Năm việc nên làm trước:**
1. **Sửa đường gửi form trên trang khách** (B1) và thoát ký tự trong tin báo đặt lịch (B2). Hai việc nhỏ,
   cùng một tệp; không có chúng thì trang chia sẻ chỉ là trang xem.
2. **Kiểm chủ khách ở lớp DB** (C1 + A1 + A2): các hàm theo khách nhận thêm mã môi giới và lọc trong SQL,
   thay vì vá từng nút/route. Gỡ cùng lúc: nút ghi chú/sửa của bot, route tạo lịch xem/deal của web, và
   bước phản hồi sau buổi xem.
3. **Thoát HTML mọi trường người dùng gõ** trong tin bot (A3), viết một hàm dùng chung và một test quét.
4. **Sửa so sánh số phòng = 0 của studio** (A4) và **chặn deal trùng** (A5): hai dòng sửa, ảnh hưởng thẳng
   chất lượng ghép và tiền phí.
5. **Giới hạn tần suất đặt lịch/báo cáo** trên trang khách (B6) và **màn xem lượt đặt lịch** cho môi giới
   (B3), để lượt đặt lịch có chỗ hiện ngoài tin Telegram.

**Hai nhánh giao diện:** cả hai **không gộp**. Nhánh trang khách thuê có 1/9 trang có logic, gọi một route
không tồn tại và tự xưng danh bằng dữ liệu không ký; chỉ lấy ý tưởng nghiệp vụ. Nhánh trang môi giới trùng
các màn main đã làm, vẽ thanh tab dưới, 2/4 trang đọc sai dữ liệu trả về. Chi tiết ở mục D.

---

## B. Trang công khai cho khách (`/s/<mã>`)

### B1. Khách bấm "Gửi yêu cầu" hay "Gửi báo cáo" đều không tới máy chủ — **Nghiêm trọng, đã xác minh**
- **Cơ chế:**
  - Link gửi khách có dạng `…/s/AbCdEf123456`, **không có dấu `/` ở cuối** (máy chủ tạo link như vậy ở
    đường tạo trang chia sẻ).
  - Mã JavaScript trong trang gọi `fetch('book')` và `fetch('report')` bằng **đường dẫn tương đối**.
  - Trình duyệt giải đường dẫn tương đối theo "thư mục" của trang. Với `…/s/AbCdEf123456`, thư mục là
    `…/s/`, nên yêu cầu đi tới `…/s/book` chứ không phải `…/s/AbCdEf123456/book`.
  - Máy chủ chỉ nhận `/s/<mã>/book`. `/s/book` không có phần mã, nên trả 404.
- **Đo:** tạo trang chia sẻ thật qua API trên DB thử, giải đường dẫn đúng như trình duyệt
  (`urljoin`): ra `/s/book`. Gửi POST tới đó: **404 `not_found`**. Gửi tới đường đúng
  `/s/<mã>/book`: 200. Nếu link có dấu `/` cuối thì đường giải ra đúng.
- **Kịch bản:** khách mở link qua Zalo, bấm "📅 Đặt lịch xem", điền tên và số, bấm gửi. Màn hình báo
  "⚠️ Gửi thất bại, thử lại sau." (vì trang 404 vẫn trả JSON nên không rơi vào nhánh "lỗi mạng"). Môi
  giới không nhận được gì. "🚩 Báo tin sai" cũng vậy.
- **Hệ quả kéo theo:**
  - Toàn bộ đường "khách đặt lịch → môi giới nhận tin ngay" chưa từng chạy được với khách thật.
  - Trớ trêu: các lỗ lạm dụng mà báo cáo luồng nêu (mục 3.3 phạt tự động, 3.13 spam đặt lịch) vẫn mở,
    vì kẻ xấu gửi POST thẳng tới đúng đường. Chỉ khách thật bị chặn.
  - Nếu môi giới chưa khai số điện thoại, trang ghi "Liên hệ qua TrueNest" mà không có số nào. Cộng với
    form hỏng, khách **không còn cách nào liên hệ**.
- **Không có test nào** chạm vào trang chia sẻ (tìm `handle_booking`, `render_share_page`, `/book` trong
  thư mục test: 0 kết quả). Đó là lý do lỗi sống được.
- **Đề xuất:** trong trang, dựng đường tuyệt đối từ mã: `fetch('/s/' + TOKEN + '/book')` (mã đã có sẵn
  ở máy chủ lúc dựng trang, cần thoát chuỗi cho JS). Không nên chỉ thêm `/` vào link, vì link đã gửi đi
  thì không sửa được, và khách có thể tự xoá dấu `/`.
- **Cổng kiểm (phải đỏ trước khi sửa):** test dựng trang bằng `render_share_page`, lấy URL mà API tạo
  trang trả về, rút đích của `fetch(...)` trong HTML, giải bằng `urljoin(url, đích)`, rồi POST qua
  máy chủ thử: phải 200 và có một dòng đặt lịch. Ở `1f9348a` test này ra 404.

### B2. Tên khách gõ vào form làm hỏng hoặc chèn được nội dung vào tin nhắn báo môi giới — **Cao, đã xác minh bằng đọc code**
- **Cơ chế:** khi khách đặt lịch, bot gửi môi giới tin "📅 Khách vừa đặt lịch xem!" ở chế độ HTML của
  Telegram, ghép **thẳng** tên, số điện thoại, ngày khách gõ, và tên toà nhà vào tin mà không thoát ký tự.
  - Khách gõ tên có dấu `<` hoặc `&` (ví dụ "Lan <3", "Anh & chị Hà"): Telegram từ chối tin vì lỗi phân
    tích HTML. Lỗi bị nuốt vào log, rồi hàng đợi đánh dấu "đã gửi" (đã có ở báo cáo luồng 3.5 về phần
    đánh dấu). Môi giới **mất lượt đặt lịch mà không biết**.
  - Khách (hay kẻ xấu cầm link) gõ tên là `<a href="https://…">Bấm xác nhận</a>`: Telegram hiển thị
    một **liên kết bấm được** trong tin của chính bot TrueNest gửi môi giới. Đây là chỗ lừa đảo dễ
    nhất: tin đến từ bot quen, có chữ "xác nhận".
  - Ô ngày (`preferred_date`) không kiểm định dạng, chỉ cắt 20 ký tự, cũng ghép thẳng.
- **Đã kiểm:** máy chủ lưu đúng nguyên văn (POST tên chứa thẻ `<a>` trả 200, dòng trong DB giữ nguyên).
  Chưa gửi qua Telegram thật; hành vi Telegram với HTML hỏng là hành vi được tài liệu Bot API mô tả.
- **Đề xuất:** `html.escape` cho mọi trường khách gửi và mọi trường của môi giới trước khi ghép vào tin
  HTML; ngày thì kiểm dạng `YYYY-MM-DD`, sai thì bỏ.
- **Cổng kiểm:** test gọi hàm báo đặt lịch với bot giả, tên `"<a href='x'>y</a> & <3"`, khẳng định
  chuỗi gửi đi không còn `<a` thô và `&` đã thành `&amp;`. Ở `1f9348a` test đỏ.

### B3. Môi giới không có chỗ nào xem được lượt đặt lịch; ghi chú của khách không tới tay ai — **Cao, đã xác minh bằng đọc code**
- **Cơ chế:**
  - Tin báo đặt lịch chỉ có tên, số, toà nhà, ngày. **Ghi chú** khách gõ ("khung giờ, yêu cầu…") được
    lưu vào DB nhưng **không có trong tin**.
  - Nút "👀 Xem chi tiết" trong tin mở `…/?view=shares` ở app cũ. App cũ không xử lý `view=shares`
    (chỉ có propose, xbroker, intake, listing, batch), nên mở **danh sách căn**.
  - Mini app v2, màn "Trang đã chia sẻ", chỉ hiện **số lượt** đặt lịch, không hiện tên, số, ngày, ghi
    chú. API có trả danh sách đặt lịch, nhưng không màn nào vẽ ra.
  - Lượt đặt lịch có trạng thái `new` mà không đường nào đổi được, không nối sang khách hay lịch xem.
- **Kịch bản:** tin Telegram báo đặt lịch bị lỡ (B2, hay lỗi mạng ở báo cáo luồng 3.5) là lượt đặt lịch
  đó **không còn đường nào hiện ra** với môi giới, dù vẫn nằm trong DB.
- **Ý định hay tàn dư:** phía API đã chuẩn bị đủ dữ liệu, nên đây là phần giao diện chưa làm, không phải
  thiết kế "chỉ đếm".
- **Đề xuất:** một màn "Lượt đặt lịch" (từ trang đã chia sẻ, ≤ 2 chạm từ trang chính) hiện đủ trường, có
  nút "Tạo khách + lịch xem" từ lượt đặt; tin báo thêm ghi chú (đã thoát) và nút mở thẳng màn đó.
- **Cổng kiểm:** test màn (hoặc test API) khẳng định một lượt đặt lịch mới hiện tên, số, ngày, ghi chú;
  test tin báo có ghi chú.

### B4. Trang khách hiện số điện thoại của ai (câu Q7) — **Đã trả lời, đã xác minh**
- Trang chỉ hiện **số của môi giới tạo trang** (lấy từ hồ sơ môi giới), kèm liên kết `tel:`.
- Không hiện số chủ nhà, địa chỉ chi tiết, nguyên văn bài đăng hay ghi chú nội bộ. Đã thử: căn giả có
  số chủ nhà, địa chỉ "bí mật", ghi chú nội bộ và mức hoa hồng trong dữ liệu; HTML trang khách không
  chứa cái nào trong số đó. Địa chỉ chỉ có tên toà và quận.
- Môi giới chỉ đưa được **căn của chính mình** vào trang (API lọc theo chủ căn; thử thêm căn của môi
  giới khác thì căn đó bị bỏ, trang chỉ còn 1 căn). Nên "số của môi giới tạo trang" cũng là số của
  người giữ căn.
- Hệ quả cho Q7 ở tài liệu độ phủ API: hiện trạng **đã là lựa chọn A** ("luôn số broker"). Câu còn lại
  chỉ là có cho môi giới chọn hay không (lựa chọn B), và khi căn của môi giới khác được phép đưa vào
  trang (luồng liên môi giới) thì số nào hiện.

### B5. Báo cáo sai và luật phạt — **cập nhật so với báo cáo luồng 3.3**
- Đã có ở báo cáo luồng 3.3. Hiện trạng ở `1f9348a` **khác** lúc báo cáo đó viết:
  - Lý do "Tiện ích không đúng thực tế" có trên nút của trang, nhưng không nằm trong danh sách lý do hợp
    lệ của DB, nên máy chủ trả **400 "Lý do không hợp lệ"** (đã thử). Nhánh phạt "tiện ích sai" phía sau
    vì vậy là **mã chết**: không bao giờ chạy. Khách bấm nút đó thì nhận lỗi (đã biết).
  - Lý do "Đã cho thuê": mỗi link chỉ gây được **một** lần phạt tự động (khoá theo mã link, chèn vào
    khoá chính nên bấm song song cũng chỉ thắng một lần). Phần "không chống lặp" của 3.3 đã được sửa.
  - Phần còn mở: phạt vẫn **tự động, không ai xác minh**. Ba link khác nhau (ba khách, hay một đối thủ
    xin được ba link) là ba lần phạt, đủ cấm đề xuất 7 ngày. Báo cáo cũng không đổi trạng thái căn,
    không báo môi giới "khách nói căn đã cho thuê".
- Câu hỏi cho chủ dự án ở cuối tài liệu (phạt tự động hay chờ admin; giữ hay bỏ nút "tiện ích").

### B6. Đặt lịch không giới hạn tần suất — **đã có ở báo cáo luồng 3.13; nay đo được số**
- Đã đo: **200 lần đặt lịch trong 2,6 giây** trên một link, mọi lần đều 200, tạo 200 dòng đặt lịch và
  200 việc báo trong hàng đợi, tức 200 tin Telegram gửi môi giới (bot gửi theo vòng 30 giây, 20 việc
  một lần, nên môi giới bị dội tin suốt khoảng 5 phút).
- Mức độ nâng từ Thấp lên **Vừa**, vì cùng đường đó dùng được để đẩy tin lừa đảo ở B2.
- **Cổng kiểm:** cùng một mã link và cùng số điện thoại, lần thứ hai trong 10 phút không tạo việc báo
  mới; quá N lần/giờ trên một link thì 429.

### B7. Mỗi lần mở trang (kể cả máy xem trước link của Zalo/Telegram) đều tăng "lượt xem" — **Thấp, đã xác minh**
- Mọi GET đều cộng một lượt xem; năm lần tải trang thử là năm lượt. Các ứng dụng chat tự tải link để
  dựng ảnh xem trước, nên số lượt xem môi giới thấy cao hơn số người thật.
- **Đề xuất:** bỏ qua tác nhân của trình xem trước, hoặc đếm khi trang chạy JavaScript.

### B8. Không thu hồi được link, không xoá được dữ liệu khách để lại — **Vừa, đã xác minh bằng đọc code**
- Link sống 30 ngày, không có đường nào cho môi giới huỷ link gửi nhầm người (không có route, không có
  nút).
- Lượt đặt lịch (tên, số điện thoại, ghi chú của người lạ) **giữ vĩnh viễn**: không có hàm xoá, không có
  hạn lưu, không gắn với việc xoá khách.
- **Đề xuất:** route huỷ link (đặt `expires_at = now`) có kiểm chủ; hạn lưu lượt đặt lịch (ví dụ 90
  ngày sau khi link hết hạn) và xoá theo yêu cầu.

### B9. Trang khách không theo chuẩn giao diện của repo — **Thấp, đã xác minh bằng đọc code**
- CLAUDE.md của repo đưa "trang chia sẻ cho khách" vào phạm vi chuẩn thiết kế. Trang hiện viết cứng
  26 mã màu hex trong khối CSS, chỉ có giao diện sáng, và gọi `fetch` trực tiếp.
- Trang này mở ngoài Telegram nên không có `--tg-theme-*`; cần quyết cách áp chuẩn (bộ token sáng/tối
  riêng cho trang ngoài Telegram). Ghi vào câu hỏi.

### B10. Đã kiểm và thấy ổn
- **Mã link:** 9 byte ngẫu nhiên từ `secrets` (12 ký tự, 72 bit), kiểm trùng khi tạo. Đoán mò không khả
  thi. Hết hạn được kiểm ở cả trang và hai đường POST.
- **XSS trên trang khách:** mọi trường của căn và môi giới đi qua `html.escape` (thử tên môi giới chứa
  `<b>`: ra `&lt;b&gt;`). Đường ảnh cũng thoát. Mã căn đặt trong thuộc tính `onclick` được thoát HTML,
  nhưng nếu mã căn có dấu `'` thì vẫn phá được chuỗi JS. Mã căn do hệ thống sinh nên **thấp**.
- **Dữ liệu khách gửi lên** được cắt độ dài (tên 80, số 20, ghi chú 300), lưu bằng tham số `?`.
- **Căn đã gỡ** không hiện trên trang (chỉ hiện căn đang mở).

---

## C. DB và back end cho dữ liệu khách

### C1. Môi giới B ghi được lịch xem, deal vào khách của môi giới A, và A đọc được ghi chú của B — **đã có ở báo cáo luồng 3.6; xác nhận lại phạm vi trên web**
- Đã thử trên DB thử, B đăng nhập bằng mã của B, dùng mã khách của A:

  | Việc B làm với khách của A | Kết quả |
  |---|---|
  | Xem chi tiết khách | 404 (có kiểm chủ) |
  | Sửa khách | 404 (có kiểm chủ) |
  | Thêm ghi chú | 404 (có kiểm chủ) |
  | **Tạo lịch xem** gắn khách của A, căn của B, ghi chú tuỳ ý | **200** |
  | **Tạo deal** gắn khách của A, **căn của A**, hoa hồng 15tr | **200** |

  Sau đó A mở hồ sơ khách: thấy lịch xem lạ với căn của B và nguyên văn ghi chú B gõ.
- Chiều ngược lại (B đọc dữ liệu của A): không thấy đường web nào. Màn "Hôm nay" chỉ hiện tên khách khi
  khách thuộc người gọi; danh sách liên môi giới không trả mã khách.
- Mã khách là `cli:` + 12 ký tự hex (48 bit ngẫu nhiên): **không đoán mò được**. Muốn khai thác phải có
  mã. Trên web, tôi không thấy đường nào lộ mã khách cho môi giới khác (danh sách yêu cầu liên môi giới
  và trang đề xuất không trả mã khách). Phía bot: xem mục A.
- Lớp DB: **mọi** hàm theo một khách (lấy, sửa, ghi chú, gắn căn, ghi căn đã gửi, ghi lựa chọn, xoá,
  lịch xem của khách) chỉ lọc theo mã khách, không theo môi giới. Kiểm chủ hoàn toàn dựa vào người gọi.
  Nên mỗi đường gọi mới (bot hay web) là một chỗ có thể quên.
- **Đề xuất (thay vì vá từng route):** thêm tham số `broker_id` bắt buộc vào các hàm DB theo khách và
  đưa điều kiện `AND broker_id = ?` vào câu SQL; route tạo lịch xem/deal kiểm khách và từng căn.
- **Cổng kiểm:** test hai môi giới giả: B tạo lịch xem/deal với khách của A phải 404; `client_viewings`
  của A không trả lịch do B tạo.

### C2. Ngân sách dạng chữ làm mất cả danh sách khách — **đã có ở báo cáo kiến trúc 1.2; vẫn còn ở `1f9348a`**
- Đã thử lại: sửa khách với ngân sách `"15tr"` trả 200; ngay sau đó danh sách khách và chi tiết khách
  **đóng kết nối không trả gì**. Sửa lại thành số thì hồi phục.
- Thêm một biến thể: tạo lịch xem với giờ hẹn là chữ (`"mai 3h"`) cũng trả 200; lịch đó nằm trong
  danh sách "sắp tới" **mãi mãi** (SQLite xếp chữ lớn hơn mọi số) và không bao giờ hiện ở "Hôm nay"
  (đã có ở báo cáo kiến trúc 1.3 về họ lỗi này).

### C3. Dữ liệu cá nhân của khách nằm ở đâu, có lộ ra ngoài không — **đã xác minh bằng đọc code**
| Nơi | Có gì | Ai đọc được |
|---|---|---|
| Bảng khách | tên, số điện thoại, nguyên văn yêu cầu, ghi chú, căn đã gửi | chủ khách (đã kiểm chủ ở web) |
| Bảng lịch xem, deal | tên khách gõ lại, ghi chú | chủ dòng; và chủ khách nếu dòng gắn mã khách của họ (C1) |
| Bảng yêu cầu ghép | bản tóm tắt nhu cầu (không tên, không số) | mọi môi giới trong nhóm, đúng thiết kế |
| Trang đề xuất | **nguyên văn yêu cầu** khách | mọi môi giới có mã yêu cầu (đã có ở báo cáo luồng 3.7) |
| Bảng lượt đặt lịch | tên, số, ghi chú người lạ | chủ trang qua API; giữ vĩnh viễn (B8) |
| Hàng đợi báo | tên, số khách đặt lịch | chỉ nội bộ; dòng không bao giờ bị xoá |
| Log | — | không thấy dòng log nào in tên/số khách (tìm mọi `log.*(` có name/phone/raw: 0 kết quả). Log máy chủ webapp in đường dẫn, nên có **mã link chia sẻ** (đã có ở báo cáo luồng 3.11 về initData trên URL) |

- **Xoá:** bot có xoá khách, web không có. Xoá khách để lại lịch xem, deal, yêu cầu ghép (đã có ở báo
  cáo kiến trúc 1.4). Không có cách xoá lượt đặt lịch hay dòng hàng đợi.
- **Ghi chú ngoài phạm vi khách nhưng nặng:** bot đặt log ở mức INFO cho mọi thư viện. Thư viện `httpx`
  mà bot Telegram dùng in mỗi yêu cầu kèm **URL đầy đủ**, và URL của Bot API có **mã bot** trong đó
  (`api.telegram.org/bot<mã>/…`). Đã thử cơ chế với `httpx 0.28.1`: dòng log in nguyên URL kèm tham số.
  Hiện log không được ghi ra đâu (báo cáo kiến trúc 3.2), nhưng ngày bật ghi log là ngày mã bot nằm
  trong tệp log. Đề xuất: đặt logger `httpx` ở mức WARNING ngay cạnh `basicConfig`. Cổng kiểm: test bắt
  log khi gọi `httpx` giả, không có dòng nào chứa `/bot`.

---

## A. Luồng khách trong bot

Cách lần: bot chỉ đăng ký **một** bộ xử lý nút bấm chung, không có mẫu lọc; mọi nút được phân nhánh
bằng chuỗi `if/elif` dài trong `bot.py`. Tin nhắn chữ đi qua một hàm duy nhất, xét lần lượt từng "bước
đang dở" lưu trong bộ nhớ phiên của môi giới. Không có hội thoại nhiều bước kiểu ConversationHandler,
không có việc định kỳ nào ngoài bộ đọc hàng đợi 30 giây. Phép đo: một script dựng hai môi giới giả trên
DB tạm, gọi thẳng hai hàm xử lý thật của bot (nút và chữ); một script khác đẩy **379** mã nút có trong
code qua bộ phân nhánh thật để tìm nút chết. Bộ test sẵn có `test_flows` + `test_high_fixes`: 95 qua,
1 hỏng do thiếu tệp môi trường (không thuộc phạm vi này).

### A1. Trong bot, môi giới B ghi chú, sửa tên/số khách của A, và đọc được số điện thoại cùng ghi chú nội bộ của A — **Cao, đã xác minh**
- **Cơ chế:** nút "Thêm ghi chú" và nút "Sửa" (từng trường) của thẻ khách chỉ kiểm "khách có tồn tại",
  **không kiểm khách thuộc ai**. Mã khách nằm trong dữ liệu nút, mà dữ liệu nút do ứng dụng Telegram gửi
  lên nên giả được. Sau khi ghi, bot in lại **toàn bộ thẻ khách** cho người bấm.
- **Đã đo:** B gửi nút ghi chú với mã khách của A rồi gõ chữ: ghi chú của B vào hồ sơ khách A, và B nhận
  lại thẻ có số điện thoại khách và ghi chú nội bộ của A ("hoa hồng nội bộ 50%"). B gửi nút sửa tên rồi
  sửa số: khách của A đổi tên và đổi số, vẫn đứng tên A.
- Thêm: nút Xoá lộ tên khách; nút sửa số lộ số hiện tại; nút "xác nhận xoá" của B trả lời "Em đã xoá khách
  rồi" dù không xoá gì (bot nói sai, dữ liệu còn).
- Các nút **đã kiểm chủ đúng:** xem chi tiết, đổi trạng thái, mức gấp, ghép tin, gửi tin, xác nhận xoá,
  đặt lịch, deal.
- **Điều kiện:** B phải có mã khách (48 bit ngẫu nhiên). Không thấy kênh nào trong bot hay web lộ mã khách
  cho môi giới khác (tin nhóm và trang liên môi giới chỉ mang mã yêu cầu). Vì vậy Cao, chưa Nghiêm trọng.
  Nếu sau này mã khách xuất hiện ở bất kỳ đâu ngoài chủ (ví dụ một link, một màn liên môi giới), mức này
  thành Nghiêm trọng.
- Mới so với hai báo cáo cùng ngày (báo cáo luồng ghi "kiểm chủ trong callback của bot: chưa kiểm").
- **Đề xuất:** kiểm chủ ở cả 5 nút (ghi chú, trạng thái, sửa, sửa trường, xoá) **và** kiểm lại ở bước
  nhận chữ; tốt hơn là hàm DB "lấy khách của tôi" nhận cả mã môi giới (cùng hướng với C1).
- **Cổng kiểm:** B bấm ghi chú/sửa trường trên khách của A: DB không đổi và không tin trả lời nào chứa số
  của khách A. Script đo hiện cho kết quả ngược lại (đỏ).

### A2. Lịch xem B gắn vào khách của A (qua web, C1) kéo theo bot đổi trạng thái khách của A — **Cao, đã xác minh**
- Trong bot, mọi đường tạo lịch xem và deal đều kiểm chủ khách và căn. Nguồn lỗi là hai route web (C1).
- Nhưng khi B nhập phản hồi sau buổi xem cho lịch đó trong bot, bot chỉ kiểm **lịch** thuộc B, rồi ghi
  "đã liên hệ" và đổi trạng thái **khách của A** thành "Đã xem". Đã đo.
- **Cổng kiểm:** lịch của B trỏ vào khách A, B nhập phản hồi: trạng thái khách A không đổi.

### A3. Môi giới gõ "<15tr" vào nhu cầu là thẻ khách không mở được nữa — **Cao, đã xác minh bằng đọc code và đo chuỗi**
- **Cơ chế:** bot gửi thẻ khách, danh sách khách, tin soạn cho khách, lịch xem ở chế độ HTML của
  Telegram. Trong các tệp khách, gửi khách, lịch xem, deal: 24+ chỗ dùng HTML và **0** chỗ thoát ký tự.
  Tên, nguyên văn nhu cầu, ghi chú được ghép thẳng.
- **Kịch bản:** "2PN <15tr Sơn Trà" là cách viết rất phổ biến. Chế độ hướng dẫn và chế độ dán đều lưu
  nguyên văn. Thẻ dựng ra chứa nguyên `<15tr` (đã đo). Telegram từ chối tin có thẻ HTML hỏng, nên bấm vào
  khách đó chỉ nhận câu xin lỗi chung chung, **mãi mãi** cho tới khi sửa nhu cầu. Tên "Tom <3" ở chế độ
  hướng dẫn hay khi sửa tên cũng vậy (chế độ dán chỉ lấy chữ cái làm tên nên an toàn).
- Cùng họ với B2 (phía trang khách). Phía ghép liên môi giới thì có thoát ký tự (5 chỗ).
- Phản ứng thật của Telegram chưa thử trên máy thật.
- **Cổng kiểm:** dựng thẻ, danh sách, tin soạn cho khách tên `Tom <3`, nhu cầu `<15tr`: kết quả không còn
  `<` lẻ.

### A4. Khách tìm studio được ghép với cả căn 2 phòng ngủ — **Cao, đã xác minh**
- **Cơ chế:** hàm đọc số của bộ ghép viết "nếu có giá trị thì đổi ra số, không thì coi như không có". Số
  phòng của studio là **0**, mà 0 bị coi là "không có". Từ đó lọc cứng bỏ qua điều kiện phòng, chấm điểm
  cộng 20 điểm "trung tính" cho mọi căn, và danh sách môi giới được mời cũng không lọc số phòng.
- Màn tìm của chính thẻ khách thì viết đúng (so với "không có" thay vì so với 0). Hai nơi lệch nhau; ghi chú
  trong mã nói "khớp chính xác", nên đây là tàn dư cách viết, không phải ý thiết kế.
- **Đã đo:** khách studio, 10tr, Sơn Trà: căn 2PN và căn studio đều qua lọc cứng, cả hai 63 điểm.
- **Cổng kiểm:** khách studio thì căn 2PN phải trượt lọc cứng.

### A5. Một deal bị ghi hai lần hoa hồng và hai lần nhắc chuyển phí — **Vừa, đã xác minh**
- Đổi trạng thái khách sang "Đã thuê" hoặc "Ký hợp đồng" đều tự hỏi hoa hồng; không bước nào kiểm "đã có
  deal cho khách và căn này chưa" (hàm kiểm có sẵn nhưng chỉ dùng cho gợi ý).
- **Đã đo:** "Đã thuê" → 15tr, rồi "Ký HĐ" → 15tr: hai deal cùng khách cùng căn, hai lần gửi hướng dẫn
  chuyển phí nền tảng.
- **Cổng kiểm:** hai lần đổi trạng thái vẫn chỉ một deal.

### A6. Bước đang dở của luồng khác ăn mất tin nhắn khách — **Vừa, đã xác minh bằng đọc code**
- Bộ xử lý chữ xét các bước của **tin đăng** (đang hỏi giá, đang xác nhận, đang sửa) **trước** bước thêm
  khách. Lệnh `/clients`, `/viewings`, `/commission` và các nút thêm khách, ghi chú, sửa trường không giải
  phóng bước đang dở; bước dở không có hạn.
- **Kịch bản:** bot đang hỏi "giá bao nhiêu?" cho một tin đăng; môi giới gõ /clients, thêm khách, dán
  "Anh Tuấn 0901… cần 2PN dưới 15tr": tin dán bị lấy làm câu trả lời giá. Hoặc bấm "Thêm ghi chú" rồi bỏ
  đó; hôm sau dán một tin cho thuê, tin đó thành ghi chú của khách cũ.
- Danh sách khoá cần dọn thì đã đủ; chỉ thiếu lời gọi dọn ở các lối vào.
- **Cổng kiểm:** đang có bước hỏi giá, gõ /clients → thêm khách → dán: khách được tạo.

### A7. Ngân sách dạng chữ — **đã có ở báo cáo kiến trúc 1.2**
- Mọi đường ghi trong bot ra số. Đường ghi chữ duy nhất là route sửa khách của web (C2). Phía bot, chữ đó
  làm hàm định dạng giá ném lỗi, nên **danh sách khách trong bot cũng gãy**, không chỉ trên web (mới:
  báo cáo kiến trúc chỉ nêu phía web). Khách thiếu tên/số/ngân sách: mọi màn đã đọc có chữ thay thế,
  không gãy.

### A8. Bot hứa nhắc nhưng không ai nhắc — **đã có ở báo cáo luồng 4.1 và 2.1; thêm hai điểm mới**
- Bot vẫn nói "Em sẽ nhắc trước 1 tiếng" (đặt lịch xem, gửi khách) và "2 ngày nữa em sẽ nhắc" (gửi khách).
  Không gì thực hiện: 9 tệp nhắc/tóm tắt có **0** lời gọi gửi tin.
- **Đã sửa so với báo cáo luồng 2.1:** các đường đặt lịch trong bot nay đổi giờ theo giờ Việt Nam (đo "mai
  9h" ra 18/10 09:00 giờ VN).
- **Mới:** script nhắc lịch xem vẫn in giờ theo giờ máy (đo: máy 05:01, Việt Nam 18:01); và không có cột
  "đã nhắc", nên nếu chạy mỗi 15 phút với cửa sổ 1 giờ sẽ nhắc tới **4 lần** một lịch.
- **Cổng kiểm:** việc nhắc gửi đúng một lần cho một lịch, giờ hiển thị theo VN. Hoặc, nếu chưa làm nhắc:
  test không còn câu "em sẽ nhắc" trong tin.

### A9. Tin soạn gửi khách có thể mang số điện thoại chủ nhà — **Vừa, đã xác minh bằng đọc code**
- Nút "gửi căn này cho khách" trong thẻ khách soạn tin với dòng liên hệ là **số môi giới, thiếu thì lấy
  số trong tin đăng**, thường là số chủ nhà. Môi giới chưa khai số là khách nhận số chủ nhà và đi thẳng.
- Nút này cũng không kiểm căn thuộc ai (kiểm khách thuộc mình, không kiểm căn).
- Đường "gửi khách" chính (chọn nhiều căn) thì sạch: không số, không ghi chú, không hoa hồng.
- **Cổng kiểm:** môi giới không có số thì tin soạn không chứa số trong tin đăng.

### A10. Lỗi nhỏ — **Thấp**
- **Nút chết:** "⬅️ Menu" ở màn cài đặt thông báo và màn giới thiệu bạn bè không có nhánh xử lý; bấm chỉ
  giải phóng bước rồi im lặng (ngoài phạm vi khách, script tìm ra). Mọi nút của luồng khách đều có nhánh.
- **Nhánh mồ côi:** hai nút "tóm tắt tối" có nhánh xử lý nhưng không ai gửi nút đó; nút chọn tin trong
  luồng ghép cần một khoá mà code thật không đặt ở đâu, nên luôn báo "hết hạn" (việc chọn tin đã chuyển
  sang web).
- **Trả lời nút hai lần:** vài nút trả lời nút một lần rồi lại trả lời lần nữa để hiện cảnh báo ("Tối đa 4
  căn"); Telegram chỉ nhận lần đầu, nên cảnh báo khả năng cao không hiện. Nghi ngờ có căn cứ.
- **Mã căn trong nút không đối chiếu danh sách ứng viên** (chọn căn gửi khách, chọn căn cho lịch xem): gắn
  được căn của người khác vào tin hay lịch; tin gửi đi không lộ số.
- **Đặt lịch giờ đã qua:** nút "Hôm nay 08:00" bấm lúc 15:00 vẫn được.
- **Giá không hiện trong lời nhắc hoa hồng:** hàm đọc khoá giá cũ, khoá thật là giá VND. Nghi ngờ có căn cứ.
- **Cặp deal gợi ý có thể chứa căn của người khác**, bấm vào thì báo "không còn hợp lệ".
- **Lượt thử "gửi khách" lệch giữa bot và web:** web cho 3 lượt thử; bot chặn cứng gói Pro, kể cả nút
  nhắc theo dõi được khai là miễn phí. Cần chủ dự án quyết (đã có câu Q10 ở tài liệu độ phủ API).

---

## D. Hai nhánh giao diện

Nền: cả hai nhánh tách từ `de0f470`; main đã đi thêm 21 commit. Số tệp cả nhánh lẫn main cùng sửa: **0**.
`git merge-tree` ra cây sạch cho cả hai, tức gộp **không xung đột về chữ**. Xung đột là về **hướng**.

### D1. Nhánh trang khách thuê (`ui-client-flow`) — chỉ lấy làm ý tưởng
- 9 trang (đề xuất, wishlist, so sánh, concierge, thị trường, môi giới, checklist, hướng dẫn, trả căn).
  **8 trang là vỏ rỗng** 58 dòng giống hệt nhau, chỉ khác tiêu đề: có phần đầu trang, mở một khối rồi hết,
  không có nội dung hay mã chạy.
- Trang duy nhất có logic là **đề xuất** (127 dòng): lướt từng căn, tối đa 15 căn, sau 30 lượt gợi ý
  "sửa yêu cầu", thêm vào wishlist.
  - Gọi `/api/proposals`: **route này không có** ở máy chủ main.
  - Xác định người xem bằng `initDataUnsafe.user.id` gắn vào URL dạng `tg_user_id=` (đã đối chiếu dòng).
    Vi phạm thẳng luật A5 của repo. Hơn nữa, mọi `/api/` ở main đòi chữ ký initData **của một môi
    giới**; khách không phải môi giới, nên kể cả có route, trang sẽ nhận 401. Trang không xử lý 401 hay
    lỗi mạng.
  - Nút sang trang "intake" (sửa yêu cầu) trỏ tới tệp không có trong nhánh; concierge chỉ là
    `alert('Concierge: 250K/tin')`.
- Vi phạm chuẩn giao diện ở mọi tệp: mã màu viết cứng, phông tuỳ biến (Be Vietnam Pro, Space Grotesk),
  tự bật toàn màn hình, tắt vuốt-đóng vĩnh viễn, chặn chọn chữ toàn trang, màu thanh đầu viết cứng.
- **Luồng dự định có khớp back end không: không.** Back end không có bảng người thuê, bảng đề xuất cho
  người thuê, wishlist hay concierge; không có cách xác thực người thuê (danh tính duy nhất của khách
  hiện nay là mã link `/s/<mã>`, gắn với môi giới, không gắn với người). Tài liệu điều hướng đã duyệt
  ghi `/s/<mã>` "không thuộc mini app, chỉ là đích"; đặc tả bot khách ghi "build sau".
- **Thiếu để luồng chạy được:** (1) định danh người thuê (đăng nhập bằng initData của chính khách qua
  một bot/mini app khách, hoặc mã link riêng cho từng khách); (2) bảng đề xuất gắn khách thuê – căn –
  môi giới, có trạng thái đã xem / thích / bỏ; (3) route `/api/tenant/...` với lớp xác thực riêng, không
  dùng chung quyền môi giới; (4) quy định số của ai hiện cho khách (Q7) khi căn đến từ nhiều môi giới;
  (5) cách thu phí concierge.
- **Kết luận:** không gộp tệp nào. Lấy ý tưởng nghiệp vụ (giới hạn 15 căn, ngưỡng 30 lượt gợi ý sửa yêu
  cầu, wishlist, so sánh) vào một đặc tả luồng khách thuê, rồi dựng sau khi có thiết kế back end khách.

### D2. Nhánh trang môi giới (`ui-broker-flow`) — không gộp
| Trang | Thực chất | Ghi chú |
|---|---|---|
| Khách | có gọi API danh sách/thêm khách (route có ở main) | thêm khách bằng hộp `prompt()` của trình duyệt |
| Lịch xem | có gọi API (route có) | phần lớn khớp dữ liệu trả về |
| Hoa hồng | có gọi API (route có) nhưng **đọc sai khoá**: chờ `deals`, `total_commission`; máy chủ trả `closed`, `negotiating`, `month_total` | danh sách luôn rỗng, tổng luôn "—" |
| Trang đã chia sẻ | có gọi API nhưng in `url`, mà máy chủ không trả `url`; chỉ gửi `tg_user_id`, không gửi initData | ngoài chế độ thử sẽ 401 |
| Hồ sơ, đề xuất, cài đặt, nâng cấp, liên môi giới | vỏ rỗng 58 dòng | |

- Cả 4 trang có nội dung đều vẽ **thanh tab dưới cố định** và nút "+" trên đầu, tự viết `apiUrl`/`fetch`,
  gửi initData trên URL: trái A3, A5, B8 và tài liệu điều hướng đã duyệt (trang chính → trang con, không
  tab dưới).
- Main đã có đủ các màn này trong mini app v2 (khách, lịch xem, hoa hồng, trang đã chia sẻ, liên môi
  giới, hồ sơ) theo token màu và lớp gọi API chung, cùng 22 mẫu đã duyệt.
- **Kết luận:** không gộp. Giá trị còn lại là hai chỗ lệch hợp đồng API ở trên, để nhớ khi viết màn
  tương ứng ở main.

---

## Câu hỏi cần chủ dự án quyết

| # | Câu hỏi | Lựa chọn | Khuyến nghị |
|---|---|---|---|
| C-Q1 | Khách báo "đã cho thuê" thì phạt môi giới **tự động** hay **chờ admin duyệt**? | **A.** giữ tự động, mỗi link một lần (hiện trạng). **B.** báo cáo vào hàng chờ `/baocao`, admin bấm mới phạt. **C.** tự động nhưng chỉ khi ≥ 2 link khác nhau cùng báo trong 7 ngày | **B** cho tới khi có người dùng thật: hiện chưa có cách nào biết người báo là khách thật; ba link là đủ cấm đề xuất 7 ngày |
| C-Q2 | Nút "Tiện ích không đúng thực tế" trên trang khách | **A.** bỏ nút (máy chủ đang từ chối, nhánh phạt là mã chết). **B.** thêm vào danh sách hợp lệ nhưng **không phạt**, chỉ lưu cho admin. **C.** thêm và phạt như "đã cho thuê" | **B**: giữ tín hiệu, không mở thêm đường phạt không xác minh |
| C-Q3 | Trang khách (mở ngoài Telegram) áp chuẩn giao diện thế nào? | **A.** bộ token sáng/tối riêng, theo `prefers-color-scheme`, cùng tên biến với `tokens.css`. **B.** giữ như hiện tại (sáng, màu viết cứng) | **A**, nhưng làm sau B1/B2 |
| C-Q4 | Lượt đặt lịch và trang chia sẻ giữ dữ liệu người lạ bao lâu? | **A.** vĩnh viễn (hiện trạng). **B.** xoá 90 ngày sau khi link hết hạn; môi giới huỷ link được bất cứ lúc nào | **B** |
| C-Q5 | Luồng khách thuê (đề xuất 15 căn, wishlist, so sánh) dựng khi nào, và khách đăng nhập bằng gì? | **A.** bot/mini app riêng cho khách, khách đăng nhập bằng initData của chính họ. **B.** mã link riêng cho từng khách (không cần Telegram). **C.** để sau, chỉ giữ trang chia sẻ | Chưa khuyến nghị A hay B: phụ thuộc khách ở Đà Nẵng dùng Zalo hay Telegram (chưa có số đo). Trước mắt **C**, và viết đặc tả |
| C-Q6 | Bot hứa "em sẽ nhắc trước 1 tiếng" mà chưa có việc nhắc | **A.** nối việc nhắc vào hàng việc định kỳ của bot (giờ VN, cột "đã nhắc"). **B.** bỏ câu hứa khỏi tin cho tới khi có | **B** ngay (một dòng), **A** khi làm nhắc việc |

---

## Đã đọc / đã đo / chưa làm
**Đã đọc trọn:** trang khách (`webapp/share.py`), lớp DB trang chia sẻ (`db/share.py`), máy chủ webapp
(`webapp/server.py`), phần khách/lịch xem/deal của `webapp/api_clients_deals.py`, phần chia sẻ/đề xuất/liên
môi giới/hôm nay của `webapp/api.py`, danh sách hàm của `db/clients.py`, `db/viewings.py`, `db/deals.py`,
bộ đọc hàng đợi và các hàm phạt/báo đặt lịch phía bot. Phía bot (đọc qua một phiên phụ, tôi kiểm lại
từng dòng của A1, A4, A5, A9): đăng ký nút trong `bot.py`, `feat_clients.py`, phía khách của
`feat_match.py`, `feat_sendclient.py`, `feat_viewings.py`, `feat_deals.py` phần nối khách. Hai nhánh: mọi
tệp thêm mới (đọc qua phiên phụ; tôi kiểm lại dòng xưng danh của trang đề xuất và dòng thanh tab dưới,
khoá dữ liệu của trang hoa hồng).

**Đã đo (máy chủ thử cổng 8097, DB thử tự dựng, đã tắt):**
- B1: đường giải tương đối `/s/book` → 404; đường đúng → 200.
- B4: HTML trang khách không chứa số chủ nhà, địa chỉ, ghi chú nội bộ của căn giả; căn của người khác bị
  loại khỏi trang.
- B5: lý do "tiện ích" → 400.
- B6: 200 lần đặt lịch / 2,6 giây, 200 việc báo.
- B7: 5 lần tải trang = 5 lượt xem.
- C1: bảng 5 thao tác của B lên khách của A.
- C2: ngân sách chữ → danh sách và chi tiết khách đóng kết nối rỗng; giờ hẹn chữ → 200.
- C3: `httpx` in nguyên URL ở mức INFO.
- Bot: script hai môi giới giả gọi bộ xử lý thật (A1, A2, A4, A5, A7, A8 phần giờ), script 379 mã nút.
  Script ở `scratchpad\c\agentA\`.

**Chưa làm:**
- Chưa gửi tin qua Telegram thật: lỗi phân tích HTML (A3, B2) và trả lời nút hai lần (A10) là theo mô tả
  của Bot API, chưa thử máy thật.
- Chưa mở trang khách trong trình duyệt thật (B1 đo bằng cách giải đường như trình duyệt, cộng POST thật).
  Cổng kiểm cuối cho B1 nên là mở link trên điện thoại.
- Phía bot chỉ đọc lướt: phần nhận trả lời trong nhóm, chuyển tiếp và kết nối hai môi giới của
  `feat_match`; phần làm giàu dữ liệu tin của `feat_clients`; mẫu tin (`feat_templates`, nút mẫu theo
  khách chưa kiểm chủ); cách tính ngày trong các script nhắc/tóm tắt (đã xác nhận chúng không gửi gì).
- Không đọc các trang v2 ngoài màn "Trang đã chia sẻ" và router.
- Có thể còn cái tôi chưa nghĩ tới: ba vùng chỉ đọc lướt ở trên là nơi nên rà tiếp.

## Quyết định của chủ dự án (17/10/2026)

| Câu | Quyết định |
|---|---|
| C-Q1 Phạt khi khách báo "đã cho thuê" | Không phạt tự động nữa: báo cáo vào hàng chờ, admin duyệt qua /baocao (phạt hoặc bỏ qua). |
| C-Q2 "Tiện ích không đúng thực tế" | Lưu báo cáo, không phạt; môi giới và admin thấy để sửa tin. |
| C-Q4 Dữ liệu người lạ đặt lịch | Xoá 90 ngày sau khi link hết hạn; môi giới huỷ được link. Khách môi giới đã lưu không bị đụng. |
| C-Q5 Luồng khách thuê | Để sau; viết đặc tả trước. Nhánh ui-client-flow và ui-broker-flow không gộp. |
| C-Q3 Giao diện trang khách | Theo khuyến nghị (chưa hỏi riêng): bộ token sáng/tối riêng, làm sau B1/B2. |
| C-Q6 Câu hứa "nhắc trước 1 tiếng" | Theo khuyến nghị (chưa hỏi riêng): bỏ câu hứa ngay; nối việc nhắc (giờ VN, cột "đã nhắc") khi làm. |
