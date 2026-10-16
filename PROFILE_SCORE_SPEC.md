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

## Lưu ý
- Cold start: broker mới chỉ tính từ chất lượng tin (2 yếu tố đầu)
- Không hiển thị điểm của người khác
- Strike/ban không ảnh hưởng điểm uy tín (2 hệ thống riêng)
