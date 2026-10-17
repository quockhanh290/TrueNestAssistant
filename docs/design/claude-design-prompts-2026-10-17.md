# Bộ prompt dán vào Claude Design: các màn mini app TrueNest (17/10/2026)

Người viết: phiên I. Chỉ đọc tài liệu và tên trường API; không sửa code, không commit.
Nguồn: `CLAUDE.md`, `docs/design/navigation-2026-10-17.md` (bản đồ trang, nội dung trang chính, nút gốc, lối tắt, 4 trạng thái), mockup `docs/design/nav-mockups/` (01-hub, 02-listings, 03-listing-detail, 04-list-states), `docs/research/tma-design-2026-10-17.md` mục 1, và tên trường trong `webapp/api.py`, `webapp/api_clients_deals.py` (đọc ngày 17/10).
Nhãn dữ liệu: **có** = trường có thật trong JSON; **chưa có API** = chưa có, thiết kế vẫn vẽ nhưng phải ghi chú "dữ liệu mẫu".

**Quyết định mới của chủ dự án (đã áp dụng toàn bộ tệp này):** màu, nút, phông giống mini app BotFather, tức theo hoàn toàn theme Telegram của người dùng. Điều này **thay** việc dùng bộ màu riêng `tokens.css` trong mockup cũ (mockup cũ chỉ có chủ đề tối xanh đậm; coi nó là tham khảo bố cục, không phải bảng màu).

---

## 0. Cách dùng

1. Mở một cuộc trò chuyện mới trong Claude Design. Dán **toàn bộ khối "Bối cảnh chung" (mục 1)** một lần, chờ nó xác nhận đã hiểu.
2. Với mỗi màn, dán **một khối prompt ở mục 2** (mỗi khối tự đứng được, nhưng vẫn dựa vào Bối cảnh chung đã dán). Mỗi lần một màn; đợi kết quả, kiểm, rồi mới sang màn tiếp để phong cách không trôi.
3. Thứ tự dựng đề xuất: (1) Trang chính; (2) Căn hộ; (3) Chi tiết căn; (4) Khách; (5) Chi tiết khách; (6) Lịch xem; (7) Đặt lịch xem; (8) Hoa hồng; (9) Ghi nhận hoa hồng; (10) Căn hợp với khách; (11) Trang đã chia sẻ; (12) Liên kết broker; (13) Đề xuất căn; (14) Hồ sơ; (15) Nâng cấp gói; (16) Cài đặt thông báo; (17) Thêm khách; (18) Thêm căn; (19) Sửa căn; (20) Bài đăng; (21) Công cụ; (22) Hướng dẫn. Lý do: sáu màn đầu quyết định ngôn ngữ chung (nhóm dòng, thẻ, nhãn trạng thái, khung nút Telegram); các màn sau tái dùng.
4. Khi nhận kết quả, đối chiếu **bảng cổng kiểm ở mục 3**. Màn nào trượt một dòng thì gửi lại đúng dòng đó kèm câu "sửa mục X của bảng cổng kiểm", đừng viết lại cả prompt.
5. Mục 4 liệt kê chỗ chưa chắc cần chủ dự án quyết trước hoặc trong lúc duyệt. Hai điểm nên quyết trước khi dựng: thẻ căn có ảnh hay không, và độ dày khối "Hôm nay".
6. Không dán token, ID thật, số điện thoại thật. Mọi dữ liệu trong prompt là mẫu tự đặt.

---

## 1. Khối "Bối cảnh chung" (dán một lần)

```
BỐI CẢNH CHUNG CHO MỌI MÀN TÔI SẼ GỬI. Đọc kỹ, ghi nhớ, chưa cần thiết kế gì. Trả lời "đã hiểu" kèm ba điều bạn thấy dễ làm sai nhất.

1. SẢN PHẨM
TrueNest là Telegram Mini App cho môi giới cho thuê căn hộ ở Đà Nẵng (Việt Nam). Môi giới dùng nó để: quản lý danh sách căn hộ đang giữ, quản lý khách đang tìm thuê, đặt và xem lịch dẫn khách đi xem, ghi hoa hồng, tạo trang chia sẻ một hoặc nhiều căn cho khách (khách mở bằng link công khai, không cần Telegram), và liên kết với môi giới khác (nhận yêu cầu tìm căn, đề xuất căn của mình).

2. NGƯỜI DÙNG
Môi giới Việt Nam, thường 25 đến 45 tuổi. Dùng điện thoại, MỘT TAY, nhiều lần mỗi ngày, thường vừa đi đường vừa dùng, thường trong lúc đang nói chuyện với khách hoặc chủ nhà. Họ cần: thấy việc hôm nay ngay khi mở; gọi, chia sẻ, đặt lịch chỉ với 1 đến 2 lần chạm; sao chép được số điện thoại và giá. Vùng bấm tối thiểu 44 px, chữ thân tối thiểu 15 px, vùng chạm quan trọng nằm ở nửa dưới màn hình khi có thể.

3. KHUNG THIẾT KẾ
Khổ 390 x 844 (điện thoại đứng). Mọi chữ trên giao diện là TIẾNG VIỆT CÓ DẤU đầy đủ (ví dụ "Căn hộ", "Hoa hồng", "Ngũ Hành Sơn"); không viết tiếng Anh trên giao diện trừ tên riêng. Dữ liệu mẫu phải thực tế (giá "14 tr/tháng", "9,5 tr/tháng"; khu An Thượng, Sơn Trà, Ngũ Hành Sơn, Hải Châu, Thanh Khê; tên khách "Chị Lan", "Anh Minh", "Chị Hạnh"). Dùng dấu phẩy thập phân kiểu Việt (9,5).

4. MÀU: CHỈ THEO THEME TELEGRAM (giống mini app của BotFather)
Mọi màu lấy từ bộ màu theme Telegram của người dùng, qua đúng các biến này và KHÔNG viết mã màu cố định nào khác:
 - nền trang: bg_color
 - nền phụ (khoảng giữa các nhóm): secondary_bg_color
 - nền nhóm dòng/thẻ: section_bg_color
 - tiêu đề nhóm: section_header_text_color
 - chữ chính: text_color
 - chữ mờ, chú thích: hint_color
 - chữ phụ (dòng thứ hai): subtitle_text_color
 - link và mũi tên chạm được: link_color
 - chữ nhấn: accent_text_color
 - nút đặc: button_color, chữ trên nút: button_text_color
 - nguy hiểm (Xoá, Huỷ, lỗi): destructive_text_color
 - nền thanh đầu (do Telegram vẽ): header_bg_color
 - đường ngăn mảnh giữa các dòng: section_separator_color
Thiết kế phải ĐẸP ở cả theme sáng và theme tối mặc định của Telegram (nền sáng/tối với màu nút xanh Telegram), và vẫn đúng khi người dùng chọn màu nút khác (ví dụ cam, tím, xanh lá): vì vậy không được giả định màu nút là xanh, không dùng màu xanh Telegram làm màu thương hiệu cứng.
NGOẠI LỆ DUY NHẤT: một bộ nhỏ màu trạng thái nghiệp vụ, MỖI MÀU CÓ BIẾN THỂ SÁNG VÀ TỐI: "Còn trống" (xanh lá), "Gấp / Cần xác nhận / Sắp quá hạn" (hổ phách), "Đã thuê" (xám trung tính), "Quá hạn" (đỏ). Dùng làm viền hoặc nền nhạt của một nhãn nhỏ (pill), không dùng cho cả mảng lớn. Khai báo chúng thành bốn biến có tên rõ ràng ở đầu tệp, mỗi biến hai giá trị sáng/tối, và nói rõ đây là ngoại lệ.

5. PHÔNG
Phông hệ thống (SF Pro trên iOS, Roboto trên Android, Segoe UI trên Windows). KHÔNG phông tuỳ biến, KHÔNG Google Fonts, không nạp phông từ ngoài. Số tiền, giờ, số đếm dùng chữ số đều (tabular-nums) để cột thẳng hàng.

6. HÌNH THỨC "BOTFATHER" (mô tả từ ảnh chụp thật)
 - Thanh đầu do TELEGRAM vẽ (tiêu đề, nút Quay lại, nút Đóng, nút ba chấm). KHÔNG vẽ header, KHÔNG vẽ nút Quay lại, KHÔNG vẽ nút Đóng. Trong khung xem trước, mô phỏng thanh đầu bằng một khung sọc xám nhạt cao khoảng 56 px có nhãn "Telegram vẽ", để biết chỗ chừa; đó không phải phần cần thiết kế.
 - Tiêu đề trang lớn, đậm, ngay đầu nội dung (không trùng với tiêu đề thanh đầu khi trang là trang con có tiêu đề riêng; trang chính dùng "Hôm nay" làm tiêu đề lớn).
 - Danh sách GOM NHÓM kiểu iOS: mỗi cụm nằm trên nền section_bg_color, bo góc cả cụm (khoảng 12 px), các dòng nối liền nhau, đường ngăn mảnh section_separator_color (thụt đầu dòng từ chỗ bắt đầu nhãn), mỗi dòng gồm icon nét mảnh (nét 1,5 px, 24 px) + nhãn + giá trị phụ tuỳ chọn + mũi tên "›".
 - Tiêu đề nhóm: chữ đậm nhỏ, màu section_header_text_color, nằm trên cụm.
 - Nút đặc bo góc (khoảng 12 px) màu button_color, chữ button_text_color, cao tối thiểu 48 px. Nút chính dùng button_color (xanh Telegram mặc định, như nút "Copy" của BotFather). Nút hành động nguy hiểm dùng màu destructive của theme (destructive_text_color; ở theme tối ra đỏ cam/san hô, KHÔNG phải đỏ thuần, như nút "Revoke" của BotFather).
 - Huy hiệu nhỏ kiểu "NEW" của BotFather: pill bo tròn, nền đặc màu nút (button_color), chữ button_text_color (trắng), chữ đậm cỡ nhỏ. Dùng cho huy hiệu số đếm (ví dụ "2" ở Liên kết broker) và nhãn "Sắp có"/"Mới". Nhãn trạng thái nghiệp vụ nhỏ (Còn trống, Gấp, Đã thuê...) theo CÙNG KIỂU huy hiệu này (pill nhỏ, chữ đậm), chỉ khác là lấy màu từ bốn màu trạng thái ngoại lệ ở mục 4.
 - Chú thích chữ xám (hint_color) NẰM DƯỚI thẻ/cụm, có thể kèm link "›" cuối câu.
 - KHÔNG thanh tab dưới. KHÔNG nút nổi (FAB). Hành động "Thêm ..." của trang danh sách là một nút trong nội dung, cạnh số đếm.

7. ĐIỀU HƯỚNG
Ba tầng: TRANG CHÍNH (hub) liệt kê các mục bằng dòng "›" -> TRANG CON (danh sách) -> TRANG CHI TIẾT hoặc FORM. Quay lại chỉ bằng nút Quay lại của Telegram. Cấu trúc: Trang chính; Căn hộ -> Chi tiết căn -> (Sửa căn, Bài đăng); Khách -> Chi tiết khách -> (Căn hợp với khách); Lịch xem -> Đặt lịch xem; Hoa hồng -> Ghi nhận hoa hồng; Trang đã chia sẻ; Liên kết broker -> Đề xuất căn; Công cụ; Hồ sơ và gói dịch vụ -> (Cài đặt thông báo, Nâng cấp gói); Hướng dẫn.

8. NÚT GỐC DO TELEGRAM VẼ
 - BackButton: hiện ở mọi trang trừ trang chính. Nằm trên thanh đầu, bạn không vẽ.
 - MainButton: Telegram vẽ ở ĐÁY màn hình, một nút rộng, dành cho đúng MỘT hành động chính của trang chi tiết hoặc form (động từ + đối tượng, ví dụ "Lưu khách"). Trang danh sách và trang chính KHÔNG có MainButton.
 - SecondaryButton: cũng do Telegram vẽ, đi đôi với MainButton (nằm bên trái nó) khi có hành động phụ thật sự.
 Trong khung xem trước, mô phỏng thanh đáy bằng một khung sọc xám nhạt cao khoảng 64 px có nhãn "Telegram vẽ: MainButton" (hoặc "SecondaryButton + MainButton") và ghi đúng chữ trên nút. Đó chỉ là chỗ giữ, không phải phần thiết kế. Nội dung cuộn phải chừa khoảng trống đáy bằng chiều cao khung này để không bị che.

9. VÙNG AN TOÀN
Chừa chỗ cho tai thỏ và thanh hệ thống: không đặt nội dung chạm mép trên/dưới. Lề hai bên 16 px. Không phần tử nào của bạn ghim sát đáy (đáy thuộc về Telegram).

10. BỐN TRẠNG THÁI CHO MỌI DANH SÁCH
 - Đang tải: 3 thẻ xám nhấp nháy (skeleton) đúng hình dạng thẻ thật; tắt nhấp nháy khi người dùng bật giảm chuyển động; không có chữ.
 - Rỗng: icon nét mảnh + tiêu đề đậm + một câu chỉ cách thêm + nút đặc "Thêm ...".
 - Lỗi mạng: icon cảnh báo + câu nói rõ chuyện gì xảy ra + nút "Thử lại" ("Không tải được danh sách" / "Kiểm tra kết nối mạng rồi thử lại. Dữ liệu của bạn không bị mất.").
 - Hết phiên (401): icon khoá + "Phiên đã hết hạn" + "Đóng ứng dụng bằng nút X ở góc trên, rồi mở lại từ bot." KHÔNG có nút Thử lại (vì thử lại vẫn 401) và KHÔNG tự vẽ nút Đóng.

11. XUẤT KẾT QUẢ
Với MỖI màn tôi yêu cầu, xuất HAI bản cạnh nhau: theme TỐI và theme SÁNG của Telegram (cùng nội dung, cùng bố cục, chỉ khác giá trị biến màu; xanh Telegram mặc định cho button_color ở cả hai). Màn danh sách thì xuất thêm khung bốn trạng thái. Đặt tên biến theme ở đầu tệp, mọi chỗ khác dùng biến.

12. KHÔNG ĐƯỢC LÀM (áp dụng mọi màn)
 - Không vẽ header, nút Quay lại, nút Đóng.
 - Không thanh tab dưới, không nút nổi, không thanh đáy tự vẽ.
 - Không mã màu cố định (hex, rgb) ngoài bốn màu trạng thái ở mục 4 và các biến theme.
 - Không phông tuỳ biến, không icon dạng ảnh bitmap; icon là SVG nét mảnh.
 - Không chặn chọn chữ trên số điện thoại và giá (cho phép sao chép).
 - Không gradient, không đổ bóng đậm, không hiệu ứng trang trí; tạo chiều sâu chỉ bằng nền section và đường ngăn mảnh.
 - Không bịa thêm trường dữ liệu ngoài những gì tôi liệt kê ở mỗi màn.
 - Không dùng emoji làm icon.

Khi tôi gửi từng màn, hãy bám đúng các quy tắc trên.
```

