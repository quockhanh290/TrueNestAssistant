# TrueNest Assistant — Telegram Broker Bot ("Linh")

Trợ lý quản lý tin cho thuê miễn phí cho môi giới Đà Nẵng.
Trojan horse để xây nguồn listing riêng, cập nhật mỗi ngày.

## Setup

1. Tạo bot với [@BotFather](https://t.me/BotFather) trên Telegram, lấy token.

2. Cài đặt:
```bash
pip install -r requirements.txt
```

3. Chạy:
```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-..."
python bot.py
```

Database SQLite tự tạo ở `broker_bot.db` (đổi qua `BOT_DB_PATH`).

## Chạy nudge availability mỗi ngày

```bash
# cron: 0 9 * * * cd /path/to/broker-bot && python nudge.py
python nudge.py --days 7 --dry-run   # chỉ in, không gửi
```

## Cấu trúc

- `bot.py` — bot "Linh" (python-telegram-bot v21, polling)
- `db.py` — SQLite: brokers, tg_listings, tg_events
- `parser.py` — regex parser tin rao tiếng Việt
- `nudge.py` — script nhắc availability cho tin cũ
- `config.py` — policy (rate limit, số ảnh tối thiểu...)

## Nguyên tắc thiết kế

- Bot KHÔNG bao giờ lộ link web cho brokers.
- Tối đa 2 câu hỏi khi thiếu thông tin, ưu tiên nút bấm.
- "Reflective listening": kể lại những gì hiểu được, để broker tự sửa.
- Giọng tự nhiên, gọi broker là "anh", tên bot là Linh.
