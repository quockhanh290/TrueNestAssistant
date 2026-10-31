# Zalo Intake Bridge v2

Tài khoản Zalo **phụ** (không dùng tài khoản chính của Khanh) nhận tin
forward 1:1 từ broker. Khác v1 (chuyển tiếp về Telegram), v2 **tự lưu
thẳng vào kho**: tin được gom thành đợt bởi batching engine, đợt đóng
là lưu ngay dạng nháp — broker tự review/xoá/sửa trong kho của họ.
Spec: `BRIDGE_V2.md`.

## Flow

```
broker forward (text/ảnh rời nhau, mọi thứ tự)
  -> zca-js -> normalize -> Batcher JS (batch.js) -> đợt đóng
  -> AUTO-SAVE qua save_cli.py -> bridge_save.py -> listing "draft"
  -> tin báo (quote tin gốc): "✅ Đã lưu vào kho: 2PN Sơn Trà 15tr + 3 ảnh"
Đợt chỉ-ảnh <=5 phút sau lần lưu trước -> hỏi GỘP / MỚI (quote)
  GỘP = thêm ảnh vào căn vừa rồi | MỚI = lưu căn riêng
  10 phút không trả lời -> lưu riêng.
HUY (<=10 phút) = huỷ lần lưu gần nhất. HUY LINK = huỷ liên kết.
```

- Mọi tin báo đều quote tin gốc của broker.
- Lưu lỗi: retry outbox 60s/300s/900s, chỉ báo "đã lưu" khi lưu thật.
- State (đợt đang mở, pending, outbox) persist ở `data/bridge-state.json`.
- Chỉ lưu ẢNH; video/file được đếm và báo "bỏ qua" trong tin báo.
- Trùng căn: vẫn tạo mới; nghi trùng theo hash ảnh thì ghi chú trong
  tin báo để broker review.

## Files

| File | Vai trò |
|---|---|
| `bridge.js` | bootstrap zca-js (QR/credentials), normalize message, tick 1s |
| `core.js` | bộ não: auto-save, hỏi bổ sung, HUY, outbox — test độc lập được |
| `batch.js` | batching engine, port 1:1 từ `../whatsapp_bridge/batch.py` |
| `simulate.js` | bộ 46 case hành vi cho engine JS (`node simulate.js`) |
| `test_core.js` | unit test core với deps giả (`node test_core.js`) |
| `save_cli.py` | one-shot gọi `bridge_save.py` (lưu/append/undo) |
| `db_cli.py` | one-shot pairing (redeem/lookup/unlink) |
| `../bridge_save.py` | đường lưu backend dùng chung (gốc repo) |

## Run

```bash
npm install
node bridge.js --pair   # lần đầu: quét QR bằng tài khoản Zalo phụ
node bridge.js          # các lần sau
```

## One-time bot wiring (Khanh, trong bot.py)

```python
import feat_zalo
app.add_handler(CommandHandler("linkzalo", feat_zalo.cmd_linkzalo))
app.add_handler(CommandHandler("unlinkzalo", feat_zalo.cmd_unlinkzalo))
```

Broker chạy `/linkzalo` trong bot rồi gửi mã `ZN-XXXXXX` cho tài khoản
Zalo nhận tin 1 lần duy nhất.
