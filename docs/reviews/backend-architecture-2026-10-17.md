# Rà soát kiến trúc cơ sở dữ liệu và back end — TrueNest (17/10/2026)

Phiên R. Chỉ đọc mã và thử trên **bản sao** cơ sở dữ liệu. Không sửa mã, không chạm tiến trình đang chạy
hay cổng 8080. Đối chiếu commit `262c142`. Đo lúc 04:13 giờ máy (Calgary, MDT) = 17:13 giờ Việt Nam, 17/10.

Cơ sở đo: DB thật mở chỉ đọc rồi chép bằng `backup()` vào thư mục nháp của phiên. DB thật nặng 336 KB:
2 môi giới, 3 căn, 0 khách, 0 lịch xem, 0 deal. Mọi phép thử đua ghi và lỗi kiểu chạy trên bản sao;
webapp thật được chạy thử ở cổng 8095, trỏ vào bản sao, `WEBAPP_DEV=1`, rồi tắt (đã kiểm: cổng 8095 trống
sau khi xong). Bộ test hiện tại: **123 bài đạt, 1 bài trượt** (bài nhập theo bước thiếu tệp danh mục phường,
đã biết từ báo cáo luồng).

Phiên bản: SQLite 3.42.0, Python 3.11.4.

---

## Tóm tắt

| Nhóm | Cao | Vừa | Thấp |
|---|---|---|---|
| 1. Toàn vẹn dữ liệu và migration | 2 | 4 | 0 |
| 2. Ghi đồng thời | 0 | 2 | 1 |
| 3. Xử lý lỗi, quan sát, outbox | 2 | 1 | 0 |
| 4. Ranh giới tầng và hợp đồng API | 0 | 2 | 2 |
| 5. Hosting, sao lưu, đường lên Postgres | 2 | 0 | 3 |
| **Tổng (21)** | **6** | **9** | **6** + 3 ghi chú |

Không có mục nào ở mức nghiêm trọng: dữ liệu hiện còn rất nhỏ, và các lỗ hổng lộ dữ liệu đã được sửa
từ trước. Nhãn: **19 mục đã xác minh** (đo hoặc đọc đủ đường chạy) và **2 mục nghi ngờ có căn cứ**
(2.3, 5.4). Trong các mục đã xác minh vẫn còn bốn ý phụ chưa kiểm, và chỗ nào cũng ghi rõ:
- giao diện có gửi chữ vào trường số không (1.2);
- 3 căn bị điền dữ liệu giả là căn thật hay căn thử (1.6);
- hai tiến trình cùng chạy ALTER một lúc (1.5);
- đường hầm đã đổi địa chỉ bao nhiêu lần (5.1).

**Năm việc nên làm trước:**
1. Mọi ngoại lệ trong máy chủ webapp phải trả về JSON 500, kèm ghi log ra tệp (mục 3.1, 3.2).
2. Chặn sai kiểu ngay tại cơ sở dữ liệu bằng trigger kiểm `typeof` trên các cột thời gian và cột số.
   Cách này không phải dựng lại bảng (mục 1.1).
3. Kiểm kiểu đầu vào ở lớp db cho khách, lịch xem và căn. Hiện webapp **tự mình** ghi chữ vào cột số
   mà không cần script nào (mục 1.2).
4. Lượt dùng thử phải được trừ bằng một câu lệnh nguyên tử có điều kiện (mục 2.1).
5. Trước khi có người dùng thật: sao lưu hằng ngày, và một tên miền cố định cho link chia sẻ khách
   (mục 5.1, 5.2).

---

## Ca 17/10: tầng nào lẽ ra phải chặn

**Chuyện đã xảy ra.** Hai script sửa tay mở thẳng tệp DB bằng `sqlite3.connect` rồi ghi
`updated_at = datetime('now')`. Biểu thức đó sinh ra chuỗi chữ `"2026-10-17 07:57:09"`, trong khi mọi chỗ
khác của hệ thống lưu thời gian dưới dạng số giây. Hai màn "Hôm nay" và "Hồ sơ" lấy hiệu
`now - updated_at`, gặp phép trừ số với chữ thì ném TypeError, và kết nối bị đóng mà không trả về gì.

Tôi dựng lại đúng ca này trên bản sao. Ghi chuỗi đó vào một căn thì `/api/today` và `/api/profile` đóng
kết nối rỗng. Chín màn còn lại vẫn trả 200, vì chúng chỉ chuyển giá trị đi chứ không tính toán gì với nó.

Có năm tầng lẽ ra chặn được, và cả năm đều để lọt:

