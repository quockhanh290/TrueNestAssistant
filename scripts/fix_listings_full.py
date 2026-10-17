"""Fix listings: fill missing data + random amenities/highlights.
Run on Windows: python fix_listings_full.py
"""
import sqlite3
import json
import os
import random

db_path = os.environ.get("BOT_DB_PATH", "broker_bot.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

AMENITIES_POOL = [
    "Wifi", "Pool", "Gym", "Thang máy", "Bảo vệ 24/7",
    "Chỗ đậu xe", "Sân thượng", "View sông Hàn", "View biển",
    "Gần chợ", "Gần trường học", "Nội thất cao cấp", "Máy lạnh",
    "Máy giặt", "Bếp đầy đủ", "Ban công", "Sát biển",
]

HIGHLIGHTS_POOL = [
    "Trống ngay", "HĐ 6 tháng", "HĐ 1 năm", "Sắp trống",
    "Giá tốt", "Vị trí đẹp", "Yên tĩnh", "Mới renovate",
]

c.execute("SELECT id, parsed FROM listings")
fixed = 0
for row in c.fetchall():
    lid = row["id"]
    try:
        p = json.loads(row["parsed"] or "{}")
    except:
        p = {}

    price = p.get("price_vnd")
    updated = False

    # Fix listing 1: 10tr, missing bedrooms
    if price == 10000000 and p.get("bedrooms") is None:
        p["bedrooms"] = 2
        p["district"] = "Hải Châu"
        p["area_m2"] = 80
        updated = True
        print(f"Fixed {lid}: 2PN, Hải Châu, 80m²")

    # Add random amenities if missing
    if not p.get("amenities"):
        p["amenities"] = random.sample(AMENITIES_POOL, k=random.randint(3, 5))
        updated = True

    # Add random highlights if missing
    if not p.get("highlights"):
        p["highlights"] = random.sample(HIGHLIGHTS_POOL, k=random.randint(1, 2))
        updated = True

    if updated:
        c.execute(
            "UPDATE listings SET parsed = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(p, ensure_ascii=False), lid)
        )
        fixed += 1

conn.commit()
conn.close()
print(f"Done. Updated {fixed} listing(s).")
