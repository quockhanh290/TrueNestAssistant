# TODO — TrueNest Assistant Bot
_Cập nhật: 2026-10-16_

## 🔴 Bắt buộc (bot chưa chạy được nếu thiếu)

- [ ] **Tạo bot via BotFather**
  - Mở Telegram → tìm @BotFather → `/newbot`
  - Đặt tên + username → lấy token
  - Chạy trên máy local: `python bot.py` (set `BOT_TOKEN` trong `.env`)

- [ ] **Copy file location catalog** (2.8MB, không push qua API được)
  ```bash
  cd TrueNestAssistant
  cp ~/workspace/user/files/danang_location_catalog.json data/danang_locations.json
  git add data/danang_locations.json
  git commit -m "Add Da Nang location catalog data"
  git push
  ```

## 🟡 Match liên broker

- [ ] **Tạo channel private**
  - Tạo channel Telegram (private)
  - Add bot làm admin (quyền post messages)
  - Lấy channel ID (forward 1 tin từ channel sang @userinfobot)
  - Gửi ID cho Tana → set `BROKER_GROUP_ID`

- [ ] **Test 2 người thật** (sau khi bot chạy)
  - Người 1: đăng 3 tin → vào 🤝 Liên kết broker → đăng nhu cầu
  - Người 2: đăng 2 tin → thấy broadcast → bấm "Tôi có tin" → chọn tin
  - Người 1: nhận DM → bấm "Kết nối"
  - Người 2: bấm "Đồng ý" → cả 2 nhận contact card

## 🟢 Trước khi thu tiền

- [ ] **Điền thông tin thanh toán** (thay 3 placeholder trong `config.py`)
  - `ADMIN_TELEGRAM_ID` — ID Telegram của Khanh (để duyệt yêu cầu premium)
  - `PAYMENT_BANK` — số TK ngân hàng nhận tiền
  - `PAYMENT_MOMO` — số MoMo nhận tiền

## 🔵 Nên làm

- [ ] **BotFather setup**
  - Description, About, Commands (Tana đã soạn draft, Khanh duyệt rồi tự set)

- [ ] **Thêm lệnh `/unban`** (optional)
  - Hiện tại user bị ban vĩnh viễn chỉ mở được bằng tay trong DB
  - Có cần Tana build lệnh `/unban <user_id>` cho Khanh không?

## ✅ Đã xong (không cần làm gì)

- Code bot đầy đủ, đã push lên GitHub
- Test suite: 20/20 pass
- Anti-spam 4 lớp tự động
- Location catalog code (chờ file data ở trên)
