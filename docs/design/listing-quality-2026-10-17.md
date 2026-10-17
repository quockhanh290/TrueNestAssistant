# Chất lượng tin: kiểm dữ liệu, bộ trường chuẩn, bảng điểm (17/10/2026)

Chủ dự án duyệt ngày 17/10/2026 (giờ Việt Nam). Đây là đặc tả cho lượt code tiếp theo; số đo
trong mục 1 lấy ở commit 9b2415c.

## 1. Hiện trạng đã đo

**Kiểm dữ liệu chỉ chặn sai kiểu, chưa chặn giá trị vô lý.** Ghi thử qua đường sửa tin:
giá 1 đồng, giá 8 (ý là 8 triệu), giá 800 tỷ, giá 0, 50 phòng ngủ, 2,5 phòng ngủ, diện tích 0 m²
và 99.999 m², số điện thoại "abc": tất cả đều lưu được.

**Khu vực gõ tay làm mất điểm ghép căn.** Khi ghép căn với khách, khu vực được so khớp nguyên văn.
- Bot tự đưa "son tra", "Q. Sơn Trà", "quận sơn trà" về "Sơn Trà".
- Ô sửa trên webapp lưu nguyên chữ người dùng gõ.
- Cùng một căn 2PN, khách tìm ở Sơn Trà: gõ "Sơn Trà" được 81 điểm khớp, gõ "son tra" chỉ còn 63.
  Căn đó còn mất luôn điểm cộng cho khu lân cận.
- Bot không nhận ra tên phường mới ("An Hải Bắc", "phường An Hải"), vì máy chạy bot thiếu tệp
  danh mục địa danh data/danang_locations.json.

**Bộ trường chuẩn có chỗ hở.**
- 5 trường có điểm nhưng không có đường nào nhập được: hướng ban công, view, phí quản lý,
  hẻm/mặt tiền, số tầng của nhà. Cộng lại là 11 điểm.
  - Không đường nào ghi chúng: bot không đọc ra từ tin, webapp không có ô sửa, luồng nhập từng
    bước không hỏi.
  - Hàm chọn câu hỏi theo loại nhà đã có sẵn trong schema.py nhưng không nơi nào gọi tới.
  - Đường AI phân tích tin chưa được kiểm, có thể nó trả thêm các trường này.
- Bot đọc được ba trường không có trong bộ trường chuẩn: phường, hợp đồng tối thiểu, ghi chú
  tình trạng trống.
- Ngày trống có trong bảng trường nhưng không đường nào ghi vào.
- Điểm cộng đủ mọi trường mà không xét loại nhà. Vì vậy:
  - Nhà phố điền đủ các ô hợp với nhà phố chỉ được tối đa 86 điểm.
  - Căn hộ điền đủ các ô hợp với căn hộ chỉ được tối đa 95 điểm.
  - Muốn được 100 thì phải điền cả những ô không hợp với loại nhà của mình.

**Chưa có số liệu thật về độ đầy đủ.** DB thật mới có 3 tin, và phần tiện ích trong đó do
script tạo ra. Sau khi deploy cần đo lại tỉ lệ điền của từng trường.

## 2. Quyết định của chủ dự án

1. **Giá trị vô lý thì từ chối, kèm tên ô sai.**
   - Bot hỏi lại môi giới; webapp đánh dấu đỏ ô sai.
   - Giá dưới 1.000 (kiểu gõ "8") thì hỏi "ý anh là 8 triệu?", không tự đoán.
2. **Khu vực và phường chọn từ danh mục, máy chủ chuẩn hoá.**
   - Mọi đường nhập đưa về tên chuẩn, giống cách bot đang làm.
   - Không tra được trong danh mục thì từ chối.
3. **Lưu phường cùng quận cũ, và ghép căn theo cả hai.** Môi giới và khách vẫn quen gọi theo quận.
4. **Ô nhập theo loại nhà**, cho cả bot (hỏi từng bước) và webapp:
   - Căn hộ: tên toà, số căn, tầng, hướng ban công, view, phí quản lý.
   - Nhà phố: số nhà và tên đường, hẻm/mặt tiền, số tầng của nhà.
5. **Thêm vào bộ trường chuẩn:**
   - ngày trống (tính điểm và hiện cho khách);
   - hợp đồng tối thiểu (số tháng);
   - nuôi thú cưng (tính điểm);
   - giá điện, giá nước;
   - phường.
6. **Bảng điểm mới** (nháp 2, đã duyệt): xem mục 4.

## 3. Luật kiểm giá trị

Luật đặt ở tầng DB, nơi duy nhất cả bot lẫn webapp đều đi qua. Mỗi luật trả về lý do riêng, để
bot và webapp nói được cho người dùng ô nào sai và sai thế nào.

