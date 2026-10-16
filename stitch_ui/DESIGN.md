# TrueNest Coastal Broker - Design System

> **Nguồn trích xuất**: Google Stitch UI Project `TrueNest Broker Web App` (`projects/12267696760691104739`)

---

## 1. Brand & Style

Hệ thống thiết kế này phục vụ nền tảng quản lý di động đa tốc độ cao dành riêng cho các môi giới căn hộ tại thị trường Đà Nẵng. Phong cách kết hợp tính thực dụng tập trung của Telegram Dark Mode với độ chính xác của một terminal tài chính chuyên nghiệp.

* **Triết lý**: Minimalism kết hợp Low-Contrast Structural Paneling. Chiều sâu được tạo bởi các sắc độ phiến đá và xám ánh xanh, không dùng đổ bóng nhòe truyền thống.
* **Màu sắc chủ đạo**: Nền tối xanh biển sâu `#071420`, điểm nhấn màu xanh Telegram rực rỡ `#2aabee` và `#89ceff`.
* **Phông chữ**:
  * **Headlines**: `Space Grotesk` (hiện đại, kiến trúc, đĩnh đạc)
  * **Body text**: `Geist` (tinh giản, nét chữ rõ ràng trong điều kiện ánh sáng ngoài trời)
  * **Data, Giá tiền & Số phòng**: `JetBrains Mono` (dễ so sánh cột, hiển thị giá `VND/tháng`, mã căn `#B-1402`, diện tích `72 m²`)

---

## 2. Bảng mã màu (Design Tokens)

| Token | Giá trị HEX | Ứng dụng |
| :--- | :--- | :--- |
| **`surface` / `background`** | `#071420` | Nền canvas toàn bộ ứng dụng |
| **`surface-container`** | `#14212d` | Khung thẻ căn hộ, danh sách list tile, modal |
| **`surface-container-high`** | `#1f2b37` | Vùng nhập liệu, dropdown, chip lọc đang hover |
| **`surface-variant`** | `#293643` | Nút bấm phụ, viền thẻ |
| **`outline`** | `#88929b` | Đường kẻ mỏng 1px phân cách các khối nội dung |
| **`primary-container`** | `#2aabee` | Nút hành động chính (CTA), tab đang active, badge nổi bật |
| **`primary`** | `#89ceff` | Màu chữ và icon nhấn mạnh chính |
| **`secondary`** | `#7bdc75` | Trạng thái "Còn trống", thành công, cọc hoàn tất |
| **`tertiary` / `warning`** | `#fabc4c` | Cảnh báo sắp hết hạn hợp đồng, lịch hẹn sắp tới |
| **`error`** | `#ffb4ab` | Hủy phòng, lỗi nhập liệu, xóa |
| **`on-surface`** | `#d7e4f4` | Màu chữ tiêu đề và nội dung chính |
| **`on-surface-variant`** | `#bec8d2` | Màu chữ phụ, mô tả diện tích, quận huyện |

---

## 3. Typography Scale

* **`headline-lg`**: Space Grotesk 32px / 700 (Mobile: 26px / 700)
* **`headline-md`**: Space Grotesk 22px / 600
* **`headline-sm`**: Space Grotesk 18px / 600
* **`body-lg`**: Geist 16px / 400
* **`body-md`**: Geist 14px / 400
* **`body-sm`**: Geist 13px / 400
* **`label-lg`**: JetBrains Mono 14px / 500
* **`label-md`**: JetBrains Mono 12px / 500
* **`label-sm`**: JetBrains Mono 10px / 600 (cho badges, tag trạng thái)

---

## 4. Spacing & Border Radius

* **Spacing**:
  * `space-xs`: `0.25rem` (4px)
  * `space-sm`: `0.5rem` (8px)
  * `space-md`: `0.75rem` (12px)
  * `space-lg`: `1rem` (16px)
  * `space-xl`: `1.5rem` (24px)
* **Radius**:
  * Thẻ căn hộ / containers: `12px - 14px` (`rounded-xl`)
  * Buttons & Inputs: `10px - 12px`
  * Badges & Tags: `6px - 8px`
  * Filter Pills / Avatars: `9999px` (`rounded-full`)
