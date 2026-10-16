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

### 6. Khách chọn
- Khách bấm chọn → bot kết nối 2 bên (reveal contact cả 2 chiều)
- 2 broker không được chọn nhận:
  ```
  Khách đã chọn môi giới khác. Cảm ơn anh đã tham gia!
  ```

## Chống bypass
- Contact khách KHÔNG BAO GIỜ xuất hiện trong broadcast, DM cho broker, hay bất kỳ đâu trước khi khách chọn
- Broker chỉ thấy contact khách SAU KHI được khách chọn
- Vi phạm (tìm cách liên hệ khách ngoài luồng) → chưa định nghĩa chế tài, cần quyết định sau

## Chưa quyết định
- [ ] Phí/mô hình kinh doanh cho match khách thật (free? thu phí broker? thu phí khách?)
- [ ] Chế tài broker bypass (liên hệ khách ngoài luồng)
- [ ] Bot nhận yêu cầu khách (build sau)