---

## 2. Prompt từng màn (dán từng khối, sau khi đã dán Bối cảnh chung)

Ghi chú chung: mọi khối bắt đầu bằng "MÀN: ..." để tự đứng được. "Dữ liệu thật" là trường JSON có trong API (đã đối chiếu code 17/10). Nút nào Telegram vẽ thì ghi rõ để thiết kế chỉ chừa chỗ.

### 2.1 Trang chính

```
MÀN: TRANG CHÍNH (hub), là màn mở đầu của app. Khổ 390x844, xuất theme tối và sáng.

MỤC ĐÍCH: môi giới mở app là thấy ngay việc hôm nay, có 3 lối tắt cho việc hay làm, rồi danh sách mục dẫn vào các trang con. Không MainButton, không tab dưới, không nút nổi. BackButton ẩn (đây là trang gốc).

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tiêu đề lớn đậm "Hôm nay", bên phải cùng dòng chữ hint "Thứ Bảy, 17/10".
2. MỘT thẻ lớn (một cụm gom nhóm) chia ba khối, mỗi khối có tiêu đề nhóm đậm nhỏ bên trái và số đếm bên phải:
   a. "Lịch xem" - "2 buổi". Mỗi dòng: giờ ở cột trái dạng chữ số đều "10:00" (đậm vừa), bên phải tên khách đậm "Chị Lan" và dòng phụ "2PN An Thượng"; mũi tên ›. Dòng 2: "15:30", "Anh Minh", "Studio Luxury Bạch Đằng".
   b. "Khách cần theo dõi" - "2 người". Dòng: "Anh Minh" + dòng phụ "1PN <12 tr · Sơn Trà" + nhãn trạng thái "Gấp" (hổ phách) + ›. Dòng: "Chị Hạnh" + dòng phụ "6 ngày chưa cập nhật" + ›.
   c. "Căn cần làm mới" - "5 căn". Một dòng có icon cảnh báo: "Quá 7 ngày chưa xác nhận còn trống" + ›.
3. Ba nút lối tắt cùng hàng, bằng nhau, mỗi nút icon nét mảnh phía trên + nhãn phía dưới, nền nhạt theo màu nút theme (không phải nút đặc): "Thêm căn", "Thêm khách", "Đặt lịch xem".
4. Ba cụm danh sách gom nhóm:
   Cụm 1: "Căn hộ" (giá trị phụ "12"), "Khách" ("7"), "Lịch xem" ("2 sắp tới"), "Hoa hồng" ("tháng này").
   Cụm 2: "Trang đã chia sẻ", "Liên kết broker" (huy hiệu tròn số "2" màu nút theme = yêu cầu đang chờ), "Công cụ" (dòng phụ "Mẫu tin nhắn, bộ marketing").
   Cụm 3: "Hồ sơ và gói dịch vụ", "Hướng dẫn".
   Mỗi dòng: icon nét mảnh, nhãn, giá trị phụ hint, ›.
5. Chân trang chữ hint căn giữa "@truenest_bot".

DỮ LIỆU THẬT (đối chiếu):
- Lịch xem hôm nay: có từ GET viewings (client_name, scheduled_at, status, listing_ids), NHƯNG chưa có tham số ngày và chưa trả buổi đã qua giờ; chưa có tiêu đề căn trong dòng viewing (chỉ listing_ids) -> "tiêu đề căn: chưa có API (phải ghép)".
- Khách cần theo dõi: có từ GET clients (name, urgency, status, req_summary, updated_at); trường hẹn liên hệ lại: chưa có API. Dòng "6 ngày chưa cập nhật" tính từ updated_at.
- Căn cần làm mới (số căn quá 7 ngày): chưa có API (listing_summary không có updated_at).
- Số đếm trên dòng mục (12 căn, 7 khách, 2 sắp tới) và huy hiệu "2": chưa có API tổng hợp; ghi chú trên thiết kế "số mẫu".
Mỗi khối của "Hôm nay" phải có đủ 4 trạng thái RIÊNG (tải/rỗng/lỗi/401): lỗi một khối không làm hỏng cả trang. Khi dữ liệu khối chưa có: hiện dòng hint "Chưa có dữ liệu", không bịa số.

LỐI TẮT CHÉO: dòng lịch xem -> chi tiết khách; dòng khách -> chi tiết khách; dòng căn làm mới -> Căn hộ (đã lọc quá hạn); 3 nút -> form Thêm căn / Thêm khách / Đặt lịch xem.

TRẠNG THÁI: vẽ thêm khung riêng của khối "Lịch xem" ở 4 trạng thái (tải = 2 dòng skeleton; rỗng = "Hôm nay chưa có lịch xem" + nút "Đặt lịch xem"; lỗi mạng = "Thử lại"; 401 = hướng dẫn mở lại từ bot).

KHÔNG ĐƯỢC: header tự vẽ, tab dưới, nút nổi, MainButton, hex ngoài 4 màu trạng thái, phông tuỳ biến; không thêm khối ngoài 3 khối "Hôm nay"; không biểu đồ.
```

### 2.2 Căn hộ (danh sách + bộ lọc + chế độ chọn nhiều căn)

```
MÀN: CĂN HỘ (danh sách), kèm TỜ BỘ LỌC kéo lên và CHẾ ĐỘ CHỌN NHIỀU CĂN. Xuất theme tối và sáng, thêm khung 4 trạng thái.

MỤC ĐÍCH: môi giới tìm nhanh một căn trong kho của mình, gọi chủ nhà, chia sẻ cho khách hoặc đặt lịch xem chỉ bằng 1 chạm trên thẻ (tổng 2 chạm từ trang chính).

NÚT GỐC: BackButton hiện (Telegram vẽ). MainButton ẩn ở chế độ thường. Ở chế độ CHỌN NHIỀU: MainButton hiện với chữ "Gửi 3 căn cho khách" (số theo số căn đã chọn); chừa khung sọc "Telegram vẽ: MainButton" ở đáy. Không SecondaryButton.

NỘI DUNG TỪ TRÊN XUỐNG (màn thường):
1. Tiêu đề lớn đậm "Căn hộ".
2. Hàng tìm kiếm: ô tìm bo góc với icon kính lúp, chữ gợi ý "Tìm theo tên, quận, giá", bên phải một nút vuông icon bộ lọc (mở tờ bộ lọc).
3. Hàng chip lọc đang bật, cuộn ngang: "Sơn Trà và Hải Châu", "8 - 30 tr/tháng" (chạm để bỏ).
4. Hàng số đếm: "12 căn" (hint) bên trái; bên phải nút đặc nhỏ "+ Thêm căn" (trong nội dung, không phải nút nổi).
5. Danh sách thẻ căn (mỗi thẻ một cụm bo góc). Thẻ: ô ảnh vuông bên trái (khung giữ chỗ có icon toà nhà nếu chưa có ảnh), bên phải: tiêu đề đậm "2PN An Thượng", giá lớn màu link_color "14 tr/tháng" (chữ số đều), dòng phụ "2PN · 2WC · 78 m²", dòng khu "Ngũ Hành Sơn", nhãn trạng thái pill "Còn trống" (chạm nhãn để mở hộp đổi trạng thái). Dưới thẻ, một hàng ba hành động ngăn bằng đường mảnh: "Gọi" (icon điện thoại), "Chia sẻ" (icon mũi tên lên), "Đặt lịch" (icon lịch). Chạm vùng trên của thẻ (ngoài hàng nút) mở chi tiết căn.
   Ba thẻ mẫu: (a) "2PN An Thượng", 14 tr/tháng, 2PN · 2WC · 78 m², Ngũ Hành Sơn, Còn trống. (b) "Studio Luxury Bạch Đằng", 9,5 tr/tháng, Studio · 1WC · 38 m², Hải Châu, Cần xác nhận (hổ phách). (c) "3PN The Royal Sông Hàn", 28 tr/tháng, 3PN · 2WC · 110 m², Hải Châu, Đã thuê (xám).
6. Chế độ CHỌN NHIỀU (vào bằng nhấn giữ một thẻ): thanh trên nội dung hiện "Đã chọn 3 căn" + liên kết "Bỏ chọn"; mỗi thẻ có vòng chọn (đánh dấu) ở góc; hàng Gọi/Chia sẻ/Đặt lịch ẩn; đáy chừa MainButton.
7. TỜ BỘ LỌC (bottom sheet cao khoảng 70% màn hình, có thanh kéo ở đầu, nền section): tiêu đề "Bộ lọc"; nhóm "Trạng thái" (chip chọn: Còn trống, Cần xác nhận, Đã đặt cọc, Đã thuê); "Số phòng ngủ" (Studio, 1PN, 2PN, 3PN+); "Khu vực" (chip: An Thượng, Sơn Trà, Ngũ Hành Sơn, Hải Châu, Thanh Khê); "Giá/tháng" (hai ô số: tối thiểu, tối đa, đơn vị triệu); "Diện tích tối thiểu" (ô số m²); "Nội thất" (Đầy đủ, Cơ bản, Không); "Cho nuôi thú cưng" (công tắc). Đáy sheet: nút đặc "Xem 12 căn" và nút chữ "Xoá bộ lọc". Sheet là phần ta vẽ (không phải MainButton).

DỮ LIỆU THẬT (GET listings, mỗi căn): id, title, price (chuỗi dạng "14tr") và price_vnd (số, định dạng "14 tr/tháng" ở giao diện), bedrooms, bedroom_label, area_m2, bathrooms, district, status, photo_count, photo_urls (hiện đang rỗng với dữ liệu thật), has_post, created_at, quality_score, amenities, highlights. Tham số lọc có thật: q, bedrooms, status, min_price, max_price, min_score, district, furnishing, pet_friendly, min_area, property_type. Trạng thái căn có thật: submitted (Còn trống), negotiating, deposited, rented, draft, pending_info, uncertain. Số điện thoại chủ nhà: chỉ có ở chi tiết căn (phone), không ở danh sách. Tên chủ nhà: chưa có API. Tuổi/ngày cập nhật trên thẻ: chưa có API (listing_summary không có updated_at).

LỐI TẮT: Gọi -> mở quay số (tel:); Chia sẻ -> hộp chọn chat của Telegram; Đặt lịch -> form Đặt lịch xem điền sẵn căn; chạm nhãn trạng thái -> hộp chọn trạng thái; chạm thẻ -> Chi tiết căn.

4 TRẠNG THÁI: tải = 3 skeleton thẻ (ô tìm vẫn hiện); rỗng = "Chưa có căn nào" / "Thêm căn đầu tiên bằng cách gửi tin cho bot, hoặc nhập trực tiếp tại đây." + nút "Thêm căn"; rỗng do lọc = "Không có căn khớp bộ lọc" + nút "Xoá bộ lọc"; lỗi mạng = "Thử lại"; 401 = hướng dẫn mở lại từ bot, không Thử lại.

KHÔNG ĐƯỢC: header tự vẽ, tab dưới, nút nổi, MainButton ở chế độ thường, hex ngoài 4 màu trạng thái, phông tuỳ biến. Thẻ phải đọc được khi KHÔNG có ảnh (ảnh hiện chưa có); đừng để bố cục phụ thuộc vào ảnh.
```

