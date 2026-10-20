# TrueNest Bridge V2 — Brief

> Spec chung cho 2 intake bridge (WhatsApp + Zalo). Logic nằm ở backend
> (`api.py`); bridge chỉ là cửa trước hội thoại, ngang hàng với bot
> Telegram và mini app. Broker làm mọi thứ trong app của họ — không
> app-hopping. Telegram chỉ còn: setup một lần (mã pairing) + app chính.

## 1. Linking (chung)

- Mã pairing `WA-XXXXXX` / `ZN-XXXXXX`: 6 ký tự rõ ràng, dùng 1 lần, hết
  hạn 15 phút, mỗi broker chỉ 1 mã hiệu lực tại 1 thời điểm.
- Mapping: `phone/zalo_id → telegram_id`. Unlink: gửi `HUY LINK` trên
  chính kênh đó.
- Người chưa link: hướng dẫn pairing, tối đa 1 lần/giờ (không spam).

## 2. Pipeline sự kiện (chung)

```
event nền tảng → chuẩn hoá Event → Batcher (theo người gửi, tick 1s)
→ action → phản hồi trên kênh → flush → thẻ xác nhận
→ broker xác nhận → backend (api.py + photos.py: dHash/pHash + R2)
```

- Batcher đã được chứng minh với **49 sim case** (xem `simulate.py`):
  forward block, text/ảnh trước-sau mọi thứ tự, chỉ text, chỉ ảnh,
  bổ sung trong 5 phút, forward 3 căn liền nhau, ghi chú chen giữa,
  BO/LUU, re-forward, reaction, pairing, trần 180s, 2 broker đồng thời,
  tin chat lẻ, webhook retry, ảnh/video/audio/PDF/location pin,
  thu hồi tin, dedup ảnh-text trùng, HUY LINK giữa đợt, 1 tin dán 2 căn
  (cờ `is_multi`), album 30 ảnh, sticker.
- Luật đóng đợt: text listing thứ 2 (KHÁC) → tách; text trùng → bỏ;
  LUU → đóng + lưu ngay; BO → huỷ; im lặng 15s → đóng; trần 180s → đóng.
- Bổ sung: đợt chính auto-save; riêng **đợt ảnh đến sau** (chỉ ảnh,
  trong 5 phút sau lần flush trước) thì **cần xác nhận** vì mơ hồ —
  có thể là ảnh của căn vừa rồi, căn mới, hoặc rác. WhatsApp: nút bấm
  [Gộp vào căn vừa rồi] [Căn mới]. Zalo: quoted question + từ khoá
  `GỘP` / `MỚI`. Không trả lời sau 10 phút → mặc định lưu thành mục
  riêng (không mất ảnh), broker xử lý tiếp lúc review trong kho.
- Đợt có text listing riêng → luôn là căn mới, không bao giờ bị gộp oan.

## 3. Receipt UX (chung)

- Reaction ✅ ngay trên tin của broker khi nhận (không spam tin nhắn).
- Thẻ xác nhận **quoted** (trả lời trích dẫn tin gốc): tóm tắt
  "2PN Sơn Trà 15tr + 13 ảnh" + hành động xác nhận.
- Không có đếm trực tiếp trên tin gốc (WhatsApp/Zalo đều không hỗ trợ).

## 4. WhatsApp bridge (Python — branch `feat-whatsapp-bridge`)

- Official Cloud API. Webhook `127.0.0.1:8090/wa-webhook`:
  GET = verify handshake, POST = events (threaded).
- Env: `WA_ACCESS_TOKEN`, `WA_PHONE_NUMBER_ID`, `WA_VERIFY_TOKEN`.
  Bot token đọc từ `token.txt` (gitignored).
- Engine: `batch.py` (Python) + vòng tick 1s.
- Xác nhận: **nút bấm native** [Lưu vào kho] [Bỏ qua] (tối đa 3 nút,
  title ≤ 20 ký tự — payload builder `build_interactive_payload`,
  parse `parse_button_reply`).
- Tải ảnh: `GET /{media_id}` → URL tạm → bytes → đưa backend
  (`photos.py`: dHash + pHash + R2 `truenest-images`, prefix `broker/`).
- Caption WhatsApp nằm trên event ảnh đầu — engine đã chứng minh đúng
  với caption ở mọi vị trí, không phụ thuộc giả định này.
- Chi phí: tin vào miễn phí; reply trong 24h ~150đ/tin sau 1.000 tin
  miễn phí/tháng/số. Business verification không cần ở quy mô của mình.

## 5. Zalo bridge (Node.js — branch `feat-zalo-bridge`)

- zca-js, tài khoản **receiver riêng** (không dùng tài khoản chính của
  Khanh), chỉ 1:1 DM (`ThreadType.User`).
- Engine: **port 1:1 sang JS** (`batch.js`), dùng đúng bộ 49 sim case
  làm test suite để đảm bảo hành vi giống hệt bản Python.
