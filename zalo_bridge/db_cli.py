#!/usr/bin/env python3
"""CLI for the Zalo bridge (Node.js) to access pairing/linking via the db package.

Usage:
    python3 db_cli.py redeem <CODE> <ZALO_ID> [ZALO_NAME]
    python3 db_cli.py lookup <ZALO_ID>
    python3 db_cli.py unlink <ZALO_ID>

All output is a single JSON line on stdout.
"""
import json
import sys

sys.path.insert(0, "..")

import db as dbm  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        print(json.dumps({"ok": False, "error": "usage"}))
        return
    cmd = sys.argv[1]
    try:
        if cmd == "redeem":
            code, zalo_id = sys.argv[2], sys.argv[3]
            zalo_name = sys.argv[4] if len(sys.argv) > 4 else ""
            print(json.dumps(dbm.redeem_pairing_code(code, zalo_id, zalo_name)))
        elif cmd == "lookup":
            zalo_id = sys.argv[2]
            tg_id = dbm.get_telegram_id(zalo_id)
            print(json.dumps({"ok": True, "telegram_id": tg_id}))
        elif cmd == "unlink":
            zalo_id = sys.argv[2]
            print(json.dumps({"ok": dbm.unlink_zalo(zalo_id)}))
        else:
            print(json.dumps({"ok": False, "error": "unknown_cmd"}))
    except Exception as e:  # noqa: BLE001 - bridge must never crash on DB errors
        print(json.dumps({"ok": False, "error": str(e)[:200]}))


if __name__ == "__main__":
    main()
