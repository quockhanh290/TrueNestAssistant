# TrueNest Platform — Thông điệp & Honour System

_Tài liệu nội bộ: những gì cần nói rõ với broker và khách_

---

## Nguyên tắc hiển thị

1. **Ngắn gọn trong flow:** onboarding và tin nhắn chỉ nói ý chính (1-2 dòng)
2. **Chi tiết trong Terms:** menu có mục "📜 Điều khoản" chứa đầy đủ
3. **Đồng ý trước khi release contact:** broker và khách đều phải bấm "Đồng ý" với điều khoản TRƯỚC KHI bot release contact lần đầu
   - Broker: đồng ý khi nhận match đầu tiên
   - Khách: đồng ý khi chọn broker đầu tiên
   - Sau đó không nhắc lại (trừ khi điều khoản thay đổi)

## Pattern: khách không xác nhận → trừ điểm broker

Nếu broker có pattern khách không xác nhận (vd: 3 deal liên tiếp không có xác nhận từ khách):
- Trừ điểm uy tín (tỷ lệ xác nhận thấp)
- Lý do: hoặc broker không chăm khách, hoặc deal không thật, hoặc broker dặn khách đừng xác nhận — cả 3 đều là red flag

> Platform vận hành trên hệ thống danh dự (honour system).
> Chúng tôi duy trì hạ tầng, kết nối khách với môi giới tốt nhất,
> và chỉ thu phí khi giao dịch thành công.
>
> Đổi lại, chúng tôi cần sự trung thực từ cả hai phía:
> broker xác nhận kết quả deal, khách đánh giá trải nghiệm.
> Chính những xác nhận này giúp platform tồn tại, được duy trì,
> và ngày càng cung cấp dịch vụ tốt hơn cho tất cả.

**Tại sao honour system mà không phải hợp đồng cứng:**
- Chi phí duy trì hạ tầng (server, bot, matching engine) là thật
- Nhưng chúng tôi không muốn rào cản gia nhập cao
- Tin vào cộng đồng: ai trung thực → được ưu tiên → có nhiều cơ hội hơn
- Ai gian lận → mất uy tín → tự loại khỏi hệ thống

---

## Nói với Broker (onboarding + nhắc định kỳ)

### Khi mới vào:
```
🤝 Chào mừng anh đến với TrueNest!

Cách hoạt động:
✅ Anh đăng tin → hoàn toàn miễn phí
✅ Có khách phù hợp → bot báo cho anh
✅ Anh chốt deal → trả 20% hoa hồng cho platform

Tại sao 20%? Để duy trì hệ thống:
- Server, bot, công nghệ matching
- Tìm kiếm khách hàng thật cho anh
- Không có platform, anh tự tìm khách tốn hơn nhiều

📊 Anh có điểm uy tín — càng cao càng được ưu tiên.
Điểm tính từ: chất lượng tin, độ tươi, tốc độ phản hồi,
độ chăm khách, và tỷ lệ xác nhận deal.

⚠️ Quan trọng: sau mỗi deal, anh XÁC NHẬN kết quả giúp em.
Không xác nhận = điểm giảm = ít cơ hội sau này.
```

### Khi nhận match:
```
🔍 Có khách cần: [yêu cầu chi tiết]

Anh có 1 giờ để submit tối đa 5 tin phù hợp.
Nhanh tay nhé — 5 người đầu tiên được chọn.

⚠️ Lưu ý: KHÔNG có thông tin liên lạc của khách ở đây.
Anh chỉ nhận được contact SAU KHI khách chọn anh.
Đây là để bảo vệ cả anh và khách.
```

### Khi được khách chọn:
```
🎉 Khách đã chọn anh!

Contact khách: [chi tiết]
5 tin anh đã đề xuất: [danh sách]

Em đã tự thêm khách vào danh sách của anh
(nguồn: broadcast) để anh follow-up.

📋 Nhắc nhẹ: sau khi xong deal, anh xác nhận giúp em nhé.
Đây là cách anh giữ điểm uy tín cao.
```

