#!/usr/bin/env python3
"""One-shot save CLI for the Zalo bridge (Node.js).

The stateful batching engine lives in JS (batch.js); saving is a single
stateless call into the shared backend (bridge_save.py), so it runs as
this subprocess — the same pattern as db_cli.py.

Usage:
    python3 save_cli.py save --tg 123 --text-file /tmp/t.txt --photos /tmp/dir
    python3 save_cli.py append --listing tg:abc --photos /tmp/dir
    python3 save_cli.py undo --listing tg:abc

Photo dir: image files, sorted by filename = batch order.
Output: one JSON line on stdout.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bridge_save  # noqa: E402


def _photo_datas(photo_dir):
    if not photo_dir or not os.path.isdir(photo_dir):
        return []
    datas = []
    for name in sorted(os.listdir(photo_dir)):
        p = os.path.join(photo_dir, name)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                datas.append(f.read())
    return datas


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save")
    s.add_argument("--tg", type=int, required=True)
    s.add_argument("--text-file", required=True)
    s.add_argument("--photos", default="")
    a = sub.add_parser("append")
    a.add_argument("--listing", required=True)
    a.add_argument("--photos", default="")
    u = sub.add_parser("undo")
    u.add_argument("--listing", required=True)
    args = ap.parse_args()

    try:
        if args.cmd == "save":
            with open(args.text_file, encoding="utf-8") as f:
                text = f.read()
            out = bridge_save.save_bridge_listing(
                args.tg, text, _photo_datas(args.photos), source="zalo")
        elif args.cmd == "append":
            out = bridge_save.append_photos_to_listing(
                args.listing, _photo_datas(args.photos))
            out = {"ok": True, **out}
        else:
            out = {"ok": bridge_save.undo_bridge_listing(args.listing)}
        print(json.dumps(out, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001 - bridge must get JSON, not a traceback
        print(json.dumps({"ok": False, "error": str(e)[:200]}))


if __name__ == "__main__":
    main()
