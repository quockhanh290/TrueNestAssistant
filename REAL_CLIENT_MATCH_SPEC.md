# Real Client Match — Spec (triển khai sau)

_Quyết định: 2026-10-16, Khanh thiết kế_

## Nguyên tắc
- **Công bằng:** mọi broker đều thấy cùng thông tin
- **Không lộ contact khách:** tuyệt đối không broadcast SĐT/tên khách
- **Khách tự chọn:** hệ thống đề xuất 3, khách quyết định

## Flow chi tiết

### 1. Broadcast
- Bot nhận yêu cầu từ khách (sẽ build bot riêng sau)
- Broadcast lên channel với ĐẦY ĐỦ thông tin yêu cầu:
  ```
  🔍 KHÁCH CẦN TÌM:
  📍 Sơn Trà, gần biển
  🏠 2PN, 2WC
  💰 Dưới 15tr/tháng
  📅 Dọn vào đầu tháng 11
  ✨ Cần ban công, cho nuôi mèo

  ⚡ 5 người phản hồi nhanh nhất được submit tin
  ```
- **KHÔNG có:** tên khách, SĐT, Telegram, bất kỳ contact nào

### 2. Reserve (giữ chỗ)
- Broker bấm "Tôi có tin phù hợp" → reserve 1 slot
- Đủ 5 người → những người sau thấy:
  ```
  Đã đủ 5 người. Anh đang ở vị trí chờ số 3.
  Nếu có người không submit, em báo anh ngay.
  ```
- Queue minh bạch: mỗi người biết mình là số mấy

### 3. Submit (30 phút)
- 5 người được chọn nhận DM với chi tiết + nút submit
- Mỗi người chọn listing từ kho của mình để đề xuất
- **Timeout 30 phút:** không submit → mất slot → người tiếp theo trong queue được đôn lên
- Người bị loại nhận: "Hết giờ rồi ạ, slot đã chuyển cho người tiếp theo."

### 4. Xếp hạng
- Đủ listing từ 5 broker (hoặc hết queue) → chấm điểm:
  ```
  Điểm = điểm match tin × percentile hồ sơ broker
  ```
- Lấy top 3

### 5. Gửi cho khách
- Khách nhận 3 đề xuất (thông tin tin + hồ sơ broker ẩn danh):
  ```
  1. 🏠 2PN An Thượng, 12tr ⭐
     Môi giới: ★★★★☆ (điểm uy tín 85)

  2. 🏠 2PN Sơn Trà, 14tr
     Môi giới: ★★★★☆ (điểm uy tín 78)

  3. 🏠 2PN Mỹ Khê, 13tr ⭐
     Môi giới: ★★★☆☆ (điểm uy tín 65)

  Anh chọn làm việc với ai ạ?
  ```

### 6. Khách chọn broker
- Khách xem up to 15 căn (3 broker × 5 căn), nhóm theo broker
- Khách chọn 1 BROKER (không phải 1 căn) để làm việc cùng
- **Tự động release:** khách bấm chọn → bot gửi ngay cho broker:
  ```
  🎉 Khách đã chọn anh!

  👤 Tên: [tên khách]
  📱 SĐT: [sđt]
  📝 Yêu cầu: [tóm tắt]

  🏠 5 tin anh đã đề xuất:
  1. ...
  2. ...

  2 bên tự liên lạc nhé. Em sẽ follow-up ạ!
  ```

### 7. Tự động cập nhật bên broker
- Bot tự tạo client mới trong danh sách của broker:
  - Tên, SĐT từ thông tin khách release
  - Trạng thái: `sent` (đã gửi tin)
  - Nguồn: `broadcast_channel`
  - Ghi chú: yêu cầu gốc + 5 tin đã đề xuất
- Broker không cần nhập tay

### 8. Follow-up kép cho đến khi deal done
- **Bot khách:** hỏi định kỳ "Anh đã xem nhà chưa? Tình hình sao rồi ạ?"
- **Bot broker:** nhắc follow-up theo pipeline bình thường
- Cả 2 bên cập nhật đến khi trạng thái = `rented` hoặc `cancelled`

### 9. Chống gian lận hoa hồng
**Vấn đề:** khách confirm đã chốt với broker X, nhưng broker X báo "không chốt được" để né hoa hồng.

**Xử lý:**
```
Khách báo "đã chốt" + Broker báo "chưa chốt"
→ Bot đối chiếu → gắn cờ mâu thuẫn
→ Warning 1: "Hệ thống ghi nhận mâu thuẫn về deal [X].
   Anh kiểm tra lại giúp em nhé."
→ Warning 2: tương tự, nghiêm khắc hơn
→ Warning 3: 🚫 BAN khỏi hệ thống match
```

**Lưu ý:** đây là hệ thống riêng với anti-spam (spam_strikes).
Bảng mới: `commission_disputes` hoặc dùng chung cơ chế.

## Chống bypass
- Contact khách KHÔNG BAO GIỜ xuất hiện trong broadcast, DM cho broker, hay bất kỳ đâu trước khi khách chọn
- Broker chỉ thấy contact khách SAU KHI được khách chọn
- Broker tìm cách liên hệ khách ngoài luồng → chưa định nghĩa chế tài

## Concierge Service (pick từng tin lẻ)

**Khi nào:** khách không thích cả 5 căn của 1 broker, muốn pick từng tin lẻ từ danh sách đề xuất.

**Flow:**
1. Khách bấm "Chọn từng tin" → tick các tin muốn xem → "Yêu cầu concierge"
2. Khách đồng ý trả phí concierge: **250K-300K** (cố định, trả cho broker làm job)
3. Bot broadcast lên channel với tag `🎩 CONCIERGE`:
   ```
   🎩 CONCIERGE REQUEST
   🏠 2PN An Thượng, 12tr
   🏠 1PN Sơn Trà, 8tr
   💰 Phí: 300K
   [Nhận job]
   ```
4. Broker bấm "Nhận" → bot release contact khách cho broker đó
5. **Broker tự lo** việc lấy thông tin các căn (liên hệ chủ tin, v.v.)
   - Nếu chủ tin đòi chia hoa hồng mới hợp tác → 2 broker tự thỏa thuận, platform không can thiệp
6. Broker dẫn khách xem các tin đã pick

**Dòng tiền:**
| | Số tiền | Ghi chú |
|---|---|---|
| Phí concierge | 250-300K | Khách → broker làm job |
| Hoa hồng deal (nếu chốt) | 20% cho platform | Broker trả như bình thường |

**Chống gian lận (giống match thường):**
- Khách confirm đã chốt 1 trong các căn concierge
- Broker không trả lời / không xác nhận → warning
- Warning 3 lần → ban

**Lưu ý:**
- Nếu không ai nhận concierge → hoàn tiền khách? → chưa quyết định

## Chưa quyết định
- [ ] Phí/mô hình kinh doanh cho match khách thật (free? thu phí broker? thu phí khách?)
- [ ] Chế tài broker bypass (liên hệ khách ngoài luồng)
- [ ] Bot nhận yêu cầu khách (build sau)
- [ ] Concierge: không ai nhận thì hoàn tiền khách?