### 2.3 Chi tiết căn

```
MÀN: CHI TIẾT CĂN. Xuất theme tối và sáng.

MỤC ĐÍCH: xem đủ thông tin một căn, gọi chủ nhà, sửa, xem/sửa bài đăng, làm mới trạng thái, chia sẻ cho khách hoặc đặt lịch xem.

NÚT GỐC: BackButton hiện. MainButton chữ "Gửi cho khách". SecondaryButton (bên trái MainButton) chữ "Đặt lịch xem". Chừa khung sọc đáy "Telegram vẽ: SecondaryButton + MainButton".

NỘI DUNG TỪ TRÊN XUỐNG:
1. Khung ảnh lớn (tỉ lệ 16:10, bo góc); nếu chưa có ảnh: khung giữ chỗ với icon toà nhà. Có chấm trang ảnh nếu nhiều ảnh.
2. Giá lớn đậm màu link_color "14 tr/tháng" (chữ số đều).
3. Tiêu đề đậm "2PN An Thượng, Ngũ Hành Sơn".
4. Ba ô thông số nhỏ cùng hàng (nhãn hint + giá trị đậm): "Phòng ngủ 2PN", "Diện tích 78 m²", "Nội thất Đầy đủ".
5. Hàng: nhãn trạng thái pill "Còn trống" + chữ hint "Cập nhật 3 ngày trước".
6. Bốn ô hành động cùng hàng (icon + nhãn): "Gọi", "Sửa", "Bài đăng", "Làm mới".
7. Một dòng gom nhóm "Khách hợp với căn này" + số "3" + ›.
8. Cụm "Thông tin thêm" gom nhóm các dòng nhãn/giá trị: "Địa chỉ", "Toà nhà", "Số phòng tắm", "Tầng", "Tiền cọc" (ví dụ "2 tháng"), "Có thể vào ở từ", "Nuôi thú cưng". Nếu có tiện ích (amenities) và điểm nổi bật (highlights): hai dãy chip.
9. Chú thích hint dưới: điểm đầy đủ thông tin "Tin đầy đủ 85/100" kèm link "Xem phần còn thiếu ›" (liệt kê trường còn thiếu).

DỮ LIỆU THẬT (GET listing/<id>): mọi trường của danh sách (id, title, price, price_vnd, bedrooms, bedroom_label, area_m2, bathrooms, district, status, photo_count, photo_urls, has_post, created_at, quality_score, amenities, highlights) cộng: raw_text, address (street), building_name, furnishing, pet_friendly, phone (số chủ nhà), deposit_months, available_from, property_type, floor_number, post_langs, missing_fields, quality_missing. Chưa có API: "cập nhật 3 ngày trước" (không có updated_at), số "khách hợp với căn này" (chưa có API ghép khách), tên chủ nhà.

LỐI TẮT: Gọi -> tel:; Sửa -> màn Sửa căn; Bài đăng -> màn Bài đăng; Làm mới -> hộp chọn xác nhận trạng thái ("Còn trống" / "Đã thuê"); "Khách hợp với căn này" -> danh sách khách (chưa có API); MainButton -> hộp chọn chat của Telegram gửi trang chia sẻ; SecondaryButton -> Đặt lịch xem điền sẵn căn.

TRẠNG THÁI (màn chi tiết, một đối tượng): tải = skeleton khung ảnh + 3 dòng; lỗi mạng = "Không tải được căn này" + Thử lại; không tìm thấy (404) = "Căn này không còn trong danh sách của bạn"; 401 = hướng dẫn mở lại từ bot, không Thử lại. Khi tải/lỗi: MainButton và SecondaryButton ẩn.

KHÔNG ĐƯỢC: header tự vẽ, nút Quay lại, nút Đóng, tab dưới, nút nổi, thanh đáy tự vẽ (chỉ chừa chỗ), hex ngoài 4 màu trạng thái, phông tuỳ biến.
```

### 2.4 Khách (danh sách)

```
MÀN: KHÁCH (danh sách). Xuất theme tối và sáng, thêm khung 4 trạng thái.

MỤC ĐÍCH: xem khách đang theo, khách gấp lên đầu; mở chi tiết, hoặc nhảy thẳng sang "Căn hợp với khách" (2 chạm từ trang chính).

NÚT GỐC: BackButton hiện. Không MainButton, không SecondaryButton.

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tiêu đề lớn đậm "Khách".
2. Ô tìm "Tìm theo tên hoặc số điện thoại".
3. Hàng chip lọc trạng thái cuộn ngang: "Tất cả", "Mới", "Đang tìm", "Đã xem", "Đang đàm phán", "Đã chốt".
4. Hàng số đếm "7 khách" (hint) bên trái + nút đặc nhỏ "+ Thêm khách" bên phải.
5. Danh sách thẻ khách (gom nhóm, dòng nối liền): mỗi thẻ: tên đậm "Anh Minh"; nhãn "Gấp" (hổ phách) khi urgency = gấp; dòng phụ nhu cầu "1PN <12 tr · Sơn Trà"; pill trạng thái nhỏ "Đang tìm"; chữ hint "Cập nhật 6 ngày trước". Hàng hành động dưới thẻ: "Gọi" (nếu có số), "Căn hợp" (dẫn tới Căn hợp với khách). Chạm thẻ -> chi tiết khách.
   Mẫu: "Anh Minh" Gấp, 1PN <12 tr · Sơn Trà, Đang tìm; "Chị Lan", 2PN <15 tr · An Thượng, Đã liên hệ; "Chị Hạnh", 3PN <28 tr · Hải Châu, Đang đàm phán; "Anh Tuấn", Studio <9 tr · Thanh Khê, Mới.

DỮ LIỆU THẬT (GET clients, mỗi khách): id, name, phone, status, status_vi (Mới, Đã liên hệ, Đang tìm, Đã gửi tin, Đã xem, Đang đàm phán, Đã chốt, Hủy), urgency (urgent/normal/low), req_summary (chuỗi nhu cầu đã ghép), notes, updated_at. Sắp xếp sẵn khẩn lên đầu. Giới hạn cứng 100 khách. Chưa có API: tìm theo tên/số điện thoại phía máy chủ (chỉ lọc status), hẹn liên hệ lại.

LỐI TẮT: thẻ -> Chi tiết khách; "Căn hợp" -> Căn hợp với khách; "Thêm khách" -> form Thêm khách.

4 TRẠNG THÁI: tải = 3 skeleton thẻ; rỗng = "Chưa có khách nào" / "Thêm khách đầu tiên để bot ghép căn phù hợp." + nút "Thêm khách"; lỗi mạng = Thử lại; 401 = hướng dẫn mở lại từ bot, không Thử lại.

KHÔNG ĐƯỢC: header tự vẽ, tab dưới, nút nổi, MainButton, hex ngoài 4 màu trạng thái, phông tuỳ biến.
```

### 2.5 Chi tiết khách

```
MÀN: CHI TIẾT KHÁCH. Xuất theme tối và sáng.

MỤC ĐÍCH: xem nhu cầu, lịch sử xem, ghi chú của một khách; gọi; đổi trạng thái; sang bước tiếp (tìm căn hợp hoặc đặt lịch).

NÚT GỐC: BackButton hiện. MainButton "Căn hợp với khách". SecondaryButton "Đặt lịch xem". Chừa khung sọc đáy "Telegram vẽ: SecondaryButton + MainButton".

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tên lớn đậm "Chị Lan", cạnh đó pill trạng thái "Đang tìm" (chạm để đổi, mở hộp chọn); nhãn "Gấp" hổ phách nếu urgency gấp.
2. Hai nút ô: "Gọi" và "Nhắn Telegram" (nếu có).
3. Cụm gom nhóm "Nhu cầu": dòng "Ngân sách" "10 - 15 tr/tháng"; "Phòng ngủ" "2PN"; "Khu vực" "An Thượng"; "Loại" "Căn hộ"; và đoạn ghi chú gốc "Cần căn gần biển, có chỗ đậu ô tô." (requirements_raw).
4. Cụm "Lịch xem" (tối đa 3 dòng + "Xem tất cả ›"): "Thứ Hai 19/10 · 10:00", pill "Đã đặt"; "Thứ Sáu 09/10 · 15:30", pill "Đã xem".
5. Cụm "Căn đã gửi" và "Căn đã xem": mỗi dòng "2PN An Thượng" ... (chỉ có mã căn trong API; tiêu đề cần ghép).
6. Dòng ›: "Trang đã chia sẻ cho khách này".
7. Cụm "Ghi chú": danh sách ghi chú ngắn (mới nhất trên) + ô nhập "Thêm ghi chú" với nút "Lưu".
8. Chú thích hint: "Cập nhật 2 ngày trước".

DỮ LIỆU THẬT (GET client/<id>): id, name, phone, status, status_vi, urgency, req_summary, notes, updated_at, requirements_raw, budget_min, budget_max, bedrooms, district, property_type, sent_listings (danh sách mã căn), viewed_listings (mã căn), viewings (tối đa 20: id, scheduled_at, status, listing_ids, notes). Chưa có API: tiêu đề của căn trong sent/viewed/viewings (chỉ có mã), danh sách ghi chú tách từng dòng (notes là một chuỗi), số "trang đã chia sẻ cho khách này" (có client_id ở shares nhưng cần lọc).

LỐI TẮT: MainButton -> Căn hợp với khách; SecondaryButton -> Đặt lịch xem điền sẵn khách; dòng lịch xem -> Lịch xem; "Sửa" (nút chữ nhỏ cạnh tên) -> form Sửa khách; dòng căn -> Chi tiết căn.

TRẠNG THÁI: tải = skeleton; lỗi mạng = Thử lại; 404 = "Không tìm thấy khách này"; 401 = hướng dẫn mở lại từ bot, không Thử lại. Khi tải/lỗi ẩn MainButton/SecondaryButton.

KHÔNG ĐƯỢC: header tự vẽ, nút Quay lại/Đóng, tab dưới, nút nổi, hex ngoài 4 màu trạng thái, phông tuỳ biến. Hành động xoá/huỷ (nếu có) dùng màu destructive_text_color và phải hỏi xác nhận (hộp xác nhận Telegram, không phải phần thiết kế).
```