### Khi đến hạn xác nhận (7/14/30 ngày):
```
Anh ơi, deal với [khách] sao rồi ạ?
[✅ Đã chốt] [❌ Chưa chốt] [⏳ Đang đàm phán]

Xác nhận giúp em để giữ điểm uy tín nhé 🙏
Platform duy trì được là nhờ sự trung thực của anh đó ạ.
```

---

## Nói với Khách (bot khách — build sau)

### Khi mới vào:
```
👋 Chào bạn! Mình giúp bạn tìm nhà ở Đà Nẵng.

Cách hoạt động:
✅ Bạn mô tả nhu cầu → mình tìm môi giới phù hợp
✅ Bạn xem đề xuất → chọn người bạn thích
✅ Hoàn toàn miễn phí cho bạn!

Chúng mình vận hành trên honour system:
sau khi thuê được nhà, bạn xác nhận giúp mình nhé.
Điều này giúp mình duy trì dịch vụ miễn phí cho bạn
và những người đến sau. 🙏
```

### Khi nhận đề xuất:
```
Mình tìm được 3 môi giới phù hợp cho bạn:

1. 🏠 2PN An Thượng, 12tr ⭐
   Môi giới: ★★★★☆ (uy tín 85/100)

2. 🏠 2PN Sơn Trà, 14tr
   Môi giới: ★★★★☆ (uy tín 78/100)

[...]

Bạn muốn làm việc với ai? Hoặc chọn từng căn
để dùng dịch vụ concierge (có phí).
```

### Sau khi chọn broker:
```
Đã kết nối bạn với [broker]! 🎉

Thông tin liên lạc của bạn đã được gửi cho họ.
Hai bên tự trao đổi tiếp nhé.

Sau khi thuê được nhà, bạn quay lại xác nhận giúp mình nhé —
điều này giúp mình tiếp tục phục vụ miễn phí. 🙏
```

### Nhắc xác nhận:
```
Bạn ơi, bạn đã thuê được nhà chưa? 🏠
[✅ Rồi, qua anh/chị X] [❌ Chưa] [⏳ Đang xem]

Xác nhận giúp mình để mình cải thiện dịch vụ nhé!
```

### Trước khi hết hợp đồng (45 ngày):
```
Chào bạn! Hợp đồng của bạn sắp hết (ngày X). 📅

Bạn muốn:
[Gia hạn với anh/chị X] [Tìm chỗ mới]

Mình hỗ trợ bạn như lần trước nhé!
```

---

## Concierge — nói với khách

```
🎩 Dịch vụ Concierge

Bạn thích từng căn lẻ thay vì chọn 1 môi giới?
Mình sẽ tìm người dẫn bạn đi xem các căn bạn đã chọn.

Phí: 250K-300K/căn
→ Người dẫn xem nhận phần lớn, platform giữ 50K/căn
   để duy trì hệ thống.

Bạn chọn các căn muốn xem nhé!
```

---

## Bảng giá tóm tắt (nói rõ từ đầu)

| Dịch vụ | Ai trả | Giá |
|---|---|---|
| Đăng tin (broker) | Free | 0đ |
| Match thường | Free | 0đ |
| Concierge | Khách | 250-300K/tin |
| Platform cắt (concierge) | Từ phí concierge | 50K/tin |
| Hoa hồng deal | Broker | 20% |
| Beta (3 tháng đầu) | — | FREE toàn bộ |

---

## Cơ chế khuyến khích xác nhận (chốt)

**Nguyên tắc:** đẩy việc "ép" khách xác nhận thành việc của broker — vì broker được lợi.

```
Khách xác nhận deal
→ Broker được GIẢM tỷ lệ hoa hồng cho platform
   (vd: từ 20% xuống thấp hơn — con số cụ thể thảo luận sau)
→ Điểm uy tín tăng

Khách KHÔNG xác nhận
→ Broker giữ full hoa hồng deal đó
→ NHƯNG bị trừ điểm uy tín dần
→ Dưới ngưỡng → remove khỏi hệ thống
```

**Logic:** broker tự cân nhắc — ăn trọn 1 deal nhưng mất nguồn lead tương lai, hay chia ít cho platform để giữ uy tín và nhận lead tiếp.

**Lưu ý:** vì platform đã lấy thấp (20%), động cơ gian lận vốn đã thấp. Cơ chế này chỉ là lớp bảo vệ thêm.
