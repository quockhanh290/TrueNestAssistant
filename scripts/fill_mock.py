"""Fill complete mock data for 3 listings."""
import sqlite3
import json
import os
import random

db_path = os.environ.get("BOT_DB_PATH", "broker_bot.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

MOCK_DATA = {
    "tg:622fd3b0d39a": {  # 10tr, 2PN Hai Chau
        "bedrooms": 2,
        "bathrooms": 2,
        "district": "Hải Châu",
        "area_m2": 80,
        "amenities": ["Wifi", "Pool", "Gym", "Thang máy", "Bảo vệ 24/7"],
        "highlights": ["Sát biển", "Ban công thoáng", "Nội thất gỗ cao cấp"],
        "furnishing": "full",
        "pet_friendly": True,
    },
    "tg:439f581f9320": {  # 20tr, 2PN
        "bedrooms": 2,
        "bathrooms": 2,
        "district": "Sơn Trà",
        "area_m2": 60,
        "amenities": ["Wifi", "Pool", "Gym", "View biển"],
        "highlights": ["Trống ngay", "HĐ 6 tháng"],
        "furnishing": "full",
        "pet_friendly": True,
    },
    "tg:5152369694d2": {  # 18tr, 1PN Son Tra
        "bedrooms": 1,
        "bathrooms": 1,
        "district": "Sơn Trà",
        "area_m2": 45,
        "amenities": ["Wifi", "Thang máy", "Chỗ đậu xe"],
        "highlights": ["Giá tốt", "Yên tĩnh"],
        "furnishing": "full",
        "pet_friendly": False,
    },
}

c.execute("SELECT id, parsed FROM tg_listings")
fixed = 0
for row in c.fetchall():
    lid = row["id"]
    if lid not in MOCK_DATA:
        continue
    try:
        p = json.loads(row["parsed"] or "{}")
    except:
        p = {}
    
    mock = MOCK_DATA[lid]
    p.update(mock)
    
    c.execute(
        "UPDATE tg_listings SET parsed = ?, updated_at = datetime('now') WHERE id = ?",
        (json.dumps(p, ensure_ascii=False), lid)
    )
    print(f"Updated {lid}: {mock['bedrooms']}PN, {mock['district']}, {mock['area_m2']}m2")
    fixed += 1

conn.commit()
conn.close()
print(f"Done. Updated {fixed} listing(s).")
