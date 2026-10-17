"""Diagnostic: check DB and listings."""
import sqlite3
import json
import os

db_path = os.environ.get("BOT_DB_PATH", "broker_bot.db")
print(f"DB path: {db_path}")
print(f"Exists: {os.path.exists(db_path)}")
if os.path.exists(db_path):
    print(f"Size: {os.path.getsize(db_path)} bytes")

try:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in c.fetchall()]
    print(f"Tables: {tables}")
    
    if "tg_listings" in tables:
        c.execute("SELECT COUNT(*) FROM tg_listings")
        count = c.fetchone()[0]
        print(f"tg_listings count: {count}")
        
        c.execute("SELECT id, parsed FROM tg_listings LIMIT 5")
        for row in c.fetchall():
            lid, parsed_str = row
            try:
                p = json.loads(parsed_str or "{}")
            except:
                p = {}
            print(f"  {lid}: price={p.get('price_vnd')}, bedrooms={p.get('bedrooms')}, district={p.get('district')}")
    conn.close()
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
