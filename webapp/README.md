# TrueNest Broker WebApp

Web app mở trong Telegram cho broker quản lý căn hộ: xem danh sách,
tìm kiếm/lọc, sửa thông tin, xem/sửa bài đăng đa ngôn ngữ.

## Chạy thử

```bash
cd ~/workspace/broker-bot
python webapp/server.py
# -> http://localhost:8080
```

Mở trên trình duyệt (chế độ mobile) để test:

```
http://localhost:8080/?demo=1&broker_id=<TELEGRAM_USER_ID>
```

`demo=1` bỏ qua xác thực Telegram, dùng `broker_id` thật từ DB.

## Kết nối với bot

1. Set env `WEBAPP_URL` = URL public của webapp (Telegram yêu cầu **HTTPS**).
2. Trong `utils.py`, `MENU_KB` đã có nút `🌐 Quản lý căn (Web)` dùng
   `WEBAPP_URL` (mặc định `http://localhost:8080` cho dev).
3. Khi broker bấm nút, Telegram mở webapp và truyền `initData`;
   server xác thực bằng `BOT_TOKEN` rồi lấy `user.id` làm `broker_id`.

Env:

| Biến           | Mặc định                | Mô tả                              |
|----------------|-------------------------|------------------------------------|
| `WEBAPP_PORT`  | `8080`                  | Port server lắng nghe               |
| `WEBAPP_URL`   | `http://localhost:8080` | URL public (bot dùng cho nút web_app) |
| `BOT_DB_PATH`  | `broker_bot.db`         | Đường dẫn SQLite (qua `config.py`) |
| `BOT_TOKEN`    | _(trống)_               | Token bot, để validate initData     |

## API

Tất cả endpoint JSON. Xác thực: header `X-Telegram-Init-Data`
(Telegram WebApp SDK tự có), hoặc `?demo=1&broker_id=X` khi dev.

| Method | Path                        | Mô tả                                      |
|--------|-----------------------------|--------------------------------------------|
| GET    | `/api/health`               | Health check                               |
| GET    | `/api/listings`             | Danh sách căn. Query: `q`, `bedrooms` (`studio`/`1`/`2`/`3`/`4+`), `status`, `limit`, `offset` |
| GET    | `/api/listing/<id>`         | Chi tiết 1 căn + `post_langs`              |
| PUT    | `/api/listing/<id>`         | Sửa field. Body: `{"fields": {"price_vnd": 12500000, ...}}` |
| PUT    | `/api/listing/<id>/status`  | Đổi trạng thái. Body: `{"status": "rented"}` |
| GET    | `/api/post/<id>?lang=vi`    | Lấy bài đăng theo ngôn ngữ                 |
| PUT    | `/api/post/<id>`            | Lưu bài đăng. Body: `{"lang": "vi", "text": "..."}` |

Field sửa được qua `PUT /api/listing/<id>`: `price_vnd`, `bedrooms`,
`bathrooms`, `area_m2`, `district`, `street`, `building_name`,
`furnished`, `pet_friendly`, `deposit`, `description`.

## Cấu trúc

```
webapp/
├── README.md        # file này
├── server.py        # stdlib http.server — serve static + route /api/*
├── api.py           # logic API, gọi db.py của bot (không duplicate SQL)
└── static/
    ├── index.html   # shell: list / detail / edit / post-edit views
    ├── style.css    # Telegram dark theme, mobile-first
    └── app.js       # vanilla JS, Telegram WebApp SDK
```

Không có dependency ngoài stdlib. Ảnh listing dùng placeholder
(Telegram `file_id` không render được trên web khi chưa có file server).
