"""Who owns an id. One lookup per id kind, used by the webapp's ownership
layer (webapp/server.py) for every route parameter and body field that
names a listing, client, viewing, deal or share page."""
from .core import connect

# kind -> (table, id column). broker_id is the owner column in all of them.
OWNER_TABLES = {
    "listing": ("tg_listings", "id"),
    "client": ("clients", "id"),
    "viewing": ("viewings", "id"),
    "deal": ("deals", "id"),
    "share": ("share_pages", "token"),
}


def owner_of(kind, ident, path=None):
    """broker_id owning `ident`, or None when it does not exist."""
    table, col = OWNER_TABLES[kind]
    if not isinstance(ident, str) or not ident:
        return None
    conn = connect(path)
    try:
        row = conn.execute(
            f"SELECT broker_id FROM {table} WHERE {col} = ?", (ident,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()