| Trường | Hợp lệ | Lý do khi sai |
|---|---|---|
| Giá thuê | 1 triệu – 200 triệu/tháng | Dưới 1.000: price_maybe_millions (hỏi lại); còn lại: out_of_range |
| Phòng ngủ, WC | số nguyên 0–10 (0 = studio) | not_an_integer / out_of_range |
| Diện tích | 10–2.000 m² | out_of_range |
| Tầng (căn hộ) | số nguyên 0–80 | out_of_range |
| Số tầng nhà | số nguyên 1–10 | out_of_range |
| Đặt cọc | 0–12 tháng; nhận cả dạng "2 tháng" | out_of_range |
| Hợp đồng tối thiểu | 1–60 tháng | out_of_range |
| Phí quản lý | 0 – 20 triệu/tháng; nhận cả dạng tiền viết tắt | out_of_range |
| Số điện thoại | số Việt Nam, đưa về dạng 10 số bắt đầu bằng 0 bằng hàm normalize_phone có sẵn | bad_phone |
| Quận | tên quận cũ có trong danh mục, đưa về tên chuẩn | not_in_catalog |
| Phường | tên phường có trong danh mục; suy ra quận nếu quận còn trống | not_in_catalog |
| Loại hình, nội thất, hướng ban công | thuộc danh sách cố định, lấy từ các giá trị bot đang ghi ra | not_allowed |
| Ngày trống | ngày dạng YYYY-MM-DD, không sớm hơn hôm nay quá 1 năm | bad_date |
| Giá điện, giá nước | "giá nhà nước", hoặc một con số (đồng/kWh với điện; đồng/m³ hoặc đồng/người với nước) | not_allowed / out_of_range |

Các khoảng ngưỡng ở trên là giá trị mặc định do điều phối đề xuất. Nếu dữ liệu thật cho thấy một
ngưỡng chặn nhầm tin đúng thì nới ngưỡng đó và ghi lý do vào commit.

Điểm chất lượng chỉ tính một trường khi giá trị của nó đã qua kiểm. Một ô địa chỉ ghi "x" sẽ
không được điểm.

## 4. Bảng điểm mới (tổng 100)

Bảng gồm phần chung 75 điểm và phần theo loại nhà 25 điểm. Nhờ vậy nhà phố và căn hộ đều đạt
được 100 bằng đúng những ô hợp với loại nhà của mình.

**Phần chung (75)**

| Trường | Cũ | Mới |
|---|---|---|
| Giá | 8 | 8 |
| Ảnh (từ 3 ảnh) | 6 | 7 |
| Phòng ngủ | 6 | 7 |
| Diện tích | 9 | 6 |
| Quận | 6 | 6 |
| Phường | — | 3 |
| Ngày trống | 0 | 5 |
| Loại hình | 5 | 4 |
| WC | 6 | 4 |
| Số điện thoại | 5 | 4 |
| Nội thất | 4 | 3 |
| Thú cưng (đã trả lời có hay không) | 0 | 2 |
| Hợp đồng tối thiểu | — | 2 |
| Giá điện nước | — | 2 |
| Đặt cọc | 2 | 2 |
| Mô tả (trên 50 ký tự) | 4 | 2 |
| Tiện ích (+0,5 mỗi cái) | 8 | 5 |
| Điểm nổi bật (+0,5 mỗi cái) | 6 | 3 |

**Phần theo loại nhà (25)**
- Căn hộ: tên toà 7, số căn 4, tầng 4, phí quản lý 4, hướng ban công 3, view 3.
- Nhà phố: số nhà và tên đường 10, hẻm/mặt tiền 9, số tầng của nhà 6.
- Chưa chọn loại hình thì phần này được 0 điểm, để môi giới có lý do chọn loại.

**So điểm cũ và mới trên tin mẫu (5 ảnh), tính bằng code**

| Tin | Cũ | Mới |
|---|---|---|
| Nhà phố điền đủ các ô hiện có | 86 | 88 |
| Căn hộ điền đủ các ô hiện có | 95 | 88 |
| Như hai dòng trên, thêm phường, ngày trống, hợp đồng, điện nước | 86 / 95 | 100 / 100 |
| Tin điển hình: giá, số điện thoại, 2PN, quận, loại hình | 36 | 36 |
| Như dòng trên nhưng không có ảnh | 30 | 29 |

## 5. Cổng kiểm cho lượt code

- Mỗi luật ở mục 3 có một test đỏ trước khi sửa và xanh sau khi sửa. Gỡ luật đó đi thì đúng test
  của nó đỏ trở lại.
- Có test ghim tổng điểm bằng 100 cho từng loại nhà. Test này tính tổng từ chính bảng trường,
  không ghi cứng con số.
- Có test cho tình huống khu vực: khách tìm ở "Sơn Trà", môi giới gõ "son tra" trên webapp, căn
  vẫn được đủ điểm khớp khu vực.
- Phát lại các lệnh lưu của app cũ trên cổng phụ, dùng bản sao DB thật: không lệnh hợp lệ nào bị
  chặn nhầm.
- Chạy luật mới trên các câu tin mẫu có trong bộ test, và đếm có bao nhiêu tin bị từ chối. Tin nào
  bị từ chối thì phải là tin thật sự sai.
- Phải có tệp data/danang_locations.json trên máy chạy bot, nếu không thì không nhận ra được phường.