### 2.6 Căn hợp với khách

```
MÀN: CĂN HỢP VỚI KHÁCH (trang con của Chi tiết khách). Xuất theme tối và sáng, thêm khung 4 trạng thái.

MỤC ĐÍCH: xem các căn trong kho của môi giới khớp nhu cầu một khách, chọn nhiều căn rồi gửi cho khách.

NÚT GỐC: BackButton hiện. MainButton chữ "Gửi 3 căn đã chọn" (số theo số căn đang chọn; khi chưa chọn căn nào MainButton bị tắt/ẩn). Không SecondaryButton. Chừa khung sọc đáy "Telegram vẽ: MainButton".

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tiêu đề lớn "Căn hợp với Chị Lan".
2. Một cụm tóm tắt nhu cầu (dòng chip): "2PN", "10 - 15 tr/tháng", "An Thượng" + link "Sửa nhu cầu ›".
3. Hàng đếm "5 căn phù hợp" (hint) + liên kết "Chọn tất cả".
4. Danh sách thẻ căn có vòng chọn ở góc (kiểu thẻ như màn Căn hộ nhưng không có hàng Gọi/Chia sẻ/Đặt lịch): tiêu đề, giá "14 tr/tháng", "2PN · 2WC · 78 m²", khu, nhãn "Còn trống"; thêm dòng "Khớp 92%" (hint, chữ số đều) với thanh nhỏ. Mẫu: "2PN An Thượng" 14 tr, Khớp 92%; "2PN Sơn Trà Ocean View" 12 tr, Khớp 85%; "2PN Mỹ Khê" 13,5 tr, Khớp 78%.
5. Chú thích hint dưới: "Chỉ gồm căn còn trống đã xác nhận trong 7 ngày gần đây." kèm link "Hiện cả căn cũ ›".

DỮ LIỆU THẬT: chưa có API riêng cho "căn hợp với khách" (chỉ dựng tạm từ GET listings với tham số bedrooms, min_price, max_price, district, status). Điểm "Khớp %" : chưa có API (chỉ có match_score cho yêu cầu liên broker). Trường mỗi căn như danh sách Căn hộ (id, title, price_vnd, bedroom_label, area_m2, bathrooms, district, status, photo_urls...). Nhu cầu khách: budget_min, budget_max, bedrooms, district, property_type, requirements_raw (từ client/<id>).

LỐI TẮT: chạm thẻ -> Chi tiết căn; MainButton -> hộp chọn chat Telegram gửi trang chia sẻ cho khách này; "Sửa nhu cầu" -> form Sửa khách.

4 TRẠNG THÁI: tải = 3 skeleton thẻ; rỗng = "Chưa có căn khớp" / "Thử nới ngân sách hoặc khu vực." + nút "Sửa nhu cầu"; lỗi mạng = Thử lại; 401 = hướng dẫn mở lại từ bot, không Thử lại.

KHÔNG ĐƯỢC: header tự vẽ, tab dưới, nút nổi, thanh đáy tự vẽ, hex ngoài 4 màu trạng thái, phông tuỳ biến; không bịa trường "Khớp %" như thể đã có (ghi chú "dữ liệu mẫu").
```

### 2.7 Lịch xem

```
MÀN: LỊCH XEM (danh sách). Xuất theme tối và sáng, thêm khung 4 trạng thái.

MỤC ĐÍCH: xem các buổi dẫn khách đi xem sắp tới, nhóm theo ngày; mở khách; đặt lịch mới.

NÚT GỐC: BackButton hiện. Không MainButton (nút "Đặt lịch xem" nằm trong nội dung). Không SecondaryButton.

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tiêu đề lớn đậm "Lịch xem".
2. Hàng số đếm "6 buổi sắp tới" (hint) + nút đặc nhỏ "+ Đặt lịch xem".
3. Các nhóm theo ngày, mỗi nhóm có tiêu đề nhóm đậm: "Hôm nay · Thứ Bảy 17/10", "Ngày mai · Chủ Nhật 18/10", "Thứ Hai 19/10".
4. Mỗi buổi là một dòng trong cụm: cột trái giờ chữ số đều "10:00"; giữa tên khách đậm "Chị Lan" và dòng phụ "2PN An Thượng"; bên phải pill trạng thái ("Đã đặt" / "Đã xem" / "Huỷ"); ›. Có thể có dòng ghi chú hint "Mang theo hợp đồng mẫu" dưới. Mẫu: 10:00 Chị Lan (2PN An Thượng); 15:30 Anh Minh (Studio Luxury Bạch Đằng); Ngày mai 09:00 Chị Hạnh (3 căn).
5. Chú thích hint dưới cùng: "Buổi đã qua giờ sẽ ẩn khỏi danh sách." (trung thực với hành vi hiện tại của API) kèm link "Xem lịch sử ›".

DỮ LIỆU THẬT (GET viewings, mỗi buổi): id, client_id, client_name, listing_ids (mã căn, có thể nhiều), scheduled_at (epoch, hiển thị giờ Việt Nam), status (scheduled, done, cancelled), notes. Hiện API mặc định chỉ trả buổi scheduled còn trong tương lai, tối đa 50. Chưa có API: tham số ngày, tiêu đề căn trong buổi (chỉ có mã), địa chỉ để dẫn đường.

LỐI TẮT: dòng buổi -> Chi tiết khách; "+ Đặt lịch xem" -> form Đặt lịch xem; chạm giữ một dòng -> hộp chọn "Đánh dấu đã xem" / "Huỷ buổi" (Huỷ màu destructive_text_color, hỏi xác nhận).

4 TRẠNG THÁI: tải = 3 dòng skeleton theo nhóm; rỗng = "Chưa có lịch xem nào" / "Đặt lịch đầu tiên cho khách của bạn." + nút "Đặt lịch xem"; lỗi mạng = Thử lại; 401 = hướng dẫn mở lại từ bot, không Thử lại.

KHÔNG ĐƯỢC: header tự vẽ, tab dưới, nút nổi, MainButton, lưới lịch tháng nặng nề (chỉ danh sách theo ngày), hex ngoài 4 màu trạng thái, phông tuỳ biến.
```

### 2.8 Đặt lịch xem (form)

```
MÀN: ĐẶT LỊCH XEM (form). Xuất theme tối và sáng. Vẽ thêm trạng thái "đang gửi" và "lỗi trường".

MỤC ĐÍCH: đặt một buổi dẫn khách đi xem căn; có thể mở từ chi tiết căn (điền sẵn căn), chi tiết khách (điền sẵn khách) hoặc lối tắt trang chính (trống).

NÚT GỐC: BackButton hiện. MainButton chữ "Đặt lịch". Không SecondaryButton. Chừa khung sọc đáy "Telegram vẽ: MainButton". MainButton tắt cho đến khi có khách (hoặc tên khách) và thời gian.

NỘI DUNG TỪ TRÊN XUỐNG (form gom nhóm kiểu iOS, mỗi trường là một dòng nhãn + giá trị):
1. Tiêu đề lớn "Đặt lịch xem".
2. Cụm "Khách": dòng "Khách" -> giá trị "Chị Lan ›" (mở bộ chọn có ô tìm); hoặc nhập tên tự do "Hoặc nhập tên khách".
3. Cụm "Căn xem": dòng "Căn" -> "2PN An Thượng ›" (chọn nhiều căn: hiện dạng chip, có "+ Thêm căn").
4. Cụm "Thời gian": dòng "Ngày" "Thứ Hai, 19/10"; dòng "Giờ" "10:00" (chọn bằng bộ chọn của hệ thống).
5. Cụm "Ghi chú": ô nhiều dòng "Ghi chú cho buổi xem (không bắt buộc)".
6. Chú thích hint: "Bạn sẽ nhận nhắc nhở trước buổi xem." (chỉ nếu đã có nhắc nhở thật: chưa chắc, xem mục chưa chắc).
Vẽ thêm một khung có trường báo lỗi nhỏ màu destructive_text_color dưới ô: "Chọn khách hoặc nhập tên khách".

DỮ LIỆU THẬT (POST viewings nhận): client_id, client_name, listing_ids (mảng), scheduled_at, notes. Danh sách chọn khách lấy từ GET clients, chọn căn từ GET listings. Chưa có API: kiểm trùng giờ, nhắc nhở.

LỐI TẮT: dòng Khách -> bộ chọn khách (có "+ Thêm khách mới"); dòng Căn -> bộ chọn căn nhiều lựa chọn. Quay lại khi form đã sửa: hỏi xác nhận bỏ thay đổi (hộp xác nhận của Telegram, không phải phần thiết kế).

TRẠNG THÁI: không phải danh sách nên không cần đủ 4; vẽ: bình thường, MainButton đang xoay (đang gửi), lỗi trường, lỗi mạng khi gửi (thông báo trên cùng "Chưa lưu được. Thử lại.").

KHÔNG ĐƯỢC: header tự vẽ, nút Quay lại, nút Đặt lịch tự vẽ trong nội dung, tab dưới, nút nổi, hex ngoài 4 màu trạng thái, phông tuỳ biến, lịch tháng tự vẽ lớn (dùng bộ chọn ngày giờ hệ thống).
```

### 2.9 Hoa hồng

```
MÀN: HOA HỒNG (danh sách theo tháng). Xuất theme tối và sáng, thêm khung 4 trạng thái.

MỤC ĐÍCH: xem tổng hoa hồng tháng này, phần đã nhận và phần đang chờ; mở xem từng khoản; ghi nhận khoản mới.

NÚT GỐC: BackButton hiện. Không MainButton (nút "Ghi nhận hoa hồng" nằm trong nội dung). Không SecondaryButton.

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tiêu đề lớn đậm "Hoa hồng".
2. Hàng chọn tháng: nút "‹" "Tháng 10/2026" "›" (hoặc chip "Tháng này").
3. Thẻ tổng: nhãn hint "Đã nhận tháng này", số rất lớn đậm "36 tr" (chữ số đều); bên dưới hai số nhỏ: "Chờ nhận 14 tr" và "3 khoản".
4. Nút đặc "+ Ghi nhận hoa hồng".
5. Cụm "Đã nhận" (tiêu đề nhóm + số đếm): dòng: tên khách đậm "Chị Lan", dòng phụ "2PN An Thượng", bên phải số "14 tr" và ngày hint "12/10". Dòng khác "Anh Minh", "Studio Luxury Bạch Đằng", "9 tr", "05/10".
6. Cụm "Chờ nhận": "Chị Hạnh", "3PN The Royal Sông Hàn", "14 tr", pill "Chờ".
7. Chú thích hint: "Tính theo giờ Việt Nam. Khoản chưa đánh dấu đã nhận chưa vào tổng."

DỮ LIỆU THẬT (GET deals?month=YYYY-MM): month_total (tổng đã nhận, VND), month, closed[] (đã nhận) và negotiating[] (chưa nhận); mỗi khoản: id, client_name, listing_id (mã căn, chưa có tiêu đề căn), commission_vnd, paid, notes, closed_at. Chưa có API: tiêu đề căn, tổng "chờ nhận" (phải cộng phía giao diện), đổi trạng thái paid (chưa thấy route), so sánh tháng trước.

LỐI TẮT: "+ Ghi nhận hoa hồng" -> form Ghi nhận hoa hồng; dòng khoản -> (chưa có màn chi tiết khoản: ghi chú trên thiết kế); chọn tháng -> tải lại.

4 TRẠNG THÁI: tải = skeleton thẻ tổng + 3 dòng; rỗng = "Tháng này chưa có hoa hồng" / "Ghi nhận khoản đầu tiên sau khi chốt một căn." + nút "Ghi nhận hoa hồng"; lỗi mạng = Thử lại; 401 = hướng dẫn mở lại từ bot, không Thử lại.

KHÔNG ĐƯỢC: header tự vẽ, tab dưới, nút nổi, MainButton, biểu đồ cột/tròn (không có dữ liệu để vẽ), hex ngoài 4 màu trạng thái, phông tuỳ biến.
```

