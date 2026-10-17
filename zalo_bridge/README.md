# Zalo → Telegram Bridge

Tài khoản Zalo nhận tin (nick phụ) → forward listing về Telegram broker qua bot Linh.

## Luồng

1. Broker chat bot Linh trên Telegram → `/linkzalo` → nhận mã `ZN-XXXXXX` (15 phút, 1 lần).
2. Broker gửi mã vào Zalo cho tài khoản nhận tin → liên kết `zalo_id ↔ telegram_id`.
3. Broker forward tin listing vào Zalo → bridge parse → gửi qua Telegram → broker xác nhận theo luồng intake bình thường.
4. Gửi `HUY LINK` vào Zalo để hủy liên kết.

## Cài đặt (máy Windows của Khanh)

```powershell
cd D:\TrueNest\TrueNestAssistant\zalo_bridge
npm install
node bridge.js --pair   # quét QR bằng app Zalo của nick PHỤ (không dùng nick chính)
node bridge.js          # chạy bình thường
```

- Credentials lưu ở `zalo_bridge/data/zalo-credentials.json` (0600).
- Bridge gọi `db_cli.py` để đọc/ghi pairing + mapping qua `db` package (đúng luật architecture).
- Gửi Telegram qua Bot API trực tiếp, dùng token trong `token.txt`.

## An toàn

- Chỉ nhận DM 1:1 (`ThreadType.User`), bỏ qua group.
- Người lạ chưa link: chỉ nhận 1 tin hướng dẫn/giờ, tin listing không đi đâu.
- Rate limit 20 tin/phút/người gửi, vượt thì drop im lặng.
- Ảnh: hiện tại chỉ đếm số ảnh; tải + forward ảnh sẽ thêm ở bước sau.

## Lưu ý

- Dùng nick Zalo phụ riêng. Không chạy bằng nick chính.
- Cho broker kết bạn với acc nhận trước để giảm nguy cơ bị Zalo soi.
- Tăng dần số broker, đừng ồ ạt ngày đầu.
