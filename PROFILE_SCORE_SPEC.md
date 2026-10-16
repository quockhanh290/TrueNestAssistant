# Broker Profile Score — Spec (triển khai sau)

_Quyết định: 2026-10-16, Khanh đồng ý_

## Công thức (4 yếu tố)

```
Điểm (0-100) =
  40% × chất lượng tin (TB completeness score)
+ 25% × độ tươi tin (% tin cập nhật trong 7 ngày)
+ 20% × tốc độ phản hồi match
+ 15% × hoạt động pipeline (% khách có cập nhật trong 14 ngày)
```

## Chi tiết từng yếu tố

### 1. Chất lượng tin (40%)
- TB `completeness_score` của tất cả tin active
- Đã implement

### 2. Độ tươi tin (25%)
- % tin active có `updated_at` trong 7 ngày qua
- Đã implement

### 3. Tốc độ phản hồi match (20%) — CHƯA LÀM
- Đo: thời gian từ khi broker nhận thông báo match → khi broker phản hồi
- < 1 giờ → 100 điểm
- 1-6 giờ → 75 điểm
- 6-24 giờ → 50 điểm
- > 24h hoặc không phản hồi → 0 điểm
- Tính TB của 10 match gần nhất
- Chưa có match nào → không tính vào điểm (chia lại tỷ trọng)

### 4. Hoạt động pipeline (15%) — CHƯA LÀM
- % khách có thay đổi trạng thái trong 14 ngày qua
- Đo độ "chăm khách" thật, không fake được bằng nhập liệu ồ ạt

## Hiển thị cho broker

```
📊 Điểm uy tín: 78/100

📝 Chất lượng tin: 85/100
🔄 Độ tươi: 65/100
⚡ Phản hồi match: 90/100 (TB 45 phút)
👥 Chăm khách: 70/100

💡 Điểm cao → ưu tiên match khách thật
```

## Match khách thật (phase sau)

1. Engine match tin theo yêu cầu khách
2. Group tin trùng (cùng tòa + PN + giá ±10%) → mỗi group chỉ lấy broker điểm cao nhất
3. Xếp hạng: `điểm match tin × điểm hồ sơ`
4. Bot gửi cho top 3 broker

## Cold start → Full score

**Giai đoạn 1 (broker mới):**
- Điều kiện: < 30 ngày HOẶC < 15 listings
- Chỉ tính 2 yếu tố: chất lượng tin (60%) + độ tươi (40%)

**Giai đoạn 2 (đủ điều kiện):**
- Điều kiện: ≥ 30 ngày VÀ ≥ 15 listings
- Tính cả 4 yếu tố theo công thức đầy đủ

**Onboarding nói rõ từ đầu:**
```
💎 Điểm uy tín của anh hiện tính theo 2 yếu tố
   (chất lượng tin + độ tươi).

   Sau 30 ngày và 15 tin → hệ thống tính thêm
   tốc độ phản hồi + độ chăm khách.
   Điểm càng cao → càng được ưu tiên match khách thật.
```

## Normalize khi match

Vấn đề: broker 5 tin (điểm 85, 2 yếu tố) vs broker 50 tin
(điểm 78, 4 yếu tố) — không so trực tiếp được.

**Giải pháp: percentile theo cohort**

1. Chia 2 nhóm:
   - Nhóm mới: < 30 ngày hoặc < 15 listings
   - Nhóm chuẩn: ≥ 30 ngày và ≥ 15 listings

2. Trong mỗi nhóm, xếp percentile:
   - Broker ở percentile 90 = top 10% của nhóm mình

3. Khi match: so sánh percentile, không so điểm thô
   - Broker mới percentile 85 vs broker chuẩn percentile 70
     → broker mới được ưu tiên (dù điểm thô thấp hơn)

**Tại sao:** công bằng cho broker mới giỏi, không bị chôn vùi
dưới broker cũ điểm cao do có nhiều data hơn.