### 2.10 Ghi nhận hoa hồng (form)

```
MÀN: GHI NHẬN HOA HỒNG (form). Xuất theme tối và sáng, kèm trạng thái lỗi trường và đang gửi.

MỤC ĐÍCH: ghi một khoản hoa hồng sau khi chốt một căn cho một khách.

NÚT GỐC: BackButton hiện. MainButton "Lưu hoa hồng" (tắt khi chưa nhập số tiền). Không SecondaryButton. Chừa khung sọc đáy "Telegram vẽ: MainButton".

NỘI DUNG TỪ TRÊN XUỐNG (form gom nhóm iOS):
1. Tiêu đề lớn "Ghi nhận hoa hồng".
2. Cụm "Khách": dòng "Khách" "Chị Lan ›" (bộ chọn có tìm) hoặc ô nhập tên khách.
3. Cụm "Căn": dòng "Căn đã chốt" "2PN An Thượng ›" (bộ chọn có tìm).
4. Cụm "Số tiền": ô số lớn, chữ số đều, đơn vị "đồng" cố định bên phải, dưới có các chip gợi ý nhanh "7 tr", "14 tr", "21 tr" (một tháng, hai tháng... chỉ là chip điền nhanh, không tính tự động); dòng hint hiện số đã định dạng "14.000.000 đ".
5. Cụm "Ghi chú": ô nhiều dòng không bắt buộc.
6. Chú thích hint: "Khoản mới ghi sẽ nằm ở mục Chờ nhận cho đến khi bạn đánh dấu đã nhận." (nếu route đánh dấu đã nhận chưa có thì ghi chú "chưa có API").

DỮ LIỆU THẬT (POST deals nhận): client_id, client_name, listing_id, commission_amount (số VND), notes. Chưa có API: trường ngày chốt, trạng thái đã nhận khi tạo.

LỐI TẮT: chọn khách và căn từ danh sách đã có (GET clients, GET listings), có ô tìm.

TRẠNG THÁI: bình thường; lỗi trường ("Nhập số tiền hợp lệ"); MainButton đang xoay; lỗi mạng khi gửi ("Chưa lưu được. Thử lại."). Thoát khi đã sửa: hỏi xác nhận (hộp Telegram).

KHÔNG ĐƯỢC: header tự vẽ, nút Lưu tự vẽ trong nội dung, tab dưới, nút nổi, hex ngoài 4 màu trạng thái, phông tuỳ biến.
```

### 2.11 Trang đã chia sẻ

```
MÀN: TRANG ĐÃ CHIA SẺ (danh sách). Xuất theme tối và sáng, thêm khung 4 trạng thái.

MỤC ĐÍCH: xem các trang tổng hợp căn đã gửi cho khách (khách mở bằng link công khai), biết khách đã xem và đã đặt lịch chưa.

NÚT GỐC: BackButton hiện. Không MainButton, không SecondaryButton (tạo trang mới đi từ chế độ chọn nhiều căn ở màn Căn hộ).

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tiêu đề lớn đậm "Trang đã chia sẻ".
2. Hàng số đếm "4 trang" (hint).
3. Danh sách thẻ gom nhóm: mỗi thẻ có tiêu đề đậm "Căn cho Chị Lan" (title), dòng phụ "3 căn · tạo 15/10", hàng ba số nhỏ có icon: "12 lượt xem", "2 lượt đặt lịch", và chữ hint "Hết hạn 22/10" (nếu sắp hết hạn: nhãn hổ phách "Còn 2 ngày"). Hai nút chữ cuối thẻ: "Sao chép link", "Chia sẻ lại". Chạm thẻ mở danh sách căn trong trang.
   Mẫu: "Căn cho Chị Lan" 3 căn, 12 lượt xem, 2 lượt đặt; "Studio khu Bạch Đằng" 5 căn, 4 lượt xem, 0 đặt; "Căn cho Anh Minh" 2 căn, 0 lượt xem (nhãn hint "Chưa ai mở").
4. Chú thích hint dưới: "Khách mở link không cần Telegram." kèm link "Xem trang khách thấy ›".

DỮ LIỆU THẬT (GET shares, mỗi trang): token, title, client_id, listing_count, view_count, booking_count, bookings (danh sách đặt lịch; cấu trúc trong mảng chưa kiểm), created_at, expires_at. Chưa có API: tên khách (chỉ có client_id; cần ghép), danh sách căn trong trang, tắt/gia hạn trang.

LỐI TẮT: "Sao chép link" -> sao chép đường dẫn công khai; "Chia sẻ lại" -> hộp chọn chat Telegram; chạm thẻ -> chi tiết trang (chưa có màn: ghi chú); từ Chi tiết khách -> lọc trang của khách này.

4 TRẠNG THÁI: tải = 3 skeleton thẻ; rỗng = "Chưa chia sẻ trang nào" / "Chọn vài căn ở mục Căn hộ rồi bấm Gửi cho khách." + nút "Mở Căn hộ"; lỗi mạng = Thử lại; 401 = hướng dẫn mở lại từ bot, không Thử lại.

KHÔNG ĐƯỢC: header tự vẽ, tab dưới, nút nổi, MainButton, biểu đồ lượt xem, hex ngoài 4 màu trạng thái, phông tuỳ biến.
```

### 2.12 Liên kết broker (danh sách yêu cầu)

```
MÀN: LIÊN KẾT BROKER (danh sách yêu cầu từ môi giới khác). Xuất theme tối và sáng, thêm khung 4 trạng thái.

MỤC ĐÍCH: xem các yêu cầu tìm căn do môi giới khác đăng, để đề xuất căn của mình. Tính năng có giới hạn lượt thử theo gói.

NÚT GỐC: BackButton hiện. Không MainButton, không SecondaryButton.

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tiêu đề lớn đậm "Liên kết broker".
2. Dải thông tin lượt thử (cụm nhỏ nền section): "Còn 2 lượt thử miễn phí" + link "Nâng cấp ›" (dẫn tới Nâng cấp gói). Khi gói đủ quyền: ẩn dải này.
3. Hàng số đếm "2 yêu cầu đang mở" (hint).
4. Danh sách thẻ yêu cầu: tiêu đề đậm "2PN gần biển, ngân sách 15 tr" (summary), dòng phụ "An Thượng · 2PN · tối đa 15 tr", nhãn "Gấp" (hổ phách) khi urgency gấp, hàng dưới: "1/3 broker đã đề xuất" (response_count / max_responders, chữ số đều) và "Đăng 2 giờ trước". Chạm thẻ mở màn Đề xuất căn.
   Mẫu: "Tìm 2PN gần biển cho khách đi làm" An Thượng, 2PN, ≤ 15 tr, 1/3; "Studio Hải Châu ngắn hạn" Hải Châu, Studio, ≤ 9 tr, 3/3 (nhãn xám "Đã đủ").
5. Chú thích hint dưới: "Chỉ hiện yêu cầu của môi giới khác." 

DỮ LIỆU THẬT (GET xbroker): requests[] mỗi yêu cầu: id, summary, urgency, response_count, max_responders, created_at, budget_max, bedrooms, district; trial: allowed, remaining, required_tier ("max"). Chưa có API: tên môi giới đăng yêu cầu (có thể cố ý ẩn), mốc "đã đề xuất của tôi" trong danh sách.

LỐI TẮT: thẻ -> Đề xuất căn; dải lượt thử -> Nâng cấp gói. Trang chính hiện huy hiệu số yêu cầu đang chờ cho dòng "Liên kết broker".

4 TRẠNG THÁI: tải = 3 skeleton thẻ; rỗng = "Chưa có yêu cầu nào" / "Khi môi giới khác đăng yêu cầu, bạn sẽ thấy ở đây." (không có nút thêm); hết lượt thử / không đủ gói = trạng thái thứ năm "Cần nâng cấp" với nút đặc "Xem gói"; lỗi mạng = Thử lại; 401 = hướng dẫn mở lại từ bot, không Thử lại.

KHÔNG ĐƯỢC: header tự vẽ, tab dưới, nút nổi, MainButton, hex ngoài 4 màu trạng thái, phông tuỳ biến.
```

### 2.13 Đề xuất căn (cho một yêu cầu liên broker)

```
MÀN: ĐỀ XUẤT CĂN (trang con của Liên kết broker). Xuất theme tối và sáng, thêm khung 4 trạng thái.

MỤC ĐÍCH: chọn các căn của mình khớp một yêu cầu của môi giới khác, rồi gửi đề xuất.

NÚT GỐC: BackButton hiện. MainButton chữ "Gửi đề xuất (2 căn)" (số theo số căn chọn; tắt khi chưa chọn). Không SecondaryButton. Chừa khung sọc đáy "Telegram vẽ: MainButton".

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tiêu đề lớn "Đề xuất căn".
2. Cụm "Yêu cầu" (nền section): summary đậm "Tìm 2PN gần biển cho khách đi làm"; chip "An Thượng", "2PN", "≤ 15 tr/tháng"; nhãn "Gấp" hổ phách; dòng hint "Hết hạn sau 18 giờ" (từ expires_at); "Còn 2 chỗ trong 3".
3. Hàng đếm "4 căn khớp" (hint) + nhãn "Tối đa chọn 5 căn" (max_listings).
4. Danh sách thẻ căn có vòng chọn: tiêu đề, giá "14 tr/tháng", "2PN · 2WC · 78 m²", khu; dòng "Khớp 92" (match_score, chữ số đều) và nhãn độ mới (freshness_label): "Mới", "Cần cập nhật" (hổ phách), kèm "5 ngày trước" (age_days). Căn đã đề xuất trước đó có dấu "Đã gửi".
5. Chú thích hint dưới: "Đã ẩn 3 căn không khớp tiêu chí cứng và 1 căn quá cũ (trên 60 ngày)." kèm link "Làm mới căn ›".
6. Biến thể: yêu cầu đã hết hạn (nút tắt, nhãn "Đã hết hạn"); không còn chỗ; đang bị tạm cấm đề xuất (propose_cooldown_until): thẻ cảnh báo màu destructive_text_color "Tạm khoá đề xuất đến 24/10".

DỮ LIỆU THẬT (GET propose/<request_id>): request {id, summary, requirements{budget_min, budget_max, bedrooms, district, property_type}, requirements_raw, urgency, expires_at, expired, status}, has_slot, slot_released, propose_cooldown_until, already_submitted (mã căn), listings[] (các trường căn như danh sách cộng match_score, quality_score, age_days, freshness_emoji, freshness_label, freshness_mult, quality_missing, potential_score), failed_summary (số căn bị loại theo từng tiêu chí, kèm stale), stale_count, stale_ids, max_listings.

LỐI TẮT: chạm thẻ -> Chi tiết căn; "Làm mới căn" -> Căn hộ (lọc căn cũ); MainButton -> gửi (POST propose) rồi quay về danh sách yêu cầu với thông báo "Đã gửi 2 căn".

4 TRẠNG THÁI: tải = skeleton cụm yêu cầu + 3 thẻ; rỗng = "Chưa có căn nào khớp" / "Cập nhật căn hoặc thêm căn mới để đề xuất." + nút "Mở Căn hộ" (nhả chỗ tự động nếu không có căn nào); lỗi mạng = Thử lại; 401 = hướng dẫn mở lại từ bot, không Thử lại.

KHÔNG ĐƯỢC: header tự vẽ, tab dưới, nút nổi, nút Gửi tự vẽ, hex ngoài 4 màu trạng thái, phông tuỳ biến; không dùng emoji tròn màu của API làm icon độ mới (vẽ pill chữ theo màu trạng thái).
```

### 2.14 Hồ sơ và gói dịch vụ