| Tầng | Hiện trạng (đã xác minh) | Lẽ ra |
|---|---|---|
| **Kiểu cột** | Cột khai `REAL`, nhưng SQLite chỉ "ưu tiên" kiểu chứ không ép. Thử bốn giá trị: chuỗi ngày → lưu thành chữ; `"1760000000"` → tự đổi thành số; `"15tr"` → chữ; byte → blob. Schema không có CHECK nào, cũng không dùng bảng STRICT. | Đây là chốt duy nhất mà **mọi** đường ghi đều phải đi qua, kể cả script, DB Browser hay phiên khác. Trigger `BEFORE INSERT/UPDATE … WHEN typeof(NEW.updated_at) NOT IN ('real','integer')` đã được thử trên bản sao: nó chặn đúng câu `datetime('now')` của 17/10 và vẫn cho số đi qua. |
| **Lớp db** | `update_listing()` tự ghi `updated_at = time.time()`, nên đi qua lớp db thì không có lỗi. Nhưng lớp db không kiểm kiểu của bất cứ thứ gì nó nhận vào (xem 1.2). | Lớp db là nơi duy nhất nắm kiểu của từng cột, nên phải kiểm và ép kiểu ở đây. |
| **Script đi vòng** | Cả ba script trong `scripts/` tự mở `sqlite3.connect`, không dùng `db.connect`. Đường dẫn DB mặc định là tương đối, nên chạy nhầm thư mục là tạo ra một DB rỗng mới. Không có quy ước "sao lưu trước khi sửa tay". | Script sửa dữ liệu phải gọi hàm của lớp db, hoặc ít nhất mở qua `db.connect`. Chạy xong phải chạy lại bộ kiểm bất biến dữ liệu. |
| **Phía đọc** | Một dòng sai làm sập **cả màn hình** của môi giới đó, không có cách cô lập theo từng dòng. Máy chủ không bắt ngoại lệ, nên trình duyệt chỉ thấy kết nối rơi và màn hình báo "lỗi mạng". | Lỗi phải hiện ra là lỗi máy chủ (500) và ghi log có traceback. Không nên lặng lẽ bỏ qua dòng sai. |
| **Test** | 124 bài test đều chạy trên một DB tạm do chính mã tạo ra, nên không bao giờ chứa dữ liệu "lạ". Test gọi thẳng hàm api, không qua HTTP, nên không bắt được việc kết nối bị đóng rỗng. | Cần một bộ kiểm bất biến chạy trên **bản sao DB thật** (kiểu dữ liệu, JSON hợp lệ, khoá ngoại), và một test HTTP ghim hành vi "ngoại lệ thì trả 500". |
| **Vận hành** | Bot và webapp chạy bằng `pythonw` nên **không có log nào cả** (mục 3.2). Lỗi chỉ lộ ra vì có người mở app và thấy hỏng. | — |

**Nguyên nhân gốc, tách khỏi cái kích hoạt.** Script là cái kích hoạt. Nguyên nhân gốc là kiểu của cột
chỉ được giữ bằng thói quen, không bằng ràng buộc nào. Mục 1.2 và 1.3 cho thấy cùng lỗ hổng này còn mở ở
những chỗ không cần script nào.

---

## 1. Toàn vẹn dữ liệu và migration

### 1.1 Cột thời gian và cột số không có ràng buộc kiểu — **Cao, đã xác minh**
- **Cơ chế:** xem bảng ở trên. Có 24 bảng, tất cả lưu thời gian dưới dạng số giây kiểu REAL, và không bảng
  nào có CHECK. Hiện tại bản sao không còn giá trị sai kiểu nào: đã quét `typeof` trên mọi cột của 24 bảng,
  và 10 cột JSON đều hợp lệ.
- **Đề xuất:** thêm trigger kiểm `typeof` cho các cột `*_at`, `*_until`, `budget_*`, `bedrooms`,
  `commission_vnd`, `scheduled_at`. Trigger thêm được bằng một migration, không phải dựng lại bảng.
  Bảng STRICT hay CHECK đòi phải dựng lại bảng, nên để dành tới lúc chuyển sang Postgres, nơi cột kiểu số
  tự từ chối chữ.
- **Cổng kiểm:**
  - Test ghi `datetime('now')` qua `sqlite3` thô thì nhận `IntegrityError`; ghi `time.time()` thì được.
  - Mutation: bỏ trigger thì test đỏ.
  - Quét `typeof` trên bản sao DB thật cho ra 0 dòng sai.

### 1.2 Webapp tự ghi chữ vào cột số, không cần script nào — **Cao, đã xác minh (ở mức API)**
- **Cơ chế:** đo trên webapp thật chạy ở cổng 8095.
  - `PUT /api/client/<id>` với `budget_max="15tr"`, `bedrooms="2PN"` trả 200. Trong DB, cả hai cột REAL
    đều thành **chữ**. Từ đó `GET /api/clients` và `GET /api/client/<id>` đóng kết nối rỗng, vì lỗi
    `int('2PN')` trong phần tóm tắt khách. Môi giới mất **toàn bộ danh sách khách** cho tới khi có người
    sửa tay DB. `POST /api/clients` có ép kiểu số, nhưng đường cập nhật thì không.
  - `POST /api/viewings` với `scheduled_at="2026-10-18 15:00"` trả 200 và lưu chữ vào cột REAL NOT NULL.
  - Cũng route đó với `listing_ids="tg:5152…"`, tức một chuỗi thay vì danh sách: lớp db gọi
    `list("tg:…")` và lưu thành **15 mã căn, mỗi mã một ký tự**.
  - `PUT /api/listing/<id>` có ép kiểu số cho giá, phòng ngủ, phòng tắm, diện tích. Nhưng `deposit` và
    `pet_friendly` đi thẳng vào JSON `parsed` nguyên văn. Bộ lọc dùng `CAST(json_extract(...) AS REAL)`
    đọc chữ thành 0 mà không báo lỗi gì.
- **Kịch bản:** giao diện sau này, hoặc app native, hoặc một bản giao diện có lỗi, gửi giá trị ở dạng chữ
  đúng như môi giới gõ. **Chưa kiểm** giao diện hiện tại có gửi như vậy không.
- **Tàn dư hay thiết kế:** tàn dư. Việc ép kiểu nằm rải trong từng hàm ở `api*.py`, có hàm có, có hàm
  không. Lớp db nhận mọi thứ.
- **Đề xuất:** lớp db kiểm và ép kiểu một lần cho mỗi bảng, ở các hàm `create_*` và `update_*`. Lỗi kiểu
  trả 400 kèm tên trường.
