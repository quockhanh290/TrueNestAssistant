"""Run the schema migrations once, before the bot and the webapp start.

    python -m db.migrate            (BOT_DB_PATH or config.DB_PATH)

start-all.ps1 calls this after stopping the old processes and before
starting the new ones, so no two processes race on ALTER TABLE and the
webapp never queries a column the bot has not added yet.

Before touching the file it writes a copy with sqlite3's backup API to
<db dir>/backups/ (kept: the newest KEEP_BACKUPS). After migrating it scans
every type-checked column and reports rows holding text where a number
belongs; those rows would refuse updates to that column until fixed.
"""
import datetime
import glob
import os
import sqlite3
import sys

from . import core

KEEP_BACKUPS = 10


def scan_types(conn):
    """[(table, column, n_bad)] for type-checked columns holding values that
    are not real/integer/null."""
    bad = []
    for t, col in core.typed_columns(conn):
        n = conn.execute(
            f'SELECT COUNT(*) FROM "{t}" WHERE typeof("{col}")'
            " NOT IN ('real', 'integer', 'null')").fetchone()[0]
        if n:
            bad.append((t, col, n))
    return bad


def backup(path):
    """Copy the DB next to itself under backups/. Returns the copy's path."""
    if not os.path.exists(path):
        return None
    folder = os.path.join(os.path.dirname(os.path.abspath(path)), "backups")
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.splitext(os.path.basename(path))[0]
    dst_path = os.path.join(folder, f"{base}.pre-migrate-{stamp}.db")
    src = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    old = sorted(glob.glob(os.path.join(folder, f"{base}.pre-migrate-*.db")))
    for p in old[:-KEEP_BACKUPS]:
        try:
            os.remove(p)
        except OSError:
            pass
    return dst_path


def main(path=None):
    import config
    path = path or config.DB_PATH
    copy = backup(path)
    print(f"backup: {copy or '(no DB yet)'}")
    core.init_db(path)
    conn = sqlite3.connect(path)
    try:
        bad = scan_types(conn)
        n_trig = conn.execute("SELECT COUNT(*) FROM sqlite_master"
                              " WHERE type='trigger'").fetchone()[0]
    finally:
        conn.close()
    print(f"migrated: {path} ({n_trig} triggers)")
    for t, col, n in bad:
        print(f"WARNING {t}.{col}: {n} row(s) hold non-numeric values")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
