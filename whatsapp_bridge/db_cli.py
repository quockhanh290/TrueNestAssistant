#!/usr/bin/env python3
"""CLI for the WhatsApp bridge to access pairing/linking via the db package.

Usage:
    python3 db_cli.py redeem <CODE> <PHONE> [WA_NAME]
    python3 db_cli.py lookup <PHONE>
    python3 db_cli.py unlink <PHONE>

All output is a single JSON line on stdout.
"""
import json
import sys

sys.path.insert(0, "..")

from db import whatsapp as wam  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        print(json.dumps({"ok": False, "error": "usage"}))
        return
    cmd = sys.argv[1]
    try:
        if cmd == "redeem":
            code, phone = sys.argv[2], sys.argv[3]
            wa_name = sys.argv[4] if len(sys.argv) > 4 else ""
            print(json.dumps(wam.redeem_wa_pairing_code(code, phone, wa_name)))
        elif cmd == "lookup":
            phone = sys.argv[2]
            tg_id = wam.get_telegram_id_by_phone(phone)
            print(json.dumps({"ok": True, "telegram_id": tg_id}))
        elif cmd == "unlink":
            phone = sys.argv[2]
            print(json.dumps({"ok": wam.unlink_whatsapp(phone)}))
        else:
            print(json.dumps({"ok": False, "error": "unknown_cmd"}))
    except Exception as e:  # noqa: BLE001 - bridge must never crash on DB errors
        print(json.dumps({"ok": False, "error": str(e)[:200]}))


if __name__ == "__main__":
    main()