```
MÀN: HỒ SƠ VÀ GÓI DỊCH VỤ. Xuất theme tối và sáng.

MỤC ĐÍCH: xem thông tin môi giới, điểm uy tín, gói hiện tại; đi tới cài đặt thông báo, nâng cấp gói, giới thiệu bạn; sửa tên/điện thoại/cách xưng hô.

NÚT GỐC: BackButton hiện. MainButton "Lưu" CHỈ khi form hồ sơ có thay đổi (ẩn khi chưa sửa). Không SecondaryButton.

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tiêu đề lớn đậm "Hồ sơ".
2. Thẻ nhận diện: vòng tròn chữ cái đầu "K", tên đậm "Anh Khoa", chip gói "Miễn phí" (hoặc "Pro", "Max").
3. Cụm "Điểm uy tín": số lớn "78 / 100", hai dòng nhỏ có thanh: "Độ đầy đủ tin 82%", "Độ mới tin 70%"; dòng hint "8 trên 12 căn đầy đủ · 6 căn còn mới". Nếu có báo cáo làm mới sai: dòng cảnh báo hổ phách "1 báo cáo làm mới sai".
4. Cụm "Thống kê": "Tổng căn 12", "Đang còn trống 7", "Đã thuê 3", "Lượt xem trang chia sẻ 41" (chữ số đều).
5. Cụm "Thông tin": "Tên hiển thị" "Anh Khoa" (sửa được), "Số điện thoại" "0xxx xxx xxx" (mẫu che), "Cách xưng hô" "anh" (chọn: anh/chị).
6. Cụm danh sách dòng ›: "Cài đặt thông báo", "Nâng cấp gói" (giá trị phụ: "Miễn phí"), "Giới thiệu bạn" (giá trị phụ "2/3 người").
7. Chú thích hint: "Điểm uy tín giúp bạn được ưu tiên khi liên kết broker." kèm link "Cách tính điểm ›".

DỮ LIỆU THẬT (GET profile): name, phone, pronoun, tier, score, completeness, freshness, complete_listings, fresh_listings, false_refresh_reports, stats{total_listings, active_listings, rented_listings, share_views}. GET referral: link, invited, qualified, needed, reward_months_active, max_stack. Chưa có API: tổng căn quá 7 ngày, ảnh đại diện, cách tính điểm chi tiết. Lưu ý: số "đang còn trống" chỉ đếm trạng thái đã gửi (submitted).

LỐI TẮT: dòng ›: -> Cài đặt thông báo / Nâng cấp gói / Giới thiệu bạn (chia sẻ link mời qua hộp chọn chat Telegram). Màn này cũng mở được từ nút Settings trong menu ngữ cảnh của Telegram.

TRẠNG THÁI: tải = skeleton thẻ + cụm; lỗi mạng = Thử lại; 401 = hướng dẫn mở lại từ bot, không Thử lại.

KHÔNG ĐƯỢC: header tự vẽ, tab dưới, nút nổi, nút Lưu tự vẽ trong nội dung, biểu đồ tròn/vòng điểm màu mè (dùng số và thanh mảnh), hex ngoài 4 màu trạng thái, phông tuỳ biến, số điện thoại thật.
```

### 2.15 Nâng cấp gói

```
MÀN: NÂNG CẤP GÓI. Xuất theme tối và sáng.

MỤC ĐÍCH: xem các gói và gửi yêu cầu nâng cấp (duyệt thủ công, không thanh toán trong app).

NÚT GỐC: BackButton hiện. MainButton "Gửi yêu cầu nâng cấp" (tắt khi chưa chọn gói, hoặc khi đã có yêu cầu đang chờ). Không SecondaryButton. Chừa khung sọc đáy "Telegram vẽ: MainButton".

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tiêu đề lớn "Nâng cấp gói".
2. Dòng hint "Gói hiện tại: Miễn phí".
3. Hai thẻ gói chọn một (kiểu chọn của iOS, có vòng chọn): "Pro" và "Max". Mỗi thẻ: tên đậm, danh sách 3 đến 4 dòng quyền lợi có dấu tích ("Gửi trang chia sẻ không giới hạn" cho Pro; "Liên kết broker không giới hạn" cho Max và gồm cả quyền Pro). Giá: ghi "Liên hệ" (chưa có giá).
4. Cụm "Lượt thử của bạn": "Gửi cho khách: còn 2/3 lượt", "Liên kết broker: còn 3/3 lượt".
5. Chú thích hint: "Yêu cầu sẽ được duyệt thủ công. Bạn nhận thông báo qua bot."
6. Biến thể đã có yêu cầu chờ: thẻ nền section "Yêu cầu nâng cấp Pro đang chờ duyệt", MainButton tắt.

DỮ LIỆU THẬT: POST premium/request chỉ nhận tier ("pro" hoặc "max"); trả lỗi "đã có yêu cầu đang chờ" nếu trùng. GET profile.tier (gói hiện tại). GET trial/<feature> (feature: send2client, xbroker_match): allowed, remaining (-1 = không giới hạn), limit, required_tier. Chưa có API: nội dung quyền lợi từng gói, giá, hạn dùng gói (tier_expires_at có trong DB nhưng chưa lộ ra API), trạng thái yêu cầu đang chờ (chỉ biết qua lỗi 409). Nội dung quyền lợi và giá trên thiết kế là dữ liệu mẫu.

LỐI TẮT: sau khi gửi: quay về Hồ sơ với thông báo "Đã gửi yêu cầu".

TRẠNG THÁI: tải = skeleton; lỗi mạng khi gửi = thông báo + Thử lại; 409 = biến thể "đang chờ"; 401 = hướng dẫn mở lại từ bot, không Thử lại.

KHÔNG ĐƯỢC: header tự vẽ, tab dưới, nút nổi, nút gửi tự vẽ, hex ngoài 4 màu trạng thái, phông tuỳ biến, mô phỏng thanh toán/thẻ ngân hàng, đếm ngược khuyến mãi.
```

### 2.16 Cài đặt thông báo

```
MÀN: CÀI ĐẶT THÔNG BÁO. Xuất theme tối và sáng.

MỤC ĐÍCH: bật/tắt từng loại thông báo bot gửi. Công tắc lưu ngay khi gạt.

NÚT GỐC: BackButton hiện. KHÔNG MainButton (công tắc lưu ngay). Không SecondaryButton.

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tiêu đề lớn "Thông báo".
2. Một cụm gom nhóm gồm 4 dòng, mỗi dòng: icon nét mảnh + nhãn + dòng phụ hint + công tắc kiểu iOS (màu bật = button_color):
   - "Lead phù hợp" / "Khi có khách của broker khác khớp căn của bạn"
   - "Điểm tin giảm" / "Khi một tin sắp bị trừ điểm vì quá cũ"
   - "Sắp hết lượt thử" / "Nhắc trước khi lượt thử miễn phí hết"
   - "Khách đặt lịch" / "Khi khách đặt lịch qua trang chia sẻ"
3. Chú thích hint dưới: "Thông báo gửi qua tin nhắn của bot trong Telegram."
4. Vẽ thêm trạng thái một công tắc đang lưu (xoay nhỏ) và trạng thái lưu lỗi (công tắc nảy về cũ + dòng báo lỗi màu destructive_text_color "Chưa lưu được. Thử lại.").

DỮ LIỆU THẬT (GET notify/prefs): prefs[] mỗi mục: key (notify_match, notify_quality, notify_trial, notify_booking), label (chuỗi tiếng Việt kèm emoji từ API, bỏ emoji khi hiển thị), enabled. PUT notify/prefs {pref, value}. Dòng phụ mô tả từng loại: chưa có API (viết sẵn trong giao diện).

TRẠNG THÁI: tải = 4 dòng skeleton; lỗi mạng = Thử lại; 401 = hướng dẫn mở lại từ bot, không Thử lại. (Không có trạng thái rỗng vì luôn đủ 4 mục.)

KHÔNG ĐƯỢC: header tự vẽ, MainButton, tab dưới, nút nổi, nút "Lưu" trong nội dung, hex ngoài 4 màu trạng thái, phông tuỳ biến.
```

### 2.17 Thêm khách / Sửa khách (form)

```
MÀN: THÊM KHÁCH (cũng dùng làm SỬA KHÁCH với dữ liệu điền sẵn). Xuất theme tối và sáng, kèm lỗi trường và đang gửi.

MỤC ĐÍCH: tạo nhanh một khách mới (lối tắt 1 chạm từ trang chính) hoặc sửa thông tin khách.

NÚT GỐC: BackButton hiện. MainButton "Lưu khách" (tắt khi chưa có tên). Không SecondaryButton. Chừa khung sọc đáy "Telegram vẽ: MainButton".

NỘI DUNG TỪ TRÊN XUỐNG (form gom nhóm iOS):
1. Tiêu đề lớn "Thêm khách" (biến thể: "Sửa khách").
2. Cụm "Liên hệ": "Tên khách" (bắt buộc) "Chị Lan"; "Số điện thoại" (không bắt buộc, mẫu che).
3. Cụm "Nhu cầu": "Ngân sách tối thiểu" và "Ngân sách tối đa" (hai ô số, đơn vị triệu/tháng); "Số phòng ngủ" (chọn: Studio, 1, 2, 3+); "Khu vực" (chọn chip: An Thượng, Sơn Trà, Ngũ Hành Sơn, Hải Châu, Thanh Khê); "Loại nhà" (chọn); ô nhiều dòng "Yêu cầu khác" ("Cần căn gần biển, có chỗ đậu ô tô.").
4. Cụm "Mức khẩn": ba lựa chọn đoạn "Bình thường", "Gấp", "Thấp".
5. Biến thể Sửa: thêm dòng "Trạng thái" -> hộp chọn (Mới, Đã liên hệ, Đang tìm, Đã gửi tin, Đã xem, Đang đàm phán, Đã chốt, Hủy).

DỮ LIỆU THẬT (POST clients nhận): name (bắt buộc), phone, requirements_raw, budget_min, budget_max, bedrooms, district, property_type, urgency. PUT client/<id> nhận thêm status, notes. Chưa có API: hẹn liên hệ lại, nguồn khách, xoá khách.

TRẠNG THÁI: bình thường; lỗi trường tên ("Vui lòng nhập tên khách"); MainButton đang xoay; lỗi mạng khi gửi. Thoát khi đã sửa: hỏi xác nhận (hộp Telegram).

KHÔNG ĐƯỢC: header tự vẽ, nút Lưu tự vẽ, tab dưới, nút nổi, hex ngoài 4 màu trạng thái, phông tuỳ biến, số điện thoại thật.
```

### 2.18 Thêm căn (form)

```
MÀN: THÊM CĂN (form nhập trực tiếp trên mini app). Xuất theme tối và sáng, kèm lỗi trường và đang gửi.

MỤC ĐÍCH: nhập một căn mới ngay trong app (hiện chỉ có thể gửi tin cho bot). Đây là lối tắt 1 chạm ở trang chính.

NÚT GỐC: BackButton hiện. MainButton "Lưu căn" (tắt khi thiếu giá hoặc khu vực). Không SecondaryButton. Chừa khung sọc đáy "Telegram vẽ: MainButton".

NỘI DUNG TỪ TRÊN XUỐNG (form gom nhóm iOS):
1. Tiêu đề lớn "Thêm căn".
2. Cụm "Cơ bản": "Giá thuê" (số, đơn vị "triệu/tháng", chữ số đều, mẫu 14), "Loại" (chọn: Studio, Căn hộ, Nhà nguyên căn), "Số phòng ngủ", "Số phòng tắm", "Diện tích" (m²).
3. Cụm "Vị trí": "Khu vực" (chọn: An Thượng, Sơn Trà, Ngũ Hành Sơn, Hải Châu, Thanh Khê), "Toà nhà" (mẫu "The Royal Sông Hàn"), "Đường/địa chỉ".
4. Cụm "Chi tiết": "Nội thất" (Đầy đủ, Cơ bản, Không), "Tiền cọc" (số tháng), "Nuôi thú cưng" (công tắc), "Vào ở từ" (ngày).
5. Cụm "Liên hệ chủ nhà": "Số điện thoại chủ nhà" (mẫu che).
6. Cụm "Mô tả": ô nhiều dòng.
7. Cụm "Ảnh": ô "Thêm ảnh" (chưa có API ảnh: ghi chú trên thiết kế "Hiện ảnh gửi qua bot").
8. Chú thích hint: "Càng đủ thông tin, điểm tin càng cao." kèm "Điểm tin dự kiến 70/100" (chữ số đều).

DỮ LIỆU THẬT: chưa có API tạo căn (phải thêm). Các trường đã có ở API sửa căn (PUT listing/<id>): price_vnd, bedrooms, bathrooms, area_m2, district, street, building_name, furnished, pet_friendly, deposit, description. Chưa có: loại nhà khi tạo, số điện thoại chủ nhà khi tạo, ngày vào ở khi sửa, ảnh, tầng (floor_number chỉ đọc). Phần nào chưa có API thì thiết kế vẫn vẽ nhưng ghi chú "chưa có API".

TRẠNG THÁI: bình thường; lỗi trường ("Nhập giá thuê"); MainButton đang xoay; lỗi mạng khi gửi. Thoát khi đã sửa: hỏi xác nhận (hộp Telegram).

KHÔNG ĐƯỢC: header tự vẽ, nút Lưu tự vẽ, tab dưới, nút nổi, hex ngoài 4 màu trạng thái, phông tuỳ biến, số điện thoại thật, trình nhập nhiều bước (một trang cuộn là đủ).
```

