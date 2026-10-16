"""Contextual hints for TrueNest broker bot (Linh).

First-time feature explanations + proactive tips after key events.
Hints are dismissible and never blocking — no locks, no gates.

Usage:
    from hints import should_show_hint, get_hint_text, mark_seen
    if should_show_hint(uid, "clients"):
        # show hint with [Bắt đầu →] button
        ...
"""

import db

# ------------------------------------------------------------------
# First-time feature hints
# key -> display text shown on first tap of that feature
# ------------------------------------------------------------------
HINTS = {
    "write": (
        "✍️ <b>Viết bài đăng</b>\n\n"
        "Chọn 1 căn để xem, sửa hoặc copy bài đăng FB.\n"
        "Bài tiếng Việt được tạo tự động mỗi khi anh thêm căn mới."
    ),
    "clients": (
        "👥 <b>Khách hàng</b>\n\n"
        "Đây là nơi quản lý khách thuê.\n"
        "Anh thêm khách + nhu cầu tìm nhà, em sẽ tự gợi ý căn phù hợp."
    ),
    "viewings": (
        "📅 <b>Lịch xem nhà</b>\n\n"
        "Đặt lịch xem nhà với khách ở đây.\n"
        "Em sẽ nhắc trước giờ hẹn để anh không quên."
    ),
    "deals": (
        "💰 <b>Hoa hồng</b>\n\n"
        "Theo dõi hoa hồng từ các deal đã chốt.\n"
        "Em tính 20% platform tự động, anh chỉ cần up bill."
    ),
    "match": (
        "🤝 <b>Liên kết broker</b>\n\n"
        "Kết nối với broker khác để trao đổi tin.\n"
        "Tìm căn cho khách của nhau, chia hoa hồng tự thỏa thuận."
    ),
    "templates": (
        "💬 <b>Mẫu tin nhắn</b>\n\n"
        "Mẫu tin nhắn dùng nhanh cho các tình huống thường gặp.\n"
        "Tạo sẵn để gửi cho khách chỉ với 1 chạm."
    ),
    "premium": (
        "💎 <b>Gói Pro</b>\n\n"
        "Mở khóa: tìm kiếm nâng cao bằng ngôn ngữ tự nhiên,\n"
        "bài đăng đa ngôn ngữ (Hàn/Trung/Nga), gợi ý tự động."
    ),
    "profile": (
        "📊 <b>Hồ sơ</b>\n\n"
        "Điểm uy tín của anh dựa trên chất lượng\n"
        "và độ mới của tin đăng. Càng chăm cập nhật, điểm càng cao."
    ),
}

# Map menu callback_data -> hint key
MENU_HINT_MAP = {
    "menu:write": "write",
    "menu:clients": "clients",
    "menu:viewings": "viewings",
    "menu:deals": "deals",
    "menu:match": "match",
    "menu:templates": "templates",
    "menu:premium": "premium",
    "menu:profile": "profile",
}


def should_show_hint(broker_id, hint_key):
    """True if this broker hasn't seen this hint yet."""
    return hint_key not in db.get_seen_hints(broker_id)


def get_hint_text(hint_key):
    """Return the hint text for a key, or None if unknown."""
    return HINTS.get(hint_key)


def mark_seen(broker_id, hint_key):
    """Record that the broker has seen this hint."""
    db.mark_hint_seen(broker_id, hint_key)


# ------------------------------------------------------------------
# Proactive tips (sent once after key milestones)
# ------------------------------------------------------------------
def tip_after_listing(count):
    """Return tip text after a listing is saved, or None.

    Only fires on exact milestone counts (1st and 5th).
    """
    if count == 1:
        return (
            "✅ Đã lưu! 💡 Bấm ✍️ <b>Viết bài đăng</b> "
            "để em tạo bài FB cho căn này nhé"
        )
    if count == 5:
        return (
            "🎉 5 căn rồi! Thử 👥 <b>Khách hàng</b> "
            "để em gợi ý căn phù hợp cho từng khách nhé"
        )
    return None


def tip_after_client(count):
    """Return tip text after a client is added, or None.

    Only fires on the 1st client.
    """
    if count == 1:
        return (
            "✅ Đã thêm khách! Đặt 📅 <b>Lịch xem</b> "
            "để không quên hẹn nhé"
        )
    return None