- Xác nhận: Zalo personal **không có nút bấm** → **AUTO-SAVE** (Khanh
  chốt 2026-10-20): đợt đóng là lưu ngay vào kho, không hỏi trước.
  Lý do: broker tự quyết định giữ/xoá/sửa khi review lại tin trong hệ
  thống của họ. Lưới an toàn: nhắn `HUY` trong 10 phút để huỷ lần lưu
  vừa rồi; để lâu hơn thì xoá trong kho như thường.
- Đợt ảnh đến sau (chỉ ảnh, ≤5 phút sau lần lưu trước) → **cần xác
  nhận**: quote hỏi + từ khoá `GỘP` (gộp vào căn vừa rồi) / `MỚI`
  (lưu căn riêng); 10 phút không trả lời → mặc định lưu riêng.
- Quote: dựng từ event thật (đủ 7 field: content, msgType, propertyExt,
  uidFrom, msgId, cliMsgId, ts, ttl).
- Thu hồi tin (undo event) → event `retract` → gỡ khỏi đợt đang mở.
- Lưu kho: bridge.js tải bytes ảnh → gọi **helper Python one-shot
  (stateless)** gọi backend; engine giữ state trong JS.

## 6. Tại sao không dùng Python cho bridge Zalo?

1. **zca-js chỉ tồn tại cho Node.js** — không có thư viện Python nào còn
   được duy trì để bắt event Zalo realtime. Cả inbox adapter cũng dùng
   zca-js. Process bắt sự kiện buộc phải là Node.
2. **Engine là stateful** (đợt đang mở, seen ids, supp_mode, tick 1s).
   Tách thành Python daemon + HTTP IPC thêm 1 process trên máy Khanh,
   thứ tự khởi động, lỗi IPC — mà state vẫn mất khi daemon restart
   (không bền hơn gì). Không được lợi gì.
3. **Port ~350 dòng sang JS là 1 lần**, và bộ 49 sim case thành test
   suite của bản port → hành vi đảm bảo giống hệt. Khi cần backend thì
   gọi Python one-shot (stateless, không giữ state).
4. Vận hành: `start-all.ps1` chỉ khởi động `bridge.js` như cũ, không
   thêm process mới.

## 7. Giới hạn đã biết (v2.x)

- Ghi âm → cần speech-to-text, chưa có trong v2.
- Ảnh 2 căn khác nhau trộn trong 1 đợt → về nguyên tắc không phân biệt
  nổi; thẻ confirm là lưới an toàn (broker tự nhìn trước khi lưu).
- `is_multi` (1 tin dán 2 căn) → thẻ confirm cảnh báo, hỏi broker tách.

## 8. Test thật còn thiếu (chỉ làm được sau khi v2 tồn tại)

- Nút bấm/quote hiển thị trên máy broker như thế nào.
- Số test free của Meta cho WhatsApp; tài khoản receiver cho Zalo.

## 9. Quyết định bổ sung (Khanh chốt 2026-10-20)

- **Luật quote (chung):** mọi tin báo của bridge (đã lưu, thất bại, hỏi
  bổ sung, nhắc xác nhận, hướng dẫn) đều **quoted vào tin gốc của broker**.
  Không quote = broker không biết tin nào được nhắc tới.
- **Lưu thất bại:** bridge giữ hàng chờ retry cục bộ; chỉ gửi "đã lưu"
  sau khi lưu thành công thật. Retry hết cỡ vẫn lỗi → nhắn
  (quoted vào đợt đó): "Không lưu được đợt này — gửi lại giúp em nhé".
- **Persist đợt đang mở:** state engine (đợt mở, seen ids, supp_mode)
  ghi xuống DB; bridge restart là khôi phục, không mất tin đang gom.
- **Nhận ảnh thôi:** engine vẫn gom video/audio/PDF/location để báo cáo
  đúng ("bỏ qua 1 video"), nhưng **bước lưu chỉ lấy ảnh**. Không âm thầm
  lưu media loại khác vào listing.
- **Trùng căn lúc lưu (Zalo auto-save):** luôn **tạo mới**; nếu dedup
  nghi trùng → tin báo đã lưu ghi thêm "có vẻ trùng với [tóm tắt căn
  cũ] — vào kho kiểm tra giúp em". Broker tự xử lúc review.
- **GỘP = căn gần nhất**; câu hỏi quote kèm tóm tắt căn đó.
- **is_multi (1 tin dán 2 căn):** lưu nguyên + cảnh báo trong tin báo
  "có vẻ chứa 2 căn — vào kho tách giúp em".
- **HUY:** chỉ huỷ **lần lưu gần nhất**, trong 10 phút. Quá 10 phút →
  trả lời (quoted): "quá hạn huỷ nhanh rồi, vào kho xoá giúp em nhé".
- **WhatsApp không bấm Lưu/Bỏ qua:** nhắc 1 lần sau 1 giờ (quoted vào
  thẻ xác nhận); chưa bấm = chưa lưu.