### 2.19 Sửa căn (form)

```
MÀN: SỬA CĂN (form có dữ liệu điền sẵn). Xuất theme tối và sáng, kèm lỗi trường và đang gửi.

MỤC ĐÍCH: sửa thông tin một căn đang có (ít dùng, 3 chạm từ trang chính: Căn hộ, chi tiết, Sửa).

NÚT GỐC: BackButton hiện. MainButton "Lưu thay đổi" (TẮT khi chưa đổi gì). Không SecondaryButton. Chừa khung sọc đáy "Telegram vẽ: MainButton".

NỘI DUNG TỪ TRÊN XUỐNG (form gom nhóm iOS, điền sẵn từ căn "2PN An Thượng"):
1. Tiêu đề lớn "Sửa căn", dòng phụ hint "2PN An Thượng".
2. Cụm "Cơ bản": "Giá thuê" 14 (triệu/tháng), "Số phòng ngủ" 2, "Số phòng tắm" 2, "Diện tích" 78 m².
3. Cụm "Vị trí": "Khu vực" "Ngũ Hành Sơn", "Toà nhà", "Đường/địa chỉ".
4. Cụm "Chi tiết": "Nội thất" "Đầy đủ", "Tiền cọc", "Nuôi thú cưng" (công tắc).
5. Cụm "Mô tả": ô nhiều dòng.
6. Trường đã sửa được tô nhẹ (viền hoặc chấm nhỏ màu button_color) để thấy chỗ khác bản gốc.
7. Cụm cuối "Vùng nguy hiểm": một dòng chữ destructive_text_color "Đánh dấu đã thuê" (hộp xác nhận); không có "Xoá căn" (chưa có API).

DỮ LIỆU THẬT (PUT listing/<id>): chỉ nhận price_vnd, bedrooms, bathrooms, area_m2, district, street, building_name, furnished, pet_friendly, deposit, description. Đọc từ GET listing/<id>. Đổi trạng thái: PUT listing/<id>/status. Chưa có API: sửa ảnh, số điện thoại chủ nhà, tầng, xoá căn.

TRẠNG THÁI: bình thường; chưa đổi gì (MainButton tắt); lỗi trường; đang gửi; lỗi mạng khi gửi. Thoát khi có thay đổi chưa lưu: hỏi xác nhận (hộp Telegram).

KHÔNG ĐƯỢC: header tự vẽ, nút Lưu tự vẽ, tab dưới, nút nổi, hex ngoài 4 màu trạng thái, phông tuỳ biến.
```

### 2.20 Bài đăng

```
MÀN: BÀI ĐĂNG (xem và sửa bài đăng của một căn theo ngôn ngữ). Xuất theme tối và sáng.

MỤC ĐÍCH: xem, sửa và sao chép bài đăng quảng cáo căn để dán lên nhóm/Facebook/Zalo. Ít dùng (3 chạm).

NÚT GỐC: BackButton hiện. MainButton "Lưu bài đăng" (chỉ bật khi có thay đổi). SecondaryButton (bên trái) "Sao chép". Chừa khung sọc đáy "Telegram vẽ: SecondaryButton + MainButton".

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tiêu đề lớn "Bài đăng", dòng phụ hint "2PN An Thượng".
2. Hàng chip chọn ngôn ngữ cuộn ngang: "Tiếng Việt" (đang chọn), "English", "한국어", "中文", "Русский"; ngôn ngữ chưa có bài hiện chấm hint "chưa có".
3. Ô văn bản lớn nhiều dòng, nền section, bo góc, chữ chọn/sao chép được, chứa bài mẫu: "CHO THUÊ 2PN AN THƯỢNG\n14 tr/tháng · 78 m² · Đầy đủ nội thất\nGần biển Mỹ Khê, 5 phút ra phố ẩm thực An Thượng.\nLiên hệ: [số điện thoại]" (dùng chỗ giữ chỗ cho số điện thoại, không số thật).
4. Chú thích hint dưới ô: "Bài tự động tạo từ thông tin căn. Bạn sửa tự do rồi lưu." và bộ đếm ký tự chữ số đều "186 ký tự".
5. Trạng thái "chưa có bài ở ngôn ngữ này": khung rỗng "Chưa có bài tiếng Anh" + nút đặc "Tạo bài tiếng Anh" (nếu chưa có API tạo: ghi chú).

DỮ LIỆU THẬT: GET post/<id>?lang=vi: lang, text, langs (các ngôn ngữ đã có). PUT post/<id> {lang, text} với lang thuộc vi, en, ko, zh, ru. Chưa có API: tạo bài tự động trong mini app (hiện qua bot), lịch sử chỉnh sửa.

LỐI TẮT: "Sao chép" -> sao chép nội dung vào bộ nhớ và hiện thông báo ngắn "Đã sao chép"; từ Chi tiết căn dòng "Bài đăng".

TRẠNG THÁI: tải = skeleton ô văn bản; rỗng (ngôn ngữ chưa có bài); lỗi mạng = Thử lại; 401 = hướng dẫn mở lại từ bot, không Thử lại. Thoát khi có thay đổi chưa lưu: hỏi xác nhận (hộp Telegram).

KHÔNG ĐƯỢC: header tự vẽ, nút Lưu/Sao chép tự vẽ ở đáy, tab dưới, nút nổi, hex ngoài 4 màu trạng thái, phông tuỳ biến, số điện thoại thật.
```

### 2.21 Công cụ

```
MÀN: CÔNG CỤ (trang con gom hai công cụ). Xuất theme tối và sáng.

MỤC ĐÍCH: nơi chứa mẫu tin nhắn có sẵn (để gửi nhanh cho khách/chủ nhà) và bộ marketing (ảnh/bài quảng cáo). Dùng ít.

NÚT GỐC: BackButton hiện. Không MainButton, không SecondaryButton.

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tiêu đề lớn "Công cụ".
2. Cụm danh sách dòng ›: "Mẫu tin nhắn" (dòng phụ "Lời chào, báo giá, nhắc lịch xem" và giá trị "6"), "Bộ marketing" (dòng phụ "Ảnh và bài đăng sẵn" và nhãn nhỏ "Sắp có").
3. Chú thích hint dưới: "Công cụ mới sẽ thêm ở đây."
4. Vẽ thêm MÀN CON "Mẫu tin nhắn" (danh sách): mỗi dòng tên mẫu đậm "Nhắc lịch xem", hai dòng xem trước chữ hint "Chào chị Lan, mai 10:00 em dẫn chị đi xem...", nút chữ "Sao chép". Có đủ 4 trạng thái (tải/rỗng với nút "Thêm mẫu"/lỗi/401).

DỮ LIỆU THẬT: chưa có API cho Mẫu tin nhắn và Bộ marketing (mẫu hiện nằm trong bot; nội dung màn này là dữ liệu mẫu, ghi chú "chưa có API" trên thiết kế). Công cụ chỉ dùng chữ tiếng Việt.

LỐI TẮT: dòng -> màn con tương ứng.

KHÔNG ĐƯỢC: header tự vẽ, tab dưới, nút nổi, MainButton, hex ngoài 4 màu trạng thái, phông tuỳ biến, hứa tính năng chưa có như thể đã chạy được (dùng nhãn "Sắp có").
```

### 2.22 Hướng dẫn

```
MÀN: HƯỚNG DẪN (nội dung tĩnh). Xuất theme tối và sáng.

MỤC ĐÍCH: giúp môi giới mới hiểu cách dùng app và bot; tìm nhanh một câu trả lời.

NÚT GỐC: BackButton hiện. Không MainButton, không SecondaryButton.

NỘI DUNG TỪ TRÊN XUỐNG:
1. Tiêu đề lớn "Hướng dẫn".
2. Cụm "Bắt đầu" (gom nhóm, dòng ›, mở rộng tại chỗ khi chạm): "Thêm căn đầu tiên", "Thêm khách và tìm căn hợp", "Đặt lịch xem", "Chia sẻ căn cho khách".
3. Cụm "Mẹo": "Làm mới căn mỗi 7 ngày để giữ điểm uy tín", "Ghi hoa hồng ngay sau khi chốt", "Liên kết broker để nhận khách".
4. Cụm "Liên hệ hỗ trợ": dòng "Nhắn cho bot" ›.
5. Mỗi mục mở rộng hiện đoạn 2 đến 3 câu tiếng Việt ngắn (dữ liệu mẫu) với danh sách đánh số.
6. Chú thích hint: "Cần thêm trợ giúp? Gõ /help trong bot."

DỮ LIỆU THẬT: không có API (nội dung tĩnh trong giao diện). Chỉ cần dựng khung; nội dung do chủ dự án viết, nội dung trên thiết kế là mẫu.

TRẠNG THÁI: không cần 4 trạng thái vì là nội dung tĩnh.

KHÔNG ĐƯỢC: header tự vẽ, tab dưới, nút nổi, video nhúng, hex ngoài 4 màu trạng thái, phông tuỳ biến.
```

---

## 3. Bảng cổng kiểm khi nhận thiết kế về

Mỗi dòng kiểm được bằng mắt hoặc đếm. Áp cho MỖI màn (trừ khi ghi riêng).