- **Cổng kiểm:** chạy lại kịch bản trên (tệp `webexp.py` trong thư mục nháp `r\`). Kỳ vọng:
  - Hai lệnh PUT/POST đầu trả 400.
  - `typeof` trong DB vẫn là real.
  - `GET /api/clients` vẫn trả 200.

### 1.3 Dạng im lặng của cùng lỗi: so sánh thời gian trong SQL — **Vừa, đã xác minh**
- **Cơ chế:** SQLite xếp mọi giá trị chữ **lớn hơn** mọi số. Đã thử: `'2026-10-17 07:57:09' < 1e12` cho
  ra 0. Có 38 phép so sánh thời gian viết trong SQL, ví dụ: căn cũ hơn mốc, khách lâu chưa liên lạc,
  lịch hôm nay, lịch sắp tới, cửa sổ đếm spam, hết hạn link.
- **Kịch bản đo được:** lịch xem có giờ dạng chữ thì
  - luôn hiện trong "Lịch sắp tới" (vì chữ ≥ bây giờ);
  - **không bao giờ** vào "Hôm nay" (vì chữ < cuối ngày là sai);
  - mọi lời nhắc theo giờ đều bỏ qua nó.

  Một căn có `updated_at` dạng chữ sẽ không bao giờ bị coi là cũ ở các truy vấn SQL, nhưng lại làm sập
  các phép tính bằng Python. Cùng một dòng sai cho ra hai triệu chứng trái ngược nhau.
- **Đề xuất và cổng kiểm:** dùng chung với 1.1. Khi trigger đã chặn ở đầu vào, dạng lỗi này không còn
  đường nào để sinh ra.

### 1.4 Khoá ngoại được khai báo nhưng không bao giờ bật — **Vừa, đã xác minh**
- **Cơ chế:** `PRAGMA foreign_keys` = 0 trên DB thật, và `connect()` không bật nó. 18 chỗ khai
  `REFERENCES` chỉ là chú thích. Dữ liệu hiện có 0 vi phạm.
- **Kịch bản:**
  - Xoá một khách thì các yêu cầu ghép và lịch xem trỏ tới khách đó vẫn còn, thành dòng mồ côi.
  - Webapp tạo khách, deal, lịch cho một mã Telegram chưa từng có dòng trong bảng môi giới. Đã thử: bật
    khoá ngoại thì lệnh tạo khách đó bị từ chối với `FOREIGN KEY constraint failed`.
- **Lưu ý:** bật khoá ngoại **không phải sửa một dòng**. Trước hết phải:
  1. tạo dòng môi giới ngay khi xác thực webapp (`get_or_create_broker`);
  2. quyết định khi xoá khách thì xoá dây chuyền hay chặn lại;
  3. chạy `foreign_key_check` trên bản sao.
- **Cổng kiểm:**
  - `foreign_key_check` cho 0 dòng trên bản sao.
  - Bộ test xanh khi `connect()` bật `foreign_keys=ON`.
  - Có test xoá khách đang có yêu cầu ghép, ghim hành vi đã chọn.

### 1.5 Migration không có số phiên bản, chạy rải ở ba nơi — **Vừa, đã xác minh**
- **Cơ chế:**
  - `user_version` = 0. Có 22 hàm `_migrate_*` với khoảng 30 lệnh ALTER, nhận biết trạng thái bằng
    cách hỏi `PRAGMA table_info`.
  - Chỉ bot gọi `init_db` lúc khởi động. Webapp không gọi, mà lại được bật **trước** bot 2 giây.
  - Có 17 lời gọi `_migrate_*` nằm ngay trong đường chạy thường (lấy tuỳ chọn thông báo, xếp outbox,
    báo cáo căn sai…). Nghĩa là mỗi request lại chạy DDL và PRAGMA.
  - `followup.py` tự thêm cột của riêng nó, ngoài `core.py`. Cột này hiện chưa có trên DB thật.
  - Một ALTER trong migration nhật ký làm mới được bọc `except Exception: pass`, nên mọi lỗi thật cũng
    bị nuốt.
- **Kịch bản:** commit mới thêm một cột mà webapp dùng. Webapp chạy trước, hoặc bot không bật được
  (khoá cổng, lỗi), thì webapp truy vấn cột chưa tồn tại. Hai tiến trình cùng thấy "chưa có cột" sẽ
  cùng ALTER, và tiến trình thứ hai lỗi `duplicate column`. **Nghi ngờ có căn cứ**, chưa dựng lại.
- **Đề xuất:**
  - Danh sách migration đánh số, ghi `user_version`, mỗi bước chạy trong một giao dịch.
  - Chạy bằng một lệnh riêng trong `start-all.ps1` **trước khi** bật cả hai tiến trình.
  - Bỏ hết lời gọi `_migrate_*` khỏi đường chạy thường.
- **Cổng kiểm:**
  - DB rỗng và bản sao DB thật cùng ra một schema (so `sqlite_master`).
  - `user_version` bằng số migration cuối.
  - Grep `_migrate_` ngoài tệp migration cho 0 kết quả.

### 1.6 `updated_at` mang hai nghĩa: "dòng vừa bị sửa" và "môi giới vừa xác nhận căn còn trống" — **Vừa, đã xác minh (đọc mã)**
- **Cơ chế:**
  - Độ tươi của căn đo từ `updated_at`. Độ tươi là thứ quyết định thứ hạng khi đề xuất, điểm hồ sơ, số
    "căn cần làm mới", và cả hệ thống phạt khi báo sai.
  - Nhưng `update_listing()` cũng ghi `updated_at = now` ở **mọi** lần ghi. Ví dụ: tải ảnh nền lên R2
    (mỗi ảnh ghi hai lần), lưu bài đăng bằng ngôn ngữ khác, môi giới sửa giá trên webapp.
  - Hai script ngày 17/10, kể cả sau khi đã sửa, vẫn đặt cả 3 căn thành "vừa xác nhận" lúc chạy.
- **Câu hỏi thiết kế cho chủ dự án:** sửa thông tin căn có được tính là "đã xác nhận còn trống" không?
  Mã hiện tại trả lời là có, nhưng ghi chú của chính hàm độ tươi nói đó là "lần làm mới trạng thái gần
  nhất".
- **Liên quan:** `fix_listings_full.py` thêm tiện ích và điểm nổi bật **ngẫu nhiên** vào căn trên DB thật.
  Trong khi đó, khách báo "tiện ích sai" trên trang chia sẻ thì môi giới bị phạt tự động. **Chưa kiểm**
  3 căn này là căn thật hay căn thử.
- **Đề xuất:** thêm cột `verified_at` riêng, chỉ ghi khi môi giới làm mới. Độ tươi đọc từ `verified_at`.
- **Cổng kiểm:** test tải ảnh nền hay lưu bài đăng xong thì độ tươi không đổi; bấm làm mới thì độ tươi
  về 0.

---

## 2. Bot và webapp cùng ghi một tệp SQLite

Đo trên DB thật: `journal_mode=delete` (nhật ký rollback, không phải WAL), `busy_timeout` 5000 ms (đó
là mặc định của Python), `synchronous=FULL`. Mỗi lời gọi hàm db tự mở và đóng một kết nối riêng
(144 chỗ). Python 3.11 chỉ tự mở giao dịch trước lệnh INSERT, UPDATE hay DELETE, nên câu SELECT đứng
trước **không** nằm cùng giao dịch với lệnh ghi theo sau.

**Tải hiện tại không có vấn đề (đã đo).** Thử ba tiến trình dùng đúng hàm db thật: hai bên ghi giống
webapp và bot, một bên đọc, mỗi bên 1.500 vòng.

| Chế độ nhật ký | Lỗi | Trễ p99 bên ghi | Trễ lớn nhất |
|---|---|---|---|
| Rollback (`delete`, như hiện tại) | 0 | khoảng 190–220 ms | 386 ms |
| WAL | 0 | khoảng 80–220 ms | 351 ms |

Không có lỗi "database is locked" nào. Rủi ro thật nằm ở hai chỗ dưới đây.

### 2.1 Lượt dùng thử bị trừ kiểu "đọc rồi mới ghi", vượt giới hạn khi bấm song song — **Vừa, đã xác minh**
- **Cơ chế:** `use_trial` đọc số lượt đã dùng (một kết nối), so với giới hạn 3, rồi mới tăng (kết nối
  khác). Webapp chạy mỗi request trên một luồng riêng.
- **Đo:**
  - Gọi tuần tự 5 lần: 200, 200, 200, 402, 402. Đúng như mong đợi.
  - Gọi song song 12 lần trên webapp thật: **12/12 thành công, số lượt đã dùng = 12**, gấp 4 lần giới hạn.
  - Đi qua hàm trực tiếp, 12 luồng trong một tiến trình: kết quả giống hệt.
- **Kịch bản:** bấm đúp, hoặc gọi API thẳng, là dùng được tính năng trả phí quá giới hạn.
  `create_share` còn tạo trang chia sẻ **trước** khi trừ lượt.
- **Đề xuất:** một câu lệnh duy nhất, kiểu
  `UPDATE … SET used_count = used_count + 1 WHERE … AND used_count < ?`, rồi xem `rowcount`. Lượt đầu
  tiên dùng `INSERT … ON CONFLICT` có điều kiện.
- **Cổng kiểm:** 12 luồng song song thì đúng 3 lần thành công và số đếm bằng 3. Mutation: trả lại cách
  cũ thì test đỏ.

### 2.2 Một bên ngoài giữ khoá ghi là cả bot đứng hình 5,6 giây ở mỗi lần ghi — **Vừa, đã xác minh**
- **Cơ chế:** bot gọi SQLite **đồng bộ**, ngay trong vòng lặp sự kiện của python-telegram-bot.
- **Đo:** để một tiến trình thứ ba giữ khoá ghi (giống DB Browser đang có thay đổi chưa lưu, hay một
  script sửa tay đang chạy). Kết quả:
  - một lần ghi của bot chờ **5,62 s** rồi báo `database is locked`;
  - mọi coroutine khác của bot bị chặn **5,72 s**;
  - đọc vẫn qua được, vì nhật ký rollback chỉ chặn người đọc lúc bên kia commit.
- **Kịch bản:** đúng kiểu làm việc ngày 17/10, mở DB thật để sửa tay. Trong lúc đó mọi môi giới thấy
  bot treo, và các lệnh ghi bị mất.
- **Đề xuất:**
  - Bật WAL, đặt `busy_timeout` có chủ đích.
  - Đẩy các lời gọi db nặng của bot sang `asyncio.to_thread`.
  - Quy ước vận hành: chỉ sửa trên bản sao, hoặc tắt bot trước khi sửa.
- **Cổng kiểm:** chạy lại phép thử giữ khoá (`lockhold.py` trong thư mục nháp `r\`). Kỳ vọng: bot không
  bị chặn quá 100 ms, và lỗi khoá được ghi log.

### 2.3 Các chỗ đọc-sửa-ghi khác không nằm trong giao dịch — **Thấp, nghi ngờ có căn cứ**
- **Các chỗ:**
  - `update_listing_field`: đọc JSON `parsed`, sửa, rồi ghi cả khối JSON.
  - `add_photo_url` và `add_photo_hash`: đọc danh sách ở một kết nối, ghi ở kết nối khác.
  - Đếm cảnh cáo spam: tính số mới bằng Python rồi ghi đè giá trị tuyệt đối.
  - Thưởng giới thiệu: kiểm "đã thưởng chưa" rồi mới thêm.
- **Vì sao chỉ ở mức thấp:**
  - Bot xử lý update **tuần tự**, vì `concurrent_updates` không bật.
  - Ảnh của một căn được tải lần lượt.
  - Phạt từ link chia sẻ dùng `INSERT OR IGNORE` trên khoá chính, và đếm báo sai dùng `+ 1` nguyên tử.
    Hai chỗ này đã đúng.

  Đua chỉ xảy ra khi bot và webapp cùng sửa một căn. Chưa dựng lại được.
- **Đề xuất:** khi gom lớp db (xem 4.2), mỗi thao tác đọc-sửa-ghi mở `BEGIN IMMEDIATE`.

---

## 3. Xử lý lỗi, quan sát, outbox

### 3.1 Ngoại lệ trong máy chủ webapp làm kết nối đóng rỗng — **Cao, đã xác minh**
- **Cơ chế:** máy chủ webapp không bọc `try/except` quanh phần định tuyến. Ngoại lệ chạy lên tới thư viện
  `socketserver`; thư viện in traceback rồi đóng socket mà không gửi gì.
- **Đo trên cổng 8095:** sáu route đóng kết nối rỗng.
  - `/api/today` và `/api/profile`: dữ liệu thời gian dạng chữ.
  - `/api/clients` và `/api/client/<id>`: khách có số phòng dạng chữ.
  - `PUT /api/listing` với `fields` là chuỗi.
  - `PUT /api/profile` với body là mảng (`'list' object has no attribute 'get'`).
- **Hậu quả:** giao diện nhận lỗi fetch, nên báo "lỗi mạng" cho môi giới. Ai đọc báo lỗi cũng sẽ đi tìm
  nhầm sang mạng hay đường hầm. Trang chia sẻ công khai cho khách cũng đi qua đúng đường này.
- **Đề xuất:**
  - Một lớp bọc duy nhất ở `do_GET`, `do_PUT`, `do_POST`. Có ngoại lệ thì ghi traceback vào log và
    trả `{"error":"server_error"}` với mã 500.
  - Body phải là object JSON, nếu không thì trả 400.
- **Cổng kiểm:** test HTTP thật dựng máy chủ trên một cổng tạm, gây lỗi cho một route, và kỳ vọng mã
  500 có body JSON. Mutation: gỡ lớp bọc thì test thấy `RemoteDisconnected`.

### 3.2 Chạy bằng `start-all.ps1` thì không có dòng log nào, cả bot lẫn webapp — **Cao, đã xác minh**
- **Cơ chế:**
  - `start-all.ps1` bật cả hai tiến trình bằng `Start-Process pythonw -WindowStyle Hidden`.
  - Tôi bật một script thử theo đúng cách đó. Script thấy `sys.stderr = None`, `sys.stdout = None`, và
    bộ ghi log của `logging.basicConfig` không có luồng ra. Traceback và print đều bị nuốt im lặng.
- **Hậu quả:**
  - Mọi `log.warning` của bot đều không đi đâu cả: outbox lỗi, phạt lỗi, lỗi gửi thông báo đặt lịch,
    `on_error`.
  - Traceback của webapp cũng vậy.
  - Lỗi 17/10 chỉ lộ ra nhờ có người dùng thấy.

  Phép thử dùng cùng cách khởi chạy, nhưng tôi **không** soi tiến trình đang chạy thật.
- **Đề xuất:**
  - Mỗi tiến trình ghi log ra tệp xoay vòng (`logs/bot.log`, `logs/webapp.log`).
  - Webapp ghi log request **không kèm** chuỗi truy vấn, vì chuỗi đó có thể chứa initData.
- **Cổng kiểm:** bật bằng `start-all.ps1`, gây một lỗi đã biết trên bản sao, thấy traceback xuất hiện
  trong tệp log.

### 3.3 Outbox giao "nhiều nhất một lần": lỗi tạm thời là mất vĩnh viễn — **Vừa, đã xác minh (đọc mã)**
- **Cơ chế:**
  - Webapp ghi việc cần báo vào bảng outbox. Bot đọc mỗi 30 giây và đánh dấu "đã gửi" trong `finally`,
    **dù gửi được hay không**.
  - Đây là thiết kế có chủ đích (commit `97db10d`), để một dòng lỗi không chặn mọi dòng phía sau.
  - Hệ quả: Telegram trả 429, mạng rớt, hay DB đang khoá đúng lúc đó, thì việc đó mất luôn. Việc có thể
    là báo khách đặt lịch, yêu cầu nâng cấp gửi admin, hay **lần phạt môi giới**. Lỗi chỉ để lại một
    dòng log, mà dòng log đó cũng không đi đâu (mục 3.2).
- **Ý định và cách làm:** ý định đúng (chống tắc đầu hàng), cách làm đổi một lỗi lấy một lỗi khác.
- **Đề xuất:** thêm cột `attempts`, `next_attempt_at`, `last_error`. Lỗi thì lùi thời gian thử lại theo
  cấp số; quá N lần thì chuyển sang trạng thái "chết" và hiện ở `/baocao`. Truy vấn lấy việc lọc theo
  `next_attempt_at <= now`, nên một dòng lỗi vẫn không chặn được dòng khác.
- **Cổng kiểm:** test giả lập gửi lỗi một lần thì lần sau gửi lại được; dòng lỗi mãi thì không chặn 20
  dòng sau; quá N lần thì thấy trong `/baocao`.

**Ghi chú về lập lịch.** Bot chỉ có **một** job, là bộ đọc outbox mỗi 30 giây. Sáu tính năng nhắc việc
vẫn là script rời, không ai lên lịch (báo cáo luồng mục 4.1, tôi không lặp lại ở đây). Khi chuyển chúng
vào `job_queue` thì `run_daily` phải truyền `tzinfo` giờ Việt Nam, vì mặc định của job queue là UTC.
Bốn script rời đó vẫn dùng `fromtimestamp` theo giờ máy Calgary. Phần bot và webapp đã đi hết qua
`db/vntime.py`: đã grep, không còn chỗ nào dùng giờ máy.

---

## 4. Ranh giới tầng và hợp đồng API

### 4.1 Luật nghiệp vụ nằm trong module handler của bot, webapp phải nạp cả thư viện Telegram — **Vừa, đã xác minh**
- **Cơ chế:**
  - Webapp tính lọc tiêu chí cứng, điểm ghép, và điểm hồ sơ bằng cách import `feat_match` và `utils`.
    Cả hai đều import `telegram` ở đầu tệp, nên tiến trình webapp phải có python-telegram-bot, và kéo
    theo toàn bộ module giao diện bot.
  - Cùng một khái niệm có hai định nghĩa khác nhau:
    - "Căn đang hoạt động" là chỉ `submitted` trong thống kê hồ sơ, nhưng là 4 trạng thái trong điểm
      hồ sơ và số căn cần làm mới.
    - "Độ tươi" là bậc 7/14/30/60 ngày trong `api.py`, nhưng là cửa sổ 7 ngày trong `utils.py`.
- **Kịch bản:** một app native hay web app mới phải chép lại các luật này, hoặc nạp module bot.
- **Đề xuất:**
  - Tách một tầng nghiệp vụ thuần, không import `telegram`, gồm: chấm điểm, lọc, độ tươi, điểm hồ sơ,
    lượt dùng thử.
  - Thứ tự phụ thuộc: bot và webapp gọi tầng nghiệp vụ, tầng nghiệp vụ gọi db.
  - Mỗi khái niệm chỉ định nghĩa một lần.
- **Cổng kiểm:**
  - Import tầng nghiệp vụ trong một môi trường không cài python-telegram-bot mà vẫn chạy được.
  - Grep `import feat_` trong `webapp/` cho 0 kết quả.

### 4.2 Hợp đồng API không có lược đồ, kiểm đầu vào rải rác — **Vừa, đã xác minh**
- **Cơ chế:**
  - Có bốn dạng báo lỗi khác nhau: chỉ có `error`; có `error` kèm `error_vi`; mã 200 kèm `ok`; và kết
    nối đóng rỗng.
  - Thời gian là số giây kiểu float. Không có số phiên bản API.
  - Quyền sở hữu khách và căn khi tạo lịch xem hay deal chưa được kiểm. Báo cáo luồng mục 3.6 đã nêu,
    và trên bản sao tôi vẫn tạo được.
- **Đề xuất:**
  - Mỗi route khai một lược đồ đầu vào nhỏ: tên trường, kiểu, bắt buộc hay không.
  - Một dạng lỗi duy nhất: `{error, error_vi, field?}`.
  - Thêm tiền tố `/api/v1` trước khi có client thứ hai.
- **Cổng kiểm:** test lặp qua mọi route, gửi body sai kiểu, kỳ vọng mã 400 chứ không phải 200 hay 500.

### 4.3 Mỗi lời gọi db là một kết nối riêng, một màn hình không đọc từ cùng một ảnh chụp — **Thấp, đã xác minh**
- **Đo:**
  - `/api/today`: 7 kết nối, 7 câu lệnh.
  - `/api/profile`: 6 kết nối.
  - `/api/listings`: 4 kết nối.
  - Với mỗi lịch xem trong ngày, màn "Hôm nay" gọi thêm một lần lấy căn và một lần lấy khách.
- **Tác động:** trên SQLite thì rẻ. Trên Postgres, nếu không có pool, mỗi kết nối là một lần bắt tay
  mạng.
- **Đề xuất:** khi tách tầng, mỗi request dùng một kết nối hoặc một giao dịch.

### 4.4 initData vẫn được nhận qua chuỗi truy vấn — **Thấp, đã xác minh**
- **Cơ chế:** hàm xác thực vẫn đọc `init_data` và `init_data_b64` trên URL, ngoài header
  `X-Telegram-Init-Data`. Quy tắc A5 của dự án chỉ cho phép header. Báo cáo luồng mục 3.11 đã nêu chuyện
  log lộ initData.
- **Đề xuất:** bỏ hai đường đọc qua URL. Cổng kiểm là test gửi initData hợp lệ qua query thì nhận 401.

---

## 5. Hosting, sao lưu, đường lên Postgres

### 5.1 Link chia sẻ gửi khách gắn liền URL đường hầm tạm — **Cao, đã xác minh (đọc mã)**
- **Cơ chế:**
  - `create_share` ghép link bằng `WEBAPP_URL`. Giá trị mặc định trong `start-all.ps1` là một địa chỉ
    `*.trycloudflare.com`, loại đường hầm nhanh mà mỗi lần bật lại sẽ đổi tên.
  - Link được gửi cho khách qua Zalo hay SMS, và DB chỉ lưu token.
- **Kịch bản:** máy Windows khởi động lại, hoặc cloudflared đổi địa chỉ, là mọi link đã gửi khách đều
  chết. Đây là kênh bán hàng hướng ra ngoài.
- **Chưa kiểm:** thực tế địa chỉ đã đổi bao nhiêu lần.
- **Đề xuất:** dùng một tên miền cố định (đường hầm có tên, hoặc hosting) trước khi gửi link thật cho
  khách.
- **Cổng kiểm:** khởi động lại máy, link cũ vẫn mở được.

### 5.2 Không có sao lưu — **Cao, đã xác minh**
- **Cơ chế:**
  - Grep chữ "backup" trong mã, script và tài liệu vận hành: không có kết quả nào.
  - DB là một tệp nằm trong thư mục làm việc git, được bỏ qua bằng `*.db`. Lệnh `git clean -X` sẽ xoá nó.
  - Ngày 17/10 đã có hai lần sửa tay trên DB thật mà không có bản sao trước.
- **Đề xuất:** job hằng ngày chép bằng `sqlite3 .backup` hoặc `VACUUM INTO` sang ổ khác hay lên R2,
  giữ 14 bản. Trước mỗi lần sửa tay, script tự sao lưu.
- **Cổng kiểm:** khôi phục một bản sao lưu vào thư mục tạm, chạy bộ kiểm bất biến, số dòng khớp.

### 5.3 Phụ thuộc vào SQLite khi chuyển sang Postgres — **Thấp (là khối lượng việc, không phải lỗi), đã xác minh bằng đếm**

| Thứ phải đổi | Số chỗ |
|---|---|
| Lời gọi `execute` dùng dấu `?` | 275 trong `db/` |
| `json_extract` cùng `CAST … AS REAL` | 16 |
| `PRAGMA table_info` dùng trong migration | 16 |
| `AUTOINCREMENT` | 6 |
| `INSERT OR IGNORE` | 4 |
| `lastrowid` | 1 |
| `executescript` | 1 |
| Script truy cập trực tiếp bằng `sqlite3` | 3 |

- JSON đang lưu dưới dạng TEXT, ít nhất 12 cột. Nên chuyển sang `jsonb`.
- Thời gian là số giây REAL. Chuyển thẳng được, nhưng nên quyết định có đổi sang `timestamptz` hay
  không.
- Không dùng `strftime`, `julianday`, `typeof` hay `rowid` trong mã ứng dụng.
- Các truy vấn kiểu `limit=10000` rồi lọc bằng Python cần viết lại khi dữ liệu lớn lên.
- **Đề xuất:** chuyển sau khi đã có tầng db duy nhất (4.1, 4.2) và migration đánh số (1.5). Khi đó việc
  chuyển chỉ đụng tới một thư mục.
- **Cổng kiểm:** bộ test chạy trên cả hai cơ sở dữ liệu. Chép dữ liệu sang xong, số dòng và tổng kiểm
  từng bảng khớp nhau.

### 5.4 Bot và webapp có thể chạy hai bản mã khác nhau — **Thấp, nghi ngờ có căn cứ**
- **Cơ chế:** webapp chạy từ worktree `TrueNestProd` ở nhánh main. Bot chạy từ thư mục repo ở HEAD hiện
  tại, và `start-all.ps1` chỉ từ chối khi có tệp `.py` chưa commit. Nếu repo đang ở nhánh khác main thì
  bot và webapp chạy hai bản mã trên cùng một DB, trong khi migration lại do bot chạy.
- **Đề xuất:** bot cũng chạy từ `TrueNestProd`. Cổng kiểm: `start-all.ps1` in ra hash commit của cả hai
  tiến trình, và hai hash phải bằng nhau.

### 5.5 Đường dẫn DB mặc định là đường dẫn tương đối — **Thấp, đã xác minh (đọc mã)**
- **Cơ chế:** `BOT_DB_PATH` mặc định là `broker_bot.db`, tính theo thư mục đang đứng. Script chạy từ
  thư mục khác sẽ lặng lẽ tạo ra một DB rỗng. Script thường sẽ lỗi ngay vì thiếu bảng, nhưng các script
  có gọi `init_db` thì dựng hẳn một DB mới đầy đủ bảng.
- **Đề xuất:** dùng đường dẫn tuyệt đối tính từ thư mục mã. Cổng kiểm: chạy một script từ thư mục khác
  thì nó dùng đúng DB thật, hoặc báo lỗi rõ ràng.

### Ghi chú thêm (không tính vào số phát hiện)
- Máy chủ webapp không giới hạn kích thước body và không đặt thời gian chờ cho request.
  `ThreadingHTTPServer` mở một luồng cho mỗi kết nối. Có Cloudflare đứng trước nên rủi ro thấp.
- `get_tier` ghi vào DB ngay trong lúc đọc: tự hạ về gói free khi hết hạn. Đây là thiết kế chấp nhận
  được, nhưng nên nhớ khi tách tầng.
- Mỗi lần tải trang chia sẻ đều tăng lượt xem, kể cả khi bot xem trước link của Zalo hay Telegram tải
  trang. Lượt xem vì thế bị thổi phồng. **Chưa đo.**

---

## Lộ trình theo thứ tự ưu tiên

### A. Việc nhỏ, làm ngay (mỗi việc dưới nửa ngày)
1. **Lớp bọc lỗi 500 cho webapp, và log ra tệp cho cả hai tiến trình** (3.1, 3.2).
   Cổng kiểm: test HTTP thấy mã 500 có JSON; bật bằng `start-all.ps1` thì thấy traceback trong tệp log.
2. **Trigger kiểm `typeof`** cho cột thời gian và cột số của các bảng căn, khách, lịch xem, deal, môi
   giới (1.1, 1.3).
   Cổng kiểm: test chạy câu `datetime('now')` thì bị chặn; mutation; quét `typeof` trên bản sao thật
   cho 0 dòng sai.
3. **Trừ lượt dùng thử bằng một câu lệnh nguyên tử** (2.1).
   Cổng kiểm: 12 luồng song song thì đúng 3 lần thành công.
4. **Kiểm kiểu ở lớp db cho `update_client` và `create_viewing`**, kèm trường số của căn (1.2).
   Cổng kiểm: chạy lại `webexp.py`, phần C cho ra 400, và `GET /api/clients` vẫn 200.
5. **Script bất biến dữ liệu** (dựa trên `types.py` trong thư mục nháp), chạy trên bản sao trước mỗi lần
   khởi động lại và sau mỗi lần sửa tay. Script sửa tay phải tự sao lưu trước.
   Cổng kiểm: cài lại lỗi 17/10 lên một bản sao thì script báo đỏ.

### B. Trước khi lên hosting hoặc có người dùng thật
6. **Sao lưu hằng ngày, kèm diễn tập khôi phục** (5.2).
7. **Tên miền cố định cho link chia sẻ** (5.1).
8. **Migration đánh số, chạy một lần trước khi bật các tiến trình**, bỏ DDL khỏi đường chạy thường (1.5).
   Cổng kiểm: so `sqlite_master` giữa DB mới và bản sao thật.
9. **Bật WAL, đẩy lời gọi db của bot sang luồng phụ** (2.2).
   Cổng kiểm: chạy lại `lockhold.py`, vòng lặp sự kiện không bị chặn quá 100 ms.
10. **Outbox có thử lại và hàng "chết"** (3.3).
11. **Bật khoá ngoại** sau khi đã tạo dòng môi giới lúc xác thực webapp và đã chọn hành vi khi xoá
    khách (1.4).
12. **Thêm cột `verified_at` riêng cho độ tươi** (1.6). Cần chủ dự án quyết câu hỏi thiết kế trước.
13. **Bot và webapp chạy cùng một bản mã** (5.4).

### C. Khi chuyển sang Postgres
14. **Tầng nghiệp vụ thuần và tầng db duy nhất**, mỗi request một kết nối, có lược đồ API (4.1, 4.2,
    4.3). Đây là điều kiện để mọi chỗ cần đổi nằm trong một thư mục.
15. **Đổi phần phụ thuộc SQLite** theo bảng 5.3: JSON chuyển sang `jsonb`, `INSERT OR IGNORE` chuyển
    sang `ON CONFLICT DO NOTHING`, `lastrowid` chuyển sang `RETURNING`. Ràng buộc kiểu và khoá ngoại
    của Postgres thay cho trigger.
    Cổng kiểm: bộ test chạy trên cả hai cơ sở dữ liệu; số dòng và tổng kiểm từng bảng khớp sau khi chép.

---

## Đã đọc / đã đo / chưa làm

**Đã đọc hết:**
- Cả hai tệp `webapp/server.py` và `db/core.py`.
- Các hàm của `webapp/api.py` và `webapp/api_clients_deals.py` mà route gọi tới: hôm nay, hồ sơ, dùng
  thử, chia sẻ, đề xuất, làm mới, khách, lịch xem, deal, premium.
- `db/trial.py`, `db/notify.py`.
- Các phần ghi của `db/listings`, `db/spam`, `db/refresh`, `db/referral`, `db/share`, `db/viewings`,
  `db/clients`, `db/brokers`.
- Bộ đọc outbox, phần `main()` của `bot.py`, `start-all.ps1`, ba script trong `scripts/`, `db/vntime.py`.

**Đã đo:**
- PRAGMA trên DB thật (chỉ đọc).
- `typeof` và JSON hợp lệ trên toàn bộ bản sao.
- Tái hiện lỗi 17/10 trên webapp thật ở cổng 8095.
- Ghi sai kiểu qua API, body hỏng, đua lượt dùng thử.
- Ba tiến trình ghi đồng thời ở hai chế độ nhật ký.
- Giữ khoá ghi và đo vòng lặp sự kiện bị chặn.
- Khoá ngoại, CHECK, STRICT, trigger.
- `pythonw` không có stderr.
- Số kết nối mỗi màn hình.
- Bộ test: 123 đạt, 1 trượt.

**Chưa đọc hoặc chưa đo:**
- Hơn 10.000 dòng `feat_*.py` của bot: chỉ lần theo những chỗ có ghi DB hoặc job.
- `db/match.py`, `db/money.py`, `share.py` phía webapp: chưa đọc hết.
- Giao diện có gửi giá trị dạng chữ cho các trường số hay không.
- Tiến trình bot và webapp đang chạy thật: không chạm vào.
- Hành vi khi hai tiến trình cùng chạy ALTER một lúc: chưa dựng lại được.
- Hành vi trên Postgres: chưa thử.
- Số lần địa chỉ đường hầm đã đổi.

Đây **không** phải một lượt quét hết. Vùng `feat_*` của bot là nơi dễ còn những chỗ đọc-sửa-ghi chưa ai xem.

Các phép thử nằm trong
`C:\Users\quock\AppData\Local\Temp\claude\d--TrueNest-TrueNestAssistant\1b5767dc-7e70-451f-a1d5-106e1c723d1a\scratchpad\r\`:
`webexp.py`, `trialseq.py`, `contend.py`, `lockhold.py`, `fkstrict.py`, `trig.py`, `types.py`,
`conncount.py`, `pyw_probe.py`. Mỗi tệp chép DB vào một bản sao riêng trước khi thử.
