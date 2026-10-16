# Bot Khách — Spec (build sau)

_Ý tưởng: 2026-10-16, Khanh_

## Triết lý
Bot khách KHÔNG phải công cụ filter đơn thuần.
Nó là **cố vấn thuê nhà** — đưa thông tin để khách tự ra quyết định đúng.

## Thông tin cung cấp cho khách

### 1. Giá thị trường
```
📊 Giá trung bình khu vực bạn quan tâm:

Sơn Trà — 2PN:
• Trung bình: 13.5tr/tháng
• Khoảng giá: 10tr – 18tr
• 127 tin đang có

💡 Tin bạn đang xem (12tr) thấp hơn TB 11% — giá tốt!
```

- Theo quận × số PN
- So sánh tin đang xem vs trung bình
- Cảnh báo nếu giá quá cao/thấp bất thường

### 2. Guidance theo khu vực
```
📍 Sơn Trà — những điều cần biết:

✅ Gần biển, nhiều Tây, an ninh tốt
⚠️ Kẹt xe giờ cao điểm đường Võ Nguyên Giáp
💡 Giá thuê tăng 8% so với năm ngoái
🏫 Gần trường quốc tế ABC
```

- Ưu/nhược điểm từng khu
- Hạ tầng, giao thông, tiện ích
- Biến động giá

### 3. Checklist thuê nhà
```
📋 Trước khi ký hợp đồng, bạn nên kiểm tra:

□ Chủ nhà có sổ đỏ / giấy ủy quyền không?
□ Hợp đồng ghi rõ ai trả phí quản lý?
□ Đặt cọc bao nhiêu? Điều kiện hoàn cọc?
□ Có được nuôi pet không? (ghi vào HĐ)
□ Kiểm tra nước nóng, máy lạnh, wifi trước khi nhận nhà
```

### 4. Cảnh báo lừa đảo
```
⚠️ Dấu hiệu tin lừa đảo:
• Giá rẻ bất thường (thấp hơn TB 40%+)
• Yêu cầu chuyển cọc trước khi xem nhà
• Không cho xem nhà trực tiếp
• Ảnh đẹp lung linh nhưng địa chỉ mơ hồ

Tin bạn đang xem: ✅ không có dấu hiệu bất thường
```

### 5. So sánh tin
```
Bạn đang phân vân giữa 3 tin:

| | Tin 1 | Tin 2 | Tin 3 |
|---|---|---|---|
| Giá | 12tr | 14tr | 11tr |
| vs TB khu vực | -11% ✅ | +4% | -19% ✅ |
| Diện tích | 75m² | 80m² | 60m² |
| Giá/m² | 160K | 175K | 183K |
| Độ đầy đủ tin | ⭐ 90% | 65% | ⭐ 85% |
| Uy tín MG | 85 | 78 | 65 |
```

## Flow bot khách

```
1. Chào + hỏi nhu cầu (ngân sách, khu vực, số PN...)
2. Hiện giá TB khu vực → "ngân sách của bạn hợp lý không?"
3. Broadcast cho broker (như spec match)
4. Nhận đề xuất → hiện 5 căn/lần, mỗi căn có nút concierge
5. Khách chọn broker HOẶC thêm từng căn vào giỏ concierge
   HOẶC bấm "xem thêm" → hiện 5 căn tiếp
   → vẫn không ưng → gợi ý nới tiêu chí → match lại
6. Kết nối → follow-up → xác nhận → đánh giá
7. Trước hết HĐ 45 ngày → hỏi gia hạn/tìm mới
```

### Hiển thị đề xuất (từng căn một)
Mỗi căn hiện riêng với 3 nút:

```
🏠 2PN An Thượng, 12tr ⭐
   75m² | ban công | cho pet
   💰 Rẻ hơn TB 11% ✅
   Môi giới: ★★★★☆ (85)

   [⭐ Shortlist] [⏭️ Bỏ qua] [🎩 Concierge]
```

- **Shortlist:** thêm vào danh sách muốn xem
- **Bỏ qua:** qua căn tiếp theo
- **Concierge:** thêm vào giỏ concierge (trả phí)
- Khách xem hết 15 căn → dừng

### Sau 15 căn
```
Bạn đã xem hết 15 căn. Bạn muốn?
[🔄 Xem lại 15 căn vừa rồi] [➡️ Xem 15 căn mới] [✅ Xong]
```

- **Xem lại:** hiện lại 15 căn cũ (giữ nguyên shortlist đã chọn, cho đổi ý)
- **Xem mới:** hiện 15 căn tiếp theo từ inventory
- Cả 2 trường hợp đều ghi nhận lựa chọn

### Sau 30 căn (2 đợt) vẫn chưa đủ
```
Có vẻ bạn gặp khó khăn trong việc quyết định. 🤔
Bạn có muốn xem lại yêu cầu của mình không?
[Sửa yêu cầu] [Không, cảm ơn]
```

**Nếu sửa:** (như cũ — broadcast lần 2, tag 🔄, báo broker cũ)

**Nếu không:**
```
Cảm ơn bạn đã dành thời gian! 🙏

Khi có căn mới phù hợp với yêu cầu của bạn,
mình sẽ báo ngay nhé. Bạn cứ yên tâm!
```
- Lưu yêu cầu vào "wishlist" → có tin mới match → auto notify
- Không làm phiền broker thêm

## Nguồn dữ liệu
- Giá TB: tính từ inventory của broker (real-time)
- Guidance khu vực: cần biên soạn tay ban đầu, cập nhật dần
- Checklist: template cố định
- Cảnh báo: rule-based từ dữ liệu tin

## Chưa quyết định
- [ ] Tên bot khách
- [ ] Ngôn ngữ: tiếng Anh (cho expat) hay song ngữ?
- [ ] Guidance khu vực: ai biên soạn? (Khanh? thuê người?)
- [ ] Có cho khách xem trực tiếp inventory không, hay chỉ qua broker?