| # | Điều kiểm | Cách kiểm | Đạt khi |
|---|---|---|---|
| 1 | Có cả bản theme tối VÀ sáng | Đếm số khung cạnh nhau | 2 bản mỗi màn |
| 2 | Không vẽ header, nút Quay lại, nút Đóng | Nhìn vùng 56 px đầu | Chỉ có khung sọc "Telegram vẽ" |
| 3 | Không thanh tab dưới, không nút nổi | Nhìn vùng đáy và góc phải dưới | Không có |
| 4 | Thanh đáy là khung "Telegram vẽ" đúng loại | Đọc nhãn khung | Danh sách/trang chính/Công cụ/Hướng dẫn/Thông báo: không có khung; chi tiết/form: có khung, chữ đúng bảng ở mục 5 |
| 5 | Chữ trên MainButton đúng bảng | So với cột MainButton ở mục 5 | Khớp chữ từng ký tự |
| 6 | Không mã màu cố định | Mở mã, tìm `#` kèm 3 đến 6 ký tự hex và `rgb(` | Không có, trừ 4 biến màu trạng thái (mỗi biến 2 giá trị) |
| 7 | Mọi màu qua biến theme | Đếm tên biến ở đầu tệp | Đủ nhóm 14 biến theme ở mục 1 (kể cả header_bg_color, section_separator_color) và chỉ dùng chúng |
| 8 | Bộ màu trạng thái có biến thể sáng-tối | Xem 4 biến | Đúng 4: còn trống, gấp/cần xác nhận, đã thuê, quá hạn; mỗi biến 2 giá trị |
| 9 | Phông hệ thống | Mở mã, tìm `font-family` | Chỉ chuỗi hệ thống (system-ui, SF Pro, Roboto, Segoe UI); không `@font-face`, không Google Fonts |
| 10 | Số tiền, giờ, số đếm chữ số đều | Mở mã, tìm `tabular-nums` | Có ở giá, giờ, số đếm |
| 11 | Chữ tiếng Việt có dấu đầy đủ, không tiếng Anh trên giao diện | Đọc toàn bộ chữ | Không thiếu dấu, không chữ Anh (trừ tên riêng) |
| 12 | Dữ liệu mẫu thực tế | Đọc | Có giá "14 tr/tháng", khu An Thượng/Sơn Trà/Ngũ Hành Sơn..., khách "Chị Lan"; không số điện thoại thật |
| 13 | Danh sách gom nhóm kiểu BotFather | Nhìn cụm dòng | Nền section, bo góc cả cụm, dòng nối liền, đường ngăn mảnh, icon nét mảnh + nhãn + ›; không thẻ tách rời kiểu card nổi trong trang chính/hồ sơ/công cụ |
| 14 | Tiêu đề trang lớn đậm, tiêu đề nhóm đậm | Nhìn | Có |
| 15 | Nút đặc theo button_color, cao tối thiểu 48 px; vùng bấm tối thiểu 44 px | Đo bằng thước trên khung 390 | Đạt |
| 15b | Nút nguy hiểm dùng destructive_text_color (theme tối ra đỏ cam/san hô, không đỏ thuần); huy hiệu nhỏ là pill nền button_color chữ trắng | Nhìn bản tối | Đúng màu và kiểu |
| 16 | Hành động "Thêm ..." của danh sách nằm trong nội dung | Nhìn hàng số đếm | Có nút "+ Thêm ..." cạnh số đếm, không phải FAB |
| 17 | Danh sách có đủ 4 trạng thái (tải, rỗng, lỗi mạng, 401) | Đếm khung | 4 khung mỗi danh sách |
| 18 | 401 không có nút "Thử lại" và không tự vẽ nút Đóng | Nhìn khung 401 | Chỉ có hướng dẫn "Đóng ... rồi mở lại từ bot" |
| 19 | Lỗi mạng có "Thử lại"; rỗng có nút thêm đúng mục (trừ Liên kết broker, Công cụ) | Nhìn | Có |
| 20 | Skeleton đúng hình thẻ thật, không chữ | Nhìn | Đạt |
| 21 | Chừa khoảng trống đáy bằng chiều cao thanh Telegram ở màn có MainButton | Cuộn xuống đáy | Nội dung cuối không bị khung đáy che |
| 22 | Lề hai bên 16 px, không nội dung chạm mép trên/dưới | Đo | Đạt |
| 23 | Trang chính: đủ 3 khối "Hôm nay", 3 lối tắt, 9 dòng mục chia 4 + 3 + 2 | Đếm | Khớp |
| 24 | Trang chính: không MainButton, BackButton ẩn | Nhìn | Đúng |
| 25 | Căn hộ: ba nút Gọi, Chia sẻ, Đặt lịch trên mỗi thẻ; thẻ đọc được khi không có ảnh | Đếm nút; che ảnh | 3 nút/thẻ; không vỡ bố cục |
| 26 | Chi tiết căn: MainButton "Gửi cho khách", SecondaryButton "Đặt lịch xem" | Đọc nhãn khung | Khớp |
| 27 | Màn dùng trường chưa có API được ghi chú | Tìm ghi chú "chưa có API" / "dữ liệu mẫu" | Mọi trường ở danh sách "chưa có API" của mục 4.2 đều có ghi chú |
| 28 | Chia sẻ cho khách nhiều căn: MainButton đổi chữ theo số căn chọn | Xem chế độ chọn nhiều | "Gửi N căn cho khách" |
| 29 | Đạt trên theme sáng: chữ hint đủ tương phản trên nền | Nhìn bản sáng | Đọc được chữ hint, chữ trên nút, nhãn trạng thái |
| 30 | Đạt khi đổi màu nút (thử cam hoặc tím) | Yêu cầu một biến thể | Không còn chỗ nào dính màu xanh cứng |
| 31 | Form không có nút Lưu tự vẽ; quay lại khi đã sửa có chú thích "hỏi xác nhận" | Nhìn | Đúng |
| 32 | Số đối chiếu: số đếm tiêu đề khớp số dòng mẫu (ví dụ "2 buổi" có đúng 2 dòng) | Đếm | Khớp |

---

## 4. Tham chiếu và các điểm cần quyết

### 4.1 Bảng nút gốc (đối chiếu cổng kiểm #5)

| Màn | BackButton | MainButton | SecondaryButton |
|---|---|---|---|
| Trang chính | ẩn | ẩn | ẩn |
| Căn hộ (thường) | hiện | ẩn | ẩn |
| Căn hộ (chọn nhiều) | hiện | "Gửi N căn cho khách" | ẩn |
| Chi tiết căn | hiện | "Gửi cho khách" | "Đặt lịch xem" |
| Sửa căn | hiện | "Lưu thay đổi" (tắt khi chưa đổi) | ẩn |
| Thêm căn | hiện | "Lưu căn" | ẩn |
| Bài đăng | hiện | "Lưu bài đăng" | "Sao chép" |
| Khách | hiện | ẩn | ẩn |
| Chi tiết khách | hiện | "Căn hợp với khách" | "Đặt lịch xem" |
| Căn hợp với khách | hiện | "Gửi N căn đã chọn" | ẩn |
| Thêm/Sửa khách | hiện | "Lưu khách" | ẩn |
| Lịch xem | hiện | ẩn | ẩn |
| Đặt lịch xem | hiện | "Đặt lịch" | ẩn |
| Hoa hồng | hiện | ẩn | ẩn |
| Ghi nhận hoa hồng | hiện | "Lưu hoa hồng" | ẩn |
| Trang đã chia sẻ | hiện | ẩn | ẩn |
| Liên kết broker | hiện | ẩn | ẩn |
| Đề xuất căn | hiện | "Gửi đề xuất (N căn)" | ẩn |
| Công cụ | hiện | ẩn | ẩn |
| Hồ sơ | hiện | "Lưu" chỉ khi có thay đổi | ẩn |
| Cài đặt thông báo | hiện | ẩn (công tắc lưu ngay) | ẩn |
| Nâng cấp gói | hiện | "Gửi yêu cầu nâng cấp" | ẩn |
| Hướng dẫn | hiện | ẩn | ẩn |

Nguồn: `docs/design/navigation-2026-10-17.md` mục 5.

### 4.2 Trường dữ liệu thiết kế cần mà API chưa có (đối chiếu code 17/10)

1. Trang chính: tham số ngày và buổi đã qua giờ cho lịch xem hôm nay; hẹn liên hệ lại của khách; số căn quá 7 ngày; số đếm từng mục (căn, khách, buổi sắp tới); huy hiệu số yêu cầu liên broker đang chờ (có thể lấy từ `xbroker` nhưng cần gọi thêm).
2. Căn: ngày cập nhật hoặc tuổi (`updated_at`/`age_days`) trong danh sách và chi tiết; tên chủ nhà; số khách hợp với căn; ảnh (`photo_urls` đang rỗng).
3. Khách: căn hợp với khách (route và điểm khớp); tìm kiếm phía máy chủ; ghi chú tách từng dòng; tiêu đề căn trong `sent_listings`, `viewed_listings`, `viewings`.
4. Lịch xem: tiêu đề căn và địa chỉ trong buổi xem; đổi trạng thái buổi (đã xem, huỷ) chưa thấy route.
5. Hoa hồng: tiêu đề căn, tổng chờ nhận, route đánh dấu đã nhận, so sánh tháng trước.
6. Trang đã chia sẻ: tên khách, danh sách căn trong trang, gia hạn hoặc tắt trang.
7. Liên kết broker: không thiếu trường chính; thiếu mốc "đã đề xuất của tôi" trong danh sách.
8. Hồ sơ: ảnh đại diện, quyền lợi từng gói, giá, hạn gói, trạng thái yêu cầu nâng cấp đang chờ (chỉ biết qua lỗi 409).
9. Thêm căn: toàn bộ API tạo căn (đã ghi trong tài liệu điều hướng); sửa căn thiếu loại nhà, số điện thoại chủ nhà.
10. Công cụ (mẫu tin nhắn, bộ marketing), Hướng dẫn: không có API.
11. Bài đăng: tạo bài tự động trong mini app.

### 4.3 Chưa chắc / cần chủ dự án quyết

1. **Thẻ căn có ảnh hay không.** `photo_urls` hiện rỗng với dữ liệu thật. Prompt yêu cầu thẻ phải đọc được khi không có ảnh nhưng vẫn chừa ô ảnh vuông ở trái (theo mockup đã duyệt). Câu hỏi: giữ ô ảnh giả hay bỏ hẳn cho tới khi có ảnh (tiết kiệm chiều cao, thấy được nhiều căn hơn)? Chưa đo số thẻ nhìn thấy trên màn 360x640.
2. **Độ dày khối "Hôm nay".** Mockup: 2 buổi + 2 khách + 1 dòng căn làm mới, chiếm khoảng một nửa màn hình đầu (khoảng 430 px trên 844 px, ước từ ảnh, chưa đo). Cần quyết: giới hạn tối đa bao nhiêu dòng mỗi khối (đề xuất 3 và "Xem tất cả ›"), và có cho thu gọn không.
3. **Bố cục từ mockup cũ có dựa trên màu riêng.** Quyết định mới (theo theme Telegram) làm mất màu thương hiệu cố định; các nhãn nhấn như giá màu xanh nhạt trong mockup cũ nay thành `link_color`, có thể đổi sắc theo theme người dùng. Cần chủ dự án duyệt trên một theme lạ (cam, tím) trước khi chốt.
4. **Màu trạng thái "Gấp" hổ phách vs nút theme màu cam.** Nếu người dùng chọn màu nút cam, nhãn "Gấp" dễ lẫn với nút. Chưa có đề xuất chắc; cổng kiểm #30 sẽ bắt ra.
5. **Kết quả của Claude Design có thể tự thêm màu hoặc phông.** Cổng #6 và #9 là cách bắt. Chưa biết Claude Design tuân thủ "chỉ biến theme" tới mức nào; cần thử ở màn đầu (Trang chính) trước khi dán tiếp.
6. **Nhắc nhở trước buổi xem (Đặt lịch xem):** chưa kiểm bot có gửi nhắc thật không (có hàm lấy buổi sắp tới trong `db/viewings.py` nhưng chưa đọc luồng gửi); dòng chú thích trong prompt Đặt lịch xem ghi "chỉ nếu đã có nhắc nhở thật". Cần xác minh trước khi giữ dòng này.
7. **Khoản hoa hồng "Chờ nhận":** API chia `closed` (paid) và `negotiating` (chưa paid), tức "đang đàm phán" cũng có thể là khoản đã ghi mà chưa nhận. Nhãn "Chờ nhận" là diễn giải của tôi, chưa xác nhận ý nghĩa nghiệp vụ.
8. **Màn "Thêm khách / Sửa khách" và chế độ chọn nhiều căn** không nằm trong danh sách màn bạn yêu cầu mà nằm trong bản đồ; tôi đã thêm màn Thêm/Sửa khách (cần cho lối tắt "Thêm khách" ở trang chính). Chế độ chọn nhiều căn gộp vào prompt Căn hộ.
9. **Chưa kiểm trên máy thật:** mọi giả định về khung sọc "Telegram vẽ" (chiều cao thanh đầu 56 px, thanh đáy 64 px) là mô phỏng, chưa đo; BackButton/MainButton/SecondaryButton cần thử trên Telegram thật (iOS hoặc Android) trước khi báo xong theo luật cổng kiểm của repo.
10. **Giá "tr/tháng" định dạng:** API trả chuỗi "14tr"; thiết kế dùng "14 tr/tháng" và dấu phẩy thập phân (9,5). Giao diện phải tự định dạng từ `price_vnd`, không dùng `price`.
